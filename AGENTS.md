# PROJECT KNOWLEDGE BASE

**Generated:** 2026-02-27
**Commit:** 036fac2
**Branch:** main

## OVERVIEW

AI-powered hedge fund simulator using LangChain/LangGraph multi-agent system. 18 analyst agents (12 investor personas + 6 technical analysts) generate trading signals, aggregated by risk manager + portfolio manager. CLI + Web (FastAPI + React/ReactFlow) interfaces. Python 3.11+ / TypeScript. A-share market support via akshare + tushare.

## STRUCTURE

```
ai-hedge-fund-fork/
├── src/                    # Core library (CLI-first)
│   ├── agents/            # 20 agents (12 investor + 6 analyst + 2 manager)
│   ├── backtesting/       # Modular backtester (cli, engine, metrics)
│   ├── graph/             # LangGraph state (AgentState)
│   ├── data/              # Providers (akshare, tushare) + adapters + validation
│   ├── tools/             # Financial data API wrappers
│   ├── llm/               # Multi-provider LLM config (16 providers)
│   ├── utils/             # Analyst registry, LLM wrapper, progress
│   ├── cli/               # Shared CLI argument parsing
│   ├── main.py            # CLI entry: hedge fund execution
│   └── backtester.py      # Legacy backtester entry
├── app/
│   ├── backend/           # FastAPI (Routes→Services→Repos→SQLAlchemy)
│   └── frontend/          # React + ReactFlow + shadcn/ui
├── data/
│   ├── reports/           # Generated analysis reports
│   └── snapshots/         # Data snapshots
├── scripts/               # Utility scripts (batch-run, list-models)
├── docker/                # Dockerfile + docker-compose
├── tests/                 # pytest (backtesting unit + integration)
└── docs/zh-cn/            # Chinese documentation
```

## AGENTS

**Investor Personas (12):**
Aswath Damodaran, Ben Graham, Bill Ackman, Cathie Wood, Charlie Munger, Michael Burry, Mohnish Pabrai, Peter Lynch, Phil Fisher, Rakesh Jhunjhunwala, Stanley Druckenmiller, Warren Buffett

**Technical Analysts (6):**
Technical Analyst, Fundamentals Analyst, Growth Analyst, News Sentiment Analyst, Sentiment Analyst, Valuation Analyst

**Managers (2):**
Risk Manager, Portfolio Manager

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add new agent | `src/agents/` + `src/utils/analysts.py` | Create file, register in ANALYST_CONFIG |
| Modify workflow | `src/main.py` | LangGraph StateGraph |
| Add data source | `src/tools/` or `src/data/providers/` | API wrappers |
| Add API endpoint | `app/backend/routes/` | Register in `routes/__init__.py` |
| Add UI node | `app/frontend/src/nodes/` | Register in `nodes/index.ts` |
| Add UI component | `app/frontend/src/components/` | shadcn/ui + Tailwind |
| Run hedge fund | `uv run python src/main.py --ticker 000001` | A-share tickers supported |
| Run backtester | `uv run backtester --ticker 000001` | Modular CLI |
| Run web app | `./app/run.sh` | Frontend:5173 + Backend:8000 |
| Run tests | `uv run pytest tests/ -v` | |

## CONVENTIONS

- **Line length 420** — `black` / `flake8` both 420 chars
- **Dual lock files** — `poetry.lock` + `uv.lock` coexist
- **No CI/CD** — Manual/local execution only
- **No auth** — All backend endpoints public
- **Type hints required** — PEP 484, pydantic validation
- **Agent output** — `{"signal": "bullish"|"bearish"|"neutral", "confidence": 0-100, "reasoning": "..."}`
- **Progress tracking** — `progress.update_status(agent_id, ticker, "Step")`
- **LLM calls** — Via `src/utils/llm.call_llm()`, never direct

## ANTI-PATTERNS

- **DO NOT** clear config state when loading flows — `useNodeState` handles isolation
- **DO NOT** reset runtime data when loading flows — preserve all state
- **DO NOT** use `allow_origins=["*"]` in production CORS
- **DO NOT** hardcode API keys — use `.env` / environment variables
- **DO NOT** use for real trading — educational/research only
- **DO NOT** rely on single agent signals — portfolio manager aggregates all

## COMMANDS

```bash
# Development
uv run python src/main.py --ticker 000001,000880    # Run hedge fund
uv run python src/main.py --ticker 000001 --ollama  # Local LLM
uv run backtester --ticker 000001                    # Backtest
./app/run.sh                                         # Web app

# Testing
uv run pytest tests/ -v                              # All tests
uv run pytest tests/backtesting/ -v                  # Unit tests

# Formatting
uv run black src/ && uv run isort src/ && uv run flake8 src/
```

## NOTES

- Python 3.13+ may have issues; 3.11-3.12 recommended
- A-share market: use 6-digit tickers (e.g., 000001, 300118)
- Free US data: AAPL, GOOGL, MSFT, NVDA, TSLA only; others need `FINANCIAL_DATASETS_API_KEY`
- Frontend uses global singleton managers for flow state isolation
- Backend streams execution results via SSE
