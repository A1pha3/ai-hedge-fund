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