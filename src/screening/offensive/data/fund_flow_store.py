"""资金流数据存储: 按 ticker 落盘 CSV, 查询时按日期过滤。

Phase 0a 用文件存储 (CSV per ticker); Phase 1+ 数据量上来后再迁 SQLite/Parquet。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.utils.atomic_files import atomic_write_csv

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FundFlowRecord:
    ticker: str
    date: str  # YYYYMMDD
    close: float
    pct_change: float
    main_net_inflow: float
    main_net_pct: float
    big_net_inflow: float = 0.0
    super_big_net_inflow: float = 0.0
    medium_net_inflow: float = 0.0
    small_net_inflow: float = 0.0


class FundFlowStore:
    """per-ticker CSV 存储。文件名: <cache_dir>/<ticker>.csv"""

    def __init__(self, cache_dir: Path | str):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, ticker: str) -> Path:
        return self.cache_dir / f"{ticker}.csv"

    def save(self, ticker: str, df: pd.DataFrame) -> int:
        """存入 ticker 资金流数据。同 ticker 已有数据时 merge + 去重 (按 date)。"""
        if df is None or len(df) == 0:
            return 0
        df = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df["date"]):
            df["date"] = pd.to_datetime(df["date"])
        df["date"] = df["date"].dt.strftime("%Y%m%d")
        df["ticker"] = ticker

        path = self._path(ticker)
        if path.exists():
            old = pd.read_csv(path, dtype={"date": str, "ticker": str})
            combined = pd.concat([old, df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["date"], keep="last")
            combined = combined.sort_values("date").reset_index(drop=True)
        else:
            combined = df.sort_values("date").reset_index(drop=True)
        atomic_write_csv(path, combined)
        return len(combined)

    def _load_all(self, ticker: str) -> pd.DataFrame:
        path = self._path(ticker)
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path, dtype={"date": str, "ticker": str})

    @staticmethod
    def _row_to_record(row: pd.Series) -> FundFlowRecord:
        # pandas NaN 是 truthy, `x or 0.0` 对 NaN 无效 → CSV 空值传播为 NaN.
        # 先 float() 再 math.isnan() 统一处理 None/NaN/非法值, 兜底为 0.0.
        def _f(key: str) -> float:
            try:
                f = float(row.get(key, 0.0))
            except (TypeError, ValueError):
                return 0.0
            return 0.0 if math.isnan(f) else f

        return FundFlowRecord(
            ticker=str(row["ticker"]),
            date=str(row["date"]),
            close=_f("close"),
            pct_change=_f("pct_change"),
            main_net_inflow=_f("main_net_inflow"),
            main_net_pct=_f("main_net_pct"),
            big_net_inflow=_f("big_net_inflow"),
            super_big_net_inflow=_f("super_big_net_inflow"),
            medium_net_inflow=_f("medium_net_inflow"),
            small_net_inflow=_f("small_net_inflow"),
        )

    def get(self, ticker: str, date: str) -> FundFlowRecord | None:
        """date 格式 YYYYMMDD。"""
        df = self._load_all(ticker)
        if len(df) == 0:
            return None
        match = df[df["date"] == date]
        if len(match) == 0:
            return None
        return self._row_to_record(match.iloc[0])

    def get_range(self, ticker: str, start_date: str, end_date: str) -> list[FundFlowRecord]:
        """闭区间 [start_date, end_date], YYYYMMDD。"""
        df = self._load_all(ticker)
        if len(df) == 0:
            return []
        mask = (df["date"] >= start_date) & (df["date"] <= end_date)
        return [self._row_to_record(row) for _, row in df[mask].iterrows()]
