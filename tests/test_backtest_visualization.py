"""Tests for the P0-4 backtest visualization endpoint."""

from __future__ import annotations

import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.auth.dependencies import require_write_access


def _load_endpoint_module():
    """Load the backtest_visualization module without going through full app init."""
    spec = importlib.util.spec_from_file_location("backtest_visualization", "app/backend/routes/backtest_visualization.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compute_equity_curve_empty():
    mod = _load_endpoint_module()
    points, monthly, summary = mod._compute_equity_curve([], 1_000_000.0)
    assert points == []
    assert monthly == []
    assert summary["total_days"] == 0


def test_compute_equity_curve_basic():
    mod = _load_endpoint_module()
    daily = [
        {"date": "2026-04-01", "portfolio_value": 1_000_000.0, "portfolio_return": 0.0},
        {"date": "2026-04-02", "portfolio_value": 1_010_000.0, "portfolio_return": 0.01},
        {"date": "2026-04-03", "portfolio_value": 1_005_000.0, "portfolio_return": -0.00495},
    ]
    points, monthly, summary = mod._compute_equity_curve(daily, 1_000_000.0)
    assert len(points) == 3
    assert points[0].portfolio_value == 1_000_000.0
    assert points[1].portfolio_value == 1_010_000.0
    assert points[1].cumulative_return == pytest.approx(0.01, rel=1e-4)
    assert points[2].drawdown > 0  # 1.005M from peak 1.01M = ~0.5% drawdown
    assert summary["max_drawdown"] > 0
    assert summary["final_value"] == 1_005_000.0
    assert summary["total_return"] == pytest.approx(0.005, rel=1e-4)


def test_compute_equity_curve_monthly_aggregation():
    mod = _load_endpoint_module()
    daily = []
    for i in range(45):  # 1.5 months
        date = f"2026-04-{(i % 30) + 1:02d}" if i < 30 else f"2026-05-{(i % 30) + 1:02d}"
        daily.append({"date": date, "portfolio_value": 1_000_000.0 * (1.001**i), "portfolio_return": 0.001})

    points, monthly, summary = mod._compute_equity_curve(daily, 1_000_000.0)
    assert len(monthly) >= 1
    assert summary["trading_months"] == len(monthly)


def test_compute_equity_curve_max_drawdown_tracks_peak():
    mod = _load_endpoint_module()
    # Build a sequence that goes up, down, recovers, hits new peak
    daily = [
        {"date": "2026-01-01", "portfolio_value": 100.0, "portfolio_return": 0.0},
        {"date": "2026-01-02", "portfolio_value": 110.0, "portfolio_return": 0.10},  # new peak
        {"date": "2026-01-03", "portfolio_value": 90.0, "portfolio_return": -0.181},  # -18% from peak
        {"date": "2026-01-04", "portfolio_value": 95.0, "portfolio_return": 0.0556},  # still below peak
        {"date": "2026-01-05", "portfolio_value": 120.0, "portfolio_return": 0.263},  # new peak
    ]
    points, _, summary = mod._compute_equity_curve(daily, 100.0)
    # Max drawdown should be (110-90)/110 = ~0.182
    assert summary["max_drawdown"] == pytest.approx(0.182, rel=1e-2)


def test_compute_equity_curve_derives_daily_returns_from_portfolio_value_when_payload_uses_cumulative_percent_points():
    mod = _load_endpoint_module()
    daily = [
        {"date": "2026-01-01", "portfolio_value": 100.0, "portfolio_return": 0.0},
        {"date": "2026-01-02", "portfolio_value": 110.0, "portfolio_return": 10.0},
        {"date": "2026-01-03", "portfolio_value": 121.0, "portfolio_return": 21.0},
    ]

    points, monthly, summary = mod._compute_equity_curve(daily, 100.0)

    assert points[1].daily_return == pytest.approx(0.10, rel=1e-6)
    assert points[2].daily_return == pytest.approx(0.10, rel=1e-6)
    assert monthly[0].return_pct == pytest.approx(0.21, rel=1e-6)
    assert summary["total_return"] == pytest.approx(0.21, rel=1e-6)


def test_compute_equity_curve_zero_initial_capital_safe():
    mod = _load_endpoint_module()
    daily = [{"date": "2026-01-01", "portfolio_value": 0.0, "portfolio_return": 0.0}]
    points, _, _ = mod._compute_equity_curve(daily, 0.0)
    assert points[0].cumulative_return == 0.0
    assert points[0].drawdown == 0.0


def test_param_compare_get_normalizes_latest_cli_report(monkeypatch):
    mod = _load_endpoint_module()
    app = FastAPI()
    app.include_router(mod.router)
    client = TestClient(app)

    monkeypatch.setattr(
        mod,
        "_load_latest_param_compare_payload",
        lambda: {
            "summary": {"total_combinations": 3, "max_workers": 2},
            "trials": [
                {
                    "trial_index": 0,
                    "params": {"top_n": 10},
                    "metrics": {"sharpe_ratio": 1.2},
                    "duration_seconds": 0.4,
                    "error": None,
                }
            ],
        },
    )

    response = client.get("/backtest/param-compare")

    assert response.status_code == 200
    body = response.json()
    assert body["total_combinations"] == 3
    assert body["max_workers"] == 2
    assert body["trials"][0]["params"]["top_n"] == 10


def test_param_compare_post_round_trips_report(monkeypatch):
    mod = _load_endpoint_module()
    app = FastAPI()
    app.include_router(mod.router)
    client = TestClient(app)
    saved_payloads: list[dict] = []

    monkeypatch.setattr(mod, "_save_param_compare_payload", lambda payload: saved_payloads.append(payload))
    app.dependency_overrides[require_write_access] = lambda: object()

    report = {
        "trials": [
            {
                "trial_index": 0,
                "params": {"top_n": 10},
                "metrics": {"sharpe_ratio": 1.1},
                "duration_seconds": 0.5,
                "error": None,
            }
        ],
        "total_combinations": 1,
        "max_workers": 2,
    }

    response = client.post("/backtest/param-compare", json=report)

    assert response.status_code == 200
    assert response.json() == report
    assert saved_payloads == [report]


import pytest
