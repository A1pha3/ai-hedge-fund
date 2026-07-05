"""FastAPI routes for the research lookback audit (feature 6.2)."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.backend.routes._common import safe_route
from src.research.lookback_audit import LookbackAuditResult, run_lookback_audit

router = APIRouter(prefix="/research", tags=["research"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class TickerAuditResultResponse(BaseModel):
    ticker: str
    rank: int
    score_final: float
    entry_date: str
    entry_price: float | None = None
    exit_date: str | None = None
    exit_price: float | None = None
    return_pct: float | None = None
    max_drawdown_pct: float | None = None
    max_return_pct: float | None = None
    trading_days_held: int = 0
    data_status: str = "ok"


class LookbackAuditResponse(BaseModel):
    audit_date: str
    lookforward_days: int
    selected_count: int
    audited_count: int
    ticker_results: list[TickerAuditResultResponse] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class LookbackAuditErrorResponse(BaseModel):
    error: str
    audit_date: str
    lookforward_days: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/lookback-audit", response_model=LookbackAuditResponse | LookbackAuditErrorResponse)
@safe_route
async def get_lookback_audit(
    date: str = Query(..., description="Audit date in YYYYMMDD or YYYY-MM-DD format"),
    days: int = Query(30, description="Lookforward window in calendar days", ge=1, le=365),
    top_n: int = Query(10, description="Number of top tickers to audit", ge=1, le=50),
    artifact_root: str | None = Query(None, description="Override artifact root directory"),
) -> LookbackAuditResponse | LookbackAuditErrorResponse:
    """Run a lookback audit: compare historical selection results against actual performance.

    Given a selection date, reads the selection_snapshot.json artifact,
    extracts the top-N selected tickers, fetches forward price data,
    and computes per-ticker return metrics.

    c362/autodev-4: previously this handler caught ``Exception`` and returned
    a ``LookbackAuditErrorResponse`` body with HTTP 200 — masking systemic
    failures (artifact schema drift, filesystem permission loss) from any
    status-code-based monitoring. Now uses ``@safe_route`` (sibling pattern):
    unhandled exceptions → 500 + ``logger.exception`` for traceability, and
    the known "no snapshot" case still raises a typed 404 below.
    """
    root = Path(artifact_root) if artifact_root else None

    result: LookbackAuditResult = run_lookback_audit(
        audit_date=date,
        lookforward_days=days,
        top_n=top_n,
        artifact_root=root,
    )

    if result.summary.get("error"):
        raise HTTPException(status_code=404, detail=result.summary["error"])

    return LookbackAuditResponse(
        audit_date=result.audit_date,
        lookforward_days=result.lookforward_days,
        selected_count=result.selected_count,
        audited_count=result.audited_count,
        ticker_results=[TickerAuditResultResponse(**asdict(tr)) for tr in result.ticker_results],
        summary=result.summary,
    )
