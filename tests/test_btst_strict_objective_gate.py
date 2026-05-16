from __future__ import annotations

import json
from pathlib import Path

import scripts.btst_strict_objective_gate as btst_strict_objective_gate
from scripts.btst_strict_objective_gate import (
    build_strict_btst_objective_gate,
    load_strict_btst_objective_gate_from_markdown,
    parse_objective_monitor_markdown,
)


def test_parse_objective_monitor_markdown_extracts_tradeable_rejected_and_false_negatives(tmp_path: Path) -> None:
    path = tmp_path / "objective.md"
    path.write_text(
        "\n".join(
            [
                "## Surface Summary",
                "- tradeable_surface: closed_cycle_count=17, positive_rate=0.4706, mean_t_plus_2_return=-0.0057, verdict=below_strict_btst_objective",
                "## Decision Leaderboard",
                "- rejected: closed_cycle_count=81, positive_rate=0.5432, mean_t_plus_2_return=0.0078, verdict=below_strict_btst_objective",
                "## False Negative Strict Goal Cases",
                "- 2026-02-26 000960: decision=blocked, source=watchlist_filter_diagnostics, t_plus_2_close_return=0.21, score_target=0.0",
            ]
        ),
        encoding="utf-8",
    )

    payload = parse_objective_monitor_markdown(path)

    assert payload["Surface Summary"]["tradeable_surface"]["positive_rate"] == 0.4706
    assert payload["Decision Leaderboard"]["rejected"]["mean_t_plus_2_return"] == 0.0078
    assert payload["False Negative Strict Goal Cases"][0]["ticker"] == "000960"


def test_build_strict_btst_objective_gate_blocks_when_rejected_outperforms_tradeable_surface() -> None:
    gate = build_strict_btst_objective_gate(
        {
            "Surface Summary": {
                "tradeable_surface": {"positive_rate": 0.4706, "mean_t_plus_2_return": -0.0057},
            },
            "Decision Leaderboard": {
                "rejected": {"positive_rate": 0.5432, "mean_t_plus_2_return": 0.0078},
            },
            "False Negative Strict Goal Cases": [{"ticker": "000960"}],
        }
    )

    assert gate["action"] == "hold"
    assert "rejected_outperforms_tradeable_surface" in gate["blockers"]
    assert "strict_false_negative_cases_present" in gate["blockers"]


def test_build_strict_btst_objective_gate_adds_structural_blockers() -> None:
    structural_guardrail = {
        "blocker_candidate": True,
        "excessive_window_count": 2,
        "excessive_window_labels": ["10d", "20d"],
    }

    gate = build_strict_btst_objective_gate(
        {
            "Surface Summary": {
                "tradeable_surface": {"positive_rate": 0.4706, "mean_t_plus_2_return": -0.0057},
            },
            "Decision Leaderboard": {
                "rejected": {"positive_rate": 0.40, "mean_t_plus_2_return": -0.01},
            },
            "False Negative Strict Goal Cases": [],
        },
        structural_guardrail=structural_guardrail,
    )

    assert gate["action"] == "hold"
    assert "structural_expansion_repeated_across_windows" in gate["blockers"]
    assert gate["structural_guardrail"] == structural_guardrail


def test_build_strict_btst_objective_gate_ignores_non_boolean_structural_blocker_candidate() -> None:
    structural_guardrail = {
        "blocker_candidate": "false",
        "excessive_window_count": 2,
        "excessive_window_labels": ["10d", "20d"],
    }

    gate = build_strict_btst_objective_gate(
        {
            "Surface Summary": {
                "tradeable_surface": {"positive_rate": 0.4706, "mean_t_plus_2_return": -0.0057},
            },
            "Decision Leaderboard": {
                "rejected": {"positive_rate": 0.40, "mean_t_plus_2_return": -0.01},
            },
            "False Negative Strict Goal Cases": [],
        },
        structural_guardrail=structural_guardrail,
    )

    assert gate["action"] == "promote"
    assert "structural_expansion_repeated_across_windows" not in gate["blockers"]
    assert gate["structural_guardrail"] == structural_guardrail


def test_btst_strict_objective_gate_main_writes_hold_artifacts(tmp_path: Path) -> None:
    input_md = tmp_path / "objective.md"
    structural_json = tmp_path / "structural.json"
    output_json = tmp_path / "gate.json"
    output_md = tmp_path / "gate.md"
    input_md.write_text(
        "\n".join(
            [
                "## Surface Summary",
                "- tradeable_surface: closed_cycle_count=17, positive_rate=0.4706, mean_t_plus_2_return=-0.0057, verdict=below_strict_btst_objective",
                "## Decision Leaderboard",
                "- rejected: closed_cycle_count=81, positive_rate=0.5432, mean_t_plus_2_return=0.0078, verdict=below_strict_btst_objective",
                "## False Negative Strict Goal Cases",
                "- 2026-02-26 000960: decision=blocked, source=watchlist_filter_diagnostics, t_plus_2_close_return=0.21, score_target=0.0",
            ]
        ),
        encoding="utf-8",
    )
    structural_json.write_text(
        json.dumps(
            {
                "structural_guardrail": {
                    "blocker_candidate": True,
                    "excessive_window_count": 2,
                    "excessive_window_labels": ["10d", "20d"],
                }
            }
        ),
        encoding="utf-8",
    )

    result = btst_strict_objective_gate.main(
        [
            "--input-md",
            str(input_md),
            "--structural-json",
            str(structural_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["action"] == "hold"
    assert "strict_false_negative_cases_present" in payload["blockers"]
    assert "structural_expansion_repeated_across_windows" in payload["blockers"]
    assert payload["structural_guardrail"]["excessive_window_count"] == 2
    markdown = output_md.read_text(encoding="utf-8")
    assert "Strict BTST Objective Gate" in markdown
    assert "rejected_outperforms_tradeable_surface" in markdown


def test_load_strict_btst_objective_gate_ignores_malformed_structural_sidecar_top_level(tmp_path: Path) -> None:
    input_md = tmp_path / "objective.md"
    structural_json = tmp_path / "structural.json"
    input_md.write_text(
        "\n".join(
            [
                "## Surface Summary",
                "- tradeable_surface: closed_cycle_count=17, positive_rate=0.4706, mean_t_plus_2_return=-0.0057, verdict=below_strict_btst_objective",
                "## Decision Leaderboard",
                "- rejected: closed_cycle_count=12, positive_rate=0.40, mean_t_plus_2_return=-0.01, verdict=below_strict_btst_objective",
                "## False Negative Strict Goal Cases",
            ]
        ),
        encoding="utf-8",
    )
    structural_json.write_text("1", encoding="utf-8")

    payload = load_strict_btst_objective_gate_from_markdown(input_md, structural_json_path=structural_json)

    assert payload["action"] == "promote"
    assert payload["blockers"] == []
    assert payload["structural_guardrail"] is None


def test_btst_strict_objective_gate_main_ignores_malformed_structural_guardrail_payload(tmp_path: Path) -> None:
    input_md = tmp_path / "objective.md"
    structural_json = tmp_path / "structural.json"
    output_json = tmp_path / "gate.json"
    output_md = tmp_path / "gate.md"
    input_md.write_text(
        "\n".join(
            [
                "## Surface Summary",
                "- tradeable_surface: closed_cycle_count=17, positive_rate=0.4706, mean_t_plus_2_return=-0.0057, verdict=below_strict_btst_objective",
                "## Decision Leaderboard",
                "- rejected: closed_cycle_count=12, positive_rate=0.40, mean_t_plus_2_return=-0.01, verdict=below_strict_btst_objective",
                "## False Negative Strict Goal Cases",
            ]
        ),
        encoding="utf-8",
    )
    structural_json.write_text(json.dumps({"structural_guardrail": "bad"}), encoding="utf-8")

    result = btst_strict_objective_gate.main(
        [
            "--input-md",
            str(input_md),
            "--structural-json",
            str(structural_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["action"] == "promote"
    assert payload["blockers"] == []
    assert payload["structural_guardrail"] is None


def test_load_strict_btst_objective_gate_ignores_unparseable_structural_sidecar(tmp_path: Path) -> None:
    input_md = tmp_path / "objective.md"
    structural_json = tmp_path / "structural.json"
    input_md.write_text(
        "\n".join(
            [
                "## Surface Summary",
                "- tradeable_surface: closed_cycle_count=17, positive_rate=0.4706, mean_t_plus_2_return=-0.0057, verdict=below_strict_btst_objective",
                "## Decision Leaderboard",
                "- rejected: closed_cycle_count=12, positive_rate=0.40, mean_t_plus_2_return=-0.01, verdict=below_strict_btst_objective",
                "## False Negative Strict Goal Cases",
            ]
        ),
        encoding="utf-8",
    )
    structural_json.write_text("{", encoding="utf-8")

    payload = load_strict_btst_objective_gate_from_markdown(input_md, structural_json_path=structural_json)

    assert payload["action"] == "promote"
    assert payload["blockers"] == []
    assert payload["structural_guardrail"] is None
