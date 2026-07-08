from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable

import pandas as pd

# NS-17 / BH-017 family sibling drain: 可选市场帧 (index/northbound) 拉取失败此前用
# print, 在 cron 上下文不可见, 运维无法定位"为何市场数据缺失"。
logger = logging.getLogger(__name__)

# 同类网络错误去重计数器: 同一个 error_message 只打第一次 WARNING,
# 后续静默计数, 最后汇总一次. 避免 --auto 跑 302 ticker 时打 48 条相同 ProxyError.
_network_error_counts: dict[str, int] = {}


# ---------------------------------------------------------------------------
# 东财 push2* 反爬限速 (令牌桶)
# ---------------------------------------------------------------------------
# 东方财富 push2his/push2 接口对高频请求会触发反爬: 连接被重置 (RemoteDisconnected)
# 或返回空响应 (Empty reply), 封禁持续数小时. --auto Step2 对 300 只候选 4 并发
# 无间隔地打 push2his (~84 req/burst), 必然触发限流.
#
# 这里在 load_optional_market_dataframe (所有东财 akshare 调用的必经之路) 加一个
# 线程安全的令牌桶: 强制两次东财请求之间至少间隔 MIN_INTERVAL 秒. 默认 0.5s (QPS~2),
# 可通过 AKSHARE_EASTMONEY_MIN_INTERVAL 环境变量调节 (设 0 可关闭限速).
class _EastMoneyRateLimiter:
    """线程安全的请求间隔限速器 (minimum interval between requests)."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._last_request_time = 0.0

    def acquire(self) -> None:
        """阻塞直到距上次请求至少 min_interval 秒。"""
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_request_time = time.monotonic()


def _get_eastmoney_rate_limiter() -> _EastMoneyRateLimiter:
    global _eastmoney_rate_limiter
    if _eastmoney_rate_limiter is None:
        min_interval = float(os.environ.get("AKSHARE_EASTMONEY_MIN_INTERVAL", "0.5"))
        _eastmoney_rate_limiter = _EastMoneyRateLimiter(min_interval)
    return _eastmoney_rate_limiter


_eastmoney_rate_limiter: _EastMoneyRateLimiter | None = None


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

    # 东财反爬限速: 强制请求间隔, 避免 --auto 批量调用触发 RemoteDisconnected 封禁.
    _get_eastmoney_rate_limiter().acquire()

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
