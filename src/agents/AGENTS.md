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
