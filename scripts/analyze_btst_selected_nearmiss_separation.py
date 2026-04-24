"""Analyze BTST selected-vs-near_miss separation from selection artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

_DEFAULT_REPORT_DIR = Path("data/p4_prior_shrinkage_eval_sample")
_OUTPUT_DIR = Path("data/reports")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_selection_snapshot_paths(input_path: Path) -> list[Path]:
    resolved = input_path.resolve()
    if resolved.is_file():
        return [resolved]
    artifacts_root = resolved / "selection_artifacts" if (resolved / "selection_artifacts").is_dir() else resolved
    return sorted(artifacts_root.glob("*/selection_snapshot.json"))


def _recommendation(*, selected_count: int, near_miss_count: int, gate_counts: dict[str, int]) -> str:
    weak_gate_count = int(gate_counts.get("halt") or 0) + int(gate_counts.get("shadow_only") or 0)
    if selected_count > near_miss_count and weak_gate_count == 0:
        return "go"
    if selected_count > 0:
        return "shadow_only"
    return "rollback"


def analyze_btst_selected_nearmiss_separation(input_path: Path) -> dict[str, Any]:
    snapshot_paths = _iter_selection_snapshot_paths(input_path)
    decision_counts: dict[str, int] = {}
    gate_counts: dict[str, int] = {}
    decision_gate_counts: dict[str, dict[str, int]] = {}

    for snapshot_path in snapshot_paths:
        try:
            snapshot = _load_json(snapshot_path)
        except Exception:
            continue
        for ticker, payload in dict(snapshot.get("selection_targets") or {}).items():
            target = dict(payload or {})
            short_trade = dict(target.get("short_trade") or {})
            decision = str(short_trade.get("decision") or "rejected")
            if decision not in {"selected", "near_miss"}:
                continue
            gate = str(target.get("btst_regime_gate") or short_trade.get("btst_regime_gate") or "unknown")
            decision_counts[decision] = int(decision_counts.get(decision) or 0) + 1
            gate_counts[gate] = int(gate_counts.get(gate) or 0) + 1
            gate_counter = decision_gate_counts.setdefault(decision, {})
            gate_counter[gate] = int(gate_counter.get(gate) or 0) + 1

    selected_count = int(decision_counts.get("selected") or 0)
    near_miss_count = int(decision_counts.get("near_miss") or 0)
    return {
        "report_type": "p4_btst_selected_nearmiss_separation",
        "generated_on": str(date.today()),
        "snapshot_count": len(snapshot_paths),
        "decision_counts": decision_counts,
        "gate_counts": gate_counts,
        "decision_gate_counts": decision_gate_counts,
        "selected_minus_near_miss": selected_count - near_miss_count,
        "recommendation": _recommendation(
            selected_count=selected_count,
            near_miss_count=near_miss_count,
            gate_counts=gate_counts,
        ),
    }


def _render_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# Selected vs Near Miss Separation",
        "",
        f"**Generated on:** {analysis.get('generated_on', 'N/A')}",
        f"**Snapshots analyzed:** {analysis.get('snapshot_count', 0)}",
        f"**Recommendation:** {analysis.get('recommendation', 'unknown')}",
        "",
        "## Decision Counts",
        "",
        f"- selected: {dict(analysis.get('decision_counts') or {}).get('selected', 0)}",
        f"- near_miss: {dict(analysis.get('decision_counts') or {}).get('near_miss', 0)}",
        "",
        "## Gate Counts",
        "",
        f"- gate_counts: {analysis.get('gate_counts', {})}",
        "",
        "## Decision by Gate",
        "",
    ]
    for decision, gate_counts in dict(analysis.get("decision_gate_counts") or {}).items():
        lines.append(f"- {decision}: {gate_counts}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_dir", nargs="?", default=str(_DEFAULT_REPORT_DIR), help="Directory containing selection_artifacts/ sub-tree")
    parser.add_argument("--output-dir", default=str(_OUTPUT_DIR), help="Directory to write reports")
    args = parser.parse_args(argv)

    analysis = analyze_btst_selected_nearmiss_separation(Path(args.report_dir))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "p4_btst_selected_nearmiss_separation.json"
    md_path = output_dir / "p4_btst_selected_nearmiss_separation.md"
    json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(analysis), encoding="utf-8")

    print(f"P4 selected-vs-near_miss separation written to:\n  {json_path}\n  {md_path}")


if __name__ == "__main__":
    main()
