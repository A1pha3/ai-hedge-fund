from __future__ import annotations

import json

from scripts.summarize_llm_metrics import summarize


def test_summarize_llm_metrics_includes_observability_dimensions(tmp_path):
    jsonl_path = tmp_path / "llm_metrics.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "model_provider": "MiniMax",
                        "model_name": "MiniMax-M2.7",
                        "route_id": "MiniMax:default",
                        "transport_family": "openai-compatible",
                        "agent_name": "agent_a",
                        "trade_date": "20260320",
                        "pipeline_stage": "daily_pipeline_post_market",
                        "model_tier": "fast",
                        "success": True,
                        "is_rate_limit": False,
                        "used_fallback": False,
                        "duration_ms": 1200.0,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "model_provider": "Volcengine",
                        "model_name": "doubao-seed-2.0-pro",
                        "route_id": "Volcengine:coding_plan",
                        "transport_family": "openai-compatible",
                        "agent_name": "agent_b",
                        "trade_date": "20260320",
                        "pipeline_stage": "daily_pipeline_post_market",
                        "model_tier": "fast",
                        "success": False,
                        "is_rate_limit": True,
                        "used_fallback": True,
                        "duration_ms": 2200.0,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "model_provider": "MiniMax",
                        "model_name": "MiniMax-M2.7",
                        "route_id": "MiniMax:default",
                        "transport_family": "openai-compatible",
                        "agent_name": "agent_c",
                        "trade_date": "20260321",
                        "pipeline_stage": "daily_pipeline_post_market",
                        "model_tier": "precise",
                        "success": True,
                        "is_rate_limit": False,
                        "used_fallback": False,
                        "duration_ms": 3200.0,
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = summarize(jsonl_path)

    assert summary["totals"]["attempts"] == 3
    assert summary["totals"]["fallback_attempts"] == 1
    assert summary["providers"]["Volcengine"]["rate_limit_errors"] == 1
    assert summary["trade_dates"]["20260320"]["attempts"] == 2
    assert summary["pipeline_stages"]["daily_pipeline_post_market"]["attempts"] == 3
    assert summary["model_tiers"]["fast"]["attempts"] == 2
    assert summary["context_breakdown"] == [
        {
            "trade_date": "20260320",
            "pipeline_stage": "daily_pipeline_post_market",
            "model_tier": "fast",
            "provider": "MiniMax",
            "attempts": 1,
            "successes": 1,
            "errors": 0,
            "rate_limit_errors": 0,
            "fallback_attempts": 0,
            "total_duration_ms": 1200.0,
            "avg_duration_ms": 1200.0,
        },
        {
            "trade_date": "20260320",
            "pipeline_stage": "daily_pipeline_post_market",
            "model_tier": "fast",
            "provider": "Volcengine",
            "attempts": 1,
            "successes": 0,
            "errors": 1,
            "rate_limit_errors": 1,
            "fallback_attempts": 1,
            "total_duration_ms": 2200.0,
            "avg_duration_ms": 2200.0,
        },
        {
            "trade_date": "20260321",
            "pipeline_stage": "daily_pipeline_post_market",
            "model_tier": "precise",
            "provider": "MiniMax",
            "attempts": 1,
            "successes": 1,
            "errors": 0,
            "rate_limit_errors": 0,
            "fallback_attempts": 0,
            "total_duration_ms": 3200.0,
            "avg_duration_ms": 3200.0,
        },
    ]