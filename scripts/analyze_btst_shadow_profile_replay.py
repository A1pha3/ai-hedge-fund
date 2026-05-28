from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.paper_trading.frozen_replay import replay_frozen_post_market_sequence


def _normalize_frozen_plan_sources(frozen_plan_source: str | Path | list[str | Path]) -> list[Path]:
    if isinstance(frozen_plan_source, (str, Path)):
        return [Path(frozen_plan_source).expanduser().resolve()]
    return [Path(source_path).expanduser().resolve() for source_path in list(frozen_plan_source or [])]


def _resolve_weekly_validation_sources(weekly_validation_json: str | Path) -> list[Path]:
    payload = json.loads(Path(weekly_validation_json).expanduser().resolve().read_text(encoding="utf-8"))
    source_paths: list[Path] = []
    for report in list(payload.get("selected_reports") or []):
        report_dir = Path(str(report.get("report_dir") or "")).expanduser().resolve()
        if not str(report_dir):
            continue
        daily_events_path = report_dir / "daily_events.jsonl"
        if daily_events_path.is_file():
            source_paths.append(daily_events_path)
    if not source_paths:
        raise ValueError(f"No replayable daily_events.jsonl files found in weekly validation manifest: {weekly_validation_json}")
    return source_paths


def _summarize_replayed_plans(plans: dict[str, Any], *, profile_name: str, profile_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    buy_order_tickers_by_date: dict[str, list[str]] = {}
    execution_eligible_tickers_by_date: dict[str, list[str]] = {}
    selected_tickers_by_date: dict[str, list[str]] = {}
    near_miss_tickers_by_date: dict[str, list[str]] = {}
    blocked_tickers_by_date: dict[str, list[str]] = {}
    rejected_tickers_by_date: dict[str, list[str]] = {}

    for trade_date in sorted(plans):
        plan = plans[trade_date]
        selection_targets = dict(getattr(plan, "selection_targets", {}) or {})
        buy_order_tickers_by_date[trade_date] = sorted(str(getattr(order, "ticker", "") or "").strip() for order in list(getattr(plan, "buy_orders", []) or []) if str(getattr(order, "ticker", "") or "").strip())
        execution_eligible_tickers_by_date[trade_date] = sorted(
            str(ticker)
            for ticker, evaluation in selection_targets.items()
            if bool(getattr(evaluation, "execution_eligible", False))
        )
        selected_tickers: list[str] = []
        near_miss_tickers: list[str] = []
        blocked_tickers: list[str] = []
        rejected_tickers: list[str] = []
        for ticker, evaluation in selection_targets.items():
            short_trade = getattr(evaluation, "short_trade", None)
            decision = str(getattr(short_trade, "decision", "") or "").strip()
            if decision == "selected":
                selected_tickers.append(str(ticker))
            elif decision == "near_miss":
                near_miss_tickers.append(str(ticker))
            elif decision == "blocked":
                blocked_tickers.append(str(ticker))
            elif decision == "rejected":
                rejected_tickers.append(str(ticker))
        selected_tickers_by_date[trade_date] = sorted(selected_tickers)
        near_miss_tickers_by_date[trade_date] = sorted(near_miss_tickers)
        blocked_tickers_by_date[trade_date] = sorted(blocked_tickers)
        rejected_tickers_by_date[trade_date] = sorted(rejected_tickers)

    return {
        "profile_name": profile_name,
        "profile_overrides": dict(profile_overrides or {}),
        "trade_dates": sorted(plans),
        "buy_order_tickers_by_date": buy_order_tickers_by_date,
        "execution_eligible_tickers_by_date": execution_eligible_tickers_by_date,
        "selected_tickers_by_date": selected_tickers_by_date,
        "near_miss_tickers_by_date": near_miss_tickers_by_date,
        "blocked_tickers_by_date": blocked_tickers_by_date,
        "rejected_tickers_by_date": rejected_tickers_by_date,
        "aggregate_counts": {
            "buy_order_count": sum(len(values) for values in buy_order_tickers_by_date.values()),
            "execution_eligible_count": sum(len(values) for values in execution_eligible_tickers_by_date.values()),
            "selected_count": sum(len(values) for values in selected_tickers_by_date.values()),
            "near_miss_count": sum(len(values) for values in near_miss_tickers_by_date.values()),
            "blocked_count": sum(len(values) for values in blocked_tickers_by_date.values()),
            "rejected_count": sum(len(values) for values in rejected_tickers_by_date.values()),
        },
    }


def _build_delta_summary(baseline: dict[str, Any], shadow: dict[str, Any]) -> dict[str, Any]:
    trade_dates = sorted(set(baseline["trade_dates"]) | set(shadow["trade_dates"]))
    buy_orders_removed_by_date: dict[str, list[str]] = {}
    execution_eligibility_lost_by_date: dict[str, list[str]] = {}
    selected_removed_by_date: dict[str, list[str]] = {}
    for trade_date in trade_dates:
        baseline_buy_orders = set(baseline["buy_order_tickers_by_date"].get(trade_date, []))
        shadow_buy_orders = set(shadow["buy_order_tickers_by_date"].get(trade_date, []))
        removed_buy_orders = sorted(baseline_buy_orders - shadow_buy_orders)
        if removed_buy_orders:
            buy_orders_removed_by_date[trade_date] = removed_buy_orders

        baseline_execution_eligible = set(baseline["execution_eligible_tickers_by_date"].get(trade_date, []))
        shadow_execution_eligible = set(shadow["execution_eligible_tickers_by_date"].get(trade_date, []))
        lost_execution_eligibility = sorted(baseline_execution_eligible - shadow_execution_eligible)
        if lost_execution_eligibility:
            execution_eligibility_lost_by_date[trade_date] = lost_execution_eligibility

        baseline_selected = set(baseline["selected_tickers_by_date"].get(trade_date, []))
        shadow_selected = set(shadow["selected_tickers_by_date"].get(trade_date, []))
        removed_selected = sorted(baseline_selected - shadow_selected)
        if removed_selected:
            selected_removed_by_date[trade_date] = removed_selected

    return {
        "buy_orders_removed_by_date": buy_orders_removed_by_date,
        "execution_eligibility_lost_by_date": execution_eligibility_lost_by_date,
        "selected_removed_by_date": selected_removed_by_date,
        "aggregate_count_delta": {
            key: int(shadow["aggregate_counts"].get(key, 0)) - int(baseline["aggregate_counts"].get(key, 0))
            for key in baseline["aggregate_counts"]
        },
    }


def render_btst_shadow_profile_replay_markdown(analysis: dict[str, Any]) -> str:
    frozen_sources = analysis["frozen_plan_source"]
    frozen_source_display = ", ".join(f"`{source}`" for source in frozen_sources) if isinstance(frozen_sources, list) else f"`{frozen_sources}`"
    lines = [
        "# BTST Shadow Profile Frozen Replay",
        "",
        f"- Frozen source: {frozen_source_display}",
        f"- Baseline profile: `{analysis['baseline']['profile_name']}`",
        f"- Baseline overrides: `{json.dumps(analysis['baseline'].get('profile_overrides', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- Shadow profile: `{analysis['shadow']['profile_name']}`",
        f"- Shadow overrides: `{json.dumps(analysis['shadow'].get('profile_overrides', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- Trade dates: {', '.join(analysis['trade_dates']) or 'N/A'}",
        "",
        "## Aggregate delta",
        "",
        "| Metric | Baseline | Shadow | Delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key, baseline_value in analysis["baseline"]["aggregate_counts"].items():
        shadow_value = int(analysis["shadow"]["aggregate_counts"].get(key, 0))
        delta = int(analysis["delta"]["aggregate_count_delta"].get(key, 0))
        lines.append(f"| {key} | {int(baseline_value)} | {shadow_value} | {delta} |")
    lines.extend(["", "## Per-date removals", ""])
    for trade_date in analysis["trade_dates"]:
        removed_buy_orders = analysis["delta"]["buy_orders_removed_by_date"].get(trade_date, [])
        lost_execution_eligibility = analysis["delta"]["execution_eligibility_lost_by_date"].get(trade_date, [])
        lines.append(f"### {trade_date}")
        lines.append(f"- Removed buy orders: {', '.join(removed_buy_orders) if removed_buy_orders else 'none'}")
        lines.append(f"- Lost execution eligibility: {', '.join(lost_execution_eligibility) if lost_execution_eligibility else 'none'}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def analyze_btst_shadow_profile_replay(
    *,
    frozen_plan_source: str | Path | list[str | Path] | None = None,
    weekly_validation_json: str | Path | None = None,
    baseline_profile: str = "btst_precision_v2",
    baseline_profile_overrides: dict[str, Any] | None = None,
    shadow_profile: str = "btst_precision_v2_layer_c_watchlist_shadow",
    shadow_profile_overrides: dict[str, Any] | None = None,
    output_json_path: str | Path | None = None,
    output_markdown_path: str | Path | None = None,
    target_mode: str = "short_trade_only",
    base_model_name: str = "gpt-4.1",
    base_model_provider: str = "OpenAI",
    clear_existing_buy_orders: bool = True,
) -> dict[str, Any]:
    if weekly_validation_json is not None:
        source_paths = _resolve_weekly_validation_sources(weekly_validation_json)
    elif frozen_plan_source is not None:
        source_paths = _normalize_frozen_plan_sources(frozen_plan_source)
    else:
        raise ValueError("Either frozen_plan_source or weekly_validation_json is required")
    baseline_plans: dict[str, Any] = {}
    shadow_plans: dict[str, Any] = {}
    for source_path in source_paths:
        baseline_plans.update(
            replay_frozen_post_market_sequence(
                source_path,
                target_mode=target_mode,
                base_model_name=base_model_name,
                base_model_provider=base_model_provider,
                short_trade_target_profile_name=baseline_profile,
                short_trade_target_profile_overrides=dict(baseline_profile_overrides or {}),
                clear_existing_buy_orders=clear_existing_buy_orders,
            )
        )
        shadow_plans.update(
            replay_frozen_post_market_sequence(
                source_path,
                target_mode=target_mode,
                base_model_name=base_model_name,
                base_model_provider=base_model_provider,
                short_trade_target_profile_name=shadow_profile,
                short_trade_target_profile_overrides=dict(shadow_profile_overrides or {}),
                clear_existing_buy_orders=clear_existing_buy_orders,
            )
        )
    baseline_summary = _summarize_replayed_plans(
        baseline_plans,
        profile_name=baseline_profile,
        profile_overrides=baseline_profile_overrides,
    )
    shadow_summary = _summarize_replayed_plans(
        shadow_plans,
        profile_name=shadow_profile,
        profile_overrides=shadow_profile_overrides,
    )
    analysis = {
        "frozen_plan_source": [str(source_path) for source_path in source_paths],
        "trade_dates": sorted(set(baseline_summary["trade_dates"]) | set(shadow_summary["trade_dates"])),
        "baseline": baseline_summary,
        "shadow": shadow_summary,
        "delta": _build_delta_summary(baseline_summary, shadow_summary),
    }
    if output_json_path is not None:
        json_path = Path(output_json_path)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if output_markdown_path is not None:
        markdown_path = Path(output_markdown_path)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_btst_shadow_profile_replay_markdown(analysis), encoding="utf-8")
    return analysis


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare BTST baseline vs shadow profiles on a frozen replay source.")
    parser.add_argument("--frozen-plan-source", nargs="+", help="One or more daily_events.jsonl paths containing current_plan records")
    parser.add_argument("--weekly-validation-json", default=None, help="Optional btst_weekly_validation JSON used to resolve daily_events sources from selected_reports")
    parser.add_argument("--baseline-profile", default="btst_precision_v2", help="Baseline short-trade target profile")
    parser.add_argument("--baseline-overrides", default="{}", help="JSON object of baseline profile overrides")
    parser.add_argument("--shadow-profile", default="btst_precision_v2_layer_c_watchlist_shadow", help="Shadow short-trade target profile")
    parser.add_argument("--shadow-overrides", default="{}", help="JSON object of shadow profile overrides")
    parser.add_argument("--output-json", default=None, help="Optional JSON output path")
    parser.add_argument("--output-markdown", default=None, help="Optional Markdown output path")
    parser.add_argument("--target-mode", default="short_trade_only", help="Replay target mode")
    parser.add_argument("--base-model-name", default="gpt-4.1", help="Pipeline base model name for frozen replay")
    parser.add_argument("--base-model-provider", default="OpenAI", help="Pipeline base model provider for frozen replay")
    parser.add_argument("--keep-existing-buy-orders", action="store_true", help="Preserve buy_orders embedded in frozen plans instead of rebuilding from profile-driven replay")
    return parser.parse_args()


def _parse_profile_overrides(raw_value: str) -> dict[str, Any]:
    parsed = json.loads(raw_value or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("Profile overrides must be a JSON object")
    return parsed


def main() -> None:
    args = _parse_args()
    analysis = analyze_btst_shadow_profile_replay(
        frozen_plan_source=args.frozen_plan_source,
        weekly_validation_json=args.weekly_validation_json,
        baseline_profile=args.baseline_profile,
        baseline_profile_overrides=_parse_profile_overrides(args.baseline_overrides),
        shadow_profile=args.shadow_profile,
        shadow_profile_overrides=_parse_profile_overrides(args.shadow_overrides),
        output_json_path=args.output_json,
        output_markdown_path=args.output_markdown,
        target_mode=args.target_mode,
        base_model_name=args.base_model_name,
        base_model_provider=args.base_model_provider,
        clear_existing_buy_orders=not args.keep_existing_buy_orders,
    )
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
