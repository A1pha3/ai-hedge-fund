"""akshare 个股资金流数据封装。

封装 akshare.stock_individual_fund_flow, 标准化列名为英文 snake_case,
处理 market 映射 (sz/sh/bj), 网络/解析异常时返回空 DataFrame。
"""
from __future__ import annotations

import logging

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)

# 中文列名 → 英文标准化 (akshare stock_individual_fund_flow 实际返回的列)
_COLUMN_MAP: dict[str, str] = {
    "日期": "date",
    "收盘价": "close",
    "涨跌幅": "pct_change",
    "主力净流入-净额": "main_net_inflow",
    "主力净流入-净占比": "main_net_pct",
    "超大单净流入-净额": "super_big_net_inflow",
    "超大单净流入-净占比": "super_big_net_pct",
    "大单净流入-净额": "big_net_inflow",
    "大单净流入-净占比": "big_net_pct",
    "中单净流入-净额": "medium_net_inflow",
    "中单净流入-净占比": "medium_net_pct",
    "小单净流入-净额": "small_net_inflow",
    "小单净流入-净占比": "small_net_pct",
}


def _resolve_market(ticker: str) -> str:
    """A股 ticker → akshare market 标识 (sz/sh/bj)。

    600/601/603/605/688/689 → sh (上海)
    000/001/002/003/300/301 → sz (深圳)
    4xx/8xx/92xx            → bj (北交所)
    """
    t = str(ticker).strip()
    if t.startswith(("600", "601", "603", "605", "688", "689")):
        return "sh"
    if t.startswith(("000", "001", "002", "003", "300", "301")):
        return "sz"
    if t.startswith(("4", "8", "92")):
        return "bj"
    # 默认深圳 (绝大多数 A 股)
    return "sz"


def fetch_individual_fund_flow(ticker: str) -> pd.DataFrame:
    """拉取个股近期日度资金流数据。

    Args:
        ticker: 6 位 A 股代码 (e.g. "300054")

    Returns:
        标准化 DataFrame, 列: date(datetime) / close / pct_change /
        main_net_inflow / main_net_pct / ... 大单/中单/小单。
        akshare 异常时返回空 DataFrame (列同上)。
    """
    market = _resolve_market(ticker)
    try:
        raw = ak.stock_individual_fund_flow(stock=ticker, market=market)
    except Exception as exc:
        logger.warning("fund flow fetch failed for %s: %s", ticker, exc)
        return pd.DataFrame(columns=list(_COLUMN_MAP.values()))

    if raw is None or len(raw) == 0:
        return pd.DataFrame(columns=list(_COLUMN_MAP.values()))

    # 标准化列名 (只保留已知的中文列, 其余丢弃)
    renamed = raw.rename(columns=_COLUMN_MAP)
    known_cols = [c for c in _COLUMN_MAP.values() if c in renamed.columns]
    result = renamed[known_cols].copy()

    if "date" in result.columns:
        result["date"] = pd.to_datetime(result["date"], errors="coerce")
        result = result.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    return result
