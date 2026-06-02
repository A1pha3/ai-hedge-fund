from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class PromotionPick:
    trade_date: str  # YYYY-MM-DD
    ticker: str
    source: str  # baseline_selected | near_miss_promoted
    score_target: float | None
    committee_gate: str | None
    execution_gate: str | None
    prior_evidence_count: int | None
    effective_close_pos_rate: float | None


def _iter_plan_dirs(*, reports_dir: Path) -> list[Path]:
    return [path for path in sorted(reports_dir.glob("paper_trading_*_plan")) if path.is_dir()]


def _select_latest_trade_brief_paths(*, month: str, reports_dir: Path) -> dict[str, Path]:
    selected: dict[str, dict[str, Any]] = {}

    for plan_dir in _iter_plan_dirs(reports_dir=reports_dir):
        brief_path = plan_dir / "btst_next_day_trade_brief_latest.json"
        if not brief_path.is_file():
            continue

        try:
            brief = _load_json(brief_path)
        except Exception:
            continue

        trade_date = str(brief.get("trade_date") or "").strip()
        if not trade_date.startswith(f"{str(month).strip()[:4]}-"):
            # quick filter; month check below
            pass

        compact = trade_date.replace("-", "")
        if not compact.startswith(str(month).strip()):
            continue

        mtime = float(brief_path.stat().st_mtime)
        prev = selected.get(compact)
        if prev is None or float(prev.get("mtime") or 0.0) < mtime:
            selected[compact] = {"trade_date": trade_date, "path": brief_path, "mtime": mtime}

    return {payload["trade_date"]: payload["path"] for payload in selected.values()}


def _choose_promotion_candidate(
    near_miss_entries: list[dict[str, Any]],
    *,
    require_committee_gate: str = "pass",
    min_prior_evidence: int = 20,
    min_effective_close_pos_rate: float = 0.65,
) -> PromotionPick | None:
    candidates: list[PromotionPick] = []

    for entry in list(near_miss_entries or []):
        if not isinstance(entry, dict):
            continue
        ticker = str(entry.get("ticker") or "").strip()
        if not ticker:
            continue

        gate = dict(entry.get("gate_status") or {})
        committee_gate = str(gate.get("committee") or "").strip() or None
        execution_gate = str(gate.get("execution") or "").strip() or None
        if require_committee_gate and committee_gate != require_committee_gate:
            continue

        prior = dict(entry.get("historical_prior") or {})
        prior_evidence_count = _as_int(prior.get("prior_evidence_count") or prior.get("same_ticker_sample_count"))
        effective_close_pos_rate = _as_float(prior.get("effective_next_close_positive_rate"))

        if (prior_evidence_count or 0) < int(min_prior_evidence):
            continue
        if effective_close_pos_rate is None or float(effective_close_pos_rate) < float(min_effective_close_pos_rate):
            continue

        candidates.append(
            PromotionPick(
                trade_date="",
                ticker=ticker,
                source="near_miss_promoted",
                score_target=_as_float(entry.get("score_target")),
                committee_gate=committee_gate,
                execution_gate=execution_gate,
                prior_evidence_count=prior_evidence_count,
                effective_close_pos_rate=effective_close_pos_rate,
            )
        )

    if not candidates:
        return None

    # prefer higher effective rate, then more evidence, then higher score_target
    candidates.sort(
        key=lambda r: (
            -(float(r.effective_close_pos_rate or 0.0)),
            -(int(r.prior_evidence_count or 0)),
            -(float(r.score_target or 0.0)),
            r.ticker,
        )
    )
    return candidates[0]


def _summarize_returns(rows: list[dict[str, Any]]) -> dict[str, Any]:
    next_close_returns = [float(r["next_close_return"]) for r in rows if r.get("next_close_return") is not None]
    open_to_close_returns = [float(r["next_open_to_close_return"]) for r in rows if r.get("next_open_to_close_return") is not None]
    max_high_from_open = [float(r["max_high_t1_t5_from_open"]) for r in rows if r.get("max_high_t1_t5_from_open") is not None]

    wins = [v for v in next_close_returns if v > 0]
    losses = [v for v in next_close_returns if v <= 0]

    win_rate = (len(wins) / len(next_close_returns)) if next_close_returns else None
    mean_next_close = (sum(next_close_returns) / len(next_close_returns)) if next_close_returns else None

    gains = sum(v for v in next_close_returns if v > 0)
    loss_abs = abs(sum(v for v in next_close_returns if v < 0))
    profit_factor = (gains / loss_abs) if loss_abs > 0 else (float("inf") if gains > 0 else None)

    hit_5d_15 = (
        sum(1 for v in max_high_from_open if v >= 0.15) / len(max_high_from_open)
        if max_high_from_open
        else None
    )

    return {
        "pick_count": len(rows),
        "win_rate_next_close_gt_0": win_rate,
        "mean_next_close_return": mean_next_close,
        "profit_factor_next_close": profit_factor,
        "hit_rate_5d_15pct_from_open": hit_5d_15,
        "mean_next_open_to_close_return": (sum(open_to_close_returns) / len(open_to_close_returns)) if open_to_close_returns else None,
        "positive_days": len(wins),
        "non_positive_days": len(losses),
    }


def analyze_btst_monthly_zero_pick_promotion_counterfactual(
    *,
    month: str,
    reports_dir: str | Path = "data/reports",
    require_committee_gate: str = "pass",
    min_prior_evidence: int = 20,
    min_effective_close_pos_rate: float = 0.65,
) -> dict[str, Any]:
    root = Path(reports_dir).expanduser().resolve()
    brief_paths = _select_latest_trade_brief_paths(month=month, reports_dir=root)

    baseline_picks: list[PromotionPick] = []
    promoted_picks: list[PromotionPick] = []
    zero_pick_days: list[str] = []

    for trade_date in sorted(brief_paths.keys()):
        brief = _load_json(brief_paths[trade_date])
        selected_entries = list(brief.get("selected_entries") or [])
        near_miss_entries = list(brief.get("near_miss_entries") or [])

        if selected_entries:
            for entry in selected_entries:
                if not isinstance(entry, dict):
                    continue
                ticker = str(entry.get("ticker") or "").strip()
                if not ticker:
                    continue
                gate = dict(entry.get("gate_status") or {})
                prior = dict(entry.get("historical_prior") or {})
                baseline_picks.append(
                    PromotionPick(
                        trade_date=trade_date,
                        ticker=ticker,
                        source="baseline_selected",
                        score_target=_as_float(entry.get("score_target")),
                        committee_gate=str(gate.get("committee") or "").strip() or None,
                        execution_gate=str(gate.get("execution") or "").strip() or None,
                        prior_evidence_count=_as_int(prior.get("prior_evidence_count") or prior.get("same_ticker_sample_count")),
                        effective_close_pos_rate=_as_float(prior.get("effective_next_close_positive_rate")),
                    )
                )
            continue

        zero_pick_days.append(trade_date)
        candidate = _choose_promotion_candidate(
            near_miss_entries,
            require_committee_gate=require_committee_gate,
            min_prior_evidence=min_prior_evidence,
            min_effective_close_pos_rate=min_effective_close_pos_rate,
        )
        if candidate is None:
            continue
        candidate.trade_date = trade_date
        promoted_picks.append(candidate)

    def realized_for(picks: list[PromotionPick]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        by_day: dict[str, list[PromotionPick]] = {}
        for p in picks:
            by_day.setdefault(p.trade_date, []).append(p)

        for trade_date, items in sorted(by_day.items()):
            realized = generate_realized_prices(signal_date=trade_date, tickers=[p.ticker for p in items])
            for p in items:
                realized_row = dict(realized.get(p.ticker) or {})
                rows.append(
                    {
                        "trade_date": trade_date,
                        "ticker": p.ticker,
                        "source": p.source,
                        "score_target": p.score_target,
                        "committee_gate": p.committee_gate,
                        "execution_gate": p.execution_gate,
                        "prior_evidence_count": p.prior_evidence_count,
                        "effective_close_pos_rate": p.effective_close_pos_rate,
                        "data_status": realized_row.get("data_status"),
                        "next_close_return": realized_row.get("next_close_return"),
                        "next_open_to_close_return": realized_row.get("next_open_to_close_return"),
                        "max_high_t1_t5_from_open": realized_row.get("max_high_t1_t5_from_open"),
                    }
                )

        # keep only ok rows for metrics
        return [r for r in rows if r.get("data_status") == "ok"]

    baseline_rows = realized_for(baseline_picks)
    promoted_rows = realized_for(promoted_picks)
    combined_rows = list(baseline_rows) + list(promoted_rows)

    overall = {
        "month": str(month),
        "reports_dir": str(root),
        "require_committee_gate": require_committee_gate,
        "min_prior_evidence": int(min_prior_evidence),
        "min_effective_close_pos_rate": float(min_effective_close_pos_rate),
        "trade_date_count": len(brief_paths),
        "zero_pick_day_count": len(zero_pick_days),
        "promoted_day_count": len({r["trade_date"] for r in promoted_rows}),
        "promotion_ticker_counts": dict(
            sorted(Counter([r["ticker"] for r in promoted_rows]).items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "baseline": _summarize_returns(baseline_rows),
        "promoted_only": _summarize_returns(promoted_rows),
        "combined": _summarize_returns(combined_rows),
    }

    return {
        "month": str(month),
        "overall": overall,
        "zero_pick_days": zero_pick_days,
        "baseline_rows": baseline_rows,
        "promoted_rows": promoted_rows,
        "combined_rows": combined_rows,
    }


def render_btst_monthly_zero_pick_promotion_counterfactual_markdown(analysis: dict[str, Any]) -> str:
    o = dict(analysis.get("overall") or {})
    lines: list[str] = []
    month = str(analysis.get("month") or "")

    def fmt(v: Any) -> str:
        if v is None:
            return "N/A"
        if isinstance(v, float):
            return f"{v:.4f}"
        return str(v)

    lines.append(f"# BTST Zero-pick Promotion Counterfactual {month}")
    lines.append("")
    lines.append("## Setup")
    lines.append(f"- zero_pick_day_count: {o.get('zero_pick_day_count')} / trade_date_count: {o.get('trade_date_count')}")
    lines.append(f"- promotion filter: committee_gate={o.get('require_committee_gate')}, prior_evidence>={o.get('min_prior_evidence')}, effective_close_pos_rate>={o.get('min_effective_close_pos_rate')}")

    lines.append("")
    lines.append("## Metrics")
    for name in ("baseline", "promoted_only", "combined"):
        block = dict(o.get(name) or {})
        lines.append("")
        lines.append(f"### {name}")
        for key in (
            "pick_count",
            "win_rate_next_close_gt_0",
            "mean_next_close_return",
            "profit_factor_next_close",
            "hit_rate_5d_15pct_from_open",
        ):
            lines.append(f"- {key}: {fmt(block.get(key))}")

    tickers = dict(o.get("promotion_ticker_counts") or {})
    if tickers:
        lines.append("")
        lines.append("## Promoted tickers (counts)")
        for t, c in list(tickers.items())[:20]:
            lines.append(f"- {t}: {c}")

    if analysis.get("zero_pick_days"):
        lines.append("")
        lines.append("## Zero-pick days")
        lines.append(", ".join(list(analysis.get("zero_pick_days") or [])[:60]))

    lines.append("")
    lines.append("## Notes")
    lines.append("- This is a counterfactual to quantify whether promoting a subset of near-miss entries could reduce empty days.")
    lines.append("- It does NOT change execution behavior unless you explicitly implement a promotion rule.")

    return "\n".join(lines) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze counterfactual promotion picks for zero-pick days")
    parser.add_argument("--month", required=True, help="YYYYMM, e.g. 202605")
    parser.add_argument("--reports-dir", default="data/reports")
    parser.add_argument("--require-committee-gate", default="pass")
    parser.add_argument("--min-prior-evidence", type=int, default=20)
    parser.add_argument("--min-effective-close-pos-rate", type=float, default=0.65)
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output-md", default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    analysis = analyze_btst_monthly_zero_pick_promotion_counterfactual(
        month=str(args.month).strip(),
        reports_dir=args.reports_dir,
        require_committee_gate=str(args.require_committee_gate).strip(),
        min_prior_evidence=int(args.min_prior_evidence),
        min_effective_close_pos_rate=float(args.min_effective_close_pos_rate),
    )
    markdown = render_btst_monthly_zero_pick_promotion_counterfactual_markdown(analysis)

    if args.output_json:
        _write_json(args.output_json, analysis)
    if args.output_md:
        _write_text(args.output_md, markdown)

    if not args.output_md:
        print(markdown)


if __name__ == "__main__":
    main()
