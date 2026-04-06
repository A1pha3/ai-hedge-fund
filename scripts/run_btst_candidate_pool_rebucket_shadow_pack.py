from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REBUCKET_SHADOW_RELEASE_SCORE_MIN = 0.28
DEFAULT_UPSTREAM_HANDOFF_BOARD_PATH = Path("data/reports/btst_candidate_pool_upstream_handoff_board_latest.json")


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: dict[str, Any]) -> str:
    resolved = Path(path).expanduser().resolve()
    resolved.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(resolved)


def _write_markdown(path: str | Path, content: str) -> str:
    resolved = Path(path).expanduser().resolve()
    resolved.write_text(content, encoding="utf-8")
    return str(resolved)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _build_rebucket_commands(*, dossier_path: str | Path, ticker: str | None = None) -> list[str]:
    resolved_dossier_path = Path(dossier_path).expanduser().resolve()
    ticker_arg = f" --ticker {ticker}" if ticker else ""
    paper_trading_ticker_arg = f" --candidate-pool-shadow-rebucket-focus-tickers {ticker}" if ticker else ""
    release_score_arg = f" --upstream-shadow-release-post-gate-rebucket-score-min {REBUCKET_SHADOW_RELEASE_SCORE_MIN:.2f}"
    return [
        "python scripts/analyze_btst_candidate_pool_recall_dossier.py "
        "--tradeable-opportunity-pool data/reports/btst_tradeable_opportunity_pool_march.json "
        "--watchlist-recall-dossier data/reports/btst_watchlist_recall_dossier_latest.json "
        "--failure-dossier data/reports/btst_no_candidate_entry_failure_dossier_latest.json "
        "--output-json data/reports/btst_candidate_pool_recall_dossier_latest.json "
        "--output-md data/reports/btst_candidate_pool_recall_dossier_latest.md",
        "python scripts/run_btst_candidate_pool_rebucket_shadow_pack.py "
        f"--dossier-path {resolved_dossier_path}{ticker_arg} "
        "--output-dir data/reports",
        "python scripts/analyze_btst_candidate_pool_rebucket_objective_validation.py "
        f"--dossier-path {resolved_dossier_path} "
        "--objective-monitor-path data/reports/btst_tplus1_tplus2_objective_monitor_latest.json "
        "--lane-objective-support-path data/reports/btst_candidate_pool_lane_objective_support_latest.json"
        f"{ticker_arg} "
        "--output-json data/reports/btst_candidate_pool_rebucket_objective_validation_latest.json "
        "--output-md data/reports/btst_candidate_pool_rebucket_objective_validation_latest.md",
        "python scripts/run_btst_candidate_pool_rebucket_comparison_bundle.py "
        f"--dossier-path {resolved_dossier_path} "
        "--lane-objective-support-path data/reports/btst_candidate_pool_lane_objective_support_latest.json "
        "--branch-priority-board-path data/reports/btst_candidate_pool_branch_priority_board_latest.json "
        "--rebucket-shadow-pack-path data/reports/btst_candidate_pool_rebucket_shadow_pack_latest.json "
        "--rebucket-objective-validation-path data/reports/btst_candidate_pool_rebucket_objective_validation_latest.json "
        "--objective-monitor-path data/reports/btst_tplus1_tplus2_objective_monitor_latest.json "
        "--output-json data/reports/btst_candidate_pool_rebucket_comparison_bundle_latest.json "
        "--output-md data/reports/btst_candidate_pool_rebucket_comparison_bundle_latest.md",
        "python scripts/run_paper_trading.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD "
        "--selection-target short_trade_only --model-provider MiniMax --model-name MiniMax-M2.7"
        f"{paper_trading_ticker_arg}{release_score_arg}",
    ]


def _select_rebucket_experiment(dossier: dict[str, Any], *, ticker: str | None = None) -> dict[str, Any] | None:
    queue = [
        dict(row)
        for row in list(dossier.get("priority_handoff_branch_experiment_queue") or [])
        if str(row.get("prototype_type") or "") == "post_gate_competition_rebucket_probe"
    ]
    if ticker:
        queue = [row for row in queue if ticker in list(row.get("tickers") or [])]
    if not queue:
        return None
    return dict(queue[0])


def _build_skipped_rebucket_shadow_pack(*, dossier_path: str | Path) -> dict[str, Any]:
    return {
        "source_dossier": str(Path(dossier_path).expanduser().resolve()),
        "shadow_status": "skipped_no_rebucket_candidate",
        "recommended_release_score_min": REBUCKET_SHADOW_RELEASE_SCORE_MIN,
        "experiment": {},
        "target_rows": [],
        "runbook": [
            "继续刷新 candidate-pool recall dossier，等待 post_gate_competition_rebucket_probe 重新进入 experiment queue。",
            "在 rebucket 候选重新出现前，不要把旧的 latest rebucket pack 当成当前 active lane。",
            "当前应以最新 control tower / candidate-pool recall dossier 对 301292 的 active blocking stage 解释为准。",
        ],
        "run_commands": [],
        "recommendation": "candidate-pool recall dossier 当前没有 post_gate_competition_rebucket_probe 候选，因此 rebucket shadow pack 只保留为空位监控。",
    }


def _find_handoff_row(upstream_handoff_board: dict[str, Any], ticker: str) -> dict[str, Any]:
    normalized_ticker = str(ticker or "").strip()
    return next(
        (
            dict(row or {})
            for row in list(upstream_handoff_board.get("board_rows") or [])
            if str((row or {}).get("ticker") or "") == normalized_ticker
        ),
        {},
    )


def _build_persistence_only_pack(
    *,
    dossier_path: str | Path,
    experiment: dict[str, Any],
    target_rows: list[dict[str, Any]],
    handoff_row: dict[str, Any],
    ticker: str | None,
) -> dict[str, Any]:
    focus_ticker = ticker or ",".join(str(value) for value in list(experiment.get("tickers") or []) if str(value or "").strip())
    return {
        "source_dossier": str(Path(dossier_path).expanduser().resolve()),
        "shadow_status": "persistence_diagnostics_only",
        "experiment": experiment,
        "recommended_release_score_min": REBUCKET_SHADOW_RELEASE_SCORE_MIN,
        "target_rows": target_rows,
        "handoff_context": handoff_row,
        "runbook": [
            "不要把单次 rebucket shadow 命中误当成 active replay lane；先确认该票是否能跨独立报告持续再出现。",
            "优先比较 historical shadow probe 与最新 active followup 的可见性差异，定位是 cooldown、召回入口还是下游 score cliff 导致留存失败。",
            "在 persistence 没确认前，不要继续增加真实 replay 频次，也不要讨论放宽默认 gate。",
        ],
        "run_commands": [
            "python scripts/run_btst_candidate_pool_upstream_handoff_board.py "
            "--failure-dossier-path data/reports/btst_no_candidate_entry_failure_dossier_latest.json "
            "--watchlist-recall-dossier-path data/reports/btst_watchlist_recall_dossier_latest.json "
            "--candidate-pool-recall-dossier-path data/reports/btst_candidate_pool_recall_dossier_latest.json "
            "--output-json data/reports/btst_candidate_pool_upstream_handoff_board_latest.json "
            "--output-md data/reports/btst_candidate_pool_upstream_handoff_board_latest.md",
            "python scripts/run_btst_candidate_pool_rebucket_shadow_pack.py "
            f"--dossier-path {Path(dossier_path).expanduser().resolve()} --ticker {focus_ticker} "
            "--upstream-handoff-board-path data/reports/btst_candidate_pool_upstream_handoff_board_latest.json --output-dir data/reports",
        ],
        "recommendation": (
            f"{focus_ticker or '目标票'} 当前只具备 historical shadow probe 证据，"
            "应先做 persistence diagnostics，而不是继续当成 ready-for-replay 的 rebucket lane。"
        ),
    }


def _resolve_upstream_handoff_board_path(dossier_path: str | Path, upstream_handoff_board_path: str | Path | None) -> Path | None:
    if upstream_handoff_board_path:
        resolved = Path(upstream_handoff_board_path).expanduser().resolve()
        return resolved if resolved.exists() else None
    sibling_path = Path(dossier_path).expanduser().resolve().parent / DEFAULT_UPSTREAM_HANDOFF_BOARD_PATH.name
    if sibling_path.exists():
        return sibling_path
    default_path = DEFAULT_UPSTREAM_HANDOFF_BOARD_PATH.expanduser().resolve()
    if default_path.exists() and sibling_path.parent == default_path.parent:
        return default_path
    return None


def _build_target_rows(dossier: dict[str, Any], tickers: list[str]) -> list[dict[str, Any]]:
    dossier_by_ticker = {str(row.get("ticker") or ""): dict(row) for row in list(dossier.get("priority_ticker_dossiers") or [])}
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        target_dossier = dossier_by_ticker.get(ticker) or {}
        occurrences = [
            dict(row)
            for row in list(target_dossier.get("occurrence_evidence") or [])
            if str(row.get("blocking_stage") or "") == "candidate_pool_truncated_after_filters"
        ]
        uplift_values = [
            round(1.0 / float(value), 4)
            for value in [row.get("pre_truncation_avg_amount_share_of_cutoff") for row in occurrences]
            if isinstance(value, (int, float)) and float(value) > 0
        ]
        lower_cap_counts = [float(row.get("top300_lower_market_cap_hot_peer_count")) for row in occurrences if isinstance(row.get("top300_lower_market_cap_hot_peer_count"), (int, float))]
        rebucket_gaps = [float(row.get("estimated_rank_gap_after_rebucket")) for row in occurrences if isinstance(row.get("estimated_rank_gap_after_rebucket"), (int, float))]
        hot_peer_examples: list[str] = []
        for occurrence in occurrences:
            for peer in list(occurrence.get("top300_lower_market_cap_hot_peer_examples") or []):
                label = str(peer or "").strip()
                if label and label not in hot_peer_examples:
                    hot_peer_examples.append(label)
                if len(hot_peer_examples) >= 5:
                    break
            if len(hot_peer_examples) >= 5:
                break
        rows.append(
            {
                "ticker": ticker,
                "occurrence_count": len(occurrences),
                "uplift_to_cutoff_multiple_mean": _mean(uplift_values),
                "top300_lower_market_cap_hot_peer_count_mean": _mean(lower_cap_counts),
                "estimated_rank_gap_after_rebucket_mean": _mean(rebucket_gaps),
                "top300_lower_market_cap_hot_peer_examples": hot_peer_examples,
                "failure_reason": target_dossier.get("failure_reason"),
                "next_step": target_dossier.get("next_step"),
            }
        )
    return rows


def render_btst_candidate_pool_rebucket_shadow_pack_markdown(pack: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Candidate Pool Rebucket Shadow Pack")
    lines.append("")
    lines.append("## Status")
    lines.append(f"- shadow_status: {pack.get('shadow_status')}")
    lines.append("")
    lines.append("## Experiment")
    lines.append(f"- task_id: {pack['experiment'].get('task_id')}")
    lines.append(f"- priority_handoff: {pack['experiment'].get('priority_handoff')}")
    lines.append(f"- prototype_readiness: {pack['experiment'].get('prototype_readiness')}")
    lines.append(f"- tickers: {pack['experiment'].get('tickers')}")
    lines.append(f"- evaluation_summary: {pack['experiment'].get('evaluation_summary')}")
    lines.append(f"- guardrail_summary: {pack['experiment'].get('guardrail_summary')}")
    lines.append("")
    lines.append("## Target Rows")
    for row in list(pack.get("target_rows") or []):
        lines.append(
            f"- ticker={row['ticker']} occurrence_count={row['occurrence_count']} uplift_to_cutoff_multiple_mean={row.get('uplift_to_cutoff_multiple_mean')} lower_cap_hot_peer_count_mean={row.get('top300_lower_market_cap_hot_peer_count_mean')} estimated_rank_gap_after_rebucket_mean={row.get('estimated_rank_gap_after_rebucket_mean')}"
        )
        lines.append(f"  top300_lower_market_cap_hot_peer_examples: {row.get('top300_lower_market_cap_hot_peer_examples')}")
        lines.append(f"  next_step: {row.get('next_step')}")
    if not list(pack.get("target_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Runbook")
    for item in list(pack.get("runbook") or []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Commands")
    for item in list(pack.get("run_commands") or []):
        lines.append(f"- {item}")
    if not list(pack.get("run_commands") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {pack['recommendation']}")
    return "\n".join(lines) + "\n"


def run_btst_candidate_pool_rebucket_shadow_pack(
    dossier_path: str | Path,
    *,
    output_dir: str | Path,
    ticker: str | None = None,
    upstream_handoff_board_path: str | Path | None = None,
) -> dict[str, Any]:
    dossier = _load_json(dossier_path)
    experiment = _select_rebucket_experiment(dossier, ticker=ticker)
    resolved_upstream_handoff_board_path = _resolve_upstream_handoff_board_path(dossier_path, upstream_handoff_board_path)
    upstream_handoff_board = _load_json(resolved_upstream_handoff_board_path) if resolved_upstream_handoff_board_path else {}
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    if experiment is None:
        pack = _build_skipped_rebucket_shadow_pack(dossier_path=dossier_path)
        json_path = _write_json(output_root / "btst_candidate_pool_rebucket_shadow_pack_latest.json", pack)
        md_path = _write_markdown(output_root / "btst_candidate_pool_rebucket_shadow_pack_latest.md", render_btst_candidate_pool_rebucket_shadow_pack_markdown(pack))
        pack["artifacts"] = {"json_path": json_path, "markdown_path": md_path}
        _write_json(Path(json_path), pack)
        _write_markdown(Path(md_path), render_btst_candidate_pool_rebucket_shadow_pack_markdown(pack))
        return pack

    tickers = [str(value) for value in list(experiment.get("tickers") or []) if str(value or "").strip()]
    target_rows = _build_target_rows(dossier, tickers)
    focus_handoff_row = _find_handoff_row(upstream_handoff_board, ticker or (tickers[0] if tickers else ""))
    if str(focus_handoff_row.get("downstream_followup_status") or "") == "transient_probe_only":
        pack = _build_persistence_only_pack(
            dossier_path=dossier_path,
            experiment=experiment,
            target_rows=target_rows,
            handoff_row=focus_handoff_row,
            ticker=ticker or (tickers[0] if tickers else None),
        )
        json_path = _write_json(output_root / "btst_candidate_pool_rebucket_shadow_pack_latest.json", pack)
        md_path = _write_markdown(output_root / "btst_candidate_pool_rebucket_shadow_pack_latest.md", render_btst_candidate_pool_rebucket_shadow_pack_markdown(pack))
        pack["artifacts"] = {"json_path": json_path, "markdown_path": md_path}
        _write_json(Path(json_path), pack)
        _write_markdown(Path(md_path), render_btst_candidate_pool_rebucket_shadow_pack_markdown(pack))
        return pack

    runbook = [
        "保持 MIN_AVG_AMOUNT_20D 不变，只观察 smaller-cap hot-peer rebucket 的影子效果。",
        f"将 post-gate shadow release score floor 固定为 {REBUCKET_SHADOW_RELEASE_SCORE_MIN:.2f}，避免 probe 被默认 release 阈值误挡。",
        "优先复核 top300_lower_market_cap_hot_peer_examples 是否持续重复出现，避免一次性噪声样本驱动结论。",
        "若 estimated_rank_gap_after_rebucket_mean 仍显著偏大，则回退为 competition-set evidence accumulation，不进入 gate-relief 讨论。",
    ]
    recommendation = (
        f"当前应先把 {','.join(tickers) or '目标票'} 作为 post-gate rebucket shadow target，"
        f"因为 {experiment.get('evaluation_summary') or ''}"
    )
    run_commands = _build_rebucket_commands(dossier_path=dossier_path, ticker=ticker or (tickers[0] if tickers else None))
    pack = {
        "source_dossier": str(Path(dossier_path).expanduser().resolve()),
        "shadow_status": "ready_for_rebucket_shadow_replay",
        "experiment": experiment,
        "recommended_release_score_min": REBUCKET_SHADOW_RELEASE_SCORE_MIN,
        "target_rows": target_rows,
        "runbook": runbook,
        "run_commands": run_commands,
        "recommendation": recommendation,
    }
    json_path = _write_json(output_root / "btst_candidate_pool_rebucket_shadow_pack_latest.json", pack)
    md_path = _write_markdown(output_root / "btst_candidate_pool_rebucket_shadow_pack_latest.md", render_btst_candidate_pool_rebucket_shadow_pack_markdown(pack))
    pack["artifacts"] = {"json_path": json_path, "markdown_path": md_path}
    _write_json(Path(json_path), pack)
    _write_markdown(Path(md_path), render_btst_candidate_pool_rebucket_shadow_pack_markdown(pack))
    return pack


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an executable shadow pack for the BTST candidate-pool post-gate rebucket lane.")
    parser.add_argument("--dossier-path", default="data/reports/btst_candidate_pool_recall_dossier_latest.json")
    parser.add_argument("--output-dir", default="data/reports")
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--upstream-handoff-board-path", default=str(DEFAULT_UPSTREAM_HANDOFF_BOARD_PATH))
    args = parser.parse_args()

    pack = run_btst_candidate_pool_rebucket_shadow_pack(
        args.dossier_path,
        output_dir=args.output_dir,
        ticker=args.ticker,
        upstream_handoff_board_path=args.upstream_handoff_board_path,
    )
    print(json.dumps(pack, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
