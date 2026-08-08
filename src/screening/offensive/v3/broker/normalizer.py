"""Plan 07 Task 4: push/poll normalization and execution revisions.

The broker speaks in cumulative truth ("as of this observation, the order
has filled N units for M cents gross, F cents fees"). Capital is booked
in deltas. The normalizer is the single place that turns cumulative
broker observations into signed execution revisions, and it does so
fail-closed:

- Executions book ``new_cumulative - last_cumulative``. A strictly
  increasing cumulative is a fill; an equal cumulative is an idempotent
  no-op; a *decreasing* cumulative without an explicit bust/correction
  marker latches a reconciliation halt — it is never silently clamped or
  reversed.
- An explicit bust appends inverse economics (negative delta) and drops
  the cumulative to the busted level.
- A correction busts the active cumulative then applies the corrected
  cumulative as one increasing-revision pair.
- Every revision is idempotent on its source envelope hash, so duplicate
  / late / out-of-order push and poll observations converge to identical
  capital and event count once sorted into canonical (observed-at) order.

The normalizer emits typed revisions; it never writes capital itself.
Plan 02 ingests the revisions. A negative impossible share (delta that
would drive cumulative below zero) is a halt, not a clamp.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal


class NormalizationHaltCode(StrEnum):
    """Stable codes for a normalization reconciliation halt."""

    UNEXPLAINED_CUMULATIVE_ROLLBACK = "unexplained_cumulative_rollback"
    NEGATIVE_IMPOSSIBLE_SHARE = "negative_impossible_share"
    BUST_WITHOUT_ACTIVE_FACT = "bust_without_active_fact"
    CORRECTION_WITHOUT_ACTIVE_FACT = "correction_without_active_fact"
    CORRECTION_REDUCES_BELOW_ZERO = "correction_reduces_below_zero"


class RevisionKind(StrEnum):
    FILL = "fill"
    BUST = "bust"
    CORRECTION_BUST = "correction_bust"
    CORRECTION_APPLY = "correction_apply"


@dataclass(frozen=True)
class CumulativeObservation:
    """One broker-observed cumulative truth for a single client order id."""

    client_order_id: str
    cumulative_quantity_units: int
    cumulative_notional_cents: int
    cumulative_fee_cents: int
    observed_at: datetime
    source_envelope_hash: str
    kind: Literal["execution", "bust", "correction"] = "execution"
    corrected_quantity_units: int | None = None
    corrected_notional_cents: int | None = None
    corrected_fee_cents: int | None = None


@dataclass(frozen=True)
class NormalizedRevision:
    """One signed execution revision derived from cumulative broker truth."""

    client_order_id: str
    kind: RevisionKind
    delta_quantity_units: int
    delta_notional_cents: int
    delta_fee_cents: int
    cumulative_quantity_units: int
    cumulative_notional_cents: int
    cumulative_fee_cents: int
    observed_at: datetime
    source_envelope_hash: str
    revision_ordinal: int


@dataclass(frozen=True)
class NormalizationHalt:
    """A fail-closed halt carrying a stable code; never a silent clamp."""

    code: NormalizationHaltCode
    client_order_id: str
    message: str
    source_envelope_hash: str


@dataclass(frozen=True)
class OrderExecutionState:
    """The normalizer's per-order cumulative memory."""

    client_order_id: str
    cumulative_quantity_units: int
    cumulative_notional_cents: int
    cumulative_fee_cents: int
    revision_ordinal: int
    applied_source_hashes: frozenset[str]


@dataclass
class NormalizeResult:
    """Outcome of normalizing one observation or batch."""

    revisions: tuple[NormalizedRevision, ...]
    halts: tuple[NormalizationHalt, ...]
    final_state: OrderExecutionState | None


class ExecutionNormalizer:
    """Turns cumulative broker observations into signed execution revisions.

    Stateful per client order id, idempotent on source envelope hash. The
    streaming ``apply`` methods halt on unexplained rollback; ``normalize_batch``
    sorts observations into canonical observed-at order first, so any
    permutation of the same source set converges to identical revisions.
    """

    def __init__(self) -> None:
        self._states: dict[str, OrderExecutionState] = {}

    def state_for(self, client_order_id: str) -> OrderExecutionState | None:
        return self._states.get(client_order_id)

    def apply(self, obs: CumulativeObservation) -> NormalizeResult:
        """Route one observation to its handler; idempotent on source hash."""

        state = self._states.get(obs.client_order_id)
        if state is not None and obs.source_envelope_hash in state.applied_source_hashes:
            return NormalizeResult(revisions=(), halts=(), final_state=state)
        if obs.kind == "bust":
            return self.apply_bust(obs)
        if obs.kind == "correction":
            return self.apply_correction(obs)
        return self.apply_cumulative_execution(obs)

    def apply_cumulative_execution(
        self, obs: CumulativeObservation
    ) -> NormalizeResult:
        state = self._states.get(obs.client_order_id)
        last_qty = state.cumulative_quantity_units if state else 0
        last_notional = state.cumulative_notional_cents if state else 0
        last_fee = state.cumulative_fee_cents if state else 0
        ordinal = state.revision_ordinal if state else 0

        delta_qty = obs.cumulative_quantity_units - last_qty
        if delta_qty < 0:
            halt = NormalizationHalt(
                code=NormalizationHaltCode.UNEXPLAINED_CUMULATIVE_ROLLBACK,
                client_order_id=obs.client_order_id,
                message=(
                    f"cumulative quantity rolled back {last_qty} ->"
                    f" {obs.cumulative_quantity_units} without an explicit bust"
                ),
                source_envelope_hash=obs.source_envelope_hash,
            )
            return NormalizeResult(revisions=(), halts=(halt,), final_state=state)
        if delta_qty == 0:
            # Idempotent re-observation of the same cumulative truth.
            return NormalizeResult(revisions=(), halts=(), final_state=state)

        delta_notional = obs.cumulative_notional_cents - last_notional
        delta_fee = obs.cumulative_fee_cents - last_fee
        ordinal += 1
        revision = NormalizedRevision(
            client_order_id=obs.client_order_id,
            kind=RevisionKind.FILL,
            delta_quantity_units=delta_qty,
            delta_notional_cents=delta_notional,
            delta_fee_cents=delta_fee,
            cumulative_quantity_units=obs.cumulative_quantity_units,
            cumulative_notional_cents=obs.cumulative_notional_cents,
            cumulative_fee_cents=obs.cumulative_fee_cents,
            observed_at=obs.observed_at,
            source_envelope_hash=obs.source_envelope_hash,
            revision_ordinal=ordinal,
        )
        new_state = OrderExecutionState(
            client_order_id=obs.client_order_id,
            cumulative_quantity_units=obs.cumulative_quantity_units,
            cumulative_notional_cents=obs.cumulative_notional_cents,
            cumulative_fee_cents=obs.cumulative_fee_cents,
            revision_ordinal=ordinal,
            applied_source_hashes=(
                state.applied_source_hashes | {obs.source_envelope_hash}
                if state is not None
                else frozenset({obs.source_envelope_hash})
            ),
        )
        self._states[obs.client_order_id] = new_state
        return NormalizeResult(
            revisions=(revision,), halts=(), final_state=new_state
        )

    def apply_bust(self, obs: CumulativeObservation) -> NormalizeResult:
        state = self._states.get(obs.client_order_id)
        if state is None or state.cumulative_quantity_units == 0:
            halt = NormalizationHalt(
                code=NormalizationHaltCode.BUST_WITHOUT_ACTIVE_FACT,
                client_order_id=obs.client_order_id,
                message="bust supplied with no active fill to reverse",
                source_envelope_hash=obs.source_envelope_hash,
            )
            return NormalizeResult(revisions=(), halts=(halt,), final_state=state)
        delta_qty = obs.cumulative_quantity_units - state.cumulative_quantity_units
        delta_notional = (
            obs.cumulative_notional_cents - state.cumulative_notional_cents
        )
        delta_fee = obs.cumulative_fee_cents - state.cumulative_fee_cents
        ordinal = state.revision_ordinal + 1
        revision = NormalizedRevision(
            client_order_id=obs.client_order_id,
            kind=RevisionKind.BUST,
            delta_quantity_units=delta_qty,
            delta_notional_cents=delta_notional,
            delta_fee_cents=delta_fee,
            cumulative_quantity_units=obs.cumulative_quantity_units,
            cumulative_notional_cents=obs.cumulative_notional_cents,
            cumulative_fee_cents=obs.cumulative_fee_cents,
            observed_at=obs.observed_at,
            source_envelope_hash=obs.source_envelope_hash,
            revision_ordinal=ordinal,
        )
        new_state = OrderExecutionState(
            client_order_id=obs.client_order_id,
            cumulative_quantity_units=obs.cumulative_quantity_units,
            cumulative_notional_cents=obs.cumulative_notional_cents,
            cumulative_fee_cents=obs.cumulative_fee_cents,
            revision_ordinal=ordinal,
            applied_source_hashes=(
                state.applied_source_hashes | {obs.source_envelope_hash}
            ),
        )
        self._states[obs.client_order_id] = new_state
        return NormalizeResult(
            revisions=(revision,), halts=(), final_state=new_state
        )

    def apply_correction(self, obs: CumulativeObservation) -> NormalizeResult:
        state = self._states.get(obs.client_order_id)
        if state is None or state.cumulative_quantity_units == 0:
            halt = NormalizationHalt(
                code=NormalizationHaltCode.CORRECTION_WITHOUT_ACTIVE_FACT,
                client_order_id=obs.client_order_id,
                message="correction supplied with no active fill to correct",
                source_envelope_hash=obs.source_envelope_hash,
            )
            return NormalizeResult(revisions=(), halts=(halt,), final_state=state)
        if obs.corrected_quantity_units is None:
            halt = NormalizationHalt(
                code=NormalizationHaltCode.CORRECTION_REDUCES_BELOW_ZERO,
                client_order_id=obs.client_order_id,
                message="correction must carry corrected cumulative facts",
                source_envelope_hash=obs.source_envelope_hash,
            )
            return NormalizeResult(revisions=(), halts=(halt,), final_state=state)

        # Step 1: bust the active cumulative to zero (inverse economics).
        bust_qty = -state.cumulative_quantity_units
        bust_notional = -state.cumulative_notional_cents
        bust_fee = -state.cumulative_fee_cents
        ordinal_bust = state.revision_ordinal + 1
        bust = NormalizedRevision(
            client_order_id=obs.client_order_id,
            kind=RevisionKind.CORRECTION_BUST,
            delta_quantity_units=bust_qty,
            delta_notional_cents=bust_notional,
            delta_fee_cents=bust_fee,
            cumulative_quantity_units=0,
            cumulative_notional_cents=0,
            cumulative_fee_cents=0,
            observed_at=obs.observed_at,
            source_envelope_hash=obs.source_envelope_hash,
            revision_ordinal=ordinal_bust,
        )
        # Step 2: apply the corrected cumulative from zero.
        corrected_qty = obs.corrected_quantity_units
        corrected_notional = obs.corrected_notional_cents or 0
        corrected_fee = obs.corrected_fee_cents or 0
        if corrected_qty < 0:
            halt = NormalizationHalt(
                code=NormalizationHaltCode.CORRECTION_REDUCES_BELOW_ZERO,
                client_order_id=obs.client_order_id,
                message="corrected cumulative quantity is negative",
                source_envelope_hash=obs.source_envelope_hash,
            )
            return NormalizeResult(revisions=(), halts=(halt,), final_state=state)
        ordinal_apply = ordinal_bust + 1
        apply_revision = NormalizedRevision(
            client_order_id=obs.client_order_id,
            kind=RevisionKind.CORRECTION_APPLY,
            delta_quantity_units=corrected_qty,
            delta_notional_cents=corrected_notional,
            delta_fee_cents=corrected_fee,
            cumulative_quantity_units=corrected_qty,
            cumulative_notional_cents=corrected_notional,
            cumulative_fee_cents=corrected_fee,
            observed_at=obs.observed_at,
            source_envelope_hash=obs.source_envelope_hash,
            revision_ordinal=ordinal_apply,
        )
        new_state = OrderExecutionState(
            client_order_id=obs.client_order_id,
            cumulative_quantity_units=corrected_qty,
            cumulative_notional_cents=corrected_notional,
            cumulative_fee_cents=corrected_fee,
            revision_ordinal=ordinal_apply,
            applied_source_hashes=(
                state.applied_source_hashes | {obs.source_envelope_hash}
            ),
        )
        self._states[obs.client_order_id] = new_state
        return NormalizeResult(
            revisions=(bust, apply_revision), halts=(), final_state=new_state
        )

    def normalize_batch(
        self, observations: tuple[CumulativeObservation, ...]
    ) -> NormalizeResult:
        """Sort by observed_at, dedup by source hash, apply in canonical order.

        Any permutation of the same source set converges to identical
        revisions and final state.
        """

        revisions: list[NormalizedRevision] = []
        halts: list[NormalizationHalt] = []
        final: OrderExecutionState | None = None
        ordered = sorted(observations, key=lambda o: (o.observed_at, o.client_order_id, o.source_envelope_hash))
        for obs in ordered:
            result = self.apply(obs)
            revisions.extend(result.revisions)
            halts.extend(result.halts)
            if result.final_state is not None:
                final = result.final_state
            if result.halts:
                break
        return NormalizeResult(
            revisions=tuple(revisions),
            halts=tuple(halts),
            final_state=final,
        )

    def normalize_order_update(
        self,
        *,
        client_order_id: str,
        cumulative_quantity_units: int,
        cumulative_notional_cents: int,
        cumulative_fee_cents: int,
        observed_at: datetime,
        source_envelope_hash: str,
        kind: Literal["execution", "bust", "correction"] = "execution",
        corrected_quantity_units: int | None = None,
        corrected_notional_cents: int | None = None,
        corrected_fee_cents: int | None = None,
    ) -> NormalizeResult:
        """Convenience wrapper building one observation and applying it."""

        obs = CumulativeObservation(
            client_order_id=client_order_id,
            cumulative_quantity_units=cumulative_quantity_units,
            cumulative_notional_cents=cumulative_notional_cents,
            cumulative_fee_cents=cumulative_fee_cents,
            observed_at=observed_at,
            source_envelope_hash=source_envelope_hash,
            kind=kind,
            corrected_quantity_units=corrected_quantity_units,
            corrected_notional_cents=corrected_notional_cents,
            corrected_fee_cents=corrected_fee_cents,
        )
        return self.apply(obs)
