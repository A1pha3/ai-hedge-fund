from __future__ import annotations

from pathlib import Path

import scripts.analyze_btst_5d_15pct_boundary_contract_inspection as boundary_script


def test_analyze_btst_5d_15pct_boundary_contract_inspection_builds_source_comparison_and_governance_boards(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_boundary_contract"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        """
        {
          "trade_date": "20260324",
          "selection_targets": {
            "001309": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "near_miss",
                "explainability_payload": {
                  "breakout_stage": "early",
                  "target_profile": "tight",
                  "replay_context": "demo",
                  "layer_c_decision": "hold"
                }
              }
            },
            "300111": {
              "candidate_source": "layer_b_boundary",
              "short_trade": {
                "decision": "rejected",
                "explainability_payload": {
                  "replay_context": "demo",
                  "layer_c_decision": "reject",
                  "candidate_source": "layer_b_boundary"
                }
              }
            },
            "600123": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "near_miss",
                "explainability_payload": {
                  "breakout_stage": "late",
                  "replay_context": "demo",
                  "layer_c_decision": "hold",
                  "candidate_source": "short_trade_boundary"
                }
              },
              "breakout_freshness": null,
              "trend_acceleration": null,
              "volume_expansion_quality": null,
              "close_strength": null,
              "t0_tail_strength": 0.9938,
              "trend_continuation": null,
              "short_term_reversal": null
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        boundary_script,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "cycle_status": "closed_cycle",
            "future_high_hit_15pct_2_5d": False,
            "max_future_high_return_2_5d": 0.04,
            "next_open_return": 0.01,
        },
    )

    analysis = boundary_script.analyze_btst_5d_15pct_boundary_contract_inspection(reports_root)

    assert analysis["boundary_row_count"] == 3
    assert len(analysis["boundary_rows"]) == 3
    assert next(row for row in analysis["boundary_rows"] if row["ticker"] == "600123")["boundary_context"] == {
        "t0_tail_strength": 0.9938,
    }
    assert {row["candidate_source"] for row in analysis["source_comparison_board"]} == {
        "short_trade_boundary",
        "layer_b_boundary",
    }
    assert analysis["governance_recommendation_board"][0]["action"] == "fix_candidate_source_contract"
