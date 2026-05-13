from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

# ---------------------------------------------------------------------------
# Task 1 (Round 10) — Factor IC validation
# ---------------------------------------------------------------------------
# The seven primary BTST scoring factors whose Information Coefficient (IC) we
# track.  IC = Spearman rank correlation between factor value and forward return.
BTST_FACTOR_NAMES: tuple[str, ...] = (
    "breakout_freshness",
    "trend_acceleration",
    "volume_expansion_quality",
    "catalyst_freshness",
    "close_strength",
    "volatility_regime",
    "sector_resonance",
    # Task 1 (Round 16): single-bar T0 net inflow ratio — measures buying pressure from T0 OHLCV.
    "t0_estimated_net_inflow_ratio",
    # Task 2 (Round 16): bar-structure divergence score — upper-shadow ratio on up-bars signals
    # distribution risk; high values predict T+1 reversal.
    "volume_price_divergence_score",
    # Task 2 (Round 17): T0 tail-session strength proxy — close/high ratio on the trade day.
    # Values near 1.0 indicate price held near the day high at close (late-session buying strength).
    # Values near 0 indicate heavy late-session selling (price closed well below the day high).
    "t0_tail_strength",
    # Task 1 (Round 26, Alpha): cross-factor F11 — momentum confirmation score.
    # breakout_freshness × close_strength: fresh breakout AND strong close = dual confirmation signal.
    # Neutral 0.25 (=0.5×0.5) when both primary factors are at mid-point; both missing → 0.25.
    "momentum_confirmation_score",
    # Task 1 (Round 26, Alpha): cross-factor F12 — volume momentum score.
    # volume_expansion_quality × t0_tail_strength: expanding volume AND late-session bid persistence.
    # Signals sustained institutional accumulation rather than ephemeral intraday spike.
    "volume_momentum_score",
)


def _rank_list(values: list[float]) -> list[float]:
    """Return average rank vector for *values* (1-based, ties resolved by average).

    Pure-stdlib implementation — no scipy dependency.
    """
    n = len(values)
    if n == 0:
        return []
    sorted_indices = sorted(range(n), key=lambda i: values[i])
    ranks: list[float] = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n and values[sorted_indices[j]] == values[sorted_indices[i]]:
            j += 1
        avg_rank = (i + j + 1) / 2.0  # 1-based average rank for this tie group
        for k in range(i, j):
            ranks[sorted_indices[k]] = avg_rank
        i = j
    return ranks


def _spearman_corr(xs: list[float], ys: list[float]) -> float | None:
    """Compute Spearman rank correlation between two equal-length numeric lists.

    Returns ``None`` when fewer than 5 observations are provided or when either
    rank vector has zero variance (constant list).  Result is rounded to 4 decimal
    places.

    Args:
        xs: First numeric list.
        ys: Second numeric list (must be same length as *xs*).

    Returns:
        Spearman correlation coefficient in [-1, 1], or ``None`` if insufficient data.
    """
    n: int = len(xs)
    if n < 5 or n != len(ys):
        return None
    rx = _rank_list(xs)
    ry = _rank_list(ys)
    mean_rx: float = sum(rx) / n
    mean_ry: float = sum(ry) / n
    numerator: float = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    denom_x: float = sum((v - mean_rx) ** 2 for v in rx) ** 0.5
    denom_y: float = sum((v - mean_ry) ** 2 for v in ry) ** 0.5
    if denom_x == 0.0 or denom_y == 0.0:
        return None
    return round(numerator / (denom_x * denom_y), 4)


def compute_factor_ic(rows: list[dict[str, Any]], factor_col: str, return_col: str = "next_close_return") -> float | None:
    """Compute Spearman rank IC between *factor_col* values and *return_col* forward returns.

    Returns ``None`` when fewer than 5 paired observations are available (insufficient data
    to produce a meaningful correlation estimate).  The result is rounded to 4 decimal places.
    """
    pairs: list[tuple[float, float]] = []
    for row in rows:
        f_val = row.get(factor_col)
        r_val = row.get(return_col)
        if f_val is not None and r_val is not None:
            try:
                pairs.append((float(f_val), float(r_val)))
            except (TypeError, ValueError):
                continue
    if len(pairs) < 5:
        return None
    factors = [p[0] for p in pairs]
    returns = [p[1] for p in pairs]
    rf = _rank_list(factors)
    rr = _rank_list(returns)
    n = len(rf)
    mean_rf = sum(rf) / n
    mean_rr = sum(rr) / n
    numerator = sum((rf[i] - mean_rf) * (rr[i] - mean_rr) for i in range(n))
    denom_f = sum((x - mean_rf) ** 2 for x in rf) ** 0.5
    denom_r = sum((x - mean_rr) ** 2 for x in rr) ** 0.5
    if denom_f == 0.0 or denom_r == 0.0:
        return None
    return round(numerator / (denom_f * denom_r), 4)


def compute_all_factor_ics(rows: list[dict[str, Any]], return_col: str = "next_close_return") -> dict[str, float | None]:
    """Compute Spearman IC for all :data:`BTST_FACTOR_NAMES` against *return_col*.

    Returns a dict mapping factor name → IC value (or ``None`` if insufficient data).

    Task 1 (Round 26, Alpha): cross-factor terms ``momentum_confirmation_score`` (F11) and
    ``volume_momentum_score`` (F12) are injected into each row before IC computation.  Missing
    primary factors are replaced with neutral 0.5 so the cross-product is always computable.
    """
    # Inject cross-factor values so compute_factor_ic can find them by key.
    for row in rows:
        row["momentum_confirmation_score"] = row.get("breakout_freshness", 0.5) * row.get("close_strength", 0.5)
        row["volume_momentum_score"] = row.get("volume_expansion_quality", 0.5) * row.get("t0_tail_strength", 0.5)
    return {factor: compute_factor_ic(rows, factor, return_col) for factor in BTST_FACTOR_NAMES}


# ---------------------------------------------------------------------------
# Task 3 (Round 12) — IC dynamic weight suggestions
# ---------------------------------------------------------------------------
# When a factor's average Spearman IC persistently stays below IC_WEIGHT_DOWNGRADE_THRESHOLD
# the optimizer should de-emphasise it; when it clearly exceeds IC_WEIGHT_UPGRADE_THRESHOLD
# the factor is a strong predictor and its weight can be raised.  These thresholds are used
# by compute_ic_weight_suggestions to generate per-factor recommendations that are written
# into the surface report so the optimizer can pick them up in the next search round.
IC_WEIGHT_DOWNGRADE_THRESHOLD: float = 0.02   # IC below this → suggest reducing weight
IC_WEIGHT_UPGRADE_THRESHOLD: float = 0.05     # IC above this → suggest maintaining / increasing


def compute_ic_weight_suggestions(avg_factor_ics: dict[str, float | None]) -> dict[str, str]:
    """Return per-factor weight adjustment suggestions based on average Spearman IC values.

    Each factor receives one of three labels:
    - ``"reduce"``: average IC is below :data:`IC_WEIGHT_DOWNGRADE_THRESHOLD` — factor is
      weakly predictive and its composite weight should be lowered in the next search round.
    - ``"increase"``: average IC is at or above :data:`IC_WEIGHT_UPGRADE_THRESHOLD` — factor
      is a strong predictor; its weight can be raised or maintained at a premium level.
    - ``"maintain"``: average IC is between the two thresholds — no change recommended.

    Factors with ``None`` IC (insufficient data) are excluded from the output.

    Args:
        avg_factor_ics: Mapping of factor name → average IC value (or ``None``).

    Returns:
        Dict mapping factor name → suggestion string for factors with valid IC data.
    """
    suggestions: dict[str, str] = {}
    for factor, ic_val in avg_factor_ics.items():
        if ic_val is None:
            continue
        ic = float(ic_val)
        if ic < IC_WEIGHT_DOWNGRADE_THRESHOLD:
            suggestions[factor] = "reduce"
        elif ic >= IC_WEIGHT_UPGRADE_THRESHOLD:
            suggestions[factor] = "increase"
        else:
            suggestions[factor] = "maintain"
    return suggestions

import pandas as pd

from scripts.btst_data_utils import (
    load_json,
    normalize_price_frame,
    round_or_none,
    safe_float,
)
from src.project_env import load_project_dotenv
from src.tools.akshare_api import get_prices_robust
from src.tools.api import get_price_data, prices_to_df

load_project_dotenv()


def normalize_trade_date(value: Any) -> str:
    token = str(value or "").strip()
    if len(token) == 8 and token.isdigit():
        return f"{token[:4]}-{token[4:6]}-{token[6:8]}"
    return token


def iter_selection_snapshots(report_dir: str | Path):
    selection_root = Path(report_dir).expanduser().resolve() / "selection_artifacts"
    if not selection_root.exists():
        return
    for day_dir in sorted(path for path in selection_root.iterdir() if path.is_dir()):
        snapshot_path = day_dir / "selection_snapshot.json"
        if snapshot_path.exists():
            yield load_json(snapshot_path)


def load_session_summary_aggregate(report_dir: str | Path) -> dict[str, Any] | None:
    report_path = Path(report_dir).expanduser().resolve()
    session_summary_path = report_path / "session_summary.json"
    if not session_summary_path.exists():
        return None

    session_summary = load_json(session_summary_path)
    selection_artifact_root = Path(str(((session_summary.get("artifacts") or {}).get("selection_artifact_root") or report_path / "selection_artifacts"))).expanduser()
    daily_events_path = Path(str(((session_summary.get("artifacts") or {}).get("daily_events") or report_path / "daily_events.jsonl"))).expanduser()
    return {
        "session_summary_path": str(session_summary_path),
        "selection_target": ((session_summary.get("plan_generation") or {}).get("selection_target")),
        "dual_target_summary": dict(session_summary.get("dual_target_summary") or {}),
        "daily_event_stats": dict(session_summary.get("daily_event_stats") or {}),
        "selection_artifact_root_exists": selection_artifact_root.exists(),
        "daily_events_exists": daily_events_path.exists(),
    }


def fetch_price_frame(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], pd.DataFrame]) -> pd.DataFrame:
    normalized_trade_date = normalize_trade_date(trade_date)
    cache_key = (ticker, normalized_trade_date)
    cached = price_cache.get(cache_key)
    if cached is not None:
        return cached

    end_date = (pd.Timestamp(normalized_trade_date) + pd.Timedelta(days=15)).strftime("%Y-%m-%d")

    def _load_frame(start_date: str) -> pd.DataFrame:
        try:
            return normalize_price_frame(get_price_data(ticker, start_date, end_date))
        except Exception:
            try:
                return normalize_price_frame(prices_to_df(get_prices_robust(ticker, start_date, end_date, use_mock_on_fail=False)))
            except Exception:
                return pd.DataFrame()

    frame = _load_frame(normalized_trade_date)
    if frame.empty or frame.loc[frame.index.normalize() <= pd.Timestamp(normalized_trade_date).normalize()].empty:
        lookback_start = (pd.Timestamp(normalized_trade_date) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        lookback_frame = _load_frame(lookback_start)
        if not lookback_frame.empty:
            frame = lookback_frame

    price_cache[cache_key] = frame
    return frame


def resolve_btst_trade_anchor(frame: pd.DataFrame, trade_date: str) -> tuple[Any | None, pd.DataFrame, str | None, bool]:
    normalized_trade_date = normalize_trade_date(trade_date)
    trade_ts = pd.Timestamp(normalized_trade_date)
    same_day = frame.loc[frame.index.normalize() == trade_ts.normalize()]
    future_days = frame.loc[frame.index.normalize() > trade_ts.normalize()]
    if not same_day.empty:
        return same_day.iloc[0], future_days, normalized_trade_date, False

    prior_days = frame.loc[frame.index.normalize() < trade_ts.normalize()]
    if prior_days.empty:
        return None, future_days, None, False

    anchor_trade_date = prior_days.index[-1].strftime("%Y-%m-%d")
    return prior_days.iloc[-1], future_days, anchor_trade_date, True


def extract_btst_price_outcome(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], pd.DataFrame]) -> dict[str, Any]:
    normalized_trade_date = normalize_trade_date(trade_date)
    frame = fetch_price_frame(ticker, normalized_trade_date, price_cache)
    if frame.empty:
        return {
            "data_status": "missing_price_frame",
            "cycle_status": "missing_next_day",
        }

    trade_row, future_days, anchor_trade_date, used_prior_trade_anchor = resolve_btst_trade_anchor(frame, normalized_trade_date)
    if trade_row is None:
        return {
            "data_status": "missing_trade_day_bar",
            "cycle_status": "missing_next_day",
        }

    if future_days.empty:
        return {
            "data_status": "missing_next_trade_day_bar",
            "trade_close": round_or_none(safe_float(trade_row.get("close"))),
            "trade_anchor_date": anchor_trade_date,
            "trade_date_was_non_trading": used_prior_trade_anchor,
            "cycle_status": "missing_next_day",
        }

    next_row = future_days.iloc[0]
    later_rows = future_days.iloc[1:]

    trade_close = safe_float(trade_row.get("close"))
    next_open = safe_float(next_row.get("open"))
    next_high = safe_float(next_row.get("high"))
    next_low = safe_float(next_row.get("low"))
    next_close = safe_float(next_row.get("close"))
    if trade_close is None or trade_close <= 0 or next_open is None or next_high is None or next_close is None:
        return {
            "data_status": "incomplete_next_trade_day_bar",
            "cycle_status": "missing_next_day",
        }

    # Task 1-3 (Round 16): T0 OHLCV for bar-metric computation.
    trade_open_raw: float | None = safe_float(trade_row.get("open"))
    trade_high_raw: float | None = safe_float(trade_row.get("high"))
    trade_low_raw: float | None = safe_float(trade_row.get("low"))
    _t0_bar_metrics: dict[str, Any] = {}
    if trade_open_raw is not None and trade_high_raw is not None and trade_low_raw is not None and trade_open_raw > 0 and trade_high_raw >= trade_low_raw:
        _t0_bar_metrics = compute_t0_bar_metrics(trade_open_raw, trade_high_raw, trade_low_raw, trade_close)

    t_plus_2_close = None
    t_plus_2_trade_date = None
    t_plus_3_close = None
    t_plus_3_trade_date = None
    t_plus_4_close = None
    t_plus_4_trade_date = None
    t_plus_5_close = None
    t_plus_5_trade_date = None
    if not later_rows.empty:
        second_row = later_rows.iloc[0]
        t_plus_2_close = safe_float(second_row.get("close"))
        t_plus_2_trade_date = later_rows.index[0].strftime("%Y-%m-%d")
    if len(later_rows) >= 2:
        third_row = later_rows.iloc[1]
        t_plus_3_close = safe_float(third_row.get("close"))
        t_plus_3_trade_date = later_rows.index[1].strftime("%Y-%m-%d")
    if len(later_rows) >= 3:
        fourth_row = later_rows.iloc[2]
        t_plus_4_close = safe_float(fourth_row.get("close"))
        t_plus_4_trade_date = later_rows.index[2].strftime("%Y-%m-%d")
    if len(later_rows) >= 4:
        fifth_row = later_rows.iloc[3]
        t_plus_5_close = safe_float(fifth_row.get("close"))
        t_plus_5_trade_date = later_rows.index[3].strftime("%Y-%m-%d")

    future_horizon_rows = future_days.iloc[:5]
    future_highs = future_horizon_rows["high"].dropna().astype(float) if not future_horizon_rows.empty else pd.Series(dtype=float)
    max_future_high = None if future_highs.empty else float(future_highs.max())
    max_future_high_trade_date_2_5d = None
    if max_future_high is not None:
        max_idx = future_horizon_rows[future_horizon_rows["high"].astype(float) == max_future_high].index[0]
        max_future_high_trade_date_2_5d = max_idx.strftime("%Y-%m-%d")
    max_future_high_return_2_5d = None if max_future_high is None else round((max_future_high / trade_close) - 1.0, 4)
    hit_rows = future_horizon_rows.loc[(future_horizon_rows["high"].astype(float) / trade_close) - 1.0 >= 0.20]
    time_to_hit_20pct = None if hit_rows.empty else int((hit_rows.index[0].normalize() - future_horizon_rows.index[0].normalize()).days + 1)
    future_high_hit_20pct_2_5d = False if hit_rows.empty else True

    data_status = "ok" if t_plus_2_close is not None else "missing_t_plus_2_bar"
    cycle_status = "closed_cycle" if t_plus_2_close is not None else "t1_only"

    return {
        "data_status": data_status,
        "cycle_status": cycle_status,
        "trade_close": round(trade_close, 4),
        "trade_anchor_date": anchor_trade_date,
        "trade_date_was_non_trading": used_prior_trade_anchor,
        "next_trade_date": future_days.index[0].strftime("%Y-%m-%d"),
        "next_open": round(next_open, 4),
        "next_high": round(next_high, 4),
        "next_low": round_or_none(next_low),
        "next_close": round(next_close, 4),
        "next_open_return": round((next_open / trade_close) - 1.0, 4),
        "next_high_return": round((next_high / trade_close) - 1.0, 4),
        # Task 1 (Round 12): T+1 intraday drawdown = low / open − 1 for next trading day.
        # Measures maximum adverse excursion from the open — negative when price dips below
        # the open.  Used to compute t_plus_1_intraday_drawdown_p10 in build_surface_summary.
        "next_low_return": None if next_low is None else round((next_low / trade_close) - 1.0, 4),
        "next_intraday_drawdown": None if (next_low is None or next_open is None or next_open <= 0) else round((next_low / next_open) - 1.0, 4),
        "next_close_return": round((next_close / trade_close) - 1.0, 4),
        "next_open_to_close_return": round((next_close / next_open) - 1.0, 4),
        "t_plus_2_trade_date": t_plus_2_trade_date,
        "t_plus_2_close": round_or_none(t_plus_2_close),
        "t_plus_2_close_return": None if t_plus_2_close is None else round((t_plus_2_close / trade_close) - 1.0, 4),
        "t_plus_3_trade_date": t_plus_3_trade_date,
        "t_plus_3_close": round_or_none(t_plus_3_close),
        "t_plus_3_close_return": None if t_plus_3_close is None else round((t_plus_3_close / trade_close) - 1.0, 4),
        "t_plus_4_trade_date": t_plus_4_trade_date,
        "t_plus_4_close": round_or_none(t_plus_4_close),
        "t_plus_4_close_return": None if t_plus_4_close is None else round((t_plus_4_close / trade_close) - 1.0, 4),
        "t_plus_5_trade_date": t_plus_5_trade_date,
        "t_plus_5_close": round_or_none(t_plus_5_close),
        "t_plus_5_close_return": None if t_plus_5_close is None else round((t_plus_5_close / trade_close) - 1.0, 4),
        "max_future_high_return_2_5d": max_future_high_return_2_5d,
        "max_future_high_trade_date_2_5d": max_future_high_trade_date_2_5d,
        "time_to_hit_20pct": time_to_hit_20pct,
        "future_high_hit_20pct_2_5d": future_high_hit_20pct_2_5d,
        # Task 1-3 (Round 16): T0 bar metrics — net inflow ratio, divergence score/flag, predicted range.
        # Absent (key not present) when T0 OHLCV is incomplete.
        **_t0_bar_metrics,
    }


def summarize_distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None, "p10": None, "p25": None, "p75": None, "p90": None}
    sorted_values = sorted(float(value) for value in values)
    max_index = len(sorted_values) - 1

    def _percentile(percent: float) -> float:
        if max_index <= 0:
            return round(sorted_values[0], 4)
        scaled_index = max(0.0, min(1.0, percent)) * max_index
        lower_index = int(scaled_index)
        upper_index = min(max_index, lower_index + 1)
        if lower_index == upper_index:
            return round(sorted_values[lower_index], 4)
        weight = scaled_index - lower_index
        interpolated = sorted_values[lower_index] + ((sorted_values[upper_index] - sorted_values[lower_index]) * weight)
        return round(interpolated, 4)

    return {
        "count": len(sorted_values),
        "min": round(sorted_values[0], 4),
        "max": round(sorted_values[-1], 4),
        "mean": round(mean(sorted_values), 4),
        "median": _percentile(0.50),
        "p10": _percentile(0.10),
        "p25": _percentile(0.25),
        "p75": _percentile(0.75),
        "p90": _percentile(0.90),
    }


def compute_excess_kurtosis(values: list[float]) -> float | None:
    """Return the excess kurtosis (Fisher definition: kurtosis − 3) of *values*.

    Uses the standard population formula (no bias correction) which is appropriate for
    the sample sizes encountered in BTST windows (typically 20–200 data points).

    Returns ``None`` when fewer than 4 values are available — kurtosis is undefined for
    n < 4 and unstable for very small samples.

    Args:
        values: List of numeric values (e.g. daily next-close returns).

    Returns:
        Excess kurtosis rounded to 4 decimal places, or ``None`` when insufficient data.
    """
    n = len(values)
    if n < 4:
        return None
    m = sum(values) / n
    variance = sum((x - m) ** 2 for x in values) / n
    if variance <= 0.0:
        return None
    fourth_moment = sum((x - m) ** 4 for x in values) / n
    return round(fourth_moment / (variance ** 2) - 3.0, 4)


def _build_return_edge_metrics(returns: list[float]) -> dict[str, float | int | None]:
    if not returns:
        return {
            "positive_count": 0,
            "negative_count": 0,
            "average_win": None,
            "average_loss_abs": None,
            "payoff_ratio": None,
            "profit_factor": None,
            "expectancy": None,
        }

    positive_returns = [float(value) for value in returns if float(value) > 0.0]
    negative_returns = [float(value) for value in returns if float(value) < 0.0]

    average_win = None if not positive_returns else float(mean(positive_returns))
    average_loss_abs = None if not negative_returns else abs(float(mean(negative_returns)))

    payoff_ratio: float | None = None
    if average_win is not None and average_loss_abs and average_loss_abs > 0.0:
        payoff_ratio = average_win / average_loss_abs

    positive_sum = sum(positive_returns)
    negative_sum_abs = abs(sum(negative_returns))
    profit_factor: float | None = None
    if negative_sum_abs > 0.0 and positive_sum > 0.0:
        profit_factor = positive_sum / negative_sum_abs

    win_rate = len(positive_returns) / len(returns)
    loss_rate = len(negative_returns) / len(returns)
    expectancy = (win_rate * (average_win or 0.0)) - (loss_rate * (average_loss_abs or 0.0))

    return {
        "positive_count": len(positive_returns),
        "negative_count": len(negative_returns),
        "average_win": round(average_win, 4) if average_win is not None else None,
        "average_loss_abs": round(average_loss_abs, 4) if average_loss_abs is not None else None,
        "payoff_ratio": round(payoff_ratio, 4) if payoff_ratio is not None else None,
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "expectancy": round(expectancy, 4),
    }



# ---------------------------------------------------------------------------
# Task 5 (Round 14): Regime-conditional backtesting constants and helpers.
# ---------------------------------------------------------------------------
# A "bull day" is defined as a trading day where the average next_close_return
# across all rows for that date exceeds REGIME_BULL_DAY_RETURN_THRESHOLD.
# Symmetrically, a "bear day" is below REGIME_BEAR_DAY_RETURN_THRESHOLD.
# All other days are classified as "sideways".
# This self-contained proxy requires no external market-index data.
REGIME_BULL_DAY_RETURN_THRESHOLD: float = 0.003   # avg daily return > +0.3 % → bull
REGIME_BEAR_DAY_RETURN_THRESHOLD: float = -0.003  # avg daily return < −0.3 % → bear


def build_regime_conditional_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute win-rate and payoff statistics grouped by market regime (Task 5, Round 14).

    Each row's trading date is assigned to one of three regimes — ``"bull"``, ``"bear"``, or
    ``"sideways"`` — by computing the average ``next_close_return`` across all rows that share
    the same ``trade_date``.  Dates where the average return exceeds
    :data:`REGIME_BULL_DAY_RETURN_THRESHOLD` (+0.3 %) are labelled "bull"; dates below
    :data:`REGIME_BEAR_DAY_RETURN_THRESHOLD` (−0.3 %) are labelled "bear"; the rest are
    "sideways".  This proxy is self-contained and requires no external market-index data.

    Args:
        rows: List of BTST candidate rows.  Each row must contain a ``trade_date`` string and
            may contain a numeric ``next_close_return`` field used for regime classification
            and statistics computation.

    Returns:
        A dict with three sub-dicts (``"bull"``, ``"bear"``, ``"sideways"``) each containing:

        - ``count`` (int): number of rows assigned to this regime.
        - ``next_close_positive_rate`` (float | None): win rate for rows in this regime.
        - ``next_close_payoff_ratio`` (float | None): average win / average loss magnitude.
        - ``next_close_average_win`` (float | None): average positive return.
        - ``next_close_average_loss_abs`` (float | None): average absolute negative return.
        - ``day_count`` (int): number of distinct trading dates assigned to this regime.

        Also includes:

        - ``regime_best_win_rate`` (str | None): name of the regime with the highest win rate
          (or ``None`` when no regime has sufficient data).
        - ``regime_best_payoff_ratio`` (str | None): name of the regime with the highest payoff
          ratio.
    """
    if not rows:
        _empty_regime: dict[str, Any] = {"count": 0, "next_close_positive_rate": None, "next_close_payoff_ratio": None, "next_close_average_win": None, "next_close_average_loss_abs": None, "day_count": 0}
        return {"bull": _empty_regime, "bear": _empty_regime, "sideways": _empty_regime, "regime_best_win_rate": None, "regime_best_payoff_ratio": None}

    # Step 1: compute per-date average next_close_return (using only rows where the field is present).
    from collections import defaultdict as _defaultdict
    date_returns: dict[str, list[float]] = _defaultdict(list)
    for row in rows:
        td = str(row.get("trade_date") or "")
        ncr = row.get("next_close_return")
        if td and ncr is not None:
            try:
                date_returns[td].append(float(ncr))
            except (TypeError, ValueError):
                pass

    # Step 2: classify each date.
    date_regime: dict[str, str] = {}
    for td, ret_list in date_returns.items():
        avg_ret = sum(ret_list) / len(ret_list)
        if avg_ret >= REGIME_BULL_DAY_RETURN_THRESHOLD:
            date_regime[td] = "bull"
        elif avg_ret <= REGIME_BEAR_DAY_RETURN_THRESHOLD:
            date_regime[td] = "bear"
        else:
            date_regime[td] = "sideways"

    # Step 3: assign each row to a regime and collect next_close_return for stats.
    regime_rows: dict[str, list[float]] = {"bull": [], "bear": [], "sideways": []}
    regime_day_counts: dict[str, set[str]] = {"bull": set(), "bear": set(), "sideways": set()}
    unclassified_rows: list[float] = []  # rows with trade_date not in date_regime
    for row in rows:
        td = str(row.get("trade_date") or "")
        ncr = row.get("next_close_return")
        if ncr is None:
            continue
        try:
            ret_val = float(ncr)
        except (TypeError, ValueError):
            continue
        regime = date_regime.get(td)
        if regime is not None:
            regime_rows[regime].append(ret_val)
            regime_day_counts[regime].add(td)
        else:
            unclassified_rows.append(ret_val)

    # Step 4: compute per-regime stats.
    def _regime_stats(returns: list[float], days: set[str]) -> dict[str, Any]:
        count = len(returns)
        if count == 0:
            return {"count": 0, "next_close_positive_rate": None, "next_close_payoff_ratio": None, "next_close_average_win": None, "next_close_average_loss_abs": None, "day_count": len(days)}
        wins = [r for r in returns if r > 0.0]
        losses = [r for r in returns if r < 0.0]
        win_rate = round(len(wins) / count, 4)
        avg_win = round(sum(wins) / len(wins), 4) if wins else None
        avg_loss_abs = round(abs(sum(losses) / len(losses)), 4) if losses else None
        payoff = round(avg_win / avg_loss_abs, 4) if avg_win is not None and avg_loss_abs and avg_loss_abs > 0.0 else None
        return {"count": count, "next_close_positive_rate": win_rate, "next_close_payoff_ratio": payoff, "next_close_average_win": avg_win, "next_close_average_loss_abs": avg_loss_abs, "day_count": len(days)}

    stats: dict[str, Any] = {label: _regime_stats(regime_rows[label], regime_day_counts[label]) for label in ("bull", "bear", "sideways")}

    # Step 5: identify best regime by win rate and payoff ratio.
    _win_rate_map = {label: stats[label]["next_close_positive_rate"] for label in ("bull", "bear", "sideways") if stats[label]["next_close_positive_rate"] is not None}
    regime_best_win_rate: str | None = max(_win_rate_map, key=_win_rate_map.__getitem__) if _win_rate_map else None
    _payoff_map = {label: stats[label]["next_close_payoff_ratio"] for label in ("bull", "bear", "sideways") if stats[label]["next_close_payoff_ratio"] is not None}
    regime_best_payoff_ratio: str | None = max(_payoff_map, key=_payoff_map.__getitem__) if _payoff_map else None

    return {**stats, "regime_best_win_rate": regime_best_win_rate, "regime_best_payoff_ratio": regime_best_payoff_ratio}


# ---------------------------------------------------------------------------
# Task 4 (Round 15): Stop-loss trigger rate analysis
# ---------------------------------------------------------------------------
# Computes the fraction of T+1 bars where the intraday low would have triggered
# each stop-loss level.  ``next_intraday_drawdown`` = (T+1 low / T+1 open) − 1
# is already present in price-outcome rows; a stop is triggered when that value
# is ≤ the threshold (e.g. ≤ −0.02 for a −2 % stop).
# Helps quantify the trade-off between "hold to close" and "stop-loss execution".
STOP_LOSS_THRESHOLDS: tuple[float, ...] = (-0.02, -0.03, -0.05)


def compute_stop_loss_trigger_rates(intraday_drawdown_values: list[float], thresholds: tuple[float, ...] = STOP_LOSS_THRESHOLDS) -> dict[str, float | None]:
    """Return the fraction of T+1 bars where each stop-loss threshold would be hit.

    A stop at level *t* (e.g. −0.02) is triggered when the intraday drawdown
    (= T+1 low / T+1 open − 1) is ≤ *t*.

    Args:
        intraday_drawdown_values: List of T+1 open-to-low returns (negative = adverse move).
        thresholds: Stop-loss levels to evaluate (each should be ≤ 0).

    Returns:
        Dict mapping ``"stop_loss_{pct}pct"`` keys to trigger-rate floats (0–1), or ``None``
        when no drawdown data are available.  Label examples: ``"stop_loss_2pct"``,
        ``"stop_loss_3pct"``, ``"stop_loss_5pct"``.
    """
    if not intraday_drawdown_values:
        return {f"stop_loss_{abs(round(t * 100))}pct": None for t in thresholds}
    n = len(intraday_drawdown_values)
    return {f"stop_loss_{abs(round(t * 100))}pct": round(sum(1 for v in intraday_drawdown_values if v <= t) / n, 4) for t in thresholds}


# ---------------------------------------------------------------------------
# Task 5 (Round 15): Cross-day momentum autocorrelation
# ---------------------------------------------------------------------------
# Computes the Spearman rank correlation between consecutive-day return pairs
# to detect momentum continuation vs. mean-reversion dynamics.
# A significantly negative T+1→T+2 autocorrelation signals mean-reversion risk
# and should be flagged in walk-forward summaries.
CROSS_DAY_AUTOCORR_MEAN_REVERSION_THRESHOLD: float = -0.10  # autocorr ≤ this → mean-reversion flag


def compute_cross_day_autocorrelation(t1_returns: list[float], t2_returns: list[float], t3_returns: list[float]) -> dict[str, float | None]:
    """Compute Spearman lag-1 autocorrelation across consecutive BTST holding-period returns.

    Two correlation pairs are computed for rows that share the same index position
    (i.e. the same candidate row):

    * ``t1_vs_t2``: Spearman(T+1 return, T+2 return) — primary momentum signal.
      A negative value indicates that stocks rising on T+1 tend to fall on T+2
      (mean reversion), which is a key risk for multi-day holds.
    * ``t2_vs_t3``: Spearman(T+2 return, T+3 return) — secondary continuation signal.

    Also computes ``t1_vs_t2_mean_reversion_flag`` (bool) when the T+1→T+2
    autocorrelation is ≤ :data:`CROSS_DAY_AUTOCORR_MEAN_REVERSION_THRESHOLD`.

    Args:
        t1_returns: Per-row T+1 close returns (``next_close_return``).
        t2_returns: Per-row T+2 close returns (same index, ``None``-free).
        t3_returns: Per-row T+3 close returns (same index, ``None``-free).

    Returns:
        Dict with keys ``t1_vs_t2``, ``t2_vs_t3``, ``t1_vs_t2_mean_reversion_flag``,
        ``t1_sample_count``, ``t2_sample_count``.
    """
    # Build paired vectors (both returns must be present).
    t1_t2_pairs: list[tuple[float, float]] = [(a, b) for a, b in zip(t1_returns, t2_returns)]
    t2_t3_pairs: list[tuple[float, float]] = [(a, b) for a, b in zip(t2_returns, t3_returns) if len(t2_returns) == len(t3_returns)]

    def _spearman(pairs: list[tuple[float, float]]) -> float | None:
        if len(pairs) < 5:
            return None
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        rx = _rank_list(xs)
        ry = _rank_list(ys)
        n = len(rx)
        mx = sum(rx) / n
        my = sum(ry) / n
        num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
        dx = sum((x - mx) ** 2 for x in rx) ** 0.5
        dy = sum((y - my) ** 2 for y in ry) ** 0.5
        if dx == 0.0 or dy == 0.0:
            return None
        return round(num / (dx * dy), 4)

    t1_vs_t2 = _spearman(t1_t2_pairs)
    t2_vs_t3 = _spearman(t2_t3_pairs)
    mean_reversion_flag = (t1_vs_t2 is not None) and (t1_vs_t2 <= CROSS_DAY_AUTOCORR_MEAN_REVERSION_THRESHOLD)
    return {
        "t1_vs_t2": t1_vs_t2,
        "t2_vs_t3": t2_vs_t3,
        "t1_vs_t2_mean_reversion_flag": mean_reversion_flag,
        "t1_sample_count": len(t1_returns),
        "t2_sample_count": len(t2_returns),
    }


# ---------------------------------------------------------------------------
# Task 2 (Round 15): Opening-gap continuation rate
# ---------------------------------------------------------------------------
# Measures the rate at which stocks that gap up strongly at the T+1 open
# (next_open_return > GAP_CONTINUATION_OPEN_THRESHOLD) also continue to rise
# during the T+1 session (next_open_to_close_return > 0).
# A high gap_continuation_rate (≥ 0.50) favours "buy at open" execution;
# a low rate suggests waiting for intraday confirmation before entry.
GAP_CONTINUATION_OPEN_THRESHOLD: float = 0.02   # ≥ 2 % open gap triggers the computation


def compute_gap_continuation_rate(rows: list[dict[str, Any]], open_gap_threshold: float = GAP_CONTINUATION_OPEN_THRESHOLD) -> dict[str, float | int | None]:
    """Compute the intraday-continuation rate for stocks that gap up significantly at the T+1 open.

    A "gap-up bar" is one where ``next_open_return`` ≥ *open_gap_threshold*.  Among those
    bars, the *continuation rate* is the fraction where ``next_open_to_close_return`` > 0
    (price continued to rise from open to close).

    Args:
        rows: BTST candidate rows with ``next_open_return`` and ``next_open_to_close_return``.
        open_gap_threshold: Minimum open-gap return to qualify (default 2 %).

    Returns:
        Dict with keys:

        - ``gap_continuation_rate`` (float | None): continuation rate among gap-up bars.
        - ``gap_up_bar_count`` (int): number of bars qualifying as gap-up.
        - ``gap_open_threshold_used`` (float): the threshold applied.
    """
    gap_rows = [row for row in rows if row.get("next_open_return") is not None and float(row["next_open_return"]) >= open_gap_threshold and row.get("next_open_to_close_return") is not None]
    if not gap_rows:
        return {"gap_continuation_rate": None, "gap_up_bar_count": 0, "gap_open_threshold_used": round(open_gap_threshold, 4)}
    continued = sum(1 for row in gap_rows if float(row["next_open_to_close_return"]) > 0.0)
    return {"gap_continuation_rate": round(continued / len(gap_rows), 4), "gap_up_bar_count": len(gap_rows), "gap_open_threshold_used": round(open_gap_threshold, 4)}


# ---------------------------------------------------------------------------
# Task 1 (Round 16) — T0 estimated net inflow ratio (资金流向因子)
# Task 2 (Round 16) — Volume-price divergence (量价背离检测)
# Task 3 (Round 16) — T0 predicted range pct + volatility/stop_loss linkage
# ---------------------------------------------------------------------------
# Task 1: T0 Net Inflow Ratio
# Approximates T0 buying/selling pressure from a single OHLCV bar.
# Formula: position of close within the bar's range mapped to [-1, +1].
#   +1 → close at day high  (pure buying pressure)
#   -1 → close at day low   (pure selling pressure)
#    0 → close at midpoint  (balanced)
# Source: classic Williams %R / buying-pressure ratio used in A-share technical analysis.
# Task 2: Volume-Price Divergence
# Detects "假阳线" (false breakout) bar structure: price rises but closes far below the day
# high, leaving a large upper shadow — sellers dominated above the close.
# For up-bars:  divergence_score = (high − close) / (high − low + ε)  → [0, 1]
#   0 = closed at high (no upper shadow, confirmed buying)
#   1 = closed at low  (all gains reversed, strong distribution)
# For down-bars: divergence_score = (close − low) / (high − low + ε) (selling above)
# divergence_flag fires when: (close/open − 1) ≥ UP_BAR_PRICE_CHANGE_MIN AND upper_shadow > threshold.
# Task 3: T0 Predicted Range Pct
# Uses T0 bar range (high − low) / open as a single-bar proxy for next-day volatility.
# Wired into stop_loss linkage: when p75(predicted_range_pct) > 4 % AND stop_loss_3pct rate > 25 %,
# the combined flag warns that the strategy is operating in a high-volatility / high-stop regime.
UP_BAR_PRICE_CHANGE_MIN: float = 0.02       # T0 up bar threshold to check for divergence
UPPER_SHADOW_DIVERGENCE_THRESHOLD: float = 0.45  # upper shadow > 45 % of range → divergence flag
HIGH_VOL_RANGE_THRESHOLD: float = 0.04     # T0 range > 4 % of open → high-volatility bar
HIGH_VOL_STOP_LOSS_RATE_THRESHOLD: float = 0.25  # stop_loss_3pct > 25 % jointly triggers warning


def compute_t0_bar_metrics(trade_open: float, trade_high: float, trade_low: float, trade_close: float) -> dict[str, Any]:
    """Compute single-bar T0 metrics for R16 Tasks 1, 2, 3 and R17 Task 2.

    All inputs are expected to be positive floats representing a single daily OHLCV bar on the
    trade day.  Returns a dict with the following keys:

    - ``t0_estimated_net_inflow_ratio`` (float): buying pressure in [-1, +1]; +1 = pure buying.
    - ``volume_price_divergence_score`` (float): bar-structure distribution risk in [0, 1]; 0 = no risk.
    - ``volume_price_divergence_flag`` (bool): True when bar is a confirmed false-breakout pattern.
    - ``t0_predicted_range_pct`` (float): T0 bar range as fraction of open (e.g. 0.05 = 5 % range).
    - ``t0_tail_strength`` (float): close / high ratio in (0, 1]; 1.0 = closed at day high (尾盘强势).
    """
    epsilon: float = 1e-6
    safe_range: float = max(trade_high - trade_low, epsilon)
    safe_open: float = max(trade_open, epsilon)

    # Task 1 — net inflow ratio: (close − low) / range × 2 − 1 → [−1, +1]
    t0_estimated_net_inflow_ratio: float = round((trade_close - trade_low) / safe_range * 2.0 - 1.0, 4)

    # Task 2 — upper-shadow fraction
    upper_shadow_pct: float = (trade_high - trade_close) / safe_range
    is_up_bar: bool = trade_close >= trade_open
    if is_up_bar:
        # Distribution risk for up-bars: large upper shadow = sellers above close
        volume_price_divergence_score: float = round(upper_shadow_pct, 4)
    else:
        # For down-bars: lower shadow means buyers stepped in; score = 1 − (close−low)/range
        lower_shadow_pct: float = (trade_close - trade_low) / safe_range
        volume_price_divergence_score = round(1.0 - lower_shadow_pct, 4)

    price_change_pct: float = (trade_close - trade_open) / safe_open
    volume_price_divergence_flag: bool = bool(
        is_up_bar
        and price_change_pct >= UP_BAR_PRICE_CHANGE_MIN
        and upper_shadow_pct > UPPER_SHADOW_DIVERGENCE_THRESHOLD
    )

    # Task 3 — T0 bar range as fraction of open (volatility proxy)
    t0_predicted_range_pct: float = round((trade_high - trade_low) / safe_open, 4)

    # Task 2 (Round 17) — tail-session strength proxy: close / high ratio.
    # A ratio near 1.0 means price closed at/near the day high (尾盘强势); near 0 means heavy
    # late-session distribution (价格远低于最高价).  ε-guard prevents div-by-zero on flat bars.
    t0_tail_strength: float = round(trade_close / max(trade_high, epsilon), 4)

    return {
        "t0_estimated_net_inflow_ratio": t0_estimated_net_inflow_ratio,
        "volume_price_divergence_score": volume_price_divergence_score,
        "volume_price_divergence_flag": volume_price_divergence_flag,
        "t0_predicted_range_pct": t0_predicted_range_pct,
        # Task 2 (Round 17): tail-session strength proxy
        "t0_tail_strength": t0_tail_strength,
    }


def compute_predicted_range_stop_loss_linkage(predicted_range_pcts: list[float], stop_loss_trigger_rate_3pct: float | None) -> dict[str, Any]:
    """Compute the joint high-volatility / stop-loss warning.

    Returns:

    - ``high_volatility_warning_rate`` (float | None): fraction of rows where T0 range > 4 %.
    - ``predicted_range_pct_p75`` (float | None): 75th-percentile T0 predicted range.
    - ``predicted_range_stop_loss_warning`` (bool | None): True when p75 > HIGH_VOL_RANGE_THRESHOLD
      AND stop_loss_3pct > HIGH_VOL_STOP_LOSS_RATE_THRESHOLD — signals high-volatility regime
      with elevated stop-out risk.  None when either component is unavailable.
    """
    if not predicted_range_pcts:
        return {"high_volatility_warning_rate": None, "predicted_range_pct_p75": None, "predicted_range_stop_loss_warning": None}

    high_vol_count: int = sum(1 for v in predicted_range_pcts if v > HIGH_VOL_RANGE_THRESHOLD)
    high_volatility_warning_rate: float = round(high_vol_count / len(predicted_range_pcts), 4)
    dist: dict[str, Any] = summarize_distribution(predicted_range_pcts)
    predicted_range_pct_p75: float | None = dist.get("p75")

    predicted_range_stop_loss_warning: bool | None = None
    if predicted_range_pct_p75 is not None and stop_loss_trigger_rate_3pct is not None:
        predicted_range_stop_loss_warning = bool(
            predicted_range_pct_p75 > HIGH_VOL_RANGE_THRESHOLD
            and stop_loss_trigger_rate_3pct > HIGH_VOL_STOP_LOSS_RATE_THRESHOLD
        )

    return {
        "high_volatility_warning_rate": high_volatility_warning_rate,
        "predicted_range_pct_p75": predicted_range_pct_p75,
        "predicted_range_stop_loss_warning": predicted_range_stop_loss_warning,
    }


# ---------------------------------------------------------------------------
# Task 1 (Round 17): Breakout conditional win rate (均线突破有效性验证)
# ---------------------------------------------------------------------------
# Computes T+1 next-close win rate conditioned on whether breakout_freshness
# exceeds a threshold (≥ BREAKOUT_FRESHNESS_SIGNAL_THRESHOLD).  A positive
# *lift* (= win_rate_breakout − win_rate_non_breakout) confirms that the
# breakout_freshness factor has incremental predictive power beyond the base
# win rate.  Used in build_surface_summary to surface this per-window.
BREAKOUT_FRESHNESS_SIGNAL_THRESHOLD: float = 0.50  # freshness ≥ 0.5 → recent breakout


def compute_breakout_conditional_win_rate(rows: list[dict[str, Any]], *, breakout_threshold: float = BREAKOUT_FRESHNESS_SIGNAL_THRESHOLD) -> dict[str, Any]:
    """Compute T+1 win rate conditioned on breakout_freshness signal (Task 1, Round 17).

    Rows are split into two groups:

    - **breakout group** (``breakout_freshness >= breakout_threshold``): stocks with a
      recent high-freshness breakout signal.
    - **non-breakout group** (all other rows with valid ``breakout_freshness``).

    For each group, the *win rate* is the fraction of rows where
    ``next_close_return > 0``.  The *lift* is the difference
    ``win_rate_breakout − win_rate_non_breakout``.  A positive lift confirms that
    the breakout signal has additive predictive power over the base population.

    Args:
        rows: BTST candidate rows.  Must contain ``breakout_freshness`` (float) and
            ``next_close_return`` (float) for a row to be included.
        breakout_threshold: Minimum ``breakout_freshness`` score to qualify as a
            recent breakout (default :data:`BREAKOUT_FRESHNESS_SIGNAL_THRESHOLD` = 0.50).

    Returns:
        Dict with keys:

        - ``win_rate_breakout`` (float | None): win rate for fresh-breakout rows.
        - ``win_rate_non_breakout`` (float | None): win rate for non-fresh rows.
        - ``lift`` (float | None): ``win_rate_breakout − win_rate_non_breakout``.
        - ``breakout_sample_count`` (int): rows in the breakout group.
        - ``non_breakout_sample_count`` (int): rows in the non-breakout group.
        - ``breakout_threshold_used`` (float): the threshold applied.
    """
    breakout_wins: int = 0
    breakout_total: int = 0
    non_breakout_wins: int = 0
    non_breakout_total: int = 0

    for row in rows:
        bf = row.get("breakout_freshness")
        ncr = row.get("next_close_return")
        if bf is None or ncr is None:
            continue
        try:
            bf_f = float(bf)
            ncr_f = float(ncr)
        except (TypeError, ValueError):
            continue
        if bf_f >= breakout_threshold:
            breakout_total += 1
            if ncr_f > 0.0:
                breakout_wins += 1
        else:
            non_breakout_total += 1
            if ncr_f > 0.0:
                non_breakout_wins += 1

    win_rate_breakout: float | None = round(breakout_wins / breakout_total, 4) if breakout_total > 0 else None
    win_rate_non_breakout: float | None = round(non_breakout_wins / non_breakout_total, 4) if non_breakout_total > 0 else None
    lift: float | None = None
    if win_rate_breakout is not None and win_rate_non_breakout is not None:
        lift = round(win_rate_breakout - win_rate_non_breakout, 4)

    return {
        "win_rate_breakout": win_rate_breakout,
        "win_rate_non_breakout": win_rate_non_breakout,
        "lift": lift,
        "breakout_sample_count": breakout_total,
        "non_breakout_sample_count": non_breakout_total,
        "breakout_threshold_used": round(breakout_threshold, 4),
    }


# ---------------------------------------------------------------------------
# Task 3 (Round 17): Sell-timing optimization analysis (卖出时机优化分析)
# ---------------------------------------------------------------------------
# Uses T+1 OHLC data (already in price-outcome rows) to characterise when the
# best intraday exit opportunity occurs.  Key ratios:
#
#   open_vs_high_ratio  = next_open / next_high    (how close open is to day high)
#   open_vs_close_ratio = next_open / next_close   (open vs final price)
#
# Three exit windows are compared by median return:
#   "early"  — next_open_return            (sell at T+1 open)
#   "mid"    — (next_high + next_close) / 2 / trade_close − 1  (mid-day average proxy)
#   "late"   — next_close_return           (hold to T+1 close)
#
# optimal_exit_window = whichever of early/mid/late has the highest median return.
# When open_vs_high_ratio_mean < 0.80 on average, the open is at least 20 % below
# the day high — suggesting that limit orders above the open (intraday high-chase)
# systematically capture materially more return.
OPEN_VS_HIGH_SIGNIFICANT_DISCOUNT_THRESHOLD: float = 0.80  # open < 80 % of high → meaningful gap


def compute_sell_timing_analysis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyse T+1 OHLC data to identify the optimal intraday exit window (Task 3, Round 17).

    Args:
        rows: BTST candidate rows containing ``next_open``, ``next_high``, ``next_close``,
            ``trade_close``, ``next_open_return``, ``next_close_return``, and
            ``next_open_to_close_return``.

    Returns:
        Dict with keys:

        - ``open_vs_high_ratio_mean`` (float | None): mean(next_open / next_high).
        - ``open_vs_close_ratio_mean`` (float | None): mean(next_open / next_close).
        - ``exit_early_median_return`` (float | None): median T+1 open return (early exit proxy).
        - ``exit_late_median_return`` (float | None): median T+1 close return (hold-to-close proxy).
        - ``exit_mid_median_return`` (float | None): median mid-day proxy return ((high+close)/2 / trade_close − 1).
        - ``optimal_exit_window`` (str | None): ``"early"`` | ``"mid"`` | ``"late"`` — whichever
          has the highest median return; ``None`` when insufficient data.
        - ``open_significantly_below_high`` (bool | None): True when
          ``open_vs_high_ratio_mean < OPEN_VS_HIGH_SIGNIFICANT_DISCOUNT_THRESHOLD``
          (open is ≥ 20 % below the day high on average — intraday high-chase has material value).
        - ``sell_timing_sample_count`` (int): number of rows with complete T+1 OHLC data.
    """
    open_vs_high_ratios: list[float] = []
    open_vs_close_ratios: list[float] = []
    early_returns: list[float] = []
    late_returns: list[float] = []
    mid_returns: list[float] = []

    for row in rows:
        next_open = row.get("next_open")
        next_high = row.get("next_high")
        next_close = row.get("next_close")
        trade_close = row.get("trade_close")
        nor = row.get("next_open_return")
        ncr = row.get("next_close_return")
        if any(v is None for v in (next_open, next_high, next_close, trade_close, nor, ncr)):
            continue
        try:
            f_open = float(next_open)   # type: ignore[arg-type]
            f_high = float(next_high)   # type: ignore[arg-type]
            f_close = float(next_close) # type: ignore[arg-type]
            f_tc = float(trade_close)   # type: ignore[arg-type]
            f_nor = float(nor)          # type: ignore[arg-type]
            f_ncr = float(ncr)          # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if f_high <= 0 or f_close == 0 or f_tc <= 0:
            continue
        open_vs_high_ratios.append(round(f_open / f_high, 4))
        open_vs_close_ratios.append(round(f_open / f_close, 4))
        early_returns.append(f_nor)
        late_returns.append(f_ncr)
        mid_ret = round((f_high + f_close) / 2.0 / f_tc - 1.0, 4)
        mid_returns.append(mid_ret)

    n = len(early_returns)
    if n == 0:
        return {
            "open_vs_high_ratio_mean": None,
            "open_vs_close_ratio_mean": None,
            "exit_early_median_return": None,
            "exit_late_median_return": None,
            "exit_mid_median_return": None,
            "optimal_exit_window": None,
            "open_significantly_below_high": None,
            "sell_timing_sample_count": 0,
        }

    open_vs_high_mean: float = round(sum(open_vs_high_ratios) / n, 4)
    open_vs_close_mean: float = round(sum(open_vs_close_ratios) / n, 4)
    early_dist = summarize_distribution(early_returns)
    late_dist = summarize_distribution(late_returns)
    mid_dist = summarize_distribution(mid_returns)
    exit_early_median: float | None = early_dist.get("median")
    exit_late_median: float | None = late_dist.get("median")
    exit_mid_median: float | None = mid_dist.get("median")

    # Identify the exit window with the highest median return.
    candidates: dict[str, float] = {}
    if exit_early_median is not None:
        candidates["early"] = exit_early_median
    if exit_mid_median is not None:
        candidates["mid"] = exit_mid_median
    if exit_late_median is not None:
        candidates["late"] = exit_late_median
    optimal_exit_window: str | None = max(candidates, key=candidates.__getitem__) if candidates else None

    open_significantly_below_high: bool | None = bool(open_vs_high_mean < OPEN_VS_HIGH_SIGNIFICANT_DISCOUNT_THRESHOLD)

    return {
        "open_vs_high_ratio_mean": open_vs_high_mean,
        "open_vs_close_ratio_mean": open_vs_close_mean,
        "exit_early_median_return": exit_early_median,
        "exit_late_median_return": exit_late_median,
        "exit_mid_median_return": exit_mid_median,
        "optimal_exit_window": optimal_exit_window,
        "open_significantly_below_high": open_significantly_below_high,
        "sell_timing_sample_count": n,
    }


# ---------------------------------------------------------------------------
# Task 2 (Round 18): Multi-period momentum alignment score (多周期动量一致性)
# ---------------------------------------------------------------------------
# Measures how consistently forward returns are positive across T+1, T+2, and T+3 horizons.
# A high alignment score indicates that BTST candidates are showing genuine multi-day momentum
# (rather than one-day pops that immediately reverse), which makes the breakout signal more
# reliable.  Three alignment tiers are reported:
#
#   full_aligned_rate   — fraction of rows where T+1 > 0 AND T+2 > 0 AND T+3 > 0 (三日连涨)
#   partial_aligned_rate — fraction of rows where at least 2 of the 3 horizons are positive
#   t1_t2_aligned_rate  — fraction of rows where T+1 > 0 AND T+2 > 0 (two-day continuation)
#
# alignment_score ∈ [0, 1]:  weighted average giving more weight to full alignment.
#   formula: (full_aligned_count × 1.0 + t1_t2_only_count × 0.5) / total_count
#
# Only rows with all three forward returns present are included in the denominator, so
# the metric is only available in "closed" evaluation windows.


def compute_multi_period_momentum_alignment(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute multi-period momentum alignment across T+1, T+2, T+3 horizons (Task 2, Round 18).

    Evaluates how consistently the forward return is positive across three consecutive horizons.
    A high ``full_aligned_rate`` (all three days positive) signals genuine multi-day momentum
    — the BTST breakout is continuing rather than reversing after T+1.

    Args:
        rows: BTST candidate rows.  Must contain ``next_close_return`` (T+1),
            ``t_plus_2_close_return`` (T+2), and ``t_plus_3_close_return`` (T+3) for a row
            to be included in the aligned-sample denominator.

    Returns:
        Dict with keys:

        - ``full_aligned_rate`` (float | None): fraction of rows with T+1 > 0 AND T+2 > 0 AND T+3 > 0.
        - ``partial_aligned_rate`` (float | None): fraction where ≥ 2 of 3 horizons positive.
        - ``t1_t2_aligned_rate`` (float | None): fraction where T+1 > 0 AND T+2 > 0 (two-day continuation).
        - ``alignment_score`` (float | None): weighted index ∈ [0, 1]; higher = stronger momentum.
        - ``aligned_sample_count`` (int): rows with all three forward returns present.
        - ``t1_positive_rate`` (float | None): T+1 win rate within the three-horizon sample.
        - ``t2_positive_rate`` (float | None): T+2 win rate within the three-horizon sample.
        - ``t3_positive_rate`` (float | None): T+3 win rate within the three-horizon sample.
    """
    full_aligned: int = 0
    partial_aligned: int = 0
    t1_t2_aligned: int = 0
    t1_positive: int = 0
    t2_positive: int = 0
    t3_positive: int = 0
    total: int = 0

    for row in rows:
        r1 = row.get("next_close_return")
        r2 = row.get("t_plus_2_close_return")
        r3 = row.get("t_plus_3_close_return")
        if r1 is None or r2 is None or r3 is None:
            continue
        try:
            f1 = float(r1)
            f2 = float(r2)
            f3 = float(r3)
        except (TypeError, ValueError):
            continue
        total += 1
        pos1 = f1 > 0.0
        pos2 = f2 > 0.0
        pos3 = f3 > 0.0
        if pos1:
            t1_positive += 1
        if pos2:
            t2_positive += 1
        if pos3:
            t3_positive += 1
        if pos1 and pos2 and pos3:
            full_aligned += 1
        if (pos1 and pos2) or (pos1 and pos3) or (pos2 and pos3):
            partial_aligned += 1
        if pos1 and pos2:
            t1_t2_aligned += 1

    if total == 0:
        return {
            "full_aligned_rate": None,
            "partial_aligned_rate": None,
            "t1_t2_aligned_rate": None,
            "alignment_score": None,
            "aligned_sample_count": 0,
            "t1_positive_rate": None,
            "t2_positive_rate": None,
            "t3_positive_rate": None,
        }

    full_aligned_rate: float = round(full_aligned / total, 4)
    partial_aligned_rate: float = round(partial_aligned / total, 4)
    t1_t2_aligned_rate: float = round(t1_t2_aligned / total, 4)
    t1_positive_rate: float = round(t1_positive / total, 4)
    t2_positive_rate: float = round(t2_positive / total, 4)
    t3_positive_rate: float = round(t3_positive / total, 4)
    # Weighted alignment score: full 3-day alignment counts fully; T+1&T+2 only counts half.
    t1_t2_only_count: int = t1_t2_aligned - full_aligned
    alignment_score: float = round((full_aligned * 1.0 + t1_t2_only_count * 0.5) / total, 4)

    return {
        "full_aligned_rate": full_aligned_rate,
        "partial_aligned_rate": partial_aligned_rate,
        "t1_t2_aligned_rate": t1_t2_aligned_rate,
        "alignment_score": alignment_score,
        "aligned_sample_count": total,
        "t1_positive_rate": t1_positive_rate,
        "t2_positive_rate": t2_positive_rate,
        "t3_positive_rate": t3_positive_rate,
    }


# ---------------------------------------------------------------------------
# Task 3 (Round 18): t0_tail_strength factor stratification (尾盘强度分层验证)
# ---------------------------------------------------------------------------
# Validates the monotonicity hypothesis for the t0_tail_strength factor introduced in R17:
# "高尾盘强度 → 高T+1胜率".  The rows are divided into three quantile strata by t0_tail_strength:
#
#   "low"   — bottom third  (t0_tail_strength < p33)
#   "mid"   — middle third  (p33 ≤ t0_tail_strength < p67)
#   "high"  — top third     (t0_tail_strength ≥ p67)
#
# For each stratum, win rate and payoff ratio (avg_win / avg_loss_abs) are computed and
# surfaced so analysts can confirm that high t0_tail_strength candidates genuinely outperform.
# If monotonicity holds (low_win_rate < mid_win_rate < high_win_rate) ``monotone_win_rate``
# is set to True; similarly for payoff ratios.
_TAIL_STRENGTH_STRATA: tuple[str, ...] = ("low", "mid", "high")


def compute_t0_tail_strength_stratification(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Stratify candidates by t0_tail_strength and compute per-stratum T+1 metrics (Task 3, Round 18).

    Divides rows into three equal-sized strata by t0_tail_strength (low / mid / high third)
    and computes win rate and payoff ratio for each stratum.  Monotonicity flags confirm whether
    higher t0_tail_strength consistently predicts better T+1 outcomes.

    Args:
        rows: BTST candidate rows with both ``t0_tail_strength`` (float ∈ (0, 1]) and
            ``next_close_return`` (float).  Rows missing either field are excluded.

    Returns:
        Dict with keys:

        - ``low`` / ``mid`` / ``high`` (dict): per-stratum statistics with:
            - ``win_rate`` (float | None), ``payoff_ratio`` (float | None),
              ``average_win`` (float | None), ``average_loss_abs`` (float | None), ``count`` (int).
        - ``monotone_win_rate`` (bool | None): True when low < mid < high win rates.
        - ``monotone_payoff_ratio`` (bool | None): True when low < mid < high payoff ratios.
        - ``stratification_sample_count`` (int): total rows with valid tail_strength and return data.
        - ``p33_threshold`` (float | None): 33rd-percentile boundary between low and mid strata.
        - ``p67_threshold`` (float | None): 67th-percentile boundary between mid and high strata.
    """
    paired: list[tuple[float, float]] = []
    for row in rows:
        ts = row.get("t0_tail_strength")
        ncr = row.get("next_close_return")
        if ts is None or ncr is None:
            continue
        try:
            paired.append((float(ts), float(ncr)))
        except (TypeError, ValueError):
            continue

    empty_stratum: dict[str, Any] = {"win_rate": None, "payoff_ratio": None, "average_win": None, "average_loss_abs": None, "count": 0}
    if len(paired) < 3:
        return {
            "low": empty_stratum,
            "mid": empty_stratum,
            "high": empty_stratum,
            "monotone_win_rate": None,
            "monotone_payoff_ratio": None,
            "stratification_sample_count": len(paired),
            "p33_threshold": None,
            "p67_threshold": None,
        }

    sorted_pairs = sorted(paired, key=lambda x: x[0])
    n = len(sorted_pairs)
    # Compute p33 and p67 thresholds from sorted t0_tail_strength values.
    tail_strengths = [p[0] for p in sorted_pairs]

    def _pct(values: list[float], pct: float) -> float:
        max_idx = len(values) - 1
        if max_idx <= 0:
            return round(values[0], 4)
        scaled = max(0.0, min(1.0, pct)) * max_idx
        lo = int(scaled)
        hi = min(max_idx, lo + 1)
        if lo == hi:
            return round(values[lo], 4)
        return round(values[lo] + (values[hi] - values[lo]) * (scaled - lo), 4)

    p33 = _pct(tail_strengths, 1.0 / 3.0)
    p67 = _pct(tail_strengths, 2.0 / 3.0)

    def _stratum_stats(returns: list[float]) -> dict[str, Any]:
        if not returns:
            return dict(empty_stratum)
        wins = [r for r in returns if r > 0.0]
        losses = [r for r in returns if r < 0.0]
        win_rate: float | None = round(len(wins) / len(returns), 4)
        avg_win: float | None = round(sum(wins) / len(wins), 4) if wins else None
        avg_loss_abs: float | None = round(abs(sum(losses) / len(losses)), 4) if losses else None
        payoff: float | None = round(avg_win / avg_loss_abs, 4) if avg_win is not None and avg_loss_abs is not None and avg_loss_abs > 0 else None
        return {"win_rate": win_rate, "payoff_ratio": payoff, "average_win": avg_win, "average_loss_abs": avg_loss_abs, "count": len(returns)}

    low_returns = [r for ts_val, r in sorted_pairs if ts_val < p33]
    mid_returns = [r for ts_val, r in sorted_pairs if p33 <= ts_val < p67]
    high_returns = [r for ts_val, r in sorted_pairs if ts_val >= p67]

    low_stats = _stratum_stats(low_returns)
    mid_stats = _stratum_stats(mid_returns)
    high_stats = _stratum_stats(high_returns)

    low_wr = low_stats["win_rate"]
    mid_wr = mid_stats["win_rate"]
    high_wr = high_stats["win_rate"]
    monotone_win_rate: bool | None = None
    if low_wr is not None and mid_wr is not None and high_wr is not None:
        monotone_win_rate = bool(low_wr < mid_wr < high_wr)

    low_pr = low_stats["payoff_ratio"]
    mid_pr = mid_stats["payoff_ratio"]
    high_pr = high_stats["payoff_ratio"]
    monotone_payoff_ratio: bool | None = None
    if low_pr is not None and mid_pr is not None and high_pr is not None:
        monotone_payoff_ratio = bool(low_pr < mid_pr < high_pr)

    return {
        "low": low_stats,
        "mid": mid_stats,
        "high": high_stats,
        "monotone_win_rate": monotone_win_rate,
        "monotone_payoff_ratio": monotone_payoff_ratio,
        "stratification_sample_count": len(paired),
        "p33_threshold": p33,
        "p67_threshold": p67,
    }


# ---------------------------------------------------------------------------
# Task 1 (Round 19): Sector concentration Gini coefficient (板块集中度基尼系数)
# ---------------------------------------------------------------------------
# Measures how concentrated the candidate pool (or escaped runners) is across sectors.
# A low Gini (near 0) indicates candidates are spread evenly across many sectors, reducing
# correlated-sector risk.  A high Gini (near 1) means most candidates cluster in one sector —
# a single adverse sector event would take down the entire portfolio.
#
# Formula: Gini coefficient of the per-sector count distribution.
#   Sort sector counts ascending: v_1 ≤ v_2 ≤ … ≤ v_k
#   G = (2 × Σ_i i × v_i) / (k × Σ_i v_i) − (k+1)/k
#
# Guardrail cap: sector_concentration_gini ≤ 0.60.
# When fewer than 2 sectors are present (or no industry labels), returns None.


def compute_sector_concentration_gini(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute Gini coefficient of sector (industry) distribution across *rows* (Task 1, Round 19).

    Measures how unevenly candidates are distributed across A-share industry categories.
    A Gini near 0.0 means candidates span many sectors evenly (low concentration risk).
    A Gini near 1.0 means nearly all candidates belong to one sector (high concentration risk).

    The Gini formula used is the standard sorted-values formula:
        G = (2 × Σ_i (rank_i × count_i)) / (k × total) − (k+1)/k
    where counts are sorted ascending, rank_i is 1-based position in that sorted order,
    k = number of distinct sectors, total = sum of all counts.

    Args:
        rows: BTST candidate rows.  Each row should have an ``industry`` (str) field.
            Rows missing the field are silently skipped.

    Returns:
        Dict with keys:

        - ``sector_concentration_gini`` (float | None): Gini ∈ [0, 1]; None when < 2 sectors.
        - ``sector_distribution`` (dict[str, float]): top-10 sectors → fraction of total.
        - ``sector_count`` (int): number of distinct sectors observed.
        - ``sample_count`` (int): rows with a non-empty ``industry`` label.
    """
    from collections import Counter
    industries: list[str] = [str(row["industry"]) for row in rows if row.get("industry")]
    if not industries:
        return {"sector_concentration_gini": None, "sector_distribution": {}, "sector_count": 0, "sample_count": 0}
    counts: Counter[str] = Counter(industries)
    k: int = len(counts)
    total: int = sum(counts.values())
    sector_distribution: dict[str, float] = {sector: round(cnt / total, 4) for sector, cnt in counts.most_common(10)}
    if k < 2:
        # All candidates in one sector → maximum concentration (Gini = 1.0).
        return {"sector_concentration_gini": 1.0, "sector_distribution": sector_distribution, "sector_count": k, "sample_count": len(industries)}
    sorted_counts: list[int] = sorted(counts.values())
    gini_numerator: float = sum((i + 1) * v for i, v in enumerate(sorted_counts))
    gini: float = round((2.0 * gini_numerator / (k * total)) - (k + 1) / k, 4)
    gini = max(0.0, min(1.0, gini))
    return {"sector_concentration_gini": gini, "sector_distribution": sector_distribution, "sector_count": k, "sample_count": len(industries)}


# ---------------------------------------------------------------------------
# Task 3 (Round 19): T+1 intraday high-point timing distribution (高点时间分布分析)
# ---------------------------------------------------------------------------
# Uses T+1 OHLC data to infer when the intraday high price was established.
# Without tick data, we approximate using open/high and close/high ratios:
#
#   early  (9:30–10:30 proxy): next_open / next_high ≥ 0.97
#          → The day opened at or very near the high — price weakened from the open.
#          Implication: BUY AT OPEN to capture the early pop.
#
#   late   (14:00–15:00 proxy): next_close / next_high ≥ 0.97 AND open/high < 0.97
#          → Price strengthened into the close and ended near the high.
#          Implication: Hold to close (or buy on dips intraday); no need to chase at open.
#
#   mid    (10:30–14:00 proxy): all other bars
#          → High established in the middle of the session.
#
# early_dominated (bool): early_fraction > 0.50 → open-execution strategy is optimal.
# late_dominated  (bool): late_fraction > 0.50  → momentum persists into close.
#
# INTRADAY_HIGH_TIMING_THRESHOLD: ratio above which open/close is considered "near" the high.

INTRADAY_HIGH_TIMING_THRESHOLD: float = 0.97  # open or close within 3 % of the day high


def compute_intraday_high_timing_distribution(rows: list[dict[str, Any]], *, threshold: float = INTRADAY_HIGH_TIMING_THRESHOLD) -> dict[str, Any]:
    """Classify T+1 intraday high-point timing into early/mid/late session buckets (Task 3, Round 19).

    Approximates intraday high timing from T+1 OHLC ratios without requiring tick data:

    - **early**: ``next_open / next_high ≥ threshold`` — high set at/near the open.
    - **late**: ``next_close / next_high ≥ threshold`` AND ``next_open / next_high < threshold``
      — high set at/near the close.
    - **mid**: all other rows — high established during the mid-session.

    Args:
        rows: BTST candidate rows.  Must contain ``next_open``, ``next_high``, ``next_close``
            as numeric fields.  Rows missing any of these are skipped.
        threshold: Ratio above which open/close is considered "near" the day high.
            Default :data:`INTRADAY_HIGH_TIMING_THRESHOLD` = 0.97.

    Returns:
        Dict with keys:

        - ``early_fraction`` (float | None): fraction of bars where high set near open.
        - ``mid_fraction`` (float | None): fraction of bars with mid-session high.
        - ``late_fraction`` (float | None): fraction of bars where high set near close.
        - ``early_count``, ``mid_count``, ``late_count`` (int): raw counts.
        - ``sample_count`` (int): total bars included.
        - ``early_dominated`` (bool | None): True when early_fraction > 0.50.
        - ``late_dominated`` (bool | None): True when late_fraction > 0.50.
        - ``threshold_used`` (float): the ratio threshold applied.
    """
    early_count: int = 0
    mid_count: int = 0
    late_count: int = 0
    total: int = 0
    for row in rows:
        raw_open = row.get("next_open")
        raw_high = row.get("next_high")
        raw_close = row.get("next_close")
        if raw_open is None or raw_high is None or raw_close is None:
            continue
        try:
            no: float = float(raw_open)
            nh: float = float(raw_high)
            nc: float = float(raw_close)
        except (TypeError, ValueError):
            continue
        if nh <= 0.0:
            continue
        total += 1
        open_to_high: float = no / nh
        close_to_high: float = nc / nh
        if open_to_high >= threshold:
            early_count += 1
        elif close_to_high >= threshold:
            late_count += 1
        else:
            mid_count += 1
    if total == 0:
        return {"early_fraction": None, "mid_fraction": None, "late_fraction": None, "early_count": 0, "mid_count": 0, "late_count": 0, "sample_count": 0, "early_dominated": None, "late_dominated": None, "threshold_used": round(threshold, 4)}
    ef: float = round(early_count / total, 4)
    mf: float = round(mid_count / total, 4)
    lf: float = round(late_count / total, 4)
    return {"early_fraction": ef, "mid_fraction": mf, "late_fraction": lf, "early_count": early_count, "mid_count": mid_count, "late_count": late_count, "sample_count": total, "early_dominated": ef > 0.50, "late_dominated": lf > 0.50, "threshold_used": round(threshold, 4)}


# ---------------------------------------------------------------------------
# Task 3 (Round 21, Beta): Optimal execution timing signal (最优执行时机信号)
# ---------------------------------------------------------------------------
# Combines T+1 intraday high-timing distribution (R19) with T0 tail-session strength (R17)
# to produce an actionable execution recommendation for each replay window.
#
# open_entry_signal_strength   = early_fraction × median(t0_tail_strength)
# wait_entry_signal_strength   = late_fraction  × (1 − median(t0_tail_strength))
# execution_timing_confidence  = max(early_fraction, late_fraction) − 0.33
# recommended_execution        = "immediate" | "wait" | "uncertain"
#   "immediate" when open_strength − wait_strength > 0.15
#   "wait"      when wait_strength − open_strength > 0.15
#   "uncertain" otherwise


def compute_optimal_entry_signal(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine T+1 high-point timing and T0 tail-session strength into an execution signal.

    Synthesises two Round 19/17 analytics into a single per-window recommendation:

    - **open_entry_signal_strength** (float [0,1]): early_fraction × median(t0_tail_strength).
      High values suggest buying at the T+1 open captures most of the daily move.
    - **wait_entry_signal_strength** (float [0,1]): late_fraction × (1 − median(t0_tail_strength)).
      High values suggest waiting for a mid/late-session confirmation is optimal.
    - **execution_timing_confidence** (float): max(early_fraction, late_fraction) − 0.33.
      Positive when one session bucket clearly dominates random (>33 %).
    - **recommended_execution** (str): ``"immediate"`` | ``"wait"`` | ``"uncertain"``.
      Assigned when the dominant signal exceeds the other by more than 0.15.

    Args:
        rows: BTST candidate rows.  Must contain ``next_open``, ``next_high``, ``next_close``
            (for intraday timing) and ``t0_tail_strength`` (for T0 session strength).
            Rows missing these fields are gracefully skipped.

    Returns:
        Dict with keys ``open_entry_signal_strength``, ``wait_entry_signal_strength``,
        ``execution_timing_confidence``, ``recommended_execution``.  All numeric fields
        are ``None`` when insufficient data is available; ``recommended_execution``
        defaults to ``"uncertain"`` in that case.
    """
    _null_result: dict[str, Any] = {"open_entry_signal_strength": None, "wait_entry_signal_strength": None, "execution_timing_confidence": None, "recommended_execution": "uncertain"}
    timing: dict[str, Any] = compute_intraday_high_timing_distribution(rows)
    early_fraction: float | None = timing.get("early_fraction")
    late_fraction: float | None = timing.get("late_fraction")
    t0_vals: list[float] = [float(row["t0_tail_strength"]) for row in rows if row.get("t0_tail_strength") is not None]
    if early_fraction is None or late_fraction is None or not t0_vals:
        return _null_result
    sorted_t0 = sorted(t0_vals)
    n: int = len(sorted_t0)
    t0_median: float = (sorted_t0[n // 2 - 1] + sorted_t0[n // 2]) / 2.0 if n % 2 == 0 else sorted_t0[n // 2]
    open_strength: float = round(early_fraction * t0_median, 4)
    wait_strength: float = round(late_fraction * (1.0 - t0_median), 4)
    confidence: float = round(max(early_fraction, late_fraction) - 0.33, 4)
    diff: float = open_strength - wait_strength
    recommended: str = "immediate" if diff > 0.15 else ("wait" if diff < -0.15 else "uncertain")
    return {"open_entry_signal_strength": open_strength, "wait_entry_signal_strength": wait_strength, "execution_timing_confidence": confidence, "recommended_execution": recommended}


# ---------------------------------------------------------------------------
# Round 22 — Task 2 (Alpha): Multi-day optimal hold period analysis
# ---------------------------------------------------------------------------
# Compares T+1 / T+2 / T+3 holding periods using a Sharpe-like ratio
# (mean_return / std_return, no risk-free rate adjustment).
# The optimal period is the one with the highest Sharpe-like ratio.
# hold_period_confidence measures how decisively the winner beats the runner-up.


def compute_optimal_hold_period(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare T+1/T+2/T+3 hold periods by Sharpe-like ratio and output the optimal period.

    For each period the Sharpe-like ratio is ``mean_return / std_return`` computed over
    rows that have a valid return for that period.  When fewer than 5 rows are available
    for a period its Sharpe is returned as ``None``.

    Args:
        rows: BTST candidate rows.  Relevant fields:

            - ``next_close_return``        — T+1 close return.
            - ``t_plus_2_close_return``    — T+2 close return.
            - ``t_plus_3_close_return``    — T+3 close return.

    Returns:
        Dict with keys:

        - ``t1_sharpe`` / ``t2_sharpe`` / ``t3_sharpe`` — Sharpe-like ratios (float or None).
        - ``t1_win_rate`` / ``t2_win_rate`` / ``t3_win_rate`` — Win rates (float or None).
        - ``t1_avg_return`` / ``t2_avg_return`` / ``t3_avg_return`` — Mean returns (float or None).
        - ``optimal_hold_days`` — 1, 2, or 3; ``None`` when all periods lack data.
        - ``hold_period_confidence`` — (best_sharpe − second_sharpe) / abs(best_sharpe) clipped to [0, 1]; ``None`` when fewer than two valid Sharpes.
        - ``t1_vs_t2_sharpe_diff`` — t1_sharpe − t2_sharpe (float or None).
        - ``t1_vs_t3_sharpe_diff`` — t1_sharpe − t3_sharpe (float or None).
    """
    _MIN_ROWS: int = 5

    def _period_stats(return_col: str) -> tuple[float | None, float | None, float | None]:
        """Return (sharpe, win_rate, avg_return) for a hold period.  None when < _MIN_ROWS rows."""
        vals: list[float] = [float(row[return_col]) for row in rows if row.get(return_col) is not None]
        if len(vals) < _MIN_ROWS:
            return None, None, None
        n: int = len(vals)
        mean: float = sum(vals) / n
        variance: float = sum((v - mean) ** 2 for v in vals) / (n - 1) if n >= 2 else 0.0
        std: float = variance ** 0.5
        sharpe: float | None = round(mean / std, 4) if std > 1e-9 else (round(mean, 4) if mean != 0.0 else None)
        win_rate: float = round(sum(1 for v in vals if v > 0.0) / n, 4)
        avg_return: float = round(mean, 4)
        return sharpe, win_rate, avg_return

    t1_sharpe, t1_win_rate, t1_avg_return = _period_stats("next_close_return")
    t2_sharpe, t2_win_rate, t2_avg_return = _period_stats("t_plus_2_close_return")
    t3_sharpe, t3_win_rate, t3_avg_return = _period_stats("t_plus_3_close_return")

    candidates: list[tuple[int, float]] = [(days, s) for days, s in ((1, t1_sharpe), (2, t2_sharpe), (3, t3_sharpe)) if s is not None]
    optimal_hold_days: int | None = None
    hold_period_confidence: float | None = None
    if candidates:
        candidates.sort(key=lambda x: x[1], reverse=True)
        optimal_hold_days = candidates[0][0]
        if len(candidates) >= 2:
            best_s: float = candidates[0][1]
            second_s: float = candidates[1][1]
            if abs(best_s) > 1e-9:
                raw_conf: float = (best_s - second_s) / abs(best_s)
                hold_period_confidence = round(max(0.0, min(1.0, raw_conf)), 4)
            else:
                hold_period_confidence = 0.0

    t1_vs_t2_sharpe_diff: float | None = round(t1_sharpe - t2_sharpe, 4) if t1_sharpe is not None and t2_sharpe is not None else None
    t1_vs_t3_sharpe_diff: float | None = round(t1_sharpe - t3_sharpe, 4) if t1_sharpe is not None and t3_sharpe is not None else None

    return {
        "t1_sharpe": t1_sharpe,
        "t2_sharpe": t2_sharpe,
        "t3_sharpe": t3_sharpe,
        "t1_win_rate": t1_win_rate,
        "t2_win_rate": t2_win_rate,
        "t3_win_rate": t3_win_rate,
        "t1_avg_return": t1_avg_return,
        "t2_avg_return": t2_avg_return,
        "t3_avg_return": t3_avg_return,
        "optimal_hold_days": optimal_hold_days,
        "hold_period_confidence": hold_period_confidence,
        "t1_vs_t2_sharpe_diff": t1_vs_t2_sharpe_diff,
        "t1_vs_t3_sharpe_diff": t1_vs_t3_sharpe_diff,
    }


# ---------------------------------------------------------------------------
# Round 22 — Task 3 (Beta): Score percentile position-tier analysis
# ---------------------------------------------------------------------------
# Divides the candidate pool into three tiers by composite score terciles
# (P33 / P67) and computes T+1 win rate and mean payoff per tier.
# tier_monotone_win_rate=True validates that higher scores → higher win rates.


def compute_score_position_tiers(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Stratify rows by runner_composite_score terciles and compute per-tier win rate/payoff.

    Three tiers are formed by the P33 and P67 percentiles of ``runner_composite_score``:

    - **high** tier: score > P67
    - **mid**  tier: P33 ≤ score ≤ P67
    - **low**  tier: score < P33

    Win rate and average payoff (mean ``next_close_return``) are computed per tier.
    A tier needs at least 3 valid rows; otherwise its metrics are ``None``.

    Args:
        rows: BTST candidate rows.  Fields used: ``runner_composite_score`` and
            ``next_close_return``.  Rows missing either field are excluded.

    Returns:
        Dict with keys:

        - ``score_p33`` / ``score_p67``                 — Tercile cut-points (float or None).
        - ``tier_high_win_rate`` / ``tier_high_avg_payoff``
        - ``tier_mid_win_rate``  / ``tier_mid_avg_payoff``
        - ``tier_low_win_rate``  / ``tier_low_avg_payoff``
        - ``tier_monotone_win_rate`` (bool)              — True when high > mid > low win rates.
        - ``tier_win_rate_spread``                       — tier_high_win_rate − tier_low_win_rate (float or None).
        - ``tier_payoff_spread``                         — tier_high_avg_payoff − tier_low_avg_payoff (float or None).
    """
    _MIN_TIER_ROWS: int = 3

    scored_pairs: list[tuple[float, float]] = [
        (float(row["runner_composite_score"]), float(row["next_close_return"]))
        for row in rows
        if row.get("runner_composite_score") is not None and row.get("next_close_return") is not None
    ]

    if not scored_pairs:
        return {"score_p33": None, "score_p67": None, "tier_high_win_rate": None, "tier_high_avg_payoff": None, "tier_mid_win_rate": None, "tier_mid_avg_payoff": None, "tier_low_win_rate": None, "tier_low_avg_payoff": None, "tier_monotone_win_rate": False, "tier_win_rate_spread": None, "tier_payoff_spread": None}

    scores_sorted: list[float] = sorted(s for s, _ in scored_pairs)
    n: int = len(scores_sorted)

    def _percentile(sorted_vals: list[float], p: float) -> float:
        """Linear-interpolated percentile (p in [0,100])."""
        idx: float = (p / 100.0) * (len(sorted_vals) - 1)
        lo: int = int(idx)
        hi: int = min(lo + 1, len(sorted_vals) - 1)
        return sorted_vals[lo] + (idx - lo) * (sorted_vals[hi] - sorted_vals[lo])

    score_p33: float = round(_percentile(scores_sorted, 33.0), 4)
    score_p67: float = round(_percentile(scores_sorted, 67.0), 4)

    high_rets: list[float] = [ret for s, ret in scored_pairs if s > score_p67]
    mid_rets: list[float] = [ret for s, ret in scored_pairs if score_p33 <= s <= score_p67]
    low_rets: list[float] = [ret for s, ret in scored_pairs if s < score_p33]

    def _tier_stats(rets: list[float]) -> tuple[float | None, float | None]:
        if len(rets) < _MIN_TIER_ROWS:
            return None, None
        win_rate: float = round(sum(1 for r in rets if r > 0.0) / len(rets), 4)
        avg_payoff: float = round(sum(rets) / len(rets), 4)
        return win_rate, avg_payoff

    tier_high_win_rate, tier_high_avg_payoff = _tier_stats(high_rets)
    tier_mid_win_rate, tier_mid_avg_payoff = _tier_stats(mid_rets)
    tier_low_win_rate, tier_low_avg_payoff = _tier_stats(low_rets)

    tier_monotone_win_rate: bool = (tier_high_win_rate is not None and tier_mid_win_rate is not None and tier_low_win_rate is not None and tier_high_win_rate > tier_mid_win_rate > tier_low_win_rate)

    tier_win_rate_spread: float | None = round(tier_high_win_rate - tier_low_win_rate, 4) if tier_high_win_rate is not None and tier_low_win_rate is not None else None
    tier_payoff_spread: float | None = round(tier_high_avg_payoff - tier_low_avg_payoff, 4) if tier_high_avg_payoff is not None and tier_low_avg_payoff is not None else None

    return {
        "score_p33": score_p33,
        "score_p67": score_p67,
        "tier_high_win_rate": tier_high_win_rate,
        "tier_high_avg_payoff": tier_high_avg_payoff,
        "tier_mid_win_rate": tier_mid_win_rate,
        "tier_mid_avg_payoff": tier_mid_avg_payoff,
        "tier_low_win_rate": tier_low_win_rate,
        "tier_low_avg_payoff": tier_low_avg_payoff,
        "tier_monotone_win_rate": tier_monotone_win_rate,
        "tier_win_rate_spread": tier_win_rate_spread,
        "tier_payoff_spread": tier_payoff_spread,
    }


# ---------------------------------------------------------------------------
# Task 2 (Round 23, Alpha): Kelly fraction position sizing
# ---------------------------------------------------------------------------
# Translates T+1 win rate and realised payoff ratio into a Kelly-optimal position
# fraction and the more conservative half-Kelly recommendation.  Per-tier (high/low
# composite-score) Kelly fractions are also computed to guide differential sizing.


def compute_kelly_position_fractions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute Kelly and half-Kelly position-sizing fractions from T+1 return distribution.

    Kelly formula: ``f* = (p × b − q) / b = p − q / b``

    where ``p`` = win rate, ``q = 1 − p``, and ``b = avg_win / avg_loss_abs``
    (the realised payoff ratio).  The result is clipped to ``[0, 0.50]``; negative
    Kelly (zero expected value) is set to 0.

    Tier fractions use the P33/P67 ``runner_composite_score`` split so callers can
    size positions larger for high-score candidates.  Rows missing either field are
    excluded from the tier calculation.  A tier requires at least 5 valid rows;
    otherwise its fraction is ``None``.

    Args:
        rows: BTST candidate rows with ``next_close_return`` (required for overall
            Kelly) and optionally ``runner_composite_score`` (required for tier Kelly).

    Returns:
        Dict with keys:

        - ``kelly_fraction_full``      — full Kelly fraction ∈ [0, 0.50].
        - ``kelly_fraction_half``      — half-Kelly (more conservative) = full / 2.
        - ``kelly_fraction_tier_high`` — half-Kelly for P67+ score tier (or ``None``).
        - ``kelly_fraction_tier_low``  — half-Kelly for P33− score tier (or ``None``).
        - ``kelly_positive``           — ``True`` when the strategy has positive expected value.
        - ``kelly_edge``               — raw edge = ``p × b − q`` (un-normalised expected return).
    """
    _MIN_ROWS: int = 5
    _MAX_FRACTION: float = 0.50

    def _kelly_from_returns(rets: list[float]) -> tuple[float, float, float, bool]:
        """Return (kelly_full, kelly_half, edge, kelly_positive) from a return list."""
        if len(rets) < _MIN_ROWS:
            return 0.0, 0.0, 0.0, False
        pos_rets: list[float] = [r for r in rets if r > 0.0]
        neg_abs: list[float] = [abs(r) for r in rets if r <= 0.0]
        p: float = len(pos_rets) / len(rets)
        q: float = 1.0 - p
        avg_win: float = sum(pos_rets) / len(pos_rets) if pos_rets else 0.0
        avg_loss_abs: float = sum(neg_abs) / len(neg_abs) if neg_abs else 0.0
        if avg_win <= 0.0 or avg_loss_abs < 1e-9:
            return 0.0, 0.0, 0.0, False
        b: float = avg_win / avg_loss_abs
        edge: float = round(p * b - q, 4)
        if edge <= 0.0:
            return 0.0, 0.0, edge, False
        kelly_full: float = round(min(edge / b, _MAX_FRACTION), 4)
        kelly_half: float = round(kelly_full / 2.0, 4)
        return kelly_full, kelly_half, edge, True

    # Overall Kelly from all rows with next_close_return.
    all_returns: list[float] = [float(row["next_close_return"]) for row in rows if row.get("next_close_return") is not None]
    kelly_full, kelly_half, kelly_edge, kelly_positive = _kelly_from_returns(all_returns)

    # Tier Kelly — split by runner_composite_score P33/P67.
    kelly_tier_high: float | None = None
    kelly_tier_low: float | None = None
    scored_pairs: list[tuple[float, float]] = [(float(row["runner_composite_score"]), float(row["next_close_return"])) for row in rows if row.get("runner_composite_score") is not None and row.get("next_close_return") is not None]
    if scored_pairs:
        _scores_sorted: list[float] = sorted(s for s, _ in scored_pairs)
        _n: int = len(_scores_sorted)

        def _percentile(p: float) -> float:
            idx: float = (p / 100.0) * (_n - 1)
            lo: int = int(idx)
            hi: int = min(lo + 1, _n - 1)
            return _scores_sorted[lo] + (idx - lo) * (_scores_sorted[hi] - _scores_sorted[lo])

        p33: float = _percentile(33.0)
        p67: float = _percentile(67.0)
        high_rets: list[float] = [ret for s, ret in scored_pairs if s > p67]
        low_rets: list[float] = [ret for s, ret in scored_pairs if s < p33]
        _kf_high, kelly_tier_high, _, _ = _kelly_from_returns(high_rets)  # noqa: F841
        _kf_low, kelly_tier_low, _, _ = _kelly_from_returns(low_rets)  # noqa: F841
        kelly_tier_high = None if not high_rets or len(high_rets) < _MIN_ROWS else kelly_tier_high
        kelly_tier_low = None if not low_rets or len(low_rets) < _MIN_ROWS else kelly_tier_low

    return {
        "kelly_fraction_full": round(kelly_full, 4),
        "kelly_fraction_half": round(kelly_half, 4),
        "kelly_fraction_tier_high": kelly_tier_high,
        "kelly_fraction_tier_low": kelly_tier_low,
        "kelly_positive": kelly_positive,
        "kelly_edge": round(kelly_edge, 4),
    }


# ---------------------------------------------------------------------------
# Task 3 (Round 23, Beta): Regime win-rate consistency check
# ---------------------------------------------------------------------------
# Validates that T+1 win rate is stable across bull / bear / sideways regimes.
# A strategy that achieves 60 % overall but only 20 % in bear markets is fragile
# and unlikely to survive out-of-sample regime shifts.


def compute_regime_consistency_check(rows: list[dict[str, Any]], surface_summary: dict[str, Any]) -> dict[str, Any]:
    """Check cross-regime win-rate stability using the regime_conditional_stats sub-dict.

    Extracts per-regime win rates from ``surface_summary["regime_conditional_stats"]``,
    discards regimes with fewer than ``_MIN_REGIME_COUNT`` rows (data insufficient),
    and computes spread / dispersion metrics.  At least 2 valid regimes are required;
    otherwise all output values are ``None``.

    The ``regime_consistency_score = 1 − regime_win_rate_range`` represents the
    fraction of the [0, 1] win-rate space *not* consumed by cross-regime spread.
    A score ≥ 0.85 is excellent; ≥ 0.70 is the quality floor.

    ``bear_market_win_rate_deficit`` is computed as
    ``overall_win_rate (from rows) − bear regime win rate``.  A large positive
    value (> 0.20) flags heavy bull-market dependency.

    Args:
        rows: BTST candidate rows; used only to compute the overall win rate for
            the ``bear_market_win_rate_deficit`` field.
        surface_summary: Dict containing ``regime_conditional_stats`` as returned
            by :func:`build_regime_conditional_stats` (or wrapped by
            :func:`build_surface_summary`).

    Returns:
        Dict with keys:

        - ``regime_win_rate_range``        — max − min across valid regimes (float or None).
        - ``regime_win_rate_std``          — population std of regime win rates (float or None).
        - ``regime_consistency_score``     — 1 − range ∈ [0, 1]; higher = more stable.
        - ``worst_regime``                 — name of regime with lowest win rate.
        - ``worst_regime_win_rate``        — win rate of the worst regime.
        - ``regime_robustness_flag``       — True when range < 0.15 (strong robustness).
        - ``bear_market_win_rate_deficit`` — overall_win_rate − bear_win_rate (float or None).
    """
    _NULL: dict[str, Any] = {"regime_win_rate_range": None, "regime_win_rate_std": None, "regime_consistency_score": None, "worst_regime": None, "worst_regime_win_rate": None, "regime_robustness_flag": None, "bear_market_win_rate_deficit": None}
    _MIN_REGIME_COUNT: int = 5
    _ROBUSTNESS_RANGE_THRESHOLD: float = 0.15

    regime_stats: dict[str, Any] = surface_summary.get("regime_conditional_stats", {})
    if not regime_stats:
        return _NULL

    regime_win_rates: dict[str, float] = {}
    for regime in ("bull", "bear", "sideways"):
        data = regime_stats.get(regime, {})
        count: int = int(data.get("count") or 0)
        win_rate = data.get("next_close_positive_rate")
        if count >= _MIN_REGIME_COUNT and win_rate is not None:
            try:
                regime_win_rates[regime] = float(win_rate)
            except (TypeError, ValueError):
                pass

    if len(regime_win_rates) < 2:
        return _NULL

    wr_values: list[float] = list(regime_win_rates.values())
    wr_range: float = round(max(wr_values) - min(wr_values), 4)
    wr_mean: float = sum(wr_values) / len(wr_values)
    wr_std: float = round((sum((v - wr_mean) ** 2 for v in wr_values) / len(wr_values)) ** 0.5, 4)
    consistency_score: float = round(max(0.0, 1.0 - wr_range), 4)
    worst_regime: str = min(regime_win_rates, key=lambda k: regime_win_rates[k])
    worst_regime_win_rate: float = round(regime_win_rates[worst_regime], 4)
    robustness_flag: bool = wr_range < _ROBUSTNESS_RANGE_THRESHOLD

    # Bear-market deficit vs overall win rate (computed directly from rows).
    bear_deficit: float | None = None
    all_returns: list[float] = [float(row["next_close_return"]) for row in rows if row.get("next_close_return") is not None]
    if all_returns:
        overall_wr: float = sum(1 for r in all_returns if r > 0.0) / len(all_returns)
        bear_wr = regime_win_rates.get("bear")
        if bear_wr is not None:
            bear_deficit = round(overall_wr - bear_wr, 4)

    return {
        "regime_win_rate_range": wr_range,
        "regime_win_rate_std": wr_std,
        "regime_consistency_score": consistency_score,
        "worst_regime": worst_regime,
        "worst_regime_win_rate": worst_regime_win_rate,
        "regime_robustness_flag": robustness_flag,
        "bear_market_win_rate_deficit": bear_deficit,
    }


# ---------------------------------------------------------------------------
# Task 2 (Round 24): Drawdown-adjusted Kelly fraction
# ---------------------------------------------------------------------------
# Applies a severity-based penalty to ``kelly_fraction_half`` derived from
# the T+1 intraday drawdown P10.  Strategies with severe intraday drawdown
# risk should use a reduced position size even when Kelly says otherwise.


def compute_drawdown_adjusted_kelly(
    next_day_rows: list[dict[str, Any]],
    surface_summary: dict[str, Any],
) -> dict[str, Any]:
    """Round 24, Task 2: Adjust Kelly fraction by T+1 intraday drawdown risk.

    Penalises ``kelly_fraction_half`` when the T+1 intraday drawdown P10 is
    severely negative.  The adjustment_factor shrinks as drawdown severity
    increases, reducing recommended position size in volatile regimes.

    Risk levels are derived from ``t_plus_1_intraday_drawdown_p10``:
    - low:      p10 > −0.02 → no reduction
    - moderate: p10 ∈ [−0.05, −0.02) → mild reduction
    - high:     p10 ∈ [−0.08, −0.05) → significant reduction
    - severe:   p10 < −0.08 → large reduction

    Formula: ``severity = max(0, −p10 / 0.05)``;
    ``adjustment_factor = 1 / (1 + severity)``;
    ``kelly_fraction_drawdown_adjusted = clip(kelly_half × adjustment_factor, 0, 0.50)``.

    Quality floor: ``kelly_fraction_drawdown_adjusted ≥ 0.01``.

    Args:
        next_day_rows: Per-row next-day outcome data (unused; kept for signature consistency).
        surface_summary: Dict containing ``kelly_fraction_half`` and
            ``t_plus_1_intraday_drawdown_p10`` from the same window.

    Returns:
        Dict with keys ``kelly_fraction_drawdown_adjusted``,
        ``drawdown_adjustment_factor``, ``drawdown_kelly_vs_base_diff``,
        and ``drawdown_risk_level``.  All numeric keys are ``None`` when
        either input is missing.
    """
    _null: dict[str, Any] = {
        "kelly_fraction_drawdown_adjusted": None,
        "drawdown_adjustment_factor": None,
        "drawdown_kelly_vs_base_diff": None,
        "drawdown_risk_level": None,
    }
    raw_kelly = surface_summary.get("kelly_fraction_half")
    raw_p10 = surface_summary.get("t_plus_1_intraday_drawdown_p10")
    if raw_kelly is None or raw_p10 is None:
        return _null
    try:
        kelly_half_f = float(raw_kelly)
        p10_f = float(raw_p10)
    except (TypeError, ValueError):
        return _null
    if p10_f > -0.02:
        risk_level = "low"
    elif p10_f >= -0.05:
        risk_level = "moderate"
    elif p10_f >= -0.08:
        risk_level = "high"
    else:
        risk_level = "severe"
    severity = max(0.0, -p10_f / 0.05)
    adjustment_factor = 1.0 / (1.0 + severity)
    adjusted_kelly = min(0.50, max(0.0, kelly_half_f * adjustment_factor))
    diff = round(adjusted_kelly - kelly_half_f, 4)
    return {
        "kelly_fraction_drawdown_adjusted": round(adjusted_kelly, 4),
        "drawdown_adjustment_factor": round(adjustment_factor, 4),
        "drawdown_kelly_vs_base_diff": diff,
        "drawdown_risk_level": risk_level,
    }


# ---------------------------------------------------------------------------
# Task 2 (Round 26, Gamma): Benchmark-adjusted Alpha vs HS300
# ---------------------------------------------------------------------------
# Computes BTST strategy Alpha relative to the HS300 (沪深300) index benchmark.
# Raw win rate and return can be inflated during broad market rallies (pure Beta).
# This function decomposes the excess return into alpha (skill) vs beta (market).


def compute_benchmark_adjusted_alpha(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute Alpha, beta exposure, and information ratio relative to HS300 benchmark.

    Uses ``next_close_return`` as the BTST daily return and ``hs300_daily_return`` as the
    benchmark.  When ``hs300_daily_return`` is absent from all rows the function returns a
    degraded dict with most fields set to ``None``.

    Args:
        rows: List of row dicts, each optionally containing ``next_close_return`` and
            ``hs300_daily_return`` fields.

    Returns:
        Dict with keys:
        - ``benchmark_mean_return``: mean HS300 daily return (float or None).
        - ``alpha_avg_return``: mean(next_close_return − hs300_daily_return).
        - ``alpha_win_rate``: fraction of rows where BTST > HS300.
        - ``alpha_sharpe``: alpha_avg / std(alpha_series) — risk-adjusted excess return.
        - ``beta_exposure``: cov(btst, hs300) / var(hs300) — market sensitivity proxy.
        - ``information_ratio``: alpha_avg / tracking_error (tracking_error = std(alpha)).
        - ``outperform_bull_rate``: BTST > HS300 fraction on bull days (hs300 > 0.3 %).
        - ``outperform_bear_rate``: BTST > HS300 fraction on bear days (hs300 < −0.3 %).
    """
    _BULL_THRESHOLD: float = 0.003
    _BEAR_THRESHOLD: float = -0.003

    paired: list[tuple[float, float]] = []
    for row in rows:
        btst_ret = row.get("next_close_return")
        bm_ret = row.get("hs300_daily_return")
        if btst_ret is not None and bm_ret is not None:
            try:
                paired.append((float(btst_ret), float(bm_ret)))
            except (TypeError, ValueError):
                continue

    if not paired:
        return {
            "benchmark_mean_return": None,
            "alpha_avg_return": None,
            "alpha_win_rate": None,
            "alpha_sharpe": None,
            "beta_exposure": None,
            "information_ratio": None,
            "outperform_bull_rate": None,
            "outperform_bear_rate": None,
        }

    btst_rets: list[float] = [p[0] for p in paired]
    bm_rets: list[float] = [p[1] for p in paired]
    n: int = len(paired)
    alpha_series: list[float] = [b - m for b, m in paired]

    benchmark_mean: float = round(sum(bm_rets) / n, 6)
    alpha_avg: float = round(sum(alpha_series) / n, 6)
    alpha_win_rate: float = round(sum(1 for a in alpha_series if a > 0.0) / n, 4)

    # Tracking error and alpha Sharpe/IR
    if n >= 2:
        alpha_mean = sum(alpha_series) / n
        alpha_var = sum((a - alpha_mean) ** 2 for a in alpha_series) / (n - 1)
        tracking_error: float = alpha_var ** 0.5
        alpha_sharpe: float | None = round(alpha_avg / tracking_error, 4) if tracking_error > 1e-9 else None
        information_ratio: float | None = alpha_sharpe  # same formula (alpha / TE)
    else:
        tracking_error = 0.0
        alpha_sharpe = None
        information_ratio = None

    # Beta exposure: cov(btst, bm) / var(bm)
    if n >= 2:
        btst_mean = sum(btst_rets) / n
        bm_mean = sum(bm_rets) / n
        cov = sum((btst_rets[i] - btst_mean) * (bm_rets[i] - bm_mean) for i in range(n)) / (n - 1)
        bm_var = sum((v - bm_mean) ** 2 for v in bm_rets) / (n - 1)
        beta_exposure: float | None = round(cov / bm_var, 4) if bm_var > 1e-12 else 1.0
    else:
        beta_exposure = None

    # Conditional outperformance rates
    bull_days: list[float] = [alpha_series[i] for i, bm in enumerate(bm_rets) if bm > _BULL_THRESHOLD]
    bear_days: list[float] = [alpha_series[i] for i, bm in enumerate(bm_rets) if bm < _BEAR_THRESHOLD]
    outperform_bull_rate: float | None = round(sum(1 for a in bull_days if a > 0.0) / len(bull_days), 4) if bull_days else None
    outperform_bear_rate: float | None = round(sum(1 for a in bear_days if a > 0.0) / len(bear_days), 4) if bear_days else None

    return {
        "benchmark_mean_return": benchmark_mean,
        "alpha_avg_return": alpha_avg,
        "alpha_win_rate": alpha_win_rate,
        "alpha_sharpe": alpha_sharpe,
        "beta_exposure": beta_exposure,
        "information_ratio": information_ratio,
        "outperform_bull_rate": outperform_bull_rate,
        "outperform_bear_rate": outperform_bear_rate,
    }


# ---------------------------------------------------------------------------
# Task 3 (Round 26, Beta): Dynamic stop-loss threshold suggestion
# ---------------------------------------------------------------------------
# Uses the already-computed stop_loss_trigger_rate_2/3/5pct metrics from Round 15
# to recommend the optimal stop-loss level that balances protection vs. premature exit.


def compute_dynamic_stop_loss_suggestion(surface_summary: dict[str, Any]) -> dict[str, Any]:
    """Suggest an optimal stop-loss percentage based on observed trigger-rate data.

    Reads ``stop_loss_trigger_rate_2pct``, ``stop_loss_trigger_rate_3pct``, and
    ``stop_loss_trigger_rate_5pct`` from *surface_summary*.  When these fields are absent the
    function returns a safe default (3 % stop, confidence="low").

    Decision rules (applied in order):
    1. ``stop_loss_trigger_rate_2pct < 0.10``  → 2 % stop is viable (rare hit, high protection).
    2. ``stop_loss_trigger_rate_3pct < 0.20``  → 3 % stop is acceptable (moderate hit rate).
    3. ``stop_loss_trigger_rate_5pct > 0.35``  → 5 % stop triggers too often; tighten to 3 %.
    4. Default fallback: 3 % stop with low confidence.

    Args:
        surface_summary: Surface summary dict as returned by ``build_surface_summary``.

    Returns:
        Dict with keys:
        - ``suggested_stop_loss_pct``: float — recommended stop-loss (0.02 / 0.03 / 0.05).
        - ``stop_loss_confidence``: str — "high" | "medium" | "low".
        - ``stop_loss_rationale``: str — human-readable reason.
        - ``tight_stop_viable``: bool — 2 % stop viable (trigger_rate_2pct < 10 %).
        - ``loose_stop_warned``: bool — 5 % stop triggers too often (trigger_rate_5pct > 35 %).
        - ``optimal_stop_trigger_rate``: float | None — observed trigger rate for suggested stop.
    """
    r2: float | None = surface_summary.get("stop_loss_trigger_rate_2pct")
    r3: float | None = surface_summary.get("stop_loss_trigger_rate_3pct")
    r5: float | None = surface_summary.get("stop_loss_trigger_rate_5pct")

    if r2 is None and r3 is None and r5 is None:
        return {
            "suggested_stop_loss_pct": 0.03,
            "stop_loss_confidence": "low",
            "stop_loss_rationale": "No stop-loss trigger data available; defaulting to 3% stop-loss.",
            "tight_stop_viable": False,
            "loose_stop_warned": False,
            "optimal_stop_trigger_rate": None,
        }

    tight_stop_viable: bool = r2 is not None and r2 < 0.10
    loose_stop_warned: bool = r5 is not None and r5 > 0.35

    if tight_stop_viable:
        return {
            "suggested_stop_loss_pct": 0.02,
            "stop_loss_confidence": "high",
            "stop_loss_rationale": f"2% stop viable: trigger rate {r2:.1%} < 10%; tight stop preserves capital without excessive false exits.",
            "tight_stop_viable": True,
            "loose_stop_warned": loose_stop_warned,
            "optimal_stop_trigger_rate": r2,
        }

    if r3 is not None and r3 < 0.20:
        confidence = "medium" if not loose_stop_warned else "medium"
        rationale = f"3% stop acceptable: trigger rate {r3:.1%} < 20%."
        if loose_stop_warned:
            rationale += f" 5% stop warned (trigger rate {r5:.1%} > 35%)."
        return {
            "suggested_stop_loss_pct": 0.03,
            "stop_loss_confidence": confidence,
            "stop_loss_rationale": rationale,
            "tight_stop_viable": False,
            "loose_stop_warned": loose_stop_warned,
            "optimal_stop_trigger_rate": r3,
        }

    if loose_stop_warned:
        return {
            "suggested_stop_loss_pct": 0.03,
            "stop_loss_confidence": "medium",
            "stop_loss_rationale": f"5% stop too permissive (trigger rate {r5:.1%} > 35%); tightening to 3% stop.",
            "tight_stop_viable": False,
            "loose_stop_warned": True,
            "optimal_stop_trigger_rate": r3,
        }

    # Fallback: suggest 3 % with low confidence when rates are ambiguous
    return {
        "suggested_stop_loss_pct": 0.03,
        "stop_loss_confidence": "low",
        "stop_loss_rationale": "Stop-loss trigger rates ambiguous; defaulting to 3% stop-loss.",
        "tight_stop_viable": False,
        "loose_stop_warned": False,
        "optimal_stop_trigger_rate": r3,
    }


# ---------------------------------------------------------------------------
# Task 1 (Round 27, Alpha): Return distribution shape — skewness and tail asymmetry
# ---------------------------------------------------------------------------


def compute_return_distribution_shape(rows: list[dict]) -> dict:
    """计算T+1收益分布的高阶统计特征（偏度与尾部非对称性）。

    Requires at least 5 rows with a valid ``next_close_return`` field.  When fewer observations
    are available all numeric outputs are ``None`` and the flag is ``False``.

    Args:
        rows: BTST candidate rows.  Field used: ``next_close_return``.

    Returns:
        Dict with keys:
        - ``next_close_return_skewness``: float — sample skewness (negative = left-skewed / fat left tail).
        - ``next_close_return_downside_std``: float — std of negative returns only.
        - ``next_close_return_upside_std``: float — std of positive returns only.
        - ``win_loss_std_ratio``: float | None — upside_std / downside_std (>1 = favourable asymmetry).
        - ``return_p5``: float — 5th-percentile return (proxy for extreme loss).
        - ``return_p95``: float — 95th-percentile return (proxy for extreme gain).
        - ``return_iqr``: float — P75 − P25 (dispersion of middle 50 %).
        - ``heavy_left_tail_flag``: bool — True when skewness < −1.0 AND return_p5 < −0.05.
    """
    rets: list[float] = [float(row["next_close_return"]) for row in rows if row.get("next_close_return") is not None]
    n: int = len(rets)
    _null: dict = {"next_close_return_skewness": None, "next_close_return_downside_std": None, "next_close_return_upside_std": None, "win_loss_std_ratio": None, "return_p5": None, "return_p95": None, "return_iqr": None, "heavy_left_tail_flag": False}
    if n < 5:
        return _null

    # Sample mean and std.
    mean_r: float = sum(rets) / n
    variance: float = sum((x - mean_r) ** 2 for x in rets) / (n - 1)  # sample variance
    std_r: float = variance ** 0.5
    if std_r == 0.0:
        return _null

    # Sample skewness: Fisher-Pearson bias-corrected formula n/((n-1)(n-2)) * Σ((x-mean)/std)^3.
    if n < 3:
        skewness = 0.0
    else:
        skewness: float = round((n / ((n - 1) * (n - 2))) * sum(((x - mean_r) / std_r) ** 3 for x in rets), 4)

    # Downside / upside std (over raw values to preserve distributional meaning).
    neg_rets: list[float] = [x for x in rets if x < 0]
    pos_rets: list[float] = [x for x in rets if x > 0]
    downside_std: float | None = None
    upside_std: float | None = None
    if len(neg_rets) >= 2:
        neg_mean = sum(neg_rets) / len(neg_rets)
        downside_std = round((sum((x - neg_mean) ** 2 for x in neg_rets) / (len(neg_rets) - 1)) ** 0.5, 6)
    if len(pos_rets) >= 2:
        pos_mean = sum(pos_rets) / len(pos_rets)
        upside_std = round((sum((x - pos_mean) ** 2 for x in pos_rets) / (len(pos_rets) - 1)) ** 0.5, 6)

    win_loss_std_ratio: float | None = round(upside_std / downside_std, 4) if (upside_std is not None and downside_std is not None and downside_std > 0.0) else None

    # Percentile helpers (linear interpolation).
    sorted_r = sorted(rets)

    def _percentile(data: list[float], pct: float) -> float:
        """Return the pct-th percentile (0–100) via linear interpolation."""
        if len(data) == 1:
            return data[0]
        idx = pct / 100.0 * (len(data) - 1)
        lo = int(idx)
        hi = lo + 1
        if hi >= len(data):
            return data[-1]
        return data[lo] + (idx - lo) * (data[hi] - data[lo])

    return_p5: float = round(_percentile(sorted_r, 5), 6)
    return_p95: float = round(_percentile(sorted_r, 95), 6)
    return_p25: float = _percentile(sorted_r, 25)
    return_p75: float = _percentile(sorted_r, 75)
    return_iqr: float = round(return_p75 - return_p25, 6)
    heavy_left_tail_flag: bool = (skewness < -1.0) and (return_p5 < -0.05)

    return {
        "next_close_return_skewness": skewness,
        "next_close_return_downside_std": downside_std,
        "next_close_return_upside_std": upside_std,
        "win_loss_std_ratio": win_loss_std_ratio,
        "return_p5": return_p5,
        "return_p95": return_p95,
        "return_iqr": return_iqr,
        "heavy_left_tail_flag": heavy_left_tail_flag,
    }


# ---------------------------------------------------------------------------
# Task 2 (Round 27, Gamma): Composite score discrimination power analysis
# ---------------------------------------------------------------------------


def compute_score_discrimination_power(rows: list[dict]) -> dict:
    """量化composite score对T+1收益的区分力（spread宽度 × Spearman相关）。

    Requires at least 5 rows with a valid ``runner_composite_score`` field.  When the field
    is absent or fewer observations are available, all numeric outputs are ``None``.

    Args:
        rows: BTST candidate rows.  Fields used: ``runner_composite_score`` and optionally
            ``next_close_return`` for the Spearman correlation.

    Returns:
        Dict with keys:
        - ``score_spread_p95_p5``: float — P95 − P5 of composite scores (distribution width).
        - ``score_iqr``: float — P75 − P25 (middle-50 % dispersion).
        - ``score_above_60_fraction``: float — fraction of scores > 0.60.
        - ``score_above_70_fraction``: float — fraction of scores > 0.70.
        - ``score_return_spearman``: float | None — Spearman rank correlation between score and T+1 return.
        - ``score_discrimination_index``: float — score_spread_p95_p5 × |score_return_spearman|.
        - ``low_discrimination_flag``: bool — spread < 0.20 OR |spearman| < 0.05.
    """
    _null: dict = {"score_spread_p95_p5": None, "score_iqr": None, "score_above_60_fraction": None, "score_above_70_fraction": None, "score_return_spearman": None, "score_discrimination_index": None, "low_discrimination_flag": True}
    # Check that field exists in at least one row.
    if not any(row.get("runner_composite_score") is not None for row in rows):
        return _null

    scored_rows = [row for row in rows if row.get("runner_composite_score") is not None]
    n: int = len(scored_rows)
    if n < 5:
        return _null

    scores: list[float] = [float(row["runner_composite_score"]) for row in scored_rows]

    def _pct(data: list[float], p: float) -> float:
        sd = sorted(data)
        idx = p / 100.0 * (len(sd) - 1)
        lo = int(idx)
        hi = lo + 1
        if hi >= len(sd):
            return sd[-1]
        return sd[lo] + (idx - lo) * (sd[hi] - sd[lo])

    score_p5: float = _pct(scores, 5)
    score_p25: float = _pct(scores, 25)
    score_p75: float = _pct(scores, 75)
    score_p95: float = _pct(scores, 95)
    score_spread_p95_p5: float = round(score_p95 - score_p5, 4)
    score_iqr: float = round(score_p75 - score_p25, 4)
    score_above_60_fraction: float = round(sum(1 for s in scores if s > 0.60) / n, 4)
    score_above_70_fraction: float = round(sum(1 for s in scores if s > 0.70) / n, 4)

    # Spearman correlation with T+1 return (requires next_close_return co-availability).
    paired_scores: list[float] = []
    paired_returns: list[float] = []
    for row in scored_rows:
        if row.get("next_close_return") is not None:
            paired_scores.append(float(row["runner_composite_score"]))
            paired_returns.append(float(row["next_close_return"]))

    score_return_spearman: float | None = _spearman_corr(paired_scores, paired_returns)

    score_discrimination_index: float = round(score_spread_p95_p5 * abs(score_return_spearman), 4) if score_return_spearman is not None else round(score_spread_p95_p5 * 0.0, 4)

    abs_spearman: float = abs(score_return_spearman) if score_return_spearman is not None else 0.0
    low_discrimination_flag: bool = (score_spread_p95_p5 < 0.20) or (abs_spearman < 0.05)

    return {
        "score_spread_p95_p5": score_spread_p95_p5,
        "score_iqr": score_iqr,
        "score_above_60_fraction": score_above_60_fraction,
        "score_above_70_fraction": score_above_70_fraction,
        "score_return_spearman": score_return_spearman,
        "score_discrimination_index": score_discrimination_index,
        "low_discrimination_flag": low_discrimination_flag,
    }


# ---------------------------------------------------------------------------
# Task 3 (Round 27, Beta): Liquidity-aware position guidance
# ---------------------------------------------------------------------------


def compute_liquidity_position_guidance(surface_summary: dict[str, Any]) -> dict[str, Any]:
    """基于流动性（候选池大小）给出仓位分散化建议。

    Reads ``avg_candidate_pool_size``, ``scarce_market_window_count``, and
    ``market_size_classification`` from *surface_summary*.  Falls back to a pool size of 50
    (medium) when ``avg_candidate_pool_size`` is absent.

    Args:
        surface_summary: Surface summary dict (output of ``build_surface_summary`` or
            walk-forward aggregate).  May include the R14 candidate-pool fields.

    Returns:
        Dict with keys:
        - ``recommended_max_positions``: int — max(1, min(10, floor(avg_pool / 10))).
        - ``recommended_position_size_pct``: float — min(0.20, 1.0 / recommended_max_positions).
        - ``concentration_risk_level``: str — "low" | "medium" | "high" | "extreme".
        - ``diversification_feasible``: bool — recommended_max_positions >= 3.
        - ``pool_size_stability``: str — "stable" | "variable" | "scarce".
    """
    import math
    avg_pool: float = float(surface_summary["avg_candidate_pool_size"]) if surface_summary.get("avg_candidate_pool_size") is not None else 50.0
    scarce_count: int = int(surface_summary.get("scarce_market_window_count") or 0)
    market_class: str = str(surface_summary.get("market_size_classification") or "unknown")

    recommended_max_positions: int = max(1, min(10, math.floor(avg_pool / 10)))
    recommended_position_size_pct: float = round(min(0.20, 1.0 / recommended_max_positions), 4)

    if avg_pool > 100:
        concentration_risk_level = "low"
    elif avg_pool >= 50:
        concentration_risk_level = "medium"
    elif avg_pool >= 20:
        concentration_risk_level = "high"
    else:
        concentration_risk_level = "extreme"

    diversification_feasible: bool = recommended_max_positions >= 3

    # pool_size_stability: derive from scarce_market_window_count / total tracked windows.
    # market_size_classification from R14: "scarce_dominated" / "abundant_dominated" / "mixed" / "unknown".
    if market_class == "scarce_dominated":
        pool_size_stability = "scarce"
    elif market_class == "abundant_dominated":
        pool_size_stability = "stable"
    elif market_class == "mixed":
        pool_size_stability = "variable"
    else:
        # Fallback: use scarce_count as a heuristic — if it's non-zero, variable; else stable.
        pool_size_stability = "variable" if scarce_count > 0 else "stable"

    return {
        "recommended_max_positions": recommended_max_positions,
        "recommended_position_size_pct": recommended_position_size_pct,
        "concentration_risk_level": concentration_risk_level,
        "diversification_feasible": diversification_feasible,
        "pool_size_stability": pool_size_stability,
    }


def build_surface_summary(rows: list[dict[str, Any]], *, next_high_hit_threshold: float) -> dict[str, Any]:
    next_day_rows = [row for row in rows if row.get("next_close_return") is not None]
    closed_rows = [row for row in rows if row.get("t_plus_2_close_return") is not None]
    t_plus_3_rows = [row for row in rows if row.get("t_plus_3_close_return") is not None]

    next_open_returns = [float(row["next_open_return"]) for row in next_day_rows if row.get("next_open_return") is not None]
    next_high_returns = [float(row["next_high_return"]) for row in next_day_rows if row.get("next_high_return") is not None]
    next_close_returns = [float(row["next_close_return"]) for row in next_day_rows if row.get("next_close_return") is not None]
    next_open_to_close_returns = [float(row["next_open_to_close_return"]) for row in next_day_rows if row.get("next_open_to_close_return") is not None]
    t_plus_2_close_returns = [float(row["t_plus_2_close_return"]) for row in closed_rows if row.get("t_plus_2_close_return") is not None]
    t_plus_3_close_returns = [float(row["t_plus_3_close_return"]) for row in t_plus_3_rows if row.get("t_plus_3_close_return") is not None]

    # Task 1 (Round 12): T+1 intraday drawdown = low / open − 1 for the next trading day.
    # Negative values indicate the stock fell below the open intraday (adverse excursion).
    # P10 represents the worst-10th-percentile intraday dip and acts as a tail-risk floor.
    next_intraday_drawdown_values = [float(row["next_intraday_drawdown"]) for row in next_day_rows if row.get("next_intraday_drawdown") is not None]
    t_plus_1_intraday_drawdown_p10 = summarize_distribution(next_intraday_drawdown_values).get("p10") if next_intraday_drawdown_values else None
    # Task 2 (Round 13): T+1 next-close return excess kurtosis — measures fat-tailedness of the
    # return distribution.  High excess kurtosis (> 5) signals that extreme wins/losses drive most
    # of the apparent edge, severely over-stating strategy robustness.  Guardrail cap: kurtosis ≤ 5.
    next_close_return_kurtosis = compute_excess_kurtosis(next_close_returns)

    next_high_hits = sum(1 for value in next_high_returns if value >= next_high_hit_threshold)
    next_close_positive = sum(1 for value in next_close_returns if value > 0)
    t_plus_2_positive = sum(1 for value in t_plus_2_close_returns if value > 0)
    t_plus_3_positive = sum(1 for value in t_plus_3_close_returns if value > 0)
    next_close_edge = _build_return_edge_metrics(next_close_returns)
    t_plus_2_edge = _build_return_edge_metrics(t_plus_2_close_returns)
    t_plus_3_edge = _build_return_edge_metrics(t_plus_3_close_returns)

    runner_rows = [row for row in rows if row.get("max_future_high_return_2_5d") is not None]
    runner_capture_count = sum(1 for row in runner_rows if bool(row.get("future_high_hit_20pct_2_5d")))
    runner_hit_rate = None if not runner_rows else round(runner_capture_count / len(runner_rows), 4)
    time_to_hit_values = [float(row["time_to_hit_20pct"]) for row in runner_rows if row.get("time_to_hit_20pct") is not None]

    escaped_rows = [row for row in rows if str(row.get("runner_escape") or "") == "pass"]
    runner_escape_rate = round(len(escaped_rows) / len(rows), 4) if rows else None
    escaped_scores = [float(row["runner_composite_score"]) for row in escaped_rows if row.get("runner_composite_score") is not None]
    avg_composite_score_escaped = round(sum(escaped_scores) / len(escaped_scores), 4) if escaped_scores else None
    # Task 1 (Round 13): escape gap cost — average T+1 open return for escaped runner rows.
    # Measures the execution premium (or discount) experienced when entering escaped runners at the T+1 open.
    # A very negative value indicates the strategy is selecting runners that gap DOWN on T+1 open (limit-up
    # reversal risk).  Guardrail floor: avg_escape_gap_cost >= -0.03 prevents promoting strategies where
    # escaped runners systematically open more than 3 % below the prior-day close.
    escaped_open_returns = [float(row["next_open_return"]) for row in escaped_rows if row.get("next_open_return") is not None]
    avg_escape_gap_cost = round(sum(escaped_open_returns) / len(escaped_open_returns), 4) if escaped_open_returns else None
    # Task 3 (Round 11): pool-level average composite score — includes ALL candidates (not just escaped
    # ones).  A high runner_escape_rate combined with a low candidate_pool_avg_composite_score indicates
    # "矮子里拔将军" (best of a bad lot) — the optimizer uses this as an optional quality guardrail.
    all_composite_scores = [float(row["runner_composite_score"]) for row in rows if row.get("runner_composite_score") is not None]
    candidate_pool_avg_composite_score = round(sum(all_composite_scores) / len(all_composite_scores), 4) if all_composite_scores else None

    # Task 1 (Round 10) — factor IC vs forward returns
    factor_ic_next_close = compute_all_factor_ics(next_day_rows, "next_close_return")
    factor_ic_t_plus_2 = compute_all_factor_ics(closed_rows, "t_plus_2_close_return")
    factor_ic_t_plus_3 = compute_all_factor_ics(t_plus_3_rows, "t_plus_3_close_return")
    # Task 3 (Round 12): IC weight suggestions — use T+1 ICs as primary signal since that
    # is the most data-rich horizon; written to the surface so the optimizer can surface them.
    ic_weight_suggestions = compute_ic_weight_suggestions(factor_ic_next_close)
    # Task 5 (Round 14): regime-conditional backtesting — classify each trading day as bull/bear/sideways
    # based on that day's average next_close_return, then compute per-regime win rate and payoff ratio.
    # This lets the optimizer identify which market environment the strategy works best in.
    regime_conditional_stats = build_regime_conditional_stats(rows)
    # Task 2 (Round 26, Gamma): benchmark-adjusted Alpha vs HS300.
    # Decomposes BTST returns into Alpha (skill) and Beta (market co-movement).
    # Requires hs300_daily_return field in rows; degrades gracefully when absent.
    _benchmark_alpha: dict[str, Any] = compute_benchmark_adjusted_alpha(next_day_rows)
    # Task 4 (Round 15): stop-loss trigger rates at -2 %, -3 %, -5 % from T+1 open.
    # Uses next_intraday_drawdown (T+1 low/open − 1) to model stop-loss hits.
    stop_loss_trigger_rates = compute_stop_loss_trigger_rates(next_intraday_drawdown_values)
    # Task 5 (Round 15): cross-day momentum autocorrelation (Spearman lag-1).
    # Negative T+1→T+2 correlation flags mean-reversion risk for multi-day holds.
    _t1_rets = [float(row["next_close_return"]) for row in closed_rows if row.get("next_close_return") is not None]
    _t2_rets = [float(row["t_plus_2_close_return"]) for row in closed_rows if row.get("t_plus_2_close_return") is not None]
    _t3_rets = [float(row["t_plus_3_close_return"]) for row in t_plus_3_rows if row.get("t_plus_3_close_return") is not None]
    cross_day_autocorrelation = compute_cross_day_autocorrelation(_t1_rets, _t2_rets, _t3_rets)
    # Task 2 (Round 15): opening-gap continuation rate — how often stocks that gap up ≥ 2 %
    # at T+1 open continue to rise intraday (next_open_to_close_return > 0).
    gap_continuation_stats = compute_gap_continuation_rate(next_day_rows)

    # -----------------------------------------------------------------------
    # Task 1 (Round 16): T0 net inflow ratio — IC-tracked buying pressure factor.
    # Factor values are spread directly into rows from extract_btst_price_outcome;
    # IC is auto-computed via compute_all_factor_ics (t0_estimated_net_inflow_ratio is in
    # BTST_FACTOR_NAMES since Round 16).
    # Task 2 (Round 16): volume-price divergence — bar-structure reversal risk.
    # volume_price_divergence_flag fires on 假阳线 (false breakout) bars: price up ≥ 2 %
    # but upper shadow > 45 % of range.  volume_price_divergence_rate > 0.30 in the
    # surface warns that many candidates are forming weak breakout candles.
    # Task 3 (Round 16): T0 predicted range pct — single-bar volatility proxy.
    # t0_predicted_range_pct = (high − low) / open for the trade day.
    # Linked to stop_loss: when p75 > 4 % AND stop_loss_3pct rate > 25 %, issues a
    # combined volatility / stop-out warning.
    # -----------------------------------------------------------------------
    _t0_inflow_values: list[float] = [float(row["t0_estimated_net_inflow_ratio"]) for row in next_day_rows if row.get("t0_estimated_net_inflow_ratio") is not None]
    _vp_div_flags: list[bool] = [bool(row["volume_price_divergence_flag"]) for row in next_day_rows if row.get("volume_price_divergence_flag") is not None]
    _vp_div_scores: list[float] = [float(row["volume_price_divergence_score"]) for row in next_day_rows if row.get("volume_price_divergence_score") is not None]
    _t0_range_pcts: list[float] = [float(row["t0_predicted_range_pct"]) for row in next_day_rows if row.get("t0_predicted_range_pct") is not None]
    volume_price_divergence_rate: float | None = round(sum(_vp_div_flags) / len(_vp_div_flags), 4) if _vp_div_flags else None
    t0_predicted_range_distribution: dict[str, Any] = summarize_distribution(_t0_range_pcts)
    _range_stop_linkage: dict[str, Any] = compute_predicted_range_stop_loss_linkage(_t0_range_pcts, stop_loss_trigger_rates.get("stop_loss_3pct"))

    # -----------------------------------------------------------------------
    # Round 17 analytics — wired into build_surface_summary.
    # -----------------------------------------------------------------------
    # Task 1 (Round 17): breakout freshness conditional win rate.
    # Computes T+1 win rate for rows where breakout_freshness ≥ 0.5 vs < 0.5.
    # A positive lift confirms that the breakout signal has incremental predictive
    # power beyond the base win rate.
    breakout_conditional_win_rate: dict[str, Any] = compute_breakout_conditional_win_rate(next_day_rows)
    # Task 2 (Round 17): T0 tail-session strength distribution.
    # t0_tail_strength = close/high on trade day; IC auto-computed via compute_all_factor_ics
    # since "t0_tail_strength" is in BTST_FACTOR_NAMES from Round 17.
    _t0_tail_strength_values: list[float] = [float(row["t0_tail_strength"]) for row in next_day_rows if row.get("t0_tail_strength") is not None]
    # Task 3 (Round 17): sell-timing optimisation.
    # Uses T+1 OHLC to identify whether early/mid/late exit maximises median return.
    sell_timing_analysis: dict[str, Any] = compute_sell_timing_analysis(next_day_rows)

    # -----------------------------------------------------------------------
    # Round 18 analytics — wired into build_surface_summary.
    # -----------------------------------------------------------------------
    # Task 2 (Round 18): Multi-period momentum alignment score.
    # Measures how consistently T+1, T+2, T+3 forward returns are all positive.
    # full_aligned_rate = fraction of rows with T+1>0 AND T+2>0 AND T+3>0.
    # alignment_score ∈ [0,1]: weighted index giving full credit for 3-day alignment.
    multi_period_momentum_alignment: dict[str, Any] = compute_multi_period_momentum_alignment(t_plus_3_rows)
    # Task 3 (Round 18): t0_tail_strength stratification (尾盘强度分层验证).
    # Divides rows into low/mid/high t0_tail_strength thirds and computes T+1 win rate
    # and payoff ratio per stratum.  monotone_win_rate=True validates the R17 factor hypothesis.
    t0_tail_strength_stratification: dict[str, Any] = compute_t0_tail_strength_stratification(next_day_rows)

    # -----------------------------------------------------------------------
    # Round 19 analytics — wired into build_surface_summary.
    # -----------------------------------------------------------------------
    # Task 1 (Round 19): Sector concentration Gini coefficient (板块集中度基尼系数).
    # Measures how concentrated the candidate pool is across A-share industry categories.
    # Gini ≈ 0 → diversified across sectors.  Gini → 1 → nearly all from one sector.
    # Guardrail cap: sector_concentration_gini ≤ 0.60 (enforced in BTST_QUALITY_CAPS).
    sector_concentration_result: dict[str, Any] = compute_sector_concentration_gini(rows)
    # Task 3 (Round 19): T+1 intraday high-point timing distribution (高点时间分布).
    # Classifies each T+1 bar into early/mid/late session based on open/high and close/high ratios.
    # early_dominated=True → buy-at-open execution is optimal for this window.
    # late_dominated=True  → momentum persists into close; chase is viable.
    intraday_high_timing: dict[str, Any] = compute_intraday_high_timing_distribution(next_day_rows)

    # -----------------------------------------------------------------------
    # Round 22 analytics — wired into build_surface_summary.
    # -----------------------------------------------------------------------
    # Task 2 (Round 22, Alpha): Multi-day optimal hold period analysis.
    # Compares T+1/T+2/T+3 Sharpe-like ratios and identifies the optimal hold period.
    _optimal_hold_period: dict[str, Any] = compute_optimal_hold_period(rows)
    # Task 3 (Round 22, Beta): Score percentile position-tier stratification.
    # Divides the candidate pool into low/mid/high composite score terciles.
    _score_position_tiers: dict[str, Any] = compute_score_position_tiers(next_day_rows)

    # -----------------------------------------------------------------------
    # Round 23 analytics — wired into build_surface_summary.
    # -----------------------------------------------------------------------
    # Task 2 (Round 23, Alpha): Kelly fraction position-sizing recommendations.
    # Translates T+1 win rate and realised payoff ratio into full-Kelly and half-Kelly
    # position fractions.  Tier fractions use P33/P67 composite-score splits.
    # Quality floor: kelly_fraction_half ≥ 0.02 (strategy has positive edge).
    _kelly_fractions: dict[str, Any] = compute_kelly_position_fractions(next_day_rows)
    # Task 3 (Round 23, Beta): Regime win-rate consistency check.
    # Compares T+1 win rate across bull/bear/sideways regimes to flag bull-market dependency.
    # regime_consistency_score = 1 − regime_win_rate_range; floor ≥ 0.70.
    _regime_consistency: dict[str, Any] = compute_regime_consistency_check(rows, {"regime_conditional_stats": regime_conditional_stats})
    # -----------------------------------------------------------------------
    # Round 24 analytics — wired into build_surface_summary.
    # -----------------------------------------------------------------------
    # Task 2 (Round 24): Drawdown-adjusted Kelly fraction.
    # Applies a severity penalty to kelly_fraction_half based on t_plus_1_intraday_drawdown_p10.
    # Quality floor: kelly_fraction_drawdown_adjusted ≥ 0.01 (strategy retains positive edge
    # even after accounting for intraday adverse excursion risk).
    _drawdown_adjusted_kelly: dict[str, Any] = compute_drawdown_adjusted_kelly(
        next_day_rows,
        {"kelly_fraction_half": _kelly_fractions.get("kelly_fraction_half"), "t_plus_1_intraday_drawdown_p10": t_plus_1_intraday_drawdown_p10},
    )

    # -----------------------------------------------------------------------
    # Round 21 analytics — wired into build_surface_summary.
    # -----------------------------------------------------------------------
    # Task 3 (Round 21, Beta): Optimal execution timing signal.
    # Combines intraday high-timing (R19) and T0 tail-session strength (R17) into
    # a per-window actionable execution recommendation.
    # open_entry_signal_strength: early_fraction × median(t0_tail_strength).
    # wait_entry_signal_strength: late_fraction × (1 − median(t0_tail_strength)).
    # execution_timing_confidence: max(early_fraction, late_fraction) − 0.33.
    # recommended_execution: "immediate" | "wait" | "uncertain".
    _optimal_entry_signal: dict[str, Any] = compute_optimal_entry_signal(next_day_rows)

    # -----------------------------------------------------------------------
    # Round 20 analytics — wired into build_surface_summary.
    # -----------------------------------------------------------------------
    # Task 1 (Round 20, Beta): Realized payoff ratio — win_avg_return / abs(loss_avg_return).
    # Explicitly named standalone metric for the core execution quality KPI.
    # win_avg_return: mean return of positive-return rows (same as next_close_edge["average_win"]).
    # loss_avg_return: mean return of negative-return rows (negative value, sign-preserved).
    # realized_payoff_ratio: win_avg_return / abs(loss_avg_return); NaN/default 2.0 when no loss samples.
    # Quality floor: realized_payoff_ratio ≥ 1.0 (wins must exceed losses on a per-trade basis).
    _win_avg_return: float | None = next_close_edge["average_win"]
    _loss_avg_return_abs: float | None = next_close_edge["average_loss_abs"]
    _loss_avg_return: float | None = (-_loss_avg_return_abs) if _loss_avg_return_abs is not None else None
    _realized_payoff_ratio: float | None = next_close_edge["payoff_ratio"]  # = average_win / average_loss_abs

    # Task 2 (Round 20, Alpha): High-confidence selection rate and score-weighted win rate.
    # Validates whether composite_score has predictive power by stratifying on score level.
    # high_confidence_selection_rate: fraction of total rows where runner_composite_score ≥ 0.65.
    # score_weighted_win_rate: sum(score_i × outcome_i) / sum(score_i) — more stable than simple win rate.
    # score_win_rate_lift: score_weighted_win_rate − simple_win_rate; positive lift validates scoring.
    # high_confidence_win_rate: win rate restricted to composite_score ≥ 0.65 rows (min 5 samples).
    _HIGH_CONFIDENCE_SCORE_THRESHOLD: float = 0.65
    _score_return_pairs: list[tuple[float, float]] = [
        (float(row["runner_composite_score"]), float(row["next_close_return"]))
        for row in next_day_rows
        if row.get("runner_composite_score") is not None and row.get("next_close_return") is not None
    ]
    _total_score_sum: float = sum(s for s, _ in _score_return_pairs)
    _score_weighted_win_rate: float | None
    if _total_score_sum > 0.0 and _score_return_pairs:
        _score_weighted_win_rate = round(sum(s for s, ret in _score_return_pairs if ret > 0.0) / _total_score_sum, 4)
    else:
        _score_weighted_win_rate = None
    _simple_win_rate: float | None = (round(next_close_positive / len(next_day_rows), 4) if next_day_rows else None)
    _score_win_rate_lift: float | None = (round(_score_weighted_win_rate - _simple_win_rate, 4) if _score_weighted_win_rate is not None and _simple_win_rate is not None else None)
    _hc_rows: list[dict[str, Any]] = [row for row in next_day_rows if row.get("runner_composite_score") is not None and float(row["runner_composite_score"]) >= _HIGH_CONFIDENCE_SCORE_THRESHOLD]
    _hc_returns: list[float] = [float(row["next_close_return"]) for row in _hc_rows if row.get("next_close_return") is not None]
    _high_confidence_selection_rate: float | None = (round(len(_hc_rows) / len(rows), 4) if rows else None)
    _high_confidence_win_rate: float | None
    if len(_hc_returns) >= 5:
        _high_confidence_win_rate = round(sum(1 for r in _hc_returns if r > 0.0) / len(_hc_returns), 4)
    else:
        _high_confidence_win_rate = None

    # Task 3 (Round 20, Gamma): Consecutive limit-up identification and risk statistics (连板识别).
    # A股连板股（连续涨停）有完全不同的风险特征.
    # Approximation: t_minus_1_return ≥ 0.095 AND t_minus_2_return ≥ 0.095.
    # Fallback when prior-day return fields absent: breakout_freshness ≥ 0.80 as proxy for recent limit-up.
    # consecutive_limit_up_rate: fraction of total rows classified as consecutive limit-up.
    # limit_up_win_rate: T+1 win rate for limit-up subset (NaN if < 3 samples).
    # limit_up_avg_payoff: mean T+1 next_close_return for limit-up subset.
    # non_limit_up_win_rate: T+1 win rate for non-limit-up subset.
    # limit_up_risk_premium: limit_up_avg_payoff − non_limit_up_win_rate × avg_win (approximate).
    def _is_consecutive_limit_up_row(row: dict[str, Any]) -> bool | None:
        """Return True if the row is a consecutive limit-up candidate; None if data missing."""
        t1 = row.get("t_minus_1_return")
        t2 = row.get("t_minus_2_return")
        if t1 is not None and t2 is not None:
            try:
                return float(t1) >= 0.095 and float(t2) >= 0.095
            except (TypeError, ValueError):
                return None
        # Fallback proxy: breakout_freshness ≥ 0.80 suggests recent limit-up momentum.
        bf = row.get("breakout_freshness")
        if bf is not None:
            try:
                return float(bf) >= 0.80
            except (TypeError, ValueError):
                return None
        return None

    _limit_up_classified: list[tuple[bool, float | None]] = []  # (is_limit_up, next_close_return or None)
    for _row in next_day_rows:
        _flag = _is_consecutive_limit_up_row(_row)
        if _flag is None:
            continue
        try:
            _ncr_val: float | None = float(_row["next_close_return"]) if _row.get("next_close_return") is not None else None
        except (TypeError, ValueError):
            _ncr_val = None
        _limit_up_classified.append((_flag, _ncr_val))

    _lu_rows_returns: list[float] = [r for is_lu, r in _limit_up_classified if is_lu and r is not None]  # type: ignore[misc]
    _non_lu_rows_returns: list[float] = [r for is_lu, r in _limit_up_classified if not is_lu and r is not None]  # type: ignore[misc]

    _consecutive_limit_up_rate: float | None
    if rows and _limit_up_classified:
        _consecutive_limit_up_rate = round(sum(1 for is_lu, _ in _limit_up_classified if is_lu) / len(rows), 4)
    else:
        _consecutive_limit_up_rate = None

    _limit_up_win_rate: float | None
    _limit_up_avg_payoff: float | None
    if len(_lu_rows_returns) >= 3:
        _limit_up_win_rate = round(sum(1 for r in _lu_rows_returns if r > 0.0) / len(_lu_rows_returns), 4)
        _limit_up_avg_payoff = round(sum(_lu_rows_returns) / len(_lu_rows_returns), 4)
    else:
        _limit_up_win_rate = None
        _limit_up_avg_payoff = None

    _non_limit_up_win_rate: float | None
    if len(_non_lu_rows_returns) >= 3:
        _non_limit_up_win_rate = round(sum(1 for r in _non_lu_rows_returns if r > 0.0) / len(_non_lu_rows_returns), 4)
    else:
        _non_limit_up_win_rate = None

    # limit_up_risk_premium ≈ limit_up_avg_payoff − non_limit_up_win_rate × avg_win
    # Measures whether limit-up stocks deliver excess return vs the baseline expected payoff.
    _limit_up_risk_premium: float | None
    if _limit_up_avg_payoff is not None and _non_limit_up_win_rate is not None and _win_avg_return is not None:
        _limit_up_risk_premium = round(_limit_up_avg_payoff - _non_limit_up_win_rate * _win_avg_return, 4)
    else:
        _limit_up_risk_premium = None

    _surface_result: dict[str, Any] = {
        "total_count": len(rows),
        # Task 2 (Round 14): explicit candidate_pool_size (= total_count) for walk-forward pool tracking.
        "candidate_pool_size": len(rows),
        "next_day_available_count": len(next_day_rows),
        "closed_cycle_count": len(closed_rows),
        "t_plus_3_cycle_count": len(t_plus_3_rows),
        "next_open_return_distribution": summarize_distribution(next_open_returns),
        "next_high_return_distribution": summarize_distribution(next_high_returns),
        "next_close_return_distribution": summarize_distribution(next_close_returns),
        "next_open_to_close_return_distribution": summarize_distribution(next_open_to_close_returns),
        "t_plus_2_close_return_distribution": summarize_distribution(t_plus_2_close_returns),
        "t_plus_3_close_return_distribution": summarize_distribution(t_plus_3_close_returns),
        "next_high_hit_threshold": round(next_high_hit_threshold, 4),
        "next_high_hit_rate_at_threshold": None if not next_day_rows else round(next_high_hits / len(next_day_rows), 4),
        "next_close_positive_rate": None if not next_day_rows else round(next_close_positive / len(next_day_rows), 4),
        "t_plus_2_close_positive_rate": None if not closed_rows else round(t_plus_2_positive / len(closed_rows), 4),
        "t_plus_3_close_positive_rate": None if not t_plus_3_rows else round(t_plus_3_positive / len(t_plus_3_rows), 4),
        "next_close_positive_count": int(next_close_edge["positive_count"]),
        "next_close_negative_count": int(next_close_edge["negative_count"]),
        "next_close_average_win": next_close_edge["average_win"],
        "next_close_average_loss_abs": next_close_edge["average_loss_abs"],
        "next_close_payoff_ratio": next_close_edge["payoff_ratio"],
        "next_close_profit_factor": next_close_edge["profit_factor"],
        "next_close_expectancy": next_close_edge["expectancy"],
        "t_plus_2_close_positive_count": int(t_plus_2_edge["positive_count"]),
        "t_plus_2_close_negative_count": int(t_plus_2_edge["negative_count"]),
        "t_plus_2_close_average_win": t_plus_2_edge["average_win"],
        "t_plus_2_close_average_loss_abs": t_plus_2_edge["average_loss_abs"],
        "t_plus_2_close_payoff_ratio": t_plus_2_edge["payoff_ratio"],
        "t_plus_2_close_profit_factor": t_plus_2_edge["profit_factor"],
        "t_plus_2_close_expectancy": t_plus_2_edge["expectancy"],
        "t_plus_3_close_positive_count": int(t_plus_3_edge["positive_count"]),
        "t_plus_3_close_negative_count": int(t_plus_3_edge["negative_count"]),
        "t_plus_3_close_average_win": t_plus_3_edge["average_win"],
        "t_plus_3_close_average_loss_abs": t_plus_3_edge["average_loss_abs"],
        "t_plus_3_close_payoff_ratio": t_plus_3_edge["payoff_ratio"],
        "t_plus_3_close_profit_factor": t_plus_3_edge["profit_factor"],
        "t_plus_3_close_expectancy": t_plus_3_edge["expectancy"],
        "runner_capture_count": runner_capture_count,
        "max_future_high_return_2_5d_hit_rate_at_20pct": runner_hit_rate,
        "max_future_high_return_2_5d_distribution": summarize_distribution([float(row["max_future_high_return_2_5d"]) for row in runner_rows]),
        "time_to_hit_20pct_median": summarize_distribution(time_to_hit_values)["median"] if time_to_hit_values else None,
        "runner_escape_rate": runner_escape_rate,
        "avg_composite_score_escaped": avg_composite_score_escaped,
        # Task 1 (Round 13): escape gap cost — avg T+1 open return for escaped runner rows.
        # A negative value indicates runners systematically gap down on the next open (limit-up reversal risk).
        "avg_escape_gap_cost": avg_escape_gap_cost,
        # Task 3 (Round 11): pool-level quality
        "candidate_pool_avg_composite_score": candidate_pool_avg_composite_score,
        # Task 1 (Round 12): T+1 intraday drawdown (open-to-low) tail-risk metric
        "t_plus_1_intraday_drawdown_p10": t_plus_1_intraday_drawdown_p10,
        "next_intraday_drawdown_distribution": summarize_distribution(next_intraday_drawdown_values),
        # Task 2 (Round 13): T+1 next-close return excess kurtosis — fat-tail distributional guardrail.
        "next_close_return_kurtosis": next_close_return_kurtosis,
        # Task 1 (Round 10) — factor IC vs forward returns
        "factor_ic_next_close": factor_ic_next_close,
        "factor_ic_t_plus_2": factor_ic_t_plus_2,
        "factor_ic_t_plus_3": factor_ic_t_plus_3,
        # Task 3 (Round 12): per-factor IC weight adjustment suggestions
        "ic_weight_suggestions": ic_weight_suggestions,
        # Task 5 (Round 14): regime-conditional stats — per-regime win rate, payoff ratio, and day count.
        "regime_conditional_stats": regime_conditional_stats,
        # Task 4 (Round 15): stop-loss trigger rates at −2 %, −3 %, −5 % from T+1 open.
        # stop_loss_2pct/3pct/5pct = fraction of bars where T+1 intraday low breached that level.
        "stop_loss_trigger_rates": stop_loss_trigger_rates,
        "stop_loss_trigger_rate_2pct": stop_loss_trigger_rates.get("stop_loss_2pct"),
        "stop_loss_trigger_rate_3pct": stop_loss_trigger_rates.get("stop_loss_3pct"),
        "stop_loss_trigger_rate_5pct": stop_loss_trigger_rates.get("stop_loss_5pct"),
        # Task 5 (Round 15): cross-day return autocorrelation — Spearman lag-1 between T+1↔T+2 and T+2↔T+3.
        # t1_vs_t2 < 0 signals mean-reversion risk; t1_vs_t2_mean_reversion_flag=True activates the warning.
        "cross_day_autocorrelation": cross_day_autocorrelation,
        "cross_day_autocorr_t1_vs_t2": cross_day_autocorrelation.get("t1_vs_t2"),
        "cross_day_autocorr_t2_vs_t3": cross_day_autocorrelation.get("t2_vs_t3"),
        "cross_day_t1_mean_reversion_flag": cross_day_autocorrelation.get("t1_vs_t2_mean_reversion_flag"),
        # Task 2 (Round 15): gap-up continuation rate — fraction of ≥2 % open-gap bars that continue intraday.
        # A high rate (≥ 0.50) supports "buy at open" execution; a low rate suggests waiting for confirmation.
        "gap_continuation_stats": gap_continuation_stats,
        "gap_continuation_rate": gap_continuation_stats.get("gap_continuation_rate"),
        # Task 1 (Round 16): T0 net inflow ratio distribution — IC-tracked buying pressure on trade day.
        # ic_next_close for this factor is captured in factor_ic_next_close under "t0_estimated_net_inflow_ratio".
        "t0_estimated_net_inflow_ratio_distribution": summarize_distribution(_t0_inflow_values),
        # Task 2 (Round 16): volume-price divergence — bar-structure reversal risk signal.
        # volume_price_divergence_rate: fraction of bars flagged as 假阳线 (false breakout).
        # volume_price_divergence_score_distribution: spread of reversal risk scores.
        "volume_price_divergence_rate": volume_price_divergence_rate,
        "volume_price_divergence_score_distribution": summarize_distribution(_vp_div_scores),
        # Task 3 (Round 16): T0 predicted range pct — single-bar volatility proxy + stop_loss linkage.
        # t0_predicted_range_pct_distribution: distribution of T0 bar ranges across the window.
        # high_volatility_warning_rate: fraction of bars where range > 4 % (high-vol sessions).
        # predicted_range_pct_p75: 75th-percentile T0 range — key percentile for regime assessment.
        # predicted_range_stop_loss_warning: joint flag (p75 > 4 % AND stop_loss_3pct > 25 %).
        "t0_predicted_range_pct_distribution": t0_predicted_range_distribution,
        "high_volatility_warning_rate": _range_stop_linkage.get("high_volatility_warning_rate"),
        "predicted_range_pct_p75": _range_stop_linkage.get("predicted_range_pct_p75"),
        "predicted_range_stop_loss_warning": _range_stop_linkage.get("predicted_range_stop_loss_warning"),
        # -----------------------------------------------------------------------
        # Round 17 analytics
        # -----------------------------------------------------------------------
        # Task 1 (Round 17): breakout freshness conditional win rate.
        # breakout_conditional_win_rate: sub-dict with win_rate_breakout, win_rate_non_breakout, lift,
        # breakout_sample_count, non_breakout_sample_count, breakout_threshold_used.
        # A positive lift confirms that breakout_freshness has incremental signal quality beyond
        # the base win rate for this window.
        "breakout_conditional_win_rate": breakout_conditional_win_rate,
        # Task 2 (Round 17): T0 tail-session strength distribution.
        # t0_tail_strength = trade_close / trade_high for each candidate row.
        # Values near 1.0 indicate strong late-session buying (尾盘接近最高价收盘).
        # IC is tracked in factor_ic_next_close["t0_tail_strength"].
        "t0_tail_strength_distribution": summarize_distribution(_t0_tail_strength_values),
        # Task 3 (Round 17): sell-timing optimisation analysis.
        # optimal_exit_window ("early"/"mid"/"late") and supporting ratios computed from T+1 OHLC.
        # open_significantly_below_high=True implies limit orders above the open capture material alpha.
        "sell_timing_analysis": sell_timing_analysis,
        "optimal_exit_window": sell_timing_analysis.get("optimal_exit_window"),
        "open_vs_high_ratio_mean": sell_timing_analysis.get("open_vs_high_ratio_mean"),
        "open_significantly_below_high": sell_timing_analysis.get("open_significantly_below_high"),
        # -----------------------------------------------------------------------
        # Round 18 analytics
        # -----------------------------------------------------------------------
        # Task 2 (Round 18): multi-period momentum alignment score.
        # full_aligned_rate: fraction of rows with T+1 > 0 AND T+2 > 0 AND T+3 > 0 (三日连涨).
        # alignment_score: weighted index ∈ [0, 1] — full credit for 3-day, half for T+1&T+2 only.
        # aligned_sample_count: rows with all three horizons available (denominator).
        "multi_period_momentum_alignment": multi_period_momentum_alignment,
        "multi_period_full_aligned_rate": multi_period_momentum_alignment.get("full_aligned_rate"),
        "multi_period_alignment_score": multi_period_momentum_alignment.get("alignment_score"),
        "multi_period_aligned_sample_count": multi_period_momentum_alignment.get("aligned_sample_count"),
        # Task 3 (Round 18): t0_tail_strength stratification (尾盘强度分层验证).
        # Per-stratum (low/mid/high t0_tail_strength thirds) win rate and payoff ratio.
        # monotone_win_rate=True validates the hypothesis that high t0_tail_strength → high T+1 win rate.
        "t0_tail_strength_stratification": t0_tail_strength_stratification,
        "t0_tail_strength_monotone_win_rate": t0_tail_strength_stratification.get("monotone_win_rate"),
        "t0_tail_strength_monotone_payoff_ratio": t0_tail_strength_stratification.get("monotone_payoff_ratio"),
        # -----------------------------------------------------------------------
        # Round 19 analytics
        # -----------------------------------------------------------------------
        # Task 1 (Round 19): sector concentration Gini.
        # sector_concentration_gini ∈ [0, 1]; cap guardrail ≤ 0.60 in BTST_QUALITY_CAPS.
        # sector_distribution: top-10 sectors with their fraction of the candidate pool.
        "sector_concentration_gini_result": sector_concentration_result,
        "sector_concentration_gini": sector_concentration_result.get("sector_concentration_gini"),
        "sector_distribution": sector_concentration_result.get("sector_distribution", {}),
        "sector_count": sector_concentration_result.get("sector_count"),
        # Task 3 (Round 19): T+1 intraday high-point timing distribution.
        # early_fraction: fraction of bars where the high was set near the open (>97% open/high).
        # late_fraction: fraction of bars where the high was set near the close (>97% close/high).
        # early_dominated: True when early_fraction > 0.50 → buy-at-open execution is optimal.
        # late_dominated: True when late_fraction > 0.50 → momentum persists into close.
        "intraday_high_timing": intraday_high_timing,
        "high_timing_early_fraction": intraday_high_timing.get("early_fraction"),
        "high_timing_mid_fraction": intraday_high_timing.get("mid_fraction"),
        "high_timing_late_fraction": intraday_high_timing.get("late_fraction"),
        "high_timing_early_dominated": intraday_high_timing.get("early_dominated"),
        "high_timing_late_dominated": intraday_high_timing.get("late_dominated"),
        # -----------------------------------------------------------------------
        # Round 20 analytics
        # -----------------------------------------------------------------------
        # Task 1 (Round 20, Beta): realized payoff ratio — explicit win/loss asymmetry KPI.
        # win_avg_return: mean next_close_return for winning rows (positive value).
        # loss_avg_return: mean next_close_return for losing rows (negative value, sign-preserved).
        # realized_payoff_ratio: win_avg_return / abs(loss_avg_return); quality floor ≥ 1.0.
        "win_avg_return": _win_avg_return,
        "loss_avg_return": _loss_avg_return,
        "realized_payoff_ratio": _realized_payoff_ratio,
        # Task 2 (Round 20, Alpha): score-conditioned win rate metrics.
        # high_confidence_selection_rate: fraction of rows with runner_composite_score ≥ 0.65.
        # score_weighted_win_rate: score-weighted win rate — more stable estimator than simple rate.
        # score_win_rate_lift: score_weighted_win_rate − simple_win_rate (positive = score has value).
        # high_confidence_win_rate: win rate restricted to high-confidence subset (min 5 samples).
        "high_confidence_selection_rate": _high_confidence_selection_rate,
        "score_weighted_win_rate": _score_weighted_win_rate,
        "score_win_rate_lift": _score_win_rate_lift,
        "high_confidence_win_rate": _high_confidence_win_rate,
        # Task 3 (Round 20, Gamma): consecutive limit-up (连板) identification and risk statistics.
        # Uses t_minus_1_return/t_minus_2_return ≥ 0.095 when available; falls back to breakout_freshness ≥ 0.80.
        # consecutive_limit_up_rate: fraction of total rows classified as consecutive limit-up.
        # limit_up_win_rate: T+1 win rate for limit-up subset (NaN if < 3 samples).
        # limit_up_avg_payoff: mean T+1 next_close_return for limit-up subset.
        # non_limit_up_win_rate: T+1 win rate for non-limit-up subset.
        # limit_up_risk_premium: limit_up_avg_payoff − non_limit_up_win_rate × avg_win (approximate).
        "consecutive_limit_up_rate": _consecutive_limit_up_rate,
        "limit_up_win_rate": _limit_up_win_rate,
        "limit_up_avg_payoff": _limit_up_avg_payoff,
        "non_limit_up_win_rate": _non_limit_up_win_rate,
        "limit_up_risk_premium": _limit_up_risk_premium,
        # -----------------------------------------------------------------------
        # Round 21 analytics
        # -----------------------------------------------------------------------
        # Task 3 (Round 21, Beta): Optimal execution timing signal.
        # open_entry_signal_strength: early_fraction × median(t0_tail_strength).
        # wait_entry_signal_strength: late_fraction × (1 − median(t0_tail_strength)).
        # execution_timing_confidence: max(early_fraction, late_fraction) − 0.33.
        # recommended_execution: "immediate" | "wait" | "uncertain".
        "optimal_entry_signal": _optimal_entry_signal,
        "open_entry_signal_strength": _optimal_entry_signal.get("open_entry_signal_strength"),
        "wait_entry_signal_strength": _optimal_entry_signal.get("wait_entry_signal_strength"),
        "execution_timing_confidence": _optimal_entry_signal.get("execution_timing_confidence"),
        "recommended_execution": _optimal_entry_signal.get("recommended_execution"),
        # -----------------------------------------------------------------------
        # Round 22 analytics
        # -----------------------------------------------------------------------
        # Task 2 (Round 22, Alpha): multi-day optimal hold period.
        # t1_sharpe/t2_sharpe/t3_sharpe: Sharpe-like ratio (mean/std) for each hold period.
        # optimal_hold_days: period (1/2/3) with the highest Sharpe-like ratio.
        # hold_period_confidence: relative advantage of winner over runner-up.
        # t1_vs_t2_sharpe_diff / t1_vs_t3_sharpe_diff: direct Sharpe comparisons.
        "optimal_hold_period": _optimal_hold_period,
        "t1_sharpe": _optimal_hold_period.get("t1_sharpe"),
        "t2_sharpe": _optimal_hold_period.get("t2_sharpe"),
        "t3_sharpe": _optimal_hold_period.get("t3_sharpe"),
        "optimal_hold_days": _optimal_hold_period.get("optimal_hold_days"),
        "hold_period_confidence": _optimal_hold_period.get("hold_period_confidence"),
        "t1_vs_t2_sharpe_diff": _optimal_hold_period.get("t1_vs_t2_sharpe_diff"),
        "t1_vs_t3_sharpe_diff": _optimal_hold_period.get("t1_vs_t3_sharpe_diff"),
        # Task 3 (Round 22, Beta): score percentile position-tier stratification.
        # score_p33/score_p67: composite score tercile cut-points.
        # tier_{high,mid,low}_win_rate: T+1 win rate per tier (None if < 3 samples).
        # tier_{high,mid,low}_avg_payoff: mean T+1 return per tier.
        # tier_monotone_win_rate: True when high > mid > low win rates (validates scoring).
        # tier_win_rate_spread: tier_high_win_rate − tier_low_win_rate.
        # tier_payoff_spread: tier_high_avg_payoff − tier_low_avg_payoff.
        "score_position_tiers": _score_position_tiers,
        "score_p33": _score_position_tiers.get("score_p33"),
        "score_p67": _score_position_tiers.get("score_p67"),
        "tier_high_win_rate": _score_position_tiers.get("tier_high_win_rate"),
        "tier_high_avg_payoff": _score_position_tiers.get("tier_high_avg_payoff"),
        "tier_mid_win_rate": _score_position_tiers.get("tier_mid_win_rate"),
        "tier_mid_avg_payoff": _score_position_tiers.get("tier_mid_avg_payoff"),
        "tier_low_win_rate": _score_position_tiers.get("tier_low_win_rate"),
        "tier_low_avg_payoff": _score_position_tiers.get("tier_low_avg_payoff"),
        "tier_monotone_win_rate": _score_position_tiers.get("tier_monotone_win_rate"),
        "tier_win_rate_spread": _score_position_tiers.get("tier_win_rate_spread"),
        "tier_payoff_spread": _score_position_tiers.get("tier_payoff_spread"),
        # -----------------------------------------------------------------------
        # Round 23 analytics
        # -----------------------------------------------------------------------
        # Task 2 (Round 23, Alpha): Kelly fraction position-sizing recommendations.
        # kelly_fraction_full: optimal position size per Kelly criterion, clipped to [0, 0.50].
        # kelly_fraction_half: half-Kelly (more conservative); quality floor ≥ 0.02.
        # kelly_fraction_tier_{high,low}: tier-specific half-Kelly fractions.
        # kelly_positive: True when the strategy has positive expected value (edge > 0).
        # kelly_edge: raw edge = p × b − q (un-normalised expected return).
        "kelly_position_fractions": _kelly_fractions,
        "kelly_fraction_full": _kelly_fractions.get("kelly_fraction_full"),
        "kelly_fraction_half": _kelly_fractions.get("kelly_fraction_half"),
        "kelly_fraction_tier_high": _kelly_fractions.get("kelly_fraction_tier_high"),
        "kelly_fraction_tier_low": _kelly_fractions.get("kelly_fraction_tier_low"),
        "kelly_positive": _kelly_fractions.get("kelly_positive"),
        "kelly_edge": _kelly_fractions.get("kelly_edge"),
        # Task 3 (Round 23, Beta): regime win-rate consistency check.
        # regime_win_rate_range: max − min win rate across valid regimes.
        # regime_consistency_score: 1 − range ∈ [0, 1]; floor ≥ 0.70.
        # worst_regime: name of the regime with the lowest win rate.
        # regime_robustness_flag: True when range < 0.15 (strong regime robustness).
        # bear_market_win_rate_deficit: overall_win_rate − bear_win_rate.
        "regime_consistency_check": _regime_consistency,
        "regime_win_rate_range": _regime_consistency.get("regime_win_rate_range"),
        "regime_win_rate_std": _regime_consistency.get("regime_win_rate_std"),
        "regime_consistency_score": _regime_consistency.get("regime_consistency_score"),
        "worst_regime": _regime_consistency.get("worst_regime"),
        "worst_regime_win_rate": _regime_consistency.get("worst_regime_win_rate"),
        "regime_robustness_flag": _regime_consistency.get("regime_robustness_flag"),
        "bear_market_win_rate_deficit": _regime_consistency.get("bear_market_win_rate_deficit"),
        # -----------------------------------------------------------------------
        # Round 24 analytics
        # -----------------------------------------------------------------------
        # Task 2 (Round 24): drawdown-adjusted Kelly fraction.
        # kelly_fraction_drawdown_adjusted: half-Kelly further reduced by intraday drawdown severity.
        # drawdown_adjustment_factor: 1 / (1 + severity); severity = max(0, −p10 / 0.05).
        # drawdown_kelly_vs_base_diff: adjusted − base half-Kelly (always ≤ 0).
        # drawdown_risk_level: "low" / "moderate" / "high" / "severe" based on p10 value.
        "drawdown_adjusted_kelly": _drawdown_adjusted_kelly,
        "kelly_fraction_drawdown_adjusted": _drawdown_adjusted_kelly.get("kelly_fraction_drawdown_adjusted"),
        "drawdown_adjustment_factor": _drawdown_adjusted_kelly.get("drawdown_adjustment_factor"),
        "drawdown_kelly_vs_base_diff": _drawdown_adjusted_kelly.get("drawdown_kelly_vs_base_diff"),
        "drawdown_risk_level": _drawdown_adjusted_kelly.get("drawdown_risk_level"),
        # -----------------------------------------------------------------------
        # Round 26 analytics
        # -----------------------------------------------------------------------
        # Task 2 (Round 26, Gamma): benchmark-adjusted Alpha vs HS300.
        # alpha_avg_return: mean(next_close_return − hs300_daily_return); positive = true skill.
        # alpha_win_rate: fraction of days BTST outperforms HS300.
        # information_ratio: alpha / tracking_error — risk-adjusted excess return signal.
        # beta_exposure: market sensitivity proxy (cov / var).
        # outperform_bull_rate / outperform_bear_rate: conditional outperformance.
        "benchmark_alpha": _benchmark_alpha,
        "benchmark_mean_return": _benchmark_alpha.get("benchmark_mean_return"),
        "alpha_avg_return": _benchmark_alpha.get("alpha_avg_return"),
        "alpha_win_rate": _benchmark_alpha.get("alpha_win_rate"),
        "alpha_sharpe": _benchmark_alpha.get("alpha_sharpe"),
        "beta_exposure": _benchmark_alpha.get("beta_exposure"),
        "information_ratio": _benchmark_alpha.get("information_ratio"),
        "outperform_bull_rate": _benchmark_alpha.get("outperform_bull_rate"),
        "outperform_bear_rate": _benchmark_alpha.get("outperform_bear_rate"),
    }
    # -----------------------------------------------------------------------
    # Round 26, Task 3 (Beta): Dynamic stop-loss suggestion.
    # Uses stop_loss_trigger_rate_2/3/5pct from Round 15 to recommend optimal stop level.
    # Called here (after _surface_result is assembled) so it can read stop-loss rates.
    # -----------------------------------------------------------------------
    _stop_loss_suggestion: dict[str, Any] = compute_dynamic_stop_loss_suggestion(_surface_result)
    _surface_result["stop_loss_suggestion"] = _stop_loss_suggestion
    _surface_result["suggested_stop_loss_pct"] = _stop_loss_suggestion.get("suggested_stop_loss_pct")
    _surface_result["stop_loss_confidence"] = _stop_loss_suggestion.get("stop_loss_confidence")
    _surface_result["stop_loss_rationale"] = _stop_loss_suggestion.get("stop_loss_rationale")
    _surface_result["tight_stop_viable"] = _stop_loss_suggestion.get("tight_stop_viable")
    _surface_result["loose_stop_warned"] = _stop_loss_suggestion.get("loose_stop_warned")
    _surface_result["optimal_stop_trigger_rate"] = _stop_loss_suggestion.get("optimal_stop_trigger_rate")
    # -----------------------------------------------------------------------
    # Round 27, Task 1 (Alpha): Return distribution shape — skewness & tail asymmetry.
    # Calls compute_return_distribution_shape on next_day_rows so all shape metrics
    # are computed against the same T+1 forward-return sample used everywhere else.
    # -----------------------------------------------------------------------
    _return_dist_shape: dict[str, Any] = compute_return_distribution_shape(next_day_rows)
    _surface_result["return_distribution_shape"] = _return_dist_shape
    _surface_result["next_close_return_skewness"] = _return_dist_shape.get("next_close_return_skewness")
    _surface_result["next_close_return_downside_std"] = _return_dist_shape.get("next_close_return_downside_std")
    _surface_result["next_close_return_upside_std"] = _return_dist_shape.get("next_close_return_upside_std")
    _surface_result["win_loss_std_ratio"] = _return_dist_shape.get("win_loss_std_ratio")
    _surface_result["return_p5"] = _return_dist_shape.get("return_p5")
    _surface_result["return_p95"] = _return_dist_shape.get("return_p95")
    _surface_result["return_iqr"] = _return_dist_shape.get("return_iqr")
    _surface_result["heavy_left_tail_flag"] = _return_dist_shape.get("heavy_left_tail_flag")
    # -----------------------------------------------------------------------
    # Round 27, Task 2 (Gamma): Composite score discrimination power.
    # Uses all rows (not just next_day_rows) to leverage the full composite score sample.
    # -----------------------------------------------------------------------
    _score_discrimination: dict[str, Any] = compute_score_discrimination_power(rows)
    _surface_result["score_discrimination_power"] = _score_discrimination
    _surface_result["score_spread_p95_p5"] = _score_discrimination.get("score_spread_p95_p5")
    _surface_result["score_iqr"] = _score_discrimination.get("score_iqr")
    _surface_result["score_above_60_fraction"] = _score_discrimination.get("score_above_60_fraction")
    _surface_result["score_above_70_fraction"] = _score_discrimination.get("score_above_70_fraction")
    _surface_result["score_return_spearman"] = _score_discrimination.get("score_return_spearman")
    _surface_result["score_discrimination_index"] = _score_discrimination.get("score_discrimination_index")
    _surface_result["low_discrimination_flag"] = _score_discrimination.get("low_discrimination_flag")
    # -----------------------------------------------------------------------
    # Round 27, Task 3 (Beta): Liquidity-aware position guidance.
    # Reads avg_candidate_pool_size/scarce_market_window_count/market_size_classification
    # from _surface_result (populated above via the R14 walk-forward aggregate fields).
    # Called before health score so health can eventually incorporate it.
    # -----------------------------------------------------------------------
    _liquidity_guidance: dict[str, Any] = compute_liquidity_position_guidance(_surface_result)
    _surface_result["liquidity_position_guidance"] = _liquidity_guidance
    _surface_result["recommended_max_positions"] = _liquidity_guidance.get("recommended_max_positions")
    _surface_result["recommended_position_size_pct"] = _liquidity_guidance.get("recommended_position_size_pct")
    _surface_result["concentration_risk_level"] = _liquidity_guidance.get("concentration_risk_level")
    _surface_result["diversification_feasible"] = _liquidity_guidance.get("diversification_feasible")
    _surface_result["pool_size_stability"] = _liquidity_guidance.get("pool_size_stability")
    # -----------------------------------------------------------------------
    # Round 25, Task 1 (Gamma): Profile health score — aggregate all quality
    # indicators into a single 0-100 score so strategists can compare profiles
    # at a glance without scanning dozens of individual metrics.
    # -----------------------------------------------------------------------
    _health: dict[str, Any] = compute_profile_health_score(_surface_result)
    _surface_result["profile_health_score"] = _health["profile_health_score"]
    _surface_result["profile_health_grade"] = _health["profile_health_grade"]
    _surface_result["health_subscores"] = _health["health_subscores"]
    _surface_result["health_weakest_area"] = _health["health_weakest_area"]
    _surface_result["health_strongest_area"] = _health["health_strongest_area"]
    return _surface_result


# ---------------------------------------------------------------------------
# Task 1 (Round 21, Gamma): Surface metric win-rate correlation analysis
# ---------------------------------------------------------------------------
# Computes Spearman rank correlation between every numeric scalar surface metric
# and the per-window next_close_positive_rate (T+1 win rate) across all replay
# windows collected during an optimizer trial.  Surfaces with fewer than 5 windows
# produce an empty dict.  Results help identify which factors/metrics most reliably
# predict future window-level win rate, guiding PROBE_GRID pruning.


def compute_surface_metric_correlations(all_window_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute Spearman correlation of each numeric surface metric with next_close_positive_rate.

    Iterates all numeric scalar keys found across *all_window_summaries* (excluding the
    target itself) and computes their Spearman rank correlation with
    ``next_close_positive_rate`` over the cross-window sample.  Metrics with fewer
    than 5 paired observations are excluded.

    Args:
        all_window_summaries: List of per-window surface summary dicts, as returned by
            ``build_surface_summary``.  Typically one dict per replay window.

    Returns:
        Dict containing:

        - One entry per metric: ``{metric_name: spearman_corr}`` in [-1, 1].
        - ``top_5_correlated_metrics``: list of up to 5 metric names with highest |corr|.
        - ``bottom_5_correlated_metrics``: list of up to 5 metric names with lowest |corr|.

        Returns an empty dict when fewer than 5 summaries are provided.
    """
    if len(all_window_summaries) < 5:
        return {}
    target_key: str = "next_close_positive_rate"
    # Discover candidate metric keys — only scalar numerics (int/float, excluding bool)
    candidate_keys: set[str] = set()
    for summary in all_window_summaries:
        for k, v in summary.items():
            if k == target_key:
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                candidate_keys.add(k)
    correlations: dict[str, float] = {}
    for metric_key in sorted(candidate_keys):
        pairs: list[tuple[float, float]] = []
        for summary in all_window_summaries:
            target_val = summary.get(target_key)
            metric_val = summary.get(metric_key)
            if target_val is None or metric_val is None:
                continue
            try:
                pairs.append((float(metric_val), float(target_val)))
            except (TypeError, ValueError):
                continue
        if len(pairs) < 5:
            continue
        corr = _spearman_corr([p[0] for p in pairs], [p[1] for p in pairs])
        if corr is not None:
            correlations[metric_key] = corr
    if not correlations:
        return {}
    sorted_by_abs: list[str] = sorted(correlations.keys(), key=lambda k: abs(correlations[k]), reverse=True)
    result: dict[str, Any] = dict(correlations)
    result["top_5_correlated_metrics"] = sorted_by_abs[:5]
    result["bottom_5_correlated_metrics"] = sorted_by_abs[-5:]
    return result


# ---------------------------------------------------------------------------
# Task 2 (Round 21, Alpha): Factor IC stability — Information Ratio per factor
# ---------------------------------------------------------------------------
# Measures cross-window IC stability for each BTST factor.  A factor that
# consistently shows IC = 0.05 across all windows is far more reliable than one
# that alternates between 0.15 and −0.05, even if both average the same.
# IR = mean_IC / std_IC — the higher the better (analogous to a Sharpe ratio
# for factor predictability).


def compute_factor_ic_stability(all_window_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute per-factor IC stability (IR = mean_IC / std_IC) across replay windows.

    For each factor in :data:`BTST_FACTOR_NAMES`, extracts the ``factor_ic_next_close``
    value from every window summary, then computes:

    - ``{factor}_ic_mean``: average Spearman IC across windows.
    - ``{factor}_ic_std``: sample standard deviation of IC across windows.
    - ``{factor}_ic_ir``: Information Ratio = mean_IC / std_IC.  When std_IC ≈ 0,
      IR falls back to mean_IC to avoid division by zero.
    - ``{factor}_ic_positive_fraction``: fraction of windows where IC > 0.
    - ``most_stable_factor``: name of factor with the highest IR.
    - ``least_stable_factor``: name of factor with the lowest IR.

    Factors with no IC observations across any window are omitted from the output.

    Args:
        all_window_summaries: List of per-window surface summary dicts.

    Returns:
        Dict of stability metrics for each observed factor, plus summary keys
        ``most_stable_factor`` and ``least_stable_factor``.  Returns an empty
        dict when no factor IC data is present in any summary.
    """
    factor_ics: dict[str, list[float]] = {f: [] for f in BTST_FACTOR_NAMES}
    for summary in all_window_summaries:
        ic_dict: dict[str, Any] = dict(summary.get("factor_ic_next_close") or {})
        for factor in BTST_FACTOR_NAMES:
            ic_raw = ic_dict.get(factor)
            if ic_raw is None:
                continue
            try:
                factor_ics[factor].append(float(ic_raw))
            except (TypeError, ValueError):
                continue
    result: dict[str, Any] = {}
    for factor in BTST_FACTOR_NAMES:
        vals: list[float] = factor_ics[factor]
        if not vals:
            continue
        n: int = len(vals)
        mean_ic: float = sum(vals) / n
        std_ic: float = (sum((v - mean_ic) ** 2 for v in vals) / (n - 1)) ** 0.5 if n >= 2 else 0.0
        ir: float = (mean_ic / std_ic) if std_ic > 1e-6 else mean_ic
        pos_fraction: float = sum(1 for v in vals if v > 0.0) / n
        result[f"{factor}_ic_mean"] = round(mean_ic, 4)
        result[f"{factor}_ic_std"] = round(std_ic, 4)
        result[f"{factor}_ic_ir"] = round(ir, 4)
        result[f"{factor}_ic_positive_fraction"] = round(pos_fraction, 4)
    ir_by_factor: dict[str, float] = {f: result[f"{f}_ic_ir"] for f in BTST_FACTOR_NAMES if f"{f}_ic_ir" in result}
    if ir_by_factor:
        result["most_stable_factor"] = max(ir_by_factor, key=lambda f: ir_by_factor[f])
        result["least_stable_factor"] = min(ir_by_factor, key=lambda f: ir_by_factor[f])
    return result


# ---------------------------------------------------------------------------
# Task 1 (Round 24): Factor IC temporal trend — decay detection
# ---------------------------------------------------------------------------
# Detects whether each factor's Information Coefficient is decaying over time
# by comparing early-window IC averages with late-window IC averages.  A trend
# below −0.02 is flagged as decaying, indicating the factor's predictive power
# is degrading and may need recalibration.


def compute_factor_ic_temporal_trend(all_window_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Round 24, Task 1: Detect IC decay trend across replay windows.

    Splits the ordered window list into early (first ⌈n/2⌉) and late (remaining)
    halves, then computes the mean IC of each half per factor.  The IC trend is
    ``late_mean − early_mean``; a trend below −0.02 is considered *decaying*.

    Per-factor output keys:
    - ``{factor}_ic_early_mean``: mean IC over early windows.
    - ``{factor}_ic_late_mean``: mean IC over late windows.
    - ``{factor}_ic_trend``: late_mean − early_mean.
    - ``{factor}_ic_decaying``: True when trend < −0.02.

    Summary keys:
    - ``decaying_factor_count``: number of factors with trend < −0.02.
    - ``decaying_factors``: sorted list of decaying factor names.
    - ``most_decaying_factor``: factor with the most negative trend (worst decay).
    - ``most_improving_factor``: factor with the most positive trend.

    Factors with fewer than 3 valid IC observations in either half receive
    ``None`` for mean/trend values and ``False`` for the decaying flag.

    Args:
        all_window_summaries: Ordered list of per-window surface summary dicts.

    Returns:
        Dict of per-factor temporal trend metrics plus summary keys.
        Returns minimal defaults when fewer than 2 windows are available.
    """
    n = len(all_window_summaries)
    if n < 2:
        return {"decaying_factor_count": 0, "decaying_factors": [], "most_decaying_factor": None, "most_improving_factor": None}
    split = (n + 1) // 2
    early_summaries = all_window_summaries[:split]
    late_summaries = all_window_summaries[split:]
    result: dict[str, Any] = {}
    factor_trends: dict[str, float | None] = {}
    for factor in BTST_FACTOR_NAMES:
        early_ics: list[float] = []
        for s in early_summaries:
            ic_dict: dict[str, Any] = dict(s.get("factor_ic_next_close") or {})
            ic_raw = ic_dict.get(factor)
            if ic_raw is None:
                continue
            try:
                early_ics.append(float(ic_raw))
            except (TypeError, ValueError):
                continue
        late_ics: list[float] = []
        for s in late_summaries:
            ic_dict = dict(s.get("factor_ic_next_close") or {})
            ic_raw = ic_dict.get(factor)
            if ic_raw is None:
                continue
            try:
                late_ics.append(float(ic_raw))
            except (TypeError, ValueError):
                continue
        if len(early_ics) < 3 or len(late_ics) < 3:
            result[f"{factor}_ic_early_mean"] = None
            result[f"{factor}_ic_late_mean"] = None
            result[f"{factor}_ic_trend"] = None
            result[f"{factor}_ic_decaying"] = False
            factor_trends[factor] = None
            continue
        early_mean = sum(early_ics) / len(early_ics)
        late_mean = sum(late_ics) / len(late_ics)
        trend = late_mean - early_mean
        result[f"{factor}_ic_early_mean"] = round(early_mean, 4)
        result[f"{factor}_ic_late_mean"] = round(late_mean, 4)
        result[f"{factor}_ic_trend"] = round(trend, 4)
        result[f"{factor}_ic_decaying"] = bool(trend < -0.02)
        factor_trends[factor] = trend
    valid_trends: dict[str, float] = {f: t for f, t in factor_trends.items() if t is not None}
    decaying_factors = sorted(f for f, t in valid_trends.items() if t < -0.02)
    result["decaying_factor_count"] = len(decaying_factors)
    result["decaying_factors"] = decaying_factors
    result["most_decaying_factor"] = min(valid_trends, key=lambda f: valid_trends[f]) if valid_trends else None
    result["most_improving_factor"] = max(valid_trends, key=lambda f: valid_trends[f]) if valid_trends else None
    return result


# ---------------------------------------------------------------------------
# Task 3 (Round 24): Walk-forward verdict calibration
# ---------------------------------------------------------------------------
# Checks whether the walk-forward runner verdicts (promotable / watch / probation)
# correlate with observed T+1 win rates across windows.  When explicit verdicts are
# absent, uses quartile-based win-rate categories as a proxy.  A calibrated system
# should show monotonically increasing win rates: promotable > watch > probation.


def compute_verdict_calibration(all_window_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Round 24, Task 3: Check walk-forward verdict calibration.

    For each window summary, reads the ``verdict`` field (if present) or uses
    the ``next_close_positive_rate`` quartile rank as a proxy verdict category.
    Then computes the average win rate per category and checks for monotone ordering.

    Proxy quartile mapping (applied only when no window carries a real verdict):
    - top-25 % win rate → "promotable-like"
    - bottom-25 % win rate → "probation-like"
    - middle 50 % → "watch-like"

    Output keys:
    - ``verdict_calibration_score``: normalised spread = min(1, max(0,
      (promotable_wr − probation_wr) / 0.20)).  1.0 = fully calibrated.
    - ``verdict_monotone``: True when promotable_wr > watch_wr > probation_wr
      (or promotable_wr > probation_wr when no watch category).
    - ``verdict_win_rate_map``: average T+1 win rate per verdict category.
    - ``verdict_sample_counts``: number of windows per category.

    Args:
        all_window_summaries: Ordered list of per-window surface summary dicts.

    Returns:
        Dict with calibration score, monotone flag, win-rate map, and sample counts.
        Returns ``None`` numeric values when not enough data is available.
    """
    _null_result: dict[str, Any] = {"verdict_calibration_score": None, "verdict_monotone": None, "verdict_win_rate_map": {}, "verdict_sample_counts": {}}
    categorized: list[tuple[str, float]] = []
    has_real_verdicts = False
    for summary in all_window_summaries:
        wr_raw = summary.get("next_close_positive_rate")
        if wr_raw is None:
            continue
        try:
            wr = float(wr_raw)
        except (TypeError, ValueError):
            continue
        verdict_raw = summary.get("verdict")
        if verdict_raw is not None:
            has_real_verdicts = True
            categorized.append((str(verdict_raw), wr))
        else:
            categorized.append(("__proxy__", wr))
    if not categorized:
        return _null_result
    if not has_real_verdicts:
        all_wrs_sorted = sorted(wr for _, wr in categorized)
        n = len(all_wrs_sorted)
        q1_idx = max(0, (n // 4) - 1)
        q3_idx = min(n - 1, (3 * n) // 4)
        q1_thresh = all_wrs_sorted[q1_idx] if n >= 4 else None
        q3_thresh = all_wrs_sorted[q3_idx] if n >= 4 else None
        proxy_categorized: list[tuple[str, float]] = []
        for _, wr in categorized:
            if q3_thresh is not None and wr >= q3_thresh:
                proxy_categorized.append(("promotable-like", wr))
            elif q1_thresh is not None and wr <= q1_thresh:
                proxy_categorized.append(("probation-like", wr))
            else:
                proxy_categorized.append(("watch-like", wr))
        categorized = proxy_categorized
    verdict_groups: dict[str, list[float]] = {}
    for verdict, wr in categorized:
        verdict_groups.setdefault(verdict, []).append(wr)
    verdict_win_rate_map: dict[str, float] = {v: round(sum(wrs) / len(wrs), 4) for v, wrs in verdict_groups.items()}
    verdict_sample_counts: dict[str, int] = {v: len(wrs) for v, wrs in verdict_groups.items()}
    promotable_wr = verdict_win_rate_map.get("promotable-like") if verdict_win_rate_map.get("promotable-like") is not None else verdict_win_rate_map.get("promotable")
    probation_wr = verdict_win_rate_map.get("probation-like") if verdict_win_rate_map.get("probation-like") is not None else verdict_win_rate_map.get("probation")
    watch_wr = verdict_win_rate_map.get("watch-like") if verdict_win_rate_map.get("watch-like") is not None else verdict_win_rate_map.get("watch")
    verdict_monotone: bool | None = None
    if promotable_wr is not None and probation_wr is not None:
        if watch_wr is not None:
            verdict_monotone = bool(promotable_wr > watch_wr > probation_wr)
        else:
            verdict_monotone = bool(promotable_wr > probation_wr)
    calibration_score: float | None = None
    if promotable_wr is not None and probation_wr is not None:
        calibration_score = round(min(1.0, max(0.0, (promotable_wr - probation_wr) / 0.20)), 4)
    return {
        "verdict_calibration_score": calibration_score,
        "verdict_monotone": verdict_monotone,
        "verdict_win_rate_map": verdict_win_rate_map,
        "verdict_sample_counts": verdict_sample_counts,
    }


# ---------------------------------------------------------------------------
# Round 25, Task 1 (Gamma): Comprehensive profile health score
# ---------------------------------------------------------------------------
# Aggregates all major quality indicators into a single 0–100 score so that
# strategists can quickly compare candidate profiles without scanning dozens of
# individual metrics.  Each of the 10 sub-items contributes up to 10 points.
# Missing fields receive a neutral 5-point score to avoid penalising profiles
# built before the corresponding metric was added to the system.


def compute_profile_health_score(surface_summary: dict[str, Any]) -> dict[str, Any]:
    """综合多个质量指标，计算profile整体健康度评分 [0, 100].

    共10个子项，每项满分10分:

    1. win_rate_score  — next_close_positive_rate
    2. payoff_score    — realized_payoff_ratio
    3. kelly_score     — kelly_positive + kelly_fraction_half
    4. regime_score    — regime_consistency_score
    5. tier_score      — tier_monotone_win_rate + tier_win_rate_spread
    6. ic_score        — ic_positive_factor_fraction
    7. stability_score — regime_robustness_flag + bear_market_win_rate_deficit
    8. drawdown_score  — t_plus_1_intraday_drawdown_p10
    9. hold_score      — hold_period_confidence
    10. execution_score — execution_timing_confidence

    Missing fields receive a neutral 5.0 score.

    Args:
        surface_summary: A surface summary dict (output of ``build_surface_summary``
            or an aggregated evaluator output dict).

    Returns:
        Dict with keys: profile_health_score (0-100 float), profile_health_grade
        ("A"/"B"/"C"/"D"), health_subscores (dict[str, float]), health_weakest_area
        (str), health_strongest_area (str).
    """
    _NEUTRAL = 5.0
    subscores: dict[str, float] = {}

    # 1. win_rate_score
    wr_raw = surface_summary.get("next_close_positive_rate")
    if wr_raw is None:
        subscores["win_rate_score"] = _NEUTRAL
    else:
        wr = float(wr_raw)
        if wr >= 0.65: subscores["win_rate_score"] = 10.0
        elif wr >= 0.55: subscores["win_rate_score"] = 7.0
        elif wr >= 0.45: subscores["win_rate_score"] = 4.0
        else: subscores["win_rate_score"] = 0.0

    # 2. payoff_score
    payoff_raw = surface_summary.get("realized_payoff_ratio")
    if payoff_raw is None:
        subscores["payoff_score"] = _NEUTRAL
    else:
        payoff = float(payoff_raw)
        if payoff >= 2.0: subscores["payoff_score"] = 10.0
        elif payoff >= 1.5: subscores["payoff_score"] = 7.0
        elif payoff >= 1.0: subscores["payoff_score"] = 4.0
        else: subscores["payoff_score"] = 0.0

    # 3. kelly_score
    kelly_pos_raw = surface_summary.get("kelly_positive")
    kelly_half_raw = surface_summary.get("kelly_fraction_half")
    if kelly_pos_raw is None:
        subscores["kelly_score"] = _NEUTRAL
    elif bool(kelly_pos_raw):
        kelly_half = float(kelly_half_raw) if kelly_half_raw is not None else None
        if kelly_half is not None and kelly_half >= 0.05: subscores["kelly_score"] = 10.0
        elif kelly_half is not None and kelly_half >= 0.02: subscores["kelly_score"] = 6.0
        else: subscores["kelly_score"] = 3.0
    else:
        subscores["kelly_score"] = 0.0

    # 4. regime_score
    rcs_raw = surface_summary.get("regime_consistency_score")
    if rcs_raw is None:
        subscores["regime_score"] = _NEUTRAL
    else:
        rcs = float(rcs_raw)
        if rcs >= 0.85: subscores["regime_score"] = 10.0
        elif rcs >= 0.70: subscores["regime_score"] = 7.0
        elif rcs >= 0.55: subscores["regime_score"] = 4.0
        else: subscores["regime_score"] = 0.0

    # 5. tier_score
    tier_mono_raw = surface_summary.get("tier_monotone_win_rate")
    tier_spread_raw = surface_summary.get("tier_win_rate_spread")
    if tier_mono_raw is None:
        subscores["tier_score"] = _NEUTRAL
    elif bool(tier_mono_raw):
        tier_spread = float(tier_spread_raw) if tier_spread_raw is not None else None
        if tier_spread is not None and tier_spread >= 0.10: subscores["tier_score"] = 10.0
        else: subscores["tier_score"] = 6.0
    else:
        subscores["tier_score"] = 0.0

    # 6. ic_score  (ic_positive_factor_fraction from R11; neutral when absent from per-surface dict)
    ic_frac_raw = surface_summary.get("ic_positive_factor_fraction")
    if ic_frac_raw is None:
        subscores["ic_score"] = _NEUTRAL
    else:
        ic_frac = float(ic_frac_raw)
        if ic_frac >= 0.80: subscores["ic_score"] = 10.0
        elif ic_frac >= 0.60: subscores["ic_score"] = 6.0
        elif ic_frac >= 0.40: subscores["ic_score"] = 3.0
        else: subscores["ic_score"] = 0.0

    # 7. stability_score
    rob_raw = surface_summary.get("regime_robustness_flag")
    deficit_raw = surface_summary.get("bear_market_win_rate_deficit")
    if rob_raw is None:
        subscores["stability_score"] = _NEUTRAL
    elif bool(rob_raw):
        deficit = float(deficit_raw) if deficit_raw is not None else None
        if deficit is not None and deficit < 0.10: subscores["stability_score"] = 10.0
        else: subscores["stability_score"] = 7.0
    else:
        subscores["stability_score"] = 3.0

    # 8. drawdown_score
    dd_raw = surface_summary.get("t_plus_1_intraday_drawdown_p10")
    if dd_raw is None:
        subscores["drawdown_score"] = _NEUTRAL
    else:
        dd = float(dd_raw)
        if dd > -0.02: subscores["drawdown_score"] = 10.0
        elif dd > -0.05: subscores["drawdown_score"] = 7.0
        elif dd > -0.08: subscores["drawdown_score"] = 4.0
        else: subscores["drawdown_score"] = 0.0

    # 9. hold_score
    hold_conf_raw = surface_summary.get("hold_period_confidence")
    if hold_conf_raw is None:
        subscores["hold_score"] = _NEUTRAL
    else:
        hold_conf = float(hold_conf_raw)
        if hold_conf >= 0.30: subscores["hold_score"] = 10.0
        elif hold_conf >= 0.15: subscores["hold_score"] = 6.0
        else: subscores["hold_score"] = 3.0

    # 10. execution_score
    exec_conf_raw = surface_summary.get("execution_timing_confidence")
    if exec_conf_raw is None:
        subscores["execution_score"] = _NEUTRAL
    else:
        exec_conf = float(exec_conf_raw)
        if exec_conf >= 0.20: subscores["execution_score"] = 10.0
        elif exec_conf >= 0.10: subscores["execution_score"] = 6.0
        else: subscores["execution_score"] = 3.0

    total_score = round(sum(subscores.values()), 2)
    if total_score >= 80.0: grade = "A"
    elif total_score >= 60.0: grade = "B"
    elif total_score >= 40.0: grade = "C"
    else: grade = "D"

    weakest_area = min(subscores, key=lambda k: subscores[k])
    strongest_area = max(subscores, key=lambda k: subscores[k])

    return {
        "profile_health_score": total_score,
        "profile_health_grade": grade,
        "health_subscores": subscores,
        "health_weakest_area": weakest_area,
        "health_strongest_area": strongest_area,
    }


# ---------------------------------------------------------------------------
# Round 25, Task 2 (Beta): Selection churn and trading-cost estimation
# ---------------------------------------------------------------------------
# Estimates cross-window stability and implied trading-cost drag from the
# sequence of per-window surface summaries accumulated during an optimizer
# replay run.  High churn (large swing in win-rate between adjacent windows)
# signals strategy instability and implies higher cumulative transaction costs.


def compute_selection_churn_metrics(all_window_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """估算连续窗口间的选股换手率和隐含交易成本.

    因单个 window_summary 不含股票代码列表，使用聚合指标的跨窗口变化率作为替代估算：
    - ``win_rate_window_volatility``: 相邻窗口 next_close_positive_rate 绝对差的均值
    - ``win_rate_window_trend``: 对窗口序号做线性回归的斜率 × 100（百分点/窗口，正=改善）
    - ``payoff_window_volatility``: 相邻窗口 realized_payoff_ratio 绝对差的均值
    - ``window_count``: 可用窗口数
    - ``stable_window_fraction``: 相邻窗口胜率变化 ≤ 5% 的比例
    - ``estimated_cost_drag_bps``: 估算交易成本拖累 = volatility × 30 × 2 (买+卖)

    Args:
        all_window_summaries: Ordered list of per-window surface summary dicts.

    Returns:
        Dict with the six metrics listed above.  Most fields are ``None`` when
        fewer than 2 windows are available.
    """
    _null: dict[str, Any] = {"win_rate_window_volatility": None, "win_rate_window_trend": None, "payoff_window_volatility": None, "window_count": len(all_window_summaries), "stable_window_fraction": None, "estimated_cost_drag_bps": None}
    if len(all_window_summaries) < 2:
        return _null

    wr_values: list[float] = []
    payoff_values: list[float] = []
    for s in all_window_summaries:
        wr_raw = s.get("next_close_positive_rate")
        if wr_raw is not None:
            try: wr_values.append(float(wr_raw))
            except (TypeError, ValueError): pass
        pr_raw = s.get("realized_payoff_ratio")
        if pr_raw is not None:
            try: payoff_values.append(float(pr_raw))
            except (TypeError, ValueError): pass

    if len(wr_values) < 2:
        return {**_null, "window_count": len(all_window_summaries)}

    wr_diffs: list[float] = [abs(wr_values[i + 1] - wr_values[i]) for i in range(len(wr_values) - 1)]
    win_rate_window_volatility = round(sum(wr_diffs) / len(wr_diffs), 4)
    stable_window_fraction = round(sum(1 for d in wr_diffs if d <= 0.05) / len(wr_diffs), 4)

    # Linear regression of win-rate vs window index; slope × 100 = percentage points per window
    n_wr = len(wr_values)
    xs_wr = list(range(n_wr))
    mean_x = (n_wr - 1) / 2.0
    mean_y = sum(wr_values) / n_wr
    ss_xy = sum((xs_wr[i] - mean_x) * (wr_values[i] - mean_y) for i in range(n_wr))
    ss_xx = sum((xi - mean_x) ** 2 for xi in xs_wr)
    win_rate_window_trend = round((ss_xy / ss_xx) * 100.0, 4) if ss_xx != 0.0 else 0.0

    payoff_window_volatility: float | None = None
    if len(payoff_values) >= 2:
        payoff_diffs = [abs(payoff_values[i + 1] - payoff_values[i]) for i in range(len(payoff_values) - 1)]
        payoff_window_volatility = round(sum(payoff_diffs) / len(payoff_diffs), 4)

    estimated_cost_drag_bps = round(win_rate_window_volatility * 30.0 * 2.0, 2)

    return {
        "win_rate_window_volatility": win_rate_window_volatility,
        "win_rate_window_trend": win_rate_window_trend,
        "payoff_window_volatility": payoff_window_volatility,
        "window_count": len(all_window_summaries),
        "stable_window_fraction": stable_window_fraction,
        "estimated_cost_drag_bps": estimated_cost_drag_bps,
    }


def _row_sort_key(row: dict[str, Any]) -> tuple[float, float, float, str, str]:
    return (
        float(row.get("next_high_return") if row.get("next_high_return") is not None else -999.0),
        float(row.get("next_close_return") if row.get("next_close_return") is not None else -999.0),
        float(row.get("score_target") if row.get("score_target") is not None else -999.0),
        str(row.get("trade_date") or ""),
        str(row.get("ticker") or ""),
    )


def build_false_negative_proxy_rows(rows: list[dict[str, Any]], *, next_high_hit_threshold: float) -> list[dict[str, Any]]:
    proxies: list[dict[str, Any]] = []
    for row in rows:
        if row.get("decision") not in {"blocked", "rejected"}:
            continue
        next_high_return = row.get("next_high_return")
        next_close_return = row.get("next_close_return")
        matched_reasons: list[str] = []
        if next_high_return is not None and float(next_high_return) >= next_high_hit_threshold:
            matched_reasons.append("high_hit")
        if next_close_return is not None and float(next_close_return) > 0:
            matched_reasons.append("next_close_positive")
        if not matched_reasons:
            continue
        proxies.append({**row, "false_negative_proxy_reasons": matched_reasons})
    proxies.sort(key=_row_sort_key, reverse=True)
    return proxies


def build_day_breakdown(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    cycle_grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        trade_date = str(row.get("trade_date") or "")
        grouped[trade_date][str(row.get("decision") or "unknown")] += 1
        cycle_grouped[trade_date][str(row.get("cycle_status") or "unknown")] += 1

    day_rows: list[dict[str, Any]] = []
    for trade_date in sorted(grouped):
        counts = grouped[trade_date]
        cycle_counts = cycle_grouped[trade_date]
        day_rows.append(
            {
                "trade_date": trade_date,
                "selected_count": int(counts.get("selected", 0)),
                "near_miss_count": int(counts.get("near_miss", 0)),
                "blocked_count": int(counts.get("blocked", 0)),
                "rejected_count": int(counts.get("rejected", 0)),
                "cycle_status_counts": dict(cycle_counts),
            }
        )
    return day_rows


def resolve_guardrail(value: float | None, baseline_value: Any, fallback: float) -> float:
    if value is not None:
        return round(float(value), 4)
    if baseline_value is None:
        return round(float(fallback), 4)
    return round(float(baseline_value), 4)


def _delta(left: Any, right: Any) -> float | None:
    left_value = safe_float(left)
    right_value = safe_float(right)
    if left_value is None or right_value is None:
        return None
    return round(right_value - left_value, 4)


def compare_reports(
    baseline: dict[str, Any],
    variant: dict[str, Any],
    *,
    guardrail_next_high_hit_rate: float,
    guardrail_next_close_positive_rate: float,
) -> dict[str, Any]:
    baseline_tradeable = dict(baseline["surface_summaries"]["tradeable"])
    variant_tradeable = dict(variant["surface_summaries"]["tradeable"])
    baseline_false_negative = dict(baseline["false_negative_proxy_summary"])
    variant_false_negative = dict(variant["false_negative_proxy_summary"])

    actionable_count_delta = int(variant_tradeable.get("total_count", 0)) - int(baseline_tradeable.get("total_count", 0))
    closed_cycle_actionable_delta = int(variant_tradeable.get("closed_cycle_count", 0)) - int(baseline_tradeable.get("closed_cycle_count", 0))
    false_negative_delta = int(variant_false_negative.get("count", 0)) - int(baseline_false_negative.get("count", 0))

    guardrail_status = "not_enough_closed_tradeable_rows"
    variant_high_hit_rate = variant_tradeable.get("next_high_hit_rate_at_threshold")
    variant_close_positive_rate = variant_tradeable.get("next_close_positive_rate")
    if variant_tradeable.get("closed_cycle_count", 0):
        if variant_high_hit_rate is not None and variant_close_positive_rate is not None and float(variant_high_hit_rate) >= guardrail_next_high_hit_rate and float(variant_close_positive_rate) >= guardrail_next_close_positive_rate:
            guardrail_status = "passes_closed_tradeable_guardrails"
        else:
            guardrail_status = "fails_closed_tradeable_guardrails"

    if variant.get("artifact_status") == "missing_selection_artifacts" and int(variant.get("row_count", 0)) == 0:
        comparison_note = f"{variant['label']} 的 session_summary 已存在，但 selection_artifacts 缺失，无法自动重建 closed-cycle surface；当前比较仅能视为产物完整性告警，不能解读为 coverage 退化。"
    elif int(baseline_tradeable.get("total_count", 0)) == 0 and int(variant_tradeable.get("total_count", 0)) > 0:
        comparison_note = f"{variant['label']} 把 tradeable surface 从 0 提升到 {variant_tradeable['total_count']}，" f"其中 closed-cycle actionable={variant_tradeable['closed_cycle_count']}。"
    elif actionable_count_delta > 0:
        comparison_note = f"{variant['label']} 的 tradeable surface 相比 baseline 增加 {actionable_count_delta}，" f"closed-cycle actionable 变化 {closed_cycle_actionable_delta}。"
    elif actionable_count_delta == 0 and false_negative_delta < 0:
        comparison_note = f"{variant['label']} 没有扩大 tradeable surface，但减少了 {abs(false_negative_delta)} 个 false negative proxy。"
    else:
        comparison_note = f"{variant['label']} 相比 baseline 没有形成明确的 coverage 优势，需结合 false negative 和 closed-cycle 质量再判断。"

    return {
        "baseline_label": baseline["label"],
        "variant_label": variant["label"],
        "tradeable_surface_delta": {
            "total_count": actionable_count_delta,
            "closed_cycle_count": closed_cycle_actionable_delta,
            "next_high_hit_rate_at_threshold": _delta(
                baseline_tradeable.get("next_high_hit_rate_at_threshold"),
                variant_tradeable.get("next_high_hit_rate_at_threshold"),
            ),
            "next_close_positive_rate": _delta(
                baseline_tradeable.get("next_close_positive_rate"),
                variant_tradeable.get("next_close_positive_rate"),
            ),
            "t_plus_2_close_positive_rate": _delta(
                baseline_tradeable.get("t_plus_2_close_positive_rate"),
                variant_tradeable.get("t_plus_2_close_positive_rate"),
            ),
            "next_high_return_mean": _delta(
                dict(baseline_tradeable.get("next_high_return_distribution") or {}).get("mean"),
                dict(variant_tradeable.get("next_high_return_distribution") or {}).get("mean"),
            ),
            "next_close_return_mean": _delta(
                dict(baseline_tradeable.get("next_close_return_distribution") or {}).get("mean"),
                dict(variant_tradeable.get("next_close_return_distribution") or {}).get("mean"),
            ),
            "next_close_return_median": _delta(
                dict(baseline_tradeable.get("next_close_return_distribution") or {}).get("median"),
                dict(variant_tradeable.get("next_close_return_distribution") or {}).get("median"),
            ),
            "next_close_return_p10": _delta(
                dict(baseline_tradeable.get("next_close_return_distribution") or {}).get("p10"),
                dict(variant_tradeable.get("next_close_return_distribution") or {}).get("p10"),
            ),
            "t_plus_2_close_return_mean": _delta(
                dict(baseline_tradeable.get("t_plus_2_close_return_distribution") or {}).get("mean"),
                dict(variant_tradeable.get("t_plus_2_close_return_distribution") or {}).get("mean"),
            ),
            "t_plus_2_close_return_median": _delta(
                dict(baseline_tradeable.get("t_plus_2_close_return_distribution") or {}).get("median"),
                dict(variant_tradeable.get("t_plus_2_close_return_distribution") or {}).get("median"),
            ),
            "t_plus_2_close_return_p10": _delta(
                dict(baseline_tradeable.get("t_plus_2_close_return_distribution") or {}).get("p10"),
                dict(variant_tradeable.get("t_plus_2_close_return_distribution") or {}).get("p10"),
            ),
            "next_close_payoff_ratio": _delta(
                baseline_tradeable.get("next_close_payoff_ratio"),
                variant_tradeable.get("next_close_payoff_ratio"),
            ),
            "next_close_profit_factor": _delta(
                baseline_tradeable.get("next_close_profit_factor"),
                variant_tradeable.get("next_close_profit_factor"),
            ),
            "next_close_expectancy": _delta(
                baseline_tradeable.get("next_close_expectancy"),
                variant_tradeable.get("next_close_expectancy"),
            ),
            "t_plus_2_close_payoff_ratio": _delta(
                baseline_tradeable.get("t_plus_2_close_payoff_ratio"),
                variant_tradeable.get("t_plus_2_close_payoff_ratio"),
            ),
            "t_plus_2_close_profit_factor": _delta(
                baseline_tradeable.get("t_plus_2_close_profit_factor"),
                variant_tradeable.get("t_plus_2_close_profit_factor"),
            ),
            "t_plus_2_close_expectancy": _delta(
                baseline_tradeable.get("t_plus_2_close_expectancy"),
                variant_tradeable.get("t_plus_2_close_expectancy"),
            ),
            "runner_capture_count": _delta(
                baseline_tradeable.get("runner_capture_count"),
                variant_tradeable.get("runner_capture_count"),
            ),
            "max_future_high_return_2_5d_hit_rate_at_20pct": _delta(
                baseline_tradeable.get("max_future_high_return_2_5d_hit_rate_at_20pct"),
                variant_tradeable.get("max_future_high_return_2_5d_hit_rate_at_20pct"),
            ),
            "max_future_high_return_2_5d_return_mean": _delta(
                dict(baseline_tradeable.get("max_future_high_return_2_5d_distribution") or {}).get("mean"),
                dict(variant_tradeable.get("max_future_high_return_2_5d_distribution") or {}).get("mean"),
            ),
        },
        "false_negative_proxy_delta": {
            "count": false_negative_delta,
            "next_high_hit_rate_at_threshold": _delta(
                dict(baseline_false_negative.get("surface_metrics") or {}).get("next_high_hit_rate_at_threshold"),
                dict(variant_false_negative.get("surface_metrics") or {}).get("next_high_hit_rate_at_threshold"),
            ),
            "next_close_positive_rate": _delta(
                dict(baseline_false_negative.get("surface_metrics") or {}).get("next_close_positive_rate"),
                dict(variant_false_negative.get("surface_metrics") or {}).get("next_close_positive_rate"),
            ),
        },
        "guardrail_status": guardrail_status,
        "comparison_note": comparison_note,
    }
