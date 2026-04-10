from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_ANCHOR_PROBE_JSON = REPORTS_DIR / "btst_carryover_anchor_probe_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_carryover_aligned_peer_harvest_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_carryover_aligned_peer_harvest_latest.md"
SCOPE_PRIORITY = {
    "same_family_source_score_catalyst": 3,
    "same_source_score": 2,
    "same_family_source": 1,
}


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def _extract_peer_rows(anchor_probe: dict[str, Any]) -> list[dict[str, Any]]:
    target_ticker = str(anchor_probe.get("ticker") or "")
    rows: list[dict[str, Any]] = []
    for probe in list(anchor_probe.get("probes") or []):
        for scope_key in ("same_family_source_rows", "same_family_source_score_catalyst_rows", "same_source_score_rows"):
            scope = scope_key.removesuffix("_rows")
            for raw_row in list(probe.get(scope_key) or []):
                row = dict(raw_row or {})
                if str(row.get("ticker") or "") == target_ticker:
                    continue
                rows.append({**row, "scope": scope, "scope_priority": SCOPE_PRIORITY.get(scope, 0)})
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("trade_date") or ""), str(row.get("ticker") or ""))
        current = deduped.get(key)
        rank = (
            int(row.get("scope_priority") or 0),
            1 if row.get("t_plus_2_close_return") is not None else 0,
            1 if row.get("next_close_return") is not None else 0,
            float(row.get("score_target") or 0.0),
            str(row.get("report_dir") or ""),
        )
        if current is None:
            deduped[key] = row
            continue
        current_rank = (
            int(current.get("scope_priority") or 0),
            1 if current.get("t_plus_2_close_return") is not None else 0,
            1 if current.get("next_close_return") is not None else 0,
            float(current.get("score_target") or 0.0),
            str(current.get("report_dir") or ""),
        )
        if rank > current_rank:
            deduped[key] = row
    return sorted(deduped.values(), key=lambda row: (str(row.get("trade_date") or ""), str(row.get("ticker") or "")))


def _classify_harvest_status(rows: list[dict[str, Any]]) -> str:
    closed_cycle_rows = [row for row in rows if row.get("t_plus_2_close_return") is not None]
    next_day_rows = [row for row in rows if row.get("next_close_return") is not None]
    latest_trade_date = max(str(row.get("trade_date") or "") for row in rows) if rows else ""

    if any(
        float(row.get("t_plus_2_close_return") or 0.0) > 0
        and float(row.get("next_close_return") or 0.0) > 0
        and float(row.get("next_high_return") or 0.0) >= 0.02
        for row in closed_cycle_rows
    ):
        return "promotion_review_ready"
    if closed_cycle_rows:
        return "closed_cycle_weak"
    if next_day_rows:
        return "next_day_watch"
    if latest_trade_date:
        return "fresh_open_cycle"
    return "no_data"


def _build_entry_recommendation(status: str, ticker: str) -> str:
    if status == "promotion_review_ready":
        return f"{ticker} 已有 closed-cycle 正兑现，可进入极窄 peer promotion review。"
    if status == "closed_cycle_weak":
        return f"{ticker} 已闭环但兑现偏弱，只能作为反例，不支持 carryover lane 扩容。"
    if status == "next_day_watch":
        return f"{ticker} 已进入 next-day 可观察阶段，优先等待 T+2 闭环再判断是否具备第二个强 peer 资格。"
    if status == "fresh_open_cycle":
        return f"{ticker} 是当前最接近的 aligned open-cycle peer，应优先盯 next-day/T+2 数据。"
    return f"{ticker} 当前没有可用于 peer harvest 的有效价格闭环。"


def _build_harvest_entries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("ticker") or ""), []).append(dict(row))

    entries: list[dict[str, Any]] = []
    for ticker, ticker_rows in grouped.items():
        latest_row = max(
            ticker_rows,
            key=lambda row: (
                str(row.get("trade_date") or ""),
                int(row.get("scope_priority") or 0),
                float(row.get("score_target") or 0.0),
            ),
        )
        status = _classify_harvest_status(ticker_rows)
        entries.append(
            {
                "ticker": ticker,
                "harvest_status": status,
                "occurrence_count": len(ticker_rows),
                "latest_trade_date": latest_row.get("trade_date"),
                "latest_scope": latest_row.get("scope"),
                "latest_score_target": latest_row.get("score_target"),
                "scope_counts": dict(Counter(str(row.get("scope") or "unknown") for row in ticker_rows)),
                "next_day_available_count": sum(1 for row in ticker_rows if row.get("next_close_return") is not None),
                "closed_cycle_count": sum(1 for row in ticker_rows if row.get("t_plus_2_close_return") is not None),
                "best_next_high_return": max((float(row.get("next_high_return") or -999.0) for row in ticker_rows), default=None),
                "best_next_close_return": max((float(row.get("next_close_return") or -999.0) for row in ticker_rows), default=None),
                "recommendation": _build_entry_recommendation(status, ticker),
                "rows": sorted(ticker_rows, key=lambda row: (str(row.get("trade_date") or ""), int(row.get("scope_priority") or 0)), reverse=True),
            }
        )
    status_rank = {
        "promotion_review_ready": 4,
        "next_day_watch": 3,
        "fresh_open_cycle": 2,
        "closed_cycle_weak": 1,
        "no_data": 0,
    }
    entries.sort(
        key=lambda entry: (
            status_rank.get(str(entry.get("harvest_status") or ""), -1),
            int(SCOPE_PRIORITY.get(str(entry.get("latest_scope") or ""), 0)),
            str(entry.get("latest_trade_date") or ""),
            float(entry.get("latest_score_target") or 0.0),
            str(entry.get("ticker") or ""),
        ),
        reverse=True,
    )
    return entries


def _build_recommendation(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "当前没有任何 aligned peer rows，不能继续推进 carryover peer harvest。"
    focus = entries[0]
    if str(focus.get("harvest_status") or "") == "promotion_review_ready":
        return f"{focus.get('ticker')} 已具备 closed-cycle 正兑现，应立刻进入 peer promotion review。"
    return (
        f"当前最值得盯的 aligned peer 是 {focus.get('ticker')}，status={focus.get('harvest_status')}。"
        " 在它进入 T+2 closed-cycle 前，002001 仍然只能被视为单票证据。"
    )


def analyze_btst_carryover_aligned_peer_harvest(anchor_probe_path: str | Path) -> dict[str, Any]:
    anchor_probe = _load_json(anchor_probe_path)
    peer_rows = _extract_peer_rows(anchor_probe)
    harvest_entries = _build_harvest_entries(peer_rows)
    return {
        "anchor_probe_path": str(Path(anchor_probe_path).expanduser().resolve()),
        "ticker": anchor_probe.get("ticker"),
        "peer_row_count": len(peer_rows),
        "peer_count": len(harvest_entries),
        "status_counts": dict(Counter(str(entry.get("harvest_status") or "") for entry in harvest_entries)),
        "focus_ticker": (harvest_entries[0].get("ticker") if harvest_entries else None),
        "focus_status": (harvest_entries[0].get("harvest_status") if harvest_entries else None),
        "harvest_entries": harvest_entries,
        "recommendation": _build_recommendation(harvest_entries),
    }


def render_btst_carryover_aligned_peer_harvest_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Carryover Aligned Peer Harvest")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- ticker: {analysis.get('ticker')}")
    lines.append(f"- peer_row_count: {analysis.get('peer_row_count')}")
    lines.append(f"- peer_count: {analysis.get('peer_count')}")
    lines.append(f"- status_counts: {analysis.get('status_counts')}")
    lines.append(f"- focus_ticker: {analysis.get('focus_ticker')}")
    lines.append(f"- focus_status: {analysis.get('focus_status')}")
    lines.append("")
    lines.append("## Harvest Entries")
    for entry in list(analysis.get("harvest_entries") or []):
        lines.append(
            f"- {entry.get('ticker')}: status={entry.get('harvest_status')}, latest_trade_date={entry.get('latest_trade_date')}, "
            f"latest_scope={entry.get('latest_scope')}, latest_score_target={entry.get('latest_score_target')}, "
            f"next_day_available_count={entry.get('next_day_available_count')}, closed_cycle_count={entry.get('closed_cycle_count')}"
        )
        lines.append(f"  recommendation: {entry.get('recommendation')}")
    if not list(analysis.get("harvest_entries") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank aligned carryover peers by harvest readiness so the next closed-cycle evidence ticket is explicit.")
    parser.add_argument("--anchor-probe-json", default=str(DEFAULT_ANCHOR_PROBE_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_carryover_aligned_peer_harvest(args.anchor_probe_json)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_carryover_aligned_peer_harvest_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
