"""P2 (2026-06-05) tests for the profile experiment harness.

Key invariants:
  1. Empty ledger list → "证据不足" report.
  2. Sufficient samples → win_rate, CI, coverage all computed.
  3. Missing regimes → explicit warning in report.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_btst_profile_experiment import (
    aggregate_outcomes_by_profile,
    render_profile_experiment_report,
)
from src.paper_trading.btst_outcome_ledger import (
    build_ledger_header,
    build_ticker_outcome,
    write_outcome_ledger,
)


def _make_outcome_ledger(
    *,
    decision_id: str,
    signal_date: str,
    profile: str,
    outcomes_data: list[tuple[str, str, str | None]],  # (ticker, verdict, regime)
    path: Path,
) -> Path:
    """Helper to build and write a small outcome ledger."""
    outcomes = []
    for ticker, verdict, regime in outcomes_data:
        outcomes.append(
            build_ticker_outcome(
                decision_id=decision_id,
                ticker=ticker,
                signal_date=signal_date,
                outcome_category="formal_selected",
                verdict=verdict,
                price_outcome={"data_status": "ok"},
                context={"regime_gate_level": regime, "profile": profile},
            )
        )
    header = build_ledger_header(
        decision_id=decision_id, signal_date=signal_date, outcomes=outcomes,
    )
    write_outcome_ledger(header, outcomes, path)
    return path


class TestEmptyLedgers:
    def test_empty_aggregation_returns_empty_dict(self) -> None:
        result = aggregate_outcomes_by_profile([])
        assert result == {}

    def test_empty_report_says_insufficient(self) -> None:
        md = render_profile_experiment_report(aggregated={})
        assert "证据不足" in md
        assert "BTST Profile Experiment" in md
        assert "Profile Routing Rules" in md


class TestAggregation:
    def test_aggregation_groups_by_profile(self, tmp_path: Path) -> None:
        ledger_path = tmp_path / "ledger.json"
        _make_outcome_ledger(
            decision_id="test-1",
            signal_date="20260601",
            profile="conservative",
            outcomes_data=[
                ("300001", "profit", "normal"),
                ("300002", "loss", "normal"),
                ("300003", "profit", "shadow_only"),
            ],
            path=ledger_path,
        )
        result = aggregate_outcomes_by_profile([ledger_path])
        assert "conservative" in result
        cons = result["conservative"]
        assert cons["sample_count"] == 3
        assert cons["profit_count"] == 2
        assert cons["loss_count"] == 1
        assert cons["win_rate"] == round(2 / 3, 4)
        assert set(cons["regimes_covered"]) == {"normal", "shadow_only"}

    def test_aggregation_handles_multiple_ledgers(self, tmp_path: Path) -> None:
        path1 = tmp_path / "ledger1.json"
        path2 = tmp_path / "ledger2.json"
        _make_outcome_ledger(
            decision_id="cons-1",
            signal_date="20260601",
            profile="conservative",
            outcomes_data=[("300001", "profit", "normal")],
            path=path1,
        )
        _make_outcome_ledger(
            decision_id="agg-1",
            signal_date="20260601",
            profile="aggressive",
            outcomes_data=[("300001", "loss", "normal")],
            path=path2,
        )
        result = aggregate_outcomes_by_profile([path1, path2])
        assert result["conservative"]["profit_count"] == 1
        assert result["aggressive"]["loss_count"] == 1

    def test_ci_95_computed_when_decided_gt_0(self, tmp_path: Path) -> None:
        ledger_path = tmp_path / "ledger.json"
        outcomes_data = [("300001", "profit", "normal")] * 10 + [("300002", "loss", "normal")] * 5
        _make_outcome_ledger(
            decision_id="test",
            signal_date="20260601",
            profile="conservative",
            outcomes_data=outcomes_data,
            path=ledger_path,
        )
        result = aggregate_outcomes_by_profile([ledger_path])
        cons = result["conservative"]
        ci = cons["win_rate_ci_95"]
        assert ci is not None
        assert ci[0] <= ci[1]
        assert 0.0 <= ci[0] <= 1.0
        assert 0.0 <= ci[1] <= 1.0


class TestReportRendering:
    def test_report_with_sufficient_data(self, tmp_path: Path) -> None:
        # Build enough samples for the report to compute meaningful stats.
        ledger_path = tmp_path / "ledger.json"
        outcomes_data = []
        for i in range(15):
            outcomes_data.append((f"300{i:03d}", "profit", "normal_trade"))
        for i in range(15, 25):
            outcomes_data.append((f"300{i:03d}", "loss", "normal_trade"))
        _make_outcome_ledger(
            decision_id="test",
            signal_date="20260601",
            profile="conservative",
            outcomes_data=outcomes_data,
            path=ledger_path,
        )
        agg = aggregate_outcomes_by_profile([ledger_path])
        md = render_profile_experiment_report(aggregated=agg)
        assert "Outcome Aggregation" in md
        assert "conservative" in md
        assert "0.600" in md or "0.6" in md  # 15/25 = 0.6 win rate
        # Regime coverage note (only normal_trade covered, missing shadow_only/halt).
        assert "Regime 覆盖警告" in md

    def test_report_warns_when_insufficient_decided(self, tmp_path: Path) -> None:
        ledger_path = tmp_path / "ledger.json"
        _make_outcome_ledger(
            decision_id="test",
            signal_date="20260601",
            profile="conservative",
            outcomes_data=[("300001", "profit", "normal_trade")],
            path=ledger_path,
        )
        agg = aggregate_outcomes_by_profile([ledger_path])
        md = render_profile_experiment_report(aggregated=agg)
        # Only 1 sample, decided<20 → must say 证据不足.
        assert "证据不足" in md

    def test_report_regime_coverage_complete(self, tmp_path: Path) -> None:
        # Cover all 3 required regimes.
        ledger_path = tmp_path / "ledger.json"
        outcomes_data = []
        for regime in ("normal_trade", "shadow_only", "halt"):
            for i in range(7):
                outcomes_data.append((f"{regime[:2]}{i:03d}", "profit", regime))
        _make_outcome_ledger(
            decision_id="test",
            signal_date="20260601",
            profile="conservative",
            outcomes_data=outcomes_data,
            path=ledger_path,
        )
        agg = aggregate_outcomes_by_profile([ledger_path])
        md = render_profile_experiment_report(aggregated=agg)
        assert "Regime 覆盖: 至少覆盖" in md
        assert "Regime 覆盖警告" not in md
