"""宏观指标多源 dispatcher — tushare 主源 → ftshare fallback。

tushare 多数宏观接口 (cn_cpi/cn_ppi/cn_m/cn_sf) 因账号权限返回
"请指定正确的接口名", 导致 MacroSnapshot 大量字段为 None, regime 恒为 unknown。

策略: 先调 tushare; 若关键字段全 None, 则用 ftshare dict 填充 MacroSnapshot。
ftshare 只填充 tushare 未提供的字段 (None 的), 不覆盖已有值。
"""

from __future__ import annotations

import logging

from src.data.macro_data import MacroSnapshot
from src.tools._multi_source import extract_first_float

logger = logging.getLogger(__name__)

# 表驱动: (snapshot 字段名, ftshare 数据 key, 候选提取 keys)
_SPECS = [
    ("cpi_yoy",               "cpi", ["nt_yoy", "yoy", "cpi_yoy"]),
    ("ppi_yoy",               "ppi", ["ppi_yoy", "yoy", "nt_yoy"]),
    ("pmi_manufacturing",     "pmi", ["pmi010000", "pmi", "manufacturing_pmi"]),
    ("pmi_non_manufacturing", "pmi", ["pmi020100", "non_manufacturing_pmi"]),
    ("m2_yoy",                "m2",  ["m2_yoy", "yoy"]),
    ("social_financing",      "sf",  ["inc_month", "total", "inc_cumval"]),
    ("interest_rate_lpr_1y",  "lpr", ["1y", "lpr_1y", "lpr"]),
]


def fetch_macro_snapshot_multi(use_cache: bool = True) -> MacroSnapshot:
    """宏观快照多源: tushare → ftshare。"""
    # 主源: tushare
    try:
        from src.data.macro_data import fetch_macro_snapshot

        snapshot = fetch_macro_snapshot(use_cache=use_cache)
    except Exception as exc:
        logger.warning("[macro_multi] tushare fetch_macro_snapshot 异常: %s", exc)
        snapshot = MacroSnapshot()

    # tushare 至少一个关键字段有效 → 直接返回
    if any(getattr(snapshot, f, None) is not None for f, _, _ in _SPECS):
        return snapshot

    # Fallback: ftshare
    logger.info("[macro_multi] tushare 宏观全字段为空 (无权限?), fallback 到 ftshare")
    try:
        from src.tools.ftshare_api import fetch_macro_snapshot_ftshare

        ftshare_data = fetch_macro_snapshot_ftshare()
    except Exception as exc:
        logger.warning("[macro_multi] ftshare 宏观快照异常: %s", exc)
        return snapshot

    if not ftshare_data:
        logger.warning("[macro_multi] ftshare 宏观快照也为空, regime 将保持 unknown")
        return snapshot

    return _fill_from_ftshare(snapshot, ftshare_data)


def _fill_from_ftshare(snapshot: MacroSnapshot, data: dict) -> MacroSnapshot:
    """用 ftshare dict 填充 MacroSnapshot 中仍为 None 的字段。"""
    filled = 0
    for field, key, extract_keys in _SPECS:
        if getattr(snapshot, field) is not None:
            continue  # tushare 已有值, 不覆盖
        sub = data.get(key, {})
        if not sub:
            continue
        val = extract_first_float(sub, extract_keys)
        if val is not None:
            setattr(snapshot, field, val)
            filled += 1

    # date: 取第一个有 month 字段的指标
    if not snapshot.date:
        for _, key, _ in _SPECS:
            month = extract_first_float(data.get(key, {}), ["month", "date", "report_date"])
            if month is not None:
                snapshot.date = _normalise_month(str(int(month)))
                break

    logger.info("[macro_multi] ftshare 填充 %d 个宏观字段", filled)
    return snapshot


def _normalise_month(raw: str) -> str:
    """归一化月份: "202606.0" → "202606", "2026-06" → "202606"。"""
    cleaned = raw.strip().replace("-", "")
    if cleaned.endswith(".0"):
        cleaned = cleaned[:-2]
    return cleaned
