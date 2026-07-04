"""NS-17 / BH-017 family sibling: provider ``health_check`` must log failures.

Characterization test for the logging-channel drain in
``src/data/providers/{akshare,tushare}_provider.py``. Previously both providers
swallowed every exception inside ``health_check()`` into a generic
``self.health_status = "unhealthy"`` return-``False`` with **no module logger
at all** — an operator could not distinguish a token revocation, a rate-limit,
an upstream API schema change, or a network blip from a transient failure,
because nothing was emitted to the logging infrastructure.

This mirrors the NS-17 / BH-017 print→logger family drained across
``src/tools/`` + ``src/llm/`` (c280–c289); ``src/data/providers/`` was missed.
The fix adds a module logger and emits ``logger.warning(...)`` carrying the
underlying exception on the failure path, while leaving the fetch/health
contract (return ``False``, set ``health_status``) unchanged.

Sibling of ``tests/backtesting/test_engine_market_data_logging.py`` (c279).
"""

from __future__ import annotations

import builtins
import logging
from unittest.mock import MagicMock, patch

from src.data.providers.akshare_provider import AKShareProvider
from src.data.providers.tushare_provider import TushareProvider

# ---------------------------------------------------------------------------
# AKShare provider
# ---------------------------------------------------------------------------


def test_akshare_health_check_failure_logs_warning(caplog) -> None:
    """AKShare health_check failure must emit a WARNING carrying the exception.

    Before fix: bare ``except Exception: ... return False`` with no logger in
    the module → silent failure, indistinguishable from "not configured".
    After fix: the exception is surfaced via ``logger.warning`` so operators
    can diagnose provider outages from structured logs.
    """
    prov = AKShareProvider()
    # Force the "available" branch so we reach the fetch whose failure we inject.
    # _ak must be a MagicMock so attribute access (self._ak.stock_zh_a_hist)
    # succeeds; the patched _run_sync raises when actually called.
    prov._akshare_available = True
    prov._ak = MagicMock()

    with patch.object(
        prov,
        "_run_sync",
        side_effect=RuntimeError("simulated akshare outage"),
    ):
        with caplog.at_level(logging.WARNING, logger="src.data.providers.akshare_provider"):
            import asyncio

            ok = asyncio.run(prov.health_check())

    # Contract preserved: failure → False, status unhealthy
    assert ok is False
    assert prov.health_status == "unhealthy"

    # Failure must be logged at WARNING level (not silent)
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) >= 1, f"expected >=1 WARNING record from akshare health_check failure, got {caplog.records}"
    msg = warning_records[0].message
    assert "akshare" in msg.lower() or "health" in msg.lower()
    assert "simulated akshare outage" in msg


def test_akshare_health_check_no_exc_info_is_fine(caplog) -> None:
    """Sanity: a passing health_check logs nothing at WARNING (no false alarm)."""
    prov = AKShareProvider()
    prov._akshare_available = True

    async def _fake(*_a, **_kw):
        return True

    with patch.object(prov, "_run_sync", side_effect=_fake):
        with caplog.at_level(logging.WARNING, logger="src.data.providers.akshare_provider"):
            import asyncio

            ok = asyncio.run(prov.health_check())

    assert ok is True
    assert prov.health_status == "healthy"
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning_records == []


# ---------------------------------------------------------------------------
# Tushare provider — same-class sibling
# ---------------------------------------------------------------------------


def test_tushare_health_check_failure_logs_warning(caplog) -> None:
    """Tushare health_check failure must emit a WARNING carrying the exception.

    Same-class sibling of the akshare fix (R162 precedent: the two providers
    share the same _run_sync kwargs bug; they share the same health_check
    swallow pattern too). Fixing one without the other leaves the tushare
    live-price path's failures silent.
    """
    prov = TushareProvider()
    # Force past the "not configured" early return so we reach the injected
    # failure. _pro must be a MagicMock so attribute access
    # (self._pro.stock_basic) succeeds; the patched _run_sync raises when called.
    prov._token = "fake-token"
    prov._pro = MagicMock()

    with patch.object(
        prov,
        "_run_sync",
        side_effect=RuntimeError("simulated tushare token revoked"),
    ):
        with caplog.at_level(logging.WARNING, logger="src.data.providers.tushare_provider"):
            import asyncio

            ok = asyncio.run(prov.health_check())

    assert ok is False
    assert prov.health_status == "unhealthy"

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) >= 1, f"expected >=1 WARNING record from tushare health_check failure, got {caplog.records}"
    msg = warning_records[0].message
    assert "tushare" in msg.lower() or "health" in msg.lower()
    assert "simulated tushare token revoked" in msg


def test_tushare_health_check_unconfigured_no_warning(caplog) -> None:
    """When the provider is not configured (no token / no _pro), it returns False
    silently — that is an expected configuration state, not a swallowed error,
    so it must NOT emit a WARNING (otherwise healthy dev boxes without a token
    would spam logs on every health poll)."""
    prov = TushareProvider()
    prov._token = None
    prov._pro = None

    with caplog.at_level(logging.WARNING, logger="src.data.providers.tushare_provider"):
        import asyncio

        ok = asyncio.run(prov.health_check())

    assert ok is False
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning_records == []


def test_akshare_health_check_unavailable_no_warning(caplog) -> None:
    """Same as the tushare unconfigured case: akshare not available is an expected
    state (ImportError at init), not a swallowed fetch error — no WARNING."""
    prov = AKShareProvider()
    prov._akshare_available = False
    prov._ak = None

    with caplog.at_level(logging.WARNING, logger="src.data.providers.akshare_provider"):
        import asyncio

        ok = asyncio.run(prov.health_check())

    assert ok is False
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning_records == []


# ---------------------------------------------------------------------------
# Tushare provider — _init_tushare non-ImportError failure logging
# (NS-17 / BH-017 family sibling: extends c305 health_check logging drain
# to the init path. Non-Import failures — token revoked at first API call,
# tushare runtime schema change, network error during pro_api() — were
# previously swallowed into a silent "unhealthy" with no log evidence.)
# ---------------------------------------------------------------------------


def test_tushare_init_non_import_failure_logs_warning(caplog) -> None:
    """Non-ImportError failure during ``ts.pro_api(token=...)`` init must emit
    a WARNING carrying the exception, so operators can distinguish "tushare
    not installed" (ImportError, silent) from "configured but broken"
    (runtime error, logged)."""
    with patch("builtins.__import__", side_effect=_import_tushare_raising_runtime()):
        with caplog.at_level(logging.WARNING, logger="src.data.providers.tushare_provider"):
            prov = TushareProvider(token="fake-token")

    assert prov.health_status == "unhealthy"
    assert prov._pro is None

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) >= 1, f"expected >=1 WARNING record from tushare init runtime failure, got {caplog.records}"
    msg = warning_records[0].message
    assert "tushare" in msg.lower() or "pro_api" in msg.lower()
    assert "simulated tushare init runtime error" in msg


def test_tushare_init_import_error_stays_silent(caplog) -> None:
    """ImportError (tushare not installed) is an expected dev-box state and
    must NOT emit a WARNING — only runtime/init failures are surfaced."""
    with patch("builtins.__import__", side_effect=_import_tushare_raising_import_error()):
        with caplog.at_level(logging.WARNING, logger="src.data.providers.tushare_provider"):
            prov = TushareProvider(token="fake-token")

    assert prov.health_status == "unhealthy"
    assert prov._pro is None
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning_records == []


def _import_tushare_raising_runtime():
    """Build an __import__ side_effect that raises RuntimeError when importing
    tushare (mimicking tushare runtime init failure: schema change, token
    rejected at first API call, etc.) but defers to the real import otherwise.
    """
    real_import = builtins.__import__

    def _side_effect(name: str, *args, **kwargs):
        if name == "tushare":
            raise RuntimeError("simulated tushare init runtime error")
        return real_import(name, *args, **kwargs)

    return _side_effect


def _import_tushare_raising_import_error():
    """Build an __import__ side_effect that raises ImportError when importing
    tushare (mimicking tushare not installed)."""
    real_import = builtins.__import__

    def _side_effect(name: str, *args, **kwargs):
        if name == "tushare":
            raise ImportError("simulated tushare not installed")
        return real_import(name, *args, **kwargs)

    return _side_effect


# ---------------------------------------------------------------------------
# Tushare provider — get_prices adj_factor fetch failure logging
# (NS-17 / BH-017 family sibling: when adj_factor fetch fails, get_prices
# degrades to raw (unadjusted) daily prices so the backtest still runs —
# but ex-div days will produce phantom losses that corrupt return/ATR/
# stop-loss/drawdown downstream. Previously the degrade was completely
# silent; operators had no way to detect that a backtest's results were
# contaminated by unadjusted prices.)
# ---------------------------------------------------------------------------


def test_tushare_get_prices_adj_factor_failure_logs_warning_and_degrades(
    caplog,
) -> None:
    """When ``adj_factor`` fetch fails inside ``get_prices``, the provider must
    (1) emit a WARNING carrying the failure + the ts_code so operators can
    correlate downstream return/ATR anomalies, and (2) still return prices
    from raw daily (degrade, don't block — backtest remains runnable)."""
    import asyncio

    import pandas as pd

    prov = TushareProvider()
    prov._token = "fake-token"
    # _pro must be a MagicMock so self._pro.daily and self._pro.adj_factor
    # attribute access both succeed; we patch _run_sync to dispatch to
    # fakes that return/raise per-call.
    prov._pro = MagicMock()

    raw_daily_df = pd.DataFrame(
        [
            {
                "trade_date": "20240102",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "vol": 1000,
            },
            {
                "trade_date": "20240103",
                "open": 10.2,
                "high": 10.6,
                "low": 10.0,
                "close": 10.4,
                "vol": 1200,
            },
        ]
    )

    call_count = {"n": 0}

    async def _fake_run_sync(func, *args, **kwargs):
        call_count["n"] += 1
        # First call: self._pro.daily → return raw daily df.
        # Second call: self._pro.adj_factor → raise (simulated fetch failure).
        if call_count["n"] == 1:
            return raw_daily_df
        raise RuntimeError("simulated adj_factor outage")

    with patch.object(prov, "_run_sync", side_effect=_fake_run_sync):
        with caplog.at_level(logging.WARNING, logger="src.data.providers.tushare_provider"):
            resp = asyncio.run(prov.get_prices("600519", "2024-01-01", "2024-01-03"))

    # Degrade-but-don't-block contract preserved: prices still returned.
    assert resp.source == "tushare"
    assert len(resp.data) == 2
    assert resp.error is None

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) >= 1, f"expected >=1 WARNING record from adj_factor fetch failure, got {caplog.records}"
    msg = warning_records[0].message
    assert "adj_factor" in msg
    assert "600519.SH" in msg or "600519" in msg
    assert "simulated adj_factor outage" in msg
