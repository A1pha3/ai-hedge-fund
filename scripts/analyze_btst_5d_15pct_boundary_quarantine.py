"""⚠️ DEPRECATED — 5d_15pct boundary quarantine decision analysis. One-time experiment from 2026-Q1; kept for historical reference only."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.analyze_btst_5d_15pct_boundary_contract_inspection import analyze_btst_5d_15pct_boundary_contract_inspection
from scripts.btst_boundary_quarantine_helpers import (
    classify_boundary_quarantine_decision,
    is_boundary_without_explainability_target,
    summarize_boundary_quarantine_rows,
)


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_5d_15pct_boundary_quarantine_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_5d_15pct_boundary_quarantine_latest.md"


def _build_governance_decision_board(decision_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    action_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in decision_rows:
        action_groups[str(row.get("governance_action") or "unknown")].append(row)

    board: list[dict[str, Any]] = []
    for action, action_rows in action_groups.items():
        board.append(
            {
                "action": action,
                "row_count": len(action_rows),
                "tickers": sorted(str(row.get("ticker") or "") for row in action_rows if row.get("ticker")),
            }
        )

    return sorted(board, key=lambda row: (-int(row["row_count"]), str(row["action"])))


def _build_research_surface_lists(decision_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    lists = {"allow": [], "quarantine": [], "separate_surface": []}
    for disposition in lists:
        lists[disposition] = sorted(str(row.get("ticker") or "") for row in decision_rows if row.get("research_surface_disposition") == disposition and row.get("ticker"))
    return lists


def analyze_btst_5d_15pct_boundary_quarantine_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decision_rows = [classify_boundary_quarantine_decision(row) for row in rows if is_boundary_without_explainability_target(row)]
    summary = summarize_boundary_quarantine_rows(decision_rows)
    disposition_counts = dict(summary.get("disposition_counts") or {})
    research_surface_lists = _build_research_surface_lists(decision_rows)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "boundary_row_count": len(decision_rows),
        "decision_rows": decision_rows,
        "disposition_summary_board": [
            {
                "allow_count": disposition_counts.get("allow", 0),
                "quarantine_count": disposition_counts.get("quarantine", 0),
                "separate_surface_count": disposition_counts.get("separate_surface", 0),
            }
        ],
        "source_summary_board": list(summary.get("source_summary_board") or []),
        "governance_decision_board": _build_governance_decision_board(decision_rows),
        "research_surface_lists": research_surface_lists,
    }


def analyze_btst_5d_15pct_boundary_quarantine(reports_root: str | Path) -> dict[str, Any]:
    inspection = analyze_btst_5d_15pct_boundary_contract_inspection(reports_root)
    analysis = analyze_btst_5d_15pct_boundary_quarantine_from_rows(list(inspection.get("boundary_rows") or []))
    analysis["reports_root"] = str(Path(reports_root))
    return analysis


def render_btst_5d_15pct_boundary_quarantine_markdown(analysis: dict[str, Any]) -> str:
    disposition_summary = dict((analysis.get("disposition_summary_board") or [{}])[0])
    lines = [
        "# BTST 5D / +15% Boundary Quarantine",
        "",
        f"- boundary_row_count: {analysis.get('boundary_row_count')}",
        "",
        "## disposition_summary_board",
        f"- allow_count: {disposition_summary.get('allow_count', 0)}",
        f"- quarantine_count: {disposition_summary.get('quarantine_count', 0)}",
        f"- separate_surface_count: {disposition_summary.get('separate_surface_count', 0)}",
        "",
        "## source_summary_board",
    ]
    for row in list(analysis.get("source_summary_board") or []):
        lines.append(
            f"- {row.get('candidate_source')}: row_count={row.get('row_count')}, quarantine_count={row.get('quarantine_count')}, separate_surface_count={row.get('separate_surface_count')}, allow_count={row.get('allow_count')}"
        )
    if not list(analysis.get("source_summary_board") or []):
        lines.append("- none")
    lines.extend(["", "## governance_decision_board"])
    for row in list(analysis.get("governance_decision_board") or []):
        lines.append(f"- {row.get('action')}: row_count={row.get('row_count')}, tickers={row.get('tickers')}")
    if not list(analysis.get("governance_decision_board") or []):
        lines.append("- none")
    lines.extend(["", "## research_surface_lists"])
    for disposition in ("allow", "quarantine", "separate_surface"):
        lines.append(f"- {disposition}: {list((analysis.get('research_surface_lists') or {}).get(disposition) or [])}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the BTST 5D/+15% boundary quarantine artifact.")
    parser.add_argument("--reports-root", type=Path, default=REPORTS_DIR)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    args = parser.parse_args()

    analysis = analyze_btst_5d_15pct_boundary_quarantine(args.reports_root)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_md.write_text(render_btst_5d_15pct_boundary_quarantine_markdown(analysis), encoding="utf-8")
    boundary_row_count = analysis.get("boundary_row_count")
    governance_actions = ",".join(str(row.get("action")) for row in list(analysis.get("governance_decision_board") or []))
    print(f"quarantine analysis: boundary_row_count={boundary_row_count}, governance_actions={governance_actions}, output_json={args.output_json}, output_md={args.output_md}")


if __name__ == "__main__":
    main()
