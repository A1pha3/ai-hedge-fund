"""Root test isolation for shared network-layer singletons.

``src.tools.tushare_api`` caches ``_pro`` (the Pro API singleton) at module
level; ``src.tools.akshare_market_helpers`` keeps the east-money circuit-breaker
state (``_endpoint_circuit_open_until`` / ``_endpoint_failure_counts``) in
module globals.  A test that fakes ``sys.modules["tushare"]`` and calls
``_get_pro()`` leaves a stale fake ``_pro`` behind after ``monkeypatch``
restores the module — so a LATER test (e.g. btst_full_report's fake tushare)
gets the cached fake instead of its own, silently using the wrong universe.

Resetting ``_pro`` and the circuit state around every test keeps them from
crossing test boundaries.  ``_stock_basic_cache`` (the process-global
"fetch once" memo inside ``get_all_stock_basic``) is reset for the same
reason: readiness tests inject 3-column stock_basic frames (no ``list_date``)
via mocked providers, the frame survives ``monkeypatch`` teardown inside the
memo, and a LATER test calling the real function (e.g. the btst recall
dossier script test) reads the reduced frame and dies on
``KeyError: 'list_date'``.  The process-local DataFrame LRU
``_tushare_df_cache`` is deliberately NOT cleared: it is a legitimate cache
that several analyzers rely on across the run, and clearing it forces real
re-fetches that fail in a no-credential environment.  The persistent disk
cache is isolated separately by tests/offensive/conftest.py.

The threshold-trigger ledger (``data/reports/threshold_trigger_ledger.jsonl``)
is likewise neutralized: ``render_daily_action_v2`` reads it through a relative
path, so on a machine that has run the judge the trigger state line appears in
every rendered view while a fresh clone renders without it — machine-dependent
test output (R86 Op1; same hermeticity family as the offensive conftest
fixtures). Tests that exercise the line itself monkeypatch the path after this
autouse fixture and are unaffected.
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
        with tushare_api._stock_basic_cache_lock:
            tushare_api._stock_basic_cache = None
    except Exception:
        pass
    try:
        import src.tools.akshare_market_helpers as helpers

        helpers._endpoint_circuit_open_until.clear()
        helpers._endpoint_failure_counts.clear()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_threshold_trigger_ledger(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Pin the trigger ledger to a nonexistent tmp path for every test.

    Without this, render-level tests show the trigger state line only on
    machines where the real ledger exists — the same test green here and flaky
    on a fresh clone. Explicit per-test monkeypatches apply after autouse
    fixtures and win.
    """
    from src.screening.offensive import threshold_trigger

    monkeypatch.setattr(threshold_trigger, "LEDGER_PATH", tmp_path / "no-trigger-ledger.jsonl")
