from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

REPLAY_INPUT_FILENAME = "selection_target_replay_input.json"
TRADE_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def derive_latest_replay_trade_date(replay_input_paths: Iterable[str | Path]) -> str | None:
    trade_dates: list[str] = []
    for replay_input_path in replay_input_paths:
        resolved = Path(replay_input_path)
        if resolved.name != REPLAY_INPUT_FILENAME:
            continue
        trade_date = resolved.parent.name
        if TRADE_DATE_PATTERN.match(trade_date):
            trade_dates.append(trade_date)
    if not trade_dates:
        return None
    return max(trade_dates)


def build_ready_btst_optimized_profile_manifest(
    *,
    profile_name: str,
    profile_overrides: dict[str, Any],
    source_path: str | Path,
    replay_input_paths: Iterable[str | Path],
    validated_by: str = "walk_forward_and_rollout",
) -> dict[str, Any]:
    return {
        "profile_name": profile_name,
        "profile_overrides": dict(profile_overrides),
        "source_type": "optimize_profile",
        "source_path": str(Path(source_path).expanduser().resolve()),
        "validated_by": validated_by,
        "trade_date": derive_latest_replay_trade_date(replay_input_paths),
        "status": "ready",
    }


def publish_btst_optimized_profile_manifest(
    *,
    manifest_path: str | Path,
    rollout_recommendation: str,
    profile_name: str,
    profile_overrides: dict[str, Any],
    source_path: str | Path,
    replay_input_paths: Iterable[str | Path],
    validated_by: str = "walk_forward_and_rollout",
) -> dict[str, Any]:
    resolved_manifest_path = Path(manifest_path).expanduser().resolve()
    if rollout_recommendation != "promote":
        return {
            "status": "skipped",
            "reason": f"rollout_recommendation_{rollout_recommendation}",
            "manifest_path": str(resolved_manifest_path),
        }

    payload = build_ready_btst_optimized_profile_manifest(
        profile_name=profile_name,
        profile_overrides=profile_overrides,
        source_path=source_path,
        replay_input_paths=replay_input_paths,
        validated_by=validated_by,
    )
    resolved_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "status": "published",
        "reason": "promoted_btst_profile",
        "manifest_path": str(resolved_manifest_path),
        "payload": payload,
    }
