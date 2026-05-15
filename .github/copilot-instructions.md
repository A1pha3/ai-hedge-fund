# Copilot Instructions

## Build, test, and lint

```bash
# Install dependencies
uv sync --group dev
# or
poetry install

# Run the main CLI workflow
uv run python src/main.py --ticker AAPL,MSFT,NVDA
uv run python src/main.py --ticker 000001,000880          # A-share tickers
uv run python src/main.py --ticker AAPL --ollama          # Local LLM via Ollama
uv run python src/main.py --show-default-model

# Run the backtester
uv run backtester --ticker 000001

# Run alternate CLI paths
uv run python src/main.py --pipeline --trade-date 20260515
uv run python src/main.py --screen-only --trade-date 20260515

# Run paper trading
source .env && .venv/bin/python scripts/run_paper_trading.py \
  --start-date 2026-02-02 --end-date 2026-03-13 --tickers 300724

# Run the web app (frontend on :5173, backend on :8000)
./app/run.sh

# Python tests
uv run pytest tests/ -v
uv run pytest tests/backtesting/ -v
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

- `src/main.py` is the orchestration entrypoint for the core hedge-fund CLI. It builds a LangGraph `StateGraph`, pulls analyst nodes from `src/utils/analysts.py`, batches them by concurrency, and then routes the combined state through `risk_management_agent` and `portfolio_management_agent`. Shared graph state lives in `src/graph/state.py`.
- There are multiple trading workflows, not one. The classic multi-agent CLI runs through `run_hedge_fund()`, while screening / post-market / BTST / paper-trading flows live under `src/screening/`, `src/execution/`, `src/targets/`, `src/research/`, and `src/paper_trading/`. `src/main.py` also exposes `--pipeline` and `--screen-only` modes for the institutional pipeline.
- LLM behavior is intentionally split: `src/llm/` defines provider catalogs and defaults, while `src/utils/llm.py` is the runtime wrapper that handles provider routing, concurrency planning, retries, fallback, timeouts, structured output, and metrics logging. Agent code should call `call_llm()` instead of provider SDKs directly.
- Backtesting is a separate subsystem under `src/backtesting/`. The `backtester` CLI (`src/backtesting/cli.py`) reuses `run_hedge_fund()` for agent-driven simulations and also owns walk-forward and A/B comparison modes. Integration tests under `tests/backtesting/integration/` replace external market-data calls with fixtures from `tests/fixtures/api/`.
- The web app under `app/` is a FastAPI backend plus a Vite/React frontend. `app/backend/routes/__init__.py` keeps `auth` and `health` public and protects the rest of the API with JWT dependencies; `app/backend/main.py` wires CORS, creates DB tables on startup, and auto-initializes the admin user when configured. The frontend boots in `app/frontend/src/main.tsx` inside `ThemeProvider`, `ErrorBoundary`, `AuthProvider`, `AuthGuard`, and `NodeProvider`.

## Key conventions

- Keep analyst registration in `src/utils/analysts.py` as the single source of truth. Adding a new analyst requires both the agent implementation and a registry entry there.
- Route model selection through environment-backed defaults. The repo expects explicit `LLM_DEFAULT_MODEL_PROVIDER` and `LLM_DEFAULT_MODEL_NAME`, and also uses `ANALYST_CONCURRENCY_LIMIT` plus optional per-provider overrides such as `MINIMAX_PROVIDER_CONCURRENCY_LIMIT` and `ZHIPU_PROVIDER_CONCURRENCY_LIMIT`.
- Reuse `progress.update_status(agent_id, ticker, "...")` for long-running agent work so CLI and pipeline progress remain visible.
- Analyst agents are expected to emit structured `signal` / `confidence` / `reasoning` outputs and write their results back into `state["data"]["analyst_signals"]`; risk and portfolio management aggregate those signals rather than trusting a single agent.
- Python formatting intentionally uses a 420-character line length in both `black` and `flake8`. Do not normalize it back to typical defaults.
- Both `poetry.lock` and `uv.lock` are intentional and should be kept in sync rather than deduplicated away.
- Treat A-share tickers as 6-digit strings like `000001`. Free US data is limited to AAPL, GOOGL, MSFT, NVDA, TSLA; broader US coverage requires `FINANCIAL_DATASETS_API_KEY`.
- For web changes, account for the current auth flow instead of assuming backend endpoints are public. The frontend assumes authenticated startup, and backend CORS should stay scoped through `get_cors_origins()` rather than widened to `*`.
- When loading saved flows in the frontend, do not clear node configuration state manually. `useNodeState` handles flow isolation, and flow-loading logic is written to preserve stored state instead of resetting it on every load or tab switch.
- Use Python 3.11–3.12; Python 3.13+ may have compatibility issues.
- Type hints (PEP 484) are required throughout; use Pydantic for validation.
- Agents must not import from each other — they are fully independent.
