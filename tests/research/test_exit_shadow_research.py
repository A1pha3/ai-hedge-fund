from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from src.research.exit_shadow_research import audit_coverage, build_legacy_cohort


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
