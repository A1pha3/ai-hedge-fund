from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database.connection import Base, get_db
from app.backend.routes import api_router


def _build_client() -> tuple[TestClient, object]:
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
    app.include_router(api_router)
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), engine


def _screening_payload() -> dict:
    return {
        "mode": "auto_screening",
        "date": "20260607",
        "market_state": {"state_type": "trend"},
        "layer_a_count": 1,
        "total_scored": 1,
        "high_pool_count": 1,
        "top_n": 1,
        "recommendations": [
            {
                "ticker": "600000",
                "name": "测试股票",
                "industry_sw": "电子",
                "score_b": 0.8,
                "decision": "watch",
                "strategy_signals": {},
            }
        ],
        "sector_concentration_warnings": [],
        "consecutive_recommendation": {"lookback_days": 30, "high_streak_count": 1},
        "signal_decay_summary": {"mild": 0, "moderate": 0, "severe": 0, "total": 0},
        "batch_data_fetcher": {"use_batch": True, "batch_calls": 0, "batch_failures": 0, "single_ticker_calls": 0, "cache_hits": 0},
        "industry_rotation": [],
        "tracking_summary": {"total_recommendations": 1, "lookback_days": 30, "win_rate": 1.0},
    }


def test_api_router_protects_flows_without_token() -> None:
    client, engine = _build_client()
    try:
        response = client.get("/flows/")

        assert response.status_code == 401
        assert "认证令牌" in response.json()["detail"]
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_api_router_keeps_screening_latest_public(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.backend.routes.screening._load_latest_auto_screening_payload",
        lambda trade_date=None: _screening_payload(),
    )
    client, engine = _build_client()
    try:
        response = client.get("/api/screening/latest")

        assert response.status_code == 200
        assert response.json()["trade_date"] == "20260607"
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_api_router_protects_param_compare_post_without_token() -> None:
    client, engine = _build_client()
    try:
        response = client.post(
            "/backtest/param-compare",
            json={"trials": [], "total_combinations": 0, "max_workers": 1},
        )

        assert response.status_code == 401
        assert "认证令牌" in response.json()["detail"]
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
