from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_btst_5d_15pct_factor_research_round1 import DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT
from scripts.analyze_btst_5d_15pct_trend_breakout_drilldown import (
    DEFAULT_REPORTS_ROOT,
    _rows_with_gap_le,
    _summary,
    _top_fraction_rows,
)
from scripts.analyze_btst_5d_15pct_trend_top20_gate_diagnostics import (
    DEFAULT_REPORT_NAME_CONTAINS,
    _collect_rows,
    _dedupe_signal_rows,
    _gate_specs,
)
from scripts.btst_analysis_utils import normalize_trade_date as _normalize_trade_date
from scripts.btst_analysis_utils import round_or_none as _round_or_none


DEFAULT_OUTPUT_JSON = Path("data/reports/btst_5d_15pct_trend_gate_oos_validation_latest.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_5d_15pct_trend_gate_oos_validation_latest.md")
DEFAULT_GATE_ID = "trend_acceleration_ge_0_85"
TARGET_HIT_RATE = 0.55
TARGET_MEAN_RETURN = 0.15
MIN_BETA_TRADEABLE_RATE = 0.70


def _gate_predicate(gate_id: str) -> Callable[[dict[str, Any]], bool]:
    if gate_id in {"base", "base_slice", "trend_acceleration_top20_gap"}:
        return lambda row: True
    for candidate_gate_id, predicate in _gate_specs():
        if candidate_gate_id == gate_id:
            return predicate
    if gate_id.startswith("candidate_source_"):
        source = gate_id.removeprefix("candidate_source_")
        return lambda row: str(row.get("candidate_source") or "unknown") == source
    raise ValueError(f"unknown gate_id: {gate_id}")


def _trade_month(row: dict[str, Any]) -> str:
    trade_date = _normalize_trade_date(row.get("trade_date"))
    return str(trade_date)[:7]


def _summary_with_uniqueness(
    unique_rows: list[dict[str, Any]],
    occurrence_rows: list[dict[str, Any]],
    *,
    min_closed_cycle_count: int,
) -> dict[str, Any]:
    summary = _summary(unique_rows, min_closed_cycle_count=min_closed_cycle_count)
    summary.update(
        {
            "unique_ticker_count": len({str(row.get("ticker") or "") for row in unique_rows}),
            "unique_month_count": len({_trade_month(row) for row in unique_rows}),
            "duplicate_occurrence_count": max(0, len(occurrence_rows) - len(unique_rows)),
            "occurrence_row_count": len(occurrence_rows),
        }
    )
    return summary


def _candidate_manifest(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "ticker": row.get("ticker"),
            "trade_date": _normalize_trade_date(row.get("trade_date")),
            "month": _trade_month(row),
            "report_dir_name": row.get("report_dir_name"),
            "decision": row.get("decision"),
            "candidate_source": row.get("candidate_source"),
            "trend_acceleration": row.get("trend_acceleration"),
            "close_strength": row.get("close_strength"),
            "next_open_return": row.get("next_open_return"),
            "future_high_hit_15pct_2_5d": row.get("future_high_hit_15pct_2_5d"),
            "max_future_high_return_2_5d": row.get("max_future_high_return_2_5d"),
        }
        for row in sorted(rows, key=lambda row: (_normalize_trade_date(row.get("trade_date")), str(row.get("ticker") or "")))
    ]


def _meets_thresholds(
    summary: dict[str, Any],
    *,
    min_closed_cycle_count: int,
    target_hit_rate: float,
    target_mean_return: float,
    min_beta_tradeable_rate: float,
) -> bool:
    return (
        int(summary.get("closed_cycle_count") or 0) >= min_closed_cycle_count
        and float(summary.get("hit_rate_15pct") or 0.0) >= target_hit_rate
        and float(summary.get("mean_max_future_high_return_2_5d") or 0.0) >= target_mean_return
        and float(summary.get("beta_tradeable_rate") or 0.0) >= min_beta_tradeable_rate
    )


def _monthly_board(
    unique_rows: list[dict[str, Any]],
    *,
    min_month_closed_cycle_count: int,
    target_hit_rate: float,
    target_mean_return: float,
    min_beta_tradeable_rate: float,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for month in sorted({_trade_month(row) for row in unique_rows}):
        month_rows = [row for row in unique_rows if _trade_month(row) == month]
        summary = _summary(month_rows, min_closed_cycle_count=min_month_closed_cycle_count)
        summary.update(
            {
                "month": month,
                "pass_oos_threshold": _meets_thresholds(
                    summary,
                    min_closed_cycle_count=min_month_closed_cycle_count,
                    target_hit_rate=target_hit_rate,
                    target_mean_return=target_mean_return,
                    min_beta_tradeable_rate=min_beta_tradeable_rate,
                ),
            }
        )
        records.append(summary)
    return records


def _rolling_splits(
    unique_rows: list[dict[str, Any]],
    *,
    min_train_months: int,
    min_month_closed_cycle_count: int,
    target_hit_rate: float,
    target_mean_return: float,
    min_beta_tradeable_rate: float,
) -> list[dict[str, Any]]:
    months = sorted({_trade_month(row) for row in unique_rows})
    splits: list[dict[str, Any]] = []
    for test_index in range(min_train_months, len(months)):
        train_months = months[:test_index]
        test_month = months[test_index]
        train_rows = [row for row in unique_rows if _trade_month(row) in set(train_months)]
        test_rows = [row for row in unique_rows if _trade_month(row) == test_month]
        train_summary = _summary(train_rows, min_closed_cycle_count=min_month_closed_cycle_count)
        test_summary = _summary(test_rows, min_closed_cycle_count=min_month_closed_cycle_count)
        test_summary["pass_oos_threshold"] = _meets_thresholds(
            test_summary,
            min_closed_cycle_count=min_month_closed_cycle_count,
            target_hit_rate=target_hit_rate,
            target_mean_return=target_mean_return,
            min_beta_tradeable_rate=min_beta_tradeable_rate,
        )
        splits.append(
            {
                "train_months": train_months,
                "test_month": test_month,
                "train_summary": train_summary,
                "test_summary": test_summary,
            }
        )
    return splits


def _rollout_decision(
    *,
    candidate_summary: dict[str, Any],
    base_summary: dict[str, Any],
    rolling_splits: list[dict[str, Any]],
    min_closed_cycle_count: int,
    min_oos_test_months: int,
    target_hit_rate: float,
    target_mean_return: float,
    min_beta_tradeable_rate: float,
) -> dict[str, str]:
    candidate_closed = int(candidate_summary.get("closed_cycle_count") or 0)
    stable_oos_count = sum(1 for split in rolling_splits if dict(split.get("test_summary") or {}).get("pass_oos_threshold") is True)
    candidate_pass = _meets_thresholds(
        candidate_summary,
        min_closed_cycle_count=min_closed_cycle_count,
        target_hit_rate=target_hit_rate,
        target_mean_return=target_mean_return,
        min_beta_tradeable_rate=min_beta_tradeable_rate,
    )
    if candidate_pass and stable_oos_count >= min_oos_test_months:
        return {"next_step": "promote_to_shadow_rollout", "reason": "deduped_candidate_and_oos_months_met_thresholds"}
    if candidate_closed < min_closed_cycle_count:
        return {"next_step": "collect_more_unique_samples", "reason": "deduped_candidate_closed_cycle_count_below_minimum"}
    if float(candidate_summary.get("hit_rate_15pct") or 0.0) <= float(base_summary.get("hit_rate_15pct") or 0.0):
        return {"next_step": "hold_gate", "reason": "deduped_candidate_did_not_improve_over_base"}
    return {"next_step": "continue_research_not_rollout", "reason": "deduped_candidate_or_oos_months_below_rollout_threshold"}


def analyze_btst_5d_15pct_trend_gate_oos_validation(
    reports_root: str | Path,
    *,
    gate_id: str = DEFAULT_GATE_ID,
    min_closed_cycle_count: int = 30,
    min_month_closed_cycle_count: int = 1,
    min_train_months: int = 2,
    min_oos_test_months: int = 2,
    boundary_quarantine_artifact: str | Path | None = None,
    local_price_only: bool = False,
    report_name_contains: str = DEFAULT_REPORT_NAME_CONTAINS,
    top_fraction: float = 0.20,
    max_entry_gap: float = 0.03,
    target_hit_rate: float = TARGET_HIT_RATE,
    target_mean_return: float = TARGET_MEAN_RETURN,
    min_beta_tradeable_rate: float = MIN_BETA_TRADEABLE_RATE,
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
    base_occurrence_rows = _rows_with_gap_le(top_rows, max_entry_gap)
    base_unique_rows = _dedupe_signal_rows(base_occurrence_rows)
    predicate = _gate_predicate(gate_id)
    candidate_occurrence_rows = [row for row in base_occurrence_rows if predicate(row)]
    candidate_unique_rows = _dedupe_signal_rows(candidate_occurrence_rows)

    base_summary = _summary_with_uniqueness(base_unique_rows, base_occurrence_rows, min_closed_cycle_count=min_closed_cycle_count)
    candidate_summary = _summary_with_uniqueness(candidate_unique_rows, candidate_occurrence_rows, min_closed_cycle_count=min_closed_cycle_count)
    candidate_summary.update(
        {
            "gate_id": gate_id,
            "hit_rate_uplift_vs_base_unique": _round_or_none(float(candidate_summary.get("hit_rate_15pct") or 0.0) - float(base_summary.get("hit_rate_15pct") or 0.0))
            if candidate_summary.get("hit_rate_15pct") is not None and base_summary.get("hit_rate_15pct") is not None
            else None,
            "mean_return_uplift_vs_base_unique": _round_or_none(float(candidate_summary.get("mean_max_future_high_return_2_5d") or 0.0) - float(base_summary.get("mean_max_future_high_return_2_5d") or 0.0))
            if candidate_summary.get("mean_max_future_high_return_2_5d") is not None and base_summary.get("mean_max_future_high_return_2_5d") is not None
            else None,
        }
    )
    monthly = _monthly_board(
        candidate_unique_rows,
        min_month_closed_cycle_count=min_month_closed_cycle_count,
        target_hit_rate=target_hit_rate,
        target_mean_return=target_mean_return,
        min_beta_tradeable_rate=min_beta_tradeable_rate,
    )
    rolling = _rolling_splits(
        candidate_unique_rows,
        min_train_months=min_train_months,
        min_month_closed_cycle_count=min_month_closed_cycle_count,
        target_hit_rate=target_hit_rate,
        target_mean_return=target_mean_return,
        min_beta_tradeable_rate=min_beta_tradeable_rate,
    )
    stable_oos_count = sum(1 for split in rolling if dict(split.get("test_summary") or {}).get("pass_oos_threshold") is True)
    rollout_decision = _rollout_decision(
        candidate_summary=candidate_summary,
        base_summary=base_summary,
        rolling_splits=rolling,
        min_closed_cycle_count=min_closed_cycle_count,
        min_oos_test_months=min_oos_test_months,
        target_hit_rate=target_hit_rate,
        target_mean_return=target_mean_return,
        min_beta_tradeable_rate=min_beta_tradeable_rate,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        "report_name_contains": report_name_contains,
        "gate_id": gate_id,
        "top_fraction": top_fraction,
        "max_entry_gap": max_entry_gap,
        "target_hit_rate": target_hit_rate,
        "target_mean_return": target_mean_return,
        "min_beta_tradeable_rate": min_beta_tradeable_rate,
        "row_count": len(rows),
        "trend_row_count": len(trend_rows),
        "base_occurrence_count": len(base_occurrence_rows),
        "candidate_occurrence_count": len(candidate_occurrence_rows),
        "base_unique_summary": base_summary,
        "candidate_unique_summary": candidate_summary,
        "monthly_board": monthly,
        "rolling_splits": rolling,
        "stable_oos_test_month_count": stable_oos_count,
        "candidate_manifest": _candidate_manifest(candidate_unique_rows),
        "excluded_event_prototype_counts": dict(sorted(Counter(str(row.get("event_prototype") or "unclassified") for row in rows if row.get("event_prototype") != "trend_continuation").items())),
        "rollout_decision": rollout_decision,
    }


def render_btst_5d_15pct_trend_gate_oos_validation_markdown(validation: dict[str, Any]) -> str:
    lines = ["# BTST 5D / 15% Trend Gate OOS Validation", ""]
    candidate = dict(validation.get("candidate_unique_summary") or {})
    base = dict(validation.get("base_unique_summary") or {})
    decision = dict(validation.get("rollout_decision") or {})
    lines.append(f"- gate_id: {validation.get('gate_id')}")
    lines.append(f"- row_count: {validation.get('row_count')}")
    lines.append(f"- trend_row_count: {validation.get('trend_row_count')}")
    lines.append(f"- base_unique_closed: {base.get('closed_cycle_count')}")
    lines.append(f"- base_unique_hit_rate_15pct: {base.get('hit_rate_15pct')}")
    lines.append(f"- candidate_unique_closed: {candidate.get('closed_cycle_count')}")
    lines.append(f"- candidate_unique_hit_rate_15pct: {candidate.get('hit_rate_15pct')}")
    lines.append(f"- candidate_unique_mean_max_return: {candidate.get('mean_max_future_high_return_2_5d')}")
    lines.append(f"- duplicate_occurrence_count: {candidate.get('duplicate_occurrence_count')}")
    lines.append(f"- stable_oos_test_month_count: {validation.get('stable_oos_test_month_count')}")
    lines.append("")
    lines.append("## Rollout Decision")
    lines.append(f"- next_step: {decision.get('next_step')}")
    lines.append(f"- reason: {decision.get('reason')}")
    lines.append("")
    lines.append("## Monthly Board")
    for row in list(validation.get("monthly_board") or []):
        lines.append(
            f"- {row.get('month')}: closed={row.get('closed_cycle_count')}, hit_rate_15pct={row.get('hit_rate_15pct')}, "
            f"mean_max_return={row.get('mean_max_future_high_return_2_5d')}, beta_tradeable_rate={row.get('beta_tradeable_rate')}, "
            f"pass_oos_threshold={row.get('pass_oos_threshold')}"
        )
    lines.append("")
    lines.append("## Rolling Splits")
    for row in list(validation.get("rolling_splits") or []):
        test_summary = dict(row.get("test_summary") or {})
        lines.append(
            f"- train={','.join(list(row.get('train_months') or []))} -> test={row.get('test_month')}: "
            f"test_closed={test_summary.get('closed_cycle_count')}, test_hit_rate_15pct={test_summary.get('hit_rate_15pct')}, "
            f"test_pass={test_summary.get('pass_oos_threshold')}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a deduped BTST trend gate with monthly and rolling OOS splits.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument("--gate-id", default=DEFAULT_GATE_ID)
    parser.add_argument("--min-closed-cycle-count", type=int, default=30)
    parser.add_argument("--min-month-closed-cycle-count", type=int, default=1)
    parser.add_argument("--min-train-months", type=int, default=2)
    parser.add_argument("--min-oos-test-months", type=int, default=2)
    parser.add_argument("--boundary-quarantine-artifact", default=str(DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT))
    parser.add_argument("--local-price-only", action="store_true")
    parser.add_argument("--report-name-contains", default=DEFAULT_REPORT_NAME_CONTAINS)
    parser.add_argument("--top-fraction", type=float, default=0.20)
    parser.add_argument("--max-entry-gap", type=float, default=0.03)
    parser.add_argument("--target-hit-rate", type=float, default=TARGET_HIT_RATE)
    parser.add_argument("--target-mean-return", type=float, default=TARGET_MEAN_RETURN)
    parser.add_argument("--min-beta-tradeable-rate", type=float, default=MIN_BETA_TRADEABLE_RATE)
    args = parser.parse_args()

    validation = analyze_btst_5d_15pct_trend_gate_oos_validation(
        args.reports_root,
        gate_id=args.gate_id,
        min_closed_cycle_count=args.min_closed_cycle_count,
        min_month_closed_cycle_count=args.min_month_closed_cycle_count,
        min_train_months=args.min_train_months,
        min_oos_test_months=args.min_oos_test_months,
        boundary_quarantine_artifact=args.boundary_quarantine_artifact,
        local_price_only=args.local_price_only,
        report_name_contains=args.report_name_contains,
        top_fraction=args.top_fraction,
        max_entry_gap=args.max_entry_gap,
        target_hit_rate=args.target_hit_rate,
        target_mean_return=args.target_mean_return,
        min_beta_tradeable_rate=args.min_beta_tradeable_rate,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_5d_15pct_trend_gate_oos_validation_markdown(validation), encoding="utf-8")
    print(
        json.dumps(
            {
                "gate_id": validation.get("gate_id"),
                "candidate_unique_summary": validation.get("candidate_unique_summary"),
                "stable_oos_test_month_count": validation.get("stable_oos_test_month_count"),
                "rollout_decision": validation.get("rollout_decision"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
