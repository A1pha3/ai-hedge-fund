from argparse import Namespace
from pathlib import Path

from scripts.manage_research_feedback import _append_command, _resolve_feedback_path, _summarize_command


def test_resolve_feedback_path_from_artifact_dir(tmp_path: Path):
    feedback_path = _resolve_feedback_path(feedback_file=None, artifact_dir=str(tmp_path), trade_date="20260322")

    assert feedback_path == tmp_path / "2026-03-22" / "research_feedback.jsonl"


def test_append_and_summarize_commands_roundtrip(tmp_path: Path):
    artifact_dir = tmp_path / "selection_artifacts"

    append_result = _append_command(
        Namespace(
            feedback_file=None,
            artifact_dir=str(artifact_dir),
            trade_date="2026-03-22",
            run_id="session_001",
            symbol="300724",
            reviewer="researcher_a",
            primary_tag="high_quality_selection",
            research_verdict="selected_for_good_reason",
            tag=["thesis_clear"],
            review_status="final",
            review_scope="watchlist",
            confidence=0.91,
            notes="逻辑充分",
            artifact_version="v1",
            feedback_version="v1",
            label_version="v1",
            created_at="2026-03-22T21:00:00+08:00",
        )
    )

    summarize_result = _summarize_command(
        Namespace(
            feedback_file=append_result["feedback_file"],
            artifact_dir=None,
            trade_date=None,
            skip_invalid=False,
            output=None,
        )
    )

    assert append_result["command"] == "append"
    assert Path(append_result["feedback_file"]).exists()
    assert summarize_result["feedback_count"] == 1
    assert summarize_result["final_feedback_count"] == 1
    assert summarize_result["primary_tag_counts"] == {"high_quality_selection": 1}
    assert summarize_result["tag_counts"] == {"high_quality_selection": 1, "thesis_clear": 1}
    assert summarize_result["review_status_counts"] == {"final": 1}