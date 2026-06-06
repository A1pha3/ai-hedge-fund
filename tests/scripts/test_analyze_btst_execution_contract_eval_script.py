from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_execution_contract_eval import analyze_btst_execution_contract_eval


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_analyze_btst_execution_contract_eval_returns_required_shape(tmp_path: Path) -> None:
    report_dir = tmp_path / "paper_trading_window_sample"
    _write_json(
        report_dir / "selection_artifacts" / "2026-04-22" / "selection_snapshot.json",
        {
            "trade_date": "2026-04-22",
            "selection_targets": {
                "300724": {
                    "ticker": "300724",
                    "candidate_source": "layer_c_watchlist",
                    "execution_eligible": True,
                    "downgrade_reasons": [],
                    "historical_prior_quality_level": "execution_ready",
                    "btst_regime_gate": "normal_trade",
                    "short_trade": {
                        "decision": "selected",
                        "execution_eligible": True,
                        "downgrade_reasons": [],
                    },
                },
                "688313": {
                    "ticker": "688313",
                    "candidate_source": "layer_c_watchlist",
                    "execution_eligible": False,
                    "downgrade_reasons": ["historical_prior_not_execution_ready"],
                    "historical_prior_quality_level": "watch_only",
                    "btst_regime_gate": "normal_trade",
                    "short_trade": {
                        "decision": "near_miss",
                        "execution_eligible": False,
                        "downgrade_reasons": ["historical_prior_not_execution_ready"],
                    },
                },
                "002028": {
                    "ticker": "002028",
                    "candidate_source": "research_only",
                    "execution_eligible": False,
                    "downgrade_reasons": ["research_only_source_not_formal_execution"],
                    "historical_prior_quality_level": "reject",
                    "btst_regime_gate": "shadow_only",
                    "short_trade": {
                        "decision": "rejected",
                        "execution_eligible": False,
                        "downgrade_reasons": ["research_only_source_not_formal_execution"],
                    },
                },
            },
        },
    )

    analysis = analyze_btst_execution_contract_eval(report_dir)

    assert analysis["report_type"] == "p5_btst_execution_contract_eval"
    assert analysis["snapshot_count"] == 1
    assert "contract_summary" in analysis
    assert "semantics_comparison" in analysis
    assert "downgrade_reason_counts" in analysis
    assert "comparison_samples" in analysis
    assert analysis["semantics_comparison"]["selected"]["formal_buy_flow"] is True
    assert analysis["semantics_comparison"]["near_miss"]["formal_buy_flow"] is False
    assert analysis["semantics_comparison"]["research_only"]["formal_buy_flow"] is False
