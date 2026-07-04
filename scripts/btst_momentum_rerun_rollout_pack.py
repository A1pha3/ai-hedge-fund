from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_COHORT_JSON = Path("data/reports/btst_momentum_rerun_rollout_cohort.json")
DEFAULT_DECISION_JSON = Path("data/reports/btst_momentum_stability_retune_decision.json")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_momentum_rerun_rollout_pack.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_momentum_rerun_rollout_pack.md")

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


def _require_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{name} must be a non-empty string.")
    return value.strip()


def _require_single_line_string(name: str, value: Any) -> str:
    normalized = _require_string(name, value)
    if "\n" in normalized or "\r" in normalized:
        raise SystemExit(f"{name} must not contain newlines.")
    if "`" in normalized:
        raise SystemExit(f"{name} must not contain backticks.")
    return normalized


def _require_guardrails(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise SystemExit("guardrails must be a list.")
    guardrails = [str(item) for item in value]
    if guardrails != list(GUARDRAILS):
        raise SystemExit("guardrails must preserve no_manifest_publication and no_btst_skill_promotion exactly.")
    return guardrails


def _normalize_candidate(name: str, candidate: Any) -> dict[str, Any]:
    normalized_candidate = _require_object(name, candidate)
    normalized_candidate["trial_index"] = _require_non_negative_int(f"{name} trial_index", normalized_candidate.get("trial_index"))
    normalized_candidate["cross_window_blocker_count"] = _require_non_negative_int(f"{name} cross_window_blocker_count", normalized_candidate.get("cross_window_blocker_count"))
    normalized_candidate["risk_blocker_count"] = _require_non_negative_int(f"{name} risk_blocker_count", normalized_candidate.get("risk_blocker_count"))
    return normalized_candidate


def build_momentum_rerun_rollout_pack(*, cohort: dict[str, object], decision: dict[str, object]) -> dict[str, object]:
    normalized_cohort = _require_object("cohort", cohort)
    normalized_decision = _require_object("decision", decision)

    action = _require_string("decision.action", normalized_decision.get("action"))
    if action != "rerun_rollout_check":
        raise SystemExit("decision.action must be rerun_rollout_check.")

    release_posture = _require_string("decision.release_posture", normalized_decision.get("release_posture"))
    if release_posture != "hold":
        raise SystemExit("decision.release_posture must be hold.")

    dominant_family = _require_single_line_string("decision.dominant_family", normalized_decision.get("dominant_family"))
    missing_theme_exposure_window_count = _require_non_negative_int("decision.missing_theme_exposure_window_count", normalized_decision.get("missing_theme_exposure_window_count"))

    winner = _normalize_candidate("cohort winner", normalized_cohort.get("winner"))
    challengers_raw = normalized_cohort.get("challengers")
    if not isinstance(challengers_raw, list):
        raise SystemExit("cohort challengers must be a list.")
    challengers = [_normalize_candidate(f"cohort challengers[{index}]", challenger) for index, challenger in enumerate(challengers_raw)]

    return {
        "winner": winner,
        "challengers": challengers,
        "guardrails": _require_guardrails(normalized_cohort.get("guardrails")),
        "release_posture": release_posture,
        "dominant_family": dominant_family,
        "missing_theme_exposure_window_count": missing_theme_exposure_window_count,
        "fail_closed": True,
    }


def render_momentum_rerun_rollout_pack_markdown(payload: dict[str, Any]) -> str:
    normalized_payload = _require_object("payload", payload)
    winner = _require_object("winner", normalized_payload.get("winner"))
    challengers = list(normalized_payload.get("challengers") or [])

    lines = [
        "# Momentum Rerun Rollout Pack",
        "",
        "## Summary",
        "",
        f"- release_posture: `{normalized_payload['release_posture']}`",
        f"- dominant_family: `{normalized_payload['dominant_family']}`",
        f"- missing_theme_exposure_window_count: {normalized_payload['missing_theme_exposure_window_count']}",
        f"- winner_trial_index: {winner['trial_index']}",
        f"- challenger_count: {len(challengers)}",
        f"- fail_closed: {normalized_payload['fail_closed']}",
        "",
        "## Guardrails",
        "",
    ]
    lines.extend(f"- `{guardrail}`" for guardrail in normalized_payload["guardrails"])
    lines.extend(["", "## Challengers", ""])

    if challengers:
        for challenger in challengers:
            lines.append(f"- trial {challenger['trial_index']}")
    else:
        lines.append("- _none_")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a governed rerun-rollout pack for the momentum stability retune cycle.")
    parser.add_argument("--cohort-json", default=str(DEFAULT_COHORT_JSON))
    parser.add_argument("--decision-json", default=str(DEFAULT_DECISION_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args(argv)

    cohort = _load_json_file(Path(args.cohort_json), label="cohort")
    decision = _load_json_file(Path(args.decision_json), label="decision")
    payload = build_momentum_rerun_rollout_pack(cohort=_require_object("cohort", cohort), decision=_require_object("decision", decision))

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    _write_output_file(output_json, content=json.dumps(payload, ensure_ascii=False, indent=2), label="output JSON")
    _write_output_file(output_md, content=render_momentum_rerun_rollout_pack_markdown(payload), label="output markdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
