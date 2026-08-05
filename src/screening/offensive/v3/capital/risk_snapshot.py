"""Complete CapitalRiskSnapshot sealing and non-replenishable stage loss.

Plan 02 Task 5. The risk snapshot is a DERIVED view over one
AccountCapitalTruth at one capital version: it consumes only fill-verified
position projections, reserves, live-order exposure and the current valid
marks. Marks are validated fail-closed before the view is assembled:

- ``valuation_unknown``: open positions exist but no as-observed valuation
  has ever been recorded;
- ``mark_unauthorized``: the newest as-observed valuation's source authority
  is not in the caller's trusted authority set;
- ``mark_not_yet_recorded``: the valuation was recorded after ``as_of`` (a
  snapshot never consumes future facts);
- ``mark_stale``: the valuation is older than ``RISK_SNAPSHOT_VALIDITY``;
- ``mark_missing``: an open position has no mark in the newest valuation (a
  position opened after the last valuation is unknown, never zero);
- ``mark_invalid``: a stored mark is not a positive price.

Rejected marks are never silently substituted; the snapshot contract then
carries exact integer truth only.

Stage loss follows the charter: the budget freezes at activation in integer
cents, consumption advances via ``max(previous, instantaneous_charge)`` in
the same capital transaction as fill/fee/mark/reserve facts, and profit,
rebound, relabel or a risk-epoch swap never refund consumed budget. The
instantaneous charge is the sum of four mutually exclusive components::

    realized_market_losses_ex_fees_cents
    + cumulative_fees_and_taxes_cents
    + max(0, -marked_unrealized_pnl_cents)
    + incremental_pending_stress_beyond_mark_cents

Per-stage budgets consume attributed charges only. The portfolio-global
budget identity additionally consumes the derived worst-case floor
(cumulative fees plus mark-to-market unrealized loss), because those ledger
facts carry no stage attribution and unattributable risk must land in the
most conservative budget. The unrealized component is measured only while
the newest valuation covers every open position; unknown marks block new
risk via snapshot rejection instead of fabricating a loss charge, and the
monotone floor catches up once the mark set is complete again, so
measurable loss is never under-reported.

``close_risk_snapshot`` seals the session snapshot as the frozen
``CapitalRiskSnapshot`` contract plus an append-only RISK_SNAPSHOT seal
record carrying the content-hash fingerprint. The frozen Plan 01
``EconomicEventKind`` contract has no RISK_SNAPSHOT member and contracts are
never modified, so the seal lives in its own append-only
``risk_snapshot_seals`` table with immutability triggers. Identical closes
converge on the sealed artifact; divergent closes conflict and never
overwrite.

Extension points for later plans:

- ``live_orders`` stays empty until the Plan 04 gateway owns an order
  registry; ambiguous submissions remain covered by Task 2's worst-case
  reserve retention, so live exposure is never under-reported meanwhile.
- ``pending_stress_components`` and ``corporate_action_risk_components``
  stay empty until Plan 04 binds pending-stress reserves; successor lots
  from Task 4 remain open positions, so their marked gross is still counted.
- Program-scoped stage-loss budgets (between stage and global) land with the
  Plan 04 governance surface.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import TYPE_CHECKING, Annotated, Final

import sqlalchemy as sa
from pydantic import Field

from src.screening.offensive.v3.capital.rounding import (
    MICROS_PER_CENT,
    round_half_even_div,
)
from src.screening.offensive.v3.contracts import (
    CanonicalModel,
    CapitalRiskSnapshot,
    Sha256,
    StageLossLatchState,
    UtcInstant,
)
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr
from src.screening.offensive.v3.storage.metadata import (
    DRAWDOWN_HALT_PPM,
    RISK_SNAPSHOT_VALIDITY,
    parse_utc,
    utc_iso,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.screening.offensive.v3.capital.repository import (
        GatewayTransactionContext,
    )


PositiveCents = Annotated[int, Field(gt=0)]
NonNegativeCents = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]

PPM_SCALE: Final[int] = 1_000_000

DRAWDOWN_SCALE_START_PPM: Final[int] = 100_000
"""Drawdown (ppm) where linear entry scaling begins (charter 10%)."""

DRAWDOWN_SCALE_BAND_PPM: Final[int] = DRAWDOWN_HALT_PPM - DRAWDOWN_SCALE_START_PPM
"""The 5pp band over which the multiplier scales linearly to zero."""

GLOBAL_STAGE_LOSS_IDENTITY: Final[tuple[str, str, str]] = (
    "__PORTFOLIO_GLOBAL__",
    "__PORTFOLIO_GLOBAL__",
    "__PORTFOLIO_GLOBAL__",
)
"""Reserved identity of the portfolio-global stage-loss budget.

Unattributable portfolio facts (cumulative fees, mark-to-market unrealized
loss) carry no stage attribution; they consume the most conservative budget,
which is this global row when governance has frozen one.
"""


def _conflict(code: str, message: str, **details: object) -> "RuntimeError":
    # Lazy import keeps this module free of a repository import cycle while
    # reusing the kernel's fail-closed exception type.
    from src.screening.offensive.v3.capital.repository import CapitalConflict

    return CapitalConflict(code, message, **details)


def entry_scaling_multiplier_ppm(drawdown_ppm_value: int) -> int:
    """The one-shot drawdown multiplier m(d) of the charter, in PPM.

    ``1.0`` below 10%, linear to zero across 10-15%, zero at and beyond the
    15% halt band. The multiplier is applied exactly once by the Growth
    Kernel to unscaled raw targets and the unscaled portfolio gross ceiling;
    this function only encodes the tier.
    """

    if drawdown_ppm_value < 0:
        raise ValueError("drawdown ppm cannot be negative")
    if drawdown_ppm_value < DRAWDOWN_SCALE_START_PPM:
        return PPM_SCALE
    if drawdown_ppm_value >= DRAWDOWN_HALT_PPM:
        return 0
    return (DRAWDOWN_HALT_PPM - drawdown_ppm_value) * (
        PPM_SCALE // DRAWDOWN_SCALE_BAND_PPM
    )


# ---------------------------------------------------------------------------
# Requests and receipts
# ---------------------------------------------------------------------------


class BuildRiskSnapshotRequest(CanonicalModel):
    """Build the complete derived snapshot at one capital version.

    ``authorized_mark_authorities`` is the caller-declared trusted set of
    valuation source authorities; it must name at least one authority so an
    unknown ledger can never pass mark validation by default.
    """

    as_of: UtcInstant
    authorized_mark_authorities: Annotated[
        tuple[NonEmptyStr, ...], Field(min_length=1)
    ]


class StageLossBudgetActivationRequest(CanonicalModel):
    """Freeze one stage-loss budget at activation in integer cents."""

    idempotency_key: NonEmptyStr
    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr
    stage_loss_budget_id: NonEmptyStr
    frozen_budget_cents: PositiveCents
    source_authority: NonEmptyStr
    authorization_reference: NonEmptyStr
    expected_stage_loss_state_version: PositiveInt
    as_of: UtcInstant


class StageLossChargeRequest(CanonicalModel):
    """One attributed instantaneous stage-loss measurement.

    Components are mutually exclusive by construction: realized losses are
    ex-fees, fees never reappear in any other component, the signed
    marked-unrealized P&L is clamped to its loss part by the engine, and
    pending stress only counts the increment beyond the current mark.
    """

    idempotency_key: NonEmptyStr
    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr
    source_authority: NonEmptyStr
    realized_market_losses_ex_fees_cents: NonNegativeCents
    cumulative_fees_and_taxes_cents: NonNegativeCents
    marked_unrealized_pnl_cents: int
    incremental_pending_stress_beyond_mark_cents: NonNegativeCents
    expected_stage_loss_state_version: PositiveInt
    as_of: UtcInstant

    @property
    def instantaneous_charge_cents(self) -> int:
        return (
            self.realized_market_losses_ex_fees_cents
            + self.cumulative_fees_and_taxes_cents
            + max(0, -self.marked_unrealized_pnl_cents)
            + self.incremental_pending_stress_beyond_mark_cents
        )

    @property
    def identity(self) -> tuple[str, str, str]:
        return (
            self.research_program_id,
            self.economic_lineage_id,
            self.stage_id,
        )


class StageLossChargeReceipt(CanonicalModel):
    """The durable outcome of one recorded stage-loss charge."""

    idempotency_key: NonEmptyStr
    research_program_id: NonEmptyStr
    economic_lineage_id: NonEmptyStr
    stage_id: NonEmptyStr
    instantaneous_charge_cents: NonNegativeCents
    consumed_before_cents: NonNegativeCents
    consumed_after_cents: NonNegativeCents
    frozen_budget_cents: PositiveCents
    remaining_budget_cents: NonNegativeCents
    stage_loss_version: PositiveInt
    state: StageLossLatchState
    capital_version: NonNegativeInt
    stage_loss_state_version: PositiveInt


class CloseRiskSnapshotRequest(CanonicalModel):
    """Seal the session snapshot (one seal per portfolio/session)."""

    session: date
    as_of: UtcInstant
    source_authority: NonEmptyStr
    authorized_mark_authorities: Annotated[
        tuple[NonEmptyStr, ...], Field(min_length=1)
    ]


class RiskSnapshotCloseReceipt(CanonicalModel):
    """The durable outcome of one sealed (or converged) session snapshot."""

    risk_snapshot_seal_id: NonEmptyStr
    risk_snapshot_id: NonEmptyStr
    session: date
    capital_version: PositiveInt
    stream_version: NonNegativeInt
    snapshot_content_hash: Sha256
    entry_scaling_multiplier_ppm: NonNegativeInt
    already_sealed: bool
    as_of: UtcInstant


# ---------------------------------------------------------------------------
# Identity derivation
# ---------------------------------------------------------------------------


def derive_stage_loss_charge_id(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"slc-{digest[:40]}"


def derive_risk_snapshot_seal_id(portfolio_id: str, session: date) -> str:
    digest = hashlib.sha256(
        f"{portfolio_id}:{session.isoformat()}".encode("utf-8")
    ).hexdigest()
    return f"seal-{digest[:40]}"


def stage_loss_floor_idempotency_key(fact_key: str, consumed_after_cents: int) -> str:
    """Deterministic identity of one derived global-floor consumption.

    The floor is strictly increasing whenever it applies, so keying on the
    fact plus the resulting consumption level is unique per application and
    stable for retries.
    """

    return f"stage-loss-floor:{fact_key}:{consumed_after_cents}"


# ---------------------------------------------------------------------------
# Mark validation and snapshot build
# ---------------------------------------------------------------------------


def _latest_valuation_row(context: "GatewayTransactionContext"):
    return context._connection.execute(
        sa.text(
            "SELECT economic_event_id, source_authority, effective_at,"
            " recorded_at FROM economic_events"
            " WHERE event_kind = 'VALUATION'"
            " AND correction_of_event_id IS NULL"
            " ORDER BY stream_version DESC LIMIT 1"
        )
    ).first()


def _latest_valuation_marks(
    context: "GatewayTransactionContext", event_id: str
) -> dict[str, int]:
    rows = context._connection.execute(
        sa.text(
            "SELECT security_id, mark_price_micros FROM economic_event_legs"
            " WHERE economic_event_id = :event_id ORDER BY sequence"
        ),
        {"event_id": event_id},
    ).all()
    return {row.security_id: int(row.mark_price_micros) for row in rows}


def require_valid_marks(
    context: "GatewayTransactionContext",
    *,
    as_of,
    authorized_mark_authorities: tuple[str, ...],
) -> dict[str, int]:
    """Validate the current mark set fail-closed; never substitute zeros.

    Returns the validated marks (empty when no position is open).
    """

    open_rows = context.open_position_rows()
    if not open_rows:
        return {}

    row = _latest_valuation_row(context)
    if row is None:
        raise _conflict(
            "valuation_unknown",
            "open positions exist but no as-observed valuation is recorded;"
            " the snapshot cannot consume unknown marks",
        )
    if row.source_authority not in authorized_mark_authorities:
        raise _conflict(
            "mark_unauthorized",
            "the newest valuation was not recorded by a trusted authority",
            source_authority=row.source_authority,
        )
    recorded_at = parse_utc(row.recorded_at)
    if recorded_at > as_of:
        raise _conflict(
            "mark_not_yet_recorded",
            "the snapshot cannot consume marks recorded after as_of",
            recorded_at=row.recorded_at,
        )
    if as_of - recorded_at > RISK_SNAPSHOT_VALIDITY:
        raise _conflict(
            "mark_stale",
            "the newest valuation is older than the snapshot validity"
            " window; marks must be refreshed before sealing risk",
            recorded_at=row.recorded_at,
        )
    marks = _latest_valuation_marks(context, row.economic_event_id)
    invalid = sorted(
        security_id
        for security_id, price_micros in marks.items()
        if price_micros <= 0
    )
    if invalid:
        raise _conflict(
            "mark_invalid",
            "stored valuation marks must be positive prices",
            securities=invalid,
        )
    missing = sorted({r.security_id for r in open_rows} - set(marks))
    if missing:
        raise _conflict(
            "mark_missing",
            "open positions have no current mark; unknown marks are never"
            " silently substituted",
            missing_securities=missing,
        )
    return marks


def build_capital_risk_snapshot(
    context: "GatewayTransactionContext", request: BuildRiskSnapshotRequest
) -> CapitalRiskSnapshot:
    """Assemble the complete derived snapshot after mark validation.

    Once ``require_valid_marks`` passes, the newest as-observed valuation
    covers every open position, so the shared projection reader assembles
    exact marked truth with no zero substitution.
    """

    require_valid_marks(
        context,
        as_of=request.as_of,
        authorized_mark_authorities=request.authorized_mark_authorities,
    )
    return context.read_capital_risk_snapshot(request.as_of)


# ---------------------------------------------------------------------------
# Stage-loss engine
# ---------------------------------------------------------------------------


def _stage_loss_meta_version(context: "GatewayTransactionContext") -> int:
    row = context._connection.execute(
        sa.text(
            "SELECT value FROM gateway_meta WHERE key = 'stage_loss_state_version'"
        )
    ).one()
    return int(row.value)


def _bump_stage_loss_meta(
    context: "GatewayTransactionContext", as_of
) -> int:
    new_version = _stage_loss_meta_version(context) + 1
    context._connection.execute(
        sa.text(
            "UPDATE gateway_meta SET value = :value, updated_at = :updated_at"
            " WHERE key = 'stage_loss_state_version'"
        ),
        {"value": str(new_version), "updated_at": utc_iso(as_of)},
    )
    return new_version


def _bump_capital_version(
    context: "GatewayTransactionContext", event_id: str | None, as_of
) -> int:
    projection_table = context._table("capital_projection")
    projection = context._connection.execute(projection_table.select()).one()
    new_version = int(projection.capital_version) + 1
    context._connection.execute(
        projection_table.update()
        .where(projection_table.c.portfolio_id == projection.portfolio_id)
        .values(
            capital_version=new_version,
            updated_at=utc_iso(as_of),
            updated_by_event_id=event_id,
        )
    )
    return new_version


def _stage_loss_row(context: "GatewayTransactionContext", identity: tuple[str, str, str]):
    return context._connection.execute(
        sa.text(
            "SELECT * FROM stage_loss_state"
            " WHERE research_program_id = :program"
            " AND economic_lineage_id = :lineage AND stage_id = :stage"
        ),
        {
            "program": identity[0],
            "lineage": identity[1],
            "stage": identity[2],
        },
    ).first()


def _charge_content_fingerprint(
    *,
    identity: tuple[str, str, str],
    source_authority: str,
    realized: int,
    fees: int,
    unrealized: int,
    stress: int,
) -> str:
    from src.screening.offensive.v3.contracts import content_hash

    return content_hash(
        {
            "kind": "stage_loss_charge",
            "research_program_id": identity[0],
            "economic_lineage_id": identity[1],
            "stage_id": identity[2],
            "source_authority": source_authority,
            "realized_market_losses_ex_fees_cents": realized,
            "cumulative_fees_and_taxes_cents": fees,
            "marked_unrealized_pnl_cents": unrealized,
            "incremental_pending_stress_beyond_mark_cents": stress,
        }
    )


def _insert_stage_loss_charge(
    context: "GatewayTransactionContext",
    *,
    idempotency_key: str,
    identity: tuple[str, str, str],
    source_authority: str,
    realized: int,
    fees: int,
    unrealized: int,
    stress: int,
    instantaneous: int,
    consumed_before: int,
    consumed_after: int,
    frozen_budget: int,
    version_before: int,
    version_after: int,
    state_after: StageLossLatchState,
    capital_version: int,
    as_of,
) -> None:
    context._connection.execute(
        context._table("stage_loss_charges").insert().values(
            stage_loss_charge_id=derive_stage_loss_charge_id(idempotency_key),
            idempotency_key=idempotency_key,
            payload_content_fingerprint=_charge_content_fingerprint(
                identity=identity,
                source_authority=source_authority,
                realized=realized,
                fees=fees,
                unrealized=unrealized,
                stress=stress,
            ),
            research_program_id=identity[0],
            economic_lineage_id=identity[1],
            stage_id=identity[2],
            source_authority=source_authority,
            realized_market_losses_ex_fees_cents=realized,
            cumulative_fees_and_taxes_cents=fees,
            marked_unrealized_pnl_cents=unrealized,
            unrealized_loss_charge_cents=max(0, -unrealized),
            incremental_pending_stress_beyond_mark_cents=stress,
            instantaneous_charge_cents=instantaneous,
            consumed_before_cents=consumed_before,
            consumed_after_cents=consumed_after,
            frozen_budget_cents=frozen_budget,
            stage_loss_version_before=version_before,
            stage_loss_version_after=version_after,
            latch_state_after=state_after.value,
            capital_version_after=capital_version,
            recorded_at=utc_iso(as_of),
        )
    )


def activate_stage_loss_budget(
    context: "GatewayTransactionContext",
    request: StageLossBudgetActivationRequest,
) -> CapitalRiskSnapshot:
    """Freeze one stage-loss budget; one budget per identity, forever."""

    conn = context._connection
    activations_table = context._table("stage_loss_budget_activations")
    existing = conn.execute(
        activations_table.select().where(
            activations_table.c.idempotency_key == request.idempotency_key
        )
    ).first()
    identity = (
        request.research_program_id,
        request.economic_lineage_id,
        request.stage_id,
    )
    if existing is not None:
        identical = (
            existing.stage_loss_budget_id == request.stage_loss_budget_id
            and int(existing.frozen_budget_cents) == request.frozen_budget_cents
            and (
                existing.research_program_id,
                existing.economic_lineage_id,
                existing.stage_id,
            )
            == identity
            and existing.source_authority == request.source_authority
        )
        if not identical:
            raise _conflict(
                "payload_conflict",
                "stage-loss activation idempotency key already committed with"
                " different content",
                idempotency_key=request.idempotency_key,
            )
        return context.read_capital_risk_snapshot(request.as_of)

    if _stage_loss_row(context, identity) is not None:
        raise _conflict(
            "stage_loss_budget_conflict",
            "this stage identity already has a frozen budget; relabel, epoch"
            " change or re-authorization can never reset it",
            research_program_id=identity[0],
            economic_lineage_id=identity[1],
            stage_id=identity[2],
        )

    expected = request.expected_stage_loss_state_version
    actual = _stage_loss_meta_version(context)
    if actual != expected:
        raise _conflict(
            "stage_loss_version_mismatch",
            "compare-and-swap failed: the stage-loss state advanced",
            expected=expected,
            actual=actual,
        )

    now = utc_iso(request.as_of)
    conn.execute(
        activations_table.insert().values(
            stage_loss_budget_id=request.stage_loss_budget_id,
            idempotency_key=request.idempotency_key,
            research_program_id=request.research_program_id,
            economic_lineage_id=request.economic_lineage_id,
            stage_id=request.stage_id,
            frozen_budget_cents=request.frozen_budget_cents,
            source_authority=request.source_authority,
            authorization_reference=request.authorization_reference,
            activated_at=now,
        )
    )
    conn.execute(
        context._table("stage_loss_state").insert().values(
            research_program_id=request.research_program_id,
            economic_lineage_id=request.economic_lineage_id,
            stage_id=request.stage_id,
            stage_loss_budget_id=request.stage_loss_budget_id,
            frozen_budget_cents=request.frozen_budget_cents,
            consumed_cents=0,
            stage_loss_version=1,
            state=StageLossLatchState.CLEAR.value,
            updated_at=now,
        )
    )
    _bump_capital_version(context, None, request.as_of)
    _bump_stage_loss_meta(context, request.as_of)
    context.recompute_risk_and_stage_loss(
        request.as_of, f"stage-loss-activation:{request.idempotency_key}"
    )
    return context.read_capital_risk_snapshot(request.as_of)


def record_stage_loss(
    context: "GatewayTransactionContext", request: StageLossChargeRequest
) -> tuple[StageLossChargeReceipt, CapitalRiskSnapshot]:
    """Consume one attributed stage-loss charge monotonically."""

    conn = context._connection
    charges_table = context._table("stage_loss_charges")
    identity = request.identity
    existing = conn.execute(
        charges_table.select().where(
            charges_table.c.idempotency_key == request.idempotency_key
        )
    ).first()
    if existing is not None:
        expected_fingerprint = _charge_content_fingerprint(
            identity=identity,
            source_authority=request.source_authority,
            realized=request.realized_market_losses_ex_fees_cents,
            fees=request.cumulative_fees_and_taxes_cents,
            unrealized=request.marked_unrealized_pnl_cents,
            stress=request.incremental_pending_stress_beyond_mark_cents,
        )
        if existing.payload_content_fingerprint != expected_fingerprint:
            raise _conflict(
                "payload_conflict",
                "stage-loss charge idempotency key already committed with"
                " different content",
                idempotency_key=request.idempotency_key,
            )
        projection = context.projection_row()
        receipt = StageLossChargeReceipt(
            idempotency_key=request.idempotency_key,
            research_program_id=existing.research_program_id,
            economic_lineage_id=existing.economic_lineage_id,
            stage_id=existing.stage_id,
            instantaneous_charge_cents=int(existing.instantaneous_charge_cents),
            consumed_before_cents=int(existing.consumed_before_cents),
            consumed_after_cents=int(existing.consumed_after_cents),
            frozen_budget_cents=int(existing.frozen_budget_cents),
            remaining_budget_cents=max(
                0,
                int(existing.frozen_budget_cents)
                - int(existing.consumed_after_cents),
            ),
            stage_loss_version=int(existing.stage_loss_version_after),
            state=StageLossLatchState(existing.latch_state_after),
            capital_version=int(projection.capital_version),
            stage_loss_state_version=_stage_loss_meta_version(context),
        )
        return receipt, context.read_capital_risk_snapshot(request.as_of)

    state_row = _stage_loss_row(context, identity)
    if state_row is None:
        raise _conflict(
            "stage_loss_budget_unknown",
            "stage loss cannot be charged against an unfrozen budget",
            research_program_id=identity[0],
            economic_lineage_id=identity[1],
            stage_id=identity[2],
        )

    expected = request.expected_stage_loss_state_version
    actual = _stage_loss_meta_version(context)
    if actual != expected:
        raise _conflict(
            "stage_loss_version_mismatch",
            "compare-and-swap failed: the stage-loss state advanced",
            expected=expected,
            actual=actual,
        )

    consumed_before = int(state_row.consumed_cents)
    frozen_budget = int(state_row.frozen_budget_cents)
    instantaneous = request.instantaneous_charge_cents
    # The non-replenishable core: consumption only advances upward. Profit,
    # rebound, fee refunds or restatements never reduce consumed budget.
    consumed_after = max(consumed_before, instantaneous)
    version_before = int(state_row.stage_loss_version)
    version_after = version_before + 1
    state_after = (
        StageLossLatchState.STAGE_LOSS_HALTED
        if consumed_after >= frozen_budget
        else StageLossLatchState.CLEAR
    )
    capital_version = _bump_capital_version(
        context, derive_stage_loss_charge_id(request.idempotency_key), request.as_of
    )
    _insert_stage_loss_charge(
        context,
        idempotency_key=request.idempotency_key,
        identity=identity,
        source_authority=request.source_authority,
        realized=request.realized_market_losses_ex_fees_cents,
        fees=request.cumulative_fees_and_taxes_cents,
        unrealized=request.marked_unrealized_pnl_cents,
        stress=request.incremental_pending_stress_beyond_mark_cents,
        instantaneous=instantaneous,
        consumed_before=consumed_before,
        consumed_after=consumed_after,
        frozen_budget=frozen_budget,
        version_before=version_before,
        version_after=version_after,
        state_after=state_after,
        capital_version=capital_version,
        as_of=request.as_of,
    )
    context._connection.execute(
        sa.text(
            "UPDATE stage_loss_state SET consumed_cents = :consumed,"
            " stage_loss_version = :version, state = :state,"
            " updated_at = :updated_at"
            " WHERE research_program_id = :program"
            " AND economic_lineage_id = :lineage AND stage_id = :stage"
        ),
        {
            "consumed": consumed_after,
            "version": version_after,
            "state": state_after.value,
            "updated_at": utc_iso(request.as_of),
            "program": identity[0],
            "lineage": identity[1],
            "stage": identity[2],
        },
    )
    stage_meta_version = _bump_stage_loss_meta(context, request.as_of)
    context.recompute_risk_and_stage_loss(
        request.as_of, f"stage-loss-charge:{request.idempotency_key}"
    )
    receipt = StageLossChargeReceipt(
        idempotency_key=request.idempotency_key,
        research_program_id=identity[0],
        economic_lineage_id=identity[1],
        stage_id=identity[2],
        instantaneous_charge_cents=instantaneous,
        consumed_before_cents=consumed_before,
        consumed_after_cents=consumed_after,
        frozen_budget_cents=frozen_budget,
        remaining_budget_cents=max(0, frozen_budget - consumed_after),
        stage_loss_version=version_after,
        state=state_after,
        capital_version=capital_version,
        stage_loss_state_version=stage_meta_version,
    )
    return receipt, context.read_capital_risk_snapshot(request.as_of)


def recompute_global_stage_loss_floor(
    context: "GatewayTransactionContext", as_of, fact_key: str
) -> None:
    """Consume the derived worst-case floor on the global budget.

    Runs inside the same capital transaction as every fill/fee/mark/reserve
    fact. Cumulative fees and mark-to-market unrealized loss carry no stage
    attribution in the ledger, so they land in the most conservative budget:
    the portfolio-global row when governance has frozen one.

    The unrealized component is measurable only while the newest as-observed
    valuation covers every open position. Unknown marks block new risk via
    snapshot rejection (fail closed) instead of fabricating a loss charge;
    once the mark set is complete again the monotone floor catches up, so
    measurable loss is never under-reported.
    """

    conn = context._connection
    global_row = _stage_loss_row(context, GLOBAL_STAGE_LOSS_IDENTITY)
    if global_row is None:
        return
    fees_total = int(
        conn.execute(
            sa.text(
                "SELECT COALESCE(SUM(l.cash_amount_cents), 0) AS total"
                " FROM economic_event_legs l"
                " JOIN economic_events e"
                " ON e.economic_event_id = l.economic_event_id"
                " WHERE e.event_kind = 'FEE_CHARGED'"
                " AND l.asset_kind = 'CASH' AND l.direction = 'DEBIT'"
            )
        ).one().total
    )
    # Fee bust/correction revisions book signed deltas against the charged
    # streams; the floor consumes the net charged fee, refunds included
    # (consumption itself stays monotone below).
    fee_revision_rows = conn.execute(
        sa.text(
            "SELECT e.payload_json AS payload_json"
            " FROM execution_revisions er"
            " JOIN economic_events e"
            " ON e.payload_content_hash = er.payload_content_hash"
            " WHERE er.revision_kind IN ('FEE_BUST', 'FEE_CORRECTION')"
        )
    ).all()
    for row in fee_revision_rows:
        fact = json.loads(row.payload_json).get("execution_revision") or {}
        fees_total += int(fact.get("fee_commission_delta_cents") or 0)
        fees_total += int(fact.get("fee_stamp_tax_delta_cents") or 0)
        fees_total += int(fact.get("fee_transfer_fee_delta_cents") or 0)
    open_rows = context.open_position_rows()
    latest = context.latest_valuation_event()
    marks = latest[1] if latest is not None else {}
    unrealized_charge = 0
    marked_gross = 0
    basis_total = 0
    if not open_rows or (
        latest is not None
        and all(row.security_id in marks for row in open_rows)
    ):
        for row in open_rows:
            marked_gross += round_half_even_div(
                int(row.settled_quantity_units) * marks.get(row.security_id, 0),
                MICROS_PER_CENT,
            )
            basis_total += int(row.cost_basis_cents)
        unrealized_charge = max(0, basis_total - marked_gross)
    floor = fees_total + unrealized_charge
    consumed = int(global_row.consumed_cents)
    if floor <= consumed:
        return

    frozen_budget = int(global_row.frozen_budget_cents)
    version_before = int(global_row.stage_loss_version)
    version_after = version_before + 1
    state_after = (
        StageLossLatchState.STAGE_LOSS_HALTED
        if floor >= frozen_budget
        else StageLossLatchState.CLEAR
    )
    floor_key = stage_loss_floor_idempotency_key(fact_key, floor)
    charges_table = context._table("stage_loss_charges")
    already = conn.execute(
        charges_table.select().where(
            charges_table.c.idempotency_key == floor_key
        )
    ).first()
    if already is None:
        _insert_stage_loss_charge(
            context,
            idempotency_key=floor_key,
            identity=GLOBAL_STAGE_LOSS_IDENTITY,
            source_authority="kernel.stage-loss-floor",
            realized=0,
            fees=fees_total,
            unrealized=marked_gross - basis_total,
            stress=0,
            instantaneous=floor,
            consumed_before=consumed,
            consumed_after=floor,
            frozen_budget=frozen_budget,
            version_before=version_before,
            version_after=version_after,
            state_after=state_after,
            capital_version=int(context.projection_row().capital_version),
            as_of=as_of,
        )
    conn.execute(
        sa.text(
            "UPDATE stage_loss_state SET consumed_cents = :consumed,"
            " stage_loss_version = :version, state = :state,"
            " updated_at = :updated_at"
            " WHERE research_program_id = :program"
            " AND economic_lineage_id = :lineage AND stage_id = :stage"
        ),
        {
            "consumed": floor,
            "version": version_after,
            "state": state_after.value,
            "updated_at": utc_iso(as_of),
            "program": GLOBAL_STAGE_LOSS_IDENTITY[0],
            "lineage": GLOBAL_STAGE_LOSS_IDENTITY[1],
            "stage": GLOBAL_STAGE_LOSS_IDENTITY[2],
        },
    )
    _bump_stage_loss_meta(context, as_of)


# ---------------------------------------------------------------------------
# Session sealing
# ---------------------------------------------------------------------------


def close_risk_snapshot(
    context: "GatewayTransactionContext", request: CloseRiskSnapshotRequest
) -> tuple[RiskSnapshotCloseReceipt, CapitalRiskSnapshot]:
    """Seal the session snapshot as one append-only RISK_SNAPSHOT record."""

    snapshot = build_capital_risk_snapshot(
        context,
        BuildRiskSnapshotRequest(
            as_of=request.as_of,
            authorized_mark_authorities=request.authorized_mark_authorities,
        ),
    )
    seals_table = context._table("risk_snapshot_seals")
    existing = context._connection.execute(
        seals_table.select().where(
            (seals_table.c.portfolio_id == snapshot.portfolio_id)
            & (seals_table.c.session == request.session.isoformat())
        )
    ).first()
    if existing is not None:
        if existing.snapshot_content_hash != snapshot.content_hash():
            raise _conflict(
                "risk_snapshot_close_conflict",
                "this session already sealed a different snapshot; capital"
                " truth moved after the seal and the close diverges",
                session=request.session.isoformat(),
                sealed_content_hash=existing.snapshot_content_hash,
                current_content_hash=snapshot.content_hash(),
            )
        sealed = CapitalRiskSnapshot.model_validate_json(existing.snapshot_json)
        receipt = RiskSnapshotCloseReceipt(
            risk_snapshot_seal_id=existing.risk_snapshot_seal_id,
            risk_snapshot_id=existing.risk_snapshot_id,
            session=request.session,
            capital_version=int(existing.capital_version),
            stream_version=int(existing.stream_version),
            snapshot_content_hash=existing.snapshot_content_hash,
            entry_scaling_multiplier_ppm=int(
                existing.entry_scaling_multiplier_ppm
            ),
            already_sealed=True,
            as_of=parse_utc(existing.as_of),
        )
        return receipt, sealed

    seal_id = derive_risk_snapshot_seal_id(
        snapshot.portfolio_id, request.session
    )
    content_hash = snapshot.content_hash()
    multiplier = entry_scaling_multiplier_ppm(snapshot.active_epoch_drawdown_ppm)
    context._connection.execute(
        seals_table.insert().values(
            risk_snapshot_seal_id=seal_id,
            portfolio_id=snapshot.portfolio_id,
            session=request.session.isoformat(),
            risk_snapshot_id=snapshot.risk_snapshot_id,
            capital_version=snapshot.capital_version,
            stream_version=context.current_stream_version(),
            snapshot_content_hash=content_hash,
            snapshot_json=snapshot.model_dump_json(),
            entry_scaling_multiplier_ppm=multiplier,
            as_of=utc_iso(request.as_of),
            sealed_at=utc_iso(request.as_of),
            source_authority=request.source_authority,
        )
    )
    receipt = RiskSnapshotCloseReceipt(
        risk_snapshot_seal_id=seal_id,
        risk_snapshot_id=snapshot.risk_snapshot_id,
        session=request.session,
        capital_version=snapshot.capital_version,
        stream_version=context.current_stream_version(),
        snapshot_content_hash=content_hash,
        entry_scaling_multiplier_ppm=multiplier,
        already_sealed=False,
        as_of=request.as_of,
    )
    return receipt, snapshot


__all__ = [
    "DRAWDOWN_SCALE_BAND_PPM",
    "DRAWDOWN_SCALE_START_PPM",
    "GLOBAL_STAGE_LOSS_IDENTITY",
    "BuildRiskSnapshotRequest",
    "CloseRiskSnapshotRequest",
    "RiskSnapshotCloseReceipt",
    "StageLossBudgetActivationRequest",
    "StageLossChargeReceipt",
    "StageLossChargeRequest",
    "activate_stage_loss_budget",
    "build_capital_risk_snapshot",
    "close_risk_snapshot",
    "derive_risk_snapshot_seal_id",
    "derive_stage_loss_charge_id",
    "entry_scaling_multiplier_ppm",
    "record_stage_loss",
    "recompute_global_stage_loss_floor",
    "require_valid_marks",
    "stage_loss_floor_idempotency_key",
]
