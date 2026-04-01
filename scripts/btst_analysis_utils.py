from __future__ import annotations

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


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def normalize_trade_date(value: Any) -> str:
    token = str(value or "").strip()
    if len(token) == 8 and token.isdigit():
        return f"{token[:4]}-{token[4:6]}-{token[6:8]}"
    return token


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def iter_selection_snapshots(report_dir: str | Path):
    selection_root = Path(report_dir).expanduser().resolve() / "selection_artifacts"
    if not selection_root.exists():
        return
    for day_dir in sorted(path for path in selection_root.iterdir() if path.is_dir()):
        snapshot_path = day_dir / "selection_snapshot.json"
        if snapshot_path.exists():
            yield load_json(snapshot_path)


def load_session_summary_aggregate(report_dir: str | Path) -> dict[str, Any] | None:
    report_path = Path(report_dir).expanduser().resolve()
    session_summary_path = report_path / "session_summary.json"
    if not session_summary_path.exists():
        return None

    session_summary = load_json(session_summary_path)
    selection_artifact_root = Path(str(((session_summary.get("artifacts") or {}).get("selection_artifact_root") or report_path / "selection_artifacts"))).expanduser()
    daily_events_path = Path(str(((session_summary.get("artifacts") or {}).get("daily_events") or report_path / "daily_events.jsonl"))).expanduser()
    return {
        "session_summary_path": str(session_summary_path),
        "selection_target": ((session_summary.get("plan_generation") or {}).get("selection_target")),
        "dual_target_summary": dict(session_summary.get("dual_target_summary") or {}),
        "daily_event_stats": dict(session_summary.get("daily_event_stats") or {}),
        "selection_artifact_root_exists": selection_artifact_root.exists(),
        "daily_events_exists": daily_events_path.exists(),
    }


def normalize_price_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
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


def fetch_price_frame(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], pd.DataFrame]) -> pd.DataFrame:
    normalized_trade_date = normalize_trade_date(trade_date)
    cache_key = (ticker, normalized_trade_date)
    cached = price_cache.get(cache_key)
    if cached is not None:
        return cached

    end_date = (pd.Timestamp(normalized_trade_date) + pd.Timedelta(days=15)).strftime("%Y-%m-%d")
    try:
        frame = normalize_price_frame(get_price_data(ticker, normalized_trade_date, end_date))
    except Exception:
        try:
            frame = normalize_price_frame(prices_to_df(get_prices_robust(ticker, normalized_trade_date, end_date, use_mock_on_fail=False)))
        except Exception:
            frame = pd.DataFrame()

    price_cache[cache_key] = frame
    return frame


def extract_btst_price_outcome(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], pd.DataFrame]) -> dict[str, Any]:
    normalized_trade_date = normalize_trade_date(trade_date)
    frame = fetch_price_frame(ticker, normalized_trade_date, price_cache)
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
            "trade_close": round_or_none(safe_float(same_day.iloc[0].get("close"))),
            "cycle_status": "missing_next_day",
        }

    trade_row = same_day.iloc[0]
    next_row = future_days.iloc[0]
    later_rows = future_days.iloc[1:]

    trade_close = safe_float(trade_row.get("close"))
    next_open = safe_float(next_row.get("open"))
    next_high = safe_float(next_row.get("high"))
    next_close = safe_float(next_row.get("close"))
    if trade_close is None or trade_close <= 0 or next_open is None or next_high is None or next_close is None:
        return {
            "data_status": "incomplete_next_trade_day_bar",
            "cycle_status": "missing_next_day",
        }

    t_plus_2_close = None
    t_plus_2_trade_date = None
    if not later_rows.empty:
        second_row = later_rows.iloc[0]
        t_plus_2_close = safe_float(second_row.get("close"))
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
        "t_plus_2_close": round_or_none(t_plus_2_close),
        "t_plus_2_close_return": None if t_plus_2_close is None else round((t_plus_2_close / trade_close) - 1.0, 4),
    }


def summarize_distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(mean(values), 4),
    }


def build_surface_summary(rows: list[dict[str, Any]], *, next_high_hit_threshold: float) -> dict[str, Any]:
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
        "next_open_return_distribution": summarize_distribution(next_open_returns),
        "next_high_return_distribution": summarize_distribution(next_high_returns),
        "next_close_return_distribution": summarize_distribution(next_close_returns),
        "next_open_to_close_return_distribution": summarize_distribution(next_open_to_close_returns),
        "t_plus_2_close_return_distribution": summarize_distribution(t_plus_2_close_returns),
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


def build_false_negative_proxy_rows(rows: list[dict[str, Any]], *, next_high_hit_threshold: float) -> list[dict[str, Any]]:
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


def build_day_breakdown(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def resolve_guardrail(value: float | None, baseline_value: Any, fallback: float) -> float:
    if value is not None:
        return round(float(value), 4)
    if baseline_value is None:
        return round(float(fallback), 4)
    return round(float(baseline_value), 4)


def _delta(left: Any, right: Any) -> float | None:
    left_value = safe_float(left)
    right_value = safe_float(right)
    if left_value is None or right_value is None:
        return None
    return round(right_value - left_value, 4)


def compare_reports(
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