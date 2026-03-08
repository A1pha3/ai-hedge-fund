"""Layer B 四策略评分器。"""

from __future__ import annotations

import math
import os
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
from typing import Iterable, Optional

import pandas as pd

from src.agents.growth_agent import (
    analyze_growth_trends,
    analyze_insider_conviction,
    analyze_margin_trends,
    analyze_valuation,
    check_financial_health,
)
from src.agents.technicals import (
    calculate_adx,
    calculate_atr,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_hurst_exponent,
    calculate_mean_reversion_signals,
    calculate_momentum_signals,
    calculate_rsi,
    calculate_stat_arb_signals,
    calculate_volatility_signals,
)
from src.data.models import CompanyNews, FinancialMetrics, InsiderTrade
from src.screening.models import CandidateStock, StrategySignal, SubFactor
from src.tools.api import (
    get_company_news,
    get_financial_metrics,
    get_insider_trades,
    get_prices,
    prices_to_df,
)
from src.tools.tushare_api import get_all_stock_basic, get_daily_basic_batch, get_sw_industry_classification

LIGHT_STRATEGY_WEIGHTS = {
    "trend": 0.6,
    "mean_reversion": 0.4,
}
TECHNICAL_SCORE_MAX_CANDIDATES = int(os.getenv("SCORE_BATCH_TECHNICAL_MAX_CANDIDATES", "160"))
FUNDAMENTAL_SCORE_MAX_CANDIDATES = int(os.getenv("SCORE_BATCH_FUNDAMENTAL_MAX_CANDIDATES", "100"))
EVENT_SENTIMENT_MAX_CANDIDATES = int(os.getenv("SCORE_BATCH_EVENT_SENTIMENT_MAX_CANDIDATES", "40"))
HEAVY_SCORE_MIN_PROVISIONAL_SCORE = float(os.getenv("SCORE_BATCH_MIN_PROVISIONAL_SCORE", "0.05"))

TREND_SUBFACTOR_WEIGHTS = {
    "ema_alignment": 0.30,
    "adx_strength": 0.25,
    "momentum": 0.25,
    "volatility": 0.20,
}

MEAN_REVERSION_SUBFACTOR_WEIGHTS = {
    "zscore_bbands": 0.35,
    "rsi_extreme": 0.20,
    "stat_arb": 0.25,
    "hurst_regime": 0.20,
}

FUNDAMENTAL_SUBFACTOR_WEIGHTS = {
    "profitability": 0.25,
    "growth": 0.25,
    "financial_health": 0.20,
    "growth_valuation": 0.15,
    "industry_pe": 0.15,
}

EVENT_SUBFACTOR_WEIGHTS = {
    "news_sentiment": 0.55,
    "insider_conviction": 0.25,
    "event_freshness": 0.20,
}

POSITIVE_NEWS_KEYWORDS = {
    "beat", "upgrade", "contract", "growth", "record", "profit", "buyback", "dividend",
    "approval", "rebound", "breakthrough", "订单", "中标", "回购", "分红", "增长", "盈利", "超预期",
}
NEGATIVE_NEWS_KEYWORDS = {
    "miss", "downgrade", "lawsuit", "fraud", "loss", "probe", "warning", "default",
    "layoff", "recall", "risk", "亏损", "减持", "调查", "诉讼", "暴雷", "违约", "风险",
}


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _signal_to_direction(signal: str) -> int:
    mapping = {"bullish": 1, "neutral": 0, "bearish": -1}
    return mapping.get(str(signal).lower(), 0)


def _safe_date(date_str: str) -> Optional[datetime]:
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


def derive_completeness(sub_factors: Iterable[SubFactor]) -> float:
    available = [factor for factor in sub_factors if factor.completeness > 0]
    if not available:
        return 0.0

    total_weight = sum(factor.weight for factor in available)
    if total_weight <= 0:
        return 0.0

    return _clip(
        sum((factor.weight / total_weight) * factor.completeness for factor in available),
        0.0,
        1.0,
    )


def aggregate_sub_factors(sub_factors: list[SubFactor]) -> StrategySignal:
    """按 Phase 2.2 的规则聚合子因子。"""
    available = [factor for factor in sub_factors if factor.completeness > 0]
    sub_factor_map = {factor.name: factor.model_dump() for factor in sub_factors}
    if not available:
        return StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors=sub_factor_map)

    total_weight = sum(factor.weight for factor in available)
    normalized = [(factor, factor.weight / total_weight) for factor in available if total_weight > 0]

    score = sum(weight * factor.direction * (factor.confidence / 100.0) for factor, weight in normalized)
    direction = 1 if score > 0 else -1 if score < 0 else 0

    majority_count = sum(1 for factor, _ in normalized if factor.direction == direction)
    if direction == 0:
        majority_count = sum(1 for factor, _ in normalized if factor.direction == 0)
    consistency = majority_count / len(normalized) if normalized else 0.0
    confidence = sum(weight * factor.confidence for factor, weight in normalized) * consistency
    completeness = derive_completeness(sub_factors)

    return StrategySignal(
        direction=direction,
        confidence=_clip(confidence, 0.0, 100.0),
        completeness=completeness,
        sub_factors=sub_factor_map,
    )


def _make_sub_factor(
    name: str,
    direction: int,
    confidence: float,
    weight: float,
    completeness: float = 1.0,
    metrics: Optional[dict] = None,
) -> SubFactor:
    return SubFactor(
        name=name,
        direction=direction,
        confidence=_clip(confidence, 0.0, 100.0),
        completeness=_clip(completeness, 0.0, 1.0),
        weight=weight,
        metrics=metrics or {},
    )


def _empty_signal() -> StrategySignal:
    return StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={})


def _load_price_frame(ticker: str, trade_date: str, lookback_days: int = 400) -> pd.DataFrame:
    start_date = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_date = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d")
    prices = get_prices(ticker=ticker, start_date=start_date, end_date=end_date)
    if not prices:
        return pd.DataFrame()
    return prices_to_df(prices)


def _score_ema_alignment(prices_df: pd.DataFrame) -> SubFactor:
    if prices_df.empty or len(prices_df) < 60:
        return _make_sub_factor("ema_alignment", 0, 0.0, TREND_SUBFACTOR_WEIGHTS["ema_alignment"], completeness=0.0)

    ema_10 = calculate_ema(prices_df, 10)
    ema_30 = calculate_ema(prices_df, 30)
    ema_60 = calculate_ema(prices_df, 60)
    close = float(prices_df["close"].iloc[-1]) if pd.notna(prices_df["close"].iloc[-1]) else 0.0

    if ema_10.iloc[-1] > ema_30.iloc[-1] > ema_60.iloc[-1]:
        direction = 1
    elif ema_10.iloc[-1] < ema_30.iloc[-1] < ema_60.iloc[-1]:
        direction = -1
    else:
        direction = 0

    if close > 0:
        spread = abs((ema_10.iloc[-1] - ema_30.iloc[-1]) / close) + abs((ema_30.iloc[-1] - ema_60.iloc[-1]) / close)
        confidence = _clip(spread * 2500, 0.0, 100.0)
    else:
        confidence = 0.0

    return _make_sub_factor(
        "ema_alignment",
        direction,
        confidence,
        TREND_SUBFACTOR_WEIGHTS["ema_alignment"],
        metrics={
            "ema_10": float(ema_10.iloc[-1]),
            "ema_30": float(ema_30.iloc[-1]),
            "ema_60": float(ema_60.iloc[-1]),
        },
    )


def _score_adx_strength(prices_df: pd.DataFrame) -> SubFactor:
    if prices_df.empty or len(prices_df) < 30:
        return _make_sub_factor("adx_strength", 0, 0.0, TREND_SUBFACTOR_WEIGHTS["adx_strength"], completeness=0.0)

    adx_df = calculate_adx(prices_df.copy(), 20)
    adx = float(adx_df["adx"].iloc[-1]) if pd.notna(adx_df["adx"].iloc[-1]) else 0.0
    plus_di = float(adx_df["+di"].iloc[-1]) if pd.notna(adx_df["+di"].iloc[-1]) else 0.0
    minus_di = float(adx_df["-di"].iloc[-1]) if pd.notna(adx_df["-di"].iloc[-1]) else 0.0

    if adx < 20:
        direction = 0
    else:
        direction = 1 if plus_di > minus_di else -1 if minus_di > plus_di else 0

    return _make_sub_factor(
        "adx_strength",
        direction,
        adx,
        TREND_SUBFACTOR_WEIGHTS["adx_strength"],
        metrics={"adx": adx, "+di": plus_di, "-di": minus_di},
    )


def score_trend_strategy(prices_df: pd.DataFrame) -> StrategySignal:
    momentum_signal = calculate_momentum_signals(prices_df) if len(prices_df) >= 126 else None
    volatility_signal = calculate_volatility_signals(prices_df) if len(prices_df) >= 126 else None

    sub_factors = [
        _score_ema_alignment(prices_df),
        _score_adx_strength(prices_df),
        _make_sub_factor(
            "momentum",
            _signal_to_direction(momentum_signal["signal"]) if momentum_signal else 0,
            (momentum_signal["confidence"] * 100.0) if momentum_signal else 0.0,
            TREND_SUBFACTOR_WEIGHTS["momentum"],
            completeness=1.0 if momentum_signal else 0.0,
            metrics=(momentum_signal["metrics"] if momentum_signal else {}),
        ),
        _make_sub_factor(
            "volatility",
            _signal_to_direction(volatility_signal["signal"]) if volatility_signal else 0,
            (volatility_signal["confidence"] * 100.0) if volatility_signal else 0.0,
            TREND_SUBFACTOR_WEIGHTS["volatility"],
            completeness=1.0 if volatility_signal else 0.0,
            metrics=(volatility_signal["metrics"] if volatility_signal else {}),
        ),
    ]
    return aggregate_sub_factors(sub_factors)


def score_mean_reversion_strategy(prices_df: pd.DataFrame) -> StrategySignal:
    mean_reversion_signal = calculate_mean_reversion_signals(prices_df) if len(prices_df) >= 50 else None
    stat_arb_signal = calculate_stat_arb_signals(prices_df) if len(prices_df) >= 80 else None

    if len(prices_df) >= 28:
        rsi_14 = calculate_rsi(prices_df, 14)
        rsi_28 = calculate_rsi(prices_df, 28)
        last_rsi_14 = float(rsi_14.iloc[-1]) if pd.notna(rsi_14.iloc[-1]) else 50.0
        last_rsi_28 = float(rsi_28.iloc[-1]) if pd.notna(rsi_28.iloc[-1]) else 50.0
        if last_rsi_14 < 30 and last_rsi_28 < 40:
            rsi_direction = 1
            rsi_conf = min(100.0, (40.0 - last_rsi_14) * 3)
        elif last_rsi_14 > 70 and last_rsi_28 > 60:
            rsi_direction = -1
            rsi_conf = min(100.0, (last_rsi_14 - 60.0) * 3)
        else:
            rsi_direction = 0
            rsi_conf = 50.0
        rsi_factor = _make_sub_factor(
            "rsi_extreme",
            rsi_direction,
            rsi_conf,
            MEAN_REVERSION_SUBFACTOR_WEIGHTS["rsi_extreme"],
            metrics={"rsi_14": last_rsi_14, "rsi_28": last_rsi_28},
        )
    else:
        rsi_factor = _make_sub_factor("rsi_extreme", 0, 0.0, MEAN_REVERSION_SUBFACTOR_WEIGHTS["rsi_extreme"], completeness=0.0)

    hurst = calculate_hurst_exponent(prices_df["close"]) if len(prices_df) >= 80 else 0.5
    z_score = None
    if len(prices_df) >= 50:
        ma_50 = prices_df["close"].rolling(window=50).mean()
        std_50 = prices_df["close"].rolling(window=50).std()
        z_score = float(((prices_df["close"] - ma_50) / std_50).iloc[-1]) if pd.notna(((prices_df["close"] - ma_50) / std_50).iloc[-1]) else 0.0
    if hurst < 0.45 and z_score is not None:
        hurst_direction = 1 if z_score < -1.0 else -1 if z_score > 1.0 else 0
        hurst_conf = min(100.0, (0.55 - hurst) * 180)
    elif hurst > 0.55:
        hurst_direction = -1 if z_score is not None and z_score < 0 else 1 if z_score is not None and z_score > 0 else 0
        hurst_conf = min(100.0, (hurst - 0.45) * 120)
    else:
        hurst_direction = 0
        hurst_conf = 45.0

    sub_factors = [
        _make_sub_factor(
            "zscore_bbands",
            _signal_to_direction(mean_reversion_signal["signal"]) if mean_reversion_signal else 0,
            (mean_reversion_signal["confidence"] * 100.0) if mean_reversion_signal else 0.0,
            MEAN_REVERSION_SUBFACTOR_WEIGHTS["zscore_bbands"],
            completeness=1.0 if mean_reversion_signal else 0.0,
            metrics=(mean_reversion_signal["metrics"] if mean_reversion_signal else {}),
        ),
        rsi_factor,
        _make_sub_factor(
            "stat_arb",
            _signal_to_direction(stat_arb_signal["signal"]) if stat_arb_signal else 0,
            (stat_arb_signal["confidence"] * 100.0) if stat_arb_signal else 0.0,
            MEAN_REVERSION_SUBFACTOR_WEIGHTS["stat_arb"],
            completeness=1.0 if stat_arb_signal else 0.0,
            metrics=(stat_arb_signal["metrics"] if stat_arb_signal else {}),
        ),
        _make_sub_factor(
            "hurst_regime",
            hurst_direction,
            hurst_conf,
            MEAN_REVERSION_SUBFACTOR_WEIGHTS["hurst_regime"],
            completeness=1.0 if len(prices_df) >= 80 else 0.0,
            metrics={"hurst_exponent": hurst, "z_score": z_score},
        ),
    ]
    return aggregate_sub_factors(sub_factors)


def _score_profitability(metrics: FinancialMetrics) -> SubFactor:
    available = 0
    positive = 0
    metric_map = {
        "return_on_equity": (metrics.return_on_equity, 0.15),
        "net_margin": (metrics.net_margin, 0.20),
        "operating_margin": (metrics.operating_margin, 0.15),
    }
    for value, threshold in metric_map.values():
        if value is not None:
            available += 1
            if value >= threshold:
                positive += 1
    if available == 0:
        return _make_sub_factor("profitability", 0, 0.0, FUNDAMENTAL_SUBFACTOR_WEIGHTS["profitability"], completeness=0.0)

    direction = 1 if positive >= 2 else -1 if positive == 0 else 0
    confidence = 100.0 * positive / available if direction >= 0 else 100.0 * (available - positive) / available
    return _make_sub_factor(
        "profitability",
        direction,
        confidence,
        FUNDAMENTAL_SUBFACTOR_WEIGHTS["profitability"],
        completeness=available / 3.0,
        metrics={key: value for key, (value, _) in metric_map.items()},
    )


def _score_growth(metrics_list: list[FinancialMetrics]) -> SubFactor:
    if len(metrics_list) < 4:
        return _make_sub_factor("growth", 0, 0.0, FUNDAMENTAL_SUBFACTOR_WEIGHTS["growth"], completeness=0.0)
    analysis = analyze_growth_trends(metrics_list)
    score = float(analysis["score"])
    direction = 1 if score > 0.6 else -1 if score < 0.4 else 0
    confidence = abs(score - 0.5) * 200.0
    return _make_sub_factor(
        "growth",
        direction,
        confidence,
        FUNDAMENTAL_SUBFACTOR_WEIGHTS["growth"],
        metrics=analysis,
    )


def _score_financial_health(metrics: FinancialMetrics) -> SubFactor:
    analysis = check_financial_health(metrics)
    score = float(analysis["score"])
    direction = 1 if score > 0.6 else -1 if score < 0.4 else 0
    confidence = abs(score - 0.5) * 200.0
    return _make_sub_factor(
        "financial_health",
        direction,
        confidence,
        FUNDAMENTAL_SUBFACTOR_WEIGHTS["financial_health"],
        metrics=analysis,
    )


def _score_growth_valuation(metrics: FinancialMetrics) -> SubFactor:
    analysis = analyze_valuation(metrics)
    score = float(analysis["score"])
    direction = 1 if score > 0.6 else -1 if score == 0 else 0
    confidence = abs(score - 0.5) * 200.0 if score > 0 else 65.0
    return _make_sub_factor(
        "growth_valuation",
        direction,
        confidence,
        FUNDAMENTAL_SUBFACTOR_WEIGHTS["growth_valuation"],
        metrics=analysis,
    )


def _score_industry_pe(metrics: FinancialMetrics, industry_name: str, industry_pe_medians: Optional[dict[str, float]]) -> SubFactor:
    if not industry_name or not industry_pe_medians or metrics.price_to_earnings_ratio is None:
        return _make_sub_factor("industry_pe", 0, 0.0, FUNDAMENTAL_SUBFACTOR_WEIGHTS["industry_pe"], completeness=0.0)
    industry_median = industry_pe_medians.get(industry_name)
    current_pe = metrics.price_to_earnings_ratio
    if industry_median is None or industry_median <= 0:
        return _make_sub_factor("industry_pe", 0, 0.0, FUNDAMENTAL_SUBFACTOR_WEIGHTS["industry_pe"], completeness=0.0)

    premium = current_pe / industry_median
    if premium <= 0.8:
        direction = 1
        confidence = min(100.0, (1.0 - premium) * 250.0)
    elif premium >= 1.2:
        direction = -1
        confidence = min(100.0, (premium - 1.0) * 150.0)
    else:
        direction = 0
        confidence = 50.0
    return _make_sub_factor(
        "industry_pe",
        direction,
        confidence,
        FUNDAMENTAL_SUBFACTOR_WEIGHTS["industry_pe"],
        metrics={"industry": industry_name, "current_pe": current_pe, "industry_pe_median": industry_median, "premium_ratio": premium},
    )


def score_fundamental_strategy(
    ticker: str,
    trade_date: str,
    industry_name: str = "",
    industry_pe_medians: Optional[dict[str, float]] = None,
) -> StrategySignal:
    metrics_list = get_financial_metrics(ticker=ticker, end_date=trade_date, period="ttm", limit=8)
    if not metrics_list:
        return StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={})

    latest = metrics_list[0]
    sub_factors = [
        _score_profitability(latest),
        _score_growth(metrics_list),
        _score_financial_health(latest),
        _score_growth_valuation(latest),
        _score_industry_pe(latest, industry_name, industry_pe_medians),
    ]
    return aggregate_sub_factors(sub_factors)


def _score_news_sentiment(news_items: list[CompanyNews], trade_date: str) -> SubFactor:
    if not news_items:
        return _make_sub_factor("news_sentiment", 0, 0.0, EVENT_SUBFACTOR_WEIGHTS["news_sentiment"], completeness=0.0)

    trade_dt = datetime.strptime(trade_date, "%Y%m%d")
    weighted_score = 0.0
    total_weight = 0.0
    recent_count = 0
    metrics = []
    for item in news_items[:20]:
        item_dt = _safe_date(item.date)
        days_old = (trade_dt - item_dt).days if item_dt else 0
        decay = compute_event_decay(days_old)
        text = f"{item.title or ''} {item.content or ''}".lower()
        pos_hits = sum(1 for word in POSITIVE_NEWS_KEYWORDS if word in text)
        neg_hits = sum(1 for word in NEGATIVE_NEWS_KEYWORDS if word in text)
        if pos_hits > neg_hits:
            direction = 1
            strength = pos_hits - neg_hits
        elif neg_hits > pos_hits:
            direction = -1
            strength = neg_hits - pos_hits
        else:
            direction = 0
            strength = 0
        confidence = min(100.0, 45.0 + strength * 18.0)
        weighted_score += direction * (confidence / 100.0) * decay
        total_weight += decay
        recent_count += 1 if days_old <= 5 else 0
        metrics.append({"title": item.title, "days_old": days_old, "decay": decay, "direction": direction, "confidence": confidence})

    normalized_score = weighted_score / total_weight if total_weight > 0 else 0.0
    direction = 1 if normalized_score > 0.08 else -1 if normalized_score < -0.08 else 0
    confidence = min(100.0, abs(normalized_score) * 130.0)
    completeness = min(1.0, len(news_items[:20]) / 5.0)
    return _make_sub_factor(
        "news_sentiment",
        direction,
        confidence,
        EVENT_SUBFACTOR_WEIGHTS["news_sentiment"],
        completeness=completeness,
        metrics={"weighted_score": normalized_score, "recent_articles": recent_count, "articles": metrics[:5]},
    )


def _score_insider_conviction(trades: list[InsiderTrade]) -> SubFactor:
    if not trades:
        return _make_sub_factor("insider_conviction", 0, 0.0, EVENT_SUBFACTOR_WEIGHTS["insider_conviction"], completeness=0.0)
    analysis = analyze_insider_conviction(trades)
    score = float(analysis["score"])
    direction = 1 if score > 0.6 else -1 if score < 0.4 else 0
    confidence = abs(score - 0.5) * 200.0
    return _make_sub_factor(
        "insider_conviction",
        direction,
        confidence,
        EVENT_SUBFACTOR_WEIGHTS["insider_conviction"],
        metrics=analysis,
    )


def _score_event_freshness(news_items: list[CompanyNews], trade_date: str) -> SubFactor:
    if not news_items:
        return _make_sub_factor("event_freshness", 0, 0.0, EVENT_SUBFACTOR_WEIGHTS["event_freshness"], completeness=0.0)
    trade_dt = datetime.strptime(trade_date, "%Y%m%d")
    latest_dt = _safe_date(news_items[0].date)
    days_old = (trade_dt - latest_dt).days if latest_dt else 0
    decay = compute_event_decay(days_old)
    text = f"{news_items[0].title or ''} {news_items[0].content or ''}".lower()
    pos_hits = sum(1 for word in POSITIVE_NEWS_KEYWORDS if word in text)
    neg_hits = sum(1 for word in NEGATIVE_NEWS_KEYWORDS if word in text)
    direction = 1 if pos_hits > neg_hits else -1 if neg_hits > pos_hits else 0
    confidence = decay * 100.0
    return _make_sub_factor(
        "event_freshness",
        direction,
        confidence,
        EVENT_SUBFACTOR_WEIGHTS["event_freshness"],
        metrics={"days_old": days_old, "decay": decay, "positive_hits": pos_hits, "negative_hits": neg_hits},
    )


def score_event_sentiment_strategy(ticker: str, trade_date: str) -> StrategySignal:
    start_date = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=30)).strftime("%Y-%m-%d")
    end_date = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d")
    news_items = get_company_news(ticker=ticker, start_date=start_date, end_date=end_date, limit=50)
    trades = get_insider_trades(ticker=ticker, end_date=end_date, start_date=start_date, limit=100)

    sub_factors = [
        _score_news_sentiment(news_items, trade_date),
        _score_insider_conviction(trades),
        _score_event_freshness(news_items, trade_date),
    ]
    return aggregate_sub_factors(sub_factors)


def _build_industry_pe_medians(trade_date: str) -> dict[str, float]:
    daily_df = get_daily_basic_batch(trade_date)
    stock_basic = get_all_stock_basic()
    sw_map = get_sw_industry_classification() or {}
    if daily_df is None or daily_df.empty or stock_basic is None or stock_basic.empty:
        return {}

    symbol_to_industry = {}
    for _, row in stock_basic.iterrows():
        ts_code = str(row["ts_code"])
        symbol = str(row["symbol"])
        symbol_to_industry[symbol] = sw_map.get(ts_code, str(row.get("industry", "")))

    grouped: dict[str, list[float]] = defaultdict(list)
    for _, row in daily_df.iterrows():
        pe_ttm = row.get("pe_ttm")
        if pd.isna(pe_ttm) or pe_ttm is None or float(pe_ttm) <= 0:
            continue
        symbol = str(row["ts_code"]).split(".")[0]
        industry = symbol_to_industry.get(symbol, "")
        if industry:
            grouped[industry].append(float(pe_ttm))

    return {industry: median(values) for industry, values in grouped.items() if values}


def score_candidate(
    candidate: CandidateStock,
    trade_date: str,
    industry_pe_medians: Optional[dict[str, float]] = None,
    prices_df: Optional[pd.DataFrame] = None,
) -> dict[str, StrategySignal]:
    prices_df = prices_df if prices_df is not None else _load_price_frame(candidate.ticker, trade_date)
    industry_pe_medians = industry_pe_medians if industry_pe_medians is not None else {}
    return {
        "trend": score_trend_strategy(prices_df),
        "mean_reversion": score_mean_reversion_strategy(prices_df),
        "fundamental": score_fundamental_strategy(candidate.ticker, trade_date, candidate.industry_sw, industry_pe_medians),
        "event_sentiment": score_event_sentiment_strategy(candidate.ticker, trade_date),
    }


def _compute_light_signals(candidate: CandidateStock, trade_date: str) -> tuple[dict[str, StrategySignal], pd.DataFrame]:
    prices_df = _load_price_frame(candidate.ticker, trade_date)
    return {
        "trend": score_trend_strategy(prices_df),
        "mean_reversion": score_mean_reversion_strategy(prices_df),
        "fundamental": _empty_signal(),
        "event_sentiment": _empty_signal(),
    }, prices_df


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
        key=lambda candidate: (candidate.avg_volume_20d, candidate.market_cap),
        reverse=True,
    )


def score_batch(candidates: list[CandidateStock], trade_date: str) -> dict[str, dict[str, StrategySignal]]:
    industry_pe_medians = _build_industry_pe_medians(trade_date)
    results: dict[str, dict[str, StrategySignal]] = {
        candidate.ticker: {
            "trend": _empty_signal(),
            "mean_reversion": _empty_signal(),
            "fundamental": _empty_signal(),
            "event_sentiment": _empty_signal(),
        }
        for candidate in candidates
    }
    provisional_ranking: list[tuple[float, CandidateStock]] = []
    technical_candidates = _rank_candidates_for_technical_stage(candidates)[:TECHNICAL_SCORE_MAX_CANDIDATES]

    for candidate in technical_candidates:
        light_signals, _ = _compute_light_signals(candidate, trade_date)
        results[candidate.ticker] = light_signals
        provisional_ranking.append((_provisional_score(light_signals), candidate))

    for candidate in candidates:
        if candidate.ticker not in {ranked_candidate.ticker for _, ranked_candidate in provisional_ranking}:
            provisional_ranking.append((0.0, candidate))

    ranked_candidates = sorted(
        provisional_ranking,
        key=lambda item: (item[0], item[1].avg_volume_20d, item[1].market_cap),
        reverse=True,
    )

    fundamental_candidates = [
        candidate
        for score, candidate in ranked_candidates
        if score >= HEAVY_SCORE_MIN_PROVISIONAL_SCORE
    ][:FUNDAMENTAL_SCORE_MAX_CANDIDATES]

    for candidate in fundamental_candidates:
        results[candidate.ticker]["fundamental"] = score_fundamental_strategy(
            candidate.ticker,
            trade_date,
            candidate.industry_sw,
            industry_pe_medians,
        )

    event_candidates = fundamental_candidates[:EVENT_SENTIMENT_MAX_CANDIDATES]
    for candidate in event_candidates:
        results[candidate.ticker]["event_sentiment"] = score_event_sentiment_strategy(candidate.ticker, trade_date)

    return results
