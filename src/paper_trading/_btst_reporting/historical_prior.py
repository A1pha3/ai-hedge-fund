"""Historical prior computation and enrichment for BTST brief entries.

This module encapsulates all logic related to:
- Normalizing price frames and extracting next-day outcomes
- Building historical prior summaries from opportunity/watch-candidate rows
- Enriching BTST brief entry groups with historical prior data
- Postprocessing enriched groups (demotion, partition, sorting)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.paper_trading.btst_reporting_utils import (
    OPPORTUNITY_POOL_HISTORICAL_LOOKBACK_REPORTS,
    OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD,
    OPPORTUNITY_POOL_HISTORICAL_SAME_TICKER_MIN_SAMPLES,
    _as_float,
    _catalyst_bucket_label,
    _format_float,
    _historical_execution_entry_sort_key,
    _load_json,
    _mean_or_none,
    _normalize_trade_date,
    _opportunity_pool_execution_sort_key,
    _research_historical_entry_sort_key,
    _round_or_none,
    _score_bucket_label,
)
from src.tools.akshare_api import get_prices_robust
from src.tools.api import get_price_data, prices_to_df
from src.paper_trading._btst_reporting.classifiers import (
    _classify_historical_prior,
    _classify_execution_quality_prior,
)
from src.paper_trading._btst_reporting.entry_builders import (
    _iter_selection_snapshot_paths,
    _discover_recent_historical_report_dirs,
    _extract_short_trade_entry,
    _extract_short_trade_opportunity_entry,
    _extract_research_upside_radar_entry,
    _extract_catalyst_theme_entry,
    _merge_entry_historical_prior,
    _reclassify_selected_execution_quality_entries,
)
from src.paper_trading._btst_reporting.entry_transforms import (
    _apply_execution_quality_entry_mode,
)
from src.paper_trading._btst_reporting.pool_classifiers import (
    _demote_weak_near_miss_entries,
    _partition_opportunity_pool_entries,
)


# ---------------------------------------------------------------------------
# Price helpers
# ---------------------------------------------------------------------------


def _normalize_price_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    normalized = frame.copy()
    if not isinstance(normalized.index, pd.DatetimeIndex):
        normalized.index = pd.to_datetime(normalized.index)
    normalized = normalized.sort_index()
    normalized.columns = [str(column).lower() for column in normalized.columns]
    return normalized


def _extract_next_day_outcome(
    ticker: str, trade_date: str, price_cache: dict[tuple[str, str], pd.DataFrame]
) -> dict[str, Any]:
    cache_key = (ticker, trade_date)
    frame = price_cache.get(cache_key)
    if frame is None:
        end_date = (pd.Timestamp(trade_date) + pd.Timedelta(days=10)).strftime(
            "%Y-%m-%d"
        )
        try:
            frame = _normalize_price_frame(
                prices_to_df(
                    get_prices_robust(
                        ticker, trade_date, end_date, use_mock_on_fail=False
                    )
                )
            )
        except Exception:
            try:
                frame = _normalize_price_frame(
                    get_price_data(ticker, trade_date, end_date)
                )
            except Exception:
                frame = pd.DataFrame()
        price_cache[cache_key] = frame
    if frame.empty:
        return {"data_status": "missing_price_frame"}

    trade_ts = pd.Timestamp(trade_date)
    same_day = frame.loc[frame.index.normalize() == trade_ts.normalize()]
    next_day = frame.loc[frame.index.normalize() > trade_ts.normalize()]
    if same_day.empty:
        return {"data_status": "missing_trade_day_bar"}
    if next_day.empty:
        return {"data_status": "missing_next_trade_day_bar"}

    trade_row = same_day.iloc[0]
    next_row = next_day.iloc[0]
    trade_close = _as_float(trade_row.get("close"))
    next_open = _as_float(next_row.get("open"))
    next_high = _as_float(next_row.get("high"))
    next_close = _as_float(next_row.get("close"))
    if trade_close <= 0 or next_open <= 0 or next_high <= 0 or next_close <= 0:
        return {"data_status": "incomplete_price_bar"}

    return {
        "data_status": "ok",
        "next_trade_date": next_day.index[0].strftime("%Y-%m-%d"),
        "trade_close": round(trade_close, 4),
        "next_open": round(next_open, 4),
        "next_high": round(next_high, 4),
        "next_close": round(next_close, 4),
        "next_open_return": round((next_open / trade_close) - 1.0, 4),
        "next_high_return": round((next_high / trade_close) - 1.0, 4),
        "next_close_return": round((next_close / trade_close) - 1.0, 4),
        "next_open_to_close_return": round((next_close / next_open) - 1.0, 4),
    }


# ---------------------------------------------------------------------------
# Watch-candidate decoration & historical row collection
# ---------------------------------------------------------------------------


def _decorate_watch_candidate_history_entry(
    entry: dict[str, Any], family: str
) -> dict[str, Any]:
    metrics = dict(entry.get("metrics") or {})
    return {
        **entry,
        "watch_candidate_family": family,
        "score_bucket": _score_bucket_label(entry.get("score_target")),
        "catalyst_bucket": _catalyst_bucket_label(metrics),
    }


def _collect_historical_opportunity_rows(
    report_dir: Path, trade_date: str | None
) -> dict[str, Any]:
    historical_report_dirs = [
        report_dir,
        *_discover_recent_historical_report_dirs(report_dir, trade_date),
    ]
    rows: list[dict[str, Any]] = []
    contributing_reports: set[str] = set()

    for historical_report_dir in historical_report_dirs:
        for snapshot_path in _iter_selection_snapshot_paths(historical_report_dir):
            snapshot = _load_json(snapshot_path)
            snapshot_trade_date = _normalize_trade_date(
                snapshot.get("trade_date") or snapshot_path.parent.name
            )
            if trade_date and snapshot_trade_date and snapshot_trade_date >= trade_date:
                continue
            selection_targets = snapshot.get("selection_targets") or {}
            for selection_entry in selection_targets.values():
                opportunity_entry = _extract_short_trade_opportunity_entry(
                    dict(selection_entry)
                )
                if opportunity_entry is None:
                    continue
                rows.append(
                    {
                        **opportunity_entry,
                        "trade_date": snapshot_trade_date,
                        "report_dir": str(historical_report_dir),
                        "snapshot_path": str(snapshot_path),
                    }
                )
                contributing_reports.add(str(historical_report_dir))

    rows.sort(
        key=lambda row: (row.get("trade_date") or "", row.get("ticker") or ""),
        reverse=True,
    )
    return {
        "rows": rows,
        "historical_report_dirs": historical_report_dirs,
        "contributing_report_count": len(contributing_reports),
    }


def _collect_historical_watch_candidate_rows(
    report_dir: Path, trade_date: str | None
) -> dict[str, Any]:
    historical_report_dirs = [
        report_dir,
        *_discover_recent_historical_report_dirs(report_dir, trade_date),
    ]
    rows: list[dict[str, Any]] = []
    contributing_reports: set[str] = set()
    family_counts = {
        "selected": 0,
        "near_miss": 0,
        "opportunity_pool": 0,
        "research_upside_radar": 0,
        "catalyst_theme": 0,
    }

    for historical_report_dir in historical_report_dirs:
        for snapshot_path in _iter_selection_snapshot_paths(historical_report_dir):
            snapshot = _load_json(snapshot_path)
            snapshot_trade_date = _normalize_trade_date(
                snapshot.get("trade_date") or snapshot_path.parent.name
            )
            if trade_date and snapshot_trade_date and snapshot_trade_date >= trade_date:
                continue
            _collect_watch_candidate_rows_from_selection_targets(
                rows=rows,
                family_counts=family_counts,
                contributing_reports=contributing_reports,
                historical_report_dir=historical_report_dir,
                snapshot_path=snapshot_path,
                snapshot_trade_date=snapshot_trade_date,
                selection_targets=snapshot.get("selection_targets") or {},
            )
            _collect_watch_candidate_rows_from_catalyst_entries(
                rows=rows,
                family_counts=family_counts,
                contributing_reports=contributing_reports,
                historical_report_dir=historical_report_dir,
                snapshot_path=snapshot_path,
                snapshot_trade_date=snapshot_trade_date,
                catalyst_entries=snapshot.get("catalyst_theme_candidates") or [],
            )

    rows.sort(
        key=lambda row: (row.get("trade_date") or "", row.get("ticker") or ""),
        reverse=True,
    )
    return {
        "rows": rows,
        "historical_report_dirs": historical_report_dirs,
        "contributing_report_count": len(contributing_reports),
        "family_counts": family_counts,
    }


def _collect_watch_candidate_rows_from_selection_targets(
    *,
    rows: list[dict[str, Any]],
    family_counts: dict[str, int],
    contributing_reports: set[str],
    historical_report_dir: Path,
    snapshot_path: Path,
    snapshot_trade_date: str | None,
    selection_targets: dict[str, Any],
) -> None:
    history_context = {
        "trade_date": snapshot_trade_date,
        "report_dir": str(historical_report_dir),
        "snapshot_path": str(snapshot_path),
    }
    for selection_entry in selection_targets.values():
        normalized_selection_entry = dict(selection_entry)
        _append_watch_candidate_row(
            rows=rows,
            family_counts=family_counts,
            contributing_reports=contributing_reports,
            report_dir=str(historical_report_dir),
            family=str(
                (_extract_short_trade_entry(normalized_selection_entry) or {}).get(
                    "decision"
                )
                or ""
            ),
            entry=_extract_short_trade_entry(normalized_selection_entry),
            history_context=history_context,
        )
        _append_watch_candidate_row(
            rows=rows,
            family_counts=family_counts,
            contributing_reports=contributing_reports,
            report_dir=str(historical_report_dir),
            family="opportunity_pool",
            entry=_extract_short_trade_opportunity_entry(normalized_selection_entry),
            history_context=history_context,
        )
        _append_watch_candidate_row(
            rows=rows,
            family_counts=family_counts,
            contributing_reports=contributing_reports,
            report_dir=str(historical_report_dir),
            family="research_upside_radar",
            entry=_extract_research_upside_radar_entry(normalized_selection_entry),
            history_context=history_context,
        )


def _collect_watch_candidate_rows_from_catalyst_entries(
    *,
    rows: list[dict[str, Any]],
    family_counts: dict[str, int],
    contributing_reports: set[str],
    historical_report_dir: Path,
    snapshot_path: Path,
    snapshot_trade_date: str | None,
    catalyst_entries: list[dict[str, Any]],
) -> None:
    history_context = {
        "trade_date": snapshot_trade_date,
        "report_dir": str(historical_report_dir),
        "snapshot_path": str(snapshot_path),
    }
    for catalyst_entry in catalyst_entries:
        _append_watch_candidate_row(
            rows=rows,
            family_counts=family_counts,
            contributing_reports=contributing_reports,
            report_dir=str(historical_report_dir),
            family="catalyst_theme",
            entry=_extract_catalyst_theme_entry(dict(catalyst_entry)),
            history_context=history_context,
        )


def _append_watch_candidate_row(
    *,
    rows: list[dict[str, Any]],
    family_counts: dict[str, int],
    contributing_reports: set[str],
    report_dir: str,
    family: str,
    entry: dict[str, Any] | None,
    history_context: dict[str, Any],
) -> None:
    if entry is None:
        return
    rows.append(
        {**_decorate_watch_candidate_history_entry(entry, family), **history_context}
    )
    family_counts[family] = int(family_counts.get(family) or 0) + 1
    contributing_reports.add(report_dir)


def _build_historical_prior_summary(
    *,
    applied_scope: str,
    evaluable_count: int,
    hit_rate: float | None,
    close_positive_rate: float | None,
    scope_label: str | None = None,
) -> str | None:
    if evaluable_count <= 0:
        return None
    resolved_scope_label = scope_label or (
        "同票" if applied_scope == "same_ticker" else "同源"
    )
    threshold_pct = OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD * 100.0
    return (
        f"{resolved_scope_label}历史 {evaluable_count} 例，next_high>={threshold_pct:.1f}% 命中率={_format_float(hit_rate)}, "
        f"next_close 正收益率={_format_float(close_positive_rate)}。"
    )


# ---------------------------------------------------------------------------
# Historical opportunity summarization
# ---------------------------------------------------------------------------


def _summarize_historical_opportunity_rows(
    rows: list[dict[str, Any]],
    price_cache: dict[tuple[str, str], pd.DataFrame],
) -> dict[str, Any]:
    summary_state = _build_empty_historical_opportunity_summary_state()

    for row in rows:
        evaluated_row = _evaluate_historical_opportunity_row(row, price_cache)
        if evaluated_row is None:
            continue
        _accumulate_historical_opportunity_summary(summary_state, evaluated_row)

    next_high_hit_rate, next_close_positive_rate = (
        _compute_historical_opportunity_rates(
            summary_state["evaluated_rows"], summary_state
        )
    )
    return _build_historical_opportunity_summary_payload(
        rows=rows,
        evaluated_rows=summary_state["evaluated_rows"],
        next_open_values=summary_state["next_open_values"],
        next_high_values=summary_state["next_high_values"],
        next_close_values=summary_state["next_close_values"],
        next_open_to_close_values=summary_state["next_open_to_close_values"],
        next_high_hit_rate=next_high_hit_rate,
        next_close_positive_rate=next_close_positive_rate,
    )


def _build_empty_historical_opportunity_summary_state() -> dict[str, Any]:
    return {
        "evaluated_rows": [],
        "next_open_values": [],
        "next_high_values": [],
        "next_close_values": [],
        "next_open_to_close_values": [],
        "hit_count": 0,
        "positive_close_count": 0,
    }


def _accumulate_historical_opportunity_summary(
    summary_state: dict[str, Any], evaluated_row: dict[str, Any]
) -> None:
    next_open_return = evaluated_row.get("next_open_return")
    next_high_return = evaluated_row.get("next_high_return")
    next_close_return = evaluated_row.get("next_close_return")
    next_open_to_close_return = evaluated_row.get("next_open_to_close_return")
    if next_open_return is not None:
        summary_state["next_open_values"].append(next_open_return)
    if next_high_return is not None:
        summary_state["next_high_values"].append(next_high_return)
        if next_high_return >= OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD:
            summary_state["hit_count"] += 1
    if next_close_return is not None:
        summary_state["next_close_values"].append(next_close_return)
        if next_close_return > 0:
            summary_state["positive_close_count"] += 1
    if next_open_to_close_return is not None:
        summary_state["next_open_to_close_values"].append(next_open_to_close_return)
    summary_state["evaluated_rows"].append(evaluated_row)


def _compute_historical_opportunity_rates(
    evaluated_rows: list[dict[str, Any]],
    summary_state: dict[str, Any],
) -> tuple[float | None, float | None]:
    evaluable_count = len(evaluated_rows)
    next_high_hit_rate = (
        round(summary_state["hit_count"] / evaluable_count, 4)
        if evaluable_count
        else None
    )
    next_close_positive_rate = (
        round(summary_state["positive_close_count"] / evaluable_count, 4)
        if evaluable_count
        else None
    )
    return next_high_hit_rate, next_close_positive_rate


def _evaluate_historical_opportunity_row(
    row: dict[str, Any],
    price_cache: dict[tuple[str, str], pd.DataFrame],
) -> dict[str, Any] | None:
    trade_date = str(row.get("trade_date") or "")
    ticker = str(row.get("ticker") or "")
    if not trade_date or not ticker:
        return None
    outcome = _extract_next_day_outcome(ticker, trade_date, price_cache)
    if outcome.get("data_status") != "ok":
        return None
    return {
        "trade_date": trade_date,
        "ticker": ticker,
        "candidate_source": row.get("candidate_source"),
        "score_target": _round_or_none(row.get("score_target")),
        "next_open_return": _round_or_none(outcome.get("next_open_return")),
        "next_high_return": _round_or_none(outcome.get("next_high_return")),
        "next_close_return": _round_or_none(outcome.get("next_close_return")),
        "next_open_to_close_return": _round_or_none(
            outcome.get("next_open_to_close_return")
        ),
    }


def _build_historical_opportunity_summary_payload(
    *,
    rows: list[dict[str, Any]],
    evaluated_rows: list[dict[str, Any]],
    next_open_values: list[float],
    next_high_values: list[float],
    next_close_values: list[float],
    next_open_to_close_values: list[float],
    next_high_hit_rate: float | None,
    next_close_positive_rate: float | None,
) -> dict[str, Any]:
    return {
        "sample_count": len(rows),
        "evaluable_count": len(evaluated_rows),
        "next_high_hit_threshold": OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD,
        "next_open_return_mean": _mean_or_none(next_open_values),
        "next_high_hit_rate_at_threshold": next_high_hit_rate,
        "next_close_positive_rate": next_close_positive_rate,
        "next_high_return_mean": _mean_or_none(next_high_values),
        "next_close_return_mean": _mean_or_none(next_close_values),
        "next_open_to_close_return_mean": _mean_or_none(next_open_to_close_values),
        "recent_examples": evaluated_rows[:3],
    }


# ---------------------------------------------------------------------------
# Opportunity pool historical prior
# ---------------------------------------------------------------------------


def _build_opportunity_pool_historical_prior(
    entry: dict[str, Any],
    historical_rows: list[dict[str, Any]],
    price_cache: dict[tuple[str, str], pd.DataFrame],
) -> dict[str, Any]:
    same_ticker_rows = [
        row for row in historical_rows if row.get("ticker") == entry.get("ticker")
    ]
    same_source_rows = [
        row
        for row in historical_rows
        if row.get("candidate_source") == entry.get("candidate_source")
    ]
    applied_scope, applied_rows = _resolve_opportunity_pool_historical_scope(
        same_ticker_rows, same_source_rows
    )

    stats = _summarize_historical_opportunity_rows(applied_rows, price_cache)
    bias_label, monitor_priority = _classify_historical_prior(
        stats.get("next_high_hit_rate_at_threshold"),
        stats.get("next_close_positive_rate"),
        int(stats.get("evaluable_count") or 0),
    )
    execution_quality = _classify_execution_quality_prior(
        stats.get("next_open_return_mean"),
        stats.get("next_open_to_close_return_mean"),
        stats.get("next_high_return_mean"),
        stats.get("next_close_return_mean"),
        stats.get("next_high_hit_rate_at_threshold"),
        stats.get("next_close_positive_rate"),
        int(stats.get("evaluable_count") or 0),
    )
    return _build_opportunity_pool_historical_prior_payload(
        same_ticker_rows=same_ticker_rows,
        same_source_rows=same_source_rows,
        applied_scope=applied_scope,
        stats=stats,
        bias_label=bias_label,
        monitor_priority=monitor_priority,
        execution_quality=execution_quality,
    )


def _resolve_opportunity_pool_historical_scope(
    same_ticker_rows: list[dict[str, Any]],
    same_source_rows: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    if len(same_ticker_rows) >= OPPORTUNITY_POOL_HISTORICAL_SAME_TICKER_MIN_SAMPLES:
        return "same_ticker", same_ticker_rows
    if same_source_rows:
        return "candidate_source", same_source_rows
    if same_ticker_rows:
        return "same_ticker", same_ticker_rows
    return "none", []


def _build_opportunity_pool_historical_prior_payload(
    *,
    same_ticker_rows: list[dict[str, Any]],
    same_source_rows: list[dict[str, Any]],
    applied_scope: str,
    stats: dict[str, Any],
    bias_label: str,
    monitor_priority: str,
    execution_quality: dict[str, str],
) -> dict[str, Any]:
    return {
        "same_ticker_sample_count": len(same_ticker_rows),
        "same_candidate_source_sample_count": len(same_source_rows),
        "applied_scope": applied_scope,
        **stats,
        "bias_label": bias_label,
        "monitor_priority": monitor_priority,
        **execution_quality,
        "summary": _build_historical_prior_summary(
            applied_scope=applied_scope,
            evaluable_count=int(stats.get("evaluable_count") or 0),
            hit_rate=stats.get("next_high_hit_rate_at_threshold"),
            close_positive_rate=stats.get("next_close_positive_rate"),
        ),
    }


# ---------------------------------------------------------------------------
# Watch-candidate historical prior
# ---------------------------------------------------------------------------


def _build_watch_candidate_historical_prior(
    entry: dict[str, Any],
    historical_rows: list[dict[str, Any]],
    price_cache: dict[tuple[str, str], pd.DataFrame],
    *,
    family: str,
) -> dict[str, Any]:
    decorated_entry = _decorate_watch_candidate_history_entry(entry, family)
    row_buckets = _build_watch_candidate_historical_row_buckets(
        historical_rows=historical_rows,
        decorated_entry=decorated_entry,
        family=family,
    )
    applied_scope, scope_label, applied_rows = _resolve_watch_candidate_scope_selection(
        row_buckets
    )

    stats = _summarize_historical_opportunity_rows(applied_rows, price_cache)
    bias_label, monitor_priority = _classify_historical_prior(
        stats.get("next_high_hit_rate_at_threshold"),
        stats.get("next_close_positive_rate"),
        int(stats.get("evaluable_count") or 0),
    )
    execution_quality = _classify_execution_quality_prior(
        stats.get("next_open_return_mean"),
        stats.get("next_open_to_close_return_mean"),
        stats.get("next_high_return_mean"),
        stats.get("next_close_return_mean"),
        stats.get("next_high_hit_rate_at_threshold"),
        stats.get("next_close_positive_rate"),
        int(stats.get("evaluable_count") or 0),
    )
    return _build_watch_candidate_historical_prior_payload(
        family=family,
        decorated_entry=decorated_entry,
        row_buckets=row_buckets,
        applied_scope=applied_scope,
        stats=stats,
        bias_label=bias_label,
        monitor_priority=monitor_priority,
        execution_quality=execution_quality,
        scope_label=scope_label,
    )


def _build_watch_candidate_historical_prior_payload(
    *,
    family: str,
    decorated_entry: dict[str, Any],
    row_buckets: dict[str, list[dict[str, Any]]],
    applied_scope: str,
    stats: dict[str, Any],
    bias_label: str,
    monitor_priority: str,
    execution_quality: dict[str, str],
    scope_label: str | None,
) -> dict[str, Any]:
    return {
        "watch_candidate_family": family,
        "score_bucket": decorated_entry.get("score_bucket"),
        "catalyst_bucket": decorated_entry.get("catalyst_bucket"),
        "same_ticker_sample_count": len(row_buckets["same_ticker"]),
        "same_family_sample_count": len(row_buckets["same_family"]),
        "same_candidate_source_sample_count": len(row_buckets["same_source"]),
        "same_family_source_sample_count": len(row_buckets["same_family_source"]),
        "same_family_source_score_catalyst_sample_count": len(
            row_buckets["same_family_source_score_catalyst"]
        ),
        "same_source_score_sample_count": len(row_buckets["same_source_score"]),
        "applied_scope": applied_scope,
        **stats,
        "bias_label": bias_label,
        "monitor_priority": monitor_priority,
        **execution_quality,
        "summary": _build_historical_prior_summary(
            applied_scope=applied_scope,
            evaluable_count=int(stats.get("evaluable_count") or 0),
            hit_rate=stats.get("next_high_hit_rate_at_threshold"),
            close_positive_rate=stats.get("next_close_positive_rate"),
            scope_label=scope_label,
        ),
    }


def _build_watch_candidate_historical_row_buckets(
    *,
    historical_rows: list[dict[str, Any]],
    decorated_entry: dict[str, Any],
    family: str,
) -> dict[str, list[dict[str, Any]]]:
    same_ticker_rows = [
        row
        for row in historical_rows
        if row.get("ticker") == decorated_entry.get("ticker")
    ]
    same_family_rows = [
        row for row in historical_rows if row.get("watch_candidate_family") == family
    ]
    same_source_rows = [
        row
        for row in historical_rows
        if row.get("candidate_source") == decorated_entry.get("candidate_source")
    ]
    same_family_source_rows = [
        row
        for row in same_family_rows
        if row.get("candidate_source") == decorated_entry.get("candidate_source")
    ]
    same_family_source_score_catalyst_rows = [
        row
        for row in same_family_source_rows
        if row.get("score_bucket") == decorated_entry.get("score_bucket")
        and row.get("catalyst_bucket") == decorated_entry.get("catalyst_bucket")
    ]
    same_source_score_rows = [
        row
        for row in same_source_rows
        if row.get("score_bucket") == decorated_entry.get("score_bucket")
    ]
    return {
        "same_ticker": same_ticker_rows,
        "same_family": same_family_rows,
        "same_source": same_source_rows,
        "same_family_source": same_family_source_rows,
        "same_family_source_score_catalyst": same_family_source_score_catalyst_rows,
        "same_source_score": same_source_score_rows,
    }


def _resolve_watch_candidate_scope_selection(
    row_buckets: dict[str, list[dict[str, Any]]],
) -> tuple[str, str | None, list[dict[str, Any]]]:
    scope_candidates = [
        (
            "same_ticker",
            "同票",
            row_buckets["same_ticker"]
            if len(row_buckets["same_ticker"])
            >= OPPORTUNITY_POOL_HISTORICAL_SAME_TICKER_MIN_SAMPLES
            else [],
        ),
        (
            "family_source_score_catalyst",
            "同层同源同分桶",
            row_buckets["same_family_source_score_catalyst"],
        ),
        ("family_source", "同层同源", row_buckets["same_family_source"]),
        ("source_score", "同源同分桶", row_buckets["same_source_score"]),
        ("candidate_source", "同源", row_buckets["same_source"]),
        ("same_ticker", "同票", row_buckets["same_ticker"]),
    ]
    for scope_name, label, scope_rows in scope_candidates:
        if scope_rows:
            return scope_name, label, scope_rows
    return "none", None, []


# ---------------------------------------------------------------------------
# Excluded research entry
# ---------------------------------------------------------------------------


def _extract_excluded_research_entry(
    selection_entry: dict[str, Any],
) -> dict[str, Any] | None:
    research_entry = selection_entry.get("research") or {}
    short_trade_entry = selection_entry.get("short_trade") or {}
    if research_entry.get("decision") != "selected":
        return None
    if short_trade_entry.get("decision") in {"selected", "near_miss"}:
        return None
    if _extract_research_upside_radar_entry(selection_entry) is not None:
        return None

    return {
        "ticker": selection_entry.get("ticker"),
        "research_score_target": research_entry.get("score_target"),
        "short_trade_decision": short_trade_entry.get("decision"),
        "short_trade_score_target": short_trade_entry.get("score_target"),
        "preferred_entry_mode": short_trade_entry.get("preferred_entry_mode"),
        "delta_summary": list(selection_entry.get("delta_summary") or []),
    }


# ---------------------------------------------------------------------------
# BTST candidate historical context
# ---------------------------------------------------------------------------


def _build_btst_candidate_historical_context(
    historical_payload: dict[str, Any],
) -> dict[str, Any]:
    family_counts = dict(historical_payload.get("family_counts") or {})
    return {
        "lookback_report_limit": OPPORTUNITY_POOL_HISTORICAL_LOOKBACK_REPORTS,
        "historical_report_count": int(
            historical_payload.get("contributing_report_count") or 0
        ),
        "historical_btst_candidate_count": len(historical_payload.get("rows") or []),
        "historical_watch_candidate_count": len(historical_payload.get("rows") or []),
        "historical_selected_candidate_count": int(family_counts.get("selected") or 0),
        "historical_near_miss_candidate_count": int(
            family_counts.get("near_miss") or 0
        ),
        "historical_opportunity_candidate_count": int(
            family_counts.get("opportunity_pool") or 0
        ),
        "historical_research_upside_radar_count": int(
            family_counts.get("research_upside_radar") or 0
        ),
        "historical_catalyst_theme_count": int(
            family_counts.get("catalyst_theme") or 0
        ),
        "next_high_hit_threshold": OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD,
    }


# ---------------------------------------------------------------------------
# Apply historical prior to entries
# ---------------------------------------------------------------------------


def _apply_historical_prior_to_entries(
    entries: list[dict[str, Any]],
    *,
    historical_rows: list[dict[str, Any]],
    price_cache: dict[tuple[str, str], pd.DataFrame],
    family: str,
) -> list[dict[str, Any]]:
    return [
        _apply_historical_prior_to_entry(
            entry=entry,
            historical_rows=historical_rows,
            price_cache=price_cache,
            family=family,
        )
        for entry in entries
    ]


def _apply_historical_prior_to_entry(
    *,
    entry: dict[str, Any],
    historical_rows: list[dict[str, Any]],
    price_cache: dict[tuple[str, str], pd.DataFrame],
    family: str,
) -> dict[str, Any]:
    enriched_entry = dict(entry)
    enriched_entry.update(
        _merge_entry_historical_prior(
            enriched_entry,
            _build_watch_candidate_historical_prior(
                enriched_entry,
                historical_rows,
                price_cache,
                family=family,
            ),
        )
    )
    return enriched_entry


# ---------------------------------------------------------------------------
# Enrich BTST brief entries with history
# ---------------------------------------------------------------------------


def _enrich_btst_brief_entries_with_history(
    *,
    report_dir: Path,
    actual_trade_date: str | None,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    default_context = _build_empty_btst_candidate_historical_context()
    no_history_observer_entries, risky_observer_entries, weak_history_pruned_entries = (
        _build_empty_brief_history_observer_groups()
    )
    if not (
        selected_entries
        or near_miss_entries
        or opportunity_pool_entries
        or research_upside_radar_entries
        or catalyst_theme_entries
    ):
        return _build_empty_brief_history_enrichment_result(
            selected_entries,
            near_miss_entries,
            opportunity_pool_entries,
            research_upside_radar_entries,
            catalyst_theme_entries,
            no_history_observer_entries,
            risky_observer_entries,
            weak_history_pruned_entries,
            default_context,
        )

    historical_payload = _collect_historical_watch_candidate_rows(
        report_dir, actual_trade_date
    )
    price_cache: dict[tuple[str, str], pd.DataFrame] = {}
    (
        selected_entries,
        near_miss_entries,
        opportunity_pool_entries,
        research_upside_radar_entries,
        catalyst_theme_entries,
    ) = _apply_historical_prior_to_brief_entry_groups(
        historical_rows=historical_payload["rows"],
        price_cache=price_cache,
        selected_entries=selected_entries,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
    )

    (
        selected_entries,
        near_miss_entries,
        opportunity_pool_entries,
        no_history_observer_entries,
        risky_observer_entries,
        weak_history_pruned_entries,
    ) = _postprocess_brief_history_enriched_groups(
        selected_entries=selected_entries,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        no_history_observer_entries=no_history_observer_entries,
        risky_observer_entries=risky_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
    )
    _sort_brief_history_enriched_groups(
        selected_entries=selected_entries,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        no_history_observer_entries=no_history_observer_entries,
        risky_observer_entries=risky_observer_entries,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
    )

    return (
        selected_entries,
        near_miss_entries,
        opportunity_pool_entries,
        research_upside_radar_entries,
        catalyst_theme_entries,
        no_history_observer_entries,
        risky_observer_entries,
        weak_history_pruned_entries,
        _build_btst_candidate_historical_context(historical_payload),
    )


def _build_empty_btst_candidate_historical_context() -> dict[str, Any]:
    return {
        "lookback_report_limit": OPPORTUNITY_POOL_HISTORICAL_LOOKBACK_REPORTS,
        "historical_report_count": 0,
        "historical_btst_candidate_count": 0,
        "historical_watch_candidate_count": 0,
        "historical_selected_candidate_count": 0,
        "historical_near_miss_candidate_count": 0,
        "historical_opportunity_candidate_count": 0,
        "historical_research_upside_radar_count": 0,
        "historical_catalyst_theme_count": 0,
        "next_high_hit_threshold": OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD,
    }


def _build_empty_brief_history_observer_groups() -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
]:
    return [], [], []


def _build_empty_brief_history_enrichment_result(
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
    default_context: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    return (
        selected_entries,
        near_miss_entries,
        opportunity_pool_entries,
        research_upside_radar_entries,
        catalyst_theme_entries,
        no_history_observer_entries,
        risky_observer_entries,
        weak_history_pruned_entries,
        default_context,
    )


# ---------------------------------------------------------------------------
# Postprocess & sort enriched groups
# ---------------------------------------------------------------------------


def _postprocess_brief_history_enriched_groups(
    *,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    selected_entries, near_miss_entries, opportunity_pool_entries = (
        _apply_and_reclassify_brief_history_groups(
            selected_entries=selected_entries,
            near_miss_entries=near_miss_entries,
            opportunity_pool_entries=opportunity_pool_entries,
        )
    )
    (
        near_miss_entries,
        opportunity_pool_entries,
        no_history_observer_entries,
        risky_observer_entries,
        weak_history_pruned_entries,
    ) = _demote_and_partition_brief_history_groups(
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        no_history_observer_entries=no_history_observer_entries,
        risky_observer_entries=risky_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
    )
    return (
        selected_entries,
        near_miss_entries,
        opportunity_pool_entries,
        no_history_observer_entries,
        risky_observer_entries,
        weak_history_pruned_entries,
    )


def _apply_and_reclassify_brief_history_groups(
    *,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    selected_entries, near_miss_entries, opportunity_pool_entries = (
        _apply_execution_quality_modes_to_brief_groups(
            selected_entries=selected_entries,
            near_miss_entries=near_miss_entries,
            opportunity_pool_entries=opportunity_pool_entries,
        )
    )
    return _reclassify_selected_execution_quality_entries(
        selected_entries,
        near_miss_entries,
        opportunity_pool_entries,
    )


def _demote_and_partition_brief_history_groups(
    *,
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    near_miss_entries, opportunity_pool_entries = _demote_weak_near_miss_entries(
        near_miss_entries,
        opportunity_pool_entries,
    )
    (
        opportunity_pool_entries,
        no_history_observer_entries,
        risky_observer_entries,
        weak_history_pruned_entries,
    ) = _partition_opportunity_pool_entries(
        opportunity_pool_entries,
    )
    return (
        near_miss_entries,
        opportunity_pool_entries,
        no_history_observer_entries,
        risky_observer_entries,
        weak_history_pruned_entries,
    )


def _sort_brief_history_enriched_groups(
    *,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
) -> None:
    selected_entries.sort(key=_historical_execution_entry_sort_key)
    near_miss_entries.sort(key=_historical_execution_entry_sort_key)
    opportunity_pool_entries.sort(key=_opportunity_pool_execution_sort_key)
    no_history_observer_entries.sort(key=_opportunity_pool_execution_sort_key)
    risky_observer_entries.sort(key=_opportunity_pool_execution_sort_key)
    research_upside_radar_entries.sort(key=_research_historical_entry_sort_key)
    catalyst_theme_entries.sort(key=_historical_execution_entry_sort_key)


def _apply_historical_prior_to_brief_entry_groups(
    *,
    historical_rows: list[dict[str, Any]],
    price_cache: dict[tuple[str, str], pd.DataFrame],
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    return (
        _apply_historical_prior_to_entries(
            selected_entries,
            historical_rows=historical_rows,
            price_cache=price_cache,
            family="selected",
        ),
        _apply_historical_prior_to_entries(
            near_miss_entries,
            historical_rows=historical_rows,
            price_cache=price_cache,
            family="near_miss",
        ),
        _apply_historical_prior_to_entries(
            opportunity_pool_entries,
            historical_rows=historical_rows,
            price_cache=price_cache,
            family="opportunity_pool",
        ),
        _apply_historical_prior_to_entries(
            research_upside_radar_entries,
            historical_rows=historical_rows,
            price_cache=price_cache,
            family="research_upside_radar",
        ),
        _apply_historical_prior_to_entries(
            catalyst_theme_entries,
            historical_rows=historical_rows,
            price_cache=price_cache,
            family="catalyst_theme",
        ),
    )


def _apply_execution_quality_modes_to_brief_groups(
    *,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    return (
        [_apply_execution_quality_entry_mode(entry) for entry in selected_entries],
        [_apply_execution_quality_entry_mode(entry) for entry in near_miss_entries],
        [
            _apply_execution_quality_entry_mode(entry)
            for entry in opportunity_pool_entries
        ],
    )
