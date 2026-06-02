from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from scripts.generate_btst_realized_prices import generate_realized_prices


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _write_text(path: str | Path, text: str) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _write_json(path: str | Path, payload: Any) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p10": None, "p25": None, "p50": None, "p75": None, "p90": None}
    series = pd.Series(values, dtype="float64")
    return {
        "p10": float(series.quantile(0.10)),
        "p25": float(series.quantile(0.25)),
        "p50": float(series.quantile(0.50)),
        "p75": float(series.quantile(0.75)),
        "p90": float(series.quantile(0.90)),
    }


def _mean(values: Iterable[float]) -> float | None:
    items = list(values)
    if not items:
        return None
    return float(sum(items) / len(items))


def _compact_date(value: str) -> str:
    token = str(value or "").strip()
    if len(token) == 10 and token[4] == "-" and token[7] == "-":
        return token.replace("-", "")
    return token


def _extract_high_confidence(report: dict[str, Any], top_n: int) -> list[dict[str, Any]]:
    entries = list(report.get("high_confidence") or [])
    if top_n <= 0:
        return entries
    return entries[:top_n]


def _iter_month_reports(*, reports_dir: Path, month: str) -> list[Path]:
    resolved_month = str(month).strip()
    candidates = sorted(reports_dir.glob(f"btst_full_report_{resolved_month}*.json"))
    return [path for path in candidates if path.is_file()]


@dataclass
class DailyScorecard:
    trade_date: str
    next_date: str | None
    pick_count: int
    ok_count: int
    missing_count: int
    win_rate_next_close: float | None
    mean_next_close_return: float | None
    mean_next_open_return: float | None
    mean_next_open_to_close_return: float | None
    hit_rate_5d_15: float | None


def _daily_metrics(outcomes: list[dict[str, Any]]) -> DailyScorecard:
    trade_date = str(outcomes[0]["trade_date"]) if outcomes else ""
    next_date = str(outcomes[0].get("next_date") or "").strip() or None if outcomes else None

    ok = [row for row in outcomes if row.get("data_status") == "ok"]
    close_returns = [float(row["next_close_return"]) for row in ok if row.get("next_close_return") is not None]
    open_returns = [float(row["next_open_return"]) for row in ok if row.get("next_open_return") is not None]
    intraday_returns = [
        float(row["next_open_to_close_return"]) for row in ok if row.get("next_open_to_close_return") is not None
    ]

    hits = [
        1.0
        for row in ok
        if row.get("max_high_t1_t5_from_open") is not None and float(row["max_high_t1_t5_from_open"]) >= 0.15
    ]
    eligible_hits = [1.0 for row in ok if row.get("max_high_t1_t5_from_open") is not None]

    win_rate = None
    if close_returns:
        win_rate = float(sum(1.0 for r in close_returns if r > 0) / len(close_returns))

    hit_rate_5d_15 = None
    if eligible_hits:
        hit_rate_5d_15 = float(len(hits) / len(eligible_hits))

    return DailyScorecard(
        trade_date=trade_date,
        next_date=next_date,
        pick_count=len(outcomes),
        ok_count=len(ok),
        missing_count=len(outcomes) - len(ok),
        win_rate_next_close=win_rate,
        mean_next_close_return=_mean(close_returns),
        mean_next_open_return=_mean(open_returns),
        mean_next_open_to_close_return=_mean(intraday_returns),
        hit_rate_5d_15=hit_rate_5d_15,
    )


def _segment_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    close_returns = [float(row["next_close_return"]) for row in rows if row.get("next_close_return") is not None]
    open_returns = [float(row["next_open_return"]) for row in rows if row.get("next_open_return") is not None]
    max_high = [
        float(row["max_high_t1_t5_from_open"]) for row in rows if row.get("max_high_t1_t5_from_open") is not None
    ]

    negative_gap_rate = None
    if open_returns:
        negative_gap_rate = float(sum(1.0 for r in open_returns if r < 0) / len(open_returns))

    return {
        "count": len(rows),
        "win_rate_next_close": float(sum(1.0 for r in close_returns if r > 0) / len(close_returns)) if close_returns else None,
        "mean_next_open_return": _mean(open_returns),
        "mean_next_close_return": _mean(close_returns),
        "negative_gap_rate": negative_gap_rate,
        "hit_rate_5d_15": float(sum(1.0 for r in max_high if r >= 0.15) / len(max_high)) if max_high else None,
    }


def _pct_chg_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value <= 5.0:
        return "pct<=5"
    if value <= 10.0:
        return "5<pct<=10"
    if value <= 20.0:
        return "10<pct<=20"
    return "pct>20"


def analyze_btst_monthly_scorecard(
    *,
    month: str,
    reports_dir: str | Path = "data/reports",
    top_n: int = 5,
) -> dict[str, Any]:
    root = Path(reports_dir).expanduser().resolve()
    report_paths = _iter_month_reports(reports_dir=root, month=month)

    daily_rows: list[dict[str, Any]] = []
    ticker_rows: list[dict[str, Any]] = []

    for report_path in report_paths:
        report = _load_json(report_path)
        trade_date = str(report.get("trade_date") or "").strip()
        next_date = str(report.get("next_date") or "").strip() or None
        picks = _extract_high_confidence(report, top_n=top_n)

        tickers = [str(entry.get("ticker") or "").strip() for entry in picks if str(entry.get("ticker") or "").strip()]
        realized = generate_realized_prices(signal_date=trade_date, tickers=tickers) if tickers else {}

        outcomes: list[dict[str, Any]] = []
        for entry in picks:
            ticker = str(entry.get("ticker") or "").strip()
            if not ticker:
                continue
            realized_row = dict(realized.get(ticker) or {})
            realized_row["ticker"] = ticker
            realized_row["name"] = entry.get("name")
            realized_row["score"] = entry.get("score")
            realized_row["pct_chg"] = entry.get("pct_chg")
            realized_row["close_strength"] = entry.get("close_strength")
            realized_row["catalyst_freshness"] = entry.get("catalyst_freshness")
            realized_row["trade_date"] = trade_date
            realized_row["next_date"] = next_date
            outcomes.append(realized_row)
            ticker_rows.append(realized_row)

        daily = _daily_metrics(outcomes)
        daily_rows.append(daily.__dict__)

    ok_all = [row for row in ticker_rows if row.get("data_status") == "ok"]
    close_all = [float(row["next_close_return"]) for row in ok_all if row.get("next_close_return") is not None]
    open_all = [float(row["next_open_return"]) for row in ok_all if row.get("next_open_return") is not None]
    intraday_all = [
        float(row["next_open_to_close_return"]) for row in ok_all if row.get("next_open_to_close_return") is not None
    ]
    max_high_all = [
        float(row["max_high_t1_t5_from_open"]) for row in ok_all if row.get("max_high_t1_t5_from_open") is not None
    ]

    gap_neg = [row for row in ok_all if _as_float(row.get("next_open_return")) is not None and float(row["next_open_return"]) < 0]
    gap_nonneg = [
        row for row in ok_all if _as_float(row.get("next_open_return")) is not None and float(row["next_open_return"]) >= 0
    ]

    pct_buckets: dict[str, list[dict[str, Any]]] = {}
    for row in ok_all:
        pct = _as_float(row.get("pct_chg"))
        label = _pct_chg_bucket(pct)
        pct_buckets.setdefault(label, []).append(row)

    overall = {
        "month": str(month),
        "source": "btst_full_report.high_confidence",
        "top_n": int(top_n),
        "day_count": len(daily_rows),
        "pick_count": len(ticker_rows),
        "ok_count": len(ok_all),
        "missing_count": len(ticker_rows) - len(ok_all),
        "win_rate_next_close": float(sum(1.0 for r in close_all if r > 0) / len(close_all)) if close_all else None,
        "mean_next_close_return": _mean(close_all),
        "mean_next_open_return": _mean(open_all),
        "mean_next_open_to_close_return": _mean(intraday_all),
        "hit_rate_5d_15": float(sum(1.0 for r in max_high_all if r >= 0.15) / len(max_high_all)) if max_high_all else None,
        "next_close_return_quantiles": _quantiles(close_all),
        "next_open_return_quantiles": _quantiles(open_all),
        "max_high_t1_t5_from_open_quantiles": _quantiles(max_high_all),
        "gap_segments": {
            "negative": _segment_summary(gap_neg),
            "non_negative": _segment_summary(gap_nonneg),
        },
        "pct_chg_buckets": {label: _segment_summary(rows) for label, rows in pct_buckets.items()},
    }

    return {
        "month": str(month),
        "reports_dir": str(root),
        "overall": overall,
        "daily": daily_rows,
        "tickers": ticker_rows,
    }


def render_btst_monthly_scorecard_markdown(analysis: dict[str, Any]) -> str:
    overall = dict(analysis.get("overall") or {})
    lines: list[str] = []
    month = str(analysis.get("month") or "")

    def pct(value: Any) -> str:
        if value is None:
            return "n/a"
        return f"{float(value) * 100:.1f}%"

    def ret(value: Any) -> str:
        if value is None:
            return "n/a"
        return f"{float(value) * 100:+.2f}%"

    lines.append(f"# BTST Monthly Scorecard {month}")
    lines.append("")
    lines.append("## Overall")
    lines.append(f"- source: {overall.get('source')}, top_n={overall.get('top_n')}")
    lines.append(f"- day_count: {overall.get('day_count')}, pick_count: {overall.get('pick_count')}, ok_count: {overall.get('ok_count')}, missing_count: {overall.get('missing_count')}")
    lines.append(f"- win_rate(next_close>0): {pct(overall.get('win_rate_next_close'))}")
    lines.append(f"- mean next_open_return (gap): {ret(overall.get('mean_next_open_return'))}")
    lines.append(f"- mean next_close_return: {ret(overall.get('mean_next_close_return'))}")
    lines.append(f"- hit_rate 5D +15% (max_high_t1_t5_from_open>=0.15): {pct(overall.get('hit_rate_5d_15'))}")

    gap_segments = dict(overall.get("gap_segments") or {})
    neg = dict(gap_segments.get("negative") or {})
    nonneg = dict(gap_segments.get("non_negative") or {})
    if gap_segments:
        lines.append(
            f"- gap<0: n={neg.get('count')}, win_rate={pct(neg.get('win_rate_next_close'))}, mean_close={ret(neg.get('mean_next_close_return'))}, hit_5d_15={pct(neg.get('hit_rate_5d_15'))}"
        )
        lines.append(
            f"- gap>=0: n={nonneg.get('count')}, win_rate={pct(nonneg.get('win_rate_next_close'))}, mean_close={ret(nonneg.get('mean_next_close_return'))}, hit_5d_15={pct(nonneg.get('hit_rate_5d_15'))}"
        )

    pct_buckets = dict(overall.get("pct_chg_buckets") or {})
    if pct_buckets:
        lines.append("")
        lines.append("## Buckets (pct_chg on signal day)")
        lines.append("| bucket | n | mean_gap | win_rate_close | mean_close | hit_5d_15 |")
        lines.append("|---:|---:|---:|---:|---:|---:|")
        for label, bucket in sorted(pct_buckets.items()):
            bucket = dict(bucket or {})
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(label),
                        str(bucket.get("count") or 0),
                        ret(bucket.get("mean_next_open_return")),
                        pct(bucket.get("win_rate_next_close")),
                        ret(bucket.get("mean_next_close_return")),
                        pct(bucket.get("hit_rate_5d_15")),
                    ]
                )
                + " |"
            )

    lines.append("")

    lines.append("## Daily breakdown")
    lines.append("| trade_date | picks | ok | win_rate_close | mean_gap | mean_close | hit_5d_15 |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|")
    for row in analysis.get("daily") or []:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("trade_date") or ""),
                    str(row.get("pick_count") or 0),
                    str(row.get("ok_count") or 0),
                    pct(row.get("win_rate_next_close")),
                    ret(row.get("mean_next_open_return")),
                    ret(row.get("mean_next_close_return")),
                    pct(row.get("hit_rate_5d_15")),
                ]
            )
            + " |"
        )
    lines.append("")

    lines.append("## Notes")
    lines.append("- next_*_return are returns vs T close (signal day close), matching decision-review ledger semantics.")
    lines.append("- 5D objective uses max high in T+1..T+5 vs entry (T+1 open): max_high_t1_t5_from_open.")
    return "\n".join(lines) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate BTST monthly realized scorecard from btst_full_report JSONs.")
    parser.add_argument("--month", required=True, help="YYYYMM, e.g. 202605")
    parser.add_argument("--top-n", type=int, default=5, help="Top-N high_confidence tickers per day")
    parser.add_argument("--reports-dir", default="data/reports")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    analysis = analyze_btst_monthly_scorecard(month=args.month, reports_dir=args.reports_dir, top_n=int(args.top_n))

    if args.output_json:
        _write_json(args.output_json, analysis)
    if args.output_md:
        _write_text(args.output_md, render_btst_monthly_scorecard_markdown(analysis))

    print(json.dumps(analysis.get("overall") or {}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
