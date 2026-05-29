from __future__ import annotations

from typing import Any


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


def normalize_historical_metric(row: dict[str, Any], key: str) -> Any:
    prior = dict(row.get("historical_prior") or {})
    prior_value = prior.get(key)
    if not _is_missing(prior_value):
        return prior_value
    return row.get(key)


def _scope_label(row: dict[str, Any]) -> str:
    return str(
        normalize_historical_metric(row, "applied_scope")
        or normalize_historical_metric(row, "scope")
        or ""
    )


def _metric_bundle(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "win_rate": _to_float(normalize_historical_metric(row, "next_close_positive_rate")),
        "payoff_ratio": _to_float(normalize_historical_metric(row, "next_close_payoff_ratio")),
        "expectancy": _to_float(normalize_historical_metric(row, "next_close_expectancy")),
        "profit_factor": _to_float(normalize_historical_metric(row, "next_close_profit_factor")),
        "evaluable_count": _to_int(normalize_historical_metric(row, "evaluable_count")),
        "sample_count": _to_int(normalize_historical_metric(row, "sample_count")),
        "scope": _scope_label(row),
        "win_rate_payoff_divergence": bool(
            normalize_historical_metric(row, "win_rate_payoff_divergence")
        ),
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
    if (
        win_rate is not None
        and win_rate >= 0.70
        and payoff_ratio is not None
        and payoff_ratio >= 1.50
        and (expectancy is None or expectancy >= 0)
    ):
        return "A"
    if (
        win_rate is not None
        and win_rate >= 0.55
        and payoff_ratio is not None
        and payoff_ratio >= 1.00
        and (expectancy is None or expectancy >= 0)
    ):
        return "B"
    if win_rate is not None and win_rate >= 0.45:
        return "C"
    if payoff_ratio is not None and payoff_ratio >= 1.50 and (
        expectancy is None or expectancy >= 0
    ):
        return "C"
    return "D"


def _cap_grade_for_risks(grade: str, metrics: dict[str, Any], notes: list[str]) -> str:
    if metrics["win_rate_payoff_divergence"]:
        notes.append("胜率和盈亏比/期望背离")
        return "C" if grade in {"A", "B"} else grade
    if (
        metrics["payoff_ratio"] is not None
        and metrics["payoff_ratio"] < 1.0
        and grade in {"A", "B"}
    ):
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
        (
            row
            for row in selected_rows
            if row.get("trade_bias") in {"trade_allowed", "confirmation_only"}
        ),
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
) -> list[dict[str, Any]]:
    ledger_rows = []
    for row in rows:
        metrics = dict(row.get("metrics") or {})
        ledger_rows.append(
            {
                "signal_date": signal_date,
                "next_trade_date": next_trade_date,
                "ticker": row.get("ticker"),
                "role": row.get("role"),
                "evidence_grade": row.get("evidence_grade"),
                "data_quality": row.get("data_quality"),
                "trade_bias": row.get("trade_bias"),
                "risk_posture": row.get("risk_posture"),
                "win_rate": metrics.get("win_rate"),
                "payoff_ratio": metrics.get("payoff_ratio"),
                "expectancy": metrics.get("expectancy"),
                "entry_mode": row.get("preferred_entry_mode"),
                "must_confirm": row.get("must_confirm"),
                "invalidate_if": row.get("invalidate_if"),
                "realized_next_open": None,
                "realized_next_high": None,
                "realized_next_close": None,
                "review_label": None,
            }
        )
    return ledger_rows
