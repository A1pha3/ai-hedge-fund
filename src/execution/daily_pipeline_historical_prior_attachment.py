"""Historical prior attachment helpers for daily pipeline.

Handles enriching candidate entries and watchlist items with
historical prior data, plus relief refresh logic.
"""

from __future__ import annotations

from typing import Any

from src.execution.models import LayerCResult


def _refresh_attached_entry_relief(entry: dict[str, Any]) -> dict[str, Any]:
    updated_entry = dict(entry)
    candidate_pool_lane = str(updated_entry.get("candidate_pool_lane") or "")
    historical_prior = dict(updated_entry.get("historical_prior") or {})
    current_relief = dict(updated_entry.get("short_trade_catalyst_relief") or {})
    if candidate_pool_lane != "post_gate_liquidity_competition":
        return updated_entry
    if str(current_relief.get("reason") or "") != "upstream_shadow_catalyst_relief":
        return updated_entry
    next_close_positive_rate = historical_prior.get("next_close_positive_rate")
    if next_close_positive_rate is not None and float(next_close_positive_rate) < 0.5:
        updated_entry.pop("short_trade_catalyst_relief", None)
    return updated_entry


def attach_historical_prior_to_entries(
    entries: list[dict[str, Any]],
    *,
    prior_by_ticker: dict[str, dict[str, Any]],
    resolve_historical_prior_for_ticker_fn: Any,
) -> list[dict[str, Any]]:
    attached_entries: list[dict[str, Any]] = []
    for entry in entries:
        updated_entry = dict(entry)
        ticker = str(updated_entry.get("ticker") or "")
        historical_prior = resolve_historical_prior_for_ticker_fn(
            ticker=ticker,
            historical_prior=dict(updated_entry.get("historical_prior") or {}),
            prior_by_ticker=prior_by_ticker,
        )
        if historical_prior:
            updated_entry["historical_prior"] = historical_prior
        updated_entry = _refresh_attached_entry_relief(updated_entry)
        attached_entries.append(updated_entry)
    return attached_entries


def attach_historical_prior_to_watchlist(
    watchlist: list[LayerCResult],
    *,
    prior_by_ticker: dict[str, dict[str, Any]],
) -> list[LayerCResult]:
    attached_watchlist: list[LayerCResult] = []
    for item in list(watchlist or []):
        historical_prior = dict(prior_by_ticker.get(str(item.ticker or "")) or {})
        if historical_prior:
            attached_watchlist.append(item.model_copy(update={"historical_prior": historical_prior}))
        else:
            attached_watchlist.append(item)
    return attached_watchlist
