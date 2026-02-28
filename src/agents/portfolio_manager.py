import json

from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing_extensions import Literal

from src.graph.state import AgentState, show_agent_reasoning
from src.utils.llm import call_llm
from src.utils.progress import progress


class PortfolioDecision(BaseModel):
    action: Literal["buy", "sell", "short", "cover", "hold"]
    quantity: int = Field(description="Number of shares to trade")
    confidence: int = Field(description="Confidence 0-100")
    reasoning: str = Field(description="Reasoning for the decision")


class PortfolioManagerOutput(BaseModel):
    decisions: dict[str, PortfolioDecision] = Field(description="Dictionary of ticker to trading decisions")


##### Portfolio Management Agent #####
def portfolio_management_agent(state: AgentState, agent_id: str = "portfolio_manager"):
    """Makes final trading decisions and generates orders for multiple tickers"""

    portfolio = state["data"]["portfolio"]
    analyst_signals = state["data"]["analyst_signals"]
    tickers = state["data"]["tickers"]

    position_limits = {}
    current_prices = {}
    max_shares = {}
    signals_by_ticker = {}
    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Processing analyst signals")

        # Find the corresponding risk manager for this portfolio manager
        if agent_id.startswith("portfolio_manager_"):
            suffix = agent_id.split("_")[-1]
            risk_manager_id = f"risk_management_agent_{suffix}"
        else:
            risk_manager_id = "risk_management_agent"  # Fallback for CLI

        risk_data = analyst_signals.get(risk_manager_id, {}).get(ticker, {})
        position_limits[ticker] = risk_data.get("remaining_position_limit", 0.0)
        current_prices[ticker] = float(risk_data.get("current_price", 0.0))

        # Calculate maximum shares allowed based on position limit and price
        if current_prices[ticker] > 0:
            max_shares[ticker] = int(position_limits[ticker] // current_prices[ticker])
        else:
            max_shares[ticker] = 0

        # Compress analyst signals to {sig, conf}
        ticker_signals = {}
        for agent, signals in analyst_signals.items():
            if not agent.startswith("risk_management_agent") and ticker in signals:
                sig = signals[ticker].get("signal")
                conf = signals[ticker].get("confidence")
                if sig is not None and conf is not None:
                    ticker_signals[agent] = {"sig": sig, "conf": conf}
        signals_by_ticker[ticker] = ticker_signals

    state["data"]["current_prices"] = current_prices

    progress.update_status(agent_id, None, "Generating trading decisions")

    result = generate_trading_decision(
        tickers=tickers,
        signals_by_ticker=signals_by_ticker,
        current_prices=current_prices,
        max_shares=max_shares,
        portfolio=portfolio,
        agent_id=agent_id,
        state=state,
    )
    message = HumanMessage(
        content=json.dumps({ticker: decision.model_dump() for ticker, decision in result.decisions.items()}),
        name=agent_id,
    )

    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning({ticker: decision.model_dump() for ticker, decision in result.decisions.items()}, "Portfolio Manager")

    progress.update_status(agent_id, None, "Done")

    return {
        "messages": state["messages"] + [message],
        "data": state["data"],
    }


def compute_allowed_actions(
    tickers: list[str],
    current_prices: dict[str, float],
    max_shares: dict[str, int],
    portfolio: dict[str, float],
) -> dict[str, dict[str, int]]:
    """Compute allowed actions and max quantities for each ticker deterministically."""
    allowed = {}
    cash = float(portfolio.get("cash", 0.0))
    positions = portfolio.get("positions", {}) or {}
    margin_requirement = float(portfolio.get("margin_requirement", 0.5))
    margin_used = float(portfolio.get("margin_used", 0.0))
    equity = float(portfolio.get("equity", cash))

    for ticker in tickers:
        price = float(current_prices.get(ticker, 0.0))
        pos = positions.get(
            ticker,
            {"long": 0, "long_cost_basis": 0.0, "short": 0, "short_cost_basis": 0.0},
        )
        long_shares = int(pos.get("long", 0) or 0)
        short_shares = int(pos.get("short", 0) or 0)
        max_qty = int(max_shares.get(ticker, 0) or 0)

        # Start with zeros
        actions = {"buy": 0, "sell": 0, "short": 0, "cover": 0, "hold": 0}

        # Long side
        if long_shares > 0:
            actions["sell"] = long_shares
        if cash > 0 and price > 0:
            max_buy_cash = int(cash // price)
            max_buy = max(0, min(max_qty, max_buy_cash))
            if max_buy > 0:
                actions["buy"] = max_buy

        # Short side
        if short_shares > 0:
            actions["cover"] = short_shares
        if price > 0 and max_qty > 0:
            if margin_requirement <= 0.0:
                # If margin requirement is zero or unset, only cap by max_qty
                max_short = max_qty
            else:
                available_margin = max(0.0, (equity / margin_requirement) - margin_used)
                max_short_margin = int(available_margin // price)
                max_short = max(0, min(max_qty, max_short_margin))
            if max_short > 0:
                actions["short"] = max_short

        # Hold always valid
        actions["hold"] = 0

        # Prune zero-capacity actions to reduce tokens, keep hold
        pruned = {"hold": 0}
        for k, v in actions.items():
            if k != "hold" and v > 0:
                pruned[k] = v

        allowed[ticker] = pruned

    return allowed


def _make_decision_from_signals(ticker: str, signals: dict, allowed: dict) -> "PortfolioDecision":
    """
    Make a trading decision based on analyst signals when LLM fails.
    Uses weighted voting based on confidence levels.
    """
    def _confidence_int(value: float) -> int:
        return max(0, min(100, int(round(value))))

    if not signals:
        return PortfolioDecision(action="hold", quantity=0, confidence=0, reasoning="无分析师信号，默认持有")

    bullish_weight = 0.0
    bearish_weight = 0.0
    neutral_weight = 0.0
    total_confidence = 0.0

    for agent, payload in signals.items():
        sig = payload.get("sig", "").lower()
        conf = float(payload.get("conf", 0))
        total_confidence += conf

        if sig == "bullish":
            bullish_weight += conf
        elif sig == "bearish":
            bearish_weight += conf
        else:
            neutral_weight += conf * 0.5

    total_weight = bullish_weight + bearish_weight + neutral_weight
    if total_weight == 0:
        return PortfolioDecision(action="hold", quantity=0, confidence=0, reasoning="分析师信号权重为零")

    avg_confidence = total_confidence / len(signals) if signals else 0

    if bullish_weight > bearish_weight * 1.5 and "buy" in allowed:
        qty = min(allowed.get("buy", 0), 100)
        reasoning = f"多数分析师看涨(权重{bullish_weight:.0f} vs {bearish_weight:.0f})，建议买入"
        return PortfolioDecision(action="buy", quantity=qty, confidence=_confidence_int(min(avg_confidence, 80)), reasoning=reasoning)
    elif bearish_weight > bullish_weight * 1.5:
        if "short" in allowed:
            qty = min(allowed.get("short", 0), 100)
            reasoning = f"多数分析师看跌(权重{bearish_weight:.0f} vs {bullish_weight:.0f})，建议做空"
            return PortfolioDecision(action="short", quantity=qty, confidence=_confidence_int(min(avg_confidence, 80)), reasoning=reasoning)
        elif "sell" in allowed:
            qty = allowed.get("sell", 0)
            reasoning = f"多数分析师看跌(权重{bearish_weight:.0f} vs {bullish_weight:.0f})，建议卖出"
            return PortfolioDecision(action="sell", quantity=qty, confidence=_confidence_int(min(avg_confidence, 80)), reasoning=reasoning)

    return PortfolioDecision(action="hold", quantity=0, confidence=_confidence_int(avg_confidence * 0.5), reasoning=f"信号分歧(涨{bullish_weight:.0f}/跌{bearish_weight:.0f})，建议观望")


def _compact_signals(signals_by_ticker: dict[str, dict]) -> dict[str, dict]:
    """Keep only {agent: {sig, conf}} and drop empty agents."""
    out = {}
    for t, agents in signals_by_ticker.items():
        if not agents:
            out[t] = {}
            continue
        compact = {}
        for agent, payload in agents.items():
            sig = payload.get("sig") or payload.get("signal")
            conf = payload.get("conf") if "conf" in payload else payload.get("confidence")
            if sig is not None and conf is not None:
                compact[agent] = {"sig": sig, "conf": conf}
        out[t] = compact
    return out


def _build_consistent_reasoning(signals: dict, action: str) -> str:
    """Build deterministic Chinese reasoning that is consistent with actual signal counts."""
    if not signals:
        return "无分析师信号，保持观望"

    counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    top_by_signal: dict[str, list[tuple[str, float]]] = {"bullish": [], "bearish": [], "neutral": []}

    for agent, payload in signals.items():
        sig = str(payload.get("sig", "neutral")).lower()
        if sig not in counts:
            sig = "neutral"
        conf = float(payload.get("conf", 0) or 0)
        counts[sig] += 1
        top_by_signal[sig].append((agent, conf))

    def _top_agents(sig: str) -> str:
        ranked = sorted(top_by_signal[sig], key=lambda item: item[1], reverse=True)[:2]
        if not ranked:
            return ""

        def _format_agent_name(agent_id: str) -> str:
            return agent_id.replace("_agent", "").replace("_", " ").title()

        return "、".join(f"{_format_agent_name(name)}({int(round(conf))}%)" for name, conf in ranked)

    if action in {"short", "sell"}:
        top = _top_agents("bearish")
        if top:
            return f"看跌{counts['bearish']}票/中性{counts['neutral']}票/看涨{counts['bullish']}票，{top}偏空"
        return f"看跌{counts['bearish']}票/中性{counts['neutral']}票/看涨{counts['bullish']}票，整体偏空"

    if action in {"buy", "cover"}:
        top = _top_agents("bullish")
        if top:
            return f"看涨{counts['bullish']}票/中性{counts['neutral']}票/看跌{counts['bearish']}票，{top}偏多"
        return f"看涨{counts['bullish']}票/中性{counts['neutral']}票/看跌{counts['bearish']}票，整体偏多"

    return f"看涨{counts['bullish']}票/看跌{counts['bearish']}票/中性{counts['neutral']}票，信号分歧"


def generate_trading_decision(
    tickers: list[str],
    signals_by_ticker: dict[str, dict],
    current_prices: dict[str, float],
    max_shares: dict[str, int],
    portfolio: dict[str, float],
    agent_id: str,
    state: AgentState,
) -> PortfolioManagerOutput:
    """Get decisions from the LLM with deterministic constraints and a minimal prompt."""

    # Deterministic constraints
    allowed_actions_full = compute_allowed_actions(tickers, current_prices, max_shares, portfolio)

    # Pre-fill pure holds to avoid sending them to the LLM at all
    prefilled_decisions: dict[str, PortfolioDecision] = {}
    tickers_for_llm: list[str] = []
    for t in tickers:
        aa = allowed_actions_full.get(t, {"hold": 0})
        # If only 'hold' key exists, there is no trade possible
        if set(aa.keys()) == {"hold"}:
            prefilled_decisions[t] = PortfolioDecision(action="hold", quantity=0, confidence=100, reasoning="No valid trade available")
        else:
            tickers_for_llm.append(t)

    if not tickers_for_llm:
        return PortfolioManagerOutput(decisions=prefilled_decisions)

    # Build compact payloads only for tickers sent to LLM
    compact_signals = _compact_signals({t: signals_by_ticker.get(t, {}) for t in tickers_for_llm})
    compact_allowed = {t: allowed_actions_full[t] for t in tickers_for_llm}

    # Minimal prompt template
    template = ChatPromptTemplate.from_messages(
        [
            ("system", "You are a portfolio manager.\n" "Inputs per ticker: analyst signals and allowed actions with max qty (already validated).\n" "Pick one allowed action per ticker and a quantity ≤ the max. " "Keep reasoning very concise (max 100 chars). No cash or margin math. Return JSON only.\n" "IMPORTANT: All reasoning must be in Chinese (中文)."),
            ("human", "Signals:\n{signals}\n\n" "Allowed:\n{allowed}\n\n" "Format:\n" "{{\n" '  "decisions": {{\n' '    "TICKER": {{"action":"...","quantity":int,"confidence":int,"reasoning":"..."}}\n' "  }}\n" "}}\n\n" "注意：reasoning 字段必须使用中文回答。"),
        ]
    )

    prompt_data = {
        "signals": json.dumps(compact_signals, separators=(",", ":"), ensure_ascii=False),
        "allowed": json.dumps(compact_allowed, separators=(",", ":"), ensure_ascii=False),
    }
    prompt = template.invoke(prompt_data)

    def create_default_portfolio_output():
        decisions = dict(prefilled_decisions)
        for t in tickers_for_llm:
            signals = compact_signals.get(t, {})
            decision = _make_decision_from_signals(t, signals, compact_allowed.get(t, {"hold": 0}))
            decisions[t] = decision
        return PortfolioManagerOutput(decisions=decisions)

    llm_out = call_llm(
        prompt=prompt,
        pydantic_model=PortfolioManagerOutput,
        agent_name=agent_id,
        state=state,
        default_factory=create_default_portfolio_output,
    )

    # Post-LLM consistency guard:
    # If LLM outputs a low-confidence HOLD while signals indicate a clear directional bias
    # and valid non-hold actions exist, fall back to deterministic rule-based decision.
    validated_decisions: dict[str, PortfolioDecision] = {}
    for t in tickers_for_llm:
        llm_decision = llm_out.decisions.get(t)
        if llm_decision is None:
            fallback = _make_decision_from_signals(t, compact_signals.get(t, {}), compact_allowed.get(t, {"hold": 0}))
            validated_decisions[t] = PortfolioDecision(
                action=fallback.action,
                quantity=fallback.quantity,
                confidence=fallback.confidence,
                reasoning=_build_consistent_reasoning(compact_signals.get(t, {}), fallback.action),
            )
            continue

        fallback_decision = _make_decision_from_signals(t, compact_signals.get(t, {}), compact_allowed.get(t, {"hold": 0}))

        should_override = (
            llm_decision.action == "hold"
            and fallback_decision.action != "hold"
            and int(llm_decision.confidence) <= 20
        )

        chosen = fallback_decision if should_override else llm_decision

        # Action/quantity consistency guard against invalid LLM output
        allowed_for_ticker = compact_allowed.get(t, {"hold": 0})
        if chosen.action not in allowed_for_ticker:
            chosen = fallback_decision

        if chosen.action == "hold":
            normalized_quantity = 0
        else:
            action_limit = int(allowed_for_ticker.get(chosen.action, 0) or 0)
            normalized_quantity = max(0, min(int(chosen.quantity), action_limit))

        validated_decisions[t] = PortfolioDecision(
            action=chosen.action,
            quantity=normalized_quantity,
            confidence=max(0, min(100, int(chosen.confidence))),
            reasoning=_build_consistent_reasoning(compact_signals.get(t, {}), chosen.action),
        )

    # Merge prefilled holds with LLM results
    merged = dict(prefilled_decisions)
    merged.update(validated_decisions)
    return PortfolioManagerOutput(decisions=merged)
