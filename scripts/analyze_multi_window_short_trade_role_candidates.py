from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scripts.analyze_short_trade_ticker_role_history import analyze_short_trade_ticker_role_history
from scripts.btst_report_utils import discover_nested_report_dirs as discover_report_dirs


WINDOW_KEY_PATTERN = re.compile(r"paper_trading_window_(\d{8})_(\d{8})")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_dicts(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_dicts(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_dicts(value)


def _iter_snapshot_paths(report_dir: Path) -> list[Path]:
    selection_root = report_dir / "selection_artifacts"
    if not selection_root.exists():
        return []
    return sorted(day_dir / "selection_snapshot.json" for day_dir in selection_root.iterdir() if day_dir.is_dir() and (day_dir / "selection_snapshot.json").exists())


def _extract_window_key(report_name: str) -> str:
    matched = WINDOW_KEY_PATTERN.search(str(report_name))
    if not matched:
        return str(report_name)
    return f"{matched.group(1)}_{matched.group(2)}"


def discover_short_trade_tickers(report_dirs: list[str | Path]) -> list[str]:
    tickers: set[str] = set()
    for report_dir in [Path(path).expanduser().resolve() for path in report_dirs]:
        for snapshot_path in _iter_snapshot_paths(report_dir):
            snapshot = _load_json(snapshot_path)
            for record in _iter_dicts(snapshot):
                if "ticker" not in record or "short_trade" not in record:
                    continue
                ticker = str(record.get("ticker") or "").strip()
                if ticker:
                    tickers.add(ticker)
    return sorted(tickers)


def render_multi_window_short_trade_role_candidates_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Multi-Window Short Trade Role Candidates")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- report_dirs: {analysis['report_dirs']}")
    lines.append(f"- ticker_count: {analysis['ticker_count']}")
    lines.append(f"- min_short_trade_trade_dates: {analysis['min_short_trade_trade_dates']}")
    lines.append("")
    lines.append("## Candidates")
    for row in analysis["candidates"]:
        lines.append(
            f"- {row['ticker']}: locality={row['transition_locality']}, short_trade_trade_date_count={row['short_trade_trade_date_count']}, distinct_window_count={row['distinct_window_count']}, distinct_report_count={row['distinct_report_count']}, previous_window_role={row['previous_window_role']}, first_short_trade_window_key={row['first_short_trade_window_key']}, role_counts={row['role_counts']}, recommendation={row['recommendation']}"
        )
    if not analysis["candidates"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_multi_window_short_trade_role_candidates(
    report_dirs: list[str | Path],
    *,
    min_short_trade_trade_dates: int = 2,
) -> dict[str, Any]:
    resolved_report_dirs = [Path(path).expanduser().resolve() for path in report_dirs]
    tickers = discover_short_trade_tickers(resolved_report_dirs)
    role_history = analyze_short_trade_ticker_role_history(resolved_report_dirs, tickers=tickers)

    candidates: list[dict[str, Any]] = []
    for summary in list(role_history.get("ticker_summaries") or []):
        observations = list(summary.get("observations") or [])
        short_trade_rows = [
            row
            for row in observations
            if str(row.get("role") or "").startswith("short_trade_") or str(row.get("role") or "").startswith("short_trade_boundary")
        ]
        short_trade_trade_date_count = len(short_trade_rows)
        if short_trade_trade_date_count < int(min_short_trade_trade_dates):
            continue

        window_keys = sorted({_extract_window_key(str(row.get("report_label") or "")) for row in short_trade_rows})
        distinct_report_count = len({str(row.get("report_label") or "") for row in short_trade_rows})
        previous_window_role = None
        first_short_trade_window_key = window_keys[0] if window_keys else None
        if first_short_trade_window_key:
            previous_rows = [
                row
                for row in observations
                if _extract_window_key(str(row.get("report_label") or "")) != first_short_trade_window_key
            ]
            if previous_rows:
                previous_window_role = str(previous_rows[-1].get("role") or "unknown")

        if len(window_keys) >= 2:
            transition_locality = "multi_window_stable"
            recommendation = f"{summary['ticker']} 已在多个逻辑窗口复现 short-trade 角色，应进入 stable recurring profile validation。"
        elif previous_window_role and previous_window_role.startswith("layer_b_pool_"):
            transition_locality = "emergent_local_baseline"
            recommendation = f"{summary['ticker']} 目前仍是从 Layer B pool 向 short-trade 角色跃迁的当前窗口 emergent baseline。"
        else:
            transition_locality = "local_recurring"
            recommendation = f"{summary['ticker']} 已在当前窗口内重复出现，但还没有跨窗口稳定复现证据。"

        candidates.append(
            {
                "ticker": summary["ticker"],
                "short_trade_trade_date_count": short_trade_trade_date_count,
                "distinct_window_count": len(window_keys),
                "distinct_report_count": distinct_report_count,
                "window_keys": window_keys,
                "previous_window_role": previous_window_role,
                "first_short_trade_window_key": first_short_trade_window_key,
                "role_counts": summary.get("role_counts") or {},
                "transition_locality": transition_locality,
                "recommendation": recommendation,
            }
        )

    candidates.sort(
        key=lambda row: (
            0 if row["transition_locality"] == "multi_window_stable" else 1,
            -int(row["distinct_window_count"]),
            -int(row["short_trade_trade_date_count"]),
            row["ticker"],
        )
    )

    stable_count = sum(1 for row in candidates if row["transition_locality"] == "multi_window_stable")
    if stable_count == 0:
        recommendation = "当前自动发现窗口范围内没有 multi-window stable short-trade ticker；默认规则仍不应从局部 recurring baseline 直接上升。"
    else:
        recommendation = f"当前已发现 {stable_count} 个 multi-window stable short-trade ticker，应优先对这些 ticker 做 profile validation。"

    return {
        "report_dirs": [str(path) for path in resolved_report_dirs],
        "ticker_count": len(tickers),
        "min_short_trade_trade_dates": int(min_short_trade_trade_dates),
        "candidate_count": len(candidates),
        "stable_candidate_count": stable_count,
        "candidates": candidates,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan all short-trade tickers across report windows and classify recurring profile locality.")
    parser.add_argument("--report-dirs", default="", help="Comma-separated report directories")
    parser.add_argument("--report-root-dirs", default="", help="Comma-separated root directories to recursively discover report directories")
    parser.add_argument("--report-name-contains", default="", help="Optional substring filter applied when discovering report directories")
    parser.add_argument("--min-short-trade-trade-dates", type=int, default=2)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    report_dirs = [token.strip() for token in str(args.report_dirs).split(",") if token.strip()]
    if args.report_root_dirs:
        report_dirs.extend(
            str(path)
            for path in discover_report_dirs(
                [token.strip() for token in str(args.report_root_dirs).split(",") if token.strip()],
                report_name_contains=str(args.report_name_contains or ""),
            )
        )
    if not report_dirs:
        raise SystemExit("No report directories were provided or discovered.")

    analysis = analyze_multi_window_short_trade_role_candidates(
        report_dirs,
        min_short_trade_trade_dates=int(args.min_short_trade_trade_dates),
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_multi_window_short_trade_role_candidates_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()