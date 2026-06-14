from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_ROLLOUT_PACK_JSON = Path("data/reports/btst_momentum_rollout_recheck_pack.json")
DEFAULT_SOURCE_JSON = Path("data/reports/param_search_momentum_optimized_apr_may_coarse_v3.json")
DEFAULT_BASELINE_BRIDGE_JSON = Path("data/reports/btst_momentum_active_baseline_bridge.json")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_momentum_rollout_recheck_comparison.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_momentum_rollout_recheck_comparison.md")

REQUIRED_BRIDGE_METRICS = ("next_close_positive_rate", "next_close_payoff_ratio", "window_count")
GUARDRAILS = ("no_manifest_publication", "no_btst_skill_promotion")


def _load_json_file(path: Path, *, label: str) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SystemExit(f"{label} file not found: {path}") from exc
    except OSError as exc:
        raise SystemExit(f"unable to read {label} file: {path}") from exc

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {label} file: {path}") from exc


def _write_output_file(path: Path, *, content: str, label: str) -> None:
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"unable to write {label}: {path}") from exc


def _require_object(name: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SystemExit(f"{name} must be a JSON object.")
    return dict(payload)


def _require_list(name: str, payload: Any) -> list[Any]:
    if not isinstance(payload, list):
        raise SystemExit(f"{name} must be a JSON list.")
    return payload


def _require_non_negative_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SystemExit(f"{name} must be a non-negative integer.")
    return value


def _require_non_empty_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{name} must be a non-empty string.")
    return value.strip()


def _require_baseline_summary_field(baseline_summary: dict[str, Any], field_name: str) -> Any:
    value = baseline_summary.get(field_name)
    if value is None:
        raise SystemExit(f"baseline_summary.{field_name} must be present.")
    return value


def _index_results(results: Any) -> dict[int, dict[str, Any]]:
    indexed: dict[int, dict[str, Any]] = {}
    for row in _require_list("source_report.results", results):
        normalized_row = _require_object("source_report result", row)
        trial_index = _require_non_negative_int("source_report result trial_index", normalized_row.get("trial_index"))
        if trial_index in indexed:
            raise SystemExit("source_report.results must not contain duplicate trial_index values.")
        indexed[trial_index] = normalized_row
    return indexed


def _require_result_metrics(name: str, result_row: dict[str, Any]) -> dict[str, Any]:
    return _require_object(name, result_row.get("metrics"))


def _load_baseline_verdicts(normalized_source: dict[str, Any]) -> dict[str, Any]:
    baseline_verdicts = normalized_source.get("baseline_verdicts")
    if isinstance(baseline_verdicts, dict):
        return dict(baseline_verdicts)
    rollout_recommendation_details = normalized_source.get("rollout_recommendation_details")
    if isinstance(rollout_recommendation_details, dict):
        nested_baseline_verdicts = rollout_recommendation_details.get("baseline_verdicts")
        if isinstance(nested_baseline_verdicts, dict):
            return dict(nested_baseline_verdicts)
    raise SystemExit("baseline_verdicts must be a JSON object.")


def _require_baseline_bridge(payload: Any, *, active_baseline_name: str) -> dict[str, Any]:
    bridge = _require_object("baseline_bridge", payload)
    baseline_name = _require_non_empty_string("baseline_bridge.baseline_name", bridge.get("baseline_name"))
    if baseline_name != active_baseline_name:
        raise SystemExit("baseline_bridge.baseline_name must match active_baseline.profile_name exactly.")
    if _require_non_empty_string("baseline_bridge.release_posture", bridge.get("release_posture")) != "hold":
        raise SystemExit("baseline_bridge.release_posture must be hold.")
    if _require_list("baseline_bridge.guardrails", bridge.get("guardrails")) != list(GUARDRAILS):
        raise SystemExit("baseline_bridge.guardrails must preserve no_manifest_publication and no_btst_skill_promotion exactly.")
    if bridge.get("fail_closed") is not True:
        raise SystemExit("baseline_bridge.fail_closed must be true.")

    baseline_metrics = _require_object("baseline_bridge.baseline_metrics", bridge.get("baseline_metrics"))
    for metric_name in REQUIRED_BRIDGE_METRICS:
        metric_value = baseline_metrics.get(metric_name)
        if metric_name not in baseline_metrics:
            raise SystemExit(f"baseline_bridge.baseline_metrics.{metric_name} must be present.")
        if isinstance(metric_value, bool) or not isinstance(metric_value, (int, float)):
            raise SystemExit(f"baseline_bridge.baseline_metrics.{metric_name} must be a numeric value.")
    return bridge


def _delta(candidate_value: Any, baseline_value: Any) -> float | None:
    if isinstance(candidate_value, bool) or isinstance(baseline_value, bool):
        return None
    if not isinstance(candidate_value, (int, float)) or not isinstance(baseline_value, (int, float)):
        return None
    return float(candidate_value) - float(baseline_value)


def build_momentum_rollout_recheck_comparison(
    *,
    rollout_pack: dict[str, object],
    source_report: dict[str, object],
    baseline_bridge: dict[str, object] | None = None,
) -> dict[str, object]:
    normalized_pack = _require_object("rollout_pack", rollout_pack)
    normalized_source = _require_object("source_report", source_report)
    indexed_results = _index_results(normalized_source.get("results"))

    winner = _require_object("winner", normalized_pack.get("winner"))
    winner_trial_index = _require_non_negative_int("winner trial_index", winner.get("trial_index"))
    if winner_trial_index not in indexed_results:
        raise SystemExit("winner trial_index must exist in source_report.results.")

    active_baseline = _require_object("active_baseline", normalized_pack.get("active_baseline"))
    baseline_name = _require_non_empty_string("active_baseline.profile_name", active_baseline.get("profile_name"))

    comparison_summary = _require_object("comparison_summary", normalized_source.get("comparison_summary"))
    baseline_summary = comparison_summary.get(baseline_name)

    challenger_context: list[dict[str, Any]] = []
    for challenger in _require_list("rollout_pack.challengers", normalized_pack.get("challengers")):
        normalized_challenger = _require_object("challenger", challenger)
        challenger_trial_index = _require_non_negative_int("challenger trial_index", normalized_challenger.get("trial_index"))
        if challenger_trial_index not in indexed_results:
            raise SystemExit("challenger trial_index must exist in source_report.results.")
        challenger_context.append(
            {
                "trial_index": challenger_trial_index,
                "metrics": _require_result_metrics("challenger metrics", indexed_results[challenger_trial_index]),
            }
        )

    winner_result = indexed_results[winner_trial_index]
    winner_metrics = _require_result_metrics("winner metrics", winner_result)

    if isinstance(baseline_summary, dict):
        baseline_verdicts = _load_baseline_verdicts(normalized_source)
        baseline_verdict = baseline_verdicts.get(baseline_name)
        if not isinstance(baseline_verdict, dict):
            raise SystemExit("baseline_verdicts must contain the active baseline entry.")
        winner_vs_active_baseline = {
            "baseline_name": baseline_name,
            "candidate": _require_baseline_summary_field(baseline_summary, "candidate"),
            "baseline": _require_baseline_summary_field(baseline_summary, "baseline"),
            "next_close_positive_rate_delta": _require_baseline_summary_field(baseline_summary, "next_close_positive_rate_delta"),
            "next_close_payoff_ratio_delta": _require_baseline_summary_field(baseline_summary, "next_close_payoff_ratio_delta"),
            "blockers": list(baseline_verdict.get("blockers") or []),
        }
    else:
        if baseline_bridge is None:
            raise SystemExit("comparison_summary must contain the active baseline entry or baseline_bridge must be provided.")
        normalized_bridge = _require_baseline_bridge(baseline_bridge, active_baseline_name=baseline_name)
        bridge_metrics = _require_object("baseline_bridge.baseline_metrics", normalized_bridge.get("baseline_metrics"))
        winner_vs_active_baseline = {
            "baseline_name": baseline_name,
            "candidate": winner_metrics,
            "baseline": bridge_metrics,
            "next_close_positive_rate_delta": _delta(winner_metrics.get("next_close_positive_rate"), bridge_metrics.get("next_close_positive_rate")),
            "next_close_payoff_ratio_delta": _delta(winner_metrics.get("next_close_payoff_ratio"), bridge_metrics.get("next_close_payoff_ratio")),
            "blockers": list(_require_list("baseline_bridge.blockers", normalized_bridge.get("blockers") or [])),
        }

    return {
        "winner": {
            "trial_index": winner_trial_index,
            "metrics": winner_metrics,
        },
        "winner_vs_active_baseline": winner_vs_active_baseline,
        "challenger_context": challenger_context,
        "guardrails": list(_require_list("rollout_pack.guardrails", normalized_pack.get("guardrails"))),
        "release_posture": _require_non_empty_string("rollout_pack.release_posture", normalized_pack.get("release_posture")),
        "fail_closed": normalized_pack.get("fail_closed") is True,
    }


def render_momentum_rollout_recheck_comparison_markdown(payload: dict[str, Any]) -> str:
    normalized_payload = _require_object("payload", payload)
    winner = _require_object("winner", normalized_payload.get("winner"))
    winner_vs_active_baseline = _require_object("winner_vs_active_baseline", normalized_payload.get("winner_vs_active_baseline"))
    lines = [
        "# Momentum Rollout Recheck Comparison",
        "",
        f"- winner_trial_index: {winner['trial_index']}",
        f"- baseline_name: `{winner_vs_active_baseline['baseline_name']}`",
        f"- release_posture: `{normalized_payload['release_posture']}`",
        f"- fail_closed: {normalized_payload['fail_closed']}",
        "",
        "## Guardrails",
        "",
    ]
    lines.extend(f"- `{guardrail}`" for guardrail in list(normalized_payload.get("guardrails") or []))
    lines.extend(["", "## Challenger Context", ""])
    challenger_context = list(normalized_payload.get("challenger_context") or [])
    if challenger_context:
        lines.extend(f"- trial_index `{entry['trial_index']}`" for entry in challenger_context)
    else:
        lines.append("- _none_")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the momentum rollout recheck comparison artifact.")
    parser.add_argument("--rollout-pack-json", default=str(DEFAULT_ROLLOUT_PACK_JSON))
    parser.add_argument("--source-json", default=str(DEFAULT_SOURCE_JSON))
    parser.add_argument("--baseline-bridge-json", default=None)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args(argv)

    rollout_pack = _load_json_file(Path(args.rollout_pack_json), label="rollout pack")
    source_report = _load_json_file(Path(args.source_json), label="source report")
    baseline_bridge = _load_json_file(Path(args.baseline_bridge_json), label="baseline bridge") if args.baseline_bridge_json else None
    payload = build_momentum_rollout_recheck_comparison(
        rollout_pack=_require_object("rollout_pack", rollout_pack),
        source_report=_require_object("source_report", source_report),
        baseline_bridge=_require_object("baseline_bridge", baseline_bridge) if baseline_bridge is not None else None,
    )

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    _write_output_file(output_json, content=json.dumps(payload, ensure_ascii=False, indent=2), label="output JSON")
    _write_output_file(output_md, content=render_momentum_rollout_recheck_comparison_markdown(payload), label="output markdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
