import json

from langchain_core.messages import HumanMessage
from pydantic import AliasChoices, BaseModel, Field
from typing_extensions import Literal

from src.agents.news_sentiment_helpers import (
    _aggregate_news_signals,
    _build_news_articles_info,
    _build_news_reasoning,
    _build_news_sentiment_details,
    _classify_news_articles,
    _select_articles_for_sentiment_analysis,
    _serialize_news_reasoning,
    _summarize_news_signals,
)
from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import get_company_news
from src.utils.api_key import get_api_key_from_state
from src.utils.llm import call_llm
from src.utils.progress import progress


class Sentiment(BaseModel):
    """Represents the sentiment of a news article."""

    sentiment: Literal["positive", "negative", "neutral"] = Field(validation_alias=AliasChoices("sentiment", "answer"))
    confidence: int = Field(description="Confidence 0-100")


def news_sentiment_agent(state: AgentState, agent_id: str = "news_sentiment_agent"):
    """
    Analyzes news sentiment for a list of tickers and generates trading signals.

    This agent fetches company news, uses an LLM to classify the sentiment of articles
    with missing sentiment data, and then aggregates the sentiments to produce an
    overall signal (bullish, bearish, or neutral) and a confidence score for each ticker.

    Args:
        state: The current state of the agent graph.
        agent_id: The ID of the agent.

    Returns:
        A dictionary containing the updated state with the agent's analysis.
    """
    data = state.get("data", {})
    end_date = data.get("end_date")
    tickers = data.get("tickers")
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")
    sentiment_analysis = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Fetching company news")
        company_news = get_company_news(
            ticker=ticker,
            end_date=end_date,
            limit=100,
            api_key=api_key,
        )

        news_signals = []
        llm_sentiments = {}
        sentiment_confidences = {}
        sentiments_classified_by_llm = 0

        if company_news:
            recent_articles = company_news[:10]
            articles_to_analyze = _select_articles_for_sentiment_analysis(recent_articles)

            if articles_to_analyze:
                progress.update_status(agent_id, ticker, f"Analyzing sentiment for {len(articles_to_analyze)} articles")
                llm_sentiments, sentiment_confidences, sentiments_classified_by_llm = _classify_news_articles(
                    ticker=ticker,
                    agent_id=agent_id,
                    state=state,
                    articles_to_analyze=articles_to_analyze,
                    sentiment_model=Sentiment,
                    llm_callable=call_llm,
                    progress_callback=progress.update_status,
                )

            news_signals = _aggregate_news_signals(company_news, llm_sentiments)

        progress.update_status(agent_id, ticker, "Aggregating signals")

        signal_summary = _summarize_news_signals(news_signals)
        overall_signal = signal_summary["overall_signal"]
        bullish_signals = signal_summary["bullish_signals"]
        bearish_signals = signal_summary["bearish_signals"]
        neutral_signals = signal_summary["neutral_signals"]
        total_signals = signal_summary["total_signals"]
        confidence = _calculate_confidence_score(
            sentiment_confidences=sentiment_confidences,
            company_news=company_news,
            overall_signal=overall_signal,
            bullish_signals=bullish_signals,
            bearish_signals=bearish_signals,
            total_signals=total_signals,
        )
        details = _build_news_sentiment_details(
            overall_signal=overall_signal,
            bullish_signals=bullish_signals,
            bearish_signals=bearish_signals,
            neutral_signals=neutral_signals,
            total_signals=total_signals,
            sentiments_classified_by_llm=sentiments_classified_by_llm,
            confidence=confidence,
        )
        articles_info = _build_news_articles_info(company_news, llm_sentiments) if company_news else []
        reasoning = _build_news_reasoning(
            overall_signal=overall_signal,
            confidence=confidence,
            details=details,
            bullish_signals=bullish_signals,
            bearish_signals=bearish_signals,
            neutral_signals=neutral_signals,
            total_signals=total_signals,
            sentiments_classified_by_llm=sentiments_classified_by_llm,
            articles_info=articles_info,
        )

        sentiment_analysis[ticker] = {
            "signal": overall_signal,
            "confidence": confidence,
            "reasoning": reasoning,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=_serialize_news_reasoning(reasoning))

    message = HumanMessage(
        content=json.dumps(sentiment_analysis),
        name=agent_id,
    )

    if state.get("metadata", {}).get("show_reasoning"):
        show_agent_reasoning(sentiment_analysis, "News Sentiment Analysis Agent")

    if "analyst_signals" not in state["data"]:
        state["data"]["analyst_signals"] = {}
    state["data"]["analyst_signals"][agent_id] = sentiment_analysis

    progress.update_status(agent_id, None, "Done")

    return {
        "messages": [message],
        "data": state["data"],
    }


def _calculate_confidence_score(sentiment_confidences: dict, company_news: list, overall_signal: str, bullish_signals: int, bearish_signals: int, total_signals: int) -> float:
    """
    Calculate confidence score for a sentiment signal.

    Uses a weighted approach combining LLM confidence scores (70%) with
    signal proportion (30%) when LLM classifications are available.

    Args:
        sentiment_confidences: Dictionary mapping news article IDs to confidence scores.
        company_news: List of CompanyNews objects.
        overall_signal: The overall sentiment signal ("bullish", "bearish", or "neutral").
        bullish_signals: Count of bullish signals.
        bearish_signals: Count of bearish signals.
        total_signals: Total number of signals.

    Returns:
        Confidence score as a float between 0 and 100.
    """
    if total_signals == 0:
        return 0.0

    # Calculate weighted confidence using LLM confidence scores when available
    if sentiment_confidences:
        # sentiment_confidences now uses article index as key (int)
        # Get all LLM confidence scores (they are already stock-specific classified)
        llm_confidences = list(sentiment_confidences.values())

        if llm_confidences:
            # Weight: 70% from LLM confidence scores, 30% from signal proportion
            avg_llm_confidence = sum(llm_confidences) / len(llm_confidences)
            signal_proportion = (max(bullish_signals, bearish_signals) / total_signals) * 100
            return round(0.7 * avg_llm_confidence + 0.3 * signal_proportion, 2)

    # Fallback to proportion-based confidence
    return round((max(bullish_signals, bearish_signals) / total_signals) * 100, 2)
