"""Tests for src.portfolio.stock_history_expectation (Feature 2.1)."""

from __future__ import annotations

from src.portfolio.stock_history_expectation import (
    StockHistoryExpectation,
    compute_stock_history_expectation,
)


def _row(ticker: str, trade_date: str, return_after_cost: float, entry_status: str = "filled") -> dict:
    """Helper: build a trade row in the canonical dict shape produced by
    BTST early-runner history and the walk-forward backtests."""
    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "entry_status": entry_status,
        "next_close_return_after_cost": return_after_cost,
    }


# ---------------------------------------------------------------------------
# Happy path: a ticker with 10 winning trades in the lookback window
# ---------------------------------------------------------------------------

def test_expectation_basic_filled_trades_within_lookback():
    """10 filled trades within 60 days → win_rate=0.8, avg/worst computed."""
    rows = [
        _row("000001", "2026-01-05",  0.03),
        _row("000001", "2026-01-08", -0.01),
        _row("000001", "2026-01-12",  0.05),
        _row("000001", "2026-01-15",  0.02),
        _row("000001", "2026-01-19", -0.02),
        _row("000001", "2026-01-22",  0.04),
        _row("000001", "2026-01-26",  0.01),
        _row("000001", "2026-01-29", -0.03),
        _row("000001", "2026-02-02",  0.06),
        _row("000001", "2026-02-05",  0.02),
    ]
    result = compute_stock_history_expectation(
        "000001", rows, as_of_date="2026-02-10", lookback_days=60,
    )
    assert result.ticker == "000001"
    assert result.n_trades == 10
    # 7 winning (0.03, 0.05, 0.02, 0.04, 0.01, 0.06, 0.02) and 3 losing
    # (-0.01, -0.02, -0.03) → win_rate = 7/10 = 0.7
    assert abs(result.win_rate - 0.7) < 1e-9
    # avg = (0.03 - 0.01 + 0.05 + 0.02 - 0.02 + 0.04 + 0.01 - 0.03 + 0.06 + 0.02) / 10
    #     = 0.17 / 10 = 0.017
    assert abs(result.avg_30d_return - 0.017) < 1e-9
    assert result.worst_30d_return == -0.03
    assert result.best_30d_return == 0.06
    assert result.is_small_sample is False


# ---------------------------------------------------------------------------
# Small-sample guard: feature 2.1 explicitly says < 5 → warn
# ---------------------------------------------------------------------------

def test_expectation_flags_small_sample_below_min():
    """Fewer than 5 filled trades → win_rate/avg/worst are None and
    is_small_sample=True. This matches v1.4 framework §7.1 small-sample
    warning convention."""
    rows = [_row("000001", "2026-01-05", 0.03), _row("000001", "2026-01-10", -0.02)]
    result = compute_stock_history_expectation(
        "000001", rows, as_of_date="2026-02-10", lookback_days=60, min_sample=5,
    )
    assert result.n_trades == 2
    assert result.win_rate is None
    assert result.avg_30d_return is None
    assert result.worst_30d_return is None
    assert result.best_30d_return is None
    assert result.is_small_sample is True


def test_expectation_exactly_min_sample_is_not_small():
    """n_trades == min_sample is the boundary; the proposal says "样本 < 5"."""
    rows = [_row("000001", f"2026-01-{i:02d}", 0.01 * i) for i in range(1, 6)]
    result = compute_stock_history_expectation(
        "000001", rows, as_of_date="2026-02-10", lookback_days=60, min_sample=5,
    )
    assert result.n_trades == 5
    assert result.is_small_sample is False
    assert result.win_rate is not None


# ---------------------------------------------------------------------------
# Filtering: trades outside the lookback window must be excluded
# ---------------------------------------------------------------------------

def test_expectation_excludes_trades_outside_lookback_window():
    """Trades older than lookback_days before as_of_date are excluded."""
    rows = [
        _row("000001", "2025-10-01",  0.50),  # way outside 60-day window
        _row("000001", "2025-11-15",  0.40),  # outside
        _row("000001", "2026-01-05",  0.02),  # inside
        _row("000001", "2026-01-20",  0.04),  # inside
        _row("000001", "2026-02-01",  0.03),  # inside (added to clear min_sample)
        _row("000001", "2026-02-05",  0.01),  # inside
        _row("000001", "2026-02-09", -0.01),  # inside
    ]
    result = compute_stock_history_expectation(
        "000001", rows, as_of_date="2026-02-10", lookback_days=60,
    )
    assert result.n_trades == 5, "Should exclude the 2025-10/11 trades"
    # wins: 4 (0.02, 0.04, 0.03, 0.01), losses: 1 (-0.01) → win_rate = 0.8
    assert abs(result.win_rate - 0.8) < 1e-9
    # avg = (0.02 + 0.04 + 0.03 + 0.01 - 0.01) / 5 = 0.018
    assert abs(result.avg_30d_return - 0.018) < 1e-9


def test_expectation_excludes_other_tickers():
    """A row for a different ticker must not affect this ticker's stats."""
    rows = [
        _row("000001", "2026-01-05",  0.10),  # ours
        _row("600000", "2026-01-06", -0.50),  # another ticker
        _row("000001", "2026-01-20",  0.05),  # ours
        _row("000001", "2026-01-25",  0.04),  # ours
        _row("000001", "2026-02-02",  0.03),  # ours
        _row("000001", "2026-02-08",  0.02),  # ours
    ]
    result = compute_stock_history_expectation(
        "000001", rows, as_of_date="2026-02-10", lookback_days=60,
    )
    assert result.n_trades == 5
    assert result.worst_30d_return == 0.02  # the 600000 -0.50 must NOT be included
    assert result.best_30d_return == 0.10


# ---------------------------------------------------------------------------
# Unfilled rows: must be excluded (only filled trades count)
# ---------------------------------------------------------------------------

def test_expectation_excludes_unfilled_rows():
    """Unfilled rows have entry_status='unfilled' and no real return.
    They must not contribute to win_rate or avg."""
    rows = [
        _row("000001", "2026-01-05",  0.05, entry_status="filled"),
        _row("000001", "2026-01-10",  0.00, entry_status="unfilled"),
        _row("000001", "2026-01-15",  0.00, entry_status="unfilled"),
        _row("000001", "2026-01-20",  0.03, entry_status="filled"),
        _row("000001", "2026-01-25",  0.04, entry_status="filled"),
        _row("000001", "2026-02-01",  0.02, entry_status="filled"),
        _row("000001", "2026-02-05",  0.06, entry_status="filled"),
    ]
    result = compute_stock_history_expectation(
        "000001", rows, as_of_date="2026-02-10", lookback_days=60,
    )
    assert result.n_trades == 5  # only filled rows count
    # avg = (0.05 + 0.03 + 0.04 + 0.02 + 0.06) / 5 = 0.04
    assert abs(result.avg_30d_return - 0.04) < 1e-9


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_expectation_empty_input_returns_small_sample():
    """No rows at all → n_trades=0, all stats None, is_small_sample=True."""
    result = compute_stock_history_expectation(
        "000001", [], as_of_date="2026-02-10", lookback_days=60,
    )
    assert result.n_trades == 0
    assert result.is_small_sample is True
    assert result.win_rate is None


def test_expectation_all_winning_streak():
    """All wins → win_rate=1.0, worst_30d_return is the smallest positive."""
    rows = [_row("000001", f"2026-01-{i:02d}", 0.01) for i in range(1, 11)]
    result = compute_stock_history_expectation(
        "000001", rows, as_of_date="2026-02-10", lookback_days=60,
    )
    assert result.win_rate == 1.0
    assert result.worst_30d_return == 0.01  # smallest of the 10 positives


def test_expectation_all_losing_streak_win_rate_zero():
    """All losses → win_rate=0.0, best_30d_return is the largest negative."""
    rows = [_row("000001", f"2026-01-{i:02d}", -0.02) for i in range(1, 11)]
    result = compute_stock_history_expectation(
        "000001", rows, as_of_date="2026-02-10", lookback_days=60,
    )
    assert result.win_rate == 0.0
    assert result.best_30d_return == -0.02  # largest of the 10 negatives


def test_expectation_default_as_of_date_is_today():
    """If as_of_date is None, must use today's date. Test by passing rows
    that are very recent (today and yesterday) and verifying they are
    included under a 60-day window."""
    from datetime import datetime, timedelta
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    rows = [
        _row("000001", today, 0.05),
        _row("000001", yesterday, 0.03),
    ]
    result = compute_stock_history_expectation("000001", rows, lookback_days=60)
    assert result.n_trades == 2
