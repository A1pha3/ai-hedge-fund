"""Analyze BTST P4 prior shrinkage effects from selection artifacts.

Produces:
  - data/reports/p4_btst_prior_shrinkage_eval.json
  - data/reports/p4_btst_prior_shrinkage_eval.md

If no real selection artifacts are available, representative synthetic inputs are acceptable.
"""

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


def _extract_prior_from_target(target: dict[str, Any]) -> dict[str, Any] | None:
    short_trade = dict(target.get("short_trade") or {})
    metrics_payload = dict(short_trade.get("metrics_payload") or {})
    explainability_payload = dict(short_trade.get("explainability_payload") or {})
    prior = dict(metrics_payload.get("historical_prior") or explainability_payload.get("historical_prior") or {})
    return prior if prior else None


def _collect_snapshot_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    selection_targets = dict(snapshot.get("selection_targets") or {})
    for ticker, payload in selection_targets.items():
        target = dict(payload or {})
        prior = _extract_prior_from_target(target)
        if not prior:
            continue
        short_trade = dict(target.get("short_trade") or {})
        rows.append(
            {
                "ticker": str(target.get("ticker") or ticker),
                "decision": str(short_trade.get("decision") or ""),
                "evaluable_count": int(prior.get("evaluable_count") or 0),
                "sample_reliability": float(prior.get("sample_reliability") or 0.0),
                "raw_next_high_hit_rate_at_threshold": float(prior.get("raw_next_high_hit_rate_at_threshold") or 0.0),
                "shrunk_high_hit_rate": float(prior.get("shrunk_high_hit_rate") or 0.0),
                "raw_next_close_positive_rate": float(prior.get("raw_next_close_positive_rate") or 0.0),
                "shrunk_close_positive_rate": float(prior.get("shrunk_close_positive_rate") or 0.0),
            }
        )
    return rows


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def analyze_btst_prior_shrinkage_eval(input_path: Path) -> dict[str, Any]:
    snapshot_paths = _iter_selection_snapshot_paths(input_path)
    rows: list[dict[str, Any]] = []
    for snapshot_path in snapshot_paths:
        try:
            rows.extend(_collect_snapshot_rows(_load_json(snapshot_path)))
        except Exception:
            continue

    comparison_samples = sorted(
        rows,
        key=lambda row: (abs(float(row["raw_next_close_positive_rate"]) - float(row["shrunk_close_positive_rate"])) + abs(float(row["raw_next_high_hit_rate_at_threshold"]) - float(row["shrunk_high_hit_rate"]))),
        reverse=True,
    )[:5]
    return {
        "report_type": "p4_btst_prior_shrinkage_eval",
        "generated_on": str(date.today()),
        "snapshot_count": len(snapshot_paths),
        "comparison_summary": {
            "prior_count": len(rows),
            "avg_sample_reliability": round(_mean([float(row["sample_reliability"]) for row in rows]), 6),
            "avg_raw_high_hit_rate": round(_mean([float(row["raw_next_high_hit_rate_at_threshold"]) for row in rows]), 6),
            "avg_shrunk_high_hit_rate": round(_mean([float(row["shrunk_high_hit_rate"]) for row in rows]), 6),
            "avg_raw_close_positive_rate": round(_mean([float(row["raw_next_close_positive_rate"]) for row in rows]), 6),
            "avg_shrunk_close_positive_rate": round(_mean([float(row["shrunk_close_positive_rate"]) for row in rows]), 6),
        },
        "raw_vs_shrunk_comparison_samples": [
            {
                **row,
                "high_hit_delta": round(float(row["raw_next_high_hit_rate_at_threshold"]) - float(row["shrunk_high_hit_rate"]), 6),
                "close_positive_delta": round(float(row["raw_next_close_positive_rate"]) - float(row["shrunk_close_positive_rate"]), 6),
            }
            for row in comparison_samples
        ],
    }


def _render_markdown(analysis: dict[str, Any]) -> str:
    summary = dict(analysis.get("comparison_summary") or {})
    lines = [
        "# P4 BTST Prior Shrinkage Eval",
        "",
        f"**Generated on:** {analysis.get('generated_on', 'N/A')}",
        f"**Snapshots analyzed:** {analysis.get('snapshot_count', 0)}",
        "",
        "## Comparison Summary",
        "",
        f"- `prior_count`: {summary.get('prior_count', 0)}",
        f"- `avg_sample_reliability`: {summary.get('avg_sample_reliability', 0.0)}",
        f"- `avg_raw_high_hit_rate`: {summary.get('avg_raw_high_hit_rate', 0.0)}",
        f"- `avg_shrunk_high_hit_rate`: {summary.get('avg_shrunk_high_hit_rate', 0.0)}",
        f"- `avg_raw_close_positive_rate`: {summary.get('avg_raw_close_positive_rate', 0.0)}",
        f"- `avg_shrunk_close_positive_rate`: {summary.get('avg_shrunk_close_positive_rate', 0.0)}",
        "",
        "## Raw vs Shrunk Comparison Samples",
        "",
        "| ticker | decision | n | reliability | raw high | shrunk high | raw close+ | shrunk close+ |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    samples = list(analysis.get("raw_vs_shrunk_comparison_samples") or [])
    if samples:
        for row in samples:
            lines.append(f"| {row.get('ticker', '')} | {row.get('decision', '')} | {row.get('evaluable_count', 0)} | {float(row.get('sample_reliability', 0.0)):.3f} | {float(row.get('raw_next_high_hit_rate_at_threshold', 0.0)):.3f} | {float(row.get('shrunk_high_hit_rate', 0.0)):.3f} | {float(row.get('raw_next_close_positive_rate', 0.0)):.3f} | {float(row.get('shrunk_close_positive_rate', 0.0)):.3f} |")
    else:
        lines.append("| _none_ |  |  |  |  |  |  |  |")
    lines += [
        "",
        "---",
        "",
        "**Flag:** `BTST_0422_P4_PRIOR_SHRINKAGE_MODE=enforce` switches selected/near_miss prior-sensitive logic to the shrunk prior surface.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_dir", nargs="?", default=str(_DEFAULT_REPORT_DIR), help="Directory containing selection_artifacts/ sub-tree")
    parser.add_argument("--output-dir", default=str(_OUTPUT_DIR), help="Directory to write reports")
    args = parser.parse_args(argv)

    analysis = analyze_btst_prior_shrinkage_eval(Path(args.report_dir))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "p4_btst_prior_shrinkage_eval.json"
    md_path = output_dir / "p4_btst_prior_shrinkage_eval.md"
    json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(analysis), encoding="utf-8")

    print(f"P4 prior shrinkage eval written to:\n  {json_path}\n  {md_path}")


if __name__ == "__main__":
    main()
