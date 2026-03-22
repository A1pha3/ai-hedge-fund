import json
from pathlib import Path

from src.paper_trading.runtime import _write_research_feedback_summary
from src.research.feedback import append_research_feedback
from src.research.models import ResearchFeedbackRecord


def test_write_research_feedback_summary_persists_summary_file(tmp_path: Path):
    artifact_root = tmp_path / "selection_artifacts"
    feedback_file = artifact_root / "2026-03-22" / "research_feedback.jsonl"

    append_research_feedback(
        file_path=feedback_file,
        record=ResearchFeedbackRecord(
            run_id="session_001",
            trade_date="2026-03-22",
            symbol="300724",
            reviewer="researcher_a",
            review_status="final",
            primary_tag="high_quality_selection",
            tags=["thesis_clear"],
            confidence=0.88,
            research_verdict="selected_for_good_reason",
            created_at="2026-03-22T21:00:00+08:00",
        ),
    )

    summary_payload, summary_path = _write_research_feedback_summary(artifact_root)

    persisted = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary_path == artifact_root / "research_feedback_summary.json"
    assert summary_payload["overall"]["feedback_count"] == 1
    assert summary_payload["by_trade_date"]["2026-03-22"]["feedback_count"] == 1
    assert persisted == summary_payload