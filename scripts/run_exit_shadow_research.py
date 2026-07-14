#!/usr/bin/env python3
"""Write an immutable, research-only legacy exit-sensitivity report."""

from __future__ import annotations

import argparse
import csv
import ctypes
import errno
import fcntl
import hashlib
import io
import json
import math
import os
import secrets
import stat
import tempfile
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

from src.research.exit_shadow_research import (
    ATR_METHOD,
    REPLAY_ATR_PERIOD,
    LegacyCohort,
    PairedExitResult,
    PairedReplayRow,
    build_legacy_cohort,
    replay_paired,
    summarize_paired_results,
)
from src.screening.offensive.execution_adjuster import ExecutionCosts
from src.screening.offensive.exit_policy import (
    ACTIVATION_RETURN,
    ATR_MULTIPLE,
    PLAN_EXIT_SESSION,
)


REPORT_MODE = "legacy_sensitivity"
FIXED_COSTS = ExecutionCosts(version="daily-action-v2")
DEFAULT_OUTPUT_DIR = Path("data/reports/exit_shadow")
BLOCK_SESSIONS = 10
REPORT_CONTRACT_IDENTITY = "exit-shadow-legacy-sensitivity-v2"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_PRE_DENOMINATOR_EXCLUSION_REASONS = frozenset(
    {"duplicate_buy", "duplicate_exit", "unmatched_buy", "unmatched_exit"}
)


def _civil_today() -> date:
    """Injectable clock for policy tests; intentionally not a CLI option."""
    return date.today()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the fixed-policy legacy exit shadow sensitivity report."
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=Path("data/paper_trading_backtest/journal.jsonl"),
    )
    parser.add_argument("--price-cache", type=Path, default=Path("data/price_cache"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--as-of", required=True, help="Report identity in YYYYMMDD")
    parser.add_argument("--bootstrap-seed", type=int, default=0)
    parser.add_argument("--bootstrap-draws", type=int, default=10_000)
    return parser


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _reject_symlink_components(path: Path, *, label: str, allow_missing: bool) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            if allow_missing:
                return
            raise ValueError(f"{label} does not exist: {path}") from None
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"{label} path must not contain symlinks: {path}")


def _validate_nofollow_input(path: Path, *, directory: bool) -> Path:
    absolute = _absolute_lexical(path)
    _reject_symlink_components(absolute, label="input", allow_missing=False)
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    if directory:
        flags |= getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = _open_existing_nofollow(absolute, flags)
    except OSError as exc:
        kind = "directory" if directory else "regular file"
        raise ValueError(f"input must be a nofollow {kind}: {absolute}") from exc
    try:
        mode = os.fstat(descriptor).st_mode
        valid = stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)
        if not valid:
            kind = "directory" if directory else "regular file"
            raise ValueError(f"input must be a nofollow {kind}: {absolute}")
    finally:
        os.close(descriptor)
    return absolute


def _open_existing_nofollow(path: Path, final_flags: int) -> int:
    """Open an absolute path without trusting any ancestor lookup."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    descriptor = os.open(path.anchor, directory_flags)
    try:
        for index, part in enumerate(path.parts[1:]):
            flags = final_flags if index == len(path.parts[1:]) - 1 else directory_flags
            child = os.open(part, flags | nofollow, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _validate_cache_entries(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        for name in os.listdir(descriptor):
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError(
                    f"cache entries must be nofollow regular files: {path / name}"
                )
    finally:
        os.close(descriptor)


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _validate_output_path(output: Path, journal: Path, price_cache: Path) -> Path:
    absolute = _absolute_lexical(output)
    _reject_symlink_components(absolute, label="output", allow_missing=True)
    protected = [journal, price_cache]
    protected.extend(
        REPOSITORY_ROOT / relative
        for relative in (
            "data/paper_trading",
            "data/paper_trading_backtest",
            "data/price_cache",
            "src",
        )
    )
    if any(_paths_overlap(absolute, item) for item in protected):
        raise ValueError(
            "output directory must be disjoint from input and source paths"
        )
    if absolute.exists() and not absolute.is_dir():
        raise ValueError("output path must be a directory")
    return absolute


def _validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    try:
        parsed = datetime.strptime(args.as_of, "%Y%m%d")
    except ValueError:
        parser.error("--as-of must be a valid date in YYYYMMDD format")
    if parsed.strftime("%Y%m%d") != args.as_of:
        parser.error("--as-of must be a valid date in YYYYMMDD format")
    try:
        args.journal = _validate_nofollow_input(args.journal, directory=False)
        args.price_cache = _validate_nofollow_input(args.price_cache, directory=True)
        _validate_cache_entries(args.price_cache)
        args.output_dir = _validate_output_path(
            args.output_dir, args.journal, args.price_cache
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.bootstrap_seed < 0:
        parser.error("bootstrap seed must be a nonnegative integer")
    if args.bootstrap_draws < 1:
        parser.error("bootstrap draws must be a positive integer")


def _source_identity(metadata: os.stat_result) -> dict[str, int]:
    return {
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "mtime_ns": metadata.st_mtime_ns,
        "ctime_ns": metadata.st_ctime_ns,
    }


def _content_fingerprint(content: bytes) -> dict[str, Any]:
    return {"sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}


def _manifest_fingerprint(files: list[dict[str, Any]]) -> dict[str, Any]:
    encoded = json.dumps(
        files, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "file_count": len(files),
        "files": files,
    }


def _read_stable_descriptor(
    descriptor: int, *, label: str
) -> tuple[bytes, os.stat_result]:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"{label} must be a nofollow regular file")
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, 1024 * 1024):
        chunks.append(chunk)
    after = os.fstat(descriptor)
    identity_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(
        getattr(before, field) != getattr(after, field) for field in identity_fields
    ):
        raise RuntimeError(f"{label} changed while being snapshotted")
    content = b"".join(chunks)
    if len(content) != before.st_size:
        raise RuntimeError(f"{label} changed while being snapshotted")
    return content, before


def _cutoff_journal(content: bytes, as_of: str) -> tuple[bytes, set[str], int]:
    kept: list[str] = []
    tickers: set[str] = set()
    excluded = 0
    for line_number, raw in enumerate(content.decode("utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"journal evidence cannot be dated at line {line_number}") from exc
        evidence_date = record.get("date") if isinstance(record, dict) else None
        if type(evidence_date) is not str or len(evidence_date) != 8 or not evidence_date.isdigit():
            raise ValueError(f"journal evidence cannot be dated at line {line_number}")
        if evidence_date <= as_of:
            kept.append(raw)
            if record.get("setup") == "btst_breakout" and type(record.get("ticker")) is str:
                tickers.add(record["ticker"])
        else:
            excluded += 1
    return (("\n".join(kept) + ("\n" if kept else "")).encode("utf-8"), tickers, excluded)


def _cutoff_csv(content: bytes, as_of: str, name: str) -> tuple[bytes, int]:
    text = content.decode("utf-8")
    rows = list(csv.reader(text.splitlines()))
    if not rows or "date" not in rows[0]:
        raise ValueError(f"cache entry {name} has no date column")
    date_index = rows[0].index("date")
    kept = [rows[0]]
    excluded = 0
    for row in rows[1:]:
        if len(row) <= date_index:
            raise ValueError(f"cache entry {name} has undated evidence")
        compact = row[date_index].replace("-", "")
        if len(compact) != 8 or not compact.isdigit():
            raise ValueError(f"cache entry {name} has undated evidence")
        if compact <= as_of:
            kept.append(row)
        else:
            excluded += 1
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(kept)
    return output.getvalue().encode("utf-8"), excluded


def _read_live_inputs(
    journal: Path, price_cache: Path, *, as_of: str = "99991231",
    cutoff_audit: dict[str, int] | None = None,
) -> tuple[dict[str, Any], bytes, dict[str, bytes]]:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    journal_fd = _open_existing_nofollow(journal, os.O_RDONLY | nonblock)
    try:
        raw_journal_bytes, _journal_stat = _read_stable_descriptor(
            journal_fd, label="journal"
        )
    finally:
        os.close(journal_fd)
    journal_bytes, consumed_tickers, future_journal = _cutoff_journal(raw_journal_bytes, as_of)
    future_price_rows = 0
    future_price_files = 0
    future_price_tickers: set[str] = set()

    cache_fd = _open_existing_nofollow(
        price_cache,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    cache_bytes: dict[str, bytes] = {}
    cache_manifest: list[dict[str, Any]] = []
    try:
        cache_dir_before = os.fstat(cache_fd)
        for name in sorted(os.listdir(cache_fd)):
            metadata = os.stat(name, dir_fd=cache_fd, follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError(
                    f"cache entries must be nofollow regular files: {price_cache / name}"
                )
            file_fd = os.open(name, os.O_RDONLY | nofollow | nonblock, dir_fd=cache_fd)
            try:
                content, stable_stat = _read_stable_descriptor(
                    file_fd, label=f"cache entry {name}"
                )
            finally:
                os.close(file_fd)
            content, future_rows = _cutoff_csv(content, as_of, name)
            future_price_rows += future_rows
            if future_rows:
                future_price_tickers.add(Path(name).stem)
            if future_rows and content.count(b"\n") <= 1:
                future_price_files += 1
            if Path(name).stem not in consumed_tickers:
                continue
            cache_bytes[name] = content
            cache_manifest.append(
                {
                    "path": name,
                    **_content_fingerprint(content),
                }
            )
        cache_dir_after = os.fstat(cache_fd)
        directory_identity_fields = (
            "st_dev",
            "st_ino",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(
            getattr(cache_dir_before, field) != getattr(cache_dir_after, field)
            for field in directory_identity_fields
        ):
            raise RuntimeError("price cache changed while being snapshotted")
    finally:
        os.close(cache_fd)

    cache_fingerprint = _manifest_fingerprint(cache_manifest)
    fingerprint = {
        "journal": _content_fingerprint(journal_bytes),
        "price_cache": cache_fingerprint,
    }
    if cutoff_audit is not None:
        cutoff_audit.update(
            future_journal_rows=future_journal,
            future_price_rows=future_price_rows,
            future_price_files=future_price_files,
            future_price_tickers=len(future_price_tickers),
        )
    return fingerprint, journal_bytes, cache_bytes


def _snapshot_fingerprint(
    journal_bytes: bytes, cache_bytes: dict[str, bytes]
) -> dict[str, Any]:
    files = [
        {"path": name, **_content_fingerprint(content)}
        for name, content in sorted(cache_bytes.items())
    ]
    return {
        "journal": _content_fingerprint(journal_bytes),
        "price_cache": _manifest_fingerprint(files),
    }


def _write_snapshot_file(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class _InputSnapshot:
    journal: Path
    price_cache: Path
    fingerprints_before: dict[str, Any]
    snapshot_fingerprint: dict[str, Any]
    cutoff_audit: dict[str, int]


@contextmanager
def _stable_input_snapshot(journal: Path, price_cache: Path, *, as_of: str):
    cutoff_audit: dict[str, int] = {}
    fingerprints, journal_bytes, cache_bytes = _read_live_inputs(
        journal, price_cache, as_of=as_of, cutoff_audit=cutoff_audit
    )
    temporary = tempfile.TemporaryDirectory(prefix="exit-shadow-snapshot-")
    root = Path(temporary.name)
    snapshot_journal = root / "journal.jsonl"
    snapshot_cache = root / "price_cache"
    snapshot_cache.mkdir(mode=0o700)
    try:
        _write_snapshot_file(snapshot_journal, journal_bytes)
        for name, content in cache_bytes.items():
            _write_snapshot_file(snapshot_cache / name, content)
        yield _InputSnapshot(
            journal=snapshot_journal,
            price_cache=snapshot_cache,
            fingerprints_before=fingerprints,
            snapshot_fingerprint=_snapshot_fingerprint(journal_bytes, cache_bytes),
            cutoff_audit=cutoff_audit,
        )
    finally:
        temporary.cleanup()


def _paired_rows(
    cohort: LegacyCohort, replay: PairedExitResult
) -> tuple[PairedReplayRow, ...]:
    paths = {path.trade_id: path for path in cohort.included}
    return tuple(
        PairedReplayRow(
            baseline=baseline,
            challenger=challenger,
            legacy_return=paths[baseline.trade_id].recorded_return,
            trading_session_dates=tuple(
                session.date for session in paths[baseline.trade_id].sessions
            ),
        )
        for baseline, challenger in zip(replay.baseline, replay.challenger)
    )


def _missing_legacy_returns(
    cohort: LegacyCohort, replay: PairedExitResult
) -> tuple[float, ...]:
    replay_excluded = {item.trade_id for item in replay.excluded}
    values = [
        item.recorded_return
        for item in cohort.excluded
        if item.recorded_return is not None
        and item.reason not in _PRE_DENOMINATOR_EXCLUSION_REASONS
    ]
    values.extend(
        path.recorded_return
        for path in cohort.included
        if path.trade_id in replay_excluded
    )
    return tuple(float(value) for value in values if math.isfinite(float(value)))


def _build_payload(
    *,
    journal: Path,
    price_cache: Path,
    live_journal: Path,
    live_price_cache: Path,
    fingerprints_before: dict[str, Any],
    snapshot_fingerprint: dict[str, Any],
    cutoff_audit: dict[str, int],
    as_of: str,
    bootstrap_seed: int,
    bootstrap_draws: int,
) -> dict[str, Any]:
    cohort = build_legacy_cohort(journal, price_cache_dir=price_cache, as_of=as_of)
    replay = replay_paired(cohort.included, costs=FIXED_COSTS)
    paired = _paired_rows(cohort, replay)
    statistics = summarize_paired_results(
        paired,
        total_trade_count=cohort.audit.total_paired_btst,
        missing_legacy_returns=_missing_legacy_returns(cohort, replay),
        block_sessions=BLOCK_SESSIONS,
        draws=bootstrap_draws,
        seed=bootstrap_seed,
    )
    fingerprints_after, _, _ = _read_live_inputs(live_journal, live_price_cache, as_of=as_of)
    if fingerprints_after != fingerprints_before:
        raise RuntimeError("inputs changed during report run; refusing publication")
    audit = asdict(cohort.audit)
    return {
        "schema_version": 1,
        "report_id": f"exit_shadow_{as_of}",
        "as_of": as_of,
        "mode": REPORT_MODE,
        "shadow_only": True,
        "production_eligible": False,
        "historical_pit_eligible": False,
        "journal_event_availability": "unverifiable",
        "as_of_semantics": "source_snapshot_observation_date",
        "cutoff_audit": dict(cutoff_audit),
        "parameters": {
            "activation_return": ACTIVATION_RETURN,
            "atr_multiple": ATR_MULTIPLE,
        },
        "policy_identity": {
            "name": "fixed_activation_atr_trailing_exit",
            "fixed": True,
            "activation_return": ACTIVATION_RETURN,
            "atr_multiple": ATR_MULTIPLE,
            "atr": {"period": REPLAY_ATR_PERIOD, "method": ATR_METHOD},
            "entry": {
                "holding_session": 1,
                "price": "open",
                "exit_allowed": False,
            },
            "baseline": {
                "trigger": "session_9_close",
                "planned_execution": "session_10_next_executable_open",
            },
            "close_trigger_execution": "next_executable_open",
            "queue_suspension_deferral": "defer_over_supplied_sessions",
            "execution_classifier": "classify_open_fill",
            "t_plus_one": True,
            "block_sessions": BLOCK_SESSIONS,
            "cost_version": FIXED_COSTS.version,
            "execution_costs": asdict(FIXED_COSTS),
            "plan_exit_session": PLAN_EXIT_SESSION,
            "planned_execution": "next_executable_open",
        },
        "input_fingerprints": fingerprints_before,
        "input_fingerprints_before": fingerprints_before,
        "analysis_snapshot_fingerprint": snapshot_fingerprint,
        "input_fingerprints_after": fingerprints_after,
        "cohort": {
            "denominator": cohort.audit.total_paired_btst,
            "counts": audit,
            "coverage": {
                "covered": cohort.audit.covered,
                "total": cohort.audit.total,
                "ratio": cohort.audit.coverage,
            },
            "missingness_bias": {
                "covered_legacy_mean": cohort.audit.covered_legacy_mean,
                "missing_legacy_mean": cohort.audit.missing_legacy_mean,
                "selection_bias_warning": cohort.audit.selection_bias_warning,
            },
            "exclusions": [asdict(item) for item in cohort.excluded],
        },
        "common_mask": {
            "total_paths": replay.total_paths,
            "eligible": replay.common_eligible,
            "excluded": [asdict(item) for item in replay.excluded],
        },
        "statistics": asdict(statistics),
        "limitations": [
            "retrospective six-month legacy backtest, not a forward production cohort",
            "paired BTST exits only",
            "selected common executable mask can introduce missingness bias",
            "fixed-policy sensitivity is not evidence of production readiness",
            "MFE uses non-executable daily highs for diagnosis only",
        ],
    }


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4%}"


def _reason_counts(items: list[dict[str, Any]]) -> str:
    counts = Counter(str(item.get("reason") or "unknown") for item in items)
    return (
        ", ".join(f"{reason}: {count}" for reason, count in sorted(counts.items()))
        or "none"
    )


def _arm_summary(label: str, arm: dict[str, Any]) -> list[str]:
    reasons = (
        ", ".join(f"{reason}: {count}" for reason, count in arm["exit_reason_counts"])
        or "none"
    )
    return [
        f"- {label} mean / median / worst decile / downside-decile mean: "
        f"{_percent(arm['mean_net_return'])} / {_percent(arm['median_net_return'])} / "
        f"{_percent(arm['worst_decile_net_return'])} / {_percent(arm['downside_decile_mean'])}",
        f"- {label} mean / median holding sessions: "
        f"{arm['mean_holding_sessions']:.4f} / {arm['median_holding_sessions']:.4f}",
        f"- {label} exit reasons: {reasons}",
    ]


def _render_markdown(payload: dict[str, Any]) -> str:
    cohort = payload["cohort"]
    common = payload["common_mask"]
    stats = payload["statistics"]
    block = stats["block_mean_difference"]
    missingness = cohort["missingness_bias"]
    baseline = stats["baseline"]
    challenger = stats["challenger"]
    policy = payload["policy_identity"]
    costs = policy["execution_costs"]
    reconstruction_covered = cohort["coverage"]["covered"]
    denominator = cohort["denominator"]
    artifact = payload.get("artifact_identity", {})
    lines = [
        "# Legacy sensitivity / shadow only",
        "",
        f"- report_id: {payload['report_id']}",
        "- mode: legacy_sensitivity",
        "- shadow_only: true",
        "- production_eligible: false",
        "- historical_pit_eligible: false",
        "- journal_event_availability: unverifiable",
        "- as_of semantics: source snapshot observation date (not historical event availability)",
        f"- future journal rows excluded: {payload['cutoff_audit']['future_journal_rows']}",
        f"- future price rows excluded: {payload['cutoff_audit']['future_price_rows']}",
        f"- contract identity: {artifact.get('contract_identity', REPORT_CONTRACT_IDENTITY)}",
        f"- semantic payload SHA-256: {artifact.get('semantic_payload_sha256', 'pending')}",
        "",
        "## Fixed policy identity",
        "",
        f"- activation return: {policy['activation_return']:.2%}",
        f"- ATR: {policy['atr']['method']} period {policy['atr']['period']}, "
        f"multiple {policy['atr_multiple']}",
        "- entry: holding session 1 open; no session-1 exit",
        "- baseline: session-9 close trigger; session-10 next executable open",
        f"- close-trigger execution: {policy['close_trigger_execution'].replace('_', ' ')}",
        "- queue/suspension: defer over supplied sessions",
        f"- execution classifier: {policy['execution_classifier']}",
        f"- execution cost version: {costs['version']}",
        f"- execution costs: commission={costs['commission']}, tax_rate={costs['tax_rate']}, "
        f"slippage_bps={costs['slippage_bps']}, other_fee={costs['other_fee']}",
        f"- T+1: {str(policy['t_plus_one']).lower()}",
        "",
        "## Why this cohort differs from current production",
        "",
        "- It is a retrospective six-month legacy backtest, not a live forward sample.",
        "- Journal EXIT dates repeat signal dates and do not prove when outcomes became available; historical PIT claims are prohibited.",
        "- It includes paired BTST exits only, not the current production opportunity set.",
        "- Results use a selected common executable mask after reconstruction exclusions.",
        "- Current board-rule mismatches are disclosed rather than silently filtered.",
        "- The fixed challenger is sensitivity evidence and cannot promote a policy.",
        "",
        "## Denominators, exclusions, and coverage",
        "",
        f"- paired BTST denominator: {cohort['denominator']}",
        f"- reconstruction coverage: {reconstruction_covered}/{denominator} "
        f"({_percent(cohort['coverage']['ratio'])})",
        f"- reconstruction covered legacy mean: {_percent(missingness['covered_legacy_mean'])}",
        f"- reconstruction missing legacy mean: {_percent(missingness['missing_legacy_mean'])}",
        f"- reconstruction selection bias warning: "
        f"{str(missingness['selection_bias_warning']).lower()}",
        f"- common executable coverage: {common['eligible']}/{denominator} "
        f"({_percent(stats['coverage'])})",
        f"- common-mask covered legacy mean: {_percent(stats['covered_group_legacy_mean'])}",
        f"- common-mask missing legacy mean: {_percent(stats['missing_group_legacy_mean'])}",
        f"- Cohort exclusion reasons: {_reason_counts(cohort['exclusions'])}",
        f"- Common-mask exclusion reasons: {_reason_counts(common['excluded'])}",
        "",
        "## Paired and block sensitivity",
        "",
        f"- trades / signal days / non-overlapping windows: {stats['trade_count']} / "
        f"{stats['signal_day_count']} / {stats['nonoverlapping_window_count']}",
        f"- mean / median / worst-decile paired difference: "
        f"{_percent(stats['mean_difference'])} / {_percent(stats['median_difference'])} / "
        f"{_percent(stats['worst_decile_difference'])}",
        f"- paired downside-decile mean difference: "
        f"{_percent(stats['downside_decile_mean_difference'])}",
        *_arm_summary("baseline", baseline),
        *_arm_summary("challenger", challenger),
        f"- moving-block sessions / draws / seed: {block['block_sessions']} / "
        f"{block['draws']} / {block['seed']}",
        f"- block signal days / trading sessions: {block['signal_day_count']} / "
        f"{block['trading_session_count']}",
        f"- candidate / usable / empty blocks: {block['candidate_block_count']} / "
        f"{block['usable_block_count']} / {block['empty_block_count']}",
        f"- moving-block 95% interval: [{_percent(block['ci_lower'])}, "
        f"{_percent(block['ci_upper'])}]",
        "",
        "## MFE diagnostic",
        "",
        f"- baseline MFE observations / positive MFE: "
        f"{baseline['mfe_observation_count']} / {baseline['positive_mfe_count']}",
        f"- baseline MFE capture / mean give-up: "
        f"{_percent(baseline['mfe_capture_mean'])} / {_percent(baseline['mean_give_up'])}",
        f"- challenger MFE observations / positive MFE: "
        f"{challenger['mfe_observation_count']} / {challenger['positive_mfe_count']}",
        f"- minimum positive-MFE denominator: {challenger['mfe_capture_min_count']}",
        f"- MFE capture mean: {_percent(challenger['mfe_capture_mean'])}",
        f"- mean give-up: {_percent(challenger['mean_give_up'])}",
        "- MFE uses non-executable daily highs and is diagnostic only; it is not a fill series.",
        "",
        "This report is shadow-only and is never production-eligible.",
        "",
    ]
    return "\n".join(lines)


def _open_output_directory(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
                os.fsync(descriptor)
                child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(descriptor, view)
        view = view[written:]


def _stage_at(
    directory_fd: int,
    target_name: str,
    content: bytes,
    *,
    temporary_name: str | None = None,
) -> str:
    temporary_name = temporary_name or f".{target_name}.tmp-{secrets.token_hex(12)}"
    descriptor = os.open(
        temporary_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o644,
        dir_fd=directory_fd,
    )
    try:
        _write_all(descriptor, content)
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        os.unlink(temporary_name, dir_fd=directory_fd)
        raise
    os.close(descriptor)
    return temporary_name


def _read_regular_at(directory_fd: int, name: str) -> bytes | None:
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode):
        raise FileExistsError(
            f"immutable report conflict: nonregular or symlink artifact {name}"
        )
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        dir_fd=directory_fd,
    )
    try:
        content, _ = _read_stable_descriptor(
            descriptor, label=f"report artifact {name}"
        )
        return content
    finally:
        os.close(descriptor)


def _fsync_regular_at(directory_fd: int, name: str) -> None:
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        dir_fd=directory_fd,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise FileExistsError(
                f"immutable report conflict: nonregular or symlink artifact {name}"
            )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


_HARDLINK_FALLBACK_ERRNOS = frozenset(
    {errno.EXDEV, errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS}
)


def _rename_noreplace_at(directory_fd: int, source_name: str, target_name: str) -> None:
    """Atomically rename within a directory while refusing target replacement."""
    libc = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(source_name)
    target = os.fsencode(target_name)
    if hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        result = rename(directory_fd, source, directory_fd, target, 1)
    elif hasattr(libc, "renameatx_np"):
        rename = libc.renameatx_np
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        result = rename(directory_fd, source, directory_fd, target, 0x00000004)
    else:
        raise OSError(errno.EOPNOTSUPP, "atomic no-replace rename is unavailable")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), target_name)


def _publish_exclusive(
    directory_fd: int,
    temporary_name: str,
    target_name: str,
    content: bytes,
) -> None:
    existing = _read_regular_at(directory_fd, target_name)
    if existing is not None:
        if existing == content:
            return
        raise FileExistsError(
            f"immutable report conflict: mismatched artifact {target_name}"
        )
    try:
        os.link(
            temporary_name,
            target_name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileExistsError:
        existing = _read_regular_at(directory_fd, target_name)
        if existing == content:
            return
        raise FileExistsError(
            f"immutable report conflict: mismatched artifact {target_name}"
        ) from None
    except OSError as exc:
        if exc.errno not in _HARDLINK_FALLBACK_ERRNOS:
            raise
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
        try:
            existing = _read_regular_at(directory_fd, target_name)
            if existing is not None:
                if existing == content:
                    return
                raise FileExistsError(
                    f"immutable report conflict: mismatched artifact {target_name}"
                )
            try:
                _rename_noreplace_at(directory_fd, temporary_name, target_name)
            except FileExistsError:
                existing = _read_regular_at(directory_fd, target_name)
                if existing == content:
                    return
                raise FileExistsError(
                    f"immutable report conflict: mismatched artifact {target_name}"
                ) from None
            _fsync_regular_at(directory_fd, target_name)
            os.fsync(directory_fd)
        finally:
            fcntl.flock(directory_fd, fcntl.LOCK_UN)
        return
    _fsync_regular_at(directory_fd, target_name)


def _commit_marker_content(
    stem: str, json_content: bytes, markdown_content: bytes, semantic_hash: str
) -> bytes:
    marker = {
        "schema_version": 1,
        "report_id": stem,
        "contract_identity": REPORT_CONTRACT_IDENTITY,
        "semantic_payload_sha256": semantic_hash,
        "artifacts": {
            "json": {
                "filename": f"{stem}.json",
                **_content_fingerprint(json_content),
            },
            "markdown": {
                "filename": f"{stem}.md",
                **_content_fingerprint(markdown_content),
            },
        },
    }
    return (
        json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _semantic_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _verified_committed_bundle(output_dir: Path, stem: str) -> bool:
    """Return true only for a complete, internally consistent immutable bundle."""
    directory_fd = _open_output_directory(output_dir)
    try:
        marker_name = f"{stem}.commit.json"
        marker_content = _read_regular_at(directory_fd, marker_name)
        if marker_content is None:
            return False
        try:
            marker = json.loads(marker_content)
            if marker.get("schema_version") != 1 or marker.get("report_id") != stem:
                raise ValueError("invalid marker identity")
            if marker.get("contract_identity") != REPORT_CONTRACT_IDENTITY:
                raise ValueError("invalid marker contract")
            artifacts = marker["artifacts"]
            json_name = f"{stem}.json"
            markdown_name = f"{stem}.md"
            if artifacts["json"]["filename"] != json_name:
                raise ValueError("invalid JSON artifact filename")
            if artifacts["markdown"]["filename"] != markdown_name:
                raise ValueError("invalid markdown artifact filename")
            json_content = _read_regular_at(directory_fd, json_name)
            markdown_content = _read_regular_at(directory_fd, markdown_name)
            if json_content is None or markdown_content is None:
                raise ValueError("committed artifact is missing")
            if _content_fingerprint(json_content) != {
                "sha256": artifacts["json"]["sha256"],
                "size_bytes": artifacts["json"]["size_bytes"],
            }:
                raise ValueError("JSON artifact fingerprint mismatch")
            if _content_fingerprint(markdown_content) != {
                "sha256": artifacts["markdown"]["sha256"],
                "size_bytes": artifacts["markdown"]["size_bytes"],
            }:
                raise ValueError("markdown artifact fingerprint mismatch")
            payload = json.loads(json_content)
            identity = payload.pop("artifact_identity")
            semantic_hash = _semantic_payload_hash(payload)
            if semantic_hash != marker["semantic_payload_sha256"]:
                raise ValueError("semantic payload fingerprint mismatch")
            if identity["semantic_payload_sha256"] != semantic_hash:
                raise ValueError("JSON semantic identity mismatch")
            if identity["markdown_sha256"] != hashlib.sha256(markdown_content).hexdigest():
                raise ValueError("JSON markdown identity mismatch")
            if identity["commit_marker_filename"] != marker_name:
                raise ValueError("JSON marker identity mismatch")
        except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise FileExistsError(
                f"immutable report conflict: invalid committed bundle {stem}"
            ) from exc
        return True
    finally:
        os.close(directory_fd)


def _commit_report_bundle(
    output_dir: Path,
    stem: str,
    json_content: bytes,
    markdown_content: bytes,
    semantic_hash: str,
) -> None:
    output_dir = _absolute_lexical(output_dir)
    _reject_symlink_components(output_dir, label="output", allow_missing=True)
    directory_fd = _open_output_directory(output_dir)
    names_and_content = (
        (f"{stem}.json", json_content),
        (f"{stem}.md", markdown_content),
    )
    marker_name = f"{stem}.commit.json"
    marker_content = _commit_marker_content(
        stem, json_content, markdown_content, semantic_hash
    )
    staged: list[str] = []
    try:
        existing_marker = _read_regular_at(directory_fd, marker_name)
        if existing_marker is not None:
            if existing_marker != marker_content:
                raise FileExistsError(
                    "immutable report conflict: mismatched commit marker"
                )
            for name, content in names_and_content:
                if _read_regular_at(directory_fd, name) != content:
                    raise FileExistsError(
                        "immutable report conflict: commit marker artifact mismatch"
                    )
            return

        data_stages: list[tuple[str, str, bytes]] = []
        for name, content in names_and_content:
            existing = _read_regular_at(directory_fd, name)
            if existing is not None:
                if existing != content:
                    raise FileExistsError(
                        f"immutable report conflict: mismatched artifact {name}"
                    )
                continue
            temporary = f".{name}.tmp-{secrets.token_hex(12)}"
            staged.append(temporary)
            _stage_at(
                directory_fd,
                name,
                content,
                temporary_name=temporary,
            )
            data_stages.append((temporary, name, content))
        for temporary, name, content in data_stages:
            _publish_exclusive(directory_fd, temporary, name, content)
        for name, _ in names_and_content:
            _fsync_regular_at(directory_fd, name)
        os.fsync(directory_fd)

        marker_stage = f".{marker_name}.tmp-{secrets.token_hex(12)}"
        staged.append(marker_stage)
        _stage_at(
            directory_fd,
            marker_name,
            marker_content,
            temporary_name=marker_stage,
        )
        _publish_exclusive(directory_fd, marker_stage, marker_name, marker_content)
        os.fsync(directory_fd)
    finally:
        for temporary in staged:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _validate_args(args, parser)
    stem = f"exit_shadow_{args.as_of}"
    if args.as_of != _civil_today().strftime("%Y%m%d"):
        if _verified_committed_bundle(args.output_dir, stem):
            return 0
        parser.error(
            "historical --as-of is not PIT-eligible because journal event availability is unverifiable"
        )
    with _stable_input_snapshot(args.journal, args.price_cache, as_of=args.as_of) as snapshot:
        payload = _build_payload(
            journal=snapshot.journal,
            price_cache=snapshot.price_cache,
            live_journal=args.journal,
            live_price_cache=args.price_cache,
            fingerprints_before=snapshot.fingerprints_before,
            snapshot_fingerprint=snapshot.snapshot_fingerprint,
            cutoff_audit=snapshot.cutoff_audit,
            as_of=args.as_of,
            bootstrap_seed=args.bootstrap_seed,
            bootstrap_draws=args.bootstrap_draws,
        )
    semantic_hash = _semantic_payload_hash(payload)
    payload["artifact_identity"] = {
        "contract_identity": REPORT_CONTRACT_IDENTITY,
        "semantic_payload_sha256": semantic_hash,
        "commit_marker_filename": f"{stem}.commit.json",
    }
    markdown_content = _render_markdown(payload).encode("utf-8")
    payload["artifact_identity"]["markdown_sha256"] = hashlib.sha256(
        markdown_content
    ).hexdigest()
    json_content = (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    final_fingerprints, _, _ = _read_live_inputs(args.journal, args.price_cache, as_of=args.as_of)
    if final_fingerprints != payload["input_fingerprints_after"]:
        raise RuntimeError("inputs changed during report run; refusing publication")
    _commit_report_bundle(
        args.output_dir,
        stem,
        json_content,
        markdown_content,
        semantic_hash,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
