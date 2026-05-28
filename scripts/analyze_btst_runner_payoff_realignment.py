from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def analyze_btst_runner_payoff_realignment(*, weekly_validation_json: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(weekly_validation_json).read_text(encoding="utf-8"))
    selected_hit_rate = float(dict(payload.get("selected_summary") or {}).get("hit_rate_15pct") or 0.0)
    near_miss_hit_rate = float(dict(payload.get("near_miss_summary") or {}).get("hit_rate_15pct") or 0.0)
    runner_recall_summary = dict(payload.get("runner_recall_summary") or {})
    report = {
        "diagnosis": {
            "primary_problem": "formal_selected_target_misalignment",
            "selected_hit_rate_15pct": round(selected_hit_rate, 4),
            "near_miss_hit_rate_15pct": round(near_miss_hit_rate, 4),
            "watchlist_filter_diagnostics_false_negatives": int(runner_recall_summary.get("watchlist_filter_diagnostics_false_negatives") or 0),
        },
        "recommendation": {
            "status": "staged_formal_shrink_plus_runner_recall",
            "next_steps": ["formal_source_shadow", "payoff_first_runner_recall"],
        },
    }
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze BTST runner/payoff weekly validation and summarize the staged recommendation.")
    parser.add_argument("weekly_validation_json", help="Path to the weekly validation JSON payload")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = analyze_btst_runner_payoff_realignment(weekly_validation_json=Path(args.weekly_validation_json))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
