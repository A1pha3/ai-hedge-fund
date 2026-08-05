"""Plan 03 Task 5: golden tests for conservative portfolio statistics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import exp, log

import pytest

from src.screening.offensive.v3.evidence.statistics import (
    CONFIDENCE_LEVEL,
    MINIMUM_DECISION_DAYS,
    MINIMUM_ESS,
    MINIMUM_MATURE_OUTCOMES,
    MINIMUM_MONTHS,
    MINIMUM_TICKERS,
    OUTER_FOLD_FRACTION,
    MinimumEvidenceReport,
    StatisticsError,
    apply_slippage_drag,
    check_minimum_evidence,
    check_tail_capacity,
    conditional_drawdown_at_risk,
    effective_sample_size,
    evaluate_frozen_policy,
    evaluate_predictable_adaptive,
    excess_daily_log_growth,
    maximum_drawdown,
    one_sided_lower_bound,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
CUTOFF = NOW - timedelta(days=1)


def _nav(*values: float) -> tuple[float, ...]:
    return tuple(values)


def test_excess_daily_log_growth_golden() -> None:
    unit = _nav(1.0, 1.02, 1.01)
    bench = _nav(1.0, 1.01, 1.015)
    growth = excess_daily_log_growth(unit, bench)
    assert len(growth) == 2
    assert growth[0] == pytest.approx(log(1.02 / 1.0) - log(1.01 / 1.0))
    assert growth[1] == pytest.approx(log(1.01 / 1.02) - log(1.015 / 1.01))


def test_excess_growth_rejects_misaligned_or_short_series() -> None:
    with pytest.raises(StatisticsError):
        excess_daily_log_growth((1.0, 1.1), (1.0,))
    with pytest.raises(StatisticsError):
        excess_daily_log_growth((1.0,), (1.0,))
    with pytest.raises(StatisticsError):
        excess_daily_log_growth((1.0, 0.0), (1.0, 1.0))


def test_one_sided_lcb_is_deterministic_and_below_mean() -> None:
    sample = (0.001, 0.002, -0.0005, 0.0015, 0.0008, 0.0012)
    first = one_sided_lower_bound(sample)
    second = one_sided_lower_bound(sample)
    assert first == second  # deterministic for a fixed sample
    assert first < sum(sample) / len(sample)
    assert CONFIDENCE_LEVEL == 0.95


def test_lcb_shrinks_with_sample_size() -> None:
    base = [0.001, 0.0012, 0.0009, 0.0011] * 2
    small = one_sided_lower_bound(base[:4])
    large = one_sided_lower_bound(base * 8)
    mean = sum(base) / len(base)
    # More evidence tightens the bound toward the mean.
    assert large > small
    assert large < mean


def test_slippage_drag_is_double() -> None:
    slipped = apply_slippage_drag((0.01, 0.02), 0.001)
    assert slipped == pytest.approx((0.01 - 0.002, 0.02 - 0.002))


def test_maximum_drawdown_golden() -> None:
    nav = _nav(1.0, 1.2, 0.9, 1.1, 0.95)
    # Peak 1.2 -> trough 0.9 => 25% drawdown.
    assert maximum_drawdown(nav) == pytest.approx(0.25)


def test_cdar_is_continuous_replay_tail_mean() -> None:
    nav = _nav(1.0, 1.2, 0.9, 1.1, 0.95)
    cdar = conditional_drawdown_at_risk(nav, quantile=0.9)
    assert cdar > 0
    # CDaR never below MDD's quantile floor and never above MDD.
    assert cdar <= maximum_drawdown(nav) + 1e-12


def test_effective_sample_size_kish_golden() -> None:
    # Equal weights: ESS equals the number of positions.
    assert effective_sample_size((1.0, 1.0, 1.0, 1.0)) == pytest.approx(4.0)
    # Single concentrated position: ESS 1.
    assert effective_sample_size((0.0, 5.0, 0.0)) == pytest.approx(1.0)
    assert effective_sample_size(()) == 0.0


def test_evaluate_frozen_policy_golden_path() -> None:
    returns = (0.001, 0.0012, 0.0009, 0.0011, 0.0008, 0.001)
    evaluation = evaluate_frozen_policy(
        excess_returns=returns,
        minimum_economic_effect=0.0,
        evaluated_at=NOW,
        evidence_cutoff=CUTOFF,
        daily_slippage=0.0001,
        adverse_window=(0, 3),
    )
    assert evaluation.observation_count == 6
    assert evaluation.excess_mean == pytest.approx(sum(returns) / 6)
    assert evaluation.excess_lcb_95 < evaluation.excess_mean
    assert evaluation.passes_economic_gate()
    assert evaluation.excess_mean_at_double_slippage == pytest.approx(
        evaluation.excess_mean - 0.0002
    )
    assert evaluation.adverse_window_excess_mean == pytest.approx(
        sum(returns[0:3]) / 3
    )
    assert evaluation.maximum_drawdown >= 0.0


def test_leakage_guard_excludes_post_cutoff_evidence() -> None:
    returns = (0.001, 0.0012, 0.0009, 0.5)  # last day is a post-cutoff spike
    committed_at = (
        CUTOFF - timedelta(days=4),
        CUTOFF - timedelta(days=3),
        CUTOFF - timedelta(days=2),
        CUTOFF + timedelta(days=1),  # committed AFTER the cutoff
    )
    evaluation = evaluate_frozen_policy(
        excess_returns=returns,
        minimum_economic_effect=0.0,
        evaluated_at=NOW,
        evidence_cutoff=CUTOFF,
        committed_at=committed_at,
    )
    # Official OOS never sees the post-cutoff revision.
    assert evaluation.observation_count == 3
    assert evaluation.excess_mean == pytest.approx(
        sum(returns[:3]) / 3
    )


def test_evaluate_fails_closed_with_little_committed_evidence() -> None:
    committed_at = (CUTOFF + timedelta(days=1),) * 5
    with pytest.raises(StatisticsError) as excinfo:
        evaluate_frozen_policy(
            excess_returns=(0.001,) * 5,
            minimum_economic_effect=0.0,
            evaluated_at=NOW,
            evidence_cutoff=CUTOFF,
            committed_at=committed_at,
        )
    assert excinfo.value.code == "sample_too_small"


def test_mee_gate_requires_lcb_not_mean() -> None:
    # High mean, wide variance: the LCB gate must stay honest.
    returns = (0.05, -0.04, 0.045, -0.035, 0.04)
    evaluation = evaluate_frozen_policy(
        excess_returns=returns,
        minimum_economic_effect=0.01,
        evaluated_at=NOW,
        evidence_cutoff=CUTOFF,
    )
    assert evaluation.excess_mean > 0.01
    assert evaluation.passes_economic_gate() is False


def test_minimum_evidence_predicates_are_distinct() -> None:
    report = MinimumEvidenceReport(
        mature_outcome_count=MINIMUM_MATURE_OUTCOMES,
        decision_day_count=MINIMUM_DECISION_DAYS,
        effective_sample_size=float(MINIMUM_ESS),
        ticker_count=MINIMUM_TICKERS,
        month_count=MINIMUM_MONTHS,
        adverse_window_complete=True,
    )
    checks = check_minimum_evidence(report)
    assert all(checks.values())

    # Each predicate fails independently; 150 outcomes and 60 decision
    # days stay separate fields, never merged.
    short_outcomes = MinimumEvidenceReport(
        mature_outcome_count=MINIMUM_MATURE_OUTCOMES - 1,
        decision_day_count=MINIMUM_DECISION_DAYS,
        effective_sample_size=float(MINIMUM_ESS),
        ticker_count=MINIMUM_TICKERS,
        month_count=MINIMUM_MONTHS,
        adverse_window_complete=True,
    )
    checks = check_minimum_evidence(short_outcomes)
    assert checks["mature_outcomes"] is False
    assert checks["decision_days"] is True
    assert checks["all"] is False

    short_days = MinimumEvidenceReport(
        mature_outcome_count=MINIMUM_MATURE_OUTCOMES,
        decision_day_count=MINIMUM_DECISION_DAYS - 1,
        effective_sample_size=float(MINIMUM_ESS),
        ticker_count=MINIMUM_TICKERS,
        month_count=MINIMUM_MONTHS,
        adverse_window_complete=True,
    )
    checks = check_minimum_evidence(short_days)
    assert checks["mature_outcomes"] is True
    assert checks["decision_days"] is False

    no_adverse = MinimumEvidenceReport(
        mature_outcome_count=MINIMUM_MATURE_OUTCOMES,
        decision_day_count=MINIMUM_DECISION_DAYS,
        effective_sample_size=float(MINIMUM_ESS),
        ticker_count=MINIMUM_TICKERS,
        month_count=MINIMUM_MONTHS,
        adverse_window_complete=False,
    )
    assert check_minimum_evidence(no_adverse)["adverse_window"] is False


def test_tail_capacity_gates() -> None:
    returns = (0.001, -0.02, 0.001, -0.01, 0.002)
    evaluation = evaluate_frozen_policy(
        excess_returns=returns,
        minimum_economic_effect=0.0,
        evaluated_at=NOW,
        evidence_cutoff=CUTOFF,
    )
    tight = check_tail_capacity(
        evaluation, mdd_cap=0.001, cdar_cap=0.001
    )
    assert tight["passes"] is False
    loose = check_tail_capacity(evaluation, mdd_cap=0.5, cdar_cap=0.5)
    assert loose["passes"] is True


def test_predictable_adaptive_golden_paired_decision_days() -> None:
    champion = (0.002,) * 10
    challenger = (0.001,) * 10
    evaluation = evaluate_predictable_adaptive(
        champion_daily_returns=champion,
        challenger_daily_returns=challenger,
        minimum_economic_effect=0.0,
        evaluated_at=NOW,
        evidence_cutoff=CUTOFF,
    )
    # Paired differences are exactly 0.001 on every decision day.
    assert evaluation.paired_difference_mean == pytest.approx(0.001)
    assert evaluation.observation_count == 10
    # Chronological split: evaluation fold first, outer fold last.
    expected_eval = max(2, int(10 * (1.0 - OUTER_FOLD_FRACTION)))
    assert evaluation.evaluation_fold_size == expected_eval
    assert evaluation.outer_fold_size == 10 - expected_eval
    assert evaluation.outer_fold_difference_mean == pytest.approx(0.001)
    # Zero-variance golden sample: the t-based one-sided LCB equals the
    # paired mean exactly, and clears MEE.
    assert evaluation.paired_difference_lcb_95 == pytest.approx(0.001)
    assert evaluation.passes_economic_gate()


def test_predictable_adaptive_outer_fold_is_chronological_and_untuned(
) -> None:
    # First 7 days favor the champion; the final 3 days (the outer fold)
    # favor the challenger. The evaluator must NOT use the outer fold for
    # the LCB gate, and must report it separately.
    champion = (0.003,) * 7 + (0.0005,) * 3
    challenger = (0.001,) * 7 + (0.002,) * 3
    evaluation = evaluate_predictable_adaptive(
        champion_daily_returns=champion,
        challenger_daily_returns=challenger,
        minimum_economic_effect=0.0,
        evaluated_at=NOW,
        evidence_cutoff=CUTOFF,
    )
    assert evaluation.evaluation_fold_size == 7
    assert evaluation.outer_fold_size == 3
    assert evaluation.outer_fold_difference_mean == pytest.approx(
        0.0005 - 0.002
    )
    assert evaluation.paired_difference_mean == pytest.approx(0.002)


def test_predictable_adaptive_rejects_bad_inputs() -> None:
    with pytest.raises(StatisticsError):
        evaluate_predictable_adaptive(
            champion_daily_returns=(0.001, 0.001),
            challenger_daily_returns=(0.001,),
            minimum_economic_effect=0.0,
            evaluated_at=NOW,
            evidence_cutoff=CUTOFF,
        )
    with pytest.raises(StatisticsError):
        evaluate_predictable_adaptive(
            champion_daily_returns=(0.001, 0.001, 0.001),
            challenger_daily_returns=(0.001, 0.001, 0.001),
            minimum_economic_effect=0.0,
            evaluated_at=NOW,
            evidence_cutoff=CUTOFF,
            outer_fold_fraction=1.5,
        )
    with pytest.raises(StatisticsError):
        evaluate_predictable_adaptive(
            champion_daily_returns=(0.001, 0.002),
            challenger_daily_returns=(0.001, 0.002),
            minimum_economic_effect=0.0,
            evaluated_at=NOW,
            evidence_cutoff=CUTOFF,
        )
