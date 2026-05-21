from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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


def build_momentum_stability_retune_decision(*, shortlist: dict[str, object], triage: dict[str, object]) -> dict[str, object]:
    normalized_shortlist = _require_object("shortlist", shortlist)
    normalized_triage = _require_object("triage", triage)

    best_candidate = _require_object("shortlist best_candidate", normalized_shortlist.get("best_candidate"))
    candidate_count = _require_non_negative_int("candidate_count", normalized_shortlist.get("candidate_count"))
    dominant_family = str(normalized_triage.get("dominant_family") or "").strip()
    blocker_count = _require_non_negative_int("blocker_count", normalized_triage.get("blocker_count"))
    missing_theme_exposure_window_count = _require_non_negative_int(
        "missing_theme_exposure_window_count", normalized_triage.get("missing_theme_exposure_window_count")
    )

    trial_index = best_candidate.get("trial_index")
    cross_window_blocker_count = _require_non_negative_int("cross_window_blocker_count", best_candidate.get("cross_window_blocker_count"))
    risk_blocker_count = _require_non_negative_int("risk_blocker_count", best_candidate.get("risk_blocker_count"))

    if dominant_family == "missing_observability":
        action = "fallback_measurement_repair"
    elif cross_window_blocker_count < blocker_count and risk_blocker_count == 0:
        action = "rerun_rollout_check"
    else:
        action = "retain_hold"

    return {
        "action": action,
        "release_posture": "hold",
        "guardrails": list(GUARDRAILS),
        "candidate_count": candidate_count,
        "best_candidate": {
            "trial_index": trial_index,
            "cross_window_blocker_count": cross_window_blocker_count,
            "risk_blocker_count": risk_blocker_count,
        },
        "dominant_family": dominant_family,
        "blocker_count": blocker_count,
        "missing_theme_exposure_window_count": missing_theme_exposure_window_count,
        "fail_closed": True,
    }


def render_momentum_stability_retune_decision_markdown(payload: dict[str, Any]) -> str:
    normalized_payload = _require_object("payload", payload)
    best_candidate = _require_object("best_candidate", normalized_payload.get("best_candidate"))

    lines = [
        "# Momentum Stability Retune Decision",
        "",
        "## Summary",
        "",
        f"- action: `{normalized_payload['action']}`",
        f"- release_posture: `{normalized_payload['release_posture']}`",
        f"- dominant_family: `{normalized_payload['dominant_family']}`",
        f"- candidate_count: {normalized_payload['candidate_count']}",
        f"- blocker_count: {normalized_payload['blocker_count']}",
        f"- missing_theme_exposure_window_count: {normalized_payload['missing_theme_exposure_window_count']}",
        f"- best_trial_index: {best_candidate['trial_index']}",
        f"- cross_window_blocker_count: {best_candidate['cross_window_blocker_count']}",
        f"- risk_blocker_count: {best_candidate['risk_blocker_count']}",
        f"- fail_closed: {normalized_payload['fail_closed']}",
        "",
        "## Guardrails",
        "",
    ]
    lines.extend(f"- `{guardrail}`" for guardrail in normalized_payload["guardrails"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a governed next-action artifact for the momentum stability retune cycle.")
    parser.add_argument("--shortlist-json", required=True)
    parser.add_argument("--triage-json", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args(argv)

    shortlist = _load_json_file(Path(args.shortlist_json), label="shortlist")
    triage = _load_json_file(Path(args.triage_json), label="triage")
    payload = build_momentum_stability_retune_decision(shortlist=_require_object("shortlist", shortlist), triage=_require_object("triage", triage))

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    _write_output_file(output_json, content=json.dumps(payload, ensure_ascii=False, indent=2), label="output JSON")
    _write_output_file(output_md, content=render_momentum_stability_retune_decision_markdown(payload), label="output markdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
