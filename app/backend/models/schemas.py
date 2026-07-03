import os
import re
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.backend.services.graph import extract_base_agent_key
from src.llm.defaults import get_default_model_config
from src.llm.models import ModelProvider

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Default cap on tickers per web money-acting request (hedge-fund run / backtest /
# rerun). Prevents resource exhaustion and cost-DoS on the pre-production web app:
# N tickers × 20 agents + per-ticker data fetches can saturate the provider lanes
# and run up LLM cost for a single request. CLI/cron bypass HedgeFundRequest (they
# build the graph directly), so this only guards the web front door. 25 is well
# above the 2-5 tickers typical of interactive use (see CLAUDE.md examples); owners
# who batch more can raise it via HEDGE_FUND_MAX_TICKERS.
_DEFAULT_MAX_TICKERS = 25


def _max_tickers() -> int:
    """Resolve the ticker cap at validation time (not import time) so an env change
    takes effect on the next request without restarting the server. Non-positive or
    unparseable values fall back to the default rather than rejecting everything."""
    raw = os.environ.get("HEDGE_FUND_MAX_TICKERS")
    if not raw:
        return _DEFAULT_MAX_TICKERS
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_TICKERS
    return n if n > 0 else _DEFAULT_MAX_TICKERS


class FlowRunStatus(str, Enum):
    IDLE = "IDLE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"


class AgentModelConfig(BaseModel):
    agent_id: str
    model_name: Optional[str] = None
    model_provider: Optional[ModelProvider] = None


class PortfolioPosition(BaseModel):
    ticker: str
    quantity: float
    trade_price: float

    @field_validator("trade_price")
    @classmethod
    def price_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Trade price must be positive!")
        return v


class GraphNode(BaseModel):
    id: str
    type: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    position: Optional[Dict[str, Any]] = None


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class HedgeFundResponse(BaseModel):
    decisions: dict
    analyst_signals: dict


class ErrorResponse(BaseModel):
    message: str
    error: str | None = None


# Base class for shared fields between HedgeFundRequest and BacktestRequest
class BaseHedgeFundRequest(BaseModel):
    tickers: List[str]
    graph_nodes: List[GraphNode]
    graph_edges: List[GraphEdge]
    agent_models: Optional[List[AgentModelConfig]] = None
    model_name: Optional[str] = Field(default_factory=lambda: get_default_model_config()[0])
    model_provider: Optional[ModelProvider] = Field(default_factory=lambda: ModelProvider(get_default_model_config()[1]))
    margin_requirement: float = 0.0
    portfolio_positions: Optional[List[PortfolioPosition]] = None
    api_keys: Optional[Dict[str, str]] = None

    @field_validator("tickers")
    @classmethod
    def bound_ticker_count(cls, v: List[str]) -> List[str]:
        limit = _max_tickers()
        if len(v) > limit:
            raise ValueError(f"Too many tickers: {len(v)} (limit {limit}). " f"Raise HEDGE_FUND_MAX_TICKERS to allow more.")
        return v

    def get_agent_ids(self) -> List[str]:
        """Extract agent IDs from graph structure"""
        return [node.id for node in self.graph_nodes]

    def get_agent_model_config(self, agent_id: str) -> tuple[str, ModelProvider]:
        """Get model configuration for a specific agent"""
        if self.agent_models:
            # Extract base agent key from unique node ID for matching
            base_agent_key = extract_base_agent_key(agent_id)

            for config in self.agent_models:
                # Check both unique node ID and base agent key for matches
                config_base_key = extract_base_agent_key(config.agent_id)
                if config.agent_id == agent_id or config_base_key == base_agent_key:
                    return (config.model_name or self.model_name, config.model_provider or self.model_provider)
        # Fallback to global model settings
        return self.model_name, self.model_provider


class BacktestRequest(BaseHedgeFundRequest):
    start_date: str
    end_date: str
    initial_capital: float = Field(default=100000.0, gt=0)

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        if not _DATE_PATTERN.match(v):
            raise ValueError(f"Date must be in YYYY-MM-DD format, got: {v}")
        return v


class BacktestDayResult(BaseModel):
    date: str
    portfolio_value: float
    cash: float
    decisions: Dict[str, Any]
    executed_trades: Dict[str, int]
    analyst_signals: Dict[str, Any]
    current_prices: Dict[str, float]
    long_exposure: float
    short_exposure: float
    gross_exposure: float
    net_exposure: float
    long_short_ratio: Optional[float] = None


class BacktestPerformanceMetrics(BaseModel):
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    max_drawdown_date: Optional[str] = None
    long_short_ratio: Optional[float] = None
    gross_exposure: Optional[float] = None
    net_exposure: Optional[float] = None


class BacktestResponse(BaseModel):
    results: List[BacktestDayResult]
    performance_metrics: BacktestPerformanceMetrics
    final_portfolio: Dict[str, Any]


class HedgeFundRequest(BaseHedgeFundRequest):
    end_date: Optional[str] = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    start_date: Optional[str] = None
    initial_cash: float = Field(default=100000.0, gt=0)

    @field_validator("end_date")
    @classmethod
    def validate_end_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _DATE_PATTERN.match(v):
            raise ValueError(f"end_date must be in YYYY-MM-DD format, got: {v}")
        return v

    @field_validator("start_date")
    @classmethod
    def validate_start_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _DATE_PATTERN.match(v):
            raise ValueError(f"start_date must be in YYYY-MM-DD format, got: {v}")
        return v

    def get_start_date(self) -> str:
        """Calculate start date if not provided"""
        if self.start_date:
            return self.start_date
        effective_end = self.end_date or datetime.now().strftime("%Y-%m-%d")
        return (datetime.strptime(effective_end, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")


# Flow-related schemas
class FlowCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    viewport: Optional[Dict[str, Any]] = None
    data: Optional[Dict[str, Any]] = None
    is_template: bool = False
    tags: Optional[List[str]] = None


class FlowUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None
    viewport: Optional[Dict[str, Any]] = None
    data: Optional[Dict[str, Any]] = None
    is_template: Optional[bool] = None
    tags: Optional[List[str]] = None


class FlowResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    viewport: Optional[Dict[str, Any]]
    data: Optional[Dict[str, Any]]
    is_template: bool
    tags: Optional[List[str]]
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class FlowSummaryResponse(BaseModel):
    """Lightweight flow response without nodes/edges for listing"""

    id: int
    name: str
    description: Optional[str]
    is_template: bool
    tags: Optional[List[str]]
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class FlowRunCreateRequest(BaseModel):
    """Request to create a new flow run"""

    request_data: Optional[Dict[str, Any]] = None


class FlowRunUpdateRequest(BaseModel):
    """Request to update an existing flow run"""

    status: Optional[FlowRunStatus] = None
    results: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class FlowRunResponse(BaseModel):
    """Complete flow run response"""

    id: int
    flow_id: int
    status: FlowRunStatus
    run_number: int
    created_at: datetime
    updated_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    request_data: Optional[Dict[str, Any]]
    results: Optional[Dict[str, Any]]
    error_message: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class FlowRunSummaryResponse(BaseModel):
    """Lightweight flow run response for listing"""

    id: int
    flow_id: int
    status: FlowRunStatus
    run_number: int
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]

    model_config = ConfigDict(from_attributes=True)


# API Key schemas
class ApiKeyCreateRequest(BaseModel):
    """Request to create or update an API key"""

    provider: str = Field(..., min_length=1, max_length=100)
    key_value: str = Field(..., min_length=1)
    description: Optional[str] = None
    is_active: bool = True


class ApiKeyUpdateRequest(BaseModel):
    """Request to update an existing API key"""

    key_value: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ApiKeyResponse(BaseModel):
    """Complete API key response"""

    id: int
    provider: str
    masked_key_value: Optional[str] = None
    is_active: bool
    description: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    last_used: Optional[datetime]
    has_key: bool = True

    model_config = ConfigDict(from_attributes=True)


class ApiKeySummaryResponse(BaseModel):
    """API key response without the actual key value"""

    id: int
    provider: str
    is_active: bool
    description: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    last_used: Optional[datetime]
    masked_key_value: Optional[str] = None
    has_key: bool = True  # Indicates if a key is set

    model_config = ConfigDict(from_attributes=True)


class ApiKeyBulkUpdateRequest(BaseModel):
    """Request to update multiple API keys at once"""

    api_keys: List[ApiKeyCreateRequest]
