from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

REPORTS_DIR = Path("data/reports")
DEFAULT_INPUT_JSON = REPORTS_DIR / "btst_5d_15pct_false_negative_dossier_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_5d_15pct_false_negative_diagnostic_board_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_5d_15pct_false_negative_diagnostic_board_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(mean(values), 4)


def analyze_btst_5d_15pct_false_negative_diagnostic_board(input_json: str | Path) -> dict[str, Any]:
    payload = _load_json(input_json)
    rows = [dict(row) for row in list(payload.get("rows") or [])]

    source_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ticker_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        source_groups[str(row.get("candidate_source") or "unknown")].append(row)
        ticker_groups[str(row.get("ticker") or "unknown")].append(row)

    source_board: list[dict[str, Any]] = []
    for candidate_source, group_rows in source_groups.items():
        repeating_tickers = sorted({str(row.get("ticker") or "") for row in group_rows if sum(1 for peer in group_rows if str(peer.get("ticker") or "") == str(row.get("ticker") or "")) >= 2 and str(row.get("ticker") or "")})
        source_board.append(
            {
                "candidate_source": candidate_source,
                "false_negative_count": len(group_rows),
                "repeating_ticker_count": len(repeating_tickers),
                "repeating_tickers": repeating_tickers,
                "avg_max_future_high_return_2_5d": _round_mean([value for value in (_safe_float(row.get("max_future_high_return_2_5d")) for row in group_rows) if value is not None]),
                "avg_time_to_hit_15pct": _round_mean([value for value in (_safe_float(row.get("time_to_hit_15pct")) for row in group_rows) if value is not None]),
                "avg_score_target": _round_mean([value for value in (_safe_float(row.get("score_target")) for row in group_rows) if value is not None]),
            }
        )
    source_board.sort(
        key=lambda row: (
            int(row.get("false_negative_count") or 0),
            int(row.get("repeating_ticker_count") or 0),
            float(row.get("avg_max_future_high_return_2_5d") or -999.0),
            str(row.get("candidate_source") or ""),
        ),
        reverse=True,
    )

    ticker_board: list[dict[str, Any]] = []
    for ticker, group_rows in ticker_groups.items():
        candidate_sources = sorted({str(row.get("candidate_source") or "unknown") for row in group_rows})
        ticker_board.append(
            {
                "ticker": ticker,
                "false_negative_count": len(group_rows),
                "candidate_sources": candidate_sources,
                "avg_max_future_high_return_2_5d": _round_mean([value for value in (_safe_float(row.get("max_future_high_return_2_5d")) for row in group_rows) if value is not None]),
                "avg_time_to_hit_15pct": _round_mean([value for value in (_safe_float(row.get("time_to_hit_15pct")) for row in group_rows) if value is not None]),
                "avg_score_target": _round_mean([value for value in (_safe_float(row.get("score_target")) for row in group_rows) if value is not None]),
            }
        )
    ticker_board.sort(
        key=lambda row: (
            int(row.get("false_negative_count") or 0),
            float(row.get("avg_max_future_high_return_2_5d") or -999.0),
            str(row.get("ticker") or ""),
        ),
        reverse=True,
    )

    priority_actions: list[dict[str, Any]] = []
    if source_board:
        top_source = source_board[0]
        priority_actions.append(
            {
                "type": "candidate_source",
                "focus": top_source["candidate_source"],
                "reason": f"false negatives most concentrated here ({top_source['false_negative_count']} rows)",
            }
        )
    if ticker_board:
        top_ticker = ticker_board[0]
        priority_actions.append(
            {
                "type": "ticker",
                "focus": top_ticker["ticker"],
                "reason": f"highest repeat miss count ({top_ticker['false_negative_count']} rows)",
            }
        )

    return {
        "input_json": str(Path(input_json).expanduser().resolve()),
        "source_board": source_board,
        "ticker_board": ticker_board,
        "priority_actions": priority_actions,
    }


def render_btst_5d_15pct_false_negative_diagnostic_board_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST 5D / +15% False Negative Diagnostic Board",
        "",
        "## Source Board",
    ]
    for row in list(analysis.get("source_board") or []):
        lines.append(f"- {row.get('candidate_source')}: false_negative_count={row.get('false_negative_count')}, repeating_ticker_count={row.get('repeating_ticker_count')}, repeating_tickers={row.get('repeating_tickers')}, avg_max_future_high_return_2_5d={row.get('avg_max_future_high_return_2_5d')}, avg_time_to_hit_15pct={row.get('avg_time_to_hit_15pct')}, avg_score_target={row.get('avg_score_target')}")
    if not list(analysis.get("source_board") or []):
        lines.append("- none")
    lines.extend(["", "## Ticker Board"])
    for row in list(analysis.get("ticker_board") or []):
        lines.append(f"- {row.get('ticker')}: false_negative_count={row.get('false_negative_count')}, candidate_sources={row.get('candidate_sources')}, avg_max_future_high_return_2_5d={row.get('avg_max_future_high_return_2_5d')}, avg_time_to_hit_15pct={row.get('avg_time_to_hit_15pct')}, avg_score_target={row.get('avg_score_target')}")
    if not list(analysis.get("ticker_board") or []):
        lines.append("- none")
    lines.extend(["", "## Priority Actions"])
    for action in list(analysis.get("priority_actions") or []):
        lines.append(f"- {action.get('type')}: focus={action.get('focus')}, reason={action.get('reason')}")
    if not list(analysis.get("priority_actions") or []):
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a candidate-source and ticker priority board from the 5D/+15% false-negative dossier.")
    parser.add_argument("--input-json", default=str(DEFAULT_INPUT_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_5d_15pct_false_negative_diagnostic_board(args.input_json)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_5d_15pct_false_negative_diagnostic_board_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
