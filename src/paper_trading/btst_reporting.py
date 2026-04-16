from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from collections.abc import Callable

import pandas as pd

from src.paper_trading.btst_reporting_utils import (
    LOW_SCORE_NO_HISTORY_UPSTREAM_MAX_SCORE_TARGET,
    MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_BREAKOUT_FRESHNESS,
    MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_NEXT_CLOSE_POSITIVE_RATE,
    MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_NEXT_HIGH_HIT_RATE,
    MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_SCORE_TARGET,
    MIXED_BOUNDARY_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT,
    OPPORTUNITY_POOL_HISTORICAL_LOOKBACK_REPORTS,
    OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD,
    OPPORTUNITY_POOL_HISTORICAL_SAME_TICKER_MIN_SAMPLES,
    OPPORTUNITY_POOL_MAX_ENTRIES,
    OPPORTUNITY_POOL_MIN_SCORE_TARGET,
    OPPORTUNITY_POOL_STRONG_SIGNAL_MIN,
    RISKY_OBSERVER_EXECUTION_QUALITY_LABELS,
    UPSTREAM_SHADOW_CANDIDATE_SOURCES,
    WEAK_BALANCED_OPPORTUNITY_POOL_MAX_NEXT_CLOSE_POSITIVE_RATE,
    WEAK_BALANCED_OPPORTUNITY_POOL_MAX_NEXT_HIGH_HIT_RATE,
    WEAK_BALANCED_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT,
    WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT,
    WEAK_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT,
    _as_float,
    _catalyst_bucket_label,
    _compact_trade_date,
    _format_float,
    _load_json,
    _load_selection_replay_input,
    _mean_or_none,
    _normalize_trade_date,
    _resolve_followup_trade_dates,
    _resolve_replay_input_path,
    _round_or_none,
    _score_bucket_label,
    _shadow_decision_rank,
    _source_lane_display,
    _source_lane_label,
    _sync_text_artifact_alias,
    _write_json,
    infer_next_trade_date,
    _entry_mode_action_guidance,
    _execution_priority_rank,
    _historical_execution_entry_sort_key,
    _monitor_priority_rank,
    _opportunity_pool_execution_sort_key,
    _research_historical_entry_sort_key,
    _summary_value,
)

from scripts.btst_latest_followup_utils import _choose_preferred_historical_prior
from src.paper_trading.btst_opening_watch_markdown_helpers import (
    append_catalyst_theme_watch_markdown as _append_catalyst_theme_watch_markdown_impl,
    append_opening_watch_focus_items_markdown as _append_opening_watch_focus_items_markdown_impl,
)
from src.paper_trading.btst_priority_board_markdown_helpers import (
    append_priority_board_frontier_markdown as _append_priority_board_frontier_markdown_impl,
    append_priority_board_overview_markdown as _append_priority_board_overview_markdown_impl,
    append_priority_board_rows_markdown as _append_priority_board_rows_markdown_impl,
    append_priority_board_shadow_watch_markdown as _append_priority_board_shadow_watch_markdown_impl,
)
from src.paper_trading.btst_trade_brief_shadow_markdown_helpers import (
    append_brief_catalyst_frontier_markdown as _append_brief_catalyst_frontier_markdown_impl,
    append_brief_catalyst_shadow_markdown as _append_brief_catalyst_shadow_markdown_impl,
    append_brief_upstream_shadow_markdown as _append_brief_upstream_shadow_markdown_impl,
)
from src.paper_trading.btst_shared_markdown_helpers import (
    append_frontier_priority_summary as _append_frontier_priority_summary_impl,
    append_frontier_promoted_shadow_none_block as _append_frontier_promoted_shadow_none_block_impl,
    append_frontier_section as _append_frontier_section_impl,
    append_guardrail_section as _append_guardrail_section_impl,
    append_indexed_ticker_block as _append_indexed_ticker_block_impl,
    append_indexed_ticker_blocks as _append_indexed_ticker_blocks_impl,
    append_none_block as _append_none_block_impl,
    append_source_paths_section as _append_source_paths_section_impl,
    append_titled_indexed_section as _append_titled_indexed_section_impl,
    append_titled_indexed_ticker_section as _append_titled_indexed_ticker_section_impl,
    append_upstream_shadow_core_fields as _append_upstream_shadow_core_fields_impl,
    append_upstream_shadow_section as _append_upstream_shadow_section_impl,
    append_upstream_shadow_summary as _append_upstream_shadow_summary_impl,
    append_upstream_shadow_summary_header as _append_upstream_shadow_summary_header_impl,
)
from src.paper_trading.btst_trade_brief_core_markdown_helpers import (
    append_brief_observer_lane_markdown as _append_brief_observer_lane_markdown_impl,
    append_brief_scored_entries_markdown as _append_brief_scored_entries_markdown_impl,
)
from src.paper_trading.btst_trade_brief_catalyst_markdown_helpers import (
    append_brief_catalyst_theme_markdown as _append_brief_catalyst_theme_markdown_impl,
    append_brief_excluded_research_markdown as _append_brief_excluded_research_markdown_impl,
)
from src.paper_trading.btst_trade_brief_pool_markdown_helpers import (
    append_brief_opportunity_pool_markdown as _append_brief_opportunity_pool_markdown_impl,
    append_brief_pruned_entries_markdown as _append_brief_pruned_entries_markdown_impl,
    append_brief_research_radar_markdown as _append_brief_research_radar_markdown_impl,
)
from src.paper_trading.btst_recommendation_helpers import (
    append_pool_and_observer_recommendations as _append_pool_and_observer_recommendations_impl,
    append_primary_and_near_miss_recommendations as _append_primary_and_near_miss_recommendations_impl,
    append_research_and_shadow_recommendations as _append_research_and_shadow_recommendations_impl,
)
from src.paper_trading.btst_premarket_markdown_helpers import (
    append_premarket_frontier_watch_markdown as _append_premarket_frontier_watch_markdown_impl,
    append_premarket_shadow_watch_markdown as _append_premarket_shadow_watch_markdown_impl,
)
from src.paper_trading.btst_report_artifact_helpers import (
    generate_and_register_btst_followup_artifacts as _generate_and_register_btst_followup_artifacts_impl,
    generate_btst_next_day_priority_board_artifacts as _generate_btst_next_day_priority_board_artifacts_impl,
    generate_btst_next_day_trade_brief_artifacts as _generate_btst_next_day_trade_brief_artifacts_impl,
    generate_btst_opening_watch_card_artifacts as _generate_btst_opening_watch_card_artifacts_impl,
    generate_btst_premarket_execution_card_artifacts as _generate_btst_premarket_execution_card_artifacts_impl,
    register_btst_followup_artifacts as _register_btst_followup_artifacts_impl,
    resolve_followup_artifact_context as _resolve_followup_artifact_context_impl,
)
from src.project_env import load_project_dotenv
from src.tools.akshare_api import get_prices_robust
from src.tools.api import get_price_data, prices_to_df
from src.paper_trading._btst_reporting.extractors import (
    _resolve_upstream_shadow_candidate_reason_codes,
    _build_upstream_shadow_promotion_trigger,
    _extract_short_trade_core_metrics,
    _extract_upstream_shadow_replay_only_entry,
    RESEARCH_UPSIDE_RADAR_MAX_ENTRIES,
)
from src.paper_trading._btst_reporting.classifiers import (
    _classify_historical_prior,
    _classify_execution_quality_prior,
)


load_project_dotenv()


CATALYST_THEME_MAX_ENTRIES = 5
CATALYST_THEME_SHADOW_MAX_ENTRIES = 5
CATALYST_THEME_SHADOW_WATCH_MAX_ENTRIES = 3


def _extract_upstream_shadow_entry(
    selection_entry: dict[str, Any], supplemental_entry: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    short_trade_entry = dict(selection_entry.get("short_trade") or {})
    if not short_trade_entry:
        return None

    explainability_payload = dict(short_trade_entry.get("explainability_payload") or {})
    replay_context = dict(explainability_payload.get("replay_context") or {})
    candidate_source = _resolve_upstream_shadow_candidate_source(
        selection_entry, explainability_payload, replay_context
    )
    if candidate_source not in UPSTREAM_SHADOW_CANDIDATE_SOURCES:
        return None

    supplemental_entry = dict(supplemental_entry or {})
    metrics_payload = dict(short_trade_entry.get("metrics_payload") or {})
    candidate_reason_codes = _resolve_upstream_shadow_candidate_reason_codes(
        selection_entry, supplemental_entry, replay_context
    )
    candidate_pool_lane = str(
        supplemental_entry.get("candidate_pool_lane")
        or replay_context.get("candidate_pool_lane")
        or _source_lane_label(candidate_source)
    )
    candidate_pool_rank = supplemental_entry.get(
        "candidate_pool_rank"
    ) or replay_context.get("candidate_pool_rank")
    decision = str(short_trade_entry.get("decision") or "rejected")
    promotion_trigger = _build_upstream_shadow_promotion_trigger(decision)

    return {
        "ticker": selection_entry.get("ticker"),
        "decision": decision,
        "score_target": short_trade_entry.get("score_target"),
        "confidence": short_trade_entry.get("confidence"),
        "preferred_entry_mode": short_trade_entry.get("preferred_entry_mode"),
        "candidate_source": candidate_source,
        "candidate_pool_lane": candidate_pool_lane,
        "candidate_pool_lane_display": _source_lane_display(candidate_source),
        "candidate_pool_rank": int(candidate_pool_rank)
        if candidate_pool_rank not in (None, "")
        else None,
        "candidate_pool_avg_amount_share_of_cutoff": _round_or_none(
            supplemental_entry.get("candidate_pool_avg_amount_share_of_cutoff")
            or replay_context.get("candidate_pool_avg_amount_share_of_cutoff")
        ),
        "candidate_pool_avg_amount_share_of_min_gate": _round_or_none(
            supplemental_entry.get("candidate_pool_avg_amount_share_of_min_gate")
            or replay_context.get("candidate_pool_avg_amount_share_of_min_gate")
        ),
        "upstream_candidate_source": str(
            supplemental_entry.get("upstream_candidate_source")
            or replay_context.get("upstream_candidate_source")
            or "candidate_pool_truncated_after_filters"
        ),
        "candidate_reason_codes": candidate_reason_codes,
        "top_reasons": list(short_trade_entry.get("top_reasons") or []),
        "rejection_reasons": list(short_trade_entry.get("rejection_reasons") or []),
        "positive_tags": list(short_trade_entry.get("positive_tags") or []),
        "gate_status": dict(short_trade_entry.get("gate_status") or {}),
        "promotion_trigger": promotion_trigger,
        "metrics": _extract_short_trade_core_metrics(metrics_payload),
    }


def _resolve_upstream_shadow_candidate_source(
    selection_entry: dict[str, Any],
    explainability_payload: dict[str, Any],
    replay_context: dict[str, Any],
) -> str:
    return str(
        explainability_payload.get("candidate_source")
        or selection_entry.get("candidate_source")
        or replay_context.get("source")
        or ""
    )


def _build_upstream_shadow_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    lane_counts: dict[str, int] = {}
    decision_counts: dict[str, int] = {}
    for entry in entries:
        lane = str(
            entry.get("candidate_pool_lane")
            or _source_lane_label(entry.get("candidate_source"))
        )
        decision = str(entry.get("decision") or "rejected")
        lane_counts[lane] = int(lane_counts.get(lane) or 0) + 1
        decision_counts[decision] = int(decision_counts.get(decision) or 0) + 1

    top_focus_tickers = [
        str(entry.get("ticker") or "") for entry in entries if entry.get("ticker")
    ][:3]
    return {
        "shadow_candidate_count": len(entries),
        "promotable_count": sum(
            1
            for entry in entries
            if str(entry.get("decision") or "") in {"selected", "near_miss"}
        ),
        "lane_counts": lane_counts,
        "decision_counts": decision_counts,
        "top_focus_tickers": top_focus_tickers,
    }


def _extract_catalyst_theme_frontier_summary(
    frontier: dict[str, Any],
) -> dict[str, Any]:
    if not frontier:
        return {}

    recommended_variant = dict(frontier.get("recommended_variant") or {})
    promoted_shadow_count = int(recommended_variant.get("promoted_shadow_count") or 0)
    shadow_candidate_count = int(frontier.get("shadow_candidate_count") or 0)
    baseline_selected_count = int(frontier.get("baseline_selected_count") or 0)
    if promoted_shadow_count > 0:
        status = "promotable_shadow_exists"
    elif shadow_candidate_count > 0:
        status = "shadow_only_no_promotion"
    elif baseline_selected_count > 0:
        status = "selected_only_no_shadow"
    else:
        status = "no_catalyst_theme_candidates"

    top_promoted_rows = list(recommended_variant.get("top_promoted_rows") or [])
    return {
        "status": status,
        "shadow_candidate_count": shadow_candidate_count,
        "baseline_selected_count": baseline_selected_count,
        "recommended_variant_name": recommended_variant.get("variant_name"),
        "recommended_promoted_shadow_count": promoted_shadow_count,
        "recommended_relaxation_cost": recommended_variant.get(
            "threshold_relaxation_cost"
        ),
        "recommended_thresholds": dict(recommended_variant.get("thresholds") or {}),
        "recommended_promoted_tickers": [
            str(row.get("ticker") or "")
            for row in top_promoted_rows
            if row.get("ticker")
        ][:3],
        "recommendation": frontier.get("recommendation"),
    }


def _load_catalyst_theme_frontier_summary(
    report_dir: str | Path | None,
) -> dict[str, Any]:
    if not report_dir:
        return {}

    resolved_report_dir = Path(report_dir).expanduser().resolve()
    frontier_json_path = resolved_report_dir / "catalyst_theme_frontier_latest.json"
    if not frontier_json_path.exists():
        return {}

    summary = _extract_catalyst_theme_frontier_summary(_load_json(frontier_json_path))
    if not summary:
        return {}
    frontier_markdown_path = resolved_report_dir / "catalyst_theme_frontier_latest.md"
    summary["json_path"] = str(frontier_json_path)
    summary["markdown_path"] = (
        str(frontier_markdown_path.resolve())
        if frontier_markdown_path.exists()
        else None
    )
    return summary


def _build_catalyst_theme_frontier_priority(
    frontier_summary: dict[str, Any], shadow_entries: list[dict[str, Any]]
) -> dict[str, Any]:
    if not frontier_summary:
        return {}

    promoted_tickers = [
        str(ticker or "")
        for ticker in list(frontier_summary.get("recommended_promoted_tickers") or [])
        if ticker
    ]
    promoted_entries = [
        entry
        for entry in shadow_entries
        if str(entry.get("ticker") or "") in promoted_tickers
    ]
    return {
        "status": frontier_summary.get("status"),
        "recommended_variant_name": frontier_summary.get("recommended_variant_name"),
        "recommended_relaxation_cost": frontier_summary.get(
            "recommended_relaxation_cost"
        ),
        "recommended_thresholds": dict(
            frontier_summary.get("recommended_thresholds") or {}
        ),
        "promoted_shadow_count": len(promoted_entries)
        or int(frontier_summary.get("recommended_promoted_shadow_count") or 0),
        "promoted_tickers": promoted_tickers,
        "recommendation": frontier_summary.get("recommendation"),
        "markdown_path": frontier_summary.get("markdown_path"),
        "promoted_shadow_watch": _build_catalyst_theme_shadow_watch_rows(
            promoted_entries, limit=max(len(promoted_entries), 1)
        )
        if promoted_entries
        else [],
    }


def _resolve_snapshot_path(
    input_path: str | Path, trade_date: str | None
) -> tuple[Path, Path]:
    resolved_input = Path(input_path).expanduser().resolve()

    if resolved_input.is_file():
        if resolved_input.name != "selection_snapshot.json":
            raise ValueError(
                "input_path must be a report directory or a selection_snapshot.json file"
            )
        return resolved_input, resolved_input.parents[2]

    if not resolved_input.is_dir():
        raise FileNotFoundError(f"Input path does not exist: {resolved_input}")

    artifacts_dir = resolved_input / "selection_artifacts"
    if not artifacts_dir.exists():
        raise FileNotFoundError(
            f"selection_artifacts directory not found under: {resolved_input}"
        )

    normalized_trade_date = _normalize_trade_date(trade_date)
    if normalized_trade_date:
        candidate = artifacts_dir / normalized_trade_date / "selection_snapshot.json"
        if not candidate.exists():
            raise FileNotFoundError(
                f"selection_snapshot.json not found for trade_date={normalized_trade_date}: {candidate}"
            )
        return candidate, resolved_input

    trade_date_dirs = sorted(path for path in artifacts_dir.iterdir() if path.is_dir())
    if not trade_date_dirs:
        raise FileNotFoundError(
            f"No trade_date directories found under: {artifacts_dir}"
        )
    latest_trade_dir = trade_date_dirs[-1]
    candidate = latest_trade_dir / "selection_snapshot.json"
    if not candidate.exists():
        raise FileNotFoundError(
            f"selection_snapshot.json not found under latest trade_date directory: {candidate}"
        )
    return candidate, resolved_input


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


def _looks_like_paper_trading_report_dir(path: Path) -> bool:
    return (
        path.is_dir()
        and path.name.startswith("paper_trading")
        and (path / "session_summary.json").exists()
        and (path / "selection_artifacts").exists()
    )


def _iter_selection_snapshot_paths(report_dir: Path) -> list[Path]:
    selection_artifacts_dir = report_dir / "selection_artifacts"
    if not selection_artifacts_dir.exists():
        return []
    return [
        snapshot_path
        for snapshot_path in sorted(
            selection_artifacts_dir.glob("*/selection_snapshot.json")
        )
        if snapshot_path.is_file()
    ]


def _discover_recent_historical_report_dirs(
    report_dir: Path,
    trade_date: str | None,
    max_reports: int = OPPORTUNITY_POOL_HISTORICAL_LOOKBACK_REPORTS,
) -> list[Path]:
    reports_root = report_dir.parent
    if not reports_root.exists():
        return []

    candidates: list[tuple[str, int, str, Path]] = []
    for candidate in reports_root.iterdir():
        if (
            candidate.resolve() == report_dir.resolve()
            or not _looks_like_paper_trading_report_dir(candidate)
        ):
            continue
        snapshot_paths = _iter_selection_snapshot_paths(candidate)
        latest_trade_date = (
            _normalize_trade_date(snapshot_paths[-1].parent.name)
            if snapshot_paths
            else None
        )
        if trade_date and latest_trade_date and latest_trade_date >= trade_date:
            continue
        candidates.append(
            (
                latest_trade_date or "",
                candidate.stat().st_mtime_ns,
                candidate.name,
                candidate,
            )
        )

    candidates.sort(reverse=True)
    return [candidate for _, _, _, candidate in candidates[:max_reports]]


def _extract_short_trade_entry(
    selection_entry: dict[str, Any],
) -> dict[str, Any] | None:
    short_trade_entry = selection_entry.get("short_trade") or {}
    decision = short_trade_entry.get("decision")
    if decision not in {"selected", "near_miss"}:
        return None

    metrics_payload = short_trade_entry.get("metrics_payload") or {}
    explainability_payload = short_trade_entry.get("explainability_payload") or {}
    candidate_reason_codes = [
        str(reason)
        for reason in list(selection_entry.get("candidate_reason_codes") or [])
        if str(reason or "").strip()
    ]
    catalyst_relief = dict(
        explainability_payload.get("upstream_shadow_catalyst_relief") or {}
    )
    short_trade_catalyst_relief_reason = (
        str(catalyst_relief.get("reason") or "")
        if catalyst_relief
        and (
            bool(catalyst_relief.get("applied")) or bool(catalyst_relief.get("enabled"))
        )
        else None
    )

    return {
        "ticker": selection_entry.get("ticker"),
        "decision": decision,
        "reporting_decision": decision,
        "score_target": short_trade_entry.get("score_target"),
        "confidence": short_trade_entry.get("confidence"),
        "rank_hint": short_trade_entry.get("rank_hint"),
        "preferred_entry_mode": short_trade_entry.get("preferred_entry_mode"),
        "positive_tags": list(short_trade_entry.get("positive_tags") or []),
        "top_reasons": list(short_trade_entry.get("top_reasons") or []),
        "candidate_source": explainability_payload.get("candidate_source")
        or selection_entry.get("candidate_source"),
        "candidate_reason_codes": candidate_reason_codes,
        "short_trade_catalyst_relief_reason": short_trade_catalyst_relief_reason,
        "gate_status": dict(short_trade_entry.get("gate_status") or {}),
        "metrics": {
            "breakout_freshness": metrics_payload.get("breakout_freshness"),
            "trend_acceleration": metrics_payload.get("trend_acceleration"),
            "volume_expansion_quality": metrics_payload.get("volume_expansion_quality"),
            "close_strength": metrics_payload.get("close_strength"),
            "catalyst_freshness": metrics_payload.get("catalyst_freshness"),
        },
        "historical_prior": dict(
            short_trade_entry.get("historical_prior")
            or explainability_payload.get("historical_prior")
            or {}
        ),
    }


def _build_opportunity_pool_promotion_trigger(metrics_payload: dict[str, Any]) -> str:
    breakout_freshness = _as_float(metrics_payload.get("breakout_freshness"))
    trend_acceleration = _as_float(metrics_payload.get("trend_acceleration"))
    close_strength = _as_float(metrics_payload.get("close_strength"))
    catalyst_freshness = _as_float(metrics_payload.get("catalyst_freshness"))

    if (
        breakout_freshness >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN
        and trend_acceleration >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN
    ):
        return "若盘中 breakout 与 trend 强度继续抬升，可升级为观察票。"
    if catalyst_freshness >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN:
        return "若催化延续并出现量价确认，可升级为观察票。"
    if close_strength >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN:
        return "若开盘后 close-strength 类信号延续，可升级为观察票。"
    return "只有盘中新增强度确认时，才允许从机会池升级。"


def _apply_execution_quality_entry_mode(entry: dict[str, Any]) -> dict[str, Any]:
    historical_prior = dict(entry.get("historical_prior") or {})
    execution_quality_label = str(
        historical_prior.get("execution_quality_label") or "unknown"
    )
    updated_entry = dict(entry)
    updated_entry["historical_prior"] = historical_prior

    top_reasons = [
        str(reason)
        for reason in list(updated_entry.get("top_reasons") or [])
        if str(reason or "").strip()
    ]

    if execution_quality_label == "intraday_only":
        updated_entry["preferred_entry_mode"] = "intraday_confirmation_only"
        updated_entry["promotion_trigger"] = (
            "历史更像盘中确认后的 intraday 机会，不把默认隔夜持有当成升级方向。"
        )
        if "historical_intraday_only_execution" not in top_reasons:
            top_reasons.append("historical_intraday_only_execution")
    elif execution_quality_label == "gap_chase_risk":
        updated_entry["preferred_entry_mode"] = "avoid_open_chase_confirmation"
        updated_entry["promotion_trigger"] = (
            "若盘中回踩后重新走强可再确认，避免把开盘追价当成默认动作。"
        )
        if "historical_gap_chase_risk" not in top_reasons:
            top_reasons.append("historical_gap_chase_risk")
    elif execution_quality_label == "close_continuation":
        updated_entry["preferred_entry_mode"] = "confirm_then_hold_breakout"
        updated_entry["promotion_trigger"] = (
            "若盘中 continuation 确认后量价延续良好，可升级为 confirm-then-hold，而不是默认快进快出。"
        )
        if "historical_close_continuation" not in top_reasons:
            top_reasons.append("historical_close_continuation")
    elif execution_quality_label == "zero_follow_through":
        updated_entry["preferred_entry_mode"] = "strong_reconfirmation_only"
        updated_entry["promotion_trigger"] = (
            "历史同层兑现极弱，只有出现新的强确认时才允许重新升级。"
        )
        if "historical_zero_follow_through" not in top_reasons:
            top_reasons.append("historical_zero_follow_through")

    updated_entry["top_reasons"] = top_reasons
    return updated_entry


def _merge_entry_historical_prior(
    entry: dict[str, Any], historical_prior: dict[str, Any]
) -> dict[str, Any]:
    updated_entry = dict(entry)
    existing_historical_prior = dict(updated_entry.get("historical_prior") or {})
    preferred_historical_prior = _choose_preferred_historical_prior(
        existing_historical_prior, historical_prior
    )
    updated_entry["historical_prior"] = preferred_historical_prior
    return updated_entry


def _reclassify_selected_execution_quality_entries(
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    retained_selected_entries: list[dict[str, Any]] = []
    updated_near_miss_entries = list(near_miss_entries)
    updated_opportunity_pool_entries = list(opportunity_pool_entries)

    for entry in selected_entries:
        updated_entry = dict(entry)
        historical_prior = dict(updated_entry.get("historical_prior") or {})
        execution_quality_label = str(
            historical_prior.get("execution_quality_label") or "unknown"
        )
        evaluable_count = int(historical_prior.get("evaluable_count") or 0)
        next_close_positive_rate = _as_float(
            historical_prior.get("next_close_positive_rate")
        )

        if (
            execution_quality_label == "zero_follow_through"
            and evaluable_count >= WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT
        ):
            demoted_entry = dict(updated_entry)
            demoted_entry["demoted_from_decision"] = "selected"
            demoted_entry["reporting_bucket"] = "selected_execution_demoted"
            demoted_entry["reporting_decision"] = "opportunity_pool"
            demoted_entry["promotion_trigger"] = (
                "历史兑现几乎为 0，先降为机会池；只有盘中新强确认时再考虑回到观察层。"
            )
            top_reasons = [
                str(reason)
                for reason in list(demoted_entry.get("top_reasons") or [])
                if str(reason or "").strip()
            ]
            if "historical_zero_follow_through_selected_demoted" not in top_reasons:
                top_reasons.append("historical_zero_follow_through_selected_demoted")
            demoted_entry["top_reasons"] = top_reasons
            updated_opportunity_pool_entries.append(demoted_entry)
            continue

        if (
            execution_quality_label == "intraday_only"
            and evaluable_count >= WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT
            and next_close_positive_rate <= 0.0
        ):
            demoted_entry = dict(updated_entry)
            demoted_entry["demoted_from_decision"] = "selected"
            demoted_entry["reporting_bucket"] = "selected_execution_demoted"
            demoted_entry["reporting_decision"] = "near_miss"
            demoted_entry["promotion_trigger"] = (
                "历史更偏向盘中兑现而非收盘延续，先降为确认型观察票，不把隔夜持有当默认动作。"
            )
            top_reasons = [
                str(reason)
                for reason in list(demoted_entry.get("top_reasons") or [])
                if str(reason or "").strip()
            ]
            if "historical_intraday_only_selected_demoted" not in top_reasons:
                top_reasons.append("historical_intraday_only_selected_demoted")
            demoted_entry["top_reasons"] = top_reasons
            updated_near_miss_entries.append(demoted_entry)
            continue

        retained_selected_entries.append(updated_entry)

    return (
        retained_selected_entries,
        updated_near_miss_entries,
        updated_opportunity_pool_entries,
    )


def _extract_short_trade_opportunity_entry(
    selection_entry: dict[str, Any],
) -> dict[str, Any] | None:
    if (selection_entry.get("research") or {}).get("decision") == "selected":
        return None

    short_trade_entry = selection_entry.get("short_trade") or {}
    gate_status = dict(short_trade_entry.get("gate_status") or {})
    if not _is_short_trade_opportunity_candidate(short_trade_entry, gate_status):
        return None

    metrics_payload = dict(short_trade_entry.get("metrics_payload") or {})
    explainability_payload = dict(short_trade_entry.get("explainability_payload") or {})
    score_target = _as_float(short_trade_entry.get("score_target"))
    if score_target < OPPORTUNITY_POOL_MIN_SCORE_TARGET:
        return None

    positive_tags = list(short_trade_entry.get("positive_tags") or [])
    strong_signal_count = _count_short_trade_strong_signals(metrics_payload)
    if strong_signal_count <= 0 and not positive_tags:
        return None

    thresholds = dict(metrics_payload.get("thresholds") or {})
    near_miss_threshold = _as_float(thresholds.get("near_miss_threshold"))
    score_gap_to_near_miss = (
        round(max(0.0, near_miss_threshold - score_target), 4)
        if near_miss_threshold > 0
        else None
    )
    candidate_reason_codes = [
        str(reason)
        for reason in list(selection_entry.get("candidate_reason_codes") or [])
        if str(reason or "").strip()
    ]
    short_trade_catalyst_relief_reason = _extract_short_trade_catalyst_relief_reason(
        explainability_payload
    )

    return {
        "ticker": selection_entry.get("ticker"),
        "decision": short_trade_entry.get("decision"),
        "reporting_decision": "opportunity_pool",
        "score_target": short_trade_entry.get("score_target"),
        "confidence": short_trade_entry.get("confidence"),
        "preferred_entry_mode": short_trade_entry.get("preferred_entry_mode"),
        "candidate_source": (short_trade_entry.get("explainability_payload") or {}).get(
            "candidate_source"
        )
        or selection_entry.get("candidate_source"),
        "candidate_reason_codes": candidate_reason_codes,
        "short_trade_catalyst_relief_reason": short_trade_catalyst_relief_reason,
        "positive_tags": positive_tags,
        "top_reasons": list(short_trade_entry.get("top_reasons") or []),
        "rejection_reasons": list(short_trade_entry.get("rejection_reasons") or []),
        "gate_status": gate_status,
        "score_gap_to_near_miss": score_gap_to_near_miss,
        "promotion_trigger": _build_opportunity_pool_promotion_trigger(metrics_payload),
        "metrics": _extract_short_trade_core_metrics(metrics_payload),
        "historical_prior": dict(
            short_trade_entry.get("historical_prior")
            or explainability_payload.get("historical_prior")
            or {}
        ),
    }


def _is_short_trade_opportunity_candidate(
    short_trade_entry: dict[str, Any], gate_status: dict[str, Any]
) -> bool:
    return (
        short_trade_entry.get("decision") == "rejected"
        and gate_status.get("data") == "pass"
        and gate_status.get("structural") == "pass"
    )


def _count_short_trade_strong_signals(metrics_payload: dict[str, Any]) -> int:
    metrics = (
        _as_float(metrics_payload.get("breakout_freshness")),
        _as_float(metrics_payload.get("trend_acceleration")),
        _as_float(metrics_payload.get("volume_expansion_quality")),
        _as_float(metrics_payload.get("close_strength")),
        _as_float(metrics_payload.get("catalyst_freshness")),
    )
    return sum(metric >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN for metric in metrics)


def _extract_short_trade_catalyst_relief_reason(
    explainability_payload: dict[str, Any],
) -> str | None:
    catalyst_relief = dict(
        explainability_payload.get("upstream_shadow_catalyst_relief") or {}
    )
    if catalyst_relief and (
        bool(catalyst_relief.get("applied")) or bool(catalyst_relief.get("enabled"))
    ):
        return str(catalyst_relief.get("reason") or "")
    return None


def _extract_research_upside_radar_entry(
    selection_entry: dict[str, Any],
) -> dict[str, Any] | None:
    research_entry = selection_entry.get("research") or {}
    short_trade_entry = selection_entry.get("short_trade") or {}
    if research_entry.get("decision") != "selected":
        return None

    gate_status = dict(short_trade_entry.get("gate_status") or {})
    if not _is_short_trade_opportunity_candidate(short_trade_entry, gate_status):
        return None

    metrics_payload = dict(short_trade_entry.get("metrics_payload") or {})
    explainability_payload = dict(short_trade_entry.get("explainability_payload") or {})
    score_target = _as_float(short_trade_entry.get("score_target"))
    if score_target < OPPORTUNITY_POOL_MIN_SCORE_TARGET:
        return None

    positive_tags = list(short_trade_entry.get("positive_tags") or [])
    strong_signal_count = _count_short_trade_strong_signals(metrics_payload)
    if strong_signal_count <= 0 and not positive_tags:
        return None
    candidate_reason_codes = [
        str(reason)
        for reason in list(selection_entry.get("candidate_reason_codes") or [])
        if str(reason or "").strip()
    ]
    short_trade_catalyst_relief_reason = _extract_short_trade_catalyst_relief_reason(
        explainability_payload
    )

    return {
        "ticker": selection_entry.get("ticker"),
        "research_decision": research_entry.get("decision"),
        "research_score_target": research_entry.get("score_target"),
        "decision": short_trade_entry.get("decision"),
        "score_target": short_trade_entry.get("score_target"),
        "confidence": short_trade_entry.get("confidence"),
        "preferred_entry_mode": short_trade_entry.get("preferred_entry_mode"),
        "candidate_source": (short_trade_entry.get("explainability_payload") or {}).get(
            "candidate_source"
        )
        or selection_entry.get("candidate_source"),
        "candidate_reason_codes": candidate_reason_codes,
        "short_trade_catalyst_relief_reason": short_trade_catalyst_relief_reason,
        "positive_tags": positive_tags,
        "top_reasons": list(short_trade_entry.get("top_reasons") or []),
        "rejection_reasons": list(short_trade_entry.get("rejection_reasons") or []),
        "gate_status": gate_status,
        "delta_summary": list(selection_entry.get("delta_summary") or []),
        "radar_note": "research 已选中但 BTST 未放行，只做漏票雷达，不纳入明日 short-trade 交易名单。",
        "metrics": _extract_short_trade_core_metrics(metrics_payload),
        "historical_prior": dict(
            short_trade_entry.get("historical_prior")
            or explainability_payload.get("historical_prior")
            or {}
        ),
    }


def _extract_catalyst_theme_entry(candidate: dict[str, Any]) -> dict[str, Any] | None:
    if not candidate:
        return None

    metrics = dict(candidate.get("metrics") or {})
    explainability_payload = dict(candidate.get("explainability_payload") or {})
    candidate_reason_codes = [
        str(reason)
        for reason in list(candidate.get("candidate_reason_codes") or [])
        if str(reason or "").strip()
    ]
    short_trade_catalyst_relief = dict(
        candidate.get("short_trade_catalyst_relief") or {}
    )
    candidate_score = _as_float(
        candidate.get("score_target")
        if candidate.get("score_target") is not None
        else candidate.get("candidate_score")
    )
    if candidate_score <= 0:
        return None

    return {
        "ticker": candidate.get("ticker"),
        "decision": candidate.get("decision") or "catalyst_theme",
        "score_target": candidate_score,
        "confidence": candidate.get("confidence"),
        "preferred_entry_mode": candidate.get("preferred_entry_mode")
        or "theme_research_followup",
        "candidate_source": candidate.get("candidate_source") or "catalyst_theme",
        "candidate_reason_codes": candidate_reason_codes,
        "short_trade_catalyst_relief_reason": str(
            short_trade_catalyst_relief.get("reason") or ""
        )
        or None,
        "positive_tags": list(candidate.get("positive_tags") or []),
        "top_reasons": list(candidate.get("top_reasons") or []),
        "blockers": list(candidate.get("blockers") or []),
        "gate_status": dict(candidate.get("gate_status") or {}),
        "promotion_trigger": candidate.get("promotion_trigger")
        or "只做题材催化跟踪，不进入主池或 BTST 执行名单。",
        "metrics": {
            "breakout_freshness": metrics.get("breakout_freshness"),
            "trend_acceleration": metrics.get("trend_acceleration"),
            "close_strength": metrics.get("close_strength"),
            "sector_resonance": metrics.get("sector_resonance"),
            "catalyst_freshness": metrics.get("catalyst_freshness"),
        },
        "historical_prior": dict(
            candidate.get("historical_prior")
            or explainability_payload.get("historical_prior")
            or {}
        ),
    }


def _extract_catalyst_theme_shadow_entry(
    candidate: dict[str, Any],
) -> dict[str, Any] | None:
    if not candidate:
        return None

    metrics = dict(candidate.get("metrics") or {})
    candidate_reason_codes = [
        str(reason)
        for reason in list(candidate.get("candidate_reason_codes") or [])
        if str(reason or "").strip()
    ]
    candidate_score = _as_float(
        candidate.get("score_target")
        if candidate.get("score_target") is not None
        else candidate.get("candidate_score")
    )
    if candidate_score <= 0:
        return None

    return {
        "ticker": candidate.get("ticker"),
        "decision": candidate.get("decision") or "catalyst_theme_shadow",
        "score_target": candidate_score,
        "confidence": candidate.get("confidence"),
        "preferred_entry_mode": candidate.get("preferred_entry_mode")
        or "theme_research_followup",
        "candidate_source": candidate.get("candidate_source")
        or "catalyst_theme_shadow",
        "candidate_reason_codes": candidate_reason_codes,
        "positive_tags": list(candidate.get("positive_tags") or []),
        "top_reasons": list(candidate.get("top_reasons") or []),
        "blockers": list(candidate.get("blockers") or []),
        "gate_status": dict(candidate.get("gate_status") or {}),
        "promotion_trigger": candidate.get("promotion_trigger")
        or "继续跟踪催化与结构缺口，不进入正式题材研究池或 BTST 执行名单。",
        "filter_reason": candidate.get("filter_reason"),
        "failed_threshold_count": int(candidate.get("failed_threshold_count") or 0),
        "total_shortfall": _round_or_none(candidate.get("total_shortfall")),
        "threshold_shortfalls": dict(candidate.get("threshold_shortfalls") or {}),
        "metrics": {
            "breakout_freshness": metrics.get("breakout_freshness"),
            "trend_acceleration": metrics.get("trend_acceleration"),
            "close_strength": metrics.get("close_strength"),
            "sector_resonance": metrics.get("sector_resonance"),
            "catalyst_freshness": metrics.get("catalyst_freshness"),
        },
    }


def _build_catalyst_theme_shadow_watch_rows(
    entries: list[dict[str, Any]],
    *,
    limit: int = CATALYST_THEME_SHADOW_WATCH_MAX_ENTRIES,
) -> list[dict[str, Any]]:
    ranked_entries = sorted(
        [dict(entry) for entry in entries if entry and entry.get("ticker")],
        key=lambda entry: (
            entry.get("total_shortfall")
            if entry.get("total_shortfall") is not None
            else 999.0,
            -_as_float(entry.get("score_target")),
            -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
            str(entry.get("ticker") or ""),
        ),
    )

    rows: list[dict[str, Any]] = []
    for entry in ranked_entries[:limit]:
        metrics = dict(entry.get("metrics") or {})
        rows.append(
            {
                "ticker": entry.get("ticker"),
                "candidate_score": entry.get("score_target"),
                "preferred_entry_mode": entry.get("preferred_entry_mode"),
                "candidate_source": entry.get("candidate_source"),
                "filter_reason": entry.get("filter_reason"),
                "failed_threshold_count": int(entry.get("failed_threshold_count") or 0),
                "total_shortfall": _round_or_none(entry.get("total_shortfall")),
                "threshold_shortfalls": dict(entry.get("threshold_shortfalls") or {}),
                "promotion_trigger": entry.get("promotion_trigger"),
                "positive_tags": list(entry.get("positive_tags") or []),
                "top_reasons": list(entry.get("top_reasons") or []),
                "metrics": {
                    "breakout_freshness": metrics.get("breakout_freshness"),
                    "trend_acceleration": metrics.get("trend_acceleration"),
                    "close_strength": metrics.get("close_strength"),
                    "sector_resonance": metrics.get("sector_resonance"),
                    "catalyst_freshness": metrics.get("catalyst_freshness"),
                },
            }
        )
    return rows


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


def _should_demote_weak_near_miss(historical_prior: dict[str, Any] | None) -> bool:
    prior = dict(historical_prior or {})
    evaluable_count = int(prior.get("evaluable_count") or 0)
    if evaluable_count < WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT:
        return False
    next_high_hit_rate = _as_float(prior.get("next_high_hit_rate_at_threshold"))
    next_close_positive_rate = _as_float(prior.get("next_close_positive_rate"))
    return next_high_hit_rate <= 0.0 and next_close_positive_rate <= 0.0


def _demote_weak_near_miss_entries(
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    retained_entries: list[dict[str, Any]] = []
    updated_opportunity_pool_entries = list(opportunity_pool_entries)
    for entry in near_miss_entries:
        historical_prior = dict(entry.get("historical_prior") or {})
        if not _should_demote_weak_near_miss(historical_prior):
            retained_entries.append(entry)
            continue

        demoted_entry = dict(entry)
        demoted_prior = dict(historical_prior)
        demoted_prior["demoted_from_near_miss"] = True
        demoted_prior["demotion_reason"] = "historical_zero_follow_through"
        demoted_prior["summary"] = (
            (demoted_prior.get("summary") or "")
            + (" " if demoted_prior.get("summary") else "")
            + "历史同层兑现为 0，降级到机会池等待新增强度。"
        )
        demoted_entry["historical_prior"] = demoted_prior
        demoted_entry["demoted_from_decision"] = "near_miss"
        demoted_entry["reporting_bucket"] = "opportunity_pool_demoted"
        demoted_entry["reporting_decision"] = "opportunity_pool"
        demoted_entry["promotion_trigger"] = (
            "历史同层兑现极弱，先降为机会池；只有盘中新强度确认时再考虑回到观察层。"
        )
        top_reasons = [
            str(reason)
            for reason in list(demoted_entry.get("top_reasons") or [])
            if str(reason or "").strip()
        ]
        if "historical_zero_follow_through_demoted" not in top_reasons:
            top_reasons.append("historical_zero_follow_through_demoted")
        demoted_entry["top_reasons"] = top_reasons
        updated_opportunity_pool_entries.append(demoted_entry)
    return retained_entries, updated_opportunity_pool_entries


def _should_prune_weak_opportunity_pool_entry(historical_prior: dict[str, Any]) -> bool:
    prior = dict(historical_prior or {})
    execution_quality_label = str(prior.get("execution_quality_label") or "unknown")
    evaluable_count = int(prior.get("evaluable_count") or 0)
    if evaluable_count < WEAK_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT:
        return False
    next_high_hit_rate = _as_float(prior.get("next_high_hit_rate_at_threshold"))
    next_close_positive_rate = _as_float(prior.get("next_close_positive_rate"))
    next_open_to_close_return_mean = _as_float(
        prior.get("next_open_to_close_return_mean")
    )
    if (
        next_high_hit_rate <= 0.0
        and next_close_positive_rate <= 0.0
        and next_open_to_close_return_mean < 0.0
    ):
        return True
    return (
        execution_quality_label == "balanced_confirmation"
        and evaluable_count >= WEAK_BALANCED_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT
        and next_high_hit_rate <= WEAK_BALANCED_OPPORTUNITY_POOL_MAX_NEXT_HIGH_HIT_RATE
        and next_close_positive_rate
        < WEAK_BALANCED_OPPORTUNITY_POOL_MAX_NEXT_CLOSE_POSITIVE_RATE
        and next_open_to_close_return_mean < 0.0
    )


def _should_prune_mixed_boundary_opportunity_pool_entry(
    entry: dict[str, Any], historical_prior: dict[str, Any]
) -> bool:
    prior = dict(historical_prior or {})
    if str(entry.get("candidate_source") or "") != "short_trade_boundary":
        return False
    if (
        str(prior.get("execution_quality_label") or "unknown")
        != "balanced_confirmation"
    ):
        return False
    if str(prior.get("applied_scope") or "none") != "family_source_score_catalyst":
        return False
    evaluable_count = int(prior.get("evaluable_count") or 0)
    if evaluable_count < MIXED_BOUNDARY_OPPORTUNITY_POOL_PRUNE_MIN_EVALUABLE_COUNT:
        return False
    top_reasons = {
        str(reason or "").strip()
        for reason in list(entry.get("top_reasons") or [])
        if str(reason or "").strip()
    }
    if "profitability_hard_cliff" not in top_reasons:
        return False
    if (
        _as_float(entry.get("score_target"))
        >= MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_SCORE_TARGET
    ):
        return False
    breakout_freshness = _as_float(
        (entry.get("metrics") or {}).get("breakout_freshness")
    )
    next_high_hit_rate = _as_float(prior.get("next_high_hit_rate_at_threshold"))
    next_close_positive_rate = _as_float(prior.get("next_close_positive_rate"))
    return (
        breakout_freshness < MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_BREAKOUT_FRESHNESS
        and next_high_hit_rate <= MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_NEXT_HIGH_HIT_RATE
        and next_close_positive_rate
        <= MIXED_BOUNDARY_OPPORTUNITY_POOL_MAX_NEXT_CLOSE_POSITIVE_RATE
    )


def _should_rebucket_no_history_opportunity_pool_entry(
    historical_prior: dict[str, Any],
) -> bool:
    prior = dict(historical_prior or {})
    execution_quality_label = str(prior.get("execution_quality_label") or "unknown")
    evaluable_count = int(prior.get("evaluable_count") or 0)
    applied_scope = str(prior.get("applied_scope") or "none")
    return (
        execution_quality_label == "unknown"
        and evaluable_count <= 0
        and applied_scope == "none"
    )


def _should_prune_low_score_no_history_opportunity_pool_entry(
    entry: dict[str, Any], historical_prior: dict[str, Any]
) -> bool:
    if not _should_rebucket_no_history_opportunity_pool_entry(historical_prior):
        return False
    if str(entry.get("candidate_source") or "") != "upstream_liquidity_corridor_shadow":
        return False
    top_reasons = {
        str(reason or "").strip()
        for reason in list(entry.get("top_reasons") or [])
        if str(reason or "").strip()
    }
    if "prepared_breakout" not in top_reasons or "confirmed_breakout" in top_reasons:
        return False
    if not any(reason.startswith("score_short=") for reason in top_reasons):
        return False
    return (
        _as_float(entry.get("score_target"))
        < LOW_SCORE_NO_HISTORY_UPSTREAM_MAX_SCORE_TARGET
    )


def _should_prune_weak_catalyst_no_history_opportunity_pool_entry(
    entry: dict[str, Any], historical_prior: dict[str, Any]
) -> bool:
    if not _should_rebucket_no_history_opportunity_pool_entry(historical_prior):
        return False
    if str(entry.get("candidate_source") or "") != "catalyst_theme":
        return False
    top_reasons = {
        str(reason or "").strip()
        for reason in list(entry.get("top_reasons") or [])
        if str(reason or "").strip()
    }
    return (
        "confirmed_breakout" in top_reasons
        and "profitability_hard_cliff" not in top_reasons
    )


def _partition_opportunity_pool_entries(
    opportunity_pool_entries: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    retained_entries: list[dict[str, Any]] = []
    no_history_observer_entries: list[dict[str, Any]] = []
    risky_observer_entries: list[dict[str, Any]] = []
    pruned_entries: list[dict[str, Any]] = []

    for entry in opportunity_pool_entries:
        updated_entry = dict(entry)
        historical_prior = dict(updated_entry.get("historical_prior") or {})
        bucket_name, bucket_entry = _classify_opportunity_pool_entry(
            updated_entry=updated_entry,
            historical_prior=historical_prior,
        )
        if bucket_name == "weak_history_pruned":
            pruned_entries.append(bucket_entry)
            continue
        if bucket_name == "no_history_observer":
            no_history_observer_entries.append(bucket_entry)
            continue
        if bucket_name == "risky_observer":
            risky_observer_entries.append(bucket_entry)
            continue
        retained_entries.append(bucket_entry)

    return (
        retained_entries,
        no_history_observer_entries,
        risky_observer_entries,
        pruned_entries,
    )


def _classify_opportunity_pool_entry(
    *,
    updated_entry: dict[str, Any],
    historical_prior: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    pruned_bucket = _classify_pruned_opportunity_pool_entry(
        updated_entry, historical_prior
    )
    if pruned_bucket is not None:
        return pruned_bucket

    no_history_bucket = _classify_no_history_opportunity_pool_entry(
        updated_entry, historical_prior
    )
    if no_history_bucket is not None:
        return no_history_bucket

    risky_bucket = _classify_risky_opportunity_pool_entry(
        updated_entry, historical_prior
    )
    if risky_bucket is not None:
        return risky_bucket
    return "retained", updated_entry


def _classify_pruned_opportunity_pool_entry(
    updated_entry: dict[str, Any],
    historical_prior: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    if _should_prune_weak_opportunity_pool_entry(historical_prior):
        return "weak_history_pruned", _build_reporting_bucket_entry(
            updated_entry,
            historical_prior,
            bucket="weak_history_pruned",
            flag_key="pruned_from_opportunity_pool",
            reason_key="prune_reason",
            reason_value="historical_zero_follow_through",
            summary_suffix="历史兑现接近 0，已从机会池移除。",
            promotion_trigger="历史兑现接近 0，不进入机会池；除非后续出现新的独立强确认，否则只保留低优先级影子观察。",
            top_reason="historical_zero_follow_through_pruned",
        )
    if _should_prune_low_score_no_history_opportunity_pool_entry(
        updated_entry, historical_prior
    ):
        return "weak_history_pruned", _build_reporting_bucket_entry(
            updated_entry,
            historical_prior,
            bucket="weak_history_pruned",
            flag_key="pruned_from_opportunity_pool",
            reason_key="prune_reason",
            reason_value="no_history_low_score_prepared_breakout",
            summary_suffix="暂无可评估历史先验，且当前仅是低分 prepared-breakout，已移出观察桶。",
            promotion_trigger="缺少历史先验且当前分数/形态偏弱，不保留在观察桶；除非后续出现新的独立强确认，否则不再继续跟踪。",
            top_reason="no_history_low_score_pruned",
        )
    if _should_prune_mixed_boundary_opportunity_pool_entry(
        updated_entry, historical_prior
    ):
        return "weak_history_pruned", _build_reporting_bucket_entry(
            updated_entry,
            historical_prior,
            bucket="weak_history_pruned",
            flag_key="pruned_from_opportunity_pool",
            reason_key="prune_reason",
            reason_value="mixed_boundary_follow_through",
            summary_suffix="同层同源同分桶历史仅属混合延续质量，且当前仍受 profitability_hard_cliff 压制，已移出标准机会池。",
            promotion_trigger="历史延续质量只有中性混合，且当前仍受 profitability_hard_cliff 压制；除非后续出现新的独立强确认，否则不再占用标准机会池名额。",
            top_reason="mixed_boundary_follow_through_pruned",
        )
    if _should_prune_weak_catalyst_no_history_opportunity_pool_entry(
        updated_entry, historical_prior
    ):
        return "weak_history_pruned", _build_reporting_bucket_entry(
            updated_entry,
            historical_prior,
            bucket="weak_history_pruned",
            flag_key="pruned_from_opportunity_pool",
            reason_key="prune_reason",
            reason_value="catalyst_no_history_without_profitability_support",
            summary_suffix="暂无可评估历史先验，且题材 confirmed-breakout 缺少 profitability_hard_cliff 支撑，已移出观察桶。",
            promotion_trigger="缺少历史先验且题材强度支撑不足，不保留在观察桶；除非后续出现新的独立强确认，否则不再继续跟踪。",
            top_reason="catalyst_no_history_pruned",
        )
    return None


def _classify_no_history_opportunity_pool_entry(
    updated_entry: dict[str, Any],
    historical_prior: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    if _should_rebucket_no_history_opportunity_pool_entry(historical_prior):
        return "no_history_observer", _build_reporting_bucket_entry(
            updated_entry,
            historical_prior,
            bucket="no_history_observer",
            flag_key="rebucketed_from_opportunity_pool",
            reason_key="rebucket_reason",
            reason_value="no_evaluable_history",
            summary_suffix="暂无可评估历史先验，已移入 no-history observer。",
            promotion_trigger="暂无可评估历史先验；只有盘中新证据显著增强时，才允许从 no-history observer 升级。",
            top_reason="no_history_observer_rebucket",
        )
    return None


def _classify_risky_opportunity_pool_entry(
    updated_entry: dict[str, Any],
    historical_prior: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    if (
        str(historical_prior.get("execution_quality_label") or "unknown")
        in RISKY_OBSERVER_EXECUTION_QUALITY_LABELS
    ):
        risky_entry = dict(updated_entry)
        risky_entry["reporting_bucket"] = "risky_observer"
        risky_entry["promotion_trigger"] = (
            "只做高风险盘中确认观察，不作为标准 BTST 机会池升级对象。"
        )
        return "risky_observer", risky_entry
    return None


def _build_reporting_bucket_entry(
    entry: dict[str, Any],
    historical_prior: dict[str, Any],
    *,
    bucket: str,
    flag_key: str,
    reason_key: str,
    reason_value: str,
    summary_suffix: str,
    promotion_trigger: str,
    top_reason: str | None = None,
) -> dict[str, Any]:
    updated_entry = dict(entry)
    updated_prior = dict(historical_prior)
    updated_prior[flag_key] = True
    updated_prior[reason_key] = reason_value
    updated_prior["summary"] = (
        (updated_prior.get("summary") or "")
        + (" " if updated_prior.get("summary") else "")
        + summary_suffix
    )
    updated_entry["historical_prior"] = updated_prior
    updated_entry["reporting_bucket"] = bucket
    updated_entry["promotion_trigger"] = promotion_trigger
    if top_reason:
        top_reasons = [
            str(reason)
            for reason in list(updated_entry.get("top_reasons") or [])
            if str(reason or "").strip()
        ]
        if top_reason not in top_reasons:
            top_reasons.append(top_reason)
        updated_entry["top_reasons"] = top_reasons
    return updated_entry


def _append_primary_and_near_miss_recommendations(
    recommendation_lines: list[str],
    *,
    primary_entry: dict[str, Any] | None,
    near_miss_entries: list[dict[str, Any]],
) -> None:
    _append_primary_and_near_miss_recommendations_impl(
        recommendation_lines,
        primary_entry=primary_entry,
        near_miss_entries=near_miss_entries,
        selected_holding_contract_note=_selected_holding_contract_note,
    )


def _append_pool_and_observer_recommendations(
    recommendation_lines: list[str],
    *,
    opportunity_pool_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
) -> None:
    _append_pool_and_observer_recommendations_impl(
        recommendation_lines,
        opportunity_pool_entries=opportunity_pool_entries,
        risky_observer_entries=risky_observer_entries,
        no_history_observer_entries=no_history_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
    )


def _append_opportunity_pool_recommendation_lines(
    recommendation_lines: list[str], *, opportunity_pool_entries: list[dict[str, Any]]
) -> None:
    _append_recommendation_line_if_entries(
        recommendation_lines,
        opportunity_pool_entries,
        prefix="自动扩容候选池为 ",
        suffix="，这些票结构未坏，但还没进入正式名单，只能在盘中新增强度确认后升级。",
    )
    _append_historical_prior_recommendation(
        recommendation_lines,
        entries=opportunity_pool_entries,
        prefix="机会池历史先验参考: ",
    )


def _append_observer_bucket_recommendation_lines(
    recommendation_lines: list[str],
    *,
    risky_observer_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    weak_history_pruned_entries: list[dict[str, Any]],
) -> None:
    _append_recommendation_line_if_entries(
        recommendation_lines,
        risky_observer_entries,
        prefix="高风险观察桶为 ",
        suffix="，这些票更像盘中确认/避免追高对象，不与标准 BTST 机会池混用。",
    )
    _append_recommendation_line_if_entries(
        recommendation_lines,
        no_history_observer_entries,
        prefix="无历史先验观察桶为 ",
        suffix="，这些票暂无可评估历史先验，不再占用标准 BTST 机会池名额，只保留盘中新证据观察。",
    )
    _append_recommendation_line_if_entries(
        recommendation_lines,
        weak_history_pruned_entries,
        prefix="已从标准观察池剔除的低质量样本有 ",
        suffix="，这些名字要么历史兑现接近 0，要么缺少历史先验且当前分数/形态偏弱，不应继续占用明日观察名额。",
    )


def _append_recommendation_line_if_entries(
    recommendation_lines: list[str],
    entries: list[dict[str, Any]],
    *,
    prefix: str,
    suffix: str,
) -> None:
    _append_recommendation_line_if_tickers(
        recommendation_lines,
        [entry["ticker"] for entry in entries],
        prefix=prefix,
        suffix=suffix,
    )


def _append_recommendation_line_if_tickers(
    recommendation_lines: list[str],
    tickers: list[str],
    *,
    prefix: str,
    suffix: str,
) -> None:
    if tickers:
        recommendation_lines.append(prefix + ", ".join(tickers) + suffix)


def _append_historical_prior_recommendation(
    recommendation_lines: list[str],
    *,
    entries: list[dict[str, Any]],
    prefix: str,
) -> None:
    historical_prior_lines = [
        f"{entry['ticker']}={entry.get('historical_prior', {}).get('summary')}"
        for entry in entries
        if (entry.get("historical_prior") or {}).get("summary")
    ]
    if historical_prior_lines:
        recommendation_lines.append(prefix + "；".join(historical_prior_lines))


def _append_research_and_shadow_recommendations(
    recommendation_lines: list[str],
    *,
    research_upside_radar_entries: list[dict[str, Any]],
    catalyst_theme_entries: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
    catalyst_theme_shadow_entries: list[dict[str, Any]],
    excluded_research_entries: list[dict[str, Any]],
    upstream_shadow_entries: list[dict[str, Any]],
) -> None:
    _append_research_and_shadow_recommendations_impl(
        recommendation_lines,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
        catalyst_theme_frontier_priority=catalyst_theme_frontier_priority,
        catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
        excluded_research_entries=excluded_research_entries,
        upstream_shadow_entries=upstream_shadow_entries,
    )


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


def _build_btst_recommendation_lines(
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
    recommendation_lines: list[str] = []
    _append_btst_recommendation_line_groups(
        recommendation_lines=recommendation_lines,
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
    return recommendation_lines


def _append_btst_recommendation_line_groups(
    *,
    recommendation_lines: list[str],
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
) -> None:
    _append_primary_and_near_miss_recommendations(
        recommendation_lines,
        primary_entry=primary_entry,
        near_miss_entries=near_miss_entries,
    )
    _append_pool_and_observer_recommendations(
        recommendation_lines,
        opportunity_pool_entries=opportunity_pool_entries,
        risky_observer_entries=risky_observer_entries,
        no_history_observer_entries=no_history_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
    )
    _append_research_and_shadow_recommendations(
        recommendation_lines,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
        catalyst_theme_frontier_priority=catalyst_theme_frontier_priority,
        catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
        excluded_research_entries=excluded_research_entries,
        upstream_shadow_entries=upstream_shadow_entries,
    )


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
    return _build_btst_recommendation_lines(
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


def _append_brief_overview_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    historical_context = (
        analysis.get("btst_candidate_historical_context")
        or analysis.get("watch_candidate_historical_context")
        or analysis.get("opportunity_pool_historical_context")
        or {}
    )
    summary = analysis["summary"]
    lines.append("# BTST Next-Day Trade Brief")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- trade_date: {analysis.get('trade_date')}")
    lines.append(f"- next_trade_date: {analysis.get('next_trade_date') or 'n/a'}")
    lines.append(f"- target_mode: {analysis.get('target_mode')}")
    lines.append(f"- selection_target: {analysis.get('selection_target')}")
    lines.append(
        f"- short_trade_selected_count: {summary.get('short_trade_selected_count')}"
    )
    lines.append(
        f"- short_trade_near_miss_count: {summary.get('short_trade_near_miss_count')}"
    )
    lines.append(
        f"- short_trade_blocked_count: {summary.get('short_trade_blocked_count')}"
    )
    lines.append(
        f"- short_trade_rejected_count: {summary.get('short_trade_rejected_count')}"
    )
    lines.append(
        f"- short_trade_opportunity_pool_count: {summary.get('short_trade_opportunity_pool_count')}"
    )
    lines.append(
        f"- no_history_observer_count: {summary.get('no_history_observer_count')}"
    )
    lines.append(
        f"- research_upside_radar_count: {summary.get('research_upside_radar_count')}"
    )
    lines.append(f"- catalyst_theme_count: {summary.get('catalyst_theme_count')}")
    lines.append(
        f"- catalyst_theme_shadow_count: {summary.get('catalyst_theme_shadow_count')}"
    )
    lines.append(
        f"- catalyst_theme_frontier_promoted_count: {summary.get('catalyst_theme_frontier_promoted_count')}"
    )
    lines.append(
        f"- upstream_shadow_candidate_count: {summary.get('upstream_shadow_candidate_count')}"
    )
    lines.append(
        f"- upstream_shadow_promotable_count: {summary.get('upstream_shadow_promotable_count')}"
    )
    lines.append(
        f"- opportunity_pool_historical_report_count: {historical_context.get('historical_report_count')}"
    )
    lines.append(
        f"- btst_candidate_historical_count: {historical_context.get('historical_btst_candidate_count')}"
    )
    lines.append(
        f"- watch_candidate_historical_count: {historical_context.get('historical_watch_candidate_count')}"
    )
    lines.append(
        f"- watch_selected_historical_count: {historical_context.get('historical_selected_candidate_count')}"
    )
    lines.append(
        f"- watch_near_miss_historical_count: {historical_context.get('historical_near_miss_candidate_count')}"
    )
    lines.append(
        f"- opportunity_pool_historical_candidate_count: {historical_context.get('historical_opportunity_candidate_count')}"
    )
    lines.append(
        f"- research_upside_radar_historical_count: {historical_context.get('historical_research_upside_radar_count')}"
    )
    lines.append(
        f"- catalyst_theme_historical_count: {historical_context.get('historical_catalyst_theme_count')}"
    )
    lines.append(
        f"- excluded_research_selected_count: {len(analysis.get('excluded_research_entries') or [])}"
    )
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")


def _append_brief_scored_entries_markdown(
    lines: list[str], title: str, entries: list[dict[str, Any]]
) -> None:
    _append_brief_scored_entries_markdown_impl(
        lines,
        title,
        entries,
        append_brief_ticker_section=_append_brief_ticker_section,
        append_brief_historical_prior_fields=_append_brief_historical_prior_fields,
        append_brief_short_trade_metrics=_append_brief_short_trade_metrics,
        append_brief_historical_recent_examples=_append_brief_historical_recent_examples,
        append_gate_status_line=_append_gate_status_line,
        format_float=_format_float,
    )


def _append_brief_ticker_section(
    lines: list[str],
    *,
    title: str,
    entries: list[dict[str, Any]],
    render_entry: Callable[[list[str], dict[str, Any]], None],
) -> None:
    lines.append(f"## {title}")
    if not entries:
        _append_none_block(lines)
        return
    for entry in entries:
        lines.append(f"### {entry['ticker']}")
        render_entry(lines, entry)
        lines.append("")


def _append_brief_historical_prior_fields(
    lines: list[str],
    historical_prior: dict[str, Any],
    *,
    include_summary: bool = True,
    include_monitor_priority: bool = False,
    include_execution_quality: bool = False,
    include_execution_note: bool = False,
) -> None:
    if include_monitor_priority:
        lines.append(
            f"- historical_monitor_priority: {historical_prior.get('monitor_priority') or 'n/a'}"
        )
    if include_summary:
        lines.append(
            f"- historical_summary: {historical_prior.get('summary') or 'n/a'}"
        )
    if include_execution_quality:
        lines.append(
            f"- historical_execution_quality: {historical_prior.get('execution_quality_label') or 'n/a'}"
        )
    if include_execution_note:
        lines.append(
            f"- historical_execution_note: {historical_prior.get('execution_note') or 'n/a'}"
        )


def _append_brief_scored_entry_metrics(
    lines: list[str], metrics: dict[str, Any]
) -> None:
    _append_brief_short_trade_metrics(lines, metrics)


def _append_brief_short_trade_metrics(
    lines: list[str], metrics: dict[str, Any]
) -> None:
    lines.append(
        "- key_metrics: "
        + ", ".join(
            [
                f"breakout={_format_float(metrics.get('breakout_freshness'))}",
                f"trend={_format_float(metrics.get('trend_acceleration'))}",
                f"volume={_format_float(metrics.get('volume_expansion_quality'))}",
                f"close={_format_float(metrics.get('close_strength'))}",
                f"catalyst={_format_float(metrics.get('catalyst_freshness'))}",
            ]
        )
    )


def _append_brief_historical_recent_examples(
    lines: list[str], historical_prior: dict[str, Any]
) -> None:
    recent_examples = historical_prior.get("recent_examples") or []
    if recent_examples:
        lines.append(
            "- historical_recent_examples: "
            + "; ".join(
                f"{sample.get('trade_date')} {sample.get('ticker')} open={_format_float(sample.get('next_open_return'))}, high={_format_float(sample.get('next_high_return'))}, close={_format_float(sample.get('next_close_return'))}"
                for sample in recent_examples
            )
        )


def _append_brief_opportunity_pool_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    _append_brief_opportunity_pool_markdown_impl(
        lines,
        entries,
        append_brief_ticker_section=_append_brief_ticker_section,
        append_brief_historical_prior_fields=_append_brief_historical_prior_fields,
        append_brief_short_trade_metrics=_append_brief_short_trade_metrics,
        append_brief_historical_recent_examples=_append_brief_historical_recent_examples,
        append_gate_status_line=_append_gate_status_line,
        format_float=_format_float,
    )


def _append_gate_status_line(lines: list[str], gate_status: dict[str, Any]) -> None:
    lines.append(
        "- gate_status: "
        + ", ".join(f"{key}={value}" for key, value in gate_status.items())
    )


def _append_brief_observer_lane_markdown(
    lines: list[str],
    title: str,
    entries: list[dict[str, Any]],
    include_execution_note: bool,
) -> None:
    _append_brief_observer_lane_markdown_impl(
        lines,
        title,
        entries,
        include_execution_note,
        append_brief_ticker_section=_append_brief_ticker_section,
        append_brief_historical_prior_fields=_append_brief_historical_prior_fields,
    )


def _append_brief_pruned_entries_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    _append_brief_pruned_entries_markdown_impl(
        lines,
        entries,
        append_brief_ticker_section=_append_brief_ticker_section,
        append_brief_historical_prior_fields=_append_brief_historical_prior_fields,
    )


def _append_brief_research_radar_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    _append_brief_research_radar_markdown_impl(
        lines,
        entries,
        append_brief_ticker_section=_append_brief_ticker_section,
        append_brief_historical_prior_fields=_append_brief_historical_prior_fields,
        format_float=_format_float,
    )


def _append_brief_catalyst_theme_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    _append_brief_catalyst_theme_markdown_impl(
        lines,
        entries,
        append_brief_ticker_section=_append_brief_ticker_section,
        append_brief_historical_prior_fields=_append_brief_historical_prior_fields,
        append_gate_status_line=_append_gate_status_line,
        format_float=_format_float,
    )


def _append_brief_catalyst_frontier_markdown(
    lines: list[str], frontier_priority: dict[str, Any]
) -> None:
    _append_brief_catalyst_frontier_markdown_impl(
        lines,
        frontier_priority,
        append_frontier_section=_append_frontier_section,
        append_threshold_shortfalls_line=_append_threshold_shortfalls_line,
        append_catalyst_watch_metrics=_append_catalyst_watch_metrics,
        format_float=_format_float,
    )


def _append_frontier_priority_summary(
    lines: list[str], frontier_priority: dict[str, Any]
) -> None:
    _append_frontier_priority_summary_impl(
        lines, frontier_priority, format_float=_format_float
    )


def _append_frontier_section(
    lines: list[str],
    frontier_priority: dict[str, Any],
    render_entries: Callable[[list[str], list[dict[str, Any]]], None],
) -> None:
    _append_frontier_section_impl(
        lines,
        frontier_priority,
        render_entries,
        append_none_block_fn=_append_none_block,
        append_frontier_priority_summary_fn=_append_frontier_priority_summary,
        append_frontier_promoted_shadow_none_block_fn=_append_frontier_promoted_shadow_none_block,
    )


def _append_brief_catalyst_shadow_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    _append_brief_catalyst_shadow_markdown_impl(
        lines,
        entries,
        append_brief_ticker_section=_append_brief_ticker_section,
        append_threshold_shortfalls_line=_append_threshold_shortfalls_line,
        append_catalyst_watch_metrics=_append_catalyst_watch_metrics,
        append_gate_status_line=_append_gate_status_line,
        format_float=_format_float,
    )


def _append_brief_excluded_research_markdown(
    lines: list[str], entries: list[dict[str, Any]]
) -> None:
    _append_brief_excluded_research_markdown_impl(
        lines,
        entries,
        append_brief_ticker_section=_append_brief_ticker_section,
        format_float=_format_float,
    )


def _append_brief_upstream_shadow_markdown(
    lines: list[str],
    upstream_shadow_summary: dict[str, Any],
    upstream_shadow_entries: list[dict[str, Any]],
) -> None:
    _append_brief_upstream_shadow_markdown_impl(
        lines,
        upstream_shadow_summary,
        upstream_shadow_entries,
        append_brief_summary_ticker_section=_append_brief_summary_ticker_section,
        append_upstream_shadow_summary=_append_brief_upstream_shadow_summary,
        append_gate_status_line=_append_gate_status_line,
        format_float=_format_float,
    )


def _append_brief_summary_ticker_section(
    lines: list[str],
    *,
    title: str,
    entries: list[dict[str, Any]],
    append_summary: Callable[[list[str]], None],
    render_entry: Callable[[list[str], dict[str, Any]], None],
) -> None:
    lines.append(f"## {title}")
    if not entries:
        _append_none_block(lines)
        return
    append_summary(lines)
    for entry in entries:
        lines.append(f"### {entry['ticker']}")
        render_entry(lines, entry)
        lines.append("")


def _append_brief_upstream_shadow_summary(
    lines: list[str], upstream_shadow_summary: dict[str, Any]
) -> None:
    _append_upstream_shadow_summary(
        lines,
        upstream_shadow_summary,
        empty_lane_counts_label="none",
    )


def render_btst_next_day_trade_brief_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    _append_brief_overview_markdown(lines, analysis)
    _append_brief_scored_entries_markdown(
        lines, "Selected Entries", list(analysis.get("selected_entries") or [])
    )
    _append_brief_scored_entries_markdown(
        lines, "Near-Miss Watchlist", list(analysis.get("near_miss_entries") or [])
    )
    _append_brief_opportunity_pool_markdown(
        lines, list(analysis.get("opportunity_pool_entries") or [])
    )
    _append_brief_observer_lane_markdown(
        lines,
        "Risky Observer Lane",
        list(analysis.get("risky_observer_entries") or []),
        include_execution_note=True,
    )
    _append_brief_observer_lane_markdown(
        lines,
        "No-History Observer Lane",
        list(analysis.get("no_history_observer_entries") or []),
        include_execution_note=False,
    )
    _append_brief_pruned_entries_markdown(
        lines, list(analysis.get("weak_history_pruned_entries") or [])
    )
    _append_brief_research_radar_markdown(
        lines, list(analysis.get("research_upside_radar_entries") or [])
    )
    _append_brief_catalyst_theme_markdown(
        lines, list(analysis.get("catalyst_theme_entries") or [])
    )
    _append_brief_catalyst_frontier_markdown(
        lines, dict(analysis.get("catalyst_theme_frontier_priority") or {})
    )
    _append_brief_catalyst_shadow_markdown(
        lines, list(analysis.get("catalyst_theme_shadow_entries") or [])
    )
    _append_brief_excluded_research_markdown(
        lines, list(analysis.get("excluded_research_entries") or [])
    )
    _append_brief_upstream_shadow_markdown(
        lines,
        dict(analysis.get("upstream_shadow_summary") or {}),
        list(analysis.get("upstream_shadow_entries") or []),
    )
    _append_brief_source_paths_markdown(lines, analysis)
    return "\n".join(lines) + "\n"


def _append_source_paths_section(
    lines: list[str],
    *,
    report_dir: Any,
    snapshot_path: Any,
    session_summary_path: Any,
    replay_input_path: Any | None = None,
) -> None:
    _append_source_paths_section_impl(
        lines,
        report_dir=report_dir,
        snapshot_path=snapshot_path,
        session_summary_path=session_summary_path,
        replay_input_path=replay_input_path,
    )


def _append_none_block(lines: list[str]) -> None:
    _append_none_block_impl(lines)


def _append_frontier_promoted_shadow_none_block(lines: list[str]) -> None:
    _append_frontier_promoted_shadow_none_block_impl(lines)


def _append_brief_source_paths_markdown(
    lines: list[str], analysis: dict[str, Any]
) -> None:
    _append_source_paths_section(
        lines,
        report_dir=analysis.get("report_dir"),
        snapshot_path=analysis.get("snapshot_path"),
        replay_input_path=analysis.get("replay_input_path"),
        session_summary_path=analysis.get("session_summary_path"),
    )


def _resolve_brief_analysis(
    input_path: str | Path | dict[str, Any],
    trade_date: str | None,
    next_trade_date: str | None,
) -> dict[str, Any]:
    payload = dict(input_path) if isinstance(input_path, dict) else {}

    if not payload:
        resolved_input = Path(input_path).expanduser().resolve()
        if resolved_input.is_file():
            payload = _load_json(resolved_input)
            if "selected_entries" not in payload or "near_miss_entries" not in payload:
                return analyze_btst_next_day_trade_brief(
                    resolved_input,
                    trade_date=trade_date,
                    next_trade_date=next_trade_date,
                )
        else:
            return analyze_btst_next_day_trade_brief(
                resolved_input, trade_date=trade_date, next_trade_date=next_trade_date
            )

    if next_trade_date and not payload.get("next_trade_date"):
        payload["next_trade_date"] = _normalize_trade_date(next_trade_date)

    frontier_summary = dict(payload.get("catalyst_theme_frontier_summary") or {})
    frontier_priority = dict(payload.get("catalyst_theme_frontier_priority") or {})
    if not frontier_summary or not frontier_priority:
        frontier_summary = frontier_summary or _load_catalyst_theme_frontier_summary(
            payload.get("report_dir")
        )
        frontier_priority = (
            frontier_priority
            or _build_catalyst_theme_frontier_priority(
                frontier_summary,
                list(payload.get("catalyst_theme_shadow_entries") or []),
            )
        )
        payload["catalyst_theme_frontier_summary"] = frontier_summary
        payload["catalyst_theme_frontier_priority"] = frontier_priority

    summary = dict(payload.get("summary") or {})
    summary.setdefault(
        "catalyst_theme_frontier_promoted_count",
        len(frontier_priority.get("promoted_tickers") or []),
    )
    payload["summary"] = summary
    payload.setdefault("upstream_shadow_entries", [])
    payload.setdefault(
        "upstream_shadow_summary",
        {
            "shadow_candidate_count": 0,
            "promotable_count": 0,
            "lane_counts": {},
            "decision_counts": {},
            "top_focus_tickers": [],
        },
    )
    return payload


def _selected_action_posture(preferred_entry_mode: str | None) -> tuple[str, list[str]]:
    if preferred_entry_mode == "next_day_breakout_confirmation":
        return (
            "confirm_then_enter",
            [
                "只在盘中出现 breakout confirmation 时考虑执行，不做无确认追价。",
                "若盘中强度无法延续或突破失败，则直接放弃当日入场。",
            ],
        )
    if preferred_entry_mode == "intraday_confirmation_only":
        return (
            "confirm_then_reduce",
            [
                "只做盘中确认后的 intraday 机会，不把默认隔夜持有当成执行目标。",
                "若盘中给出空间后回落，应优先减仓或放弃隔夜持有。",
            ],
        )
    if preferred_entry_mode == "avoid_open_chase_confirmation":
        return (
            "avoid_open_chase",
            [
                "避免开盘直接追价，等待回踩或二次确认后再决定是否参与。",
                "若高开后强度迅速衰减，则直接放弃当日入场。",
            ],
        )
    if preferred_entry_mode == "confirm_then_hold_breakout":
        return (
            "confirm_then_hold",
            [
                "先等盘中 continuation 确认，再决定是否执行，不做无确认开盘追价。",
                "若确认后量价延续良好，可把 follow-through 持有到收盘，而不是默认盘中快速减仓。",
            ],
        )
    if preferred_entry_mode == "strong_reconfirmation_only":
        return (
            "reconfirm_only",
            [
                "历史兑现极弱，只有出现新的强确认时才允许重新评估。",
                "没有新增强度时，不把它当成可执行 BTST 对象。",
            ],
        )
    return (
        "manual_review",
        [
            "当前 entry mode 不是标准 breakout confirmation，开盘前应先人工复核。",
        ],
    )


def _selected_holding_contract_note(
    preferred_entry_mode: str | None, historical_prior: dict[str, Any] | None
) -> str | None:
    prior = dict(historical_prior or {})
    if preferred_entry_mode != "confirm_then_hold_breakout":
        return None
    if str(prior.get("execution_quality_label") or "") != "close_continuation":
        return None
    if str(prior.get("entry_timing_bias") or "") != "confirm_then_hold":
        return None
    return "默认按 BTST T+2 bias 管理，不把 T+3 连续走强当成基础预期。"


def _augment_execution_note(
    preferred_entry_mode: str | None, historical_prior: dict[str, Any] | None
) -> str | None:
    prior = dict(historical_prior or {})
    base_note = str(prior.get("execution_note") or "").strip()
    contract_note = _selected_holding_contract_note(preferred_entry_mode, prior)
    if contract_note and contract_note not in base_note:
        return f"{base_note} {contract_note}".strip() if base_note else contract_note
    return base_note or None


def _build_premarket_primary_action(
    primary_entry: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not primary_entry:
        return None

    posture, trigger_rules = _selected_action_posture(
        primary_entry.get("preferred_entry_mode")
    )
    historical_prior = dict(primary_entry.get("historical_prior") or {})
    if historical_prior.get("summary"):
        trigger_rules.insert(0, f"历史先验: {historical_prior['summary']}")
    if historical_prior.get("execution_note"):
        trigger_rules.append(f"执行先验: {historical_prior['execution_note']}")
    holding_contract_note = _selected_holding_contract_note(
        primary_entry.get("preferred_entry_mode"), historical_prior
    )
    if holding_contract_note:
        trigger_rules.append(f"持有 contract: {holding_contract_note}")
    return {
        "ticker": primary_entry.get("ticker"),
        "action_tier": "primary_entry",
        "execution_posture": posture,
        "watch_priority": historical_prior.get("monitor_priority") or "unscored",
        "execution_quality_label": historical_prior.get("execution_quality_label")
        or "unknown",
        "preferred_entry_mode": primary_entry.get("preferred_entry_mode"),
        "trigger_rules": trigger_rules,
        "avoid_rules": [
            "不把 near-miss 或 research-only 股票并入主执行名单。",
            "不因为开盘情绪强就跳过 breakout confirmation。",
        ],
        "evidence": list(primary_entry.get("top_reasons") or []),
        "positive_tags": list(primary_entry.get("positive_tags") or []),
        "metrics": dict(primary_entry.get("metrics") or {}),
        "historical_prior": historical_prior,
        "holding_contract_note": holding_contract_note,
    }


def _build_premarket_observer_action(
    entry: dict[str, Any],
    *,
    action_tier: str,
    execution_posture: str,
    default_action: str,
    secondary_rule: str,
    avoid_rules: list[str],
    include_rejection_reasons: bool,
) -> dict[str, Any]:
    historical_prior = dict(entry.get("historical_prior") or {})
    _, primary_watch_rule = _entry_mode_action_guidance(
        entry.get("preferred_entry_mode"),
        default_action=default_action,
    )
    trigger_rules = [primary_watch_rule, secondary_rule]
    if historical_prior.get("summary"):
        trigger_rules.insert(0, f"历史先验: {historical_prior['summary']}")
    evidence = list(entry.get("top_reasons") or [])
    if include_rejection_reasons:
        evidence += list(entry.get("rejection_reasons") or [])
    return {
        "ticker": entry.get("ticker"),
        "action_tier": action_tier,
        "execution_posture": execution_posture,
        "watch_priority": historical_prior.get("monitor_priority") or "unscored",
        "execution_quality_label": historical_prior.get("execution_quality_label")
        or "unknown",
        "preferred_entry_mode": entry.get("preferred_entry_mode"),
        "trigger_rules": trigger_rules,
        "avoid_rules": avoid_rules,
        "evidence": evidence,
        "metrics": dict(entry.get("metrics") or {}),
        "historical_prior": historical_prior,
    }


def analyze_btst_premarket_execution_card(
    input_path: str | Path | dict[str, Any],
    trade_date: str | None = None,
    next_trade_date: str | None = None,
) -> dict[str, Any]:
    brief = _resolve_brief_analysis(
        input_path, trade_date=trade_date, next_trade_date=next_trade_date
    )
    action_context = _build_premarket_action_context(brief)
    catalyst_theme_frontier_priority = action_context[
        "catalyst_theme_frontier_priority"
    ]
    catalyst_theme_shadow_watch = action_context["catalyst_theme_shadow_watch"]
    primary_action = action_context["primary_action"]
    watch_actions = action_context["watch_actions"]
    opportunity_actions = action_context["opportunity_actions"]
    no_history_observer_actions = action_context["no_history_observer_actions"]
    risky_observer_actions = action_context["risky_observer_actions"]
    upstream_shadow_summary = action_context["upstream_shadow_summary"]

    return {
        "trade_date": brief.get("trade_date"),
        "next_trade_date": brief.get("next_trade_date"),
        "selection_target": brief.get("selection_target"),
        "summary": _build_premarket_card_summary(
            brief=brief,
            primary_action=primary_action,
            watch_actions=watch_actions,
            opportunity_actions=opportunity_actions,
            no_history_observer_actions=no_history_observer_actions,
            risky_observer_actions=risky_observer_actions,
            catalyst_theme_frontier_priority=catalyst_theme_frontier_priority,
            upstream_shadow_summary=upstream_shadow_summary,
        ),
        "recommendation": brief.get("recommendation"),
        "primary_action": primary_action,
        "watch_actions": watch_actions,
        "opportunity_actions": opportunity_actions,
        "no_history_observer_actions": no_history_observer_actions,
        "risky_observer_actions": risky_observer_actions,
        "catalyst_theme_frontier_priority": catalyst_theme_frontier_priority,
        "catalyst_theme_shadow_watch": catalyst_theme_shadow_watch,
        "upstream_shadow_entries": list(brief.get("upstream_shadow_entries") or []),
        "upstream_shadow_summary": upstream_shadow_summary,
        "excluded_research_entries": list(brief.get("excluded_research_entries") or []),
        "global_guardrails": [
            "主执行名单只认 short-trade selected，不把 research selected 自动等价成短线可交易票。",
            "near-miss 默认只做观察，不预设与主票同级的买入动作。",
            "机会池只用于补充盯盘覆盖面，不自动升级为正式交易对象。",
            "题材催化影子池只做研究跟踪，不进入当日 BTST 交易名单。",
            "若 selected 当日没有出现确认信号，则允许空仓而不是强行交易。",
        ],
        "source_paths": {
            "report_dir": brief.get("report_dir"),
            "snapshot_path": brief.get("snapshot_path"),
            "session_summary_path": brief.get("session_summary_path"),
        },
    }


def _build_premarket_action_context(brief: dict[str, Any]) -> dict[str, Any]:
    primary_entry = brief.get("primary_entry")
    return {
        "primary_entry": primary_entry,
        "catalyst_theme_frontier_priority": dict(
            brief.get("catalyst_theme_frontier_priority") or {}
        ),
        "catalyst_theme_shadow_watch": _build_catalyst_theme_shadow_watch_rows(
            list(brief.get("catalyst_theme_shadow_entries") or [])
        ),
        "primary_action": _build_premarket_primary_action(primary_entry),
        "watch_actions": _build_watch_actions(
            list(brief.get("near_miss_entries") or [])
        ),
        "opportunity_actions": _build_opportunity_actions(
            list(brief.get("opportunity_pool_entries") or [])
        ),
        "no_history_observer_actions": _build_no_history_observer_actions(
            list(brief.get("no_history_observer_entries") or [])
        ),
        "risky_observer_actions": _build_risky_observer_actions(
            list(brief.get("risky_observer_entries") or [])
        ),
        "upstream_shadow_summary": dict(brief.get("upstream_shadow_summary") or {}),
    }


def _build_watch_actions(
    near_miss_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_premarket_observer_action(
            entry,
            action_tier="watch_only",
            execution_posture="observe_only",
            default_action="仅做盘中强度跟踪，不预设主买入动作。",
            secondary_rule="若当日需要转为可执行对象，应先回看 short-trade score 与盘中确认信号。",
            avoid_rules=[
                "near_miss 不能与 selected 同级表达。",
                "没有新增确认前，不把它视为默认替补主票。",
            ],
            include_rejection_reasons=False,
        )
        for entry in near_miss_entries
    ]


def _build_opportunity_actions(
    opportunity_pool_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_premarket_observer_action(
            entry,
            action_tier="conditional_watch_upgrade",
            execution_posture="observe_for_upgrade_only",
            default_action=str(
                entry.get("promotion_trigger")
                or "只有盘中新增强度确认时，才允许从机会池升级。"
            ),
            secondary_rule="默认不在开盘前直接升级为主票或近似主票。",
            avoid_rules=[
                "机会池不是默认交易名单，不因情绪拉升直接入场。",
                "若结构重新转弱或强度未延续，则继续留在非交易状态。",
            ],
            include_rejection_reasons=True,
        )
        for entry in opportunity_pool_entries
    ]


def _build_no_history_observer_actions(
    no_history_observer_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_premarket_observer_action(
            entry,
            action_tier="no_history_observer_watch",
            execution_posture="observe_only_no_history",
            default_action="暂无可评估历史先验，只做盘中新证据观察，不预设 BTST 升级。",
            secondary_rule="默认不升级为主票；只有出现新的独立强确认，才考虑重新评估。",
            avoid_rules=[
                "缺少可评估历史先验时，不把它视为标准机会池升级对象。",
                "没有新的盘中强确认前，不预设隔夜 BTST 持有。",
            ],
            include_rejection_reasons=True,
        )
        for entry in no_history_observer_entries
    ]


def _build_risky_observer_actions(
    risky_observer_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_premarket_observer_action(
            entry,
            action_tier="risky_observer_watch",
            execution_posture="observe_only_high_risk",
            default_action="只做高风险盘中观察，不做标准 BTST 升级预案。",
            secondary_rule="默认不升级为主票，也不把隔夜持有当成基础执行路径。",
            avoid_rules=[
                "高风险观察桶不与标准机会池混用。",
                "没有新的强确认时，不把它视为 BTST 候补交易对象。",
            ],
            include_rejection_reasons=True,
        )
        for entry in risky_observer_entries
    ]


def _build_premarket_card_summary(
    *,
    brief: dict[str, Any],
    primary_action: dict[str, Any] | None,
    watch_actions: list[dict[str, Any]],
    opportunity_actions: list[dict[str, Any]],
    no_history_observer_actions: list[dict[str, Any]],
    risky_observer_actions: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
    upstream_shadow_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "primary_count": 1 if primary_action else 0,
        "watch_count": len(watch_actions),
        "opportunity_pool_count": len(opportunity_actions),
        "no_history_observer_count": len(no_history_observer_actions),
        "risky_observer_count": len(risky_observer_actions),
        "catalyst_theme_frontier_promoted_count": len(
            catalyst_theme_frontier_priority.get("promoted_tickers") or []
        ),
        "catalyst_theme_shadow_count": len(
            brief.get("catalyst_theme_shadow_entries") or []
        ),
        "upstream_shadow_candidate_count": int(
            upstream_shadow_summary.get("shadow_candidate_count") or 0
        ),
        "upstream_shadow_promotable_count": int(
            upstream_shadow_summary.get("promotable_count") or 0
        ),
        "excluded_research_count": len(brief.get("excluded_research_entries") or []),
    }


def _append_premarket_overview_markdown(lines: list[str], card: dict[str, Any]) -> None:
    summary = dict(card.get("summary") or {})
    lines.append("# BTST Premarket Execution Card")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- trade_date: {card.get('trade_date')}")
    lines.append(f"- next_trade_date: {card.get('next_trade_date') or 'n/a'}")
    lines.append(f"- selection_target: {card.get('selection_target')}")
    lines.append(f"- primary_count: {summary.get('primary_count')}")
    lines.append(f"- watch_count: {summary.get('watch_count')}")
    lines.append(f"- opportunity_pool_count: {summary.get('opportunity_pool_count')}")
    lines.append(
        f"- no_history_observer_count: {summary.get('no_history_observer_count')}"
    )
    lines.append(f"- risky_observer_count: {summary.get('risky_observer_count')}")
    lines.append(
        f"- catalyst_theme_frontier_promoted_count: {summary.get('catalyst_theme_frontier_promoted_count')}"
    )
    lines.append(
        f"- catalyst_theme_shadow_count: {summary.get('catalyst_theme_shadow_count')}"
    )
    lines.append(
        f"- upstream_shadow_candidate_count: {summary.get('upstream_shadow_candidate_count')}"
    )
    lines.append(
        f"- upstream_shadow_promotable_count: {summary.get('upstream_shadow_promotable_count')}"
    )
    lines.append(f"- excluded_research_count: {summary.get('excluded_research_count')}")
    lines.append(f"- recommendation: {card.get('recommendation')}")
    lines.append("")


def _append_premarket_action_block(
    lines: list[str], entry: dict[str, Any], *, indexed: int | None = None
) -> None:
    label = f"### {indexed}. {entry.get('ticker')}" if indexed is not None else None
    if label:
        lines.append(label)
    else:
        lines.append(f"- ticker: {entry.get('ticker')}")
    prefix = "- " if label else "- "
    lines.append(f"{prefix}action_tier: {entry.get('action_tier')}")
    lines.append(f"{prefix}execution_posture: {entry.get('execution_posture')}")
    lines.append(f"{prefix}watch_priority: {entry.get('watch_priority')}")
    lines.append(
        f"{prefix}execution_quality_label: {entry.get('execution_quality_label')}"
    )
    lines.append(f"{prefix}preferred_entry_mode: {entry.get('preferred_entry_mode')}")
    lines.append(
        f"{prefix}historical_summary: {(entry.get('historical_prior') or {}).get('summary') or 'n/a'}"
    )
    lines.append(f"{prefix}evidence: {', '.join(entry.get('evidence') or []) or 'n/a'}")
    lines.append("- trigger_rules:")
    lines.extend(f"  - {item}" for item in entry.get("trigger_rules") or [])
    lines.append("- avoid_rules:")
    lines.extend(f"  - {item}" for item in entry.get("avoid_rules") or [])
    lines.append("")


def _append_premarket_action_section(
    lines: list[str], title: str, entries: list[dict[str, Any]]
) -> None:
    _append_titled_indexed_section(
        lines,
        title=f"## {title}",
        items=entries,
        render_item=lambda inner_lines, entry, index: _append_premarket_action_block(
            inner_lines, entry, indexed=index
        ),
    )


def _append_premarket_frontier_watch_markdown(
    lines: list[str], frontier_priority: dict[str, Any]
) -> None:
    _append_premarket_frontier_watch_markdown_impl(
        lines,
        frontier_priority,
        append_frontier_section=_append_frontier_section,
        append_indexed_ticker_blocks=_append_indexed_ticker_blocks,
        append_candidate_watch_scoring_fields=_append_candidate_watch_scoring_fields,
        append_candidate_watch_reason_tags=_append_candidate_watch_reason_tags,
        append_threshold_shortfalls_line=_append_threshold_shortfalls_line,
        append_catalyst_watch_metrics=_append_catalyst_watch_metrics,
        format_float=_format_float,
    )


def _append_premarket_shadow_watch_markdown(
    lines: list[str], shadow_watch: list[dict[str, Any]]
) -> None:
    _append_premarket_shadow_watch_markdown_impl(
        lines,
        shadow_watch,
        append_titled_indexed_ticker_section=_append_titled_indexed_ticker_section,
        append_candidate_watch_scoring_fields=_append_candidate_watch_scoring_fields,
        append_candidate_watch_reason_tags=_append_candidate_watch_reason_tags,
        append_threshold_shortfalls_line=_append_threshold_shortfalls_line,
        append_catalyst_watch_metrics=_append_catalyst_watch_metrics,
        format_float=_format_float,
    )


def _append_candidate_watch_scoring_fields(
    lines: list[str], item: dict[str, Any]
) -> None:
    lines.append(f"- candidate_score: {_format_float(item.get('candidate_score'))}")
    lines.append(f"- filter_reason: {item.get('filter_reason') or 'n/a'}")
    lines.append(f"- total_shortfall: {_format_float(item.get('total_shortfall'))}")
    lines.append(f"- failed_threshold_count: {item.get('failed_threshold_count')}")
    lines.append(f"- preferred_entry_mode: {item.get('preferred_entry_mode')}")


def _append_candidate_watch_reason_tags(
    lines: list[str], item: dict[str, Any], *, reasons_label: str
) -> None:
    lines.append(
        f"- {reasons_label}: {', '.join(item.get('top_reasons') or []) or 'n/a'}"
    )
    lines.append(
        f"- positive_tags: {', '.join(item.get('positive_tags') or []) or 'n/a'}"
    )


def _append_threshold_shortfalls_line(
    lines: list[str], threshold_shortfalls: dict[str, Any]
) -> None:
    lines.append(
        "- threshold_shortfalls: "
        + (
            ", ".join(
                f"{key}={_format_float(value)}"
                for key, value in threshold_shortfalls.items()
            )
            if threshold_shortfalls
            else "none"
        )
    )


def _append_catalyst_watch_metrics(lines: list[str], metrics: dict[str, Any]) -> None:
    lines.append(
        "- key_metrics: "
        + ", ".join(
            [
                f"breakout={_format_float(metrics.get('breakout_freshness'))}",
                f"trend={_format_float(metrics.get('trend_acceleration'))}",
                f"close={_format_float(metrics.get('close_strength'))}",
                f"sector={_format_float(metrics.get('sector_resonance'))}",
                f"catalyst={_format_float(metrics.get('catalyst_freshness'))}",
            ]
        )
    )


def _append_premarket_excluded_entries_markdown(
    lines: list[str], excluded_entries: list[dict[str, Any]]
) -> None:
    lines.append("## Explicit Non-Trades")
    if not excluded_entries:
        _append_none_block(lines)
        return
    lines.extend(
        f"- {entry.get('ticker')}: research selected, but short_trade={entry.get('short_trade_decision')} so it stays outside the short-trade execution list."
        for entry in excluded_entries
    )
    lines.append("")


def _append_upstream_shadow_summary_header(
    lines: list[str], upstream_shadow_summary: dict[str, Any]
) -> None:
    _append_upstream_shadow_summary_header_impl(
        lines,
        upstream_shadow_summary,
        append_upstream_shadow_summary_fn=lambda inner_lines, summary: (
            _append_upstream_shadow_summary(
                inner_lines,
                summary,
                empty_lane_counts_label="",
            )
        ),
    )


def _append_upstream_shadow_summary(
    lines: list[str],
    upstream_shadow_summary: dict[str, Any],
    *,
    empty_lane_counts_label: str,
) -> None:
    _append_upstream_shadow_summary_impl(
        lines,
        upstream_shadow_summary,
        empty_lane_counts_label=empty_lane_counts_label,
    )


def _append_upstream_shadow_core_fields(
    lines: list[str],
    entry: dict[str, Any],
    *,
    opening_plan_label: str,
    reasons_label: str,
) -> None:
    _append_upstream_shadow_core_fields_impl(
        lines,
        entry,
        opening_plan_label=opening_plan_label,
        reasons_label=reasons_label,
    )


def _append_upstream_shadow_section(
    lines: list[str],
    upstream_shadow_summary: dict[str, Any],
    upstream_shadow_entries: list[dict[str, Any]],
    render_item: Callable[[list[str], dict[str, Any], int], None],
) -> None:
    _append_upstream_shadow_section_impl(
        lines,
        upstream_shadow_summary,
        upstream_shadow_entries,
        render_item,
        append_none_block_fn=_append_none_block,
        append_upstream_shadow_summary_header_fn=_append_upstream_shadow_summary_header,
    )


def _append_premarket_upstream_shadow_item(
    lines: list[str], entry: dict[str, Any], index: int
) -> None:
    del index
    lines.append(f"### {entry.get('ticker')}")
    _append_upstream_shadow_core_fields(
        lines,
        entry,
        opening_plan_label="promotion_trigger",
        reasons_label="evidence",
    )


def _append_premarket_upstream_shadow_markdown(
    lines: list[str],
    upstream_shadow_summary: dict[str, Any],
    upstream_shadow_entries: list[dict[str, Any]],
) -> None:
    _append_upstream_shadow_section(
        lines,
        upstream_shadow_summary,
        upstream_shadow_entries,
        _append_premarket_upstream_shadow_item,
    )


def _append_opening_upstream_shadow_item(
    lines: list[str], item: dict[str, Any], index: int
) -> None:
    lines.append(f"### {index}. {item.get('ticker')}")
    lines.append("- focus_tier: upstream_shadow_recall")
    _append_upstream_shadow_core_fields(
        lines,
        item,
        opening_plan_label="opening_plan",
        reasons_label="top_reasons",
    )


def render_btst_premarket_execution_card_markdown(card: dict[str, Any]) -> str:
    lines: list[str] = []
    _append_premarket_overview_markdown(lines, card)
    _append_premarket_primary_action_markdown(lines, card.get("primary_action"))
    _append_premarket_action_section(
        lines, "Watchlist Actions", list(card.get("watch_actions") or [])
    )
    _append_premarket_action_section(
        lines, "Opportunity Pool Actions", list(card.get("opportunity_actions") or [])
    )
    _append_premarket_action_section(
        lines, "Risky Observer Actions", list(card.get("risky_observer_actions") or [])
    )
    _append_premarket_action_section(
        lines,
        "No-History Observer Actions",
        list(card.get("no_history_observer_actions") or []),
    )
    _append_premarket_frontier_watch_markdown(
        lines, dict(card.get("catalyst_theme_frontier_priority") or {})
    )
    _append_premarket_shadow_watch_markdown(
        lines, list(card.get("catalyst_theme_shadow_watch") or [])
    )
    _append_premarket_excluded_entries_markdown(
        lines, list(card.get("excluded_research_entries") or [])
    )
    _append_premarket_upstream_shadow_markdown(
        lines,
        dict(card.get("upstream_shadow_summary") or {}),
        list(card.get("upstream_shadow_entries") or []),
    )
    _append_premarket_guardrails_markdown(
        lines, list(card.get("global_guardrails") or [])
    )
    _append_premarket_source_paths_markdown(lines, dict(card.get("source_paths") or {}))
    return "\n".join(lines) + "\n"


def _append_premarket_primary_action_markdown(
    lines: list[str], primary_action: Any
) -> None:
    lines.append("## Primary Action")
    if not primary_action:
        _append_none_block(lines)
        return
    _append_premarket_action_block(lines, dict(primary_action))


def _append_guardrail_section(
    lines: list[str], title: str, guardrails: list[str]
) -> None:
    _append_guardrail_section_impl(lines, title, guardrails)


def _append_premarket_guardrails_markdown(
    lines: list[str], guardrails: list[str]
) -> None:
    _append_guardrail_section(lines, "## Global Guardrails", guardrails)


def _append_premarket_source_paths_markdown(
    lines: list[str], source_paths: dict[str, Any]
) -> None:
    _append_source_paths_section(
        lines,
        report_dir=source_paths.get("report_dir"),
        snapshot_path=source_paths.get("snapshot_path"),
        session_summary_path=source_paths.get("session_summary_path"),
    )


def _build_opening_primary_focus_item(
    primary_entry: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not primary_entry:
        return None
    posture, trigger_rules = _selected_action_posture(
        primary_entry.get("preferred_entry_mode")
    )
    historical_prior = dict(primary_entry.get("historical_prior") or {})
    return {
        "ticker": primary_entry.get("ticker"),
        "focus_tier": "primary_entry",
        "monitor_priority": "execute",
        "execution_posture": posture,
        "score_target": primary_entry.get("score_target"),
        "preferred_entry_mode": primary_entry.get("preferred_entry_mode"),
        "why_now": ", ".join(primary_entry.get("top_reasons") or [])
        or "当前 short-trade 正式 selected。",
        "opening_plan": trigger_rules[0] if trigger_rules else "只在确认出现后执行。",
        "historical_summary": historical_prior.get("summary"),
        "execution_note": _augment_execution_note(
            primary_entry.get("preferred_entry_mode"), historical_prior
        ),
    }


def _build_opening_focus_item(
    entry: dict[str, Any],
    *,
    focus_tier: str,
    execution_posture: str,
    default_action: str,
    default_why_now: str,
    execution_note_mode: str = "historical",
    opening_plan_key: str | None = None,
) -> dict[str, Any]:
    historical_prior = dict(entry.get("historical_prior") or {})
    _, opening_plan = _entry_mode_action_guidance(
        entry.get("preferred_entry_mode"),
        default_action=default_action,
    )
    if opening_plan_key:
        opening_plan = str(entry.get(opening_plan_key) or opening_plan)
    execution_note = (
        _augment_execution_note(entry.get("preferred_entry_mode"), historical_prior)
        if execution_note_mode == "augment"
        else historical_prior.get("execution_note")
    )
    return {
        "ticker": entry.get("ticker"),
        "focus_tier": focus_tier,
        "monitor_priority": historical_prior.get("monitor_priority") or "unscored",
        "execution_posture": execution_posture,
        "score_target": entry.get("score_target"),
        "preferred_entry_mode": entry.get("preferred_entry_mode"),
        "why_now": ", ".join(entry.get("top_reasons") or []) or default_why_now,
        "opening_plan": opening_plan,
        "historical_summary": historical_prior.get("summary"),
        "execution_note": execution_note,
    }


def _build_opening_headline(
    *,
    primary_entry: dict[str, Any],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
    upstream_shadow_summary: dict[str, Any],
) -> str:
    headline = "当前没有正式交易票，开盘只做观察。"
    if primary_entry:
        headline = "先看主票确认，再看 near-miss 和机会池是否出现升级信号。"
    elif near_miss_entries:
        headline = "当前没有正式主票，开盘只保留 near-miss 与机会池观察，不预设交易。"
    elif opportunity_pool_entries:
        headline = "当前只有机会池可跟踪，除非盘中新强度确认，否则不交易。"
    elif no_history_observer_entries:
        headline = "当前没有标准 BTST 机会池，只保留无历史先验观察，不预设交易。"
    elif risky_observer_entries:
        headline = "当前没有标准 BTST 机会池，只保留高风险盘中观察，不预设交易。"
    if catalyst_theme_frontier_priority.get("promoted_tickers"):
        headline = (
            headline.rstrip("。")
            + "；题材催化前沿优先跟踪 "
            + ", ".join(catalyst_theme_frontier_priority.get("promoted_tickers") or [])
            + "，但仍只做研究跟踪。"
        )
    if upstream_shadow_summary.get("shadow_candidate_count"):
        headline = (
            headline.rstrip("。")
            + "；上游影子召回关注 "
            + ", ".join(upstream_shadow_summary.get("top_focus_tickers") or [])
            + "。"
        )
    return headline


def analyze_btst_opening_watch_card(
    input_path: str | Path | dict[str, Any],
    trade_date: str | None = None,
    next_trade_date: str | None = None,
) -> dict[str, Any]:
    brief = _resolve_brief_analysis(
        input_path, trade_date=trade_date, next_trade_date=next_trade_date
    )
    opening_context = _build_opening_watch_context(brief)
    catalyst_theme_frontier_priority = opening_context[
        "catalyst_theme_frontier_priority"
    ]
    catalyst_theme_shadow_watch = opening_context["catalyst_theme_shadow_watch"]
    near_miss_entries = opening_context["near_miss_entries"]
    opportunity_pool_entries = opening_context["opportunity_pool_entries"]
    no_history_observer_entries = opening_context["no_history_observer_entries"]
    risky_observer_entries = opening_context["risky_observer_entries"]
    primary_entry = opening_context["primary_entry"]
    focus_items = _build_opening_focus_items(
        brief=brief,
        primary_entry=primary_entry,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        no_history_observer_entries=no_history_observer_entries,
        risky_observer_entries=risky_observer_entries,
    )
    _sort_opening_focus_items(focus_items)
    upstream_shadow_summary = opening_context["upstream_shadow_summary"]
    headline = _build_opening_headline(
        primary_entry=primary_entry,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        no_history_observer_entries=no_history_observer_entries,
        risky_observer_entries=risky_observer_entries,
        catalyst_theme_frontier_priority=catalyst_theme_frontier_priority,
        upstream_shadow_summary=upstream_shadow_summary,
    )

    return {
        "trade_date": brief.get("trade_date"),
        "next_trade_date": brief.get("next_trade_date"),
        "selection_target": brief.get("selection_target"),
        "headline": headline,
        "recommendation": brief.get("recommendation"),
        "summary": _build_opening_watch_summary(
            brief=brief,
            no_history_observer_entries=no_history_observer_entries,
            risky_observer_entries=risky_observer_entries,
            catalyst_theme_frontier_priority=catalyst_theme_frontier_priority,
            upstream_shadow_summary=upstream_shadow_summary,
        ),
        "focus_items": focus_items,
        "no_history_observer_entries": no_history_observer_entries,
        "risky_observer_entries": risky_observer_entries,
        "catalyst_theme_frontier_priority": catalyst_theme_frontier_priority,
        "catalyst_theme_shadow_watch": catalyst_theme_shadow_watch,
        "upstream_shadow_entries": list(brief.get("upstream_shadow_entries") or []),
        "upstream_shadow_summary": upstream_shadow_summary,
        "global_guardrails": [
            "selected 之外的对象默认都不是开盘直接交易名单。",
            "机会池只做覆盖扩容，不因情绪走强直接升级为正式交易票。",
            "题材催化影子池只做研究跟踪，不进入当日 BTST 交易名单。",
            "research 漏票雷达只做上涨线索学习，不加入当日 BTST 交易名单。",
            "若主票缺少确认信号，则允许空仓，不强行补票。",
        ],
        "source_paths": {
            "report_dir": brief.get("report_dir"),
            "snapshot_path": brief.get("snapshot_path"),
            "session_summary_path": brief.get("session_summary_path"),
        },
    }


def _build_opening_watch_context(brief: dict[str, Any]) -> dict[str, Any]:
    selected_entries = [
        _apply_execution_quality_entry_mode(entry)
        for entry in list(brief.get("selected_entries") or [])
    ]
    return {
        "catalyst_theme_frontier_priority": dict(
            brief.get("catalyst_theme_frontier_priority") or {}
        ),
        "catalyst_theme_shadow_watch": _build_catalyst_theme_shadow_watch_rows(
            list(brief.get("catalyst_theme_shadow_entries") or [])
        ),
        "selected_entries": selected_entries,
        "near_miss_entries": [
            _apply_execution_quality_entry_mode(entry)
            for entry in list(brief.get("near_miss_entries") or [])
        ],
        "opportunity_pool_entries": [
            _apply_execution_quality_entry_mode(entry)
            for entry in list(brief.get("opportunity_pool_entries") or [])
        ],
        "no_history_observer_entries": [
            _apply_execution_quality_entry_mode(entry)
            for entry in list(brief.get("no_history_observer_entries") or [])
        ],
        "risky_observer_entries": [
            _apply_execution_quality_entry_mode(entry)
            for entry in list(brief.get("risky_observer_entries") or [])
        ],
        "primary_entry": _resolve_opening_primary_entry(brief, selected_entries),
        "upstream_shadow_summary": dict(brief.get("upstream_shadow_summary") or {}),
    }


def _resolve_opening_primary_entry(
    brief: dict[str, Any], selected_entries: list[dict[str, Any]]
) -> dict[str, Any]:
    primary_entry = dict(brief.get("primary_entry") or {})
    if not primary_entry and selected_entries:
        return dict(selected_entries[0])
    if primary_entry:
        return _apply_execution_quality_entry_mode(primary_entry)
    return {}


def _build_opening_focus_items(
    *,
    brief: dict[str, Any],
    primary_entry: dict[str, Any],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    focus_items = _build_primary_focus_items(primary_entry)
    focus_items.extend(_build_near_miss_focus_items(near_miss_entries))
    focus_items.extend(_build_opportunity_pool_focus_items(opportunity_pool_entries))
    focus_items.extend(_build_risky_observer_focus_items(risky_observer_entries))
    focus_items.extend(
        _build_no_history_observer_focus_items(no_history_observer_entries)
    )
    focus_items.extend(
        _build_research_upside_focus_items(
            list(brief.get("research_upside_radar_entries") or [])
        )
    )
    return focus_items


def _build_primary_focus_items(primary_entry: dict[str, Any]) -> list[dict[str, Any]]:
    primary_focus_item = _build_opening_primary_focus_item(primary_entry)
    return [primary_focus_item] if primary_focus_item else []


def _build_near_miss_focus_items(
    near_miss_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_opening_focus_item(
            entry,
            focus_tier="near_miss_watch",
            execution_posture="observe_only",
            default_action="只观察，不预设与主票同级的买入动作。",
            default_why_now="当前接近 near-miss 边界。",
            execution_note_mode="augment",
        )
        for entry in near_miss_entries
    ]


def _build_opportunity_pool_focus_items(
    opportunity_pool_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_opening_focus_item(
            entry,
            focus_tier="opportunity_pool",
            execution_posture="observe_for_upgrade_only",
            default_action=str(
                entry.get("promotion_trigger")
                or "只有盘中新增强度确认时，才允许从机会池升级。"
            ),
            default_why_now="结构未坏，但暂未进入正式 short-trade 名单。",
        )
        for entry in opportunity_pool_entries
    ]


def _build_risky_observer_focus_items(
    risky_observer_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_opening_focus_item(
            entry,
            focus_tier="risky_observer",
            execution_posture="risk_observer_only",
            default_action="只做高风险盘中确认观察，不预设隔夜 BTST 升级。",
            default_why_now="当前属于高风险盘中观察桶。",
        )
        for entry in risky_observer_entries
    ]


def _build_no_history_observer_focus_items(
    no_history_observer_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_opening_focus_item(
            entry,
            focus_tier="no_history_observer",
            execution_posture="observe_only_no_history",
            default_action="暂无可评估历史先验，只做盘中新证据观察，不预设 BTST 升级。",
            default_why_now="当前暂无可评估历史先验，只保留观察。",
        )
        for entry in no_history_observer_entries
    ]


def _build_research_upside_focus_items(
    research_upside_radar_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_opening_focus_item(
            entry,
            focus_tier="research_upside_radar",
            execution_posture="non_trade_learning_only",
            default_action="只做漏票学习，不加入当日 BTST 交易名单。",
            default_why_now="research 已选中但 BTST 未放行。",
            opening_plan_key="radar_note",
        )
        for entry in research_upside_radar_entries
    ]


def _sort_opening_focus_items(focus_items: list[dict[str, Any]]) -> None:
    focus_items.sort(
        key=lambda item: (
            0
            if item.get("focus_tier") == "primary_entry"
            else 1
            if item.get("focus_tier") == "near_miss_watch"
            else 2
            if item.get("focus_tier") == "opportunity_pool"
            else 3
            if item.get("focus_tier") == "no_history_observer"
            else 4,
            _monitor_priority_rank(item.get("monitor_priority")),
            _execution_priority_rank(
                (item.get("execution_note") and "medium") or "unscored"
            ),
            -_as_float(item.get("score_target")),
            str(item.get("ticker") or ""),
        )
    )


def _build_opening_watch_summary(
    *,
    brief: dict[str, Any],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
    upstream_shadow_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "primary_count": len(brief.get("selected_entries") or []),
        "near_miss_count": len(brief.get("near_miss_entries") or []),
        "opportunity_pool_count": len(brief.get("opportunity_pool_entries") or []),
        "no_history_observer_count": len(no_history_observer_entries),
        "risky_observer_count": len(risky_observer_entries),
        "catalyst_theme_frontier_promoted_count": len(
            catalyst_theme_frontier_priority.get("promoted_tickers") or []
        ),
        "catalyst_theme_shadow_count": len(
            brief.get("catalyst_theme_shadow_entries") or []
        ),
        "upstream_shadow_candidate_count": int(
            upstream_shadow_summary.get("shadow_candidate_count") or 0
        ),
        "upstream_shadow_promotable_count": int(
            upstream_shadow_summary.get("promotable_count") or 0
        ),
    }


def _append_indexed_ticker_blocks(
    lines: list[str],
    items: list[dict[str, Any]],
    render_item: Callable[[list[str], dict[str, Any]], None],
) -> None:
    _append_indexed_ticker_blocks_impl(lines, items, render_item)


def _append_titled_indexed_section(
    lines: list[str],
    *,
    title: str,
    items: list[dict[str, Any]],
    render_item: Callable[[list[str], dict[str, Any], int], None],
) -> None:
    _append_titled_indexed_section_impl(
        lines,
        title=title,
        items=items,
        render_item=render_item,
        append_none_block_fn=_append_none_block,
    )


def _append_titled_indexed_ticker_section(
    lines: list[str],
    *,
    title: str,
    items: list[dict[str, Any]],
    render_item: Callable[[list[str], dict[str, Any]], None],
) -> None:
    _append_titled_indexed_ticker_section_impl(
        lines,
        title=title,
        items=items,
        render_item=render_item,
        append_titled_indexed_section_fn=_append_titled_indexed_section,
        append_indexed_ticker_block_fn=_append_indexed_ticker_block,
    )


def _append_indexed_ticker_block(
    lines: list[str],
    item: dict[str, Any],
    index: int,
    render_item: Callable[[list[str], dict[str, Any]], None],
) -> None:
    _append_indexed_ticker_block_impl(lines, item, index, render_item)


def _append_opening_watch_focus_items_markdown(
    lines: list[str], focus_items: list[dict[str, Any]]
) -> None:
    _append_opening_watch_focus_items_markdown_impl(
        lines,
        focus_items,
        append_titled_indexed_ticker_section=_append_titled_indexed_ticker_section,
        format_float=_format_float,
    )


def _append_catalyst_theme_watch_markdown(
    lines: list[str],
    *,
    title: str,
    items: list[dict[str, Any]],
    focus_tier: str,
    execution_posture: str,
) -> None:
    _append_catalyst_theme_watch_markdown_impl(
        lines,
        title=title,
        items=items,
        focus_tier=focus_tier,
        execution_posture=execution_posture,
        append_none_block=_append_none_block,
        append_indexed_ticker_blocks=_append_indexed_ticker_blocks,
        append_candidate_watch_scoring_fields=_append_candidate_watch_scoring_fields,
        append_candidate_watch_reason_tags=_append_candidate_watch_reason_tags,
        append_threshold_shortfalls_line=_append_threshold_shortfalls_line,
        append_catalyst_watch_metrics=_append_catalyst_watch_metrics,
    )


def _append_upstream_shadow_recall_markdown(
    lines: list[str],
    upstream_shadow_summary: dict[str, Any],
    upstream_shadow_entries: list[dict[str, Any]],
) -> None:
    _append_upstream_shadow_section(
        lines,
        upstream_shadow_summary,
        upstream_shadow_entries,
        _append_opening_upstream_shadow_item,
    )


def render_btst_opening_watch_card_markdown(card: dict[str, Any]) -> str:
    lines: list[str] = []
    _append_opening_watch_overview_markdown(lines, card)
    _append_opening_watch_focus_items_markdown(
        lines, list(card.get("focus_items") or [])
    )
    _append_opening_watch_frontier_markdown(
        lines, dict(card.get("catalyst_theme_frontier_priority") or {})
    )
    _append_catalyst_theme_watch_markdown(
        lines,
        title="## Catalyst Theme Shadow Watch",
        items=list(card.get("catalyst_theme_shadow_watch") or []),
        focus_tier="catalyst_theme_shadow",
        execution_posture="research_followup_only",
    )

    _append_upstream_shadow_recall_markdown(
        lines,
        dict(card.get("upstream_shadow_summary") or {}),
        list(card.get("upstream_shadow_entries") or []),
    )
    _append_opening_watch_guardrails_markdown(
        lines, list(card.get("global_guardrails") or [])
    )
    _append_opening_watch_source_paths_markdown(
        lines, dict(card.get("source_paths") or {})
    )
    return "\n".join(lines) + "\n"


def _append_opening_watch_overview_markdown(
    lines: list[str], card: dict[str, Any]
) -> None:
    summary = dict(card.get("summary") or {})
    lines.append("# BTST Opening Watch Card")
    lines.append("")
    lines.append("## Opening Headline")
    lines.append(f"- trade_date: {card.get('trade_date')}")
    lines.append(f"- next_trade_date: {card.get('next_trade_date') or 'n/a'}")
    lines.append(f"- selection_target: {card.get('selection_target')}")
    lines.append(f"- headline: {card.get('headline')}")
    lines.append(f"- primary_count: {summary.get('primary_count')}")
    lines.append(f"- near_miss_count: {summary.get('near_miss_count')}")
    lines.append(f"- opportunity_pool_count: {summary.get('opportunity_pool_count')}")
    lines.append(
        f"- no_history_observer_count: {summary.get('no_history_observer_count')}"
    )
    lines.append(f"- risky_observer_count: {summary.get('risky_observer_count')}")
    lines.append(
        f"- catalyst_theme_frontier_promoted_count: {summary.get('catalyst_theme_frontier_promoted_count')}"
    )
    lines.append(
        f"- catalyst_theme_shadow_count: {summary.get('catalyst_theme_shadow_count')}"
    )
    lines.append(
        f"- upstream_shadow_candidate_count: {summary.get('upstream_shadow_candidate_count')}"
    )
    lines.append(
        f"- upstream_shadow_promotable_count: {summary.get('upstream_shadow_promotable_count')}"
    )
    lines.append(f"- recommendation: {card.get('recommendation')}")
    lines.append("")


def _append_opening_watch_frontier_markdown(
    lines: list[str], catalyst_theme_frontier_priority: dict[str, Any]
) -> None:
    _append_frontier_section(
        lines, catalyst_theme_frontier_priority, _append_opening_frontier_entries
    )


def _append_opening_frontier_entries(
    lines: list[str], items: list[dict[str, Any]]
) -> None:
    _append_catalyst_theme_watch_markdown(
        lines,
        title="",
        items=items,
        focus_tier="catalyst_theme_frontier_priority",
        execution_posture="research_followup_priority",
    )


def _append_opening_watch_guardrails_markdown(
    lines: list[str], guardrails: list[str]
) -> None:
    _append_guardrail_section(lines, "## Guardrails", guardrails)


def _append_opening_watch_source_paths_markdown(
    lines: list[str], source_paths: dict[str, Any]
) -> None:
    _append_source_paths_section(
        lines,
        report_dir=source_paths.get("report_dir"),
        snapshot_path=source_paths.get("snapshot_path"),
        session_summary_path=source_paths.get("session_summary_path"),
    )


def _build_priority_board_row(
    entry: dict[str, Any],
    *,
    lane: str,
    actionability: str,
    default_action: str,
    default_why_now: str,
    execution_note_mode: str = "historical",
    historical_default_monitor_priority: str = "unscored",
    opening_plan_key: str | None = None,
    research_score_target: Any | None = None,
) -> dict[str, Any]:
    historical_prior = dict(entry.get("historical_prior") or {})
    if lane in {"primary_entry", "selected_backup"}:
        _, trigger_rules = _selected_action_posture(entry.get("preferred_entry_mode"))
        suggested_action = trigger_rules[0] if trigger_rules else "盘中确认后再执行。"
    else:
        _, suggested_action = _entry_mode_action_guidance(
            entry.get("preferred_entry_mode"),
            default_action=default_action,
        )
    if opening_plan_key:
        suggested_action = str(entry.get(opening_plan_key) or suggested_action)
    execution_note = (
        _augment_execution_note(entry.get("preferred_entry_mode"), historical_prior)
        if execution_note_mode == "augment"
        else historical_prior.get("execution_note")
    )
    return {
        "ticker": entry.get("ticker"),
        "lane": lane,
        "actionability": actionability,
        "monitor_priority": historical_prior.get("monitor_priority")
        or historical_default_monitor_priority,
        "execution_priority": historical_prior.get("execution_priority") or "unscored",
        "execution_quality_label": historical_prior.get("execution_quality_label")
        or "unknown",
        "score_target": entry.get("score_target"),
        "research_score_target": research_score_target,
        "preferred_entry_mode": entry.get("preferred_entry_mode"),
        "why_now": ", ".join(entry.get("top_reasons") or []) or default_why_now,
        "suggested_action": suggested_action,
        "historical_summary": historical_prior.get("summary"),
        "execution_note": execution_note,
    }


def _build_priority_board_headline(
    *,
    brief: dict[str, Any],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
) -> str:
    headline = "当前没有可执行主票，priority board 只保留观察与漏票线索。"
    if brief.get("primary_entry"):
        headline = "先执行主票确认，再按 near-miss、机会池、research 漏票雷达递减关注。"
    elif brief.get("near_miss_entries"):
        headline = "当前没有主票，优先看 near-miss，其次看机会池和 research 漏票雷达。"
    elif no_history_observer_entries:
        headline = "当前没有标准 BTST 候选，只保留无历史先验观察与研究跟踪。"
    elif risky_observer_entries:
        headline = "当前没有标准 BTST 候选，只有高风险盘中观察与研究跟踪。"
    if catalyst_theme_frontier_priority.get("promoted_tickers"):
        headline = (
            headline.rstrip("。")
            + "；题材催化前沿 research priority 为 "
            + ", ".join(catalyst_theme_frontier_priority.get("promoted_tickers") or [])
            + "。"
        )
    return headline


def analyze_btst_next_day_priority_board(
    input_path: str | Path | dict[str, Any],
    trade_date: str | None = None,
    next_trade_date: str | None = None,
) -> dict[str, Any]:
    brief = _resolve_brief_analysis(
        input_path, trade_date=trade_date, next_trade_date=next_trade_date
    )
    board_context = _build_priority_board_context(brief)
    catalyst_theme_frontier_priority = board_context["catalyst_theme_frontier_priority"]
    catalyst_theme_shadow_watch = board_context["catalyst_theme_shadow_watch"]
    selected_entries = board_context["selected_entries"]
    near_miss_entries = board_context["near_miss_entries"]
    opportunity_pool_entries = board_context["opportunity_pool_entries"]
    no_history_observer_entries = board_context["no_history_observer_entries"]
    risky_observer_entries = board_context["risky_observer_entries"]
    priority_rows = _build_priority_board_rows(
        brief=brief,
        selected_entries=selected_entries,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        no_history_observer_entries=no_history_observer_entries,
        risky_observer_entries=risky_observer_entries,
    )
    _sort_priority_board_rows(priority_rows)

    headline = _build_priority_board_headline(
        brief=brief,
        no_history_observer_entries=no_history_observer_entries,
        risky_observer_entries=risky_observer_entries,
        catalyst_theme_frontier_priority=catalyst_theme_frontier_priority,
    )

    return {
        "trade_date": brief.get("trade_date"),
        "next_trade_date": brief.get("next_trade_date"),
        "selection_target": brief.get("selection_target"),
        "headline": headline,
        "summary": _build_priority_board_summary(
            brief=brief,
            no_history_observer_entries=no_history_observer_entries,
            risky_observer_entries=risky_observer_entries,
            catalyst_theme_frontier_priority=catalyst_theme_frontier_priority,
        ),
        "priority_rows": priority_rows,
        "catalyst_theme_frontier_priority": catalyst_theme_frontier_priority,
        "catalyst_theme_shadow_watch": catalyst_theme_shadow_watch,
        "global_guardrails": [
            "priority board 只负责排序和分层，不改变 short-trade admission 默认语义。",
            "题材催化影子池只做研究跟踪，不进入当日 BTST 交易名单。",
            "research_upside_radar 只做上涨线索学习，不进入当日 BTST 交易名单。",
            "所有交易候选都仍需盘中确认，不因历史先验直接跳过执行 guardrail。",
        ],
        "source_paths": {
            "report_dir": brief.get("report_dir"),
            "snapshot_path": brief.get("snapshot_path"),
            "session_summary_path": brief.get("session_summary_path"),
        },
    }


def _build_priority_board_context(brief: dict[str, Any]) -> dict[str, Any]:
    return {
        "catalyst_theme_frontier_priority": dict(
            brief.get("catalyst_theme_frontier_priority") or {}
        ),
        "catalyst_theme_shadow_watch": _build_catalyst_theme_shadow_watch_rows(
            list(brief.get("catalyst_theme_shadow_entries") or [])
        ),
        "selected_entries": [
            _apply_execution_quality_entry_mode(entry)
            for entry in list(brief.get("selected_entries") or [])
        ],
        "near_miss_entries": [
            _apply_execution_quality_entry_mode(entry)
            for entry in list(brief.get("near_miss_entries") or [])
        ],
        "opportunity_pool_entries": [
            _apply_execution_quality_entry_mode(entry)
            for entry in list(brief.get("opportunity_pool_entries") or [])
        ],
        "no_history_observer_entries": [
            _apply_execution_quality_entry_mode(entry)
            for entry in list(brief.get("no_history_observer_entries") or [])
        ],
        "risky_observer_entries": [
            _apply_execution_quality_entry_mode(entry)
            for entry in list(brief.get("risky_observer_entries") or [])
        ],
    }


def _build_priority_board_rows(
    *,
    brief: dict[str, Any],
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    opportunity_pool_entries: list[dict[str, Any]],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        *_build_selected_priority_rows(selected_entries),
        *_build_near_miss_priority_rows(near_miss_entries),
        *_build_opportunity_pool_priority_rows(opportunity_pool_entries),
        *_build_no_history_observer_priority_rows(no_history_observer_entries),
        *_build_risky_observer_priority_rows(risky_observer_entries),
        *_build_research_upside_priority_rows(
            list(brief.get("research_upside_radar_entries") or [])
        ),
    ]


def _build_selected_priority_rows(
    selected_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_priority_board_row(
            entry,
            lane="primary_entry" if index == 0 else "selected_backup",
            actionability="trade_candidate",
            default_action="盘中确认后再执行。",
            default_why_now="当前 short-trade selected。",
            execution_note_mode="augment",
            historical_default_monitor_priority="high",
        )
        for index, entry in enumerate(selected_entries)
    ]


def _build_near_miss_priority_rows(
    near_miss_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_priority_board_row(
            entry,
            lane="near_miss_watch",
            actionability="watch_only",
            default_action="仅做盘中跟踪，不预设主买入动作。",
            default_why_now="当前接近 near-miss 边界。",
            execution_note_mode="augment",
        )
        for entry in near_miss_entries
    ]


def _build_opportunity_pool_priority_rows(
    opportunity_pool_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_priority_board_row(
            entry,
            lane="opportunity_pool",
            actionability="upgrade_only",
            default_action=str(
                entry.get("promotion_trigger") or "只有盘中新强度确认时才升级。"
            ),
            default_why_now="结构未坏但仍在机会池。",
        )
        for entry in opportunity_pool_entries
    ]


def _build_no_history_observer_priority_rows(
    no_history_observer_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_priority_board_row(
            entry,
            lane="no_history_observer",
            actionability="observe_only_no_history",
            default_action=str(
                entry.get("promotion_trigger")
                or "暂无可评估历史先验，只做盘中新证据观察。"
            ),
            default_why_now="暂无可评估历史先验。",
        )
        for entry in no_history_observer_entries
    ]


def _build_risky_observer_priority_rows(
    risky_observer_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_priority_board_row(
            entry,
            lane="risky_observer",
            actionability="high_risk_watch_only",
            default_action="只做高风险盘中观察，不做标准 BTST 升级。",
            default_why_now="当前属于高风险观察桶。",
        )
        for entry in risky_observer_entries
    ]


def _build_research_upside_priority_rows(
    research_upside_radar_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _build_priority_board_row(
            entry,
            lane="research_upside_radar",
            actionability="non_trade_learning_only",
            default_action="只做漏票学习，不加入当日 BTST 交易名单。",
            default_why_now="research 已选中但 BTST 未放行。",
            opening_plan_key="radar_note",
            research_score_target=entry.get("research_score_target"),
        )
        for entry in research_upside_radar_entries
    ]


def _sort_priority_board_rows(priority_rows: list[dict[str, Any]]) -> None:
    lane_rank = {
        "primary_entry": 0,
        "selected_backup": 1,
        "near_miss_watch": 2,
        "opportunity_pool": 3,
        "no_history_observer": 4,
        "risky_observer": 5,
        "research_upside_radar": 6,
    }
    priority_rows.sort(
        key=lambda row: (
            lane_rank.get(str(row.get("lane") or "research_upside_radar"), 9),
            _monitor_priority_rank(row.get("monitor_priority")),
            _execution_priority_rank(row.get("execution_priority")),
            -(row.get("research_score_target") or 0.0),
            -_as_float(row.get("score_target")),
            str(row.get("ticker") or ""),
        )
    )


def _build_priority_board_summary(
    *,
    brief: dict[str, Any],
    no_history_observer_entries: list[dict[str, Any]],
    risky_observer_entries: list[dict[str, Any]],
    catalyst_theme_frontier_priority: dict[str, Any],
) -> dict[str, Any]:
    return {
        "primary_count": len(brief.get("selected_entries") or []),
        "near_miss_count": len(brief.get("near_miss_entries") or []),
        "opportunity_pool_count": len(brief.get("opportunity_pool_entries") or []),
        "no_history_observer_count": len(no_history_observer_entries),
        "risky_observer_count": len(risky_observer_entries),
        "research_upside_radar_count": len(
            brief.get("research_upside_radar_entries") or []
        ),
        "catalyst_theme_count": len(brief.get("catalyst_theme_entries") or []),
        "catalyst_theme_frontier_promoted_count": len(
            catalyst_theme_frontier_priority.get("promoted_tickers") or []
        ),
        "catalyst_theme_shadow_count": len(
            brief.get("catalyst_theme_shadow_entries") or []
        ),
    }


def render_btst_next_day_priority_board_markdown(board: dict[str, Any]) -> str:
    lines: list[str] = []
    _append_priority_board_overview_markdown(lines, board)
    _append_priority_board_rows_markdown(lines, list(board.get("priority_rows") or []))
    _append_priority_board_frontier_markdown(
        lines, dict(board.get("catalyst_theme_frontier_priority") or {})
    )
    _append_priority_board_shadow_watch_markdown(
        lines, list(board.get("catalyst_theme_shadow_watch") or [])
    )
    _append_priority_board_guardrails_markdown(
        lines, list(board.get("global_guardrails") or [])
    )
    _append_priority_board_source_paths_markdown(
        lines, dict(board.get("source_paths") or {})
    )
    return "\n".join(lines) + "\n"


def _append_priority_board_overview_markdown(
    lines: list[str], board: dict[str, Any]
) -> None:
    _append_priority_board_overview_markdown_impl(lines, board)


def _append_priority_board_rows_markdown(
    lines: list[str], priority_rows: list[dict[str, Any]]
) -> None:
    _append_priority_board_rows_markdown_impl(
        lines,
        priority_rows,
        append_titled_indexed_ticker_section=_append_titled_indexed_ticker_section,
        format_float=_format_float,
    )


def _append_priority_board_frontier_markdown(
    lines: list[str], catalyst_theme_frontier_priority: dict[str, Any]
) -> None:
    _append_priority_board_frontier_markdown_impl(
        lines,
        catalyst_theme_frontier_priority,
        append_frontier_section=_append_frontier_section,
        append_indexed_ticker_blocks=_append_indexed_ticker_blocks,
        append_threshold_shortfalls_line=_append_threshold_shortfalls_line,
        append_catalyst_watch_metrics=_append_catalyst_watch_metrics,
        format_float=_format_float,
    )


def _append_priority_board_shadow_watch_markdown(
    lines: list[str], catalyst_theme_shadow_watch: list[dict[str, Any]]
) -> None:
    _append_priority_board_shadow_watch_markdown_impl(
        lines,
        catalyst_theme_shadow_watch,
        append_titled_indexed_ticker_section=_append_titled_indexed_ticker_section,
        append_threshold_shortfalls_line=_append_threshold_shortfalls_line,
        append_catalyst_watch_metrics=_append_catalyst_watch_metrics,
        format_float=_format_float,
    )


def _append_priority_board_guardrails_markdown(
    lines: list[str], guardrails: list[str]
) -> None:
    _append_guardrail_section(lines, "## Guardrails", guardrails)


def _append_priority_board_source_paths_markdown(
    lines: list[str], source_paths: dict[str, Any]
) -> None:
    _append_source_paths_section(
        lines,
        report_dir=source_paths.get("report_dir"),
        snapshot_path=source_paths.get("snapshot_path"),
        session_summary_path=source_paths.get("session_summary_path"),
    )


def _build_output_file_stem(
    prefix: str, trade_date: str | None, next_trade_date: str | None
) -> str:
    compact_trade_date = _compact_trade_date(trade_date) or "unknown"
    compact_next_trade_date = _compact_trade_date(next_trade_date) or "unknown"
    return f"{prefix}_{compact_trade_date}_for_{compact_next_trade_date}"


def _build_next_trade_date_file_stem(prefix: str, next_trade_date: str | None) -> str:
    return f"{prefix}_{_compact_trade_date(next_trade_date) or 'unknown'}"


def _write_analysis_artifacts(
    *,
    payload: dict[str, Any],
    render_markdown: Callable[[dict[str, Any]], str],
    resolved_output_dir: Path,
    stem: str,
) -> dict[str, Any]:
    output_json = resolved_output_dir / f"{stem}.json"
    output_md = resolved_output_dir / f"{stem}.md"
    output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    output_md.write_text(render_markdown(payload), encoding="utf-8")
    return {
        "analysis": payload,
        "json_path": str(output_json),
        "markdown_path": str(output_md),
    }


def _resolve_followup_artifact_context(
    *,
    report_dir: str | Path,
    trade_date: str | None,
    next_trade_date: str | None,
    brief_file_stem: str,
) -> tuple[Path, str | None, str | None, dict[str, Any]]:
    return _resolve_followup_artifact_context_impl(
        report_dir=report_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        brief_file_stem=brief_file_stem,
        normalize_trade_date=_normalize_trade_date,
        infer_next_trade_date=infer_next_trade_date,
        generate_btst_next_day_trade_brief_artifacts=generate_btst_next_day_trade_brief_artifacts,
    )


def generate_btst_next_day_trade_brief_artifacts(
    input_path: str | Path,
    output_dir: str | Path,
    trade_date: str | None = None,
    next_trade_date: str | None = None,
    file_stem: str | None = None,
) -> dict[str, Any]:
    return _generate_btst_next_day_trade_brief_artifacts_impl(
        input_path=input_path,
        output_dir=output_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        file_stem=file_stem,
        analyze_btst_next_day_trade_brief=analyze_btst_next_day_trade_brief,
        render_btst_next_day_trade_brief_markdown=render_btst_next_day_trade_brief_markdown,
        build_output_file_stem=_build_output_file_stem,
        write_analysis_artifacts=_write_analysis_artifacts,
    )


def generate_btst_premarket_execution_card_artifacts(
    input_path: str | Path | dict[str, Any],
    output_dir: str | Path,
    trade_date: str | None = None,
    next_trade_date: str | None = None,
    file_stem: str | None = None,
) -> dict[str, Any]:
    return _generate_btst_premarket_execution_card_artifacts_impl(
        input_path=input_path,
        output_dir=output_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        file_stem=file_stem,
        analyze_btst_premarket_execution_card=analyze_btst_premarket_execution_card,
        render_btst_premarket_execution_card_markdown=render_btst_premarket_execution_card_markdown,
        build_output_file_stem=_build_output_file_stem,
        write_analysis_artifacts=_write_analysis_artifacts,
    )


def generate_btst_opening_watch_card_artifacts(
    input_path: str | Path | dict[str, Any],
    output_dir: str | Path,
    trade_date: str | None = None,
    next_trade_date: str | None = None,
    file_stem: str | None = None,
) -> dict[str, Any]:
    return _generate_btst_opening_watch_card_artifacts_impl(
        input_path=input_path,
        output_dir=output_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        file_stem=file_stem,
        analyze_btst_opening_watch_card=analyze_btst_opening_watch_card,
        render_btst_opening_watch_card_markdown=render_btst_opening_watch_card_markdown,
        build_next_trade_date_file_stem=_build_next_trade_date_file_stem,
        write_analysis_artifacts=_write_analysis_artifacts,
    )


def generate_btst_next_day_priority_board_artifacts(
    input_path: str | Path | dict[str, Any],
    output_dir: str | Path,
    trade_date: str | None = None,
    next_trade_date: str | None = None,
    file_stem: str | None = None,
) -> dict[str, Any]:
    return _generate_btst_next_day_priority_board_artifacts_impl(
        input_path=input_path,
        output_dir=output_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        file_stem=file_stem,
        analyze_btst_next_day_priority_board=analyze_btst_next_day_priority_board,
        render_btst_next_day_priority_board_markdown=render_btst_next_day_priority_board_markdown,
        build_next_trade_date_file_stem=_build_next_trade_date_file_stem,
        write_analysis_artifacts=_write_analysis_artifacts,
    )


def register_btst_followup_artifacts(
    report_dir: str | Path,
    *,
    trade_date: str | None,
    next_trade_date: str | None,
    brief_json_path: str | Path,
    brief_markdown_path: str | Path,
    card_json_path: str | Path,
    card_markdown_path: str | Path,
    opening_card_json_path: str | Path,
    opening_card_markdown_path: str | Path,
    priority_board_json_path: str | Path,
    priority_board_markdown_path: str | Path,
) -> dict[str, Any]:
    return _register_btst_followup_artifacts_impl(
        report_dir=report_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        brief_json_path=brief_json_path,
        brief_markdown_path=brief_markdown_path,
        card_json_path=card_json_path,
        card_markdown_path=card_markdown_path,
        opening_card_json_path=opening_card_json_path,
        opening_card_markdown_path=opening_card_markdown_path,
        priority_board_json_path=priority_board_json_path,
        priority_board_markdown_path=priority_board_markdown_path,
        load_json=_load_json,
        resolve_followup_trade_dates=_resolve_followup_trade_dates,
        sync_text_artifact_alias=_sync_text_artifact_alias,
        write_json=_write_json,
    )


def generate_and_register_btst_followup_artifacts(
    report_dir: str | Path,
    trade_date: str | None,
    next_trade_date: str | None = None,
    *,
    brief_file_stem: str = "btst_next_day_trade_brief_latest",
    card_file_stem: str = "btst_premarket_execution_card_latest",
    opening_card_file_stem: str | None = None,
    priority_board_file_stem: str | None = None,
) -> dict[str, Any]:
    return _generate_and_register_btst_followup_artifacts_impl(
        report_dir=report_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        brief_file_stem=brief_file_stem,
        card_file_stem=card_file_stem,
        opening_card_file_stem=opening_card_file_stem,
        priority_board_file_stem=priority_board_file_stem,
        build_next_trade_date_file_stem=_build_next_trade_date_file_stem,
        resolve_followup_artifact_context=_resolve_followup_artifact_context,
        generate_btst_premarket_execution_card_artifacts=generate_btst_premarket_execution_card_artifacts,
        generate_btst_opening_watch_card_artifacts=generate_btst_opening_watch_card_artifacts,
        generate_btst_next_day_priority_board_artifacts=generate_btst_next_day_priority_board_artifacts,
        register_btst_followup_artifacts=register_btst_followup_artifacts,
    )
