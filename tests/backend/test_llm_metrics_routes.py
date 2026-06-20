"""Tests for the LLM metrics summary API route."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.routes.llm_metrics import _collect_metrics, router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    lines = [json.dumps(e, ensure_ascii=False) for e in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_metrics_summary_returns_200_with_empty_logs(tmp_path, monkeypatch):
    """GET /llm-metrics/summary returns 200 and empty structure when no JSONL files exist."""
    monkeypatch.setenv("LLM_METRICS_DIR", str(tmp_path))

    client = TestClient(_make_app())
    response = client.get("/llm-metrics/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["totals"]["calls"] == 0
    assert data["agents"] == []
    assert data["daily_trend"] == []
    assert data["lookback_days"] == 7


def test_metrics_summary_aggregates_agents(tmp_path, monkeypatch):
    """GET /llm-metrics/summary correctly aggregates per-agent metrics."""
    monkeypatch.setenv("LLM_METRICS_DIR", str(tmp_path))

    # Anchor the fixture to today so the entries never age out of the
    # default 7-day lookback window as the calendar advances. A hardcoded
    # historical date silently flips these assertions once it crosses the
    # cutoff (see the sibling test_metrics_summary_respects_lookback_days,
    # whose comment documents the same rot risk).
    today = datetime.now(timezone.utc)
    day = today.strftime("%Y-%m-%d")

    entries = [
        {
            "timestamp": f"{day}T12:00:00",
            "agent_name": "warren_buffett_agent",
            "model_provider": "OpenAI",
            "model_name": "gpt-4o",
            "success": True,
            "duration_ms": 1500.0,
            "prompt_chars": 3000,
            "response_chars": 500,
        },
        {
            "timestamp": f"{day}T12:01:00",
            "agent_name": "warren_buffett_agent",
            "model_provider": "OpenAI",
            "model_name": "gpt-4o",
            "success": True,
            "duration_ms": 2000.0,
            "prompt_chars": 3500,
            "response_chars": 600,
        },
        {
            "timestamp": f"{day}T12:02:00",
            "agent_name": "cathie_wood_agent",
            "model_provider": "Anthropic",
            "model_name": "claude-sonnet",
            "success": False,
            "duration_ms": 5000.0,
            "prompt_chars": 2000,
            "response_chars": 0,
        },
    ]

    # Use a filename pattern that matches today's date
    jsonl = tmp_path / f"llm_metrics_{today.strftime('%Y%m%d')}_120000.jsonl"
    _write_jsonl(jsonl, entries)

    client = TestClient(_make_app())
    data = client.get("/llm-metrics/summary").json()

    assert data["totals"]["calls"] == 3
    assert data["totals"]["successes"] == 2
    assert data["totals"]["errors"] == 1
    assert data["totals"]["sessions_scanned"] == 1

    # Agent-level checks
    agents_by_name = {a["agent_name"]: a for a in data["agents"]}
    buffett = agents_by_name["warren_buffett_agent"]
    assert buffett["calls"] == 2
    assert buffett["successes"] == 2
    assert buffett["errors"] == 0
    assert buffett["avg_duration_ms"] == 1750.0

    cathie = agents_by_name["cathie_wood_agent"]
    assert cathie["calls"] == 1
    assert cathie["errors"] == 1
    assert cathie["p95_duration_ms"] == 5000.0


def test_metrics_summary_respects_lookback_days(tmp_path, monkeypatch):
    """Only JSONL files within the lookback window are included."""
    monkeypatch.setenv("LLM_METRICS_DIR", str(tmp_path))

    # Recent file — anchored to today so the test is time-stable. A hardcoded
    # historical date rots out of the days=7 window as the calendar advances,
    # silently flipping the "included" assertion. "Old" stays a far-past fixed
    # date to guarantee it is always outside the window.
    today = datetime.now(timezone.utc)
    recent_name = f"llm_metrics_{today.strftime('%Y%m%d')}_000000.jsonl"
    recent_ts = today.strftime("%Y-%m-%dT00:00:00")
    recent = tmp_path / recent_name
    _write_jsonl(
        recent,
        [
            {
                "timestamp": recent_ts,
                "agent_name": "agent_a",
                "model_provider": "P",
                "model_name": "M",
                "success": True,
                "duration_ms": 100.0,
                "prompt_chars": 10,
                "response_chars": 5,
            }
        ],
    )

    # Old file (more than 7 days ago)
    old = tmp_path / "llm_metrics_20250520_000000.jsonl"
    _write_jsonl(
        old,
        [
            {
                "timestamp": "2026-05-20T00:00:00",
                "agent_name": "agent_b",
                "model_provider": "P",
                "model_name": "M",
                "success": True,
                "duration_ms": 200.0,
                "prompt_chars": 20,
                "response_chars": 10,
            }
        ],
    )

    client = TestClient(_make_app())
    data = client.get("/llm-metrics/summary?days=7").json()

    # Only the recent file should be included
    assert data["totals"]["calls"] == 1
    assert data["totals"]["sessions_scanned"] == 1
    agents_by_name = {a["agent_name"]: a for a in data["agents"]}
    assert "agent_a" in agents_by_name
    assert "agent_b" not in agents_by_name
