from pathlib import Path

import pytest

from src.research.feedback import append_research_feedback, read_research_feedback, summarize_research_feedback
from src.research.models import ResearchFeedbackRecord


def test_feedback_roundtrip_and_summary(tmp_path: Path):
    feedback_path = tmp_path / "research_feedback.jsonl"

    append_research_feedback(
        file_path=feedback_path,
        record=ResearchFeedbackRecord(
            run_id="session_001",
            trade_date="2026-03-22",
            symbol="300724",
            reviewer="researcher_a",
            review_status="final",
            primary_tag="high_quality_selection",
            tags=["thesis_clear"],
            confidence=0.84,
            research_verdict="selected_for_good_reason",
            notes="逻辑清楚",
            created_at="2026-03-22T20:15:00+08:00",
        ),
    )
    append_research_feedback(
        file_path=feedback_path,
        record=ResearchFeedbackRecord(
            run_id="session_001",
            trade_date="2026-03-22",
            symbol="300724",
            reviewer="researcher_b",
            review_status="draft",
            primary_tag="weak_edge",
            tags=["event_noise_suspected", "weak_edge"],
            confidence=0.42,
            research_verdict="needs_followup",
            notes="仍需复核",
            created_at="2026-03-22T20:20:00+08:00",
        ),
    )

    records = read_research_feedback(file_path=feedback_path)
    summary = summarize_research_feedback(records=records)

    assert len(records) == 2
    assert records[0].label_version == "v1"
    assert records[0].tags == ["high_quality_selection", "thesis_clear"]
    assert records[1].tags == ["weak_edge", "event_noise_suspected"]
    assert summary.feedback_count == 2
    assert summary.final_feedback_count == 1
    assert summary.primary_tag_counts == {"high_quality_selection": 1, "weak_edge": 1}
    assert summary.tag_counts["weak_edge"] == 1
    assert summary.tag_counts["high_quality_selection"] == 1
    assert summary.review_status_counts == {"final": 1, "draft": 1}
    assert summary.verdict_counts == {"selected_for_good_reason": 1, "needs_followup": 1}
    assert summary.latest_created_at == "2026-03-22T20:20:00+08:00"


def test_feedback_rejects_unknown_tag():
    with pytest.raises(ValueError, match="Unsupported research feedback tag"):
        ResearchFeedbackRecord(
            run_id="session_002",
            trade_date="2026-03-22",
            symbol="000001",
            reviewer="researcher_a",
            primary_tag="unknown_tag",
            tags=[],
            confidence=0.5,
            research_verdict="selected_for_good_reason",
            created_at="2026-03-22T20:15:00+08:00",
        )


def test_feedback_reader_can_skip_invalid_lines(tmp_path: Path):
    feedback_path = tmp_path / "research_feedback.jsonl"
    feedback_path.write_text(
        "\n".join(
            [
                '{"run_id":"session_003","trade_date":"2026-03-22","symbol":"000001","reviewer":"researcher_a","primary_tag":"high_quality_selection","tags":["thesis_clear"],"confidence":0.7,"research_verdict":"selected_for_good_reason","created_at":"2026-03-22T20:15:00+08:00"}',
                '{"run_id":"bad","primary_tag":"not_allowed"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    records = read_research_feedback(file_path=feedback_path, skip_invalid=True)

    assert len(records) == 1
    assert records[0].symbol == "000001"