from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_btst_5d_15pct_factor_research_round1 import (
    DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT,
)
from scripts.analyze_btst_5d_15pct_trend_breakout_drilldown import (
    _rows_with_gap_le,
    _summary,
    _top_fraction_rows,
    DEFAULT_REPORTS_ROOT,
)
from scripts.analyze_btst_5d_15pct_trend_gate_oos_validation import (
    _gate_predicate,
    DEFAULT_GATE_ID,
)
from scripts.analyze_btst_5d_15pct_trend_top20_gate_diagnostics import (
    _collect_rows,
    _dedupe_signal_rows,
    DEFAULT_REPORT_NAME_CONTAINS,
)
from scripts.btst_analysis_utils import round_or_none as _round_or_none
from scripts.btst_analysis_utils import safe_float as _safe_float

DEFAULT_OUTPUT_JSON = Path("data/reports/btst_5d_15pct_trend_gate_missing_price_manifest_latest.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_5d_15pct_trend_gate_missing_price_manifest_latest.md")
DEFAULT_TOP_FRACTION = 0.20
DEFAULT_MAX_ENTRY_GAP = 0.03


def _priority_bucket(row: dict[str, Any]) -> tuple[int, str, str]:
    missing_reason = str(row.get("local_price_missing_reason") or "")
    if missing_reason == "missing_ticker_snapshot_root":
        return 0, "p0_gate_missing_ticker_snapshot_root", "fetch_missing_gate_candidate_history"
    if missing_reason == "local_snapshot_missing_future_bar":
        return 1, "p1_gate_missing_future_bar", "extend_gate_candidate_snapshot_forward"
    return 2, "p2_gate_other_missing_price", "repair_gate_candidate_local_snapshot"


def _priority_score(row: dict[str, Any]) -> float | None:
    values = [
        _safe_float(row.get("trend_acceleration")),
        1.0 - float(_safe_float(row.get("close_strength")) or 0.0) if _safe_float(row.get("close_strength")) is not None else None,
        _safe_float(row.get("trend_continuation")),
    ]
    populated = [value for value in values if value is not None]
    if not populated:
        return None
    return _round_or_none(sum(populated) / len(populated))


def _manifest_row(row: dict[str, Any], *, gate_id: str) -> dict[str, Any]:
    priority_order, priority_bucket, action = _priority_bucket(row)
    return {
        "priority_order": priority_order,
        "priority_bucket": priority_bucket,
        "补数_action": action,
        "gate_id": gate_id,
        "report_dir_name": row.get("report_dir_name"),
        "ticker": row.get("ticker"),
        "trade_date": row.get("trade_date"),
        "event_prototype": row.get("event_prototype"),
        "local_price_missing_reason": row.get("local_price_missing_reason"),
        "decision": row.get("decision"),
        "candidate_source": row.get("candidate_source"),
        "trend_acceleration": row.get("trend_acceleration"),
        "close_strength": row.get("close_strength"),
        "trend_continuation": row.get("trend_continuation"),
        "volume_expansion_quality": row.get("volume_expansion_quality"),
        "breakout_freshness": row.get("breakout_freshness"),
        "priority_score": _priority_score(row),
        "slice_tags": ["trend_acceleration_top_pre_execution", gate_id],
    }


def _sort_manifest_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            int(row.get("priority_order") or 0),
            -float(row.get("priority_score") or 0.0),
            str(row.get("trade_date") or ""),
            str(row.get("ticker") or ""),
            str(row.get("report_dir_name") or ""),
        ),
    )


def _request_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("ticker") or ""),
        str(row.get("trade_date") or ""),
        str(row.get("gate_id") or ""),
        str(row.get("local_price_missing_reason") or ""),
    )


def _dedupe_manifest_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = _request_key(row)
        report_dir_name = str(row.get("report_dir_name") or "")
        if key not in deduped:
            deduped[key] = {
                **row,
                "occurrence_count": 1,
                "report_dir_names": [report_dir_name] if report_dir_name else [],
            }
            continue
        record = deduped[key]
        record["occurrence_count"] = int(record.get("occurrence_count") or 0) + 1
        report_dir_names = list(record.get("report_dir_names") or [])
        if report_dir_name and report_dir_name not in report_dir_names:
            report_dir_names.append(report_dir_name)
        record["report_dir_names"] = report_dir_names
    return list(deduped.values())


def analyze_btst_5d_15pct_trend_gate_missing_price_manifest(
    reports_root: str | Path,
    *,
    gate_id: str = DEFAULT_GATE_ID,
    boundary_quarantine_artifact: str | Path | None = None,
    report_name_contains: str = DEFAULT_REPORT_NAME_CONTAINS,
    top_fraction: float = DEFAULT_TOP_FRACTION,
    max_entry_gap: float = DEFAULT_MAX_ENTRY_GAP,
    min_closed_cycle_count: int = 30,
    max_rows: int | None = None,
) -> dict[str, Any]:
    resolved_root = Path(reports_root).expanduser().resolve()
    rows = _collect_rows(
        resolved_root,
        boundary_quarantine_artifact=boundary_quarantine_artifact,
        local_price_only=True,
        report_name_contains=report_name_contains,
    )
    trend_rows = [row for row in rows if row.get("event_prototype") == "trend_continuation"]
    top_rows = _top_fraction_rows(trend_rows, "trend_acceleration", top_fraction)
    predicate = _gate_predicate(gate_id)
    pre_execution_rows = [row for row in top_rows if predicate(row)]
    pre_execution_unique_rows = _dedupe_signal_rows(pre_execution_rows)
    missing_rows = [row for row in pre_execution_rows if row.get("local_price_missing_reason")]
    known_rows = [row for row in pre_execution_rows if not row.get("local_price_missing_reason")]
    known_executable_rows = _rows_with_gap_le(known_rows, max_entry_gap)
    occurrence_rows = _sort_manifest_rows([_manifest_row(row, gate_id=gate_id) for row in missing_rows])
    manifest_rows = _sort_manifest_rows(_dedupe_manifest_rows(occurrence_rows))
    limited_rows = manifest_rows if not max_rows or max_rows <= 0 else manifest_rows[:max_rows]
    for index, row in enumerate(limited_rows, start=1):
        row["priority_rank"] = index
        row.pop("priority_order", None)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        "report_name_contains": report_name_contains,
        "gate_id": gate_id,
        "top_fraction": top_fraction,
        "max_entry_gap": max_entry_gap,
        "row_count": len(rows),
        "trend_row_count": len(trend_rows),
        "pre_execution_occurrence_count": len(pre_execution_rows),
        "pre_execution_unique_count": len(pre_execution_unique_rows),
        "known_executable_unique_summary": _summary(_dedupe_signal_rows(known_executable_rows), min_closed_cycle_count=min_closed_cycle_count),
        "missing_occurrence_count": len(missing_rows),
        "manifest_occurrence_count": len(occurrence_rows),
        "manifest_row_count": len(limited_rows),
        "missing_reason_counts": dict(sorted(Counter(str(row.get("local_price_missing_reason")) for row in missing_rows).items())),
        "priority_bucket_counts": dict(sorted(Counter(str(row.get("priority_bucket")) for row in limited_rows).items())),
        "manifest_rows": limited_rows,
    }


def render_trend_gate_missing_price_manifest_markdown(manifest: dict[str, Any], *, row_limit: int = 120) -> str:
    lines = ["# BTST 5D / 15% Trend Gate Missing Price Manifest", ""]
    lines.append(f"- gate_id: {manifest.get('gate_id')}")
    lines.append(f"- row_count: {manifest.get('row_count')}")
    lines.append(f"- trend_row_count: {manifest.get('trend_row_count')}")
    lines.append(f"- pre_execution_occurrence_count: {manifest.get('pre_execution_occurrence_count')}")
    lines.append(f"- pre_execution_unique_count: {manifest.get('pre_execution_unique_count')}")
    lines.append(f"- missing_occurrence_count: {manifest.get('missing_occurrence_count')}")
    lines.append(f"- manifest_row_count: {manifest.get('manifest_row_count')}")
    known = dict(manifest.get("known_executable_unique_summary") or {})
    lines.append(f"- known_executable_unique_closed: {known.get('closed_cycle_count')}")
    lines.append(f"- known_executable_unique_hit_rate_15pct: {known.get('hit_rate_15pct')}")
    lines.append("")
    lines.append("## Missing Reason Counts")
    for label, count in dict(manifest.get("missing_reason_counts") or {}).items():
        lines.append(f"- {label}: {count}")
    lines.append("")
    lines.append("## Priority Bucket Counts")
    for label, count in dict(manifest.get("priority_bucket_counts") or {}).items():
        lines.append(f"- {label}: {count}")
    lines.append("")
    lines.append("## Top补数 Rows")
    for row in list(manifest.get("manifest_rows") or [])[:row_limit]:
        lines.append(
            f"- #{row.get('priority_rank')} {row.get('priority_bucket')} {row.get('ticker')} {row.get('trade_date')} "
            f"reason={row.get('local_price_missing_reason')} score={row.get('priority_score')} occurrences={row.get('occurrence_count')}"
        )
    lines.append("")
    return "\n".join(lines)


def _stdout_summary(manifest: dict[str, Any], output_json: Path, output_md: Path) -> dict[str, Any]:
    return {
        "generated_at": manifest.get("generated_at"),
        "gate_id": manifest.get("gate_id"),
        "pre_execution_unique_count": manifest.get("pre_execution_unique_count"),
        "missing_occurrence_count": manifest.get("missing_occurrence_count"),
        "manifest_row_count": manifest.get("manifest_row_count"),
        "missing_reason_counts": manifest.get("missing_reason_counts"),
        "priority_bucket_counts": manifest.get("priority_bucket_counts"),
        "output_json": str(output_json),
        "output_md": str(output_md),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a pre-execution missing-price manifest for a BTST trend gate.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument("--gate-id", default=DEFAULT_GATE_ID)
    parser.add_argument("--boundary-quarantine-artifact", default=str(DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT))
    parser.add_argument("--report-name-contains", default=DEFAULT_REPORT_NAME_CONTAINS)
    parser.add_argument("--top-fraction", type=float, default=DEFAULT_TOP_FRACTION)
    parser.add_argument("--max-entry-gap", type=float, default=DEFAULT_MAX_ENTRY_GAP)
    parser.add_argument("--min-closed-cycle-count", type=int, default=30)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--markdown-row-limit", type=int, default=120)
    args = parser.parse_args()

    manifest = analyze_btst_5d_15pct_trend_gate_missing_price_manifest(
        args.reports_root,
        gate_id=args.gate_id,
        boundary_quarantine_artifact=args.boundary_quarantine_artifact,
        report_name_contains=args.report_name_contains,
        top_fraction=args.top_fraction,
        max_entry_gap=args.max_entry_gap,
        min_closed_cycle_count=args.min_closed_cycle_count,
        max_rows=args.max_rows,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_trend_gate_missing_price_manifest_markdown(manifest, row_limit=args.markdown_row_limit), encoding="utf-8")
    print(json.dumps(_stdout_summary(manifest, output_json, output_md), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
