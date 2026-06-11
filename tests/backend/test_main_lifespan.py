import asyncio
from unittest.mock import AsyncMock

from fastapi import FastAPI

import app.backend.main as backend_main


def test_lifespan_creates_tables_before_auto_init_admin(monkeypatch) -> None:
    call_order: list[str] = []

    monkeypatch.setattr(backend_main, "_auto_init_admin", lambda: call_order.append("auto_init_admin"))
    monkeypatch.setattr(
        backend_main.Base.metadata,
        "create_all",
        lambda *, bind: call_order.append("create_all"),
    )
    monkeypatch.setattr(
        backend_main.ollama_service,
        "check_ollama_status",
        AsyncMock(return_value={"installed": False, "running": False, "server_url": "", "available_models": []}),
    )

    async def _run() -> None:
        async with backend_main.lifespan(FastAPI()):
            pass

    asyncio.run(_run())

    assert call_order[:2] == ["create_all", "auto_init_admin"]
