from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_STRATEGY_THRESHOLDS_CONFIG = Path("config/btst_strategy_thresholds.json")
DEFAULT_STRATEGY_THRESHOLDS_PROFILE = "conservative"
AGGRESSIVE_STRATEGY_THRESHOLDS_CONFIG = Path("config/btst_strategy_thresholds_aggressive.json")
STRATEGY_THRESHOLD_PROFILE_CONFIGS = {
    "default": DEFAULT_STRATEGY_THRESHOLDS_CONFIG,
    "conservative": DEFAULT_STRATEGY_THRESHOLDS_CONFIG,
    "aggressive": AGGRESSIVE_STRATEGY_THRESHOLDS_CONFIG,
}


def default_strategy_thresholds() -> dict[str, Any]:
    """Return the conservative default thresholds shared by BTST docs and validation."""
    return {
        "min_recent_exact_streak": 3,
        "min_intersection_positive_days": 2,
        "require_zero_unavailable_days_for_directory_switch": True,
        "intersection_min_candidate_count": 2,
        "intersection_uplift_rate_threshold": 0.15,
        "intersection_uplift_mean_return_threshold": 0.02,
        "only_early_runner_min_candidate_count": 2,
        "only_early_runner_max_positive_rate": 0.45,
        "second_entry_min_candidate_count": 2,
        "second_entry_t2_advantage_threshold": 0.01,
        "selected_zero_follow_through_min_evaluable_count": 3,
        "selected_intraday_only_min_evaluable_count": 3,
        "selected_intraday_only_max_next_close_positive_rate": 0.0,
        "near_miss_zero_follow_through_min_evaluable_count": 3,
        "near_miss_zero_follow_through_max_next_high_hit_rate": 0.0,
        "near_miss_zero_follow_through_max_next_close_positive_rate": 0.0,
        "opportunity_zero_follow_through_prune_min_evaluable_count": 2,
        "opportunity_zero_follow_through_max_next_high_hit_rate": 0.0,
        "opportunity_zero_follow_through_max_next_close_positive_rate": 0.0,
        "opportunity_zero_follow_through_max_next_open_to_close_return_mean": -0.0001,
        "opportunity_balanced_prune_min_evaluable_count": 4,
        "opportunity_balanced_max_next_high_hit_rate": 0.5,
        "opportunity_balanced_max_next_close_positive_rate": 0.2,
        "opportunity_balanced_max_next_open_to_close_return_mean": -0.0001,
        "mixed_boundary_prune_min_evaluable_count": 6,
        "mixed_boundary_max_score_target": 0.4,
        "mixed_boundary_max_breakout_freshness": 0.5,
        "mixed_boundary_max_next_high_hit_rate": 0.5,
        "mixed_boundary_max_next_close_positive_rate": 0.5,
    }


def _normalize_strategy_thresholds_profile(profile: str | None = None) -> str:
    """Normalize one profile name and fall back to the conservative baseline."""
    resolved = str(profile or DEFAULT_STRATEGY_THRESHOLDS_PROFILE).strip().lower()
    if not resolved:
        return DEFAULT_STRATEGY_THRESHOLDS_PROFILE
    return resolved


def resolve_strategy_thresholds_config_path(
    config_path: str | Path | None = None,
    *,
    profile: str | None = None,
) -> Path:
    """Resolve the strategy-threshold config path from an explicit path or one named profile."""
    if config_path:
        return Path(config_path).expanduser().resolve()
    normalized_profile = _normalize_strategy_thresholds_profile(profile)
    mapped_path = STRATEGY_THRESHOLD_PROFILE_CONFIGS.get(normalized_profile)
    if mapped_path is None:
        supported = ", ".join(sorted(STRATEGY_THRESHOLD_PROFILE_CONFIGS))
        raise ValueError(f"unsupported BTST strategy-threshold profile: {profile!r}; supported: {supported}")
    return mapped_path.expanduser().resolve()


def load_strategy_thresholds_config(
    config_path: str | Path | None = None,
    *,
    profile: str | None = None,
) -> dict[str, Any]:
    """Load one repository-level threshold config file when it exists."""
    resolved_path = resolve_strategy_thresholds_config_path(config_path, profile=profile)
    if not resolved_path.exists():
        return {}
    payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    return dict(payload or {})


def resolve_strategy_thresholds(
    overrides: dict[str, Any] | None = None,
    *,
    config_path: str | Path | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Merge code defaults, repository config, and runtime overrides in that order."""
    resolved = default_strategy_thresholds()
    resolved.update(load_strategy_thresholds_config(config_path, profile=profile))
    for key, value in dict(overrides or {}).items():
        if value is not None:
            resolved[key] = value
    return resolved
