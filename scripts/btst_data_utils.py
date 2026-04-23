from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from src.tools.ashare_board_utils import (
    BEIJING_EXCHANGE_SYMBOL_PREFIXES,
    build_beijing_exchange_mask_from_series,
    is_beijing_exchange_ts_code,
)


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def normalize_price_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    normalized = frame.copy()
    if not isinstance(normalized.index, pd.DatetimeIndex):
        date_column = None
        for candidate in ("date", "trade_date", "datetime"):
            if candidate in normalized.columns:
                date_column = candidate
                break
        if date_column is not None:
            normalized[date_column] = pd.to_datetime(normalized[date_column])
            normalized = normalized.set_index(date_column)
        else:
            normalized.index = pd.to_datetime(normalized.index)
    normalized.index = pd.to_datetime(normalized.index).normalize()
    normalized = normalized.sort_index()
    normalized.columns = [str(column).lower() for column in normalized.columns]
    return normalized


def build_beijing_exchange_mask(series: pd.Series) -> pd.Series:
    return build_beijing_exchange_mask_from_series(series)