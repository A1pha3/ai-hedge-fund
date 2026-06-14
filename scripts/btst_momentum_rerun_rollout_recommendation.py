from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_PACK_JSON = Path("data/reports/btst_momentum_rerun_rollout_pack.json")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_momentum_rerun_rollout_recommendation.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_momentum_rerun_rollout_recommendation.md")
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
    normalized_candidate["trial_index"] = _require_non_negative_int(f"{name} trial_index", normalized_candidate.get("trial_index"))
    normalized_candidate["cross_window_blocker_count"] = _require_non_negative_int(
        f"{name} cross_window_blocker_count", normalized_candidate.get("cross_window_blocker_count")
    )
    normalized_candidate["risk_blocker_count"] = _require_non_negative_int(f"{name} risk_blocker_count", normalized_candidate.get("risk_blocker_count"))
    return normalized_candidate


def build_momentum_rerun_rollout_recommendation(*, pack: dict[str, object]) -> dict[str, object]:
    normalized_pack = _require_object("pack", pack)

    winner = _normalize_candidate("pack winner", normalized_pack.get("winner"))
    challengers_raw = normalized_pack.get("challengers")
    if not isinstance(challengers_raw, list):
        raise SystemExit("pack challengers must be a list.")
    challengers = [_normalize_candidate(f"pack challengers[{index}]", challenger) for index, challenger in enumerate(challengers_raw)]

    dominant_family = str(normalized_pack.get("dominant_family") or "").strip()
    if not dominant_family:
        raise SystemExit("pack dominant_family must be a non-empty string.")

    missing_theme_exposure_window_count = _require_non_negative_int(
        "pack missing_theme_exposure_window_count", normalized_pack.get("missing_theme_exposure_window_count")
    )

    if dominant_family == "missing_observability" and missing_theme_exposure_window_count > 0:
        action = "fallback_measurement_repair"
    elif winner["cross_window_blocker_count"] == 0 and winner["risk_blocker_count"] == 0:
        action = "advance_rollout_recheck"
    else:
        action = "retain_hold"

    return {
        "action": action,
        "release_posture": "hold",
        "guardrails": list(GUARDRAILS),
        "winner": winner,
        "challengers": challengers,
        "dominant_family": dominant_family,
        "missing_theme_exposure_window_count": missing_theme_exposure_window_count,
        "fail_closed": True,
    }


def render_momentum_rerun_rollout_recommendation_markdown(payload: dict[str, Any]) -> str:
    normalized_payload = _require_object("payload", payload)
    winner = _require_object("winner", normalized_payload.get("winner"))
    challengers = list(normalized_payload.get("challengers") or [])

    lines = [
        "# Momentum Rerun Rollout Recommendation",
        "",
        "## Summary",
        "",
        f"- action: `{normalized_payload['action']}`",
        f"- release_posture: `{normalized_payload['release_posture']}`",
        f"- dominant_family: `{normalized_payload['dominant_family']}`",
        f"- missing_theme_exposure_window_count: {normalized_payload['missing_theme_exposure_window_count']}",
        f"- winner_trial_index: {winner['trial_index']}",
        f"- winner_cross_window_blocker_count: {winner['cross_window_blocker_count']}",
        f"- winner_risk_blocker_count: {winner['risk_blocker_count']}",
        f"- challenger_count: {len(challengers)}",
        f"- fail_closed: {normalized_payload['fail_closed']}",
        "",
        "## Guardrails",
        "",
    ]
    lines.extend(f"- `{guardrail}`" for guardrail in normalized_payload["guardrails"])
    lines.extend(["", "## Winner", ""])
    lines.append(
        f"- trial {winner['trial_index']}: cross_window={winner['cross_window_blocker_count']}, risk={winner['risk_blocker_count']}"
    )
    lines.extend(["", "## Challengers", ""])
    if challengers:
        for challenger in challengers:
            lines.append(
                f"- trial {challenger['trial_index']}: cross_window={challenger['cross_window_blocker_count']}, risk={challenger['risk_blocker_count']}"
            )
    else:
        lines.append("- _none_")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a governed rerun-rollout recommendation artifact for the momentum rerun cycle.")
    parser.add_argument("--pack-json", default=str(DEFAULT_PACK_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args(argv)

    pack = _load_json_file(Path(args.pack_json), label="pack")
    payload = build_momentum_rerun_rollout_recommendation(pack=_require_object("pack", pack))

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    _write_output_file(output_json, content=json.dumps(payload, ensure_ascii=False, indent=2), label="output JSON")
    _write_output_file(output_md, content=render_momentum_rerun_rollout_recommendation_markdown(payload), label="output markdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
