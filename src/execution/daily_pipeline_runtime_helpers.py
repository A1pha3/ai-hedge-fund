from __future__ import annotations

from typing import Any, Callable


def load_candidate_pool_bundle(
    trade_date: str,
    *,
    build_candidate_pool: Callable[[str], list[Any]],
    build_candidate_pool_with_shadow: Callable[[str], tuple[list[Any], list[Any], dict[str, Any]]],
    original_build_candidate_pool: object,
    original_build_candidate_pool_with_shadow: object,
) -> tuple[list[Any], list[Any], dict[str, Any]]:
    if build_candidate_pool is not original_build_candidate_pool and build_candidate_pool_with_shadow is original_build_candidate_pool_with_shadow:
        candidates = build_candidate_pool(trade_date)
        return candidates, [], {
            "pool_size": len(candidates),
            "selected_count": len(candidates),
            "overflow_count": 0,
            "selected_cutoff_avg_volume_20d": round(float(candidates[-1].avg_volume_20d), 4) if candidates else 0.0,
            "lane_counts": {},
            "selected_tickers": [],
            "tickers": [],
        }
    return build_candidate_pool_with_shadow(trade_date)


def default_exit_checker(
    portfolio_snapshot: dict[str, Any],
    trade_date: str,
    logic_scores: dict[str, float] | None = None,
    *,
    build_watchlist_price_map: Callable[[str, list[str]], dict[str, float]],
    check_exit_signal: Callable[..., Any],
    holding_state_cls: type,
) -> list[Any]:
    positions = portfolio_snapshot.get("positions", {})
    active_tickers = [ticker for ticker, position in positions.items() if float(position.get("long", 0.0)) > 0]
    if not active_tickers:
        return []

    price_map = build_watchlist_price_map(trade_date, active_tickers)
    exits: list[Any] = []
    for ticker in active_tickers:
        current_price = price_map.get(ticker)
        if current_price is None or current_price <= 0:
            continue
        position = positions.get(ticker, {})
        shares = int(position.get("long", 0))
        entry_price = float(position.get("long_cost_basis", 0.0))
        if shares <= 0 or entry_price <= 0:
            continue
        holding = holding_state_cls(
            ticker=ticker,
            entry_price=entry_price,
            entry_date=str(position.get("entry_date") or trade_date),
            shares=shares,
            cost_basis=entry_price * shares,
            industry_sw=str(position.get("industry_sw", "")),
            max_unrealized_pnl_pct=float(position.get("max_unrealized_pnl_pct", 0.0)),
            holding_days=int(position.get("holding_days", 0)),
            profit_take_stage=int(position.get("profit_take_stage", 0)),
            entry_score=float(position.get("entry_score", 0.0)),
            quality_score=float(position.get("quality_score", 0.5)),
            is_fundamental_driven=bool(position.get("is_fundamental_driven", False)),
        )
        signal = check_exit_signal(
            holding,
            current_price=float(current_price),
            trade_date=trade_date,
            logic_score=(logic_scores or {}).get(ticker),
        )
        if signal is not None:
            exits.append(signal)
    return exits


def build_filter_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    reason_counts: dict[str, int] = {}
    for entry in entries:
        reason = str(entry.get("reason") or "unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "filtered_count": len(entries),
        "reason_counts": reason_counts,
        "tickers": entries,
    }


def load_latest_historical_prior_by_ticker(*, reports_root, loader: Callable[[Any], dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    return loader(reports_root)


def historical_prior_value_is_missing(key: str, value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return True
        if key == "execution_quality_label" and normalized == "unknown":
            return True
    return False


def resolve_historical_prior_for_ticker(
    *,
    ticker: str,
    historical_prior: dict[str, Any] | None,
    prior_by_ticker: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    embedded_historical_prior = dict(historical_prior or {})
    latest_historical_prior = dict(prior_by_ticker.get(ticker) or {})
    if not embedded_historical_prior:
        return latest_historical_prior
    if not latest_historical_prior:
        return embedded_historical_prior

    resolved_historical_prior = dict(latest_historical_prior)
    for key, value in embedded_historical_prior.items():
        if historical_prior_value_is_missing(str(key), value):
            continue
        resolved_historical_prior[str(key)] = value
    return resolved_historical_prior
