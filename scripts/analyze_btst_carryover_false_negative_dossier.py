from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

from scripts.btst_analysis_utils import extract_btst_price_outcome


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_carryover_false_negative_dossier_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_carryover_false_negative_dossier_latest.md"
RELIEF_REASON = "catalyst_theme_short_trade_carryover"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _summarize(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(mean(values), 4),
    }


def _build_row(snapshot_path: Path, ticker: str, payload: dict[str, Any], price_cache: dict[tuple[str, str], Any]) -> dict[str, Any] | None:
    short_trade = dict((payload or {}).get("short_trade") or {})
    if not short_trade:
        return None
    explainability = dict(short_trade.get("explainability_payload") or {})
    replay_context = dict(explainability.get("replay_context") or {})
    historical_prior = dict(explainability.get("historical_prior") or replay_context.get("historical_prior") or {})
    upstream_relief = dict(explainability.get("upstream_shadow_catalyst_relief") or {})
    short_trade_relief = dict(replay_context.get("short_trade_catalyst_relief") or {})
    candidate_reason_codes = [str(code) for code in list(replay_context.get("candidate_reason_codes") or []) if str(code or "").strip()]
    relief_reason = str(upstream_relief.get("reason") or short_trade_relief.get("reason") or "").strip()

    if relief_reason != RELIEF_REASON and "catalyst_theme_short_trade_carryover_candidate" not in candidate_reason_codes:
        return None
    if str(short_trade.get("decision") or "") == "selected":
        return None
    if str(historical_prior.get("execution_quality_label") or "") != "close_continuation":
        return None
    if str(historical_prior.get("entry_timing_bias") or "") != "confirm_then_hold":
        return None

    trade_date = str(snapshot_path.parent.name)
    metrics_payload = dict(short_trade.get("metrics_payload") or {})
    outcome = extract_btst_price_outcome(str(ticker), trade_date, price_cache)
    return {
        "trade_date": trade_date,
        "ticker": str(ticker),
        "report_dir": str(snapshot_path.parents[2]),
        "snapshot_path": str(snapshot_path),
        "decision": str(short_trade.get("decision") or ""),
        "candidate_source": str(short_trade.get("candidate_source") or ""),
        "preferred_entry_mode": str(short_trade.get("preferred_entry_mode") or ""),
        "score_target": round(_safe_float(short_trade.get("score_target")), 4),
        "relief_applied": bool(upstream_relief.get("applied")),
        "historical_sample_count": int(historical_prior.get("sample_count") or 0),
        "historical_evaluable_count": int(historical_prior.get("evaluable_count") or 0),
        "historical_next_close_positive_rate": historical_prior.get("next_close_positive_rate"),
        "historical_next_open_to_close_return_mean": historical_prior.get("next_open_to_close_return_mean"),
        "stale_trend_repair_penalty": round(_safe_float(metrics_payload.get("stale_trend_repair_penalty")), 4),
        "extension_without_room_penalty": round(_safe_float(metrics_payload.get("extension_without_room_penalty")), 4),
        "overhead_supply_penalty": round(_safe_float(metrics_payload.get("overhead_supply_penalty")), 4),
        "top_reasons": [str(reason) for reason in list(short_trade.get("top_reasons") or []) if str(reason or "").strip()],
        **outcome,
    }


def _deduplicate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("trade_date") or ""), str(row.get("ticker") or ""))
        current = deduplicated.get(key)
        if current is None:
            deduplicated[key] = row
            continue
        rank = (
            1 if str(row.get("decision") or "") == "near_miss" else 0,
            1 if row.get("relief_applied") else 0,
            float(row.get("score_target") or 0.0),
            str(row.get("report_dir") or ""),
        )
        current_rank = (
            1 if str(current.get("decision") or "") == "near_miss" else 0,
            1 if current.get("relief_applied") else 0,
            float(current.get("score_target") or 0.0),
            str(current.get("report_dir") or ""),
        )
        if rank > current_rank:
            deduplicated[key] = row
    return sorted(deduplicated.values(), key=lambda row: (str(row.get("trade_date") or ""), str(row.get("ticker") or "")))


def analyze_btst_carryover_false_negative_dossier(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    price_cache: dict[tuple[str, str], Any] = {}
    rows: list[dict[str, Any]] = []
    for snapshot_path in sorted(resolved_reports_root.glob("**/selection_artifacts/*/selection_snapshot.json")):
        snapshot = _load_json(snapshot_path)
        for ticker, payload in dict(snapshot.get("selection_targets") or {}).items():
            row = _build_row(snapshot_path, str(ticker), dict(payload or {}), price_cache)
            if row is not None:
                rows.append(row)

    rows = _deduplicate_rows(rows)
    top_reason_counts = Counter(reason for row in rows for reason in list(row.get("top_reasons") or []))
    next_close_values = [float(row["next_close_return"]) for row in rows if row.get("next_close_return") is not None]
    t_plus_2_values = [float(row["t_plus_2_close_return"]) for row in rows if row.get("t_plus_2_close_return") is not None]
    stale_penalties = [float(row["stale_trend_repair_penalty"]) for row in rows if row.get("stale_trend_repair_penalty") is not None]
    extension_penalties = [float(row["extension_without_room_penalty"]) for row in rows if row.get("extension_without_room_penalty") is not None]

    recommendation = "当前没有 strong carryover false negative 样本。"
    if rows:
        lead_row = rows[0]
        lead_reason = str(lead_row.get("top_reasons")[2] if len(lead_row.get("top_reasons") or []) >= 3 else "")
        if next_close_values and max(next_close_values) <= 0:
            recommendation = (
                "当前 strong carryover false negatives 的已闭环样本没有兑现次日正收益，"
                "说明现阶段更像是 penalty 在保护胜率，而不是错杀该放行的票。"
            )
        else:
            recommendation = (
                f"当前 strong carryover false negatives 的主导 penalty 为 {lead_reason or 'unknown'}，"
                "且至少有一部分已闭环样本兑现为正收益，可考虑继续做更窄的 targeted replay。"
            )

    return {
        "reports_root": str(resolved_reports_root),
        "false_negative_count": len(rows),
        "decision_counts": dict(Counter(str(row.get("decision") or "") for row in rows)),
        "top_reason_counts": dict(top_reason_counts.most_common()),
        "next_close_return_summary": _summarize(next_close_values),
        "t_plus_2_close_return_summary": _summarize(t_plus_2_values),
        "stale_trend_repair_penalty_summary": _summarize(stale_penalties),
        "extension_without_room_penalty_summary": _summarize(extension_penalties),
        "rows": rows,
        "recommendation": recommendation,
    }


def render_btst_carryover_false_negative_dossier_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Carryover False Negative Dossier")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- false_negative_count: {analysis.get('false_negative_count')}")
    lines.append(f"- decision_counts: {analysis.get('decision_counts')}")
    lines.append(f"- top_reason_counts: {analysis.get('top_reason_counts')}")
    lines.append("")
    lines.append("## Outcome Summary")
    lines.append(f"- next_close_return_summary: {analysis.get('next_close_return_summary')}")
    lines.append(f"- t_plus_2_close_return_summary: {analysis.get('t_plus_2_close_return_summary')}")
    lines.append(f"- stale_trend_repair_penalty_summary: {analysis.get('stale_trend_repair_penalty_summary')}")
    lines.append(f"- extension_without_room_penalty_summary: {analysis.get('extension_without_room_penalty_summary')}")
    lines.append("")
    lines.append("## Rows")
    for row in list(analysis.get("rows") or []):
        lines.append(
            f"- {row.get('trade_date')} {row.get('ticker')}: decision={row.get('decision')}, score_target={row.get('score_target')}, stale_penalty={row.get('stale_trend_repair_penalty')}, extension_penalty={row.get('extension_without_room_penalty')}, next_close_return={row.get('next_close_return')}, t_plus_2_close_return={row.get('t_plus_2_close_return')}, top_reasons={row.get('top_reasons')}"
        )
    if not list(analysis.get("rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit strong carryover false negatives and their realized outcomes.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_carryover_false_negative_dossier(args.reports_root)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_carryover_false_negative_dossier_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
