from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from dateutil.relativedelta import relativedelta

from src.tools.tushare_api import _cached_tushare_dataframe_call, _get_pro

from .evaluation_bundle import BTST_QUALITY_FLOORS, BTST_QUALITY_CAPS, build_btst_quality_floor_blockers, build_btst_quality_cap_blockers, build_canonical_btst_evaluation_bundle
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

# ---------------------------------------------------------------------------
# Task 1 (Round 14): consecutive-window profile stability constants.
# A profile that is non-promotable in too many or too many consecutive windows
# is flagged as "unstable_profile" and receives a stability-penalty blocker in rollout.
# ---------------------------------------------------------------------------
PROFILE_STABILITY_NON_PROMOTABLE_STREAK_THRESHOLD: int = 2  # max consecutive non-promotable windows before "unstable"
PROFILE_STABILITY_NON_PROMOTABLE_FRACTION_THRESHOLD: float = 0.5  # ≥50 % non-promotable windows → unstable

# ---------------------------------------------------------------------------
# Task 2 (Round 14): candidate pool size thresholds for market-regime classification.
# ---------------------------------------------------------------------------
CANDIDATE_POOL_SCARCE_THRESHOLD: int = 20  # pools below this are "scarce market" windows
CANDIDATE_POOL_ABUNDANT_THRESHOLD: int = 100  # pools above this are "abundant market" windows

RUNNER_TAIL_HIT_IMPROVEMENT_MIN = 0.05
RUNNER_TAIL_HIT_ABSOLUTE_MIN = 0.12
RUNNER_T1_WIN_RATE_REGRESSION_FLOOR = -0.04
RUNNER_T2_WIN_RATE_REGRESSION_FLOOR = -0.02
RUNNER_T3_WIN_RATE_REGRESSION_FLOOR = -0.02
# Absolute minimum win rate on T+2 / T+3. A runner that does not clear
# these bars is intrinsically risky regardless of how its baseline compares
# (a 0% T+2 win rate minus a 0% baseline still gives 0.0 regression, but
# the strategy itself is unprofitable on the 2-3 day horizon). These match
# the BTST_QUALITY_FLOORS conventions used elsewhere in the evaluation bundle.
RUNNER_T2_WIN_RATE_ABSOLUTE_MIN = 0.30
RUNNER_T3_WIN_RATE_ABSOLUTE_MIN = 0.30
RUNNER_DOWNSIDE_REGRESSION_FLOOR = -0.015
RUNNER_COMPOSITE_SCORE_QUALITY_FLOOR = 0.50
RUNNER_ESCAPE_RATE_MIN = 0.03
WIN_RATE_FIRST_MIN_POSITIVE_DELTA = 0.005
WIN_RATE_FIRST_MAX_PAYOFF_DEGRADATION = 0.10
WIN_RATE_FIRST_MAX_EXPECTANCY_DEGRADATION = 0.005
WIN_RATE_FIRST_MAX_COVERAGE_DEGRADATION = 0.03

# Task 4 (Round 11): temporal recency decay for walk-forward BTST quality metrics.
# Windows with test_start closer to the reference date (most recent) receive weight ~1.0;
# windows ``WALK_FORWARD_RECENCY_HALF_LIFE_DAYS`` before the reference receive ~0.5;
# the floor ``WALK_FORWARD_RECENCY_DECAY_MIN_FACTOR`` prevents oldest windows from
# being fully discarded.  Consistent with the optimizer's recency decay (Round 9).
WALK_FORWARD_RECENCY_HALF_LIFE_DAYS: int = 90
WALK_FORWARD_RECENCY_DECAY_MIN_FACTOR: float = 0.20


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


def _compute_walk_forward_recency_weight(
    test_start: str,
    reference_date: str,
    half_life_days: int = WALK_FORWARD_RECENCY_HALF_LIFE_DAYS,
) -> float:
    """Return an exponential recency decay weight in [WALK_FORWARD_RECENCY_DECAY_MIN_FACTOR, 1.0].

    Windows with ``test_start`` equal to ``reference_date`` receive weight 1.0; windows that
    are ``half_life_days`` older receive ~0.5; the floor prevents complete discarding of
    old windows.  Mirrors the optimizer's recency decay (Task S, Round 9) for consistency.

    Args:
        test_start: ISO-format ``YYYY-MM-DD`` date of this walk-forward window's test period start.
        reference_date: ISO-format date of the most-recent window (defines the recency anchor).
        half_life_days: Calendar days after which the decay factor reaches approximately 0.5.

    Returns:
        Decay weight in [WALK_FORWARD_RECENCY_DECAY_MIN_FACTOR, 1.0].
    """
    import math as _math
    try:
        start_dt = datetime.strptime(test_start, "%Y-%m-%d")
        ref_dt = datetime.strptime(reference_date, "%Y-%m-%d")
        days_lag = max(0, (ref_dt - start_dt).days)
    except (ValueError, TypeError):
        return 1.0
    decay = _math.exp(-_math.log(2.0) * days_lag / max(1, half_life_days))
    return max(WALK_FORWARD_RECENCY_DECAY_MIN_FACTOR, round(decay, 6))


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


def assess_profile_stability(verdicts: list[tuple[str, dict]]) -> dict[str, Any]:
    """Assess verdict consistency across consecutive walk-forward windows (Task 1, Round 14).

    A profile that flips between promotable and non-promotable verdicts in consecutive windows
    provides a weaker rollout signal than one that is consistently promotable.  This function
    computes a stability score and flags profiles with too many or too many consecutive
    non-promotable verdicts as ``"unstable_profile"``.

    Non-promotable verdict labels (all labels except ``"promotable_runner_profile"``) are:
    - ``"keep_precision_baseline"``
    - ``"coverage_only_not_runner_better"``
    - ``"tail_hit_better_but_t1_risky"``

    A profile is considered **unstable** when either:
    - the maximum consecutive non-promotable streak ≥ :data:`PROFILE_STABILITY_NON_PROMOTABLE_STREAK_THRESHOLD`
    - OR the fraction of non-promotable windows ≥ :data:`PROFILE_STABILITY_NON_PROMOTABLE_FRACTION_THRESHOLD`

    Args:
        verdicts: Ordered list of ``(verdict_label, detail_dict)`` tuples from consecutive
            walk-forward windows.  Must be in chronological order (oldest first).

    Returns:
        A dict with the following keys:

        - ``stability_score`` (float | None): fraction of promotable windows in ``[0.0, 1.0]``.
          ``None`` when *verdicts* is empty.
        - ``max_consecutive_non_promotable`` (int): longest run of consecutive non-promotable
          verdicts.
        - ``non_promotable_count`` (int): total number of non-promotable windows.
        - ``total_window_count`` (int): total number of windows evaluated.
        - ``stability_verdict`` (str): ``"stable_profile"``, ``"unstable_profile"``, or
          ``"insufficient_data"`` (empty input).
    """
    if not verdicts:
        return {"stability_score": None, "max_consecutive_non_promotable": 0, "non_promotable_count": 0, "total_window_count": 0, "stability_verdict": "insufficient_data"}

    _non_promotable_labels: frozenset[str] = frozenset({"keep_precision_baseline", "coverage_only_not_runner_better", "tail_hit_better_but_t1_risky"})
    total = len(verdicts)
    max_streak = 0
    current_streak = 0
    non_promotable_count = 0
    for verdict_label, _detail in verdicts:
        if verdict_label in _non_promotable_labels:
            non_promotable_count += 1
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0

    stability_score = round(1.0 - (non_promotable_count / total), 4)
    is_unstable = (max_streak >= PROFILE_STABILITY_NON_PROMOTABLE_STREAK_THRESHOLD) or (non_promotable_count / total >= PROFILE_STABILITY_NON_PROMOTABLE_FRACTION_THRESHOLD)
    stability_verdict = "unstable_profile" if is_unstable else "stable_profile"
    return {
        "stability_score": stability_score,
        "max_consecutive_non_promotable": max_streak,
        "non_promotable_count": non_promotable_count,
        "total_window_count": total,
        "stability_verdict": stability_verdict,
    }


def summarize_walk_forward(results: Sequence[WalkForwardResult], baseline_summary: dict | None = None) -> dict[str, Any]:
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
            # Task 1 (Round 14): profile stability — no windows means insufficient_data.
            "profile_stability_score": None,
            "profile_stability_max_consecutive_non_promotable": 0,
            "profile_stability_verdict": "insufficient_data",
            # Task 2 (Round 14): candidate pool size — no data when empty.
            "avg_candidate_pool_size": None,
            "scarce_market_window_count": 0,
            "abundant_market_window_count": 0,
            "market_size_classification": "unknown",
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
    # Task 4 (Round 11): time-weighted BTST quality metrics — parallel weight lists for each
    # BTST quality metric so we can compute recency-weighted averages.
    btst_metric_weights: dict[str, list[float]] = {key: [] for key in btst_metric_keys}
    # Task 2 (Round 13): cap-guarded metrics (e.g. excess kurtosis) are tracked separately with
    # plain (unweighted) averages — recency-weighting adds noise for distributional shape metrics.
    btst_cap_metric_keys = tuple(BTST_QUALITY_CAPS.keys())
    btst_cap_metric_values: dict[str, list[float]] = {key: [] for key in btst_cap_metric_keys}
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

    def _weighted_average(values: list[float], weights: list[float]) -> float | None:
        if not values:
            return None
        total_w = sum(weights) if weights else 0.0
        if total_w <= 0.0:
            return None
        return sum(v * w for v, w in zip(values, weights)) / total_w

    # Task 4 (Round 11): derive per-result recency weights from test_start dates.
    # The most recent window (largest test_start) anchors the reference date.
    _all_test_starts = [item.window.test_start for item in results]
    _reference_date = max(_all_test_starts) if _all_test_starts else ""
    _recency_weights: list[float] = [_compute_walk_forward_recency_weight(item.window.test_start, _reference_date) for item in results]

    for item, recency_w in zip(results, _recency_weights):
        bundle = build_canonical_btst_evaluation_bundle(item.metrics)
        window_has_complete_btst_quality = True
        for metric_key in btst_metric_keys:
            value = bundle.lookup(metric_key)
            if value is None:
                window_has_complete_btst_quality = False
                continue
            btst_metric_values[metric_key].append(float(value))
            btst_metric_weights[metric_key].append(recency_w)
        for metric_key in execution_metric_keys:
            value = bundle.lookup(metric_key)
            if value is not None:
                execution_metric_values[metric_key].append(float(value))
        # Task 2 (Round 13): collect cap-guarded metrics (e.g. kurtosis) using plain (unweighted) accumulation.
        for metric_key in btst_cap_metric_keys:
            value = bundle.lookup(metric_key)
            if value is not None:
                btst_cap_metric_values[metric_key].append(float(value))
        if window_has_complete_btst_quality:
            btst_complete_window_count += 1

    positive_sharpe_window_count = sum(1 for value in sharpe_values if float(value or 0.0) > 0.0)
    negative_sharpe_window_count = sum(1 for value in sharpe_values if float(value or 0.0) < 0.0)
    zero_sharpe_window_count = sum(1 for value in sharpe_values if abs(float(value or 0.0)) < 1e-12)
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

    # Task 2 (Round 14): candidate pool size adaptive awareness — track per-window pool sizes to
    # identify "scarce market" (pool < CANDIDATE_POOL_SCARCE_THRESHOLD) and "abundant market"
    # (pool > CANDIDATE_POOL_ABUNDANT_THRESHOLD) windows and compute aggregate pool statistics.
    candidate_pool_size_values: list[int] = [int(float(v)) for item in results for v in [item.metrics.get("candidate_pool_size")] if v is not None]
    avg_candidate_pool_size: float | None = (sum(candidate_pool_size_values) / len(candidate_pool_size_values)) if candidate_pool_size_values else None
    scarce_market_window_count = sum(1 for size in candidate_pool_size_values if size < CANDIDATE_POOL_SCARCE_THRESHOLD)
    abundant_market_window_count = sum(1 for size in candidate_pool_size_values if size > CANDIDATE_POOL_ABUNDANT_THRESHOLD)
    # Derive market size classification: a majority of tracked windows determines the label.
    if candidate_pool_size_values:
        _tracked = len(candidate_pool_size_values)
        if scarce_market_window_count / _tracked > 0.5:
            market_size_classification = "scarce_dominated"
        elif abundant_market_window_count / _tracked > 0.5:
            market_size_classification = "abundant_dominated"
        else:
            market_size_classification = "mixed"
    else:
        market_size_classification = "unknown"

    # Task 4 (Round 11): use recency-weighted averages for BTST quality metrics so that more
    # recent walk-forward windows carry proportionally more weight in rollout decisions.
    # The rollout floor checks continue to operate on these weighted averages.
    btst_quality_summary: dict[str, float | None] = {
        metric_key: _weighted_average(btst_metric_values[metric_key], btst_metric_weights[metric_key]) for metric_key in btst_metric_keys
    }
    btst_quality_summary["window_coverage"] = (
        float(btst_complete_window_count) / float(len(results)) if btst_complete_window_count > 0 else None
    )
    # Task 2 (Round 13): merge plain-average cap metrics into the quality summary so that
    # build_btst_quality_cap_blockers can inspect them alongside the floor-guarded metrics.
    btst_cap_summary: dict[str, float | None] = {metric_key: _average(btst_cap_metric_values[metric_key]) for metric_key in btst_cap_metric_keys}
    btst_quality_summary.update(btst_cap_summary)
    execution_summary: dict[str, float | None] = {
        metric_key: _average(execution_metric_values[metric_key]) for metric_key in execution_metric_keys
    }
    if any(value is not None for value in btst_quality_summary.values()):
        rollout_blockers.extend(build_btst_quality_floor_blockers(btst_quality_summary))
        rollout_blockers.extend(build_btst_quality_cap_blockers(btst_quality_summary))

    # Task 1 (Round 14): compute profile stability from the per-window runner verdicts.
    # Only include windows that have explicit runner metric data (max_future_high_return_2_5d_hit_rate_at_20pct
    # must be present); windows without runner data are not informative for stability assessment.
    # The stability assessment then checks for consecutive non-promotable runs and high non-promotable fractions.
    _per_window_verdicts: list[tuple[str, dict]] = []
    for _item in results:
        if _item.metrics.get("max_future_high_return_2_5d_hit_rate_at_20pct") is None:
            continue  # skip windows without runner data — they cannot produce meaningful stability verdicts
        _window_summary: dict[str, Any] = {**_item.metrics}
        _wv_label, _wv_detail = classify_runner_rollout_verdict(runner_summary=_window_summary)
        _per_window_verdicts.append((_wv_label, _wv_detail))
    profile_stability = assess_profile_stability(_per_window_verdicts)
    # If the profile is unstable, add a rollout blocker so the optimizer can reject or penalise it.
    if profile_stability["stability_verdict"] == "unstable_profile":
        rollout_blockers.append("profile_stability_unstable")

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
        # Task 4 (Round 11): expose the recency weighting parameters for transparency.
        "recency_half_life_days": WALK_FORWARD_RECENCY_HALF_LIFE_DAYS,
        # Task 1 (Round 14): profile stability across consecutive windows.
        "profile_stability_score": profile_stability["stability_score"],
        "profile_stability_max_consecutive_non_promotable": profile_stability["max_consecutive_non_promotable"],
        "profile_stability_verdict": profile_stability["stability_verdict"],
        # Task 2 (Round 14): candidate pool size adaptive awareness.
        "avg_candidate_pool_size": avg_candidate_pool_size,
        "scarce_market_window_count": scarce_market_window_count,
        "abundant_market_window_count": abundant_market_window_count,
        "market_size_classification": market_size_classification,
        "rollout_ready": not rollout_blockers,
        "rollout_blockers": rollout_blockers,
    }
    runner_verdict, runner_verdict_detail = classify_runner_rollout_verdict(runner_summary=base_summary)

    # Task B (Round btst-winrate-design-20260517): expose win-rate-first acceptance verdict
    # Pass baseline_summary through to enable real uplift evaluation when available
    win_rate_first_verdict, win_rate_first_verdict_detail = classify_win_rate_first_rollout_verdict(
        candidate_summary=base_summary,
        baseline_summary=baseline_summary,
    )

    return {
        **base_summary,
        **build_promotion_gate_summary(walk_forward_summary=base_summary),
        "runner_rollout_verdict": runner_verdict,
        "runner_rollout_verdict_detail": runner_verdict_detail,
        "win_rate_first_verdict": win_rate_first_verdict,
        "win_rate_first_verdict_detail": win_rate_first_verdict_detail,
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
        t2_win_rate = float(runner_summary.get("t_plus_2_close_positive_rate") or 0.0)
        t3_win_rate = float(runner_summary.get("t_plus_3_close_positive_rate") or 0.0)
        t2_regression = t2_win_rate - float(baseline_summary.get("t_plus_2_close_positive_rate") or 0.0)
        t3_regression = t3_win_rate - float(baseline_summary.get("t_plus_3_close_positive_rate") or 0.0)

        # Check T+1, T+2, T+3, or downside regression.
        # T+1/T+2/T+3 are evaluated symmetrically. We combine two flags:
        #   1. Regression: candidate has regressed by more than the floor
        #      relative to the baseline.
        #   2. Absolute minimum: candidate's raw win rate is below
        #      RUNNER_T*_WIN_RATE_ABSOLUTE_MIN — even if it matches the
        #      baseline (e.g. both 0%), an absolute-floor breach is risky.
        # GAMMA-004: the previous `> 0.0` guard on t2/t3 made 0% T+2/T+3
        # win rates pass as "not risky" — logically inverted.
        t1_risky = t1_regression < RUNNER_T1_WIN_RATE_REGRESSION_FLOOR
        t2_regression_risky = t2_regression < RUNNER_T2_WIN_RATE_REGRESSION_FLOOR
        t3_regression_risky = t3_regression < RUNNER_T3_WIN_RATE_REGRESSION_FLOOR
        t2_risky = t2_regression_risky or t2_win_rate < RUNNER_T2_WIN_RATE_ABSOLUTE_MIN
        t3_risky = t3_regression_risky or t3_win_rate < RUNNER_T3_WIN_RATE_ABSOLUTE_MIN
        downside_risky = downside_regression < RUNNER_DOWNSIDE_REGRESSION_FLOOR

        if improvement >= RUNNER_TAIL_HIT_IMPROVEMENT_MIN and (t1_risky or t2_risky or t3_risky or downside_risky):
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


def classify_win_rate_first_rollout_verdict(
    candidate_summary: dict,
    baseline_summary: dict | None = None,
) -> tuple[str, dict]:
    def _delta(metric_key: str) -> float | None:
        candidate_value = candidate_summary.get(metric_key)
        if baseline_summary is not None:
            baseline_value = baseline_summary.get(metric_key)
            if candidate_value is None or baseline_value is None:
                return None
            return float(candidate_value) - float(baseline_value)
        delta_value = candidate_summary.get(f"{metric_key}_delta")
        if delta_value is None:
            return None
        return float(delta_value)

    close_positive_delta = _delta("next_close_positive_rate")
    high_hit_delta = _delta("next_high_hit_rate")
    payoff_ratio_delta = _delta("realized_payoff_ratio")
    expectancy_delta = _delta("next_close_expectancy")
    coverage_delta = _delta("window_coverage")
    rollout_blockers = list(candidate_summary.get("rollout_blockers") or [])

    # Task B spec fix: if no baseline and no deltas, cannot evaluate uplift → neutral verdict
    # BUT: existing rollout_blockers must still force rejection
    if baseline_summary is None and close_positive_delta is None and high_hit_delta is None:
        if rollout_blockers:
            # Blocker-constrained candidate remains rejected regardless of baseline availability
            detail = {
                "next_close_positive_rate_delta": None,
                "next_high_hit_rate_delta": None,
                "realized_payoff_ratio_delta": None,
                "next_close_expectancy_delta": None,
                "window_coverage_delta": None,
                "rollout_blockers": rollout_blockers,
                "rejection_reasons": ["rollout_blocked"],
                "verdict_reason": "rollout_blocked",
            }
            return ("rejected", detail)
        # Only blocker-free candidates without baseline/deltas may return neutral
        detail = {
            "next_close_positive_rate_delta": None,
            "next_high_hit_rate_delta": None,
            "realized_payoff_ratio_delta": None,
            "next_close_expectancy_delta": None,
            "window_coverage_delta": None,
            "rollout_blockers": rollout_blockers,
            "rejection_reasons": [],
            "verdict_reason": "not_evaluable",
        }
        return ("neutral", detail)

    rejection_reasons: list[str] = []
    if rollout_blockers:
        rejection_reasons.append("rollout_blocked")
    if close_positive_delta is None or close_positive_delta < WIN_RATE_FIRST_MIN_POSITIVE_DELTA:
        rejection_reasons.append("win_rate_uplift_missing")
    if high_hit_delta is None or high_hit_delta < WIN_RATE_FIRST_MIN_POSITIVE_DELTA:
        rejection_reasons.append("win_rate_uplift_missing")
    if payoff_ratio_delta is not None and payoff_ratio_delta < -WIN_RATE_FIRST_MAX_PAYOFF_DEGRADATION:
        rejection_reasons.append("payoff_degradation_too_large")
    elif payoff_ratio_delta is None and expectancy_delta is not None and expectancy_delta < -WIN_RATE_FIRST_MAX_EXPECTANCY_DEGRADATION:
        rejection_reasons.append("payoff_degradation_too_large")
    if coverage_delta is not None and coverage_delta < -WIN_RATE_FIRST_MAX_COVERAGE_DEGRADATION:
        rejection_reasons.append("coverage_degradation_too_large")

    rejection_reasons = list(dict.fromkeys(rejection_reasons))
    if not rejection_reasons:
        verdict_reason = "meets_win_rate_first_criteria"
    elif "rollout_blocked" in rejection_reasons:
        verdict_reason = "rollout_blocked"
    elif rejection_reasons == ["win_rate_uplift_missing"]:
        verdict_reason = "win_rate_uplift_missing"
    else:
        verdict_reason = "bounded_tradeoff_check_failed"

    detail = {
        "next_close_positive_rate_delta": close_positive_delta,
        "next_high_hit_rate_delta": high_hit_delta,
        "realized_payoff_ratio_delta": payoff_ratio_delta,
        "next_close_expectancy_delta": expectancy_delta,
        "window_coverage_delta": coverage_delta,
        "rollout_blockers": rollout_blockers,
        "rejection_reasons": rejection_reasons,
        "verdict_reason": verdict_reason,
    }
    return ("accepted" if not rejection_reasons else "rejected"), detail


# Verdict priority ordering — higher index means better/more preferred.
# Used by select_best_promotable_candidate to rank candidates when multiple pass checks.
_VERDICT_PRIORITY: dict[str, int] = {
    "keep_precision_baseline": 0,
    "coverage_only_not_runner_better": 1,
    "tail_hit_better_but_t1_risky": 2,
    "promotable_runner_profile": 3,
}


def select_best_promotable_candidate(
    candidates: Sequence[tuple[str, dict]],
    baseline_summary: dict | None = None,
) -> tuple[str | None, str | None, dict]:
    """Evaluate a list of runner candidates and return the best promotable one.

    Replaces the manual single-candidate workflow of calling
    :func:`classify_runner_rollout_verdict` individually for each profile variant.
    The function evaluates every candidate, ranks them by verdict quality, and
    returns the winner — or ``(None, None, {})`` when the list is empty.

    Priority (highest to lowest):
    1. ``promotable_runner_profile``
    2. ``tail_hit_better_but_t1_risky``
    3. ``coverage_only_not_runner_better``
    4. ``keep_precision_baseline``

    Ties within the same verdict class are broken by descending
    ``avg_runner_tail_hit_rate`` so the most aggressive runner wins.

    Args:
        candidates: Sequence of ``(label, runner_summary)`` pairs.  *label* is an
            arbitrary string that identifies the candidate (e.g. ``"half_life_90"``
            or ``"threshold_0.50"``).
        baseline_summary: Optional baseline walk-forward summary dict with the same
            keys as *runner_summary*.  Forwarded to :func:`classify_runner_rollout_verdict`
            for each candidate so relative comparisons are consistent.

    Returns:
        A three-tuple ``(best_label, best_verdict, best_detail)`` where:
        - *best_label* is the label of the winning candidate (or ``None``).
        - *best_verdict* is its verdict string (or ``None``).
        - *best_detail* is the detail dict from :func:`classify_runner_rollout_verdict`
          (empty dict when there are no candidates).
    """
    if not candidates:
        return None, None, {}

    scored: list[tuple[int, float, str, str, dict]] = []
    for label, runner_summary in candidates:
        verdict, detail = classify_runner_rollout_verdict(runner_summary, baseline_summary)
        priority = _VERDICT_PRIORITY.get(verdict, 0)
        tail_hit = float(runner_summary.get("avg_runner_tail_hit_rate") or 0.0)
        scored.append((priority, tail_hit, label, verdict, detail))

    # Sort descending: highest priority first, then highest tail_hit as tie-breaker
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    _best_priority, _best_tail_hit, best_label, best_verdict, best_detail = scored[0]
    return best_label, best_verdict, best_detail
