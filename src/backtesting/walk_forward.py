from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Sequence

from dateutil.relativedelta import relativedelta

from src.tools.tushare_api import _cached_tushare_dataframe_call, _get_pro

from .types import PerformanceMetrics


class WindowMode(str, Enum):
    ROLLING = "rolling"
    EXPANDING = "expanding"


WALK_FORWARD_PRESETS: dict[str, dict[str, int]] = {
    "fast": {"train_months": 1, "test_months": 1, "step_months": 1, "max_test_trading_days": 10},
    "standard": {"train_months": 2, "test_months": 1, "step_months": 1},
    "extended": {"train_months": 2, "test_months": 2, "step_months": 1},
    "seasonal": {"train_months": 3, "test_months": 3, "step_months": 3},
}


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


def run_walk_forward(
    windows: Sequence[WalkForwardWindow],
    engine_factory: Callable[[WalkForwardWindow], object],
) -> list[WalkForwardResult]:
    results: list[WalkForwardResult] = []
    for window in windows:
        engine = engine_factory(window)
        metrics = engine.run_backtest()
        results.append(WalkForwardResult(window=window, metrics=metrics))
    return results


def summarize_walk_forward(results: Sequence[WalkForwardResult]) -> dict[str, float | int | None]:
    if not results:
        return {"window_count": 0, "avg_sharpe": None, "avg_sortino": None, "avg_max_drawdown": None}

    sharpe_values = [item.metrics["sharpe_ratio"] for item in results if item.metrics.get("sharpe_ratio") is not None]
    sortino_values = [item.metrics["sortino_ratio"] for item in results if item.metrics.get("sortino_ratio") is not None]
    max_drawdown_values = [item.metrics["max_drawdown"] for item in results if item.metrics.get("max_drawdown") is not None]

    def _average(values: list[float | None]) -> float | None:
        clean_values = [value for value in values if value is not None]
        if not clean_values:
            return None
        return sum(clean_values) / len(clean_values)

    return {
        "window_count": len(results),
        "avg_sharpe": _average(sharpe_values),
        "avg_sortino": _average(sortino_values),
        "avg_max_drawdown": _average(max_drawdown_values),
    }
