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
    FactorStateInversion,
    compute_factor_attribution_by_state_from_loaded,
    render_factor_attribution_by_state_line,
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
        # c322/autodev-36: 倒挂因子携带 bootstrap CI
        assert inv.inversion_ci_low is not None, "FactorStateInversion 应携带 CI"
        assert inv.inversion_ci_high is not None
        assert inv.inversion_ci_high >= inv.inversion_ci_low
        assert inv.inversion_ci_low > 0, "强倒挂 CI 下界 > 0"
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

    def test_score_controlled_inversion_carries_bootstrap_ci(self) -> None:
        """c321/autodev-36: score-controlled 因子倒挂携带 bootstrap CI (镜像 c317)."""
        from src.screening.factor_attribution_by_state import compute_factor_attribution_score_controlled_from_loaded
        recs = []
        # 全 low bucket, event_sentiment 高→负 (强倒挂, ~720 条)
        for i in range(120):
            recs.append({"score_decomposition": {"base_contributions": {"event_sentiment": 0.03}, "total": 0.2}, "next_5day_return": -3.0})
        for i in range(120):
            recs.append({"score_decomposition": {"base_contributions": {"event_sentiment": -0.04}, "total": 0.2}, "next_5day_return": +3.0})
        report = compute_factor_attribution_score_controlled_from_loaded(recs, min_n=15)
        inv = next((x for x in report.inversions if x.factor == "event_sentiment"), None)
        assert inv is not None
        # Bootstrap CI 应存在且上界 > 下界
        assert inv.inversion_ci_low is not None
        assert inv.inversion_ci_high is not None
        assert inv.inversion_ci_high >= inv.inversion_ci_low
        # 强倒挂 CI 应 > 0 (不跨零)
        assert inv.inversion_ci_low > 0, f"强倒挂 CI 下界应 > 0, got {inv.inversion_ci_low:.4f}"
        assert inv.inversion_ci_high > 0

    def test_score_controlled_render_shows_ci_bracket(self) -> None:
        """c321: render_score_controlled_factor_line 展示 CI 括号."""
        from src.screening.factor_attribution_by_state import (
            ScoreControlledFactorInversion, ScoreControlledFactorReport,
            render_score_controlled_factor_line,
        )
        inv = ScoreControlledFactorInversion(
            factor="event_sentiment", stratified_inversion=0.15,
            high_winrate=0.40, low_winrate=0.55, n=200, survives=True,
            inversion_ci_low=0.05, inversion_ci_high=0.25,
        )
        report = ScoreControlledFactorReport(
            inversions=[inv], sample_count=500,
            horizon_label="T+5", verdict="ok",
        )
        line = render_score_controlled_factor_line(report)
        assert "CI[" in line
        assert "+5%" in line or "+5.0%" in line or "5%" in line
        assert "15%" in line or "15.0%" in line or "+15%" in line
        assert "经 score 控制仍真实" in line

    def test_score_controlled_render_silent_when_insufficient(self) -> None:
        """insufficient 时 render 返回空串."""
        from src.screening.factor_attribution_by_state import (
            ScoreControlledFactorReport, render_score_controlled_factor_line,
        )
        report = ScoreControlledFactorReport(verdict="insufficient")
        assert render_score_controlled_factor_line(report) == ""

    def test_bootstrap_inversion_ci_upper_ge_lower(self) -> None:
        """_bootstrap_inversion_ci 单调性: upper >= lower (幂等 seed 相同)."""
        from src.screening.factor_attribution_by_state import _bootstrap_inversion_ci
        high_ret = [-2.0, -1.0, -3.0, -5.0, -1.5, -0.5, -4.0, -2.0, -3.5, -1.0]
        low_ret = [3.0, 5.0, 2.0, 1.0, 4.0, 3.5, 2.5, 1.5, 4.5, 3.0]
        lo, hi = _bootstrap_inversion_ci(high_ret, low_ret, n_bootstrap=500, seed=42)
        assert lo is not None and hi is not None
        assert hi >= lo
        # 强效应: CI 应 > 0
        assert lo > 0, f"强 inversion CI 下界应 > 0, got {lo:.4f}"

    def test_bootstrap_inversion_ci_deterministic(self) -> None:
        """同 seed → 同 CI (幂等)."""
        from src.screening.factor_attribution_by_state import _bootstrap_inversion_ci
        high_ret = [-2.0, -1.0, -3.0, -5.0] * 5
        low_ret = [3.0, 5.0, 2.0, 1.0] * 5
        lo1, hi1 = _bootstrap_inversion_ci(high_ret, low_ret, n_bootstrap=500, seed=42)
        lo2, hi2 = _bootstrap_inversion_ci(high_ret, low_ret, n_bootstrap=500, seed=42)
        assert lo1 == lo2 and hi1 == hi2

    def test_bootstrap_inversion_ci_returns_none_for_empty(self) -> None:
        """空输入 → None, None."""
        from src.screening.factor_attribution_by_state import _bootstrap_inversion_ci
        lo, hi = _bootstrap_inversion_ci([], [1.0, 2.0])
        assert lo is None and hi is None
        lo, hi = _bootstrap_inversion_ci([1.0, 2.0], [])
        assert lo is None and hi is None

    def test_factor_state_inversion_carries_bootstrap_ci(self) -> None:
        """c322/autodev-36: FactorStateInversion (uncontrolled) 也携带 bootstrap CI."""
        recs = []
        for i in range(30):
            recs.append(_rec(f"H{i}", "MIXED", {"MR": 0.08}, t5=-2.0))
        for i in range(30):
            recs.append(_rec(f"L{i}", "MIXED", {"MR": -0.08}, t5=+3.0))
        report = compute_factor_attribution_by_state_from_loaded(recs, min_n=15, horizon_field="next_5day_return")
        inv = next((x for x in report.inversions if x.state_type == "MIXED" and x.factor == "MR"), None)
        assert inv is not None
        assert inv.inversion_ci_low is not None
        assert inv.inversion_ci_high is not None
        assert inv.inversion_ci_high >= inv.inversion_ci_low

    def test_factor_state_render_shows_ci_bracket(self) -> None:
        """render_factor_attribution_by_state_line 展示 CI 括号."""
        inv = FactorStateInversion(
            state_type="MIXED", factor="MR",
            high_contrib_winrate=0.22, low_contrib_winrate=0.50,
            inversion=0.28, high_n=30, low_n=30,
            inversion_ci_low=0.10, inversion_ci_high=0.42,
        )
        report = FactorAttributionByStateReport(
            inversions=[inv], sample_count=100,
            state_types=["MIXED"], horizon_label="T+5", verdict="ok",
        )
        line = render_factor_attribution_by_state_line(report)
        assert "CI[" in line
        assert "+10%" in line or "+10.0%" in line or "10%" in line
        assert "帮倒忙" in line

    def test_factor_state_render_no_ci_fallback(self) -> None:
        """CI unavailable 时 fallback 到 bare estimate (无 CI)."""
        inv = FactorStateInversion(
            state_type="MIXED", factor="ES",
            high_contrib_winrate=0.30, low_contrib_winrate=0.55,
            inversion=0.25, high_n=30, low_n=30,
            inversion_ci_low=None, inversion_ci_high=None,
        )
        report = FactorAttributionByStateReport(
            inversions=[inv], sample_count=60,
            state_types=["MIXED"], horizon_label="T+5", verdict="ok",
        )
        line = render_factor_attribution_by_state_line(report)
        assert "CI[" not in line
        assert "帮倒忙" in line

    def test_factor_state_render_shows_n(self) -> None:
        """c332/autodev-36: n 现在展示 (镜像 _format_one_score_controlled)."""
        inv = FactorStateInversion(
            state_type="MIXED", factor="MR",
            high_contrib_winrate=0.30, low_contrib_winrate=0.55,
            inversion=0.25, high_n=40, low_n=60,
            inversion_ci_low=0.10, inversion_ci_high=0.40,
        )
        report = FactorAttributionByStateReport(
            inversions=[inv], sample_count=100,
            state_types=["MIXED"], horizon_label="T+5", verdict="ok",
        )
        line = render_factor_attribution_by_state_line(report)
        assert "n=100" in line  # total_n = high_n + low_n = 40 + 60


class TestAsOf:
    """c325/autodev-36: 数据时点披露."""

    def test_factor_state_report_has_as_of_when_data_available(self) -> None:
        """有 recommended_date 时, as_of 取最大值."""
        recs = [
            _rec("A", "MIXED", {"MR": 0.08}, t5=-2.0),
            _rec("B", "MIXED", {"MR": -0.08}, t5=+3.0),
        ]
        recs[0]["recommended_date"] = "20260702"
        recs[1]["recommended_date"] = "20260703"
        report = compute_factor_attribution_by_state_from_loaded(recs, min_n=1)
        assert report.as_of == "20260703"

    def test_score_controlled_report_has_as_of(self) -> None:
        from src.screening.factor_attribution_by_state import compute_factor_attribution_score_controlled_from_loaded
        recs = [
            {"score_decomposition": {"base_contributions": {"ES": 0.02}, "total": 0.3}, "next_5day_return": -2.0, "recommended_date": "20260701"},
            {"score_decomposition": {"base_contributions": {"ES": -0.05}, "total": 0.3}, "next_5day_return": +3.0, "recommended_date": "20260702"},
        ]
        report = compute_factor_attribution_score_controlled_from_loaded(recs, min_n=1)
        assert report.as_of == "20260702"

    def test_render_shows_as_of(self) -> None:
        """render 展示 | 数据时点."""
        inv = FactorStateInversion(
            state_type="MIXED", factor="MR",
            high_contrib_winrate=0.30, low_contrib_winrate=0.55,
            inversion=0.25, high_n=20, low_n=20,
            inversion_ci_low=0.10, inversion_ci_high=0.40,
        )
        report = FactorAttributionByStateReport(
            inversions=[inv], sample_count=40,
            state_types=["MIXED"], horizon_label="T+5", verdict="ok",
            as_of="20260703",
        )
        line = render_factor_attribution_by_state_line(report)
        assert "数据时点" in line
        assert "20260703" in line

    def test_render_no_as_of_when_none(self) -> None:
        """as_of=None 时不显示数据时点."""
        inv = FactorStateInversion(
            state_type="MIXED", factor="ES",
            high_contrib_winrate=0.30, low_contrib_winrate=0.55,
            inversion=0.25, high_n=20, low_n=20,
        )
        report = FactorAttributionByStateReport(
            inversions=[inv], sample_count=40,
            state_types=["MIXED"], horizon_label="T+5", verdict="ok",
        )
        line = render_factor_attribution_by_state_line(report)
        assert "数据时点" not in line


class TestDeterministicStrHash:
    """c337/autodev-36 regression: stable across process restarts."""

    def test_known_values(self) -> None:
        """Lock the Java String.hashCode() algorithm to known outputs."""
        from src.screening.factor_attribution_by_state import _deterministic_str_hash
        assert _deterministic_str_hash("") == 0
        assert _deterministic_str_hash("a") == 97
        assert _deterministic_str_hash("ab") == 3105  # 31*97 + 98

    def test_consistent_with_sibling_modules(self) -> None:
        """All 3 implementations must produce identical hashes."""
        from src.screening.factor_attribution_by_state import _deterministic_str_hash as h1
        from src.screening.north_star_pnl import _deterministic_str_hash as h2
        from src.screening.model_version_comparison import _deterministic_str_hash as h3
        for s in ["event_sentiment", "trend", "score_desc"]:
            assert h1(s) == h2(s) == h3(s)
