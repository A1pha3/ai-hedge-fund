"""#1 wire BTST picks → tracking_history — realized-evidence bridge.

BTST reports live in ``outputs/`` with picks in ``operator_summary.json`` (string
format "002222 福晶科技"). calibration / reconcile / P-3 read
``data/reports/tracking_history.json``. This bridge closes the gap: extracts BTST
picks across all date dirs, seeds them into tracking_history as recommendations,
then the existing ``update_tracking_history`` Phase 2 (R164-fixed tushare path)
backfills their realized T+1/T+5/.../T+30 returns.

This jump-starts the calibration dataset with ACTUAL BTST outcomes from reports
that already exist, instead of waiting weeks for the daily cron to accumulate.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

from src.screening.consecutive_recommendation import resolve_report_dir
from src.screening.recommendation_tracker import (
    HISTORY_FILENAME,
    _load_history,
    _record_key,
    fetch_actual_returns,
)

logger = logging.getLogger(__name__)

_TICKER_RE = re.compile(r"^(\d{6})")


def _extract_btst_picks(outputs_dir: Path) -> list[tuple[str, str, str]]:
    """Walk BTST output dirs, extract (signal_date, ticker, name) from operator_summary.

    Picks come from execution.formal_selected_tickers + confirmation_only_tickers
    (deduped). The string format is "002222 福晶科技" → ticker="002222", name="福晶科技".
    Only dirs containing ``operator_summary.json`` are read.
    """
    picks: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    if not outputs_dir.exists():
        return picks
    for ops_path in sorted(outputs_dir.glob("*/operator_summary.json")):
        try:
            payload = json.loads(ops_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        signal_date = str(payload.get("signal_date") or payload.get("decision_date") or "")
        signal_date = signal_date.replace("-", "")[:8]
        if len(signal_date) != 8:
            continue
        execution = payload.get("execution") or {}
        pick_strings: list[str] = []
        for field in ("formal_selected_tickers", "confirmation_only_tickers", "orderable_tickers"):
            pick_strings.extend(execution.get(field) or [])
        for raw in pick_strings:
            match = _TICKER_RE.match(str(raw).strip())
            if not match:
                continue
            ticker = match.group(1)
            name = str(raw).strip()[6:].strip()  # rest after the 6-digit code
            key = (signal_date, ticker)
            if key in seen:
                continue
            seen.add(key)
            picks.append((signal_date, ticker, name))
    return picks


def backfill_btst_realized(
    *,
    outputs_dir: Path,
    reports_dir: Path | None = None,
    as_of_date: str,
    use_data_fetcher: Callable[[str, str, str], list[dict[str, Any]]] | None = None,
) -> int:
    """Seed BTST picks into tracking_history, then backfill realized returns.

    Idempotent: if a (ticker, signal_date) record already exists in tracking_history,
    it's not duplicated — only the realized-returns backfill runs on it.

    Args:
        outputs_dir: ``outputs/`` dir containing BTST report subdirs
        reports_dir: ``data/reports`` dir (None → resolve_report_dir())
        as_of_date: the "today" for realized-returns backfill (YYYYMMDD)
        use_data_fetcher: injectable fetcher (testing); default uses R164 tushare path

    Returns:
        Number of BTST picks seeded (new records). Existing records that only got
        their realized returns updated are NOT counted (only genuinely new seeds).
    """
    search_dir = reports_dir or resolve_report_dir()
    picks = _extract_btst_picks(outputs_dir)
    if not picks:
        return 0

    history_path = search_dir / HISTORY_FILENAME
    history = _load_history(history_path)
    index: dict[tuple[str, str], dict[str, Any]] = {_record_key(r): r for r in history}

    # Phase 1: seed BTST picks as tracking records (idempotent — skip if exists)
    seeded = 0
    for signal_date, ticker, name in picks:
        key = (ticker, signal_date)
        if key in index:
            continue
        record = {
            "ticker": ticker,
            "name": name,
            "recommended_date": signal_date,
            "recommended_price": 0.0,
            "recommendation_score": 0.0,  # BTST picks don't carry score_b in operator_summary
            "next_day_price": None,
            "next_day_return": None,
            "next_3day_return": None,
            "next_5day_return": None,
            "next_10day_return": None,
            # Task 4: T+15 / T+25 horizons (multi-horizon diagnosis plan).
            "next_15day_return": None,
            "next_20day_return": None,
            "next_25day_return": None,
            "next_30day_return": None,
            "tracking_status": "pending",
            "source": "btst",
        }
        index[key] = record
        history.append(record)
        seeded += 1

    # Phase 2: backfill realized returns (delegates to fetch_actual_returns → R164 path)
    pending_tickers_by_date: dict[str, list[str]] = {}
    for rec in history:
        if rec.get("tracking_status") == "complete" and rec.get("next_30day_return") is not None:
            continue
        rd = str(rec.get("recommended_date") or "")
        if not rd:
            continue
        pending_tickers_by_date.setdefault(rd, []).append(str(rec.get("ticker") or ""))

    for rec_date, tickers in pending_tickers_by_date.items():
        if not tickers:
            continue
        returns_map = fetch_actual_returns(
            tickers=tickers,
            from_date=rec_date,
            to_date=as_of_date,
            use_data_fetcher=use_data_fetcher,
        )
        for ticker, returns in returns_map.items():
            key = (ticker, rec_date)
            target = index.get(key)
            if target is None:
                continue
            for field_key, day_key in (
                ("next_day_return", "day_1"),
                ("next_3day_return", "day_3"),
                ("next_5day_return", "day_5"),
                ("next_10day_return", "day_10"),
                # Task 4: T+15 / T+25 horizon mapping.
                ("next_15day_return", "day_15"),
                ("next_20day_return", "day_20"),
                ("next_25day_return", "day_25"),
                ("next_30day_return", "day_30"),
            ):
                fetched = returns.get(day_key)
                if fetched is not None and target.get(field_key) is None:
                    target[field_key] = fetched

    # Persist
    search_dir.mkdir(parents=True, exist_ok=True)
    payload = {"records": history, "updated_at": as_of_date}
    tmp_path = history_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(history_path)

    logger.info("[btst_bridge] seeded %d BTST picks into tracking_history", seeded)
    return seeded


__all__ = ["backfill_btst_realized", "_extract_btst_picks"]
