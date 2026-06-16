"""Tests for the LLM metrics heatmap / cost-savings additions (Feature 6.4)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.backend.routes.llm_metrics import (
    _estimate_cost_usd,
    _MODEL_COST_PER_1K_CHARS,
)

# Time-stable anchors for lookback-windowed tests. A hardcoded historical date
# (e.g. 2026-06-01) rots out of the days=30 window as the calendar advances,
# silently dropping entries and flipping assertions. Anchoring to "today - 5
# days" keeps fixtures inside the window regardless of when tests run.
_ANCHOR_DT = datetime.now(timezone.utc) - timedelta(days=5)
RECENT_DATE = _ANCHOR_DT.strftime("%Y-%m-%d")
RECENT_DATE_NEXT = (_ANCHOR_DT + timedelta(days=1)).strftime("%Y-%m-%d")
RECENT_COMPACT = _ANCHOR_DT.strftime("%Y%m%d")
RECENT_TS = f"{RECENT_DATE}T12:00:00"
RECENT_TS_NEXT = f"{RECENT_DATE_NEXT}T12:00:00"
RECENT_TS_MIN = f"{RECENT_DATE}T12:01:00"
RECENT_TS_SEC = f"{RECENT_DATE}T12:02:00"
RECENT_FILE = f"llm_metrics_{RECENT_COMPACT}_120000.jsonl"


def test_estimate_cost_uses_matched_model_rates() -> None:
    # gpt-4o pricing: input 0.005, output 0.015 per 1K chars
    cost = _estimate_cost_usd("gpt-4o-2024-08-06", prompt_chars=1000, response_chars=2000)
    assert cost == round(0.005 + 0.030, 6) == 0.035

    # claude-3-5-sonnet pricing
    cost = _estimate_cost_usd("claude-3-5-sonnet-20241022", prompt_chars=1000, response_chars=1000)
    assert cost == round(0.003 + 0.015, 6) == 0.018

    # deepseek-chat pricing (very cheap)
    cost = _estimate_cost_usd("deepseek-chat", prompt_chars=1000, response_chars=1000)
    assert cost == round(0.00014 + 0.00028, 6) == 0.00042


def test_estimate_cost_falls_back_to_default_rates() -> None:
    # Unknown model → default rates (0.002 / 0.006 per 1K)
    cost = _estimate_cost_usd("some-unknown-model", prompt_chars=1000, response_chars=1000)
    assert cost == round(0.002 + 0.006, 6) == 0.008


def test_estimate_cost_handles_zero_chars() -> None:
    assert _estimate_cost_usd("gpt-4o", 0, 0) == 0.0
    assert _estimate_cost_usd("", 0, 0) == 0.0


def test_estimate_cost_is_case_insensitive() -> None:
    cost_lower = _estimate_cost_usd("gpt-4o", 100, 100)
    cost_upper = _estimate_cost_usd("GPT-4O", 100, 100)
    assert cost_lower == cost_upper


def test_known_model_rates_are_reasonable() -> None:
    """Sanity check: haiku < sonnet < opus, deepseek < gpt-3.5."""
    haiku = _MODEL_COST_PER_1K_CHARS["claude-3-haiku"]["output"]
    sonnet = _MODEL_COST_PER_1K_CHARS["claude-3-5-sonnet"]["output"]
    opus = _MODEL_COST_PER_1K_CHARS["claude-3-opus"]["output"]
    assert haiku < sonnet < opus
    deepseek = _MODEL_COST_PER_1K_CHARS["deepseek-chat"]["output"]
    gpt35 = _MODEL_COST_PER_1K_CHARS["gpt-3.5-turbo"]["output"]
    assert deepseek < gpt35


# ---------------------------------------------------------------------------
# Integration tests for the /llm-metrics/summary heatmap fields
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    lines = [json.dumps(e, ensure_ascii=False) for e in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_summary_includes_provider_aggregation(tmp_path, monkeypatch) -> None:
    """The new /llm-metrics/summary response includes a `providers` field."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.backend.routes.llm_metrics import router

    monkeypatch.setenv("LLM_METRICS_DIR", str(tmp_path))
    _write_jsonl(
        tmp_path / RECENT_FILE,
        [
            {
                "timestamp": RECENT_TS,
                "agent_name": "warren_buffett",
                "model_provider": "openai",
                "model_name": "gpt-4o",
                "duration_ms": 1500,
                "success": True,
                "prompt_chars": 2000,
                "response_chars": 1500,
            },
            {
                "timestamp": RECENT_TS_MIN,
                "agent_name": "warren_buffett",
                "model_provider": "openai",
                "model_name": "gpt-4o",
                "duration_ms": 2200,
                "success": False,
                "prompt_chars": 2000,
                "response_chars": 0,
            },
            {
                "timestamp": RECENT_TS_SEC,
                "agent_name": "charlie_munger",
                "model_provider": "anthropic",
                "model_name": "claude-3-5-sonnet",
                "duration_ms": 1800,
                "success": True,
                "prompt_chars": 3000,
                "response_chars": 2000,
            },
        ],
    )

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/llm-metrics/summary?days=30")
    assert response.status_code == 200
    payload = response.json()

    assert "providers" in payload
    assert "estimated_cost_usd" in payload["totals"]
    providers_by_name = {p["provider"]: p for p in payload["providers"]}
    assert "openai" in providers_by_name
    assert "anthropic" in providers_by_name
    # openai had 1 error out of 2 calls
    assert providers_by_name["openai"]["calls"] == 2
    assert providers_by_name["openai"]["errors"] == 1
    assert providers_by_name["openai"]["error_rate"] == 0.5
    # anthropic had 0 errors
    assert providers_by_name["anthropic"]["error_rate"] == 0.0


def test_summary_top_agents_by_cost_sorted_descending(tmp_path, monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.backend.routes.llm_metrics import router

    monkeypatch.setenv("LLM_METRICS_DIR", str(tmp_path))
    # warren_buffett uses gpt-4o (expensive), charlie_munger uses deepseek (cheap).
    _write_jsonl(
        tmp_path / RECENT_FILE,
        [
            {
                "timestamp": RECENT_TS,
                "agent_name": "warren_buffett",
                "model_provider": "openai",
                "model_name": "gpt-4o",
                "duration_ms": 1000,
                "success": True,
                "prompt_chars": 5000,
                "response_chars": 5000,
            },
            {
                "timestamp": RECENT_TS_MIN,
                "agent_name": "charlie_munger",
                "model_provider": "deepseek",
                "model_name": "deepseek-chat",
                "duration_ms": 800,
                "success": True,
                "prompt_chars": 5000,
                "response_chars": 5000,
            },
        ],
    )

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    payload = client.get("/llm-metrics/summary?days=30").json()
    top = payload["top_agents_by_cost"]
    assert len(top) >= 2
    # gpt-4o agent should be more expensive than deepseek agent
    costs = [a["estimated_cost_usd"] for a in top]
    assert costs == sorted(costs, reverse=True)
    # First entry should be warren_buffett (uses gpt-4o)
    assert top[0]["agent_name"] == "warren_buffett"
    assert top[0]["estimated_cost_usd"] > top[1]["estimated_cost_usd"]


def test_summary_top_providers_by_latency_sorted_descending(tmp_path, monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.backend.routes.llm_metrics import router

    monkeypatch.setenv("LLM_METRICS_DIR", str(tmp_path))
    _write_jsonl(
        tmp_path / RECENT_FILE,
        [
            {
                "timestamp": RECENT_TS,
                "agent_name": "a1",
                "model_provider": "slow_provider",
                "model_name": "gpt-4o",
                "duration_ms": 5000,
                "success": True,
                "prompt_chars": 100,
                "response_chars": 100,
            },
            {
                "timestamp": RECENT_TS_MIN,
                "agent_name": "a2",
                "model_provider": "fast_provider",
                "model_name": "deepseek-chat",
                "duration_ms": 500,
                "success": True,
                "prompt_chars": 100,
                "response_chars": 100,
            },
        ],
    )

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    payload = client.get("/llm-metrics/summary?days=30").json()
    top = payload["top_providers_by_latency"]
    assert len(top) == 2
    # Slowest first
    assert top[0]["provider"] == "slow_provider"
    assert top[0]["avg_duration_ms"] > top[1]["avg_duration_ms"]


def test_summary_daily_provider_heatmap_populated(tmp_path, monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.backend.routes.llm_metrics import router

    monkeypatch.setenv("LLM_METRICS_DIR", str(tmp_path))
    _write_jsonl(
        tmp_path / RECENT_FILE,
        [
            {
                "timestamp": RECENT_TS,
                "agent_name": "a1",
                "model_provider": "openai",
                "model_name": "gpt-4o",
                "duration_ms": 1000,
                "success": True,
                "prompt_chars": 100,
                "response_chars": 100,
            },
            {
                "timestamp": RECENT_TS_NEXT,
                "agent_name": "a2",
                "model_provider": "openai",
                "model_name": "gpt-4o",
                "duration_ms": 1100,
                "success": False,
                "prompt_chars": 100,
                "response_chars": 100,
            },
        ],
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    payload = client.get("/llm-metrics/summary?days=30").json()
    heat = payload["daily_provider"]
    assert len(heat) == 2
    assert heat[0]["date"] == RECENT_DATE
    assert heat[0]["providers"][0]["provider"] == "openai"
    assert heat[0]["providers"][0]["calls"] == 1
    assert heat[1]["providers"][0]["errors"] == 1


def test_cost_savings_suggestion_flags_outlier_agents(tmp_path, monkeypatch) -> None:
    """An agent whose cost-per-call is >= 2x the median should be flagged."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.backend.routes.llm_metrics import router

    monkeypatch.setenv("LLM_METRICS_DIR", str(tmp_path))
    _write_jsonl(
        tmp_path / RECENT_FILE,
        [
            # Cheap: deepseek, 1000 in + 1000 out
            {
                "timestamp": RECENT_TS,
                "agent_name": "cheap_a",
                "model_provider": "deepseek",
                "model_name": "deepseek-chat",
                "duration_ms": 100,
                "success": True,
                "prompt_chars": 1000,
                "response_chars": 1000,
            },
            {
                "timestamp": RECENT_TS_MIN,
                "agent_name": "cheap_b",
                "model_provider": "deepseek",
                "model_name": "deepseek-chat",
                "duration_ms": 100,
                "success": True,
                "prompt_chars": 1000,
                "response_chars": 1000,
            },
            # Expensive: opus, 10000 in + 10000 out
            {
                "timestamp": RECENT_TS_SEC,
                "agent_name": "expensive_one",
                "model_provider": "anthropic",
                "model_name": "claude-3-opus",
                "duration_ms": 5000,
                "success": True,
                "prompt_chars": 10000,
                "response_chars": 10000,
            },
        ],
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    payload = client.get("/llm-metrics/summary?days=30").json()
    suggestions = payload["cost_savings_suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["agent_name"] == "expensive_one"
    assert suggestions[0]["potential_savings_pct"] > 0


def test_cost_savings_suggestion_empty_when_no_outliers(tmp_path, monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.backend.routes.llm_metrics import router

    monkeypatch.setenv("LLM_METRICS_DIR", str(tmp_path))
    _write_jsonl(
        tmp_path / RECENT_FILE,
        [
            {
                "timestamp": RECENT_TS,
                "agent_name": "a1",
                "model_provider": "openai",
                "model_name": "gpt-4o",
                "duration_ms": 1000,
                "success": True,
                "prompt_chars": 1000,
                "response_chars": 1000,
            },
            {
                "timestamp": RECENT_TS_MIN,
                "agent_name": "a2",
                "model_provider": "openai",
                "model_name": "gpt-4o",
                "duration_ms": 1100,
                "success": True,
                "prompt_chars": 1000,
                "response_chars": 1000,
            },
        ],
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    payload = client.get("/llm-metrics/summary?days=30").json()
    # Both agents use the same model, so no outlier
    assert payload["cost_savings_suggestions"] == []
