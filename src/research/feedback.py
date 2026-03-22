from __future__ import annotations

import json
from pathlib import Path

from src.research.models import ResearchFeedbackRecord


def append_research_feedback(*, file_path: Path, record: ResearchFeedbackRecord) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")