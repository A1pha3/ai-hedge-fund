from fastapi import APIRouter, Depends

from app.backend.routes.attribution import router as attribution_router
from app.backend.routes.backtest_visualization import router as backtest_visualization_router
from app.backend.routes.data_sources import router as data_sources_router
from app.backend.routes.hedge_fund import router as hedge_fund_router
from app.backend.routes.health import router as health_router
from app.backend.routes.storage import router as storage_router
from app.backend.routes.flows import router as flows_router
from app.backend.routes.flow_runs import router as flow_runs_router
from app.backend.routes.ollama import router as ollama_router
from app.backend.routes.language_models import router as language_models_router
from app.backend.routes.api_keys import router as api_keys_router
from app.backend.routes.auth import router as auth_router
from app.backend.routes.invites import router as invites_router
from app.backend.routes.replay_artifacts import router as replay_artifacts_router
from app.backend.routes.cache import router as cache_router
from app.backend.routes.llm_metrics import router as llm_metrics_router
from app.backend.routes.research import router as research_router
from app.backend.routes.portfolio_simulator import router as portfolio_simulator_router
from app.backend.routes.risk_metrics import router as risk_metrics_router
from app.backend.routes.admin_audit import router as admin_audit_router
from app.backend.routes.screening import router as screening_router
from app.backend.auth.dependencies import get_current_user

# Main API router
api_router = APIRouter()

# Public routes (no authentication required)
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(health_router, tags=["health"])
api_router.include_router(cache_router, tags=["cache"])
api_router.include_router(llm_metrics_router, tags=["llm-metrics"])
api_router.include_router(data_sources_router, tags=["data-sources"])
# Invite management: redeem is public, CRUD requires admin (handled per-endpoint)
api_router.include_router(invites_router, tags=["invites"])
# Portfolio attribution (public analytics endpoint)
api_router.include_router(attribution_router, tags=["portfolio"])
# P2 2.3: Portfolio adjustment simulator (public analytics endpoint)
api_router.include_router(portfolio_simulator_router, tags=["portfolio"])
# P1-6: Portfolio risk snapshot (VaR / CVaR / drawdown / concentration)
api_router.include_router(risk_metrics_router, tags=["portfolio"])
# P0-4: Backtest visualization data (equity curve, drawdown, monthly returns)
api_router.include_router(backtest_visualization_router, tags=["backtest"])
# P1-5: Web 端一键选股 (public analytics endpoint, may take up to 60s)
api_router.include_router(screening_router, tags=["screening"])

# Protected routes (require valid JWT token)
_auth = [Depends(get_current_user)]
api_router.include_router(hedge_fund_router, tags=["hedge-fund"], dependencies=_auth)
api_router.include_router(storage_router, tags=["storage"], dependencies=_auth)
api_router.include_router(flows_router, tags=["flows"], dependencies=_auth)
api_router.include_router(flow_runs_router, tags=["flow-runs"], dependencies=_auth)
api_router.include_router(ollama_router, tags=["ollama"], dependencies=_auth)
api_router.include_router(language_models_router, tags=["language-models"], dependencies=_auth)
api_router.include_router(api_keys_router, tags=["api-keys"], dependencies=_auth)
api_router.include_router(replay_artifacts_router, tags=["replay-artifacts"], dependencies=_auth)
api_router.include_router(research_router, tags=["research"], dependencies=_auth)
# P2 2.5: admin audit + session revoke — endpoints individually enforce require_admin
api_router.include_router(admin_audit_router, tags=["admin"])
