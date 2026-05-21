from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.paper_trading.optimized_profile_resolution import resolve_btst_optimized_profile_manifest


DEFAULT_RERUN_PACK_JSON = Path("data/reports/btst_momentum_rerun_rollout_pack.json")
DEFAULT_RERUN_RECOMMENDATION_JSON = Path("data/reports/btst_momentum_rerun_rollout_recommendation.json")
DEFAULT_MANIFEST_JSON = Path("data/reports/btst_latest_optimized_profile.json")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_momentum_rollout_recheck_pack.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_momentum_rollout_recheck_pack.md")

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


def build_momentum_rollout_recheck_pack(*, rerun_pack: dict[str, object], rerun_recommendation: dict[str, object], baseline_resolution: dict[str, object]) -> dict[str, object]:
    normalized_pack = _require_object("rerun_pack", rerun_pack)
    normalized_recommendation = _require_object("rerun_recommendation", rerun_recommendation)
    normalized_baseline = _require_object("baseline_resolution", baseline_resolution)

    if str(normalized_recommendation.get("action") or "").strip() != "advance_rollout_recheck":
        raise SystemExit("rerun_recommendation.action must be advance_rollout_recheck.")
    if str(normalized_recommendation.get("release_posture") or "").strip() != "hold":
        raise SystemExit("rerun_recommendation.release_posture must be hold.")
    if list(normalized_recommendation.get("guardrails") or []) != list(normalized_pack.get("guardrails") or []):
        raise SystemExit("rerun_recommendation.guardrails must preserve rerun_pack.guardrails exactly.")
    if str(normalized_baseline.get("mode") or "").strip() != "optimized" or str(normalized_baseline.get("status") or "").strip() != "ready":
        raise SystemExit("baseline_resolution must be resolved to an optimized profile.")
    if normalized_baseline.get("fallback_reason") is not None:
        raise SystemExit("baseline_resolution must be resolved to an optimized profile.")
    if str(normalized_pack.get("release_posture") or "").strip() != "hold":
        raise SystemExit("rerun_pack.release_posture must be hold.")
    if list(normalized_pack.get("guardrails") or []) != list(GUARDRAILS):
        raise SystemExit("rerun_pack.guardrails must preserve no_manifest_publication and no_btst_skill_promotion exactly.")

    winner = _normalize_candidate("winner", normalized_pack.get("winner"))
    challengers_raw = normalized_pack.get("challengers")
    if not isinstance(challengers_raw, list):
        raise SystemExit("rerun_pack.challengers must be a list.")
    challengers = [_normalize_candidate(f"challengers[{index}]", candidate) for index, candidate in enumerate(challengers_raw)]

    return {
        "winner": winner,
        "challengers": challengers,
        "active_baseline": normalized_baseline,
        "guardrails": list(GUARDRAILS),
        "release_posture": "hold",
        "dominant_family": str(normalized_pack.get("dominant_family") or "").strip(),
        "missing_theme_exposure_window_count": _require_non_negative_int(
            "missing_theme_exposure_window_count", normalized_pack.get("missing_theme_exposure_window_count")
        ),
        "fail_closed": True,
    }


def render_momentum_rollout_recheck_pack_markdown(payload: dict[str, Any]) -> str:
    normalized_payload = _require_object("payload", payload)
    winner = _require_object("winner", normalized_payload.get("winner"))
    baseline = _require_object("active_baseline", normalized_payload.get("active_baseline"))

    lines = [
        "# Momentum Rollout Recheck Pack",
        "",
        "## Summary",
        "",
        f"- release_posture: `{normalized_payload['release_posture']}`",
        f"- dominant_family: `{normalized_payload['dominant_family']}`",
        f"- missing_theme_exposure_window_count: {normalized_payload['missing_theme_exposure_window_count']}",
        f"- winner_trial_index: {winner['trial_index']}",
        f"- active_baseline_profile_name: `{baseline.get('profile_name')}`",
        f"- challenger_count: {len(list(normalized_payload.get('challengers') or []))}",
        f"- fail_closed: {normalized_payload['fail_closed']}",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the momentum rollout recheck pack.")
    parser.add_argument("--rerun-pack-json", default=str(DEFAULT_RERUN_PACK_JSON))
    parser.add_argument("--rerun-recommendation-json", default=str(DEFAULT_RERUN_RECOMMENDATION_JSON))
    parser.add_argument("--manifest-json", default=str(DEFAULT_MANIFEST_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args(argv)

    rerun_pack = _load_json_file(Path(args.rerun_pack_json), label="rerun pack")
    rerun_recommendation = _load_json_file(Path(args.rerun_recommendation_json), label="rerun recommendation")
    baseline_resolution = resolve_btst_optimized_profile_manifest(args.manifest_json)
    payload = build_momentum_rollout_recheck_pack(
        rerun_pack=_require_object("rerun_pack", rerun_pack),
        rerun_recommendation=_require_object("rerun_recommendation", rerun_recommendation),
        baseline_resolution=_require_object("baseline_resolution", baseline_resolution),
    )

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    _write_output_file(output_json, content=json.dumps(payload, ensure_ascii=False, indent=2), label="output JSON")
    _write_output_file(output_md, content=render_momentum_rollout_recheck_pack_markdown(payload), label="output markdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
