from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

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


def test_builder_uses_only_paired_btst_exits_and_common_complete_paths(tmp_path: Path) -> None:
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


def test_builder_fails_closed_for_malformed_duplicate_and_unmatched_btst_events(tmp_path: Path) -> None:
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


def test_builder_counts_each_layer_and_keeps_current_board_rule_mismatch(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    rows: list[str] = []
    for ticker in ("300001", "000002", "000003", "000004"):
        base = {"date": "20260105", "ticker": ticker, "setup": "btst_breakout"}
        rows.append(json.dumps(base | {"action": "BUY", "entry_price": 10.0}))
        rows.append(json.dumps(base | {"action": "EXIT", "reasoning": "realized=+5.00%"}))
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
    assert reasons == {"price_file_missing", "signal_date_missing", "incomplete_session_10_window"}


def test_builder_audits_recorded_return_against_reconstructable_legacy_return(tmp_path: Path) -> None:
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


def test_execution_proxy_ineligible_trade_is_excluded_with_recorded_return_preserved(tmp_path: Path) -> None:
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

    cohort = build_legacy_cohort(journal, price_loader=lambda _: prices)

    assert cohort.included == ()
    assert cohort.excluded[0].reason == "execution_proxy_ineligible"
    assert cohort.excluded[0].recorded_return == -0.03
    assert cohort.audit.coverage == 0.0
    assert cohort.audit.missing_legacy_mean == -0.03


def test_invalid_recorded_return_does_not_shrink_paired_btst_denominator(tmp_path: Path) -> None:
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
    assert cohort.excluded == (
        cohort.excluded[0],
    )
    assert cohort.excluded[0].reason == "invalid_recorded_return"


def test_execution_proxy_uses_reconstructed_pct_change_when_column_is_absent(tmp_path: Path) -> None:
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
        [{"date": "2026-01-04", "open": 9.0, "high": 9.3, "low": 8.9, "close": 9.2727272727}]
    )
    prices = pd.concat((prior, prices), ignore_index=True)
    prices.loc[2, "open"] = prices.loc[1, "close"] * 1.10

    cohort = build_legacy_cohort(journal, price_loader=lambda _: prices)

    assert cohort.included == ()
    assert cohort.excluded[0].reason == "execution_proxy_ineligible"
