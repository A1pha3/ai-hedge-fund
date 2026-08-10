#!/usr/bin/env python3
"""Deterministic regenerator for the Revision 2 contract snapshot fixtures.

Every checked-in fixture under ``tests/offensive/v3/contracts/fixtures/revision2``
is a pure projection of:

* the public registries in ``revision2_snapshot_registry.py`` (which contracts
  exist), and
* one valid strict-construction exemplar payload per model, plus the runtime
  rendering helpers in ``revision2_snapshot_exemplars.py``.

This script rebuilds the fixtures from those inputs so that contract drift is
detected mechanically rather than by surgical hand edits.

* ``--check`` (default) renders every fixture and exits non-zero if any rendered
  fixture differs from the checked-in bytes.
* ``--accept-contract-change`` rewrites the fixtures with the rendered output.

When a contract changes shape, add or update its entry in ``EXEMPLAR_OVERRIDES``
(the one valid payload that exercises the new shape) and re-run with
``--accept-contract-change``. The tool never touches private key or seed
material: the protected signing/approval preimages for non-policy artifacts are
preserved verbatim and only have their ``sha256`` re-derived from their stored
preimage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.screening.offensive.v3.contracts.base import CanonicalModel
from src.screening.offensive.v3.contracts.decision import PlanEvidence
from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    OutcomeEvidence,
    SignalEvidence,
    SnapshotEvidence,
)
from src.screening.offensive.v3.policy.models import (
    ProducerIdentity,
    PolicySnapshot,
    behavior_fingerprint,
)

from tests.offensive.v3.contracts.revision2_snapshot_exemplars import (
    alias_snapshot,
    compact_json_bytes,
    enum_snapshot,
    port_snapshot,
    resolve_name,
    schema_snapshot,
    sha256_json,
)
from tests.offensive.v3.contracts.revision2_snapshot_registry import (
    ARTIFACT_HASH_CASES,
    EVIDENCE_RECORD_SPECIALIZATIONS,
    EXCLUDED_MODEL_TYPES,
    PUBLIC_ALIASES,
    PUBLIC_ENUMS,
    PUBLIC_MODEL_CASES,
    PUBLIC_PORTS,
    PROTECTED_PREIMAGE_CASES,
    WIRE_MODEL_EXCEPTIONS,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = (
    REPO_ROOT
    / "tests/offensive/v3/contracts/fixtures/revision2"
)

MODEL_HASHES = FIXTURE_ROOT / "public_model_hashes.json"
MODEL_SCHEMAS = FIXTURE_ROOT / "public_model_schemas.json"
PUBLIC_TYPES = FIXTURE_ROOT / "public_types.json"
PORT_SIGNATURES = FIXTURE_ROOT / "port_signatures.json"
PROTECTED_HASHES = FIXTURE_ROOT / "protected_hashes.json"

ALL_FIXTURES = (
    MODEL_SCHEMAS,
    MODEL_HASHES,
    PUBLIC_TYPES,
    PORT_SIGNATURES,
    PROTECTED_HASHES,
)

POLICY_SNAPSHOT_NAME = "src.screening.offensive.v3.policy.models.PolicySnapshot"
PRODUCER_IDENTITY_NAME = "src.screening.offensive.v3.policy.models.ProducerIdentity"

# Behaviour fingerprint hashes every typed, behaviour-affecting policy field
# except provenance-only labels (policy_id, policy_version, authority_epoch,
# risk_epoch, schema_major). Keep this list in lockstep with
# ``policy.models.behavior_fingerprint``.
BEHAVIOUR_FINGERPRINT_POLICY_KEYS = (
    "policy_epoch",
    "runtime_mode",
    "capital",
    "risk",
    "adv",
    "producers",
    "execution",
    "versions",
    "evidence_gates",
)

# One valid strict-construction payload for every NEW contract in this revision.
# Existing contracts reuse their checked-in exemplar, optionally patched via
# EXEMPLAR_PATCHES.
EXEMPLAR_OVERRIDES: dict[str, dict[str, Any]] = {
    "src.screening.offensive.v3.policy.models.ProducerPolicy": {
        "btst_enabled": False,
        "oversold_bounce_enabled": False,
        "btst_regime_admission_mode": "IGNORE",
        "regime_sizing_enabled": False,
        "streak_sizing_enabled": False,
        "trigger_strength_sizing_enabled": False,
        "composite_sizing_enabled": False,
    },
    "src.screening.offensive.v3.contracts.regime.RegimeSourceRevision": {
        "evidence_id": "regime-evidence-1",
        "revision": 1,
        "artifact_hash": "a" * 64,
    },
    "src.screening.offensive.v3.contracts.regime.RegimeObservation": {
        "signal_session": "2026-08-11",
        "state": "NORMAL",
        "reason": "CLASSIFIED",
        "raw_state": "NORMAL",
        "source_revisions": [
            {
                "evidence_id": "regime-evidence-1",
                "revision": 1,
                "artifact_hash": "a" * 64,
            },
            {
                "evidence_id": "regime-evidence-2",
                "revision": 3,
                "artifact_hash": "b" * 64,
            },
        ],
        "effective_at": "2026-08-11T15:00:00Z",
        "provider_published_at": "2026-08-11T15:30:00Z",
        "observed_at": "2026-08-11T16:00:00Z",
        "classifier_semver": "1.0.0",
        "behavior_fingerprint": "c" * 64,
        "input_schema_hash": "d" * 64,
    },
    "src.screening.offensive.v3.contracts.trial.BaselineShadowPolicyBinding": {
        "source_kind": "BASELINE_POLICY_ACTIVATION",
        "baseline_policy_activation_hash": "a" * 64,
        "policy_snapshot_hash": "b" * 64,
        "policy_fingerprint": "c" * 64,
    },
    "src.screening.offensive.v3.contracts.trial.TargetShadowPolicyBinding": {
        "source_kind": "TARGET_POLICY_REGISTRATION",
        "target_policy_registration_hash": "d" * 64,
        "policy_snapshot_hash": "e" * 64,
        "policy_fingerprint": "f" * 64,
    },
    'src.screening.offensive.v3.contracts.compatibility.LegacyShadowDecisionV2': {
        "artifact_kind": "shadow_decision",
        "artifact_namespace": "growth-kernel.shadow.v1",
        "available_at": "2026-07-29T08:00:00Z",
        "cost_assumption_version": "cn-a-share.v1",
        "counterfactual_key": {
            "counterfactual_cycle_id": "auto-shadow-daily-v1",
            "portfolio_id": "portfolio-v3",
            "signal_session": "2026-07-29"
        },
        "counterfactual_lines": [
            {
                "cost_assumption_version": "cn-a-share.v1",
                "economic_lineage_id": "auto-lineage",
                "estimated_cash_reserve_cents": 105050,
                "estimated_fee_cents": 50,
                "evidence_artifact_hash": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
                "evidence_id": "shadow-evidence-1",
                "evidence_payload_hash": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                "execution_assumption_version": "t1-open-t10-open.v1",
                "exit_session_ordinal": 10,
                "family_id": "auto-family",
                "limit_price_cents": 1050,
                "lot_rule_version": "cn-a-share-lot.v1",
                "lot_size_units": 100,
                "order_type": "LIMIT",
                "price_boundary_version": "cn-price-limit.v1",
                "producer_namespace": "auto.shadow",
                "research_program_id": "auto-program",
                "security_id": "600000.SH",
                "shadow_line_id": "shadow-line-1",
                "stage_id": "auto-shadow-stage",
                "stage_manifest_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                "target_quantity_units": 100,
                "time_in_force": "OPEN_AUCTION",
                "trial_id": "auto-shadow-trial",
                "worst_case_price_cents": 1050
            },
            {
                "cost_assumption_version": "cn-a-share.v1",
                "economic_lineage_id": "auto-lineage",
                "estimated_cash_reserve_cents": 160075,
                "estimated_fee_cents": 75,
                "evidence_artifact_hash": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
                "evidence_id": "shadow-evidence-2",
                "evidence_payload_hash": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                "execution_assumption_version": "t1-open-t10-open.v1",
                "exit_session_ordinal": 10,
                "family_id": "auto-family",
                "limit_price_cents": 800,
                "lot_rule_version": "cn-a-share-lot.v1",
                "lot_size_units": 100,
                "order_type": "LIMIT",
                "price_boundary_version": "cn-price-limit.v1",
                "producer_namespace": "auto.shadow",
                "research_program_id": "auto-program",
                "security_id": "600001.SH",
                "shadow_line_id": "shadow-line-2",
                "stage_id": "auto-shadow-stage",
                "stage_manifest_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                "target_quantity_units": 200,
                "time_in_force": "OPEN_AUCTION",
                "trial_id": "auto-shadow-trial",
                "worst_case_price_cents": 800
            }
        ],
        "created_at": "2026-07-29T08:00:00Z",
        "economic_lineage_id": "auto-lineage",
        "evidence_set_merkle_root": "2222222222222222222222222222222222222222222222222222222222222222",
        "execution_assumption_version": "t1-open-t10-open.v1",
        "execution_authority": "NONE",
        "family_id": "auto-family",
        "issuer_binding": {
            "capability_artifact_kind": "shadow_decision",
            "capability_mode": "broker_confirmed",
            "capability_namespace": "growth-kernel.shadow.v1",
            "capability_schema_major": 2,
            "capability_scope": "portfolio:portfolio-v3",
            "capability_version": "growth-kernel-shadow.v1",
            "issuer_id": "growth-kernel.shadow.service",
            "key_id": "shadow-key-1",
            "registry_epoch": 7,
            "trust_bundle_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "valid_until": "2026-07-29T08:04:00Z",
            "verification_result": "VALID",
            "verified_at": "2026-07-29T07:59:00Z"
        },
        "mode": "broker_confirmed",
        "policy_activation_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "policy_epoch": 4,
        "portfolio_id": "portfolio-v3",
        "producer_namespace": "auto.shadow",
        "research_program_id": "auto-program",
        "schema_major": 2,
        "shadow_decision_id": "shadow-decision-1",
        "shadow_stage_binding": {
            "economic_lineage_id": "auto-lineage",
            "research_program_id": "auto-program",
            "stage_id": "auto-shadow-stage",
            "stage_manifest_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            "trial_id": "auto-shadow-trial"
        },
        "stage_id": "auto-shadow-stage",
        "target_entry_session": "2026-07-30",
        "trial_id": "auto-shadow-trial"
    },
    'src.screening.offensive.v3.contracts.compatibility.LegacyShadowOrderLine': {
        "cost_assumption_version": "cn-a-share.v1",
        "economic_lineage_id": "auto-lineage",
        "estimated_cash_reserve_cents": 105050,
        "estimated_fee_cents": 50,
        "evidence_artifact_hash": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        "evidence_id": "shadow-evidence-1",
        "evidence_payload_hash": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        "execution_assumption_version": "t1-open-t10-open.v1",
        "exit_session_ordinal": 10,
        "family_id": "auto-family",
        "limit_price_cents": 1050,
        "lot_rule_version": "cn-a-share-lot.v1",
        "lot_size_units": 100,
        "order_type": "LIMIT",
        "price_boundary_version": "cn-price-limit.v1",
        "producer_namespace": "auto.shadow",
        "research_program_id": "auto-program",
        "security_id": "600000.SH",
        "shadow_line_id": "shadow-line-1",
        "stage_id": "auto-shadow-stage",
        "stage_manifest_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "target_quantity_units": 100,
        "time_in_force": "OPEN_AUCTION",
        "trial_id": "auto-shadow-trial",
        "worst_case_price_cents": 1050
    },
    'src.screening.offensive.v3.contracts.decision.ShadowDecision': {
        "artifact_kind": "shadow_decision",
        "artifact_namespace": "growth-kernel.shadow.v2",
        "available_at": "2026-07-29T08:00:00Z",
        "cost_assumption_version": "cn-a-share-30bps-tax.v2",
        "counterfactual_key": {
            "counterfactual_cycle_id": "auto-shadow-daily-v1",
            "portfolio_id": "portfolio-v3",
            "signal_session": "2026-07-29"
        },
        "counterfactual_lines": [
            {
                "cost_assumption_version": "cn-a-share-30bps-tax.v2",
                "economic_lineage_id": "auto-lineage",
                "estimated_cash_reserve_cents": 105050,
                "estimated_fee_cents": 50,
                "evidence_artifact_hash": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
                "evidence_id": "shadow-evidence-1",
                "evidence_payload_hash": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                "execution_assumption_version": "t1-open-t10-open-slippage.v2",
                "exit_session_ordinal": 10,
                "family_id": "auto-family",
                "limit_price_cents": 1050,
                "lot_rule_version": "cn-a-share-lot.v1",
                "lot_size_units": 100,
                "order_type": "LIMIT",
                "price_boundary_version": "cn-price-limit.v1",
                "producer_namespace": "auto.shadow",
                "research_program_id": "auto-program",
                "security_id": "600000.SH",
                "shadow_line_id": "shadow-line-1",
                "stage_id": "auto-shadow-stage",
                "stage_manifest_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                "target_quantity_units": 100,
                "time_in_force": "OPEN_AUCTION",
                "trial_id": "auto-shadow-trial",
                "worst_case_price_cents": 1050,
                "target_exit_session": "2026-08-08"
            },
            {
                "cost_assumption_version": "cn-a-share-30bps-tax.v2",
                "economic_lineage_id": "auto-lineage",
                "estimated_cash_reserve_cents": 160075,
                "estimated_fee_cents": 75,
                "evidence_artifact_hash": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
                "evidence_id": "shadow-evidence-2",
                "evidence_payload_hash": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                "execution_assumption_version": "t1-open-t10-open-slippage.v2",
                "exit_session_ordinal": 10,
                "family_id": "auto-family",
                "limit_price_cents": 800,
                "lot_rule_version": "cn-a-share-lot.v1",
                "lot_size_units": 100,
                "order_type": "LIMIT",
                "price_boundary_version": "cn-price-limit.v1",
                "producer_namespace": "auto.shadow",
                "research_program_id": "auto-program",
                "security_id": "600001.SH",
                "shadow_line_id": "shadow-line-2",
                "stage_id": "auto-shadow-stage",
                "stage_manifest_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                "target_quantity_units": 200,
                "time_in_force": "OPEN_AUCTION",
                "trial_id": "auto-shadow-trial",
                "worst_case_price_cents": 800,
                "target_exit_session": "2026-08-08"
            }
        ],
        "created_at": "2026-07-29T08:00:00Z",
        "economic_lineage_id": "auto-lineage",
        "evidence_set_merkle_root": "2222222222222222222222222222222222222222222222222222222222222222",
        "execution_assumption_version": "t1-open-t10-open-slippage.v2",
        "execution_authority": "NONE",
        "family_id": "auto-family",
        "issuer_binding": {
            "capability_artifact_kind": "shadow_decision",
            "capability_mode": "broker_confirmed",
            "capability_namespace": "growth-kernel.shadow.v2",
            "capability_schema_major": 3,
            "capability_scope": "portfolio:portfolio-v3",
            "capability_version": "growth-kernel-shadow.v2",
            "issuer_id": "growth-kernel.shadow.service",
            "key_id": "shadow-key-1",
            "registry_epoch": 7,
            "trust_bundle_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "valid_until": "2026-07-29T08:04:00Z",
            "verification_result": "VALID",
            "verified_at": "2026-07-29T07:59:00Z"
        },
        "mode": "broker_confirmed",
        "policy_epoch": 4,
        "portfolio_id": "portfolio-v3",
        "producer_namespace": "auto.shadow",
        "research_program_id": "auto-program",
        "schema_major": 3,
        "shadow_decision_id": "shadow-decision-1",
        "shadow_stage_binding": {
            "economic_lineage_id": "auto-lineage",
            "research_program_id": "auto-program",
            "stage_id": "auto-shadow-stage",
            "stage_manifest_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            "trial_id": "auto-shadow-trial"
        },
        "stage_id": "auto-shadow-stage",
        "target_entry_session": "2026-07-30",
        "trial_id": "auto-shadow-trial",
        "shadow_policy_binding": {
            "source_kind": "BASELINE_POLICY_ACTIVATION",
            "baseline_policy_activation_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "policy_snapshot_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "policy_fingerprint": "2222222222222222222222222222222222222222222222222222222222222222"
        }
    },
}

# Partial updates applied on top of a contract's checked-in exemplar when only a
# few fields changed shape (avoids re-stating a large stable payload). A dict
# value replaces that sub-object wholesale.
EXEMPLAR_PATCHES: dict[str, dict[str, Any]] = {
    POLICY_SNAPSHOT_NAME: {
        "schema_major": 2,
        "producers": {
            "btst_enabled": False,
            "oversold_bounce_enabled": False,
            "btst_regime_admission_mode": "IGNORE",
            "regime_sizing_enabled": False,
            "streak_sizing_enabled": False,
            "trigger_strength_sizing_enabled": False,
            "composite_sizing_enabled": False,
        },
        "versions": {
            "execution_contract_version": "t0-close-t1-open-t10-open-slippage.v2",
            "cost_version": "cn-a-share-costs-30bps-tax.v2",
        },
    },
    "src.screening.offensive.v3.policy.models.VerifiedPolicyActivation": {
        "policy_snapshot": {
            "schema_major": 2,
            "producers": {
                "btst_enabled": False,
                "oversold_bounce_enabled": False,
                "btst_regime_admission_mode": "IGNORE",
                "regime_sizing_enabled": False,
                "streak_sizing_enabled": False,
                "trigger_strength_sizing_enabled": False,
                "composite_sizing_enabled": False,
            },
            "versions": {
                "execution_contract_version": "t0-close-t1-open-t10-open-slippage.v2",
                "cost_version": "cn-a-share-costs-30bps-tax.v2",
            },
        },
    },
    "src.screening.offensive.v3.contracts.decision.ShadowOrderLine": {
        "cost_assumption_version": "cn-a-share-30bps-tax.v2",
        "execution_assumption_version": "t1-open-t10-open-slippage.v2",
        "target_exit_session": "2026-08-08"
    },
}


def _deep_merge(base: Any, patch: Any) -> Any:
    """Recursively merge ``patch`` into ``base``; scalars and lists are replaced."""

    if isinstance(base, dict) and isinstance(patch, dict):
        merged: dict[str, Any] = dict(base)
        for key, value in patch.items():
            merged[key] = _deep_merge(merged.get(key), value) if key in merged else value
        return merged
    return patch


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    """Render ``value`` preserving the fixture's existing serialization style.

    ``public_model_schemas.json`` is checked in as compact single-line JSON while
    the other fixtures use pretty-printed indented JSON; regenerating must not
    reformat untouched entries, so the on-disk style is detected and reused.
    """

    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing and existing.count("\n") <= 1:
        rendered = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    else:
        match = re.search(r"\n( +)\S", existing)
        indent = len(match.group(1)) if match else 2
        rendered = json.dumps(
            value, ensure_ascii=False, sort_keys=True, indent=indent
        )
    path.write_text(rendered + "\n", encoding="utf-8")


def _load_exemplar_payloads() -> dict[str, dict[str, Any]]:
    """Return one valid payload per public model.

    Precedence per registered contract: full override, then checked-in exemplar
    with an optional patch, then the checked-in exemplar verbatim.
    """

    existing = _read_json(MODEL_HASHES)
    payloads: dict[str, dict[str, Any]] = {}
    for name in PUBLIC_MODEL_CASES:
        if name in EXEMPLAR_OVERRIDES:
            payloads[name] = EXEMPLAR_OVERRIDES[name]
            continue
        if name not in existing:
            raise SystemExit(
                f"no exemplar payload for registered contract {name!r}; "
                "add one to EXEMPLAR_OVERRIDES"
            )
        base = existing[name]["payload"]
        payloads[name] = (
            _deep_merge(base, EXEMPLAR_PATCHES[name])
            if name in EXEMPLAR_PATCHES
            else base
        )
    return payloads


def render_model_schemas() -> dict[str, Any]:
    rendered: dict[str, Any] = {}
    for name in PUBLIC_MODEL_CASES:
        model_type = resolve_name(name)
        rendered[name] = (
            {
                "model_module": model_type.__module__,
                "model_name": model_type.__name__,
            }
            | schema_snapshot(model_type)
        )
    return rendered


def render_model_hashes(payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rendered: dict[str, Any] = {}
    for name in PUBLIC_MODEL_CASES:
        model_type = resolve_name(name)
        payload = payloads[name]
        encoded = compact_json_bytes(payload)
        parsed = model_type.model_validate_json(encoded, strict=True)
        entry: dict[str, Any] = {
            "model_module": model_type.__module__,
            "model_name": model_type.__name__,
            "payload": parsed.model_dump(mode="json"),
            "json_payload_sha256": hashlib.sha256(encoded).hexdigest(),
        }
        if name in WIRE_MODEL_EXCEPTIONS:
            assert not isinstance(parsed, CanonicalModel)
        else:
            assert isinstance(parsed, CanonicalModel)
            canonical = hashlib.sha256(parsed.canonical_bytes()).hexdigest()
            entry["canonical_payload_sha256"] = canonical
            entry["content_hash"] = parsed.content_hash()
        if name in ARTIFACT_HASH_CASES:
            # Every Revision 2 artifact hash seals under schema major 2; models
            # that carry the field expose it, the rest hardcode it in artifact_hash.
            schema_major = getattr(parsed, "schema_major", 2)
            entry["artifact_hash"] = {
                "domain": model_type.HASH_DOMAIN,  # type: ignore[attr-defined]
                "schema_major": schema_major,
                "sha256": parsed.artifact_hash(),  # type: ignore[attr-defined]
            }
        rendered[name] = entry
    return rendered


def render_public_types() -> dict[str, Any]:
    return {
        "aliases": {
            name: alias_snapshot(resolve_name(name)) for name in PUBLIC_ALIASES
        },
        "enums": {
            name: enum_snapshot(resolve_name(name)) for name in PUBLIC_ENUMS
        },
    }


def render_port_signatures() -> dict[str, Any]:
    return {name: port_snapshot(resolve_name(name)) for name in PUBLIC_PORTS}


def _policy_fingerprint_entry(policy_payload: dict[str, Any]) -> dict[str, Any]:
    policy = PolicySnapshot.model_validate_json(
        compact_json_bytes(policy_payload), strict=True
    )
    preimage = json.loads(policy.canonical_bytes())
    digest = hashlib.sha256(compact_json_bytes(preimage)).hexdigest()
    assert digest == policy.policy_fingerprint
    return {"fingerprint": policy.policy_fingerprint, "preimage": preimage, "sha256": digest}


def _behavior_fingerprint_entry(
    policy_payload: dict[str, Any], producer_payload: dict[str, Any]
) -> dict[str, Any]:
    policy = PolicySnapshot.model_validate_json(
        compact_json_bytes(policy_payload), strict=True
    )
    producer = ProducerIdentity.model_validate_json(
        compact_json_bytes(producer_payload), strict=True
    )
    preimage = {
        "policy": {
            key: policy_payload[key] for key in BEHAVIOUR_FINGERPRINT_POLICY_KEYS
        },
        "producer": producer_payload,
    }
    digest = hashlib.sha256(compact_json_bytes(preimage)).hexdigest()
    assert digest == behavior_fingerprint(producer, policy)
    return {"fingerprint": digest, "preimage": preimage, "sha256": digest}


def render_protected_hashes(
    payloads: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Regenerate policy-derived preimages; preserve crypto signing material.

    ``policy_fingerprint`` and ``behavior_fingerprint`` are pure projections of
    the policy/producer exemplars, so they are rebuilt from code. The remaining
    protected entries bind hand-authored signing/approval material that is not a
    simple model exemplar; their preimage is preserved verbatim and only the
    ``sha256`` is re-derived from that preimage.
    """

    rendered: dict[str, Any] = {}
    policy_payload = payloads[POLICY_SNAPSHOT_NAME]
    producer_payload = payloads[PRODUCER_IDENTITY_NAME]
    rendered["policy_fingerprint"] = _policy_fingerprint_entry(policy_payload)
    rendered["behavior_fingerprint"] = _behavior_fingerprint_entry(
        policy_payload, producer_payload
    )
    existing = _read_json(PROTECTED_HASHES)
    for name in PROTECTED_PREIMAGE_CASES:
        if name in rendered:
            continue
        entry = existing[name]
        preimage = entry["preimage"]
        entry = dict(entry)
        entry["sha256"] = hashlib.sha256(compact_json_bytes(preimage)).hexdigest()
        rendered[name] = entry
    return rendered


def render_all() -> dict[Path, Any]:
    payloads = _load_exemplar_payloads()
    return {
        MODEL_SCHEMAS: render_model_schemas(),
        MODEL_HASHES: render_model_hashes(payloads),
        PUBLIC_TYPES: render_public_types(),
        PORT_SIGNATURES: render_port_signatures(),
        PROTECTED_HASHES: render_protected_hashes(payloads),
    }


def _classify_model_modules() -> tuple[str, ...]:
    """Enum discovery modules, derived from where public enums live."""

    modules: list[str] = []
    for name in PUBLIC_ENUMS:
        module = name.rpartition(".")[0]
        if module not in modules:
            modules.append(module)
    return tuple(modules)


def _check_invariants() -> None:
    """Fail fast on registry/exemplar wiring mistakes before rendering."""

    if len(PUBLIC_MODEL_CASES) != len(set(PUBLIC_MODEL_CASES)):
        raise SystemExit("PUBLIC_MODEL_CASES has duplicates")
    if set(WIRE_MODEL_EXCEPTIONS) & set(EXCLUDED_MODEL_TYPES):
        raise SystemExit("a wire-model exception cannot also be excluded")
    for override_name in EXEMPLAR_OVERRIDES:
        if override_name not in PUBLIC_MODEL_CASES:
            raise SystemExit(
                f"EXEMPLAR_OVERRIDES references unregistered contract {override_name!r}"
            )
    # Every specialization must remain registered and resolvable.
    for spec in EVIDENCE_RECORD_SPECIALIZATIONS:
        resolve_name(spec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="fail if any rendered fixture differs from the checked-in bytes",
    )
    mode.add_argument(
        "--accept-contract-change",
        action="store_true",
        help="rewrite the fixtures with the rendered output",
    )
    args = parser.parse_args(argv)
    accept = args.accept_contract_change
    if not accept and not args.check:
        args.check = True

    _check_invariants()
    rendered = render_all()

    drift: list[str] = []
    for path, value in rendered.items():
        on_disk = _read_json(path)
        if on_disk == value:
            continue
        drift.append(path.name)
        if accept:
            _write_json(path, value)

    if accept:
        if drift:
            print(f"accepted contract changes in: {', '.join(drift)}")
        else:
            print("no contract drift to accept")
        return 0

    if drift:
        print("contract snapshot drift detected in:", ", ".join(drift), file=sys.stderr)
        print(
            "run `scripts/v3_refresh_contract_snapshots.py --accept-contract-change`",
            file=sys.stderr,
        )
        return 1
    print("contract snapshots are up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
