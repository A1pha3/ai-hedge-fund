from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from scripts.btst_report_utils import discover_report_dirs, normalize_trade_date, safe_load_json
from scripts.generate_reports_manifest import generate_reports_manifest_artifacts
from scripts.run_btst_nightly_control_tower import generate_btst_nightly_control_tower_artifacts
from scripts.btst_latest_followup_utils import load_btst_followup_by_ticker_for_report, load_latest_btst_followup_by_ticker
from src.execution.daily_pipeline import _build_upstream_shadow_catalyst_relief_config
from src.execution.models import ExecutionPlan
from src.paper_trading.btst_reporting import generate_and_register_btst_followup_artifacts
from src.paper_trading.frozen_replay import load_frozen_post_market_plans
from src.research.artifacts import FileSelectionArtifactWriter
from src.targets.router import build_selection_targets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh selection_artifacts from historical daily_events current_plan records using current target rules.")
    parser.add_argument("input_paths", nargs="+", help="One or more paper trading report directories or report roots")
    parser.add_argument("--trade-date", default=None, help="Optional trade date in YYYY-MM-DD or YYYYMMDD format")
    parser.add_argument("--report-name-contains", default="paper_trading", help="When scanning a root directory, only include report directories whose names contain this fragment")
    parser.add_argument("--refresh-followup", action="store_true", help="Regenerate BTST followup artifacts after refreshing selection_artifacts")
    parser.add_argument("--refresh-manifest", action="store_true", help="Regenerate report_manifest_latest.json after refreshing")
    parser.add_argument("--refresh-control-tower", action="store_true", help="Regenerate btst_nightly_control_tower_latest.json after refreshing")
    return parser.parse_args()


def _normalize_trade_date_compact(value: str | None) -> str | None:
    digits = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
    return digits if len(digits) == 8 else None


def _load_artifact_metadata(report_dir: Path, trade_date_compact: str) -> tuple[dict[str, Any], list[str], Any]:
    trade_date = normalize_trade_date(trade_date_compact)
    snapshot_path = report_dir / "selection_artifacts" / str(trade_date or "") / "selection_snapshot.json"
    snapshot = safe_load_json(snapshot_path)
    pipeline_config_snapshot = dict(snapshot.get("pipeline_config_snapshot") or {})
    selected_analysts = [str(item) for item in list(pipeline_config_snapshot.get("selected_analysts") or []) if str(item or "").strip()]
    pipeline_stub = SimpleNamespace(
        base_model_provider=str(pipeline_config_snapshot.get("model_provider") or ""),
        base_model_name=str(pipeline_config_snapshot.get("model_name") or ""),
        frozen_post_market_plans=True,
        frozen_plan_source=str((report_dir / "daily_events.jsonl").resolve()),
    )
    metadata = {
        "run_id": str(snapshot.get("run_id") or report_dir.name),
        "experiment_id": snapshot.get("experiment_id"),
        "market": str(snapshot.get("market") or "CN"),
        "artifact_version": str(snapshot.get("artifact_version") or "v1"),
    }
    return metadata, selected_analysts, pipeline_stub


def _load_raw_current_plans(daily_events_path: Path) -> dict[str, dict[str, Any]]:
    raw_plans: dict[str, dict[str, Any]] = {}
    for raw_line in daily_events_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        payload = json.loads(raw_line)
        if str(payload.get("event") or "") != "paper_trading_day":
            continue
        trade_date_compact = _normalize_trade_date_compact(payload.get("trade_date"))
        current_plan = payload.get("current_plan")
        if trade_date_compact and isinstance(current_plan, dict):
            raw_plans[trade_date_compact] = dict(current_plan)
    return raw_plans


def _build_candidate_pool_shadow_lookup(raw_current_plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    risk_metrics = dict(raw_current_plan.get("risk_metrics") or {})
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics") or {})
    filters = dict(funnel_diagnostics.get("filters") or {})
    candidate_pool_shadow = dict(filters.get("candidate_pool_shadow") or raw_current_plan.get("candidate_pool_shadow") or {})
    lookup: dict[str, dict[str, Any]] = {}
    for raw_entry in list(candidate_pool_shadow.get("tickers") or []):
        entry = dict(raw_entry or {})
        ticker = str(entry.get("ticker") or "").strip()
        if ticker:
            lookup[ticker] = entry
    return lookup


def _merge_shadow_metadata(entry: dict[str, Any], shadow_lookup: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ticker = str(entry.get("ticker") or "").strip()
    shadow_entry = dict(shadow_lookup.get(ticker) or {})
    if not shadow_entry:
        return entry
    merged = dict(entry)
    for key in (
        "candidate_pool_shadow_reason",
        "shadow_visibility_gap_selected",
        "shadow_visibility_gap_relaxed_band",
        "candidate_pool_rank",
        "candidate_pool_avg_amount_share_of_cutoff",
        "candidate_pool_avg_amount_share_of_min_gate",
    ):
        if key not in merged or merged.get(key) in ("", None, False):
            value = shadow_entry.get(key)
            if value not in ("", None):
                merged[key] = value
    return merged


def _refresh_released_shadow_entries(filters: dict[str, Any], filter_key: str, shadow_lookup: dict[str, dict[str, Any]]) -> None:
    filter_payload = dict(filters.get(filter_key) or {})
    refreshed_entries: list[dict[str, Any]] = []
    for raw_entry in list(filter_payload.get("released_shadow_entries") or []):
        entry = _merge_shadow_metadata(dict(raw_entry or {}), shadow_lookup)
        existing_relief = dict(entry.get("short_trade_catalyst_relief") or {})
        relief = _build_upstream_shadow_catalyst_relief_config(
            candidate_pool_lane=str(entry.get("candidate_pool_lane") or ""),
            filter_reason=str(entry.get("shadow_release_filter_reason") or ""),
            metrics_payload=dict(entry.get("short_trade_boundary_metrics") or {}),
            shadow_visibility_gap_selected=bool(entry.get("shadow_visibility_gap_selected")),
        )
        merged_relief = {**existing_relief, **relief} if relief else existing_relief
        if merged_relief:
            entry["short_trade_catalyst_relief"] = merged_relief
        refreshed_entries.append(entry)
    filter_payload["released_shadow_entries"] = refreshed_entries
    filters[filter_key] = filter_payload


def _load_latest_historical_prior_by_ticker(report_dir: Path) -> dict[str, dict[str, Any]]:
    rows_by_ticker = load_btst_followup_by_ticker_for_report(report_dir)
    if not rows_by_ticker:
        rows_by_ticker = load_latest_btst_followup_by_ticker(report_dir.parent)
    return {
        ticker: dict(row.get("historical_prior") or {})
        for ticker, row in rows_by_ticker.items()
        if dict(row.get("historical_prior") or {})
    }


def _attach_historical_prior_to_entries(entries: list[dict[str, Any]], *, prior_by_ticker: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    attached_entries: list[dict[str, Any]] = []
    for entry in entries:
        updated_entry = dict(entry or {})
        ticker = str(updated_entry.get("ticker") or "").strip()
        historical_prior = dict(updated_entry.get("historical_prior") or prior_by_ticker.get(ticker) or {})
        if historical_prior:
            updated_entry["historical_prior"] = historical_prior
        attached_entries.append(updated_entry)
    return attached_entries


def rebuild_selection_targets_for_plan(
    plan: ExecutionPlan,
    trade_date_compact: str,
    shadow_lookup: dict[str, dict[str, Any]] | None = None,
    *,
    historical_prior_by_ticker: dict[str, dict[str, Any]] | None = None,
) -> ExecutionPlan:
    risk_metrics = dict(plan.risk_metrics or {})
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics") or {})
    filters = dict(funnel_diagnostics.get("filters") or {})
    shadow_lookup = dict(shadow_lookup or {})
    historical_prior_by_ticker = dict(historical_prior_by_ticker or {})

    _refresh_released_shadow_entries(filters, "short_trade_candidates", shadow_lookup)
    _refresh_released_shadow_entries(filters, "watchlist", shadow_lookup)

    short_trade_candidate_filters = dict(filters.get("short_trade_candidates") or {})
    watchlist_filter = dict(filters.get("watchlist") or {})
    refreshed_rejected_entries = _attach_historical_prior_to_entries(
        list(watchlist_filter.get("tickers") or []),
        prior_by_ticker=historical_prior_by_ticker,
    )
    refreshed_short_trade_tickers = _attach_historical_prior_to_entries(
        list(short_trade_candidate_filters.get("tickers") or []),
        prior_by_ticker=historical_prior_by_ticker,
    )
    refreshed_short_trade_released_shadow_entries = _attach_historical_prior_to_entries(
        list(short_trade_candidate_filters.get("released_shadow_entries") or []),
        prior_by_ticker=historical_prior_by_ticker,
    )
    refreshed_watchlist_released_shadow_entries = _attach_historical_prior_to_entries(
        list(watchlist_filter.get("released_shadow_entries") or []),
        prior_by_ticker=historical_prior_by_ticker,
    )
    selection_targets, dual_target_summary = build_selection_targets(
        trade_date=trade_date_compact,
        watchlist=list(plan.watchlist or []),
        rejected_entries=refreshed_rejected_entries,
        supplemental_short_trade_entries=[
            *refreshed_short_trade_tickers,
            *refreshed_short_trade_released_shadow_entries,
            *refreshed_watchlist_released_shadow_entries,
        ],
        buy_order_tickers={str(order.ticker) for order in list(plan.buy_orders or [])},
        target_mode=str(getattr(plan, "target_mode", "research_only") or "research_only"),
    )

    watchlist_filter["tickers"] = refreshed_rejected_entries
    watchlist_filter["released_shadow_entries"] = refreshed_watchlist_released_shadow_entries
    short_trade_candidate_filters["tickers"] = refreshed_short_trade_tickers
    short_trade_candidate_filters["released_shadow_entries"] = refreshed_short_trade_released_shadow_entries
    filters["watchlist"] = watchlist_filter
    filters["short_trade_candidates"] = short_trade_candidate_filters
    funnel_diagnostics["filters"] = filters
    risk_metrics["funnel_diagnostics"] = funnel_diagnostics
    plan.risk_metrics = risk_metrics
    plan.selection_targets = selection_targets
    plan.dual_target_summary = dual_target_summary
    return plan


def refresh_selection_artifacts_for_report(report_dir: str | Path, trade_date: str | None = None) -> dict[str, Any]:
    resolved_report_dir = Path(report_dir).expanduser().resolve()
    daily_events_path = resolved_report_dir / "daily_events.jsonl"
    plans_by_date = load_frozen_post_market_plans(daily_events_path)
    raw_plans_by_date = _load_raw_current_plans(daily_events_path)
    requested_trade_date = _normalize_trade_date_compact(trade_date)
    target_trade_dates = [requested_trade_date] if requested_trade_date else sorted(plans_by_date.keys())
    if requested_trade_date and requested_trade_date not in plans_by_date:
        raise ValueError(f"Missing current_plan in daily_events for trade_date={requested_trade_date}")

    refreshed_results: list[dict[str, Any]] = []
    for trade_date_compact in target_trade_dates:
        plan = ExecutionPlan.model_validate(plans_by_date[trade_date_compact].model_dump(mode="json"))
        shadow_lookup = _build_candidate_pool_shadow_lookup(raw_plans_by_date.get(trade_date_compact) or {})
        refreshed_plan = rebuild_selection_targets_for_plan(
            plan,
            trade_date_compact,
            shadow_lookup,
            historical_prior_by_ticker=_load_latest_historical_prior_by_ticker(resolved_report_dir),
        )
        metadata, selected_analysts, pipeline_stub = _load_artifact_metadata(resolved_report_dir, trade_date_compact)
        writer = FileSelectionArtifactWriter(
            artifact_root=resolved_report_dir / "selection_artifacts",
            run_id=str(metadata["run_id"]),
            experiment_id=metadata["experiment_id"],
            market=str(metadata["market"]),
            artifact_version=str(metadata["artifact_version"]),
        )
        write_result = writer.write_for_plan(
            plan=refreshed_plan,
            trade_date=trade_date_compact,
            pipeline=pipeline_stub,
            selected_analysts=selected_analysts,
        )
        trade_date_display = normalize_trade_date(trade_date_compact) or trade_date_compact
        refreshed_results.append(
            {
                "trade_date": trade_date_display,
                "snapshot_path": write_result.snapshot_path,
                "replay_input_path": write_result.replay_input_path,
                "write_status": write_result.write_status,
                "selection_target_count": len(refreshed_plan.selection_targets),
                "short_trade_selected_symbols": list(refreshed_plan.dual_target_summary.short_trade_selected_count and sorted(
                    ticker
                    for ticker, evaluation in refreshed_plan.selection_targets.items()
                    if getattr(getattr(evaluation, "short_trade", None), "decision", "") == "selected"
                ) or []),
            }
        )

    session_summary_path = resolved_report_dir / "session_summary.json"
    session_summary = safe_load_json(session_summary_path)
    session_summary["selection_artifact_refresh"] = {
        "refreshed_trade_dates": [row["trade_date"] for row in refreshed_results],
        "result_count": len(refreshed_results),
        "source": str(daily_events_path),
    }
    session_summary_path.write_text(json.dumps(session_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "report_dir": str(resolved_report_dir),
        "daily_events_path": str(daily_events_path),
        "results": refreshed_results,
    }


def main() -> None:
    args = parse_args()
    report_dirs: list[Path] = []
    for raw_input in args.input_paths:
        report_dirs.extend(discover_report_dirs(raw_input, report_name_contains=args.report_name_contains))

    seen: set[Path] = set()
    unique_report_dirs = [path for path in report_dirs if not (path in seen or seen.add(path))]
    if not unique_report_dirs:
        raise SystemExit("No report directories found for selection artifact refresh.")

    reports_roots_to_refresh_manifest: set[Path] = set()
    reports_roots_to_refresh_control_tower: set[Path] = set()
    for report_dir in unique_report_dirs:
        result = refresh_selection_artifacts_for_report(report_dir, trade_date=args.trade_date)
        print(f"report_dir={result['report_dir']}")
        print(f"daily_events_path={result['daily_events_path']}")
        for trade_result in result["results"]:
            print(f"trade_date={trade_result['trade_date']}")
            print(f"write_status={trade_result['write_status']}")
            print(f"snapshot_path={trade_result['snapshot_path']}")
            print(f"replay_input_path={trade_result['replay_input_path']}")
            print(f"short_trade_selected_symbols={','.join(trade_result['short_trade_selected_symbols'])}")
            if args.refresh_followup:
                followup = generate_and_register_btst_followup_artifacts(
                    report_dir=report_dir,
                    trade_date=trade_result["trade_date"],
                )
                print(f"btst_brief_json={followup['brief_json']}")
                print(f"btst_execution_card_json={followup['execution_card_json']}")
        reports_root = report_dir.parent
        if reports_root.name == "reports":
            if args.refresh_manifest:
                reports_roots_to_refresh_manifest.add(reports_root)
            if args.refresh_control_tower:
                reports_roots_to_refresh_control_tower.add(reports_root)

    for reports_root in sorted(reports_roots_to_refresh_manifest):
        manifest = generate_reports_manifest_artifacts(reports_root=reports_root)
        print(f"manifest_json={manifest['json_path']}")

    for reports_root in sorted(reports_roots_to_refresh_control_tower):
        control_tower = generate_btst_nightly_control_tower_artifacts(reports_root=reports_root)
        print(f"nightly_control_tower_json={control_tower['json_path']}")


if __name__ == "__main__":
    main()
