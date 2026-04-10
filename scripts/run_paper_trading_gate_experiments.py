from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


DEFAULT_FAST_SCORE_THRESHOLD = 0.38
DEFAULT_WATCHLIST_SCORE_THRESHOLD = 0.20
FROZEN_POST_MARKET_GATE_ENV_KEYS = {
    "DAILY_PIPELINE_FAST_SCORE_THRESHOLD",
    "DAILY_PIPELINE_WATCHLIST_SCORE_THRESHOLD",
    "DAILY_PIPELINE_LAYER_C_BLEND_B_WEIGHT",
    "DAILY_PIPELINE_LAYER_C_BLEND_C_WEIGHT",
    "DAILY_PIPELINE_LAYER_C_AVOID_SCORE_C_THRESHOLD",
}


VARIANTS: dict[str, dict[str, object]] = {
    "baseline": {
        "description": "Current default gate settings with no overrides.",
        "env": {},
    },
    "fast_0375": {
        "description": "Only lower Layer B fast threshold from 0.38 to 0.375.",
        "env": {
            "DAILY_PIPELINE_FAST_SCORE_THRESHOLD": "0.375",
        },
    },
    "watchlist_019": {
        "description": "Only lower watchlist threshold from 0.20 to 0.19.",
        "env": {
            "DAILY_PIPELINE_WATCHLIST_SCORE_THRESHOLD": "0.19",
        },
    },
    "fast_0375_watchlist_019": {
        "description": "Lower Layer B threshold to 0.375 and watchlist threshold to 0.19.",
        "env": {
            "DAILY_PIPELINE_FAST_SCORE_THRESHOLD": "0.375",
            "DAILY_PIPELINE_WATCHLIST_SCORE_THRESHOLD": "0.19",
        },
    },
}


def _default_output_root(start_date: str, end_date: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("data/reports") / f"paper_trading_gate_experiments_{start_date.replace('-', '')}_{end_date.replace('-', '')}_{timestamp}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run frozen paper-trading gate experiments and summarize selection artifacts.")
    parser.add_argument("--start-date", required=True, help="Start date in YYYY-MM-DD format")
    parser.add_argument("--end-date", required=True, help="End date in YYYY-MM-DD format")
    parser.add_argument("--frozen-plan-source", required=True, help="Path to historical daily_events.jsonl used as the frozen replay source")
    parser.add_argument("--model-name", default=None, help="Optional model name passed through to run_paper_trading.py")
    parser.add_argument("--model-provider", default=None, help="Optional model provider passed through to run_paper_trading.py")
    parser.add_argument("--initial-capital", type=float, default=100000.0, help="Initial capital passed through to run_paper_trading.py")
    parser.add_argument(
        "--variants",
        default="baseline,fast_0375,watchlist_019,fast_0375_watchlist_019",
        help="Comma-separated variant names. Available: " + ", ".join(sorted(VARIANTS.keys())),
    )
    parser.add_argument("--output-root", default=None, help="Directory root for per-variant outputs and the final report")
    return parser.parse_args()


def _build_variant_output_dir(output_root: Path, variant_name: str) -> Path:
    return output_root / variant_name


def _extract_env_float(env_updates: dict[str, str], key: str) -> float | None:
    raw_value = env_updates.get(key)
    if raw_value is None:
        return None
    try:
        return float(raw_value)
    except ValueError:
        return None


def _run_variant(repo_root: Path, output_dir: Path, args: argparse.Namespace, variant_name: str, env_updates: dict[str, str]) -> dict:
    command = [
        sys.executable,
        "scripts/run_paper_trading.py",
        "--start-date",
        args.start_date,
        "--end-date",
        args.end_date,
        "--frozen-plan-source",
        str(Path(args.frozen_plan_source).resolve()),
        "--initial-capital",
        str(args.initial_capital),
        "--output-dir",
        str(output_dir),
    ]
    if args.model_name:
        command.extend(["--model-name", args.model_name])
    if args.model_provider:
        command.extend(["--model-provider", args.model_provider])

    env = os.environ.copy()
    env.update(env_updates)

    completed = subprocess.run(command, cwd=repo_root, env=env, capture_output=True, text=True, check=False)
    return {
        "variant": variant_name,
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "output_dir": str(output_dir),
    }


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _iter_selection_snapshots(selection_root: Path):
    for day_dir in sorted(path for path in selection_root.iterdir() if path.is_dir()):
        yield _load_json(day_dir / "selection_snapshot.json")


def _summarize_selection_artifacts(output_dir: Path) -> dict:
    selection_root = output_dir / "selection_artifacts"
    if not selection_root.exists():
        return {
            "selection_artifact_root": str(selection_root),
            "exists": False,
        }

    selected_freq: Counter[str] = Counter()
    rejected_freq: Counter[str] = Counter()
    buy_order_freq: Counter[str] = Counter()
    layer_b_reason_counts: Counter[str] = Counter()
    watchlist_reason_counts: Counter[str] = Counter()
    buy_order_reason_counts: Counter[str] = Counter()
    rows: list[dict] = []

    for day_dir in sorted(path for path in selection_root.iterdir() if path.is_dir()):
        snapshot = _load_json(day_dir / "selection_snapshot.json")
        universe = snapshot.get("universe_summary", {})
        filters = snapshot.get("funnel_diagnostics", {}).get("filters", {})
        layer_b = filters.get("layer_b", {})
        watchlist = filters.get("watchlist", {})
        buy_orders = filters.get("buy_orders", {})

        layer_b_reason_counts.update(layer_b.get("reason_counts", {}))
        watchlist_reason_counts.update(watchlist.get("reason_counts", {}))
        buy_order_reason_counts.update(buy_orders.get("reason_counts", {}))

        for item in snapshot.get("selected", []):
            symbol = item.get("symbol")
            if symbol:
                selected_freq[str(symbol)] += 1
        for item in snapshot.get("rejected", []):
            symbol = item.get("symbol")
            if symbol:
                rejected_freq[str(symbol)] += 1
        for item in snapshot.get("buy_orders", []):
            ticker = item.get("ticker") or item.get("symbol")
            if ticker:
                buy_order_freq[str(ticker)] += 1

        rows.append(
            {
                "trade_date": snapshot.get("trade_date"),
                "candidate_count": universe.get("candidate_count", 0),
                "high_pool_count": universe.get("high_pool_count", 0),
                "watchlist_count": universe.get("watchlist_count", 0),
                "buy_order_count": universe.get("buy_order_count", 0),
            }
        )

    zero_high_pool_days = [row["trade_date"] for row in rows if row["high_pool_count"] == 0]
    zero_watchlist_days = [row["trade_date"] for row in rows if row["high_pool_count"] > 0 and row["watchlist_count"] == 0]
    zero_buy_order_days = [row["trade_date"] for row in rows if row["watchlist_count"] > 0 and row["buy_order_count"] == 0]

    return {
        "selection_artifact_root": str(selection_root),
        "exists": True,
        "day_count": len(rows),
        "total_candidate_count": sum(row["candidate_count"] for row in rows),
        "total_high_pool_count": sum(row["high_pool_count"] for row in rows),
        "total_watchlist_count": sum(row["watchlist_count"] for row in rows),
        "total_buy_order_count": sum(row["buy_order_count"] for row in rows),
        "zero_high_pool_days": zero_high_pool_days,
        "nonzero_high_pool_zero_watchlist_days": zero_watchlist_days,
        "nonzero_watchlist_zero_buy_days": zero_buy_order_days,
        "layer_b_reason_counts": dict(layer_b_reason_counts),
        "watchlist_reason_counts": dict(watchlist_reason_counts),
        "buy_order_reason_counts": dict(buy_order_reason_counts),
        "selected_freq_top10": selected_freq.most_common(10),
        "rejected_freq_top10": rejected_freq.most_common(10),
        "buy_order_freq_top10": buy_order_freq.most_common(10),
    }


def _extract_plan_generation_mode(session_summary: dict | None) -> str | None:
    if not session_summary:
        return None
    plan_generation = session_summary.get("plan_generation") or {}
    mode = plan_generation.get("mode")
    return str(mode) if mode else None


def _build_fast_threshold_margin(selection_root: Path, proposed_fast_threshold: float) -> dict[str, object]:
    released_examples: list[dict[str, object]] = []
    for snapshot in _iter_selection_snapshots(selection_root):
        layer_b = ((snapshot.get("funnel_diagnostics") or {}).get("filters") or {}).get("layer_b") or {}
        for item in layer_b.get("tickers") or []:
            score_b = item.get("score_b")
            if score_b is None:
                continue
            if proposed_fast_threshold <= float(score_b) < DEFAULT_FAST_SCORE_THRESHOLD:
                released_examples.append(
                    {
                        "trade_date": snapshot.get("trade_date"),
                        "ticker": item.get("ticker"),
                        "score_b": float(score_b),
                        "decision": item.get("decision"),
                        "rank": item.get("rank"),
                    }
                )
    return {
        "baseline_threshold": DEFAULT_FAST_SCORE_THRESHOLD,
        "proposed_threshold": proposed_fast_threshold,
        "released_count": len(released_examples),
        "released_examples": released_examples[:20],
        "note": "Frozen current_plan replay does not rerun Layer B or Layer C. This margin scan only counts layer_b-filtered names whose score_b falls into the newly opened band; it does not imply they would survive downstream watchlist or buy-order filters.",
    }


def _build_watchlist_margin_payload(snapshot: dict, item: dict, score_final: float) -> dict[str, object]:
    return {
        "trade_date": snapshot.get("trade_date"),
        "ticker": item.get("ticker"),
        "score_b": item.get("score_b"),
        "score_c": item.get("score_c"),
        "score_final": score_final,
        "decision": item.get("decision"),
        "bc_conflict": item.get("bc_conflict"),
        "reasons": item.get("reasons") or ([item.get("reason")] if item.get("reason") else []),
    }


def _build_watchlist_threshold_margin(selection_root: Path, proposed_watchlist_threshold: float) -> dict[str, object]:
    threshold_only_examples: list[dict[str, object]] = []
    avoid_blocked_examples: list[dict[str, object]] = []
    for snapshot in _iter_selection_snapshots(selection_root):
        watchlist = ((snapshot.get("funnel_diagnostics") or {}).get("filters") or {}).get("watchlist") or {}
        for item in watchlist.get("tickers") or []:
            score_final = item.get("score_final")
            if score_final is None:
                continue
            score_final_value = float(score_final)
            if proposed_watchlist_threshold <= score_final_value < DEFAULT_WATCHLIST_SCORE_THRESHOLD:
                payload = _build_watchlist_margin_payload(snapshot, item, score_final_value)
                if item.get("decision") == "avoid":
                    avoid_blocked_examples.append(payload)
                else:
                    threshold_only_examples.append(payload)
    return {
        "baseline_threshold": DEFAULT_WATCHLIST_SCORE_THRESHOLD,
        "proposed_threshold": proposed_watchlist_threshold,
        "threshold_only_release_count": len(threshold_only_examples),
        "threshold_only_release_examples": threshold_only_examples[:20],
        "still_avoid_blocked_count": len(avoid_blocked_examples),
        "still_avoid_blocked_examples": avoid_blocked_examples[:20],
        "note": "Frozen current_plan replay preserves the historical watchlist decision set. This margin scan isolates names inside the newly opened score_final band and separates pure threshold misses from names that would still be blocked by decision=avoid.",
    }


def _build_frozen_gate_margin_scan(output_dir: Path, env_updates: dict[str, str]) -> dict | None:
    selection_root = output_dir / "selection_artifacts"
    if not selection_root.exists():
        return None

    scan: dict[str, object] = {}
    proposed_fast_threshold = _extract_env_float(env_updates, "DAILY_PIPELINE_FAST_SCORE_THRESHOLD")
    proposed_watchlist_threshold = _extract_env_float(env_updates, "DAILY_PIPELINE_WATCHLIST_SCORE_THRESHOLD")

    if proposed_fast_threshold is not None and proposed_fast_threshold < DEFAULT_FAST_SCORE_THRESHOLD:
        scan["fast_threshold_margin"] = _build_fast_threshold_margin(selection_root, proposed_fast_threshold)

    if proposed_watchlist_threshold is not None and proposed_watchlist_threshold < DEFAULT_WATCHLIST_SCORE_THRESHOLD:
        scan["watchlist_threshold_margin"] = _build_watchlist_threshold_margin(selection_root, proposed_watchlist_threshold)

    return scan or None


def _load_session_summary(output_dir: Path) -> dict | None:
    summary_path = output_dir / "session_summary.json"
    if not summary_path.exists():
        return None
    return _load_json(summary_path)


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_root = Path(args.output_root) if args.output_root else _default_output_root(args.start_date, args.end_date)
    output_root.mkdir(parents=True, exist_ok=True)

    variant_names = [item.strip() for item in args.variants.split(",") if item.strip()]
    unknown = [name for name in variant_names if name not in VARIANTS]
    if unknown:
        raise SystemExit(f"Unknown variants: {', '.join(unknown)}")

    report: dict[str, object] = {
        "start_date": args.start_date,
        "end_date": args.end_date,
        "frozen_plan_source": str(Path(args.frozen_plan_source).resolve()),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "output_root": str(output_root.resolve()),
        "variants": {},
    }

    for variant_name in variant_names:
        variant_payload = VARIANTS[variant_name]
        env_updates = {str(key): str(value) for key, value in dict(variant_payload.get("env", {})).items()}
        output_dir = _build_variant_output_dir(output_root, variant_name)
        run_result = _run_variant(repo_root, output_dir, args, variant_name, env_updates)
        session_summary = _load_session_summary(output_dir) if run_result["exit_code"] == 0 else None
        artifact_summary = _summarize_selection_artifacts(output_dir) if run_result["exit_code"] == 0 else {"exists": False}
        plan_generation_mode = _extract_plan_generation_mode(session_summary)
        overridden_frozen_gate_keys = sorted(set(env_updates) & FROZEN_POST_MARKET_GATE_ENV_KEYS)
        frozen_gate_noop_warning = None
        frozen_gate_margin_scan = None
        if plan_generation_mode == "frozen_current_plan_replay" and overridden_frozen_gate_keys:
            frozen_gate_noop_warning = (
                "Frozen current_plan replay reuses stored post-market plans. "
                "These env overrides do not regenerate Layer B / Layer C / watchlist decisions, "
                "so the replay result should not be interpreted as a valid gate-sensitivity outcome."
            )
            frozen_gate_margin_scan = _build_frozen_gate_margin_scan(output_dir, env_updates)

        report["variants"][variant_name] = {
            "description": variant_payload.get("description"),
            "env": env_updates,
            "run": run_result,
            "session_summary": session_summary,
            "artifact_summary": artifact_summary,
            "plan_generation_mode": plan_generation_mode,
            "overridden_frozen_gate_keys": overridden_frozen_gate_keys,
            "frozen_gate_noop_warning": frozen_gate_noop_warning,
            "frozen_gate_margin_scan": frozen_gate_margin_scan,
        }

    report_path = output_root / "gate_experiment_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    print(f"Saved gate experiment report to: {report_path}")
    for variant_name in variant_names:
        payload = report["variants"][variant_name]
        exit_code = payload["run"]["exit_code"]
        artifact_summary = payload.get("artifact_summary", {})
        if exit_code != 0:
            print(f"{variant_name}: failed exit_code={exit_code}")
            continue
        print(
            f"{variant_name}: high_pool={artifact_summary.get('total_high_pool_count')} "
            f"watchlist={artifact_summary.get('total_watchlist_count')} "
            f"buy_orders={artifact_summary.get('total_buy_order_count')}"
        )
        warning = payload.get("frozen_gate_noop_warning")
        if warning:
            print(f"{variant_name}: warning={warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
