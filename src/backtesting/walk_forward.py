from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from dateutil.relativedelta import relativedelta

from src.tools.tushare_api import _cached_tushare_dataframe_call, _get_pro

from .evaluation_bundle import BTST_QUALITY_FLOORS, build_btst_quality_floor_blockers, build_canonical_btst_evaluation_bundle
from .promotion_gate import build_promotion_gate_summary
from .types import PerformanceMetrics


class WindowMode(StrEnum):
    ROLLING = "rolling"
    EXPANDING = "expanding"


WALK_FORWARD_PRESETS: dict[str, dict[str, int]] = {
    # fast: 1-month train, 1-month test, 1-month step.  No trading-day cap so the
    # preset works without a live Tushare connection.  Use --max-test-trading-days
    # explicitly if you need day-level truncation on top of the fast window shape.
    "fast": {"train_months": 1, "test_months": 1, "step_months": 1},
    "standard": {"train_months": 2, "test_months": 1, "step_months": 1},
    "extended": {"train_months": 2, "test_months": 2, "step_months": 1},
    "seasonal": {"train_months": 3, "test_months": 3, "step_months": 3},
}
ROLLOUT_MAX_NON_POSITIVE_SHARPE_STREAK = 2
ROLLOUT_WORST_MAX_DRAWDOWN_FLOOR = -12.0
MIN_TEST_TRADING_DAYS_FOR_ROLLOUT = 5

RUNNER_TAIL_HIT_IMPROVEMENT_MIN = 0.05
RUNNER_TAIL_HIT_ABSOLUTE_MIN = 0.12
RUNNER_T1_WIN_RATE_REGRESSION_FLOOR = -0.04
RUNNER_DOWNSIDE_REGRESSION_FLOOR = -0.015
RUNNER_COMPOSITE_SCORE_QUALITY_FLOOR = 0.50
RUNNER_ESCAPE_RATE_MIN = 0.03


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: str
    train_end: str
    test_start: str
    test_end: str


@dataclass(frozen=True)
class WalkForwardResult:
    window: WalkForwardWindow
    metrics: PerformanceMetrics


def build_walk_forward_windows(
    start_date: str,
    end_date: str,
    *,
    train_months: int = 2,
    test_months: int = 1,
    step_months: int = 1,
    max_test_trading_days: int | None = None,
    window_mode: WindowMode = WindowMode.ROLLING,
) -> list[WalkForwardWindow]:
    if train_months <= 0 or test_months <= 0 or step_months <= 0:
        raise ValueError("walk-forward windows require positive month lengths")
    if max_test_trading_days is not None and max_test_trading_days <= 0:
        raise ValueError("max_test_trading_days must be positive when provided")

    overall_start = datetime.strptime(start_date, "%Y-%m-%d")
    overall_end = datetime.strptime(end_date, "%Y-%m-%d")
    windows: list[WalkForwardWindow] = []

    cursor = overall_start
    iteration = 0
    while True:
        if window_mode == WindowMode.EXPANDING:
            train_start = overall_start
            train_duration = train_months + iteration * step_months
            train_end = train_start + relativedelta(months=train_duration) - relativedelta(days=1)
        else:
            train_start = cursor
            train_end = train_start + relativedelta(months=train_months) - relativedelta(days=1)

        test_start = train_end + relativedelta(days=1)
        full_test_end = test_start + relativedelta(months=test_months) - relativedelta(days=1)
        if full_test_end > overall_end:
            break
        test_end = _truncate_test_end_by_trading_days(test_start, full_test_end, max_test_trading_days)
        windows.append(
            WalkForwardWindow(
                train_start=train_start.strftime("%Y-%m-%d"),
                train_end=train_end.strftime("%Y-%m-%d"),
                test_start=test_start.strftime("%Y-%m-%d"),
                test_end=test_end.strftime("%Y-%m-%d"),
            )
        )
        cursor = cursor + relativedelta(months=step_months)
        iteration += 1

    return windows


def _truncate_test_end_by_trading_days(test_start: datetime, test_end: datetime, max_test_trading_days: int | None) -> datetime:
    if max_test_trading_days is None:
        return test_end

    pro = _get_pro()
    if pro is None:
        raise RuntimeError("Tushare trade calendar is required when max_test_trading_days is set")

    df = _cached_tushare_dataframe_call(
        pro,
        "trade_cal",
        exchange="",
        start_date=test_start.strftime("%Y%m%d"),
        end_date=test_end.strftime("%Y%m%d"),
        is_open=1,
        fields="cal_date,is_open",
    )
    if df is None or df.empty:
        raise RuntimeError("No open trading days found in requested walk-forward test window")

    open_dates = sorted(str(value) for value in df["cal_date"].tolist())
    capped_index = min(max_test_trading_days, len(open_dates)) - 1
    return datetime.strptime(open_dates[capped_index], "%Y%m%d")


def _estimate_test_trading_days(test_start: str, test_end: str) -> int:
    start = datetime.strptime(test_start, "%Y-%m-%d")
    end = datetime.strptime(test_end, "%Y-%m-%d")
    if end < start:
        return 0

    trading_days = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            trading_days += 1
        current += timedelta(days=1)
    return trading_days


def _resolve_calendar_test_trading_days(test_start: str, test_end: str) -> int | None:
    pro = _get_pro()
    if pro is None:
        return None

    df = _cached_tushare_dataframe_call(
        pro,
        "trade_cal",
        exchange="",
        start_date=test_start.replace("-", ""),
        end_date=test_end.replace("-", ""),
        is_open=1,
        fields="cal_date,is_open",
    )
    if df is None or df.empty:
        return None
    return len(df)


def _resolve_test_trading_days(result: WalkForwardResult) -> int:
    explicit_test_trading_days = result.metrics.get("test_trading_days")
    if explicit_test_trading_days is not None:
        return int(explicit_test_trading_days)
    return _estimate_test_trading_days(result.window.test_start, result.window.test_end)


def run_walk_forward(
    windows: Sequence[WalkForwardWindow],
    engine_factory: Callable[[WalkForwardWindow], object],
) -> list[WalkForwardResult]:
    results: list[WalkForwardResult] = []
    for window in windows:
        engine = engine_factory(window)
        metrics = engine.run_backtest()
        if metrics.get("test_trading_days") is None:
            calendar_test_trading_days = _resolve_calendar_test_trading_days(window.test_start, window.test_end)
            if calendar_test_trading_days is not None:
                metrics = {
                    **metrics,
                    "test_trading_days": calendar_test_trading_days,
                }
        results.append(WalkForwardResult(window=window, metrics=metrics))
    return results


def summarize_walk_forward(results: Sequence[WalkForwardResult]) -> dict[str, Any]:
    if not results:
        base_summary: dict[str, Any] = {
            "window_count": 0,
            "avg_sharpe": None,
            "avg_sortino": None,
            "avg_max_drawdown": None,
            "positive_sharpe_window_count": 0,
            "negative_sharpe_window_count": 0,
            "zero_sharpe_window_count": 0,
            "non_positive_sharpe_window_count": 0,
            "positive_sharpe_window_ratio": None,
            "worst_sharpe": None,
            "worst_max_drawdown": None,
            "max_non_positive_sharpe_streak": 0,
            "rollout_ready": False,
            "rollout_blockers": ["no_walk_forward_windows"],
        }
        runner_verdict, runner_verdict_detail = classify_runner_rollout_verdict(runner_summary=base_summary)
        return {
            **base_summary,
            **build_promotion_gate_summary(walk_forward_summary=base_summary),
            "runner_rollout_verdict": runner_verdict,
            "runner_rollout_verdict_detail": runner_verdict_detail,
        }

    sharpe_sequence = [item.metrics.get("sharpe_ratio") for item in results]
    sharpe_values = [item.metrics["sharpe_ratio"] for item in results if item.metrics.get("sharpe_ratio") is not None]
    sortino_values = [item.metrics["sortino_ratio"] for item in results if item.metrics.get("sortino_ratio") is not None]
    max_drawdown_values = [item.metrics["max_drawdown"] for item in results if item.metrics.get("max_drawdown") is not None]
    test_trading_days = [_resolve_test_trading_days(item) for item in results]
    btst_metric_keys = tuple(key for key in BTST_QUALITY_FLOORS if key != "window_coverage")
    btst_metric_values: dict[str, list[float]] = {key: [] for key in btst_metric_keys}
    execution_metric_keys = (
        "projected_theme_exposure",
        "incremental_theme_exposure",
        "liquidity_capacity_raw_100",
        "crowding_risk_raw_100",
        "gap_risk_raw_100",
    )
    execution_metric_values: dict[str, list[float]] = {key: [] for key in execution_metric_keys}
    btst_complete_window_count = 0

    def _average(values: list[float | None]) -> float | None:
        clean_values = [value for value in values if value is not None]
        if not clean_values:
            return None
        return sum(clean_values) / len(clean_values)

    for item in results:
        bundle = build_canonical_btst_evaluation_bundle(item.metrics)
        window_has_complete_btst_quality = True
        for metric_key in btst_metric_keys:
            value = bundle.lookup(metric_key)
            if value is None:
                window_has_complete_btst_quality = False
                continue
            btst_metric_values[metric_key].append(float(value))
        for metric_key in execution_metric_keys:
            value = bundle.lookup(metric_key)
            if value is not None:
                execution_metric_values[metric_key].append(float(value))
        if window_has_complete_btst_quality:
            btst_complete_window_count += 1

    positive_sharpe_window_count = sum(1 for value in sharpe_values if float(value or 0.0) > 0.0)
    negative_sharpe_window_count = sum(1 for value in sharpe_values if float(value or 0.0) < 0.0)
    zero_sharpe_window_count = sum(1 for value in sharpe_values if float(value or 0.0) == 0.0)
    non_positive_sharpe_window_count = sum(1 for value in sharpe_values if float(value or 0.0) <= 0.0)
    positive_sharpe_window_ratio = (positive_sharpe_window_count / len(sharpe_values)) if sharpe_values else None
    max_non_positive_sharpe_streak = 0
    current_non_positive_streak = 0
    for value in sharpe_sequence:
        if value is None:
            current_non_positive_streak = 0
        elif float(value or 0.0) <= 0.0:
            current_non_positive_streak += 1
            max_non_positive_sharpe_streak = max(max_non_positive_sharpe_streak, current_non_positive_streak)
        else:
            current_non_positive_streak = 0

    worst_max_drawdown = min(max_drawdown_values) if max_drawdown_values else None
    rollout_blockers: list[str] = []
    if len(sharpe_values) != len(results):
        rollout_blockers.append("missing_required_sharpe_data")
    if non_positive_sharpe_window_count > positive_sharpe_window_count:
        rollout_blockers.append("majority_non_positive_sharpe_windows")
    if max_non_positive_sharpe_streak >= ROLLOUT_MAX_NON_POSITIVE_SHARPE_STREAK:
        rollout_blockers.append("non_positive_sharpe_streak_exceeded")
    if worst_max_drawdown is not None and worst_max_drawdown <= ROLLOUT_WORST_MAX_DRAWDOWN_FLOOR:
        rollout_blockers.append("worst_drawdown_breach")
    if test_trading_days and min(test_trading_days) < MIN_TEST_TRADING_DAYS_FOR_ROLLOUT:
        rollout_blockers.append("test_window_too_short")

    # Runner tail hit floor check (only if runner metrics are present)
    runner_tail_hit_values = [item.metrics.get("max_future_high_return_2_5d_hit_rate_at_20pct") for item in results if item.metrics.get("max_future_high_return_2_5d_hit_rate_at_20pct") is not None]
    avg_runner_tail_hit_rate = _average(runner_tail_hit_values)
    if runner_tail_hit_values:
        if avg_runner_tail_hit_rate is None or avg_runner_tail_hit_rate < 0.10:
            rollout_blockers.append("btst_runner_tail_hit_floor_breach")
    runner_capture_count_values = [item.metrics.get("runner_capture_count") for item in results if item.metrics.get("runner_capture_count") is not None]
    total_runner_capture_count = int(sum(float(v) for v in runner_capture_count_values)) if runner_capture_count_values else None
    runner_escape_rate_values = [item.metrics.get("runner_escape_rate") for item in results if item.metrics.get("runner_escape_rate") is not None]
    avg_runner_escape_rate = _average(runner_escape_rate_values) if runner_escape_rate_values else None
    composite_score_escaped_values = [item.metrics.get("avg_composite_score_escaped") for item in results if item.metrics.get("avg_composite_score_escaped") is not None]
    avg_composite_score_escaped = _average(composite_score_escaped_values) if composite_score_escaped_values else None

    btst_quality_summary: dict[str, float | None] = {
        metric_key: _average(btst_metric_values[metric_key]) for metric_key in btst_metric_keys
    }
    btst_quality_summary["window_coverage"] = (
        float(btst_complete_window_count) / float(len(results)) if btst_complete_window_count > 0 else None
    )
    execution_summary: dict[str, float | None] = {
        metric_key: _average(execution_metric_values[metric_key]) for metric_key in execution_metric_keys
    }
    if any(value is not None for value in btst_quality_summary.values()):
        rollout_blockers.extend(build_btst_quality_floor_blockers(btst_quality_summary))

    base_summary: dict[str, Any] = {
        "window_count": len(results),
        "avg_sharpe": _average(sharpe_values),
        "avg_sortino": _average(sortino_values),
        "avg_max_drawdown": _average(max_drawdown_values),
        "positive_sharpe_window_count": positive_sharpe_window_count,
        "negative_sharpe_window_count": negative_sharpe_window_count,
        "zero_sharpe_window_count": zero_sharpe_window_count,
        "non_positive_sharpe_window_count": non_positive_sharpe_window_count,
        "positive_sharpe_window_ratio": positive_sharpe_window_ratio,
        "worst_sharpe": min(sharpe_values) if sharpe_values else None,
        "worst_max_drawdown": worst_max_drawdown,
        "max_non_positive_sharpe_streak": max_non_positive_sharpe_streak,
        **btst_quality_summary,
        **execution_summary,
        "avg_runner_tail_hit_rate": avg_runner_tail_hit_rate,
        "total_runner_capture_count": total_runner_capture_count,
        "avg_runner_escape_rate": avg_runner_escape_rate,
        "avg_composite_score_escaped": avg_composite_score_escaped,
        "rollout_ready": not rollout_blockers,
        "rollout_blockers": rollout_blockers,
    }
    runner_verdict, runner_verdict_detail = classify_runner_rollout_verdict(runner_summary=base_summary)
    return {
        **base_summary,
        **build_promotion_gate_summary(walk_forward_summary=base_summary),
        "runner_rollout_verdict": runner_verdict,
        "runner_rollout_verdict_detail": runner_verdict_detail,
    }


def classify_runner_rollout_verdict(
    runner_summary: dict,
    baseline_summary: dict | None = None,
) -> tuple[str, dict]:
    """Classify the runner rollout verdict for a walk-forward summary.

    Four possible verdict labels:
    - ``promotable_runner_profile``: tail hit meets the absolute floor AND either
      no baseline is provided or shows sufficient improvement without T+1 or
      downside regression.
    - ``tail_hit_better_but_t1_risky``: tail hit improves over baseline but the
      T+1 win rate or downside regresses beyond the tolerance floors.
    - ``coverage_only_not_runner_better``: coverage/T+1 quality acceptable but
      runner tail hit rate does not improve enough over baseline.
    - ``keep_precision_baseline``: runner tail hit is below the absolute floor,
      regardless of baseline comparison.

    Args:
        runner_summary: Summary dict containing ``avg_runner_tail_hit_rate``,
            ``next_close_positive_rate``, and ``downside_p10`` values.
        baseline_summary: Optional baseline summary dict with the same keys.

    Returns:
        A tuple of (verdict_label, detail_dict).
    """
    tail_hit = float(runner_summary.get("avg_runner_tail_hit_rate") or 0.0)
    t1_win_rate = float(runner_summary.get("next_close_positive_rate") or 0.0)
    downside = float(runner_summary.get("downside_p10") or 0.0)

    detail: dict = {
        "tail_hit": tail_hit,
        "t1_win_rate": t1_win_rate,
        "downside": downside,
        "baseline_tail_hit": None,
        "tail_hit_delta": None,
        "t1_win_rate_delta": None,
        "downside_delta": None,
        "avg_composite_score_escaped": runner_summary.get("avg_composite_score_escaped"),
        "avg_runner_escape_rate": runner_summary.get("avg_runner_escape_rate"),
    }

    if baseline_summary is not None:
        baseline_tail_hit = float(baseline_summary.get("avg_runner_tail_hit_rate") or 0.0)
        baseline_t1 = float(baseline_summary.get("next_close_positive_rate") or 0.0)
        baseline_downside = float(baseline_summary.get("downside_p10") or 0.0)
        detail["baseline_tail_hit"] = baseline_tail_hit
        detail["tail_hit_delta"] = tail_hit - baseline_tail_hit
        detail["t1_win_rate_delta"] = t1_win_rate - baseline_t1
        detail["downside_delta"] = downside - baseline_downside
    else:
        baseline_tail_hit = None

    # Absolute floor: if tail hit below minimum, always keep precision baseline
    if tail_hit < RUNNER_TAIL_HIT_ABSOLUTE_MIN:
        detail["verdict_reason"] = "tail_hit_below_absolute_min"
        return "keep_precision_baseline", detail

    # Absolute floor: if escape rate is below minimum, the profile can't capture
    # runners in production regardless of signal quality — always keep precision baseline.
    escape_rate = runner_summary.get("avg_runner_escape_rate")
    if escape_rate is not None and float(escape_rate) < RUNNER_ESCAPE_RATE_MIN:
        detail["verdict_reason"] = "runner_escape_rate_below_floor"
        return "keep_precision_baseline", detail

    if baseline_tail_hit is not None:
        improvement = tail_hit - baseline_tail_hit
        t1_regression = (t1_win_rate - float(baseline_summary.get("next_close_positive_rate") or 0.0))  # type: ignore[arg-type]
        downside_regression = downside - float(baseline_summary.get("downside_p10") or 0.0)  # type: ignore[arg-type]

        # Check T+1 or downside regression
        t1_risky = t1_regression < RUNNER_T1_WIN_RATE_REGRESSION_FLOOR
        downside_risky = downside_regression < RUNNER_DOWNSIDE_REGRESSION_FLOOR

        if improvement >= RUNNER_TAIL_HIT_IMPROVEMENT_MIN and (t1_risky or downside_risky):
            detail["verdict_reason"] = "t1_or_downside_regression"
            return "tail_hit_better_but_t1_risky", detail

        if improvement < RUNNER_TAIL_HIT_IMPROVEMENT_MIN:
            detail["verdict_reason"] = "insufficient_tail_hit_improvement"
            return "coverage_only_not_runner_better", detail

    detail["verdict_reason"] = "meets_all_runner_criteria"
    # Composite quality gate: if avg score of escaped runners is below floor, downgrade.
    # This check is optional — only applies when avg_composite_score_escaped is available.
    composite_score_escaped = runner_summary.get("avg_composite_score_escaped")
    if composite_score_escaped is not None and float(composite_score_escaped) < RUNNER_COMPOSITE_SCORE_QUALITY_FLOOR:
        detail["verdict_reason"] = "low_runner_composite_quality"
        return "tail_hit_better_but_t1_risky", detail
    return "promotable_runner_profile", detail
