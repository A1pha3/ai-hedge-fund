from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.logging import get_logger

_SECTION_PATTERN = re.compile(r"^##\s+(?P<section>.+?)\s*$")
_ROW_PATTERN = re.compile(r"^-\s+(?P<label>[^:]+):\s*(?P<body>.+)$")

logger = get_logger(__name__)


def _coerce_value(raw: str) -> Any:
    text = raw.strip()
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def _parse_key_value_blob(blob: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for part in blob.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        parsed[key.strip()] = _coerce_value(value)
    return parsed


def parse_objective_monitor_markdown(path: str | Path) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    current_section: str | None = None
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        section_match = _SECTION_PATTERN.match(raw_line.strip())
        if section_match:
            current_section = section_match.group("section")
            payload.setdefault(current_section, {} if current_section not in {"False Negative Strict Goal Cases", "Strict Goal Cases"} else [])
            continue

        row_match = _ROW_PATTERN.match(raw_line.strip())
        if not row_match or not current_section:
            continue

        label = row_match.group("label").strip()
        body = row_match.group("body").strip()
        if current_section in {"Surface Summary", "Decision Leaderboard", "Candidate Source Leaderboard"}:
            payload.setdefault(current_section, {})
            payload[current_section][label] = _parse_key_value_blob(body)
            continue

        if current_section in {"False Negative Strict Goal Cases", "Strict Goal Cases"}:
            parts = label.split()
            entry = {"raw_label": label}
            if len(parts) >= 2:
                entry["trade_date"] = parts[0]
                entry["ticker"] = parts[1]
            entry.update(_parse_key_value_blob(body))
            payload.setdefault(current_section, [])
            payload[current_section].append(entry)
    return payload


def build_strict_btst_objective_gate(objective_monitor: dict[str, Any], structural_guardrail: dict[str, Any] | None = None) -> dict[str, Any]:
    blockers: list[str] = []
    tradeable = (((objective_monitor.get("Surface Summary") or {}).get("tradeable_surface")) or {})
    rejected = (((objective_monitor.get("Decision Leaderboard") or {}).get("rejected")) or {})
    false_negatives = list(objective_monitor.get("False Negative Strict Goal Cases") or [])
    structural_guardrail = structural_guardrail or None

    if float(rejected.get("positive_rate", 0.0) or 0.0) > float(tradeable.get("positive_rate", 0.0) or 0.0):
        blockers.append("rejected_outperforms_tradeable_surface")
    if float(rejected.get("mean_t_plus_2_return", 0.0) or 0.0) > float(tradeable.get("mean_t_plus_2_return", 0.0) or 0.0):
        blockers.append("rejected_outperforms_tradeable_return_surface")
    if false_negatives:
        blockers.append("strict_false_negative_cases_present")
    structural_guardrail_blockers = [str(blocker).strip() for blocker in list((structural_guardrail or {}).get("blockers") or []) if str(blocker).strip()]
    for blocker in structural_guardrail_blockers:
        if blocker not in blockers:
            blockers.append(blocker)
    execution_eligible_evidence = None
    if structural_guardrail:
        has_execution_eligible_evidence = "non_halt_execution_eligible_count" in structural_guardrail or "has_positive_execution_eligible_evidence" in structural_guardrail
        if has_execution_eligible_evidence:
            non_halt_execution_eligible_count = int(structural_guardrail.get("non_halt_execution_eligible_count") or 0)
            has_positive_execution_eligible_evidence = bool(
                structural_guardrail.get("has_positive_execution_eligible_evidence", non_halt_execution_eligible_count > 0)
            )
            execution_eligible_evidence = {
                "non_halt_execution_eligible_count": non_halt_execution_eligible_count,
                "has_positive_execution_eligible_evidence": has_positive_execution_eligible_evidence,
            }
            if not has_positive_execution_eligible_evidence and "no_non_halt_execution_eligible_evidence" not in blockers:
                blockers.append("no_non_halt_execution_eligible_evidence")
    if structural_guardrail and structural_guardrail.get("blocker_candidate") is True and "structural_expansion_repeated_across_windows" not in blockers:
        blockers.append("structural_expansion_repeated_across_windows")

    return {
        "action": "hold" if blockers else "promote",
        "blockers": blockers,
        "false_negative_count": len(false_negatives),
        "tradeable_surface": tradeable,
        "rejected_surface": rejected,
        "structural_guardrail": structural_guardrail,
        "execution_eligible_evidence": execution_eligible_evidence,
    }


def _load_json_payload(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_structural_guardrail(path: str | Path) -> dict[str, Any] | None:
    try:
        payload = _load_json_payload(path)
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Failed to load BTST structural guardrail sidecar from %s: %s", path, exc)
        return None
    if not isinstance(payload, Mapping):
        logger.warning("Ignoring non-mapping BTST structural guardrail sidecar from %s", path)
        return None
    raw_structural_guardrail = payload.get("structural_guardrail")
    if raw_structural_guardrail is None:
        return None
    if not isinstance(raw_structural_guardrail, Mapping):
        logger.warning("Ignoring non-mapping BTST structural guardrail payload from %s", path)
        return None
    return dict(raw_structural_guardrail)


def load_strict_btst_objective_gate_from_markdown(path: str | Path, structural_json_path: str | Path | None = None) -> dict[str, Any]:
    structural_guardrail = None
    if structural_json_path:
        structural_guardrail = _load_structural_guardrail(structural_json_path)
    return build_strict_btst_objective_gate(parse_objective_monitor_markdown(path), structural_guardrail=structural_guardrail)


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Strict BTST Objective Gate",
        "",
        f"- action: {payload['action']}",
        f"- false_negative_count: {payload['false_negative_count']}",
        "",
        "## Blockers",
        "",
    ]
    blockers = list(payload.get("blockers") or [])
    if blockers:
        for blocker in blockers:
            lines.append(f"- {blocker}")
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a strict BTST objective rollout gate from the latest objective-monitor markdown.")
    parser.add_argument("--input-md", required=True)
    parser.add_argument("--structural-json")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args(argv)

    payload = load_strict_btst_objective_gate_from_markdown(args.input_md, structural_json_path=args.structural_json)
    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(_render_markdown(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
