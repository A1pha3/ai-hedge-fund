from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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


def analyze_btst_monthly_execution_blockers(
    *,
    month: str,
    reports_dir: str | Path = "data/reports",
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
            blocked_rows.append(
                BlockedRow(
                    trade_date=trade_date,
                    ticker=str(entry.get("ticker") or ticker),
                    decision=str(short_trade.get("decision") or ""),
                    block_flags=flags,
                )
            )

        daily.append(
            {
                "trade_date": trade_date,
                "formal_selected_count": formal_selected_count,
                "execution_blocked_target_count": execution_blocked_count,
                "selection_target_count": len(selection_targets),
                "snapshot_path": snapshot_path,
                "brief_path": str(run.get("brief_path") or ""),
            }
        )

    flags_counter = Counter()
    decision_counter = Counter()
    for r in blocked_rows:
        decision_counter[str(r.decision or "unknown")] += 1
        for f in r.block_flags:
            flags_counter[str(f)] += 1

    overall = {
        "month": str(month),
        "source": "trade_brief.snapshot.selection_targets",
        "day_count": len(selected_runs),
        "blocked_row_count": len(blocked_rows),
        "by_block_flag": dict(sorted(flags_counter.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_decision": dict(sorted(decision_counter.items(), key=lambda kv: (-kv[1], kv[0]))),
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
    lines.append("## Daily")
    lines.append("| trade_date | formal_selected | blocked_targets | selection_targets |")
    lines.append("|---:|---:|---:|---:|")
    for row in list(analysis.get("daily") or []):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("trade_date") or ""),
                    str(row.get("formal_selected_count") or 0),
                    str(row.get("execution_blocked_target_count") or 0),
                    str(row.get("selection_target_count") or 0),
                ]
            )
            + " |"
        )

    lines.append("")
    lines.append("## Notes")
    lines.append("- blocked_targets replicate the same p2/p3/p5/p6 flags used to filter formal execution-ready entries.")

    return "\n".join(lines) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze BTST monthly execution blockers from selection_targets")
    parser.add_argument("--month", required=True, help="YYYYMM")
    parser.add_argument("--reports-dir", default="data/reports")
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output-md", default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    analysis = analyze_btst_monthly_execution_blockers(month=str(args.month).strip(), reports_dir=args.reports_dir)
    md = render_btst_monthly_execution_blockers_markdown(analysis)

    if args.output_json:
        _write_json(args.output_json, analysis)
    if args.output_md:
        _write_text(args.output_md, md)

    if not args.output_md:
        print(md)


if __name__ == "__main__":
    main()
