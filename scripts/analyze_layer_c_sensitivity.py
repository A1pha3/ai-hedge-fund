from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean


DEFAULT_SCENARIOS = {
    "current": {"b_weight": 0.4, "c_weight": 0.6, "watchlist_threshold": 0.25, "avoid_score_c_threshold": -0.30},
    "equal_weight": {"b_weight": 0.5, "c_weight": 0.5, "watchlist_threshold": 0.25, "avoid_score_c_threshold": -0.30},
    "b_heavier_0604": {"b_weight": 0.6, "c_weight": 0.4, "watchlist_threshold": 0.25, "avoid_score_c_threshold": -0.30},
    "relax_avoid_to_neg040": {"b_weight": 0.4, "c_weight": 0.6, "watchlist_threshold": 0.25, "avoid_score_c_threshold": -0.40},
    "disable_avoid_conflict": {"b_weight": 0.4, "c_weight": 0.6, "watchlist_threshold": 0.25, "avoid_score_c_threshold": None},
    "lower_watchlist_to_020": {"b_weight": 0.4, "c_weight": 0.6, "watchlist_threshold": 0.20, "avoid_score_c_threshold": -0.30},
    "b_heavier_relax_conflict": {"b_weight": 0.6, "c_weight": 0.4, "watchlist_threshold": 0.25, "avoid_score_c_threshold": -0.40},
    "b_heavier_lower_watchlist": {"b_weight": 0.6, "c_weight": 0.4, "watchlist_threshold": 0.20, "avoid_score_c_threshold": -0.40},
}


def _load_pipeline_rows(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if payload.get("event") == "pipeline_day_timing":
            rows[str(payload["trade_date"])] = payload
    return rows


def _filters(row: dict) -> dict:
    return ((row.get("current_plan") or {}).get("funnel_diagnostics") or {}).get("filters", {})


def _selected_tickers(filter_payload: dict) -> list[str]:
    return [str(item) for item in (filter_payload.get("selected_tickers") or [])]


def _ticker_map(filter_payload: dict) -> dict[str, dict]:
    entries = filter_payload.get("tickers") or []
    return {str(item.get("ticker")): item for item in entries if isinstance(item, dict) and item.get("ticker")}


def _collect_extra_records(baseline_rows: dict[str, dict], variant_rows: dict[str, dict]) -> list[dict]:
    records: list[dict] = []
    for trade_date in sorted(set(baseline_rows) & set(variant_rows)):
        baseline_layer_b = set(_selected_tickers(_filters(baseline_rows[trade_date]).get("layer_b", {})))
        variant_filters = _filters(variant_rows[trade_date])
        extra_tickers = [ticker for ticker in _selected_tickers(variant_filters.get("layer_b", {})) if ticker not in baseline_layer_b]
        if not extra_tickers:
            continue

        watchlist_map = _ticker_map(variant_filters.get("watchlist", {}))
        buy_orders_map = _ticker_map(variant_filters.get("buy_orders", {}))
        for ticker in extra_tickers:
            payload = watchlist_map.get(ticker) or buy_orders_map.get(ticker)
            if not payload:
                continue
            records.append(
                {
                    "trade_date": trade_date,
                    "ticker": ticker,
                    "score_b": float(payload.get("score_b", 0.0) or 0.0),
                    "score_c": float(payload.get("score_c", 0.0) or 0.0),
                    "score_final": float(payload.get("score_final", 0.0) or 0.0),
                    "decision": str(payload.get("decision") or ""),
                    "bc_conflict": payload.get("bc_conflict"),
                    "reasons": [str(item) for item in (payload.get("reasons") or [])],
                }
            )
    return records


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


def _evaluate_record(record: dict, scenario: dict) -> dict:
    score_b = float(record["score_b"])
    score_c = float(record["score_c"])
    score_final = (float(scenario["b_weight"]) * score_b) + (float(scenario["c_weight"]) * score_c)
    avoid_threshold = scenario.get("avoid_score_c_threshold")
    decision = _classify_score_b(score_b)
    bc_conflict = None
    if score_b > 0.50 and score_c < 0:
        bc_conflict = "b_strong_buy_c_negative"
        decision = "watch"
    if avoid_threshold is not None and score_b > 0 and score_c < float(avoid_threshold):
        bc_conflict = "b_positive_c_strong_bearish"
        decision = "avoid"

    passes_watchlist = score_final >= float(scenario["watchlist_threshold"]) and decision != "avoid"
    return {
        "score_final": score_final,
        "decision": decision,
        "bc_conflict": bc_conflict,
        "passes_watchlist": passes_watchlist,
    }


def _analyze_scenarios(records: list[dict]) -> dict[str, dict]:
    report: dict[str, dict] = {}
    for name, scenario in DEFAULT_SCENARIOS.items():
        passed: list[dict] = []
        blocked_by_avoid = 0
        blocked_by_threshold = 0
        conflict_counts: Counter = Counter()
        for record in records:
            result = _evaluate_record(record, scenario)
            if result["passes_watchlist"]:
                passed.append(
                    {
                        "trade_date": record["trade_date"],
                        "ticker": record["ticker"],
                        "score_b": round(record["score_b"], 4),
                        "score_c": round(record["score_c"], 4),
                        "score_final": round(result["score_final"], 4),
                        "decision": result["decision"],
                        "bc_conflict": result["bc_conflict"],
                    }
                )
            else:
                if result["decision"] == "avoid":
                    blocked_by_avoid += 1
                elif result["score_final"] < float(scenario["watchlist_threshold"]):
                    blocked_by_threshold += 1
            if result["bc_conflict"]:
                conflict_counts[str(result["bc_conflict"])] += 1

        report[name] = {
            "scenario": scenario,
            "extra_candidates": len(records),
            "pass_count": len(passed),
            "pass_rate": round((len(passed) / len(records)) if records else 0.0, 4),
            "blocked_by_avoid": blocked_by_avoid,
            "blocked_by_threshold": blocked_by_threshold,
            "conflict_counts": dict(conflict_counts),
            "passed_examples": passed[:20],
            "mean_pass_score_final": round(mean(item["score_final"] for item in passed), 4) if passed else None,
        }
    return report


def _print_variant_report(variant_name: str, records: list[dict], scenario_report: dict[str, dict]) -> None:
    print(f"## {variant_name}")
    print(f"extra_records: {len(records)}")
    if records:
        print(
            "observed_means:",
            {
                "score_b": round(mean(record["score_b"] for record in records), 4),
                "score_c": round(mean(record["score_c"] for record in records), 4),
                "score_final": round(mean(record["score_final"] for record in records), 4),
            },
        )
    for scenario_name, payload in scenario_report.items():
        print(
            scenario_name,
            {
                "pass_count": payload["pass_count"],
                "pass_rate": payload["pass_rate"],
                "blocked_by_avoid": payload["blocked_by_avoid"],
                "blocked_by_threshold": payload["blocked_by_threshold"],
            },
        )
        if payload["passed_examples"]:
            print("  passed_examples", payload["passed_examples"][:5])


def _write_json(output_path: Path, payload: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline sensitivity analysis for Layer C fusion using existing timing logs")
    parser.add_argument("--baseline", required=True, help="Baseline timing JSONL path")
    parser.add_argument("--variant", action="append", dest="variants", default=[], help="Variant timing JSONL path; can be passed multiple times")
    parser.add_argument("--output", required=False, help="Optional JSON output path")
    args = parser.parse_args()

    if not args.variants:
        raise ValueError("至少需要提供一个 --variant")

    baseline_rows = _load_pipeline_rows(Path(args.baseline).resolve())
    report: dict[str, dict] = {}

    for variant_arg in args.variants:
        variant_path = Path(variant_arg).resolve()
        variant_rows = _load_pipeline_rows(variant_path)
        records = _collect_extra_records(baseline_rows, variant_rows)
        scenario_report = _analyze_scenarios(records)
        report[variant_path.stem] = {
            "extra_records": records,
            "scenarios": scenario_report,
        }
        _print_variant_report(variant_path.stem, records, scenario_report)

    if args.output:
        output_path = Path(args.output).resolve()
        _write_json(output_path, report)
        print(f"saved_json: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())