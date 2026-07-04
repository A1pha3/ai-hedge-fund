from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _atomic_write_json(path: Path, payload: Any) -> None:
    """Write JSON atomically: serialize to a temp file in the same directory, then
    ``os.replace`` onto the final path. A crash during serialization leaves the
    previous file intact instead of a truncated/corrupt file (R93: prevents the
    BH-017/R88 corrupted-state crash family on the candidate-pool front door)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Named temp file in the same dir so os.replace is atomic on the same filesystem.
    fd, tmp_name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except BaseException:
        # Clean up the temp file on any failure; never leave a half-written tmp behind.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _safe_load_json(path: Path, *, fallback: Any, context: str) -> Any:
    """Load JSON with corruption tolerance: a missing or truncated/corrupt file
    (from a previously interrupted non-atomic write) returns ``fallback`` with a
    warning instead of crashing the caller (R93 BH-017/R88 family)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return fallback
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "candidate-pool state file %s is corrupt or unreadable (%s); " "falling back to empty %s — a previous write may have been interrupted",
            path,
            exc,
            context,
        )
        return fallback


def load_candidate_pool_snapshot(snapshot_path: Path, *, candidate_stock_cls: type) -> list[Any]:
    data = _safe_load_json(snapshot_path, fallback=[], context="candidate list")
    return [candidate_stock_cls(**item) for item in data]


def normalize_shadow_summary(shadow_summary: dict[str, Any], *, shadow_candidates: list[Any]) -> dict[str, Any]:
    normalized_summary = dict(shadow_summary or {})
    if "shadow_recall_complete" in normalized_summary and "shadow_recall_status" in normalized_summary:
        return normalized_summary

    has_shadow_entries = bool(normalized_summary.get("tickers")) or bool(shadow_candidates)
    if has_shadow_entries:
        normalized_summary.setdefault("shadow_recall_complete", True)
        normalized_summary.setdefault("shadow_recall_status", "computed_legacy")
        return normalized_summary

    normalized_summary.setdefault("shadow_recall_complete", False)
    normalized_summary.setdefault("shadow_recall_status", "legacy_unknown")
    return normalized_summary


def write_candidate_pool_snapshot(snapshot_path: Path, candidates: list[Any], *, snapshot_dir: Path) -> None:
    _atomic_write_json(
        snapshot_path,
        [candidate.model_dump() for candidate in candidates],
    )


def load_candidate_pool_shadow_snapshot(
    snapshot_path: Path,
    *,
    candidate_stock_cls: type,
    normalize_shadow_summary_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    payload = _safe_load_json(
        snapshot_path,
        fallback={"selected_candidates": [], "shadow_candidates": [], "shadow_summary": {}},
        context="shadow snapshot",
    )
    shadow_summary_payload = dict(payload.get("shadow_summary") or {})
    shadow_summary_rows = {str(entry.get("ticker") or "").strip(): dict(entry) for entry in list(shadow_summary_payload.get("tickers") or []) if str(dict(entry).get("ticker") or "").strip()}
    shadow_candidates = [candidate_stock_cls(**_hydrate_shadow_candidate_payload(dict(item), shadow_summary_rows.get(str(dict(item).get("ticker") or "").strip()))) for item in list(payload.get("shadow_candidates") or [])]
    return {
        "selected_candidates": [candidate_stock_cls(**item) for item in list(payload.get("selected_candidates") or [])],
        "shadow_candidates": shadow_candidates,
        "shadow_summary": normalize_shadow_summary_fn(
            shadow_summary_payload,
            shadow_candidates=shadow_candidates,
        ),
    }


def _hydrate_shadow_candidate_payload(candidate_payload: dict[str, Any], summary_row: dict[str, Any] | None) -> dict[str, Any]:
    if not summary_row:
        return candidate_payload

    hydrated_payload = dict(candidate_payload)
    field_mapping = {
        "candidate_pool_rank": "candidate_pool_rank",
        "candidate_pool_lane": "candidate_pool_lane",
        "candidate_pool_shadow_reason": "candidate_pool_shadow_reason",
        "avg_amount_share_of_cutoff": "candidate_pool_avg_amount_share_of_cutoff",
        "avg_amount_share_of_min_gate": "candidate_pool_avg_amount_share_of_min_gate",
        "shadow_focus_selected": "shadow_focus_selected",
        "shadow_focus_relaxed_band": "shadow_focus_relaxed_band",
        "shadow_visibility_gap_selected": "shadow_visibility_gap_selected",
        "shadow_visibility_gap_relaxed_band": "shadow_visibility_gap_relaxed_band",
        "source_layer_release_stage": "source_layer_release_stage",
        "source_layer_release_reason": "source_layer_release_reason",
    }
    for summary_key, candidate_key in field_mapping.items():
        if summary_key in summary_row:
            hydrated_payload[candidate_key] = summary_row.get(summary_key)
    return hydrated_payload


def write_candidate_pool_shadow_snapshot(
    snapshot_path: Path,
    *,
    selected_candidates: list[Any],
    shadow_candidates: list[Any],
    shadow_summary: dict[str, Any],
    snapshot_dir: Path,
) -> None:
    _atomic_write_json(
        snapshot_path,
        {
            "selected_candidates": [candidate.model_dump() for candidate in selected_candidates],
            "shadow_candidates": [candidate.model_dump() for candidate in shadow_candidates],
            "shadow_summary": shadow_summary,
        },
    )


def load_cooldown_registry(cooldown_file: Path) -> dict[str, str]:
    # Delegate to the canonical corruption-tolerant loader so cooldown state and
    # candidate-pool snapshots share one consistent read path (R93/R87 dedupe).
    return _safe_load_json(cooldown_file, fallback={}, context="cooldown registry")


def save_cooldown_registry(registry: dict[str, str], *, cooldown_file: Path, snapshot_dir: Path) -> None:
    _atomic_write_json(cooldown_file, registry)


def add_cooldown(
    ticker: str,
    trade_date: str,
    *,
    days: int,
    load_cooldown_registry_fn: Callable[[], dict[str, str]],
    save_cooldown_registry_fn: Callable[[dict[str, str]], None],
) -> None:
    registry = load_cooldown_registry_fn()
    dt = datetime.strptime(trade_date, "%Y%m%d")
    expire_dt = dt + timedelta(days=int(days * 1.5))
    registry[ticker] = expire_dt.strftime("%Y%m%d")
    save_cooldown_registry_fn(registry)


def get_cooled_tickers(
    trade_date: str,
    *,
    load_cooldown_registry_fn: Callable[[], dict[str, str]],
    save_cooldown_registry_fn: Callable[[dict[str, str]], None],
) -> set[str]:
    registry = load_cooldown_registry_fn()
    cooled: set[str] = set()
    expired: list[str] = []
    for ticker, expire_date in registry.items():
        if expire_date > trade_date:
            cooled.add(ticker)
        else:
            expired.append(ticker)
    if expired:
        for ticker in expired:
            del registry[ticker]
        save_cooldown_registry_fn(registry)
    return cooled
