"""Tests for the cache status API route."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.routes.cache import router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def test_cache_stats_returns_200():
    """GET /cache/stats returns 200 with expected structure."""
    client = TestClient(_make_app())
    response = client.get("/cache/stats")

    assert response.status_code == 200
    data = response.json()

    # Top-level keys
    assert "stats" in data
    assert "lru_maxsize" in data
    assert "redis_available" in data
    assert "disk_available" in data
    assert "disk_path" in data
    assert "disk_entry_count" in data
    assert "disk_file_size_bytes" in data

    # Stats sub-object keys
    stats = data["stats"]
    for key in ("lru_hits", "redis_hits", "disk_hits", "misses", "sets", "total_hits", "total_requests", "hit_rate"):
        assert key in stats, f"Missing stats key: {key}"

    # hit_rate is between 0 and 1
    assert 0 <= stats["hit_rate"] <= 1


def test_cache_stats_types():
    """GET /cache/stats returns correct value types."""
    client = TestClient(_make_app())
    data = client.get("/cache/stats").json()

    assert isinstance(data["lru_maxsize"], int)
    assert isinstance(data["redis_available"], bool)
    assert isinstance(data["disk_available"], bool)
    assert isinstance(data["disk_entry_count"], int)
    assert isinstance(data["disk_file_size_bytes"], int)

    stats = data["stats"]
    # round(0, 4) returns int 0 in Python, so accept both int and float
    assert isinstance(stats["hit_rate"], (int, float))
    assert isinstance(stats["total_requests"], int)


def test_cache_stats_hit_rate_math():
    """hit_rate = total_hits / total_requests (or 0 when no requests)."""
    client = TestClient(_make_app())
    data = client.get("/cache/stats").json()
    stats = data["stats"]

    if stats["total_requests"] > 0:
        expected = round(stats["total_hits"] / stats["total_requests"], 4)
        assert abs(stats["hit_rate"] - expected) < 1e-9
    else:
        assert stats["hit_rate"] == 0.0
