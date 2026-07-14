from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from src.research.exit_shadow_research import (
    ExitReplayResult,
    LegacySession,
    LegacyTradePath,
    PairedReplayRow,
    ReplayIneligibleError,
    audit_coverage,
    build_legacy_cohort,
    moving_block_mean_difference,
    replay_fixed_baseline,
    replay_paired,
    replay_shadow_challenger,
    summarize_paired_results,
)
from src.screening.offensive.execution_adjuster import ExecutionCosts


FIXED_TEST_COSTS = ExecutionCosts(
    version="exit-shadow-test-v1",
    commission=0.01,
    tax_rate=0.001,
    slippage_bps=10,
    other_fee=0.005,
)


def _session(
    offset: int,
    *,
    open_price: float,
    close: float,
    high: float | None = None,
    low: float | None = None,
    atr: float | None = 0.4,
    volume: float | None = 1_000.0,
    suspended: bool | None = False,
    limit_down: float | None = 8.0,
    limit_up: float | None = 14.0,
) -> LegacySession:
    return LegacySession(
        date=f"202607{14 + offset:02d}",
        open=open_price,
        high=high if high is not None else max(open_price, close) + 0.2,
        low=low if low is not None else min(open_price, close) - 0.2,
        close=close,
        atr=atr,
        volume=volume,
        suspended=suspended,
        limit_down=limit_down,
        limit_up=limit_up,
    )


def _trade_path(
    trade_id: str = "20260713:000001:btst_breakout",
    *,
    sessions: tuple[LegacySession, ...] | None = None,
) -> LegacyTradePath:
    path_sessions = sessions or tuple(
        _session(
            offset,
            open_price=10.0 + offset * 0.1,
            close=(11.5 if offset == 1 else 10.1 + offset * 0.1),
        )
        for offset in range(12)
    )
    return LegacyTradePath(
        trade_id=trade_id,
        signal_date="20260713",
        ticker=trade_id.split(":")[1],
        setup="btst_breakout",
        regime="normal",
        source="test",
        buy_line_number=1,
        exit_line_number=2,
        recorded_entry_price=10.0,
        replay_entry_price=path_sessions[0].open,
        sessions=path_sessions,
        recorded_return=0.05,
        reconstructed_legacy_return=0.05,
        recorded_return_mismatch=False,
        current_board_rule_mismatch=False,
        board_rule_auditable=True,
    )


@pytest.fixture
def single_trade_path() -> LegacyTradePath:
    return _trade_path()


@pytest.fixture
def complete_trade_paths(
    single_trade_path: LegacyTradePath,
) -> tuple[LegacyTradePath, ...]:
    return (
        single_trade_path,
        _trade_path("20260714:000002:btst_breakout"),
    )


def _replay_row(
    index: int,
    *,
    baseline_return: float = 0.01,
    challenger_return: float = 0.02,
    challenger_reason: str = "trailing_exit",
    challenger_holding: int = 5,
    challenger_mfe: float | None = 0.08,
) -> PairedReplayRow:
    day = pd.Timestamp("2026-01-05") + pd.offsets.BDay(index)
    signal_date = day.strftime("%Y%m%d")
    entry_date = (day + pd.offsets.BDay(1)).strftime("%Y%m%d")
    trading_session_dates = tuple(
        (day + pd.offsets.BDay(session)).strftime("%Y%m%d") for session in range(1, 13)
    )

    def result(
        arm: str,
        net_return: float,
        reason: str,
        holding_sessions: int,
        mfe: float | None,
    ) -> ExitReplayResult:
        trigger_date = (day + pd.offsets.BDay(holding_sessions - 1)).strftime("%Y%m%d")
        exit_date = (day + pd.offsets.BDay(holding_sessions)).strftime("%Y%m%d")
        return ExitReplayResult(
            trade_id=f"{signal_date}:{index:06d}:btst_breakout",
            signal_date=signal_date,
            ticker=f"{index:06d}",
            regime="normal",
            source="test",
            entry_date=entry_date,
            raw_entry_price=10.0,
            exit_trigger_date=trigger_date,
            exit_date=exit_date,
            raw_exit_price=10.0 * (1.0 + net_return),
            exit_reason=reason,
            deferred_exits=(),
            entry_net_cash_flow=-10.0,
            exit_net_cash_flow=10.0 * (1.0 + net_return),
            net_return=net_return,
            cost_version=f"{arm}-test",
            holding_sessions=holding_sessions,
            maximum_favorable_excursion=mfe,
            trading_session_dates=trading_session_dates,
        )

    return PairedReplayRow(
        baseline=result(
            "baseline", baseline_return, "maximum_holding_session", 10, 0.10
        ),
        challenger=result(
            "challenger",
            challenger_return,
            challenger_reason,
            challenger_holding,
            challenger_mfe,
        ),
        legacy_return=baseline_return + 0.005,
        trading_session_dates=trading_session_dates,
    )


@pytest.fixture
def paired_rows() -> tuple[PairedReplayRow, ...]:
    return tuple(
        _replay_row(
            index,
            baseline_return=(index - 10) / 100.0,
            challenger_return=(index - 8) / 100.0,
        )
        for index in range(20)
    )


def _prices(
    ticker: str = "000001",
    *,
    trigger_pct: float | None = None,
    session_10_close: float = 10.5,
) -> pd.DataFrame:
    rows = []
    for offset, day in enumerate(range(5, 16)):
        row = {
            "date": f"2026-01-{day:02d}",
            "open": 10.0,
            "high": 10.5,
            "low": 9.8,
            "close": session_10_close if offset == 10 else 10.2,
        }
        if trigger_pct is not None:
            row["pct_change"] = trigger_pct if offset == 0 else 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def test_builder_uses_only_paired_btst_exits_and_common_complete_paths(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+5.00%"}',
                '{"date":"20260105","ticker":"000002","setup":"oversold_bounce","action":"BUY"}',
            )
        ),
        encoding="utf-8",
    )
    prices = {
        "000001": pd.DataFrame(
            [
                {
                    "date": f"2026-01-{day:02d}",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                }
                for day in range(5, 20)
            ]
        )
    }
    cohort = build_legacy_cohort(journal, price_loader=prices.get)
    assert [trade.ticker for trade in cohort.included] == ["000001"]
    assert cohort.audit.total_paired_btst == 1
    assert cohort.audit.total_journal_rows == 3
    assert cohort.audit.execution_proxy_eligible == 1


def test_as_of_excludes_future_journal_and_price_evidence(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        '\n'.join((
            '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
            '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+5.00%"}',
        )), encoding="utf-8",
    )
    prices = _prices()
    early = build_legacy_cohort(journal, price_loader=lambda _: prices, as_of="20260114")
    assert early.included == ()
    assert early.audit.cutoff_excluded_journal_rows == 0
    assert early.audit.cutoff_excluded_price_sessions == 1
    current = build_legacy_cohort(journal, price_loader=lambda _: prices, as_of="20260115")
    assert len(current.included) == 1


def test_coverage_audit_blocks_promotion_when_missing_group_differs() -> None:
    audit = audit_coverage(
        covered_legacy_returns=[0.10, 0.12, 0.08],
        missing_legacy_returns=[0.01, 0.02],
        total=5,
    )
    assert audit.coverage == 0.60
    assert audit.selection_bias_warning is True
    assert audit.production_eligible is False


def test_builder_fails_closed_for_malformed_duplicate_and_unmatched_btst_events(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    valid = {"date": "20260105", "ticker": "000001", "setup": "btst_breakout"}
    duplicate = {"date": "20260105", "ticker": "000002", "setup": "btst_breakout"}
    unmatched = {"date": "20260105", "ticker": "000003", "setup": "btst_breakout"}
    rows = [
        "not-json",
        json.dumps(valid | {"action": "BUY"}),
        json.dumps(valid | {"action": "EXIT", "reasoning": "realized=+5.00%"}),
        json.dumps(duplicate | {"action": "BUY"}),
        json.dumps(duplicate | {"action": "BUY"}),
        json.dumps(duplicate | {"action": "EXIT", "reasoning": "realized=+5.00%"}),
        json.dumps(unmatched | {"action": "BUY"}),
    ]
    journal.write_text("\n".join(rows), encoding="utf-8")

    prices = {ticker: _prices(ticker) for ticker in ("000001", "000002", "000003")}
    cohort = build_legacy_cohort(journal, price_loader=prices.get)

    assert [trade.ticker for trade in cohort.included] == ["000001"]
    reasons = {(row.key, row.reason) for row in cohort.excluded}
    assert ("line:1", "malformed_json") in reasons
    assert ("20260105:000002:btst_breakout", "duplicate_buy") in reasons
    assert ("20260105:000003:btst_breakout", "unmatched_exit") in reasons
    assert cohort.audit.total_paired_btst == 1
    assert cohort.audit.malformed_rows == 1


def test_builder_counts_each_layer_and_keeps_current_board_rule_mismatch(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    rows: list[str] = []
    for ticker in ("300001", "000002", "000003", "000004"):
        base = {"date": "20260105", "ticker": ticker, "setup": "btst_breakout"}
        rows.append(json.dumps(base | {"action": "BUY", "entry_price": 10.0}))
        rows.append(
            json.dumps(base | {"action": "EXIT", "reasoning": "realized=+5.00%"})
        )
    journal.write_text("\n".join(rows), encoding="utf-8")
    missing_signal = _prices("000003")
    missing_signal["date"] = pd.date_range("2026-02-01", periods=len(missing_signal))
    short = _prices("000004").iloc[:5]
    prices = {
        "300001": _prices("300001", trigger_pct=10.0),
        "000003": missing_signal,
        "000004": short,
    }

    cohort = build_legacy_cohort(journal, price_loader=prices.get)

    assert cohort.audit.total_paired_btst == 4
    assert cohort.audit.price_file_present == 3
    assert cohort.audit.signal_date_present == 2
    assert cohort.audit.complete_session_10_window == 1
    assert cohort.audit.execution_proxy_eligible == 1
    assert len(cohort.included) == 1
    assert cohort.included[0].current_board_rule_mismatch is True
    assert cohort.included[0].setup == "btst_breakout"
    assert cohort.included[0].regime == "unknown"
    assert cohort.included[0].source == "paper_trading_backtest"
    reasons = {row.reason for row in cohort.excluded}
    assert reasons == {
        "price_file_missing",
        "signal_date_missing",
        "incomplete_session_10_window",
    }


def test_board_rule_mismatch_compares_legacy_and_current_detectors(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+1.00%"}',
            )
        ),
        encoding="utf-8",
    )

    cohort = build_legacy_cohort(
        journal,
        price_loader=lambda _: _prices(trigger_pct=5.0),
    )

    assert cohort.included[0].current_board_rule_mismatch is False


def test_builder_audits_recorded_return_against_reconstructable_legacy_return(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY","entry_price":10.0}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+5.00%"}',
                '{"date":"20260105","ticker":"000002","setup":"btst_breakout","action":"BUY","entry_price":10.0}',
                '{"date":"20260105","ticker":"000002","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+9.00%"}',
            )
        ),
        encoding="utf-8",
    )
    prices = {
        "000001": _prices(session_10_close=10.5),
        "000002": _prices(session_10_close=10.5),
    }

    cohort = build_legacy_cohort(journal, price_loader=prices.get)

    by_ticker = {trade.ticker: trade for trade in cohort.included}
    assert by_ticker["000001"].reconstructed_legacy_return == 0.05
    assert by_ticker["000001"].recorded_return_mismatch is False
    assert by_ticker["000002"].recorded_return_mismatch is True
    assert cohort.audit.recorded_return_mismatches == 1


def test_execution_proxy_ineligible_trade_is_excluded_with_recorded_return_preserved(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=-3.00%"}',
            )
        ),
        encoding="utf-8",
    )
    prices = _prices(trigger_pct=10.0)
    prices.loc[1, "open"] = prices.loc[0, "close"] * 1.10
    prices.loc[1, "high"] = prices.loc[1, "open"]

    cohort = build_legacy_cohort(journal, price_loader=lambda _: prices)

    assert cohort.included == ()
    assert cohort.excluded[0].reason == "execution_proxy_ineligible"
    assert cohort.excluded[0].recorded_return == -0.03
    assert cohort.audit.coverage == 0.0
    assert cohort.audit.missing_legacy_mean == -0.03


def test_invalid_recorded_return_does_not_shrink_paired_btst_denominator(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"missing realized marker"}',
            )
        ),
        encoding="utf-8",
    )

    cohort = build_legacy_cohort(journal, price_loader=lambda _: _prices())

    assert cohort.included == ()
    assert cohort.audit.total_paired_btst == 1
    assert cohort.audit.total == 1
    assert cohort.audit.coverage == 0.0
    assert cohort.audit.selection_bias_warning is True
    assert cohort.excluded == (cohort.excluded[0],)
    assert cohort.excluded[0].reason == "invalid_recorded_return"


def test_execution_proxy_uses_reconstructed_pct_change_when_column_is_absent(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+1.00%"}',
            )
        ),
        encoding="utf-8",
    )
    prices = _prices()
    prior = pd.DataFrame(
        [
            {
                "date": "2026-01-04",
                "open": 9.0,
                "high": 9.3,
                "low": 8.9,
                "close": 9.2727272727,
            }
        ]
    )
    prices = pd.concat((prior, prices), ignore_index=True)
    prices.loc[2, "open"] = prices.loc[1, "close"] * 1.10
    prices.loc[2, "high"] = prices.loc[2, "open"]

    cohort = build_legacy_cohort(journal, price_loader=lambda _: prices)

    assert cohort.included == ()
    assert cohort.excluded[0].reason == "execution_proxy_ineligible"


def test_exit_before_buy_is_excluded_after_pairing_without_shrinking_denominator(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+1.00%"}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
            )
        ),
        encoding="utf-8",
    )

    cohort = build_legacy_cohort(journal, price_loader=lambda _: _prices())

    assert cohort.included == ()
    assert cohort.audit.total_paired_btst == 1
    assert cohort.audit.total == 1
    assert cohort.excluded[0].reason == "exit_not_after_buy"
    assert cohort.excluded[0].recorded_return == 0.01
    assert cohort.excluded[0].line_numbers == (1, 2)
    assert cohort.audit.missing_legacy_mean == 0.01


def test_exit_before_buy_with_invalid_return_is_unclassified_but_stays_in_denominator(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"missing realized"}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
            )
        ),
        encoding="utf-8",
    )

    cohort = build_legacy_cohort(journal, price_loader=lambda _: _prices())

    assert cohort.audit.total_paired_btst == 1
    assert cohort.excluded[0].reason == "exit_not_after_buy"
    assert cohort.excluded[0].recorded_return is None
    assert cohort.audit.coverage == 0.0
    assert cohort.audit.missing_legacy_mean is None
    assert cohort.audit.selection_bias_warning is True


def test_included_trade_preserves_buy_and_exit_line_numbers(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"oversold_bounce","action":"BUY"}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+1.00%"}',
            )
        ),
        encoding="utf-8",
    )

    cohort = build_legacy_cohort(journal, price_loader=lambda _: _prices())

    assert cohort.included[0].buy_line_number == 2
    assert cohort.included[0].exit_line_number == 3


@pytest.mark.parametrize("duplicate_date", ["2026-01-05", "2026-01-10"])
def test_price_normalization_rejects_duplicate_civil_session_dates(
    tmp_path: Path,
    duplicate_date: str,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+1.00%"}',
            )
        ),
        encoding="utf-8",
    )
    prices = _prices()
    duplicate = prices.loc[prices["date"] == duplicate_date].copy()
    duplicate["date"] = duplicate_date + " 15:00:00"
    original_index = prices.index[prices["date"] == duplicate_date][0]
    prices.loc[original_index, "date"] = duplicate_date + " 09:30:00"
    prices = pd.concat((duplicate, prices.iloc[::-1]), ignore_index=True)

    cohort = build_legacy_cohort(journal, price_loader=lambda _: prices)

    assert cohort.included == ()
    assert cohort.audit.price_file_present == 1
    assert cohort.excluded[0].reason == "duplicate_session_date"


@pytest.mark.parametrize(
    "raw_date",
    [
        None,
        "",
        " ",
        float("nan"),
        pd.NaT,
        20260105,
        20260105.0,
        True,
        False,
        "2026/01/05",
        "2026-13-01",
        "not-a-date",
    ],
)
def test_price_date_parser_rejects_unsupported_values_without_throwing(
    tmp_path: Path,
    raw_date: object,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+1.00%"}',
            )
        ),
        encoding="utf-8",
    )
    prices = _prices()
    prices["date"] = prices["date"].astype(object)
    prices.loc[0, "date"] = raw_date

    cohort = build_legacy_cohort(journal, price_loader=lambda _: prices)

    assert cohort.included == ()
    assert cohort.excluded[0].reason == "price_data_invalid"


@pytest.mark.parametrize(
    "raw_date",
    [
        "20260105",
        "2026-01-05",
        "2026-01-05 09:30:00",
        "2026-01-05T15:00:00",
        date(2026, 1, 5),
        datetime(2026, 1, 5, 15, 0, 0),
    ],
)
def test_price_date_parser_accepts_only_declared_civil_date_formats(
    tmp_path: Path,
    raw_date: object,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+1.00%"}',
            )
        ),
        encoding="utf-8",
    )
    prices = _prices()
    prices["date"] = prices["date"].astype(object)
    prices.loc[0, "date"] = raw_date

    cohort = build_legacy_cohort(journal, price_loader=lambda _: prices)

    assert len(cohort.included) == 1


@pytest.mark.parametrize(
    ("loader_value", "file_present", "reason"),
    [
        (None, 0, "price_file_missing"),
        (pd.DataFrame(), 1, "empty_price_data"),
        ({"not": "a dataframe"}, 1, "invalid_price_data"),
    ],
)
def test_price_loader_layers_distinguish_absent_empty_and_invalid_results(
    tmp_path: Path,
    loader_value: object,
    file_present: int,
    reason: str,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+1.00%"}',
            )
        ),
        encoding="utf-8",
    )

    cohort = build_legacy_cohort(journal, price_loader=lambda _: loader_value)  # type: ignore[arg-type]

    assert cohort.audit.price_file_present == file_present
    assert cohort.excluded[0].reason == reason
    assert cohort.excluded[0].line_numbers == (1, 2)


def test_default_loader_distinguishes_existing_but_unreadable_price_file(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+1.00%"}',
            )
        ),
        encoding="utf-8",
    )
    price_cache = tmp_path / "prices"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_bytes(b"\xff\xfe\x00")

    cohort = build_legacy_cohort(journal, price_cache_dir=price_cache)

    assert cohort.audit.price_file_present == 1
    assert cohort.excluded[0].reason == "unreadable_price_data"


@pytest.mark.parametrize(
    ("column", "value"),
    [("low", 10.3), ("high", 10.1), ("close", 10.6)],
)
def test_price_normalization_rejects_impossible_ohlc_bars(
    tmp_path: Path,
    column: str,
    value: float,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+1.00%"}',
            )
        ),
        encoding="utf-8",
    )
    prices = _prices()
    prices.loc[5, column] = value

    cohort = build_legacy_cohort(journal, price_loader=lambda _: prices)

    assert cohort.included == ()
    assert cohort.excluded[0].reason == "invalid_ohlc_bar"


@pytest.mark.parametrize(
    ("date", "ticker"),
    [
        ("20260230", "000001"),
        ("２０２６０１０５", "000001"),
        ("20260105", "１２３４５６"),
        ("20260105", "00001"),
        ("20260105", "000001.SZ"),
    ],
)
def test_natural_key_requires_real_date_and_exact_six_ascii_digit_ticker(
    tmp_path: Path,
    date: str,
    ticker: str,
) -> None:
    journal = tmp_path / "journal.jsonl"
    base = {"date": date, "ticker": ticker, "setup": "btst_breakout"}
    journal.write_text(
        "\n".join(
            (
                json.dumps(base | {"action": "BUY"}),
                json.dumps(base | {"action": "EXIT", "reasoning": "realized=+1.00%"}),
            )
        ),
        encoding="utf-8",
    )

    cohort = build_legacy_cohort(journal, price_loader=lambda _: _prices())

    assert cohort.included == ()
    assert cohort.audit.total_paired_btst == 0
    assert cohort.audit.malformed_rows == 2
    assert {row.reason for row in cohort.excluded} == {"malformed_natural_key"}


def test_unknown_btst_action_is_explicitly_malformed_without_poisoning_valid_pair(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    base = {"date": "20260105", "ticker": "000001", "setup": "btst_breakout"}
    journal.write_text(
        "\n".join(
            (
                json.dumps(base | {"action": "buy"}),
                json.dumps(base | {"action": "BUY"}),
                json.dumps(base | {"action": "EXIT", "reasoning": "realized=+1.00%"}),
            )
        ),
        encoding="utf-8",
    )

    cohort = build_legacy_cohort(journal, price_loader=lambda _: _prices())

    assert len(cohort.included) == 1
    assert cohort.audit.total_paired_btst == 1
    assert cohort.audit.malformed_rows == 1
    assert cohort.excluded[0].reason == "unknown_btst_action"
    assert cohort.excluded[0].line_numbers == (1,)


@pytest.mark.parametrize(
    ("field", "value"),
    [("horizon", 5), ("horizon", "10"), ("time_exit", "T+5")],
)
def test_incompatible_btst_holding_fields_fail_closed_after_pairing(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    journal = tmp_path / "journal.jsonl"
    base = {"date": "20260105", "ticker": "000001", "setup": "btst_breakout"}
    journal.write_text(
        "\n".join(
            (
                json.dumps(base | {"action": "BUY", field: value}),
                json.dumps(
                    base
                    | {
                        "action": "EXIT",
                        "horizon": 10,
                        "time_exit": "T+10",
                        "reasoning": "realized=+1.00%",
                    }
                ),
            )
        ),
        encoding="utf-8",
    )

    cohort = build_legacy_cohort(journal, price_loader=lambda _: _prices())

    assert cohort.included == ()
    assert cohort.audit.total_paired_btst == 1
    assert cohort.audit.malformed_rows == 1
    assert cohort.excluded[0].reason == "incompatible_btst_holding_period"
    assert cohort.excluded[0].recorded_return == 0.01
    assert cohort.audit.missing_legacy_mean == 0.01


def test_wrong_horizon_with_invalid_return_is_unclassified_but_stays_in_denominator(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    base = {"date": "20260105", "ticker": "000001", "setup": "btst_breakout"}
    journal.write_text(
        "\n".join(
            (
                json.dumps(base | {"action": "BUY", "horizon": 5}),
                json.dumps(
                    base
                    | {
                        "action": "EXIT",
                        "horizon": 10,
                        "reasoning": "missing realized",
                    }
                ),
            )
        ),
        encoding="utf-8",
    )

    cohort = build_legacy_cohort(journal, price_loader=lambda _: _prices())

    assert cohort.audit.total_paired_btst == 1
    assert cohort.excluded[0].reason == "incompatible_btst_holding_period"
    assert cohort.excluded[0].recorded_return is None
    assert cohort.audit.missing_legacy_mean is None
    assert cohort.audit.selection_bias_warning is True


def test_coverage_means_include_valid_returns_excluded_before_price_layers(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY","entry_price":10.0}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+10.00%"}',
                '{"date":"20260105","ticker":"000002","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+1.00%"}',
                '{"date":"20260105","ticker":"000002","setup":"btst_breakout","action":"BUY","entry_price":10.0}',
            )
        ),
        encoding="utf-8",
    )

    cohort = build_legacy_cohort(journal, price_loader=lambda _: _prices())

    assert cohort.audit.total_paired_btst == 2
    assert cohort.audit.coverage == 0.5
    assert cohort.audit.covered_legacy_mean == 0.10
    assert cohort.audit.missing_legacy_mean == 0.01
    assert cohort.audit.selection_bias_warning is True


@pytest.mark.parametrize(
    ("difference", "expected_mismatch"),
    [(0.00005, False), (0.00005001, True)],
)
def test_recorded_return_rounding_tolerance_is_half_a_percentage_basis_point(
    tmp_path: Path,
    difference: float,
    expected_mismatch: bool,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY","entry_price":10.0}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+5.00%"}',
            )
        ),
        encoding="utf-8",
    )
    prices = _prices(session_10_close=10.0 * (1.05 + difference))
    prices.loc[10, "high"] = 11.0

    cohort = build_legacy_cohort(journal, price_loader=lambda _: prices)

    assert cohort.included[0].recorded_return_mismatch is expected_mismatch


def test_recorded_and_replay_entry_prices_keep_distinct_provenance(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"BUY","entry_price":10.0}',
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+5.00%"}',
            )
        ),
        encoding="utf-8",
    )
    prices = _prices(session_10_close=10.5)
    prices.loc[1, "open"] = 11.0
    prices.loc[1, "high"] = 11.2

    cohort = build_legacy_cohort(journal, price_loader=lambda _: prices)
    trade = cohort.included[0]

    assert trade.recorded_entry_price == 10.0
    assert trade.replay_entry_price == 11.0
    assert trade.reconstructed_legacy_return == 0.05
    assert trade.recorded_return_mismatch is False


@pytest.mark.parametrize("entry_price", [None, 0, -1, True, "10.0", "not-a-number"])
def test_missing_or_invalid_recorded_entry_is_unauditable_not_replaced_by_replay_open(
    tmp_path: Path,
    entry_price: object,
) -> None:
    journal = tmp_path / "journal.jsonl"
    buy = {
        "date": "20260105",
        "ticker": "000001",
        "setup": "btst_breakout",
        "action": "BUY",
        "entry_price": entry_price,
    }
    journal.write_text(
        "\n".join(
            (
                json.dumps(buy),
                '{"date":"20260105","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+5.00%"}',
            )
        ),
        encoding="utf-8",
    )
    prices = _prices(session_10_close=10.5)
    prices.loc[1, "open"] = 10.8
    prices.loc[1, "high"] = 11.0

    cohort = build_legacy_cohort(journal, price_loader=lambda _: prices)
    trade = cohort.included[0]

    assert trade.recorded_entry_price is None
    assert trade.replay_entry_price == 10.8
    assert trade.reconstructed_legacy_return is None
    assert trade.recorded_return_mismatch is None
    assert cohort.audit.recorded_return_unauditable == 1


def test_baseline_and_challenger_share_exact_trade_keys(
    complete_trade_paths: tuple[LegacyTradePath, ...],
) -> None:
    result = replay_paired(complete_trade_paths, costs=FIXED_TEST_COSTS)

    assert [row.trade_id for row in result.baseline] == [
        row.trade_id for row in result.challenger
    ]
    assert result.total_paths == 2
    assert result.common_eligible == 2


def test_baseline_exits_session_ten_open_not_close(
    single_trade_path: LegacyTradePath,
) -> None:
    result = replay_fixed_baseline(single_trade_path, costs=FIXED_TEST_COSTS)

    assert result.exit_date == single_trade_path.sessions[9].date
    assert result.raw_exit_price == single_trade_path.sessions[9].open
    assert result.exit_trigger_date == single_trade_path.sessions[8].date
    assert result.exit_reason == "maximum_holding_session"


def test_challenger_uses_only_prior_close_information(
    single_trade_path: LegacyTradePath,
) -> None:
    original = replay_shadow_challenger(
        single_trade_path,
        costs=FIXED_TEST_COSTS,
    )
    mutated_sessions = tuple(
        session
        if session.date <= original.exit_trigger_date
        else replace(
            session,
            close=session.close + 40.0,
        )
        for session in single_trade_path.sessions
    )
    mutated = replace(single_trade_path, sessions=mutated_sessions)

    assert (
        replay_shadow_challenger(mutated, costs=FIXED_TEST_COSTS).exit_trigger_date
        == original.exit_trigger_date
    )


def test_replay_applies_shared_cost_model_to_entry_and_exit(
    single_trade_path: LegacyTradePath,
) -> None:
    result = replay_fixed_baseline(single_trade_path, costs=FIXED_TEST_COSTS)
    entry = single_trade_path.sessions[0]
    exit_session = single_trade_path.sessions[9]
    expected_entry_cash = -(
        entry.open * 1.001 + FIXED_TEST_COSTS.commission + FIXED_TEST_COSTS.other_fee
    )
    expected_exit_cash = (
        exit_session.open * (1.0 - 0.001 - 0.001)
        - FIXED_TEST_COSTS.commission
        - FIXED_TEST_COSTS.other_fee
    )

    assert result.entry_net_cash_flow == pytest.approx(expected_entry_cash)
    assert result.exit_net_cash_flow == pytest.approx(expected_exit_cash)
    assert result.net_return == pytest.approx(
        expected_exit_cash / -expected_entry_cash - 1.0
    )
    assert result.cost_version == FIXED_TEST_COSTS.version


def test_unknown_queue_exit_is_deferred_to_next_executable_open(
    single_trade_path: LegacyTradePath,
) -> None:
    sessions = list(single_trade_path.sessions)
    sessions[3] = replace(
        sessions[3],
        open=sessions[3].limit_up,
        high=sessions[3].limit_up,
        low=sessions[3].limit_up - 0.2,
        close=sessions[3].limit_up - 0.1,
        suspended=None,
    )
    path = replace(single_trade_path, sessions=tuple(sessions))

    result = replay_shadow_challenger(path, costs=FIXED_TEST_COSTS)

    assert result.exit_trigger_date == sessions[2].date
    assert result.exit_date == sessions[4].date
    assert result.deferred_exits == ((sessions[3].date, "unknown_queue"),)


def test_replay_statistics_calendar_keeps_all_supplied_path_sessions(
    single_trade_path: LegacyTradePath,
) -> None:
    result = replay_shadow_challenger(single_trade_path, costs=FIXED_TEST_COSTS)

    assert result.exit_date < single_trade_path.sessions[-1].date
    assert result.trading_session_dates == tuple(
        session.date for session in single_trade_path.sessions
    )


def test_replay_mfe_uses_audited_daily_highs_as_nonexecutable_diagnostic(
    single_trade_path: LegacyTradePath,
) -> None:
    result = replay_shadow_challenger(single_trade_path, costs=FIXED_TEST_COSTS)
    exit_index = next(
        index
        for index, session in enumerate(single_trade_path.sessions)
        if session.date == result.exit_date
    )
    expected_mfe = (
        max(
            *(session.high for session in single_trade_path.sessions[:exit_index]),
            single_trade_path.sessions[exit_index].open,
        )
        / result.raw_entry_price
        - 1.0
    )

    assert result.holding_sessions == exit_index + 1
    assert result.maximum_favorable_excursion == pytest.approx(expected_mfe)


def test_replay_mfe_never_uses_exit_session_high_low_or_close(
    single_trade_path: LegacyTradePath,
) -> None:
    original = replay_shadow_challenger(single_trade_path, costs=FIXED_TEST_COSTS)
    exit_index = next(
        index
        for index, session in enumerate(single_trade_path.sessions)
        if session.date == original.exit_date
    )
    sessions = list(single_trade_path.sessions)
    exit_session = sessions[exit_index]
    sessions[exit_index] = replace(
        exit_session,
        high=min(float(exit_session.limit_up) - 0.1, exit_session.high + 1.0),
        low=max(float(exit_session.limit_down) + 0.1, exit_session.low - 0.5),
        close=exit_session.high + 0.5,
    )

    mutated = replay_shadow_challenger(
        replace(single_trade_path, sessions=tuple(sessions)),
        costs=FIXED_TEST_COSTS,
    )

    assert mutated.exit_date == original.exit_date
    assert mutated.maximum_favorable_excursion == pytest.approx(
        original.maximum_favorable_excursion
    )


def test_session_ten_open_mfe_uses_sessions_one_to_nine_highs_and_exit_open(
    single_trade_path: LegacyTradePath,
) -> None:
    result = replay_fixed_baseline(single_trade_path, costs=FIXED_TEST_COSTS)
    exit_index = 9
    attainable_proxy = max(
        *(session.high for session in single_trade_path.sessions[:exit_index]),
        single_trade_path.sessions[exit_index].open,
    )

    assert result.exit_date == single_trade_path.sessions[exit_index].date
    assert result.maximum_favorable_excursion == pytest.approx(
        attainable_proxy / result.raw_entry_price - 1.0
    )


def test_common_mask_excludes_both_arms_when_only_baseline_cannot_execute(
    single_trade_path: LegacyTradePath,
) -> None:
    sessions = list(single_trade_path.sessions)
    for index in range(9, len(sessions)):
        sessions[index] = replace(sessions[index], suspended=True)
    path = replace(single_trade_path, sessions=tuple(sessions))

    result = replay_paired((path,), costs=FIXED_TEST_COSTS)

    assert result.baseline == ()
    assert result.challenger == ()
    assert result.total_paths == 1
    assert result.common_eligible == 0
    assert result.excluded[0].trade_id == path.trade_id
    assert result.excluded[0].reason == "baseline_exit_not_executable"
    assert result.excluded[0].baseline_reason == "exit_path_exhausted"
    assert result.excluded[0].challenger_reason is None


def test_exhausted_baseline_preserves_mixed_deferral_trace(
    single_trade_path: LegacyTradePath,
) -> None:
    sessions = list(single_trade_path.sessions)
    sessions[9] = replace(
        sessions[9],
        open=sessions[9].limit_up,
        high=sessions[9].limit_up,
        low=sessions[9].limit_up - 0.2,
        close=sessions[9].limit_up - 0.1,
    )
    sessions[10] = replace(sessions[10], suspended=True)
    sessions[11] = replace(sessions[11], volume=None, suspended=False)
    path = replace(single_trade_path, sessions=tuple(sessions))

    with pytest.raises(ReplayIneligibleError) as raised:
        replay_fixed_baseline(path, costs=FIXED_TEST_COSTS)

    assert raised.value.failure.reason == "exit_path_exhausted"
    assert raised.value.failure.deferred_exits == (
        (sessions[9].date, "unknown_queue"),
        (sessions[10].date, "unexecutable_proxy"),
        (sessions[11].date, "unknown_queue"),
    )

    paired = replay_paired((path,), costs=FIXED_TEST_COSTS)
    exclusion = paired.excluded[0]
    assert exclusion.baseline_failure == raised.value.failure
    assert exclusion.challenger_failure is None


def test_common_mask_excludes_missing_causal_atr_with_explicit_reason(
    single_trade_path: LegacyTradePath,
) -> None:
    sessions = list(single_trade_path.sessions)
    sessions[4] = replace(sessions[4], atr=None)
    path = replace(single_trade_path, sessions=tuple(sessions))

    result = replay_paired((path,), costs=FIXED_TEST_COSTS)

    assert result.baseline == result.challenger == ()
    assert result.excluded[0].reason == "causal_atr_unavailable"


def test_common_mask_treats_missing_volume_as_unknown_suspension(
    single_trade_path: LegacyTradePath,
) -> None:
    sessions = list(single_trade_path.sessions)
    sessions[0] = replace(sessions[0], volume=None, suspended=False)
    path = replace(single_trade_path, sessions=tuple(sessions))

    result = replay_paired((path,), costs=FIXED_TEST_COSTS)

    assert result.baseline == result.challenger == ()
    assert result.excluded[0].reason == "entry_unknown_queue"


def test_builder_carries_causal_atr_execution_metadata_and_deferral_tail(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260120","ticker":"000001","setup":"btst_breakout","action":"BUY","entry_price":10.0}',
                '{"date":"20260120","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+5.00%"}',
            )
        ),
        encoding="utf-8",
    )
    prices = pd.DataFrame(
        [
            {
                "date": f"2026-01-{day:02d}",
                "open": 10.0 + day * 0.01,
                "high": 10.5 + day * 0.01,
                "low": 9.5 + day * 0.01,
                "close": 10.1 + day * 0.01,
                "volume": 1_000.0,
            }
            for day in range(1, 32)
        ]
    )

    trade = build_legacy_cohort(journal, price_loader=lambda _: prices).included[0]

    assert len(trade.sessions) == 11
    assert trade.sessions[0].atr == pytest.approx(1.0)
    assert trade.sessions[0].volume == 1_000.0
    assert trade.sessions[0].suspended is False
    assert trade.sessions[0].limit_down == pytest.approx(
        prices.loc[19, "close"] * (1.0 - 0.095)
    )
    assert trade.sessions[0].limit_up == pytest.approx(
        prices.loc[19, "close"] * (1.0 + 0.095)
    )


def test_builder_preserves_explicit_numpy_suspension_over_positive_volume(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260120","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
                '{"date":"20260120","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+1.00%"}',
            )
        ),
        encoding="utf-8",
    )
    prices = pd.DataFrame(
        [
            {
                "date": f"2026-01-{day:02d}",
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.1,
                "volume": 1_000.0,
                "suspended": day == 21,
            }
            for day in range(1, 32)
        ]
    )

    trade = build_legacy_cohort(journal, price_loader=lambda _: prices).included[0]

    assert trade.sessions[0].suspended is True


def test_builder_does_not_replace_invalid_explicit_limit_with_derived_value(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            (
                '{"date":"20260120","ticker":"000001","setup":"btst_breakout","action":"BUY"}',
                '{"date":"20260120","ticker":"000001","setup":"btst_breakout","action":"EXIT","reasoning":"realized=+1.00%"}',
            )
        ),
        encoding="utf-8",
    )
    prices = pd.DataFrame(
        [
            {
                "date": f"2026-01-{day:02d}",
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.1,
                "volume": 1_000.0,
                "limit_up": "unknown" if day == 21 else 11.0,
            }
            for day in range(1, 32)
        ]
    )

    trade = build_legacy_cohort(journal, price_loader=lambda _: prices).included[0]

    assert trade.sessions[0].limit_up is None


def test_block_resampling_is_deterministic(
    paired_rows: tuple[PairedReplayRow, ...],
) -> None:
    first = moving_block_mean_difference(
        paired_rows, block_sessions=10, draws=1_000, seed=7
    )
    second = moving_block_mean_difference(
        paired_rows, block_sessions=10, draws=1_000, seed=7
    )

    assert first == second
    assert first.draws == 1_000
    assert first.block_sessions == 10
    assert first.trading_session_count > first.signal_day_count
    assert first.effective_sample_counts == (first.signal_day_count,) * first.draws
    assert first.ci_lower <= first.mean_difference <= first.ci_upper


def test_block_resampling_aggregates_trades_by_signal_day_first() -> None:
    first = _replay_row(0, baseline_return=0.0, challenger_return=0.0)
    same_day_raw = _replay_row(1, baseline_return=0.0, challenger_return=0.20)
    same_day = PairedReplayRow(
        baseline=replace(same_day_raw.baseline, signal_date=first.signal_date),
        challenger=replace(same_day_raw.challenger, signal_date=first.signal_date),
        legacy_return=same_day_raw.legacy_return,
        trading_session_dates=same_day_raw.trading_session_dates,
    )
    second_day = _replay_row(2, baseline_return=0.0, challenger_return=0.0)

    result = moving_block_mean_difference(
        (first, same_day, second_day), draws=100, seed=3
    )

    assert result.signal_day_count == 2
    assert result.mean_difference == pytest.approx(0.05)


def test_block_resampling_reports_sparse_empty_calendar_windows() -> None:
    result = moving_block_mean_difference(
        (_replay_row(0), _replay_row(20)), draws=100, seed=3
    )

    assert result.candidate_block_count == (
        result.trading_session_count - result.block_sessions + 1
    )
    assert result.empty_block_count > 0
    assert result.usable_block_count + result.empty_block_count == (
        result.candidate_block_count
    )
    assert set(result.effective_sample_counts) == {result.signal_day_count}


def test_block_resampling_dense_and_sparse_blocks_use_same_effective_n() -> None:
    rows = tuple(
        _replay_row(
            index,
            baseline_return=0.0,
            challenger_return=float(index >= 20),
        )
        for index in (0, 1, 2, 20, 40)
    )

    result = moving_block_mean_difference(rows, draws=250, seed=11)

    assert result.empty_block_count > 0
    assert len(result.effective_sample_counts) == 250
    assert all(count == len(rows) for count in result.effective_sample_counts)


def test_statistics_count_signal_days_and_nonoverlapping_blocks(
    paired_rows: tuple[PairedReplayRow, ...],
) -> None:
    stats = summarize_paired_results(paired_rows)

    assert stats.trade_count == len(paired_rows)
    assert stats.signal_day_count == len({row.signal_date for row in paired_rows})
    assert 0 < stats.nonoverlapping_window_count <= stats.signal_day_count


def test_paired_statistics_report_returns_tails_holding_and_reasons(
    paired_rows: tuple[PairedReplayRow, ...],
) -> None:
    stats = summarize_paired_results(
        paired_rows,
        total_trade_count=25,
        missing_legacy_returns=(-0.20, -0.10, 0.0, 0.10, 0.20),
    )
    differences = [
        row.challenger.net_return - row.baseline.net_return for row in paired_rows
    ]

    assert stats.mean_difference == pytest.approx(sum(differences) / len(differences))
    assert stats.median_difference == pytest.approx(0.02)
    assert stats.worst_decile_difference == pytest.approx(0.02)
    assert stats.baseline.mean_holding_sessions == 10.0
    assert stats.challenger.median_holding_sessions == 5.0
    assert stats.baseline.exit_reason_counts == (("maximum_holding_session", 20),)
    assert stats.challenger.exit_reason_counts == (("trailing_exit", 20),)
    assert stats.coverage == pytest.approx(0.8)
    assert stats.missing_group_legacy_mean == pytest.approx(0.0)


def test_headline_paired_statistics_equal_weight_signal_days() -> None:
    first = _replay_row(0, baseline_return=0.0, challenger_return=0.0)
    same_day_raw = _replay_row(1, baseline_return=0.0, challenger_return=0.20)
    same_day = PairedReplayRow(
        baseline=replace(same_day_raw.baseline, signal_date=first.signal_date),
        challenger=replace(same_day_raw.challenger, signal_date=first.signal_date),
        legacy_return=same_day_raw.legacy_return,
        trading_session_dates=same_day_raw.trading_session_dates,
    )
    second_day = _replay_row(2, baseline_return=0.0, challenger_return=0.0)

    stats = summarize_paired_results((first, same_day, second_day), draws=100)

    assert stats.mean_difference == pytest.approx(0.05)
    assert stats.median_difference == pytest.approx(0.05)
    assert stats.worst_decile_difference == pytest.approx(0.01)
    assert stats.downside_decile_mean_difference == pytest.approx(0.0)


def test_mfe_capture_fails_closed_below_fixed_positive_denominator() -> None:
    too_small = tuple(_replay_row(index) for index in range(9))
    enough = tuple(_replay_row(index) for index in range(10))

    too_small_stats = summarize_paired_results(too_small)
    enough_stats = summarize_paired_results(enough)

    assert too_small_stats.challenger.positive_mfe_count == 9
    assert too_small_stats.challenger.mfe_capture_min_count == 10
    assert too_small_stats.challenger.mfe_capture_mean is None
    assert too_small_stats.challenger.mean_give_up == pytest.approx(0.06)
    assert too_small_stats.challenger.mfe_is_diagnostic_not_executable is True
    assert enough_stats.challenger.positive_mfe_count == 10
    assert enough_stats.challenger.mfe_capture_mean == pytest.approx(0.25)


@pytest.mark.parametrize(
    ("rows", "block_sessions", "draws"),
    [
        ((), 10, 100),
        ((_replay_row(0),), 10, 100),
        (tuple(_replay_row(index) for index in range(10)), 9, 100),
        (tuple(_replay_row(index) for index in range(10)), 10, 0),
    ],
)
def test_block_resampling_fails_closed_for_invalid_or_small_samples(
    rows: tuple[PairedReplayRow, ...],
    block_sessions: int,
    draws: int,
) -> None:
    with pytest.raises(ValueError):
        moving_block_mean_difference(
            rows,
            block_sessions=block_sessions,
            draws=draws,
            seed=0,
        )


def test_report_is_never_production_eligible(
    paired_rows: tuple[PairedReplayRow, ...],
) -> None:
    stats = summarize_paired_results(paired_rows)

    assert stats.shadow_only is True
    assert stats.production_eligible is False


@pytest.mark.parametrize(
    "calendar",
    [
        ("20260106", "20260106"),
        ("20260107", "20260106"),
        ("20260106", "20260230"),
    ],
)
def test_paired_row_rejects_duplicate_reversed_or_invalid_calendars(
    calendar: tuple[str, ...],
) -> None:
    raw = _replay_row(0)

    with pytest.raises(ValueError):
        PairedReplayRow(
            baseline=replace(raw.baseline, trading_session_dates=calendar),
            challenger=replace(raw.challenger, trading_session_dates=calendar),
            trading_session_dates=calendar,
        )


def test_paired_row_rejects_arm_or_explicit_path_calendar_mismatch() -> None:
    raw = _replay_row(0)
    shorter = raw.trading_session_dates[:-1]

    with pytest.raises(ValueError):
        PairedReplayRow(
            baseline=raw.baseline,
            challenger=replace(raw.challenger, trading_session_dates=shorter),
        )
    with pytest.raises(ValueError):
        PairedReplayRow(
            baseline=raw.baseline,
            challenger=raw.challenger,
            trading_session_dates=shorter,
        )


def test_nonoverlap_count_uses_maximum_interval_schedule() -> None:
    early_long = _replay_row(0)
    short_one_raw = _replay_row(1)
    short_one = PairedReplayRow(
        baseline=replace(short_one_raw.baseline, exit_date="20260108"),
        challenger=replace(short_one_raw.challenger, exit_date="20260108"),
        trading_session_dates=short_one_raw.trading_session_dates,
    )
    short_two_raw = _replay_row(4)
    short_two = PairedReplayRow(
        baseline=replace(short_two_raw.baseline, exit_date="20260113"),
        challenger=replace(short_two_raw.challenger, exit_date="20260113"),
        trading_session_dates=short_two_raw.trading_session_dates,
    )

    stats = summarize_paired_results((early_long, short_one, short_two), draws=100)

    assert stats.nonoverlapping_window_count == 2
