"""BTST brief entry enrichment with historical prior data and postprocessing.

Extracted from historical_prior.py during R20.16 refactoring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.paper_trading.btst_reporting_utils import (
    OPPORTUNITY_POOL_HISTORICAL_LOOKBACK_REPORTS,
    OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD,
    _historical_execution_entry_sort_key,
    _opportunity_pool_execution_sort_key,
    _research_historical_entry_sort_key,
)
from src.paper_trading._btst_reporting.entry_builders import (
    _reclassify_selected_execution_quality_entries,
)
from src.paper_trading._btst_reporting.entry_transforms import (
    _apply_execution_quality_entry_mode,
)
from src.paper_trading._btst_reporting.pool_classifiers import (
    _demote_weak_near_miss_entries,
    _partition_opportunity_pool_entries,
)
from src.paper_trading._btst_reporting.historical_prior_collection import (
    _collect_historical_watch_candidate_rows,
    _apply_historical_prior_to_entries,
    _build_btst_candidate_historical_context,
)


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


def _enrich_upstream_shadow_entries_with_history(
    *,
    report_dir: Path,
    actual_trade_date: str | None,
    upstream_shadow_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not upstream_shadow_entries:
        return []
    historical_payload = _collect_historical_watch_candidate_rows(
        report_dir, actual_trade_date
    )
    price_cache: dict[tuple[str, str], pd.DataFrame] = {}
    return _apply_historical_prior_to_entries(
        upstream_shadow_entries,
        historical_rows=historical_payload["rows"],
        price_cache=price_cache,
        family="upstream_shadow",
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
