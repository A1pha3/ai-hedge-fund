"""DAILY_BAR_PROXY execution adapters.

Two non-interchangeable adapters share one settlement core:

- :class:`~src.screening.offensive.v3.execution.proxy.DailyBarProxy` is the
  authorised adapter that resolves a sealed, permitted entry plan into
  capital truth;
- :class:`~src.screening.offensive.v3.execution.shadow_proxy.ShadowProxyAdapter`
  is the counterfactual adapter that reserves and settles committed
  ``ShadowDecision`` artifacts into an isolated arm ledger.

Both drive the shared :func:`~src.screening.offensive.v3.execution.proxy_core.settle_proxy_open`
core so they can never disagree on economics, and neither adapter may import
the other. Imports use the full submodule path (e.g.
``from src.screening.offensive.v3.execution.shadow_proxy import ShadowProxyAdapter``);
this package init stays import-light by design.
"""
