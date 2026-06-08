"""Historical row collection, prior application, and context building.

These functions sit between the collection layer and the enrichment layer,
needed by both historical_prior.py and historical_prior_brief_enrichment.py.

Extracted from historical_prior.py during R20.16 refactoring to avoid circular imports.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.paper_trading.btst_reporting_utils import (
    OPPORTUNITY_POOL_HISTORICAL_LOOKBACK_REPORTS,
    OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD,
    _catalyst_bucket_label,
    _load_json,
    _normalize_trade_date,
    _round_or_none,
    _score_bucket_label,
)
from src.paper_trading._btst_reporting.entry_builders import (
    _iter_selection_snapshot_paths,
    _discover_recent_historical_report_dirs,
    _extract_short_trade_entry,
    _extract_short_trade_opportunity_entry,
    _extract_research_upside_radar_entry,
    _extract_catalyst_theme_entry,
    _merge_entry_historical_prior,
)


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
    # Deferred import to avoid circular dependency: this module is imported by
    # historical_prior.py, which defines the prior builders we need here.
    from src.paper_trading._btst_reporting.historical_prior import _build_watch_candidate_historical_prior

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
