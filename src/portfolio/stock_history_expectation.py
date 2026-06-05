"""Per-ticker historical expectation (Feature 2.1 in feature-proposals.md).

Computes the empirical win rate / average return / worst return / best return
of a single ticker under a given trading history. The result lets a user
answer "if I had been running this strategy on this stock over the last
N days, what would I have expected to see?" — a core v1.4 framework §8.2
metric that was previously only available at the portfolio level inside
the backtest engine.

Inputs are trade rows in the canonical shape produced by BTST early-runner
history and the walk-forward backtests:

    {
        "ticker": str,
        "trade_date": "YYYY-MM-DD",
        "entry_status": "filled" | "unfilled" | ...,
        "next_close_return_after_cost": float | None,
    }

Filtering:
- ``ticker`` must match exactly.
- ``entry_status`` must be "filled" (unfilled rows have no real return).
- ``trade_date`` must fall within ``[as_of_date - lookback_days, as_of_date]``.

Small-sample guard:
- v1.4 framework §7.1 marks a strategy "unreliable" with < 5 observations.
  When ``n_filled_in_window < min_sample`` (default 5), the function returns
  ``None`` for win_rate/avg/worst/best and sets ``is_small_sample=True``.

Output:
    StockHistoryExpectation — a frozen dataclass. Returned for every
    invocation; callers should check ``is_small_sample`` before
    presenting the numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class StockHistoryExpectation:
    """Empirical per-ticker performance over a recent lookback window.

    Attributes:
        ticker: the ticker the expectation is for.
        n_trades: number of filled trades in the lookback window.
        win_rate: fraction of trades with positive return, or None if
            the sample is too small to be reliable.
        avg_30d_return: mean of next_close_return_after_cost over the
            sample, or None if too small.
        worst_30d_return: minimum (most negative) return, or None if
            too small. If all trades won, this is the smallest positive.
        best_30d_return: maximum (most positive) return, or None if
            too small. If all trades lost, this is the largest negative.
        is_small_sample: True when n_trades < min_sample; caller should
            present an explicit warning to the user.
        lookback_days: window size in calendar days.
        period_start: ISO date of the earliest included trade.
        period_end: ISO date of the latest included trade (== as_of_date
            or the latest trade_date in the data, whichever is earlier).
    """

    ticker: str
    n_trades: int
    win_rate: float | None
    avg_30d_return: float | None
    worst_30d_return: float | None
    best_30d_return: float | None
    is_small_sample: bool
    lookback_days: int
    period_start: str
    period_end: str


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


def _filter_window(
    ticker: str,
    trade_rows: list[dict],
    as_of: datetime,
    lookback_days: int,
) -> tuple[list[float], str, str]:
    """Return (list of returns in window, period_start, period_end)."""
    cutoff = as_of - timedelta(days=lookback_days)
    in_window: list[tuple[datetime, float]] = []
    for row in trade_rows:
        if str(row.get("ticker") or "") != ticker:
            continue
        if str(row.get("entry_status") or "") != "filled":
            continue
        ret = row.get("next_close_return_after_cost")
        if ret is None:
            continue
        try:
            trade_date = _parse_date(str(row.get("trade_date") or ""))
        except ValueError:
            continue
        if not (cutoff <= trade_date <= as_of):
            continue
        in_window.append((trade_date, float(ret)))
    in_window.sort(key=lambda item: item[0])
    if not in_window:
        return [], cutoff.strftime("%Y-%m-%d"), as_of.strftime("%Y-%m-%d")
    returns = [ret for _, ret in in_window]
    period_start = in_window[0][0].strftime("%Y-%m-%d")
    period_end = in_window[-1][0].strftime("%Y-%m-%d")
    return returns, period_start, period_end


def compute_stock_history_expectation(
    ticker: str,
    trade_rows: list[dict],
    *,
    as_of_date: str | None = None,
    lookback_days: int = 60,
    min_sample: int = 5,
) -> StockHistoryExpectation:
    """Compute the per-ticker empirical performance summary.

    See module docstring for the input contract and small-sample guard.
    """
    if as_of_date is None:
        as_of = datetime.now()
    else:
        as_of = _parse_date(as_of_date)

    returns, period_start, period_end = _filter_window(
        ticker, trade_rows, as_of, lookback_days,
    )
    n = len(returns)
    is_small = n < min_sample

    if is_small:
        return StockHistoryExpectation(
            ticker=ticker,
            n_trades=n,
            win_rate=None,
            avg_30d_return=None,
            worst_30d_return=None,
            best_30d_return=None,
            is_small_sample=True,
            lookback_days=lookback_days,
            period_start=period_start,
            period_end=period_end,
        )

    wins = sum(1 for r in returns if r > 0)
    return StockHistoryExpectation(
        ticker=ticker,
        n_trades=n,
        win_rate=wins / n,
        avg_30d_return=sum(returns) / n,
        worst_30d_return=min(returns),
        best_30d_return=max(returns),
        is_small_sample=False,
        lookback_days=lookback_days,
        period_start=period_start,
        period_end=period_end,
    )
