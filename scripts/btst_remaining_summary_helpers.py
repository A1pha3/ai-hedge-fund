from __future__ import annotations

from collections.abc import Callable
from typing import Any


SafeLoadJson = Callable[[str | None], dict[str, Any]]
EntryById = Callable[[dict[str, Any], str], dict[str, Any]]


def _load_entry_backed_summary(
    manifest: dict[str, Any],
    *,
    summary_key: str,
    entry_id: str,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    summary = dict(manifest.get(summary_key) or {})
    if summary:
        return summary
    entry = entry_by_id(manifest, entry_id)
    if not entry:
        return {}
    return safe_load_json(entry.get("absolute_path"))


def extract_default_merge_review_summary(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    return _load_entry_backed_summary(
        manifest,
        summary_key="default_merge_review_summary",
        entry_id="btst_default_merge_review_latest",
        entry_by_id=entry_by_id,
        safe_load_json=safe_load_json,
    )


def extract_default_merge_historical_counterfactual_summary(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    return _load_entry_backed_summary(
        manifest,
        summary_key="default_merge_historical_counterfactual_summary",
        entry_id="btst_default_merge_historical_counterfactual_latest",
        entry_by_id=entry_by_id,
        safe_load_json=safe_load_json,
    )


def extract_continuation_merge_candidate_ranking_summary(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    return _load_entry_backed_summary(
        manifest,
        summary_key="continuation_merge_candidate_ranking_summary",
        entry_id="btst_continuation_merge_candidate_ranking_latest",
        entry_by_id=entry_by_id,
        safe_load_json=safe_load_json,
    )


def extract_default_merge_strict_counterfactual_summary(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    return _load_entry_backed_summary(
        manifest,
        summary_key="default_merge_strict_counterfactual_summary",
        entry_id="btst_default_merge_strict_counterfactual_latest",
        entry_by_id=entry_by_id,
        safe_load_json=safe_load_json,
    )


def extract_merge_replay_validation_summary(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    return _load_entry_backed_summary(
        manifest,
        summary_key="merge_replay_validation_summary",
        entry_id="btst_merge_replay_validation_latest",
        entry_by_id=entry_by_id,
        safe_load_json=safe_load_json,
    )


def extract_prepared_breakout_relief_validation_summary(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    return _load_entry_backed_summary(
        manifest,
        summary_key="prepared_breakout_relief_validation_summary",
        entry_id="btst_prepared_breakout_relief_validation_latest",
        entry_by_id=entry_by_id,
        safe_load_json=safe_load_json,
    )


def extract_prepared_breakout_cohort_summary(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    return _load_entry_backed_summary(
        manifest,
        summary_key="prepared_breakout_cohort_summary",
        entry_id="btst_prepared_breakout_cohort_latest",
        entry_by_id=entry_by_id,
        safe_load_json=safe_load_json,
    )


def extract_prepared_breakout_residual_surface_summary(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    return _load_entry_backed_summary(
        manifest,
        summary_key="prepared_breakout_residual_surface_summary",
        entry_id="btst_prepared_breakout_residual_surface_latest",
        entry_by_id=entry_by_id,
        safe_load_json=safe_load_json,
    )


def extract_candidate_pool_corridor_persistence_dossier_summary(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    return _load_entry_backed_summary(
        manifest,
        summary_key="candidate_pool_corridor_persistence_dossier_summary",
        entry_id="btst_candidate_pool_corridor_persistence_dossier_latest",
        entry_by_id=entry_by_id,
        safe_load_json=safe_load_json,
    )


def extract_candidate_pool_corridor_window_command_board_summary(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    return _load_entry_backed_summary(
        manifest,
        summary_key="candidate_pool_corridor_window_command_board_summary",
        entry_id="btst_candidate_pool_corridor_window_command_board_latest",
        entry_by_id=entry_by_id,
        safe_load_json=safe_load_json,
    )


def extract_candidate_pool_corridor_window_diagnostics_summary(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    return _load_entry_backed_summary(
        manifest,
        summary_key="candidate_pool_corridor_window_diagnostics_summary",
        entry_id="btst_candidate_pool_corridor_window_diagnostics_latest",
        entry_by_id=entry_by_id,
        safe_load_json=safe_load_json,
    )


def extract_candidate_pool_corridor_narrow_probe_summary(
    manifest: dict[str, Any],
    *,
    entry_by_id: EntryById,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    return _load_entry_backed_summary(
        manifest,
        summary_key="candidate_pool_corridor_narrow_probe_summary",
        entry_id="btst_candidate_pool_corridor_narrow_probe_latest",
        entry_by_id=entry_by_id,
        safe_load_json=safe_load_json,
    )
