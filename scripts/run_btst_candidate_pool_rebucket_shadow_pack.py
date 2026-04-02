from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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


def _select_rebucket_experiment(dossier: dict[str, Any], *, ticker: str | None = None) -> dict[str, Any]:
    queue = [
        dict(row)
        for row in list(dossier.get("priority_handoff_branch_experiment_queue") or [])
        if str(row.get("prototype_type") or "") == "post_gate_competition_rebucket_probe"
    ]
    if ticker:
        queue = [row for row in queue if ticker in list(row.get("tickers") or [])]
    if not queue:
        raise ValueError("No post_gate_competition_rebucket_probe experiment found in dossier")
    return dict(queue[0])


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
    lines.append("")
    lines.append("## Runbook")
    for item in list(pack.get("runbook") or []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {pack['recommendation']}")
    return "\n".join(lines) + "\n"


def run_btst_candidate_pool_rebucket_shadow_pack(
    dossier_path: str | Path,
    *,
    output_dir: str | Path,
    ticker: str | None = None,
) -> dict[str, Any]:
    dossier = _load_json(dossier_path)
    experiment = _select_rebucket_experiment(dossier, ticker=ticker)
    tickers = [str(value) for value in list(experiment.get("tickers") or []) if str(value or "").strip()]
    target_rows = _build_target_rows(dossier, tickers)
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    runbook = [
        "保持 MIN_AVG_AMOUNT_20D 不变，只观察 smaller-cap hot-peer rebucket 的影子效果。",
        "优先复核 top300_lower_market_cap_hot_peer_examples 是否持续重复出现，避免一次性噪声样本驱动结论。",
        "若 estimated_rank_gap_after_rebucket_mean 仍显著偏大，则回退为 competition-set evidence accumulation，不进入 gate-relief 讨论。",
    ]
    recommendation = (
        f"当前应先把 {','.join(tickers) or '目标票'} 作为 post-gate rebucket shadow target，"
        f"因为 {experiment.get('evaluation_summary') or ''}"
    )
    pack = {
        "source_dossier": str(Path(dossier_path).expanduser().resolve()),
        "experiment": experiment,
        "target_rows": target_rows,
        "runbook": runbook,
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
    args = parser.parse_args()

    pack = run_btst_candidate_pool_rebucket_shadow_pack(
        args.dossier_path,
        output_dir=args.output_dir,
        ticker=args.ticker,
    )
    print(json.dumps(pack, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()