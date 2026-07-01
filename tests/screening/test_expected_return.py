"""Tests for expected_return.py -- P9-1."""

from __future__ import annotations

from unittest.mock import patch

from src.screening.confidence_calibration import (
    CalibrationSummary,
    ScoreBucketStats,
)
from src.screening.expected_return import (
    compute_expected_returns,
    ExpectedReturn,
    ExpectedReturnReport,
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
    t20_ret: float | None = 6.0,
    t30_ret: float | None = 8.0,
    t5_wr: float | None = 0.60,
    t10_wr: float | None = 0.58,
    t20_wr: float | None = 0.57,
    t30_wr: float | None = 0.56,
    t30_mature: int | None = None,
    t30_median: float | None = None,
) -> ScoreBucketStats:
    bucket = ScoreBucketStats(
        label=label,
        score_low=low,
        score_high=high,
        sample_count=n,
        t1_win_rate=0.55,
        t5_win_rate=t5_wr,
        t10_win_rate=t10_wr,
        t20_win_rate=t20_wr,
        t30_win_rate=t30_wr,
        t1_avg_return=1.0,
        t5_avg_return=t5_ret,
        t10_avg_return=t10_ret,
        t20_avg_return=t20_ret,
        t30_avg_return=t30_ret,
    )
    # BH-002: default matured T+30 count to the all-records count unless a
    # smaller matured subset is explicitly requested (simulating immature picks).
    bucket.t30_sample_count = n if t30_mature is None else t30_mature
    # R-5.C: t30_median_return defaults to t30_ret (== avg) for backward-compat;
    # tests that distinguish median from mean pass t30_median explicitly.
    bucket.t30_median_return = t30_ret if t30_median is None else t30_median
    return bucket


def _make_calibration() -> CalibrationSummary:
    summary = CalibrationSummary(
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
    # Default: all records matured (matches the all-records assumption the
    # existing tests were written against before BH-002 surfaced maturity).
    summary.total_t30_samples = sum(b.t30_sample_count for b in summary.buckets)
    return summary


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

    @patch("src.screening.expected_return._load_tracking_records")
    @patch("src.screening.expected_return.compute_calibration")
    def test_mature_t30_samples_propagated_to_report(self, mock_calib: object, mock_records: object) -> None:
        """BH-002: ``ExpectedReturnReport.mature_t30_samples`` must reflect the
        calibration's matured-T+30 total, not the all-records ``total_samples``.

        A freshly-recommended batch has no realized T+30 returns yet; it must
        not inflate the 30-day-edge backing-sample count shown to users.
        """
        mock_records.return_value = [{"dummy": True}]
        # 高 bucket: 40 records, but only 10 matured to T+30 (rest immature).
        calib = CalibrationSummary(
            lookback_days=60,
            total_samples=120,
            total_t30_samples=25,
            buckets=[
                _make_bucket("高 (>0.8)", 0.8, 1.01, 40, t30_mature=10),
                _make_bucket("中高 (0.7-0.8)", 0.7, 0.8, 50, t30_mature=15),
            ],
        )
        mock_calib.return_value = calib

        recs = [_make_rec("000001", 0.85)]  # 高 bucket
        report = compute_expected_returns(recommendations=recs, lookback_days=60)

        # Report-level: matured T+30 denominator is 25, not 120.
        assert report.total_samples == 120
        assert report.mature_t30_samples == 25
        # Item-level: 高 bucket's T+30 stat is backed by 10 matured, not 40.
        high = report.items[0]
        assert high.bucket_sample_count == 40
        assert high.bucket_t30_mature_count == 10

    @patch("src.screening.expected_return._load_tracking_records")
    @patch("src.screening.expected_return.compute_calibration")
    def test_compact_render_attributes_t30_to_matured_denominator(self, mock_calib: object, mock_records: object) -> None:
        """BH-002: compact render must show the matured T+30 count next to the
        30-day edge, so users see how much actually backs the number."""
        mock_records.return_value = [{"dummy": True}]
        calib = CalibrationSummary(
            lookback_days=60,
            total_samples=120,
            total_t30_samples=25,
            buckets=[_make_bucket("高 (>0.8)", 0.8, 1.01, 40, t30_mature=10)],
        )
        mock_calib.return_value = calib

        recs = [_make_rec("000001", 0.85)]
        report = compute_expected_returns(recommendations=recs, lookback_days=60)
        text = render_expected_returns_compact(report)

        # Header attributes the 30-day edge to BOTH counts.
        assert "120 条历史" in text
        assert "25 条已满 30 天" in text
        # Row shows matured T+30 count (10), not the all-records count (40).
        assert "T30熟=10" in text
        assert "样本=40" in text


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

    @patch("src.screening.expected_return._load_tracking_records")
    @patch("src.screening.expected_return.compute_calibration")
    def test_render_shows_t30_winrate(self, mock_calib: object, mock_records: object) -> None:
        """R52: full render must surface the T+30 win rate (decision horizon).

        ``win_rates`` is computed for all horizons but the full
        ``render_expected_returns`` previously showed only expected returns —
        the T+30 win rate (the most decision-relevant stat, since T+30 edge
        drives the BUY gate) was computed-but-hidden. The full table must now
        include a T+30 win-rate column so the user can judge confidence.
        """
        mock_records.return_value = [{"dummy": True}]
        mock_calib.return_value = _make_calibration()

        recs = [_make_rec("000001", 0.85)]
        report = compute_expected_returns(recommendations=recs)
        text = render_expected_returns(report)
        # T+30 win-rate header must appear.
        assert "T+30胜率" in text or "T30胜率" in text

    @patch("src.screening.expected_return._load_tracking_records")
    @patch("src.screening.expected_return.compute_calibration")
    def test_render_full_flags_t30_winrate_on_tiny_mature_sample(self, mock_calib: object, mock_records: object) -> None:
        """R140 Bug Hunt (R51/R52 family — same-function coverage gap): c271 added the
        ``⚠少样本`` low-confidence marker to ``render_expected_returns_compact`` (the
        --decision-flow view) but NOT to ``render_expected_returns`` (the full
        --expected-returns table) — even though both render the SAME ``T+30胜率`` via
        the SAME ``_fmt_winrate(item.win_rates.get("t30"))`` and both have
        ``bucket_t30_mature_count`` available (the full table even DISPLAYS it as
        ``T30熟``). So a per-bucket n=1 "100% winrate" renders confident-green in
        ``--expected-returns`` but flagged-yellow in ``--decision-flow`` — c271's
        honesty fix is inconsistent across the two surfaces.

        This guard asserts the full renderer also flags tiny-mature-sample T+30
        winrates, matching the compact renderer's c271 behavior.
        """
        mock_records.return_value = [{"dummy": True}]
        calib = CalibrationSummary(
            lookback_days=60,
            total_samples=4,
            total_t30_samples=1,
            buckets=[_make_bucket("高 (>0.8)", 0.8, 1.01, n=4, t30_mature=1, t30_wr=1.0)],
        )
        mock_calib.return_value = calib
        recs = [_make_rec("000001", 0.85)]
        report = compute_expected_returns(recommendations=recs, lookback_days=60)
        text = render_expected_returns(report)
        assert "T+30胜率" in text or "T30胜率" in text
        assert "少" in text or "⚠" in text or "不足" in text, (
            "render_expected_returns (full --expected-returns table) must flag T+30 winrate "
            "low-confidence when mature sample < 5 — c271 added this to the compact renderer "
            "but missed the full renderer (same _fmt_winrate, same bucket_t30_mature_count). "
            "A green 100% on n=1 misleads users of a 赚钱工具."
        )

    @patch("src.screening.expected_return._load_tracking_records")
    @patch("src.screening.expected_return.compute_calibration")
    def test_render_full_no_flag_when_mature_sample_sufficient(self, mock_calib: object, mock_records: object) -> None:
        """R140 negative guard (mirror of c271's compact guard): mature sample >= 5 →
        the full renderer must NOT emit the low-confidence marker."""
        mock_records.return_value = [{"dummy": True}]
        calib = CalibrationSummary(
            lookback_days=60,
            total_samples=50,
            total_t30_samples=10,
            buckets=[_make_bucket("高 (>0.8)", 0.8, 1.01, n=50, t30_mature=10, t30_wr=0.60)],
        )
        mock_calib.return_value = calib
        recs = [_make_rec("000001", 0.85)]
        report = compute_expected_returns(recommendations=recs, lookback_days=60)
        text = render_expected_returns(report)
        assert "少样本" not in text


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
        assert "T+20" in text
        assert "T+30" in text
        assert "样本" in text

    @patch("src.screening.expected_return._load_tracking_records")
    @patch("src.screening.expected_return.compute_calibration")
    def test_compact_flags_t30_winrate_on_tiny_mature_sample(self, mock_calib: object, mock_records: object) -> None:
        """C271 (2026-07-01, empirical dogfood via --decision-flow on 2026-06-30):
        T+30 winrate based on <5 mature samples must be flagged low-confidence.
        ``_fmt_winrate`` colors 100% green regardless of n; a per-bucket n=1
        ``100% winrate`` is statistically meaningless yet rendered as a confident
        green — for a 赚钱工具 this invites over-reaction to noise. The codebase
        already requires ``backing_sample >= 20`` for the BUY gate; this extends
        the honesty to the display."""
        mock_records.return_value = [{"dummy": True}]
        calib = CalibrationSummary(
            lookback_days=60,
            total_samples=4,
            total_t30_samples=1,
            buckets=[_make_bucket("高 (>0.8)", 0.8, 1.01, n=4, t30_mature=1, t30_wr=1.0)],
        )
        mock_calib.return_value = calib
        recs = [_make_rec("000001", 0.85)]
        report = compute_expected_returns(recommendations=recs, lookback_days=60)
        text = render_expected_returns_compact(report)
        # winrate is present (100% on n=1) but flagged low-confidence
        assert "T30熟=1" in text or "T30熟= 1" in text
        assert "少" in text or "⚠" in text or "不足" in text, (
            "T+30 winrate based on <5 mature samples must carry a low-confidence marker "
            "— a green 100% on n=1 misleads users of a 赚钱工具."
        )

    @patch("src.screening.expected_return._load_tracking_records")
    @patch("src.screening.expected_return.compute_calibration")
    def test_compact_no_flag_when_mature_sample_sufficient(self, mock_calib: object, mock_records: object) -> None:
        """C271 negative guard: mature sample >= 5 → no low-confidence marker."""
        mock_records.return_value = [{"dummy": True}]
        calib = CalibrationSummary(
            lookback_days=60,
            total_samples=50,
            total_t30_samples=10,
            buckets=[_make_bucket("高 (>0.8)", 0.8, 1.01, n=50, t30_mature=10, t30_wr=0.60)],
        )
        mock_calib.return_value = calib
        recs = [_make_rec("000001", 0.85)]
        report = compute_expected_returns(recommendations=recs, lookback_days=60)
        text = render_expected_returns_compact(report)
        # winrate shown without the tiny-sample marker
        assert "少样本" not in text


# ---------------------------------------------------------------------------
# _build_bucket_return_map / _build_bucket_winrate_map / _build_bucket_sample_map
# ---------------------------------------------------------------------------


class TestBuildBucketMaps:
    """Direct tests for bucket-map helpers extracted from render_expected_returns."""

    def test_return_map_builds_all_horizons(self):
        from src.screening.expected_return import _build_bucket_return_map

        cal = _make_calibration()
        result = _build_bucket_return_map(cal)
        assert "高 (>0.8)" in result
        high = result["高 (>0.8)"]
        assert set(high.keys()) == {"t1", "t5", "t10", "t20", "t30"}
        assert high["t5"] == 3.5
        assert high["t10"] == 5.2

    def test_return_map_preserves_none(self):
        from src.screening.expected_return import _build_bucket_return_map

        cal = CalibrationSummary(
            lookback_days=60,
            buckets=[ScoreBucketStats(label="x", score_low=0.0, score_high=1.0, t5_avg_return=None)],
        )
        result = _build_bucket_return_map(cal)
        assert result["x"]["t5"] is None
        assert result["x"]["t1"] is None

    def test_winrate_map_builds_all_horizons(self):
        from src.screening.expected_return import _build_bucket_winrate_map

        cal = _make_calibration()
        result = _build_bucket_winrate_map(cal)
        high = result["高 (>0.8)"]
        assert set(high.keys()) == {"t1", "t5", "t10", "t20", "t30"}
        assert high["t5"] == 0.60

    def test_sample_map(self):
        from src.screening.expected_return import _build_bucket_sample_map

        cal = _make_calibration()
        result = _build_bucket_sample_map(cal)
        assert result["高 (>0.8)"] == 40
        assert result["中高 (0.7-0.8)"] == 50

    def test_empty_calibration_returns_empty_maps(self):
        from src.screening.expected_return import (
            _build_bucket_return_map,
            _build_bucket_sample_map,
            _build_bucket_winrate_map,
        )

        cal = CalibrationSummary(lookback_days=60)
        assert _build_bucket_return_map(cal) == {}
        assert _build_bucket_winrate_map(cal) == {}
        assert _build_bucket_sample_map(cal) == {}


# ---------------------------------------------------------------------------
# _fmt_return / _fmt_winrate
# ---------------------------------------------------------------------------


class TestFmtReturn:
    def test_none_returns_dash(self):
        from src.screening.expected_return import _fmt_return

        out = _fmt_return(None)
        assert "—" in out

    def test_positive_has_plus_sign(self):
        from src.screening.expected_return import _fmt_return

        out = _fmt_return(2.5)
        assert "+2.50%" in out

    def test_negative_no_plus_sign(self):
        from src.screening.expected_return import _fmt_return

        out = _fmt_return(-1.3)
        assert "-1.30%" in out
        assert "+" not in out

    def test_zero_shows_zero(self):
        from src.screening.expected_return import _fmt_return

        out = _fmt_return(0.0)
        assert "0.00%" in out


class TestFmtWinrate:
    def test_none_returns_dash(self):
        from src.screening.expected_return import _fmt_winrate

        out = _fmt_winrate(None)
        assert "—" in out

    def test_high_winrate_formats_as_percent(self):
        from src.screening.expected_return import _fmt_winrate

        out = _fmt_winrate(0.62)
        assert "62%" in out

    def test_mid_winrate(self):
        from src.screening.expected_return import _fmt_winrate

        out = _fmt_winrate(0.50)
        assert "50%" in out

    def test_low_winrate(self):
        from src.screening.expected_return import _fmt_winrate

        out = _fmt_winrate(0.30)
        assert "30%" in out


# ---------------------------------------------------------------------------
# P-2: T+30 std (outcome dispersion) propagation + render
# ---------------------------------------------------------------------------


class TestBucketT30StdPropagation:
    """P-2: bucket_t30_std_return must propagate from calibration → ExpectedReturn."""

    def test_expected_return_carries_t30_std(self, tmp_path):
        """ExpectedReturn must expose bucket_t30_std_return from calibration."""
        import json
        from src.screening.expected_return import compute_expected_returns

        # 3 records in "高 (>0.8)" with distinct T+30 returns → std is computable
        records = [
            {"ticker": "000001", "recommended_date": "20260101", "recommendation_score": 0.85, "next_30day_return": 10.0},
            {"ticker": "000002", "recommended_date": "20260101", "recommendation_score": 0.82, "next_30day_return": 6.0},
            {"ticker": "000003", "recommended_date": "20260101", "recommendation_score": 0.81, "next_30day_return": 2.0},
        ]
        (tmp_path / "tracking_history.json").write_text(json.dumps(records), encoding="utf-8")
        recs = [{"ticker": "000001", "score_b": 0.85}]
        report = compute_expected_returns(recommendations=recs, reports_dir=tmp_path)
        item = report.items[0]
        assert item.bucket_t30_std_return is not None
        # sample std of [10,6,2] = 4.0
        assert abs(item.bucket_t30_std_return - 4.0) < 0.01

    def test_expected_return_std_none_when_insufficient(self, tmp_path):
        """<2 matured T+30 records → std None (honest, not a fake 0)."""
        import json
        from src.screening.expected_return import compute_expected_returns

        records = [
            {"ticker": "000001", "recommended_date": "20260101", "recommendation_score": 0.85, "next_30day_return": 5.0},
        ]
        (tmp_path / "tracking_history.json").write_text(json.dumps(records), encoding="utf-8")
        recs = [{"ticker": "000001", "score_b": 0.85}]
        report = compute_expected_returns(recommendations=recs, reports_dir=tmp_path)
        assert report.items[0].bucket_t30_std_return is None

    def test_compact_render_shows_dispersion(self, tmp_path):
        """P-2: compact render must show ±std 离散 next to T+30 edge."""
        import json
        from src.screening.expected_return import compute_expected_returns, render_expected_returns_compact

        records = [
            {"ticker": "000001", "recommended_date": "20260101", "recommendation_score": 0.85, "next_30day_return": 10.0},
            {"ticker": "000002", "recommended_date": "20260101", "recommendation_score": 0.82, "next_30day_return": 6.0},
            {"ticker": "000003", "recommended_date": "20260101", "recommendation_score": 0.81, "next_30day_return": 2.0},
        ]
        (tmp_path / "tracking_history.json").write_text(json.dumps(records), encoding="utf-8")
        recs = [{"ticker": "000001", "score_b": 0.85}]
        report = compute_expected_returns(recommendations=recs, reports_dir=tmp_path)
        out = render_expected_returns_compact(report)
        assert "离散" in out
        assert "±" in out


# ---------------------------------------------------------------------------
# NS-13 sibling: expected_return NaN score_b guard
# ---------------------------------------------------------------------------


def test_expected_return_nan_score_b_does_not_corrupt_bucket():
    """NS-13: a NaN score_b must fall to 0.0 (was: float('nan' or 0.0) = nan, NaN is truthy)."""
    import math
    from src.screening.expected_return import compute_expected_returns

    recs = [{"ticker": "000001", "name": "X", "score_b": float("nan")}]
    report = compute_expected_returns(recommendations=recs)
    # NaN score_b must NOT produce a NaN bucket label / NaN-finding logic;
    # it should be coerced to 0.0 and binned into the lowest bucket.
    for item in report.items:
        assert math.isfinite(item.score_b if hasattr(item, "score_b") else 0.0), "NaN score_b leaked into expected_return"


# ---------------------------------------------------------------------------
# R-5.C: T+30 median (诚实窄预测) propagation + render
# ---------------------------------------------------------------------------


class TestBucketT30MedianPropagation:
    """R-5.C: bucket_t30_median_return must propagate from calibration → ExpectedReturn.

    Mean 被 outlier 污染 (688008 +112% 案例); median 是更稳健的"典型票"信号.
    复用 confidence_calibration.R-6 的 t30_median_return, 不重新计算.
    """

    def test_expected_return_carries_t30_median(self, tmp_path):
        """ExpectedReturn must expose bucket_t30_median_return from calibration."""
        import json
        from src.screening.expected_return import compute_expected_returns

        # 5 records in "高 (>0.8)" with skewed T+30 returns → median ≠ mean
        # mean = (1+2+3+4+100)/5 = 22.0 (polluted by +100% outlier)
        # median = 3.0 (honest typical-pick view)
        records = [
            {"ticker": "000001", "recommended_date": "20260101", "recommendation_score": 0.85, "next_30day_return": 1.0},
            {"ticker": "000002", "recommended_date": "20260101", "recommendation_score": 0.82, "next_30day_return": 2.0},
            {"ticker": "000003", "recommended_date": "20260101", "recommendation_score": 0.81, "next_30day_return": 3.0},
            {"ticker": "000004", "recommended_date": "20260101", "recommendation_score": 0.83, "next_30day_return": 4.0},
            {"ticker": "000005", "recommended_date": "20260101", "recommendation_score": 0.84, "next_30day_return": 100.0},
        ]
        (tmp_path / "tracking_history.json").write_text(json.dumps(records), encoding="utf-8")
        recs = [{"ticker": "000001", "score_b": 0.85}]
        report = compute_expected_returns(recommendations=recs, reports_dir=tmp_path)
        item = report.items[0]
        assert item.bucket_t30_median_return is not None
        # median of [1,2,3,4,100] = 3.0
        assert abs(item.bucket_t30_median_return - 3.0) < 0.01
        # R-5.C (autodev): expected_returns["t30"] now uses MEDIAN (3.0), not the
        # outlier-polluted mean (22.0). Mean 22.0 is dragged up by the +100%
        # outlier; median 3.0 is the honest "typical pick" T+30 prediction.
        assert item.expected_returns["t30"] is not None
        assert abs(item.expected_returns["t30"] - 3.0) < 0.01

    def test_expected_return_median_none_when_no_matured(self, tmp_path):
        """No matured T+30 records → median None (honest, not a fake 0)."""
        import json
        from src.screening.expected_return import compute_expected_returns

        # Records without next_30day_return → no matured T+30 → median None
        records = [
            {"ticker": "000001", "recommended_date": "20260101", "recommendation_score": 0.85},
        ]
        (tmp_path / "tracking_history.json").write_text(json.dumps(records), encoding="utf-8")
        recs = [{"ticker": "000001", "score_b": 0.85}]
        report = compute_expected_returns(recommendations=recs, reports_dir=tmp_path)
        assert report.items[0].bucket_t30_median_return is None

    def test_to_dict_serializes_median(self, tmp_path):
        """R-5.C: to_dict must serialize bucket_t30_median_return (None and value)."""
        import json
        from src.screening.expected_return import ExpectedReturn, HORIZONS

        # Case 1: median value → rounded to 4 decimals
        item = ExpectedReturn(
            ticker="000001",
            score_b=0.85,
            bucket_label="高 (>0.8)",
            bucket_sample_count=5,
            expected_returns={h: None for h in HORIZONS},
            win_rates={h: None for h in HORIZONS},
            bucket_t30_median_return=3.12345,
        )
        d = item.to_dict()
        assert d["bucket_t30_median_return"] == 3.1235

        # Case 2: None → None (no fake 0)
        item_none = ExpectedReturn(
            ticker="000002",
            score_b=0.5,
            bucket_label="中 (0.4-0.6)",
            bucket_sample_count=0,
            expected_returns={h: None for h in HORIZONS},
            win_rates={h: None for h in HORIZONS},
            bucket_t30_median_return=None,
        )
        assert item_none.to_dict()["bucket_t30_median_return"] is None

    def test_full_render_shows_median_column(self, tmp_path):
        """R-5.C: render_expected_returns must show T+30中位 column header and value."""
        import json
        from src.screening.expected_return import compute_expected_returns, render_expected_returns

        records = [
            {"ticker": "000001", "recommended_date": "20260101", "recommendation_score": 0.85, "next_30day_return": 3.0},
            {"ticker": "000002", "recommended_date": "20260101", "recommendation_score": 0.82, "next_30day_return": 5.0},
        ]
        (tmp_path / "tracking_history.json").write_text(json.dumps(records), encoding="utf-8")
        recs = [{"ticker": "000001", "score_b": 0.85}]
        report = compute_expected_returns(recommendations=recs, reports_dir=tmp_path)
        out = render_expected_returns(report)
        assert "T+30中位" in out
        # median of [3.0, 5.0] = 4.0 → rendered as +4.00%
        assert "+4.00%" in out

    def test_compact_render_shows_median(self, tmp_path):
        """R-5.C: compact render must show T+30中位= next to T+30 mean."""
        import json
        from src.screening.expected_return import compute_expected_returns, render_expected_returns_compact

        records = [
            {"ticker": "000001", "recommended_date": "20260101", "recommendation_score": 0.85, "next_30day_return": 3.0},
            {"ticker": "000002", "recommended_date": "20260101", "recommendation_score": 0.82, "next_30day_return": 5.0},
        ]
        (tmp_path / "tracking_history.json").write_text(json.dumps(records), encoding="utf-8")
        recs = [{"ticker": "000001", "score_b": 0.85}]
        report = compute_expected_returns(recommendations=recs, reports_dir=tmp_path)
        out = render_expected_returns_compact(report)
        assert "T+30中位" in out

    def test_compact_render_omits_median_when_none(self, tmp_path):
        """R-5.C: when median is None, compact render must omit T+30中位 (no fake 0)."""
        import json
        from src.screening.expected_return import compute_expected_returns, render_expected_returns_compact

        # Records without next_30day_return → median None
        records = [
            {"ticker": "000001", "recommended_date": "20260101", "recommendation_score": 0.85},
        ]
        (tmp_path / "tracking_history.json").write_text(json.dumps(records), encoding="utf-8")
        recs = [{"ticker": "000001", "score_b": 0.85}]
        report = compute_expected_returns(recommendations=recs, reports_dir=tmp_path)
        out = render_expected_returns_compact(report)
        assert "T+30中位" not in out


class TestR5CMedianBaseline:
    """R-5.C (autodev): T+30 predicted return uses bucket MEDIAN not MEAN.

    R-6/R-7 realized evidence: median MAE 8.7% < mean MAE 10.7% (outlier-robust).
    Isotonic calibration (isotonic_calibration.py) DEFERRED — NS-4 (C192) shows
    T+30 score ranking is inverted; PAV isotonic would mask the inversion
    (dishonest while rank_monotonicity footer discloses 倒挂). Revisit after
    owner fixes inversion. BUY gate uses t5/t10 (C222), so t30 change is
    orthogonal to BUY decisions / iv069 observation.
    """

    @patch("src.screening.expected_return._load_tracking_records")
    @patch("src.screening.expected_return.compute_calibration")
    def test_t30_uses_median_not_mean(self, mock_calib: object, mock_records: object) -> None:
        """expected_returns['t30'] must equal bucket median, not mean (R-5.C)."""
        mock_records.return_value = [{"dummy": True}]
        # bucket with DISTINCT mean (8.0) vs median (5.0)
        mock_calib.return_value = CalibrationSummary(
            lookback_days=60,
            total_samples=40,
            buckets=[_make_bucket("高 (>0.8)", 0.8, 1.01, 40, t30_ret=8.0, t30_median=5.0)],
        )
        report = compute_expected_returns(recommendations=[_make_rec("000001", 0.85)])
        assert report.items[0].expected_returns["t30"] == 5.0  # median, not 8.0 mean

    @patch("src.screening.expected_return._load_tracking_records")
    @patch("src.screening.expected_return.compute_calibration")
    def test_t5_t10_unchanged_by_median_switch(self, mock_calib: object, mock_records: object) -> None:
        """BUY-gate inputs t5/t10 must stay mean-based (orthogonality to iv069)."""
        mock_records.return_value = [{"dummy": True}]
        mock_calib.return_value = CalibrationSummary(
            lookback_days=60,
            total_samples=40,
            buckets=[_make_bucket("高 (>0.8)", 0.8, 1.01, 40, t5_ret=3.5, t10_ret=5.2, t30_ret=8.0, t30_median=5.0)],
        )
        report = compute_expected_returns(recommendations=[_make_rec("000001", 0.85)])
        er = report.items[0].expected_returns
        assert er["t5"] == 3.5  # mean, unchanged
        assert er["t10"] == 5.2  # mean, unchanged
        assert er["t30"] == 5.0  # median (R-5.C)

    @patch("src.screening.expected_return._load_tracking_records")
    @patch("src.screening.expected_return.compute_calibration")
    def test_t30_falls_back_when_median_none(self, mock_calib: object, mock_records: object) -> None:
        """When median unavailable (no mature T+30), t30 should be None (same as mean's None semantics)."""
        mock_records.return_value = [{"dummy": True}]
        b = _make_bucket("高 (>0.8)", 0.8, 1.01, 40, t30_ret=8.0, t30_median=None)
        # force median None explicitly
        b.t30_median_return = None
        mock_calib.return_value = CalibrationSummary(lookback_days=60, total_samples=40, buckets=[b])
        report = compute_expected_returns(recommendations=[_make_rec("000001", 0.85)])
        assert report.items[0].expected_returns["t30"] is None
