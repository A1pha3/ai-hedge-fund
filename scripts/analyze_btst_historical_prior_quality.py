"""Analyze BTST historical prior quality across a selection artifact window.

Produces:
  - data/reports/p3_btst_historical_prior_quality_audit.json
  - data/reports/p3_btst_historical_prior_quality_audit.md

Usage:
  uv run python scripts/analyze_btst_historical_prior_quality.py [REPORT_DIR]

If REPORT_DIR is omitted, the default paper trading report directory is used.
Reads selection_artifacts/*/selection_snapshot.json files and classifies each
entry's historical_prior using P3 hard rules. Produces a before/after
comparison of selected entry sample quality.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from src.targets.prior_quality import PriorQualityLabel, classify_prior_quality


_DEFAULT_REPORT_DIR = Path("data/paper_trading_window_sample")
_OUTPUT_DIR = Path("data/reports")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_selection_snapshot_paths(input_path: Path) -> list[Path]:
    resolved = input_path.resolve()
    if resolved.is_file():
        return [resolved]
    artifacts_root = resolved / "selection_artifacts" if (resolved / "selection_artifacts").is_dir() else resolved
    return sorted(artifacts_root.glob("*/selection_snapshot.json"))


def _extract_prior(entry: dict[str, Any]) -> dict[str, Any] | None:
    replay_context = dict(entry.get("replay_context") or {})
    prior = dict(replay_context.get("historical_prior") or {})
    return prior if prior else None


def _classify_entry_prior(prior: dict[str, Any]) -> tuple[PriorQualityLabel, str]:
    evaluable_count = int(prior.get("evaluable_count") or 0)
    next_high_hit = float(prior.get("next_high_hit_rate_at_threshold") or 0.0)
    next_close_pos = float(prior.get("next_close_positive_rate") or 0.0)
    result = classify_prior_quality(
        evaluable_count=evaluable_count,
        next_high_hit_rate_at_threshold=next_high_hit,
        next_close_positive_rate=next_close_pos,
    )
    return result.label, result.reason


def analyze_btst_historical_prior_quality(input_path: Path) -> dict[str, Any]:
    """Analyze prior quality for all selection artifacts under input_path.

    Returns a dict with:
      - snapshot_count: number of snapshots analyzed
      - prior_quality_distribution: {label: count}
      - selected_sample_quality_before: {total_selected, by_quality}
      - selected_sample_quality_after: {total_selected, by_quality}
      - downgrade_reasons: {reason_code: count}
      - report_type: "p3_btst_historical_prior_quality_audit"
    """
    snapshot_paths = _iter_selection_snapshot_paths(input_path)

    overall_quality_counter: Counter[str] = Counter()
    downgrade_reasons: Counter[str] = Counter()

    before_total_selected = 0
    before_by_quality: Counter[str] = Counter()
    after_total_selected = 0
    after_by_quality: Counter[str] = Counter()

    for snapshot_path in snapshot_paths:
        try:
            snapshot = _load_json(snapshot_path)
        except Exception:
            continue

        entries = list(snapshot.get("target_context") or [])
        for entry in entries:
            prior = _extract_prior(entry)
            if not prior:
                continue

            short_trade = dict(entry.get("short_trade") or {})
            decision = str(short_trade.get("decision") or "")

            label, reason = _classify_entry_prior(prior)
            overall_quality_counter[label.value] += 1

            if reason:
                for code in reason.split(","):
                    code = code.strip()
                    if code:
                        downgrade_reasons[code] += 1

            if decision == "selected":
                before_total_selected += 1
                before_by_quality[label.value] += 1
                if label == PriorQualityLabel.EXECUTION_READY:
                    after_total_selected += 1
                    after_by_quality[label.value] += 1

    return {
        "report_type": "p3_btst_historical_prior_quality_audit",
        "generated_on": str(date.today()),
        "snapshot_count": len(snapshot_paths),
        "prior_quality_distribution": dict(overall_quality_counter),
        "selected_sample_quality_before": {
            "description": "All formally-selected entries regardless of prior quality",
            "total_selected": before_total_selected,
            "by_quality": dict(before_by_quality),
        },
        "selected_sample_quality_after": {
            "description": "Selected entries that would survive P3 hard gate (execution_ready only)",
            "total_selected": after_total_selected,
            "by_quality": dict(after_by_quality),
        },
        "downgrade_reasons": dict(downgrade_reasons),
    }


def _render_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = [
        "# P3 BTST Historical Prior Quality Audit",
        "",
        f"**Generated on:** {analysis.get('generated_on', 'N/A')}",
        f"**Snapshots analyzed:** {analysis.get('snapshot_count', 0)}",
        "",
        "## Prior Quality Distribution (All Entries With Prior Data)",
        "",
    ]
    for label, count in sorted(analysis.get("prior_quality_distribution", {}).items()):
        lines.append(f"- `{label}`: {count}")
    lines += [
        "",
        "## Selected Entry Sample Quality — Before P3 Gate",
        "",
    ]
    before = analysis.get("selected_sample_quality_before", {})
    lines.append(f"**Total selected entries:** {before.get('total_selected', 0)}")
    lines.append("")
    for label, count in sorted(before.get("by_quality", {}).items()):
        lines.append(f"- `{label}`: {count}")
    lines += [
        "",
        "## Selected Entry Sample Quality — After P3 Gate (execution_ready only)",
        "",
    ]
    after = analysis.get("selected_sample_quality_after", {})
    lines.append(f"**Total selected entries (post-gate):** {after.get('total_selected', 0)}")
    lines.append("")
    for label, count in sorted(after.get("by_quality", {}).items()):
        lines.append(f"- `{label}`: {count}")
    lines += [
        "",
        "## Downgrade Reason Codes",
        "",
    ]
    reasons = analysis.get("downgrade_reasons", {})
    if reasons:
        for code, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{code}`: {count}")
    else:
        lines.append("_No downgrade reasons recorded._")
    lines += [
        "",
        "---",
        "",
        "**Flag:** `BTST_0422_P3_PRIOR_QUALITY_MODE=enforce` activates hard gate enforcement.",
        "Default (`off`) preserves all existing behaviour.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_dir", nargs="?", default=str(_DEFAULT_REPORT_DIR), help="Directory containing selection_artifacts/ sub-tree")
    parser.add_argument("--output-dir", default=str(_OUTPUT_DIR), help="Directory to write reports")
    args = parser.parse_args(argv)

    input_path = Path(args.report_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    analysis = analyze_btst_historical_prior_quality(input_path)

    json_path = output_dir / "p3_btst_historical_prior_quality_audit.json"
    json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md_path = output_dir / "p3_btst_historical_prior_quality_audit.md"
    md_path.write_text(_render_markdown(analysis), encoding="utf-8")

    print(f"P3 audit written to:\n  {json_path}\n  {md_path}")


if __name__ == "__main__":
    main()
