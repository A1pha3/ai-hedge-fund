from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_btst_5d_15pct_factor_research_round1 import DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT
from scripts.analyze_btst_5d_15pct_trend_breakout_drilldown import (
    DEFAULT_REPORTS_ROOT,
    _summary,
    _top_fraction_rows,
)
from scripts.analyze_btst_5d_15pct_trend_gate_oos_validation import (
    TARGET_HIT_RATE,
    TARGET_MEAN_RETURN,
    _gate_predicate,
)
from scripts.analyze_btst_5d_15pct_trend_top20_gate_diagnostics import (
    DEFAULT_REPORT_NAME_CONTAINS,
    _collect_rows,
    _dedupe_signal_rows,
)
from scripts.btst_analysis_utils import normalize_trade_date as _normalize_trade_date
from scripts.btst_analysis_utils import safe_float as _safe_float


DEFAULT_OUTPUT_JSON = Path("data/reports/btst_5d_15pct_trend_gate_sample_intake_board_latest.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_5d_15pct_trend_gate_sample_intake_board_latest.md")
STATUS_ORDER = (
    "closed_hit",
    "closed_miss",
    "pending_cycle",
    "missing_price",
    "missing_execution_price",
    "non_executable_gap",
)


def _sample_status(row: dict[str, Any], *, max_entry_gap: float) -> str:
    if row.get("local_price_missing_reason"):
        return "missing_price"
    next_open_return = _safe_float(row.get("next_open_return"))
    if next_open_return is None:
        return "missing_execution_price"
    if next_open_return > max_entry_gap:
        return "non_executable_gap"
    if row.get("gamma_closed_cycle") is not True:
        return "pending_cycle"
    if row.get("future_high_hit_15pct_2_5d") is True:
        return "closed_hit"
    return "closed_miss"


def _status_counts(rows: list[dict[str, Any]], *, max_entry_gap: float) -> dict[str, int]:
    counts = Counter(_sample_status(row, max_entry_gap=max_entry_gap) for row in rows)
    return {status: counts[status] for status in STATUS_ORDER if counts[status]}


def _record(row: dict[str, Any], *, max_entry_gap: float) -> dict[str, Any]:
    return {
        "ticker": row.get("ticker"),
        "trade_date": _normalize_trade_date(row.get("trade_date")),
        "month": str(_normalize_trade_date(row.get("trade_date")))[:7],
        "report_dir_name": row.get("report_dir_name"),
        "sample_status": _sample_status(row, max_entry_gap=max_entry_gap),
        "decision": row.get("decision"),
        "candidate_source": row.get("candidate_source"),
        "trend_acceleration": row.get("trend_acceleration"),
        "close_strength": row.get("close_strength"),
        "next_open_return": row.get("next_open_return"),
        "local_price_missing_reason": row.get("local_price_missing_reason"),
        "future_high_hit_15pct_2_5d": row.get("future_high_hit_15pct_2_5d"),
        "max_future_high_return_2_5d": row.get("max_future_high_return_2_5d"),
    }


def _intake_decision(
    *,
    status_counts: dict[str, int],
    closed_unique_summary: dict[str, Any],
    sample_gap_to_min_closed: int,
    target_hit_rate: float,
    target_mean_return: float,
) -> dict[str, str]:
    if int(status_counts.get("missing_price") or 0) + int(status_counts.get("missing_execution_price") or 0) > 0:
        return {"next_step": "backfill_missing_prices", "reason": "repairable_price_gaps_exist_inside_best_gate"}
    if sample_gap_to_min_closed > 0:
        return {"next_step": "collect_new_trade_dates", "reason": "deduped_closed_cycle_count_below_minimum_after_repairs"}
    hit_rate = float(closed_unique_summary.get("hit_rate_15pct") or 0.0)
    mean_return = float(closed_unique_summary.get("mean_max_future_high_return_2_5d") or 0.0)
    if hit_rate >= target_hit_rate and mean_return >= target_mean_return:
        return {"next_step": "run_oos_rollout_validation", "reason": "sample_count_and_research_thresholds_met"}
    return {"next_step": "refine_or_reject_gate", "reason": "sample_count_met_but_research_thresholds_not_met"}


def analyze_btst_5d_15pct_trend_gate_sample_intake_board(
    reports_root: str | Path,
    *,
    gate_id: str = "catalyst_theme_close_strength_lt_0_90",
    min_closed_cycle_count: int = 30,
    boundary_quarantine_artifact: str | Path | None = None,
    local_price_only: bool = True,
    report_name_contains: str = DEFAULT_REPORT_NAME_CONTAINS,
    top_fraction: float = 0.20,
    max_entry_gap: float = 0.03,
    target_hit_rate: float = TARGET_HIT_RATE,
    target_mean_return: float = TARGET_MEAN_RETURN,
) -> dict[str, Any]:
    resolved_root = Path(reports_root).expanduser().resolve()
    rows = _collect_rows(
        resolved_root,
        boundary_quarantine_artifact=boundary_quarantine_artifact,
        local_price_only=local_price_only,
        report_name_contains=report_name_contains,
    )
    trend_rows = [row for row in rows if row.get("event_prototype") == "trend_continuation"]
    top_rows = _top_fraction_rows(trend_rows, "trend_acceleration", top_fraction)
    predicate = _gate_predicate(gate_id)
    pre_execution_rows = [row for row in top_rows if predicate(row)]
    unique_rows = _dedupe_signal_rows(pre_execution_rows)
    counts = _status_counts(unique_rows, max_entry_gap=max_entry_gap)
    executable_rows = [
        row
        for row in unique_rows
        if _sample_status(row, max_entry_gap=max_entry_gap) in {"closed_hit", "closed_miss", "pending_cycle"}
    ]
    closed_rows = [
        row
        for row in unique_rows
        if _sample_status(row, max_entry_gap=max_entry_gap) in {"closed_hit", "closed_miss"}
    ]
    closed_summary = _summary(executable_rows, min_closed_cycle_count=min_closed_cycle_count)
    sample_gap = max(0, min_closed_cycle_count - len(closed_rows))
    records = sorted(
        [_record(row, max_entry_gap=max_entry_gap) for row in unique_rows],
        key=lambda row: (str(row.get("sample_status") or ""), str(row.get("trade_date") or ""), str(row.get("ticker") or "")),
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        "report_name_contains": report_name_contains,
        "gate_id": gate_id,
        "top_fraction": top_fraction,
        "max_entry_gap": max_entry_gap,
        "row_count": len(rows),
        "trend_row_count": len(trend_rows),
        "pre_execution_occurrence_count": len(pre_execution_rows),
        "pre_execution_unique_count": len(unique_rows),
        "duplicate_occurrence_count": max(0, len(pre_execution_rows) - len(unique_rows)),
        "executable_unique_count": len(executable_rows),
        "closed_unique_count": len(closed_rows),
        "sample_gap_to_min_closed": sample_gap,
        "status_counts": counts,
        "closed_unique_summary": closed_summary,
        "intake_decision": _intake_decision(
            status_counts=counts,
            closed_unique_summary=closed_summary,
            sample_gap_to_min_closed=sample_gap,
            target_hit_rate=target_hit_rate,
            target_mean_return=target_mean_return,
        ),
        "candidate_records": records,
    }


def render_btst_5d_15pct_trend_gate_sample_intake_board_markdown(board: dict[str, Any], *, row_limit: int = 120) -> str:
    lines = ["# BTST 5D / 15% Trend Gate Sample Intake Board", ""]
    summary = dict(board.get("closed_unique_summary") or {})
    decision = dict(board.get("intake_decision") or {})
    lines.append(f"- gate_id: {board.get('gate_id')}")
    lines.append(f"- row_count: {board.get('row_count')}")
    lines.append(f"- trend_row_count: {board.get('trend_row_count')}")
    lines.append(f"- pre_execution_unique_count: {board.get('pre_execution_unique_count')}")
    lines.append(f"- duplicate_occurrence_count: {board.get('duplicate_occurrence_count')}")
    lines.append(f"- executable_unique_count: {board.get('executable_unique_count')}")
    lines.append(f"- closed_unique_count: {board.get('closed_unique_count')}")
    lines.append(f"- sample_gap_to_min_closed: {board.get('sample_gap_to_min_closed')}")
    lines.append(f"- closed_hit_rate_15pct: {summary.get('hit_rate_15pct')}")
    lines.append(f"- closed_mean_max_return: {summary.get('mean_max_future_high_return_2_5d')}")
    lines.append(f"- intake_decision: {decision.get('next_step')}")
    lines.append("")
    lines.append("## Sample Status Board")
    for status, count in dict(board.get("status_counts") or {}).items():
        lines.append(f"- {status}: {count}")
    lines.append("")
    lines.append("## Candidate Records")
    for row in list(board.get("candidate_records") or [])[:row_limit]:
        lines.append(
            f"- {row.get('sample_status')} {row.get('ticker')} {row.get('trade_date')} "
            f"next_open_return={row.get('next_open_return')} hit={row.get('future_high_hit_15pct_2_5d')} "
            f"max_return={row.get('max_future_high_return_2_5d')} reason={row.get('local_price_missing_reason')}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Decompose sample-intake status for the best BTST trend gate.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument("--gate-id", default="catalyst_theme_close_strength_lt_0_90")
    parser.add_argument("--min-closed-cycle-count", type=int, default=30)
    parser.add_argument("--boundary-quarantine-artifact", default=str(DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT))
    parser.add_argument("--local-price-only", action="store_true")
    parser.add_argument("--report-name-contains", default=DEFAULT_REPORT_NAME_CONTAINS)
    parser.add_argument("--top-fraction", type=float, default=0.20)
    parser.add_argument("--max-entry-gap", type=float, default=0.03)
    parser.add_argument("--target-hit-rate", type=float, default=TARGET_HIT_RATE)
    parser.add_argument("--target-mean-return", type=float, default=TARGET_MEAN_RETURN)
    parser.add_argument("--markdown-row-limit", type=int, default=120)
    args = parser.parse_args()

    board = analyze_btst_5d_15pct_trend_gate_sample_intake_board(
        args.reports_root,
        gate_id=args.gate_id,
        min_closed_cycle_count=args.min_closed_cycle_count,
        boundary_quarantine_artifact=args.boundary_quarantine_artifact,
        local_price_only=args.local_price_only,
        report_name_contains=args.report_name_contains,
        top_fraction=args.top_fraction,
        max_entry_gap=args.max_entry_gap,
        target_hit_rate=args.target_hit_rate,
        target_mean_return=args.target_mean_return,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(board, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_5d_15pct_trend_gate_sample_intake_board_markdown(board, row_limit=args.markdown_row_limit), encoding="utf-8")
    print(
        json.dumps(
            {
                "gate_id": board.get("gate_id"),
                "pre_execution_unique_count": board.get("pre_execution_unique_count"),
                "closed_unique_count": board.get("closed_unique_count"),
                "sample_gap_to_min_closed": board.get("sample_gap_to_min_closed"),
                "status_counts": board.get("status_counts"),
                "intake_decision": board.get("intake_decision"),
                "output_json": str(output_json),
                "output_md": str(output_md),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
