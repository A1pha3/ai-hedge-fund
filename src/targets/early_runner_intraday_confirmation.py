from __future__ import annotations

from typing import Any

import pandas as pd

from src.execution.buy_signal_confirmation import confirm_buy_signal
from src.screening.strategy_scorer import build_intraday_short_trade_metrics
from src.tools.akshare_api import get_intraday_bars


def _safe_float(value: Any) -> float | None:
    """Return a float when parsing succeeds, otherwise ``None``."""
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any, default: float = 0.0) -> float:
    """Convert mixed inputs into float while preserving a caller-provided default."""
    parsed = _safe_float(value)
    return default if parsed is None else float(parsed)


def _clamp_unit_interval(value: float) -> float:
    """Clamp a numeric score into the inclusive ``[0.0, 1.0]`` range."""
    return max(0.0, min(1.0, float(value)))


def compute_open_gap_quality(next_open_return: float, *, max_open_gap: float) -> float:
    """Score the opening gap so over-gapped entries fail closed."""
    if next_open_return > max_open_gap:
        return 0.0
    if next_open_return < -0.03:
        return 0.2
    if next_open_return <= 0.02:
        return 1.0
    return round(_clamp_unit_interval(1.0 - ((next_open_return - 0.02) / max(0.0001, max_open_gap - 0.02))), 4)


def compute_vwap_proxy(next_open_to_close_return: float) -> float:
    """Preserve the current close-based VWAP proxy until real 30-minute data lands."""
    return round(_clamp_unit_interval((next_open_to_close_return + 0.03) / 0.06), 4)


def compute_intraday_volume_rhythm(next_high_return: float, next_close_return: float) -> float:
    """Estimate intraday volume follow-through from the current T+1 outcome proxy."""
    if next_high_return <= 0.0:
        return 0.0
    pullback = max(0.0, next_high_return - max(next_close_return, 0.0))
    base = _clamp_unit_interval(next_high_return / 0.12)
    exhaustion_penalty = _clamp_unit_interval(pullback / 0.12)
    return round(_clamp_unit_interval((0.60 * base) + (0.40 * (1.0 - exhaustion_penalty))), 4)


def compute_liquidity_score(estimated_amount_1d_wan_yuan: float | None, *, low_liquidity_threshold_wan_yuan: float) -> float:
    """Score tradable liquidity using the current turnover threshold contract."""
    if estimated_amount_1d_wan_yuan is None:
        return 0.0
    return round(_clamp_unit_interval(float(estimated_amount_1d_wan_yuan) / (low_liquidity_threshold_wan_yuan * 2.0)), 4)


def compute_confirm_score(
    row: dict[str, Any],
    *,
    max_open_gap: float,
    low_liquidity_threshold_wan_yuan: float,
) -> float:
    """Compute the current confirm-score contract without changing output fields."""
    next_open_return = _as_float(row.get("next_open_return"), 0.0)
    next_open_to_close_return = _as_float(row.get("next_open_to_close_return"), 0.0)
    next_high_return = _as_float(row.get("next_high_return"), 0.0)
    next_close_return = _as_float(row.get("next_close_return"), 0.0)
    gap_to_limit = _as_float(row.get("gap_to_limit"), 0.10)
    open_gap_quality = compute_open_gap_quality(next_open_return, max_open_gap=max_open_gap)
    vwap_reclaim_or_hold = compute_vwap_proxy(next_open_to_close_return)
    intraday_volume_rhythm = compute_intraday_volume_rhythm(next_high_return, next_close_return)
    theme_continuation = round(_clamp_unit_interval((0.60 * _as_float(row.get("sector_resonance"), 0.0)) + (0.40 * _as_float(row.get("catalyst_theme_score"), 0.0))), 4)
    no_failed_breakout_intraday = 1.0 if next_close_return >= 0.0 and (next_high_return - next_close_return) <= 0.05 else 0.0
    tradable_liquidity = compute_liquidity_score(row.get("estimated_amount_1d_wan_yuan"), low_liquidity_threshold_wan_yuan=low_liquidity_threshold_wan_yuan)
    pre_score_rank_quality = _as_float(row.get("pre_score_rank_quality"), 0.0)

    execution_penalty = 0.0
    if next_open_return > max_open_gap:
        execution_penalty += 0.18
    if next_open_to_close_return < 0.0:
        execution_penalty += 0.15
    if next_high_return - next_close_return > 0.08 and next_close_return < 0.02:
        execution_penalty += 0.12
    if gap_to_limit <= 0.01:
        execution_penalty += 0.10

    score = (0.25 * open_gap_quality) + (0.22 * vwap_reclaim_or_hold) + (0.16 * intraday_volume_rhythm) + (0.14 * theme_continuation) + (0.10 * no_failed_breakout_intraday) + (0.08 * tradable_liquidity) + (0.05 * pre_score_rank_quality) - execution_penalty
    return round(_clamp_unit_interval(score), 4)


def _normalize_intraday_bars(intraday_bars: pd.DataFrame | None) -> pd.DataFrame:
    """Normalize minute bars into a compact schema for confirmation checks."""
    if intraday_bars is None or intraday_bars.empty:
        return pd.DataFrame()
    normalized = intraday_bars.copy()
    for source, target in {
        "时间": "timestamp",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交额": "amount",
        "成交量": "volume",
    }.items():
        if source in normalized.columns and target not in normalized.columns:
            normalized[target] = normalized[source]
    required = {"timestamp", "close"}
    if not required.issubset(normalized.columns):
        return pd.DataFrame()
    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], errors="coerce")
    for column in ["open", "close", "high", "low", "amount", "volume"]:
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    normalized = normalized.dropna(subset=["timestamp", "close"]).sort_values("timestamp").reset_index(drop=True)
    if normalized.empty:
        return pd.DataFrame()
    if "open" not in normalized.columns:
        normalized["open"] = normalized["close"]
    if "high" not in normalized.columns:
        normalized["high"] = normalized[["open", "close"]].max(axis=1)
    if "low" not in normalized.columns:
        normalized["low"] = normalized[["open", "close"]].min(axis=1)
    if "amount" not in normalized.columns:
        normalized["amount"] = 0.0
    if "volume" not in normalized.columns:
        normalized["volume"] = 0.0
    return normalized


def _build_runtime_confirmation_payload(
    row: dict[str, Any],
    *,
    ticker: str,
    confirm_trade_date: str,
) -> dict[str, Any] | None:
    """Build real intraday confirmation inputs from the first 30 minutes when data exists."""
    intraday_bars = _normalize_intraday_bars(get_intraday_bars(ticker, confirm_trade_date))
    if intraday_bars.empty:
        return None
    first_window = intraday_bars.head(min(30, len(intraday_bars)))
    if first_window.empty:
        return None
    # R156 same-class drain: ``float(x or y or 0.0)`` does NOT catch NaN — NaN
    # is truthy and short-circuits the ``or`` chain, so a NaN open (valid close,
    # passes _normalize's dropna(subset=['close'])) propagates to NaN open_price
    # → NaN breakout_anchor / failed_breakout. Sibling vwap/amount lines already
    # use fillna which catches NaN. Use a NaN-aware first-valid extraction.
    _first_open = first_window.iloc[0].get("open")
    _first_close = first_window.iloc[0].get("close")
    open_price = float(_first_open) if pd.notna(_first_open) and _first_open else float(_first_close) if pd.notna(_first_close) and _first_close else 0.0
    next_open_return = _safe_float(row.get("next_open_return"))
    prev_close = open_price / (1.0 + next_open_return) if next_open_return is not None and open_price > 0.0 and abs(1.0 + next_open_return) > 1e-6 else 0.0
    _last_close = first_window.iloc[-1].get("close")
    current_price = float(_last_close) if pd.notna(_last_close) and _last_close else 0.0
    amount_sum = float(first_window["amount"].fillna(0.0).sum())
    estimated_amount_1d = _safe_float(row.get("estimated_amount_1d_wan_yuan"))
    avg_same_time_volume = max(amount_sum, 1.0)
    if estimated_amount_1d is not None and estimated_amount_1d > 0.0:
        avg_same_time_volume = max((estimated_amount_1d * 10000.0) / 8.0, 1.0)
    amount_weights = first_window["amount"].fillna(0.0)
    weighted_close = first_window["close"].fillna(0.0)
    vwap = float((weighted_close * amount_weights).sum() / amount_weights.sum()) if float(amount_weights.sum()) > 0.0 else float(weighted_close.mean())
    ema30 = float(weighted_close.ewm(span=min(10, len(weighted_close)), adjust=False).mean().iloc[-1]) if not weighted_close.empty else current_price
    breakout_anchor = max(prev_close, open_price)
    day_low = float(first_window["low"].fillna(current_price).min())
    day_high = float(first_window["high"].fillna(current_price).max())
    failed_breakout = bool(current_price < (breakout_anchor * 0.995) and day_high > breakout_anchor)
    runtime_inputs = {
        "day_low": day_low if day_low > 0.0 else current_price,
        "ema30": ema30 if ema30 > 0.0 else current_price,
        "current_price": current_price,
        "vwap": vwap if vwap > 0.0 else current_price,
        "intraday_volume": max(amount_sum, 1.0),
        "avg_same_time_volume": avg_same_time_volume,
        "industry_percentile": round(1.0 - _clamp_unit_interval(_as_float(row.get("sector_resonance"), 0.0)), 4),
        "stock_pct_change": ((current_price / prev_close) - 1.0) if prev_close > 0.0 else 0.0,
        "industry_pct_change": _as_float(row.get("sector_resonance"), 0.0) * 0.02,
        "open_price": open_price,
        "prev_close": prev_close,
        "breakout_anchor": breakout_anchor,
        "open_gap_pct": next_open_return,
        "minutes_since_open": min(30, len(first_window)),
        "failed_breakout": failed_breakout,
    }
    intraday_metrics = build_intraday_short_trade_metrics(ticker, confirm_trade_date)
    return {
        "runtime_inputs": runtime_inputs,
        "intraday_metrics": intraday_metrics,
        "bars_available": True,
    }


def compute_confirm_assessment(
    row: dict[str, Any],
    *,
    ticker: str,
    confirm_trade_date: str | None,
    max_open_gap: float,
    low_liquidity_threshold_wan_yuan: float,
) -> dict[str, Any]:
    """Prefer real first-30-minute confirmation data and fall back to legacy proxy scoring."""
    proxy_score = compute_confirm_score(
        row,
        max_open_gap=max_open_gap,
        low_liquidity_threshold_wan_yuan=low_liquidity_threshold_wan_yuan,
    )
    if not confirm_trade_date:
        return {
            "score": proxy_score,
            "confirmed": proxy_score >= 0.55,
            "provenance": "proxy_fallback",
            "checks": {},
            "hard_failures": {},
            "inputs": {},
            "intraday_metrics": {},
        }
    runtime_payload = _build_runtime_confirmation_payload(
        row,
        ticker=ticker,
        confirm_trade_date=confirm_trade_date,
    )
    if not runtime_payload:
        return {
            "score": proxy_score,
            "confirmed": proxy_score >= 0.55,
            "provenance": "proxy_fallback",
            "checks": {},
            "hard_failures": {},
            "inputs": {},
            "intraday_metrics": {},
        }
    runtime_decision = confirm_buy_signal(
        max_open_gap_pct=max_open_gap,
        **runtime_payload["runtime_inputs"],
    )
    total_checks = max(len(dict(runtime_decision.get("checks") or {})), 1)
    runtime_score = _clamp_unit_interval((float(runtime_decision.get("passed_checks") or 0.0) / total_checks) - (0.20 * len([flag for flag in dict(runtime_decision.get("hard_failures") or {}).values() if flag])))
    if bool(runtime_decision.get("confirmed")):
        runtime_score = max(runtime_score, 0.72)
    blended_score = round(_clamp_unit_interval((0.70 * runtime_score) + (0.30 * proxy_score)), 4)
    return {
        "score": blended_score,
        "confirmed": bool(runtime_decision.get("confirmed")),
        "provenance": "intraday_live",
        "checks": dict(runtime_decision.get("checks") or {}),
        "hard_failures": dict(runtime_decision.get("hard_failures") or {}),
        "inputs": dict(runtime_payload.get("runtime_inputs") or {}),
        "intraday_metrics": dict(runtime_payload.get("intraday_metrics") or {}),
        "proxy_score": proxy_score,
        "runtime_score": round(runtime_score, 4),
    }
