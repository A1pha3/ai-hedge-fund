from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean


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
    values = filter_payload.get("selected_tickers") or []
    return [str(item) for item in values]


def _ticker_map(filter_payload: dict) -> dict[str, dict]:
    entries = filter_payload.get("tickers") or []
    return {str(item.get("ticker")): item for item in entries if isinstance(item, dict) and item.get("ticker")}


def _required_score_c(score_b: float, watchlist_threshold: float) -> float:
    return (watchlist_threshold - (0.4 * score_b)) / 0.6


def _format_reasons(payload: dict) -> tuple[str, ...]:
    reasons = payload.get("reasons")
    if reasons:
        return tuple(str(item) for item in reasons)
    reason = payload.get("reason")
    return (str(reason),) if reason else tuple()


def analyze_variant(baseline_rows: dict[str, dict], variant_rows: dict[str, dict], variant_name: str) -> dict:
    summary: dict[str, object] = {
        "variant": variant_name,
        "extra_layer_b_total": 0,
        "blocked_at_watchlist": 0,
        "blocked_at_buy_orders": 0,
        "missing_from_filters": 0,
        "reason_counts": Counter(),
        "ticker_counts": Counter(),
        "bc_conflict_counts": Counter(),
        "score_b_values": [],
        "score_c_values": [],
        "score_final_values": [],
        "score_c_gap_values": [],
        "details": [],
    }

    for trade_date in sorted(set(baseline_rows) & set(variant_rows)):
        base_filters = _filters(baseline_rows[trade_date])
        var_filters = _filters(variant_rows[trade_date])

        baseline_layer_b = set(_selected_tickers(base_filters.get("layer_b", {})))
        variant_layer_b = _selected_tickers(var_filters.get("layer_b", {}))
        extra_tickers = [ticker for ticker in variant_layer_b if ticker not in baseline_layer_b]
        if not extra_tickers:
            continue

        watchlist_map = _ticker_map(var_filters.get("watchlist", {}))
        buy_orders_map = _ticker_map(var_filters.get("buy_orders", {}))
        watchlist_threshold = float(((variant_rows[trade_date].get("current_plan") or {}).get("counts") or {}).get("watchlist_score_threshold", 0.25))

        for ticker in extra_tickers:
            summary["extra_layer_b_total"] += 1
            summary["ticker_counts"][ticker] += 1

            bucket = "missing_from_filters"
            payload: dict = {}
            if ticker in watchlist_map:
                bucket = "watchlist"
                summary["blocked_at_watchlist"] += 1
                payload = watchlist_map[ticker]
            elif ticker in buy_orders_map:
                bucket = "buy_orders"
                summary["blocked_at_buy_orders"] += 1
                payload = buy_orders_map[ticker]
            else:
                summary["missing_from_filters"] += 1

            reasons = _format_reasons(payload)
            summary["reason_counts"][(bucket, reasons)] += 1
            if payload.get("bc_conflict"):
                summary["bc_conflict_counts"][str(payload["bc_conflict"])] += 1

            score_b = payload.get("score_b")
            score_c = payload.get("score_c")
            score_final = payload.get("score_final")
            score_c_gap = None
            if isinstance(score_b, (int, float)):
                summary["score_b_values"].append(float(score_b))
            if isinstance(score_c, (int, float)):
                summary["score_c_values"].append(float(score_c))
            if isinstance(score_final, (int, float)):
                summary["score_final_values"].append(float(score_final))
            if isinstance(score_b, (int, float)) and isinstance(score_c, (int, float)):
                score_c_gap = float(score_c) - _required_score_c(float(score_b), watchlist_threshold)
                summary["score_c_gap_values"].append(score_c_gap)

            summary["details"].append(
                {
                    "trade_date": trade_date,
                    "ticker": ticker,
                    "bucket": bucket,
                    "reasons": list(reasons),
                    "bc_conflict": payload.get("bc_conflict"),
                    "decision": payload.get("decision"),
                    "score_b": score_b,
                    "score_c": score_c,
                    "score_final": score_final,
                    "required_score_c": round(_required_score_c(float(score_b), watchlist_threshold), 4) if isinstance(score_b, (int, float)) else None,
                    "score_c_gap": round(score_c_gap, 4) if isinstance(score_c_gap, float) else None,
                }
            )

    return summary


def _counter_to_lines(counter: Counter, prefix: str) -> list[str]:
    lines: list[str] = []
    for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"{prefix}{count} {key}")
    return lines


def _describe_float(values: list[float], label: str) -> str:
    if not values:
        return f"{label}: n/a"
    return f"{label}: mean={mean(values):.4f} min={min(values):.4f} max={max(values):.4f}"


def _print_summary(summary: dict) -> None:
    print(f"## {summary['variant']}")
    print(
        "counts:",
        {
            "extra_layer_b_total": summary["extra_layer_b_total"],
            "blocked_at_watchlist": summary["blocked_at_watchlist"],
            "blocked_at_buy_orders": summary["blocked_at_buy_orders"],
            "missing_from_filters": summary["missing_from_filters"],
        },
    )
    print(_describe_float(summary["score_b_values"], "score_b"))
    print(_describe_float(summary["score_c_values"], "score_c"))
    print(_describe_float(summary["score_final_values"], "score_final"))
    print(_describe_float(summary["score_c_gap_values"], "score_c_minus_required_c"))
    print("reason_counts:")
    for line in _counter_to_lines(summary["reason_counts"], "  "):
        print(line)
    print("bc_conflict_counts:")
    for line in _counter_to_lines(summary["bc_conflict_counts"], "  "):
        print(line)
    print("ticker_counts:")
    for line in _counter_to_lines(summary["ticker_counts"], "  "):
        print(line)


def _write_json(output_path: Path, payload: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {}
    for variant_name, summary in payload.items():
        serializable[variant_name] = {
            "variant": summary["variant"],
            "extra_layer_b_total": summary["extra_layer_b_total"],
            "blocked_at_watchlist": summary["blocked_at_watchlist"],
            "blocked_at_buy_orders": summary["blocked_at_buy_orders"],
            "missing_from_filters": summary["missing_from_filters"],
            "reason_counts": [{"bucket": bucket, "reasons": list(reasons), "count": count} for (bucket, reasons), count in sorted(summary["reason_counts"].items(), key=lambda item: (-item[1], item[0]))],
            "bc_conflict_counts": dict(summary["bc_conflict_counts"]),
            "ticker_counts": dict(summary["ticker_counts"]),
            "score_b": summary["score_b_values"],
            "score_c": summary["score_c_values"],
            "score_final": summary["score_final_values"],
            "score_c_gap": summary["score_c_gap_values"],
            "details": summary["details"],
        }
    output_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze why extra Layer B candidates fail to reach watchlist or buy orders")
    parser.add_argument("--baseline", required=True, help="Baseline timing JSONL path")
    parser.add_argument("--variant", action="append", dest="variants", default=[], help="Variant timing JSONL path; can be passed multiple times")
    parser.add_argument("--output", required=False, help="Optional JSON output path")
    args = parser.parse_args()

    if not args.variants:
        raise ValueError("至少需要提供一个 --variant")

    baseline_path = Path(args.baseline).resolve()
    baseline_rows = _load_pipeline_rows(baseline_path)

    report: dict[str, dict] = {}
    for variant_arg in args.variants:
        variant_path = Path(variant_arg).resolve()
        variant_rows = _load_pipeline_rows(variant_path)
        summary = analyze_variant(baseline_rows, variant_rows, variant_path.stem)
        report[variant_path.stem] = summary
        _print_summary(summary)

    if args.output:
        output_path = Path(args.output).resolve()
        _write_json(output_path, report)
        print(f"saved_json: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())