from __future__ import annotations

import json
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
            plan = ExecutionPlan.model_validate(current_plan_payload)
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
