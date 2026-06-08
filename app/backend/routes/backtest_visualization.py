"""P0-4: Backtest visualization data endpoint.

Provides equity curve, drawdown, and monthly returns data for the React front-end
to render interactive charts. The data is computed from the same backtest
service that powers the streaming endpoint, but packaged in a single
non-streaming response for easy consumption by chart libraries.

Endpoints:
- GET /api/backtest/equity-curve-sample — sample data shape reference
- POST /api/backtest/equity-curve — compute equity curve from request payload

For live backtest runs, the streaming endpoint already sends per-day results
with portfolio_value. This endpoint exists to:
1. Document the expected data shape (sample endpoint)
2. Support re-computation from a saved payload (e.g. share a backtest result)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backtest", tags=["backtest"])


class EquityCurveRequest(BaseModel):
    """Request body for /equity-curve endpoint.

    Accepts an array of per-day results from a previously run backtest
    (the same shape as the streaming endpoint emits) and returns the
    derived equity curve, drawdown, and monthly returns.
    """

    daily_results: list[dict[str, Any]] = Field(
        ..., description="Array of per-day backtest results from a backtest run"
    )
    initial_capital: float = Field(
        ..., description="Initial portfolio value (for return calculations)"
    )


class EquityCurvePoint(BaseModel):
    date: str
    portfolio_value: float
    cumulative_return: float
    daily_return: float
    drawdown: float


class MonthlyReturn(BaseModel):
    year_month: str  # YYYY-MM
    return_pct: float


class EquityCurveResponse(BaseModel):
    equity_curve: list[EquityCurvePoint]
    monthly_returns: list[MonthlyReturn]
    summary: dict[str, Any]


def _compute_equity_curve(
    daily_results: list[dict[str, Any]], initial_capital: float
) -> tuple[list[EquityCurvePoint], list[MonthlyReturn], dict[str, Any]]:
    """Derive equity curve, drawdown, and monthly returns from per-day results."""
    if not daily_results:
        return [], [], {"total_days": 0}

    points: list[EquityCurvePoint] = []
    monthly_returns_map: dict[str, list[float]] = {}
    peak = initial_capital
    prev_value = initial_capital
    total_return = 0.0
    max_dd = 0.0

    for day in daily_results:
        value = float(day.get("portfolio_value", initial_capital))
        date = str(day.get("date", ""))
        daily_return = float(day.get("portfolio_return", 0.0) or 0.0)
        cumulative_return = (value / initial_capital) - 1.0 if initial_capital > 0 else 0.0

        # Track peak and drawdown
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak if peak > 0 else 0.0
        if drawdown > max_dd:
            max_dd = drawdown

        # Monthly bucket
        if date:
            year_month = date[:7]  # YYYY-MM
            monthly_returns_map.setdefault(year_month, []).append(daily_return)

        points.append(
            EquityCurvePoint(
                date=date,
                portfolio_value=round(value, 2),
                cumulative_return=round(cumulative_return, 6),
                daily_return=round(daily_return, 6),
                drawdown=round(drawdown, 6),
            )
        )
        prev_value = value

    # Compute monthly aggregate returns
    monthly_returns: list[MonthlyReturn] = []
    for ym, returns in sorted(monthly_returns_map.items()):
        # Compound daily returns within the month: (1+r1)(1+r2)...(1+rn) - 1
        compound = 1.0
        for r in returns:
            compound *= (1.0 + r)
        monthly_return = compound - 1.0
        monthly_returns.append(
            MonthlyReturn(year_month=ym, return_pct=round(monthly_return, 6))
        )

    final_value = points[-1].portfolio_value
    total_return = (final_value / initial_capital) - 1.0 if initial_capital > 0 else 0.0

    summary = {
        "total_days": len(points),
        "initial_capital": initial_capital,
        "final_value": round(final_value, 2),
        "total_return": round(total_return, 6),
        "max_drawdown": round(max_dd, 6),
        "trading_months": len(monthly_returns),
    }

    return points, monthly_returns, summary


@router.get("/equity-curve-sample")
async def equity_curve_sample() -> dict[str, Any]:
    """Return a sample equity curve data shape for documentation / chart development.

    Frontend developers can call this endpoint to understand the exact JSON
    structure the equity-curve endpoint produces. The data here is synthetic.
    """
    import datetime

    initial = 1_000_000.0
    sample_daily = []
    base = initial
    for i in range(60):
        date = (datetime.date(2026, 4, 1) + datetime.timedelta(days=i)).isoformat()
        # Simulate a moderate growth with noise
        base *= 1 + 0.001 + 0.005 * (0.5 - (i % 7) / 7)
        sample_daily.append({"date": date, "portfolio_value": round(base, 2), "portfolio_return": 0.001})

    points, monthly, summary = _compute_equity_curve(sample_daily, initial)
    return {
        "equity_curve": [p.model_dump() for p in points],
        "monthly_returns": [m.model_dump() for m in monthly],
        "summary": summary,
        "schema_notes": {
            "equity_curve[].date": "ISO date string (YYYY-MM-DD)",
            "equity_curve[].portfolio_value": "组合当日总值 (元)",
            "equity_curve[].cumulative_return": "相对初始资本累计收益 (decimal, e.g. 0.05 = 5%)",
            "equity_curve[].daily_return": "当日收益 (decimal)",
            "equity_curve[].drawdown": "相对历史峰值的回撤 (decimal, e.g. 0.10 = 10%)",
            "monthly_returns[].year_month": "YYYY-MM 格式",
            "monthly_returns[].return_pct": "该月累计收益 (decimal)",
            "summary": "汇总统计: initial_capital, final_value, total_return, max_drawdown",
        },
    }


@router.post("/equity-curve", response_model=EquityCurveResponse)
async def compute_equity_curve(request: EquityCurveRequest) -> EquityCurveResponse:
    """Compute equity curve, drawdown, and monthly returns from a backtest payload.

    Takes an array of per-day backtest results (same shape as the streaming
    endpoint emits) and returns derived visualization data. Use this endpoint
    when you have a saved/persisted backtest payload and want to render
    charts without re-running the backtest.
    """
    points, monthly, summary = _compute_equity_curve(
        request.daily_results, request.initial_capital
    )
    return EquityCurveResponse(
        equity_curve=points,
        monthly_returns=monthly,
        summary=summary,
    )
