"""tushare 个股资金流数据封装 (主源)。

tushare moneyflow API: buy/sell 拆分到 大单/中单/小单/超大单 + net_mf_amount (净额)。
数据比 akshare 更丰富, 且本项目 token 已开通 (验证: --auto 跑时 tushare 全通)。

单位: tushare *_amount 字段单位是【万元】, 本模块归一化为【元】(与 akshare 一致),
保证双源数据可混用, setup 的"主力 > 历史均值"比较不会因单位错位。

API: pro.moneyflow(ts_code='300502.SZ', start_date='20260601', end_date='20260706')
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# tushare amount 字段单位是万元 → 归一化为元 (×10000)
_WAN_TO_YUAN = 10_000.0


def _load_token() -> str:
    """从 env 或 .env 文件加载 TUSHARE_TOKEN。"""
    token = os.environ.get("TUSHARE_TOKEN", "")
    if token:
        return token
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("TUSHARE_TOKEN="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def _to_ts_code(ticker: str) -> str:
    """6 位 A 股代码 → tushare ts_code (带交易所后缀)。

    6xx/688 → .SH; 0xx/3xx → .SZ; 8xx/4xx/92 → .BJ
    """
    t = str(ticker).strip()
    if t.startswith(("600", "601", "603", "605", "688", "689")):
        return f"{t}.SH"
    if t.startswith(("000", "001", "002", "003", "300", "301")):
        return f"{t}.SZ"
    if t.startswith(("4", "8", "92")):
        return f"{t}.BJ"
    return f"{t}.SZ"  # 默认深圳


def fetch_individual_fund_flow_tushare(
    ticker: str,
    start_date: str = "20200101",
    end_date: str | None = None,
) -> pd.DataFrame:
    """拉取个股日度资金流 (tushare moneyflow, 主源)。

    Args:
        ticker: 6 位代码 (e.g. "300502")
        start_date: YYYYMMDD
        end_date: YYYYMMDD (None = 今天)

    Returns:
        标准化 DataFrame (与 akshare_fund_flow.fetch_individual_fund_flow 同 schema):
        date(datetime) / close / pct_change / main_net_inflow(元) / main_net_pct /
        big_net_inflow / super_big_net_inflow / medium_net_inflow / small_net_inflow
        全部金额字段单位【元】(已从万元归一化)。
        tushare 异常或 token 缺失时返回空 DataFrame。
    """
    token = _load_token()
    if not token:
        logger.warning("tushare_fund_flow: TUSHARE_TOKEN 未配置, 返回空")
        return pd.DataFrame(columns=["date", "main_net_inflow"])

    if end_date is None:
        end_date = pd.Timestamp.now().strftime("%Y%m%d")

    try:
        import tushare as ts

        ts.set_token(token)
        pro = ts.pro_api()
        raw = pro.moneyflow(ts_code=_to_ts_code(ticker), start_date=start_date, end_date=end_date)
    except Exception as exc:
        logger.warning("tushare moneyflow fetch failed for %s: %s", ticker, exc)
        return pd.DataFrame(columns=["date", "main_net_inflow"])

    if raw is None or len(raw) == 0:
        return pd.DataFrame(columns=["date", "main_net_inflow"])

    # 归一化: 万元 → 元, 计算净流入 (buy - sell per order size)
    df = raw.copy()
    # 主力净流入 = net_mf_amount (tushare 已算好, 万元)
    df["main_net_inflow"] = df["net_mf_amount"].astype(float) * _WAN_TO_YUAN
    # 大单净流入 = buy_lg_amount - sell_lg_amount
    df["big_net_inflow"] = (df["buy_lg_amount"].astype(float) - df["sell_lg_amount"].astype(float)) * _WAN_TO_YUAN
    # 超大单净流入
    df["super_big_net_inflow"] = (df["buy_elg_amount"].astype(float) - df["sell_elg_amount"].astype(float)) * _WAN_TO_YUAN
    # 中单 / 小单
    df["medium_net_inflow"] = (df["buy_md_amount"].astype(float) - df["sell_md_amount"].astype(float)) * _WAN_TO_YUAN
    df["small_net_inflow"] = (df["buy_sm_amount"].astype(float) - df["sell_sm_amount"].astype(float)) * _WAN_TO_YUAN
    # 主力净流入占比 = net_mf_amount / (成交额) — tushare 不直接给, 用 net_mf_vol/总股本近似留空
    df["main_net_pct"] = 0.0  # tushare 不提供占比, 留 0 (setup 主要用 net_inflow 绝对值)
    # close / pct_change: tushare moneyflow 不含价格, 留 NaN (价格从 daily 行情另取)
    df["close"] = float("nan")
    df["pct_change"] = 0.0
    # 日期: tushare trade_date 是 YYYYMMDD 字符串 → datetime
    df["date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    keep = ["date", "close", "pct_change", "main_net_inflow", "main_net_pct", "big_net_inflow", "super_big_net_inflow", "medium_net_inflow", "small_net_inflow"]
    return df[[c for c in keep if c in df.columns]]
