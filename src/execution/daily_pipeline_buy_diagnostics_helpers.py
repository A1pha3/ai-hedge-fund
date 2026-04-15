from __future__ import annotations

from typing import Any, Callable


def prepare_buy_order_execution_context(
    *,
    watchlist: list[Any],
    portfolio_snapshot: dict[str, Any],
    candidate_by_ticker: dict[str, Any] | None,
    price_map: dict[str, float] | None,
    blocked_buy_tickers: dict[str, dict[str, Any]],
    selection_targets: dict[str, Any] | None,
) -> dict[str, Any]:
    cash = float(portfolio_snapshot.get("cash", 0.0))
    nav = cash + sum(
        float(position.get("long", 0)) * float(position.get("long_cost_basis", 0.0))
        for position in portfolio_snapshot.get("positions", {}).values()
    )
    nav = nav if nav > 0 else cash
    return {
        "cash": cash,
        "nav": nav,
        "per_name_cash": cash / max(1, min(3, len(watchlist))),
        "candidate_by_ticker": candidate_by_ticker or {},
        "price_map": price_map or {},
        "blocked_buy_tickers": blocked_buy_tickers,
        "selection_targets": selection_targets or {},
    }


def build_no_cash_buy_order_summary(
    *,
    watchlist: list[Any],
    build_filter_summary_fn: Callable[[list[dict[str, Any]]], dict[str, Any]],
) -> dict[str, Any]:
    entries = [
        {
            "ticker": item.ticker,
            "reason": "no_available_cash",
            "score_final": round(item.score_final, 4),
        }
        for item in watchlist
    ]
    summary = build_filter_summary_fn(entries)
    summary["selected_tickers"] = []
    return summary


def build_reentry_filter_payload(
    *,
    ticker: str,
    score_final: float,
    cooldown_payload: dict[str, Any],
    trade_date: str,
    selection_target: Any,
    resolve_reentry_required_score_fn: Callable[[dict[str, Any], Any], tuple[float, bool]],
) -> dict[str, Any] | None:
    normalized_ticker = str(ticker)
    blocked_until = str(cooldown_payload.get("blocked_until") or "")
    trigger_reason = str(cooldown_payload.get("trigger_reason") or "")
    exit_trade_date = str(cooldown_payload.get("exit_trade_date") or "")
    if blocked_until and trade_date and trade_date < blocked_until:
        return {
            "ticker": normalized_ticker,
            "reason": "blocked_by_exit_cooldown",
            "score_final": round(score_final, 4),
            "blocked_until": blocked_until,
            "trigger_reason": trigger_reason,
            "exit_trade_date": exit_trade_date,
        }

    reentry_review_until = str(cooldown_payload.get("reentry_review_until") or "")
    required_score, weak_confirmation_reentry_guard = resolve_reentry_required_score_fn(cooldown_payload, selection_target)
    if reentry_review_until and trade_date and trade_date <= reentry_review_until and score_final < required_score:
        return {
            "ticker": normalized_ticker,
            "reason": "blocked_by_reentry_score_confirmation",
            "score_final": round(score_final, 4),
            "required_score": round(required_score, 4),
            "weak_confirmation_reentry_guard": weak_confirmation_reentry_guard,
            "reentry_review_until": reentry_review_until,
            "trigger_reason": trigger_reason,
            "exit_trade_date": exit_trade_date,
        }

    return None


def _resolve_short_trade_target_result(selection_target: Any) -> Any:
    if selection_target is None:
        return None
    short_trade_result = getattr(selection_target, "short_trade", None)
    if short_trade_result is not None:
        return short_trade_result
    if isinstance(selection_target, dict):
        return selection_target.get("short_trade") or selection_target
    return selection_target


def build_short_trade_execution_gate_filter_payload(
    *,
    item: Any,
    selection_target: Any,
) -> dict[str, Any] | None:
    short_trade_result = _resolve_short_trade_target_result(selection_target)
    if short_trade_result is None:
        return None

    metrics_payload = dict(getattr(short_trade_result, "metrics_payload", {}) or {})
    explainability_payload = dict(getattr(short_trade_result, "explainability_payload", {}) or {})
    thresholds = dict(metrics_payload.get("thresholds") or {})
    breakout_trap_guard = dict(metrics_payload.get("breakout_trap_guard") or explainability_payload.get("breakout_trap_guard") or {})
    market_state_threshold_adjustment = dict(thresholds.get("market_state_threshold_adjustment") or explainability_payload.get("market_state_threshold_adjustment") or {})
    decision = str(getattr(short_trade_result, "decision", None) or "").strip().lower()
    gate_status = dict(getattr(short_trade_result, "gate_status", {}) or {})
    blockers = [str(blocker) for blocker in list(getattr(short_trade_result, "blockers", []) or []) if str(blocker or "").strip()]
    breakout_trap_risk = float(breakout_trap_guard.get("risk", 0.0) or 0.0)
    breakout_trap_penalty = float(breakout_trap_guard.get("penalty", 0.0) or 0.0)
    risk_level = str(market_state_threshold_adjustment.get("risk_level") or "unknown").strip().lower()
    regime_gate_level = str(market_state_threshold_adjustment.get("regime_gate_level") or risk_level or "unknown").strip().lower()

    if bool(breakout_trap_guard.get("blocked")) or bool(breakout_trap_guard.get("execution_blocked")) or "breakout_trap_risk" in blockers or "breakout_trap_execution_hard_gate" in blockers:
        reason = "blocked_by_breakout_trap_risk"
    elif bool(market_state_threshold_adjustment.get("execution_hard_gate")):
        reason = "blocked_by_market_regime_gate"
    elif decision == "blocked" or gate_status.get("execution") == "fail":
        reason = "blocked_by_short_trade_target"
    else:
        return None

    return {
        "ticker": item.ticker,
        "reason": reason,
        "score_final": round(float(item.score_final), 4),
        "quality_score": round(float(item.quality_score), 4),
        "short_trade_decision": decision,
        "risk_level": risk_level,
        "regime_gate_level": regime_gate_level,
        "breakout_trap_risk": round(breakout_trap_risk, 4),
        "breakout_trap_penalty": round(breakout_trap_penalty, 4),
        "execution_gate_status": str(gate_status.get("execution") or "pass"),
        "blockers": blockers,
        "candidate_source": str(getattr(short_trade_result, "candidate_source", None) or ""),
        "top_reasons": [str(reason) for reason in list(getattr(short_trade_result, "top_reasons", []) or [])[:5]],
    }


def process_buy_order_watchlist_item(
    *,
    item,
    portfolio_snapshot: dict[str, Any],
    trade_date: str,
    cash: float,
    nav: float,
    per_name_cash: float,
    candidate_by_ticker: dict[str, Any],
    price_map: dict[str, float],
    blocked_buy_tickers: dict[str, dict[str, Any]],
    selection_targets: dict[str, Any],
    build_reentry_filter_entry_fn: Callable[..., dict[str, Any] | None],
    resolve_continuation_execution_overrides_fn: Callable[..., dict[str, Any]],
    calculate_position_fn: Callable[..., Any],
) -> dict[str, Any]:
    selection_target = selection_targets.get(item.ticker)
    cooldown_payload = blocked_buy_tickers.get(item.ticker)
    if cooldown_payload is not None:
        reentry_filter_entry = build_reentry_filter_entry_fn(
            item,
            cooldown_payload,
            trade_date,
            selection_target=selection_target,
        )
        if reentry_filter_entry is not None:
            return {"buy_plan": None, "filtered_entry": reentry_filter_entry}

    short_trade_execution_filter_entry = build_short_trade_execution_gate_filter_payload(
        item=item,
        selection_target=selection_target,
    )
    if short_trade_execution_filter_entry is not None:
        return {"buy_plan": None, "filtered_entry": short_trade_execution_filter_entry}

    current_price = float(price_map.get(item.ticker, 10.0))
    candidate = candidate_by_ticker.get(item.ticker)
    avg_volume_20d = float(candidate.avg_volume_20d) if candidate and candidate.avg_volume_20d > 0 else 10_000_000.0
    industry_quota = nav * 0.25
    existing_position = portfolio_snapshot.get("positions", {}).get(item.ticker, {})
    existing_long_shares = float(existing_position.get("long", 0.0))
    existing_position_ratio = ((existing_long_shares * current_price) / nav) if nav > 0 else 0.0
    continuation_overrides = resolve_continuation_execution_overrides_fn(
        item=item,
        selection_target=selection_target,
    )
    plan = calculate_position_fn(
        ticker=item.ticker,
        current_price=current_price,
        score_final=item.score_final,
        portfolio_nav=nav,
        available_cash=min(cash, per_name_cash),
        avg_volume_20d=avg_volume_20d,
        industry_remaining_quota=industry_quota,
        quality_score=item.quality_score,
        existing_position_ratio=existing_position_ratio,
        watchlist_min_score_override=continuation_overrides.get("watchlist_min_score_override"),
        watchlist_edge_execution_ratio_override=continuation_overrides.get("watchlist_edge_execution_ratio_override"),
    )
    if plan.shares > 0:
        return {"buy_plan": plan, "filtered_entry": None}

    return {
        "buy_plan": None,
        "filtered_entry": {
            "ticker": item.ticker,
            "reason": f"position_blocked_{plan.constraint_binding or 'unknown'}",
            "score_final": round(item.score_final, 4),
            "constraint_binding": plan.constraint_binding,
            "amount": round(plan.amount, 4),
            "execution_ratio": plan.execution_ratio,
            "quality_score": round(plan.quality_score, 4),
            "continuation_execution_override": bool(continuation_overrides.get("applied")),
        },
    }


def collect_buy_order_candidates(
    *,
    watchlist: list[Any],
    portfolio_snapshot: dict[str, Any],
    trade_date: str,
    cash: float,
    nav: float,
    per_name_cash: float,
    candidate_by_ticker: dict[str, Any],
    price_map: dict[str, float],
    blocked_buy_tickers: dict[str, dict[str, Any]],
    selection_targets: dict[str, Any],
    build_reentry_filter_entry_fn: Callable[..., dict[str, Any] | None],
    resolve_continuation_execution_overrides_fn: Callable[..., dict[str, Any]],
    calculate_position_fn: Callable[..., Any],
) -> tuple[list[Any], list[dict[str, Any]]]:
    candidate_plans: list[Any] = []
    filtered_entries: list[dict[str, Any]] = []
    for item in watchlist:
        result = process_buy_order_watchlist_item(
            item=item,
            portfolio_snapshot=portfolio_snapshot,
            trade_date=trade_date,
            cash=cash,
            nav=nav,
            per_name_cash=per_name_cash,
            candidate_by_ticker=candidate_by_ticker,
            price_map=price_map,
            blocked_buy_tickers=blocked_buy_tickers,
            selection_targets=selection_targets,
            build_reentry_filter_entry_fn=build_reentry_filter_entry_fn,
            resolve_continuation_execution_overrides_fn=resolve_continuation_execution_overrides_fn,
            calculate_position_fn=calculate_position_fn,
        )
        if result["buy_plan"] is not None:
            candidate_plans.append(result["buy_plan"])
            continue
        if result["filtered_entry"] is not None:
            filtered_entries.append(result["filtered_entry"])
    return candidate_plans, filtered_entries


def resolve_buy_orders_with_diagnostics(
    *,
    watchlist: list[Any],
    portfolio_snapshot: dict[str, Any],
    trade_date: str,
    execution_context: dict[str, Any],
    build_reentry_filter_entry_fn: Callable[..., dict[str, Any] | None],
    resolve_continuation_execution_overrides_fn: Callable[..., dict[str, Any]],
    calculate_position_fn: Callable[..., Any],
    enforce_daily_trade_limit_fn: Callable[[list[Any], float], list[Any]],
    build_filter_summary_fn: Callable[[list[dict[str, Any]]], dict[str, Any]],
) -> tuple[list[Any], dict[str, Any]]:
    cash = float(execution_context["cash"])
    nav = float(execution_context["nav"])
    if cash <= 0:
        return [], build_no_cash_buy_order_summary(
            watchlist=watchlist,
            build_filter_summary_fn=build_filter_summary_fn,
        )

    candidate_plans, filtered_entries = collect_buy_order_candidates(
        watchlist=watchlist,
        portfolio_snapshot=portfolio_snapshot,
        trade_date=trade_date,
        cash=cash,
        nav=nav,
        per_name_cash=float(execution_context["per_name_cash"]),
        candidate_by_ticker=execution_context["candidate_by_ticker"],
        price_map=execution_context["price_map"],
        blocked_buy_tickers=execution_context["blocked_buy_tickers"],
        selection_targets=execution_context["selection_targets"],
        build_reentry_filter_entry_fn=build_reentry_filter_entry_fn,
        resolve_continuation_execution_overrides_fn=resolve_continuation_execution_overrides_fn,
        calculate_position_fn=calculate_position_fn,
    )
    buy_orders = enforce_daily_trade_limit_fn(candidate_plans, nav)
    summary = build_buy_order_diagnostics_summary(
        buy_orders=buy_orders,
        candidate_plans=candidate_plans,
        filtered_entries=filtered_entries,
        build_filter_summary_fn=build_filter_summary_fn,
    )
    return buy_orders, summary


def build_buy_order_diagnostics_summary(
    *,
    buy_orders: list[Any],
    candidate_plans: list[Any],
    filtered_entries: list[dict[str, Any]],
    build_filter_summary_fn: Callable[[list[dict[str, Any]]], dict[str, Any]],
) -> dict[str, Any]:
    selected_tickers = {plan.ticker for plan in buy_orders}
    for plan in candidate_plans:
        if plan.ticker in selected_tickers:
            continue
        filtered_entries.append(
            {
                "ticker": plan.ticker,
                "reason": "filtered_by_daily_trade_limit",
                "score_final": round(plan.score_final, 4),
                "constraint_binding": plan.constraint_binding,
                "amount": round(plan.amount, 4),
                "execution_ratio": plan.execution_ratio,
                "quality_score": round(plan.quality_score, 4),
            }
        )

    summary = build_filter_summary_fn(filtered_entries)
    summary["selected_tickers"] = [plan.ticker for plan in buy_orders]
    return summary


def build_buy_orders_with_diagnostics(
    *,
    watchlist: list[Any],
    portfolio_snapshot: dict[str, Any],
    trade_date: str,
    candidate_by_ticker: dict[str, Any] | None,
    price_map: dict[str, float] | None,
    blocked_buy_tickers: dict[str, dict[str, Any]] | None,
    selection_targets: dict[str, Any] | None,
    normalize_blocked_buy_tickers_fn: Callable[[dict[str, dict[str, Any]] | None], dict[str, dict[str, Any]]],
    build_filter_summary_fn: Callable[[list[dict[str, Any]]], dict[str, Any]],
    build_reentry_filter_entry_fn: Callable[..., dict[str, Any] | None],
    resolve_continuation_execution_overrides_fn: Callable[..., dict[str, Any]],
    calculate_position_fn: Callable[..., Any],
    enforce_daily_trade_limit_fn: Callable[[list[Any], float], list[Any]],
) -> tuple[list[Any], dict[str, Any]]:
    blocked_buy_tickers = normalize_blocked_buy_tickers_fn(blocked_buy_tickers)
    if not watchlist:
        return [], build_filter_summary_fn([])

    execution_context = prepare_buy_order_execution_context(
        watchlist=watchlist,
        portfolio_snapshot=portfolio_snapshot,
        candidate_by_ticker=candidate_by_ticker,
        price_map=price_map,
        blocked_buy_tickers=blocked_buy_tickers,
        selection_targets=selection_targets,
    )
    return resolve_buy_orders_with_diagnostics(
        watchlist=watchlist,
        portfolio_snapshot=portfolio_snapshot,
        trade_date=trade_date,
        execution_context=execution_context,
        build_reentry_filter_entry_fn=build_reentry_filter_entry_fn,
        resolve_continuation_execution_overrides_fn=resolve_continuation_execution_overrides_fn,
        calculate_position_fn=calculate_position_fn,
        enforce_daily_trade_limit_fn=enforce_daily_trade_limit_fn,
        build_filter_summary_fn=build_filter_summary_fn,
    )
