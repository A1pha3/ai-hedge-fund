import sys
from pathlib import Path

import scripts.analyze_btst_5d_15pct_boundary_contract_fill_path as fill_script


def test_analyze_btst_5d_15pct_boundary_contract_fill_path_builds_repair_and_governance_boards(tmp_path: Path) -> None:
    rows = [
        {
            "candidate_source": "short_trade_boundary",
            "ticker": "001309",
            "trade_date": "20260324",
            "breakout_freshness": 0.9,
            "trend_acceleration": 0.8,
            "volume_expansion_quality": 0.7,
            "close_strength": 0.6,
            "t0_tail_strength": 0.5,
            "trend_continuation": 0.4,
            "short_term_reversal": 0.3,
            "boundary_context": {
                "breakout_freshness": 0.9,
                "trend_acceleration": 0.8,
                "volume_expansion_quality": 0.7,
                "close_strength": 0.6,
                "t0_tail_strength": 0.5,
                "trend_continuation": 0.4,
                "short_term_reversal": 0.3,
            },
            "metadata_keys": ["candidate_source", "layer_c_decision", "replay_context"],
        },
        {
            "candidate_source": "layer_b_boundary",
            "ticker": "300111",
            "trade_date": "20260324",
            "breakout_freshness": 0.9,
            "close_strength": 0.4,
            "boundary_context": {
                "breakout_freshness": 0.9,
                "close_strength": 0.4,
            },
            "metadata_keys": ["candidate_source", "layer_c_decision"],
        },
        {
            "candidate_source": "layer_b_boundary",
            "ticker": "600123",
            "trade_date": "20260324",
            "breakout_freshness": 0.9,
            "metadata_keys": ["candidate_source", "layer_c_decision"],
        },
    ]

    analysis = fill_script.analyze_btst_5d_15pct_boundary_contract_fill_path_from_rows(rows)

    assert analysis["boundary_row_count"] == 3
    assert analysis["repair_status_board"][0]["repair_status"] == "fully_repaired_boundary_contract"
    assert analysis["repair_status_board"][1]["repair_status"] == "partially_repaired_boundary_contract"
    assert analysis["repair_status_board"][2]["repair_status"] == "irrecoverable_boundary_contract"
    assert analysis["repair_status_board"][0]["recovered_core_payload"] == rows[0]["boundary_context"]
    assert analysis["repair_summary_board"][0] == {
        "fully_repaired_row_count": 1,
        "partially_repaired_row_count": 1,
        "irrecoverable_row_count": 1,
    }
    assert analysis["repair_source_summary_board"] == [
        {
            "candidate_source": "layer_b_boundary",
            "row_count": 2,
            "fully_repaired_row_count": 0,
            "partially_repaired_row_count": 1,
            "irrecoverable_row_count": 1,
        },
        {
            "candidate_source": "short_trade_boundary",
            "row_count": 1,
            "fully_repaired_row_count": 1,
            "partially_repaired_row_count": 0,
            "irrecoverable_row_count": 0,
        },
    ]
    assert analysis["governance_decision_board"][0]["action"] == "quarantine_boundary_surface"


def test_analyze_btst_5d_15pct_boundary_contract_fill_path_consumes_boundary_rows_from_inspection(tmp_path: Path, monkeypatch) -> None:
    captured_rows = [
        {
            "candidate_source": "short_trade_boundary",
            "ticker": "001309",
            "trade_date": "20260324",
            "breakout_freshness": 0.9,
            "trend_acceleration": 0.8,
            "volume_expansion_quality": 0.7,
            "close_strength": 0.6,
            "t0_tail_strength": 0.5,
            "trend_continuation": 0.4,
            "short_term_reversal": 0.3,
            "boundary_context": {
                "breakout_freshness": 0.9,
                "trend_acceleration": 0.8,
                "volume_expansion_quality": 0.7,
                "close_strength": 0.6,
                "t0_tail_strength": 0.5,
                "trend_continuation": 0.4,
                "short_term_reversal": 0.3,
            },
            "metadata_keys": ["candidate_source", "layer_c_decision", "replay_context"],
        },
        {
            "candidate_source": "layer_b_boundary",
            "ticker": "300111",
            "trade_date": "20260324",
            "breakout_freshness": 0.9,
            "boundary_context": {
                "breakout_freshness": 0.9,
            },
            "metadata_keys": ["candidate_source", "layer_c_decision"],
        },
    ]

    monkeypatch.setattr(
        fill_script,
        "analyze_btst_5d_15pct_boundary_contract_inspection",
        lambda reports_root: {
            "generated_at": "2026-03-24T00:00:00Z",
            "reports_root": str(reports_root),
            "row_count": 2,
            "boundary_row_count": 2,
            "boundary_rows": captured_rows,
            "source_comparison_board": [],
            "governance_recommendation_board": [],
        },
    )

    analysis = fill_script.analyze_btst_5d_15pct_boundary_contract_fill_path(tmp_path / "data" / "reports")

    assert analysis["boundary_row_count"] == 2
    assert analysis["repair_summary_board"][0]["fully_repaired_row_count"] == 1
    assert analysis["repair_summary_board"][0]["partially_repaired_row_count"] == 1
    assert analysis["repair_summary_board"][0]["irrecoverable_row_count"] == 0
    assert analysis["repair_source_summary_board"] == [
        {
            "candidate_source": "layer_b_boundary",
            "row_count": 1,
            "fully_repaired_row_count": 0,
            "partially_repaired_row_count": 1,
            "irrecoverable_row_count": 0,
        },
        {
            "candidate_source": "short_trade_boundary",
            "row_count": 1,
            "fully_repaired_row_count": 1,
            "partially_repaired_row_count": 0,
            "irrecoverable_row_count": 0,
        },
    ]
    assert analysis["governance_decision_board"][0]["action"] == "hold_boundary_repair_until_more_context"


def test_render_btst_5d_15pct_boundary_contract_fill_path_markdown_includes_source_summary_board() -> None:
    analysis = {
        "boundary_row_count": 2,
        "repair_summary_board": [
            {
                "fully_repaired_row_count": 1,
                "partially_repaired_row_count": 1,
                "irrecoverable_row_count": 0,
            }
        ],
        "repair_source_summary_board": [
            {
                "candidate_source": "layer_b_boundary",
                "row_count": 1,
                "fully_repaired_row_count": 0,
                "partially_repaired_row_count": 1,
                "irrecoverable_row_count": 0,
            },
            {
                "candidate_source": "short_trade_boundary",
                "row_count": 1,
                "fully_repaired_row_count": 1,
                "partially_repaired_row_count": 0,
                "irrecoverable_row_count": 0,
            },
        ],
        "governance_decision_board": [
            {
                "action": "hold_boundary_repair_until_more_context",
                "reason": "boundary fill-path outcome is governed by irrecoverable and partial repair counts",
            }
        ],
    }

    markdown = fill_script.render_btst_5d_15pct_boundary_contract_fill_path_markdown(analysis)

    assert "## repair_source_summary_board" in markdown
    assert "- layer_b_boundary: row_count=1, fully_repaired_row_count=0, partially_repaired_row_count=1, irrecoverable_row_count=0" in markdown
    assert "- short_trade_boundary: row_count=1, fully_repaired_row_count=1, partially_repaired_row_count=0, irrecoverable_row_count=0" in markdown


def test_main_writes_json_and_markdown_and_prints_compact_summary(tmp_path: Path, monkeypatch, capsys) -> None:
    analysis = {
        "generated_at": "2026-03-24T00:00:00Z",
        "boundary_row_count": 2,
        "repair_summary_board": [
            {
                "fully_repaired_row_count": 1,
                "partially_repaired_row_count": 1,
                "irrecoverable_row_count": 0,
            }
        ],
        "repair_source_summary_board": [
            {
                "candidate_source": "short_trade_boundary",
                "row_count": 2,
                "fully_repaired_row_count": 1,
                "partially_repaired_row_count": 1,
                "irrecoverable_row_count": 0,
            }
        ],
        "governance_decision_board": [
            {
                "action": "hold_boundary_repair_until_more_context",
                "reason": "boundary fill-path outcome is governed by irrecoverable and partial repair counts",
            }
        ],
    }

    monkeypatch.setattr(
        fill_script,
        "analyze_btst_5d_15pct_boundary_contract_inspection",
        lambda reports_root: {
            "generated_at": "2026-03-24T00:00:00Z",
            "reports_root": str(reports_root),
            "row_count": 2,
            "boundary_row_count": 2,
            "boundary_rows": [],
            "source_comparison_board": [],
            "governance_recommendation_board": [],
        },
    )
    monkeypatch.setattr(fill_script, "analyze_btst_5d_15pct_boundary_contract_fill_path", lambda reports_root: analysis)
    output_json = tmp_path / "fill_path.json"
    output_md = tmp_path / "fill_path.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "analyze_btst_5d_15pct_boundary_contract_fill_path.py",
            "--reports-root",
            str(tmp_path / "reports"),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
    )

    fill_script.main()

    captured = capsys.readouterr().out.strip()
    assert output_json.exists()
    assert output_md.exists()
    json_text = output_json.read_text(encoding="utf-8")
    md_text = output_md.read_text(encoding="utf-8")
    assert '"boundary_row_count": 2' in json_text
    assert '"governance_decision_board"' in json_text
    assert "## governance_decision_board" in md_text
    assert captured
    assert "\n" not in captured
    assert not captured.lstrip().startswith("{")
    assert "boundary_row_count=2" in captured


def test_fill_path_script_avoids_same_quote_nested_fstring_expression() -> None:
    source = Path(fill_script.__file__).read_text(encoding="utf-8")

    assert 'print(f"fill_path analysis: boundary_row_count={analysis.get("boundary_row_count")}' not in source
