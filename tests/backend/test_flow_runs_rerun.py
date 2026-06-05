"""Tests for POST /flows/{flow_id}/runs/{run_id}/rerun endpoint.

Three test cases:
1. Successful rerun returns an SSE stream with X-Rerun-Run-Id header.
2. Rerun of a flow run with no request_data returns 400.
3. Rerun of a non-existent run returns 404.
"""
from unittest.mock import patch, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database.connection import Base, get_db
from app.backend.database.models import HedgeFundFlow, HedgeFundFlowRun
from app.backend.routes.flow_runs import router


def _create_test_client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = test_session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    return client, test_session, engine


def _seed_flow_and_run(db, flow_id=1, run_id=1, request_data=None, status="COMPLETE"):
    """Insert a flow and a completed run into the test database."""
    flow = HedgeFundFlow(
        id=flow_id,
        name="Test Flow",
        nodes=[],
        edges=[],
        is_template=False,
    )
    db.add(flow)
    db.flush()

    run = HedgeFundFlowRun(
        id=run_id,
        flow_id=flow_id,
        status=status,
        run_number=1,
        request_data=request_data,
    )
    db.add(run)
    db.commit()


def test_rerun_returns_stream_with_new_run_id():
    """A completed run with valid request_data should produce an SSE response."""
    client, test_session, engine = _create_test_client()
    try:
        db = test_session()
        stored_request = {
            "tickers": ["AAPL"],
            "graph_nodes": [],
            "graph_edges": [],
            "initial_cash": 100000.0,
            "start_date": "2026-01-01",
            "end_date": "2026-03-01",
        }
        _seed_flow_and_run(db, request_data=stored_request)
        db.close()

        # Patch the heavy graph/LLM internals to avoid real execution
        with (
            patch("app.backend.routes.flow_runs.create_graph") as mock_create_graph,
            patch("app.backend.routes.flow_runs.create_portfolio", return_value={}),
            patch("app.backend.routes.flow_runs.hydrate_api_keys"),
            patch("app.backend.routes.flow_runs.resolve_model_provider", return_value="OpenAI"),
            patch("app.backend.routes.flow_runs.progress"),
            patch("app.backend.routes.flow_runs.stream_hedge_fund_run") as mock_stream,
        ):
            # Make the compiled graph a simple mock
            mock_graph = MagicMock()
            mock_create_graph.return_value = mock_graph

            # SSE generator that yields one complete event
            async def _fake_stream(*args, **kwargs):
                yield 'event: complete\ndata: {"data": {"decisions": {}}}\n\n'

            mock_stream.return_value = _fake_stream()

            response = client.post("/flows/1/runs/1/rerun")

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        assert "X-Rerun-Run-Id" in response.headers
        new_run_id = int(response.headers["X-Rerun-Run-Id"])
        assert new_run_id > 0

    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_rerun_returns_400_when_no_request_data():
    """A run without stored request_data should return 400."""
    client, test_session, engine = _create_test_client()
    try:
        db = test_session()
        _seed_flow_and_run(db, request_data=None)
        db.close()

        response = client.post("/flows/1/runs/1/rerun")

        assert response.status_code == 400
        assert "request_data" in response.json()["detail"].lower()

    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_rerun_returns_404_for_missing_run():
    """A non-existent run_id should return 404."""
    client, test_session, engine = _create_test_client()
    try:
        db = test_session()
        _seed_flow_and_run(db)  # only seed flow + run 1
        db.close()

        response = client.post("/flows/1/runs/999/rerun")

        assert response.status_code == 404

    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
