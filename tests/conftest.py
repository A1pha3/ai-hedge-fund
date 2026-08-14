"""Root test isolation for shared network-layer singletons.

``src.tools.tushare_api`` caches ``_pro`` (the Pro API singleton) and the
process-local DataFrame LRU ``_tushare_df_cache`` at module level;
``src.tools.akshare_market_helpers`` keeps the east-money circuit-breaker state
(``_endpoint_circuit_open_until`` / ``_endpoint_failure_counts``) in module
globals.  A test that fakes ``sys.modules["tushare"]`` and calls ``_get_pro()``
leaves a stale fake ``_pro`` behind after ``monkeypatch`` restores the module —
so a LATER test (e.g. btst_full_report's fake tushare) gets the cached fake
instead of its own, silently using the wrong universe.  The same class of leak
applies to the DataFrame cache and the circuit breaker.

Resetting these singletons around every test keeps them from crossing test
boundaries, without touching the persistent disk cache (isolated separately).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_network_layer_singletons() -> None:
    """Neutralize module-level tushare/akshare caches after each test."""
    yield
    try:
        import src.tools.tushare_api as tushare_api

        tushare_api._pro = None
        tushare_api._tushare_df_cache.clear()
    except Exception:
        pass
    try:
        import src.tools.akshare_market_helpers as helpers

        helpers._endpoint_circuit_open_until.clear()
        helpers._endpoint_failure_counts.clear()
    except Exception:
        pass
