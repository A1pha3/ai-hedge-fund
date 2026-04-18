from __future__ import annotations

from pathlib import Path
from typing import Any

from src.paper_trading.btst_reporting_utils import (
    OPPORTUNITY_POOL_MAX_ENTRIES,
    _as_float,
    _load_json,
    _load_selection_replay_input,
    _normalize_trade_date,
    _resolve_replay_input_path,
    _shadow_decision_rank,
    _summary_value,
)
from src.paper_trading._btst_reporting.extractors import (
    _extract_upstream_shadow_replay_only_entry,
    RESEARCH_UPSIDE_RADAR_MAX_ENTRIES,
)
from src.paper_trading._btst_reporting.entry_builders import (
    CATALYST_THEME_MAX_ENTRIES,
    CATALYST_THEME_SHADOW_MAX_ENTRIES,
    _extract_catalyst_theme_entry as _extract_catalyst_theme_entry_eb,
    _extract_catalyst_theme_shadow_entry as _extract_catalyst_theme_shadow_entry_eb,
    _extract_research_upside_radar_entry as _extract_research_upside_radar_entry_eb,
    _extract_short_trade_entry as _extract_short_trade_entry_eb,
    _extract_short_trade_opportunity_entry as _extract_short_trade_opportunity_entry_eb,
    _extract_upstream_shadow_entry as _extract_upstream_shadow_entry_eb,
    _build_upstream_shadow_summary as _build_upstream_shadow_summary_eb,
    _build_catalyst_theme_frontier_priority as _build_catalyst_theme_frontier_priority_eb,
    _load_catalyst_theme_frontier_summary as _load_catalyst_theme_frontier_summary_eb,
    _resolve_snapshot_path as _resolve_snapshot_path_eb,
)
from src.paper_trading._btst_reporting.historical_prior import (
    _enrich_btst_brief_entries_with_history,
    _extract_excluded_research_entry,
)


# ---------------------------------------------------------------------------
# Lazy import helpers for Middle Man functions remaining in btst_reporting.py
# ---------------------------------------------------------------------------

def _extract_short_trade_entry(
    selection_entry: dict[str, Any],
) -> dict[str, Any] | None:
    return _extract_short_trade_entry_eb(selection_entry)


def _extract_short_trade_opportunity_entry(
    selection_entry: dict[str, Any],
) -> dict[str, Any] | None:
    return _extract_short_trade_opportunity_entry_eb(selection_entry)


def _extract_research_upside_radar_entry(
    selection_entry: dict[str, Any],
) -> dict[str, Any] | None:
    return _extract_research_upside_radar_entry_eb(selection_entry)


def _extract_catalyst_theme_entry(candidate: dict[str, Any]) -> dict[str, Any] | None:
    return _extract_catalyst_theme_entry_eb(candidate)


def _extract_catalyst_theme_shadow_entry(
    candidate: dict[str, Any],
) -> dict[str, Any] | None:
    return _extract_catalyst_theme_shadow_entry_eb(candidate)


def _extract_upstream_shadow_entry(
    selection_entry: dict[str, Any], supplemental_entry: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    return _extract_upstream_shadow_entry_eb(selection_entry, supplemental_entry)


def _build_upstream_shadow_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return _build_upstream_shadow_summary_eb(entries)


def _load_catalyst_theme_frontier_summary(
    report_dir: str | Path | None,
) -> dict[str, Any]:
    return _load_catalyst_theme_frontier_summary_eb(report_dir)


def _build_catalyst_theme_frontier_priority(
    frontier_summary: dict[str, Any], shadow_entries: list[dict[str, Any]]
) -> dict[str, Any]:
    return _build_catalyst_theme_frontier_priority_eb(frontier_summary, shadow_entries)


def _resolve_snapshot_path(
    input_path: str | Path, trade_date: str | None
) -> tuple[Path, Path]:
    return _resolve_snapshot_path_eb(input_path, trade_date)


def _build_btst_recommendation_lines_lazy(
    *,
    primary_entry: dict[str, Any] | None,
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    excluded_research_entries: list[dict[str, Any]],
    upstream_shadow_entries: list[dict[str, Any]],
) -> list[str]:
    from src.paper_trading.btst_reporting import _build_btst_recommendation_lines
    return _build_btst_recommendation_lines(
        primary_entry=primary_entry,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        risky_observer_entries=risky_observer_entries,
        no_history_observer_entries=no_history_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
        catalyst_theme_frontier_priority=catalyst_theme_frontier_priority,
        catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
        excluded_research_entries=excluded_research_entries,
        upstream_shadow_entries=upstream_shadow_entries,
    )


# ---------------------------------------------------------------------------
# Public brief builder functions (extracted from btst_reporting.py lines 493-1231)
# ---------------------------------------------------------------------------

def analyze_btst_next_day_trade_brief(
    input_path: str | Path,
    trade_date: str | None = None,
    next_trade_date: str | None = None,
) -> dict[str, Any]:
    brief_inputs = _load_btst_brief_inputs(input_path=input_path, trade_date=trade_date)
    snapshot_path = brief_inputs["snapshot_path"]
    report_dir = brief_inputs["report_dir"]
    snapshot = brief_inputs["snapshot"]
    session_summary_path = brief_inputs["session_summary_path"]
    session_summary = brief_inputs["session_summary"]
    actual_trade_date = brief_inputs["actual_trade_date"]
    selection_targets = brief_inputs["selection_targets"]
    candidate_groups = _build_btst_brief_candidate_groups(
        snapshot=snapshot, selection_targets=selection_targets
    )
    brief_candidate_context = _build_btst_brief_candidate_context(candidate_groups)
    selected_entries = brief_candidate_context["selected_entries"]
    near_miss_entries = brief_candidate_context["near_miss_entries"]
    opportunity_pool_entries = brief_candidate_context["opportunity_pool_entries"]
    research_upside_radar_entries = brief_candidate_context[
        "research_upside_radar_entries"
    ]
    catalyst_theme_entries = brief_candidate_context["catalyst_theme_entries"]
    catalyst_theme_shadow_entries = brief_candidate_context[
        "catalyst_theme_shadow_entries"
    ]
    brief_frontier_context = _build_btst_brief_frontier_context(
        report_dir=report_dir,
        catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
        selection_targets=selection_targets,
        replay_input=brief_inputs["replay_input"],
    )
    history_context = _build_btst_brief_history_context(
        report_dir=report_dir,
        actual_trade_date=actual_trade_date,
        selected_entries=selected_entries,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
    )
    selected_entries = history_context["selected_entries"]
    near_miss_entries = history_context["near_miss_entries"]
    opportunity_pool_entries = history_context["opportunity_pool_entries"]
    research_upside_radar_entries = history_context["research_upside_radar_entries"]
    catalyst_theme_entries = history_context["catalyst_theme_entries"]
    no_history_observer_entries = history_context["no_history_observer_entries"]
    risky_observer_entries = history_context["risky_observer_entries"]
    weak_history_pruned_entries = history_context["weak_history_pruned_entries"]
    btst_candidate_historical_context = history_context[
        "btst_candidate_historical_context"
    ]

    excluded_research_entries = _build_excluded_research_entries(selection_targets)
    recommendation_lines = _build_btst_brief_recommendation_lines(
        selected_entries=selected_entries,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        risky_observer_entries=risky_observer_entries,
        no_history_observer_entries=no_history_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
        catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
        excluded_research_entries=excluded_research_entries,
        brief_frontier_context=brief_frontier_context,
    )

    return _build_btst_next_day_trade_brief_payload(
        report_dir=report_dir,
        snapshot_path=snapshot_path,
        session_summary_path=session_summary_path,
        actual_trade_date=actual_trade_date,
        next_trade_date=next_trade_date,
        snapshot=snapshot,
        session_summary=session_summary,
        selection_targets=selection_targets,
        selected_entries=selected_entries,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        no_history_observer_entries=no_history_observer_entries,
        risky_observer_entries=risky_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
        catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
        btst_candidate_historical_context=btst_candidate_historical_context,
        excluded_research_entries=excluded_research_entries,
        recommendation_lines=recommendation_lines,
        brief_frontier_context=brief_frontier_context,
    )


def _build_btst_brief_history_context(
    *,
    report_dir: Path,
    actual_trade_date: str | None,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    (
        selected_entries,
        near_miss_entries,
        opportunity_pool_entries,
        research_upside_radar_entries,
        catalyst_theme_entries,
        no_history_observer_entries,
        risky_observer_entries,
        weak_history_pruned_entries,
        btst_candidate_historical_context,
    ) = _enrich_btst_brief_entries_with_history(
        report_dir=report_dir,
        actual_trade_date=actual_trade_date,
        selected_entries=selected_entries,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
    )
    return {
        "selected_entries": selected_entries,
        "near_miss_entries": near_miss_entries,
        "opportunity_pool_entries": opportunity_pool_entries,
        "research_upside_radar_entries": research_upside_radar_entries,
        "catalyst_theme_entries": catalyst_theme_entries,
        "no_history_observer_entries": no_history_observer_entries,
        "risky_observer_entries": risky_observer_entries,
        "weak_history_pruned_entries": weak_history_pruned_entries,
        "btst_candidate_historical_context": btst_candidate_historical_context,
    }


def _build_btst_brief_candidate_context(
    candidate_groups: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "selected_entries": candidate_groups["selected_entries"],
        "near_miss_entries": candidate_groups["near_miss_entries"],
        "opportunity_pool_entries": candidate_groups["opportunity_pool_entries"],
        "research_upside_radar_entries": candidate_groups[
            "research_upside_radar_entries"
        ],
        "catalyst_theme_entries": candidate_groups["catalyst_theme_entries"],
        "catalyst_theme_shadow_entries": candidate_groups[
            "catalyst_theme_shadow_entries"
        ],
    }


def _build_btst_brief_recommendation_lines(
    *,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    excluded_research_entries: list[dict[str, Any]],
    brief_frontier_context: dict[str, Any],
) -> list[str]:
    primary_entry = selected_entries[0] if selected_entries else None
    return _build_btst_recommendation_lines_lazy(
        primary_entry=primary_entry,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        risky_observer_entries=risky_observer_entries,
        no_history_observer_entries=no_history_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
        catalyst_theme_frontier_priority=brief_frontier_context[
            "catalyst_theme_frontier_priority"
        ],
        catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
        excluded_research_entries=excluded_research_entries,
        upstream_shadow_entries=brief_frontier_context["upstream_shadow_entries"],
    )


def _build_btst_brief_frontier_context(
    *,
    report_dir: Path,
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    selection_targets: dict[str, Any],
    replay_input: dict[str, Any],
) -> dict[str, Any]:
    catalyst_theme_frontier_summary = _load_catalyst_theme_frontier_summary(report_dir)
    catalyst_theme_frontier_priority = _build_catalyst_theme_frontier_priority(
        catalyst_theme_frontier_summary, catalyst_theme_shadow_entries
    )
    upstream_shadow_entries = _build_upstream_shadow_entries(
        selection_targets=selection_targets,
        replay_input=replay_input,
    )
    return {
        "catalyst_theme_frontier_summary": catalyst_theme_frontier_summary,
        "catalyst_theme_frontier_priority": catalyst_theme_frontier_priority,
        "upstream_shadow_entries": upstream_shadow_entries,
        "upstream_shadow_summary": _build_upstream_shadow_summary(
            upstream_shadow_entries
        ),
    }


def _build_btst_next_day_trade_brief_payload(
    *,
    report_dir: Path,
    snapshot_path: Path,
    session_summary_path: Path,
    actual_trade_date: str | None,
    next_trade_date: str | None,
    snapshot: dict[str, Any],
    session_summary: dict[str, Any],
    selection_targets: dict[str, Any],
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    btst_candidate_historical_context: dict[str, Any],
    excluded_research_entries: list[dict[str, Any]],
    recommendation_lines: list[str],
    brief_frontier_context: dict[str, Any],
) -> dict[str, Any]:
    primary_entry = selected_entries[0] if selected_entries else None
    return {
        **_build_btst_next_day_trade_brief_metadata(
            report_dir=report_dir,
            snapshot_path=snapshot_path,
            session_summary_path=session_summary_path,
            actual_trade_date=actual_trade_date,
            next_trade_date=next_trade_date,
            snapshot=snapshot,
            session_summary=session_summary,
        ),
        **_build_btst_next_day_trade_brief_content(
            snapshot=snapshot,
            selection_targets=selection_targets,
            primary_entry=primary_entry,
            selected_entries=selected_entries,
            near_miss_entries=near_miss_entries,
            opportunity_pool_entries=opportunity_pool_entries,
            no_history_observer_entries=no_history_observer_entries,
            risky_observer_entries=risky_observer_entries,
            weak_history_pruned_entries=weak_history_pruned_entries,
            research_upside_radar_entries=research_upside_radar_entries,
            catalyst_theme_entries=catalyst_theme_entries,
            catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
            btst_candidate_historical_context=btst_candidate_historical_context,
            excluded_research_entries=excluded_research_entries,
            recommendation_lines=recommendation_lines,
            brief_frontier_context=brief_frontier_context,
        ),
    }


def _build_btst_next_day_trade_brief_content(
    *,
    snapshot: dict[str, Any],
    selection_targets: dict[str, Any],
    primary_entry: dict[str, Any] | None,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    btst_candidate_historical_context: dict[str, Any],
    excluded_research_entries: list[dict[str, Any]],
    recommendation_lines: list[str],
    brief_frontier_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "summary": _build_btst_brief_summary(
            snapshot=snapshot,
            selection_targets=selection_targets,
            selected_entries=selected_entries,
            near_miss_entries=near_miss_entries,
            opportunity_pool_entries=opportunity_pool_entries,
            no_history_observer_entries=no_history_observer_entries,
            risky_observer_entries=risky_observer_entries,
            weak_history_pruned_entries=weak_history_pruned_entries,
            research_upside_radar_entries=research_upside_radar_entries,
            catalyst_theme_entries=catalyst_theme_entries,
            catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
            catalyst_theme_frontier_priority=brief_frontier_context[
                "catalyst_theme_frontier_priority"
            ],
            upstream_shadow_summary=brief_frontier_context["upstream_shadow_summary"],
        ),
        **_build_btst_next_day_trade_brief_sections(
            primary_entry=primary_entry,
            selected_entries=selected_entries,
            near_miss_entries=near_miss_entries,
            opportunity_pool_entries=opportunity_pool_entries,
            no_history_observer_entries=no_history_observer_entries,
            risky_observer_entries=risky_observer_entries,
            weak_history_pruned_entries=weak_history_pruned_entries,
            research_upside_radar_entries=research_upside_radar_entries,
            catalyst_theme_entries=catalyst_theme_entries,
            catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
            btst_candidate_historical_context=btst_candidate_historical_context,
            excluded_research_entries=excluded_research_entries,
            brief_frontier_context=brief_frontier_context,
        ),
        "recommendation": " ".join(recommendation_lines),
    }


def _build_btst_next_day_trade_brief_metadata(
    *,
    report_dir: Path,
    snapshot_path: Path,
    session_summary_path: Path,
    actual_trade_date: str | None,
    next_trade_date: str | None,
    snapshot: dict[str, Any],
    session_summary: dict[str, Any],
) -> dict[str, Any]:
    replay_input_path = _resolve_replay_input_path(snapshot_path)
    return {
        "report_dir": str(report_dir),
        "snapshot_path": str(snapshot_path),
        "replay_input_path": str(replay_input_path)
        if replay_input_path.exists()
        else None,
        "session_summary_path": str(session_summary_path)
        if session_summary_path.exists()
        else None,
        "trade_date": actual_trade_date,
        "next_trade_date": _normalize_trade_date(next_trade_date),
        "target_mode": snapshot.get("target_mode"),
        "selection_target": (session_summary.get("plan_generation") or {}).get(
            "selection_target"
        )
        or snapshot.get("target_mode"),
    }


def _build_btst_next_day_trade_brief_sections(
    *,
    primary_entry: dict[str, Any] | None,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    btst_candidate_historical_context: dict[str, Any],
    excluded_research_entries: list[dict[str, Any]],
    brief_frontier_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "primary_entry": primary_entry,
        "selected_entries": selected_entries,
        "near_miss_entries": near_miss_entries,
        "opportunity_pool_entries": opportunity_pool_entries,
        "no_history_observer_entries": no_history_observer_entries,
        "risky_observer_entries": risky_observer_entries,
        "weak_history_pruned_entries": weak_history_pruned_entries,
        "research_upside_radar_entries": research_upside_radar_entries,
        "catalyst_theme_entries": catalyst_theme_entries,
        "catalyst_theme_shadow_entries": catalyst_theme_shadow_entries,
        "catalyst_theme_frontier_summary": brief_frontier_context[
            "catalyst_theme_frontier_summary"
        ],
        "catalyst_theme_frontier_priority": brief_frontier_context[
            "catalyst_theme_frontier_priority"
        ],
        "upstream_shadow_entries": brief_frontier_context["upstream_shadow_entries"],
        "upstream_shadow_summary": brief_frontier_context["upstream_shadow_summary"],
        "btst_candidate_historical_context": btst_candidate_historical_context,
        "watch_candidate_historical_context": btst_candidate_historical_context,
        "opportunity_pool_historical_context": btst_candidate_historical_context,
        "excluded_research_entries": excluded_research_entries,
    }


def _load_btst_brief_inputs(
    input_path: str | Path, trade_date: str | None
) -> dict[str, Any]:
    snapshot_path, report_dir = _resolve_snapshot_path(input_path, trade_date)
    snapshot = _load_json(snapshot_path)
    replay_input = _load_selection_replay_input(snapshot_path)
    session_summary_path = report_dir / "session_summary.json"
    return {
        "snapshot_path": snapshot_path,
        "report_dir": report_dir,
        "snapshot": snapshot,
        "replay_input": replay_input,
        "session_summary_path": session_summary_path,
        "session_summary": _load_json(session_summary_path)
        if session_summary_path.exists()
        else {},
        "actual_trade_date": _normalize_trade_date(
            snapshot.get("trade_date") or trade_date
        ),
        "selection_targets": snapshot.get("selection_targets") or {},
    }


def _build_btst_brief_candidate_groups(
    *, snapshot: dict[str, Any], selection_targets: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    short_trade_entries = _build_btst_brief_short_trade_entries(selection_targets)
    opportunity_pool_entries = _build_btst_brief_opportunity_pool_entries(
        selection_targets
    )
    research_upside_radar_entries = _build_btst_brief_research_upside_radar_entries(
        selection_targets
    )
    catalyst_theme_entries = _build_btst_brief_catalyst_theme_entries(snapshot)
    catalyst_theme_shadow_entries = _build_btst_brief_catalyst_theme_shadow_entries(
        snapshot
    )
    return {
        "selected_entries": [
            entry for entry in short_trade_entries if entry["decision"] == "selected"
        ],
        "near_miss_entries": [
            entry for entry in short_trade_entries if entry["decision"] == "near_miss"
        ],
        "opportunity_pool_entries": opportunity_pool_entries[
            :OPPORTUNITY_POOL_MAX_ENTRIES
        ],
        "research_upside_radar_entries": research_upside_radar_entries[
            :RESEARCH_UPSIDE_RADAR_MAX_ENTRIES
        ],
        "catalyst_theme_entries": catalyst_theme_entries[:CATALYST_THEME_MAX_ENTRIES],
        "catalyst_theme_shadow_entries": catalyst_theme_shadow_entries[
            :CATALYST_THEME_SHADOW_MAX_ENTRIES
        ],
    }


def _build_btst_brief_short_trade_entries(
    selection_targets: dict[str, Any],
) -> list[dict[str, Any]]:
    short_trade_entries = [
        candidate
        for candidate in (
            _extract_short_trade_entry(entry) for entry in selection_targets.values()
        )
        if candidate is not None
    ]
    short_trade_entries.sort(
        key=lambda entry: (
            0 if entry["decision"] == "selected" else 1,
            -(entry.get("score_target") or 0.0),
            entry.get("ticker") or "",
        )
    )
    return short_trade_entries


def _build_btst_brief_opportunity_pool_entries(
    selection_targets: dict[str, Any],
) -> list[dict[str, Any]]:
    opportunity_pool_entries = [
        candidate
        for candidate in (
            _extract_short_trade_opportunity_entry(entry)
            for entry in selection_targets.values()
        )
        if candidate is not None
    ]
    opportunity_pool_entries.sort(
        key=lambda entry: (
            entry.get("score_gap_to_near_miss")
            if entry.get("score_gap_to_near_miss") is not None
            else 999.0,
            -(entry.get("score_target") or 0.0),
            -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
            -_as_float((entry.get("metrics") or {}).get("breakout_freshness")),
            entry.get("ticker") or "",
        )
    )
    return opportunity_pool_entries


def _build_btst_brief_research_upside_radar_entries(
    selection_targets: dict[str, Any],
) -> list[dict[str, Any]]:
    research_upside_radar_entries = [
        candidate
        for candidate in (
            _extract_research_upside_radar_entry(entry)
            for entry in selection_targets.values()
        )
        if candidate is not None
    ]
    research_upside_radar_entries.sort(
        key=lambda entry: (
            -(entry.get("research_score_target") or 0.0),
            -(entry.get("score_target") or 0.0),
            -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
            entry.get("ticker") or "",
        )
    )
    return research_upside_radar_entries


def _build_btst_brief_catalyst_theme_entries(
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    catalyst_theme_entries = [
        candidate
        for candidate in (
            _extract_catalyst_theme_entry(entry)
            for entry in (snapshot.get("catalyst_theme_candidates") or [])
        )
        if candidate is not None
    ]
    catalyst_theme_entries.sort(
        key=lambda entry: (
            -(entry.get("score_target") or 0.0),
            -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
            -_as_float((entry.get("metrics") or {}).get("sector_resonance")),
            entry.get("ticker") or "",
        )
    )
    return catalyst_theme_entries


def _build_btst_brief_catalyst_theme_shadow_entries(
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    catalyst_theme_shadow_entries = [
        candidate
        for candidate in (
            _extract_catalyst_theme_shadow_entry(entry)
            for entry in (snapshot.get("catalyst_theme_shadow_candidates") or [])
        )
        if candidate is not None
    ]
    catalyst_theme_shadow_entries.sort(
        key=lambda entry: (
            -(entry.get("score_target") or 0.0),
            entry.get("total_shortfall")
            if entry.get("total_shortfall") is not None
            else 999.0,
            -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
            entry.get("ticker") or "",
        )
    )
    return catalyst_theme_shadow_entries


def _build_upstream_shadow_entries(
    *, selection_targets: dict[str, Any], replay_input: dict[str, Any]
) -> list[dict[str, Any]]:
    supplemental_short_trade_entry_by_ticker = (
        _build_supplemental_short_trade_entry_map(replay_input)
    )
    upstream_shadow_entries_by_ticker = _build_upstream_shadow_entry_map(
        selection_targets=selection_targets,
        supplemental_short_trade_entry_by_ticker=supplemental_short_trade_entry_by_ticker,
    )
    _merge_replay_only_upstream_shadow_entries(
        upstream_shadow_entries_by_ticker, replay_input
    )
    upstream_shadow_entries = list(upstream_shadow_entries_by_ticker.values())
    upstream_shadow_entries.sort(
        key=lambda entry: (
            _shadow_decision_rank(entry.get("decision")),
            -(entry.get("score_target") or 0.0),
            entry.get("candidate_pool_rank")
            if entry.get("candidate_pool_rank") is not None
            else 999999,
            entry.get("ticker") or "",
        )
    )
    return upstream_shadow_entries


def _build_supplemental_short_trade_entry_map(
    replay_input: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        str(entry.get("ticker") or ""): dict(entry)
        for entry in list(replay_input.get("supplemental_short_trade_entries") or [])
        if entry.get("ticker")
    }


def _build_upstream_shadow_entry_map(
    *,
    selection_targets: dict[str, Any],
    supplemental_short_trade_entry_by_ticker: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        str(candidate.get("ticker") or ""): candidate
        for candidate in (
            _extract_upstream_shadow_entry(
                entry,
                supplemental_short_trade_entry_by_ticker.get(
                    str(entry.get("ticker") or "")
                ),
            )
            for entry in selection_targets.values()
        )
        if candidate is not None and candidate.get("ticker")
    }


def _merge_replay_only_upstream_shadow_entries(
    upstream_shadow_entries_by_ticker: dict[str, dict[str, Any]],
    replay_input: dict[str, Any],
) -> None:
    for candidate in (
        _extract_upstream_shadow_replay_only_entry(entry)
        for entry in list(replay_input.get("upstream_shadow_observation_entries") or [])
        if entry.get("ticker")
    ):
        if candidate is None or not candidate.get("ticker"):
            continue
        upstream_shadow_entries_by_ticker.setdefault(
            str(candidate.get("ticker") or ""), candidate
        )


def _build_excluded_research_entries(
    selection_targets: dict[str, Any],
) -> list[dict[str, Any]]:
    excluded_research_entries = [
        candidate
        for candidate in (
            _extract_excluded_research_entry(entry)
            for entry in selection_targets.values()
        )
        if candidate is not None
    ]
    excluded_research_entries.sort(
        key=lambda entry: (
            -(entry.get("research_score_target") or 0.0),
            entry.get("ticker") or "",
        )
    )
    return excluded_research_entries


def _build_btst_brief_summary(
    *,
    snapshot: dict[str, Any],
    selection_targets: dict[str, Any],
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
    upstream_shadow_summary: dict[str, Any],
) -> dict[str, Any]:
    dual_target_summary = snapshot.get("dual_target_summary") or {}
    brief_decision_counts = _build_btst_brief_decision_counts(selection_targets)
    return {
        "selection_target_count": _summary_value(
            dual_target_summary, "selection_target_count", len(selection_targets)
        ),
        "short_trade_selected_count": len(selected_entries),
        "short_trade_near_miss_count": len(near_miss_entries),
        "short_trade_blocked_count": _summary_value(
            dual_target_summary,
            "short_trade_blocked_count",
            brief_decision_counts["blocked_count"],
        ),
        "short_trade_rejected_count": _summary_value(
            dual_target_summary,
            "short_trade_rejected_count",
            brief_decision_counts["rejected_count"],
        ),
        "short_trade_opportunity_pool_count": len(opportunity_pool_entries),
        "no_history_observer_count": len(no_history_observer_entries),
        "risky_observer_count": len(risky_observer_entries),
        "weak_history_pruned_count": len(weak_history_pruned_entries),
        "research_upside_radar_count": len(research_upside_radar_entries),
        "catalyst_theme_count": len(catalyst_theme_entries),
        "catalyst_theme_shadow_count": len(catalyst_theme_shadow_entries),
        "catalyst_theme_frontier_promoted_count": len(
            catalyst_theme_frontier_priority.get("promoted_tickers") or []
        ),
        "upstream_shadow_candidate_count": upstream_shadow_summary.get(
            "shadow_candidate_count"
        )
        or 0,
        "upstream_shadow_promotable_count": upstream_shadow_summary.get(
            "promotable_count"
        )
        or 0,
        "research_selected_count": _summary_value(
            dual_target_summary,
            "research_selected_count",
            brief_decision_counts["research_selected_count"],
        ),
    }


def _build_btst_brief_decision_counts(
    selection_targets: dict[str, Any],
) -> dict[str, int]:
    short_trade_decisions = [
        (entry.get("short_trade") or {}).get("decision")
        for entry in selection_targets.values()
        if entry.get("short_trade")
    ]
    return {
        "blocked_count": sum(
            1 for decision in short_trade_decisions if decision == "blocked"
        ),
        "rejected_count": sum(
            1 for decision in short_trade_decisions if decision == "rejected"
        ),
        "research_selected_count": sum(
            1
            for entry in selection_targets.values()
            if (entry.get("research") or {}).get("decision") == "selected"
        ),
    }
