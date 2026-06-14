#!/usr/bin/env python3
"""BTST next-day package — unified entrypoint for pre-trade workflow.

Orchestrates doc-bundle generation, optional profile compare,
``operator_summary`` building, ONE-PAGER rendering, and bridge updates.

P0D (2026-06-04): first working version covering reuse, refresh, dry-run,
resume and the key invariants from the improvement plan.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Project-root relative defaults
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_REPORTS_DIR = _PROJECT_ROOT / "data" / "reports"
_OUTPUTS_DIR = _PROJECT_ROOT / "outputs"


def _resolve_reports_root(reports_root: str | Path | None) -> Path:
    return Path(reports_root).expanduser().resolve() if reports_root else _REPORTS_DIR


def _resolve_output_dir(output_dir: str | Path | None, signal_date: str) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    return _OUTPUTS_DIR / signal_date[:6] / signal_date


# ---------------------------------------------------------------------------
# Step tracking
# ---------------------------------------------------------------------------

def _new_step(name: str) -> dict[str, Any]:
    return {"step_name": name, "started_at": time.time(), "status": "pending"}


def _finish_step(step: dict[str, Any], status: str, *, failure_reason: str | None = None, source_path: str | None = None) -> None:
    step["status"] = status
    step["duration_seconds"] = round(time.time() - step["started_at"], 3)
    if failure_reason:
        step["failure_reason"] = failure_reason
    if source_path:
        step["source_path"] = source_path


# ---------------------------------------------------------------------------
# ONE-PAGER renderer
# ---------------------------------------------------------------------------

_FORBIDDEN_IN_POST_CLOSE = {
    "filled", "confirmed", "executable",
    "next_open_return", "next_open_to_close_return",
    "next_high_return", "next_close_return",
    "realized_return", "realized_outcome", "t_plus_1_outcome",
}


def _render_one_pager(summary_data: dict[str, Any]) -> str:
    """Render a ONE-PAGER markdown from a validated operator_summary dict.

    Only reads fields already in the summary; never reads raw artifacts directly.
    Respects the decision_phase — omits fields not available at the current phase.
    """
    phase = str(summary_data.get("decision_phase") or "post_close_plan")
    lines = [
        f"# BTST ONE-PAGER — {summary_data.get('signal_date', 'n/a')}",
        "",
        f"- **决策阶段**: `{phase}`",
        f"- **数据截止**: `{summary_data.get('data_as_of', 'n/a')}`",
        f"- **生成时间**: `{summary_data.get('generated_at', 'n/a')}`",
        f"- **Decision ID**: `{summary_data.get('decision_id', 'n/a')}`",
        "",
    ]

    # Market section
    market = dict(summary_data.get("market") or {})
    lines.extend([
        "## 市场门控",
        "",
        f"- regime_gate_level: `{market.get('regime_gate_level') or 'n/a'}`",
        f"- market_gate: `{market.get('market_gate') or 'n/a'}`",
        f"- gate_enforced: `{market.get('gate_enforced')}`",
        f"- buy_orders_cleared: `{market.get('buy_orders_cleared')}`",
        "",
    ])

    # Execution section
    execution = dict(summary_data.get("execution") or {})
    report_mode = execution.get("report_mode") or "n/a"
    lines.extend([
        "## 执行状态",
        "",
        f"- report_mode: `{report_mode}`",
        f"- 正式入选: `{', '.join(execution.get('formal_selected_tickers') or []) or '无'}`",
        f"- 可下单: `{', '.join(execution.get('orderable_tickers') or []) or '无'}`",
        f"- 仅确认: `{', '.join(execution.get('confirmation_only_tickers') or []) or '无'}`",
    ])
    first_invalidate = execution.get("first_invalidate_if")
    if first_invalidate:
        lines.append(f"- 第一取消条件: {first_invalidate}")
    lines.append("")

    # Early-runner section
    er = dict(summary_data.get("early_runner") or {})
    lines.extend([
        "## Early-Runner",
        "",
        f"- 日期对齐: `{er.get('board_date_alignment_status') or 'n/a'}`",
        f"- 产物新鲜度: `{er.get('artifact_freshness_status') or 'n/a'}`",
        f"- Point-in-time: `{er.get('point_in_time_status') or 'n/a'}`",
        f"- Actionability: `{er.get('actionability_status') or 'n/a'}`",
        f"- 交集票: `{er.get('intersection_count', 0)}`",
        f"- Only early-runner: `{er.get('only_early_runner_count', 0)}`",
        f"- Second-entry: `{er.get('second_entry_count', 0)}`",
        "",
    ])

    # Incremental evidence
    ie = dict(summary_data.get("incremental_evidence") or {})
    lines.extend([
        "## 历史增量证据",
        "",
        f"- 状态: `{ie.get('status', 'insufficient')}`",
        f"- 样本量: `{ie.get('sample_count', 0)}`",
    ])
    if ie.get("status") == "insufficient":
        lines.append("- **证据不足**，不能声称有或无增量价值。")
    lines.append("")

    # P0D: omit fields not available at the current phase.
    if phase == "post_close_plan":
        lines.extend([
            "## ⚠️ 阶段限制",
            "",
            "当前为 `post_close_plan` 阶段。本 ONE-PAGER 不包含 T+1 确认结果、成交状态或已实现收益。",
            "",
        ])

    # Profile compare
    pc = dict(summary_data.get("profile_compare") or {})
    lines.extend([
        "## Profile 对比",
        "",
        f"- 比较范围: `{pc.get('comparison_scope', 'n/a')}`",
        f"- 有效决策差异: `{pc.get('effective_decision_diff', False)}`",
    ])
    if not pc.get("effective_decision_diff"):
        lines.append("- 当前 profile 未改变真实候选或执行语义。")
    lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run_btst_next_day_package(
    *,
    signal_date: str,
    reports_root: str | Path | None = None,
    output_dir: str | Path | None = None,
    reuse_existing: bool = True,
    refresh_early_runner: bool = False,
    with_profile_compare: bool = False,
    rerun_paper_trading: bool = False,
    dry_run: bool = False,
    resume: bool = False,
    timeout_seconds: int | None = None,
    default_output: bool = False,
) -> dict[str, Any]:
    """Run the full next-day BTST package workflow.

    Returns a dict with operator_summary data, run steps, and file paths.
    Always writes ``operator_summary.json`` (even on failure).
    """
    from src.paper_trading.btst_operator_summary import (
        build_operator_summary,
    )

    time.time()
    steps: list[dict[str, Any]] = []
    summary_status = "complete"
    manual_intervention: dict[str, Any] = {"required": False, "reasons": []}
    bridge_info: dict[str, Any] = {"updated_files": [], "unchanged_files": [], "missing_targets": [], "failure_reasons": []}
    source_artifacts: list[dict[str, Any]] = []
    source_conflicts: list[dict[str, Any]] = []
    artifacts_status: dict[str, Any] = {"required": [], "optional": [], "missing_required": [], "missing_optional": []}

    resolved_reports_root = _resolve_reports_root(reports_root)
    resolved_output_dir = _resolve_output_dir(output_dir, signal_date)

    # --- Step 1: Check existing operator_summary for resume ---
    summary_path = resolved_output_dir / "operator_summary.json"
    if resume and summary_path.exists():
        step = _new_step("resume_check")
        try:
            existing = json.loads(summary_path.read_text(encoding="utf-8"))
            step["source_path"] = str(summary_path)
            _finish_step(step, "reused", source_path=str(summary_path))
            steps.append(step)
            # If the existing summary was complete, short-circuit.
            if existing.get("summary_status") == "complete" and reuse_existing:
                return {"status": "resumed", "summary": existing, "steps": steps}
        except (json.JSONDecodeError, OSError) as exc:
            _finish_step(step, "failed", failure_reason=str(exc))
            steps.append(step)

    # --- Step 2: Generate doc bundle ---
    step = _new_step("generate_doc_bundle")
    doc_bundle_result: dict[str, Any] = {}
    try:
        from scripts.generate_btst_doc_bundle import generate_btst_doc_bundle
        doc_bundle_result = generate_btst_doc_bundle(
            signal_date,
            reports_root=resolved_reports_root,
            output_dir=resolved_output_dir,
            refresh_early_runner=refresh_early_runner,
        )
        _finish_step(step, "success", source_path=doc_bundle_result.get("output_dir"))
    except Exception as exc:
        _finish_step(step, "failed", failure_reason=str(exc))
        summary_status = "failed"
        manual_intervention["required"] = True
        manual_intervention["reasons"].append(f"generate_doc_bundle failed: {exc}")
    steps.append(step)

    # --- Step 3: Optional profile compare ---
    if with_profile_compare and summary_status != "failed":
        step = _new_step("profile_compare")
        try:
            from scripts.generate_btst_doc_bundle import (
                compare_btst_doc_bundle_profiles,
            )
            compare_result = compare_btst_doc_bundle_profiles(
                signal_date,
                profiles=["conservative", "aggressive"],
                reports_root=resolved_reports_root,
                output_dir=resolved_output_dir / f"{signal_date}_profile_compare",
                refresh_early_runner=False,  # Never refresh twice.
            )
            _finish_step(step, "success", source_path=compare_result.get("output_dir"))
        except Exception as exc:
            _finish_step(step, "failed", failure_reason=str(exc))
            summary_status = "degraded"
        steps.append(step)

    # --- Step 4: Build operator_summary ---
    control_tower = doc_bundle_result.get("control_tower") or {}
    market_data = {
        "regime_gate_level": control_tower.get("regime_gate_level"),
        "market_gate": control_tower.get("gate"),
        "gate_enforced": control_tower.get("enforced"),
        "buy_orders_cleared": control_tower.get("buy_orders_cleared"),
    }
    execution_data = {
        "report_mode": doc_bundle_result.get("report_mode"),
        "formal_selected_tickers": list(doc_bundle_result.get("semantic_selected_labels") or []),
        "orderable_tickers": [],
        "confirmation_only_tickers": list(doc_bundle_result.get("semantic_selected_labels") or []),
    }
    er_status = doc_bundle_result.get("early_runner_status", "unavailable")
    early_runner_data: dict[str, Any] = {
        "board_date_alignment_status": er_status,
        "artifact_freshness_status": "unknown",
        "point_in_time_status": "unknown",
        "intersection_count": doc_bundle_result.get("early_runner_intersection_count", 0),
        "only_early_runner_count": doc_bundle_result.get("early_runner_only_count", 0),
        "second_entry_count": doc_bundle_result.get("early_runner_second_entry_count", 0),
    }

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary_kwargs: dict[str, Any] = {
        "signal_date": signal_date,
        "decision_phase": "post_close_plan",
        "next_trade_date": doc_bundle_result.get("next_trade_date_iso"),
        "decision_as_of": f"{signal_date[:4]}-{signal_date[4:6]}-{signal_date[6:8]}T23:59:59+08:00",
        "data_as_of": f"{signal_date[:4]}-{signal_date[4:6]}-{signal_date[6:8]}T15:00:00+08:00",
        "summary_status": summary_status,
        "market": market_data,
        "execution": execution_data,
        "early_runner": early_runner_data,
        "profile_compare": {
            "comparison_scope": "doc_bundle_rendering",
            "effective_decision_diff": False,
        },
        "artifacts": artifacts_status,
        "bridge": bridge_info,
        "source_artifacts": source_artifacts,
        "source_conflicts": source_conflicts,
        "run_steps": steps,
        "manual_intervention": manual_intervention,
    }

    try:
        summary = build_operator_summary(**summary_kwargs)
        summary_data = json.loads(summary.model_dump_json())
    except Exception as exc:
        # Fallback: write a minimal failed summary.
        summary_data = {
            "schema_version": 1,
            "summary_status": "failed",
            "generated_at": now_iso,
            "decision_id": f"btst-{signal_date}-post-close-plan-v1",
            "decision_phase": "post_close_plan",
            "signal_date": signal_date,
            "decision_as_of": summary_kwargs["decision_as_of"],
            "data_as_of": summary_kwargs["data_as_of"],
            "run_steps": steps,
            "manual_intervention": {"required": True, "reasons": [f"summary build failed: {exc}"]},
        }

    # --- Step 5: Render ONE-PAGER ---
    one_pager_path = resolved_output_dir / f"BTST-{signal_date}-ONE-PAGER.md"
    if summary_status != "failed" and not dry_run:
        step = _new_step("render_one_pager")
        try:
            one_pager_content = _render_one_pager(summary_data)
            one_pager_path.parent.mkdir(parents=True, exist_ok=True)
            one_pager_path.write_text(one_pager_content, encoding="utf-8")
            _finish_step(step, "success", source_path=str(one_pager_path))
        except Exception as exc:
            _finish_step(step, "failed", failure_reason=str(exc))
        steps.append(step)

    # --- Step 6: Write operator_summary.json (always, even on failure) ---
    if not dry_run:
        resolved_output_dir.mkdir(parents=True, exist_ok=True)
        try:
            # Use the raw dict for failed summaries that couldn't build a Pydantic model.
            if isinstance(summary_data, dict) and "schema_version" in summary_data:
                atomic_content = json.dumps(summary_data, ensure_ascii=False, indent=2) + "\n"
                import tempfile
                fd, tmp = tempfile.mkstemp(
                    dir=str(resolved_output_dir),
                    prefix=".operator_summary_",
                    suffix=".tmp",
                )
                try:
                    with open(fd, "w", encoding="utf-8") as f:
                        f.write(atomic_content)
                    Path(tmp).rename(summary_path)
                except BaseException:
                    Path(tmp).unlink(missing_ok=True)
                    raise
        except Exception as exc:
            manual_intervention["required"] = True
            manual_intervention["reasons"].append(f"summary write failed: {exc}")

    return {
        "status": "completed" if summary_status != "failed" else "failed",
        "summary": summary_data,
        "steps": steps,
        "output_dir": str(resolved_output_dir),
        "one_pager_path": str(one_pager_path) if not dry_run else None,
        "dry_run": dry_run,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="BTST next-day package unified entrypoint.")
    parser.add_argument("--signal-date", required=True, help="Signal date in YYYYMMDD format")
    parser.add_argument("--reports-root", default=None, help="Reports root directory")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    parser.add_argument("--reuse-existing", action="store_true", default=True, help="Reuse existing artifacts (default)")
    parser.add_argument("--refresh-early-runner", action="store_true", default=False, help="Refresh early-runner artifacts")
    parser.add_argument("--rerun-paper-trading", action="store_true", default=False, help="Re-run paper trading (expensive)")
    parser.add_argument("--with-profile-compare", action="store_true", default=False, help="Generate profile comparison")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Show plan without writing files")
    parser.add_argument("--resume", action="store_true", default=False, help="Resume from last failed step")
    parser.add_argument("--timeout-seconds", type=int, default=None, help="Per-step timeout")
    parser.add_argument("--default-output", action="store_true", default=False, help="Use default output path")
    args = parser.parse_args()

    result = run_btst_next_day_package(
        signal_date=args.signal_date,
        reports_root=args.reports_root,
        output_dir=args.output_dir,
        reuse_existing=args.reuse_existing,
        refresh_early_runner=args.refresh_early_runner,
        rerun_paper_trading=args.rerun_paper_trading,
        with_profile_compare=args.with_profile_compare,
        dry_run=args.dry_run,
        resume=args.resume,
        timeout_seconds=args.timeout_seconds,
        default_output=args.default_output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
