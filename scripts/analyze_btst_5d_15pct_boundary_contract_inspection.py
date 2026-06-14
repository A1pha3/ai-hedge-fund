from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.analyze_btst_5d_15pct_missing_core_features_noise_compression import (
    CORE_EXPLAINABILITY_KEYS,
)
from scripts.btst_analysis_utils import (
    extract_btst_price_outcome as _extract_btst_price_outcome,
)
from scripts.btst_analysis_utils import (
    iter_selection_snapshots as _iter_selection_snapshots,
)
from scripts.btst_analysis_utils import normalize_trade_date as _normalize_trade_date
from scripts.btst_boundary_contract_helpers import (
    classify_boundary_contract_verdict,
    recommend_boundary_contract_action,
    summarize_boundary_contract_group,
)
from scripts.btst_missing_core_features_noise_helpers import (
    classify_missing_core_root_cause,
)
from scripts.btst_report_utils import (
    discover_nested_report_dirs as discover_report_dirs,
)
from scripts.btst_round1_factor_mining_helpers import build_round1_research_row
from scripts.btst_round1_unclassified_split_helpers import classify_unclassified_bucket

REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_5d_15pct_boundary_contract_inspection_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_5d_15pct_boundary_contract_inspection_latest.md"
BOUNDARY_CONTEXT_KEYS = tuple(sorted(CORE_EXPLAINABILITY_KEYS))


def _build_boundary_row(*, ticker: str, trade_date: str, report_dir_name: str, evaluation: dict[str, Any], price_outcome: dict[str, Any]) -> dict[str, Any]:
    short_trade = dict((evaluation or {}).get("short_trade") or {})
    explainability = dict(short_trade.get("explainability_payload") or {})
    row = build_round1_research_row(
        ticker=ticker,
        trade_date=trade_date,
        report_dir_name=report_dir_name,
        evaluation=evaluation,
        price_outcome=price_outcome,
    )
    row["bucket"] = classify_unclassified_bucket(row) if row.get("event_prototype") == "unclassified" else None
    row["core_explainability_key_count"] = sum(1 for key in CORE_EXPLAINABILITY_KEYS if key in explainability)
    row["metadata_keys"] = sorted(key for key in explainability if key not in CORE_EXPLAINABILITY_KEYS)
    row["root_cause"] = classify_missing_core_root_cause(
        {
            **row,
            "explainability_key_count": len(explainability),
            "core_explainability_key_count": row["core_explainability_key_count"],
        }
    )
    row["boundary_context"] = {key: row[key] for key in BOUNDARY_CONTEXT_KEYS if row.get(key) is not None}
    return row


def analyze_btst_5d_15pct_boundary_contract_inspection(reports_root: str | Path) -> dict[str, Any]:
    resolved_root = Path(reports_root).expanduser().resolve()
    rows: list[dict[str, Any]] = []
    price_cache: dict[tuple[str, str], Any] = {}
    for report_dir in discover_report_dirs([resolved_root], report_name_contains="paper_trading_window"):
        for snapshot in _iter_selection_snapshots(report_dir) or []:
            trade_date = _normalize_trade_date(snapshot.get("trade_date"))
            for ticker, evaluation in dict(snapshot.get("selection_targets") or {}).items():
                short_trade = dict((evaluation or {}).get("short_trade") or {})
                if not short_trade:
                    continue
                rows.append(
                    _build_boundary_row(
                        ticker=str(ticker),
                        trade_date=trade_date,
                        report_dir_name=report_dir.name,
                        evaluation=dict(evaluation or {}),
                        price_outcome=_extract_btst_price_outcome(str(ticker), trade_date, price_cache),
                    )
                )

    boundary_rows = [
        row
        for row in rows
        if row.get("root_cause") == "boundary_without_explainability"
        and row.get("bucket") == "missing_all_core_features"
        and row.get("candidate_source") in {"short_trade_boundary", "layer_b_boundary"}
    ]
    source_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in boundary_rows:
        source_groups[str(row.get("candidate_source") or "unknown")].append(row)

    source_comparison_board = []
    for source, group_rows in source_groups.items():
        summary = summarize_boundary_contract_group(group_rows)
        verdict = classify_boundary_contract_verdict(summary)
        source_comparison_board.append(
            {
                "candidate_source": source,
                **summary,
                "contract_verdict": verdict,
                "action": recommend_boundary_contract_action({"contract_verdict": verdict, **summary}),
            }
        )
    source_comparison_board.sort(key=lambda row: (int(row.get("row_count") or 0), str(row.get("candidate_source") or "")), reverse=True)
    governance_recommendation_board = [
        {
            "action": row["action"],
            "focus": row["candidate_source"],
            "reason": f"source {row['candidate_source']} has verdict {row['contract_verdict']}",
        }
        for row in source_comparison_board
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        "row_count": len(rows),
        "boundary_row_count": len(boundary_rows),
        "boundary_rows": boundary_rows,
        "source_comparison_board": source_comparison_board,
        "governance_recommendation_board": governance_recommendation_board,
    }


def render_btst_5d_15pct_boundary_contract_inspection_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST 5D / +15% Boundary Contract Inspection",
        "",
        f"- row_count: {analysis.get('row_count')}",
        f"- boundary_row_count: {analysis.get('boundary_row_count')}",
        "",
        "## source_comparison_board",
    ]
    for row in list(analysis.get("source_comparison_board") or []):
        lines.append(
            f"- {row.get('candidate_source')}: row_count={row.get('row_count')}, decision_counts={row.get('decision_counts')}, metadata_only_rate={row.get('metadata_only_rate')}, top_metadata_keys={row.get('top_metadata_keys')}, core_payload_empty_count={row.get('core_payload_empty_count')}, contract_verdict={row.get('contract_verdict')}, action={row.get('action')}"
        )
    if not list(analysis.get("source_comparison_board") or []):
        lines.append("- none")
    lines.extend(["", "## governance_recommendation_board"])
    for row in list(analysis.get("governance_recommendation_board") or []):
        lines.append(f"- {row.get('action')}: focus={row.get('focus')}, reason={row.get('reason')}")
    if not list(analysis.get("governance_recommendation_board") or []):
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the BTST 5D/+15% boundary contract inspection artifact.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_5d_15pct_boundary_contract_inspection(args.reports_root)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_5d_15pct_boundary_contract_inspection_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
