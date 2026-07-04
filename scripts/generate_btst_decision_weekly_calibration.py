from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_rows(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [dict(row) for row in list(payload.get("rows") or [])]


def _summarize_group(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        label = str(row.get(key) or "unknown")
        grouped.setdefault(label, []).append(row)
    summary: dict[str, dict[str, Any]] = {}
    for label, label_rows in grouped.items():
        positives = sum(1 for row in label_rows if row.get("review_label") == "close_positive")
        summary[label] = {
            "row_count": len(label_rows),
            "close_positive_count": positives,
            "close_positive_rate": round(positives / len(label_rows), 4) if label_rows else None,
        }
    return summary


def build_weekly_calibration(ledger_paths: list[str | Path]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in ledger_paths:
        rows.extend(_read_rows(path))
    return {
        "total_rows": len(rows),
        "by_evidence_grade": _summarize_group(rows, "evidence_grade"),
        "by_data_quality": _summarize_group(rows, "data_quality"),
        "by_role": _summarize_group(rows, "role"),
        "by_entry_mode": _summarize_group(rows, "entry_mode"),
    }


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.2f}%"


def _render_group(title: str, rows: dict[str, dict[str, Any]]) -> list[str]:
    lines = [
        f"## {title}",
        "",
        "| 分组 | 样本 | 收盘为正 | 收盘胜率 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for label in sorted(rows):
        item = rows[label]
        lines.append(f"| {label} | {item.get('row_count')} | {item.get('close_positive_count')} | {_fmt_pct(item.get('close_positive_rate'))} |")
    return lines


def render_weekly_calibration_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# BTST Decision Weekly Calibration",
        "",
        f"- total_rows: `{summary.get('total_rows')}`",
        "",
    ]
    lines.extend(_render_group("By Evidence Grade", dict(summary.get("by_evidence_grade") or {})))
    lines.extend([""])
    lines.extend(_render_group("By Data Quality", dict(summary.get("by_data_quality") or {})))
    lines.extend([""])
    lines.extend(_render_group("By Role", dict(summary.get("by_role") or {})))
    lines.extend([""])
    lines.extend(_render_group("By Entry Mode", dict(summary.get("by_entry_mode") or {})))
    return "\n".join(lines) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate BTST decision weekly calibration.")
    parser.add_argument("ledger_paths", nargs="+")
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary = build_weekly_calibration(args.ledger_paths)
    if args.output_json:
        json_path = Path(args.output_json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.output_md:
        md_path = Path(args.output_md)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(render_weekly_calibration_markdown(summary), encoding="utf-8")
    print(
        json.dumps(
            {"status": "generated", "total_rows": summary["total_rows"]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
