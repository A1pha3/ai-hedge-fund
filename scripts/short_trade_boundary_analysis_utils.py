from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

import pandas as pd

from src.execution.daily_pipeline import (
    SHORT_TRADE_BOUNDARY_BREAKOUT_MIN,
    SHORT_TRADE_BOUNDARY_CANDIDATE_SCORE_MIN,
    SHORT_TRADE_BOUNDARY_CATALYST_MIN,
    SHORT_TRADE_BOUNDARY_TREND_MIN,
    SHORT_TRADE_BOUNDARY_VOLUME_MIN,
)
from src.targets.short_trade_target import build_short_trade_target_snapshot_from_entry
from src.tools.api import get_price_data, prices_to_df
from src.tools.akshare_api import get_prices_robust


REPLAY_INPUT_FILENAME = "selection_target_replay_input.json"
BOUNDARY_METRIC_KEYS = (
    "breakout_freshness",
    "trend_acceleration",
    "volume_expansion_quality",
    "catalyst_freshness",
    "close_strength",
    "candidate_score",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_candidate_sources(raw: str | None) -> set[str]:
    if raw is None or not str(raw).strip():
        return set()
    return {token.strip() for token in str(raw).split(",") if token.strip()}


def parse_float_grid(raw: str | None, *, default: float) -> list[float]:
    values: list[float] = [round(float(default), 4)]
    if raw is None or not str(raw).strip():
        return values
    for token in str(raw).split(","):
        stripped = token.strip()
        if not stripped:
            continue
        value = round(float(stripped), 4)
        if value not in values:
            values.append(value)
    return values


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def summarize(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(mean(values), 4),
    }


def iter_replay_inputs(report_dir: Path):
    selection_root = report_dir / "selection_artifacts"
    if not selection_root.exists():
        return
    for day_dir in sorted(path for path in selection_root.iterdir() if path.is_dir()):
        replay_input_path = day_dir / REPLAY_INPUT_FILENAME
        if replay_input_path.exists():
            yield replay_input_path, load_json(replay_input_path)


def normalize_price_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    normalized = frame.copy()
    if not isinstance(normalized.index, pd.DatetimeIndex):
        normalized.index = pd.to_datetime(normalized.index)
    normalized = normalized.sort_index()
    normalized.columns = [str(column).lower() for column in normalized.columns]
    return normalized


def extract_next_day_outcome(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], pd.DataFrame]) -> dict[str, Any]:
    cache_key = (ticker, trade_date)
    frame = price_cache.get(cache_key)
    if frame is None:
        end_date = (pd.Timestamp(trade_date) + pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        try:
            frame = normalize_price_frame(get_price_data(ticker, trade_date, end_date))
        except Exception:
            try:
                frame = normalize_price_frame(prices_to_df(get_prices_robust(ticker, trade_date, end_date, use_mock_on_fail=False)))
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
    trade_close = safe_float(trade_row.get("close"))
    next_open = safe_float(next_row.get("open"))
    next_high = safe_float(next_row.get("high"))
    next_close = safe_float(next_row.get("close"))
    if trade_close is None or trade_close <= 0 or next_open is None or next_high is None or next_close is None:
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


def compute_candidate_score(metrics: dict[str, Any]) -> float:
    return round(
        (0.30 * float(metrics.get("breakout_freshness", 0.0) or 0.0))
        + (0.25 * float(metrics.get("trend_acceleration", 0.0) or 0.0))
        + (0.20 * float(metrics.get("volume_expansion_quality", 0.0) or 0.0))
        + (0.15 * float(metrics.get("catalyst_freshness", 0.0) or 0.0))
        + (0.10 * float(metrics.get("close_strength", 0.0) or 0.0)),
        4,
    )


def resolve_boundary_metrics(*, trade_date: str, entry: dict[str, Any]) -> dict[str, Any]:
    provided_metrics = dict(entry.get("short_trade_boundary_metrics") or {})
    if provided_metrics and all(key in provided_metrics for key in BOUNDARY_METRIC_KEYS if key != "candidate_score"):
        normalized = {key: round(float(provided_metrics.get(key, 0.0) or 0.0), 4) for key in BOUNDARY_METRIC_KEYS if key != "candidate_score"}
        normalized["candidate_score"] = round(float(provided_metrics.get("candidate_score") or compute_candidate_score(normalized)), 4)
        normalized["gate_status"] = dict(entry.get("short_trade_boundary_gate_status") or provided_metrics.get("gate_status") or {"data": "pass", "structural": "pass"})
        normalized["blockers"] = list(entry.get("short_trade_boundary_blockers") or provided_metrics.get("blockers") or [])
        return normalized

    snapshot = build_short_trade_target_snapshot_from_entry(trade_date=trade_date, entry=entry)
    metrics = {
        "breakout_freshness": round(float(snapshot.get("breakout_freshness", 0.0) or 0.0), 4),
        "trend_acceleration": round(float(snapshot.get("trend_acceleration", 0.0) or 0.0), 4),
        "volume_expansion_quality": round(float(snapshot.get("volume_expansion_quality", 0.0) or 0.0), 4),
        "catalyst_freshness": round(float(snapshot.get("catalyst_freshness", 0.0) or 0.0), 4),
        "close_strength": round(float(snapshot.get("close_strength", 0.0) or 0.0), 4),
        "candidate_score": round(float(compute_candidate_score(snapshot)), 4),
        "gate_status": dict(snapshot.get("gate_status") or {}),
        "blockers": list(snapshot.get("blockers") or []),
    }
    return metrics


def default_boundary_thresholds() -> dict[str, float]:
    return {
        "candidate_score_min": round(float(SHORT_TRADE_BOUNDARY_CANDIDATE_SCORE_MIN), 4),
        "breakout_freshness_min": round(float(SHORT_TRADE_BOUNDARY_BREAKOUT_MIN), 4),
        "trend_acceleration_min": round(float(SHORT_TRADE_BOUNDARY_TREND_MIN), 4),
        "volume_expansion_quality_min": round(float(SHORT_TRADE_BOUNDARY_VOLUME_MIN), 4),
        "catalyst_freshness_min": round(float(SHORT_TRADE_BOUNDARY_CATALYST_MIN), 4),
    }


def classify_boundary_candidate(metrics: dict[str, Any], thresholds: dict[str, float]) -> dict[str, Any]:
    gate_status = dict(metrics.get("gate_status") or {})
    blockers = [str(value) for value in list(metrics.get("blockers") or []) if str(value).strip()]
    if str(gate_status.get("data") or "pass") != "pass":
        return {
            "qualified": False,
            "primary_reason": "metric_data_fail",
            "failed_thresholds": {},
            "failed_threshold_count": 0,
            "total_shortfall": None,
        }
    if str(gate_status.get("structural") or "pass") == "fail" or blockers:
        return {
            "qualified": False,
            "primary_reason": "structural_prefilter_fail",
            "failed_thresholds": {},
            "failed_threshold_count": 0,
            "total_shortfall": None,
        }

    threshold_order = [
        ("breakout_freshness", "breakout_freshness_min", "breakout_freshness_below_short_trade_boundary_floor"),
        ("trend_acceleration", "trend_acceleration_min", "trend_acceleration_below_short_trade_boundary_floor"),
        ("volume_expansion_quality", "volume_expansion_quality_min", "volume_expansion_below_short_trade_boundary_floor"),
        ("catalyst_freshness", "catalyst_freshness_min", "catalyst_freshness_below_short_trade_boundary_floor"),
        ("candidate_score", "candidate_score_min", "candidate_score_below_short_trade_boundary_floor"),
    ]
    failed_thresholds: dict[str, float] = {}
    primary_reason = "qualified"
    for metric_key, threshold_key, reason in threshold_order:
        actual_value = float(metrics.get(metric_key, 0.0) or 0.0)
        threshold_value = float(thresholds.get(threshold_key, 0.0) or 0.0)
        shortfall = round(threshold_value - actual_value, 4)
        if shortfall > 0:
            failed_thresholds[metric_key] = shortfall
            if primary_reason == "qualified":
                primary_reason = reason
    if failed_thresholds:
        return {
            "qualified": False,
            "primary_reason": primary_reason,
            "failed_thresholds": failed_thresholds,
            "failed_threshold_count": len(failed_thresholds),
            "total_shortfall": round(sum(failed_thresholds.values()), 4),
        }
    return {
        "qualified": True,
        "primary_reason": "short_trade_prequalified",
        "failed_thresholds": {},
        "failed_threshold_count": 0,
        "total_shortfall": 0.0,
    }


def collect_candidate_rows(
    report_dir: str | Path,
    *,
    candidate_sources: set[str] | None = None,
    next_high_hit_threshold: float = 0.02,
) -> dict[str, Any]:
    report_path = Path(report_dir).expanduser().resolve()
    active_sources = {str(value) for value in (candidate_sources or set()) if str(value).strip()}
    rows: list[dict[str, Any]] = []
    price_cache: dict[tuple[str, str], pd.DataFrame] = {}
    data_status_counts: Counter[str] = Counter()
    candidate_source_counts: Counter[str] = Counter()

    for _, replay_input in iter_replay_inputs(report_path) or []:
        trade_date = str(replay_input.get("trade_date") or "")
        for entry in list(replay_input.get("supplemental_short_trade_entries") or []):
            candidate_source = str(entry.get("candidate_source") or "unknown")
            if active_sources and candidate_source not in active_sources:
                continue
            metrics = resolve_boundary_metrics(trade_date=trade_date, entry=dict(entry))
            outcome = extract_next_day_outcome(str(entry.get("ticker") or ""), trade_date, price_cache)
            data_status = str(outcome.get("data_status") or "unknown")
            data_status_counts[data_status] += 1
            candidate_source_counts[candidate_source] += 1
            row = {
                "trade_date": trade_date,
                "ticker": str(entry.get("ticker") or ""),
                "candidate_source": candidate_source,
                "score_b": round_or_none(safe_float(entry.get("score_b"))),
                **{key: metrics.get(key) for key in BOUNDARY_METRIC_KEYS},
                "gate_status": dict(metrics.get("gate_status") or {}),
                "blockers": list(metrics.get("blockers") or []),
                **outcome,
            }
            row["next_high_hit_threshold"] = round(float(next_high_hit_threshold), 4)
            rows.append(row)

    return {
        "report_dir": str(report_path),
        "candidate_sources_filter": sorted(active_sources),
        "rows": rows,
        "data_status_counts": dict(data_status_counts.most_common()),
        "candidate_source_counts": dict(candidate_source_counts.most_common()),
        "next_high_hit_threshold": round(float(next_high_hit_threshold), 4),
    }