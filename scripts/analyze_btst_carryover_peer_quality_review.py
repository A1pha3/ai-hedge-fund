from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.btst_analysis_utils import build_surface_summary


REPORTS_DIR = Path("data/reports")
DEFAULT_ANCHOR_PROBE_JSON = REPORTS_DIR / "btst_carryover_anchor_probe_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_carryover_peer_quality_review_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_carryover_peer_quality_review_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("trade_date") or ""), str(row.get("ticker") or ""))
        current = deduped.get(key)
        rank = (
            1 if row.get("t_plus_2_close_return") is not None else 0,
            1 if row.get("next_close_return") is not None else 0,
            float(row.get("score_target") or 0.0),
            str(row.get("report_dir") or ""),
        )
        if current is None:
            deduped[key] = dict(row)
            continue
        current_rank = (
            1 if current.get("t_plus_2_close_return") is not None else 0,
            1 if current.get("next_close_return") is not None else 0,
            float(current.get("score_target") or 0.0),
            str(current.get("report_dir") or ""),
        )
        if rank > current_rank:
            deduped[key] = dict(row)
    return sorted(deduped.values(), key=lambda row: (str(row.get("trade_date") or ""), str(row.get("ticker") or "")))


def _extract_peer_rows(anchor_probe: dict[str, Any]) -> list[dict[str, Any]]:
    target_ticker = str(anchor_probe.get("ticker") or "")
    rows: list[dict[str, Any]] = []
    for probe in list(anchor_probe.get("probes") or []):
        for row in list(probe.get("same_family_source_rows") or []):
            if str(row.get("ticker") or "") == target_ticker:
                continue
            rows.append({**dict(row), "scope": "same_family_source"})
        for row in list(probe.get("same_family_source_score_catalyst_rows") or []):
            if str(row.get("ticker") or "") == target_ticker:
                continue
            rows.append({**dict(row), "scope": "same_family_source_score_catalyst"})
    return _dedupe_rows(rows)


def _summarize_peer_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    peer_rows = [dict(row) for row in rows]
    peer_rows.sort(
        key=lambda row: (
            float(row.get("next_high_return") if row.get("next_high_return") is not None else -999.0),
            float(row.get("next_close_return") if row.get("next_close_return") is not None else -999.0),
            float(row.get("score_target") if row.get("score_target") is not None else -999.0),
            str(row.get("trade_date") or ""),
            str(row.get("ticker") or ""),
        ),
        reverse=True,
    )
    return build_surface_summary(peer_rows, next_high_hit_threshold=0.02)


def _build_peer_entries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("ticker") or ""), []).append(dict(row))

    entries: list[dict[str, Any]] = []
    for ticker, ticker_rows in grouped.items():
        deduped = _dedupe_rows(ticker_rows)
        entries.append(
            {
                "ticker": ticker,
                "occurrence_count": len(deduped),
                "scope_counts": dict(Counter(str(row.get("scope") or "unknown") for row in deduped)),
                "surface_summary": _summarize_peer_rows(deduped),
                "rows": deduped,
            }
        )
    entries.sort(
        key=lambda entry: (
            -int((entry.get("surface_summary") or {}).get("closed_cycle_count") or 0),
            -float(((entry.get("surface_summary") or {}).get("next_close_positive_rate") or 0.0)),
            -float(((entry.get("surface_summary") or {}).get("next_high_hit_rate_at_threshold") or 0.0)),
            -int(entry.get("occurrence_count") or 0),
            str(entry.get("ticker") or ""),
        )
    )
    return entries


def _build_recommendation(peer_entries: list[dict[str, Any]]) -> str:
    if not peer_entries:
        return "当前 anchor probe 还没有任何 target 之外的 peer 行，不能把 002001 当成可复制 lane。"
    promotable_peers = [
        entry
        for entry in peer_entries
        if int((entry.get("surface_summary") or {}).get("closed_cycle_count") or 0) > 0
        and float(((entry.get("surface_summary") or {}).get("next_high_hit_rate_at_threshold") or 0.0)) >= 0.5
        and float(((entry.get("surface_summary") or {}).get("next_close_positive_rate") or 0.0)) >= 0.5
    ]
    if promotable_peers:
        top = promotable_peers[0]
        return f"{top.get('ticker')} 已出现可复核 closed-cycle 质量，下一步应把它纳入极窄 peer promotion review。"
    best = peer_entries[0]
    return (
        f"当前最可见的 peer 是 {best.get('ticker')}，但它还没有形成达标的 closed-cycle 兑现。"
        " 这条 carryover lane 仍未出现第二只可证实强 peer，暂不支持扩容。"
    )


def analyze_btst_carryover_peer_quality_review(anchor_probe_path: str | Path) -> dict[str, Any]:
    anchor_probe = _load_json(anchor_probe_path)
    peer_rows = _extract_peer_rows(anchor_probe)
    peer_entries = _build_peer_entries(peer_rows)
    return {
        "anchor_probe_path": str(Path(anchor_probe_path).expanduser().resolve()),
        "ticker": anchor_probe.get("ticker"),
        "peer_row_count": len(peer_rows),
        "peer_count": len(peer_entries),
        "peer_entries": peer_entries,
        "recommendation": _build_recommendation(peer_entries),
    }


def render_btst_carryover_peer_quality_review_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Carryover Peer Quality Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- ticker: {analysis.get('ticker')}")
    lines.append(f"- peer_row_count: {analysis.get('peer_row_count')}")
    lines.append(f"- peer_count: {analysis.get('peer_count')}")
    lines.append("")
    lines.append("## Peer Entries")
    for entry in list(analysis.get("peer_entries") or []):
        lines.append(
            f"- {entry.get('ticker')}: occurrence_count={entry.get('occurrence_count')}, scope_counts={entry.get('scope_counts')}, "
            f"surface_summary={entry.get('surface_summary')}"
        )
    if not list(analysis.get("peer_entries") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Review closed-cycle quality for carryover peers surfaced by the anchor probe.")
    parser.add_argument("--anchor-probe-json", default=str(DEFAULT_ANCHOR_PROBE_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_carryover_peer_quality_review(args.anchor_probe_json)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_carryover_peer_quality_review_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
