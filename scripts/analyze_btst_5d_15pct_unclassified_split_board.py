from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.btst_analysis_utils import (
    extract_btst_price_outcome as _extract_btst_price_outcome,
    iter_selection_snapshots as _iter_selection_snapshots,
    normalize_trade_date as _normalize_trade_date,
    round_or_none as _round_or_none,
    safe_float as _safe_float,
)
from scripts.btst_report_utils import discover_nested_report_dirs as discover_report_dirs
from scripts.btst_round1_factor_mining_helpers import build_round1_research_row
from scripts.btst_round1_unclassified_split_helpers import (
    classify_unclassified_bucket,
    summarize_unclassified_recoverability,
)


REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_5d_15pct_unclassified_split_board_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_5d_15pct_unclassified_split_board_latest.md"


def _bucket_score(row: dict[str, Any]) -> tuple[float, float, int, str]:
    return (
        1.0 if row.get("recoverability_verdict") == "recover_threshold_near_miss" else 0.0,
        float(row.get("hit_rate_15pct") or -999.0),
        int(row.get("row_count") or 0),
        str(row.get("bucket") or ""),
    )


def analyze_btst_5d_15pct_unclassified_split_board(reports_root: str | Path) -> dict[str, Any]:
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
                row = build_round1_research_row(
                    ticker=str(ticker),
                    trade_date=trade_date,
                    report_dir_name=report_dir.name,
                    evaluation=dict(evaluation or {}),
                    price_outcome=_extract_btst_price_outcome(str(ticker), trade_date, price_cache),
                )
                rows.append(row)

    unclassified_rows = [row for row in rows if row.get("event_prototype") == "unclassified"]
    for row in unclassified_rows:
        row["bucket"] = classify_unclassified_bucket(row)
        row["recoverability_verdict"] = summarize_unclassified_recoverability(row)

    bucket_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in unclassified_rows:
        bucket_groups[str(row.get("bucket") or "other_unclassified")].append(row)

    bucket_board: list[dict[str, Any]] = []
    for bucket, group_rows in bucket_groups.items():
        decision_counts = Counter(str(row.get("decision") or "unknown") for row in group_rows)
        source_counts = Counter(str(row.get("candidate_source") or "unknown") for row in group_rows)
        verdict = Counter(str(row.get("recoverability_verdict") or "ignore_noise") for row in group_rows).most_common(1)[0][0]
        hit_rate = _round_or_none(sum(1 for row in group_rows if row.get("future_high_hit_15pct_2_5d") is True) / len(group_rows)) if group_rows else None
        mean_max_return = _round_or_none(
            sum(value for value in (_safe_float(row.get("max_future_high_return_2_5d")) for row in group_rows) if value is not None)
            / max(1, sum(1 for value in (_safe_float(row.get("max_future_high_return_2_5d")) for row in group_rows) if value is not None))
        )
        bucket_board.append(
            {
                "bucket": bucket,
                "row_count": len(group_rows),
                "decision_counts": dict(decision_counts),
                "candidate_source_counts": dict(source_counts),
                "hit_rate_15pct": hit_rate,
                "mean_max_future_high_return_2_5d": mean_max_return,
                "recoverability_verdict": verdict,
            }
        )
    bucket_board.sort(key=_bucket_score, reverse=True)

    recommendation_board = [
        {
            "action": row["recoverability_verdict"],
            "focus": row["bucket"],
            "reason": f"bucket {row['bucket']} has {row['row_count']} rows",
        }
        for row in bucket_board
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        "row_count": len(rows),
        "unclassified_row_count": len(unclassified_rows),
        "bucket_board": bucket_board,
        "recommendation_board": recommendation_board,
    }


def render_btst_5d_15pct_unclassified_split_board_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST 5D / +15% Unclassified Split Board",
        "",
        f"- row_count: {analysis.get('row_count')}",
        f"- unclassified_row_count: {analysis.get('unclassified_row_count')}",
        "",
        "## Bucket Board",
    ]
    for row in list(analysis.get("bucket_board") or []):
        lines.append(
            f"- {row.get('bucket')}: row_count={row.get('row_count')}, decision_counts={row.get('decision_counts')}, candidate_source_counts={row.get('candidate_source_counts')}, hit_rate_15pct={row.get('hit_rate_15pct')}, mean_max_future_high_return_2_5d={row.get('mean_max_future_high_return_2_5d')}, recoverability_verdict={row.get('recoverability_verdict')}"
        )
    if not list(analysis.get("bucket_board") or []):
        lines.append("- none")
    lines.extend(["", "## Recommendation Board"])
    for row in list(analysis.get("recommendation_board") or []):
        lines.append(f"- {row.get('action')}: focus={row.get('focus')}, reason={row.get('reason')}")
    if not list(analysis.get("recommendation_board") or []):
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the BTST 5D/+15% unclassified split board.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_5d_15pct_unclassified_split_board(args.reports_root)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_5d_15pct_unclassified_split_board_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
