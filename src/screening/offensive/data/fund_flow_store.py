"""资金流数据存储: 按 ticker 落盘 CSV, 查询时按日期过滤。

Phase 0a 用文件存储 (CSV per ticker); Phase 1+ 数据量上来后再迁 SQLite/Parquet。
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.screening.offensive.pit_evidence import validate_flow_artifact
from src.utils.atomic_files import atomic_write_csv

logger = logging.getLogger(__name__)


def _normalize_flow_frame_for_persistence(combined: pd.DataFrame) -> pd.DataFrame:
    """合并后、PIT 校验前的规整: 对 schema 列的历史 NaN 做安全填充。

    背景: validate_flow_artifact (commit 86226d72, 7-15 加入 FundFlowStore.save) 对
    合并后每一行做 _canonical_decimal 校验, NaN 被拒 → 整票落盘失败。但旧 cache 有
    两类历史性 NaN:

    1. close 列: 历史 100% NaN (tushare moneyflow 从不提供 close, 它是价格字段,
       下游从 price_cache 取)。填 0.0 安全 — 无下游消费者, row_to_record._f() 本来
       就 NaN→0.0。

    2. main_net_pct 列: 最近 3 天 (07-13/14/15) 约 13% 票的 NaN — tushare 改填 NaN
       (commit C1) 后、ftshare enrich 启用前积累的。这些是历史行, 当天新行由
       fund_flow._enrich_close_and_main_net_pct 补全。填 0.0 比"整票被拒丢失全部
       资金流数据"代价小 — scoring_feature_store 对 0.0 算出 main_flow_ratio=0.0
       (占比 0%), 而非跳过; 但只影响这 3 天的历史行, 后续会被正确数据覆盖。

    两者都填 0.0: 优先保证资金流数据能落盘 (main_net_inflow 等金额列是 setup 真正
    依赖的), 避免因辅助列的 NaN 连累整票。
    """
    for col in ("close", "main_net_pct"):
        if col in combined.columns:
            combined[col] = combined[col].fillna(0.0)
    return combined


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

    def save(
        self,
        ticker: str,
        df: pd.DataFrame,
        *,
        existing_frame: pd.DataFrame | None = None,
        artifact_sink: Callable[[pd.DataFrame], None] | None = None,
    ) -> int:
        """存入 ticker 资金流数据。同 ticker 已有数据时 merge + 去重 (按 date)。"""
        if df is None or len(df) == 0:
            return 0
        df = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df["date"]):
            df["date"] = pd.to_datetime(df["date"])
        df["date"] = df["date"].dt.strftime("%Y%m%d")
        df["ticker"] = ticker

        path = self._path(ticker)
        if existing_frame is not None:
            old = existing_frame.copy(deep=True)
            if "ticker" not in old.columns:
                old["ticker"] = ticker
            combined = pd.concat([old, df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["date"], keep="last")
            combined = combined.sort_values("date").reset_index(drop=True)
        elif path.exists():
            old = pd.read_csv(path, dtype={"date": str, "ticker": str})
            if "ticker" not in old.columns:
                old["ticker"] = ticker
            combined = pd.concat([old, df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["date"], keep="last")
            combined = combined.sort_values("date").reset_index(drop=True)
        else:
            combined = df.sort_values("date").reset_index(drop=True)
        combined = _normalize_flow_frame_for_persistence(combined)
        validate_flow_artifact(combined, ticker)
        if artifact_sink is not None:
            artifact_sink(combined.copy(deep=True))
        atomic_write_csv(path, combined)
        return len(combined)

    def _load_all(self, ticker: str) -> pd.DataFrame:
        path = self._path(ticker)
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path, dtype={"date": str, "ticker": str})

    @staticmethod
    def row_to_record(row: pd.Series, ticker: str | None = None) -> FundFlowRecord:
        """Convert a pandas Series row to a FundFlowRecord.

        NaN-safe: missing/invalid numeric fields default to 0.0
        (pandas NaN is truthy, so `x or 0.0` does not work; we float()
        then math.isnan() to normalize None/NaN/illegal values).

        Args:
            row: pandas Series with columns matching FundFlowRecord fields.
            ticker: optional ticker override (used by snapshot loader which
                knows the ticker from the filename and may load CSVs that
                lack a ``ticker`` column). When ``None``, falls back to
                ``row["ticker"]``.
        """
        def _f(key: str) -> float:
            try:
                f = float(row.get(key, 0.0))
            except (TypeError, ValueError):
                return 0.0
            return 0.0 if math.isnan(f) else f

        ticker_value = ticker if ticker is not None else str(row["ticker"])
        return FundFlowRecord(
            ticker=ticker_value,
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
        return self.row_to_record(match.iloc[0])

    def get_range(self, ticker: str, start_date: str, end_date: str) -> list[FundFlowRecord]:
        """闭区间 [start_date, end_date], YYYYMMDD。"""
        df = self._load_all(ticker)
        if len(df) == 0:
            return []
        mask = (df["date"] >= start_date) & (df["date"] <= end_date)
        return [self.row_to_record(row) for _, row in df[mask].iterrows()]
