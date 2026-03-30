from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from src.project_env import load_project_dotenv

load_project_dotenv()


def _resolve_trade_dates(raw_trade_dates: str) -> list[str]:
    trade_dates = [item.strip() for item in raw_trade_dates.split(",") if item.strip()]
    if not trade_dates:
        raise SystemExit("--trade-dates is required")
    return trade_dates


def _classify_score_b(score_b: float) -> str:
    if score_b > 0.50:
        return "strong_buy"
    if score_b >= 0.35:
        return "watch"
    if score_b >= -0.20:
        return "neutral"
    if score_b >= -0.50:
        return "sell"
    return "strong_sell"


def _resolve_blend_weights() -> tuple[float, float]:
    from src.execution.layer_c_aggregator import LAYER_C_BLEND_B_WEIGHT, LAYER_C_BLEND_C_WEIGHT

    b_weight = max(0.0, float(LAYER_C_BLEND_B_WEIGHT))
    c_weight = max(0.0, float(LAYER_C_BLEND_C_WEIGHT))
    total = b_weight + c_weight
    if total <= 0:
        return 0.55, 0.45
    return b_weight / total, c_weight / total


def _watchlist_score_threshold() -> float:
    from src.execution.daily_pipeline import WATCHLIST_SCORE_THRESHOLD

    return float(WATCHLIST_SCORE_THRESHOLD)


def _layer_c_avoid_score_c_threshold() -> float:
    from src.execution.layer_c_aggregator import LAYER_C_AVOID_SCORE_C_THRESHOLD

    return float(LAYER_C_AVOID_SCORE_C_THRESHOLD)


def _required_score_c(score_b: float, watchlist_threshold: float) -> float | None:
    blend_b_weight, blend_c_weight = _resolve_blend_weights()
    if blend_c_weight <= 0:
        return None
    return (watchlist_threshold - (blend_b_weight * score_b)) / blend_c_weight


def _would_enter_watchlist(score_final: float, decision: str) -> bool:
    return decision != "avoid" and score_final >= _watchlist_score_threshold()


def _compact_agents(entries: list[dict]) -> list[dict[str, object]]:
    compact: list[dict[str, object]] = []
    for item in entries[:3]:
        compact.append(
            {
                "agent_id": str(item.get("agent_id") or ""),
                "contribution": round(float(item.get("contribution", 0.0) or 0.0), 4),
                "direction": int(item.get("direction", 0) or 0),
                "confidence": round(float(item.get("confidence", 0.0) or 0.0), 2),
                "completeness": round(float(item.get("completeness", 0.0) or 0.0), 2),
            }
        )
    return compact


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = list(rows[0].keys()) if rows else [
        "trade_date",
        "ticker",
        "industry_sw",
        "tags",
        "variant_score_b",
        "required_score_c",
        "replay_score_c",
        "score_c_gap",
        "score_final",
        "decision",
        "bc_conflict",
        "would_enter_watchlist",
        "manual_verdict",
        "manual_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _render_markdown(payload: dict) -> str:
    summary = payload["summary"]
    lines = [
        f"# {payload['variant']} 新增样本 Layer C 承接对照",
        "",
        f"- trade_dates: {', '.join(payload['trade_dates'])}",
        f"- model: {payload['model']['model_provider']} / {payload['model']['model_name']}",
        f"- added_sample_count: {summary['added_sample_count']}",
        f"- would_enter_watchlist: {summary['would_enter_watchlist_count']}",
        f"- rejected_after_layer_c: {summary['rejected_after_layer_c_count']}",
        f"- avoid_conflicts: {summary['avoid_conflict_count']}",
        f"- watchlist_threshold: {payload['thresholds']['watchlist_score_threshold']:.4f}",
        f"- layer_c_blend: B={payload['thresholds']['layer_c_blend_b_weight']:.4f}, C={payload['thresholds']['layer_c_blend_c_weight']:.4f}",
        f"- layer_c_avoid_score_c_threshold: {payload['thresholds']['layer_c_avoid_score_c_threshold']:.4f}",
        "",
        "## 核心判断",
        "",
        "1. 先看新增样本里有多少能被 Layer C 真正承接进 watchlist。",
        "2. 再看被否决的样本是因为强 bearish 冲突，还是只是差一点点。",
        "3. 最后看哪些标签组合更容易被承接。",
        "",
        "## 汇总",
        "",
        f"- accepted_tag_counts: {json.dumps(summary['accepted_tag_counts'], ensure_ascii=False)}",
        f"- rejected_tag_counts: {json.dumps(summary['rejected_tag_counts'], ensure_ascii=False)}",
        f"- bc_conflict_counts: {json.dumps(summary['bc_conflict_counts'], ensure_ascii=False)}",
        f"- daily_status_counts: {json.dumps(summary['daily_status_counts'], ensure_ascii=False)}",
        "",
        "## 样本明细",
        "",
    ]

    if not payload["rows"]:
        lines.extend(["- 无新增样本", ""])
        return "\n".join(lines)

    for row in payload["rows"]:
        required_score_c_text = "n/a" if row["required_score_c"] is None else f"{float(row['required_score_c']):.4f}"
        score_c_gap_text = "n/a" if row["score_c_gap"] is None else f"{float(row['score_c_gap']):.4f}"
        lines.append(
            f"- {row['trade_date']} / {row['ticker']} | industry={row['industry_sw']} | tags={', '.join(row['tags'])} | "
            f"score_b={row['variant_score_b']:.4f} | score_c={row['replay_score_c']:.4f} | "
            f"required_c={required_score_c_text} | "
            f"gap={score_c_gap_text} | "
            f"final={row['score_final']:.4f} | decision={row['decision']} | watchlist={'yes' if row['would_enter_watchlist'] else 'no'}"
        )
        if row["bc_conflict"]:
            lines.append(f"  - bc_conflict: {row['bc_conflict']}")
        if row["top_positive_agents"]:
            lines.append(f"  - top_positive_agents: {json.dumps(row['top_positive_agents'], ensure_ascii=False)}")
        if row["top_negative_agents"]:
            lines.append(f"  - top_negative_agents: {json.dumps(row['top_negative_agents'], ensure_ascii=False)}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    from scripts.analyze_layer_b_rule_variants import VARIANTS, _build_comparison, _run_variant
    from scripts.model_selection import resolve_model_selection
    from src.backtesting.rule_variant_compare import make_pipeline_agent_runner
    from src.execution.layer_c_aggregator import aggregate_layer_c_results
    from src.screening.models import FusedScore
    from src.utils.analysts import ANALYST_ORDER

    parser = argparse.ArgumentParser(description="Replay Layer C carryover for samples newly added by a Layer B rule variant.")
    parser.add_argument("--trade-dates", required=True, help="Comma-separated trade dates like 20260323,20260324")
    parser.add_argument("--variant", required=True, help="Variant name from scripts/analyze_layer_b_rule_variants.py")
    parser.add_argument("--model-name", required=False, help="Model name override")
    parser.add_argument("--model-provider", required=False, help="Model provider override")
    parser.add_argument("--output-dir", default="", help="Optional output dir")
    args = parser.parse_args()

    if args.variant not in VARIANTS or args.variant == "baseline":
        raise SystemExit(f"Unsupported variant: {args.variant}")

    trade_dates = _resolve_trade_dates(args.trade_dates)
    baseline = _run_variant(trade_dates, {})
    variant = _run_variant(trade_dates, VARIANTS[args.variant])
    comparison = _build_comparison(args.variant, baseline, variant)

    resolved_model_name, resolved_model_provider = resolve_model_selection(args.model_name, args.model_provider)
    selected_analysts = [value for _, value in ANALYST_ORDER]
    agent_runner = make_pipeline_agent_runner(
        model_name=resolved_model_name,
        model_provider=resolved_model_provider,
        selected_analysts=selected_analysts,
    )

    added_by_date: dict[str, list[dict]] = {}
    for item in comparison["added_samples"]:
        added_by_date.setdefault(str(item["trade_date"]), []).append(item)

    rows: list[dict[str, object]] = []
    bc_conflict_counts: Counter[str] = Counter()
    accepted_tag_counts: Counter[str] = Counter()
    rejected_tag_counts: Counter[str] = Counter()
    daily_status_counts: dict[str, dict[str, int]] = {}

    for trade_date in sorted(added_by_date):
        samples = added_by_date[trade_date]
        tickers = [str(item["ticker"]) for item in samples]
        analyst_signals = agent_runner(tickers, trade_date, "fast") if tickers else {}
        fused_scores = [
            FusedScore(
                ticker=str(item["ticker"]),
                score_b=float(item["variant_score_b"]),
                strategy_signals={},
                arbitration_applied=list(item.get("variant_arbitration") or []),
                market_state=None,
                weights_used={},
                decision=_classify_score_b(float(item["variant_score_b"])),
            )
            for item in samples
        ]
        replay_results = aggregate_layer_c_results(fused_scores, analyst_signals)
        replay_by_ticker = {item.ticker: item for item in replay_results}

        accepted_count = 0
        rejected_count = 0
        for item in samples:
            ticker = str(item["ticker"])
            replay = replay_by_ticker.get(ticker)
            if replay is None:
                continue
            required_score_c = _required_score_c(float(item["variant_score_b"]), _watchlist_score_threshold())
            score_c_gap = None if required_score_c is None else round(float(replay.score_c) - float(required_score_c), 4)
            would_enter_watchlist = _would_enter_watchlist(float(replay.score_final), str(replay.decision))
            if replay.bc_conflict:
                bc_conflict_counts[str(replay.bc_conflict)] += 1
            if would_enter_watchlist:
                accepted_count += 1
                accepted_tag_counts.update(item["tags"])
            else:
                rejected_count += 1
                rejected_tag_counts.update(item["tags"])

            contribution_summary = dict(replay.agent_contribution_summary or {})
            rows.append(
                {
                    "trade_date": trade_date,
                    "ticker": ticker,
                    "industry_sw": item["industry_sw"],
                    "tags": list(item["tags"]),
                    "variant_score_b": round(float(item["variant_score_b"]), 4),
                    "baseline_score_b": round(float(item["baseline_score_b"]), 4),
                    "score_delta": round(float(item["score_delta"]), 4),
                    "required_score_c": round(float(required_score_c), 4) if required_score_c is not None else None,
                    "replay_score_c": round(float(replay.score_c), 4),
                    "score_c_gap": score_c_gap,
                    "score_final": round(float(replay.score_final), 4),
                    "decision": str(replay.decision),
                    "bc_conflict": replay.bc_conflict,
                    "would_enter_watchlist": would_enter_watchlist,
                    "top_positive_agents": _compact_agents(list(contribution_summary.get("top_positive_agents") or [])),
                    "top_negative_agents": _compact_agents(list(contribution_summary.get("top_negative_agents") or [])),
                    "cohort_contributions": dict(contribution_summary.get("cohort_contributions") or {}),
                    "manual_verdict": "",
                    "manual_notes": "",
                }
            )
        daily_status_counts[trade_date] = {"accepted": accepted_count, "rejected": rejected_count}

    rows.sort(key=lambda item: (str(item["trade_date"]), str(item["ticker"])))

    payload = {
        "variant": args.variant,
        "trade_dates": trade_dates,
        "model": {"model_name": resolved_model_name, "model_provider": resolved_model_provider},
        "thresholds": {
            "watchlist_score_threshold": round(_watchlist_score_threshold(), 4),
            "layer_c_blend_b_weight": round(_resolve_blend_weights()[0], 4),
            "layer_c_blend_c_weight": round(_resolve_blend_weights()[1], 4),
            "layer_c_avoid_score_c_threshold": round(_layer_c_avoid_score_c_threshold(), 4),
        },
        "summary": {
            "added_sample_count": len(rows),
            "would_enter_watchlist_count": sum(1 for row in rows if bool(row["would_enter_watchlist"])),
            "rejected_after_layer_c_count": sum(1 for row in rows if not bool(row["would_enter_watchlist"])),
            "avoid_conflict_count": sum(1 for row in rows if str(row["decision"]) == "avoid"),
            "bc_conflict_counts": dict(bc_conflict_counts),
            "accepted_tag_counts": dict(accepted_tag_counts),
            "rejected_tag_counts": dict(rejected_tag_counts),
            "daily_status_counts": daily_status_counts,
        },
        "rows": rows,
    }

    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser().resolve()
    else:
        output_dir = Path(__file__).resolve().parents[1] / "data" / "reports" / f"{args.variant}_layer_c_carryover_{trade_dates[0]}_{trade_dates[-1]}"
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_rows: list[dict[str, object]] = []
    for row in rows:
        csv_rows.append(
            {
                "trade_date": row["trade_date"],
                "ticker": row["ticker"],
                "industry_sw": row["industry_sw"],
                "tags": ";".join(row["tags"]),
                "variant_score_b": f"{float(row['variant_score_b']):.4f}",
                "required_score_c": "" if row["required_score_c"] is None else f"{float(row['required_score_c']):.4f}",
                "replay_score_c": f"{float(row['replay_score_c']):.4f}",
                "score_c_gap": "" if row["score_c_gap"] is None else f"{float(row['score_c_gap']):.4f}",
                "score_final": f"{float(row['score_final']):.4f}",
                "decision": row["decision"],
                "bc_conflict": row["bc_conflict"] or "",
                "would_enter_watchlist": "yes" if bool(row["would_enter_watchlist"]) else "no",
                "top_positive_agents": json.dumps(row["top_positive_agents"], ensure_ascii=False),
                "top_negative_agents": json.dumps(row["top_negative_agents"], ensure_ascii=False),
                "manual_verdict": "",
                "manual_notes": "",
            }
        )

    json_path = output_dir / "layer_c_carryover.json"
    csv_path = output_dir / "layer_c_carryover_ledger.csv"
    md_path = output_dir / "layer_c_carryover_review.md"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(csv_path, csv_rows)
    md_path.write_text(_render_markdown(payload), encoding="utf-8")

    summary = {
        "variant": args.variant,
        "trade_dates": trade_dates,
        "added_sample_count": payload["summary"]["added_sample_count"],
        "would_enter_watchlist_count": payload["summary"]["would_enter_watchlist_count"],
        "rejected_after_layer_c_count": payload["summary"]["rejected_after_layer_c_count"],
        "output_files": {
            "json": str(json_path),
            "csv": str(csv_path),
            "markdown": str(md_path),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()