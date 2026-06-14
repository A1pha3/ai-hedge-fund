from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

DEFAULT_ROLLOUT_JSON = Path("data/reports/btst_momentum_rollout_blocker_dossier_latest.json")
DEFAULT_SOURCE_JSON = Path("data/reports/btst_latest_optimized_profile.json")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_momentum_rollout_window_attribution_latest.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_momentum_rollout_window_attribution_latest.md")

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

THEME_EXPOSURE_FIELDS = ("projected_theme_exposure_delta", "incremental_theme_exposure_delta")
POSITIVE_DIRECTION_REGRESSION_ROOTS = {
    "factor_drift_score",
    "gate_above_threshold_cv",
    "max_drawdown_simulated",
    "param_drift_score",
    "win_rate_ci_width",
    "win_rate_cv",
    "win_rate_window_volatility",
}


def _normalize_blocker(blocker: str) -> str:
    return str(blocker or "").strip().strip("`").strip()


def _classify_blocker(blocker: str) -> str | None:
    normalized_blocker = _normalize_blocker(blocker)
    for family_name, tokens in FAMILY_RULES.items():
        if any(token in normalized_blocker for token in tokens):
            return family_name
    return None


def _validate_rollout_blockers(rollout_blockers: list[str]) -> list[str]:
    if not isinstance(rollout_blockers, list):
        raise SystemExit("rollout_blockers must be a list of strings.")

    normalized_blockers: list[str] = []
    for blocker in rollout_blockers:
        if not isinstance(blocker, str):
            raise SystemExit("rollout_blockers must be a list of strings.")
        normalized_blocker = _normalize_blocker(blocker)
        if not normalized_blocker:
            raise SystemExit("rollout_blockers must contain non-empty strings.")
        normalized_blockers.append(normalized_blocker)

    if len(set(normalized_blockers)) != len(normalized_blockers):
        raise SystemExit("rollout_blockers must not contain duplicate blocker names.")
    return normalized_blockers


def _normalize_metric_value(report_label: str, field_name: str, value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SystemExit(f"Window '{report_label}' field '{field_name}' must be numeric or null.")
    return float(value)


def _validate_window_rows(window_rows: list[dict[str, object]]) -> list[dict[str, Any]]:
    if not isinstance(window_rows, list):
        raise SystemExit("window_rows must be a list of objects.")

    normalized_rows: list[dict[str, Any]] = []
    seen_report_labels: set[str] = set()
    for row in window_rows:
        if not isinstance(row, dict):
            raise SystemExit("window_rows must be a list of objects.")
        report_label = str(row.get("report_label") or "").strip()
        if not report_label:
            raise SystemExit("Each window row must include a non-empty report_label.")
        if report_label in seen_report_labels:
            raise SystemExit("Each window row must include a unique report_label.")
        seen_report_labels.add(report_label)

        normalized_row: dict[str, Any] = {"report_label": report_label}
        for field_name, field_value in row.items():
            if field_name == "report_label":
                continue
            normalized_row[field_name] = _normalize_metric_value(report_label, field_name, field_value)
        normalized_rows.append(normalized_row)

    return normalized_rows


def _load_rollout_blockers(rollout_payload: dict[str, Any]) -> list[str]:
    blockers = rollout_payload.get("blockers")
    if blockers is not None:
        return _validate_rollout_blockers(blockers)

    families = rollout_payload.get("families")
    if isinstance(families, dict):
        if not families:
            raise SystemExit("families must include at least one family entry when reading a dossier JSON.")
        family_blockers: list[str] = []
        for family_payload in families.values():
            if not isinstance(family_payload, dict):
                raise SystemExit("families entries must be objects when reading a dossier JSON.")
            raw_family_blockers = family_payload.get("blockers")
            if raw_family_blockers is None:
                raise SystemExit("families entries must include a blockers list when reading a dossier JSON.")
            family_blockers.extend(_validate_rollout_blockers(raw_family_blockers))
        return family_blockers

    raise SystemExit("Rollout JSON must contain either 'blockers' or dossier-style 'families.blockers'.")


def _load_window_rows(source_payload: dict[str, Any]) -> list[dict[str, Any]]:
    window_rows = source_payload.get("window_rows")
    if window_rows is not None:
        return _validate_window_rows(window_rows)

    comparison_summary = source_payload.get("comparison_summary")
    if isinstance(comparison_summary, dict):
        if not comparison_summary:
            raise SystemExit("comparison_summary must include at least one baseline delta row.")

        synthesized_rows: list[dict[str, Any]] = []
        for report_label, comparison_payload in comparison_summary.items():
            if not isinstance(comparison_payload, dict):
                raise SystemExit("comparison_summary entries must be objects.")

            row: dict[str, Any] = {"report_label": str(report_label).strip()}
            for field_name, field_value in comparison_payload.items():
                if field_name.endswith("_delta"):
                    row[field_name] = field_value
            synthesized_rows.append(row)

        return _validate_window_rows(synthesized_rows)

    raise SystemExit("Source JSON must contain 'window_rows' or 'comparison_summary'.")


def _derive_metric_field_candidates(blocker: str) -> tuple[str, ...]:
    """Map a blocker name to the window-row metric fields that can explain it."""
    if blocker.startswith("missing_projected_theme_exposure_delta"):
        return ("projected_theme_exposure_delta",)
    if blocker.startswith("missing_incremental_theme_exposure_delta"):
        return ("incremental_theme_exposure_delta",)

    blocker_root = blocker.split("_vs_", 1)[0]
    if blocker_root.endswith("_regressed"):
        blocker_root = blocker_root.removesuffix("_regressed")

    candidates = [blocker_root]
    if not blocker_root.endswith("_delta"):
        candidates.insert(0, f"{blocker_root}_delta")
    return tuple(dict.fromkeys(candidates))


def _is_regression_value(blocker: str, metric_value: float) -> bool:
    blocker_root = blocker.split("_vs_", 1)[0]
    if blocker_root.endswith("_regressed"):
        blocker_root = blocker_root.removesuffix("_regressed")
    if blocker_root in POSITIVE_DIRECTION_REGRESSION_ROOTS:
        return metric_value > 0
    return metric_value < 0


def _render_inline_code(value: str) -> str:
    text = str(value)
    max_backtick_run = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    fence = "`" * (max_backtick_run + 1)
    return f"{fence}{text}{fence}"


def _windows_missing_theme_exposure(window_rows: list[dict[str, Any]]) -> tuple[list[str], dict[str, list[str]]]:
    windows: list[str] = []
    surfaces: dict[str, list[str]] = {}
    for row in window_rows:
        missing_surfaces = [field_name for field_name in THEME_EXPOSURE_FIELDS if field_name in row and row.get(field_name) is None]
        if missing_surfaces:
            report_label = str(row["report_label"])
            windows.append(report_label)
            surfaces[report_label] = missing_surfaces
    return sorted(windows), {label: surfaces[label] for label in sorted(surfaces)}


def _attribute_windows_for_blocker(blocker: str, window_rows: list[dict[str, Any]]) -> list[str]:
    family_name = _classify_blocker(blocker)
    if family_name == "missing_observability":
        target_fields = set(_derive_metric_field_candidates(blocker))
        return sorted([str(row["report_label"]) for row in window_rows if any(field_name in row and row.get(field_name) is None for field_name in target_fields)])

    candidate_fields = _derive_metric_field_candidates(blocker)
    attributed_windows: list[str] = []
    for row in window_rows:
        for field_name in candidate_fields:
            metric_value = row.get(field_name)
            if metric_value is None:
                continue
            if _is_regression_value(blocker, float(metric_value)):
                attributed_windows.append(str(row["report_label"]))
                break
    return sorted(dict.fromkeys(attributed_windows))


def build_momentum_rollout_window_attribution(*, rollout_blockers: list[str], window_rows: list[dict[str, object]]) -> dict[str, object]:
    normalized_blockers = _validate_rollout_blockers(rollout_blockers)
    normalized_rows = _validate_window_rows(window_rows)
    family_counts: dict[str, int] = {family_name: 0 for family_name in FAMILY_RULES}
    windows_by_blocker: dict[str, list[str]] = {}

    for blocker in normalized_blockers:
        family_name = _classify_blocker(blocker)
        if family_name is not None:
            family_counts[family_name] += 1
        windows_by_blocker[blocker] = _attribute_windows_for_blocker(blocker, normalized_rows)

    dominant_family = None
    if normalized_blockers and max(family_counts.values(), default=0) > 0:
        dominant_family = sorted(family_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    windows_missing_theme_exposure, missing_theme_exposure_surfaces = _windows_missing_theme_exposure(normalized_rows)
    dominant_family_windows = sorted(
        {
            report_label
            for blocker, report_labels in windows_by_blocker.items()
            if dominant_family is not None and _classify_blocker(blocker) == dominant_family
            for report_label in report_labels
        }
    )

    return {
        "blocker_count": len(normalized_blockers),
        "window_count": len(normalized_rows),
        "dominant_family": dominant_family,
        "family_counts": family_counts,
        "windows_by_blocker": windows_by_blocker,
        "dominant_family_windows": dominant_family_windows,
        "windows_missing_theme_exposure": windows_missing_theme_exposure,
        "missing_theme_exposure_surfaces": missing_theme_exposure_surfaces,
        "fail_closed": True,
    }


def render_momentum_rollout_window_attribution_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Momentum Rollout Window Attribution",
        "",
        f"- blocker_count: {int(payload.get('blocker_count') or 0)}",
        f"- window_count: {int(payload.get('window_count') or 0)}",
        f"- dominant_family: {payload.get('dominant_family') or 'none'}",
        f"- fail_closed: {bool(payload.get('fail_closed', True))}",
        "",
        "## Family Counts",
        "",
    ]

    family_counts = dict(payload.get("family_counts") or {})
    for family_name in ("missing_observability", "cross_window_stability", "risk_payoff_regression"):
        lines.append(f"- {family_name}: {int(family_counts.get(family_name) or 0)}")

    lines.extend(["", "## Dominant Family Windows", ""])
    dominant_family_windows = list(payload.get("dominant_family_windows") or [])
    if dominant_family_windows:
        lines.extend(f"- {_render_inline_code(str(report_label))}" for report_label in dominant_family_windows)
    else:
        lines.append("- _none_")

    lines.extend(["", "## Windows Missing Theme Exposure", ""])
    windows_missing_theme_exposure = list(payload.get("windows_missing_theme_exposure") or [])
    missing_theme_exposure_surfaces = dict(payload.get("missing_theme_exposure_surfaces") or {})
    if windows_missing_theme_exposure:
        for report_label in windows_missing_theme_exposure:
            missing_surfaces = ", ".join(missing_theme_exposure_surfaces.get(report_label) or [])
            lines.append(f"- {_render_inline_code(str(report_label))}: {missing_surfaces}")
    else:
        lines.append("- _none_")

    lines.extend(["", "## Blocker Window Attribution", ""])
    windows_by_blocker = dict(payload.get("windows_by_blocker") or {})
    if windows_by_blocker:
        for blocker in sorted(windows_by_blocker):
            report_labels = list(windows_by_blocker.get(blocker) or [])
            if report_labels:
                rendered_labels = ", ".join(_render_inline_code(str(report_label)) for report_label in report_labels)
                lines.append(f"- {_render_inline_code(str(blocker))} -> {rendered_labels}")
            else:
                lines.append(f"- {_render_inline_code(str(blocker))} -> _none_")
    else:
        lines.append("- _none_")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a fail-closed window-attribution artifact for the momentum rollout line.")
    parser.add_argument("--rollout-json", default=str(DEFAULT_ROLLOUT_JSON))
    parser.add_argument("--source-json", default=str(DEFAULT_SOURCE_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args(argv)

    rollout_payload = json.loads(Path(args.rollout_json).read_text(encoding="utf-8"))
    source_payload = json.loads(Path(args.source_json).read_text(encoding="utf-8"))
    payload = build_momentum_rollout_window_attribution(rollout_blockers=_load_rollout_blockers(rollout_payload), window_rows=_load_window_rows(source_payload))

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(render_momentum_rollout_window_attribution_markdown(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
