# PROJECT KNOWLEDGE BASE

**Generated:** 2026-02-25
**Commit:** aa60590
**Branch:** main

## OVERVIEW

AI-powered hedge fund simulator using LangChain/LangGraph multi-agent system. 18 investor/analyst agents analyze stocks and generate trading signals, aggregated by risk manager + portfolio manager. CLI + Web (FastAPI + React/ReactFlow) interfaces. Python 3.11+ / TypeScript.

## STRUCTURE

```
ai-hedge-fund-fork/
├── src/                    # Core library (CLI-first)
│   ├── agents/            # 21 agent files (12 investor + 6 analyst + 2 manager)
│   ├── backtesting/       # Modular backtester subsystem
│   ├── graph/             # LangGraph state definition (AgentState)
│   ├── data/              # Data providers (akshare, tushare, financial datasets API)
│   ├── tools/             # Financial data API wrappers
│   ├── llm/               # Multi-provider LLM config (10 providers)
│   ├── utils/             # Analyst registry, LLM wrapper, progress tracking
│   ├── cli/               # Shared CLI argument parsing
│   ├── main.py            # CLI entry: hedge fund execution
│   └── backtester.py      # Legacy backtester entry
├── app/
│   ├── backend/           # FastAPI (Routes→Services→Repos→SQLAlchemy)
│   └── frontend/          # React + ReactFlow + shadcn/ui
├── docker/                # Dockerfile + docker-compose (6 services)
├── tests/                 # pytest (backtesting unit + integration)
└── docs/zh-cn/            # Chinese documentation
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add new agent | `src/agents/` + `src/utils/analysts.py` | Create agent file, register in ANALYST_CONFIG |
| Modify workflow | `src/main.py` | LangGraph StateGraph construction |
| Add data source | `src/tools/` or `src/data/providers/` | API wrappers for financial data |
| Add API endpoint | `app/backend/routes/` | Register in `routes/__init__.py` |
| Add UI node type | `app/frontend/src/nodes/` | Register in `nodes/index.ts` |
| Add UI component | `app/frontend/src/components/` | Uses shadcn/ui + Tailwind |
| Run hedge fund | `poetry run python src/main.py --ticker AAPL,MSFT` | or `uv run python src/main.py` |
| Run backtester | `poetry run backtester --ticker AAPL` | New modular CLI |
| Run web app | `./app/run.sh` | Starts frontend:5173 + backend:8000 |
| Run tests | `poetry run pytest tests/` | |
| Docker | `./docker/run.sh --ticker AAPL main` | |

## CONVENTIONS

- **Line length 420** — `black` and `flake8` both set to 420 chars (intentional, not a typo)
- **Dual lock files** — `poetry.lock` + `uv.lock` coexist; both work
- **No CI/CD** — No GitHub Actions workflows; manual/local execution only
- **No auth** — Backend has zero authentication; all endpoints public
- **Type hints required** — PEP 484, pydantic for validation
- **Agent output format** — All agents return `{"signal": "bullish"|"bearish"|"neutral", "confidence": 0-100, "reasoning": "..."}`
- **Progress tracking** — All agents call `progress.update_status(agent_id, ticker, "Step")`
- **LLM calls** — Always via `src/utils/llm.call_llm()`, never direct provider calls

## ANTI-PATTERNS (THIS PROJECT)

- **DO NOT** clear configuration state when loading flows — `useNodeState` handles flow isolation
- **DO NOT** reset runtime data when loading flows — preserve all runtime state
- **DO NOT** use `allow_origins=["*"]` in production CORS
- **DO NOT** hardcode API keys — always `.env` / environment variables
- **DO NOT** use this for real trading — educational/research only
- **DO NOT** rely on single agent signals — portfolio manager aggregates all

## COMMANDS

```bash
# Development
poetry install                                          # Install deps
poetry run python src/main.py --ticker AAPL,MSFT,NVDA  # Run hedge fund
poetry run python src/main.py --ticker AAPL --ollama    # Local LLM
poetry run backtester --ticker AAPL                     # Backtest
./app/run.sh                                            # Web app (full stack)

# Testing
poetry run pytest tests/                                # All tests
poetry run pytest tests/backtesting/                    # Unit tests
poetry run pytest tests/backtesting/integration/        # Integration tests

# Formatting
poetry run black .                                      # Format (420 line length)
poetry run flake8 .                                     # Lint
poetry run isort .                                      # Sort imports
```

## NOTES

- Python 3.13+ may have compatibility issues; 3.11 recommended
- Free data for AAPL, GOOGL, MSFT, NVDA, TSLA only; others need `FINANCIAL_DATASETS_API_KEY`
- Frontend uses global singleton managers (not Redux/Zustand) for flow state isolation
- Backend streams execution results via SSE (Server-Sent Events)
- A-share market support via akshare + tushare providers
