from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any
from collections.abc import Sequence


def serialize_portfolio_values(portfolio_values: Sequence[dict]) -> list[dict]:
    serialized: list[dict] = []
    for point in portfolio_values:
        payload = dict(point)
        date_value = payload.get("Date")
        if isinstance(date_value, datetime):
            payload["Date"] = date_value.strftime("%Y-%m-%d")
        serialized.append(payload)
    return serialized


class JsonlPaperTradingRecorder:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.day_count = 0
        self.executed_trade_days = 0
        self.total_executed_orders = 0

    def record(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.day_count += 1
        executed_order_count = sum(1 for quantity in payload.get("executed_trades", {}).values() if quantity)
        if executed_order_count > 0:
            self.executed_trade_days += 1
        self.total_executed_orders += executed_order_count
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def build_selection_artifact_writer(session_paths: Any, *, selection_artifact_writer_cls: type) -> Any:
    return selection_artifact_writer_cls(
        artifact_root=session_paths.selection_artifact_root,
        run_id=session_paths.output_dir_path.name,
    )
