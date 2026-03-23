from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from src.execution.daily_pipeline import build_buy_orders_with_diagnostics, build_watchlist_price_map
from src.execution.models import ExecutionPlan, LayerCResult
from src.screening.candidate_pool import build_candidate_pool


def _normalize_trade_date(value: str) -> str:
    text = str(value).strip()
    return text.replace("-", "")


def _load_daily_event(path: Path, trade_date: str) -> dict[str, Any]:
    normalized_trade_date = _normalize_trade_date(trade_date)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if _normalize_trade_date(str(payload.get("trade_date") or payload.get("date") or "")) != normalized_trade_date:
            continue
        current_plan = payload.get("current_plan")
        if isinstance(current_plan, dict):
            return payload
    raise ValueError(f"未在 {path} 中找到 trade_date={trade_date} 的 current_plan")


def _parse_symbols(symbols_arg: str | None) -> list[str] | None:
    if not symbols_arg:
        return None
    values = [item.strip() for item in symbols_arg.split(",") if item.strip()]
    return values or None


def _parse_price_overrides(price_overrides_arg: str | None) -> dict[str, float]:
    if not price_overrides_arg:
        return {}
    overrides: dict[str, float] = {}
    for raw_item in price_overrides_arg.split(","):
        item = raw_item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"无效的价格覆盖项: {item}，应为 ticker=price")
        ticker, raw_price = item.split("=", 1)
        normalized_ticker = ticker.strip()
        if not normalized_ticker:
            raise ValueError(f"无效的价格覆盖项: {item}，ticker 不能为空")
        try:
            price = float(raw_price.strip())
        except ValueError as exc:
            raise ValueError(f"无效的价格覆盖项: {item}，price 必须是数字") from exc
        if price <= 0:
            raise ValueError(f"无效的价格覆盖项: {item}，price 必须大于 0")
        overrides[normalized_ticker] = price
    return overrides


def _candidate_map(trade_date: str, tickers: list[str]) -> tuple[dict[str, Any], list[str]]:
    candidate_by_ticker = {candidate.ticker: candidate for candidate in build_candidate_pool(trade_date)}
    matched = {ticker: candidate_by_ticker[ticker] for ticker in tickers if ticker in candidate_by_ticker}
    missing = [ticker for ticker in tickers if ticker not in matched]
    return matched, missing


def _extract_original_buy_order_map(plan: ExecutionPlan) -> dict[str, dict[str, Any]]:
    return {
        str(order.ticker): {
            "included_in_buy_orders": True,
            "shares": int(order.shares),
            "amount": round(float(order.amount), 4),
            "constraint_binding": order.constraint_binding,
            "execution_ratio": round(float(order.execution_ratio), 4),
            "quality_score": round(float(order.quality_score), 4),
        }
        for order in plan.buy_orders
    }


def _extract_original_filtered_map(plan: ExecutionPlan) -> dict[str, dict[str, Any]]:
    filters = (((plan.risk_metrics or {}).get("funnel_diagnostics") or {}).get("filters") or {}).get("buy_orders") or {}
    return {
        str(entry.get("ticker")): dict(entry)
        for entry in list(filters.get("tickers") or [])
        if isinstance(entry, dict) and entry.get("ticker")
    }


def _price_from_order_like(payload: dict[str, Any]) -> float | None:
    amount = payload.get("amount")
    shares = payload.get("shares")
    if amount in (None, 0) or shares in (None, 0):
        return None
    try:
        parsed_amount = float(amount)
        parsed_shares = float(shares)
    except (TypeError, ValueError):
        return None
    if parsed_amount <= 0 or parsed_shares <= 0:
        return None
    return parsed_amount / parsed_shares


def _resolve_probe_price_map(
    event_payload: dict[str, Any],
    plan: ExecutionPlan,
    normalized_trade_date: str,
    probe_tickers: list[str],
    explicit_price_overrides: dict[str, float],
) -> dict[str, float]:
    resolved_price_map = {ticker: float(price) for ticker, price in explicit_price_overrides.items() if ticker in probe_tickers}

    top_level_current_prices = event_payload.get("current_prices")
    if isinstance(top_level_current_prices, dict):
        for ticker in probe_tickers:
            price = top_level_current_prices.get(ticker)
            if price is None:
                continue
            try:
                parsed_price = float(price)
            except (TypeError, ValueError):
                continue
            if parsed_price > 0:
                resolved_price_map.setdefault(ticker, parsed_price)

    prepared_plan = event_payload.get("prepared_plan")
    if isinstance(prepared_plan, dict):
        prepared_current_prices = prepared_plan.get("current_prices")
        if isinstance(prepared_current_prices, dict):
            for ticker in probe_tickers:
                price = prepared_current_prices.get(ticker)
                if price is None:
                    continue
                try:
                    parsed_price = float(price)
                except (TypeError, ValueError):
                    continue
                if parsed_price > 0:
                    resolved_price_map.setdefault(ticker, parsed_price)

    lookup_price_map = build_watchlist_price_map(normalized_trade_date, probe_tickers)
    for ticker in probe_tickers:
        price = lookup_price_map.get(ticker)
        if price is None:
            continue
        try:
            parsed_price = float(price)
        except (TypeError, ValueError):
            continue
        if parsed_price > 0:
            resolved_price_map.setdefault(ticker, parsed_price)

    original_order_map = {str(order.ticker): order for order in plan.buy_orders}
    for ticker in probe_tickers:
        if ticker in resolved_price_map:
            continue
        order = original_order_map.get(ticker)
        if order is None:
            continue
        implied_price = _price_from_order_like({"amount": order.amount, "shares": order.shares})
        if implied_price is not None:
            resolved_price_map[ticker] = implied_price

    missing_prices = [ticker for ticker in probe_tickers if ticker not in resolved_price_map]
    if missing_prices:
        raise ValueError(
            "以下 ticker 缺少可信价格，probe 已拒绝继续运行: "
            + ", ".join(missing_prices)
            + "。请通过 --price-overrides 传入显式价格，例如 600988=19.87"
        )

    return resolved_price_map


@contextmanager
def _temporary_env(overrides: dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def probe_execution_buy_orders(
    daily_events_path: Path,
    trade_date: str,
    symbols: list[str] | None = None,
    threshold_overrides: dict[str, str] | None = None,
    price_overrides: dict[str, float] | None = None,
) -> dict[str, Any]:
    event_payload = _load_daily_event(daily_events_path, trade_date)
    current_plan = ExecutionPlan.model_validate(event_payload["current_plan"])
    watchlist = list(current_plan.watchlist)
    if symbols is not None:
        requested = set(symbols)
        watchlist = [item for item in watchlist if item.ticker in requested]
        missing = sorted(requested - {item.ticker for item in watchlist})
        if missing:
            raise ValueError(f"trade_date={trade_date} 的 watchlist 中未找到: {', '.join(missing)}")

    probe_tickers = [item.ticker for item in watchlist]
    normalized_trade_date = _normalize_trade_date(trade_date)
    candidate_by_ticker, missing_candidate_context = _candidate_map(normalized_trade_date, probe_tickers)
    price_map = _resolve_probe_price_map(
        event_payload,
        current_plan,
        normalized_trade_date,
        probe_tickers,
        price_overrides or {},
    )
    blocked_buy_tickers = (((current_plan.risk_metrics or {}).get("funnel_diagnostics") or {}).get("blocked_buy_tickers") or {})

    threshold_overrides = {key: value for key, value in (threshold_overrides or {}).items() if value is not None}
    with _temporary_env(threshold_overrides):
        recomputed_buy_orders, recomputed_diagnostics = build_buy_orders_with_diagnostics(
            watchlist,
            current_plan.portfolio_snapshot,
            trade_date=normalized_trade_date,
            candidate_by_ticker=candidate_by_ticker,
            price_map=price_map,
            blocked_buy_tickers=blocked_buy_tickers,
        )

    recomputed_buy_order_map = {
        str(order.ticker): order
        for order in recomputed_buy_orders
    }
    recomputed_filtered_map = {
        str(entry.get("ticker")): dict(entry)
        for entry in list(recomputed_diagnostics.get("tickers") or [])
        if isinstance(entry, dict) and entry.get("ticker")
    }
    original_buy_order_map = _extract_original_buy_order_map(current_plan)
    original_filtered_map = _extract_original_filtered_map(current_plan)

    probes: list[dict[str, Any]] = []
    for item in watchlist:
        recomputed_order = recomputed_buy_order_map.get(item.ticker)
        recomputed_filter = recomputed_filtered_map.get(item.ticker, {})
        original_order = original_buy_order_map.get(item.ticker)
        original_filter = original_filtered_map.get(item.ticker, {})
        candidate = candidate_by_ticker.get(item.ticker)
        probes.append(
            {
                "ticker": item.ticker,
                "score_b": round(float(item.score_b), 4),
                "score_c": round(float(item.score_c), 4),
                "score_final": round(float(item.score_final), 4),
                "quality_score": round(float(item.quality_score), 4),
                "decision": item.decision,
                "bc_conflict": item.bc_conflict,
                "current_price": round(float(price_map[item.ticker]), 4),
                "avg_volume_20d": round(float(candidate.avg_volume_20d), 4) if candidate is not None else None,
                "original": original_order
                or {
                    "included_in_buy_orders": False,
                    "reason": original_filter.get("reason"),
                    "constraint_binding": original_filter.get("constraint_binding"),
                    "execution_ratio": original_filter.get("execution_ratio"),
                    "amount": original_filter.get("amount"),
                    "quality_score": original_filter.get("quality_score"),
                },
                "probed": {
                    "included_in_buy_orders": recomputed_order is not None,
                    "reason": None if recomputed_order is not None else recomputed_filter.get("reason"),
                    "constraint_binding": recomputed_order.constraint_binding if recomputed_order is not None else recomputed_filter.get("constraint_binding"),
                    "execution_ratio": round(float(recomputed_order.execution_ratio), 4) if recomputed_order is not None else recomputed_filter.get("execution_ratio"),
                    "shares": int(recomputed_order.shares) if recomputed_order is not None else 0,
                    "amount": round(float(recomputed_order.amount), 4) if recomputed_order is not None else recomputed_filter.get("amount"),
                    "quality_score": round(float(recomputed_order.quality_score), 4) if recomputed_order is not None else recomputed_filter.get("quality_score"),
                },
            }
        )

    return {
        "daily_events_path": str(daily_events_path),
        "trade_date": normalized_trade_date,
        "probe_symbol_count": len(probe_tickers),
        "threshold_overrides": threshold_overrides,
        "price_overrides": {ticker: round(float(price), 4) for ticker, price in (price_overrides or {}).items()},
        "portfolio_snapshot": current_plan.portfolio_snapshot,
        "missing_candidate_context": missing_candidate_context,
        "price_map": {ticker: round(float(price), 4) for ticker, price in price_map.items()},
        "original_buy_order_selected_tickers": [str(order.ticker) for order in current_plan.buy_orders],
        "recomputed_buy_order_selected_tickers": [str(order.ticker) for order in recomputed_buy_orders],
        "recomputed_buy_order_reason_counts": dict(recomputed_diagnostics.get("reason_counts") or {}),
        "probes": probes,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe execution-layer buy-order decisions for fixed watchlist samples from daily_events.jsonl")
    parser.add_argument("--daily-events", required=True, help="Path to a daily_events.jsonl artifact")
    parser.add_argument("--trade-date", required=True, help="Trade date in YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--symbols", default=None, help="Optional comma-separated watchlist tickers to probe; default is all watchlist names")
    parser.add_argument("--watchlist-min-score", default=None, help="Optional override for PIPELINE_WATCHLIST_MIN_SCORE")
    parser.add_argument("--standard-execution-score", default=None, help="Optional override for PIPELINE_STANDARD_EXECUTION_SCORE")
    parser.add_argument("--full-execution-score", default=None, help="Optional override for PIPELINE_FULL_EXECUTION_SCORE")
    parser.add_argument("--watchlist-edge-execution-ratio", default=None, help="Optional override for PIPELINE_WATCHLIST_EDGE_EXECUTION_RATIO")
    parser.add_argument("--price-overrides", default=None, help="Optional comma-separated ticker=price overrides for missing historical prices")
    parser.add_argument("--output", default=None, help="Optional JSON output path")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    threshold_overrides = {
        "PIPELINE_WATCHLIST_MIN_SCORE": args.watchlist_min_score,
        "PIPELINE_STANDARD_EXECUTION_SCORE": args.standard_execution_score,
        "PIPELINE_FULL_EXECUTION_SCORE": args.full_execution_score,
        "PIPELINE_WATCHLIST_EDGE_EXECUTION_RATIO": args.watchlist_edge_execution_ratio,
    }
    report = probe_execution_buy_orders(
        Path(args.daily_events).resolve(),
        trade_date=args.trade_date,
        symbols=_parse_symbols(args.symbols),
        threshold_overrides=threshold_overrides,
        price_overrides=_parse_price_overrides(args.price_overrides),
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())