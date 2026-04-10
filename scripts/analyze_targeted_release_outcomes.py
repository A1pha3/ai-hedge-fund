from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

import pandas as pd

from src.project_env import load_project_dotenv
from src.tools.akshare_api import get_prices_robust
from src.tools.api import get_price_data, prices_to_df


load_project_dotenv()


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_price_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    normalized = frame.copy()
    if not isinstance(normalized.index, pd.DatetimeIndex):
        normalized.index = pd.to_datetime(normalized.index)
    normalized = normalized.sort_index()
    normalized.columns = [str(column).lower() for column in normalized.columns]
    return normalized


def _extract_next_day_outcome(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], pd.DataFrame]) -> dict[str, Any]:
    cache_key = (ticker, trade_date)
    frame = price_cache.get(cache_key)
    if frame is None:
        end_date = (pd.Timestamp(trade_date) + pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        try:
            frame = _normalize_price_frame(get_price_data(ticker, trade_date, end_date))
        except Exception:
            try:
                frame = _normalize_price_frame(prices_to_df(get_prices_robust(ticker, trade_date, end_date, use_mock_on_fail=False)))
            except Exception:
                frame = pd.DataFrame()
        price_cache[cache_key] = frame
    if frame.empty:
        return {"data_status": "missing_price_frame"}

    trade_ts = pd.Timestamp(trade_date)
    same_day = frame.loc[frame.index.normalize() == trade_ts.normalize()]
    next_day = frame.loc[frame.index.normalize() > trade_ts.normalize()]
    if same_day.empty:
        return {"data_status": "missing_trade_day_bar"}
    if next_day.empty:
        return {"data_status": "missing_next_trade_day_bar"}

    trade_row = same_day.iloc[0]
    next_row = next_day.iloc[0]
    trade_close = _safe_float(trade_row.get("close"))
    next_open = _safe_float(next_row.get("open"))
    next_high = _safe_float(next_row.get("high"))
    next_close = _safe_float(next_row.get("close"))
    if trade_close is None or trade_close <= 0 or next_open is None or next_high is None or next_close is None:
        return {"data_status": "incomplete_price_bar"}

    return {
        "data_status": "ok",
        "next_trade_date": next_day.index[0].strftime("%Y-%m-%d"),
        "trade_close": round(trade_close, 4),
        "next_open": round(next_open, 4),
        "next_high": round(next_high, 4),
        "next_close": round(next_close, 4),
        "next_open_return": round((next_open / trade_close) - 1.0, 4),
        "next_high_return": round((next_high / trade_close) - 1.0, 4),
        "next_close_return": round((next_close / trade_close) - 1.0, 4),
        "next_open_to_close_return": round((next_close / next_open) - 1.0, 4),
    }


def _resolve_thresholds(release_analysis: dict[str, Any], target_row: dict[str, Any]) -> dict[str, float | None]:
    profile_overrides = dict(release_analysis.get("profile_overrides") or {})
    return {
        "select_threshold": _safe_float(release_analysis.get("select_threshold") or target_row.get("select_threshold")),
        "near_miss_threshold": _safe_float(
            release_analysis.get("near_miss_threshold")
            or profile_overrides.get("near_miss_threshold")
            or target_row.get("near_miss_threshold")
        ),
        "stale_weight": _safe_float(release_analysis.get("stale_weight") or target_row.get("stale_weight")),
        "extension_weight": _safe_float(release_analysis.get("extension_weight") or target_row.get("extension_weight")),
    }


def _resolve_target_rows(release_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    targets = [str(token) for token in list(release_analysis.get("targets") or []) if str(token).strip()]
    rows = list(release_analysis.get("target_changed_cases") or release_analysis.get("changed_cases") or [])
    row_by_key = {f"{row.get('trade_date')}:{row.get('ticker')}": dict(row) for row in rows}

    resolved: list[dict[str, Any]] = []
    for target in targets:
        trade_date, ticker = target.split(":", 1)
        row = dict(row_by_key.get(target) or {})
        if not row:
            row = {"trade_date": trade_date, "ticker": ticker}
        resolved.append(row)
    return resolved


def _infer_release_mode(release_analysis: dict[str, Any], target_cases: list[dict[str, Any]]) -> str:
    if release_analysis.get("select_threshold") is not None:
        return "near_miss_promotion"
    if release_analysis.get("profile_overrides"):
        return "structural_conflict_release"
    if target_cases and str(target_cases[0].get("before_decision") or "") == "rejected":
        return "score_frontier_release"
    return "targeted_release"


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(mean(values), 4)


def render_targeted_release_outcomes_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Targeted Release Outcome Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- release_report: {analysis['release_report']}")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- release_mode: {analysis['release_mode']}")
    lines.append(f"- ticker: {analysis['ticker']}")
    lines.append(f"- target_case_count: {analysis['target_case_count']}")
    lines.append(f"- promoted_target_case_count: {analysis['promoted_target_case_count']}")
    lines.append(f"- changed_non_target_case_count: {analysis['changed_non_target_case_count']}")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- next_high_return_mean: {analysis['next_high_return_mean']}")
    lines.append(f"- next_close_return_mean: {analysis['next_close_return_mean']}")
    lines.append(f"- next_high_hit_rate_at_threshold: {analysis['next_high_hit_rate_at_threshold']}")
    lines.append(f"- next_close_positive_rate: {analysis['next_close_positive_rate']}")
    lines.append("")
    lines.append("## Target Cases")
    for row in analysis["target_cases"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: {row['before_decision']} -> {row['after_decision']}, next_open_return={row.get('next_open_return')}, next_high_return={row.get('next_high_return')}, next_close_return={row.get('next_close_return')}, release_verdict={row['release_verdict']}"
        )
    if not analysis["target_cases"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def _enrich_target_release_rows(
    target_rows: list[dict[str, Any]],
    *,
    release_analysis: dict[str, Any],
    next_high_hit_threshold: float,
) -> dict[str, Any]:
    price_cache: dict[tuple[str, str], pd.DataFrame] = {}
    enriched_rows: list[dict[str, Any]] = []
    promoted_target_case_count = 0
    positive_next_close_count = 0
    high_hit_count = 0
    next_high_values: list[float] = []
    next_close_values: list[float] = []
    for row in target_rows:
        enriched_row = _build_enriched_target_release_row(
            row,
            release_analysis=release_analysis,
            price_cache=price_cache,
            next_high_hit_threshold=next_high_hit_threshold,
        )
        enriched_rows.append(enriched_row)
        if enriched_row["promoted"]:
            promoted_target_case_count += 1
        next_high_return = enriched_row.get("next_high_return")
        if next_high_return is not None:
            next_high_values.append(float(next_high_return))
            if float(next_high_return) >= next_high_hit_threshold:
                high_hit_count += 1
        next_close_return = enriched_row.get("next_close_return")
        if next_close_return is not None:
            next_close_values.append(float(next_close_return))
            if float(next_close_return) > 0:
                positive_next_close_count += 1
    return {
        "enriched_rows": enriched_rows,
        "promoted_target_case_count": promoted_target_case_count,
        "positive_next_close_count": positive_next_close_count,
        "high_hit_count": high_hit_count,
        "next_high_values": next_high_values,
        "next_close_values": next_close_values,
    }


def _build_enriched_target_release_row(
    row: dict[str, Any],
    *,
    release_analysis: dict[str, Any],
    price_cache: dict[tuple[str, str], pd.DataFrame],
    next_high_hit_threshold: float,
) -> dict[str, Any]:
    trade_date = str(row.get("trade_date") or "")
    ticker = str(row.get("ticker") or "")
    outcome = _extract_next_day_outcome(ticker, trade_date, price_cache)
    thresholds = _resolve_thresholds(release_analysis, row)
    before_decision = row.get("before_decision")
    after_decision = row.get("after_decision")
    promoted = str(after_decision or "") in {"near_miss", "selected"} and str(after_decision or "") != str(before_decision or "")
    return {
        **row,
        **thresholds,
        **outcome,
        "promoted": promoted,
        "release_verdict": _build_target_release_verdict(
            promoted=promoted,
            next_high_return=outcome.get("next_high_return"),
            next_close_return=outcome.get("next_close_return"),
            next_high_hit_threshold=next_high_hit_threshold,
        ),
    }


def _build_target_release_verdict(
    *,
    promoted: bool,
    next_high_return: float | None,
    next_close_return: float | None,
    next_high_hit_threshold: float,
) -> str:
    if promoted and next_close_return is not None and float(next_close_return) > 0:
        return "promoted_with_positive_close"
    if promoted and next_high_return is not None and float(next_high_return) >= next_high_hit_threshold:
        return "promoted_with_intraday_upside"
    if promoted:
        return "promoted_but_outcome_mixed"
    return "not_promoted"


def _build_targeted_release_outcomes_recommendation(
    *,
    enriched_rows: list[dict[str, Any]],
    promoted_target_case_count: int,
    positive_next_close_count: int,
    high_hit_count: int,
    next_close_positive_rate: float | None,
    ticker: str,
) -> str:
    if enriched_rows and promoted_target_case_count == len(enriched_rows) and positive_next_close_count == len(enriched_rows):
        return (
            f"当前 targeted release 值得继续保留。{ticker} 的 {len(enriched_rows)} 个目标样本都完成了目标迁移，"
            f"且 next_close_positive_rate={next_close_positive_rate}。"
        )
    if enriched_rows and promoted_target_case_count == len(enriched_rows) and high_hit_count == len(enriched_rows):
        return "当前 targeted release 至少兑现了稳定的 intraday upside，但 close continuation 仍需继续观察。"
    if enriched_rows and promoted_target_case_count > 0:
        return "当前 targeted release 已发生变化，但真实次日表现没有形成一致支持，建议继续保留为观察样本。"
    if enriched_rows:
        return "目标样本拿到了后验行情，但当前 release 没有形成有效迁移。"
    return "当前没有可供评估的 targeted release 样本。"


def analyze_targeted_release_outcomes(
    release_report: str | Path,
    *,
    next_high_hit_threshold: float = 0.02,
) -> dict[str, Any]:
    release_analysis = _load_json(release_report)
    target_rows = _resolve_target_rows(release_analysis)
    release_mode = _infer_release_mode(release_analysis, target_rows)
    report_dir = str(release_analysis.get("report_dir") or "")
    enrichment = _enrich_target_release_rows(
        target_rows,
        release_analysis=release_analysis,
        next_high_hit_threshold=next_high_hit_threshold,
    )
    enriched_rows = enrichment["enriched_rows"]
    promoted_target_case_count = enrichment["promoted_target_case_count"]
    positive_next_close_count = enrichment["positive_next_close_count"]
    high_hit_count = enrichment["high_hit_count"]
    next_high_values = enrichment["next_high_values"]
    next_close_values = enrichment["next_close_values"]
    for row in enriched_rows:
        row.pop("promoted", None)

    next_high_return_mean = _mean(next_high_values)
    next_close_return_mean = _mean(next_close_values)
    next_high_hit_rate = round(high_hit_count / len(enriched_rows), 4) if enriched_rows else None
    next_close_positive_rate = round(positive_next_close_count / len(enriched_rows), 4) if enriched_rows else None
    ticker = str(enriched_rows[0].get("ticker") or "") if enriched_rows else ""
    recommendation = _build_targeted_release_outcomes_recommendation(
        enriched_rows=enriched_rows,
        promoted_target_case_count=promoted_target_case_count,
        positive_next_close_count=positive_next_close_count,
        high_hit_count=high_hit_count,
        next_close_positive_rate=next_close_positive_rate,
        ticker=ticker,
    )

    return {
        "release_report": str(Path(release_report).expanduser().resolve()),
        "report_dir": report_dir,
        "release_mode": release_mode,
        "ticker": ticker,
        "target_case_count": len(enriched_rows),
        "promoted_target_case_count": promoted_target_case_count,
        "changed_non_target_case_count": int(release_analysis.get("changed_non_target_case_count") or len(release_analysis.get("non_target_changed_cases") or [])),
        "next_high_hit_threshold": round(next_high_hit_threshold, 4),
        "next_high_return_mean": next_high_return_mean,
        "next_close_return_mean": next_close_return_mean,
        "next_high_hit_rate_at_threshold": next_high_hit_rate,
        "next_close_positive_rate": next_close_positive_rate,
        "positive_next_close_count": positive_next_close_count,
        "select_threshold": _safe_float(release_analysis.get("select_threshold")),
        "near_miss_threshold": _safe_float(
            release_analysis.get("near_miss_threshold") or dict(release_analysis.get("profile_overrides") or {}).get("near_miss_threshold")
        ),
        "target_cases": enriched_rows,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate next-day outcomes for a targeted release report.")
    parser.add_argument("--release-report", required=True)
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_targeted_release_outcomes(
        args.release_report,
        next_high_hit_threshold=float(args.next_high_hit_threshold),
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_targeted_release_outcomes_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
