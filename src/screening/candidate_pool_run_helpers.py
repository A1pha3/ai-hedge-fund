from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from src.screening.models import CandidateStock


def build_candidate_pool_with_shadow(
    *,
    trade_date: str,
    use_cache: bool,
    cooldown_tickers: set[str] | None,
    snapshot_path: Path,
    legacy_snapshot_path: Path,
    shadow_snapshot_path: Path,
    max_candidate_pool_size: int,
    shadow_focus_signature_fn: Callable[[], str],
    load_candidate_pool_shadow_snapshot_fn: Callable[[Path], dict[str, Any]],
    write_candidate_pool_snapshot_fn: Callable[[Path, list["CandidateStock"]], None],
    load_candidate_pool_snapshot_fn: Callable[[Path], list["CandidateStock"]],
    build_shadow_summary_from_selected_candidates_fn: Callable[..., dict[str, Any]],
    write_candidate_pool_shadow_snapshot_fn: Callable[..., None],
    compute_candidate_pool_candidates_fn: Callable[..., tuple[list["CandidateStock"], list["CandidateStock"], list[dict[str, Any]]]],
    build_shadow_candidate_pool_payload_fn: Callable[..., tuple[list["CandidateStock"], list["CandidateStock"], dict[str, Any]]],
    finalize_focus_filter_diagnostics_fn: Callable[..., list[dict[str, Any]]],
) -> tuple[list["CandidateStock"], list["CandidateStock"], dict[str, Any]]:
    cached_selected_candidates: list[CandidateStock] = []
    focus_signature = shadow_focus_signature_fn()
    focus_label = f", focus={focus_signature}" if focus_signature else ""

    if use_cache and snapshot_path.exists() and shadow_snapshot_path.exists():
        try:
            shadow_payload = load_candidate_pool_shadow_snapshot_fn(shadow_snapshot_path)
            write_candidate_pool_snapshot_fn(legacy_snapshot_path, shadow_payload["selected_candidates"])
            print(
                f"[CandidatePool] 从缓存加载 {len(shadow_payload['selected_candidates'])} 只候选标的 + {len(shadow_payload['shadow_candidates'])} 只 shadow 标的 ({trade_date}, top{max_candidate_pool_size}{focus_label})"
            )
            return shadow_payload["selected_candidates"], shadow_payload["shadow_candidates"], shadow_payload["shadow_summary"]
        except Exception as e:
            print(f"[CandidatePool] shadow 缓存读取失败，重新计算: {e}")
    elif use_cache and snapshot_path.exists():
        print(f"[CandidatePool] 发现仅主池缓存 {snapshot_path.name}，补算 shadow recall 快照{focus_label}")
        try:
            cached_selected_candidates = load_candidate_pool_snapshot_fn(snapshot_path)
            if cached_selected_candidates and not focus_signature:
                shadow_summary = build_shadow_summary_from_selected_candidates_fn(
                    cached_selected_candidates,
                    pool_size=max_candidate_pool_size,
                )
                write_candidate_pool_shadow_snapshot_fn(
                    shadow_snapshot_path,
                    selected_candidates=cached_selected_candidates,
                    shadow_candidates=[],
                    shadow_summary=shadow_summary,
                )
                write_candidate_pool_snapshot_fn(legacy_snapshot_path, cached_selected_candidates)
                print(
                    f"[CandidatePool] 使用已有主池缓存直接回填空 shadow 快照 ({trade_date}, top{max_candidate_pool_size})"
                )
                return cached_selected_candidates, [], shadow_summary
        except Exception as e:
            print(f"[CandidatePool] 主池缓存读取失败，无法作为 shadow 补算回退: {e}")

    candidates, cooldown_review_candidates, focus_filter_diagnostics = compute_candidate_pool_candidates_fn(
        trade_date,
        cooldown_tickers=cooldown_tickers,
    )
    if not candidates and cached_selected_candidates:
        shadow_summary = build_shadow_summary_from_selected_candidates_fn(
            cached_selected_candidates,
            pool_size=max_candidate_pool_size,
        )
        shadow_summary["shadow_recall_status"] = "selected_cache_fallback_after_recompute_failure"
        write_candidate_pool_shadow_snapshot_fn(
            shadow_snapshot_path,
            selected_candidates=cached_selected_candidates,
            shadow_candidates=[],
            shadow_summary=shadow_summary,
        )
        write_candidate_pool_snapshot_fn(legacy_snapshot_path, cached_selected_candidates)
        print(
            f"[CandidatePool] 候选池重算失败，保留已有主池缓存并回填空 shadow 快照 ({trade_date}, top{max_candidate_pool_size})"
        )
        return cached_selected_candidates, [], shadow_summary

    selected_candidates, shadow_candidates, shadow_summary = build_shadow_candidate_pool_payload_fn(
        candidates,
        pool_size=max_candidate_pool_size,
        cooldown_review_candidates=cooldown_review_candidates,
        focus_filter_diagnostics=focus_filter_diagnostics,
    )
    shadow_summary["focus_filter_diagnostics"] = finalize_focus_filter_diagnostics_fn(
        {item["ticker"]: item for item in focus_filter_diagnostics},
        candidate_tickers={candidate.ticker for candidate in candidates},
        cooldown_review_tickers={candidate.ticker for candidate in cooldown_review_candidates},
        selected_tickers={candidate.ticker for candidate in selected_candidates},
        shadow_tickers={candidate.ticker for candidate in shadow_candidates},
    )

    write_candidate_pool_snapshot_fn(snapshot_path, selected_candidates)
    write_candidate_pool_snapshot_fn(legacy_snapshot_path, selected_candidates)
    write_candidate_pool_shadow_snapshot_fn(
        shadow_snapshot_path,
        selected_candidates=selected_candidates,
        shadow_candidates=shadow_candidates,
        shadow_summary=shadow_summary,
    )

    if len(candidates) > max_candidate_pool_size:
        print(f"[CandidatePool] 候选池截断至 Top {max_candidate_pool_size}（按20日均成交额/市值排序）")
    if shadow_candidates:
        print(
            f"[CandidatePool] shadow recall 标的: {len(shadow_candidates)} 只 ({shadow_summary.get('lane_counts')})"
        )
    print(f"[CandidatePool] 最终候选池: {len(selected_candidates)} 只 → {snapshot_path}")
    return selected_candidates, shadow_candidates, shadow_summary
