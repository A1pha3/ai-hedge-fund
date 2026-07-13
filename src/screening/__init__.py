"""Screening package public API with lazy compatibility exports."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any


__all__ = [
    "build_candidate_pool",
    "detect_market_state",
    "fuse_batch",
    "fuse_signals_for_ticker",
    "score_batch",
    "score_candidate",
]

_EXPORTS = {
    "build_candidate_pool": (".candidate_pool", "build_candidate_pool"),
    "detect_market_state": (".market_state", "detect_market_state"),
    "fuse_batch": (".signal_fusion", "fuse_batch"),
    "fuse_signals_for_ticker": (".signal_fusion", "fuse_signals_for_ticker"),
    "score_batch": (".strategy_scorer", "score_batch"),
    "score_candidate": (".strategy_scorer", "score_candidate"),
}


def __getattr__(name: str) -> Any:
    """Resolve the historical package-level exports only when requested."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


if TYPE_CHECKING:
    from .candidate_pool import build_candidate_pool
    from .market_state import detect_market_state
    from .signal_fusion import fuse_batch, fuse_signals_for_ticker
    from .strategy_scorer import score_batch, score_candidate
