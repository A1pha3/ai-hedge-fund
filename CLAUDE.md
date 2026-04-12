# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-powered hedge fund simulator (educational/research only) using LangChain/LangGraph multi-agent architecture. 20 agents — 12 investor personas (Warren Buffett, Charlie Munger, Ben Graham, etc.), 6 technical analysts, 1 risk manager, 1 portfolio manager — analyze stocks and generate aggregated trading signals. Supports both US equities and Chinese A-share markets (via akshare/tushare). Two interfaces: CLI and full-stack web app (FastAPI + React/ReactFlow).

## Commands

```bash
# Install dependencies
poetry install          # or: uv sync

# Run hedge fund (CLI)
uv run python src/main.py --ticker AAPL,MSFT,NVDA
uv run python src/main.py --ticker 000001,000880       # A-share tickers
uv run python src/main.py --ticker AAPL --ollama       # Local LLM
uv run python src/main.py --show-default-model

# Run backtester
uv run backtester --ticker 000001

# Run web app (frontend :5173 + backend :8000)
./app/run.sh

# Run paper trading
source .env && .venv/bin/python scripts/run_paper_trading.py \
  --start-date 2026-02-02 --end-date 2026-03-13 --tickers 300724

# Tests
uv run pytest tests/ -v                    # All tests
uv run pytest tests/backtesting/ -v        # Backtesting unit tests
uv run pytest tests/path/to/test.py -v     # Single test file

# Formatting & linting
uv run black src/ && uv run isort src/ && uv run flake8 src/

# Utility scripts
.venv/bin/python scripts/list-models.py
.venv/bin/python scripts/summarize_llm_metrics.py logs/<metrics_file>.jsonl
.venv/bin/python scripts/manage_data_cache.py stats
```

## Architecture

### Workflow (LangGraph StateGraph)

1. Analyst agents run in configurable parallel waves per provider lane
2. Each agent emits: `{"signal": "bullish"|"bearish"|"neutral", "confidence": 0-100, "reasoning": "..."}`
3. Risk Manager aggregates signals and sets position limits
4. Portfolio Manager makes final trading decisions and generates orders
5. Results logged to `logs/` as structured JSONL metrics

### Key Directories

| Directory | Purpose |
|---|---|
| `src/agents/` | 20 agent implementations (12 investor + 6 analyst + 2 manager) |
| `src/graph/` | LangGraph state definitions (`AgentState`) |
| `src/data/` | Data providers (akshare, tushare), adapters, validation, enhanced SQLite cache |
| `src/tools/` | Financial data API wrappers |
| `src/llm/` | Multi-provider LLM config (16 providers supported) |
| `src/utils/` | Analyst registry, LLM wrapper, progress tracking |
| `src/cli/` | Shared CLI argument parsing |
| `app/backend/` | FastAPI app (Routes → Services → Repos → SQLAlchemy), SSE streaming |
| `app/frontend/` | React + ReactFlow + shadcn/ui + Tailwind |

### Extension Points

| Task | Where | Notes |
|------|-------|-------|
| Add new agent | `src/agents/` + `src/utils/analysts.py` | Create file, register in `ANALYST_CONFIG` |
| Add data source | `src/tools/` or `src/data/providers/` | API wrappers |
| Add API endpoint | `app/backend/routes/` | Register in `routes/__init__.py` |
| Add UI node | `app/frontend/src/nodes/` | Register in `nodes/index.ts` |

## Conventions

- **Line length 420** — both `black` and `flake8` use 420 chars; this is intentional, do not change
- **Dual lock files** — `poetry.lock` + `uv.lock` coexist; both are valid
- **All LLM calls** go through `src/utils/llm.call_llm()` — never call provider SDKs directly
- **Progress tracking** — use `progress.update_status(agent_id, ticker, "Step")`
- **Type hints required** — PEP 484 throughout, Pydantic for validation
- **Python 3.11–3.12** recommended; 3.13+ may have compatibility issues
- **A-share tickers** use 6-digit format (e.g., 000001, 300118)
- **Free US data** limited to AAPL, GOOGL, MSFT, NVDA, TSLA; others need `FINANCIAL_DATASETS_API_KEY`
- **No CI/CD** — manual/local execution only
- **No auth** — all backend endpoints are public

## Anti-Patterns

- Do NOT clear config state when loading flows — `useNodeState` handles isolation
- Do NOT reset runtime data when loading flows — preserve all state
- Do NOT hardcode API keys — use `.env` / environment variables
- Do NOT rely on single agent signals — portfolio manager must aggregate all

## Environment Variables

Requires `.env` file (see `.env.example`). Key variables:
- At least one LLM provider key: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `GROQ_API_KEY`, `GOOGLE_API_KEY`, etc.
- `LLM_DEFAULT_MODEL_PROVIDER` + `LLM_DEFAULT_MODEL_NAME` — explicit default model routing
- `ANALYST_CONCURRENCY_LIMIT` — parallel analyst execution (1=serial, 2-3=recommended)
- `MINIMAX_PROVIDER_CONCURRENCY_LIMIT` / `ZHIPU_PROVIDER_CONCURRENCY_LIMIT` — dual-provider tuning
- `LLM_PRIMARY_PROVIDER` — bias which provider leads in dual-provider mode
- `DISK_CACHE_PATH` — override default cache location (`~/.cache/ai-hedge-fund/cache.sqlite`)
