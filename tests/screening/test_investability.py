"""Tests for investability ranking helpers."""

from __future__ import annotations

import math

from src.screening.composite_score import CompositeEntry, CompositeReport
from src.screening.expected_return import ExpectedReturn, ExpectedReturnReport
from src.screening.investability import (
    _safe_metric,
    build_front_door_verdict,
    rank_recommendations_by_investability,
    select_representative_candidates,
)


# ---------------------------------------------------------------------------
# NS-13: _safe_metric NaN/Inf guard (ranking determinism)
# ---------------------------------------------------------------------------


class TestSafeMetricNanGuard:
    def test_nan_returns_default_not_propagates(self) -> None:
        """NS-13: NaN must not propagate into sort keys (else same data -> different top picks across runs)."""
        assert _safe_metric(float("nan"), 0.0) == 0.0
        assert _safe_metric(float("nan"), -1.0) == -1.0

    def test_inf_returns_default(self) -> None:
        """NS-13: Inf also poisons sort comparisons; must fall to default."""
        assert _safe_metric(float("inf"), 0.0) == 0.0
        assert _safe_metric(float("-inf"), 0.0) == 0.0

    def test_nan_string_returns_default(self) -> None:
        """NS-13: 'NaN' string (from LLM/JSON) must not leak through as NaN float."""
        assert _safe_metric("NaN", 0.0) == 0.0
        assert _safe_metric("inf", 0.0) == 0.0

    def test_finite_value_passes_through(self) -> None:
        """NS-13: legitimate finite values are unchanged (no over-rejection)."""
        assert _safe_metric(0.72, 0.0) == 0.72
        assert _safe_metric(0, 0.5) == 0.0
        assert _safe_metric(None, 0.5) == 0.5

    def test_nan_does_not_corrupt_sort_key(self) -> None:
        """NS-13 regression: a NaN composite_score must yield deterministic ranking.

        Before fix, _safe_metric(float('nan')) returned nan, which as a sort key
        made sorted() produce non-deterministic ordering across runs (nan comparison
        is unstable). Two NaN-bearing recs must now tie-break deterministically.
        """
        import random
        recs = [
            {"ticker": "AAA", "name": "A", "score_b": float("nan"), "composite_score": float("nan")},
            {"ticker": "BBB", "name": "B", "score_b": float("nan"), "composite_score": float("nan")},
            {"ticker": "CCC", "name": "C", "score_b": 0.5, "composite_score": 0.5},
        ]
        cr = CompositeReport(trade_date="20260101", items=[])
        er = ExpectedReturnReport(trade_date="20260101", items=[], lookback_days=60, total_samples=0)
        # Run ranking twice with shuffled input order; output tickers must be identical
        order_a = rank_recommendations_by_investability(list(recs), cr, er)
        shuffled = list(reversed(recs))
        order_b = rank_recommendations_by_investability(shuffled, cr, er)
        assert [r["ticker"] for r in order_a] == [r["ticker"] for r in order_b], (
            "NaN in sort key produced non-deterministic ranking"
        )
        # sane ordering: CCC (finite 0.5) should rank ahead of the two NaN-defaulted recs
        assert order_a[0]["ticker"] == "CCC"


def test_rank_recommendations_prefers_30d_edge_when_composite_ties() -> None:
    recommendations = [
        {"ticker": "000001", "name": "Alpha", "score_b": 0.70},
        {"ticker": "000002", "name": "Beta", "score_b": 0.71},
        {"ticker": "000003", "name": "Gamma", "score_b": 0.69},
    ]
    composite = CompositeReport(
        trade_date="20260612",
        items=[
            CompositeEntry(ticker="000001", name="Alpha", base_score=0.70, composite_score=0.85),
            CompositeEntry(ticker="000002", name="Beta", base_score=0.71, composite_score=0.85),
            CompositeEntry(ticker="000003", name="Gamma", base_score=0.69, composite_score=0.82),
        ],
    )
    expected = ExpectedReturnReport(
        trade_date="20260612",
        lookback_days=60,
        total_samples=120,
        items=[
            ExpectedReturn(
                ticker="000001",
                score_b=0.70,
                bucket_label="高 (>0.8)",
                bucket_sample_count=40,
                expected_returns={"t1": 1.0, "t5": 2.0, "t10": 3.0, "t20": 6.0, "t30": 7.0},
                win_rates={"t1": 0.55, "t5": 0.56, "t10": 0.57, "t20": 0.58, "t30": 0.59},
            ),
            ExpectedReturn(
                ticker="000002",
                score_b=0.71,
                bucket_label="高 (>0.8)",
                bucket_sample_count=45,
                expected_returns={"t1": 1.0, "t5": 2.0, "t10": 3.0, "t20": 6.0, "t30": 9.0},
                win_rates={"t1": 0.55, "t5": 0.56, "t10": 0.57, "t20": 0.60, "t30": 0.62},
            ),
            ExpectedReturn(
                ticker="000003",
                score_b=0.69,
                bucket_label="中高 (0.7-0.8)",
                bucket_sample_count=60,
                expected_returns={"t1": 1.0, "t5": 1.5, "t10": 2.0, "t20": 4.0, "t30": 5.0},
                win_rates={"t1": 0.54, "t5": 0.55, "t10": 0.56, "t20": 0.57, "t30": 0.58},
            ),
        ],
    )

    ranked = rank_recommendations_by_investability(recommendations, composite, expected)

    assert [item["ticker"] for item in ranked] == ["000002", "000001", "000003"]
    assert ranked[0]["composite_score"] == 0.85
    assert ranked[0]["expected_returns"]["t30"] == 9.0
    assert ranked[0]["win_rates"]["t30"] == 0.62
    assert ranked[0]["bucket_sample_count"] == 45
    assert ranked[0]["composite_grade"] == "A"


def test_rank_recommendations_full_tiebreaks_by_ticker_ascending_deterministic() -> None:
    """R120/BH-011 family (investability sibling of top_picks + portfolio builder):
    when the 5-level ranking tuple fully collides (identical composite_score, t30,
    win_rate.t30, bucket_sample_count, AND score_b — realistic for fallback/missing-
    expected-return recs, or two recs in the same score_b bucket with identical
    calibration), the final tie-break must be deterministic by ticker ascending, not by
    whatever upstream dict/JSON iteration order the ``ranked`` list arrived in. Before
    the fix the tuple ended on score_b (a colliding float), so two identical runs over
    the same data could reorder the front-door verdict assignment."""
    base_recs = [
        {"ticker": "600999", "name": "Zeta", "score_b": 0.50},
        {"ticker": "000001", "name": "Alpha", "score_b": 0.50},
    ]
    composite = CompositeReport(
        trade_date="20260612",
        items=[
            CompositeEntry(ticker="600999", name="Zeta", base_score=0.50, composite_score=0.50),
            CompositeEntry(ticker="000001", name="Alpha", base_score=0.50, composite_score=0.50),
        ],
    )
    # No expected-return report → both fall to t30=-inf, win_rate=-inf, sample=0:
    # all five tuple components identical → deterministic tie-break required.
    expected = ExpectedReturnReport(trade_date="20260612", lookback_days=60, total_samples=0, items=[])

    ranked_forward = rank_recommendations_by_investability(list(base_recs), composite, expected)
    ranked_reversed = rank_recommendations_by_investability(list(reversed(base_recs)), composite, expected)

    assert [item["ticker"] for item in ranked_forward] == ["000001", "600999"]
    assert [item["ticker"] for item in ranked_reversed] == ["000001", "600999"]


def test_select_representative_candidates_prefers_unique_industry_clusters() -> None:
    ranked = [
        {"ticker": "000001", "industry_sw": "电子", "composite_score": 0.82},
        {"ticker": "000002", "industry_sw": "电子", "composite_score": 0.79},
        {"ticker": "000003", "industry_sw": "银行", "composite_score": 0.76},
        {"ticker": "000004", "industry_sw": "医药", "composite_score": 0.72},
    ]

    selected = select_representative_candidates(ranked, count=3)

    assert [item["ticker"] for item in selected] == ["000001", "000003", "000004"]
    assert selected[0]["cluster_label"] == "电子"
    assert selected[0]["cluster_size"] == 2
    assert selected[0]["cluster_alternatives"] == ["000002"]


def test_select_representative_candidates_backfills_duplicates_when_clusters_insufficient() -> None:
    ranked = [
        {"ticker": "000001", "industry_sw": "电子", "composite_score": 0.82},
        {"ticker": "000002", "industry_sw": "电子", "composite_score": 0.79},
        {"ticker": "000003", "industry_sw": "银行", "composite_score": 0.76},
    ]

    selected = select_representative_candidates(ranked, count=3)

    assert [item["ticker"] for item in selected] == ["000001", "000003", "000002"]


def test_build_front_door_verdict_promotes_high_quality_pick_to_buy() -> None:
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.68,
            # C219: BUY gate 用 T+5 OR T+10 OR 逻辑; t5/t10 提供, t30 保留作 invalidation
            "expected_returns": {"t5": 8.5, "t10": 9.0, "t30": 9.4},
            "win_rates": {"t5": 0.61, "t10": 0.62, "t30": 0.63},
            "bucket_sample_count": 48,
            "momentum_bonus": 0.05,
            "sector_bonus": 0.03,
            "consistency_adj": 0.02,
            "volume_factor": 0.01,
            "trend_resonance_factor": 0.04,
        },
        market_regime="trend",
    )

    assert verdict["action"] == "BUY"
    # BH-010: a BUY pick (t30 edge +9.4%) must NOT carry the false "edge 转负"
    # invalidation reason. The old code hardcoded it unconditionally.
    assert "转负" not in verdict["invalidation_reason"]


def test_build_front_door_verdict_lists_edge_turn_negative_only_when_negative() -> None:
    """BH-010: "T+30 edge 转负" must only appear when t30 edge is actually < 0."""
    # Positive edge → HOLD (composite 0.4) → no "转负" reason.
    # C219: t5/t10 正值让 is_watchable 通过 → HOLD
    pos = build_front_door_verdict(
        {"decision": "bullish", "composite_score": 0.4, "expected_returns": {"t5": 1.8, "t10": 2.0, "t30": 2.0},
         "win_rates": {"t5": 0.51, "t10": 0.52, "t30": 0.52}, "bucket_sample_count": 48},
        market_regime="trend",
    )
    assert "转负" not in pos["invalidation_reason"]
    # Negative edge → AVOID → "转负" reason present.
    # C219: t5/t10 负值让 is_watchable 不通过 → AVOID
    neg = build_front_door_verdict(
        {"decision": "bullish", "composite_score": 0.4, "expected_returns": {"t5": -1.2, "t10": -1.5, "t30": -1.5},
         "win_rates": {"t5": 0.45, "t10": 0.45, "t30": 0.45}, "bucket_sample_count": 48},
        market_regime="trend",
    )
    assert "转负" in neg["invalidation_reason"]


def test_build_front_door_verdict_respects_risk_off_gate() -> None:
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.71,
            # C219: t5/t10 让 _meets_quality_bar 通过, risk_off → HOLD
            "expected_returns": {"t5": 10.0, "t10": 10.5, "t30": 11.2},
            "win_rates": {"t5": 0.64, "t10": 0.65, "t30": 0.66},
            "bucket_sample_count": 52,
        },
        market_regime="risk_off",
    )

    assert verdict["action"] == "HOLD"


def test_build_front_door_verdict_buy_requires_mature_t30_sample() -> None:
    """R35 consistency drain: the BUY gate must require enough *mature* T+30
    samples, not just the raw all-records ``bucket_sample_count``.

    A recommendation whose bucket has 40 raw records but only 5 matured T+30
    records is backed by thin, mostly-unmatured evidence — the T+30 edge/win
    rate are not yet statistically trustworthy. Promoting it to BUY would
    violate the "higher conviction" goal and contradict R35's display honesty.
    With ``bucket_t30_mature_count`` present and small, the verdict must NOT
    be BUY even when every other signal looks strong."""
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.68,
            # C219: t5/t10 让 _short_term_passes 通过, 但 mature_count=5 < 20 → 不 BUY
            "expected_returns": {"t5": 8.5, "t10": 9.0, "t30": 9.4},
            "win_rates": {"t5": 0.61, "t10": 0.62, "t30": 0.63},
            "bucket_sample_count": 40,
            # Only 5 of the 40 historical picks have matured past the 30-day
            # horizon — the T+30 stats are dominated by unmatured records.
            "bucket_t30_mature_count": 5,
        },
        market_regime="trend",
    )
    assert verdict["action"] != "BUY", (
        "BUY must require a meaningful mature T+30 sample, not just raw count"
    )


def test_build_front_door_verdict_buy_ok_when_mature_sample_sufficient() -> None:
    """When the mature T+30 sample is sufficient, a strong pick still promotes
    to BUY — the gate tightens but does not become unreachable."""
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.68,
            # C219: t5/t10 让 _short_term_passes 通过, mature_count=25 >= 20 → BUY
            "expected_returns": {"t5": 8.5, "t10": 9.0, "t30": 9.4},
            "win_rates": {"t5": 0.61, "t10": 0.62, "t30": 0.63},
            "bucket_sample_count": 40,
            "bucket_t30_mature_count": 25,
        },
        market_regime="trend",
    )
    assert verdict["action"] == "BUY"


def test_build_front_door_verdict_falls_back_to_raw_count_when_mature_absent() -> None:
    """Backward compatibility: legacy recommendations without
    ``bucket_t30_mature_count`` must still gate on the raw
    ``bucket_sample_count`` so existing pipelines are not silently broken."""
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.68,
            # C219: t5/t10 让 _short_term_passes 通过, 无 mature_count → fallback raw count
            "expected_returns": {"t5": 8.5, "t10": 9.0, "t30": 9.4},
            "win_rates": {"t5": 0.61, "t10": 0.62, "t30": 0.63},
            "bucket_sample_count": 48,
            # No bucket_t30_mature_count key at all (pre-R35 data / partial pipeline)
        },
        market_regime="trend",
    )
    assert verdict["action"] == "BUY"


def test_build_front_door_verdict_risk_off_hold_not_blocked_by_zero_mature_count() -> None:
    """BH-013: a high-quality pick under risk_off must HOLD (not AVOID) even when
    ``bucket_t30_mature_count`` is present but zero.

    Scenario: the bucket has 40 raw historical picks but none have yet matured
    past the 30-day horizon (e.g. a freshly-active bucket, or a system within
    its first 30 days of tracking). R35's BUY gate correctly refuses to BUY on
    unmatured evidence, but the *risk_off HOLD* decision must not be blocked by
    the same strict mature-count gate: HOLD only claims "quality looks good,
    watch" — it does not rely on realized 30-day returns. Locking
    ``backing_sample`` to 0 when the field exists-but-is-zero caused high-quality
    picks (composite 0.72, edge +11.4%, winrate 66%, raw sample 40) to be
    mis-classified as AVOID under risk_off, contradicting the "higher conviction"
    goal (HOLD/AVOID distinction must reflect pick quality, not tracking age).

    The fix: the BUY gate keeps the strict mature-count requirement, but the
    risk_off HOLD path uses the raw ``bucket_sample_count`` as its backing
    sample so a young-but-populated bucket can still surface quality picks as
    HOLD rather than AVOID."""
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.72,
            # C219: t5/t10 让 _meets_quality_bar 通过, risk_off + mature=0 → HOLD (用 raw count)
            "expected_returns": {"t5": 10.0, "t10": 10.5, "t30": 11.4},
            "win_rates": {"t5": 0.64, "t10": 0.65, "t30": 0.66},
            "bucket_sample_count": 40,
            # Field present but zero: bucket is tracked but no pick has matured
            # past 30 days yet.
            "bucket_t30_mature_count": 0,
        },
        market_regime="risk_off",
    )
    assert verdict["action"] == "HOLD", (
        "risk_off HOLD must reflect pick quality, not tracking age; a populated "
        "bucket with no matured samples should still HOLD a high-quality pick"
    )


def test_build_front_door_verdict_buy_still_requires_mature_sample_when_zero() -> None:
    """BH-013 complement: even though risk_off HOLD now tolerates
    ``bucket_t30_mature_count=0``, the BUY gate in a normal regime must STILL
    refuse to BUY without mature evidence. The fix loosens the HOLD bar but
    preserves R35's strict BUY requirement."""
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.72,
            # C219: t5/t10 让 _short_term_passes 通过, 但 mature=0 < 20 → 不 BUY
            "expected_returns": {"t5": 10.0, "t10": 10.5, "t30": 11.4},
            "win_rates": {"t5": 0.64, "t10": 0.65, "t30": 0.66},
            "bucket_sample_count": 40,
            "bucket_t30_mature_count": 0,
        },
        market_regime="trend",
    )
    assert verdict["action"] != "BUY", (
        "BUY must still require mature T+30 evidence; zero mature samples must "
        "not promote to BUY even with a large raw sample count"
    )


# ---------------------------------------------------------------------------
# C219: BUY gate T+5 OR T+10 OR 逻辑 (短期反弹信号)
# per-horizon bootstrap CI (n=7203, 95%): T+5 60.2% [59.0%, 61.3%],
# T+10 60.5% [59.4%, 61.6%], T+30 45.4% [44.2%, 46.5%] << 50%
# ---------------------------------------------------------------------------


def test_c219_buy_passes_when_t5_only_passes() -> None:
    """C219: T+5 通过 (winrate>=0.55 AND edge>0), T+10 不通过 → 仍 BUY."""
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.68,
            # T+5 强 (winrate 0.62, edge 8.5), T+10 弱 (winrate 0.50, edge 0.5)
            "expected_returns": {"t5": 8.5, "t10": 0.5, "t30": -1.0},
            "win_rates": {"t5": 0.62, "t10": 0.50, "t30": 0.40},
            "bucket_sample_count": 48,
            "bucket_t30_mature_count": 25,
        },
        market_regime="trend",
    )
    assert verdict["action"] == "BUY", "T+5 单独通过应 BUY (OR 逻辑)"


def test_c219_buy_passes_when_t10_only_passes() -> None:
    """C219: T+10 通过, T+5 不通过 → 仍 BUY."""
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.68,
            # T+5 弱 (winrate 0.50, edge 0.5), T+10 强 (winrate 0.62, edge 9.0)
            "expected_returns": {"t5": 0.5, "t10": 9.0, "t30": -1.0},
            "win_rates": {"t5": 0.50, "t10": 0.62, "t30": 0.40},
            "bucket_sample_count": 48,
            "bucket_t30_mature_count": 25,
        },
        market_regime="trend",
    )
    assert verdict["action"] == "BUY", "T+10 单独通过应 BUY (OR 逻辑)"


def test_c219_buy_blocked_when_both_t5_t10_fail() -> None:
    """C219: T+5 和 T+10 都不通过 → 不 BUY, 即使 T+30 强."""
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.68,
            # T+5/T+10 都弱, T+30 强 — 旧代码会 BUY, 新代码不应 BUY
            "expected_returns": {"t5": -0.5, "t10": -0.5, "t30": 9.4},
            "win_rates": {"t5": 0.45, "t10": 0.45, "t30": 0.63},
            "bucket_sample_count": 48,
            "bucket_t30_mature_count": 25,
        },
        market_regime="trend",
    )
    assert verdict["action"] != "BUY", "T+5/T+10 都不通过时即使 T+30 强也不应 BUY"


def test_c219_buy_passes_when_both_t5_t10_pass() -> None:
    """C219: T+5 和 T+10 都通过 → BUY (OR 逻辑的退化情况)."""
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.68,
            "expected_returns": {"t5": 8.5, "t10": 9.0, "t30": 9.4},
            "win_rates": {"t5": 0.62, "t10": 0.63, "t30": 0.63},
            "bucket_sample_count": 48,
            "bucket_t30_mature_count": 25,
        },
        market_regime="trend",
    )
    assert verdict["action"] == "BUY"


def test_c219_watchable_uses_or_logic() -> None:
    """C219: is_watchable 也用 T+5 OR T+10 (winrate>=0.5, edge>=0).
    composite 0.4 (不够 BUY), T+5 弱但 T+10 watchable → HOLD."""
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.40,  # 不够 BUY (需要 >=0.5)
            # T+5 不 watchable (edge<0), T+10 watchable (winrate 0.52, edge 2.0)
            "expected_returns": {"t5": -0.5, "t10": 2.0, "t30": 2.0},
            "win_rates": {"t5": 0.48, "t10": 0.52, "t30": 0.52},
            "bucket_sample_count": 48,
        },
        market_regime="trend",
    )
    assert verdict["action"] == "HOLD", "T+10 watchable 但 T+5 不 watchable → HOLD (OR)"


def test_c219_invalidation_t30_negative_still_flagged() -> None:
    """C219: 即使 BUY 通过 (T+5/T+10 强), T+30 edge 转负仍作为长期衰退信号."""
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.68,
            # T+5/T+10 强 (BUY), T+30 edge 转负 (长期衰退)
            "expected_returns": {"t5": 8.5, "t10": 9.0, "t30": -2.0},
            "win_rates": {"t5": 0.62, "t10": 0.63, "t30": 0.40},
            "bucket_sample_count": 48,
            "bucket_t30_mature_count": 25,
        },
        market_regime="trend",
    )
    # BUY gate 通过 (T+5/T+10 OR)
    assert verdict["action"] == "BUY"
    # 但 T+30 edge 转负仍被标记 (长期衰退信号)
    assert "转负" in verdict["invalidation_reason"]


# ---------------------------------------------------------------------------
# _grade_code / _safe_metric / _decorate_cluster_candidate
# ---------------------------------------------------------------------------


class TestGradeCode:
    def test_grade_a_boundary(self):
        from src.screening.investability import _grade_code

        assert _grade_code(0.7) == "A"
        assert _grade_code(0.95) == "A"
        assert _grade_code(1.0) == "A"

    def test_grade_b(self):
        from src.screening.investability import _grade_code

        assert _grade_code(0.5) == "B"
        assert _grade_code(0.69) == "B"

    def test_grade_c(self):
        from src.screening.investability import _grade_code

        assert _grade_code(0.3) == "C"
        assert _grade_code(0.49) == "C"

    def test_grade_d(self):
        from src.screening.investability import _grade_code

        assert _grade_code(0.1) == "D"
        assert _grade_code(0.29) == "D"

    def test_grade_f(self):
        from src.screening.investability import _grade_code

        assert _grade_code(0.09) == "F"
        assert _grade_code(0.0) == "F"
        assert _grade_code(-0.5) == "F"


class TestSafeMetric:
    def test_none_returns_default(self):
        from src.screening.investability import _safe_metric

        assert _safe_metric(None, 0.5) == 0.5

    def test_valid_float(self):
        from src.screening.investability import _safe_metric

        assert _safe_metric(0.8, 0.0) == 0.8

    def test_int_coerced(self):
        from src.screening.investability import _safe_metric

        assert _safe_metric(5, 0.0) == 5.0

    def test_numeric_string_coerced(self):
        from src.screening.investability import _safe_metric

        assert _safe_metric("0.42", 0.0) == 0.42

    def test_invalid_string_returns_default(self):
        from src.screening.investability import _safe_metric

        assert _safe_metric("abc", 1.0) == 1.0

    def test_uncoercible_type_returns_default(self):
        from src.screening.investability import _safe_metric

        assert _safe_metric([1, 2, 3], 2.0) == 2.0


class TestDecorateClusterCandidate:
    def test_decorates_with_cluster_metadata(self):
        from src.screening.investability import _decorate_cluster_candidate

        rec = {"ticker": "000001", "score_b": 0.7}
        members = [{"ticker": "000001"}, {"ticker": "000002"}, {"ticker": "000003"}]
        result = _decorate_cluster_candidate(rec, cluster_kind="industry", cluster_label="电子", cluster_members=members)

        assert result["cluster_kind"] == "industry"
        assert result["cluster_label"] == "电子"
        assert result["cluster_size"] == 3
        assert result["cluster_members"] == ["000001", "000002", "000003"]
        assert result["cluster_alternatives"] == ["000002", "000003"]
        assert result["is_cluster_representative"] is True

    def test_non_first_member_not_representative(self):
        from src.screening.investability import _decorate_cluster_candidate

        rec = {"ticker": "000002"}
        members = [{"ticker": "000001"}, {"ticker": "000002"}]
        result = _decorate_cluster_candidate(rec, cluster_kind="concept", cluster_label="AI", cluster_members=members)

        assert result["is_cluster_representative"] is False
        assert result["cluster_alternatives"] == ["000001"]

    def test_empty_members(self):
        from src.screening.investability import _decorate_cluster_candidate

        rec = {"ticker": "000001"}
        result = _decorate_cluster_candidate(rec, cluster_kind="industry", cluster_label="电子", cluster_members=[])

        assert result["cluster_size"] == 0
        assert result["cluster_alternatives"] == []
        assert result["is_cluster_representative"] is False

    def test_does_not_mutate_original(self):
        from src.screening.investability import _decorate_cluster_candidate

        rec = {"ticker": "000001"}
        _decorate_cluster_candidate(rec, cluster_kind="industry", cluster_label="电子", cluster_members=[{"ticker": "000001"}])
        assert "cluster_kind" not in rec


def test_missing_composite_fallback_applies_penalty_and_marks_unverified() -> None:
    """R39: when a ticker is absent from the composite report, its fallback
    ``composite_score`` must (a) be discounted so a missing-composite ticker
    cannot easily cross the BUY 0.5 gate that a penalty-aware composite would
    have demoted, and (b) be flagged ``composite_verified=False``.

    Before the fix, ``score_b`` (domain [0,1], no penalties) was aliased
    directly into ``composite_score`` (domain [-1,1], with negative
    consistency/momentum/sector adjustments), so score_b=0.55 → composite 0.55
    could spuriously reach BUY despite penalties that a real composite would
    have applied.
    """
    # 000001 has a composite entry (verified); 000002 does NOT (fallback path).
    recommendations = [
        {"ticker": "000001", "name": "A", "score_b": 0.60},
        {"ticker": "000002", "name": "B", "score_b": 0.55},
    ]
    composite = CompositeReport(
        trade_date="20260612",
        items=[CompositeEntry(ticker="000001", name="A", base_score=0.60, composite_score=0.55)],
    )
    expected = ExpectedReturnReport(trade_date="20260612", lookback_days=60, total_samples=10, items=[])

    ranked = rank_recommendations_by_investability(recommendations, composite, expected)
    by_ticker = {r["ticker"]: r for r in ranked}

    # Verified ticker keeps the real composite score + verified flag.
    assert by_ticker["000001"]["composite_score"] == 0.55
    assert by_ticker["000001"]["composite_verified"] is True

    # Missing-composite ticker: penalized (0.55 * 0.9 = 0.495) + unverified.
    missing = by_ticker["000002"]
    assert missing["composite_score"] == round(0.55 * 0.9, 4)
    assert missing["composite_verified"] is False
    # 0.495 < 0.5 → does not easily cross the BUY gate via the score_b shortcut.
    assert missing["composite_score"] < 0.5
