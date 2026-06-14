from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

DEFAULT_COMPARISON_JSON = Path("data/reports/btst_momentum_rollout_recheck_comparison.json")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_momentum_rollout_recheck_decision.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_momentum_rollout_recheck_decision.md")
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


def _require_float(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SystemExit(f"{name} must be a number.")
    float_value = float(value)
    if not math.isfinite(float_value):
        raise SystemExit(f"{name} must be a number.")
    return float_value


def _is_finite_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))


def _has_measurement_evidence(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    for key in ("next_close_positive_rate", "next_close_payoff_ratio"):
        value = payload.get(key)
        if not _is_finite_number(value) or value < 0:
            return False
    window_count = payload.get("window_count")
    if isinstance(window_count, bool) or not isinstance(window_count, int) or window_count <= 0:
        return False
    return True


def _sanitize_measurement_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload or not isinstance(payload, dict):
        return payload
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            sanitized[key] = value if math.isfinite(value) else None
        else:
            sanitized[key] = value
    return sanitized


def _require_guardrails(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise SystemExit("guardrails must be a JSON list.")
    guardrails = [str(item).strip() for item in value]
    if guardrails != list(GUARDRAILS):
        raise SystemExit("guardrails must preserve the governed no-publication and no-BTST-skill constraints.")
    return guardrails


def build_momentum_rollout_recheck_decision(*, comparison: dict[str, object]) -> dict[str, object]:
    normalized_comparison = _require_object("comparison", comparison)
    winner = _require_object("winner", normalized_comparison.get("winner"))
    winner_trial_index = _require_non_negative_int("winner trial_index", winner.get("trial_index"))
    winner_payload = dict(winner)
    winner_payload["trial_index"] = winner_trial_index

    winner_vs_active_baseline = _require_object("winner_vs_active_baseline", normalized_comparison.get("winner_vs_active_baseline"))
    blockers_raw = winner_vs_active_baseline.get("blockers")
    if not isinstance(blockers_raw, list):
        raise SystemExit("winner_vs_active_baseline.blockers must be a JSON list.")
    blockers = [str(blocker).strip() for blocker in blockers_raw if str(blocker).strip()]

    guardrails = _require_guardrails(normalized_comparison.get("guardrails"))
    release_posture = str(normalized_comparison.get("release_posture") or "").strip()
    if release_posture != "hold":
        raise SystemExit("release_posture must remain hold for the governed decision artifact.")
    fail_closed = normalized_comparison.get("fail_closed") is True
    if not fail_closed:
        raise SystemExit("fail_closed must be true for the governed decision artifact.")

    candidate_raw = winner_vs_active_baseline.get("candidate")
    baseline_raw = winner_vs_active_baseline.get("baseline")
    candidate = dict(candidate_raw) if isinstance(candidate_raw, dict) else None
    baseline = dict(baseline_raw) if isinstance(baseline_raw, dict) else None

    next_close_positive_rate_delta = winner_vs_active_baseline.get("next_close_positive_rate_delta")
    next_close_payoff_ratio_delta = winner_vs_active_baseline.get("next_close_payoff_ratio_delta")
    win_rate_delta = float(next_close_positive_rate_delta) if _is_finite_number(next_close_positive_rate_delta) else None
    payoff_delta = float(next_close_payoff_ratio_delta) if _is_finite_number(next_close_payoff_ratio_delta) else None

    if (
        not _has_measurement_evidence(candidate)
        or not _has_measurement_evidence(baseline)
        or next_close_positive_rate_delta is None
        or next_close_payoff_ratio_delta is None
        or not _is_finite_number(next_close_positive_rate_delta)
        or not _is_finite_number(next_close_payoff_ratio_delta)
    ):
        win_rate_delta = None
        payoff_delta = None
        action = "fallback_measurement_repair"
    else:
        win_rate_delta = _require_float("winner_vs_active_baseline.next_close_positive_rate_delta", next_close_positive_rate_delta)
        payoff_delta = _require_float("winner_vs_active_baseline.next_close_payoff_ratio_delta", next_close_payoff_ratio_delta)
        if win_rate_delta > 0 and payoff_delta > 0 and not blockers:
            action = "ready_for_release_review"
        else:
            action = "retain_hold"

    return {
        "action": action,
        "release_posture": "hold",
        "guardrails": guardrails,
        "winner": winner_payload,
        "winner_vs_active_baseline": {
            "baseline_name": str(winner_vs_active_baseline.get("baseline_name") or "").strip(),
            "candidate": _sanitize_measurement_payload(candidate),
            "baseline": _sanitize_measurement_payload(baseline),
            "next_close_positive_rate_delta": win_rate_delta,
            "next_close_payoff_ratio_delta": payoff_delta,
            "blockers": blockers,
        },
        "fail_closed": True,
    }


def render_momentum_rollout_recheck_decision_markdown(payload: dict[str, Any]) -> str:
    normalized_payload = _require_object("payload", payload)
    winner = _require_object("winner", normalized_payload.get("winner"))
    winner_vs_active_baseline = _require_object("winner_vs_active_baseline", normalized_payload.get("winner_vs_active_baseline"))
    lines = [
        "# Momentum Rollout Recheck Decision",
        "",
        "## Summary",
        "",
        f"- action: `{normalized_payload['action']}`",
        f"- release_posture: `{normalized_payload['release_posture']}`",
        f"- baseline_name: `{winner_vs_active_baseline['baseline_name']}`",
        f"- winner_trial_index: {winner['trial_index']}",
        f"- next_close_positive_rate_delta: {winner_vs_active_baseline['next_close_positive_rate_delta']}",
        f"- next_close_payoff_ratio_delta: {winner_vs_active_baseline['next_close_payoff_ratio_delta']}",
        f"- fail_closed: {normalized_payload['fail_closed']}",
        "",
        "## Guardrails",
        "",
    ]
    lines.extend(f"- `{guardrail}`" for guardrail in normalized_payload["guardrails"])
    lines.extend(["", "## Blockers", ""])
    blockers = list(winner_vs_active_baseline.get("blockers") or [])
    if blockers:
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    else:
        lines.append("- _none_")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a governed decision artifact for the momentum rollout recheck.")
    parser.add_argument("--comparison-json", default=str(DEFAULT_COMPARISON_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args(argv)

    comparison = _load_json_file(Path(args.comparison_json), label="comparison")
    payload = build_momentum_rollout_recheck_decision(comparison=_require_object("comparison", comparison))

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    _write_output_file(output_json, content=json.dumps(payload, ensure_ascii=False, indent=2), label="output JSON")
    _write_output_file(output_md, content=render_momentum_rollout_recheck_decision_markdown(payload), label="output markdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
