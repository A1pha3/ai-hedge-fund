from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


DEFAULT_DOSSIER_JSON = Path("data/reports/btst_momentum_rollout_blocker_dossier_latest.json")
DEFAULT_ATTRIBUTION_JSON = Path("data/reports/btst_momentum_rollout_window_attribution_latest.json")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_momentum_rollout_triage_recommendation_latest.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_momentum_rollout_triage_recommendation_latest.md")

ALLOWED_DOMINANT_FAMILIES = {
    "missing_observability",
    "cross_window_stability",
    "risk_payoff_regression",
}
GUARDRAILS = ("no_manifest_publication", "no_btst_skill_promotion")


def _require_object(name: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SystemExit(f"{name} must be a JSON object.")
    return payload


def _require_non_negative_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SystemExit(f"{name} must be a non-negative integer.")
    if value < 0:
        raise SystemExit(f"{name} must be a non-negative integer.")
    return value


def _load_missing_theme_exposure_windows(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise SystemExit("windows_missing_theme_exposure must be a list of strings.")

    normalized_windows: list[str] = []
    seen_windows: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise SystemExit("windows_missing_theme_exposure must be a list of strings.")
        normalized_item = item.strip()
        if not normalized_item:
            raise SystemExit("windows_missing_theme_exposure must not contain blank labels.")
        if normalized_item in seen_windows:
            raise SystemExit("windows_missing_theme_exposure must not contain duplicate labels.")
        seen_windows.add(normalized_item)
        normalized_windows.append(normalized_item)
    return normalized_windows


def _render_inline_code(value: str) -> str:
    text = str(value)
    max_backtick_run = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    fence = "`" * (max_backtick_run + 1)
    return f"{fence}{text}{fence}"


def build_momentum_rollout_triage_recommendation(*, dossier: dict[str, object], attribution: dict[str, object]) -> dict[str, object]:
    normalized_dossier = _require_object("dossier", dossier)
    normalized_attribution = _require_object("attribution", attribution)

    dominant_family = str(normalized_dossier.get("dominant_family") or "").strip()
    if dominant_family not in ALLOWED_DOMINANT_FAMILIES:
        raise SystemExit("dossier dominant_family must be one of the governed rollout blocker families.")

    blocker_count = _require_non_negative_int("dossier blocker_count", normalized_dossier.get("blocker_count"))
    window_count = _require_non_negative_int("attribution window_count", normalized_attribution.get("window_count"))
    missing_theme_exposure_windows = _load_missing_theme_exposure_windows(normalized_attribution.get("windows_missing_theme_exposure", []))

    if dominant_family == "missing_observability":
        action = "measurement_fix_next"
    elif dominant_family == "cross_window_stability":
        action = "parameter_retune_next"
    else:
        action = "retain_hold"

    return {
        "action": action,
        "release_posture": "hold",
        "guardrails": list(GUARDRAILS),
        "dominant_family": dominant_family,
        "blocker_count": blocker_count,
        "window_count": window_count,
        "windows_missing_theme_exposure": missing_theme_exposure_windows,
        "missing_theme_exposure_window_count": len(missing_theme_exposure_windows),
        "fail_closed": True,
    }


def render_momentum_rollout_triage_recommendation_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Momentum Rollout Triage Recommendation",
        "",
        f"- action: {_render_inline_code(str(payload.get('action') or 'retain_hold'))}",
        f"- release_posture: {_render_inline_code(str(payload.get('release_posture') or 'hold'))}",
        f"- dominant_family: {_render_inline_code(str(payload.get('dominant_family') or 'unknown'))}",
        f"- blocker_count: {int(payload.get('blocker_count') or 0)}",
        f"- window_count: {int(payload.get('window_count') or 0)}",
        f"- missing_theme_exposure_window_count: {int(payload.get('missing_theme_exposure_window_count') or 0)}",
        f"- fail_closed: {bool(payload.get('fail_closed', True))}",
        "",
        "## Guardrails",
        "",
    ]

    guardrails = list(payload.get("guardrails") or [])
    if guardrails:
        lines.extend(f"- {_render_inline_code(str(guardrail))}" for guardrail in guardrails)
    else:
        lines.append("- _none_")

    lines.extend(["", "## Windows Missing Theme Exposure", ""])
    windows_missing_theme_exposure = list(payload.get("windows_missing_theme_exposure") or [])
    if windows_missing_theme_exposure:
        lines.extend(f"- {_render_inline_code(str(report_label))}" for report_label in windows_missing_theme_exposure)
    else:
        lines.append("- _none_")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a governed next-action artifact for the momentum rollout triage cycle.")
    parser.add_argument("--dossier-json", default=str(DEFAULT_DOSSIER_JSON))
    parser.add_argument("--attribution-json", default=str(DEFAULT_ATTRIBUTION_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args(argv)

    dossier = json.loads(Path(args.dossier_json).read_text(encoding="utf-8"))
    attribution = json.loads(Path(args.attribution_json).read_text(encoding="utf-8"))
    payload = build_momentum_rollout_triage_recommendation(dossier=dossier, attribution=attribution)

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(render_momentum_rollout_triage_recommendation_markdown(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
