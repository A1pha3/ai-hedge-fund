from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

import pandas as pd

from src.project_env import load_project_dotenv
from src.tools.akshare_api import get_prices_robust
from src.tools.api import get_price_data, prices_to_df
from src.tools.tushare_api import _cached_tushare_dataframe_call, _get_pro


load_project_dotenv()


OPPORTUNITY_POOL_MIN_SCORE_TARGET = 0.30
OPPORTUNITY_POOL_STRONG_SIGNAL_MIN = 0.65
OPPORTUNITY_POOL_MAX_ENTRIES = 3
OPPORTUNITY_POOL_HISTORICAL_LOOKBACK_REPORTS = 24
OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD = 0.02
OPPORTUNITY_POOL_HISTORICAL_SAME_TICKER_MIN_SAMPLES = 2
WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT = 3
WATCH_CANDIDATE_HISTORICAL_SCORE_BUCKET_SIZE = 0.05
RESEARCH_UPSIDE_RADAR_MAX_ENTRIES = 3
CATALYST_THEME_MAX_ENTRIES = 5
CATALYST_THEME_SHADOW_MAX_ENTRIES = 5
CATALYST_THEME_SHADOW_WATCH_MAX_ENTRIES = 3
UPSTREAM_SHADOW_CANDIDATE_SOURCES = {
    "upstream_liquidity_corridor_shadow": "layer_a_liquidity_corridor",
    "post_gate_liquidity_competition_shadow": "post_gate_liquidity_competition",
}


def _shadow_decision_rank(decision: str | None) -> int:
    return {
        "selected": 0,
        "near_miss": 1,
        "observation": 2,
        "blocked": 3,
        "rejected": 4,
    }.get(str(decision or "rejected"), 5)


def _source_lane_label(candidate_source: str | None) -> str:
    normalized = str(candidate_source or "")
    return UPSTREAM_SHADOW_CANDIDATE_SOURCES.get(normalized, normalized or "unknown")


def _source_lane_display(candidate_source: str | None) -> str:
    return {
        "upstream_liquidity_corridor_shadow": "layer_a_liquidity_corridor",
        "post_gate_liquidity_competition_shadow": "post_gate_liquidity_competition",
    }.get(str(candidate_source or ""), str(candidate_source or "unknown"))


def _resolve_replay_input_path(snapshot_path: str | Path) -> Path:
    return Path(snapshot_path).expanduser().resolve().with_name("selection_target_replay_input.json")


def _load_selection_replay_input(snapshot_path: str | Path) -> dict[str, Any]:
    replay_input_path = _resolve_replay_input_path(snapshot_path)
    if not replay_input_path.exists():
        return {}
    return _load_json(replay_input_path)


def _extract_upstream_shadow_entry(selection_entry: dict[str, Any], supplemental_entry: dict[str, Any] | None = None) -> dict[str, Any] | None:
    short_trade_entry = dict(selection_entry.get("short_trade") or {})
    if not short_trade_entry:
        return None

    explainability_payload = dict(short_trade_entry.get("explainability_payload") or {})
    replay_context = dict(explainability_payload.get("replay_context") or {})
    candidate_source = str(explainability_payload.get("candidate_source") or selection_entry.get("candidate_source") or replay_context.get("source") or "")
    if candidate_source not in UPSTREAM_SHADOW_CANDIDATE_SOURCES:
        return None

    supplemental_entry = dict(supplemental_entry or {})
    metrics_payload = dict(short_trade_entry.get("metrics_payload") or {})
    candidate_reason_codes = [
        str(reason)
        for reason in (
            list(selection_entry.get("candidate_reason_codes") or [])
            or list(supplemental_entry.get("candidate_reason_codes") or [])
            or list(replay_context.get("candidate_reason_codes") or [])
        )
        if str(reason or "").strip()
    ]
    candidate_pool_lane = str(
        supplemental_entry.get("candidate_pool_lane")
        or replay_context.get("candidate_pool_lane")
        or _source_lane_label(candidate_source)
    )
    candidate_pool_rank = supplemental_entry.get("candidate_pool_rank") or replay_context.get("candidate_pool_rank")
    decision = str(short_trade_entry.get("decision") or "rejected")

    if decision == "selected":
        promotion_trigger = "影子召回样本已晋级为正式 short-trade selected，但仍需盘中确认后才能执行。"
    elif decision == "near_miss":
        promotion_trigger = "影子召回样本已进入 near-miss 观察层，只能做盘中跟踪，不可预设交易。"
    else:
        promotion_trigger = "影子召回样本尚未进入可执行层，只有盘中新强度确认后才允许升级。"

    return {
        "ticker": selection_entry.get("ticker"),
        "decision": decision,
        "score_target": short_trade_entry.get("score_target"),
        "confidence": short_trade_entry.get("confidence"),
        "preferred_entry_mode": short_trade_entry.get("preferred_entry_mode"),
        "candidate_source": candidate_source,
        "candidate_pool_lane": candidate_pool_lane,
        "candidate_pool_lane_display": _source_lane_display(candidate_source),
        "candidate_pool_rank": int(candidate_pool_rank) if candidate_pool_rank not in (None, "") else None,
        "candidate_pool_avg_amount_share_of_cutoff": _round_or_none(
            supplemental_entry.get("candidate_pool_avg_amount_share_of_cutoff") or replay_context.get("candidate_pool_avg_amount_share_of_cutoff")
        ),
        "candidate_pool_avg_amount_share_of_min_gate": _round_or_none(
            supplemental_entry.get("candidate_pool_avg_amount_share_of_min_gate") or replay_context.get("candidate_pool_avg_amount_share_of_min_gate")
        ),
        "upstream_candidate_source": str(
            supplemental_entry.get("upstream_candidate_source") or replay_context.get("upstream_candidate_source") or "candidate_pool_truncated_after_filters"
        ),
        "candidate_reason_codes": candidate_reason_codes,
        "top_reasons": list(short_trade_entry.get("top_reasons") or []),
        "rejection_reasons": list(short_trade_entry.get("rejection_reasons") or []),
        "positive_tags": list(short_trade_entry.get("positive_tags") or []),
        "gate_status": dict(short_trade_entry.get("gate_status") or {}),
        "promotion_trigger": promotion_trigger,
        "metrics": {
            "breakout_freshness": metrics_payload.get("breakout_freshness"),
            "trend_acceleration": metrics_payload.get("trend_acceleration"),
            "volume_expansion_quality": metrics_payload.get("volume_expansion_quality"),
            "close_strength": metrics_payload.get("close_strength"),
            "catalyst_freshness": metrics_payload.get("catalyst_freshness"),
        },
    }


def _extract_upstream_shadow_replay_only_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    candidate_source = str(entry.get("candidate_source") or "")
    if candidate_source not in UPSTREAM_SHADOW_CANDIDATE_SOURCES:
        return None

    metrics_payload = dict(entry.get("metrics") or entry.get("short_trade_boundary_metrics") or {})
    candidate_pool_rank = entry.get("candidate_pool_rank")
    return {
        "ticker": entry.get("ticker"),
        "decision": str(entry.get("decision") or "observation"),
        "score_target": entry.get("score_target") if entry.get("score_target") is not None else metrics_payload.get("candidate_score"),
        "confidence": entry.get("confidence"),
        "preferred_entry_mode": entry.get("preferred_entry_mode") or "shadow_observation_only",
        "candidate_source": candidate_source,
        "candidate_pool_lane": str(entry.get("candidate_pool_lane") or _source_lane_label(candidate_source)),
        "candidate_pool_lane_display": _source_lane_display(candidate_source),
        "candidate_pool_rank": int(candidate_pool_rank) if candidate_pool_rank not in (None, "") else None,
        "candidate_pool_avg_amount_share_of_cutoff": _round_or_none(entry.get("candidate_pool_avg_amount_share_of_cutoff")),
        "candidate_pool_avg_amount_share_of_min_gate": _round_or_none(entry.get("candidate_pool_avg_amount_share_of_min_gate")),
        "upstream_candidate_source": str(entry.get("upstream_candidate_source") or "candidate_pool_truncated_after_filters"),
        "candidate_reason_codes": [str(reason) for reason in list(entry.get("candidate_reason_codes") or []) if str(reason or "").strip()],
        "top_reasons": list(entry.get("top_reasons") or []),
        "rejection_reasons": list(entry.get("rejection_reasons") or ([entry.get("filter_reason")] if entry.get("filter_reason") else [])),
        "positive_tags": list(entry.get("positive_tags") or []),
        "gate_status": dict(entry.get("gate_status") or {}),
        "promotion_trigger": str(entry.get("promotion_trigger") or "影子召回样本当前只保留为补票观察层，不自动升级到正式执行名单。"),
        "metrics": {
            "breakout_freshness": metrics_payload.get("breakout_freshness"),
            "trend_acceleration": metrics_payload.get("trend_acceleration"),
            "volume_expansion_quality": metrics_payload.get("volume_expansion_quality"),
            "close_strength": metrics_payload.get("close_strength"),
            "catalyst_freshness": metrics_payload.get("catalyst_freshness"),
        },
    }


def _build_upstream_shadow_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    lane_counts: dict[str, int] = {}
    decision_counts: dict[str, int] = {}
    for entry in entries:
        lane = str(entry.get("candidate_pool_lane") or _source_lane_label(entry.get("candidate_source")))
        decision = str(entry.get("decision") or "rejected")
        lane_counts[lane] = int(lane_counts.get(lane) or 0) + 1
        decision_counts[decision] = int(decision_counts.get(decision) or 0) + 1

    top_focus_tickers = [str(entry.get("ticker") or "") for entry in entries if entry.get("ticker")][:3]
    return {
        "shadow_candidate_count": len(entries),
        "promotable_count": sum(1 for entry in entries if str(entry.get("decision") or "") in {"selected", "near_miss"}),
        "lane_counts": lane_counts,
        "decision_counts": decision_counts,
        "top_focus_tickers": top_focus_tickers,
    }


def _extract_catalyst_theme_frontier_summary(frontier: dict[str, Any]) -> dict[str, Any]:
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
        "recommended_relaxation_cost": recommended_variant.get("threshold_relaxation_cost"),
        "recommended_thresholds": dict(recommended_variant.get("thresholds") or {}),
        "recommended_promoted_tickers": [str(row.get("ticker") or "") for row in top_promoted_rows if row.get("ticker")][:3],
        "recommendation": frontier.get("recommendation"),
    }


def _load_catalyst_theme_frontier_summary(report_dir: str | Path | None) -> dict[str, Any]:
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
    summary["markdown_path"] = str(frontier_markdown_path.resolve()) if frontier_markdown_path.exists() else None
    return summary


def _build_catalyst_theme_frontier_priority(frontier_summary: dict[str, Any], shadow_entries: list[dict[str, Any]]) -> dict[str, Any]:
    if not frontier_summary:
        return {}

    promoted_tickers = [str(ticker or "") for ticker in list(frontier_summary.get("recommended_promoted_tickers") or []) if ticker]
    promoted_entries = [entry for entry in shadow_entries if str(entry.get("ticker") or "") in promoted_tickers]
    return {
        "status": frontier_summary.get("status"),
        "recommended_variant_name": frontier_summary.get("recommended_variant_name"),
        "recommended_relaxation_cost": frontier_summary.get("recommended_relaxation_cost"),
        "recommended_thresholds": dict(frontier_summary.get("recommended_thresholds") or {}),
        "promoted_shadow_count": len(promoted_entries) or int(frontier_summary.get("recommended_promoted_shadow_count") or 0),
        "promoted_tickers": promoted_tickers,
        "recommendation": frontier_summary.get("recommendation"),
        "markdown_path": frontier_summary.get("markdown_path"),
        "promoted_shadow_watch": _build_catalyst_theme_shadow_watch_rows(promoted_entries, limit=max(len(promoted_entries), 1)) if promoted_entries else [],
    }


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    resolved = Path(path).expanduser().resolve()
    resolved.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sync_text_artifact_alias(source_path: str | Path, alias_path: str | Path) -> str:
    resolved_source = Path(source_path).expanduser().resolve()
    resolved_alias = Path(alias_path).expanduser().resolve()
    resolved_alias.write_text(resolved_source.read_text(encoding="utf-8"), encoding="utf-8")
    return str(resolved_alias)


def _resolve_followup_trade_dates(
    trade_date: str | None,
    next_trade_date: str | None,
    brief_json_path: str | Path,
    card_json_path: str | Path,
) -> tuple[str | None, str | None]:
    normalized_trade_date = _normalize_trade_date(trade_date)
    normalized_next_trade_date = _normalize_trade_date(next_trade_date)
    if normalized_trade_date and normalized_next_trade_date:
        return normalized_trade_date, normalized_next_trade_date

    brief_payload = _load_json(brief_json_path)
    card_payload = _load_json(card_json_path)
    return (
        normalized_trade_date or _normalize_trade_date(brief_payload.get("trade_date") or card_payload.get("trade_date")),
        normalized_next_trade_date or _normalize_trade_date(brief_payload.get("next_trade_date") or card_payload.get("next_trade_date")),
    )


def _format_float(value: Any, digits: int = 4) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return "n/a"


def _as_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _round_or_none(value: Any, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(mean(values), 4)


def _score_bucket_label(score_target: Any, bucket_size: float = WATCH_CANDIDATE_HISTORICAL_SCORE_BUCKET_SIZE) -> str:
    if not isinstance(score_target, (int, float)):
        return "unknown"
    score_value = max(0.0, float(score_target))
    lower = round(int(score_value / bucket_size) * bucket_size, 2)
    upper = round(lower + bucket_size, 2)
    return f"{lower:.2f}-{upper:.2f}"


def _catalyst_bucket_label(metrics: dict[str, Any] | None) -> str:
    catalyst_freshness = _as_float((metrics or {}).get("catalyst_freshness"))
    if catalyst_freshness >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN:
        return "strong"
    if catalyst_freshness >= 0.45:
        return "medium"
    if catalyst_freshness > 0:
        return "weak"
    return "none"


def _normalize_trade_date(value: str | None) -> str | None:
    if not value:
        return None
    if "-" in value:
        return value
    if len(value) == 8:
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    return value


def _compact_trade_date(value: str | None) -> str | None:
    normalized = _normalize_trade_date(value)
    return normalized.replace("-", "") if normalized else None


def _fallback_next_weekday(trade_date: str | None) -> str | None:
    normalized = _normalize_trade_date(trade_date)
    if not normalized:
        return None
    cursor = datetime.strptime(normalized, "%Y-%m-%d") + timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor += timedelta(days=1)
    return cursor.strftime("%Y-%m-%d")


def infer_next_trade_date(trade_date: str | None, lookahead_days: int = 14) -> str | None:
    normalized = _normalize_trade_date(trade_date)
    if not normalized:
        return None

    pro = _get_pro()
    if pro is None:
        return _fallback_next_weekday(normalized)

    start_date = (datetime.strptime(normalized, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y%m%d")
    end_date = (datetime.strptime(normalized, "%Y-%m-%d") + timedelta(days=lookahead_days)).strftime("%Y%m%d")

    try:
        df = _cached_tushare_dataframe_call(
            pro,
            "trade_cal",
            exchange="",
            start_date=start_date,
            end_date=end_date,
            is_open=1,
            fields="cal_date,is_open",
        )
    except Exception:
        df = None

    if df is not None and not df.empty:
        candidate_dates = sorted(_normalize_trade_date(str(value)) for value in df["cal_date"].tolist())
        if candidate_dates:
            return candidate_dates[0]
    return _fallback_next_weekday(normalized)


def _resolve_snapshot_path(input_path: str | Path, trade_date: str | None) -> tuple[Path, Path]:
    resolved_input = Path(input_path).expanduser().resolve()

    if resolved_input.is_file():
        if resolved_input.name != "selection_snapshot.json":
            raise ValueError("input_path must be a report directory or a selection_snapshot.json file")
        return resolved_input, resolved_input.parents[2]

    if not resolved_input.is_dir():
        raise FileNotFoundError(f"Input path does not exist: {resolved_input}")

    artifacts_dir = resolved_input / "selection_artifacts"
    if not artifacts_dir.exists():
        raise FileNotFoundError(f"selection_artifacts directory not found under: {resolved_input}")

    normalized_trade_date = _normalize_trade_date(trade_date)
    if normalized_trade_date:
        candidate = artifacts_dir / normalized_trade_date / "selection_snapshot.json"
        if not candidate.exists():
            raise FileNotFoundError(f"selection_snapshot.json not found for trade_date={normalized_trade_date}: {candidate}")
        return candidate, resolved_input

    trade_date_dirs = sorted(path for path in artifacts_dir.iterdir() if path.is_dir())
    if not trade_date_dirs:
        raise FileNotFoundError(f"No trade_date directories found under: {artifacts_dir}")
    latest_trade_dir = trade_date_dirs[-1]
    candidate = latest_trade_dir / "selection_snapshot.json"
    if not candidate.exists():
        raise FileNotFoundError(f"selection_snapshot.json not found under latest trade_date directory: {candidate}")
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


def _extract_next_day_outcome(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], pd.DataFrame]) -> dict[str, Any]:
    cache_key = (ticker, trade_date)
    frame = price_cache.get(cache_key)
    if frame is None:
        end_date = (pd.Timestamp(trade_date) + pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        try:
            frame = _normalize_price_frame(get_price_data(ticker, trade_date, end_date))
        except Exception:
            try:
                frame = _normalize_price_frame(prices_to_df(get_prices_robust(ticker, trade_date, end_date, use_mock_on_fail=False)))
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
    return path.is_dir() and path.name.startswith("paper_trading") and (path / "session_summary.json").exists() and (path / "selection_artifacts").exists()


def _iter_selection_snapshot_paths(report_dir: Path) -> list[Path]:
    selection_artifacts_dir = report_dir / "selection_artifacts"
    if not selection_artifacts_dir.exists():
        return []
    return [
        snapshot_path
        for snapshot_path in sorted(selection_artifacts_dir.glob("*/selection_snapshot.json"))
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
        if candidate.resolve() == report_dir.resolve() or not _looks_like_paper_trading_report_dir(candidate):
            continue
        snapshot_paths = _iter_selection_snapshot_paths(candidate)
        latest_trade_date = _normalize_trade_date(snapshot_paths[-1].parent.name) if snapshot_paths else None
        if trade_date and latest_trade_date and latest_trade_date >= trade_date:
            continue
        candidates.append((latest_trade_date or "", candidate.stat().st_mtime_ns, candidate.name, candidate))

    candidates.sort(reverse=True)
    return [candidate for _, _, _, candidate in candidates[:max_reports]]


def _extract_short_trade_entry(selection_entry: dict[str, Any]) -> dict[str, Any] | None:
    short_trade_entry = selection_entry.get("short_trade") or {}
    decision = short_trade_entry.get("decision")
    if decision not in {"selected", "near_miss"}:
        return None

    metrics_payload = short_trade_entry.get("metrics_payload") or {}
    explainability_payload = short_trade_entry.get("explainability_payload") or {}

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
        "candidate_source": explainability_payload.get("candidate_source") or selection_entry.get("candidate_source"),
        "gate_status": dict(short_trade_entry.get("gate_status") or {}),
        "metrics": {
            "breakout_freshness": metrics_payload.get("breakout_freshness"),
            "trend_acceleration": metrics_payload.get("trend_acceleration"),
            "volume_expansion_quality": metrics_payload.get("volume_expansion_quality"),
            "close_strength": metrics_payload.get("close_strength"),
            "catalyst_freshness": metrics_payload.get("catalyst_freshness"),
        },
    }


def _build_opportunity_pool_promotion_trigger(metrics_payload: dict[str, Any]) -> str:
    breakout_freshness = _as_float(metrics_payload.get("breakout_freshness"))
    trend_acceleration = _as_float(metrics_payload.get("trend_acceleration"))
    close_strength = _as_float(metrics_payload.get("close_strength"))
    catalyst_freshness = _as_float(metrics_payload.get("catalyst_freshness"))

    if breakout_freshness >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN and trend_acceleration >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN:
        return "若盘中 breakout 与 trend 强度继续抬升，可升级为观察票。"
    if catalyst_freshness >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN:
        return "若催化延续并出现量价确认，可升级为观察票。"
    if close_strength >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN:
        return "若开盘后 close-strength 类信号延续，可升级为观察票。"
    return "只有盘中新增强度确认时，才允许从机会池升级。"


def _apply_execution_quality_entry_mode(entry: dict[str, Any]) -> dict[str, Any]:
    historical_prior = dict(entry.get("historical_prior") or {})
    execution_quality_label = str(historical_prior.get("execution_quality_label") or "unknown")
    updated_entry = dict(entry)
    updated_entry["historical_prior"] = historical_prior

    top_reasons = [str(reason) for reason in list(updated_entry.get("top_reasons") or []) if str(reason or "").strip()]

    if execution_quality_label == "intraday_only":
        updated_entry["preferred_entry_mode"] = "intraday_confirmation_only"
        updated_entry["promotion_trigger"] = "历史更像盘中确认后的 intraday 机会，不把默认隔夜持有当成升级方向。"
        if "historical_intraday_only_execution" not in top_reasons:
            top_reasons.append("historical_intraday_only_execution")
    elif execution_quality_label == "gap_chase_risk":
        updated_entry["preferred_entry_mode"] = "avoid_open_chase_confirmation"
        updated_entry["promotion_trigger"] = "若盘中回踩后重新走强可再确认，避免把开盘追价当成默认动作。"
        if "historical_gap_chase_risk" not in top_reasons:
            top_reasons.append("historical_gap_chase_risk")
    elif execution_quality_label == "close_continuation":
        updated_entry["preferred_entry_mode"] = "confirm_then_hold_breakout"
        updated_entry["promotion_trigger"] = "若盘中 continuation 确认后量价延续良好，可升级为 confirm-then-hold，而不是默认快进快出。"
        if "historical_close_continuation" not in top_reasons:
            top_reasons.append("historical_close_continuation")
    elif execution_quality_label == "zero_follow_through":
        updated_entry["preferred_entry_mode"] = "strong_reconfirmation_only"
        updated_entry["promotion_trigger"] = "历史同层兑现极弱，只有出现新的强确认时才允许重新升级。"
        if "historical_zero_follow_through" not in top_reasons:
            top_reasons.append("historical_zero_follow_through")

    updated_entry["top_reasons"] = top_reasons
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
        execution_quality_label = str(historical_prior.get("execution_quality_label") or "unknown")
        evaluable_count = int(historical_prior.get("evaluable_count") or 0)
        next_close_positive_rate = _as_float(historical_prior.get("next_close_positive_rate"))

        if execution_quality_label == "zero_follow_through" and evaluable_count >= WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT:
            demoted_entry = dict(updated_entry)
            demoted_entry["demoted_from_decision"] = "selected"
            demoted_entry["reporting_bucket"] = "selected_execution_demoted"
            demoted_entry["reporting_decision"] = "opportunity_pool"
            demoted_entry["promotion_trigger"] = "历史兑现几乎为 0，先降为机会池；只有盘中新强确认时再考虑回到观察层。"
            top_reasons = [str(reason) for reason in list(demoted_entry.get("top_reasons") or []) if str(reason or "").strip()]
            if "historical_zero_follow_through_selected_demoted" not in top_reasons:
                top_reasons.append("historical_zero_follow_through_selected_demoted")
            demoted_entry["top_reasons"] = top_reasons
            updated_opportunity_pool_entries.append(demoted_entry)
            continue

        if execution_quality_label == "intraday_only" and evaluable_count >= WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT and next_close_positive_rate <= 0.0:
            demoted_entry = dict(updated_entry)
            demoted_entry["demoted_from_decision"] = "selected"
            demoted_entry["reporting_bucket"] = "selected_execution_demoted"
            demoted_entry["reporting_decision"] = "near_miss"
            demoted_entry["promotion_trigger"] = "历史更偏向盘中兑现而非收盘延续，先降为确认型观察票，不把隔夜持有当默认动作。"
            top_reasons = [str(reason) for reason in list(demoted_entry.get("top_reasons") or []) if str(reason or "").strip()]
            if "historical_intraday_only_selected_demoted" not in top_reasons:
                top_reasons.append("historical_intraday_only_selected_demoted")
            demoted_entry["top_reasons"] = top_reasons
            updated_near_miss_entries.append(demoted_entry)
            continue

        retained_selected_entries.append(updated_entry)

    return retained_selected_entries, updated_near_miss_entries, updated_opportunity_pool_entries


def _extract_short_trade_opportunity_entry(selection_entry: dict[str, Any]) -> dict[str, Any] | None:
    if (selection_entry.get("research") or {}).get("decision") == "selected":
        return None

    short_trade_entry = selection_entry.get("short_trade") or {}
    if short_trade_entry.get("decision") != "rejected":
        return None

    gate_status = dict(short_trade_entry.get("gate_status") or {})
    if gate_status.get("data") != "pass" or gate_status.get("structural") != "pass":
        return None

    metrics_payload = dict(short_trade_entry.get("metrics_payload") or {})
    score_target = _as_float(short_trade_entry.get("score_target"))
    if score_target < OPPORTUNITY_POOL_MIN_SCORE_TARGET:
        return None

    breakout_freshness = _as_float(metrics_payload.get("breakout_freshness"))
    trend_acceleration = _as_float(metrics_payload.get("trend_acceleration"))
    volume_expansion_quality = _as_float(metrics_payload.get("volume_expansion_quality"))
    close_strength = _as_float(metrics_payload.get("close_strength"))
    catalyst_freshness = _as_float(metrics_payload.get("catalyst_freshness"))
    positive_tags = list(short_trade_entry.get("positive_tags") or [])
    strong_signal_count = sum(
        metric >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN
        for metric in (breakout_freshness, trend_acceleration, volume_expansion_quality, close_strength, catalyst_freshness)
    )
    if strong_signal_count <= 0 and not positive_tags:
        return None

    thresholds = dict(metrics_payload.get("thresholds") or {})
    near_miss_threshold = _as_float(thresholds.get("near_miss_threshold"))
    score_gap_to_near_miss = round(max(0.0, near_miss_threshold - score_target), 4) if near_miss_threshold > 0 else None

    return {
        "ticker": selection_entry.get("ticker"),
        "decision": short_trade_entry.get("decision"),
        "reporting_decision": "opportunity_pool",
        "score_target": short_trade_entry.get("score_target"),
        "confidence": short_trade_entry.get("confidence"),
        "preferred_entry_mode": short_trade_entry.get("preferred_entry_mode"),
        "candidate_source": (short_trade_entry.get("explainability_payload") or {}).get("candidate_source") or selection_entry.get("candidate_source"),
        "positive_tags": positive_tags,
        "top_reasons": list(short_trade_entry.get("top_reasons") or []),
        "rejection_reasons": list(short_trade_entry.get("rejection_reasons") or []),
        "gate_status": gate_status,
        "score_gap_to_near_miss": score_gap_to_near_miss,
        "promotion_trigger": _build_opportunity_pool_promotion_trigger(metrics_payload),
        "metrics": {
            "breakout_freshness": metrics_payload.get("breakout_freshness"),
            "trend_acceleration": metrics_payload.get("trend_acceleration"),
            "volume_expansion_quality": metrics_payload.get("volume_expansion_quality"),
            "close_strength": metrics_payload.get("close_strength"),
            "catalyst_freshness": metrics_payload.get("catalyst_freshness"),
        },
    }


def _extract_research_upside_radar_entry(selection_entry: dict[str, Any]) -> dict[str, Any] | None:
    research_entry = selection_entry.get("research") or {}
    short_trade_entry = selection_entry.get("short_trade") or {}
    if research_entry.get("decision") != "selected":
        return None
    if short_trade_entry.get("decision") != "rejected":
        return None

    gate_status = dict(short_trade_entry.get("gate_status") or {})
    if gate_status.get("data") != "pass" or gate_status.get("structural") != "pass":
        return None

    metrics_payload = dict(short_trade_entry.get("metrics_payload") or {})
    score_target = _as_float(short_trade_entry.get("score_target"))
    if score_target < OPPORTUNITY_POOL_MIN_SCORE_TARGET:
        return None

    breakout_freshness = _as_float(metrics_payload.get("breakout_freshness"))
    trend_acceleration = _as_float(metrics_payload.get("trend_acceleration"))
    volume_expansion_quality = _as_float(metrics_payload.get("volume_expansion_quality"))
    close_strength = _as_float(metrics_payload.get("close_strength"))
    catalyst_freshness = _as_float(metrics_payload.get("catalyst_freshness"))
    positive_tags = list(short_trade_entry.get("positive_tags") or [])
    strong_signal_count = sum(
        metric >= OPPORTUNITY_POOL_STRONG_SIGNAL_MIN
        for metric in (breakout_freshness, trend_acceleration, volume_expansion_quality, close_strength, catalyst_freshness)
    )
    if strong_signal_count <= 0 and not positive_tags:
        return None

    return {
        "ticker": selection_entry.get("ticker"),
        "research_decision": research_entry.get("decision"),
        "research_score_target": research_entry.get("score_target"),
        "decision": short_trade_entry.get("decision"),
        "score_target": short_trade_entry.get("score_target"),
        "confidence": short_trade_entry.get("confidence"),
        "preferred_entry_mode": short_trade_entry.get("preferred_entry_mode"),
        "candidate_source": (short_trade_entry.get("explainability_payload") or {}).get("candidate_source") or selection_entry.get("candidate_source"),
        "positive_tags": positive_tags,
        "top_reasons": list(short_trade_entry.get("top_reasons") or []),
        "rejection_reasons": list(short_trade_entry.get("rejection_reasons") or []),
        "gate_status": gate_status,
        "delta_summary": list(selection_entry.get("delta_summary") or []),
        "radar_note": "research 已选中但 BTST 未放行，只做漏票雷达，不纳入明日 short-trade 交易名单。",
        "metrics": {
            "breakout_freshness": metrics_payload.get("breakout_freshness"),
            "trend_acceleration": metrics_payload.get("trend_acceleration"),
            "volume_expansion_quality": metrics_payload.get("volume_expansion_quality"),
            "close_strength": metrics_payload.get("close_strength"),
            "catalyst_freshness": metrics_payload.get("catalyst_freshness"),
        },
    }


def _extract_catalyst_theme_entry(candidate: dict[str, Any]) -> dict[str, Any] | None:
    if not candidate:
        return None

    metrics = dict(candidate.get("metrics") or {})
    candidate_score = _as_float(candidate.get("score_target") if candidate.get("score_target") is not None else candidate.get("candidate_score"))
    if candidate_score <= 0:
        return None

    return {
        "ticker": candidate.get("ticker"),
        "decision": candidate.get("decision") or "catalyst_theme",
        "score_target": candidate_score,
        "confidence": candidate.get("confidence"),
        "preferred_entry_mode": candidate.get("preferred_entry_mode") or "theme_research_followup",
        "candidate_source": candidate.get("candidate_source") or "catalyst_theme",
        "positive_tags": list(candidate.get("positive_tags") or []),
        "top_reasons": list(candidate.get("top_reasons") or []),
        "blockers": list(candidate.get("blockers") or []),
        "gate_status": dict(candidate.get("gate_status") or {}),
        "promotion_trigger": candidate.get("promotion_trigger") or "只做题材催化跟踪，不进入主池或 BTST 执行名单。",
        "metrics": {
            "breakout_freshness": metrics.get("breakout_freshness"),
            "trend_acceleration": metrics.get("trend_acceleration"),
            "close_strength": metrics.get("close_strength"),
            "sector_resonance": metrics.get("sector_resonance"),
            "catalyst_freshness": metrics.get("catalyst_freshness"),
        },
    }


def _extract_catalyst_theme_shadow_entry(candidate: dict[str, Any]) -> dict[str, Any] | None:
    if not candidate:
        return None

    metrics = dict(candidate.get("metrics") or {})
    candidate_score = _as_float(candidate.get("score_target") if candidate.get("score_target") is not None else candidate.get("candidate_score"))
    if candidate_score <= 0:
        return None

    return {
        "ticker": candidate.get("ticker"),
        "decision": candidate.get("decision") or "catalyst_theme_shadow",
        "score_target": candidate_score,
        "confidence": candidate.get("confidence"),
        "preferred_entry_mode": candidate.get("preferred_entry_mode") or "theme_research_followup",
        "candidate_source": candidate.get("candidate_source") or "catalyst_theme_shadow",
        "positive_tags": list(candidate.get("positive_tags") or []),
        "top_reasons": list(candidate.get("top_reasons") or []),
        "blockers": list(candidate.get("blockers") or []),
        "gate_status": dict(candidate.get("gate_status") or {}),
        "promotion_trigger": candidate.get("promotion_trigger") or "继续跟踪催化与结构缺口，不进入正式题材研究池或 BTST 执行名单。",
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


def _build_catalyst_theme_shadow_watch_rows(entries: list[dict[str, Any]], *, limit: int = CATALYST_THEME_SHADOW_WATCH_MAX_ENTRIES) -> list[dict[str, Any]]:
    ranked_entries = sorted(
        [dict(entry) for entry in entries if entry and entry.get("ticker")],
        key=lambda entry: (
            entry.get("total_shortfall") if entry.get("total_shortfall") is not None else 999.0,
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


def _decorate_watch_candidate_history_entry(entry: dict[str, Any], family: str) -> dict[str, Any]:
    metrics = dict(entry.get("metrics") or {})
    return {
        **entry,
        "watch_candidate_family": family,
        "score_bucket": _score_bucket_label(entry.get("score_target")),
        "catalyst_bucket": _catalyst_bucket_label(metrics),
    }


def _collect_historical_opportunity_rows(report_dir: Path, trade_date: str | None) -> dict[str, Any]:
    historical_report_dirs = [report_dir, *_discover_recent_historical_report_dirs(report_dir, trade_date)]
    rows: list[dict[str, Any]] = []
    contributing_reports: set[str] = set()

    for historical_report_dir in historical_report_dirs:
        for snapshot_path in _iter_selection_snapshot_paths(historical_report_dir):
            snapshot = _load_json(snapshot_path)
            snapshot_trade_date = _normalize_trade_date(snapshot.get("trade_date") or snapshot_path.parent.name)
            if trade_date and snapshot_trade_date and snapshot_trade_date >= trade_date:
                continue
            selection_targets = snapshot.get("selection_targets") or {}
            for selection_entry in selection_targets.values():
                opportunity_entry = _extract_short_trade_opportunity_entry(dict(selection_entry))
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

    rows.sort(key=lambda row: (row.get("trade_date") or "", row.get("ticker") or ""), reverse=True)
    return {
        "rows": rows,
        "historical_report_dirs": historical_report_dirs,
        "contributing_report_count": len(contributing_reports),
    }


def _collect_historical_watch_candidate_rows(report_dir: Path, trade_date: str | None) -> dict[str, Any]:
    historical_report_dirs = [report_dir, *_discover_recent_historical_report_dirs(report_dir, trade_date)]
    rows: list[dict[str, Any]] = []
    contributing_reports: set[str] = set()
    family_counts = {"selected": 0, "near_miss": 0, "opportunity_pool": 0, "research_upside_radar": 0, "catalyst_theme": 0}

    for historical_report_dir in historical_report_dirs:
        for snapshot_path in _iter_selection_snapshot_paths(historical_report_dir):
            snapshot = _load_json(snapshot_path)
            snapshot_trade_date = _normalize_trade_date(snapshot.get("trade_date") or snapshot_path.parent.name)
            if trade_date and snapshot_trade_date and snapshot_trade_date >= trade_date:
                continue
            selection_targets = snapshot.get("selection_targets") or {}
            for selection_entry in selection_targets.values():
                short_trade_entry = _extract_short_trade_entry(dict(selection_entry))
                if short_trade_entry is not None:
                    family = str(short_trade_entry.get("decision") or "")
                    rows.append(
                        {
                            **_decorate_watch_candidate_history_entry(short_trade_entry, family),
                            "trade_date": snapshot_trade_date,
                            "report_dir": str(historical_report_dir),
                            "snapshot_path": str(snapshot_path),
                        }
                    )
                    family_counts[family] = int(family_counts.get(family) or 0) + 1
                    contributing_reports.add(str(historical_report_dir))

                opportunity_entry = _extract_short_trade_opportunity_entry(dict(selection_entry))
                if opportunity_entry is not None:
                    rows.append(
                        {
                            **_decorate_watch_candidate_history_entry(opportunity_entry, "opportunity_pool"),
                            "trade_date": snapshot_trade_date,
                            "report_dir": str(historical_report_dir),
                            "snapshot_path": str(snapshot_path),
                        }
                    )
                    family_counts["opportunity_pool"] += 1
                    contributing_reports.add(str(historical_report_dir))

                research_radar_entry = _extract_research_upside_radar_entry(dict(selection_entry))
                if research_radar_entry is not None:
                    rows.append(
                        {
                            **_decorate_watch_candidate_history_entry(research_radar_entry, "research_upside_radar"),
                            "trade_date": snapshot_trade_date,
                            "report_dir": str(historical_report_dir),
                            "snapshot_path": str(snapshot_path),
                        }
                    )
                    family_counts["research_upside_radar"] += 1
                    contributing_reports.add(str(historical_report_dir))

            for catalyst_entry in snapshot.get("catalyst_theme_candidates") or []:
                normalized_entry = _extract_catalyst_theme_entry(dict(catalyst_entry))
                if normalized_entry is None:
                    continue
                rows.append(
                    {
                        **_decorate_watch_candidate_history_entry(normalized_entry, "catalyst_theme"),
                        "trade_date": snapshot_trade_date,
                        "report_dir": str(historical_report_dir),
                        "snapshot_path": str(snapshot_path),
                    }
                )
                family_counts["catalyst_theme"] += 1
                contributing_reports.add(str(historical_report_dir))

    rows.sort(key=lambda row: (row.get("trade_date") or "", row.get("ticker") or ""), reverse=True)
    return {
        "rows": rows,
        "historical_report_dirs": historical_report_dirs,
        "contributing_report_count": len(contributing_reports),
        "family_counts": family_counts,
    }


def _classify_historical_prior(hit_rate: float | None, close_positive_rate: float | None, evaluable_count: int) -> tuple[str, str]:
    if evaluable_count <= 0:
        return "unknown", "unscored"
    if evaluable_count < 3:
        if (hit_rate or 0.0) >= 0.5 or (close_positive_rate or 0.0) >= 0.5:
            return "mixed", "medium"
        return "weak", "low"
    if (hit_rate or 0.0) >= 0.6 and (close_positive_rate or 0.0) >= 0.5:
        return "positive", "high"
    if (hit_rate or 0.0) >= 0.4 or (close_positive_rate or 0.0) >= 0.4:
        return "mixed", "medium"
    return "weak", "low"


def _classify_execution_quality_prior(
    next_open_return_mean: float | None,
    next_open_to_close_return_mean: float | None,
    next_high_return_mean: float | None,
    next_close_return_mean: float | None,
    next_high_hit_rate: float | None,
    next_close_positive_rate: float | None,
    evaluable_count: int,
) -> dict[str, str]:
    if evaluable_count <= 0:
        return {
            "execution_quality_label": "unknown",
            "execution_priority": "unscored",
            "entry_timing_bias": "unknown",
            "execution_note": "历史执行样本不足，仍需以盘中确认为准。",
        }

    open_mean = next_open_return_mean or 0.0
    open_to_close_mean = next_open_to_close_return_mean or 0.0
    high_mean = next_high_return_mean or 0.0
    close_mean = next_close_return_mean or 0.0
    high_hit_rate = next_high_hit_rate or 0.0
    close_positive_hit_rate = next_close_positive_rate or 0.0

    if evaluable_count >= WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT and high_hit_rate <= 0.0 and close_positive_hit_rate <= 0.0:
        return {
            "execution_quality_label": "zero_follow_through",
            "execution_priority": "low",
            "entry_timing_bias": "avoid_without_new_strength",
            "execution_note": "历史同层样本几乎不给盘中空间，也没有收盘正收益，除非出现新的强确认，否则不应进入高优先级执行面。",
        }

    if open_mean >= 0.02 and open_to_close_mean < 0:
        return {
            "execution_quality_label": "gap_chase_risk",
            "execution_priority": "low",
            "entry_timing_bias": "avoid_open_chase",
            "execution_note": "历史上更像高开后回落，避免开盘直接追价。",
        }
    if close_mean >= 0.02 and open_to_close_mean >= 0:
        return {
            "execution_quality_label": "close_continuation",
            "execution_priority": "high",
            "entry_timing_bias": "confirm_then_hold",
            "execution_note": "历史上更偏向次日收盘延续，确认后可保留 follow-through 预期。",
        }
    if high_mean >= 0.03 and close_mean <= 0:
        return {
            "execution_quality_label": "intraday_only",
            "execution_priority": "medium",
            "entry_timing_bias": "confirm_then_reduce",
            "execution_note": "历史上更多是盘中给空间、收盘回落，更适合作为 intraday 机会而不是隔夜延续。",
        }
    return {
        "execution_quality_label": "balanced_confirmation",
        "execution_priority": "medium",
        "entry_timing_bias": "confirm_then_review",
        "execution_note": "历史表现相对均衡，仍应坚持盘中确认后再决定是否持有。",
    }


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
    resolved_scope_label = scope_label or ("同票" if applied_scope == "same_ticker" else "同源")
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
        demoted_entry["promotion_trigger"] = "历史同层兑现极弱，先降为机会池；只有盘中新强度确认时再考虑回到观察层。"
        top_reasons = [str(reason) for reason in list(demoted_entry.get("top_reasons") or []) if str(reason or "").strip()]
        if "historical_zero_follow_through_demoted" not in top_reasons:
            top_reasons.append("historical_zero_follow_through_demoted")
        demoted_entry["top_reasons"] = top_reasons
        updated_opportunity_pool_entries.append(demoted_entry)
    return retained_entries, updated_opportunity_pool_entries


def _entry_mode_action_guidance(preferred_entry_mode: str | None, *, default_action: str) -> tuple[str, str]:
    if preferred_entry_mode == "intraday_confirmation_only":
        return "confirm_then_reduce", "只做盘中确认后的 intraday 机会，不把默认隔夜持有当成执行目标。"
    if preferred_entry_mode == "avoid_open_chase_confirmation":
        return "avoid_open_chase", "避免开盘直接追价，等待回踩或二次确认后再决定是否参与。"
    if preferred_entry_mode == "confirm_then_hold_breakout":
        return "confirm_then_hold", "先等盘中 continuation 确认，再决定是否入场；若确认质量足够，允许把 follow-through 持有到收盘而不是机械快进快出。"
    if preferred_entry_mode == "strong_reconfirmation_only":
        return "reconfirm_only", "历史兑现极弱，只有出现新的强确认时才允许重新评估。"
    return "standard_confirmation", default_action


def _opportunity_pool_execution_sort_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    historical_prior = dict(entry.get("historical_prior") or {})
    execution_quality_label = str(historical_prior.get("execution_quality_label") or "unknown")
    execution_quality_rank = {
        "close_continuation": 0,
        "balanced_confirmation": 1,
        "gap_chase_risk": 2,
        "intraday_only": 3,
        "unknown": 4,
        "zero_follow_through": 5,
    }.get(execution_quality_label, 4)
    next_close_positive_rate = _as_float(historical_prior.get("next_close_positive_rate"))
    next_high_hit_rate = _as_float(historical_prior.get("next_high_hit_rate_at_threshold"))
    return (
        execution_quality_rank,
        -next_close_positive_rate,
        -next_high_hit_rate,
        entry.get("score_gap_to_near_miss") if entry.get("score_gap_to_near_miss") is not None else 999.0,
        -(entry.get("score_target") or 0.0),
        -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
        entry.get("ticker") or "",
    )


def _summarize_historical_opportunity_rows(
    rows: list[dict[str, Any]],
    price_cache: dict[tuple[str, str], pd.DataFrame],
) -> dict[str, Any]:
    evaluated_rows: list[dict[str, Any]] = []
    next_open_values: list[float] = []
    next_high_values: list[float] = []
    next_close_values: list[float] = []
    next_open_to_close_values: list[float] = []
    hit_count = 0
    positive_close_count = 0

    for row in rows:
        trade_date = str(row.get("trade_date") or "")
        ticker = str(row.get("ticker") or "")
        if not trade_date or not ticker:
            continue
        outcome = _extract_next_day_outcome(ticker, trade_date, price_cache)
        if outcome.get("data_status") != "ok":
            continue

        next_open_return = _round_or_none(outcome.get("next_open_return"))
        next_high_return = _round_or_none(outcome.get("next_high_return"))
        next_close_return = _round_or_none(outcome.get("next_close_return"))
        next_open_to_close_return = _round_or_none(outcome.get("next_open_to_close_return"))
        if next_open_return is not None:
            next_open_values.append(next_open_return)
        if next_high_return is not None:
            next_high_values.append(next_high_return)
            if next_high_return >= OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD:
                hit_count += 1
        if next_close_return is not None:
            next_close_values.append(next_close_return)
            if next_close_return > 0:
                positive_close_count += 1
        if next_open_to_close_return is not None:
            next_open_to_close_values.append(next_open_to_close_return)

        evaluated_rows.append(
            {
                "trade_date": trade_date,
                "ticker": ticker,
                "candidate_source": row.get("candidate_source"),
                "score_target": _round_or_none(row.get("score_target")),
                "next_open_return": next_open_return,
                "next_high_return": next_high_return,
                "next_close_return": next_close_return,
                "next_open_to_close_return": next_open_to_close_return,
            }
        )

    evaluable_count = len(evaluated_rows)
    next_high_hit_rate = round(hit_count / evaluable_count, 4) if evaluable_count else None
    next_close_positive_rate = round(positive_close_count / evaluable_count, 4) if evaluable_count else None

    return {
        "sample_count": len(rows),
        "evaluable_count": evaluable_count,
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
    same_ticker_rows = [row for row in historical_rows if row.get("ticker") == entry.get("ticker")]
    same_source_rows = [row for row in historical_rows if row.get("candidate_source") == entry.get("candidate_source")]

    applied_scope = "none"
    applied_rows: list[dict[str, Any]] = []
    if len(same_ticker_rows) >= OPPORTUNITY_POOL_HISTORICAL_SAME_TICKER_MIN_SAMPLES:
        applied_scope = "same_ticker"
        applied_rows = same_ticker_rows
    elif same_source_rows:
        applied_scope = "candidate_source"
        applied_rows = same_source_rows
    elif same_ticker_rows:
        applied_scope = "same_ticker"
        applied_rows = same_ticker_rows

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
    same_ticker_rows = [row for row in historical_rows if row.get("ticker") == decorated_entry.get("ticker")]
    same_family_rows = [row for row in historical_rows if row.get("watch_candidate_family") == family]
    same_source_rows = [row for row in historical_rows if row.get("candidate_source") == decorated_entry.get("candidate_source")]
    same_family_source_rows = [
        row
        for row in same_family_rows
        if row.get("candidate_source") == decorated_entry.get("candidate_source")
    ]
    same_family_source_score_catalyst_rows = [
        row
        for row in same_family_source_rows
        if row.get("score_bucket") == decorated_entry.get("score_bucket") and row.get("catalyst_bucket") == decorated_entry.get("catalyst_bucket")
    ]
    same_source_score_rows = [
        row
        for row in same_source_rows
        if row.get("score_bucket") == decorated_entry.get("score_bucket")
    ]

    scope_candidates = [
        ("same_ticker", "同票", same_ticker_rows if len(same_ticker_rows) >= OPPORTUNITY_POOL_HISTORICAL_SAME_TICKER_MIN_SAMPLES else []),
        ("family_source_score_catalyst", "同层同源同分桶", same_family_source_score_catalyst_rows),
        ("family_source", "同层同源", same_family_source_rows),
        ("source_score", "同源同分桶", same_source_score_rows),
        ("candidate_source", "同源", same_source_rows),
        ("same_ticker", "同票", same_ticker_rows),
    ]

    applied_scope = "none"
    applied_rows: list[dict[str, Any]] = []
    scope_label: str | None = None
    for scope_name, label, scope_rows in scope_candidates:
        if scope_rows:
            applied_scope = scope_name
            applied_rows = scope_rows
            scope_label = label
            break

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
    return {
        "watch_candidate_family": family,
        "score_bucket": decorated_entry.get("score_bucket"),
        "catalyst_bucket": decorated_entry.get("catalyst_bucket"),
        "same_ticker_sample_count": len(same_ticker_rows),
        "same_family_sample_count": len(same_family_rows),
        "same_candidate_source_sample_count": len(same_source_rows),
        "same_family_source_sample_count": len(same_family_source_rows),
        "same_family_source_score_catalyst_sample_count": len(same_family_source_score_catalyst_rows),
        "same_source_score_sample_count": len(same_source_score_rows),
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


def _extract_excluded_research_entry(selection_entry: dict[str, Any]) -> dict[str, Any] | None:
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


def _summary_value(summary: dict[str, Any], key: str, fallback: int) -> int:
    value = summary.get(key)
    return fallback if value is None else value


def _execution_priority_rank(priority: str | None) -> int:
    return {
        "high": 0,
        "medium": 1,
        "low": 2,
        "unscored": 3,
    }.get(str(priority or "unscored"), 3)


def analyze_btst_next_day_trade_brief(input_path: str | Path, trade_date: str | None = None, next_trade_date: str | None = None) -> dict[str, Any]:
    snapshot_path, report_dir = _resolve_snapshot_path(input_path, trade_date)
    snapshot = _load_json(snapshot_path)
    replay_input = _load_selection_replay_input(snapshot_path)

    session_summary_path = report_dir / "session_summary.json"
    session_summary = _load_json(session_summary_path) if session_summary_path.exists() else {}
    actual_trade_date = _normalize_trade_date(snapshot.get("trade_date") or trade_date)

    selection_targets = snapshot.get("selection_targets") or {}
    supplemental_short_trade_entry_by_ticker = {
        str(entry.get("ticker") or ""): dict(entry)
        for entry in list(replay_input.get("supplemental_short_trade_entries") or [])
        if entry.get("ticker")
    }
    upstream_shadow_observation_entries = [
        dict(entry)
        for entry in list(replay_input.get("upstream_shadow_observation_entries") or [])
        if entry.get("ticker")
    ]
    short_trade_entries = [
        candidate
        for candidate in (_extract_short_trade_entry(entry) for entry in selection_targets.values())
        if candidate is not None
    ]
    short_trade_entries.sort(key=lambda entry: (0 if entry["decision"] == "selected" else 1, -(entry.get("score_target") or 0.0), entry.get("ticker") or ""))

    selected_entries = [entry for entry in short_trade_entries if entry["decision"] == "selected"]
    near_miss_entries = [entry for entry in short_trade_entries if entry["decision"] == "near_miss"]

    opportunity_pool_entries = [
        candidate
        for candidate in (_extract_short_trade_opportunity_entry(entry) for entry in selection_targets.values())
        if candidate is not None
    ]
    opportunity_pool_entries.sort(
        key=lambda entry: (
            entry.get("score_gap_to_near_miss") if entry.get("score_gap_to_near_miss") is not None else 999.0,
            -(entry.get("score_target") or 0.0),
            -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
            -_as_float((entry.get("metrics") or {}).get("breakout_freshness")),
            entry.get("ticker") or "",
        )
    )
    opportunity_pool_entries = opportunity_pool_entries[:OPPORTUNITY_POOL_MAX_ENTRIES]

    research_upside_radar_entries = [
        candidate
        for candidate in (_extract_research_upside_radar_entry(entry) for entry in selection_targets.values())
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
    research_upside_radar_entries = research_upside_radar_entries[:RESEARCH_UPSIDE_RADAR_MAX_ENTRIES]

    catalyst_theme_entries = [
        candidate
        for candidate in (_extract_catalyst_theme_entry(entry) for entry in (snapshot.get("catalyst_theme_candidates") or []))
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
    catalyst_theme_entries = catalyst_theme_entries[:CATALYST_THEME_MAX_ENTRIES]

    catalyst_theme_shadow_entries = [
        candidate
        for candidate in (_extract_catalyst_theme_shadow_entry(entry) for entry in (snapshot.get("catalyst_theme_shadow_candidates") or []))
        if candidate is not None
    ]
    catalyst_theme_shadow_entries.sort(
        key=lambda entry: (
            -(entry.get("score_target") or 0.0),
            entry.get("total_shortfall") if entry.get("total_shortfall") is not None else 999.0,
            -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
            entry.get("ticker") or "",
        )
    )
    catalyst_theme_shadow_entries = catalyst_theme_shadow_entries[:CATALYST_THEME_SHADOW_MAX_ENTRIES]
    catalyst_theme_frontier_summary = _load_catalyst_theme_frontier_summary(report_dir)
    catalyst_theme_frontier_priority = _build_catalyst_theme_frontier_priority(catalyst_theme_frontier_summary, catalyst_theme_shadow_entries)
    upstream_shadow_entries_by_ticker = {
        str(candidate.get("ticker") or ""): candidate
        for candidate in (
            _extract_upstream_shadow_entry(entry, supplemental_short_trade_entry_by_ticker.get(str(entry.get("ticker") or "")))
            for entry in selection_targets.values()
        )
        if candidate is not None and candidate.get("ticker")
    }
    for candidate in (
        _extract_upstream_shadow_replay_only_entry(entry)
        for entry in upstream_shadow_observation_entries
    ):
        if candidate is None or not candidate.get("ticker"):
            continue
        upstream_shadow_entries_by_ticker.setdefault(str(candidate.get("ticker") or ""), candidate)
    upstream_shadow_entries = list(upstream_shadow_entries_by_ticker.values())
    upstream_shadow_entries.sort(
        key=lambda entry: (
            _shadow_decision_rank(entry.get("decision")),
            -(entry.get("score_target") or 0.0),
            entry.get("candidate_pool_rank") if entry.get("candidate_pool_rank") is not None else 999999,
            entry.get("ticker") or "",
        )
    )
    upstream_shadow_summary = _build_upstream_shadow_summary(upstream_shadow_entries)

    btst_candidate_historical_context = {
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
    if selected_entries or near_miss_entries or opportunity_pool_entries or research_upside_radar_entries or catalyst_theme_entries:
        historical_payload = _collect_historical_watch_candidate_rows(report_dir, actual_trade_date)
        price_cache: dict[tuple[str, str], pd.DataFrame] = {}
        for entry in selected_entries:
            entry["historical_prior"] = _build_watch_candidate_historical_prior(
                entry,
                historical_payload["rows"],
                price_cache,
                family="selected",
            )
        for entry in near_miss_entries:
            entry["historical_prior"] = _build_watch_candidate_historical_prior(
                entry,
                historical_payload["rows"],
                price_cache,
                family="near_miss",
            )
        for entry in opportunity_pool_entries:
            entry["historical_prior"] = _build_watch_candidate_historical_prior(
                entry,
                historical_payload["rows"],
                price_cache,
                family="opportunity_pool",
            )
        for entry in research_upside_radar_entries:
            entry["historical_prior"] = _build_watch_candidate_historical_prior(
                entry,
                historical_payload["rows"],
                price_cache,
                family="research_upside_radar",
            )
        for entry in catalyst_theme_entries:
            entry["historical_prior"] = _build_watch_candidate_historical_prior(
                entry,
                historical_payload["rows"],
                price_cache,
                family="catalyst_theme",
            )
        selected_entries = [_apply_execution_quality_entry_mode(entry) for entry in selected_entries]
        near_miss_entries = [_apply_execution_quality_entry_mode(entry) for entry in near_miss_entries]
        opportunity_pool_entries = [_apply_execution_quality_entry_mode(entry) for entry in opportunity_pool_entries]
        selected_entries, near_miss_entries, opportunity_pool_entries = _reclassify_selected_execution_quality_entries(
            selected_entries,
            near_miss_entries,
            opportunity_pool_entries,
        )
        near_miss_entries, opportunity_pool_entries = _demote_weak_near_miss_entries(
            near_miss_entries,
            opportunity_pool_entries,
        )
        selected_entries.sort(
            key=lambda entry: (
                _execution_priority_rank((entry.get("historical_prior") or {}).get("execution_priority")),
                _monitor_priority_rank((entry.get("historical_prior") or {}).get("monitor_priority")),
                -(entry.get("score_target") or 0.0),
                -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
                entry.get("ticker") or "",
            )
        )
        near_miss_entries.sort(
            key=lambda entry: (
                _execution_priority_rank((entry.get("historical_prior") or {}).get("execution_priority")),
                _monitor_priority_rank((entry.get("historical_prior") or {}).get("monitor_priority")),
                -(entry.get("score_target") or 0.0),
                -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
                entry.get("ticker") or "",
            )
        )
        opportunity_pool_entries.sort(
            key=_opportunity_pool_execution_sort_key,
        )
        research_upside_radar_entries.sort(
            key=lambda entry: (
                _execution_priority_rank((entry.get("historical_prior") or {}).get("execution_priority")),
                _monitor_priority_rank((entry.get("historical_prior") or {}).get("monitor_priority")),
                -(entry.get("research_score_target") or 0.0),
                -(entry.get("score_target") or 0.0),
                entry.get("ticker") or "",
            )
        )
        catalyst_theme_entries.sort(
            key=lambda entry: (
                _execution_priority_rank((entry.get("historical_prior") or {}).get("execution_priority")),
                _monitor_priority_rank((entry.get("historical_prior") or {}).get("monitor_priority")),
                -(entry.get("score_target") or 0.0),
                -_as_float((entry.get("metrics") or {}).get("catalyst_freshness")),
                entry.get("ticker") or "",
            )
        )
        btst_candidate_historical_context = {
            "lookback_report_limit": OPPORTUNITY_POOL_HISTORICAL_LOOKBACK_REPORTS,
            "historical_report_count": int(historical_payload.get("contributing_report_count") or 0),
            "historical_btst_candidate_count": len(historical_payload.get("rows") or []),
            "historical_watch_candidate_count": len(historical_payload.get("rows") or []),
            "historical_selected_candidate_count": int((historical_payload.get("family_counts") or {}).get("selected") or 0),
            "historical_near_miss_candidate_count": int((historical_payload.get("family_counts") or {}).get("near_miss") or 0),
            "historical_opportunity_candidate_count": len(historical_payload.get("rows") or []),
            "historical_research_upside_radar_count": int((historical_payload.get("family_counts") or {}).get("research_upside_radar") or 0),
            "historical_catalyst_theme_count": int((historical_payload.get("family_counts") or {}).get("catalyst_theme") or 0),
            "next_high_hit_threshold": OPPORTUNITY_POOL_HISTORICAL_NEXT_HIGH_HIT_THRESHOLD,
        }
        btst_candidate_historical_context["historical_opportunity_candidate_count"] = int((historical_payload.get("family_counts") or {}).get("opportunity_pool") or 0)

    excluded_research_entries = [
        candidate
        for candidate in (_extract_excluded_research_entry(entry) for entry in selection_targets.values())
        if candidate is not None
    ]
    excluded_research_entries.sort(key=lambda entry: (-(entry.get("research_score_target") or 0.0), entry.get("ticker") or ""))

    dual_target_summary = snapshot.get("dual_target_summary") or {}
    primary_entry = selected_entries[0] if selected_entries else None
    short_trade_decisions = [
        (entry.get("short_trade") or {}).get("decision")
        for entry in selection_targets.values()
        if entry.get("short_trade")
    ]
    blocked_count = sum(1 for decision in short_trade_decisions if decision == "blocked")
    rejected_count = sum(1 for decision in short_trade_decisions if decision == "rejected")
    research_selected_count = sum(
        1 for entry in selection_targets.values() if (entry.get("research") or {}).get("decision") == "selected"
    )

    recommendation_lines: list[str] = []
    if primary_entry:
        recommendation_lines.append(
            f"主入场票为 {primary_entry['ticker']}，应按 {primary_entry['preferred_entry_mode']} 执行，而不是把它视为无条件开盘追价。"
        )
        primary_historical = primary_entry.get("historical_prior") or {}
        if primary_historical.get("summary"):
            recommendation_lines.append("主票历史先验参考: " + str(primary_historical.get("summary")))
        if primary_historical.get("execution_note"):
            recommendation_lines.append("主票执行先验: " + str(primary_historical.get("execution_note")))
    else:
        recommendation_lines.append("本次 short-trade 没有正式 selected 样本，不建议把 near_miss 直接当成主入场票。")
    if near_miss_entries:
        recommendation_lines.append(
            "备选观察票为 " + ", ".join(entry["ticker"] for entry in near_miss_entries) + "，仅适合作为盘中跟踪对象。"
        )
        near_miss_historical_lines = [
            f"{entry['ticker']}={entry.get('historical_prior', {}).get('summary')}"
            for entry in near_miss_entries
            if (entry.get("historical_prior") or {}).get("summary")
        ]
        if near_miss_historical_lines:
            recommendation_lines.append("观察票历史先验参考: " + "；".join(near_miss_historical_lines))
    if opportunity_pool_entries:
        recommendation_lines.append(
            "自动扩容候选池为 "
            + ", ".join(entry["ticker"] for entry in opportunity_pool_entries)
            + "，这些票结构未坏，但还没进入正式名单，只能在盘中新增强度确认后升级。"
        )
        historical_prior_lines = [
            f"{entry['ticker']}={entry.get('historical_prior', {}).get('summary')}"
            for entry in opportunity_pool_entries
            if (entry.get("historical_prior") or {}).get("summary")
        ]
        if historical_prior_lines:
            recommendation_lines.append("机会池历史先验参考: " + "；".join(historical_prior_lines))
    if research_upside_radar_entries:
        recommendation_lines.append(
            "research 漏票雷达为 "
            + ", ".join(entry["ticker"] for entry in research_upside_radar_entries)
            + "，这些票只用于第二天上涨线索复盘，不进入 BTST 执行名单。"
        )
    if catalyst_theme_entries:
        recommendation_lines.append(
            "题材催化研究池为 "
            + ", ".join(entry["ticker"] for entry in catalyst_theme_entries)
            + "，这些票只用于专题催化跟踪，不进入主池或 BTST 执行名单。"
        )
    if catalyst_theme_frontier_priority.get("promoted_tickers"):
        recommendation_lines.append(
            "题材催化前沿第一优先 research follow-up 为 "
            + ", ".join(catalyst_theme_frontier_priority.get("promoted_tickers") or [])
            + "；这些票是解释性前沿下的可晋级影子样本，只做研究跟踪，不进入当日 BTST 执行名单。"
        )
    if catalyst_theme_shadow_entries:
        recommendation_lines.append(
            "题材催化影子观察为 "
            + ", ".join(entry["ticker"] for entry in catalyst_theme_shadow_entries)
            + "，这些票距离正式题材研究池仅差少数阈值，当前只做近阈值跟踪，不进入主池或 BTST 执行名单。"
        )
    if excluded_research_entries:
        recommendation_lines.append(
            "research 侧已选中但不属于本次 short-trade 执行名单的股票有 "
            + ", ".join(entry["ticker"] for entry in excluded_research_entries)
            + "。"
        )
    if upstream_shadow_entries:
        recommendation_lines.append(
            "上游影子召回覆盖 "
            + ", ".join(entry["ticker"] for entry in upstream_shadow_entries)
            + "，这些票来自 candidate-pool 上游漏票修复通道，只能按当前 short-trade decision 分层处理，不能因为被召回就自动升级。"
        )

    return {
        "report_dir": str(report_dir),
        "snapshot_path": str(snapshot_path),
        "replay_input_path": str(_resolve_replay_input_path(snapshot_path)) if _resolve_replay_input_path(snapshot_path).exists() else None,
        "session_summary_path": str(session_summary_path) if session_summary_path.exists() else None,
        "trade_date": actual_trade_date,
        "next_trade_date": _normalize_trade_date(next_trade_date),
        "target_mode": snapshot.get("target_mode"),
        "selection_target": (session_summary.get("plan_generation") or {}).get("selection_target") or snapshot.get("target_mode"),
        "summary": {
            "selection_target_count": _summary_value(dual_target_summary, "selection_target_count", len(selection_targets)),
            "short_trade_selected_count": len(selected_entries),
            "short_trade_near_miss_count": len(near_miss_entries),
            "short_trade_blocked_count": _summary_value(dual_target_summary, "short_trade_blocked_count", blocked_count),
            "short_trade_rejected_count": _summary_value(dual_target_summary, "short_trade_rejected_count", rejected_count),
            "short_trade_opportunity_pool_count": len(opportunity_pool_entries),
            "research_upside_radar_count": len(research_upside_radar_entries),
            "catalyst_theme_count": len(catalyst_theme_entries),
            "catalyst_theme_shadow_count": len(catalyst_theme_shadow_entries),
            "catalyst_theme_frontier_promoted_count": len(catalyst_theme_frontier_priority.get("promoted_tickers") or []),
            "upstream_shadow_candidate_count": upstream_shadow_summary.get("shadow_candidate_count") or 0,
            "upstream_shadow_promotable_count": upstream_shadow_summary.get("promotable_count") or 0,
            "research_selected_count": _summary_value(dual_target_summary, "research_selected_count", research_selected_count),
        },
        "primary_entry": primary_entry,
        "selected_entries": selected_entries,
        "near_miss_entries": near_miss_entries,
        "opportunity_pool_entries": opportunity_pool_entries,
        "research_upside_radar_entries": research_upside_radar_entries,
        "catalyst_theme_entries": catalyst_theme_entries,
        "catalyst_theme_shadow_entries": catalyst_theme_shadow_entries,
        "catalyst_theme_frontier_summary": catalyst_theme_frontier_summary,
        "catalyst_theme_frontier_priority": catalyst_theme_frontier_priority,
        "upstream_shadow_entries": upstream_shadow_entries,
        "upstream_shadow_summary": upstream_shadow_summary,
        "btst_candidate_historical_context": btst_candidate_historical_context,
        "watch_candidate_historical_context": btst_candidate_historical_context,
        "opportunity_pool_historical_context": btst_candidate_historical_context,
        "excluded_research_entries": excluded_research_entries,
        "recommendation": " ".join(recommendation_lines),
    }


def render_btst_next_day_trade_brief_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    historical_context = (
        analysis.get("btst_candidate_historical_context")
        or analysis.get("watch_candidate_historical_context")
        or analysis.get("opportunity_pool_historical_context")
        or {}
    )
    lines.append("# BTST Next-Day Trade Brief")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- trade_date: {analysis.get('trade_date')}")
    lines.append(f"- next_trade_date: {analysis.get('next_trade_date') or 'n/a'}")
    lines.append(f"- target_mode: {analysis.get('target_mode')}")
    lines.append(f"- selection_target: {analysis.get('selection_target')}")
    lines.append(f"- short_trade_selected_count: {analysis['summary'].get('short_trade_selected_count')}")
    lines.append(f"- short_trade_near_miss_count: {analysis['summary'].get('short_trade_near_miss_count')}")
    lines.append(f"- short_trade_blocked_count: {analysis['summary'].get('short_trade_blocked_count')}")
    lines.append(f"- short_trade_rejected_count: {analysis['summary'].get('short_trade_rejected_count')}")
    lines.append(f"- short_trade_opportunity_pool_count: {analysis['summary'].get('short_trade_opportunity_pool_count')}")
    lines.append(f"- research_upside_radar_count: {analysis['summary'].get('research_upside_radar_count')}")
    lines.append(f"- catalyst_theme_count: {analysis['summary'].get('catalyst_theme_count')}")
    lines.append(f"- catalyst_theme_shadow_count: {analysis['summary'].get('catalyst_theme_shadow_count')}")
    lines.append(f"- catalyst_theme_frontier_promoted_count: {analysis['summary'].get('catalyst_theme_frontier_promoted_count')}")
    lines.append(f"- upstream_shadow_candidate_count: {analysis['summary'].get('upstream_shadow_candidate_count')}")
    lines.append(f"- upstream_shadow_promotable_count: {analysis['summary'].get('upstream_shadow_promotable_count')}")
    lines.append(f"- opportunity_pool_historical_report_count: {historical_context.get('historical_report_count')}")
    lines.append(f"- btst_candidate_historical_count: {historical_context.get('historical_btst_candidate_count')}")
    lines.append(f"- watch_candidate_historical_count: {historical_context.get('historical_watch_candidate_count')}")
    lines.append(f"- watch_selected_historical_count: {historical_context.get('historical_selected_candidate_count')}")
    lines.append(f"- watch_near_miss_historical_count: {historical_context.get('historical_near_miss_candidate_count')}")
    lines.append(f"- opportunity_pool_historical_candidate_count: {historical_context.get('historical_opportunity_candidate_count')}")
    lines.append(f"- research_upside_radar_historical_count: {historical_context.get('historical_research_upside_radar_count')}")
    lines.append(f"- catalyst_theme_historical_count: {historical_context.get('historical_catalyst_theme_count')}")
    lines.append(f"- excluded_research_selected_count: {len(analysis.get('excluded_research_entries') or [])}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")

    for section_title, entries in (
        ("Selected Entries", analysis.get("selected_entries") or []),
        ("Near-Miss Watchlist", analysis.get("near_miss_entries") or []),
    ):
        lines.append(f"## {section_title}")
        if not entries:
            lines.append("- none")
            lines.append("")
            continue
        for entry in entries:
            historical_prior = entry.get("historical_prior") or {}
            lines.append(f"### {entry['ticker']}")
            lines.append(f"- decision: {entry['decision']}")
            lines.append(f"- score_target: {_format_float(entry.get('score_target'))}")
            lines.append(f"- confidence: {_format_float(entry.get('confidence'))}")
            lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
            lines.append(f"- candidate_source: {entry.get('candidate_source')}")
            if historical_prior:
                lines.append(f"- historical_monitor_priority: {historical_prior.get('monitor_priority') or 'n/a'}")
                lines.append(f"- historical_summary: {historical_prior.get('summary') or 'n/a'}")
                lines.append(f"- historical_execution_quality: {historical_prior.get('execution_quality_label') or 'n/a'}")
                lines.append(f"- historical_execution_note: {historical_prior.get('execution_note') or 'n/a'}")
            lines.append(f"- top_reasons: {', '.join(entry.get('top_reasons') or []) or 'n/a'}")
            lines.append(f"- positive_tags: {', '.join(entry.get('positive_tags') or []) or 'n/a'}")
            lines.append(
                "- key_metrics: "
                + ", ".join(
                    [
                        f"breakout={_format_float((entry.get('metrics') or {}).get('breakout_freshness'))}",
                        f"trend={_format_float((entry.get('metrics') or {}).get('trend_acceleration'))}",
                        f"volume={_format_float((entry.get('metrics') or {}).get('volume_expansion_quality'))}",
                        f"close={_format_float((entry.get('metrics') or {}).get('close_strength'))}",
                        f"catalyst={_format_float((entry.get('metrics') or {}).get('catalyst_freshness'))}",
                    ]
                )
            )
            recent_examples = historical_prior.get("recent_examples") or []
            if recent_examples:
                lines.append(
                    "- historical_recent_examples: "
                    + "; ".join(
                        f"{sample.get('trade_date')} {sample.get('ticker')} open={_format_float(sample.get('next_open_return'))}, high={_format_float(sample.get('next_high_return'))}, close={_format_float(sample.get('next_close_return'))}"
                        for sample in recent_examples
                    )
                )
            lines.append("- gate_status: " + ", ".join(f"{key}={value}" for key, value in (entry.get("gate_status") or {}).items()))
            lines.append("")

    lines.append("## Opportunity Expansion Pool")
    opportunity_pool_entries = analysis.get("opportunity_pool_entries") or []
    if not opportunity_pool_entries:
        lines.append("- none")
        lines.append("")
    else:
        for entry in opportunity_pool_entries:
            historical_prior = entry.get("historical_prior") or {}
            lines.append(f"### {entry['ticker']}")
            lines.append(f"- decision: {entry['decision']}")
            lines.append(f"- score_target: {_format_float(entry.get('score_target'))}")
            lines.append(f"- confidence: {_format_float(entry.get('confidence'))}")
            lines.append(f"- score_gap_to_near_miss: {_format_float(entry.get('score_gap_to_near_miss'))}")
            lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
            lines.append(f"- candidate_source: {entry.get('candidate_source')}")
            lines.append(f"- promotion_trigger: {entry.get('promotion_trigger')}")
            lines.append(f"- historical_monitor_priority: {historical_prior.get('monitor_priority') or 'n/a'}")
            lines.append(f"- historical_summary: {historical_prior.get('summary') or 'n/a'}")
            lines.append(f"- historical_execution_quality: {historical_prior.get('execution_quality_label') or 'n/a'}")
            lines.append(f"- historical_execution_note: {historical_prior.get('execution_note') or 'n/a'}")
            lines.append(f"- top_reasons: {', '.join(entry.get('top_reasons') or []) or 'n/a'}")
            lines.append(f"- rejection_reasons: {', '.join(entry.get('rejection_reasons') or []) or 'n/a'}")
            lines.append(f"- positive_tags: {', '.join(entry.get('positive_tags') or []) or 'n/a'}")
            lines.append(
                "- key_metrics: "
                + ", ".join(
                    [
                        f"breakout={_format_float((entry.get('metrics') or {}).get('breakout_freshness'))}",
                        f"trend={_format_float((entry.get('metrics') or {}).get('trend_acceleration'))}",
                        f"volume={_format_float((entry.get('metrics') or {}).get('volume_expansion_quality'))}",
                        f"close={_format_float((entry.get('metrics') or {}).get('close_strength'))}",
                        f"catalyst={_format_float((entry.get('metrics') or {}).get('catalyst_freshness'))}",
                    ]
                )
            )
            recent_examples = historical_prior.get("recent_examples") or []
            if recent_examples:
                lines.append(
                    "- historical_recent_examples: "
                    + "; ".join(
                        f"{sample.get('trade_date')} {sample.get('ticker')} open={_format_float(sample.get('next_open_return'))}, high={_format_float(sample.get('next_high_return'))}, close={_format_float(sample.get('next_close_return'))}"
                        for sample in recent_examples
                    )
                )
            lines.append("- gate_status: " + ", ".join(f"{key}={value}" for key, value in (entry.get("gate_status") or {}).items()))
            lines.append("")

    lines.append("## Research Upside Radar")
    research_upside_radar_entries = analysis.get("research_upside_radar_entries") or []
    if not research_upside_radar_entries:
        lines.append("- none")
        lines.append("")
    else:
        for entry in research_upside_radar_entries:
            historical_prior = entry.get("historical_prior") or {}
            lines.append(f"### {entry['ticker']}")
            lines.append(f"- research_score_target: {_format_float(entry.get('research_score_target'))}")
            lines.append(f"- short_trade_score_target: {_format_float(entry.get('score_target'))}")
            lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
            lines.append(f"- candidate_source: {entry.get('candidate_source')}")
            lines.append(f"- radar_note: {entry.get('radar_note')}")
            lines.append(f"- historical_monitor_priority: {historical_prior.get('monitor_priority') or 'n/a'}")
            lines.append(f"- historical_summary: {historical_prior.get('summary') or 'n/a'}")
            lines.append(f"- historical_execution_quality: {historical_prior.get('execution_quality_label') or 'n/a'}")
            lines.append(f"- historical_execution_note: {historical_prior.get('execution_note') or 'n/a'}")
            lines.append(f"- top_reasons: {', '.join(entry.get('top_reasons') or []) or 'n/a'}")
            lines.append(f"- rejection_reasons: {', '.join(entry.get('rejection_reasons') or []) or 'n/a'}")
            lines.append(f"- delta_summary: {', '.join(entry.get('delta_summary') or []) or 'n/a'}")
            lines.append("")

    lines.append("## Catalyst Theme Research Lane")
    catalyst_theme_entries = analysis.get("catalyst_theme_entries") or []
    if not catalyst_theme_entries:
        lines.append("- none")
        lines.append("")
    else:
        for entry in catalyst_theme_entries:
            historical_prior = entry.get("historical_prior") or {}
            lines.append(f"### {entry['ticker']}")
            lines.append(f"- candidate_score: {_format_float(entry.get('score_target'))}")
            lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
            lines.append(f"- candidate_source: {entry.get('candidate_source')}")
            lines.append(f"- promotion_trigger: {entry.get('promotion_trigger')}")
            lines.append(f"- historical_monitor_priority: {historical_prior.get('monitor_priority') or 'n/a'}")
            lines.append(f"- historical_summary: {historical_prior.get('summary') or 'n/a'}")
            lines.append(f"- positive_tags: {', '.join(entry.get('positive_tags') or []) or 'n/a'}")
            lines.append(f"- blockers: {', '.join(entry.get('blockers') or []) or 'none'}")
            lines.append(
                "- key_metrics: "
                + ", ".join(
                    [
                        f"breakout={_format_float((entry.get('metrics') or {}).get('breakout_freshness'))}",
                        f"trend={_format_float((entry.get('metrics') or {}).get('trend_acceleration'))}",
                        f"close={_format_float((entry.get('metrics') or {}).get('close_strength'))}",
                        f"sector={_format_float((entry.get('metrics') or {}).get('sector_resonance'))}",
                        f"catalyst={_format_float((entry.get('metrics') or {}).get('catalyst_freshness'))}",
                    ]
                )
            )
            lines.append("- gate_status: " + ", ".join(f"{key}={value}" for key, value in (entry.get("gate_status") or {}).items()))
            lines.append("")

    lines.append("## Catalyst Theme Frontier Priority")
    catalyst_theme_frontier_priority = analysis.get("catalyst_theme_frontier_priority") or {}
    promoted_shadow_watch = catalyst_theme_frontier_priority.get("promoted_shadow_watch") or []
    if not catalyst_theme_frontier_priority:
        lines.append("- none")
        lines.append("")
    else:
        lines.append(f"- status: {catalyst_theme_frontier_priority.get('status')}")
        lines.append(f"- recommended_variant_name: {catalyst_theme_frontier_priority.get('recommended_variant_name') or 'n/a'}")
        lines.append(f"- promoted_shadow_count: {catalyst_theme_frontier_priority.get('promoted_shadow_count')}")
        lines.append(f"- promoted_tickers: {', '.join(catalyst_theme_frontier_priority.get('promoted_tickers') or []) or 'none'}")
        lines.append(f"- recommended_relaxation_cost: {_format_float(catalyst_theme_frontier_priority.get('recommended_relaxation_cost'))}")
        lines.append(f"- recommendation: {catalyst_theme_frontier_priority.get('recommendation') or 'n/a'}")
        lines.append(f"- frontier_markdown_path: {catalyst_theme_frontier_priority.get('markdown_path') or 'n/a'}")
        lines.append("")
        if not promoted_shadow_watch:
            lines.append("- promoted_shadow_watch: none")
            lines.append("")
        else:
            for entry in promoted_shadow_watch:
                threshold_shortfalls = dict(entry.get("threshold_shortfalls") or {})
                lines.append(f"### {entry['ticker']}")
                lines.append("- frontier_role: promoted_shadow_priority")
                lines.append("- execution_posture: research_followup_priority")
                lines.append(f"- candidate_score: {_format_float(entry.get('candidate_score'))}")
                lines.append(f"- filter_reason: {entry.get('filter_reason') or 'n/a'}")
                lines.append(f"- total_shortfall: {_format_float(entry.get('total_shortfall'))}")
                lines.append(f"- failed_threshold_count: {entry.get('failed_threshold_count')}")
                lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
                lines.append(f"- promotion_trigger: {entry.get('promotion_trigger') or '若催化继续发酵，才允许升级到题材催化研究池。'}")
                lines.append(f"- top_reasons: {', '.join(entry.get('top_reasons') or []) or 'n/a'}")
                lines.append(f"- positive_tags: {', '.join(entry.get('positive_tags') or []) or 'n/a'}")
                lines.append(
                    "- threshold_shortfalls: "
                    + (
                        ", ".join(f"{key}={_format_float(value)}" for key, value in threshold_shortfalls.items())
                        if threshold_shortfalls
                        else "none"
                    )
                )
                lines.append(
                    "- key_metrics: "
                    + ", ".join(
                        [
                            f"breakout={_format_float((entry.get('metrics') or {}).get('breakout_freshness'))}",
                            f"trend={_format_float((entry.get('metrics') or {}).get('trend_acceleration'))}",
                            f"close={_format_float((entry.get('metrics') or {}).get('close_strength'))}",
                            f"sector={_format_float((entry.get('metrics') or {}).get('sector_resonance'))}",
                            f"catalyst={_format_float((entry.get('metrics') or {}).get('catalyst_freshness'))}",
                        ]
                    )
                )
                lines.append("")

    lines.append("## Catalyst Theme Shadow Watch")
    catalyst_theme_shadow_entries = analysis.get("catalyst_theme_shadow_entries") or []
    if not catalyst_theme_shadow_entries:
        lines.append("- none")
        lines.append("")
    else:
        for entry in catalyst_theme_shadow_entries:
            threshold_shortfalls = dict(entry.get("threshold_shortfalls") or {})
            lines.append(f"### {entry['ticker']}")
            lines.append(f"- candidate_score: {_format_float(entry.get('score_target'))}")
            lines.append(f"- filter_reason: {entry.get('filter_reason') or 'n/a'}")
            lines.append(f"- total_shortfall: {_format_float(entry.get('total_shortfall'))}")
            lines.append(f"- failed_threshold_count: {entry.get('failed_threshold_count')}")
            lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
            lines.append(f"- candidate_source: {entry.get('candidate_source')}")
            lines.append(f"- promotion_trigger: {entry.get('promotion_trigger')}")
            lines.append(f"- top_reasons: {', '.join(entry.get('top_reasons') or []) or 'n/a'}")
            lines.append(f"- positive_tags: {', '.join(entry.get('positive_tags') or []) or 'n/a'}")
            lines.append(
                "- threshold_shortfalls: "
                + (
                    ", ".join(f"{key}={_format_float(value)}" for key, value in threshold_shortfalls.items())
                    if threshold_shortfalls
                    else "none"
                )
            )
            lines.append(f"- blockers: {', '.join(entry.get('blockers') or []) or 'none'}")
            lines.append(
                "- key_metrics: "
                + ", ".join(
                    [
                        f"breakout={_format_float((entry.get('metrics') or {}).get('breakout_freshness'))}",
                        f"trend={_format_float((entry.get('metrics') or {}).get('trend_acceleration'))}",
                        f"close={_format_float((entry.get('metrics') or {}).get('close_strength'))}",
                        f"sector={_format_float((entry.get('metrics') or {}).get('sector_resonance'))}",
                        f"catalyst={_format_float((entry.get('metrics') or {}).get('catalyst_freshness'))}",
                    ]
                )
            )
            lines.append("- gate_status: " + ", ".join(f"{key}={value}" for key, value in (entry.get("gate_status") or {}).items()))
            lines.append("")

    lines.append("## Research Picks Excluded From Short-Trade Brief")
    excluded_research_entries = analysis.get("excluded_research_entries") or []
    if not excluded_research_entries:
        lines.append("- none")
        lines.append("")
    else:
        for entry in excluded_research_entries:
            lines.append(f"### {entry['ticker']}")
            lines.append(f"- research_score_target: {_format_float(entry.get('research_score_target'))}")
            lines.append(f"- short_trade_decision: {entry.get('short_trade_decision')}")
            lines.append(f"- short_trade_score_target: {_format_float(entry.get('short_trade_score_target'))}")
            lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
            lines.append(f"- delta_summary: {', '.join(entry.get('delta_summary') or []) or 'n/a'}")
            lines.append("")

    lines.append("## Upstream Shadow Recall")
    upstream_shadow_summary = analysis.get("upstream_shadow_summary") or {}
    upstream_shadow_entries = analysis.get("upstream_shadow_entries") or []
    if not upstream_shadow_entries:
        lines.append("- none")
        lines.append("")
    else:
        lines.append(f"- shadow_candidate_count: {upstream_shadow_summary.get('shadow_candidate_count')}")
        lines.append(f"- promotable_count: {upstream_shadow_summary.get('promotable_count')}")
        lane_counts = dict(upstream_shadow_summary.get("lane_counts") or {})
        lines.append(
            "- lane_counts: "
            + (
                ", ".join(f"{key}={value}" for key, value in lane_counts.items())
                if lane_counts
                else "none"
            )
        )
        for entry in upstream_shadow_entries:
            lines.append(f"### {entry['ticker']}")
            lines.append(f"- decision: {entry.get('decision')}")
            lines.append(f"- score_target: {_format_float(entry.get('score_target'))}")
            lines.append(f"- confidence: {_format_float(entry.get('confidence'))}")
            lines.append(f"- candidate_source: {entry.get('candidate_source')}")
            lines.append(f"- candidate_pool_lane: {entry.get('candidate_pool_lane_display')}")
            lines.append(f"- candidate_pool_rank: {entry.get('candidate_pool_rank') if entry.get('candidate_pool_rank') is not None else 'n/a'}")
            lines.append(f"- share_of_cutoff: {_format_float(entry.get('candidate_pool_avg_amount_share_of_cutoff'))}")
            lines.append(f"- share_of_min_gate: {_format_float(entry.get('candidate_pool_avg_amount_share_of_min_gate'))}")
            lines.append(f"- upstream_candidate_source: {entry.get('upstream_candidate_source')}")
            lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
            lines.append(f"- promotion_trigger: {entry.get('promotion_trigger')}")
            lines.append(f"- candidate_reason_codes: {', '.join(entry.get('candidate_reason_codes') or []) or 'n/a'}")
            lines.append(f"- top_reasons: {', '.join(entry.get('top_reasons') or []) or 'n/a'}")
            lines.append(f"- rejection_reasons: {', '.join(entry.get('rejection_reasons') or []) or 'n/a'}")
            lines.append(f"- positive_tags: {', '.join(entry.get('positive_tags') or []) or 'n/a'}")
            lines.append(
                "- key_metrics: "
                + ", ".join(
                    [
                        f"breakout={_format_float((entry.get('metrics') or {}).get('breakout_freshness'))}",
                        f"trend={_format_float((entry.get('metrics') or {}).get('trend_acceleration'))}",
                        f"volume={_format_float((entry.get('metrics') or {}).get('volume_expansion_quality'))}",
                        f"close={_format_float((entry.get('metrics') or {}).get('close_strength'))}",
                        f"catalyst={_format_float((entry.get('metrics') or {}).get('catalyst_freshness'))}",
                    ]
                )
            )
            lines.append("- gate_status: " + ", ".join(f"{key}={value}" for key, value in (entry.get("gate_status") or {}).items()))
            lines.append("")

    lines.append("## Source Paths")
    lines.append(f"- report_dir: {analysis.get('report_dir')}")
    lines.append(f"- snapshot_path: {analysis.get('snapshot_path')}")
    lines.append(f"- replay_input_path: {analysis.get('replay_input_path') or 'n/a'}")
    lines.append(f"- session_summary_path: {analysis.get('session_summary_path') or 'n/a'}")
    return "\n".join(lines) + "\n"


def _resolve_brief_analysis(input_path: str | Path | dict[str, Any], trade_date: str | None, next_trade_date: str | None) -> dict[str, Any]:
    if isinstance(input_path, dict):
        payload = dict(input_path)
    else:
        payload = {}

    if not payload:
        resolved_input = Path(input_path).expanduser().resolve()
        if resolved_input.is_file():
            payload = _load_json(resolved_input)
            if "selected_entries" not in payload or "near_miss_entries" not in payload:
                return analyze_btst_next_day_trade_brief(resolved_input, trade_date=trade_date, next_trade_date=next_trade_date)
        else:
            return analyze_btst_next_day_trade_brief(resolved_input, trade_date=trade_date, next_trade_date=next_trade_date)

    if next_trade_date and not payload.get("next_trade_date"):
        payload["next_trade_date"] = _normalize_trade_date(next_trade_date)

    frontier_summary = dict(payload.get("catalyst_theme_frontier_summary") or {})
    frontier_priority = dict(payload.get("catalyst_theme_frontier_priority") or {})
    if not frontier_summary or not frontier_priority:
        frontier_summary = frontier_summary or _load_catalyst_theme_frontier_summary(payload.get("report_dir"))
        frontier_priority = frontier_priority or _build_catalyst_theme_frontier_priority(frontier_summary, list(payload.get("catalyst_theme_shadow_entries") or []))
        payload["catalyst_theme_frontier_summary"] = frontier_summary
        payload["catalyst_theme_frontier_priority"] = frontier_priority

    summary = dict(payload.get("summary") or {})
    summary.setdefault("catalyst_theme_frontier_promoted_count", len(frontier_priority.get("promoted_tickers") or []))
    payload["summary"] = summary
    payload.setdefault("upstream_shadow_entries", [])
    payload.setdefault("upstream_shadow_summary", {"shadow_candidate_count": 0, "promotable_count": 0, "lane_counts": {}, "decision_counts": {}, "top_focus_tickers": []})
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


def analyze_btst_premarket_execution_card(input_path: str | Path | dict[str, Any], trade_date: str | None = None, next_trade_date: str | None = None) -> dict[str, Any]:
    brief = _resolve_brief_analysis(input_path, trade_date=trade_date, next_trade_date=next_trade_date)
    primary_entry = brief.get("primary_entry")
    primary_action = None
    catalyst_theme_frontier_priority = dict(brief.get("catalyst_theme_frontier_priority") or {})
    catalyst_theme_shadow_watch = _build_catalyst_theme_shadow_watch_rows(list(brief.get("catalyst_theme_shadow_entries") or []))
    if primary_entry:
        posture, trigger_rules = _selected_action_posture(primary_entry.get("preferred_entry_mode"))
        historical_prior = dict(primary_entry.get("historical_prior") or {})
        if historical_prior.get("summary"):
            trigger_rules.insert(0, f"历史先验: {historical_prior['summary']}")
        if historical_prior.get("execution_note"):
            trigger_rules.append(f"执行先验: {historical_prior['execution_note']}")
        primary_action = {
            "ticker": primary_entry.get("ticker"),
            "action_tier": "primary_entry",
            "execution_posture": posture,
            "watch_priority": historical_prior.get("monitor_priority") or "unscored",
            "execution_quality_label": historical_prior.get("execution_quality_label") or "unknown",
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
        }

    watch_actions = []
    for entry in brief.get("near_miss_entries") or []:
        historical_prior = dict(entry.get("historical_prior") or {})
        _, primary_watch_rule = _entry_mode_action_guidance(
            entry.get("preferred_entry_mode"),
            default_action="仅做盘中强度跟踪，不预设主买入动作。",
        )
        trigger_rules = [
            primary_watch_rule,
            "若当日需要转为可执行对象，应先回看 short-trade score 与盘中确认信号。",
        ]
        if historical_prior.get("summary"):
            trigger_rules.insert(0, f"历史先验: {historical_prior['summary']}")
        watch_actions.append(
            {
                "ticker": entry.get("ticker"),
                "action_tier": "watch_only",
                "execution_posture": "observe_only",
                "watch_priority": historical_prior.get("monitor_priority") or "unscored",
                "execution_quality_label": historical_prior.get("execution_quality_label") or "unknown",
                "preferred_entry_mode": entry.get("preferred_entry_mode"),
                "trigger_rules": trigger_rules,
                "avoid_rules": [
                    "near_miss 不能与 selected 同级表达。",
                    "没有新增确认前，不把它视为默认替补主票。",
                ],
                "evidence": list(entry.get("top_reasons") or []),
                "metrics": dict(entry.get("metrics") or {}),
                "historical_prior": historical_prior,
            }
        )

    opportunity_actions = []
    for entry in brief.get("opportunity_pool_entries") or []:
        historical_prior = dict(entry.get("historical_prior") or {})
        _, primary_watch_rule = _entry_mode_action_guidance(
            entry.get("preferred_entry_mode"),
            default_action=str(entry.get("promotion_trigger") or "只有盘中新增强度确认时，才允许从机会池升级。"),
        )
        trigger_rules = [
            primary_watch_rule,
            "默认不在开盘前直接升级为主票或近似主票。",
        ]
        if historical_prior.get("summary"):
            trigger_rules.insert(0, f"历史先验: {historical_prior['summary']}")
        opportunity_actions.append(
            {
                "ticker": entry.get("ticker"),
                "action_tier": "conditional_watch_upgrade",
                "execution_posture": "observe_for_upgrade_only",
                "watch_priority": historical_prior.get("monitor_priority") or "unscored",
                "execution_quality_label": historical_prior.get("execution_quality_label") or "unknown",
                "preferred_entry_mode": entry.get("preferred_entry_mode"),
                "trigger_rules": trigger_rules,
                "avoid_rules": [
                    "机会池不是默认交易名单，不因情绪拉升直接入场。",
                    "若结构重新转弱或强度未延续，则继续留在非交易状态。",
                ],
                "evidence": list(entry.get("top_reasons") or []) + list(entry.get("rejection_reasons") or []),
                "metrics": dict(entry.get("metrics") or {}),
                "historical_prior": historical_prior,
            }
        )

    return {
        "trade_date": brief.get("trade_date"),
        "next_trade_date": brief.get("next_trade_date"),
        "selection_target": brief.get("selection_target"),
        "summary": {
            "primary_count": 1 if primary_action else 0,
            "watch_count": len(watch_actions),
            "opportunity_pool_count": len(opportunity_actions),
            "catalyst_theme_frontier_promoted_count": len(catalyst_theme_frontier_priority.get("promoted_tickers") or []),
            "catalyst_theme_shadow_count": len(brief.get("catalyst_theme_shadow_entries") or []),
            "upstream_shadow_candidate_count": int((brief.get("upstream_shadow_summary") or {}).get("shadow_candidate_count") or 0),
            "upstream_shadow_promotable_count": int((brief.get("upstream_shadow_summary") or {}).get("promotable_count") or 0),
            "excluded_research_count": len(brief.get("excluded_research_entries") or []),
        },
        "recommendation": brief.get("recommendation"),
        "primary_action": primary_action,
        "watch_actions": watch_actions,
        "opportunity_actions": opportunity_actions,
        "catalyst_theme_frontier_priority": catalyst_theme_frontier_priority,
        "catalyst_theme_shadow_watch": catalyst_theme_shadow_watch,
        "upstream_shadow_entries": list(brief.get("upstream_shadow_entries") or []),
        "upstream_shadow_summary": dict(brief.get("upstream_shadow_summary") or {}),
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


def render_btst_premarket_execution_card_markdown(card: dict[str, Any]) -> str:
    lines: list[str] = []
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
    lines.append(f"- catalyst_theme_frontier_promoted_count: {summary.get('catalyst_theme_frontier_promoted_count')}")
    lines.append(f"- catalyst_theme_shadow_count: {summary.get('catalyst_theme_shadow_count')}")
    lines.append(f"- upstream_shadow_candidate_count: {summary.get('upstream_shadow_candidate_count')}")
    lines.append(f"- upstream_shadow_promotable_count: {summary.get('upstream_shadow_promotable_count')}")
    lines.append(f"- excluded_research_count: {summary.get('excluded_research_count')}")
    lines.append(f"- recommendation: {card.get('recommendation')}")
    lines.append("")

    primary_action = card.get("primary_action")
    lines.append("## Primary Action")
    if not primary_action:
        lines.append("- none")
        lines.append("")
    else:
        lines.append(f"- ticker: {primary_action.get('ticker')}")
        lines.append(f"- action_tier: {primary_action.get('action_tier')}")
        lines.append(f"- execution_posture: {primary_action.get('execution_posture')}")
        lines.append(f"- watch_priority: {primary_action.get('watch_priority')}")
        lines.append(f"- execution_quality_label: {primary_action.get('execution_quality_label')}")
        lines.append(f"- preferred_entry_mode: {primary_action.get('preferred_entry_mode')}")
        lines.append(f"- historical_summary: {(primary_action.get('historical_prior') or {}).get('summary') or 'n/a'}")
        lines.append(f"- evidence: {', '.join(primary_action.get('evidence') or []) or 'n/a'}")
        lines.append("- trigger_rules:")
        for item in primary_action.get("trigger_rules") or []:
            lines.append(f"  - {item}")
        lines.append("- avoid_rules:")
        for item in primary_action.get("avoid_rules") or []:
            lines.append(f"  - {item}")
        lines.append("")

    lines.append("## Watchlist Actions")
    watch_actions = card.get("watch_actions") or []
    if not watch_actions:
        lines.append("- none")
        lines.append("")
    else:
        for entry in watch_actions:
            lines.append(f"### {entry.get('ticker')}")
            lines.append(f"- action_tier: {entry.get('action_tier')}")
            lines.append(f"- execution_posture: {entry.get('execution_posture')}")
            lines.append(f"- watch_priority: {entry.get('watch_priority')}")
            lines.append(f"- execution_quality_label: {entry.get('execution_quality_label')}")
            lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
            lines.append(f"- historical_summary: {(entry.get('historical_prior') or {}).get('summary') or 'n/a'}")
            lines.append(f"- evidence: {', '.join(entry.get('evidence') or []) or 'n/a'}")
            lines.append("- trigger_rules:")
            for item in entry.get("trigger_rules") or []:
                lines.append(f"  - {item}")
            lines.append("- avoid_rules:")
            for item in entry.get("avoid_rules") or []:
                lines.append(f"  - {item}")
            lines.append("")

    lines.append("## Opportunity Pool Actions")
    opportunity_actions = card.get("opportunity_actions") or []
    if not opportunity_actions:
        lines.append("- none")
        lines.append("")
    else:
        for entry in opportunity_actions:
            lines.append(f"### {entry.get('ticker')}")
            lines.append(f"- action_tier: {entry.get('action_tier')}")
            lines.append(f"- execution_posture: {entry.get('execution_posture')}")
            lines.append(f"- watch_priority: {entry.get('watch_priority')}")
            lines.append(f"- execution_quality_label: {entry.get('execution_quality_label')}")
            lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
            lines.append(f"- historical_summary: {(entry.get('historical_prior') or {}).get('summary') or 'n/a'}")
            lines.append(f"- evidence: {', '.join(entry.get('evidence') or []) or 'n/a'}")
            lines.append("- trigger_rules:")
            for item in entry.get("trigger_rules") or []:
                lines.append(f"  - {item}")
            lines.append("- avoid_rules:")
            for item in entry.get("avoid_rules") or []:
                lines.append(f"  - {item}")
            lines.append("")

    lines.append("## Catalyst Theme Frontier Priority")
    catalyst_theme_frontier_priority = card.get("catalyst_theme_frontier_priority") or {}
    promoted_shadow_watch = catalyst_theme_frontier_priority.get("promoted_shadow_watch") or []
    if not catalyst_theme_frontier_priority:
        lines.append("- none")
        lines.append("")
    else:
        lines.append(f"- status: {catalyst_theme_frontier_priority.get('status')}")
        lines.append(f"- recommended_variant_name: {catalyst_theme_frontier_priority.get('recommended_variant_name') or 'n/a'}")
        lines.append(f"- promoted_shadow_count: {catalyst_theme_frontier_priority.get('promoted_shadow_count')}")
        lines.append(f"- promoted_tickers: {', '.join(catalyst_theme_frontier_priority.get('promoted_tickers') or []) or 'none'}")
        lines.append(f"- recommended_relaxation_cost: {_format_float(catalyst_theme_frontier_priority.get('recommended_relaxation_cost'))}")
        lines.append(f"- recommendation: {catalyst_theme_frontier_priority.get('recommendation') or 'n/a'}")
        lines.append(f"- frontier_markdown_path: {catalyst_theme_frontier_priority.get('markdown_path') or 'n/a'}")
        lines.append("")
        if not promoted_shadow_watch:
            lines.append("- promoted_shadow_watch: none")
            lines.append("")
        else:
            for index, item in enumerate(promoted_shadow_watch, start=1):
                threshold_shortfalls = dict(item.get("threshold_shortfalls") or {})
                metrics = dict(item.get("metrics") or {})
                lines.append(f"### {index}. {item.get('ticker')}")
                lines.append("- action_tier: catalyst_theme_frontier_priority")
                lines.append("- execution_posture: research_followup_priority")
                lines.append(f"- candidate_score: {_format_float(item.get('candidate_score'))}")
                lines.append(f"- filter_reason: {item.get('filter_reason') or 'n/a'}")
                lines.append(f"- total_shortfall: {_format_float(item.get('total_shortfall'))}")
                lines.append(f"- failed_threshold_count: {item.get('failed_threshold_count')}")
                lines.append(f"- preferred_entry_mode: {item.get('preferred_entry_mode')}")
                lines.append(f"- evidence: {', '.join(item.get('top_reasons') or []) or 'n/a'}")
                lines.append(f"- positive_tags: {', '.join(item.get('positive_tags') or []) or 'n/a'}")
                lines.append(
                    "- threshold_shortfalls: "
                    + (
                        ", ".join(f"{key}={_format_float(value)}" for key, value in threshold_shortfalls.items())
                        if threshold_shortfalls
                        else "none"
                    )
                )
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
                lines.append("- trigger_rules:")
                lines.append(f"  - {item.get('promotion_trigger') or '若催化继续发酵，才允许升级到题材催化研究池。'}")
                if threshold_shortfalls:
                    lines.append(
                        "  - 需先补齐阈值缺口: "
                        + ", ".join(f"{key}={_format_float(value)}" for key, value in threshold_shortfalls.items())
                    )
                lines.append("- avoid_rules:")
                lines.append("  - 不进入当日 BTST 交易名单。")
                lines.append("  - 不把题材催化前沿 priority 与 short-trade watchlist 混用。")
                lines.append("")

    lines.append("## Catalyst Theme Shadow Watch")
    catalyst_theme_shadow_watch = card.get("catalyst_theme_shadow_watch") or []
    if not catalyst_theme_shadow_watch:
        lines.append("- none")
        lines.append("")
    else:
        for index, item in enumerate(catalyst_theme_shadow_watch, start=1):
            threshold_shortfalls = dict(item.get("threshold_shortfalls") or {})
            metrics = dict(item.get("metrics") or {})
            lines.append(f"### {index}. {item.get('ticker')}")
            lines.append("- action_tier: research_followup_only")
            lines.append("- execution_posture: research_followup_only")
            lines.append(f"- candidate_score: {_format_float(item.get('candidate_score'))}")
            lines.append(f"- filter_reason: {item.get('filter_reason') or 'n/a'}")
            lines.append(f"- total_shortfall: {_format_float(item.get('total_shortfall'))}")
            lines.append(f"- failed_threshold_count: {item.get('failed_threshold_count')}")
            lines.append(f"- preferred_entry_mode: {item.get('preferred_entry_mode')}")
            lines.append(f"- evidence: {', '.join(item.get('top_reasons') or []) or 'n/a'}")
            lines.append(f"- positive_tags: {', '.join(item.get('positive_tags') or []) or 'n/a'}")
            lines.append(
                "- threshold_shortfalls: "
                + (
                    ", ".join(f"{key}={_format_float(value)}" for key, value in threshold_shortfalls.items())
                    if threshold_shortfalls
                    else "none"
                )
            )
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
            lines.append("- trigger_rules:")
            lines.append(f"  - {item.get('promotion_trigger') or '若催化继续发酵，才允许升级到题材催化研究池。'}")
            if threshold_shortfalls:
                lines.append(
                    "  - 需先补齐阈值缺口: "
                    + ", ".join(f"{key}={_format_float(value)}" for key, value in threshold_shortfalls.items())
                )
            lines.append("- avoid_rules:")
            lines.append("  - 不进入当日 BTST 交易名单。")
            lines.append("  - 不把题材催化研究跟踪对象与 short-trade watchlist 混用。")
            lines.append("")

    lines.append("## Explicit Non-Trades")
    excluded_entries = card.get("excluded_research_entries") or []
    if not excluded_entries:
        lines.append("- none")
        lines.append("")
    else:
        for entry in excluded_entries:
            lines.append(
                f"- {entry.get('ticker')}: research selected, but short_trade={entry.get('short_trade_decision')} so it stays outside the short-trade execution list."
            )
        lines.append("")

    lines.append("## Upstream Shadow Recall")
    upstream_shadow_summary = card.get("upstream_shadow_summary") or {}
    upstream_shadow_entries = card.get("upstream_shadow_entries") or []
    if not upstream_shadow_entries:
        lines.append("- none")
        lines.append("")
    else:
        lines.append(f"- shadow_candidate_count: {upstream_shadow_summary.get('shadow_candidate_count')}")
        lines.append(f"- promotable_count: {upstream_shadow_summary.get('promotable_count')}")
        lines.append(
            "- lane_counts: "
            + ", ".join(f"{key}={value}" for key, value in dict(upstream_shadow_summary.get('lane_counts') or {}).items())
        )
        lines.append("")
        for entry in upstream_shadow_entries:
            lines.append(f"### {entry.get('ticker')}")
            lines.append(f"- candidate_source: {entry.get('candidate_source')}")
            lines.append(f"- candidate_pool_lane: {entry.get('candidate_pool_lane_display')}")
            lines.append(f"- decision: {entry.get('decision')}")
            lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
            lines.append(f"- promotion_trigger: {entry.get('promotion_trigger')}")
            lines.append(f"- evidence: {', '.join(entry.get('top_reasons') or []) or 'n/a'}")
            lines.append(f"- rejection_reasons: {', '.join(entry.get('rejection_reasons') or []) or 'n/a'}")
            lines.append("")

    lines.append("## Global Guardrails")
    for item in card.get("global_guardrails") or []:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Source Paths")
    source_paths = card.get("source_paths") or {}
    lines.append(f"- report_dir: {source_paths.get('report_dir')}")
    lines.append(f"- snapshot_path: {source_paths.get('snapshot_path')}")
    lines.append(f"- session_summary_path: {source_paths.get('session_summary_path')}")
    return "\n".join(lines) + "\n"


def _monitor_priority_rank(priority: str | None) -> int:
    return {
        "high": 0,
        "medium": 1,
        "low": 2,
        "unscored": 3,
    }.get(str(priority or "unscored"), 3)


def analyze_btst_opening_watch_card(input_path: str | Path | dict[str, Any], trade_date: str | None = None, next_trade_date: str | None = None) -> dict[str, Any]:
    brief = _resolve_brief_analysis(input_path, trade_date=trade_date, next_trade_date=next_trade_date)
    focus_items: list[dict[str, Any]] = []
    catalyst_theme_frontier_priority = dict(brief.get("catalyst_theme_frontier_priority") or {})
    catalyst_theme_shadow_watch = _build_catalyst_theme_shadow_watch_rows(list(brief.get("catalyst_theme_shadow_entries") or []))
    selected_entries = [_apply_execution_quality_entry_mode(entry) for entry in list(brief.get("selected_entries") or [])]
    near_miss_entries = [_apply_execution_quality_entry_mode(entry) for entry in list(brief.get("near_miss_entries") or [])]
    opportunity_pool_entries = [_apply_execution_quality_entry_mode(entry) for entry in list(brief.get("opportunity_pool_entries") or [])]

    primary_entry = dict(brief.get("primary_entry") or {})
    if not primary_entry and selected_entries:
        primary_entry = dict(selected_entries[0])
    elif primary_entry:
        primary_entry = _apply_execution_quality_entry_mode(primary_entry)
    if primary_entry:
        posture, trigger_rules = _selected_action_posture(primary_entry.get("preferred_entry_mode"))
        historical_prior = dict(primary_entry.get("historical_prior") or {})
        focus_items.append(
            {
                "ticker": primary_entry.get("ticker"),
                "focus_tier": "primary_entry",
                "monitor_priority": "execute",
                "execution_posture": posture,
                "score_target": primary_entry.get("score_target"),
                "preferred_entry_mode": primary_entry.get("preferred_entry_mode"),
                "why_now": ", ".join(primary_entry.get("top_reasons") or []) or "当前 short-trade 正式 selected。",
                "opening_plan": trigger_rules[0] if trigger_rules else "只在确认出现后执行。",
                "historical_summary": historical_prior.get("summary"),
                "execution_note": historical_prior.get("execution_note"),
            }
        )

    for entry in near_miss_entries:
        historical_prior = dict(entry.get("historical_prior") or {})
        _, opening_plan = _entry_mode_action_guidance(
            entry.get("preferred_entry_mode"),
            default_action="只观察，不预设与主票同级的买入动作。",
        )
        focus_items.append(
            {
                "ticker": entry.get("ticker"),
                "focus_tier": "near_miss_watch",
                "monitor_priority": historical_prior.get("monitor_priority") or "unscored",
                "execution_posture": "observe_only",
                "score_target": entry.get("score_target"),
                "preferred_entry_mode": entry.get("preferred_entry_mode"),
                "why_now": ", ".join(entry.get("top_reasons") or []) or "当前接近 near-miss 边界。",
                "opening_plan": opening_plan,
                "historical_summary": historical_prior.get("summary"),
                "execution_note": historical_prior.get("execution_note"),
            }
        )

    for entry in opportunity_pool_entries:
        historical_prior = dict(entry.get("historical_prior") or {})
        _, opening_plan = _entry_mode_action_guidance(
            entry.get("preferred_entry_mode"),
            default_action=str(entry.get("promotion_trigger") or "只有盘中新增强度确认时，才允许从机会池升级。"),
        )
        focus_items.append(
            {
                "ticker": entry.get("ticker"),
                "focus_tier": "opportunity_pool",
                "monitor_priority": historical_prior.get("monitor_priority") or "unscored",
                "execution_posture": "observe_for_upgrade_only",
                "score_target": entry.get("score_target"),
                "preferred_entry_mode": entry.get("preferred_entry_mode"),
                "why_now": ", ".join(entry.get("top_reasons") or []) or "结构未坏，但暂未进入正式 short-trade 名单。",
                "opening_plan": opening_plan,
                "historical_summary": historical_prior.get("summary"),
                "execution_note": historical_prior.get("execution_note"),
            }
        )

    for entry in brief.get("research_upside_radar_entries") or []:
        historical_prior = dict(entry.get("historical_prior") or {})
        focus_items.append(
            {
                "ticker": entry.get("ticker"),
                "focus_tier": "research_upside_radar",
                "monitor_priority": historical_prior.get("monitor_priority") or "unscored",
                "execution_posture": "non_trade_learning_only",
                "score_target": entry.get("score_target"),
                "preferred_entry_mode": entry.get("preferred_entry_mode"),
                "why_now": ", ".join(entry.get("top_reasons") or []) or "research 已选中但 BTST 未放行。",
                "opening_plan": str(entry.get("radar_note") or "只做漏票学习，不加入当日 BTST 交易名单。"),
                "historical_summary": historical_prior.get("summary"),
                "execution_note": historical_prior.get("execution_note"),
            }
        )

    focus_items.sort(
        key=lambda item: (
            0
            if item.get("focus_tier") == "primary_entry"
            else 1
            if item.get("focus_tier") == "near_miss_watch"
            else 2
            if item.get("focus_tier") == "opportunity_pool"
            else 3,
            _monitor_priority_rank(item.get("monitor_priority")),
            _execution_priority_rank((item.get("execution_note") and "medium") or "unscored"),
            -_as_float(item.get("score_target")),
            str(item.get("ticker") or ""),
        )
    )

    headline = "当前没有正式交易票，开盘只做观察。"
    if primary_entry:
        headline = "先看主票确认，再看 near-miss 和机会池是否出现升级信号。"
    elif brief.get("near_miss_entries"):
        headline = "当前没有正式主票，开盘只保留 near-miss 与机会池观察，不预设交易。"
    elif brief.get("opportunity_pool_entries"):
        headline = "当前只有机会池可跟踪，除非盘中新强度确认，否则不交易。"
    if catalyst_theme_frontier_priority.get("promoted_tickers"):
        headline = headline.rstrip("。") + "；题材催化前沿优先跟踪 " + ", ".join(catalyst_theme_frontier_priority.get("promoted_tickers") or []) + "，但仍只做研究跟踪。"
    upstream_shadow_summary = dict(brief.get("upstream_shadow_summary") or {})
    if upstream_shadow_summary.get("shadow_candidate_count"):
        headline = headline.rstrip("。") + "；上游影子召回关注 " + ", ".join(upstream_shadow_summary.get("top_focus_tickers") or []) + "。"

    return {
        "trade_date": brief.get("trade_date"),
        "next_trade_date": brief.get("next_trade_date"),
        "selection_target": brief.get("selection_target"),
        "headline": headline,
        "recommendation": brief.get("recommendation"),
        "summary": {
            "primary_count": len(brief.get("selected_entries") or []),
            "near_miss_count": len(brief.get("near_miss_entries") or []),
            "opportunity_pool_count": len(brief.get("opportunity_pool_entries") or []),
            "catalyst_theme_frontier_promoted_count": len(catalyst_theme_frontier_priority.get("promoted_tickers") or []),
            "catalyst_theme_shadow_count": len(brief.get("catalyst_theme_shadow_entries") or []),
            "upstream_shadow_candidate_count": int(upstream_shadow_summary.get("shadow_candidate_count") or 0),
            "upstream_shadow_promotable_count": int(upstream_shadow_summary.get("promotable_count") or 0),
        },
        "focus_items": focus_items,
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


def render_btst_opening_watch_card_markdown(card: dict[str, Any]) -> str:
    lines: list[str] = []
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
    lines.append(f"- catalyst_theme_frontier_promoted_count: {summary.get('catalyst_theme_frontier_promoted_count')}")
    lines.append(f"- catalyst_theme_shadow_count: {summary.get('catalyst_theme_shadow_count')}")
    lines.append(f"- upstream_shadow_candidate_count: {summary.get('upstream_shadow_candidate_count')}")
    lines.append(f"- upstream_shadow_promotable_count: {summary.get('upstream_shadow_promotable_count')}")
    lines.append(f"- recommendation: {card.get('recommendation')}")
    lines.append("")
    lines.append("## Focus Order")
    focus_items = card.get("focus_items") or []
    if not focus_items:
        lines.append("- none")
        lines.append("")
    else:
        for index, item in enumerate(focus_items, start=1):
            lines.append(f"### {index}. {item.get('ticker')}")
            lines.append(f"- focus_tier: {item.get('focus_tier')}")
            lines.append(f"- monitor_priority: {item.get('monitor_priority')}")
            lines.append(f"- execution_posture: {item.get('execution_posture')}")
            lines.append(f"- score_target: {_format_float(item.get('score_target'))}")
            lines.append(f"- preferred_entry_mode: {item.get('preferred_entry_mode')}")
            lines.append(f"- why_now: {item.get('why_now')}")
            lines.append(f"- opening_plan: {item.get('opening_plan')}")
            lines.append(f"- historical_summary: {item.get('historical_summary') or 'n/a'}")
            lines.append(f"- execution_note: {item.get('execution_note') or 'n/a'}")
            lines.append("")

    lines.append("## Catalyst Theme Frontier Priority")
    catalyst_theme_frontier_priority = card.get("catalyst_theme_frontier_priority") or {}
    promoted_shadow_watch = catalyst_theme_frontier_priority.get("promoted_shadow_watch") or []
    if not catalyst_theme_frontier_priority:
        lines.append("- none")
        lines.append("")
    else:
        lines.append(f"- status: {catalyst_theme_frontier_priority.get('status')}")
        lines.append(f"- recommended_variant_name: {catalyst_theme_frontier_priority.get('recommended_variant_name') or 'n/a'}")
        lines.append(f"- promoted_shadow_count: {catalyst_theme_frontier_priority.get('promoted_shadow_count')}")
        lines.append(f"- promoted_tickers: {', '.join(catalyst_theme_frontier_priority.get('promoted_tickers') or []) or 'none'}")
        lines.append(f"- recommended_relaxation_cost: {_format_float(catalyst_theme_frontier_priority.get('recommended_relaxation_cost'))}")
        lines.append(f"- recommendation: {catalyst_theme_frontier_priority.get('recommendation') or 'n/a'}")
        lines.append(f"- frontier_markdown_path: {catalyst_theme_frontier_priority.get('markdown_path') or 'n/a'}")
        lines.append("")
        if not promoted_shadow_watch:
            lines.append("- promoted_shadow_watch: none")
            lines.append("")
        else:
            for index, item in enumerate(promoted_shadow_watch, start=1):
                threshold_shortfalls = dict(item.get("threshold_shortfalls") or {})
                lines.append(f"### {index}. {item.get('ticker')}")
                lines.append("- focus_tier: catalyst_theme_frontier_priority")
                lines.append("- execution_posture: research_followup_priority")
                lines.append(f"- candidate_score: {_format_float(item.get('candidate_score'))}")
                lines.append(f"- filter_reason: {item.get('filter_reason') or 'n/a'}")
                lines.append(f"- total_shortfall: {_format_float(item.get('total_shortfall'))}")
                lines.append(f"- failed_threshold_count: {item.get('failed_threshold_count')}")
                lines.append(f"- preferred_entry_mode: {item.get('preferred_entry_mode')}")
                lines.append(f"- opening_plan: {item.get('promotion_trigger') or '只做研究跟踪，不进入当日 BTST 交易名单。'}")
                lines.append(f"- top_reasons: {', '.join(item.get('top_reasons') or []) or 'n/a'}")
                lines.append(f"- positive_tags: {', '.join(item.get('positive_tags') or []) or 'n/a'}")
                lines.append(
                    "- threshold_shortfalls: "
                    + (
                        ", ".join(f"{key}={_format_float(value)}" for key, value in threshold_shortfalls.items())
                        if threshold_shortfalls
                        else "none"
                    )
                )
                lines.append(
                    "- key_metrics: "
                    + ", ".join(
                        [
                            f"breakout={_format_float((item.get('metrics') or {}).get('breakout_freshness'))}",
                            f"trend={_format_float((item.get('metrics') or {}).get('trend_acceleration'))}",
                            f"close={_format_float((item.get('metrics') or {}).get('close_strength'))}",
                            f"sector={_format_float((item.get('metrics') or {}).get('sector_resonance'))}",
                            f"catalyst={_format_float((item.get('metrics') or {}).get('catalyst_freshness'))}",
                        ]
                    )
                )
                lines.append("")

    lines.append("## Catalyst Theme Shadow Watch")
    catalyst_theme_shadow_watch = card.get("catalyst_theme_shadow_watch") or []
    if not catalyst_theme_shadow_watch:
        lines.append("- none")
        lines.append("")
    else:
        for index, item in enumerate(catalyst_theme_shadow_watch, start=1):
            threshold_shortfalls = dict(item.get("threshold_shortfalls") or {})
            lines.append(f"### {index}. {item.get('ticker')}")
            lines.append("- focus_tier: catalyst_theme_shadow")
            lines.append("- execution_posture: research_followup_only")
            lines.append(f"- candidate_score: {_format_float(item.get('candidate_score'))}")
            lines.append(f"- filter_reason: {item.get('filter_reason') or 'n/a'}")
            lines.append(f"- total_shortfall: {_format_float(item.get('total_shortfall'))}")
            lines.append(f"- failed_threshold_count: {item.get('failed_threshold_count')}")
            lines.append(f"- preferred_entry_mode: {item.get('preferred_entry_mode')}")
            lines.append(f"- opening_plan: {item.get('promotion_trigger') or '只做研究跟踪，不进入当日 BTST 交易名单。'}")
            lines.append(f"- top_reasons: {', '.join(item.get('top_reasons') or []) or 'n/a'}")
            lines.append(f"- positive_tags: {', '.join(item.get('positive_tags') or []) or 'n/a'}")
            lines.append(
                "- threshold_shortfalls: "
                + (
                    ", ".join(f"{key}={_format_float(value)}" for key, value in threshold_shortfalls.items())
                    if threshold_shortfalls
                    else "none"
                )
            )
            lines.append(
                "- key_metrics: "
                + ", ".join(
                    [
                        f"breakout={_format_float((item.get('metrics') or {}).get('breakout_freshness'))}",
                        f"trend={_format_float((item.get('metrics') or {}).get('trend_acceleration'))}",
                        f"close={_format_float((item.get('metrics') or {}).get('close_strength'))}",
                        f"sector={_format_float((item.get('metrics') or {}).get('sector_resonance'))}",
                        f"catalyst={_format_float((item.get('metrics') or {}).get('catalyst_freshness'))}",
                    ]
                )
            )
            lines.append("")

    lines.append("## Upstream Shadow Recall")
    upstream_shadow_summary = card.get("upstream_shadow_summary") or {}
    upstream_shadow_entries = card.get("upstream_shadow_entries") or []
    if not upstream_shadow_entries:
        lines.append("- none")
        lines.append("")
    else:
        lines.append(f"- shadow_candidate_count: {upstream_shadow_summary.get('shadow_candidate_count')}")
        lines.append(f"- promotable_count: {upstream_shadow_summary.get('promotable_count')}")
        lines.append(
            "- lane_counts: "
            + ", ".join(f"{key}={value}" for key, value in dict(upstream_shadow_summary.get('lane_counts') or {}).items())
        )
        lines.append("")
        for index, item in enumerate(upstream_shadow_entries, start=1):
            lines.append(f"### {index}. {item.get('ticker')}")
            lines.append("- focus_tier: upstream_shadow_recall")
            lines.append(f"- candidate_source: {item.get('candidate_source')}")
            lines.append(f"- candidate_pool_lane: {item.get('candidate_pool_lane_display')}")
            lines.append(f"- decision: {item.get('decision')}")
            lines.append(f"- preferred_entry_mode: {item.get('preferred_entry_mode')}")
            lines.append(f"- opening_plan: {item.get('promotion_trigger')}")
            lines.append(f"- top_reasons: {', '.join(item.get('top_reasons') or []) or 'n/a'}")
            lines.append(f"- rejection_reasons: {', '.join(item.get('rejection_reasons') or []) or 'n/a'}")
            lines.append("")

    lines.append("## Guardrails")
    for item in card.get("global_guardrails") or []:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Source Paths")
    source_paths = card.get("source_paths") or {}
    lines.append(f"- report_dir: {source_paths.get('report_dir')}")
    lines.append(f"- snapshot_path: {source_paths.get('snapshot_path')}")
    lines.append(f"- session_summary_path: {source_paths.get('session_summary_path')}")
    return "\n".join(lines) + "\n"


def analyze_btst_next_day_priority_board(input_path: str | Path | dict[str, Any], trade_date: str | None = None, next_trade_date: str | None = None) -> dict[str, Any]:
    brief = _resolve_brief_analysis(input_path, trade_date=trade_date, next_trade_date=next_trade_date)
    priority_rows: list[dict[str, Any]] = []
    catalyst_theme_frontier_priority = dict(brief.get("catalyst_theme_frontier_priority") or {})
    catalyst_theme_shadow_watch = _build_catalyst_theme_shadow_watch_rows(list(brief.get("catalyst_theme_shadow_entries") or []))
    selected_entries = [_apply_execution_quality_entry_mode(entry) for entry in list(brief.get("selected_entries") or [])]
    near_miss_entries = [_apply_execution_quality_entry_mode(entry) for entry in list(brief.get("near_miss_entries") or [])]
    opportunity_pool_entries = [_apply_execution_quality_entry_mode(entry) for entry in list(brief.get("opportunity_pool_entries") or [])]

    for index, entry in enumerate(selected_entries):
        historical_prior = dict(entry.get("historical_prior") or {})
        posture, trigger_rules = _selected_action_posture(entry.get("preferred_entry_mode"))
        priority_rows.append(
            {
                "ticker": entry.get("ticker"),
                "lane": "primary_entry" if index == 0 else "selected_backup",
                "actionability": "trade_candidate",
                "monitor_priority": historical_prior.get("monitor_priority") or "high",
                "execution_priority": historical_prior.get("execution_priority") or "unscored",
                "execution_quality_label": historical_prior.get("execution_quality_label") or "unknown",
                "score_target": entry.get("score_target"),
                "preferred_entry_mode": entry.get("preferred_entry_mode"),
                "why_now": ", ".join(entry.get("top_reasons") or []) or "当前 short-trade selected。",
                "suggested_action": trigger_rules[0] if trigger_rules else "盘中确认后再执行。",
                "historical_summary": historical_prior.get("summary"),
                "execution_note": historical_prior.get("execution_note"),
            }
        )

    for entry in near_miss_entries:
        historical_prior = dict(entry.get("historical_prior") or {})
        _, suggested_action = _entry_mode_action_guidance(
            entry.get("preferred_entry_mode"),
            default_action="仅做盘中跟踪，不预设主买入动作。",
        )
        priority_rows.append(
            {
                "ticker": entry.get("ticker"),
                "lane": "near_miss_watch",
                "actionability": "watch_only",
                "monitor_priority": historical_prior.get("monitor_priority") or "unscored",
                "execution_priority": historical_prior.get("execution_priority") or "unscored",
                "execution_quality_label": historical_prior.get("execution_quality_label") or "unknown",
                "score_target": entry.get("score_target"),
                "preferred_entry_mode": entry.get("preferred_entry_mode"),
                "why_now": ", ".join(entry.get("top_reasons") or []) or "当前接近 near-miss 边界。",
                "suggested_action": suggested_action,
                "historical_summary": historical_prior.get("summary"),
                "execution_note": historical_prior.get("execution_note"),
            }
        )

    for entry in opportunity_pool_entries:
        historical_prior = dict(entry.get("historical_prior") or {})
        _, suggested_action = _entry_mode_action_guidance(
            entry.get("preferred_entry_mode"),
            default_action=str(entry.get("promotion_trigger") or "只有盘中新强度确认时才升级。"),
        )
        priority_rows.append(
            {
                "ticker": entry.get("ticker"),
                "lane": "opportunity_pool",
                "actionability": "upgrade_only",
                "monitor_priority": historical_prior.get("monitor_priority") or "unscored",
                "execution_priority": historical_prior.get("execution_priority") or "unscored",
                "execution_quality_label": historical_prior.get("execution_quality_label") or "unknown",
                "score_target": entry.get("score_target"),
                "preferred_entry_mode": entry.get("preferred_entry_mode"),
                "why_now": ", ".join(entry.get("top_reasons") or []) or "结构未坏但仍在机会池。",
                "suggested_action": suggested_action,
                "historical_summary": historical_prior.get("summary"),
                "execution_note": historical_prior.get("execution_note"),
            }
        )

    for entry in brief.get("research_upside_radar_entries") or []:
        historical_prior = dict(entry.get("historical_prior") or {})
        priority_rows.append(
            {
                "ticker": entry.get("ticker"),
                "lane": "research_upside_radar",
                "actionability": "non_trade_learning_only",
                "monitor_priority": historical_prior.get("monitor_priority") or "unscored",
                "execution_priority": historical_prior.get("execution_priority") or "unscored",
                "execution_quality_label": historical_prior.get("execution_quality_label") or "unknown",
                "score_target": entry.get("score_target"),
                "research_score_target": entry.get("research_score_target"),
                "preferred_entry_mode": entry.get("preferred_entry_mode"),
                "why_now": ", ".join(entry.get("top_reasons") or []) or "research 已选中但 BTST 未放行。",
                "suggested_action": str(entry.get("radar_note") or "只做漏票学习，不加入当日 BTST 交易名单。"),
                "historical_summary": historical_prior.get("summary"),
                "execution_note": historical_prior.get("execution_note"),
            }
        )

    lane_rank = {
        "primary_entry": 0,
        "selected_backup": 1,
        "near_miss_watch": 2,
        "opportunity_pool": 3,
        "research_upside_radar": 4,
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

    headline = "当前没有可执行主票，priority board 只保留观察与漏票线索。"
    if brief.get("primary_entry"):
        headline = "先执行主票确认，再按 near-miss、机会池、research 漏票雷达递减关注。"
    elif brief.get("near_miss_entries"):
        headline = "当前没有主票，优先看 near-miss，其次看机会池和 research 漏票雷达。"
    if catalyst_theme_frontier_priority.get("promoted_tickers"):
        headline = headline.rstrip("。") + "；题材催化前沿 research priority 为 " + ", ".join(catalyst_theme_frontier_priority.get("promoted_tickers") or []) + "。"

    return {
        "trade_date": brief.get("trade_date"),
        "next_trade_date": brief.get("next_trade_date"),
        "selection_target": brief.get("selection_target"),
        "headline": headline,
        "summary": {
            "primary_count": len(brief.get("selected_entries") or []),
            "near_miss_count": len(brief.get("near_miss_entries") or []),
            "opportunity_pool_count": len(brief.get("opportunity_pool_entries") or []),
            "research_upside_radar_count": len(brief.get("research_upside_radar_entries") or []),
            "catalyst_theme_count": len(brief.get("catalyst_theme_entries") or []),
            "catalyst_theme_frontier_promoted_count": len(catalyst_theme_frontier_priority.get("promoted_tickers") or []),
            "catalyst_theme_shadow_count": len(brief.get("catalyst_theme_shadow_entries") or []),
        },
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


def render_btst_next_day_priority_board_markdown(board: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Next-Day Priority Board")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- trade_date: {board.get('trade_date')}")
    lines.append(f"- next_trade_date: {board.get('next_trade_date') or 'n/a'}")
    lines.append(f"- selection_target: {board.get('selection_target')}")
    lines.append(f"- headline: {board.get('headline')}")
    summary = board.get("summary") or {}
    lines.append(f"- primary_count: {summary.get('primary_count')}")
    lines.append(f"- near_miss_count: {summary.get('near_miss_count')}")
    lines.append(f"- opportunity_pool_count: {summary.get('opportunity_pool_count')}")
    lines.append(f"- research_upside_radar_count: {summary.get('research_upside_radar_count')}")
    lines.append(f"- catalyst_theme_count: {summary.get('catalyst_theme_count')}")
    lines.append(f"- catalyst_theme_frontier_promoted_count: {summary.get('catalyst_theme_frontier_promoted_count')}")
    lines.append(f"- catalyst_theme_shadow_count: {summary.get('catalyst_theme_shadow_count')}")
    lines.append("")
    lines.append("## Priority Rows")
    priority_rows = board.get("priority_rows") or []
    if not priority_rows:
        lines.append("- none")
        lines.append("")
    else:
        for index, row in enumerate(priority_rows, start=1):
            lines.append(f"### {index}. {row.get('ticker')}")
            lines.append(f"- lane: {row.get('lane')}")
            lines.append(f"- actionability: {row.get('actionability')}")
            lines.append(f"- monitor_priority: {row.get('monitor_priority')}")
            lines.append(f"- execution_priority: {row.get('execution_priority')}")
            lines.append(f"- execution_quality_label: {row.get('execution_quality_label')}")
            lines.append(f"- score_target: {_format_float(row.get('score_target'))}")
            if row.get("research_score_target") is not None:
                lines.append(f"- research_score_target: {_format_float(row.get('research_score_target'))}")
            lines.append(f"- preferred_entry_mode: {row.get('preferred_entry_mode')}")
            lines.append(f"- why_now: {row.get('why_now')}")
            lines.append(f"- suggested_action: {row.get('suggested_action')}")
            lines.append(f"- historical_summary: {row.get('historical_summary') or 'n/a'}")
            lines.append(f"- execution_note: {row.get('execution_note') or 'n/a'}")
            lines.append("")

    lines.append("## Catalyst Theme Frontier Priority")
    catalyst_theme_frontier_priority = board.get("catalyst_theme_frontier_priority") or {}
    promoted_shadow_watch = catalyst_theme_frontier_priority.get("promoted_shadow_watch") or []
    if not catalyst_theme_frontier_priority:
        lines.append("- none")
        lines.append("")
    else:
        lines.append(f"- status: {catalyst_theme_frontier_priority.get('status')}")
        lines.append(f"- recommended_variant_name: {catalyst_theme_frontier_priority.get('recommended_variant_name') or 'n/a'}")
        lines.append(f"- promoted_shadow_count: {catalyst_theme_frontier_priority.get('promoted_shadow_count')}")
        lines.append(f"- promoted_tickers: {', '.join(catalyst_theme_frontier_priority.get('promoted_tickers') or []) or 'none'}")
        lines.append(f"- recommended_relaxation_cost: {_format_float(catalyst_theme_frontier_priority.get('recommended_relaxation_cost'))}")
        lines.append(f"- recommendation: {catalyst_theme_frontier_priority.get('recommendation') or 'n/a'}")
        lines.append(f"- frontier_markdown_path: {catalyst_theme_frontier_priority.get('markdown_path') or 'n/a'}")
        lines.append("")
        if not promoted_shadow_watch:
            lines.append("- promoted_shadow_watch: none")
            lines.append("")
        else:
            for index, item in enumerate(promoted_shadow_watch, start=1):
                threshold_shortfalls = dict(item.get("threshold_shortfalls") or {})
                lines.append(f"### {index}. {item.get('ticker')}")
                lines.append("- lane: catalyst_theme_frontier_priority")
                lines.append("- actionability: research_followup_priority")
                lines.append(f"- candidate_score: {_format_float(item.get('candidate_score'))}")
                lines.append(f"- filter_reason: {item.get('filter_reason') or 'n/a'}")
                lines.append(f"- total_shortfall: {_format_float(item.get('total_shortfall'))}")
                lines.append(f"- failed_threshold_count: {item.get('failed_threshold_count')}")
                lines.append(f"- preferred_entry_mode: {item.get('preferred_entry_mode')}")
                lines.append(f"- suggested_action: {item.get('promotion_trigger') or '只做研究跟踪，不进入当日 BTST 交易名单。'}")
                lines.append(f"- top_reasons: {', '.join(item.get('top_reasons') or []) or 'n/a'}")
                lines.append(f"- positive_tags: {', '.join(item.get('positive_tags') or []) or 'n/a'}")
                lines.append(
                    "- threshold_shortfalls: "
                    + (
                        ", ".join(f"{key}={_format_float(value)}" for key, value in threshold_shortfalls.items())
                        if threshold_shortfalls
                        else "none"
                    )
                )
                lines.append(
                    "- key_metrics: "
                    + ", ".join(
                        [
                            f"breakout={_format_float((item.get('metrics') or {}).get('breakout_freshness'))}",
                            f"trend={_format_float((item.get('metrics') or {}).get('trend_acceleration'))}",
                            f"close={_format_float((item.get('metrics') or {}).get('close_strength'))}",
                            f"sector={_format_float((item.get('metrics') or {}).get('sector_resonance'))}",
                            f"catalyst={_format_float((item.get('metrics') or {}).get('catalyst_freshness'))}",
                        ]
                    )
                )
                lines.append("")

    lines.append("## Catalyst Theme Shadow Watch")
    catalyst_theme_shadow_watch = board.get("catalyst_theme_shadow_watch") or []
    if not catalyst_theme_shadow_watch:
        lines.append("- none")
        lines.append("")
    else:
        for index, item in enumerate(catalyst_theme_shadow_watch, start=1):
            threshold_shortfalls = dict(item.get("threshold_shortfalls") or {})
            lines.append(f"### {index}. {item.get('ticker')}")
            lines.append("- lane: catalyst_theme_shadow_watch")
            lines.append("- actionability: research_followup_only")
            lines.append(f"- candidate_score: {_format_float(item.get('candidate_score'))}")
            lines.append(f"- filter_reason: {item.get('filter_reason') or 'n/a'}")
            lines.append(f"- total_shortfall: {_format_float(item.get('total_shortfall'))}")
            lines.append(f"- failed_threshold_count: {item.get('failed_threshold_count')}")
            lines.append(f"- preferred_entry_mode: {item.get('preferred_entry_mode')}")
            lines.append(f"- suggested_action: {item.get('promotion_trigger') or '只做研究跟踪，不进入当日 BTST 交易名单。'}")
            lines.append(f"- top_reasons: {', '.join(item.get('top_reasons') or []) or 'n/a'}")
            lines.append(f"- positive_tags: {', '.join(item.get('positive_tags') or []) or 'n/a'}")
            lines.append(
                "- threshold_shortfalls: "
                + (
                    ", ".join(f"{key}={_format_float(value)}" for key, value in threshold_shortfalls.items())
                    if threshold_shortfalls
                    else "none"
                )
            )
            lines.append(
                "- key_metrics: "
                + ", ".join(
                    [
                        f"breakout={_format_float((item.get('metrics') or {}).get('breakout_freshness'))}",
                        f"trend={_format_float((item.get('metrics') or {}).get('trend_acceleration'))}",
                        f"close={_format_float((item.get('metrics') or {}).get('close_strength'))}",
                        f"sector={_format_float((item.get('metrics') or {}).get('sector_resonance'))}",
                        f"catalyst={_format_float((item.get('metrics') or {}).get('catalyst_freshness'))}",
                    ]
                )
            )
            lines.append("")

    lines.append("## Guardrails")
    for item in board.get("global_guardrails") or []:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Source Paths")
    source_paths = board.get("source_paths") or {}
    lines.append(f"- report_dir: {source_paths.get('report_dir')}")
    lines.append(f"- snapshot_path: {source_paths.get('snapshot_path')}")
    lines.append(f"- session_summary_path: {source_paths.get('session_summary_path')}")
    return "\n".join(lines) + "\n"


def _build_output_file_stem(prefix: str, trade_date: str | None, next_trade_date: str | None) -> str:
    compact_trade_date = _compact_trade_date(trade_date) or "unknown"
    compact_next_trade_date = _compact_trade_date(next_trade_date) or "unknown"
    return f"{prefix}_{compact_trade_date}_for_{compact_next_trade_date}"


def generate_btst_next_day_trade_brief_artifacts(
    input_path: str | Path,
    output_dir: str | Path,
    trade_date: str | None = None,
    next_trade_date: str | None = None,
    file_stem: str | None = None,
) -> dict[str, Any]:
    analysis = analyze_btst_next_day_trade_brief(input_path=input_path, trade_date=trade_date, next_trade_date=next_trade_date)
    resolved_output_dir = Path(output_dir).expanduser().resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    stem = file_stem or _build_output_file_stem("btst_next_day_trade_brief", analysis.get("trade_date"), analysis.get("next_trade_date"))
    output_json = resolved_output_dir / f"{stem}.json"
    output_md = resolved_output_dir / f"{stem}.md"
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_next_day_trade_brief_markdown(analysis), encoding="utf-8")
    return {
        "analysis": analysis,
        "json_path": str(output_json),
        "markdown_path": str(output_md),
    }


def generate_btst_premarket_execution_card_artifacts(
    input_path: str | Path | dict[str, Any],
    output_dir: str | Path,
    trade_date: str | None = None,
    next_trade_date: str | None = None,
    file_stem: str | None = None,
) -> dict[str, Any]:
    card = analyze_btst_premarket_execution_card(input_path=input_path, trade_date=trade_date, next_trade_date=next_trade_date)
    resolved_output_dir = Path(output_dir).expanduser().resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    stem = file_stem or _build_output_file_stem("btst_premarket_execution_card", card.get("trade_date"), card.get("next_trade_date"))
    output_json = resolved_output_dir / f"{stem}.json"
    output_md = resolved_output_dir / f"{stem}.md"
    output_json.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_premarket_execution_card_markdown(card), encoding="utf-8")
    return {
        "analysis": card,
        "json_path": str(output_json),
        "markdown_path": str(output_md),
    }


def generate_btst_opening_watch_card_artifacts(
    input_path: str | Path | dict[str, Any],
    output_dir: str | Path,
    trade_date: str | None = None,
    next_trade_date: str | None = None,
    file_stem: str | None = None,
) -> dict[str, Any]:
    card = analyze_btst_opening_watch_card(input_path=input_path, trade_date=trade_date, next_trade_date=next_trade_date)
    resolved_output_dir = Path(output_dir).expanduser().resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    stem = file_stem or f"btst_opening_watch_card_{_compact_trade_date(card.get('next_trade_date')) or 'unknown'}"
    output_json = resolved_output_dir / f"{stem}.json"
    output_md = resolved_output_dir / f"{stem}.md"
    output_json.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_opening_watch_card_markdown(card), encoding="utf-8")
    return {
        "analysis": card,
        "json_path": str(output_json),
        "markdown_path": str(output_md),
    }


def generate_btst_next_day_priority_board_artifacts(
    input_path: str | Path | dict[str, Any],
    output_dir: str | Path,
    trade_date: str | None = None,
    next_trade_date: str | None = None,
    file_stem: str | None = None,
) -> dict[str, Any]:
    board = analyze_btst_next_day_priority_board(input_path=input_path, trade_date=trade_date, next_trade_date=next_trade_date)
    resolved_output_dir = Path(output_dir).expanduser().resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    stem = file_stem or f"btst_next_day_priority_board_{_compact_trade_date(board.get('next_trade_date')) or 'unknown'}"
    output_json = resolved_output_dir / f"{stem}.json"
    output_md = resolved_output_dir / f"{stem}.md"
    output_json.write_text(json.dumps(board, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_next_day_priority_board_markdown(board), encoding="utf-8")
    return {
        "analysis": board,
        "json_path": str(output_json),
        "markdown_path": str(output_md),
    }


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
    resolved_report_dir = Path(report_dir).expanduser().resolve()
    summary_path = resolved_report_dir / "session_summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"session_summary.json not found under: {resolved_report_dir}")

    summary = _load_json(summary_path)
    resolved_trade_date, resolved_next_trade_date = _resolve_followup_trade_dates(
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        brief_json_path=brief_json_path,
        card_json_path=card_json_path,
    )
    brief_json_latest = _sync_text_artifact_alias(brief_json_path, resolved_report_dir / "btst_next_day_trade_brief_latest.json")
    brief_markdown_latest = _sync_text_artifact_alias(brief_markdown_path, resolved_report_dir / "btst_next_day_trade_brief_latest.md")
    execution_card_json_latest = _sync_text_artifact_alias(card_json_path, resolved_report_dir / "btst_premarket_execution_card_latest.json")
    execution_card_markdown_latest = _sync_text_artifact_alias(card_markdown_path, resolved_report_dir / "btst_premarket_execution_card_latest.md")
    opening_watch_card_json_latest = _sync_text_artifact_alias(opening_card_json_path, resolved_report_dir / "btst_opening_watch_card_latest.json")
    opening_watch_card_markdown_latest = _sync_text_artifact_alias(opening_card_markdown_path, resolved_report_dir / "btst_opening_watch_card_latest.md")
    priority_board_json_latest = _sync_text_artifact_alias(priority_board_json_path, resolved_report_dir / "btst_next_day_priority_board_latest.json")
    priority_board_markdown_latest = _sync_text_artifact_alias(priority_board_markdown_path, resolved_report_dir / "btst_next_day_priority_board_latest.md")
    followup_manifest = {
        "trade_date": resolved_trade_date,
        "next_trade_date": resolved_next_trade_date,
        "brief_json": brief_json_latest,
        "brief_markdown": brief_markdown_latest,
        "execution_card_json": execution_card_json_latest,
        "execution_card_markdown": execution_card_markdown_latest,
        "opening_watch_card_json": opening_watch_card_json_latest,
        "opening_watch_card_markdown": opening_watch_card_markdown_latest,
        "priority_board_json": priority_board_json_latest,
        "priority_board_markdown": priority_board_markdown_latest,
    }
    summary["btst_followup"] = followup_manifest
    artifacts = dict(summary.get("artifacts") or {})
    artifacts.update(
        {
            "btst_next_day_trade_brief_json": followup_manifest["brief_json"],
            "btst_next_day_trade_brief_markdown": followup_manifest["brief_markdown"],
            "btst_premarket_execution_card_json": followup_manifest["execution_card_json"],
            "btst_premarket_execution_card_markdown": followup_manifest["execution_card_markdown"],
            "btst_opening_watch_card_json": followup_manifest["opening_watch_card_json"],
            "btst_opening_watch_card_markdown": followup_manifest["opening_watch_card_markdown"],
            "btst_next_day_priority_board_json": followup_manifest["priority_board_json"],
            "btst_next_day_priority_board_markdown": followup_manifest["priority_board_markdown"],
        }
    )
    summary["artifacts"] = artifacts
    _write_json(summary_path, summary)
    return followup_manifest


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
    resolved_report_dir = Path(report_dir).expanduser().resolve()
    resolved_trade_date = _normalize_trade_date(trade_date)
    resolved_next_trade_date = _normalize_trade_date(next_trade_date) or infer_next_trade_date(resolved_trade_date)
    brief_result = generate_btst_next_day_trade_brief_artifacts(
        input_path=resolved_report_dir,
        output_dir=resolved_report_dir,
        trade_date=resolved_trade_date,
        next_trade_date=resolved_next_trade_date,
        file_stem=brief_file_stem,
    )

    if not resolved_trade_date:
        resolved_trade_date = _normalize_trade_date(brief_result["analysis"].get("trade_date"))

    if not resolved_next_trade_date:
        resolved_next_trade_date = _normalize_trade_date(brief_result["analysis"].get("next_trade_date")) or infer_next_trade_date(resolved_trade_date)
        if resolved_next_trade_date:
            brief_result = generate_btst_next_day_trade_brief_artifacts(
                input_path=resolved_report_dir,
                output_dir=resolved_report_dir,
                trade_date=resolved_trade_date,
                next_trade_date=resolved_next_trade_date,
                file_stem=brief_file_stem,
            )

    card_result = generate_btst_premarket_execution_card_artifacts(
        input_path=brief_result["analysis"],
        output_dir=resolved_report_dir,
        trade_date=resolved_trade_date,
        next_trade_date=resolved_next_trade_date,
        file_stem=card_file_stem,
    )
    opening_card_result = generate_btst_opening_watch_card_artifacts(
        input_path=brief_result["analysis"],
        output_dir=resolved_report_dir,
        trade_date=resolved_trade_date,
        next_trade_date=resolved_next_trade_date,
        file_stem=opening_card_file_stem or f"btst_opening_watch_card_{_compact_trade_date(resolved_next_trade_date) or 'unknown'}",
    )
    priority_board_result = generate_btst_next_day_priority_board_artifacts(
        input_path=brief_result["analysis"],
        output_dir=resolved_report_dir,
        trade_date=resolved_trade_date,
        next_trade_date=resolved_next_trade_date,
        file_stem=priority_board_file_stem or f"btst_next_day_priority_board_{_compact_trade_date(resolved_next_trade_date) or 'unknown'}",
    )
    followup_manifest = register_btst_followup_artifacts(
        resolved_report_dir,
        trade_date=resolved_trade_date,
        next_trade_date=resolved_next_trade_date,
        brief_json_path=brief_result["json_path"],
        brief_markdown_path=brief_result["markdown_path"],
        card_json_path=card_result["json_path"],
        card_markdown_path=card_result["markdown_path"],
        opening_card_json_path=opening_card_result["json_path"],
        opening_card_markdown_path=opening_card_result["markdown_path"],
        priority_board_json_path=priority_board_result["json_path"],
        priority_board_markdown_path=priority_board_result["markdown_path"],
    )
    return {
        "analysis": brief_result["analysis"],
        "execution_card": card_result["analysis"],
        "opening_watch_card": opening_card_result["analysis"],
        "priority_board": priority_board_result["analysis"],
        **followup_manifest,
    }
