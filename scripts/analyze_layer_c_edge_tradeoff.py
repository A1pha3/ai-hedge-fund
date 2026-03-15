from __future__ import annotations

import argparse
import json
from itertools import product
from pathlib import Path


DEFAULT_SCENARIOS = {
    "current": {
        "b_weight": 0.4,
        "c_weight": 0.6,
        "watchlist_threshold": 0.25,
        "avoid_score_c_threshold": -0.30,
        "investor_scale": 1.0,
        "analyst_scale": 1.0,
        "other_scale": 1.0,
    },
    "watchlist_020_only": {
        "b_weight": 0.4,
        "c_weight": 0.6,
        "watchlist_threshold": 0.20,
        "avoid_score_c_threshold": -0.30,
        "investor_scale": 1.0,
        "analyst_scale": 1.0,
        "other_scale": 1.0,
    },
    "investor_090_only": {
        "b_weight": 0.4,
        "c_weight": 0.6,
        "watchlist_threshold": 0.25,
        "avoid_score_c_threshold": -0.30,
        "investor_scale": 0.90,
        "analyst_scale": 1.0,
        "other_scale": 1.0,
    },
    "investor_090_b055_watch020": {
        "b_weight": 0.55,
        "c_weight": 0.45,
        "watchlist_threshold": 0.20,
        "avoid_score_c_threshold": -0.30,
        "investor_scale": 0.90,
        "analyst_scale": 1.0,
        "other_scale": 1.0,
    },
    "investor_085_b060_watch020_relax040": {
        "b_weight": 0.60,
        "c_weight": 0.40,
        "watchlist_threshold": 0.20,
        "avoid_score_c_threshold": -0.40,
        "investor_scale": 0.85,
        "analyst_scale": 1.0,
        "other_scale": 1.0,
    },
    "investor_090_b060_watch018": {
        "b_weight": 0.60,
        "c_weight": 0.40,
        "watchlist_threshold": 0.18,
        "avoid_score_c_threshold": -0.30,
        "investor_scale": 0.90,
        "analyst_scale": 1.0,
        "other_scale": 1.0,
    },
}

GRID_INVESTOR_SCALES = [0.95, 0.925, 0.90, 0.875, 0.85]
GRID_B_WEIGHTS = [0.50, 0.525, 0.55, 0.575, 0.60]
GRID_WATCHLIST_THRESHOLDS = [0.22, 0.21, 0.20, 0.19, 0.18]
GRID_AVOID_THRESHOLDS = [-0.30, -0.35, -0.40]


def _classify_score_b(score_b: float) -> str:
    if score_b > 0.50:
        return "strong_buy"
    if score_b >= 0.35:
        return "watch"
    if score_b >= -0.20:
        return "neutral"
    if score_b >= -0.50:
        return "sell"
    return "strong_sell"


def _classify_sample(replay: dict) -> str:
    if replay.get("bc_conflict") == "b_positive_c_strong_bearish":
        return "structural_conflict"
    if replay.get("bc_conflict") is None and replay.get("decision") == "watch":
        return "edge_watch_threshold"
    return "other"


def _load_records(paths: list[Path]) -> list[dict]:
    records: list[dict] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload.get("comparisons", []):
            replay = row.get("replay") or {}
            summary = (replay.get("agent_contribution_summary") or {}).get("cohort_contributions") or {}
            records.append(
                {
                    "source": str(path),
                    "variant": row.get("variant"),
                    "trade_date": row.get("trade_date"),
                    "ticker": row.get("ticker"),
                    "score_b": float(replay.get("score_b", 0.0) or 0.0),
                    "score_c": float(replay.get("score_c", 0.0) or 0.0),
                    "score_final": float(replay.get("score_final", 0.0) or 0.0),
                    "decision": str(replay.get("decision") or ""),
                    "bc_conflict": replay.get("bc_conflict"),
                    "sample_class": _classify_sample(replay),
                    "cohort_contributions": {
                        "investor": float(summary.get("investor", 0.0) or 0.0),
                        "analyst": float(summary.get("analyst", 0.0) or 0.0),
                        "other": float(summary.get("other", 0.0) or 0.0),
                    },
                }
            )
    return records


def _evaluate_record(record: dict, scenario: dict) -> dict:
    score_c = (
        record["cohort_contributions"]["investor"] * float(scenario["investor_scale"])
        + record["cohort_contributions"]["analyst"] * float(scenario["analyst_scale"])
        + record["cohort_contributions"]["other"] * float(scenario["other_scale"])
    )
    score_b = float(record["score_b"])
    decision = _classify_score_b(score_b)
    bc_conflict = None

    if score_b > 0.50 and score_c < 0:
        bc_conflict = "b_strong_buy_c_negative"
        decision = "watch"
    if scenario["avoid_score_c_threshold"] is not None and score_b > 0 and score_c < float(scenario["avoid_score_c_threshold"]):
        bc_conflict = "b_positive_c_strong_bearish"
        decision = "avoid"

    score_final = (float(scenario["b_weight"]) * score_b) + (float(scenario["c_weight"]) * score_c)
    passes_watchlist = score_final >= float(scenario["watchlist_threshold"]) and decision != "avoid"
    return {
        "score_c": round(score_c, 4),
        "score_final": round(score_final, 4),
        "decision": decision,
        "bc_conflict": bc_conflict,
        "passes_watchlist": passes_watchlist,
    }


def _summarize_scenario(records: list[dict], scenario_name: str, scenario: dict) -> dict:
    edge_passes: list[dict] = []
    structural_leaks: list[dict] = []
    evaluated_rows: list[dict] = []

    for record in records:
        evaluated = _evaluate_record(record, scenario)
        row = {
            "trade_date": record["trade_date"],
            "ticker": record["ticker"],
            "variant": record["variant"],
            "sample_class": record["sample_class"],
            **evaluated,
        }
        evaluated_rows.append(row)
        if record["sample_class"] == "edge_watch_threshold" and evaluated["passes_watchlist"]:
            edge_passes.append(row)
        if record["sample_class"] == "structural_conflict" and evaluated["passes_watchlist"]:
            structural_leaks.append(row)

    edge_total = sum(1 for record in records if record["sample_class"] == "edge_watch_threshold")
    structural_total = sum(1 for record in records if record["sample_class"] == "structural_conflict")

    return {
        "scenario": scenario,
        "edge_total": edge_total,
        "edge_pass_count": len(edge_passes),
        "edge_pass_examples": edge_passes,
        "structural_total": structural_total,
        "structural_blocked_count": structural_total - len(structural_leaks),
        "structural_leak_count": len(structural_leaks),
        "structural_leak_examples": structural_leaks,
        "all_rows": evaluated_rows,
        "status": "clean_edge_gain" if edge_passes and not structural_leaks else "no_gain" if not edge_passes else "leaky",
        "scenario_name": scenario_name,
    }


def _print_summary(report: dict) -> None:
    sample_counts = report["sample_counts"]
    print("sample_counts", sample_counts)
    for name, payload in report["scenarios"].items():
        print(
            name,
            {
                "status": payload["status"],
                "edge_pass_count": payload["edge_pass_count"],
                "structural_leak_count": payload["structural_leak_count"],
            },
        )
        if payload["edge_pass_examples"]:
            print("  edge_pass_examples", payload["edge_pass_examples"])
        if payload["structural_leak_examples"]:
            print("  structural_leak_examples", payload["structural_leak_examples"])
    grid_search = report.get("grid_search") or {}
    ranked_clean = grid_search.get("top_clean_candidates") or []
    if ranked_clean:
        print("top_clean_candidates")
        for candidate in ranked_clean:
            print(" ", candidate)


def _scenario_penalty(scenario: dict) -> float:
    return round(
        ((1.0 - float(scenario["investor_scale"])) * 2.0)
        + (float(scenario["b_weight"]) - 0.40)
        + ((0.25 - float(scenario["watchlist_threshold"])) * 2.0)
        + max(0.0, abs(float(scenario["avoid_score_c_threshold"])) - 0.30 if scenario["avoid_score_c_threshold"] is not None else 0.20),
        4,
    )


def _build_grid_scenarios() -> dict[str, dict]:
    scenarios: dict[str, dict] = {}
    for investor_scale, b_weight, watchlist_threshold, avoid_threshold in product(
        GRID_INVESTOR_SCALES,
        GRID_B_WEIGHTS,
        GRID_WATCHLIST_THRESHOLDS,
        GRID_AVOID_THRESHOLDS,
    ):
        scenario_name = (
            f"grid_inv_{int(investor_scale * 1000):03d}_"
            f"b_{int(b_weight * 1000):03d}_"
            f"watch_{int(watchlist_threshold * 1000):03d}_"
            f"avoid_{int(abs(avoid_threshold) * 1000):03d}"
        )
        scenarios[scenario_name] = {
            "b_weight": b_weight,
            "c_weight": round(1.0 - b_weight, 3),
            "watchlist_threshold": watchlist_threshold,
            "avoid_score_c_threshold": avoid_threshold,
            "investor_scale": investor_scale,
            "analyst_scale": 1.0,
            "other_scale": 1.0,
        }
    return scenarios


def _run_grid_search(records: list[dict], limit: int) -> dict:
    grid_scenarios = _build_grid_scenarios()
    ranked_rows: list[dict] = []
    for name, scenario in grid_scenarios.items():
        summary = _summarize_scenario(records, name, scenario)
        ranked_rows.append(
            {
                "scenario_name": name,
                "scenario": scenario,
                "status": summary["status"],
                "edge_pass_count": summary["edge_pass_count"],
                "edge_pass_examples": summary["edge_pass_examples"],
                "structural_leak_count": summary["structural_leak_count"],
                "structural_leak_examples": summary["structural_leak_examples"],
                "penalty": _scenario_penalty(scenario),
            }
        )

    ranked_rows.sort(
        key=lambda item: (
            -item["edge_pass_count"],
            item["structural_leak_count"],
            item["penalty"],
            item["scenario"]["watchlist_threshold"],
        )
    )
    clean_candidates = [item for item in ranked_rows if item["edge_pass_count"] > 0 and item["structural_leak_count"] == 0]
    return {
        "grid_size": len(ranked_rows),
        "top_clean_candidates": clean_candidates[:limit],
        "top_all_candidates": ranked_rows[:limit],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Layer C edge-vs-structural tradeoffs from focused replay artifacts")
    parser.add_argument("--input", action="append", dest="inputs", default=[], help="Focused replay JSON path; can be passed multiple times")
    parser.add_argument("--output", required=False, help="Optional JSON output path")
    parser.add_argument("--grid-search", action="store_true", help="Run fine-grained grid search around the current candidate region")
    parser.add_argument("--grid-limit", type=int, default=12, help="How many ranked grid candidates to keep")
    args = parser.parse_args()

    if not args.inputs:
        raise ValueError("至少需要提供一个 --input")

    paths = [Path(item).resolve() for item in args.inputs]
    records = _load_records(paths)
    report = {
        "inputs": [str(path) for path in paths],
        "sample_counts": {
            "total": len(records),
            "edge_watch_threshold": sum(1 for record in records if record["sample_class"] == "edge_watch_threshold"),
            "structural_conflict": sum(1 for record in records if record["sample_class"] == "structural_conflict"),
            "other": sum(1 for record in records if record["sample_class"] == "other"),
        },
        "scenarios": {name: _summarize_scenario(records, name, scenario) for name, scenario in DEFAULT_SCENARIOS.items()},
    }

    if args.grid_search:
        report["grid_search"] = _run_grid_search(records, max(1, args.grid_limit))

    _print_summary(report)

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved_json: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())