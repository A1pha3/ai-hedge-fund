from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

import pandas as pd

from src.backtesting.walk_forward import WALK_FORWARD_PRESETS, build_walk_forward_windows
from src.project_env import load_project_dotenv
from src.targets.short_trade_forward_label_helpers import build_short_trade_forward_labels
from src.tools.api import get_price_data, prices_to_df
from src.tools.akshare_api import get_prices_robust


load_project_dotenv()


REPLAY_INPUT_FILENAME = "selection_target_replay_input.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_candidate_sources(raw: str | None) -> set[str]:
    if raw is None or not str(raw).strip():
        return set()
    return {token.strip() for token in str(raw).split(",") if token.strip()}


def _parse_tickers(raw: str | None) -> set[str]:
    if raw is None or not str(raw).strip():
        return set()
    return {token.strip() for token in str(raw).split(",") if token.strip()}


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric):
        return default
    return numeric


def _round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _resolve_candidate_metrics(entry: dict[str, Any]) -> dict[str, Any]:
    boundary_metrics = dict(entry.get("short_trade_boundary_metrics") or {})
    catalyst_metrics = dict(entry.get("catalyst_theme_metrics") or {})
    if boundary_metrics:
        return boundary_metrics
    return catalyst_metrics


def _resolve_regime_gate(entry: dict[str, Any]) -> str:
    historical_prior = dict(entry.get("historical_prior") or {})
    if str(historical_prior.get("btst_regime_gate") or "").strip():
        return str(historical_prior.get("btst_regime_gate")).strip()
    market_state = dict(entry.get("market_state") or {})
    nested_gate = market_state.get("btst_regime_gate")
    if isinstance(nested_gate, dict) and str(nested_gate.get("gate") or "").strip():
        return str(nested_gate.get("gate")).strip()
    if str(market_state.get("btst_regime_gate") or "").strip():
        return str(market_state.get("btst_regime_gate")).strip()
    return "unknown"


def _summarize(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(mean(values), 4),
    }


def _classify_board(ticker: str) -> str:
    """Classify ticker by board: star_market (688xxx), chinext (300xxx), or main_board."""
    ticker_str = str(ticker).strip()
    if ticker_str.startswith("688"):
        return "star_market"
    if ticker_str.startswith("300"):
        return "chinext"
    return "main_board"


def _iter_replay_inputs(report_dir: Path):
    selection_root = report_dir / "selection_artifacts"
    for day_dir in sorted(path for path in selection_root.iterdir() if path.is_dir()):
        replay_input_path = day_dir / REPLAY_INPUT_FILENAME
        if replay_input_path.exists():
            yield replay_input_path, _load_json(replay_input_path)


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
    trade_close = _safe_float(trade_row.get("close"))
    next_open = _safe_float(next_row.get("open"))
    next_high = _safe_float(next_row.get("high"))
    next_close = _safe_float(next_row.get("close"))
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
        **build_short_trade_forward_labels(
            entry_price=next_open,
            forward_days=[
                {
                    "high": _safe_float(forward_row.get("high")),
                    "close": _safe_float(forward_row.get("close")),
                }
                for _, forward_row in next_day.iloc[:9].iterrows()
                if _safe_float(forward_row.get("high")) is not None and _safe_float(forward_row.get("close")) is not None
            ],
        ),
    }


def _compute_walk_forward_validation(
    candidate_rows: list[dict[str, Any]],
    preset: str,
    window_mode: str,
    next_high_hit_threshold: float,
) -> dict[str, Any]:
    """Compute walk-forward validation metrics using existing walk_forward.py helpers."""
    # Validate preset and window_mode explicitly upfront
    if preset not in WALK_FORWARD_PRESETS:
        raise ValueError(f"Unknown walk-forward preset: {preset}. Valid presets: {', '.join(WALK_FORWARD_PRESETS.keys())}")
    
    valid_window_modes = {"rolling", "expanding"}
    if window_mode not in valid_window_modes:
        raise ValueError(f"Invalid walk-forward window mode: {window_mode}. Valid modes: {', '.join(sorted(valid_window_modes))}")
    
    ok_rows = [row for row in candidate_rows if row.get("data_status") == "ok" and row.get("trade_date")]
    
    if not ok_rows:
        return {
            "preset": preset,
            "window_mode": window_mode,
            "summary": {
                "window_count": 0,
                "candidate_count": 0,
                "next_high_return_mean": None,
                "next_close_return_mean": None,
                "next_high_hit_rate_at_threshold": None,
                "next_close_positive_rate": None,
                "fast_confirm_rate": None,
                "retention_rate": None,
                "tail_20_rate": None,
            },
            "windows": [],
        }

    trade_dates = sorted(row["trade_date"] for row in ok_rows)
    start_date = trade_dates[0]
    end_date = trade_dates[-1]
    
    preset_config = WALK_FORWARD_PRESETS[preset]
    
    windows = build_walk_forward_windows(
        start_date=start_date,
        end_date=end_date,
        train_months=preset_config["train_months"],
        test_months=preset_config["test_months"],
        step_months=preset_config["step_months"],
        max_test_trading_days=preset_config.get("max_test_trading_days"),
        window_mode=window_mode,
    )

    window_metrics: list[dict[str, Any]] = []
    all_window_candidates: list[dict[str, Any]] = []

    for window in windows:
        test_start = pd.Timestamp(window.test_start)
        test_end = pd.Timestamp(window.test_end)
        
        window_rows = [
            row
            for row in ok_rows
            if test_start <= pd.Timestamp(row["trade_date"]) <= test_end
        ]
        
        if not window_rows:
            continue
        
        all_window_candidates.extend(window_rows)
        
        high_returns = [float(row["next_high_return"]) for row in window_rows]
        close_returns = [float(row["next_close_return"]) for row in window_rows]
        high_hits = sum(1 for value in high_returns if value >= next_high_hit_threshold)
        close_positive = sum(1 for value in close_returns if value > 0)
        fast_confirm_hits = sum(1 for row in window_rows if bool(row.get("label_fast_confirm")))
        retention_hits = sum(1 for row in window_rows if bool(row.get("label_retention")))
        tail_hits = sum(1 for row in window_rows if bool(row.get("label_tail_20")))
        count = len(window_rows)

        window_metrics.append({
            "train_start": window.train_start,
            "train_end": window.train_end,
            "test_start": window.test_start,
            "test_end": window.test_end,
            "count": count,
            "next_high_return_mean": round(mean(high_returns), 4) if high_returns else None,
            "next_close_return_mean": round(mean(close_returns), 4) if close_returns else None,
            "next_high_hit_rate_at_threshold": None if count == 0 else round(high_hits / count, 4),
            "next_close_positive_rate": None if count == 0 else round(close_positive / count, 4),
            "fast_confirm_rate": None if count == 0 else round(fast_confirm_hits / count, 4),
            "retention_rate": None if count == 0 else round(retention_hits / count, 4),
            "tail_20_rate": None if count == 0 else round(tail_hits / count, 4),
        })

    if all_window_candidates:
        all_high_returns = [float(row["next_high_return"]) for row in all_window_candidates]
        all_close_returns = [float(row["next_close_return"]) for row in all_window_candidates]
        all_high_hits = sum(1 for value in all_high_returns if value >= next_high_hit_threshold)
        all_close_positive = sum(1 for value in all_close_returns if value > 0)
        all_fast_confirm = sum(1 for row in all_window_candidates if bool(row.get("label_fast_confirm")))
        all_retention = sum(1 for row in all_window_candidates if bool(row.get("label_retention")))
        all_tail = sum(1 for row in all_window_candidates if bool(row.get("label_tail_20")))
        total_count = len(all_window_candidates)

        summary = {
            "window_count": len(window_metrics),
            "candidate_count": total_count,
            "next_high_return_mean": round(mean(all_high_returns), 4) if all_high_returns else None,
            "next_close_return_mean": round(mean(all_close_returns), 4) if all_close_returns else None,
            "next_high_hit_rate_at_threshold": None if total_count == 0 else round(all_high_hits / total_count, 4),
            "next_close_positive_rate": None if total_count == 0 else round(all_close_positive / total_count, 4),
            "fast_confirm_rate": None if total_count == 0 else round(all_fast_confirm / total_count, 4),
            "retention_rate": None if total_count == 0 else round(all_retention / total_count, 4),
            "tail_20_rate": None if total_count == 0 else round(all_tail / total_count, 4),
        }
    else:
        summary = {
            "window_count": 0,
            "candidate_count": 0,
            "next_high_return_mean": None,
            "next_close_return_mean": None,
            "next_high_hit_rate_at_threshold": None,
            "next_close_positive_rate": None,
            "fast_confirm_rate": None,
            "retention_rate": None,
            "tail_20_rate": None,
        }

    return {
        "preset": preset,
        "window_mode": window_mode,
        "summary": summary,
        "windows": window_metrics,
    }


def render_pre_layer_short_trade_outcomes_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Pre-Layer C Short Trade Candidate Outcome Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- candidate_sources_filter: {analysis['candidate_sources_filter']}")
    lines.append(f"- tickers_filter: {analysis['tickers_filter']}")
    lines.append(f"- candidate_count: {analysis['candidate_count']}")
    lines.append(f"- data_status_counts: {analysis['data_status_counts']}")
    lines.append(f"- candidate_source_counts: {analysis['candidate_source_counts']}")
    lines.append("")
    lines.append("## Returns Summary")
    lines.append(f"- next_open_return: {analysis['next_open_return_distribution']}")
    lines.append(f"- next_high_return: {analysis['next_high_return_distribution']}")
    lines.append(f"- next_close_return: {analysis['next_close_return_distribution']}")
    lines.append("")
    lines.append("## Hit Rates")
    lines.append(f"- next_high_hit_rate_at_threshold: {analysis['next_high_hit_rate_at_threshold']}")
    lines.append(f"- next_close_positive_rate: {analysis['next_close_positive_rate']}")
    lines.append(f"- fast_confirm_rate: {analysis.get('fast_confirm_rate')}")
    lines.append(f"- retention_rate: {analysis.get('retention_rate')}")
    lines.append(f"- tail_20_rate: {analysis.get('tail_20_rate')}")
    lines.append("")
    lines.append("## Source Breakdown")
    for source, summary in analysis["source_breakdown"].items():
        lines.append(
            f"- {source}: count={summary['count']}, next_high_mean={summary['next_high_return_mean']}, next_close_mean={summary['next_close_return_mean']}, high_hit_rate={summary['next_high_hit_rate_at_threshold']}, close_positive_rate={summary['next_close_positive_rate']}"
        )
    lines.append("")
    lines.append("## Regime Gate Breakdown")
    gate_breakdown = analysis.get("gate_breakdown", {})
    if gate_breakdown:
        for gate, summary in gate_breakdown.items():
            lines.append(
                f"- {gate}: count={summary['count']}, next_high_mean={summary['next_high_return_mean']}, next_close_mean={summary['next_close_return_mean']}, high_hit_rate={summary['next_high_hit_rate_at_threshold']}, close_positive_rate={summary['next_close_positive_rate']}, fast_confirm_rate={summary['fast_confirm_rate']}, retention_rate={summary['retention_rate']}, tail_20_rate={summary['tail_20_rate']}"
            )
    else:
        lines.append("(no regime gate data available)")
    lines.append("")
    lines.append("## Board Breakdown")
    board_breakdown = analysis.get("board_breakdown", {})
    if board_breakdown:
        for board, summary in board_breakdown.items():
            lines.append(
                f"- {board}: count={summary['count']}, next_high_mean={summary['next_high_return_mean']}, next_close_mean={summary['next_close_return_mean']}, high_hit_rate={summary['next_high_hit_rate_at_threshold']}, close_positive_rate={summary['next_close_positive_rate']}, fast_confirm_rate={summary['fast_confirm_rate']}, retention_rate={summary['retention_rate']}, tail_20_rate={summary['tail_20_rate']}"
            )
    else:
        lines.append("(no board classification data available)")
    lines.append("")
    lines.append("## Walk-Forward Validation")
    walk_forward = analysis.get("walk_forward", {})
    if walk_forward:
        lines.append(f"- preset={walk_forward.get('preset')}, window_mode={walk_forward.get('window_mode')}")
        summary = walk_forward.get("summary", {})
        window_count = summary.get('window_count', 0)
        lines.append(
            f"- summary: window_count={window_count}, candidate_count={summary.get('candidate_count')}, "
            f"next_high_mean={summary.get('next_high_return_mean')}, next_close_mean={summary.get('next_close_return_mean')}, "
            f"high_hit_rate={summary.get('next_high_hit_rate_at_threshold')}, close_positive_rate={summary.get('next_close_positive_rate')}, "
            f"fast_confirm_rate={summary.get('fast_confirm_rate')}, retention_rate={summary.get('retention_rate')}, tail_20_rate={summary.get('tail_20_rate')}"
        )
        windows = walk_forward.get("windows", [])
        if window_count == 0 or not windows:
            lines.append("(no walk-forward windows generated; insufficient date span or no qualifying candidates)")
        else:
            for window in windows:
                lines.append(
                    f"- window: train=[{window.get('train_start')} to {window.get('train_end')}], test=[{window.get('test_start')} to {window.get('test_end')}], "
                    f"count={window.get('count')}, next_high_mean={window.get('next_high_return_mean')}, next_close_mean={window.get('next_close_return_mean')}, "
                    f"high_hit_rate={window.get('next_high_hit_rate_at_threshold')}, close_positive_rate={window.get('next_close_positive_rate')}, "
                    f"fast_confirm_rate={window.get('fast_confirm_rate')}, retention_rate={window.get('retention_rate')}, tail_20_rate={window.get('tail_20_rate')}"
                )
    lines.append("")
    lines.append("## Top Cases")
    for row in analysis["top_cases"]:
        lines.append(
            f"- {row.get('trade_date')} {row.get('ticker')}: "
            f"source={row.get('candidate_source')}, "
            f"candidate_score={row.get('candidate_score')}, "
            f"data_status={row.get('data_status')}, "
            f"next_high_return={row.get('next_high_return')}, "
            f"next_close_return={row.get('next_close_return')}"
        )
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_pre_layer_short_trade_outcomes(
    report_dir: str | Path,
    *,
    candidate_sources: set[str] | None = None,
    tickers: set[str] | None = None,
    next_high_hit_threshold: float = 0.02,
    walk_forward_preset: str = "standard",
    walk_forward_window_mode: str = "rolling",
) -> dict[str, Any]:
    report_path = Path(report_dir).expanduser().resolve()
    active_sources = {str(value) for value in (candidate_sources or set()) if str(value).strip()}
    active_tickers = {str(value) for value in (tickers or set()) if str(value).strip()}
    candidate_rows: list[dict[str, Any]] = []
    price_cache: dict[tuple[str, str], pd.DataFrame] = {}
    data_status_counts: Counter[str] = Counter()
    candidate_source_counts: Counter[str] = Counter()
    source_return_buckets: dict[str, dict[str, list[float] | int]] = defaultdict(lambda: {"next_high": [], "next_close": [], "count": 0, "high_hits": 0, "close_positive": 0})
    gate_return_buckets: dict[str, dict[str, list[float] | int]] = defaultdict(
        lambda: {"next_high": [], "next_close": [], "count": 0, "high_hits": 0, "close_positive": 0, "fast_confirm_hits": 0, "retention_hits": 0, "tail_hits": 0}
    )
    board_return_buckets: dict[str, dict[str, list[float] | int]] = defaultdict(
        lambda: {"next_high": [], "next_close": [], "count": 0, "high_hits": 0, "close_positive": 0, "fast_confirm_hits": 0, "retention_hits": 0, "tail_hits": 0}
    )

    for _, replay_input in _iter_replay_inputs(report_path):
        trade_date = str(replay_input.get("trade_date") or "")
        for entry in list(replay_input.get("supplemental_short_trade_entries") or []):
            ticker = str(entry.get("ticker") or "")
            if active_tickers and ticker not in active_tickers:
                continue
            candidate_source = str(entry.get("candidate_source") or "unknown")
            if active_sources and candidate_source not in active_sources:
                continue
            metrics = _resolve_candidate_metrics(entry)
            regime_gate = _resolve_regime_gate(entry)
            outcome = _extract_next_day_outcome(ticker, trade_date, price_cache)
            data_status = str(outcome.get("data_status") or "unknown")
            data_status_counts[data_status] += 1
            candidate_source_counts[candidate_source] += 1
            row = {
                "trade_date": trade_date,
                "ticker": ticker,
                "candidate_source": candidate_source,
                "regime_gate": regime_gate,
                "candidate_score": _round_or_none(_safe_float(metrics.get("candidate_score"))),
                "breakout_freshness": _round_or_none(_safe_float(metrics.get("breakout_freshness"))),
                "trend_acceleration": _round_or_none(_safe_float(metrics.get("trend_acceleration"))),
                "volume_expansion_quality": _round_or_none(_safe_float(metrics.get("volume_expansion_quality"))),
                "catalyst_freshness": _round_or_none(_safe_float(metrics.get("catalyst_freshness"))),
                **outcome,
            }
            candidate_rows.append(row)

            if data_status != "ok":
                continue
            next_high_return = float(outcome["next_high_return"])
            next_close_return = float(outcome["next_close_return"])
            source_bucket = source_return_buckets[candidate_source]
            cast_high = source_bucket["next_high"]
            cast_close = source_bucket["next_close"]
            assert isinstance(cast_high, list) and isinstance(cast_close, list)
            cast_high.append(next_high_return)
            cast_close.append(next_close_return)
            source_bucket["count"] = int(source_bucket["count"]) + 1
            if next_high_return >= next_high_hit_threshold:
                source_bucket["high_hits"] = int(source_bucket["high_hits"]) + 1
            if next_close_return > 0:
                source_bucket["close_positive"] = int(source_bucket["close_positive"]) + 1

            gate_bucket = gate_return_buckets[regime_gate]
            gate_high = gate_bucket["next_high"]
            gate_close = gate_bucket["next_close"]
            assert isinstance(gate_high, list) and isinstance(gate_close, list)
            gate_high.append(next_high_return)
            gate_close.append(next_close_return)
            gate_bucket["count"] = int(gate_bucket["count"]) + 1
            if next_high_return >= next_high_hit_threshold:
                gate_bucket["high_hits"] = int(gate_bucket["high_hits"]) + 1
            if next_close_return > 0:
                gate_bucket["close_positive"] = int(gate_bucket["close_positive"]) + 1
            if bool(outcome.get("label_fast_confirm")):
                gate_bucket["fast_confirm_hits"] = int(gate_bucket["fast_confirm_hits"]) + 1
            if bool(outcome.get("label_retention")):
                gate_bucket["retention_hits"] = int(gate_bucket["retention_hits"]) + 1
            if bool(outcome.get("label_tail_20")):
                gate_bucket["tail_hits"] = int(gate_bucket["tail_hits"]) + 1

            board = _classify_board(ticker)
            board_bucket = board_return_buckets[board]
            board_high = board_bucket["next_high"]
            board_close = board_bucket["next_close"]
            assert isinstance(board_high, list) and isinstance(board_close, list)
            board_high.append(next_high_return)
            board_close.append(next_close_return)
            board_bucket["count"] = int(board_bucket["count"]) + 1
            if next_high_return >= next_high_hit_threshold:
                board_bucket["high_hits"] = int(board_bucket["high_hits"]) + 1
            if next_close_return > 0:
                board_bucket["close_positive"] = int(board_bucket["close_positive"]) + 1
            if bool(outcome.get("label_fast_confirm")):
                board_bucket["fast_confirm_hits"] = int(board_bucket["fast_confirm_hits"]) + 1
            if bool(outcome.get("label_retention")):
                board_bucket["retention_hits"] = int(board_bucket["retention_hits"]) + 1
            if bool(outcome.get("label_tail_20")):
                board_bucket["tail_hits"] = int(board_bucket["tail_hits"]) + 1

    ok_rows = [row for row in candidate_rows if row.get("data_status") == "ok"]
    next_open_returns = [float(row["next_open_return"]) for row in ok_rows]
    next_high_returns = [float(row["next_high_return"]) for row in ok_rows]
    next_close_returns = [float(row["next_close_return"]) for row in ok_rows]
    next_high_hits = sum(1 for value in next_high_returns if value >= next_high_hit_threshold)
    next_close_positive = sum(1 for value in next_close_returns if value > 0)
    fast_confirm_hits = sum(1 for row in ok_rows if bool(row.get("label_fast_confirm")))
    retention_hits = sum(1 for row in ok_rows if bool(row.get("label_retention")))
    tail_hits = sum(1 for row in ok_rows if bool(row.get("label_tail_20")))

    source_breakdown: dict[str, dict[str, Any]] = {}
    for source, bucket in sorted(source_return_buckets.items()):
        high_values = list(bucket["next_high"])
        close_values = list(bucket["next_close"])
        count = int(bucket["count"])
        source_breakdown[source] = {
            "count": count,
            "next_high_return_mean": round(mean(high_values), 4) if high_values else None,
            "next_close_return_mean": round(mean(close_values), 4) if close_values else None,
            "next_high_hit_rate_at_threshold": None if count == 0 else round(int(bucket["high_hits"]) / count, 4),
            "next_close_positive_rate": None if count == 0 else round(int(bucket["close_positive"]) / count, 4),
        }

    gate_breakdown: dict[str, dict[str, Any]] = {}
    for gate, bucket in sorted(gate_return_buckets.items()):
        high_values = list(bucket["next_high"])
        close_values = list(bucket["next_close"])
        count = int(bucket["count"])
        gate_breakdown[gate] = {
            "count": count,
            "next_high_return_mean": round(mean(high_values), 4) if high_values else None,
            "next_close_return_mean": round(mean(close_values), 4) if close_values else None,
            "next_high_hit_rate_at_threshold": None if count == 0 else round(int(bucket["high_hits"]) / count, 4),
            "next_close_positive_rate": None if count == 0 else round(int(bucket["close_positive"]) / count, 4),
            "fast_confirm_rate": None if count == 0 else round(int(bucket["fast_confirm_hits"]) / count, 4),
            "retention_rate": None if count == 0 else round(int(bucket["retention_hits"]) / count, 4),
            "tail_20_rate": None if count == 0 else round(int(bucket["tail_hits"]) / count, 4),
        }

    board_breakdown: dict[str, dict[str, Any]] = {}
    for board, bucket in sorted(board_return_buckets.items()):
        high_values = list(bucket["next_high"])
        close_values = list(bucket["next_close"])
        count = int(bucket["count"])
        board_breakdown[board] = {
            "count": count,
            "next_high_return_mean": round(mean(high_values), 4) if high_values else None,
            "next_close_return_mean": round(mean(close_values), 4) if close_values else None,
            "next_high_hit_rate_at_threshold": None if count == 0 else round(int(bucket["high_hits"]) / count, 4),
            "next_close_positive_rate": None if count == 0 else round(int(bucket["close_positive"]) / count, 4),
            "fast_confirm_rate": None if count == 0 else round(int(bucket["fast_confirm_hits"]) / count, 4),
            "retention_rate": None if count == 0 else round(int(bucket["retention_hits"]) / count, 4),
            "tail_20_rate": None if count == 0 else round(int(bucket["tail_hits"]) / count, 4),
        }

    walk_forward = _compute_walk_forward_validation(
        candidate_rows=candidate_rows,
        preset=walk_forward_preset,
        window_mode=walk_forward_window_mode,
        next_high_hit_threshold=next_high_hit_threshold,
    )

    candidate_rows.sort(key=lambda row: (float(row.get("next_high_return") or -999.0), str(row.get("trade_date") or ""), str(row.get("ticker") or "")), reverse=True)

    if ok_rows:
        recommendation = (
            f"当前前置短线候选共有 {len(ok_rows)} 个拿到了次日行情；next_high 命中阈值 {round(next_high_hit_threshold, 4)} 的比例为 "
            f"{round(next_high_hits / len(ok_rows), 4)}，next_close 为正的比例为 {round(next_close_positive / len(ok_rows), 4)}。"
        )
    else:
        recommendation = "当前报告里没有拿到可用次日行情的前置短线候选，先补齐价格数据后再做前置策略优化。"

    return {
        "report_dir": str(report_path),
        "candidate_sources_filter": sorted(active_sources),
        "tickers_filter": sorted(active_tickers),
        "candidate_count": len(candidate_rows),
        "data_status_counts": dict(data_status_counts.most_common()),
        "candidate_source_counts": dict(candidate_source_counts.most_common()),
        "next_open_return_distribution": _summarize(next_open_returns),
        "next_high_return_distribution": _summarize(next_high_returns),
        "next_close_return_distribution": _summarize(next_close_returns),
        "next_high_hit_threshold": round(next_high_hit_threshold, 4),
        "next_high_hit_rate_at_threshold": None if not ok_rows else round(next_high_hits / len(ok_rows), 4),
        "next_close_positive_rate": None if not ok_rows else round(next_close_positive / len(ok_rows), 4),
        "fast_confirm_rate": None if not ok_rows else round(fast_confirm_hits / len(ok_rows), 4),
        "retention_rate": None if not ok_rows else round(retention_hits / len(ok_rows), 4),
        "tail_20_rate": None if not ok_rows else round(tail_hits / len(ok_rows), 4),
        "source_breakdown": source_breakdown,
        "gate_breakdown": gate_breakdown,
        "board_breakdown": board_breakdown,
        "walk_forward": walk_forward,
        "top_cases": candidate_rows[:8],
        "rows": candidate_rows,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze next-day outcomes for pre-Layer C short-trade candidates from selection artifacts.")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--candidate-sources", default="", help="Optional comma-separated candidate_source filter")
    parser.add_argument("--tickers", default="", help="Optional comma-separated ticker filter")
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--walk-forward-preset", default="standard", help="Walk-forward preset (fast, standard, extended, seasonal)")
    parser.add_argument("--walk-forward-window-mode", default="rolling", help="Walk-forward window mode (rolling, expanding)")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_pre_layer_short_trade_outcomes(
        args.report_dir,
        candidate_sources=_parse_candidate_sources(args.candidate_sources),
        tickers=_parse_tickers(args.tickers),
        next_high_hit_threshold=float(args.next_high_hit_threshold),
        walk_forward_preset=args.walk_forward_preset,
        walk_forward_window_mode=args.walk_forward_window_mode,
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_pre_layer_short_trade_outcomes_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
