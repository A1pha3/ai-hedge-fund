from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import scripts.btst_round89_rollout_assessment as round89_rollout_assessment
from scripts.btst_round89_rollout_helpers import (
    build_round89_rollout_assessment,
    summarize_round89_surface,
)


def test_summarize_round89_surface_averages_daily_metrics() -> None:
    summary = summarize_round89_surface(
        [
            {
                "date": "20260415",
                "win_rate": 0.60,
                "avg_ret": 1.20,
                "payoff_ratio": 2.10,
                "expectancy": 1.20,
                "downside_p10": -2.10,
                "tplus2_expectancy": 0.50,
                "tplus2_payoff_ratio": 1.50,
            },
            {
                "date": "20260416",
                "win_rate": 0.40,
                "avg_ret": -0.20,
                "payoff_ratio": 1.10,
                "expectancy": -0.20,
                "downside_p10": -3.10,
                "tplus2_expectancy": 0.10,
                "tplus2_payoff_ratio": 1.30,
            },
        ]
    )

    assert summary == {
        "n_days": 2,
        "win_rate": 0.5,
        "avg_ret": 0.5,
        "payoff_ratio": 1.6,
        "expectancy": 0.5,
        "downside_p10": -2.6,
        "tplus2_expectancy": 0.3,
        "tplus2_payoff_ratio": 1.4,
    }


def test_build_round89_rollout_assessment_holds_when_selected_surface_regresses() -> None:
    payload = {
        "trend_corrected_v1": {
            "selected": [
                {"date": "20260415", "win_rate": 0.49, "avg_ret": 0.43, "payoff_ratio": 1.56, "expectancy": 0.43, "downside_p10": -3.50},
                {"date": "20260416", "win_rate": 0.49, "avg_ret": 0.43, "payoff_ratio": 1.56, "expectancy": 0.43, "downside_p10": -3.50},
            ],
            "near_miss": [],
        },
        "ic_v5": {
            "selected": [
                {"date": "20260415", "win_rate": 0.48, "avg_ret": 0.34, "payoff_ratio": 1.51, "expectancy": 0.34, "downside_p10": -3.38},
            ],
            "near_miss": [],
        },
        "momentum_optimized": {
            "selected": [
                {"date": "20260415", "win_rate": 0.50, "avg_ret": 0.38, "payoff_ratio": 1.55, "expectancy": 0.38, "downside_p10": -3.10},
            ],
            "near_miss": [],
        },
    }

    assessment = build_round89_rollout_assessment(payload)

    assert assessment["action"] == "hold"
    assert "selected_win_rate_regressed_vs_momentum_optimized" in assessment["blockers"]
    assert "selected_downside_p10_regressed_vs_ic_v5" in assessment["blockers"]
    assert "selected_downside_p10_regressed_vs_momentum_optimized" in assessment["blockers"]


def test_build_round89_rollout_assessment_promotes_when_candidate_clears_guardrails() -> None:
    payload = {
        "trend_corrected_v1": {
            "selected": [
                {"date": "20260415", "win_rate": 0.55, "avg_ret": 0.50, "payoff_ratio": 1.70, "expectancy": 0.50, "downside_p10": -2.80},
                {"date": "20260416", "win_rate": 0.56, "avg_ret": 0.52, "payoff_ratio": 1.72, "expectancy": 0.52, "downside_p10": -2.75},
            ],
            "near_miss": [],
        },
        "ic_v5": {
            "selected": [
                {"date": "20260415", "win_rate": 0.48, "avg_ret": 0.34, "payoff_ratio": 1.51, "expectancy": 0.34, "downside_p10": -3.38},
            ],
            "near_miss": [],
        },
        "momentum_optimized": {
            "selected": [
                {"date": "20260415", "win_rate": 0.50, "avg_ret": 0.38, "payoff_ratio": 1.55, "expectancy": 0.38, "downside_p10": -3.10},
            ],
            "near_miss": [],
        },
    }

    assessment = build_round89_rollout_assessment(payload)

    assert assessment["action"] == "promote"
    assert assessment["blockers"] == []
    assert assessment["comparison_summary"]["momentum_optimized"]["selected_avg_ret_delta"] > 0
    assert assessment["comparison_summary"]["momentum_optimized"]["selected_downside_p10_delta"] > 0


def test_round89_rollout_assessment_main_writes_json_and_markdown(tmp_path: Path) -> None:
    input_path = tmp_path / "comparison.json"
    output_json = tmp_path / "assessment.json"
    output_md = tmp_path / "assessment.md"
    input_path.write_text(
        json.dumps(
            {
                "trend_corrected_v1": {
                    "selected": [
                        {"date": "20260415", "win_rate": 0.49, "avg_ret": 0.43, "payoff_ratio": 1.56, "expectancy": 0.43, "downside_p10": -3.50}
                    ],
                    "near_miss": [],
                },
                "ic_v5": {
                    "selected": [
                        {"date": "20260415", "win_rate": 0.48, "avg_ret": 0.34, "payoff_ratio": 1.51, "expectancy": 0.34, "downside_p10": -3.38}
                    ],
                    "near_miss": [],
                },
                "momentum_optimized": {
                    "selected": [
                        {"date": "20260415", "win_rate": 0.50, "avg_ret": 0.38, "payoff_ratio": 1.55, "expectancy": 0.38, "downside_p10": -3.10}
                    ],
                    "near_miss": [],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = round89_rollout_assessment.main(
        [
            "--input-json",
            str(input_path),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    assessment = json.loads(output_json.read_text(encoding="utf-8"))
    assert assessment["action"] == "hold"
    assert "selected_win_rate_regressed_vs_momentum_optimized" in assessment["blockers"]
    markdown = output_md.read_text(encoding="utf-8")
    assert "Round 89 Rollout Recommendation: **hold**" in markdown
    assert "selected_downside_p10_regressed_vs_momentum_optimized" in markdown


def test_round89_rollout_assessment_script_runs_as_python_entrypoint(tmp_path: Path) -> None:
    input_path = tmp_path / "comparison.json"
    output_json = tmp_path / "assessment.json"
    output_md = tmp_path / "assessment.md"
    input_path.write_text(
        json.dumps(
            {
                "trend_corrected_v1": {
                    "selected": [
                        {"date": "20260415", "win_rate": 0.55, "avg_ret": 0.50, "payoff_ratio": 1.70, "expectancy": 0.50, "downside_p10": -2.80}
                    ],
                    "near_miss": [],
                },
                "ic_v5": {
                    "selected": [
                        {"date": "20260415", "win_rate": 0.48, "avg_ret": 0.34, "payoff_ratio": 1.51, "expectancy": 0.34, "downside_p10": -3.38}
                    ],
                    "near_miss": [],
                },
                "momentum_optimized": {
                    "selected": [
                        {"date": "20260415", "win_rate": 0.50, "avg_ret": 0.38, "payoff_ratio": 1.55, "expectancy": 0.38, "downside_p10": -3.10}
                    ],
                    "near_miss": [],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    script_path = Path("scripts/btst_round89_rollout_assessment.py").resolve()
    python_executable = shutil.which("python")
    assert python_executable is not None

    result = subprocess.run(
        [
            python_executable,
            str(script_path),
            "--input-json",
            str(input_path),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
    )

    assert result.returncode == 0, result.stderr
    assert output_json.exists()
    assert output_md.exists()
