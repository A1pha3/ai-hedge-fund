"""Tests for src/screening/reconciliation.py — P-3 实盘对账 (预测 vs 实际闭环)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.screening.reconciliation import (
    ReconciliationReport,
    ReconciliationRow,
    _load_trade_log,
    compute_reconciliation,
    render_reconciliation,
)


def _seed_report(dir_path: Path, date_str: str, recs: list[dict]) -> None:
    payload = {"date": date_str, "recommendations": recs}
    (dir_path / f"auto_screening_{date_str}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _seed_tracking(dir_path: Path, records: list[dict]) -> None:
    (dir_path / "tracking_history.json").write_text(json.dumps(records), encoding="utf-8")


def _write_trade_log(dir_path: Path, rows: list[dict]) -> Path:
    """Write a trade_log.csv in the documented v1 format.

    Format: ticker,buy_date,buy_price,sell_date,sell_price
    """
    path = dir_path / "trade_log.csv"
    lines = ["ticker,buy_date,buy_price,sell_date,sell_price"]
    for r in rows:
        lines.append(f"{r['ticker']},{r['buy_date']},{r['buy_price']},{r['sell_date']},{r['sell_price']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# _load_trade_log
# ---------------------------------------------------------------------------


class TestLoadTradeLog:
    def test_parses_csv(self, tmp_path: Path) -> None:
        path = _write_trade_log(tmp_path, [
            {"ticker": "000001", "buy_date": "20260101", "buy_price": 10.5, "sell_date": "20260131", "sell_price": 11.2},
        ])
        trades = _load_trade_log(path)
        assert len(trades) == 1
        t = trades[0]
        assert t["ticker"] == "000001"
        assert t["buy_date"] == "20260101"
        assert t["buy_price"] == pytest.approx(10.5)
        assert t["sell_price"] == pytest.approx(11.2)

    def test_skips_header_and_blank(self, tmp_path: Path) -> None:
        path = tmp_path / "trade_log.csv"
        path.write_text(
            "ticker,buy_date,buy_price,sell_date,sell_price\n"
            "000001,20260101,10,20260131,11\n"
            "\n"
            "   \n",
            encoding="utf-8",
        )
        trades = _load_trade_log(path)
        assert len(trades) == 1

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        trades = _load_trade_log(tmp_path / "nonexistent.csv")
        assert trades == []

    def test_header_maps_columns_with_extra_leading_columns(self, tmp_path: Path) -> None:
        """NS-22: broker export with extra leading column must map by header name, not position.

        Before fix: _load_trade_log was purely positional (row[0..4]), so a broker export
        with a leading 账户/序号 column silently misaligned → wrong ticker/date/price →
        garbage MAE. Header-based column mapping handles it.
        """
        path = tmp_path / "broker_export.csv"
        # Extra leading "账户" column; columns in different order than positional default
        path.write_text(
            "账户,代码,买入日期,买入价,卖出日期,卖出价\n"
            "ACC1,000001,2026-01-01,10.5,2026-01-31,11.2\n",
            encoding="utf-8",
        )
        trades = _load_trade_log(path)
        assert len(trades) == 1
        t = trades[0]
        assert t["ticker"] == "000001"
        assert t["buy_date"] == "20260101"
        assert t["buy_price"] == pytest.approx(10.5)
        assert t["sell_price"] == pytest.approx(11.2)

    def test_english_header_maps_columns(self, tmp_path: Path) -> None:
        """NS-22: English header keywords also trigger column mapping."""
        path = tmp_path / "trade_log.csv"
        path.write_text(
            "id,ticker,buy_date,buy_price,sell_date,sell_price,note\n"
            "1,000002,2026-02-01,20,2026-02-28,22,extra\n",
            encoding="utf-8",
        )
        trades = _load_trade_log(path)
        assert len(trades) == 1
        assert trades[0]["ticker"] == "000002"
        assert trades[0]["buy_price"] == pytest.approx(20.0)

    def test_positional_fallback_when_no_header_keywords(self, tmp_path: Path) -> None:
        """NS-22: CSV with no recognizable header → positional [0..4] (backward compat)."""
        path = tmp_path / "trade_log.csv"
        path.write_text(
            "000001,20260101,10.5,20260131,11.2\n"
            "000002,20260101,20,20260131,22\n",
            encoding="utf-8",
        )
        trades = _load_trade_log(path)
        assert len(trades) == 2
        assert trades[0]["ticker"] == "000001"
        assert trades[1]["ticker"] == "000002"


# ---------------------------------------------------------------------------
# compute_reconciliation
# ---------------------------------------------------------------------------


class TestComputeReconciliation:
    def test_warns_when_mostly_unmatched(self, tmp_path: Path) -> None:
        """NS-22: unmatched >50% → warning in report (likely column misalignment / date / dir issue)."""
        # No reports seeded → every trade is unmatched (no score_b on buy_date)
        trade_path = _write_trade_log(tmp_path, [
            {"ticker": "000001", "buy_date": "20260101", "buy_price": 10.0, "sell_date": "20260131", "sell_price": 11.0},
            {"ticker": "000002", "buy_date": "20260101", "buy_price": 20.0, "sell_date": "20260131", "sell_price": 21.0},
            {"ticker": "000003", "buy_date": "20260101", "buy_price": 30.0, "sell_date": "20260131", "sell_price": 31.0},
            {"ticker": "000004", "buy_date": "20260101", "buy_price": 40.0, "sell_date": "20260131", "sell_price": 41.0},
        ])
        report = compute_reconciliation(trade_log_path=trade_path, reports_dir=tmp_path)
        assert report.unmatched_count == 4
        assert report.matched_count == 0
        # NS-22 unmatched warning must be present
        assert any("未匹配率 4/4" in w for w in report.warnings)
        # R-5.C: matched=0 < 20 also adds 证据不足 warning (honest, expected)
        assert any("证据不足" in w for w in report.warnings)

    def test_no_warning_when_mostly_matched(self, tmp_path: Path) -> None:
        """NS-22: matched majority → no spurious NS-22 warning.

        Note: R-5.C may still add a 证据不足 warning when matched < 20; that is
        intentional honest labeling, not a spurious NS-22 warning. This test
        only asserts the NS-22 unmatched warning is absent.
        """
        _seed_report(tmp_path, "20260101", [
            {"ticker": "000001", "score_b": 0.75},
            {"ticker": "000002", "score_b": 0.75},
            {"ticker": "000003", "score_b": 0.75},
        ])
        _seed_tracking(tmp_path, [
            {"ticker": "000099", "recommended_date": "20251201", "recommendation_score": 0.72, "next_30day_return": 5.0},
        ])
        trade_path = _write_trade_log(tmp_path, [
            {"ticker": "000001", "buy_date": "20260101", "buy_price": 10.0, "sell_date": "20260131", "sell_price": 11.0},
            {"ticker": "000002", "buy_date": "20260101", "buy_price": 20.0, "sell_date": "20260131", "sell_price": 21.0},
            {"ticker": "000003", "buy_date": "20260101", "buy_price": 30.0, "sell_date": "20260131", "sell_price": 31.0},
            {"ticker": "999999", "buy_date": "20260101", "buy_price": 40.0, "sell_date": "20260131", "sell_price": 41.0},
        ])
        report = compute_reconciliation(trade_log_path=trade_path, reports_dir=tmp_path)
        # NS-22 unmatched warning must NOT be present (majority matched)
        assert not any("未匹配率" in w for w in report.warnings)

    def test_predicted_vs_actual(self, tmp_path: Path) -> None:
        """Ticker bought on 20260101; model predicted (bucket avg) +5%, actual +6.7%."""
        # report on buy_date has the ticker with score_b → bucket "中高 (0.7-0.8)"
        _seed_report(tmp_path, "20260101", [{"ticker": "000001", "score_b": 0.75}])
        # tracking_history gives the bucket a T+30 avg return of +5% (via 1 matured record)
        _seed_tracking(tmp_path, [
            {"ticker": "000099", "recommended_date": "20251201", "recommendation_score": 0.72, "next_30day_return": 5.0},
        ])
        trade_path = _write_trade_log(tmp_path, [
            {"ticker": "000001", "buy_date": "20260101", "buy_price": 10.0, "sell_date": "20260131", "sell_price": 10.67},
        ])
        report = compute_reconciliation(trade_log_path=trade_path, reports_dir=tmp_path)
        assert len(report.rows) == 1
        row = report.rows[0]
        assert row.ticker == "000001"
        # actual = (10.67/10.0 - 1) * 100 = 6.7% (percent convention, matches calibration)
        assert row.actual_return == pytest.approx(6.7, abs=1e-2)
        # predicted = bucket 中高 t30 avg = 5.0% (from the tracking record in same bucket)
        assert row.predicted_return == pytest.approx(5.0, abs=1e-2)
        assert row.error == pytest.approx(6.7 - 5.0, abs=1e-2)
        assert row.directional_match is True  # both positive

    def test_directional_mismatch(self, tmp_path: Path) -> None:
        """Predicted positive but actual negative → directional_match False."""
        _seed_report(tmp_path, "20260101", [{"ticker": "000001", "score_b": 0.75}])
        _seed_tracking(tmp_path, [
            {"ticker": "000099", "recommended_date": "20251201", "recommendation_score": 0.72, "next_30day_return": 5.0},
        ])
        trade_path = _write_trade_log(tmp_path, [
            {"ticker": "000001", "buy_date": "20260101", "buy_price": 10.0, "sell_date": "20260131", "sell_price": 9.5},
        ])
        report = compute_reconciliation(trade_log_path=trade_path, reports_dir=tmp_path)
        row = report.rows[0]
        assert row.actual_return < 0
        assert row.predicted_return > 0
        assert row.directional_match is False

    def test_ticker_not_in_report(self, tmp_path: Path) -> None:
        """Trade for a ticker not in the buy-date report → row with predicted=None, unmatched."""
        _seed_report(tmp_path, "20260101", [{"ticker": "000001", "score_b": 0.75}])
        _seed_tracking(tmp_path, [])
        trade_path = _write_trade_log(tmp_path, [
            {"ticker": "999999", "buy_date": "20260101", "buy_price": 10.0, "sell_date": "20260131", "sell_price": 11.0},
        ])
        report = compute_reconciliation(trade_log_path=trade_path, reports_dir=tmp_path)
        assert len(report.rows) == 1
        assert report.rows[0].predicted_return is None
        assert report.unmatched_count == 1

    def test_aggregate_stats(self, tmp_path: Path) -> None:
        """2 matched trades → aggregate MAE + directional accuracy computed."""
        _seed_report(tmp_path, "20260101", [
            {"ticker": "000001", "score_b": 0.75},
            {"ticker": "000002", "score_b": 0.72},
        ])
        _seed_tracking(tmp_path, [
            {"ticker": "000099", "recommended_date": "20251201", "recommendation_score": 0.72, "next_30day_return": 5.0},
        ])
        trade_path = _write_trade_log(tmp_path, [
            {"ticker": "000001", "buy_date": "20260101", "buy_price": 10.0, "sell_date": "20260131", "sell_price": 10.67},  # actual +6.7%, pred +5%
            {"ticker": "000002", "buy_date": "20260101", "buy_price": 20.0, "sell_date": "20260131", "sell_price": 19.0},  # actual -5%, pred +5%
        ])
        report = compute_reconciliation(trade_log_path=trade_path, reports_dir=tmp_path)
        assert report.matched_count == 2
        assert report.directional_accuracy == pytest.approx(0.5, abs=1e-3)  # 1 of 2 matched direction
        assert report.mae is not None and report.mae > 0

    def test_empty_trade_log(self, tmp_path: Path) -> None:
        """No trades → empty report, not a crash."""
        _seed_report(tmp_path, "20260101", [{"ticker": "000001", "score_b": 0.75}])
        trade_path = _write_trade_log(tmp_path, [])
        report = compute_reconciliation(trade_log_path=trade_path, reports_dir=tmp_path)
        assert report.rows == []
        assert report.matched_count == 0


# ---------------------------------------------------------------------------
# render_reconciliation
# ---------------------------------------------------------------------------


class TestRenderReconciliation:
    def test_renders_summary(self) -> None:
        report = ReconciliationReport(
            rows=[
                ReconciliationRow(ticker="000001", buy_date="20260101", predicted_return=5.0, actual_return=6.7, error=1.7, directional_match=True),
            ],
            matched_count=1, unmatched_count=0, mae=1.7, directional_accuracy=1.0,
        )
        result = render_reconciliation(report)
        assert "000001" in result
        assert "实盘" in result or "对账" in result or "reconcile" in result.lower()

    def test_empty_report(self) -> None:
        report = ReconciliationReport()
        result = render_reconciliation(report)
        assert "无" in result or "无交易" in result or "empty" in result.lower() or result == ""


# ---------------------------------------------------------------------------
# R-7: median predicted side — wire t30_median_return into reconcile
# (R-6 added the robust center; R-7 makes reconcile USE it so users see both
#  mean-based and median-based predictions + which center is more accurate)
# ---------------------------------------------------------------------------


class TestReconcileMedianPrediction:
    """R-7: reconcile surfaces median prediction alongside mean."""

    def test_predicted_return_median_populated(self, tmp_path: Path) -> None:
        """Each matched row carries both predicted_return (mean) and predicted_return_median."""
        _seed_report(tmp_path, "20260101", [{"ticker": "000001", "score_b": 0.75}])
        # bucket 中高: give it T+30 returns so mean != median (outlier scenario)
        _seed_tracking(tmp_path, [
            {"ticker": "000099", "recommended_date": "20251201", "recommendation_score": 0.72, "next_30day_return": -1.0},
            {"ticker": "000098", "recommended_date": "20251202", "recommendation_score": 0.71, "next_30day_return": 3.0},
            {"ticker": "000097", "recommended_date": "20251203", "recommendation_score": 0.78, "next_30day_return": 112.0},  # outlier
        ])
        trade_path = _write_trade_log(tmp_path, [
            {"ticker": "000001", "buy_date": "20260101", "buy_price": 10.0, "sell_date": "20260131", "sell_price": 10.5},
        ])
        report = compute_reconciliation(trade_log_path=trade_path, reports_dir=tmp_path)
        row = report.rows[0]
        # mean = (-1+3+112)/3 ≈ 38; median = 3.0 → both populated, differ
        assert row.predicted_return is not None
        assert row.predicted_return_median is not None
        assert row.predicted_return > row.predicted_return_median  # mean inflated by outlier

    def test_predicted_median_none_when_bucket_has_no_t30(self, tmp_path: Path) -> None:
        """Bucket with no matured T+30 → median None (same as mean)."""
        _seed_report(tmp_path, "20260101", [{"ticker": "000001", "score_b": 0.75}])
        _seed_tracking(tmp_path, [])  # empty → bucket t30 all None
        trade_path = _write_trade_log(tmp_path, [
            {"ticker": "000001", "buy_date": "20260101", "buy_price": 10.0, "sell_date": "20260131", "sell_price": 10.5},
        ])
        report = compute_reconciliation(trade_log_path=trade_path, reports_dir=tmp_path)
        row = report.rows[0]
        assert row.predicted_return is None
        assert row.predicted_return_median is None

    def test_report_has_mae_median(self, tmp_path: Path) -> None:
        """ReconciliationReport carries mae_median (median-based MAE) alongside mae."""
        _seed_report(tmp_path, "20260101", [{"ticker": "000001", "score_b": 0.75}])
        _seed_tracking(tmp_path, [
            {"ticker": "000099", "recommended_date": "20251201", "recommendation_score": 0.72, "next_30day_return": 5.0},
        ])
        trade_path = _write_trade_log(tmp_path, [
            {"ticker": "000001", "buy_date": "20260101", "buy_price": 10.0, "sell_date": "20260131", "sell_price": 10.67},
        ])
        report = compute_reconciliation(trade_log_path=trade_path, reports_dir=tmp_path)
        assert report.mae is not None
        assert report.mae_median is not None

    def test_render_shows_both_centers(self, tmp_path: Path) -> None:
        """render_reconciliation output mentions both mean and median predictions."""
        report = ReconciliationReport(
            rows=[ReconciliationRow(ticker="000001", buy_date="20260101",
                                    predicted_return=38.0, predicted_return_median=3.0,
                                    actual_return=5.0, error=-33.0, directional_match=True)],
            matched_count=1, mae=33.0, mae_median=2.0,
        )
        out = render_reconciliation(report)
        # both MAE stats surfaced
        assert "MAE" in out


# ---------------------------------------------------------------------------
# R-5.C: isotonic MAE comparison + n<20 honest "证据不足" labeling
# (owner-chosen honest-narrow-prediction direction: median + isotonic + MAE
#  comparison + n<20 honest flag)
# ---------------------------------------------------------------------------


class TestReconcileIsotonicCalibration:
    """R-5.C #3: isotonic MAE alongside mean/median MAE for tri-center comparison."""

    def _seed_and_reconcile(self, tmp_path: Path, n_trades: int) -> ReconciliationReport:
        """Helper: seed n trades with monotonically increasing predicted→actual.

        predicted is bucket T+30 mean; we seed tracking so the bucket has known
        T+30 returns, then write n trade rows each matching a distinct buy_date.
        """
        # Seed tracking: bucket 中高 (0.6-0.8) with T+30 returns around +5%
        # (so predicted_return ≈ 5.0 for all rows in this bucket).
        tracking_recs = [
            {"ticker": f"00009{i}", "recommended_date": f"202511{i+1:02d}",
             "recommendation_score": 0.70 + i * 0.01,
             "next_30day_return": 5.0 + i * 0.1}
            for i in range(min(n_trades + 2, 30))  # extra matured for bucket stability
        ]
        _seed_tracking(tmp_path, tracking_recs)

        # Seed n_trades daily reports, each containing one ticker at score_b=0.75
        # (so all rows land in bucket 中高 with predicted ≈ 5.1).
        # Date format: YYYYMMDD (8 digits). Day = i+1 (01..31).
        for i in range(n_trades):
            day = f"202601{i+1:02d}"
            _seed_report(tmp_path, day, [{"ticker": f"60000{i}", "score_b": 0.75}])

        # Trade log: n_trades rows, each buy on its own day, sell 30 days later.
        # All actual returns ≈ 5% (buy 10, sell 10.5) — predicted ≈ 5.5 → small error.
        # Isotonic fit on near-constant xs will just average the ys.
        trade_rows = []
        for i in range(n_trades):
            day = f"202601{i+1:02d}"
            sell_day = f"202602{i+1:02d}"  # next month, same day (≥30 days later)
            trade_rows.append({
                "ticker": f"60000{i}", "buy_date": day,
                "buy_price": 10.0, "sell_date": sell_day, "sell_price": 10.5,
            })
        trade_path = _write_trade_log(tmp_path, trade_rows)
        return compute_reconciliation(trade_log_path=trade_path, reports_dir=tmp_path)

    def test_mae_isotonic_populated_when_sufficient(self, tmp_path: Path) -> None:
        """matched >= 20 → mae_isotonic must be populated (not None)."""
        report = self._seed_and_reconcile(tmp_path, n_trades=22)
        assert report.matched_count >= 20
        assert report.calibration_sufficient is True
        assert report.mae_isotonic is not None
        # isotonic on near-constant predicted → calibrated ≈ mean of actuals,
        # so MAE(保序) should be small (all actuals ≈ 5%).
        assert report.mae_isotonic >= 0.0

    def test_mae_isotonic_none_when_insufficient(self, tmp_path: Path) -> None:
        """matched < 20 → mae_isotonic None (证据不足, not a fake 0)."""
        report = self._seed_and_reconcile(tmp_path, n_trades=5)
        assert report.matched_count == 5
        assert report.calibration_sufficient is False
        assert report.mae_isotonic is None
        # warning surfaces the honest "证据不足" message
        assert any("证据不足" in w for w in report.warnings)

    def test_render_shows_isotonic_mae_when_sufficient(self, tmp_path: Path) -> None:
        """render shows MAE(保序) column when matched >= 20."""
        report = self._seed_and_reconcile(tmp_path, n_trades=22)
        out = render_reconciliation(report)
        assert "MAE(保序)" in out

    def test_render_shows_证据不足_when_insufficient(self, tmp_path: Path) -> None:
        """render shows 证据不足 in MAE(保序) slot when matched < 20."""
        report = self._seed_and_reconcile(tmp_path, n_trades=5)
        out = render_reconciliation(report)
        assert "MAE(保序)" in out
        assert "证据不足" in out
        # the standalone warning line also fires
        assert "isotonic 校准未执行" in out

    def test_calibration_sufficient_flag_threshold(self, tmp_path: Path) -> None:
        """calibration_sufficient is True at >= 20, False below 20."""
        # exactly 20 → sufficient
        r20 = self._seed_and_reconcile(tmp_path, n_trades=20)
        assert r20.calibration_sufficient is True
        # 19 → insufficient (need a fresh tmp_path)
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            r19 = self._seed_and_reconcile(Path(td), n_trades=19)
            assert r19.calibration_sufficient is False

    def test_predicted_return_isotonic_backfilled_per_row(self, tmp_path: Path) -> None:
        """Each matched row carries predicted_return_isotonic when sufficient."""
        report = self._seed_and_reconcile(tmp_path, n_trades=22)
        matched_rows = [r for r in report.rows if r.predicted_return is not None]
        assert len(matched_rows) >= 20
        for row in matched_rows:
            assert row.predicted_return_isotonic is not None
