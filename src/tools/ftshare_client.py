"""ftshare SDK 单例管理 — 懒加载 + 带重试的 requests.Session 注入。

ftshare SDK 本身不内置重试/限频处理 (base.py 只有 timeout=10s, 非二进制直接抛异常)。
本模块构造一个带 urllib3 Retry 的 Session, 注入给 ``ft.market_api(session=)``,
使其具备与 tushare_api._get_pro() 同级的瞬时错误重试能力。

线程安全单例 (仿 tushare_api._get_pro / akshare_api._akshare_available 模式):
- ImportError (SDK 未安装) → 静默, _ftshare_available=False
- 其他 init 异常 → logger.warning + 返回 None (NS-17 house rule)

无需 token: ftshare SDK 构造函数不含鉴权参数, 认证由后端网关处理。
"""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

# ── 可用性 flag (仿 akshare_api._akshare_available) ──────────────────────
_ftshare_available = False

try:
    import ftshare as ft  # noqa: F401

    _ftshare_available = True
except ImportError:
    logger.debug("ftshare 未安装 (可选数据源, 不影响 tushare/akshare 主链)")
    ft = None  # type: ignore[assignment]

# ── 单例 (线程安全 double-checked locking) ────────────────────────────────
_market: object | None = None
_market_lock = threading.Lock()

# ── 重试 session ──────────────────────────────────────────────────────────
# ftshare SDK base.py 的 _request 只有 timeout, 无任何 retry/backoff。
# 我们预配置一个带 urllib3 Retry 的 requests.Session 注入给 market_api。
_session: object | None = None
_session_lock = threading.Lock()


def _get_retry_session():
    """构造 (并缓存) 一个带 Retry 的 requests.Session。

    urllib3 Retry: total=3, backoff_factor=0.5, 对 429/5xx 自动重试。
    """
    global _session
    if _session is not None:
        return _session

    with _session_lock:
        if _session is not None:
            return _session

        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        total = int(os.getenv("FTSHARE_MAX_RETRIES", "3"))
        backoff_factor = float(os.getenv("FTSHARE_BACKOFF_FACTOR", "0.5"))
        timeout = float(os.getenv("FTSHARE_TIMEOUT", "30"))

        retry = Retry(
            total=total,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "POST"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session = requests.Session()
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        session._ftshare_timeout = timeout  # type: ignore[attr-defined]
        _session = session
        return _session


def _get_market():
    """返回 ftshare market client 单例 (线程安全)。

    Returns:
        ftshare client 对象, 或 None (SDK 未安装 / init 失败时)。

    调用方应始终检查 ``if market is None: return empty`` — 与 tushare_api._get_pro() 同契约。
    """
    global _market
    if _market is not None:
        return _market
    if not _ftshare_available:
        return None

    with _market_lock:
        if _market is not None:
            return _market

        try:
            session = _get_retry_session()
            timeout = getattr(session, "_ftshare_timeout", 30.0)
            # 直接构造 FtshareClient 注入 retry session。
            # 不能用 ft.market_api() 工厂 — 它的签名 (base_url/timeout/headers) 不接受 session,
            # 而 FtshareClient.__init__ 接受 session。我们要 session 注入来做 429/5xx 重试。
            from ftshare.client import FtshareClient

            _market = FtshareClient(timeout=timeout, session=session)
            logger.debug("ftshare market client 初始化成功 (timeout=%.1fs, retry=%d)", timeout, 3)
            return _market
        except Exception as e:
            # NS-17 house rule: 非 ImportError 失败 surface 到 warning, 不静默吞 None
            logger.warning("ftshare market_api 初始化失败: %s", e, exc_info=True)
            return None


def reset_market():
    """重置单例 (仅用于测试)。"""
    global _market
    with _market_lock:
        _market = None
