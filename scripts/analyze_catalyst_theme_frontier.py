from __future__ import annotations

import argparse
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.execution.daily_pipeline import (
    CATALYST_THEME_BREAKOUT_MIN,
    CATALYST_THEME_CANDIDATE_SCORE_MIN,
    CATALYST_THEME_CATALYST_MIN,
    CATALYST_THEME_CLOSE_MIN,
    CATALYST_THEME_MAX_TICKERS,
    CATALYST_THEME_SECTOR_MIN,
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_trade_date(value: Any) -> str:
    raw = str(value or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return raw


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_float_grid(raw: str | None, *, default: float) -> list[float]:
    values = [round(float(default), 4)]
    if raw is None or not str(raw).strip():
        return values
    for token in str(raw).split(","):
        stripped = token.strip()
        if not stripped:
            continue
        value = round(float(stripped), 4)
        if value not in values:
            values.append(value)
    return values


def default_catalyst_theme_thresholds() -> dict[str, float]:
    return {
        "candidate_score_min": round(float(CATALYST_THEME_CANDIDATE_SCORE_MIN), 4),
        "breakout_freshness_min": round(float(CATALYST_THEME_BREAKOUT_MIN), 4),
        "close_strength_min": round(float(CATALYST_THEME_CLOSE_MIN), 4),
        "sector_resonance_min": round(float(CATALYST_THEME_SECTOR_MIN), 4),
        "catalyst_freshness_min": round(float(CATALYST_THEME_CATALYST_MIN), 4),
    }


def default_catalyst_theme_frontier_grid_strings() -> dict[str, str]:
    defaults = default_catalyst_theme_thresholds()
    return {
        "candidate_score_min_grid": f"{defaults['candidate_score_min']},0.32,0.30,0.28",
        "breakout_min_grid": f"{defaults['breakout_freshness_min']},0.08",
        "close_min_grid": f"{defaults['close_strength_min']},0.18,0.16",
        "sector_min_grid": f"{defaults['sector_resonance_min']},0.22,0.20,0.18,0.16",
        "catalyst_min_grid": f"{defaults['catalyst_freshness_min']},0.42,0.40,0.38",
    }


def default_catalyst_theme_frontier_grids() -> dict[str, list[float]]:
    defaults = default_catalyst_theme_thresholds()
    grid_strings = default_catalyst_theme_frontier_grid_strings()
    return {
        "candidate_score_min_grid": _parse_float_grid(grid_strings["candidate_score_min_grid"], default=defaults["candidate_score_min"]),
        "breakout_min_grid": _parse_float_grid(grid_strings["breakout_min_grid"], default=defaults["breakout_freshness_min"]),
        "close_min_grid": _parse_float_grid(grid_strings["close_min_grid"], default=defaults["close_strength_min"]),
        "sector_min_grid": _parse_float_grid(grid_strings["sector_min_grid"], default=defaults["sector_resonance_min"]),
        "catalyst_min_grid": _parse_float_grid(grid_strings["catalyst_min_grid"], default=defaults["catalyst_freshness_min"]),
    }


def _build_variant_name(thresholds: dict[str, float]) -> str:
    return (
        f"candidate_{thresholds['candidate_score_min']:.2f}_"
        f"breakout_{thresholds['breakout_freshness_min']:.2f}_"
        f"close_{thresholds['close_strength_min']:.2f}_"
        f"sector_{thresholds['sector_resonance_min']:.2f}_"
        f"catalyst_{thresholds['catalyst_freshness_min']:.2f}"
    )


def _iter_selection_snapshots(report_dir: Path):
    selection_root = report_dir / "selection_artifacts"
    if not selection_root.exists():
        return
    for day_dir in sorted(path for path in selection_root.iterdir() if path.is_dir()):
        snapshot_path = day_dir / "selection_snapshot.json"
        if snapshot_path.exists():
            yield snapshot_path, _load_json(snapshot_path)


def _serialize_candidate_row(entry: dict[str, Any], *, trade_date: str, baseline_status: str) -> dict[str, Any]:
    metrics = dict(entry.get("metrics") or {})
    threshold_shortfalls = dict(entry.get("threshold_shortfalls") or {})
    return {
        "trade_date": trade_date,
        "ticker": str(entry.get("ticker") or ""),
        "baseline_status": baseline_status,
        "decision": str(entry.get("decision") or baseline_status),
        "candidate_source": str(entry.get("candidate_source") or baseline_status),
        "candidate_score": round(_safe_float(entry.get("score_target") if entry.get("score_target") is not None else entry.get("candidate_score")), 4),
        "breakout_freshness": round(_safe_float(metrics.get("breakout_freshness")), 4),
        "trend_acceleration": round(_safe_float(metrics.get("trend_acceleration")), 4),
        "close_strength": round(_safe_float(metrics.get("close_strength")), 4),
        "sector_resonance": round(_safe_float(metrics.get("sector_resonance")), 4),
        "catalyst_freshness": round(_safe_float(metrics.get("catalyst_freshness")), 4),
        "gate_status": dict(entry.get("gate_status") or {}),
        "blockers": list(entry.get("blockers") or []),
        "filter_reason": str(entry.get("filter_reason") or ""),
        "threshold_shortfalls": threshold_shortfalls,
        "failed_threshold_count": int(entry.get("failed_threshold_count") or len(threshold_shortfalls)),
        "total_shortfall": round(_safe_float(entry.get("total_shortfall")), 4),
        "top_reasons": list(entry.get("top_reasons") or []),
        "positive_tags": list(entry.get("positive_tags") or []),
    }


def collect_catalyst_theme_rows(report_dir: str | Path) -> dict[str, Any]:
    report_path = Path(report_dir).expanduser().resolve()
    rows: list[dict[str, Any]] = []
    candidate_source_counts: Counter[str] = Counter()
    shadow_filter_reason_counts: Counter[str] = Counter()
    trade_dates: set[str] = set()

    for _, snapshot in _iter_selection_snapshots(report_path) or []:
        trade_date = _normalize_trade_date(snapshot.get("trade_date"))
        trade_dates.add(trade_date)
        for entry in list(snapshot.get("catalyst_theme_candidates") or []):
            row = _serialize_candidate_row(dict(entry), trade_date=trade_date, baseline_status="selected")
            candidate_source_counts[row["candidate_source"]] += 1
            rows.append(row)
        for entry in list(snapshot.get("catalyst_theme_shadow_candidates") or []):
            row = _serialize_candidate_row(dict(entry), trade_date=trade_date, baseline_status="shadow")
            candidate_source_counts[row["candidate_source"]] += 1
            if row["filter_reason"]:
                shadow_filter_reason_counts[row["filter_reason"]] += 1
            rows.append(row)

    baseline_selected_count = sum(1 for row in rows if row.get("baseline_status") == "selected")
    shadow_candidate_count = sum(1 for row in rows if row.get("baseline_status") == "shadow")
    return {
        "report_dir": str(report_path),
        "trade_date_count": len(trade_dates),
        "baseline_selected_count": baseline_selected_count,
        "shadow_candidate_count": shadow_candidate_count,
        "candidate_source_counts": dict(candidate_source_counts.most_common()),
        "shadow_filter_reason_counts": dict(shadow_filter_reason_counts.most_common()),
        "rows": rows,
    }


def classify_catalyst_theme_candidate(row: dict[str, Any], thresholds: dict[str, float]) -> dict[str, Any]:
    gate_status = dict(row.get("gate_status") or {})
    if str(gate_status.get("data") or "pass") != "pass":
        return {
            "qualified": False,
            "primary_reason": "metric_data_fail",
            "failed_thresholds": {},
            "failed_threshold_count": 0,
            "total_shortfall": None,
        }

    threshold_order = [
        ("catalyst_freshness", "catalyst_freshness_min", "catalyst_freshness_below_catalyst_theme_floor"),
        ("sector_resonance", "sector_resonance_min", "sector_resonance_below_catalyst_theme_floor"),
        ("close_strength", "close_strength_min", "close_strength_below_catalyst_theme_floor"),
        ("breakout_freshness", "breakout_freshness_min", "breakout_freshness_below_catalyst_theme_floor"),
        ("candidate_score", "candidate_score_min", "candidate_score_below_catalyst_theme_floor"),
    ]
    failed_thresholds: dict[str, float] = {}
    primary_reason = "catalyst_theme_candidate_score_ranked"
    for metric_key, threshold_key, reason in threshold_order:
        actual_value = _safe_float(row.get(metric_key))
        threshold_value = _safe_float(thresholds.get(threshold_key))
        shortfall = round(threshold_value - actual_value, 4)
        if shortfall > 0:
            failed_thresholds[metric_key] = shortfall
            if primary_reason == "catalyst_theme_candidate_score_ranked":
                primary_reason = reason
    if failed_thresholds:
        return {
            "qualified": False,
            "primary_reason": primary_reason,
            "failed_thresholds": failed_thresholds,
            "failed_threshold_count": len(failed_thresholds),
            "total_shortfall": round(sum(failed_thresholds.values()), 4),
        }
    return {
        "qualified": True,
        "primary_reason": "catalyst_theme_candidate_score_ranked",
        "failed_thresholds": {},
        "failed_threshold_count": 0,
        "total_shortfall": 0.0,
    }


def _pick_recommended_variant(variants: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not variants:
        return None
    baseline = next((variant for variant in variants if variant.get("is_baseline")), variants[0])
    promotable = [variant for variant in variants if int(variant.get("promoted_shadow_count") or 0) > 0]
    if not promotable:
        return baseline
    promotable.sort(
        key=lambda variant: (
            float(variant.get("threshold_relaxation_cost") or 999.0),
            -int(variant.get("promoted_shadow_count") or 0),
            -int(variant.get("selected_candidate_count") or 0),
            str(variant.get("variant_name") or ""),
        )
    )
    return promotable[0]


def analyze_catalyst_theme_frontier(
    report_dir: str | Path,
    *,
    candidate_score_min_grid: list[float] | None = None,
    breakout_min_grid: list[float] | None = None,
    close_min_grid: list[float] | None = None,
    sector_min_grid: list[float] | None = None,
    catalyst_min_grid: list[float] | None = None,
    max_candidates_per_trade_date: int = CATALYST_THEME_MAX_TICKERS,
) -> dict[str, Any]:
    candidate_payload = collect_catalyst_theme_rows(report_dir)
    rows = list(candidate_payload["rows"])
    default_thresholds = default_catalyst_theme_thresholds()
    variants: list[dict[str, Any]] = []

    candidate_score_values = candidate_score_min_grid or [default_thresholds["candidate_score_min"]]
    breakout_values = breakout_min_grid or [default_thresholds["breakout_freshness_min"]]
    close_values = close_min_grid or [default_thresholds["close_strength_min"]]
    sector_values = sector_min_grid or [default_thresholds["sector_resonance_min"]]
    catalyst_values = catalyst_min_grid or [default_thresholds["catalyst_freshness_min"]]

    for candidate_score_min, breakout_min, close_min, sector_min, catalyst_min in itertools.product(
        candidate_score_values,
        breakout_values,
        close_values,
        sector_values,
        catalyst_values,
    ):
        thresholds = {
            "candidate_score_min": round(float(candidate_score_min), 4),
            "breakout_freshness_min": round(float(breakout_min), 4),
            "close_strength_min": round(float(close_min), 4),
            "sector_resonance_min": round(float(sector_min), 4),
            "catalyst_freshness_min": round(float(catalyst_min), 4),
        }
        qualified_by_trade_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
        filtered_reason_counts: Counter[str] = Counter()

        for row in rows:
            classification = classify_catalyst_theme_candidate(row, thresholds)
            if not classification["qualified"]:
                filtered_reason_counts[str(classification["primary_reason"])] += 1
                continue
            qualified_by_trade_date[str(row.get("trade_date") or "")].append({**row, **classification})

        selected_rows: list[dict[str, Any]] = []
        promoted_rows: list[dict[str, Any]] = []
        selected_candidate_count_by_trade_date: dict[str, int] = {}
        promoted_shadow_count_by_trade_date: dict[str, int] = {}
        promoted_filter_reason_counts: Counter[str] = Counter()

        for trade_date, trade_rows in sorted(qualified_by_trade_date.items()):
            ranked_rows = sorted(
                trade_rows,
                key=lambda current: (
                    float(current.get("candidate_score") or 0.0),
                    -float(current.get("total_shortfall") or 0.0),
                    str(current.get("ticker") or ""),
                ),
                reverse=True,
            )
            chosen_rows = ranked_rows[:max_candidates_per_trade_date]
            selected_candidate_count_by_trade_date[trade_date] = len(chosen_rows)
            promoted_rows_for_day = [row for row in chosen_rows if row.get("baseline_status") == "shadow"]
            promoted_shadow_count_by_trade_date[trade_date] = len(promoted_rows_for_day)
            for row in promoted_rows_for_day:
                promoted_rows.append(row)
                filter_reason = str(row.get("filter_reason") or "shadow_candidate")
                promoted_filter_reason_counts[filter_reason] += 1
            selected_rows.extend(chosen_rows)

        threshold_relaxation_cost = round(
            max(0.0, default_thresholds["candidate_score_min"] - thresholds["candidate_score_min"])
            + max(0.0, default_thresholds["breakout_freshness_min"] - thresholds["breakout_freshness_min"])
            + max(0.0, default_thresholds["close_strength_min"] - thresholds["close_strength_min"])
            + max(0.0, default_thresholds["sector_resonance_min"] - thresholds["sector_resonance_min"])
            + max(0.0, default_thresholds["catalyst_freshness_min"] - thresholds["catalyst_freshness_min"]),
            4,
        )
        variants.append(
            {
                "variant_name": _build_variant_name(thresholds),
                "thresholds": thresholds,
                "is_baseline": thresholds == default_thresholds,
                "qualified_pool_count": sum(len(value) for value in qualified_by_trade_date.values()),
                "selected_candidate_count": len(selected_rows),
                "baseline_selected_retained_count": sum(1 for row in selected_rows if row.get("baseline_status") == "selected"),
                "promoted_shadow_count": len(promoted_rows),
                "selected_candidate_count_by_trade_date": selected_candidate_count_by_trade_date,
                "promoted_shadow_count_by_trade_date": promoted_shadow_count_by_trade_date,
                "filtered_reason_counts": dict(filtered_reason_counts.most_common()),
                "promoted_filter_reason_counts": dict(promoted_filter_reason_counts.most_common()),
                "threshold_relaxation_cost": threshold_relaxation_cost,
                "top_promoted_rows": promoted_rows[:8],
            }
        )

    variants.sort(
        key=lambda variant: (
            int(variant.get("promoted_shadow_count") or 0),
            -float(variant.get("threshold_relaxation_cost") or 0.0),
            int(variant.get("selected_candidate_count") or 0),
            str(variant.get("variant_name") or ""),
        ),
        reverse=True,
    )
    baseline_variant = next((variant for variant in variants if variant.get("is_baseline")), variants[0] if variants else None)
    recommended_variant = _pick_recommended_variant(variants)

    if not rows:
        recommendation = "当前报告中没有题材催化正式池或影子池样本，无法做前沿诊断。"
    elif recommended_variant and recommended_variant is not baseline_variant and int(recommended_variant.get("promoted_shadow_count") or 0) > 0:
        recommendation = (
            f"诊断上优先查看 {recommended_variant['variant_name']}：在每个 trade_date 最多保留 {int(max_candidates_per_trade_date)} 个样本的前提下，"
            f"可额外提升 {recommended_variant['promoted_shadow_count']} 个影子候选进入题材催化正式池；"
            f"这是基于最小阈值放宽成本 {recommended_variant['threshold_relaxation_cost']:.4f} 的解释性前沿，不代表直接采用该阈值。"
        )
    else:
        recommendation = "baseline 下没有可提升到正式题材研究池的影子候选；当前更适合继续积累样本并观察影子池短板分布。"

    return {
        "report_dir": candidate_payload["report_dir"],
        "trade_date_count": candidate_payload["trade_date_count"],
        "baseline_selected_count": candidate_payload["baseline_selected_count"],
        "shadow_candidate_count": candidate_payload["shadow_candidate_count"],
        "candidate_source_counts": candidate_payload["candidate_source_counts"],
        "shadow_filter_reason_counts": candidate_payload["shadow_filter_reason_counts"],
        "max_candidates_per_trade_date": int(max_candidates_per_trade_date),
        "baseline_variant": baseline_variant,
        "recommended_variant": recommended_variant,
        "variants": variants,
        "recommendation": recommendation,
    }


def render_catalyst_theme_frontier_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Catalyst Theme Frontier Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- report_dir: {analysis.get('report_dir')}")
    lines.append(f"- trade_date_count: {analysis.get('trade_date_count')}")
    lines.append(f"- baseline_selected_count: {analysis.get('baseline_selected_count')}")
    lines.append(f"- shadow_candidate_count: {analysis.get('shadow_candidate_count')}")
    lines.append(f"- candidate_source_counts: {analysis.get('candidate_source_counts')}")
    lines.append(f"- shadow_filter_reason_counts: {analysis.get('shadow_filter_reason_counts')}")
    lines.append("")

    baseline_variant = dict(analysis.get("baseline_variant") or {})
    lines.append("## Baseline")
    lines.append(f"- variant_name: {baseline_variant.get('variant_name')}")
    lines.append(f"- thresholds: {baseline_variant.get('thresholds')}")
    lines.append(f"- selected_candidate_count: {baseline_variant.get('selected_candidate_count')}")
    lines.append(f"- promoted_shadow_count: {baseline_variant.get('promoted_shadow_count')}")
    lines.append("")

    recommended_variant = dict(analysis.get("recommended_variant") or {})
    lines.append("## Recommended Variant")
    lines.append(f"- variant_name: {recommended_variant.get('variant_name')}")
    lines.append(f"- thresholds: {recommended_variant.get('thresholds')}")
    lines.append(f"- threshold_relaxation_cost: {recommended_variant.get('threshold_relaxation_cost')}")
    lines.append(f"- selected_candidate_count: {recommended_variant.get('selected_candidate_count')}")
    lines.append(f"- promoted_shadow_count: {recommended_variant.get('promoted_shadow_count')}")
    lines.append(f"- promoted_filter_reason_counts: {recommended_variant.get('promoted_filter_reason_counts')}")
    lines.append("")

    lines.append("## Variant Ranking")
    for variant in list(analysis.get("variants") or [])[:10]:
        lines.append(
            f"- {variant.get('variant_name')}: selected={variant.get('selected_candidate_count')}, promoted_shadow={variant.get('promoted_shadow_count')}, relaxation_cost={variant.get('threshold_relaxation_cost')}, filtered_reason_counts={variant.get('filtered_reason_counts')}"
        )
    lines.append("")

    lines.append("## Promoted Shadow Examples")
    top_promoted_rows = list(recommended_variant.get("top_promoted_rows") or [])
    if not top_promoted_rows:
        lines.append("- none")
    else:
        for row in top_promoted_rows:
            lines.append(
                f"- {row.get('trade_date')} {row.get('ticker')}: filter_reason={row.get('filter_reason') or 'n/a'}, candidate_score={row.get('candidate_score')}, total_shortfall={row.get('total_shortfall')}, threshold_shortfalls={row.get('threshold_shortfalls')}"
            )
    lines.append("")

    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")
    return "\n".join(lines)


def generate_catalyst_theme_frontier_artifacts(
    report_dir: str | Path,
    *,
    output_json: str | Path,
    output_md: str | Path,
    candidate_score_min_grid: list[float] | None = None,
    breakout_min_grid: list[float] | None = None,
    close_min_grid: list[float] | None = None,
    sector_min_grid: list[float] | None = None,
    catalyst_min_grid: list[float] | None = None,
    max_candidates_per_trade_date: int = CATALYST_THEME_MAX_TICKERS,
) -> dict[str, Any]:
    default_grids = default_catalyst_theme_frontier_grids()
    analysis = analyze_catalyst_theme_frontier(
        report_dir,
        candidate_score_min_grid=default_grids["candidate_score_min_grid"] if candidate_score_min_grid is None else candidate_score_min_grid,
        breakout_min_grid=default_grids["breakout_min_grid"] if breakout_min_grid is None else breakout_min_grid,
        close_min_grid=default_grids["close_min_grid"] if close_min_grid is None else close_min_grid,
        sector_min_grid=default_grids["sector_min_grid"] if sector_min_grid is None else sector_min_grid,
        catalyst_min_grid=default_grids["catalyst_min_grid"] if catalyst_min_grid is None else catalyst_min_grid,
        max_candidates_per_trade_date=max_candidates_per_trade_date,
    )
    resolved_output_json = Path(output_json).expanduser().resolve()
    resolved_output_md = Path(output_md).expanduser().resolve()
    resolved_output_json.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_md.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resolved_output_md.write_text(render_catalyst_theme_frontier_markdown(analysis), encoding="utf-8")
    return {
        "analysis": analysis,
        "json_path": str(resolved_output_json),
        "markdown_path": str(resolved_output_md),
    }


def main() -> None:
    defaults = default_catalyst_theme_thresholds()
    default_grid_strings = default_catalyst_theme_frontier_grid_strings()
    parser = argparse.ArgumentParser(description="Analyze catalyst-theme frontier variants using baseline and shadow candidates from selection snapshots.")
    parser.add_argument("--report-dir", required=True, help="Paper trading report directory containing selection_artifacts")
    parser.add_argument("--candidate-score-min-grid", default=default_grid_strings["candidate_score_min_grid"])
    parser.add_argument("--breakout-min-grid", default=default_grid_strings["breakout_min_grid"])
    parser.add_argument("--close-min-grid", default=default_grid_strings["close_min_grid"])
    parser.add_argument("--sector-min-grid", default=default_grid_strings["sector_min_grid"])
    parser.add_argument("--catalyst-min-grid", default=default_grid_strings["catalyst_min_grid"])
    parser.add_argument("--max-candidates-per-trade-date", type=int, default=CATALYST_THEME_MAX_TICKERS)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_catalyst_theme_frontier(
        args.report_dir,
        candidate_score_min_grid=_parse_float_grid(args.candidate_score_min_grid, default=defaults["candidate_score_min"]),
        breakout_min_grid=_parse_float_grid(args.breakout_min_grid, default=defaults["breakout_freshness_min"]),
        close_min_grid=_parse_float_grid(args.close_min_grid, default=defaults["close_strength_min"]),
        sector_min_grid=_parse_float_grid(args.sector_min_grid, default=defaults["sector_resonance_min"]),
        catalyst_min_grid=_parse_float_grid(args.catalyst_min_grid, default=defaults["catalyst_freshness_min"]),
        max_candidates_per_trade_date=int(args.max_candidates_per_trade_date),
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_catalyst_theme_frontier_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()