"""Analyze BTST P6 risk-budget overlay semantics from selection artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

_DEFAULT_REPORT_DIR = Path("data/p6_risk_budget_overlay_eval_sample")
_OUTPUT_DIR = Path("data/reports")
_RISK_BUDGET_MATRIX = [
    {"condition": "halt × any × any", "risk_budget_ratio": 0.0, "explanation": "停止正式持仓；只保留观察或空仓。"},
    {"condition": "shadow_only × any × any", "risk_budget_ratio": 0.0, "explanation": "仅 paper/shadow，正式仓位为 0。"},
    {"condition": "normal_trade × execution_ready × formal_full", "risk_budget_ratio": 1.0, "explanation": "保持默认正式仓位。"},
    {"condition": "normal_trade × execution_ready × formal_capped", "risk_budget_ratio": 0.6, "explanation": "执行合格但质量偏弱，降配而非满仓。"},
    {"condition": "aggressive_trade × execution_ready × formal_full", "risk_budget_ratio": 1.15, "explanation": "强势窗口允许放大到上限。"},
    {"condition": "aggressive_trade × execution_ready × formal_capped", "risk_budget_ratio": 0.75, "explanation": "强势窗口下仍保留折价风险预算。"},
    {"condition": "any × watch_only/reject/research_only × any", "risk_budget_ratio": 0.0, "explanation": "观察层或不合格样本不进入正式持仓。"},
]


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
    p6_risk_budget = dict(short_trade.get("metrics_payload", {}).get("p6_risk_budget", {}) or short_trade.get("explainability_payload", {}).get("p6_risk_budget", {}) or {})
    return {
        "ticker": str(payload.get("ticker") or ticker),
        "candidate_source": str(payload.get("candidate_source") or "unknown"),
        "decision": str(short_trade.get("decision") or "rejected"),
        "execution_eligible": bool(payload.get("execution_eligible", short_trade.get("execution_eligible"))),
        "gate": str(payload.get("btst_regime_gate") or short_trade.get("btst_regime_gate") or p6_risk_budget.get("risk_budget_gate") or "unknown"),
        "prior_quality_label": str(payload.get("historical_prior_quality_level") or short_trade.get("historical_prior_quality_level") or p6_risk_budget.get("prior_quality_label") or "unknown"),
        "risk_budget_ratio": float(p6_risk_budget.get("risk_budget_ratio", 1.0) or 0.0),
        "formal_exposure_bucket": str(p6_risk_budget.get("formal_exposure_bucket") or "unknown"),
        "execution_contract_bucket": str(p6_risk_budget.get("execution_contract_bucket") or "unknown"),
    }


def analyze_btst_risk_budget_overlay_eval(input_path: Path) -> dict[str, Any]:
    snapshot_paths = _iter_selection_snapshot_paths(input_path)
    rows: list[dict[str, Any]] = []
    gate_distribution: dict[str, int] = {}
    formal_exposure_distribution: dict[str, int] = {}
    suppressed_position_summary = {
        "zero_budget_count": 0,
        "reduced_budget_count": 0,
    }

    for snapshot_path in snapshot_paths:
        try:
            snapshot = _load_json(snapshot_path)
        except Exception:
            continue
        for ticker, payload in dict(snapshot.get("selection_targets") or {}).items():
            row = _coerce_row(ticker, dict(payload or {}))
            rows.append(row)
            gate_distribution[row["gate"]] = int(gate_distribution.get(row["gate"]) or 0) + 1
            formal_exposure_distribution[row["formal_exposure_bucket"]] = int(formal_exposure_distribution.get(row["formal_exposure_bucket"]) or 0) + 1
            if row["formal_exposure_bucket"] == "zero_budget":
                suppressed_position_summary["zero_budget_count"] += 1
            if row["formal_exposure_bucket"] == "reduced":
                suppressed_position_summary["reduced_budget_count"] += 1

    session_summary_path = Path(input_path) / "session_summary.json"
    session_summary = _load_json(session_summary_path) if session_summary_path.exists() else {}
    session_level_summary = dict(session_summary.get("btst_risk_budget_p6_summary") or {})
    if session_level_summary:
        gate_distribution = dict(session_level_summary.get("gate_distribution") or gate_distribution)
        formal_exposure_distribution = dict(session_level_summary.get("formal_exposure_distribution") or formal_exposure_distribution)
        suppressed_position_summary = dict(session_level_summary.get("suppressed_position_summary") or suppressed_position_summary)

    strong_day_rows = [row for row in rows if row["gate"] in {"normal_trade", "aggressive_trade"} and bool(row["execution_eligible"])]
    retained_formal_exposure_count = sum(1 for row in strong_day_rows if float(row["risk_budget_ratio"]) > 0.0)
    strong_day_retention_summary = {
        "strong_day_candidate_count": len(strong_day_rows),
        "retained_formal_exposure_count": retained_formal_exposure_count,
        "retained_formal_exposure_rate": round(retained_formal_exposure_count / len(strong_day_rows), 4) if strong_day_rows else 0.0,
    }
    comparison_samples = sorted(rows, key=lambda row: (row["risk_budget_ratio"], row["formal_exposure_bucket"], row["ticker"]))[:5]
    return {
        "report_type": "p6_btst_risk_budget_overlay_eval",
        "generated_on": str(date.today()),
        "snapshot_count": len(snapshot_paths),
        "risk_budget_matrix": _RISK_BUDGET_MATRIX,
        "gate_distribution": gate_distribution,
        "formal_exposure_distribution": formal_exposure_distribution,
        "suppressed_position_summary": suppressed_position_summary,
        "strong_day_retention_summary": strong_day_retention_summary,
        "comparison_samples": comparison_samples,
    }


def _render_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# P6 BTST Risk Budget Overlay Eval",
        "",
        f"**Generated on:** {analysis.get('generated_on', 'N/A')}",
        f"**Snapshots analyzed:** {analysis.get('snapshot_count', 0)}",
        "",
        "## 风险预算矩阵说明",
        "",
        "| 条件 | 风险预算比率 | 说明 |",
        "|---|---:|---|",
    ]
    for row in list(analysis.get("risk_budget_matrix") or []):
        lines.append(f"| {row.get('condition', '')} | {row.get('risk_budget_ratio', 0.0)} | {row.get('explanation', '')} |")
    lines.extend(
        [
            "",
            "## Session Summary Overlay",
            "",
            f"- gate_distribution: {analysis.get('gate_distribution', {})}",
            f"- formal_exposure_distribution: {analysis.get('formal_exposure_distribution', {})}",
            f"- suppressed_position_summary: {analysis.get('suppressed_position_summary', {})}",
            "",
            "## 强势日正式暴露保留",
            "",
            f"- strong_day_retention_summary: {analysis.get('strong_day_retention_summary', {})}",
            "",
            "## Comparison Samples",
            "",
            "| ticker | gate | prior | contract | ratio | exposure_bucket |",
            "|---|---|---|---|---:|---|",
        ]
    )
    samples = list(analysis.get("comparison_samples") or [])
    if samples:
        for row in samples:
            lines.append(
                f"| {row.get('ticker', '')} | {row.get('gate', '')} | {row.get('prior_quality_label', '')} | {row.get('execution_contract_bucket', '')} | {row.get('risk_budget_ratio', 0.0)} | {row.get('formal_exposure_bucket', '')} |"
            )
    else:
        lines.append("| _none_ |  |  |  |  |  |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_dir", nargs="?", default=str(_DEFAULT_REPORT_DIR), help="Directory containing selection_artifacts/ sub-tree")
    parser.add_argument("--output-dir", default=str(_OUTPUT_DIR), help="Directory to write reports")
    args = parser.parse_args(argv)

    analysis = analyze_btst_risk_budget_overlay_eval(Path(args.report_dir))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "p6_btst_risk_budget_overlay_eval.json"
    md_path = output_dir / "p6_btst_risk_budget_overlay_eval.md"
    json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(analysis), encoding="utf-8")

    print(f"P6 risk budget overlay eval written to:\n  {json_path}\n  {md_path}")


if __name__ == "__main__":
    main()
