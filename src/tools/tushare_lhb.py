"""tushare 龙虎榜数据封装 — 机构席位明细 (非散户能拿的数据)。

API: pro.top_inst(trade_date='20260706') → 每日机构席位买卖明细。
关键字段: ts_code, exalter(席位名), buy(买入万元), sell(卖出万元), net_buy(净买入万元)

"机构专用" = 机构席位。散户几乎不看这个数据，edge 未被充分套利。
归一化单位: 万元 → 元 (与 fund_flow 保持一致)。
"""
from __future__ import annotations

import logging

import pandas as pd

from src.tools.tushare_api import get_tushare_token

logger = logging.getLogger(__name__)

_WAN_TO_YUAN = 10_000.0


def fetch_lhb_inst_detail(trade_date: str) -> pd.DataFrame:
    """拉取某日龙虎榜机构席位明细。

    Args:
        trade_date: YYYYMMDD

    Returns:
        标准化 DataFrame, 列: date / ts_code / exalter / buy(元) / sell(元) / net_buy(元)
        异常时返回空 DataFrame.
    """
    token = get_tushare_token()
    if not token:
        return pd.DataFrame()

    try:
        import tushare as ts

        pro = ts.pro_api(token=token)
        raw = pro.top_inst(trade_date=trade_date)
    except Exception as exc:
        logger.warning("lhb inst fetch failed for %s: %s", trade_date, exc)
        return pd.DataFrame()

    if raw is None or len(raw) == 0:
        return pd.DataFrame()

    df = raw.copy()
    df["date"] = trade_date
    df["buy"] = df["buy"].astype(float) * _WAN_TO_YUAN
    df["sell"] = df["sell"].astype(float) * _WAN_TO_YUAN
    df["net_buy"] = df["net_buy"].astype(float) * _WAN_TO_YUAN
    return df[["date", "ts_code", "exalter", "buy", "sell", "net_buy"]]


def aggregate_inst_net_buy(df: pd.DataFrame) -> dict[str, float]:
    """聚合每日机构席位净买入, 返回 {ts_code: net_buy(元)}。

    只取 "机构专用" 席位, 按 ts_code 求和。
    """
    inst = df[df["exalter"] == "机构专用"]
    if len(inst) == 0:
        return {}
    agg = inst.groupby("ts_code")["net_buy"].sum()
    return {k: float(v) for k, v in agg.items()}
