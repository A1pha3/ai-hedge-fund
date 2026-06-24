"""测试 src.screening.confidence_calibration (P0-9)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.screening.confidence_calibration import (
    _find_bucket,
    CalibrationSummary,
    compute_calibration,
    DEFAULT_LOOKBACK_DAYS,
    render_calibration_table,
    render_top_n_calibration,
    SCORE_BUCKETS,
    ScoreBucketStats,
)

# ---------------------------------------------------------------------------
# _find_bucket
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,expected_label_contains",
    [
        (0.95, "高"),
        (0.80, "高"),  # 边界 0.8 落入"高"桶 (左闭)
        (0.79, "中高"),
        (0.75, "中高"),
        (0.70, "中高"),  # 边界 0.7 落入"中高" (左闭)
        (0.65, "中"),
        (0.55, "中低"),
        (0.50, "中低"),  # 边界 0.5 落入"中低" (左闭)
        (0.45, "低"),
        (0.10, "低"),
    ],
)
def test_find_bucket(score, expected_label_contains):
    result = _find_bucket(score)
    assert result is not None
    assert expected_label_contains in result[0]


def test_find_bucket_extreme_low():
    """score=-1.0 应落入"低"桶 (低边界 -1.01)。"""
    result = _find_bucket(-1.0)
    assert result is not None
    assert "低" in result[0]


def test_find_bucket_invalid_returns_none():
    """桶定义范围之外的极端值 — 理论上不会出现, 但应安全处理。"""
    # 我们的桶覆盖 -1.01 到 1.01, 所以 1.5 应找不到
    # 但实际 score_b 范围 -1 到 +1, 所以这是防御性测试
    result = _find_bucket(1.5)
    assert result is None


# ---------------------------------------------------------------------------
# compute_calibration
# ---------------------------------------------------------------------------


def _make_record(ticker: str, score: float, t1: float | None = None, t3: float | None = None, t5: float | None = None, date: str = "20260601") -> dict:
    return {
        "ticker": ticker,
        "recommended_date": date,
        "recommendation_score": score,
        "next_day_return": t1,
        "next_3day_return": t3,
        "next_5day_return": t5,
    }


def test_compute_calibration_empty_records():
    summary = compute_calibration([])
    assert summary.total_samples == 0
    assert summary.overall_t1_win_rate is None
    assert all(b.sample_count == 0 for b in summary.buckets)


def test_compute_calibration_single_bucket_all_winners():
    """4 只票都在 0.7-0.8 桶, 全部 T+5 正收益 → 100% 胜率。"""
    records = [
        _make_record("000001", 0.75, t1=1.0, t3=2.0, t5=3.0),
        _make_record("000002", 0.72, t1=0.5, t3=1.5, t5=2.5),
        _make_record("000003", 0.78, t1=-0.5, t3=1.0, t5=1.8),
        _make_record("000004", 0.71, t1=2.0, t3=3.0, t5=4.0),
    ]
    summary = compute_calibration(records)
    bucket = next(b for b in summary.buckets if "中高" in b.label)
    assert bucket.sample_count == 4
    assert bucket.t5_win_rate == 1.0  # 全部 T+5 正收益
    assert bucket.t1_win_rate == pytest.approx(0.75, abs=1e-3)  # 3/4 T+1 正
    assert bucket.t5_avg_return == pytest.approx(2.825, abs=1e-3)


def test_compute_calibration_multiple_buckets():
    """跨桶验证分桶正确性。"""
    records = [
        _make_record("000001", 0.85, t5=2.0),  # 高桶
        _make_record("000002", 0.65, t5=-1.0),  # 中桶
        _make_record("000003", 0.45, t5=0.5),  # 低桶
    ]
    summary = compute_calibration(records)
    high = next(b for b in summary.buckets if "高" in b.label)
    mid = next(b for b in summary.buckets if b.label.startswith("中 ("))
    low = next(b for b in summary.buckets if b.label.startswith("低"))
    assert high.sample_count == 1
    assert mid.sample_count == 1
    assert low.sample_count == 1
    assert summary.total_samples == 3


def test_compute_calibration_lookback_filter():
    """lookback_days 应限制样本到最近 N 个不同日期。"""
    records = [
        _make_record("000001", 0.75, t5=1.0, date="20260601"),
        _make_record("000002", 0.75, t5=1.0, date="20260602"),
        _make_record("000003", 0.75, t5=1.0, date="20260603"),
        _make_record("000004", 0.75, t5=1.0, date="20260604"),
    ]
    # lookback=2 只保留最近 2 天 (20260603, 20260604)
    summary = compute_calibration(records, lookback_days=2)
    assert summary.total_samples == 2


def test_compute_calibration_lookback_zero_means_all():
    """lookback_days=0 表示不限制 (取全部日期)。"""
    records = [
        _make_record("000001", 0.75, t5=1.0, date="20260601"),
        _make_record("000002", 0.75, t5=1.0, date="20260610"),
    ]
    summary = compute_calibration(records, lookback_days=0)
    assert summary.total_samples == 2


def test_compute_calibration_none_returns_excluded():
    """None T+5 收益应排除出统计 (不计入 sample_count 的 win_rate 分母)。"""
    records = [
        _make_record("000001", 0.75, t5=2.0),
        _make_record("000002", 0.75, t5=None),  # 无 T+5 数据
        _make_record("000003", 0.75, t5=-1.0),
    ]
    summary = compute_calibration(records)
    bucket = next(b for b in summary.buckets if "中高" in b.label)
    assert bucket.sample_count == 3  # 总记录数包含无 T+5 的
    assert bucket.t5_win_rate == pytest.approx(0.5, abs=1e-3)  # 1/2 有 T+5 数据的中 1 个赢


def test_compute_calibration_t30_avg_negative_return_only_losers():
    """O-4: t30_avg_negative_return = mean of LOSING T+30 returns only (赔率 /
    typical downside). Positive/zero returns excluded so the user sees how much a
    typical loss costs, distinct from the overall avg_return (which winners pull
    up). 60% win @ -4% typical loss ≠ 60% @ -30%."""
    records = [
        _make_record_full("000001", 0.75, t30=0.08),   # winner — excluded from downside
        _make_record_full("000002", 0.75, t30=-0.04),  # loser
        _make_record_full("000003", 0.75, t30=-0.12),  # loser
    ]
    summary = compute_calibration(records)
    bucket = next(b for b in summary.buckets if "中高" in b.label)
    # mean of losers only: (-0.04 + -0.12) / 2 = -0.08
    assert bucket.t30_avg_negative_return == pytest.approx(-0.08)
    # overall avg includes the winner: (0.08 - 0.04 - 0.12) / 3
    assert bucket.t30_avg_return == pytest.approx((0.08 - 0.04 - 0.12) / 3)


def test_compute_calibration_t30_avg_negative_return_none_when_no_losers():
    """O-4: when every T+30 return is a winner, the bucket has no observed
    downside → None (distinct from 0.0)."""
    records = [
        _make_record_full("000001", 0.75, t30=0.05),
        _make_record_full("000002", 0.75, t30=0.08),
    ]
    summary = compute_calibration(records)
    bucket = next(b for b in summary.buckets if "中高" in b.label)
    assert bucket.t30_avg_negative_return is None
    assert bucket.t30_avg_return == pytest.approx(0.065)


def test_compute_calibration_score_missing_record_excluded():
    """缺 recommendation_score 的记录应被排除。"""
    records = [
        {"ticker": "000001", "recommended_date": "20260601", "next_5day_return": 1.0},  # 无 score
        _make_record("000002", 0.75, t5=1.0),
    ]
    summary = compute_calibration(records)
    assert summary.total_samples == 1  # 只计有 score 的


def test_compute_calibration_overall_stats():
    """整体统计应跨桶聚合。"""
    records = [
        _make_record("000001", 0.85, t5=2.0),  # 高桶 +赢
        _make_record("000002", 0.45, t5=-1.0),  # 低桶 -输
    ]
    summary = compute_calibration(records)
    assert summary.overall_t5_win_rate == pytest.approx(0.5, abs=1e-3)
    assert summary.overall_t5_avg_return == pytest.approx(0.5, abs=1e-3)


def _make_record_full(
    ticker: str,
    score: float,
    t1: float | None = None,
    t3: float | None = None,
    t5: float | None = None,
    t10: float | None = None,
    t20: float | None = None,
    t30: float | None = None,
    date: str = "20260601",
) -> dict:
    """Record builder supporting all horizons (for BH-002 maturity tests)."""
    rec = _make_record(ticker, score, t1=t1, t3=t3, t5=t5, date=date)
    rec["next_10day_return"] = t10
    rec["next_20day_return"] = t20
    rec["next_30day_return"] = t30
    return rec


def test_compute_calibration_matured_sample_counts_track_per_horizon_realized():
    """BH-002: per-horizon matured sample counts must equal the number of
    records that actually have a realized return at that horizon, not the
    all-records ``sample_count``.

    A freshly-recommended pick has no T+30 return yet; it must NOT inflate the
    T+30 backing-sample denominator displayed next to the 30-day edge.
    """
    records = [
        # 3 picks in 中高 bucket; only 1 has matured to T+30.
        _make_record_full("000001", 0.75, t1=1.0, t5=2.0, t10=3.0, t20=4.0, t30=5.0),
        _make_record_full("000002", 0.72, t1=0.5, t5=1.5, t10=None, t20=None, t30=None),  # immature at T+10+
        _make_record_full("000003", 0.78, t1=-0.5, t5=None, t10=None, t20=None, t30=None),  # immature at T+5+
    ]
    summary = compute_calibration(records)
    bucket = next(b for b in summary.buckets if "中高" in b.label)

    # sample_count counts every record (the denominator that previously
    # mislabeled T+30 stats).
    assert bucket.sample_count == 3
    # Matured counts must reflect realized returns per horizon.
    assert bucket.t1_sample_count == 3   # all 3 have T+1
    assert bucket.t5_sample_count == 2   # 000001 + 000002
    assert bucket.t10_sample_count == 1  # only 000001
    assert bucket.t20_sample_count == 1  # only 000001
    assert bucket.t30_sample_count == 1  # only 000001 — the crux of BH-002


def test_compute_calibration_total_matured_samples_aggregate_across_buckets():
    """BH-002: ``CalibrationSummary.total_t30_samples`` aggregates matured
    T+30 counts across all buckets, so a 30-day-edge header can be attributed
    to its true denominator instead of ``total_samples`` (all records)."""
    records = [
        _make_record_full("000001", 0.85, t30=5.0),   # 高 bucket, mature T+30
        _make_record_full("000002", 0.82, t30=None),  # 高 bucket, immature
        _make_record_full("000003", 0.45, t30=-2.0),  # 低 bucket, mature T+30
        _make_record_full("000004", 0.42, t30=None),  # 低 bucket, immature
    ]
    summary = compute_calibration(records)
    assert summary.total_samples == 4          # all records
    assert summary.total_t30_samples == 2      # only 000001 + 000003 matured
    assert summary.total_t20_samples == 0      # none have T+20
    assert summary.total_t5_samples == 0       # none have T+5


# ---------------------------------------------------------------------------
# render_calibration_table
# ---------------------------------------------------------------------------


def test_render_calibration_table_empty():
    summary = compute_calibration([])
    out = render_calibration_table(summary)
    assert "置信度校准" in out
    assert "无历史推荐追踪数据" in out


def test_render_calibration_table_with_data():
    records = [
        _make_extended_record("000001", 0.85, t1=1.0, t5=2.0, t10=3.0, t20=4.0, t30=5.0),
        _make_extended_record("000002", 0.65, t1=-0.5, t5=-1.0, t10=-2.0, t20=-3.0, t30=-4.0),
    ]
    summary = compute_calibration(records)
    out = render_calibration_table(summary)
    assert "Score 桶" in out
    assert "T+5 胜率" in out
    assert "T+10 胜率" in out
    assert "T+20 胜率" in out
    assert "T+30 胜率" in out
    assert "T+10 均收" in out
    assert "T+20 均收" in out
    assert "T+30 均收" in out
    assert "整体" in out


# ---------------------------------------------------------------------------
# render_top_n_calibration
# ---------------------------------------------------------------------------


def test_render_top_n_calibration_empty_recs():
    summary = compute_calibration([])
    out = render_top_n_calibration([], summary, top_n=5)
    assert out == ""  # 无推荐返回空


def test_render_top_n_calibration_with_bucket_match():
    records = [_make_extended_record("000099", 0.85, t5=2.0, t10=3.0, t20=4.0, t30=5.0)]
    summary = compute_calibration(records)
    top_recs = [
        {"ticker": "000001", "name": "测试票A", "score_b": 0.85},
    ]
    out = render_top_n_calibration(top_recs, summary, top_n=5)
    assert "Top 1 推荐校准" in out
    assert "000001" in out
    assert "高" in out  # 0.85 落入高桶
    assert "T+10 胜率" in out
    assert "T+20 胜率" in out
    assert "T+30 胜率" in out


def test_render_top_n_calibration_no_sample_bucket():
    """推荐落入一个无历史样本的桶, 应显示"无样本, 不可校准"。"""
    summary = compute_calibration([])  # 无任何历史
    top_recs = [
        {"ticker": "000001", "name": "测试票", "score_b": 0.75},
    ]
    out = render_top_n_calibration(top_recs, summary, top_n=5)
    assert "无样本, 不可校准" in out


def test_render_top_n_calibration_respects_top_n_limit():
    records = [_make_record("000099", 0.85, t5=2.0)]
    summary = compute_calibration(records)
    top_recs = [
        {"ticker": f"{i:06d}", "name": f"票{i}", "score_b": 0.85} for i in range(5)
    ]
    out = render_top_n_calibration(top_recs, summary, top_n=2)
    assert "Top 2 推荐校准" in out


# ---------------------------------------------------------------------------
# Extended horizons (T+10/T+20/T+30) - P5-1
# ---------------------------------------------------------------------------


def _make_extended_record(
    ticker: str, score: float, 
    t1: float | None = None, t3: float | None = None, t5: float | None = None,
    t10: float | None = None, t20: float | None = None, t30: float | None = None,
    date: str = "20260601"
) -> dict:
    """Create tracking record with extended horizons."""
    return {
        "ticker": ticker,
        "recommended_date": date,
        "recommendation_score": score,
        "next_day_return": t1,
        "next_3day_return": t3,
        "next_5day_return": t5,
        "next_10day_return": t10,
        "next_20day_return": t20,
        "next_30day_return": t30,
    }


def test_compute_calibration_with_extended_horizons():
    """Calibration should compute T+10/T+20/T+30 stats alongside existing T+1/T+3/T+5."""
    records = [
        _make_extended_record("000001", 0.75, t1=1.0, t5=3.0, t10=5.0, t20=8.0, t30=10.0),
        _make_extended_record("000002", 0.72, t1=0.5, t5=2.5, t10=4.0, t20=-2.0, t30=1.0),
        _make_extended_record("000003", 0.78, t1=-0.5, t5=1.8, t10=-1.0, t20=3.0, t30=-2.0),
    ]
    summary = compute_calibration(records)
    bucket = next(b for b in summary.buckets if "中高" in b.label)
    
    # Should have extended horizon stats
    assert bucket.sample_count == 3
    assert hasattr(bucket, 't10_win_rate')
    assert hasattr(bucket, 't20_win_rate')
    assert hasattr(bucket, 't30_win_rate')
    assert hasattr(bucket, 't10_avg_return')
    assert hasattr(bucket, 't20_avg_return')
    assert hasattr(bucket, 't30_avg_return')
    
    # T+10: 2/3 positive
    assert bucket.t10_win_rate == pytest.approx(2/3, abs=1e-3)
    # T+20: 2/3 positive
    assert bucket.t20_win_rate == pytest.approx(2/3, abs=1e-3)
    # T+30: 2/3 positive
    assert bucket.t30_win_rate == pytest.approx(2/3, abs=1e-3)


def test_calibration_summary_has_extended_overall_stats():
    """Overall summary should include T+10/T+20/T+30 aggregate stats."""
    records = [
        _make_extended_record("000001", 0.85, t10=5.0, t20=8.0, t30=10.0),
        _make_extended_record("000002", 0.45, t10=-2.0, t20=-3.0, t30=-1.0),
    ]
    summary = compute_calibration(records)
    
    assert hasattr(summary, 'overall_t10_win_rate')
    assert hasattr(summary, 'overall_t20_win_rate')
    assert hasattr(summary, 'overall_t30_win_rate')
    assert hasattr(summary, 'overall_t10_avg_return')
    assert hasattr(summary, 'overall_t20_avg_return')
    assert hasattr(summary, 'overall_t30_avg_return')
    
    # 1 win / 1 loss = 50%
    assert summary.overall_t10_win_rate == pytest.approx(0.5, abs=1e-3)
    assert summary.overall_t20_win_rate == pytest.approx(0.5, abs=1e-3)
    assert summary.overall_t30_win_rate == pytest.approx(0.5, abs=1e-3)


# ---------------------------------------------------------------------------
# P-2: T+30 standard deviation (outcome dispersion → 预测置信区间)
# ---------------------------------------------------------------------------


class TestStdAndT30StdReturn:
    """P-2: calibration must expose T+30 return standard deviation so the front
    door can show outcome dispersion (±std), not just the point-estimate mean.

    产品目标 "更高确信" 此前只给点估计 "+3.2%" — 用户无法判断该估计的离散度。
    +3.2% (±1.5%, n=45) vs +3.2% (±8%, n=45) 是完全不同的置信度。"""

    def test_std_or_none_sample_std(self) -> None:
        from src.screening.confidence_calibration import _std_or_none
        # sample std of [1,2,3,4,5] = sqrt(10/4) = sqrt(2.5) ≈ 1.5811
        assert _std_or_none([1.0, 2.0, 3.0, 4.0, 5.0]) == pytest.approx(1.5811, abs=1e-3)

    def test_std_or_none_empty(self) -> None:
        from src.screening.confidence_calibration import _std_or_none
        assert _std_or_none([]) is None

    def test_std_or_none_single_is_none(self) -> None:
        """sample std of 1 element is undefined (n-1=0 division) → None."""
        from src.screening.confidence_calibration import _std_or_none
        assert _std_or_none([5.0]) is None

    def test_std_or_none_identical_is_zero(self) -> None:
        from src.screening.confidence_calibration import _std_or_none
        assert _std_or_none([3.0, 3.0, 3.0]) == 0.0

    def test_bucket_has_t30_std_return(self) -> None:
        """P-2: ScoreBucketStats must carry t30_std_return for the front door."""
        records = [
            _make_extended_record("000001", 0.85, t30=10.0),
            _make_extended_record("000002", 0.82, t30=6.0),
            _make_extended_record("000003", 0.81, t30=2.0),
        ]
        summary = compute_calibration(records)
        high_bucket = next(b for b in summary.buckets if b.label == "高 (>0.8)")
        assert high_bucket.t30_std_return is not None
        # sample std of [10,6,2]: mean=6, var=((16+0+16)/2)=16, std=4.0
        assert high_bucket.t30_std_return == pytest.approx(4.0, abs=1e-2)

    def test_bucket_t30_std_none_when_no_t30_data(self) -> None:
        from src.screening.confidence_calibration import compute_calibration
        # records with no t30 return
        records = [{"ticker": "000001", "score_b": 0.85, "recommended_date": "20260101"}]
        summary = compute_calibration(records)
        high_bucket = next(b for b in summary.buckets if b.label == "高 (>0.8)")
        assert high_bucket.t30_std_return is None

    def test_std_return_in_to_dict(self) -> None:
        """t30_std_return must serialize for web/API consumers."""
        records = [
            _make_extended_record("000001", 0.85, t30=5.0),
            _make_extended_record("000002", 0.82, t30=3.0),
        ]
        summary = compute_calibration(records)
        d = summary.buckets[0].to_dict()
        assert "t30_std_return" in d


# ---------------------------------------------------------------------------
# R-6 t30_median_return — robust center vs outlier-polluted mean
# (realized evidence 20260624: 688008 +112% singlehandedly pulled a bucket's
#  arithmetic mean to +17% while the typical pick was flat. Median is immune.)
# ---------------------------------------------------------------------------


class TestT30MedianReturn:
    """R-6: t30_median_return as an outlier-robust companion to t30_avg_return."""

    def test_median_none_when_no_t30(self) -> None:
        """无成熟 T+30 → median None (同 avg)。"""
        records = [_make_extended_record("000001", 0.85)]  # no t30
        summary = compute_calibration(records)
        high = next(b for b in summary.buckets if b.label == "高 (>0.8)")
        assert high.t30_median_return is None

    def test_median_equals_avg_when_symmetric(self) -> None:
        """对称分布 → median ≈ avg。"""
        records = [
            _make_extended_record("000001", 0.85, t30=2.0),
            _make_extended_record("000002", 0.82, t30=4.0),
            _make_extended_record("000003", 0.81, t30=6.0),
        ]
        summary = compute_calibration(records)
        high = next(b for b in summary.buckets if b.label == "高 (>0.8)")
        assert high.t30_median_return == pytest.approx(4.0)
        assert high.t30_avg_return == pytest.approx(4.0)

    def test_median_robust_to_outlier(self) -> None:
        """单个极端赢家 (688008 场景: +112%) 污染 mean 但不污染 median。

        realized evidence 20260624: 中高 bucket mean +17% (被 +112% 拉高),
        但典型 pick 其实是 flat/negative。median 揭示真实典型值。
        """
        records = [
            _make_extended_record("000001", 0.72, t30=-3.0),
            _make_extended_record("000002", 0.71, t30=-1.0),
            _make_extended_record("000003", 0.75, t30=2.0),
            _make_extended_record("000004", 0.78, t30=112.0),  # 极端赢家
        ]
        summary = compute_calibration(records)
        bucket = next(b for b in summary.buckets if b.label == "中高 (0.7-0.8)")
        # mean 被严重拉高
        assert bucket.t30_avg_return > 20.0
        # median 保持在中位 (~0.5), 反映典型 pick
        assert bucket.t30_median_return is not None
        assert abs(bucket.t30_median_return) < 5.0  # 接近 0, 不是 +27

    def test_median_serializes(self) -> None:
        """t30_median_return 必须序列化 (web/API 消费)。"""
        records = [
            _make_extended_record("000001", 0.85, t30=5.0),
            _make_extended_record("000002", 0.82, t30=3.0),
        ]
        summary = compute_calibration(records)
        d = summary.buckets[0].to_dict()
        assert "t30_median_return" in d
