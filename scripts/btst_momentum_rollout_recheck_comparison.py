from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_ROLLOUT_PACK_JSON = Path("data/reports/btst_momentum_rollout_recheck_pack.json")
DEFAULT_SOURCE_JSON = Path("/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/reports/param_search_momentum_optimized_apr_may_coarse_v3.json")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_momentum_rollout_recheck_comparison.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_momentum_rollout_recheck_comparison.md")


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


def build_momentum_rollout_recheck_comparison(*, rollout_pack: dict[str, object], source_report: dict[str, object]) -> dict[str, object]:
    normalized_pack = _require_object("rollout_pack", rollout_pack)
    normalized_source = _require_object("source_report", source_report)
    indexed_results = _index_results(normalized_source.get("results"))

    winner = _require_object("winner", normalized_pack.get("winner"))
    winner_trial_index = _require_non_negative_int("winner trial_index", winner.get("trial_index"))
    if winner_trial_index not in indexed_results:
        raise SystemExit("winner trial_index must exist in source_report.results.")

    active_baseline = _require_object("active_baseline", normalized_pack.get("active_baseline"))
    baseline_name = str(active_baseline.get("profile_name") or "").strip()
    if not baseline_name:
        raise SystemExit("active_baseline.profile_name must be a non-empty string.")

    comparison_summary = _require_object("comparison_summary", normalized_source.get("comparison_summary"))
    baseline_summary = comparison_summary.get(baseline_name)
    if not isinstance(baseline_summary, dict):
        raise SystemExit("comparison_summary must contain the active baseline entry.")
    baseline_verdicts = _require_object("baseline_verdicts", normalized_source.get("baseline_verdicts"))
    baseline_verdict = baseline_verdicts.get(baseline_name)
    if not isinstance(baseline_verdict, dict):
        raise SystemExit("baseline_verdicts must contain the active baseline entry.")

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
    return {
        "winner": {
            "trial_index": winner_trial_index,
            "metrics": _require_result_metrics("winner metrics", winner_result),
        },
        "winner_vs_active_baseline": {
            "baseline_name": baseline_name,
            "comparison_summary": baseline_summary,
            "baseline_verdict": baseline_verdict,
            "blockers": list(baseline_verdict.get("blockers") or []),
        },
        "challenger_context": challenger_context,
        "guardrails": list(_require_list("rollout_pack.guardrails", normalized_pack.get("guardrails"))),
        "release_posture": str(normalized_pack.get("release_posture") or "").strip(),
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
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args(argv)

    rollout_pack = json.loads(Path(args.rollout_pack_json).read_text(encoding="utf-8"))
    source_report = json.loads(Path(args.source_json).read_text(encoding="utf-8"))
    payload = build_momentum_rollout_recheck_comparison(rollout_pack=rollout_pack, source_report=source_report)

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(render_momentum_rollout_recheck_comparison_markdown(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
