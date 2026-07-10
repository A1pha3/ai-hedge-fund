"""多源数据获取共享引擎 — dispatcher 循环、空表常量、列名工具。

所有 N 源 dispatcher (price.py / fund_flow.py) 共享的 4 个关注点:
1. 选源: 按优先级顺序尝试每个源, 首个非空即返回
2. 追踪: 区分 "返回空数据" 与 "异常" (不同根因)
3. 去重: 首次 WARNING 含详情, 后续静默, 每 50 次 INFO 计数
4. 空返回: 统一 schema 的空 DataFrame

提取本模块后, 各 dispatcher 退化为: 构造 sources 列表 + 一行调 try_sources()。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import pandas as pd

logger = logging.getLogger(__name__)

# ── 空 DataFrame schema 常量 ──────────────────────────────────────────────
# 所有源 fetcher 和 dispatcher 统一引用, 避免列名散落不同步。

PRICE_COLUMNS = ["date", "close", "open", "high", "low", "pct_change", "volume"]
FUND_FLOW_COLUMNS = ["date", "main_net_inflow"]

EMPTY_PRICE_DF = pd.DataFrame(columns=PRICE_COLUMNS)
EMPTY_FUND_FLOW_DF = pd.DataFrame(columns=FUND_FLOW_COLUMNS)

# ── 全源失败去重计数器 ────────────────────────────────────────────────────
_empty_counts: dict[str, int] = {}


def try_sources(
    sources: list[tuple[str, Callable[..., pd.DataFrame]]],
    *,
    log_tag: str,
    label: str,
    fetch_args: tuple = (),
    empty_df: pd.DataFrame = EMPTY_PRICE_DF,
) -> pd.DataFrame:
    """按优先级顺序尝试每个源, 首个非空即返回; 全空时去重 WARNING + 计数。

    Args:
        sources: [(name, fetcher), ...] 按优先级排序
        log_tag: 日志前缀, 如 "[日线]" / "[资金流]"
        label: 标识符 (通常是 ticker), 用于日志
        fetch_args: 透传给每个 fetcher 的位置参数
        empty_df: 全源失败时返回的空 DataFrame (调用方决定 schema)

    Returns:
        首个非空源的 DataFrame, 或全源失败时的 empty_df.copy()
    """
    outcomes: dict[str, str] = {}
    for name, fetcher in sources:
        try:
            df = fetcher(*fetch_args)
        except Exception as exc:
            outcomes[name] = f"异常 ({type(exc).__name__}: {exc})"
            df = pd.DataFrame()
        if df is not None and len(df) > 0:
            logger.debug("%s %s 命中 %s (%d 行)", log_tag, label, name, len(df))
            return df
        if name not in outcomes:
            outcomes[name] = "返回空数据"
        logger.debug("%s %s %s 返回空, 尝试下一源", log_tag, label, name)

    _log_all_empty(log_tag, label, outcomes)
    return empty_df.copy()


def _log_all_empty(log_tag: str, label: str, outcomes: dict[str, str]) -> None:
    """全源失败去重: 首次 WARNING (含每源真实失败原因), 后续静默, 每 50 次 INFO。"""
    key = log_tag
    _empty_counts[key] = _empty_counts.get(key, 0) + 1
    count = _empty_counts[key]
    detail = "; ".join(f"{src}: {reason}" for src, reason in outcomes.items())
    if count == 1:
        logger.warning("%s %s 全源均失败 — %s (后续同类将静默)", log_tag, label, detail)
    elif count % 50 == 0:
        logger.info("%s 全源均失败已累计 %d 次 (静默中)", log_tag, count)


def reorder_sources(
    sources: list[tuple[str, Callable]],
    primary: str,
) -> list[tuple[str, Callable]]:
    """把 primary 源排到第一位, 其余保持原顺序。"""
    head = [s for s in sources if s[0] == primary]
    tail = [s for s in sources if s[0] != primary]
    return head + tail


# ── 列名查找工具 (统一大小写不敏感匹配) ────────────────────────────────────

def find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """大小写不敏感查找第一个命中的候选列名 (中文 lower() 恒等, 同样适用)。"""
    lower_map = {str(c).lower(): c for c in df.columns}
    for candidate in candidates:
        key = candidate.lower()
        if key in lower_map:
            return lower_map[key]
    return None


def safe_float_col(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    """find_col + to_numeric(fillna=0.0), 缺失列返回全 0 Series。"""
    col = find_col(df, candidates)
    if col is None:
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0)


def extract_first_float(data: dict, keys: list[str]) -> float | None:
    """按 keys 顺序找第一个非 None 且可 float() 的值。"""
    for key in keys:
        val = data.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def safe_scalar(value: object) -> float | str | None:
    """pandas/numpy 标量 → Python 原生 (NaN → None)。"""
    try:
        if pd.isna(value):  # type: ignore[arg-type]
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return value.item()  # type: ignore[no-any-return]
    return value  # type: ignore[return-value]


def select_and_sort(df: pd.DataFrame, keep: list[str], sort_col: str = "date") -> pd.DataFrame:
    """保留 keep 中存在的列, 按 sort_col 排序并 reset_index。"""
    cols = [c for c in keep if c in df.columns]
    return df[cols].sort_values(sort_col).reset_index(drop=True)


# ── 单位常量 ──────────────────────────────────────────────────────────────

WAN_TO_YUAN = 10_000.0


def wan_to_yuan_if_needed(series: pd.Series, *, threshold: float = 1e4) -> pd.Series:
    """若 abs 中位数 < threshold (疑为万元), ×10000; 否则原样返回。"""
    med = series.abs().median()
    if med > 0 and med < threshold:
        return series * WAN_TO_YUAN
    return series
