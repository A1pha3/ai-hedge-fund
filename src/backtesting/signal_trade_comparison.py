"""Signal vs actual trade comparison layer for backtesting replay.

Aligns strategy signals with executed trades on a per-ticker, per-date
basis and computes slippage, fill delay, and fill-rate statistics.

Typical usage::

    from src.backtesting.signal_trade_comparison import compare_signals_to_trades

    result = compare_signals_to_trades(
        signals=[...],
        trades=[...],
        time_window_days=1,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any, Sequence

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class FillStatus(StrEnum):
    """Match status for a signal."""

    FILLED = "filled"
    PARTIAL = "partial"
    MISSED = "missed"


class SignalDirection(StrEnum):
    """Signal direction."""

    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class Signal:
    """A strategy signal emitted by the backtesting engine.

    Attributes:
        ticker: Stock ticker.
        date: Date the signal was generated (YYYY-MM-DD or datetime).
        direction: BUY or SELL.
        price: The reference price at signal time.
        quantity: Intended quantity (shares). 0 means "unspecified".
        metadata: Arbitrary extra context (agent name, score, etc.).
    """

    ticker: str
    date: str | datetime | date
    direction: SignalDirection
    price: float
    quantity: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def date_str(self) -> str:
        if isinstance(self.date, datetime):
            return self.date.strftime("%Y-%m-%d")
        if isinstance(self.date, date):
            return self.date.isoformat()
        return str(self.date)


@dataclass(frozen=True)
class Trade:
    """An executed trade recorded by the backtester.

    Attributes:
        ticker: Stock ticker.
        date: Execution date (YYYY-MM-DD or datetime).
        direction: BUY or SELL.
        price: Actual fill price.
        quantity: Executed quantity (shares).
        metadata: Arbitrary extra context (slippage diagnostics, etc.).
    """

    ticker: str
    date: str | datetime | date
    direction: SignalDirection
    price: float
    quantity: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def date_str(self) -> str:
        if isinstance(self.date, datetime):
            return self.date.strftime("%Y-%m-%d")
        if isinstance(self.date, date):
            return self.date.isoformat()
        return str(self.date)


@dataclass(frozen=True)
class MatchedPair:
    """Result of aligning one signal to its best matching trade.

    Attributes:
        signal: The original signal.
        trade: The matched trade, or None if no match found.
        status: filled / partial / missed.
        price_diff: trade.price - signal.price.
            For BUY signals, a positive value means unfavorable slippage.
            For SELL signals, a negative value means unfavorable slippage.
        price_diff_pct: price_diff expressed as a percentage of signal.price.
        delay_days: Calendar days between signal date and trade date.
            0 = same-day fill.
    """

    signal: Signal
    trade: Trade | None
    status: FillStatus
    price_diff: float
    price_diff_pct: float
    delay_days: int


@dataclass
class ComparisonSummary:
    """Aggregate statistics across all matched pairs.

    All numeric fields default to 0.0 so that an empty comparison still
    serializes cleanly.
    """

    total_signals: int = 0
    filled_count: int = 0
    partial_count: int = 0
    missed_count: int = 0
    fill_rate: float = 0.0
    avg_price_diff: float = 0.0
    avg_price_diff_pct: float = 0.0
    avg_delay_days: float = 0.0
    max_delay_days: int = 0
    min_delay_days: int = 0
    # Slippage broken out by direction
    avg_buy_slippage: float = 0.0
    avg_sell_slippage: float = 0.0


@dataclass
class ComparisonResult:
    """Full output of a signal-vs-trade comparison.

    Attributes:
        pairs: One entry per signal, in the order the signals were provided.
        summary: Aggregate statistics.
    """

    pairs: list[MatchedPair]
    summary: ComparisonSummary


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------


def _parse_date(value: str | datetime | date) -> date:
    """Normalise a date-like value to a Python ``date``."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _compute_price_diff(
    signal: Signal,
    trade: Trade,
) -> tuple[float, float]:
    """Return (price_diff, price_diff_pct).

    For BUY signals the slippage is ``trade.price - signal.price`` (positive =
    unfavorable).  For SELL signals it is ``signal.price - trade.price``
    (positive = unfavorable).  This makes the sign convention consistent:
    positive always means "worse than the signal price".

    Both inputs are expected to be finite real numbers.  When either side
    is NaN/Inf the slippage is meaningless, so we return 0.0 for both
    fields rather than silently propagating a non-finite value into the
    summary statistics.
    """
    sig_price = signal.price
    trd_price = trade.price
    if not (isinstance(sig_price, (int, float)) and sig_price == sig_price and abs(sig_price) != float('inf')):
        return 0.0, 0.0
    if not (isinstance(trd_price, (int, float)) and trd_price == trd_price and abs(trd_price) != float('inf')):
        return 0.0, 0.0

    if signal.direction == SignalDirection.BUY:
        diff = trd_price - sig_price
    else:
        diff = sig_price - trd_price
    pct = (diff / sig_price) if abs(sig_price) > 1e-12 else 0.0
    return diff, pct


def _best_match(
    signal: Signal,
    trades_by_ticker: dict[str, list[Trade]],
    time_window_days: int,
    consumed_trade_keys: set[tuple[str, int]],
) -> tuple[Trade | None, FillStatus, int]:
    """Find the best matching trade for a single signal.

    Strategy:
      1. Filter trades by same ticker, same direction, within time window.
      2. Prefer the trade closest in time (minimum delay).
      3. Among ties, prefer closest price.
    """
    candidates = trades_by_ticker.get(signal.ticker, [])
    signal_dt = _parse_date(signal.date)
    window_start = signal_dt
    window_end = signal_dt + timedelta(days=time_window_days)

    scored: list[tuple[int, Trade, int, float]] = []
    for idx, trade in enumerate(candidates):
        if (signal.ticker, idx) in consumed_trade_keys:
            continue
        if trade.direction != signal.direction:
            continue
        trade_dt = _parse_date(trade.date)
        if trade_dt < window_start or trade_dt > window_end:
            continue
        delay = (trade_dt - signal_dt).days
        price_dist = abs(trade.price - signal.price)
        scored.append((idx, trade, delay, price_dist))

    if not scored:
        return None, FillStatus.MISSED, 0

    # Sort by (delay, price_distance) to pick the closest-in-time, then closest-price
    scored.sort(key=lambda t: (t[2], t[3]))
    best_idx, best_trade, delay, _ = scored[0]
    consumed_trade_keys.add((signal.ticker, best_idx))

    # Determine fill status
    if signal.quantity > 0 and best_trade.quantity < signal.quantity:
        status = FillStatus.PARTIAL
    else:
        status = FillStatus.FILLED

    return best_trade, status, delay


def compare_signals_to_trades(
    signals: Sequence[Signal],
    trades: Sequence[Trade],
    time_window_days: int = 1,
) -> ComparisonResult:
    """Align signals to trades and compute comparison metrics.

    Args:
        signals: Strategy signals in chronological order.
        trades: Executed trades in chronological order.
        time_window_days: Maximum calendar days between signal and trade
            for them to be considered a match.  Default 1 means same-day
            or next-day fills only.

    Returns:
        A ``ComparisonResult`` with per-signal matched pairs and aggregate
        summary statistics.
    """
    # Index trades by ticker for O(N*M) matching
    trades_by_ticker: dict[str, list[Trade]] = {}
    for trade in trades:
        trades_by_ticker.setdefault(trade.ticker, []).append(trade)

    consumed: set[tuple[str, int]] = set()
    pairs: list[MatchedPair] = []

    for signal in signals:
        matched_trade, status, delay = _best_match(
            signal,
            trades_by_ticker,
            time_window_days,
            consumed,
        )

        if matched_trade is not None:
            price_diff, price_diff_pct = _compute_price_diff(signal, matched_trade)
        else:
            price_diff = 0.0
            price_diff_pct = 0.0

        pairs.append(
            MatchedPair(
                signal=signal,
                trade=matched_trade,
                status=status,
                price_diff=round(price_diff, 6),
                price_diff_pct=round(price_diff_pct, 6),
                delay_days=delay,
            )
        )

    summary = _build_summary(pairs)
    return ComparisonResult(pairs=pairs, summary=summary)


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------


def _build_summary(pairs: list[MatchedPair]) -> ComparisonSummary:
    """Aggregate statistics from a list of matched pairs."""
    total = len(pairs)
    if total == 0:
        return ComparisonSummary()

    filled = [p for p in pairs if p.status == FillStatus.FILLED]
    partial = [p for p in pairs if p.status == FillStatus.PARTIAL]
    missed = [p for p in pairs if p.status == FillStatus.MISSED]
    matched = filled + partial  # trades that actually happened

    fill_rate = len(matched) / total if total else 0.0

    if matched:
        avg_price_diff = sum(p.price_diff for p in matched) / len(matched)
        avg_price_diff_pct = sum(p.price_diff_pct for p in matched) / len(matched)
        delays = [p.delay_days for p in matched]
        avg_delay = sum(delays) / len(delays)
        max_delay = max(delays)
        min_delay = min(delays)
    else:
        avg_price_diff = 0.0
        avg_price_diff_pct = 0.0
        avg_delay = 0.0
        max_delay = 0
        min_delay = 0

    # Direction-specific slippage
    buy_matched = [p for p in matched if p.signal.direction == SignalDirection.BUY]
    sell_matched = [p for p in matched if p.signal.direction == SignalDirection.SELL]
    avg_buy_slippage = sum(p.price_diff for p in buy_matched) / len(buy_matched) if buy_matched else 0.0
    avg_sell_slippage = sum(p.price_diff for p in sell_matched) / len(sell_matched) if sell_matched else 0.0

    return ComparisonSummary(
        total_signals=total,
        filled_count=len(filled),
        partial_count=len(partial),
        missed_count=len(missed),
        fill_rate=round(fill_rate, 6),
        avg_price_diff=round(avg_price_diff, 6),
        avg_price_diff_pct=round(avg_price_diff_pct, 6),
        avg_delay_days=round(avg_delay, 2),
        max_delay_days=max_delay,
        min_delay_days=min_delay,
        avg_buy_slippage=round(avg_buy_slippage, 6),
        avg_sell_slippage=round(avg_sell_slippage, 6),
    )


# ---------------------------------------------------------------------------
# Conversion helpers (from backtest event payloads / results)
# ---------------------------------------------------------------------------


def signals_from_event_payload(
    events: Sequence[dict[str, Any]],
) -> list[Signal]:
    """Extract signals from backtest event payloads (JSONL records).

    Each event is expected to have the structure produced by
    ``build_pipeline_event_payload`` or ``build_backtest_day_result``,
    with keys like ``decisions``, ``current_prices``, ``trade_date``.

    A signal is inferred whenever a decision has an action of "buy" or "sell"
    (not "hold") and a non-zero quantity.
    """
    signals: list[Signal] = []
    for event in events:
        trade_date_raw = event.get("trade_date") or event.get("date", "")
        if not trade_date_raw:
            continue
        # Normalize YYYYMMDD -> YYYY-MM-DD
        trade_date_str = str(trade_date_raw)
        if len(trade_date_str) == 8 and trade_date_str.isdigit():
            trade_date_str = f"{trade_date_str[:4]}-{trade_date_str[4:6]}-{trade_date_str[6:8]}"

        decisions = event.get("decisions", {})
        current_prices = event.get("current_prices", {})
        executed_trades = event.get("executed_trades", {})

        for ticker, decision in decisions.items():
            action = str(decision.get("action", "hold")).lower()
            if action not in ("buy", "sell"):
                continue
            price = float(current_prices.get(ticker, 0.0))
            if price <= 0:
                continue
            quantity = int(executed_trades.get(ticker, 0))
            direction = SignalDirection.BUY if action == "buy" else SignalDirection.SELL
            signals.append(
                Signal(
                    ticker=ticker,
                    date=trade_date_str,
                    direction=direction,
                    price=price,
                    quantity=quantity,
                )
            )
    return signals


def trades_from_event_payload(
    events: Sequence[dict[str, Any]],
) -> list[Trade]:
    """Extract executed trades from backtest event payloads (JSONL records).

    A trade is recorded whenever ``executed_trades[ticker] > 0`` and
    the corresponding decision action is "buy" or "sell".
    """
    trades: list[Trade] = []
    for event in events:
        trade_date_raw = event.get("trade_date") or event.get("date", "")
        if not trade_date_raw:
            continue
        trade_date_str = str(trade_date_raw)
        if len(trade_date_str) == 8 and trade_date_str.isdigit():
            trade_date_str = f"{trade_date_str[:4]}-{trade_date_str[4:6]}-{trade_date_str[6:8]}"

        decisions = event.get("decisions", {})
        current_prices = event.get("current_prices", {})
        executed_trades = event.get("executed_trades", {})

        for ticker, qty in executed_trades.items():
            qty_int = int(qty) if qty else 0
            if qty_int == 0:
                continue
            action = str(decisions.get(ticker, {}).get("action", "hold")).lower()
            if action not in ("buy", "sell"):
                continue
            price = float(current_prices.get(ticker, 0.0))
            direction = SignalDirection.BUY if action == "buy" else SignalDirection.SELL
            trades.append(
                Trade(
                    ticker=ticker,
                    date=trade_date_str,
                    direction=direction,
                    price=price,
                    quantity=qty_int,
                )
            )
    return trades


# ---------------------------------------------------------------------------
# Convenience: run comparison directly from raw event payloads
# ---------------------------------------------------------------------------


def compare_from_events(
    events: Sequence[dict[str, Any]],
    time_window_days: int = 1,
) -> ComparisonResult:
    """One-call convenience: extract signals + trades from events and compare.

    Args:
        events: Sequence of event payload dicts as stored in backtest JSONL
            timing / event logs or web-backend SSE results.
        time_window_days: Match window (default 1).

    Returns:
        ``ComparisonResult`` with matched pairs and summary.
    """
    signals = signals_from_event_payload(events)
    trades = trades_from_event_payload(events)
    return compare_signals_to_trades(signals, trades, time_window_days=time_window_days)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def matched_pair_to_dict(pair: MatchedPair) -> dict[str, Any]:
    """Convert a MatchedPair to a JSON-friendly dict."""
    return {
        "status": str(pair.status),
        "signal": {
            "ticker": pair.signal.ticker,
            "date": pair.signal.date_str(),
            "direction": str(pair.signal.direction),
            "price": pair.signal.price,
            "quantity": pair.signal.quantity,
            **pair.signal.metadata,
        },
        "trade": (
            {
                "ticker": pair.trade.ticker,
                "date": pair.trade.date_str(),
                "direction": str(pair.trade.direction),
                "price": pair.trade.price,
                "quantity": pair.trade.quantity,
                **pair.trade.metadata,
            }
            if pair.trade is not None
            else None
        ),
        "price_diff": pair.price_diff,
        "price_diff_pct": pair.price_diff_pct,
        "delay_days": pair.delay_days,
    }


def summary_to_dict(summary: ComparisonSummary) -> dict[str, Any]:
    """Convert a ComparisonSummary to a JSON-friendly dict."""
    return {
        "total_signals": summary.total_signals,
        "filled_count": summary.filled_count,
        "partial_count": summary.partial_count,
        "missed_count": summary.missed_count,
        "fill_rate": summary.fill_rate,
        "avg_price_diff": summary.avg_price_diff,
        "avg_price_diff_pct": summary.avg_price_diff_pct,
        "avg_delay_days": summary.avg_delay_days,
        "max_delay_days": summary.max_delay_days,
        "min_delay_days": summary.min_delay_days,
        "avg_buy_slippage": summary.avg_buy_slippage,
        "avg_sell_slippage": summary.avg_sell_slippage,
    }


def comparison_result_to_dict(result: ComparisonResult) -> dict[str, Any]:
    """Full serialisation of a ComparisonResult."""
    return {
        "pairs": [matched_pair_to_dict(p) for p in result.pairs],
        "summary": summary_to_dict(result.summary),
    }
