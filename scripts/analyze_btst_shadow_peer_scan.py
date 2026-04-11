from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

REPORTS_DIR = Path("data/reports")
DEFAULT_SHADOW_EXPANSION_PATH = REPORTS_DIR / "p4_shadow_entry_expansion_board_300383_20260330.json"
DEFAULT_FRONTIER_REPORT_PATH = REPORTS_DIR / "short_trade_boundary_score_failures_frontier_catalyst_floor_zero_refresh_20260401.json"
DEFAULT_SCOREBOARD_REPORT_PATH = REPORTS_DIR / "short_trade_release_priority_scoreboard_20260329.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "p7_shadow_peer_scan_300383_20260401.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "p7_shadow_peer_scan_300383_20260401.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def analyze_btst_shadow_peer_scan(
    shadow_expansion_path: str | Path,
    *,
    frontier_report_path: str | Path,
    scoreboard_report_path: str | Path,
    ticker: str = "300383",
) -> dict[str, Any]:
    normalized_ticker = str(ticker).strip()
    shadow_expansion = _load_json(shadow_expansion_path)
    frontier_report = _load_json(frontier_report_path)
    scoreboard_report = _load_json(scoreboard_report_path)

    threshold_only_tickers = set(dict(shadow_expansion.get("frontier_uniqueness") or {}).get("threshold_only_tickers") or [])
    grouped_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in list(frontier_report.get("minimal_near_miss_rows") or []):
        peer_ticker = str(row.get("ticker") or "")
        if not peer_ticker or peer_ticker == normalized_ticker:
            continue
        grouped_rows[peer_ticker].append(dict(row))

    scoreboard_by_ticker = {str(row.get("ticker") or ""): dict(row) for row in list(scoreboard_report.get("entries") or [])}
    peer_rows: list[dict[str, Any]] = []
    for peer_ticker, rows in grouped_rows.items():
        rows.sort(key=lambda row: (float(row.get("adjustment_cost") or 999.0), str(row.get("trade_date") or "")))
        scoreboard = scoreboard_by_ticker.get(peer_ticker) or {}
        peer_class = "threshold_only" if peer_ticker in threshold_only_tickers else "penalty_coupled"
        peer_rows.append(
            {
                "ticker": peer_ticker,
                "peer_class": peer_class,
                "occurrence_count": len(rows),
                "minimal_adjustment_cost": rows[0].get("adjustment_cost"),
                "representative_case": rows[0],
                "scoreboard_rank": scoreboard.get("priority_rank"),
                "lane_type": scoreboard.get("lane_type"),
                "has_existing_release_outcome": bool(scoreboard),
            }
        )

    peer_rows.sort(
        key=lambda row: (
            0 if row["peer_class"] == "threshold_only" else 1,
            0 if row["has_existing_release_outcome"] else 1,
            float(row.get("minimal_adjustment_cost") or 999.0),
            int(row.get("scoreboard_rank") or 999),
            row["ticker"],
        )
    )
    same_rule_peer_rows = [row for row in peer_rows if row["peer_class"] == "threshold_only"]
    redirect_candidates = [row for row in peer_rows if str(row.get("lane_type") or "") == "recurring_frontier_release"]

    if same_rule_peer_rows:
        peer_scan_verdict = "same_rule_peer_exists"
        recommendation = "已经存在第二只 threshold-only peer，可以继续做受控 shadow peer scan。"
    else:
        peer_scan_verdict = "no_same_rule_peer_redirect_to_recurring"
        recommendation = "当前不存在第二只 threshold-only peer；若继续扩 shadow，只能转向 recurring frontier 的 300113/600821 双轨验证。"

    return {
        "generated_on": shadow_expansion.get("generated_on"),
        "shadow_expansion": str(Path(shadow_expansion_path).expanduser().resolve()),
        "frontier_report": str(Path(frontier_report_path).expanduser().resolve()),
        "scoreboard_report": str(Path(scoreboard_report_path).expanduser().resolve()),
        "ticker": normalized_ticker,
        "peer_scan_verdict": peer_scan_verdict,
        "same_rule_peer_rows": same_rule_peer_rows,
        "priority_peer_rows": peer_rows[:8],
        "redirect_candidates": redirect_candidates,
        "next_actions": [
            f"继续把 {normalized_ticker} 固定为单票 shadow entry，不做同规则复制。",
            "若要继续扩 shadow lane，直接转向 300113 的 close-continuation recurring shadow 验证。",
            "把 600821 维持为 recurring intraday control，用来约束 intraday-only 漂移。",
        ],
        "recommendation": recommendation,
    }


def render_btst_shadow_peer_scan_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Shadow Peer Scan")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- ticker: {analysis['ticker']}")
    lines.append(f"- peer_scan_verdict: {analysis['peer_scan_verdict']}")
    lines.append("")
    lines.append("## Priority Peers")
    for row in analysis["priority_peer_rows"]:
        lines.append(f"- ticker={row['ticker']} peer_class={row['peer_class']} occurrence_count={row['occurrence_count']} minimal_adjustment_cost={row['minimal_adjustment_cost']} scoreboard_rank={row['scoreboard_rank']} lane_type={row['lane_type']}")
    if not analysis["priority_peer_rows"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Next Actions")
    for item in analysis["next_actions"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan whether the BTST shadow entry has any same-rule peers or must redirect to recurring frontier validation.")
    parser.add_argument("--shadow-expansion", default=str(DEFAULT_SHADOW_EXPANSION_PATH))
    parser.add_argument("--frontier-report", default=str(DEFAULT_FRONTIER_REPORT_PATH))
    parser.add_argument("--scoreboard-report", default=str(DEFAULT_SCOREBOARD_REPORT_PATH))
    parser.add_argument("--ticker", default="300383")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_shadow_peer_scan(
        args.shadow_expansion,
        frontier_report_path=args.frontier_report,
        scoreboard_report_path=args.scoreboard_report,
        ticker=args.ticker,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_shadow_peer_scan_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
