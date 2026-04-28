"""Entry extraction and building functions.

Pure data transformers that build various entry dicts from raw selection data,
historical reports, and upstream shadow data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.paper_trading.btst_reporting_utils import (
    OPPORTUNITY_POOL_HISTORICAL_LOOKBACK_REPORTS,
    OPPORTUNITY_POOL_MIN_SCORE_TARGET,
    OPPORTUNITY_POOL_STRONG_SIGNAL_MIN,
    UPSTREAM_SHADOW_CANDIDATE_SOURCES,
    WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT,
    _as_float,
    _load_json,
    _normalize_trade_date,
    _round_or_none,
    _source_lane_display,
    _source_lane_label,
)
from src.paper_trading._btst_reporting.extractors import (
    _build_upstream_shadow_promotion_trigger,
    _extract_short_trade_core_metrics,
    _resolve_upstream_shadow_candidate_reason_codes,
)
from src.paper_trading._btst_reporting.entry_transforms import (
    CATALYST_THEME_SHADOW_WATCH_MAX_ENTRIES,
    _build_catalyst_theme_shadow_watch_rows as _build_catalyst_theme_shadow_watch_rows_direct,
)
from scripts.btst_latest_followup_utils import _choose_preferred_historical_prior
from src.tools.akshare_api import get_prices_robust
from src.tools.api import get_price_data, prices_to_df


CATALYST_THEME_MAX_ENTRIES = 5
CATALYST_THEME_SHADOW_MAX_ENTRIES = 5

FORMAL_EXECUTION_BLOCK_FLAGS = (
    "p2_execution_blocked",
    "p3_execution_blocked",
    "p5_execution_blocked",
    "p6_execution_blocked",
)


def _collect_formal_execution_block_flags(
    selection_entry: dict[str, Any], short_trade_entry: dict[str, Any] | None = None
) -> list[str]:
    short_trade_entry = dict(short_trade_entry or selection_entry.get("short_trade") or {})
    return [
        flag
        for flag in FORMAL_EXECUTION_BLOCK_FLAGS
        if bool(selection_entry.get(flag)) or bool(short_trade_entry.get(flag))
    ]


def _is_formal_execution_blocked_entry(entry: dict[str, Any]) -> bool:
    if bool(entry.get("execution_blocked")):
        return True
    if str(entry.get("reporting_decision") or "").strip() == "blocked":
        return True
    return any(bool(entry.get(flag)) for flag in FORMAL_EXECUTION_BLOCK_FLAGS)


def _filter_execution_ready_entries(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        dict(entry)
        for entry in entries
        if not _is_formal_execution_blocked_entry(entry)
    ]


def _resolve_formal_shadow_decision(
    selection_entry: dict[str, Any], short_trade_entry: dict[str, Any]
) -> tuple[str, list[str]]:
    execution_blocked_flags = _collect_formal_execution_block_flags(
        selection_entry, short_trade_entry
    )
    raw_decision = str(short_trade_entry.get("decision") or "rejected")
    formal_decision = "blocked" if execution_blocked_flags else raw_decision
    return formal_decision, execution_blocked_flags


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
    decision, execution_blocked_flags = _resolve_formal_shadow_decision(
        selection_entry, short_trade_entry
    )
    promotion_trigger = _build_upstream_shadow_promotion_trigger(decision)

    return {
        "ticker": selection_entry.get("ticker"),
        "decision": decision,
        "reporting_decision": decision,
        "short_trade_decision": str(short_trade_entry.get("decision") or "rejected"),
        "execution_blocked": bool(execution_blocked_flags),
        "execution_blocked_flags": execution_blocked_flags,
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
        decision = str(
            entry.get("reporting_decision") or entry.get("decision") or "rejected"
        )
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
            if str(entry.get("reporting_decision") or entry.get("decision") or "")
            in {"selected", "near_miss"}
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

    execution_blocked_flags = _collect_formal_execution_block_flags(
        selection_entry, short_trade_entry
    )
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
        "reporting_decision": "blocked" if execution_blocked_flags else decision,
        "execution_blocked": bool(execution_blocked_flags),
        "execution_blocked_flags": execution_blocked_flags,
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
    return _build_catalyst_theme_shadow_watch_rows_direct(entries, limit=limit)
