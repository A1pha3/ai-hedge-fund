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


def test_save_json_atomic_crash_preserves_prior(tmp_path, monkeypatch):
    """R88 corrupt-file CRASH vector (web 用户输入): save_json_file 必须原子写。
    用户通过 web 存的 JSON, crash 落在 open('w') truncate 之后会丢用户输入。
    当前实现 catch Exception→500, 但文件已被 truncate 成空。原子写让 prior 完整。"""
    import json as _json
    import app.backend.routes.storage as storage_mod
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setattr(storage_mod, "_PROJECT_ROOT", tmp_path)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    target = outputs / "user_report.json"
    target.write_text(_json.dumps({"prior": True, "keep": "alive"}), encoding="utf-8")

    app = FastAPI()
    app.include_router(storage_mod.router)
    client = TestClient(app)

    from unittest.mock import patch
    with patch("app.backend.routes.storage.json.dump", side_effect=RuntimeError("simulated crash")):
        resp = client.post("/storage/save-json", json={"filename": "user_report.json", "data": {"new": 1}})

    assert resp.status_code == 500  # caught by except Exception → HTTPException(500)

    raw = target.read_text(encoding="utf-8")
    assert raw.strip(), (
        "prior user file must not be truncated-empty after a crashed write — "
        "non-atomic open('w') truncates immediately (R88 corrupt-file CRASH vector root cause, 用户输入丢失)"
    )
    _json.loads(raw)  # must parse cleanly
