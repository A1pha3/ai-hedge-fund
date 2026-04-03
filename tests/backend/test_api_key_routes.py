from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database.connection import Base, get_db
from app.backend.database.models import ApiKey
from app.backend.routes.api_keys import router


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


def test_get_api_key_masks_key_value():
    client, test_session, engine = _create_test_client()
    try:
        db = test_session()
        db.add(ApiKey(provider="OPENAI_API_KEY", key_value="sk-secret-value-1234", is_active=True))
        db.commit()
        db.close()

        response = client.get("/api-keys/OPENAI_API_KEY")

        assert response.status_code == 200
        payload = response.json()
        assert "key_value" not in payload
        assert payload["masked_key_value"] == "sk-s...1234"
        assert payload["has_key"] is True
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_list_api_keys_masks_key_values():
    client, test_session, engine = _create_test_client()
    try:
        db = test_session()
        db.add(ApiKey(provider="OPENAI_API_KEY", key_value="sk-secret-value-1234", is_active=True))
        db.commit()
        db.close()

        response = client.get("/api-keys/")

        assert response.status_code == 200
        payload = response.json()
        assert payload[0]["masked_key_value"] == "sk-s...1234"
        assert payload[0]["has_key"] is True
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
