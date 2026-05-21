from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional


def build_momentum_rollout_recheck_pack(*, baseline_resolution: Optional[Dict[str, Any]] = None, active_baseline_snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build a rerun/recheck pack for momentum rollout.

    Supports two mutually-compatible input paths:
    - active_baseline_snapshot: a governed input-only snapshot (preferred when provided)
    - baseline_resolution: existing manifest-based resolution path (kept for backward compatibility)

    Validation is strict and fail-closed: invalid inputs raise SystemExit.
    """
    if active_baseline_snapshot is not None:
        if not isinstance(active_baseline_snapshot, dict):
            raise SystemExit("active_baseline_snapshot must be a JSON object")
        # governance checks
        if active_baseline_snapshot.get("release_posture") != "hold":
            raise SystemExit("active_baseline_snapshot.release_posture must be 'hold' (fail closed)")
        guardrails = active_baseline_snapshot.get("guardrails")
        if not isinstance(guardrails, list) or guardrails != ["no_manifest_publication", "no_btst_skill_promotion"]:
            raise SystemExit("active_baseline_snapshot.guardrails must be ['no_manifest_publication', 'no_btst_skill_promotion'] (fail closed)")
        if active_baseline_snapshot.get("fail_closed") is not True:
            raise SystemExit("active_baseline_snapshot.fail_closed must be True (fail closed)")

        active_baseline = active_baseline_snapshot
    else:
        # baseline_resolution path
        if baseline_resolution is None:
            raise SystemExit("either baseline_resolution or active_baseline_snapshot must be provided")
        if not isinstance(baseline_resolution, dict):
            raise SystemExit("baseline_resolution must be a JSON object")
        manifest_path = baseline_resolution.get("manifest_path")
        if not isinstance(manifest_path, str) or not manifest_path.strip():
            raise SystemExit("baseline_resolution.manifest_path must be a non-empty string")
        # keep behavior minimal: build active_baseline reference from manifest
        active_baseline = {
            "source": "manifest_resolution",
            "manifest_path": manifest_path,
        }

    pack = {
        "active_baseline": active_baseline,
        "rerun_pack": {
            "metadata": {},
            "recommendation": "recheck",
        },
    }
    return pack


def main(argv: list[str] | None = None, return_pack: bool = False) -> int | Dict[str, Any]:
    parser = argparse.ArgumentParser(description="Build BTST momentum rollout recheck pack")
    parser.add_argument("--baseline-resolution-json", help="Path to baseline_resolution JSON", default=None)
    parser.add_argument("--active-baseline-json", help="Path to active baseline snapshot JSON", default=None)
    args = parser.parse_args(argv)

    baseline_resolution = None
    active_baseline_snapshot = None

    if args.baseline_resolution_json:
        p = Path(args.baseline_resolution_json)
        if not p.exists():
            raise SystemExit(f"baseline_resolution JSON not found: {p}")
        try:
            with p.open("r", encoding="utf-8") as f:
                baseline_resolution = json.load(f)
        except Exception as e:
            raise SystemExit(f"failed to read baseline_resolution JSON: {e}")

    if args.active_baseline_json:
        p = Path(args.active_baseline_json)
        if not p.exists():
            raise SystemExit(f"active_baseline JSON not found: {p}")
        try:
            with p.open("r", encoding="utf-8") as f:
                active_baseline_snapshot = json.load(f)
        except Exception as e:
            raise SystemExit(f"failed to read active_baseline JSON: {e}")

    # prefer active_baseline_snapshot if supplied
    pack = build_momentum_rollout_recheck_pack(
        baseline_resolution=baseline_resolution, active_baseline_snapshot=active_baseline_snapshot
    )

    if return_pack:
        return pack

    # otherwise, write pack to stdout as JSON (non-file side-effect)
    print(json.dumps(pack, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
