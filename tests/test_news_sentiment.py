import json
from types import SimpleNamespace

import src.agents.news_sentiment as news_sentiment_module
from src.agents.news_sentiment import Sentiment, news_sentiment_agent
from src.data.models import CompanyNews


def test_sentiment_model_accepts_answer_alias():
    parsed = Sentiment.model_validate({"answer": "negative", "confidence": 100})

    assert parsed.sentiment == "negative"
    assert parsed.confidence == 100


def test_news_sentiment_agent_returns_neutral_when_no_articles(monkeypatch):
    monkeypatch.setattr(news_sentiment_module.progress, "update_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(news_sentiment_module, "get_api_key_from_state", lambda state, key: "fake")
    monkeypatch.setattr(news_sentiment_module, "get_company_news", lambda **kwargs: [])

    state = {
        "messages": [],
        "metadata": {"show_reasoning": False},
        "data": {"tickers": ["000001"], "end_date": "2026-04-10", "analyst_signals": {}},
    }

    result = news_sentiment_agent(state)
    analysis = result["data"]["analyst_signals"]["news_sentiment_agent"]["000001"]

    assert analysis == {
        "signal": "neutral",
        "confidence": 0.0,
        "reasoning": {
            "news_sentiment": {
                "signal": "neutral",
                "confidence": 0.0,
                "details": "未找到相关新闻文章，无法进行情感分析。",
                "metrics": {
                    "total_articles": 0,
                    "bullish_articles": 0,
                    "bearish_articles": 0,
                    "neutral_articles": 0,
                    "articles_classified_by_llm": 0,
                },
                "articles": [],
            }
        },
    }
    assert json.loads(result["messages"][0].content) == {"000001": analysis}


def test_news_sentiment_agent_preserves_llm_overrides_and_neutral_fallback(monkeypatch):
    monkeypatch.setattr(news_sentiment_module.progress, "update_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(news_sentiment_module, "get_api_key_from_state", lambda state, key: "fake")
    monkeypatch.setattr(
        news_sentiment_module,
        "get_company_news",
        lambda **kwargs: [
            CompanyNews(ticker="000001", title="Strong earnings beat expectations", author="A", source="S1", date="2026-04-10T09:00:00", url="u1", sentiment=None, content="A" * 120),
            CompanyNews(ticker="000001", title="Regulatory pressure increases", author="B", source="S2", date="2026-04-09T09:00:00", url="u2", sentiment="negative", content="B" * 50),
            CompanyNews(ticker="000001", title="Product launch gains traction", author="C", source="S3", date="2026-04-08T09:00:00", url="u3", sentiment="positive", content=None),
        ],
    )
    responses = iter(
        [
            SimpleNamespace(sentiment="positive", confidence=88),
            None,
            SimpleNamespace(sentiment="negative", confidence=64),
        ]
    )
    monkeypatch.setattr(news_sentiment_module, "call_llm", lambda *args, **kwargs: next(responses))

    state = {
        "messages": [],
        "metadata": {"show_reasoning": False},
        "data": {"tickers": ["000001"], "end_date": "2026-04-10", "analyst_signals": {}},
    }

    result = news_sentiment_agent(state)
    analysis = result["data"]["analyst_signals"]["news_sentiment_agent"]["000001"]
    reasoning = analysis["reasoning"]["news_sentiment"]

    assert analysis["signal"] == "neutral"
    assert analysis["confidence"] == 45.47
    assert reasoning["details"] == "共分析 3 篇新闻文章，其中看涨 1 篇、看跌 1 篇、中性 1 篇。通过 LLM 对 3 篇文章进行了深度情感分类。正面与负面新闻比例均衡，整体情绪中性。综合置信度为 45.5%。"
    assert reasoning["metrics"] == {
        "total_articles": 3,
        "bullish_articles": 1,
        "bearish_articles": 1,
        "neutral_articles": 1,
        "articles_classified_by_llm": 3,
    }
    assert reasoning["articles"] == [
        {
            "title": "Strong earnings beat expectations",
            "url": "u1",
            "date": "2026-04-10",
            "source": "S1",
            "sentiment": "正面",
            "summary": "A" * 100 + "...",
        },
        {
            "title": "Regulatory pressure increases",
            "url": "u2",
            "date": "2026-04-09",
            "source": "S2",
            "sentiment": "中性",
            "summary": "B" * 50,
        },
        {
            "title": "Product launch gains traction",
            "url": "u3",
            "date": "2026-04-08",
            "source": "S3",
            "sentiment": "负面",
        },
    ]
