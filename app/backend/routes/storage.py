import json
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.backend.models.schemas import ErrorResponse
from app.backend.routes._common import safe_route

router = APIRouter(prefix="/storage")

# 模块级常量 (便于测试 monkeypatch + 代码清晰度)
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # → repo root


class SaveJsonRequest(BaseModel):
    filename: str
    data: dict


@router.post(
    path="/save-json",
    responses={
        200: {"description": "File saved successfully"},
        400: {"model": ErrorResponse, "description": "Invalid request parameters"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def save_json_file(request: SaveJsonRequest):
    """Save JSON data to the project's /outputs directory.

    c292: rewired to ``@safe_route`` so unexpected exceptions (disk-full,
    permission-denied, encoding-failure) are logged with traceback via
    ``logger.exception`` instead of being silently swallowed by a hand-rolled
    ``except Exception: raise HTTPException(500)`` (NS-17 drain scope gap found
    by dogfooding the remaining web routes after c291).
    """
    # Create outputs directory if it doesn't exist
    outputs_dir = _PROJECT_ROOT / "outputs"
    outputs_dir.mkdir(exist_ok=True)

    raw_path = Path(request.filename)
    if raw_path.is_absolute():
        raise HTTPException(status_code=400, detail="Invalid filename")

    outputs_root = outputs_dir.resolve()
    file_path = (outputs_root / raw_path).resolve()
    if file_path == outputs_root or outputs_root not in file_path.parents:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Save JSON data to file (原子写: R88 corrupt-file CRASH vector guard)。
    # 此前 open('w') 立即 truncate, crash 落在 json.dump 中途会丢用户输入 (web 路由)。
    # tempfile + os.replace: crash 不 truncate 最终路径。
    fd, tmp_name = tempfile.mkstemp(prefix="." + file_path.name + ".", suffix=".tmp", dir=str(file_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(request.data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_name, file_path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    return {
        "success": True,
        "message": "File saved successfully",
        "filename": str(file_path.relative_to(outputs_root)),
    }
