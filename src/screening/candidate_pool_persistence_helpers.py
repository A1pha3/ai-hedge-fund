from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from collections.abc import Callable


def load_candidate_pool_snapshot(snapshot_path: Path, *, candidate_stock_cls: type) -> list[Any]:
    with open(snapshot_path, encoding="utf-8") as f:
        data = json.load(f)
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
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump([candidate.model_dump() for candidate in candidates], f, ensure_ascii=False, indent=2)


def load_candidate_pool_shadow_snapshot(
    snapshot_path: Path,
    *,
    candidate_stock_cls: type,
    normalize_shadow_summary_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    with open(snapshot_path, encoding="utf-8") as f:
        payload = json.load(f)
    shadow_candidates = [candidate_stock_cls(**item) for item in list(payload.get("shadow_candidates") or [])]
    return {
        "selected_candidates": [candidate_stock_cls(**item) for item in list(payload.get("selected_candidates") or [])],
        "shadow_candidates": shadow_candidates,
        "shadow_summary": normalize_shadow_summary_fn(
            dict(payload.get("shadow_summary") or {}),
            shadow_candidates=shadow_candidates,
        ),
    }


def write_candidate_pool_shadow_snapshot(
    snapshot_path: Path,
    *,
    selected_candidates: list[Any],
    shadow_candidates: list[Any],
    shadow_summary: dict[str, Any],
    snapshot_dir: Path,
) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "selected_candidates": [candidate.model_dump() for candidate in selected_candidates],
                "shadow_candidates": [candidate.model_dump() for candidate in shadow_candidates],
                "shadow_summary": shadow_summary,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def load_cooldown_registry(cooldown_file: Path) -> dict[str, str]:
    if cooldown_file.exists():
        try:
            with open(cooldown_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_cooldown_registry(registry: dict[str, str], *, cooldown_file: Path, snapshot_dir: Path) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    with open(cooldown_file, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


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
