"""Parameter search framework for short-trade target profile optimization.

Provides grid search over profile parameters evaluated via replay-based
multi-window analysis. Supports checkpointing and ranked output.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from src.backtesting.evaluation_bundle import (
    build_canonical_btst_evaluation_bundle,
    coerce_numeric_metric_value,
)
from src.utils.numeric import clip

_logger = logging.getLogger(__name__)

GuardrailSpec = float | int | dict[str, float | bool]


class SearchObjective(StrEnum):
    SHARPE = "sharpe"
    SORTINO = "sortino"
    COMPOSITE = "composite"
    EDGE = "edge"
    BTST = "btst"
    BTST_RUNNER = "btst_runner"


@dataclass(frozen=True)
class TrialResult:
    trial_index: int
    params: dict[str, Any]
    metrics: dict[str, float | None]
    window_count: int
    score: float | None = None
    failed_guardrails: tuple[str, ...] = ()


@dataclass
class ParamSpace:
    grid: dict[str, list[Any]]

    def combinations(self) -> list[dict[str, Any]]:
        keys = sorted(self.grid.keys())
        values = [self.grid[k] for k in keys]
        return [dict(zip(keys, combo, strict=False)) for combo in itertools.product(*values)]

    def size(self) -> int:
        result = 1
        for v in self.grid.values():
            result *= len(v)
        return result


@dataclass
class SearchReport:
    objective: SearchObjective
    results: list[TrialResult] = field(default_factory=list)
    best_params: dict[str, Any] = field(default_factory=dict)
    best_score: float | None = None
    total_trials: int = 0
    completed_trials: int = 0
    # UTC ISO-8601 timestamp captured when the report is finalized (run_param_search
    # return). Renders into the markdown/json header so a reader reopening a saved
    # report knows when it was generated — trust-calibration for re-runnable tuning.
    generated_at: str | None = None


def compute_objective_score(
    metrics: dict[str, float | None],
    objective: SearchObjective,
) -> float | None:
    if objective == SearchObjective.SHARPE:
        return metrics.get("sharpe_ratio")
    if objective == SearchObjective.SORTINO:
        return metrics.get("sortino_ratio")
    if objective == SearchObjective.COMPOSITE:
        sharpe = metrics.get("sharpe_ratio")
        sortino = metrics.get("sortino_ratio")
        max_dd = metrics.get("max_drawdown")
        if sharpe is None or sortino is None or max_dd is None:
            return None
        return 0.4 * sortino + 0.3 * sharpe - 0.3 * abs(max_dd)
    if objective == SearchObjective.EDGE:
        bundle = build_canonical_btst_evaluation_bundle(metrics)
        win_rate = bundle.lookup("next_close_positive_rate")
        payoff_ratio = bundle.lookup("next_close_payoff_ratio")
        expectancy = bundle.lookup("next_close_expectancy")
        next_high_hit_rate = bundle.lookup("next_high_hit_rate")
        t_plus_2_positive_rate = bundle.lookup("t_plus_2_close_positive_rate")
        downside_p10 = bundle.lookup("downside_p10")
        sample_weight = bundle.lookup("sample_weight")
        if win_rate is None or payoff_ratio is None or expectancy is None or next_high_hit_rate is None or t_plus_2_positive_rate is None or downside_p10 is None:
            return None

        normalized_payoff = clip(float(payoff_ratio) / 3.0, 0.0, 1.0)
        normalized_expectancy = clip((float(expectancy) + 0.03) / 0.06, 0.0, 1.0)
        downside_penalty = clip(abs(float(downside_p10)) / 0.06, 0.0, 1.0)
        effective_sample_weight = clip(float(sample_weight or 0.0), 0.0, 1.0)
        edge_score = (0.28 * float(win_rate)) + (0.22 * normalized_payoff) + (0.16 * float(next_high_hit_rate)) + (0.14 * float(t_plus_2_positive_rate)) + (0.20 * normalized_expectancy) - (0.18 * downside_penalty)
        return edge_score * (0.40 + (0.60 * effective_sample_weight))
    if objective == SearchObjective.BTST:
        if metrics.get("promotion_guardrail_pass") is False:
            return None
        bundle = build_canonical_btst_evaluation_bundle(metrics)
        win_rate = bundle.lookup("next_close_positive_rate")
        payoff_ratio = bundle.lookup("next_close_payoff_ratio")
        expectancy = bundle.lookup("next_close_expectancy")
        next_high_hit_rate = bundle.lookup("next_high_hit_rate")
        t_plus_2_positive_rate = bundle.lookup("t_plus_2_close_positive_rate")
        t_plus_3_positive_rate = bundle.lookup("t_plus_3_close_positive_rate")
        t_plus_3_expectancy = bundle.lookup("t_plus_3_close_expectancy")
        downside_p10 = bundle.lookup("downside_p10")
        sample_weight = bundle.lookup("sample_weight")
        if win_rate is None or payoff_ratio is None or expectancy is None or next_high_hit_rate is None or t_plus_2_positive_rate is None or t_plus_3_positive_rate is None or t_plus_3_expectancy is None or downside_p10 is None:
            return None

        normalized_payoff = clip(float(payoff_ratio) / 3.0, 0.0, 1.0)
        normalized_expectancy = clip((float(expectancy) + 0.03) / 0.06, 0.0, 1.0)
        normalized_t_plus_3_expectancy = clip((float(t_plus_3_expectancy) + 0.03) / 0.08, 0.0, 1.0)
        downside_penalty = clip(abs(float(downside_p10)) / 0.06, 0.0, 1.0)
        effective_sample_weight = clip(float(sample_weight or 0.0), 0.0, 1.0)

        base_score = (0.28 * float(win_rate)) + (0.16 * normalized_payoff) + (0.14 * normalized_expectancy) + (0.14 * float(next_high_hit_rate)) + (0.12 * float(t_plus_2_positive_rate)) + (0.10 * float(t_plus_3_positive_rate)) + (0.10 * normalized_t_plus_3_expectancy) - (0.14 * downside_penalty)
        floor_penalty = (0.50 * max(0.0, 0.54 - float(win_rate))) + (0.28 * max(0.0, 0.56 - float(next_high_hit_rate))) + (0.22 * max(0.0, 0.52 - float(t_plus_2_positive_rate))) + (0.18 * max(0.0, 0.50 - float(t_plus_3_positive_rate))) + (0.12 * max(0.0, 0.0 - float(t_plus_3_expectancy)))

        # Bounded bonus from positive baseline deltas; capped to prevent distortion.
        pos_rate_delta = coerce_numeric_metric_value(metrics.get("baseline_next_close_positive_rate_delta"))
        expectancy_delta = coerce_numeric_metric_value(metrics.get("baseline_next_close_expectancy_delta"))
        delta_bonus = 0.0
        if pos_rate_delta is not None and pos_rate_delta > 0:
            delta_bonus += clip(float(pos_rate_delta) * 1.5, 0.0, 0.04)
        if expectancy_delta is not None and expectancy_delta > 0:
            delta_bonus += clip(float(expectancy_delta) * 5.0, 0.0, 0.02)

        return (base_score - floor_penalty + delta_bonus) * (0.35 + (0.65 * effective_sample_weight))
    if objective == SearchObjective.BTST_RUNNER:
        if metrics.get("promotion_guardrail_pass") is False:
            return None
        bundle = build_canonical_btst_evaluation_bundle(metrics)
        tail_hit_rate_15pct = bundle.lookup("max_future_high_return_2_5d_hit_rate_at_15pct")
        tail_hit_rate = bundle.lookup("max_future_high_return_2_5d_hit_rate_at_20pct")
        tail_median = bundle.lookup("median_max_future_high_return_2_5d")
        next_open_return = bundle.lookup("next_open_return")
        next_open_to_close_return = bundle.lookup("next_open_to_close_return")
        next_close_positive_rate = bundle.lookup("next_close_positive_rate")
        downside_p10 = bundle.lookup("downside_p10")
        sample_weight = clip(float(bundle.lookup("sample_weight") or 0.0), 0.0, 1.0)
        if None in (tail_hit_rate, tail_median, next_open_return, next_open_to_close_return, next_close_positive_rate, downside_p10):
            return None
        if tail_hit_rate_15pct is None:
            tail_score = (0.42 * float(tail_hit_rate)) + (0.18 * clip(float(tail_median) / 0.25, 0.0, 1.0))
        else:
            tail_score = (0.28 * float(tail_hit_rate_15pct)) + (0.18 * float(tail_hit_rate)) + (0.14 * clip(float(tail_median) / 0.25, 0.0, 1.0))
        t1_score = (0.18 * clip((float(next_open_return) + 0.05) / 0.10, 0.0, 1.0)) + (0.14 * clip((float(next_open_to_close_return) + 0.05) / 0.10, 0.0, 1.0)) + (0.10 * float(next_close_positive_rate))
        downside_penalty = 0.20 * clip(abs(float(downside_p10)) / 0.06, 0.0, 1.0)
        return (tail_score + t1_score - downside_penalty) * (0.35 + (0.65 * sample_weight))
    return None


def check_guardrails(
    metrics: dict[str, float | None],
    guardrails: dict[str, GuardrailSpec],
) -> list[str]:
    """Return names of guardrail constraints that are violated.

    A guardrail maps a metric key to either:
    - a legacy minimum acceptable value, or
    - a dict with ``min`` and/or ``max`` bounds and an optional ``skip_if_null``
      flag (bool, default False).

    A violation occurs when the metric is absent (None), below the minimum, or
    above the maximum.  When ``skip_if_null`` is True on a dict spec and the
    metric evaluates to None, the guardrail is skipped (not violated).  This is
    intended for governance metrics (e.g. theme-exposure) that are legitimately
    unavailable in sparse-window replays.

    Args:
        metrics: Evaluated metrics dict from the evaluator.
        guardrails: Mapping of metric name → legacy minimum float value or a
            bound dict with ``min`` and/or ``max`` values.  Dict specs may also
            include ``skip_if_null: true`` to suppress violations when the
            metric is None.

    Returns:
        List of violated guardrail names (empty when all pass).
    """

    def _normalize_guardrail_bounds(spec: GuardrailSpec) -> dict[str, float]:
        if isinstance(spec, dict):
            bounds: dict[str, float] = {}
            if spec.get("min") is not None:
                bounds["min"] = float(spec["min"])  # type: ignore[arg-type]
            if spec.get("max") is not None:
                bounds["max"] = float(spec["max"])  # type: ignore[arg-type]
            if not bounds:
                raise ValueError("guardrail dict must contain min and/or max")
            return bounds
        return {"min": float(spec)}

    bundle = build_canonical_btst_evaluation_bundle(metrics)
    violations: list[str] = []
    for key, spec in guardrails.items():
        skip_if_null = isinstance(spec, dict) and bool(spec.get("skip_if_null", False))
        value = bundle.lookup(key)
        if value is None and key not in bundle.objective_metrics and key not in bundle.guardrail_metrics and key not in bundle.context_metrics:
            value = coerce_numeric_metric_value(metrics.get(key))
        bounds = _normalize_guardrail_bounds(spec)
        if value is None:
            if not skip_if_null:
                violations.append(key)
            continue
        if ("min" in bounds and value < bounds["min"]) or ("max" in bounds and value > bounds["max"]):
            violations.append(key)
    return violations


def _load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"completed_trials": []}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        # R88 drain (BH-017 family): checkpoint 可能因运行中断 / 磁盘错误 / 部分写入而损坏
        # (_save_checkpoint 非原子写)。此前裸 json.load 会让整个 --param-search
        # JSONDecodeError 崩溃, 数小时已完成 trials 全部需要重跑。现在回退空 checkpoint
        # 让搜索继续, 并发 warning 诊断让用户知情。
        _logger.warning("param_search: 损坏的 checkpoint %s (运行中断/部分写入?): %s; 回退空 checkpoint", path, exc)
        return {"completed_trials": []}


def _save_checkpoint(path: Path, data: dict[str, Any]) -> None:
    """Atomically write *data* to *path*.

    R93 family drain (write-side companion to R88 read-side fallback): the
    previous plain ``open(path, "w") + json.dump`` could leave a truncated
    checkpoint if the process was interrupted mid-write (SIGKILL / OOM /
    disk-full / Ctrl-C during a long ``--param-search`` run). The next run
    would then hit the R88 ``_load_checkpoint`` corrupt-fallback path and
    silently lose all completed trials — even though the data was
    successfully computed.

    Atomic write via temp-file + ``os.replace`` (POSIX atomic on the same
    mount point) guarantees the canonical path always holds either the
    previous valid checkpoint or the complete new one — never a partial
    write. Matches the established pattern in
    ``backtesting/engine_checkpoint_helpers.write_checkpoint`` (C2-BH1) and
    ``screening/candidate_pool_persistence_helpers._atomic_write_json`` (R93).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = str(path.parent)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=tmp_dir, delete=False, suffix=".tmp") as tmp:
        json.dump(data, tmp, indent=2, default=str, ensure_ascii=False)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = tmp.name
    try:
        os.replace(tmp_path, path)
    except OSError:
        # If the atomic rename fails (extremely rare on same mount point),
        # clean up the temp file so it cannot accumulate; re-raise so the
        # caller knows the checkpoint was not persisted (and the canonical
        # path still holds the prior valid state).
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _trial_key(params: dict[str, Any]) -> str:
    return json.dumps(params, sort_keys=True, default=str)


def run_param_search(
    *,
    space: ParamSpace,
    objective: SearchObjective = SearchObjective.COMPOSITE,
    evaluator: Callable[[dict[str, Any]], dict[str, float | None]],
    checkpoint_path: str | Path | None = None,
    guardrails: dict[str, GuardrailSpec] | None = None,
) -> SearchReport:
    """Run grid search over profile parameters.

    Args:
        space: Parameter grid definition.
        objective: Optimization objective.
        evaluator: Callable that takes a params dict and returns metrics dict
                   with keys like sharpe_ratio, sortino_ratio, max_drawdown.
        checkpoint_path: Optional path for checkpointing completed trials.
        guardrails: Optional mapping of metric name → bound spec. Legacy float
            values act as minimum floors; dict specs may define ``min`` and/or
            ``max``. Trials that violate any guardrail are ranked after all
            passing trials regardless of their objective score. Use this to
            enforce hard floors/caps on win rate, downside tail, exposure, or
            other protected metrics so the search never silently promotes a
            candidate that regresses on quality gates.

    Returns:
        SearchReport with ranked results.  Guardrail-failing trials appear at
        the end of ``report.results``; ``report.best_params`` reflects only the
        top-ranked passing trial (or the overall top trial when all fail).
    """
    combos = space.combinations()
    report = SearchReport(
        objective=objective,
        total_trials=len(combos),
    )

    completed_map: dict[str, TrialResult] = {}
    cp_path = Path(checkpoint_path) if checkpoint_path else None

    if cp_path:
        cp_data = _load_checkpoint(cp_path)
        for trial_data in cp_data.get("completed_trials", []):
            raw_failed = trial_data.get("failed_guardrails") or []
            tr = TrialResult(
                trial_index=trial_data["trial_index"],
                params=trial_data["params"],
                metrics=trial_data["metrics"],
                window_count=trial_data.get("window_count", 0),
                score=trial_data.get("score"),
                failed_guardrails=tuple(raw_failed),
            )
            completed_map[_trial_key(tr.params)] = tr

    for i, params in enumerate(combos):
        key = _trial_key(params)
        if key in completed_map:
            report.results.append(completed_map[key])
            report.completed_trials += 1
            continue

        _logger.info("Trial %d/%d: %s", i + 1, len(combos), _params_summary(params))
        metrics = evaluator(params)
        score = compute_objective_score(metrics, objective)
        violations = check_guardrails(metrics, guardrails) if guardrails else []

        result = TrialResult(
            trial_index=i,
            params=params,
            metrics=metrics,
            window_count=metrics.get("window_count", 1),
            score=score,
            failed_guardrails=tuple(violations),
        )
        report.results.append(result)
        report.completed_trials += 1

        if cp_path:
            completed_map[key] = result
            _save_checkpoint(
                cp_path,
                {
                    "completed_trials": [
                        {
                            "trial_index": r.trial_index,
                            "params": r.params,
                            "metrics": r.metrics,
                            "window_count": r.window_count,
                            "score": r.score,
                            "failed_guardrails": list(r.failed_guardrails),
                        }
                        for r in completed_map.values()
                    ]
                },
            )

    # Guardrail-failing trials are always ranked after passing ones regardless
    # of their objective score.  Within each tier, rank by score descending.
    ranked = sorted(
        report.results,
        key=lambda r: (bool(r.failed_guardrails), r.score is None, -(r.score or 0)),
    )
    report.results = ranked
    # best_params and best_score reflect the top passing trial, falling back to
    # the overall top only when every trial failed guardrails.
    top = next((r for r in ranked if not r.failed_guardrails), None) or (ranked[0] if ranked else None)
    if top and top.score is not None:
        report.best_params = top.params
        report.best_score = top.score

    # Finalize the report: capture the generation timestamp once, at return, so a
    # saved markdown/json report self-documents when the run completed.
    report.generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return report


def _params_summary(params: dict[str, Any]) -> str:
    parts = [f"{k}={v}" for k, v in sorted(params.items())]
    return " ".join(parts)


def format_search_report(report: SearchReport) -> str:
    lines: list[str] = []
    lines.append("# Parameter Search Report")
    lines.append("")
    if report.generated_at:
        lines.append(f"Generated at: **{report.generated_at}** (UTC ISO-8601)")
        lines.append("")
    lines.append(f"Objective: **{report.objective.value}**")
    lines.append(f"Trials completed: {report.completed_trials}/{report.total_trials}")
    if report.best_score is not None:
        lines.append(f"Best score: **{report.best_score:.4f}**")
    lines.append("")

    if report.best_params:
        lines.append("## Best Parameters")
        lines.append("")
        for k, v in sorted(report.best_params.items()):
            lines.append(f"- `{k}`: {v}")
        lines.append("")

    failing = [r for r in report.results if r.failed_guardrails]
    if failing:
        lines.append(f"Guardrail violations: **{len(failing)}** trial(s) ranked last due to failed guardrails")
        lines.append("")

    lines.append("## Top 10 Trials")
    lines.append("")
    param_keys = sorted(report.results[0].params.keys()) if report.results else []
    header_extra = " | Guardrail violations" if any(r.failed_guardrails for r in report.results) else ""
    lines.append("| Rank | Score | " + " | ".join(param_keys) + header_extra + " |")
    lines.append("| --- | --- | " + " | ".join(["---"] * len(param_keys)) + (" | ---" if header_extra else "") + " |")
    for rank, result in enumerate(report.results[:10], 1):
        score_str = f"{result.score:.4f}" if result.score is not None else "N/A"
        param_values = [str(result.params.get(k, "")) for k in param_keys]
        guardrail_col = (" | " + ", ".join(result.failed_guardrails)) if header_extra else ""
        lines.append(f"| {rank} | {score_str} | " + " | ".join(param_values) + guardrail_col + " |")
    lines.append("")

    return "\n".join(lines)


def _write_report_file(text: str, output_path: str | Path | None, default_name: str) -> Path:
    """Write report text to disk with explicit UTF-8 encoding.

    Shared by markdown and JSON report writers. Explicit encoding avoids the locale
    default (cp1252/gbk on Windows) raising UnicodeEncodeError on Chinese A-share
    labels in param values.
    """
    path = Path(output_path) if output_path else Path("data/reports") / default_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def save_search_report(report: SearchReport, output_path: str | Path | None = None) -> Path:
    return _write_report_file(format_search_report(report), output_path, "param_search_report.md")


def save_search_payload(report: SearchReport, output_path: str | Path | None = None) -> Path:
    payload = {
        "objective": report.objective.value,
        "total_trials": report.total_trials,
        "completed_trials": report.completed_trials,
        "generated_at": report.generated_at,
        "best_score": report.best_score,
        "best_params": report.best_params,
        "results": [
            {
                "trial_index": r.trial_index,
                "params": r.params,
                "metrics": r.metrics,
                "window_count": r.window_count,
                "score": r.score,
                "failed_guardrails": list(r.failed_guardrails),
            }
            for r in report.results
        ],
    }
    # ensure_ascii=False writes Chinese A-share param labels as raw UTF-8 chars,
    # not \uXXXX escapes, for human-readable reports.
    return _write_report_file(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        output_path,
        "param_search_report.json",
    )
