from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.execution.models import LayerCResult
from src.targets.short_trade_target import evaluate_short_trade_rejected_target, evaluate_short_trade_selected_target


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _parse_profile_overrides(raw: str | None) -> dict[str, Any]:
    if raw is None or not str(raw).strip():
        return {}
    payload = json.loads(str(raw))
    if not isinstance(payload, dict):
        raise ValueError("Profile overrides JSON must decode to an object.")
    return dict(payload)


def _load_replay_input(report_dir: Path, trade_date: str) -> dict[str, Any]:
    replay_input_path = report_dir / "selection_artifacts" / trade_date / "selection_target_replay_input.json"
    return _load_json(replay_input_path)


def _locate_entry(replay_input: dict[str, Any], ticker: str) -> tuple[str, dict[str, Any]]:
    for entry in list(replay_input.get("watchlist") or []):
        if str(entry.get("ticker") or "") == ticker:
            return "watchlist", dict(entry)
    for entry in list(replay_input.get("rejected_entries") or []):
        if str(entry.get("ticker") or "") == ticker:
            return "rejected_entries", dict(entry)
    for entry in list(replay_input.get("supplemental_short_trade_entries") or []):
        if str(entry.get("ticker") or "") == ticker:
            return "supplemental_short_trade_entries", dict(entry)
    raise ValueError(f"Ticker not found in replay input: {ticker}")


def _evaluate_target_case(
    *,
    trade_date: str,
    source_bucket: str,
    entry: dict[str, Any],
    buy_order_tickers: set[str],
    profile_overrides: dict[str, Any],
) -> dict[str, Any]:
    if source_bucket == "watchlist":
        item = LayerCResult.model_validate(entry)
        result = evaluate_short_trade_selected_target(
            trade_date=trade_date,
            item=item,
            included_in_buy_orders=item.ticker in buy_order_tickers,
            profile_overrides=profile_overrides,
        )
    else:
        result = evaluate_short_trade_rejected_target(
            trade_date=trade_date,
            entry=entry,
            profile_overrides=profile_overrides,
        )

    metrics_payload = dict(result.metrics_payload or {})
    thresholds = dict(metrics_payload.get("thresholds") or {})
    return {
        "decision": result.decision,
        "score_target": round(float(result.score_target), 4),
        "blockers": list(result.blockers or []),
        "top_reasons": list(result.top_reasons or []),
        "thresholds": thresholds,
    }


def render_targeted_structural_conflict_release_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Targeted Structural Conflict Release Review")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- targets: {analysis['targets']}")
    lines.append(f"- profile_overrides: {analysis['profile_overrides']}")
    lines.append(f"- total_case_count: {analysis['total_case_count']}")
    lines.append(f"- matched_target_case_count: {analysis['matched_target_case_count']}")
    lines.append(f"- changed_case_count: {analysis['changed_case_count']}")
    lines.append("")
    lines.append("## Decision Counts")
    lines.append(f"- before: {analysis['before_decision_counts']}")
    lines.append(f"- after: {analysis['after_decision_counts']}")
    lines.append(f"- transitions: {analysis['decision_transition_counts']}")
    lines.append("")
    lines.append("## Changed Cases")
    for row in analysis["changed_cases"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: {row['before_decision']} -> {row['after_decision']}, before_score={row['before_score_target']}, after_score={row['after_score_target']}, target_case={row['is_target_case']}, candidate_source={row['candidate_source']}"
        )
    if not analysis["changed_cases"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_targeted_structural_conflict_release(
    report_dir: str | Path,
    *,
    targets: set[tuple[str, str]],
    profile_overrides: dict[str, Any],
) -> dict[str, Any]:
    report_path = Path(report_dir).expanduser().resolve()
    selection_root = report_path / "selection_artifacts"
    before_decision_counts: Counter[str] = Counter()
    after_decision_counts: Counter[str] = Counter()
    transition_counts: Counter[str] = Counter()
    changed_cases: list[dict[str, Any]] = []
    per_trade_date: list[dict[str, Any]] = []
    replay_input_cache: dict[str, dict[str, Any]] = {}
    matched_targets: set[tuple[str, str]] = set()
    total_case_count = 0

    for day_dir in sorted(path for path in selection_root.iterdir() if path.is_dir()):
        snapshot_path = day_dir / "selection_snapshot.json"
        if not snapshot_path.exists():
            continue
        snapshot = _load_json(snapshot_path)
        trade_date = str(snapshot.get("trade_date") or day_dir.name)
        day_before: Counter[str] = Counter()
        day_after: Counter[str] = Counter()
        selection_targets = dict(snapshot.get("selection_targets") or {})

        for ticker, evaluation in selection_targets.items():
            total_case_count += 1
            normalized_ticker = str(ticker)
            normalized_evaluation = dict(evaluation or {})
            short_trade = dict(normalized_evaluation.get("short_trade") or {})
            candidate_source = str(normalized_evaluation.get("candidate_source") or "unknown")
            before_decision = str(short_trade.get("decision") or "none")
            before_score = short_trade.get("score_target")
            case_key = (trade_date, normalized_ticker)
            is_target_case = case_key in targets
            after_snapshot = {
                "decision": before_decision,
                "score_target": before_score,
                "blockers": list(short_trade.get("blockers") or []),
                "top_reasons": list(short_trade.get("top_reasons") or []),
                "thresholds": dict(short_trade.get("thresholds") or {}),
            }
            source_bucket = None

            if is_target_case:
                replay_input = replay_input_cache.get(trade_date)
                if replay_input is None:
                    replay_input = _load_replay_input(report_path, trade_date)
                    replay_input_cache[trade_date] = replay_input
                source_bucket, entry = _locate_entry(replay_input, normalized_ticker)
                after_snapshot = _evaluate_target_case(
                    trade_date=trade_date,
                    source_bucket=source_bucket,
                    entry=entry,
                    buy_order_tickers={str(value) for value in list(replay_input.get("buy_order_tickers") or []) if str(value or "").strip()},
                    profile_overrides=profile_overrides,
                )
                matched_targets.add(case_key)

            after_decision = str(after_snapshot.get("decision") or "none")
            before_decision_counts[before_decision] += 1
            after_decision_counts[after_decision] += 1
            day_before[before_decision] += 1
            day_after[after_decision] += 1
            transition_counts[f"{before_decision}->{after_decision}"] += 1

            if before_decision != after_decision or before_score != after_snapshot.get("score_target"):
                changed_cases.append(
                    {
                        "trade_date": trade_date,
                        "ticker": normalized_ticker,
                        "candidate_source": candidate_source,
                        "source_bucket": source_bucket,
                        "is_target_case": is_target_case,
                        "before_decision": before_decision,
                        "after_decision": after_decision,
                        "before_score_target": before_score,
                        "after_score_target": after_snapshot.get("score_target"),
                        "before_blockers": list(short_trade.get("blockers") or []),
                        "after_blockers": list(after_snapshot.get("blockers") or []),
                        "after_top_reasons": list(after_snapshot.get("top_reasons") or []),
                    }
                )

        per_trade_date.append(
            {
                "trade_date": trade_date,
                "before_decision_counts": dict(day_before.most_common()),
                "after_decision_counts": dict(day_after.most_common()),
            }
        )

    unmatched_targets = sorted(f"{trade_date}:{ticker}" for trade_date, ticker in (targets - matched_targets))
    if unmatched_targets:
        raise ValueError(f"Targets not found in selection_snapshot.json: {', '.join(unmatched_targets)}")

    target_changed_cases = [row for row in changed_cases if row["is_target_case"]]
    non_target_changed_cases = [row for row in changed_cases if not row["is_target_case"]]

    if target_changed_cases and not non_target_changed_cases:
        promoted_rows = [row for row in target_changed_cases if row["after_decision"] in {"near_miss", "selected"}]
        if promoted_rows:
            head = promoted_rows[0]
            recommendation = (
                f"当前 case-based 定向释放只改变目标样本。{head['trade_date']} / {head['ticker']} 从 {head['before_decision']} -> {head['after_decision']}，"
                f"未污染其它 {total_case_count - len(target_changed_cases)} 个样本，可作为 300724-only 受控实验入口。"
            )
        else:
            recommendation = "目标样本被重新评估，但未进入 near_miss/selected；当前 overrides 不足以形成有效 release。"
    elif non_target_changed_cases:
        recommendation = "出现了非目标样本变化，当前实验语义不再是严格的 300724-only 受控释放。"
    else:
        recommendation = "目标样本未发生任何决策变化，当前定向 release 不值得继续推进。"

    return {
        "report_dir": str(report_path),
        "targets": sorted(f"{trade_date}:{ticker}" for trade_date, ticker in targets),
        "profile_overrides": dict(profile_overrides),
        "total_case_count": total_case_count,
        "matched_target_case_count": len(matched_targets),
        "changed_case_count": len(changed_cases),
        "before_decision_counts": dict(before_decision_counts.most_common()),
        "after_decision_counts": dict(after_decision_counts.most_common()),
        "decision_transition_counts": dict(transition_counts.most_common()),
        "changed_cases": changed_cases,
        "target_changed_cases": target_changed_cases,
        "non_target_changed_cases": non_target_changed_cases,
        "by_trade_date": per_trade_date,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a case-based targeted structural conflict release experiment.")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--targets", required=True, help="Comma-separated trade_date:ticker targets, e.g. 2026-03-25:300724")
    parser.add_argument("--profile-overrides-json", default="{}", help="JSON object passed as short-trade profile overrides")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_targeted_structural_conflict_release(
        args.report_dir,
        targets=_parse_targets(args.targets),
        profile_overrides=_parse_profile_overrides(args.profile_overrides_json),
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_targeted_structural_conflict_release_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()