from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def _as_price(day: Mapping[str, Any], key: str) -> float:
    value = day.get(key)
    if value is None:
        raise ValueError(f"forward day is missing required '{key}' price")
    price = float(value)
    if not math.isfinite(price):
        raise ValueError(f"forward day '{key}' price must be finite")
    return price


def _return_ratio(price: float, entry_price: float) -> float:
    return (price / entry_price) - 1.0


_FORWARD_DAYS_MINIMUM = 3  # minimum observed days for reliable label computation


def build_short_trade_forward_labels(*, entry_price: float, forward_days: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build forward-looking labels for short-trade evaluation.

    Returns a dict with numeric indicators, label booleans (or None when data
    is insufficient), and a ``data_sufficient`` flag so downstream consumers
    can distinguish missing data from genuinely negative observations.
    """
    if entry_price <= 0.0:
        raise ValueError("entry_price must be positive")

    observed = len(forward_days)
    data_sufficient = observed >= _FORWARD_DAYS_MINIMUM

    high_returns = [_return_ratio(_as_price(day, "high"), entry_price) for day in forward_days]
    close_returns = [_return_ratio(_as_price(day, "close"), entry_price) for day in forward_days]

    fast_high_window = high_returns[:2]
    retention_window = close_returns[1:4]
    tail_window = high_returns[1:9]

    max_high_return_t1_t2 = max(fast_high_window, default=0.0)
    close_return_t2 = close_returns[1] if len(close_returns) >= 2 else 0.0
    positive_close_count_t2_t4 = sum(1 for value in retention_window if value > 0.0)
    mean_close_return_t2_t4 = sum(retention_window) / len(retention_window) if retention_window else 0.0
    max_high_return_t2_t9 = max(tail_window, default=0.0)

    # When forward data is insufficient, labels are None so downstream models
    # can distinguish "data missing" from "truly negative".
    label_fast_confirm: bool | None = bool(max_high_return_t1_t2 >= 0.04 or close_return_t2 >= 0.01) if data_sufficient else None
    label_retention: bool | None = bool(positive_close_count_t2_t4 >= 2 and mean_close_return_t2_t4 >= 0.01) if data_sufficient else None
    label_tail_20: bool | None = bool(max_high_return_t2_t9 >= 0.20) if data_sufficient else None

    return {
        "entry_price": float(entry_price),
        "observed_forward_days": observed,
        "data_sufficient": data_sufficient,
        "max_high_return_t1_t2": max_high_return_t1_t2,
        "close_return_t2": close_return_t2,
        "positive_close_count_t2_t4": positive_close_count_t2_t4,
        "mean_close_return_t2_t4": mean_close_return_t2_t4,
        "max_high_return_t2_t9": max_high_return_t2_t9,
        "label_fast_confirm": label_fast_confirm,
        "label_retention": label_retention,
        "label_tail_20": label_tail_20,
    }
