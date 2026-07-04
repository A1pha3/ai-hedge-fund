# flake8: noqa
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_btst_5d_15pct_factor_research_round1 import (
    DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT,
)
from scripts.analyze_btst_5d_15pct_trend_breakout_drilldown import (
    _rows_with_gap_le,
    _summary,
    _top_fraction_rows,
    DEFAULT_REPORTS_ROOT,
)
from scripts.analyze_btst_5d_15pct_trend_gate_oos_validation import (
    _gate_predicate,
    MIN_BETA_TRADEABLE_RATE,
    TARGET_HIT_RATE,
    TARGET_MEAN_RETURN,
)
from scripts.analyze_btst_5d_15pct_trend_top20_gate_diagnostics import (
    _collect_rows,
    _dedupe_signal_rows,
    DEFAULT_REPORT_NAME_CONTAINS,
)
from scripts.btst_analysis_utils import round_or_none as _round_or_none
from scripts.btst_analysis_utils import safe_float as _safe_float

DEFAULT_OUTPUT_JSON = Path("data/reports/btst_5d_15pct_trend_gate_confirmation_grid_latest.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_5d_15pct_trend_gate_confirmation_grid_latest.md")
DEFAULT_BASE_GATE_ID = "catalyst_theme_close_strength_lt_0_90"
DEFAULT_CONFIRMATION_SPECS: tuple[tuple[str, str, str, float], ...] = (
    ("breakout_freshness_le_0_40", "breakout_freshness", "<=", 0.40),
    ("breakout_freshness_le_0_43", "breakout_freshness", "<=", 0.43),
    ("volume_expansion_quality_le_0_25", "volume_expansion_quality", "<=", 0.25),
    ("volume_expansion_quality_le_0_28", "volume_expansion_quality", "<=", 0.28),
    ("close_strength_le_0_89", "close_strength", "<=", 0.89),
    ("close_strength_le_0_895", "close_strength", "<=", 0.895),
)

ConfirmationSpec = tuple[str, str, str, float]


def _predicate_for_confirmation(field_name: str, operator: str, threshold: float) -> Callable[[dict[str, Any]], bool]:
    def _predicate(row: dict[str, Any]) -> bool:
        value = _safe_float(row.get(field_name))
        if value is None:
            return False
        if operator == ">=":
            return value >= threshold
        if operator == "<=":
            return value <= threshold
        raise ValueError(f"Unsupported operator: {operator}")

    return _predicate


def _confirmation_row(
    *,
    confirmation_spec: ConfirmationSpec,
    base_unique_rows: list[dict[str, Any]],
    base_summary: dict[str, Any],
    min_closed_cycle_count: int,
) -> dict[str, Any]:
    confirmation_id, field_name, operator, threshold = confirmation_spec
    predicate = _predicate_for_confirmation(field_name, operator, threshold)
    candidate_unique_rows = [row for row in base_unique_rows if predicate(row)]
    candidate_summary = _summary(candidate_unique_rows, min_closed_cycle_count=min_closed_cycle_count)
    candidate_hit_rate = candidate_summary.get("hit_rate_15pct")
    candidate_mean_return = candidate_summary.get("mean_max_future_high_return_2_5d")
    base_hit_rate = base_summary.get("hit_rate_15pct")
    base_mean_return = base_summary.get("mean_max_future_high_return_2_5d")
    return {
        "confirmation_id": confirmation_id,
        "field_name": field_name,
        "operator": operator,
        "threshold": float(threshold),
        "candidate_unique_count": candidate_summary.get("row_count"),
        "candidate_unique_closed": candidate_summary.get("closed_cycle_count"),
        "candidate_unique_hit_rate_15pct": candidate_hit_rate,
        "candidate_unique_mean_max_return": candidate_mean_return,
        "candidate_unique_beta_tradeable_rate": candidate_summary.get("beta_tradeable_rate"),
        "sample_gap_to_min_closed": max(0, min_closed_cycle_count - int(candidate_summary.get("closed_cycle_count") or 0)),
        "hit_rate_uplift_vs_base": _round_or_none(float(candidate_hit_rate or 0.0) - float(base_hit_rate or 0.0)) if candidate_hit_rate is not None and base_hit_rate is not None else None,
        "mean_return_uplift_vs_base": _round_or_none(float(candidate_mean_return or 0.0) - float(base_mean_return or 0.0)) if candidate_mean_return is not None and base_mean_return is not None else None,
    }


def _confirmation_sort_key(row: dict[str, Any]) -> tuple[float, float, int, float]:
    return (
        float(row.get("candidate_unique_hit_rate_15pct") or -1.0),
        int(row.get("candidate_unique_closed") or 0),
        float(row.get("candidate_unique_mean_max_return") or -1.0),
        float(row.get("candidate_unique_beta_tradeable_rate") or -1.0),
    )


def _grid_decision(
    best_candidate: dict[str, Any] | None,
    *,
    min_closed_cycle_count: int,
    target_hit_rate: float,
    target_mean_return: float,
    min_beta_tradeable_rate: float,
    research_hit_rate_floor: float,
) -> dict[str, str]:
    if not best_candidate:
        return {"next_step": "hold_base_gate", "reason": "no_confirmation_candidate_rows"}

    closed_count = int(best_candidate.get("candidate_unique_closed") or 0)
    hit_rate = float(best_candidate.get("candidate_unique_hit_rate_15pct") or 0.0)
    mean_return = float(best_candidate.get("candidate_unique_mean_max_return") or 0.0)
    beta_tradeable_rate = float(best_candidate.get("candidate_unique_beta_tradeable_rate") or 0.0)
    if closed_count >= min_closed_cycle_count and hit_rate >= target_hit_rate and mean_return >= target_mean_return and beta_tradeable_rate >= min_beta_tradeable_rate:
        return {"next_step": "promote_confirmation_candidate_to_oos_review", "reason": "confirmation_candidate_met_research_thresholds"}
    if hit_rate >= research_hit_rate_floor and mean_return >= target_mean_return:
        return {"next_step": "keep_confirmation_candidate_collect_samples", "reason": "quality_promising_but_sample_size_still_small"}
    return {"next_step": "hold_base_gate", "reason": "no_confirmation_candidate_preserved_quality"}


def analyze_btst_5d_15pct_trend_gate_confirmation_grid(
    reports_root: str | Path,
    *,
    base_gate_id: str = DEFAULT_BASE_GATE_ID,
    confirmation_specs: list[ConfirmationSpec] | tuple[ConfirmationSpec, ...] = DEFAULT_CONFIRMATION_SPECS,
    min_closed_cycle_count: int = 30,
    boundary_quarantine_artifact: str | Path | None = None,
    local_price_only: bool = False,
    report_name_contains: str = DEFAULT_REPORT_NAME_CONTAINS,
    top_fraction: float = 0.20,
    max_entry_gap: float = 0.03,
    target_hit_rate: float = TARGET_HIT_RATE,
    target_mean_return: float = TARGET_MEAN_RETURN,
    min_beta_tradeable_rate: float = MIN_BETA_TRADEABLE_RATE,
    research_hit_rate_floor: float = 0.50,
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
    entry_eligible_rows = _rows_with_gap_le(top_rows, max_entry_gap)
    base_gate_predicate = _gate_predicate(base_gate_id)
    base_occurrence_rows = [row for row in entry_eligible_rows if base_gate_predicate(row)]
    base_unique_rows = _dedupe_signal_rows(base_occurrence_rows)
    base_summary = _summary(base_unique_rows, min_closed_cycle_count=min_closed_cycle_count)
    grid_board = [
        _confirmation_row(
            confirmation_spec=spec,
            base_unique_rows=base_unique_rows,
            base_summary=base_summary,
            min_closed_cycle_count=min_closed_cycle_count,
        )
        for spec in confirmation_specs
    ]
    populated_rows = [row for row in grid_board if row.get("candidate_unique_hit_rate_15pct") is not None]
    best_candidate = max(populated_rows, key=_confirmation_sort_key) if populated_rows else None
    sorted_board = sorted(grid_board, key=lambda row: (str(row.get("field_name") or ""), str(row.get("operator") or ""), float(row.get("threshold") or 0.0)))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        "report_name_contains": report_name_contains,
        "row_count": len(rows),
        "trend_row_count": len(trend_rows),
        "top_fraction": top_fraction,
        "base_gate_id": base_gate_id,
        "base_occurrence_count": len(base_occurrence_rows),
        "base_unique_count": len(base_unique_rows),
        "base_summary": base_summary,
        "grid_row_count": len(sorted_board),
        "grid_board": sorted_board,
        "best_confirmation_candidate": best_candidate,
        "grid_decision": _grid_decision(
            best_candidate,
            min_closed_cycle_count=min_closed_cycle_count,
            target_hit_rate=target_hit_rate,
            target_mean_return=target_mean_return,
            min_beta_tradeable_rate=min_beta_tradeable_rate,
            research_hit_rate_floor=research_hit_rate_floor,
        ),
    }


def render_btst_5d_15pct_trend_gate_confirmation_grid_markdown(grid: dict[str, Any]) -> str:
    lines = ["# BTST 5D / 15% Trend Gate Confirmation Grid", ""]
    best = dict(grid.get("best_confirmation_candidate") or {})
    decision = dict(grid.get("grid_decision") or {})
    base_summary = dict(grid.get("base_summary") or {})
    lines.append(f"- base_gate_id: {grid.get('base_gate_id')}")
    lines.append(f"- base_unique_count: {grid.get('base_unique_count')}")
    lines.append(f"- base_closed_cycle_count: {base_summary.get('closed_cycle_count')}")
    lines.append(f"- best_confirmation_id: {best.get('confirmation_id')}")
    lines.append(f"- best_hit_rate_15pct: {best.get('candidate_unique_hit_rate_15pct')}")
    lines.append(f"- best_mean_max_return: {best.get('candidate_unique_mean_max_return')}")
    lines.append(f"- grid_decision: {decision.get('next_step')}")
    lines.append("")
    lines.append("## Confirmation Grid Board")
    for row in list(grid.get("grid_board") or []):
        lines.append(f"- {row.get('confirmation_id')}: " f"closed={row.get('candidate_unique_closed')} " f"hit_rate={row.get('candidate_unique_hit_rate_15pct')} " f"mean_return={row.get('candidate_unique_mean_max_return')} " f"sample_gap={row.get('sample_gap_to_min_closed')}")
    lines.append("")
    return "\n".join(lines)


def _parse_confirmation_spec(value: str) -> ConfirmationSpec:
    parts = [part.strip() for part in value.split("|")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("Confirmation spec must be id|field|operator|threshold")
    confirmation_id, field_name, operator, threshold_text = parts
    if operator not in {">=", "<="}:
        raise argparse.ArgumentTypeError("Confirmation operator must be >= or <=")
    try:
        threshold = float(threshold_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Confirmation threshold must be numeric") from exc
    return (confirmation_id, field_name, operator, threshold)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank second-layer confirmation factors inside the best BTST trend gate.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument("--base-gate-id", default=DEFAULT_BASE_GATE_ID)
    parser.add_argument("--confirmation-spec", action="append", type=_parse_confirmation_spec, default=None)
    parser.add_argument("--min-closed-cycle-count", type=int, default=30)
    parser.add_argument("--boundary-quarantine-artifact", default=str(DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT))
    parser.add_argument("--local-price-only", action="store_true")
    parser.add_argument("--report-name-contains", default=DEFAULT_REPORT_NAME_CONTAINS)
    parser.add_argument("--top-fraction", type=float, default=0.20)
    parser.add_argument("--max-entry-gap", type=float, default=0.03)
    parser.add_argument("--target-hit-rate", type=float, default=TARGET_HIT_RATE)
    parser.add_argument("--target-mean-return", type=float, default=TARGET_MEAN_RETURN)
    parser.add_argument("--min-beta-tradeable-rate", type=float, default=MIN_BETA_TRADEABLE_RATE)
    parser.add_argument("--research-hit-rate-floor", type=float, default=0.50)
    args = parser.parse_args()

    board = analyze_btst_5d_15pct_trend_gate_confirmation_grid(
        args.reports_root,
        base_gate_id=args.base_gate_id,
        confirmation_specs=tuple(args.confirmation_spec) if args.confirmation_spec else DEFAULT_CONFIRMATION_SPECS,
        min_closed_cycle_count=args.min_closed_cycle_count,
        boundary_quarantine_artifact=args.boundary_quarantine_artifact,
        local_price_only=args.local_price_only,
        report_name_contains=args.report_name_contains,
        top_fraction=args.top_fraction,
        max_entry_gap=args.max_entry_gap,
        target_hit_rate=args.target_hit_rate,
        target_mean_return=args.target_mean_return,
        min_beta_tradeable_rate=args.min_beta_tradeable_rate,
        research_hit_rate_floor=args.research_hit_rate_floor,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(board, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_5d_15pct_trend_gate_confirmation_grid_markdown(board), encoding="utf-8")
    print(
        json.dumps(
            {
                "base_gate_id": board.get("base_gate_id"),
                "base_unique_count": board.get("base_unique_count"),
                "grid_row_count": board.get("grid_row_count"),
                "best_confirmation_candidate": board.get("best_confirmation_candidate"),
                "grid_decision": board.get("grid_decision"),
                "output_json": str(output_json),
                "output_md": str(output_md),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
