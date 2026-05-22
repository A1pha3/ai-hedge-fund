from __future__ import annotations

from pathlib import Path

import scripts.analyze_btst_5d_15pct_unclassified_split_board as split_script


def test_analyze_btst_5d_15pct_unclassified_split_board_builds_bucket_and_recommendation_boards(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_unclassified"
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
                "explainability_payload": {
                  "trend_acceleration": 0.53,
                  "close_strength": 0.59,
                  "breakout_freshness": 0.31,
                  "volume_expansion_quality": 0.42
                }
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        split_script,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "cycle_status": "closed_cycle",
            "future_high_hit_15pct_2_5d": ticker == "001309",
            "max_future_high_return_2_5d": 0.16 if ticker == "001309" else 0.04,
            "next_open_return": 0.01,
        },
    )

    analysis = split_script.analyze_btst_5d_15pct_unclassified_split_board(reports_root)

    assert analysis["row_count"] == 2
    assert analysis["unclassified_row_count"] == 2
    assert analysis["bucket_board"][0]["bucket"] == "near_trend_threshold"
    assert analysis["recommendation_board"][0]["action"] == "recover_threshold_near_miss"
