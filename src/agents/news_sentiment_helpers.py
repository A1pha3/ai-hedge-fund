import json
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from src.data.models import CompanyNews


def _select_articles_for_sentiment_analysis(recent_articles: list[CompanyNews], max_articles: int = 5) -> list[tuple[int, CompanyNews]]:
    articles_without_sentiment = [(i, news) for i, news in enumerate(recent_articles) if news.sentiment is None]
    articles_with_sentiment = [(i, news) for i, news in enumerate(recent_articles) if news.sentiment is not None]
    return (articles_without_sentiment + articles_with_sentiment)[:max_articles]


def _build_news_sentiment_prompt(ticker: str, title: str) -> str:
    return (
        f"Please analyze the sentiment of the following news headline "
        f"with the following context: "
        f"The stock is {ticker}. "
        f"Determine if sentiment is 'positive', 'negative', or 'neutral' for the stock {ticker} only. "
        f"Also provide a confidence score for your prediction from 0 to 100. "
        f"Respond in JSON format.\n\n"
        f"Headline: {title}"
    )


def _classify_news_articles(
    *,
    ticker: str,
    agent_id: str,
    state: dict[str, Any],
    articles_to_analyze: list[tuple[int, CompanyNews]],
    sentiment_model: type,
    llm_callable: Callable[..., Any],
    progress_callback: Callable[..., None],
) -> tuple[dict[int, str], dict[int, int], int]:
    llm_sentiments: dict[int, str] = {}
    sentiment_confidences: dict[int, int] = {}
    sentiments_classified_by_llm = 0

    for idx, (article_idx, news) in enumerate(articles_to_analyze):
        progress_callback(agent_id, ticker, f"Analyzing sentiment for article {idx + 1} of {len(articles_to_analyze)}")
        response = llm_callable(
            _build_news_sentiment_prompt(ticker, news.title),
            sentiment_model,
            agent_name=agent_id,
            state=state,
        )
        if response:
            llm_sentiments[article_idx] = response.sentiment.lower()
            sentiment_confidences[article_idx] = response.confidence
        else:
            llm_sentiments[article_idx] = "neutral"
            sentiment_confidences[article_idx] = 0
        sentiments_classified_by_llm += 1

    return llm_sentiments, sentiment_confidences, sentiments_classified_by_llm


def _aggregate_news_signals(company_news: list[CompanyNews], llm_sentiments: dict[int, str]) -> list[str]:
    all_sentiments = []
    for index, news in enumerate(company_news):
        if index in llm_sentiments:
            all_sentiments.append(llm_sentiments[index])
        elif news.sentiment:
            all_sentiments.append(news.sentiment)

    sentiment = pd.Series(all_sentiments).dropna()
    return np.where(sentiment == "negative", "bearish", np.where(sentiment == "positive", "bullish", "neutral")).tolist()


def _summarize_news_signals(news_signals: list[str]) -> dict[str, Any]:
    bullish_signals = news_signals.count("bullish")
    bearish_signals = news_signals.count("bearish")
    neutral_signals = news_signals.count("neutral")

    if bullish_signals > bearish_signals:
        overall_signal = "bullish"
    elif bearish_signals > bullish_signals:
        overall_signal = "bearish"
    else:
        overall_signal = "neutral"

    return {
        "overall_signal": overall_signal,
        "bullish_signals": bullish_signals,
        "bearish_signals": bearish_signals,
        "neutral_signals": neutral_signals,
        "total_signals": len(news_signals),
    }


def _build_news_sentiment_details(
    *,
    overall_signal: str,
    bullish_signals: int,
    bearish_signals: int,
    neutral_signals: int,
    total_signals: int,
    sentiments_classified_by_llm: int,
    confidence: float,
) -> str:
    if total_signals == 0:
        return "未找到相关新闻文章，无法进行情感分析。"

    details = (
        f"共分析 {total_signals} 篇新闻文章，其中看涨 {bullish_signals} 篇、看跌 {bearish_signals} 篇、中性 {neutral_signals} 篇。"
        f"通过 LLM 对 {sentiments_classified_by_llm} 篇文章进行了深度情感分类。"
    )
    if overall_signal == "bullish":
        details += f"正面新闻占比 {bullish_signals / total_signals * 100:.0f}%，整体新闻情绪偏向积极，发出看涨信号。"
    elif overall_signal == "bearish":
        details += f"负面新闻占比 {bearish_signals / total_signals * 100:.0f}%，整体新闻情绪偏向消极，发出看跌信号。"
    else:
        details += "正面与负面新闻比例均衡，整体情绪中性。"
    details += f"综合置信度为 {confidence:.1f}%。"
    return details


def _build_news_articles_info(company_news: list[CompanyNews], llm_sentiments: dict[int, str]) -> list[dict[str, str]]:
    sentiment_map = {"positive": "正面", "negative": "负面", "neutral": "中性"}
    articles_info = []

    for index, news in enumerate(company_news[:10]):
        final_sentiment = llm_sentiments.get(index, news.sentiment) or "neutral"
        article = {
            "title": news.title,
            "url": news.url,
            "date": news.date[:10] if news.date else "",
            "source": news.source or news.author or "",
            "sentiment": sentiment_map.get(final_sentiment, final_sentiment),
        }
        if news.content:
            article["summary"] = news.content[:100] + ("..." if len(news.content) > 100 else "")
        articles_info.append(article)

    return articles_info


def _build_news_reasoning(
    *,
    overall_signal: str,
    confidence: float,
    details: str,
    bullish_signals: int,
    bearish_signals: int,
    neutral_signals: int,
    total_signals: int,
    sentiments_classified_by_llm: int,
    articles_info: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "news_sentiment": {
            "signal": overall_signal,
            "confidence": confidence,
            "details": details,
            "metrics": {
                "total_articles": total_signals,
                "bullish_articles": bullish_signals,
                "bearish_articles": bearish_signals,
                "neutral_articles": neutral_signals,
                "articles_classified_by_llm": sentiments_classified_by_llm,
            },
            "articles": articles_info,
        }
    }


def _serialize_news_reasoning(reasoning: dict[str, Any]) -> str:
    return json.dumps(reasoning, indent=4)
