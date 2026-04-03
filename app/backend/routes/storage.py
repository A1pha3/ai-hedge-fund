from fastapi import APIRouter, HTTPException
import json
from pathlib import Path
from pydantic import BaseModel

from app.backend.models.schemas import ErrorResponse

router = APIRouter(prefix="/storage")

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
async def save_json_file(request: SaveJsonRequest):
    """Save JSON data to the project's /outputs directory."""
    try:
        # Create outputs directory if it doesn't exist
        project_root = Path(__file__).parent.parent.parent.parent  # Navigate to project root
        outputs_dir = project_root / "outputs"
        outputs_dir.mkdir(exist_ok=True)

        raw_path = Path(request.filename)
        if raw_path.is_absolute():
            raise HTTPException(status_code=400, detail="Invalid filename")

        outputs_root = outputs_dir.resolve()
        file_path = (outputs_root / raw_path).resolve()
        if outputs_root not in file_path.parents:
            raise HTTPException(status_code=400, detail="Invalid filename")

        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Save JSON data to file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(request.data, f, indent=2, ensure_ascii=False)

        return {
            "success": True,
            "message": "File saved successfully",
            "filename": str(file_path.relative_to(outputs_root)),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
