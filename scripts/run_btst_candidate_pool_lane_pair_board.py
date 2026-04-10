from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.run_btst_candidate_pool_corridor_shadow_pack import analyze_btst_candidate_pool_corridor_shadow_pack
from scripts.run_btst_candidate_pool_rebucket_comparison_bundle import analyze_btst_candidate_pool_rebucket_comparison_bundle


REPORTS_DIR = Path("data/reports")
DEFAULT_CORRIDOR_SHADOW_PACK_PATH = REPORTS_DIR / "btst_candidate_pool_corridor_shadow_pack_latest.json"
DEFAULT_REBUCKET_COMPARISON_BUNDLE_PATH = REPORTS_DIR / "btst_candidate_pool_rebucket_comparison_bundle_latest.json"
DEFAULT_GOVERNANCE_SYNTHESIS_PATH = REPORTS_DIR / "btst_governance_synthesis_latest.json"
DEFAULT_UPSTREAM_HANDOFF_BOARD_PATH = REPORTS_DIR / "btst_candidate_pool_upstream_handoff_board_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_candidate_pool_lane_pair_board_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_candidate_pool_lane_pair_board_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _maybe_load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return _load_json(resolved)


def _candidate_row(
    *,
    ticker: str | None,
    lane_family: str,
    role: str,
    mean_t_plus_2_return: float | None,
    objective_fit_score: float | None,
    t_plus_2_return_hit_rate_at_target: float | None,
    t_plus_2_positive_rate: float | None,
    tractability_tier: str | None,
    current_decision: str | None = None,
    current_candidate_source: str | None = None,
    governance_status: str | None = None,
    governance_blocker: str | None = None,
    governance_summary: str | None = None,
    governance_same_source_sample_count: int | None = None,
    governance_same_source_next_close_positive_rate: float | None = None,
    governance_same_source_next_close_return_mean: float | None = None,
    governance_execution_quality_label: str | None = None,
    governance_entry_timing_bias: str | None = None,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "lane_family": lane_family,
        "role": role,
        "mean_t_plus_2_return": mean_t_plus_2_return,
        "objective_fit_score": objective_fit_score,
        "t_plus_2_return_hit_rate_at_target": t_plus_2_return_hit_rate_at_target,
        "t_plus_2_positive_rate": t_plus_2_positive_rate,
        "tractability_tier": tractability_tier,
        "current_decision": current_decision,
        "current_candidate_source": current_candidate_source,
        "governance_status": governance_status,
        "governance_blocker": governance_blocker,
        "governance_summary": governance_summary,
        "governance_same_source_sample_count": governance_same_source_sample_count,
        "governance_same_source_next_close_positive_rate": governance_same_source_next_close_positive_rate,
        "governance_same_source_next_close_return_mean": governance_same_source_next_close_return_mean,
        "governance_execution_quality_label": governance_execution_quality_label,
        "governance_entry_timing_bias": governance_entry_timing_bias,
    }


def _apply_governance_constraint_overlays(
    raw_overlays: dict[str, dict[str, Any]],
    constraints: list[dict[str, Any]],
) -> None:
    for constraint in constraints:
        row = dict(constraint or {})
        for ticker in list(row.get("focus_tickers") or []):
            normalized = str(ticker or "").strip()
            if not normalized:
                continue
            raw_overlays.setdefault(normalized, {}).update(
                {
                    "governance_status": row.get("status"),
                    "governance_blocker": row.get("blocker"),
                    "governance_summary": row.get("recommendation"),
                }
            )


def _resolve_followup_governance_override(entry: dict[str, Any]) -> dict[str, Any]:
    historical_next_close_positive_rate = entry.get("historical_next_close_positive_rate")
    top_reasons = [str(reason) for reason in list(entry.get("top_reasons") or []) if str(reason).strip()]
    if (
        entry.get("candidate_source") == "upstream_liquidity_corridor_shadow"
        and entry.get("decision") == "selected"
        and entry.get("historical_execution_quality_label") in {"intraday_only", "gap_chase_risk"}
    ):
        return {
            "governance_status": "continuation_confirm_only_intraday_bias",
            "governance_blocker": "weak_overnight_follow_through_after_shadow_recall",
            "governance_summary": (
                "Latest upstream shadow selected row still behaves like a confirmation-only setup; "
                "historical payoff is stronger intraday than overnight, so keep it out of standard BTST hold assumptions."
            ),
        }

    if (
        entry.get("candidate_source") == "upstream_liquidity_corridor_shadow"
        and entry.get("decision") == "near_miss"
        and "profitability_hard_cliff" in top_reasons
    ):
        sample_count = entry.get("historical_sample_count")
        next_close_positive_rate = entry.get("historical_next_close_positive_rate")
        next_close_return_mean = entry.get("historical_next_close_return_mean")
        weak_payoff_suffix = ""
        if sample_count is not None or next_close_positive_rate is not None or next_close_return_mean is not None:
            weak_payoff_suffix = (
                " Historical same-source near-miss payoff remains weak"
                f" (samples={sample_count}, next_close_positive_rate={next_close_positive_rate},"
                f" next_close_return_mean={next_close_return_mean})."
            )
        return {
            "governance_status": "parallel_watch_only_not_default_ready",
            "governance_blocker": "profitability_hard_cliff_and_weak_same_source_payoff",
            "governance_summary": (
                "Keep corridor profitability-cliff names as confirmatory parallel watch only; "
                "do not treat a single-window near-miss uplift as a default BTST upgrade."
                f"{weak_payoff_suffix}"
            ),
        }

    if historical_next_close_positive_rate is not None and float(historical_next_close_positive_rate) <= 0.2:
        return {
            "governance_status": "monitor_only_weak_historical_payoff",
            "governance_blocker": "weak_same_source_payoff",
            "governance_summary": "Latest followup remains monitor-only because historical same-source payoff is still weak.",
        }
    return {}


def _apply_followup_governance_overlays(
    raw_overlays: dict[str, dict[str, Any]],
    followups: list[dict[str, Any]],
) -> None:
    for followup in followups:
        entries = [dict(entry or {}) for entry in list(followup.get("entries") or [])]
        for entry in entries:
            ticker = str(entry.get("ticker") or "").strip()
            if not ticker:
                continue
            overlay = raw_overlays.setdefault(ticker, {})
            overlay.setdefault("current_decision", entry.get("decision"))
            overlay.setdefault("current_candidate_source", entry.get("candidate_source"))
            if entry.get("historical_execution_quality_label") not in (None, "", [], {}):
                overlay.setdefault("governance_execution_quality_label", entry.get("historical_execution_quality_label"))
            if entry.get("historical_entry_timing_bias") not in (None, "", [], {}):
                overlay.setdefault("governance_entry_timing_bias", entry.get("historical_entry_timing_bias"))

            followup_override = _resolve_followup_governance_override(entry)
            if followup_override:
                overlay.update(followup_override)
                continue
            if overlay.get("governance_status"):
                continue

            overlay.update(_resolve_followup_governance_override(entry))


def _build_governance_overlays(governance_synthesis: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_overlays: dict[str, dict[str, Any]] = {}
    _apply_governance_constraint_overlays(
        raw_overlays,
        [dict(constraint or {}) for constraint in list(governance_synthesis.get("execution_surface_constraints") or [])],
    )
    _apply_followup_governance_overlays(
        raw_overlays,
        [dict(row or {}) for row in list(governance_synthesis.get("evidence_btst_followups") or [])],
    )

    return {
        ticker: overlay
        for ticker, overlay in raw_overlays.items()
        if overlay.get("governance_status") or overlay.get("governance_blocker") or overlay.get("governance_summary")
    }


def _resolve_upstream_handoff_board_path(
    corridor_shadow_pack_path: str | Path,
    upstream_handoff_board_path: str | Path | None = None,
) -> Path | None:
    if upstream_handoff_board_path:
        resolved = Path(upstream_handoff_board_path).expanduser().resolve()
        return resolved if resolved.exists() else None
    sibling = Path(corridor_shadow_pack_path).expanduser().resolve().parent / DEFAULT_UPSTREAM_HANDOFF_BOARD_PATH.name
    return sibling if sibling.exists() else None


def _build_upstream_handoff_overlays(upstream_handoff_board: dict[str, Any]) -> dict[str, dict[str, Any]]:
    overlays: dict[str, dict[str, Any]] = {}
    for row in [dict(item or {}) for item in list(upstream_handoff_board.get("board_rows") or [])]:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        governance_status = row.get("downstream_followup_status")
        governance_blocker = row.get("downstream_followup_blocker")
        governance_summary = row.get("downstream_followup_summary")
        if (
            governance_blocker == "profitability_hard_cliff_and_weak_same_source_payoff"
            and (
                row.get("latest_followup_historical_sample_count") is not None
                or row.get("latest_followup_historical_next_close_positive_rate") is not None
                or row.get("latest_followup_historical_next_close_return_mean") is not None
            )
        ):
            governance_summary = (
                f"{governance_summary} Historical same-source near-miss payoff remains weak"
                f" (samples={row.get('latest_followup_historical_sample_count')},"
                f" next_close_positive_rate={row.get('latest_followup_historical_next_close_positive_rate')},"
                f" next_close_return_mean={row.get('latest_followup_historical_next_close_return_mean')})."
            )
        if governance_status or governance_blocker or governance_summary:
            overlays[ticker] = {
                "current_decision": row.get("latest_followup_decision"),
                "current_candidate_source": row.get("latest_followup_candidate_source"),
                "governance_status": governance_status,
                "governance_blocker": governance_blocker,
                "governance_summary": governance_summary,
                "governance_same_source_sample_count": row.get("latest_followup_historical_sample_count"),
                "governance_same_source_next_close_positive_rate": row.get("latest_followup_historical_next_close_positive_rate"),
                "governance_same_source_next_close_return_mean": row.get("latest_followup_historical_next_close_return_mean"),
                "governance_execution_quality_label": row.get("latest_followup_historical_execution_quality_label"),
                "governance_entry_timing_bias": row.get("latest_followup_historical_entry_timing_bias"),
            }
    return overlays


def _resolve_rebucket_ticker(rebucket: dict[str, Any]) -> Any:
    return rebucket.get("ticker") or (list(rebucket.get("tickers") or [])[:1] or [None])[0]


def _build_lane_pair_governance_overlays(
    corridor_shadow_pack_path: str | Path,
    governance_synthesis_path: str | Path | None,
    upstream_handoff_board_path: str | Path | None,
) -> tuple[dict[str, dict[str, Any]], Path | None]:
    governance_synthesis = _maybe_load_json(governance_synthesis_path or DEFAULT_GOVERNANCE_SYNTHESIS_PATH)
    governance_overlays = _build_governance_overlays(governance_synthesis)
    resolved_upstream_handoff_board_path = _resolve_upstream_handoff_board_path(corridor_shadow_pack_path, upstream_handoff_board_path)
    upstream_handoff_board = _maybe_load_json(resolved_upstream_handoff_board_path)
    for ticker, overlay in _build_upstream_handoff_overlays(upstream_handoff_board).items():
        governance_overlays.setdefault(ticker, {}).update({key: value for key, value in overlay.items() if value is not None})
    return governance_overlays, resolved_upstream_handoff_board_path


def _build_lane_pair_candidates(
    *,
    primary: dict[str, Any],
    parallel: list[dict[str, Any]],
    rebucket: dict[str, Any],
    governance_overlays: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rebucket_ticker = _resolve_rebucket_ticker(rebucket)
    candidates = [
        _candidate_row(
            ticker=primary.get("ticker"),
            lane_family="corridor",
            role="primary_shadow_replay",
            mean_t_plus_2_return=primary.get("mean_t_plus_2_return"),
            objective_fit_score=primary.get("objective_fit_score"),
            t_plus_2_return_hit_rate_at_target=primary.get("t_plus_2_return_hit_rate_at_target"),
            t_plus_2_positive_rate=primary.get("t_plus_2_positive_rate"),
            tractability_tier=primary.get("tractability_tier"),
            **governance_overlays.get(str(primary.get("ticker") or "").strip(), {}),
        ),
        _candidate_row(
            ticker=rebucket_ticker,
            lane_family="rebucket",
            role="structural_challenger",
            mean_t_plus_2_return=rebucket.get("mean_t_plus_2_return"),
            objective_fit_score=rebucket.get("objective_fit_score"),
            t_plus_2_return_hit_rate_at_target=rebucket.get("t_plus_2_return_hit_rate_at_target"),
            t_plus_2_positive_rate=rebucket.get("t_plus_2_positive_rate"),
            tractability_tier=rebucket.get("prototype_readiness"),
            **governance_overlays.get(str(rebucket_ticker or "").strip(), {}),
        ),
    ]
    for row in parallel:
        candidates.append(
            _candidate_row(
                ticker=row.get("ticker"),
                lane_family="corridor",
                role="parallel_watch",
                mean_t_plus_2_return=row.get("mean_t_plus_2_return"),
                objective_fit_score=row.get("objective_fit_score"),
                t_plus_2_return_hit_rate_at_target=row.get("t_plus_2_return_hit_rate_at_target"),
                t_plus_2_positive_rate=row.get("t_plus_2_positive_rate"),
                tractability_tier=row.get("tractability_tier"),
                **governance_overlays.get(str(row.get("ticker") or "").strip(), {}),
            )
        )

    existing_tickers = {str(row.get("ticker") or "").strip() for row in candidates if str(row.get("ticker") or "").strip()}
    for ticker, overlay in governance_overlays.items():
        if not ticker or ticker in existing_tickers:
            continue
        candidates.append(
            _candidate_row(
                ticker=ticker,
                lane_family="governance_overlay",
                role="execution_blocked_followup",
                mean_t_plus_2_return=None,
                objective_fit_score=None,
                t_plus_2_return_hit_rate_at_target=None,
                t_plus_2_positive_rate=None,
                tractability_tier="governance_only",
                **overlay,
            )
        )

    candidates = [row for row in candidates if row.get("ticker")]
    candidates.sort(
        key=lambda row: (
            0 if row.get("role") == "primary_shadow_replay" else 1,
            0 if row.get("lane_family") == "corridor" else 1,
            -(float(row.get("objective_fit_score") or -999.0)),
            -(float(row.get("mean_t_plus_2_return") or -999.0)),
            str(row.get("ticker") or ""),
        )
    )
    for index, row in enumerate(candidates, start=1):
        row["board_rank"] = index
    return candidates


def _build_lane_pair_guidance(
    *,
    primary: dict[str, Any],
    comparison: dict[str, Any],
    board_leader: dict[str, Any],
    governance_overlays: dict[str, dict[str, Any]],
) -> tuple[str, list[str]]:
    has_active_rebucket_challenger = bool(comparison.get("rebucket_ticker"))
    if board_leader.get("lane_family") == "corridor":
        recommendation = (
            f"lane pair board 当前仍应由 corridor 主导，首选 ticker={board_leader.get('ticker')}。"
            + (
                f" rebucket ticker={comparison.get('rebucket_ticker')} 保留为结构 challenger，用于并行收益对照。"
                if has_active_rebucket_challenger
                else " 当前没有 active rebucket challenger，不应分散主槽位注意力。"
            )
        )
    elif board_leader:
        recommendation = (
            f"rebucket 当前在 pair board 中反超，ticker={board_leader.get('ticker')}。"
            " 但只有在新增窗口继续成立时，才允许它挤占 corridor primary replay 槽位。"
        )
    else:
        recommendation = "当前没有可排名的 corridor/rebucket lane 候选。"

    next_actions = [
        f"保持 corridor primary ticker {primary.get('ticker') or 'N/A'} 为第一 replay 槽位。",
        "parallel_watch 只承担 confirmatory evidence，不允许直接替换 primary replay 优先级。",
        (
            f"保持 rebucket ticker {comparison.get('rebucket_ticker')} 为结构 challenger，对照 corridor 主槽位表现。"
            if has_active_rebucket_challenger
            else "当前没有 active rebucket challenger；先修复 persistence / active lane 资格，再恢复并行收益对照。"
        ),
    ]
    if governance_overlays.get("300720", {}).get("governance_status"):
        if governance_overlays.get("300720", {}).get("governance_status") == "continuation_confirm_only_intraday_bias":
            next_actions.append("300720 继续保持 confirmation-only；盘中确认后可做 intraday 机会，但不要默认当成标准隔夜 BTST 持有。")
        else:
            next_actions.append("300720 继续保持 continuation / observation-only，等待 selected persistence 或独立窗口 edge。")
    if governance_overlays.get("003036", {}).get("governance_status"):
        next_actions.append("003036 保持 profitability-cliff parallel watch，不把单窗口 near-miss uplift 当成默认 BTST 放行证据。")
    if governance_overlays.get("301292", {}).get("governance_status"):
        next_actions.append("301292 保持 shadow-recall diagnostics，不进入 execution lanes。")
    return recommendation, next_actions


def analyze_btst_candidate_pool_lane_pair_board(
    corridor_shadow_pack_path: str | Path,
    rebucket_comparison_bundle_path: str | Path,
    governance_synthesis_path: str | Path | None = None,
    upstream_handoff_board_path: str | Path | None = None,
) -> dict[str, Any]:
    corridor_pack = _maybe_load_json(corridor_shadow_pack_path)
    if not corridor_pack:
        corridor_pack = analyze_btst_candidate_pool_corridor_shadow_pack(REPORTS_DIR / "btst_candidate_pool_corridor_validation_pack_latest.json")

    rebucket_bundle = _maybe_load_json(rebucket_comparison_bundle_path)
    if not rebucket_bundle:
        rebucket_bundle = analyze_btst_candidate_pool_rebucket_comparison_bundle(REPORTS_DIR / "btst_candidate_pool_recall_dossier_latest.json")

    governance_overlays, resolved_upstream_handoff_board_path = _build_lane_pair_governance_overlays(
        corridor_shadow_pack_path,
        governance_synthesis_path,
        upstream_handoff_board_path,
    )
    primary = dict(corridor_pack.get("primary_shadow_replay") or {})
    parallel = [dict(row) for row in list(corridor_pack.get("parallel_watch_lanes") or [])]
    rebucket = dict(rebucket_bundle.get("rebucket_objective_row") or {})
    candidates = _build_lane_pair_candidates(
        primary=primary,
        parallel=parallel,
        rebucket=rebucket,
        governance_overlays=governance_overlays,
    )

    pair_status = "ready_for_ranked_comparison" if candidates else "skipped_missing_candidates"
    board_leader = dict(candidates[0]) if candidates else {}

    comparison = {
        "corridor_primary_ticker": primary.get("ticker"),
        "corridor_primary_objective_fit_score": primary.get("objective_fit_score"),
        "corridor_primary_mean_t_plus_2_return": primary.get("mean_t_plus_2_return"),
        "rebucket_ticker": _resolve_rebucket_ticker(rebucket),
        "rebucket_objective_fit_score": rebucket.get("objective_fit_score"),
        "rebucket_mean_t_plus_2_return": rebucket.get("mean_t_plus_2_return"),
        "alignment_status": rebucket_bundle.get("priority_alignment_status"),
        "governance_overlay_count": len(governance_overlays),
    }
    recommendation, next_actions = _build_lane_pair_guidance(
        primary=primary,
        comparison=comparison,
        board_leader=board_leader,
        governance_overlays=governance_overlays,
    )

    return {
        "corridor_shadow_pack_path": str(Path(corridor_shadow_pack_path).expanduser().resolve()),
        "rebucket_comparison_bundle_path": str(Path(rebucket_comparison_bundle_path).expanduser().resolve()),
        "governance_synthesis_path": str(Path(governance_synthesis_path or DEFAULT_GOVERNANCE_SYNTHESIS_PATH).expanduser().resolve()),
        "upstream_handoff_board_path": str(resolved_upstream_handoff_board_path) if resolved_upstream_handoff_board_path else None,
        "pair_status": pair_status,
        "board_leader": board_leader,
        "candidates": candidates,
        "comparison": comparison,
        "recommendation": recommendation,
        "next_actions": next_actions,
    }


def render_btst_candidate_pool_lane_pair_board_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Candidate Pool Lane Pair Board")
    lines.append("")
    lines.append("## Status")
    lines.append(f"- pair_status: {analysis.get('pair_status')}")
    leader = dict(analysis.get("board_leader") or {})
    if leader:
        lines.append(
            f"- board_leader: ticker={leader.get('ticker')} lane_family={leader.get('lane_family')} role={leader.get('role')} board_rank={leader.get('board_rank')}"
        )
    lines.append("")
    lines.append("## Candidates")
    for row in list(analysis.get("candidates") or []):
        lines.append(
            f"- board_rank={row.get('board_rank')} ticker={row.get('ticker')} lane_family={row.get('lane_family')} role={row.get('role')} objective_fit_score={row.get('objective_fit_score')} mean_t_plus_2_return={row.get('mean_t_plus_2_return')} tractability_tier={row.get('tractability_tier')} current_decision={row.get('current_decision')} governance_status={row.get('governance_status')} governance_blocker={row.get('governance_blocker')}"
        )
        if row.get("governance_execution_quality_label"):
            lines.append(f"  - governance_execution_quality_label: {row.get('governance_execution_quality_label')}")
        if row.get("governance_entry_timing_bias"):
            lines.append(f"  - governance_entry_timing_bias: {row.get('governance_entry_timing_bias')}")
        if row.get("governance_summary"):
            lines.append(f"  - governance_summary: {row.get('governance_summary')}")
    if not list(analysis.get("candidates") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Comparison")
    for key, value in dict(analysis.get("comparison") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    for item in list(analysis.get("next_actions") or []):
        lines.append(f"- next_action: {item}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a pair board for corridor and rebucket candidate-pool lanes.")
    parser.add_argument("--corridor-shadow-pack-path", default=str(DEFAULT_CORRIDOR_SHADOW_PACK_PATH))
    parser.add_argument("--rebucket-comparison-bundle-path", default=str(DEFAULT_REBUCKET_COMPARISON_BUNDLE_PATH))
    parser.add_argument("--governance-synthesis-path", default=str(DEFAULT_GOVERNANCE_SYNTHESIS_PATH))
    parser.add_argument("--upstream-handoff-board-path", default=None)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_lane_pair_board(
        args.corridor_shadow_pack_path,
        args.rebucket_comparison_bundle_path,
        governance_synthesis_path=args.governance_synthesis_path,
        upstream_handoff_board_path=args.upstream_handoff_board_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_candidate_pool_lane_pair_board_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))
