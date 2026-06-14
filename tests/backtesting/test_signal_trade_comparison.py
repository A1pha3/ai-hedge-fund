"""Tests for signal vs trade comparison layer."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.backtesting.signal_trade_comparison import (
    _build_summary,
    _compute_price_diff,
    _parse_date,
    compare_from_events,
    compare_signals_to_trades,
    comparison_result_to_dict,
    ComparisonResult,
    ComparisonSummary,
    FillStatus,
    matched_pair_to_dict,
    MatchedPair,
    Signal,
    SignalDirection,
    signals_from_event_payload,
    summary_to_dict,
    Trade,
    trades_from_event_payload,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def buy_signal_a() -> Signal:
    return Signal(
        ticker="000001",
        date="2026-01-05",
        direction=SignalDirection.BUY,
        price=10.00,
        quantity=100,
    )


@pytest.fixture()
def sell_signal_a() -> Signal:
    return Signal(
        ticker="000001",
        date="2026-01-10",
        direction=SignalDirection.SELL,
        price=11.00,
        quantity=100,
    )


@pytest.fixture()
def buy_trade_a() -> Trade:
    return Trade(
        ticker="000001",
        date="2026-01-05",
        direction=SignalDirection.BUY,
        price=10.05,
        quantity=100,
    )


@pytest.fixture()
def sell_trade_a() -> Trade:
    return Trade(
        ticker="000001",
        date="2026-01-10",
        direction=SignalDirection.SELL,
        price=10.90,
        quantity=100,
    )


# ===========================================================================
# 1. Date parsing
# ===========================================================================


class TestParseDate:
    def test_string_format(self) -> None:
        assert _parse_date("2026-01-05") == date(2026, 1, 5)

    def test_datetime_input(self) -> None:
        dt = datetime(2026, 3, 15, 10, 30)
        assert _parse_date(dt) == date(2026, 3, 15)

    def test_date_input(self) -> None:
        d = date(2026, 6, 1)
        assert _parse_date(d) == date(2026, 6, 1)

    def test_string_with_timestamp_prefix(self) -> None:
        assert _parse_date("2026-12-31T23:59:59") == date(2026, 12, 31)


# ===========================================================================
# 2. Price diff computation
# ===========================================================================


class TestComputePriceDiff:
    def test_buy_unfavorable_slippage(self, buy_signal_a: Signal, buy_trade_a: Trade) -> None:
        diff, pct = _compute_price_diff(buy_signal_a, buy_trade_a)
        assert diff == pytest.approx(0.05)
        assert pct == pytest.approx(0.005)

    def test_buy_favorable_slippage(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.00)
        trade = Trade(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=9.90, quantity=100)
        diff, pct = _compute_price_diff(sig, trade)
        assert diff == pytest.approx(-0.10)
        assert pct == pytest.approx(-0.01)

    def test_sell_unfavorable_slippage(self, sell_signal_a: Signal, sell_trade_a: Trade) -> None:
        diff, pct = _compute_price_diff(sell_signal_a, sell_trade_a)
        # signal=11.00, trade=10.90 -> diff = 11.00 - 10.90 = 0.10 (unfavorable)
        assert diff == pytest.approx(0.10)
        assert pct == pytest.approx(0.10 / 11.0)

    def test_sell_favorable_slippage(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.SELL, price=10.00)
        trade = Trade(ticker="A", date="2026-01-01", direction=SignalDirection.SELL, price=10.20, quantity=100)
        diff, pct = _compute_price_diff(sig, trade)
        assert diff == pytest.approx(-0.20)

    def test_zero_signal_price(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=0.0)
        trade = Trade(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=1.0, quantity=100)
        diff, pct = _compute_price_diff(sig, trade)
        assert pct == 0.0


# ===========================================================================
# 3. Perfect match (same day, same ticker, same direction)
# ===========================================================================


class TestPerfectMatch:
    def test_single_buy_signal_matches_trade(self, buy_signal_a: Signal, buy_trade_a: Trade) -> None:
        result = compare_signals_to_trades([buy_signal_a], [buy_trade_a])
        assert len(result.pairs) == 1
        pair = result.pairs[0]
        assert pair.status == FillStatus.FILLED
        assert pair.trade is not None
        assert pair.trade.price == 10.05
        assert pair.delay_days == 0
        assert pair.price_diff == pytest.approx(0.05)

    def test_single_sell_signal_matches_trade(self, sell_signal_a: Signal, sell_trade_a: Trade) -> None:
        result = compare_signals_to_trades([sell_signal_a], [sell_trade_a])
        assert result.pairs[0].status == FillStatus.FILLED
        assert result.pairs[0].delay_days == 0


# ===========================================================================
# 4. Partial fill
# ===========================================================================


class TestPartialFill:
    def test_signal_quantity_exceeds_trade_quantity(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=200)
        trade = Trade(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=50)
        result = compare_signals_to_trades([sig], [trade])
        assert result.pairs[0].status == FillStatus.PARTIAL
        assert result.summary.partial_count == 1
        assert result.summary.filled_count == 0


# ===========================================================================
# 5. Missed signals (no matching trade)
# ===========================================================================


class TestMissedSignal:
    def test_no_trades_at_all(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=100)
        result = compare_signals_to_trades([sig], [])
        assert result.pairs[0].status == FillStatus.MISSED
        assert result.pairs[0].trade is None
        assert result.summary.missed_count == 1
        assert result.summary.fill_rate == 0.0

    def test_wrong_ticker(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=100)
        trade = Trade(ticker="B", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=100)
        result = compare_signals_to_trades([sig], [trade])
        assert result.pairs[0].status == FillStatus.MISSED

    def test_wrong_direction(self, buy_signal_a: Signal) -> None:
        wrong_trade = Trade(
            ticker="000001",
            date="2026-01-05",
            direction=SignalDirection.SELL,
            price=10.05,
            quantity=100,
        )
        result = compare_signals_to_trades([buy_signal_a], [wrong_trade])
        assert result.pairs[0].status == FillStatus.MISSED

    def test_outside_time_window(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=100)
        trade = Trade(ticker="A", date="2026-01-05", direction=SignalDirection.BUY, price=10.0, quantity=100)
        result = compare_signals_to_trades([sig], [trade], time_window_days=2)
        assert result.pairs[0].status == FillStatus.MISSED


# ===========================================================================
# 6. Multiple signals and trades
# ===========================================================================


class TestMultipleSignalsTrades:
    def test_two_signals_two_trades_matched(self) -> None:
        sigs = [
            Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=100),
            Signal(ticker="B", date="2026-01-01", direction=SignalDirection.BUY, price=20.0, quantity=50),
        ]
        trades = [
            Trade(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.1, quantity=100),
            Trade(ticker="B", date="2026-01-01", direction=SignalDirection.BUY, price=20.2, quantity=50),
        ]
        result = compare_signals_to_trades(sigs, trades)
        assert result.summary.filled_count == 2
        assert result.summary.total_signals == 2
        assert result.summary.fill_rate == 1.0

    def test_three_signals_one_missed(self) -> None:
        sigs = [
            Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=100),
            Signal(ticker="B", date="2026-01-01", direction=SignalDirection.BUY, price=20.0, quantity=50),
            Signal(ticker="C", date="2026-01-01", direction=SignalDirection.BUY, price=30.0, quantity=30),
        ]
        trades = [
            Trade(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.1, quantity=100),
            Trade(ticker="B", date="2026-01-01", direction=SignalDirection.BUY, price=20.2, quantity=50),
        ]
        result = compare_signals_to_trades(sigs, trades)
        assert result.summary.filled_count == 2
        assert result.summary.missed_count == 1
        assert result.summary.fill_rate == pytest.approx(2 / 3)

    def test_trade_consumed_by_first_signal(self) -> None:
        """Two signals for the same ticker: only the first should match."""
        sigs = [
            Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=100),
            Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=100),
        ]
        trades = [
            Trade(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.1, quantity=100),
        ]
        result = compare_signals_to_trades(sigs, trades)
        assert result.pairs[0].status == FillStatus.FILLED
        assert result.pairs[1].status == FillStatus.MISSED


# ===========================================================================
# 7. Delay computation
# ===========================================================================


class TestDelay:
    def test_next_day_fill(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=100)
        trade = Trade(ticker="A", date="2026-01-02", direction=SignalDirection.BUY, price=10.0, quantity=100)
        result = compare_signals_to_trades([sig], [trade], time_window_days=1)
        assert result.pairs[0].delay_days == 1
        assert result.pairs[0].status == FillStatus.FILLED

    def test_same_day_zero_delay(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=100)
        trade = Trade(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=100)
        result = compare_signals_to_trades([sig], [trade])
        assert result.pairs[0].delay_days == 0

    def test_summary_delay_stats(self) -> None:
        sigs = [
            Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=100),
            Signal(ticker="A", date="2026-01-05", direction=SignalDirection.BUY, price=10.0, quantity=100),
        ]
        trades = [
            Trade(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=100),
            Trade(ticker="A", date="2026-01-06", direction=SignalDirection.BUY, price=10.0, quantity=100),
        ]
        result = compare_signals_to_trades(sigs, trades)
        assert result.summary.avg_delay_days == 0.5
        assert result.summary.max_delay_days == 1
        assert result.summary.min_delay_days == 0


# ===========================================================================
# 8. Empty inputs
# ===========================================================================


class TestEmptyInputs:
    def test_no_signals_no_trades(self) -> None:
        result = compare_signals_to_trades([], [])
        assert result.pairs == []
        assert result.summary.total_signals == 0

    def test_no_signals_with_trades(self) -> None:
        trades = [Trade(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=100)]
        result = compare_signals_to_trades([], trades)
        assert result.pairs == []
        assert result.summary.total_signals == 0


# ===========================================================================
# 9. Summary builder edge cases
# ===========================================================================


class TestBuildSummary:
    def test_all_missed(self) -> None:
        pairs = [
            MatchedPair(
                signal=Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0),
                trade=None,
                status=FillStatus.MISSED,
                price_diff=0.0,
                price_diff_pct=0.0,
                delay_days=0,
            )
        ]
        summary = _build_summary(pairs)
        assert summary.total_signals == 1
        assert summary.missed_count == 1
        assert summary.fill_rate == 0.0
        assert summary.avg_price_diff == 0.0

    def test_direction_specific_slippage(self) -> None:
        pairs = [
            MatchedPair(
                signal=Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0),
                trade=Trade(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.2, quantity=100),
                status=FillStatus.FILLED,
                price_diff=0.2,
                price_diff_pct=0.02,
                delay_days=0,
            ),
            MatchedPair(
                signal=Signal(ticker="A", date="2026-01-02", direction=SignalDirection.SELL, price=15.0),
                trade=Trade(ticker="A", date="2026-01-02", direction=SignalDirection.SELL, price=14.7, quantity=100),
                status=FillStatus.FILLED,
                price_diff=0.3,
                price_diff_pct=0.02,
                delay_days=0,
            ),
        ]
        summary = _build_summary(pairs)
        assert summary.avg_buy_slippage == pytest.approx(0.2)
        assert summary.avg_sell_slippage == pytest.approx(0.3)


# ===========================================================================
# 10. Event payload extraction
# ===========================================================================


class TestEventPayloadExtraction:
    def test_signals_from_pipeline_event(self) -> None:
        events = [
            {
                "trade_date": "20260105",
                "decisions": {"000001": {"action": "buy", "quantity": 100}, "000002": {"action": "hold", "quantity": 0}},
                "current_prices": {"000001": 10.50, "000002": 20.00},
                "executed_trades": {"000001": 100, "000002": 0},
            }
        ]
        signals = signals_from_event_payload(events)
        assert len(signals) == 1
        assert signals[0].ticker == "000001"
        assert signals[0].direction == SignalDirection.BUY
        assert signals[0].price == 10.50
        assert signals[0].date_str() == "2026-01-05"

    def test_trades_from_pipeline_event(self) -> None:
        events = [
            {
                "trade_date": "20260105",
                "decisions": {"000001": {"action": "buy", "quantity": 100}},
                "current_prices": {"000001": 10.50},
                "executed_trades": {"000001": 100},
            }
        ]
        trades = trades_from_event_payload(events)
        assert len(trades) == 1
        assert trades[0].ticker == "000001"
        assert trades[0].quantity == 100

    def test_hold_actions_not_extracted(self) -> None:
        events = [
            {
                "trade_date": "20260105",
                "decisions": {"000001": {"action": "hold", "quantity": 0}},
                "current_prices": {"000001": 10.50},
                "executed_trades": {"000001": 0},
            }
        ]
        assert signals_from_event_payload(events) == []
        assert trades_from_event_payload(events) == []

    def test_zero_executed_quantity_not_extracted_as_trade(self) -> None:
        events = [
            {
                "trade_date": "20260105",
                "decisions": {"000001": {"action": "buy", "quantity": 100}},
                "current_prices": {"000001": 10.50},
                "executed_trades": {"000001": 0},
            }
        ]
        # Signal is extracted (decision was buy), but no trade (quantity 0)
        signals = signals_from_event_payload(events)
        assert len(signals) == 1
        trades = trades_from_event_payload(events)
        assert len(trades) == 0


# ===========================================================================
# 11. compare_from_events convenience
# ===========================================================================


class TestCompareFromEvents:
    def test_full_round_trip(self) -> None:
        events = [
            {
                "trade_date": "20260105",
                "decisions": {"000001": {"action": "buy", "quantity": 100}},
                "current_prices": {"000001": 10.00},
                "executed_trades": {"000001": 100},
            },
            {
                "trade_date": "20260106",
                "decisions": {"000001": {"action": "sell", "quantity": 100}},
                "current_prices": {"000001": 11.00},
                "executed_trades": {"000001": 100},
            },
        ]
        result = compare_from_events(events)
        assert result.summary.total_signals == 2
        assert result.summary.filled_count == 2
        assert result.summary.fill_rate == 1.0

    def test_empty_events(self) -> None:
        result = compare_from_events([])
        assert result.summary.total_signals == 0


# ===========================================================================
# 12. Serialization
# ===========================================================================


class TestSerialization:
    def test_matched_pair_to_dict_filled(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0)
        trade = Trade(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.1, quantity=100)
        pair = MatchedPair(signal=sig, trade=trade, status=FillStatus.FILLED, price_diff=0.1, price_diff_pct=0.01, delay_days=0)
        d = matched_pair_to_dict(pair)
        assert d["status"] == "filled"
        assert d["trade"] is not None
        assert d["trade"]["price"] == 10.1
        assert d["price_diff"] == 0.1

    def test_matched_pair_to_dict_missed(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0)
        pair = MatchedPair(signal=sig, trade=None, status=FillStatus.MISSED, price_diff=0.0, price_diff_pct=0.0, delay_days=0)
        d = matched_pair_to_dict(pair)
        assert d["status"] == "missed"
        assert d["trade"] is None

    def test_summary_to_dict(self) -> None:
        s = ComparisonSummary(total_signals=5, filled_count=3, missed_count=2, fill_rate=0.6)
        d = summary_to_dict(s)
        assert d["total_signals"] == 5
        assert d["fill_rate"] == 0.6

    def test_comparison_result_to_dict(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0)
        pair = MatchedPair(signal=sig, trade=None, status=FillStatus.MISSED, price_diff=0.0, price_diff_pct=0.0, delay_days=0)
        result = ComparisonResult(pairs=[pair], summary=ComparisonSummary(total_signals=1, missed_count=1))
        d = comparison_result_to_dict(result)
        assert "pairs" in d
        assert "summary" in d
        assert len(d["pairs"]) == 1

    def test_metadata_included_in_serialization(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, metadata={"agent": "buffett"})
        pair = MatchedPair(signal=sig, trade=None, status=FillStatus.MISSED, price_diff=0.0, price_diff_pct=0.0, delay_days=0)
        d = matched_pair_to_dict(pair)
        assert d["signal"]["agent"] == "buffett"


# ===========================================================================
# 13. Signal / Trade date_str helpers
# ===========================================================================


class TestDateStrHelpers:
    def test_signal_date_str_from_datetime(self) -> None:
        sig = Signal(ticker="A", date=datetime(2026, 6, 15, 9, 30), direction=SignalDirection.BUY, price=10.0)
        assert sig.date_str() == "2026-06-15"

    def test_signal_date_str_from_date(self) -> None:
        sig = Signal(ticker="A", date=date(2026, 6, 15), direction=SignalDirection.BUY, price=10.0)
        assert sig.date_str() == "2026-06-15"

    def test_trade_date_str_from_string(self) -> None:
        trade = Trade(ticker="A", date="2026-06-15", direction=SignalDirection.BUY, price=10.0, quantity=100)
        assert trade.date_str() == "2026-06-15"


# ===========================================================================
# 14. Time window edge cases
# ===========================================================================


class TestTimeWindow:
    def test_exactly_at_boundary(self) -> None:
        """Signal and trade on day N+time_window should still match."""
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=100)
        trade = Trade(ticker="A", date="2026-01-02", direction=SignalDirection.BUY, price=10.0, quantity=100)
        result = compare_signals_to_trades([sig], [trade], time_window_days=1)
        assert result.pairs[0].status == FillStatus.FILLED
        assert result.pairs[0].delay_days == 1

    def test_just_outside_boundary(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=100)
        trade = Trade(ticker="A", date="2026-01-03", direction=SignalDirection.BUY, price=10.0, quantity=100)
        result = compare_signals_to_trades([sig], [trade], time_window_days=1)
        assert result.pairs[0].status == FillStatus.MISSED

    def test_larger_window_matches(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=10.0, quantity=100)
        trade = Trade(ticker="A", date="2026-01-03", direction=SignalDirection.BUY, price=10.0, quantity=100)
        result = compare_signals_to_trades([sig], [trade], time_window_days=3)
        assert result.pairs[0].status == FillStatus.FILLED
        assert result.pairs[0].delay_days == 2


# ===========================================================================
# 15. NaN / Inf input guards (regression for v0 audit)
# ===========================================================================
class TestNonFinitePriceGuards:
    """`_compute_price_diff` must not silently propagate NaN/Inf from corrupt
    inputs.  Otherwise a single bad row in an upstream event log would
    yield ``NaN`` slippage, contaminating every aggregate metric in the
    comparison summary (avg, p95, etc.) and crashing the JSON consumer."""

    def test_nan_signal_price_zeroes_both_fields(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=float("nan"), quantity=10)
        trade = Trade(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=100.0, quantity=10)
        diff, pct = _compute_price_diff(sig, trade)
        assert diff == 0.0
        assert pct == 0.0
        assert diff == diff  # not NaN
        assert pct == pct  # not NaN

    def test_inf_signal_price_zeroes_both_fields(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=float("inf"), quantity=10)
        trade = Trade(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=100.0, quantity=10)
        diff, pct = _compute_price_diff(sig, trade)
        assert diff == 0.0
        assert pct == 0.0

    def test_nan_trade_price_zeroes_both_fields(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=100.0, quantity=10)
        trade = Trade(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=float("nan"), quantity=10)
        diff, pct = _compute_price_diff(sig, trade)
        assert diff == 0.0
        assert pct == 0.0

    def test_inf_trade_price_zeroes_both_fields(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=100.0, quantity=10)
        trade = Trade(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=float("inf"), quantity=10)
        diff, pct = _compute_price_diff(sig, trade)
        assert diff == 0.0
        assert pct == 0.0

    def test_normal_buy_slippage_unaffected(self) -> None:
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=100.0, quantity=10)
        trade = Trade(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=105.0, quantity=10)
        diff, pct = _compute_price_diff(sig, trade)
        assert diff == 5.0
        assert abs(pct - 0.05) < 1e-9

    def test_nan_in_summary_does_not_contaminate_aggregates(self) -> None:
        """An end-to-end run with one NaN trade should keep ``avg_*`` finite."""
        sig = Signal(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=100.0, quantity=10)
        nan_trade = Trade(ticker="A", date="2026-01-01", direction=SignalDirection.BUY, price=float("nan"), quantity=10)
        result = compare_signals_to_trades([sig], [nan_trade], time_window_days=1)
        pair = result.pairs[0]
        assert pair.price_diff == pair.price_diff  # not NaN
        assert pair.price_diff_pct == pair.price_diff_pct  # not NaN
        assert result.summary.avg_price_diff == result.summary.avg_price_diff
        assert result.summary.avg_price_diff_pct == result.summary.avg_price_diff_pct
