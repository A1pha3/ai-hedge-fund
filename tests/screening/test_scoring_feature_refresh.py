"""Tests for per-ticker observation tracking in scoring_feature_refresh.

Spec reference: Task 3 of the Auto/Daily Action readiness separation.
``_fetch_ticker_data`` must return truthful per-family observation evidence
(success / partial / failed) instead of only count dicts, so the refresh
manifest can distinguish a legal empty observation (e.g. no insider trades
filed today) from a silent producer failure.

These tests focus on ``_fetch_ticker_data`` directly because it owns the
observation-status derivation; ``refresh_scoring_features`` is a thin
thread-pool wrapper around it.
"""

from __future__ import annotations

import concurrent.futures
import json
import threading
import time

import pytest

from src.screening import scoring_feature_refresh
from src.screening.scoring_feature_refresh import (
    SourceObservation,
    TickerFeatureObservation,
    _fetch_ticker_data,
    refresh_scoring_features,
)
from src.screening.scoring_feature_quality import ObservationStatus


@pytest.fixture
def stub_snapshot_exporter(monkeypatch):
    """Stub ``get_snapshot_exporter`` so export_insider_trades is a no-op."""

    class _StubExporter:
        def export_insider_trades(self, *args, **kwargs):
            return None

    monkeypatch.setattr(
        "src.data.snapshot.get_snapshot_exporter",
        lambda: _StubExporter(),
    )


def _observation_for(observations, family):
    return next(obs for obs in observations if obs.family == family)


def test_successful_empty_events_are_observed_empty(
    monkeypatch, stub_snapshot_exporter
):
    """get_company_news returns [], get_insider_trades returns [] → SUCCESS, nonempty=0.

    event_inputs has legal-when-observed empty semantics: a reachable source
    that truthfully returns zero rows is an authoritative observation, not a
    failure. Both sources reachable (even empty) → SUCCESS with nonempty=0.
    """
    monkeypatch.setattr("src.tools.api.get_company_news", lambda *a, **k: [])
    monkeypatch.setattr("src.tools.api.get_insider_trades", lambda *a, **k: [])
    monkeypatch.setattr(
        "src.tools.api.get_financial_metrics",
        lambda *a, **k: [],
    )

    observations = _fetch_ticker_data("000001", "20260708")

    event_obs = _observation_for(observations, "event_inputs")
    assert event_obs.status is ObservationStatus.SUCCESS
    assert event_obs.nonempty_count == 0
    assert event_obs.source_parts_succeeded == 2
    assert event_obs.source_parts_total == 2
    assert event_obs.failure_code is None


def test_event_is_partial_when_one_source_fails(monkeypatch, stub_snapshot_exporter):
    """get_insider_trades raises → PARTIAL for event_inputs.

    One of the two event sources is reachable (company_news returns a list),
    the other raises — the family is PARTIAL because only a strict subset of
    sources produced an authoritative answer.
    """

    def _raise(*args, **kwargs):
        raise RuntimeError("tushare unreachable")

    monkeypatch.setattr(
        "src.tools.api.get_company_news",
        lambda *a, **k: [{"title": "news"}],
    )
    monkeypatch.setattr("src.tools.api.get_insider_trades", _raise)
    monkeypatch.setattr(
        "src.tools.api.get_financial_metrics",
        lambda *a, **k: [],
    )

    observations = _fetch_ticker_data("000001", "20260708")

    event_obs = _observation_for(observations, "event_inputs")
    assert event_obs.status is ObservationStatus.PARTIAL
    assert event_obs.source_parts_succeeded == 1
    assert event_obs.source_parts_total == 2
    assert event_obs.nonempty_count == 1  # only news rows counted
    assert event_obs.failure_code == "RuntimeError"
    sources = {source.source: source for source in event_obs.sources}
    assert sources["company_news"].status is ObservationStatus.SUCCESS
    assert sources["company_news"].nonempty_count == 1
    assert sources["company_news"].failure_code is None
    assert sources["insider_trades"].status is ObservationStatus.FAILED
    assert sources["insider_trades"].nonempty_count == 0
    assert sources["insider_trades"].failure_code == "RuntimeError"


def test_all_sources_fail_is_failed(monkeypatch, stub_snapshot_exporter):
    """Both news and trades raise → FAILED.

    When no event source is reachable the family observation is FAILED — the
    manifest must record this honestly rather than masking it as an empty
    SUCCESS.
    """

    def _raise(*args, **kwargs):
        raise ConnectionError("network down")

    monkeypatch.setattr("src.tools.api.get_company_news", _raise)
    monkeypatch.setattr("src.tools.api.get_insider_trades", _raise)
    monkeypatch.setattr(
        "src.tools.api.get_financial_metrics",
        lambda *a, **k: [],
    )

    observations = _fetch_ticker_data("000001", "20260708")

    event_obs = _observation_for(observations, "event_inputs")
    assert event_obs.status is ObservationStatus.FAILED
    assert event_obs.source_parts_succeeded == 0
    assert event_obs.source_parts_total == 2
    assert event_obs.nonempty_count == 0
    assert event_obs.failure_code == "ConnectionError"


def test_financial_metrics_success_on_nonempty(monkeypatch, stub_snapshot_exporter):
    """financial_metrics is a single-source family: nonempty result → SUCCESS."""
    monkeypatch.setattr(
        "src.tools.api.get_financial_metrics",
        lambda *a, **k: [{"ticker": "000001"}, {"ticker": "000001"}],
    )
    monkeypatch.setattr("src.tools.api.get_company_news", lambda *a, **k: [])
    monkeypatch.setattr("src.tools.api.get_insider_trades", lambda *a, **k: [])

    observations = _fetch_ticker_data("000001", "20260708")

    fin_obs = _observation_for(observations, "financial_metrics")
    assert fin_obs.status is ObservationStatus.SUCCESS
    assert fin_obs.nonempty_count == 2
    assert fin_obs.source_parts_succeeded == 1
    assert fin_obs.source_parts_total == 1


def test_financial_metrics_failed_on_exception(monkeypatch, stub_snapshot_exporter):
    """financial_metrics raising → FAILED with the exception class recorded."""

    def _raise(*args, **kwargs):
        raise TimeoutError("tushare timeout")

    monkeypatch.setattr("src.tools.api.get_financial_metrics", _raise)
    monkeypatch.setattr("src.tools.api.get_company_news", lambda *a, **k: [])
    monkeypatch.setattr("src.tools.api.get_insider_trades", lambda *a, **k: [])

    observations = _fetch_ticker_data("000001", "20260708")

    fin_obs = _observation_for(observations, "financial_metrics")
    assert fin_obs.status is ObservationStatus.FAILED
    assert fin_obs.source_parts_succeeded == 0
    assert fin_obs.source_parts_total == 1
    assert fin_obs.failure_code == "TimeoutError"


def test_timeout_conserves_every_requested_ticker(monkeypatch, tmp_path):
    release_slow_provider = threading.Event()
    shutdown_calls = []

    class _RecordingExecutor(concurrent.futures.ThreadPoolExecutor):
        def shutdown(self, wait=True, *, cancel_futures=False):
            shutdown_calls.append((wait, cancel_futures))
            return super().shutdown(wait=wait, cancel_futures=cancel_futures)

    def _fake_fetch(ticker, trade_date):
        if ticker == "000002":
            release_slow_provider.wait(timeout=1.0)
        return [
            TickerFeatureObservation(
                ticker=ticker,
                family="financial_metrics",
                status=ObservationStatus.SUCCESS,
                nonempty_count=1,
                source_parts_succeeded=1,
                source_parts_total=1,
            ),
            TickerFeatureObservation(
                ticker=ticker,
                family="event_inputs",
                status=ObservationStatus.SUCCESS,
                nonempty_count=0,
                source_parts_succeeded=2,
                source_parts_total=2,
            ),
        ]

    monkeypatch.delenv("AUTO_OPTIONAL_FEATURE_REFRESH", raising=False)
    monkeypatch.setattr(scoring_feature_refresh, "_enable_snapshots", lambda: None)
    monkeypatch.setattr(scoring_feature_refresh, "_fetch_ticker_data", _fake_fetch)
    monkeypatch.setattr(scoring_feature_refresh, "_MAX_WORKERS", 2)
    monkeypatch.setattr(
        scoring_feature_refresh.concurrent.futures,
        "ThreadPoolExecutor",
        _RecordingExecutor,
    )
    release_timer = threading.Timer(0.5, release_slow_provider.set)
    release_timer.daemon = True
    release_timer.start()
    started = time.monotonic()
    try:
        result = refresh_scoring_features(
            "20260713",
            ["000001", "000002"],
            timeout_seconds=0.05,
            cache_dir=tmp_path,
        )
    finally:
        elapsed = time.monotonic() - started
        release_slow_provider.set()
        release_timer.cancel()

    assert elapsed < 0.25
    assert set(result["ticker_outcomes"]) == {"000001", "000002"}
    assert result["success_count"] + result["failure_count"] == 2
    assert result["failure_count"] == 1
    assert shutdown_calls == [(False, True)]

    completed = result["ticker_outcomes"]["000001"]
    assert completed["observation_status"] == "success"
    timed_out = result["ticker_outcomes"]["000002"]
    assert timed_out["observation_status"] == "failed"
    assert {family["failure_code"] for family in timed_out["families"].values()} == {
        "provider_timeout"
    }

    manifest = json.loads(
        (tmp_path / "feature_manifest_20260713.json").read_text(encoding="utf-8")
    )
    assert manifest["ticker_outcomes"] == result["ticker_outcomes"]
    assert manifest["features"]["financial_metrics"]["failed_count"] == 1
    assert manifest["features"]["event_inputs"]["failed_count"] == 1


def test_partial_ticker_counts_as_top_level_failure(monkeypatch, tmp_path):
    def _partial_fetch(ticker, trade_date):
        return [
            TickerFeatureObservation(
                ticker=ticker,
                family="financial_metrics",
                status=ObservationStatus.SUCCESS,
                nonempty_count=1,
                source_parts_succeeded=1,
                source_parts_total=1,
                sources=(
                    SourceObservation(
                        source="financial_metrics",
                        status=ObservationStatus.SUCCESS,
                        nonempty_count=1,
                    ),
                ),
            ),
            TickerFeatureObservation(
                ticker=ticker,
                family="event_inputs",
                status=ObservationStatus.PARTIAL,
                nonempty_count=0,
                source_parts_succeeded=1,
                source_parts_total=2,
                failure_code="RuntimeError",
                sources=(
                    SourceObservation(
                        source="company_news",
                        status=ObservationStatus.SUCCESS,
                        nonempty_count=0,
                    ),
                    SourceObservation(
                        source="insider_trades",
                        status=ObservationStatus.FAILED,
                        nonempty_count=0,
                        failure_code="RuntimeError",
                    ),
                ),
            ),
        ]

    monkeypatch.setenv("AUTO_OPTIONAL_FEATURE_REFRESH", "1")
    monkeypatch.setattr(scoring_feature_refresh, "_enable_snapshots", lambda: None)
    monkeypatch.setattr(scoring_feature_refresh, "_fetch_ticker_data", _partial_fetch)

    result = refresh_scoring_features(
        "20260713", ["000001"], timeout_seconds=1.0, cache_dir=tmp_path
    )

    assert result["success_count"] == 0
    assert result["failure_count"] == 1
    ticker_outcome = result["ticker_outcomes"]["000001"]
    assert ticker_outcome["observation_status"] == "partial"
    assert (
        ticker_outcome["families"]["event_inputs"]["observation_status"]
        == "partial"
    )


@pytest.mark.parametrize(
    ("tickers", "expected_failures"),
    [(["000001", "000002"], 2), ([], 0)],
)
def test_skipped_refresh_emits_conserved_explicit_counters(
    monkeypatch, tmp_path, tickers, expected_failures
):
    monkeypatch.setenv("AUTO_OPTIONAL_FEATURE_REFRESH", "0")

    result = refresh_scoring_features(
        "20260713", tickers, timeout_seconds=1.0, cache_dir=tmp_path
    )

    assert result["success_count"] == 0
    assert result["failure_count"] == expected_failures
    assert result["success_count"] + result["failure_count"] == len(tickers)
    manifest = json.loads(
        (tmp_path / "feature_manifest_20260713.json").read_text(encoding="utf-8")
    )
    assert manifest["success_count"] == result["success_count"]
    assert manifest["failure_count"] == result["failure_count"]
