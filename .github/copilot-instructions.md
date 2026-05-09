# Copilot Instructions

## Build, test, and lint

```bash
# Install dependencies
uv sync --group dev
# or
poetry install

# Run the main CLI workflow
uv run python src/main.py --ticker AAPL,MSFT,NVDA
uv run python src/main.py --ticker 000001,000880
uv run python src/main.py --show-default-model

# Run the backtester
uv run backtester --ticker 000001

# Run the web app (frontend on :5173, backend on :8000)
./app/run.sh

# Python tests
uv run pytest tests/ -v
uv run pytest tests/path/to/test.py -v
uv run pytest tests/path/to/test.py::test_name -v

# Python formatting and linting
uv run black src/ && uv run isort src/ && uv run flake8 src/

# Frontend build, test, and lint
cd app/frontend && npm ci
cd app/frontend && npm run build
cd app/frontend && npm run test
cd app/frontend && npm run test -- src/test/path/to/test-file.test.tsx
cd app/frontend && npm run lint
```

## High-level architecture

- The core hedge-fund CLI is assembled in `src/main.py` as a LangGraph `StateGraph`. Analyst nodes come from the central registry in `src/utils/analysts.py`, run in ordered batches based on the configured concurrency, then hand off to `risk_management_agent` and `portfolio_management_agent`. Shared graph state lives in `src/graph/state.py`.
- LLM access is centralized in `src/utils/llm.py`. That module owns provider routing, per-provider concurrency, fallback behavior, timeouts, and metrics logging. If you add or change agent/model behavior, wire it through this shared path instead of calling provider SDKs directly.
- The BTST / post-market / paper-trading stack is a parallel workflow centered around `src/execution/`, `src/screening/`, `src/targets/`, `src/research/`, and `src/paper_trading/`. Do not assume every trading workflow comes through the simple `src/main.py` CLI path.
- The web app lives under `app/` and is split into a FastAPI backend plus a Vite/React frontend. The backend composes routes in `app/backend/routes/__init__.py`, with auth/health public and most other routes protected by JWT dependencies. The frontend boots through `app/frontend/src/main.tsx`, wrapping the app in `AuthProvider`, `AuthGuard`, `ThemeProvider`, and `NodeProvider` before rendering the ReactFlow-based UI.

## Key conventions

- Keep analyst registration in `src/utils/analysts.py` as the single source of truth. Adding a new analyst requires both the agent implementation and a registry entry there.
- Route model selection through environment-backed defaults. The repo expects explicit `LLM_DEFAULT_MODEL_PROVIDER` and `LLM_DEFAULT_MODEL_NAME`, and also uses `ANALYST_CONCURRENCY_LIMIT` plus optional per-provider overrides such as `MINIMAX_PROVIDER_CONCURRENCY_LIMIT` and `ZHIPU_PROVIDER_CONCURRENCY_LIMIT`.
- Reuse `progress.update_status(agent_id, ticker, "...")` for long-running agent work so CLI and pipeline progress remain visible.
- Python formatting intentionally uses a 420-character line length in both `black` and `flake8`. Do not normalize it back to typical defaults.
- Both `poetry.lock` and `uv.lock` are intentional and should be kept in sync rather than deduplicated away.
- Treat A-share tickers as 6-digit strings like `000001`. Free US data is limited to a small built-in set; broader coverage requires `FINANCIAL_DATASETS_API_KEY`.
- For web changes, account for the current auth flow instead of assuming all backend endpoints are public. Backend routes use auth dependencies, and the frontend assumes authenticated app startup.
