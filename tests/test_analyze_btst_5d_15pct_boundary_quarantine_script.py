from pathlib import Path
import scripts.analyze_btst_5d_15pct_boundary_contract_inspection as boundary_script
import scripts.analyze_btst_5d_15pct_boundary_quarantine as quarantine_script


def test_analyze_btst_5d_15pct_boundary_quarantine_builds_boards_and_surface_lists(tmp_path: Path, monkeypatch) -> None:
    captured_rows = [
        {
            "ticker": "001309",
            "candidate_source": "short_trade_boundary",
            "root_cause": "boundary_without_explainability",
            "bucket": "missing_all_core_features",
            "boundary_context": {"t0_tail_strength": 0.61},
        },
        {
            "ticker": "300111",
            "candidate_source": "layer_b_boundary",
            "root_cause": "boundary_without_explainability",
            "bucket": "missing_all_core_features",
            "boundary_context": {},
        },
    ]

    monkeypatch.setattr(
        quarantine_script,
        "analyze_btst_5d_15pct_boundary_contract_inspection",
        lambda reports_root: {
            "generated_at": "2026-05-22T00:00:00Z",
            "reports_root": str(reports_root),
            "row_count": 2,
            "boundary_row_count": 2,
            "boundary_rows": captured_rows,
            "source_comparison_board": [],
            "governance_recommendation_board": [],
        },
    )

    analysis = quarantine_script.analyze_btst_5d_15pct_boundary_quarantine(tmp_path / "data" / "reports")

    assert analysis["boundary_row_count"] == 2
    assert analysis["research_surface_lists"] == {
        "allow": [],
        "quarantine": ["001309"],
        "separate_surface": ["300111"],
    }
    assert analysis["governance_decision_board"] == [
        {
            "action": "inspect_candidate_source_contract",
            "row_count": 1,
            "tickers": ["001309"],
        },
        {
            "action": "split_into_separate_research_surface",
            "row_count": 1,
            "tickers": ["300111"],
        },
    ]


def test_analyze_btst_5d_15pct_boundary_quarantine_handles_zero_rows() -> None:
    analysis = quarantine_script.analyze_btst_5d_15pct_boundary_quarantine_from_rows([])

    assert analysis["boundary_row_count"] == 0
    assert analysis["decision_rows"] == []
    assert analysis["research_surface_lists"] == {
        "allow": [],
        "quarantine": [],
        "separate_surface": [],
    }


def test_render_btst_5d_15pct_boundary_quarantine_markdown_includes_surface_lists() -> None:
    markdown = quarantine_script.render_btst_5d_15pct_boundary_quarantine_markdown(
        {
            "boundary_row_count": 1,
            "disposition_summary_board": [{"allow_count": 0, "quarantine_count": 1, "separate_surface_count": 0}],
            "source_summary_board": [{"candidate_source": "short_trade_boundary", "row_count": 1, "quarantine_count": 1, "separate_surface_count": 0, "allow_count": 0}],
            "governance_decision_board": [{"action": "inspect_candidate_source_contract", "row_count": 1, "tickers": ["001309"]}],
            "research_surface_lists": {"allow": [], "quarantine": ["001309"], "separate_surface": []},
        }
    )

    assert "## research_surface_lists" in markdown
    assert "- quarantine: ['001309']" in markdown


def test_analyze_btst_5d_15pct_boundary_quarantine_excludes_repaired_contract_rows(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_boundary_contract"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        '''
        {
          "trade_date": "20260324",
          "selection_targets": {
            "001309": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "breakout_freshness": 0.71,
                  "trend_acceleration": 0.66,
                  "volume_expansion_quality": 0.63,
                  "close_strength": 0.68,
                  "trend_continuation": 0.57,
                  "short_term_reversal": 0.21
                }
              }
            }
          }
        }
        '''.strip(),
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

    analysis = quarantine_script.analyze_btst_5d_15pct_boundary_quarantine(reports_root)

    assert analysis["boundary_row_count"] == 0
    assert analysis["research_surface_lists"] == {
        "allow": [],
        "quarantine": [],
        "separate_surface": [],
    }
