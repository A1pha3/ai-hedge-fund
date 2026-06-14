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
    _collect_round1_rows,
    _round_or_none,
    _safe_float,
    _top_fraction_rows,
    DEFAULT_REPORTS_ROOT,
    SCOPED_PROTOTYPES,
)

DEFAULT_OUTPUT_JSON = Path("data/reports/btst_5d_15pct_scoped_missing_price_manifest_latest.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_5d_15pct_scoped_missing_price_manifest_latest.md")
DEFAULT_REPORT_NAME_CONTAINS = ""
DEFAULT_TOP_FRACTION = 0.40


def _row_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("report_dir_name") or ""),
        str(row.get("ticker") or ""),
        str(row.get("trade_date") or ""),
        str(row.get("event_prototype") or ""),
    )


def _mean_score(values: list[float | None]) -> float | None:
    populated = [value for value in values if value is not None]
    if not populated:
        return None
    return _round_or_none(sum(populated) / len(populated))


def _slice_tags(row: dict[str, Any], top_trend_keys: set[tuple[str, str, str, str]], top_breakout_keys: set[tuple[str, str, str, str]]) -> list[str]:
    tags: list[str] = []
    row_key = _row_key(row)
    if row.get("event_prototype") == "trend_continuation":
        if row_key in top_trend_keys:
            tags.append("trend_acceleration_top_40pct")
        if (_safe_float(row.get("close_strength")) or 0.0) >= 0.60:
            tags.append("close_strength_confirmed")
    if row.get("event_prototype") == "breakout_ignition":
        if row_key in top_breakout_keys:
            tags.append("breakout_freshness_top_40pct")
        if (_safe_float(row.get("volume_expansion_quality")) or 0.0) >= 0.55:
            tags.append("volume_quality_confirmed")
    return tags


def _priority_bucket(row: dict[str, Any], slice_tags: list[str]) -> tuple[int, str, str]:
    prototype = str(row.get("event_prototype") or "")
    missing_reason = str(row.get("local_price_missing_reason") or "")
    if prototype == "trend_continuation" and "trend_acceleration_top_40pct" in slice_tags and missing_reason == "missing_ticker_snapshot_root":
        return 0, "p0_trend_top40_missing_ticker_snapshot_root", "fetch_missing_ticker_snapshot_history"
    if prototype == "trend_continuation" and "trend_acceleration_top_40pct" in slice_tags and missing_reason == "local_snapshot_missing_future_bar":
        return 1, "p1_trend_top40_missing_future_bar", "extend_existing_ticker_snapshot_forward"
    if prototype == "trend_continuation":
        return 2, "p2_trend_scoped_missing", "fetch_or_extend_trend_scoped_snapshot"
    return 3, "p3_breakout_scoped_missing", "top_up_breakout_sample_for_validation"


def _priority_score(row: dict[str, Any]) -> float | None:
    if row.get("event_prototype") == "breakout_ignition":
        return _mean_score(
            [
                _safe_float(row.get("breakout_freshness")),
                _safe_float(row.get("volume_expansion_quality")),
                _safe_float(row.get("close_strength")),
            ]
        )
    return _mean_score(
        [
            _safe_float(row.get("trend_acceleration")),
            _safe_float(row.get("close_strength")),
            _safe_float(row.get("trend_continuation")),
        ]
    )


def _manifest_row(row: dict[str, Any], top_trend_keys: set[tuple[str, str, str, str]], top_breakout_keys: set[tuple[str, str, str, str]]) -> dict[str, Any]:
    tags = _slice_tags(row, top_trend_keys, top_breakout_keys)
    priority_order, priority_bucket, action = _priority_bucket(row, tags)
    return {
        "priority_order": priority_order,
        "priority_bucket": priority_bucket,
        "补数_action": action,
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
        "breakout_freshness": row.get("breakout_freshness"),
        "volume_expansion_quality": row.get("volume_expansion_quality"),
        "trend_family": row.get("trend_family"),
        "breakout_family": row.get("breakout_family"),
        "priority_score": _priority_score(row),
        "slice_tags": tags,
    }


def _sort_manifest_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            int(row.get("priority_order") or 0),
            -float(row.get("priority_score") or 0.0),
            str(row.get("report_dir_name") or ""),
            str(row.get("trade_date") or ""),
            str(row.get("ticker") or ""),
        ),
    )


def _request_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("ticker") or ""),
        str(row.get("trade_date") or ""),
        str(row.get("event_prototype") or ""),
        str(row.get("local_price_missing_reason") or ""),
        str(row.get("补数_action") or ""),
    )


def _dedupe_manifest_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
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


def analyze_btst_5d_15pct_scoped_missing_price_manifest(
    reports_root: str | Path,
    *,
    boundary_quarantine_artifact: str | Path | None = None,
    report_name_contains: str = DEFAULT_REPORT_NAME_CONTAINS,
    top_fraction: float = DEFAULT_TOP_FRACTION,
    max_rows: int | None = None,
) -> dict[str, Any]:
    resolved_root = Path(reports_root).expanduser().resolve()
    rows = _collect_round1_rows(
        resolved_root,
        boundary_quarantine_artifact=boundary_quarantine_artifact,
        local_price_only=True,
        report_name_contains=report_name_contains,
    )
    scoped_rows = [row for row in rows if row.get("event_prototype") in SCOPED_PROTOTYPES]
    scoped_missing_rows = [row for row in scoped_rows if row.get("local_price_missing_reason")]
    excluded_counts = Counter(str(row.get("event_prototype") or "unclassified") for row in rows if row.get("event_prototype") not in SCOPED_PROTOTYPES)

    trend_rows = [row for row in scoped_rows if row.get("event_prototype") == "trend_continuation"]
    breakout_rows = [row for row in scoped_rows if row.get("event_prototype") == "breakout_ignition"]
    top_trend_keys = {_row_key(row) for row in _top_fraction_rows(trend_rows, "trend_acceleration", top_fraction)}
    top_breakout_keys = {_row_key(row) for row in _top_fraction_rows(breakout_rows, "breakout_freshness", top_fraction)}

    occurrence_rows = _sort_manifest_rows([_manifest_row(row, top_trend_keys, top_breakout_keys) for row in scoped_missing_rows])
    sorted_rows = _sort_manifest_rows(_dedupe_manifest_rows(occurrence_rows))
    limited_rows = sorted_rows if not max_rows or max_rows <= 0 else sorted_rows[:max_rows]
    for index, row in enumerate(limited_rows, start=1):
        row["priority_rank"] = index
        row.pop("priority_order", None)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        "report_name_contains": report_name_contains,
        "scope": {
            "included_event_prototypes": list(SCOPED_PROTOTYPES),
            "frozen_out": ["volume_quality_release", "unclassified", "full_market_feature_sweep"],
        },
        "row_count": len(rows),
        "scoped_row_count": len(scoped_rows),
        "scoped_missing_count": len(scoped_missing_rows),
        "manifest_occurrence_count": len(occurrence_rows),
        "manifest_row_count": len(limited_rows),
        "top_fraction": top_fraction,
        "missing_reason_counts": dict(sorted(Counter(str(row.get("local_price_missing_reason")) for row in scoped_missing_rows).items())),
        "event_prototype_counts": dict(sorted(Counter(str(row.get("event_prototype")) for row in scoped_missing_rows).items())),
        "priority_bucket_counts": dict(sorted(Counter(str(row.get("priority_bucket")) for row in limited_rows).items())),
        "excluded_event_prototype_counts": dict(sorted(excluded_counts.items())),
        "manifest_rows": limited_rows,
    }


def render_scoped_missing_price_manifest_markdown(manifest: dict[str, Any], *, row_limit: int = 80) -> str:
    lines = ["# BTST 5D / 15% Scoped Missing Price Manifest", ""]
    lines.append(f"- row_count: {manifest.get('row_count')}")
    lines.append(f"- scoped_row_count: {manifest.get('scoped_row_count')}")
    lines.append(f"- scoped_missing_count: {manifest.get('scoped_missing_count')}")
    lines.append(f"- manifest_occurrence_count: {manifest.get('manifest_occurrence_count')}")
    lines.append(f"- manifest_row_count: {manifest.get('manifest_row_count')}")
    lines.append(f"- report_name_contains: {manifest.get('report_name_contains')!r}")
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
        tags = ",".join(list(row.get("slice_tags") or []))
        lines.append(
            f"- #{row.get('priority_rank')} {row.get('priority_bucket')} {row.get('ticker')} {row.get('trade_date')} "
            f"{row.get('event_prototype')} reason={row.get('local_price_missing_reason')} score={row.get('priority_score')} "
            f"occurrences={row.get('occurrence_count')} tags={tags}"
        )
    lines.append("")
    return "\n".join(lines)


def _stdout_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": manifest.get("generated_at"),
        "reports_root": manifest.get("reports_root"),
        "report_name_contains": manifest.get("report_name_contains"),
        "row_count": manifest.get("row_count"),
        "scoped_row_count": manifest.get("scoped_row_count"),
        "scoped_missing_count": manifest.get("scoped_missing_count"),
        "manifest_occurrence_count": manifest.get("manifest_occurrence_count"),
        "manifest_row_count": manifest.get("manifest_row_count"),
        "missing_reason_counts": manifest.get("missing_reason_counts"),
        "event_prototype_counts": manifest.get("event_prototype_counts"),
        "priority_bucket_counts": manifest.get("priority_bucket_counts"),
        "output_json": None,
        "output_md": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a scoped missing local price manifest for BTST 5D/+15% trend/breakout validation.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument("--boundary-quarantine-artifact", default=str(DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT))
    parser.add_argument("--report-name-contains", default=DEFAULT_REPORT_NAME_CONTAINS)
    parser.add_argument("--top-fraction", type=float, default=DEFAULT_TOP_FRACTION)
    parser.add_argument("--max-rows", type=int, default=0, help="Limit JSON manifest rows. Use 0 to keep all scoped missing rows.")
    parser.add_argument("--markdown-row-limit", type=int, default=80)
    args = parser.parse_args()

    manifest = analyze_btst_5d_15pct_scoped_missing_price_manifest(
        args.reports_root,
        boundary_quarantine_artifact=args.boundary_quarantine_artifact,
        report_name_contains=args.report_name_contains,
        top_fraction=args.top_fraction,
        max_rows=args.max_rows,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_scoped_missing_price_manifest_markdown(manifest, row_limit=args.markdown_row_limit), encoding="utf-8")
    summary = _stdout_summary(manifest)
    summary["output_json"] = str(output_json)
    summary["output_md"] = str(output_md)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
