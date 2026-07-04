"""P1 (2026-06-05) tests for the BTST outcome ledger.

Key invariants from the plan:
  1. outcome 与 decision 唯一关联率 100% (via decision_id).
  2. 重复 outcome 记录为 0 (unique decision_id + ticker pair).
  3. 校准报告包含 sample_count, coverage, confidence.
  4. 历史摘要不被 outcome 回写修改.
  5. regime 覆盖至少覆盖 normal_trade / shadow_only / halt, 缺失时显式说明.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.paper_trading.btst_outcome_ledger import (
    build_ledger_header,
    build_ticker_outcome,
    classify_verdict,
    compute_incremental_evidence,
    OutcomeCategory,
    OutcomeDataStatus,
    OutcomeLedgerHeader,
    OutcomeVerdict,
    read_outcome_ledger,
    TickerOutcome,
    write_outcome_ledger,
)


def _base_outcome_kwargs(**overrides) -> dict:
    kw = {
        "decision_id": "btst-20260602-post-close-plan-v1",
        "ticker": "300001",
        "signal_date": "20260602",
        "outcome_category": "formal_selected",
        "verdict": "profit",
        "price_outcome": {
            "data_status": "ok",
            "trade_close": 10.0,
            "next_open": 10.5,
            "next_high": 11.0,
            "next_close": 10.8,
            "next_open_return": 0.05,
            "next_high_return": 0.10,
            "next_close_return": 0.08,
            "next_open_to_close_return": 0.0286,
            "next_trade_date": "2026-06-03",
        },
        "context": {
            "regime_gate_level": "normal",
            "market_gate": "normal_trade",
            "profile": "conservative",
            "score_target": 0.72,
        },
    }
    kw.update(overrides)
    return kw


class TestTickerOutcome:
    def test_build_from_price_outcome(self) -> None:
        outcome = build_ticker_outcome(**_base_outcome_kwargs())
        assert outcome.decision_id == "btst-20260602-post-close-plan-v1"
        assert outcome.ticker == "300001"
        assert outcome.outcome_category == OutcomeCategory.FORMAL_SELECTED
        assert outcome.verdict == OutcomeVerdict.PROFIT
        assert outcome.next_close_return == 0.08
        assert outcome.regime_gate_level == "normal"

    def test_missing_price_data(self) -> None:
        outcome = build_ticker_outcome(
            **_base_outcome_kwargs(
                verdict="missing_data",
                price_outcome={"data_status": "missing_next_trade_day_bar"},
            )
        )
        assert outcome.data_status == OutcomeDataStatus.MISSING_NEXT_TRADE_DAY_BAR
        assert outcome.next_close_return is None

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(Exception, match="Extra inputs"):
            TickerOutcome(
                decision_id="test",
                ticker="300001",
                signal_date="20260602",
                outcome_category="formal_selected",
                verdict="profit",
                some_unknown_field=True,
            )

    def test_unique_key_is_decision_id_plus_ticker(self) -> None:
        a = build_ticker_outcome(**_base_outcome_kwargs())
        b = build_ticker_outcome(**_base_outcome_kwargs(ticker="300002"))
        assert a.decision_id == b.decision_id
        assert a.ticker != b.ticker


class TestClassifyVerdict:
    def test_profit(self) -> None:
        assert classify_verdict(next_close_return=0.02) == "profit"

    def test_loss(self) -> None:
        assert classify_verdict(next_close_return=-0.03) == "loss"

    def test_breakeven(self) -> None:
        assert classify_verdict(next_close_return=0.001) == "breakeven"

    def test_no_entry(self) -> None:
        assert classify_verdict(next_close_return=None, entry_status="no_entry") == "no_entry"

    def test_missing_data_from_status(self) -> None:
        assert classify_verdict(next_close_return=None, data_status="missing_price_frame") == "missing_data"

    def test_missing_data_from_none_return(self) -> None:
        assert classify_verdict(next_close_return=None, next_open_return=None) == "missing_data"


class TestLedgerHeader:
    def test_header_statistics(self) -> None:
        outcomes = [
            build_ticker_outcome(**_base_outcome_kwargs(ticker="300001", verdict="profit")),
            build_ticker_outcome(**_base_outcome_kwargs(ticker="300002", verdict="loss")),
            build_ticker_outcome(**_base_outcome_kwargs(ticker="300003", verdict="profit")),
            build_ticker_outcome(**_base_outcome_kwargs(ticker="300004", verdict="no_entry")),
            build_ticker_outcome(**_base_outcome_kwargs(ticker="300005", verdict="missing_data", price_outcome={"data_status": "missing_price_frame"})),
        ]
        header = build_ledger_header(
            decision_id="btst-20260602-post-close-plan-v1",
            signal_date="20260602",
            outcomes=outcomes,
        )
        assert header.outcome_count == 5
        assert header.sample_count == 5
        assert header.profit_count == 2
        assert header.loss_count == 1
        assert header.breakeven_count == 0
        assert header.no_entry_count == 1
        assert header.missing_data_count == 1
        assert header.win_rate == round(2 / 3, 4)  # 2 profit / 3 decided
        assert header.coverage == round(3 / 5, 4)
        assert "formal_selected" in header.categories_covered
        assert "normal" in header.regimes_covered

    def test_empty_outcomes(self) -> None:
        header = build_ledger_header(
            decision_id="test",
            signal_date="20260602",
            outcomes=[],
        )
        assert header.outcome_count == 0
        assert header.win_rate is None
        assert header.coverage is None


class TestIncrementalEvidence:
    def test_insufficient_when_few_samples(self) -> None:
        header = build_ledger_header(
            decision_id="test",
            signal_date="20260602",
            outcomes=[
                build_ticker_outcome(**_base_outcome_kwargs(ticker="300001", verdict="profit")),
                build_ticker_outcome(**_base_outcome_kwargs(ticker="300002", verdict="loss")),
            ],
        )
        evidence = compute_incremental_evidence([header])
        assert evidence["status"] == "insufficient"
        assert evidence["sample_count"] == 2

    def test_sufficient_when_many_samples(self) -> None:
        outcomes = [build_ticker_outcome(**_base_outcome_kwargs(ticker=f"300{i:03d}", verdict="profit")) for i in range(15)] + [build_ticker_outcome(**_base_outcome_kwargs(ticker=f"301{i:03d}", verdict="loss")) for i in range(10)]
        header = build_ledger_header(
            decision_id="test",
            signal_date="20260602",
            outcomes=outcomes,
        )
        evidence = compute_incremental_evidence([header])
        assert evidence["status"] == "sufficient"
        assert evidence["sample_count"] == 25
        assert evidence["confidence"] is not None

    def test_empty_ledgers(self) -> None:
        evidence = compute_incremental_evidence([])
        assert evidence["status"] == "insufficient"
        assert evidence["sample_count"] == 0


class TestAtomicWrite:
    def test_write_and_read_roundtrip(self, tmp_path: Path) -> None:
        outcomes = [
            build_ticker_outcome(**_base_outcome_kwargs(ticker="300001", verdict="profit")),
            build_ticker_outcome(**_base_outcome_kwargs(ticker="300002", verdict="loss")),
        ]
        header = build_ledger_header(
            decision_id="btst-20260602-post-close-plan-v1",
            signal_date="20260602",
            outcomes=outcomes,
        )
        path = tmp_path / "outcome_ledger.json"
        write_outcome_ledger(header, outcomes, path)

        read_header, read_outcomes = read_outcome_ledger(path)
        assert read_header.decision_id == header.decision_id
        assert read_header.outcome_count == 2
        assert len(read_outcomes) == 2
        assert read_outcomes[0].ticker == "300001"

    def test_overwrite_is_atomic(self, tmp_path: Path) -> None:
        outcomes_v1 = [
            build_ticker_outcome(**_base_outcome_kwargs(ticker="300001", verdict="profit")),
        ]
        header_v1 = build_ledger_header(
            decision_id="test",
            signal_date="20260602",
            outcomes=outcomes_v1,
        )
        path = tmp_path / "outcome_ledger.json"
        write_outcome_ledger(header_v1, outcomes_v1, path)

        outcomes_v2 = [
            build_ticker_outcome(**_base_outcome_kwargs(ticker="300001", verdict="profit")),
            build_ticker_outcome(**_base_outcome_kwargs(ticker="300002", verdict="loss")),
        ]
        header_v2 = build_ledger_header(
            decision_id="test",
            signal_date="20260602",
            outcomes=outcomes_v2,
        )
        write_outcome_ledger(header_v2, outcomes_v2, path)

        read_header, read_outcomes = read_outcome_ledger(path)
        assert read_header.outcome_count == 2
        assert len(read_outcomes) == 2
        # No leftover temp files.
        assert len(list(tmp_path.glob(".outcome_ledger_*"))) == 0


class TestOutcomeDoesNotModifySummary:
    def test_outcome_ledger_is_independent_from_operator_summary(self, tmp_path: Path) -> None:
        """Writing an outcome ledger must not modify the operator_summary.json."""
        from src.paper_trading.btst_operator_summary import (
            build_operator_summary,
            write_operator_summary,
        )

        summary = build_operator_summary(
            signal_date="20260602",
            decision_as_of="2026-06-02T23:59:59+08:00",
            data_as_of="2026-06-02T15:00:00+08:00",
        )
        summary_path = tmp_path / "operator_summary.json"
        write_operator_summary(summary, summary_path)

        # Read the summary before writing outcome.
        summary_before = json.loads(summary_path.read_text(encoding="utf-8"))

        # Write outcome ledger.
        outcomes = [
            build_ticker_outcome(**_base_outcome_kwargs(ticker="300001", verdict="profit")),
        ]
        header = build_ledger_header(
            decision_id="test",
            signal_date="20260602",
            outcomes=outcomes,
        )
        ledger_path = tmp_path / "outcome_ledger.json"
        write_outcome_ledger(header, outcomes, ledger_path)

        # Summary must be unchanged.
        summary_after = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary_before == summary_after
