"""Create an input-only active baseline snapshot from a session summary.

Validates optimization_profile_resolution and emits JSON + Markdown artifacts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

DEFAULT_INPUT = (
    Path("data/reports/paper_trading_20260512_20260512_live_m2_7_short_trade_only_20260513_plan_optimized_verify")
    / "session_summary.json"
)
DEFAULT_JSON_OUT = Path("data/reports/btst_momentum_active_baseline_snapshot.json")
DEFAULT_MD_OUT = Path("data/reports/btst_momentum_active_baseline_snapshot.md")


class SnapshotValidationError(ValueError):
    pass


def load_session_summary(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise SnapshotValidationError(f"session summary not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise SnapshotValidationError(f"failed to read session summary JSON: {e}")
    return data


def build_snapshot(session_summary: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(session_summary, dict):
        raise SnapshotValidationError("session summary must be a JSON object")

    opr = session_summary.get("optimization_profile_resolution")
    if not isinstance(opr, dict):
        raise SnapshotValidationError("missing or malformed optimization_profile_resolution")

    mode = opr.get("mode")
    status = opr.get("status")
    fallback_reason = opr.get("fallback_reason")
    if mode != "optimized" or status != "ready" or fallback_reason is not None:
        raise SnapshotValidationError(
            "optimization_profile_resolution must have mode==optimized, status==ready, and fallback_reason==None"
        )

    # required string fields
    required_strs = ["profile_name", "source_type", "source_path", "validated_by", "manifest_path"]
    for k in required_strs:
        v = opr.get(k)
        if not isinstance(v, str) or not v.strip():
            raise SnapshotValidationError(f"optimization_profile_resolution.{k} must be a non-empty string")

    profile_overrides = opr.get("profile_overrides")
    if profile_overrides is None:
        # allow empty dict but must be present and an object
        raise SnapshotValidationError("optimization_profile_resolution.profile_overrides must be present (object)")
    if not isinstance(profile_overrides, dict):
        raise SnapshotValidationError("optimization_profile_resolution.profile_overrides must be a JSON object")

    trade_date = session_summary.get("trade_date")
    if not isinstance(trade_date, str) or not trade_date.strip():
        raise SnapshotValidationError("session_summary.trade_date must be a non-empty string")

    snapshot = {
        "profile_name": opr["profile_name"],
        "profile_overrides": profile_overrides,
        "source_type": opr["source_type"],
        "source_path": opr["source_path"],
        "validated_by": opr["validated_by"],
        "trade_date": trade_date,
        "manifest_path": opr["manifest_path"],
        # governance fields
        "release_posture": "hold",
        "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
        "fail_closed": True,
    }
    return snapshot


def render_markdown(snapshot: Dict[str, Any]) -> str:
    lines = ["# BTST Momentum Active Baseline Snapshot", ""]
    lines.append(f"- profile_name: `{snapshot.get('profile_name')}`")
    lines.append(f"- trade_date: `{snapshot.get('trade_date')}`")
    lines.append(f"- source_type: `{snapshot.get('source_type')}`")
    lines.append(f"- source_path: `{snapshot.get('source_path')}`")
    lines.append(f"- validated_by: `{snapshot.get('validated_by')}`")
    lines.append(f"- manifest_path: `{snapshot.get('manifest_path')}`")
    lines.append("")
    lines.append("## Profile overrides")
    po = json.dumps(snapshot.get("profile_overrides", {}), indent=2)
    lines.append("```json")
    lines.append(po)
    lines.append("```")
    lines.append("")
    lines.append("## Governance")
    lines.append(f"- release_posture: `{snapshot.get('release_posture')}`")
    lines.append(f"- guardrails: `{snapshot.get('guardrails')}`")
    lines.append(f"- fail_closed: `{snapshot.get('fail_closed')}`")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit BTST momentum active baseline snapshot from session summary")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--json-output", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--md-output", default=str(DEFAULT_MD_OUT))
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    json_out = Path(args.json_output)
    md_out = Path(args.md_output)

    session = load_session_summary(input_path)
    snapshot = build_snapshot(session)

    # ensure parent directories exist
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)

    with json_out.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    md_text = render_markdown(snapshot)
    with md_out.open("w", encoding="utf-8") as f:
        f.write(md_text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
