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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.screening.scoring_feature_quality import ObservationStatus

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


@dataclass(frozen=True)
class TickerFeatureObservation:
    """Per-ticker, per-family producer observation evidence.

    Produced by ``_fetch_ticker_data`` for each data family it attempts.
    Captures the truthful outcome (success / partial / failed) and the
    authoritative non-empty row count so the manifest can distinguish a
    legal empty observation (e.g. no insider trades filed today) from a
    silent failure (exception swallowed with count zero).
    """

    ticker: str
    family: str
    status: ObservationStatus
    nonempty_count: int
    source_parts_succeeded: int
    source_parts_total: int
    failure_code: str | None = None


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


def _fetch_ticker_data(ticker: str, trade_date: str) -> list[TickerFeatureObservation]:
    """Fetch financial metrics, company news, and insider trades for one ticker.

    Returns one :class:`TickerFeatureObservation` per data family.  Each call is
    independent — a failure in one family does not block the others.  All
    exceptions are swallowed (debug-logged) so the pool never loses a worker to
    an unhandled exception, but the observation status truthfully records
    success / partial / failed so the manifest can distinguish a legal empty
    observation (e.g. no insider trades filed today) from a silent failure.
    """
    from src.tools.api import get_company_news, get_financial_metrics, get_insider_trades
    from src.data.snapshot import get_snapshot_exporter

    observations: list[TickerFeatureObservation] = []

    # Financial metrics (tushare fina_indicator) — single source, auto-writes
    # financials.json. SUCCESS even on legal empty.
    try:
        metrics = get_financial_metrics(ticker, trade_date, period="ttm", limit=10)
        nonempty = len(metrics) if metrics else 0
        observations.append(
            TickerFeatureObservation(
                ticker=ticker,
                family="financial_metrics",
                status=ObservationStatus.SUCCESS,
                nonempty_count=nonempty,
                source_parts_succeeded=1,
                source_parts_total=1,
            )
        )
    except Exception as exc:
        logger.debug("[Refresh] financial_metrics failed for %s: %s", ticker, exc)
        observations.append(
            TickerFeatureObservation(
                ticker=ticker,
                family="financial_metrics",
                status=ObservationStatus.FAILED,
                nonempty_count=0,
                source_parts_succeeded=0,
                source_parts_total=1,
                failure_code=type(exc).__name__,
            )
        )

    # Event inputs has two independent sources: company_news + insider_trades.
    # Both must be reachable to call the family SUCCESS; one failure → PARTIAL;
    # both failing → FAILED. Empty results from a reachable source are still
    # SUCCESS-shaped (event_inputs has legal-when-observed empty semantics).
    news_nonempty = 0
    news_succeeded = False
    news_error: str | None = None
    try:
        news = get_company_news(ticker, trade_date, limit=200)
        news_nonempty = len(news) if news else 0
        news_succeeded = True
    except Exception as exc:
        logger.debug("[Refresh] company_news failed for %s: %s", ticker, exc)
        news_error = type(exc).__name__

    trades_nonempty = 0
    trades_succeeded = False
    trades_error: str | None = None
    try:
        trades = get_insider_trades(ticker, trade_date, limit=200)
        if trades:
            trades_nonempty = len(trades)
            # api.py does NOT auto-write this snapshot, so export manually.
            get_snapshot_exporter().export_insider_trades(
                ticker, trade_date, trades, "tushare"
            )
        trades_succeeded = True
    except Exception as exc:
        logger.debug("[Refresh] insider_trades failed for %s: %s", ticker, exc)
        trades_error = type(exc).__name__

    succeeded_parts = int(news_succeeded) + int(trades_succeeded)
    if succeeded_parts == 2:
        event_status = ObservationStatus.SUCCESS
    elif succeeded_parts == 1:
        event_status = ObservationStatus.PARTIAL
    else:
        event_status = ObservationStatus.FAILED
    failure_code = news_error or trades_error if succeeded_parts < 2 else None
    observations.append(
        TickerFeatureObservation(
            ticker=ticker,
            family="event_inputs",
            status=event_status,
            nonempty_count=news_nonempty + trades_nonempty,
            source_parts_succeeded=succeeded_parts,
            source_parts_total=2,
            failure_code=failure_code,
        )
    )

    return observations


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

    # Per-family aggregate observation bookkeeping.
    per_family_observations: dict[str, list[TickerFeatureObservation]] = {
        "financial_metrics": [],
        "event_inputs": [],
    }
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
                        observations = future.result()
                        for observation in observations:
                            per_family_observations.setdefault(
                                observation.family, []
                            ).append(observation)
                        # A ticker counts as refresh-successful if every family
                        # it produced reached at least PARTIAL (some source was
                        # reachable). FAILED-only tickers are failure_count.
                        if observations and all(
                            obs.status is not ObservationStatus.FAILED
                            for obs in observations
                        ):
                            success_tickers.add(ticker)
                        else:
                            failure_count += 1
                    except Exception:
                        failure_count += 1
            except concurrent.futures.TimeoutError:
                pending = sum(1 for f in future_map if not f.done())
                logger.warning(
                    "[Refresh] Timeout after %ss — %d/%d tickers done, %d pending",
                    timeout_seconds, len(success_tickers), len(unique_tickers), pending,
                )

    manifest = _build_manifest(
        trade_date, unique_tickers, timeout_seconds, "completed", "tushare+akshare",
        success_count=len(success_tickers), failure_count=failure_count,
        per_family_observations=per_family_observations,
    )
    manifest_path = _write_manifest(cache_path, trade_date, manifest)

    fin_rows = sum(obs.nonempty_count for obs in per_family_observations.get("financial_metrics", []))
    event_rows = sum(obs.nonempty_count for obs in per_family_observations.get("event_inputs", []))
    logger.info(
        "[Refresh] trade_date=%s tickers=%d ok=%d fail=%d fin_metrics=%d event_rows=%d",
        trade_date, len(unique_tickers), len(success_tickers), failure_count,
        fin_rows, event_rows,
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
    per_family_observations: dict[str, list[TickerFeatureObservation]] | None = None,
) -> dict[str, Any]:
    """Build the refresh manifest.

    The ``features`` block keeps the legacy fields (``provider_failures``,
    ``rows_written``, ``source``) for backward compatibility and adds the new
    additive observation evidence fields (``observed_count`` /
    ``nonempty_count`` / ``failed_count`` / ``source_parts_succeeded`` /
    ``source_parts_total`` / ``observations``).
    """
    observations_by_family = per_family_observations or {}

    features: dict[str, Any] = {}
    for family in _FEATURE_FAMILIES:
        family_observations = observations_by_family.get(family, [])
        # Tickers that received at least a partial answer (source reachable).
        observed_count = sum(
            1
            for obs in family_observations
            if obs.status in (ObservationStatus.SUCCESS, ObservationStatus.PARTIAL)
        )
        # Authoritative nonempty rows across observed tickers.
        nonempty_count = sum(obs.nonempty_count for obs in family_observations)
        # Tickers whose every source part failed.
        failed_count = sum(
            1 for obs in family_observations if obs.status is ObservationStatus.FAILED
        )
        source_parts_succeeded = sum(obs.source_parts_succeeded for obs in family_observations)
        source_parts_total = sum(obs.source_parts_total for obs in family_observations)

        # Backward-compatible legacy fields. For families we actually refreshed
        # (financial_metrics, event_inputs) we derive rows_written from the
        # observation nonempty_count so the legacy field stays truthful. Other
        # families are local-cache only at score time, so their legacy fields
        # remain 0 / "local_cache".
        if family == "financial_metrics":
            legacy_rows = nonempty_count if family_observations else fin_rows
            legacy_failures = failed_count
            legacy_source = source
        elif family == "event_inputs":
            legacy_rows = nonempty_count if family_observations else event_rows
            legacy_failures = failed_count
            legacy_source = source
        else:
            legacy_rows = 0
            legacy_failures = 0
            legacy_source = "local_cache"

        family_entry: dict[str, Any] = {
            # Legacy fields — preserved for backward compatibility with
            # ScoringFeatureStore._quality_for_family and any external reader
            # that still consumes the flat counters.
            "provider_failures": legacy_failures,
            "rows_written": legacy_rows,
            "source": legacy_source,
            # New additive observation evidence. Downstream consumers
            # (assess_auto_quality via build_quality_summary) prefer these; the
            # legacy fields are kept only for compatibility.
            "observed_count": observed_count,
            "nonempty_count": nonempty_count,
            "failed_count": failed_count,
            "source_parts_succeeded": source_parts_succeeded,
            "source_parts_total": source_parts_total,
        }
        features[family] = family_entry

    manifest: dict[str, Any] = {
        "trade_date": str(trade_date),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "candidate_count": len(tickers),
        "timeout_seconds": float(timeout),
        "status": status,
        "success_count": success_count,
        "failure_count": failure_count,
        "features": features,
    }
    return manifest


def _write_manifest(cache_path: Path, trade_date: str, manifest: dict[str, Any]) -> Path:
    manifest_path = cache_path / f"feature_manifest_{trade_date}.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path
