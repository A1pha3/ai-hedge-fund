"""Live BTST setup-output logger — out-of-sample accumulation.

Every ``--daily-action`` run appends the full scanned candidate set (both
plan-eligible and filtered-out) with the setup's structured diagnostics
(``trigger_strength``, fund flow, pre-runup, industry, thresholds) to a per-day
JSONL file. Over time this accumulates a real out-of-sample record of the FULL
setup's live outputs so cross-cycle robustness can eventually be validated on
genuine forward data (the retroactive replay is blocked by thin historical
fund-flow/industry depth).

Design:
  - one file per signal day (``YYYYMMDD.jsonl``), atomically overwritten on
    rerun → idempotent, never duplicates;
  - append-only across days; forward returns are joined later from price_cache;
  - never raises into the trading path (best-effort observation).
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
_DEFAULT_DIR = Path("data/reports/setup_output_log")


def _finite(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _record(action: Any, *, signal_date: str, regime: str, plan_eligible: bool, logged_at: str) -> dict:
    md = getattr(action, "metadata", None) or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "signal_date": signal_date,
        "logged_at": logged_at,
        "ticker": str(getattr(action, "ticker", "")),
        "setup": str(getattr(action, "setup", "")),
        "plan_eligible": bool(plan_eligible),
        "degraded": bool(getattr(action, "degraded", False)),
        "trigger_strength": _finite(getattr(action, "trigger_strength", 0.0)),
        "entry_price": _finite(getattr(action, "entry_price", 0.0)),
        "kelly_pct": _finite(getattr(action, "kelly_pct", 0.0)),
        "regime": str(regime),
        "block_reason": str(getattr(action, "block_reason", "") or ""),
        "degradation_reason": str(getattr(action, "degradation_reason", "") or ""),
        # Flattened setup diagnostics (present only for detected candidates).
        "pct_change": _finite(md.get("pct_change")),
        "main_net_inflow": _finite(md.get("main_net_inflow")),
        "industry_pct": _finite(md.get("industry_pct")),
        "pre_5d_runup_pct": _finite(md.get("pre_5d_runup_pct")),
        "limit_up_pct_threshold": _finite(md.get("limit_up_pct_threshold")),
    }


def log_setup_outputs(
    signal_date: date,
    candidates: Iterable[Any],
    blocked: Iterable[Any],
    *,
    regime: str = "unknown",
    out_dir: Path | str = _DEFAULT_DIR,
) -> Path:
    """Persist the full scanned setup output for ``signal_date`` (idempotent).

    ``candidates`` are the plan-eligible actions; ``blocked`` are the
    filtered-out / degraded ones. Returns the written per-day file path.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    compact = signal_date.strftime("%Y%m%d")
    logged_at = datetime.now(timezone.utc).isoformat()

    records = [
        _record(a, signal_date=compact, regime=regime, plan_eligible=True, logged_at=logged_at)
        for a in candidates
    ] + [
        _record(a, signal_date=compact, regime=regime, plan_eligible=False, logged_at=logged_at)
        for a in blocked
    ]

    payload = "\n".join(
        json.dumps(rec, ensure_ascii=False, allow_nan=False, sort_keys=True) for rec in records
    )
    if payload:
        payload += "\n"

    target = out / f"{compact}.jsonl"
    fd, tmp = tempfile.mkstemp(dir=str(out), prefix=f".{compact}_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target
