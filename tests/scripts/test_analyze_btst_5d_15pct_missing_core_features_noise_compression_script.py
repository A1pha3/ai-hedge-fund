from __future__ import annotations

from pathlib import Path

import scripts.analyze_btst_5d_15pct_missing_core_features_noise_compression as compression_script


def test_analyze_btst_5d_15pct_missing_core_features_noise_compression_builds_root_cause_and_recommendation_boards(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_missing_core"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        """
        {
          "trade_date": "20260324",
          "selection_targets": {
            "601600": {
              "candidate_source": "layer_c_watchlist",
              "short_trade": {
                "decision": "blocked",
                "explainability_payload": {}
              }
            },
            "001309": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "near_miss",
                "explainability_payload": {}
              }
            },
            "300111": {
              "candidate_source": "watchlist_filter_diagnostics",
              "short_trade": {
                "decision": "rejected",
                "explainability_payload": {}
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        compression_script,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "cycle_status": "closed_cycle",
            "future_high_hit_15pct_2_5d": ticker == "300111",
            "max_future_high_return_2_5d": 0.16 if ticker == "300111" else 0.04,
            "next_open_return": 0.01,
        },
    )

    analysis = compression_script.analyze_btst_5d_15pct_missing_core_features_noise_compression(reports_root)

    assert analysis["missing_core_row_count"] == 3
    assert {row["root_cause"] for row in analysis["root_cause_board"]} == {
        "watchlist_empty_payload",
        "boundary_without_explainability",
        "diagnostic_probe_without_core_features",
    }
    assert any(row["action"] == "inspect_candidate_source_contract" for row in analysis["compression_recommendation_board"])
