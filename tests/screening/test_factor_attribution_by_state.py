"""TDD for factor_attribution_by_state — NS-6 因子归因 × state_type (历史回测).

NS-6 (§三·6): 各因子(T/MR/F/E)正/负贡献 × state_type 的 T+5/T+10 胜率,
告诉 owner 哪个因子在哪个市场帮倒忙。镜像 factor_attribution (overall) +
state_type_calibration 结构。纯诊断, 不改因子/gate/仓位。

数据来源 (用户方法论: 历史回测先行, 不等 score_decomposition 持久化成熟):
  tracking_history (realized T+5/T+10 return) JOIN 历史报告 recommendations
  (score_decomposition.base_contributions + market_state.state_type) on (ticker, date).
"""
from __future__ import annotations

from src.screening.factor_attribution_by_state import (
    FactorAttributionByStateReport,
    compute_factor_attribution_by_state_from_loaded,
)


def _rec(ticker: str, state: str, contribs: dict[str, float], t5: float) -> dict:
    """合成 record: state_type + score_decomposition.base_contributions + T+5 return."""
    return {
        "ticker": ticker,
        "state_type": state,
        "score_decomposition": {"base_contributions": contribs},
        "next_5day_return": t5,
    }


class TestComputeFactorAttributionByState:
    def test_detects_factor_inversion_in_one_state(self) -> None:
        """MR 因子在 MIXED 市场: 高贡献反而低胜率 (倒挂 = 帮倒忙)."""
        # MIXED: MR 高贡献 → 多数负 return (倒挂); MR 低贡献 → 多数正 return
        recs = []
        for i in range(30):  # MR 高贡献组 (倒挂: 高贡献低胜率)
            recs.append(_rec(f"H{i}", "MIXED", {"MR": 0.08, "T": 0.01}, t5=-2.0))
        for i in range(30):  # MR 低贡献组 (高胜率)
            recs.append(_rec(f"L{i}", "MIXED", {"MR": -0.08, "T": 0.01}, t5=+3.0))
        for i in range(30):  # TREND: MR 正常 (高贡献高胜率, 无倒挂)
            recs.append(_rec(f"T{i}", "TREND", {"MR": 0.08, "T": 0.01}, t5=+2.0))
        report = compute_factor_attribution_by_state_from_loaded(recs, min_n=15, horizon_field="next_5day_return")
        inv = next((x for x in report.inversions if x.state_type == "MIXED" and x.factor == "MR"), None)
        assert inv is not None, "MIXED 市场 MR 倒挂应被检测"
        assert inv.inversion > 0.05  # low_winrate - high_winrate > 0 (倒挂)
        # TREND 市场 MR 不应倒挂
        inv_trend = next((x for x in report.inversions if x.state_type == "TREND"), None)
        assert inv_trend is None

    def test_insufficient_when_sample_too_small(self) -> None:
        """样本不足 (每 state×factor 组 < min_n) → insufficient, 不下结论."""
        recs = [_rec("A", "MIXED", {"MR": 0.08}, t5=1.0) for _ in range(5)]
        report = compute_factor_attribution_by_state_from_loaded(recs, min_n=15)
        assert report.verdict == "insufficient"
        assert report.inversions == []

    def test_no_inversion_when_factor_helps(self) -> None:
        """因子高贡献 → 高胜率 (正向, 无倒挂)."""
        recs = []
        for i in range(30):
            recs.append(_rec(f"H{i}", "RANGE", {"T": 0.08}, t5=+2.0))  # T 高贡献 + 正 return
        for i in range(30):
            recs.append(_rec(f"L{i}", "RANGE", {"T": -0.08}, t5=-2.0))  # T 低贡献 + 负 return
        report = compute_factor_attribution_by_state_from_loaded(recs, min_n=15)
        assert report.inversions == []  # T 在 RANGE 是正向, 无倒挂

    def test_skips_records_without_decomposition_or_return(self) -> None:
        """缺 score_decomposition 或 return 的 record 跳过 (不污染)."""
        recs = [
            {"ticker": "X", "state_type": "MIXED", "next_5day_return": 1.0},  # 无 decomp
            _rec("Y", "MIXED", {"MR": 0.08}, t5=2.0),
        ]
        report = compute_factor_attribution_by_state_from_loaded(recs, min_n=1)
        assert report.sample_count == 1  # 只 Y 有效


class TestScoreControlledFactorAttribution:
    """NS-6 score-controlled: 隔离因子真实效应 (排除 score-level confound).

    c239 uncontrolled NS-6 把 fundamental 标为倒挂 (+9%), 但 score-controlled 后
    只剩 +5% (borderline) — 多数是 score-level inversion (NS-4) 的 confound.
    event_sentiment 经 control 仍 +15% (真实倒挂). owner 据 score-controlled 视图决策.
    """

    def test_real_factor_inversion_survives_score_control(self) -> None:
        """真实因子效应: 同 score bucket 内, 高贡献→低胜率 (经 control 仍倒挂)."""
        from src.screening.factor_attribution_by_state import compute_factor_attribution_score_controlled_from_loaded
        recs = []
        # 全在 low bucket (score~0.2), 排除 score confound; event_sentiment 高→负return
        for i in range(60):
            recs.append({"score_decomposition": {"base_contributions": {"event_sentiment": 0.02}, "total": 0.2}, "next_5day_return": -2.0})
        for i in range(60):
            recs.append({"score_decomposition": {"base_contributions": {"event_sentiment": -0.05}, "total": 0.2}, "next_5day_return": +3.0})
        report = compute_factor_attribution_score_controlled_from_loaded(recs, min_n=15)
        inv = next((x for x in report.inversions if x.factor == "event_sentiment"), None)
        assert inv is not None, "event_sentiment 真实倒挂应被检测 (经 score control)"
        assert inv.stratified_inversion > 0.05

    def test_score_confound_filtered_out(self) -> None:
        """纯 score confound (无真实因子效应): score-controlled 后不报倒挂."""
        from src.screening.factor_attribution_by_state import compute_factor_attribution_score_controlled_from_loaded
        recs = []
        # factor 贡献完全跟随 score (无独立效应); winrate 由 score 决定非 factor
        # low bucket: factor 低 + 高 winrate; high bucket: factor 高 + 低 winrate
        # uncontrolled 会显示倒挂, 但 within-bucket factor 无效应 → score-controlled 无倒挂
        for i in range(60):  # low bucket, factor 低
            recs.append({"score_decomposition": {"base_contributions": {"trend": 0.01}, "total": 0.2}, "next_5day_return": +2.0})
        for i in range(60):  # low bucket, factor 高 (within low, factor 高也高 winrate — 无倒挂)
            recs.append({"score_decomposition": {"base_contributions": {"trend": 0.05}, "total": 0.2}, "next_5day_return": +2.0})
        for i in range(60):  # high bucket
            recs.append({"score_decomposition": {"base_contributions": {"trend": 0.20}, "total": 0.6}, "next_5day_return": -2.0})
        report = compute_factor_attribution_score_controlled_from_loaded(recs, min_n=15)
        # within low bucket, trend 高/低 都是 +2.0 (50/50) → 无 within-bucket 倒挂
        inv = next((x for x in report.inversions if x.factor == "trend"), None)
        assert inv is None, "纯 score confound (within-bucket 无效应) 不应报倒挂"
