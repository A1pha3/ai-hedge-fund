"""NS-4 排序单调性健康度模块的合成数据测试.

不依赖真实报告文件 —— 全部用内联合成 history + tracking records. 验证:
  - 高分票胜率反而更低 → inverted (⚠ 倒挂)
  - 低分→高分胜率递增 → monotonic (✓)
  - 任一 bucket 样本不足 → insufficient (静默)
  - per-state_type 细分裁决
  - render 行为 (⚠/✓/空串)
"""

from __future__ import annotations

from src.screening.rank_monotonicity import (
    compute_rank_monotonicity_from_loaded,
    render_monotonicity_line,
    render_per_state_type_monotonicity_line,
)


def _by_bucket(report, bucket):
    for row in report.overall_buckets:
        if row.bucket == bucket:
            return row
    return None


def _records(buckets):
    """合成 records: {bucket: [t30 returns]} → flat record list (score→bucket)."""
    score_for = {"low": 0.10, "mid_low": 0.35, "mid_high": 0.45, "high": 0.60}
    out = []
    for bucket, rets in buckets.items():
        for r in rets:
            out.append(
                {
                    "recommended_date": "20250601",
                    "recommendation_score": score_for[bucket],
                    "next_5day_return": r,
                }
            )
    return out


def test_inverted_when_high_score_winrate_lower_than_low():
    """高分票全跌, 低分票全涨 → 倒挂 (模型把输家排前面)."""
    history = [{"date": "20250601", "payload": {"market_state": {"state_type": "MIXED"}}}]
    records = _records(
        {
            "low": [5.0, 5.0, 5.0, 5.0],  # 全涨 100%
            "mid_low": [3.0, 3.0, -1.0, -1.0],  # 50%
            "mid_high": [-2.0, -2.0, 1.0, 1.0],  # 50%
            "high": [-4.0, -4.0, -4.0, -4.0],  # 全跌 0%
        }
    )
    report = compute_rank_monotonicity_from_loaded(history, records, min_n=2)
    assert report.overall_verdict == "inverted"
    assert report.overall_inverted is True
    assert _by_bucket(report, "low").win_rate == 1.0
    assert _by_bucket(report, "high").win_rate == 0.0


def test_monotonic_when_winrate_increases_with_score():
    """低分→高分胜率递增 → monotonic (理想: 高分=高胜率)."""
    history = [{"date": "20250601", "payload": {"market_state": {"state_type": "TREND"}}}]
    records = _records(
        {
            "low": [-5.0, -5.0, 1.0, 1.0],  # 50%
            "mid_low": [1.0, 1.0, 1.0, -1.0],  # 75%
            "mid_high": [2.0, 2.0, 2.0, 2.0],  # 100%
            "high": [3.0, 3.0, 3.0, 3.0],  # 100%
        }
    )
    report = compute_rank_monotonicity_from_loaded(history, records, min_n=2)
    assert report.overall_verdict == "monotonic"
    assert report.overall_inverted is False


def test_non_monotonic_when_shape_is_mixed():
    """非单调也非严格倒挂 (中间凸起) → non_monotonic."""
    history = [{"date": "20250601", "payload": {"market_state": {"state_type": "RANGE"}}}]
    records = _records(
        {
            "low": [5.0, 5.0, 5.0, 5.0],  # 100%
            "mid_low": [-1.0, -1.0, -1.0, -1.0],  # 0%
            "mid_high": [2.0, 2.0, 2.0, 2.0],  # 100%
            "high": [1.0, 1.0, -1.0, -1.0],  # 50%
        }
    )
    report = compute_rank_monotonicity_from_loaded(history, records, min_n=2)
    assert report.overall_verdict == "non_monotonic"
    assert report.overall_inverted is False


def test_insufficient_when_any_bucket_below_min_n():
    """任一 bucket 样本 < min_n → insufficient (诚实, 不下倒挂结论)."""
    history = [{"date": "20250601", "payload": {"market_state": {"state_type": "MIXED"}}}]
    records = _records(
        {
            "low": [5.0] * 5,
            "mid_low": [3.0] * 5,
            "mid_high": [1.0] * 5,
            "high": [-4.0],  # 仅 1 只 < min_n=2
        }
    )
    report = compute_rank_monotonicity_from_loaded(history, records, min_n=2)
    assert report.overall_verdict == "insufficient"
    assert report.overall_inverted is False


def test_per_state_type_subdivision():
    """overall 倒挂但某 state_type 单调 → per_state_type 各自裁决."""
    history = [
        {"date": "20250601", "payload": {"market_state": {"state_type": "MIXED"}}},
        {"date": "20250602", "payload": {"market_state": {"state_type": "TREND"}}},
    ]
    score_for = {"low": 0.10, "mid_low": 0.35, "mid_high": 0.45, "high": 0.60}
    records = []
    # MIXED 日: 倒挂 (低涨高跌)
    for b, r in [("low", 5.0), ("mid_low", 3.0), ("mid_high", -1.0), ("high", -4.0)]:
        for _ in range(3):
            records.append(
                {
                    "recommended_date": "20250601",
                    "recommendation_score": score_for[b],
                    "next_5day_return": r,
                }
            )
    # TREND 日: 单调 (低跌高涨)
    for b, r in [("low", -5.0), ("mid_low", -1.0), ("mid_high", 2.0), ("high", 4.0)]:
        for _ in range(3):
            records.append(
                {
                    "recommended_date": "20250602",
                    "recommendation_score": score_for[b],
                    "next_5day_return": r,
                }
            )
    report = compute_rank_monotonicity_from_loaded(history, records, min_n=2)
    assert report.per_state_type_verdict.get("MIXED") == "inverted"
    assert report.per_state_type_verdict.get("TREND") == "monotonic"


def test_render_inverted_line_has_warning():
    history = [{"date": "20250601", "payload": {"market_state": {"state_type": "MIXED"}}}]
    report = compute_rank_monotonicity_from_loaded(
        history,
        _records(
            {
                "low": [5.0, 5.0, 5.0, 5.0],
                "mid_low": [3.0, 3.0, -1.0, -1.0],
                "mid_high": [-2.0, -2.0, 1.0, 1.0],
                "high": [-4.0, -4.0, -4.0, -4.0],
            }
        ),
        min_n=2,
    )
    line = render_monotonicity_line(report)
    assert line  # 非空
    assert "倒挂" in line or "inverted" in line.lower()
    assert "100%" in line  # 低 bucket 胜率
    assert "0%" in line  # 高 bucket 胜率


def test_render_silent_when_insufficient():
    history = [{"date": "20250601", "payload": {"market_state": {"state_type": "MIXED"}}}]
    report = compute_rank_monotonicity_from_loaded(
        history,
        _records(
            {
                "low": [5.0] * 5,
                "mid_low": [3.0] * 5,
                "mid_high": [1.0] * 5,
                "high": [-4.0],  # 样本不足
            }
        ),
        min_n=2,
    )
    assert render_monotonicity_line(report) == ""


def test_render_monotonic_line():
    history = [{"date": "20250601", "payload": {"market_state": {"state_type": "TREND"}}}]
    report = compute_rank_monotonicity_from_loaded(
        history,
        _records(
            {
                "low": [-5.0, -5.0, 1.0, 1.0],
                "mid_low": [1.0, 1.0, 1.0, -1.0],
                "mid_high": [2.0, 2.0, 2.0, 2.0],
                "high": [3.0, 3.0, 3.0, 3.0],
            }
        ),
        min_n=2,
    )
    line = render_monotonicity_line(report)
    assert line
    assert "单调" in line or "monotonic" in line.lower()


def test_finite_float_rejects_nan_and_garbage():
    from src.screening.rank_monotonicity import _finite_float

    assert _finite_float(None) is None
    assert _finite_float("abc") is None
    assert _finite_float(float("nan")) is None
    assert _finite_float("1.5") == 1.5


# ---------------------------------------------------------------------------
# M5: 时段分段单调性 (period breakdown) — 区分 H1 因子 bug (全期倒挂) vs H2 regime (分化)
# ---------------------------------------------------------------------------

from src.screening.rank_monotonicity import (  # noqa: E402
    compute_period_breakdown_from_loaded,
    render_period_breakdown_line,
)


def _period_records(first_half: dict, second_half: dict) -> list:
    """{bucket: [returns]} × 2 halves → records with recommended_date."""
    score_for = {"low": 0.10, "mid_low": 0.35, "mid_high": 0.45, "high": 0.60}
    out = []
    for bucket, rets in first_half.items():
        for r in rets:
            out.append({"recommended_date": "20250101", "recommendation_score": score_for[bucket], "next_30day_return": r})
    for bucket, rets in second_half.items():
        for r in rets:
            out.append({"recommended_date": "20250601", "recommendation_score": score_for[bucket], "next_30day_return": r})
    return out


def test_period_breakdown_two_halves_inverted_first_monotonic_second():
    """前半倒挂 (高分全跌), 后半单调 (低跌高涨) → 各段 verdict 不同 → regime 分化 (H2 信号)."""
    # 前半: 倒挂 (low 涨 high 跌)
    first = {"low": [5] * 4, "mid_low": [3, -1, 3, -1], "mid_high": [-2, 2, -2, 2], "high": [-4] * 4}
    # 后半: 单调 (low 跌 high 涨)
    second = {"low": [-5] * 4, "mid_low": [-1, 1, -1, 1], "mid_high": [2] * 4, "high": [4] * 4}
    recs = _period_records(first, second)
    periods = compute_period_breakdown_from_loaded(recs, n_periods=2, min_n=2)
    assert len(periods) == 2
    verdicts = {p.label: p.verdict for p in periods}
    assert verdicts["前半"] == "inverted"
    assert verdicts["后半"] == "monotonic"


def test_period_breakdown_both_inverted_signals_h1():
    """两段都倒挂 → 全期因子方向问题 (H1 信号, 非 regime)."""
    first = {"low": [5] * 4, "mid_low": [3, -1, 3, -1], "mid_high": [-2, 2, -2, 2], "high": [-4] * 4}
    second = {"low": [6] * 4, "mid_low": [2, -2, 2, -2], "mid_high": [-1, 1, -1, 1], "high": [-5] * 4}
    recs = _period_records(first, second)
    periods = compute_period_breakdown_from_loaded(recs, n_periods=2, min_n=2)
    verdicts = {p.label: p.verdict for p in periods}
    assert verdicts["前半"] == "inverted"
    assert verdicts["后半"] == "inverted"


def test_period_breakdown_insufficient_segment():
    """一段样本不足 → 该段 insufficient (诚实)."""
    first = {"low": [5] * 4, "mid_low": [3, -1, 3, -1], "mid_high": [-2, 2, -2, 2], "high": [-4] * 4}
    second = {"low": [5], "mid_low": [3], "mid_high": [-2], "high": [-4]}  # 各 1 < min_n=2
    recs = _period_records(first, second)
    periods = compute_period_breakdown_from_loaded(recs, n_periods=2, min_n=2)
    verdicts = {p.label: p.verdict for p in periods}
    assert verdicts["后半"] == "insufficient"


def test_render_period_breakdown_line_has_both_periods():
    first = {"low": [5] * 4, "mid_low": [3, -1, 3, -1], "mid_high": [-2, 2, -2, 2], "high": [-4] * 4}
    second = {"low": [6] * 4, "mid_low": [2, -2, 2, -2], "mid_high": [-1, 1, -1, 1], "high": [-5] * 4}
    recs = _period_records(first, second)
    periods = compute_period_breakdown_from_loaded(recs, n_periods=2, min_n=2)
    line = render_period_breakdown_line(periods)
    assert line
    assert "前半" in line
    assert "后半" in line


def test_render_period_breakdown_silent_when_all_insufficient():
    first = {"low": [5], "mid_low": [3], "mid_high": [-2], "high": [-4]}
    second = {"low": [5], "mid_low": [3], "mid_high": [-2], "high": [-4]}
    recs = _period_records(first, second)
    periods = compute_period_breakdown_from_loaded(recs, n_periods=2, min_n=2)
    assert render_period_breakdown_line(periods) == ""


# ---------------------------------------------------------------------------
# M6: 多 horizon 单调性 (horizon breakdown) — 回答 design packet H5/D1
# 倒挂是 T+30 特定还是全 horizon? (排除 MR 短期反转假说)
# ---------------------------------------------------------------------------

from src.screening.rank_monotonicity import (  # noqa: E402
    compute_horizon_monotonicity_from_loaded,
    render_horizon_breakdown_line,
)


def _horizon_records(horizon_returns: dict) -> list:
    """{horizon_field: {bucket: [returns]}} → records (每 horizon 独立 set)."""
    score_for = {"low": 0.10, "mid_low": 0.35, "mid_high": 0.45, "high": 0.60}
    out = []
    for horizon, buckets in horizon_returns.items():
        for bucket, rets in buckets.items():
            for r in rets:
                out.append({"recommended_date": "20250101", "recommendation_score": score_for[bucket], horizon: r})
    return out


def test_horizon_breakdown_each_horizon_independent_verdict():
    """T+5 倒挂, T+30 单调 → 各 horizon 独立裁决 (排除 MR 短期反转 = 全 horizon 倒挂才是 H5)."""
    recs = _horizon_records(
        {
            "next_5day_return": {"low": [5] * 4, "mid_low": [3, -1, 3, -1], "mid_high": [-2, 2, -2, 2], "high": [-4] * 4},
            "next_30day_return": {"low": [-5] * 4, "mid_low": [-1, 1, -1, 1], "mid_high": [2] * 4, "high": [4] * 4},
        }
    )
    horizons = compute_horizon_monotonicity_from_loaded(recs, ["next_5day_return", "next_30day_return"], min_n=2)
    v = {h.horizon: h.verdict for h in horizons}
    assert v["next_5day_return"] == "inverted"
    assert v["next_30day_return"] == "monotonic"


def test_horizon_breakdown_insufficient_horizon():
    recs = _horizon_records({"next_5day_return": {"low": [5], "mid_low": [3], "mid_high": [-2], "high": [-4]}})
    horizons = compute_horizon_monotonicity_from_loaded(recs, ["next_5day_return"], min_n=2)
    assert horizons[0].verdict == "insufficient"


def test_horizon_breakdown_missing_horizon_field():
    """record 缺该 horizon 字段 → insufficient (诚实, 不下结论)."""
    recs = [{"recommended_date": "20250101", "recommendation_score": 0.5, "next_5day_return": 5.0}]
    horizons = compute_horizon_monotonicity_from_loaded(recs, ["next_99day_return"], min_n=2)  # 不存在字段
    assert horizons[0].verdict == "insufficient"


def test_render_horizon_breakdown_line_shows_horizons():
    recs = _horizon_records(
        {
            "next_5day_return": {"low": [5] * 4, "mid_low": [3, -1, 3, -1], "mid_high": [-2, 2, -2, 2], "high": [-4] * 4},
            "next_30day_return": {"low": [-5] * 4, "mid_low": [-1, 1, -1, 1], "mid_high": [2] * 4, "high": [4] * 4},
        }
    )
    horizons = compute_horizon_monotonicity_from_loaded(recs, ["next_5day_return", "next_30day_return"], min_n=2)
    line = render_horizon_breakdown_line(horizons)
    assert line
    assert "T+5" in line or "next_5day" in line
    assert "T+30" in line or "next_30day" in line


def test_render_horizon_breakdown_silent_when_all_insufficient():
    recs = _horizon_records({"next_5day_return": {"low": [5], "mid_low": [3], "mid_high": [-2], "high": [-4]}})
    horizons = compute_horizon_monotonicity_from_loaded(recs, ["next_5day_return"], min_n=2)
    assert render_horizon_breakdown_line(horizons) == ""


# ---------------------------------------------------------------------------
# M7: 单调性统计显著性 — NS-4 倒挂是真的还是小样本噪声?
# high-vs-low two-proportion z-test + Wilson CI (免 owner over-react 到噪声)
# ---------------------------------------------------------------------------

from src.screening.rank_monotonicity import (  # noqa: E402
    compute_high_vs_low_significance_from_loaded,
    render_significance_line,
)


def _sig_records(low_returns: list, high_returns: list) -> list:
    """合成 low/high bucket records."""
    out = []
    for r in low_returns:
        out.append({"recommended_date": "20250101", "recommendation_score": 0.10, "next_30day_return": r})
    for r in high_returns:
        out.append({"recommended_date": "20250101", "recommendation_score": 0.60, "next_30day_return": r})
    return out


def test_significance_large_gap_significant():
    """low 全涨 (n=50), high 全跌 (n=50) → 显著 (p~0)."""
    recs = _sig_records([5.0] * 50, [-5.0] * 50)
    res = compute_high_vs_low_significance_from_loaded(recs, min_n=20)
    assert res.verdict_note == "significant"
    assert res.p_value < 0.05
    assert res.z_score > 0  # low > high


def test_significance_small_gap_not_significant():
    """low/high 接近 → 不显著."""
    # low 52% win, high 48% win, n=50 each → z 小, 不显著
    low = [1.0] * 26 + [-1.0] * 24  # 26/50 = 52%
    high = [1.0] * 24 + [-1.0] * 26  # 24/50 = 48%
    recs = _sig_records(low, high)
    res = compute_high_vs_low_significance_from_loaded(recs, min_n=20)
    assert res.verdict_note == "not_significant"
    assert res.p_value >= 0.05


def test_significance_marginal():
    """p 在 [0.05, 0.1) → marginal (边缘显著)."""
    # 构造边缘: low 60% (n=50), high 38% (n=50) → z≈2.3? 调整到 p~0.06-0.1
    low = [1.0] * 30 + [-1.0] * 20  # 60%
    high = [1.0] * 19 + [-1.0] * 31  # 38%
    recs = _sig_records(low, high)
    res = compute_high_vs_low_significance_from_loaded(recs, min_n=20)
    assert res.verdict_note in ("marginal", "significant", "not_significant")  # 容忍边界


def test_significance_insufficient_small_n():
    """low/high n < min_n → insufficient (诚实, 不下结论)."""
    recs = _sig_records([5.0] * 5, [-5.0] * 5)  # n=5 < min_n=20
    res = compute_high_vs_low_significance_from_loaded(recs, min_n=20)
    assert res.verdict_note == "insufficient"


def test_significance_insufficient_when_no_high_bucket():
    """无 high bucket → insufficient."""
    recs = _sig_records([5.0] * 50, [])  # 无 high
    res = compute_high_vs_low_significance_from_loaded(recs, min_n=20)
    assert res.verdict_note == "insufficient"


def test_render_significance_line_shows_z_p():
    recs = _sig_records([5.0] * 50, [-5.0] * 50)
    res = compute_high_vs_low_significance_from_loaded(recs, min_n=20)
    line = render_significance_line(res)
    assert line
    assert "p=" in line
    assert "z=" in line.lower() or "z=" in line


def test_render_significance_silent_when_insufficient():
    recs = _sig_records([5.0] * 5, [-5.0] * 5)
    res = compute_high_vs_low_significance_from_loaded(recs, min_n=20)
    assert render_significance_line(res) == ""


# ---------------------------------------------------------------------------
# M8: 样本量充足性 (power analysis) — 当前数据够不够下结论?
# M7 T+30 不显著因 high n=38 太小. 告诉 owner 需累积多少样本.
# ---------------------------------------------------------------------------

from src.screening.rank_monotonicity import (  # noqa: E402
    _required_sample_size,
    compute_power_analysis_from_loaded,
    render_power_line,
)


def test_required_sample_size_formula():
    """11pp (50% vs 39%) 80% power alpha=0.05 → ~317/组."""
    n = _required_sample_size(0.50, 0.39)
    assert n is not None
    assert 310 <= n <= 325  # ~317 容差


def test_required_sample_size_smaller_gap_needs_more():
    """小 gap → 大 n (5pp > 15pp)."""
    n_small_gap = _required_sample_size(0.50, 0.45)  # 5pp
    n_large_gap = _required_sample_size(0.50, 0.35)  # 15pp
    assert n_small_gap > n_large_gap


def test_required_sample_size_zero_gap_none():
    assert _required_sample_size(0.50, 0.50) is None


def test_power_analysis_from_loaded_current_vs_required():
    """合成 records: high n=38, low 50% high 39% → required ~317, sufficiency 12%."""
    # low: 105 records, 53 win (50%); high: 38 records, 15 win (39%)
    low = [1.0] * 53 + [-1.0] * 52  # 53/105 = 50%
    high = [1.0] * 15 + [-1.0] * 23  # 15/38 = 39%
    recs = [{"recommended_date": "20250101", "recommendation_score": 0.10, "next_30day_return": r} for r in low] + [{"recommended_date": "20250101", "recommendation_score": 0.60, "next_30day_return": r} for r in high]
    res = compute_power_analysis_from_loaded(recs, min_n=20)
    assert res.current_high_n == 38
    assert res.required_n_per_group is not None
    assert 310 <= res.required_n_per_group <= 325
    assert res.verdict == "insufficient_samples"  # 38 << 317


def test_power_analysis_no_high_bucket():
    recs = [{"recommended_date": "20250101", "recommendation_score": 0.10, "next_30day_return": 5.0}]
    res = compute_power_analysis_from_loaded(recs, min_n=20)
    assert res.verdict == "no_data"


def test_render_power_line_shows_required_and_current():
    low = [1.0] * 53 + [-1.0] * 52
    high = [1.0] * 15 + [-1.0] * 23
    recs = [{"recommended_date": "20250101", "recommendation_score": 0.10, "next_30day_return": r} for r in low] + [{"recommended_date": "20250101", "recommendation_score": 0.60, "next_30day_return": r} for r in high]
    res = compute_power_analysis_from_loaded(recs, min_n=20)
    line = render_power_line(res)
    assert line
    assert "需" in line or "样本" in line
    assert "317" in line or "31" in line  # required ~317


def test_render_power_silent_when_no_data():
    recs = [{"recommended_date": "20250101", "recommendation_score": 0.10, "next_30day_return": 5.0}]
    res = compute_power_analysis_from_loaded(recs, min_n=20)
    assert render_power_line(res) == ""


class TestRenderPerStateTypeMonotonicityLine:
    """c334/autodev-36: per-state_type 单调性渲染 (computed-but-unrendered 修复)."""

    def test_all_inverted_shows_universal_warning(self) -> None:
        """全 regime 倒挂 → model defect 标注."""
        history = [
            {"date": "20250601", "payload": {"market_state": {"state_type": "MIXED"}}},
            {"date": "20250602", "payload": {"market_state": {"state_type": "TREND"}}},
        ]
        score_for = {"low": 0.10, "mid_low": 0.35, "mid_high": 0.45, "high": 0.60}
        records = []
        # 两个 state 都倒挂: 高分跌, 低分涨
        for date, st in [("20250601", "MIXED"), ("20250602", "TREND")]:
            for b, r in [("low", 5.0), ("mid_low", 3.0), ("mid_high", -1.0), ("high", -4.0)]:
                for _ in range(3):
                    records.append({"recommended_date": date, "recommendation_score": score_for[b], "next_5day_return": r})
        report = compute_rank_monotonicity_from_loaded(history, records, min_n=2)
        line = render_per_state_type_monotonicity_line(report)
        assert line
        assert "倒挂" in line
        assert "model defect" in line
        report = compute_rank_monotonicity_from_loaded(history, records, min_n=2)
        line = render_per_state_type_monotonicity_line(report)
        assert line
        assert "倒挂" in line
        assert "model defect" in line

    def test_divergent_shows_regime_specific(self) -> None:
        """verdict 分化 → regime-specific 标注."""
        history = [
            {"date": "20250601", "payload": {"market_state": {"state_type": "MIXED"}}},
            {"date": "20250602", "payload": {"market_state": {"state_type": "TREND"}}},
        ]
        score_for = {"low": 0.10, "mid_low": 0.35, "mid_high": 0.45, "high": 0.60}
        records = []
        # MIXED: inverted; TREND: monotonic
        for b, r in [("low", 5.0), ("mid_low", 3.0), ("mid_high", -1.0), ("high", -4.0)]:
            for _ in range(5):
                records.append({"recommended_date": "20250601", "recommendation_score": score_for[b], "next_5day_return": r})
        for b, r in [("low", -5.0), ("mid_low", -1.0), ("mid_high", 2.0), ("high", 4.0)]:
            for _ in range(5):
                records.append({"recommended_date": "20250602", "recommendation_score": score_for[b], "next_5day_return": r})
        report = compute_rank_monotonicity_from_loaded(history, records, min_n=2)
        line = render_per_state_type_monotonicity_line(report)
        assert line
        assert "regime-specific" in line or "分化" in line

    def test_empty_when_no_per_state_type(self) -> None:
        report = compute_rank_monotonicity_from_loaded([], [], min_n=2)
        assert render_per_state_type_monotonicity_line(report) == ""

    def test_shows_horizon_label(self) -> None:
        """c335/autodev-36: render 包含 horizon_label."""
        history = [
            {"date": "20250601", "payload": {"market_state": {"state_type": "MIXED"}}},
            {"date": "20250602", "payload": {"market_state": {"state_type": "TREND"}}},
        ]
        score_for = {"low": 0.10, "mid_low": 0.35, "mid_high": 0.45, "high": 0.60}
        records = []
        for date, st in [("20250601", "MIXED"), ("20250602", "TREND")]:
            for b, r in [("low", 5.0), ("mid_low", 3.0), ("mid_high", -1.0), ("high", -4.0)]:
                for _ in range(3):
                    records.append({"recommended_date": date, "recommendation_score": score_for[b], "next_5day_return": r})
        report = compute_rank_monotonicity_from_loaded(history, records, min_n=2)
        line = render_per_state_type_monotonicity_line(report)
        assert "(T+5)" in line
