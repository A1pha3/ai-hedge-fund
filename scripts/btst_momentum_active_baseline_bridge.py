#!/usr/bin/env python3
"""Create a governed baseline bridge from BTST-v2 report.

Reads a governed active-baseline snapshot and a BTST-v2 report and emits
an interoperable bridge artifact (JSON + Markdown).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


REQUIRED_METRICS = [
    "next_close_positive_rate",
    "next_close_payoff_ratio",
    "next_close_expectancy",
    "window_coverage",
    "window_count",
    "max_drawdown",
]

REQUIRED_GUARDRAILS = ["no_manifest_publication", "no_btst_skill_promotion"]


def _load_json(path: str) -> Any:
    p = Path(path)
    if not p.exists():
        raise ValueError(f"input JSON not found: {path}")
    try:
        return json.loads(p.read_text())
    except Exception as e:
        raise ValueError(f"failed to read JSON {path}: {e}")


def _iter_report_rows(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = source.get("rows")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]

    report_rows: List[Dict[str, Any]] = []
    for report_key, payload in source.items():
        if not isinstance(payload, dict):
            continue
        if "objective" not in payload or "best_params" not in payload or "best_metrics" not in payload:
            continue
        row = dict(payload)
        row.setdefault("report_key", report_key)
        report_rows.append(row)
    return report_rows


def build_bridge(*, active_baseline_json: str, source_json: str) -> Dict[str, Any]:
    active = _load_json(active_baseline_json)
    source = _load_json(source_json)

    # validate governance fields
    guardrails = active.get("guardrails")
    if guardrails != REQUIRED_GUARDRAILS:
        raise ValueError(f"active baseline guardrails must be {REQUIRED_GUARDRAILS}")
    if active.get("release_posture") != "hold":
        raise ValueError("active baseline release_posture must be 'hold'")
    if active.get("fail_closed") is not True:
        raise ValueError("active baseline fail_closed must be True")

    profile_overrides = active.get("profile_overrides")
    if not isinstance(profile_overrides, dict):
        raise ValueError("active baseline profile_overrides must be a JSON object")

    # find matching rows
    rows: List[Dict[str, Any]] = []
    for r in _iter_report_rows(source):
        if r.get("objective") != "btst":
            continue
        if r.get("best_params") == profile_overrides:
            rows.append(r)

    if len(rows) != 1:
        raise ValueError(f"expected exactly one matching BTST row, found {len(rows)}")

    match = rows[0]

    best_metrics = match.get("best_metrics") or {}
    for m in REQUIRED_METRICS:
        if m not in best_metrics:
            raise ValueError(f"required metric missing from matched row: {m}")

    bridge = {
        "baseline_name": active.get("profile_name"),
        "report_key": match.get("report_key"),
        "baseline_metrics": {k: best_metrics[k] for k in REQUIRED_METRICS},
        "source_path": active.get("source_path"),
        "validated_by": active.get("validated_by"),
        "release_posture": "hold",
        "guardrails": REQUIRED_GUARDRAILS,
        "blockers": [],
        "fail_closed": True,
    }
    return bridge


def render_markdown(bridge: Dict[str, Any]) -> str:
    lines = ["# BTST Momentum Active Baseline Bridge", ""]
    lines.append(f"- baseline_name: `{bridge.get('baseline_name')}`")
    lines.append(f"- report_key: `{bridge.get('report_key')}`")
    lines.append(f"- source_path: `{bridge.get('source_path')}`")
    lines.append(f"- validated_by: `{bridge.get('validated_by')}`")
    lines.append(f"- release_posture: `{bridge.get('release_posture')}`")
    lines.append(f"- guardrails: `{bridge.get('guardrails')}`")
    lines.append(f"- fail_closed: `{bridge.get('fail_closed')}`")
    lines.append("")
    lines.append("## Baseline metrics")
    lines.append("```json")
    lines.append(json.dumps(bridge.get("baseline_metrics", {}), indent=2, ensure_ascii=False))
    lines.append("```")
    return "\n".join(lines)


def main(
    argv: list[str] | None = None,
    *,
    active_baseline_json: str = "data/reports/btst_momentum_active_baseline_snapshot.json",
    source_json: str = "data/reports/btst_v2_objective_alignment_primary.json",
    output_json: str = "data/reports/btst_momentum_active_baseline_bridge.json",
    output_md: str = "data/reports/btst_momentum_active_baseline_bridge.md",
) -> int:
    if argv is not None:
        parser = argparse.ArgumentParser(description="Create a governed baseline bridge from a BTST-v2 report.")
        parser.add_argument("--active-baseline-json", default=active_baseline_json)
        parser.add_argument("--source-json", default=source_json)
        parser.add_argument("--output-json", default=output_json)
        parser.add_argument("--output-md", default=output_md)
        args = parser.parse_args(argv)
        active_baseline_json = args.active_baseline_json
        source_json = args.source_json
        output_json = args.output_json
        output_md = args.output_md

    bridge = build_bridge(active_baseline_json=active_baseline_json, source_json=source_json)

    outp = Path(output_json)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(bridge, indent=2, ensure_ascii=False))

    md = render_markdown(bridge)
    outmd = Path(output_md)
    outmd.parent.mkdir(parents=True, exist_ok=True)
    outmd.write_text(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(argv=sys.argv[1:]))
