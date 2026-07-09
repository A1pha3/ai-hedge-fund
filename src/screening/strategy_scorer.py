"""Layer B 四策略评分器。"""

from __future__ import annotations

import concurrent.futures
import logging
import math
import os
from collections import defaultdict
from datetime import datetime
from statistics import median
from time import perf_counter
from typing import Any

import pandas as pd

from src.screening.models import CandidateStock, StrategySignal
from src.screening.optional_feature_store import OptionalFeatureStore
from src.screening.scoring_feature_store import ScoringFeatureStore
from src.screening.strategy_scorer_fundamental import (
    score_fundamental_strategy,
    score_fundamental_strategy_from_metrics,
)
from src.screening.strategy_scorer_mean_reversion import (
    score_mean_reversion_strategy,
)
from src.screening.strategy_scorer_trend import (
    score_trend_strategy,
)
from src.screening.strategy_scorer_utils import (
    aggregate_sub_factors,
    derive_completeness,
)
from src.tools import akshare_api as _akshare_api
from src.tools.akshare_api import (
    get_lhb_detail,
    get_lhb_institutional_stats,
)
from src.tools.tushare_api import (
    get_all_stock_basic,
    get_daily_basic_batch,
    get_sw_industry_classification,
)

logger = logging.getLogger(__name__)

# Provider aliases retained for tests that assert score-time helpers never call them.
get_intraday_bars = _akshare_api.get_intraday_bars
get_intraday_ticks = _akshare_api.get_intraday_ticks
get_money_flow = _akshare_api.get_money_flow

# Re-export for backward compatibility
__all__ = [
    "aggregate_sub_factors",
    "derive_completeness",
    "score_trend_strategy",
    "score_mean_reversion_strategy",
    "score_fundamental_strategy",
]

# Light stage weights: 全 universe 因子回测 (2026-06-25, n=8136) 证明 MR 是正向有效因子
# C226 revert: 全 universe 诊断 (C225 n=8901) 证实 MR 全 4 sub-factor 与 T+1 反向
# (sep<0, IC=-0.128); MR-heavy (0.65) 在更长样本下跑输 trend-heavy (daily excess -0.28%).
# mean-reversion bet 在 T+1 horizon 失败 (短期 momentum 主导). 回滚到 trend:0.65/MR:0.35
# (validated by _backtest_light_stage_universe: OLD Top-50 T+1 跑赢 NEW 67% 天).
LIGHT_STRATEGY_WEIGHTS = {
    "trend": 0.65,
    "mean_reversion": 0.35,
}
_DEFAULT_CANDIDATE_POOL_SIZE = int(os.getenv("MAX_CANDIDATE_POOL_SIZE", "300"))
TECHNICAL_SCORE_MAX_CANDIDATES = int(
    os.getenv(
        "SCORE_BATCH_TECHNICAL_MAX_CANDIDATES",
        str(max(160, math.ceil(_DEFAULT_CANDIDATE_POOL_SIZE * 0.75))),
    )
)
FUNDAMENTAL_SCORE_MAX_CANDIDATES = int(
    os.getenv(
        "SCORE_BATCH_FUNDAMENTAL_MAX_CANDIDATES",
        str(max(100, math.ceil(_DEFAULT_CANDIDATE_POOL_SIZE * 0.47))),
    )
)
EVENT_SENTIMENT_MAX_CANDIDATES = int(
    os.getenv(
        "SCORE_BATCH_EVENT_SENTIMENT_MAX_CANDIDATES",
        str(max(40, math.ceil(_DEFAULT_CANDIDATE_POOL_SIZE * 0.20))),
    )
)
INTRADAY_SCORE_MAX_CANDIDATES = int(
    os.getenv(
        "SCORE_BATCH_INTRADAY_MAX_CANDIDATES",
        "12",
    )
)
HEAVY_SCORE_MIN_PROVISIONAL_SCORE = float(os.getenv("SCORE_BATCH_MIN_PROVISIONAL_SCORE", "0.05"))
HEAVY_SCORE_MIN_TREND_CONFIDENCE = float(os.getenv("SCORE_BATCH_MIN_TREND_CONFIDENCE", "35"))
_EVENT_DECAY_LAMBDA = float(os.getenv("EVENT_DECAY_LAMBDA", "0.35"))
TECHNICAL_STAGE_LIQUIDITY_RANK_BUCKET = float(os.getenv("CANDIDATE_POOL_BTST_LIQUIDITY_RANK_BUCKET", "2500"))
SCORE_BATCH_CONCURRENCY = int(os.getenv("SCORE_BATCH_CONCURRENCY", "4"))

# R20.2: Event sentiment helpers extracted for readability
from src.screening.strategy_scorer_event_sentiment_helpers import (  # noqa: E402
    _empty_signal,
    _load_price_frame,
    score_event_sentiment_strategy,
    score_event_sentiment_strategy_from_inputs,
)


def _build_symbol_to_industry_map(stock_basic: pd.DataFrame, sw_map: dict[str, str]) -> dict[str, str]:
    symbol_to_industry: dict[str, str] = {}
    for _, row in stock_basic.iterrows():
        ts_code = str(row["ts_code"])
        symbol = str(row["symbol"])
        symbol_to_industry[symbol] = sw_map.get(ts_code, str(row.get("industry", "")))
    return symbol_to_industry


def _group_industry_pe_values(daily_df: pd.DataFrame, symbol_to_industry: dict[str, str]) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for _, row in daily_df.iterrows():
        pe_ttm = row.get("pe_ttm")
        if pd.isna(pe_ttm) or pe_ttm is None or float(pe_ttm) <= 0:
            continue
        symbol = str(row["ts_code"]).split(".")[0]
        industry = symbol_to_industry.get(symbol, "")
        if industry:
            grouped[industry].append(float(pe_ttm))
    return grouped


def _build_industry_pe_medians(trade_date: str, feature_store: ScoringFeatureStore) -> dict[str, float]:
    return feature_store.load_industry_pe_medians(trade_date)


def score_candidate(
    candidate: CandidateStock,
    trade_date: str,
    industry_pe_medians: dict[str, float] | None = None,
    prices_df: pd.DataFrame | None = None,
    feature_store: ScoringFeatureStore | None = None,
) -> dict[str, StrategySignal]:
    store = feature_store or ScoringFeatureStore()
    prices_df = prices_df if prices_df is not None else store.load_price_frame(candidate.ticker, trade_date)
    industry_pe_medians = industry_pe_medians if industry_pe_medians is not None else store.load_industry_pe_medians(trade_date)
    metrics_list = store.load_financial_metrics(candidate.ticker, trade_date)
    news_items, trades = store.load_event_inputs(candidate.ticker, trade_date)
    return {
        "trend": score_trend_strategy(prices_df, ticker=candidate.ticker),
        "mean_reversion": score_mean_reversion_strategy(prices_df),
        "fundamental": score_fundamental_strategy_from_metrics(metrics_list, candidate.industry_sw, industry_pe_medians),
        "event_sentiment": score_event_sentiment_strategy_from_inputs(news_items, trades, trade_date),
    }


def _compute_light_signals(
    candidate: CandidateStock,
    trade_date: str,
    feature_store: ScoringFeatureStore,
) -> tuple[dict[str, StrategySignal], pd.DataFrame]:
    prices_df = feature_store.load_price_frame(candidate.ticker, trade_date)
    return _build_light_signal_map(prices_df, ticker=candidate.ticker), prices_df


def _build_light_signal_map(prices_df: pd.DataFrame, *, ticker: str | None = None) -> dict[str, StrategySignal]:
    return {
        "trend": score_trend_strategy(prices_df, ticker=ticker),
        "mean_reversion": score_mean_reversion_strategy(prices_df),
        "fundamental": _empty_signal(),
        "event_sentiment": _empty_signal(),
    }


def _provisional_score(signals: dict[str, StrategySignal]) -> float:
    score = 0.0
    total_weight = 0.0
    for name, weight in LIGHT_STRATEGY_WEIGHTS.items():
        signal = signals.get(name)
        if signal is None or signal.completeness <= 0:
            continue
        total_weight += weight
        score += weight * signal.direction * (signal.confidence / 100.0) * signal.completeness
    if total_weight <= 0:
        return 0.0
    return score / total_weight


def _rank_candidates_for_technical_stage(candidates: list[CandidateStock]) -> list[CandidateStock]:
    return sorted(
        candidates,
        key=_technical_stage_ranking_key,
        reverse=True,
    )


def _technical_stage_ranking_key(candidate: CandidateStock) -> tuple[int, float, float, str]:
    liquidity_band = int(float(candidate.avg_volume_20d) / max(TECHNICAL_STAGE_LIQUIDITY_RANK_BUCKET, 1.0))
    return (
        liquidity_band,
        -float(candidate.market_cap),
        float(candidate.avg_volume_20d),
        str(candidate.ticker),
    )


def _initialize_score_batch_results(candidates: list[CandidateStock]) -> dict[str, dict[str, StrategySignal]]:
    return {
        candidate.ticker: {
            "trend": _empty_signal(),
            "mean_reversion": _empty_signal(),
            "fundamental": _empty_signal(),
            "event_sentiment": _empty_signal(),
        }
        for candidate in candidates
    }


def _build_provisional_ranking(
    candidates: list[CandidateStock],
    trade_date: str,
    results: dict[str, dict[str, StrategySignal]],
    feature_store: ScoringFeatureStore,
) -> list[tuple[float, CandidateStock]]:
    provisional_ranking: list[tuple[float, CandidateStock]] = []
    technical_candidates = _rank_candidates_for_technical_stage(candidates)[:TECHNICAL_SCORE_MAX_CANDIDATES]
    price_frames_by_ticker: dict[str, pd.DataFrame] = {}

    # Parallel IO: load price frames and compute light signals concurrently
    max_workers = min(SCORE_BATCH_CONCURRENCY, len(technical_candidates)) if technical_candidates else 1
    if max_workers <= 1:
        for candidate in technical_candidates:
            light_signals, price_frame = _compute_light_signals(candidate, trade_date, feature_store)
            results[candidate.ticker] = light_signals
            if price_frame is not None:
                price_frames_by_ticker[candidate.ticker] = price_frame
            provisional_ranking.append((_provisional_score(light_signals), candidate))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_candidate = {
                executor.submit(_compute_light_signals, candidate, trade_date, feature_store): candidate
                for candidate in technical_candidates
            }
            for future in concurrent.futures.as_completed(future_to_candidate):
                candidate = future_to_candidate[future]
                try:
                    light_signals, price_frame = future.result()
                except Exception:
                    logger.warning("Light-signal computation failed for %s", candidate.ticker, exc_info=True)
                    light_signals, price_frame = _build_light_signal_map(pd.DataFrame(), ticker=candidate.ticker), None
                results[candidate.ticker] = light_signals
                if price_frame is not None:
                    price_frames_by_ticker[candidate.ticker] = price_frame
                provisional_ranking.append((_provisional_score(light_signals), candidate))

    _populate_sector_diffusion_metrics(results, technical_candidates, price_frames_by_ticker)
    return _append_unranked_candidates_to_provisional_ranking(provisional_ranking, candidates)


def _append_unranked_candidates_to_provisional_ranking(provisional_ranking: list[tuple[float, CandidateStock]], candidates: list[CandidateStock]) -> list[tuple[float, CandidateStock]]:
    ranked_tickers = {ranked_candidate.ticker for _, ranked_candidate in provisional_ranking}
    for candidate in candidates:
        if candidate.ticker in ranked_tickers:
            continue
        provisional_ranking.append((0.0, candidate))
    return provisional_ranking


def _populate_sector_diffusion_metrics(
    results: dict[str, dict[str, StrategySignal]],
    candidates: list[CandidateStock],
    price_frames_by_ticker: dict[str, pd.DataFrame],
) -> None:
    sector_metric_map = _build_sector_diffusion_metric_map(candidates, price_frames_by_ticker)
    for ticker, metrics in sector_metric_map.items():
        trend_signal = results.get(ticker, {}).get("trend")
        if not _trend_signal_has_momentum_payload(trend_signal):
            continue
        _merge_metrics_into_trend_momentum(trend_signal, metrics)


def _build_sector_diffusion_metric_map(
    candidates: list[CandidateStock],
    price_frames_by_ticker: dict[str, pd.DataFrame],
) -> dict[str, dict[str, float]]:
    industry_returns: dict[str, list[tuple[str, float]]] = defaultdict(list)
    industry_amounts: dict[str, float] = defaultdict(float)
    total_amount = 0.0
    for candidate in candidates:
        industry = str(candidate.industry_sw or "").strip()
        if not industry:
            continue
        price_frame = price_frames_by_ticker.get(candidate.ticker)
        ret_1d = _compute_price_frame_close_return(price_frame, sessions=1)
        if ret_1d is None:
            continue
        industry_returns[industry].append((candidate.ticker, ret_1d))
        latest_amount = _compute_price_frame_latest_amount(price_frame)
        if latest_amount is not None and latest_amount > 0.0:
            industry_amounts[industry] += latest_amount
            total_amount += latest_amount

    sector_metric_map: dict[str, dict[str, float]] = {}
    for industry, members in industry_returns.items():
        if not members:
            continue
        leader_ticker = max(members, key=lambda item: item[1])[0]
        sector_breadth_3 = sum(1 for _, ret_1d in members if ret_1d > 0.03) / len(members)
        nonleaders = [(ticker, ret_1d) for ticker, ret_1d in members if ticker != leader_ticker]
        follow_ratio_2 = sum(1 for _, ret_1d in nonleaders if ret_1d > 0.02) / max(len(nonleaders), 1)
        for ticker, _ in members:
            metrics = {
                "sector_breadth_3": round(float(sector_breadth_3), 4),
                "follow_ratio_2": round(float(follow_ratio_2), 4),
            }
            industry_amount = float(industry_amounts.get(industry, 0.0) or 0.0)
            if total_amount > 0.0 and industry_amount > 0.0:
                metrics["sector_amt_share"] = round(industry_amount / total_amount, 4)
            sector_metric_map[ticker] = metrics
    return sector_metric_map


def _compute_price_frame_close_return(price_frame: pd.DataFrame | None, *, sessions: int) -> float | None:
    if price_frame is None or price_frame.empty or "close" not in price_frame.columns or len(price_frame) <= sessions:
        return None
    close_series = pd.to_numeric(price_frame["close"], errors="coerce").dropna()
    if len(close_series) <= sessions:
        return None
    previous_close = float(close_series.iloc[-(sessions + 1)])
    latest_close = float(close_series.iloc[-1])
    if previous_close <= 0.0:
        return None
    return round((latest_close / previous_close) - 1.0, 4)


def _compute_price_frame_latest_amount(price_frame: pd.DataFrame | None) -> float | None:
    if price_frame is None or price_frame.empty:
        return None
    source_column = "amount" if "amount" in price_frame.columns else "volume" if "volume" in price_frame.columns else ""
    if not source_column:
        return None
    latest_amount = pd.to_numeric(price_frame[source_column], errors="coerce").dropna()
    if latest_amount.empty:
        return None
    value = float(latest_amount.iloc[-1])
    return value if value > 0.0 else None


def _rank_candidates_for_heavy_scoring(provisional_ranking: list[tuple[float, CandidateStock]]) -> list[tuple[float, CandidateStock]]:
    return sorted(
        provisional_ranking,
        key=_heavy_score_ranking_key,
        reverse=True,
    )


def _heavy_score_ranking_key(item: tuple[float, CandidateStock]) -> tuple[float, float, float]:
    return item[0], item[1].avg_volume_20d, item[1].market_cap


def _select_fundamental_candidates(
    ranked_candidates: list[tuple[float, CandidateStock]],
    results: dict[str, dict[str, StrategySignal]],
) -> list[CandidateStock]:
    return [candidate for score, candidate in ranked_candidates if _is_heavy_score_eligible(score, results.get(candidate.ticker, {}))][:FUNDAMENTAL_SCORE_MAX_CANDIDATES]


def _is_heavy_score_eligible(score: float, signals: dict[str, StrategySignal]) -> bool:
    return score >= HEAVY_SCORE_MIN_PROVISIONAL_SCORE and _has_positive_trend_confirmation(signals)


def _has_positive_trend_confirmation(signals: dict[str, StrategySignal]) -> bool:
    trend_signal = signals.get("trend")
    if trend_signal is None or trend_signal.completeness <= 0:
        return False
    return trend_signal.direction > 0 and trend_signal.confidence >= HEAVY_SCORE_MIN_TREND_CONFIDENCE


def _populate_heavy_signals(
    results: dict[str, dict[str, StrategySignal]],
    fundamental_candidates: list[CandidateStock],
    trade_date: str,
    industry_pe_medians: dict[str, float],
    feature_store: ScoringFeatureStore,
) -> None:
    # Parallel IO: fundamental + event_sentiment scoring per candidate
    max_workers = min(SCORE_BATCH_CONCURRENCY, len(fundamental_candidates)) if fundamental_candidates else 1
    if max_workers <= 1:
        for candidate in fundamental_candidates:
            results[candidate.ticker]["fundamental"] = _score_fundamental_from_store(
                candidate, trade_date, industry_pe_medians, feature_store
            )
        for candidate in _select_event_sentiment_candidates(fundamental_candidates):
            results[candidate.ticker]["event_sentiment"] = _score_event_from_store(candidate, trade_date, feature_store)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all fundamental scoring tasks
            fundamental_futures = {
                executor.submit(
                    _score_fundamental_from_store,
                    candidate,
                    trade_date,
                    industry_pe_medians,
                    feature_store,
                ): candidate
                for candidate in fundamental_candidates
            }
            # Submit event_sentiment scoring tasks for eligible candidates
            event_candidates = _select_event_sentiment_candidates(fundamental_candidates)
            event_futures = {
                executor.submit(_score_event_from_store, candidate, trade_date, feature_store): candidate
                for candidate in event_candidates
            }
            # Collect fundamental results
            for future in concurrent.futures.as_completed(fundamental_futures):
                candidate = fundamental_futures[future]
                try:
                    results[candidate.ticker]["fundamental"] = future.result()
                except Exception:
                    logger.warning("Fundamental scoring failed for %s", candidate.ticker, exc_info=True)
            # Collect event_sentiment results
            for future in concurrent.futures.as_completed(event_futures):
                candidate = event_futures[future]
                try:
                    results[candidate.ticker]["event_sentiment"] = future.result()
                except Exception:
                    logger.warning("Event-sentiment scoring failed for %s", candidate.ticker, exc_info=True)

    _populate_intraday_short_trade_metrics(results, fundamental_candidates, trade_date, feature_store)
    _populate_dragon_tiger_bonus_metrics(results, fundamental_candidates, trade_date, feature_store)


def _score_fundamental_from_store(
    candidate: CandidateStock,
    trade_date: str,
    industry_pe_medians: dict[str, float],
    feature_store: ScoringFeatureStore,
) -> StrategySignal:
    return score_fundamental_strategy_from_metrics(
        feature_store.load_financial_metrics(candidate.ticker, trade_date),
        candidate.industry_sw,
        industry_pe_medians,
    )


def _score_event_from_store(
    candidate: CandidateStock,
    trade_date: str,
    feature_store: ScoringFeatureStore,
) -> StrategySignal:
    news_items, trades = feature_store.load_event_inputs(candidate.ticker, trade_date)
    return score_event_sentiment_strategy_from_inputs(news_items, trades, trade_date)


def _populate_intraday_short_trade_metrics(
    results: dict[str, dict[str, StrategySignal]],
    candidates: list[CandidateStock],
    trade_date: str,
    feature_store: ScoringFeatureStore,
) -> None:
    # Gather eligible candidates and their trend signals first (sequential, CPU-only)
    eligible: list[tuple[CandidateStock, StrategySignal]] = []
    for candidate in _select_intraday_metric_candidates(candidates):
        trend_signal = results.get(candidate.ticker, {}).get("trend")
        if not _trend_signal_has_momentum_payload(trend_signal):
            continue
        eligible.append((candidate, trend_signal))

    if not eligible:
        return

    # Parallel IO: fetch intraday metrics concurrently
    max_workers = min(SCORE_BATCH_CONCURRENCY, len(eligible))
    if max_workers <= 1:
        for candidate, trend_signal in eligible:
            intraday_metrics = _build_intraday_short_trade_metrics(
                candidate.ticker,
                trade_date,
                feature_store=feature_store,
            )
            if not intraday_metrics:
                continue
            _merge_metrics_into_trend_momentum(trend_signal, intraday_metrics)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_pair = {
                executor.submit(
                    _build_intraday_short_trade_metrics,
                    candidate.ticker,
                    trade_date,
                    feature_store=feature_store,
                ): (candidate, trend_signal)
                for candidate, trend_signal in eligible
            }
            for future in concurrent.futures.as_completed(future_to_pair):
                _candidate, trend_signal = future_to_pair[future]
                try:
                    intraday_metrics = future.result()
                except Exception:
                    logger.warning("Intraday metrics failed for %s", _candidate.ticker, exc_info=True)
                    continue
                if not intraday_metrics:
                    continue
                _merge_metrics_into_trend_momentum(trend_signal, intraday_metrics)


def _select_intraday_metric_candidates(candidates: list[CandidateStock]) -> list[CandidateStock]:
    return candidates[:INTRADAY_SCORE_MAX_CANDIDATES]


def _populate_dragon_tiger_bonus_metrics(
    results: dict[str, dict[str, StrategySignal]],
    candidates: list[CandidateStock],
    trade_date: str,
    feature_store: ScoringFeatureStore,
) -> None:
    candidates_with_momentum = [candidate for candidate in candidates if _trend_signal_has_momentum_payload(results.get(candidate.ticker, {}).get("trend"))]
    if not candidates_with_momentum:
        return
    bonus_map = feature_store.load_dragon_tiger_bonus_map([candidate.ticker for candidate in candidates_with_momentum], trade_date)
    if not bonus_map:
        return
    for candidate in candidates_with_momentum:
        bonus = bonus_map.get(candidate.ticker)
        if bonus is None:
            continue
        trend_signal = results.get(candidate.ticker, {}).get("trend")
        _merge_metrics_into_trend_momentum(trend_signal, {"dragon_tiger_bonus": round(float(bonus), 4)})


def _build_dragon_tiger_bonus_map(tickers: list[str], trade_date: str) -> dict[str, float]:
    if not tickers:
        return {}
    lhb_detail = get_lhb_detail(trade_date, trade_date)
    institutional_stats = get_lhb_institutional_stats(trade_date, trade_date)
    if (lhb_detail is None or lhb_detail.empty) and (institutional_stats is None or institutional_stats.empty):
        return {}

    normalized_tickers = {str(ticker).zfill(6) for ticker in tickers}
    bonus_map = {ticker: 0.0 for ticker in normalized_tickers}
    if lhb_detail is not None and not lhb_detail.empty and "代码" in lhb_detail.columns:
        for code in lhb_detail["代码"].astype(str).str.zfill(6):
            if code in bonus_map:
                bonus_map[code] = 1.0
    if institutional_stats is not None and not institutional_stats.empty and {"代码", "机构买入净额"}.issubset(institutional_stats.columns):
        institutional_codes = institutional_stats.copy()
        institutional_codes["代码"] = institutional_codes["代码"].astype(str).str.zfill(6)
        institutional_codes["机构买入净额"] = pd.to_numeric(institutional_codes["机构买入净额"], errors="coerce").fillna(0.0)
        for code in institutional_codes.loc[institutional_codes["机构买入净额"] > 0.0, "代码"]:
            if code in bonus_map:
                bonus_map[code] = 1.0
    return bonus_map


def _build_intraday_short_trade_metrics(
    ticker: str,
    trade_date: str,
    feature_store: ScoringFeatureStore | OptionalFeatureStore | None = None,
) -> dict[str, Any]:
    store = feature_store or OptionalFeatureStore()
    metrics = store.load_intraday_metrics(trade_date, [ticker]).get(str(ticker).zfill(6), {})
    if metrics:
        return dict(metrics)
    fallback_flow = _load_daily_flow_proxy_ratio(ticker, trade_date=trade_date, feature_store=store)
    return {"flow_60": fallback_flow, "flow_60_source": "daily_flow_proxy"} if fallback_flow is not None else {}


def build_intraday_short_trade_metrics(ticker: str, trade_date: str) -> dict[str, Any]:
    """Expose the shared intraday short-trade metrics builder for downstream adapters."""
    return _build_intraday_short_trade_metrics(ticker, trade_date)


def _build_intraday_short_trade_metrics_from_bars(intraday_bars: pd.DataFrame | None) -> dict[str, float]:
    required_columns = {"时间", "收盘", "成交额"}
    if intraday_bars is None or intraday_bars.empty or not required_columns.issubset(intraday_bars.columns):
        return {}
    normalized = intraday_bars.copy()
    normalized["时间"] = pd.to_datetime(normalized["时间"], errors="coerce")
    normalized["收盘"] = pd.to_numeric(normalized["收盘"], errors="coerce")
    normalized["成交额"] = pd.to_numeric(normalized["成交额"], errors="coerce").fillna(0.0)
    normalized = normalized.dropna(subset=["时间", "收盘"]).sort_values("时间").reset_index(drop=True)
    if len(normalized) < 2:
        return {}
    normalized["direction"] = normalized["收盘"].diff().fillna(0.0).apply(lambda value: 1.0 if value > 0 else -1.0 if value < 0 else 0.0)
    normalized["signed_turnover"] = normalized["成交额"] * normalized["direction"]

    last_120 = normalized.tail(min(120, len(normalized)))
    last_60 = normalized.tail(min(60, len(normalized)))
    last_30 = normalized.tail(min(30, len(normalized)))
    metrics: dict[str, float] = {}

    turnover_60 = float(last_60["成交额"].sum())
    if turnover_60 > 0.0:
        metrics["flow_60"] = round(float(last_60["signed_turnover"].sum()) / turnover_60, 4)
        metrics["flow_60_source"] = "bar_proxy"

    turnover_30 = float(last_30["成交额"].sum())
    if turnover_30 > 0.0:
        metrics["close_support_30"] = round(float(last_30["signed_turnover"].sum()) / turnover_30, 4)
        metrics["close_support_30_source"] = "bar_proxy"

    if not last_120.empty:
        metrics["persist_120"] = round(float((last_120["signed_turnover"] > 0.0).sum() / len(last_120)), 4)
        metrics["persist_120_source"] = "bar_proxy"
    return metrics


def _build_intraday_short_trade_metrics_from_frames(
    *,
    intraday_bars: pd.DataFrame | None,
    intraday_ticks: pd.DataFrame | None,
    trade_date: str,
) -> dict[str, float]:
    if intraday_bars is None or intraday_bars.empty or intraday_ticks is None or intraday_ticks.empty:
        return {}

    turnover_windows = _extract_intraday_turnover_windows(intraday_bars)
    if not turnover_windows:
        return {}
    tick_flows = _extract_intraday_tick_net_flows(intraday_ticks, trade_date, turnover_windows)
    if not tick_flows:
        return {}

    metrics: dict[str, float] = {}
    turnover_60 = float(turnover_windows.get("turnover_60", 0.0) or 0.0)
    turnover_30 = float(turnover_windows.get("turnover_30", 0.0) or 0.0)
    net_buy_amt_60 = float(tick_flows.get("net_buy_amt_60", 0.0) or 0.0)
    net_buy_amt_30 = float(tick_flows.get("net_buy_amt_30", 0.0) or 0.0)
    if turnover_60 > 0.0:
        metrics["flow_60"] = round(net_buy_amt_60 / turnover_60, 4)
        metrics["flow_60_source"] = "exact_tick"
    if turnover_30 > 0.0:
        metrics["close_support_30"] = round(net_buy_amt_30 / turnover_30, 4)
        metrics["close_support_30_source"] = "exact_tick"
    persist_120 = tick_flows.get("persist_120")
    if persist_120 is not None:
        metrics["persist_120"] = round(float(persist_120), 4)
        metrics["persist_120_source"] = "exact_tick"
    return metrics


def _extract_intraday_turnover_windows(intraday_bars: pd.DataFrame) -> dict[str, Any]:
    if intraday_bars.empty or not {"时间", "成交额"}.issubset(intraday_bars.columns):
        return {}
    normalized = intraday_bars.copy()
    normalized["时间"] = pd.to_datetime(normalized["时间"], errors="coerce")
    normalized["成交额"] = pd.to_numeric(normalized["成交额"], errors="coerce").fillna(0.0)
    normalized = normalized.dropna(subset=["时间"]).sort_values("时间")
    if normalized.empty:
        return {}
    last_120 = normalized.tail(min(120, len(normalized)))
    last_60 = normalized.tail(min(60, len(normalized)))
    last_30 = normalized.tail(min(30, len(normalized)))
    return {
        "minute_index_120": last_120["时间"].reset_index(drop=True),
        "window_start_60": last_60["时间"].iloc[0],
        "window_start_30": last_30["时间"].iloc[0],
        "turnover_60": float(last_60["成交额"].sum()),
        "turnover_30": float(last_30["成交额"].sum()),
    }


def _extract_intraday_tick_net_flows(
    intraday_ticks: pd.DataFrame,
    trade_date: str,
    turnover_windows: dict[str, Any],
) -> dict[str, float]:
    required_columns = {"ticktime", "price", "volume", "kind"}
    if intraday_ticks.empty or not required_columns.issubset(intraday_ticks.columns):
        return {}
    normalized = intraday_ticks.copy()
    trade_day = datetime.strptime(str(trade_date), "%Y%m%d").strftime("%Y-%m-%d")
    normalized["timestamp"] = pd.to_datetime(trade_day + " " + normalized["ticktime"].astype(str), errors="coerce")
    normalized["price"] = pd.to_numeric(normalized["price"], errors="coerce")
    normalized["volume"] = pd.to_numeric(normalized["volume"], errors="coerce")
    normalized = normalized.dropna(subset=["timestamp", "price", "volume"])
    if normalized.empty:
        return {}
    normalized["signed_amount"] = normalized["price"] * normalized["volume"] * normalized["kind"].astype(str).map({"U": 1.0, "D": -1.0}).fillna(0.0)
    window_start_60 = turnover_windows["window_start_60"]
    window_start_30 = turnover_windows["window_start_30"]
    minute_index_120 = pd.to_datetime(turnover_windows.get("minute_index_120"), errors="coerce")
    minute_flow = normalized.groupby(normalized["timestamp"].dt.floor("min"))["signed_amount"].sum()
    active_minutes_120 = minute_index_120.dropna()
    persist_120 = None
    if not active_minutes_120.empty:
        aligned_minute_flow = minute_flow.reindex(active_minutes_120, fill_value=0.0)
        persist_120 = float((aligned_minute_flow > 0.0).sum() / len(active_minutes_120))
    return {
        "net_buy_amt_60": float(normalized.loc[normalized["timestamp"] >= window_start_60, "signed_amount"].sum()),
        "net_buy_amt_30": float(normalized.loc[normalized["timestamp"] >= window_start_30, "signed_amount"].sum()),
        "persist_120": persist_120,
    }


def _load_daily_flow_proxy_ratio(
    ticker: str,
    trade_date: str | None = None,
    feature_store: ScoringFeatureStore | OptionalFeatureStore | None = None,
) -> float | None:
    if trade_date is None:
        return None
    store = feature_store or OptionalFeatureStore()
    metrics = store.load_fund_flow_metrics(trade_date, [ticker]).get(str(ticker).zfill(6), {})
    ratio = metrics.get("main_flow_ratio")
    if ratio is None:
        return None
    try:
        value = float(ratio)
    except (TypeError, ValueError):
        return None
    if abs(value) > 1.0:
        value /= 100.0
    return round(value, 4)


def _trend_signal_has_momentum_payload(trend_signal: StrategySignal | None) -> bool:
    if trend_signal is None:
        return False
    return trend_signal.sub_factors.get("momentum") is not None


def _merge_metrics_into_trend_momentum(trend_signal: StrategySignal | None, raw_metrics: dict[str, float]) -> None:
    if trend_signal is None or not raw_metrics:
        return
    momentum_payload = trend_signal.sub_factors.get("momentum")
    if momentum_payload is None:
        return
    if isinstance(momentum_payload, dict):
        metrics = dict(momentum_payload.get("metrics") or {})
        metrics.update(raw_metrics)
        momentum_payload["metrics"] = metrics
        trend_signal.sub_factors["momentum"] = momentum_payload
        return
    metrics = dict(getattr(momentum_payload, "metrics", {}) or {})
    metrics.update(raw_metrics)
    setattr(momentum_payload, "metrics", metrics)


def _select_event_sentiment_candidates(fundamental_candidates: list[CandidateStock]) -> list[CandidateStock]:
    return fundamental_candidates[:EVENT_SENTIMENT_MAX_CANDIDATES]


def score_batch(
    candidates: list[CandidateStock],
    trade_date: str,
    feature_store: ScoringFeatureStore | None = None,
) -> dict[str, dict[str, StrategySignal]]:
    started_at = perf_counter()
    scoring_feature_store = feature_store or ScoringFeatureStore()
    industry_pe_medians = _build_industry_pe_medians(trade_date, scoring_feature_store)
    results = _initialize_score_batch_results(candidates)
    fundamental_candidates = _prepare_heavy_score_candidates(candidates, trade_date, results, scoring_feature_store)
    _populate_heavy_signals(results, fundamental_candidates, trade_date, industry_pe_medians, scoring_feature_store)
    elapsed = perf_counter() - started_at
    logger.info(
        "score_batch completed: %d candidates, %d heavy-scored, concurrency=%d, %.2fs",
        len(candidates),
        len(fundamental_candidates),
        SCORE_BATCH_CONCURRENCY,
        elapsed,
    )
    return results


def _prepare_heavy_score_candidates(
    candidates: list[CandidateStock],
    trade_date: str,
    results: dict[str, dict[str, StrategySignal]],
    feature_store: ScoringFeatureStore,
) -> list[CandidateStock]:
    provisional_ranking = _build_provisional_ranking(candidates, trade_date, results, feature_store)
    ranked_candidates = _rank_candidates_for_heavy_scoring(provisional_ranking)
    return _select_fundamental_candidates(ranked_candidates, results)
