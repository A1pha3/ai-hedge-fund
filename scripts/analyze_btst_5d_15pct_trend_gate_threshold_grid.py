from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_btst_5d_15pct_factor_research_round1 import DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT
from scripts.analyze_btst_5d_15pct_trend_breakout_drilldown import (
    DEFAULT_REPORTS_ROOT,
    _rows_with_gap_le,
    _top_fraction_rows,
)
from scripts.analyze_btst_5d_15pct_trend_gate_oos_validation import (
    MIN_BETA_TRADEABLE_RATE,
    TARGET_HIT_RATE,
    TARGET_MEAN_RETURN,
    _gate_predicate,
    _monthly_board,
    _rollout_decision,
    _rolling_splits,
    _summary_with_uniqueness,
)
from scripts.analyze_btst_5d_15pct_trend_top20_gate_diagnostics import (
    DEFAULT_REPORT_NAME_CONTAINS,
    _collect_rows,
    _dedupe_signal_rows,
)
from scripts.btst_analysis_utils import round_or_none as _round_or_none


DEFAULT_OUTPUT_JSON = Path("data/reports/btst_5d_15pct_trend_gate_threshold_grid_latest.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_5d_15pct_trend_gate_threshold_grid_latest.md")
DEFAULT_CLOSE_STRENGTH_THRESHOLDS = (0.88, 0.90, 0.92, 0.95)
DEFAULT_TOP_FRACTIONS = (0.20, 0.30)
DEFAULT_MAX_ENTRY_GAP = 0.03


def _gate_id_for_close_threshold(threshold: float) -> str:
    return f"catalyst_theme_close_strength_lt_{threshold:.2f}".replace(".", "_")


def _candidate_quality_sort_key(row: dict[str, Any]) -> tuple[float, float, int, float]:
    return (
        float(row.get("candidate_unique_hit_rate_15pct") or -1.0),
        float(row.get("candidate_unique_mean_max_return") or -1.0),
        int(row.get("candidate_unique_closed") or 0),
        -float(row.get("close_strength_threshold") or 999.0),
    )


def _grid_row(
    *,
    gate_id: str,
    threshold: float,
    top_fraction: float,
    base_occurrence_rows: list[dict[str, Any]],
    min_closed_cycle_count: int,
    min_month_closed_cycle_count: int,
    min_train_months: int,
    min_oos_test_months: int,
    target_hit_rate: float,
    target_mean_return: float,
    min_beta_tradeable_rate: float,
) -> dict[str, Any]:
    base_unique_rows = _dedupe_signal_rows(base_occurrence_rows)
    base_summary = _summary_with_uniqueness(base_unique_rows, base_occurrence_rows, min_closed_cycle_count=min_closed_cycle_count)
    predicate = _gate_predicate(gate_id)
    candidate_occurrence_rows = [row for row in base_occurrence_rows if predicate(row)]
    candidate_unique_rows = _dedupe_signal_rows(candidate_occurrence_rows)
    candidate_summary = _summary_with_uniqueness(candidate_unique_rows, candidate_occurrence_rows, min_closed_cycle_count=min_closed_cycle_count)
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
    decision = _rollout_decision(
        candidate_summary=candidate_summary,
        base_summary=base_summary,
        rolling_splits=rolling,
        min_closed_cycle_count=min_closed_cycle_count,
        min_oos_test_months=min_oos_test_months,
        target_hit_rate=target_hit_rate,
        target_mean_return=target_mean_return,
        min_beta_tradeable_rate=min_beta_tradeable_rate,
    )
    candidate_hit_rate = candidate_summary.get("hit_rate_15pct")
    base_hit_rate = base_summary.get("hit_rate_15pct")
    candidate_mean_return = candidate_summary.get("mean_max_future_high_return_2_5d")
    base_mean_return = base_summary.get("mean_max_future_high_return_2_5d")
    closed_count = int(candidate_summary.get("closed_cycle_count") or 0)
    return {
        "gate_id": gate_id,
        "close_strength_threshold": threshold,
        "top_fraction": top_fraction,
        "base_unique_closed": base_summary.get("closed_cycle_count"),
        "base_unique_hit_rate_15pct": base_hit_rate,
        "base_unique_mean_max_return": base_mean_return,
        "candidate_occurrence_count": len(candidate_occurrence_rows),
        "candidate_unique_count": candidate_summary.get("row_count"),
        "candidate_unique_closed": candidate_summary.get("closed_cycle_count"),
        "candidate_unique_hit_rate_15pct": candidate_hit_rate,
        "candidate_unique_mean_max_return": candidate_mean_return,
        "candidate_unique_beta_tradeable_rate": candidate_summary.get("beta_tradeable_rate"),
        "candidate_unique_month_count": candidate_summary.get("unique_month_count"),
        "candidate_unique_ticker_count": candidate_summary.get("unique_ticker_count"),
        "duplicate_occurrence_count": candidate_summary.get("duplicate_occurrence_count"),
        "sample_gap_to_min_closed": max(0, min_closed_cycle_count - closed_count),
        "hit_rate_uplift_vs_base_unique": _round_or_none(float(candidate_hit_rate or 0.0) - float(base_hit_rate or 0.0)) if candidate_hit_rate is not None and base_hit_rate is not None else None,
        "mean_return_uplift_vs_base_unique": _round_or_none(float(candidate_mean_return or 0.0) - float(base_mean_return or 0.0)) if candidate_mean_return is not None and base_mean_return is not None else None,
        "stable_oos_test_month_count": stable_oos_count,
        "monthly_board": monthly,
        "rollout_decision": decision,
        "dilution_flag": False,
    }


def _attach_dilution_flags(grid_board: list[dict[str, Any]], *, dilution_hit_rate_drop: float) -> None:
    grouped: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for row in grid_board:
        grouped[float(row.get("top_fraction") or 0.0)].append(row)

    for rows in grouped.values():
        prior_best_hit_rate: float | None = None
        for row in sorted(rows, key=lambda item: float(item.get("close_strength_threshold") or 0.0)):
            hit_rate = row.get("candidate_unique_hit_rate_15pct")
            if hit_rate is not None and prior_best_hit_rate is not None:
                row["dilution_flag"] = (prior_best_hit_rate - float(hit_rate)) >= dilution_hit_rate_drop
            if hit_rate is not None:
                prior_best_hit_rate = max(prior_best_hit_rate if prior_best_hit_rate is not None else float(hit_rate), float(hit_rate))


def _grid_decision(
    grid_board: list[dict[str, Any]],
    best_candidate: dict[str, Any] | None,
    *,
    research_hit_rate_floor: float,
    target_mean_return: float,
) -> dict[str, str]:
    if any(dict(row.get("rollout_decision") or {}).get("next_step") == "promote_to_shadow_rollout" for row in grid_board):
        return {"next_step": "promote_best_gate_to_shadow_review", "reason": "at_least_one_grid_gate_met_rollout_thresholds"}
    if not best_candidate:
        return {"next_step": "hold_grid", "reason": "no_candidate_rows"}
    best_hit_rate = float(best_candidate.get("candidate_unique_hit_rate_15pct") or 0.0)
    best_mean_return = float(best_candidate.get("candidate_unique_mean_max_return") or 0.0)
    if best_hit_rate >= research_hit_rate_floor and best_mean_return >= target_mean_return:
        return {"next_step": "keep_narrow_gate_collect_samples", "reason": "best_gate_keeps_research_quality_but_needs_more_oos_evidence"}
    if any(row.get("dilution_flag") for row in grid_board):
        return {"next_step": "reject_wide_threshold_expansion", "reason": "wider_thresholds_diluted_deduped_hit_rate"}
    return {"next_step": "hold_grid", "reason": "no_grid_gate_preserved_research_quality"}


def analyze_btst_5d_15pct_trend_gate_threshold_grid(
    reports_root: str | Path,
    *,
    close_strength_thresholds: list[float] | tuple[float, ...] = DEFAULT_CLOSE_STRENGTH_THRESHOLDS,
    top_fractions: list[float] | tuple[float, ...] = DEFAULT_TOP_FRACTIONS,
    min_closed_cycle_count: int = 30,
    min_month_closed_cycle_count: int = 1,
    min_train_months: int = 2,
    min_oos_test_months: int = 2,
    boundary_quarantine_artifact: str | Path | None = None,
    local_price_only: bool = False,
    report_name_contains: str = DEFAULT_REPORT_NAME_CONTAINS,
    max_entry_gap: float = DEFAULT_MAX_ENTRY_GAP,
    target_hit_rate: float = TARGET_HIT_RATE,
    target_mean_return: float = TARGET_MEAN_RETURN,
    min_beta_tradeable_rate: float = MIN_BETA_TRADEABLE_RATE,
    dilution_hit_rate_drop: float = 0.20,
    research_hit_rate_floor: float = 0.45,
) -> dict[str, Any]:
    resolved_root = Path(reports_root).expanduser().resolve()
    rows = _collect_rows(
        resolved_root,
        boundary_quarantine_artifact=boundary_quarantine_artifact,
        local_price_only=local_price_only,
        report_name_contains=report_name_contains,
    )
    trend_rows = [row for row in rows if row.get("event_prototype") == "trend_continuation"]
    grid_board: list[dict[str, Any]] = []
    for top_fraction in top_fractions:
        top_rows = _top_fraction_rows(trend_rows, "trend_acceleration", float(top_fraction))
        base_occurrence_rows = _rows_with_gap_le(top_rows, max_entry_gap)
        for threshold in close_strength_thresholds:
            grid_board.append(
                _grid_row(
                    gate_id=_gate_id_for_close_threshold(float(threshold)),
                    threshold=float(threshold),
                    top_fraction=float(top_fraction),
                    base_occurrence_rows=base_occurrence_rows,
                    min_closed_cycle_count=min_closed_cycle_count,
                    min_month_closed_cycle_count=min_month_closed_cycle_count,
                    min_train_months=min_train_months,
                    min_oos_test_months=min_oos_test_months,
                    target_hit_rate=target_hit_rate,
                    target_mean_return=target_mean_return,
                    min_beta_tradeable_rate=min_beta_tradeable_rate,
                )
            )
    _attach_dilution_flags(grid_board, dilution_hit_rate_drop=dilution_hit_rate_drop)
    populated_rows = [row for row in grid_board if row.get("candidate_unique_hit_rate_15pct") is not None]
    best_candidate = max(populated_rows, key=_candidate_quality_sort_key) if populated_rows else None
    sorted_board = sorted(
        grid_board,
        key=lambda row: (
            float(row.get("top_fraction") or 0.0),
            float(row.get("close_strength_threshold") or 0.0),
        ),
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        "report_name_contains": report_name_contains,
        "row_count": len(rows),
        "trend_row_count": len(trend_rows),
        "close_strength_thresholds": [float(value) for value in close_strength_thresholds],
        "top_fractions": [float(value) for value in top_fractions],
        "max_entry_gap": max_entry_gap,
        "target_hit_rate": target_hit_rate,
        "target_mean_return": target_mean_return,
        "grid_row_count": len(sorted_board),
        "grid_board": sorted_board,
        "best_research_candidate": best_candidate,
        "grid_decision": _grid_decision(
            sorted_board,
            best_candidate,
            research_hit_rate_floor=research_hit_rate_floor,
            target_mean_return=target_mean_return,
        ),
    }


def render_btst_5d_15pct_trend_gate_threshold_grid_markdown(grid: dict[str, Any]) -> str:
    lines = ["# BTST 5D / 15% Trend Gate Threshold Grid", ""]
    best = dict(grid.get("best_research_candidate") or {})
    decision = dict(grid.get("grid_decision") or {})
    lines.append(f"- row_count: {grid.get('row_count')}")
    lines.append(f"- trend_row_count: {grid.get('trend_row_count')}")
    lines.append(f"- grid_row_count: {grid.get('grid_row_count')}")
    lines.append(f"- best_gate_id: {best.get('gate_id')}")
    lines.append(f"- best_hit_rate_15pct: {best.get('candidate_unique_hit_rate_15pct')}")
    lines.append(f"- best_mean_max_return: {best.get('candidate_unique_mean_max_return')}")
    lines.append(f"- grid_decision: {decision.get('next_step')}")
    lines.append("")
    lines.append("## Grid Board")
    for row in list(grid.get("grid_board") or []):
        lines.append(
            f"- top={row.get('top_fraction')} {row.get('gate_id')}: closed={row.get('candidate_unique_closed')}, "
            f"hit_rate_15pct={row.get('candidate_unique_hit_rate_15pct')}, mean_max_return={row.get('candidate_unique_mean_max_return')}, "
            f"sample_gap={row.get('sample_gap_to_min_closed')}, stable_oos={row.get('stable_oos_test_month_count')}, "
            f"dilution={row.get('dilution_flag')}, decision={dict(row.get('rollout_decision') or {}).get('next_step')}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare controlled catalyst close-strength gates inside the BTST trend top slice.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument("--close-strength-threshold", action="append", dest="close_strength_thresholds", type=float, default=None)
    parser.add_argument("--top-fraction", action="append", dest="top_fractions", type=float, default=None)
    parser.add_argument("--min-closed-cycle-count", type=int, default=30)
    parser.add_argument("--min-month-closed-cycle-count", type=int, default=1)
    parser.add_argument("--min-train-months", type=int, default=2)
    parser.add_argument("--min-oos-test-months", type=int, default=2)
    parser.add_argument("--boundary-quarantine-artifact", default=str(DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT))
    parser.add_argument("--local-price-only", action="store_true")
    parser.add_argument("--report-name-contains", default=DEFAULT_REPORT_NAME_CONTAINS)
    parser.add_argument("--max-entry-gap", type=float, default=DEFAULT_MAX_ENTRY_GAP)
    parser.add_argument("--target-hit-rate", type=float, default=TARGET_HIT_RATE)
    parser.add_argument("--target-mean-return", type=float, default=TARGET_MEAN_RETURN)
    parser.add_argument("--min-beta-tradeable-rate", type=float, default=MIN_BETA_TRADEABLE_RATE)
    parser.add_argument("--dilution-hit-rate-drop", type=float, default=0.20)
    parser.add_argument("--research-hit-rate-floor", type=float, default=0.45)
    args = parser.parse_args()

    grid = analyze_btst_5d_15pct_trend_gate_threshold_grid(
        args.reports_root,
        close_strength_thresholds=tuple(args.close_strength_thresholds or DEFAULT_CLOSE_STRENGTH_THRESHOLDS),
        top_fractions=tuple(args.top_fractions or DEFAULT_TOP_FRACTIONS),
        min_closed_cycle_count=args.min_closed_cycle_count,
        min_month_closed_cycle_count=args.min_month_closed_cycle_count,
        min_train_months=args.min_train_months,
        min_oos_test_months=args.min_oos_test_months,
        boundary_quarantine_artifact=args.boundary_quarantine_artifact,
        local_price_only=args.local_price_only,
        report_name_contains=args.report_name_contains,
        max_entry_gap=args.max_entry_gap,
        target_hit_rate=args.target_hit_rate,
        target_mean_return=args.target_mean_return,
        min_beta_tradeable_rate=args.min_beta_tradeable_rate,
        dilution_hit_rate_drop=args.dilution_hit_rate_drop,
        research_hit_rate_floor=args.research_hit_rate_floor,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(grid, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_5d_15pct_trend_gate_threshold_grid_markdown(grid), encoding="utf-8")
    print(
        json.dumps(
            {
                "grid_row_count": grid.get("grid_row_count"),
                "best_research_candidate": grid.get("best_research_candidate"),
                "grid_decision": grid.get("grid_decision"),
                "output_json": str(output_json),
                "output_md": str(output_md),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
