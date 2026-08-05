"""Plan 04 Task 2: admission, ranking, capacity, integer sizing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.screening.offensive.v3.contracts import ExecutionMode
from src.screening.offensive.v3.contracts.authorization import (
    AuthorizationKind,
    CapitalAuthorizationEnvelope,
)
from src.screening.offensive.v3.contracts.governance import (
    GrantKind,
    LineageGrant,
    PolicyActivation,
    ProgramLossBudgetBinding,
)
from src.screening.offensive.v3.kernel.admission import (
    BTST_FAMILY,
    OVERSOLD_BOUNCE_FAMILY,
    AdmissionError,
    admit_candidates,
)
from src.screening.offensive.v3.kernel.models import (
    BlockReason,
    RawCandidate,
)
from src.screening.offensive.v3.kernel.sizing import (
    LOT_UNITS,
    SizingConfig,
    decision_lines,
    rank_candidates,
    size_portfolio,
    worst_case_fee_cents,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
HASH = "a" * 64
BEHAVIOR = "b" * 64
PORTFOLIO = "paper-v3"


def _policy_activation() -> PolicyActivation:
    return PolicyActivation(
        portfolio_id=PORTFOLIO,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        policy_snapshot_hash=HASH,
        predecessor_policy_activation_hash="0" * 64,
        trust_bundle_hash=HASH,
        registry_epoch=1,
        policy_epoch=1,
        authority_epoch=1,
        risk_epoch=1,
        effective_from=NOW,
        expires_at=NOW + timedelta(days=1),
        issuer_id="governance.service",
        issuer_capability="governance.policy.activation.v1",
        schema_major=2,
    )


def _grant(**overrides) -> LineageGrant:
    values = {
        "grant_id": "grant-1",
        "grant_kind": GrantKind.EDGE,
        "grant_certificate_hash": HASH,
        "grant_issuer_id": "authorizer.service",
        "subject_producer": "btst",
        "family_id": BTST_FAMILY,
        "economic_lineage_id": "eline-1",
        "research_program_id": "prog-1",
        "behavior_fingerprint": BEHAVIOR,
        "execution_version": "t1-open-t10-open.v1",
        "cost_version": "cn-a-share-costs.v1",
        "capital_tier": 2,
        "lineage_gross_cap": Decimal("0.02"),
        "trial_id": "trial-1",
        "trial_manifest_hash": HASH,
        "statistical_analysis_plan_hash": HASH,
        "stage_id": "stage-1",
        "stage_manifest_hash": HASH,
        "stage_sample_reservation_id": "reservation-1",
        "stage_loss_budget_id": "budget-1",
        "stage_loss_budget_cents": 100_000,
        "stage_loss_version": 1,
        "assessment_result_hash": HASH,
        "grant_evidence_set_merkle_root": HASH,
        "attempt_ledger_checkpoint_hash": HASH,
        "alpha_or_evalue_budget_consumption_id": "consumption-1",
        "alpha_sample_consumption_id": "sample-1",
        "schema_major": 2,
    }
    values.update(overrides)
    return LineageGrant(**values)


def _binding() -> ProgramLossBudgetBinding:
    return ProgramLossBudgetBinding(
        research_program_id="prog-1",
        budget_id="budget-1",
        budget_cents=100_000,
        consumed_cents=0,
        version=1,
        schema_major=2,
    )


def _envelope(policy_activation: PolicyActivation, **overrides):
    values = {
        "authorization_kind": AuthorizationKind.EDGE,
        "authorization_id": "auth-1",
        "authorization_version": 1,
        "mode": ExecutionMode.DAILY_BAR_PROXY,
        "portfolio_id": PORTFOLIO,
        "broker_account_id": None,
        "broker_account_fingerprint": None,
        "base_currency": "CNY",
        "policy_activation_hash": policy_activation.artifact_hash(),
        "trust_bundle_hash": HASH,
        "registry_epoch": 1,
        "policy_epoch": 1,
        "authority_epoch": 1,
        "risk_epoch": 1,
        "research_program_ids": ("prog-1",),
        "baseline_portfolio_policy_fingerprint": HASH,
        "target_portfolio_policy_fingerprint": "c" * 64,
        "lineage_grants": (_grant(),),
        "evidence_as_of": NOW,
        "evidence_set_merkle_root": HASH,
        "issued_at": NOW,
        "expires_at": NOW + timedelta(days=1),
        "activation_capital_snapshot_id": "snapshot-1",
        "activation_capital_snapshot_hash": HASH,
        "portfolio_gross_cap": Decimal("0.02"),
        "exploration_aggregate_gross_cap": Decimal("0"),
        "program_loss_budget_bindings": (_binding(),),
        "issuer_id": "authorizer.service",
        "issuer_capability": "authorizer.edge.envelope.v1",
        "portfolio_assessment_result_hash": HASH,
        "global_attempt_ledger_checkpoint_hash": HASH,
        "global_multiplicity_budget_consumption_id": "consumption-1",
        "schema_major": 2,
    }
    values.update(overrides)
    return CapitalAuthorizationEnvelope(**values)


def _candidate(candidate_id="cand-1", **overrides) -> RawCandidate:
    values = {
        "candidate_id": candidate_id,
        "producer_namespace": "btst",
        "family_id": BTST_FAMILY,
        "economic_lineage_id": "eline-1",
        "research_program_id": "prog-1",
        "stage_id": "stage-1",
        "security_id": "600000.SH",
        "direction": "LONG",
        "unscaled_target_gross_cents": 50_000,
        "behavior_fingerprint": BEHAVIOR,
        "execution_version": "t1-open-t10-open.v1",
        "cost_version": "cn-a-share-costs.v1",
        "evidence_ids": (),
    }
    values.update(overrides)
    return RawCandidate(**values)


@pytest.fixture()
def authority():
    policy = _policy_activation()
    return policy, _envelope(policy)


def _statuses(candidates, authority):
    policy, envelope = authority
    return admit_candidates(
        candidates, policy_activation=policy, envelope=envelope
    )


def test_btst_admits_when_grant_matches(authority) -> None:
    (status,) = _statuses((_candidate(),), authority)
    assert status.status == "ADMITTED"
    assert status.block_reason is None


def test_oversold_bounce_stays_disabled(authority) -> None:
    (status,) = _statuses(
        (_candidate(family_id=OVERSOLD_BOUNCE_FAMILY),), authority
    )
    assert status.status == "BLOCKED"
    assert status.block_reason is BlockReason.NO_SIGNAL


def test_auto_producer_is_shadow_only(authority) -> None:
    (status,) = _statuses(
        (_candidate(producer_namespace="auto"),), authority
    )
    assert status.status == "SHADOW"


def test_unknown_family_or_lineage_never_defaults(authority) -> None:
    statuses = _statuses(
        (
            _candidate("cand-fam", family_id="unknown.family"),
            _candidate("cand-lin", economic_lineage_id="eline-unknown"),
        ),
        authority,
    )
    assert all(s.status == "BLOCKED" for s in statuses)
    assert all(
        s.block_reason is BlockReason.NO_AUTHORIZED_ENVELOPE
        for s in statuses
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        (
            "behavior_fingerprint",
            "f" * 64,
            BlockReason.POLICY_ENVELOPE_MISMATCH,
        ),
        (
            "execution_version",
            "other-exec.v9",
            BlockReason.CAPITAL_VERSION_MISMATCH,
        ),
        (
            "cost_version",
            "other-costs.v9",
            BlockReason.CAPITAL_VERSION_MISMATCH,
        ),
        ("stage_id", "stage-other", BlockReason.CAPITAL_VERSION_MISMATCH),
        (
            "research_program_id",
            "prog-other",
            BlockReason.MODE_MISMATCH,
        ),
    ],
)
def test_grant_mismatches_are_typed_blocks(
    authority, field: str, value, reason: BlockReason
) -> None:
    (status,) = _statuses(
        (_candidate(**{field: value}),), authority
    )
    assert status.status == "BLOCKED"
    assert status.block_reason is reason


def test_policy_envelope_hash_binding_is_enforced(authority) -> None:
    policy, envelope = authority
    broken = envelope.model_copy(update={"policy_activation_hash": "f" * 64})
    with pytest.raises(AdmissionError) as excinfo:
        admit_candidates(
            (_candidate(),), policy_activation=policy, envelope=broken
        )
    assert excinfo.value.code == "policy_envelope_mismatch"


def _config(**overrides) -> SizingConfig:
    values = {
        "per_ticker_gross_cap_cents": 200_000,
        "per_industry_gross_cap_cents": 300_000,
        "per_day_gross_cap_cents": 500_000,
        "portfolio_gross_cap_cents": 400_000,
        "worst_case_fee_ppm": 3_000,
    }
    values.update(overrides)
    return SizingConfig(**values)


def test_rank_is_deterministic_and_input_order_independent() -> None:
    small = _candidate("cand-b", unscaled_target_gross_cents=10_000)
    big = _candidate("cand-a", unscaled_target_gross_cents=90_000)
    tie_a = _candidate("cand-tie-a", unscaled_target_gross_cents=50_000)
    tie_b = _candidate("cand-tie-b", unscaled_target_gross_cents=50_000)
    forward = rank_candidates((small, big, tie_b, tie_a))
    backward = rank_candidates((tie_a, tie_b, big, small))
    assert forward == backward
    assert [c.candidate_id for c in forward] == [
        "cand-a",
        "cand-tie-a",
        "cand-tie-b",
        "cand-b",
    ]


def test_sizing_floors_to_integer_lots_and_reserves_worst_case() -> None:
    candidate = _candidate(
        unscaled_target_gross_cents=105_000,  # 1050.00 CNY
    )
    lines = size_portfolio(
        ranked_candidates=(candidate,),
        adjusted_target_gross_by_lineage={"eline-1": 500_000},
        price_micros_by_candidate={"cand-1": 10_000_000},  # 10.00 CNY
        industry_by_candidate={"cand-1": "electronics"},
        available_cash_cents=1_000_000,
        config=_config(),
    )
    (line,) = lines
    assert line.status == "ENTRY_PLANNED"
    # 105_000 cents at 10.00 => 105 units -> floored to 100.
    assert line.quantity_units == 100
    assert line.quantity_units % LOT_UNITS == 0
    gross = 100 * 10_000_000 // 10_000  # 100_000 cents
    assert line.worst_case_reserve_cents == (
        gross + worst_case_fee_cents(gross, 3_000)
    )


def test_high_price_zero_lot_is_blocked_not_filled() -> None:
    candidate = _candidate(unscaled_target_gross_cents=50_000)  # 500 CNY
    lines = size_portfolio(
        ranked_candidates=(candidate,),
        adjusted_target_gross_by_lineage={"eline-1": 500_000},
        price_micros_by_candidate={"cand-1": 100_000_000},  # 1000 CNY
        industry_by_candidate={"cand-1": "electronics"},
        available_cash_cents=1_000_000,
        config=_config(),
    )
    (line,) = lines
    assert line.status == "BLOCKED"
    assert line.block_reason is BlockReason.LOT_FLOOR_ZERO


def test_missing_price_is_typed_missing_adv() -> None:
    candidate = _candidate()
    lines = size_portfolio(
        ranked_candidates=(candidate,),
        adjusted_target_gross_by_lineage={"eline-1": 50_000},
        price_micros_by_candidate={},
        industry_by_candidate={},
        available_cash_cents=1_000_000,
        config=_config(),
    )
    (line,) = lines
    assert line.block_reason is BlockReason.MISSING_ADV


def test_capacity_caps_constrain_before_cash() -> None:
    candidate = _candidate(unscaled_target_gross_cents=500_000)
    lines = size_portfolio(
        ranked_candidates=(candidate,),
        adjusted_target_gross_by_lineage={"eline-1": 500_000},
        price_micros_by_candidate={"cand-1": 10_000_000},
        industry_by_candidate={"cand-1": "electronics"},
        available_cash_cents=10_000_000,
        config=_config(per_ticker_gross_cap_cents=200_000),
    )
    (line,) = lines
    # Capped at the ticker cap (200_000 cents at 10.00) => 200 units.
    assert line.quantity_units == 200
    assert line.quantity_units * 10_000_000 // 10_000 <= 200_000


def test_cash_constraint_reduces_to_affordable_lots() -> None:
    candidate = _candidate(unscaled_target_gross_cents=500_000)
    lines = size_portfolio(
        ranked_candidates=(candidate,),
        adjusted_target_gross_by_lineage={"eline-1": 500_000},
        price_micros_by_candidate={"cand-1": 10_000_000},
        industry_by_candidate={"cand-1": "electronics"},
        available_cash_cents=150_000,
        config=_config(),
    )
    (line,) = lines
    # Reserve includes worst-case fees; quantity shrinks to what cash
    # covers. Leftover cash is NOT reallocated to other candidates.
    reserve = line.worst_case_reserve_cents
    assert reserve <= 250_000
    assert line.quantity_units % LOT_UNITS == 0


def test_permutation_invariance_of_selected_orders(authority) -> None:
    a = _candidate(
        "cand-a", security_id="600000.SH", unscaled_target_gross_cents=500_000
    )
    b = _candidate(
        "cand-b",
        security_id="600001.SH",
        economic_lineage_id="eline-1",
        unscaled_target_gross_cents=300_000,
    )
    ranked_forward = rank_candidates((a, b))
    ranked_backward = rank_candidates((b, a))
    prices = {"cand-a": 10_000_000, "cand-b": 20_000_000}
    industries = {"cand-a": "electronics", "cand-b": "chemicals"}
    targets = {"eline-1": 500_000}
    forward = size_portfolio(
        ranked_candidates=ranked_forward,
        adjusted_target_gross_by_lineage=targets,
        price_micros_by_candidate=prices,
        industry_by_candidate=industries,
        available_cash_cents=1_000_000,
        config=_config(),
    )
    backward = size_portfolio(
        ranked_candidates=ranked_backward,
        adjusted_target_gross_by_lineage=targets,
        price_micros_by_candidate=prices,
        industry_by_candidate=industries,
        available_cash_cents=1_000_000,
        config=_config(),
    )
    assert forward == backward
    assert all(line.status == "ENTRY_PLANNED" for line in forward)


def test_producer_supplied_target_cannot_bypass_central_caps() -> None:
    # A producer claims a huge unscaled target; the central portfolio cap
    # still bounds the sized gross.
    greedy = _candidate(unscaled_target_gross_cents=10_000_000)
    lines = size_portfolio(
        ranked_candidates=(greedy,),
        adjusted_target_gross_by_lineage={"eline-1": 10_000_000},
        price_micros_by_candidate={"cand-1": 10_000_000},
        industry_by_candidate={"cand-1": "electronics"},
        available_cash_cents=10_000_000,
        config=_config(
            per_ticker_gross_cap_cents=10_000_000,
            per_industry_gross_cap_cents=10_000_000,
            per_day_gross_cap_cents=10_000_000,
            portfolio_gross_cap_cents=800_000,
        ),
    )
    (line,) = lines
    assert line.status == "ENTRY_PLANNED"
    gross = line.quantity_units * 10_000_000 // 10_000
    assert gross <= 800_000


def test_decision_lines_keep_blocked_lines_visible(authority) -> None:
    candidate = _candidate(unscaled_target_gross_cents=50_000)
    lines = size_portfolio(
        ranked_candidates=(candidate,),
        adjusted_target_gross_by_lineage={"eline-1": 500_000},
        price_micros_by_candidate={"cand-1": 100_000_000},
        industry_by_candidate={"cand-1": "electronics"},
        available_cash_cents=1_000_000,
        config=_config(),
    )
    projected = decision_lines(lines)
    (line,) = projected
    assert line.status == "BLOCKED"
    assert line.block_reason is BlockReason.LOT_FLOOR_ZERO
