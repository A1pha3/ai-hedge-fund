"""Shared utilities for backend route handlers.

Provides a decorator that wraps every route handler with consistent error
handling: HTTPException passes through, everything else is logged and
converted to a 500 response.  Eliminates the boilerplate try/except block
that was duplicated ~60 times across the routes directory during R20.13.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable

from fastapi import HTTPException


def safe_route(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that applies standardised error handling to a FastAPI route.

    Behaviour (identical to the hand-written pattern it replaces):
    - ``HTTPException`` instances are re-raised unchanged (404, 400, etc.)
    - All other exceptions are logged with traceback and converted to
      ``HTTPException(status_code=500, detail="Internal server error")``
    - The module-level ``logger`` of the calling module is used for logging.

    Usage::

        @router.get("/things")
        @safe_route
        async def list_things(db: Session = Depends(get_db)):
            repo = ThingRepository(db)
            return repo.get_all()

    Equivalent to the previous hand-written pattern::

        @router.get("/things")
        async def list_things(db: Session = Depends(get_db)):
            try:
                repo = ThingRepository(db)
                return repo.get_all()
            except HTTPException:
                raise
            except Exception as e:
                logger.exception("Failed to list things")
                raise HTTPException(status_code=500, detail="Internal server error")
    """

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            raise
        except Exception:
            _get_route_logger(func).exception("Route handler failed: %s", func.__qualname__)
            raise HTTPException(status_code=500, detail="Internal server error")

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except HTTPException:
            raise
        except Exception:
            _get_route_logger(func).exception("Route handler failed: %s", func.__qualname__)
            raise HTTPException(status_code=500, detail="Internal server error")

    if asyncio_is_coroutine(func):
        return async_wrapper
    return sync_wrapper


def _get_route_logger(func: Callable[..., Any]) -> logging.Logger:
    """Return a logger named after the module that defines *func*."""
    module = func.__module__ or __name__
    return logging.getLogger(module)


def asyncio_is_coroutine(func: Callable[..., Any]) -> bool:
    """Return True if *func* is a native async function."""
    import asyncio

    return asyncio.iscoroutinefunction(func)
