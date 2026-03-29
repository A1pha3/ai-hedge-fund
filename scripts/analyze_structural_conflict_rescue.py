from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.execution.models import LayerCResult
from src.targets.profiles import get_short_trade_target_profile
from src.targets.short_trade_target import evaluate_short_trade_rejected_target, evaluate_short_trade_selected_target


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_replay_input(report_dir: Path, trade_date: str) -> dict[str, Any]:
    replay_input_path = report_dir / "selection_artifacts" / trade_date / "selection_target_replay_input.json"
    return _load_json(replay_input_path)


def _load_snapshot(report_dir: Path, trade_date: str) -> dict[str, Any]:
    snapshot_path = report_dir / "selection_artifacts" / trade_date / "selection_snapshot.json"
    return _load_json(snapshot_path)


def _parse_float_grid(raw: str | None, *, default: list[float]) -> list[float]:
    if raw is None or not str(raw).strip():
        return list(default)
    values: list[float] = []
    for token in str(raw).split(","):
        normalized = token.strip()
        if not normalized:
            continue
        values.append(float(normalized))
    return values or list(default)


def _locate_entry(replay_input: dict[str, Any], ticker: str) -> tuple[str, dict[str, Any]]:
    for entry in list(replay_input.get("watchlist") or []):
        if str(entry.get("ticker") or "") == ticker:
            return "watchlist", dict(entry)
    for entry in list(replay_input.get("rejected_entries") or []):
        if str(entry.get("ticker") or "") == ticker:
            return "rejected_entries", dict(entry)
    for entry in list(replay_input.get("supplemental_short_trade_entries") or []):
        if str(entry.get("ticker") or "") == ticker:
            return "supplemental_short_trade_entries", dict(entry)
    raise ValueError(f"Ticker not found in replay input: {ticker}")


def _evaluate_variant(
    *,
    trade_date: str,
    source_bucket: str,
    entry: dict[str, Any],
    buy_order_tickers: set[str],
    profile_name: str | None = None,
    profile_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if source_bucket == "watchlist":
        item = LayerCResult.model_validate(entry)
        result = evaluate_short_trade_selected_target(
            trade_date=trade_date,
            item=item,
            included_in_buy_orders=item.ticker in buy_order_tickers,
            profile_name=profile_name,
            profile_overrides=profile_overrides,
        )
    else:
        result = evaluate_short_trade_rejected_target(
            trade_date=trade_date,
            entry=entry,
            profile_name=profile_name,
            profile_overrides=profile_overrides,
        )

    metrics_payload = dict(result.metrics_payload or {})
    thresholds = dict(metrics_payload.get("thresholds") or {})
    near_miss_threshold = float(thresholds.get("near_miss_threshold", 0.46) or 0.46)
    select_threshold = float(thresholds.get("select_threshold", 0.58) or 0.58)
    return {
        "decision": result.decision,
        "score_target": round(float(result.score_target), 4),
        "gap_to_near_miss": round(near_miss_threshold - float(result.score_target), 4),
        "gap_to_select": round(select_threshold - float(result.score_target), 4),
        "blockers": list(result.blockers or []),
        "top_reasons": list(result.top_reasons or []),
        "positive_metrics": {
            key: round(float(metrics_payload.get(key, 0.0) or 0.0), 4)
            for key in [
                "breakout_freshness",
                "trend_acceleration",
                "volume_expansion_quality",
                "close_strength",
                "catalyst_freshness",
                "layer_c_alignment",
            ]
        },
        "penalties": {
            key: round(float(metrics_payload.get(key, 0.0) or 0.0), 4)
            for key in [
                "layer_c_avoid_penalty",
                "stale_trend_repair_penalty",
                "overhead_supply_penalty",
                "extension_without_room_penalty",
            ]
        },
        "thresholds": thresholds,
    }


def _build_penalty_threshold_frontier(
    *,
    trade_date: str,
    source_bucket: str,
    entry: dict[str, Any],
    buy_order_tickers: set[str],
    base_profile_overrides: dict[str, Any],
    avoid_penalty_values: list[float],
    stale_score_penalty_weight_values: list[float],
    extension_score_penalty_weight_values: list[float],
    select_threshold_values: list[float],
    near_miss_threshold_values: list[float],
) -> dict[str, Any]:
    default_profile = get_short_trade_target_profile("default")
    rows: list[dict[str, Any]] = []

    for avoid_penalty in avoid_penalty_values:
        for stale_weight in stale_score_penalty_weight_values:
            for extension_weight in extension_score_penalty_weight_values:
                for select_threshold in select_threshold_values:
                    for near_miss_threshold in near_miss_threshold_values:
                        if float(select_threshold) < float(near_miss_threshold):
                            continue
                        profile_overrides = {
                            **base_profile_overrides,
                            "layer_c_avoid_penalty": float(avoid_penalty),
                            "stale_score_penalty_weight": float(stale_weight),
                            "extension_score_penalty_weight": float(extension_weight),
                            "select_threshold": float(select_threshold),
                            "near_miss_threshold": float(near_miss_threshold),
                        }
                        payload = _evaluate_variant(
                            trade_date=trade_date,
                            source_bucket=source_bucket,
                            entry=entry,
                            buy_order_tickers=buy_order_tickers,
                            profile_overrides=profile_overrides,
                        )
                        adjustment_cost = round(
                            (float(default_profile.layer_c_avoid_penalty) - float(avoid_penalty))
                            + (float(default_profile.stale_score_penalty_weight) - float(stale_weight))
                            + (float(default_profile.extension_score_penalty_weight) - float(extension_weight))
                            + (float(default_profile.select_threshold) - float(select_threshold))
                            + (float(default_profile.near_miss_threshold) - float(near_miss_threshold)),
                            4,
                        )
                        rows.append(
                            {
                                "layer_c_avoid_penalty": round(float(avoid_penalty), 4),
                                "stale_score_penalty_weight": round(float(stale_weight), 4),
                                "extension_score_penalty_weight": round(float(extension_weight), 4),
                                "select_threshold": round(float(select_threshold), 4),
                                "near_miss_threshold": round(float(near_miss_threshold), 4),
                                "adjustment_cost": adjustment_cost,
                                **payload,
                            }
                        )

    near_miss_rows = [row for row in rows if row["decision"] in {"near_miss", "selected"}]
    selected_rows = [row for row in rows if row["decision"] == "selected"]
    best_score_row = max(rows, key=lambda row: row["score_target"]) if rows else None
    minimal_near_miss_row = (
        min(
            near_miss_rows,
            key=lambda row: (
                float(row["adjustment_cost"]),
                abs(float(row["gap_to_near_miss"])),
                -float(row["score_target"]),
            ),
        )
        if near_miss_rows
        else None
    )
    minimal_selected_row = (
        min(
            selected_rows,
            key=lambda row: (
                float(row["adjustment_cost"]),
                -float(row["score_target"]),
            ),
        )
        if selected_rows
        else None
    )
    return {
        "base_profile_overrides": dict(base_profile_overrides),
        "grid": {
            "layer_c_avoid_penalty": [round(float(value), 4) for value in avoid_penalty_values],
            "stale_score_penalty_weight": [round(float(value), 4) for value in stale_score_penalty_weight_values],
            "extension_score_penalty_weight": [round(float(value), 4) for value in extension_score_penalty_weight_values],
            "select_threshold": [round(float(value), 4) for value in select_threshold_values],
            "near_miss_threshold": [round(float(value), 4) for value in near_miss_threshold_values],
        },
        "row_count": len(rows),
        "rows": rows,
        "best_score_row": best_score_row,
        "minimal_near_miss_row": minimal_near_miss_row,
        "minimal_selected_row": minimal_selected_row,
    }


def render_structural_conflict_rescue_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Structural Conflict Rescue Analysis")
    lines.append("")
    lines.append("## Focus")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- trade_date: {analysis['trade_date']}")
    lines.append(f"- ticker: {analysis['ticker']}")
    lines.append(f"- source_bucket: {analysis['source_bucket']}")
    lines.append(f"- candidate_source: {analysis['candidate_source']}")
    lines.append(f"- stored_short_trade_decision: {analysis['stored_short_trade_decision']}")
    lines.append("")
    lines.append("## Variants")
    for row in analysis["variant_results"]:
        lines.append(
            f"- {row['variant']}: decision={row['decision']}, score_target={row['score_target']}, gap_to_near_miss={row['gap_to_near_miss']}, blockers={row['blockers']}, penalties={row['penalties']}"
        )
    penalty_threshold_frontier = dict(analysis.get("penalty_threshold_frontier") or {})
    if penalty_threshold_frontier:
        lines.append("")
        lines.append("## Penalty Threshold Frontier")
        lines.append(f"- row_count: {penalty_threshold_frontier.get('row_count', 0)}")
        minimal_near_miss_row = penalty_threshold_frontier.get("minimal_near_miss_row")
        minimal_selected_row = penalty_threshold_frontier.get("minimal_selected_row")
        best_score_row = penalty_threshold_frontier.get("best_score_row")
        if minimal_near_miss_row:
            lines.append(
                f"- minimal_near_miss_row: decision={minimal_near_miss_row['decision']}, score_target={minimal_near_miss_row['score_target']}, adjustment_cost={minimal_near_miss_row['adjustment_cost']}, stale_weight={minimal_near_miss_row['stale_score_penalty_weight']}, extension_weight={minimal_near_miss_row['extension_score_penalty_weight']}, select={minimal_near_miss_row['select_threshold']}, near_miss={minimal_near_miss_row['near_miss_threshold']}"
            )
        else:
            lines.append("- minimal_near_miss_row: none")
        if minimal_selected_row:
            lines.append(
                f"- minimal_selected_row: decision={minimal_selected_row['decision']}, score_target={minimal_selected_row['score_target']}, adjustment_cost={minimal_selected_row['adjustment_cost']}, stale_weight={minimal_selected_row['stale_score_penalty_weight']}, extension_weight={minimal_selected_row['extension_score_penalty_weight']}, select={minimal_selected_row['select_threshold']}, near_miss={minimal_selected_row['near_miss_threshold']}"
            )
        else:
            lines.append("- minimal_selected_row: none")
        if best_score_row:
            lines.append(
                f"- best_score_row: decision={best_score_row['decision']}, score_target={best_score_row['score_target']}, adjustment_cost={best_score_row['adjustment_cost']}, stale_weight={best_score_row['stale_score_penalty_weight']}, extension_weight={best_score_row['extension_score_penalty_weight']}, select={best_score_row['select_threshold']}, near_miss={best_score_row['near_miss_threshold']}"
            )
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_structural_conflict_rescue(
    report_dir: str | Path,
    trade_date: str,
    ticker: str,
    *,
    avoid_penalty_grid: list[float] | None = None,
    stale_score_penalty_grid: list[float] | None = None,
    extension_score_penalty_grid: list[float] | None = None,
    select_threshold_grid: list[float] | None = None,
    near_miss_threshold_grid: list[float] | None = None,
) -> dict[str, Any]:
    report_path = Path(report_dir).expanduser().resolve()
    replay_input = _load_replay_input(report_path, trade_date)
    snapshot = _load_snapshot(report_path, trade_date)
    source_bucket, entry = _locate_entry(replay_input, ticker)
    stored_target = dict(dict(snapshot.get("selection_targets") or {}).get(ticker) or {})
    stored_short_trade = dict(stored_target.get("short_trade") or {})
    buy_order_tickers = {str(current) for current in list(replay_input.get("buy_order_tickers") or [])}

    variants = [
        ("baseline", None, None),
        (
            "remove_conflict_hard_block_keep_penalty",
            None,
            {"hard_block_bearish_conflicts": []},
        ),
        (
            "remove_conflict_hard_block_and_conflict_penalty",
            None,
            {
                "hard_block_bearish_conflicts": [],
                "overhead_conflict_penalty_conflicts": [],
            },
        ),
        (
            "remove_conflict_hard_block_and_conflict_penalty_aggressive_thresholds",
            None,
            {
                "hard_block_bearish_conflicts": [],
                "overhead_conflict_penalty_conflicts": [],
                "near_miss_threshold": 0.42,
                "select_threshold": 0.54,
            },
        ),
    ]

    variant_results = []
    for variant_name, profile_name, profile_overrides in variants:
        payload = _evaluate_variant(
            trade_date=trade_date,
            source_bucket=source_bucket,
            entry=entry,
            buy_order_tickers=buy_order_tickers,
            profile_name=profile_name,
            profile_overrides=profile_overrides,
        )
        variant_results.append({"variant": variant_name, **payload})

    best_variant = max(variant_results, key=lambda row: row["score_target"])
    default_profile = get_short_trade_target_profile("default")
    conflict_release_overrides = {
        "hard_block_bearish_conflicts": [],
        "overhead_conflict_penalty_conflicts": [],
    }
    penalty_threshold_frontier = _build_penalty_threshold_frontier(
        trade_date=trade_date,
        source_bucket=source_bucket,
        entry=entry,
        buy_order_tickers=buy_order_tickers,
        base_profile_overrides=conflict_release_overrides,
        avoid_penalty_values=avoid_penalty_grid or [float(default_profile.layer_c_avoid_penalty)],
        stale_score_penalty_weight_values=stale_score_penalty_grid or [float(default_profile.stale_score_penalty_weight)],
        extension_score_penalty_weight_values=extension_score_penalty_grid or [float(default_profile.extension_score_penalty_weight)],
        select_threshold_values=select_threshold_grid or [float(default_profile.select_threshold)],
        near_miss_threshold_values=near_miss_threshold_grid or [float(default_profile.near_miss_threshold)],
    )
    minimal_near_miss_row = penalty_threshold_frontier.get("minimal_near_miss_row")
    minimal_selected_row = penalty_threshold_frontier.get("minimal_selected_row")
    recommendation = (
        f"最佳释放路径是 {best_variant['variant']}，score_target={best_variant['score_target']}，decision={best_variant['decision']}。"
        if variant_results
        else "未生成任何变体结果。"
    )
    if minimal_near_miss_row:
        recommendation += (
            f" 在去掉 conflict hard block 与 surcharge 后，最小 near_miss frontier 为 "
            f"stale_weight={minimal_near_miss_row['stale_score_penalty_weight']}、extension_weight={minimal_near_miss_row['extension_score_penalty_weight']}、"
            f"select_threshold={minimal_near_miss_row['select_threshold']}、near_miss_threshold={minimal_near_miss_row['near_miss_threshold']}，"
            f"adjustment_cost={minimal_near_miss_row['adjustment_cost']}。"
        )
    else:
        recommendation += " 在当前 penalty+threshold 搜索空间内仍未找到 near_miss rescue row。"
    if minimal_selected_row:
        recommendation += (
            f" 最小 selected frontier 为 stale_weight={minimal_selected_row['stale_score_penalty_weight']}、"
            f"extension_weight={minimal_selected_row['extension_score_penalty_weight']}、select_threshold={minimal_selected_row['select_threshold']}、"
            f"near_miss_threshold={minimal_selected_row['near_miss_threshold']}，adjustment_cost={minimal_selected_row['adjustment_cost']}。"
        )

    return {
        "report_dir": str(report_path),
        "trade_date": trade_date,
        "ticker": ticker,
        "source_bucket": source_bucket,
        "candidate_source": str(entry.get("candidate_source") or ""),
        "stored_short_trade_decision": str(stored_short_trade.get("decision") or ""),
        "variant_results": variant_results,
        "penalty_threshold_frontier": penalty_threshold_frontier,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze rescue variants for a structural-conflict short-trade candidate.")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--avoid-penalty-grid", default=None)
    parser.add_argument("--stale-score-penalty-grid", default=None)
    parser.add_argument("--extension-score-penalty-grid", default=None)
    parser.add_argument("--select-threshold-grid", default=None)
    parser.add_argument("--near-miss-threshold-grid", default=None)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    default_profile = get_short_trade_target_profile("default")
    analysis = analyze_structural_conflict_rescue(
        args.report_dir,
        args.trade_date,
        args.ticker,
        avoid_penalty_grid=_parse_float_grid(args.avoid_penalty_grid, default=[float(default_profile.layer_c_avoid_penalty)]),
        stale_score_penalty_grid=_parse_float_grid(args.stale_score_penalty_grid, default=[float(default_profile.stale_score_penalty_weight)]),
        extension_score_penalty_grid=_parse_float_grid(args.extension_score_penalty_grid, default=[float(default_profile.extension_score_penalty_weight)]),
        select_threshold_grid=_parse_float_grid(args.select_threshold_grid, default=[float(default_profile.select_threshold)]),
        near_miss_threshold_grid=_parse_float_grid(args.near_miss_threshold_grid, default=[float(default_profile.near_miss_threshold)]),
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_structural_conflict_rescue_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()