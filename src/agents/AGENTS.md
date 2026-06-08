# src/agents/

## OVERVIEW

21 independent AI agents (12 famous investors + 6 functional analysts + 2 managers) — all follow identical functional pattern, no cross-agent dependencies.

## AGENT ROSTER

| File | Agent ID | Type | Strategy |
|------|----------|------|----------|
| `warren_buffett.py` | `warren_buffett_agent` | Investor | Value investing, competitive moat, DCF |
| `ben_graham.py` | `ben_graham_agent` | Investor | Deep value, Graham Number, net-net |
| `charlie_munger.py` | `charlie_munger_agent` | Investor | Quality at fair price |
| `phil_fisher.py` | `phil_fisher_agent` | Investor | Scuttlebutt growth research |
| `bill_ackman.py` | `bill_ackman_agent` | Investor | Activist, high conviction |
| `cathie_wood.py` | `cathie_wood_agent` | Investor | Disruptive innovation |
| `peter_lynch.py` | `peter_lynch_agent` | Investor | Ten-baggers, PEG ratio |
| `michael_burry.py` | `michael_burry_agent` | Investor | Contrarian, deep value |
| `mohnish_pabrai.py` | `mohnish_pabrai_agent` | Investor | Dhandho, low risk high return |
| `rakesh_jhunjhunwala.py` | `rakesh_jhunjhunwala_agent` | Investor | Emerging markets |
| `stanley_druckenmiller.py` | `stanley_druckenmiller_agent` | Investor | Macro, asymmetric bets |
| `aswath_damodaran.py` | `aswath_damodaran_agent` | Investor | Story + numbers valuation |
| `valuation.py` | `valuation_analyst_agent` | Analyst | DCF, EV/EBITDA, residual income |
| `technicals.py` | `technical_analyst_agent` | Analyst | Chart patterns, indicators |
| `fundamentals.py` | `fundamentals_analyst_agent` | Analyst | Financial statement analysis |
| `sentiment.py` | `sentiment_analyst_agent` | Analyst | Behavioral / market sentiment |
| `news_sentiment.py` | `news_sentiment_agent` | Analyst | Company news scoring |
| `growth_agent.py` | `growth_analyst_agent` | Analyst | Revenue/earnings growth trends |
| `risk_manager.py` | `risk_management_agent` | Manager | Volatility-based position sizing |
| `portfolio_manager.py` | `portfolio_management_agent` | Manager | Aggregates signals → trading orders |

## ADDING A NEW AGENT

1. Create `src/agents/your_agent.py` following the template below
2. Register in `src/utils/analysts.py` → `ANALYST_CONFIG` dict
3. Done — LangGraph workflow picks it up automatically

## AGENT TEMPLATE

```python
import json
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing_extensions import Literal

from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import get_financial_metrics, get_market_cap, search_line_items
from src.utils.api_key import get_api_key_from_state
from src.utils.llm import call_llm
from src.utils.progress import progress

class YourSignal(BaseModel):
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str

def your_agent(state: AgentState, agent_id: str = "your_agent"):
    data = state["data"]
    tickers = data["tickers"]
    results = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Analyzing")
        # ... fetch data, analyze, call LLM ...
        progress.update_status(agent_id, ticker, "Done", analysis=output.reasoning)
        results[ticker] = {"signal": ..., "confidence": ..., "reasoning": ...}

    message = HumanMessage(content=json.dumps(results), name=agent_id)
    state["data"]["analyst_signals"][agent_id] = results
    return {"messages": [message], "data": state["data"]}
```

## CONVENTIONS

- **No cross-agent imports** — agents are fully independent
- **All LLM calls** via `call_llm()` — never direct provider calls
- **Progress tracking** required — `progress.update_status(agent_id, ticker, "Step")`
- **Output format** — `{"signal": "bullish"|"bearish"|"neutral", "confidence": 0-100, "reasoning": "..."}`
- **Prompt pattern** — `ChatPromptTemplate.from_messages([("system", ...), ("human", ...)])`
- **Naming** — file: `snake_case.py`, function: `xxx_agent`, model: `XxxSignal`

## R20.8 KNOWN DUPLICATION (future consolidation candidates)

The agent return-state pattern is duplicated across many files. The two
variants are functionally equivalent (LangGraph reducer merges messages):

**Variant A** — `{"messages": [message], "data": state["data"]}` (12 agents):
- `src/agents/aswath_damodaran.py:162`
- `src/agents/ben_graham.py:109`
- `src/agents/bill_ackman.py:130`
- `src/agents/cathie_wood.py:148`
- `src/agents/charlie_munger.py:174`
- `src/agents/michael_burry.py:153`
- `src/agents/mohnish_pabrai.py:144`
- `src/agents/peter_lynch.py:173`
- `src/agents/phil_fisher.py:175`
- `src/agents/rakesh_jhunjhunwala.py:161`
- `src/agents/stanley_druckenmiller.py:173`
- `src/agents/warren_buffett.py:185`

**Variant B** — `{"messages": state["messages"] + [message], "data": data}` (6 agents):
- `src/agents/fundamentals.py:90`
- `src/agents/growth_agent.py:159` (uses `data` local)
- `src/agents/news_sentiment.py:142`
- `src/agents/portfolio_manager.py:102`
- `src/agents/risk_manager.py:83`
- `src/agents/sentiment.py:152`
- `src/agents/technicals.py:320`
- `src/agents/valuation.py:176` (uses `data` local)

**Other duplicated patterns** (not yet refactored):
- `state["data"]["analyst_signals"][agent_id] = results` — present in all 20 agents
- `if state["metadata"].get("show_reasoning"): show_agent_reasoning(...)` — 20 agents
- `progress.update_status(agent_id, None, "Done")` at the end of each agent — 20 agents
- `HumanMessage(content=json.dumps(results), name=agent_id)` — 20 agents

**Consolidation plan (deferred, R20.9+)**:
- Extract `src/agents/_state.py` with `make_agent_return(message, state, data=None)`
  helper that unifies Variants A & B (defaults to `state["data"]`).
- Add `record_agent_signals(state, agent_id, results)` to remove the
  `analyst_signals` dict-update duplication.
- Add `agent_done(agent_id, message, results, state, show_reasoning)` to merge
  the four end-of-agent idioms into a single helper.
- Do NOT refactor across files in R20.8 — pure refactor risk is high and the
  duplication is shallow and well-localized.
