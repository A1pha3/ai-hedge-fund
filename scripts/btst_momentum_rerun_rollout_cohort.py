from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_SHORTLIST_JSON = Path("data/reports/btst_momentum_stability_retune_shortlist.json")
DEFAULT_DECISION_JSON = Path("data/reports/btst_momentum_stability_retune_decision.json")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_momentum_rerun_rollout_cohort.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_momentum_rerun_rollout_cohort.md")

CHALLENGER_LIMIT = 3
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


def _require_non_negative_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SystemExit(f"{name} must be a non-negative integer.")
    return value


def _normalize_candidate(name: str, candidate: Any) -> dict[str, Any]:
    normalized_candidate = _require_object(name, candidate)
    trial_index = _require_non_negative_int(f"{name} trial_index", normalized_candidate.get("trial_index"))
    cross_window_blocker_count = _require_non_negative_int(
        f"{name} cross_window_blocker_count", normalized_candidate.get("cross_window_blocker_count")
    )
    risk_blocker_count = _require_non_negative_int(f"{name} risk_blocker_count", normalized_candidate.get("risk_blocker_count"))

    normalized_row: dict[str, Any] = dict(normalized_candidate)
    normalized_row["trial_index"] = trial_index
    normalized_row["cross_window_blocker_count"] = cross_window_blocker_count
    normalized_row["risk_blocker_count"] = risk_blocker_count
    return normalized_row


def build_momentum_rerun_rollout_cohort(*, shortlist: dict[str, object], decision: dict[str, object]) -> dict[str, object]:
    normalized_shortlist = _require_object("shortlist", shortlist)
    normalized_decision = _require_object("decision", decision)

    action = str(normalized_decision.get("action") or "").strip()
    if action != "rerun_rollout_check":
        raise SystemExit("decision.action must be rerun_rollout_check.")

    shortlist_best_candidate = _require_object("shortlist best_candidate", normalized_shortlist.get("best_candidate"))
    shortlist_trial_index = _require_non_negative_int("shortlist best_candidate trial_index", shortlist_best_candidate.get("trial_index"))
    decision_winner = _require_object("decision best_candidate", normalized_decision.get("best_candidate"))
    decision_trial_index = _require_non_negative_int("decision best_candidate trial_index", decision_winner.get("trial_index"))

    if shortlist_trial_index != decision_trial_index:
        raise SystemExit("decision winner must match shortlist winner.")

    shortlist_winner = _normalize_candidate("shortlist best_candidate", shortlist_best_candidate)
    raw_candidates = normalized_shortlist.get("candidates")
    if not isinstance(raw_candidates, list):
        raise SystemExit("shortlist candidates must be a list of objects.")

    normalized_candidates: list[dict[str, Any]] = []
    seen_trial_indices: set[int] = set()
    winner_found = False
    for index, candidate in enumerate(raw_candidates):
        normalized_candidate = _normalize_candidate(f"candidate[{index}]", candidate)
        trial_index = int(normalized_candidate["trial_index"])
        if trial_index in seen_trial_indices:
            raise SystemExit("shortlist candidates must not contain a duplicate trial_index.")
        seen_trial_indices.add(trial_index)
        if normalized_candidate["trial_index"] == shortlist_winner["trial_index"] and not winner_found:
            winner_found = True
            continue
        normalized_candidates.append(normalized_candidate)

    if not winner_found:
        raise SystemExit("shortlist candidates must include the shortlist winner.")

    challengers = sorted(
        normalized_candidates,
        key=lambda item: (item["risk_blocker_count"], item["cross_window_blocker_count"], item["trial_index"]),
    )[:CHALLENGER_LIMIT]

    return {
        "guardrails": list(GUARDRAILS),
        "winner": shortlist_winner,
        "challenger_count": len(challengers),
        "challengers": challengers,
        "fail_closed": True,
    }


def render_momentum_rerun_rollout_cohort_markdown(payload: dict[str, Any]) -> str:
    normalized_payload = _require_object("payload", payload)
    winner = _require_object("winner", normalized_payload.get("winner"))

    lines = [
        "# Momentum Rerun Rollout Cohort",
        "",
        "## Summary",
        "",
        f"- winner_trial_index: {winner['trial_index']}",
        f"- challenger_count: {normalized_payload['challenger_count']}",
        f"- fail_closed: {normalized_payload['fail_closed']}",
        "",
        "## Guardrails",
        "",
    ]
    lines.extend(f"- `{guardrail}`" for guardrail in normalized_payload["guardrails"])
    lines.extend(["", "## Challengers", ""])

    challengers = list(normalized_payload.get("challengers") or [])
    if challengers:
        for challenger in challengers:
            lines.append(
                f"- trial {challenger['trial_index']}: risk={challenger['risk_blocker_count']}, cross_window={challenger['cross_window_blocker_count']}"
            )
    else:
        lines.append("- _none_")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a governed rerun-rollout cohort artifact for the momentum stability retune cycle.")
    parser.add_argument("--shortlist-json", default=str(DEFAULT_SHORTLIST_JSON))
    parser.add_argument("--decision-json", default=str(DEFAULT_DECISION_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args(argv)

    shortlist = _load_json_file(Path(args.shortlist_json), label="shortlist")
    decision = _load_json_file(Path(args.decision_json), label="decision")
    payload = build_momentum_rerun_rollout_cohort(shortlist=_require_object("shortlist", shortlist), decision=_require_object("decision", decision))

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    _write_output_file(output_json, content=json.dumps(payload, ensure_ascii=False, indent=2), label="output JSON")
    _write_output_file(output_md, content=render_momentum_rerun_rollout_cohort_markdown(payload), label="output markdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
