"""Explicit Phase 4 test compatibility adapter for daily_pipeline.

Phase 4 tests monkeypatch symbols on src.execution.daily_pipeline. The execution logic now lives across helper modules, so this adapter mirrors the supported module-level overrides into the helper modules that actually execute the code.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import ModuleType
from typing import Any, TypeVar

import src.execution.daily_pipeline_short_trade_diagnostics_helpers as short_trade_diagnostics_helpers
import src.execution.daily_pipeline_upstream_shadow_helpers as upstream_shadow_helpers

T = TypeVar("T")

__all__ = [
    "Phase4TestOverrideBinding",
    "PHASE4_TEST_OVERRIDE_BINDINGS",
    "sync_phase4_test_overrides",
    "run_with_phase4_test_overrides",
]


@dataclass(frozen=True)
class Phase4TestOverrideBinding:
    source_name: str
    target_module: ModuleType
    target_name: str | None = None

    def apply(self, source_globals: Mapping[str, Any]) -> None:
        setattr(self.target_module, self.target_name or self.source_name, source_globals[self.source_name])


PHASE4_TEST_OVERRIDE_BINDINGS = (
    Phase4TestOverrideBinding("build_short_trade_target_snapshot_from_entry", short_trade_diagnostics_helpers),
    Phase4TestOverrideBinding("UPSTREAM_SHADOW_RELEASE_MAX_TICKERS", short_trade_diagnostics_helpers),
    Phase4TestOverrideBinding("UPSTREAM_SHADOW_RELEASE_LANE_SCORE_MINS", short_trade_diagnostics_helpers),
    Phase4TestOverrideBinding("UPSTREAM_SHADOW_RELEASE_LANE_MAX_TICKERS", short_trade_diagnostics_helpers),
    Phase4TestOverrideBinding("UPSTREAM_SHADOW_RELEASE_PRIORITY_TICKERS_BY_LANE", short_trade_diagnostics_helpers),
    Phase4TestOverrideBinding("UPSTREAM_SHADOW_RELEASE_MAX_TICKERS", upstream_shadow_helpers),
    Phase4TestOverrideBinding("UPSTREAM_SHADOW_RELEASE_LANE_SCORE_MINS", upstream_shadow_helpers),
    Phase4TestOverrideBinding("UPSTREAM_SHADOW_RELEASE_LANE_MAX_TICKERS", upstream_shadow_helpers),
    Phase4TestOverrideBinding("UPSTREAM_SHADOW_RELEASE_PRIORITY_TICKERS_BY_LANE", upstream_shadow_helpers),
    Phase4TestOverrideBinding("UPSTREAM_SHADOW_WATCHLIST_PROMOTION_LANES", upstream_shadow_helpers),
    Phase4TestOverrideBinding("UPSTREAM_SHADOW_WATCHLIST_PROMOTION_MAX_TICKERS", upstream_shadow_helpers),
)


def sync_phase4_test_overrides(source_globals: Mapping[str, Any]) -> None:
    for binding in PHASE4_TEST_OVERRIDE_BINDINGS:
        binding.apply(source_globals)


def run_with_phase4_test_overrides(callback: Callable[..., T], source_globals: Mapping[str, Any], /, *args: Any, **kwargs: Any) -> T:
    sync_phase4_test_overrides(source_globals)
    return callback(*args, **kwargs)