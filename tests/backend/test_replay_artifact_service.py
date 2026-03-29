from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.connection import Base
from app.backend.services.replay_artifact_service import ReplayArtifactService


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")


def _build_service_with_db(tmp_path: Path) -> ReplayArtifactService:
    engine = create_engine(f"sqlite:///{tmp_path / 'replay-feedback-test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    service = ReplayArtifactService(session_factory=test_session)
    service._reports_root = tmp_path
    return service


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
                "data_cache_benchmark_json": str(report_dir / "data_cache_benchmark.json"),
                "data_cache_benchmark_markdown": str(report_dir / "data_cache_benchmark.md"),
            },
            "data_cache_benchmark_status": {
                "requested": True,
                "executed": True,
                "write_status": "success",
                "reason": None,
            },
            "data_cache_benchmark": {
                "trade_date": "20260311",
                "ticker": "300724",
                "summary": {
                    "reuse_confirmed": True,
                    "disk_hit_gain": 6,
                    "miss_reduction": 6,
                    "set_reduction": 6,
                    "first_hit_rate": 0.0,
                    "second_hit_rate": 1.0,
                },
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
            "target_mode": "dual_target",
            "pipeline_config_snapshot": {
                "short_trade_target_profile": {
                    "name": "aggressive",
                    "config": {
                        "select_threshold": 0.54,
                    },
                }
            },
            "target_summary": {
                "target_mode": "dual_target",
                "selection_target_count": 2,
                "research_target_count": 2,
                "short_trade_target_count": 2,
                "research_selected_count": 1,
                "research_near_miss_count": 1,
                "research_rejected_count": 0,
                "short_trade_selected_count": 1,
                "short_trade_near_miss_count": 0,
                "short_trade_blocked_count": 1,
                "short_trade_rejected_count": 0,
                "shell_target_count": 0,
                "delta_classification_counts": {"research_reject_short_pass": 1},
            },
            "research_view": {
                "selected_symbols": ["300724"],
                "near_miss_symbols": ["002916"],
                "rejected_symbols": [],
                "blocker_counts": {"analyst_divergence_high": 1},
            },
            "short_trade_view": {
                "selected_symbols": ["002916"],
                "near_miss_symbols": [],
                "rejected_symbols": [],
                "blocked_symbols": ["300724"],
                "blocker_counts": {"missing_trend_signal": 1},
            },
            "dual_target_delta": {
                "delta_counts": {"research_reject_short_pass": 1},
                "representative_cases": [
                    {
                        "ticker": "002916",
                        "delta_classification": "research_reject_short_pass",
                        "research_decision": "near_miss",
                        "short_trade_decision": "selected",
                        "delta_summary": ["short trade target promoted a setup that research pipeline kept as near-miss"],
                    }
                ],
                "dominant_delta_reasons": ["short trade target promoted a setup that research pipeline kept as near-miss"],
            },
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

    service = _build_service_with_db(tmp_path)

    detail = service.get_replay("demo_report")

    overview = detail["selection_artifact_overview"]
    cache_overview = detail["cache_benchmark_overview"]
    assert overview["available"] is True
    assert overview["trade_date_count"] == 1
    assert overview["available_trade_dates"] == ["2026-03-11"]
    assert overview["trade_date_target_index"] == [
        {
            "trade_date": "2026-03-11",
            "target_mode": "dual_target",
            "short_trade_profile_name": "aggressive",
            "delta_classification_counts": {"research_reject_short_pass": 2},
            "research_selected_count": 1,
            "research_near_miss_count": 1,
            "short_trade_selected_count": 1,
            "short_trade_blocked_count": 1,
        }
    ]
    assert overview["write_status_counts"] == {"success": 1}
    assert overview["blocker_counts"] == [{"reason": "blocked_by_reentry_score_confirmation", "count": 1}]
    assert overview["short_trade_profile_overview"] == {
        "profile_name_counts": {"aggressive": 1},
        "latest_profile_name": "aggressive",
        "latest_profile_trade_date": "2026-03-11",
        "latest_profile_config": {"select_threshold": 0.54},
    }
    assert overview["dual_target_overview"] == {
        "target_mode_counts": {"dual_target": 1},
        "dual_target_trade_date_count": 1,
        "selection_target_count": 2,
        "research_target_count": 2,
        "short_trade_target_count": 2,
        "research_selected_count": 1,
        "research_near_miss_count": 1,
        "research_rejected_count": 0,
        "short_trade_selected_count": 1,
        "short_trade_near_miss_count": 0,
        "short_trade_blocked_count": 1,
        "short_trade_rejected_count": 0,
        "shell_target_count": 0,
        "delta_classification_counts": {"research_reject_short_pass": 2},
        "dominant_delta_reasons": ["short trade target promoted a setup that research pipeline kept as near-miss"],
        "dominant_delta_reason_counts": {"short trade target promoted a setup that research pipeline kept as near-miss": 1},
        "representative_cases": [
            {
                "trade_date": "2026-03-11",
                "ticker": "002916",
                "delta_classification": "research_reject_short_pass",
                "research_decision": "near_miss",
                "short_trade_decision": "selected",
                "delta_summary": ["short trade target promoted a setup that research pipeline kept as near-miss"],
            }
        ],
    }
    assert overview["feedback_summary"]["feedback_file_count"] == 1
    assert cache_overview == {
        "requested": True,
        "executed": True,
        "write_status": "success",
        "reason": None,
        "ticker": "300724",
        "trade_date": "20260311",
        "reuse_confirmed": True,
        "disk_hit_gain": 6,
        "miss_reduction": 6,
        "set_reduction": 6,
        "first_hit_rate": 0.0,
        "second_hit_rate": 1.0,
        "artifacts": {
            "data_cache_benchmark_json": str(report_dir / "data_cache_benchmark.json"),
            "data_cache_benchmark_markdown": str(report_dir / "data_cache_benchmark.md"),
        },
    }


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
            "target_mode": "dual_target",
            "target_summary": {
                "target_mode": "dual_target",
                "selection_target_count": 2,
                "research_target_count": 2,
                "short_trade_target_count": 2,
                "research_selected_count": 1,
                "research_near_miss_count": 1,
                "research_rejected_count": 0,
                "short_trade_selected_count": 1,
                "short_trade_near_miss_count": 0,
                "short_trade_blocked_count": 1,
                "short_trade_rejected_count": 0,
                "shell_target_count": 0,
                "delta_classification_counts": {"research_reject_short_pass": 1},
            },
            "research_view": {
                "selected_symbols": ["300724"],
                "near_miss_symbols": ["002916"],
                "rejected_symbols": [],
                "blocker_counts": {"analyst_divergence_high": 1},
            },
            "short_trade_view": {
                "selected_symbols": ["002916"],
                "near_miss_symbols": [],
                "rejected_symbols": [],
                "blocked_symbols": ["300724"],
                "blocker_counts": {"missing_trend_signal": 1},
            },
            "dual_target_delta": {
                "delta_counts": {"research_reject_short_pass": 1},
                "representative_cases": [
                    {
                        "ticker": "002916",
                        "delta_classification": "research_reject_short_pass",
                        "research_decision": "near_miss",
                        "short_trade_decision": "selected",
                        "delta_summary": ["short trade target promoted a setup that research pipeline kept as near-miss"],
                    }
                ],
                "dominant_delta_reasons": ["short trade target promoted a setup that research pipeline kept as near-miss"],
            },
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

    service = _build_service_with_db(tmp_path)

    detail = service.get_selection_artifact_day("demo_report", "2026-03-11")

    assert detail["trade_date"] == "2026-03-11"
    assert detail["snapshot"]["trade_date"] == "2026-03-11"
    assert detail["review_markdown"] == "review body"
    assert detail["feedback_record_count"] == 2
    assert detail["feedback_summary"]["feedback_count"] == 2
    assert detail["feedback_options"]["allowed_review_statuses"] == ["draft", "final", "adjudicated"]
    assert detail["blocker_counts"] == [{"reason": "blocked_by_reentry_score_confirmation", "count": 1}]
    assert detail["snapshot"]["target_mode"] == "dual_target"
    assert detail["snapshot"]["target_summary"]["short_trade_blocked_count"] == 1
    assert detail["snapshot"]["research_view"]["selected_symbols"] == ["300724"]
    assert detail["snapshot"]["short_trade_view"]["blocked_symbols"] == ["300724"]
    assert detail["snapshot"]["dual_target_delta"]["delta_counts"] == {"research_reject_short_pass": 1}
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

    service = _build_service_with_db(tmp_path)

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

    activity = service.get_feedback_activity(report_name="demo_report")
    assert activity["record_count"] == 1
    assert activity["recent_records"][0]["symbol"] == "300724"
    assert activity["review_status_counts"] == {"final": 1}
    assert activity["report_counts"] == {"demo_report": 1}
    assert activity["workflow_status_counts"] == {"final": 1}
    assert activity["workflow_queue"]["final"][0]["symbol"] == "300724"


def test_append_selection_artifact_feedback_batch_updates_summary(tmp_path: Path) -> None:
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
            "rejected": [{"symbol": "002916"}],
        },
    )
    (day_dir / "selection_review.md").write_text("review body", encoding="utf-8")
    (day_dir / "research_feedback.jsonl").write_text("", encoding="utf-8")

    service = _build_service_with_db(tmp_path)

    result = service.append_selection_artifact_feedback_batch(
        report_name="demo_report",
        trade_date="2026-03-11",
        reviewer="researcher_a",
        symbols=["300724", "002916", "300724"],
        primary_tag="threshold_false_negative",
        research_verdict="needs_weekly_review",
        tags=["thesis_clear"],
        review_status="draft",
        confidence=0.55,
        notes="weekly batch triage",
    )

    assert result["appended_count"] == 2
    assert [record["symbol"] for record in result["records"]] == ["300724", "002916"]
    assert result["records"][0]["review_scope"] == "watchlist"
    assert result["records"][1]["review_scope"] == "near_miss"
    assert result["feedback_record_count"] == 2
    assert result["feedback_summary"]["feedback_count"] == 2
    assert result["directory_summary"]["overall"]["feedback_count"] == 2

    activity = service.get_feedback_activity(report_name="demo_report")
    assert activity["record_count"] == 2
    assert activity["review_status_counts"] == {"draft": 2}
    assert activity["tag_counts"] == {"threshold_false_negative": 2, "thesis_clear": 2}
    assert activity["workflow_status_counts"] == {"draft": 2}
    assert [record["symbol"] for record in activity["workflow_queue"]["draft"]] == ["300724", "002916"]


def test_list_workflow_queue_and_update_assignee(tmp_path: Path) -> None:
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
            "rejected": [{"symbol": "002916"}],
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
                        "reviewer": "einstein",
                        "review_status": "draft",
                        "primary_tag": "high_quality_selection",
                        "tags": ["high_quality_selection"],
                        "confidence": 0.82,
                        "research_verdict": "selected_for_good_reason",
                        "notes": "needs owner",
                        "created_at": "2026-03-25T10:00:00+08:00",
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
                        "symbol": "002916",
                        "review_scope": "near_miss",
                        "reviewer": "curie",
                        "review_status": "final",
                        "primary_tag": "threshold_false_negative",
                        "tags": ["threshold_false_negative"],
                        "confidence": 0.61,
                        "research_verdict": "escalate_to_weekly_review",
                        "notes": "ready for adjudication",
                        "created_at": "2026-03-25T11:00:00+08:00",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    service = _build_service_with_db(tmp_path)

    queue = service.list_workflow_queue()
    assert queue["item_count"] == 2
    assert queue["workflow_status_counts"] == {"unassigned": 1, "ready_for_adjudication": 1}
    assert queue["assignee_counts"] == {"__unassigned__": 2}

    updated = service.update_workflow_item(
        report_name="demo_report",
        trade_date="2026-03-11",
        symbol="300724",
        review_scope="watchlist",
        assignee="einstein",
    )
    assert updated["assignee"] == "einstein"
    assert updated["workflow_status"] == "assigned"

    my_queue = service.list_workflow_queue(assignee="einstein")
    assert my_queue["item_count"] == 1
    assert my_queue["items"][0]["symbol"] == "300724"


def test_get_selection_artifact_day_syncs_existing_feedback_to_database(tmp_path: Path) -> None:
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
            "selected": [{"symbol": "300724"}],
            "rejected": [{"symbol": "002916"}],
        },
    )
    (day_dir / "selection_review.md").write_text("review body", encoding="utf-8")
    _write_jsonl(
        day_dir / "research_feedback.jsonl",
        [
            {
                "feedback_version": "v1",
                "artifact_version": "v1",
                "label_version": "v1",
                "run_id": "demo_run",
                "trade_date": "2026-03-11",
                "symbol": "002916",
                "review_scope": "near_miss",
                "reviewer": "researcher_b",
                "review_status": "draft",
                "primary_tag": "threshold_false_negative",
                "tags": ["threshold_false_negative"],
                "confidence": 0.61,
                "research_verdict": "near_miss_review",
                "notes": "older",
                "created_at": "2026-03-22T10:00:00+08:00",
            },
            {
                "feedback_version": "v1",
                "artifact_version": "v1",
                "label_version": "v1",
                "run_id": "demo_run",
                "trade_date": "2026-03-11",
                "symbol": "300724",
                "review_scope": "watchlist",
                "reviewer": "researcher_a",
                "review_status": "final",
                "primary_tag": "high_quality_selection",
                "tags": ["high_quality_selection", "thesis_clear"],
                "confidence": 0.82,
                "research_verdict": "selected_for_good_reason",
                "notes": "newer",
                "created_at": "2026-03-23T10:00:00+08:00",
            },
        ],
    )

    service = _build_service_with_db(tmp_path)

    detail = service.get_selection_artifact_day("demo_report", "2026-03-11")
    assert detail["feedback_record_count"] == 2

    activity = service.get_feedback_activity(report_name="demo_report")
    assert activity["record_count"] == 2
    assert [record["created_at"] for record in activity["recent_records"]] == [
        "2026-03-23T10:00:00",
        "2026-03-22T10:00:00",
    ]
    assert activity["review_status_counts"] == {"final": 1, "draft": 1}
    assert activity["tag_counts"]["high_quality_selection"] == 1
    assert activity["tag_counts"]["thesis_clear"] == 1