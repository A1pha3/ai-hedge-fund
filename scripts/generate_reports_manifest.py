from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "report_manifest_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "report_manifest_latest.md"

STATIC_ENTRY_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "reports_hub_readme",
        "path": "data/reports/README.md",
        "report_type": "report_hub_readme",
        "topic": "reports_navigation",
        "usage": "navigation",
        "priority": 1,
        "is_latest": True,
        "question": "reports 根入口是什么",
        "view_order": 1,
        "time_scope": {"label": "rolling"},
        "source_kind": "stable_entry_page",
    },
    {
        "id": "optimize0330_readme",
        "path": "docs/zh-cn/factors/BTST/optimize0330/README.md",
        "report_type": "source_of_truth_doc",
        "topic": "btst_optimize0330",
        "usage": "truth_source",
        "priority": 1,
        "is_latest": True,
        "question": "0330 BTST 当前主线逻辑是什么",
        "view_order": 1,
        "time_scope": {"label": "rolling"},
        "source_kind": "source_of_truth",
    },
    {
        "id": "optimize0330_checklist",
        "path": "docs/zh-cn/factors/BTST/optimize0330/01-0330-research-execution-checklist.md",
        "report_type": "execution_checklist",
        "topic": "btst_optimize0330",
        "usage": "truth_source",
        "priority": 2,
        "is_latest": True,
        "question": "0330 BTST 当前执行状态和下一步动作是什么",
        "view_order": 2,
        "time_scope": {"label": "rolling"},
        "source_kind": "source_of_truth",
    },
    {
        "id": "arch_optimize_implementation",
        "path": "docs/zh-cn/product/arch/arch_optimize_implementation.md",
        "report_type": "implementation_truth_doc",
        "topic": "upstream_architecture",
        "usage": "truth_source",
        "priority": 3,
        "is_latest": True,
        "question": "上游真实落地事实与系统边界是什么",
        "view_order": 3,
        "time_scope": {"label": "rolling"},
        "source_kind": "source_of_truth",
    },
    {
        "id": "p2_top3_execution_summary",
        "path": "data/reports/p2_top3_experiment_execution_summary_20260330.json",
        "report_type": "btst_execution_summary",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 1,
        "is_latest": True,
        "question": "Top 3 case-based 执行结果是什么",
        "view_order": 1,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p3_post_execution_action_board",
        "path": "data/reports/p3_top3_post_execution_action_board_20260330.json",
        "report_type": "btst_action_board",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 2,
        "is_latest": True,
        "question": "当前 lane 分流后的动作板是什么",
        "view_order": 2,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p5_rollout_governance_board",
        "path": "data/reports/p5_btst_rollout_governance_board_20260330.json",
        "report_type": "btst_rollout_governance_board",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 3,
        "is_latest": True,
        "question": "当前 default / shadow / freeze 治理结论是什么",
        "view_order": 3,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "btst_micro_window_regression_review",
        "path": "data/reports/btst_micro_window_regression_20260330.md",
        "report_type": "btst_micro_window_regression_review",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 4,
        "is_latest": True,
        "question": "0323-0326 闭环 baseline 与 catalyst_floor_zero 的微窗口回归结果是什么",
        "view_order": 4,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p6_primary_window_gap",
        "path": "data/reports/p6_primary_window_gap_001309_20260330.json",
        "report_type": "btst_window_gap_runbook",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 5,
        "is_latest": True,
        "question": "001309 还缺什么窗口证据",
        "view_order": 5,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p6_recurring_shadow_runbook",
        "path": "data/reports/p6_recurring_shadow_runbook_20260330.json",
        "report_type": "btst_recurring_shadow_runbook",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 6,
        "is_latest": True,
        "question": "recurring shadow lane 该如何阅读和执行",
        "view_order": 6,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p7_primary_window_validation_runbook",
        "path": "data/reports/p7_primary_window_validation_runbook_001309_20260330.json",
        "report_type": "btst_primary_validation_runbook",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 7,
        "is_latest": True,
        "question": "001309 后续复跑命令与判断条件是什么",
        "view_order": 7,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "p8_structural_shadow_runbook",
        "path": "data/reports/p8_structural_shadow_runbook_300724_20260330.json",
        "report_type": "btst_structural_shadow_runbook",
        "topic": "btst_governance",
        "usage": "btst_governance",
        "priority": 8,
        "is_latest": True,
        "question": "300724 为什么保持 structural shadow hold",
        "view_order": 8,
        "time_scope": {"label": "current_window_20260330"},
        "source_kind": "governance_artifact",
    },
    {
        "id": "replay_artifacts_stock_selection_manual",
        "path": "docs/zh-cn/manual/replay-artifacts-stock-selection-manual.md",
        "report_type": "manual",
        "topic": "replay_artifacts",
        "usage": "replay_history",
        "priority": 1,
        "is_latest": True,
        "question": "Replay Artifacts 工作台如何查报告",
        "view_order": 1,
        "time_scope": {"label": "rolling"},
        "source_kind": "manual",
    },
    {
        "id": "historical_edge_artifact_index",
        "path": "docs/zh-cn/analysis/historical-edge-artifact-index-20260318.md",
        "report_type": "artifact_index",
        "topic": "historical_edge",
        "usage": "replay_history",
        "priority": 2,
        "is_latest": True,
        "question": "历史 edge 专题从哪里进入",
        "view_order": 2,
        "time_scope": {"label": "historical_archive"},
        "source_kind": "artifact_index",
    },
)

READING_PATH_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "navigation",
        "title": "入口导航",
        "description": "先看稳定入口，不直接翻 data/reports 目录。",
        "entry_ids": ["reports_hub_readme", "optimize0330_readme", "optimize0330_checklist", "arch_optimize_implementation"],
    },
    {
        "id": "tomorrow_open",
        "title": "明天开盘",
        "description": "开盘前的最短阅读路径，优先解决明天到底交易什么。",
        "entry_ids": ["latest_btst_opening_watch_card", "latest_btst_execution_card_markdown", "latest_btst_brief_markdown"],
    },
    {
        "id": "nightly_review",
        "title": "晚间复盘",
        "description": "晚间确认本次运行发生了什么、明日结论为何如此。",
        "entry_ids": ["latest_btst_session_summary", "latest_btst_brief_json", "latest_btst_execution_card_json", "latest_btst_selection_snapshot"],
    },
    {
        "id": "btst_governance",
        "title": "BTST 治理主线",
        "description": "解释当前 lane 为什么被保留、冻结或只允许 shadow。",
        "entry_ids": [
            "p2_top3_execution_summary",
            "p3_post_execution_action_board",
            "p5_rollout_governance_board",
            "btst_micro_window_regression_review",
            "p6_primary_window_gap",
            "p6_recurring_shadow_runbook",
            "p7_primary_window_validation_runbook",
            "p8_structural_shadow_runbook",
        ],
    },
    {
        "id": "truth_source",
        "title": "真相源文档",
        "description": "专题逻辑、执行状态和上游实现事实的固定 source of truth。",
        "entry_ids": ["optimize0330_readme", "optimize0330_checklist", "arch_optimize_implementation"],
    },
    {
        "id": "replay_history",
        "title": "Replay 与历史专题",
        "description": "需要从工作台或历史专题入口回查时，固定从这里进入。",
        "entry_ids": ["replay_artifacts_stock_selection_manual", "historical_edge_artifact_index"],
    },
)


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def _normalize_trade_date(value: Any) -> str | None:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
    if len(digits) != 8:
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"


def _resolve_repo_root(reports_root: Path) -> Path:
    resolved_reports_root = reports_root.expanduser().resolve()
    if resolved_reports_root.name == "reports" and resolved_reports_root.parent.name == "data":
        return resolved_reports_root.parent.parent
    return resolved_reports_root.parent


def _repo_relative_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _build_entry(
    *,
    entry_id: str,
    absolute_path: Path,
    repo_root: Path,
    report_type: str,
    topic: str,
    usage: str,
    priority: int,
    is_latest: bool,
    question: str,
    view_order: int,
    time_scope: dict[str, Any],
    source_kind: str,
    report_dir: str | None = None,
) -> dict[str, Any] | None:
    resolved_path = absolute_path.expanduser().resolve()
    if not resolved_path.exists():
        return None
    return {
        "id": entry_id,
        "report_path": _repo_relative_path(resolved_path, repo_root),
        "absolute_path": resolved_path.as_posix(),
        "report_type": report_type,
        "topic": topic,
        "usage": usage,
        "priority": priority,
        "is_latest": is_latest,
        "question": question,
        "view_order": view_order,
        "time_scope": time_scope,
        "source_kind": source_kind,
        "report_dir": report_dir,
    }


def _looks_like_report_dir(path: Path) -> bool:
    return path.is_dir() and (path / "session_summary.json").exists() and (path / "selection_artifacts").exists()


def _discover_report_dirs(reports_root: Path) -> list[Path]:
    resolved_reports_root = reports_root.expanduser().resolve()
    if not resolved_reports_root.exists():
        return []
    return sorted(
        candidate
        for candidate in resolved_reports_root.iterdir()
        if _looks_like_report_dir(candidate) and candidate.name.startswith("paper_trading")
    )


def _extract_btst_candidate(report_dir: Path, repo_root: Path) -> dict[str, Any] | None:
    summary = _load_json(report_dir / "session_summary.json")
    followup = dict(summary.get("btst_followup") or {})
    artifacts = dict(summary.get("artifacts") or {})
    selection_target = str(summary.get("plan_generation", {}).get("selection_target") or summary.get("selection_target") or "")

    brief_json_path = followup.get("brief_json") or artifacts.get("btst_next_day_trade_brief_json")
    brief_markdown_path = followup.get("brief_markdown") or artifacts.get("btst_next_day_trade_brief_markdown")
    card_json_path = followup.get("execution_card_json") or artifacts.get("btst_premarket_execution_card_json")
    card_markdown_path = followup.get("execution_card_markdown") or artifacts.get("btst_premarket_execution_card_markdown")
    if not any([brief_json_path, brief_markdown_path, card_json_path, card_markdown_path]):
        return None

    trade_date = _normalize_trade_date(followup.get("trade_date") or summary.get("end_date"))
    next_trade_date = _normalize_trade_date(followup.get("next_trade_date"))
    selection_snapshot_path = report_dir / "selection_artifacts" / trade_date / "selection_snapshot.json" if trade_date else None
    opening_card_path = report_dir / f"btst_opening_watch_card_{next_trade_date.replace('-', '')}.md" if next_trade_date else None

    trade_date_rank = trade_date or _normalize_trade_date(summary.get("end_date")) or ""
    selection_target_rank = 2 if selection_target == "short_trade_only" else 1

    return {
        "report_dir": report_dir.resolve(),
        "report_dir_name": report_dir.name,
        "report_dir_path": _repo_relative_path(report_dir, repo_root),
        "selection_target": selection_target or None,
        "trade_date": trade_date,
        "next_trade_date": next_trade_date,
        "brief_json_path": Path(brief_json_path).expanduser().resolve() if brief_json_path else None,
        "brief_markdown_path": Path(brief_markdown_path).expanduser().resolve() if brief_markdown_path else None,
        "card_json_path": Path(card_json_path).expanduser().resolve() if card_json_path else None,
        "card_markdown_path": Path(card_markdown_path).expanduser().resolve() if card_markdown_path else None,
        "session_summary_path": (report_dir / "session_summary.json").resolve(),
        "selection_snapshot_path": selection_snapshot_path.resolve() if selection_snapshot_path and selection_snapshot_path.exists() else None,
        "opening_card_path": opening_card_path.resolve() if opening_card_path and opening_card_path.exists() else None,
        "rank": (selection_target_rank, trade_date_rank, report_dir.stat().st_mtime_ns, report_dir.name),
    }


def _select_latest_btst_candidate(reports_root: Path, repo_root: Path) -> dict[str, Any] | None:
    candidates = [candidate for candidate in (_extract_btst_candidate(path, repo_root) for path in _discover_report_dirs(reports_root)) if candidate]
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate["rank"])


def _build_static_entries(repo_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for spec in STATIC_ENTRY_SPECS:
        entry = _build_entry(
            entry_id=spec["id"],
            absolute_path=repo_root / spec["path"],
            repo_root=repo_root,
            report_type=spec["report_type"],
            topic=spec["topic"],
            usage=spec["usage"],
            priority=int(spec["priority"]),
            is_latest=bool(spec["is_latest"]),
            question=spec["question"],
            view_order=int(spec["view_order"]),
            time_scope=dict(spec["time_scope"]),
            source_kind=spec["source_kind"],
        )
        if entry:
            entries.append(entry)
    return entries


def _build_dynamic_latest_btst_entries(latest_btst_run: dict[str, Any] | None, repo_root: Path) -> list[dict[str, Any]]:
    if not latest_btst_run:
        return []

    report_dir = latest_btst_run["report_dir_path"]
    time_scope = {
        "label": "latest_btst_followup",
        "trade_date": latest_btst_run.get("trade_date"),
        "next_trade_date": latest_btst_run.get("next_trade_date"),
    }

    dynamic_specs = [
        {
            "id": "latest_btst_opening_watch_card",
            "path": latest_btst_run.get("opening_card_path"),
            "report_type": "btst_opening_watch_card",
            "topic": "btst_followup",
            "usage": "tomorrow_open",
            "priority": 1,
            "is_latest": True,
            "question": "明天开盘第一眼该看什么",
            "view_order": 1,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_execution_card_markdown",
            "path": latest_btst_run.get("card_markdown_path"),
            "report_type": "btst_premarket_execution_card_markdown",
            "topic": "btst_followup",
            "usage": "tomorrow_open",
            "priority": 2,
            "is_latest": True,
            "question": "当前执行姿态和 guardrails 是什么",
            "view_order": 2,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_brief_markdown",
            "path": latest_btst_run.get("brief_markdown_path"),
            "report_type": "btst_next_day_trade_brief_markdown",
            "topic": "btst_followup",
            "usage": "tomorrow_open",
            "priority": 3,
            "is_latest": True,
            "question": "明日主票、观察票和排除票结论是什么",
            "view_order": 3,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_session_summary",
            "path": latest_btst_run.get("session_summary_path"),
            "report_type": "paper_trading_session_summary",
            "topic": "btst_followup",
            "usage": "nightly_review",
            "priority": 1,
            "is_latest": True,
            "question": "这次运行整体发生了什么",
            "view_order": 1,
            "source_kind": "generated_runtime_artifact",
        },
        {
            "id": "latest_btst_brief_json",
            "path": latest_btst_run.get("brief_json_path"),
            "report_type": "btst_next_day_trade_brief_json",
            "topic": "btst_followup",
            "usage": "nightly_review",
            "priority": 2,
            "is_latest": True,
            "question": "结构化主票与观察票结论是什么",
            "view_order": 2,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_execution_card_json",
            "path": latest_btst_run.get("card_json_path"),
            "report_type": "btst_premarket_execution_card_json",
            "topic": "btst_followup",
            "usage": "nightly_review",
            "priority": 3,
            "is_latest": True,
            "question": "结构化执行 guardrails 是什么",
            "view_order": 3,
            "source_kind": "generated_btst_followup",
        },
        {
            "id": "latest_btst_selection_snapshot",
            "path": latest_btst_run.get("selection_snapshot_path"),
            "report_type": "selection_snapshot",
            "topic": "btst_followup",
            "usage": "nightly_review",
            "priority": 4,
            "is_latest": True,
            "question": "逐票底层证据是什么",
            "view_order": 4,
            "source_kind": "generated_runtime_artifact",
        },
    ]

    entries: list[dict[str, Any]] = []
    for spec in dynamic_specs:
        path = spec.get("path")
        if not path:
            continue
        entry = _build_entry(
            entry_id=spec["id"],
            absolute_path=Path(path),
            repo_root=repo_root,
            report_type=spec["report_type"],
            topic=spec["topic"],
            usage=spec["usage"],
            priority=int(spec["priority"]),
            is_latest=bool(spec["is_latest"]),
            question=spec["question"],
            view_order=int(spec["view_order"]),
            time_scope=dict(time_scope),
            source_kind=spec["source_kind"],
            report_dir=report_dir,
        )
        if entry:
            entries.append(entry)
    return entries


def generate_reports_manifest(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    repo_root = _resolve_repo_root(resolved_reports_root)
    latest_btst_run = _select_latest_btst_candidate(resolved_reports_root, repo_root)

    entries = _build_static_entries(repo_root) + _build_dynamic_latest_btst_entries(latest_btst_run, repo_root)
    entries.sort(key=lambda entry: (entry["usage"], entry["priority"], entry["view_order"], entry["id"]))

    entry_ids = {entry["id"] for entry in entries}
    reading_paths: list[dict[str, Any]] = []
    for spec in READING_PATH_SPECS:
        resolved_entry_ids = [entry_id for entry_id in spec["entry_ids"] if entry_id in entry_ids]
        if not resolved_entry_ids:
            continue
        reading_paths.append(
            {
                "id": spec["id"],
                "title": spec["title"],
                "description": spec["description"],
                "entry_ids": resolved_entry_ids,
            }
        )

    entry_count_by_usage: dict[str, int] = {}
    for entry in entries:
        entry_count_by_usage[entry["usage"]] = entry_count_by_usage.get(entry["usage"], 0) + 1

    manifest: dict[str, Any] = {
        "manifest_version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "repo_root": repo_root.as_posix(),
        "reports_root": resolved_reports_root.as_posix(),
        "entry_count": len(entries),
        "entry_count_by_usage": entry_count_by_usage,
        "latest_btst_run": None,
        "reading_paths": reading_paths,
        "entries": entries,
    }
    if latest_btst_run:
        manifest["latest_btst_run"] = {
            "report_dir": latest_btst_run["report_dir_path"],
            "report_dir_abs": latest_btst_run["report_dir"].as_posix(),
            "selection_target": latest_btst_run.get("selection_target"),
            "trade_date": latest_btst_run.get("trade_date"),
            "next_trade_date": latest_btst_run.get("next_trade_date"),
        }
    return manifest


def _build_markdown_link(entry: dict[str, Any], output_parent: Path) -> str:
    relative_target = Path(os.path.relpath(entry["absolute_path"], output_parent)).as_posix()
    return f"[{entry['report_path']}]({relative_target})"


def render_reports_manifest_markdown(manifest: dict[str, Any], *, output_parent: str | Path) -> str:
    resolved_output_parent = Path(output_parent).expanduser().resolve()
    entries_by_id = {entry["id"]: entry for entry in list(manifest.get("entries") or [])}

    lines: list[str] = []
    lines.append("# Reports Manifest Latest")
    lines.append("")
    lines.append(f"- generated_at: {manifest['generated_at']}")
    lines.append(f"- entry_count: {manifest['entry_count']}")
    lines.append(f"- reports_root: {manifest['reports_root']}")
    latest_btst_run = manifest.get("latest_btst_run") or {}
    if latest_btst_run:
        lines.append(f"- latest_btst_report_dir: {latest_btst_run['report_dir']}")
        lines.append(f"- latest_btst_trade_date: {latest_btst_run.get('trade_date')}")
        lines.append(f"- latest_btst_next_trade_date: {latest_btst_run.get('next_trade_date')}")
        lines.append(f"- latest_btst_selection_target: {latest_btst_run.get('selection_target')}")
    lines.append("")

    for reading_path in list(manifest.get("reading_paths") or []):
        lines.append(f"## {reading_path['title']}")
        lines.append("")
        lines.append(reading_path["description"])
        lines.append("")
        for index, entry_id in enumerate(list(reading_path.get("entry_ids") or []), start=1):
            entry = entries_by_id[entry_id]
            lines.append(f"{index}. {_build_markdown_link(entry, resolved_output_parent)}")
            lines.append(f"   用途：{entry['question']}")
            lines.append(f"   类型：{entry['report_type']} | usage={entry['usage']} | priority={entry['priority']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def generate_reports_manifest_artifacts(
    reports_root: str | Path,
    *,
    output_json: str | Path | None = None,
    output_md: str | Path | None = None,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    resolved_output_json = Path(output_json).expanduser().resolve() if output_json else (resolved_reports_root / DEFAULT_OUTPUT_JSON.name).resolve()
    resolved_output_md = Path(output_md).expanduser().resolve() if output_md else (resolved_reports_root / DEFAULT_OUTPUT_MD.name).resolve()
    manifest = generate_reports_manifest(resolved_reports_root)
    resolved_output_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resolved_output_md.write_text(render_reports_manifest_markdown(manifest, output_parent=resolved_output_md.parent), encoding="utf-8")
    return {
        "manifest": manifest,
        "json_path": resolved_output_json.as_posix(),
        "markdown_path": resolved_output_md.as_posix(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a machine-readable manifest for frequently reviewed reports under data/reports.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR), help="Reports root directory to scan")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON), help="Output JSON manifest path")
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD), help="Output Markdown manifest path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = generate_reports_manifest_artifacts(
        reports_root=args.reports_root,
        output_json=args.output_json,
        output_md=args.output_md,
    )
    print(f"report_manifest_json={result['json_path']}")
    print(f"report_manifest_markdown={result['markdown_path']}")


if __name__ == "__main__":
    main()