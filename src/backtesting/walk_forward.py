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


def summarize_walk_forward(results: Sequence[WalkForwardResult]) -> dict[str, float | int | bool | list[str] | None]:
    if not results:
        base_summary: dict[str, float | int | bool | list[str] | None] = {
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
        return {
            **base_summary,
            **build_promotion_gate_summary(walk_forward_summary=base_summary),
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

    base_summary: dict[str, float | int | bool | list[str] | None] = {
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
        "rollout_ready": not rollout_blockers,
        "rollout_blockers": rollout_blockers,
    }
    return {
        **base_summary,
        **build_promotion_gate_summary(walk_forward_summary=base_summary),
    }
