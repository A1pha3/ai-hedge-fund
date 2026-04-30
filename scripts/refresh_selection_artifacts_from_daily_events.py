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
from src.execution.daily_pipeline_catalyst_diagnostics_helpers import _build_catalyst_theme_candidate_diagnostics
from src.execution.daily_pipeline import _build_upstream_shadow_catalyst_relief_config, _build_upstream_shadow_observation_entry, _qualifies_short_trade_boundary_candidate
from src.execution.models import ExecutionPlan
from src.paper_trading.btst_reporting import generate_and_register_btst_followup_artifacts
from src.paper_trading.frozen_replay import load_frozen_post_market_plans
from src.research.artifacts import FileSelectionArtifactWriter
from src.screening.models import FusedScore, MarketState, StrategySignal
from src.targets.models import DualTargetEvaluation
from src.targets.router import build_selection_targets, summarize_selection_targets
from src.targets.short_trade_target import evaluate_short_trade_selected_target

EVIDENCE_DEFICIENT_BROAD_FAMILY_ONLY = "evidence_deficient_broad_family_only"
CATALYST_THEME_DIAGNOSTICS_RERUN_FILENAME = "catalyst_theme_diagnostics_rerun.json"


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


def _normalize_strategy_signals_payload(raw_signals: Any) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for name, payload in dict(raw_signals or {}).items():
        signal_name = str(name or "").strip()
        if not signal_name:
            continue
        if hasattr(payload, "model_dump"):
            signal_payload = dict(payload.model_dump(mode="json") or {})
        elif isinstance(payload, dict):
            signal_payload = dict(payload or {})
        else:
            continue
        if signal_payload:
            normalized[signal_name] = signal_payload
    return normalized


def _merge_strategy_signals_lookup(
    strategy_signals_by_ticker: dict[str, dict[str, dict[str, Any]]],
    *,
    ticker: Any,
    raw_signals: Any,
) -> None:
    normalized_ticker = str(ticker or "").strip()
    if not normalized_ticker:
        return
    normalized_signals = _normalize_strategy_signals_payload(raw_signals)
    if not normalized_signals:
        return
    strategy_signals_by_ticker.setdefault(normalized_ticker, normalized_signals)


def _load_existing_replay_input_strategy_signals(report_dir: Path, trade_date_compact: str) -> dict[str, dict[str, dict[str, Any]]]:
    trade_date = normalize_trade_date(trade_date_compact) or trade_date_compact
    replay_input_path = report_dir / "selection_artifacts" / str(trade_date) / "selection_target_replay_input.json"
    replay_input = safe_load_json(replay_input_path)
    strategy_signals_by_ticker: dict[str, dict[str, dict[str, Any]]] = {}
    for entry_key in (
        "watchlist",
        "rejected_entries",
        "supplemental_short_trade_entries",
        "supplemental_catalyst_theme_entries",
        "upstream_shadow_observation_entries",
    ):
        for raw_entry in list(replay_input.get(entry_key) or []):
            entry = dict(raw_entry or {})
            _merge_strategy_signals_lookup(
                strategy_signals_by_ticker,
                ticker=entry.get("ticker"),
                raw_signals=entry.get("strategy_signals"),
            )
    return strategy_signals_by_ticker


def _build_strategy_signals_lookup(
    plan: ExecutionPlan,
    *,
    report_dir: Path,
    trade_date_compact: str,
) -> dict[str, dict[str, dict[str, Any]]]:
    strategy_signals_by_ticker: dict[str, dict[str, dict[str, Any]]] = {}
    for item in list(plan.watchlist or []):
        _merge_strategy_signals_lookup(
            strategy_signals_by_ticker,
            ticker=getattr(item, "ticker", None),
            raw_signals=getattr(item, "strategy_signals", None),
        )

    filters = dict(dict((plan.risk_metrics or {}).get("funnel_diagnostics") or {}).get("filters") or {})
    for filter_key in ("watchlist", "short_trade_candidates", "catalyst_theme_candidates"):
        filter_payload = dict(filters.get(filter_key) or {})
        for entry_key in ("tickers", "released_shadow_entries", "shadow_observation_entries"):
            for raw_entry in list(filter_payload.get(entry_key) or []):
                entry = dict(raw_entry or {})
                _merge_strategy_signals_lookup(
                    strategy_signals_by_ticker,
                    ticker=entry.get("ticker"),
                    raw_signals=entry.get("strategy_signals"),
                )

    for ticker, signals in _load_existing_replay_input_strategy_signals(report_dir, trade_date_compact).items():
        strategy_signals_by_ticker.setdefault(ticker, signals)
    return strategy_signals_by_ticker


def _attach_strategy_signals_to_entry(
    entry: dict[str, Any],
    *,
    strategy_signals_by_ticker: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    updated_entry = dict(entry or {})
    existing_signals = _normalize_strategy_signals_payload(updated_entry.get("strategy_signals"))
    if existing_signals:
        updated_entry["strategy_signals"] = existing_signals
        return updated_entry

    ticker = str(updated_entry.get("ticker") or "").strip()
    fallback_signals = dict(strategy_signals_by_ticker.get(ticker) or {})
    if fallback_signals:
        updated_entry["strategy_signals"] = fallback_signals
    return updated_entry


def _attach_strategy_signals_to_entries(
    entries: list[dict[str, Any]],
    *,
    strategy_signals_by_ticker: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    return [
        _attach_strategy_signals_to_entry(entry, strategy_signals_by_ticker=strategy_signals_by_ticker)
        for entry in list(entries or [])
    ]


def _coerce_strategy_signal_models(raw_signals: dict[str, dict[str, Any]]) -> dict[str, StrategySignal]:
    coerced: dict[str, StrategySignal] = {}
    for name, payload in dict(raw_signals or {}).items():
        try:
            coerced[str(name)] = StrategySignal.model_validate(payload)
        except Exception:
            continue
    return coerced


def _rehydrate_watchlist_strategy_signals(
    watchlist: list[Any],
    *,
    strategy_signals_by_ticker: dict[str, dict[str, dict[str, Any]]],
) -> list[Any]:
    rehydrated_watchlist: list[Any] = []
    for item in list(watchlist or []):
        existing_signals = _normalize_strategy_signals_payload(getattr(item, "strategy_signals", None))
        if existing_signals:
            rehydrated_watchlist.append(item)
            continue

        ticker = str(getattr(item, "ticker", "") or "").strip()
        fallback_signals = dict(strategy_signals_by_ticker.get(ticker) or {})
        if not fallback_signals or not hasattr(item, "model_copy"):
            rehydrated_watchlist.append(item)
            continue

        rehydrated_watchlist.append(
            item.model_copy(
                update={
                    "strategy_signals": _coerce_strategy_signal_models(fallback_signals),
                }
            )
        )
    return rehydrated_watchlist


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


def _resolve_carryover_evidence_deficiency(entry: dict[str, Any]) -> dict[str, Any]:
    historical_prior = dict(entry.get("historical_prior") or {})
    candidate_reason_codes = {
        str(code).strip()
        for code in list(entry.get("candidate_reason_codes") or [])
        if str(code or "").strip()
    }
    same_ticker_sample_count = int(historical_prior.get("same_ticker_sample_count") or 0)
    same_family_sample_count = int(historical_prior.get("same_family_sample_count") or 0)
    same_family_source_sample_count = int(historical_prior.get("same_family_source_sample_count") or 0)
    same_family_source_score_catalyst_sample_count = int(historical_prior.get("same_family_source_score_catalyst_sample_count") or 0)
    same_source_score_sample_count = int(historical_prior.get("same_source_score_sample_count") or 0)
    evaluable_count = int(historical_prior.get("evaluable_count") or 0)
    gate_hits = {
        "candidate_source": str(entry.get("candidate_source") or "").strip() == "catalyst_theme",
        "carryover_candidate": "catalyst_theme_short_trade_carryover_candidate" in candidate_reason_codes,
        "execution_quality_label": str(historical_prior.get("execution_quality_label") or "") == "close_continuation",
        "entry_timing_bias": str(historical_prior.get("entry_timing_bias") or "") == "confirm_then_hold",
        "low_same_ticker_samples": same_ticker_sample_count < 2,
        "low_evaluable_count": evaluable_count <= 1,
        "broad_family_only": same_family_sample_count > 0,
        "no_same_family_source": same_family_source_sample_count == 0,
        "no_same_family_source_score_catalyst": same_family_source_score_catalyst_sample_count == 0,
        "no_same_source_score": same_source_score_sample_count == 0,
    }
    return {
        "enabled": bool(historical_prior),
        "evidence_deficient": bool(historical_prior) and all(gate_hits.values()),
        "gate_hits": gate_hits,
        "same_ticker_sample_count": same_ticker_sample_count,
        "same_family_sample_count": same_family_sample_count,
        "same_family_source_sample_count": same_family_source_sample_count,
        "same_family_source_score_catalyst_sample_count": same_family_source_score_catalyst_sample_count,
        "same_source_score_sample_count": same_source_score_sample_count,
        "evaluable_count": evaluable_count,
    }


def _prepend_unique(values: list[str], item: str) -> list[str]:
    normalized = [str(value) for value in values if str(value or "").strip()]
    return [item, *[value for value in normalized if value != item]]


def _annotate_carryover_evidence_deficiency(entry: dict[str, Any]) -> dict[str, Any]:
    updated_entry = dict(entry or {})
    deficiency = _resolve_carryover_evidence_deficiency(updated_entry)
    if not deficiency.get("enabled"):
        return updated_entry
    updated_entry["carryover_evidence_deficiency"] = deficiency
    metrics_payload = dict(updated_entry.get("short_trade_boundary_metrics") or {})
    metrics_payload["carryover_evidence_deficiency"] = deficiency
    updated_entry["short_trade_boundary_metrics"] = metrics_payload
    if not deficiency.get("evidence_deficient"):
        return updated_entry
    updated_entry["negative_tags"] = _prepend_unique(list(updated_entry.get("negative_tags") or []), EVIDENCE_DEFICIENT_BROAD_FAMILY_ONLY)
    updated_entry["rejection_reasons"] = _prepend_unique(list(updated_entry.get("rejection_reasons") or []), EVIDENCE_DEFICIENT_BROAD_FAMILY_ONLY)
    return updated_entry


def _refresh_released_shadow_entries(
    filters: dict[str, Any],
    filter_key: str,
    shadow_lookup: dict[str, dict[str, Any]],
    *,
    prior_by_ticker: dict[str, dict[str, Any]],
) -> None:
    filter_payload = dict(filters.get(filter_key) or {})
    refreshed_entries: list[dict[str, Any]] = []
    for raw_entry in list(filter_payload.get("released_shadow_entries") or []):
        entry = _merge_shadow_metadata(dict(raw_entry or {}), shadow_lookup)
        ticker = str(entry.get("ticker") or "").strip()
        historical_prior = dict(entry.get("historical_prior") or prior_by_ticker.get(ticker) or {})
        if historical_prior:
            entry["historical_prior"] = historical_prior
        existing_relief = dict(entry.get("short_trade_catalyst_relief") or {})
        relief = _build_upstream_shadow_catalyst_relief_config(
            candidate_pool_lane=str(entry.get("candidate_pool_lane") or ""),
            filter_reason=str(entry.get("shadow_release_filter_reason") or ""),
            metrics_payload=dict(entry.get("short_trade_boundary_metrics") or {}),
            historical_prior=historical_prior,
            shadow_visibility_gap_selected=bool(entry.get("shadow_visibility_gap_selected")),
        )
        merged_relief = {**existing_relief, **relief} if relief else existing_relief
        if merged_relief:
            entry["short_trade_catalyst_relief"] = merged_relief
        refreshed_entries.append(_annotate_carryover_evidence_deficiency(entry))
    filter_payload["released_shadow_entries"] = refreshed_entries
    filters[filter_key] = filter_payload


def _refresh_shadow_observation_entries(
    filters: dict[str, Any],
    *,
    shadow_lookup: dict[str, dict[str, Any]],
    prior_by_ticker: dict[str, dict[str, Any]],
    trade_date_compact: str,
) -> None:
    filter_payload = dict(filters.get("short_trade_candidates") or {})
    refreshed_entries: list[dict[str, Any]] = []
    for raw_entry in list(filter_payload.get("shadow_observation_entries") or []):
        entry = _merge_shadow_metadata(dict(raw_entry or {}), shadow_lookup)
        ticker = str(entry.get("ticker") or "").strip()
        historical_prior = dict(entry.get("historical_prior") or prior_by_ticker.get(ticker) or {})
        if historical_prior:
            entry["historical_prior"] = historical_prior
        qualified, filter_reason, metrics_payload = _qualifies_short_trade_boundary_candidate(
            trade_date=trade_date_compact,
            entry=entry,
        )
        if not qualified and filter_reason:
            entry = _build_upstream_shadow_observation_entry(
                candidate_entry=entry,
                filter_reason=filter_reason,
                metrics_payload=metrics_payload,
            )
        refreshed_entries.append(_annotate_carryover_evidence_deficiency(entry))
    filter_payload["shadow_observation_entries"] = refreshed_entries
    filters["short_trade_candidates"] = filter_payload


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
        attached_entries.append(_annotate_carryover_evidence_deficiency(updated_entry))
    return attached_entries


def _extract_historical_prior_from_plan_selection_targets(plan: ExecutionPlan) -> dict[str, dict[str, Any]]:
    prior_by_ticker: dict[str, dict[str, Any]] = {}
    for ticker, evaluation in dict(getattr(plan, "selection_targets", {}) or {}).items():
        short_trade = getattr(evaluation, "short_trade", None)
        explainability_payload = dict(getattr(short_trade, "explainability_payload", {}) or {}) if short_trade is not None else {}
        replay_context = dict(explainability_payload.get("replay_context") or {})
        historical_prior = dict(replay_context.get("historical_prior") or {})
        if historical_prior:
            prior_by_ticker[str(ticker)] = historical_prior
    return prior_by_ticker


def _build_selected_catalyst_theme_evaluation(*, trade_date: str, entry: dict[str, Any], rank_hint: int) -> DualTargetEvaluation:
    selected_entry = dict(entry or {})
    relief = dict(selected_entry.get("short_trade_catalyst_relief") or {})
    if str(relief.get("reason") or "") == "catalyst_theme_short_trade_carryover":
        relief.setdefault("selected_threshold", 0.45)
        relief.setdefault("min_historical_evaluable_count", 2)
    if relief:
        selected_entry["short_trade_catalyst_relief"] = relief

    candidate_reason_codes = [
        str(reason)
        for reason in list(selected_entry.get("candidate_reason_codes", selected_entry.get("reasons", [])) or [])
        if str(reason or "").strip()
    ]
    selected_item = SimpleNamespace(
        ticker=str(selected_entry.get("ticker") or ""),
        score_b=float(selected_entry.get("score_b", 0.0) or 0.0),
        score_c=float(selected_entry.get("score_c", 0.0) or 0.0),
        score_final=float(selected_entry.get("score_final", 0.0) or 0.0),
        quality_score=float(selected_entry.get("quality_score", 0.5) or 0.5),
        candidate_source=str(selected_entry.get("candidate_source") or "catalyst_theme"),
        candidate_reason_codes=candidate_reason_codes,
        strategy_signals=dict(selected_entry.get("strategy_signals") or {}),
        agent_contribution_summary=dict(selected_entry.get("agent_contribution_summary") or {}),
        bc_conflict=selected_entry.get("bc_conflict"),
        decision=str(selected_entry.get("decision") or ""),
        historical_prior=dict(selected_entry.get("historical_prior") or {}),
        short_trade_catalyst_relief=relief,
        metrics=dict(selected_entry.get("metrics") or {}),
        catalyst_theme_metrics=dict(selected_entry.get("catalyst_theme_metrics") or {}),
        reason=str(selected_entry.get("reason") or ""),
    )
    short_trade_result = evaluate_short_trade_selected_target(
        trade_date=trade_date,
        item=selected_item,
        rank_hint=rank_hint,
        included_in_buy_orders=False,
    )
    return DualTargetEvaluation(
        ticker=selected_item.ticker,
        trade_date=trade_date,
        research=None,
        short_trade=short_trade_result,
        candidate_source=selected_item.candidate_source,
        candidate_reason_codes=candidate_reason_codes,
    )


def _selected_tickers_from_filter(filter_payload: dict[str, Any]) -> set[str]:
    return {
        str(ticker).strip()
        for ticker in list(filter_payload.get("selected_tickers") or [])
        if str(ticker or "").strip()
    }


def _catalyst_theme_entries_by_ticker(filter_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(entry.get("ticker") or "").strip(): dict(entry or {})
        for entry in list(filter_payload.get("tickers") or [])
        if str((entry or {}).get("ticker") or "").strip()
    }


def _restore_selected_catalyst_theme_targets(
    *,
    selection_targets: dict[str, DualTargetEvaluation],
    catalyst_theme_filter: dict[str, Any],
    trade_date_compact: str,
    target_mode: str,
) -> tuple[dict[str, DualTargetEvaluation], Any]:
    if target_mode == "research_only":
        return selection_targets, summarize_selection_targets(selection_targets=selection_targets, target_mode=target_mode)

    selected_tickers = _selected_tickers_from_filter(catalyst_theme_filter)
    if not selected_tickers:
        return selection_targets, summarize_selection_targets(selection_targets=selection_targets, target_mode=target_mode)

    catalyst_theme_entries = _catalyst_theme_entries_by_ticker(catalyst_theme_filter)
    restored_targets = dict(selection_targets)
    next_rank_hint = len(restored_targets) + 1
    for ticker in selected_tickers:
        entry = catalyst_theme_entries.get(ticker)
        if not entry:
            continue
        restored_targets[ticker] = _build_selected_catalyst_theme_evaluation(
            trade_date=trade_date_compact,
            entry=entry,
            rank_hint=next_rank_hint,
        )
        next_rank_hint += 1
    return restored_targets, summarize_selection_targets(selection_targets=restored_targets, target_mode=target_mode)


def rebuild_selection_targets_for_plan(
    plan: ExecutionPlan,
    trade_date_compact: str,
    shadow_lookup: dict[str, dict[str, Any]] | None = None,
    *,
    historical_prior_by_ticker: dict[str, dict[str, Any]] | None = None,
    strategy_signals_by_ticker: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> ExecutionPlan:
    risk_metrics = dict(plan.risk_metrics or {})
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics") or {})
    filters = dict(funnel_diagnostics.get("filters") or {})
    shadow_lookup = dict(shadow_lookup or {})
    strategy_signals_by_ticker = dict(strategy_signals_by_ticker or {})
    historical_prior_by_ticker = {
        **_extract_historical_prior_from_plan_selection_targets(plan),
        **dict(historical_prior_by_ticker or {}),
    }

    _refresh_released_shadow_entries(filters, "short_trade_candidates", shadow_lookup, prior_by_ticker=historical_prior_by_ticker)
    _refresh_released_shadow_entries(filters, "watchlist", shadow_lookup, prior_by_ticker=historical_prior_by_ticker)
    _refresh_shadow_observation_entries(
        filters,
        shadow_lookup=shadow_lookup,
        prior_by_ticker=historical_prior_by_ticker,
        trade_date_compact=trade_date_compact,
    )

    short_trade_candidate_filters = dict(filters.get("short_trade_candidates") or {})
    watchlist_filter = dict(filters.get("watchlist") or {})
    catalyst_theme_filter = dict(filters.get("catalyst_theme_candidates") or {})
    refreshed_rejected_entries = _attach_historical_prior_to_entries(
        list(watchlist_filter.get("tickers") or []),
        prior_by_ticker=historical_prior_by_ticker,
    )
    refreshed_rejected_entries = _attach_strategy_signals_to_entries(
        refreshed_rejected_entries,
        strategy_signals_by_ticker=strategy_signals_by_ticker,
    )
    refreshed_short_trade_tickers = _attach_historical_prior_to_entries(
        list(short_trade_candidate_filters.get("tickers") or []),
        prior_by_ticker=historical_prior_by_ticker,
    )
    refreshed_short_trade_tickers = _attach_strategy_signals_to_entries(
        refreshed_short_trade_tickers,
        strategy_signals_by_ticker=strategy_signals_by_ticker,
    )
    refreshed_short_trade_released_shadow_entries = _attach_historical_prior_to_entries(
        list(short_trade_candidate_filters.get("released_shadow_entries") or []),
        prior_by_ticker=historical_prior_by_ticker,
    )
    refreshed_short_trade_released_shadow_entries = _attach_strategy_signals_to_entries(
        refreshed_short_trade_released_shadow_entries,
        strategy_signals_by_ticker=strategy_signals_by_ticker,
    )
    refreshed_watchlist_released_shadow_entries = _attach_historical_prior_to_entries(
        list(watchlist_filter.get("released_shadow_entries") or []),
        prior_by_ticker=historical_prior_by_ticker,
    )
    refreshed_watchlist_released_shadow_entries = _attach_strategy_signals_to_entries(
        refreshed_watchlist_released_shadow_entries,
        strategy_signals_by_ticker=strategy_signals_by_ticker,
    )
    refreshed_catalyst_theme_tickers = _attach_historical_prior_to_entries(
        list(catalyst_theme_filter.get("tickers") or []),
        prior_by_ticker=historical_prior_by_ticker,
    )
    refreshed_catalyst_theme_tickers = _attach_strategy_signals_to_entries(
        refreshed_catalyst_theme_tickers,
        strategy_signals_by_ticker=strategy_signals_by_ticker,
    )
    refreshed_catalyst_theme_filter = {
        **catalyst_theme_filter,
        "tickers": refreshed_catalyst_theme_tickers,
    }
    plan.watchlist = _rehydrate_watchlist_strategy_signals(
        list(plan.watchlist or []),
        strategy_signals_by_ticker=strategy_signals_by_ticker,
    )
    selection_targets, dual_target_summary = build_selection_targets(
        trade_date=trade_date_compact,
        watchlist=list(plan.watchlist or []),
        rejected_entries=refreshed_rejected_entries,
        supplemental_short_trade_entries=[
            *refreshed_short_trade_tickers,
            *refreshed_short_trade_released_shadow_entries,
            *refreshed_watchlist_released_shadow_entries,
            *refreshed_catalyst_theme_tickers,
        ],
        buy_order_tickers={str(order.ticker) for order in list(plan.buy_orders or [])},
        target_mode=str(getattr(plan, "target_mode", "research_only") or "research_only"),
    )
    selection_targets, dual_target_summary = _restore_selected_catalyst_theme_targets(
        selection_targets=selection_targets,
        catalyst_theme_filter=refreshed_catalyst_theme_filter,
        trade_date_compact=trade_date_compact,
        target_mode=str(getattr(plan, "target_mode", "research_only") or "research_only"),
    )

    watchlist_filter["tickers"] = refreshed_rejected_entries
    watchlist_filter["released_shadow_entries"] = refreshed_watchlist_released_shadow_entries
    short_trade_candidate_filters["tickers"] = refreshed_short_trade_tickers
    short_trade_candidate_filters["released_shadow_entries"] = refreshed_short_trade_released_shadow_entries
    filters["watchlist"] = watchlist_filter
    filters["short_trade_candidates"] = short_trade_candidate_filters
    filters["catalyst_theme_candidates"] = refreshed_catalyst_theme_filter
    funnel_diagnostics["filters"] = filters
    risk_metrics["funnel_diagnostics"] = funnel_diagnostics
    plan.risk_metrics = risk_metrics
    plan.selection_targets = selection_targets
    plan.dual_target_summary = dual_target_summary
    return plan


def _selection_artifact_trade_dir(report_dir: Path, trade_date_compact: str) -> Path:
    trade_date = normalize_trade_date(trade_date_compact) or trade_date_compact
    return report_dir / "selection_artifacts" / str(trade_date)


def _load_selection_snapshot_payload(report_dir: Path, trade_date_compact: str) -> dict[str, Any]:
    return safe_load_json(_selection_artifact_trade_dir(report_dir, trade_date_compact) / "selection_snapshot.json")


def _load_selection_replay_input_payload(report_dir: Path, trade_date_compact: str) -> dict[str, Any]:
    return safe_load_json(_selection_artifact_trade_dir(report_dir, trade_date_compact) / "selection_target_replay_input.json")


def _load_rebuilt_catalyst_theme_filter(report_dir: Path, trade_date_compact: str) -> dict[str, Any] | None:
    payload = safe_load_json(_selection_artifact_trade_dir(report_dir, trade_date_compact) / CATALYST_THEME_DIAGNOSTICS_RERUN_FILENAME)
    if "rebuild" not in payload:
        return None
    rebuild = dict(payload.get("rebuild") or {})
    tickers = [dict(entry or {}) for entry in list(rebuild.get("tickers") or [])]
    shadow_candidates = [dict(entry or {}) for entry in list(rebuild.get("shadow_candidates") or [])]
    return {
        "tickers": tickers,
        "shadow_candidates": shadow_candidates,
        "selected_tickers": [str(ticker or "").strip() for ticker in list(rebuild.get("selected_tickers") or []) if str(ticker or "").strip()],
        "filtered_reason_counts": dict(rebuild.get("filtered_reason_counts") or {}),
        "reason_counts": dict(rebuild.get("reason_counts") or {}),
    }


def _apply_rebuilt_catalyst_theme_filter(*, plan: ExecutionPlan, report_dir: Path, trade_date_compact: str) -> ExecutionPlan:
    rebuilt_filter = _load_rebuilt_catalyst_theme_filter(report_dir, trade_date_compact)
    if rebuilt_filter is None:
        return plan

    risk_metrics = dict(plan.risk_metrics or {})
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics") or {})
    filters = dict(funnel_diagnostics.get("filters") or {})
    catalyst_theme_filter = dict(filters.get("catalyst_theme_candidates") or {})
    catalyst_theme_filter.update(rebuilt_filter)
    filters["catalyst_theme_candidates"] = catalyst_theme_filter
    funnel_diagnostics["filters"] = filters
    risk_metrics["funnel_diagnostics"] = funnel_diagnostics
    plan.risk_metrics = risk_metrics
    return plan


def _normalize_market_state_payload(raw_market_state: Any) -> dict[str, Any]:
    if hasattr(raw_market_state, "model_dump"):
        return dict(raw_market_state.model_dump(mode="json") or {})
    if isinstance(raw_market_state, dict):
        return dict(raw_market_state or {})
    return {}


def _resolve_replay_market_state(
    raw_market_state: Any,
    *,
    fallback_market_state: Any,
) -> MarketState | None:
    payload = _normalize_market_state_payload(raw_market_state) or _normalize_market_state_payload(fallback_market_state)
    if not payload:
        return None
    try:
        return MarketState.model_validate(payload)
    except Exception:
        return None


def _coerce_replay_entry(raw_entry: Any) -> dict[str, Any]:
    if hasattr(raw_entry, "model_dump"):
        return dict(raw_entry.model_dump(mode="json") or {})
    if isinstance(raw_entry, dict):
        return dict(raw_entry or {})
    return {}


def _replay_entry_richness(entry: dict[str, Any]) -> tuple[int, int]:
    strategy_signals = _normalize_strategy_signals_payload(entry.get("strategy_signals"))
    return len(strategy_signals), len(entry)


def _upsert_replay_entry(
    entries_by_ticker: dict[str, dict[str, Any]],
    *,
    raw_entry: Any,
    source_name: str,
    source_row_counts: dict[str, int],
    sources_by_ticker: dict[str, set[str]],
    strategy_signals_by_ticker: dict[str, dict[str, dict[str, Any]]],
    dropped_no_strategy_signals_counts: dict[str, int],
    dropped_no_strategy_signal_tickers: set[str],
) -> None:
    entry = _attach_strategy_signals_to_entry(
        _coerce_replay_entry(raw_entry),
        strategy_signals_by_ticker=strategy_signals_by_ticker,
    )
    ticker = str(entry.get("ticker") or "").strip()
    if not ticker:
        return
    source_row_counts[source_name] = source_row_counts.get(source_name, 0) + 1
    if not _normalize_strategy_signals_payload(entry.get("strategy_signals")):
        dropped_no_strategy_signals_counts[source_name] = dropped_no_strategy_signals_counts.get(source_name, 0) + 1
        dropped_no_strategy_signal_tickers.add(ticker)
        return
    existing_entry = entries_by_ticker.get(ticker)
    if existing_entry is None or _replay_entry_richness(entry) > _replay_entry_richness(existing_entry):
        entries_by_ticker[ticker] = entry
        sources_by_ticker[ticker] = {source_name}


def _build_frozen_catalyst_replay_universe(
    *,
    plan: ExecutionPlan,
    report_dir: Path,
    trade_date_compact: str,
    strategy_signals_by_ticker: dict[str, dict[str, dict[str, Any]]],
) -> tuple[list[FusedScore], dict[str, Any]]:
    trade_dir = _selection_artifact_trade_dir(report_dir, trade_date_compact)
    replay_input_path = trade_dir / "selection_target_replay_input.json"
    selection_snapshot_path = trade_dir / "selection_snapshot.json"
    replay_input = _load_selection_replay_input_payload(report_dir, trade_date_compact)
    selection_snapshot = _load_selection_snapshot_payload(report_dir, trade_date_compact)
    filters = dict(dict((plan.risk_metrics or {}).get("funnel_diagnostics") or {}).get("filters") or {})
    fallback_market_state = selection_snapshot.get("market_state") or getattr(plan, "market_state", None)

    entries_by_ticker: dict[str, dict[str, Any]] = {}
    source_row_counts: dict[str, int] = {}
    sources_by_ticker: dict[str, set[str]] = {}
    dropped_no_strategy_signals_counts: dict[str, int] = {}
    dropped_no_strategy_signal_tickers: set[str] = set()

    for source_name, entries in (
        ("replay_input_watchlist", replay_input.get("watchlist") or []),
        ("replay_input_rejected_entries", replay_input.get("rejected_entries") or []),
        ("replay_input_supplemental_short_trade", replay_input.get("supplemental_short_trade_entries") or []),
        ("replay_input_supplemental_catalyst", replay_input.get("supplemental_catalyst_theme_entries") or []),
        ("replay_input_shadow_observation", replay_input.get("upstream_shadow_observation_entries") or []),
        ("snapshot_catalyst_selected", selection_snapshot.get("catalyst_theme_candidates") or []),
        ("snapshot_catalyst_shadow", selection_snapshot.get("catalyst_theme_shadow_candidates") or []),
        ("filter_watchlist", dict(filters.get("watchlist") or {}).get("tickers") or []),
        ("filter_watchlist_shadow", dict(filters.get("watchlist") or {}).get("released_shadow_entries") or []),
        ("filter_short_trade", dict(filters.get("short_trade_candidates") or {}).get("tickers") or []),
        ("filter_short_trade_shadow", dict(filters.get("short_trade_candidates") or {}).get("released_shadow_entries") or []),
        ("filter_short_trade_observation", dict(filters.get("short_trade_candidates") or {}).get("shadow_observation_entries") or []),
        ("filter_catalyst_selected", dict(filters.get("catalyst_theme_candidates") or {}).get("tickers") or []),
        ("filter_catalyst_shadow", dict(filters.get("catalyst_theme_candidates") or {}).get("shadow_candidates") or []),
        ("current_plan_watchlist", list(plan.watchlist or [])),
    ):
        for raw_entry in list(entries or []):
            _upsert_replay_entry(
                entries_by_ticker,
                raw_entry=raw_entry,
                source_name=source_name,
                source_row_counts=source_row_counts,
                sources_by_ticker=sources_by_ticker,
                strategy_signals_by_ticker=strategy_signals_by_ticker,
                dropped_no_strategy_signals_counts=dropped_no_strategy_signals_counts,
                dropped_no_strategy_signal_tickers=dropped_no_strategy_signal_tickers,
            )

    replay_universe: list[FusedScore] = []
    for ticker, entry in sorted(entries_by_ticker.items()):
        market_state = _resolve_replay_market_state(entry.get("market_state"), fallback_market_state=fallback_market_state)
        replay_universe.append(
            FusedScore(
                ticker=ticker,
                score_b=max(-1.0, min(1.0, float(entry.get("score_b", 0.0) or 0.0))),
                strategy_signals=_coerce_strategy_signal_models(_normalize_strategy_signals_payload(entry.get("strategy_signals"))),
                arbitration_applied=[],
                market_state=market_state,
                weights_used=dict(getattr(market_state, "adjusted_weights", {}) or {}),
                decision=str(entry.get("decision") or FusedScore.classify_decision(float(entry.get("score_b", 0.0) or 0.0))),
            )
        )

    return replay_universe, {
        "source_row_counts": source_row_counts,
        "source_ticker_counts": {source: sum(1 for tickers in sources_by_ticker.values() if source in tickers) for source in sorted(source_row_counts)},
        "dropped_no_strategy_signals_counts": dict(sorted(dropped_no_strategy_signals_counts.items())),
        "dropped_no_strategy_signal_tickers": sorted(dropped_no_strategy_signal_tickers),
        "missing_optional_inputs": [
            str(path.relative_to(report_dir))
            for path in (selection_snapshot_path, replay_input_path)
            if not path.exists()
        ],
        "replay_requires_strategy_signals": True,
        "replay_universe_count": len(replay_universe),
        "replay_universe_tickers": sorted(item.ticker for item in replay_universe),
    }


def _serialize_catalyst_theme_diagnostics_payload(payload: dict[str, Any]) -> dict[str, Any]:
    entries = [dict(entry or {}) for entry in list(payload.get("tickers") or [])]
    shadow_entries = [dict(entry or {}) for entry in list(payload.get("shadow_candidates") or [])]
    return {
        "candidate_count": int(payload.get("candidate_count", len(entries)) or 0),
        "shadow_candidate_count": int(payload.get("shadow_candidate_count", len(shadow_entries)) or 0),
        "selected_tickers": [str(entry.get("ticker") or "") for entry in entries if str(entry.get("ticker") or "").strip()],
        "shadow_tickers": [str(entry.get("ticker") or "") for entry in shadow_entries if str(entry.get("ticker") or "").strip()],
        "filtered_reason_counts": dict(payload.get("filtered_reason_counts") or {}),
        "reason_counts": dict(payload.get("reason_counts") or {}),
        "tickers": entries,
        "shadow_candidates": shadow_entries,
    }


def _build_baseline_catalyst_theme_diagnostics_payload(
    *,
    plan: ExecutionPlan,
    report_dir: Path,
    trade_date_compact: str,
    use_selection_snapshot_baseline: bool = False,
) -> dict[str, Any]:
    selection_snapshot_path = _selection_artifact_trade_dir(report_dir, trade_date_compact) / "selection_snapshot.json"
    selection_snapshot = _load_selection_snapshot_payload(report_dir, trade_date_compact)
    if use_selection_snapshot_baseline and selection_snapshot_path.exists():
        return {
            **_serialize_catalyst_theme_diagnostics_payload(
                {
                    "candidate_count": len(selection_snapshot.get("catalyst_theme_candidates") or []),
                    "shadow_candidate_count": len(selection_snapshot.get("catalyst_theme_shadow_candidates") or []),
                    "tickers": selection_snapshot.get("catalyst_theme_candidates") or [],
                    "shadow_candidates": selection_snapshot.get("catalyst_theme_shadow_candidates") or [],
                }
            ),
            "_baseline_source": "selection_snapshot",
        }
    catalyst_theme_filter = dict(dict(dict((plan.risk_metrics or {}).get("funnel_diagnostics") or {}).get("filters") or {}).get("catalyst_theme_candidates") or {})
    baseline_payload = {
        **_serialize_catalyst_theme_diagnostics_payload(
            {
                "candidate_count": len(list(catalyst_theme_filter.get("tickers") or [])),
                "shadow_candidate_count": len(list(catalyst_theme_filter.get("shadow_candidates") or [])),
                "tickers": list(catalyst_theme_filter.get("tickers") or []),
                "shadow_candidates": list(catalyst_theme_filter.get("shadow_candidates") or []),
            }
        ),
        "_baseline_source": "plan_funnel_diagnostics",
    }
    if use_selection_snapshot_baseline and not selection_snapshot_path.exists():
        baseline_payload["_baseline_fallback_reason"] = "selection_snapshot_requested_but_not_found"
    return baseline_payload


def _build_catalyst_theme_diagnostics_diff(
    *,
    baseline: dict[str, Any],
    rebuild: dict[str, Any],
) -> dict[str, Any]:
    baseline_selected = set(baseline.get("selected_tickers") or [])
    rebuilt_selected = set(rebuild.get("selected_tickers") or [])
    baseline_shadow = set(baseline.get("shadow_tickers") or [])
    rebuilt_shadow = set(rebuild.get("shadow_tickers") or [])

    baseline_entries = {str(entry.get("ticker") or ""): dict(entry or {}) for entry in list(baseline.get("tickers") or []) if str(entry.get("ticker") or "").strip()}
    rebuilt_entries = {str(entry.get("ticker") or ""): dict(entry or {}) for entry in list(rebuild.get("tickers") or []) if str(entry.get("ticker") or "").strip()}

    changed_selected_entries: list[dict[str, Any]] = []
    for ticker in sorted(baseline_selected & rebuilt_selected):
        baseline_entry = baseline_entries.get(ticker, {})
        rebuilt_entry = rebuilt_entries.get(ticker, {})
        baseline_quality = round(float(baseline_entry.get("quality_score", 0.0) or 0.0), 4)
        rebuilt_quality = round(float(rebuilt_entry.get("quality_score", 0.0) or 0.0), 4)
        baseline_market_state = str(dict(baseline_entry.get("market_state") or {}).get("state_type") or "")
        rebuilt_market_state = str(dict(rebuilt_entry.get("market_state") or {}).get("state_type") or "")
        if baseline_quality == rebuilt_quality and baseline_market_state == rebuilt_market_state:
            continue
        changed_selected_entries.append(
            {
                "ticker": ticker,
                "baseline_quality_score": baseline_quality,
                "rebuilt_quality_score": rebuilt_quality,
                "baseline_market_state_type": baseline_market_state,
                "rebuilt_market_state_type": rebuilt_market_state,
            }
        )

    return {
        "added_selected_tickers": sorted(rebuilt_selected - baseline_selected),
        "removed_selected_tickers": sorted(baseline_selected - rebuilt_selected),
        "added_shadow_tickers": sorted(rebuilt_shadow - baseline_shadow),
        "removed_shadow_tickers": sorted(baseline_shadow - rebuilt_shadow),
        "changed_selected_entries": changed_selected_entries,
    }


def rebuild_catalyst_theme_diagnostics_for_report(
    report_dir: str | Path,
    trade_date: str | None = None,
    *,
    use_selection_snapshot_baseline: bool = False,
) -> dict[str, Any]:
    resolved_report_dir = Path(report_dir).expanduser().resolve()
    daily_events_path = resolved_report_dir / "daily_events.jsonl"
    if not daily_events_path.exists():
        raise ValueError(f"Missing daily_events.jsonl at {daily_events_path}")
    plans_by_date = load_frozen_post_market_plans(daily_events_path)
    requested_trade_date = _normalize_trade_date_compact(trade_date)
    target_trade_dates = [requested_trade_date] if requested_trade_date else sorted(plans_by_date.keys())
    if requested_trade_date and requested_trade_date not in plans_by_date:
        raise ValueError(f"Missing current_plan in daily_events for trade_date={requested_trade_date}")

    results: list[dict[str, Any]] = []
    for trade_date_compact in target_trade_dates:
        plan = ExecutionPlan.model_validate(plans_by_date[trade_date_compact].model_dump(mode="json"))
        strategy_signals_by_ticker = _build_strategy_signals_lookup(
            plan,
            report_dir=resolved_report_dir,
            trade_date_compact=trade_date_compact,
        )
        replay_watchlist = _rehydrate_watchlist_strategy_signals(
            list(plan.watchlist or []),
            strategy_signals_by_ticker=strategy_signals_by_ticker,
        )
        replay_universe, source_summary = _build_frozen_catalyst_replay_universe(
            plan=plan,
            report_dir=resolved_report_dir,
            trade_date_compact=trade_date_compact,
            strategy_signals_by_ticker=strategy_signals_by_ticker,
        )
        short_trade_candidate_diagnostics = dict(
            dict(dict((plan.risk_metrics or {}).get("funnel_diagnostics") or {}).get("filters") or {}).get("short_trade_candidates") or {}
        )
        rebuilt_payload = _serialize_catalyst_theme_diagnostics_payload(
            _build_catalyst_theme_candidate_diagnostics(
                fused=replay_universe,
                watchlist=replay_watchlist,
                short_trade_candidate_diagnostics=short_trade_candidate_diagnostics,
                trade_date=trade_date_compact,
            )
        )
        baseline_payload = _build_baseline_catalyst_theme_diagnostics_payload(
            plan=plan,
            report_dir=resolved_report_dir,
            trade_date_compact=trade_date_compact,
            use_selection_snapshot_baseline=use_selection_snapshot_baseline,
        )
        diff_payload = _build_catalyst_theme_diagnostics_diff(
            baseline=baseline_payload,
            rebuild=rebuilt_payload,
        )
        artifact_payload = {
            "report_dir": str(resolved_report_dir),
            "trade_date": normalize_trade_date(trade_date_compact) or trade_date_compact,
            "source_summary": source_summary,
            "baseline": baseline_payload,
            "rebuild": rebuilt_payload,
            "diff": diff_payload,
        }
        artifact_path = _selection_artifact_trade_dir(resolved_report_dir, trade_date_compact) / CATALYST_THEME_DIAGNOSTICS_RERUN_FILENAME
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps(artifact_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(
            {
                "trade_date": artifact_payload["trade_date"],
                "artifact_path": str(artifact_path),
                "baseline_selected_tickers": baseline_payload["selected_tickers"],
                "rebuilt_selected_tickers": rebuilt_payload["selected_tickers"],
                "replay_universe_count": source_summary["replay_universe_count"],
            }
        )

    return {
        "report_dir": str(resolved_report_dir),
        "results": results,
        **({"artifact_path": results[0]["artifact_path"]} if len(results) == 1 else {}),
    }


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
        plan = _apply_rebuilt_catalyst_theme_filter(
            plan=plan,
            report_dir=resolved_report_dir,
            trade_date_compact=trade_date_compact,
        )
        shadow_lookup = _build_candidate_pool_shadow_lookup(raw_plans_by_date.get(trade_date_compact) or {})
        strategy_signals_by_ticker = _build_strategy_signals_lookup(
            plan,
            report_dir=resolved_report_dir,
            trade_date_compact=trade_date_compact,
        )
        refreshed_plan = rebuild_selection_targets_for_plan(
            plan,
            trade_date_compact,
            shadow_lookup,
            historical_prior_by_ticker=_load_latest_historical_prior_by_ticker(resolved_report_dir),
            strategy_signals_by_ticker=strategy_signals_by_ticker,
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


def _discover_unique_report_dirs(input_paths: list[str], *, report_name_contains: str) -> list[Path]:
    report_dirs: list[Path] = []
    for raw_input in input_paths:
        report_dirs.extend(discover_report_dirs(raw_input, report_name_contains=report_name_contains))
    seen: set[Path] = set()
    return [path for path in report_dirs if not (path in seen or seen.add(path))]


def _print_refresh_result(result: dict[str, Any], *, report_dir: Path, refresh_followup: bool) -> None:
    print(f"report_dir={result['report_dir']}")
    print(f"daily_events_path={result['daily_events_path']}")
    for trade_result in result["results"]:
        print(f"trade_date={trade_result['trade_date']}")
        print(f"write_status={trade_result['write_status']}")
        print(f"snapshot_path={trade_result['snapshot_path']}")
        print(f"replay_input_path={trade_result['replay_input_path']}")
        print(f"short_trade_selected_symbols={','.join(trade_result['short_trade_selected_symbols'])}")
        if refresh_followup:
            followup = generate_and_register_btst_followup_artifacts(
                report_dir=report_dir,
                trade_date=trade_result["trade_date"],
            )
            print(f"btst_brief_json={followup['brief_json']}")
            print(f"btst_execution_card_json={followup['execution_card_json']}")


def _collect_reports_root_refreshes(
    report_dir: Path,
    *,
    refresh_manifest: bool,
    refresh_control_tower: bool,
    manifest_roots: set[Path],
    control_tower_roots: set[Path],
) -> None:
    reports_root = report_dir.parent
    if reports_root.name != "reports":
        return
    if refresh_manifest:
        manifest_roots.add(reports_root)
    if refresh_control_tower:
        control_tower_roots.add(reports_root)


def _refresh_reports_root_artifacts(*, manifest_roots: set[Path], control_tower_roots: set[Path]) -> None:
    for reports_root in sorted(manifest_roots):
        manifest = generate_reports_manifest_artifacts(reports_root=reports_root)
        print(f"manifest_json={manifest['json_path']}")
    for reports_root in sorted(control_tower_roots):
        control_tower = generate_btst_nightly_control_tower_artifacts(reports_root=reports_root)
        print(f"nightly_control_tower_json={control_tower['json_path']}")


def main() -> None:
    args = parse_args()
    unique_report_dirs = _discover_unique_report_dirs(args.input_paths, report_name_contains=args.report_name_contains)
    if not unique_report_dirs:
        raise SystemExit("No report directories found for selection artifact refresh.")

    reports_roots_to_refresh_manifest: set[Path] = set()
    reports_roots_to_refresh_control_tower: set[Path] = set()
    for report_dir in unique_report_dirs:
        result = refresh_selection_artifacts_for_report(report_dir, trade_date=args.trade_date)
        _print_refresh_result(result, report_dir=report_dir, refresh_followup=args.refresh_followup)
        _collect_reports_root_refreshes(
            report_dir,
            refresh_manifest=args.refresh_manifest,
            refresh_control_tower=args.refresh_control_tower,
            manifest_roots=reports_roots_to_refresh_manifest,
            control_tower_roots=reports_roots_to_refresh_control_tower,
        )
    _refresh_reports_root_artifacts(
        manifest_roots=reports_roots_to_refresh_manifest,
        control_tower_roots=reports_roots_to_refresh_control_tower,
    )


if __name__ == "__main__":
    main()
