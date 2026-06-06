import json
from pathlib import Path

import pytest

import scripts.btst_momentum_stability_retune_surface as surface


def test_build_retune_surface_keeps_search_local_and_freezes_zero_weights() -> None:
    payload = surface.build_momentum_stability_retune_surface(
        best_params={
            "select_threshold": 0.46,
            "recency_half_life_days": 180,
            "trend_acceleration_weight": 0.22,
            "close_strength_weight": 0.12,
            "volume_expansion_quality_weight": 0.16,
            "catalyst_freshness_weight": 0.14,
            "momentum_strength_weight": 0.0,
            "short_term_reversal_weight": 0.0,
        },
        triage={"action": "parameter_retune_next", "dominant_family": "cross_window_stability"},
    )

    assert payload["retune_allowed"] is True
    assert payload["fixed_params"] == {
        "momentum_strength_weight": 0.0,
        "short_term_reversal_weight": 0.0,
    }
    assert payload["grid"]["select_threshold"] == [0.42, 0.46, 0.5]
    assert payload["grid"]["recency_half_life_days"] == [120, 180, 240]


def test_build_retune_surface_fails_closed_when_triage_does_not_allow_parameter_retune() -> None:
    with pytest.raises(SystemExit, match="parameter_retune_next"):
        surface.build_momentum_stability_retune_surface(
            best_params={"select_threshold": 0.46},
            triage={"action": "retain_hold", "dominant_family": "risk_payoff_regression"},
        )


def test_main_writes_surface_outputs(tmp_path: Path) -> None:
    source_json = tmp_path / "param_search.json"
    triage_json = tmp_path / "triage.json"
    output_json = tmp_path / "surface.json"
    output_md = tmp_path / "surface.md"
    source_json.write_text(
        json.dumps({"best_params": {"select_threshold": 0.46, "recency_half_life_days": 180, "trend_acceleration_weight": 0.22, "close_strength_weight": 0.12, "volume_expansion_quality_weight": 0.16, "catalyst_freshness_weight": 0.14, "momentum_strength_weight": 0.0, "short_term_reversal_weight": 0.0}}),
        encoding="utf-8",
    )
    triage_json.write_text(json.dumps({"action": "parameter_retune_next", "dominant_family": "cross_window_stability"}), encoding="utf-8")

    result = surface.main(
        [
            "--source-json",
            str(source_json),
            "--triage-json",
            str(triage_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["retune_allowed"] is True
    assert output_md.exists()


def test_main_fails_when_source_json_is_not_object(tmp_path: Path) -> None:
    source_json = tmp_path / "param_search.json"
    triage_json = tmp_path / "triage.json"
    source_json.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    triage_json.write_text(json.dumps({"action": "parameter_retune_next", "dominant_family": "cross_window_stability"}), encoding="utf-8")

    with pytest.raises(SystemExit):
        surface.main(
            [
                "--source-json",
                str(source_json),
                "--triage-json",
                str(triage_json),
                "--output-json",
                str(tmp_path / "out.json"),
                "--output-md",
                str(tmp_path / "out.md"),
            ]
        )


def test_main_fails_when_best_params_not_object(tmp_path: Path) -> None:
    source_json = tmp_path / "param_search.json"
    triage_json = tmp_path / "triage.json"
    source_json.write_text(json.dumps({"best_params": ["not", "object"]}), encoding="utf-8")
    triage_json.write_text(json.dumps({"action": "parameter_retune_next", "dominant_family": "cross_window_stability"}), encoding="utf-8")

    with pytest.raises(SystemExit):
        surface.main(
            [
                "--source-json",
                str(source_json),
                "--triage-json",
                str(triage_json),
                "--output-json",
                str(tmp_path / "out.json"),
                "--output-md",
                str(tmp_path / "out.md"),
            ]
        )


def test_build_fails_when_fixed_weights_missing_or_non_numeric() -> None:
    # missing fixed-weight keys should fail-closed
    with pytest.raises(SystemExit):
        surface.build_momentum_stability_retune_surface(
            best_params={
                "select_threshold": 0.46,
                "recency_half_life_days": 180,
                "trend_acceleration_weight": 0.22,
                "close_strength_weight": 0.12,
                "volume_expansion_quality_weight": 0.16,
                "catalyst_freshness_weight": 0.14,
            },
            triage={"action": "parameter_retune_next", "dominant_family": "cross_window_stability"},
        )

    # non-numeric value should fail
    with pytest.raises(SystemExit):
        surface.build_momentum_stability_retune_surface(
            best_params={
                "select_threshold": "not-a-number",
                "recency_half_life_days": 180,
                "trend_acceleration_weight": 0.22,
                "close_strength_weight": 0.12,
                "volume_expansion_quality_weight": 0.16,
                "catalyst_freshness_weight": 0.14,
                "momentum_strength_weight": 0.0,
                "short_term_reversal_weight": 0.0,
            },
            triage={"action": "parameter_retune_next", "dominant_family": "cross_window_stability"},
        )


def test_main_fails_when_triage_json_is_not_object(tmp_path: Path) -> None:
    source_json = tmp_path / "param_search.json"
    triage_json = tmp_path / "triage.json"
    source_json.write_text(
        json.dumps({"best_params": {"select_threshold": 0.46, "recency_half_life_days": 180, "trend_acceleration_weight": 0.22, "close_strength_weight": 0.12, "volume_expansion_quality_weight": 0.16, "catalyst_freshness_weight": 0.14, "momentum_strength_weight": 0.0, "short_term_reversal_weight": 0.0}}),
        encoding="utf-8",
    )
    triage_json.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    with pytest.raises(SystemExit):
        surface.main(
            [
                "--source-json",
                str(source_json),
                "--triage-json",
                str(triage_json),
                "--output-json",
                str(tmp_path / "out.json"),
                "--output-md",
                str(tmp_path / "out.md"),
            ]
        )


def test_main_fails_closed_when_source_file_missing(tmp_path: Path) -> None:
    triage_json = tmp_path / "triage.json"
    triage_json.write_text(json.dumps({"action": "parameter_retune_next", "dominant_family": "cross_window_stability"}), encoding="utf-8")

    with pytest.raises(SystemExit, match="source file not found"):
        surface.main(
            [
                "--source-json",
                str(tmp_path / "missing.json"),
                "--triage-json",
                str(triage_json),
                "--output-json",
                str(tmp_path / "out.json"),
                "--output-md",
                str(tmp_path / "out.md"),
            ]
        )


def test_main_fails_closed_when_source_json_is_invalid(tmp_path: Path) -> None:
    source_json = tmp_path / "param_search.json"
    triage_json = tmp_path / "triage.json"
    source_json.write_text("{invalid", encoding="utf-8")
    triage_json.write_text(json.dumps({"action": "parameter_retune_next", "dominant_family": "cross_window_stability"}), encoding="utf-8")

    with pytest.raises(SystemExit, match="invalid JSON in source file"):
        surface.main(
            [
                "--source-json",
                str(source_json),
                "--triage-json",
                str(triage_json),
                "--output-json",
                str(tmp_path / "out.json"),
                "--output-md",
                str(tmp_path / "out.md"),
            ]
        )


def test_main_fails_closed_when_output_path_is_unwritable(tmp_path: Path) -> None:
    source_json = tmp_path / "param_search.json"
    triage_json = tmp_path / "triage.json"
    source_json.write_text(
        json.dumps({"best_params": {"select_threshold": 0.46, "recency_half_life_days": 180, "trend_acceleration_weight": 0.22, "close_strength_weight": 0.12, "volume_expansion_quality_weight": 0.16, "catalyst_freshness_weight": 0.14, "momentum_strength_weight": 0.0, "short_term_reversal_weight": 0.0}}),
        encoding="utf-8",
    )
    triage_json.write_text(json.dumps({"action": "parameter_retune_next", "dominant_family": "cross_window_stability"}), encoding="utf-8")

    with pytest.raises(SystemExit, match="unable to write output JSON"):
        surface.main(
            [
                "--source-json",
                str(source_json),
                "--triage-json",
                str(triage_json),
                "--output-json",
                str(tmp_path / "missing-dir" / "out.json"),
                "--output-md",
                str(tmp_path / "out.md"),
            ]
        )
