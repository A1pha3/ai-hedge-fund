"""Analyze BTST P5 execution contract semantics from selection artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

_DEFAULT_REPORT_DIR = Path("data/p5_execution_contract_eval_sample")
_OUTPUT_DIR = Path("data/reports")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_selection_snapshot_paths(input_path: Path) -> list[Path]:
    resolved = input_path.resolve()
    if resolved.is_file():
        return [resolved]
    artifacts_root = resolved / "selection_artifacts" if (resolved / "selection_artifacts").is_dir() else resolved
    return sorted(artifacts_root.glob("*/selection_snapshot.json"))


def _coerce_row(ticker: str, payload: dict[str, Any]) -> dict[str, Any]:
    short_trade = dict(payload.get("short_trade") or {})
    candidate_source = str(payload.get("candidate_source") or "unknown")
    decision = str(short_trade.get("decision") or "rejected")
    if candidate_source in {"upgrade_only", "research_only"}:
        semantic_bucket = "research_only"
    elif decision == "near_miss":
        semantic_bucket = "near_miss"
    elif decision == "selected" and bool(payload.get("execution_eligible")):
        semantic_bucket = "selected"
    else:
        semantic_bucket = "research_only"
    return {
        "ticker": str(payload.get("ticker") or ticker),
        "candidate_source": candidate_source,
        "decision": decision,
        "execution_eligible": bool(payload.get("execution_eligible", short_trade.get("execution_eligible"))),
        "downgrade_reasons": [str(reason) for reason in list(payload.get("downgrade_reasons") or short_trade.get("downgrade_reasons") or []) if str(reason or "").strip()],
        "historical_prior_quality_level": str(payload.get("historical_prior_quality_level") or short_trade.get("historical_prior_quality_level") or ""),
        "btst_regime_gate": str(payload.get("btst_regime_gate") or short_trade.get("btst_regime_gate") or ""),
        "semantic_bucket": semantic_bucket,
    }


def analyze_btst_execution_contract_eval(input_path: Path) -> dict[str, Any]:
    snapshot_paths = _iter_selection_snapshot_paths(input_path)
    rows: list[dict[str, Any]] = []
    downgrade_reason_counts: dict[str, int] = {}
    semantic_counts = {"selected": 0, "near_miss": 0, "research_only": 0}

    for snapshot_path in snapshot_paths:
        try:
            snapshot = _load_json(snapshot_path)
        except Exception:
            continue
        for ticker, payload in dict(snapshot.get("selection_targets") or {}).items():
            row = _coerce_row(ticker, dict(payload or {}))
            rows.append(row)
            semantic_counts[row["semantic_bucket"]] = int(semantic_counts.get(row["semantic_bucket"]) or 0) + 1
            for reason in row["downgrade_reasons"]:
                downgrade_reason_counts[reason] = int(downgrade_reason_counts.get(reason) or 0) + 1

    comparison_samples = sorted(rows, key=lambda row: (len(row["downgrade_reasons"]), row["semantic_bucket"], row["ticker"]), reverse=True)[:5]
    return {
        "report_type": "p5_btst_execution_contract_eval",
        "generated_on": str(date.today()),
        "snapshot_count": len(snapshot_paths),
        "contract_summary": {
            "target_count": len(rows),
            "execution_eligible_count": sum(1 for row in rows if row["execution_eligible"]),
            "selected_count": semantic_counts["selected"],
            "near_miss_count": semantic_counts["near_miss"],
            "research_only_count": semantic_counts["research_only"],
        },
        "semantics_comparison": {
            "selected": {
                "definition": "score passed + gate allowed + prior quality qualified + formal execution eligible",
                "formal_buy_flow": True,
            },
            "near_miss": {
                "definition": "observation only; keeps visibility but never enters formal buy-order flow",
                "formal_buy_flow": False,
            },
            "research_only": {
                "definition": "research or upgrade queue only; excluded from formal BTST performance stats",
                "formal_buy_flow": False,
            },
        },
        "downgrade_reason_counts": downgrade_reason_counts,
        "comparison_samples": comparison_samples,
    }


def _render_markdown(analysis: dict[str, Any]) -> str:
    contract_summary = dict(analysis.get("contract_summary") or {})
    semantics = dict(analysis.get("semantics_comparison") or {})
    lines = [
        "# P5 BTST Execution Contract Eval",
        "",
        f"**Generated on:** {analysis.get('generated_on', 'N/A')}",
        f"**Snapshots analyzed:** {analysis.get('snapshot_count', 0)}",
        "",
        "## Contract Summary",
        "",
        f"- `target_count`: {contract_summary.get('target_count', 0)}",
        f"- `execution_eligible_count`: {contract_summary.get('execution_eligible_count', 0)}",
        f"- `selected_count`: {contract_summary.get('selected_count', 0)}",
        f"- `near_miss_count`: {contract_summary.get('near_miss_count', 0)}",
        f"- `research_only_count`: {contract_summary.get('research_only_count', 0)}",
        "",
        "## selected / near_miss / research_only 语义对比",
        "",
    ]
    for key in ("selected", "near_miss", "research_only"):
        payload = dict(semantics.get(key) or {})
        lines.extend(
            [
                f"### {key}",
                f"- formal_buy_flow: {payload.get('formal_buy_flow', False)}",
                f"- definition: {payload.get('definition', 'n/a')}",
                "",
            ]
        )
    lines.extend(
        [
            "## Comparison Samples",
            "",
            "| ticker | bucket | decision | execution_eligible | downgrade_reasons | gate | prior |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    samples = list(analysis.get("comparison_samples") or [])
    if samples:
        for row in samples:
            lines.append(
                f"| {row.get('ticker', '')} | {row.get('semantic_bucket', '')} | {row.get('decision', '')} | {row.get('execution_eligible', False)} | {', '.join(row.get('downgrade_reasons', [])) or 'none'} | {row.get('btst_regime_gate', '') or 'n/a'} | {row.get('historical_prior_quality_level', '') or 'n/a'} |"
            )
    else:
        lines.append("| _none_ |  |  |  |  |  |  |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_dir", nargs="?", default=str(_DEFAULT_REPORT_DIR), help="Directory containing selection_artifacts/ sub-tree")
    parser.add_argument("--output-dir", default=str(_OUTPUT_DIR), help="Directory to write reports")
    args = parser.parse_args(argv)

    analysis = analyze_btst_execution_contract_eval(Path(args.report_dir))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "p5_btst_execution_contract_eval.json"
    md_path = output_dir / "p5_btst_execution_contract_eval.md"
    json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(analysis), encoding="utf-8")

    print(f"P5 execution contract eval written to:\n  {json_path}\n  {md_path}")


if __name__ == "__main__":
    main()
