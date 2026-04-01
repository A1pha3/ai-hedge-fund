from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "data" / "reports"
PYTHON = sys.executable

DEFAULT_FROZEN_SOURCE = REPORTS_DIR / "paper_trading_window_20260202_20260313_w1_live_m2_7_20260319" / "daily_events.jsonl"
DEFAULT_DEV_REPLAY_DIR = REPORTS_DIR / "paper_trading_20260302_20260313_btst_research_replay"
DEFAULT_BASELINE_DIR = REPORTS_DIR / "paper_trading_window_20260323_20260326_btst_baseline_refresh"
DEFAULT_VARIANT_DIR = REPORTS_DIR / "paper_trading_window_20260323_20260326_btst_catalyst_floor_zero_refresh"
DEFAULT_FORWARD_DIR = REPORTS_DIR / "paper_trading_20260327_20260327_btst_forward_refresh"
DEFAULT_VARIANT_SUMMARY = REPORTS_DIR / "paper_trading_window_20260323_20260326_btst_catalyst_floor_zero_refresh_summary.json"
DEFAULT_MICRO_JSON = REPORTS_DIR / "btst_micro_window_regression_march_refresh.json"
DEFAULT_MICRO_MD = REPORTS_DIR / "btst_micro_window_regression_march_refresh.md"
DEFAULT_SUMMARY_JSON = REPORTS_DIR / "btst_march_backtest_refresh_summary.json"
DEFAULT_SUMMARY_MD = REPORTS_DIR / "btst_march_backtest_refresh_summary.md"


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _load_json(path)


def _validate_report_artifacts(report_dir: Path) -> dict[str, Any]:
    resolved_report_dir = report_dir.expanduser().resolve()
    session_summary_path = resolved_report_dir / "session_summary.json"
    daily_events_path = resolved_report_dir / "daily_events.jsonl"
    timing_log_path = resolved_report_dir / "pipeline_timings.jsonl"
    selection_root = resolved_report_dir / "selection_artifacts"
    snapshot_paths = sorted(selection_root.glob("*/selection_snapshot.json")) if selection_root.exists() else []
    missing_paths: list[str] = []
    for candidate in (session_summary_path, daily_events_path, timing_log_path):
        if not candidate.exists():
            missing_paths.append(str(candidate))
    if not selection_root.exists():
        missing_paths.append(str(selection_root))
    elif not snapshot_paths:
        missing_paths.append(str(selection_root / "*/selection_snapshot.json"))
    return {
        "report_dir": str(resolved_report_dir),
        "missing_paths": missing_paths,
        "selection_snapshot_count": len(snapshot_paths),
        "latest_selection_snapshot": str(snapshot_paths[-1]) if snapshot_paths else None,
        "is_complete": not missing_paths,
    }


def _extract_dev_replay_summary(session_summary: dict[str, Any]) -> dict[str, Any]:
    dual_target_summary = dict(session_summary.get("dual_target_summary") or {})
    return {
        "selection_target": (session_summary.get("plan_generation") or {}).get("selection_target"),
        "selection_target_count": dual_target_summary.get("selection_target_count"),
        "short_trade_target_count": dual_target_summary.get("short_trade_target_count"),
        "short_trade_selected_count": dual_target_summary.get("short_trade_selected_count"),
        "short_trade_near_miss_count": dual_target_summary.get("short_trade_near_miss_count"),
        "short_trade_blocked_count": dual_target_summary.get("short_trade_blocked_count"),
        "short_trade_rejected_count": dual_target_summary.get("short_trade_rejected_count"),
    }


def _build_summary_payload(
    *,
    dev_session_summary_path: Path,
    micro_window_json_path: Path,
    artifact_paths: dict[str, str],
) -> dict[str, Any]:
    dev_session_summary = _load_json(dev_session_summary_path)
    micro_window = _load_json(micro_window_json_path)

    baseline = dict(micro_window.get("baseline") or {})
    variants = list(micro_window.get("variants") or [])
    forward_reports = list(micro_window.get("forward_reports") or [])
    catalyst_variant = next((row for row in variants if str(row.get("label") or "") == "catalyst_floor_zero"), variants[0] if variants else {})
    forward_short_trade = next((row for row in forward_reports if str(row.get("label") or "") == "short_trade_only_20260327"), forward_reports[0] if forward_reports else {})

    baseline_tradeable = dict((baseline.get("surface_summaries") or {}).get("tradeable") or {})
    baseline_false_negative = dict((baseline.get("false_negative_proxy_summary") or {}).get("surface_metrics") or {})
    catalyst_tradeable = dict((catalyst_variant.get("surface_summaries") or {}).get("tradeable") or {})
    catalyst_false_negative = dict((catalyst_variant.get("false_negative_proxy_summary") or {}).get("surface_metrics") or {})
    catalyst_session_aggregate = dict(catalyst_variant.get("session_summary_aggregate") or {})

    conclusion = (
        "3 月验证继续支持当前研究主线：baseline 仍然主要表现为漏机会，而 catalyst floor zero 变体已经把 closed-cycle tradeable surface 从 0 推高到正值，下一步应优先围绕 short_trade_boundary score fail、candidate entry semantics 和局部结构治理推进。"
    )
    if catalyst_variant.get("artifact_status") == "missing_selection_artifacts" and not catalyst_tradeable.get("total_count"):
        conclusion = (
            "3 月 fresh baseline 与 fresh forward 已完成并可直接解读；fresh catalyst floor zero 运行本身完成，但报告目录缺少 selection_artifacts，导致 closed-cycle surface 无法自动重建。当前可确认的 only-safe 结论是：baseline 仍存在明显漏机会，forward 端仍有可交易 near-miss，而 catalyst fresh 版本在 session_summary 聚合口径下累计给出 1 个 selected、12 个 near_miss、10 个 blocked、56 个 rejected，下一步优先修复 variant 产物完整性后再做严格 surface 对比。"
        )

    return {
        "artifact_paths": artifact_paths,
        "dev_replay": {
            "session_summary_path": str(dev_session_summary_path),
            "summary": _extract_dev_replay_summary(dev_session_summary),
        },
        "micro_window": {
            "baseline_report_dir": baseline.get("report_dir"),
            "baseline_tradeable_surface": baseline_tradeable,
            "baseline_false_negative_surface": baseline_false_negative,
            "catalyst_floor_zero_report_dir": catalyst_variant.get("report_dir"),
            "catalyst_floor_zero_artifact_status": catalyst_variant.get("artifact_status"),
            "catalyst_floor_zero_session_aggregate": catalyst_session_aggregate,
            "catalyst_floor_zero_tradeable_surface": catalyst_tradeable,
            "catalyst_floor_zero_false_negative_surface": catalyst_false_negative,
            "forward_short_trade_report_dir": forward_short_trade.get("report_dir"),
            "forward_short_trade_tradeable_surface": dict((forward_short_trade.get("surface_summaries") or {}).get("tradeable") or {}),
            "comparisons": micro_window.get("comparisons") or [],
        },
        "conclusion": conclusion,
    }


def _render_summary_markdown(summary: dict[str, Any]) -> str:
    dev = dict(summary.get("dev_replay") or {})
    dev_stats = dict(dev.get("summary") or {})
    micro = dict(summary.get("micro_window") or {})
    baseline_tradeable = dict(micro.get("baseline_tradeable_surface") or {})
    catalyst_tradeable = dict(micro.get("catalyst_floor_zero_tradeable_surface") or {})
    catalyst_session_aggregate = dict(micro.get("catalyst_floor_zero_session_aggregate") or {})
    forward_tradeable = dict(micro.get("forward_short_trade_tradeable_surface") or {})

    lines: list[str] = []
    lines.append("# BTST March Backtest Refresh Summary")
    lines.append("")
    lines.append("## Development Replay")
    lines.append(f"- session_summary_path: {dev.get('session_summary_path')}")
    lines.append(f"- selection_target: {dev_stats.get('selection_target')}")
    lines.append(f"- selection_target_count: {dev_stats.get('selection_target_count')}")
    lines.append(f"- short_trade_target_count: {dev_stats.get('short_trade_target_count')}")
    lines.append(f"- short_trade_selected_count: {dev_stats.get('short_trade_selected_count')}")
    lines.append(f"- short_trade_near_miss_count: {dev_stats.get('short_trade_near_miss_count')}")
    lines.append(f"- short_trade_blocked_count: {dev_stats.get('short_trade_blocked_count')}")
    lines.append(f"- short_trade_rejected_count: {dev_stats.get('short_trade_rejected_count')}")
    lines.append("")
    lines.append("## Closed-Cycle Validation")
    lines.append(f"- baseline_report_dir: {micro.get('baseline_report_dir')}")
    lines.append(f"- baseline_tradeable_surface: {baseline_tradeable}")
    lines.append(f"- catalyst_floor_zero_report_dir: {micro.get('catalyst_floor_zero_report_dir')}")
    lines.append(f"- catalyst_floor_zero_artifact_status: {micro.get('catalyst_floor_zero_artifact_status')}")
    if catalyst_session_aggregate:
        lines.append(f"- catalyst_floor_zero_session_aggregate: {catalyst_session_aggregate}")
    lines.append(f"- catalyst_floor_zero_tradeable_surface: {catalyst_tradeable}")
    lines.append(f"- forward_short_trade_report_dir: {micro.get('forward_short_trade_report_dir')}")
    lines.append(f"- forward_short_trade_tradeable_surface: {forward_tradeable}")
    lines.append("")
    lines.append("## Conclusion")
    lines.append(f"- {summary.get('conclusion')}")
    lines.append("")
    lines.append("## Artifacts")
    for key, value in dict(summary.get("artifact_paths") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the BTST March minimal backtest refresh and produce a final summary bundle.")
    parser.add_argument("--model-provider", default="MiniMax")
    parser.add_argument("--model-name", default="MiniMax-M2.7")
    parser.add_argument("--frozen-plan-source", type=Path, default=DEFAULT_FROZEN_SOURCE)
    parser.add_argument("--dev-output-dir", type=Path, default=DEFAULT_DEV_REPLAY_DIR)
    parser.add_argument("--baseline-output-dir", type=Path, default=DEFAULT_BASELINE_DIR)
    parser.add_argument("--variant-output-dir", type=Path, default=DEFAULT_VARIANT_DIR)
    parser.add_argument("--forward-output-dir", type=Path, default=DEFAULT_FORWARD_DIR)
    parser.add_argument("--variant-summary-json", type=Path, default=DEFAULT_VARIANT_SUMMARY)
    parser.add_argument("--micro-output-json", type=Path, default=DEFAULT_MICRO_JSON)
    parser.add_argument("--micro-output-md", type=Path, default=DEFAULT_MICRO_MD)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    parser.add_argument("--summary-md", type=Path, default=DEFAULT_SUMMARY_MD)
    parser.add_argument("--skip-dev-replay", action="store_true")
    parser.add_argument("--skip-baseline", action="store_true")
    parser.add_argument("--skip-variant", action="store_true")
    parser.add_argument("--skip-forward", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    commands: list[tuple[str, list[str], bool]] = []

    if not args.skip_dev_replay:
        commands.append(
            (
                "dev_replay",
                [
                    PYTHON,
                    "scripts/run_paper_trading.py",
                    "--start-date",
                    "2026-03-02",
                    "--end-date",
                    "2026-03-13",
                    "--selection-target",
                    "dual_target",
                    "--frozen-plan-source",
                    str(args.frozen_plan_source),
                    "--model-provider",
                    args.model_provider,
                    "--model-name",
                    args.model_name,
                    "--output-dir",
                    str(args.dev_output_dir),
                ],
                True,
            )
        )

    if not args.skip_baseline:
        commands.append(
            (
                "baseline",
                [
                    PYTHON,
                    "scripts/run_paper_trading.py",
                    "--start-date",
                    "2026-03-23",
                    "--end-date",
                    "2026-03-26",
                    "--selection-target",
                    "dual_target",
                    "--model-provider",
                    args.model_provider,
                    "--model-name",
                    args.model_name,
                    "--output-dir",
                    str(args.baseline_output_dir),
                ],
                True,
            )
        )

    if not args.skip_variant:
        commands.append(
            (
                "variant",
                [
                    PYTHON,
                    "scripts/run_short_trade_boundary_variant_validation.py",
                    "--start-date",
                    "2026-03-23",
                    "--end-date",
                    "2026-03-26",
                    "--selection-target",
                    "dual_target",
                    "--model-provider",
                    args.model_provider,
                    "--model-name",
                    args.model_name,
                    "--variant-name",
                    "catalyst_floor_zero",
                    "--output-dir",
                    str(args.variant_output_dir),
                    "--summary-json",
                    str(args.variant_summary_json),
                ],
                True,
            )
        )

    if not args.skip_forward:
        commands.append(
            (
                "forward",
                [
                    PYTHON,
                    "scripts/run_paper_trading.py",
                    "--start-date",
                    "2026-03-27",
                    "--end-date",
                    "2026-03-27",
                    "--selection-target",
                    "short_trade_only",
                    "--model-provider",
                    args.model_provider,
                    "--model-name",
                    args.model_name,
                    "--output-dir",
                    str(args.forward_output_dir),
                ],
                True,
            )
        )

    execution_log: list[dict[str, Any]] = []
    for step_name, command, required in commands:
        result = _run(command, cwd=REPO_ROOT)
        execution_log.append(
            {
                "step": step_name,
                "command": command,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        if required and result.returncode != 0:
            print(json.dumps({"execution_log": execution_log}, ensure_ascii=False, indent=2))
            raise SystemExit(result.returncode)

    report_validations = {
        "dev_replay": _validate_report_artifacts(args.dev_output_dir),
        "baseline": _validate_report_artifacts(args.baseline_output_dir),
        "variant": _validate_report_artifacts(args.variant_output_dir),
        "forward": _validate_report_artifacts(args.forward_output_dir),
    }
    incomplete_reports = {label: payload for label, payload in report_validations.items() if not payload.get("is_complete")}
    execution_log.append({"step": "report_validation", "reports": report_validations})
    if incomplete_reports:
        print(json.dumps({"execution_log": execution_log, "incomplete_reports": incomplete_reports}, ensure_ascii=False, indent=2))
        raise SystemExit(2)

    micro_command = [
        PYTHON,
        "scripts/analyze_btst_micro_window_regression.py",
        "--baseline-report-dir",
        str(args.baseline_output_dir),
        "--variant-report",
        f"catalyst_floor_zero={args.variant_output_dir}",
        "--forward-report",
        f"short_trade_only_20260327={args.forward_output_dir}",
        "--output-json",
        str(args.micro_output_json),
        "--output-md",
        str(args.micro_output_md),
    ]
    micro_result = _run(micro_command, cwd=REPO_ROOT)
    execution_log.append(
        {
            "step": "micro_window_analysis",
            "command": micro_command,
            "exit_code": micro_result.returncode,
            "stdout": micro_result.stdout,
            "stderr": micro_result.stderr,
        }
    )
    if micro_result.returncode != 0:
        print(json.dumps({"execution_log": execution_log}, ensure_ascii=False, indent=2))
        raise SystemExit(micro_result.returncode)

    dev_session_summary_path = args.dev_output_dir / "session_summary.json"
    summary_payload = _build_summary_payload(
        dev_session_summary_path=dev_session_summary_path,
        micro_window_json_path=args.micro_output_json,
        artifact_paths={
            "dev_output_dir": str(args.dev_output_dir),
            "baseline_output_dir": str(args.baseline_output_dir),
            "variant_output_dir": str(args.variant_output_dir),
            "forward_output_dir": str(args.forward_output_dir),
            "variant_summary_json": str(args.variant_summary_json),
            "micro_output_json": str(args.micro_output_json),
            "micro_output_md": str(args.micro_output_md),
        },
    )
    summary_payload["execution_log"] = execution_log
    summary_payload["report_validations"] = report_validations

    args.summary_json.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.summary_md.write_text(_render_summary_markdown(summary_payload) + "\n", encoding="utf-8")
    print(json.dumps(summary_payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()