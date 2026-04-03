from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.routes.storage import router


def test_save_json_rejects_path_traversal():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.post(
        "/storage/save-json",
        json={"filename": "../secrets.json", "data": {"ok": True}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid filename"
