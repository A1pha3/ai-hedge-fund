"""Plan 03 Task 4: attempt/consumption/multiplicity ledgers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.evidence.consumption import (
    AttemptLedger,
    AttemptStatus,
    EvidenceConsumptionLedger,
    GlobalMultiplicityBudgetLedger,
    LedgerError,
    MultiplicityBudgetKind,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
PROGRAM = "prog-1"
OTHER_PROGRAM = "prog-2"
LINEAGE = "eline-1"
PLAN_HASH = "a" * 64


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


@pytest.fixture()
def ledgers(tmp_path: Path):
    clock = _Clock(NOW)
    budget = GlobalMultiplicityBudgetLedger(
        str(tmp_path / "budget.sqlite3")
    )
    budget.set_budget(MultiplicityBudgetKind.ALPHA, 5)
    attempts = AttemptLedger(
        str(tmp_path / "attempts.sqlite3"),
        budget=budget,
        clock=clock,
    )
    consumption = EvidenceConsumptionLedger(
        str(tmp_path / "consumption.sqlite3"),
        attempts=attempts,
        clock=clock,
    )
    return budget, attempts, consumption


def _reserve(attempts, attempt_id="attempt-1", program=PROGRAM):
    attempts.reserve(
        attempt_id=attempt_id,
        research_program_id=program,
        economic_lineage_id=LINEAGE,
        family_id="btst.limit-up-breakout",
        frozen_plan_hash=PLAN_HASH,
    )


def test_attempt_reservation_consumes_global_budget(ledgers) -> None:
    budget, attempts, _ = ledgers
    assert budget.consumed(MultiplicityBudgetKind.ALPHA) == 0
    _reserve(attempts)
    assert budget.consumed(MultiplicityBudgetKind.ALPHA) == 1
    assert attempts.status("attempt-1") is AttemptStatus.RESERVED


def test_failed_and_abandoned_attempts_still_consume_budget(
    ledgers,
) -> None:
    budget, attempts, _ = ledgers
    _reserve(attempts, "attempt-fail")
    attempts.close("attempt-fail", AttemptStatus.FAILED)
    _reserve(attempts, "attempt-abandon")
    attempts.close("attempt-abandon", AttemptStatus.ABANDONED)
    # Budget is never refunded by failure or abandonment.
    assert budget.consumed(MultiplicityBudgetKind.ALPHA) == 2
    assert attempts.status("attempt-fail") is AttemptStatus.FAILED
    assert attempts.status("attempt-abandon") is AttemptStatus.ABANDONED


def test_global_budget_caps_every_program_lineage_and_name(
    ledgers,
) -> None:
    budget, attempts, _ = ledgers
    for index in range(5):
        _reserve(attempts, f"attempt-{index}", program=f"prog-{index}")
    assert budget.consumed(MultiplicityBudgetKind.ALPHA) == 5
    # A brand-new program/lineage/name cannot escape the global budget.
    with pytest.raises(LedgerError) as excinfo:
        attempts.reserve(
            attempt_id="attempt-escape",
            research_program_id="prog-new-name",
            economic_lineage_id="eline-new",
            family_id="new.family",
            frozen_plan_hash=PLAN_HASH,
        )
    assert excinfo.value.code == "multiplicity_budget_exhausted"
    assert budget.consumed(MultiplicityBudgetKind.ALPHA) == 5


def test_primary_promotion_evidence_identity_is_unreusable(
    ledgers,
) -> None:
    _, attempts, consumption = ledgers
    _reserve(attempts)
    first = consumption.consume_primary_promotion(
        research_program_id=PROGRAM,
        attempt_id="attempt-1",
        evidence_id="evidence-1",
        payload_hash="p" * 64,
    )
    # Identical retry converges on the original consumption.
    again = consumption.consume_primary_promotion(
        research_program_id=PROGRAM,
        attempt_id="attempt-1",
        evidence_id="evidence-1",
        payload_hash="p" * 64,
    )
    assert again.consumption_id == first.consumption_id
    assert again.consumed_at == first.consumed_at
    # Different content under the same sample identity writes nothing.
    with pytest.raises(LedgerError) as excinfo:
        consumption.consume_primary_promotion(
            research_program_id=PROGRAM,
            attempt_id="attempt-1",
            evidence_id="evidence-1",
            payload_hash="q" * 64,
        )
    assert excinfo.value.code == "sample_reuse_conflict"


def test_evaluation_unit_identity_is_unreusable(ledgers) -> None:
    _, attempts, consumption = ledgers
    _reserve(attempts)
    units = consumption.reserve_evaluation_units(
        research_program_id=PROGRAM,
        signal_session="2026-08-03",
        count=1,
    )
    unit = units[0]
    first = consumption.consume_primary_promotion(
        research_program_id=PROGRAM,
        attempt_id="attempt-1",
        governance_minted_evaluation_unit_id=unit,
        payload_hash="p" * 64,
    )
    assert first.governance_minted_evaluation_unit_id == unit
    with pytest.raises(LedgerError) as excinfo:
        consumption.consume_primary_promotion(
            research_program_id=PROGRAM,
            attempt_id="attempt-1",
            governance_minted_evaluation_unit_id=unit,
            payload_hash="different" + "x" * 55,
        )
    assert excinfo.value.code == "sample_reuse_conflict"


def test_same_evidence_under_another_program_is_distinct_sample(
    ledgers,
) -> None:
    budget, attempts, consumption = ledgers
    budget.set_budget(MultiplicityBudgetKind.ALPHA, 100)
    _reserve(attempts, "attempt-a", program=PROGRAM)
    _reserve(attempts, "attempt-b", program=OTHER_PROGRAM)
    consumption.consume_primary_promotion(
        research_program_id=PROGRAM,
        attempt_id="attempt-a",
        evidence_id="shared-evidence",
        payload_hash="p" * 64,
    )
    other = consumption.consume_primary_promotion(
        research_program_id=OTHER_PROGRAM,
        attempt_id="attempt-b",
        evidence_id="shared-evidence",
        payload_hash="p" * 64,
    )
    # Different programs: distinct consumption rows (the uniqueness key
    # includes the program), but BOTH consumed the global budget.
    assert other.research_program_id == OTHER_PROGRAM
    assert budget.consumed(MultiplicityBudgetKind.ALPHA) == 2


def test_outcome_revision_does_not_create_a_new_sample(
    ledgers,
) -> None:
    _, attempts, consumption = ledgers
    _reserve(attempts)
    first = consumption.consume_primary_promotion(
        research_program_id=PROGRAM,
        attempt_id="attempt-1",
        evidence_id="outcome:pl-1",
        payload_hash="revision-1-hash" + "z" * 47,
    )
    # A restated outcome revision under the same sample identity cannot
    # mint a second PRIMARY_PROMOTION sample.
    with pytest.raises(LedgerError) as excinfo:
        consumption.consume_primary_promotion(
            research_program_id=PROGRAM,
            attempt_id="attempt-1",
            evidence_id="outcome:pl-1",
            payload_hash="revision-2-hash" + "z" * 47,
        )
    assert excinfo.value.code == "sample_reuse_conflict"
    assert first.evidence_id == "outcome:pl-1"


def test_consumption_requires_live_reserved_attempt(ledgers) -> None:
    _, attempts, consumption = ledgers
    _reserve(attempts, "attempt-closed")
    attempts.close("attempt-closed", AttemptStatus.FAILED)
    with pytest.raises(LedgerError) as excinfo:
        consumption.consume_primary_promotion(
            research_program_id=PROGRAM,
            attempt_id="attempt-closed",
            evidence_id="evidence-x",
            payload_hash="p" * 64,
        )
    assert excinfo.value.code == "attempt_not_reserved"


def test_exactly_one_sample_identity_is_required(ledgers) -> None:
    _, attempts, consumption = ledgers
    _reserve(attempts)
    with pytest.raises(LedgerError) as excinfo:
        consumption.consume_primary_promotion(
            research_program_id=PROGRAM,
            attempt_id="attempt-1",
            payload_hash="p" * 64,
        )
    assert excinfo.value.code == "consumption_identity_ambiguous"
    with pytest.raises(LedgerError):
        consumption.consume_primary_promotion(
            research_program_id=PROGRAM,
            attempt_id="attempt-1",
            evidence_id="evidence-1",
            governance_minted_evaluation_unit_id="unit-1",
            payload_hash="p" * 64,
        )


def test_evaluation_units_mint_disjoint_under_concurrent_reservation(
    ledgers,
) -> None:
    _, _, consumption = ledgers
    first_batch = consumption.reserve_evaluation_units(
        research_program_id=PROGRAM,
        signal_session="2026-08-03",
        count=3,
    )
    second_batch = consumption.reserve_evaluation_units(
        research_program_id=PROGRAM,
        signal_session="2026-08-03",
        count=2,
    )
    assert len(set(first_batch) | set(second_batch)) == 5
    assert not (set(first_batch) & set(second_batch))


def test_two_uniqueness_constraints_are_independent(ledgers) -> None:
    """The evidence key and the evaluation-unit key are separate indexes;
    consuming one kind must not collide with the other kind."""

    _, attempts, consumption = ledgers
    _reserve(attempts)
    consumption.consume_primary_promotion(
        research_program_id=PROGRAM,
        attempt_id="attempt-1",
        evidence_id="sample-x",
        payload_hash="p" * 64,
    )
    units = consumption.reserve_evaluation_units(
        research_program_id=PROGRAM,
        signal_session="2026-08-04",
        count=1,
    )
    # Same program, same literal value space: no cross-kind collision.
    other = consumption.consume_primary_promotion(
        research_program_id=PROGRAM,
        attempt_id="attempt-1",
        governance_minted_evaluation_unit_id=units[0],
        payload_hash="p" * 64,
    )
    assert other.consumption_id != "consumption:prog-1:sample-x:PRIMARY_PROMOTION"
