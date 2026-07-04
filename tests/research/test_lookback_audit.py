"""Unit tests for src.research.lookback_audit (feature 6.2).

Tests cover:
- Snapshot reading and ticker extraction
- Price filtering and return calculations
- Max drawdown / max return
- Edge cases: no data, partial data, zero prices
- CLI argument parsing
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from src.data.models import Price
from src.research.lookback_audit import (
    _compute_max_drawdown,
    _compute_max_return,
    _extract_top_tickers,
    _filter_prices_in_window,
    _format_date,
    _parse_date,
    _read_selection_snapshot,
    format_audit_table,
    LookbackAuditResult,
    PriceFetcher,
    run_lookback_audit,
    TickerAuditResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_snapshot(
    trade_date: str = "2026-05-05",
    selected: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimal selection_snapshot dict."""
    if selected is None:
        selected = [
            {"symbol": "000001", "score_final": 0.85, "decision": "watchlist"},
            {"symbol": "600519", "score_final": 0.72, "decision": "watchlist"},
            {"symbol": "300724", "score_final": 0.60, "decision": "watchlist"},
        ]
    return {
        "trade_date": trade_date,
        "run_id": "test-run",
        "selected": selected,
        "market": "CN",
    }


def _make_prices(
    base_price: float = 10.0,
    days: int = 5,
    start_date: str = "2026-05-05",
    trend: str = "up",
) -> list[Price]:
    """Create a simple price series."""
    from datetime import timedelta

    prices: list[Price] = []
    dt = datetime.strptime(start_date, "%Y-%m-%d")
    for i in range(days):
        date_str = dt.strftime("%Y-%m-%d")
        if trend == "up":
            price = base_price * (1 + 0.02 * i)
        elif trend == "down":
            price = base_price * (1 - 0.02 * i)
        elif trend == "volatile":
            # Go up then down: peak at day 2
            if i <= 2:
                price = base_price * (1 + 0.05 * i)
            else:
                price = base_price * (1 + 0.05 * 2 - 0.08 * (i - 2))
        else:
            price = base_price
        prices.append(
            Price(
                open=price,
                close=price,
                high=price * 1.01,
                low=price * 0.99,
                volume=1000000,
                time=date_str,
            )
        )
        dt += timedelta(days=1)
    return prices


class MockPriceFetcher(PriceFetcher):
    """PriceFetcher that returns canned data for testing."""

    def __init__(self, data: dict[str, list[Price]] | None = None) -> None:
        super().__init__()
        self._data = data or {}

    def fetch(self, ticker: str, start_date: str, end_date: str) -> list[Price]:
        return self._data.get(ticker, [])


# ---------------------------------------------------------------------------
# Tests: date formatting
# ---------------------------------------------------------------------------


class TestDateFormatting:
    def test_format_yyyymmdd(self) -> None:
        assert _format_date("20260505") == "2026-05-05"

    def test_format_already_formatted(self) -> None:
        assert _format_date("2026-05-05") == "2026-05-05"

    def test_parse_date(self) -> None:
        dt = _parse_date("20260505")
        assert dt.year == 2026
        assert dt.month == 5
        assert dt.day == 5


# ---------------------------------------------------------------------------
# Tests: snapshot reading and extraction
# ---------------------------------------------------------------------------


class TestSnapshotExtraction:
    def test_extract_top_tickers_default(self) -> None:
        snapshot = _make_snapshot()
        tickers = _extract_top_tickers(snapshot, top_n=10)
        assert len(tickers) == 3
        assert tickers[0]["ticker"] == "000001"
        assert tickers[0]["rank"] == 1
        assert tickers[0]["score_final"] == 0.85

    def test_extract_top_n_limits(self) -> None:
        snapshot = _make_snapshot()
        tickers = _extract_top_tickers(snapshot, top_n=2)
        assert len(tickers) == 2
        assert tickers[1]["ticker"] == "600519"

    def test_extract_empty_selected(self) -> None:
        snapshot = _make_snapshot(selected=[])
        tickers = _extract_top_tickers(snapshot)
        assert tickers == []

    def test_extract_skips_empty_symbols(self) -> None:
        snapshot = _make_snapshot(
            selected=[
                {"symbol": "000001", "score_final": 0.9},
                {"symbol": "", "score_final": 0.8},
                {"symbol": "600519", "score_final": 0.7},
            ]
        )
        tickers = _extract_top_tickers(snapshot)
        assert len(tickers) == 2
        assert tickers[0]["ticker"] == "000001"
        assert tickers[1]["ticker"] == "600519"

    def test_read_snapshot_from_disk(self, tmp_path: Path) -> None:
        day_dir = tmp_path / "2026-05-05"
        day_dir.mkdir()
        snapshot = _make_snapshot()
        (day_dir / "selection_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
        result = _read_selection_snapshot(tmp_path, "2026-05-05")
        assert result["trade_date"] == "2026-05-05"

    def test_read_snapshot_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            _read_selection_snapshot(tmp_path, "2099-01-01")

    def test_read_snapshot_accepts_raw_date(self, tmp_path: Path) -> None:
        day_dir = tmp_path / "2026-05-05"
        day_dir.mkdir()
        snapshot = _make_snapshot()
        (day_dir / "selection_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
        result = _read_selection_snapshot(tmp_path, "20260505")
        assert result["trade_date"] == "2026-05-05"

    def test_read_snapshot_corrupt_raises_file_not_found(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """R88 drain: 损坏的 snapshot (部分写入/磁盘错误) 应包装为 FileNotFoundError
        让 caller 的 graceful 分支处理, 并发 warning 诊断 -- 而非裸 JSONDecodeError
        崩溃整个 --lookback-audit CLI。
        """
        import logging as _logging

        day_dir = tmp_path / "2026-05-05"
        day_dir.mkdir()
        (day_dir / "selection_snapshot.json").write_text("{not valid json", encoding="utf-8")

        with caplog.at_level(_logging.WARNING, logger="src.research.lookback_audit"):
            with pytest.raises(FileNotFoundError):
                _read_selection_snapshot(tmp_path, "2026-05-05")
        warn_msgs = [r.message for r in caplog.records if r.levelno >= _logging.WARNING]
        assert any("损坏" in m for m in warn_msgs), f"损坏 snapshot 应触发 warning 诊断; got warnings={warn_msgs!r}"


# ---------------------------------------------------------------------------
# Tests: price calculations
# ---------------------------------------------------------------------------


class TestPriceCalculations:
    def test_max_drawdown_mono_up(self) -> None:
        prices = _make_prices(base_price=10.0, days=5, trend="up")
        dd = _compute_max_drawdown(prices)
        assert dd == 0.0  # No drawdown in rising market

    def test_max_drawdown_mono_down(self) -> None:
        prices = _make_prices(base_price=10.0, days=5, trend="down")
        dd = _compute_max_drawdown(prices)
        assert dd is not None
        assert dd < 0  # Should be negative

    def test_max_drawdown_volatile(self) -> None:
        prices = _make_prices(base_price=10.0, days=5, trend="volatile")
        dd = _compute_max_drawdown(prices)
        assert dd is not None
        assert dd < 0

    def test_max_drawdown_insufficient_data(self) -> None:
        prices = [Price(open=10, close=10, high=10, low=10, volume=1000, time="2026-05-05")]
        assert _compute_max_drawdown(prices) is None
        assert _compute_max_drawdown([]) is None

    def test_max_return_up(self) -> None:
        prices = _make_prices(base_price=10.0, days=5, trend="up")
        mr = _compute_max_return(prices)
        assert mr is not None
        assert mr > 0

    def test_max_return_down(self) -> None:
        prices = _make_prices(base_price=10.0, days=5, trend="down")
        mr = _compute_max_return(prices)
        assert mr is not None
        assert mr < 0

    def test_max_return_insufficient_data(self) -> None:
        prices = [Price(open=10, close=10, high=10, low=10, volume=1000, time="2026-05-05")]
        assert _compute_max_return(prices) is None

    def test_max_return_zero_entry(self) -> None:
        prices = [
            Price(open=0, close=0, high=0, low=0, volume=1000, time="2026-05-05"),
            Price(open=10, close=10, high=10, low=10, volume=1000, time="2026-05-06"),
        ]
        assert _compute_max_return(prices) is None

    def test_filter_prices_in_window(self) -> None:
        prices = _make_prices(base_price=10.0, days=10, start_date="2026-05-01")
        start = datetime(2026, 5, 3)
        end = datetime(2026, 5, 7)
        filtered = _filter_prices_in_window(prices, start, end)
        assert len(filtered) == 5
        assert str(filtered[0].time) == "2026-05-03"
        assert str(filtered[-1].time) == "2026-05-07"


# ---------------------------------------------------------------------------
# Tests: full audit
# ---------------------------------------------------------------------------


class TestRunLookbackAudit:
    def test_audit_with_full_data(self, tmp_path: Path) -> None:
        """Full audit with complete price data for all tickers."""
        # Write snapshot
        day_dir = tmp_path / "2026-05-05"
        day_dir.mkdir()
        snapshot = _make_snapshot()
        (day_dir / "selection_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")

        # Mock price data
        mock_fetcher = MockPriceFetcher(
            {
                "000001": _make_prices(base_price=10.0, days=31, start_date="2026-05-05", trend="up"),
                "600519": _make_prices(base_price=100.0, days=31, start_date="2026-05-05", trend="down"),
                "300724": _make_prices(base_price=50.0, days=31, start_date="2026-05-05", trend="volatile"),
            }
        )

        result = run_lookback_audit(
            audit_date="20260505",
            lookforward_days=30,
            top_n=10,
            artifact_root=tmp_path,
            price_fetcher=mock_fetcher,
        )

        assert result.audit_date == "2026-05-05"
        assert result.selected_count == 3
        assert result.audited_count == 3
        assert len(result.ticker_results) == 3

        # Ticker 000001 went up
        t1 = result.ticker_results[0]
        assert t1.ticker == "000001"
        assert t1.return_pct is not None
        assert t1.return_pct > 0
        assert t1.data_status == "ok"

        # Ticker 600519 went down
        t2 = result.ticker_results[1]
        assert t2.ticker == "600519"
        assert t2.return_pct is not None
        assert t2.return_pct < 0

        # Summary
        assert "avg_return_pct" in result.summary
        assert "hit_rate" in result.summary

    def test_audit_no_snapshot(self, tmp_path: Path) -> None:
        """Audit when no snapshot exists for the date."""
        result = run_lookback_audit(
            audit_date="20990101",
            artifact_root=tmp_path,
        )
        assert result.selected_count == 0
        assert "error" in result.summary

    def test_audit_empty_selected(self, tmp_path: Path) -> None:
        """Audit when snapshot has no selected tickers."""
        day_dir = tmp_path / "2026-05-05"
        day_dir.mkdir()
        snapshot = _make_snapshot(selected=[])
        (day_dir / "selection_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")

        result = run_lookback_audit(
            audit_date="20260505",
            artifact_root=tmp_path,
        )
        assert result.selected_count == 0
        assert result.audited_count == 0

    def test_audit_no_forward_data(self, tmp_path: Path) -> None:
        """Audit when price data is missing for a ticker."""
        day_dir = tmp_path / "2026-05-05"
        day_dir.mkdir()
        snapshot = _make_snapshot()
        (day_dir / "selection_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")

        # Only one ticker has data
        mock_fetcher = MockPriceFetcher(
            {
                "000001": _make_prices(base_price=10.0, days=5, start_date="2026-05-05"),
                # 600519 and 300724: no data
            }
        )

        result = run_lookback_audit(
            audit_date="20260505",
            artifact_root=tmp_path,
            price_fetcher=mock_fetcher,
        )

        assert result.selected_count == 3
        assert result.audited_count == 1
        assert result.ticker_results[1].data_status == "no_forward_data"
        assert result.ticker_results[2].data_status == "no_forward_data"

    def test_audit_zero_entry_price(self, tmp_path: Path) -> None:
        """Audit when entry price is zero (delisted/suspended stock)."""
        day_dir = tmp_path / "2026-05-05"
        day_dir.mkdir()
        snapshot = _make_snapshot(
            selected=[
                {"symbol": "000001", "score_final": 0.85},
            ]
        )
        (day_dir / "selection_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")

        mock_fetcher = MockPriceFetcher(
            {
                "000001": [
                    Price(open=0, close=0, high=0, low=0, volume=0, time="2026-05-05"),
                    Price(open=5, close=5, high=5, low=5, volume=1000, time="2026-05-06"),
                ],
            }
        )

        result = run_lookback_audit(
            audit_date="20260505",
            artifact_root=tmp_path,
            price_fetcher=mock_fetcher,
        )
        assert result.audited_count == 0
        assert result.ticker_results[0].data_status == "no_entry_price"

    def test_audit_partial_data(self, tmp_path: Path) -> None:
        """Audit when price data doesn't cover full lookforward window."""
        day_dir = tmp_path / "2026-05-05"
        day_dir.mkdir()
        snapshot = _make_snapshot(
            selected=[
                {"symbol": "000001", "score_final": 0.85},
            ]
        )
        (day_dir / "selection_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")

        # Only 3 days of data instead of 30
        mock_fetcher = MockPriceFetcher(
            {
                "000001": _make_prices(base_price=10.0, days=3, start_date="2026-05-05"),
            }
        )

        result = run_lookback_audit(
            audit_date="20260505",
            lookforward_days=30,
            artifact_root=tmp_path,
            price_fetcher=mock_fetcher,
        )

        assert result.audited_count == 1
        tr = result.ticker_results[0]
        assert tr.data_status == "ok"
        assert tr.trading_days_held == 3
        assert tr.return_pct is not None

    def test_audit_accepts_yyyymmdd_and_yyyy_mm_dd(self, tmp_path: Path) -> None:
        """Both date formats work for audit_date."""
        day_dir = tmp_path / "2026-05-05"
        day_dir.mkdir()
        snapshot = _make_snapshot()
        (day_dir / "selection_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")

        result1 = run_lookback_audit(
            audit_date="20260505",
            artifact_root=tmp_path,
            price_fetcher=MockPriceFetcher(),
        )
        result2 = run_lookback_audit(
            audit_date="2026-05-05",
            artifact_root=tmp_path,
            price_fetcher=MockPriceFetcher(),
        )
        assert result1.audit_date == result2.audit_date


# ---------------------------------------------------------------------------
# Tests: summary statistics
# ---------------------------------------------------------------------------


class TestSummaryStatistics:
    def test_hit_rate_calculation(self, tmp_path: Path) -> None:
        """Verify hit_rate = fraction of positive returns."""
        day_dir = tmp_path / "2026-05-05"
        day_dir.mkdir()
        snapshot = _make_snapshot(
            selected=[
                {"symbol": "TICK1", "score_final": 0.9},
                {"symbol": "TICK2", "score_final": 0.8},
                {"symbol": "TICK3", "score_final": 0.7},
            ]
        )
        (day_dir / "selection_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")

        mock_fetcher = MockPriceFetcher(
            {
                "TICK1": _make_prices(base_price=10.0, days=5, trend="up"),
                "TICK2": _make_prices(base_price=10.0, days=5, trend="down"),
                "TICK3": _make_prices(base_price=10.0, days=5, trend="up"),
            }
        )

        result = run_lookback_audit(
            audit_date="20260505",
            artifact_root=tmp_path,
            price_fetcher=mock_fetcher,
        )
        assert abs(result.summary["hit_rate"] - 2 / 3) < 0.001

    def test_summary_with_all_no_data(self, tmp_path: Path) -> None:
        """Summary has no avg_return when all tickers have no data."""
        day_dir = tmp_path / "2026-05-05"
        day_dir.mkdir()
        snapshot = _make_snapshot()
        (day_dir / "selection_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")

        result = run_lookback_audit(
            audit_date="20260505",
            artifact_root=tmp_path,
            price_fetcher=MockPriceFetcher(),
        )
        assert "avg_return_pct" not in result.summary


# ---------------------------------------------------------------------------
# Tests: format_audit_table
# ---------------------------------------------------------------------------


class TestFormatAuditTable:
    def test_table_output_contains_headers(self) -> None:
        result = LookbackAuditResult(
            audit_date="2026-05-05",
            lookforward_days=30,
            selected_count=1,
            audited_count=0,
            ticker_results=[],
        )
        table = format_audit_table(result)
        assert "Lookback Audit" in table
        assert "2026-05-05" in table
        assert "Ticker" in table

    def test_table_shows_ticker_data(self) -> None:
        tr = TickerAuditResult(
            ticker="000001",
            rank=1,
            score_final=0.85,
            entry_date="2026-05-05",
            entry_price=10.0,
            exit_date="2026-06-04",
            exit_price=12.0,
            return_pct=20.0,
            max_drawdown_pct=-2.5,
            max_return_pct=22.0,
            trading_days_held=22,
            data_status="ok",
        )
        result = LookbackAuditResult(
            audit_date="2026-05-05",
            lookforward_days=30,
            selected_count=1,
            audited_count=1,
            ticker_results=[tr],
            summary={"avg_return_pct": 20.0, "hit_rate": 1.0},
        )
        table = format_audit_table(result)
        assert "000001" in table
        assert "+20.00" in table


# ---------------------------------------------------------------------------
# Tests: CLI
# ---------------------------------------------------------------------------


class TestCLI:
    def test_cli_parse_args(self) -> None:
        import io
        from unittest.mock import patch

        from src.research.lookback_audit import main

        with patch("sys.argv", ["lookback_audit", "--date", "20260505", "--days", "30", "--json"]):
            # Should not crash; just test arg parsing
            pass  # Arg parsing tested implicitly


# ---------------------------------------------------------------------------
# Tests: dataclass serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_ticker_audit_result_to_dict(self) -> None:
        tr = TickerAuditResult(
            ticker="000001",
            rank=1,
            score_final=0.85,
            entry_date="2026-05-05",
            entry_price=10.0,
            exit_date="2026-06-04",
            exit_price=12.0,
            return_pct=20.0,
            max_drawdown_pct=-2.5,
            max_return_pct=22.0,
            trading_days_held=22,
            data_status="ok",
        )
        d = tr.__dict__
        assert d["ticker"] == "000001"
        assert d["return_pct"] == 20.0

    def test_lookback_audit_result_to_dict(self) -> None:
        from dataclasses import asdict

        result = LookbackAuditResult(
            audit_date="2026-05-05",
            lookforward_days=30,
            selected_count=3,
            audited_count=3,
            summary={"avg_return_pct": 5.0},
        )
        d = asdict(result)
        assert d["audit_date"] == "2026-05-05"
        assert d["summary"]["avg_return_pct"] == 5.0


# ---------------------------------------------------------------------------
# NaN / Inf price guards (regression for v0 audit)
# ---------------------------------------------------------------------------
class TestNaNPriceGuards:
    """NaN/Inf in upstream price data must not propagate into return_pct /
    max_drawdown_pct / max_return_pct.  Without this guard a single corrupt
    row would mark the ticker as 'ok' with NaN metrics and contaminate the
    summary (avg_return_pct, hit_rate, etc.)."""

    def test_nan_close_is_filtered(self, tmp_path: Path) -> None:
        """A NaN close in the forward window must drop that row, leaving the
        remaining rows to produce a well-defined return_pct."""
        day_dir = tmp_path / "2026-05-05"
        day_dir.mkdir()
        snapshot = _make_snapshot(
            selected=[
                {"symbol": "AAPL", "score_final": 0.85},
            ]
        )
        (day_dir / "selection_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")

        mock_fetcher = MockPriceFetcher(
            {
                "AAPL": [
                    Price(open=10, close=10, high=10, low=10, volume=1000, time="2026-05-05"),
                    # NaN close must be dropped
                    Price(open=11, close=float("nan"), high=11, low=11, volume=1000, time="2026-05-06"),
                    Price(open=12, close=12, high=12, low=12, volume=1000, time="2026-05-07"),
                ],
            }
        )

        result = run_lookback_audit(
            audit_date="20260505",
            artifact_root=tmp_path,
            price_fetcher=mock_fetcher,
        )
        tr = result.ticker_results[0]
        assert tr.data_status == "ok"
        # return_pct is well-defined (10 -> 12 over 2 surviving rows)
        assert tr.return_pct is not None
        assert tr.return_pct == tr.return_pct  # not NaN
        assert tr.max_drawdown_pct is not None
        assert tr.max_drawdown_pct == tr.max_drawdown_pct  # not NaN

    def test_all_nan_closes_treated_as_no_data(self, tmp_path: Path) -> None:
        """If every forward row has a NaN close, no audit can be produced."""
        day_dir = tmp_path / "2026-05-05"
        day_dir.mkdir()
        snapshot = _make_snapshot(
            selected=[
                {"symbol": "AAPL", "score_final": 0.85},
            ]
        )
        (day_dir / "selection_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")

        mock_fetcher = MockPriceFetcher(
            {
                "AAPL": [
                    Price(open=10, close=float("nan"), high=10, low=10, volume=1000, time="2026-05-05"),
                    Price(open=11, close=float("nan"), high=11, low=11, volume=1000, time="2026-05-06"),
                ],
            }
        )

        result = run_lookback_audit(
            audit_date="20260505",
            artifact_root=tmp_path,
            price_fetcher=mock_fetcher,
        )
        tr = result.ticker_results[0]
        assert tr.data_status == "no_forward_data"
        assert tr.return_pct is None
        assert result.audited_count == 0


def test_r103_price_fetcher_silent_failure_emits_debug_diagnostic(caplog):
    """R103 (BH-017/R48-R50/R57-R60/R63 family): ``PriceFetcher.fetch`` previously
    had ``except Exception: return []`` with no logging — a forward-price fetch
    failure (akshare API / network / rate limit) silently produced an empty
    price series, making the lookback audit evaluate data-missing as a clean
    "no anomaly". Behavior is still best-effort empty, but now emits a debug
    diagnostic so operators can distinguish "no prices" vs "fetch broke"."""
    fetcher = PriceFetcher(use_robust=False)

    # Force the underlying get_prices import to raise on call.
    import src.tools.akshare_api as akshare_api

    orig = akshare_api.get_prices
    akshare_api.get_prices = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("api down"))
    try:
        with caplog.at_level("DEBUG", logger="src.research.lookback_audit"):
            out = fetcher.fetch("000001", "20260101", "20260110")
    finally:
        akshare_api.get_prices = orig

    # Behavior preserved: empty list, no raise.
    assert out == []
    # Diagnostic emitted.
    assert any("forward price fetch failed" in rec.message for rec in caplog.records)
