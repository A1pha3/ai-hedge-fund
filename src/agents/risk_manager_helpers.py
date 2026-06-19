import logging

import pandas as pd

logger = logging.getLogger(__name__)


def _fallback_volatility_metrics(data_points: int = 0) -> dict[str, float | int]:
    return {
        "daily_volatility": 0.05,
        "annualized_volatility": 0.05 * (252**0.5),
        "volatility_percentile": 100,
        "data_points": data_points,
    }


def _collect_market_data(
    *,
    all_tickers: set[str],
    data: dict,
    api_key: str,
    agent_id: str,
    progress_callback,
    get_prices_callable,
    prices_to_df_callable,
    calculate_volatility_metrics_callable,
) -> tuple[dict[str, float], dict[str, dict], dict[str, pd.Series]]:
    current_prices: dict[str, float] = {}
    volatility_data: dict[str, dict] = {}
    returns_by_ticker: dict[str, pd.Series] = {}

    for ticker in all_tickers:
        progress_callback(agent_id, ticker, "Fetching price data and calculating volatility")
        prices = get_prices_callable(
            ticker=ticker,
            start_date=data["start_date"],
            end_date=data["end_date"],
            api_key=api_key,
        )

        if not prices:
            progress_callback(agent_id, ticker, "Warning: No price data found")
            volatility_data[ticker] = _fallback_volatility_metrics()
            continue

        prices_df = prices_to_df_callable(prices)
        if not prices_df.empty and len(prices_df) > 1:
            raw_current_price = prices_df["close"].iloc[-1]
            # Guard against NaN/None in the most recent close. Treating NaN as
            # a usable price silently propagates NaN through downstream
            # max_shares and remaining_position_limit calculations, leading
            # to undefined division behavior in the portfolio manager.
            if raw_current_price is None or (
                isinstance(raw_current_price, float) and raw_current_price != raw_current_price
            ):
                progress_callback(agent_id, ticker, "Warning: NaN price in last bar")
                current_prices[ticker] = 0
                volatility_data[ticker] = _fallback_volatility_metrics(len(prices_df))
                continue
            current_price = float(raw_current_price)
            current_prices[ticker] = current_price
            volatility_metrics = calculate_volatility_metrics_callable(prices_df)
            volatility_data[ticker] = volatility_metrics

            daily_returns = prices_df["close"].pct_change().dropna()
            if len(daily_returns) > 0:
                returns_by_ticker[ticker] = daily_returns

            progress_callback(agent_id, ticker, f"Price: {current_price:.2f}, Ann. Vol: {volatility_metrics['annualized_volatility']:.1%}")
        else:
            progress_callback(agent_id, ticker, "Warning: Insufficient price data")
            current_prices[ticker] = 0
            volatility_data[ticker] = _fallback_volatility_metrics(len(prices_df) if not prices_df.empty else 0)

    return current_prices, volatility_data, returns_by_ticker


def _build_correlation_matrix(returns_by_ticker: dict[str, pd.Series]) -> pd.DataFrame | None:
    if len(returns_by_ticker) < 2:
        return None
    try:
        returns_df = pd.DataFrame(returns_by_ticker).dropna(how="any")
        if returns_df.shape[1] >= 2 and returns_df.shape[0] >= 5:
            return returns_df.corr()
    except Exception:
        # Traceability: returning None makes the risk manager proceed without
        # correlation/diversification checks, understating portfolio risk. Log so
        # a real pandas/shape failure is observable rather than silent.
        logger.debug("correlation matrix build failed; returning None fallback", exc_info=True)
        return None
    return None


def _calculate_total_portfolio_value(portfolio: dict, current_prices: dict[str, float]) -> float:
    total_portfolio_value = portfolio.get("cash", 0.0)
    for ticker, position in portfolio.get("positions", {}).items():
        price = current_prices.get(ticker, 0.0)
        total_portfolio_value += position.get("long", 0) * price
        total_portfolio_value -= position.get("short", 0) * price
    # Margin used is cash locked as collateral for open short positions.
    # It belongs to the portfolio but is excluded from the cash balance,
    # so it must be added back to get the true total value.
    total_portfolio_value += float(portfolio.get("margin_used", 0.0))
    return total_portfolio_value


def _build_missing_price_analysis() -> dict:
    return {
        "remaining_position_limit": 0.0,
        "current_price": 0.0,
        "reasoning": {"error": "Missing price data for risk calculation"},
    }


def _build_correlation_metrics(
    *,
    ticker: str,
    correlation_matrix: pd.DataFrame | None,
    active_positions: set[str],
    calculate_correlation_multiplier_callable,
) -> tuple[dict, float]:
    corr_metrics = {
        "avg_correlation_with_active": None,
        "max_correlation_with_active": None,
        "top_correlated_tickers": [],
    }
    corr_multiplier = 1.0

    if correlation_matrix is None or ticker not in correlation_matrix.columns:
        return corr_metrics, corr_multiplier

    comparable = [t for t in active_positions if t in correlation_matrix.columns and t != ticker]
    if not comparable:
        comparable = [t for t in correlation_matrix.columns if t != ticker]
    if not comparable:
        return corr_metrics, corr_multiplier

    series = correlation_matrix.loc[ticker, comparable].dropna()
    if len(series) == 0:
        return corr_metrics, corr_multiplier

    avg_corr = float(series.mean())
    max_corr = float(series.max())
    top_corr = series.sort_values(ascending=False).head(3)
    corr_metrics["avg_correlation_with_active"] = avg_corr
    corr_metrics["max_correlation_with_active"] = max_corr
    corr_metrics["top_correlated_tickers"] = [{"ticker": idx, "correlation": float(val)} for idx, val in top_corr.items()]
    corr_multiplier = calculate_correlation_multiplier_callable(avg_corr)
    return corr_metrics, corr_multiplier


def _build_risk_analysis_entry(
    *,
    portfolio: dict,
    ticker: str,
    current_prices: dict[str, float],
    volatility_data: dict[str, dict],
    correlation_matrix: pd.DataFrame | None,
    active_positions: set[str],
    total_portfolio_value: float,
    calculate_volatility_adjusted_limit_callable,
    calculate_correlation_multiplier_callable,
) -> tuple[dict, float]:
    current_price = current_prices[ticker]
    vol_data = volatility_data.get(ticker, {})
    position = portfolio.get("positions", {}).get(ticker, {})
    long_value = position.get("long", 0) * current_price
    short_value = position.get("short", 0) * current_price
    current_position_value = abs(long_value - short_value)
    vol_adjusted_limit_pct = calculate_volatility_adjusted_limit_callable(vol_data.get("annualized_volatility", 0.25))
    corr_metrics, corr_multiplier = _build_correlation_metrics(
        ticker=ticker,
        correlation_matrix=correlation_matrix,
        active_positions=active_positions,
        calculate_correlation_multiplier_callable=calculate_correlation_multiplier_callable,
    )
    combined_limit_pct = vol_adjusted_limit_pct * corr_multiplier
    position_limit = total_portfolio_value * combined_limit_pct
    remaining_position_limit = max(0.0, position_limit - current_position_value)
    # NOTE: do not clip by cash here. Cash/margin constraints are enforced
    # downstream in portfolio_manager._resolve_max_buy / _resolve_max_short.
    # Clipping here under-reports shorting capacity (which is bounded by margin,
    # not cash) and shrinks the headroom shown to the LLM.
    max_position_size = float(remaining_position_limit)

    return {
        "remaining_position_limit": max_position_size,
        "current_price": float(current_price),
        "volatility_metrics": {
            "daily_volatility": float(vol_data.get("daily_volatility", 0.05)),
            "annualized_volatility": float(vol_data.get("annualized_volatility", 0.25)),
            "volatility_percentile": float(vol_data.get("volatility_percentile", 100)),
            "data_points": int(vol_data.get("data_points", 0)),
        },
        "correlation_metrics": corr_metrics,
        "reasoning": {
            "portfolio_value": float(total_portfolio_value),
            "current_position_value": float(current_position_value),
            "base_position_limit_pct": float(vol_adjusted_limit_pct),
            "correlation_multiplier": float(corr_multiplier),
            "combined_position_limit_pct": float(combined_limit_pct),
            "position_limit": float(position_limit),
            "remaining_limit": float(remaining_position_limit),
            "available_cash": float(portfolio.get("cash", 0)),
            "risk_adjustment": f"Volatility x Correlation adjusted: {combined_limit_pct:.1%} (base {vol_adjusted_limit_pct:.1%})",
        },
    }, combined_limit_pct
