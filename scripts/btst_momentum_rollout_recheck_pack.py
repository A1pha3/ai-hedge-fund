from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_RERUN_PACK_JSON = Path("data/reports/btst_momentum_rerun_rollout_pack.json")
DEFAULT_RERUN_RECOMMENDATION_JSON = Path("data/reports/btst_momentum_rerun_rollout_recommendation.json")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_momentum_rollout_recheck_pack.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_momentum_rollout_recheck_pack.md")
GUARDRAILS = ["no_manifest_publication", "no_btst_skill_promotion"]


def _load_json(path: Path, *, label: str) -> Dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"{label} JSON not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        raise SystemExit(f"failed to read {label} JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{label} must be a JSON object")
    return payload


def _write_output(path: Path, *, content: str, label: str) -> None:
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"failed to write {label}: {path}") from exc


def _normalize_candidate(candidate: Any, *, label: str) -> Dict[str, Any]:
    if not isinstance(candidate, dict):
        raise SystemExit(f"{label} must be a JSON object")
    trial_index = candidate.get("trial_index")
    if isinstance(trial_index, bool) or not isinstance(trial_index, int) or trial_index < 0:
        raise SystemExit(f"{label}.trial_index must be a non-negative integer")
    return {
        "trial_index": trial_index,
        "params": candidate.get("params", {}),
        "cross_window_blocker_count": candidate.get("cross_window_blocker_count", 0),
        "risk_blocker_count": candidate.get("risk_blocker_count", 0),
    }


def _validate_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    if snapshot.get("release_posture") != "hold":
        raise SystemExit("active_baseline_snapshot.release_posture must be 'hold' (fail closed)")
    guardrails = snapshot.get("guardrails")
    if not isinstance(guardrails, list) or guardrails != GUARDRAILS:
        raise SystemExit("active_baseline_snapshot.guardrails must be ['no_manifest_publication', 'no_btst_skill_promotion'] (fail closed)")
    if snapshot.get("fail_closed") is not True:
        raise SystemExit("active_baseline_snapshot.fail_closed must be True (fail closed)")
    return snapshot


def _resolve_active_baseline(*, baseline_resolution: Optional[Dict[str, Any]], active_baseline_snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if active_baseline_snapshot is not None:
        if not isinstance(active_baseline_snapshot, dict):
            raise SystemExit("active_baseline_snapshot must be a JSON object")
        return _validate_snapshot(active_baseline_snapshot)

    if baseline_resolution is None:
        raise SystemExit("either baseline_resolution or active_baseline_snapshot must be provided")
    if not isinstance(baseline_resolution, dict):
        raise SystemExit("baseline_resolution must be a JSON object")
    manifest_path = baseline_resolution.get("manifest_path")
    if not isinstance(manifest_path, str) or not manifest_path.strip():
        raise SystemExit("baseline_resolution.manifest_path must be a non-empty string")
    return {
        "source": "manifest_resolution",
        "manifest_path": manifest_path,
    }


def _validate_rerun_contract(*, rerun_pack: Dict[str, Any], rerun_recommendation: Dict[str, Any]) -> None:
    if rerun_recommendation.get("action") != "advance_rollout_recheck":
        raise SystemExit("rerun_recommendation.action must be advance_rollout_recheck")
    if rerun_pack.get("guardrails") != GUARDRAILS or rerun_recommendation.get("guardrails") != GUARDRAILS:
        raise SystemExit("rerun guardrails must preserve no_manifest_publication and no_btst_skill_promotion")
    if rerun_pack.get("release_posture") != "hold" or rerun_recommendation.get("release_posture") != "hold":
        raise SystemExit("rerun release_posture must remain hold")
    if rerun_pack.get("dominant_family") != rerun_recommendation.get("dominant_family"):
        raise SystemExit("dominant_family must match between rerun pack and recommendation")
    if rerun_pack.get("missing_theme_exposure_window_count") != rerun_recommendation.get("missing_theme_exposure_window_count"):
        raise SystemExit("missing_theme_exposure_window_count must match between rerun pack and recommendation")
    if rerun_pack.get("fail_closed") is not True or rerun_recommendation.get("fail_closed") is not True:
        raise SystemExit("rerun pack and recommendation must remain fail_closed")


def build_momentum_rollout_recheck_pack(
    *,
    baseline_resolution: Optional[Dict[str, Any]] = None,
    active_baseline_snapshot: Optional[Dict[str, Any]] = None,
    rerun_pack: Optional[Dict[str, Any]] = None,
    rerun_recommendation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    active_baseline = _resolve_active_baseline(baseline_resolution=baseline_resolution, active_baseline_snapshot=active_baseline_snapshot)

    if rerun_pack is None and rerun_recommendation is None:
        return {
            "active_baseline": active_baseline,
            "rerun_pack": {
                "metadata": {},
                "recommendation": "recheck",
            },
        }

    if not isinstance(rerun_pack, dict):
        raise SystemExit("rerun_pack must be a JSON object")
    if not isinstance(rerun_recommendation, dict):
        raise SystemExit("rerun_recommendation must be a JSON object")
    _validate_rerun_contract(rerun_pack=rerun_pack, rerun_recommendation=rerun_recommendation)

    return {
        "winner": _normalize_candidate(rerun_pack.get("winner"), label="rerun_pack.winner"),
        "challengers": [_normalize_candidate(candidate, label="rerun_pack.challenger") for candidate in rerun_pack.get("challengers") or []],
        "active_baseline": active_baseline,
        "guardrails": GUARDRAILS,
        "release_posture": "hold",
        "dominant_family": rerun_pack.get("dominant_family"),
        "missing_theme_exposure_window_count": rerun_pack.get("missing_theme_exposure_window_count"),
        "fail_closed": True,
    }


def render_momentum_rollout_recheck_pack_markdown(payload: Dict[str, Any]) -> str:
    lines = ["# BTST Momentum Rollout Recheck Pack", ""]
    if "winner" in payload:
        lines.append(f"- winner_trial_index: {payload['winner']['trial_index']}")
        lines.append(f"- challenger_count: {len(payload.get('challengers') or [])}")
        lines.append(f"- active_baseline: `{payload['active_baseline'].get('profile_name', payload['active_baseline'].get('manifest_path'))}`")
        lines.append(f"- release_posture: `{payload.get('release_posture')}`")
        lines.append(f"- fail_closed: {payload.get('fail_closed')}")
    else:
        lines.append("- fallback manifest/snapshot compatibility mode")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, return_pack: bool = False) -> int | Dict[str, Any]:
    parser = argparse.ArgumentParser(description="Build BTST momentum rollout recheck pack")
    parser.add_argument("--baseline-resolution-json", help="Path to baseline_resolution JSON", default=None)
    parser.add_argument("--active-baseline-json", help="Path to active baseline snapshot JSON", default=None)
    parser.add_argument("--rerun-pack-json", help="Path to rerun rollout pack JSON", default=None)
    parser.add_argument("--rerun-recommendation-json", help="Path to rerun rollout recommendation JSON", default=None)
    parser.add_argument("--output-json", help="Path to output JSON", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", help="Path to output markdown", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args(argv)

    baseline_resolution = _load_json(Path(args.baseline_resolution_json), label="baseline_resolution") if args.baseline_resolution_json else None
    active_baseline_snapshot = _load_json(Path(args.active_baseline_json), label="active_baseline") if args.active_baseline_json else None
    rerun_pack = _load_json(Path(args.rerun_pack_json), label="rerun_pack") if args.rerun_pack_json else None
    rerun_recommendation = _load_json(Path(args.rerun_recommendation_json), label="rerun_recommendation") if args.rerun_recommendation_json else None

    pack = build_momentum_rollout_recheck_pack(
        baseline_resolution=baseline_resolution,
        active_baseline_snapshot=active_baseline_snapshot,
        rerun_pack=rerun_pack,
        rerun_recommendation=rerun_recommendation,
    )

    if return_pack:
        return pack

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    _write_output(output_json, content=json.dumps(pack, indent=2, ensure_ascii=False), label="output JSON")
    _write_output(output_md, content=render_momentum_rollout_recheck_pack_markdown(pack), label="output markdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
