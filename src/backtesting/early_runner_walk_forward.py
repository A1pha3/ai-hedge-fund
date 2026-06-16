from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from itertools import product
from statistics import mean
from typing import Any

import numpy as np

from src.backtesting.walk_forward import (
    build_walk_forward_windows,
    WALK_FORWARD_PRESETS,
    WindowMode,
)


def _safe_float(value: Any) -> float | None:
    """Return a float when parsing succeeds, otherwise ``None``."""
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any, default: float = 0.0) -> float:
    """Convert mixed inputs into float while preserving a caller-provided default."""
    parsed = _safe_float(value)
    return default if parsed is None else float(parsed)


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    """Return a rounded ratio or ``None`` when the denominator is not positive."""
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def _round_or_none(value: float | None) -> float | None:
    """Round numeric outputs while leaving ``None`` untouched."""
    if value is None:
        return None
    return round(float(value), 4)


def _distribution_p10(values: list[float]) -> float | None:
    """Return the 10th percentile (p10) used by the legacy report.

    ALPHA-006: the old ``index = max(0, floor((len(ordered) - 1) * 0.10))``
    discrete index was always 0 for N<11, so p10 silently returned the
    *minimum* (worst drawdown) instead of a real p10 — overstating tail risk
    on every small walk-forward window. Switched to numpy's linear-interpolated
    percentile, which matches the rest of the analytics layer and gives a
    meaningful tail estimate even for small N.
    """
    if not values:
        return None
    return round(float(np.percentile(np.asarray(values, dtype=float), 10)), 4)


def _month_key(trade_date: str) -> str:
    """Collapse a trade date into the current month-bucket key."""
    compact = "".join(char for char in str(trade_date or "") if char.isdigit())
    return compact[:6] if len(compact) >= 6 else compact


def _future_hit_15(row: dict[str, Any]) -> bool:
    """Return the existing 15 percent future-hit label used in the report."""
    return bool(row.get("future_high_hit_15pct_2_5d") is True)


def _filter_rows_for_param_set(rows: list[dict[str, Any]], param_set: dict[str, float]) -> list[dict[str, Any]]:
    """Apply the early-runner parameter set to a candidate row list."""
    return [
        row
        for row in rows
        if _as_float(row.get("ret_5d"), 0.0) <= float(param_set["ret_5d_max"])
        and _as_float(row.get("ret_10d"), 0.0) <= float(param_set["ret_10d_max"])
        and _as_float(row.get("next_open_return"), 0.0) <= float(param_set["gap_max"])
        and _as_float(row.get("close_strength"), 0.0) <= float(param_set["close_strength_max"])
        and _as_float(row.get("volume_expansion_quality"), 0.0) <= float(param_set["volume_quality_max"])
        and _as_float(row.get("confirm_score"), 0.0) >= float(param_set["confirm_score_min"])
    ]


def _summarize_param_set(rows: list[dict[str, Any]], param_set: dict[str, float]) -> dict[str, Any]:
    """Summarize one parameter set against a row sample."""
    filtered = _filter_rows_for_param_set(rows, param_set)
    after_cost_returns = [float(row.get("next_close_return_after_cost") or 0.0) for row in filtered if row.get("next_close_return_after_cost") is not None]
    drawdowns = [float(row.get("next_low_return") or 0.0) for row in filtered if row.get("next_low_return") is not None]
    # ALPHA-003 fix: split hit_rate into filled-only and all-attempts.
    # The old hit_rate_5d15 used len(filtered) as denominator, which includes
    # unfilled rows (whose future_hit is almost always False). A strategy with
    # 50% unfilled rate and 80% filled hit rate would report 40%, not 80%.
    filled_rows = [row for row in filtered if row.get("entry_status") != "unfilled"]
    return {
        "param_set": dict(param_set),
        "row_count": len(filtered),
        "hit_rate_5d15": _safe_ratio(sum(1 for row in filtered if _future_hit_15(row)), len(filtered)),
        "hit_rate_5d15_on_fills": _safe_ratio(sum(1 for row in filled_rows if _future_hit_15(row)), len(filled_rows)),
        "after_cost_expectancy": _round_or_none(mean(after_cost_returns)) if after_cost_returns else None,
        "unfilled_rate": _safe_ratio(sum(1 for row in filtered if row.get("entry_status") == "unfilled"), len(filtered)),
        "drawdown_p10": _distribution_p10(drawdowns),
    }


def _ranking_key(summary: dict[str, Any]) -> tuple[float, float, float, int]:
    """Build the current ranking key for selecting a best parameter set."""
    expectancy = summary.get("after_cost_expectancy")
    hit_rate = summary.get("hit_rate_5d15")
    unfilled = summary.get("unfilled_rate")
    row_count = summary.get("row_count")
    return (
        float(expectancy) if expectancy is not None else -999.0,
        float(hit_rate) if hit_rate is not None else -999.0,
        -(float(unfilled) if unfilled is not None else 999.0),
        int(row_count) if row_count is not None else 0,
    )


def _build_shared_windows(candidate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build rolling and expanding walk-forward windows from available trade dates."""
    trade_dates = sorted({str(row.get("trade_date") or "") for row in candidate_rows if str(row.get("trade_date") or "").strip()})
    if len(trade_dates) < 3:
        return []
    overall_start = min(datetime.strptime(date, "%Y-%m-%d") for date in trade_dates)
    overall_end = max(datetime.strptime(date, "%Y-%m-%d") for date in trade_dates)
    if overall_end <= overall_start:
        return []
    preset = WALK_FORWARD_PRESETS["fast"]
    windows: list[dict[str, Any]] = []
    for mode in [WindowMode.ROLLING, WindowMode.EXPANDING]:
        built = build_walk_forward_windows(
            overall_start.strftime("%Y-%m-%d"),
            overall_end.strftime("%Y-%m-%d"),
            train_months=int(preset["train_months"]),
            test_months=int(preset["test_months"]),
            step_months=int(preset["step_months"]),
            window_mode=mode,
        )
        for window in built:
            windows.append(
                {
                    "window_mode": str(mode),
                    "train_start": window.train_start,
                    "train_end": window.train_end,
                    "test_start": window.test_start,
                    "test_end": window.test_end,
                }
            )
    return windows


def build_early_runner_walk_forward_summary(rows: list[dict[str, Any]], *, walk_forward_grid: dict[str, list[float]]) -> dict[str, Any]:
    """Preserve the current month-grid walk-forward summary behind a dedicated module seam."""
    candidate_rows = [row for row in rows if row.get("bucket") == "early_runner_first_entry"]
    grid_keys = list(walk_forward_grid.keys())
    grid_values = list(walk_forward_grid.values())
    param_sets = [dict(zip(grid_keys, combo)) for combo in product(*grid_values)]
    shared_windows = _build_shared_windows(candidate_rows)

    best_param_set_by_window: dict[str, dict[str, Any]] = {}
    param_counter: Counter[str] = Counter()
    month_oos_pass_count = 0

    if shared_windows:
        iteration_windows = []
        for window in shared_windows:
            test_rows = [
                row
                for row in candidate_rows
                if str(window["test_start"]) <= str(row.get("trade_date") or "") <= str(window["test_end"])
            ]
            if test_rows:
                iteration_windows.append((f"{window['window_mode']}:{window['test_start']}->{window['test_end']}", test_rows, window))
    else:
        by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in candidate_rows:
            by_month[_month_key(str(row.get("trade_date") or ""))].append(row)
        iteration_windows = [(month, month_rows, {"window_mode": "legacy_month_grid", "test_start": month, "test_end": month}) for month, month_rows in sorted(by_month.items())]

    for window_key, month_rows, window_meta in iteration_windows:
        best_summary: dict[str, Any] | None = None
        for param_set in param_sets:
            summary = _summarize_param_set(month_rows, param_set)
            if best_summary is None or _ranking_key(summary) > _ranking_key(best_summary):
                best_summary = summary
        if best_summary is None:
            continue
        best_param_set_by_window[window_key] = {
            **best_summary,
            "window_mode": window_meta["window_mode"],
            "test_start": window_meta["test_start"],
            "test_end": window_meta["test_end"],
        }
        param_counter[json.dumps(best_summary["param_set"], sort_keys=True)] += 1
        if (best_summary.get("after_cost_expectancy") or 0.0) > 0 and (best_summary.get("hit_rate_5d15") or 0.0) >= 0.55:
            month_oos_pass_count += 1

    return {
        "candidate_grid_size": len(param_sets),
        "window_count": len(best_param_set_by_window),
        "shared_window_mode_enabled": bool(shared_windows),
        "best_param_set_by_window": best_param_set_by_window,
        "param_set_frequency": {key: int(value) for key, value in param_counter.items()},
        "median_rank_of_chosen_param": 1 if best_param_set_by_window else None,
        "month_oos_pass_count": month_oos_pass_count,
    }
