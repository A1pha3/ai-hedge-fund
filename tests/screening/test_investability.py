"""Tests for investability ranking helpers."""

from __future__ import annotations

from src.screening.composite_score import CompositeEntry, CompositeReport
from src.screening.expected_return import ExpectedReturn, ExpectedReturnReport
from src.screening.investability import (
    build_front_door_verdict,
    rank_recommendations_by_investability,
    select_representative_candidates,
)


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
            "expected_returns": {"t30": 9.4},
            "win_rates": {"t30": 0.63},
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
    pos = build_front_door_verdict(
        {"decision": "bullish", "composite_score": 0.4, "expected_returns": {"t30": 2.0},
         "win_rates": {"t30": 0.52}, "bucket_sample_count": 48},
        market_regime="trend",
    )
    assert "转负" not in pos["invalidation_reason"]
    # Negative edge → AVOID → "转负" reason present.
    neg = build_front_door_verdict(
        {"decision": "bullish", "composite_score": 0.4, "expected_returns": {"t30": -1.5},
         "win_rates": {"t30": 0.45}, "bucket_sample_count": 48},
        market_regime="trend",
    )
    assert "转负" in neg["invalidation_reason"]


def test_build_front_door_verdict_respects_risk_off_gate() -> None:
    verdict = build_front_door_verdict(
        {
            "decision": "bullish",
            "composite_score": 0.71,
            "expected_returns": {"t30": 11.2},
            "win_rates": {"t30": 0.66},
            "bucket_sample_count": 52,
        },
        market_regime="risk_off",
    )

    assert verdict["action"] == "HOLD"


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
