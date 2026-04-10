from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _parse_targets(raw: str) -> set[tuple[str, str]]:
    targets: set[tuple[str, str]] = set()
    for token in str(raw or "").split(","):
        normalized = token.strip()
        if not normalized:
            continue
        if ":" not in normalized:
            raise ValueError(f"Target must use trade_date:ticker format, got: {normalized}")
        trade_date, ticker = normalized.split(":", 1)
        targets.add((trade_date.strip(), ticker.strip()))
    return targets


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_selection_snapshots(selection_root: Path):
    for day_dir in sorted(path for path in selection_root.iterdir() if path.is_dir()):
        snapshot_path = day_dir / "selection_snapshot.json"
        if snapshot_path.exists():
            yield _load_json(snapshot_path)


def _round(value: float) -> float:
    return round(float(value), 4)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _resolve_default_thresholds(metrics_payload: dict[str, Any]) -> dict[str, float]:
    thresholds = dict(metrics_payload.get("thresholds") or {})
    return {
        "select_threshold": _safe_float(thresholds.get("select_threshold"), 0.58),
        "near_miss_threshold": _safe_float(thresholds.get("near_miss_threshold"), 0.46),
        "stale_score_penalty_weight": _safe_float(thresholds.get("stale_score_penalty_weight"), 0.12),
        "overhead_score_penalty_weight": _safe_float(thresholds.get("overhead_score_penalty_weight"), 0.10),
        "extension_score_penalty_weight": _safe_float(thresholds.get("extension_score_penalty_weight"), 0.08),
        "layer_c_avoid_penalty": _safe_float(thresholds.get("layer_c_avoid_penalty"), 0.12),
    }


def _compute_replayed_score(
    metrics_payload: dict[str, Any],
    *,
    stale_weight: float,
    overhead_weight: float,
    extension_weight: float,
    avoid_weight: float,
) -> float:
    total_positive = _safe_float(metrics_payload.get("total_positive_contribution"))
    stale_penalty = _safe_float(metrics_payload.get("stale_trend_repair_penalty")) * stale_weight
    overhead_penalty = _safe_float(metrics_payload.get("overhead_supply_penalty")) * overhead_weight
    extension_penalty = _safe_float(metrics_payload.get("extension_without_room_penalty")) * extension_weight
    avoid_penalty = _safe_float(metrics_payload.get("layer_c_avoid_penalty")) * avoid_weight
    return total_positive - stale_penalty - overhead_penalty - extension_penalty - avoid_penalty


def _evaluate_after_snapshot(
    metrics_payload: dict[str, Any],
    *,
    select_threshold: float,
    stale_weight: float,
    extension_weight: float,
) -> dict[str, Any]:
    default_thresholds = _resolve_default_thresholds(metrics_payload)
    replayed_score = _compute_replayed_score(
        metrics_payload,
        stale_weight=stale_weight,
        overhead_weight=default_thresholds["overhead_score_penalty_weight"],
        extension_weight=extension_weight,
        avoid_weight=default_thresholds["layer_c_avoid_penalty"],
    )
    breakout_freshness = _safe_float(metrics_payload.get("breakout_freshness"))
    trend_acceleration = _safe_float(metrics_payload.get("trend_acceleration"))
    if replayed_score >= select_threshold and breakout_freshness >= 0.35 and trend_acceleration >= 0.38:
        decision = "selected"
    elif replayed_score >= default_thresholds["near_miss_threshold"]:
        decision = "near_miss"
    else:
        decision = "rejected"
    return {
        "decision": decision,
        "score_target": _round(replayed_score),
        "select_threshold": _round(select_threshold),
        "stale_weight": _round(stale_weight),
        "extension_weight": _round(extension_weight),
    }


def render_targeted_short_trade_near_miss_release_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Targeted Short Trade Near-Miss Release Review")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- targets: {analysis['targets']}")
    lines.append(f"- total_case_count: {analysis['total_case_count']}")
    lines.append(f"- changed_case_count: {analysis['changed_case_count']}")
    lines.append(f"- changed_non_target_case_count: {analysis['changed_non_target_case_count']}")
    lines.append("")
    lines.append("## Transitions")
    lines.append(f"- before: {analysis['before_decision_counts']}")
    lines.append(f"- after: {analysis['after_decision_counts']}")
    lines.append(f"- transitions: {analysis['decision_transition_counts']}")
    lines.append("")
    lines.append("## Changed Cases")
    for row in analysis["changed_cases"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: {row['before_decision']} -> {row['after_decision']}, before_score={row['before_score_target']}, after_score={row['after_score_target']}, target_case={row['is_target_case']}"
        )
    if not analysis["changed_cases"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def _collect_near_miss_release_changes(
    selection_root: Path,
    *,
    targets: set[tuple[str, str]],
    select_threshold: float,
    stale_weight: float,
    extension_weight: float,
) -> tuple[Counter[str], Counter[str], Counter[str], list[dict[str, Any]], set[tuple[str, str]], int]:
    before_decision_counts: Counter[str] = Counter()
    after_decision_counts: Counter[str] = Counter()
    transition_counts: Counter[str] = Counter()
    changed_cases: list[dict[str, Any]] = []
    matched_targets: set[tuple[str, str]] = set()
    total_case_count = 0
    for snapshot in _iter_selection_snapshots(selection_root):
        snapshot_counts = _process_near_miss_release_snapshot(
            snapshot,
            targets=targets,
            select_threshold=select_threshold,
            stale_weight=stale_weight,
            extension_weight=extension_weight,
        )
        before_decision_counts.update(snapshot_counts["before_decision_counts"])
        after_decision_counts.update(snapshot_counts["after_decision_counts"])
        transition_counts.update(snapshot_counts["transition_counts"])
        changed_cases.extend(snapshot_counts["changed_cases"])
        matched_targets.update(snapshot_counts["matched_targets"])
        total_case_count += int(snapshot_counts["total_case_count"])
    return before_decision_counts, after_decision_counts, transition_counts, changed_cases, matched_targets, total_case_count


def _process_near_miss_release_snapshot(
    snapshot: dict[str, Any],
    *,
    targets: set[tuple[str, str]],
    select_threshold: float,
    stale_weight: float,
    extension_weight: float,
) -> dict[str, Any]:
    before_decision_counts: Counter[str] = Counter()
    after_decision_counts: Counter[str] = Counter()
    transition_counts: Counter[str] = Counter()
    changed_cases: list[dict[str, Any]] = []
    matched_targets: set[tuple[str, str]] = set()
    total_case_count = 0
    trade_date = str(snapshot.get("trade_date") or "")
    selection_targets = dict(snapshot.get("selection_targets") or {})
    for ticker, evaluation in selection_targets.items():
        case_update = _process_near_miss_release_case(
            trade_date=trade_date,
            ticker=str(ticker),
            evaluation=dict(evaluation or {}),
            targets=targets,
            select_threshold=select_threshold,
            stale_weight=stale_weight,
            extension_weight=extension_weight,
        )
        if case_update is None:
            continue
        total_case_count += 1
        before_decision_counts.update([case_update["before_decision"]])
        after_decision_counts.update([case_update["after_decision"]])
        transition_counts.update([f"{case_update['before_decision']}->{case_update['after_decision']}"])
        if case_update["is_target_case"]:
            matched_targets.add((trade_date, str(ticker)))
        if case_update["changed_case"] is not None:
            changed_cases.append(case_update["changed_case"])
    return {
        "before_decision_counts": before_decision_counts,
        "after_decision_counts": after_decision_counts,
        "transition_counts": transition_counts,
        "changed_cases": changed_cases,
        "matched_targets": matched_targets,
        "total_case_count": total_case_count,
    }


def _process_near_miss_release_case(
    *,
    trade_date: str,
    ticker: str,
    evaluation: dict[str, Any],
    targets: set[tuple[str, str]],
    select_threshold: float,
    stale_weight: float,
    extension_weight: float,
) -> dict[str, Any] | None:
    candidate_source = str(evaluation.get("candidate_source") or "")
    short_trade = dict(evaluation.get("short_trade") or {})
    if candidate_source != "short_trade_boundary":
        return None
    if str(short_trade.get("decision") or "") != "near_miss":
        return None
    case_key = (trade_date, ticker)
    is_target_case = case_key in targets
    before_decision = "near_miss"
    before_score = _round(_safe_float(short_trade.get("score_target")))
    after_snapshot = {
        "decision": before_decision,
        "score_target": before_score,
        "select_threshold": _round(select_threshold),
        "stale_weight": _round(stale_weight),
        "extension_weight": _round(extension_weight),
    }
    if is_target_case:
        after_snapshot = _evaluate_after_snapshot(
            dict(short_trade.get("metrics_payload") or {}),
            select_threshold=select_threshold,
            stale_weight=stale_weight,
            extension_weight=extension_weight,
        )
    after_decision = str(after_snapshot.get("decision") or before_decision)
    changed_case = None
    if before_decision != after_decision or before_score != after_snapshot.get("score_target"):
        changed_case = {
            "trade_date": trade_date,
            "ticker": ticker,
            "is_target_case": is_target_case,
            "before_decision": before_decision,
            "after_decision": after_decision,
            "before_score_target": before_score,
            "after_score_target": after_snapshot.get("score_target"),
            "select_threshold": after_snapshot.get("select_threshold"),
            "stale_weight": after_snapshot.get("stale_weight"),
            "extension_weight": after_snapshot.get("extension_weight"),
        }
    return {
        "is_target_case": is_target_case,
        "before_decision": before_decision,
        "after_decision": after_decision,
        "changed_case": changed_case,
    }


def _build_near_miss_release_recommendation(
    promoted_target_rows: list[dict[str, Any]],
    changed_non_target_case_count: int,
) -> str:
    if promoted_target_rows and changed_non_target_case_count == 0:
        target_descriptions = ", ".join(f"{row['trade_date']} / {row['ticker']}" for row in promoted_target_rows)
        return (
            f"当前定向 release 只改变目标 near-miss 样本。{target_descriptions} 从 near_miss -> selected，"
            f"可作为低污染的 case-based near-miss promotion 实验。"
        )
    if changed_non_target_case_count > 0:
        return "出现了非目标 near-miss 样本变化，当前实验不再是严格的 case-based promotion。"
    return "目标 near-miss 样本没有进入 selected，当前 release 参数还不够强。"


def analyze_targeted_short_trade_near_miss_release(
    report_dir: str | Path,
    *,
    targets: set[tuple[str, str]],
    select_threshold: float,
    stale_weight: float,
    extension_weight: float,
) -> dict[str, Any]:
    report_path = Path(report_dir).expanduser().resolve()
    selection_root = report_path / "selection_artifacts"
    before_decision_counts, after_decision_counts, transition_counts, changed_cases, matched_targets, total_case_count = _collect_near_miss_release_changes(
        selection_root,
        targets=targets,
        select_threshold=select_threshold,
        stale_weight=stale_weight,
        extension_weight=extension_weight,
    )

    unmatched_targets = sorted(f"{trade_date}:{ticker}" for trade_date, ticker in (targets - matched_targets))
    if unmatched_targets:
        raise ValueError(f"Targets not found in near_miss short_trade_boundary rows: {', '.join(unmatched_targets)}")

    changed_non_target_case_count = sum(1 for row in changed_cases if not row["is_target_case"])
    promoted_target_rows = [row for row in changed_cases if row["is_target_case"] and row["after_decision"] == "selected"]
    recommendation = _build_near_miss_release_recommendation(promoted_target_rows, changed_non_target_case_count)

    return {
        "report_dir": str(report_path),
        "targets": sorted(f"{trade_date}:{ticker}" for trade_date, ticker in targets),
        "select_threshold": _round(select_threshold),
        "stale_weight": _round(stale_weight),
        "extension_weight": _round(extension_weight),
        "total_case_count": total_case_count,
        "changed_case_count": len(changed_cases),
        "changed_non_target_case_count": changed_non_target_case_count,
        "before_decision_counts": dict(before_decision_counts.most_common()),
        "after_decision_counts": dict(after_decision_counts.most_common()),
        "decision_transition_counts": dict(transition_counts.most_common()),
        "changed_cases": changed_cases,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a case-based release experiment on near_miss short_trade_boundary candidates.")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--targets", required=True, help="Comma-separated trade_date:ticker targets")
    parser.add_argument("--select-threshold", type=float, required=True)
    parser.add_argument("--stale-weight", type=float, required=True)
    parser.add_argument("--extension-weight", type=float, required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_targeted_short_trade_near_miss_release(
        args.report_dir,
        targets=_parse_targets(args.targets),
        select_threshold=float(args.select_threshold),
        stale_weight=float(args.stale_weight),
        extension_weight=float(args.extension_weight),
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_targeted_short_trade_near_miss_release_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
