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

import pytest

from src.screening.scoring_feature_refresh import _fetch_ticker_data
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


def test_successful_empty_events_are_observed_empty(monkeypatch, stub_snapshot_exporter):
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
