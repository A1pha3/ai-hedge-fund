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
    assert len(warning_records) >= 1, (
        f"expected >=1 WARNING record from akshare health_check failure, got {caplog.records}"
    )
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
    assert len(warning_records) >= 1, (
        f"expected >=1 WARNING record from tushare health_check failure, got {caplog.records}"
    )
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
