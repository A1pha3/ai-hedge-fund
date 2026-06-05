"""Data source health API route — exposes provider health status with auto-degradation info."""

from fastapi import APIRouter

from src.data.health import get_health_monitor

router = APIRouter(prefix="/data-sources", tags=["data-sources"])


@router.get("/health")
async def data_sources_health() -> dict:
    """Return health status of all tracked data-source providers.

    Response shape::

        {
          "providers": {
            "akshare": {
              "provider": "akshare",
              "status": "healthy",          # healthy | degraded | unknown
              "success_rate": 0.92,
              "avg_latency_ms": 145.3,
              "total_requests": 50,
              "success_count": 46,
              "last_check": "2026-06-06T10:30:00",
              "last_error": null
            },
            ...
          },
          "summary": {
            "total": 3,
            "healthy": 2,
            "degraded": 0,
            "unknown": 1
          }
        }
    """
    monitor = get_health_monitor()
    all_health = monitor.get_all_health()

    providers_payload = {}
    summary = {"total": 0, "healthy": 0, "degraded": 0, "unknown": 0}

    for name, health in all_health.items():
        providers_payload[name] = health.to_dict()
        summary["total"] += 1
        status = health.status.value
        if status in summary:
            summary[status] += 1

    return {
        "providers": providers_payload,
        "summary": summary,
    }
