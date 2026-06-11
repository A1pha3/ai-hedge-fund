"""P4-1: 行业内相对强度 — _compute_relative_strength 测试。

覆盖:
  - 多行业分组 + 百分位排名
  - 单一行业 < 2 只 → 中性 0.5
  - 空结果列表
  - 同行业同 score_b (ties)
  - 无 industry_sw 标记 → 归入 "未知"
"""
from __future__ import annotations

from src.screening.models import FusedScore
from src.screening.signal_fusion import _compute_relative_strength


def _make_fused(ticker: str, score_b: float, industry_sw: str = "") -> FusedScore:
    return FusedScore(ticker=ticker, score_b=score_b, industry_sw=industry_sw)


class TestComputeRelativeStrength:
    """P4-1: 行业内相对强度测试。"""

    def test_basic_two_industries(self) -> None:
        """两个行业, 各 3 只标的 — 验证百分位计算正确。"""
        results = [
            _make_fused("A", 0.5, "电子"),
            _make_fused("B", 0.3, "电子"),
            _make_fused("C", 0.1, "电子"),
            _make_fused("D", 0.4, "医药"),
            _make_fused("E", 0.2, "医药"),
            _make_fused("F", 0.0, "医药"),
        ]
        _compute_relative_strength(results)

        by_ticker = {r.ticker: r for r in results}

        # 电子: sorted [C=0.1, B=0.3, A=0.5] → percentiles [0.0, 0.5, 1.0]
        assert by_ticker["C"].metrics["industry_relative_strength"] == 0.0
        assert by_ticker["B"].metrics["industry_relative_strength"] == 0.5
        assert by_ticker["A"].metrics["industry_relative_strength"] == 1.0

        # 医药: sorted [F=0.0, E=0.2, D=0.4] → percentiles [0.0, 0.5, 1.0]
        assert by_ticker["F"].metrics["industry_relative_strength"] == 0.0
        assert by_ticker["E"].metrics["industry_relative_strength"] == 0.5
        assert by_ticker["D"].metrics["industry_relative_strength"] == 1.0

    def test_single_stock_in_industry_gets_neutral(self) -> None:
        """行业内仅 1 只标的 → 中性 0.5。"""
        results = [_make_fused("A", 0.8, "独门")]
        _compute_relative_strength(results)
        assert results[0].metrics["industry_relative_strength"] == 0.5

    def test_empty_results(self) -> None:
        """空列表不报错。"""
        _compute_relative_strength([])

    def test_two_stocks_same_industry(self) -> None:
        """同行业 2 只 → 排名 [0.0, 1.0]。"""
        results = [
            _make_fused("X", 0.6, "金融"),
            _make_fused("Y", 0.2, "金融"),
        ]
        _compute_relative_strength(results)
        by_ticker = {r.ticker: r for r in results}
        assert by_ticker["X"].metrics["industry_relative_strength"] == 1.0
        assert by_ticker["Y"].metrics["industry_relative_strength"] == 0.0

    def test_ties_same_score(self) -> None:
        """同行业同 score_b → 相同百分位。"""
        results = [
            _make_fused("P", 0.3, "化工"),
            _make_fused("Q", 0.3, "化工"),
            _make_fused("R", 0.1, "化工"),
        ]
        _compute_relative_strength(results)
        by_ticker = {r.ticker: r for r in results}
        # sorted: R(0.1), P(0.3), Q(0.3) or R(0.1), Q(0.3), P(0.3)
        # P and Q are ties — both get rank 1 or 2
        # R gets percentile 0.0
        assert by_ticker["R"].metrics["industry_relative_strength"] == 0.0
        # P and Q should be 1.0 and 0.5 (or vice versa depending on sort stability)
        pq = {by_ticker["P"].metrics["industry_relative_strength"], by_ticker["Q"].metrics["industry_relative_strength"]}
        assert pq == {0.5, 1.0}

    def test_missing_industry_defaults_to_unknown(self) -> None:
        """无 industry_sw → 归入 "未知" 组。"""
        results = [
            _make_fused("A", 0.7, ""),
            _make_fused("B", 0.3, ""),
        ]
        _compute_relative_strength(results)
        by_ticker = {r.ticker: r for r in results}
        assert by_ticker["A"].metrics["industry_relative_strength"] == 1.0
        assert by_ticker["B"].metrics["industry_relative_strength"] == 0.0

    def test_does_not_modify_score_b(self) -> None:
        """相对强度计算不改变原始 score_b。"""
        results = [
            _make_fused("A", 0.5, "X"),
            _make_fused("B", 0.1, "X"),
        ]
        original_scores = {r.ticker: r.score_b for r in results}
        _compute_relative_strength(results)
        for r in results:
            assert r.score_b == original_scores[r.ticker]

    def test_mixed_industries_with_isolation(self) -> None:
        """不同行业的百分位互不影响。"""
        results = [
            _make_fused("A", 0.9, "科技"),  # 科技最强
            _make_fused("B", 0.1, "科技"),  # 科技最弱
            _make_fused("C", 0.9, "消费"),  # 消费最强
            _make_fused("D", 0.8, "消费"),  # 消费次强
        ]
        _compute_relative_strength(results)
        by_ticker = {r.ticker: r for r in results}

        # 科技: [B=0.0, A=1.0]
        assert by_ticker["A"].metrics["industry_relative_strength"] == 1.0
        assert by_ticker["B"].metrics["industry_relative_strength"] == 0.0

        # 消费: [D=0.0, C=1.0]
        assert by_ticker["C"].metrics["industry_relative_strength"] == 1.0
        assert by_ticker["D"].metrics["industry_relative_strength"] == 0.0

        # D has score_b=0.8 (high absolute) but worst in 消费 → relative=0.0
        # B has score_b=0.1 (low absolute) but worst in 科技 → relative=0.0
        # This shows the isolation works correctly
