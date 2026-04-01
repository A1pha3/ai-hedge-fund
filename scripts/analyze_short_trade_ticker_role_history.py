from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scripts.btst_report_utils import discover_nested_report_dirs as discover_report_dirs


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_snapshot_paths(report_dir: Path) -> list[Path]:
    selection_root = report_dir / "selection_artifacts"
    if not selection_root.exists():
        return []
    return sorted(day_dir / "selection_snapshot.json" for day_dir in selection_root.iterdir() if day_dir.is_dir() and (day_dir / "selection_snapshot.json").exists())


def _iter_dicts(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_dicts(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_dicts(value)


def _classify_record(record: dict[str, Any]) -> tuple[int, str, dict[str, Any]]:
    if "short_trade" in record:
        short_trade = dict(record.get("short_trade") or {})
        metrics_payload = dict(short_trade.get("metrics_payload") or {})
        return (
            3,
            f"{record.get('candidate_source') or 'short_trade_unknown'}_{short_trade.get('decision') or 'unknown'}",
            {
                "ticker": record.get("ticker"),
                "trade_date": record.get("trade_date"),
                "candidate_source": record.get("candidate_source"),
                "target_decision": short_trade.get("decision"),
                "score_target": short_trade.get("score_target"),
                "rank_hint": short_trade.get("rank_hint"),
                "gate_status": short_trade.get("gate_status"),
                "candidate_score": metrics_payload.get("candidate_score"),
                "breakout_freshness": metrics_payload.get("breakout_freshness"),
                "trend_acceleration": metrics_payload.get("trend_acceleration"),
                "volume_expansion_quality": metrics_payload.get("volume_expansion_quality"),
                "catalyst_freshness": metrics_payload.get("catalyst_freshness"),
                "close_strength": metrics_payload.get("close_strength"),
            },
        )
    if "score_final" in record and "decision" in record and "ticker" in record:
        return (
            2,
            f"watchlist_{record.get('decision') or 'unknown'}",
            {
                "ticker": record.get("ticker"),
                "decision": record.get("decision"),
                "score_b": record.get("score_b"),
                "score_c": record.get("score_c"),
                "score_final": record.get("score_final"),
            },
        )
    if "score_b" in record and "reason" in record and "rank" in record and "ticker" in record:
        return (
            1,
            f"layer_b_pool_{record.get('reason') or 'unknown'}",
            {
                "ticker": record.get("ticker"),
                "decision": record.get("decision"),
                "score_b": record.get("score_b"),
                "reason": record.get("reason"),
                "rank": record.get("rank"),
            },
        )
    return (0, "unknown", {})


def _extract_best_record(snapshot: dict[str, Any], ticker: str) -> dict[str, Any] | None:
    best_priority = -1
    best_role = ""
    best_payload: dict[str, Any] | None = None
    for record in _iter_dicts(snapshot):
        if str(record.get("ticker") or "") != ticker:
            continue
        priority, role, payload = _classify_record(record)
        if priority > best_priority:
            best_priority = priority
            best_role = role
            best_payload = {"role": role, **payload}
    return best_payload


def render_short_trade_ticker_role_history_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Short Trade Ticker Role History")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- report_dirs: {analysis['report_dirs']}")
    lines.append(f"- tickers: {analysis['tickers']}")
    lines.append("")
    for ticker_summary in analysis["ticker_summaries"]:
        lines.append(f"## {ticker_summary['ticker']}")
        lines.append(f"- observation_count: {ticker_summary['observation_count']}")
        lines.append(f"- role_counts: {ticker_summary['role_counts']}")
        lines.append(f"- first_short_trade_report_dir: {ticker_summary['first_short_trade_report_dir']}")
        lines.append(f"- recurring_short_trade_trade_date_count: {ticker_summary['recurring_short_trade_trade_date_count']}")
        lines.append(f"- recommendation: {ticker_summary['recommendation']}")
        lines.append("")
        lines.append("### Observations")
        for row in ticker_summary["observations"]:
            lines.append(
                f"- {row['report_label']} {row['trade_date']} role={row['role']}, candidate_source={row.get('candidate_source')}, target_decision={row.get('target_decision')}, score_target={row.get('score_target')}, reason={row.get('reason')}, rank={row.get('rank')}"
            )
        if not ticker_summary["observations"]:
            lines.append("- none")
        lines.append("")
    return "\n".join(lines) + "\n"


def analyze_short_trade_ticker_role_history(report_dirs: list[str | Path], *, tickers: list[str]) -> dict[str, Any]:
    resolved_report_dirs = [Path(path).expanduser().resolve() for path in report_dirs]
    ticker_summaries: list[dict[str, Any]] = []

    for ticker in [str(value).strip() for value in tickers if str(value).strip()]:
        observations: list[dict[str, Any]] = []
        role_counts: Counter[str] = Counter()
        first_short_trade_report_dir: str | None = None
        recurring_short_trade_trade_date_count = 0

        for report_dir in resolved_report_dirs:
            snapshot_paths = _iter_snapshot_paths(report_dir)
            for snapshot_path in snapshot_paths:
                snapshot = _load_json(snapshot_path)
                record = _extract_best_record(snapshot, ticker)
                if record is None:
                    continue
                trade_date = str(snapshot.get("trade_date") or snapshot_path.parent.name)
                row = {
                    "report_dir": str(report_dir),
                    "report_label": report_dir.name,
                    "trade_date": trade_date,
                    **record,
                }
                observations.append(row)
                role = str(record.get("role") or "unknown")
                role_counts[role] += 1
                if role.startswith("short_trade_") or role.startswith("short_trade_boundary"):
                    recurring_short_trade_trade_date_count += 1
                    if first_short_trade_report_dir is None:
                        first_short_trade_report_dir = report_dir.name

        observations.sort(key=lambda row: (row["report_label"], row["trade_date"]))
        if recurring_short_trade_trade_date_count >= 2 and first_short_trade_report_dir and len({row['report_label'] for row in observations if str(row.get('role') or '').startswith('short_trade_') or str(row.get('role') or '').startswith('short_trade_boundary')}) == 1:
            recommendation = (
                f"{ticker} 已在当前窗口形成 recurring short-trade pattern，但 short-trade 角色仍只出现在 {first_short_trade_report_dir}，"
                "暂时应视为窗口内成立的局部 baseline，而不是历史稳定规则。"
            )
        elif recurring_short_trade_trade_date_count >= 2:
            recommendation = f"{ticker} 已在多个报告中重复进入 short-trade 角色，可继续推进更正式的 profile validation。"
        elif observations:
            recommendation = f"{ticker} 目前更多是窗口级观察样本，尚未形成可重复的 short-trade 角色。"
        else:
            recommendation = f"{ticker} 在给定报告范围内没有可用观察记录。"

        ticker_summaries.append(
            {
                "ticker": ticker,
                "observation_count": len(observations),
                "role_counts": dict(role_counts.most_common()),
                "first_short_trade_report_dir": first_short_trade_report_dir,
                "recurring_short_trade_trade_date_count": recurring_short_trade_trade_date_count,
                "observations": observations,
                "recommendation": recommendation,
            }
        )

    return {
        "report_dirs": [str(path) for path in resolved_report_dirs],
        "tickers": [str(value).strip() for value in tickers if str(value).strip()],
        "ticker_summaries": ticker_summaries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Review how specific tickers change roles across report windows.")
    parser.add_argument("--report-dirs", default="", help="Comma-separated report directories")
    parser.add_argument("--report-root-dirs", default="", help="Comma-separated root directories to recursively discover report directories")
    parser.add_argument("--report-name-contains", default="", help="Optional substring filter applied when discovering report directories")
    parser.add_argument("--tickers", required=True, help="Comma-separated tickers")
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

    analysis = analyze_short_trade_ticker_role_history(
        report_dirs,
        tickers=[token.strip() for token in str(args.tickers).split(",") if token.strip()],
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_short_trade_ticker_role_history_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()