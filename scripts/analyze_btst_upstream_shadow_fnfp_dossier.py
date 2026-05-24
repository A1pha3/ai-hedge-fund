from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.analyze_short_trade_blockers import collect_short_trade_rows
from scripts.btst_analysis_utils import extract_btst_price_outcome

REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_upstream_shadow_fnfp_dossier_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_upstream_shadow_fnfp_dossier_latest.md"
UPSTREAM_SHADOW_SOURCE = "upstream_liquidity_corridor_shadow"


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_upstream_shadow_row(row: dict[str, Any]) -> bool:
    return str(row.get("candidate_source") or "") == UPSTREAM_SHADOW_SOURCE


def _trend_acceleration_band(value: Any) -> str:
    metric = _safe_float(value)
    if metric is None:
        return "unknown"
    if metric >= 0.8:
        return "gte_0_80"
    if metric >= 0.6:
        return "gte_0_60_lt_0_80"
    return "lt_0_60"


def _close_strength_band(value: Any) -> str:
    metric = _safe_float(value)
    if metric is None:
        return "unknown"
    if metric >= 0.85:
        return "gte_0_85"
    if metric >= 0.6:
        return "gte_0_60_lt_0_85"
    return "lt_0_60"


def _build_band_split(rows: list[dict[str, Any]], metric_key: str, band_fn: Any) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        band = band_fn(row.get(metric_key))
        grouped.setdefault(band, []).append(row)
    return {
        band: {
            "count": len(group_rows),
            "tickers": sorted({str(group_row.get("ticker") or "") for group_row in group_rows if str(group_row.get("ticker") or "")}),
        }
        for band, group_rows in sorted(grouped.items())
    }


def _build_repeat_ticker_board(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ticker_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "")
        if not ticker:
            continue
        ticker_groups.setdefault(ticker, []).append(row)

    repeat_rows: list[dict[str, Any]] = []
    for ticker, group_rows in ticker_groups.items():
        if len(group_rows) < 2:
            continue
        repeat_rows.append(
            {
                "ticker": ticker,
                "count": len(group_rows),
                "false_negative_count": sum(1 for row in group_rows if _classify_upstream_shadow_row(row) == "false_negative"),
                "false_positive_count": sum(1 for row in group_rows if _classify_upstream_shadow_row(row) == "false_positive"),
            }
        )
    repeat_rows.sort(key=lambda row: (int(row.get("count") or 0), int(row.get("false_negative_count") or 0), str(row.get("ticker") or "")), reverse=True)
    return repeat_rows


def _build_blocker_clusters(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocker_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for blocker in list(row.get("blockers") or []):
            blocker_name = str(blocker or "").strip()
            if not blocker_name:
                continue
            blocker_groups.setdefault(blocker_name, []).append(row)

    blocker_rows: list[dict[str, Any]] = []
    for blocker, group_rows in blocker_groups.items():
        blocker_rows.append(
            {
                "blocker": blocker,
                "count": len(group_rows),
                "false_negative_count": sum(1 for row in group_rows if _classify_upstream_shadow_row(row) == "false_negative"),
                "false_positive_count": sum(1 for row in group_rows if _classify_upstream_shadow_row(row) == "false_positive"),
            }
        )
    blocker_rows.sort(key=lambda row: (-int(row.get("count") or 0), str(row.get("blocker") or "")))
    return blocker_rows


def _rank_false_negative_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            _safe_float(row.get("t_plus_2_close_return"), -999.0),
            _safe_float(row.get("next_close_return"), -999.0),
            _safe_float(row.get("score_target"), -999.0),
            str(row.get("trade_date") or ""),
            str(row.get("ticker") or ""),
        ),
        reverse=True,
    )


def _rank_false_positive_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            _safe_float(row.get("t_plus_2_close_return"), 999.0),
            _safe_float(row.get("next_close_return"), 999.0),
            -(_safe_float(row.get("score_target"), 0.0) or 0.0),
            str(row.get("trade_date") or ""),
            str(row.get("ticker") or ""),
        ),
    )


def _build_upstream_shadow_row(row: dict[str, Any], price_cache: dict[tuple[str, str], Any]) -> dict[str, Any]:
    short_trade = dict(row.get("short_trade") or {})
    metrics_payload = dict(short_trade.get("metrics_payload") or {})
    historical_prior = dict(short_trade.get("historical_prior") or {})
    outcome = extract_btst_price_outcome(str(row.get("ticker") or ""), str(row.get("trade_date") or ""), price_cache)
    score_target = _safe_float(short_trade.get("score_target"), 0.0) or 0.0
    return {
        "trade_date": str(row.get("trade_date") or ""),
        "ticker": str(row.get("ticker") or ""),
        "candidate_source": str(row.get("candidate_source") or ""),
        "decision": str(short_trade.get("decision") or ""),
        "score_target": round(score_target, 4),
        "gap_to_select": round(0.58 - score_target, 4),
        "gap_to_near_miss": round(0.46 - score_target, 4),
        "blockers": [str(blocker) for blocker in list(short_trade.get("blockers") or []) if str(blocker or "").strip()],
        "top_reasons": [str(reason) for reason in list(short_trade.get("top_reasons") or []) if str(reason or "").strip()],
        "historical_execution_quality_label": str(historical_prior.get("execution_quality_label") or "unknown"),
        "historical_evaluable_count": int(historical_prior.get("evaluable_count") or 0),
        "historical_next_close_positive_rate": historical_prior.get("next_close_positive_rate"),
        "trend_acceleration": metrics_payload.get("trend_acceleration"),
        "close_strength": metrics_payload.get("close_strength"),
        **outcome,
    }


def _classify_upstream_shadow_row(row: dict[str, Any]) -> str | None:
    decision = str(row.get("decision") or "")
    next_close_return = _safe_float(row.get("next_close_return"))
    t_plus_2_close_return = _safe_float(row.get("t_plus_2_close_return"))
    quality_label = str(row.get("historical_execution_quality_label") or "unknown")
    has_clearly_positive_follow_through = (t_plus_2_close_return is not None and t_plus_2_close_return >= 0.05) or (next_close_return is not None and next_close_return >= 0.03)
    has_weak_or_poor_follow_through = (next_close_return is None or next_close_return < 0.03) and (t_plus_2_close_return is None or t_plus_2_close_return < 0.05)

    if decision != "selected" and has_clearly_positive_follow_through:
        return "false_negative"
    if decision in {"selected", "near_miss"} and (
        ((next_close_return is not None and next_close_return <= 0.0) and (t_plus_2_close_return is None or t_plus_2_close_return <= 0.0))
        or (quality_label == "balanced_confirmation" and has_weak_or_poor_follow_through and not has_clearly_positive_follow_through)
    ):
        return "false_positive"
    return None


def analyze_btst_upstream_shadow_fnfp_dossier(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    price_cache: dict[tuple[str, str], Any] = {}
    cohort_rows: list[dict[str, Any]] = []
    for selection_root in sorted(resolved_reports_root.glob("**/selection_artifacts")):
        for row in collect_short_trade_rows(selection_root.parent):
            if not _is_upstream_shadow_row(dict(row)):
                continue
            cohort_rows.append(_build_upstream_shadow_row(dict(row), price_cache))

    false_negative_rows = _rank_false_negative_rows([row for row in cohort_rows if _classify_upstream_shadow_row(row) == "false_negative"])
    false_positive_rows = _rank_false_positive_rows([row for row in cohort_rows if _classify_upstream_shadow_row(row) == "false_positive"])
    quality_label_split = dict(Counter(str(row.get("historical_execution_quality_label") or "unknown") for row in cohort_rows))

    return {
        "reports_root": str(resolved_reports_root),
        "cohort_count": len(cohort_rows),
        "false_negative_count": len(false_negative_rows),
        "false_positive_count": len(false_positive_rows),
        "candidate_source_counts": dict(Counter(str(row.get("candidate_source") or "unknown") for row in cohort_rows)),
        "quality_label_split": quality_label_split,
        "trend_acceleration_band_split": _build_band_split(cohort_rows, "trend_acceleration", _trend_acceleration_band),
        "close_strength_band_split": _build_band_split(cohort_rows, "close_strength", _close_strength_band),
        "repeat_ticker_board": _build_repeat_ticker_board(cohort_rows),
        "blocker_clusters": _build_blocker_clusters(cohort_rows),
        "false_negative_rows": false_negative_rows,
        "false_positive_rows": false_positive_rows,
        "recommendation": "Prioritize close_continuation upstream-shadow rows that narrowly missed selection." if false_negative_rows else "No upstream-shadow false negatives qualified yet.",
    }


def render_btst_upstream_shadow_fnfp_dossier_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# Upstream Shadow FN/FP Dossier",
        "",
        "## Overview",
        f"- cohort_count: {analysis.get('cohort_count')}",
        f"- false_negative_count: {analysis.get('false_negative_count')}",
        f"- false_positive_count: {analysis.get('false_positive_count')}",
        f"- candidate_source_counts: {analysis.get('candidate_source_counts')}",
        f"- quality_label_split: {analysis.get('quality_label_split')}",
        "",
        "## Trend / Close Bands",
        f"- trend_acceleration_band_split: {analysis.get('trend_acceleration_band_split')}",
        f"- close_strength_band_split: {analysis.get('close_strength_band_split')}",
        "",
        "## Repeat Ticker Board",
    ]
    for repeat_row in list(analysis.get("repeat_ticker_board") or []):
        lines.append(f"- {repeat_row}")
    if not list(analysis.get("repeat_ticker_board") or []):
        lines.append("- none")
    lines.extend([
        "",
        "## Blocker Clusters",
    ])
    for cluster in list(analysis.get("blocker_clusters") or []):
        lines.append(f"- {cluster}")
    if not list(analysis.get("blocker_clusters") or []):
        lines.append("- none")
    lines.extend(["", "## False Negatives"])
    for row in list(analysis.get("false_negative_rows") or []):
        lines.append(f"- {row.get('trade_date')} {row.get('ticker')}")
    if not list(analysis.get("false_negative_rows") or []):
        lines.append("- none")
    lines.extend(["", "## False Positives"])
    for row in list(analysis.get("false_positive_rows") or []):
        lines.append(f"- {row.get('trade_date')} {row.get('ticker')}")
    if not list(analysis.get("false_positive_rows") or []):
        lines.append("- none")
    lines.extend(["", "## Recommendation", f"- {analysis.get('recommendation')}", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze upstream-shadow false negatives and false positives from BTST report artifacts.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_upstream_shadow_fnfp_dossier(args.reports_root)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_upstream_shadow_fnfp_dossier_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
