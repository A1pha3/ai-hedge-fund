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
)
from scripts.btst_missing_core_features_noise_helpers import (
    classify_missing_core_root_cause,
    suggest_missing_core_compression_action,
)
from scripts.btst_report_utils import discover_nested_report_dirs as discover_report_dirs
from scripts.btst_round1_factor_mining_helpers import build_round1_research_row
from scripts.btst_round1_unclassified_split_helpers import classify_unclassified_bucket


REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_5d_15pct_missing_core_features_noise_compression_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_5d_15pct_missing_core_features_noise_compression_latest.md"
CORE_EXPLAINABILITY_KEYS = {
    "breakout_freshness",
    "trend_acceleration",
    "volume_expansion_quality",
    "close_strength",
    "t0_tail_strength",
    "trend_continuation",
    "short_term_reversal",
}


def _build_missing_core_row(*, ticker: str, trade_date: str, report_dir_name: str, evaluation: dict[str, Any], price_outcome: dict[str, Any]) -> dict[str, Any]:
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
    row["has_short_trade"] = bool(short_trade)
    row["explainability_key_count"] = len(explainability)
    row["core_explainability_key_count"] = sum(1 for key in CORE_EXPLAINABILITY_KEYS if key in explainability)
    row["payload_is_empty"] = len(explainability) == 0
    row["root_cause"] = classify_missing_core_root_cause(row)
    row["compression_action"] = suggest_missing_core_compression_action(row)
    return row


def _root_cause_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decision_counts = Counter(str(row.get("decision") or "unknown") for row in rows)
    source_counts = Counter(str(row.get("candidate_source") or "unknown") for row in rows)
    closed_rows = [row for row in rows if row.get("gamma_closed_cycle")]
    hit_rows = [row for row in closed_rows if row.get("future_high_hit_15pct_2_5d") is True]
    return {
        "row_count": len(rows),
        "decision_counts": dict(decision_counts),
        "candidate_source_counts": dict(source_counts),
        "closed_cycle_count": len(closed_rows),
        "hit_rate_15pct": _round_or_none(len(hit_rows) / len(closed_rows)) if closed_rows else None,
        "mean_max_future_high_return_2_5d": _round_or_none(sum(float(row.get("max_future_high_return_2_5d") or 0.0) for row in closed_rows) / len(closed_rows)) if closed_rows else None,
        "payload_empty_count": sum(1 for row in rows if row.get("payload_is_empty")),
        "core_payload_empty_count": sum(1 for row in rows if int(row.get("core_explainability_key_count") or 0) == 0),
        "action": Counter(str(row.get("compression_action") or "hold_until_more_context") for row in rows).most_common(1)[0][0],
    }


def analyze_btst_5d_15pct_missing_core_features_noise_compression(reports_root: str | Path) -> dict[str, Any]:
    resolved_root = Path(reports_root).expanduser().resolve()
    report_dirs = discover_report_dirs([resolved_root], report_name_contains="paper_trading_window")
    price_cache: dict[tuple[str, str], Any] = {}
    rows: list[dict[str, Any]] = []
    for report_dir in report_dirs:
        for snapshot in _iter_selection_snapshots(report_dir) or []:
            trade_date = _normalize_trade_date(snapshot.get("trade_date"))
            for ticker, evaluation in dict(snapshot.get("selection_targets") or {}).items():
                short_trade = dict((evaluation or {}).get("short_trade") or {})
                if not short_trade:
                    continue
                rows.append(
                    _build_missing_core_row(
                        ticker=str(ticker),
                        trade_date=trade_date,
                        report_dir_name=report_dir.name,
                        evaluation=dict(evaluation or {}),
                        price_outcome=_extract_btst_price_outcome(str(ticker), trade_date, price_cache),
                    )
                )

    missing_core_rows = [row for row in rows if row.get("bucket") == "missing_all_core_features"]
    root_cause_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in missing_core_rows:
        root_cause_groups[str(row.get("root_cause") or "unknown_missing_core_contract")].append(row)

    root_cause_board = [{"root_cause": root_cause, **_root_cause_summary(group_rows)} for root_cause, group_rows in root_cause_groups.items()]
    root_cause_board.sort(key=lambda row: (int(row.get("row_count") or 0), str(row.get("root_cause") or "")), reverse=True)
    compression_recommendation_board = [
        {
            "action": row["action"],
            "focus": row["root_cause"],
            "reason": f"root_cause {row['root_cause']} has {row['row_count']} rows",
        }
        for row in root_cause_board
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        "row_count": len(rows),
        "missing_core_row_count": len(missing_core_rows),
        "root_cause_board": root_cause_board,
        "compression_recommendation_board": compression_recommendation_board,
    }


def render_btst_5d_15pct_missing_core_features_noise_compression_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST 5D / +15% Missing-Core-Features Noise Compression",
        "",
        f"- row_count: {analysis.get('row_count')}",
        f"- missing_core_row_count: {analysis.get('missing_core_row_count')}",
        "",
        "## root_cause_board",
    ]
    for row in list(analysis.get("root_cause_board") or []):
        lines.append(
            f"- {row.get('root_cause')}: row_count={row.get('row_count')}, decision_counts={row.get('decision_counts')}, candidate_source_counts={row.get('candidate_source_counts')}, hit_rate_15pct={row.get('hit_rate_15pct')}, mean_max_future_high_return_2_5d={row.get('mean_max_future_high_return_2_5d')}, payload_empty_count={row.get('payload_empty_count')}, action={row.get('action')}"
            f", core_payload_empty_count={row.get('core_payload_empty_count')}"
        )
    if not list(analysis.get("root_cause_board") or []):
        lines.append("- none")
    lines.extend(["", "## compression_recommendation_board"])
    for row in list(analysis.get("compression_recommendation_board") or []):
        lines.append(f"- {row.get('action')}: focus={row.get('focus')}, reason={row.get('reason')}")
    if not list(analysis.get("compression_recommendation_board") or []):
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the BTST 5D/+15% missing-core-features noise-compression artifact.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_5d_15pct_missing_core_features_noise_compression(args.reports_root)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_5d_15pct_missing_core_features_noise_compression_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
