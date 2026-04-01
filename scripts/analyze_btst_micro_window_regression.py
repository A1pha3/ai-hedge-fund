from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

import pandas as pd

from src.project_env import load_project_dotenv
from src.tools.api import get_price_data, prices_to_df
from src.tools.akshare_api import get_prices_robust


load_project_dotenv()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_trade_date(value: str | None) -> str:
    token = str(value or "").strip()
    if len(token) == 8 and token.isdigit():
        return f"{token[:4]}-{token[4:6]}-{token[6:8]}"
    return token


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _iter_selection_snapshots(report_dir: Path):
    selection_root = report_dir / "selection_artifacts"
    if not selection_root.exists():
        return
    for day_dir in sorted(path for path in selection_root.iterdir() if path.is_dir()):
        snapshot_path = day_dir / "selection_snapshot.json"
        if snapshot_path.exists():
            yield _load_json(snapshot_path)


def _load_session_summary_aggregate(report_dir: Path) -> dict[str, Any] | None:
    session_summary_path = report_dir / "session_summary.json"
    if not session_summary_path.exists():
        return None

    session_summary = _load_json(session_summary_path)
    selection_artifact_root = Path(str(((session_summary.get("artifacts") or {}).get("selection_artifact_root") or report_dir / "selection_artifacts"))).expanduser()
    daily_events_path = Path(str(((session_summary.get("artifacts") or {}).get("daily_events") or report_dir / "daily_events.jsonl"))).expanduser()
    return {
        "session_summary_path": str(session_summary_path),
        "selection_target": ((session_summary.get("plan_generation") or {}).get("selection_target")),
        "dual_target_summary": dict(session_summary.get("dual_target_summary") or {}),
        "daily_event_stats": dict(session_summary.get("daily_event_stats") or {}),
        "selection_artifact_root_exists": selection_artifact_root.exists(),
        "daily_events_exists": daily_events_path.exists(),
    }


def _normalize_price_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    normalized = frame.copy()
    if not isinstance(normalized.index, pd.DatetimeIndex):
        date_column = None
        for candidate in ("date", "trade_date", "datetime"):
            if candidate in normalized.columns:
                date_column = candidate
                break
        if date_column is not None:
            normalized[date_column] = pd.to_datetime(normalized[date_column])
            normalized = normalized.set_index(date_column)
        else:
            normalized.index = pd.to_datetime(normalized.index)
    normalized.index = pd.to_datetime(normalized.index).normalize()
    normalized = normalized.sort_index()
    normalized.columns = [str(column).lower() for column in normalized.columns]
    return normalized


def _fetch_price_frame(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], pd.DataFrame]) -> pd.DataFrame:
    normalized_trade_date = _normalize_trade_date(trade_date)
    cache_key = (ticker, normalized_trade_date)
    cached = price_cache.get(cache_key)
    if cached is not None:
        return cached

    end_date = (pd.Timestamp(normalized_trade_date) + pd.Timedelta(days=15)).strftime("%Y-%m-%d")
    try:
        frame = _normalize_price_frame(get_price_data(ticker, normalized_trade_date, end_date))
    except Exception:
        try:
            frame = _normalize_price_frame(prices_to_df(get_prices_robust(ticker, normalized_trade_date, end_date, use_mock_on_fail=False)))
        except Exception:
            frame = pd.DataFrame()

    price_cache[cache_key] = frame
    return frame


def _extract_btst_price_outcome(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], pd.DataFrame]) -> dict[str, Any]:
    normalized_trade_date = _normalize_trade_date(trade_date)
    frame = _fetch_price_frame(ticker, normalized_trade_date, price_cache)
    if frame.empty:
        return {
            "data_status": "missing_price_frame",
            "cycle_status": "missing_next_day",
        }

    trade_ts = pd.Timestamp(normalized_trade_date)
    same_day = frame.loc[frame.index.normalize() == trade_ts.normalize()]
    if same_day.empty:
        return {
            "data_status": "missing_trade_day_bar",
            "cycle_status": "missing_next_day",
        }

    future_days = frame.loc[frame.index.normalize() > trade_ts.normalize()]
    if future_days.empty:
        return {
            "data_status": "missing_next_trade_day_bar",
            "trade_close": _round_or_none(_safe_float(same_day.iloc[0].get("close"))),
            "cycle_status": "missing_next_day",
        }

    trade_row = same_day.iloc[0]
    next_row = future_days.iloc[0]
    later_rows = future_days.iloc[1:]

    trade_close = _safe_float(trade_row.get("close"))
    next_open = _safe_float(next_row.get("open"))
    next_high = _safe_float(next_row.get("high"))
    next_close = _safe_float(next_row.get("close"))
    if trade_close is None or trade_close <= 0 or next_open is None or next_high is None or next_close is None:
        return {
            "data_status": "incomplete_next_trade_day_bar",
            "cycle_status": "missing_next_day",
        }

    t_plus_2_close = None
    t_plus_2_trade_date = None
    if not later_rows.empty:
        second_row = later_rows.iloc[0]
        t_plus_2_close = _safe_float(second_row.get("close"))
        t_plus_2_trade_date = later_rows.index[0].strftime("%Y-%m-%d")

    data_status = "ok" if t_plus_2_close is not None else "missing_t_plus_2_bar"
    cycle_status = "closed_cycle" if t_plus_2_close is not None else "t1_only"

    return {
        "data_status": data_status,
        "cycle_status": cycle_status,
        "trade_close": round(trade_close, 4),
        "next_trade_date": future_days.index[0].strftime("%Y-%m-%d"),
        "next_open": round(next_open, 4),
        "next_high": round(next_high, 4),
        "next_close": round(next_close, 4),
        "next_open_return": round((next_open / trade_close) - 1.0, 4),
        "next_high_return": round((next_high / trade_close) - 1.0, 4),
        "next_close_return": round((next_close / trade_close) - 1.0, 4),
        "next_open_to_close_return": round((next_close / next_open) - 1.0, 4),
        "t_plus_2_trade_date": t_plus_2_trade_date,
        "t_plus_2_close": _round_or_none(t_plus_2_close),
        "t_plus_2_close_return": None if t_plus_2_close is None else round((t_plus_2_close / trade_close) - 1.0, 4),
    }


def _summarize_distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(mean(values), 4),
    }


def _build_surface_summary(rows: list[dict[str, Any]], *, next_high_hit_threshold: float) -> dict[str, Any]:
    next_day_rows = [row for row in rows if row.get("next_close_return") is not None]
    closed_rows = [row for row in rows if row.get("t_plus_2_close_return") is not None]

    next_open_returns = [float(row["next_open_return"]) for row in next_day_rows if row.get("next_open_return") is not None]
    next_high_returns = [float(row["next_high_return"]) for row in next_day_rows if row.get("next_high_return") is not None]
    next_close_returns = [float(row["next_close_return"]) for row in next_day_rows if row.get("next_close_return") is not None]
    next_open_to_close_returns = [float(row["next_open_to_close_return"]) for row in next_day_rows if row.get("next_open_to_close_return") is not None]
    t_plus_2_close_returns = [float(row["t_plus_2_close_return"]) for row in closed_rows if row.get("t_plus_2_close_return") is not None]

    next_high_hits = sum(1 for value in next_high_returns if value >= next_high_hit_threshold)
    next_close_positive = sum(1 for value in next_close_returns if value > 0)
    t_plus_2_positive = sum(1 for value in t_plus_2_close_returns if value > 0)

    return {
        "total_count": len(rows),
        "next_day_available_count": len(next_day_rows),
        "closed_cycle_count": len(closed_rows),
        "next_open_return_distribution": _summarize_distribution(next_open_returns),
        "next_high_return_distribution": _summarize_distribution(next_high_returns),
        "next_close_return_distribution": _summarize_distribution(next_close_returns),
        "next_open_to_close_return_distribution": _summarize_distribution(next_open_to_close_returns),
        "t_plus_2_close_return_distribution": _summarize_distribution(t_plus_2_close_returns),
        "next_high_hit_threshold": round(next_high_hit_threshold, 4),
        "next_high_hit_rate_at_threshold": None if not next_day_rows else round(next_high_hits / len(next_day_rows), 4),
        "next_close_positive_rate": None if not next_day_rows else round(next_close_positive / len(next_day_rows), 4),
        "t_plus_2_close_positive_rate": None if not closed_rows else round(t_plus_2_positive / len(closed_rows), 4),
    }


def _row_sort_key(row: dict[str, Any]) -> tuple[float, float, float, str, str]:
    return (
        float(row.get("next_high_return") if row.get("next_high_return") is not None else -999.0),
        float(row.get("next_close_return") if row.get("next_close_return") is not None else -999.0),
        float(row.get("score_target") if row.get("score_target") is not None else -999.0),
        str(row.get("trade_date") or ""),
        str(row.get("ticker") or ""),
    )


def _build_false_negative_proxy_rows(rows: list[dict[str, Any]], *, next_high_hit_threshold: float) -> list[dict[str, Any]]:
    proxies: list[dict[str, Any]] = []
    for row in rows:
        if row.get("decision") not in {"blocked", "rejected"}:
            continue
        next_high_return = row.get("next_high_return")
        next_close_return = row.get("next_close_return")
        matched_reasons: list[str] = []
        if next_high_return is not None and float(next_high_return) >= next_high_hit_threshold:
            matched_reasons.append("high_hit")
        if next_close_return is not None and float(next_close_return) > 0:
            matched_reasons.append("next_close_positive")
        if not matched_reasons:
            continue
        proxies.append({**row, "false_negative_proxy_reasons": matched_reasons})
    proxies.sort(key=_row_sort_key, reverse=True)
    return proxies


def _build_day_breakdown(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    cycle_grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        trade_date = str(row.get("trade_date") or "")
        grouped[trade_date][str(row.get("decision") or "unknown")] += 1
        cycle_grouped[trade_date][str(row.get("cycle_status") or "unknown")] += 1

    day_rows: list[dict[str, Any]] = []
    for trade_date in sorted(grouped):
        counts = grouped[trade_date]
        cycle_counts = cycle_grouped[trade_date]
        day_rows.append(
            {
                "trade_date": trade_date,
                "selected_count": int(counts.get("selected", 0)),
                "near_miss_count": int(counts.get("near_miss", 0)),
                "blocked_count": int(counts.get("blocked", 0)),
                "rejected_count": int(counts.get("rejected", 0)),
                "cycle_status_counts": dict(cycle_counts),
            }
        )
    return day_rows


def analyze_btst_micro_window_report(
    report_dir: str | Path,
    *,
    label: str,
    next_high_hit_threshold: float = 0.02,
) -> dict[str, Any]:
    report_path = Path(report_dir).expanduser().resolve()
    selection_root = report_path / "selection_artifacts"
    rows: list[dict[str, Any]] = []
    price_cache: dict[tuple[str, str], pd.DataFrame] = {}
    decision_counts: Counter[str] = Counter()
    candidate_source_counts: Counter[str] = Counter()
    cycle_status_counts: Counter[str] = Counter()
    data_status_counts: Counter[str] = Counter()
    target_modes: Counter[str] = Counter()

    for snapshot in _iter_selection_snapshots(report_path) or []:
        trade_date = _normalize_trade_date(snapshot.get("trade_date"))
        target_mode = str(snapshot.get("target_mode") or "unknown")
        target_modes[target_mode] += 1
        for ticker, evaluation in dict(snapshot.get("selection_targets") or {}).items():
            short_trade = dict((evaluation or {}).get("short_trade") or {})
            if not short_trade:
                continue

            price_outcome = _extract_btst_price_outcome(str(ticker), trade_date, price_cache)
            candidate_source = str((evaluation or {}).get("candidate_source") or dict(short_trade.get("explainability_payload") or {}).get("candidate_source") or "unknown")
            row = {
                "report_label": label,
                "trade_date": trade_date,
                "ticker": str(ticker),
                "decision": str(short_trade.get("decision") or "unknown"),
                "score_target": _round_or_none(_safe_float(short_trade.get("score_target"))),
                "preferred_entry_mode": short_trade.get("preferred_entry_mode"),
                "candidate_source": candidate_source,
                "candidate_reason_codes": list((evaluation or {}).get("candidate_reason_codes") or []),
                "delta_classification": (evaluation or {}).get("delta_classification"),
                "blockers": list(short_trade.get("blockers") or []),
                "gate_status": dict(short_trade.get("gate_status") or {}),
                "target_mode": target_mode,
                **price_outcome,
            }
            rows.append(row)
            decision_counts[row["decision"]] += 1
            candidate_source_counts[candidate_source] += 1
            cycle_status_counts[str(row.get("cycle_status") or "unknown")] += 1
            data_status_counts[str(row.get("data_status") or "unknown")] += 1

    rows.sort(key=lambda row: (str(row.get("trade_date") or ""), str(row.get("ticker") or "")))
    actionable_rows = [row for row in rows if row.get("decision") in {"selected", "near_miss"}]
    selected_rows = [row for row in rows if row.get("decision") == "selected"]
    near_miss_rows = [row for row in rows if row.get("decision") == "near_miss"]
    blocked_rows = [row for row in rows if row.get("decision") == "blocked"]
    rejected_rows = [row for row in rows if row.get("decision") == "rejected"]
    false_negative_rows = _build_false_negative_proxy_rows(rows, next_high_hit_threshold=next_high_hit_threshold)

    top_tradeable_rows = sorted(actionable_rows, key=lambda row: (1 if row.get("decision") == "selected" else 0, float(row.get("score_target") or -999.0), float(row.get("next_high_return") or -999.0)), reverse=True)[:8]

    session_summary_aggregate = None
    artifact_status = "complete"
    if not selection_root.exists():
        session_summary_aggregate = _load_session_summary_aggregate(report_path)
        artifact_status = "missing_selection_artifacts"

    if actionable_rows:
        recommendation = "当前窗口已经形成可研究的 tradeable surface，下一步优先比较 actionable surface 的机会质量与 false negative proxy 的剩余规模。"
    elif false_negative_rows:
        recommendation = "当前窗口的 tradeable surface 仍为空或偏窄，但 closed-cycle false negative proxy 已经存在，优先继续做 score frontier / case-based release，而不是重开 admission floor。"
    elif session_summary_aggregate is not None:
        recommendation = "当前报告目录缺少 selection_artifacts，无法自动重建逐行 surface；请结合 session_summary 聚合统计与原始产物完整性一起解读。"
    else:
        recommendation = "当前窗口既没有稳定的 tradeable surface，也没有形成可用 false negative proxy，先检查样本窗口或价格补齐情况。"

    false_negative_source_counts: Counter[str] = Counter(str(row.get("candidate_source") or "unknown") for row in false_negative_rows)
    false_negative_decision_counts: Counter[str] = Counter(str(row.get("decision") or "unknown") for row in false_negative_rows)

    return {
        "label": label,
        "report_dir": str(report_path),
        "artifact_status": artifact_status,
        "session_summary_aggregate": session_summary_aggregate,
        "target_mode": target_modes.most_common(1)[0][0] if target_modes else "unknown",
        "trade_dates": sorted({str(row.get("trade_date") or "") for row in rows}),
        "row_count": len(rows),
        "decision_counts": dict(decision_counts),
        "candidate_source_counts": dict(candidate_source_counts),
        "cycle_status_counts": dict(cycle_status_counts),
        "data_status_counts": dict(data_status_counts),
        "surface_summaries": {
            "all": _build_surface_summary(rows, next_high_hit_threshold=next_high_hit_threshold),
            "tradeable": _build_surface_summary(actionable_rows, next_high_hit_threshold=next_high_hit_threshold),
            "selected": _build_surface_summary(selected_rows, next_high_hit_threshold=next_high_hit_threshold),
            "near_miss": _build_surface_summary(near_miss_rows, next_high_hit_threshold=next_high_hit_threshold),
            "blocked": _build_surface_summary(blocked_rows, next_high_hit_threshold=next_high_hit_threshold),
            "rejected": _build_surface_summary(rejected_rows, next_high_hit_threshold=next_high_hit_threshold),
        },
        "false_negative_proxy_summary": {
            "count": len(false_negative_rows),
            "candidate_source_counts": dict(false_negative_source_counts),
            "decision_counts": dict(false_negative_decision_counts),
            "surface_metrics": _build_surface_summary(false_negative_rows, next_high_hit_threshold=next_high_hit_threshold),
        },
        "top_tradeable_rows": top_tradeable_rows,
        "top_false_negative_rows": false_negative_rows[:8],
        "day_breakdown": _build_day_breakdown(rows),
        "recommendation": recommendation,
        "rows": rows,
    }


def _delta(left: Any, right: Any) -> float | None:
    left_value = _safe_float(left)
    right_value = _safe_float(right)
    if left_value is None or right_value is None:
        return None
    return round(right_value - left_value, 4)


def _compare_reports(
    baseline: dict[str, Any],
    variant: dict[str, Any],
    *,
    guardrail_next_high_hit_rate: float,
    guardrail_next_close_positive_rate: float,
) -> dict[str, Any]:
    baseline_tradeable = dict(baseline["surface_summaries"]["tradeable"])
    variant_tradeable = dict(variant["surface_summaries"]["tradeable"])
    baseline_false_negative = dict(baseline["false_negative_proxy_summary"])
    variant_false_negative = dict(variant["false_negative_proxy_summary"])

    actionable_count_delta = int(variant_tradeable.get("total_count", 0)) - int(baseline_tradeable.get("total_count", 0))
    closed_cycle_actionable_delta = int(variant_tradeable.get("closed_cycle_count", 0)) - int(baseline_tradeable.get("closed_cycle_count", 0))
    false_negative_delta = int(variant_false_negative.get("count", 0)) - int(baseline_false_negative.get("count", 0))

    guardrail_status = "not_enough_closed_tradeable_rows"
    variant_high_hit_rate = variant_tradeable.get("next_high_hit_rate_at_threshold")
    variant_close_positive_rate = variant_tradeable.get("next_close_positive_rate")
    if variant_tradeable.get("closed_cycle_count", 0):
        if (
            variant_high_hit_rate is not None
            and variant_close_positive_rate is not None
            and float(variant_high_hit_rate) >= guardrail_next_high_hit_rate
            and float(variant_close_positive_rate) >= guardrail_next_close_positive_rate
        ):
            guardrail_status = "passes_closed_tradeable_guardrails"
        else:
            guardrail_status = "fails_closed_tradeable_guardrails"

    if variant.get("artifact_status") == "missing_selection_artifacts" and int(variant.get("row_count", 0)) == 0:
        comparison_note = f"{variant['label']} 的 session_summary 已存在，但 selection_artifacts 缺失，无法自动重建 closed-cycle surface；当前比较仅能视为产物完整性告警，不能解读为 coverage 退化。"
    elif int(baseline_tradeable.get("total_count", 0)) == 0 and int(variant_tradeable.get("total_count", 0)) > 0:
        comparison_note = (
            f"{variant['label']} 把 tradeable surface 从 0 提升到 {variant_tradeable['total_count']}，"
            f"其中 closed-cycle actionable={variant_tradeable['closed_cycle_count']}。"
        )
    elif actionable_count_delta > 0:
        comparison_note = (
            f"{variant['label']} 的 tradeable surface 相比 baseline 增加 {actionable_count_delta}，"
            f"closed-cycle actionable 变化 {closed_cycle_actionable_delta}。"
        )
    elif actionable_count_delta == 0 and false_negative_delta < 0:
        comparison_note = f"{variant['label']} 没有扩大 tradeable surface，但减少了 {abs(false_negative_delta)} 个 false negative proxy。"
    else:
        comparison_note = f"{variant['label']} 相比 baseline 没有形成明确的 coverage 优势，需结合 false negative 和 closed-cycle 质量再判断。"

    return {
        "baseline_label": baseline["label"],
        "variant_label": variant["label"],
        "tradeable_surface_delta": {
            "total_count": actionable_count_delta,
            "closed_cycle_count": closed_cycle_actionable_delta,
            "next_high_hit_rate_at_threshold": _delta(
                baseline_tradeable.get("next_high_hit_rate_at_threshold"),
                variant_tradeable.get("next_high_hit_rate_at_threshold"),
            ),
            "next_close_positive_rate": _delta(
                baseline_tradeable.get("next_close_positive_rate"),
                variant_tradeable.get("next_close_positive_rate"),
            ),
            "t_plus_2_close_positive_rate": _delta(
                baseline_tradeable.get("t_plus_2_close_positive_rate"),
                variant_tradeable.get("t_plus_2_close_positive_rate"),
            ),
            "next_high_return_mean": _delta(
                dict(baseline_tradeable.get("next_high_return_distribution") or {}).get("mean"),
                dict(variant_tradeable.get("next_high_return_distribution") or {}).get("mean"),
            ),
            "next_close_return_mean": _delta(
                dict(baseline_tradeable.get("next_close_return_distribution") or {}).get("mean"),
                dict(variant_tradeable.get("next_close_return_distribution") or {}).get("mean"),
            ),
            "t_plus_2_close_return_mean": _delta(
                dict(baseline_tradeable.get("t_plus_2_close_return_distribution") or {}).get("mean"),
                dict(variant_tradeable.get("t_plus_2_close_return_distribution") or {}).get("mean"),
            ),
        },
        "false_negative_proxy_delta": {
            "count": false_negative_delta,
            "next_high_hit_rate_at_threshold": _delta(
                dict(baseline_false_negative.get("surface_metrics") or {}).get("next_high_hit_rate_at_threshold"),
                dict(variant_false_negative.get("surface_metrics") or {}).get("next_high_hit_rate_at_threshold"),
            ),
            "next_close_positive_rate": _delta(
                dict(baseline_false_negative.get("surface_metrics") or {}).get("next_close_positive_rate"),
                dict(variant_false_negative.get("surface_metrics") or {}).get("next_close_positive_rate"),
            ),
        },
        "guardrail_status": guardrail_status,
        "comparison_note": comparison_note,
    }


def _parse_labeled_paths(values: list[str]) -> dict[str, str]:
    labeled: dict[str, str] = {}
    for raw in values:
        token = str(raw or "").strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError(f"Expected label=path, got: {token}")
        label, path = token.split("=", 1)
        labeled[label.strip()] = path.strip()
    return labeled


def analyze_btst_micro_window_regression(
    baseline_report_dir: str | Path,
    *,
    variant_reports: dict[str, str] | None = None,
    forward_reports: dict[str, str] | None = None,
    next_high_hit_threshold: float = 0.02,
    guardrail_next_high_hit_rate: float = 0.5217,
    guardrail_next_close_positive_rate: float = 0.5652,
) -> dict[str, Any]:
    baseline = analyze_btst_micro_window_report(
        baseline_report_dir,
        label="baseline",
        next_high_hit_threshold=next_high_hit_threshold,
    )
    variant_analyses = [
        analyze_btst_micro_window_report(path, label=label, next_high_hit_threshold=next_high_hit_threshold)
        for label, path in sorted((variant_reports or {}).items())
    ]
    forward_analyses = [
        analyze_btst_micro_window_report(path, label=label, next_high_hit_threshold=next_high_hit_threshold)
        for label, path in sorted((forward_reports or {}).items())
    ]
    comparisons = [
        _compare_reports(
            baseline,
            variant,
            guardrail_next_high_hit_rate=guardrail_next_high_hit_rate,
            guardrail_next_close_positive_rate=guardrail_next_close_positive_rate,
        )
        for variant in variant_analyses
    ]

    return {
        "baseline": baseline,
        "variants": variant_analyses,
        "forward_reports": forward_analyses,
        "comparisons": comparisons,
        "next_high_hit_threshold": round(next_high_hit_threshold, 4),
        "guardrail_next_high_hit_rate": round(guardrail_next_high_hit_rate, 4),
        "guardrail_next_close_positive_rate": round(guardrail_next_close_positive_rate, 4),
    }


def render_btst_micro_window_regression_markdown(analysis: dict[str, Any]) -> str:
    baseline = dict(analysis["baseline"])
    lines: list[str] = []
    lines.append("# BTST Micro-Window Regression Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- baseline_report: {baseline['report_dir']}")
    lines.append(f"- baseline_trade_dates: {baseline['trade_dates']}")
    lines.append(f"- next_high_hit_threshold: {analysis['next_high_hit_threshold']}")
    lines.append(f"- guardrail_next_high_hit_rate: {analysis['guardrail_next_high_hit_rate']}")
    lines.append(f"- guardrail_next_close_positive_rate: {analysis['guardrail_next_close_positive_rate']}")
    lines.append("")
    lines.append("## Baseline Summary")
    lines.append(f"- decision_counts: {baseline['decision_counts']}")
    lines.append(f"- candidate_source_counts: {baseline['candidate_source_counts']}")
    lines.append(f"- cycle_status_counts: {baseline['cycle_status_counts']}")
    lines.append(f"- tradeable_surface: {baseline['surface_summaries']['tradeable']}")
    lines.append(f"- false_negative_proxy_summary: {baseline['false_negative_proxy_summary']}")
    lines.append(f"- recommendation: {baseline['recommendation']}")
    lines.append("")
    if analysis["variants"]:
        lines.append("## Variant Comparison")
        for variant, comparison in zip(analysis["variants"], analysis["comparisons"]):
            lines.append(f"### {variant['label']}")
            lines.append(f"- report_dir: {variant['report_dir']}")
            lines.append(f"- artifact_status: {variant.get('artifact_status')}")
            if variant.get("session_summary_aggregate"):
                lines.append(f"- session_summary_aggregate: {variant['session_summary_aggregate']}")
            lines.append(f"- decision_counts: {variant['decision_counts']}")
            lines.append(f"- cycle_status_counts: {variant['cycle_status_counts']}")
            lines.append(f"- tradeable_surface: {variant['surface_summaries']['tradeable']}")
            lines.append(f"- false_negative_proxy_summary: {variant['false_negative_proxy_summary']}")
            lines.append(f"- guardrail_status: {comparison['guardrail_status']}")
            lines.append(f"- comparison_note: {comparison['comparison_note']}")
            lines.append(f"- tradeable_surface_delta: {comparison['tradeable_surface_delta']}")
            lines.append(f"- false_negative_proxy_delta: {comparison['false_negative_proxy_delta']}")
            lines.append("")
    if analysis["forward_reports"]:
        lines.append("## Forward Reports")
        for report in analysis["forward_reports"]:
            lines.append(f"### {report['label']}")
            lines.append(f"- report_dir: {report['report_dir']}")
            lines.append(f"- trade_dates: {report['trade_dates']}")
            lines.append(f"- cycle_status_counts: {report['cycle_status_counts']}")
            lines.append(f"- tradeable_surface: {report['surface_summaries']['tradeable']}")
            lines.append(f"- top_tradeable_rows: {report['top_tradeable_rows']}")
            lines.append(f"- recommendation: {report['recommendation']}")
            lines.append("")
    lines.append("## Baseline Top False Negatives")
    for row in baseline["top_false_negative_rows"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: decision={row['decision']}, source={row['candidate_source']}, next_high_return={row['next_high_return']}, next_close_return={row['next_close_return']}, t_plus_2_close_return={row['t_plus_2_close_return']}, reasons={row['false_negative_proxy_reasons']}"
        )
    if not baseline["top_false_negative_rows"]:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze BTST micro-window regression quality across closed-cycle and forward-only report windows.")
    parser.add_argument("--baseline-report-dir", required=True)
    parser.add_argument("--variant-report", action="append", default=[], help="Repeated label=path entries for comparable variant windows")
    parser.add_argument("--forward-report", action="append", default=[], help="Repeated label=path entries for forward-only windows")
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--guardrail-next-high-hit-rate", type=float, default=0.5217)
    parser.add_argument("--guardrail-next-close-positive-rate", type=float, default=0.5652)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_btst_micro_window_regression(
        args.baseline_report_dir,
        variant_reports=_parse_labeled_paths(list(args.variant_report)),
        forward_reports=_parse_labeled_paths(list(args.forward_report)),
        next_high_hit_threshold=float(args.next_high_hit_threshold),
        guardrail_next_high_hit_rate=float(args.guardrail_next_high_hit_rate),
        guardrail_next_close_positive_rate=float(args.guardrail_next_close_positive_rate),
    )

    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_btst_micro_window_regression_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()