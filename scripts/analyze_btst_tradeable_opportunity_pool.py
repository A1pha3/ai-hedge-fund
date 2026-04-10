from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.btst_analysis_utils import extract_btst_price_outcome
from scripts.btst_data_utils import round_or_none, safe_float
from scripts.btst_report_utils import discover_nested_report_dirs, discover_report_dirs, normalize_trade_date, safe_load_json
from src.project_env import load_project_dotenv
from src.screening.candidate_pool import MIN_ESTIMATED_AMOUNT_1D, MIN_LISTING_DAYS, get_cooled_tickers, is_beijing_exchange_stock
from src.tools.tushare_api import get_all_stock_basic, get_daily_basic_batch, get_daily_price_batch, get_limit_list, get_open_trade_dates, get_suspend_list


load_project_dotenv()


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tradeable_opportunity_pool_march.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tradeable_opportunity_pool_march.md"
DEFAULT_OUTPUT_CSV = REPORTS_DIR / "btst_tradeable_opportunity_pool_march.csv"
DEFAULT_WATERFALL_JSON = REPORTS_DIR / "btst_tradeable_opportunity_reason_waterfall_march.json"
DEFAULT_WATERFALL_MD = REPORTS_DIR / "btst_tradeable_opportunity_reason_waterfall_march.md"

INTRADAY_STRONG_THRESHOLD = 0.05
CLOSE_CONTINUATION_THRESHOLD = 0.03
STRICT_BTST_GOAL_THRESHOLD = 0.05
EXTREME_NEXT_OPEN_GAP_THRESHOLD = 0.095
ONE_WORD_BOARD_THRESHOLD = 0.095

KILL_SWITCH_ORDER: tuple[str, ...] = (
    "universe_prefilter",
    "day0_limit_up_excluded",
    "no_candidate_entry",
    "candidate_entry_filtered",
    "boundary_filtered",
    "score_fail",
    "structural_block",
    "execution_contract_only",
    "selected_or_near_miss",
)

SELECTION_TARGET_RANK = {
    "short_trade_only": 3,
    "dual_target": 2,
    "research_only": 1,
}

MODE_RANK = {
    "live_pipeline": 3,
    "paper_trading": 2,
    "frozen_current_plan_replay": 1,
    "frozen_replay": 1,
}

THEME_RESEARCH_SOURCES = {"catalyst_theme", "catalyst_theme_shadow"}
THEME_RESEARCH_ENTRY_MODES = {"theme_research_followup", "watchlist_recheck"}
EXECUTION_PROXY_GATES = {"proxy_only", "shadow"}
NO_CANDIDATE_ENTRY_TOP_TICKER_LIMIT = 8
NO_CANDIDATE_ENTRY_TOP_PRIORITY_LIMIT = 8


def _parse_trade_dates(raw: str | None) -> set[str]:
    if raw is None or not str(raw).strip():
        return set()
    return {
        value
        for value in (normalize_trade_date(token) for token in str(raw).split(","))
        if value
    }


def _trade_date_in_scope(
    trade_date: str,
    *,
    explicit_trade_dates: set[str],
    start_date: str | None,
    end_date: str | None,
) -> bool:
    if explicit_trade_dates and trade_date not in explicit_trade_dates:
        return False
    if start_date and trade_date < start_date:
        return False
    if end_date and trade_date > end_date:
        return False
    return True


def _compact_trade_date(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _infer_report_mode(session_summary: dict[str, Any], report_dir_name: str) -> str:
    plan_generation = dict(session_summary.get("plan_generation") or {})
    mode = str(plan_generation.get("mode") or session_summary.get("mode") or "").strip()
    if mode:
        return mode
    lowered = report_dir_name.lower()
    if "frozen" in lowered:
        return "frozen_current_plan_replay"
    return "live_pipeline"


def _estimate_listing_days(list_date: str, trade_date: str) -> int:
    try:
        listed_at = datetime.strptime(_compact_trade_date(list_date), "%Y%m%d")
        traded_at = datetime.strptime(_compact_trade_date(trade_date), "%Y%m%d")
    except (TypeError, ValueError):
        return 0
    natural_days = (traded_at - listed_at).days
    return max(0, int(natural_days * 0.7))


def _estimate_amount_from_daily_basic(row: dict[str, Any] | None) -> float | None:
    if not row:
        return None
    turnover_rate = safe_float(row.get("turnover_rate"))
    circ_mv = safe_float(row.get("circ_mv"))
    if turnover_rate is None or circ_mv is None:
        return None
    return round(max(0.0, circ_mv * turnover_rate / 100.0), 4)


def _normalize_dict(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _ticker_entry_map(entries: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in list(entries or []):
        ticker = str(entry.get("ticker") or "").strip()
        if ticker:
            result[ticker] = dict(entry)
    return result


def _safe_path(path: str | Path | None) -> Path | None:
    if not path:
        return None
    return Path(path).expanduser().resolve()


def _load_daily_event_funnel(report_dir: Path, trade_date: str) -> dict[str, Any]:
    daily_events_path = report_dir / "daily_events.jsonl"
    if not daily_events_path.exists():
        return {}

    target_compact = _compact_trade_date(trade_date)
    for line in daily_events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload_trade_date = normalize_trade_date(
            payload.get("trade_date")
            or dict(payload.get("current_plan") or {}).get("trade_date")
            or dict(payload.get("prepared_plan") or {}).get("trade_date")
        )
        if payload_trade_date and _compact_trade_date(payload_trade_date) != target_compact:
            continue

        current_plan = dict(payload.get("current_plan") or {})
        funnel = dict(current_plan.get("funnel_diagnostics") or payload.get("funnel_diagnostics") or {})
        if funnel:
            return funnel
    return {}


def _select_report_trade_date_contexts(
    reports_root: str | Path,
    *,
    explicit_trade_dates: set[str],
    start_date: str | None,
    end_date: str | None,
) -> dict[str, dict[str, Any]]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    candidate_dirs = discover_report_dirs(resolved_reports_root, report_name_prefix="paper_trading")
    if not candidate_dirs:
        candidate_dirs = discover_nested_report_dirs([resolved_reports_root], report_name_contains="paper_trading")

    selected: dict[str, dict[str, Any]] = {}
    for report_dir in candidate_dirs:
        session_summary = safe_load_json(report_dir / "session_summary.json")
        plan_generation = dict(session_summary.get("plan_generation") or {})
        selection_target = str(plan_generation.get("selection_target") or session_summary.get("selection_target") or "") or None
        mode = _infer_report_mode(session_summary, report_dir.name)
        selection_root = report_dir / "selection_artifacts"
        if not selection_root.exists():
            continue

        for day_dir in sorted(path for path in selection_root.iterdir() if path.is_dir()):
            trade_date = normalize_trade_date(day_dir.name)
            if not trade_date or not _trade_date_in_scope(
                trade_date,
                explicit_trade_dates=explicit_trade_dates,
                start_date=start_date,
                end_date=end_date,
            ):
                continue

            snapshot_path = day_dir / "selection_snapshot.json"
            replay_input_path = day_dir / "selection_target_replay_input.json"
            if not snapshot_path.exists() and not replay_input_path.exists() and not (report_dir / "daily_events.jsonl").exists():
                continue

            candidate = {
                "trade_date": trade_date,
                "report_dir": report_dir,
                "report_dir_name": report_dir.name,
                "selection_target": selection_target,
                "mode": mode,
                "session_summary": session_summary,
                "selection_snapshot_path": snapshot_path if snapshot_path.exists() else None,
                "replay_input_path": replay_input_path if replay_input_path.exists() else None,
                "rank": (
                    int(SELECTION_TARGET_RANK.get(str(selection_target or ""), 0)),
                    int(MODE_RANK.get(mode, 0)),
                    int(report_dir.stat().st_mtime_ns),
                    report_dir.name,
                ),
            }
            previous = selected.get(trade_date)
            if previous is None or candidate["rank"] > previous["rank"]:
                selected[trade_date] = candidate

    result: dict[str, dict[str, Any]] = {}
    for trade_date, candidate in selected.items():
        selection_snapshot = safe_load_json(candidate.get("selection_snapshot_path"))
        replay_input = safe_load_json(candidate.get("replay_input_path"))
        funnel_diagnostics = dict(selection_snapshot.get("funnel_diagnostics") or {})
        if not funnel_diagnostics:
            funnel_diagnostics = _load_daily_event_funnel(candidate["report_dir"], trade_date)
        filters = dict(funnel_diagnostics.get("filters") or {})

        context = {
            "trade_date": trade_date,
            "report_dir": candidate["report_dir"],
            "report_dir_name": candidate["report_dir_name"],
            "selection_target": candidate.get("selection_target"),
            "mode": candidate.get("mode"),
            "selection_targets": _normalize_dict(selection_snapshot.get("selection_targets") or replay_input.get("selection_targets") or {}),
            "watchlist_filters_by_ticker": _ticker_entry_map(dict(filters.get("watchlist") or {}).get("tickers")),
            "layer_b_filters_by_ticker": _ticker_entry_map(dict(filters.get("layer_b") or {}).get("tickers")),
            "short_trade_candidates_by_ticker": _ticker_entry_map(dict(filters.get("short_trade_candidates") or {}).get("tickers")),
            "buy_order_filters_by_ticker": _ticker_entry_map(dict(filters.get("buy_orders") or {}).get("tickers")),
            "replay_rejected_by_ticker": _ticker_entry_map(replay_input.get("rejected_entries")),
            "replay_short_trade_by_ticker": _ticker_entry_map(replay_input.get("supplemental_short_trade_entries")),
            "blocked_buy_tickers": {
                str(ticker): dict(payload or {})
                for ticker, payload in dict(funnel_diagnostics.get("blocked_buy_tickers") or {}).items()
            },
            "buy_order_tickers": {str(ticker) for ticker in list(replay_input.get("buy_order_tickers") or []) if str(ticker).strip()},
        }
        result[trade_date] = context
    return result


def _resolve_stage_from_context(ticker: str, context: dict[str, Any]) -> str | None:
    if ticker in context.get("selection_targets", {}):
        return "selection_target"
    if ticker in context.get("replay_short_trade_by_ticker", {}) or ticker in context.get("short_trade_candidates_by_ticker", {}):
        return "short_trade_candidate"
    if ticker in context.get("replay_rejected_by_ticker", {}) or ticker in context.get("watchlist_filters_by_ticker", {}):
        return "candidate_entry"
    if ticker in context.get("layer_b_filters_by_ticker", {}):
        return "boundary"
    if ticker in context.get("blocked_buy_tickers", {}) or ticker in context.get("buy_order_filters_by_ticker", {}):
        return "execution"
    return None


def _resolve_system_view(ticker: str, context: dict[str, Any] | None) -> dict[str, Any]:
    if not context:
        return {
            "system_recalled": False,
            "system_seen_stage": None,
            "candidate_source": None,
            "candidate_reason_codes": [],
            "decision": None,
            "score_target": None,
            "preferred_entry_mode": None,
            "blockers": [],
            "gate_status": {},
            "delta_classification": None,
            "blocked_buy_details": {},
            "buy_order_filter": {},
            "selected_or_near_miss": False,
            "report_dir_name": None,
            "selection_target": None,
            "mode": None,
        }

    evaluation = dict(context.get("selection_targets", {}).get(ticker) or {})
    short_trade = dict(evaluation.get("short_trade") or {})
    explainability_payload = dict(short_trade.get("explainability_payload") or {})
    replay_short_trade = dict(context.get("replay_short_trade_by_ticker", {}).get(ticker) or {})
    replay_rejected = dict(context.get("replay_rejected_by_ticker", {}).get(ticker) or {})
    watchlist_filter = dict(context.get("watchlist_filters_by_ticker", {}).get(ticker) or {})
    layer_b_filter = dict(context.get("layer_b_filters_by_ticker", {}).get(ticker) or {})
    short_trade_candidate = dict(context.get("short_trade_candidates_by_ticker", {}).get(ticker) or {})
    buy_order_filter = dict(context.get("buy_order_filters_by_ticker", {}).get(ticker) or {})
    blocked_buy_details = dict(context.get("blocked_buy_tickers", {}).get(ticker) or {})

    fallback_entry = replay_short_trade or replay_rejected or short_trade_candidate or watchlist_filter or layer_b_filter
    candidate_source = (
        evaluation.get("candidate_source")
        or explainability_payload.get("candidate_source")
        or fallback_entry.get("candidate_source")
        or ("layer_b_boundary" if layer_b_filter else None)
        or ("watchlist_filter_diagnostics" if watchlist_filter or replay_rejected else None)
        or ("short_trade_boundary" if replay_short_trade or short_trade_candidate else None)
    )
    candidate_reason_codes = list(evaluation.get("candidate_reason_codes") or fallback_entry.get("candidate_reason_codes") or fallback_entry.get("reasons") or [])
    blockers = list(short_trade.get("blockers") or fallback_entry.get("blockers") or [])
    gate_status = dict(short_trade.get("gate_status") or fallback_entry.get("gate_status") or {})
    preferred_entry_mode = short_trade.get("preferred_entry_mode") or fallback_entry.get("preferred_entry_mode")
    decision = short_trade.get("decision")
    selected_or_near_miss = decision in {"selected", "near_miss"}

    return {
        "system_recalled": bool(
            evaluation
            or replay_short_trade
            or replay_rejected
            or watchlist_filter
            or layer_b_filter
            or short_trade_candidate
            or buy_order_filter
            or blocked_buy_details
        ),
        "system_seen_stage": _resolve_stage_from_context(ticker, context),
        "candidate_source": candidate_source,
        "candidate_reason_codes": candidate_reason_codes,
        "decision": decision,
        "score_target": round_or_none(safe_float(short_trade.get("score_target"))),
        "preferred_entry_mode": preferred_entry_mode,
        "blockers": blockers,
        "gate_status": gate_status,
        "delta_classification": evaluation.get("delta_classification"),
        "blocked_buy_details": blocked_buy_details,
        "buy_order_filter": buy_order_filter,
        "selected_or_near_miss": selected_or_near_miss,
        "report_dir_name": context.get("report_dir_name"),
        "selection_target": context.get("selection_target"),
        "mode": context.get("mode"),
    }


def _is_execution_contract_only(system_view: dict[str, Any]) -> bool:
    candidate_source = str(system_view.get("candidate_source") or "")
    preferred_entry_mode = str(system_view.get("preferred_entry_mode") or "")
    gate_status = dict(system_view.get("gate_status") or {})
    blocked_buy_details = dict(system_view.get("blocked_buy_details") or {})
    buy_order_filter = dict(system_view.get("buy_order_filter") or {})
    execution_gate = str(gate_status.get("execution") or gate_status.get("score") or "")

    return bool(
        blocked_buy_details
        or buy_order_filter
        or candidate_source in THEME_RESEARCH_SOURCES
        or preferred_entry_mode in THEME_RESEARCH_ENTRY_MODES
        or execution_gate in EXECUTION_PROXY_GATES
    )


def _is_structural_block(system_view: dict[str, Any]) -> bool:
    blockers = {str(blocker) for blocker in list(system_view.get("blockers") or []) if str(blocker).strip()}
    gate_status = dict(system_view.get("gate_status") or {})
    return bool(blockers.intersection({"layer_c_bearish_conflict", "trend_not_constructive", "stale_trend_repair_penalty", "overhead_supply_penalty", "extension_without_room_penalty"})) or str(gate_status.get("structural") or "") == "fail"


def _classify_system_kill_switch(system_view: dict[str, Any]) -> str:
    if not system_view.get("system_recalled"):
        return "no_candidate_entry"
    if _is_execution_contract_only(system_view):
        return "execution_contract_only"
    if system_view.get("selected_or_near_miss"):
        return "selected_or_near_miss"
    if _is_structural_block(system_view):
        return "structural_block"

    candidate_source = str(system_view.get("candidate_source") or "")
    stage = str(system_view.get("system_seen_stage") or "")
    gate_status = dict(system_view.get("gate_status") or {})
    decision = str(system_view.get("decision") or "")

    if candidate_source in {"watchlist_filter_diagnostics", "layer_c_watchlist"} or stage == "candidate_entry":
        return "candidate_entry_filtered"
    if candidate_source == "layer_b_boundary" or stage == "boundary":
        return "boundary_filtered"
    if candidate_source == "short_trade_boundary" or stage in {"selection_target", "short_trade_candidate"}:
        if str(gate_status.get("score") or "") == "fail" or decision == "rejected":
            return "score_fail"
        return "boundary_filtered"
    return "candidate_entry_filtered"


def _detect_tradeability_notes(price_outcome: dict[str, Any]) -> list[str]:
    next_open_return = safe_float(price_outcome.get("next_open_return"))
    next_high = safe_float(price_outcome.get("next_high"))
    next_open = safe_float(price_outcome.get("next_open"))
    next_close = safe_float(price_outcome.get("next_close"))
    next_close_return = safe_float(price_outcome.get("next_close_return"))
    notes: list[str] = []
    if next_open_return is not None and next_open_return >= EXTREME_NEXT_OPEN_GAP_THRESHOLD:
        notes.append("t_plus_1_extreme_open_gap")
    if (
        next_open is not None
        and next_high is not None
        and next_close is not None
        and next_close_return is not None
        and next_close_return >= ONE_WORD_BOARD_THRESHOLD
        and round(next_open, 4) == round(next_high, 4) == round(next_close, 4)
    ):
        notes.append("t_plus_1_one_word_board")
    return notes


def _build_result_truth_labels(price_outcome: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    next_high_return = safe_float(price_outcome.get("next_high_return"))
    next_close_return = safe_float(price_outcome.get("next_close_return"))
    t_plus_2_close_return = safe_float(price_outcome.get("t_plus_2_close_return"))
    if next_high_return is not None and next_high_return >= INTRADAY_STRONG_THRESHOLD:
        labels.append("intraday_strong")
    if next_close_return is not None and next_close_return >= CLOSE_CONTINUATION_THRESHOLD:
        labels.append("close_continuation_strong")
    if t_plus_2_close_return is not None and t_plus_2_close_return >= STRICT_BTST_GOAL_THRESHOLD:
        labels.append("strict_btst_goal_case")
    return labels


def _build_market_price_batches(active_trade_dates: list[str]) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, list[str]]]:
    compact_trade_dates = sorted({_compact_trade_date(trade_date) for trade_date in active_trade_dates if _compact_trade_date(trade_date)})
    if not compact_trade_dates:
        return {}, {}

    calendar_end = (pd.Timestamp(normalize_trade_date(compact_trade_dates[-1])) + pd.Timedelta(days=15)).strftime("%Y%m%d")
    open_trade_dates = get_open_trade_dates(compact_trade_dates[0], calendar_end)
    if not open_trade_dates:
        return {}, {}

    price_batches_by_trade_date: dict[str, dict[str, dict[str, Any]]] = {}
    for batch_trade_date in open_trade_dates:
        frame = get_daily_price_batch(batch_trade_date)
        if frame is None or frame.empty:
            price_batches_by_trade_date[batch_trade_date] = {}
            continue
        price_batches_by_trade_date[batch_trade_date] = {
            str(row["ts_code"]): row.to_dict()
            for _, row in frame.iterrows()
            if str(row.get("ts_code") or "").strip()
        }

    future_trade_dates_by_trade_date = {
        trade_date: [future_trade_date for future_trade_date in open_trade_dates if future_trade_date > trade_date]
        for trade_date in compact_trade_dates
    }
    return price_batches_by_trade_date, future_trade_dates_by_trade_date


def _extract_batched_btst_price_outcome(
    ts_code: str,
    trade_date: str,
    price_batches_by_trade_date: dict[str, dict[str, dict[str, Any]]],
    future_trade_dates_by_trade_date: dict[str, list[str]],
) -> dict[str, Any]:
    compact_trade_date = _compact_trade_date(trade_date)
    trade_row = dict(price_batches_by_trade_date.get(compact_trade_date, {}).get(ts_code) or {})
    if not trade_row:
        return {
            "data_status": "missing_trade_day_bar",
            "cycle_status": "missing_next_day",
        }

    trade_close = safe_float(trade_row.get("close"))
    if trade_close is None or trade_close <= 0:
        return {
            "data_status": "missing_trade_day_bar",
            "cycle_status": "missing_next_day",
        }

    future_rows: list[tuple[str, dict[str, Any]]] = []
    for future_trade_date in future_trade_dates_by_trade_date.get(compact_trade_date, []):
        future_row = dict(price_batches_by_trade_date.get(future_trade_date, {}).get(ts_code) or {})
        if future_row:
            future_rows.append((future_trade_date, future_row))
            if len(future_rows) >= 2:
                break

    if not future_rows:
        return {
            "data_status": "missing_next_trade_day_bar",
            "trade_close": round_or_none(trade_close),
            "cycle_status": "missing_next_day",
        }

    next_trade_date, next_row = future_rows[0]
    next_open = safe_float(next_row.get("open"))
    next_high = safe_float(next_row.get("high"))
    next_close = safe_float(next_row.get("close"))
    if trade_close is None or trade_close <= 0 or next_open is None or next_high is None or next_close is None:
        return {
            "data_status": "incomplete_next_trade_day_bar",
            "cycle_status": "missing_next_day",
        }

    t_plus_2_trade_date = None
    t_plus_2_close = None
    if len(future_rows) > 1:
        t_plus_2_trade_date, t_plus_2_row = future_rows[1]
        t_plus_2_close = safe_float(t_plus_2_row.get("close"))

    data_status = "ok" if t_plus_2_close is not None else "missing_t_plus_2_bar"
    cycle_status = "closed_cycle" if t_plus_2_close is not None else "t1_only"
    return {
        "data_status": data_status,
        "cycle_status": cycle_status,
        "trade_close": round(trade_close, 4),
        "next_trade_date": normalize_trade_date(next_trade_date),
        "next_open": round(next_open, 4),
        "next_high": round(next_high, 4),
        "next_close": round(next_close, 4),
        "next_open_return": round((next_open / trade_close) - 1.0, 4),
        "next_high_return": round((next_high / trade_close) - 1.0, 4),
        "next_close_return": round((next_close / trade_close) - 1.0, 4),
        "next_open_to_close_return": round((next_close / next_open) - 1.0, 4),
        "t_plus_2_trade_date": normalize_trade_date(t_plus_2_trade_date),
        "t_plus_2_close": round_or_none(t_plus_2_close),
        "t_plus_2_close_return": None if t_plus_2_close is None else round((t_plus_2_close / trade_close) - 1.0, 4),
    }


def _build_trade_date_rows(
    trade_date: str,
    *,
    stock_basic: pd.DataFrame,
    daily_basic: pd.DataFrame | None,
    limit_list: pd.DataFrame | None,
    suspend_list: pd.DataFrame | None,
    cooled_tickers: set[str],
    report_context: dict[str, Any] | None,
    price_cache: dict[tuple[str, str], pd.DataFrame],
    price_batches_by_trade_date: dict[str, dict[str, dict[str, Any]]] | None = None,
    future_trade_dates_by_trade_date: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    trade_date_context = _build_trade_date_context(daily_basic, limit_list, suspend_list)
    rows: list[dict[str, Any]] = []
    compact_trade_date = _compact_trade_date(trade_date)
    for _, stock_row in stock_basic.iterrows():
        row = _build_trade_date_row(
            trade_date=trade_date,
            compact_trade_date=compact_trade_date,
            stock_row=stock_row,
            cooled_tickers=cooled_tickers,
            report_context=report_context,
            price_cache=price_cache,
            price_batches_by_trade_date=price_batches_by_trade_date,
            future_trade_dates_by_trade_date=future_trade_dates_by_trade_date,
            trade_date_context=trade_date_context,
        )
        if row:
            rows.append(row)
    return rows


def _build_trade_date_context(
    daily_basic: pd.DataFrame | None,
    limit_list: pd.DataFrame | None,
    suspend_list: pd.DataFrame | None,
) -> dict[str, Any]:
    normalized_daily_basic = daily_basic if daily_basic is not None else pd.DataFrame()
    normalized_limit_list = limit_list if limit_list is not None else pd.DataFrame()
    normalized_suspend_list = suspend_list if suspend_list is not None else pd.DataFrame()
    return {
        "daily_basic_by_ts": {
            str(row["ts_code"]): row.to_dict()
            for _, row in normalized_daily_basic.iterrows()
            if str(row.get("ts_code") or "").strip()
        },
        "suspend_codes": {str(value) for value in list(normalized_suspend_list.get("ts_code", [])) if str(value).strip()},
        "limit_up_codes": {
            str(row.get("ts_code") or "")
            for _, row in normalized_limit_list.iterrows()
            if str(row.get("limit") or "") == "U" and str(row.get("ts_code") or "").strip()
        },
    }


def _build_trade_date_row(
    *,
    trade_date: str,
    compact_trade_date: str,
    stock_row: pd.Series,
    cooled_tickers: set[str],
    report_context: dict[str, Any] | None,
    price_cache: dict[tuple[str, str], pd.DataFrame],
    price_batches_by_trade_date: dict[str, dict[str, dict[str, Any]]] | None,
    future_trade_dates_by_trade_date: dict[str, list[str]] | None,
    trade_date_context: dict[str, Any],
) -> dict[str, Any] | None:
    symbol = str(stock_row.get("symbol") or "").strip()
    ts_code = str(stock_row.get("ts_code") or "").strip()
    if not symbol or not ts_code:
        return None
    price_outcome = _resolve_trade_date_price_outcome(
        symbol=symbol,
        ts_code=ts_code,
        trade_date=trade_date,
        price_cache=price_cache,
        price_batches_by_trade_date=price_batches_by_trade_date,
        future_trade_dates_by_trade_date=future_trade_dates_by_trade_date,
    )
    result_truth_labels = _build_result_truth_labels(price_outcome)
    if not result_truth_labels:
        return None
    stock_context = _build_trade_date_stock_context(
        stock_row=stock_row,
        symbol=symbol,
        ts_code=ts_code,
        compact_trade_date=compact_trade_date,
        cooled_tickers=cooled_tickers,
        trade_date_context=trade_date_context,
    )
    system_view = _resolve_system_view(symbol, report_context)
    return _assemble_trade_date_row(
        trade_date=trade_date,
        symbol=symbol,
        ts_code=ts_code,
        stock_row=stock_row,
        stock_context=stock_context,
        system_view=system_view,
        result_truth_labels=result_truth_labels,
        price_outcome=price_outcome,
    )


def _resolve_trade_date_price_outcome(
    *,
    symbol: str,
    ts_code: str,
    trade_date: str,
    price_cache: dict[tuple[str, str], pd.DataFrame],
    price_batches_by_trade_date: dict[str, dict[str, dict[str, Any]]] | None,
    future_trade_dates_by_trade_date: dict[str, list[str]] | None,
) -> dict[str, Any]:
    if price_batches_by_trade_date:
        return _extract_batched_btst_price_outcome(
            ts_code,
            trade_date,
            price_batches_by_trade_date,
            future_trade_dates_by_trade_date or {},
        )
    return extract_btst_price_outcome(symbol, trade_date, price_cache)


def _build_trade_date_stock_context(
    *,
    stock_row: pd.Series,
    symbol: str,
    ts_code: str,
    compact_trade_date: str,
    cooled_tickers: set[str],
    trade_date_context: dict[str, Any],
) -> dict[str, Any]:
    name = str(stock_row.get("name") or "")
    market = str(stock_row.get("market") or "")
    list_date = _compact_trade_date(stock_row.get("list_date"))
    estimated_amount_1d = _estimate_amount_from_daily_basic(dict(trade_date_context["daily_basic_by_ts"]).get(ts_code))
    prefilter_reasons: list[str] = []
    if "ST" in name.upper():
        prefilter_reasons.append("st")
    if is_beijing_exchange_stock(ts_code=ts_code, symbol=symbol, market=market):
        prefilter_reasons.append("beijing_market")
    if _estimate_listing_days(list_date, compact_trade_date) < MIN_LISTING_DAYS:
        prefilter_reasons.append("new_listing")
    if ts_code in set(trade_date_context["suspend_codes"]):
        prefilter_reasons.append("suspended")
    if symbol in cooled_tickers:
        prefilter_reasons.append("cooldown")
    if estimated_amount_1d is not None and estimated_amount_1d < MIN_ESTIMATED_AMOUNT_1D:
        prefilter_reasons.append("low_estimated_liquidity")
    return {
        "name": name,
        "market": market,
        "list_date": list_date,
        "estimated_amount_1d": estimated_amount_1d,
        "prefilter_reasons": prefilter_reasons,
        "day0_limit_up_excluded": ts_code in set(trade_date_context["limit_up_codes"]),
    }


def _assemble_trade_date_row(
    *,
    trade_date: str,
    symbol: str,
    ts_code: str,
    stock_row: pd.Series,
    stock_context: dict[str, Any],
    system_view: dict[str, Any],
    result_truth_labels: list[str],
    price_outcome: dict[str, Any],
) -> dict[str, Any]:
    tradeability_notes = _detect_tradeability_notes(price_outcome)
    prefilter_reasons = list(stock_context["prefilter_reasons"])
    day0_limit_up_excluded = bool(stock_context["day0_limit_up_excluded"])
    pool_b_tradeable = not prefilter_reasons and not day0_limit_up_excluded and not tradeability_notes
    first_kill_switch = _resolve_first_kill_switch(prefilter_reasons, day0_limit_up_excluded, tradeability_notes, system_view)
    selected_or_near_miss = bool(system_view.get("selected_or_near_miss"))
    return {
        "trade_date": trade_date,
        "ticker": symbol,
        "ts_code": ts_code,
        "name": stock_context["name"],
        "industry": stock_row.get("industry"),
        "market": stock_context["market"],
        "list_date": normalize_trade_date(stock_context["list_date"]),
        "estimated_amount_1d": round_or_none(stock_context["estimated_amount_1d"]),
        "result_truth_labels": result_truth_labels,
        "intraday_strong": "intraday_strong" in result_truth_labels,
        "close_continuation_strong": "close_continuation_strong" in result_truth_labels,
        "strict_btst_goal_case": "strict_btst_goal_case" in result_truth_labels,
        "pool_a": True,
        "pool_b_tradeable": pool_b_tradeable,
        "pool_c_system_recalled": bool(pool_b_tradeable and system_view.get("system_recalled")),
        "selected_or_near_miss": selected_or_near_miss,
        "pool_d_main_execution_eligible": bool(pool_b_tradeable and first_kill_switch == "selected_or_near_miss"),
        "first_kill_switch": first_kill_switch,
        "universe_prefilter_reasons": prefilter_reasons,
        "tradeability_notes": tradeability_notes,
        "day0_limit_up_excluded": day0_limit_up_excluded,
        "system_seen_stage": system_view.get("system_seen_stage"),
        "candidate_source": system_view.get("candidate_source"),
        "candidate_reason_codes": list(system_view.get("candidate_reason_codes") or []),
        "short_trade_decision": system_view.get("decision"),
        "score_target": system_view.get("score_target"),
        "preferred_entry_mode": system_view.get("preferred_entry_mode"),
        "delta_classification": system_view.get("delta_classification"),
        "blockers": list(system_view.get("blockers") or []),
        "gate_status": dict(system_view.get("gate_status") or {}),
        "blocked_buy_details": dict(system_view.get("blocked_buy_details") or {}),
        "buy_order_filter": dict(system_view.get("buy_order_filter") or {}),
        "report_dir": system_view.get("report_dir_name"),
        "report_selection_target": system_view.get("selection_target"),
        "report_mode": system_view.get("mode"),
        **price_outcome,
    }


def _resolve_first_kill_switch(
    prefilter_reasons: list[str],
    day0_limit_up_excluded: bool,
    tradeability_notes: list[str],
    system_view: dict[str, Any],
) -> str:
    if prefilter_reasons:
        return "universe_prefilter"
    if day0_limit_up_excluded:
        return "day0_limit_up_excluded"
    if tradeability_notes:
        return "execution_contract_only"
    return _classify_system_kill_switch(system_view)


def _summarize_counter(counter: Counter[str], *, limit: int | None = None) -> dict[str, int]:
    pairs = counter.most_common(limit)
    return {key: int(value) for key, value in pairs}


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _row_priority_key(row: dict[str, Any]) -> tuple[float, float, float, float, str, str]:
    return (
        1.0 if row.get("strict_btst_goal_case") else 0.0,
        float(row.get("t_plus_2_close_return") if row.get("t_plus_2_close_return") is not None else -999.0),
        float(row.get("next_high_return") if row.get("next_high_return") is not None else -999.0),
        float(row.get("next_close_return") if row.get("next_close_return") is not None else -999.0),
        str(row.get("trade_date") or ""),
        str(row.get("ticker") or ""),
    )


def _bucket_estimated_amount_1d(amount: Any) -> str:
    estimated_amount = safe_float(amount)
    if estimated_amount is None:
        return "unknown"
    if estimated_amount < 5000:
        return "lt_5000w"
    if estimated_amount < 10000:
        return "5000w_to_10000w"
    if estimated_amount < 20000:
        return "10000w_to_20000w"
    return "gte_20000w"


def _classify_truth_pattern(row: dict[str, Any]) -> str:
    if row.get("strict_btst_goal_case"):
        return "strict_goal_case"
    if row.get("intraday_strong") and row.get("close_continuation_strong"):
        return "intraday_and_close_continuation"
    if row.get("intraday_strong"):
        return "intraday_only"
    if row.get("close_continuation_strong"):
        return "close_continuation_only"
    return "other_truth"


def _mean_metric(rows: list[dict[str, Any]], key: str) -> float | None:
    numeric_values = [
        float(value)
        for value in (safe_float(row.get(key)) for row in rows)
        if value is not None
    ]
    if not numeric_values:
        return None
    return round(sum(numeric_values) / len(numeric_values), 4)


def _build_no_candidate_entry_summary(tradeable_rows: list[dict[str, Any]]) -> dict[str, Any]:
    no_candidate_entry_rows = [
        row
        for row in tradeable_rows
        if str(row.get("first_kill_switch") or "") == "no_candidate_entry"
    ]
    if not no_candidate_entry_rows:
        return {
            "count": 0,
            "share_of_tradeable_pool": 0.0 if tradeable_rows else None,
            "strict_goal_case_count": 0,
            "strict_goal_case_share": None,
            "industry_counts": {},
            "trade_date_counts": {},
            "estimated_amount_bucket_counts": {},
            "truth_pattern_counts": {},
            "top_ticker_rows": [],
            "top_priority_rows": [],
            "recommendation": "当前 tradeable pool 中没有 no_candidate_entry 样本。",
        }

    industry_counts = Counter(str(row.get("industry") or "unknown") for row in no_candidate_entry_rows)
    trade_date_counts = Counter(str(row.get("trade_date") or "unknown") for row in no_candidate_entry_rows)
    estimated_amount_bucket_counts = Counter(_bucket_estimated_amount_1d(row.get("estimated_amount_1d")) for row in no_candidate_entry_rows)
    truth_pattern_counts = Counter(_classify_truth_pattern(row) for row in no_candidate_entry_rows)

    ticker_buckets: dict[str, list[dict[str, Any]]] = {}
    for row in no_candidate_entry_rows:
        ticker = str(row.get("ticker") or "")
        if ticker:
            ticker_buckets.setdefault(ticker, []).append(row)

    top_ticker_rows: list[dict[str, Any]] = []
    for ticker, ticker_rows in ticker_buckets.items():
        ticker_rows_sorted = sorted(ticker_rows, key=_row_priority_key, reverse=True)
        lead_row = ticker_rows_sorted[0]
        top_ticker_rows.append(
            {
                "ticker": ticker,
                "occurrence_count": len(ticker_rows),
                "strict_goal_case_count": sum(1 for row in ticker_rows if row.get("strict_btst_goal_case")),
                "industry": str(lead_row.get("industry") or "unknown"),
                "latest_trade_date": max(str(row.get("trade_date") or "") for row in ticker_rows),
                "trade_dates": sorted({str(row.get("trade_date") or "") for row in ticker_rows if str(row.get("trade_date") or "")}),
                "mean_next_high_return": _mean_metric(ticker_rows, "next_high_return"),
                "mean_next_close_return": _mean_metric(ticker_rows, "next_close_return"),
                "mean_t_plus_2_close_return": _mean_metric(ticker_rows, "t_plus_2_close_return"),
                "lead_truth_pattern": _classify_truth_pattern(lead_row),
            }
        )
    top_ticker_rows.sort(
        key=lambda row: (
            int(row.get("strict_goal_case_count") or 0),
            int(row.get("occurrence_count") or 0),
            float(row.get("mean_t_plus_2_close_return") if row.get("mean_t_plus_2_close_return") is not None else -999.0),
            float(row.get("mean_next_high_return") if row.get("mean_next_high_return") is not None else -999.0),
            str(row.get("ticker") or ""),
        ),
        reverse=True,
    )

    top_industries = [label for label, _ in industry_counts.most_common(3)]
    top_tickers = [str(row.get("ticker") or "") for row in top_ticker_rows[:3] if row.get("ticker")]
    if top_tickers:
        recommendation = f"no_candidate_entry 机会主要集中在 {top_industries}，优先围绕 {top_tickers} 回查 candidate entry semantics / watchlist 召回，而不是继续放松 score。"
    else:
        recommendation = f"no_candidate_entry 机会主要集中在 {top_industries}，应先补 candidate entry 召回先验，再决定是否扩展到 boundary。"

    strict_goal_case_count = sum(1 for row in no_candidate_entry_rows if row.get("strict_btst_goal_case"))
    return {
        "count": len(no_candidate_entry_rows),
        "share_of_tradeable_pool": _rate(len(no_candidate_entry_rows), len(tradeable_rows)),
        "strict_goal_case_count": strict_goal_case_count,
        "strict_goal_case_share": _rate(strict_goal_case_count, len(no_candidate_entry_rows)),
        "industry_counts": _summarize_counter(industry_counts, limit=10),
        "trade_date_counts": _summarize_counter(trade_date_counts, limit=10),
        "estimated_amount_bucket_counts": _summarize_counter(estimated_amount_bucket_counts, limit=10),
        "truth_pattern_counts": _summarize_counter(truth_pattern_counts, limit=10),
        "top_ticker_rows": top_ticker_rows[:NO_CANDIDATE_ENTRY_TOP_TICKER_LIMIT],
        "top_priority_rows": sorted(no_candidate_entry_rows, key=_row_priority_key, reverse=True)[:NO_CANDIDATE_ENTRY_TOP_PRIORITY_LIMIT],
        "recommendation": recommendation,
    }


def _build_waterfall(analysis: dict[str, Any]) -> dict[str, Any]:
    result_truth_pool_count = int(analysis.get("result_truth_pool_count") or 0)
    strict_goal_case_count = int(analysis.get("strict_goal_case_count") or 0)
    first_kill_switch_counts = Counter(dict(analysis.get("first_kill_switch_counts") or {}))
    strict_counts = Counter(dict(analysis.get("first_kill_switch_strict_goal_case_counts") or {}))
    tradeable_counts = Counter(dict(analysis.get("tradeable_pool_first_kill_switch_counts") or {}))

    ordered_labels = list(KILL_SWITCH_ORDER)
    for label in sorted(first_kill_switch_counts):
        if label not in ordered_labels:
            ordered_labels.append(label)

    waterfall_rows: list[dict[str, Any]] = []
    for label in ordered_labels:
        count = int(first_kill_switch_counts.get(label) or 0)
        if count <= 0:
            continue
        strict_count = int(strict_counts.get(label) or 0)
        tradeable_count = int(tradeable_counts.get(label) or 0)
        waterfall_rows.append(
            {
                "kill_switch": label,
                "count": count,
                "share_of_result_truth_pool": _rate(count, result_truth_pool_count),
                "strict_goal_case_count": strict_count,
                "share_of_strict_goal_cases": _rate(strict_count, strict_goal_case_count),
                "tradeable_pool_count": tradeable_count,
            }
        )

    false_negative_rows = list(analysis.get("top_false_negative_rows") or [])
    strict_false_negative_rows = list(analysis.get("top_strict_goal_false_negative_rows") or [])
    top_tradeable_kill_switches = sorted(
        [
            {"kill_switch": key, "count": int(value)}
            for key, value in tradeable_counts.items()
            if int(value) > 0
        ],
        key=lambda row: (-row["count"], KILL_SWITCH_ORDER.index(row["kill_switch"]) if row["kill_switch"] in KILL_SWITCH_ORDER else 999, row["kill_switch"]),
    )[:3]

    recommendation = str(analysis.get("recommendation") or "")
    return {
        "generated_at": analysis.get("generated_at"),
        "trade_dates": list(analysis.get("trade_dates") or []),
        "result_truth_pool_count": result_truth_pool_count,
        "tradeable_opportunity_pool_count": int(analysis.get("tradeable_opportunity_pool_count") or 0),
        "strict_goal_case_count": strict_goal_case_count,
        "tradeable_pool_capture_rate": analysis.get("tradeable_pool_capture_rate"),
        "tradeable_pool_selected_or_near_miss_rate": analysis.get("tradeable_pool_selected_or_near_miss_rate"),
        "top_tradeable_kill_switches": top_tradeable_kill_switches,
        "waterfall_rows": waterfall_rows,
        "candidate_source_false_negative_counts": dict(analysis.get("candidate_source_false_negative_counts") or {}),
        "industry_false_negative_counts": dict(analysis.get("industry_false_negative_counts") or {}),
        "top_false_negative_rows": false_negative_rows,
        "top_strict_goal_false_negative_rows": strict_false_negative_rows,
        "recommendation": recommendation,
    }


def _build_recommendation(
    *,
    tradeable_pool_count: int,
    tradeable_counts: Counter[str],
    capture_rate: float | None,
) -> str:
    if tradeable_pool_count <= 0:
        return "当前区间没有形成可交易机会池，请先检查日期范围、价格补齐或结果真值阈值。"
    top_kill_switch = tradeable_counts.most_common(1)[0][0] if tradeable_counts else "selected_or_near_miss"
    if capture_rate is not None and capture_rate < 0.3:
        if top_kill_switch == "no_candidate_entry":
            return "可交易机会主要在 candidate entry 之前丢失，先补短线入口召回，而不是继续微调 score。"
        if top_kill_switch == "candidate_entry_filtered":
            return "当前主瓶颈在 candidate entry selective 过滤，先审视 watchlist / rejected entry 语义。"
    if top_kill_switch in {"boundary_filtered", "score_fail"}:
        return "当前主瓶颈已经集中到 short-trade boundary / score frontier，优先沿 breakout-trend-catalyst 语义做前沿修复。"
    if top_kill_switch == "structural_block":
        return "当前主错杀簇已经转向结构冲突，适合继续做定点 structural release，而不是全局放松。"
    if top_kill_switch == "execution_contract_only":
        return "系统已经看见一部分机会，但仍停在执行 contract 之外，应把主执行池和研究观察池继续拆开。"
    return "当前 tradeable pool 已有一定保留，但仍需沿 top kill switch 继续收敛召回与执行语义。"


def analyze_btst_tradeable_opportunity_pool(
    reports_root: str | Path,
    *,
    trade_dates: set[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    explicit_trade_dates = {value for value in (trade_dates or set()) if value}
    normalized_start_date = normalize_trade_date(start_date) if start_date else None
    normalized_end_date = normalize_trade_date(end_date) if end_date else None
    resolved_reports_root = Path(reports_root).expanduser().resolve()

    report_contexts = _select_report_trade_date_contexts(
        resolved_reports_root,
        explicit_trade_dates=explicit_trade_dates,
        start_date=normalized_start_date,
        end_date=normalized_end_date,
    )
    active_trade_dates = sorted(explicit_trade_dates or set(report_contexts))
    if not active_trade_dates:
        return {
            "artifact_schema_version": 2,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "reports_root": resolved_reports_root.as_posix(),
            "trade_dates": [],
            "trade_date_contexts": {},
            "result_truth_pool_count": 0,
            "tradeable_opportunity_pool_count": 0,
            "system_recall_count": 0,
            "selected_or_near_miss_count": 0,
            "main_execution_pool_count": 0,
            "strict_goal_case_count": 0,
            "strict_goal_tradeable_count": 0,
            "strict_goal_false_negative_count": 0,
            "tradeable_pool_capture_rate": None,
            "tradeable_pool_selected_or_near_miss_rate": None,
            "tradeable_pool_main_execution_rate": None,
            "first_kill_switch_counts": {},
            "first_kill_switch_strict_goal_case_counts": {},
            "tradeable_pool_first_kill_switch_counts": {},
            "candidate_source_false_negative_counts": {},
            "industry_false_negative_counts": {},
            "no_candidate_entry_summary": {
                "count": 0,
                "share_of_tradeable_pool": None,
                "strict_goal_case_count": 0,
                "strict_goal_case_share": None,
                "industry_counts": {},
                "trade_date_counts": {},
                "estimated_amount_bucket_counts": {},
                "truth_pattern_counts": {},
                "top_ticker_rows": [],
                "top_priority_rows": [],
                "recommendation": "当前 tradeable pool 中没有 no_candidate_entry 样本。",
            },
            "top_false_negative_rows": [],
            "top_strict_goal_false_negative_rows": [],
            "recommendation": "当前没有可分析的 trade_date，上游报告目录尚未提供 selection artifacts。",
            "rows": [],
        }

    stock_basic = get_all_stock_basic()
    if stock_basic is None or stock_basic.empty:
        raise RuntimeError("无法加载全市场 stock_basic，无法构建结果真值池。")

    rows: list[dict[str, Any]] = []
    price_cache: dict[tuple[str, str], pd.DataFrame] = {}
    price_batches_by_trade_date, future_trade_dates_by_trade_date = _build_market_price_batches(active_trade_dates)
    trade_date_contexts: dict[str, dict[str, Any]] = {}
    for trade_date in active_trade_dates:
        daily_basic = get_daily_basic_batch(_compact_trade_date(trade_date))
        limit_list = get_limit_list(_compact_trade_date(trade_date))
        suspend_list = get_suspend_list(_compact_trade_date(trade_date))
        cooled_tickers = set(get_cooled_tickers(_compact_trade_date(trade_date)))
        report_context = report_contexts.get(trade_date)
        trade_date_contexts[trade_date] = {
            "report_dir": dict(report_context or {}).get("report_dir_name"),
            "selection_target": dict(report_context or {}).get("selection_target"),
            "mode": dict(report_context or {}).get("mode"),
        }
        rows.extend(
            _build_trade_date_rows(
                trade_date,
                stock_basic=stock_basic,
                daily_basic=daily_basic,
                limit_list=limit_list,
                suspend_list=suspend_list,
                cooled_tickers=cooled_tickers,
                report_context=report_context,
                price_cache=price_cache,
                price_batches_by_trade_date=price_batches_by_trade_date,
                future_trade_dates_by_trade_date=future_trade_dates_by_trade_date,
            )
        )

    rows.sort(key=lambda row: _row_priority_key(row), reverse=True)
    first_kill_switch_counts = Counter(str(row.get("first_kill_switch") or "unknown") for row in rows)
    strict_goal_rows = [row for row in rows if row.get("strict_btst_goal_case")]
    tradeable_rows = [row for row in rows if row.get("pool_b_tradeable")]
    tradeable_false_negative_rows = [
        row
        for row in tradeable_rows
        if str(row.get("first_kill_switch") or "") != "selected_or_near_miss"
    ]
    strict_goal_false_negative_rows = [
        row
        for row in tradeable_false_negative_rows
        if row.get("strict_btst_goal_case")
    ]
    tradeable_pool_first_kill_switch_counts = Counter(str(row.get("first_kill_switch") or "unknown") for row in tradeable_rows)
    strict_goal_kill_switch_counts = Counter(str(row.get("first_kill_switch") or "unknown") for row in strict_goal_rows)
    candidate_source_false_negative_counts = Counter(str(row.get("candidate_source") or "unseen") for row in tradeable_false_negative_rows)
    industry_false_negative_counts = Counter(str(row.get("industry") or "unknown") for row in tradeable_false_negative_rows)

    system_recall_count = sum(1 for row in tradeable_rows if row.get("pool_c_system_recalled"))
    selected_or_near_miss_count = sum(1 for row in tradeable_rows if row.get("selected_or_near_miss"))
    main_execution_pool_count = sum(1 for row in tradeable_rows if row.get("pool_d_main_execution_eligible"))
    capture_rate = _rate(system_recall_count, len(tradeable_rows))
    selected_or_near_miss_rate = _rate(selected_or_near_miss_count, len(tradeable_rows))
    main_execution_rate = _rate(main_execution_pool_count, len(tradeable_rows))
    no_candidate_entry_summary = _build_no_candidate_entry_summary(tradeable_rows)
    recommendation = _build_recommendation(
        tradeable_pool_count=len(tradeable_rows),
        tradeable_counts=tradeable_pool_first_kill_switch_counts,
        capture_rate=capture_rate,
    )

    return {
        "artifact_schema_version": 2,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "reports_root": resolved_reports_root.as_posix(),
        "trade_dates": active_trade_dates,
        "trade_date_contexts": trade_date_contexts,
        "thresholds": {
            "intraday_strong_threshold": INTRADAY_STRONG_THRESHOLD,
            "close_continuation_threshold": CLOSE_CONTINUATION_THRESHOLD,
            "strict_btst_goal_threshold": STRICT_BTST_GOAL_THRESHOLD,
            "extreme_next_open_gap_threshold": EXTREME_NEXT_OPEN_GAP_THRESHOLD,
            "min_listing_days": MIN_LISTING_DAYS,
            "min_estimated_amount_1d": MIN_ESTIMATED_AMOUNT_1D,
        },
        "pool_semantics": {
            "pool_a": "结果真值池：next_high / next_close / t+2 收益达到阈值的样本。",
            "pool_b": "可交易机会池：Pool A 扣除基础 prefilter、day0 涨停与明显不可复制执行场景后的样本。",
            "pool_c": "系统召回池：在 selection target、入口过滤或执行诊断里留下痕迹的 Pool B 样本。",
            "pool_d": "主执行池：Pool B 中被系统保留为 selected_or_near_miss 且未再被执行 contract 阻断的样本。",
        },
        "result_truth_pool_count": len(rows),
        "tradeable_opportunity_pool_count": len(tradeable_rows),
        "system_recall_count": system_recall_count,
        "selected_or_near_miss_count": selected_or_near_miss_count,
        "main_execution_pool_count": main_execution_pool_count,
        "strict_goal_case_count": len(strict_goal_rows),
        "strict_goal_tradeable_count": sum(1 for row in tradeable_rows if row.get("strict_btst_goal_case")),
        "strict_goal_false_negative_count": len(strict_goal_false_negative_rows),
        "tradeable_pool_capture_rate": capture_rate,
        "tradeable_pool_selected_or_near_miss_rate": selected_or_near_miss_rate,
        "tradeable_pool_main_execution_rate": main_execution_rate,
        "first_kill_switch_counts": _summarize_counter(first_kill_switch_counts),
        "first_kill_switch_strict_goal_case_counts": _summarize_counter(strict_goal_kill_switch_counts),
        "tradeable_pool_first_kill_switch_counts": _summarize_counter(tradeable_pool_first_kill_switch_counts),
        "candidate_source_false_negative_counts": _summarize_counter(candidate_source_false_negative_counts, limit=10),
        "industry_false_negative_counts": _summarize_counter(industry_false_negative_counts, limit=10),
        "no_candidate_entry_summary": no_candidate_entry_summary,
        "top_false_negative_rows": sorted(tradeable_false_negative_rows, key=_row_priority_key, reverse=True)[:12],
        "top_strict_goal_false_negative_rows": sorted(strict_goal_false_negative_rows, key=_row_priority_key, reverse=True)[:12],
        "recommendation": recommendation,
        "rows": rows,
    }


def render_btst_tradeable_opportunity_pool_markdown(analysis: dict[str, Any]) -> str:
    no_candidate_entry_summary = dict(analysis.get("no_candidate_entry_summary") or {})
    lines: list[str] = []
    lines.append("# BTST Tradeable Opportunity Pool Review")
    lines.append("")
    _append_tradeable_pool_overview_markdown(lines, analysis)
    _append_tradeable_pool_report_contexts_markdown(lines, dict(analysis.get("trade_date_contexts") or {}))
    _append_tradeable_pool_dict_section_markdown(lines, "Pool Semantics", dict(analysis.get("pool_semantics") or {}))
    _append_tradeable_pool_kill_switch_summary_markdown(lines, analysis)
    _append_tradeable_pool_false_negative_clusters_markdown(lines, analysis)
    _append_tradeable_pool_no_candidate_entry_markdown(lines, no_candidate_entry_summary)
    _append_tradeable_pool_row_section_markdown(lines, "Top Tradeable False Negatives", list(analysis.get("top_false_negative_rows") or []), strict=False)
    _append_tradeable_pool_row_section_markdown(lines, "Top Strict Goal False Negatives", list(analysis.get("top_strict_goal_false_negative_rows") or []), strict=True)
    return "\n".join(lines) + "\n"


def _append_tradeable_pool_overview_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    lines.append("## Overview")
    for key in (
        "generated_at",
        "trade_dates",
        "result_truth_pool_count",
        "tradeable_opportunity_pool_count",
        "system_recall_count",
        "selected_or_near_miss_count",
        "main_execution_pool_count",
        "strict_goal_case_count",
        "strict_goal_false_negative_count",
        "tradeable_pool_capture_rate",
        "tradeable_pool_selected_or_near_miss_rate",
        "tradeable_pool_main_execution_rate",
        "recommendation",
    ):
        lines.append(f"- {key}: {analysis.get(key)}")
    lines.append("")


def _append_tradeable_pool_report_contexts_markdown(lines: list[str], contexts: dict[str, Any]) -> None:
    lines.append("## Report Contexts")
    for trade_date, context in sorted(contexts.items()):
        lines.append(f"- {trade_date}: report_dir={context.get('report_dir')}, selection_target={context.get('selection_target')}, mode={context.get('mode')}")
    if not contexts:
        lines.append("- none")
    lines.append("")


def _append_tradeable_pool_dict_section_markdown(lines: list[str], title: str, payload: dict[str, Any]) -> None:
    lines.append(f"## {title}")
    for key, value in payload.items():
        lines.append(f"- {key}: {value}")
    lines.append("")


def _append_tradeable_pool_kill_switch_summary_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    lines.append("## Kill Switch Summary")
    for key in ("first_kill_switch_counts", "tradeable_pool_first_kill_switch_counts", "first_kill_switch_strict_goal_case_counts"):
        lines.append(f"- {key}: {analysis.get(key)}")
    lines.append("")


def _append_tradeable_pool_false_negative_clusters_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    lines.append("## False Negative Clusters")
    for key in ("candidate_source_false_negative_counts", "industry_false_negative_counts"):
        lines.append(f"- {key}: {analysis.get(key)}")
    lines.append("")


def _append_tradeable_pool_no_candidate_entry_markdown(lines: list[str], summary: dict[str, Any]) -> None:
    lines.append("## No Candidate Entry Breakdown")
    if int(summary.get("count") or 0) <= 0:
        lines.append("- none")
        lines.append("")
        return
    for key in (
        "count",
        "share_of_tradeable_pool",
        "strict_goal_case_count",
        "strict_goal_case_share",
        "industry_counts",
        "trade_date_counts",
        "estimated_amount_bucket_counts",
        "truth_pattern_counts",
    ):
        lines.append(f"- {key}: {summary.get(key)}")
    for row in list(summary.get("top_ticker_rows") or []):
        lines.append(
            f"- recurring_ticker: {row.get('ticker')} occurrences={row.get('occurrence_count')}, strict_goal_case_count={row.get('strict_goal_case_count')}, industry={row.get('industry')}, mean_next_high_return={row.get('mean_next_high_return')}, mean_t_plus_2_close_return={row.get('mean_t_plus_2_close_return')}"
        )
    for row in list(summary.get("top_priority_rows") or []):
        lines.append(
            f"- priority_case: {row.get('trade_date')} {row.get('ticker')} next_high_return={row.get('next_high_return')}, next_close_return={row.get('next_close_return')}, t_plus_2_close_return={row.get('t_plus_2_close_return')}"
        )
    lines.append(f"- recommendation: {summary.get('recommendation')}")
    lines.append("")


def _append_tradeable_pool_row_section_markdown(
    lines: list[str],
    title: str,
    rows: list[dict[str, Any]],
    *,
    strict: bool,
) -> None:
    lines.append(f"## {title}")
    for row in rows:
        if strict:
            lines.append(
                f"- {row.get('trade_date')} {row.get('ticker')}: kill_switch={row.get('first_kill_switch')}, source={row.get('candidate_source')}, t_plus_2_close_return={row.get('t_plus_2_close_return')}, preferred_entry_mode={row.get('preferred_entry_mode')}"
            )
        else:
            lines.append(
                f"- {row.get('trade_date')} {row.get('ticker')}: kill_switch={row.get('first_kill_switch')}, source={row.get('candidate_source')}, next_high_return={row.get('next_high_return')}, next_close_return={row.get('next_close_return')}, t_plus_2_close_return={row.get('t_plus_2_close_return')}"
            )
    if not rows:
        lines.append("- none")
    lines.append("")


def render_btst_tradeable_opportunity_reason_waterfall_markdown(waterfall: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Tradeable Opportunity Reason Waterfall")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- generated_at: {waterfall.get('generated_at')}")
    lines.append(f"- trade_dates: {waterfall.get('trade_dates')}")
    lines.append(f"- result_truth_pool_count: {waterfall.get('result_truth_pool_count')}")
    lines.append(f"- tradeable_opportunity_pool_count: {waterfall.get('tradeable_opportunity_pool_count')}")
    lines.append(f"- strict_goal_case_count: {waterfall.get('strict_goal_case_count')}")
    lines.append(f"- tradeable_pool_capture_rate: {waterfall.get('tradeable_pool_capture_rate')}")
    lines.append(f"- tradeable_pool_selected_or_near_miss_rate: {waterfall.get('tradeable_pool_selected_or_near_miss_rate')}")
    lines.append(f"- recommendation: {waterfall.get('recommendation')}")
    lines.append("")
    lines.append("## Tradeable Pool Top Kill Switches")
    for row in list(waterfall.get("top_tradeable_kill_switches") or []):
        lines.append(f"- {row.get('kill_switch')}: count={row.get('count')}")
    if not list(waterfall.get("top_tradeable_kill_switches") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Waterfall")
    for row in list(waterfall.get("waterfall_rows") or []):
        lines.append(
            f"- {row.get('kill_switch')}: count={row.get('count')}, share_of_result_truth_pool={row.get('share_of_result_truth_pool')}, strict_goal_case_count={row.get('strict_goal_case_count')}, tradeable_pool_count={row.get('tradeable_pool_count')}"
        )
    if not list(waterfall.get("waterfall_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Strict Goal False Negatives")
    for row in list(waterfall.get("top_strict_goal_false_negative_rows") or []):
        lines.append(
            f"- {row.get('trade_date')} {row.get('ticker')}: kill_switch={row.get('first_kill_switch')}, t_plus_2_close_return={row.get('t_plus_2_close_return')}, source={row.get('candidate_source')}"
        )
    if not list(waterfall.get("top_strict_goal_false_negative_rows") or []):
        lines.append("- none")
    lines.append("")
    return "\n".join(lines) + "\n"


def _csv_ready_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        resolved.write_text("", encoding="utf-8")
        return

    fieldnames = list(rows[0].keys())
    with resolved.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_ready_value(value) for key, value in row.items()})


def load_btst_tradeable_opportunity_artifacts(
    reports_root: str | Path,
    *,
    output_json: str | Path | None = None,
    waterfall_json: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    resolved_output_json = Path(output_json).expanduser().resolve() if output_json else (resolved_reports_root / DEFAULT_OUTPUT_JSON.name).resolve()
    resolved_waterfall_json = Path(waterfall_json).expanduser().resolve() if waterfall_json else (resolved_reports_root / DEFAULT_WATERFALL_JSON.name).resolve()
    if not resolved_output_json.exists() or not resolved_waterfall_json.exists():
        return {}, {}
    return json.loads(resolved_output_json.read_text(encoding="utf-8")), json.loads(resolved_waterfall_json.read_text(encoding="utf-8"))


def summarize_btst_tradeable_opportunity_artifacts(analysis: dict[str, Any], waterfall: dict[str, Any]) -> dict[str, Any]:
    top_kill_switches = list(waterfall.get("top_tradeable_kill_switches") or [])[:3]
    top_strict_rows = list(analysis.get("top_strict_goal_false_negative_rows") or [])[:3]
    no_candidate_entry_summary = dict(analysis.get("no_candidate_entry_summary") or {})
    top_no_candidate_entry_industries = list(dict(no_candidate_entry_summary.get("industry_counts") or {}).keys())[:3]
    top_no_candidate_entry_tickers = [
        str(row.get("ticker") or "")
        for row in list(no_candidate_entry_summary.get("top_ticker_rows") or [])[:3]
        if row.get("ticker")
    ]
    return {
        "result_truth_pool_count": int(analysis.get("result_truth_pool_count") or 0),
        "tradeable_opportunity_pool_count": int(analysis.get("tradeable_opportunity_pool_count") or 0),
        "system_recall_count": int(analysis.get("system_recall_count") or 0),
        "selected_or_near_miss_count": int(analysis.get("selected_or_near_miss_count") or 0),
        "main_execution_pool_count": int(analysis.get("main_execution_pool_count") or 0),
        "strict_goal_case_count": int(analysis.get("strict_goal_case_count") or 0),
        "strict_goal_false_negative_count": int(analysis.get("strict_goal_false_negative_count") or 0),
        "tradeable_pool_capture_rate": analysis.get("tradeable_pool_capture_rate"),
        "tradeable_pool_selected_or_near_miss_rate": analysis.get("tradeable_pool_selected_or_near_miss_rate"),
        "tradeable_pool_main_execution_rate": analysis.get("tradeable_pool_main_execution_rate"),
        "no_candidate_entry_count": int(no_candidate_entry_summary.get("count") or 0),
        "no_candidate_entry_share_of_tradeable_pool": no_candidate_entry_summary.get("share_of_tradeable_pool"),
        "top_no_candidate_entry_industries": top_no_candidate_entry_industries,
        "top_no_candidate_entry_tickers": top_no_candidate_entry_tickers,
        "top_tradeable_kill_switches": top_kill_switches,
        "top_tradeable_kill_switch_labels": [str(row.get("kill_switch") or "") for row in top_kill_switches if row.get("kill_switch")],
        "top_strict_goal_false_negative_tickers": [str(row.get("ticker") or "") for row in top_strict_rows if row.get("ticker")],
        "recommendation": analysis.get("recommendation") or waterfall.get("recommendation"),
    }


def generate_btst_tradeable_opportunity_pool_artifacts(
    reports_root: str | Path,
    *,
    trade_dates: set[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    output_json: str | Path | None = None,
    output_md: str | Path | None = None,
    output_csv: str | Path | None = None,
    waterfall_output_json: str | Path | None = None,
    waterfall_output_md: str | Path | None = None,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    resolved_output_json = Path(output_json).expanduser().resolve() if output_json else (resolved_reports_root / DEFAULT_OUTPUT_JSON.name).resolve()
    resolved_output_md = Path(output_md).expanduser().resolve() if output_md else (resolved_reports_root / DEFAULT_OUTPUT_MD.name).resolve()
    resolved_output_csv = Path(output_csv).expanduser().resolve() if output_csv else (resolved_reports_root / DEFAULT_OUTPUT_CSV.name).resolve()
    resolved_waterfall_json = Path(waterfall_output_json).expanduser().resolve() if waterfall_output_json else (resolved_reports_root / DEFAULT_WATERFALL_JSON.name).resolve()
    resolved_waterfall_md = Path(waterfall_output_md).expanduser().resolve() if waterfall_output_md else (resolved_reports_root / DEFAULT_WATERFALL_MD.name).resolve()

    analysis = analyze_btst_tradeable_opportunity_pool(
        resolved_reports_root,
        trade_dates=trade_dates,
        start_date=start_date,
        end_date=end_date,
    )
    waterfall = _build_waterfall(analysis)

    resolved_output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resolved_output_md.write_text(render_btst_tradeable_opportunity_pool_markdown(analysis), encoding="utf-8")
    _write_csv(resolved_output_csv, list(analysis.get("rows") or []))
    resolved_waterfall_json.write_text(json.dumps(waterfall, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resolved_waterfall_md.write_text(render_btst_tradeable_opportunity_reason_waterfall_markdown(waterfall), encoding="utf-8")

    return {
        "analysis": analysis,
        "waterfall": waterfall,
        "json_path": resolved_output_json.as_posix(),
        "markdown_path": resolved_output_md.as_posix(),
        "csv_path": resolved_output_csv.as_posix(),
        "waterfall_json_path": resolved_waterfall_json.as_posix(),
        "waterfall_markdown_path": resolved_waterfall_md.as_posix(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze BTST tradeable opportunity pool coverage and first kill switches.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR), help="Reports root directory")
    parser.add_argument("--trade-dates", default="", help="Comma-separated normalized trade dates, e.g. 2026-03-23,2026-03-24")
    parser.add_argument("--start-date", default="", help="Inclusive start date, e.g. 2026-03-01")
    parser.add_argument("--end-date", default="", help="Inclusive end date, e.g. 2026-03-31")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON), help="Output JSON path")
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD), help="Output Markdown path")
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV), help="Output CSV path")
    parser.add_argument("--waterfall-output-json", default=str(DEFAULT_WATERFALL_JSON), help="Output JSON path for reason waterfall")
    parser.add_argument("--waterfall-output-md", default=str(DEFAULT_WATERFALL_MD), help="Output Markdown path for reason waterfall")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = generate_btst_tradeable_opportunity_pool_artifacts(
        args.reports_root,
        trade_dates=_parse_trade_dates(args.trade_dates),
        start_date=args.start_date or None,
        end_date=args.end_date or None,
        output_json=args.output_json,
        output_md=args.output_md,
        output_csv=args.output_csv,
        waterfall_output_json=args.waterfall_output_json,
        waterfall_output_md=args.waterfall_output_md,
    )
    print(json.dumps(result["analysis"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
