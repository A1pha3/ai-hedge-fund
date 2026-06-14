"""Event sentiment strategy sub-factor helpers.

Extracted from strategy_scorer.py (Round 20.2) to improve readability.
Contains: news sentiment scoring, insider conviction, event freshness,
and the top-level ``score_event_sentiment_strategy`` orchestrator.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from src.agents.growth_agent import (
    analyze_insider_conviction,
)
from src.data.models import CompanyNews, InsiderTrade
from src.screening.models import StrategySignal, SubFactor
from src.screening.strategy_scorer_utils import (
    _make_sub_factor,
    aggregate_sub_factors,
    EVENT_SUBFACTOR_WEIGHTS,
    NEGATIVE_NEWS_KEYWORDS,
    POSITIVE_NEWS_KEYWORDS,
)
from src.tools.api import (
    get_company_news,
    get_insider_trades,
    get_prices,
    prices_to_df,
)

logger = logging.getLogger(__name__)

_EVENT_DECAY_LAMBDA = float(os.environ.get("EVENT_DECAY_LAMBDA", "0.35"))


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
    """事件衰减函数，按文档要求使用 e^(-lambda * t)。"""
    return math.exp(-_EVENT_DECAY_LAMBDA * max(days_old, 0))


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
    # GAMMA-001: unparseable dates should be treated as very old (stale),
    # not as "today" (which would give maximum freshness weight).
    return max((trade_dt - item_dt).days, 0) if item_dt else 9999


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
    # GAMMA-002: unparseable dates should be treated as very old (stale),
    # not as "today" (which would give maximum freshness weight).
    return max((trade_dt - latest_dt).days, 0) if latest_dt else 9999


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
