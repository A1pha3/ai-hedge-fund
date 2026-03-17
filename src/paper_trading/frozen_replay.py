from __future__ import annotations

import json
from pathlib import Path

from src.execution.models import ExecutionPlan


def load_frozen_post_market_plans(daily_events_path: str | Path) -> dict[str, ExecutionPlan]:
    source_path = Path(daily_events_path).resolve()
    plans_by_date: dict[str, ExecutionPlan] = {}

    with source_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            current_plan_payload = payload.get("current_plan")
            if not current_plan_payload:
                continue
            trade_date = str(payload.get("trade_date") or current_plan_payload.get("date") or "")
            if not trade_date:
                continue
            plans_by_date[trade_date] = ExecutionPlan.model_validate(current_plan_payload)

    if not plans_by_date:
        raise ValueError(f"No current_plan records found in frozen replay source: {source_path}")

    return plans_by_date