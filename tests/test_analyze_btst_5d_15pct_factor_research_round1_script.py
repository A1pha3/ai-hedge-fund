from __future__ import annotations

from pathlib import Path

import scripts.analyze_btst_5d_15pct_factor_research_round1 as round1_script


def test_analyze_btst_5d_15pct_factor_research_round1_builds_shortlist_from_synthetic_reports(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir_a = reports_root / "paper_trading_window_20260323_20260326_round1_a"
    snapshot_dir_a = report_dir_a / "selection_artifacts" / "2026-03-24"
    snapshot_dir_a.mkdir(parents=True, exist_ok=True)
    snapshot_dir_a.joinpath("selection_snapshot.json").write_text(
        """
        {
          "trade_date": "20260324",
          "selection_targets": {
            "001309": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.64,
                  "close_strength": 0.67,
                  "volume_expansion_quality": 0.62,
                  "breakout_freshness": 0.58,
                  "t0_tail_strength": 0.61,
                  "trend_continuation": 0.66
                }
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    report_dir_b = reports_root / "paper_trading_window_20260325_20260328_round1_b"
    snapshot_dir_b = report_dir_b / "selection_artifacts" / "2026-03-25"
    snapshot_dir_b.mkdir(parents=True, exist_ok=True)
    snapshot_dir_b.joinpath("selection_snapshot.json").write_text(
        """
        {
          "trade_date": "20260325",
          "selection_targets": {
            "300383": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "near_miss",
                "explainability_payload": {
                  "trend_acceleration": 0.62,
                  "close_strength": 0.65,
                  "volume_expansion_quality": 0.64,
                  "breakout_freshness": 0.57,
                  "t0_tail_strength": 0.60,
                  "trend_continuation": 0.63
                }
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    def _fake_extract_btst_price_outcome(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], object]) -> dict[str, object]:
        if ticker == "001309":
            return {
                "cycle_status": "closed_cycle",
                "future_high_hit_15pct_2_5d": True,
                "max_future_high_return_2_5d": 0.18,
                "time_to_hit_15pct": 2,
                "next_open_return": 0.01,
            }
        return {
            "cycle_status": "closed_cycle",
            "future_high_hit_15pct_2_5d": True,
            "max_future_high_return_2_5d": 0.17,
            "time_to_hit_15pct": 3,
            "next_open_return": 0.02,
        }

    monkeypatch.setattr(round1_script, "_extract_btst_price_outcome", _fake_extract_btst_price_outcome)

    analysis = round1_script.analyze_btst_5d_15pct_factor_research_round1(reports_root, min_closed_cycle_count=1)

    assert analysis["row_count"] == 2
    assert analysis["event_prototype_leaderboard"][0]["group_label"] in {"breakout_ignition", "trend_continuation"}
    assert analysis["factor_family_leaderboard"][0]["alpha_pass"] is True
    assert analysis["alpha_beta_gamma_shortlist"][0]["group_type"] in {"factor_family", "interaction"}


def test_analyze_btst_5d_15pct_factor_research_round1_excludes_quarantined_tickers(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    quarantine_artifact = reports_root / "btst_5d_15pct_boundary_quarantine_latest.json"
    quarantine_artifact.parent.mkdir(parents=True, exist_ok=True)
    quarantine_artifact.write_text(
        """
        {
          "research_surface_lists": {
            "allow": [],
            "quarantine": ["001309"],
            "separate_surface": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    report_dir = reports_root / "paper_trading_window_20260323_20260326_round1_a"
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
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.64,
                  "close_strength": 0.67,
                  "volume_expansion_quality": 0.62,
                  "breakout_freshness": 0.58
                }
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        round1_script,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "cycle_status": "closed_cycle",
            "future_high_hit_15pct_2_5d": True,
            "max_future_high_return_2_5d": 0.18,
            "time_to_hit_15pct": 2,
            "next_open_return": 0.01,
        },
    )

    analysis = round1_script.analyze_btst_5d_15pct_factor_research_round1(
        reports_root,
        min_closed_cycle_count=1,
        boundary_quarantine_artifact=quarantine_artifact,
    )

    assert analysis["row_count"] == 0
    assert analysis["alpha_beta_gamma_shortlist"] == []
