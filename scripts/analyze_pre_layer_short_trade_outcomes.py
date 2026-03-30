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


REPLAY_INPUT_FILENAME = "selection_target_replay_input.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_candidate_sources(raw: str | None) -> set[str]:
    if raw is None or not str(raw).strip():
        return set()
    return {token.strip() for token in str(raw).split(",") if token.strip()}


def _parse_tickers(raw: str | None) -> set[str]:
    if raw is None or not str(raw).strip():
        return set()
    return {token.strip() for token in str(raw).split(",") if token.strip()}


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _summarize(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(mean(values), 4),
    }


def _iter_replay_inputs(report_dir: Path):
    selection_root = report_dir / "selection_artifacts"
    for day_dir in sorted(path for path in selection_root.iterdir() if path.is_dir()):
        replay_input_path = day_dir / REPLAY_INPUT_FILENAME
        if replay_input_path.exists():
            yield replay_input_path, _load_json(replay_input_path)


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


def render_pre_layer_short_trade_outcomes_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Pre-Layer C Short Trade Candidate Outcome Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- candidate_sources_filter: {analysis['candidate_sources_filter']}")
    lines.append(f"- tickers_filter: {analysis['tickers_filter']}")
    lines.append(f"- candidate_count: {analysis['candidate_count']}")
    lines.append(f"- data_status_counts: {analysis['data_status_counts']}")
    lines.append(f"- candidate_source_counts: {analysis['candidate_source_counts']}")
    lines.append("")
    lines.append("## Returns Summary")
    lines.append(f"- next_open_return: {analysis['next_open_return_distribution']}")
    lines.append(f"- next_high_return: {analysis['next_high_return_distribution']}")
    lines.append(f"- next_close_return: {analysis['next_close_return_distribution']}")
    lines.append("")
    lines.append("## Hit Rates")
    lines.append(f"- next_high_hit_rate_at_threshold: {analysis['next_high_hit_rate_at_threshold']}")
    lines.append(f"- next_close_positive_rate: {analysis['next_close_positive_rate']}")
    lines.append("")
    lines.append("## Source Breakdown")
    for source, summary in analysis["source_breakdown"].items():
        lines.append(
            f"- {source}: count={summary['count']}, next_high_mean={summary['next_high_return_mean']}, next_close_mean={summary['next_close_return_mean']}, high_hit_rate={summary['next_high_hit_rate_at_threshold']}, close_positive_rate={summary['next_close_positive_rate']}"
        )
    lines.append("")
    lines.append("## Top Cases")
    for row in analysis["top_cases"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: source={row['candidate_source']}, candidate_score={row['candidate_score']}, next_high_return={row['next_high_return']}, next_close_return={row['next_close_return']}"
        )
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_pre_layer_short_trade_outcomes(
    report_dir: str | Path,
    *,
    candidate_sources: set[str] | None = None,
    tickers: set[str] | None = None,
    next_high_hit_threshold: float = 0.02,
) -> dict[str, Any]:
    report_path = Path(report_dir).expanduser().resolve()
    active_sources = {str(value) for value in (candidate_sources or set()) if str(value).strip()}
    active_tickers = {str(value) for value in (tickers or set()) if str(value).strip()}
    candidate_rows: list[dict[str, Any]] = []
    price_cache: dict[tuple[str, str], pd.DataFrame] = {}
    data_status_counts: Counter[str] = Counter()
    candidate_source_counts: Counter[str] = Counter()
    source_return_buckets: dict[str, dict[str, list[float] | int]] = defaultdict(lambda: {"next_high": [], "next_close": [], "count": 0, "high_hits": 0, "close_positive": 0})

    for _, replay_input in _iter_replay_inputs(report_path):
        trade_date = str(replay_input.get("trade_date") or "")
        for entry in list(replay_input.get("supplemental_short_trade_entries") or []):
            ticker = str(entry.get("ticker") or "")
            if active_tickers and ticker not in active_tickers:
                continue
            candidate_source = str(entry.get("candidate_source") or "unknown")
            if active_sources and candidate_source not in active_sources:
                continue
            outcome = _extract_next_day_outcome(ticker, trade_date, price_cache)
            data_status = str(outcome.get("data_status") or "unknown")
            data_status_counts[data_status] += 1
            candidate_source_counts[candidate_source] += 1
            row = {
                "trade_date": trade_date,
                "ticker": ticker,
                "candidate_source": candidate_source,
                "candidate_score": _round_or_none(_safe_float(dict(entry.get("short_trade_boundary_metrics") or {}).get("candidate_score"))),
                "breakout_freshness": _round_or_none(_safe_float(dict(entry.get("short_trade_boundary_metrics") or {}).get("breakout_freshness"))),
                "trend_acceleration": _round_or_none(_safe_float(dict(entry.get("short_trade_boundary_metrics") or {}).get("trend_acceleration"))),
                "volume_expansion_quality": _round_or_none(_safe_float(dict(entry.get("short_trade_boundary_metrics") or {}).get("volume_expansion_quality"))),
                "catalyst_freshness": _round_or_none(_safe_float(dict(entry.get("short_trade_boundary_metrics") or {}).get("catalyst_freshness"))),
                **outcome,
            }
            candidate_rows.append(row)

            if data_status != "ok":
                continue
            next_high_return = float(outcome["next_high_return"])
            next_close_return = float(outcome["next_close_return"])
            source_bucket = source_return_buckets[candidate_source]
            cast_high = source_bucket["next_high"]
            cast_close = source_bucket["next_close"]
            assert isinstance(cast_high, list) and isinstance(cast_close, list)
            cast_high.append(next_high_return)
            cast_close.append(next_close_return)
            source_bucket["count"] = int(source_bucket["count"]) + 1
            if next_high_return >= next_high_hit_threshold:
                source_bucket["high_hits"] = int(source_bucket["high_hits"]) + 1
            if next_close_return > 0:
                source_bucket["close_positive"] = int(source_bucket["close_positive"]) + 1

    ok_rows = [row for row in candidate_rows if row.get("data_status") == "ok"]
    next_open_returns = [float(row["next_open_return"]) for row in ok_rows]
    next_high_returns = [float(row["next_high_return"]) for row in ok_rows]
    next_close_returns = [float(row["next_close_return"]) for row in ok_rows]
    next_high_hits = sum(1 for value in next_high_returns if value >= next_high_hit_threshold)
    next_close_positive = sum(1 for value in next_close_returns if value > 0)

    source_breakdown: dict[str, dict[str, Any]] = {}
    for source, bucket in sorted(source_return_buckets.items()):
        high_values = list(bucket["next_high"])
        close_values = list(bucket["next_close"])
        count = int(bucket["count"])
        source_breakdown[source] = {
            "count": count,
            "next_high_return_mean": round(mean(high_values), 4) if high_values else None,
            "next_close_return_mean": round(mean(close_values), 4) if close_values else None,
            "next_high_hit_rate_at_threshold": None if count == 0 else round(int(bucket["high_hits"]) / count, 4),
            "next_close_positive_rate": None if count == 0 else round(int(bucket["close_positive"]) / count, 4),
        }

    candidate_rows.sort(key=lambda row: (float(row.get("next_high_return") or -999.0), str(row.get("trade_date") or ""), str(row.get("ticker") or "")), reverse=True)

    if ok_rows:
        recommendation = (
            f"当前前置短线候选共有 {len(ok_rows)} 个拿到了次日行情；next_high 命中阈值 {round(next_high_hit_threshold, 4)} 的比例为 "
            f"{round(next_high_hits / len(ok_rows), 4)}，next_close 为正的比例为 {round(next_close_positive / len(ok_rows), 4)}。"
        )
    else:
        recommendation = "当前报告里没有拿到可用次日行情的前置短线候选，先补齐价格数据后再做前置策略优化。"

    return {
        "report_dir": str(report_path),
        "candidate_sources_filter": sorted(active_sources),
        "tickers_filter": sorted(active_tickers),
        "candidate_count": len(candidate_rows),
        "data_status_counts": dict(data_status_counts.most_common()),
        "candidate_source_counts": dict(candidate_source_counts.most_common()),
        "next_open_return_distribution": _summarize(next_open_returns),
        "next_high_return_distribution": _summarize(next_high_returns),
        "next_close_return_distribution": _summarize(next_close_returns),
        "next_high_hit_threshold": round(next_high_hit_threshold, 4),
        "next_high_hit_rate_at_threshold": None if not ok_rows else round(next_high_hits / len(ok_rows), 4),
        "next_close_positive_rate": None if not ok_rows else round(next_close_positive / len(ok_rows), 4),
        "source_breakdown": source_breakdown,
        "top_cases": candidate_rows[:8],
        "rows": candidate_rows,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze next-day outcomes for pre-Layer C short-trade candidates from selection artifacts.")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--candidate-sources", default="", help="Optional comma-separated candidate_source filter")
    parser.add_argument("--tickers", default="", help="Optional comma-separated ticker filter")
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_pre_layer_short_trade_outcomes(
        args.report_dir,
        candidate_sources=_parse_candidate_sources(args.candidate_sources),
        tickers=_parse_tickers(args.tickers),
        next_high_hit_threshold=float(args.next_high_hit_threshold),
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_pre_layer_short_trade_outcomes_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()