from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.auth.dependencies import get_current_user
from app.backend.routes.replay_artifacts import router
from app.backend.services.replay_artifact_service import ReplayArtifactService


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(username="tester")
    return TestClient(app)


def test_get_replay_selection_artifact_route_returns_payload(monkeypatch) -> None:
    def _fake_get_selection_artifact_day(self: ReplayArtifactService, report_name: str, trade_date: str) -> dict:
        return {
            "report_dir": report_name,
            "trade_date": trade_date,
            "paths": {
                "snapshot_path": "/tmp/snapshot.json",
                "review_path": "/tmp/selection_review.md",
                "feedback_path": "/tmp/research_feedback.jsonl",
            },
            "snapshot": {
                "trade_date": trade_date,
                "selected": [],
                "rejected": [],
                "buy_orders": [],
                "sell_orders": [],
                "pipeline_config_snapshot": {},
                "universe_summary": {},
                "funnel_diagnostics": {},
                "artifact_version": "v1",
                "run_id": report_name,
                "experiment_id": None,
                "market": "CN",
                "decision_timestamp": "2026-03-11T15:05:00+08:00",
                "data_available_until": "2026-03-11T15:00:00+08:00",
            },
            "review_markdown": "# Review",
            "feedback_record_count": 0,
            "blocker_counts": [],
        }

    monkeypatch.setattr(ReplayArtifactService, "get_selection_artifact_day", _fake_get_selection_artifact_day)

    client = _build_client()

    response = client.get("/replay-artifacts/demo_report/selection-artifacts/2026-03-11")

    assert response.status_code == 200
    payload = response.json()["selection_artifact"]
    assert payload["report_dir"] == "demo_report"
    assert payload["trade_date"] == "2026-03-11"
    assert payload["review_markdown"] == "# Review"


def test_get_replay_selection_artifact_route_returns_404(monkeypatch) -> None:
    def _fake_get_selection_artifact_day(self: ReplayArtifactService, report_name: str, trade_date: str) -> dict:
        raise FileNotFoundError(f"Selection artifact day not found: {report_name}/{trade_date}")

    monkeypatch.setattr(ReplayArtifactService, "get_selection_artifact_day", _fake_get_selection_artifact_day)

    client = _build_client()

    response = client.get("/replay-artifacts/missing_report/selection-artifacts/2026-03-11")

    assert response.status_code == 404
    assert "Selection artifact day not found" in response.json()["detail"]


def test_append_replay_selection_feedback_route_returns_payload(monkeypatch) -> None:
    def _fake_append_selection_artifact_feedback(self: ReplayArtifactService, **kwargs) -> dict:
        assert kwargs["reviewer"] == "tester"
        return {
            "record": {
                "symbol": kwargs["symbol"],
                "primary_tag": kwargs["primary_tag"],
                "reviewer": kwargs["reviewer"],
            },
            "feedback_record_count": 1,
            "feedback_summary": {"feedback_count": 1},
            "directory_summary": {"overall": {"feedback_count": 1}},
            "feedback_path": "/tmp/research_feedback.jsonl",
        }

    monkeypatch.setattr(ReplayArtifactService, "append_selection_artifact_feedback", _fake_append_selection_artifact_feedback)

    client = _build_client()
    response = client.post(
        "/replay-artifacts/demo_report/selection-artifacts/2026-03-11/feedback",
        json={
            "symbol": "300724",
            "primary_tag": "high_quality_selection",
            "research_verdict": "selected_for_good_reason",
            "tags": ["thesis_clear"],
            "review_status": "final",
            "confidence": 0.8,
            "notes": "looks good",
        },
    )

    assert response.status_code == 200
    payload = response.json()["feedback"]
    assert payload["record"]["symbol"] == "300724"
    assert payload["record"]["reviewer"] == "tester"
    assert payload["feedback_record_count"] == 1


def test_append_replay_selection_feedback_route_returns_400(monkeypatch) -> None:
    def _fake_append_selection_artifact_feedback(self: ReplayArtifactService, **kwargs) -> dict:
        raise ValueError("Symbol not found in selection snapshot: 300724")

    monkeypatch.setattr(ReplayArtifactService, "append_selection_artifact_feedback", _fake_append_selection_artifact_feedback)

    client = _build_client()
    response = client.post(
        "/replay-artifacts/demo_report/selection-artifacts/2026-03-11/feedback",
        json={
            "symbol": "300724",
            "primary_tag": "high_quality_selection",
            "research_verdict": "selected_for_good_reason",
        },
    )

    assert response.status_code == 400
    assert "Symbol not found in selection snapshot" in response.json()["detail"]


def test_append_replay_selection_feedback_batch_route_returns_payload(monkeypatch) -> None:
    def _fake_append_selection_artifact_feedback_batch(self: ReplayArtifactService, **kwargs) -> dict:
        assert kwargs["reviewer"] == "tester"
        assert kwargs["symbols"] == ["300724", "002916"]
        return {
            "records": [
                {
                    "symbol": "300724",
                    "review_scope": "watchlist",
                    "reviewer": kwargs["reviewer"],
                },
                {
                    "symbol": "002916",
                    "review_scope": "near_miss",
                    "reviewer": kwargs["reviewer"],
                },
            ],
            "appended_count": 2,
            "feedback_record_count": 2,
            "feedback_summary": {"feedback_count": 2},
            "directory_summary": {"overall": {"feedback_count": 2}},
            "feedback_path": "/tmp/research_feedback.jsonl",
        }

    monkeypatch.setattr(ReplayArtifactService, "append_selection_artifact_feedback_batch", _fake_append_selection_artifact_feedback_batch)

    client = _build_client()
    response = client.post(
        "/replay-artifacts/demo_report/selection-artifacts/2026-03-11/feedback/batch",
        json={
            "symbols": ["300724", "002916"],
            "primary_tag": "threshold_false_negative",
            "research_verdict": "needs_weekly_review",
            "tags": ["thesis_clear"],
            "review_status": "draft",
            "confidence": 0.55,
            "notes": "weekly batch triage",
        },
    )

    assert response.status_code == 200
    payload = response.json()["feedback"]
    assert payload["appended_count"] == 2
    assert payload["records"][0]["symbol"] == "300724"
    assert payload["records"][1]["review_scope"] == "near_miss"


def test_get_replay_feedback_activity_route_returns_payload(monkeypatch) -> None:
    def _fake_get_feedback_activity(self: ReplayArtifactService, **kwargs) -> dict:
        assert kwargs["report_name"] == "demo_report"
        assert kwargs["reviewer"] == "tester"
        assert kwargs["limit"] == 5
        return {
            "report_name": "demo_report",
            "reviewer": "tester",
            "limit": 5,
            "record_count": 1,
            "recent_records": [
                {
                    "report_name": "demo_report",
                    "trade_date": "2026-03-11",
                    "symbol": "300724",
                    "reviewer": "tester",
                    "review_status": "final",
                    "primary_tag": "high_quality_selection",
                    "tags": ["high_quality_selection"],
                    "confidence": 0.82,
                    "research_verdict": "selected_for_good_reason",
                    "notes": "looks good",
                    "created_at": "2026-03-23T10:00:00+08:00",
                    "review_scope": "watchlist",
                    "feedback_path": "/tmp/research_feedback.jsonl",
                }
            ],
            "review_status_counts": {"final": 1},
            "tag_counts": {"high_quality_selection": 1},
            "reviewer_counts": {"tester": 1},
            "report_counts": {"demo_report": 1},
        }

    monkeypatch.setattr(ReplayArtifactService, "get_feedback_activity", _fake_get_feedback_activity)

    client = _build_client()
    response = client.get("/replay-artifacts/feedback-activity", params={"report_name": "demo_report", "reviewer": "tester", "limit": 5})

    assert response.status_code == 200
    payload = response.json()["activity"]
    assert payload["record_count"] == 1
    assert payload["recent_records"][0]["symbol"] == "300724"


def test_get_replay_workflow_queue_route_returns_payload(monkeypatch) -> None:
    def _fake_list_workflow_queue(self: ReplayArtifactService, **kwargs) -> dict:
        assert kwargs["assignee"] == "einstein"
        assert kwargs["workflow_status"] == "assigned"
        assert kwargs["report_name"] == "demo_report"
        assert kwargs["limit"] == 5
        return {
            "assignee": "einstein",
            "workflow_status": "assigned",
            "report_name": "demo_report",
            "limit": 5,
            "item_count": 1,
            "items": [
                {
                    "report_name": "demo_report",
                    "trade_date": "2026-03-11",
                    "symbol": "300724",
                    "review_scope": "watchlist",
                    "assignee": "einstein",
                    "workflow_status": "assigned",
                    "latest_review_status": "draft",
                    "latest_primary_tag": "high_quality_selection",
                    "latest_tags": ["high_quality_selection"],
                    "latest_research_verdict": "selected_for_good_reason",
                    "latest_notes": "needs owner",
                    "latest_feedback_created_at": "2026-03-25T10:00:00+08:00",
                    "latest_reviewer": "einstein",
                    "feedback_path": "/tmp/research_feedback.jsonl",
                }
            ],
            "workflow_status_counts": {"assigned": 1},
            "assignee_counts": {"einstein": 1},
            "report_counts": {"demo_report": 1},
        }

    monkeypatch.setattr(ReplayArtifactService, "list_workflow_queue", _fake_list_workflow_queue)

    client = _build_client()
    response = client.get(
        "/replay-artifacts/workflow-queue",
        params={"assignee": "einstein", "workflow_status": "assigned", "report_name": "demo_report", "limit": 5},
    )

    assert response.status_code == 200
    payload = response.json()["queue"]
    assert payload["item_count"] == 1
    assert payload["items"][0]["assignee"] == "einstein"


def test_update_replay_workflow_item_route_returns_payload(monkeypatch) -> None:
    def _fake_update_workflow_item(self: ReplayArtifactService, **kwargs) -> dict:
        assert kwargs["report_name"] == "demo_report"
        assert kwargs["trade_date"] == "2026-03-11"
        assert kwargs["symbol"] == "300724"
        assert kwargs["review_scope"] == "watchlist"
        assert kwargs["assignee"] == "einstein"
        assert kwargs["workflow_status"] == "assigned"
        return {
            "report_name": "demo_report",
            "trade_date": "2026-03-11",
            "symbol": "300724",
            "review_scope": "watchlist",
            "assignee": "einstein",
            "workflow_status": "assigned",
            "latest_review_status": "draft",
            "latest_primary_tag": "high_quality_selection",
            "latest_tags": ["high_quality_selection"],
            "latest_research_verdict": "selected_for_good_reason",
            "latest_notes": "needs owner",
            "latest_feedback_created_at": "2026-03-25T10:00:00+08:00",
            "latest_reviewer": "einstein",
            "feedback_path": "/tmp/research_feedback.jsonl",
        }

    monkeypatch.setattr(ReplayArtifactService, "update_workflow_item", _fake_update_workflow_item)

    client = _build_client()
    response = client.patch(
        "/replay-artifacts/workflow-queue/item",
        json={
            "report_name": "demo_report",
            "trade_date": "2026-03-11",
            "symbol": "300724",
            "review_scope": "watchlist",
            "assignee": "einstein",
            "workflow_status": "assigned",
        },
    )

    assert response.status_code == 200
    payload = response.json()["item"]
    assert payload["assignee"] == "einstein"
    assert payload["workflow_status"] == "assigned"