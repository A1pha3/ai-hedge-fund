from src.agents.news_sentiment import Sentiment


def test_sentiment_model_accepts_answer_alias():
    parsed = Sentiment.model_validate({"answer": "negative", "confidence": 100})

    assert parsed.sentiment == "negative"
    assert parsed.confidence == 100