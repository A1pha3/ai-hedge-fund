from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from scripts.analyze_layer_b_rule_variants import VARIANTS, _build_comparison, _run_variant


def _resolve_trade_dates(raw_trade_dates: str) -> list[str]:
    trade_dates = [item.strip() for item in raw_trade_dates.split(",") if item.strip()]
    if not trade_dates:
        raise SystemExit("--trade-dates is required")
    return trade_dates


def _write_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = list(rows[0].keys()) if rows else [
        "trade_date",
        "ticker",
        "industry_sw",
        "baseline_score_b",
        "variant_score_b",
        "score_delta",
        "tags",
        "manual_verdict",
        "manual_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _render_markdown(variant_name: str, comparison: dict) -> str:
    lines = [
        f"# {variant_name} 新增释放样本审核台账",
        "",
        f"- baseline passes: {comparison['baseline_total_layer_b_passes']}",
        f"- variant passes: {comparison['variant_total_layer_b_passes']}",
        f"- delta: {comparison['layer_b_pass_delta']}",
        f"- added_sample_count: {comparison['added_sample_count']}",
        "",
        "## 审核重点",
        "",
        "1. 这些新增样本是否真的是你想释放的边缘健康票。",
        "2. 它们是否高度集中在 neutral_mean_reversion_active + trend/fundamental dual-leg。",
        "3. 是否混入了明显只是被规则放水带出来的噪声票。",
        "",
        "## 新增样本",
        "",
    ]
    if not comparison["added_samples"]:
        lines.extend(["- 无新增样本", ""])
        return "\n".join(lines)

    for item in comparison["added_samples"]:
        lines.append(
            f"- {item['trade_date']} / {item['ticker']} | industry={item['industry_sw']} | "
            f"baseline={item['baseline_score_b']:.4f} -> variant={item['variant_score_b']:.4f} | delta={item['score_delta']:.4f}"
        )
        lines.append(f"  - tags: {', '.join(item['tags'])}")
        lines.append(f"  - strategy_summary: {json.dumps(item['strategy_summary'], ensure_ascii=False)}")
        lines.append(f"  - profitability: {json.dumps(item['profitability'], ensure_ascii=False)}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export manual-review ledger for samples newly added by a Layer B variant.")
    parser.add_argument("--trade-dates", required=True, help="Comma-separated trade dates like 20260323,20260324")
    parser.add_argument("--variant", required=True, help="Variant name from scripts/analyze_layer_b_rule_variants.py")
    parser.add_argument("--output-dir", default="", help="Optional output dir")
    args = parser.parse_args()

    if args.variant not in VARIANTS or args.variant == "baseline":
        raise SystemExit(f"Unsupported variant: {args.variant}")

    trade_dates = _resolve_trade_dates(args.trade_dates)
    baseline = _run_variant(trade_dates, {})
    variant = _run_variant(trade_dates, VARIANTS[args.variant])
    comparison = _build_comparison(args.variant, baseline, variant)

    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser().resolve()
    else:
        output_dir = Path(__file__).resolve().parents[1] / "data" / "reports" / f"{args.variant}_added_review_{trade_dates[0]}_{trade_dates[-1]}"
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for item in comparison["added_samples"]:
        rows.append(
            {
                "trade_date": item["trade_date"],
                "ticker": item["ticker"],
                "industry_sw": item["industry_sw"],
                "baseline_score_b": f"{float(item['baseline_score_b']):.4f}",
                "variant_score_b": f"{float(item['variant_score_b']):.4f}",
                "score_delta": f"{float(item['score_delta']):.4f}",
                "tags": ";".join(item["tags"]),
                "manual_verdict": "",
                "manual_notes": "",
            }
        )

    csv_path = output_dir / "added_samples_ledger.csv"
    md_path = output_dir / "added_samples_review.md"
    summary_path = output_dir / "summary.json"
    _write_csv(csv_path, rows)
    md_path.write_text(_render_markdown(args.variant, comparison), encoding="utf-8")
    summary = {
        "variant": args.variant,
        "trade_dates": trade_dates,
        "added_sample_count": comparison["added_sample_count"],
        "layer_b_pass_delta": comparison["layer_b_pass_delta"],
        "output_files": {
            "csv": str(csv_path),
            "markdown": str(md_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()