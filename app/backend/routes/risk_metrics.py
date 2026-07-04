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

from src.portfolio.rebalance_advisor import (
    compute_rebalance_actions,
    DEFAULT_DRIFT_THRESHOLD,
    DEFAULT_MIN_TRADE_AMOUNT,
    INDUSTRY_HARD_LIMIT,
    SINGLE_NAME_HARD_LIMIT,
    STRONG_DRIFT_THRESHOLD,
)
from src.portfolio.risk_metrics import (
    compute_risk_snapshot,
    DRAWDOWN_WARNING_THRESHOLD,
    INDUSTRY_CONCENTRATION_WARNING_THRESHOLD,
    RiskSnapshot,
    SINGLE_POSITION_WARNING_THRESHOLD,
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
    description=("Returns a real-time risk snapshot for the supplied positions. " "When called without a body the snapshot contains zero-risk values " "(no positions, no lookback) — useful for the dashboard to render " "an empty state. The heavy lifting is in the POST variant which " "accepts a full payload."),
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


# ---------------------------------------------------------------------------
# P1-12: 组合再平衡建议 (Rebalance Advisor)
# ---------------------------------------------------------------------------


class RebalancePositionInput(BaseModel):
    """单条持仓(供再平衡使用)。"""

    ticker: str
    name: str = ""
    sector: str = "UNKNOWN"
    current_value: float = Field(default=0.0, ge=0.0)
    target_weight: float = Field(default=0.0, ge=0.0, le=1.0)


class RebalanceRequest(BaseModel):
    """POST 请求体 (持仓 + 阈值)。"""

    portfolio_value: float = Field(..., gt=0.0, description="组合总价值 (元)")
    positions: list[RebalancePositionInput] = Field(default_factory=list)
    drift_threshold: float = Field(default=DEFAULT_DRIFT_THRESHOLD, ge=0.0, le=1.0)
    strong_drift_threshold: float = Field(default=STRONG_DRIFT_THRESHOLD, ge=0.0, le=1.0)
    min_trade_amount: float = Field(default=DEFAULT_MIN_TRADE_AMOUNT, ge=0.0)
    industry_hard_limit: float = Field(default=INDUSTRY_HARD_LIMIT, ge=0.0, le=1.0)
    single_name_hard_limit: float = Field(default=SINGLE_NAME_HARD_LIMIT, ge=0.0, le=1.0)


class RebalanceActionResponse(BaseModel):
    """单条再平衡操作 — 与 RebalanceAction.to_dict 同构。"""

    ticker: str
    name: str
    action: str
    sector: str
    current_weight: float
    target_weight: float
    delta_weight: float
    delta_amount: float
    reason: str
    priority: int


class RebalanceResponse(BaseModel):
    """再平衡建议响应。"""

    portfolio_value: float
    drift_threshold: float
    actions: list[RebalanceActionResponse]


@router.get(
    path="/rebalance",
    response_model=RebalanceResponse,
    summary="Portfolio rebalance advice (empty payload returns thresholds + empty actions)",
)
def get_rebalance_actions(
    drift_threshold: float = Query(DEFAULT_DRIFT_THRESHOLD, ge=0.0, le=1.0, description="漂移阈值"),
) -> RebalanceResponse:
    """GET 端点 — 无持仓时返回空 actions, 用于前端首次加载。"""
    return RebalanceResponse(
        portfolio_value=0.0,
        drift_threshold=float(drift_threshold),
        actions=[],
    )


@router.post(
    path="/rebalance",
    response_model=RebalanceResponse,
    summary="Portfolio rebalance advice (POST with positions)",
)
def post_rebalance_actions(req: RebalanceRequest) -> RebalanceResponse:
    """接收 ``positions`` + ``portfolio_value``, 返回 ``actions``。"""
    positions_payload = [p.model_dump() for p in req.positions]
    actions = compute_rebalance_actions(
        positions_payload,
        req.portfolio_value,
        drift_threshold=req.drift_threshold,
        strong_drift_threshold=req.strong_drift_threshold,
        min_trade_amount=req.min_trade_amount,
        industry_hard_limit=req.industry_hard_limit,
        single_name_hard_limit=req.single_name_hard_limit,
    )
    return RebalanceResponse(
        portfolio_value=req.portfolio_value,
        drift_threshold=req.drift_threshold,
        actions=[RebalanceActionResponse(**a.to_dict()) for a in actions],
    )


# ---------------------------------------------------------------------------
# P2-8: 组合绩效周报/月报 (Performance Report)
# ---------------------------------------------------------------------------

from src.portfolio.performance_report import (  # noqa: E402
    generate_performance_report,
)
from src.portfolio.performance_report import (  # noqa: E402
    PerformanceReport as PerformanceReportData,
)


class PerformanceReportResponse(BaseModel):
    """P2-8 绩效报告响应 — 与 PerformanceReport 同构。"""

    period: str
    start_date: str
    end_date: str
    total_return: float
    annualized_return: float
    benchmark_return: float
    excess_return: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    volatility: float
    total_trades: int
    win_count: int
    loss_count: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    strategy_attribution: dict[str, float] = {}
    top_winners: list[dict] = []
    top_losers: list[dict] = []
    total_recommendations: int = 0
    recommendation_hit_rate: float = 0.0

    @classmethod
    def from_report(cls, report: PerformanceReportData) -> "PerformanceReportResponse":
        return cls(**report.to_dict())


class PerformanceReportRequest(BaseModel):
    """POST 请求体 — 完整数据 payload。"""

    positions_history: list[dict] = []
    trades: list[dict] = []
    recommendations: list[dict] = []
    tracking_history: list[dict] = []
    period: str = "weekly"
    end_date: str | None = None
    benchmark_return: float = 0.0


@router.get(
    path="/performance-report",
    response_model=PerformanceReportResponse,
    summary="Portfolio performance report (empty payload)",
    description="Returns a zero-value performance report. Use the POST variant for full analysis.",
)
def get_performance_report(
    period: str = Query("weekly", pattern="^(weekly|monthly)$", description="报告周期: weekly / monthly"),
    end_date: str | None = Query(None, description="结束日期 YYYYMMDD"),
    benchmark_return: float = Query(0.0, description="基准收益率 (小数)"),
) -> PerformanceReportResponse:
    """GET 端点 — 无数据时返回零值报告。"""
    report = generate_performance_report(
        positions_history=[],
        trades=[],
        recommendations=[],
        tracking_history=[],
        period=period,
        end_date=end_date,
        benchmark_return=benchmark_return,
    )
    return PerformanceReportResponse.from_report(report)


@router.post(
    path="/performance-report",
    response_model=PerformanceReportResponse,
    summary="Portfolio performance report (POST with full payload)",
)
def post_performance_report(req: PerformanceReportRequest) -> PerformanceReportResponse:
    """接收完整数据, 生成绩效报告。"""
    report = generate_performance_report(
        positions_history=req.positions_history,
        trades=req.trades,
        recommendations=req.recommendations,
        tracking_history=req.tracking_history,
        period=req.period,
        end_date=req.end_date,
        benchmark_return=req.benchmark_return,
    )
    return PerformanceReportResponse.from_report(report)
