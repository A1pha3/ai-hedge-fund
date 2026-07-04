# isort: skip_file
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_btst_5d_15pct_factor_research_round1 import (
    DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT,
    _load_boundary_quarantine_lists,
    _resolve_boundary_quarantine_artifact,
)
from scripts.analyze_btst_5d_15pct_trend_breakout_drilldown import (
    DEFAULT_REPORTS_ROOT,
    _extract_local_btst_price_outcome_with_reason,
    _missing_local_price_outcome,
    _rows_with_gap_le,
    _summary,
    _top_fraction_rows,
)
from scripts.btst_analysis_utils import (
    extract_btst_price_outcome as _extract_btst_price_outcome,
    iter_selection_snapshots as _iter_selection_snapshots,
    normalize_trade_date as _normalize_trade_date,
    round_or_none as _round_or_none,
    safe_float as _safe_float,
)
from scripts.btst_report_utils import discover_nested_report_dirs as discover_report_dirs
from scripts.btst_round1_factor_mining_helpers import build_round1_research_row

DEFAULT_OUTPUT_JSON = Path("data/reports/btst_5d_15pct_trend_top20_gate_diagnostics_latest.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_5d_15pct_trend_top20_gate_diagnostics_latest.md")
DEFAULT_REPORT_NAME_CONTAINS = ""


GatePredicate = Callable[[dict[str, Any]], bool]


def _extract_price_outcome(
    report_dir: Path,
    ticker: str,
    trade_date: str,
    price_cache: dict[tuple[str, str], Any],
    *,
    local_price_only: bool,
) -> dict[str, Any]:
    local_outcome, local_missing_reason = _extract_local_btst_price_outcome_with_reason(report_dir, ticker, trade_date)
    if local_outcome is not None:
        return local_outcome
    if local_price_only:
        return _missing_local_price_outcome(local_missing_reason)
    external_outcome = dict(_extract_btst_price_outcome(ticker, trade_date, price_cache))
    if local_missing_reason:
        external_outcome.setdefault("local_price_missing_reason", local_missing_reason)
    return external_outcome


def _collect_rows(
    reports_root: str | Path,
    *,
    boundary_quarantine_artifact: str | Path | None,
    local_price_only: bool,
    report_name_contains: str,
) -> list[dict[str, Any]]:
    resolved_root = Path(reports_root).expanduser().resolve()
    quarantine_lists = _load_boundary_quarantine_lists(_resolve_boundary_quarantine_artifact(resolved_root, boundary_quarantine_artifact))
    excluded_tickers = quarantine_lists["quarantine"] | quarantine_lists["separate_surface"]
    report_dirs = discover_report_dirs([resolved_root], report_name_contains=report_name_contains)
    price_cache: dict[tuple[str, str], Any] = {}
    rows: list[dict[str, Any]] = []
    for report_dir in report_dirs:
        for snapshot in _iter_selection_snapshots(report_dir) or []:
            trade_date = _normalize_trade_date(snapshot.get("trade_date"))
            for ticker, evaluation in dict(snapshot.get("selection_targets") or {}).items():
                if str(ticker) in excluded_tickers:
                    continue
                short_trade = dict((evaluation or {}).get("short_trade") or {})
                if not short_trade:
                    continue
                rows.append(
                    build_round1_research_row(
                        ticker=str(ticker),
                        trade_date=trade_date,
                        report_dir_name=report_dir.name,
                        evaluation=dict(evaluation or {}),
                        price_outcome=_extract_price_outcome(report_dir, str(ticker), trade_date, price_cache, local_price_only=local_price_only),
                    )
                )
    return rows


def _gate_specs() -> list[tuple[str, GatePredicate]]:
    return [
        ("close_strength_ge_0_85", lambda row: (_safe_float(row.get("close_strength")) or 0.0) >= 0.85),
        ("close_strength_ge_0_90", lambda row: (_safe_float(row.get("close_strength")) or 0.0) >= 0.90),
        ("trend_acceleration_ge_0_80", lambda row: (_safe_float(row.get("trend_acceleration")) or 0.0) >= 0.80),
        ("trend_acceleration_ge_0_85", lambda row: (_safe_float(row.get("trend_acceleration")) or 0.0) >= 0.85),
        ("volume_quality_lt_0_55", lambda row: (_safe_float(row.get("volume_expansion_quality")) or 0.0) < 0.55),
        ("breakout_freshness_lt_0_55", lambda row: (_safe_float(row.get("breakout_freshness")) or 0.0) < 0.55),
        ("decision_selected_only", lambda row: str(row.get("decision") or "") == "selected"),
        ("decision_non_selected", lambda row: str(row.get("decision") or "") != "selected"),
        ("catalyst_theme_non_selected", lambda row: str(row.get("candidate_source") or "") == "catalyst_theme" and str(row.get("decision") or "") != "selected"),
        ("catalyst_theme_close_strength_lt_0_90", lambda row: str(row.get("candidate_source") or "") == "catalyst_theme" and (_safe_float(row.get("close_strength")) or 0.0) < 0.90),
        (
            "catalyst_theme_close_strength_lt_0_90_non_selected",
            lambda row: str(row.get("candidate_source") or "") == "catalyst_theme" and (_safe_float(row.get("close_strength")) or 0.0) < 0.90 and str(row.get("decision") or "") != "selected",
        ),
        ("catalyst_theme_trend_acceleration_lt_0_85", lambda row: str(row.get("candidate_source") or "") == "catalyst_theme" and (_safe_float(row.get("trend_acceleration")) or 0.0) < 0.85),
        (
            "catalyst_theme_trend_acceleration_lt_0_85_non_selected",
            lambda row: str(row.get("candidate_source") or "") == "catalyst_theme" and (_safe_float(row.get("trend_acceleration")) or 0.0) < 0.85 and str(row.get("decision") or "") != "selected",
        ),
    ]


def _decide_gate(gate_summary: dict[str, Any], base_summary: dict[str, Any], *, min_closed_cycle_count: int) -> str:
    closed_count = int(gate_summary.get("deduped_closed_cycle_count") or 0)
    hit_rate = float(gate_summary.get("deduped_hit_rate_15pct") or 0.0)
    mean_return = float(gate_summary.get("deduped_mean_max_future_high_return_2_5d") or 0.0)
    beta_tradeable_rate = float(gate_summary.get("deduped_beta_tradeable_rate") or 0.0)
    uplift = float(gate_summary.get("deduped_hit_rate_uplift_vs_base") or 0.0)
    if closed_count >= max(3, min_closed_cycle_count) and hit_rate >= 0.55 and mean_return >= 0.15 and beta_tradeable_rate >= 0.70:
        return "upgrade"
    if closed_count >= min_closed_cycle_count and uplift > 0.0:
        return "observe"
    if closed_count == 0 or hit_rate < float(base_summary.get("deduped_hit_rate_15pct") or 0.0):
        return "downgrade"
    return "hold"


def _dedupe_signal_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("ticker") or ""), str(row.get("trade_date") or ""))
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = row
            continue
        if row.get("gamma_closed_cycle") and not existing.get("gamma_closed_cycle"):
            deduped[key] = row
    return list(deduped.values())


def _attach_deduped_summary(summary: dict[str, Any], rows: list[dict[str, Any]], *, min_closed_cycle_count: int) -> dict[str, Any]:
    deduped_summary = _summary(_dedupe_signal_rows(rows), min_closed_cycle_count=min_closed_cycle_count)
    summary.update(
        {
            "deduped_row_count": deduped_summary.get("row_count"),
            "deduped_closed_cycle_count": deduped_summary.get("closed_cycle_count"),
            "deduped_hit_rate_15pct": deduped_summary.get("hit_rate_15pct"),
            "deduped_executable_hit_rate_15pct": deduped_summary.get("executable_hit_rate_15pct"),
            "deduped_mean_max_future_high_return_2_5d": deduped_summary.get("mean_max_future_high_return_2_5d"),
            "deduped_beta_tradeable_rate": deduped_summary.get("beta_tradeable_rate"),
            "deduped_unique_report_dir_count": deduped_summary.get("unique_report_dir_count"),
            "deduped_has_min_closed_cycle_count": deduped_summary.get("has_min_closed_cycle_count"),
        }
    )
    return summary


def _gate_record(
    *,
    gate_id: str,
    rows: list[dict[str, Any]],
    base_summary: dict[str, Any],
    min_closed_cycle_count: int,
) -> dict[str, Any]:
    summary = _summary(rows, min_closed_cycle_count=min_closed_cycle_count)
    _attach_deduped_summary(summary, rows, min_closed_cycle_count=min_closed_cycle_count)
    base_hit_rate = base_summary.get("hit_rate_15pct")
    base_mean_return = base_summary.get("mean_max_future_high_return_2_5d")
    base_deduped_hit_rate = base_summary.get("deduped_hit_rate_15pct")
    base_deduped_mean_return = base_summary.get("deduped_mean_max_future_high_return_2_5d")
    summary.update(
        {
            "gate_id": gate_id,
            "hit_rate_uplift_vs_base": _round_or_none(float(summary.get("hit_rate_15pct") or 0.0) - float(base_hit_rate or 0.0)) if base_hit_rate is not None and summary.get("hit_rate_15pct") is not None else None,
            "mean_return_uplift_vs_base": _round_or_none(float(summary.get("mean_max_future_high_return_2_5d") or 0.0) - float(base_mean_return or 0.0)) if base_mean_return is not None and summary.get("mean_max_future_high_return_2_5d") is not None else None,
            "deduped_hit_rate_uplift_vs_base": _round_or_none(float(summary.get("deduped_hit_rate_15pct") or 0.0) - float(base_deduped_hit_rate or 0.0)) if base_deduped_hit_rate is not None and summary.get("deduped_hit_rate_15pct") is not None else None,
            "deduped_mean_return_uplift_vs_base": _round_or_none(float(summary.get("deduped_mean_max_future_high_return_2_5d") or 0.0) - float(base_deduped_mean_return or 0.0)) if base_deduped_mean_return is not None and summary.get("deduped_mean_max_future_high_return_2_5d") is not None else None,
        }
    )
    summary["decision"] = _decide_gate(summary, base_summary, min_closed_cycle_count=min_closed_cycle_count)
    return summary


def _candidate_source_records(base_rows: list[dict[str, Any]], base_summary: dict[str, Any], *, min_closed_cycle_count: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source, count in Counter(str(row.get("candidate_source") or "unknown") for row in base_rows).most_common():
        if count == 0:
            continue
        source_rows = [row for row in base_rows if str(row.get("candidate_source") or "unknown") == source]
        records.append(
            _gate_record(
                gate_id=f"candidate_source_{source}",
                rows=source_rows,
                base_summary=base_summary,
                min_closed_cycle_count=min_closed_cycle_count,
            )
        )
    return records


def _gate_decision(gate_board: list[dict[str, Any]]) -> dict[str, str]:
    if any(row.get("decision") == "upgrade" for row in gate_board):
        return {"next_step": "promote_best_gate_to_candidate_review", "reason": "at_least_one_gate_met_upgrade_threshold"}
    if any(row.get("decision") == "observe" for row in gate_board):
        return {"next_step": "continue_gate_validation", "reason": "at_least_one_gate_improved_over_current_base"}
    return {"next_step": "hold_current_top20_gap_gate", "reason": "no_gate_improved_over_current_base"}


def analyze_btst_5d_15pct_trend_top20_gate_diagnostics(
    reports_root: str | Path,
    *,
    min_closed_cycle_count: int = 30,
    boundary_quarantine_artifact: str | Path | None = None,
    local_price_only: bool = False,
    report_name_contains: str = DEFAULT_REPORT_NAME_CONTAINS,
    top_fraction: float = 0.20,
    max_entry_gap: float = 0.03,
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
    base_rows = _rows_with_gap_le(top_rows, max_entry_gap)
    base_summary = _summary(base_rows, min_closed_cycle_count=min_closed_cycle_count)
    _attach_deduped_summary(base_summary, base_rows, min_closed_cycle_count=min_closed_cycle_count)
    top_label = int(top_fraction * 100)
    base_summary.update({"slice_id": f"trend_acceleration_top_{top_label}pct_gap_le_{int(max_entry_gap * 100)}pct"})

    gate_board = [_gate_record(gate_id=gate_id, rows=[row for row in base_rows if predicate(row)], base_summary=base_summary, min_closed_cycle_count=min_closed_cycle_count) for gate_id, predicate in _gate_specs()]
    gate_board.extend(_candidate_source_records(base_rows, base_summary, min_closed_cycle_count=min_closed_cycle_count))
    gate_board = sorted(
        gate_board,
        key=lambda row: (
            str(row.get("decision") or "") != "upgrade",
            str(row.get("decision") or "") != "observe",
            -float(row.get("deduped_hit_rate_uplift_vs_base") or -999.0),
            -int(row.get("deduped_closed_cycle_count") or 0),
            str(row.get("gate_id") or ""),
        ),
    )
    frozen_counts = Counter(str(row.get("event_prototype") or "unclassified") for row in rows if row.get("event_prototype") != "trend_continuation")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        "report_name_contains": report_name_contains,
        "row_count": len(rows),
        "trend_row_count": len(trend_rows),
        "top_fraction": top_fraction,
        "max_entry_gap": max_entry_gap,
        "base_slice": base_summary,
        "gate_board": gate_board,
        "frozen_out_event_prototype_counts": dict(sorted(frozen_counts.items())),
        "gate_decision": _gate_decision(gate_board),
    }


def render_btst_5d_15pct_trend_top20_gate_diagnostics_markdown(diagnostics: dict[str, Any]) -> str:
    lines = ["# BTST 5D / 15% Trend Top20 Gate Diagnostics", ""]
    base = dict(diagnostics.get("base_slice") or {})
    lines.append(f"- row_count: {diagnostics.get('row_count')}")
    lines.append(f"- trend_row_count: {diagnostics.get('trend_row_count')}")
    lines.append(f"- base_slice: {base.get('slice_id')}")
    lines.append(f"- base_closed: {base.get('closed_cycle_count')}")
    lines.append(f"- base_hit_rate_15pct: {base.get('hit_rate_15pct')}")
    lines.append(f"- base_mean_max_return: {base.get('mean_max_future_high_return_2_5d')}")
    lines.append(f"- base_deduped_closed: {base.get('deduped_closed_cycle_count')}")
    lines.append(f"- base_deduped_hit_rate_15pct: {base.get('deduped_hit_rate_15pct')}")
    lines.append(f"- base_deduped_mean_max_return: {base.get('deduped_mean_max_future_high_return_2_5d')}")
    lines.append(f"- gate_decision: {dict(diagnostics.get('gate_decision') or {}).get('next_step')}")
    lines.append("")
    lines.append("## Gate Board")
    for row in list(diagnostics.get("gate_board") or []):
        lines.append(
            f"- {row.get('gate_id')}: rows={row.get('row_count')}, closed={row.get('closed_cycle_count')}, "
            f"hit_rate_15pct={row.get('hit_rate_15pct')}, uplift={row.get('hit_rate_uplift_vs_base')}, "
            f"deduped_closed={row.get('deduped_closed_cycle_count')}, deduped_hit_rate_15pct={row.get('deduped_hit_rate_15pct')}, "
            f"deduped_uplift={row.get('deduped_hit_rate_uplift_vs_base')}, "
            f"mean_max_return={row.get('mean_max_future_high_return_2_5d')}, beta_tradeable_rate={row.get('beta_tradeable_rate')}, "
            f"decision={row.get('decision')}"
        )
    lines.append("")
    lines.append("## Frozen Out Event Prototype Counts")
    for label, count in dict(diagnostics.get("frozen_out_event_prototype_counts") or {}).items():
        lines.append(f"- {label}: {count}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose pre-registered gates inside the current BTST trend top20 gap slice.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument("--min-closed-cycle-count", type=int, default=30)
    parser.add_argument("--boundary-quarantine-artifact", default=str(DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT))
    parser.add_argument("--local-price-only", action="store_true")
    parser.add_argument("--report-name-contains", default=DEFAULT_REPORT_NAME_CONTAINS)
    parser.add_argument("--top-fraction", type=float, default=0.20)
    parser.add_argument("--max-entry-gap", type=float, default=0.03)
    args = parser.parse_args()

    diagnostics = analyze_btst_5d_15pct_trend_top20_gate_diagnostics(
        args.reports_root,
        min_closed_cycle_count=args.min_closed_cycle_count,
        boundary_quarantine_artifact=args.boundary_quarantine_artifact,
        local_price_only=args.local_price_only,
        report_name_contains=args.report_name_contains,
        top_fraction=args.top_fraction,
        max_entry_gap=args.max_entry_gap,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_5d_15pct_trend_top20_gate_diagnostics_markdown(diagnostics), encoding="utf-8")
    print(json.dumps({key: diagnostics.get(key) for key in ("row_count", "trend_row_count", "base_slice", "gate_decision")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
