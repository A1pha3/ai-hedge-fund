from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_INPUT_MD = Path("data/reports/btst_latest_optimized_profile.md")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_momentum_rollout_blocker_dossier_latest.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_momentum_rollout_blocker_dossier_latest.md")

FAMILY_RULES: dict[str, tuple[str, ...]] = {
    "missing_observability": (
        "missing_projected_theme_exposure_delta",
        "missing_incremental_theme_exposure_delta",
    ),
    "cross_window_stability": (
        "win_rate_window_",
        "win_rate_ci_width",
        "win_rate_cv",
        "param_drift_score",
        "factor_drift_score",
        "gate_above_threshold_cv",
    ),
    "risk_payoff_regression": (
        "downside_p10",
        "liquidity_capacity_raw_100",
        "max_drawdown_simulated",
        "t_plus_3_close_payoff_ratio",
    ),
}


def _normalize_blocker(blocker: str) -> str:
    return str(blocker or "").strip().strip("`").strip()


def parse_rollout_blockers_from_markdown(markdown_text: str) -> list[str]:
    blockers: list[str] = []
    in_blocker_section = False

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not in_blocker_section:
            if line == "Rollout Blockers:":
                in_blocker_section = True
            continue

        if not line:
            continue
        if line.startswith("#"):
            break
        if not line.startswith("- "):
            if blockers:
                break
            continue

        blocker = _normalize_blocker(line.removeprefix("- "))
        if blocker:
            blockers.append(blocker)

    return blockers


def load_rollout_blockers_from_markdown(markdown_text: str) -> list[str]:
    blockers = parse_rollout_blockers_from_markdown(markdown_text)
    if blockers:
        return blockers
    raise SystemExit("Rollout Blockers section missing or empty; refusing to emit an empty dossier.")


def build_momentum_rollout_blocker_dossier(blockers: list[str]) -> dict[str, Any]:
    normalized_blockers = [_normalize_blocker(blocker) for blocker in blockers if _normalize_blocker(blocker)]
    families: dict[str, dict[str, Any]] = {}
    classified_blockers: set[str] = set()

    for family_name, tokens in FAMILY_RULES.items():
        family_blockers = [blocker for blocker in normalized_blockers if any(token in blocker for token in tokens)]
        families[family_name] = {
            "count": len(family_blockers),
            "blockers": family_blockers,
        }
        classified_blockers.update(family_blockers)

    family_counts = {family_name: int(payload["count"]) for family_name, payload in families.items()}
    dominant_family = None
    if normalized_blockers and max(family_counts.values(), default=0) > 0:
        dominant_family = sorted(family_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    unclassified_blockers = [blocker for blocker in normalized_blockers if blocker not in classified_blockers]
    return {
        "blocker_count": len(normalized_blockers),
        "families": families,
        "dominant_family": dominant_family,
        "unclassified_blockers": unclassified_blockers,
        "fail_closed": True,
    }


def render_momentum_rollout_blocker_dossier_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Momentum Rollout Blocker Dossier",
        "",
        f"- blocker_count: {payload.get('blocker_count', 0)}",
        f"- dominant_family: {payload.get('dominant_family') or 'none'}",
        f"- fail_closed: {bool(payload.get('fail_closed', True))}",
        "",
        "## Families",
        "",
    ]

    families = dict(payload.get("families") or {})
    for family_name in ("missing_observability", "cross_window_stability", "risk_payoff_regression"):
        family_payload = dict(families.get(family_name) or {})
        lines.append(f"### {family_name}")
        lines.append(f"- count: {int(family_payload.get('count') or 0)}")
        blockers = list(family_payload.get("blockers") or [])
        if blockers:
            lines.extend(f"- `{blocker}`" for blocker in blockers)
        else:
            lines.append("- _none_")
        lines.append("")

    lines.append("## Unclassified Blockers")
    unclassified_blockers = list(payload.get("unclassified_blockers") or [])
    if unclassified_blockers:
        lines.extend(f"- `{blocker}`" for blocker in unclassified_blockers)
    else:
        lines.append("- _none_")
    lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a fail-closed blocker dossier for the momentum rollout line.")
    parser.add_argument("--input-md", default=str(DEFAULT_INPUT_MD))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args(argv)

    input_md = Path(args.input_md)
    output_json = Path(args.output_json)
    output_md = Path(args.output_md)

    markdown_text = input_md.read_text(encoding="utf-8")
    blockers = load_rollout_blockers_from_markdown(markdown_text)
    payload = build_momentum_rollout_blocker_dossier(blockers)

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(render_momentum_rollout_blocker_dossier_markdown(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
