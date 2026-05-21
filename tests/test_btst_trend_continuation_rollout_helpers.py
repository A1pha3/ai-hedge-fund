from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import scripts.btst_trend_continuation_rollout_assessment as trend_continuation_rollout_assessment
from scripts.btst_trend_continuation_rollout_helpers import build_trend_continuation_rollout_assessment


def _build_analysis(
    *,
    keep_baseline_count: int = 0,
    variant_supports_t1_count: int = 1,
    variant_improves_t2_only_count: int = 0,
    mixed_count: int = 0,
    execution_eligible_delta: int = 1,
) -> dict[str, object]:
    return {
        "baseline_profile": "trend_continuation_strength_v2",
        "variant_profile": "trend_continuation_strength_v3",
        "keep_baseline_count": keep_baseline_count,
        "variant_supports_t1_count": variant_supports_t1_count,
        "variant_improves_t2_only_count": variant_improves_t2_only_count,
        "mixed_count": mixed_count,
        "recommendation": "Variant is promising across the observed windows and may be ready for a deeper rollout review.",
        "rows": [
            {
                "report_label": "paper_trading_window_a",
                "window_recommendation": "variant_supports_t1_edge",
                "tradeable_surface_delta": {
                    "next_close_positive_rate": 0.012,
                    "next_close_return_p10": 0.0015,
                    "t_plus_2_close_return_median": 0.001,
                },
                "runtime_activation_attribution": {
                    "selected_count_delta": 0,
                    "near_miss_count_delta": 0,
                    "tradeable_count_delta": 0,
                    "execution_eligible_count_delta": execution_eligible_delta,
                    "guardrail_status_changed": False,
                    "zero_delta_reason": "profile_variant_without_runtime_activation_delta" if execution_eligible_delta == 0 else None,
                },
            }
        ],
    }


def test_build_trend_continuation_rollout_assessment_promotes_with_t1_support_and_execution_evidence() -> None:
    assessment = build_trend_continuation_rollout_assessment(_build_analysis())

    assert assessment["action"] == "promote"
    assert assessment["blockers"] == []
    assert assessment["execution_eligible_evidence"] == {
        "positive_window_count": 1,
        "non_halt_execution_eligible_count": 1,
        "has_positive_execution_eligible_evidence": True,
    }


def test_build_trend_continuation_rollout_assessment_holds_when_any_window_keeps_baseline() -> None:
    assessment = build_trend_continuation_rollout_assessment(_build_analysis(keep_baseline_count=1, variant_supports_t1_count=0))

    assert assessment["action"] == "hold"
    assert "keep_baseline_window_present" in assessment["blockers"]
    assert "no_window_supports_t1_edge" in assessment["blockers"]


def test_build_trend_continuation_rollout_assessment_holds_without_execution_eligible_evidence() -> None:
    assessment = build_trend_continuation_rollout_assessment(_build_analysis(execution_eligible_delta=0))

    assert assessment["action"] == "hold"
    assert assessment["execution_eligible_evidence"]["has_positive_execution_eligible_evidence"] is False
    assert "no_execution_eligible_activation_evidence" in assessment["blockers"]


def test_build_trend_continuation_rollout_assessment_flags_missing_runtime_activation_delta() -> None:
    assessment = build_trend_continuation_rollout_assessment(_build_analysis(execution_eligible_delta=0))

    assert assessment["action"] == "hold"
    assert "no_runtime_activation_delta" in assessment["blockers"]


def test_trend_continuation_rollout_assessment_main_writes_json_and_markdown(tmp_path: Path) -> None:
    input_json = tmp_path / "analysis.json"
    output_json = tmp_path / "assessment.json"
    output_md = tmp_path / "assessment.md"
    input_json.write_text(json.dumps(_build_analysis(), ensure_ascii=False), encoding="utf-8")

    result = trend_continuation_rollout_assessment.main(
        [
            "--input-json",
            str(input_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["action"] == "promote"
    markdown = output_md.read_text(encoding="utf-8")
    assert "Trend Continuation Rollout Assessment" in markdown
    assert "- action: promote" in markdown


def test_trend_continuation_rollout_assessment_script_runs_as_python_entrypoint(tmp_path: Path) -> None:
    input_json = tmp_path / "analysis.json"
    output_json = tmp_path / "assessment.json"
    output_md = tmp_path / "assessment.md"
    input_json.write_text(json.dumps(_build_analysis(keep_baseline_count=1, variant_supports_t1_count=0), ensure_ascii=False), encoding="utf-8")

    script_path = Path("scripts/btst_trend_continuation_rollout_assessment.py").resolve()
    python_executable = shutil.which("python")
    assert python_executable is not None

    result = subprocess.run(
        [
            python_executable,
            str(script_path),
            "--input-json",
            str(input_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["action"] == "hold"
    assert "keep_baseline_window_present" in payload["blockers"]
