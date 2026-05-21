from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


LOCAL_GRID = {
    "select_threshold": [-0.04, 0.0, 0.04],
    "recency_half_life_days": [-60, 0, 60],
    "trend_acceleration_weight": [-0.04, 0.0, 0.04],
    "close_strength_weight": [-0.04, 0.0, 0.04],
    "volume_expansion_quality_weight": [-0.04, 0.0, 0.04],
    "catalyst_freshness_weight": [-0.04, 0.0, 0.04],
}
FIXED_ZERO_PARAMS = ("momentum_strength_weight", "short_term_reversal_weight")


def build_momentum_stability_retune_surface(*, best_params: dict[str, object], triage: dict[str, object]) -> dict[str, object]:
    if str(triage.get("action") or "") != "parameter_retune_next":
        raise SystemExit("triage action must be parameter_retune_next before building a retune surface.")

    # normalize numeric best params
    normalized_best_params: dict[str, float] = {}
    for key, value in best_params.items():
        if isinstance(value, bool):
            continue
        try:
            normalized_best_params[key] = float(value)
        except Exception:
            # skip non-numeric
            continue

    fixed_params: dict[str, float] = {key: float(normalized_best_params.get(key, 0.0)) for key in FIXED_ZERO_PARAMS}
    if any(value != 0.0 for value in fixed_params.values()):
        raise SystemExit("fixed zero-weight parameters must stay disabled for this retune cycle.")

    grid: dict[str, list[Any]] = {
        "select_threshold": [round(normalized_best_params["select_threshold"] + delta, 2) for delta in LOCAL_GRID["select_threshold"]],
        "recency_half_life_days": [int(normalized_best_params["recency_half_life_days"] + delta) for delta in LOCAL_GRID["recency_half_life_days"]],
        "trend_acceleration_weight": [round(normalized_best_params["trend_acceleration_weight"] + delta, 2) for delta in LOCAL_GRID["trend_acceleration_weight"]],
        "close_strength_weight": [round(normalized_best_params["close_strength_weight"] + delta, 2) for delta in LOCAL_GRID["close_strength_weight"]],
        "volume_expansion_quality_weight": [round(normalized_best_params["volume_expansion_quality_weight"] + delta, 2) for delta in LOCAL_GRID["volume_expansion_quality_weight"]],
        "catalyst_freshness_weight": [round(normalized_best_params["catalyst_freshness_weight"] + delta, 2) for delta in LOCAL_GRID["catalyst_freshness_weight"]],
    }

    return {
        "retune_allowed": True,
        "dominant_family": str(triage.get("dominant_family") or ""),
        "best_params": normalized_best_params,
        "fixed_params": fixed_params,
        "grid": grid,
        "fail_closed": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-json", required=True)
    parser.add_argument("--triage-json", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args(argv)

    source = Path(args.source_json)
    triage_path = Path(args.triage_json)
    output_json = Path(args.output_json)
    output_md = Path(args.output_md)

    src = json.loads(source.read_text(encoding="utf-8"))
    triage = json.loads(triage_path.read_text(encoding="utf-8"))
    best_params = src.get("best_params") or {}

    payload = build_momentum_stability_retune_surface(best_params=best_params, triage=triage)

    output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # write a simple markdown summary
    md = ["# Momentum stability retune surface", "\n"]
    md.append("## Summary\n")
    md.append(f"- retune_allowed: {payload['retune_allowed']}\n")
    md.append(f"- dominant_family: {payload.get('dominant_family')}\n")
    md.append("## Grid\n")
    for k, v in payload.get("grid", {}).items():
        md.append(f"- {k}: {v}\n")
    output_md.write_text("\n".join(md), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
