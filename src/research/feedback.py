from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from src.research.models import ResearchFeedbackRecord, ResearchFeedbackSummary


def append_research_feedback(*, file_path: Path, record: ResearchFeedbackRecord) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")


def read_research_feedback(*, file_path: Path, skip_invalid: bool = False) -> list[ResearchFeedbackRecord]:
    if not file_path.exists():
        return []

    records: list[ResearchFeedbackRecord] = []
    with file_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                records.append(ResearchFeedbackRecord.model_validate(payload))
            except (json.JSONDecodeError, ValidationError) as error:
                if skip_invalid:
                    continue
                raise ValueError(f"Invalid research feedback record at {file_path}:{line_number}: {error}") from error
    return records


def summarize_research_feedback(*, records: list[ResearchFeedbackRecord] | None = None, file_path: Path | None = None, skip_invalid: bool = False) -> ResearchFeedbackSummary:
    if records is None:
        if file_path is None:
            raise ValueError("Either records or file_path must be provided")
        records = read_research_feedback(file_path=file_path, skip_invalid=skip_invalid)
    return ResearchFeedbackSummary.from_records(records)