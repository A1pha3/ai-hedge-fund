from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from src.data.enhanced_cache import clear_cache


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark cold-vs-warm reuse of the persisted market-data cache.")
    parser.add_argument("--trade-date", required=True, help="Trade date in YYYYMMDD format")
    parser.add_argument("--ticker", default="000001", help="Ticker used for detail lookup")
    parser.add_argument("--clear-first", action="store_true", help="Clear the local cache before the first run to force a cold start")
    parser.add_argument("--output", default=None, help="Optional path to write the benchmark JSON payload")
    return parser


def _build_validation_command(*, python_executable: str, repo_root: Path, trade_date: str, ticker: str) -> list[str]:
    return [
        python_executable,
        str(repo_root / "scripts" / "validate_data_cache_reuse.py"),
        "--trade-date",
        trade_date,
        "--ticker",
        ticker,
    ]


def _run_validation(command: list[str], *, cwd: Path, env: dict[str, str]) -> dict:
    completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        raise RuntimeError(stderr or stdout or f"Validation command failed with exit code {completed.returncode}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Validation command did not return JSON output") from exc


def _summarize_benchmark(*, first_run: dict, second_run: dict, trade_date: str, ticker: str, clear_first: bool) -> dict:
    first_stats = first_run.get("session_stats", {})
    second_stats = second_run.get("session_stats", {})
    first_shapes = first_run.get("result_shapes", {})
    second_shapes = second_run.get("result_shapes", {})

    first_total_rows = sum(int(value) for value in first_shapes.values())
    second_total_rows = sum(int(value) for value in second_shapes.values())

    return {
        "trade_date": trade_date,
        "ticker": ticker,
        "clear_first": clear_first,
        "first_run": first_run,
        "second_run": second_run,
        "summary": {
            "first_total_rows": first_total_rows,
            "second_total_rows": second_total_rows,
            "first_disk_hits": int(first_stats.get("disk_hits", 0)),
            "second_disk_hits": int(second_stats.get("disk_hits", 0)),
            "first_misses": int(first_stats.get("misses", 0)),
            "second_misses": int(second_stats.get("misses", 0)),
            "first_sets": int(first_stats.get("sets", 0)),
            "second_sets": int(second_stats.get("sets", 0)),
            "disk_hit_gain": int(second_stats.get("disk_hits", 0)) - int(first_stats.get("disk_hits", 0)),
            "miss_reduction": int(first_stats.get("misses", 0)) - int(second_stats.get("misses", 0)),
            "set_reduction": int(first_stats.get("sets", 0)) - int(second_stats.get("sets", 0)),
            "first_hit_rate": float(first_stats.get("hit_rate", 0.0)),
            "second_hit_rate": float(second_stats.get("hit_rate", 0.0)),
            "reuse_confirmed": int(second_stats.get("disk_hits", 0)) > 0 and int(second_stats.get("misses", 0)) <= int(first_stats.get("misses", 0)) and int(second_stats.get("sets", 0)) <= int(first_stats.get("sets", 0)),
        },
    }


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    command = _build_validation_command(python_executable=sys.executable, repo_root=repo_root, trade_date=args.trade_date, ticker=args.ticker)

    if args.clear_first:
        clear_cache()

    first_run = _run_validation(command, cwd=repo_root, env=env)
    second_run = _run_validation(command, cwd=repo_root, env=env)
    payload = _summarize_benchmark(first_run=first_run, second_run=second_run, trade_date=args.trade_date, ticker=args.ticker, clear_first=args.clear_first)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()