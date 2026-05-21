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
