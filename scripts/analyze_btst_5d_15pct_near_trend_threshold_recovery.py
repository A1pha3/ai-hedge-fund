from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.btst_analysis_utils import (
    extract_btst_price_outcome as _extract_btst_price_outcome,
    iter_selection_snapshots as _iter_selection_snapshots,
    normalize_trade_date as _normalize_trade_date,
    round_or_none as _round_or_none,
)
from scripts.btst_near_trend_threshold_recovery_helpers import (
    build_near_trend_recovery_candidate,
    summarize_near_trend_recovery_governance_verdict,
)
from scripts.btst_report_utils import discover_nested_report_dirs as discover_report_dirs
from scripts.btst_round1_factor_mining_helpers import build_round1_research_row
from scripts.btst_round1_unclassified_split_helpers import classify_unclassified_bucket


REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_5d_15pct_near_trend_threshold_recovery_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_5d_15pct_near_trend_threshold_recovery_latest.md"


def _cohort_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closed_rows = [row for row in rows if row.get("gamma_closed_cycle")]
    hit_rows = [row for row in closed_rows if row.get("future_high_hit_15pct_2_5d") is True]
    mean_max_return = _round_or_none(sum(float(row.get("max_future_high_return_2_5d") or 0.0) for row in closed_rows) / len(closed_rows)) if closed_rows else None
    beta_tradeable_rate = _round_or_none(sum(1 for row in rows if row.get("beta_tradeable")) / len(rows)) if rows else None
    return {
        "row_count": len(rows),
        "closed_cycle_count": len(closed_rows),
        "hit_rate_15pct": _round_or_none(len(hit_rows) / len(closed_rows)) if closed_rows else None,
        "mean_max_future_high_return_2_5d": mean_max_return,
        "beta_tradeable_rate": beta_tradeable_rate,
        "tickers": [str(row.get("ticker") or "") for row in rows],
    }


def analyze_btst_5d_15pct_near_trend_threshold_recovery(reports_root: str | Path, *, min_recovered_row_count: int = 3) -> dict[str, Any]:
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
                row = build_round1_research_row(
                    ticker=str(ticker),
                    trade_date=trade_date,
                    report_dir_name=report_dir.name,
                    evaluation=dict(evaluation or {}),
                    price_outcome=_extract_btst_price_outcome(str(ticker), trade_date, price_cache),
                )
                row["bucket"] = classify_unclassified_bucket(row) if row.get("event_prototype") == "unclassified" else None
                rows.append(build_near_trend_recovery_candidate(row))

    recovered_rows = [row for row in rows if row.get("is_recovery_candidate")]
    unrecovered_bucket_rows = [row for row in rows if row.get("bucket") == "near_trend_threshold" and not row.get("is_recovery_candidate")]
    trend_baseline_rows = [row for row in rows if row.get("event_prototype") == "trend_continuation"]

    recovered_summary = _cohort_summary(recovered_rows)
    unrecovered_summary = _cohort_summary(unrecovered_bucket_rows)
    trend_summary = _cohort_summary(trend_baseline_rows)
    recovered_row_count_for_verdict = int(recovered_summary.get("row_count") or 0) if int(recovered_summary.get("row_count") or 0) >= min_recovered_row_count else 0
    governance_verdict = summarize_near_trend_recovery_governance_verdict(
        recovered_hit_rate=recovered_summary.get("hit_rate_15pct"),
        recovered_mean_return=recovered_summary.get("mean_max_future_high_return_2_5d"),
        recovered_tradeable_rate=recovered_summary.get("beta_tradeable_rate"),
        recovered_row_count=recovered_row_count_for_verdict,
        minimum_required_row_count=min_recovered_row_count,
        baseline_hit_rate=unrecovered_summary.get("hit_rate_15pct"),
        baseline_mean_return=unrecovered_summary.get("mean_max_future_high_return_2_5d"),
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        "row_count": len(rows),
        "recovered_cohort": recovered_summary,
        "unrecovered_bucket_baseline": unrecovered_summary,
        "trend_baseline": trend_summary,
        "governance_verdict": governance_verdict,
    }


def render_btst_5d_15pct_near_trend_threshold_recovery_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST 5D / +15% Near-Trend-Threshold Recovery",
        "",
        f"- row_count: {analysis.get('row_count')}",
        f"- governance_verdict: {analysis.get('governance_verdict')}",
        "",
        "## Cohorts",
    ]
    for label in ("recovered_cohort", "unrecovered_bucket_baseline", "trend_baseline"):
        row = dict(analysis.get(label) or {})
        lines.append(
            f"- {label}: row_count={row.get('row_count')}, closed_cycle_count={row.get('closed_cycle_count')}, hit_rate_15pct={row.get('hit_rate_15pct')}, mean_max_future_high_return_2_5d={row.get('mean_max_future_high_return_2_5d')}, beta_tradeable_rate={row.get('beta_tradeable_rate')}, tickers={row.get('tickers')}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the BTST 5D/+15% near-trend-threshold recovery validation artifact.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument("--min-recovered-row-count", type=int, default=3)
    args = parser.parse_args()

    analysis = analyze_btst_5d_15pct_near_trend_threshold_recovery(args.reports_root, min_recovered_row_count=args.min_recovered_row_count)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_5d_15pct_near_trend_threshold_recovery_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
