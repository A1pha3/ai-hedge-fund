from src.utils.numeric import safe_float


def _resolve_portfolio_position(positions: dict, ticker: str) -> tuple[int, int]:
    position = positions.get(
        ticker,
        {"long": 0, "long_cost_basis": 0.0, "short": 0, "short_cost_basis": 0.0},
    )
    return int(position.get("long", 0) or 0), int(position.get("short", 0) or 0)


def _resolve_max_buy(cash: float, price: float, max_qty: int) -> int:
    if cash != cash or price != price:
        # NaN guard: NaN comparisons are always False, so the cash/price <= 0
        # guard would otherwise pass through NaN and crash int(NaN // price).
        return 0
    if cash <= 0 or price <= 0:
        return 0
    if max_qty is None or max_qty != max_qty:
        # None or NaN max_qty means no cap was provided by the risk manager;
        # treat as 0 (no buy allowed) rather than crashing min(None, int).
        return 0
    max_buy_cash = int(cash // price)
    return max(0, min(int(max_qty), max_buy_cash))


def _resolve_max_short(price: float, max_qty: int, margin_requirement: float, margin_used: float, equity: float) -> int:
    if price != price or price <= 0:
        return 0
    if max_qty is None or max_qty != max_qty or max_qty <= 0:
        # None or NaN max_qty must degrade to 0 (no short allowed) rather
        # than crashing int(NaN // per_share_cost).
        return 0
    if equity != equity:
        # NaN equity would propagate through available_margin and crash int().
        return 0
    if margin_requirement != margin_requirement:
        # NaN margin_requirement would crash int(available // NaN).
        # Fail closed (return 0) — risk budget must not be silently bypassed
        # by corrupt config / upstream NaN.
        return 0
    if margin_requirement <= 0.0:
        return int(max_qty)

    # Standard short-selling margin formula:
    # Each short share requires `price * margin_requirement` of margin collateral.
    # Available margin is the portion of equity not already locked as margin.
    # Max shares = available_equity / per_share_margin_cost
    #   where available_equity = equity - margin_used
    #   and per_share_cost = price * margin_requirement
    available_equity = max(0.0, equity - margin_used)
    max_short_margin = int(available_equity // (price * margin_requirement))
    return max(0, min(int(max_qty), max_short_margin))


def _prune_zero_actions(actions: dict[str, int]) -> dict[str, int]:
    return {"hold": 0, **{a: q for a, q in actions.items() if a != "hold" and q > 0}}


def _confidence_int(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _accumulate_signal_weights(signals: dict) -> tuple[float, float, float, float]:
    bullish_weight = 0.0
    bearish_weight = 0.0
    neutral_weight = 0.0
    total_confidence = 0.0

    for payload in signals.values():
        signal = payload.get("sig", "").lower()
        # R100 (R73/R76 bare-coercion 同族): ``.get("conf", 0)`` 默认值仅在 key
        # 缺失时生效, key 存在且值为 JSON null 时返回 None, 裸 ``float(None)`` 抛
        # TypeError 中断整个 generate_trading_decision 交易决策路径。当前两个
        # caller (portfolio_manager.py:82 / :201) 都用 ``is not None`` 守卫, 故
        # 现为 latent; 但本 helper 是 public decision-path 边界, 未来 caller
        # (web/JSON snapshot / serialized state replay) 易传 null。改用 safe_float
        # 与 R73 (--top score_b=null) / R76 (--why-not score_b=null) 一致, 在边界
        # 处 fail-soft 而非崩整个决策。
        confidence = safe_float(payload.get("conf"), 0.0)
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
        # R100: 同上 — 改用 safe_float。原 ``or 0`` 虽然 null-safe, 但带 R68/R69/R96
        # falsy-zero 潜在风险 (conf=0.0 真实"零信心"会被 ``0.0 or 0`` 短路保留为 0,
        # 当前语义恰好一致故非 active bug, 但与 _accumulate_signal_weights 路径分裂)。
        # 统一 safe_float 消除两条 decision-path confidence 解析的语义分裂。
        confidence = safe_float(payload.get("conf"), 0.0)
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
