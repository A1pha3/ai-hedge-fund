from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.generate_btst_realized_prices import generate_realized_prices


FORMAL_EXECUTION_BLOCK_FLAGS = (
    "p2_execution_blocked",
    "p3_execution_blocked",
    "p5_execution_blocked",
    "p6_execution_blocked",
)


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _write_text(path: str | Path, text: str) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _write_json(path: str | Path, payload: Any) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _compact_date(value: str) -> str:
    token = str(value or "").strip()
    if len(token) == 10 and token[4] == "-" and token[7] == "-":
        return token.replace("-", "")
    return token


def _iter_plan_dirs(*, reports_dir: Path) -> list[Path]:
    return [path for path in sorted(reports_dir.glob("paper_trading_*_plan")) if path.is_dir()]


def _as_bool(value: Any) -> bool:
    return bool(value)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _collect_formal_execution_block_flags(selection_entry: dict[str, Any]) -> list[str]:
    short_trade_entry = dict(selection_entry.get("short_trade") or {})
    flags: list[str] = []
    for flag in FORMAL_EXECUTION_BLOCK_FLAGS:
        if _as_bool(selection_entry.get(flag)) or _as_bool(short_trade_entry.get(flag)):
            flags.append(flag)
    return flags


def _is_formal_execution_blocked_target(selection_entry: dict[str, Any]) -> tuple[bool, list[str]]:
    short_trade_entry = dict(selection_entry.get("short_trade") or {})
    decision = str(short_trade_entry.get("decision") or "").strip()
    if decision == "blocked":
        return True, _collect_formal_execution_block_flags(selection_entry) or ["decision_blocked"]
    if decision not in {"selected", "near_miss"}:
        return False, []
    flags = _collect_formal_execution_block_flags(selection_entry)
    return (bool(flags), flags)


@dataclass
class BlockedRow:
    trade_date: str
    ticker: str
    decision: str
    block_flags: list[str]
    p2_block_reason: str | None = None
    short_trade_blockers: list[str] | None = None

    # Optional realized (counterfactual) returns for diagnosing whether a blocker is likely over/under strict.
    realized_data_status: str | None = None
    realized_next_close_return: float | None = None
    realized_next_open_to_close_return: float | None = None


def analyze_btst_monthly_execution_blockers(
    *,
    month: str,
    reports_dir: str | Path = "data/reports",
    include_realized: bool = False,
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

        mtime = float(brief_path.stat().st_mtime)
        prev = selected_runs.get(trade_date)
        if prev is None or float(prev.get("mtime") or 0.0) < mtime:
            selected_runs[trade_date] = {
                "trade_date": trade_date,
                "plan_dir": str(plan_dir),
                "brief_path": str(brief_path),
                "mtime": mtime,
            }

    blocked_rows: list[BlockedRow] = []
    daily: list[dict[str, Any]] = []

    for trade_date in sorted(selected_runs.keys()):
        run = dict(selected_runs[trade_date] or {})
        brief = _load_json(str(run.get("brief_path") or ""))
        snapshot_path = str(brief.get("snapshot_path") or "").strip()
        snapshot: dict[str, Any] = _load_json(snapshot_path) if snapshot_path else {}

        market_state = dict(snapshot.get("market_state") or {})
        market_regime_gate_level = str(market_state.get("regime_gate_level") or "").strip() or None

        selection_targets = snapshot.get("selection_targets")
        if not isinstance(selection_targets, dict):
            selection_targets = {}

        formal_selected_count = len(list(brief.get("selected_entries") or []))
        execution_blocked_count = 0
        for ticker, entry in selection_targets.items():
            if not isinstance(entry, dict):
                continue
            blocked, flags = _is_formal_execution_blocked_target(entry)
            if not blocked:
                continue
            execution_blocked_count += 1
            short_trade = dict(entry.get("short_trade") or {})
            p2_reason: str | None = None
            if "p2_execution_blocked" in set(flags):
                p2_reason = str(entry.get("p2_execution_block_reason") or "").strip() or None

            decision = str(short_trade.get("decision") or "")
            blockers: list[str] | None = None
            if decision == "blocked":
                blockers = [str(v) for v in list(short_trade.get("blockers") or []) if str(v or "").strip()]
                downgrade = [str(v) for v in list(short_trade.get("downgrade_reasons") or []) if str(v or "").strip()]
                # Keep a compact, de-duplicated list for analysis.
                merged: list[str] = []
                for item in blockers + downgrade:
                    if item not in merged:
                        merged.append(item)
                blockers = merged

            blocked_rows.append(
                BlockedRow(
                    trade_date=trade_date,
                    ticker=str(entry.get("ticker") or ticker),
                    decision=decision,
                    block_flags=flags,
                    p2_block_reason=p2_reason,
                    short_trade_blockers=blockers,
                )
            )

        daily.append(
            {
                "trade_date": trade_date,
                "market_regime_gate_level": market_regime_gate_level,
                "formal_selected_count": formal_selected_count,
                "execution_blocked_target_count": execution_blocked_count,
                "selection_target_count": len(selection_targets),
                "snapshot_path": snapshot_path,
                "brief_path": str(run.get("brief_path") or ""),
            }
        )

    flags_counter = Counter()
    decision_counter = Counter()
    p2_reason_counter = Counter()
    blocked_reason_counter = Counter()
    for r in blocked_rows:
        decision_counter[str(r.decision or "unknown")] += 1
        for f in r.block_flags:
            flags_counter[str(f)] += 1
        if r.p2_block_reason:
            p2_reason_counter[str(r.p2_block_reason)] += 1
        if r.short_trade_blockers:
            for reason in r.short_trade_blockers:
                blocked_reason_counter[str(reason)] += 1

    if include_realized and blocked_rows:
        # Aggregate realized returns for blocked targets.
        # NOTE: This is a *counterfactual diagnostic* only; it does not imply the target should have been traded.
        p2_realized: dict[str, dict[str, Any]] = {}
        blocker_realized: dict[str, dict[str, Any]] = {}

        p2_samples: dict[str, list[tuple[float | None, float | None]]] = {}
        blocker_samples: dict[str, list[tuple[float | None, float | None]]] = {}

        rows_by_day: dict[str, list[BlockedRow]] = {}
        for row in blocked_rows:
            rows_by_day.setdefault(str(row.trade_date), []).append(row)

        for trade_date, rows in sorted(rows_by_day.items()):
            tickers = sorted({str(r.ticker) for r in rows if str(r.ticker).strip()})
            realized = generate_realized_prices(signal_date=trade_date, tickers=tickers) if tickers else {}
            for r in rows:
                rec = dict(realized.get(str(r.ticker)) or {})
                status = str(rec.get("data_status") or "").strip() or None
                r.realized_data_status = status
                r.realized_next_close_return = _as_float(rec.get("next_close_return"))
                r.realized_next_open_to_close_return = _as_float(rec.get("next_open_to_close_return"))

                sample = (r.realized_next_close_return, r.realized_next_open_to_close_return)
                if r.p2_block_reason:
                    p2_samples.setdefault(str(r.p2_block_reason), []).append(sample)
                if r.short_trade_blockers:
                    for reason in r.short_trade_blockers:
                        blocker_samples.setdefault(str(reason), []).append(sample)

        def _summarize(samples: list[tuple[float | None, float | None]]) -> dict[str, Any]:
            close_vals = [v for v, _ in samples if isinstance(v, (int, float))]
            o2c_vals = [v for _, v in samples if isinstance(v, (int, float))]
            out: dict[str, Any] = {"sample_count": len(samples)}
            if close_vals:
                out.update(
                    {
                        "next_close_ok_count": len(close_vals),
                        "next_close_win_rate": round(sum(1 for v in close_vals if v > 0.0) / len(close_vals), 4),
                        "next_close_return_mean": round(sum(close_vals) / len(close_vals), 6),
                    }
                )
            if o2c_vals:
                out.update(
                    {
                        "open_to_close_ok_count": len(o2c_vals),
                        "open_to_close_win_rate": round(sum(1 for v in o2c_vals if v > 0.0) / len(o2c_vals), 4),
                        "open_to_close_return_mean": round(sum(o2c_vals) / len(o2c_vals), 6),
                    }
                )
            return out

        for reason, samples in sorted(p2_samples.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            p2_realized[str(reason)] = _summarize(samples)
        for reason, samples in sorted(blocker_samples.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            blocker_realized[str(reason)] = _summarize(samples)

    overall = {
        "month": str(month),
        "source": "trade_brief.snapshot.selection_targets",
        "day_count": len(selected_runs),
        "blocked_row_count": len(blocked_rows),
        "by_block_flag": dict(sorted(flags_counter.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_decision": dict(sorted(decision_counter.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_p2_block_reason": dict(sorted(p2_reason_counter.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_short_trade_blocker": dict(sorted(blocked_reason_counter.items(), key=lambda kv: (-kv[1], kv[0]))),
    }

    if include_realized and blocked_rows:
        overall["realized"] = {
            "p2_block_reason": p2_realized,
            "short_trade_blocker": blocker_realized,
        }

    return {
        "month": str(month),
        "reports_dir": str(root),
        "overall": overall,
        "daily": daily,
        "blocked_rows": [r.__dict__ for r in blocked_rows],
        "selected_runs": [selected_runs[key] for key in sorted(selected_runs.keys())],
    }


def render_btst_monthly_execution_blockers_markdown(analysis: dict[str, Any]) -> str:
    o = dict(analysis.get("overall") or {})
    lines: list[str] = []
    month = str(analysis.get("month") or "")

    def top_k(d: dict[str, Any], k: int = 12) -> list[tuple[str, Any]]:
        items = list((d or {}).items())
        items.sort(key=lambda kv: (-int(kv[1] or 0), str(kv[0])))
        return items[:k]

    def top_k_stats(d: dict[str, Any], k: int = 12) -> list[tuple[str, Any]]:
        items = list((d or {}).items())
        items.sort(key=lambda kv: (-int(dict(kv[1] or {}).get("sample_count") or 0), str(kv[0])))
        return items[:k]

    lines.append(f"# BTST Monthly Execution Blockers {month}")
    lines.append("")
    lines.append("## Overall")
    lines.append(f"- source: {o.get('source')}")
    lines.append(f"- day_count: {o.get('day_count')}, blocked_row_count: {o.get('blocked_row_count')}")

    by_flag = dict(o.get("by_block_flag") or {})
    if by_flag:
        lines.append("")
        lines.append("## Block flags")
        for name, count in top_k(by_flag):
            lines.append(f"- {name}: {count}")

    by_decision = dict(o.get("by_decision") or {})
    if by_decision:
        lines.append("")
        lines.append("## Blocked short_trade decisions")
        for name, count in top_k(by_decision):
            lines.append(f"- {name}: {count}")

    lines.append("")
    p2_reasons = dict(o.get("by_p2_block_reason") or {})
    if p2_reasons:
        lines.append("")
        lines.append("## P2 block reasons")
        for name, count in top_k(p2_reasons):
            lines.append(f"- {name}: {count}")

    lines.append("")
    lines.append("## Daily")
    lines.append("| trade_date | regime_gate | formal_selected | blocked_targets | selection_targets |")
    lines.append("|---:|:---|---:|---:|---:|")
    for row in list(analysis.get("daily") or []):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("trade_date") or ""),
                    str(row.get("market_regime_gate_level") or ""),
                    str(row.get("formal_selected_count") or 0),
                    str(row.get("execution_blocked_target_count") or 0),
                    str(row.get("selection_target_count") or 0),
                ]
            )
            + " |"
        )

    blocked_reasons = dict(o.get("by_short_trade_blocker") or {})
    if blocked_reasons:
        lines.append("")
        lines.append("## short_trade blocked reasons")
        for name, count in top_k(blocked_reasons):
            lines.append(f"- {name}: {count}")

    realized = dict(o.get("realized") or {})
    if realized:
        lines.append("")
        lines.append("## Realized (blocked targets, counterfactual)")
        lines.append("- next_close_return: (T+1 close / T close - 1)")
        lines.append("- open_to_close_return: (T+1 close / T+1 open - 1)")

        p2_realized = dict(realized.get("p2_block_reason") or {})
        if p2_realized:
            lines.append("")
            lines.append("### By P2 block reason")
            for name, stats in top_k_stats(p2_realized):
                s = dict(stats or {})
                lines.append(
                    "- "
                    + str(name)
                    + ": n="
                    + str(s.get("sample_count") or 0)
                    + ", open_to_close_win_rate="
                    + str(s.get("open_to_close_win_rate") or "n/a")
                    + ", open_to_close_mean="
                    + str(s.get("open_to_close_return_mean") or "n/a")
                )

        blocker_realized = dict(realized.get("short_trade_blocker") or {})
        if blocker_realized:
            lines.append("")
            lines.append("### By short_trade blocker (multi-tag counts)")
            for name, stats in top_k_stats(blocker_realized):
                s = dict(stats or {})
                lines.append(
                    "- "
                    + str(name)
                    + ": n="
                    + str(s.get("sample_count") or 0)
                    + ", open_to_close_win_rate="
                    + str(s.get("open_to_close_win_rate") or "n/a")
                    + ", open_to_close_mean="
                    + str(s.get("open_to_close_return_mean") or "n/a")
                )

    lines.append("")
    lines.append("## Notes")
    lines.append("- blocked_targets replicate the same p2/p3/p5/p6 flags used to filter formal execution-ready entries.")

    return "\n".join(lines) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze BTST monthly execution blockers from selection_targets")
    parser.add_argument("--month", required=True, help="YYYYMM")
    parser.add_argument("--reports-dir", default="data/reports")
    parser.add_argument("--include-realized", action="store_true", help="Also compute realized next-day returns for blocked targets")
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output-md", default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    analysis = analyze_btst_monthly_execution_blockers(
        month=str(args.month).strip(),
        reports_dir=args.reports_dir,
        include_realized=bool(args.include_realized),
    )
    md = render_btst_monthly_execution_blockers_markdown(analysis)

    if args.output_json:
        _write_json(args.output_json, analysis)
    if args.output_md:
        _write_text(args.output_md, md)

    if not args.output_md:
        print(md)


if __name__ == "__main__":
    main()
