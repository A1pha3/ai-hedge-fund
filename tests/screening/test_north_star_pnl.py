"""NS-3 北极星 P&L 趋势仪表模块的合成数据测试.

不依赖真实报告文件 —— 全部用内联合成 tracking records. 验证:
  - 累积等权 mean P&L 计算 (默认 horizon = T+5, BUY gate 决策 horizon; 2026-06-28 缩短自 T+30)
  - 整体 winrate + median (典型票, 免异常值污染)
  - mean/median 背离检测 (R-6/R-7: mean 被少数大赢家拉高但典型票微亏)
  - render 3 色态 (divergent⚠ / positive✓ / negative⚠) + insufficient 静默
  - horizon 可配置 (T+5 默认 / T+10 / T+30 长期 invalidation)
"""
from __future__ import annotations

from src.screening.north_star_pnl import (
    compute_north_star_pnl_from_loaded,
    render_north_star_line,
)


def _records(date_returns: dict[str, list[float]]) -> list[dict]:
    """{date: [returns]} → flat tracking record list (默认 horizon field = next_5day_return)."""
    out = []
    for dt, rets in date_returns.items():
        for r in rets:
            out.append({"recommended_date": dt, "next_5day_return": r})
    return out


def test_cumulative_mean_and_winrate_median():
    """2 日期: 各 3 只, 等权 mean 累积 + winrate/median 整体."""
    recs = _records(
        {"20250101": [10.0, -5.0, 8.0], "20250102": [6.0, -2.0, 4.0]}
    )
    rep = compute_north_star_pnl_from_loaded(recs, min_n=2)
    # 每日等权 avg: day1=13/3=4.33, day2=8/3=2.67; 累积=7.0
    assert abs(rep.cumulative_mean_pnl - 7.0) < 0.01
    # 整体 winrate: 4 正 / 6 = 0.667
    assert abs(rep.overall_winrate - 4 / 6) < 0.01
    # median of [10,-5,8,6,-2,4] sorted=[-5,-2,4,6,8,10] → (4+6)/2=5
    assert rep.overall_median == 5.0
    assert rep.sample_count == 6
    assert rep.sample_dates == 2


def test_divergent_when_mean_positive_but_median_negative():
    """mean 正 (大赢家拉高) 但 median 负 + winrate<50% → divergent (典型票微亏)."""
    recs = _records({"20250101": [200.0, -3.0, -2.0, -4.0, -1.0]})  # 1 大赢家 + 4 微亏
    rep = compute_north_star_pnl_from_loaded(recs, min_n=2)
    assert rep.mean_median_divergence is True
    assert rep.verdict == "divergent"
    # mean 正 (200-10)/5=38, 但 median=-2, winrate=0.2
    assert rep.cumulative_mean_pnl > 0
    assert rep.overall_median < 0
    assert rep.overall_winrate < 0.5


def test_positive_when_mean_winrate_median_all_positive():
    """mean + median + winrate 全正 → positive (真趋近北极星)."""
    recs = _records({"20250101": [5.0, 3.0, 8.0, 2.0, 6.0]})  # 全涨
    rep = compute_north_star_pnl_from_loaded(recs, min_n=2)
    assert rep.verdict == "positive"
    assert rep.mean_median_divergence is False
    assert rep.overall_winrate == 1.0
    assert rep.overall_median > 0


def test_negative_when_mean_negative():
    """mean 负 → negative (明显亏)."""
    recs = _records({"20250101": [-5.0, -3.0, -8.0, -2.0, -6.0]})  # 全跌
    rep = compute_north_star_pnl_from_loaded(recs, min_n=2)
    assert rep.verdict == "negative"
    assert rep.cumulative_mean_pnl < 0


def test_insufficient_when_below_min_n():
    """n < min_n → insufficient (诚实, 不下结论)."""
    recs = _records({"20250101": [5.0, 3.0]})  # n=2 < min_n=5
    rep = compute_north_star_pnl_from_loaded(recs, min_n=5)
    assert rep.verdict == "insufficient"


def test_render_divergent_has_warning():
    rep = compute_north_star_pnl_from_loaded(
        _records({"20250101": [200.0, -3.0, -2.0, -4.0, -1.0]}), min_n=2
    )
    line = render_north_star_line(rep)
    assert line
    assert "北极星" in line
    assert "典型" in line  # 显示 median
    assert "胜率" in line  # 显示 winrate


def test_render_silent_when_insufficient():
    rep = compute_north_star_pnl_from_loaded(
        _records({"20250101": [5.0, 3.0]}), min_n=5
    )
    assert render_north_star_line(rep) == ""


def test_render_positive_green():
    rep = compute_north_star_pnl_from_loaded(
        _records({"20250101": [5.0, 3.0, 8.0, 2.0, 6.0]}), min_n=2
    )
    line = render_north_star_line(rep)
    assert line
    assert "趋近" in line or "✓" in line


def test_render_positive_warns_when_mean_inflated_by_outliers():
    """C270 (2026-07-01, empirical dogfood on 2026-06-30 report): when the
    cumulative mean is positive but wildly inflated by a few outliers
    (mean >> median, both positive), the `positive` verdict must warn — not a
    bare ✓. The 2026-06-30 north star headlined ``+102% (mean) ✓ 趋近 >0`` while
    the typical (median) pick made only +2%; for a 赚钱工具 this overstates the
    typical user's outcome by ~50×. R-6/R-7 established median honesty; the
    existing ``divergent`` verdict only catches ``median < 0``. This test pins
    the extension: mean >> median (both positive) shows ✓ PLUS a warning."""
    rep = compute_north_star_pnl_from_loaded(
        _records({"20250101": [200.0, 2.0, 1.0, 3.0, 1.0]}), min_n=2
    )
    # both mean and median positive → positive verdict (not divergent)
    assert rep.verdict == "positive"
    assert rep.cumulative_mean_pnl - rep.overall_median > 10  # mean inflated by outlier
    line = render_north_star_line(rep)
    assert line
    # still positive (both metrics positive) — keeps the ✓/趋近 signal...
    assert "趋近" in line or "✓" in line
    # ...but warns the mean is inflated (not a bare green ✓)
    assert "拉高" in line


def test_render_positive_no_warning_when_mean_close_to_median():
    """C270 negative guard: when mean ≈ median (no outlier inflation), the
    positive verdict shows a bare ✓ with no inflation warning."""
    rep = compute_north_star_pnl_from_loaded(
        _records({"20250101": [5.0, 3.0, 8.0, 2.0, 6.0]}), min_n=2
    )
    assert rep.verdict == "positive"
    assert (rep.cumulative_mean_pnl - rep.overall_median) <= 10
    line = render_north_star_line(rep)
    assert "拉高" not in line


def test_finite_float_rejects_nan_garbage():
    from src.screening.north_star_pnl import _finite_float

    assert _finite_float(None) is None
    assert _finite_float("abc") is None
    assert _finite_float(float("nan")) is None
    assert _finite_float("1.5") == 1.5


def test_handles_missing_and_garbage_returns():
    """缺 next_5day_return / NaN / 字符串 → 跳过, 不崩."""
    recs = [
        {"recommended_date": "20250101", "next_5day_return": 5.0},
        {"recommended_date": "20250101"},  # 缺
        {"recommended_date": "20250101", "next_5day_return": None},
        {"recommended_date": "20250101", "next_5day_return": float("nan")},
        {"recommended_date": "20250101", "next_5day_return": "abc"},
        {"recommended_date": "20250101", "next_5day_return": -2.0},
    ]
    rep = compute_north_star_pnl_from_loaded(recs, min_n=2)
    # 只 2 条有效 (5.0, -2.0) → n=2
    assert rep.sample_count == 2


def test_horizon_configurable_default_t5_label_and_t30_explicit():
    """horizon_field 可配置: 默认 T+5 (label), 显式传 next_30day_return 走 T+30."""
    recs = [
        {"recommended_date": "20250101", "next_5day_return": 3.0, "next_30day_return": 9.0},
        {"recommended_date": "20250101", "next_5day_return": -1.0, "next_30day_return": -5.0},
    ]
    # 默认 T+5
    rep_t5 = compute_north_star_pnl_from_loaded(recs, min_n=2)
    assert rep_t5.horizon_label == "T+5"
    assert abs(rep_t5.cumulative_mean_pnl - 1.0) < 0.01  # (3 + -1)/2 = 1.0 per day
    # 显式 T+30 (长期 invalidation 子度量)
    rep_t30 = compute_north_star_pnl_from_loaded(recs, min_n=2, horizon_field="next_30day_return")
    assert rep_t30.horizon_label == "T+30"
    assert abs(rep_t30.cumulative_mean_pnl - 2.0) < 0.01  # (9 + -5)/2 = 2.0


def test_render_shows_horizon_label():
    """render 输出含 horizon_label (T+5 默认), 让用户知道度量的是哪个周期."""
    rep = compute_north_star_pnl_from_loaded(
        _records({"20250101": [5.0, 3.0, 8.0, 2.0, 6.0]}), min_n=2
    )
    line = render_north_star_line(rep)
    assert "(T+5)" in line


# ---------------------------------------------------------------------------
# M9: 持有期收益曲线 (holding period) — 全样本, 不受 high bucket n=38 限制
# 各 horizon avg/winrate/median → 最优卖出点 + 推荐票稳健画像
# ---------------------------------------------------------------------------

from src.screening.north_star_pnl import (  # noqa: E402
    HoldingPeriodPoint,
    compute_holding_period_curve_from_loaded,
    render_holding_period_line,
)


def test_holding_period_curve_per_horizon():
    recs = [
        {"next_5day_return": 5.0, "next_30day_return": 10.0},
        {"next_5day_return": -3.0, "next_30day_return": -5.0},
    ]
    curve = compute_holding_period_curve_from_loaded(recs, ["next_5day_return", "next_30day_return"], min_n=2)
    p5 = [p for p in curve if p.horizon == "next_5day_return"][0]
    assert p5.avg_return == 1.0  # (5 + -3)/2
    assert p5.winrate == 0.5
    assert p5.median_return == 1.0
    assert p5.sample_count == 2
    p30 = [p for p in curve if p.horizon == "next_30day_return"][0]
    assert p30.avg_return == 2.5  # (10 + -5)/2


def test_holding_period_curve_insufficient_below_min_n():
    recs = [{"next_5day_return": 5.0}]
    curve = compute_holding_period_curve_from_loaded(recs, ["next_5day_return"], min_n=2)
    assert curve[0].verdict == "insufficient"


def test_holding_period_curve_handles_missing_horizon():
    recs = [{"next_5day_return": 5.0}, {"next_5day_return": 3.0}]  # 无 next_30day
    curve = compute_holding_period_curve_from_loaded(recs, ["next_5day_return", "next_30day_return"], min_n=2)
    p30 = [p for p in curve if p.horizon == "next_30day_return"][0]
    assert p30.verdict == "insufficient"  # 缺字段
    p5 = [p for p in curve if p.horizon == "next_5day_return"][0]
    assert p5.verdict != "insufficient"


def test_render_holding_period_line_shows_horizons():
    recs = [{"next_5day_return": 5.0, "next_30day_return": 10.0}, {"next_5day_return": -3.0, "next_30day_return": -5.0}]
    curve = compute_holding_period_curve_from_loaded(recs, ["next_5day_return", "next_30day_return"], min_n=2)
    line = render_holding_period_line(curve)
    assert line
    assert "T+5" in line or "next_5day" in line
    assert "T+30" in line or "next_30day" in line


def test_render_holding_period_silent_when_all_insufficient():
    recs = [{"next_5day_return": 5.0}]
    curve = compute_holding_period_curve_from_loaded(recs, ["next_5day_return"], min_n=2)
    assert render_holding_period_line(curve) == ""


def test_finite_float_skips_nan_in_curve():
    recs = [
        {"next_5day_return": 5.0},
        {"next_5day_return": float("nan")},
        {"next_5day_return": "abc"},
        {"next_5day_return": None},
        {"next_5day_return": 3.0},
    ]
    curve = compute_holding_period_curve_from_loaded(recs, ["next_5day_return"], min_n=2)
    p5 = curve[0]
    assert p5.sample_count == 2  # 只 5.0 + 3.0 有效
    assert p5.avg_return == 4.0


# ---------------------------------------------------------------------------
# M10: 盈亏比 + 输家画像 — 服务 winrate>50% + 高盈亏比目标
# payoff ratio, avg_winner, avg_loser, profit factor, per-bucket 输家池
# ---------------------------------------------------------------------------

from src.screening.north_star_pnl import (  # noqa: E402
    PayoffAnalysisResult,
    compute_payoff_analysis_from_loaded,
    render_payoff_line,
)


def _p_recs(returns: list) -> list:
    return [{"recommended_date": "20250101", "recommendation_score": 0.35, "next_30day_return": r} for r in returns]


def test_payoff_computes_ratio_from_wins_and_losses():
    recs = _p_recs([10.0, -5.0, 20.0, -10.0])  # 2 wins (10,20) 2 losses (-5,-10)
    res = compute_payoff_analysis_from_loaded(recs, min_n=2)
    assert res.verdict == "ok"
    assert res.winrate == 0.5
    assert res.avg_winner == 15.0  # (10+20)/2
    assert res.avg_loser == -7.5  # (-5+-10)/2
    assert res.payoff_ratio == 2.0  # 15/7.5
    assert abs(res.expectancy - 3.75) < 0.1  # (10-5+20-10)/4


def test_payoff_no_losses_none_ratio():
    recs = _p_recs([10.0, 20.0, 5.0])
    res = compute_payoff_analysis_from_loaded(recs, min_n=2)
    assert res.avg_loser is None
    assert res.payoff_ratio is None  # 无输家


def test_payoff_insufficient_below_min_n():
    recs = _p_recs([10.0, -5.0])  # n=2 < min_n=5
    res = compute_payoff_analysis_from_loaded(recs, min_n=5)
    assert res.verdict == "insufficient"


def test_payoff_per_bucket_breakdown():
    """per-bucket winrate + expectancy (定位输家池)."""
    low = [{"recommended_date": "20250101", "recommendation_score": 0.10, "next_30day_return": 5.0} for _ in range(30)]
    mid_high = [{"recommended_date": "20250101", "recommendation_score": 0.45, "next_30day_return": -5.0} for _ in range(30)]
    recs = low + mid_high
    res = compute_payoff_analysis_from_loaded(recs, min_n=20)
    low_row = [b for b in res.per_bucket if b["bucket"] == "low"][0]
    assert low_row["winrate"] == 1.0
    mh_row = [b for b in res.per_bucket if b["bucket"] == "mid_high"][0]
    assert mh_row["winrate"] == 0.0


def test_render_payoff_line_shows_ratio():
    recs = _p_recs([10.0, -5.0, 20.0, -10.0, 5.0, -3.0])
    res = compute_payoff_analysis_from_loaded(recs, min_n=2)
    line = render_payoff_line(res)
    assert line
    assert "payoff" in line.lower() or "盈亏" in line
    assert "payoff" in line


def test_render_payoff_silent_when_insufficient():
    recs = _p_recs([10.0, -5.0])
    res = compute_payoff_analysis_from_loaded(recs, min_n=5)
    assert render_payoff_line(res) == ""


# ---------------------------------------------------------------------------
# M11: 砍输家池策略模拟 — 各 score 子集的 winrate/payoff/expectancy
# 服务 winrate>50%+高盈亏比: 量化"砍哪个 bucket"的效果 (owner 门控决策依据)
# ---------------------------------------------------------------------------

from src.screening.north_star_pnl import (  # noqa: E402
    compute_pruning_strategy_from_loaded,
    render_pruning_line,
)


def _pruning_recs(low_rets: list, high_rets: list) -> list:
    out = [{"recommended_date": "20250101", "recommendation_score": 0.10, "next_30day_return": r} for r in low_rets]
    out += [{"recommended_date": "20250101", "recommendation_score": 0.60, "next_30day_return": r} for r in high_rets]
    return out


def test_pruning_strategy_all_vs_subset():
    """low 全涨, high 全跌 → 砍 high 后 winrate 从 50% → 100%."""
    low = [5.0] * 10 + [-3.0] * 10  # winrate 50%
    high = [-4.0] * 20  # winrate 0%
    recs = _pruning_recs(low, high)
    result = compute_pruning_strategy_from_loaded(recs, min_n=5)
    assert "all" in result
    assert "drop_high" in result
    assert result["all"]["winrate"] == 0.25  # 10 win / 40 total
    assert result["drop_high"]["winrate"] == 0.5  # 10 win / 20 total (low only)


def test_pruning_strategy_expectancy_improves_when_dropping_losers():
    low = [10.0] * 8 + [-2.0] * 2  # exp high
    high = [-5.0] * 10  # exp negative
    recs = _pruning_recs(low, high)
    result = compute_pruning_strategy_from_loaded(recs, min_n=5)
    assert result["drop_high"]["expectancy"] > result["all"]["expectancy"]


def test_pruning_strategy_insufficient_sample():
    recs = _pruning_recs([5.0], [-3.0])  # n=2 < min_n=5
    result = compute_pruning_strategy_from_loaded(recs, min_n=5)
    assert result.get("all", {}).get("verdict") == "insufficient"


def test_render_pruning_line_shows_strategies():
    low = [10.0] * 8 + [-2.0] * 2
    high = [-5.0] * 10
    recs = _pruning_recs(low, high)
    result = compute_pruning_strategy_from_loaded(recs, min_n=5)
    line = render_pruning_line(result)
    assert line
    assert "winrate" in line.lower() or "胜率" in line


def test_render_pruning_silent_when_insufficient():
    recs = _pruning_recs([5.0], [-3.0])
    result = compute_pruning_strategy_from_loaded(recs, min_n=5)
    assert render_pruning_line(result) == ""


# ---------------------------------------------------------------------------
# M12: winrate bootstrap CI (percentile method) — 给 owner 门控决策提供稳健
# 不确定性估计. 服务 winrate>50% 路径: low bucket 50% (n=105) 的 95% CI 是
# [42%, 58%] (正态近似 ±9.6% 太宽). bootstrap percentile 免正态假设, 更稳健.
# 纯诊断, 不改 gate/factor; 幂等 (固定 seed); 单调 (lower <= upper).
# ---------------------------------------------------------------------------

from src.screening.north_star_pnl import (  # noqa: E402
    compute_bootstrap_ci_from_loaded,
    render_bootstrap_ci_line,
)


def _ci_recs(low_rets: list, high_rets: list) -> list:
    """{score: low|high} → tracking records (镜像 _pruning_recs)."""
    out = [{"recommended_date": "20250101", "recommendation_score": 0.10, "next_30day_return": r} for r in low_rets]
    out += [{"recommended_date": "20250101", "recommendation_score": 0.60, "next_30day_return": r} for r in high_rets]
    return out


def test_bootstrap_ci_computes_percentile_bounds():
    """给定 30 条 low records (winrate ~50%), bootstrap 应返回非 None 的 lower/upper."""
    recs = _ci_recs([5.0] * 15 + [-3.0] * 15, [])  # low only, winrate=50%, n=30
    result = compute_bootstrap_ci_from_loaded(recs, buckets=["low"], min_n=20, n_bootstrap=500, seed=42)
    assert len(result) == 1
    ci = result[0]
    assert ci.bucket == "low"
    assert ci.verdict == "ok"
    assert ci.point_estimate == 0.5  # 15/30
    assert ci.ci_lower is not None
    assert ci.ci_upper is not None


def test_bootstrap_ci_monotonic_lower_le_upper():
    """CI 边界单调: lower <= point_estimate <= upper (percentile method 保证)."""
    recs = _ci_recs([5.0] * 20 + [-3.0] * 10, [])  # winrate ~67%
    result = compute_bootstrap_ci_from_loaded(recs, buckets=["low"], min_n=20, n_bootstrap=500, seed=42)
    ci = result[0]
    assert ci.ci_lower <= ci.point_estimate <= ci.ci_upper


def test_bootstrap_ci_idempotent_same_seed():
    """同 seed + 同 input → 完全相同的 CI 输出 (幂等, 可复现)."""
    recs = _ci_recs([5.0] * 15 + [-3.0] * 15, [])
    r1 = compute_bootstrap_ci_from_loaded(recs, buckets=["low"], min_n=20, n_bootstrap=500, seed=42)
    r2 = compute_bootstrap_ci_from_loaded(recs, buckets=["low"], min_n=20, n_bootstrap=500, seed=42)
    assert r1[0].ci_lower == r2[0].ci_lower
    assert r1[0].ci_upper == r2[0].ci_upper


def test_bootstrap_ci_insufficient_below_min_n():
    """n < min_n → verdict='insufficient', ci_lower/ci_upper=None (诚实, 静默)."""
    recs = _ci_recs([5.0, -3.0], [])  # n=2 < min_n=20
    result = compute_bootstrap_ci_from_loaded(recs, buckets=["low"], min_n=20, n_bootstrap=500, seed=42)
    ci = result[0]
    assert ci.verdict == "insufficient"
    assert ci.ci_lower is None
    assert ci.ci_upper is None


def test_bootstrap_ci_per_bucket():
    """给定 low + high records, 默认返回所有非空 bucket 的 CI."""
    low = [5.0] * 15 + [-3.0] * 15  # n=30
    high = [5.0] * 10 + [-3.0] * 20  # n=30, winrate=33%
    recs = _ci_recs(low, high)
    result = compute_bootstrap_ci_from_loaded(recs, min_n=20, n_bootstrap=500, seed=42)
    buckets = {ci.bucket for ci in result}
    assert "low" in buckets
    assert "high" in buckets
    low_ci = next(ci for ci in result if ci.bucket == "low")
    high_ci = next(ci for ci in result if ci.bucket == "high")
    assert low_ci.point_estimate == 0.5  # 15/30
    assert high_ci.point_estimate == 0.3333333333333333  # 10/30


def test_bootstrap_ci_extreme_winrate_capped_at_1():
    """winrate=100% (全涨) → CI upper <= 1.0 (不超 100%, 逻辑边界)."""
    recs = _ci_recs([5.0] * 30, [])  # winrate=100%
    result = compute_bootstrap_ci_from_loaded(recs, buckets=["low"], min_n=20, n_bootstrap=500, seed=42)
    ci = result[0]
    assert ci.point_estimate == 1.0
    assert ci.ci_lower <= 1.0
    assert ci.ci_upper <= 1.0


def test_render_bootstrap_ci_line_shows_bounds():
    """渲染含 lower/upper + bucket label (服务 owner 决策可读性)."""
    recs = _ci_recs([5.0] * 15 + [-3.0] * 15, [])  # n=30, winrate=50%
    result = compute_bootstrap_ci_from_loaded(recs, buckets=["low"], min_n=20, n_bootstrap=500, seed=42)
    line = render_bootstrap_ci_line(result)
    assert line
    assert "low" in line.lower() or "低" in line
    assert "50" in line  # point estimate 50%
    assert "bootstrap" in line.lower()
    assert "95" in line  # ci_level=0.95


def test_render_bootstrap_ci_silent_when_insufficient():
    """全 bucket insufficient → 空串 (永不破坏前门, 同 M9/M10/M11 模式)."""
    recs = _ci_recs([5.0], [-3.0])  # n=2 < min_n=20
    result = compute_bootstrap_ci_from_loaded(recs, min_n=20, n_bootstrap=500, seed=42)
    assert render_bootstrap_ci_line(result) == ""


# ---------------------------------------------------------------------------
# C272 (2026-07-01): selection-profitability diagnostic.
# Backtest the MODEL's top-N-by-score selection vs alternatives (score_asc,
# equal_weight, random). First-principles: the 2026-06-30 empirical backtest
# (74 days, n=7993) showed score_desc portfolio T+5 winrate=47.3% (median
# -0.45%) vs random 58.1% / equal_weight 59.5% — the model's score has
# NEGATIVE predictive value for the front-door top-N selection. This makes
# the inversion measurable at the portfolio level (rank_monotonicity shows
# bucket-level; this shows selection-level) and tracks whether owner factor
# changes (MR flip) fix it.
# ---------------------------------------------------------------------------

from src.screening.north_star_pnl import (  # noqa: E402
    compute_selection_profitability_from_loaded,
    render_selection_profitability_line,
)


def _selection_recs(date_returns: dict[str, list[tuple[float, float]]]) -> list[dict]:
    """{date: [(score, t5_return), ...]} → flat record list."""
    out = []
    for dt, pairs in date_returns.items():
        for i, (score, ret) in enumerate(pairs):
            out.append({"recommended_date": dt, "recommendation_score": score, "next_5day_return": ret, "ticker": f"t{i}_{dt}"})
    return out


def test_selection_profitability_detects_model_underperforms():
    """C272: when the model's top-N-by-score loses vs random/equal-weight, the
    verdict must be ``model_underperforms``. Synthetic inversion: each day's
    high-score picks return -5%, low-score picks return +5%."""
    # 3 days × 6 picks. score_desc picks the 3 high-score (-5%) losers.
    pairs = [(0.80, -5.0), (0.70, -5.0), (0.60, -5.0), (0.20, 8.0), (0.15, 8.0), (0.10, 8.0)]
    recs = _selection_recs({f"2026010{d}": pairs for d in range(3)})
    report = compute_selection_profitability_from_loaded(recs, top_n=3, min_days=2)
    assert report.has_data
    assert report.verdict == "model_underperforms"
    sd = next(s for s in report.strategies if s.strategy == "score_desc")
    ew = next(s for s in report.strategies if s.strategy == "equal_weight_all")
    assert sd.median_return is not None and sd.median_return < 0  # top-3-by-score loses
    assert ew.median_return is not None and ew.median_return > 0  # equal-weight profits


def test_selection_profitability_detects_model_outperforms():
    """C272 positive guard: when high-score picks actually win more, verdict is
    ``model_outperforms`` (not a hardcoded 'always inverted' label)."""
    # high-score = +5%, low-score = -5% (model is correct)
    pairs = [(0.80, 5.0), (0.70, 5.0), (0.60, 5.0), (0.20, -5.0), (0.15, -5.0), (0.10, -5.0)]
    recs = _selection_recs({f"2026010{d}": pairs for d in range(3)})
    report = compute_selection_profitability_from_loaded(recs, top_n=3, min_days=2)
    assert report.verdict == "model_outperforms"


def test_selection_profitability_silent_when_insufficient():
    """Few days (< min_days) → has_data=False, render returns empty (never breaks front door)."""
    recs = _selection_recs({"20260101": [(0.8, 5.0), (0.2, -5.0)]})  # 1 day < min_days
    report = compute_selection_profitability_from_loaded(recs, top_n=3, min_days=2)
    assert not report.has_data
    assert render_selection_profitability_line(report) == ""


def test_render_selection_profitability_line_shows_inversion():
    """Render names the verdict + the model's portfolio winrate so the owner
    sees the selection-level profitability directly."""
    pairs = [(0.80, -5.0), (0.70, -5.0), (0.60, -5.0), (0.20, 8.0), (0.15, 8.0), (0.10, 8.0)]
    recs = _selection_recs({f"2026010{d}": pairs for d in range(4)})
    report = compute_selection_profitability_from_loaded(recs, top_n=3, min_days=2)
    line = render_selection_profitability_line(report)
    assert line
    assert "选取" in line or "selection" in line.lower()
    # must surface the model's portfolio winrate (the problematic number)
    assert "倒挂" in line or "跑输" in line or "负预测" in line
