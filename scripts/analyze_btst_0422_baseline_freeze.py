from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from src.paper_trading.runtime_session_helpers import build_session_summary
from src.research.models import SelectionSnapshot, SelectionTargetReplayInput


def _extract_float(text: str) -> float | None:
    match = re.search(r"([+-]?\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else None


def _extract_percent(text: str) -> float | None:
    match = re.search(r"([+-]?\d+(?:\.\d+)?)%", text)
    return float(match.group(1)) if match else None


def _extract_fee_expectation_range(text: str) -> tuple[float | None, float | None]:
    match = re.search(r"(-?\d+(?:\.\d+)?)%\s*~\s*(-?\d+(?:\.\d+)?)%", text)
    if match is None:
        return None, None
    values = sorted((float(match.group(1)), float(match.group(2))))
    return values[0], values[1]


def _build_session_summary_field_inventory() -> list[str]:
    summary = build_session_summary(
        start_date="2026-04-01",
        end_date="2026-04-02",
        tickers=["000001"],
        initial_capital=100000.0,
        resolved_model_name="test-model",
        resolved_model_provider="test-provider",
        selected_analysts=[],
        fast_selected_analysts=[],
        short_trade_target_profile_name="default",
        short_trade_target_profile_overrides={},
        frozen_plan_source_path=None,
        selection_target="short_trade_only",
        metrics={},
        portfolio_values=[],
        final_portfolio_snapshot={},
        llm_route_provenance={},
        execution_plan_provenance={},
        dual_target_summary={},
        llm_observability_summary={},
        llm_error_digest={},
        data_cache_summary={},
        cache_benchmark_summary=None,
        cache_benchmark_status={},
        research_feedback_summary={},
        recorder_day_count=0,
        recorder_executed_trade_days=0,
        recorder_total_executed_orders=0,
        daily_events_path=Path("daily_events.jsonl"),
        timing_log_path=Path("pipeline_timings.jsonl"),
        summary_path=Path("session_summary.json"),
        selection_artifact_root=Path("selection_artifacts"),
        feedback_summary_path=Path("research_feedback_summary.json"),
        cache_benchmark_artifacts={},
        llm_metrics_artifacts={},
    )
    return sorted(summary.keys())


def _parse_regime_row(text: str, label: str) -> dict[str, Any]:
    pattern = rf"\|\s*(?:\*\*)?{label}(?:（?.*?\)?)?(?:\*\*)?\s*\|[^|]*?(\d+)\s*\|\s*(?:\*\*)?([0-9.]+)%\s*(?:\*\*)?\s*\|\s*(?:\*\*)?([0-9.]+)\s*(?:\*\*)?\s*\|\s*(?:\*\*)?([+-]?[0-9,≈]+)\s*(?:\*\*)?\s*\|"
    match = re.search(pattern, text)
    if match is None:
        return {}
    profit_text = match.group(4).replace(",", "").replace("≈", "")
    return {
        "day_count": int(match.group(1)),
        "close_win_rate": float(match.group(2)),
        "payoff_ratio": float(match.group(3)),
        "relative_profit_contribution": float(profit_text),
    }


def _extract_table_float(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text)
    return float(match.group(1)) if match else None


def build_btst_0422_baseline_freeze(
    *,
    evidence_doc_path: str | Path,
    output_json_path: str | Path | None = None,
    output_markdown_path: str | Path | None = None,
) -> dict[str, Any]:
    evidence_text = Path(evidence_doc_path).read_text(encoding="utf-8")
    selected_expectation = _extract_percent(re.search(r"期望收益[^\n]*", evidence_text).group(0)) if re.search(r"期望收益[^\n]*", evidence_text) else None
    post_fee_low, post_fee_high = _extract_fee_expectation_range(evidence_text)
    if post_fee_low is None and selected_expectation is not None:
        post_fee_low = round(selected_expectation - 0.12, 2)
        post_fee_high = round(selected_expectation - 0.07, 2)

    report = {
        "generated_on": str(date.today()),
        "inputs": {
            "evidence_doc": str(Path(evidence_doc_path)),
        },
        "report_names": {
            "baseline_json": "p0_btst_0422_baseline_freeze.json",
            "baseline_markdown": "p0_btst_0422_baseline_freeze.md",
            "p1_shadow_eval_json": "p1_btst_regime_gate_shadow_eval.json",
            "p1_shadow_eval_markdown": "p1_btst_regime_gate_shadow_eval.md",
        },
        "baseline_metrics": {
            "selected_close_win_rate": _extract_table_float(evidence_text, r"\|\s*T\+1 收盘胜率\s*\|\s*\*\*?([0-9.]+)%"),
            "selected_payoff_ratio": _extract_table_float(evidence_text, r"\|\s*盈亏比\s*\|\s*\*\*?([0-9.]+):1"),
            "selected_expectation": selected_expectation,
            "post_fee_expectation_low": post_fee_low,
            "post_fee_expectation_high": post_fee_high,
            "regime_breakdown": {
                "strong": _parse_regime_row(evidence_text, "强势日"),
                "weak": _parse_regime_row(evidence_text, "弱势日"),
                "neutral": _parse_regime_row(evidence_text, "中性日"),
            },
            "near_miss_comparison": {
                "selected_win_rate": _extract_table_float(evidence_text, r"\|\s*selected（精选）\s*\|\s*([0-9.]+)%\s*\|"),
                "near_miss_win_rate": _extract_table_float(evidence_text, r"\|\s*near_miss（候补）\s*\|\s*([0-9.]+)%\s*\|"),
                "selected_payoff_ratio": _extract_table_float(evidence_text, r"\|\s*selected（精选）\s*\|\s*[0-9.]+%\s*\|\s*([0-9.]+)\s*\|"),
                "near_miss_payoff_ratio": _extract_table_float(evidence_text, r"\|\s*near_miss（候补）\s*\|\s*[0-9.]+%\s*\|\s*([0-9.]+)\s*\|"),
            },
        },
        "field_inventory": {
            "selection_snapshot": {
                "fields": sorted(SelectionSnapshot.model_fields.keys()),
                "planned_extensions": ["btst_regime_gate", "pipeline_config_snapshot.btst_0422_flags"],
            },
            "selection_target_replay_input": {
                "fields": sorted(SelectionTargetReplayInput.model_fields.keys()),
                "planned_extensions": ["btst_regime_gate"],
            },
            "session_summary": {
                "fields": _build_session_summary_field_inventory(),
                "planned_extensions": ["btst_regime_gate_summary"],
            },
            "selection_review": {
                "sections": [
                    "运行概览",
                    "双目标空壳状态",
                    "Research Target Summary",
                    "Short Trade Target Summary",
                    "Target Delta Highlights",
                    "题材催化研究池",
                    "今日入选股票",
                    "接近入选但落选",
                    "当日漏斗观察",
                ],
                "planned_extensions": ["BTST 择日门控"],
            },
        },
        "feature_flag_injection_points": {
            "p1_regime_gate_shadow": {
                "default_mode": "off",
                "planned_flag": "BTST_0422_P1_REGIME_GATE_MODE",
                "injection_point": "src/execution/daily_pipeline.py::run_post_market",
            },
            "p2_regime_gate_enforce": {
                "default_mode": "off",
                "planned_flag": "BTST_0422_P2_REGIME_GATE_MODE",
                "injection_point": "src/execution/daily_pipeline.py::run_post_market",
            },
            "p3_prior_quality_hard_gate": {
                "default_mode": "off",
                "planned_flag": "BTST_0422_P3_PRIOR_QUALITY_MODE",
                "injection_point": "src/targets/router.py::build_selection_targets",
            },
            "p4_prior_shrinkage": {
                "default_mode": "off",
                "planned_flag": "BTST_0422_P4_PRIOR_SHRINKAGE_MODE",
                "injection_point": "src/targets/profiles.py::ShortTradeTargetProfile",
            },
            "p5_execution_contract": {
                "default_mode": "off",
                "planned_flag": "BTST_0422_P5_EXECUTION_CONTRACT_MODE",
                "injection_point": "src/targets/router.py::build_selection_targets",
            },
            "p6_risk_budget_overlay": {
                "default_mode": "off",
                "planned_flag": "BTST_0422_P6_RISK_BUDGET_MODE",
                "injection_point": "src/execution/daily_pipeline.py::build_buy_orders_with_diagnostics",
            },
        },
    }

    markdown = "\n".join(
        [
            "# P0 BTST 0422 Baseline Freeze",
            "",
            f"- evidence_doc: {report['inputs']['evidence_doc']}",
            f"- selected_close_win_rate: {report['baseline_metrics']['selected_close_win_rate']}",
            f"- selected_expectation: {report['baseline_metrics']['selected_expectation']}",
            f"- post_fee_expectation_range: {report['baseline_metrics']['post_fee_expectation_low']} ~ {report['baseline_metrics']['post_fee_expectation_high']}",
            "",
            "## Field Inventory",
            "",
            f"- selection_snapshot_fields: {', '.join(report['field_inventory']['selection_snapshot']['fields'])}",
            f"- session_summary_fields: {', '.join(report['field_inventory']['session_summary']['fields'])}",
            "",
            "## Feature Flags",
            "",
            *[
                f"- {flag_name}: {payload['planned_flag']} @ {payload['injection_point']} (default={payload['default_mode']})"
                for flag_name, payload in report["feature_flag_injection_points"].items()
            ],
            "",
        ]
    )

    if output_json_path is not None:
        output_json = Path(output_json_path)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if output_markdown_path is not None:
        output_markdown = Path(output_markdown_path)
        output_markdown.parent.mkdir(parents=True, exist_ok=True)
        output_markdown.write_text(markdown, encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the BTST 0422 P0 baseline freeze artifact.")
    parser.add_argument(
        "--evidence-doc",
        default="docs/zh-cn/factors/BTST/optimize0422/01-0422-实盘复盘与数据证据.md",
    )
    parser.add_argument("--output-json", default="data/reports/p0_btst_0422_baseline_freeze.json")
    parser.add_argument("--output-markdown", default="data/reports/p0_btst_0422_baseline_freeze.md")
    args = parser.parse_args()

    build_btst_0422_baseline_freeze(
        evidence_doc_path=args.evidence_doc,
        output_json_path=args.output_json,
        output_markdown_path=args.output_markdown,
    )


if __name__ == "__main__":
    main()
