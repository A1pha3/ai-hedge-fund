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
    }


def _build_governance_overlays(governance_synthesis: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_overlays: dict[str, dict[str, Any]] = {}

    for constraint in list(governance_synthesis.get("execution_surface_constraints") or []):
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

    followups = [dict(row or {}) for row in list(governance_synthesis.get("evidence_btst_followups") or [])]
    for followup in followups:
        entries = [dict(entry or {}) for entry in list(followup.get("entries") or [])]
        for entry in entries:
            ticker = str(entry.get("ticker") or "").strip()
            if not ticker:
                continue
            overlay = raw_overlays.setdefault(ticker, {})
            overlay.setdefault("current_decision", entry.get("decision"))
            overlay.setdefault("current_candidate_source", entry.get("candidate_source"))

            if overlay.get("governance_status"):
                continue

            top_reasons = [str(reason) for reason in list(entry.get("top_reasons") or []) if str(reason).strip()]
            historical_next_close_positive_rate = entry.get("historical_next_close_positive_rate")
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
                overlay.update(
                    {
                        "governance_status": "parallel_watch_only_not_default_ready",
                        "governance_blocker": "profitability_hard_cliff_and_weak_same_source_payoff",
                        "governance_summary": (
                            "Keep corridor profitability-cliff names as confirmatory parallel watch only; "
                            "do not treat a single-window near-miss uplift as a default BTST upgrade."
                            f"{weak_payoff_suffix}"
                        ),
                    }
                )
            elif historical_next_close_positive_rate is not None and float(historical_next_close_positive_rate) <= 0.2:
                overlay.update(
                    {
                        "governance_status": "monitor_only_weak_historical_payoff",
                        "governance_blocker": "weak_same_source_payoff",
                        "governance_summary": "Latest followup remains monitor-only because historical same-source payoff is still weak.",
                    }
                )

    return {
        ticker: overlay
        for ticker, overlay in raw_overlays.items()
        if overlay.get("governance_status") or overlay.get("governance_blocker") or overlay.get("governance_summary")
    }


def analyze_btst_candidate_pool_lane_pair_board(
    corridor_shadow_pack_path: str | Path,
    rebucket_comparison_bundle_path: str | Path,
    governance_synthesis_path: str | Path | None = None,
) -> dict[str, Any]:
    corridor_pack = _maybe_load_json(corridor_shadow_pack_path)
    if not corridor_pack:
        corridor_pack = analyze_btst_candidate_pool_corridor_shadow_pack(REPORTS_DIR / "btst_candidate_pool_corridor_validation_pack_latest.json")

    rebucket_bundle = _maybe_load_json(rebucket_comparison_bundle_path)
    if not rebucket_bundle:
        rebucket_bundle = analyze_btst_candidate_pool_rebucket_comparison_bundle(REPORTS_DIR / "btst_candidate_pool_recall_dossier_latest.json")

    governance_synthesis = _maybe_load_json(governance_synthesis_path or DEFAULT_GOVERNANCE_SYNTHESIS_PATH)
    governance_overlays = _build_governance_overlays(governance_synthesis)
    primary = dict(corridor_pack.get("primary_shadow_replay") or {})
    parallel = [dict(row) for row in list(corridor_pack.get("parallel_watch_lanes") or [])]
    rebucket = dict(rebucket_bundle.get("rebucket_objective_row") or {})

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
            ticker=rebucket.get("ticker") or (list(rebucket.get("tickers") or [])[:1] or [None])[0],
            lane_family="rebucket",
            role="structural_challenger",
            mean_t_plus_2_return=rebucket.get("mean_t_plus_2_return"),
            objective_fit_score=rebucket.get("objective_fit_score"),
            t_plus_2_return_hit_rate_at_target=rebucket.get("t_plus_2_return_hit_rate_at_target"),
            t_plus_2_positive_rate=rebucket.get("t_plus_2_positive_rate"),
            tractability_tier=rebucket.get("prototype_readiness"),
            **governance_overlays.get(str((rebucket.get("ticker") or (list(rebucket.get("tickers") or [])[:1] or [None])[0]) or "").strip(), {}),
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

    pair_status = "ready_for_ranked_comparison" if candidates else "skipped_missing_candidates"
    board_leader = dict(candidates[0]) if candidates else {}

    comparison = {
        "corridor_primary_ticker": primary.get("ticker"),
        "corridor_primary_objective_fit_score": primary.get("objective_fit_score"),
        "corridor_primary_mean_t_plus_2_return": primary.get("mean_t_plus_2_return"),
        "rebucket_ticker": rebucket.get("ticker") or (list(rebucket.get("tickers") or [])[:1] or [None])[0],
        "rebucket_objective_fit_score": rebucket.get("objective_fit_score"),
        "rebucket_mean_t_plus_2_return": rebucket.get("mean_t_plus_2_return"),
        "alignment_status": rebucket_bundle.get("priority_alignment_status"),
        "governance_overlay_count": len(governance_overlays),
    }

    if board_leader.get("lane_family") == "corridor":
        recommendation = (
            f"lane pair board 当前仍应由 corridor 主导，首选 ticker={board_leader.get('ticker')}。"
            f" rebucket ticker={comparison.get('rebucket_ticker')} 保留为结构 challenger，用于并行收益对照。"
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
        f"保持 rebucket ticker {comparison.get('rebucket_ticker') or 'N/A'} 为结构 challenger，对照 corridor 主槽位表现。",
        "parallel_watch 只承担 confirmatory evidence，不允许直接替换 primary replay 优先级。",
    ]
    if governance_overlays.get("300720", {}).get("governance_status"):
        next_actions.append("300720 继续保持 continuation / observation-only，等待 selected persistence 或独立窗口 edge。")
    if governance_overlays.get("003036", {}).get("governance_status"):
        next_actions.append("003036 保持 profitability-cliff parallel watch，不把单窗口 near-miss uplift 当成默认 BTST 放行证据。")
    if governance_overlays.get("301292", {}).get("governance_status"):
        next_actions.append("301292 保持 shadow-recall diagnostics，不进入 execution lanes。")

    return {
        "corridor_shadow_pack_path": str(Path(corridor_shadow_pack_path).expanduser().resolve()),
        "rebucket_comparison_bundle_path": str(Path(rebucket_comparison_bundle_path).expanduser().resolve()),
        "governance_synthesis_path": str(Path(governance_synthesis_path or DEFAULT_GOVERNANCE_SYNTHESIS_PATH).expanduser().resolve()),
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
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_lane_pair_board(
        args.corridor_shadow_pack_path,
        args.rebucket_comparison_bundle_path,
        governance_synthesis_path=args.governance_synthesis_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_candidate_pool_lane_pair_board_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))
