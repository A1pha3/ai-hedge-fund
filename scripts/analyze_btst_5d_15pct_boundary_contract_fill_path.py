from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.analyze_btst_5d_15pct_boundary_contract_inspection import (
    analyze_btst_5d_15pct_boundary_contract_inspection,
)
from scripts.btst_boundary_contract_fill_helpers import (
    recommend_boundary_repair_action,
    repair_boundary_contract_row,
)

DEFAULT_REPORTS_ROOT = Path("data/reports")
DEFAULT_OUTPUT_JSON = DEFAULT_REPORTS_ROOT / "btst_5d_15pct_boundary_contract_fill_path_latest.json"
DEFAULT_OUTPUT_MD = DEFAULT_REPORTS_ROOT / "btst_5d_15pct_boundary_contract_fill_path_latest.md"


def _summarize_repair_sources(repaired_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in repaired_rows:
        source_groups[str(row.get("candidate_source") or "unknown")].append(row)

    repair_source_summary_board: list[dict[str, Any]] = []
    for candidate_source, source_rows in source_groups.items():
        repair_counter = Counter(str(row.get("repair_status") or "unknown") for row in source_rows)
        repair_source_summary_board.append(
            {
                "candidate_source": candidate_source,
                "row_count": len(source_rows),
                "fully_repaired_row_count": repair_counter.get("fully_repaired_boundary_contract", 0),
                "partially_repaired_row_count": repair_counter.get("partially_repaired_boundary_contract", 0),
                "irrecoverable_row_count": repair_counter.get("irrecoverable_boundary_contract", 0),
            }
        )

    return sorted(repair_source_summary_board, key=lambda row: (-int(row["row_count"]), str(row["candidate_source"])))


def analyze_btst_5d_15pct_boundary_contract_fill_path_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    repaired_rows: list[dict[str, Any]] = []
    for row in rows:
        repaired_rows.append(repair_boundary_contract_row(row))

    repair_counter = Counter(str(row["repair_status"]) for row in repaired_rows)
    summary = {
        "fully_repaired_row_count": repair_counter.get("fully_repaired_boundary_contract", 0),
        "partially_repaired_row_count": repair_counter.get("partially_repaired_boundary_contract", 0),
        "irrecoverable_row_count": repair_counter.get("irrecoverable_boundary_contract", 0),
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "boundary_row_count": len(repaired_rows),
        "repair_status_board": repaired_rows,
        "repair_summary_board": [summary],
        "repair_source_summary_board": _summarize_repair_sources(repaired_rows),
        "governance_decision_board": [
            {
                "action": recommend_boundary_repair_action(summary),
                "reason": "boundary fill-path outcome is governed by irrecoverable and partial repair counts",
            }
        ],
    }


def analyze_btst_5d_15pct_boundary_contract_fill_path(reports_root: str | Path) -> dict[str, Any]:
    inspection = analyze_btst_5d_15pct_boundary_contract_inspection(reports_root)
    return analyze_btst_5d_15pct_boundary_contract_fill_path_from_rows(list(inspection["boundary_rows"]))


def render_btst_5d_15pct_boundary_contract_fill_path_markdown(analysis: dict[str, Any]) -> str:
    summary = dict((analysis.get("repair_summary_board") or [{}])[0])
    governance = dict((analysis.get("governance_decision_board") or [{}])[0])
    lines = [
        "# BTST 5D / +15% Boundary Contract Fill Path",
        "",
        f"- boundary_row_count: {analysis.get('boundary_row_count')}",
        "",
        "## repair_summary_board",
        f"- fully_repaired_row_count: {summary.get('fully_repaired_row_count')}",
        f"- partially_repaired_row_count: {summary.get('partially_repaired_row_count')}",
        f"- irrecoverable_row_count: {summary.get('irrecoverable_row_count')}",
        "",
        "## repair_source_summary_board",
    ]
    for row in list(analysis.get("repair_source_summary_board") or []):
        lines.append(f"- {row.get('candidate_source')}: row_count={row.get('row_count')}, fully_repaired_row_count={row.get('fully_repaired_row_count')}, partially_repaired_row_count={row.get('partially_repaired_row_count')}, irrecoverable_row_count={row.get('irrecoverable_row_count')}")
    if not list(analysis.get("repair_source_summary_board") or []):
        lines.append("- none")
    lines.extend(
        [
            "",
            "## governance_decision_board",
            f"- {governance.get('action')}: {governance.get('reason')}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the BTST 5D/+15% boundary contract fill-path artifact.")
    parser.add_argument("--reports-root", type=Path, default=DEFAULT_REPORTS_ROOT)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    args = parser.parse_args()

    analysis = analyze_btst_5d_15pct_boundary_contract_fill_path(args.reports_root)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_md.write_text(render_btst_5d_15pct_boundary_contract_fill_path_markdown(analysis), encoding="utf-8")
    boundary_row_count = analysis.get("boundary_row_count")
    governance_action = (analysis.get("governance_decision_board") or [{}])[0].get("action")
    print(f"fill_path analysis: boundary_row_count={boundary_row_count}, governance_action={governance_action}, output_json={args.output_json}, output_md={args.output_md}")


if __name__ == "__main__":
    main()
