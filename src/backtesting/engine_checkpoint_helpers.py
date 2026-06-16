from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from src.execution.models import ExecutionPlan, PendingOrder

logger = logging.getLogger(__name__)


def serialize_portfolio_values(portfolio_values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for point in portfolio_values:
        payload = dict(point)
        date_value = payload.get("Date")
        if isinstance(date_value, datetime):
            payload["Date"] = date_value.strftime("%Y-%m-%d")
        serialized.append(payload)
    return serialized


def deserialize_portfolio_values(portfolio_values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    restored_values: list[dict[str, Any]] = []
    for item in portfolio_values:
        restored = dict(item)
        date_value = restored.get("Date")
        if isinstance(date_value, str) and date_value:
            restored["Date"] = datetime.strptime(date_value, "%Y-%m-%d")
        restored_values.append(restored)
    return restored_values


def build_checkpoint_payload(
    *,
    last_processed_date: str,
    portfolio_snapshot: dict[str, Any],
    portfolio_values: list[dict[str, Any]],
    performance_metrics: dict[str, Any],
    pending_buy_queue: list[PendingOrder],
    pending_sell_queue: list[PendingOrder],
    exit_reentry_cooldowns: dict[str, dict],
    pending_plan: ExecutionPlan | None,
) -> dict[str, Any]:
    return {
        "last_processed_date": last_processed_date,
        "portfolio_snapshot": portfolio_snapshot,
        "portfolio_values": serialize_portfolio_values(portfolio_values),
        "performance_metrics": dict(performance_metrics),
        "pending_buy_queue": [order.model_dump() for order in pending_buy_queue],
        "pending_sell_queue": [order.model_dump() for order in pending_sell_queue],
        "exit_reentry_cooldowns": dict(exit_reentry_cooldowns),
        "pending_plan": pending_plan.model_dump() if pending_plan is not None else None,
    }


def write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write *payload* to *path*.

    C2-BH1: a crash mid-write (SIGKILL / OOM / disk-full) on a plain
    ``path.write_text`` leaves a truncated/empty checkpoint at the canonical
    path. The recovery chain then wedges: ``reset_output_artifacts_for_fresh_run``
    sees ``checkpoint_path.exists()`` is True and skips cleanup, while
    ``read_checkpoint`` raises ``JSONDecodeError`` on the truncated file. Using
    temp-file + ``os.replace`` (atomic on POSIX, same mount point) guarantees
    the canonical path is always either the previous valid checkpoint or the
    complete new one — never a partial write. Matches the established pattern in
    ``screening/watchlist.py`` and ``screening/recommendation_tracker.py``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = str(path.parent)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=tmp_dir, delete=False, suffix=".tmp") as tmp:
        tmp.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = tmp.name
    try:
        os.replace(tmp_path, path)
    except OSError:
        # If the atomic rename fails (extremely rare on same mount point), clean
        # up the temp file so it cannot accumulate; re-raise so the caller knows
        # the checkpoint was not persisted.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_checkpoint(path: Path) -> dict[str, Any]:
    """Read a checkpoint, degrading gracefully on a corrupt/missing file.

    C2-BH1: a checkpoint that was truncated by a crash (or otherwise corrupt)
    must NOT raise ``JSONDecodeError`` and wedge the resume path. Instead it is
    quarantined aside (``<name>.corrupt``) and treated as missing, so the engine
    falls through to a fresh run rather than wedging the session. A missing path
    also returns ``{}`` for defensive callers.
    """
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(
            "read_checkpoint: corrupt checkpoint at %s (%s); quarantining and "
            "treating as missing so the session can start fresh.",
            path, exc,
        )
        corrupt_path = path.with_suffix(path.suffix + ".corrupt")
        try:
            path.replace(corrupt_path)
        except OSError as rename_exc:
            logger.warning("read_checkpoint: could not quarantine corrupt %s: %s", path, rename_exc)
            try:
                path.unlink()
            except OSError:
                pass
        return {}


def restore_pending_orders(payloads: list[dict[str, Any]]) -> list[PendingOrder]:
    return [PendingOrder.model_validate(item) for item in payloads]


def restore_exit_reentry_cooldowns(payload: dict[str, dict[str, Any]]) -> dict[str, dict]:
    return {
        str(ticker): dict(item or {})
        for ticker, item in payload.items()
    }


def restore_pending_plan(payload: dict[str, Any] | None) -> ExecutionPlan | None:
    return ExecutionPlan.model_validate(payload) if payload else None
