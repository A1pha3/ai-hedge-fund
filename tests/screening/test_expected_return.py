"""Tests for expected_return.py -- P9-1."""

from __future__ import annotations

from unittest.mock import patch

from src.screening.confidence_calibration import (
    CalibrationSummary,
    ScoreBucketStats,
)
from src.screening.expected_return import (
    ExpectedReturn,
    ExpectedReturnReport,
    compute_expected_returns,
    render_expected_returns,
    render_expected_returns_compact,
)


def _make_bucket(
    label: str,
    low: float,
    high: float,
    n: int = 50,
    t5_ret: float | None = 2.5,
    t10_ret: float | None = 4.0,
    t5_wr: float | None = 0.60,
    t10_wr: float | None = 0.58,
) -> ScoreBucketStats:
    return ScoreBucketStats(
        label=label,
        score_low=low,
        score_high=high,
        sample_count=n,
        t1_win_rate=0.55,
        t5_win_rate=t5_wr,
        t10_win_rate=t10_wr,
        t1_avg_return=1.0,
        t5_avg_return=t5_ret,
        t10_avg_return=t10_ret,
    )


def _make_calibration() -> CalibrationSummary:
    return CalibrationSummary(
        lookback_days=60,
        total_samples=200,
        buckets=[
            _make_bucket("高 (>0.8)", 0.8, 1.01, 40, t5_ret=3.5, t10_ret=5.2),
            _make_bucket("中高 (0.7-0.8)", 0.7, 0.8, 50, t5_ret=2.0, t10_ret=3.0),
            _make_bucket("中 (0.6-0.7)", 0.6, 0.7, 45, t5_ret=1.0, t10_ret=1.5),
            _make_bucket("中低 (0.5-0.6)", 0.5, 0.6, 35, t5_ret=-0.5, t10_ret=-1.0),
            _make_bucket("低 (<0.5)", -1.01, 0.5, 30, t5_ret=-2.0, t10_ret=-3.5),
        ],
    )


def _make_rec(ticker: str, score_b: float) -> dict:
    return {"ticker": ticker, "score_b": score_b, "trade_date": "20260611"}


class TestExpectedReturnDataclass:
    def test_to_dict_roundtrip(self) -> None:
        er = ExpectedReturn(
            ticker="000001",
            score_b=0.85,
            bucket_label="高 (>0.8)",
            bucket_sample_count=40,
            expected_returns={"t1": 1.0, "t5": 3.5, "t10": 5.2, "t20": None, "t30": None},
            win_rates={"t1": 0.55, "t5": 0.60, "t10": 0.58, "t20": None, "t30": None},
        )
        d = er.to_dict()
        assert d["ticker"] == "000001"
        assert d["score_b"] == 0.85
        assert d["bucket_sample_count"] == 40
        assert d["expected_returns"]["t5"] == 3.5
        assert d["expected_returns"]["t20"] is None

    def test_to_dict_none_returns(self) -> None:
        er = ExpectedReturn(
            ticker="000002",
            score_b=0.3,
            bucket_label="低 (<0.5)",
            bucket_sample_count=0,
            expected_returns={"t1": None, "t5": None, "t10": None, "t20": None, "t30": None},
            win_rates={"t1": None, "t5": None, "t10": None, "t20": None, "t30": None},
        )
        d = er.to_dict()
        assert all(v is None for v in d["expected_returns"].values())


class TestExpectedReturnReport:
    def test_to_dict(self) -> None:
        report = ExpectedReturnReport(
            trade_date="20260611",
            lookback_days=60,
            total_samples=200,
            items=[
                ExpectedReturn(
                    ticker="000001", score_b=0.85, bucket_label="高 (>0.8)",
                    bucket_sample_count=40,
                    expected_returns={"t1": 1.0, "t5": 3.5, "t10": 5.2, "t20": None, "t30": None},
                    win_rates={"t1": 0.55, "t5": 0.60, "t10": 0.58, "t20": None, "t30": None},
                ),
            ],
        )
        d = report.to_dict()
        assert d["trade_date"] == "20260611"
        assert len(d["items"]) == 1
        assert d["total_samples"] == 200


class TestComputeExpectedReturns:
    @patch("src.screening.expected_return._load_tracking_records")
    @patch("src.screening.expected_return.compute_calibration")
    def test_basic_computation(self, mock_calib: object, mock_records: object) -> None:
        mock_records.return_value = [{"dummy": True}]
        mock_calib.return_value = _make_calibration()

        recs = [
            _make_rec("000001", 0.85),  # 高 (>0.8) bucket
            _make_rec("000002", 0.75),  # 中高 (0.7-0.8) bucket
            _make_rec("000003", 0.40),  # 低 (<0.5) bucket
        ]
        report = compute_expected_returns(recommendations=recs, lookback_days=60)
        assert len(report.items) == 3

        # High score stock
        high = report.items[0]
        assert high.ticker == "000001"
        assert high.bucket_label == "高 (>0.8)"
        assert high.bucket_sample_count == 40
        assert high.expected_returns["t5"] == 3.5
        assert high.expected_returns["t10"] == 5.2

        # Medium-high score stock
        med = report.items[1]
        assert med.ticker == "000002"
        assert med.bucket_label == "中高 (0.7-0.8)"
        assert med.expected_returns["t5"] == 2.0

        # Low score stock
        low = report.items[2]
        assert low.ticker == "000003"
        assert low.bucket_label == "低 (<0.5)"
        assert low.expected_returns["t5"] == -2.0

    @patch("src.screening.expected_return._load_tracking_records")
    @patch("src.screening.expected_return.compute_calibration")
    def test_empty_recommendations(self, mock_calib: object, mock_records: object) -> None:
        mock_records.return_value = []
        mock_calib.return_value = _make_calibration()

        report = compute_expected_returns(recommendations=[])
        assert len(report.items) == 0
        assert report.total_samples == 200

    @patch("src.screening.expected_return._load_tracking_records")
    @patch("src.screening.expected_return.compute_calibration")
    def test_score_outside_buckets(self, mock_calib: object, mock_records: object) -> None:
        """Score far below bucket range should still be handled."""
        mock_records.return_value = []
        mock_calib.return_value = CalibrationSummary(lookback_days=60, total_samples=0, buckets=[])

        recs = [_make_rec("999999", -5.0)]
        report = compute_expected_returns(recommendations=recs)
        assert len(report.items) == 1
        assert report.items[0].bucket_label == "未知"
        assert report.items[0].bucket_sample_count == 0


class TestRenderExpectedReturns:
    def test_empty_report(self) -> None:
        report = ExpectedReturnReport(trade_date="20260611", lookback_days=60, total_samples=0)
        text = render_expected_returns(report)
        assert "无推荐数据" in text

    @patch("src.screening.expected_return._load_tracking_records")
    @patch("src.screening.expected_return.compute_calibration")
    def test_render_with_data(self, mock_calib: object, mock_records: object) -> None:
        mock_records.return_value = [{"dummy": True}]
        mock_calib.return_value = _make_calibration()

        recs = [_make_rec("000001", 0.85), _make_rec("000002", 0.40)]
        report = compute_expected_returns(recommendations=recs)
        text = render_expected_returns(report)
        assert "000001" in text
        assert "000002" in text
        assert "预期收益估算" in text


class TestRenderCompact:
    def test_empty(self) -> None:
        report = ExpectedReturnReport(trade_date="20260611", lookback_days=60, total_samples=0)
        text = render_expected_returns_compact(report)
        assert "无预期收益数据" in text

    @patch("src.screening.expected_return._load_tracking_records")
    @patch("src.screening.expected_return.compute_calibration")
    def test_compact_with_data(self, mock_calib: object, mock_records: object) -> None:
        mock_records.return_value = [{"dummy": True}]
        mock_calib.return_value = _make_calibration()

        recs = [_make_rec("000001", 0.85)]
        report = compute_expected_returns(recommendations=recs)
        text = render_expected_returns_compact(report)
        assert "000001" in text
        assert "T+5" in text
        assert "T+10" in text
