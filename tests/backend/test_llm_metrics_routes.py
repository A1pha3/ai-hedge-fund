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


# ---------------------------------------------------------------------------
# c293: data-quality + staleness honesty disclosure.
#
# The dashboard previously:
#   - silently skipped JSONL files that raised OSError on open (line 264)
#     with no log and no counter — a whole session's data could disappear
#     and the operator saw a polished dashboard with no hint of data loss;
#   - silently skipped malformed JSON lines (line 203) with no counter;
#   - silently skipped files whose name had an unparseable date (line 191)
#     with no counter;
#   - bucketed entries with unparseable timestamps into "unknown" with no
#     surfaced count;
#   - returned a 60s-TTL cached result with NO as_of / served_from_cache /
#     cache_age field — the operator could not tell fresh vs stale;
#   - returned an all-zero "success" response when the logs dir was missing,
#     indistinguishable from a genuine-zero day.
#
# These are the same NS-17 silent-degradation + NS-5 staleness disease
# classes drained across the decision chain (c267-c292). The fix is ADDITIVE
# disclosure: a top-level ``data_quality`` dict + ``as_of`` /
# ``served_from_cache`` / ``cache_age_seconds`` fields. No existing field
# semantics change.
# ---------------------------------------------------------------------------


def _reset_llm_metrics_cache() -> None:
    """Clear the module-level TTL cache so cache tests start from a known state."""
    import app.backend.routes.llm_metrics as mod

    mod._metrics_cache = {}
    mod._metrics_cache_ts = 0.0


def test_collect_metrics_discloses_missing_logs_dir(tmp_path, monkeypatch):
    """A missing logs dir must not look like a genuine-zero day.

    Previously ``logs_dir.glob(...)`` on a non-existent path returns ``[]``
    silently and the endpoint returns a 200 all-zero dict with no disclosure
    that the data source itself was absent. The operator cannot distinguish
    "no LLM calls happened" from "we cannot find the logs".
    """
    missing_dir = tmp_path / "does_not_exist"
    monkeypatch.setenv("LLM_METRICS_DIR", str(missing_dir))
    _reset_llm_metrics_cache()

    client = TestClient(_make_app())
    data = client.get("/llm-metrics/summary").json()

    assert data["totals"]["calls"] == 0
    dq = data["data_quality"]
    assert dq["logs_dir_exists"] is False
    assert dq["logs_dir"] == str(missing_dir)
    # The other skip counters should be zero (no files to skip).
    assert dq["files_skipped_oserror"] == 0
    assert dq["lines_skipped_json"] == 0
    assert dq["files_skipped_bad_date"] == 0
    assert dq["entries_unknown_date"] == 0


def test_collect_metrics_discloses_oserror_file_skip(tmp_path, monkeypatch, caplog):
    """A JSONL file that raises OSError on open must be counted + logged, not silently dropped."""
    import logging

    import app.backend.routes.llm_metrics as mod

    monkeypatch.setenv("LLM_METRICS_DIR", str(tmp_path))
    _reset_llm_metrics_cache()

    today = datetime.now(timezone.utc)
    # A directory named like a metrics file makes Path.open() raise
    # IsADirectoryError (a subclass of OSError) — exercises the
    # `except OSError: continue` branch at line 264 without mocking.
    skip_dir = tmp_path / f"llm_metrics_{today.strftime('%Y%m%d')}_120000.jsonl"
    skip_dir.mkdir()

    with caplog.at_level(logging.WARNING, logger="app.backend.routes.llm_metrics"):
        data = mod._collect_metrics(tmp_path, lookback_days=7)

    dq = data["data_quality"]
    assert dq["files_skipped_oserror"] == 1, "a JSONL file that raised OSError on open must be counted in " "data_quality.files_skipped_oserror — silently dropping a whole " "session's data is the NS-17 silent-skip disease class (c293)"
    # The skip must also be logged so the operator can diagnose (matches the
    # c289 corrupt-row logging pattern).
    assert "skip" in caplog.text.lower() or "oserror" in caplog.text.lower(), "OSError file-skip must be logged (logger.warning) so the operator can " "diagnose permissions / IO errors, not just silently counted"


def test_collect_metrics_discloses_json_line_skip_and_bad_date(tmp_path, monkeypatch):
    """Malformed JSON lines + files with unparseable date names must be counted."""
    monkeypatch.setenv("LLM_METRICS_DIR", str(tmp_path))
    _reset_llm_metrics_cache()

    today = datetime.now(timezone.utc)

    # File 1: valid name + one good line + one malformed JSON line.
    good_file = tmp_path / f"llm_metrics_{today.strftime('%Y%m%d')}_120000.jsonl"
    good_file.write_text(
        json.dumps(
            {
                "timestamp": today.strftime("%Y-%m-%dT12:00:00"),
                "agent_name": "a",
                "model_provider": "p",
                "model_name": "m",
                "success": True,
                "duration_ms": 10.0,
                "prompt_chars": 1,
                "response_chars": 1,
            }
        )
        + "\n{not valid json\n"
        + "\n",  # malformed line + blank line
        encoding="utf-8",
    )

    # File 2: unparseable date in filename → skipped at line 191.
    bad_date_file = tmp_path / "llm_metrics_NOTADATE_120000.jsonl"
    bad_date_file.write_text("", encoding="utf-8")

    data = _collect_metrics(tmp_path, lookback_days=7)

    dq = data["data_quality"]
    assert dq["lines_skipped_json"] == 1, "the malformed JSON line must be counted in data_quality.lines_skipped_json"
    assert dq["files_skipped_bad_date"] == 1, "the file with an unparseable date in its name must be counted in " "data_quality.files_skipped_bad_date"


def test_collect_metrics_discloses_cache_staleness(tmp_path, monkeypatch):
    """A cached response must disclose as_of + served_from_cache + cache_age_seconds."""
    import time as _time

    monkeypatch.setenv("LLM_METRICS_DIR", str(tmp_path))
    _reset_llm_metrics_cache()

    # First call — fresh compute.
    first = _collect_metrics(tmp_path, lookback_days=7)
    assert first["served_from_cache"] is False
    assert first["cache_age_seconds"] == 0.0
    assert first["as_of"], "fresh response must carry an as_of timestamp"

    # Sleep just enough to make cache_age measurably positive.
    _time.sleep(0.05)

    # Second call within TTL — served from cache.
    second = _collect_metrics(tmp_path, lookback_days=7)
    assert second["served_from_cache"] is True, "second call within 60s TTL must disclose served_from_cache=True so the " "operator can tell the dashboard is stale (NS-5 staleness disease class, c293)"
    assert second["cache_age_seconds"] >= 0.0
    # as_of stays pinned to when the data was actually computed (the cache
    # population time), NOT the serve time — so the operator sees the true
    # age of the underlying data.
    assert second["as_of"] == first["as_of"]
