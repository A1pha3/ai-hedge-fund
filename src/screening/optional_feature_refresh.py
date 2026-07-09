"""Best-effort optional feature refresh for auto screening.

The scorer reads local snapshots only.  Provider-specific snapshot writers can
be added behind this boundary without changing ``score_batch()``.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def _refresh_enabled() -> bool:
    raw = os.environ.get("AUTO_OPTIONAL_FEATURE_REFRESH", "1")
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def refresh_optional_features(
    trade_date: str,
    tickers: list[str],
    *,
    timeout_seconds: float = 20.0,
    cache_dir: Path | str = "data/feature_cache",
) -> dict[str, Any]:
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    unique_tickers = sorted({str(ticker).zfill(6) for ticker in tickers})
    enabled = _refresh_enabled()
    status = "not_implemented" if enabled else "skipped"
    source = "pending_provider_implementation" if enabled else "not_refreshed"
    manifest = {
        "trade_date": str(trade_date),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "candidate_count": len(unique_tickers),
        "timeout_seconds": float(timeout_seconds),
        "status": status,
        "features": {
            "intraday_short_trade_metrics": {
                "provider_failures": 0,
                "rows_written": 0,
                "source": source,
            },
            "daily_fund_flow_metrics": {
                "provider_failures": 0,
                "rows_written": 0,
                "source": source,
            },
        },
    }
    manifest_path = cache_path / f"feature_manifest_{trade_date}.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "status": status,
        "trade_date": str(trade_date),
        "candidate_count": len(unique_tickers),
        "manifest_path": str(manifest_path),
    }
