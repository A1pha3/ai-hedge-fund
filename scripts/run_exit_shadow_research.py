#!/usr/bin/env python3
"""Write an immutable, research-only legacy exit-sensitivity report."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from src.research.exit_shadow_research import (
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
_PRE_DENOMINATOR_EXCLUSION_REASONS = frozenset(
    {"duplicate_buy", "duplicate_exit", "unmatched_buy", "unmatched_exit"}
)


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


def _validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    try:
        parsed = datetime.strptime(args.as_of, "%Y%m%d")
    except ValueError:
        parser.error("--as-of must be a valid date in YYYYMMDD format")
    if parsed.strftime("%Y%m%d") != args.as_of:
        parser.error("--as-of must be a valid date in YYYYMMDD format")
    if not args.journal.is_file():
        parser.error(f"journal is not a readable file: {args.journal}")
    if not args.price_cache.is_dir():
        parser.error(f"price cache is not a readable directory: {args.price_cache}")
    if args.bootstrap_draws < 1:
        parser.error("--bootstrap-draws must be positive")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_fingerprint(path: Path) -> dict[str, Any]:
    return {
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _directory_fingerprint(path: Path) -> dict[str, Any]:
    files = sorted(item for item in path.rglob("*") if item.is_file())
    manifest = [
        {
            "path": item.relative_to(path).as_posix(),
            **_file_fingerprint(item),
        }
        for item in files
    ]
    encoded = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "file_count": len(manifest),
        "files": manifest,
    }


def _input_fingerprints(journal: Path, price_cache: Path) -> dict[str, Any]:
    return {
        "journal": _file_fingerprint(journal),
        "price_cache": _directory_fingerprint(price_cache),
    }


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
    as_of: str,
    bootstrap_seed: int,
    bootstrap_draws: int,
) -> dict[str, Any]:
    fingerprints = _input_fingerprints(journal, price_cache)
    cohort = build_legacy_cohort(journal, price_cache_dir=price_cache)
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
    if _input_fingerprints(journal, price_cache) != fingerprints:
        raise RuntimeError("inputs changed during report run; refusing publication")
    audit = asdict(cohort.audit)
    return {
        "schema_version": 1,
        "report_id": f"exit_shadow_{as_of}",
        "as_of": as_of,
        "mode": REPORT_MODE,
        "shadow_only": True,
        "production_eligible": False,
        "parameters": {
            "activation_return": ACTIVATION_RETURN,
            "atr_multiple": ATR_MULTIPLE,
        },
        "policy_identity": {
            "name": "fixed_activation_atr_trailing_exit",
            "fixed": True,
            "block_sessions": BLOCK_SESSIONS,
            "cost_version": FIXED_COSTS.version,
            "execution_costs": asdict(FIXED_COSTS),
            "plan_exit_session": PLAN_EXIT_SESSION,
            "planned_execution": "next_executable_open",
        },
        "input_fingerprints": fingerprints,
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


def _render_markdown(payload: dict[str, Any]) -> str:
    cohort = payload["cohort"]
    common = payload["common_mask"]
    stats = payload["statistics"]
    block = stats["block_mean_difference"]
    missingness = cohort["missingness_bias"]
    challenger = stats["challenger"]
    lines = [
        "# Legacy sensitivity / shadow only",
        "",
        f"- report_id: {payload['report_id']}",
        "- mode: legacy_sensitivity",
        "- shadow_only: true",
        "- production_eligible: false",
        "- fixed policy: activation_return=10.00%, atr_multiple=2.5",
        f"- execution cost identity: {payload['policy_identity']['cost_version']}",
        "",
        "## Why this cohort differs from current production",
        "",
        "- It is a retrospective six-month legacy backtest, not a live forward sample.",
        "- It includes paired BTST exits only, not the current production opportunity set.",
        "- Results use a selected common executable mask after reconstruction exclusions.",
        "- Current board-rule mismatches are disclosed rather than silently filtered.",
        "- The fixed challenger is sensitivity evidence and cannot promote a policy.",
        "",
        "## Denominators, exclusions, and coverage",
        "",
        f"- paired BTST denominator: {cohort['denominator']}",
        f"- reconstructable paths: {common['total_paths']}",
        f"- executable common mask: {common['eligible']}",
        f"- statistical coverage: {_percent(stats['coverage'])}",
        f"- cohort exclusions: {len(cohort['exclusions'])}",
        f"- replay exclusions: {len(common['excluded'])}",
        f"- covered legacy mean: {_percent(missingness['covered_legacy_mean'])}",
        f"- missing legacy mean: {_percent(missingness['missing_legacy_mean'])}",
        f"- selection bias warning: {str(missingness['selection_bias_warning']).lower()}",
        "",
        "## Paired and block sensitivity",
        "",
        f"- trades / signal days / non-overlapping windows: {stats['trade_count']} / "
        f"{stats['signal_day_count']} / {stats['nonoverlapping_window_count']}",
        f"- mean / median / worst-decile paired difference: "
        f"{_percent(stats['mean_difference'])} / {_percent(stats['median_difference'])} / "
        f"{_percent(stats['worst_decile_difference'])}",
        f"- moving-block sessions / draws / seed: {block['block_sessions']} / "
        f"{block['draws']} / {block['seed']}",
        f"- moving-block 95% interval: [{_percent(block['ci_lower'])}, "
        f"{_percent(block['ci_upper'])}]",
        "",
        "## MFE diagnostic",
        "",
        f"- challenger MFE observations / positive MFE: "
        f"{challenger['mfe_observation_count']} / {challenger['positive_mfe_count']}",
        f"- minimum positive-MFE denominator: {challenger['mfe_capture_min_count']}",
        f"- MFE capture mean: {_percent(challenger['mfe_capture_mean'])}",
        f"- mean give-up: {_percent(challenger['mean_give_up'])}",
        "- MFE is diagnostic only; daily highs are not executable fills.",
        "",
        "This report is shadow-only and is never production-eligible.",
        "",
    ]
    return "\n".join(lines)


def _stage(path: Path, content: bytes) -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    staged = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


def _publish_immutable_pair(files: tuple[tuple[Path, bytes], ...]) -> None:
    mismatched = [
        path
        for path, content in files
        if path.exists() and path.read_bytes() != content
    ]
    if mismatched:
        raise FileExistsError(
            "immutable report conflict: same report id has different content"
        )
    pending = tuple((path, content) for path, content in files if not path.exists())
    if not pending:
        return

    staged: list[tuple[Path, Path]] = []
    published: list[Path] = []
    try:
        for path, content in pending:
            staged.append((_stage(path, content), path))
        for temporary, target in staged:
            os.link(temporary, target)
            published.append(target)
    except FileExistsError as exc:
        if all(
            path.exists() and path.read_bytes() == content for path, content in files
        ):
            return
        for target in published:
            target.unlink(missing_ok=True)
        raise FileExistsError(
            "immutable report conflict: same report id was published concurrently"
        ) from exc
    except BaseException:
        for target in published:
            target.unlink(missing_ok=True)
        raise
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _validate_args(args, parser)
    payload = _build_payload(
        journal=args.journal,
        price_cache=args.price_cache,
        as_of=args.as_of,
        bootstrap_seed=args.bootstrap_seed,
        bootstrap_draws=args.bootstrap_draws,
    )
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
    markdown_content = _render_markdown(payload).encode("utf-8")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"exit_shadow_{args.as_of}"
    _publish_immutable_pair(
        (
            (args.output_dir / f"{stem}.json", json_content),
            (args.output_dir / f"{stem}.md", markdown_content),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
