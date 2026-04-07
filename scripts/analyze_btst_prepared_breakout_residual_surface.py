from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scripts.analyze_btst_prepared_breakout_cohort import REFERENCE_TICKER
from scripts.analyze_btst_prepared_breakout_relief_validation import RELIEF_FIELDS
from scripts.replay_selection_target_calibration import analyze_selection_target_replay_sources, load_selection_target_replay_sources

REPORTS_DIR = Path("data/reports")
DEFAULT_COHORT_PATH = REPORTS_DIR / "btst_prepared_breakout_cohort_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_prepared_breakout_residual_surface_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_prepared_breakout_residual_surface_latest.md"

POSITIVE_FACTORS: tuple[str, ...] = (
    "breakout_freshness",
    "trend_acceleration",
    "volume_expansion_quality",
    "close_strength",
    "sector_resonance",
    "catalyst_freshness",
    "layer_c_alignment",
)
NEGATIVE_FACTORS: tuple[str, ...] = (
    "stale_trend_repair_penalty",
    "overhead_supply_penalty",
    "extension_without_room_penalty",
    "layer_c_avoid_penalty",
    "watchlist_zero_catalyst_penalty",
    "watchlist_zero_catalyst_crowded_penalty",
    "watchlist_zero_catalyst_flat_trend_penalty",
)
KEY_METRICS: tuple[str, ...] = (
    "breakout_freshness",
    "trend_acceleration",
    "volume_expansion_quality",
    "close_strength",
    "sector_resonance",
    "catalyst_freshness",
    "layer_c_alignment",
    "long_trend_strength",
)


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _score_stats(values: list[Any]) -> dict[str, float | None]:
    numeric_values = [float(value) for value in values if isinstance(value, (int, float))]
    return {
        "min": round(min(numeric_values), 4) if numeric_values else None,
        "max": round(max(numeric_values), 4) if numeric_values else None,
        "mean": _mean(numeric_values),
    }


def _average_mapping(rows: list[dict[str, Any]], field: str, keys: tuple[str, ...]) -> dict[str, float]:
    result: dict[str, float] = {}
    for key in keys:
        numeric_values = [
            float(dict(row.get(field) or {}).get(key))
            for row in rows
            if isinstance(dict(row.get(field) or {}).get(key), (int, float))
        ]
        result[key] = round(sum(numeric_values) / len(numeric_values), 4) if numeric_values else 0.0
    return result


def _difference_mapping(left: dict[str, float], right: dict[str, float], keys: tuple[str, ...]) -> dict[str, float]:
    return {
        key: round(float(left.get(key) or 0.0) - float(right.get(key) or 0.0), 4)
        for key in keys
    }


def _resolve_focus_ticker(cohort: dict[str, Any], focus_ticker: str | None) -> str:
    if focus_ticker:
        return str(focus_ticker)
    next_candidate = dict(cohort.get("next_candidate") or {})
    if next_candidate.get("ticker"):
        return str(next_candidate.get("ticker"))
    raise ValueError("No focus ticker provided and cohort report has no next_candidate.")


def _build_focus_report_dirs(cohort: dict[str, Any], focus_ticker: str, reference_ticker: str) -> list[Path]:
    report_dirs: set[Path] = set()
    for row in list(cohort.get("candidates") or []):
        ticker = str(row.get("ticker") or "")
        if ticker not in {focus_ticker, reference_ticker}:
            continue
        for candidate_row in list(row.get("rows") or []):
            report_dir = str(candidate_row.get("report_dir") or "").strip()
            if report_dir:
                report_dirs.add(Path(report_dir).expanduser().resolve())
    return sorted(report_dirs)


def _collect_focused_rows(report_dirs: list[Path], *, focus_tickers: list[str], profile_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for report_dir in report_dirs:
        replay_sources = load_selection_target_replay_sources(report_dir)
        if not replay_sources:
            continue
        analysis = analyze_selection_target_replay_sources(
            replay_sources,
            profile_name=profile_name,
            focus_tickers=focus_tickers,
        )
        rows.extend(dict(row or {}) for row in list(analysis.get("focused_score_diagnostics") or []))
    return rows


def _normalize_diagnostic_row(row: dict[str, Any]) -> dict[str, Any]:
    metrics_payload = dict(row.get("replayed_metrics_payload") or {})
    explainability = dict(row.get("replayed_explainability_payload") or {})
    return {
        "ticker": str(row.get("ticker") or ""),
        "trade_date": row.get("trade_date"),
        "replayed_decision": row.get("replayed_decision"),
        "replayed_score_target": row.get("replayed_score_target"),
        "replayed_gap_to_near_miss": row.get("replayed_gap_to_near_miss"),
        "replayed_gap_to_selected": row.get("replayed_gap_to_selected"),
        "replayed_gate_status": dict(row.get("replayed_gate_status") or {}),
        "replayed_top_reasons": list(row.get("replayed_top_reasons") or []),
        "report_dir": str(Path(str(row.get("replay_input_path") or "")).expanduser().resolve().parents[2]),
        "positive_contributions": dict(row.get("replayed_weighted_positive_contributions") or {}),
        "negative_contributions": dict(row.get("replayed_weighted_negative_contributions") or {}),
        "metrics_payload": metrics_payload,
        "explainability": explainability,
    }


def _build_gate_miss_counts(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    gate_miss_counts: dict[str, dict[str, int]] = {}
    for relief_field in RELIEF_FIELDS:
        counters: Counter[str] = Counter()
        for row in rows:
            explainability = dict(row.get("explainability") or {})
            relief_payload = dict(explainability.get(relief_field) or {})
            gate_hits = dict(relief_payload.get("gate_hits") or {})
            for gate_name, hit in gate_hits.items():
                if hit is False:
                    counters[str(gate_name)] += 1
        gate_miss_counts[relief_field] = dict(counters)
    return gate_miss_counts


def _build_relief_counts(rows: list[dict[str, Any]], status_key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for relief_field in RELIEF_FIELDS:
        counts[relief_field] = sum(
            1
            for row in rows
            if bool(dict(dict(row.get("explainability") or {}).get(relief_field) or {}).get(status_key))
        )
    return counts


def _build_surface_summary(ticker: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    decision_counts = Counter(str(row.get("replayed_decision") or "unknown") for row in rows)
    stage_counts = Counter(str(dict(row.get("metrics_payload") or {}).get("breakout_stage") or "unknown") for row in rows)
    gate_status_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        for gate_name, gate_status in dict(row.get("replayed_gate_status") or {}).items():
            gate_status_counts[str(gate_name)][str(gate_status or "unknown")] += 1

    positive_contribution_means = _average_mapping(rows, "positive_contributions", POSITIVE_FACTORS)
    negative_contribution_means = _average_mapping(rows, "negative_contributions", NEGATIVE_FACTORS)
    metric_means = _average_mapping(rows, "metrics_payload", KEY_METRICS)
    relief_eligible_window_counts = _build_relief_counts(rows, "eligible")
    relief_applied_window_counts = _build_relief_counts(rows, "applied")

    return {
        "ticker": ticker,
        "row_count": len(rows),
        "decision_counts": dict(decision_counts),
        "breakout_stage_counts": dict(stage_counts),
        "gate_status_counts": {name: dict(counts) for name, counts in gate_status_counts.items()},
        "score_target_stats": _score_stats([row.get("replayed_score_target") for row in rows]),
        "required_score_uplift_to_near_miss_stats": _score_stats([row.get("replayed_gap_to_near_miss") for row in rows]),
        "required_score_uplift_to_selected_stats": _score_stats([row.get("replayed_gap_to_selected") for row in rows]),
        "weighted_positive_contribution_means": positive_contribution_means,
        "weighted_negative_contribution_means": negative_contribution_means,
        "key_metric_means": metric_means,
        "relief_eligible_window_counts": relief_eligible_window_counts,
        "relief_applied_window_counts": relief_applied_window_counts,
        "relief_gate_miss_counts": _build_gate_miss_counts(rows),
        "top_reason_counts": dict(Counter(reason for row in rows for reason in list(row.get("replayed_top_reasons") or [])).most_common(8)),
        "rows": rows,
    }


def _build_priority_board(cohort: dict[str, Any], *, reference_ticker: str, limit: int = 5) -> list[dict[str, Any]]:
    board: list[dict[str, Any]] = []
    for row in list(cohort.get("candidates") or []):
        ticker = str(row.get("ticker") or "")
        if not ticker or ticker == reference_ticker:
            continue
        gap_stats = dict(row.get("required_score_uplift_to_selected_stats") or {})
        board.append(
            {
                "ticker": ticker,
                "verdict": row.get("verdict"),
                "decision_counts": dict(row.get("decision_counts") or {}),
                "selected_relief_window_count": int(row.get("selected_relief_window_count") or 0),
                "required_score_uplift_to_selected_min": gap_stats.get("min"),
                "required_score_uplift_to_selected_mean": gap_stats.get("mean"),
            }
        )
    board.sort(
        key=lambda row: (
            float(row.get("required_score_uplift_to_selected_min")) if isinstance(row.get("required_score_uplift_to_selected_min"), (int, float)) else 999.0,
            -int(dict(row.get("decision_counts") or {}).get("near_miss", 0)),
            str(row.get("ticker") or ""),
        )
    )
    return board[:limit]


def analyze_btst_prepared_breakout_residual_surface(
    reports_root: str | Path,
    *,
    focus_ticker: str | None = None,
    reference_ticker: str = REFERENCE_TICKER,
    profile_name: str = "default",
    cohort_path: str | Path | None = None,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    resolved_cohort_path = Path(cohort_path or DEFAULT_COHORT_PATH).expanduser().resolve()
    cohort = _load_json(resolved_cohort_path)
    resolved_focus_ticker = _resolve_focus_ticker(cohort, focus_ticker)
    focus_report_dirs = _build_focus_report_dirs(cohort, resolved_focus_ticker, reference_ticker)

    focused_rows = [
        _normalize_diagnostic_row(row)
        for row in _collect_focused_rows(focus_report_dirs, focus_tickers=[resolved_focus_ticker, reference_ticker], profile_name=profile_name)
    ]
    rows_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in focused_rows:
        rows_by_ticker[str(row.get("ticker") or "")].append(row)

    focus_rows = rows_by_ticker.get(resolved_focus_ticker, [])
    reference_rows = rows_by_ticker.get(reference_ticker, [])
    if not focus_rows:
        raise ValueError(f"No focused diagnostic rows found for ticker: {resolved_focus_ticker}")

    focus_surface = _build_surface_summary(resolved_focus_ticker, focus_rows)
    reference_surface = _build_surface_summary(reference_ticker, reference_rows) if reference_rows else {}
    focus_gap_stats = dict(focus_surface.get("required_score_uplift_to_selected_stats") or {})
    focus_decision_counts = dict(focus_surface.get("decision_counts") or {})
    focus_eligible_counts = dict(focus_surface.get("relief_eligible_window_counts") or {})
    focus_applied_counts = dict(focus_surface.get("relief_applied_window_counts") or {})

    if (
        int(focus_decision_counts.get("selected", 0)) == 0
        and int(focus_decision_counts.get("near_miss", 0)) == 0
        and isinstance(focus_gap_stats.get("min"), (int, float))
        and float(focus_gap_stats.get("min")) > 0.15
        and sum(int(value) for value in focus_eligible_counts.values()) == 0
        and sum(int(value) for value in focus_applied_counts.values()) == 0
    ):
        verdict = "non_actionable_score_surface"
        recommendation = f"{resolved_focus_ticker} should stay outside the prepared-breakout uplift lane; it is a broad score-deficit surface, not a narrow missing-relief case like {reference_ticker}."
    elif int(focus_decision_counts.get("near_miss", 0)) > 0 and isinstance(focus_gap_stats.get("min"), (int, float)) and float(focus_gap_stats.get("min")) <= 0.12:
        verdict = "candidate_relief_frontier"
        recommendation = f"{resolved_focus_ticker} is close enough to selected that a new narrow relief hypothesis may be worth testing."
    else:
        verdict = "mixed_residual_surface"
        recommendation = f"{resolved_focus_ticker} remains below the prepared-breakout anchor; keep it in the residual queue until a narrower, evidence-backed lever appears."

    comparison_vs_reference = {}
    if reference_surface:
        comparison_vs_reference = {
            "reference_ticker": reference_ticker,
            "score_target_mean_delta": round(
                float(dict(focus_surface.get("score_target_stats") or {}).get("mean") or 0.0)
                - float(dict(reference_surface.get("score_target_stats") or {}).get("mean") or 0.0),
                4,
            ),
            "required_score_uplift_to_selected_mean_delta": round(
                float(dict(focus_surface.get("required_score_uplift_to_selected_stats") or {}).get("mean") or 0.0)
                - float(dict(reference_surface.get("required_score_uplift_to_selected_stats") or {}).get("mean") or 0.0),
                4,
            ),
            "positive_contribution_deltas": _difference_mapping(
                dict(focus_surface.get("weighted_positive_contribution_means") or {}),
                dict(reference_surface.get("weighted_positive_contribution_means") or {}),
                POSITIVE_FACTORS,
            ),
            "negative_contribution_deltas": _difference_mapping(
                dict(focus_surface.get("weighted_negative_contribution_means") or {}),
                dict(reference_surface.get("weighted_negative_contribution_means") or {}),
                NEGATIVE_FACTORS,
            ),
            "key_metric_deltas": _difference_mapping(
                dict(focus_surface.get("key_metric_means") or {}),
                dict(reference_surface.get("key_metric_means") or {}),
                KEY_METRICS,
            ),
        }

    return {
        "reports_root": str(resolved_reports_root),
        "cohort_path": str(resolved_cohort_path),
        "profile_name": profile_name,
        "focus_ticker": resolved_focus_ticker,
        "reference_ticker": reference_ticker,
        "focus_report_dir_count": len(focus_report_dirs),
        "focus_surface": focus_surface,
        "reference_surface": reference_surface,
        "comparison_vs_reference": comparison_vs_reference,
        "priority_residual_candidates": _build_priority_board(cohort, reference_ticker=reference_ticker),
        "verdict": verdict,
        "recommendation": recommendation,
    }


def render_btst_prepared_breakout_residual_surface_markdown(analysis: dict[str, Any]) -> str:
    focus_surface = dict(analysis.get("focus_surface") or {})
    reference_surface = dict(analysis.get("reference_surface") or {})
    comparison = dict(analysis.get("comparison_vs_reference") or {})
    lines: list[str] = []
    lines.append("# BTST Prepared-Breakout Residual Surface")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- focus_ticker: {analysis['focus_ticker']}")
    lines.append(f"- reference_ticker: {analysis['reference_ticker']}")
    lines.append(f"- focus_report_dir_count: {analysis['focus_report_dir_count']}")
    lines.append(f"- profile_name: {analysis['profile_name']}")
    lines.append("")
    lines.append("## Focus Surface")
    lines.append(f"- decision_counts: {focus_surface.get('decision_counts')}")
    lines.append(f"- breakout_stage_counts: {focus_surface.get('breakout_stage_counts')}")
    lines.append(f"- score_target_stats: {focus_surface.get('score_target_stats')}")
    lines.append(f"- required_score_uplift_to_selected_stats: {focus_surface.get('required_score_uplift_to_selected_stats')}")
    lines.append(f"- weighted_positive_contribution_means: {focus_surface.get('weighted_positive_contribution_means')}")
    lines.append(f"- weighted_negative_contribution_means: {focus_surface.get('weighted_negative_contribution_means')}")
    lines.append(f"- key_metric_means: {focus_surface.get('key_metric_means')}")
    lines.append(f"- relief_eligible_window_counts: {focus_surface.get('relief_eligible_window_counts')}")
    lines.append(f"- relief_applied_window_counts: {focus_surface.get('relief_applied_window_counts')}")
    lines.append(f"- relief_gate_miss_counts: {focus_surface.get('relief_gate_miss_counts')}")
    lines.append("")
    if reference_surface:
        lines.append("## Reference Comparison")
        lines.append(f"- reference_decision_counts: {reference_surface.get('decision_counts')}")
        lines.append(f"- reference_score_target_stats: {reference_surface.get('score_target_stats')}")
        lines.append(f"- comparison_vs_reference: {comparison}")
        lines.append("")
    lines.append("## Residual Priority Board")
    for row in list(analysis.get("priority_residual_candidates") or []):
        lines.append(
            f"- {row.get('ticker')}: verdict={row.get('verdict')} decision_counts={row.get('decision_counts')} "
            f"selected_relief_window_count={row.get('selected_relief_window_count')} "
            f"required_score_uplift_to_selected_min={row.get('required_score_uplift_to_selected_min')}"
        )
    if not list(analysis.get("priority_residual_candidates") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Verdict")
    lines.append(f"- verdict: {analysis['verdict']}")
    lines.append(f"- recommendation: {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose prepared-breakout residual surfaces that should not inherit the 300505 uplift path.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--focus-ticker", default="")
    parser.add_argument("--reference-ticker", default=REFERENCE_TICKER)
    parser.add_argument("--profile-name", default="default")
    parser.add_argument("--cohort-path", default=str(DEFAULT_COHORT_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_prepared_breakout_residual_surface(
        args.reports_root,
        focus_ticker=str(args.focus_ticker or "").strip() or None,
        reference_ticker=str(args.reference_ticker or REFERENCE_TICKER),
        profile_name=str(args.profile_name or "default"),
        cohort_path=args.cohort_path,
    )

    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_prepared_breakout_residual_surface_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
