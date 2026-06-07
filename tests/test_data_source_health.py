"""
Tests for src/data/health.py — HealthTracker, HealthMonitor, DataSourceHealth,
and the integration with router_helpers.fetch_from_providers.

Covers:
  - Sliding window success rate computation
  - Degradation when success_rate drops below threshold
  - Recovery when success_rate climbs above recover threshold (hysteresis)
  - Edge cases: no history, all failures, instant recovery attempts
  - HealthMonitor global API
  - Integration with fetch_from_providers (health recording on each provider call)
"""

from __future__ import annotations

import asyncio

import pytest

from src.data.base_provider import DataResponse
from src.data.health import (
    DataSourceHealth,
    HealthMonitor,
    HealthTracker,
    SourceStatus,
    get_health_monitor,
    reset_health_monitor,
)
from src.data.router_helpers import fetch_from_providers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Provider:
    """Fake provider for integration tests."""

    def __init__(self, name: str, priority: int = 1, *, price_response=None):
        self.name = name
        self.priority = priority
        self._price_response = price_response

    async def get_prices(self, ticker: str, start_date: str, end_date: str):
        if isinstance(self._price_response, Exception):
            raise self._price_response
        return self._price_response


# ---------------------------------------------------------------------------
# HealthTracker unit tests
# ---------------------------------------------------------------------------


class TestHealthTrackerStats:
    """Sliding window statistics."""

    def test_empty_tracker_returns_zero_stats(self):
        tracker = HealthTracker("test")
        rate, latency, total, successes, last_error = tracker._compute_stats()
        assert rate == 0.0
        assert latency == 0.0
        assert total == 0
        assert successes == 0
        assert last_error is None

    def test_single_success(self):
        tracker = HealthTracker("test")
        tracker.record_success(100.0)
        rate, latency, total, successes, last_error = tracker._compute_stats()
        assert rate == 1.0
        assert latency == 100.0
        assert total == 1
        assert successes == 1

    def test_mixed_success_failure(self):
        tracker = HealthTracker("test")
        tracker.record_success(100.0)
        tracker.record_failure(200.0, error="timeout")
        tracker.record_success(150.0)
        rate, latency, total, successes, last_error = tracker._compute_stats()
        assert total == 3
        assert successes == 2
        assert rate == pytest.approx(2 / 3, abs=1e-4)
        assert latency == pytest.approx((100 + 200 + 150) / 3, abs=0.01)
        assert last_error == "timeout"

    def test_last_error_picks_most_recent(self):
        tracker = HealthTracker("test")
        tracker.record_failure(50.0, error="err1")
        tracker.record_success(50.0)
        tracker.record_failure(50.0, error="err2")
        _, _, _, _, last_error = tracker._compute_stats()
        assert last_error == "err2"

    def test_sliding_window_evicts_old_records(self):
        tracker = HealthTracker("test", window_size=5)
        # Fill with 5 successes
        for _ in range(5):
            tracker.record_success(100.0)
        # Add 5 failures — the 5 successes should be evicted
        for i in range(5):
            tracker.record_failure(100.0, error=f"fail-{i}")
        rate, _, total, successes, _ = tracker._compute_stats()
        assert total == 5
        assert successes == 0
        assert rate == 0.0


class TestHealthTrackerDegradation:
    """Degrade / recover state transitions."""

    def test_starts_as_unknown(self):
        tracker = HealthTracker("test")
        assert tracker.status == SourceStatus.UNKNOWN
        assert tracker.is_healthy is True  # UNKNOWN is not DEGRADED

    def test_transitions_to_healthy_on_good_data(self):
        """With success_rate >= degrade_threshold, UNKNOWN -> HEALTHY."""
        tracker = HealthTracker("test", window_size=10, degrade_threshold=0.70, recover_threshold=0.80)
        tracker.record_success(100.0)
        assert tracker.status == SourceStatus.HEALTHY

    def test_transitions_to_degraded_on_bad_data_from_unknown(self):
        """With success_rate < degrade_threshold, UNKNOWN -> DEGRADED."""
        tracker = HealthTracker("test", window_size=10, degrade_threshold=0.70, recover_threshold=0.80)
        tracker.record_failure(100.0, error="err")
        assert tracker.status == SourceStatus.DEGRADED

    def test_degrades_when_below_threshold(self):
        tracker = HealthTracker("test", window_size=10, degrade_threshold=0.70, recover_threshold=0.80)
        # 3 successes + 7 failures = 30% success rate < 70%
        for _ in range(3):
            tracker.record_success(100.0)
        for _ in range(7):
            tracker.record_failure(100.0, error="err")
        assert tracker.status == SourceStatus.DEGRADED
        assert tracker.is_healthy is False

    def test_does_not_degrade_at_threshold(self):
        """success_rate == degrade_threshold should stay HEALTHY (not strictly less)."""
        tracker = HealthTracker("test", window_size=10, degrade_threshold=0.70, recover_threshold=0.80)
        # 7 successes + 3 failures = 70% == degrade_threshold -> not < threshold -> HEALTHY
        for _ in range(7):
            tracker.record_success(100.0)
        for _ in range(3):
            tracker.record_failure(100.0, error="err")
        assert tracker.status == SourceStatus.HEALTHY

    def test_recovery_requires_higher_threshold(self):
        """Once degraded, recovery requires success_rate >= recover_threshold."""
        tracker = HealthTracker("test", window_size=10, degrade_threshold=0.70, recover_threshold=0.80)

        # Degrade: 3S + 7F = 30%
        for _ in range(3):
            tracker.record_success(100.0)
        for _ in range(7):
            tracker.record_failure(100.0, error="err")
        assert tracker.status == SourceStatus.DEGRADED

        # Add 5 more successes: window [S,S,S,F,F,F,F,F,F,F] + 5S
        # evicts 5 oldest (S,S,S,F,F) -> window [F,F,F,F,F,S,S,S,S,S] = 50% < 80%
        for _ in range(5):
            tracker.record_success(100.0)
        assert tracker.status == SourceStatus.DEGRADED

        # Add 3 more successes: evict 3 oldest F
        # window [F,F,S,S,S,S,S,S,S,S] = 8/10 = 80% >= 80% -> recovered
        for _ in range(3):
            tracker.record_success(100.0)
        assert tracker.status == SourceStatus.HEALTHY

    def test_instant_recovery_blocked_after_degradation(self):
        """A single success after degradation should not immediately recover."""
        tracker = HealthTracker("test", window_size=10, degrade_threshold=0.70, recover_threshold=0.80)
        for _ in range(10):
            tracker.record_failure(100.0, error="err")
        assert tracker.status == SourceStatus.DEGRADED
        # 1 success: window = 9F + 1S = 10% << 80%
        tracker.record_success(100.0)
        assert tracker.status == SourceStatus.DEGRADED

    def test_all_failures_degrades(self):
        tracker = HealthTracker("test", window_size=5, degrade_threshold=0.70, recover_threshold=0.80)
        for _ in range(5):
            tracker.record_failure(100.0, error="timeout")
        assert tracker.status == SourceStatus.DEGRADED
        assert tracker.is_healthy is False


class TestHealthTrackerValidation:
    """Parameter validation."""

    def test_degrade_threshold_must_be_in_range(self):
        with pytest.raises(ValueError, match="degrade_threshold"):
            HealthTracker("test", degrade_threshold=0.0)

    def test_degrade_threshold_must_be_positive(self):
        with pytest.raises(ValueError, match="degrade_threshold"):
            HealthTracker("test", degrade_threshold=-0.1)

    def test_recover_threshold_must_be_in_range(self):
        with pytest.raises(ValueError, match="recover_threshold"):
            HealthTracker("test", recover_threshold=1.5)

    def test_recover_must_be_ge_degrade(self):
        with pytest.raises(ValueError, match="recover_threshold"):
            HealthTracker("test", degrade_threshold=0.80, recover_threshold=0.70)


class TestHealthTrackerSnapshot:
    """DataSourceHealth snapshot."""

    def test_get_health_returns_correct_snapshot(self):
        tracker = HealthTracker("my_provider", window_size=10)
        tracker.record_success(100.0)
        tracker.record_failure(200.0, error="boom")

        health = tracker.get_health()
        assert isinstance(health, DataSourceHealth)
        assert health.provider == "my_provider"
        # 1/2 = 50% < 70% degrade threshold -> DEGRADED
        assert health.status == SourceStatus.DEGRADED
        assert health.total_requests == 2
        assert health.success_count == 1
        assert health.success_rate == 0.5
        assert health.last_error == "boom"

    def test_to_dict_roundtrip(self):
        tracker = HealthTracker("test")
        tracker.record_success(50.0)
        d = tracker.get_health().to_dict()
        assert d["provider"] == "test"
        assert d["status"] in ("healthy", "degraded", "unknown")
        assert isinstance(d["success_rate"], float)
        assert isinstance(d["total_requests"], int)


# ---------------------------------------------------------------------------
# HealthMonitor unit tests
# ---------------------------------------------------------------------------


class TestHealthMonitor:
    """Global monitor that manages multiple trackers."""

    def test_unknown_provider_is_healthy(self):
        """Providers with no history default to healthy."""
        monitor = HealthMonitor()
        assert monitor.is_healthy("never_seen") is True

    def test_record_and_query(self):
        monitor = HealthMonitor(window_size=10, degrade_threshold=0.70, recover_threshold=0.80)
        monitor.record_success("p1", 100.0)
        monitor.record_failure("p1", 200.0, error="err")
        health = monitor.get_health("p1")
        assert health is not None
        assert health.total_requests == 2
        assert health.success_count == 1

    def test_degraded_provider_not_in_healthy_list(self):
        monitor = HealthMonitor(window_size=5, degrade_threshold=0.70, recover_threshold=0.80)
        # Degrade p1
        for _ in range(5):
            monitor.record_failure("p1", 100.0, error="fail")
        assert monitor.is_healthy("p1") is False

        healthy = monitor.get_healthy_providers(["p1", "p2", "p3"])
        assert healthy == ["p2", "p3"]

    def test_get_all_health(self):
        monitor = HealthMonitor()
        monitor.record_success("a", 10.0)
        monitor.record_failure("b", 20.0, error="x")
        all_health = monitor.get_all_health()
        assert set(all_health.keys()) == {"a", "b"}
        assert all_health["a"].success_count == 1
        assert all_health["b"].total_requests == 1

    def test_record_convenience_method(self):
        monitor = HealthMonitor()
        monitor.record("p", success=True, latency_ms=50.0)
        monitor.record("p", success=False, latency_ms=100.0, error="oops")
        health = monitor.get_health("p")
        assert health.total_requests == 2
        assert health.success_count == 1

    def test_global_singleton(self):
        reset_health_monitor()
        m1 = get_health_monitor()
        m2 = get_health_monitor()
        assert m1 is m2
        reset_health_monitor()

    def test_global_reset(self):
        reset_health_monitor()
        m1 = get_health_monitor()
        m1.record_success("x", 10.0)
        reset_health_monitor()
        m2 = get_health_monitor()
        assert m2.get_health("x") is None


# ---------------------------------------------------------------------------
# fetch_from_providers integration tests
# ---------------------------------------------------------------------------


class TestFetchFromProvidersHealthRecording:
    """Verify fetch_from_providers records health outcomes in the global HealthMonitor."""

    def setup_method(self):
        reset_health_monitor()

    def _run(self, coro):
        return asyncio.run(coro)

    def test_records_success_for_good_provider(self):
        reset_health_monitor()
        monitor = get_health_monitor()
        p = _Provider(
            "good",
            price_response=DataResponse(data=[{"close": 42}], source="good"),
        )

        response, error = self._run(
            fetch_from_providers(
                [p],
                request_label="test",
                logger=__import__("logging").getLogger("test"),
                fetcher=lambda provider: provider.get_prices("AAPL", "2024-01-01", "2024-01-02"),
            )
        )

        assert response is not None
        assert error is None
        health = monitor.get_health("good")
        assert health is not None
        assert health.success_count == 1
        assert health.total_requests == 1

    def test_records_failure_on_exception(self):
        reset_health_monitor()
        monitor = get_health_monitor()
        p = _Provider("boom", price_response=RuntimeError("kapow"))

        response, error = self._run(
            fetch_from_providers(
                [p],
                request_label="test",
                logger=__import__("logging").getLogger("test"),
                fetcher=lambda provider: provider.get_prices("AAPL", "2024-01-01", "2024-01-02"),
            )
        )

        assert response is None
        assert error == "kapow"
        health = monitor.get_health("boom")
        assert health is not None
        assert health.success_count == 0
        assert health.total_requests == 1
        assert health.last_error == "kapow"

    def test_records_failure_on_error_response(self):
        reset_health_monitor()
        monitor = get_health_monitor()
        p1 = _Provider("bad", price_response=DataResponse(data=[], source="bad", error="bad data"))
        p2 = _Provider("ok", price_response=DataResponse(data=[{"close": 1}], source="ok"))

        response, error = self._run(
            fetch_from_providers(
                [p1, p2],
                request_label="test",
                logger=__import__("logging").getLogger("test"),
                fetcher=lambda provider: provider.get_prices("AAPL", "2024-01-01", "2024-01-02"),
            )
        )

        assert response is not None
        assert response.source == "ok"
        h1 = monitor.get_health("bad")
        assert h1.success_count == 0
        assert h1.total_requests == 1
        h2 = monitor.get_health("ok")
        assert h2.success_count == 1

    def test_fallback_to_next_provider_and_records_both(self):
        reset_health_monitor()
        monitor = get_health_monitor()
        p1 = _Provider("primary", price_response=DataResponse(data=[], source="primary", error="err"))
        p2 = _Provider(
            "secondary",
            price_response=DataResponse(data=[{"close": 99}], source="secondary"),
        )

        response, error = self._run(
            fetch_from_providers(
                [p1, p2],
                request_label="test",
                logger=__import__("logging").getLogger("test"),
                fetcher=lambda provider: provider.get_prices("AAPL", "2024-01-01", "2024-01-02"),
            )
        )

        assert response.source == "secondary"
        assert monitor.get_health("primary").success_count == 0
        assert monitor.get_health("secondary").success_count == 1

    def test_all_providers_fail(self):
        reset_health_monitor()
        monitor = get_health_monitor()
        p1 = _Provider("a", price_response=DataResponse(data=[], source="a", error="e1"))
        p2 = _Provider("b", price_response=RuntimeError("e2"))

        response, error = self._run(
            fetch_from_providers(
                [p1, p2],
                request_label="test",
                logger=__import__("logging").getLogger("test"),
                fetcher=lambda provider: provider.get_prices("AAPL", "2024-01-01", "2024-01-02"),
            )
        )

        assert response is None
        assert error == "e2"
        assert monitor.get_health("a").total_requests == 1
        assert monitor.get_health("b").total_requests == 1

    def test_degraded_provider_skipped_by_monitor(self):
        """Simulate what DataRouter._get_healthy_providers does with HealthMonitor."""
        reset_health_monitor()
        monitor = get_health_monitor()

        # Degrade p1: 4 failures out of 5 = 20% < 70%
        for i in range(4):
            monitor.record_failure("p1", 100.0, error=f"err-{i}")
        monitor.record_success("p1", 100.0)
        assert monitor.is_healthy("p1") is False

        # get_healthy_providers should skip p1
        healthy = monitor.get_healthy_providers(["p1", "p2"])
        assert healthy == ["p2"]
