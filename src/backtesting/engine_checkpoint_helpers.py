from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from src.execution.models import ExecutionPlan, PendingOrder


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def read_checkpoint(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def restore_pending_orders(payloads: list[dict[str, Any]]) -> list[PendingOrder]:
    return [PendingOrder.model_validate(item) for item in payloads]


def restore_exit_reentry_cooldowns(payload: dict[str, dict[str, Any]]) -> dict[str, dict]:
    return {
        str(ticker): dict(item or {})
        for ticker, item in payload.items()
    }


def restore_pending_plan(payload: dict[str, Any] | None) -> ExecutionPlan | None:
    return ExecutionPlan.model_validate(payload) if payload else None
