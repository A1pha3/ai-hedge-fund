import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.backend.database import get_db
from app.backend.database.models import ApiKey
from app.backend.models.schemas import (
    ApiKeyBulkUpdateRequest,
    ApiKeyCreateRequest,
    ApiKeyResponse,
    ApiKeySummaryResponse,
    ApiKeyUpdateRequest,
    ErrorResponse,
)
from app.backend.repositories.api_key_repository import ApiKeyRepository
from app.backend.routes._common import safe_route

router = APIRouter(prefix="/api-keys", tags=["api-keys"])
logger = logging.getLogger(__name__)


def _mask_key_value(key_value: str | None) -> str | None:
    if not key_value:
        return None
    if len(key_value) <= 8:
        return "*" * len(key_value)
    return f"{key_value[:4]}...{key_value[-4:]}"


def _to_api_key_response(api_key: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=api_key.id,
        provider=api_key.provider,
        masked_key_value=_mask_key_value(api_key.key_value),
        is_active=api_key.is_active,
        description=api_key.description,
        created_at=api_key.created_at,
        updated_at=api_key.updated_at,
        last_used=api_key.last_used,
        has_key=bool(api_key.key_value),
    )


def _to_api_key_summary(api_key: ApiKey) -> ApiKeySummaryResponse:
    return ApiKeySummaryResponse(
        id=api_key.id,
        provider=api_key.provider,
        is_active=api_key.is_active,
        description=api_key.description,
        created_at=api_key.created_at,
        updated_at=api_key.updated_at,
        last_used=api_key.last_used,
        masked_key_value=_mask_key_value(api_key.key_value),
        has_key=bool(api_key.key_value),
    )


@router.post(
    "/",
    response_model=ApiKeyResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def create_or_update_api_key(request: ApiKeyCreateRequest, db: Session = Depends(get_db)):
    """Create a new API key or update existing one"""
    repo = ApiKeyRepository(db)
    api_key = repo.create_or_update_api_key(
        provider=request.provider,
        key_value=request.key_value,
        description=request.description,
        is_active=request.is_active
    )
    return _to_api_key_response(api_key)


@router.get(
    "/",
    response_model=List[ApiKeySummaryResponse],
    responses={
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def get_api_keys(include_inactive: bool = False, db: Session = Depends(get_db)):
    """Get all API keys (without actual key values for security)"""
    repo = ApiKeyRepository(db)
    api_keys = repo.get_all_api_keys(include_inactive=include_inactive)
    return [_to_api_key_summary(key) for key in api_keys]


@router.get(
    "/{provider}",
    response_model=ApiKeyResponse,
    responses={
        404: {"model": ErrorResponse, "description": "API key not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def get_api_key(provider: str, db: Session = Depends(get_db)):
    """Get a specific API key by provider"""
    repo = ApiKeyRepository(db)
    api_key = repo.get_api_key_by_provider(provider)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    return _to_api_key_response(api_key)


@router.put(
    "/{provider}",
    response_model=ApiKeyResponse,
    responses={
        404: {"model": ErrorResponse, "description": "API key not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def update_api_key(provider: str, request: ApiKeyUpdateRequest, db: Session = Depends(get_db)):
    """Update an existing API key"""
    repo = ApiKeyRepository(db)
    api_key = repo.update_api_key(
        provider=provider,
        key_value=request.key_value,
        description=request.description,
        is_active=request.is_active
    )
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    return _to_api_key_response(api_key)


@router.delete(
    "/{provider}",
    responses={
        204: {"description": "API key deleted successfully"},
        404: {"model": ErrorResponse, "description": "API key not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def delete_api_key(provider: str, db: Session = Depends(get_db)):
    """Delete an API key"""
    repo = ApiKeyRepository(db)
    success = repo.delete_api_key(provider)
    if not success:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"message": "API key deleted successfully"}


@router.patch(
    "/{provider}/deactivate",
    response_model=ApiKeySummaryResponse,
    responses={
        404: {"model": ErrorResponse, "description": "API key not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def deactivate_api_key(provider: str, db: Session = Depends(get_db)):
    """Deactivate an API key without deleting it"""
    repo = ApiKeyRepository(db)
    api_key = repo.deactivate_api_key(provider)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    return _to_api_key_summary(api_key)


@router.post(
    "/bulk",
    response_model=List[ApiKeyResponse],
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def bulk_update_api_keys(request: ApiKeyBulkUpdateRequest, db: Session = Depends(get_db)):
    """Bulk create or update multiple API keys"""
    repo = ApiKeyRepository(db)
    api_keys_data = [
        {
            'provider': key.provider,
            'key_value': key.key_value,
            'description': key.description,
            'is_active': key.is_active
        }
        for key in request.api_keys
    ]
    api_keys = repo.bulk_create_or_update(api_keys_data)
    return [_to_api_key_response(key) for key in api_keys]


@router.patch(
    "/{provider}/last-used",
    responses={
        200: {"description": "Last used timestamp updated"},
        404: {"model": ErrorResponse, "description": "API key not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@safe_route
async def update_last_used(provider: str, db: Session = Depends(get_db)):
    """Update the last used timestamp for an API key"""
    repo = ApiKeyRepository(db)
    success = repo.update_last_used(provider)
    if not success:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"message": "Last used timestamp updated"}
