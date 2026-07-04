"""Parameter grid comparison for backtest runs.

Parses a compact ``"key=v1,v2;key2=v3,v4"`` grid spec, expands it into the
cartesian product, runs each combination in parallel via
:class:`concurrent.futures.ThreadPoolExecutor`, and renders a side-by-side
comparison table (Sharpe / win-rate / max drawdown / total return).

The module is intentionally decoupled from :class:`BacktestEngine`: callers
provide an *evaluator* callable (params -> metrics dict).  This keeps the
infrastructure reusable from both the CLI and unit tests, and matches the
"pluggable evaluator" pattern used by :mod:`src.backtesting.param_search`.
"""

from __future__ import annotations

import csv
import itertools
import json
import logging
import math
import os
from collections.abc import Callable, Sequence
from concurrent.futures import as_completed, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


def _is_finite_number(value: Any) -> bool:
    """Return True iff value is a real number (int/float, not bool) and finite.

    Used to drop NaN/Inf metric values from ``best_trial`` /
    ``trials_sorted_by`` so a corrupt metric can never bubble up as the
    "best" via IEEE-754 sort quirks.
    """
    if isinstance(value, bool):
        return True
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


GRID_ENV_VAR = "ANALYST_CONCURRENCY_LIMIT"
DEFAULT_GRID_MAX_WORKERS = 2
"""Default worker count for the grid runner.  Mirrors the default for
:data:`scripts.supervise_ab_compare.DEFAULT_ANALYST_CONCURRENCY_LIMIT` and
the default in :mod:`src.main` (so a single in-process backtester matches
the budget already negotiated with the LLM provider)."""


# ---------------------------------------------------------------------------
# Grid spec parsing
# ---------------------------------------------------------------------------


class ParamGridError(ValueError):
    """Raised when a ``--param-grid`` string cannot be parsed."""


def _coerce_value(raw: str) -> Any:
    """Coerce a single value cell to ``int`` / ``float`` / ``str`` / ``bool``.

    The coercion order is deliberately permissive: booleans and ints are
    detected before floats so that ``"10"`` stays an int (consistent with
    CLI flag types such as ``--baseline-top-n``) and ``"0.5"`` becomes a
    float.  Strings that fail both attempts remain strings.
    """
    text = raw.strip()
    if not text:
        raise ParamGridError("empty value cell in --param-grid (check trailing commas)")

    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"

    # int (no decimal, optional sign)
    try:
        return int(text)
    except ValueError:
        pass

    # float
    try:
        return float(text)
    except ValueError:
        pass

    return text


def parse_param_grid(spec: str) -> dict[str, list[Any]]:
    """Parse a ``"key=v1,v2;key2=v3,v4"`` style grid spec.

    Format:
      - Dimensions are separated by ``;``.
      - Within a dimension, ``key`` is followed by ``=`` then a comma-separated
        list of values.
      - Values are coerced via :func:`_coerce_value` (int / float / bool / str).
      - Whitespace around tokens is stripped.

    Raises:
        ParamGridError: when the spec is empty, contains duplicate keys,
            a dimension has zero values, or any value cell is empty.

    Returns:
        Dict mapping dimension name -> ordered list of values.
    """
    if spec is None or not spec.strip():
        raise ParamGridError("--param-grid is empty; expected 'key=v1,v2;key2=v3,v4'")

    grid: dict[str, list[Any]] = {}
    for raw_dim in spec.split(";"):
        dim = raw_dim.strip()
        if not dim:
            continue
        if "=" not in dim:
            raise ParamGridError(f"invalid --param-grid dimension {dim!r}: expected 'key=v1,v2' format")
        key, raw_values = dim.split("=", 1)
        key = key.strip()
        if not key:
            raise ParamGridError(f"empty dimension name in --param-grid segment {dim!r}")
        if key in grid:
            raise ParamGridError(f"duplicate dimension {key!r} in --param-grid")
        values = [_coerce_value(cell) for cell in raw_values.split(",")]
        if not values:
            raise ParamGridError(f"dimension {key!r} has no values")
        grid[key] = values
    if not grid:
        raise ParamGridError("--param-grid contains no dimensions")
    return grid


def grid_combinations(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Expand a grid dict into the cartesian product of params dicts.

    Keys are returned sorted lexicographically so the trial order is
    deterministic across runs (helpful for caching and debugging).  An
    empty grid yields an empty list (rather than the
    ``[itertools.product()] == [()]`` surprise of a single empty combo)
    so callers can short-circuit cleanly.
    """
    if not grid:
        return []
    keys = sorted(grid.keys())
    value_lists = [grid[k] for k in keys]
    return [dict(zip(keys, combo, strict=False)) for combo in itertools.product(*value_lists)]


# ---------------------------------------------------------------------------
# Trial / report dataclasses
# ---------------------------------------------------------------------------


# Metrics pulled out of the evaluator's dict and surfaced in the comparison
# table.  Order is the column order in CSV / Markdown / console output.
COMPARISON_METRICS: tuple[str, ...] = (
    "sharpe_ratio",
    "sortino_ratio",
    "max_drawdown",
    "win_rate",
    "total_return",
    "window_count",
)
"""Metric columns captured from each trial's metrics dict (None cells become
the empty string in output)."""


@dataclass(frozen=True)
class ParamGridTrial:
    """One row of the comparison table.

    Attributes:
        trial_index: 0-based index assigned by :func:`run_param_grid`.
        params: The parameter dict for this trial (frozen so callers can
            rely on the key set without copying).
        metrics: Flat dict of metric name -> numeric value (or None).
        duration_seconds: Wall-clock time the evaluator took to run.
        error: Captured exception message (``None`` on success).  When set,
            the metrics dict will still contain a ``status`` key but the
            numeric metric columns will be ``None``.
    """

    trial_index: int
    params: dict[str, Any]
    metrics: dict[str, float | int | str | None]
    duration_seconds: float
    error: str | None = None

    def is_failed(self) -> bool:
        return self.error is not None

    def to_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {f"param.{k}": v for k, v in sorted(self.params.items())}
        for key in COMPARISON_METRICS:
            row[key] = self.metrics.get(key)
        row["duration_s"] = round(self.duration_seconds, 3)
        row["status"] = "failed" if self.is_failed() else "ok"
        if self.error is not None:
            row["error"] = self.error
        return row


@dataclass
class ParamGridReport:
    """Aggregated result of a parameter grid run."""

    trials: list[ParamGridTrial] = field(default_factory=list)
    total_combinations: int = 0
    max_workers: int = 1

    @property
    def completed(self) -> int:
        return sum(1 for t in self.trials if not t.is_failed())

    @property
    def failed(self) -> int:
        return sum(1 for t in self.trials if t.is_failed())

    def trials_sorted_by(self, metric: str, *, descending: bool = True) -> list[ParamGridTrial]:
        """Return trials sorted by *metric*; failed/missing values go last.

        The primary key is a present/missing flag so trials missing the
        metric (None) always sort to the end regardless of ``descending``.
        Within the present bucket, trials are ordered by the metric value
        in the requested direction (default: descending — best first).
        Non-finite (NaN/Inf) values are treated as missing so a corrupt
        metric can never appear above finite values via IEEE-754 quirks.
        """
        finite_trials = [t for t in self.trials if t.metrics.get(metric) is not None and _is_finite_number(t.metrics[metric])]
        missing_trials = [t for t in self.trials if t.metrics.get(metric) is None or not _is_finite_number(t.metrics[metric])]
        finite_trials.sort(key=lambda t: float(t.metrics[metric]), reverse=descending)
        # ``missing_trials`` keeps its original report order so failed
        # rows render in the same order they were submitted.
        return finite_trials + missing_trials

    def best_trial(self, metric: str = "sharpe_ratio") -> ParamGridTrial | None:
        passing = [t for t in self.trials if not t.is_failed()]
        if not passing:
            return None
        # Sort *passing* trials directly so a high metric on a failed
        # trial (e.g. partial metrics returned before the exception) can
        # never beat a real passing trial.
        present = [t for t in passing if t.metrics.get(metric) is not None]
        if not present:
            return None
        # Drop non-finite (NaN/Inf) metrics so a corrupt numeric value can
        # never bubble up as the "best trial" via IEEE-754 sort quirks.
        finite = [t for t in present if _is_finite_number(t.metrics[metric])]
        if not finite:
            return None
        return sorted(finite, key=lambda t: float(t.metrics[metric]), reverse=True)[0]


# ---------------------------------------------------------------------------
# Worker pool
# ---------------------------------------------------------------------------


def _resolve_max_workers(explicit: int | None) -> int:
    # Explicit 0/negative is a programming error / convenience typo; clamp
    # to 1 instead of falling through to the env-var default so the call
    # site (e.g. ``--max-workers 0``) behaves predictably.
    if explicit is not None:
        if explicit <= 0:
            return 1
        return int(explicit)
    try:
        env_value = int(os.getenv(GRID_ENV_VAR, str(DEFAULT_GRID_MAX_WORKERS)))
    except (TypeError, ValueError):
        env_value = DEFAULT_GRID_MAX_WORKERS
    return max(1, env_value)


def _run_single_trial(
    evaluator: Callable[[dict[str, Any]], dict[str, Any]],
    trial_index: int,
    params: dict[str, Any],
) -> ParamGridTrial:
    """Execute a single trial and package the result.

    Separated from :func:`run_param_grid` so it can be tested directly and
    so the worker pool submission is one line.
    """
    import time as _time

    started = _time.perf_counter()
    try:
        raw_metrics = evaluator(dict(params)) or {}
    except Exception as exc:  # noqa: BLE001 - we want to capture any evaluator failure
        duration = _time.perf_counter() - started
        _logger.exception("Trial %d failed: %s", trial_index, exc)
        return ParamGridTrial(
            trial_index=trial_index,
            params=dict(params),
            metrics={"status": "failed"},
            duration_seconds=duration,
            error=f"{type(exc).__name__}: {exc}",
        )
    duration = _time.perf_counter() - started
    metrics: dict[str, float | int | str | None] = {"status": "ok"}
    for key in COMPARISON_METRICS:
        if key in raw_metrics:
            metrics[key] = raw_metrics[key]
    # Preserve any extra keys the caller wants in the JSON payload.
    for key, value in raw_metrics.items():
        if key not in metrics:
            metrics[key] = value
    return ParamGridTrial(
        trial_index=trial_index,
        params=dict(params),
        metrics=metrics,
        duration_seconds=duration,
    )


def run_param_grid(
    *,
    grid: dict[str, list[Any]],
    evaluator: Callable[[dict[str, Any]], dict[str, Any]],
    max_workers: int | None = None,
) -> ParamGridReport:
    """Run the grid's cartesian product through *evaluator* in parallel.

    Args:
        grid: Output of :func:`parse_param_grid` (param name -> value list).
        evaluator: Callable taking a params dict and returning a flat
            metrics dict.  Must be thread-safe — it will be invoked from
            worker threads.
        max_workers: Concurrency cap.  ``None`` reads
            :data:`GRID_ENV_VAR` and falls back to
            :data:`DEFAULT_GRID_MAX_WORKERS`.  Values <= 0 are clamped to 1.

    Returns:
        :class:`ParamGridReport` with one :class:`ParamGridTrial` per
        combination.  Trial ordering follows submission order
        (which is :func:`grid_combinations` order, i.e. sorted keys).
    """
    combinations = grid_combinations(grid)
    workers = _resolve_max_workers(max_workers)
    report = ParamGridReport(trials=[], total_combinations=len(combinations), max_workers=workers)

    if not combinations:
        return report

    # Submit all trials, then drain in completion order so a slow trial
    # can't stall the others' results from appearing in the report.
    futures = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, params in enumerate(combinations):
            future = pool.submit(_run_single_trial, evaluator, index, params)
            futures[future] = index
        for future in as_completed(futures):
            report.trials.append(future.result())

    # Restore the cartesian-product order so the table is deterministic
    # regardless of which thread finished first.
    report.trials.sort(key=lambda t: t.trial_index)
    _logger.info(
        "Param grid complete: %d/%d trials succeeded (workers=%d)",
        report.completed,
        report.total_combinations,
        workers,
    )
    return report


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------


def _format_metric(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, (int,)):
        return f"{value}"
    return str(value)


def _column_headers(trials: Sequence[ParamGridTrial]) -> list[str]:
    param_keys: list[str] = []
    if trials:
        param_keys = sorted(trials[0].params.keys())
    return [*param_keys, *COMPARISON_METRICS, "duration_s", "status"]


def _row_cells(trial: ParamGridTrial, param_keys: Sequence[str]) -> list[str]:
    cells = [_format_metric(trial.params.get(k)) for k in param_keys]
    cells.extend(_format_metric(trial.metrics.get(m)) for m in COMPARISON_METRICS)
    cells.append(f"{trial.duration_seconds:.3f}")
    cells.append("FAILED" if trial.is_failed() else "ok")
    return cells


def _column_widths(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[int]:
    widths = [len(h) for h in headers]
    for row in rows:
        for index, cell in enumerate(row):
            if index >= len(widths):
                widths.append(len(cell))
            elif len(cell) > widths[index]:
                widths[index] = len(cell)
    return widths


def _format_row(cells: Sequence[str], widths: Sequence[int]) -> str:
    return " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))


def _format_separator(widths: Sequence[int]) -> str:
    return "-+-".join("-" * w for w in widths)


def render_console_table(report: ParamGridReport) -> str:
    """Render the report as a fixed-width console table.

    The output mirrors the markdown table layout so researchers can
    paste the same content into a PR / chat without reformatting.
    Failed trials are included with a ``FAILED`` status and pushed to
    the bottom of the table regardless of metric values.
    """
    if not report.trials:
        return "(no trials)"

    param_keys: list[str] = sorted(report.trials[0].params.keys())
    headers = _column_headers(report.trials)
    rows = [_row_cells(trial, param_keys) for trial in report.trials]
    widths = _column_widths(headers, rows)
    lines = [_format_row(headers, widths), _format_separator(widths)]
    lines.extend(_format_row(row, widths) for row in rows)
    return "\n".join(lines)


def render_markdown_table(
    report: ParamGridReport,
    *,
    sort_by: str = "sharpe_ratio",
) -> str:
    """Render the report as a Markdown table sorted by *sort_by*."""
    lines: list[str] = ["# Parameter Grid Comparison", ""]
    lines.append(f"- Total combinations: **{report.total_combinations}**")
    lines.append(f"- Completed: **{report.completed}**")
    lines.append(f"- Failed: **{report.failed}**")
    lines.append(f"- Max workers: **{report.max_workers}**")
    lines.append(f"- Sort metric: **{sort_by}** (descending)")
    lines.append("")

    if not report.trials:
        lines.append("_No trials to display._")
        return "\n".join(lines)

    best = report.best_trial(sort_by)
    if best is not None:
        lines.append("## Best Trial")
        lines.append("")
        for k, v in sorted(best.params.items()):
            lines.append(f"- `{k}`: {v}")
        for metric in COMPARISON_METRICS:
            value = best.metrics.get(metric)
            if value is not None:
                lines.append(f"- `{metric}`: {value}")
        lines.append("")

    sorted_trials = report.trials_sorted_by(sort_by)
    param_keys = sorted(report.trials[0].params.keys())
    headers = _column_headers(report.trials)
    lines.append("## Results")
    lines.append("")
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for trial in sorted_trials:
        cells = _row_cells(trial, param_keys)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def save_csv_report(report: ParamGridReport, output_path: str | Path) -> Path:
    """Write the report to CSV (one row per trial).

    Numeric metric cells are written as raw values; missing metrics become
    empty strings.  Param values are emitted as ``param.<name>`` columns
    so they share the same prefix across all param names and don't
    collide with metric keys.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not report.trials:
        # Always emit a header-only CSV so downstream pipelines don't
        # choke on a missing file.
        path.write_text("", encoding="utf-8")
        return path

    rows = [trial.to_row() for trial in report.trials]
    headers = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([row.get(h, "") for h in headers])
    return path


def save_json_report(
    report: ParamGridReport,
    output_path: str | Path,
    *,
    sort_by: str = "sharpe_ratio",
) -> Path:
    """Write the report to a JSON file with a stable, sorted shape."""
    payload = {
        "summary": {
            "total_combinations": report.total_combinations,
            "completed": report.completed,
            "failed": report.failed,
            "max_workers": report.max_workers,
            "sort_by": sort_by,
            "best_params": report.best_trial(sort_by).params if report.best_trial(sort_by) else None,
        },
        "trials": [
            {
                "trial_index": trial.trial_index,
                "params": trial.params,
                "metrics": trial.metrics,
                "duration_seconds": round(trial.duration_seconds, 3),
                "status": "failed" if trial.is_failed() else "ok",
                "error": trial.error,
            }
            for trial in report.trials_sorted_by(sort_by)
        ],
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def save_markdown_report(
    report: ParamGridReport,
    output_path: str | Path,
    *,
    sort_by: str = "sharpe_ratio",
) -> Path:
    """Write the markdown report (alias of :func:`render_markdown_table`)."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown_table(report, sort_by=sort_by), encoding="utf-8")
    return path


__all__ = [
    "COMPARISON_METRICS",
    "DEFAULT_GRID_MAX_WORKERS",
    "GRID_ENV_VAR",
    "ParamGridError",
    "ParamGridReport",
    "ParamGridTrial",
    "grid_combinations",
    "parse_param_grid",
    "render_console_table",
    "render_markdown_table",
    "run_param_grid",
    "save_csv_report",
    "save_json_report",
    "save_markdown_report",
    # Re-exported so the CLI doesn't have to reach into the dataclass.
    "asdict",
]
