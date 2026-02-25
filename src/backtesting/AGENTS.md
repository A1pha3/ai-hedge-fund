# src/backtesting/

## OVERVIEW

Modular backtesting subsystem — runs hedge fund agents over historical date ranges, tracks portfolio performance with full metrics. Separate from legacy `src/backtester.py`.

## STRUCTURE

```
backtesting/
├── cli.py              # Entry point (poetry run backtester)
├── engine.py           # Core backtest loop: iterate dates → run agents → execute trades
├── controller.py       # Orchestrates engine + results collection
├── execution.py        # Trade execution simulation (fills, slippage)
├── portfolio.py        # Portfolio state: positions, cash, margin
├── valuation.py        # Portfolio valuation at each timestep
├── metrics.py          # Performance metrics (Sharpe, drawdown, returns)
├── results.py          # Results aggregation and formatting
├── types.py            # Shared type definitions
├── router.py           # Data routing for backtest context
└── __init__.py
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add CLI flag | `cli.py` | Uses `src/cli/input.py` shared parser |
| Modify backtest loop | `engine.py` | Date iteration + agent execution |
| Change trade execution | `execution.py` | Fill logic, margin checks |
| Add performance metric | `metrics.py` | Sharpe, max drawdown, etc. |
| Fix portfolio tracking | `portfolio.py` | Position sizing, cash management |

## CONVENTIONS

- **Entry point**: `poetry run backtester --ticker AAPL` (registered in `pyproject.toml [tool.poetry.scripts]`)
- **Legacy**: `src/backtester.py` still works but this module is the replacement
- **Tests**: `tests/backtesting/` (unit) + `tests/backtesting/integration/` (with JSON fixtures)
- **Integration tests** auto-mock all external API calls via `conftest.py` autouse fixtures
