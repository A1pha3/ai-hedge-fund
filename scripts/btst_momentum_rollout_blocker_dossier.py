"""Build a momentum rollout blocker dossier from optimized-profile markdown.

Minimal, surgical implementation used by tests.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List


ROLL_OUT_SECTION_RE = re.compile(r"^Rollout Blockers:\s*$", flags=re.IGNORECASE | re.MULTILINE)
BULLET_RE = re.compile(r"^-\s+(.*)")


def _extract_rollout_blocker_lines(md_text: str) -> List[str]:
    """Extract bullet lines under a "Rollout Blockers:" section.

    Returns raw bullet text (stripped) in original order. If no section found, returns [].
    """
    m = ROLL_OUT_SECTION_RE.search(md_text)
    if not m:
        return []
    # start from end of match
    start = m.end()
    lines = md_text[start:].splitlines()
    bullets: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            # stop at first blank line after section (conservative)
            if bullets:
                break
            else:
                continue
        # stop if next heading encountered
        if stripped.startswith("#"):
            break
        b = BULLET_RE.match(stripped)
        if b:
            item = b.group(1).strip()
            # remove surrounding backticks if present
            if item.startswith("`") and item.endswith("`"):
                item = item[1:-1].strip()
            bullets.append(item)
        else:
            # non-bullet line after starting bullets: treat as end
            if bullets:
                break
            # else keep scanning
    return bullets


def build_momentum_rollout_blocker_dossier(md_text: str) -> Dict[str, object]:
    """Group rollout blockers into families and surface unclassified blockers.

    Returns a dict with keys:
      - families: {missing_observability, cross_window_stability, risk_payoff_regression} -> list[str]
      - unclassified: list[str]
    """
    bullets = _extract_rollout_blocker_lines(md_text)

    families: Dict[str, List[str]] = {
        "missing_observability": [],
        "cross_window_stability": [],
        "risk_payoff_regression": [],
    }
    unclassified: List[str] = []

    for b in bullets:
        low = b.lower()
        classified = False

        # missing observability: keywords related to metrics/observability/telemetry
        if any(kw in low for kw in ("observability", "metric", "metrics", "monitor", "telemetry", "missing metric", "missing metrics")):
            families["missing_observability"].append(b)
            classified = True

        # cross-window stability: window, cross-window, alignment, inter-window
        if not classified and any(kw in low for kw in ("cross-window", "cross window", "window", "inter-window", "alignment")):
            families["cross_window_stability"].append(b)
            classified = True

        # risk/payoff regression
        if not classified and any(kw in low for kw in ("risk", "payoff", "regression", "risk/payoff")):
            families["risk_payoff_regression"].append(b)
            classified = True

        if not classified:
            unclassified.append(b)

    return {"families": families, "unclassified": unclassified}


def _render_markdown(dossier: Dict[str, object]) -> str:
    families = dossier["families"]
    unclassified = dossier.get("unclassified", [])
    lines = ["# Rollout Blocker Dossier", "", "## Families", ""]
    for k, items in families.items():
        lines.append(f"### {k}")
        if items:
            for it in items:
                lines.append(f"- {it}")
        else:
            lines.append("- _none_")
        lines.append("")
    lines.append("## Unclassified")
    if unclassified:
        for it in unclassified:
            lines.append(f"- {it}")
    else:
        lines.append("- _none_")
    lines.append("")
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-md", default=str(Path("data/reports/btst_latest_optimized_profile.md")))
    parser.add_argument("--out-dir", default=str(Path("outputs")))
    args = parser.parse_args(argv)

    in_path = Path(args.input_md)
    if not in_path.exists():
        raise SystemExit(f"Input markdown not found: {in_path}")

    md_text = in_path.read_text(encoding="utf-8")
    dossier = build_momentum_rollout_blocker_dossier(md_text)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "momentum_rollout_blocker_dossier.json"
    md_path = out_dir / "momentum_rollout_blocker_dossier.md"

    json_text = json.dumps(dossier, indent=2, ensure_ascii=False)
    json_path.write_text(json_text, encoding="utf-8")

    md_text = _render_markdown(dossier)
    md_path.write_text(md_text, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
