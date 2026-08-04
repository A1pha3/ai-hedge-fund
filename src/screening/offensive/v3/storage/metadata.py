"""Versioned identity, derivation, and encoding helpers for the capital store.

Plan 02 kernel revision constants are frozen here. Later tasks add new
constants instead of renumbering existing ones, so stored rows keep their
meaning across revisions.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Final

from src.screening.offensive.v3.contracts import content_hash


SCHEMA_MAJOR: Final[int] = 2
"""The Revision 2 contract schema major persisted into snapshots."""

LEDGER_SCHEMA_VERSION: Final[int] = 1
"""The capital ledger storage schema revision managed by migrations."""

INITIAL_MIGRATION_REVISION: Final[str] = "0001"
"""Alembic revision identifier of the initial ledger migration."""

UNACTIVATED_POLICY_ACTIVATION_HASH: Final[str] = "0" * 64
UNACTIVATED_AUTHORIZATION_ID: Final[str] = "unactivated"

GATEWAY_META_DEFAULTS: Final[dict[str, str]] = {
    "schema_version": str(LEDGER_SCHEMA_VERSION),
    "policy_activation_hash": UNACTIVATED_POLICY_ACTIVATION_HASH,
    "policy_epoch": "1",
    "authority_epoch": "1",
    "risk_epoch": "1",
    "registry_epoch": "1",
    "authorization_id": UNACTIVATED_AUTHORIZATION_ID,
    "authorization_version": "1",
    "stage_loss_state_version": "1",
    "writer_fencing_epoch": "1",
}
"""Sentinel governance rows for kernel revision 1.

These placeholders carry no authority: the Governance Control Plane binds
real values through the Plan 04 gateway transaction. Snapshots surface them
so consumers fail closed until activation.
"""

EXPECTED_TABLE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "account_capital_truth",
        "capital_projection",
        "economic_event_legs",
        "economic_events",
        "entry_tombstones",
        "event_revisions",
        "execution_revisions",
        "gateway_meta",
        "payables",
        "positions",
        "receivables",
        "reserves",
        "risk_latches",
        "session_checkpoints",
        "stage_loss_state",
    }
)

RISK_SNAPSHOT_VALIDITY: Final[timedelta] = timedelta(hours=1)

CENT_SCALE: Final[int] = 100
PRICE_MICRO_SCALE: Final[int] = 1_000_000

DRAWDOWN_HALT_PPM: Final[int] = 150_000


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("capital store timestamps must be UTC-aware")
    return value.isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("capital store timestamps must be UTC-aware")
    return parsed.astimezone(timezone.utc)


def derive_event_id(idempotency_key: str) -> str:
    """Deterministically bind one canonical event identity to one command key.

    Retried submissions must converge on the same canonical event, so the
    identity is derived from the idempotency key rather than assigned from a
    mutable sequence.
    """

    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"eco-{digest[:40]}"


def derive_risk_snapshot_id(portfolio_id: str, capital_version: int) -> str:
    digest = content_hash(
        {"portfolio_id": portfolio_id, "capital_version": capital_version}
    )
    return f"cap-risk-{digest[:40]}"


def scaled_int(value: Decimal, scale: int, label: str) -> int:
    """Convert a boundary Decimal into exact integer quanta.

    Persistence never stores REAL money/price/quantity values; any sub-quanta
    remainder is a command defect and fails closed.
    """

    scaled = value * scale
    if not scaled.is_finite() or scaled != scaled.to_integral_value():
        raise ValueError(f"{label} must be an exact integer count of quanta")
    return int(scaled)


def drawdown_ppm(nav_cents: int, high_water_mark_cents: int) -> int:
    if high_water_mark_cents <= 0:
        return 0
    return ((high_water_mark_cents - nav_cents) * 1_000_000) // high_water_mark_cents
