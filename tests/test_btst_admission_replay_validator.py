from __future__ import annotations

import json
from pathlib import Path

import scripts.analyze_btst_multi_window_profile_validation as multi_window_validation
import scripts.btst_admission_replay_validator as btst_admission_replay_validator
from scripts.btst_admission_replay_validator import build_admission_replay_summary


def test_build_admission_replay_summary_flags_identical_approximate_surfaces() -> None:
    summary = build_admission_replay_summary(
        baseline_payload={"selected": [{"ticker": "300724"}], "near_miss": [{"ticker": "688313"}]},
        candidate_payload={"selected": [{"ticker": "300724"}], "near_miss": [{"ticker": "688313"}]},
        regime_rows=[
            {"gate": "weak", "execution_eligible": False, "decision": "blocked"},
            {"gate": "normal_trade", "execution_eligible": True, "decision": "selected"},
        ],
        baseline_metrics={"selected_close_win_rate": 47.27, "selected_payoff_ratio": 1.282, "post_fee_expectation_low": -0.16},
        prior_audit={"downgrade_reasons": {"sample_small_n4_lt_5": 1}},
    )

    assert summary["approximate_surface_changed"] is False
    assert summary["requires_runtime_replay"] is True
    assert summary["runtime_recommendation"] == "runtime_replay_required_before_conclusion"
    assert summary["regime_counts"]["weak"]["execution_eligible_count"] == 0
    assert "identical_selected_and_near_miss_surfaces" in summary["blind_spot_reasons"]


def test_build_admission_replay_summary_reports_runtime_improvement_when_formal_surface_recovers() -> None:
    summary = build_admission_replay_summary(
        baseline_payload={"selected": [{"ticker": "A"}], "near_miss": [{"ticker": "B"}]},
        candidate_payload={"selected": [{"ticker": "A"}, {"ticker": "C"}], "near_miss": []},
        regime_rows=[
            {"gate": "normal_trade", "execution_eligible": True, "decision": "selected"},
            {"gate": "normal_trade", "execution_eligible": True, "decision": "selected"},
            {"gate": "weak", "execution_eligible": False, "decision": "blocked"},
        ],
        baseline_metrics={"selected_close_win_rate": 47.27, "selected_payoff_ratio": 1.282, "post_fee_expectation_low": -0.16},
        prior_audit={"downgrade_reasons": {"sample_small_n4_lt_5": 1}},
    )

    assert summary["approximate_surface_changed"] is True
    assert summary["requires_runtime_replay"] is False
    assert summary["runtime_recommendation"] == "candidate_ready_for_replay_window_validation"
    assert summary["regime_counts"]["normal_trade"]["execution_eligible_count"] == 2


def test_build_admission_replay_summary_uses_multi_window_replay_to_keep_baseline_default() -> None:
    summary = build_admission_replay_summary(
        baseline_payload={"selected": [{"ticker": "A"}], "near_miss": [{"ticker": "B"}]},
        candidate_payload={"selected": [{"ticker": "A"}], "near_miss": [{"ticker": "B"}]},
        regime_rows=[
            {"gate": "normal_trade", "execution_eligible": True, "decision": "selected"},
        ],
        baseline_metrics={"selected_close_win_rate": 47.27, "selected_payoff_ratio": 1.282, "post_fee_expectation_low": -0.16},
        prior_audit={"downgrade_reasons": {"sample_small_n4_lt_5": 1}},
        multi_window_validation={
            "report_dir_count": 17,
            "rows": [
                {
                    "report_label": "window-a",
                    "tradeable_surface_delta": {"next_close_positive_rate": 0.0, "next_close_return_p10": 0.0, "t_plus_2_close_return_median": 0.0},
                    "baseline_tradeable": {"total_count": 11},
                    "variant_tradeable": {"total_count": 11},
                },
                {
                    "report_label": "window-b",
                    "tradeable_surface_delta": {"next_close_positive_rate": 0.0, "next_close_return_p10": 0.0, "t_plus_2_close_return_median": 0.0},
                    "baseline_tradeable": {"total_count": 6},
                    "variant_tradeable": {"total_count": 6},
                },
            ],
        },
    )

    assert summary["requires_runtime_replay"] is False
    assert summary["runtime_recommendation"] == "keep_baseline_default_no_replay_delta"
    assert summary["multi_window_validation"]["changed_window_count"] == 0
    assert "multi_window_replay_showed_no_observable_delta" in summary["blind_spot_reasons"]


def test_build_admission_replay_summary_reports_structural_expansion_pressure() -> None:
    def _build_multi_window_row(
        *,
        report_label: str,
        window_recommendation: str,
        baseline_tradeable_total: int,
        variant_tradeable_total: int,
        baseline_selected_total: int,
        variant_selected_total: int,
        baseline_near_miss_total: int,
        variant_near_miss_total: int,
    ) -> dict[str, object]:
        if window_recommendation == "keep_baseline_default":
            tradeable_surface_delta = {
                "next_close_positive_rate": -0.01,
                "next_close_return_p10": -0.01,
            }
        elif window_recommendation == "variant_supports_t1_edge":
            tradeable_surface_delta = {
                "next_close_positive_rate": 0.01,
                "next_close_return_p10": 0.01,
            }
        else:
            tradeable_surface_delta = {}
        return multi_window_validation._summarize_row(
            report_dir=Path(report_label),
            baseline={
                "profile_name": "baseline",
                "trade_dates": ["2026-03-24"],
                "surface_summaries": {
                    "tradeable": {"total_count": baseline_tradeable_total},
                    "selected": {"total_count": baseline_selected_total},
                    "near_miss": {"total_count": baseline_near_miss_total},
                },
            },
            variant={
                "profile_name": "variant",
                "trade_dates": ["2026-03-24"],
                "surface_summaries": {
                    "tradeable": {"total_count": variant_tradeable_total},
                    "selected": {"total_count": variant_selected_total},
                    "near_miss": {"total_count": variant_near_miss_total},
                },
            },
            comparison={
                "tradeable_surface_delta": tradeable_surface_delta,
                "guardrail_status": "guardrail_pass",
            },
        )

    summary = build_admission_replay_summary(
        baseline_payload={"selected": [{"ticker": "A"}], "near_miss": [{"ticker": "B"}]},
        candidate_payload={"selected": [{"ticker": "A"}], "near_miss": [{"ticker": "B"}]},
        regime_rows=[
            {"gate": "normal_trade", "execution_eligible": True, "decision": "selected"},
        ],
        baseline_metrics={"selected_close_win_rate": 47.27, "selected_payoff_ratio": 1.282, "post_fee_expectation_low": -0.16},
        prior_audit={"downgrade_reasons": {"sample_small_n4_lt_5": 1}},
        multi_window_validation={
            "report_dir_count": 3,
            "rows": [
                _build_multi_window_row(
                    report_label="window-selected-expansion",
                    window_recommendation="keep_baseline_default",
                    baseline_tradeable_total=11,
                    variant_tradeable_total=11,
                    baseline_selected_total=10,
                    variant_selected_total=12,
                    baseline_near_miss_total=5,
                    variant_near_miss_total=5,
                ),
                _build_multi_window_row(
                    report_label="window-near-miss-expansion",
                    window_recommendation="mixed",
                    baseline_tradeable_total=18,
                    variant_tradeable_total=18,
                    baseline_selected_total=8,
                    variant_selected_total=8,
                    baseline_near_miss_total=10,
                    variant_near_miss_total=13,
                ),
                _build_multi_window_row(
                    report_label="window-ignore-supportive",
                    window_recommendation="variant_supports_t1_edge",
                    baseline_tradeable_total=20,
                    variant_tradeable_total=20,
                    baseline_selected_total=10,
                    variant_selected_total=20,
                    baseline_near_miss_total=10,
                    variant_near_miss_total=20,
                ),
            ],
        },
    )

    assert summary["structural_guardrail"]["selected_ratio_threshold"] == 0.15
    assert summary["structural_guardrail"]["near_miss_ratio_threshold"] == 0.20
    assert summary["structural_guardrail"]["excessive_window_count"] == 2
    assert summary["structural_guardrail"]["blocker_candidate"] is True
    assert summary["structural_guardrail"]["excessive_window_labels"] == [
        "window-selected-expansion",
        "window-near-miss-expansion",
    ]


def test_btst_admission_replay_validator_main_writes_blind_spot_report(tmp_path: Path) -> None:
    approximate_json = tmp_path / "approximate.json"
    baseline_json = tmp_path / "baseline.json"
    prior_audit_json = tmp_path / "prior.json"
    execution_contract_md = tmp_path / "execution.md"
    output_json = tmp_path / "validator.json"
    output_md = tmp_path / "validator.md"

    approximate_json.write_text(
        json.dumps(
            {
                "btst_precision_v2": {
                    "selected": [{"ticker": "300724"}],
                    "near_miss": [{"ticker": "688313"}],
                },
                "btst_admission_edge_recovery": {
                    "selected": [{"ticker": "300724"}],
                    "near_miss": [{"ticker": "688313"}],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    baseline_json.write_text(
        json.dumps(
            {
                "baseline_metrics": {
                    "selected_close_win_rate": 47.27,
                    "selected_payoff_ratio": 1.282,
                    "post_fee_expectation_low": -0.16,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    prior_audit_json.write_text(
        json.dumps({"downgrade_reasons": {"sample_small_n4_lt_5": 1}}, ensure_ascii=False),
        encoding="utf-8",
    )
    execution_contract_md.write_text(
        "\n".join(
            [
                "| ticker | bucket | decision | execution_eligible | downgrade_reasons | gate | prior |",
                "|---|---|---|---|---|---|---|",
                "| 688313 | near_miss | near_miss | False | historical_prior_not_execution_ready | normal_trade | watch_only |",
                "| 300724 | selected | selected | True | none | normal_trade | execution_ready |",
            ]
        ),
        encoding="utf-8",
    )

    result = btst_admission_replay_validator.main(
        [
            "--approximate-json",
            str(approximate_json),
            "--baseline-json",
            str(baseline_json),
            "--prior-audit-json",
            str(prior_audit_json),
            "--execution-contract-md",
            str(execution_contract_md),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    summary = json.loads(output_json.read_text(encoding="utf-8"))
    assert summary["requires_runtime_replay"] is True
    assert "identical_selected_and_near_miss_surfaces" in summary["blind_spot_reasons"]
    markdown = output_md.read_text(encoding="utf-8")
    assert "Admission Edge Replay Validation" in markdown
    assert "runtime_replay_required_before_conclusion" in markdown
