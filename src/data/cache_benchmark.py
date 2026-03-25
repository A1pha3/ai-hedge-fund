from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from src.data.enhanced_cache import clear_cache


def build_validation_command(*, python_executable: str, repo_root: Path, trade_date: str, ticker: str) -> list[str]:
    return [
        python_executable,
        str(repo_root / "scripts" / "validate_data_cache_reuse.py"),
        "--trade-date",
        trade_date,
        "--ticker",
        ticker,
    ]


def run_validation_subprocess(command: list[str], *, cwd: Path, env: dict[str, str]) -> dict:
    completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        raise RuntimeError(stderr or stdout or f"Validation command failed with exit code {completed.returncode}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Validation command did not return JSON output") from exc


def summarize_cache_reuse_benchmark(*, first_run: dict, second_run: dict, trade_date: str, ticker: str, clear_first: bool) -> dict:
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


def render_cache_benchmark_markdown(payload: dict) -> str:
    summary = payload.get("summary", {})
    status = "confirmed" if summary.get("reuse_confirmed") else "not confirmed"
    clear_first = "yes" if payload.get("clear_first") else "no"

    return "\n".join(
        [
            f"# Data Cache Benchmark - {payload.get('trade_date')} - {payload.get('ticker')}",
            "",
            "## Run Setup",
            f"- trade_date: {payload.get('trade_date')}",
            f"- ticker: {payload.get('ticker')}",
            f"- clear_first: {clear_first}",
            f"- reuse_confirmed: {status}",
            "",
            "## Cold vs Warm Summary",
            f"- first_total_rows: {summary.get('first_total_rows', 0)}",
            f"- second_total_rows: {summary.get('second_total_rows', 0)}",
            f"- first_disk_hits: {summary.get('first_disk_hits', 0)}",
            f"- second_disk_hits: {summary.get('second_disk_hits', 0)}",
            f"- disk_hit_gain: {summary.get('disk_hit_gain', 0)}",
            f"- first_misses: {summary.get('first_misses', 0)}",
            f"- second_misses: {summary.get('second_misses', 0)}",
            f"- miss_reduction: {summary.get('miss_reduction', 0)}",
            f"- first_sets: {summary.get('first_sets', 0)}",
            f"- second_sets: {summary.get('second_sets', 0)}",
            f"- set_reduction: {summary.get('set_reduction', 0)}",
            f"- first_hit_rate: {summary.get('first_hit_rate', 0.0)}",
            f"- second_hit_rate: {summary.get('second_hit_rate', 0.0)}",
        ]
    ) + "\n"


def append_cache_benchmark_markdown(target_path: str | Path, markdown: str) -> None:
    report_path = Path(target_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    existing = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    separator = "\n\n" if existing and not existing.endswith("\n\n") else ""
    report_path.write_text(f"{existing}{separator}{markdown}", encoding="utf-8")


def run_cache_reuse_benchmark(
    *,
    repo_root: Path,
    python_executable: str,
    trade_date: str,
    ticker: str,
    clear_first: bool,
    output_path: str | Path | None = None,
    markdown_output_path: str | Path | None = None,
    append_markdown_to: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> dict:
    resolved_env = dict(os.environ) if env is None else dict(env)
    command = build_validation_command(python_executable=python_executable, repo_root=repo_root, trade_date=trade_date, ticker=ticker)

    if clear_first:
        clear_cache()

    first_run = run_validation_subprocess(command, cwd=repo_root, env=resolved_env)
    second_run = run_validation_subprocess(command, cwd=repo_root, env=resolved_env)
    payload = summarize_cache_reuse_benchmark(first_run=first_run, second_run=second_run, trade_date=trade_date, ticker=ticker, clear_first=clear_first)
    markdown_summary = render_cache_benchmark_markdown(payload)

    if output_path:
        json_path = Path(output_path)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if markdown_output_path:
        markdown_path = Path(markdown_output_path)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown_summary, encoding="utf-8")

    if append_markdown_to:
        append_cache_benchmark_markdown(append_markdown_to, markdown_summary)

    return payload