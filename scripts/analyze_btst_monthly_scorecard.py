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


def _iter_daily_events_candidates(*, daily_events_root: Path, trade_date: str) -> list[Path]:
    token = str(trade_date or "").strip()
    if not token:
        return []

    # Prefer the canonical live plan folder (trade_date == signal_date).
    preferred = sorted(
        daily_events_root.glob(f"paper_trading_{token}_{token}_live_*_plan/daily_events.jsonl")
    )
    if preferred:
        return [path for path in preferred if path.is_file()]

    # Fallback: any plan folder for that trade_date.
    fallback = sorted(daily_events_root.glob(f"paper_trading_{token}_*_plan/daily_events.jsonl"))
    return [path for path in fallback if path.is_file()]


def _extract_regime_gate_level_from_daily_events(daily_events_path: Path, *, trade_date: str) -> str | None:
    try:
        lines = daily_events_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    token = str(trade_date or "").strip()
    for line in lines:
        raw = line.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if token and str(payload.get("trade_date") or "").strip() not in ("", token):
            continue
        plan = payload.get("current_plan") or {}
        market_state = plan.get("market_state") or {}
        level = str(market_state.get("regime_gate_level") or "").strip()
        if level:
            return level
    return None


def _resolve_regime_gate_level(*, daily_events_root: Path, trade_date: str) -> str | None:
    candidates = _iter_daily_events_candidates(daily_events_root=daily_events_root, trade_date=trade_date)
    for path in candidates:
        level = _extract_regime_gate_level_from_daily_events(path, trade_date=trade_date)
        if level:
            return level
    return None


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


def _parse_gap_cutoffs(value: str | None) -> list[float]:
    """Parse comma-separated gap cutoffs.

    Cutoffs express a minimum allowed next_open_return (gap) to keep a sample:
      keep if next_open_return >= cutoff

    Accepted formats:
    - "-0.005" (fraction)
    - "-0.5%" (percent)
    - "-0.5" (treated as percent when abs(v) > 0.2)

    Positive inputs are interpreted as magnitudes and converted to negative cutoffs.
    """
    text = str(value or "").strip()
    if not text:
        return []

    cutoffs: list[float] = []
    for token in text.replace(";", ",").split(","):
        raw = token.strip()
        if not raw:
            continue
        try:
            if raw.endswith("%"):
                parsed = float(raw[:-1].strip()) / 100.0
            else:
                parsed = float(raw)
                if abs(parsed) > 0.2:
                    parsed = parsed / 100.0
        except (TypeError, ValueError):
            continue

        if parsed == 0:
            cutoffs.append(0.0)
        else:
            cutoffs.append(-abs(parsed))

    # Stable unique + sorted (more strict → less strict: -1.0%, -0.5%, -0.3%, 0%)
    return sorted({float(c) for c in cutoffs})


def _format_gap_cutoff_label(cutoff: float) -> str:
    pct = cutoff * 100.0
    # keep stable 1-decimal formatting to match CLI expectations
    return f"gap>={pct:.1f}%"


def _gap_overlay_counterfactual(rows: list[dict[str, Any]], cutoffs: list[float]) -> dict[str, Any]:
    overlays: dict[str, Any] = {}
    if not rows:
        return overlays
    for cutoff in cutoffs:
        kept = [
            row
            for row in rows
            if _as_float(row.get("next_open_return")) is not None
            and float(row["next_open_return"]) >= float(cutoff)
        ]
        overlays[_format_gap_cutoff_label(float(cutoff))] = {
            "cutoff": float(cutoff),
            "kept_rate": float(len(kept) / len(rows)) if rows else None,
            "kept": _segment_summary(kept),
            "dropped_count": int(len(rows) - len(kept)),
        }
    return overlays


def _suggest_gap_overlay_cutoff(overlays: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for label, payload in dict(overlays or {}).items():
        row = dict(payload or {})
        kept = dict(row.get("kept") or {})
        win_rate = _as_float(kept.get("win_rate_next_close"))
        kept_rate = _as_float(row.get("kept_rate"))
        count = int(kept.get("count") or 0)
        if win_rate is None or kept_rate is None or count <= 0:
            continue
        candidates.append(
            {
                "label": str(label),
                "cutoff": _as_float(row.get("cutoff")),
                "kept_rate": float(kept_rate),
                "kept_count": int(count),
                "win_rate_next_close": float(win_rate),
            }
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            float(item["win_rate_next_close"]),
            float(item["kept_rate"]),
        ),
        reverse=True,
    )
    best_win = candidates[0]
    best_win_rate = float(best_win["win_rate_next_close"])

    tolerance = 0.02
    near_best = [
        item
        for item in candidates
        if float(item["win_rate_next_close"]) >= best_win_rate - tolerance
    ]
    best_tradeoff = max(near_best, key=lambda item: float(item["kept_rate"]))

    return {
        "picked": best_tradeoff,
        "best_win": best_win,
        "tolerance": tolerance,
        "note": "Heuristic suggestion for review only; do not treat as an execution guarantee.",
    }


def analyze_btst_monthly_scorecard(
    *,
    month: str,
    reports_dir: str | Path = "data/reports",
    top_n: int = 5,
    gap_cutoffs: list[float] | None = None,
    daily_events_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(reports_dir).expanduser().resolve()
    report_paths = _iter_month_reports(reports_dir=root, month=month)

    daily_events_root_path = Path(daily_events_root).expanduser().resolve() if daily_events_root else None
    regime_gate_by_trade_date: dict[str, str] = {}

    daily_rows: list[dict[str, Any]] = []
    ticker_rows: list[dict[str, Any]] = []

    for report_path in report_paths:
        report = _load_json(report_path)
        trade_date = str(report.get("trade_date") or "").strip()
        next_date = str(report.get("next_date") or "").strip() or None
        picks = _extract_high_confidence(report, top_n=top_n)

        regime_gate_level: str | None = None
        if daily_events_root_path is not None and trade_date:
            cached = regime_gate_by_trade_date.get(trade_date)
            if cached is None:
                resolved = _resolve_regime_gate_level(daily_events_root=daily_events_root_path, trade_date=trade_date)
                regime_gate_level = resolved or "unknown"
                regime_gate_by_trade_date[trade_date] = regime_gate_level
            else:
                regime_gate_level = cached

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
            if regime_gate_level is not None:
                realized_row["regime_gate_level"] = regime_gate_level
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

    regime_buckets: dict[str, list[dict[str, Any]]] = {}
    if daily_events_root_path is not None:
        for row in ok_all:
            label = str(row.get("regime_gate_level") or "unknown").strip() or "unknown"
            regime_buckets.setdefault(label, []).append(row)

    regime_day_counts: dict[str, int] = {}
    if daily_events_root_path is not None:
        for level in regime_gate_by_trade_date.values():
            token = str(level or "unknown").strip() or "unknown"
            regime_day_counts[token] = int(regime_day_counts.get(token, 0)) + 1

    resolved_gap_cutoffs = gap_cutoffs
    if resolved_gap_cutoffs is None:
        # Default counterfactual cutoffs (keep if gap >= cutoff)
        resolved_gap_cutoffs = [-0.01, -0.005, -0.003, 0.0]

    # Normalize: treat positives as magnitudes; keep stable uniqueness
    resolved_gap_cutoffs = sorted({0.0 if c == 0 else float(-abs(float(c))) for c in resolved_gap_cutoffs})

    gap_overlay_counterfactual = _gap_overlay_counterfactual(ok_all, resolved_gap_cutoffs)

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
        "gap_overlay_cutoffs": list(resolved_gap_cutoffs),
        "gap_overlay_counterfactual": gap_overlay_counterfactual,
        "gap_overlay_suggestion": _suggest_gap_overlay_cutoff(gap_overlay_counterfactual),
        "pct_chg_buckets": {label: _segment_summary(rows) for label, rows in pct_buckets.items()},
        "regime_gate_day_counts": dict(regime_day_counts),
        "regime_gate_buckets": {label: _segment_summary(rows) for label, rows in sorted(regime_buckets.items())},
        "regime_gate_gap_overlay_counterfactual": {
            label: _gap_overlay_counterfactual(rows, resolved_gap_cutoffs) for label, rows in sorted(regime_buckets.items())
        },
        "regime_gate_gap_overlay_suggestions": {
            label: _suggest_gap_overlay_cutoff(_gap_overlay_counterfactual(rows, resolved_gap_cutoffs))
            for label, rows in sorted(regime_buckets.items())
        },
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

    overlays = dict(overall.get("gap_overlay_counterfactual") or {})
    if overlays:
        lines.append("")
        lines.append("## Gap overlay counterfactual (keep if gap >= cutoff)")
        lines.append("| cutoff | kept_n | kept_rate | mean_gap | win_rate_close | mean_close | hit_5d_15 |")
        lines.append("|---:|---:|---:|---:|---:|---:|---:|")
        # Sort by numeric cutoff when available
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
            lines.append(
                f"- suggestion: {picked.get('label')} (win_rate={pct(picked.get('win_rate_next_close'))}, kept_rate={pct(picked.get('kept_rate'))}, n={picked.get('kept_count')})"
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

    regime_buckets = dict(overall.get("regime_gate_buckets") or {})
    if regime_buckets:
        lines.append("")
        lines.append("## Regime buckets (from daily_events market_state.regime_gate_level)")
        lines.append("| regime | n | negative_gap_rate | win_rate_close | mean_close | hit_5d_15 |")
        lines.append("|---:|---:|---:|---:|---:|---:|")
        for label, bucket in sorted(regime_buckets.items()):
            bucket = dict(bucket or {})
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(label),
                        str(bucket.get("count") or 0),
                        pct(bucket.get("negative_gap_rate")),
                        pct(bucket.get("win_rate_next_close")),
                        ret(bucket.get("mean_next_close_return")),
                        pct(bucket.get("hit_rate_5d_15")),
                    ]
                )
                + " |"
            )
        lines.append("")
        lines.append("Notes: regime buckets are only available when --daily-events-root is provided.")

        regime_suggestions = dict(overall.get("regime_gate_gap_overlay_suggestions") or {})
        if regime_suggestions:
            lines.append("")
            lines.append("## Regime gap overlay suggestions (review only)")
            lines.append("| regime | picked_cutoff | win_rate_close | kept_rate | kept_n |")
            lines.append("|---:|---:|---:|---:|---:|")
            for regime, suggestion in sorted(regime_suggestions.items()):
                suggestion = dict(suggestion or {})
                picked = dict(suggestion.get("picked") or {})
                if not picked:
                    continue
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            str(regime),
                            str(picked.get("label") or "n/a"),
                            pct(picked.get("win_rate_next_close")),
                            pct(picked.get("kept_rate")),
                            str(picked.get("kept_count") or 0),
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
    parser.add_argument(
        "--gap-cutoffs",
        default="-1.0%,-0.5%,-0.3%,0%",
        help="Comma-separated gap cutoffs for counterfactual overlay. Keep sample if next_open_return >= cutoff. Supports fraction (-0.005) or percent (-0.5%%).",
    )
    parser.add_argument(
        "--daily-events-root",
        default="",
        help="Optional: data/reports root containing paper_trading_*_plan/daily_events.jsonl for regime_gate_level bucketing.",
    )
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    analysis = analyze_btst_monthly_scorecard(
        month=args.month,
        reports_dir=args.reports_dir,
        top_n=int(args.top_n),
        gap_cutoffs=_parse_gap_cutoffs(args.gap_cutoffs),
        daily_events_root=str(args.daily_events_root).strip() or None,
    )

    if args.output_json:
        _write_json(args.output_json, analysis)
    if args.output_md:
        _write_text(args.output_md, render_btst_monthly_scorecard_markdown(analysis))

    print(json.dumps(analysis.get("overall") or {}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
