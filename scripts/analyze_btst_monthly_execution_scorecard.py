from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.analyze_btst_monthly_scorecard import (
    _as_float,
    _compact_date,
    _extract_regime_gate_level_from_daily_events,
    _gap_overlay_counterfactual,
    _mean,
    _quantiles,
    _segment_summary,
    _suggest_gap_overlay_cutoff,
)
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


def _iter_plan_dirs(*, reports_dir: Path) -> list[Path]:
    return [path for path in sorted(reports_dir.glob("paper_trading_*_plan")) if path.is_dir()]


def _extract_selected_tickers(brief: dict[str, Any]) -> list[str]:
    tickers: list[str] = []

    primary = brief.get("primary_entry")
    if isinstance(primary, dict):
        ticker = str(primary.get("ticker") or "").strip()
        if ticker:
            tickers.append(ticker)

    for entry in list(brief.get("selected_entries") or []):
        if not isinstance(entry, dict):
            continue
        ticker = str(entry.get("ticker") or "").strip()
        if ticker:
            tickers.append(ticker)

    # stable unique
    seen: set[str] = set()
    out: list[str] = []
    for ticker in tickers:
        if ticker in seen:
            continue
        seen.add(ticker)
        out.append(ticker)
    return out


def _resolve_regime_gate_level(*, plan_dir: Path, trade_date: str) -> str | None:
    daily_events_path = plan_dir / "daily_events.jsonl"
    if not daily_events_path.is_file():
        return None
    level = _extract_regime_gate_level_from_daily_events(daily_events_path, trade_date=trade_date)
    return level


@dataclass
class DailyExecutionScorecard:
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


def _daily_metrics(outcomes: list[dict[str, Any]], *, trade_date: str, next_date: str | None) -> DailyExecutionScorecard:
    ok = [row for row in outcomes if row.get("data_status") == "ok"]
    close_returns = [float(row["next_close_return"]) for row in ok if row.get("next_close_return") is not None]
    open_returns = [float(row["next_open_return"]) for row in ok if row.get("next_open_return") is not None]
    intraday_returns = [float(row["next_open_to_close_return"]) for row in ok if row.get("next_open_to_close_return") is not None]

    eligible_hits = [1.0 for row in ok if row.get("max_high_t1_t5_from_open") is not None]
    hits = [1.0 for row in ok if row.get("max_high_t1_t5_from_open") is not None and float(row["max_high_t1_t5_from_open"]) >= 0.15]

    win_rate = None
    if close_returns:
        win_rate = float(sum(1.0 for r in close_returns if r > 0) / len(close_returns))

    hit_rate_5d_15 = None
    if eligible_hits:
        hit_rate_5d_15 = float(len(hits) / len(eligible_hits))

    return DailyExecutionScorecard(
        trade_date=str(trade_date),
        next_date=str(next_date or "").strip() or None,
        pick_count=len(outcomes),
        ok_count=len(ok),
        missing_count=len(outcomes) - len(ok),
        win_rate_next_close=win_rate,
        mean_next_close_return=_mean(close_returns),
        mean_next_open_return=_mean(open_returns),
        mean_next_open_to_close_return=_mean(intraday_returns),
        hit_rate_5d_15=hit_rate_5d_15,
    )


def analyze_btst_monthly_execution_scorecard(
    *,
    month: str,
    reports_dir: str | Path = "data/reports",
    gap_cutoffs: list[float] | None = None,
) -> dict[str, Any]:
    root = Path(reports_dir).expanduser().resolve()

    selected_runs: dict[str, dict[str, Any]] = {}

    for plan_dir in _iter_plan_dirs(reports_dir=root):
        brief_path = plan_dir / "btst_next_day_trade_brief_latest.json"
        if not brief_path.is_file():
            continue

        try:
            brief = _load_json(brief_path)
        except Exception:
            continue

        trade_date = _compact_date(str(brief.get("trade_date") or "").strip())
        if not trade_date or not trade_date.startswith(str(month).strip()):
            continue

        next_date = _compact_date(str(brief.get("next_trade_date") or "").strip()) or None
        tickers = _extract_selected_tickers(brief)

        mtime = float(brief_path.stat().st_mtime)
        prev = selected_runs.get(trade_date)
        if prev is None or float(prev.get("mtime") or 0.0) < mtime:
            selected_runs[trade_date] = {
                "trade_date": trade_date,
                "next_date": next_date,
                "tickers": tickers,
                "plan_dir": str(plan_dir),
                "brief_path": str(brief_path),
                "mtime": mtime,
            }

    ticker_rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []

    # stable by trade_date
    for trade_date in sorted(selected_runs.keys()):
        run = dict(selected_runs[trade_date] or {})
        next_date = run.get("next_date")
        tickers = list(run.get("tickers") or [])
        plan_dir = Path(str(run.get("plan_dir") or "")).expanduser().resolve()

        regime_gate_level = _resolve_regime_gate_level(plan_dir=plan_dir, trade_date=trade_date) or "unknown"

        realized = generate_realized_prices(signal_date=trade_date, tickers=tickers) if tickers else {}
        outcomes: list[dict[str, Any]] = []

        for ticker in tickers:
            realized_row = dict(realized.get(ticker) or {})
            realized_row["ticker"] = ticker
            realized_row["trade_date"] = trade_date
            realized_row["next_date"] = next_date
            realized_row["regime_gate_level"] = regime_gate_level
            realized_row["plan_dir"] = str(plan_dir)
            outcomes.append(realized_row)
            ticker_rows.append(realized_row)

        daily_rows.append(_daily_metrics(outcomes, trade_date=trade_date, next_date=next_date).__dict__)

    ok_all = [row for row in ticker_rows if row.get("data_status") == "ok"]
    close_all = [float(row["next_close_return"]) for row in ok_all if row.get("next_close_return") is not None]
    open_all = [float(row["next_open_return"]) for row in ok_all if row.get("next_open_return") is not None]
    intraday_all = [float(row["next_open_to_close_return"]) for row in ok_all if row.get("next_open_to_close_return") is not None]
    max_high_all = [float(row["max_high_t1_t5_from_open"]) for row in ok_all if row.get("max_high_t1_t5_from_open") is not None]

    gap_neg = [row for row in ok_all if _as_float(row.get("next_open_return")) is not None and float(row["next_open_return"]) < 0]
    gap_nonneg = [row for row in ok_all if _as_float(row.get("next_open_return")) is not None and float(row["next_open_return"]) >= 0]

    resolved_gap_cutoffs = gap_cutoffs
    if resolved_gap_cutoffs is None:
        resolved_gap_cutoffs = [-0.01, -0.005, -0.003, 0.0]

    resolved_gap_cutoffs = sorted({0.0 if c == 0 else float(-abs(float(c))) for c in resolved_gap_cutoffs})

    gap_overlay_counterfactual = _gap_overlay_counterfactual(ok_all, resolved_gap_cutoffs)

    # profit factor for next_close_return
    pos = sum(r for r in close_all if r > 0)
    neg = sum(r for r in close_all if r < 0)
    profit_factor = None
    if close_all and neg != 0:
        profit_factor = float(pos / abs(neg))

    overall = {
        "month": str(month),
        "source": "paper_trading.trade_brief.formal_selected",
        "day_count": len(daily_rows),
        "days_with_picks": int(sum(1 for row in daily_rows if int(row.get("pick_count") or 0) > 0)),
        "pick_count": len(ticker_rows),
        "ok_count": len(ok_all),
        "missing_count": len(ticker_rows) - len(ok_all),
        "win_rate_next_close": float(sum(1.0 for r in close_all if r > 0) / len(close_all)) if close_all else None,
        "mean_next_close_return": _mean(close_all),
        "mean_next_open_return": _mean(open_all),
        "mean_next_open_to_close_return": _mean(intraday_all),
        "profit_factor_next_close": profit_factor,
        "hit_rate_5d_15": float(sum(1.0 for r in max_high_all if r >= 0.15) / len(max_high_all)) if max_high_all else None,
        "next_close_return_quantiles": _quantiles(close_all),
        "next_open_return_quantiles": _quantiles(open_all),
        "max_high_t1_t5_from_open_quantiles": _quantiles(max_high_all),
        "gap_segments": {
            "negative": _segment_summary(gap_neg),
            "non_negative": _segment_summary(gap_nonneg),
        },
        "gap_overlay_cutoffs": list(resolved_gap_cutoffs),
        "gap_overlay_counterfactual": gap_overlay_counterfactual,
        "gap_overlay_suggestion": _suggest_gap_overlay_cutoff(gap_overlay_counterfactual),
    }

    return {
        "month": str(month),
        "reports_dir": str(root),
        "overall": overall,
        "daily": daily_rows,
        "tickers": ticker_rows,
        "selected_runs": [selected_runs[key] for key in sorted(selected_runs.keys())],
    }


def render_btst_monthly_execution_scorecard_markdown(analysis: dict[str, Any]) -> str:
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

    lines.append(f"# BTST Monthly Execution Scorecard {month}")
    lines.append("")
    lines.append("## Overall")
    lines.append(f"- source: {overall.get('source')}")
    lines.append(f"- day_count: {overall.get('day_count')}, days_with_picks: {overall.get('days_with_picks')}, pick_count: {overall.get('pick_count')}, ok_count: {overall.get('ok_count')}, missing_count: {overall.get('missing_count')}")
    lines.append(f"- win_rate(next_close>0): {pct(overall.get('win_rate_next_close'))}")
    lines.append(f"- mean next_open_return (gap): {ret(overall.get('mean_next_open_return'))}")
    lines.append(f"- mean next_close_return: {ret(overall.get('mean_next_close_return'))}")
    lines.append(f"- profit_factor(next_close): {overall.get('profit_factor_next_close') if overall.get('profit_factor_next_close') is not None else 'n/a'}")
    lines.append(f"- hit_rate 5D +15% (max_high_t1_t5_from_open>=0.15): {pct(overall.get('hit_rate_5d_15'))}")

    gap_segments = dict(overall.get("gap_segments") or {})
    neg = dict(gap_segments.get("negative") or {})
    nonneg = dict(gap_segments.get("non_negative") or {})
    if gap_segments:
        lines.append(f"- gap<0: n={neg.get('count')}, win_rate={pct(neg.get('win_rate_next_close'))}, mean_close={ret(neg.get('mean_next_close_return'))}, hit_5d_15={pct(neg.get('hit_rate_5d_15'))}")
        lines.append(f"- gap>=0: n={nonneg.get('count')}, win_rate={pct(nonneg.get('win_rate_next_close'))}, mean_close={ret(nonneg.get('mean_next_close_return'))}, hit_5d_15={pct(nonneg.get('hit_rate_5d_15'))}")

    overlays = dict(overall.get("gap_overlay_counterfactual") or {})
    if overlays:
        lines.append("")
        lines.append("## Gap overlay counterfactual (keep if gap >= cutoff)")
        lines.append("| cutoff | kept_n | kept_rate | mean_gap | win_rate_close | mean_close | hit_5d_15 |")
        lines.append("|---:|---:|---:|---:|---:|---:|---:|")
        overlay_items: list[tuple[str, dict[str, Any]]] = []
        for label, payload in overlays.items():
            overlay_items.append((str(label), dict(payload or {})))
        overlay_items.sort(key=lambda item: float(item[1].get("cutoff", 0.0)))
        for label, payload in overlay_items:
            kept = dict(payload.get("kept") or {})
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(label),
                        str(kept.get("count") or 0),
                        pct(payload.get("kept_rate")),
                        ret(kept.get("mean_next_open_return")),
                        pct(kept.get("win_rate_next_close")),
                        ret(kept.get("mean_next_close_return")),
                        pct(kept.get("hit_rate_5d_15")),
                    ]
                )
                + " |"
            )

        suggestion = dict(overall.get("gap_overlay_suggestion") or {})
        picked = dict(suggestion.get("picked") or {})
        if picked:
            lines.append("")
            lines.append(f"- suggestion: {picked.get('label')} (win_rate={pct(picked.get('win_rate_next_close'))}, kept_rate={pct(picked.get('kept_rate'))}, n={picked.get('kept_count')})")

    lines.append("")
    lines.append("## Daily breakdown")
    lines.append("| trade_date | picks | ok | win_rate_close | mean_gap | mean_close | hit_5d_15 |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|")

    for row in list(analysis.get("daily") or []):
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
    lines.append("- This scorecard evaluates execution formal-selected entries from btst_next_day_trade_brief_latest.json.")
    lines.append("- next_*_return are vs signal-day close (T close), matching decision-review ledger semantics.")

    return "\n".join(lines) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze BTST monthly execution scorecard from paper-trading trade briefs")
    parser.add_argument("--month", required=True, help="YYYYMM, e.g. 202605")
    parser.add_argument("--reports-dir", default="data/reports")
    parser.add_argument("--gap-cutoffs", default=None)
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output-md", default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    gap_cutoffs = None
    if args.gap_cutoffs:
        # reuse parse semantics from existing scorecard CLI via pandas-friendly parsing
        tokens = str(args.gap_cutoffs).replace(";", ",").split(",")
        parsed: list[float] = []
        for token in tokens:
            raw = token.strip()
            if not raw:
                continue
            try:
                if raw.endswith("%"):
                    value = float(raw[:-1].strip()) / 100.0
                else:
                    value = float(raw)
                    if abs(value) > 0.2:
                        value = value / 100.0
            except (TypeError, ValueError):
                continue
            parsed.append(0.0 if value == 0 else float(-abs(value)))
        gap_cutoffs = sorted({float(c) for c in parsed}) if parsed else None

    analysis = analyze_btst_monthly_execution_scorecard(month=args.month, reports_dir=args.reports_dir, gap_cutoffs=gap_cutoffs)
    markdown = render_btst_monthly_execution_scorecard_markdown(analysis)

    if args.output_json:
        _write_json(args.output_json, analysis)
    if args.output_md:
        _write_text(args.output_md, markdown)

    if not args.output_md:
        print(markdown)


if __name__ == "__main__":
    main()
