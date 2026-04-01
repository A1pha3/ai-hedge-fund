from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.btst_report_utils import safe_load_json as _safe_load_json


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_latest_close_validation_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_latest_close_validation_latest.md"


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _relative_link(target: str | Path | None, output_path: Path) -> str | None:
    if not target:
        return None
    resolved = Path(target).expanduser().resolve()
    if not resolved.exists():
        return None
    try:
        repo_root = output_path.parent.parent.parent.resolve()
        return resolved.relative_to(repo_root).as_posix()
    except ValueError:
        return resolved.as_posix()


def _current_watch_summary(nightly_payload: dict[str, Any]) -> dict[str, Any]:
    latest_followup = dict(dict(nightly_payload.get("control_tower_snapshot") or {}).get("synthesis") or {}).get("latest_btst_followup") or {}
    priority_board = dict(nightly_payload.get("latest_priority_board_snapshot") or {})
    priority_rows = list(priority_board.get("priority_rows") or [])
    return {
        "headline": latest_followup.get("priority_board_headline") or priority_board.get("headline"),
        "selected_count": _as_int(latest_followup.get("selected_count")),
        "near_miss_count": _as_int(latest_followup.get("near_miss_count")),
        "blocked_count": _as_int(latest_followup.get("blocked_count")),
        "rejected_count": _as_int(latest_followup.get("rejected_count")),
        "opportunity_pool_count": _as_int(latest_followup.get("opportunity_pool_count")),
        "priority_rows": priority_rows,
        "brief_recommendation": latest_followup.get("brief_recommendation") or priority_board.get("brief_recommendation"),
    }


def _extract_lane_focus(nightly_payload: dict[str, Any]) -> list[dict[str, Any]]:
    lane_matrix = list(dict(dict(nightly_payload.get("control_tower_snapshot") or {}).get("synthesis") or {}).get("lane_matrix") or [])
    focus_lane_ids = {
        "primary_roll_forward",
        "recurring_shadow_close_candidate",
        "recurring_intraday_control",
        "structural_shadow_hold",
    }
    focus_rows = []
    for row in lane_matrix:
        lane_id = str(row.get("lane_id") or "")
        if lane_id not in focus_lane_ids:
            continue
        focus_rows.append(
            {
                "lane_id": lane_id,
                "ticker": row.get("ticker"),
                "lane_status": row.get("lane_status"),
                "validation_verdict": row.get("validation_verdict"),
                "missing_window_count": row.get("missing_window_count"),
                "next_step": row.get("next_step"),
            }
        )
    return focus_rows


def _build_key_conclusions(nightly_payload: dict[str, Any], delta_payload: dict[str, Any]) -> list[str]:
    watch_summary = _current_watch_summary(nightly_payload)
    governance = dict(dict(nightly_payload.get("control_tower_snapshot") or {}).get("validation") or {})
    material_anchor = dict(delta_payload.get("material_change_anchor") or {})
    priority_delta = dict(material_anchor.get("priority_delta") or delta_payload.get("priority_delta") or {})
    material_operator_focus = [str(item).strip() for item in list(material_anchor.get("operator_focus") or []) if str(item).strip()]
    conclusions: list[str] = []

    if watch_summary.get("selected_count", 0) == 0:
        conclusions.append("本次收盘验证后，下一交易日仍无正式主票，当前结论继续停留在观察层而非执行层。")
    else:
        conclusions.append("本次收盘验证后，系统已经给出正式主票，应优先按主票而不是 near-miss 观察层组织明日动作。")

    conclusions.append(
        f"当前观察层结构为 near_miss={watch_summary.get('near_miss_count', 0)}、opportunity_pool={watch_summary.get('opportunity_pool_count', 0)}、blocked={watch_summary.get('blocked_count', 0)}、rejected={watch_summary.get('rejected_count', 0)}。"
    )

    if governance.get("overall_verdict") == "pass":
        conclusions.append("治理链当前保持 pass，说明 lane 分工和治理证据在本轮收盘后没有出现新的内部冲突。")
    else:
        conclusions.append(f"治理链当前 verdict={governance.get('overall_verdict') or 'unknown'}，需要先处理治理一致性再谈默认升级。")

    added_tickers = [str(item.get("ticker") or "") for item in list(priority_delta.get("added_tickers") or []) if item.get("ticker")]
    removed_tickers = [str(item.get("ticker") or "") for item in list(priority_delta.get("removed_tickers") or []) if item.get("ticker")]
    if added_tickers or removed_tickers:
        added_label = ", ".join(added_tickers) if added_tickers else "none"
        removed_label = ", ".join(removed_tickers) if removed_tickers else "none"
        conclusions.append(f"相对上一份发生实质变化的 BTST 报告，本轮观察对象已切换，新增={added_label}，移出={removed_label}。")
    elif material_operator_focus:
        conclusions.append(f"上一份实质变化锚点显示，本轮 rollforward 的重点变化为：{material_operator_focus[0]}")
    else:
        conclusions.append("相对上一份发生实质变化的 BTST 报告，本轮观察对象没有出现新的结构性切换。")

    return conclusions


def _build_recommendation(nightly_payload: dict[str, Any]) -> str:
    watch_summary = _current_watch_summary(nightly_payload)
    priority_rows = list(watch_summary.get("priority_rows") or [])
    near_miss_tickers = [str(row.get("ticker") or "") for row in priority_rows if str(row.get("lane") or "") == "near_miss_watch" and row.get("ticker")]
    opportunity_tickers = [str(row.get("ticker") or "") for row in priority_rows if str(row.get("lane") or "") == "opportunity_pool" and row.get("ticker")]

    if watch_summary.get("selected_count", 0) > 0:
        return "当前已存在正式主票，明日应优先按主票执行卡组织盘中确认，并把观察层留作备选。"

    near_miss_label = ", ".join(near_miss_tickers) if near_miss_tickers else "无"
    opportunity_label = ", ".join(opportunity_tickers) if opportunity_tickers else "无"
    return f"当前没有主票，明日应继续把 near-miss 作为盘中跟踪层（{near_miss_label}），把机会池作为仅升级备选（{opportunity_label}），不要把观察层直接上调为默认入场。"


def build_btst_latest_close_validation_payload(nightly_payload: dict[str, Any], delta_payload: dict[str, Any]) -> dict[str, Any]:
    latest_run = dict(nightly_payload.get("latest_btst_run") or {})
    latest_snapshot = dict(nightly_payload.get("latest_btst_snapshot") or {})
    watch_summary = _current_watch_summary(nightly_payload)
    governance_validation = dict(dict(nightly_payload.get("control_tower_snapshot") or {}).get("validation") or {})
    governance_synthesis = dict(dict(nightly_payload.get("control_tower_snapshot") or {}).get("synthesis") or {})
    material_anchor = dict(delta_payload.get("material_change_anchor") or {})
    report_rollforward = material_anchor if material_anchor else (delta_payload if str(delta_payload.get("comparison_scope") or "") == "report_rollforward" else {})
    priority_delta = dict(report_rollforward.get("priority_delta") or {})

    focus_rows = []
    for row in list(watch_summary.get("priority_rows") or [])[:4]:
        focus_rows.append(
            {
                "ticker": row.get("ticker"),
                "lane": row.get("lane"),
                "actionability": row.get("actionability"),
                "score_target": row.get("score_target"),
                "execution_quality_label": row.get("execution_quality_label"),
                "suggested_action": row.get("suggested_action"),
            }
        )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "latest_btst_run": latest_run,
        "validation_scope": {
            "current_trade_date": latest_run.get("trade_date"),
            "next_trade_date": latest_run.get("next_trade_date"),
            "comparison_basis": delta_payload.get("comparison_basis"),
            "comparison_scope": delta_payload.get("comparison_scope"),
            "same_report_delta_verdict": delta_payload.get("overall_delta_verdict"),
            "last_material_change_reference": {
                "generated_at": material_anchor.get("reference_generated_at"),
                "report_dir": material_anchor.get("reference_report_dir"),
                "comparison_scope": material_anchor.get("comparison_scope"),
                "overall_delta_verdict": material_anchor.get("overall_delta_verdict"),
            },
        },
        "current_followup": {
            "headline": watch_summary.get("headline"),
            "summary": {
                "selected_count": watch_summary.get("selected_count"),
                "near_miss_count": watch_summary.get("near_miss_count"),
                "blocked_count": watch_summary.get("blocked_count"),
                "rejected_count": watch_summary.get("rejected_count"),
                "opportunity_pool_count": watch_summary.get("opportunity_pool_count"),
            },
            "brief_recommendation": watch_summary.get("brief_recommendation"),
            "focus_rows": focus_rows,
        },
        "rollforward_delta": {
            "headline_changed": priority_delta.get("headline_changed"),
            "previous_headline": priority_delta.get("previous_headline"),
            "current_headline": priority_delta.get("current_headline"),
            "summary_delta": dict(priority_delta.get("summary_delta") or {}),
            "added_tickers": list(priority_delta.get("added_tickers") or []),
            "removed_tickers": list(priority_delta.get("removed_tickers") or []),
            "changed_sections": list(material_anchor.get("changed_sections") or []),
            "operator_focus": [str(item).strip() for item in list(material_anchor.get("operator_focus") or []) if str(item).strip()],
        },
        "governance_check": {
            "overall_verdict": governance_validation.get("overall_verdict"),
            "pass_count": governance_validation.get("pass_count"),
            "warn_count": governance_validation.get("warn_count"),
            "fail_count": governance_validation.get("fail_count"),
            "waiting_lane_count": governance_synthesis.get("waiting_lane_count"),
            "ready_lane_count": governance_synthesis.get("ready_lane_count"),
            "lane_focus": _extract_lane_focus(nightly_payload),
        },
        "key_conclusions": _build_key_conclusions(nightly_payload, delta_payload),
        "recommendation": _build_recommendation(nightly_payload),
        "source_paths": {
            "priority_board_json": latest_snapshot.get("priority_board_json_path"),
            "brief_json": latest_snapshot.get("brief_json_path"),
            "session_summary_json": str((Path(latest_run.get("report_dir_abs") or "") / "session_summary.json").resolve()) if latest_run.get("report_dir_abs") else None,
            "delta_json": None,
        },
    }


def render_btst_latest_close_validation_markdown(payload: dict[str, Any], *, output_path: str | Path) -> str:
    resolved_output_path = Path(output_path).expanduser().resolve()
    validation_scope = dict(payload.get("validation_scope") or {})
    current_followup = dict(payload.get("current_followup") or {})
    current_summary = dict(current_followup.get("summary") or {})
    rollforward_delta = dict(payload.get("rollforward_delta") or {})
    governance_check = dict(payload.get("governance_check") or {})

    lines = [
        "# BTST Latest Close Validation",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- trade_date: {validation_scope.get('current_trade_date') or 'unknown'}",
        f"- next_trade_date: {validation_scope.get('next_trade_date') or 'unknown'}",
        f"- comparison_scope: {validation_scope.get('comparison_scope') or 'unknown'}",
        f"- same_report_delta_verdict: {validation_scope.get('same_report_delta_verdict') or 'unknown'}",
        "",
        "## Tonight Verdict",
        "",
    ]
    for item in list(payload.get("key_conclusions") or []):
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## Current Followup",
            "",
            f"- headline: {current_followup.get('headline') or 'unknown'}",
            f"- selected_count: {current_summary.get('selected_count') or 0}",
            f"- near_miss_count: {current_summary.get('near_miss_count') or 0}",
            f"- blocked_count: {current_summary.get('blocked_count') or 0}",
            f"- rejected_count: {current_summary.get('rejected_count') or 0}",
            f"- opportunity_pool_count: {current_summary.get('opportunity_pool_count') or 0}",
            "",
        ]
    )

    if current_followup.get("brief_recommendation"):
        lines.append(f"- brief_recommendation: {current_followup.get('brief_recommendation')}")
        lines.append("")

    lines.extend(["## Focus Rows", ""])
    for row in list(current_followup.get("focus_rows") or []):
        lines.append(
            f"- {row.get('ticker')}: lane={row.get('lane')}, actionability={row.get('actionability')}, score_target={row.get('score_target')}, execution_quality={row.get('execution_quality_label')}, suggested_action={row.get('suggested_action')}"
        )
    if not list(current_followup.get("focus_rows") or []):
        lines.append("- none")

    lines.extend(["", "## Rollforward Delta", ""])
    lines.append(f"- previous_headline: {rollforward_delta.get('previous_headline') or 'unknown'}")
    lines.append(f"- current_headline: {rollforward_delta.get('current_headline') or 'unknown'}")
    summary_delta = dict(rollforward_delta.get("summary_delta") or {})
    for key, value in summary_delta.items():
        lines.append(f"- summary_delta {key}: {value}")
    for item in list(rollforward_delta.get("added_tickers") or []):
        lines.append(f"- added_ticker: {item.get('ticker')} ({item.get('lane')}, {item.get('actionability')})")
    for item in list(rollforward_delta.get("removed_tickers") or []):
        lines.append(f"- removed_ticker: {item.get('ticker')} ({item.get('lane')}, {item.get('actionability')})")
    for item in list(rollforward_delta.get("changed_sections") or []):
        lines.append(f"- changed_section: {item}")
    for item in list(rollforward_delta.get("operator_focus") or []):
        lines.append(f"- operator_focus: {item}")

    lines.extend(["", "## Governance Check", ""])
    lines.append(f"- overall_verdict: {governance_check.get('overall_verdict') or 'unknown'}")
    lines.append(f"- pass_count: {governance_check.get('pass_count') or 0}")
    lines.append(f"- warn_count: {governance_check.get('warn_count') or 0}")
    lines.append(f"- fail_count: {governance_check.get('fail_count') or 0}")
    lines.append(f"- waiting_lane_count: {governance_check.get('waiting_lane_count') or 0}")
    lines.append(f"- ready_lane_count: {governance_check.get('ready_lane_count') or 0}")
    for row in list(governance_check.get("lane_focus") or []):
        lines.append(
            f"- lane {row.get('lane_id')}: ticker={row.get('ticker')}, status={row.get('lane_status')}, validation_verdict={row.get('validation_verdict')}, missing_window_count={row.get('missing_window_count')}, next_step={row.get('next_step')}"
        )

    lines.extend(["", "## Recommendation", "", f"- {payload.get('recommendation') or 'unknown'}", ""])

    lines.extend(["## Source Paths", ""])
    for label, source_path in dict(payload.get("source_paths") or {}).items():
        lines.append(f"- {label}: {_relative_link(source_path, resolved_output_path) or source_path or 'unknown'}")
    lines.append("")
    return "\n".join(lines)


def generate_btst_latest_close_validation_artifacts(
    *,
    nightly_payload: dict[str, Any] | None = None,
    delta_payload: dict[str, Any] | None = None,
    nightly_json_path: str | Path | None = None,
    delta_json_path: str | Path | None = None,
    output_json: str | Path | None = None,
    output_md: str | Path | None = None,
) -> dict[str, Any]:
    resolved_nightly_json_path = Path(nightly_json_path).expanduser().resolve() if nightly_json_path else None
    resolved_delta_json_path = Path(delta_json_path).expanduser().resolve() if delta_json_path else None
    current_nightly_payload = dict(nightly_payload or _safe_load_json(resolved_nightly_json_path))
    current_delta_payload = dict(delta_payload or _safe_load_json(resolved_delta_json_path))
    if not current_nightly_payload:
        raise ValueError("nightly payload is required")
    if not current_delta_payload:
        raise ValueError("delta payload is required")

    resolved_output_json = Path(output_json).expanduser().resolve() if output_json else Path(DEFAULT_OUTPUT_JSON).expanduser().resolve()
    resolved_output_md = Path(output_md).expanduser().resolve() if output_md else Path(DEFAULT_OUTPUT_MD).expanduser().resolve()
    payload = build_btst_latest_close_validation_payload(current_nightly_payload, current_delta_payload)
    payload["source_paths"]["delta_json"] = str(resolved_delta_json_path) if resolved_delta_json_path else None

    resolved_output_json.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_md.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resolved_output_md.write_text(render_btst_latest_close_validation_markdown(payload, output_path=resolved_output_md), encoding="utf-8")
    return {
        "payload": payload,
        "json_path": resolved_output_json.as_posix(),
        "markdown_path": resolved_output_md.as_posix(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the latest BTST close validation summary from nightly control tower artifacts.")
    parser.add_argument("--nightly-json", default=str(REPORTS_DIR / "btst_nightly_control_tower_latest.json"), help="Nightly control tower JSON path")
    parser.add_argument("--delta-json", default=str(REPORTS_DIR / "btst_open_ready_delta_latest.json"), help="Open-ready delta JSON path")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON), help="Output JSON artifact path")
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD), help="Output Markdown artifact path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = generate_btst_latest_close_validation_artifacts(
        nightly_json_path=args.nightly_json,
        delta_json_path=args.delta_json,
        output_json=args.output_json,
        output_md=args.output_md,
    )
    print(f"btst_latest_close_validation_json={result['json_path']}")
    print(f"btst_latest_close_validation_markdown={result['markdown_path']}")


if __name__ == "__main__":
    main()