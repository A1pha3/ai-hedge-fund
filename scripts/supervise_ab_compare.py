from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
import subprocess
import time


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_MD = REPO_ROOT / "data/reports/ab_walk_forward_first_pilot.md"
DEFAULT_REPORT_JSON = REPO_ROOT / "data/reports/ab_walk_forward_first_pilot.json"
DEFAULT_LOG = REPO_ROOT / "data/reports/ab_walk_forward_supervisor.log"
DEFAULT_MODEL_PROVIDER = "Zhipu"
DEFAULT_MODEL_NAME = "glm-4.7"
RESET_INTERVAL_HOURS = 5
RESET_ANCHOR_HOUR = 20
RESET_ANCHOR_MINUTE = 0
RESET_INTERVAL = dt.timedelta(hours=RESET_INTERVAL_HOURS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Supervise A/B compare runs with Coding Plan first and provider reset-window recovery")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--train-months", type=int, default=2)
    parser.add_argument("--test-months", type=int, default=1)
    parser.add_argument("--step-months", type=int, default=1)
    parser.add_argument("--model-provider", default=DEFAULT_MODEL_PROVIDER)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--report-file", default=str(DEFAULT_REPORT_MD))
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_JSON))
    parser.add_argument("--heartbeat-seconds", type=int, default=3600)
    parser.add_argument("--restart-grace-seconds", type=int, default=600)
    parser.add_argument("--log-file", default=str(DEFAULT_LOG))
    parser.add_argument("--first-reset", default=None, help="First known provider reset time, format: YYYY-MM-DD HH:MM:SS")
    return parser.parse_args()


def now() -> dt.datetime:
    return dt.datetime.now()


def now_str() -> str:
    return now().strftime("%Y-%m-%d %H:%M:%S")


def resolve_first_reset(first_reset_text: str | None) -> dt.datetime:
    if first_reset_text:
        return dt.datetime.strptime(first_reset_text, "%Y-%m-%d %H:%M:%S")

    moment = now()
    candidate = moment.replace(hour=RESET_ANCHOR_HOUR, minute=RESET_ANCHOR_MINUTE, second=0, microsecond=0)
    if candidate < moment:
        return candidate
    return candidate


def next_reset_after(moment: dt.datetime, first_reset: dt.datetime) -> dt.datetime:
    if moment < first_reset:
        return first_reset
    elapsed = moment - first_reset
    steps = int(elapsed.total_seconds() // RESET_INTERVAL.total_seconds()) + 1
    return first_reset + steps * RESET_INTERVAL


def latest_reset_at_or_before(moment: dt.datetime, first_reset: dt.datetime) -> dt.datetime | None:
    if moment < first_reset:
        return None
    elapsed = moment - first_reset
    steps = int(elapsed.total_seconds() // RESET_INTERVAL.total_seconds())
    return first_reset + steps * RESET_INTERVAL


def upcoming_resets(count: int, first_reset: dt.datetime) -> list[dt.datetime]:
    points: list[dt.datetime] = []
    cursor = now()
    for _ in range(count):
        cursor = next_reset_after(cursor, first_reset)
        points.append(cursor)
        cursor = cursor + dt.timedelta(seconds=1)
    return points


def build_command(args: argparse.Namespace) -> list[str]:
    return [
        str(REPO_ROOT / ".venv/bin/backtester"),
        "--ab-compare",
        "--mode",
        "pipeline",
        "--start-date",
        args.start_date,
        "--end-date",
        args.end_date,
        "--train-months",
        str(args.train_months),
        "--test-months",
        str(args.test_months),
        "--step-months",
        str(args.step_months),
        "--model-provider",
        args.model_provider,
        "--model-name",
        args.model_name,
        "--analysts-all",
        "--report-file",
        args.report_file,
        "--report-json",
        args.report_json,
    ]


def process_patterns(args: argparse.Namespace) -> list[str]:
    return [
        f"src.backtesting.cli --ab-compare --start-date {args.start_date} --end-date {args.end_date}",
        f".venv/bin/backtester --ab-compare --mode pipeline --start-date {args.start_date} --end-date {args.end_date}",
    ]


def running_pids(patterns: list[str]) -> list[str]:
    matches: set[str] = set()
    for pattern in patterns:
        proc = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        if proc.returncode != 0:
            continue
        matches.update(line.strip() for line in proc.stdout.splitlines() if line.strip())
    return sorted(matches)


def reports_ready(report_md: Path, report_json: Path) -> bool:
    return report_md.exists() and report_json.exists()


def append_log(log_file: Path, message: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"[{now_str()}] {message}\n")


def describe_latest_progress(report_md: Path, report_json: Path) -> str:
    progress_files = [report_md, report_json]
    report_prefix = report_md.stem
    progress_files.extend(sorted(report_md.parent.glob(f"{report_prefix}.checkpoint*")))

    existing_files = [path for path in progress_files if path.exists()]
    if not existing_files:
        return "progress=no-artifacts-yet"

    latest_file = max(existing_files, key=lambda path: path.stat().st_mtime)
    updated_at = dt.datetime.fromtimestamp(latest_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return f"progress={latest_file.name} updated_at={updated_at}"


def in_restart_window(reset_point: dt.datetime | None, grace_seconds: int) -> bool:
    if reset_point is None:
        return False
    delta = abs((now() - reset_point).total_seconds())
    return delta <= grace_seconds


def main() -> None:
    args = parse_args()
    report_md = Path(args.report_file)
    report_json = Path(args.report_json)
    log_file = Path(args.log_file)
    command = build_command(args)
    patterns = process_patterns(args)
    first_reset = resolve_first_reset(args.first_reset)

    append_log(log_file, f"A/B supervisor started strategy=CodingPlan->MiniMax->ZhipuStandard launch={args.model_provider}:{args.model_name} heartbeat={args.heartbeat_seconds}s")
    append_log(
        log_file,
        "next resets: " + ", ".join(point.strftime("%Y-%m-%d %H:%M") for point in upcoming_resets(6, first_reset)),
    )

    last_heartbeat_at = 0.0

    while True:
        if reports_ready(report_md, report_json):
            append_log(log_file, "reports detected, supervisor exit")
            return

        current_time = now()
        next_reset = next_reset_after(current_time, first_reset)
        latest_reset = latest_reset_at_or_before(current_time, first_reset)
        pids = running_pids(patterns)

        if pids:
            current = time.time()
            if current - last_heartbeat_at >= args.heartbeat_seconds:
                append_log(log_file, f"alive pids={','.join(pids)} next_reset={next_reset.strftime('%Y-%m-%d %H:%M:%S')} {describe_latest_progress(report_md, report_json)}")
                last_heartbeat_at = current
            time.sleep(30)
            continue

        if in_restart_window(latest_reset, args.restart_grace_seconds):
            append_log(log_file, f"starting command at reset window; next_reset={next_reset.strftime('%Y-%m-%d %H:%M:%S')}")
            process = subprocess.Popen(command, cwd=REPO_ROOT)
            append_log(log_file, f"started pid={process.pid}")
            time.sleep(15)
            continue

        append_log(log_file, f"waiting for next reset at {next_reset.strftime('%Y-%m-%d %H:%M:%S')}")
        sleep_seconds = min(args.heartbeat_seconds, max(30, int((next_reset - now()).total_seconds())))
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    main()
