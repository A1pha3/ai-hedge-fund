from __future__ import annotations

import argparse
import importlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


AUTO_SHADOW_RECALL_MIN_STRICT_GOAL_CASES = int(os.getenv("AUTO_SHADOW_RECALL_MIN_STRICT_GOAL_CASES", "2"))
AUTO_SHADOW_CORRIDOR_MIN_GATE_SHARE = float(os.getenv("AUTO_SHADOW_CORRIDOR_MIN_GATE_SHARE", "2.25"))
AUTO_SHADOW_CORRIDOR_MAX_CUTOFF_SHARE = float(os.getenv("AUTO_SHADOW_CORRIDOR_MAX_CUTOFF_SHARE", "0.15"))
AUTO_SHADOW_REBUCKET_MIN_GATE_SHARE = float(os.getenv("AUTO_SHADOW_REBUCKET_MIN_GATE_SHARE", "5.0"))
AUTO_SHADOW_RECALL_MAX_CLOSEST_PRE_TRUNCATION_GAP = int(os.getenv("AUTO_SHADOW_RECALL_MAX_CLOSEST_PRE_TRUNCATION_GAP", "1200"))
AUTO_SHADOW_FOLLOWUP_MIN_NEXT_CLOSE_POSITIVE_RATE = float(os.getenv("AUTO_SHADOW_FOLLOWUP_MIN_NEXT_CLOSE_POSITIVE_RATE", "0.5"))


def _default_output_dir(start_date: str, end_date: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("data/reports") / f"paper_trading_{start_date}_{end_date}_{timestamp}"


def generate_btst_followup_artifacts(report_dir: Path, trade_date: str, next_trade_date: str | None = None) -> dict[str, str] | None:
    refresh_reports_manifest(report_dir)
    btst_reporting_module = importlib.import_module("src.paper_trading.btst_reporting")
    result = btst_reporting_module.generate_and_register_btst_followup_artifacts(
        report_dir=report_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
    )
    return {
        "brief_json": result["brief_json"],
        "brief_markdown": result["brief_markdown"],
        "card_json": result["execution_card_json"],
        "card_markdown": result["execution_card_markdown"],
        "opening_card_json": result["opening_watch_card_json"],
        "opening_card_markdown": result["opening_watch_card_markdown"],
        "priority_board_json": result["priority_board_json"],
        "priority_board_markdown": result["priority_board_markdown"],
    }


def refresh_reports_manifest(report_dir: Path) -> dict[str, str] | None:
    resolved_report_dir = report_dir.expanduser().resolve()
    reports_root = resolved_report_dir.parent
    if reports_root.name != "reports":
        return None
    manifest_module = importlib.import_module("scripts.generate_reports_manifest")
    result = manifest_module.generate_reports_manifest_artifacts(reports_root=reports_root)
    return {
        "manifest_json": result["json_path"],
        "manifest_markdown": result["markdown_path"],
    }


def refresh_btst_nightly_control_tower(report_dir: Path) -> dict[str, str] | None:
    resolved_report_dir = report_dir.expanduser().resolve()
    reports_root = resolved_report_dir.parent
    if reports_root.name != "reports":
        return None
    control_tower_module = importlib.import_module("scripts.run_btst_nightly_control_tower")
    result = control_tower_module.generate_btst_nightly_control_tower_artifacts(reports_root=reports_root)
    return {
        "open_ready_delta_json": result["delta_json_path"],
        "open_ready_delta_markdown": result["delta_markdown_path"],
        "nightly_control_tower_json": result["json_path"],
        "nightly_control_tower_markdown": result["markdown_path"],
        "catalyst_theme_frontier_json": result.get("catalyst_theme_frontier_json"),
        "catalyst_theme_frontier_markdown": result.get("catalyst_theme_frontier_markdown"),
        "manifest_json": result["manifest_json"],
        "manifest_markdown": result["manifest_markdown"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a paper-trading session using the existing pipeline mode engine.")
    parser.add_argument("--start-date", required=True, help="Start date in YYYY-MM-DD format")
    parser.add_argument("--end-date", required=True, help="End date in YYYY-MM-DD format")
    parser.add_argument("--tickers", default="", help="Optional comma-separated tracking tickers")
    parser.add_argument("--initial-capital", type=float, default=100000.0)
    parser.add_argument("--model-name", default=None, help="Model name override; omitted means use the primary route detected from .env")
    parser.add_argument("--model-provider", default=None, help="Model provider override; omitted means use the primary route detected from .env")
    parser.add_argument(
        "--selection-target",
        default="research_only",
        choices=["research_only", "short_trade_only", "dual_target"],
        help="Selection target mode for the underlying daily pipeline",
    )
    parser.add_argument("--output-dir", default=None, help="Directory for daily events, timing logs, and session summary")
    parser.add_argument("--frozen-plan-source", default=None, help="Path to a historical daily_events.jsonl file whose current_plan records will be replayed")
    parser.add_argument("--cache-benchmark", action="store_true", help="Run a post-session cache benchmark and write benchmark artifacts into the output directory")
    parser.add_argument("--cache-benchmark-ticker", default=None, help="Ticker used for the post-session cache benchmark; defaults to the first tracked ticker")
    parser.add_argument("--cache-benchmark-clear-first", action="store_true", help="Clear the local cache before running the post-session benchmark; use with caution")
    parser.add_argument("--analysts", default=None, help="Optional comma-separated analyst keys for a lower-cost replay subset")
    parser.add_argument("--fast-analysts", default=None, help="Optional comma-separated analyst keys used only for the fast agent tier")
    parser.add_argument("--short-trade-target-profile", default="default", help="Short-trade target profile for replay selection logic")
    parser.add_argument("--short-trade-target-overrides", default=None, help="JSON object with short-trade target profile overrides")
    parser.add_argument("--analysts-all", action="store_true", help="Use all analysts explicitly")
    parser.add_argument("--analyst-concurrency-limit", type=int, default=None, help="Optional ANALYST_CONCURRENCY_LIMIT override for replay throughput control")
    parser.add_argument("--disable-data-snapshots", action="store_true", help="Disable data snapshot exports for faster replay runs")
    parser.add_argument("--candidate-pool-shadow-focus-tickers", default=None, help="Comma-separated tickers pinned into shadow recall selection across all lanes")
    parser.add_argument("--candidate-pool-shadow-corridor-focus-tickers", default=None, help="Comma-separated tickers pinned into layer_a_liquidity_corridor shadow selection")
    parser.add_argument("--candidate-pool-shadow-rebucket-focus-tickers", default=None, help="Comma-separated tickers pinned into post_gate_liquidity_competition shadow selection")
    parser.add_argument("--upstream-shadow-release-liquidity-corridor-score-min", type=float, default=None, help="Optional lane-specific release score floor for layer_a_liquidity_corridor")
    parser.add_argument("--upstream-shadow-release-post-gate-rebucket-score-min", type=float, default=None, help="Optional lane-specific release score floor for post_gate_liquidity_competition")
    return parser.parse_args()


def _apply_optional_env_override(name: str, value: str | float | None) -> None:
    if value is None:
        return
    os.environ[name] = str(value)


def _resolve_model_route(model_name: str | None, model_provider: str | None) -> tuple[str | None, str | None]:
    model_selection_module = importlib.import_module("scripts.model_selection")
    return model_selection_module.resolve_model_selection(model_name, model_provider)


def _resolve_selected_analysts(analysts: str | None, analysts_all: bool) -> list[str] | None:
    analysts_module = importlib.import_module("src.utils.analysts")
    if analysts_all:
        return [value for _, value in analysts_module.ANALYST_ORDER]
    if analysts:
        return [item.strip() for item in analysts.split(",") if item.strip()]
    return None


def _resolve_short_trade_target_overrides(raw: str | None) -> dict[str, object] | None:
    token = str(raw or "").strip()
    if not token:
        return None
    parsed = json.loads(token)
    if not isinstance(parsed, dict):
        raise ValueError("--short-trade-target-overrides must be a JSON object")
    return parsed


def _parse_csv_tokens(raw: str | None) -> list[str]:
    return [token.strip() for token in str(raw or "").split(",") if token.strip()]


def _join_csv_tokens(tokens: list[str]) -> str | None:
    unique_tokens = sorted(dict.fromkeys(token for token in tokens if token))
    return ",".join(unique_tokens) if unique_tokens else None


def _resolve_reports_root_from_output_dir(output_dir: Path) -> Path | None:
    resolved_output_dir = output_dir.expanduser().resolve()
    reports_root = resolved_output_dir.parent
    if reports_root.name != "reports":
        return None
    return reports_root


def _load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _latest_followup_supports_overnight_shadow_focus(dossier: dict[str, Any]) -> bool:
    governance_followup = dict(dossier.get("governance_followup") or {})
    latest_followup_next_close_positive_rate = governance_followup.get("latest_followup_historical_next_close_positive_rate")
    if latest_followup_next_close_positive_rate is None:
        return True
    try:
        return float(latest_followup_next_close_positive_rate) >= AUTO_SHADOW_FOLLOWUP_MIN_NEXT_CLOSE_POSITIVE_RATE
    except (TypeError, ValueError):
        return True


def _extend_shadow_focus_from_candidate_pool_recall_dossier(
    reports_root: Path,
    *,
    all_focus: set[str],
    corridor_focus: set[str],
    rebucket_focus: set[str],
) -> None:
    dossier = _load_json_if_exists(reports_root / "btst_candidate_pool_recall_dossier_latest.json")
    for row in list(dossier.get("priority_ticker_dossiers") or []):
        _extend_shadow_focus_from_recall_row(
            reports_root,
            dict(row or {}),
            all_focus=all_focus,
            corridor_focus=corridor_focus,
            rebucket_focus=rebucket_focus,
        )


def _extend_shadow_focus_from_recall_row(
    reports_root: Path,
    payload: dict[str, Any],
    *,
    all_focus: set[str],
    corridor_focus: set[str],
    rebucket_focus: set[str],
) -> None:
    ticker = str(payload.get("ticker") or "").strip()
    if not ticker:
        return

    strict_goal_case_count = int(payload.get("strict_btst_goal_case_count") or 0)
    if strict_goal_case_count < AUTO_SHADOW_RECALL_MIN_STRICT_GOAL_CASES:
        return

    candidate_dossier = _load_json_if_exists(reports_root / f"btst_tplus2_candidate_dossier_{ticker}_latest.json")
    if candidate_dossier and not _latest_followup_supports_overnight_shadow_focus(candidate_dossier):
        return

    truncation_liquidity_profile = dict(payload.get("truncation_liquidity_profile") or {})
    priority_handoff = str(truncation_liquidity_profile.get("priority_handoff") or "").strip()
    avg_amount_share_of_min_gate = truncation_liquidity_profile.get("avg_amount_share_of_min_gate_mean")
    avg_amount_share_of_cutoff = truncation_liquidity_profile.get("avg_amount_share_of_cutoff_mean")
    if priority_handoff == "layer_a_liquidity_corridor":
        if avg_amount_share_of_min_gate is None or float(avg_amount_share_of_min_gate) < AUTO_SHADOW_CORRIDOR_MIN_GATE_SHARE:
            return
        if avg_amount_share_of_cutoff is None or float(avg_amount_share_of_cutoff) > AUTO_SHADOW_CORRIDOR_MAX_CUTOFF_SHARE:
            return
        all_focus.add(ticker)
        corridor_focus.add(ticker)
        return

    if priority_handoff != "post_gate_liquidity_competition":
        return
    if avg_amount_share_of_min_gate is None or float(avg_amount_share_of_min_gate) < AUTO_SHADOW_REBUCKET_MIN_GATE_SHARE:
        return
    closest_pre_truncation_gap = payload.get("closest_pre_truncation_gap")
    if closest_pre_truncation_gap is None or int(closest_pre_truncation_gap) > AUTO_SHADOW_RECALL_MAX_CLOSEST_PRE_TRUNCATION_GAP:
        return
    all_focus.add(ticker)
    rebucket_focus.add(ticker)


def _mark_visibility_gap_focus(
    *,
    ticker: str,
    latest_followup_decision: str,
    has_visibility_gap: bool,
    visibility_gap_all_focus: set[str],
    visibility_gap_corridor_focus: set[str],
    visibility_gap_rebucket_focus: set[str],
    lane: str,
) -> None:
    if latest_followup_decision != "selected" or not has_visibility_gap:
        return
    visibility_gap_all_focus.add(ticker)
    if lane == "layer_a_liquidity_corridor":
        visibility_gap_corridor_focus.add(ticker)
    elif lane == "post_gate_liquidity_competition":
        visibility_gap_rebucket_focus.add(ticker)


def _update_shadow_focus_from_candidate_dossier(
    dossier: dict[str, Any],
    *,
    all_focus: set[str],
    corridor_focus: set[str],
    rebucket_focus: set[str],
    visibility_gap_all_focus: set[str],
    visibility_gap_corridor_focus: set[str],
    visibility_gap_rebucket_focus: set[str],
) -> None:
    ticker = str(dossier.get("candidate_ticker") or "").strip()
    governance_followup = dict(dossier.get("governance_followup") or {})
    latest_followup_decision = str(governance_followup.get("latest_followup_decision") or "").strip()
    downstream_followup_status = str(governance_followup.get("downstream_followup_status") or "").strip()
    current_plan_visibility_summary = dict(dossier.get("current_plan_visibility_summary") or {})
    has_visibility_gap = int(current_plan_visibility_summary.get("current_plan_visibility_gap_trade_date_count") or 0) > 0
    if (
        not ticker
        or latest_followup_decision not in {"near_miss", "selected"}
        or downstream_followup_status not in {"continuation_confirm_then_review", "continuation_only_confirm_then_review"}
        or not _latest_followup_supports_overnight_shadow_focus(dossier)
    ):
        return

    all_focus.add(ticker)
    priority_handoff = str(governance_followup.get("priority_handoff") or "").strip()
    if priority_handoff == "layer_a_liquidity_corridor":
        corridor_focus.add(ticker)
    elif priority_handoff == "post_gate_liquidity_competition":
        rebucket_focus.add(ticker)
    _mark_visibility_gap_focus(
        ticker=ticker,
        latest_followup_decision=latest_followup_decision,
        has_visibility_gap=has_visibility_gap,
        visibility_gap_all_focus=visibility_gap_all_focus,
        visibility_gap_corridor_focus=visibility_gap_corridor_focus,
        visibility_gap_rebucket_focus=visibility_gap_rebucket_focus,
        lane=priority_handoff,
    )

    for row in list(dossier.get("governance_recent_followup_rows") or []):
        row_payload = dict(row or {})
        if str(row_payload.get("ticker") or "").strip() != ticker:
            continue
        if str(row_payload.get("decision") or "").strip() not in {"near_miss", "selected"}:
            continue
        lane = str(row_payload.get("candidate_pool_lane") or "").strip()
        if lane == "layer_a_liquidity_corridor":
            corridor_focus.add(ticker)
        elif lane == "post_gate_liquidity_competition":
            rebucket_focus.add(ticker)
        else:
            continue
        _mark_visibility_gap_focus(
            ticker=ticker,
            latest_followup_decision=latest_followup_decision,
            has_visibility_gap=has_visibility_gap,
            visibility_gap_all_focus=visibility_gap_all_focus,
            visibility_gap_corridor_focus=visibility_gap_corridor_focus,
            visibility_gap_rebucket_focus=visibility_gap_rebucket_focus,
            lane=lane,
        )


def _derive_shadow_focus_tickers_from_reports(reports_root: Path | None) -> dict[str, list[str]]:
    derived_focus = {
        "all": [],
        "layer_a_liquidity_corridor": [],
        "post_gate_liquidity_competition": [],
        "visibility_gap_all": [],
        "visibility_gap_layer_a_liquidity_corridor": [],
        "visibility_gap_post_gate_liquidity_competition": [],
    }
    if reports_root is None or not reports_root.exists():
        return derived_focus

    all_focus: set[str] = set()
    corridor_focus: set[str] = set()
    rebucket_focus: set[str] = set()
    visibility_gap_all_focus: set[str] = set()
    visibility_gap_corridor_focus: set[str] = set()
    visibility_gap_rebucket_focus: set[str] = set()

    for dossier_path in sorted(reports_root.glob("btst_tplus2_candidate_dossier_*_latest.json")):
        _update_shadow_focus_from_candidate_dossier(
            _load_json_if_exists(dossier_path),
            all_focus=all_focus,
            corridor_focus=corridor_focus,
            rebucket_focus=rebucket_focus,
            visibility_gap_all_focus=visibility_gap_all_focus,
            visibility_gap_corridor_focus=visibility_gap_corridor_focus,
            visibility_gap_rebucket_focus=visibility_gap_rebucket_focus,
        )

    _extend_shadow_focus_from_candidate_pool_recall_dossier(
        reports_root,
        all_focus=all_focus,
        corridor_focus=corridor_focus,
        rebucket_focus=rebucket_focus,
    )

    derived_focus["all"] = sorted(all_focus)
    derived_focus["layer_a_liquidity_corridor"] = sorted(corridor_focus)
    derived_focus["post_gate_liquidity_competition"] = sorted(rebucket_focus)
    derived_focus["visibility_gap_all"] = sorted(visibility_gap_all_focus)
    derived_focus["visibility_gap_layer_a_liquidity_corridor"] = sorted(visibility_gap_corridor_focus)
    derived_focus["visibility_gap_post_gate_liquidity_competition"] = sorted(visibility_gap_rebucket_focus)
    return derived_focus


def _run_paper_trading_session(*, disable_data_snapshots: bool = False, **kwargs):
    runtime_module = importlib.import_module("src.paper_trading.runtime")
    if disable_data_snapshots:
        os.environ["DATA_SNAPSHOT_ENABLED"] = "false"
        snapshot_module = importlib.import_module("src.data.snapshot")
        snapshot_module.DataSnapshotExporter._instance = None
    return runtime_module.run_paper_trading_session(**kwargs)


def _resolve_paper_trading_runtime_inputs(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir(args.start_date, args.end_date)
    return {
        "tickers": _parse_csv_tokens(args.tickers),
        "selected_analysts": _resolve_selected_analysts(args.analysts, args.analysts_all),
        "fast_selected_analysts": _resolve_selected_analysts(args.fast_analysts, False),
        "short_trade_target_profile": str(args.short_trade_target_profile or "default").strip() or "default",
        "short_trade_target_overrides": _resolve_short_trade_target_overrides(args.short_trade_target_overrides),
        "output_dir": output_dir,
        "auto_shadow_focus": _derive_shadow_focus_tickers_from_reports(_resolve_reports_root_from_output_dir(output_dir)),
    }


def _apply_shadow_focus_env_overrides(args: argparse.Namespace, auto_shadow_focus: dict[str, list[str]]) -> dict[str, str]:
    resolved_shadow_focus_tickers = _join_csv_tokens(_parse_csv_tokens(args.candidate_pool_shadow_focus_tickers) + list(auto_shadow_focus["all"]))
    resolved_shadow_corridor_focus_tickers = _join_csv_tokens(
        _parse_csv_tokens(args.candidate_pool_shadow_corridor_focus_tickers) + list(auto_shadow_focus["layer_a_liquidity_corridor"])
    )
    resolved_shadow_rebucket_focus_tickers = _join_csv_tokens(
        _parse_csv_tokens(args.candidate_pool_shadow_rebucket_focus_tickers) + list(auto_shadow_focus["post_gate_liquidity_competition"])
    )
    resolved_shadow_visibility_gap_tickers = _join_csv_tokens(_parse_csv_tokens(os.getenv("CANDIDATE_POOL_SHADOW_VISIBILITY_GAP_TICKERS")) + list(auto_shadow_focus["visibility_gap_all"]))
    resolved_shadow_visibility_gap_corridor_tickers = _join_csv_tokens(
        _parse_csv_tokens(os.getenv("CANDIDATE_POOL_SHADOW_VISIBILITY_GAP_LIQUIDITY_CORRIDOR_TICKERS")) + list(auto_shadow_focus["visibility_gap_layer_a_liquidity_corridor"])
    )
    resolved_shadow_visibility_gap_rebucket_tickers = _join_csv_tokens(
        _parse_csv_tokens(os.getenv("CANDIDATE_POOL_SHADOW_VISIBILITY_GAP_REBUCKET_TICKERS")) + list(auto_shadow_focus["visibility_gap_post_gate_liquidity_competition"])
    )
    _apply_optional_env_override("CANDIDATE_POOL_SHADOW_FOCUS_TICKERS", resolved_shadow_focus_tickers)
    _apply_optional_env_override("CANDIDATE_POOL_SHADOW_FOCUS_LIQUIDITY_CORRIDOR_TICKERS", resolved_shadow_corridor_focus_tickers)
    _apply_optional_env_override("CANDIDATE_POOL_SHADOW_FOCUS_REBUCKET_TICKERS", resolved_shadow_rebucket_focus_tickers)
    _apply_optional_env_override("CANDIDATE_POOL_SHADOW_VISIBILITY_GAP_TICKERS", resolved_shadow_visibility_gap_tickers)
    _apply_optional_env_override("CANDIDATE_POOL_SHADOW_VISIBILITY_GAP_LIQUIDITY_CORRIDOR_TICKERS", resolved_shadow_visibility_gap_corridor_tickers)
    _apply_optional_env_override("CANDIDATE_POOL_SHADOW_VISIBILITY_GAP_REBUCKET_TICKERS", resolved_shadow_visibility_gap_rebucket_tickers)
    return {
        "resolved_shadow_focus_tickers": resolved_shadow_focus_tickers,
        "resolved_shadow_corridor_focus_tickers": resolved_shadow_corridor_focus_tickers,
        "resolved_shadow_rebucket_focus_tickers": resolved_shadow_rebucket_focus_tickers,
        "resolved_shadow_visibility_gap_tickers": resolved_shadow_visibility_gap_tickers,
        "resolved_shadow_visibility_gap_corridor_tickers": resolved_shadow_visibility_gap_corridor_tickers,
        "resolved_shadow_visibility_gap_rebucket_tickers": resolved_shadow_visibility_gap_rebucket_tickers,
    }


def _print_paper_trading_run_summary(
    *,
    args: argparse.Namespace,
    artifacts: Any,
    resolved_model_name: str,
    resolved_model_provider: str,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile: str,
    short_trade_target_overrides: dict[str, Any],
    auto_shadow_focus: dict[str, list[str]],
    shadow_focus_env: dict[str, str],
) -> None:
    _print_paper_trading_runtime_summary(
        args=args,
        artifacts=artifacts,
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        short_trade_target_profile=short_trade_target_profile,
        short_trade_target_overrides=short_trade_target_overrides,
    )
    _print_shadow_focus_summary(auto_shadow_focus, shadow_focus_env)
    print(f"paper_trading_selected_analysts={','.join(selected_analysts) if selected_analysts else 'all'}")
    if fast_selected_analysts is not None:
        print(f"paper_trading_fast_selected_analysts={','.join(fast_selected_analysts)}")
    if args.analyst_concurrency_limit is not None:
        print(f"paper_trading_analyst_concurrency_limit={args.analyst_concurrency_limit}")
    if args.disable_data_snapshots:
        print("paper_trading_data_snapshots=disabled")


def _print_paper_trading_runtime_summary(
    *,
    args: argparse.Namespace,
    artifacts: Any,
    resolved_model_name: str,
    resolved_model_provider: str,
    short_trade_target_profile: str,
    short_trade_target_overrides: dict[str, Any],
) -> None:
    print(f"paper_trading_model_route={resolved_model_provider}:{resolved_model_name}")
    print(f"paper_trading_output_dir={artifacts.output_dir}")
    print(f"paper_trading_daily_events={artifacts.daily_events_path}")
    print(f"paper_trading_timing_log={artifacts.timing_log_path}")
    print(f"paper_trading_summary={artifacts.summary_path}")
    print(f"paper_trading_selection_target={args.selection_target}")
    print(f"paper_trading_short_trade_target_profile={short_trade_target_profile}")
    if short_trade_target_overrides:
        print(f"paper_trading_short_trade_target_overrides={json.dumps(short_trade_target_overrides, ensure_ascii=False, sort_keys=True)}")


def _print_shadow_focus_summary(auto_shadow_focus: dict[str, list[str]], shadow_focus_env: dict[str, str]) -> None:
    if auto_shadow_focus["all"] or auto_shadow_focus["layer_a_liquidity_corridor"] or auto_shadow_focus["post_gate_liquidity_competition"]:
        print(f"paper_trading_auto_shadow_focus={json.dumps(auto_shadow_focus, ensure_ascii=False, sort_keys=True)}")
    if shadow_focus_env["resolved_shadow_focus_tickers"]:
        print(f"paper_trading_shadow_focus_tickers={shadow_focus_env['resolved_shadow_focus_tickers']}")
    if shadow_focus_env["resolved_shadow_corridor_focus_tickers"]:
        print(f"paper_trading_shadow_corridor_focus_tickers={shadow_focus_env['resolved_shadow_corridor_focus_tickers']}")
    if shadow_focus_env["resolved_shadow_rebucket_focus_tickers"]:
        print(f"paper_trading_shadow_rebucket_focus_tickers={shadow_focus_env['resolved_shadow_rebucket_focus_tickers']}")
    if shadow_focus_env["resolved_shadow_visibility_gap_tickers"]:
        print(f"paper_trading_shadow_visibility_gap_tickers={shadow_focus_env['resolved_shadow_visibility_gap_tickers']}")
    if shadow_focus_env["resolved_shadow_visibility_gap_corridor_tickers"]:
        print(f"paper_trading_shadow_visibility_gap_corridor_tickers={shadow_focus_env['resolved_shadow_visibility_gap_corridor_tickers']}")
    if shadow_focus_env["resolved_shadow_visibility_gap_rebucket_tickers"]:
        print(f"paper_trading_shadow_visibility_gap_rebucket_tickers={shadow_focus_env['resolved_shadow_visibility_gap_rebucket_tickers']}")


def _print_btst_followup_artifacts(output_dir: Path, end_date: str) -> None:
    followup_artifacts = generate_btst_followup_artifacts(output_dir, end_date)
    print(f"paper_trading_btst_brief_json={followup_artifacts['brief_json']}")
    print(f"paper_trading_btst_brief_markdown={followup_artifacts['brief_markdown']}")
    print(f"paper_trading_btst_execution_card_json={followup_artifacts['card_json']}")
    print(f"paper_trading_btst_execution_card_markdown={followup_artifacts['card_markdown']}")
    print(f"paper_trading_btst_opening_watch_card_json={followup_artifacts['opening_card_json']}")
    print(f"paper_trading_btst_opening_watch_card_markdown={followup_artifacts['opening_card_markdown']}")
    print(f"paper_trading_btst_priority_board_json={followup_artifacts['priority_board_json']}")
    print(f"paper_trading_btst_priority_board_markdown={followup_artifacts['priority_board_markdown']}")
    nightly_control_tower_artifacts = refresh_btst_nightly_control_tower(output_dir)
    if nightly_control_tower_artifacts:
        print(f"paper_trading_btst_open_ready_delta_json={nightly_control_tower_artifacts['open_ready_delta_json']}")
        print(f"paper_trading_btst_open_ready_delta_markdown={nightly_control_tower_artifacts['open_ready_delta_markdown']}")
        print(f"paper_trading_btst_nightly_control_tower_json={nightly_control_tower_artifacts['nightly_control_tower_json']}")
        print(f"paper_trading_btst_nightly_control_tower_markdown={nightly_control_tower_artifacts['nightly_control_tower_markdown']}")
        if nightly_control_tower_artifacts.get("catalyst_theme_frontier_json"):
            print(f"paper_trading_catalyst_theme_frontier_json={nightly_control_tower_artifacts['catalyst_theme_frontier_json']}")
        if nightly_control_tower_artifacts.get("catalyst_theme_frontier_markdown"):
            print(f"paper_trading_catalyst_theme_frontier_markdown={nightly_control_tower_artifacts['catalyst_theme_frontier_markdown']}")
        print(f"paper_trading_report_manifest_json={nightly_control_tower_artifacts['manifest_json']}")
        print(f"paper_trading_report_manifest_markdown={nightly_control_tower_artifacts['manifest_markdown']}")


def main() -> None:
    args = parse_args()
    runtime_inputs = _resolve_paper_trading_runtime_inputs(args)
    tickers = runtime_inputs["tickers"]
    selected_analysts = runtime_inputs["selected_analysts"]
    fast_selected_analysts = runtime_inputs["fast_selected_analysts"]
    short_trade_target_profile = runtime_inputs["short_trade_target_profile"]
    short_trade_target_overrides = runtime_inputs["short_trade_target_overrides"]
    output_dir = runtime_inputs["output_dir"]
    auto_shadow_focus = runtime_inputs["auto_shadow_focus"]
    shadow_focus_env = _apply_shadow_focus_env_overrides(args, auto_shadow_focus)
    resolved_shadow_focus_tickers = shadow_focus_env["resolved_shadow_focus_tickers"]
    resolved_shadow_corridor_focus_tickers = shadow_focus_env["resolved_shadow_corridor_focus_tickers"]
    resolved_shadow_rebucket_focus_tickers = shadow_focus_env["resolved_shadow_rebucket_focus_tickers"]
    resolved_shadow_visibility_gap_tickers = shadow_focus_env["resolved_shadow_visibility_gap_tickers"]
    resolved_shadow_visibility_gap_corridor_tickers = shadow_focus_env["resolved_shadow_visibility_gap_corridor_tickers"]
    resolved_shadow_visibility_gap_rebucket_tickers = shadow_focus_env["resolved_shadow_visibility_gap_rebucket_tickers"]
    _apply_optional_env_override("ANALYST_CONCURRENCY_LIMIT", args.analyst_concurrency_limit)
    if args.disable_data_snapshots:
        _apply_optional_env_override("DATA_SNAPSHOT_ENABLED", "false")
    _apply_optional_env_override(
        "DAILY_PIPELINE_UPSTREAM_SHADOW_RELEASE_LIQUIDITY_CORRIDOR_SCORE_MIN",
        args.upstream_shadow_release_liquidity_corridor_score_min,
    )
    _apply_optional_env_override(
        "DAILY_PIPELINE_UPSTREAM_SHADOW_RELEASE_POST_GATE_REBUCKET_SCORE_MIN",
        args.upstream_shadow_release_post_gate_rebucket_score_min,
    )
    resolved_model_name, resolved_model_provider = _resolve_model_route(args.model_name, args.model_provider)
    artifacts = _run_paper_trading_session(
        disable_data_snapshots=args.disable_data_snapshots,
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=output_dir,
        tickers=tickers,
        initial_capital=args.initial_capital,
        model_name=resolved_model_name,
        model_provider=resolved_model_provider,
        selected_analysts=selected_analysts,
        fast_selected_analysts=fast_selected_analysts,
        short_trade_target_profile_name=short_trade_target_profile,
        short_trade_target_profile_overrides=short_trade_target_overrides,
        frozen_plan_source=args.frozen_plan_source,
        selection_target=args.selection_target,
        cache_benchmark=args.cache_benchmark,
        cache_benchmark_ticker=args.cache_benchmark_ticker,
        cache_benchmark_clear_first=args.cache_benchmark_clear_first,
    )
    _print_paper_trading_run_summary(
        args=args,
        artifacts=artifacts,
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        selected_analysts=selected_analysts,
        fast_selected_analysts=fast_selected_analysts,
        short_trade_target_profile=short_trade_target_profile,
        short_trade_target_overrides=short_trade_target_overrides,
        auto_shadow_focus=auto_shadow_focus,
        shadow_focus_env=shadow_focus_env,
    )
    if args.selection_target != "research_only":
        _print_btst_followup_artifacts(output_dir, args.end_date)
    if args.cache_benchmark:
        print(f"paper_trading_cache_benchmark=enabled")
    if args.frozen_plan_source:
        print(f"paper_trading_frozen_plan_source={Path(args.frozen_plan_source).resolve()}")


if __name__ == "__main__":
    main()
