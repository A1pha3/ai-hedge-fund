"""Cache status API route — exposes cache hit-rate, disk info, and data-source health."""

from fastapi import APIRouter

from src.data.enhanced_cache import get_cache_runtime_info, get_cache_stats

router = APIRouter(prefix="/cache", tags=["cache"])


@router.get("/stats")
async def cache_stats() -> dict:
    """Return cache hit-rate, entry counts, disk usage, and layer availability.

    Response shape::

        {
          "lru_maxsize": 128,
          "redis_available": false,
          "disk_available": true,
          "disk_path": "~/.cache/ai-hedge-fund/cache.sqlite",
          "disk_entry_count": 42,
          "disk_file_size_bytes": 1048576,
          "stats": {
            "lru_hits": 10,
            "redis_hits": 0,
            "disk_hits": 5,
            "misses": 3,
            "sets": 18,
            "total_hits": 15,
            "total_requests": 18,
            "hit_rate": 0.8333
          }
        }
    """
    return get_cache_runtime_info()
