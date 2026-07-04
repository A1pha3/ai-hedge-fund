"""NS-14 (part 3): screening route error-handling hardening.

Public screening endpoints (registered without ``_auth``) must not leak
internal exception detail to anonymous callers. Two leakage patterns:

  - Pattern A: the 5 endpoints without ``@safe_route`` let unhandled
    exceptions surface as an inconsistent plain-text 500 (and a full
    traceback when the app runs with ``debug=True``), with no route-level
    logging.
  - Pattern B: ``run_auto_screening`` catches ``Exception`` and re-raises
    ``HTTPException(500, detail=f"一键选股失败: {exc}")`` — this embeds
    ``str(exc)`` into the JSON response body regardless of debug mode.

``@safe_route`` (the established pattern, 54 existing usages) converts any
non-``HTTPException`` into a generic ``HTTPException(500, "Internal server
error")`` plus a logged traceback. Delegating ``run_auto_screening``'s
catch-all to ``@safe_route`` removes the detail leak while preserving the
meaningful 503 (empty pool) / 504 (timeout) status codes.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.routes.screening import router as screening_router

# A distinctive token planted into the fake exception message. If any of it
# reaches the HTTP response body, the endpoint leaks internal detail.
_LEAKED_SECRET = "LEAKED_INTERNAL_DETAIL_marker_hunter2_token"

# Endpoints that must be hardened (every screening route handler).
_EXPECTED_SAFE_ROUTE_PATHS = {
    "/api/screening/auto",
    "/api/screening/latest",
    "/api/screening/compare",
    "/api/screening/conditional-orders",
    "/api/screening/custom-weights",
    "/api/screening/winrate-dashboard",
    "/api/screening/stock-detail/{ticker}",
}


def _build_client(*, raise_server_exceptions: bool = True) -> TestClient:
    """Minimal TestClient over the screening router.

    ``raise_server_exceptions=False`` lets Starlette turn a truly unhandled
    exception into a 500 response so the assertion can inspect the body
    (needed for the Pattern A RED state before ``@safe_route`` is applied).
    """
    app = FastAPI()
    app.include_router(screening_router)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


# ---------------------------------------------------------------------------
# Pattern B: /auto must not embed str(exc) into the 500 detail
# ---------------------------------------------------------------------------


def test_auto_internal_error_does_not_leak_exception_detail() -> None:
    """A non-ValueError/non-Timeout internal error must return a generic 500.

    Before the fix the catch-all wrapped the message into
    ``f"一键选股失败: {exc}"`` so the raw exception text reached anonymous
    callers via the JSON ``detail`` field.
    """
    client = _build_client()
    with (
        patch.dict("os.environ", {"TUSHARE_TOKEN": "test_token"}, clear=False),
        patch(
            "app.backend.routes.screening.compute_auto_screening_results",
            side_effect=RuntimeError(f"db connect failed: {_LEAKED_SECRET}"),
        ),
    ):
        response = client.post("/api/screening/auto", json={"trade_date": "20260607"})

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detail"] == "Internal server error"
    assert _LEAKED_SECRET not in response.text


# ---------------------------------------------------------------------------
# Pattern A: the other public endpoints must sanitise unhandled errors
# ---------------------------------------------------------------------------

# (http_method, path, patch_target, json_body). ``patch_target`` is the
# fully-qualified name of a function each endpoint calls *after* request
# validation so the fake RuntimeError reaches the handler body.
_PATTERN_A_CASES = [
    pytest.param(
        "get",
        "/api/screening/compare?tickers=000001,000002",
        "src.screening.compare_tool.load_latest_recommendations",
        None,
        id="compare",
    ),
    pytest.param(
        "get",
        "/api/screening/conditional-orders",
        "src.screening.compare_tool.load_latest_recommendations",
        None,
        id="conditional-orders",
    ),
    pytest.param(
        "post",
        "/api/screening/custom-weights",
        "app.backend.routes.screening._load_latest_auto_screening_payload",
        {
            "trend": 0.4,
            "mean_reversion": 0.2,
            "fundamental": 0.2,
            "event_sentiment": 0.2,
        },
        id="custom-weights",
    ),
    pytest.param(
        "get",
        "/api/screening/winrate-dashboard",
        "src.screening.winrate_dashboard.compute_winrate_dashboard",
        None,
        id="winrate-dashboard",
    ),
    pytest.param(
        "get",
        "/api/screening/stock-detail/000001",
        "src.screening.compare_tool.load_latest_recommendations",
        None,
        id="stock-detail",
    ),
]


@pytest.mark.parametrize("method,path,patch_target,json_body", _PATTERN_A_CASES)
def test_screening_route_internal_error_returns_sanitized_500(
    method: str,
    path: str,
    patch_target: str,
    json_body: dict | None,
) -> None:
    """An unhandled internal error on a public screening route must become a
    generic JSON 500, never the raw exception message.
    """
    client = _build_client(raise_server_exceptions=False)
    with patch(patch_target, side_effect=RuntimeError(f"boom: {_LEAKED_SECRET}")):
        if method == "get":
            response = client.get(path)
        else:
            response = client.post(path, json=json_body)

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detail"] == "Internal server error"
    assert _LEAKED_SECRET not in response.text


# ---------------------------------------------------------------------------
# Guard: every screening route handler must be wrapped by @safe_route
# ---------------------------------------------------------------------------


def test_all_screening_routes_are_safe_route_wrapped() -> None:
    """No screening route may regress to an unwrapped handler.

    ``@safe_route`` uses ``functools.wraps``, which sets ``__wrapped__`` on
    the wrapper. A bare handler has no such attribute, so this detects any
    future endpoint added without the decorator.
    """
    route_paths = {r.path for r in screening_router.routes if hasattr(r, "path")}
    assert _EXPECTED_SAFE_ROUTE_PATHS <= route_paths

    unwrapped = [r.path for r in screening_router.routes if hasattr(r, "path") and r.path in _EXPECTED_SAFE_ROUTE_PATHS and not hasattr(r.endpoint, "__wrapped__")]
    assert unwrapped == [], f"screening routes missing @safe_route: {unwrapped}"
