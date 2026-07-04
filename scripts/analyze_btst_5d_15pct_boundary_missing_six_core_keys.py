from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.analyze_btst_5d_15pct_boundary_contract_inspection import (
    analyze_btst_5d_15pct_boundary_contract_inspection,
)
from scripts.btst_boundary_missing_core_key_trace_helpers import (
    BOUNDARY_TRACE_KEYS,
    summarize_boundary_key_trace_statuses,
)

MISSING_SIX_CORE_KEYS = tuple(key for key in BOUNDARY_TRACE_KEYS if key != "t0_tail_strength")
REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_5d_15pct_boundary_missing_six_core_keys_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_5d_15pct_boundary_missing_six_core_keys_latest.md"
_SOURCE_PAYLOAD_ALIASES = (
    "source_payload",
    "candidate_source_payload",
    "source_entry",
    "replay_input_source_entry",
    "selection_target_replay_input_source_entry",
)
_ATTACHED_TARGET_ALIASES = (
    "attached_target",
    "replay_input_target",
    "selection_target_replay_input_target",
)
_SNAPSHOT_TARGET_ALIASES = (
    "snapshot_target",
    "selection_snapshot_target",
)
_GOVERNANCE_PRIORITY = (
    "fix_boundary_source_contract",
    "fix_snapshot_attachment_contract",
    "hold_boundary_until_more_context",
)
_REPLAY_INPUT_SOURCE_BUCKETS = (
    "supplemental_short_trade_entries",
    "watchlist",
    "rejected_entries",
    "upstream_shadow_observation_entries",
    "supplemental_catalyst_theme_entries",
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _trade_date_path_candidates(trade_date: str) -> list[str]:
    normalized = str(trade_date or "").strip()
    digits_only = normalized.replace("-", "")
    candidates: list[str] = []
    for value in (
        normalized,
        f"{digits_only[:4]}-{digits_only[4:6]}-{digits_only[6:]}" if len(digits_only) == 8 else "",
        digits_only,
    ):
        if value and value not in candidates:
            candidates.append(value)
    return candidates


def _resolve_selection_artifact_dir(*, reports_root: Path, report_dir_name: str, trade_date: str) -> Path:
    base_dir = reports_root / report_dir_name / "selection_artifacts"
    candidates = [base_dir / candidate for candidate in _trade_date_path_candidates(trade_date)]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Selection artifact directory not found for report={report_dir_name} trade_date={trade_date}: " f"{', '.join(str(candidate) for candidate in candidates)}")


def _iter_replay_input_candidates(replay_input: dict[str, Any], ticker: str) -> list[tuple[str, dict[str, Any]]]:
    matches: list[tuple[str, dict[str, Any]]] = []
    normalized_ticker = str(ticker or "")
    for bucket in _REPLAY_INPUT_SOURCE_BUCKETS:
        for entry in list(replay_input.get(bucket) or []):
            payload = dict(entry or {})
            if str(payload.get("ticker") or "") == normalized_ticker:
                matches.append((bucket, payload))
    return matches


def _locate_replay_input_source_entry(replay_input: dict[str, Any], *, ticker: str, candidate_source: str) -> tuple[str | None, dict[str, Any]]:
    matches = _iter_replay_input_candidates(replay_input, ticker)
    if not matches:
        return None, {}

    normalized_candidate_source = str(candidate_source or "")
    exact_matches = [(bucket, payload) for bucket, payload in matches if str(payload.get("candidate_source") or "") == normalized_candidate_source]
    if exact_matches:
        return exact_matches[0][0], exact_matches[0][1]

    upstream_matches = [(bucket, payload) for bucket, payload in matches if str(payload.get("upstream_candidate_source") or "") == normalized_candidate_source]
    if upstream_matches:
        return upstream_matches[0][0], upstream_matches[0][1]

    return None, {}


def _lookup_selection_target(payload: dict[str, Any], ticker: str) -> dict[str, Any]:
    return dict(dict(payload.get("selection_targets") or {}).get(str(ticker)) or {})


def _reconstruct_boundary_trace_row(boundary_row: dict[str, Any], reports_root: Path) -> dict[str, Any]:
    trade_date = str(boundary_row.get("trade_date") or "")
    ticker = str(boundary_row.get("ticker") or "")
    candidate_source = str(boundary_row.get("candidate_source") or "")
    report_dir_name = str(boundary_row.get("report_dir_name") or "")
    if not report_dir_name:
        raise ValueError(f"Boundary row missing report_dir_name: {boundary_row}")
    if not trade_date or not ticker:
        raise ValueError(f"Boundary row missing trade_date/ticker: {boundary_row}")

    artifact_dir = _resolve_selection_artifact_dir(
        reports_root=reports_root,
        report_dir_name=report_dir_name,
        trade_date=trade_date,
    )
    replay_input = _load_json(artifact_dir / "selection_target_replay_input.json")
    snapshot = _load_json(artifact_dir / "selection_snapshot.json")
    source_bucket, source_entry = _locate_replay_input_source_entry(
        replay_input,
        ticker=ticker,
        candidate_source=candidate_source,
    )
    attached_target = _lookup_selection_target(replay_input, ticker)
    snapshot_target = _lookup_selection_target(snapshot, ticker)
    if not snapshot_target:
        raise ValueError(f"Ticker {ticker} missing from selection_snapshot.json under {artifact_dir}")
    if not attached_target:
        attached_target = dict(snapshot_target)
    source_payload = {
        **dict(source_entry),
        "ticker": ticker,
        "candidate_source": candidate_source or str(source_entry.get("candidate_source") or ""),
    }
    return {
        "report_dir_name": report_dir_name,
        "trade_date": trade_date,
        "ticker": ticker,
        "candidate_source": candidate_source,
        "source_bucket": source_bucket,
        "source_payload": source_payload,
        "attached_target": attached_target,
        "snapshot_target": snapshot_target,
    }


def _first_dict(row: dict[str, Any], aliases: tuple[str, ...]) -> dict[str, Any]:
    for alias in aliases:
        payload = row.get(alias)
        if isinstance(payload, dict):
            return dict(payload)
    return {}


def _extract_source_payload(row: dict[str, Any]) -> dict[str, Any]:
    source_entry = _first_dict(row, _SOURCE_PAYLOAD_ALIASES)
    boundary_metrics_payload = dict(source_entry.get("short_trade_boundary_metrics") or {})
    metrics = dict(source_entry.get("metrics") or {})
    metrics_payload = dict(source_entry.get("metrics_payload") or {})
    payload: dict[str, Any] = {}
    for key in BOUNDARY_TRACE_KEYS:
        for layer in (source_entry, boundary_metrics_payload, metrics, metrics_payload):
            value = layer.get(key)
            if value is not None:
                payload[key] = value
                break
    return payload


def _extract_target(row: dict[str, Any], aliases: tuple[str, ...]) -> dict[str, Any]:
    return _first_dict(row, aliases)


def _extract_surface_payload(target: dict[str, Any]) -> dict[str, Any]:
    short_trade = dict(target.get("short_trade") or {})
    explainability_payload = dict(short_trade.get("explainability_payload") or {})
    payload: dict[str, Any] = {}
    for key in BOUNDARY_TRACE_KEYS:
        for layer in (explainability_payload, short_trade, target):
            value = layer.get(key)
            if value is not None:
                payload[key] = value
                break
    return payload


def _extract_nested_metrics_payload(target: dict[str, Any]) -> dict[str, Any]:
    metrics_payload = dict(dict(target.get("short_trade") or {}).get("metrics_payload") or {})
    return {key: metrics_payload[key] for key in BOUNDARY_TRACE_KEYS if metrics_payload.get(key) is not None}


def _has_key(payload: dict[str, Any], key: str) -> bool:
    return payload.get(key) is not None


def _diagnose_missing_six_key(
    *,
    key: str,
    source_payload: dict[str, Any],
    attached_surface_payload: dict[str, Any],
    attached_metrics_payload: dict[str, Any],
    snapshot_surface_payload: dict[str, Any],
    snapshot_metrics_payload: dict[str, Any],
) -> str:
    attached_surface_has = _has_key(attached_surface_payload, key)
    snapshot_surface_has = _has_key(snapshot_surface_payload, key)
    attached_metrics_has = _has_key(attached_metrics_payload, key)
    snapshot_metrics_has = _has_key(snapshot_metrics_payload, key)
    source_has = _has_key(source_payload, key)

    if attached_surface_has or snapshot_surface_has:
        return "surface_visible"
    if attached_metrics_has or snapshot_metrics_has:
        return "nested_only"
    if not source_has:
        return "missing_everywhere"
    if source_has:
        return "lost_after_source"
    return "inconclusive"


def _governance_action_from_counts(counts: dict[str, int]) -> str:
    if counts.get("missing_everywhere", 0) > 0:
        return "fix_boundary_source_contract"
    if counts.get("nested_only", 0) > 0 or counts.get("lost_after_source", 0) > 0:
        return "fix_snapshot_attachment_contract"
    return "hold_boundary_until_more_context"


def _normalize_row_trace(row: dict[str, Any]) -> dict[str, Any]:
    source_payload = _extract_source_payload(row)
    attached_target = _extract_target(row, _ATTACHED_TARGET_ALIASES)
    snapshot_target = _extract_target(row, _SNAPSHOT_TARGET_ALIASES)
    attached_surface_payload = _extract_surface_payload(attached_target)
    attached_metrics_payload = _extract_nested_metrics_payload(attached_target)
    snapshot_surface_payload = _extract_surface_payload(snapshot_target)
    snapshot_metrics_payload = _extract_nested_metrics_payload(snapshot_target)
    surface_trace_summary = summarize_boundary_key_trace_statuses(
        source_payload=source_payload,
        attached_target=attached_surface_payload,
        snapshot_target=snapshot_surface_payload,
    )
    missing_six_diagnoses = {
        key: _diagnose_missing_six_key(
            key=key,
            source_payload=source_payload,
            attached_surface_payload=attached_surface_payload,
            attached_metrics_payload=attached_metrics_payload,
            snapshot_surface_payload=snapshot_surface_payload,
            snapshot_metrics_payload=snapshot_metrics_payload,
        )
        for key in MISSING_SIX_CORE_KEYS
    }
    diagnosis_counts = Counter(missing_six_diagnoses.values())
    governance_action = _governance_action_from_counts(dict(diagnosis_counts))
    return {
        "candidate_source": str(row.get("candidate_source") or attached_target.get("candidate_source") or snapshot_target.get("candidate_source") or "unknown"),
        "ticker": str(row.get("ticker") or attached_target.get("ticker") or snapshot_target.get("ticker") or ""),
        "trade_date": str(row.get("trade_date") or ""),
        "surface_trace_status_counts": dict(surface_trace_summary["status_counts"]),
        "surface_trace_statuses": dict(surface_trace_summary["key_trace_statuses"]),
        "nested_only_missing_six_keys": [key for key in MISSING_SIX_CORE_KEYS if missing_six_diagnoses[key] == "nested_only"],
        "missing_everywhere_missing_six_keys": [key for key in MISSING_SIX_CORE_KEYS if missing_six_diagnoses[key] == "missing_everywhere"],
        "surface_visible_keys": [key for key in BOUNDARY_TRACE_KEYS if _has_key(attached_surface_payload, key) or _has_key(snapshot_surface_payload, key)],
        "missing_six_key_diagnoses": missing_six_diagnoses,
        "governance_action": governance_action,
        "source_payload": source_payload,
        "attached_surface_payload": attached_surface_payload,
        "attached_metrics_payload": attached_metrics_payload,
        "snapshot_surface_payload": snapshot_surface_payload,
        "snapshot_metrics_payload": snapshot_metrics_payload,
    }


def _build_key_trace_summary_board(row_traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    surface_status_counts: Counter[str] = Counter()
    diagnosis_counts: Counter[str] = Counter()
    for row_trace in row_traces:
        surface_status_counts.update(dict(row_trace["surface_trace_status_counts"]))
        diagnosis_counts.update(dict(Counter(dict(row_trace["missing_six_key_diagnoses"]).values())))
    return [
        {
            "row_count": len(row_traces),
            "surface_trace_status_counts": dict(surface_status_counts),
            "missing_six_key_diagnosis_counts": {
                "nested_only": diagnosis_counts.get("nested_only", 0),
                "missing_everywhere": diagnosis_counts.get("missing_everywhere", 0),
                "surface_visible": diagnosis_counts.get("surface_visible", 0),
                "lost_after_source": diagnosis_counts.get("lost_after_source", 0),
                "inconclusive": diagnosis_counts.get("inconclusive", 0),
            },
        }
    ]


def _build_boundary_source_trace_board(row_traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row_trace in row_traces:
        source_groups[str(row_trace["candidate_source"])].append(row_trace)

    board: list[dict[str, Any]] = []
    for candidate_source, source_rows in source_groups.items():
        diagnosis_counts: Counter[str] = Counter()
        for row_trace in source_rows:
            diagnosis_counts.update(dict(Counter(dict(row_trace["missing_six_key_diagnoses"]).values())))
        board.append(
            {
                "candidate_source": candidate_source,
                "row_count": len(source_rows),
                "nested_only_missing_six_key_count": diagnosis_counts.get("nested_only", 0),
                "missing_everywhere_missing_six_key_count": diagnosis_counts.get("missing_everywhere", 0),
                "surface_visible_missing_six_key_count": diagnosis_counts.get("surface_visible", 0),
                "lost_after_source_missing_six_key_count": diagnosis_counts.get("lost_after_source", 0),
                "inconclusive_missing_six_key_count": diagnosis_counts.get("inconclusive", 0),
                "governance_action": _governance_action_from_counts(dict(diagnosis_counts)),
            }
        )
    return sorted(board, key=lambda current: (-int(current["row_count"]), str(current["candidate_source"])))


def _build_survivor_key_contrast_board(row_traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    board: list[dict[str, Any]] = []
    for key in BOUNDARY_TRACE_KEYS:
        board.append(
            {
                "key": key,
                "source_payload_count": sum(1 for row_trace in row_traces if _has_key(dict(row_trace["source_payload"]), key)),
                "attached_metrics_payload_count": sum(1 for row_trace in row_traces if _has_key(dict(row_trace["attached_metrics_payload"]), key)),
                "attached_surface_payload_count": sum(1 for row_trace in row_traces if _has_key(dict(row_trace["attached_surface_payload"]), key)),
                "snapshot_metrics_payload_count": sum(1 for row_trace in row_traces if _has_key(dict(row_trace["snapshot_metrics_payload"]), key)),
                "snapshot_surface_payload_count": sum(1 for row_trace in row_traces if _has_key(dict(row_trace["snapshot_surface_payload"]), key)),
            }
        )
    return board


def _build_governance_diagnosis_board(row_traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row_trace in row_traces:
        grouped[str(row_trace["governance_action"])].append(row_trace)

    board: list[dict[str, Any]] = []
    for action in _GOVERNANCE_PRIORITY:
        action_rows = grouped.get(action) or []
        if not action_rows:
            continue
        affected_keys: set[str] = set()
        for row_trace in action_rows:
            if action == "fix_snapshot_attachment_contract":
                diagnoses = dict(row_trace["missing_six_key_diagnoses"])
                affected_keys.update(key for key, diagnosis in diagnoses.items() if diagnosis in {"nested_only", "lost_after_source"})
            elif action == "fix_boundary_source_contract":
                affected_keys.update(row_trace["missing_everywhere_missing_six_keys"])
            else:
                diagnoses = dict(row_trace["missing_six_key_diagnoses"])
                affected_keys.update(key for key, diagnosis in diagnoses.items() if diagnosis in {"lost_after_source", "inconclusive"})
        board.append(
            {
                "action": action,
                "row_count": len(action_rows),
                "tickers": sorted(str(row_trace["ticker"]) for row_trace in action_rows),
                "affected_keys": [key for key in MISSING_SIX_CORE_KEYS if key in affected_keys],
            }
        )
    return board


def analyze_btst_5d_15pct_boundary_missing_six_core_keys_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    row_traces = sorted(
        (_normalize_row_trace(row) for row in rows),
        key=lambda current: (str(current["trade_date"]), str(current["ticker"]), str(current["candidate_source"])),
    )
    trace_status_board = [
        {
            "candidate_source": row_trace["candidate_source"],
            "ticker": row_trace["ticker"],
            "trade_date": row_trace["trade_date"],
            "surface_trace_status_counts": row_trace["surface_trace_status_counts"],
            "surface_trace_statuses": row_trace["surface_trace_statuses"],
            "nested_only_missing_six_keys": row_trace["nested_only_missing_six_keys"],
            "missing_everywhere_missing_six_keys": row_trace["missing_everywhere_missing_six_keys"],
            "surface_visible_keys": row_trace["surface_visible_keys"],
            "governance_action": row_trace["governance_action"],
        }
        for row_trace in row_traces
    ]
    return {
        "boundary_row_count": len(row_traces),
        "trace_status_board": trace_status_board,
        "key_trace_summary_board": _build_key_trace_summary_board(row_traces),
        "boundary_source_trace_board": _build_boundary_source_trace_board(row_traces),
        "survivor_key_contrast_board": _build_survivor_key_contrast_board(row_traces),
        "governance_diagnosis_board": _build_governance_diagnosis_board(row_traces),
    }


def analyze_btst_5d_15pct_boundary_missing_six_core_keys(reports_root: str | Path) -> dict[str, Any]:
    resolved_root = Path(reports_root).expanduser().resolve()
    inspection = analyze_btst_5d_15pct_boundary_contract_inspection(resolved_root)
    live_rows = [_reconstruct_boundary_trace_row(dict(row or {}), resolved_root) for row in list(inspection.get("boundary_rows") or [])]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        **analyze_btst_5d_15pct_boundary_missing_six_core_keys_from_rows(live_rows),
    }


def _render_markdown_board(title: str, rows: list[dict[str, Any]]) -> list[str]:
    lines = [f"## {title}"]
    if not rows:
        lines.extend(["- none", ""])
        return lines
    for row in rows:
        parts = [f"{key}={row[key]}" for key in row]
        lines.append(f"- {', '.join(parts)}")
    lines.append("")
    return lines


def render_btst_5d_15pct_boundary_missing_six_core_keys_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST 5D / +15% Boundary Missing Six Core Keys",
        "",
        f"- generated_at: {analysis.get('generated_at')}",
        f"- reports_root: {analysis.get('reports_root')}",
        f"- boundary_row_count: {analysis.get('boundary_row_count')}",
        "",
    ]
    for board_name in (
        "key_trace_summary_board",
        "boundary_source_trace_board",
        "survivor_key_contrast_board",
        "governance_diagnosis_board",
    ):
        lines.extend(_render_markdown_board(board_name, list(analysis.get(board_name) or [])))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the BTST 5D/+15% boundary missing-six core key trace artifact.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_5d_15pct_boundary_missing_six_core_keys(args.reports_root)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(
        render_btst_5d_15pct_boundary_missing_six_core_keys_markdown(analysis),
        encoding="utf-8",
    )
    print("boundary_missing_six_core_keys: " f"boundary_row_count={analysis['boundary_row_count']} " f"json={output_json} md={output_md}")


if __name__ == "__main__":
    main()
