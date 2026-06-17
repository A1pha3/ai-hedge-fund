"""组合风险指标 + API 端点测试 — 全部 mock, 不依赖外部数据/网络。"""

from __future__ import annotations

import math
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.routes import risk_metrics as risk_metrics_route
from app.backend.routes.risk_metrics import (
    PositionInput,
    RiskSnapshotRequest,
    RiskSnapshotResponse,
)
from src.portfolio.risk_metrics import (
    compute_risk_snapshot,
    DRAWDOWN_WARNING_THRESHOLD,
    INDUSTRY_CONCENTRATION_WARNING_THRESHOLD,
    RiskSnapshot,
    SINGLE_POSITION_WARNING_THRESHOLD,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _position(ticker: str, market_value: float, industry_sw: str = "电子") -> dict[str, Any]:
    return {
        "ticker": ticker,
        "market_value": market_value,
        "industry_sw": industry_sw,
    }


def _return(date: str, ticker: str, return_pct: float) -> dict[str, Any]:
    return {"date": date, "ticker": ticker, "return_pct": return_pct}


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(risk_metrics_route.router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. 单一持仓 → VaR/CVaR 计算正确
# ---------------------------------------------------------------------------


def test_single_position_var_cvar_uses_only_observation() -> None:
    positions = [_position("000001.SZ", market_value=1_000_000.0, industry_sw="银行")]
    # 单一标的, 只有 -3% 这一个观测点 → VaR/CVaR @95% 应 = 3% * 1M = 30,000
    lookback = [_return("2026-06-05", "000001.SZ", -0.03)]
    snapshot = compute_risk_snapshot(positions, lookback)
    assert snapshot.position_count == 1
    assert math.isclose(snapshot.var_95, 30_000.0, rel_tol=1e-3)
    assert math.isclose(snapshot.cvar_95, 30_000.0, rel_tol=1e-3)
    # 99% confidence uses the same single tail (no additional observations)
    assert snapshot.var_99 >= snapshot.var_95 >= 0.0


# ---------------------------------------------------------------------------
# 2. 多持仓分散 → VaR 更低
# ---------------------------------------------------------------------------


def test_diversified_portfolio_has_lower_var_than_concentrated() -> None:
    concentrated_value = 1_000_000.0
    concentrated_positions = [_position("X", concentrated_value, industry_sw="银行")]
    diversified_positions = [
        _position("A", 200_000.0, industry_sw="银行"),
        _position("B", 200_000.0, industry_sw="电子"),
        _position("C", 200_000.0, industry_sw="医药"),
        _position("D", 200_000.0, industry_sw="汽车"),
        _position("E", 200_000.0, industry_sw="食品"),
    ]
    # Mixed returns: when diversified, the worst observation is the most-negative of all
    lookback = [
        _return("2026-06-01", "X", -0.08),
        _return("2026-06-01", "A", -0.02),
        _return("2026-06-01", "B", 0.01),
        _return("2026-06-01", "C", -0.01),
        _return("2026-06-01", "D", 0.00),
        _return("2026-06-01", "E", 0.02),
    ]
    conc_snapshot = compute_risk_snapshot(concentrated_positions, lookback)
    div_snapshot = compute_risk_snapshot(diversified_positions, lookback)
    assert div_snapshot.var_95 < conc_snapshot.var_95
    assert div_snapshot.cvar_95 < conc_snapshot.cvar_95


# ---------------------------------------------------------------------------
# 3. 行业集中度计算
# ---------------------------------------------------------------------------


def test_industry_concentration_normalised_to_one() -> None:
    positions = [
        _position("A", 400_000.0, industry_sw="银行"),
        _position("B", 300_000.0, industry_sw="银行"),
        _position("C", 200_000.0, industry_sw="电子"),
        _position("D", 100_000.0, industry_sw="医药"),
    ]
    snapshot = compute_risk_snapshot(positions, [])
    total = sum(snapshot.industry_concentration.values())
    assert math.isclose(total, 1.0, abs_tol=1e-6)
    assert math.isclose(snapshot.industry_concentration["银行"], 0.7, abs_tol=1e-6)
    assert math.isclose(snapshot.industry_concentration["电子"], 0.2, abs_tol=1e-6)
    assert math.isclose(snapshot.industry_concentration["医药"], 0.1, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# 4. 集中度预警触发 (>25%)
# ---------------------------------------------------------------------------


def test_concentration_warning_triggers_above_industry_threshold() -> None:
    positions = [
        _position("A", 600_000.0, industry_sw="银行"),
        _position("B", 200_000.0, industry_sw="电子"),
        _position("C", 200_000.0, industry_sw="医药"),
    ]
    snapshot = compute_risk_snapshot(positions, [])
    assert snapshot.industry_concentration["银行"] > INDUSTRY_CONCENTRATION_WARNING_THRESHOLD
    assert snapshot.concentration_warning is True

    # 分散: 每个行业 <= 25% 且每只标的 < 12% → 预警应解除
    diversified = [
        _position("A", 100_000.0, industry_sw="银行"),
        _position("B", 100_000.0, industry_sw="银行"),
        _position("C", 100_000.0, industry_sw="电子"),
        _position("D", 100_000.0, industry_sw="电子"),
        _position("E", 100_000.0, industry_sw="医药"),
        _position("F", 100_000.0, industry_sw="医药"),
        _position("G", 100_000.0, industry_sw="汽车"),
        _position("H", 100_000.0, industry_sw="汽车"),
        _position("I", 100_000.0, industry_sw="食品"),
    ]
    snapshot_ok = compute_risk_snapshot(diversified, [])
    assert snapshot_ok.concentration_warning is False


# ---------------------------------------------------------------------------
# 5. 当前回撤计算
# ---------------------------------------------------------------------------


def test_current_drawdown_computed_from_equity_curve() -> None:
    # 0% → +10% → 0% → -20% → -5%: peak 1.1, last 0.95 → drawdown ≈ 13.6%
    lookback = [
        _return("2026-06-01", "A", 0.00),
        _return("2026-06-02", "A", 0.10),
        _return("2026-06-03", "A", -0.0909),  # 1.10 → 1.0
        _return("2026-06-04", "A", -0.20),  # 1.0 → 0.8
        _return("2026-06-05", "A", 0.0625),  # 0.8 → 0.85
    ]
    positions = [_position("A", 850_000.0)]
    snapshot = compute_risk_snapshot(positions, lookback)
    # peak 1.1, last 0.85 → (1.1-0.85)/1.1 ≈ 0.2272
    assert math.isclose(snapshot.current_drawdown, (1.10 - 0.85) / 1.10, abs_tol=1e-3)


# ---------------------------------------------------------------------------
# 6. 最大回撤计算
# ---------------------------------------------------------------------------


def test_max_drawdown_captures_worst_peak_to_trough() -> None:
    lookback = [
        _return("d1", "A", 0.0),  # 1.0
        _return("d2", "A", 0.20),  # 1.20
        _return("d3", "A", -0.50),  # 0.60
        _return("d4", "A", 0.50),  # 0.90
        _return("d5", "A", -0.10),  # 0.81
    ]
    snapshot = compute_risk_snapshot([_position("A", 810_000.0)], lookback)
    # peak 1.20, trough 0.60 → max_dd = 0.50
    assert math.isclose(snapshot.max_drawdown, 0.50, abs_tol=1e-6)
    # current_dd: last 0.81 vs peak 1.20 → (1.20-0.81)/1.20 ≈ 0.325
    assert math.isclose(snapshot.current_drawdown, (1.20 - 0.81) / 1.20, abs_tol=1e-3)


# ---------------------------------------------------------------------------
# 7. 回撤预警线 (>10%)
# ---------------------------------------------------------------------------


def test_drawdown_warning_triggers_above_threshold() -> None:
    # last vs peak = 0.85 / 1.0 = -15% drawdown → warning
    lookback = [
        _return("d1", "A", 0.0),  # 1.0
        _return("d2", "A", -0.15),  # 0.85
    ]
    snapshot = compute_risk_snapshot([_position("A", 850_000.0)], lookback)
    assert snapshot.current_drawdown >= DRAWDOWN_WARNING_THRESHOLD
    assert snapshot.drawdown_warning is True

    # -5% drawdown → no warning
    lookback_ok = [
        _return("d1", "A", 0.0),
        _return("d2", "A", -0.05),
    ]
    snapshot_ok = compute_risk_snapshot([_position("A", 950_000.0)], lookback_ok)
    assert snapshot_ok.current_drawdown < DRAWDOWN_WARNING_THRESHOLD
    assert snapshot_ok.drawdown_warning is False


# ---------------------------------------------------------------------------
# 8. 单一标的占比上限检查
# ---------------------------------------------------------------------------


def test_single_position_max_triggers_concentration_warning() -> None:
    positions = [
        _position("A", 130_000.0, industry_sw="银行"),
        _position("B", 100_000.0, industry_sw="电子"),
        _position("C", 100_000.0, industry_sw="医药"),
        _position("D", 100_000.0, industry_sw="汽车"),
        _position("E", 100_000.0, industry_sw="食品"),
    ]
    snapshot = compute_risk_snapshot(positions, [])
    assert snapshot.single_position_max >= SINGLE_POSITION_WARNING_THRESHOLD
    assert snapshot.concentration_warning is True

    # < 12% 时不应触发
    positions_ok = [_position(t, 100_000.0, industry_sw=f"ind{i}") for i, t in enumerate("ABCDEFGHIJKL", start=1)]
    snapshot_ok = compute_risk_snapshot(positions_ok, [])
    assert snapshot_ok.single_position_max < SINGLE_POSITION_WARNING_THRESHOLD
    assert snapshot_ok.concentration_warning is False


# ---------------------------------------------------------------------------
# 9. 端点存在 + 注册
# ---------------------------------------------------------------------------


def test_endpoint_registered_in_api_router() -> None:
    from app.backend.routes import api_router

    paths = {route.path for route in api_router.routes}  # type: ignore[attr-defined]
    assert "/portfolio/risk-snapshot" in paths
    assert "/portfolio/risk-snapshot/thresholds" in paths


def test_endpoint_returns_empty_snapshot_on_get(client: TestClient) -> None:
    resp = client.get("/portfolio/risk-snapshot")
    assert resp.status_code == 200
    data = resp.json()
    assert data["position_count"] == 0
    assert data["var_95"] == 0.0
    assert data["cvar_95"] == 0.0
    assert data["max_drawdown"] == 0.0
    assert data["drawdown_warning"] is False
    assert data["concentration_warning"] is False
    assert data["industry_concentration"] == {}


# ---------------------------------------------------------------------------
# 10. 端点响应结构
# ---------------------------------------------------------------------------


def test_endpoint_post_computes_full_snapshot(client: TestClient) -> None:
    payload = {
        "positions": [
            {"ticker": "A", "market_value": 600_000.0, "industry_sw": "银行"},
            {"ticker": "B", "market_value": 200_000.0, "industry_sw": "电子"},
            {"ticker": "C", "market_value": 200_000.0, "industry_sw": "医药"},
        ],
        "lookback_returns": [
            {"date": "2026-06-01", "ticker": "A", "return_pct": -0.05},
            {"date": "2026-06-01", "ticker": "B", "return_pct": 0.01},
            {"date": "2026-06-01", "ticker": "C", "return_pct": -0.02},
            {"date": "2026-06-02", "ticker": "A", "return_pct": -0.03},
            {"date": "2026-06-02", "ticker": "B", "return_pct": 0.00},
            {"date": "2026-06-02", "ticker": "C", "return_pct": -0.01},
        ],
        "timestamp": "2026-06-07T09:30:00",
        "var_horizon_days": 1,
        "confidence_levels": [0.95, 0.99],
    }
    resp = client.post("/portfolio/risk-snapshot", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # 结构完整性
    required_keys = {
        "timestamp",
        "portfolio_value",
        "var_95",
        "var_99",
        "cvar_95",
        "cvar_99",
        "max_drawdown",
        "current_drawdown",
        "drawdown_warning",
        "industry_concentration",
        "concentration_warning",
        "single_position_max",
        "position_count",
        "beta_adjusted",
    }
    assert required_keys.issubset(data.keys())
    assert data["position_count"] == 3
    assert math.isclose(data["portfolio_value"], 1_000_000.0, rel_tol=1e-6)
    # 银行 60% > 25% → 预警
    assert data["concentration_warning"] is True
    assert data["industry_concentration"]["银行"] == pytest.approx(0.6, abs=1e-4)
    # VaR/CVaR 应为正 (历史有负收益观测)
    assert data["var_95"] > 0
    assert data["cvar_95"] > 0
    assert data["var_99"] >= data["var_95"]


def test_thresholds_endpoint_returns_three_thresholds(client: TestClient) -> None:
    resp = client.get("/portfolio/risk-snapshot/thresholds")
    assert resp.status_code == 200
    data = resp.json()
    assert "thresholds" in data
    assert math.isclose(data["thresholds"]["industry_concentration"], INDUSTRY_CONCENTRATION_WARNING_THRESHOLD)
    assert math.isclose(data["thresholds"]["single_position"], SINGLE_POSITION_WARNING_THRESHOLD)
    assert math.isclose(data["thresholds"]["drawdown"], DRAWDOWN_WARNING_THRESHOLD)


# ---------------------------------------------------------------------------
# 边界与稳健性 (附加)
# ---------------------------------------------------------------------------


def test_empty_inputs_produce_zero_snapshot() -> None:
    snapshot = compute_risk_snapshot([], [])
    assert snapshot.position_count == 0
    assert snapshot.portfolio_value == 0.0
    assert snapshot.var_95 == 0.0
    assert snapshot.cvar_99 == 0.0
    assert snapshot.industry_concentration == {}
    assert snapshot.concentration_warning is False
    assert snapshot.drawdown_warning is False
    assert snapshot.beta_adjusted == 1.0  # fallback to market-neutral


def test_nan_and_inf_values_dont_crash() -> None:
    # NaN/Inf 必须被吸收为 0 (GAMMA-009)
    positions = [
        {"ticker": "A", "market_value": float("nan"), "industry_sw": "银行"},
        {"ticker": "B", "market_value": float("inf"), "industry_sw": "电子"},
    ]
    lookback = [
        {"date": "d1", "ticker": "A", "return_pct": float("nan")},
        {"date": "d1", "ticker": "B", "return_pct": float("inf")},
    ]
    snapshot = compute_risk_snapshot(positions, lookback)
    assert all(math.isfinite(v) for v in (snapshot.var_95, snapshot.var_99, snapshot.cvar_95, snapshot.cvar_99, snapshot.max_drawdown, snapshot.current_drawdown, snapshot.single_position_max, snapshot.portfolio_value))
    assert all(math.isfinite(w) for w in snapshot.industry_concentration.values())


def test_position_without_industry_falls_back_to_unknown() -> None:
    positions = [{"ticker": "A", "market_value": 100_000.0}]  # no industry_sw
    snapshot = compute_risk_snapshot(positions, [])
    assert "UNKNOWN" in snapshot.industry_concentration
    assert math.isclose(snapshot.industry_concentration["UNKNOWN"], 1.0, abs_tol=1e-6)


def test_var_horizon_days_scales_by_sqrt() -> None:
    positions = [_position("A", 1_000_000.0)]
    lookback = [_return(f"d{i}", "A", -0.02) for i in range(20)]
    s1 = compute_risk_snapshot(positions, lookback, var_horizon_days=1)
    s4 = compute_risk_snapshot(positions, lookback, var_horizon_days=4)
    assert math.isclose(s4.var_95, s1.var_95 * math.sqrt(4), rel_tol=1e-6)
    assert math.isclose(s4.cvar_95, s1.cvar_95 * 2, rel_tol=1e-6)


def test_response_model_accepts_snapshot_dict() -> None:
    snap = compute_risk_snapshot(
        [_position("A", 100.0)],
        [_return("d1", "A", -0.01)],
        timestamp="2026-06-07",
    )
    resp = RiskSnapshotResponse.from_snapshot(snap)
    assert resp.timestamp == "2026-06-07"
    assert resp.position_count == 1
    # Round-trippable to dict
    assert RiskSnapshot(**resp.model_dump()) == snap


def test_request_model_validation() -> None:
    req = RiskSnapshotRequest(
        positions=[PositionInput(ticker="A", market_value=100.0, industry_sw="银行")],
        lookback_returns=[],
        var_horizon_days=1,
        confidence_levels=(0.95, 0.99),
    )
    assert req.positions[0].ticker == "A"
    # var_horizon_days out of range
    with pytest.raises(Exception):
        RiskSnapshotRequest(var_horizon_days=99)


# ---------------------------------------------------------------------------
# GAMMA regression: CVaR off-by-one tail
# ---------------------------------------------------------------------------


def test_cvar_tail_excludes_var_boundary_observation() -> None:
    """CVaR must average the tail strictly *beyond* VaR, not including the VaR boundary.

    With 20 sorted returns at 95% confidence:
      tail_index = floor(0.05 * 20) = 1
      VaR  = -cleaned[1]  (2nd worst loss)
      CVaR should average cleaned[0:1] (the single worst loss), NOT cleaned[0:2].
    """
    from src.portfolio.risk_metrics import _histogram_cvar, _histogram_var

    # 20 returns sorted ascending: -0.10, -0.09, -0.08, ... , 0.08, 0.09
    returns = [i * 0.01 for i in range(-10, 10)]  # 20 values

    var_95 = _histogram_var(returns, 0.95)
    cvar_95 = _histogram_cvar(returns, 0.95)

    # VaR at 95%: tail_index = floor(0.05*20) = 1, so VaR = -cleaned[1] = 0.09
    assert math.isclose(var_95, 0.09, abs_tol=1e-6)

    # CVaR should average only the single worst observation: -cleaned[0] = 0.10
    # (NOT the average of cleaned[0] and cleaned[1] = 0.095)
    assert math.isclose(cvar_95, 0.10, abs_tol=1e-6), (
        f"CVaR={cvar_95} should be 0.10 (single worst), not 0.095 (average of 2)"
    )

    # CVaR must be >= VaR (tail risk is always at least as bad as VaR)
    assert cvar_95 >= var_95


# ---------------------------------------------------------------------------
# ALPHA regression: beta computed from aggregated portfolio returns, not per-ticker rows
# ---------------------------------------------------------------------------


def test_beta_uses_aggregated_portfolio_returns_not_per_ticker_rows() -> None:
    """``beta_adjusted`` must regress the *value-weighted portfolio* daily-return
    series against the benchmark — NOT the raw per-ticker ``return_pct`` rows.

    Regression guard: ``compute_risk_snapshot`` previously passed the raw
    ``lookback_returns`` (per-ticker rows ``{date, ticker, return_pct}``) to
    ``_resolve_beta``, which read ``return_pct`` from every per-ticker row. That
    conflates cross-sectional stock variation with the time-series portfolio
    series: with N holdings × D days it builds an N·D-length series that is
    neither date-aligned with the benchmark nor a portfolio return, so the
    resulting beta is meaningless.

    This test builds an equal-weighted two-ticker portfolio where ticker A
    moves at 2.0× the benchmark and ticker B at 0.5×. The value-weighted
    portfolio beta is therefore (2.0 + 0.5) / 2 = 1.25. The per-ticker-rows
    regression instead regresses a shuffled bag of all 2.0× and 0.5× moves
    against the benchmark, collapsing toward the unweighted average slope.
    """
    # 20 deterministic benchmark daily returns (decimal, e.g. 0.01 = +1%)
    bench = [0.010 * (1 if i % 2 == 0 else -1) + 0.002 * (i - 10) / 10.0 for i in range(20)]
    # Ticker A tracks 2.0x benchmark, B tracks 0.5x (no intercept, deterministic)
    positions = [
        {"ticker": "A", "market_value": 100_000.0, "industry_sw": "电子"},
        {"ticker": "B", "market_value": 100_000.0, "industry_sw": "电子"},
    ]
    lookback = []
    for i, b in enumerate(bench):
        date = f"2026-06-{i + 1:02d}"
        lookback.append({"date": date, "ticker": "A", "return_pct": 2.0 * b})
        lookback.append({"date": date, "ticker": "B", "return_pct": 0.5 * b})

    snapshot = compute_risk_snapshot(positions, lookback, benchmark_returns=bench)
    # Expected value-weighted portfolio beta = (2.0 + 0.5) / 2 = 1.25
    assert math.isclose(snapshot.beta_adjusted, 1.25, abs_tol=0.05), (
        f"beta_adjusted={snapshot.beta_adjusted} should be ~1.25 (value-weighted avg of "
        f"2.0 and 0.5), got a per-ticker-rows regression result instead"
    )


def test_beta_single_ticker_matches_its_own_slope() -> None:
    """Sanity check: a single-ticker portfolio's beta must equal that ticker's
    slope vs the benchmark (this held before the fix too, and must still hold)."""
    bench = [0.010 * (1 if i % 2 == 0 else -1) for i in range(20)]
    positions = [_position("A", 100_000.0)]
    lookback = [_return(f"d{i}", "A", 1.5 * b) for i, b in enumerate(bench)]
    snapshot = compute_risk_snapshot(positions, lookback, benchmark_returns=bench)
    assert math.isclose(snapshot.beta_adjusted, 1.5, abs_tol=0.05)


def test_beta_falls_back_to_market_neutral_without_benchmark() -> None:
    """No benchmark series -> market-neutral fallback (1.0), unchanged by the fix."""
    positions = [_position("A", 100_000.0)]
    lookback = [_return(f"d{i}", "A", 0.01 * (1 if i % 2 == 0 else -1)) for i in range(20)]
    snapshot = compute_risk_snapshot(positions, lookback, benchmark_returns=None)
    assert snapshot.beta_adjusted == 1.0


def test_beta_length_mismatch_falls_back_to_market_neutral(caplog) -> None:
    """BH-030: when ``portfolio`` daily returns and ``benchmark`` have different
    lengths, ``_resolve_beta`` used to pair ``portfolio[:n]`` with
    ``benchmark[:n]``, silently misaligning dates.

    ``_weighted_portfolio_daily_returns`` legitimately drops days with no
    observations (line 199-200), while the API-supplied ``benchmark_returns``
    is a continuous trading-day series. A length mismatch therefore means the
    two series are NOT date-aligned, and pairing by position produces a
    meaningless (even wrong-sign) beta.

    Regression guard: a perfect tracker (true beta = 1.0) with one dropped day
    must NOT report a wrong-sign beta. It must fall back to the market-neutral
    proxy (1.0) and emit a diagnosable warning so operators know beta degraded.
    """
    import logging

    bench = [0.010 * (1 if i % 2 == 0 else -1) for i in range(20)]
    # Single ticker perfectly tracking the benchmark (true beta = 1.0), but drop
    # day index 5 to simulate a no-observation day being skipped.
    lookback = [
        _return(f"d{i}", "A", bench[i]) for i in range(20) if i != 5
    ]  # 19 days vs 20-day benchmark -> length mismatch
    positions = [_position("A", 100_000.0)]

    with caplog.at_level(logging.WARNING, logger="src.portfolio.risk_metrics"):
        snapshot = compute_risk_snapshot(positions, lookback, benchmark_returns=bench)

    # A length-misaligned series must not yield a wrong-sign beta; fall back to
    # the market-neutral proxy and warn so the degradation is observable.
    assert snapshot.beta_adjusted == 1.0, (
        f"length-mismatched portfolio/benchmark must fall back to market-neutral "
        f"1.0, got {snapshot.beta_adjusted} (silent date misalignment)"
    )
    assert any(
        "beta" in rec.message.lower() and ("mismatch" in rec.message.lower() or "align" in rec.message.lower())
        for rec in caplog.records
    ), "beta length-mismatch degradation must emit a diagnosable warning (BH-030)"
