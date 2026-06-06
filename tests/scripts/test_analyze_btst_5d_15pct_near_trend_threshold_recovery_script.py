from __future__ import annotations

from pathlib import Path

import scripts.analyze_btst_5d_15pct_near_trend_threshold_recovery as recovery_script


def test_analyze_btst_5d_15pct_near_trend_threshold_recovery_builds_cohort_comparison_and_verdict(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_recovery"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        """
        {
          "trade_date": "20260324",
          "selection_targets": {
            "001309": {
              "candidate_source": "watchlist_filter_diagnostics",
              "short_trade": {
                "decision": "rejected",
                "explainability_payload": {
                  "trend_acceleration": 0.53,
                  "close_strength": 0.59,
                  "breakout_freshness": 0.31,
                  "volume_expansion_quality": 0.42
                }
              }
            },
            "600101": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "near_miss",
                "explainability_payload": {
                  "trend_acceleration": 0.52,
                  "close_strength": 0.58,
                  "breakout_freshness": 0.22,
                  "volume_expansion_quality": 0.30
                }
              }
            },
            "300111": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.62,
                  "close_strength": 0.64,
                  "breakout_freshness": 0.30,
                  "volume_expansion_quality": 0.47
                }
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        recovery_script,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "cycle_status": "closed_cycle",
            "future_high_hit_15pct_2_5d": ticker in {"001309", "300111"},
            "max_future_high_return_2_5d": 0.18 if ticker == "001309" else 0.16 if ticker == "300111" else 0.04,
            "next_open_return": 0.01 if ticker != "600101" else 0.05,
        },
    )

    analysis = recovery_script.analyze_btst_5d_15pct_near_trend_threshold_recovery(reports_root, min_recovered_row_count=1)

    assert analysis["recovered_cohort"]["row_count"] == 1
    assert analysis["unrecovered_bucket_baseline"]["row_count"] == 1
    assert analysis["trend_baseline"]["row_count"] == 1
    assert analysis["governance_verdict"] == "advance_recovery_validation"
