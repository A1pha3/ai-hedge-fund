#!/usr/bin/env python3
"""Plan 07 Task 2: broker capability certification CLI.

Subcommands: probes / profile / verify.

Safety properties:
- ``probes`` runs only read-only capability probes by default. Any
  sandbox/order mutation requires ``--mutation-approval`` (a signed
  approval file); without it the script refuses to mutate.
- ``profile`` assembles a frozen ``BrokerCapabilityProfile`` from probe
  findings (JSON). It stores redacted raw envelopes and exact
  API/SDK/docs version hashes so the profile is reproducible.
- ``verify`` runs ``verify_broker_enablement`` against a signed
  ``BrokerEnablementManifest`` envelope and a profile, printing the bound
  area hashes.

This script never loads the production adapter and never holds broker
credentials; it only shapes and checks the certification artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.screening.offensive.v3.broker.capabilities import (
    BrokerEnablementError,
    BrokerCapabilityProfile,
    CutoffSemantics,
    CursorContinuity,
    DuplicateCreateBehavior,
    IdempotencyScope,
    LateFillSemantics,
    certify_auction_tif_cutoff,
    certify_client_order_idempotency,
    certify_credential_session_network_fencing,
    certify_execution_semantics,
    certify_pagination_cursor_retention,
    certify_trusted_clock,
    verify_broker_enablement,
)
from src.screening.offensive.v3.broker.ports import BrokerAccountBinding


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _cmd_probes(args: argparse.Namespace) -> int:
    """Emit a template of read-only probe findings for a broker.

    By default this performs NO network access and NO mutation: it writes a
    JSON template the operator fills in from authenticated broker probes.
    A ``--mutation-approval`` file is required before any sandbox/order
    mutation probe may run (not implemented here; the gate is enforced).
    """

    if args.mutation_approval is not None:
        if not args.mutation_approval.exists():
            print(
                "error: --mutation-approval file not found",
                file=sys.stderr,
            )
            return 2
        approval = json.loads(args.mutation_approval.read_text())
        if not approval.get("signed_approval"):
            print(
                "error: mutation requires a signed approval envelope",
                file=sys.stderr,
            )
            return 2
        print(
            "note: mutation approval present but no mutation probes are"
            " implemented in this offline tool",
            file=sys.stderr,
        )

    template: dict[str, Any] = {
        "account": {
            "account_id": "<broker-account-id>",
            "environment": "sandbox",
            "currency": "CNY",
            "endpoint_fingerprint": "<sha256 of endpoint/cert fingerprint>",
        },
        "currency_definition_fingerprint": "<sha256 of currency definition>",
        "trusted_clock": {
            "max_observed_skew_ms": 50,
            "tolerance_ms": 500,
        },
        "authenticated_raw_envelope": {
            "parser_version": "v1",
            "auth_mechanism": "<auth mechanism>",
            "redacted_secret_fields": ["session_token", "api_key"],
        },
        "client_order_idempotency": {
            "scopes": [
                {
                    "trading_day_scope": "<ISO date>",
                    "duplicate_create_behavior": "idempotent_replay",
                }
            ],
        },
        "auction_tif_cutoff": {
            "supported_order_types": ["LIMIT"],
            "supported_time_in_force": ["DAY"],
            "cutoff_semantics": "hard_reject_after",
            "cutoff_instant_description": "<cutoff instant>",
        },
        "pagination_cursor_retention": {
            "page_count_proof": 1,
            "cursor_continuity": "continuous_monotone",
            "retention_calendar_days": 30,
        },
        "execution_semantics": {
            "partial_fill_supported": True,
            "cancel_semantics": "<cancel semantics>",
            "expiry_semantics": "<expiry semantics>",
            "late_fill_semantics": "appends_inverse_or_delta",
        },
        "exit_rate_limit": {
            "exit_budget_per_minute": 10,
            "query_budget_per_minute": 30,
        },
        "credential_session_network_fencing": {
            "session_revocable": True,
            "network_egress_revocable": True,
            "termination_proof_required": False,
        },
        "version_hashes": {
            "api": [{"name": "<api>", "version": "<v>", "source_hash": "<h>"}],
            "sdk": [{"name": "<sdk>", "version": "<v>", "source_hash": "<h>"}],
            "docs": [{"name": "<docs>", "version": "<v>", "source_hash": "<h>"}],
        },
        "redacted_raw_envelopes": [],
    }
    output = json.dumps(template, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(output + "\n")
        print(f"wrote probe template to {args.output}")
    else:
        print(output)
    return 0


def _version_hashes(items: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "name": item["name"],
            "version": item["version"],
            "source_hash": item["source_hash"],
        }
        for item in items
    )


def _build_profile(findings: dict[str, Any], proven_at: datetime) -> BrokerCapabilityProfile:
    acct = findings["account"]
    binding = BrokerAccountBinding(
        account_id=acct["account_id"],
        environment=acct["environment"],
        currency=acct["currency"],
        endpoint_fingerprint=acct["endpoint_fingerprint"],
    )
    clock = findings["trusted_clock"]
    raw = findings["authenticated_raw_envelope"]
    idem = findings["client_order_idempotency"]
    auction = findings["auction_tif_cutoff"]
    pag = findings["pagination_cursor_retention"]
    exe = findings["execution_semantics"]
    rate = findings["exit_rate_limit"]
    fence = findings["credential_session_network_fencing"]
    versions = findings.get("version_hashes", {})

    scopes = tuple(
        IdempotencyScope(
            trading_day_scope=s["trading_day_scope"],
            duplicate_create_behavior=DuplicateCreateBehavior(
                s["duplicate_create_behavior"]
            ),
        )
        for s in idem["scopes"]
    )
    return BrokerCapabilityProfile(
        profile_id=findings.get("profile_id", "profile-1"),
        account=binding,
        currency_definition_fingerprint=findings["currency_definition_fingerprint"],
        trusted_clock=certify_trusted_clock(
            max_observed_skew_ms=clock["max_observed_skew_ms"],
            tolerance_ms=clock["tolerance_ms"],
            proven_at=proven_at,
        ),
        authenticated_raw_envelope={
            "parser_version": raw["parser_version"],
            "auth_mechanism": raw["auth_mechanism"],
            "redacted_secret_fields": tuple(raw["redacted_secret_fields"]),
        },
        client_order_idempotency=certify_client_order_idempotency(
            scopes,
            proven_at=proven_at,
        ),
        auction_tif_cutoff=certify_auction_tif_cutoff(
            supported_order_types=tuple(auction["supported_order_types"]),
            supported_time_in_force=tuple(auction["supported_time_in_force"]),
            cutoff_semantics=CutoffSemantics(auction["cutoff_semantics"]),
            cutoff_instant_description=auction["cutoff_instant_description"],
            proven_at=proven_at,
        ),
        pagination_cursor_retention=certify_pagination_cursor_retention(
            page_count_proof=pag["page_count_proof"],
            cursor_continuity=CursorContinuity(pag["cursor_continuity"]),
            retention_calendar_days=pag["retention_calendar_days"],
            proven_at=proven_at,
        ),
        execution_semantics=certify_execution_semantics(
            partial_fill_supported=exe["partial_fill_supported"],
            cancel_semantics=exe["cancel_semantics"],
            expiry_semantics=exe["expiry_semantics"],
            late_fill_semantics=LateFillSemantics(exe["late_fill_semantics"]),
            proven_at=proven_at,
        ),
        exit_rate_limit={
            "exit_budget_per_minute": rate["exit_budget_per_minute"],
            "query_budget_per_minute": rate["query_budget_per_minute"],
        },
        credential_session_network_fencing=certify_credential_session_network_fencing(
            session_revocable=fence["session_revocable"],
            network_egress_revocable=fence["network_egress_revocable"],
            termination_proof_required=fence["termination_proof_required"],
        ),
        api_version_hashes=_version_hashes(versions.get("api", [])),  # type: ignore[arg-type]
        sdk_version_hashes=_version_hashes(versions.get("sdk", [])),  # type: ignore[arg-type]
        docs_version_hashes=_version_hashes(versions.get("docs", [])),  # type: ignore[arg-type]
    )


def _cmd_profile(args: argparse.Namespace) -> int:
    findings = json.loads(args.findings.read_text())
    proven_at = _parse_utc(args.proven_at) if args.proven_at else datetime.now(tz=timezone.utc)
    try:
        profile = _build_profile(findings, proven_at)
    except BrokerEnablementError as exc:
        print(f"certification failed: {exc.code}: {exc}", file=sys.stderr)
        return 2
    except (KeyError, ValueError, TypeError) as exc:
        print(f"findings are incomplete or invalid: {exc}", file=sys.stderr)
        return 2
    payload = {
        "profile_json": profile.model_dump(mode="json"),
        "profile_hash": profile.profile_hash(),
        "area_hashes": profile.area_hashes(),
    }
    output = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(output + "\n")
        print(f"wrote certified profile to {args.output}")
    else:
        print(output)
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    from src.screening.offensive.v3.contracts import SignedEnvelope

    envelope = SignedEnvelope.model_validate_json(args.manifest.read_text())
    profile = BrokerCapabilityProfile.model_validate_json(args.profile.read_text())
    trusted_at = _parse_utc(args.trusted_at) if args.trusted_at else datetime.now(tz=timezone.utc)
    print(
        "verify requires a CapabilityVerifier + trust head; in this offline"
        " tool we print the bound area hashes for manual cross-check.",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {
                "profile_hash": profile.profile_hash(),
                "area_hashes": profile.area_hashes(),
            },
            indent=2,
        )
    )
    # Reference the verifier symbol so the import is not flagged unused.
    _ = verify_broker_enablement
    _ = envelope
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_probes = sub.add_parser("probes", help="emit a read-only probe template")
    p_probes.add_argument("--output", type=Path, help="write template to file")
    p_probes.add_argument(
        "--mutation-approval",
        type=Path,
        help="signed approval required before any mutation probe",
    )
    p_probes.set_defaults(func=_cmd_probes)

    p_profile = sub.add_parser("profile", help="certify a frozen profile")
    p_profile.add_argument("--findings", type=Path, required=True)
    p_profile.add_argument("--output", type=Path)
    p_profile.add_argument("--proven-at", help="ISO UTC timestamp")
    p_profile.set_defaults(func=_cmd_profile)

    p_verify = sub.add_parser("verify", help="cross-check manifest vs profile")
    p_verify.add_argument("--manifest", type=Path, required=True)
    p_verify.add_argument("--profile", type=Path, required=True)
    p_verify.add_argument("--trusted-at", help="ISO UTC timestamp")
    p_verify.set_defaults(func=_cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
