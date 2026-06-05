"""Portfolio return attribution API endpoint.

GET /api/portfolio/attribution?start=DATE&end=DATE

Returns Brinson attribution decomposition: allocation contribution,
selection contribution, residual, and per-ticker breakdown.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from pydantic import BaseModel
from src.portfolio.return_attribution import (
    AttributionResult,
    brinson_attribution,
)

router = APIRouter(prefix="/portfolio")


class AttributionRequest(BaseModel):
    """Request body for POST-based attribution (optional, for complex scenarios)."""

    ticker_returns: dict[str, float]
    ticker_market_values: dict[str, float]
    total_portfolio_value: float
    benchmark_weights: dict[str, float] | None = None
    benchmark_returns: dict[str, float] | None = None
    start_date: str = ""
    end_date: str = ""


class TickerAttributionResponse(BaseModel):
    ticker: str
    portfolio_weight: float
    benchmark_weight: float
    portfolio_return: float
    benchmark_return: float
    allocation_contribution: float
    selection_contribution: float
    total_contribution: float


class AttributionResponse(BaseModel):
    start_date: str
    end_date: str
    total_portfolio_return: float
    total_benchmark_return: float
    total_allocation_contribution: float
    total_selection_contribution: float
    total_residual: float
    tickers: list[TickerAttributionResponse]


@router.get(
    path="/attribution",
    response_model=AttributionResponse,
    summary="Portfolio return attribution (Brinson model)",
    description="Decomposes portfolio returns into allocation and selection contributions per ticker.",
)
def get_attribution(
    start: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end: str = Query(..., description="End date (YYYY-MM-DD)"),
    tickers: str | None = Query(None, description="Comma-separated ticker list"),
    returns: str | None = Query(None, description="Comma-separated returns (parallel to tickers)"),
    weights: str | None = Query(None, description="Comma-separated portfolio market values (parallel to tickers)"),
    total_value: float | None = Query(None, description="Total portfolio value at start"),
    benchmark_weights_csv: str | None = Query(None, description="Comma-separated benchmark weights (parallel to tickers)"),
    benchmark_returns_csv: str | None = Query(None, description="Comma-separated benchmark returns (parallel to tickers)"),
) -> AttributionResponse:
    """Compute Brinson attribution for the given parameters.

    For GET requests, pass tickers, returns, and weights as comma-separated strings.
    For complex payloads, use the POST endpoint.
    """
    # Validate date format
    try:
        datetime.strptime(start, "%Y-%m-%d")
        datetime.strptime(end, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format")

    if not tickers or not returns or not weights or total_value is None:
        raise HTTPException(
            status_code=400,
            detail="tickers, returns, weights, and total_value are required query parameters",
        )

    ticker_list = [t.strip() for t in tickers.split(",")]
    returns_list = [float(r.strip()) for r in returns.split(",")]
    weights_list = [float(w.strip()) for w in weights.split(",")]

    if len(ticker_list) != len(returns_list) or len(ticker_list) != len(weights_list):
        raise HTTPException(
            status_code=400,
            detail="tickers, returns, and weights must have the same number of comma-separated values",
        )

    ticker_returns = dict(zip(ticker_list, returns_list))
    ticker_market_values = dict(zip(ticker_list, weights_list))

    b_weights: dict[str, float] | None = None
    b_returns: dict[str, float] | None = None

    if benchmark_weights_csv:
        bw_list = [float(w.strip()) for w in benchmark_weights_csv.split(",")]
        if len(bw_list) != len(ticker_list):
            raise HTTPException(status_code=400, detail="benchmark_weights must match ticker count")
        b_weights = dict(zip(ticker_list, bw_list))

    if benchmark_returns_csv:
        br_list = [float(r.strip()) for r in benchmark_returns_csv.split(",")]
        if len(br_list) != len(ticker_list):
            raise HTTPException(status_code=400, detail="benchmark_returns must match ticker count")
        b_returns = dict(zip(ticker_list, br_list))

    result = brinson_attribution(
        start_date=start,
        end_date=end,
        ticker_returns=ticker_returns,
        ticker_market_values=ticker_market_values,
        total_portfolio_value=total_value,
        benchmark_weights=b_weights,
        benchmark_returns=b_returns,
    )

    return _result_to_response(result)


@router.post(
    path="/attribution",
    response_model=AttributionResponse,
    summary="Portfolio return attribution (POST, JSON body)",
)
def post_attribution(req: AttributionRequest) -> AttributionResponse:
    """Compute Brinson attribution from a JSON body."""
    if not req.start_date or not req.end_date:
        raise HTTPException(status_code=400, detail="start_date and end_date are required")

    try:
        datetime.strptime(req.start_date, "%Y-%m-%d")
        datetime.strptime(req.end_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format")

    result = brinson_attribution(
        start_date=req.start_date,
        end_date=req.end_date,
        ticker_returns=req.ticker_returns,
        ticker_market_values=req.ticker_market_values,
        total_portfolio_value=req.total_portfolio_value,
        benchmark_weights=req.benchmark_weights,
        benchmark_returns=req.benchmark_returns,
    )

    return _result_to_response(result)


def _result_to_response(result: AttributionResult) -> AttributionResponse:
    """Convert internal AttributionResult to API response model."""
    return AttributionResponse(
        start_date=result.start_date,
        end_date=result.end_date,
        total_portfolio_return=result.total_portfolio_return,
        total_benchmark_return=result.total_benchmark_return,
        total_allocation_contribution=result.total_allocation_contribution,
        total_selection_contribution=result.total_selection_contribution,
        total_residual=result.total_residual,
        tickers=[
            TickerAttributionResponse(
                ticker=t.ticker,
                portfolio_weight=t.portfolio_weight,
                benchmark_weight=t.benchmark_weight,
                portfolio_return=t.portfolio_return,
                benchmark_return=t.benchmark_return,
                allocation_contribution=t.allocation_contribution,
                selection_contribution=t.selection_contribution,
                total_contribution=t.total_contribution,
            )
            for t in sorted(result.tickers, key=lambda x: x.total_contribution, reverse=True)
        ],
    )
