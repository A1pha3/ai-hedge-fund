from __future__ import annotations

import logging
from collections.abc import Callable

import pandas as pd

# NS-17 / BH-017 family sibling drain: 可选市场帧 (index/northbound) 拉取失败此前用
# print, 在 cron 上下文不可见, 运维无法定位"为何市场数据缺失"。
logger = logging.getLogger(__name__)

# 同类网络错误去重计数器: 同一个 error_message 只打第一次 WARNING,
# 后续静默计数, 最后汇总一次. 避免 --auto 跑 302 ticker 时打 48 条相同 ProxyError.
_network_error_counts: dict[str, int] = {}


def load_optional_market_dataframe(
    *,
    is_available: bool,
    unavailable_message: str,
    fetch_dataframe_fn: Callable[[], pd.DataFrame | None],
    error_message: str,
    transform_fn: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> pd.DataFrame | None:
    if not is_available:
        logger.warning("%s", unavailable_message)
        return None

    try:
        df = fetch_dataframe_fn()
        if df is None or df.empty:
            return None
        if transform_fn is not None:
            df = transform_fn(df)
            if df is None or df.empty:
                return None
        return df
    except Exception as error:
        # 可选数据降级路径 (非核心数据, 失败不阻断 --auto):
        # 1. 网络错误 (ProxyError/RemoteDisconnected/Timeout) — 代理/超时, 预期降级
        # 2. 数据空响应 (NoneType/KeyError/IndexError) — akshare 返回空 (如龙虎榜
        #    当天未发布), 内部解析时 data_json["result"] 为 None → TypeError, 非代码 bug
        # 两类都不打 Traceback + 去重, 只在真正的代码 bug (如 AttributeError
        # 指向本仓库代码) 时打完整栈帮助调试.
        error_name = type(error).__name__
        error_str = str(error)
        is_expected_failure = error_name in (
            "ProxyError", "RemoteDisconnected", "ConnectionError",
            "TimeoutError", "MaxRetryError", "ConnectTimeoutError",
            "ReadTimeoutError", "SSLError",
            # 数据空响应类 (akshare 内部解析空 JSON 触发, 非本仓库代码 bug):
            "TypeError", "KeyError", "IndexError",
        ) or "proxy" in error_str.lower() or "timeout" in error_str.lower()
        # 进一步区分: TypeError 的 "'NoneType' object is not subscriptable" 是数据空,
        # 但其他 TypeError (如参数类型错) 可能是代码 bug → 看 error_str 区分
        if error_name == "TypeError" and "NoneType" not in error_str:
            is_expected_failure = False  # 非 NoneType 的 TypeError 可能是真 bug
        if is_expected_failure:
            # 去重: 同类错误只打第一次, 后续静默计数
            dedup_key = f"{error_name}:{error_message.split('(')[0]}"
            _network_error_counts[dedup_key] = _network_error_counts.get(dedup_key, 0) + 1
            if _network_error_counts[dedup_key] == 1:
                logger.warning("%s: %s (数据降级, 后续同类将静默)", error_message, error_str[:80])
            elif _network_error_counts[dedup_key] == 5:
                logger.info("  … %s 已连续 %d 次失败 (静默后续)", dedup_key, _network_error_counts[dedup_key])
        else:
            # 真正的代码 bug: 打完整 Traceback 帮助调试
            logger.warning("%s: %s", error_message, error, exc_info=True)
        return None
