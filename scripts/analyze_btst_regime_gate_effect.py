from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from src.screening.market_state_helpers import classify_btst_regime_gate_from_market_state


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_selection_snapshot_paths(input_path: Path) -> list[Path]:
    resolved_input = input_path.resolve()
    if resolved_input.is_file():
        return [resolved_input]
    artifacts_root = resolved_input / "selection_artifacts" if (resolved_input / "selection_artifacts").is_dir() else resolved_input
    return sorted(artifacts_root.glob("*/selection_snapshot.json"))


def _normalize_trade_date(value: Any) -> str:
    return str(value or "").replace("-", "").strip()


def _find_report_root(input_path: Path) -> Path | None:
    for candidate in [input_path.resolve(), *input_path.resolve().parents]:
        if (candidate / "daily_events.jsonl").is_file():
            return candidate
    return None


def _load_market_state_index(report_root: Path | None) -> dict[str, dict[str, Any]]:
    if report_root is None:
        return {}
    daily_events_path = report_root / "daily_events.jsonl"
    if not daily_events_path.is_file():
        return {}
    market_states: dict[str, dict[str, Any]] = {}
    with daily_events_path.open(encoding="utf-8") as handle:
        for line in handle:
            event = json.loads(line)
            trade_date = _normalize_trade_date(event.get("trade_date"))
            current_plan = dict(event.get("current_plan") or {})
            market_state = dict(current_plan.get("market_state") or {})
            if trade_date and market_state:
                market_states[trade_date] = market_state
    return market_states


def _resolve_gate_payload(snapshot: dict[str, Any], market_state_index: dict[str, dict[str, Any]] | None = None) -> dict[str, Any] | None:
    explicit_payload = dict(snapshot.get("btst_regime_gate") or {})
    if explicit_payload.get("gate"):
        return explicit_payload
    derived_payload = classify_btst_regime_gate_from_market_state(snapshot.get("market_state"))
    if derived_payload is not None:
        return derived_payload
    trade_date = _normalize_trade_date(snapshot.get("trade_date"))
    fallback_market_state = dict((market_state_index or {}).get(trade_date) or {})
    if not fallback_market_state:
        return None
    return classify_btst_regime_gate_from_market_state(fallback_market_state)


def analyze_btst_regime_gate_effect(input_path: str | Path) -> dict[str, Any]:
    resolved_input = Path(input_path).resolve()
    snapshot_paths = _iter_selection_snapshot_paths(resolved_input)
    market_state_index = _load_market_state_index(_find_report_root(resolved_input))
    gate_counts: Counter[str] = Counter()
    mode_counts: Counter[str] = Counter()
    by_gate: dict[str, dict[str, Any]] = {}

    for snapshot_path in snapshot_paths:
        snapshot = _load_json(snapshot_path)
        gate_payload = _resolve_gate_payload(snapshot, market_state_index)
        if gate_payload is None:
            continue
        gate_name = str(gate_payload.get("gate") or "unknown")
        gate_counts[gate_name] += 1
        gate_mode = str(gate_payload.get("mode") or "derived")
        mode_counts[gate_mode] += 1
        gate_bucket = by_gate.setdefault(
            gate_name,
            {
                "snapshot_count": 0,
                "buy_order_count": 0,
                "short_trade_selected_count": 0,
                "short_trade_near_miss_count": 0,
                "trade_dates": [],
            },
        )
        target_summary = dict(snapshot.get("target_summary") or {})
        universe_summary = dict(snapshot.get("universe_summary") or {})
        gate_bucket["snapshot_count"] += 1
        gate_bucket["buy_order_count"] += int(universe_summary.get("buy_order_count") or 0)
        gate_bucket["short_trade_selected_count"] += int(target_summary.get("short_trade_selected_count") or 0)
        gate_bucket["short_trade_near_miss_count"] += int(target_summary.get("short_trade_near_miss_count") or 0)
        gate_bucket["trade_dates"].append(str(snapshot.get("trade_date") or snapshot_path.parent.name))

    recommendation = "go"
    if gate_counts.get("halt") or gate_counts.get("shadow_only"):
        recommendation = "shadow_only"
    elif not gate_counts:
        recommendation = "rollback"

    return {
        "generated_on": str(date.today()),
        "input_path": str(resolved_input),
        "snapshot_count": len(snapshot_paths),
        "gate_counts": dict(sorted(gate_counts.items())),
        "mode_counts": dict(sorted(mode_counts.items())),
        "by_gate": by_gate,
        "recommendation": recommendation,
    }


def _render_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# P1 BTST Regime Gate Shadow Eval",
        "",
        f"- input_path: {analysis['input_path']}",
        f"- snapshot_count: {analysis['snapshot_count']}",
        f"- recommendation: {analysis['recommendation']}",
        "",
        "## Gate Counts",
        "",
    ]
    gate_counts = dict(analysis.get("gate_counts") or {})
    if not gate_counts:
        lines.append("- none")
    else:
        for gate_name, count in gate_counts.items():
            lines.append(f"- {gate_name}: {count}")
    lines.extend(["", "## Gate Details", ""])
    for gate_name, payload in dict(analysis.get("by_gate") or {}).items():
        lines.append(f"### {gate_name}")
        lines.append(f"- snapshot_count: {payload.get('snapshot_count', 0)}")
        lines.append(f"- buy_order_count: {payload.get('buy_order_count', 0)}")
        lines.append(f"- short_trade_selected_count: {payload.get('short_trade_selected_count', 0)}")
        lines.append(f"- short_trade_near_miss_count: {payload.get('short_trade_near_miss_count', 0)}")
        lines.append(f"- trade_dates: {', '.join(payload.get('trade_dates', [])) or 'none'}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze BTST regime gate shadow effects from selection snapshots.")
    parser.add_argument("input_path", help="Report directory, selection_artifacts directory, or selection_snapshot.json path.")
    parser.add_argument("--output-json", dest="output_json", default="data/reports/p1_btst_regime_gate_shadow_eval.json")
    parser.add_argument("--output-markdown", dest="output_markdown", default="data/reports/p1_btst_regime_gate_shadow_eval.md")
    args = parser.parse_args()

    analysis = analyze_btst_regime_gate_effect(args.input_path)
    output_json_path = Path(args.output_json)
    output_markdown_path = Path(args.output_markdown)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_markdown_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_markdown_path.write_text(_render_markdown(analysis), encoding="utf-8")


if __name__ == "__main__":
    main()
