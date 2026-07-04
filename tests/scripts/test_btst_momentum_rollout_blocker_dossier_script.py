from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.btst_momentum_rollout_blocker_dossier as dossier


def test_build_momentum_rollout_blocker_dossier_groups_blockers_by_family() -> None:
    payload = dossier.build_momentum_rollout_blocker_dossier(
        [
            "missing_projected_theme_exposure_delta_vs_default",
            "win_rate_window_trend_regressed_vs_momentum_optimized",
            "downside_p10_regressed_vs_default",
            "mystery_blocker",
        ]
    )

    assert payload["blocker_count"] == 4
    assert payload["families"]["missing_observability"]["count"] == 1
    assert payload["families"]["cross_window_stability"]["count"] == 1
    assert payload["families"]["risk_payoff_regression"]["count"] == 1
    assert payload["unclassified_blockers"] == ["mystery_blocker"]
    assert payload["dominant_family"] in {
        "missing_observability",
        "cross_window_stability",
        "risk_payoff_regression",
    }


def test_main_reads_markdown_and_writes_json_and_markdown_outputs(tmp_path: Path) -> None:
    input_md = tmp_path / "btst_latest_optimized_profile.md"
    output_json = tmp_path / "dossier.json"
    output_md = tmp_path / "dossier.md"
    input_md.write_text(
        "# Parameter Search Report\n\nRollout Blockers:\n- `missing_projected_theme_exposure_delta_vs_default`\n- `downside_p10_regressed_vs_default`\n- `unknown_hold_reason`\n",
        encoding="utf-8",
    )

    result = dossier.main(
        [
            "--input-md",
            str(input_md),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["blocker_count"] == 3
    assert data["families"]["missing_observability"]["count"] == 1
    assert data["families"]["risk_payoff_regression"]["count"] == 1
    assert data["unclassified_blockers"] == ["unknown_hold_reason"]
    markdown = output_md.read_text(encoding="utf-8")
    assert "# Momentum Rollout Blocker Dossier" in markdown
    assert "unknown_hold_reason" in markdown


def test_main_fails_closed_when_rollout_blockers_section_is_missing(tmp_path: Path) -> None:
    input_md = tmp_path / "btst_latest_optimized_profile.md"
    output_json = tmp_path / "dossier.json"
    output_md = tmp_path / "dossier.md"
    input_md.write_text("# Parameter Search Report\n\nNo rollout blocker section here.\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="Rollout Blockers"):
        dossier.main(
            [
                "--input-md",
                str(input_md),
                "--output-json",
                str(output_json),
                "--output-md",
                str(output_md),
            ]
        )


def test_parse_rollout_blockers_keeps_blockers_after_blank_lines() -> None:
    markdown_text = "# Parameter Search Report\n\n" "Rollout Blockers:\n" "- `missing_projected_theme_exposure_delta_vs_default`\n" "\n" "- `downside_p10_regressed_vs_default`\n" "\n" "- `unknown_hold_reason`\n"

    assert dossier.parse_rollout_blockers_from_markdown(markdown_text) == [
        "missing_projected_theme_exposure_delta_vs_default",
        "downside_p10_regressed_vs_default",
        "unknown_hold_reason",
    ]


def test_main_fails_closed_when_rollout_blockers_section_is_explicitly_empty(tmp_path: Path) -> None:
    input_md = tmp_path / "btst_latest_optimized_profile.md"
    output_json = tmp_path / "dossier.json"
    output_md = tmp_path / "dossier.md"
    input_md.write_text("# Parameter Search Report\n\nRollout Blockers:\n\n## Next Section\n- note\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="Rollout Blockers"):
        dossier.main(
            [
                "--input-md",
                str(input_md),
                "--output-json",
                str(output_json),
                "--output-md",
                str(output_md),
            ]
        )
