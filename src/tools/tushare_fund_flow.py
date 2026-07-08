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
import random
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# tushare amount 字段单位是万元 → 归一化为元 (×10000)
_WAN_TO_YUAN = 10_000.0

# 瞬时错误 (网络超时 / 连接中断 / 服务端 5xx) 才重试; 参数/权限/数据类错误不重试。
_NON_RETRYABLE_EXCEPTIONS = ("TypeError", "ValueError", "AttributeError", "KeyError")


def _is_rate_limit_error(exc: BaseException) -> bool:
    """检测是否为限速错误 (HTTP 429 / msg 含 rate limit)。与 tushare_api 同族逻辑。"""
    if type(exc).__name__ in {"HTTPError", "TooManyRequests", "RequestException"}:
        return True
    msg = str(exc).lower()
    return any(kw in msg for kw in ("rate limit", "too many", "限速", "频率", "429"))


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


def _moneyflow_with_retry(pro, *, ts_code: str, start_date: str, end_date: str, ticker: str) -> pd.DataFrame | None:
    """调用 pro.moneyflow, 带瞬时错误指数退避重试。

    网络抖动 (超时 / 连接中断 / 服务端 5xx) 是资金流批量拉取时 tushare 返回空的主因 —
    tushare client.py 的 query() 在 requests.post 失败时直接抛异常, 若无重试则整个
    moneyflow 调用失败, fallback 到不稳定的 akshare push2his。本函数复用 tushare_api
    的重试策略: 瞬时错误重试 TUSHARE_MAX_RETRIES 次, 指数退避 + jitter; 限速错误走
    独立通道; 参数/权限错误不重试。
    """
    max_retries = int(os.environ.get("TUSHARE_MAX_RETRIES", "2"))
    base_delay = float(os.environ.get("TUSHARE_RETRY_BASE_DELAY", "1.0"))
    rate_limit_delay = float(os.environ.get("TUSHARE_RATE_LIMIT_DELAY", "30.0"))
    rate_limit_max_retries = int(os.environ.get("TUSHARE_RATE_LIMIT_MAX_RETRIES", "2"))

    transient_attempts = 0
    rate_limit_attempts = 0
    max_total = max_retries + rate_limit_max_retries + 1

    for _ in range(max_total):
        try:
            return pro.moneyflow(ts_code=ts_code, start_date=start_date, end_date=end_date)
        except Exception as exc:
            exc_name = type(exc).__name__
            if exc_name in _NON_RETRYABLE_EXCEPTIONS:
                logger.warning("tushare moneyflow [%s] 不可重试错误: %s", ticker, exc)
                return None
            error_msg = str(exc)
            if "请指定正确的接口名" in error_msg or "接口名" in error_msg:
                logger.warning("tushare moneyflow [%s] 无权限 (不可重试): %s", ticker, error_msg)
                return None

            if _is_rate_limit_error(exc):
                rate_limit_attempts += 1
                if rate_limit_attempts > rate_limit_max_retries:
                    logger.warning("tushare moneyflow [%s] 限速重试已用尽: %s", ticker, exc)
                    return None
                delay = rate_limit_delay * (1 + random.random() * 0.3)
                logger.info("tushare moneyflow [%s] 限速 (尝试 %d/%d), %.1fs 后重试", ticker, rate_limit_attempts, rate_limit_max_retries, delay)
                time.sleep(delay)
                continue

            transient_attempts += 1
            if transient_attempts > max_retries:
                logger.warning("tushare moneyflow [%s] 重试 %d 次仍失败: %s", ticker, max_retries, exc)
                return None
            delay = base_delay * (2 ** (transient_attempts - 1)) * (1 + random.random() * 0.3)
            logger.info("tushare moneyflow [%s] 瞬时错误 (尝试 %d/%d), %.1fs 后重试: %s", ticker, transient_attempts, max_retries, delay, exc)
            time.sleep(delay)

    return None


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
        raw = _moneyflow_with_retry(pro, ts_code=_to_ts_code(ticker), start_date=start_date, end_date=end_date, ticker=ticker)
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
