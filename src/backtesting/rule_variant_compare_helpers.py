from __future__ import annotations

import json
import logging
from pathlib import Path
from statistics import mean

logger = logging.getLogger(__name__)


def load_pipeline_day_events(timing_log_path: Path) -> list[dict]:
    """Load ``pipeline_day_timing`` events from a JSONL timing log.

    R102 (R88/BH-017 family JSONL drain): a bare ``json.loads(line)`` previously
    raised ``JSONDecodeError`` on a single corrupt/truncated line (left behind
    by a process interrupted mid-write of one timing record), aborting the whole
    rule-variant comparison CLI even though every other line in the log was
    valid. Skip the corrupt line + warning so the operator can distinguish
    "no events" vs "some lines corrupt"; keep all valid lines. Mirrors the R60
    pagination-break principle (skip bad entry, keep good entries).
    """
    pipeline_day_events: list[dict] = []
    with timing_log_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "[RuleVariantCompare] 跳过 timing log %s 的损坏行: %s",
                    timing_log_path,
                    exc,
                )
                continue
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
