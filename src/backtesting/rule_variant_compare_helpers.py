from __future__ import annotations

from pathlib import Path
import json
from statistics import mean


def load_pipeline_day_events(timing_log_path: Path) -> list[dict]:
    pipeline_day_events: list[dict] = []
    with timing_log_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if payload.get("event") == "pipeline_day_timing":
                pipeline_day_events.append(payload)
    return pipeline_day_events


def extract_numeric_path(payload: dict, path: tuple[str, ...]) -> float | None:
    current = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    if isinstance(current, (int, float)):
        return float(current)
    return None


def average_numeric_path(events: list[dict], path: tuple[str, ...]) -> float | None:
    values = [value for event in events if (value := extract_numeric_path(event, path)) is not None]
    return mean(values) if values else None


def count_positive_numeric_path(events: list[dict], path: tuple[str, ...]) -> int:
    return sum(1 for event in events if (value := extract_numeric_path(event, path)) is not None and value > 0)
