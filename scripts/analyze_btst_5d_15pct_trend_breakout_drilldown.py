# isort: skip_file
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_btst_5d_15pct_factor_research_round1 import (
    DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT,
    _load_boundary_quarantine_lists,
    _resolve_boundary_quarantine_artifact,
)
from scripts.btst_analysis_utils import (
    extract_btst_price_outcome as _extract_btst_price_outcome,
    iter_selection_snapshots as _iter_selection_snapshots,
    normalize_trade_date as _normalize_trade_date,
    resolve_btst_trade_anchor as _resolve_btst_trade_anchor,
    round_or_none as _round_or_none,
    safe_float as _safe_float,
)
from scripts.btst_data_utils import normalize_price_frame as _normalize_price_frame
from scripts.btst_report_utils import discover_nested_report_dirs as discover_report_dirs
from scripts.btst_round1_factor_mining_helpers import build_round1_research_row

REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_5d_15pct_trend_breakout_drilldown_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_5d_15pct_trend_breakout_drilldown_latest.md"
DEFAULT_REPORT_NAME_CONTAINS = "paper_trading_window"
SCOPED_PROTOTYPES = ("trend_continuation", "breakout_ignition")


def _local_prices_path(report_dir: Path, ticker: str, trade_date: str) -> Path:
    return report_dir / "data_snapshots" / str(ticker) / _normalize_trade_date(trade_date) / "prices.json"


def _load_local_price_frame_with_reason(report_dir: Path, ticker: str, trade_date: str) -> tuple[pd.DataFrame, str | None]:
    ticker_root = report_dir / "data_snapshots" / str(ticker)
    if not ticker_root.exists():
        return pd.DataFrame(), "missing_ticker_snapshot_root"
    price_paths = sorted(ticker_root.glob("*/prices.json"))
    if not price_paths:
        exact_path = _local_prices_path(report_dir, ticker, trade_date)
        price_paths = [exact_path] if exact_path.exists() else []
    if not price_paths:
        return pd.DataFrame(), "missing_prices_json"
    raw_rows: list[dict[str, Any]] = []
    for prices_path in price_paths:
        payload = json.loads(prices_path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else list(payload.get("prices") or [])
        raw_rows.extend(row for row in rows if isinstance(row, dict))
    if not raw_rows:
        return pd.DataFrame(), "empty_prices_json_rows"
    raw_frame = pd.DataFrame(raw_rows)
    if "time" in raw_frame.columns and "date" not in raw_frame.columns:
        raw_frame = raw_frame.rename(columns={"time": "date"})
    frame = _normalize_price_frame(raw_frame)
    if frame.empty:
        return frame, "unusable_price_frame"
    return frame[~frame.index.duplicated(keep="last")].sort_index(), None


def _load_local_price_frame(report_dir: Path, ticker: str, trade_date: str) -> pd.DataFrame:
    frame, _missing_reason = _load_local_price_frame_with_reason(report_dir, ticker, trade_date)
    return frame


def _extract_local_btst_price_outcome(report_dir: Path, ticker: str, trade_date: str) -> dict[str, Any] | None:
    outcome, _missing_reason = _extract_local_btst_price_outcome_with_reason(report_dir, ticker, trade_date)
    return outcome


def _extract_local_btst_price_outcome_with_reason(report_dir: Path, ticker: str, trade_date: str) -> tuple[dict[str, Any] | None, str | None]:
    frame, missing_reason = _load_local_price_frame_with_reason(report_dir, ticker, trade_date)
    if frame.empty:
        return None, missing_reason or "empty_local_price_frame"

    trade_row, future_days, anchor_trade_date, used_prior_trade_anchor = _resolve_btst_trade_anchor(frame, trade_date)
    if trade_row is None:
        return None, "local_snapshot_missing_trade_anchor"
    if future_days.empty:
        return None, "local_snapshot_missing_future_bar"

    next_row = future_days.iloc[0]
    later_rows = future_days.iloc[1:]
    trade_close = _safe_float(trade_row.get("close"))
    next_open = _safe_float(next_row.get("open"))
    next_high = _safe_float(next_row.get("high"))
    next_low = _safe_float(next_row.get("low"))
    next_close = _safe_float(next_row.get("close"))
    if trade_close is None or trade_close <= 0 or next_open is None or next_high is None or next_close is None:
        return None, "local_snapshot_incomplete_anchor_or_t1_ohlc"

    t_plus_2_close = _safe_float(later_rows.iloc[0].get("close")) if len(later_rows) >= 1 else None
    future_horizon_rows = future_days.iloc[:5]
    future_highs = future_horizon_rows["high"].dropna().astype(float) if not future_horizon_rows.empty else pd.Series(dtype=float)
    max_future_high = None if future_highs.empty else float(future_highs.max())
    max_future_high_trade_date_2_5d = None
    if max_future_high is not None:
        max_idx = future_horizon_rows[future_horizon_rows["high"].astype(float) == max_future_high].index[0]
        max_future_high_trade_date_2_5d = max_idx.strftime("%Y-%m-%d")

    def _threshold_metrics(threshold: float) -> tuple[bool, int | None]:
        hit_rows = future_horizon_rows.loc[(future_horizon_rows["high"].astype(float) / trade_close) - 1.0 >= threshold]
        if hit_rows.empty:
            return False, None
        return True, int((hit_rows.index[0].normalize() - future_horizon_rows.index[0].normalize()).days + 1)

    future_high_hit_15pct_2_5d, time_to_hit_15pct = _threshold_metrics(0.15)
    return {
        "data_status": "ok" if t_plus_2_close is not None else "missing_t_plus_2_bar",
        "cycle_status": "closed_cycle" if t_plus_2_close is not None else "t1_only",
        "outcome_source": "local_data_snapshot",
        "trade_close": round(trade_close, 4),
        "trade_anchor_date": anchor_trade_date,
        "trade_date_was_non_trading": used_prior_trade_anchor,
        "next_trade_date": future_days.index[0].strftime("%Y-%m-%d"),
        "next_open": round(next_open, 4),
        "next_high": round(next_high, 4),
        "next_low": _round_or_none(next_low),
        "next_close": round(next_close, 4),
        "next_open_return": round((next_open / trade_close) - 1.0, 4),
        "next_high_return": round((next_high / trade_close) - 1.0, 4),
        "next_low_return": None if next_low is None else round((next_low / trade_close) - 1.0, 4),
        "next_close_return": round((next_close / trade_close) - 1.0, 4),
        "t_plus_2_close": _round_or_none(t_plus_2_close),
        "max_future_high_return_2_5d": None if max_future_high is None else round((max_future_high / trade_close) - 1.0, 4),
        "max_future_high_trade_date_2_5d": max_future_high_trade_date_2_5d,
        "time_to_hit_15pct": time_to_hit_15pct,
        "future_high_hit_15pct_2_5d": future_high_hit_15pct_2_5d,
    }, None


def _missing_local_price_outcome(missing_reason: str | None = None) -> dict[str, Any]:
    return {
        "data_status": "missing_local_data_snapshot",
        "cycle_status": "missing_next_day",
        "outcome_source": "missing_local_data_snapshot",
        "local_price_missing_reason": missing_reason or "missing_local_data_snapshot",
    }


def _extract_price_outcome(report_dir: Path, ticker: str, trade_date: str, price_cache: dict[tuple[str, str], Any], *, local_price_only: bool) -> dict[str, Any]:
    local_outcome, local_missing_reason = _extract_local_btst_price_outcome_with_reason(report_dir, ticker, trade_date)
    if local_outcome is not None:
        return local_outcome
    if local_price_only:
        return _missing_local_price_outcome(local_missing_reason)
    external_outcome = dict(_extract_btst_price_outcome(ticker, trade_date, price_cache))
    if local_missing_reason:
        external_outcome.setdefault("local_price_missing_reason", local_missing_reason)
    return external_outcome


def _count_outcome_sources(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get("outcome_source") or "external_price_extractor") for row in rows).items()))


def _count_data_statuses(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get("data_status") or "unknown") for row in rows).items()))


def _local_price_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    local_outcome_rows = [row for row in rows if row.get("outcome_source") == "local_data_snapshot"]
    missing_rows = [row for row in rows if row.get("local_price_missing_reason")]
    by_report: dict[str, dict[str, Any]] = {}
    for row in missing_rows:
        report_dir_name = str(row.get("report_dir_name") or "unknown")
        record = by_report.setdefault(
            report_dir_name,
            {
                "report_dir_name": report_dir_name,
                "missing_count": 0,
                "scoped_missing_count": 0,
            },
        )
        record["missing_count"] += 1
        if row.get("event_prototype") in SCOPED_PROTOTYPES:
            record["scoped_missing_count"] += 1
    top_missing_report_dirs = sorted(
        by_report.values(),
        key=lambda record: (-int(record["missing_count"]), str(record["report_dir_name"])),
    )[:10]
    total_rows = len(rows)
    return {
        "total_rows": total_rows,
        "local_outcome_count": len(local_outcome_rows),
        "missing_count": len(missing_rows),
        "coverage_rate": _round_or_none(len(local_outcome_rows) / total_rows) if total_rows else None,
        "missing_reason_counts": dict(sorted(Counter(str(row.get("local_price_missing_reason")) for row in missing_rows).items())),
        "missing_by_event_prototype": dict(sorted(Counter(str(row.get("event_prototype") or "unclassified") for row in missing_rows).items())),
        "top_missing_report_dirs": top_missing_report_dirs,
    }


def _collect_round1_rows(
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


def _summary(rows: list[dict[str, Any]], *, min_closed_cycle_count: int) -> dict[str, Any]:
    closed_rows = [row for row in rows if row.get("gamma_closed_cycle")]
    hit_rows = [row for row in closed_rows if row.get("future_high_hit_15pct_2_5d") is True]
    executable_rows = [row for row in closed_rows if row.get("beta_tradeable")]
    executable_hit_rows = [row for row in executable_rows if row.get("future_high_hit_15pct_2_5d") is True]
    hit_rate = _round_or_none(len(hit_rows) / len(closed_rows)) if closed_rows else None
    executable_hit_rate = _round_or_none(len(executable_hit_rows) / len(executable_rows)) if executable_rows else None
    mean_max_return = _round_or_none(sum(float(row.get("max_future_high_return_2_5d") or 0.0) for row in closed_rows) / len(closed_rows)) if closed_rows else None
    beta_tradeable_rate = _round_or_none(sum(1 for row in rows if row.get("beta_tradeable")) / len(rows)) if rows else None
    return {
        "row_count": len(rows),
        "closed_cycle_count": len(closed_rows),
        "hit_rate_15pct": hit_rate,
        "executable_hit_rate_15pct": executable_hit_rate,
        "raw_executable_hit_rate_gap": _round_or_none(float(hit_rate or 0.0) - float(executable_hit_rate or 0.0)) if hit_rate is not None and executable_hit_rate is not None else None,
        "mean_max_future_high_return_2_5d": mean_max_return,
        "beta_tradeable_rate": beta_tradeable_rate,
        "unique_report_dir_count": len({str(row.get("report_dir_name") or "") for row in closed_rows}),
        "has_min_closed_cycle_count": len(closed_rows) >= min_closed_cycle_count,
    }


def _top_fraction_rows(rows: list[dict[str, Any]], factor_name: str, fraction: float) -> list[dict[str, Any]]:
    populated = [row for row in rows if _safe_float(row.get(factor_name)) is not None]
    if not populated:
        return []
    limit = max(1, ceil(len(populated) * fraction))
    return sorted(populated, key=lambda row: float(_safe_float(row.get(factor_name)) or 0.0), reverse=True)[:limit]


def _rows_with_min_value(rows: list[dict[str, Any]], factor_name: str, minimum: float) -> list[dict[str, Any]]:
    return [row for row in rows if (_safe_float(row.get(factor_name)) or 0.0) >= minimum]


def _rows_with_gap_le(rows: list[dict[str, Any]], maximum_gap: float) -> list[dict[str, Any]]:
    return [row for row in rows if (_safe_float(row.get("next_open_return")) is not None and float(_safe_float(row.get("next_open_return")) or 0.0) <= maximum_gap)]


def _rows_with_decision(rows: list[dict[str, Any]], decisions: set[str]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("decision") or "") in decisions]


def _decide_slice(slice_summary: dict[str, Any], baseline_summary: dict[str, Any], *, min_closed_cycle_count: int) -> str:
    closed_count = int(slice_summary.get("closed_cycle_count") or 0)
    hit_rate = float(slice_summary.get("hit_rate_15pct") or 0.0)
    mean_return = float(slice_summary.get("mean_max_future_high_return_2_5d") or 0.0)
    beta_tradeable_rate = float(slice_summary.get("beta_tradeable_rate") or 0.0)
    uplift = float(slice_summary.get("hit_rate_uplift_vs_baseline") or 0.0)
    upgrade_min_count = max(3, min_closed_cycle_count)
    if closed_count >= upgrade_min_count and hit_rate >= 0.55 and mean_return >= 0.15 and beta_tradeable_rate >= 0.70:
        return "upgrade"
    if closed_count >= min_closed_cycle_count and uplift > 0.0:
        return "observe"
    if closed_count == 0 or hit_rate < float(baseline_summary.get("hit_rate_15pct") or 0.0):
        return "downgrade"
    return "hold"


def _slice_record(
    *,
    slice_id: str,
    rows: list[dict[str, Any]],
    baseline_summary: dict[str, Any],
    min_closed_cycle_count: int,
) -> dict[str, Any]:
    summary = _summary(rows, min_closed_cycle_count=min_closed_cycle_count)
    baseline_hit_rate = baseline_summary.get("hit_rate_15pct")
    baseline_mean_return = baseline_summary.get("mean_max_future_high_return_2_5d")
    summary.update(
        {
            "slice_id": slice_id,
            "hit_rate_uplift_vs_baseline": _round_or_none(float(summary.get("hit_rate_15pct") or 0.0) - float(baseline_hit_rate or 0.0)) if baseline_hit_rate is not None and summary.get("hit_rate_15pct") is not None else None,
            "mean_return_uplift_vs_baseline": _round_or_none(float(summary.get("mean_max_future_high_return_2_5d") or 0.0) - float(baseline_mean_return or 0.0)) if baseline_mean_return is not None and summary.get("mean_max_future_high_return_2_5d") is not None else None,
        }
    )
    summary["decision"] = _decide_slice(summary, baseline_summary, min_closed_cycle_count=min_closed_cycle_count)
    return summary


def _build_trend_slices(rows: list[dict[str, Any]], baseline_summary: dict[str, Any], *, min_closed_cycle_count: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for pct in (0.40, 0.30, 0.20):
        top_rows = _top_fraction_rows(rows, "trend_acceleration", pct)
        pct_label = int(pct * 100)
        records.append(_slice_record(slice_id=f"trend_acceleration_top_{pct_label}pct", rows=top_rows, baseline_summary=baseline_summary, min_closed_cycle_count=min_closed_cycle_count))
    top_40 = _top_fraction_rows(rows, "trend_acceleration", 0.40)
    top_20 = _top_fraction_rows(rows, "trend_acceleration", 0.20)
    records.append(_slice_record(slice_id="trend_acceleration_top_40pct_close_strength_confirmed", rows=_rows_with_min_value(top_40, "close_strength", 0.60), baseline_summary=baseline_summary, min_closed_cycle_count=min_closed_cycle_count))
    records.append(_slice_record(slice_id="trend_acceleration_top_40pct_volume_quality_confirmed", rows=_rows_with_min_value(top_40, "volume_expansion_quality", 0.55), baseline_summary=baseline_summary, min_closed_cycle_count=min_closed_cycle_count))
    records.append(_slice_record(slice_id="trend_acceleration_top_40pct_gap_le_3pct", rows=_rows_with_gap_le(top_40, 0.03), baseline_summary=baseline_summary, min_closed_cycle_count=min_closed_cycle_count))
    top_20_selected = _rows_with_decision(top_20, {"selected"})
    records.append(_slice_record(slice_id="trend_acceleration_top_20pct_gap_le_3pct", rows=_rows_with_gap_le(top_20, 0.03), baseline_summary=baseline_summary, min_closed_cycle_count=min_closed_cycle_count))
    records.append(_slice_record(slice_id="trend_acceleration_top_20pct_selected_only", rows=top_20_selected, baseline_summary=baseline_summary, min_closed_cycle_count=min_closed_cycle_count))
    records.append(_slice_record(slice_id="trend_acceleration_top_20pct_selected_gap_le_3pct", rows=_rows_with_gap_le(top_20_selected, 0.03), baseline_summary=baseline_summary, min_closed_cycle_count=min_closed_cycle_count))
    return records


def _build_breakout_slices(rows: list[dict[str, Any]], baseline_summary: dict[str, Any], *, min_closed_cycle_count: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for pct in (0.40, 0.30, 0.20):
        top_rows = _top_fraction_rows(rows, "breakout_freshness", pct)
        pct_label = int(pct * 100)
        records.append(_slice_record(slice_id=f"breakout_freshness_top_{pct_label}pct", rows=top_rows, baseline_summary=baseline_summary, min_closed_cycle_count=min_closed_cycle_count))
    top_40 = _top_fraction_rows(rows, "breakout_freshness", 0.40)
    records.append(_slice_record(slice_id="breakout_freshness_top_40pct_volume_quality_confirmed", rows=_rows_with_min_value(top_40, "volume_expansion_quality", 0.55), baseline_summary=baseline_summary, min_closed_cycle_count=min_closed_cycle_count))
    records.append(_slice_record(slice_id="breakout_freshness_top_40pct_close_strength_confirmed", rows=_rows_with_min_value(top_40, "close_strength", 0.60), baseline_summary=baseline_summary, min_closed_cycle_count=min_closed_cycle_count))
    records.append(_slice_record(slice_id="breakout_freshness_top_40pct_gap_le_3pct", rows=_rows_with_gap_le(top_40, 0.03), baseline_summary=baseline_summary, min_closed_cycle_count=min_closed_cycle_count))
    return records


def _scope_decision(drilldown_boards: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    observed = [row for rows in drilldown_boards.values() for row in rows if row.get("decision") in {"upgrade", "observe"}]
    upgraded = [row for rows in drilldown_boards.values() for row in rows if row.get("decision") == "upgrade"]
    if upgraded:
        return {"next_step": "promote_best_slice_to_candidate_review", "reason": "at_least_one_slice_met_upgrade_gate"}
    if observed:
        return {"next_step": "continue_scoped_drilldown", "reason": "at_least_one_slice_has_positive_uplift_but_needs_more_evidence"}
    return {"next_step": "return_to_prototype_definition", "reason": "no_scoped_slice_showed_positive_uplift"}


def analyze_btst_5d_15pct_trend_breakout_drilldown(
    reports_root: str | Path,
    *,
    min_closed_cycle_count: int = 3,
    boundary_quarantine_artifact: str | Path | None = None,
    local_price_only: bool = False,
    report_name_contains: str = DEFAULT_REPORT_NAME_CONTAINS,
) -> dict[str, Any]:
    resolved_root = Path(reports_root).expanduser().resolve()
    rows = _collect_round1_rows(resolved_root, boundary_quarantine_artifact=boundary_quarantine_artifact, local_price_only=local_price_only, report_name_contains=report_name_contains)
    scoped_rows = [row for row in rows if row.get("event_prototype") in SCOPED_PROTOTYPES]
    excluded_counts = Counter(str(row.get("event_prototype") or "unclassified") for row in rows if row.get("event_prototype") not in SCOPED_PROTOTYPES)

    prototype_rows = {prototype: [row for row in scoped_rows if row.get("event_prototype") == prototype] for prototype in SCOPED_PROTOTYPES}
    prototype_baselines = {prototype: _summary(prototype_rows[prototype], min_closed_cycle_count=min_closed_cycle_count) for prototype in SCOPED_PROTOTYPES}
    drilldown_boards = {
        "trend_continuation": _build_trend_slices(prototype_rows["trend_continuation"], prototype_baselines["trend_continuation"], min_closed_cycle_count=min_closed_cycle_count),
        "breakout_ignition": _build_breakout_slices(prototype_rows["breakout_ignition"], prototype_baselines["breakout_ignition"], min_closed_cycle_count=min_closed_cycle_count),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        "report_name_contains": report_name_contains,
        "scope": {
            "included_event_prototypes": list(SCOPED_PROTOTYPES),
            "frozen_out": ["volume_quality_release", "unclassified", "boundary_quarantine", "full_market_feature_sweep"],
        },
        "row_count": len(rows),
        "scoped_row_count": len(scoped_rows),
        "local_price_only": local_price_only,
        "outcome_source_counts": _count_outcome_sources(rows),
        "data_status_counts": _count_data_statuses(rows),
        "local_price_coverage": _local_price_coverage(rows),
        "excluded_event_prototype_counts": dict(sorted(excluded_counts.items())),
        "prototype_baselines": prototype_baselines,
        "drilldown_boards": drilldown_boards,
        "scope_decision": _scope_decision(drilldown_boards),
    }


def render_btst_5d_15pct_trend_breakout_drilldown_markdown(analysis: dict[str, Any]) -> str:
    lines = ["# BTST 5D / 15% Trend-Breakout Drilldown", ""]
    lines.append(f"- row_count: {analysis.get('row_count')}")
    lines.append(f"- scoped_row_count: {analysis.get('scoped_row_count')}")
    lines.append(f"- local_price_only: {analysis.get('local_price_only')}")
    lines.append(f"- report_name_contains: {analysis.get('report_name_contains')!r}")
    lines.append(f"- scope_decision: {dict(analysis.get('scope_decision') or {}).get('next_step')}")
    lines.append("")
    lines.append("## Local Price Coverage")
    coverage = dict(analysis.get("local_price_coverage") or {})
    lines.append(f"- total_rows: {coverage.get('total_rows')}")
    lines.append(f"- local_outcome_count: {coverage.get('local_outcome_count')}")
    lines.append(f"- missing_count: {coverage.get('missing_count')}")
    lines.append(f"- coverage_rate: {coverage.get('coverage_rate')}")
    lines.append("- missing_reason_counts:")
    for label, count in dict(coverage.get("missing_reason_counts") or {}).items():
        lines.append(f"  - {label}: {count}")
    lines.append("")
    lines.append("## Prototype Baselines")
    for prototype, summary in dict(analysis.get("prototype_baselines") or {}).items():
        lines.append(f"- {prototype}: rows={summary.get('row_count')}, closed={summary.get('closed_cycle_count')}, hit_rate_15pct={summary.get('hit_rate_15pct')}, mean_max_return={summary.get('mean_max_future_high_return_2_5d')}, beta_tradeable_rate={summary.get('beta_tradeable_rate')}")
    lines.append("")
    lines.append("## Drilldown Boards")
    for prototype, rows in dict(analysis.get("drilldown_boards") or {}).items():
        lines.append(f"### {prototype}")
        for row in list(rows or []):
            lines.append(f"- {row.get('slice_id')}: rows={row.get('row_count')}, closed={row.get('closed_cycle_count')}, hit_rate_15pct={row.get('hit_rate_15pct')}, uplift={row.get('hit_rate_uplift_vs_baseline')}, mean_max_return={row.get('mean_max_future_high_return_2_5d')}, beta_tradeable_rate={row.get('beta_tradeable_rate')}, decision={row.get('decision')}")
        lines.append("")
    lines.append("## Excluded Event Prototype Counts")
    excluded = dict(analysis.get("excluded_event_prototype_counts") or {})
    if not excluded:
        lines.append("- none")
    for label, count in excluded.items():
        lines.append(f"- {label}: {count}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a scoped BTST 5D/+15% trend/breakout drilldown report.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument("--min-closed-cycle-count", type=int, default=3)
    parser.add_argument("--boundary-quarantine-artifact", default=str(DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT))
    parser.add_argument("--local-price-only", action="store_true", help="Use only report-local data_snapshots prices and never call external price providers.")
    parser.add_argument("--report-name-contains", default=DEFAULT_REPORT_NAME_CONTAINS, help="Only scan report directories whose name contains this text. Use an empty string to scan all report dirs.")
    args = parser.parse_args()

    analysis = analyze_btst_5d_15pct_trend_breakout_drilldown(
        args.reports_root,
        min_closed_cycle_count=args.min_closed_cycle_count,
        boundary_quarantine_artifact=args.boundary_quarantine_artifact,
        local_price_only=args.local_price_only,
        report_name_contains=args.report_name_contains,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_5d_15pct_trend_breakout_drilldown_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
