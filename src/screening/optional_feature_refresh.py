"""Backward-compatible optional feature refresh entry point.

Delegates to :func:`refresh_scoring_features`, which owns the manifest for all
scoring feature families.  ``score_batch()`` never depends on refresh success.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.screening.scoring_feature_refresh import refresh_scoring_features


def refresh_optional_features(
    trade_date: str,
    tickers: list[str],
    *,
    timeout_seconds: float = 20.0,
    cache_dir: Path | str = "data/feature_cache",
) -> dict[str, Any]:
    return refresh_scoring_features(
        trade_date,
        tickers,
        timeout_seconds=timeout_seconds,
        cache_dir=cache_dir,
    )
