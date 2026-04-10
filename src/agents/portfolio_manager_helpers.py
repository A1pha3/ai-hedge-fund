def _resolve_portfolio_position(positions: dict, ticker: str) -> tuple[int, int]:
    position = positions.get(
        ticker,
        {"long": 0, "long_cost_basis": 0.0, "short": 0, "short_cost_basis": 0.0},
    )
    return int(position.get("long", 0) or 0), int(position.get("short", 0) or 0)


def _resolve_max_buy(cash: float, price: float, max_qty: int) -> int:
    if cash <= 0 or price <= 0:
        return 0
    max_buy_cash = int(cash // price)
    return max(0, min(max_qty, max_buy_cash))


def _resolve_max_short(price: float, max_qty: int, margin_requirement: float, margin_used: float, equity: float) -> int:
    if price <= 0 or max_qty <= 0:
        return 0
    if margin_requirement <= 0.0:
        return max_qty

    available_margin = max(0.0, (equity / margin_requirement) - margin_used)
    max_short_margin = int(available_margin // price)
    return max(0, min(max_qty, max_short_margin))


def _prune_zero_actions(actions: dict[str, int]) -> dict[str, int]:
    pruned = {"hold": 0}
    for action, quantity in actions.items():
        if action != "hold" and quantity > 0:
            pruned[action] = quantity
    return pruned


def _confidence_int(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _accumulate_signal_weights(signals: dict) -> tuple[float, float, float, float]:
    bullish_weight = 0.0
    bearish_weight = 0.0
    neutral_weight = 0.0
    total_confidence = 0.0

    for payload in signals.values():
        signal = payload.get("sig", "").lower()
        confidence = float(payload.get("conf", 0))
        total_confidence += confidence
        if signal == "bullish":
            bullish_weight += confidence
        elif signal == "bearish":
            bearish_weight += confidence
        else:
            neutral_weight += confidence * 0.5

    return bullish_weight, bearish_weight, neutral_weight, total_confidence


def _build_buy_decision(allowed: dict, bullish_weight: float, bearish_weight: float, avg_confidence: float, decision_model):
    quantity = min(allowed.get("buy", 0), 100)
    return decision_model(
        action="buy",
        quantity=quantity,
        confidence=_confidence_int(min(avg_confidence, 80)),
        reasoning=f"多数分析师看涨(权重{bullish_weight:.0f} vs {bearish_weight:.0f})，建议买入",
    )


def _build_short_or_sell_decision(allowed: dict, bearish_weight: float, bullish_weight: float, avg_confidence: float, decision_model):
    confidence = _confidence_int(min(avg_confidence, 80))
    if "short" in allowed:
        quantity = min(allowed.get("short", 0), 100)
        return decision_model(
            action="short",
            quantity=quantity,
            confidence=confidence,
            reasoning=f"多数分析师看跌(权重{bearish_weight:.0f} vs {bullish_weight:.0f})，建议做空",
        )
    if "sell" in allowed:
        quantity = allowed.get("sell", 0)
        return decision_model(
            action="sell",
            quantity=quantity,
            confidence=confidence,
            reasoning=f"多数分析师看跌(权重{bearish_weight:.0f} vs {bullish_weight:.0f})，建议卖出",
        )
    return None


def _normalize_signal_label(signal: str, counts: dict[str, int]) -> str:
    normalized = str(signal).lower()
    if normalized not in counts:
        return "neutral"
    return normalized


def _collect_signal_counts(signals: dict) -> tuple[dict[str, int], dict[str, list[tuple[str, float]]]]:
    counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    top_by_signal: dict[str, list[tuple[str, float]]] = {"bullish": [], "bearish": [], "neutral": []}

    for agent, payload in signals.items():
        signal = _normalize_signal_label(payload.get("sig", "neutral"), counts)
        confidence = float(payload.get("conf", 0) or 0)
        counts[signal] += 1
        top_by_signal[signal].append((agent, confidence))

    return counts, top_by_signal


def _format_agent_name(agent_id: str) -> str:
    return agent_id.replace("_agent", "").replace("_", " ").title()


def _format_top_agents(top_by_signal: dict[str, list[tuple[str, float]]], signal: str) -> str:
    ranked = sorted(top_by_signal[signal], key=lambda item: item[1], reverse=True)[:2]
    if not ranked:
        return ""
    return "、".join(f"{_format_agent_name(name)}({int(round(conf))}%)" for name, conf in ranked)
