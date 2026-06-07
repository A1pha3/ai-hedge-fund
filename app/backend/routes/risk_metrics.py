"""组合风险指标 API — 为前端 risk-monitor-panel 提供数据。

GET /api/portfolio/risk-snapshot?lookback_days=60

返回当前持仓的实时风险快照 (VaR / CVaR / 回撤 / 集中度)。

数据来源:
- ``portfolio_positions``: 调用方通过 query/body 传入 (本端点为纯计算服务,
  不直接绑定 paper_trading 运行时, 便于前端/回测/审计多种场景共用)
- ``lookback_returns``: 调用方传入, 默认为空 (空时 VaR/CVaR = 0, 回撤 = 0)

生产环境建议: 由上游 ``paper_trading`` 运行时调用此端点, 或前端直接 fetch
本端点并附带当日持仓 + 回溯收益快照。这样保持本模块无状态, 单测可纯
mock 验证。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from src.portfolio.risk_metrics import (
    DRAWDOWN_WARNING_THRESHOLD,
    INDUSTRY_CONCENTRATION_WARNING_THRESHOLD,
    SINGLE_POSITION_WARNING_THRESHOLD,
    RiskSnapshot,
    compute_risk_snapshot,
)

router = APIRouter(prefix="/portfolio")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class PositionInput(BaseModel):
    """单只标的的当前持仓快照。"""

    ticker: str
    shares: float = 0.0
    current_price: float = 0.0
    market_value: float | None = None
    industry_sw: str | None = None
    beta: float | None = None


class LookbackReturnInput(BaseModel):
    """回溯收益中的单条记录。"""

    date: str
    ticker: str
    return_pct: float
    portfolio_return: float | None = None


class RiskSnapshotRequest(BaseModel):
    """POST 请求体 (含完整快照输入)。"""

    positions: list[PositionInput] = Field(default_factory=list)
    lookback_returns: list[LookbackReturnInput] = Field(default_factory=list)
    benchmark_returns: list[float] | None = None
    initial_portfolio_value: float | None = None
    var_horizon_days: int = Field(default=1, ge=1, le=20)
    confidence_levels: tuple[float, ...] = (0.95, 0.99)
    timestamp: str = ""


class RiskSnapshotResponse(BaseModel):
    """单点风险快照响应 — 与 src/portfolio/risk_metrics.RiskSnapshot 同构。"""

    timestamp: str
    portfolio_value: float
    var_95: float
    var_99: float
    cvar_95: float
    cvar_99: float
    max_drawdown: float
    current_drawdown: float
    drawdown_warning: bool
    industry_concentration: dict[str, float]
    concentration_warning: bool
    single_position_max: float
    position_count: int
    beta_adjusted: float

    @classmethod
    def from_snapshot(cls, snapshot: RiskSnapshot) -> "RiskSnapshotResponse":
        return cls(**snapshot.to_dict())


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    path="/risk-snapshot",
    response_model=RiskSnapshotResponse,
    summary="Portfolio risk snapshot (VaR / CVaR / drawdown / concentration)",
    description=(
        "Returns a real-time risk snapshot for the supplied positions. "
        "When called without a body the snapshot contains zero-risk values "
        "(no positions, no lookback) — useful for the dashboard to render "
        "an empty state. The heavy lifting is in the POST variant which "
        "accepts a full payload."
    ),
)
def get_risk_snapshot(
    lookback_days: int = Query(60, ge=1, le=252, description="回溯窗口长度 (1-252 个交易日)"),
) -> RiskSnapshotResponse:
    """无持仓 / 无收益的空快照, 用于前端初始加载。"""
    snapshot = compute_risk_snapshot(
        portfolio_positions=[],
        lookback_returns=[],
        timestamp="",
        confidence_levels=(0.95, 0.99),
    )
    return RiskSnapshotResponse.from_snapshot(snapshot)


@router.post(
    path="/risk-snapshot",
    response_model=RiskSnapshotResponse,
    summary="Portfolio risk snapshot (POST with full payload)",
)
def post_risk_snapshot(req: RiskSnapshotRequest) -> RiskSnapshotResponse:
    """接收完整持仓 + 回溯收益, 计算 RiskSnapshot。"""
    positions = [position.model_dump() for position in req.positions]
    lookback = [row.model_dump() for row in req.lookback_returns]
    snapshot = compute_risk_snapshot(
        portfolio_positions=positions,
        lookback_returns=lookback,
        timestamp=req.timestamp,
        initial_portfolio_value=req.initial_portfolio_value or 0.0,
        var_horizon_days=req.var_horizon_days,
        confidence_levels=tuple(req.confidence_levels) or (0.95, 0.99),
        benchmark_returns=req.benchmark_returns,
    )
    return RiskSnapshotResponse.from_snapshot(snapshot)


# ---------------------------------------------------------------------------
# Diagnostic helpers (kept simple, no I/O)
# ---------------------------------------------------------------------------


def _thresholds_dict() -> dict[str, float]:
    return {
        "industry_concentration": INDUSTRY_CONCENTRATION_WARNING_THRESHOLD,
        "single_position": SINGLE_POSITION_WARNING_THRESHOLD,
        "drawdown": DRAWDOWN_WARNING_THRESHOLD,
    }


@router.get(
    path="/risk-snapshot/thresholds",
    summary="Current risk warning thresholds (diagnostic)",
)
def get_risk_thresholds() -> dict[str, Any]:
    """返回当前生效的预警阈值, 便于前端对齐展示口径。"""
    return {"thresholds": _thresholds_dict()}
