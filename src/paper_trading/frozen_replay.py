from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from src.execution.models import ExecutionPlan


def _normalize_frozen_trade_date_key(value: object) -> str:
    raw_value = str(value or "").strip()
    digits = "".join(ch for ch in raw_value if ch.isdigit())
    return digits if len(digits) == 8 else raw_value


def _extract_sidecar_prior_by_ticker(payload: dict) -> dict[str, dict]:
    prior_by_ticker: dict[str, dict] = {}

    for ticker, evaluation in dict(payload.get("selection_targets") or {}).items():
        short_trade = dict((evaluation or {}).get("short_trade") or {})
        explainability_payload = dict(short_trade.get("explainability_payload") or {})
        metrics_payload = dict(short_trade.get("metrics_payload") or {})
        historical_prior = dict(explainability_payload.get("historical_prior") or metrics_payload.get("historical_prior") or {})
        if historical_prior:
            prior_by_ticker[str(ticker)] = historical_prior

    if prior_by_ticker:
        return prior_by_ticker

    for entry in list(payload.get("target_context") or []):
        ticker = str(entry.get("ticker") or "").strip()
        replay_context = dict(entry.get("replay_context") or {})
        historical_prior = dict(replay_context.get("historical_prior") or {})
        if ticker and historical_prior:
            prior_by_ticker[ticker] = historical_prior
    return prior_by_ticker


def _load_sidecar_prior_by_ticker(source_path: Path, trade_date: str) -> dict[str, dict]:
    selection_root = source_path.parent / "selection_artifacts"
    if not selection_root.is_dir():
        return {}

    normalized_trade_date = _normalize_frozen_trade_date_key(trade_date)
    candidate_dirs = [
        selection_root / f"{normalized_trade_date[:4]}-{normalized_trade_date[4:6]}-{normalized_trade_date[6:]}",
        selection_root / normalized_trade_date,
    ]
    candidate_files = ("selection_target_replay_input.json", "selection_snapshot.json")

    for candidate_dir in candidate_dirs:
        for candidate_name in candidate_files:
            candidate_path = candidate_dir / candidate_name
            if not candidate_path.is_file():
                continue
            payload = json.loads(candidate_path.read_text(encoding="utf-8"))
            prior_by_ticker = _extract_sidecar_prior_by_ticker(payload)
            if prior_by_ticker:
                return prior_by_ticker
    return {}


def _load_sidecar_replay_input_payload(source_path: Path, trade_date: str) -> dict:
    def _build_snapshot_watchlist_rich_rows(selection_snapshot_payload: dict) -> dict[str, dict]:
        rich_rows_by_ticker: dict[str, dict] = {}
        funnel_filters = dict(dict(selection_snapshot_payload.get("funnel_diagnostics") or {}).get("filters") or {})
        candidate_sections = [
            list(selection_snapshot_payload.get("catalyst_theme_candidates") or []),
            list(dict(funnel_filters.get("watchlist") or {}).get("tickers") or []),
            list(dict(funnel_filters.get("catalyst_theme_candidates") or {}).get("tickers") or []),
            list(dict(funnel_filters.get("short_trade_candidates") or {}).get("tickers") or []),
        ]
        for section in candidate_sections:
            for raw_row in section:
                row = dict(raw_row or {})
                ticker = str(row.get("ticker") or row.get("symbol") or "").strip()
                if ticker and row.get("strategy_signals"):
                    rich_rows_by_ticker[ticker] = row
        return rich_rows_by_ticker

    def _hydrate_sparse_watchlist_rows(*, replay_input_payload: dict, selection_snapshot_payload: dict) -> dict:
        rich_rows_by_ticker = _build_snapshot_watchlist_rich_rows(selection_snapshot_payload)
        if not rich_rows_by_ticker:
            return replay_input_payload
        hydrated_payload = dict(replay_input_payload or {})
        hydrated_watchlist: list[dict] = []
        changed = False
        for raw_row in list(hydrated_payload.get("watchlist") or []):
            row = dict(raw_row or {})
            ticker = str(row.get("ticker") or "").strip()
            rich_row = rich_rows_by_ticker.get(ticker)
            if rich_row and not row.get("strategy_signals"):
                if rich_row.get("strategy_signals"):
                    row["strategy_signals"] = rich_row["strategy_signals"]
                    changed = True
                if not row.get("agent_contribution_summary") and rich_row.get("agent_contribution_summary"):
                    row["agent_contribution_summary"] = rich_row["agent_contribution_summary"]
                    changed = True
                if not row.get("candidate_reason_codes") and rich_row.get("candidate_reason_codes"):
                    row["candidate_reason_codes"] = rich_row["candidate_reason_codes"]
                    changed = True
                if not row.get("theme_name") and rich_row.get("theme_name"):
                    row["theme_name"] = rich_row["theme_name"]
                    changed = True
                if not row.get("theme_category") and rich_row.get("theme_category"):
                    row["theme_category"] = rich_row["theme_category"]
                    changed = True
                if not row.get("metrics") and rich_row.get("metrics"):
                    row["metrics"] = rich_row["metrics"]
                    changed = True
            hydrated_watchlist.append(row)
        if changed:
            hydrated_payload["watchlist"] = hydrated_watchlist
        return hydrated_payload

    selection_root = source_path.parent / "selection_artifacts"
    if not selection_root.is_dir():
        return {}

    normalized_trade_date = _normalize_frozen_trade_date_key(trade_date)
    candidate_dirs = [
        selection_root / f"{normalized_trade_date[:4]}-{normalized_trade_date[4:6]}-{normalized_trade_date[6:]}",
        selection_root / normalized_trade_date,
    ]

    for candidate_dir in candidate_dirs:
        candidate_path = candidate_dir / "selection_target_replay_input.json"
        if not candidate_path.is_file():
            continue
        payload = json.loads(candidate_path.read_text(encoding="utf-8"))
        selection_snapshot_path = candidate_dir / "selection_snapshot.json"
        if selection_snapshot_path.is_file():
            selection_snapshot_payload = json.loads(selection_snapshot_path.read_text(encoding="utf-8"))
            payload = _hydrate_sparse_watchlist_rows(
                replay_input_payload=payload,
                selection_snapshot_payload=selection_snapshot_payload,
            )
        if isinstance(payload, dict) and payload:
            return payload
    return {}


def load_frozen_post_market_plans(daily_events_path: str | Path) -> dict[str, ExecutionPlan]:
    source_path = Path(daily_events_path).resolve()
    plans_by_date: dict[str, ExecutionPlan] = {}

    with source_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            current_plan_payload = payload.get("current_plan")
            if not current_plan_payload:
                continue
            trade_date = _normalize_frozen_trade_date_key(payload.get("trade_date") or current_plan_payload.get("date"))
            if not trade_date:
                continue
            normalized_plan_payload = dict(current_plan_payload)
            normalized_plan_payload.setdefault("date", trade_date)
            plan = ExecutionPlan.model_validate(normalized_plan_payload)
            risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
            explicit_prior = dict(risk_metrics.get("historical_prior_by_ticker", {}) or {})
            if not explicit_prior:
                sidecar_prior = _load_sidecar_prior_by_ticker(source_path, trade_date)
                if sidecar_prior:
                    risk_metrics["historical_prior_by_ticker"] = sidecar_prior
            explicit_replay_input = dict(risk_metrics.get("frozen_selection_target_replay_input", {}) or {})
            if not explicit_replay_input:
                sidecar_replay_input = _load_sidecar_replay_input_payload(source_path, trade_date)
                if sidecar_replay_input:
                    risk_metrics["frozen_selection_target_replay_input"] = sidecar_replay_input
            if risk_metrics != dict(getattr(plan, "risk_metrics", {}) or {}):
                plan.risk_metrics = risk_metrics
            plans_by_date[trade_date] = plan

    if not plans_by_date:
        raise ValueError(f"No current_plan records found in frozen replay source: {source_path}")

    return plans_by_date


def _parse_frozen_trade_date(value: object) -> datetime | None:
    """Strict parser for YYYYMMDD strings used inside the frozen replay source.

    Returns None for malformed values so callers can skip the offending row
    instead of crashing the entire replay.
    """
    text = _normalize_frozen_trade_date_key(value)
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return None


def _build_recent_generated_buy_blocks(*, latest_buy_trade_by_ticker: dict[str, str], current_trade_date: str, cooldown_calendar_days: int = 2) -> dict[str, dict]:
    current_dt = _parse_frozen_trade_date(current_trade_date)
    if current_dt is None:
        return {}
    blocked_until = (current_dt + timedelta(days=1)).strftime("%Y%m%d")
    blocked: dict[str, dict] = {}
    for ticker, buy_trade_date in dict(latest_buy_trade_by_ticker or {}).items():
        buy_dt = _parse_frozen_trade_date(buy_trade_date)
        if buy_dt is None:
            continue
        calendar_day_gap = (current_dt - buy_dt).days
        if calendar_day_gap <= 0 or calendar_day_gap > cooldown_calendar_days:
            continue
        blocked[str(ticker)] = {
            "trigger_reason": "recent_formal_buy_cooldown",
            "exit_trade_date": buy_dt.strftime("%Y%m%d"),
            "blocked_until": blocked_until,
        }
    return blocked


def _reset_frozen_buy_order_filter_summary(plan: ExecutionPlan) -> ExecutionPlan:
    normalized_plan = plan.model_copy(deep=True)
    original_buy_order_tickers = [str(getattr(order, "ticker", "") or "").strip() for order in list(getattr(normalized_plan, "buy_orders", []) or []) if str(getattr(order, "ticker", "") or "").strip()]
    risk_metrics = dict(getattr(normalized_plan, "risk_metrics", {}) or {})
    has_sidecar_replay_input = bool(dict(risk_metrics.get("frozen_selection_target_replay_input", {}) or {}))
    counts = dict(risk_metrics.get("counts", {}) or {})
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}) or {})
    filters = dict(funnel_diagnostics.get("filters", {}) or {})
    filters["buy_orders"] = {
        "filtered_count": 0,
        "reason_counts": {},
        "tickers": [],
        "selected_tickers": list(original_buy_order_tickers),
    }
    funnel_diagnostics["filters"] = filters
    counts["buy_order_count"] = len(original_buy_order_tickers)
    risk_metrics["counts"] = counts
    risk_metrics["funnel_diagnostics"] = funnel_diagnostics
    if has_sidecar_replay_input:
        risk_metrics["frozen_original_buy_order_tickers"] = list(original_buy_order_tickers)
    else:
        risk_metrics.pop("frozen_original_buy_order_tickers", None)
    normalized_plan.risk_metrics = risk_metrics
    return normalized_plan


def _clear_frozen_buy_orders(plan: ExecutionPlan) -> ExecutionPlan:
    normalized_plan = _reset_frozen_buy_order_filter_summary(plan)
    normalized_plan.buy_orders = []
    risk_metrics = dict(getattr(normalized_plan, "risk_metrics", {}) or {})
    counts = dict(risk_metrics.get("counts", {}) or {})
    counts["buy_order_count"] = 0
    risk_metrics["counts"] = counts
    normalized_plan.risk_metrics = risk_metrics
    return normalized_plan


def replay_frozen_post_market_sequence(
    daily_events_path: str | Path,
    *,
    target_mode: str = "short_trade_only",
    base_model_name: str = "gpt-4.1",
    base_model_provider: str = "OpenAI",
    short_trade_target_profile_name: str = "default",
    short_trade_target_profile_overrides: dict[str, object] | None = None,
    clear_existing_buy_orders: bool = False,
) -> dict[str, ExecutionPlan]:
    from src.execution.daily_pipeline import DailyPipeline

    frozen_plan_source = Path(daily_events_path).resolve()
    frozen_plans = {
        trade_date: (_clear_frozen_buy_orders(plan) if clear_existing_buy_orders else _reset_frozen_buy_order_filter_summary(plan))
        for trade_date, plan in load_frozen_post_market_plans(frozen_plan_source).items()
    }
    pipeline = DailyPipeline(
        frozen_post_market_plans=frozen_plans,
        frozen_plan_source=str(frozen_plan_source),
        target_mode=target_mode,
        base_model_name=base_model_name,
        base_model_provider=base_model_provider,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=dict(short_trade_target_profile_overrides or {}),
    )
    replayed_plans: dict[str, ExecutionPlan] = {}
    latest_buy_trade_by_ticker: dict[str, str] = {}
    for trade_date in sorted(frozen_plans):
        blocked_buy_tickers = _build_recent_generated_buy_blocks(
            latest_buy_trade_by_ticker=latest_buy_trade_by_ticker,
            current_trade_date=trade_date,
        )
        frozen_plan = frozen_plans[trade_date]
        replayed_plan = pipeline.run_post_market(
            trade_date,
            portfolio_snapshot=dict(getattr(frozen_plan, "portfolio_snapshot", {}) or {}),
            blocked_buy_tickers=blocked_buy_tickers,
        )
        replayed_plans[trade_date] = replayed_plan
        for order in list(getattr(replayed_plan, "buy_orders", []) or []):
            ticker = str(getattr(order, "ticker", "") or "").strip()
            if ticker:
                latest_buy_trade_by_ticker[ticker] = trade_date
    return replayed_plans
