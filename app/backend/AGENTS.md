# app/backend/

## OVERVIEW

FastAPI backend — converts React Flow graphs into LangGraph workflows, streams execution results via SSE. Layered architecture: Routes → Services → Repositories → SQLAlchemy (SQLite).

## STRUCTURE

```
backend/
├── main.py              # FastAPI app, CORS, startup events
├── routes/              # 8 sub-routers (registered in __init__.py)
│   ├── hedge_fund.py    # /hedge-fund/run (SSE), /backtest, /agents
│   ├── flows.py         # /flows CRUD
│   ├── flow_runs.py     # /flow-runs execution history
│   ├── api_keys.py      # /api-keys management
│   ├── ollama.py        # /ollama/* local LLM integration
│   ├── language_models.py # /language-models provider listing
│   ├── storage.py       # /storage generic persistence
│   └── health.py        # /health
├── services/            # Business logic
│   ├── graph.py         # React Flow → LangGraph StateGraph conversion
│   ├── backtest_service.py
│   ├── api_key_service.py
│   └── ollama_service.py
├── repositories/        # Data access (SQLAlchemy Session)
│   ├── flow_repository.py
│   ├── flow_run_repository.py
│   └── api_key_repository.py
├── database/
│   ├── connection.py    # Engine, SessionLocal, Base (SQLite)
│   └── models.py        # ORM: HedgeFundFlow, FlowRun, FlowRunCycle, ApiKey
├── models/
│   ├── schemas.py       # Pydantic request/response + field validators
│   └── events.py        # SSE event types (Start, Progress, Complete, Error)
└── alembic/             # Database migrations
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add API endpoint | `routes/` + `routes/__init__.py` | Create router, register in aggregator |
| Add business logic | `services/` | Accept db Session, use repositories |
| Add database model | `database/models.py` + alembic migration | ORM model + `alembic revision --autogenerate` |
| Add Pydantic schema | `models/schemas.py` | Request/Response separation pattern |
| SSE streaming | `models/events.py` | `BaseEvent.to_sse()` method |
| Modify workflow build | `services/graph.py` | React Flow nodes/edges → LangGraph |

## CONVENTIONS

- **No authentication** — all endpoints public, CORS allows localhost:5173
- **SSE for execution** — hedge fund run + backtest stream events, not request-response
- **Repository pattern** — `__init__(self, db: Session)`, CRUD methods return ORM models
- **Error handling** — `HTTPException` with status codes; generic catch-all wraps to 500
- **src/ integration** — imports directly from `src.agents`, `src.utils`, `src.tools`
- **Pydantic v2** — uses `model_config = ConfigDict(from_attributes=True)`, `field_validator`

## ANTI-PATTERNS

- **DO NOT** use `allow_origins=["*"]` — currently scoped to localhost:5173
- **DO NOT** add auth middleware without updating all frontend API calls
