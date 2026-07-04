from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import scripts.btst_momentum_rollout_window_attribution as attribution


def _make_scratch_dir(name: str) -> Path:
    scratch_dir = Path("tests/.scratch_btst_momentum_rollout_window_attribution") / name
    if scratch_dir.exists():
        shutil.rmtree(scratch_dir)
    scratch_dir.mkdir(parents=True, exist_ok=False)
    return scratch_dir


def test_build_momentum_rollout_window_attribution_flags_missing_metric_family() -> None:
    payload = attribution.build_momentum_rollout_window_attribution(
        rollout_blockers=[
            "missing_projected_theme_exposure_delta_vs_default",
            "missing_incremental_theme_exposure_delta_vs_default",
        ],
        window_rows=[
            {"report_label": "window_a", "projected_theme_exposure_delta": None, "incremental_theme_exposure_delta": None},
            {"report_label": "window_b", "projected_theme_exposure_delta": 0.01, "incremental_theme_exposure_delta": None},
        ],
    )

    assert payload["dominant_family"] == "missing_observability"
    assert payload["windows_missing_theme_exposure"] == ["window_a", "window_b"]


def test_main_writes_attribution_outputs() -> None:
    scratch_dir = _make_scratch_dir("main_writes_attribution_outputs")
    try:
        rollout_json = scratch_dir / "rollout.json"
        source_json = scratch_dir / "source.json"
        output_json = scratch_dir / "attribution.json"
        output_md = scratch_dir / "attribution.md"
        rollout_json.write_text(json.dumps({"blockers": ["win_rate_window_trend_regressed_vs_default"]}), encoding="utf-8")
        source_json.write_text(json.dumps({"window_rows": [{"report_label": "window_a", "win_rate_window_trend_delta": -0.04}]}), encoding="utf-8")

        result = attribution.main(
            [
                "--rollout-json",
                str(rollout_json),
                "--source-json",
                str(source_json),
                "--output-json",
                str(output_json),
                "--output-md",
                str(output_md),
            ]
        )

        assert result == 0
        data = json.loads(output_json.read_text(encoding="utf-8"))
        assert data["window_count"] == 1
        assert data["dominant_family"] == "cross_window_stability"
        assert output_md.exists()
    finally:
        if scratch_dir.exists():
            shutil.rmtree(scratch_dir)


def test_build_momentum_rollout_window_attribution_tracks_cross_window_regressions() -> None:
    payload = attribution.build_momentum_rollout_window_attribution(
        rollout_blockers=["win_rate_window_trend_regressed_vs_default"],
        window_rows=[
            {"report_label": "window_a", "win_rate_window_trend_delta": -0.04},
            {"report_label": "window_b", "win_rate_window_trend_delta": 0.02},
        ],
    )

    assert payload["dominant_family"] == "cross_window_stability"
    assert payload["dominant_family_windows"] == ["window_a"]
    assert payload["windows_by_blocker"]["win_rate_window_trend_regressed_vs_default"] == ["window_a"]


def test_build_momentum_rollout_window_attribution_tracks_positive_direction_regressions() -> None:
    payload = attribution.build_momentum_rollout_window_attribution(
        rollout_blockers=["win_rate_ci_width_regressed_vs_default", "param_drift_score_regressed_vs_default"],
        window_rows=[
            {"report_label": "window_a", "win_rate_ci_width_delta": 0.03, "param_drift_score_delta": 1.2},
            {"report_label": "window_b", "win_rate_ci_width_delta": -0.01, "param_drift_score_delta": 0.0},
        ],
    )

    assert payload["dominant_family"] == "cross_window_stability"
    assert payload["windows_by_blocker"]["win_rate_ci_width_regressed_vs_default"] == ["window_a"]
    assert payload["windows_by_blocker"]["param_drift_score_regressed_vs_default"] == ["window_a"]
    assert payload["dominant_family_windows"] == ["window_a"]


def test_build_momentum_rollout_window_attribution_allows_empty_blockers() -> None:
    payload = attribution.build_momentum_rollout_window_attribution(
        rollout_blockers=[],
        window_rows=[{"report_label": "window_a", "projected_theme_exposure_delta": 0.01, "incremental_theme_exposure_delta": 0.02}],
    )

    assert payload["blocker_count"] == 0
    assert payload["dominant_family"] is None
    assert payload["windows_missing_theme_exposure"] == []


def test_build_momentum_rollout_window_attribution_fails_closed_on_blank_blocker_strings() -> None:
    with pytest.raises(SystemExit, match="rollout_blockers"):
        attribution.build_momentum_rollout_window_attribution(
            rollout_blockers=["   "],
            window_rows=[{"report_label": "window_a", "projected_theme_exposure_delta": 0.01, "incremental_theme_exposure_delta": 0.02}],
        )


def test_build_momentum_rollout_window_attribution_fails_closed_on_duplicate_blockers() -> None:
    with pytest.raises(SystemExit, match="duplicate"):
        attribution.build_momentum_rollout_window_attribution(
            rollout_blockers=[
                "win_rate_window_trend_regressed_vs_default",
                "win_rate_window_trend_regressed_vs_default",
            ],
            window_rows=[{"report_label": "window_a", "win_rate_window_trend_delta": -0.04}],
        )


def test_build_momentum_rollout_window_attribution_fails_closed_on_malformed_window_rows() -> None:
    with pytest.raises(SystemExit, match="report_label"):
        attribution.build_momentum_rollout_window_attribution(
            rollout_blockers=["missing_projected_theme_exposure_delta_vs_default"],
            window_rows=[{"projected_theme_exposure_delta": None}],
        )


def test_build_momentum_rollout_window_attribution_fails_closed_on_duplicate_report_labels() -> None:
    with pytest.raises(SystemExit, match="report_label"):
        attribution.build_momentum_rollout_window_attribution(
            rollout_blockers=["missing_projected_theme_exposure_delta_vs_default"],
            window_rows=[
                {"report_label": "window_a", "projected_theme_exposure_delta": None, "incremental_theme_exposure_delta": 0.01},
                {"report_label": "window_a", "projected_theme_exposure_delta": 0.02, "incremental_theme_exposure_delta": None},
            ],
        )


def test_main_reads_dossier_style_rollout_json() -> None:
    scratch_dir = _make_scratch_dir("main_reads_dossier_style_rollout_json")
    try:
        rollout_json = scratch_dir / "rollout.json"
        source_json = scratch_dir / "source.json"
        output_json = scratch_dir / "attribution.json"
        output_md = scratch_dir / "attribution.md"
        rollout_json.write_text(
            json.dumps(
                {
                    "families": {
                        "missing_observability": {"blockers": ["missing_projected_theme_exposure_delta_vs_default"]},
                        "cross_window_stability": {"blockers": []},
                        "risk_payoff_regression": {"blockers": []},
                    }
                }
            ),
            encoding="utf-8",
        )
        source_json.write_text(
            json.dumps({"window_rows": [{"report_label": "window_a", "projected_theme_exposure_delta": None, "incremental_theme_exposure_delta": 0.01}]}),
            encoding="utf-8",
        )

        result = attribution.main(
            [
                "--rollout-json",
                str(rollout_json),
                "--source-json",
                str(source_json),
                "--output-json",
                str(output_json),
                "--output-md",
                str(output_md),
            ]
        )

        assert result == 0
        data = json.loads(output_json.read_text(encoding="utf-8"))
        assert data["dominant_family"] == "missing_observability"
        assert data["windows_missing_theme_exposure"] == ["window_a"]
        markdown = output_md.read_text(encoding="utf-8")
        assert "# Momentum Rollout Window Attribution" in markdown
        assert "window_a" in markdown
    finally:
        if scratch_dir.exists():
            shutil.rmtree(scratch_dir)


def test_main_reads_comparison_summary_source_json() -> None:
    scratch_dir = _make_scratch_dir("main_reads_comparison_summary_source_json")
    try:
        rollout_json = scratch_dir / "rollout.json"
        source_json = scratch_dir / "source.json"
        output_json = scratch_dir / "attribution.json"
        output_md = scratch_dir / "attribution.md"
        rollout_json.write_text(
            json.dumps(
                {
                    "blockers": [
                        "missing_projected_theme_exposure_delta_vs_default",
                        "win_rate_window_trend_regressed_vs_momentum_optimized",
                    ]
                }
            ),
            encoding="utf-8",
        )
        source_json.write_text(
            json.dumps(
                {
                    "comparison_summary": {
                        "momentum_optimized": {"win_rate_window_trend_delta": -0.04},
                        "default": {"projected_theme_exposure_delta": None, "incremental_theme_exposure_delta": 0.01},
                    }
                }
            ),
            encoding="utf-8",
        )

        result = attribution.main(
            [
                "--rollout-json",
                str(rollout_json),
                "--source-json",
                str(source_json),
                "--output-json",
                str(output_json),
                "--output-md",
                str(output_md),
            ]
        )

        assert result == 0
        data = json.loads(output_json.read_text(encoding="utf-8"))
        assert data["window_count"] == 2
        assert data["windows_missing_theme_exposure"] == ["default"]
        assert data["windows_by_blocker"]["missing_projected_theme_exposure_delta_vs_default"] == ["default"]
        assert data["windows_by_blocker"]["win_rate_window_trend_regressed_vs_momentum_optimized"] == ["momentum_optimized"]
        markdown = output_md.read_text(encoding="utf-8")
        assert "momentum_optimized" in markdown
        assert "default" in markdown
    finally:
        if scratch_dir.exists():
            shutil.rmtree(scratch_dir)


def test_render_momentum_rollout_window_attribution_markdown_uses_safe_code_fences_for_backticks() -> None:
    payload = attribution.build_momentum_rollout_window_attribution(
        rollout_blockers=["win_rate_window_trend_regressed_vs_default"],
        window_rows=[{"report_label": "window`a", "win_rate_window_trend_delta": -0.04}],
    )

    markdown = attribution.render_momentum_rollout_window_attribution_markdown(payload)

    assert "``window`a``" in markdown


def test_main_fails_closed_on_malformed_dossier_blocker_list() -> None:
    scratch_dir = _make_scratch_dir("main_fails_closed_on_malformed_dossier_blocker_list")
    try:
        rollout_json = scratch_dir / "rollout.json"
        source_json = scratch_dir / "source.json"
        output_json = scratch_dir / "attribution.json"
        output_md = scratch_dir / "attribution.md"
        rollout_json.write_text(
            json.dumps(
                {
                    "families": {
                        "missing_observability": {"blockers": "missing_projected_theme_exposure_delta_vs_default"},
                        "cross_window_stability": {"blockers": []},
                        "risk_payoff_regression": {"blockers": []},
                    }
                }
            ),
            encoding="utf-8",
        )
        source_json.write_text(
            json.dumps({"window_rows": [{"report_label": "window_a", "projected_theme_exposure_delta": None, "incremental_theme_exposure_delta": 0.01}]}),
            encoding="utf-8",
        )

        with pytest.raises(SystemExit, match="rollout_blockers"):
            attribution.main(
                [
                    "--rollout-json",
                    str(rollout_json),
                    "--source-json",
                    str(source_json),
                    "--output-json",
                    str(output_json),
                    "--output-md",
                    str(output_md),
                ]
            )
    finally:
        if scratch_dir.exists():
            shutil.rmtree(scratch_dir)


@pytest.mark.parametrize(
    ("family_payload", "expected_message"),
    [
        ({}, "blockers"),
        ({"blockers": None}, "blockers"),
    ],
)
def test_main_fails_closed_when_dossier_family_omits_blockers(family_payload: dict[str, object], expected_message: str) -> None:
    scratch_dir = _make_scratch_dir("main_fails_closed_when_dossier_family_omits_blockers")
    try:
        rollout_json = scratch_dir / "rollout.json"
        source_json = scratch_dir / "source.json"
        output_json = scratch_dir / "attribution.json"
        output_md = scratch_dir / "attribution.md"
        rollout_json.write_text(
            json.dumps(
                {
                    "families": {
                        "missing_observability": family_payload,
                        "cross_window_stability": {"blockers": []},
                        "risk_payoff_regression": {"blockers": []},
                    }
                }
            ),
            encoding="utf-8",
        )
        source_json.write_text(
            json.dumps({"window_rows": [{"report_label": "window_a", "projected_theme_exposure_delta": None, "incremental_theme_exposure_delta": 0.01}]}),
            encoding="utf-8",
        )

        with pytest.raises(SystemExit, match=expected_message):
            attribution.main(
                [
                    "--rollout-json",
                    str(rollout_json),
                    "--source-json",
                    str(source_json),
                    "--output-json",
                    str(output_json),
                    "--output-md",
                    str(output_md),
                ]
            )
    finally:
        if scratch_dir.exists():
            shutil.rmtree(scratch_dir)


def test_main_fails_closed_on_empty_dossier_families() -> None:
    scratch_dir = _make_scratch_dir("main_fails_closed_on_empty_dossier_families")
    try:
        rollout_json = scratch_dir / "rollout.json"
        source_json = scratch_dir / "source.json"
        output_json = scratch_dir / "attribution.json"
        output_md = scratch_dir / "attribution.md"
        rollout_json.write_text(json.dumps({"families": {}}), encoding="utf-8")
        source_json.write_text(
            json.dumps({"window_rows": [{"report_label": "window_a", "projected_theme_exposure_delta": None, "incremental_theme_exposure_delta": 0.01}]}),
            encoding="utf-8",
        )

        with pytest.raises(SystemExit, match="families"):
            attribution.main(
                [
                    "--rollout-json",
                    str(rollout_json),
                    "--source-json",
                    str(source_json),
                    "--output-json",
                    str(output_json),
                    "--output-md",
                    str(output_md),
                ]
            )
    finally:
        if scratch_dir.exists():
            shutil.rmtree(scratch_dir)
