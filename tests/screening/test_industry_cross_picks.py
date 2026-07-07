"""Tests for P3-3: industry_cross_picks module."""

from src.screening.industry_cross_picks import (
    _extract_top_picks_for_industry,
    compute_cross_picks,
    compute_cross_picks_verdict_summary,
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

    def test_renders_front_door_verdict_beside_raw_decision(self):
        result = compute_cross_picks(SAMPLE_RECS, top_industries=2, picks_per_industry=2)
        output = render_cross_picks(result)

        assert "bullish" in output
        assert "前门=AVOID" in output

    def test_renders_empty(self):
        output = render_cross_picks([])
        assert "无交叉选择数据" in output


class TestComputeCrossPicksVerdictSummary:
    """autodev-24 loop 2: 前门判决汇总 (extending loop126 pattern)."""

    def test_verdict_summary_empty_cross_picks(self):
        buy, hold, avoid, total = compute_cross_picks_verdict_summary([])
        assert buy == []
        assert hold == []
        assert avoid == []
        assert total == 0

    def test_verdict_summary_all_AVOID(self):
        picks = [
            CrossPick(industry_name="银行", industry_rank=1, momentum_score=10.0, candidate_count=2,
                      top_picks=[
                          IndustryTopPick(ticker="000001", name="平安银行", score_b=0.5, decision="bullish", front_door_action="AVOID"),
                          IndustryTopPick(ticker="600036", name="招商银行", score_b=0.4, decision="bullish", front_door_action="AVOID"),
                      ]),
        ]
        buy, hold, avoid, total = compute_cross_picks_verdict_summary(picks)
        assert buy == []
        assert hold == []
        assert len(avoid) == 2
        assert "000001" in avoid
        assert "600036" in avoid
        assert total == 2

    def test_verdict_summary_mixed(self):
        picks = [
            CrossPick(industry_name="银行", industry_rank=1, momentum_score=10.0, candidate_count=3,
                      top_picks=[
                          IndustryTopPick(ticker="000001", name="A", score_b=0.5, decision="bullish", front_door_action="BUY"),
                          IndustryTopPick(ticker="600036", name="B", score_b=0.4, decision="bullish", front_door_action="HOLD"),
                          IndustryTopPick(ticker="601398", name="C", score_b=0.3, decision="neutral", front_door_action="AVOID"),
                      ]),
        ]
        buy, hold, avoid, total = compute_cross_picks_verdict_summary(picks)
        assert buy == ["000001"]
        assert hold == ["600036"]
        assert avoid == ["601398"]
        assert total == 3

    def test_verdict_summary_defaults_AVOID_when_front_door_none(self):
        """front_door_action 为空/Nones → 归类为 AVOID."""
        picks = [
            CrossPick(industry_name="测试", industry_rank=1, momentum_score=5.0, candidate_count=1,
                      top_picks=[
                          IndustryTopPick(ticker="000001", name="A", score_b=0.5, decision="bullish", front_door_action=""),
                      ]),
        ]
        buy, hold, avoid, total = compute_cross_picks_verdict_summary(picks)
        assert buy == []
        assert avoid == ["000001"]
        assert total == 1


# ── Integration guard (autodev-24 loop 3): --cross-picks CLI output ──


class TestCrossPicksVerdictSummaryIntegration:
    """Integration guard: run_industry_cross_picks 必须在 CLI 输出中渲染
    🎯 前门判决 汇总行. Locks in autodev-24 loop 2 fix.

    回归风险: 如果未来重构 run_industry_cross_picks 移除了 compute_cross_picks_verdict_summary
    调用块, compute_cross_picks_verdict_summary 的单元测试仍 pass, 但 CLI 不再显示
    汇总. 本集成测试 mock compute_cross_picks 并捕获 stdout, 确保完整路径不变.
    """

    def test_cli_output_contains_verdict_summary(self, tmp_path, capsys) -> None:
        """run_industry_cross_picks 的 stdout 必须包含 🎯 前门判决 汇总."""
        import json
        from unittest.mock import patch

        report_dir = tmp_path / "data" / "reports"
        report_dir.mkdir(parents=True)
        payload = {
            "mode": "auto_screening", "date": "20260609",
            "market_state": {"state_type": "trend_up", "regime_gate_level": "normal"},
            "top_n": 5,
            "recommendations": [{"ticker": "000001", "industry_sw": "银行", "score_b": 0.5}],
        }
        (report_dir / "auto_screening_20260609.json").write_text(json.dumps(payload), encoding="utf-8")

        mock_picks = [
            CrossPick(industry_name="银行", industry_rank=1, momentum_score=10.0, candidate_count=2,
                      top_picks=[
                          IndustryTopPick(ticker="000001", name="A", score_b=0.5, decision="bullish", front_door_action="BUY"),
                          IndustryTopPick(ticker="002049", name="B", score_b=0.4, decision="bullish", front_door_action="AVOID"),
                      ]),
        ]

        from src.screening.consecutive_recommendation import resolve_report_dir
        with patch("src.screening.consecutive_recommendation.resolve_report_dir", return_value=report_dir), \
             patch("src.screening.industry_cross_picks.compute_cross_picks", return_value=mock_picks):
            from src.main import run_industry_cross_picks
            rc = run_industry_cross_picks(trade_date="20260609", top_industries=1, picks_per_industry=2)

        out = capsys.readouterr().out
        assert rc == 0
        # 汇总行必须出现在输出中
        assert "前门判决" in out
        assert "BUY 1/2" in out
        assert "AVOID 1" in out
        # AVOID 个票必须列出
        assert "002049" in out
        assert "前门门控拒绝" in out
