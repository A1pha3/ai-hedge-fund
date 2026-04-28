from __future__ import annotations

import json
from pathlib import Path

import scripts.analyze_btst_selected_outcome_refresh_board as refresh_board_module
from scripts.analyze_btst_selected_outcome_refresh_board import (
    _resolve_contract_alignment,
    analyze_btst_selected_outcome_refresh_board,
)


def test_analyze_btst_selected_outcome_refresh_board_accepts_legacy_target_context_selected(monkeypatch, tmp_path: Path) -> None:
    report_dir = tmp_path / "paper_trading_window_sample"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-04-21"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-04-21",
                "target_context": [
                    {
                        "ticker": "300724",
                        "short_trade": {"decision": "selected"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    captured: dict[str, list[str]] = {}

    def _fake_build_refresh_board_entries(
        *,
        report_dir: Path,
        trade_date: str,
        selected_tickers: list[str],
        price_cache: dict[tuple[str, str], object],
    ) -> list[dict[str, object]]:
        captured["selected_tickers"] = list(selected_tickers)
        return [
            {
                "ticker": ticker,
                "current_cycle_status": "t_plus_2_closed",
                "overall_contract_verdict": "t_plus_2_observed_without_positive_expectation",
            }
            for ticker in selected_tickers
        ]

    monkeypatch.setattr(refresh_board_module, "_build_refresh_board_entries", _fake_build_refresh_board_entries)

    analysis = analyze_btst_selected_outcome_refresh_board(report_dir)

    assert captured["selected_tickers"] == ["300724"]
    assert analysis["selected_count"] == 1
    assert analysis["current_cycle_status_counts"] == {"t_plus_2_closed": 1}
    assert analysis["entries"][0]["ticker"] == "300724"
    assert "closed-cycle" in analysis["recommendation"]


def test_resolve_contract_alignment_marks_closed_cycle_without_positive_expectation() -> None:
    alignment = _resolve_contract_alignment(
        {"summary": {"next_close_positive_rate": 0.4, "t_plus_2_close_positive_rate": 0.3}},
        {"next_close_return": 0.011, "t_plus_2_close_return": -0.008},
    )

    assert alignment["historical_next_close_expectation_positive"] is False
    assert alignment["historical_t_plus_2_expectation_positive"] is False
    assert alignment["next_day_contract_verdict"] == "observed_without_positive_expectation"
    assert alignment["t_plus_2_contract_verdict"] == "observed_without_positive_expectation"
    assert alignment["overall_contract_verdict"] == "t_plus_2_observed_without_positive_expectation"
