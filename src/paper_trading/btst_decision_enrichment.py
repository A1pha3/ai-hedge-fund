from __future__ import annotations

import math
from typing import Any

_REPORT_MODE_FORMAL_EXECUTION = "formal_execution"
_REPORT_MODE_CONFIRMATION_REVIEW_ONLY = "confirmation_review_only"
_VALID_REPORT_MODES = {
    _REPORT_MODE_FORMAL_EXECUTION,
    _REPORT_MODE_CONFIRMATION_REVIEW_ONLY,
}
_VETO_OWNER_MARKET_GATE = "market_gate"
_VETO_OWNER_MODEL_EVIDENCE = "model_evidence"
_VETO_OWNER_MANUAL_REVIEW = "manual_review"
_VALID_VETO_OWNERS = {
    _VETO_OWNER_MARKET_GATE,
    _VETO_OWNER_MODEL_EVIDENCE,
    _VETO_OWNER_MANUAL_REVIEW,
}
_RELEASE_AUTHORITY_ALREADY_RELEASED = "already_released"
_RELEASE_AUTHORITY_EXECUTION_DESK = "execution_desk"
_RELEASE_AUTHORITY_NONE = "none"


def _is_missing(value: Any) -> bool:
    return value in (None, "", [], {}, ())


def _to_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if _is_missing(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_list(value: Any) -> list[str]:
    if _is_missing(value):
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        values = list(value)
    else:
        values = [value]
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if text and text not in seen:
            normalized.append(text)
            seen.add(text)
    return normalized


def _merge_string_lists(*values: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in _string_list(value):
            if item not in seen:
                merged.append(item)
                seen.add(item)
    return merged


def _normalized_report_mode(report_mode: Any) -> str:
    candidate = str(report_mode or "").strip()
    if candidate in _VALID_REPORT_MODES:
        return candidate
    return _REPORT_MODE_CONFIRMATION_REVIEW_ONLY


def _explicit_report_mode(report_mode: Any) -> str | None:
    candidate = str(report_mode or "").strip()
    if candidate in _VALID_REPORT_MODES:
        return candidate
    return None


def normalize_historical_metric(row: dict[str, Any], key: str) -> Any:
    prior = dict(row.get("historical_prior") or {})
    prior_value = prior.get(key)
    if not _is_missing(prior_value):
        return prior_value
    return row.get(key)


def _historical_metric_source(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row.get("source_row") or row)


def _historical_counts(row: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    source = _historical_metric_source(row)
    wins = _to_int(normalize_historical_metric(source, "next_close_positive_count"))
    losses = _to_int(normalize_historical_metric(source, "next_close_negative_count"))
    evaluable_count = _to_int(normalize_historical_metric(source, "evaluable_count"))
    if evaluable_count is None and wins is not None and losses is not None:
        evaluable_count = wins + losses
    if evaluable_count is not None:
        win_rate = _to_float(normalize_historical_metric(source, "next_close_positive_rate"))
        if wins is None and win_rate is not None:
            wins = int(round(win_rate * evaluable_count))
        if losses is None and wins is not None:
            losses = max(evaluable_count - wins, 0)
    return wins, losses, evaluable_count


def _wilson_interval(wins: int | None, total: int | None) -> tuple[float | None, float | None]:
    if wins is None or total is None or total <= 0:
        return None, None
    z = 1.96
    phat = wins / total
    denominator = 1 + z * z / total
    centre = phat + z * z / (2 * total)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    return (centre - margin) / denominator, (centre + margin) / denominator


def build_historical_reliability_metrics(row: dict[str, Any]) -> dict[str, Any]:
    source = _historical_metric_source(row)
    wins, losses, evaluable_count = _historical_counts(source)
    sample_count = _to_int(normalize_historical_metric(source, "sample_count"))
    total = evaluable_count or sample_count
    raw_win_rate = _to_float(normalize_historical_metric(source, "next_close_positive_rate"))
    if raw_win_rate is None and wins is not None and total:
        raw_win_rate = wins / total
    wilson_low, wilson_high = _wilson_interval(wins, total)
    shrunk_win_rate = ((wins + 1) / (total + 2)) if wins is not None and total else None
    if total is None:
        reliability_label = "样本未知"
    elif total < 5:
        reliability_label = "弱参考"
    elif total < 20:
        reliability_label = "中等样本"
    else:
        reliability_label = "较稳健"
    return {
        "sample_count": sample_count,
        "evaluable_count": evaluable_count,
        "positive_count": wins,
        "negative_count": losses,
        "raw_win_rate": round(raw_win_rate, 4) if raw_win_rate is not None else None,
        "shrunk_win_rate": round(shrunk_win_rate, 4) if shrunk_win_rate is not None else None,
        "win_rate_wilson_low": round(wilson_low, 4) if wilson_low is not None else None,
        "win_rate_wilson_high": round(wilson_high, 4) if wilson_high is not None else None,
        "reliability_label": reliability_label,
    }


def estimate_execution_cost_cap(row: dict[str, Any]) -> float:
    source = _historical_metric_source(row)
    expectancy = _to_float(normalize_historical_metric(source, "next_close_expectancy"))
    close_return_mean = _to_float(normalize_historical_metric(source, "next_close_return_mean"))
    edge = expectancy if expectancy is not None else close_return_mean
    if edge is None or edge <= 0:
        return 0.001
    return round(min(0.005, max(0.001, edge * 0.2)), 4)


def _scope_label(row: dict[str, Any]) -> str:
    return str(normalize_historical_metric(row, "applied_scope") or normalize_historical_metric(row, "scope") or "")


def _metric_bundle(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "win_rate": _to_float(normalize_historical_metric(row, "next_close_positive_rate")),
        "payoff_ratio": _to_float(normalize_historical_metric(row, "next_close_payoff_ratio")),
        "expectancy": _to_float(normalize_historical_metric(row, "next_close_expectancy")),
        "profit_factor": _to_float(normalize_historical_metric(row, "next_close_profit_factor")),
        "evaluable_count": _to_int(normalize_historical_metric(row, "evaluable_count")),
        "sample_count": _to_int(normalize_historical_metric(row, "sample_count")),
        "scope": _scope_label(row),
        "win_rate_payoff_divergence": bool(normalize_historical_metric(row, "win_rate_payoff_divergence")),
    }


def _reliability_count(metrics: dict[str, Any]) -> int | None:
    if metrics["evaluable_count"] is not None:
        return metrics["evaluable_count"]
    return metrics["sample_count"]


def classify_data_quality(
    row: dict[str, Any],
    *,
    role: str,
    early_runner_status: str,
) -> tuple[str, list[str]]:
    metrics = _metric_bundle(row)
    reliability_count = _reliability_count(metrics)
    notes: list[str] = []
    if role.startswith("early_runner") and early_runner_status == "stale_fallback":
        notes.append("early-runner 非当日板")
        return "stale_reference", notes
    if metrics["win_rate"] is None and metrics["payoff_ratio"] is None:
        notes.append("胜率和盈亏比均缺失")
        return "insufficient", notes
    if reliability_count is not None and reliability_count < 5:
        notes.append("样本不足 5，只能作弱参考")
        return "insufficient", notes
    if reliability_count is not None and reliability_count < 10:
        notes.append("样本不足 10")
        return "usable_with_warning", notes
    if metrics["payoff_ratio"] is None:
        notes.append("盈亏比缺失，不能确认赔率质量")
        return "usable_with_warning", notes
    if metrics["scope"] and metrics["scope"] != "same_ticker":
        notes.append("历史先验来自分桶样本，不是同票样本")
        return "usable_with_warning", notes
    return "fresh", notes


def _base_grade(metrics: dict[str, Any], data_quality: str) -> str:
    win_rate = metrics["win_rate"]
    payoff_ratio = metrics["payoff_ratio"]
    expectancy = metrics["expectancy"]
    if data_quality in {"stale_reference", "insufficient"}:
        return "D"
    if win_rate is None and payoff_ratio is None:
        return "D"
    if win_rate is not None and win_rate >= 0.70 and payoff_ratio is not None and payoff_ratio >= 1.50 and (expectancy is None or expectancy >= 0):
        return "A"
    if win_rate is not None and win_rate >= 0.55 and payoff_ratio is not None and payoff_ratio >= 1.00 and (expectancy is None or expectancy >= 0):
        return "B"
    if win_rate is not None and win_rate >= 0.45:
        return "C"
    if payoff_ratio is not None and payoff_ratio >= 1.50 and (expectancy is None or expectancy >= 0):
        return "C"
    return "D"


def _cap_grade_for_risks(grade: str, metrics: dict[str, Any], notes: list[str]) -> str:
    if metrics["win_rate_payoff_divergence"]:
        notes.append("胜率和盈亏比/期望背离")
        return "C" if grade in {"A", "B"} else grade
    if metrics["payoff_ratio"] is not None and metrics["payoff_ratio"] < 1.0 and grade in {"A", "B"}:
        notes.append("盈亏比低于 1.00，不能按高赔率处理")
        return "C"
    return grade


def _trade_bias_for_grade(role: str, grade: str, data_quality: str) -> str:
    if role != "formal_selected":
        return "watch_only"
    if data_quality in {"stale_reference", "insufficient"} or grade == "D":
        return "skip"
    if grade == "A":
        return "trade_allowed"
    return "confirmation_only"


def _risk_posture_for_bias(trade_bias: str, grade: str, data_quality: str) -> str:
    if trade_bias == "skip" or data_quality == "stale_reference":
        return "no_trade"
    if trade_bias == "watch_only" or grade == "C" or data_quality == "usable_with_warning":
        return "micro"
    if trade_bias == "confirmation_only":
        return "reduced"
    return "normal"


def _must_confirm(preferred_entry_mode: str) -> str:
    if preferred_entry_mode == "payoff_reconfirmation_only":
        return "必须看到新的强确认，且不能只凭历史胜率入场。"
    if preferred_entry_mode == "intraday_confirmation_only":
        return "只做盘中确认后的机会，不预设隔夜执行。"
    return "等待盘中延续确认后再执行，不做开盘无确认追价。"


def _invalidate_if(preferred_entry_mode: str) -> str:
    if preferred_entry_mode == "payoff_reconfirmation_only":
        return "若确认不足或赔率背离继续存在，则取消正式执行。"
    if preferred_entry_mode == "intraday_confirmation_only":
        return "若盘中确认失败或收盘延续预期不足，则不隔夜持有。"
    return "若开盘后无法形成延续确认，或快速冲高回落，则取消正式执行。"


def _action_matrix(preferred_entry_mode: str) -> list[dict[str, str]]:
    return [
        {
            "scenario": "开盘强且延续确认",
            "action": _must_confirm(preferred_entry_mode),
        },
        {
            "scenario": "高开但确认失败",
            "action": "不追价，降级为观察。",
        },
        {
            "scenario": "低开后修复",
            "action": "只在原始触发逻辑仍成立时复审，不因低位反弹自动升级。",
        },
        {
            "scenario": "触发失效条件",
            "action": _invalidate_if(preferred_entry_mode),
        },
    ]


def build_report_mode(control_tower: dict[str, Any]) -> str:
    effective_trade_bias = str(control_tower.get("effective_trade_bias") or "").strip()
    if effective_trade_bias == "trade_allowed":
        return _REPORT_MODE_FORMAL_EXECUTION
    existing_report_mode = str(control_tower.get("report_mode") or "").strip()
    if not effective_trade_bias and existing_report_mode in _VALID_REPORT_MODES:
        return existing_report_mode
    return _REPORT_MODE_CONFIRMATION_REVIEW_ONLY


def build_veto_owner(control_tower: dict[str, Any]) -> str:
    existing_veto_owner = str(control_tower.get("veto_owner") or "").strip()
    if existing_veto_owner in _VALID_VETO_OWNERS:
        return existing_veto_owner
    reason_codes = _string_list(control_tower.get("reason_codes"))
    if any("market_gate" in code or "regime_gate" in code or "buy_orders_cleared" in code for code in reason_codes):
        return _VETO_OWNER_MARKET_GATE
    if any("selection_snapshot_missing" in code or "manual_review" in code for code in reason_codes):
        return _VETO_OWNER_MANUAL_REVIEW
    return _VETO_OWNER_MODEL_EVIDENCE


def _selection_snapshot_gate_context(selection_snapshot: dict[str, Any]) -> dict[str, Any]:
    market_state = dict(selection_snapshot.get("market_state") or {})
    funnel_diagnostics = dict(selection_snapshot.get("funnel_diagnostics") or {})
    gate_enforcement = dict(funnel_diagnostics.get("btst_regime_gate_enforcement") or {})
    return {
        "regime_gate_level": str(market_state.get("regime_gate_level") or "n/a"),
        "regime_gate_reasons": list(market_state.get("regime_gate_reasons") or []),
        "position_scale": market_state.get("position_scale"),
        "gate": str(gate_enforcement.get("gate") or ""),
        "enforced": gate_enforcement.get("enforced"),
        "buy_orders_cleared": gate_enforcement.get("buy_orders_cleared"),
        "buy_orders_cleared_count": gate_enforcement.get("buy_orders_cleared_count"),
    }


def build_premarket_control_tower(
    decision_card: dict[str, Any],
    selection_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    raw_trade_bias = str(decision_card.get("trade_bias") or "skip")
    gate_context = _selection_snapshot_gate_context(selection_snapshot or {}) if selection_snapshot else {}
    gate = str(gate_context.get("gate") or "")
    regime_level = str(gate_context.get("regime_gate_level") or "n/a")
    buy_orders_cleared = bool(gate_context.get("buy_orders_cleared"))
    hard_gate = gate == "halt" or regime_level in {"crisis", "halt", "risk_off"} or buy_orders_cleared
    reason_codes: list[str] = []
    if raw_trade_bias in {"skip", "no_trade"}:
        effective_trade_bias = raw_trade_bias
        reason_codes.append("raw_model_no_trade")
    elif not selection_snapshot:
        effective_trade_bias = "manual_review_required"
        reason_codes.append("selection_snapshot_missing")
    elif hard_gate:
        effective_trade_bias = "gate_locked_confirmation_only"
        reason_codes.append("market_gate_downgraded_raw_trade_allowed" if raw_trade_bias == "trade_allowed" else "market_gate_requires_confirmation")
    else:
        effective_trade_bias = raw_trade_bias
        reason_codes.append("market_gate_passed")
    return {
        "raw_trade_bias": raw_trade_bias,
        "effective_trade_bias": effective_trade_bias,
        "primary_ticker": decision_card.get("primary_ticker"),
        "evidence_grade": decision_card.get("evidence_grade"),
        "data_quality": decision_card.get("data_quality"),
        "risk_posture": decision_card.get("risk_posture"),
        "regime_gate_level": regime_level,
        "gate": gate or "n/a",
        "enforced": gate_context.get("enforced"),
        "buy_orders_cleared": gate_context.get("buy_orders_cleared"),
        "buy_orders_cleared_count": gate_context.get("buy_orders_cleared_count"),
        "position_scale": gate_context.get("position_scale"),
        "reason_codes": reason_codes,
        "action": "先按门控降级，只允许 09:25 后重新确认；若盘口承接和市场宽度没有修复，则不执行。" if effective_trade_bias == "gate_locked_confirmation_only" else "沿用模型原始倾向，但仍需完成盘中确认。",
    }


def _resolve_execution_context(
    *,
    report_mode: Any = None,
    control_tower: dict[str, Any] | None = None,
    veto_owner: str | None = None,
) -> tuple[str | None, str | None]:
    resolved_report_mode = _explicit_report_mode(report_mode)
    if resolved_report_mode is None and control_tower is not None:
        resolved_report_mode = build_report_mode(control_tower)
    elif resolved_report_mode is None and not _is_missing(report_mode):
        resolved_report_mode = _normalized_report_mode(report_mode)

    resolved_veto_owner = str(veto_owner or "").strip() or None
    if not resolved_veto_owner and control_tower is not None:
        resolved_veto_owner = build_veto_owner(control_tower)

    return resolved_report_mode, resolved_veto_owner


def build_release_authority(
    *,
    report_mode: str,
    execution_state: str,
    control_tower: dict[str, Any] | None = None,
    veto_owner: str | None = None,
) -> str:
    resolved_report_mode, resolved_veto_owner = _resolve_execution_context(
        report_mode=report_mode,
        control_tower=control_tower,
        veto_owner=veto_owner,
    )
    normalized_execution_state = str(execution_state or "").strip()
    if normalized_execution_state == "orderable":
        return _RELEASE_AUTHORITY_ALREADY_RELEASED
    if normalized_execution_state == "confirmable":
        if resolved_report_mode == _REPORT_MODE_FORMAL_EXECUTION:
            return _RELEASE_AUTHORITY_EXECUTION_DESK
        if resolved_veto_owner:
            return resolved_veto_owner
    if normalized_execution_state in {"watching", "blocked"} and resolved_report_mode == _REPORT_MODE_CONFIRMATION_REVIEW_ONLY and resolved_veto_owner:
        return resolved_veto_owner
    if normalized_execution_state == "blocked" and resolved_veto_owner:
        return resolved_veto_owner
    return _RELEASE_AUTHORITY_NONE


def build_execution_semantics(
    *,
    report_mode: str,
    role: str,
    trade_bias: str,
    control_tower: dict[str, Any] | None = None,
    veto_owner: str | None = None,
    state_reason_codes: Any = None,
) -> dict[str, Any]:
    resolved_report_mode = _normalized_report_mode(report_mode)
    normalized_role = str(role or "").strip()
    normalized_trade_bias = str(trade_bias or "watch_only").strip() or "watch_only"
    merged_reason_codes = _merge_string_lists(
        state_reason_codes,
        (control_tower or {}).get("reason_codes"),
    )

    if resolved_report_mode == _REPORT_MODE_CONFIRMATION_REVIEW_ONLY:
        if normalized_trade_bias == "skip":
            execution_state = "blocked"
            allowed_sections = ["blocked_only"]
        elif normalized_role == "formal_selected" and normalized_trade_bias in {"trade_allowed", "confirmation_only"}:
            execution_state = "confirmable"
            allowed_sections = ["review_queue"]
        else:
            execution_state = "watching"
            allowed_sections = ["watch_queue"]
        max_allowed_state_today = "confirmable"
        formal_buy_allowed = False
    else:
        if normalized_trade_bias == "trade_allowed" and normalized_role == "formal_selected":
            execution_state = "orderable"
            allowed_sections = ["formal_queue"]
            formal_buy_allowed = True
        elif normalized_trade_bias == "confirmation_only" and normalized_role == "formal_selected":
            execution_state = "confirmable"
            allowed_sections = ["formal_queue"]
            formal_buy_allowed = False
        elif normalized_trade_bias == "skip":
            execution_state = "blocked"
            allowed_sections = ["blocked_only"]
            formal_buy_allowed = False
        else:
            execution_state = "watching"
            allowed_sections = ["watch_queue"]
            formal_buy_allowed = False
        max_allowed_state_today = "orderable"
    release_authority = build_release_authority(
        report_mode=resolved_report_mode,
        execution_state=execution_state,
        control_tower=control_tower,
        veto_owner=veto_owner,
    )

    return {
        "report_mode": resolved_report_mode,
        "execution_state": execution_state,
        "max_allowed_state_today": max_allowed_state_today,
        "formal_buy_allowed": formal_buy_allowed,
        "allowed_sections": allowed_sections,
        "release_authority": release_authority,
        "state_reason_codes": merged_reason_codes,
    }


def attach_execution_semantics(
    row: dict[str, Any],
    *,
    report_mode: str,
    control_tower: dict[str, Any] | None = None,
    veto_owner: str | None = None,
) -> dict[str, Any]:
    resolved_report_mode, resolved_veto_owner = _resolve_execution_context(
        report_mode=report_mode,
        control_tower=control_tower,
        veto_owner=veto_owner,
    )
    semantics = build_execution_semantics(
        report_mode=resolved_report_mode or report_mode,
        role=str(row.get("role") or ""),
        trade_bias=str(row.get("trade_bias") or "watch_only"),
        control_tower=control_tower,
        veto_owner=resolved_veto_owner,
        state_reason_codes=row.get("state_reason_codes"),
    )
    enriched = dict(row)
    enriched.update(semantics)
    if resolved_veto_owner:
        enriched["veto_owner"] = resolved_veto_owner
    return enriched


def enrich_btst_row(
    row: dict[str, Any],
    *,
    role: str,
    early_runner_status: str,
) -> dict[str, Any]:
    metrics = _metric_bundle(row)
    data_quality, notes = classify_data_quality(
        row,
        role=role,
        early_runner_status=early_runner_status,
    )
    grade = _cap_grade_for_risks(_base_grade(metrics, data_quality), metrics, notes)
    preferred_entry_mode = str(row.get("preferred_entry_mode") or "next_day_breakout_confirmation")
    trade_bias = _trade_bias_for_grade(role, grade, data_quality)
    return {
        "ticker": str(row.get("ticker") or ""),
        "name": str(row.get("name") or ""),
        "role": role,
        "source_row": dict(row),
        "preferred_entry_mode": preferred_entry_mode,
        "score_target": row.get("score_target", row.get("pre_score")),
        "evidence_grade": grade,
        "data_quality": data_quality,
        "trade_bias": trade_bias,
        "risk_posture": _risk_posture_for_bias(trade_bias, grade, data_quality),
        "must_confirm": _must_confirm(preferred_entry_mode),
        "invalidate_if": _invalidate_if(preferred_entry_mode),
        "quality_notes": notes,
        "metrics": metrics,
        "action_matrix": _action_matrix(preferred_entry_mode),
    }


def build_decision_card(
    *,
    selected_rows: list[dict[str, Any]],
    early_runner_status: str,
    signal_date: str,
    next_trade_date: str,
) -> dict[str, Any]:
    primary = next(
        (row for row in selected_rows if row.get("trade_bias") in {"trade_allowed", "confirmation_only"}),
        selected_rows[0] if selected_rows else {},
    )
    if not primary:
        return {
            "signal_date": signal_date,
            "next_trade_date": next_trade_date,
            "trade_bias": "skip",
            "primary_ticker": None,
            "evidence_grade": "D",
            "data_quality": "insufficient",
            "risk_posture": "no_trade",
            "must_confirm": "没有 formal selected 票，保持空仓观察。",
            "invalidate_if": "无可执行主线。",
            "early_runner_status": early_runner_status,
        }
    return {
        "signal_date": signal_date,
        "next_trade_date": next_trade_date,
        "trade_bias": primary["trade_bias"],
        "primary_ticker": primary["ticker"],
        "evidence_grade": primary["evidence_grade"],
        "data_quality": primary["data_quality"],
        "risk_posture": primary["risk_posture"],
        "must_confirm": primary["must_confirm"],
        "invalidate_if": primary["invalidate_if"],
        "early_runner_status": early_runner_status,
    }


def build_review_ledger_rows(
    *,
    signal_date: str,
    next_trade_date: str,
    rows: list[dict[str, Any]],
    report_mode: str | None = None,
    control_tower: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    semantic_fields = (
        "report_mode",
        "execution_state",
        "max_allowed_state_today",
        "formal_buy_allowed",
        "allowed_sections",
        "release_authority",
        "state_reason_codes",
        "veto_owner",
    )
    ledger_rows = []
    default_report_mode, default_veto_owner = _resolve_execution_context(
        report_mode=report_mode,
        control_tower=control_tower,
    )
    for row in rows:
        normalized_row = dict(row)
        row_report_mode = normalized_row.get("report_mode")
        if _is_missing(row_report_mode):
            row_report_mode = default_report_mode
        if row_report_mode or control_tower is not None:
            semantics_row = attach_execution_semantics(
                normalized_row,
                report_mode=str(row_report_mode or ""),
                control_tower=control_tower,
                veto_owner=default_veto_owner,
            )
            for field in semantic_fields:
                if _is_missing(normalized_row.get(field)) and not _is_missing(semantics_row.get(field)):
                    normalized_row[field] = semantics_row.get(field)
        if _is_missing(normalized_row.get("veto_owner")) and default_veto_owner is not None:
            normalized_row["veto_owner"] = default_veto_owner
        metrics = dict(row.get("metrics") or {})
        reliability_metrics = build_historical_reliability_metrics(normalized_row)
        ledger_rows.append(
            {
                "signal_date": signal_date,
                "next_trade_date": next_trade_date,
                "ticker": normalized_row.get("ticker"),
                "role": normalized_row.get("role"),
                "evidence_grade": normalized_row.get("evidence_grade"),
                "data_quality": normalized_row.get("data_quality"),
                "trade_bias": normalized_row.get("trade_bias"),
                "risk_posture": normalized_row.get("risk_posture"),
                "report_mode": normalized_row.get("report_mode"),
                "execution_state": normalized_row.get("execution_state"),
                "max_allowed_state_today": normalized_row.get("max_allowed_state_today"),
                "formal_buy_allowed": normalized_row.get("formal_buy_allowed"),
                "allowed_sections": _string_list(normalized_row.get("allowed_sections")),
                "release_authority": normalized_row.get("release_authority"),
                "state_reason_codes": _string_list(normalized_row.get("state_reason_codes")),
                "veto_owner": normalized_row.get("veto_owner"),
                "win_rate": metrics.get("win_rate"),
                "payoff_ratio": metrics.get("payoff_ratio"),
                "expectancy": metrics.get("expectancy"),
                "sample_count": reliability_metrics["sample_count"],
                "evaluable_count": reliability_metrics["evaluable_count"],
                "positive_count": reliability_metrics["positive_count"],
                "negative_count": reliability_metrics["negative_count"],
                "shrunk_win_rate": reliability_metrics["shrunk_win_rate"],
                "win_rate_wilson_low": reliability_metrics["win_rate_wilson_low"],
                "win_rate_wilson_high": reliability_metrics["win_rate_wilson_high"],
                "expected_slippage_cap": estimate_execution_cost_cap(normalized_row),
                "entry_mode": normalized_row.get("preferred_entry_mode"),
                "must_confirm": normalized_row.get("must_confirm"),
                "invalidate_if": normalized_row.get("invalidate_if"),
                "intended_entry_trigger": normalized_row.get("must_confirm"),
                "intended_invalidation": normalized_row.get("invalidate_if"),
                "realized_entry_price": None,
                "realized_exit_price": None,
                "realized_slippage": None,
                "mae": None,
                "mfe": None,
                "realized_next_open": None,
                "realized_next_high": None,
                "realized_next_close": None,
                "post_close_review_state": None,
                "post_close_review_transition": None,
                "review_label": None,
                "execution_review_label": None,
            }
        )
    return ledger_rows
