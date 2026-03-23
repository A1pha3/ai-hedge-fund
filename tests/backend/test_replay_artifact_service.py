from __future__ import annotations

import json
from pathlib import Path

from app.backend.services.replay_artifact_service import ReplayArtifactService


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")


def test_get_replay_includes_selection_artifact_overview(tmp_path: Path) -> None:
    report_dir = tmp_path / "demo_report"
    artifact_root = report_dir / "selection_artifacts"
    day_dir = artifact_root / "2026-03-11"

    _write_json(
        report_dir / "session_summary.json",
        {
            "start_date": "2026-03-10",
            "end_date": "2026-03-11",
            "initial_capital": 100000.0,
            "portfolio_values": [{"Portfolio Value": 101000.0}],
            "daily_event_stats": {"executed_trade_days": 1, "total_executed_orders": 1},
            "performance_metrics": {"sharpe_ratio": 1.2, "sortino_ratio": 1.8, "max_drawdown": -0.03, "max_drawdown_date": "2026-03-11"},
            "plan_generation": {"mode": "frozen_replay"},
            "model_provider": "MiniMax",
            "model_name": "MiniMax-M2.7",
            "artifacts": {
                "selection_artifact_root": str(artifact_root),
            },
            "final_portfolio_snapshot": {"positions": {}, "realized_gains": {}},
        },
    )
    _write_jsonl(
        report_dir / "daily_events.jsonl",
        [
            {
                "trade_date": "2026-03-11",
                "current_plan": {
                    "selection_artifacts": {"write_status": "success"},
                    "risk_metrics": {
                        "counts": {"layer_b_count": 2, "watchlist_count": 1, "buy_order_count": 0},
                        "funnel_diagnostics": {
                            "filters": {
                                "watchlist": {"reason_counts": {}},
                                "buy_orders": {"reason_counts": {"blocked_by_reentry_score_confirmation": 1}},
                            }
                        },
                    },
                },
                "portfolio_snapshot": {"positions": {}},
                "current_prices": {},
                "decisions": {},
            }
        ],
    )
    _write_jsonl(report_dir / "pipeline_timings.jsonl", [{"timing_seconds": {"total_day": 12.5, "post_market": 4.0}}])
    _write_json(
        day_dir / "selection_snapshot.json",
        {
            "trade_date": "2026-03-11",
            "selected": [
                {
                    "symbol": "300724",
                    "execution_bridge": {"block_reason": "blocked_by_reentry_score_confirmation"},
                }
            ],
        },
    )
    (day_dir / "selection_review.md").write_text("# Selection Review\n\n阻断原因: blocked_by_reentry_score_confirmation\n", encoding="utf-8")
    (day_dir / "research_feedback.jsonl").write_text("", encoding="utf-8")
    _write_json(
        artifact_root / "research_feedback_summary.json",
        {
            "artifact_root": str(artifact_root),
            "feedback_file_count": 1,
            "trade_date_count": 1,
            "overall": {"feedback_count": 0, "final_feedback_count": 0},
            "by_trade_date": {},
        },
    )

    service = ReplayArtifactService()
    service._reports_root = tmp_path

    detail = service.get_replay("demo_report")

    overview = detail["selection_artifact_overview"]
    assert overview["available"] is True
    assert overview["trade_date_count"] == 1
    assert overview["available_trade_dates"] == ["2026-03-11"]
    assert overview["write_status_counts"] == {"success": 1}
    assert overview["blocker_counts"] == [{"reason": "blocked_by_reentry_score_confirmation", "count": 1}]
    assert overview["feedback_summary"]["feedback_file_count"] == 1


def test_get_selection_artifact_day_returns_snapshot_and_review(tmp_path: Path) -> None:
    report_dir = tmp_path / "demo_report"
    day_dir = report_dir / "selection_artifacts" / "2026-03-11"

    _write_json(
        report_dir / "session_summary.json",
        {
            "artifacts": {
                "selection_artifact_root": str(report_dir / "selection_artifacts"),
            }
        },
    )
    _write_json(
        day_dir / "selection_snapshot.json",
        {
            "trade_date": "2026-03-11",
            "selected": [
                {
                    "symbol": "300724",
                    "execution_bridge": {"block_reason": "blocked_by_reentry_score_confirmation"},
                }
            ],
        },
    )
    (day_dir / "selection_review.md").write_text("review body", encoding="utf-8")
    (day_dir / "research_feedback.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "feedback_version": "v1",
                        "artifact_version": "v1",
                        "label_version": "v1",
                        "run_id": "demo_run",
                        "trade_date": "2026-03-11",
                        "symbol": "300724",
                        "review_scope": "watchlist",
                        "reviewer": "researcher_a",
                        "review_status": "draft",
                        "primary_tag": "weak_edge",
                        "tags": ["weak_edge"],
                        "confidence": 0.4,
                        "research_verdict": "older_note",
                        "notes": "older",
                        "created_at": "2026-03-22T10:00:00+08:00",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "feedback_version": "v1",
                        "artifact_version": "v1",
                        "label_version": "v1",
                        "run_id": "demo_run",
                        "trade_date": "2026-03-11",
                        "symbol": "300724",
                        "review_scope": "watchlist",
                        "reviewer": "researcher_b",
                        "review_status": "final",
                        "primary_tag": "high_quality_selection",
                        "tags": ["high_quality_selection"],
                        "confidence": 0.8,
                        "research_verdict": "newer_note",
                        "notes": "newer",
                        "created_at": "2026-03-23T10:00:00+08:00",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    service = ReplayArtifactService()
    service._reports_root = tmp_path

    detail = service.get_selection_artifact_day("demo_report", "2026-03-11")

    assert detail["trade_date"] == "2026-03-11"
    assert detail["snapshot"]["trade_date"] == "2026-03-11"
    assert detail["review_markdown"] == "review body"
    assert detail["feedback_record_count"] == 2
    assert detail["feedback_summary"]["feedback_count"] == 2
    assert detail["feedback_options"]["allowed_review_statuses"] == ["draft", "final", "adjudicated"]
    assert detail["blocker_counts"] == [{"reason": "blocked_by_reentry_score_confirmation", "count": 1}]
    assert [record["created_at"] for record in detail["feedback_records"]] == [
        "2026-03-23T10:00:00+08:00",
        "2026-03-22T10:00:00+08:00",
    ]


def test_append_selection_artifact_feedback_updates_summary(tmp_path: Path) -> None:
    report_dir = tmp_path / "demo_report"
    artifact_root = report_dir / "selection_artifacts"
    day_dir = artifact_root / "2026-03-11"

    _write_json(
        report_dir / "session_summary.json",
        {
            "artifacts": {
                "selection_artifact_root": str(artifact_root),
                "research_feedback_summary": str(artifact_root / "research_feedback_summary.json"),
            },
        },
    )
    _write_json(
        day_dir / "selection_snapshot.json",
        {
            "artifact_version": "v1",
            "run_id": "demo_run",
            "trade_date": "2026-03-11",
            "selected": [{"symbol": "300724"}],
            "rejected": [],
        },
    )
    (day_dir / "selection_review.md").write_text("review body", encoding="utf-8")
    (day_dir / "research_feedback.jsonl").write_text("", encoding="utf-8")

    service = ReplayArtifactService()
    service._reports_root = tmp_path

    result = service.append_selection_artifact_feedback(
        report_name="demo_report",
        trade_date="2026-03-11",
        reviewer="researcher_a",
        symbol="300724",
        primary_tag="high_quality_selection",
        research_verdict="selected_for_good_reason",
        tags=["thesis_clear"],
        review_status="final",
        confidence=0.82,
        notes="quality looks strong",
    )

    assert result["record"]["reviewer"] == "researcher_a"
    assert result["feedback_record_count"] == 1
    assert result["feedback_summary"]["feedback_count"] == 1
    assert result["directory_summary"]["overall"]["feedback_count"] == 1

    summary_payload = json.loads((artifact_root / "research_feedback_summary.json").read_text(encoding="utf-8"))
    assert summary_payload["overall"]["feedback_count"] == 1

    session_summary_payload = json.loads((report_dir / "session_summary.json").read_text(encoding="utf-8"))
    assert session_summary_payload["research_feedback_summary"]["overall"]["feedback_count"] == 1