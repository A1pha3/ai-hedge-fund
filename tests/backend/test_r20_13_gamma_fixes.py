"""Regression tests for R20.13 Gamma sub-issue fixes.

Covers 6 fixes:
1. attribution.py float() ValueError -> HTTPException 400
2. replay_artifacts.py unprotected endpoints -> try/except + 500
3. language_models.py ollama isolation -> cloud models still return
4. api.py _make_api_request timeout=30
5. llm_metrics.py _collect_metrics TTL cache
6. graph/state.py show_agent_reasoning TypeError catch
"""

from __future__ import annotations

import json
import time as time_module
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ===========================================================================
# Fix 1: attribution.py float() ValueError -> HTTPException 400
# ===========================================================================


def test_attribution_get_returns_400_on_non_numeric_returns():
    """GET /portfolio/attribution with non-numeric 'returns' returns 400, not 500."""
    from app.backend.routes.attribution import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get(
        "/portfolio/attribution",
        params={
            "start": "2026-01-01",
            "end": "2026-06-01",
            "tickers": "AAPL",
            "returns": "abc",
            "weights": "1000",
            "total_value": "1000",
        },
    )
    assert response.status_code == 400
    assert "numeric" in response.json()["detail"].lower()


def test_attribution_get_returns_400_on_non_numeric_weights():
    """GET /portfolio/attribution with non-numeric 'weights' returns 400, not 500."""
    from app.backend.routes.attribution import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get(
        "/portfolio/attribution",
        params={
            "start": "2026-01-01",
            "end": "2026-06-01",
            "tickers": "AAPL",
            "returns": "0.1",
            "weights": "xyz",
            "total_value": "1000",
        },
    )
    assert response.status_code == 400
    assert "numeric" in response.json()["detail"].lower()


def test_attribution_get_returns_400_on_non_numeric_benchmark_weights():
    """GET /portfolio/attribution with non-numeric 'benchmark_weights_csv' returns 400."""
    from app.backend.routes.attribution import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get(
        "/portfolio/attribution",
        params={
            "start": "2026-01-01",
            "end": "2026-06-01",
            "tickers": "AAPL",
            "returns": "0.1",
            "weights": "1000",
            "total_value": "1000",
            "benchmark_weights_csv": "bad",
        },
    )
    assert response.status_code == 400
    assert "numeric" in response.json()["detail"].lower()


def test_attribution_get_returns_400_on_non_numeric_benchmark_returns():
    """GET /portfolio/attribution with non-numeric 'benchmark_returns_csv' returns 400."""
    from app.backend.routes.attribution import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get(
        "/portfolio/attribution",
        params={
            "start": "2026-01-01",
            "end": "2026-06-01",
            "tickers": "AAPL",
            "returns": "0.1",
            "weights": "1000",
            "total_value": "1000",
            "benchmark_returns_csv": "oops",
        },
    )
    assert response.status_code == 400
    assert "numeric" in response.json()["detail"].lower()


# ===========================================================================
# Fix 2: replay_artifacts.py unprotected endpoints -> try/except + 500
# ===========================================================================

def test_list_replay_artifacts_returns_500_on_service_failure(monkeypatch):
    """GET /replay-artifacts/ returns 500 when service.list_replays() raises."""
    from app.backend.routes.replay_artifacts import router
    from app.backend.services.replay_artifact_service import ReplayArtifactService

    def _boom(self):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(ReplayArtifactService, "list_replays", _boom)

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/replay-artifacts/")
    assert response.status_code == 500
    assert "Internal server error" in response.json()["detail"]


def test_get_replay_feedback_activity_returns_500_on_service_failure(monkeypatch):
    """GET /replay-artifacts/feedback-activity returns 500 on service failure."""
    from app.backend.routes.replay_artifacts import router
    from app.backend.services.replay_artifact_service import ReplayArtifactService

    def _boom(self, **kwargs):
        raise RuntimeError("db gone")

    monkeypatch.setattr(ReplayArtifactService, "get_feedback_activity", _boom)

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/replay-artifacts/feedback-activity")
    assert response.status_code == 500
    assert "Internal server error" in response.json()["detail"]


def test_get_replay_workflow_queue_returns_500_on_service_failure(monkeypatch):
    """GET /replay-artifacts/workflow-queue returns 500 on service failure."""
    from app.backend.routes.replay_artifacts import router
    from app.backend.services.replay_artifact_service import ReplayArtifactService

    def _boom(self, **kwargs):
        raise RuntimeError("queue broken")

    monkeypatch.setattr(ReplayArtifactService, "list_workflow_queue", _boom)

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/replay-artifacts/workflow-queue")
    assert response.status_code == 500
    assert "Internal server error" in response.json()["detail"]


# ===========================================================================
# Fix 3: language_models.py ollama isolation -> cloud models still return
# ===========================================================================

def test_language_models_returns_cloud_models_when_ollama_fails(monkeypatch):
    """GET /language-models/ returns cloud models even if ollama fails."""
    from app.backend.routes import language_models as lm_module

    # Mock get_models_list to return a known cloud model
    monkeypatch.setattr(
        lm_module,
        "get_models_list",
        lambda: [{"display_name": "GPT-4o", "model_name": "gpt-4o", "provider": "OpenAI"}],
    )
    # Mock get_default_model_config
    monkeypatch.setattr(
        lm_module,
        "get_default_model_config",
        lambda: ("gpt-4o", "OpenAI"),
    )
    # Mock ollama service to raise
    mock_service = MagicMock()
    mock_service.get_available_models = MagicMock(side_effect=ConnectionError("ollama not running"))
    monkeypatch.setattr(lm_module, "ollama_service", mock_service)

    from app.backend.routes.language_models import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/language-models/")
    assert response.status_code == 200
    models = response.json()["models"]
    assert len(models) >= 1
    assert any(m["model_name"] == "gpt-4o" for m in models)


# ===========================================================================
# Fix 4: api.py _make_api_request timeout=30
# ===========================================================================

def test_make_api_request_passes_timeout(monkeypatch):
    """_make_api_request passes timeout to requests.get."""
    import src.tools.api as api_module

    captured_kwargs = {}

    def fake_get(url, **kwargs):
        captured_kwargs.update(kwargs)
        return SimpleNamespace(status_code=200, json=lambda: {})

    monkeypatch.setattr("requests.get", fake_get)

    api_module._make_api_request("https://example.com", {}, timeout=10.0)

    assert captured_kwargs.get("timeout") == 10.0


def test_make_api_request_default_timeout_is_30(monkeypatch):
    """_make_api_request defaults to timeout=30 when not specified."""
    import src.tools.api as api_module

    captured_kwargs = {}

    def fake_get(url, **kwargs):
        captured_kwargs.update(kwargs)
        return SimpleNamespace(status_code=200, json=lambda: {})

    monkeypatch.setattr("requests.get", fake_get)

    api_module._make_api_request("https://example.com", {})

    assert captured_kwargs.get("timeout") == 30.0


# ===========================================================================
# Fix 5: llm_metrics.py _collect_metrics TTL cache
# ===========================================================================

def test_collect_metrics_caches_result_within_ttl(tmp_path, monkeypatch):
    """_collect_metrics returns cached result within TTL without re-reading files."""
    # Reset module-level cache state
    import app.backend.routes.llm_metrics as lm_mod
    from app.backend.routes.llm_metrics import _collect_metrics, _METRICS_CACHE_TTL
    lm_mod._metrics_cache = {}
    lm_mod._metrics_cache_ts = 0.0

    monkeypatch.setenv("LLM_METRICS_DIR", str(tmp_path))

    # Use a date relative to "now" so the test is time-stable: a hardcoded
    # historical timestamp (e.g. 20260609) rots out of the lookback_days=7
    # window as the calendar advances, making file_date < cutoff and silently
    # dropping the entry (calls==0). Anchoring to today keeps it inside the
    # window regardless of when the test runs.
    now = datetime.now(timezone.utc)
    file_name = f"llm_metrics_{now.strftime('%Y%m%d')}_000000.jsonl"
    entry_ts = now.strftime("%Y-%m-%dT12:00:00")

    # Write one entry
    jsonl = tmp_path / file_name
    jsonl.write_text(
        json.dumps({
            "timestamp": entry_ts,
            "agent_name": "test_agent",
            "model_provider": "Test",
            "model_name": "test-model",
            "success": True,
            "duration_ms": 100.0,
            "prompt_chars": 50,
            "response_chars": 10,
        })
        + "\n",
        encoding="utf-8",
    )

    result1 = _collect_metrics(tmp_path, 7)
    assert result1["totals"]["calls"] == 1

    # Remove the file -- if cache works, result2 should still say 1 call
    jsonl.unlink()
    result2 = _collect_metrics(tmp_path, 7)
    assert result2["totals"]["calls"] == 1  # cached

    # Reset cache to force re-read
    lm_mod._metrics_cache_ts = 0.0
    result3 = _collect_metrics(tmp_path, 7)
    assert result3["totals"]["calls"] == 0  # file gone, fresh read


# ===========================================================================
# Fix 6: graph/state.py show_agent_reasoning TypeError catch
# ===========================================================================

def test_show_agent_reasoning_handles_none_output(capsys):
    """show_agent_reasoning does not crash when output=None."""
    from src.graph.state import show_agent_reasoning

    # Should not raise -- None triggers json.loads(None) -> TypeError
    show_agent_reasoning(None, "test_agent")

    captured = capsys.readouterr()
    assert "test_agent" in captured.out
    assert "None" in captured.out


def test_show_agent_reasoning_handles_valid_string(capsys):
    """show_agent_reasoning still works for valid JSON strings."""
    from src.graph.state import show_agent_reasoning

    show_agent_reasoning('{"key": "value"}', "test_agent")

    captured = capsys.readouterr()
    assert "value" in captured.out


def test_show_agent_reasoning_handles_non_json_string(capsys):
    """show_agent_reasoning falls back to plain print for non-JSON strings."""
    from src.graph.state import show_agent_reasoning

    show_agent_reasoning("just a plain string", "test_agent")

    captured = capsys.readouterr()
    assert "just a plain string" in captured.out


# ===========================================================================
# New finding A: data_sources.py had no error handling
# ===========================================================================

def test_data_sources_health_returns_500_on_monitor_failure(monkeypatch):
    """GET /data-sources/health returns 500 when get_health_monitor() fails."""
    import app.backend.routes.data_sources as ds_module
    from app.backend.routes.data_sources import router

    def _boom():
        raise RuntimeError("monitor exploded")

    monkeypatch.setattr(ds_module, "get_health_monitor", _boom)

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/data-sources/health")
    assert response.status_code == 500
    assert "Failed to get data source health" in response.json()["detail"]


# ===========================================================================
# New finding B: cache.py had no error handling
# ===========================================================================

def test_cache_stats_returns_500_on_cache_failure(monkeypatch):
    """GET /cache/stats returns 500 when get_cache_runtime_info() fails."""
    import app.backend.routes.cache as cache_module
    from app.backend.routes.cache import router

    def _boom():
        raise RuntimeError("cache corrupted")

    monkeypatch.setattr(cache_module, "get_cache_runtime_info", _boom)

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/cache/stats")
    assert response.status_code == 500
    assert "Failed to get cache stats" in response.json()["detail"]
