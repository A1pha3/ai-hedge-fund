"""Best-effort scoring feature refresh boundary.

Fetches financial metrics, company news, and insider trades via the sync
data layer (``src.tools.api``) and writes them as local snapshots via
``DataSnapshotExporter``.  Score time never depends on refresh success —
``ScoringFeatureStore`` with ``allow_stale=True`` falls back to recent
snapshots when the refresh is partial or fails entirely.

Architecture: the sync path (``api.py`` → ``tushare_api`` / ``akshare_api``)
is the production data gateway.  Each ``get_*`` function auto-writes snapshots
as a side effect when ``DATA_SNAPSHOT_ENABLED=true``.  The one exception is
``get_insider_trades`` (no ``export_insider_trades`` call in api.py), so we
export manually here.
"""

from __future__ import annotations

import concurrent.futures
import importlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FEATURE_FAMILIES = (
    "price_history",
    "financial_metrics",
    "event_inputs",
    "industry_pe_medians",
    "dragon_tiger_bonus",
    "intraday_short_trade_metrics",
    "daily_fund_flow_metrics",
)

_MAX_WORKERS = int(os.environ.get("SCORING_REFRESH_CONCURRENCY", "4"))


def _refresh_enabled() -> bool:
    raw = os.environ.get("AUTO_OPTIONAL_FEATURE_REFRESH", "1")
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _enable_snapshots() -> None:
    """Enable DataSnapshotExporter and reset singleton to pick up new config.

    ``SnapshotConfig`` reads ``DATA_SNAPSHOT_ENABLED`` at init time.  If the
    singleton was already created (by an earlier ``api.py`` call) with
    ``enabled=False``, setting the env var alone won't help — we must clear
    ``_instance`` so the next ``DataSnapshotExporter()`` call re-reads config.
    """
    os.environ.setdefault("DATA_SNAPSHOT_ENABLED", "true")
    try:
        snapshot_module = importlib.import_module("src.data.snapshot")
        snapshot_module.DataSnapshotExporter._instance = None
    except Exception:
        pass


def _fetch_ticker_data(ticker: str, trade_date: str) -> dict[str, int]:
    """Fetch financial metrics, company news, and insider trades for one ticker.

    Returns counts per family.  Each call is independent — a failure in one
    family does not block the others.  All exceptions are swallowed (debug-logged)
    so the pool never loses a worker to an unhandled exception.
    """
    from src.tools.api import get_company_news, get_financial_metrics, get_insider_trades
    from src.data.snapshot import get_snapshot_exporter

    counts = {"financial_metrics": 0, "company_news": 0, "insider_trades": 0}

    # Financial metrics (tushare fina_indicator) — auto-writes financials.json.
    try:
        metrics = get_financial_metrics(ticker, trade_date, period="ttm", limit=10)
        counts["financial_metrics"] = len(metrics) if metrics else 0
    except Exception as exc:
        logger.debug("[Refresh] financial_metrics failed for %s: %s", ticker, exc)

    # Company news (akshare for A-shares) — auto-writes company_news.json.
    try:
        news = get_company_news(ticker, trade_date, limit=200)
        counts["company_news"] = len(news) if news else 0
    except Exception as exc:
        logger.debug("[Refresh] company_news failed for %s: %s", ticker, exc)

    # Insider trades (tushare stk_holdertrade) — api.py does NOT auto-write
    # this snapshot, so we export manually via the new export_insider_trades.
    try:
        trades = get_insider_trades(ticker, trade_date, limit=200)
        if trades:
            counts["insider_trades"] = len(trades)
            get_snapshot_exporter().export_insider_trades(
                ticker, trade_date, trades, "tushare"
            )
    except Exception as exc:
        logger.debug("[Refresh] insider_trades failed for %s: %s", ticker, exc)

    return counts


def refresh_scoring_features(
    trade_date: str,
    tickers: list[str],
    *,
    timeout_seconds: float = 180.0,
    cache_dir: Path | str = "data/feature_cache",
) -> dict[str, Any]:
    """Refresh scoring features for the given tickers and trade date.

    Fetches financial metrics, company news, and insider trades concurrently
    via the sync data layer.  Results are written as local snapshots that
    ``ScoringFeatureStore`` reads at score time.  Best-effort: partial failures
    are logged but never block the pipeline.
    """
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    unique_tickers = sorted({str(t).split(".")[0].zfill(6) for t in tickers})

    if not _refresh_enabled() or not unique_tickers:
        status = "skipped"
        manifest = _build_manifest(trade_date, unique_tickers, timeout_seconds, status, "not_refreshed")
        manifest_path = _write_manifest(cache_path, trade_date, manifest)
        return {"status": status, "trade_date": str(trade_date),
                "candidate_count": len(unique_tickers), "manifest_path": str(manifest_path)}

    _enable_snapshots()

    total_counts: dict[str, int] = {"financial_metrics": 0, "company_news": 0, "insider_trades": 0}
    success_tickers: set[str] = set()
    failure_count = 0

    max_workers = min(_MAX_WORKERS, len(unique_tickers))
    if max_workers > 0:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(_fetch_ticker_data, t, str(trade_date)): t
                for t in unique_tickers
            }
            try:
                for future in concurrent.futures.as_completed(future_map, timeout=timeout_seconds):
                    ticker = future_map[future]
                    try:
                        counts = future.result()
                        if any(v > 0 for v in counts.values()):
                            success_tickers.add(ticker)
                        for key, val in counts.items():
                            total_counts[key] += val
                    except Exception:
                        failure_count += 1
            except concurrent.futures.TimeoutError:
                pending = sum(1 for f in future_map if not f.done())
                logger.warning(
                    "[Refresh] Timeout after %ss — %d/%d tickers done, %d pending",
                    timeout_seconds, len(success_tickers), len(unique_tickers), pending,
                )

    event_rows = total_counts["company_news"] + total_counts["insider_trades"]
    manifest = _build_manifest(
        trade_date, unique_tickers, timeout_seconds, "completed", "tushare+akshare",
        success_count=len(success_tickers), failure_count=failure_count,
        fin_rows=total_counts["financial_metrics"], event_rows=event_rows,
    )
    manifest_path = _write_manifest(cache_path, trade_date, manifest)

    logger.info(
        "[Refresh] trade_date=%s tickers=%d ok=%d fail=%d fin_metrics=%d news=%d trades=%d",
        trade_date, len(unique_tickers), len(success_tickers), failure_count,
        total_counts["financial_metrics"], total_counts["company_news"], total_counts["insider_trades"],
    )

    return {
        "status": "completed",
        "trade_date": str(trade_date),
        "candidate_count": len(unique_tickers),
        "success_count": len(success_tickers),
        "failure_count": failure_count,
        "manifest_path": str(manifest_path),
    }


def _build_manifest(
    trade_date: str,
    tickers: list[str],
    timeout: float,
    status: str,
    source: str,
    *,
    success_count: int = 0,
    failure_count: int = 0,
    fin_rows: int = 0,
    event_rows: int = 0,
) -> dict[str, Any]:
    return {
        "trade_date": str(trade_date),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "candidate_count": len(tickers),
        "timeout_seconds": float(timeout),
        "status": status,
        "success_count": success_count,
        "failure_count": failure_count,
        "features": {
            family: {
                "provider_failures": failure_count if family in ("financial_metrics", "event_inputs") else 0,
                "rows_written": (
                    fin_rows if family == "financial_metrics"
                    else event_rows if family == "event_inputs"
                    else 0
                ),
                "source": source if family in ("financial_metrics", "event_inputs") else "local_cache",
            }
            for family in _FEATURE_FAMILIES
        },
    }


def _write_manifest(cache_path: Path, trade_date: str, manifest: dict[str, Any]) -> Path:
    manifest_path = cache_path / f"feature_manifest_{trade_date}.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path
