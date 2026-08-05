"""Legacy research-material import tool (Plan 03 Task 7).

Converts legacy materials to store truth as
``RESEARCH_RECONSTRUCTION | PRIOR`` ONLY. Broker-mode claims on legacy
data are rejected; provenance gaps are retained; every imported record
carries ``authorization_eligible=0``. ``--dry-run`` validates and reports
without writing; live ingestion requires the Plan 04 trust bootstrap and
fails closed until it exists.

Usage:
    uv run python scripts/v3_import_research_evidence.py --dry-run \
        --source PATH [--db PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from src.screening.offensive.v3.contracts.base import ExecutionMode
from src.screening.offensive.v3.contracts.decision import PlanEvidence
from src.screening.offensive.v3.contracts.evidence import (
    OutcomeEvidence,
    SignalEvidence,
    SnapshotEvidence,
)

_ADAPTER = TypeAdapter(
    SnapshotEvidence | SignalEvidence | OutcomeEvidence | PlanEvidence
)

_PROVENANCE_FIELDS = (
    "subject_producer",
    "family_id",
    "behavior_fingerprint",
    "provider_published_at",
    "source_authority",
)


def _report(payload: bytes, *, dry_run: bool) -> int:
    try:
        envelope = _ADAPTER.validate_json(payload, strict=True)
    except ValidationError as exc:
        print("status=REJECTED reason=legacy_payload_invalid")
        print(f"detail={exc.errors()[:3]}")
        return 1
    anchor_fingerprint = hashlib.sha256(payload).hexdigest()
    if envelope.mode is not ExecutionMode.RESEARCH_RECONSTRUCTION:
        print(
            "status=REJECTED reason=legacy_broker_claim_rejected "
            f"claimed_mode={envelope.mode.value}"
        )
        print(
            "note=legacy materials are PRIOR | RESEARCH_RECONSTRUCTION"
            " only; broker-mode claims are forbidden"
        )
        return 1
    gaps = [
        field
        for field in _PROVENANCE_FIELDS
        if getattr(envelope, field) in (None, "")
    ]
    print("status=OK" if not dry_run else "status=DRY_RUN_OK")
    print(f"evidence_id={envelope.evidence_id}")
    print(f"evidence_kind={envelope.evidence_kind}")
    print("forced_mode=RESEARCH_RECONSTRUCTION")
    print("provenance_class=PRIOR")
    print("authorization_eligible=0")
    print(f"anchor_fingerprint={anchor_fingerprint}")
    print(f"provenance_gaps={json.dumps(gaps)}")
    if dry_run:
        print("note=dry-run: nothing written")
        return 0
    print(
        "note=live ingestion requires the Plan 04 trust bootstrap;"
        " failing closed"
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="v3_import_research_evidence",
        description=(
            "Import legacy research materials as PRIOR |"
            " RESEARCH_RECONSTRUCTION only."
        ),
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Path to a legacy evidence envelope JSON file.",
    )
    parser.add_argument(
        "--db",
        required=False,
        help="Evidence store database path (live ingestion only).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report without writing.",
    )
    args = parser.parse_args(argv)
    source = Path(args.source)
    if not source.exists():
        parser.error(f"source file not found: {source}")
    return _report(source.read_bytes(), dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
