"""Create an input-only active baseline snapshot from a session summary.

Validates optimization_profile_resolution and emits JSON + Markdown artifacts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

DEFAULT_INPUT = Path("data/reports/paper_trading_20260512_20260512_live_m2_7_short_trade_only_20260513_plan_optimized_verify") / "session_summary.json"
DEFAULT_JSON_OUT = Path("data/reports/btst_momentum_active_baseline_snapshot.json")
DEFAULT_MD_OUT = Path("data/reports/btst_momentum_active_baseline_snapshot.md")


def load_session_summary(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"session summary not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise SystemExit(f"failed to read session summary JSON: {e}")
    return data


def build_active_baseline_snapshot(*, session_summary: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(session_summary, dict):
        raise SystemExit("session summary must be a JSON object")

    opr = session_summary.get("optimization_profile_resolution")
    if not isinstance(opr, dict):
        raise SystemExit("missing or malformed optimization_profile_resolution")

    mode = opr.get("mode")
    status = opr.get("status")
    fallback_reason = opr.get("fallback_reason")
    if mode != "optimized" or status != "ready" or fallback_reason is not None:
        raise SystemExit("optimization_profile_resolution must have mode==optimized, status==ready, and fallback_reason==None")

    # required string fields
    required_strs = ["profile_name", "source_type", "source_path", "validated_by", "manifest_path"]
    for k in required_strs:
        v = opr.get(k)
        if not isinstance(v, str) or not v.strip():
            raise SystemExit(f"optimization_profile_resolution.{k} must be a non-empty string")

    profile_overrides = opr.get("profile_overrides")
    if profile_overrides is None:
        # allow empty dict but must be present and an object
        raise SystemExit("optimization_profile_resolution.profile_overrides must be present (object)")
    if not isinstance(profile_overrides, dict):
        raise SystemExit("optimization_profile_resolution.profile_overrides must be a JSON object")

    trade_date = opr.get("trade_date")
    if trade_date is not None and (not isinstance(trade_date, str) or not trade_date.strip()):
        raise SystemExit("optimization_profile_resolution.trade_date must be None or a non-empty string")

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


def render_active_baseline_snapshot_markdown(payload: Dict[str, Any]) -> str:
    lines = ["# BTST Momentum Active Baseline Snapshot", ""]
    lines.append(f"- profile_name: `{payload.get('profile_name')}`")
    lines.append(f"- trade_date: `{payload.get('trade_date')}`")
    lines.append(f"- source_type: `{payload.get('source_type')}`")
    lines.append(f"- source_path: `{payload.get('source_path')}`")
    lines.append(f"- validated_by: `{payload.get('validated_by')}`")
    lines.append(f"- manifest_path: `{payload.get('manifest_path')}`")
    lines.append("")
    lines.append("## Profile overrides")
    po = json.dumps(payload.get("profile_overrides", {}), indent=2)
    lines.append("```json")
    lines.append(po)
    lines.append("```")
    lines.append("")
    lines.append("## Governance")
    lines.append(f"- release_posture: `{payload.get('release_posture')}`")
    lines.append(f"- guardrails: `{payload.get('guardrails')}`")
    lines.append(f"- fail_closed: `{payload.get('fail_closed')}`")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit BTST momentum active baseline snapshot from session summary")
    parser.add_argument("--session-summary-json", default=str(DEFAULT_INPUT))
    parser.add_argument("--output-json", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--output-md", default=str(DEFAULT_MD_OUT))
    args = parser.parse_args(argv)

    input_path = Path(args.session_summary_json)
    json_out = Path(args.output_json)
    md_out = Path(args.output_md)

    session = load_session_summary(input_path)
    snapshot = build_active_baseline_snapshot(session_summary=session)

    # ensure parent directories exist
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)

    with json_out.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    md_text = render_active_baseline_snapshot_markdown(snapshot)
    with md_out.open("w", encoding="utf-8") as f:
        f.write(md_text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
