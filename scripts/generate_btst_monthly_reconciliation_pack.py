from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_monthly_execution_scorecard import (
    analyze_btst_monthly_execution_scorecard,
    render_btst_monthly_execution_scorecard_markdown,
)
from scripts.analyze_btst_monthly_scorecard import analyze_btst_monthly_scorecard, render_btst_monthly_scorecard_markdown
from scripts.analyze_btst_monthly_execution_health import (
    analyze_btst_monthly_execution_health,
    render_btst_monthly_execution_health_markdown,
)
from scripts.analyze_btst_monthly_near_miss_gate_breakdown import (
    analyze_btst_monthly_near_miss_gate_breakdown,
    render_btst_monthly_near_miss_gate_breakdown_markdown,
)
from scripts.audit_btst_outputs_month import audit_btst_outputs_month


def _write_text(path: str | Path, text: str) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _write_json(path: str | Path, payload: Any) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def generate_btst_monthly_reconciliation_pack(
    *,
    month: str,
    out_dir: str | Path,
    outputs_dir: str | Path = "outputs",
    repo_root: str | Path = ".",
    reports_dir: str | Path = "data/reports",
    top_n: int = 5,
    gap_cutoffs: list[float] | None = None,
    daily_events_root: str | Path | None = None,
) -> dict[str, str]:
    """Generate a month-level reconciliation pack.

    The pack is meant for post-mortem review:
    - outputs month audit (path references + date-role/canonicalization diagnostics)
    - rule top-N realized scorecard
    - execution formal-selected realized scorecard
    - execution health (why picks are empty / blocked)
    - near-miss gate breakdown (which gates are suppressing promotion)

    Returns a mapping of artifact names -> absolute file paths.
    """

    out_root = Path(out_dir).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    audit = audit_btst_outputs_month(month=month, outputs_dir=outputs_dir, repo_root=repo_root)

    rule = analyze_btst_monthly_scorecard(
        month=month,
        reports_dir=reports_dir,
        top_n=top_n,
        gap_cutoffs=gap_cutoffs,
        daily_events_root=daily_events_root,
    )
    rule_md = render_btst_monthly_scorecard_markdown(rule)

    execution = analyze_btst_monthly_execution_scorecard(
        month=month,
        reports_dir=reports_dir,
        gap_cutoffs=gap_cutoffs,
    )
    execution_md = render_btst_monthly_execution_scorecard_markdown(execution)

    health = analyze_btst_monthly_execution_health(
        month=month,
        reports_dir=reports_dir,
    )
    health_md = render_btst_monthly_execution_health_markdown(health)

    near_miss = analyze_btst_monthly_near_miss_gate_breakdown(
        month=month,
        reports_dir=reports_dir,
    )
    near_miss_md = render_btst_monthly_near_miss_gate_breakdown_markdown(near_miss)

    paths: dict[str, Path] = {
        "outputs_audit_json": out_root / f"outputs_audit_{month}.json",
        "rule_scorecard_json": out_root / f"btst_monthly_scorecard_{month}_top{top_n}.json",
        "rule_scorecard_md": out_root / f"btst_monthly_scorecard_{month}_top{top_n}.md",
        "execution_scorecard_json": out_root / f"btst_monthly_execution_scorecard_{month}.json",
        "execution_scorecard_md": out_root / f"btst_monthly_execution_scorecard_{month}.md",
        "execution_health_json": out_root / f"btst_monthly_execution_health_{month}.json",
        "execution_health_md": out_root / f"btst_monthly_execution_health_{month}.md",
        "near_miss_gate_breakdown_json": out_root / f"btst_monthly_near_miss_gate_breakdown_{month}.json",
        "near_miss_gate_breakdown_md": out_root / f"btst_monthly_near_miss_gate_breakdown_{month}.md",
    }

    _write_json(paths["outputs_audit_json"], audit)
    _write_json(paths["rule_scorecard_json"], rule)
    _write_text(paths["rule_scorecard_md"], rule_md)
    _write_json(paths["execution_scorecard_json"], execution)
    _write_text(paths["execution_scorecard_md"], execution_md)
    _write_json(paths["execution_health_json"], health)
    _write_text(paths["execution_health_md"], health_md)
    _write_json(paths["near_miss_gate_breakdown_json"], near_miss)
    _write_text(paths["near_miss_gate_breakdown_md"], near_miss_md)

    return {name: str(path) for name, path in paths.items()}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate BTST monthly reconciliation pack")
    parser.add_argument("--month", required=True, help="YYYYMM, e.g. 202605")
    parser.add_argument("--out-dir", default=None, help="Output directory (default: data/reports/btst_monthly_reconcile_<month>)")
    parser.add_argument("--outputs-dir", default="outputs")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--reports-dir", default="data/reports")
    parser.add_argument("--daily-events-root", default=None)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--gap-cutoffs", default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    month = str(args.month).strip()
    out_dir = args.out_dir or f"data/reports/btst_monthly_reconcile_{month}"

    gap_cutoffs = None
    if args.gap_cutoffs:
        # minimal parsing aligned with other scorecards
        tokens = str(args.gap_cutoffs).replace(";", ",").split(",")
        parsed: list[float] = []
        for token in tokens:
            raw = token.strip()
            if not raw:
                continue
            try:
                if raw.endswith("%"):
                    value = float(raw[:-1].strip()) / 100.0
                else:
                    value = float(raw)
                    if abs(value) > 0.2:
                        value = value / 100.0
            except (TypeError, ValueError):
                continue
            parsed.append(0.0 if value == 0 else float(-abs(value)))
        gap_cutoffs = sorted({float(c) for c in parsed}) if parsed else None

    outputs = generate_btst_monthly_reconciliation_pack(
        month=month,
        out_dir=out_dir,
        outputs_dir=args.outputs_dir,
        repo_root=args.repo_root,
        reports_dir=args.reports_dir,
        daily_events_root=args.daily_events_root,
        top_n=int(args.top_n),
        gap_cutoffs=gap_cutoffs,
    )

    print(json.dumps(outputs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
