"""Tests for P3-3: industry_cross_picks module."""
from src.screening.industry_cross_picks import (
    _extract_top_picks_for_industry,
    compute_cross_picks,
    CrossPick,
    IndustryTopPick,
    render_cross_picks,
)

SAMPLE_RECS = [
    {"ticker": "000001", "name": "平安银行", "industry_sw": "银行", "score_b": 0.85, "decision": "bullish"},
    {"ticker": "600036", "name": "招商银行", "industry_sw": "银行", "score_b": 0.75, "decision": "bullish"},
    {"ticker": "601398", "name": "工商银行", "industry_sw": "银行", "score_b": 0.65, "decision": "bullish"},
    {"ticker": "000858", "name": "五粮液", "industry_sw": "食品饮料", "score_b": 0.78, "decision": "bullish"},
    {"ticker": "600519", "name": "贵州茅台", "industry_sw": "食品饮料", "score_b": 0.90, "decision": "bullish"},
    {"ticker": "300750", "name": "宁德时代", "industry_sw": "电力设备", "score_b": 0.55, "decision": "neutral"},
]


class TestExtractTopPicks:
    def test_filters_by_industry(self):
        picks = _extract_top_picks_for_industry(SAMPLE_RECS, "银行", max_picks=3)
        assert len(picks) == 3
        # Sorted by score_b desc
        assert picks[0].ticker == "000001"  # score_b 0.85
        assert picks[1].ticker == "600036"  # 0.75
        assert picks[2].ticker == "601398"  # 0.65

    def test_max_picks_limits(self):
        picks = _extract_top_picks_for_industry(SAMPLE_RECS, "银行", max_picks=2)
        assert len(picks) == 2

    def test_unknown_industry_empty(self):
        picks = _extract_top_picks_for_industry(SAMPLE_RECS, "未知行业", max_picks=3)
        assert picks == []

    def test_empty_recs_empty(self):
        picks = _extract_top_picks_for_industry([], "银行", max_picks=3)
        assert picks == []


class TestComputeCrossPicks:
    def test_basic_computation(self):
        result = compute_cross_picks(SAMPLE_RECS, top_industries=2, picks_per_industry=2)
        assert len(result) == 2  # Top 2 industries
        # All have top_picks
        for cp in result:
            assert cp.candidate_count > 0
            assert len(cp.top_picks) > 0

    def test_empty_recs(self):
        result = compute_cross_picks([], top_industries=5, picks_per_industry=3)
        assert result == []

    def test_top_industries_limit(self):
        result = compute_cross_picks(SAMPLE_RECS, top_industries=2, picks_per_industry=3)
        # Should not exceed 2 industries
        assert len(result) <= 2

    def test_top_picks_per_industry_limit(self):
        result = compute_cross_picks(SAMPLE_RECS, top_industries=3, picks_per_industry=2)
        for cp in result:
            assert len(cp.top_picks) <= 2

    def test_industries_sorted_by_momentum(self):
        result = compute_cross_picks(SAMPLE_RECS, top_industries=3, picks_per_industry=2)
        # momentum_score should be descending
        for i in range(len(result) - 1):
            assert result[i].momentum_score >= result[i + 1].momentum_score

    def test_picks_sorted_by_score(self):
        result = compute_cross_picks(SAMPLE_RECS, top_industries=3, picks_per_industry=3)
        for cp in result:
            for i in range(len(cp.top_picks) - 1):
                assert cp.top_picks[i].score_b >= cp.top_picks[i + 1].score_b


class TestRenderCrossPicks:
    def test_renders_basic(self):
        result = compute_cross_picks(SAMPLE_RECS, top_industries=2, picks_per_industry=2)
        output = render_cross_picks(result)
        assert "行业 + 个股交叉选择" in output
        assert "动量" in output
        assert "Top 标的" in output

    def test_renders_empty(self):
        output = render_cross_picks([])
        assert "无交叉选择数据" in output
