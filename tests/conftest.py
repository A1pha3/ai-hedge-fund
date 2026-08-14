"""Root test isolation for shared network-layer singletons.

``src.tools.tushare_api`` caches ``_pro`` (the Pro API singleton) at module
level; ``src.tools.akshare_market_helpers`` keeps the east-money circuit-breaker
state (``_endpoint_circuit_open_until`` / ``_endpoint_failure_counts``) in
module globals.  A test that fakes ``sys.modules["tushare"]`` and calls
``_get_pro()`` leaves a stale fake ``_pro`` behind after ``monkeypatch``
restores the module — so a LATER test (e.g. btst_full_report's fake tushare)
gets the cached fake instead of its own, silently using the wrong universe.

Resetting ``_pro`` and the circuit state around every test keeps them from
crossing test boundaries.  The process-local DataFrame LRU
``_tushare_df_cache`` is deliberately NOT cleared: it is a legitimate cache
that several analyzers rely on across the run, and clearing it forces real
re-fetches that fail in a no-credential environment (regressing e.g.
test_analyze_btst_candidate_pool_recall_dossier).  The persistent disk cache is
isolated separately by tests/offensive/conftest.py.
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
    except Exception:
        pass
    try:
        import src.tools.akshare_market_helpers as helpers

        helpers._endpoint_circuit_open_until.clear()
        helpers._endpoint_failure_counts.clear()
    except Exception:
        pass
