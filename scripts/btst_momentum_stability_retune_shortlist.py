from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CROSS_WINDOW_METRICS: tuple[str, ...] = (
    "win_rate_window_trend_delta",
    "win_rate_window_volatility_delta",
    "win_rate_ci_width_delta",
    "win_rate_cv_delta",
    "factor_drift_score_delta",
    "param_drift_score_delta",
    "gate_above_threshold_cv_delta",
)
RISK_METRICS: tuple[str, ...] = (
    "max_drawdown_simulated_delta",
    "downside_p10_delta",
    "liquidity_capacity_raw_100_delta",
    "t_plus_3_close_payoff_ratio_delta",
)
LOWER_IS_BETTER_METRICS: frozenset[str] = frozenset(
    {
        "win_rate_window_volatility",
        "win_rate_ci_width",
        "win_rate_cv",
        "factor_drift_score",
        "param_drift_score",
        "gate_above_threshold_cv",
        "max_drawdown_simulated",
    }
)


def _load_json_file(path: Path, *, label: str) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SystemExit(f"{label} file not found: {path}") from exc
    except OSError as exc:
        raise SystemExit(f"unable to read {label} file: {path}") from exc

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {label} file: {path}") from exc


def _write_output_file(path: Path, *, content: str, label: str) -> None:
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"unable to write {label}: {path}") from exc


def _as_mapping(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must be a JSON object.")
    return dict(value)


def _count_regressions(comparison_summary: dict[str, Any], metric_names: tuple[str, ...]) -> int:
    count = 0
    for payload in comparison_summary.values():
        if not isinstance(payload, dict):
            continue
        for metric_name in metric_names:
            value = payload.get(metric_name)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) < 0:
                count += 1
    return count


def _matches_surface(params: dict[str, Any], surface: dict[str, Any]) -> bool:
    grid = surface.get("grid")
    fixed_params = surface.get("fixed_params")
    if not isinstance(grid, dict) or not isinstance(fixed_params, dict):
        raise SystemExit("surface JSON must contain object-valued 'grid' and 'fixed_params' entries.")

    for key, allowed_values in grid.items():
        if not isinstance(allowed_values, list):
            raise SystemExit(f"surface grid for {key} must be a list.")
        if key not in params or params[key] not in allowed_values:
            return False

    for key, expected in fixed_params.items():
        if params.get(key) != expected:
            return False

    return True


def _extract_results(src: object) -> list[dict[str, Any]]:
    baseline_metrics: dict[str, Any] | None = None
    if isinstance(src, dict):
        results = src.get("results")
        best_params = src.get("best_params")
        if isinstance(best_params, dict) and isinstance(results, list):
            for row in results:
                if not isinstance(row, dict):
                    continue
                if row.get("params") == best_params and isinstance(row.get("metrics"), dict):
                    baseline_metrics = dict(row["metrics"])
                    break
    else:
        results = src
    if not isinstance(results, list):
        raise SystemExit("source JSON must contain a 'results' list.")

    normalized: list[dict[str, Any]] = []
    for row in results:
        if not isinstance(row, dict):
            raise SystemExit("each source result must be a JSON object.")
        normalized_row = dict(row)
        if not isinstance(normalized_row.get("comparison_summary"), dict) and isinstance(normalized_row.get("metrics"), dict) and baseline_metrics is not None:
            normalized_row["comparison_summary"] = _build_comparison_summary_from_metrics(dict(normalized_row["metrics"]), baseline_metrics)
        normalized.append(normalized_row)
    return normalized


def _normalize_trial_index(value: object) -> int:
    try:
        trial_index = int(value)
    except (TypeError, ValueError) as exc:
        raise SystemExit("each shortlisted source result must include an integer-valued trial_index.") from exc
    return trial_index


def _build_comparison_summary_from_metrics(metrics: dict[str, Any], baseline_metrics: dict[str, Any]) -> dict[str, dict[str, float]]:
    deltas: dict[str, float] = {}
    for delta_name in CROSS_WINDOW_METRICS + RISK_METRICS:
        metric_name = delta_name.removesuffix("_delta")
        value = metrics.get(metric_name)
        baseline_value = baseline_metrics.get(metric_name)
        if isinstance(value, bool) or isinstance(baseline_value, bool):
            continue
        if not isinstance(value, (int, float)) or not isinstance(baseline_value, (int, float)):
            continue
        candidate_value = float(value)
        baseline_float = float(baseline_value)
        if metric_name in LOWER_IS_BETTER_METRICS:
            delta = baseline_float - candidate_value
        else:
            delta = candidate_value - baseline_float
        deltas[delta_name] = round(delta, 6)
    return {"current_best": deltas}


def build_momentum_stability_retune_shortlist(*, results: list[dict[str, object]], surface: dict[str, object]) -> dict[str, object]:
    grid = surface.get("grid")
    fixed_params = surface.get("fixed_params")
    if not isinstance(grid, dict) or not isinstance(fixed_params, dict):
        raise SystemExit("surface JSON must contain object-valued 'grid' and 'fixed_params' entries.")

    local_candidates: list[dict[str, Any]] = []
    for row in results:
        params = row.get("params")
        comparison_summary = row.get("comparison_summary")
        if not isinstance(params, dict) or not isinstance(comparison_summary, dict):
            continue
        if not _matches_surface(params, surface):
            continue

        local_candidates.append(
            {
                "trial_index": _normalize_trial_index(row.get("trial_index")),
                "params": dict(params),
                "cross_window_blocker_count": _count_regressions(comparison_summary, CROSS_WINDOW_METRICS),
                "risk_blocker_count": _count_regressions(comparison_summary, RISK_METRICS),
            }
        )

    if not local_candidates:
        raise SystemExit("No governed local retune candidates matched the declared surface.")

    ordered = sorted(local_candidates, key=lambda item: (item["risk_blocker_count"], item["cross_window_blocker_count"], item["trial_index"]))
    return {
        "candidate_count": len(local_candidates),
        "best_candidate": ordered[0],
        "candidates": ordered,
        "fail_closed": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-json", required=True)
    parser.add_argument("--surface-json", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args(argv)

    source = _load_json_file(Path(args.source_json), label="source")
    surface = _load_json_file(Path(args.surface_json), label="surface")
    results = _extract_results(source)
    surface_obj = _as_mapping(surface, label="surface")

    payload = build_momentum_stability_retune_shortlist(results=results, surface=surface_obj)

    _write_output_file(Path(args.output_json), content=json.dumps(payload, indent=2), label="output JSON")
    best_candidate = payload["best_candidate"]
    md = [
        "# Momentum stability retune shortlist",
        "",
        "## Summary",
        "",
        f"- candidate_count: {payload['candidate_count']}",
        f"- best_trial_index: {best_candidate['trial_index']}",
        f"- cross_window_blockers: {best_candidate['cross_window_blocker_count']}",
        f"- risk_blockers: {best_candidate['risk_blocker_count']}",
        "",
        "## Candidates",
    ]
    for candidate in payload["candidates"]:
        md.append(
            f"- trial {candidate['trial_index']}: cross_window={candidate['cross_window_blocker_count']}, risk={candidate['risk_blocker_count']}"
        )
    _write_output_file(Path(args.output_md), content="\n".join(md) + "\n", label="output markdown")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
