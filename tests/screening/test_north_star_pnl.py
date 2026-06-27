"""NS-3 北极星 P&L 趋势仪表模块的合成数据测试.

不依赖真实报告文件 —— 全部用内联合成 tracking records. 验证:
  - 累积等权 mean T+30 P&L 计算
  - 整体 winrate + median (典型票, 免异常值污染)
  - mean/median 背离检测 (R-6/R-7: mean 被少数大赢家拉高但典型票微亏)
  - render 3 色态 (divergent⚠ / positive✓ / negative⚠) + insufficient 静默
"""
from __future__ import annotations

from src.screening.north_star_pnl import (
    compute_north_star_pnl_from_loaded,
    render_north_star_line,
)


def _records(date_returns: dict[str, list[float]]) -> list[dict]:
    """{date: [t30 returns]} → flat tracking record list."""
    out = []
    for dt, rets in date_returns.items():
        for r in rets:
            out.append({"recommended_date": dt, "next_30day_return": r})
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


def test_finite_float_rejects_nan_garbage():
    from src.screening.north_star_pnl import _finite_float

    assert _finite_float(None) is None
    assert _finite_float("abc") is None
    assert _finite_float(float("nan")) is None
    assert _finite_float("1.5") == 1.5


def test_handles_missing_and_garbage_returns():
    """缺 next_30day_return / NaN / 字符串 → 跳过, 不崩."""
    recs = [
        {"recommended_date": "20250101", "next_30day_return": 5.0},
        {"recommended_date": "20250101"},  # 缺
        {"recommended_date": "20250101", "next_30day_return": None},
        {"recommended_date": "20250101", "next_30day_return": float("nan")},
        {"recommended_date": "20250101", "next_30day_return": "abc"},
        {"recommended_date": "20250101", "next_30day_return": -2.0},
    ]
    rep = compute_north_star_pnl_from_loaded(recs, min_n=2)
    # 只 2 条有效 (5.0, -2.0) → n=2
    assert rep.sample_count == 2


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
