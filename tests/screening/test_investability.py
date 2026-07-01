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


def test_rank_recommendations_prefers_decision_horizon_edge_when_composite_ties() -> None:
    """R143/O-1 + C222: when composite_score ties, ranking falls back to the
    BUY-gate decision-horizon tie-breakers (max of T+5/T+10 edge, then max
    of T+5/T+10 winrate, then bucket_sample_count, then score_b, then ticker).

    C222 (2026-06-28 horizon 一致性): previously asserted on T+30 edge as the
    2nd tie-breaker; tie-breakers 2/3 now use ``_max_short_horizon_metric``
    (max of t5/t10) to align with BUY gate horizon (T+5 OR T+10 pass, see
    C220 commit 4184dd7e). Test data: 000001 and 000002 share composite=0.85
    AND max(t5,t10)=3.0 AND max(t5,t10) winrate=0.57, so the tie cascades to
    bucket_sample_count (000002: 45 > 000001: 40) → 000002 ranks first.
    """
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
    # C222: T+30 fields are still attached (invalidation horizon); the BUY
    # decision used max(t5, t10) but T+30 is retained for downstream display.
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
# C221: signal_horizon 字段 — 呈现层区分 T+5 / T+10 / T+5+T+10 反弹信号
# C219 改 BUY gate 为 T+5 OR T+10 OR, 但呈现只显示 action=BUY, 用户无法区分
# 是 T+5 还是 T+10 反弹, 容易把 T+5 票当 T+10 持有增加风险. signal_horizon 字段
# 让用户灵活组合资金: T+5 票快进快出, T+10 票持有更久, T+5+T+10 票更强可加仓.
# ---------------------------------------------------------------------------


def test_c221_signal_horizon_t5_only() -> None:
    """C221: T+5 通过 (edge>0 AND winrate>=0.55), T+10 不通过 → signal_horizon="T+5"."""
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
    assert verdict["action"] == "BUY"
    assert verdict["signal_horizon"] == "T+5", (
        "T+5 单独通过时 signal_horizon 必须为 'T+5', 让用户知道这是 T+5 反弹票"
    )


def test_c221_signal_horizon_t10_only() -> None:
    """C221: T+10 通过, T+5 不通过 → signal_horizon="T+10"."""
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
    assert verdict["action"] == "BUY"
    assert verdict["signal_horizon"] == "T+10", (
        "T+10 单独通过时 signal_horizon 必须为 'T+10', 让用户知道这是 T+10 反弹票"
    )


def test_c221_signal_horizon_both() -> None:
    """C221: T+5 和 T+10 都通过 → signal_horizon="T+5+T+10" (双信号更强)."""
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
    assert verdict["signal_horizon"] == "T+5+T+10", (
        "T+5 和 T+10 都通过时 signal_horizon 必须为 'T+5+T+10', 标识双信号更强的反弹票"
    )


def test_c221_signal_horizon_empty_when_neither_passes() -> None:
    """C221: T+5/T+10 都不通过 (HOLD/AVOID) → signal_horizon="" (不展示)."""
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.40,  # 不够 BUY
            # T+5/T+10 都弱 (winrate 0.48, edge 负)
            "expected_returns": {"t5": -0.5, "t10": -0.8, "t30": -1.0},
            "win_rates": {"t5": 0.48, "t10": 0.48, "t30": 0.40},
            "bucket_sample_count": 48,
        },
        market_regime="trend",
    )
    # 不是 BUY (composite 0.4 < 0.5)
    assert verdict["action"] != "BUY"
    # signal_horizon 为空, 呈现层不展示 (避免误导用户)
    assert verdict["signal_horizon"] == "", (
        "T+5/T+10 都不通过时 signal_horizon 必须为空, 不展示短期反弹信号"
    )


def test_c221_signal_horizon_preserved_under_risk_off_downgrade() -> None:
    """C221: risk_off 降级 BUY→HOLD, 但 signal_horizon 仍标注.

    让用户知道"本可 BUY 但被市场门控降级为 HOLD"的短期反弹信号,
    可以在市场门控解除后重新关注这些票.
    """
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.72,
            # T+5/T+10 强 (本可 BUY)
            "expected_returns": {"t5": 10.0, "t10": 10.5, "t30": 11.4},
            "win_rates": {"t5": 0.64, "t10": 0.65, "t30": 0.66},
            "bucket_sample_count": 40,
            "bucket_t30_mature_count": 25,
        },
        market_regime="risk_off",  # 降级 BUY→HOLD
    )
    # risk_off 降级为 HOLD
    assert verdict["action"] == "HOLD"
    # 但 signal_horizon 仍标注 (让用户知道本可 BUY)
    assert verdict["signal_horizon"] == "T+5+T+10", (
        "risk_off 降级不应丢失 signal_horizon — 用户需知道本可 BUY 的短期反弹信号"
    )


# ---------------------------------------------------------------------------
# NS-11 (autodev c232): consecutive bonus 不应喂 BUY 门控 — bonus 本意是
# 排序 tie-break, 不是放水 gate. _apply_consecutive_bonus_and_resort (top_picks.py)
# 在加 bonus 前存 pre-bonus `composite_score_gated`, build_front_door_verdict
# 优先读 composite_score_gated 判 BUY gate (>=0.5), 缺省回退 composite_score
# (向后兼容旧报告). C220 horizon 对齐后, bonus 污染 gate 会让 0.47 真分 + 0.05
# bonus = 0.52 越过 BUY → stale 挑选反而更容易 BUY, 与"稳定找到"产品目标相违.
# ---------------------------------------------------------------------------


def test_ns11_buy_gate_uses_pre_bonus_composite_score_gated() -> None:
    """NS-11: BUY gate 必须用 pre-bonus composite_score_gated 判定, 不被
    consecutive bonus 放水. 模拟 0.47 真分 + 0.05 bonus = 0.52 场景:
    composite_score_gated=0.47 < 0.5 → 不 BUY, 即使 composite_score=0.52."""
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            # post-bonus composite_score (boosted, 用于排序)
            "composite_score": 0.52,
            # pre-bonus composite_score_gated (NS-11 新增, 用于 BUY gate)
            "composite_score_gated": 0.47,
            # T+5/T+10 强 (本可 BUY 若 score 够)
            "expected_returns": {"t5": 8.5, "t10": 9.0, "t30": 9.4},
            "win_rates": {"t5": 0.62, "t10": 0.63, "t30": 0.63},
            "bucket_sample_count": 48,
            "bucket_t30_mature_count": 25,
        },
        market_regime="trend",
    )
    # composite_score_gated=0.47 < 0.5 → 不 BUY, 降级 HOLD (is_watchable: 0.47>=0.25)
    assert verdict["action"] != "BUY", (
        "NS-11: BUY gate 必须用 pre-bonus composite_score_gated; 0.47 真分 + "
        "0.05 bonus = 0.52 不应越过 BUY gate (>=0.5) — bonus 是排序 tie-break, "
        "不是放水 gate"
    )
    # is_watchable 用 pre-bonus score: 0.47 >= 0.25 → HOLD (非 AVOID)
    assert verdict["action"] == "HOLD", (
        "NS-11: composite_score_gated=0.47 >= 0.25 (is_watchable 阈值) → HOLD, 非 AVOID"
    )


def test_ns11_buy_passes_when_composite_score_gated_above_threshold() -> None:
    """NS-11: composite_score_gated >= 0.5 (真分够 BUY) → BUY, bonus 仅影响排序."""
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.55,  # post-bonus (0.50 + 0.05)
            "composite_score_gated": 0.50,  # pre-bonus (真分够 BUY)
            "expected_returns": {"t5": 8.5, "t10": 9.0, "t30": 9.4},
            "win_rates": {"t5": 0.62, "t10": 0.63, "t30": 0.63},
            "bucket_sample_count": 48,
            "bucket_t30_mature_count": 25,
        },
        market_regime="trend",
    )
    assert verdict["action"] == "BUY", (
        "NS-11: composite_score_gated=0.50 >= 0.5 → BUY (bonus 仅排序, 不影响 gate)"
    )


def test_ns11_falls_back_to_composite_score_when_gated_absent() -> None:
    """NS-11: 缺省 composite_score_gated (旧报告/无 bonus 路径) 回退 composite_score.

    向后兼容: 旧报告无 composite_score_gated 字段, build_front_door_verdict
    回退到 composite_score 判 BUY gate, 保持旧行为."""
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.68,  # 无 composite_score_gated → 回退
            "expected_returns": {"t5": 8.5, "t10": 9.0, "t30": 9.4},
            "win_rates": {"t5": 0.62, "t10": 0.63, "t30": 0.63},
            "bucket_sample_count": 48,
            "bucket_t30_mature_count": 25,
        },
        market_regime="trend",
    )
    assert verdict["action"] == "BUY", (
        "NS-11: 缺省 composite_score_gated 时回退 composite_score 判 BUY gate (向后兼容)"
    )


def test_ns11_watchable_uses_pre_bonus_composite_score_gated() -> None:
    """NS-11: is_watchable (HOLD/AVOID 分界) 也用 composite_score_gated.

    模拟 0.22 真分 + 0.05 bonus = 0.27 场景: composite_score_gated=0.22 < 0.25
    → 不 watchable → AVOID, 即使 composite_score=0.27 >= 0.25."""
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.27,  # post-bonus (0.22 + 0.05)
            "composite_score_gated": 0.22,  # pre-bonus (不够 watchable)
            "expected_returns": {"t5": 2.0, "t10": 2.5, "t30": 3.0},
            "win_rates": {"t5": 0.52, "t10": 0.52, "t30": 0.52},
            "bucket_sample_count": 48,
        },
        market_regime="trend",
    )
    # composite_score_gated=0.22 < 0.25 → 不 watchable → AVOID
    assert verdict["action"] == "AVOID", (
        "NS-11: is_watchable 用 composite_score_gated; 0.22 真分 + 0.05 bonus "
        "= 0.27 不应越过 watchable 阈值 (>=0.25) → AVOID"
    )


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


# ---------------------------------------------------------------------------
# NS-23 (autodev c245): crisis regime T+5 BUY gate 不可靠修复.
#
# 根因 (用户 2026-06-29 直接复现证据): C220 BUY gate 用全期 per-bucket T+5
# winrate (~60%) 判门控 (`_short_term_passes = _t5_passes or _t10_passes`),
# 但本月 crisis regime 实际 T+5 winrate=43.59% < 50%. per-ticker 全期历史
# stats 不能盲目外推到 regime-specific — crisis 下 T+5 alone 不应放行.
# T+10 相对靠谱但仍需验证 (仅 2 信号日 mature, 等 7 月初更多数据).
#
# Fix: crisis/risk_off regime 下 `_short_term_passes = _t10_passes` (只 T+10
# 可放行); 非 crisis 保持 C220 OR 逻辑.
# ---------------------------------------------------------------------------


def test_ns23_crisis_t5_only_does_not_pass_gate() -> None:
    """NS-23: crisis regime 下 T+5 alone 不应放行 BUY gate.

    场景: composite 0.68 (够 BUY), T+5 强 (winrate 0.61, edge 8.5), T+10 弱
    (winrate 0.45, edge -1.0). 全期 T+5 winrate 0.61 >= 0.55 让 _t5_passes=True,
    但 crisis regime 实际 T+5 winrate=43.59% < 50% → T+5 信号不可靠, 不应放行.
    期望: action=AVOID (非 HOLD), 因为 _short_term_passes 在 crisis 下只看 T+10.
    """
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.68,
            # T+5 强 (全期历史 stats, crisis 下实际不可靠)
            "expected_returns": {"t5": 8.5, "t10": -1.0, "t30": -2.0},
            "win_rates": {"t5": 0.61, "t10": 0.45, "t30": 0.42},
            "bucket_sample_count": 48,
            "bucket_t30_mature_count": 25,
        },
        market_regime="crisis",
    )
    assert verdict["action"] == "AVOID", (
        "NS-23: crisis regime 下 T+5 alone 不应放行 — 全期 T+5 winrate 0.61 让 "
        "_t5_passes=True, 但 crisis 实际 T+5 winrate=43.59% < 50% 不可靠. "
        "T+10 弱 (winrate 0.45) → _short_term_passes 应为 False → AVOID (非 HOLD)"
    )


def test_ns23_crisis_t10_passes_still_hold() -> None:
    """NS-23: crisis regime 下 T+10 通过仍可 HOLD (T+10 相对靠谱).

    场景: T+5 弱, T+10 强 (winrate 0.62, edge 9.0). crisis 下只看 T+10,
    T+10 通过 → _short_term_passes=True → is_high_quality_for_hold=True → HOLD.
    """
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.68,
            # T+5 弱, T+10 强 (crisis 下 T+10 相对靠谱)
            "expected_returns": {"t5": -0.5, "t10": 9.0, "t30": -1.0},
            "win_rates": {"t5": 0.45, "t10": 0.62, "t30": 0.42},
            "bucket_sample_count": 48,
            "bucket_t30_mature_count": 25,
        },
        market_regime="crisis",
    )
    assert verdict["action"] == "HOLD", (
        "NS-23: crisis regime 下 T+10 通过仍可 HOLD — T+10 相对靠谱 (用户 evidence), "
        "crisis 下 _short_term_passes=_t10_passes=True → is_high_quality_for_hold=True → HOLD"
    )


def test_ns23_crisis_both_pass_still_hold() -> None:
    """NS-23: crisis regime 下 T+5+T+10 都通过 → HOLD (T+10 通过即放行).

    场景: T+5/T+10 都强. crisis 下 _short_term_passes=_t10_passes=True → HOLD.
    signal_horizon 仍标注 'T+5+T+10' (raw 信号展示, 不受 regime 调整影响).
    """
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.72,
            "expected_returns": {"t5": 10.0, "t10": 10.5, "t30": 11.4},
            "win_rates": {"t5": 0.64, "t10": 0.65, "t30": 0.66},
            "bucket_sample_count": 40,
            "bucket_t30_mature_count": 25,
        },
        market_regime="crisis",
    )
    assert verdict["action"] == "HOLD"
    # signal_horizon 仍标注 raw 信号 (T+5+T+10 都通过), 不受 regime 调整影响
    assert verdict["signal_horizon"] == "T+5+T+10"


def test_ns23_risk_off_t5_only_does_not_pass_gate() -> None:
    """NS-23: risk_off regime 同 crisis — T+5 alone 不应放行.

    risk_off 与 crisis 共享同一 market_gate 分支 (line 254), T+5 不可靠
    同样适用. T+5 强但 T+10 弱 → AVOID (非 HOLD).
    """
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.68,
            "expected_returns": {"t5": 8.5, "t10": -1.0, "t30": -2.0},
            "win_rates": {"t5": 0.61, "t10": 0.45, "t30": 0.42},
            "bucket_sample_count": 48,
            "bucket_t30_mature_count": 25,
        },
        market_regime="risk_off",
    )
    assert verdict["action"] == "AVOID", (
        "NS-23: risk_off 同 crisis — T+5 alone 不应放行 (T+10 弱 → AVOID 非 HOLD)"
    )


def test_ns23_non_crisis_keeps_or_logic() -> None:
    """NS-23: 非 crisis regime 保持 C220 OR 逻辑 (回归保护).

    场景: trend regime, T+5 强 T+10 弱. C220 OR 逻辑下 _t5_passes=True
    → _short_term_passes=True → BUY. crisis 调整不应影响非 crisis regime.
    """
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.68,
            # T+5 强, T+10 弱 — 非 crisis 下 OR 逻辑让 T+5 放行
            "expected_returns": {"t5": 8.5, "t10": -1.0, "t30": 9.4},
            "win_rates": {"t5": 0.61, "t10": 0.45, "t30": 0.63},
            "bucket_sample_count": 48,
            "bucket_t30_mature_count": 25,
        },
        market_regime="trend",
    )
    assert verdict["action"] == "BUY", (
        "NS-23: 非 crisis regime 保持 C220 OR 逻辑 — T+5 强 → _t5_passes=True "
        "→ _short_term_passes=True → BUY (crisis 调整不影响非 crisis)"
    )


def test_ns23_crisis_t5_only_signal_horizon_preserved() -> None:
    """NS-23: crisis 下 T+5-only 被 AVOID, 但 signal_horizon 仍标注 'T+5'.

    signal_horizon 展示 raw 信号 (T+5 通过), action 展示 regime 调整后判决
    (AVOID). 让用户知道"有 T+5 信号但 crisis 下不可靠 → AVOID", 与 C221
    'risk_off 降级 HOLD 仍标注 horizon' 同理.
    """
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.68,
            "expected_returns": {"t5": 8.5, "t10": -1.0, "t30": -2.0},
            "win_rates": {"t5": 0.61, "t10": 0.45, "t30": 0.42},
            "bucket_sample_count": 48,
            "bucket_t30_mature_count": 25,
        },
        market_regime="crisis",
    )
    # action=AVOID (T+5 alone crisis 下不放行)
    assert verdict["action"] == "AVOID"
    # signal_horizon 仍标注 'T+5' (raw 信号, 让用户知道有 T+5 信号但被 crisis 门控)
    assert verdict["signal_horizon"] == "T+5", (
        "NS-23: crisis 下 T+5-only 被 AVOID 但 signal_horizon 仍标注 'T+5' — "
        "raw 信号展示, 让用户知道有 T+5 信号但 crisis 下不可靠"
    )


# ---------------------------------------------------------------------------
# C273 (2026-07-01): profit-aware ranking mode.
# c272 selection-profitability backtest (74 days, n=7993) proved the model's
# composite_score has NEGATIVE predictive value for top-N selection (score_desc
# portfolio T+5 winrate 47.3% vs equal_weight 59.5%). This adds an opt-in
# ``profit_aware`` ranking that keys on empirical bucket winrate instead.
# Opt-in only — default behavior unchanged (no change to existing users).
# ---------------------------------------------------------------------------


def test_profit_aware_ranks_by_empirical_winrate_not_composite() -> None:
    """C273: in profit-aware mode, rank by empirical bucket winrate (the
    backtested profit signal), not composite_score (negative predictive value).
    A low-composite / high-winrate pick must rank ABOVE high-composite / low-winrate.
    Default mode (profit_aware=False) keeps composite-first ordering."""
    recommendations = [
        {"ticker": "AAA", "name": "high-score low-winrate", "score_b": 0.80},
        {"ticker": "BBB", "name": "low-score high-winrate", "score_b": 0.30},
    ]
    composite = CompositeReport(
        trade_date="20260612",
        items=[
            CompositeEntry(ticker="AAA", name="high-score low-winrate", base_score=0.80, composite_score=0.85),
            CompositeEntry(ticker="BBB", name="low-score high-winrate", base_score=0.30, composite_score=0.25),
        ],
    )
    expected = ExpectedReturnReport(
        trade_date="20260612", lookback_days=60, total_samples=100,
        items=[
            ExpectedReturn(
                ticker="AAA", score_b=0.80, bucket_label="高 (>0.8)", bucket_sample_count=40,
                expected_returns={"t5": 1.0, "t10": 1.0}, win_rates={"t5": 0.42, "t10": 0.42},
            ),
            ExpectedReturn(
                ticker="BBB", score_b=0.30, bucket_label="低 (<0.3)", bucket_sample_count=50,
                expected_returns={"t5": 3.0, "t10": 3.0}, win_rates={"t5": 0.62, "t10": 0.62},
            ),
        ],
    )
    # default mode: composite first → AAA (0.85) > BBB (0.25)
    ranked_default = rank_recommendations_by_investability(recommendations, composite, expected)
    assert [r["ticker"] for r in ranked_default] == ["AAA", "BBB"], "default mode unchanged (composite-first)"
    # profit-aware mode: empirical winrate first → BBB (0.62) > AAA (0.42)
    ranked_pa = rank_recommendations_by_investability(recommendations, composite, expected, profit_aware=True)
    assert [r["ticker"] for r in ranked_pa] == ["BBB", "AAA"], (
        "profit-aware mode must rank by empirical bucket winrate, not composite_score "
        "— c272 backtest proved composite has negative predictive value (47% vs 60%)"
    )


def test_profit_aware_default_is_off() -> None:
    """C273 safety: profit_aware defaults to False (opt-in). Verifies the
    parameter exists and defaults off — existing callers see no behavior change."""
    import inspect
    sig = inspect.signature(rank_recommendations_by_investability)
    assert "profit_aware" in sig.parameters
    assert sig.parameters["profit_aware"].default is False


def test_profit_aware_survives_consecutive_bonus_resort() -> None:
    """R139 Bug Hunt: the profit-aware winrate ordering must survive the
    ``_apply_consecutive_bonus_and_resort`` step that ``_build_ranked_candidates``
    runs AFTER the ranker. c273's unit test (test_profit_aware_ranks_by_empirical_
    winrate_not_composite) proves the RANKER re-keys on winrate, but the WIRED
    path (``run_top_picks`` → ``_build_ranked_candidates`` → ranker →
    ``_apply_consecutive_bonus_and_resort``) always calls the resort, which
    re-sorts on ``composite_score`` primary — silently reverting the profit-aware
    ordering. The ``--profit-aware`` flag was a no-op in the integrated path
    despite the commit claiming "backtested 47%→62%".

    This guard runs the actual wired sequence (ranker THEN resort) and asserts
    the profit-aware winrate ordering is preserved end-to-end. Without passing
    ``profit_aware`` through to the resort (or skipping the composite re-sort in
    profit-aware mode), the low-composite/high-winrate pick (BBB) must STILL rank
    above the high-composite/low-winrate pick (AAA) after the resort.
    """
    from src.screening.top_picks import _apply_consecutive_bonus_and_resort

    recommendations = [
        {"ticker": "AAA", "name": "high-score low-winrate", "score_b": 0.80},
        {"ticker": "BBB", "name": "low-score high-winrate", "score_b": 0.30},
    ]
    composite = CompositeReport(
        trade_date="20260612",
        items=[
            CompositeEntry(ticker="AAA", name="high-score low-winrate", base_score=0.80, composite_score=0.85),
            CompositeEntry(ticker="BBB", name="low-score high-winrate", base_score=0.30, composite_score=0.25),
        ],
    )
    expected = ExpectedReturnReport(
        trade_date="20260612", lookback_days=60, total_samples=100,
        items=[
            ExpectedReturn(
                ticker="AAA", score_b=0.80, bucket_label="高 (>0.8)", bucket_sample_count=40,
                expected_returns={"t5": 1.0, "t10": 1.0}, win_rates={"t5": 0.42, "t10": 0.42},
            ),
            ExpectedReturn(
                ticker="BBB", score_b=0.30, bucket_label="低 (<0.3)", bucket_sample_count=50,
                expected_returns={"t5": 3.0, "t10": 3.0}, win_rates={"t5": 0.62, "t10": 0.62},
            ),
        ],
    )
    # Step 1: ranker alone (what c273's unit test checks) — profit-aware works here
    ranked_pa = rank_recommendations_by_investability(recommendations, composite, expected, profit_aware=True)
    assert [r["ticker"] for r in ranked_pa] == ["BBB", "AAA"], "ranker profit-aware ordering (c273 unit test)"

    # Step 2: the wired path applies _apply_consecutive_bonus_and_resort AFTER the ranker.
    # This must NOT revert the profit-aware winrate ordering back to composite-score order.
    # (profit_aware threads through _build_ranked_candidates → resort, mirroring the wired path.)
    ranked_after_resort = _apply_consecutive_bonus_and_resort([dict(r) for r in ranked_pa], profit_aware=True)
    assert [r["ticker"] for r in ranked_after_resort] == ["BBB", "AAA"], (
        "profit-aware ordering was reverted by _apply_consecutive_bonus_and_resort — the "
        "--profit-aware flag is a no-op in the wired run_top_picks path (the resort re-sorts "
        "on composite_score primary, undoing the ranker's winrate re-keying). c273's claimed "
        "47%→62% improvement is not delivered."
    )
