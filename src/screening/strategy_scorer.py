"""Layer B 四策略评分器。"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median

import pandas as pd

from src.agents.growth_agent import (
    analyze_insider_conviction,
)
from src.screening.strategy_scorer_utils import (
    EVENT_SUBFACTOR_WEIGHTS,
    POSITIVE_NEWS_KEYWORDS,
    NEGATIVE_NEWS_KEYWORDS,
    aggregate_sub_factors,
    derive_completeness,
    _make_sub_factor,
)
from src.screening.strategy_scorer_trend import (
    score_trend_strategy,
)
from src.screening.strategy_scorer_mean_reversion import (
    score_mean_reversion_strategy,
)
from src.screening.strategy_scorer_fundamental import (
    score_fundamental_strategy,
)
from src.data.models import CompanyNews, InsiderTrade
from src.screening.models import CandidateStock, StrategySignal, SubFactor
from src.tools.akshare_api import get_intraday_bars, get_intraday_ticks, get_lhb_detail, get_lhb_institutional_stats, get_money_flow
from src.tools.api import (
    get_company_news,
    get_insider_trades,
    get_prices,
    prices_to_df,
)
from src.tools.tushare_api import get_all_stock_basic, get_daily_basic_batch, get_sw_industry_classification

# Re-export for backward compatibility
__all__ = [
    "aggregate_sub_factors",
    "derive_completeness",
    "score_trend_strategy",
    "score_mean_reversion_strategy",
    "score_fundamental_strategy",
]

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
TECHNICAL_STAGE_LIQUIDITY_RANK_BUCKET = float(os.getenv("CANDIDATE_POOL_BTST_LIQUIDITY_RANK_BUCKET", "2500"))


def _safe_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(date_str[:19], fmt)
        except ValueError:
            continue
    return None


def compute_event_decay(days_old: int) -> float:
    """事件衰减函数，按文档要求使用 e^(-0.35t)。"""
    return math.exp(-0.35 * max(days_old, 0))


def _event_weight_multiplier(days_old: int, strength: int) -> float:
    multiplier = 1.0
    if strength <= 0:
        return 0.0
    if strength == 1 and days_old > 2:
        return 0.0
    if strength == 1:
        multiplier *= 0.55
    if days_old > 3:
        multiplier *= 0.75
    if days_old > 5:
        multiplier *= 0.55
    if days_old > 10:
        multiplier *= 0.25
    return multiplier


def _empty_signal() -> StrategySignal:
    return StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={})


def _load_price_frame(ticker: str, trade_date: str, lookback_days: int = 400) -> pd.DataFrame:
    start_date = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_date = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d")
    prices = get_prices(ticker=ticker, start_date=start_date, end_date=end_date)
    if not prices:
        return pd.DataFrame()
    return prices_to_df(prices)


def _score_news_sentiment(news_items: list[CompanyNews], trade_date: str) -> SubFactor:
    if not news_items:
        return _make_sub_factor("news_sentiment", 0, 0.0, EVENT_SUBFACTOR_WEIGHTS["news_sentiment"], completeness=0.0)

    article_metrics = _build_news_sentiment_article_metrics(news_items, trade_date)
    normalized_score, recent_count, informative_count = _aggregate_news_article_metrics(article_metrics)
    direction, confidence, completeness = _resolve_news_sentiment_signal(
        normalized_score=normalized_score,
        informative_count=informative_count,
    )
    return _build_news_sentiment_sub_factor(
        direction,
        confidence,
        completeness,
        normalized_score=normalized_score,
        recent_count=recent_count,
        informative_count=informative_count,
        article_metrics=article_metrics,
    )


def _build_news_sentiment_article_metrics(news_items: list[CompanyNews], trade_date: str) -> list[dict]:
    trade_dt = datetime.strptime(trade_date, "%Y%m%d")
    return [_score_news_article(item, trade_dt) for item in news_items[:20]]


def _build_news_sentiment_sub_factor(
    direction: int,
    confidence: float,
    completeness: float,
    *,
    normalized_score: float,
    recent_count: int,
    informative_count: int,
    article_metrics: list[dict],
) -> SubFactor:
    return _make_sub_factor(**_build_news_sentiment_sub_factor_payload(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        normalized_score=normalized_score,
        recent_count=recent_count,
        informative_count=informative_count,
        article_metrics=article_metrics,
    ))


def _build_news_sentiment_sub_factor_payload(
    *,
    direction: int,
    confidence: float,
    completeness: float,
    normalized_score: float,
    recent_count: int,
    informative_count: int,
    article_metrics: list[dict],
) -> dict:
    return {
        "name": "news_sentiment",
        "direction": direction,
        "confidence": confidence,
        "weight": EVENT_SUBFACTOR_WEIGHTS["news_sentiment"],
        "completeness": completeness,
        "metrics": _build_news_sentiment_metrics_payload(
            normalized_score=normalized_score,
            recent_count=recent_count,
            informative_count=informative_count,
            article_metrics=article_metrics,
        ),
    }


def _resolve_news_sentiment_signal(*, normalized_score: float, informative_count: int) -> tuple[int, float, float]:
    direction = 1 if normalized_score > 0.08 else -1 if normalized_score < -0.08 else 0
    confidence = min(100.0, abs(normalized_score) * 130.0)
    completeness = min(1.0, informative_count / 3.0)
    return direction, confidence, completeness


def _build_news_sentiment_metrics_payload(
    *,
    normalized_score: float,
    recent_count: int,
    informative_count: int,
    article_metrics: list[dict],
) -> dict[str, float | int | list[dict]]:
    return {
        "weighted_score": normalized_score,
        "recent_articles": recent_count,
        "informative_articles": informative_count,
        "articles": article_metrics[:5],
    }


def _score_news_article(item: CompanyNews, trade_dt: datetime) -> dict:
    days_old = _resolve_news_article_days_old(item.date, trade_dt)
    decay = compute_event_decay(days_old)
    pos_hits, neg_hits = _count_event_keyword_hits(item)
    direction, strength = _resolve_news_direction_and_strength(pos_hits, neg_hits)
    effective_weight = decay * _event_weight_multiplier(days_old, strength)
    confidence = min(100.0, 45.0 + strength * 18.0) if strength > 0 else 0.0
    return _build_news_article_metrics(item.title, days_old, decay, direction, confidence, effective_weight)


def _build_news_article_metrics(
    title: str,
    days_old: int,
    decay: float,
    direction: int,
    confidence: float,
    effective_weight: float,
) -> dict[str, str | int | float]:
    return {
        "title": title,
        "days_old": days_old,
        "decay": decay,
        "direction": direction,
        "confidence": confidence,
        "effective_weight": effective_weight,
    }


def _resolve_news_article_days_old(news_date: str, trade_dt: datetime) -> int:
    item_dt = _safe_date(news_date)
    return (trade_dt - item_dt).days if item_dt else 0


def _resolve_news_direction_and_strength(pos_hits: int, neg_hits: int) -> tuple[int, int]:
    if pos_hits > neg_hits:
        return 1, pos_hits - neg_hits
    if neg_hits > pos_hits:
        return -1, neg_hits - pos_hits
    return 0, 0


def _aggregate_news_article_metrics(article_metrics: list[dict]) -> tuple[float, int, int]:
    weighted_score = 0.0
    total_weight = 0.0
    recent_count = 0
    informative_count = 0
    for metric in article_metrics:
        weighted_delta, effective_weight, recent_delta, informative_delta = _resolve_news_metric_contribution(metric)
        weighted_score += weighted_delta
        total_weight += effective_weight
        recent_count += recent_delta
        informative_count += informative_delta
    normalized_score = weighted_score / total_weight if total_weight > 0 else 0.0
    return normalized_score, recent_count, informative_count


def _resolve_news_metric_contribution(metric: dict) -> tuple[float, float, int, int]:
    effective_weight = float(metric["effective_weight"])
    confidence = float(metric["confidence"])
    direction = int(metric["direction"])
    return (
        direction * (confidence / 100.0) * effective_weight,
        effective_weight,
        1 if int(metric["days_old"]) <= 5 else 0,
        1 if effective_weight > 0 else 0,
    )


def _score_insider_conviction(trades: list[InsiderTrade]) -> SubFactor:
    if not trades:
        return _make_sub_factor("insider_conviction", 0, 0.0, EVENT_SUBFACTOR_WEIGHTS["insider_conviction"], completeness=0.0)
    analysis = analyze_insider_conviction(trades)
    direction, confidence = _resolve_insider_conviction_direction_and_confidence(float(analysis["score"]))
    return _make_sub_factor(
        "insider_conviction",
        direction,
        confidence,
        EVENT_SUBFACTOR_WEIGHTS["insider_conviction"],
        metrics=analysis,
    )


def _resolve_insider_conviction_direction_and_confidence(score: float) -> tuple[int, float]:
    return (1 if score > 0.6 else -1 if score < 0.4 else 0), abs(score - 0.5) * 200.0


def _score_event_freshness(news_items: list[CompanyNews], trade_date: str) -> SubFactor:
    if not news_items:
        return _make_sub_factor("event_freshness", 0, 0.0, EVENT_SUBFACTOR_WEIGHTS["event_freshness"], completeness=0.0)
    return _build_event_freshness_factor(_build_event_freshness_snapshot(news_items[0], trade_date))


@dataclass(frozen=True)
class EventFreshnessSnapshot:
    days_old: int
    decay: float
    positive_hits: int
    negative_hits: int
    freshness_weight: float
    strength: int


def _build_event_freshness_snapshot(item: CompanyNews, trade_date: str) -> EventFreshnessSnapshot:
    days_old = _resolve_event_freshness_days_old(item.date, trade_date)
    decay = compute_event_decay(days_old)
    positive_hits, negative_hits = _count_event_keyword_hits(item)
    strength = abs(positive_hits - negative_hits)
    freshness_weight = _event_weight_multiplier(days_old, strength)
    return EventFreshnessSnapshot(
        days_old=days_old,
        decay=decay,
        positive_hits=positive_hits,
        negative_hits=negative_hits,
        freshness_weight=freshness_weight,
        strength=strength,
    )


def _build_event_freshness_factor(snapshot: EventFreshnessSnapshot) -> SubFactor:
    direction = _resolve_event_freshness_direction(
        pos_hits=snapshot.positive_hits,
        neg_hits=snapshot.negative_hits,
        strength=snapshot.strength,
        freshness_weight=snapshot.freshness_weight,
    )
    return _make_sub_factor(
        "event_freshness",
        direction,
        snapshot.decay * snapshot.freshness_weight * 100.0,
        EVENT_SUBFACTOR_WEIGHTS["event_freshness"],
        metrics=_build_event_freshness_metrics(snapshot),
    )


def _build_event_freshness_metrics(snapshot: EventFreshnessSnapshot) -> dict[str, int | float]:
    metrics: dict[str, int | float] = {
        "days_old": snapshot.days_old,
        "decay": snapshot.decay,
        "positive_hits": snapshot.positive_hits,
        "negative_hits": snapshot.negative_hits,
        "freshness_weight": snapshot.freshness_weight,
    }
    if snapshot.positive_hits > snapshot.negative_hits and snapshot.strength > 0 and snapshot.freshness_weight > 0:
        metrics["days_since_positive_event"] = snapshot.days_old
        metrics["catalyst_freshness"] = snapshot.decay
    return metrics


def _resolve_event_freshness_days_old(news_date: str, trade_date: str) -> int:
    trade_dt = datetime.strptime(trade_date, "%Y%m%d")
    latest_dt = _safe_date(news_date)
    return (trade_dt - latest_dt).days if latest_dt else 0


def _count_event_keyword_hits(news_item: CompanyNews) -> tuple[int, int]:
    text = f"{news_item.title or ''} {news_item.content or ''}".lower()
    pos_hits = sum(1 for word in POSITIVE_NEWS_KEYWORDS if word in text)
    neg_hits = sum(1 for word in NEGATIVE_NEWS_KEYWORDS if word in text)
    return pos_hits, neg_hits


def _resolve_event_freshness_direction(*, pos_hits: int, neg_hits: int, strength: int, freshness_weight: float) -> int:
    if freshness_weight <= 0 or freshness_weight < 0.35 or strength < 2:
        return 0
    if pos_hits > neg_hits:
        return 1
    if neg_hits > pos_hits:
        return -1
    return 0


def score_event_sentiment_strategy(ticker: str, trade_date: str) -> StrategySignal:
    start_date, end_date = _resolve_event_sentiment_date_window(trade_date)
    news_items, trades = _load_event_sentiment_inputs(ticker=ticker, start_date=start_date, end_date=end_date)
    return _build_event_sentiment_strategy_signal(news_items=news_items, trades=trades, trade_date=trade_date)


def _build_event_sentiment_strategy_signal(
    *, news_items: list[CompanyNews], trades: list[InsiderTrade], trade_date: str
) -> StrategySignal:
    return aggregate_sub_factors(
        _build_event_sentiment_sub_factors(news_items=news_items, trades=trades, trade_date=trade_date)
    )


def _resolve_event_sentiment_date_window(trade_date: str) -> tuple[str, str]:
    trade_dt = datetime.strptime(trade_date, "%Y%m%d")
    return (trade_dt - timedelta(days=30)).strftime("%Y-%m-%d"), trade_dt.strftime("%Y-%m-%d")


def _load_event_sentiment_inputs(*, ticker: str, start_date: str, end_date: str) -> tuple[list[CompanyNews], list[InsiderTrade]]:
    news_items = get_company_news(ticker=ticker, start_date=start_date, end_date=end_date, limit=50)
    trades = get_insider_trades(ticker=ticker, end_date=end_date, start_date=start_date, limit=100)
    return news_items, trades


def _build_event_sentiment_sub_factors(
    *,
    news_items: list[CompanyNews],
    trades: list[InsiderTrade],
    trade_date: str,
) -> list[SubFactor]:
    return _assemble_event_sentiment_sub_factors(
        _score_news_sentiment(news_items, trade_date),
        _score_insider_conviction(trades),
        _score_event_freshness(news_items, trade_date),
    )


def _assemble_event_sentiment_sub_factors(
    news_sentiment: SubFactor, insider_conviction: SubFactor, event_freshness: SubFactor
) -> list[SubFactor]:
    return [news_sentiment, insider_conviction, event_freshness]


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


def _build_industry_pe_medians(trade_date: str) -> dict[str, float]:
    daily_df = get_daily_basic_batch(trade_date)
    stock_basic = get_all_stock_basic()
    sw_map = get_sw_industry_classification() or {}
    if daily_df is None or daily_df.empty or stock_basic is None or stock_basic.empty:
        return {}

    symbol_to_industry = _build_symbol_to_industry_map(stock_basic, sw_map)
    grouped = _group_industry_pe_values(daily_df, symbol_to_industry)
    return {industry: median(values) for industry, values in grouped.items() if values}


def score_candidate(
    candidate: CandidateStock,
    trade_date: str,
    industry_pe_medians: dict[str, float] | None = None,
    prices_df: pd.DataFrame | None = None,
) -> dict[str, StrategySignal]:
    prices_df = prices_df if prices_df is not None else _load_price_frame(candidate.ticker, trade_date)
    industry_pe_medians = industry_pe_medians if industry_pe_medians is not None else {}
    return {
        "trend": score_trend_strategy(prices_df, ticker=candidate.ticker),
        "mean_reversion": score_mean_reversion_strategy(prices_df),
        "fundamental": score_fundamental_strategy(candidate.ticker, trade_date, candidate.industry_sw, industry_pe_medians),
        "event_sentiment": score_event_sentiment_strategy(candidate.ticker, trade_date),
    }


def _compute_light_signals(candidate: CandidateStock, trade_date: str) -> tuple[dict[str, StrategySignal], pd.DataFrame]:
    prices_df = _load_price_frame(candidate.ticker, trade_date)
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
) -> list[tuple[float, CandidateStock]]:
    provisional_ranking: list[tuple[float, CandidateStock]] = []
    technical_candidates = _rank_candidates_for_technical_stage(candidates)[:TECHNICAL_SCORE_MAX_CANDIDATES]
    price_frames_by_ticker: dict[str, pd.DataFrame] = {}

    for candidate in technical_candidates:
        light_signals, price_frame = _compute_light_signals(candidate, trade_date)
        results[candidate.ticker] = light_signals
        if price_frame is not None:
            price_frames_by_ticker[candidate.ticker] = price_frame
        provisional_ranking.append((_provisional_score(light_signals), candidate))
    _populate_sector_diffusion_metrics(results, technical_candidates, price_frames_by_ticker)
    return _append_unranked_candidates_to_provisional_ranking(provisional_ranking, candidates)


def _append_unranked_candidates_to_provisional_ranking(
    provisional_ranking: list[tuple[float, CandidateStock]], candidates: list[CandidateStock]
) -> list[tuple[float, CandidateStock]]:
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
    return [
        candidate
        for score, candidate in ranked_candidates
        if _is_heavy_score_eligible(score, results.get(candidate.ticker, {}))
    ][:FUNDAMENTAL_SCORE_MAX_CANDIDATES]


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
) -> None:
    for candidate in fundamental_candidates:
        results[candidate.ticker]["fundamental"] = score_fundamental_strategy(
            candidate.ticker,
            trade_date,
            candidate.industry_sw,
            industry_pe_medians,
        )

    for candidate in _select_event_sentiment_candidates(fundamental_candidates):
        results[candidate.ticker]["event_sentiment"] = score_event_sentiment_strategy(candidate.ticker, trade_date)

    _populate_intraday_short_trade_metrics(results, fundamental_candidates, trade_date)
    _populate_dragon_tiger_bonus_metrics(results, fundamental_candidates, trade_date)


def _populate_intraday_short_trade_metrics(
    results: dict[str, dict[str, StrategySignal]],
    candidates: list[CandidateStock],
    trade_date: str,
) -> None:
    for candidate in _select_intraday_metric_candidates(candidates):
        trend_signal = results.get(candidate.ticker, {}).get("trend")
        if not _trend_signal_has_momentum_payload(trend_signal):
            continue
        intraday_metrics = _build_intraday_short_trade_metrics(candidate.ticker, trade_date)
        if not intraday_metrics:
            continue
        _merge_metrics_into_trend_momentum(trend_signal, intraday_metrics)


def _select_intraday_metric_candidates(candidates: list[CandidateStock]) -> list[CandidateStock]:
    return candidates[:INTRADAY_SCORE_MAX_CANDIDATES]


def _populate_dragon_tiger_bonus_metrics(
    results: dict[str, dict[str, StrategySignal]],
    candidates: list[CandidateStock],
    trade_date: str,
) -> None:
    candidates_with_momentum = [
        candidate
        for candidate in candidates
        if _trend_signal_has_momentum_payload(results.get(candidate.ticker, {}).get("trend"))
    ]
    if not candidates_with_momentum:
        return
    bonus_map = _build_dragon_tiger_bonus_map([candidate.ticker for candidate in candidates_with_momentum], trade_date)
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


def _build_intraday_short_trade_metrics(ticker: str, trade_date: str) -> dict[str, float]:
    intraday_bars = get_intraday_bars(ticker, trade_date)
    if intraday_bars is None or intraday_bars.empty:
        fallback_flow = _load_daily_flow_proxy_ratio(ticker)
        return {"flow_60": fallback_flow, "flow_60_source": "daily_flow_proxy"} if fallback_flow is not None else {}
    proxy_metrics = _build_intraday_short_trade_metrics_from_bars(intraday_bars)
    if proxy_metrics:
        return proxy_metrics
    intraday_ticks = get_intraday_ticks(ticker, trade_date)
    metrics = _build_intraday_short_trade_metrics_from_frames(
        intraday_bars=intraday_bars,
        intraday_ticks=intraday_ticks,
        trade_date=trade_date,
    )
    if "flow_60" not in metrics:
        fallback_flow = _load_daily_flow_proxy_ratio(ticker)
        if fallback_flow is not None:
            metrics["flow_60"] = fallback_flow
            metrics["flow_60_source"] = "daily_flow_proxy"
    return metrics


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


def _load_daily_flow_proxy_ratio(ticker: str) -> float | None:
    money_flow = get_money_flow(ticker)
    if money_flow is None or money_flow.empty:
        return None
    ratio_values = money_flow.get("主力净流入占比")
    if ratio_values is None:
        return None
    if isinstance(ratio_values, pd.Series):
        ratio_series = pd.to_numeric(ratio_values, errors="coerce")
    else:
        ratio_series = pd.Series([pd.to_numeric(ratio_values, errors="coerce")])
    ratio_series = ratio_series.dropna()
    if ratio_series.empty:
        return None
    latest_ratio = float(ratio_series.dropna().iloc[0])
    if abs(latest_ratio) > 1.0:
        latest_ratio /= 100.0
    return round(latest_ratio, 4)


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


def score_batch(candidates: list[CandidateStock], trade_date: str) -> dict[str, dict[str, StrategySignal]]:
    industry_pe_medians = _build_industry_pe_medians(trade_date)
    results = _initialize_score_batch_results(candidates)
    fundamental_candidates = _prepare_heavy_score_candidates(candidates, trade_date, results)
    _populate_heavy_signals(results, fundamental_candidates, trade_date, industry_pe_medians)
    return results


def _prepare_heavy_score_candidates(
    candidates: list[CandidateStock],
    trade_date: str,
    results: dict[str, dict[str, StrategySignal]],
) -> list[CandidateStock]:
    provisional_ranking = _build_provisional_ranking(candidates, trade_date, results)
    ranked_candidates = _rank_candidates_for_heavy_scoring(provisional_ranking)
    return _select_fundamental_candidates(ranked_candidates, results)
