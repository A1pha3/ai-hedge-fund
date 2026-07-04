from __future__ import annotations

import argparse
import json
from collections import defaultdict
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
        execution_eligible_tickers_by_date[trade_date] = sorted(str(ticker) for ticker, evaluation in selection_targets.items() if bool(getattr(evaluation, "execution_eligible", False)))
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


def _trade_date_selection_artifact_folder(trade_date: str) -> str:
    raw = str(trade_date or "").strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


def _load_selection_target_replay_input(source_paths: list[Path], *, trade_date: str) -> Any | None:
    date_folder = _trade_date_selection_artifact_folder(trade_date)
    if not date_folder:
        return None
    for source_path in list(source_paths or []):
        replay_path = source_path.parent / "selection_artifacts" / date_folder / "selection_target_replay_input.json"
        if replay_path.is_file():
            return json.loads(replay_path.read_text(encoding="utf-8"))
    return None


def _scan_ticker_candidate_source_hits(payload: Any, *, tickers: set[str]) -> dict[str, Any]:
    if not tickers:
        return {}

    total_hits: dict[str, int] = {ticker: 0 for ticker in tickers}
    source_counts: dict[str, dict[str, int]] = {ticker: defaultdict(int) for ticker in tickers}

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            ticker = obj.get("ticker")
            if ticker is None:
                ticker = obj.get("symbol")
            ticker_str = str(ticker) if ticker is not None else ""
            if ticker_str in tickers:
                total_hits[ticker_str] = int(total_hits.get(ticker_str, 0)) + 1
                candidate_source = str(obj.get("candidate_source") or "").strip()
                if candidate_source:
                    source_counts[ticker_str][candidate_source] += 1
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(payload)

    result: dict[str, Any] = {}
    for ticker in sorted(tickers):
        total = int(total_hits.get(ticker, 0))
        if total <= 0:
            continue
        counts = dict(source_counts.get(ticker, {}))
        result[ticker] = {
            "total_hits": total,
            "candidate_source_counts": {key: int(value) for key, value in sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0]))) if str(key).strip()},
        }
    return result


def _extract_removed_ticker_evaluation_snapshot(plan: Any, *, ticker: str) -> dict[str, Any] | None:
    selection_targets = dict(getattr(plan, "selection_targets", {}) or {})
    evaluation = selection_targets.get(ticker)
    if evaluation is None:
        return None
    short_trade = getattr(evaluation, "short_trade", None)
    return {
        "evaluation_candidate_source": str(getattr(evaluation, "candidate_source", "") or "") or None,
        "execution_eligible": bool(getattr(evaluation, "execution_eligible", False)),
        "short_trade": {
            "decision": str(getattr(short_trade, "decision", "") or "") or None,
            "candidate_source": str(getattr(short_trade, "candidate_source", "") or "") or None,
            "score_target": float(getattr(short_trade, "score_target", 0.0) or 0.0),
            "confidence": float(getattr(short_trade, "confidence", 0.0) or 0.0),
            "downgrade_reasons": list(getattr(short_trade, "downgrade_reasons", []) or []),
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
        "aggregate_count_delta": {key: int(shadow["aggregate_counts"].get(key, 0)) - int(baseline["aggregate_counts"].get(key, 0)) for key in baseline["aggregate_counts"]},
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

        delta = analysis.get("delta") or {}
        removed_hits = dict(delta.get("removed_ticker_source_hits_by_date", {}).get(trade_date, {}) or {})
        if removed_hits:
            payload_source = str(dict(delta.get("removed_ticker_source_hits_payload_source_by_date", {}) or {}).get(trade_date, "unknown"))
            lines.append(f"- Removed ticker candidate_source hits (source: {payload_source}):")
            for ticker in sorted(removed_hits):
                payload = dict(removed_hits.get(ticker) or {})
                total = int(payload.get("total_hits") or 0)
                counts = dict(payload.get("candidate_source_counts") or {})
                layer_c_hits = int(counts.get("layer_c_watchlist") or 0)
                top = ", ".join(f"{key}={value}" for key, value in list(counts.items())[:3])
                lines.append(f"  - {ticker}: layer_c_watchlist {layer_c_hits}/{total}{('; top: ' + top) if top else ''}")

        eval_by_ticker = dict(delta.get("removed_ticker_eval_snapshot_by_date", {}).get(trade_date, {}) or {})
        if eval_by_ticker:
            lines.append("- Removed ticker evaluation snapshot (baseline vs shadow):")
            for ticker in sorted(eval_by_ticker):
                payload = dict(eval_by_ticker.get(ticker) or {})
                baseline = dict(payload.get("baseline") or {})
                shadow = dict(payload.get("shadow") or {})

                def _render_side(side: dict[str, Any]) -> str:
                    if not side:
                        return "N/A"
                    short_trade = dict(side.get("short_trade") or {})
                    decision = str(short_trade.get("decision") or "") or "N/A"
                    execution_eligible = "Y" if bool(side.get("execution_eligible")) else "N"
                    source = str(short_trade.get("candidate_source") or side.get("evaluation_candidate_source") or "") or "N/A"
                    score = short_trade.get("score_target")
                    score_display = f"{float(score):.4f}" if score is not None else "N/A"
                    return f"decision={decision} exec={execution_eligible} score={score_display} src={source}"

                lines.append(f"  - {ticker}: baseline({_render_side(baseline)}) | shadow({_render_side(shadow)})")

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

    removed_ticker_source_hits_by_date: dict[str, Any] = {}
    removed_ticker_source_hits_payload_source_by_date: dict[str, str] = {}
    removed_ticker_eval_snapshot_by_date: dict[str, Any] = {}

    for trade_date in analysis["trade_dates"]:
        delta = dict(analysis.get("delta") or {})
        removed_tickers = set(delta.get("buy_orders_removed_by_date", {}).get(trade_date, []) or [])
        removed_tickers |= set(delta.get("execution_eligibility_lost_by_date", {}).get(trade_date, []) or [])
        removed_tickers |= set(delta.get("selected_removed_by_date", {}).get(trade_date, []) or [])
        if not removed_tickers:
            continue

        baseline_plan = baseline_plans.get(trade_date)
        shadow_plan = shadow_plans.get(trade_date)
        eval_snapshots: dict[str, Any] = {}
        for ticker in sorted(removed_tickers):
            baseline_snapshot = _extract_removed_ticker_evaluation_snapshot(baseline_plan, ticker=ticker) if baseline_plan is not None else None
            shadow_snapshot = _extract_removed_ticker_evaluation_snapshot(shadow_plan, ticker=ticker) if shadow_plan is not None else None
            if baseline_snapshot is None and shadow_snapshot is None:
                continue
            eval_snapshots[ticker] = {
                "baseline": baseline_snapshot,
                "shadow": shadow_snapshot,
            }
        if eval_snapshots:
            removed_ticker_eval_snapshot_by_date[trade_date] = eval_snapshots

        payload_source = "selection_target_replay_input"
        attribution_payload = _load_selection_target_replay_input(source_paths, trade_date=trade_date)
        if attribution_payload is None:
            payload_source = "replayed_plan_payload"
            fallback_plan = baseline_plans.get(trade_date) or shadow_plans.get(trade_date)
            if fallback_plan is None:
                continue
            attribution_payload = fallback_plan.model_dump(mode="json")

        hits = _scan_ticker_candidate_source_hits(attribution_payload, tickers=removed_tickers)
        if hits:
            removed_ticker_source_hits_by_date[trade_date] = hits
            removed_ticker_source_hits_payload_source_by_date[trade_date] = payload_source

    if removed_ticker_source_hits_by_date:
        analysis["delta"]["removed_ticker_source_hits_by_date"] = removed_ticker_source_hits_by_date
        analysis["delta"]["removed_ticker_source_hits_payload_source_by_date"] = removed_ticker_source_hits_payload_source_by_date

    if removed_ticker_eval_snapshot_by_date:
        analysis["delta"]["removed_ticker_eval_snapshot_by_date"] = removed_ticker_eval_snapshot_by_date
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
