from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from scripts.analyze_btst_candidate_entry_rollout_governance import (
    analyze_btst_candidate_entry_rollout_governance,
    render_btst_candidate_entry_rollout_governance_markdown,
)
from scripts.analyze_btst_candidate_entry_window_scan import (
    analyze_btst_candidate_entry_window_scan,
    render_btst_candidate_entry_window_scan_markdown,
)
from scripts.analyze_btst_candidate_pool_branch_priority_board import (
    analyze_btst_candidate_pool_branch_priority_board,
    render_btst_candidate_pool_branch_priority_board_markdown,
)
from scripts.analyze_btst_candidate_pool_lane_objective_support import (
    analyze_btst_candidate_pool_lane_objective_support,
    render_btst_candidate_pool_lane_objective_support_markdown,
)
from scripts.analyze_btst_candidate_pool_rebucket_objective_validation import (
    analyze_btst_candidate_pool_rebucket_objective_validation,
    render_btst_candidate_pool_rebucket_objective_validation_markdown,
)
from scripts.analyze_btst_candidate_pool_recall_dossier import (
    analyze_btst_candidate_pool_recall_dossier,
    render_btst_candidate_pool_recall_dossier_markdown,
)
from scripts.analyze_btst_no_candidate_entry_action_board import (
    analyze_btst_no_candidate_entry_action_board,
    render_btst_no_candidate_entry_action_board_markdown,
)
from scripts.analyze_btst_no_candidate_entry_failure_dossier import (
    analyze_btst_no_candidate_entry_failure_dossier,
    render_btst_no_candidate_entry_failure_dossier_markdown,
)
from scripts.analyze_btst_no_candidate_entry_replay_bundle import (
    analyze_btst_no_candidate_entry_replay_bundle,
    render_btst_no_candidate_entry_replay_bundle_markdown,
)
from scripts.analyze_btst_watchlist_recall_dossier import (
    analyze_btst_watchlist_recall_dossier,
    render_btst_watchlist_recall_dossier_markdown,
)
from scripts.run_btst_candidate_pool_corridor_shadow_pack import (
    analyze_btst_candidate_pool_corridor_shadow_pack,
    render_btst_candidate_pool_corridor_shadow_pack_markdown,
)
from scripts.run_btst_candidate_pool_corridor_uplift_runbook import (
    analyze_btst_candidate_pool_corridor_uplift_runbook,
    render_btst_candidate_pool_corridor_uplift_runbook_markdown,
)
from scripts.run_btst_candidate_pool_corridor_validation_pack import (
    analyze_btst_candidate_pool_corridor_validation_pack,
    render_btst_candidate_pool_corridor_validation_pack_markdown,
)
from scripts.run_btst_candidate_pool_lane_pair_board import (
    analyze_btst_candidate_pool_lane_pair_board,
    render_btst_candidate_pool_lane_pair_board_markdown,
)
from scripts.run_btst_candidate_pool_rebucket_comparison_bundle import (
    analyze_btst_candidate_pool_rebucket_comparison_bundle,
    render_btst_candidate_pool_rebucket_comparison_bundle_markdown,
)
from scripts.run_btst_candidate_pool_rebucket_shadow_pack import (
    render_btst_candidate_pool_rebucket_shadow_pack_markdown,
    run_btst_candidate_pool_rebucket_shadow_pack,
)
from scripts.run_btst_candidate_pool_upstream_handoff_board import (
    analyze_btst_candidate_pool_upstream_handoff_board,
    render_btst_candidate_pool_upstream_handoff_board_markdown,
)


MarkdownRenderer = Callable[[dict[str, Any]], str]
SummaryBuilder = Callable[[Path], dict[str, Any]]


@dataclass(frozen=True)
class JsonMarkdownPaths:
    json: Path
    md: Path


@dataclass(frozen=True)
class CandidateEntryShadowPaths:
    frontier_report: Path
    structural_validation: Path
    score_frontier_report: Path
    tradeable_opportunity_pool: Path
    objective_monitor: Path
    window_scan: JsonMarkdownPaths
    rollout_governance: JsonMarkdownPaths
    no_candidate_entry_action_board: JsonMarkdownPaths
    no_candidate_entry_replay_bundle: JsonMarkdownPaths
    no_candidate_entry_failure_dossier: JsonMarkdownPaths
    watchlist_recall_dossier: JsonMarkdownPaths
    candidate_pool_recall_dossier: JsonMarkdownPaths
    candidate_pool_branch_priority_board: JsonMarkdownPaths
    candidate_pool_lane_objective_support: JsonMarkdownPaths
    candidate_pool_rebucket_shadow_pack: JsonMarkdownPaths
    candidate_pool_rebucket_objective_validation: JsonMarkdownPaths
    candidate_pool_rebucket_comparison_bundle: JsonMarkdownPaths
    candidate_pool_corridor_validation_pack: JsonMarkdownPaths
    candidate_pool_corridor_shadow_pack: JsonMarkdownPaths
    candidate_pool_lane_pair_board: JsonMarkdownPaths
    candidate_pool_upstream_handoff_board: JsonMarkdownPaths
    candidate_pool_corridor_uplift_runbook: JsonMarkdownPaths


@dataclass
class RefreshArtifact:
    analysis: dict[str, Any] = field(default_factory=dict)
    status: str = ""


@dataclass
class CandidateEntryShadowRefreshState:
    no_candidate_entry_action_board: RefreshArtifact = field(
        default_factory=lambda: RefreshArtifact(status="skipped_missing_tradeable_opportunity_pool")
    )
    no_candidate_entry_replay_bundle: RefreshArtifact = field(default_factory=lambda: RefreshArtifact(status="skipped_missing_action_board"))
    no_candidate_entry_failure_dossier: RefreshArtifact = field(default_factory=lambda: RefreshArtifact(status="skipped_missing_action_board"))
    watchlist_recall_dossier: RefreshArtifact = field(default_factory=lambda: RefreshArtifact(status="skipped_missing_failure_dossier"))
    candidate_pool_recall_dossier: RefreshArtifact = field(default_factory=lambda: RefreshArtifact(status="skipped_missing_watchlist_recall_dossier"))
    candidate_pool_branch_priority_board: RefreshArtifact = field(default_factory=lambda: RefreshArtifact(status="skipped_missing_candidate_pool_recall_dossier"))
    candidate_pool_lane_objective_support: RefreshArtifact = field(default_factory=lambda: RefreshArtifact(status="skipped_missing_candidate_pool_recall_dossier"))
    candidate_pool_corridor_validation_pack: RefreshArtifact = field(default_factory=lambda: RefreshArtifact(status="skipped_missing_candidate_pool_recall_dossier"))
    candidate_pool_corridor_shadow_pack: RefreshArtifact = field(default_factory=lambda: RefreshArtifact(status="skipped_missing_candidate_pool_recall_dossier"))
    candidate_pool_rebucket_shadow_pack: RefreshArtifact = field(default_factory=lambda: RefreshArtifact(status="skipped_missing_candidate_pool_recall_dossier"))
    candidate_pool_rebucket_objective_validation: RefreshArtifact = field(default_factory=lambda: RefreshArtifact(status="skipped_missing_candidate_pool_recall_dossier"))
    candidate_pool_rebucket_comparison_bundle: RefreshArtifact = field(default_factory=lambda: RefreshArtifact(status="skipped_missing_candidate_pool_recall_dossier"))
    candidate_pool_lane_pair_board: RefreshArtifact = field(default_factory=lambda: RefreshArtifact(status="skipped_missing_candidate_pool_recall_dossier"))
    candidate_pool_upstream_handoff_board: RefreshArtifact = field(default_factory=lambda: RefreshArtifact(status="skipped_missing_candidate_pool_recall_dossier"))
    candidate_pool_corridor_uplift_runbook: RefreshArtifact = field(default_factory=lambda: RefreshArtifact(status="skipped_missing_candidate_pool_recall_dossier"))


def build_candidate_entry_shadow_paths(reports_root: Path, artifact_names: Mapping[str, str]) -> CandidateEntryShadowPaths:
    return CandidateEntryShadowPaths(
        frontier_report=reports_root / artifact_names["frontier_report"],
        structural_validation=reports_root / artifact_names["structural_validation"],
        score_frontier_report=reports_root / artifact_names["score_frontier_report"],
        tradeable_opportunity_pool=reports_root / artifact_names["tradeable_opportunity_pool"],
        objective_monitor=reports_root / artifact_names["objective_monitor"],
        window_scan=_build_json_markdown_paths(reports_root, artifact_names, "window_scan_json", "window_scan_md"),
        rollout_governance=_build_json_markdown_paths(reports_root, artifact_names, "rollout_governance_json", "rollout_governance_md"),
        no_candidate_entry_action_board=_build_json_markdown_paths(reports_root, artifact_names, "no_candidate_entry_action_board_json", "no_candidate_entry_action_board_md"),
        no_candidate_entry_replay_bundle=_build_json_markdown_paths(reports_root, artifact_names, "no_candidate_entry_replay_bundle_json", "no_candidate_entry_replay_bundle_md"),
        no_candidate_entry_failure_dossier=_build_json_markdown_paths(reports_root, artifact_names, "no_candidate_entry_failure_dossier_json", "no_candidate_entry_failure_dossier_md"),
        watchlist_recall_dossier=_build_json_markdown_paths(reports_root, artifact_names, "watchlist_recall_dossier_json", "watchlist_recall_dossier_md"),
        candidate_pool_recall_dossier=_build_json_markdown_paths(reports_root, artifact_names, "candidate_pool_recall_dossier_json", "candidate_pool_recall_dossier_md"),
        candidate_pool_branch_priority_board=_build_json_markdown_paths(reports_root, artifact_names, "candidate_pool_branch_priority_board_json", "candidate_pool_branch_priority_board_md"),
        candidate_pool_lane_objective_support=_build_json_markdown_paths(reports_root, artifact_names, "candidate_pool_lane_objective_support_json", "candidate_pool_lane_objective_support_md"),
        candidate_pool_rebucket_shadow_pack=_build_json_markdown_paths(reports_root, artifact_names, "candidate_pool_rebucket_shadow_pack_json", "candidate_pool_rebucket_shadow_pack_md"),
        candidate_pool_rebucket_objective_validation=_build_json_markdown_paths(reports_root, artifact_names, "candidate_pool_rebucket_objective_validation_json", "candidate_pool_rebucket_objective_validation_md"),
        candidate_pool_rebucket_comparison_bundle=_build_json_markdown_paths(reports_root, artifact_names, "candidate_pool_rebucket_comparison_bundle_json", "candidate_pool_rebucket_comparison_bundle_md"),
        candidate_pool_corridor_validation_pack=_build_json_markdown_paths(reports_root, artifact_names, "candidate_pool_corridor_validation_pack_json", "candidate_pool_corridor_validation_pack_md"),
        candidate_pool_corridor_shadow_pack=_build_json_markdown_paths(reports_root, artifact_names, "candidate_pool_corridor_shadow_pack_json", "candidate_pool_corridor_shadow_pack_md"),
        candidate_pool_lane_pair_board=_build_json_markdown_paths(reports_root, artifact_names, "candidate_pool_lane_pair_board_json", "candidate_pool_lane_pair_board_md"),
        candidate_pool_upstream_handoff_board=_build_json_markdown_paths(reports_root, artifact_names, "candidate_pool_upstream_handoff_board_json", "candidate_pool_upstream_handoff_board_md"),
        candidate_pool_corridor_uplift_runbook=_build_json_markdown_paths(reports_root, artifact_names, "candidate_pool_corridor_uplift_runbook_json", "candidate_pool_corridor_uplift_runbook_md"),
    )


def build_candidate_entry_shadow_required_inputs(paths: CandidateEntryShadowPaths) -> dict[str, Path]:
    return {
        "frontier_report": paths.frontier_report,
        "structural_validation": paths.structural_validation,
        "score_frontier_report": paths.score_frontier_report,
    }


def build_candidate_entry_shadow_initial_state() -> CandidateEntryShadowRefreshState:
    return CandidateEntryShadowRefreshState()


def refresh_candidate_entry_shadow_prerequisites(
    *,
    paths: CandidateEntryShadowPaths,
    reports_root: Path,
    preserve_tickers: list[str],
    state: CandidateEntryShadowRefreshState,
) -> CandidateEntryShadowRefreshState:
    state.no_candidate_entry_action_board.analysis = analyze_btst_no_candidate_entry_action_board(
        paths.tradeable_opportunity_pool,
        preserve_tickers=preserve_tickers,
    )
    _write_analysis_artifact(
        paths.no_candidate_entry_action_board,
        state.no_candidate_entry_action_board.analysis,
        render_btst_no_candidate_entry_action_board_markdown,
    )
    state.no_candidate_entry_action_board.status = "refreshed"

    replay_report_dir_names = {
        str(row.get("primary_report_dir") or "").strip()
        for row in list(state.no_candidate_entry_action_board.analysis.get("priority_queue") or [])
        if str(row.get("primary_report_dir") or "").strip()
    }
    replay_report_dir_names.update(
        str(row.get("report_dir") or "").strip()
        for row in list(state.no_candidate_entry_action_board.analysis.get("window_hotspot_rows") or [])
        if str(row.get("report_dir") or "").strip()
    )
    available_replay_report_dir_names = [report_dir_name for report_dir_name in replay_report_dir_names if (reports_root / report_dir_name).exists()]
    if available_replay_report_dir_names:
        state.no_candidate_entry_replay_bundle.analysis = analyze_btst_no_candidate_entry_replay_bundle(paths.no_candidate_entry_action_board.json)
        _write_analysis_artifact(
            paths.no_candidate_entry_replay_bundle,
            state.no_candidate_entry_replay_bundle.analysis,
            render_btst_no_candidate_entry_replay_bundle_markdown,
        )
        state.no_candidate_entry_replay_bundle.status = "refreshed"
    else:
        state.no_candidate_entry_replay_bundle.status = "skipped_missing_replay_reports"

    state.no_candidate_entry_failure_dossier.analysis = analyze_btst_no_candidate_entry_failure_dossier(
        paths.tradeable_opportunity_pool,
        action_board_path=paths.no_candidate_entry_action_board.json,
        replay_bundle_path=paths.no_candidate_entry_replay_bundle.json if state.no_candidate_entry_replay_bundle.analysis else None,
    )
    _write_analysis_artifact(
        paths.no_candidate_entry_failure_dossier,
        state.no_candidate_entry_failure_dossier.analysis,
        render_btst_no_candidate_entry_failure_dossier_markdown,
    )
    state.no_candidate_entry_failure_dossier.status = "refreshed"

    state.watchlist_recall_dossier.analysis = analyze_btst_watchlist_recall_dossier(
        paths.tradeable_opportunity_pool,
        failure_dossier_path=paths.no_candidate_entry_failure_dossier.json if state.no_candidate_entry_failure_dossier.analysis else None,
    )
    _write_analysis_artifact(
        paths.watchlist_recall_dossier,
        state.watchlist_recall_dossier.analysis,
        render_btst_watchlist_recall_dossier_markdown,
    )
    state.watchlist_recall_dossier.status = "refreshed"

    state.candidate_pool_recall_dossier.analysis = analyze_btst_candidate_pool_recall_dossier(
        paths.tradeable_opportunity_pool,
        watchlist_recall_dossier_path=paths.watchlist_recall_dossier.json if state.watchlist_recall_dossier.analysis else None,
        failure_dossier_path=paths.no_candidate_entry_failure_dossier.json if state.no_candidate_entry_failure_dossier.analysis else None,
    )
    _write_analysis_artifact(
        paths.candidate_pool_recall_dossier,
        state.candidate_pool_recall_dossier.analysis,
        render_btst_candidate_pool_recall_dossier_markdown,
    )
    state.candidate_pool_recall_dossier.status = "refreshed"

    objective_monitor_path = paths.objective_monitor if paths.objective_monitor.exists() else None
    state.candidate_pool_lane_objective_support.analysis = analyze_btst_candidate_pool_lane_objective_support(
        paths.candidate_pool_recall_dossier.json,
        objective_monitor_path=objective_monitor_path,
    )
    _write_analysis_artifact(
        paths.candidate_pool_lane_objective_support,
        state.candidate_pool_lane_objective_support.analysis,
        render_btst_candidate_pool_lane_objective_support_markdown,
    )
    state.candidate_pool_lane_objective_support.status = "refreshed"

    state.candidate_pool_branch_priority_board.analysis = analyze_btst_candidate_pool_branch_priority_board(
        paths.candidate_pool_recall_dossier.json,
        lane_objective_support_path=paths.candidate_pool_lane_objective_support.json,
    )
    _write_analysis_artifact(
        paths.candidate_pool_branch_priority_board,
        state.candidate_pool_branch_priority_board.analysis,
        render_btst_candidate_pool_branch_priority_board_markdown,
    )
    state.candidate_pool_branch_priority_board.status = "refreshed"

    state.candidate_pool_corridor_validation_pack.analysis = analyze_btst_candidate_pool_corridor_validation_pack(
        paths.candidate_pool_recall_dossier.json,
        lane_objective_support_path=paths.candidate_pool_lane_objective_support.json,
        branch_priority_board_path=paths.candidate_pool_branch_priority_board.json,
        objective_monitor_path=objective_monitor_path,
    )
    _write_analysis_artifact(
        paths.candidate_pool_corridor_validation_pack,
        state.candidate_pool_corridor_validation_pack.analysis,
        render_btst_candidate_pool_corridor_validation_pack_markdown,
    )
    state.candidate_pool_corridor_validation_pack.status = str(state.candidate_pool_corridor_validation_pack.analysis.get("pack_status") or "refreshed")

    state.candidate_pool_corridor_shadow_pack.analysis = analyze_btst_candidate_pool_corridor_shadow_pack(paths.candidate_pool_corridor_validation_pack.json)
    _write_analysis_artifact(
        paths.candidate_pool_corridor_shadow_pack,
        state.candidate_pool_corridor_shadow_pack.analysis,
        render_btst_candidate_pool_corridor_shadow_pack_markdown,
    )
    state.candidate_pool_corridor_shadow_pack.status = str(state.candidate_pool_corridor_shadow_pack.analysis.get("shadow_status") or "refreshed")

    rebucket_candidates = [
        dict(row)
        for row in list(state.candidate_pool_recall_dossier.analysis.get("priority_handoff_branch_experiment_queue") or [])
        if str(row.get("prototype_type") or "") == "post_gate_competition_rebucket_probe"
    ]
    rebucket_ticker = str(list(rebucket_candidates[0].get("tickers") or [None])[0] or "") or None if rebucket_candidates else None

    state.candidate_pool_rebucket_shadow_pack.analysis = run_btst_candidate_pool_rebucket_shadow_pack(
        paths.candidate_pool_recall_dossier.json,
        output_dir=reports_root,
        ticker=rebucket_ticker,
    )
    _write_analysis_artifact(
        paths.candidate_pool_rebucket_shadow_pack,
        state.candidate_pool_rebucket_shadow_pack.analysis,
        render_btst_candidate_pool_rebucket_shadow_pack_markdown,
    )
    state.candidate_pool_rebucket_shadow_pack.status = str(state.candidate_pool_rebucket_shadow_pack.analysis.get("shadow_status") or "skipped_no_rebucket_candidate")

    state.candidate_pool_rebucket_objective_validation.analysis = analyze_btst_candidate_pool_rebucket_objective_validation(
        paths.candidate_pool_recall_dossier.json,
        objective_monitor_path=objective_monitor_path,
        lane_objective_support_path=paths.candidate_pool_lane_objective_support.json if state.candidate_pool_lane_objective_support.analysis else None,
        ticker=rebucket_ticker,
    )
    _write_analysis_artifact(
        paths.candidate_pool_rebucket_objective_validation,
        state.candidate_pool_rebucket_objective_validation.analysis,
        render_btst_candidate_pool_rebucket_objective_validation_markdown,
    )
    state.candidate_pool_rebucket_objective_validation.status = (
        "refreshed"
        if rebucket_candidates
        else str(state.candidate_pool_rebucket_objective_validation.analysis.get("validation_status") or "skipped_no_rebucket_candidate")
    )

    state.candidate_pool_rebucket_comparison_bundle.analysis = analyze_btst_candidate_pool_rebucket_comparison_bundle(
        paths.candidate_pool_recall_dossier.json,
        lane_objective_support_path=paths.candidate_pool_lane_objective_support.json,
        branch_priority_board_path=paths.candidate_pool_branch_priority_board.json,
        rebucket_shadow_pack_path=paths.candidate_pool_rebucket_shadow_pack.json,
        rebucket_objective_validation_path=paths.candidate_pool_rebucket_objective_validation.json,
        objective_monitor_path=objective_monitor_path,
    )
    _write_analysis_artifact(
        paths.candidate_pool_rebucket_comparison_bundle,
        state.candidate_pool_rebucket_comparison_bundle.analysis,
        render_btst_candidate_pool_rebucket_comparison_bundle_markdown,
    )
    state.candidate_pool_rebucket_comparison_bundle.status = str(state.candidate_pool_rebucket_comparison_bundle.analysis.get("bundle_status") or "refreshed")

    state.candidate_pool_upstream_handoff_board.analysis = analyze_btst_candidate_pool_upstream_handoff_board(
        paths.no_candidate_entry_failure_dossier.json,
        watchlist_recall_dossier_path=paths.watchlist_recall_dossier.json,
        candidate_pool_recall_dossier_path=paths.candidate_pool_recall_dossier.json,
    )
    _write_analysis_artifact(
        paths.candidate_pool_upstream_handoff_board,
        state.candidate_pool_upstream_handoff_board.analysis,
        render_btst_candidate_pool_upstream_handoff_board_markdown,
    )
    state.candidate_pool_upstream_handoff_board.status = str(state.candidate_pool_upstream_handoff_board.analysis.get("board_status") or "refreshed")

    state.candidate_pool_lane_pair_board.analysis = analyze_btst_candidate_pool_lane_pair_board(
        paths.candidate_pool_corridor_shadow_pack.json,
        paths.candidate_pool_rebucket_comparison_bundle.json,
        upstream_handoff_board_path=paths.candidate_pool_upstream_handoff_board.json,
    )
    _write_analysis_artifact(
        paths.candidate_pool_lane_pair_board,
        state.candidate_pool_lane_pair_board.analysis,
        render_btst_candidate_pool_lane_pair_board_markdown,
    )
    state.candidate_pool_lane_pair_board.status = str(state.candidate_pool_lane_pair_board.analysis.get("pair_status") or "refreshed")

    state.candidate_pool_corridor_uplift_runbook.analysis = analyze_btst_candidate_pool_corridor_uplift_runbook(
        paths.candidate_pool_recall_dossier.json,
        corridor_shadow_pack_path=paths.candidate_pool_corridor_shadow_pack.json,
        lane_pair_board_path=paths.candidate_pool_lane_pair_board.json,
    )
    _write_analysis_artifact(
        paths.candidate_pool_corridor_uplift_runbook,
        state.candidate_pool_corridor_uplift_runbook.analysis,
        render_btst_candidate_pool_corridor_uplift_runbook_markdown,
    )
    state.candidate_pool_corridor_uplift_runbook.status = str(state.candidate_pool_corridor_uplift_runbook.analysis.get("runbook_status") or "refreshed")
    return state


def refresh_candidate_entry_shadow_window_artifacts(
    *,
    paths: CandidateEntryShadowPaths,
    report_dirs: list[Path],
    focus_tickers: list[str],
    preserve_tickers: list[str],
    state: CandidateEntryShadowRefreshState,
) -> tuple[dict[str, Any], dict[str, Any]]:
    window_scan_analysis = analyze_btst_candidate_entry_window_scan(
        report_dirs,
        structural_variant="exclude_watchlist_avoid_weak_structure_entries",
        focus_tickers=focus_tickers,
        preserve_tickers=preserve_tickers,
    )
    _write_analysis_artifact(paths.window_scan, window_scan_analysis, render_btst_candidate_entry_window_scan_markdown)

    rollout_governance_analysis = analyze_btst_candidate_entry_rollout_governance(
        paths.frontier_report,
        structural_validation_path=paths.structural_validation,
        window_scan_path=paths.window_scan.json,
        score_frontier_path=paths.score_frontier_report,
        no_candidate_entry_action_board_path=paths.no_candidate_entry_action_board.json if state.no_candidate_entry_action_board.analysis else None,
        no_candidate_entry_replay_bundle_path=paths.no_candidate_entry_replay_bundle.json if state.no_candidate_entry_replay_bundle.analysis else None,
        no_candidate_entry_failure_dossier_path=paths.no_candidate_entry_failure_dossier.json if state.no_candidate_entry_failure_dossier.analysis else None,
        watchlist_recall_dossier_path=paths.watchlist_recall_dossier.json if state.watchlist_recall_dossier.analysis else None,
        candidate_pool_recall_dossier_path=paths.candidate_pool_recall_dossier.json if state.candidate_pool_recall_dossier.analysis else None,
    )
    _write_analysis_artifact(paths.rollout_governance, rollout_governance_analysis, render_btst_candidate_entry_rollout_governance_markdown)
    return window_scan_analysis, rollout_governance_analysis


def build_candidate_entry_shadow_missing_inputs_summary(
    *,
    missing_inputs: list[str],
    paths: CandidateEntryShadowPaths,
    state: CandidateEntryShadowRefreshState,
    window_report_count: int,
    report_summaries: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": "skipped_missing_inputs",
        "missing_inputs": missing_inputs,
        "window_report_count": window_report_count,
        **_build_missing_inputs_base_summary(paths, state),
        **report_summaries,
    }


def build_candidate_entry_shadow_no_window_summary(
    *,
    paths: CandidateEntryShadowPaths,
    state: CandidateEntryShadowRefreshState,
) -> dict[str, Any]:
    return {
        "status": "skipped_no_window_reports",
        "missing_inputs": [],
        "window_report_count": 0,
        **_build_no_window_base_summary(paths, state),
    }


def build_candidate_entry_shadow_refreshed_summary(
    *,
    paths: CandidateEntryShadowPaths,
    state: CandidateEntryShadowRefreshState,
    window_scan_analysis: dict[str, Any],
    rollout_governance_analysis: dict[str, Any],
    report_summaries: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": "refreshed",
        "missing_inputs": [],
        "window_report_count": window_scan_analysis.get("report_count"),
        "filtered_report_count": window_scan_analysis.get("filtered_report_count"),
        "focus_hit_report_count": window_scan_analysis.get("focus_hit_report_count"),
        "preserve_misfire_report_count": window_scan_analysis.get("preserve_misfire_report_count"),
        "rollout_readiness": window_scan_analysis.get("rollout_readiness"),
        "lane_status": rollout_governance_analysis.get("lane_status"),
        **_build_refreshed_base_summary(paths, state),
        **report_summaries,
        "window_scan_json": paths.window_scan.json.as_posix(),
        "rollout_governance_json": paths.rollout_governance.json.as_posix(),
    }


def build_candidate_entry_shadow_report_summaries(reports_root: Path, summary_builders: Mapping[str, SummaryBuilder]) -> dict[str, dict[str, Any]]:
    return {name: builder(reports_root) for name, builder in summary_builders.items()}


def _build_json_markdown_paths(reports_root: Path, artifact_names: Mapping[str, str], json_key: str, md_key: str) -> JsonMarkdownPaths:
    return JsonMarkdownPaths(json=reports_root / artifact_names[json_key], md=reports_root / artifact_names[md_key])


def _write_analysis_artifact(paths: JsonMarkdownPaths, analysis: dict[str, Any], render_markdown: MarkdownRenderer) -> None:
    paths.json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths.md.write_text(render_markdown(analysis), encoding="utf-8")


def _build_missing_inputs_base_summary(paths: CandidateEntryShadowPaths, state: CandidateEntryShadowRefreshState) -> dict[str, Any]:
    return {
        **_build_common_artifact_summary(paths, state),
        "candidate_pool_corridor_validation_pack_status": state.candidate_pool_corridor_validation_pack.status,
        "candidate_pool_corridor_validation_pack_json": paths.candidate_pool_corridor_validation_pack.json.as_posix() if state.candidate_pool_corridor_validation_pack.analysis else None,
        "candidate_pool_corridor_validation_pack_summary": _build_corridor_validation_pack_summary(state.candidate_pool_corridor_validation_pack.analysis),
        "candidate_pool_corridor_shadow_pack_status": state.candidate_pool_corridor_shadow_pack.status,
        "candidate_pool_corridor_shadow_pack_json": paths.candidate_pool_corridor_shadow_pack.json.as_posix() if state.candidate_pool_corridor_shadow_pack.analysis else None,
        "candidate_pool_corridor_shadow_pack_summary": _build_corridor_shadow_pack_summary(state.candidate_pool_corridor_shadow_pack.analysis),
        "candidate_pool_rebucket_comparison_bundle_status": state.candidate_pool_rebucket_comparison_bundle.status,
        "candidate_pool_rebucket_comparison_bundle_json": paths.candidate_pool_rebucket_comparison_bundle.json.as_posix() if state.candidate_pool_rebucket_comparison_bundle.analysis else None,
        "candidate_pool_rebucket_comparison_bundle_summary": _build_rebucket_comparison_bundle_summary(state.candidate_pool_rebucket_comparison_bundle.analysis),
        "candidate_pool_lane_pair_board_status": state.candidate_pool_lane_pair_board.status,
        "candidate_pool_lane_pair_board_json": paths.candidate_pool_lane_pair_board.json.as_posix() if state.candidate_pool_lane_pair_board.analysis else None,
        "candidate_pool_lane_pair_board_summary": _build_lane_pair_board_summary(state.candidate_pool_lane_pair_board.analysis),
        "candidate_pool_upstream_handoff_board_status": state.candidate_pool_upstream_handoff_board.status,
        "candidate_pool_upstream_handoff_board_json": paths.candidate_pool_upstream_handoff_board.json.as_posix() if state.candidate_pool_upstream_handoff_board.analysis else None,
        "candidate_pool_upstream_handoff_board_summary": _build_upstream_handoff_board_summary(state.candidate_pool_upstream_handoff_board.analysis),
        "candidate_pool_corridor_uplift_runbook_status": state.candidate_pool_corridor_uplift_runbook.status,
        "candidate_pool_corridor_uplift_runbook_json": paths.candidate_pool_corridor_uplift_runbook.json.as_posix() if state.candidate_pool_corridor_uplift_runbook.analysis else None,
        "candidate_pool_corridor_uplift_runbook_summary": _build_corridor_uplift_runbook_summary(state.candidate_pool_corridor_uplift_runbook.analysis),
    }


def _build_no_window_base_summary(paths: CandidateEntryShadowPaths, state: CandidateEntryShadowRefreshState) -> dict[str, Any]:
    common_summary = _build_common_artifact_summary(paths, state)
    for key in (
        "candidate_pool_corridor_validation_pack_status",
        "candidate_pool_corridor_validation_pack_json",
        "candidate_pool_corridor_validation_pack_summary",
        "candidate_pool_corridor_shadow_pack_status",
        "candidate_pool_corridor_shadow_pack_json",
        "candidate_pool_corridor_shadow_pack_summary",
        "candidate_pool_rebucket_comparison_bundle_status",
        "candidate_pool_rebucket_comparison_bundle_json",
        "candidate_pool_rebucket_comparison_bundle_summary",
        "candidate_pool_lane_pair_board_status",
        "candidate_pool_lane_pair_board_json",
        "candidate_pool_lane_pair_board_summary",
        "candidate_pool_upstream_handoff_board_status",
        "candidate_pool_upstream_handoff_board_json",
        "candidate_pool_upstream_handoff_board_summary",
        "candidate_pool_corridor_uplift_runbook_status",
        "candidate_pool_corridor_uplift_runbook_json",
        "candidate_pool_corridor_uplift_runbook_summary",
    ):
        common_summary.pop(key, None)
    return common_summary


def _build_refreshed_base_summary(paths: CandidateEntryShadowPaths, state: CandidateEntryShadowRefreshState) -> dict[str, Any]:
    return {
        **_build_common_artifact_summary(paths, state),
        "candidate_pool_corridor_validation_pack_status": state.candidate_pool_corridor_validation_pack.status,
        "candidate_pool_corridor_validation_pack_json": paths.candidate_pool_corridor_validation_pack.json.as_posix() if state.candidate_pool_corridor_validation_pack.analysis else None,
        "candidate_pool_corridor_validation_pack_summary": _build_corridor_validation_pack_summary(state.candidate_pool_corridor_validation_pack.analysis),
        "candidate_pool_corridor_shadow_pack_status": state.candidate_pool_corridor_shadow_pack.status,
        "candidate_pool_corridor_shadow_pack_json": paths.candidate_pool_corridor_shadow_pack.json.as_posix() if state.candidate_pool_corridor_shadow_pack.analysis else None,
        "candidate_pool_corridor_shadow_pack_summary": _build_corridor_shadow_pack_summary(state.candidate_pool_corridor_shadow_pack.analysis),
        "candidate_pool_rebucket_comparison_bundle_status": state.candidate_pool_rebucket_comparison_bundle.status,
        "candidate_pool_rebucket_comparison_bundle_json": paths.candidate_pool_rebucket_comparison_bundle.json.as_posix() if state.candidate_pool_rebucket_comparison_bundle.analysis else None,
        "candidate_pool_rebucket_comparison_bundle_summary": _build_rebucket_comparison_bundle_summary(state.candidate_pool_rebucket_comparison_bundle.analysis),
        "candidate_pool_lane_pair_board_status": state.candidate_pool_lane_pair_board.status,
        "candidate_pool_lane_pair_board_json": paths.candidate_pool_lane_pair_board.json.as_posix() if state.candidate_pool_lane_pair_board.analysis else None,
        "candidate_pool_lane_pair_board_summary": _build_lane_pair_board_summary(state.candidate_pool_lane_pair_board.analysis),
        "candidate_pool_upstream_handoff_board_status": state.candidate_pool_upstream_handoff_board.status,
        "candidate_pool_upstream_handoff_board_json": paths.candidate_pool_upstream_handoff_board.json.as_posix() if state.candidate_pool_upstream_handoff_board.analysis else None,
        "candidate_pool_upstream_handoff_board_summary": _build_upstream_handoff_board_summary(state.candidate_pool_upstream_handoff_board.analysis),
        "candidate_pool_corridor_uplift_runbook_status": state.candidate_pool_corridor_uplift_runbook.status,
        "candidate_pool_corridor_uplift_runbook_json": paths.candidate_pool_corridor_uplift_runbook.json.as_posix() if state.candidate_pool_corridor_uplift_runbook.analysis else None,
        "candidate_pool_corridor_uplift_runbook_summary": _build_corridor_uplift_runbook_summary(state.candidate_pool_corridor_uplift_runbook.analysis),
    }


def _build_common_artifact_summary(paths: CandidateEntryShadowPaths, state: CandidateEntryShadowRefreshState) -> dict[str, Any]:
    return {
        "no_candidate_entry_action_board_status": state.no_candidate_entry_action_board.status,
        "no_candidate_entry_priority_queue_count": state.no_candidate_entry_action_board.analysis.get("priority_queue_count"),
        "no_candidate_entry_top_tickers": state.no_candidate_entry_action_board.analysis.get("top_priority_tickers"),
        "no_candidate_entry_hotspot_report_dirs": state.no_candidate_entry_action_board.analysis.get("top_hotspot_report_dirs"),
        "no_candidate_entry_action_board_json": paths.no_candidate_entry_action_board.json.as_posix() if state.no_candidate_entry_action_board.analysis else None,
        "no_candidate_entry_replay_bundle_status": state.no_candidate_entry_replay_bundle.status,
        "no_candidate_entry_replay_bundle_json": paths.no_candidate_entry_replay_bundle.json.as_posix() if state.no_candidate_entry_replay_bundle.analysis else None,
        "no_candidate_entry_promising_tickers": state.no_candidate_entry_replay_bundle.analysis.get("promising_priority_tickers"),
        "no_candidate_entry_failure_dossier_status": state.no_candidate_entry_failure_dossier.status,
        "no_candidate_entry_failure_dossier_json": paths.no_candidate_entry_failure_dossier.json.as_posix() if state.no_candidate_entry_failure_dossier.analysis else None,
        "no_candidate_entry_upstream_absence_tickers": state.no_candidate_entry_failure_dossier.analysis.get("top_upstream_absence_tickers"),
        "no_candidate_entry_handoff_stage_counts": state.no_candidate_entry_failure_dossier.analysis.get("priority_handoff_stage_counts"),
        "no_candidate_entry_absent_from_watchlist_tickers": state.no_candidate_entry_failure_dossier.analysis.get("top_absent_from_watchlist_tickers"),
        "no_candidate_entry_watchlist_handoff_gap_tickers": state.no_candidate_entry_failure_dossier.analysis.get("top_watchlist_visible_but_not_candidate_entry_tickers"),
        "no_candidate_entry_candidate_entry_target_gap_tickers": state.no_candidate_entry_failure_dossier.analysis.get("top_candidate_entry_visible_but_not_selection_target_tickers"),
        "no_candidate_entry_handoff_action_queue_task_ids": _extract_task_ids(state.no_candidate_entry_failure_dossier.analysis.get("priority_handoff_action_queue")),
        "no_candidate_entry_semantic_miss_tickers": state.no_candidate_entry_failure_dossier.analysis.get("top_candidate_entry_semantic_miss_tickers"),
        "watchlist_recall_dossier_status": state.watchlist_recall_dossier.status,
        "watchlist_recall_dossier_json": paths.watchlist_recall_dossier.json.as_posix() if state.watchlist_recall_dossier.analysis else None,
        "watchlist_recall_stage_counts": state.watchlist_recall_dossier.analysis.get("priority_recall_stage_counts"),
        "watchlist_recall_absent_from_candidate_pool_tickers": state.watchlist_recall_dossier.analysis.get("top_absent_from_candidate_pool_tickers"),
        "watchlist_recall_candidate_pool_layer_b_gap_tickers": state.watchlist_recall_dossier.analysis.get("top_candidate_pool_visible_but_missing_layer_b_tickers"),
        "watchlist_recall_layer_b_watchlist_gap_tickers": state.watchlist_recall_dossier.analysis.get("top_layer_b_visible_but_missing_watchlist_tickers"),
        "watchlist_recall_action_queue_task_ids": _extract_task_ids(state.watchlist_recall_dossier.analysis.get("action_queue")),
        "candidate_pool_recall_dossier_status": state.candidate_pool_recall_dossier.status,
        "candidate_pool_recall_dossier_json": paths.candidate_pool_recall_dossier.json.as_posix() if state.candidate_pool_recall_dossier.analysis else None,
        "candidate_pool_recall_stage_counts": state.candidate_pool_recall_dossier.analysis.get("priority_stage_counts"),
        "candidate_pool_recall_dominant_stage": state.candidate_pool_recall_dossier.analysis.get("dominant_stage"),
        "candidate_pool_recall_top_stage_tickers": state.candidate_pool_recall_dossier.analysis.get("top_stage_tickers"),
        "candidate_pool_recall_truncation_frontier_summary": state.candidate_pool_recall_dossier.analysis.get("truncation_frontier_summary"),
        "candidate_pool_recall_dominant_liquidity_gap_mode": dict(state.candidate_pool_recall_dossier.analysis.get("truncation_frontier_summary") or {}).get("dominant_liquidity_gap_mode"),
        "candidate_pool_recall_focus_liquidity_profiles": list(dict(state.candidate_pool_recall_dossier.analysis.get("focus_liquidity_profile_summary") or {}).get("primary_focus_tickers") or [])[:3],
        "candidate_pool_recall_priority_handoff_counts": dict(dict(state.candidate_pool_recall_dossier.analysis.get("focus_liquidity_profile_summary") or {}).get("priority_handoff_counts") or {}),
        "candidate_pool_recall_priority_handoff_branch_diagnoses": list(state.candidate_pool_recall_dossier.analysis.get("priority_handoff_branch_diagnoses") or [])[:3],
        "candidate_pool_recall_priority_handoff_branch_mechanisms": list(state.candidate_pool_recall_dossier.analysis.get("priority_handoff_branch_mechanisms") or [])[:3],
        "candidate_pool_recall_priority_handoff_branch_experiment_queue": list(state.candidate_pool_recall_dossier.analysis.get("priority_handoff_branch_experiment_queue") or [])[:3],
        "candidate_pool_branch_priority_board_status": state.candidate_pool_branch_priority_board.status,
        "candidate_pool_branch_priority_board_json": paths.candidate_pool_branch_priority_board.json.as_posix() if state.candidate_pool_branch_priority_board.analysis else None,
        "candidate_pool_branch_priority_board_rows": list(state.candidate_pool_branch_priority_board.analysis.get("branch_rows") or [])[:3],
        "candidate_pool_branch_priority_alignment_status": state.candidate_pool_branch_priority_board.analysis.get("priority_alignment_status"),
        "candidate_pool_branch_priority_alignment_summary": state.candidate_pool_branch_priority_board.analysis.get("alignment_summary"),
        "candidate_pool_lane_objective_support_status": state.candidate_pool_lane_objective_support.status,
        "candidate_pool_lane_objective_support_json": paths.candidate_pool_lane_objective_support.json.as_posix() if state.candidate_pool_lane_objective_support.analysis else None,
        "candidate_pool_lane_objective_support_rows": list(state.candidate_pool_lane_objective_support.analysis.get("branch_rows") or [])[:3],
        "candidate_pool_rebucket_shadow_pack_status": state.candidate_pool_rebucket_shadow_pack.status,
        "candidate_pool_rebucket_shadow_pack_json": paths.candidate_pool_rebucket_shadow_pack.json.as_posix() if state.candidate_pool_rebucket_shadow_pack.analysis else None,
        "candidate_pool_rebucket_shadow_pack_experiment": dict(state.candidate_pool_rebucket_shadow_pack.analysis.get("experiment") or {}),
        "candidate_pool_rebucket_objective_validation_status": state.candidate_pool_rebucket_objective_validation.status,
        "candidate_pool_rebucket_objective_validation_json": paths.candidate_pool_rebucket_objective_validation.json.as_posix() if state.candidate_pool_rebucket_objective_validation.analysis else None,
        "candidate_pool_rebucket_objective_validation_summary": {
            "validation_status": state.candidate_pool_rebucket_objective_validation.analysis.get("validation_status"),
            "support_verdict": dict(state.candidate_pool_rebucket_objective_validation.analysis.get("branch_objective_row") or {}).get("support_verdict"),
            "mean_t_plus_2_return": dict(state.candidate_pool_rebucket_objective_validation.analysis.get("branch_objective_row") or {}).get("mean_t_plus_2_return"),
        },
        "candidate_pool_recall_action_queue_task_ids": _extract_task_ids(state.candidate_pool_recall_dossier.analysis.get("action_queue")),
    }


def _build_corridor_validation_pack_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "pack_status": analysis.get("pack_status"),
        "focus_ticker": analysis.get("focus_ticker"),
        "primary_validation_ticker": dict(analysis.get("primary_validation_ticker") or {}).get("ticker"),
        "leader_gap_to_target": analysis.get("leader_gap_to_target"),
        "promotion_readiness_status": analysis.get("promotion_readiness_status"),
        "parallel_watch_tickers": [str(row.get("ticker") or "") for row in list(analysis.get("parallel_watch_tickers") or [])[:3] if str(row.get("ticker") or "").strip()],
    }


def _build_corridor_shadow_pack_ticker_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": payload.get("ticker"),
        "validation_priority_rank": payload.get("validation_priority_rank"),
        "tractability_tier": payload.get("tractability_tier"),
        "closed_cycle_count": payload.get("closed_cycle_count"),
        "t_plus_2_positive_rate": payload.get("t_plus_2_positive_rate"),
        "t_plus_2_return_hit_rate_at_target": payload.get("t_plus_2_return_hit_rate_at_target"),
        "mean_t_plus_2_return": payload.get("mean_t_plus_2_return"),
        "objective_fit_score": payload.get("objective_fit_score"),
        "uplift_to_cutoff_multiple_mean": payload.get("uplift_to_cutoff_multiple_mean"),
    }


def _build_corridor_shadow_pack_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    primary_shadow_replay_raw = analysis.get("primary_shadow_replay")
    primary_shadow_replay_payload = dict(primary_shadow_replay_raw or {}) if isinstance(primary_shadow_replay_raw, dict) else {"ticker": primary_shadow_replay_raw}
    return {
        "shadow_status": analysis.get("shadow_status"),
        "primary_shadow_replay": _build_corridor_shadow_pack_ticker_summary(primary_shadow_replay_payload),
        "parallel_watch_tickers": [str(row.get("ticker") or "") for row in list(analysis.get("parallel_watch_lanes") or [])[:3] if str(row.get("ticker") or "").strip()],
        "parallel_watch_outcome_loop": [
            _build_corridor_shadow_pack_ticker_summary(dict(row or {}))
            for row in list(analysis.get("parallel_watch_lanes") or [])[:3]
            if str(dict(row or {}).get("ticker") or "").strip()
        ],
        "excluded_low_gate_tail_tickers": [str(ticker) for ticker in list(analysis.get("excluded_low_gate_tail_tickers") or [])[:3] if str(ticker).strip()],
    }


def _build_rebucket_comparison_bundle_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "bundle_status": analysis.get("bundle_status"),
        "structural_leader": dict(analysis.get("structural_leader") or {}).get("priority_handoff"),
        "objective_leader": dict(analysis.get("objective_leader") or {}).get("priority_handoff"),
        "rebucket_ticker": dict(analysis.get("rebucket_objective_row") or {}).get("ticker") or (list(dict(analysis.get("rebucket_objective_row") or {}).get("tickers") or [])[:1] or [None])[0],
        "objective_fit_gap_vs_corridor": dict(analysis.get("comparison") or {}).get("objective_fit_gap_vs_corridor"),
        "mean_t_plus_2_return_gap_vs_corridor": dict(analysis.get("comparison") or {}).get("mean_t_plus_2_return_gap_vs_corridor"),
    }


def _build_lane_pair_board_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "pair_status": analysis.get("pair_status"),
        "board_leader": dict(analysis.get("board_leader") or {}).get("ticker"),
        "leader_lane_family": dict(analysis.get("board_leader") or {}).get("lane_family"),
        "leader_governance_status": dict(analysis.get("board_leader") or {}).get("governance_status"),
        "leader_governance_blocker": dict(analysis.get("board_leader") or {}).get("governance_blocker"),
        "leader_governance_execution_quality": dict(analysis.get("board_leader") or {}).get("governance_execution_quality_label"),
        "leader_governance_entry_timing_bias": dict(analysis.get("board_leader") or {}).get("governance_entry_timing_bias"),
        "leader_current_decision": dict(analysis.get("board_leader") or {}).get("current_decision"),
        "parallel_watch_ticker": next((row.get("ticker") for row in list(analysis.get("candidates") or []) if str(row.get("role") or "") == "parallel_watch"), None),
        "parallel_watch_governance_blocker": next((row.get("governance_blocker") for row in list(analysis.get("candidates") or []) if str(row.get("role") or "") == "parallel_watch"), None),
        "parallel_watch_same_source_sample_count": next((row.get("governance_same_source_sample_count") for row in list(analysis.get("candidates") or []) if str(row.get("role") or "") == "parallel_watch"), None),
        "parallel_watch_next_close_positive_rate": next((row.get("governance_same_source_next_close_positive_rate") for row in list(analysis.get("candidates") or []) if str(row.get("role") or "") == "parallel_watch"), None),
        "parallel_watch_next_close_return_mean": next((row.get("governance_same_source_next_close_return_mean") for row in list(analysis.get("candidates") or []) if str(row.get("role") or "") == "parallel_watch"), None),
    }


def _build_upstream_handoff_board_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "board_status": analysis.get("board_status"),
        "focus_tickers": list(analysis.get("focus_tickers") or [])[:3],
        "first_broken_handoff_counts": dict(dict(analysis.get("stage_summary") or {}).get("first_broken_handoff_counts") or {}),
        "historical_shadow_probe_tickers": [
            str(row.get("ticker") or "")
            for row in list(analysis.get("board_rows") or [])
            if str(row.get("board_phase") or "") == "historical_shadow_probe_gap" and str(row.get("ticker") or "").strip()
        ][:3],
    }


def _build_corridor_uplift_runbook_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "runbook_status": analysis.get("runbook_status"),
        "primary_shadow_replay": analysis.get("primary_shadow_replay"),
        "parallel_watch_tickers": list(analysis.get("parallel_watch_tickers") or [])[:3],
        "excluded_low_gate_tail_tickers": list(analysis.get("excluded_low_gate_tail_tickers") or [])[:3],
        "prototype_type": analysis.get("prototype_type"),
        "next_step": analysis.get("next_step"),
        "execution_step_head": next(iter(list(analysis.get("execution_steps") or [])), None),
        "execution_command_head": next(iter(list(analysis.get("execution_commands") or [])), None),
        "guardrail_head": next(iter(list(analysis.get("guardrails") or [])), None),
    }


def _extract_task_ids(rows: Any) -> list[str]:
    return [str(row.get("task_id") or "") for row in list(rows or [])[:3] if str(row.get("task_id") or "").strip()]
