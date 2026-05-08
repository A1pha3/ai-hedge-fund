from __future__ import annotations

from src.execution.daily_pipeline import DailyPipeline


def test_daily_pipeline_defaults_btst_fast_selected_analysts_for_short_trade_only() -> None:
    pipeline = DailyPipeline(
        agent_runner=lambda tickers, trade_date, model_tier: {},
        target_mode="short_trade_only",
    )

    assert pipeline._resolve_selected_analysts_for_tier("fast") == [
        "technical_analyst",
        "sentiment_analyst",
    ]
