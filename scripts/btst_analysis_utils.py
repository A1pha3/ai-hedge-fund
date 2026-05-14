from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime as _datetime
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

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
    # Task 3 (Round 31, Beta): F13 — relative sector strength rank.
    # (sector_resonance + close_strength) / 2: individual stock's outperformance within its sector.
    # High value = sector rotation leader (强于板块的个股), most likely to lead sector moves.
    "rs_sector_rank",
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
        # Task 3 (Round 31, Beta): inject F13 rs_sector_rank = (sector_resonance + close_strength) / 2.
        sr = row.get("sector_resonance")
        cs = row.get("close_strength")
        if sr is not None and cs is not None:
            row["rs_sector_rank"] = (float(sr) + float(cs)) / 2.0
        else:
            row.setdefault("rs_sector_rank", None)
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


# ---------------------------------------------------------------------------
# Task 1 (Round 28, Alpha): Factor cross-correlation matrix analysis
# ---------------------------------------------------------------------------


def compute_factor_cross_correlation(rows: list[dict]) -> dict:
    """计算12个BTST因子的两两Spearman相关系数，识别冗余因子对。

    For each factor pair (i, j), uses only rows where **both** factors carry non-missing data.
    Pairs with fewer than 5 common observations are skipped.  Missing factor values are treated
    as absent (not filled), so F11/F12 cross-factors that may not be pre-computed in rows are
    gracefully excluded.

    Args:
        rows: BTST candidate rows.  Factor values are looked up directly by name from
            :data:`BTST_FACTOR_NAMES`.

    Returns:
        Dict with keys:

        - ``factor_max_correlation_pair``: tuple[str, str] | None — factor pair with highest |corr|.
        - ``factor_max_correlation``: float | None — corresponding Spearman correlation.
        - ``factor_min_correlation_pair``: tuple[str, str] | None — most orthogonal factor pair.
        - ``factor_min_correlation``: float | None — corresponding Spearman correlation (lowest |corr|).
        - ``high_correlation_pairs``: list[tuple[str, str, float]] — all pairs with |corr| > 0.70.
        - ``high_correlation_pair_count``: int — count of high-correlation pairs.
        - ``avg_pairwise_correlation``: float | None — mean |corr| across all computed pairs.
        - ``redundancy_warning_flag``: bool — True when high_correlation_pair_count > 3.
    """
    _null: dict = {"factor_max_correlation_pair": None, "factor_max_correlation": None, "factor_min_correlation_pair": None, "factor_min_correlation": None, "high_correlation_pairs": [], "high_correlation_pair_count": 0, "avg_pairwise_correlation": None, "redundancy_warning_flag": False}
    if not rows:
        return _null

    # Identify factors that appear in at least one row (graceful skip for absent cross-factors).
    available_factors: list[str] = [f for f in BTST_FACTOR_NAMES if any(row.get(f) is not None for row in rows)]
    n_factors = len(available_factors)
    if n_factors < 2:
        return _null

    # Compute C(n,2) pairwise Spearman correlations using only common non-missing observations.
    computed_pairs: list[tuple[str, str, float]] = []
    for i in range(n_factors):
        for j in range(i + 1, n_factors):
            fi = available_factors[i]
            fj = available_factors[j]
            xs: list[float] = []
            ys: list[float] = []
            for row in rows:
                vi = row.get(fi)
                vj = row.get(fj)
                if vi is not None and vj is not None:
                    xs.append(float(vi))
                    ys.append(float(vj))
            corr = _spearman_corr(xs, ys)
            if corr is not None:
                computed_pairs.append((fi, fj, corr))

    if not computed_pairs:
        return _null

    max_pair = max(computed_pairs, key=lambda t: abs(t[2]))
    min_pair = min(computed_pairs, key=lambda t: abs(t[2]))
    high_corr_pairs: list[tuple[str, str, float]] = [(fi, fj, corr) for fi, fj, corr in computed_pairs if abs(corr) > 0.70]
    avg_pairwise: float = round(sum(abs(t[2]) for t in computed_pairs) / len(computed_pairs), 4)

    return {
        "factor_max_correlation_pair": (max_pair[0], max_pair[1]),
        "factor_max_correlation": round(max_pair[2], 4),
        "factor_min_correlation_pair": (min_pair[0], min_pair[1]),
        "factor_min_correlation": round(min_pair[2], 4),
        "high_correlation_pairs": high_corr_pairs,
        "high_correlation_pair_count": len(high_corr_pairs),
        "avg_pairwise_correlation": avg_pairwise,
        "redundancy_warning_flag": len(high_corr_pairs) > 3,
    }


# ---------------------------------------------------------------------------
# Task 2 (Round 28, Gamma): Regime-domain Alpha consistency analysis
# ---------------------------------------------------------------------------


def compute_regime_alpha_consistency(rows: list[dict]) -> dict:
    """分别计算bull/bear/sideways三个市场环境下的Alpha表现。

    Uses ``hs300_daily_return`` as both the benchmark return and the regime classifier:
    bull day > +0.3 %, bear day < −0.3 %, sideways otherwise.
    Alpha per row = ``next_close_return`` − ``hs300_daily_return``.

    When ``hs300_daily_return`` is absent from all rows all fields return None.
    Domains with fewer than 5 samples return None for their alpha (and are excluded from
    consistency scoring).  When fewer than 2 domains have valid alpha, ``alpha_consistency_score``
    returns None.

    Args:
        rows: BTST candidate rows.  Fields used: ``next_close_return`` and ``hs300_daily_return``.

    Returns:
        Dict with keys:

        - ``bull_alpha_avg``: float | None — mean alpha on bull-market days (hs300 > +0.3 %).
        - ``bear_alpha_avg``: float | None — mean alpha on bear-market days (hs300 < −0.3 %).
        - ``sideways_alpha_avg``: float | None — mean alpha on sideways days.
        - ``alpha_consistency_score``: float | None — min_domain_alpha / max(|domain_alphas|); ∈ (−∞, 1].
        - ``all_regimes_positive_alpha``: bool — all valid-domain alphas > 0.
        - ``worst_regime_alpha``: float | None — lowest domain alpha among valid domains.
        - ``worst_regime``: str | None — "bull" | "bear" | "sideways".
        - ``alpha_regime_spread``: float | None — max_alpha − min_alpha across valid domains.
    """
    _null: dict = {"bull_alpha_avg": None, "bear_alpha_avg": None, "sideways_alpha_avg": None, "alpha_consistency_score": None, "all_regimes_positive_alpha": False, "worst_regime_alpha": None, "worst_regime": None, "alpha_regime_spread": None}
    if not any(row.get("hs300_daily_return") is not None for row in rows):
        return _null

    bull_alphas: list[float] = []
    bear_alphas: list[float] = []
    sideways_alphas: list[float] = []
    for row in rows:
        bm = row.get("hs300_daily_return")
        btst = row.get("next_close_return")
        if bm is None or btst is None:
            continue
        bm_f = float(bm)
        alpha = float(btst) - bm_f
        if bm_f > 0.003:
            bull_alphas.append(alpha)
        elif bm_f < -0.003:
            bear_alphas.append(alpha)
        else:
            sideways_alphas.append(alpha)

    bull_alpha_avg: float | None = round(sum(bull_alphas) / len(bull_alphas), 4) if len(bull_alphas) >= 5 else None
    bear_alpha_avg: float | None = round(sum(bear_alphas) / len(bear_alphas), 4) if len(bear_alphas) >= 5 else None
    sideways_alpha_avg: float | None = round(sum(sideways_alphas) / len(sideways_alphas), 4) if len(sideways_alphas) >= 5 else None

    valid: dict[str, float] = {k: v for k, v in {"bull": bull_alpha_avg, "bear": bear_alpha_avg, "sideways": sideways_alpha_avg}.items() if v is not None}

    worst_regime: str | None = min(valid, key=lambda k: valid[k]) if valid else None
    worst_regime_alpha: float | None = valid[worst_regime] if worst_regime is not None else None

    if len(valid) < 2:
        return {"bull_alpha_avg": bull_alpha_avg, "bear_alpha_avg": bear_alpha_avg, "sideways_alpha_avg": sideways_alpha_avg, "alpha_consistency_score": None, "all_regimes_positive_alpha": False, "worst_regime_alpha": worst_regime_alpha, "worst_regime": worst_regime, "alpha_regime_spread": None}

    vals = list(valid.values())
    min_alpha = min(vals)
    max_alpha = max(vals)
    max_abs = max(abs(a) for a in vals)
    alpha_consistency_score: float | None = round(min_alpha / max_abs, 4) if max_abs > 0.0 else None
    all_regimes_positive_alpha: bool = all(a > 0.0 for a in vals)
    alpha_regime_spread: float = round(max_alpha - min_alpha, 4)

    return {
        "bull_alpha_avg": bull_alpha_avg,
        "bear_alpha_avg": bear_alpha_avg,
        "sideways_alpha_avg": sideways_alpha_avg,
        "alpha_consistency_score": alpha_consistency_score,
        "all_regimes_positive_alpha": all_regimes_positive_alpha,
        "worst_regime_alpha": worst_regime_alpha,
        "worst_regime": worst_regime,
        "alpha_regime_spread": alpha_regime_spread,
    }


# ---------------------------------------------------------------------------
# Task 3 (Round 28, Beta): Post-loss recovery rate analysis
# ---------------------------------------------------------------------------


def compute_post_loss_recovery_analysis(rows: list[dict]) -> dict:
    """分析T+1亏损后T+2/T+3的恢复模式。

    Only analyses the loss subset where ``next_close_return < 0``.  When the loss
    subset has fewer than 5 rows, most outputs return None.

    Args:
        rows: BTST candidate rows.  Fields used: ``next_close_return`` (T+1),
            ``t_plus_2_close_return`` (T+2), ``t_plus_3_close_return`` (T+3).

    Returns:
        Dict with keys:

        - ``loss_sample_count``: int — number of T+1 loss rows.
        - ``post_loss_t2_positive_rate``: float | None — fraction of loss rows where T+2 > 0.
        - ``post_loss_t2_avg_return``: float | None — mean T+2 return for loss rows.
        - ``post_loss_t3_avg_return``: float | None — mean T+3 return for loss rows.
        - ``mean_reversion_signal``: bool — post_loss_t2_positive_rate > 0.55.
        - ``momentum_continuation_signal``: bool — post_loss_t2_positive_rate < 0.45.
        - ``recovery_expected_value``: float | None — t1_loss_avg × (1 + post_loss_t2_avg_return).
        - ``hold_through_loss_beneficial``: bool — post_loss_t2_avg_return > |t1_loss_avg| × 0.30.
    """
    _null: dict = {"loss_sample_count": 0, "post_loss_t2_positive_rate": None, "post_loss_t2_avg_return": None, "post_loss_t3_avg_return": None, "mean_reversion_signal": False, "momentum_continuation_signal": False, "recovery_expected_value": None, "hold_through_loss_beneficial": False}
    loss_rows: list[dict] = [row for row in rows if row.get("next_close_return") is not None and float(row["next_close_return"]) < 0.0]
    n_loss: int = len(loss_rows)
    if n_loss < 5:
        return {**_null, "loss_sample_count": n_loss}

    t1_losses: list[float] = [float(row["next_close_return"]) for row in loss_rows]
    t1_loss_avg: float = sum(t1_losses) / len(t1_losses)

    # T+2 metrics — use only loss rows that also carry a T+2 close return.
    t2_eligible: list[dict] = [row for row in loss_rows if row.get("t_plus_2_close_return") is not None]
    if t2_eligible:
        t2_rets: list[float] = [float(row["t_plus_2_close_return"]) for row in t2_eligible]
        post_loss_t2_positive_rate: float | None = round(sum(1 for r in t2_rets if r > 0.0) / len(t2_rets), 4)
        post_loss_t2_avg_return: float | None = round(sum(t2_rets) / len(t2_rets), 4)
    else:
        post_loss_t2_positive_rate = None
        post_loss_t2_avg_return = None

    # T+3 metrics — use only loss rows that also carry a T+3 close return.
    t3_eligible: list[dict] = [row for row in loss_rows if row.get("t_plus_3_close_return") is not None]
    post_loss_t3_avg_return: float | None = round(sum(float(row["t_plus_3_close_return"]) for row in t3_eligible) / len(t3_eligible), 4) if t3_eligible else None

    mean_reversion_signal: bool = post_loss_t2_positive_rate is not None and post_loss_t2_positive_rate > 0.55
    momentum_continuation_signal: bool = post_loss_t2_positive_rate is not None and post_loss_t2_positive_rate < 0.45

    recovery_expected_value: float | None = round(t1_loss_avg * (1.0 + post_loss_t2_avg_return), 4) if post_loss_t2_avg_return is not None else None
    hold_through_loss_beneficial: bool = post_loss_t2_avg_return is not None and post_loss_t2_avg_return > abs(t1_loss_avg) * 0.30

    return {
        "loss_sample_count": n_loss,
        "post_loss_t2_positive_rate": post_loss_t2_positive_rate,
        "post_loss_t2_avg_return": post_loss_t2_avg_return,
        "post_loss_t3_avg_return": post_loss_t3_avg_return,
        "mean_reversion_signal": mean_reversion_signal,
        "momentum_continuation_signal": momentum_continuation_signal,
        "recovery_expected_value": recovery_expected_value,
        "hold_through_loss_beneficial": hold_through_loss_beneficial,
    }


# ---------------------------------------------------------------------------
# Task 1 (Round 29, Alpha): PCA因子正交化分析
# ---------------------------------------------------------------------------


def compute_factor_pca_analysis(rows: list[dict]) -> dict:
    """PCA因子正交化分析：对12个BTST因子做主成分分析，量化独立信号维度数量。

    Uses numpy SVD (no sklearn). F11/F12 (momentum_confirmation_score, volume_momentum_score)
    are included only when present in at least one row; otherwise gracefully skipped.
    Requires at least 10 aligned rows (all active factors non-missing); returns None fields otherwise.

    Args:
        rows: BTST candidate rows. Factor values looked up via BTST_FACTOR_NAMES.

    Returns:
        Dict with keys:

        - ``effective_factor_rank``: int | None — minimum PCs needed to explain ≥ 80 % variance.
        - ``pca_diversity_score``: float | None — effective_factor_rank / k (0=all-same, 1=fully-orthogonal).
        - ``pc1_dominant_factors``: list[str] — top-3 factors by |loading| on PC1 (main shared driver).
        - ``redundancy_reduction_candidates``: list[str] — factors with |PC1 loading| > 0.40 (co-move with PC1).
        - ``explained_variance_ratio``: list[float] | None — per-PC explained variance fraction.
    """
    _null: dict = {"effective_factor_rank": None, "pca_diversity_score": None, "pc1_dominant_factors": [], "redundancy_reduction_candidates": [], "explained_variance_ratio": None}
    if len(rows) < 10:
        return _null
    # Identify factors present in at least one row (graceful skip for absent cross-factors F11/F12).
    available: list[str] = [f for f in BTST_FACTOR_NAMES if any(row.get(f) is not None for row in rows)]
    k = len(available)
    if k < 2:
        return _null
    # Build aligned matrix: only rows where ALL k factors are non-missing.
    aligned: list[list[float]] = []
    for row in rows:
        vals = [row.get(f) for f in available]
        if any(v is None for v in vals):
            continue
        try:
            aligned.append([float(v) for v in vals])  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    n = len(aligned)
    if n < 10:
        return _null
    # Standardise (mean=0, std=1); skip columns with near-zero variance.
    X = np.array(aligned, dtype=float)  # (n, k)
    col_means = X.mean(axis=0)
    col_stds = X.std(axis=0)
    active_cols: list[int] = [j for j in range(k) if col_stds[j] > 1e-8]
    if len(active_cols) < 2:
        return _null
    X_s = (X[:, active_cols] - col_means[active_cols]) / col_stds[active_cols]
    active_factors: list[str] = [available[j] for j in active_cols]
    ka = len(active_cols)
    # SVD-based PCA: X_s = U S Vt; rows of Vt are principal components (PC loadings).
    U, S, Vt = np.linalg.svd(X_s, full_matrices=False)
    ev = S ** 2
    evr_arr = ev / ev.sum()
    evr: list[float] = evr_arr.tolist()
    # effective_factor_rank = number of PCs needed to reach 80 % cumulative explained variance.
    cumvar = 0.0
    effective_factor_rank: int = ka
    for idx, ratio in enumerate(evr):
        cumvar += ratio
        if cumvar >= 0.80:
            effective_factor_rank = idx + 1
            break
    pca_diversity_score = round(effective_factor_rank / ka, 4)
    # PC1 loadings = first row of Vt (absolute values = factor contribution to PC1).
    pc1_abs: list[tuple[str, float]] = [(active_factors[j], float(abs(Vt[0, j]))) for j in range(ka)]
    pc1_sorted = sorted(pc1_abs, key=lambda t: t[1], reverse=True)
    pc1_dominant_factors: list[str] = [name for name, _ in pc1_sorted[:3]]
    redundancy_reduction_candidates: list[str] = [name for name, v in pc1_abs if v > 0.40]
    return {
        "effective_factor_rank": int(effective_factor_rank),
        "pca_diversity_score": pca_diversity_score,
        "pc1_dominant_factors": pc1_dominant_factors,
        "redundancy_reduction_candidates": redundancy_reduction_candidates,
        "explained_variance_ratio": [round(v, 4) for v in evr],
    }


# ---------------------------------------------------------------------------
# Task 2 (Round 29, Gamma): 样本内外差距检测
# ---------------------------------------------------------------------------


def compute_in_sample_oos_gap(rows: list[dict]) -> dict:
    """检测样本内外（IS/OOS）性能差距，防止参数过拟合。

    Chronological 70/30 split (sorted by ``date``): first 70 % rows = in-sample (IS),
    last 30 % = out-of-sample (OOS).  Requires at least 5 rows in each set.

    Args:
        rows: BTST candidate rows. Fields used: ``date`` (YYYY-MM-DD), ``next_close_return``.

    Returns:
        Dict with keys:

        - ``is_win_rate`` / ``oos_win_rate``: float | None — T+1 win rate in IS/OOS.
        - ``win_rate_gap``: float | None — IS − OOS win rate.
        - ``is_avg_return`` / ``oos_avg_return``: float | None — mean T+1 return in IS/OOS.
        - ``return_gap``: float | None — IS − OOS avg return.
        - ``overfit_score``: float | None — normalised IS/OOS gap (≈0 = no overfit).
        - ``overfit_warning_flag``: bool — True when overfit_score > 0.20.
    """
    _null: dict = {"is_win_rate": None, "oos_win_rate": None, "win_rate_gap": None, "is_avg_return": None, "oos_avg_return": None, "return_gap": None, "overfit_score": None, "overfit_warning_flag": False}
    valid: list[dict] = [row for row in rows if row.get("date") is not None and row.get("next_close_return") is not None]
    if not valid:
        return _null
    try:
        valid_sorted = sorted(valid, key=lambda r: str(r["date"]))
    except Exception:
        return _null
    n = len(valid_sorted)
    split = max(1, int(n * 0.70))
    is_rows = valid_sorted[:split]
    oos_rows = valid_sorted[split:]
    if len(is_rows) < 5 or len(oos_rows) < 5:
        return _null

    def _stats(subset: list[dict]) -> tuple[float, float]:
        rets = [float(r["next_close_return"]) for r in subset]
        wr = sum(1 for v in rets if v > 0.0) / len(rets)
        ar = sum(rets) / len(rets)
        return wr, ar

    is_wr, is_ar = _stats(is_rows)
    oos_wr, oos_ar = _stats(oos_rows)
    win_rate_gap = round(is_wr - oos_wr, 4)
    return_gap = round(is_ar - oos_ar, 4)
    # Normalised composite overfit score: each component is gap / IS-value (capped by small epsilon).
    overfit_score = round(0.5 * win_rate_gap / max(is_wr, 0.01) + 0.5 * return_gap / max(is_ar, 0.001), 4)
    return {
        "is_win_rate": round(is_wr, 4),
        "oos_win_rate": round(oos_wr, 4),
        "win_rate_gap": win_rate_gap,
        "is_avg_return": round(is_ar, 4),
        "oos_avg_return": round(oos_ar, 4),
        "return_gap": return_gap,
        "overfit_score": overfit_score,
        "overfit_warning_flag": overfit_score > 0.20,
    }


# ---------------------------------------------------------------------------
# Task 3 (Round 29, Beta): 星期效应分析
# ---------------------------------------------------------------------------


def compute_weekday_performance_analysis(rows: list[dict]) -> dict:
    """按交易星期（周一到周五）分析BTST胜率和平均收益，识别A股日历效应。

    Uses ``date`` (YYYY-MM-DD format) and ``next_close_return`` fields.
    Weekday encoding: 0=Monday, 1=Tuesday, ..., 4=Friday.
    A weekday is included only when it has ≥ 5 samples; weekdays with fewer observations
    are excluded from spread / best / worst calculations.  When fewer than 2 weekdays
    have valid samples, most aggregated fields return None.

    Args:
        rows: BTST candidate rows.

    Returns:
        Dict with keys:

        - ``weekday_win_rates``: dict[int, float] — win rate per valid weekday.
        - ``weekday_avg_returns``: dict[int, float] — mean return per valid weekday.
        - ``best_weekday``: int | None — weekday with highest win rate (0–4).
        - ``worst_weekday``: int | None — weekday with lowest win rate (0–4).
        - ``weekday_best_win_rate``: float | None
        - ``weekday_worst_win_rate``: float | None
        - ``weekday_win_rate_spread``: float | None — max − min win rate across valid weekdays.
        - ``recommended_avoid_weekday``: int | None — equals worst_weekday.
        - ``calendar_effect_strong``: bool — True when spread > 0.10.
    """
    _null: dict = {"weekday_win_rates": {}, "weekday_avg_returns": {}, "best_weekday": None, "worst_weekday": None, "weekday_best_win_rate": None, "weekday_worst_win_rate": None, "weekday_win_rate_spread": None, "recommended_avoid_weekday": None, "calendar_effect_strong": False}
    buckets: dict[int, list[float]] = {d: [] for d in range(5)}
    for row in rows:
        date_val = row.get("date")
        ret_val = row.get("next_close_return")
        if date_val is None or ret_val is None:
            continue
        try:
            wd = _datetime.strptime(str(date_val), "%Y-%m-%d").weekday()
            buckets[wd].append(float(ret_val))
        except (ValueError, TypeError):
            continue
    weekday_win_rates: dict[int, float] = {}
    weekday_avg_returns: dict[int, float] = {}
    for wd, rets in buckets.items():
        if len(rets) < 5:
            continue
        weekday_win_rates[wd] = round(sum(1 for r in rets if r > 0.0) / len(rets), 4)
        weekday_avg_returns[wd] = round(sum(rets) / len(rets), 4)
    if len(weekday_win_rates) < 2:
        return {**_null, "weekday_win_rates": weekday_win_rates, "weekday_avg_returns": weekday_avg_returns}
    best_wd = max(weekday_win_rates, key=lambda d: weekday_win_rates[d])
    worst_wd = min(weekday_win_rates, key=lambda d: weekday_win_rates[d])
    spread = round(weekday_win_rates[best_wd] - weekday_win_rates[worst_wd], 4)
    return {
        "weekday_win_rates": weekday_win_rates,
        "weekday_avg_returns": weekday_avg_returns,
        "best_weekday": best_wd,
        "worst_weekday": worst_wd,
        "weekday_best_win_rate": weekday_win_rates[best_wd],
        "weekday_worst_win_rate": weekday_win_rates[worst_wd],
        "weekday_win_rate_spread": spread,
        "recommended_avoid_weekday": worst_wd,
        "calendar_effect_strong": spread > 0.10,
    }


# ---------------------------------------------------------------------------
# Round 30, Task 2 (Alpha): 月份效应分析 — monthly calendar-effect analysis.
# Identifies best/worst trading month (1-12) by T+1 win rate; seasonal_effect_strong when spread > 0.10.
# ---------------------------------------------------------------------------


def compute_monthly_performance_analysis(rows: list[dict]) -> dict:
    """按月份（1-12）分析BTST胜率和平均收益，识别A股市场月历效应（1月效应等）。

    Uses ``date`` (YYYY-MM-DD format) and ``next_close_return`` fields.
    A month is included only when it has ≥ 5 samples; months with fewer observations
    are excluded from spread / best / worst calculations.  When fewer than 2 months
    have valid samples, most aggregated fields return None.

    Args:
        rows: BTST candidate rows.

    Returns:
        Dict with keys:

        - ``monthly_win_rates``: dict[int, float] — win rate per valid month (1-12).
        - ``monthly_avg_returns``: dict[int, float] — mean return per valid month.
        - ``best_month``: int | None — month with highest win rate.
        - ``worst_month``: int | None — month with lowest win rate.
        - ``monthly_win_rate_spread``: float | None — max − min win rate across valid months.
        - ``january_effect_present``: bool — True when month-1 win rate > mean × 1.05 and month 1 is valid.
        - ``seasonal_effect_strong``: bool — True when spread > 0.10.
    """
    _null: dict = {
        "monthly_win_rates": {},
        "monthly_avg_returns": {},
        "best_month": None,
        "worst_month": None,
        "monthly_win_rate_spread": None,
        "january_effect_present": False,
        "seasonal_effect_strong": False,
    }
    buckets: dict[int, list[float]] = {m: [] for m in range(1, 13)}
    for row in rows:
        date_val = row.get("date")
        ret_val = row.get("next_close_return")
        if date_val is None or ret_val is None:
            continue
        try:
            month = _datetime.strptime(str(date_val), "%Y-%m-%d").month
            buckets[month].append(float(ret_val))
        except (ValueError, TypeError):
            continue
    monthly_win_rates: dict[int, float] = {}
    monthly_avg_returns: dict[int, float] = {}
    for month, rets in buckets.items():
        if len(rets) < 5:
            continue
        monthly_win_rates[month] = round(sum(1 for r in rets if r > 0.0) / len(rets), 4)
        monthly_avg_returns[month] = round(sum(rets) / len(rets), 4)
    if len(monthly_win_rates) < 2:
        return {**_null, "monthly_win_rates": monthly_win_rates, "monthly_avg_returns": monthly_avg_returns}
    best_m = max(monthly_win_rates, key=lambda m: monthly_win_rates[m])
    worst_m = min(monthly_win_rates, key=lambda m: monthly_win_rates[m])
    spread = round(monthly_win_rates[best_m] - monthly_win_rates[worst_m], 4)
    mean_wr = sum(monthly_win_rates.values()) / len(monthly_win_rates)
    jan_present = bool(1 in monthly_win_rates and monthly_win_rates[1] > mean_wr * 1.05)
    return {
        "monthly_win_rates": monthly_win_rates,
        "monthly_avg_returns": monthly_avg_returns,
        "best_month": best_m,
        "worst_month": worst_m,
        "monthly_win_rate_spread": spread,
        "january_effect_present": jan_present,
        "seasonal_effect_strong": spread > 0.10,
    }


# ---------------------------------------------------------------------------
# Round 30, Task 3 (Beta): 因子非线性检测 — factor nonlinearity detection.
# Detects U-shaped / threshold effects via tertile-split deviation from linearity.
# ---------------------------------------------------------------------------


def compute_factor_nonlinearity(rows: list[dict]) -> dict:
    """检测每个BTST因子与T+1收益之间是否存在非线性关系（三分位阈值效应检测）。

    Splits each factor into low/mid/high tertiles (P33/P67) and measures how
    much the mid-tertile mean return deviates from the linear interpolation
    between the low and high tertile means.

    Args:
        rows: BTST candidate rows with factor values and ``next_close_return``.

    Returns:
        Dict with keys:

        - ``nonlinear_factor_names``: list[str] — factors with nonlinearity_ratio > 0.30.
        - ``nonlinear_factor_count``: int — number of nonlinear factors.
        - ``most_nonlinear_factor``: str | None — factor with highest nonlinearity_ratio.
        - ``avg_nonlinearity_ratio``: float | None — mean ratio across all valid factors.
        - ``binning_recommended_factors``: list[str] — same as nonlinear_factor_names.
    """
    _null: dict = {
        "nonlinear_factor_names": [],
        "nonlinear_factor_count": 0,
        "most_nonlinear_factor": None,
        "avg_nonlinearity_ratio": None,
        "binning_recommended_factors": [],
    }
    valid_rows = [row for row in rows if row.get("next_close_return") is not None]
    if len(valid_rows) < 15:
        return _null

    nonlinearity_ratios: dict[str, float] = {}
    for factor in BTST_FACTOR_NAMES:
        paired: list[tuple[float, float]] = []
        for row in valid_rows:
            fv = row.get(factor)
            rv = row.get("next_close_return")
            if fv is None or rv is None:
                continue
            try:
                paired.append((float(fv), float(rv)))
            except (TypeError, ValueError):
                continue
        if len(paired) < 15:
            continue
        factor_vals = [p[0] for p in paired]
        n = len(factor_vals)
        sorted_fv = sorted(factor_vals)
        p33 = sorted_fv[int(n * 1 / 3)]
        p67 = sorted_fv[int(n * 2 / 3)]
        low_rets = [rv for fv, rv in paired if fv <= p33]
        mid_rets = [rv for fv, rv in paired if p33 < fv <= p67]
        high_rets = [rv for fv, rv in paired if fv > p67]
        if len(low_rets) < 5 or len(mid_rets) < 5 or len(high_rets) < 5:
            continue
        mean_low = sum(low_rets) / len(low_rets)
        mean_mid = sum(mid_rets) / len(mid_rets)
        mean_high = sum(high_rets) / len(high_rets)
        linear_score = abs(mean_high - mean_low)
        nonlinear_deviation = abs(mean_mid - (mean_high + mean_low) / 2.0)
        nonlinearity_ratio = nonlinear_deviation / max(linear_score, 0.001)
        nonlinearity_ratios[factor] = round(nonlinearity_ratio, 4)

    if not nonlinearity_ratios:
        return _null

    nonlinear_names = [f for f, r in nonlinearity_ratios.items() if r > 0.30]
    most_nonlinear = max(nonlinearity_ratios, key=lambda f: nonlinearity_ratios[f])
    avg_ratio = round(sum(nonlinearity_ratios.values()) / len(nonlinearity_ratios), 4)
    return {
        "nonlinear_factor_names": nonlinear_names,
        "nonlinear_factor_count": len(nonlinear_names),
        "most_nonlinear_factor": most_nonlinear,
        "avg_nonlinearity_ratio": avg_ratio,
        "binning_recommended_factors": nonlinear_names,
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
    # Round 28, Task 1 (Alpha): Factor cross-correlation matrix.
    # Computes C(12,2)=66 pairwise Spearman correlations across BTST_FACTOR_NAMES.
    # Uses all rows (not just next_day_rows) to maximise sample coverage.
    # -----------------------------------------------------------------------
    _factor_cross_corr: dict[str, Any] = compute_factor_cross_correlation(rows)
    _surface_result["factor_cross_correlation"] = _factor_cross_corr
    _surface_result["factor_max_correlation"] = _factor_cross_corr.get("factor_max_correlation")
    _surface_result["high_correlation_pair_count"] = _factor_cross_corr.get("high_correlation_pair_count")
    _surface_result["avg_pairwise_correlation"] = _factor_cross_corr.get("avg_pairwise_correlation")
    _surface_result["redundancy_warning_flag"] = _factor_cross_corr.get("redundancy_warning_flag")
    # -----------------------------------------------------------------------
    # Round 28, Task 2 (Gamma): Regime-domain Alpha consistency.
    # Splits next_day_rows into bull/bear/sideways by hs300_daily_return and
    # measures whether the strategy alpha is positive in all three domains.
    # -----------------------------------------------------------------------
    _regime_alpha_consistency: dict[str, Any] = compute_regime_alpha_consistency(next_day_rows)
    _surface_result["regime_alpha_consistency"] = _regime_alpha_consistency
    _surface_result["bull_alpha_avg"] = _regime_alpha_consistency.get("bull_alpha_avg")
    _surface_result["bear_alpha_avg"] = _regime_alpha_consistency.get("bear_alpha_avg")
    _surface_result["sideways_alpha_avg"] = _regime_alpha_consistency.get("sideways_alpha_avg")
    _surface_result["alpha_consistency_score"] = _regime_alpha_consistency.get("alpha_consistency_score")
    _surface_result["all_regimes_positive_alpha"] = _regime_alpha_consistency.get("all_regimes_positive_alpha")
    _surface_result["worst_regime_alpha"] = _regime_alpha_consistency.get("worst_regime_alpha")
    _surface_result["alpha_regime_spread"] = _regime_alpha_consistency.get("alpha_regime_spread")
    # -----------------------------------------------------------------------
    # Round 28, Task 3 (Beta): Post-loss recovery rate analysis.
    # Identifies whether T+1 losses are followed by T+2 mean-reversion or
    # momentum continuation — directly informing multi-day hold decisions.
    # -----------------------------------------------------------------------
    _post_loss_recovery: dict[str, Any] = compute_post_loss_recovery_analysis(rows)
    _surface_result["post_loss_recovery"] = _post_loss_recovery
    _surface_result["post_loss_t2_positive_rate"] = _post_loss_recovery.get("post_loss_t2_positive_rate")
    _surface_result["post_loss_t2_avg_return"] = _post_loss_recovery.get("post_loss_t2_avg_return")
    _surface_result["mean_reversion_signal"] = _post_loss_recovery.get("mean_reversion_signal")
    _surface_result["hold_through_loss_beneficial"] = _post_loss_recovery.get("hold_through_loss_beneficial")
    # -----------------------------------------------------------------------
    # Round 29, Task 1 (Alpha): PCA因子正交化分析.
    # Quantifies the true number of independent signal dimensions across all BTST factors.
    # effective_factor_rank = min PCs to explain ≥ 80 % variance (floor ≥ 3).
    # pca_diversity_score = effective_factor_rank / k — closer to 1 means more orthogonal factors.
    # -----------------------------------------------------------------------
    _factor_pca: dict[str, Any] = compute_factor_pca_analysis(rows)
    _surface_result["factor_pca_analysis"] = _factor_pca
    _surface_result["effective_factor_rank"] = _factor_pca.get("effective_factor_rank")
    _surface_result["pca_diversity_score"] = _factor_pca.get("pca_diversity_score")
    _surface_result["pc1_dominant_factors"] = _factor_pca.get("pc1_dominant_factors")
    _surface_result["redundancy_reduction_candidates"] = _factor_pca.get("redundancy_reduction_candidates")
    # -----------------------------------------------------------------------
    # Round 29, Task 2 (Gamma): 样本内外差距检测 — IS/OOS overfit detection.
    # Chronological 70/30 split; overfit_score > 0.30 triggers cap breach.
    # -----------------------------------------------------------------------
    _oos_gap: dict[str, Any] = compute_in_sample_oos_gap(rows)
    _surface_result["in_sample_oos_gap"] = _oos_gap
    _surface_result["overfit_score"] = _oos_gap.get("overfit_score")
    _surface_result["win_rate_gap"] = _oos_gap.get("win_rate_gap")
    _surface_result["overfit_warning_flag"] = _oos_gap.get("overfit_warning_flag")
    _surface_result["is_win_rate"] = _oos_gap.get("is_win_rate")
    _surface_result["oos_win_rate"] = _oos_gap.get("oos_win_rate")
    # -----------------------------------------------------------------------
    # Round 29, Task 3 (Beta): 星期效应分析 — weekday calendar-effect analysis.
    # Identifies best/worst trading weekday by T+1 win rate; calendar_effect_strong when spread > 0.10.
    # -----------------------------------------------------------------------
    _weekday_perf: dict[str, Any] = compute_weekday_performance_analysis(rows)
    _surface_result["weekday_performance"] = _weekday_perf
    _surface_result["weekday_win_rate_spread"] = _weekday_perf.get("weekday_win_rate_spread")
    _surface_result["best_weekday"] = _weekday_perf.get("best_weekday")
    _surface_result["worst_weekday"] = _weekday_perf.get("worst_weekday")
    _surface_result["calendar_effect_strong"] = _weekday_perf.get("calendar_effect_strong")
    _surface_result["recommended_avoid_weekday"] = _weekday_perf.get("recommended_avoid_weekday")
    # -----------------------------------------------------------------------
    # Round 30, Task 2 (Alpha): 月份效应分析 — monthly calendar-effect analysis.
    # Identifies best/worst month by T+1 win rate; seasonal_effect_strong when spread > 0.10.
    # -----------------------------------------------------------------------
    _monthly_perf: dict[str, Any] = compute_monthly_performance_analysis(rows)
    _surface_result["monthly_performance"] = _monthly_perf
    _surface_result["monthly_win_rate_spread"] = _monthly_perf.get("monthly_win_rate_spread")
    _surface_result["best_month"] = _monthly_perf.get("best_month")
    _surface_result["worst_month"] = _monthly_perf.get("worst_month")
    _surface_result["january_effect_present"] = _monthly_perf.get("january_effect_present")
    _surface_result["seasonal_effect_strong"] = _monthly_perf.get("seasonal_effect_strong")
    # -----------------------------------------------------------------------
    # Round 30, Task 3 (Beta): 因子非线性检测 — factor nonlinearity detection.
    # Tertile-split deviation analysis; nonlinear_factor_count lower-is-better.
    # -----------------------------------------------------------------------
    _factor_nonlin: dict[str, Any] = compute_factor_nonlinearity(rows)
    _surface_result["factor_nonlinearity"] = _factor_nonlin
    _surface_result["nonlinear_factor_count"] = _factor_nonlin.get("nonlinear_factor_count")
    _surface_result["avg_nonlinearity_ratio"] = _factor_nonlin.get("avg_nonlinearity_ratio")
    _surface_result["most_nonlinear_factor"] = _factor_nonlin.get("most_nonlinear_factor")
    _surface_result["nonlinear_factor_names"] = _factor_nonlin.get("nonlinear_factor_names")
    # -----------------------------------------------------------------------
    # Round 31, Task 1 (Alpha): Factor return time-series autocorrelation.
    # Detects regime persistence (momentum) or mean-reversion in the return series.
    # -----------------------------------------------------------------------
    # Inject rs_sector_rank before computing autocorr (F13 needed in rows).
    for _row in rows:
        _sr = _row.get("sector_resonance")
        _cs = _row.get("close_strength")
        if _sr is not None and _cs is not None:
            _row["rs_sector_rank"] = (float(_sr) + float(_cs)) / 2.0
    _return_autocorr: dict[str, Any] = compute_factor_return_autocorr(next_day_rows)
    _surface_result["return_autocorr"] = _return_autocorr
    _surface_result["autocorr_lag1"] = _return_autocorr.get("autocorr_lag1")
    _surface_result["autocorr_lag2"] = _return_autocorr.get("autocorr_lag2")
    _surface_result["longest_win_streak"] = _return_autocorr.get("longest_win_streak")
    _surface_result["longest_loss_streak"] = _return_autocorr.get("longest_loss_streak")
    _surface_result["autocorr_significant"] = _return_autocorr.get("autocorr_significant")
    _surface_result["momentum_persistence"] = _return_autocorr.get("momentum_persistence")
    _surface_result["mean_reversion_tendency"] = _return_autocorr.get("mean_reversion_tendency")

    _health: dict[str, Any] = compute_profile_health_score(_surface_result)
    _surface_result["profile_health_score"] = _health["profile_health_score"]
    _surface_result["profile_health_grade"] = _health["profile_health_grade"]
    _surface_result["health_subscores"] = _health["health_subscores"]
    _surface_result["health_weakest_area"] = _health["health_weakest_area"]
    _surface_result["health_strongest_area"] = _health["health_strongest_area"]

    # -----------------------------------------------------------------------
    # Round 32, Task 1 (Gamma): Conditional tail-risk analysis.
    # Quantifies P(deep loss | high-score) vs P(deep loss | low-score).
    # -----------------------------------------------------------------------
    _ctr: dict[str, Any] = compute_conditional_tail_risk(next_day_rows)
    _surface_result["conditional_tail_risk"] = _ctr
    _surface_result["high_score_tail_loss_rate"] = _ctr.get("high_score_tail_loss_rate")
    _surface_result["high_score_cvar_5pct"] = _ctr.get("high_score_cvar_5pct")
    _surface_result["high_score_upside_5pct"] = _ctr.get("high_score_upside_5pct")
    _surface_result["tail_risk_asymmetry"] = _ctr.get("tail_risk_asymmetry")
    _surface_result["low_score_tail_loss_rate"] = _ctr.get("low_score_tail_loss_rate")
    _surface_result["low_score_cvar_5pct"] = _ctr.get("low_score_cvar_5pct")
    _surface_result["score_tail_separation"] = _ctr.get("score_tail_separation")
    _surface_result["tail_risk_well_controlled"] = _ctr.get("tail_risk_well_controlled")

    # -----------------------------------------------------------------------
    # Round 32, Task 2 (Alpha): Volume anomaly detection.
    # Detects whether放量/inflow correlates with higher win rates.
    # -----------------------------------------------------------------------
    _vam: dict[str, Any] = compute_volume_anomaly_metrics(next_day_rows)
    _surface_result["volume_anomaly_metrics"] = _vam
    _surface_result["volume_low_win_rate"] = _vam.get("volume_low_win_rate")
    _surface_result["volume_mid_win_rate"] = _vam.get("volume_mid_win_rate")
    _surface_result["volume_high_win_rate"] = _vam.get("volume_high_win_rate")
    _surface_result["volume_monotone_win_rate"] = _vam.get("volume_monotone_win_rate")
    _surface_result["extreme_volume_win_rate_premium"] = _vam.get("extreme_volume_win_rate_premium")
    _surface_result["inflow_low_win_rate"] = _vam.get("inflow_low_win_rate")
    _surface_result["inflow_high_win_rate"] = _vam.get("inflow_high_win_rate")
    _surface_result["inflow_win_rate_premium"] = _vam.get("inflow_win_rate_premium")
    _surface_result["volume_inflow_alignment"] = _vam.get("volume_inflow_alignment")

    # -----------------------------------------------------------------------
    # Round 32, Task 3 (Beta): Composite gate score.
    # Must be called LAST — reads all previously computed surface metrics.
    # -----------------------------------------------------------------------
    _gate: dict[str, Any] = compute_composite_gate_score(_surface_result)
    _surface_result["composite_gate_score"] = _gate.get("composite_gate_score")
    _surface_result["gate_score_grade"] = _gate.get("gate_score_grade")
    _surface_result["trade_recommended"] = _gate.get("trade_recommended")
    _surface_result["gate_score_components"] = _gate.get("gate_score_components")

    # -----------------------------------------------------------------------
    # Round 33, Task 1 (Alpha): Expected value per trade.
    # -----------------------------------------------------------------------
    _ev: dict[str, Any] = compute_expected_value_metrics(next_day_rows)
    _surface_result["expected_value_per_trade"] = _ev.get("expected_value_per_trade")
    _surface_result["win_rate_ev"] = _ev.get("win_rate_ev")
    _surface_result["avg_win_return_ev"] = _ev.get("avg_win_return")
    _surface_result["avg_loss_return_ev"] = _ev.get("avg_loss_return")
    _surface_result["payoff_ratio_ev"] = _ev.get("payoff_ratio_ev")
    _surface_result["ev_positive"] = _ev.get("ev_positive")
    _surface_result["ev_grade"] = _ev.get("ev_grade")

    # -----------------------------------------------------------------------
    # Round 33, Task 2 (Gamma): Momentum decay curve.
    # -----------------------------------------------------------------------
    _mdc: dict[str, Any] = compute_momentum_decay_curve(rows)
    _surface_result["momentum_half_life_days"] = _mdc.get("momentum_half_life_days")
    _surface_result["avg_t1_abs"] = _mdc.get("avg_t1_abs")
    _surface_result["avg_t2_abs"] = _mdc.get("avg_t2_abs")
    _surface_result["avg_t3_abs"] = _mdc.get("avg_t3_abs")
    _surface_result["momentum_persists"] = _mdc.get("momentum_persists")
    _surface_result["decay_speed"] = _mdc.get("decay_speed")
    _surface_result["decay_curve_valid"] = _mdc.get("decay_curve_valid")

    # -----------------------------------------------------------------------
    # Round 34, Task 1 (Alpha): Multi-factor conditional joint effect.
    # -----------------------------------------------------------------------
    _cfc: dict[str, Any] = compute_cross_factor_conditional(rows)
    _surface_result["multi_factor_lift"] = _cfc.get("multi_factor_lift")
    _surface_result["multi_factor_synergy"] = _cfc.get("multi_factor_synergy")
    _surface_result["optimal_factor_count"] = _cfc.get("optimal_factor_count")
    _surface_result["cross_factor_group_win_rates"] = _cfc.get("group_win_rates")
    _surface_result["cross_factor_group_counts"] = _cfc.get("group_counts")

    # -----------------------------------------------------------------------
    # Round 34, Task 2 (Gamma): Adaptive position-sizing score.
    # Must be called after composite_gate_score and expected_value_per_trade.
    # -----------------------------------------------------------------------
    _asz: dict[str, Any] = compute_adaptive_sizing_score(_surface_result)
    _surface_result["adaptive_sizing_score"] = _asz.get("adaptive_sizing_score")
    _surface_result["sizing_multiplier"] = _asz.get("sizing_multiplier")
    _surface_result["sizing_grade"] = _asz.get("sizing_grade")
    _surface_result["full_size_recommended"] = _asz.get("full_size_recommended")

    # -----------------------------------------------------------------------
    # Round 35, Task 1 (Alpha): Sharpe / Sortino risk-adjusted return metrics.
    # Must be called after next_day_rows is assembled (uses next_close_return).
    # -----------------------------------------------------------------------
    _ssa: dict[str, Any] = compute_sharpe_sortino_analysis(next_day_rows)
    _surface_result["sortino_ratio"] = _ssa.get("sortino_ratio")
    _surface_result["sharpe_ratio_r35"] = _ssa.get("sharpe_ratio")
    _surface_result["calmar_proxy"] = _ssa.get("calmar_proxy")
    _surface_result["risk_adjusted_grade"] = _ssa.get("risk_adjusted_grade")
    _surface_result["sortino_positive"] = _ssa.get("sortino_positive")
    # win_rate alias — convenience key equal to next_close_positive_rate.
    _surface_result["win_rate"] = _surface_result.get("next_close_positive_rate")

    # -----------------------------------------------------------------------
    # Round 35, Task 3 (Beta): Candidate pool sector/industry diversity score.
    # -----------------------------------------------------------------------
    _cds: dict[str, Any] = compute_candidate_diversity_score(rows)
    _surface_result["diversity_score"] = _cds.get("diversity_score")
    _surface_result["sector_hhi"] = _cds.get("sector_hhi")
    _surface_result["diversity_grade"] = _cds.get("diversity_grade")
    _surface_result["sector_count"] = _cds.get("sector_count")
    _surface_result["dominant_sector_share"] = _cds.get("dominant_sector_share")
    _surface_result["concentration_risk"] = _cds.get("concentration_risk")

    # -----------------------------------------------------------------------
    # Round 36, Task 1 (Alpha): Return percentile breakdown — right-tail dominance.
    # -----------------------------------------------------------------------
    _rpb: dict[str, Any] = compute_return_percentile_breakdown(next_day_rows)
    _surface_result["right_tail_dominance"] = _rpb.get("right_tail_dominance")
    _surface_result["return_p5"] = _rpb.get("p5")
    _surface_result["return_p10"] = _rpb.get("p10")
    _surface_result["return_p25"] = _rpb.get("p25")
    _surface_result["return_p50"] = _rpb.get("p50")
    _surface_result["return_p75"] = _rpb.get("p75")
    _surface_result["return_p90"] = _rpb.get("p90")
    _surface_result["return_p95"] = _rpb.get("p95")
    _surface_result["return_iqr"] = _rpb.get("iqr")
    _surface_result["return_iqr_ratio"] = _rpb.get("iqr_ratio")
    _surface_result["upper_fence"] = _rpb.get("upper_fence")
    _surface_result["lower_fence"] = _rpb.get("lower_fence")
    _surface_result["right_outlier_rate"] = _rpb.get("right_outlier_rate")
    _surface_result["left_outlier_rate"] = _rpb.get("left_outlier_rate")
    _surface_result["tail_asymmetry_index"] = _rpb.get("tail_asymmetry_index")

    # -----------------------------------------------------------------------
    # Round 36, Task 2 (Beta): Composite score IC — Spearman rank correlation.
    # -----------------------------------------------------------------------
    _csic: dict[str, Any] = compute_composite_score_ic(next_day_rows)
    _surface_result["composite_ic"] = _csic.get("composite_ic")
    _surface_result["composite_ic_positive"] = _csic.get("composite_ic_positive")
    _surface_result["composite_ic_magnitude"] = _csic.get("composite_ic_magnitude")
    _surface_result["ic_t_stat"] = _csic.get("ic_t_stat")
    _surface_result["ic_significant"] = _csic.get("ic_significant")

    # -----------------------------------------------------------------------
    # Round 36, Task 3 (Gamma): Win-rate Bootstrap confidence interval.
    # -----------------------------------------------------------------------
    _wrci: dict[str, Any] = compute_win_rate_confidence_interval(next_day_rows)
    _surface_result["observed_win_rate"] = _wrci.get("observed_win_rate")
    _surface_result["win_rate_ci_lower"] = _wrci.get("ci_lower")
    _surface_result["win_rate_ci_upper"] = _wrci.get("ci_upper")
    _surface_result["win_rate_ci_width"] = _wrci.get("ci_width")
    _surface_result["win_rate_reliable"] = _wrci.get("win_rate_reliable")
    _surface_result["win_rate_ci_grade"] = _wrci.get("win_rate_ci_grade")

    # -----------------------------------------------------------------------
    # Round 37, Task 1 (Alpha): Optimal holding period analysis — T+1/T+2/T+3.
    # -----------------------------------------------------------------------
    _hpa: dict[str, Any] = compute_holding_period_analysis(next_day_rows)
    _surface_result["optimal_holding_days"] = _hpa.get("optimal_holding_days")
    _surface_result["holding_analysis_valid"] = _hpa.get("holding_analysis_valid")
    _surface_result["avg_return_t1"] = _hpa.get("avg_return_t1")
    _surface_result["avg_return_t2"] = _hpa.get("avg_return_t2")
    _surface_result["avg_return_t3"] = _hpa.get("avg_return_t3")
    _surface_result["ev_t1"] = _hpa.get("ev_t1")
    _surface_result["ev_t2"] = _hpa.get("ev_t2")
    _surface_result["ev_t3"] = _hpa.get("ev_t3")
    _surface_result["holding_period_monotone"] = _hpa.get("holding_period_monotone")
    _surface_result["t1_vs_t2_advantage"] = _hpa.get("t1_vs_t2_advantage")
    _surface_result["multi_day_cumulative_return"] = _hpa.get("multi_day_cumulative_return")

    # -----------------------------------------------------------------------
    # Round 37, Task 2 (Beta): Loss trade factor signature — loss-warning signal.
    # -----------------------------------------------------------------------
    _lts: dict[str, Any] = compute_loss_trade_signature(next_day_rows)
    _surface_result["loss_warning_factors"] = _lts.get("loss_warning_factors")
    _surface_result["loss_warning_factor_count"] = _lts.get("loss_warning_factor_count")
    _surface_result["loss_signature_strength"] = _lts.get("loss_signature_strength")
    _surface_result["loss_avoidable"] = _lts.get("loss_avoidable")

    # -----------------------------------------------------------------------
    # Round 37, Task 3 (Gamma): Score Gini coefficient — distribution quality.
    # -----------------------------------------------------------------------
    _sgc: dict[str, Any] = compute_score_gini_coefficient(next_day_rows)
    _surface_result["score_gini"] = _sgc.get("score_gini")
    _surface_result["top20_share"] = _sgc.get("top20_share")
    _surface_result["elite_candidate_rate"] = _sgc.get("elite_candidate_rate")
    _surface_result["score_distribution_quality"] = _sgc.get("score_distribution_quality")
    _surface_result["score_well_differentiated"] = _sgc.get("score_well_differentiated")

    # -----------------------------------------------------------------------
    # Round 38, Task 1 (Alpha): Market environment sensitivity — bull vs bear.
    # -----------------------------------------------------------------------
    _mes: dict[str, Any] = compute_market_environment_sensitivity(next_day_rows)
    _surface_result["bull_env_win_rate"] = _mes.get("bull_env_win_rate")
    _surface_result["bear_env_win_rate"] = _mes.get("bear_env_win_rate")
    _surface_result["bull_env_avg_return"] = _mes.get("bull_env_avg_return")
    _surface_result["bear_env_avg_return"] = _mes.get("bear_env_avg_return")
    _surface_result["market_sensitivity_ratio"] = _mes.get("market_sensitivity_ratio")
    _surface_result["env_win_rate_gap"] = _mes.get("env_win_rate_gap")
    _surface_result["environment_adaptive"] = _mes.get("environment_adaptive")
    _surface_result["market_neutral"] = _mes.get("market_neutral")

    # -----------------------------------------------------------------------
    # Round 38, Task 2 (Beta): Factor importance ranking — per-factor Spearman IC.
    # -----------------------------------------------------------------------
    _fir: dict[str, Any] = compute_factor_importance_ranking(next_day_rows)
    _surface_result["factor_ic_ranking"] = _fir.get("factor_ic_ranking")
    _surface_result["top_factor"] = _fir.get("top_factor")
    _surface_result["bottom_factor"] = _fir.get("bottom_factor")
    _surface_result["positive_ic_factor_count"] = _fir.get("positive_ic_factor_count")
    _surface_result["top3_avg_ic"] = _fir.get("top3_avg_ic")
    _surface_result["factor_ic_spread"] = _fir.get("factor_ic_spread")

    # -----------------------------------------------------------------------
    # Round 38, Task 3 (Gamma): Score bucket win rates — quintile monotonicity.
    # -----------------------------------------------------------------------
    _sbw: dict[str, Any] = compute_score_bucket_win_rates(next_day_rows)
    _surface_result["win_rate_q1"] = _sbw.get("win_rate_q1")
    _surface_result["win_rate_q2"] = _sbw.get("win_rate_q2")
    _surface_result["win_rate_q3"] = _sbw.get("win_rate_q3")
    _surface_result["win_rate_q4"] = _sbw.get("win_rate_q4")
    _surface_result["win_rate_q5"] = _sbw.get("win_rate_q5")
    _surface_result["score_monotone"] = _sbw.get("score_monotone")
    _surface_result["score_near_monotone"] = _sbw.get("score_near_monotone")
    _surface_result["top_quintile_premium"] = _sbw.get("top_quintile_premium")
    _surface_result["score_rank_ic"] = _sbw.get("score_rank_ic")
    _surface_result["score_discriminates_well"] = _sbw.get("score_discriminates_well")

    # -----------------------------------------------------------------------
    # Round 39, Task 1 (Alpha): Recency vs history — overfitting warning.
    # -----------------------------------------------------------------------
    _rha: dict[str, Any] = compute_recency_vs_history_analysis(next_day_rows)
    _surface_result["historical_win_rate"] = _rha.get("historical_win_rate")
    _surface_result["recent_win_rate"] = _rha.get("recent_win_rate")
    _surface_result["recency_win_rate_gap"] = _rha.get("recency_win_rate_gap")
    _surface_result["recency_return_gap"] = _rha.get("recency_return_gap")
    _surface_result["recency_degraded"] = _rha.get("recency_degraded")
    _surface_result["recency_improved"] = _rha.get("recency_improved")
    _surface_result["recency_stable"] = _rha.get("recency_stable")

    # -----------------------------------------------------------------------
    # Round 39, Task 2 (Beta): Optimal score threshold — entry filter search.
    # -----------------------------------------------------------------------
    _ost: dict[str, Any] = compute_optimal_score_threshold(next_day_rows)
    _surface_result["optimal_threshold_pct"] = _ost.get("optimal_threshold_pct")
    _surface_result["optimal_score_threshold"] = _ost.get("optimal_score_threshold")
    _surface_result["optimal_above_win_rate"] = _ost.get("optimal_above_win_rate")
    _surface_result["optimal_threshold_lift"] = _ost.get("optimal_threshold_lift")
    _surface_result["above_threshold_count"] = _ost.get("above_threshold_count")
    _surface_result["threshold_coverage"] = _ost.get("threshold_coverage")

    # -----------------------------------------------------------------------
    # Round 39, Task 3 (Gamma): Simulated equity curve — drawdown / recovery.
    # -----------------------------------------------------------------------
    _sec: dict[str, Any] = compute_simulated_equity_curve(next_day_rows)
    _surface_result["total_return_simulated"] = _sec.get("total_return")
    _surface_result["max_drawdown_simulated"] = _sec.get("max_drawdown")
    _surface_result["max_consecutive_losses"] = _sec.get("max_consecutive_losses")
    _surface_result["recovery_factor"] = _sec.get("recovery_factor")
    _surface_result["equity_curve_slope"] = _sec.get("equity_curve_slope")
    _surface_result["equity_rising"] = _sec.get("equity_rising")
    _surface_result["equity_curve_grade"] = _sec.get("equity_curve_grade")

    # -----------------------------------------------------------------------
    # Round 40, Task 1 (Alpha): Factor synergy matrix — pairwise co-activation lift.
    # -----------------------------------------------------------------------
    _fsm: dict[str, Any] = compute_factor_synergy_matrix(next_day_rows)
    _surface_result["best_factor_pair"] = _fsm.get("best_factor_pair")
    _surface_result["best_pair_lift"] = _fsm.get("best_pair_lift")
    _surface_result["best_pair_win_rate"] = _fsm.get("best_pair_win_rate")
    _surface_result["synergy_pair_count"] = _fsm.get("synergy_pair_count")
    _surface_result["max_synergy_lift"] = _fsm.get("max_synergy_lift")
    _surface_result["synergy_matrix_valid"] = _fsm.get("synergy_matrix_valid")

    # -----------------------------------------------------------------------
    # Round 40, Task 2 (Beta): Float turnover analysis —换手率 bucket win rates.
    # -----------------------------------------------------------------------
    _fta: dict[str, Any] = compute_float_turnover_analysis(next_day_rows)
    _surface_result["turnover_analysis_valid"] = _fta.get("turnover_analysis_valid")
    _surface_result["turnover_low_win_rate"] = _fta.get("turnover_low_win_rate")
    _surface_result["turnover_mid_win_rate"] = _fta.get("turnover_mid_win_rate")
    _surface_result["turnover_high_win_rate"] = _fta.get("turnover_high_win_rate")
    _surface_result["optimal_turnover_bucket"] = _fta.get("optimal_turnover_bucket")
    _surface_result["turnover_monotone_win_rate"] = _fta.get("turnover_monotone_win_rate")
    _surface_result["high_vs_low_lift"] = _fta.get("high_vs_low_lift")
    _surface_result["p33_turnover"] = _fta.get("p33_turnover")
    _surface_result["p67_turnover"] = _fta.get("p67_turnover")

    # -----------------------------------------------------------------------
    # Round 41, Task 2 (Beta): Volume-price alignment — 量价方向对齐率.
    # -----------------------------------------------------------------------
    _vpa: dict[str, Any] = compute_volume_price_alignment(next_day_rows)
    _surface_result["vol_price_signal_valid"] = _vpa.get("vol_price_signal_valid")
    _surface_result["vol_price_alignment_rate"] = _vpa.get("vol_price_alignment_rate")
    _surface_result["vol_price_alignment_strong"] = _vpa.get("vol_price_alignment_strong")
    _surface_result["aligned_win_rate"] = _vpa.get("aligned_win_rate")
    _surface_result["misaligned_win_rate"] = _vpa.get("misaligned_win_rate")
    _surface_result["inflow_win_rate"] = _vpa.get("inflow_win_rate")
    _surface_result["outflow_win_rate"] = _vpa.get("outflow_win_rate")
    _surface_result["inflow_vs_outflow_lift"] = _vpa.get("inflow_vs_outflow_lift")

    # -----------------------------------------------------------------------
    # Round 41, Task 3 (Gamma): Statistical significance tests — 综合统计显著性.
    # -----------------------------------------------------------------------
    _sst: dict[str, Any] = compute_statistical_significance_tests(next_day_rows)
    _surface_result["win_rate_p_value"] = _sst.get("win_rate_p_value")
    _surface_result["z_win_rate"] = _sst.get("z_win_rate")
    _surface_result["t_stat_return"] = _sst.get("t_stat_return")
    _surface_result["win_rate_significant_90"] = _sst.get("win_rate_significant_90")
    _surface_result["win_rate_significant_95"] = _sst.get("win_rate_significant_95")
    _surface_result["return_significant_90"] = _sst.get("return_significant_90")
    _surface_result["return_significant_95"] = _sst.get("return_significant_95")
    _surface_result["combined_significance_score"] = _sst.get("combined_significance_score")
    _surface_result["strategy_statistically_valid"] = _sst.get("strategy_statistically_valid")

    # -----------------------------------------------------------------------
    # Round 42, Task 1 (Alpha): Score calibration curve — 评分校准曲线.
    # -----------------------------------------------------------------------
    _scc: dict[str, Any] = compute_score_calibration_curve(next_day_rows)
    _surface_result["calibration_slope"] = _scc.get("calibration_slope")
    _surface_result["calibration_mse"] = _scc.get("calibration_mse")
    _surface_result["calibration_monotone"] = _scc.get("calibration_monotone")
    _surface_result["well_calibrated"] = _scc.get("well_calibrated")
    _surface_result["calibration_bin_count"] = _scc.get("calibration_bin_count")
    _surface_result["calibration_valid"] = _scc.get("calibration_valid")

    # -----------------------------------------------------------------------
    # Round 42, Task 2 (Beta): Close-strength quartile stratification — 收盘强度分层.
    # -----------------------------------------------------------------------
    _css: dict[str, Any] = compute_close_strength_stratification(next_day_rows)
    _surface_result["close_strength_valid"] = _css.get("close_strength_valid")
    _surface_result["cs_win_rate_q1"] = _css.get("cs_win_rate_q1")
    _surface_result["cs_win_rate_q2"] = _css.get("cs_win_rate_q2")
    _surface_result["cs_win_rate_q3"] = _css.get("cs_win_rate_q3")
    _surface_result["cs_win_rate_q4"] = _css.get("cs_win_rate_q4")
    _surface_result["cs_monotone"] = _css.get("cs_monotone")
    _surface_result["cs_top_quartile_premium"] = _css.get("cs_top_quartile_premium")
    _surface_result["cs_top_quartile_avg_return"] = _css.get("cs_top_quartile_avg_return")
    _surface_result["cs_bottom_quartile_avg_return"] = _css.get("cs_bottom_quartile_avg_return")
    _surface_result["cs_return_spread"] = _css.get("cs_return_spread")
    _surface_result["cs_effective"] = _css.get("cs_effective")

    # -----------------------------------------------------------------------
    # Round 43, Task 1 (Alpha): Profit Factor Analysis — 盈利因子PF.
    # -----------------------------------------------------------------------
    _pfa: dict[str, Any] = compute_profit_factor_analysis(next_day_rows)
    _surface_result["profit_factor"] = _pfa.get("profit_factor")
    _surface_result["gross_profit"] = _pfa.get("gross_profit")
    _surface_result["gross_loss"] = _pfa.get("gross_loss")
    _surface_result["avg_win"] = _pfa.get("avg_win")
    _surface_result["avg_loss"] = _pfa.get("avg_loss")
    _surface_result["win_loss_ratio"] = _pfa.get("win_loss_ratio")
    _surface_result["profit_factor_grade"] = _pfa.get("profit_factor_grade")
    _surface_result["profitable"] = _pfa.get("profitable")
    _surface_result["profit_factor_vs_kelly_consistent"] = _pfa.get("profit_factor_vs_kelly_consistent")
    _surface_result["profit_factor_valid"] = _pfa.get("profit_factor_valid")

    # -----------------------------------------------------------------------
    # Round 43, Task 2 (Beta): News Sentiment Stratification — 情绪评分分层.
    # -----------------------------------------------------------------------
    _nss: dict[str, Any] = compute_news_sentiment_stratification(next_day_rows)
    _surface_result["sentiment_analysis_valid"] = _nss.get("sentiment_analysis_valid")
    _surface_result["sentiment_low_win_rate"] = _nss.get("sentiment_low_win_rate")
    _surface_result["sentiment_mid_win_rate"] = _nss.get("sentiment_mid_win_rate")
    _surface_result["sentiment_high_win_rate"] = _nss.get("sentiment_high_win_rate")
    _surface_result["sentiment_monotone"] = _nss.get("sentiment_monotone")
    _surface_result["high_vs_low_sentiment_lift"] = _nss.get("high_vs_low_sentiment_lift")
    _surface_result["optimal_sentiment_bucket"] = _nss.get("optimal_sentiment_bucket")
    _surface_result["sentiment_effective"] = _nss.get("sentiment_effective")

    # Round 44, Task 1 (Alpha): Relative-Strength Quartile Stratification.
    # -----------------------------------------------------------------------
    _rss: dict[str, Any] = compute_relative_strength_stratification(next_day_rows)
    _surface_result["rs_stratification_valid"] = _rss.get("rs_stratification_valid")
    _surface_result["rs_q1_win_rate"] = _rss.get("rs_q1_win_rate")
    _surface_result["rs_q2_win_rate"] = _rss.get("rs_q2_win_rate")
    _surface_result["rs_q3_win_rate"] = _rss.get("rs_q3_win_rate")
    _surface_result["rs_q4_win_rate"] = _rss.get("rs_q4_win_rate")
    _surface_result["rs_top_quartile_win_rate"] = _rss.get("rs_top_quartile_win_rate")
    _surface_result["rs_bottom_quartile_win_rate"] = _rss.get("rs_bottom_quartile_win_rate")
    _surface_result["rs_top_quartile_premium"] = _rss.get("rs_top_quartile_premium")
    _surface_result["rs_monotone"] = _rss.get("rs_monotone")

    # Round 44, Task 2 (Beta): Breakout-Quality Tercile Stratification.
    # -----------------------------------------------------------------------
    _bqs: dict[str, Any] = compute_breakout_quality_stratification(next_day_rows)
    _surface_result["bq_stratification_valid"] = _bqs.get("bq_stratification_valid")
    _surface_result["bq_low_win_rate"] = _bqs.get("bq_low_win_rate")
    _surface_result["bq_mid_win_rate"] = _bqs.get("bq_mid_win_rate")
    _surface_result["bq_high_win_rate"] = _bqs.get("bq_high_win_rate")
    _surface_result["bq_high_vs_low_lift"] = _bqs.get("bq_high_vs_low_lift")
    _surface_result["bq_monotone"] = _bqs.get("bq_monotone")
    _surface_result["bq_effective"] = _bqs.get("bq_effective")

    # Round 45, Task 1 (Alpha): Market-Cap Tercile Stratification.
    # -----------------------------------------------------------------------
    _mcs: dict[str, Any] = compute_market_cap_stratification(next_day_rows)
    _surface_result["mc_stratification_valid"] = _mcs.get("mc_stratification_valid")
    _surface_result["mc_low_win_rate"] = _mcs.get("mc_low_win_rate")
    _surface_result["mc_mid_win_rate"] = _mcs.get("mc_mid_win_rate")
    _surface_result["mc_high_win_rate"] = _mcs.get("mc_high_win_rate")
    _surface_result["mc_high_vs_low_lift"] = _mcs.get("mc_high_vs_low_lift")
    _surface_result["mc_monotone"] = _mcs.get("mc_monotone")
    _surface_result["mc_effective"] = _mcs.get("mc_effective")

    # Round 45, Task 2 (Beta): Catalyst-Theme-Score Quartile Stratification.
    # -----------------------------------------------------------------------
    _cats: dict[str, Any] = compute_catalyst_score_stratification(next_day_rows)
    _surface_result["catalyst_stratification_valid"] = _cats.get("catalyst_stratification_valid")
    _surface_result["catalyst_q1_win_rate"] = _cats.get("catalyst_q1_win_rate")
    _surface_result["catalyst_q2_win_rate"] = _cats.get("catalyst_q2_win_rate")
    _surface_result["catalyst_q3_win_rate"] = _cats.get("catalyst_q3_win_rate")
    _surface_result["catalyst_q4_win_rate"] = _cats.get("catalyst_q4_win_rate")
    _surface_result["catalyst_top_quartile_premium"] = _cats.get("catalyst_top_quartile_premium")
    _surface_result["catalyst_monotone"] = _cats.get("catalyst_monotone")

    # Round 46, Task 1 (Alpha): Volume-Price Divergence Stratification.
    # ------------------------------------------------------------------
    _vpds: dict[str, Any] = compute_volume_price_divergence_stratification(next_day_rows)
    _surface_result["vpd_stratification_valid"] = _vpds.get("vpd_stratification_valid")
    _surface_result["vpd_low_win_rate"] = _vpds.get("vpd_low_win_rate")
    _surface_result["vpd_mid_win_rate"] = _vpds.get("vpd_mid_win_rate")
    _surface_result["vpd_high_win_rate"] = _vpds.get("vpd_high_win_rate")
    _surface_result["vpd_low_vs_high_lift"] = _vpds.get("vpd_low_vs_high_lift")
    _surface_result["vpd_anti_monotone"] = _vpds.get("vpd_anti_monotone")
    _surface_result["vpd_effective"] = _vpds.get("vpd_effective")

    # Round 46, Task 2 (Beta): Score Distribution Moments.
    # -----------------------------------------------------
    _sdm: dict[str, Any] = compute_score_distribution_moments(next_day_rows)
    _surface_result["score_mean"] = _sdm.get("score_mean")
    _surface_result["score_std"] = _sdm.get("score_std")
    _surface_result["score_skewness"] = _sdm.get("score_skewness")
    _surface_result["score_kurtosis"] = _sdm.get("score_kurtosis")
    _surface_result["score_positive_pct"] = _sdm.get("score_positive_pct")
    _surface_result["score_p10"] = _sdm.get("score_p10")
    _surface_result["score_p25"] = _sdm.get("score_p25")
    _surface_result["score_p50"] = _sdm.get("score_p50")
    _surface_result["score_p75"] = _sdm.get("score_p75")
    _surface_result["score_p90"] = _sdm.get("score_p90")
    _surface_result["score_iqr"] = _sdm.get("score_iqr")

    # Round 47, Task 1 (Alpha): Momentum Slope Stratification.
    # ---------------------------------------------------------
    _mss: dict[str, Any] = compute_momentum_slope_stratification(next_day_rows)
    _surface_result["ms_stratification_valid"] = _mss.get("ms_stratification_valid")
    _surface_result["ms_low_win_rate"] = _mss.get("ms_low_win_rate")
    _surface_result["ms_mid_win_rate"] = _mss.get("ms_mid_win_rate")
    _surface_result["ms_high_win_rate"] = _mss.get("ms_high_win_rate")
    _surface_result["ms_high_vs_low_lift"] = _mss.get("ms_high_vs_low_lift")
    _surface_result["ms_monotone"] = _mss.get("ms_monotone")
    _surface_result["ms_effective"] = _mss.get("ms_effective")

    # Round 47, Task 2 (Beta): Inflow Ratio Stratification.
    # ------------------------------------------------------
    _irs: dict[str, Any] = compute_inflow_ratio_stratification(next_day_rows)
    _surface_result["inflow_stratification_valid"] = _irs.get("inflow_stratification_valid")
    _surface_result["inflow_low_win_rate"] = _irs.get("inflow_low_win_rate")
    _surface_result["inflow_mid_win_rate"] = _irs.get("inflow_mid_win_rate")
    _surface_result["inflow_high_win_rate"] = _irs.get("inflow_high_win_rate")
    _surface_result["inflow_high_vs_low_lift"] = _irs.get("inflow_high_vs_low_lift")
    _surface_result["inflow_monotone"] = _irs.get("inflow_monotone")
    _surface_result["inflow_effective"] = _irs.get("inflow_effective")

    # Round 48, Task 1 (Alpha): VEQ Stratification.
    # ------------------------------------------------
    _veqs: dict[str, Any] = compute_veq_stratification(next_day_rows)
    _surface_result["veq_stratification_valid"] = _veqs.get("veq_stratification_valid")
    _surface_result["veq_low_win_rate"] = _veqs.get("veq_low_win_rate")
    _surface_result["veq_mid_win_rate"] = _veqs.get("veq_mid_win_rate")
    _surface_result["veq_high_win_rate"] = _veqs.get("veq_high_win_rate")
    _surface_result["veq_high_vs_low_lift"] = _veqs.get("veq_high_vs_low_lift")
    _surface_result["veq_monotone"] = _veqs.get("veq_monotone")
    _surface_result["veq_effective"] = _veqs.get("veq_effective")

    # Round 48, Task 2 (Beta): Sector Resonance Stratification.
    # -----------------------------------------------------------
    _srs: dict[str, Any] = compute_sector_resonance_stratification(next_day_rows)
    _surface_result["sr_stratification_valid"] = _srs.get("sr_stratification_valid")
    _surface_result["sr_low_win_rate"] = _srs.get("sr_low_win_rate")
    _surface_result["sr_mid_win_rate"] = _srs.get("sr_mid_win_rate")
    _surface_result["sr_high_win_rate"] = _srs.get("sr_high_win_rate")
    _surface_result["sr_high_vs_low_lift"] = _srs.get("sr_high_vs_low_lift")
    _surface_result["sr_monotone"] = _srs.get("sr_monotone")
    _surface_result["sr_effective"] = _srs.get("sr_effective")

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


# ---------------------------------------------------------------------------
# Round 30, Task 1 (Gamma): 参数稳定性追踪 — cross-window parameter drift analysis.
# Tracks drift of key surface metrics across walk-forward windows to identify
# over-fitted profiles whose metrics fluctuate wildly between windows.
# ---------------------------------------------------------------------------

_PARAM_STABILITY_DEFAULT_KEYS: tuple[str, ...] = (
    "next_close_positive_rate",
    "next_close_expectancy",
    "candidate_pool_avg_composite_score",
    "realized_payoff_ratio",
    "regime_consistency_score",
)


def compute_parameter_stability_metrics(
    window_summaries: list[dict],
    param_keys: list[str] | None = None,
) -> dict:
    """跨walk-forward窗口追踪关键指标的漂移程度，识别高度不稳定参数（过拟合信号）。

    For each tracked key, extracts its non-None scalar values across windows and
    computes ``std / (max − min + 1e-8)`` as the relative drift score.
    The overall ``param_drift_score`` is the median across all tracked keys.

    Args:
        window_summaries: Ordered list of per-window surface summary dicts.
        param_keys: Keys to track.  Defaults to :data:`_PARAM_STABILITY_DEFAULT_KEYS`.

    Returns:
        Dict with keys:

        - ``param_drift_score``: float | None — median relative drift; None when < 3 windows.
        - ``most_stable_param``: str | None — key with lowest relative drift.
        - ``most_unstable_param``: str | None — key with highest relative drift.
        - ``unstable_param_count``: int — number of keys with relative drift > 0.40.
        - ``parameter_stability_grade``: str | None — A(<0.15)/B(<0.30)/C(<0.50)/D(≥0.50).
        - ``param_drift_by_key``: dict[str, float] — per-key relative drift scores.
    """
    _null: dict = {
        "param_drift_score": None,
        "most_stable_param": None,
        "most_unstable_param": None,
        "unstable_param_count": 0,
        "parameter_stability_grade": None,
        "param_drift_by_key": {},
    }
    keys: list[str] = list(param_keys) if param_keys is not None else list(_PARAM_STABILITY_DEFAULT_KEYS)
    if len(window_summaries) < 3:
        return _null

    drift_by_key: dict[str, float] = {}
    for key in keys:
        vals: list[float] = []
        for s in window_summaries:
            raw = s.get(key)
            if raw is None:
                continue
            try:
                vals.append(float(raw))
            except (TypeError, ValueError):
                continue
        if len(vals) < 3:
            continue
        n = len(vals)
        mean_v = sum(vals) / n
        std_v = (sum((v - mean_v) ** 2 for v in vals) / n) ** 0.5
        range_v = max(vals) - min(vals)
        drift_by_key[key] = round(std_v / (range_v + 1e-8), 4)

    if not drift_by_key:
        return _null

    sorted_drifts = sorted(drift_by_key.values())
    n_d = len(sorted_drifts)
    if n_d % 2 == 1:
        median_drift = sorted_drifts[n_d // 2]
    else:
        median_drift = (sorted_drifts[n_d // 2 - 1] + sorted_drifts[n_d // 2]) / 2.0
    median_drift = round(median_drift, 4)

    most_stable = min(drift_by_key, key=lambda k: drift_by_key[k])
    most_unstable = max(drift_by_key, key=lambda k: drift_by_key[k])
    unstable_count = sum(1 for v in drift_by_key.values() if v > 0.40)

    if median_drift < 0.15:
        grade = "A"
    elif median_drift < 0.30:
        grade = "B"
    elif median_drift < 0.50:
        grade = "C"
    else:
        grade = "D"

    return {
        "param_drift_score": median_drift,
        "most_stable_param": most_stable,
        "most_unstable_param": most_unstable,
        "unstable_param_count": unstable_count,
        "parameter_stability_grade": grade,
        "param_drift_by_key": drift_by_key,
    }


# ---------------------------------------------------------------------------
# Task 1 (Round 31, Alpha): Factor return time-series autocorrelation analysis
# ---------------------------------------------------------------------------
# Detects regime persistence (momentum continuation) or mean-reversion tendencies
# in the BTST return series by computing Pearson lag-1 and lag-2 autocorrelations
# and win/loss streak statistics.


def compute_factor_return_autocorr(rows: list[dict]) -> dict:
    """Compute Pearson lag-1/lag-2 autocorrelation and run-length statistics on next_close_return.

    Args:
        rows: BTST candidate rows containing ``date`` and ``next_close_return`` fields.
              Rows missing either field are skipped.

    Returns:
        Dict with keys:

        - ``autocorr_lag1``: float | None — Pearson correlation between r[t] and r[t+1].
        - ``autocorr_lag2``: float | None — Pearson correlation between r[t] and r[t+2].
        - ``longest_win_streak``: int | None — max consecutive days with positive return.
        - ``longest_loss_streak``: int | None — max consecutive days with negative return.
        - ``mean_win_streak``: float | None — average length of win runs.
        - ``mean_loss_streak``: float | None — average length of loss runs.
        - ``autocorr_significant``: bool | None — abs(autocorr_lag1) > 0.15.
        - ``momentum_persistence``: bool | None — autocorr_lag1 > 0.10 (trend continuation).
        - ``mean_reversion_tendency``: bool | None — autocorr_lag1 < -0.10 (reversal tendency).

        Returns all-None dict when fewer than 10 valid rows are available.
    """
    _null: dict = {
        "autocorr_lag1": None,
        "autocorr_lag2": None,
        "longest_win_streak": None,
        "longest_loss_streak": None,
        "mean_win_streak": None,
        "mean_loss_streak": None,
        "autocorr_significant": None,
        "momentum_persistence": None,
        "mean_reversion_tendency": None,
    }
    # Extract (date, return) pairs; sort by date then drop date for numeric series.
    pairs: list[tuple[str, float]] = []
    for row in rows:
        d = row.get("date")
        r = row.get("next_close_return")
        if d is None or r is None:
            continue
        try:
            pairs.append((str(d), float(r)))
        except (TypeError, ValueError):
            continue
    pairs.sort(key=lambda x: x[0])
    ret: list[float] = [p[1] for p in pairs]
    n = len(ret)
    if n < 10:
        return _null

    def _pearson(xs: list[float], ys: list[float]) -> float | None:
        """Pearson correlation between xs and ys (must be same length, >= 5)."""
        m = len(xs)
        if m < 5 or m != len(ys):
            return None
        mx = sum(xs) / m
        my = sum(ys) / m
        num = sum((xs[i] - mx) * (ys[i] - my) for i in range(m))
        dx = sum((v - mx) ** 2 for v in xs) ** 0.5
        dy = sum((v - my) ** 2 for v in ys) ** 0.5
        if dx == 0.0 or dy == 0.0:
            return None
        return round(num / (dx * dy), 4)

    lag1 = _pearson(ret[:-1], ret[1:])
    lag2 = _pearson(ret[:-2], ret[2:]) if n >= 12 else None

    # Compute win/loss runs
    win_streaks: list[int] = []
    loss_streaks: list[int] = []
    cur_w = 0
    cur_l = 0
    for r in ret:
        if r > 0:
            cur_w += 1
            if cur_l > 0:
                loss_streaks.append(cur_l)
                cur_l = 0
        elif r < 0:
            cur_l += 1
            if cur_w > 0:
                win_streaks.append(cur_w)
                cur_w = 0
        else:
            if cur_w > 0:
                win_streaks.append(cur_w)
                cur_w = 0
            if cur_l > 0:
                loss_streaks.append(cur_l)
                cur_l = 0
    if cur_w > 0:
        win_streaks.append(cur_w)
    if cur_l > 0:
        loss_streaks.append(cur_l)

    longest_win = max(win_streaks) if win_streaks else 0
    longest_loss = max(loss_streaks) if loss_streaks else 0
    mean_win = round(sum(win_streaks) / len(win_streaks), 4) if win_streaks else None
    mean_loss = round(sum(loss_streaks) / len(loss_streaks), 4) if loss_streaks else None

    autocorr_significant: bool | None = (abs(lag1) > 0.15) if lag1 is not None else None
    momentum_persistence: bool | None = (lag1 > 0.10) if lag1 is not None else None
    mean_reversion_tendency: bool | None = (lag1 < -0.10) if lag1 is not None else None

    return {
        "autocorr_lag1": lag1,
        "autocorr_lag2": lag2,
        "longest_win_streak": longest_win,
        "longest_loss_streak": longest_loss,
        "mean_win_streak": mean_win,
        "mean_loss_streak": mean_loss,
        "autocorr_significant": autocorr_significant,
        "momentum_persistence": momentum_persistence,
        "mean_reversion_tendency": mean_reversion_tendency,
    }


# ---------------------------------------------------------------------------
# Task 2 (Round 31, Gamma): Score stability across walk-forward windows
# ---------------------------------------------------------------------------
# Tracks composite_score mean, std, and trend across replay windows to detect
# whether the scoring system produces consistent evaluations (low CV = stable).


def compute_score_stability_across_windows(window_summaries: list[dict]) -> dict:
    """Measure stability of candidate_pool_avg_composite_score across replay windows.

    Args:
        window_summaries: Ordered list of per-window surface summary dicts, each containing
                          ``candidate_pool_avg_composite_score`` and optionally
                          ``next_close_positive_rate``.

    Returns:
        Dict with keys:

        - ``score_mean_across_windows``: float | None — mean composite score across windows.
        - ``score_std_across_windows``: float | None — standard deviation across windows.
        - ``score_cv_across_windows``: float | None — coefficient of variation (std / mean).
        - ``score_trend_across_windows``: float | None — OLS slope of score vs window index.
        - ``win_rate_score_corr``: float | None — Spearman(avg_score, win_rate) across windows.
        - ``score_system_stable``: bool | None — True when score_cv < 0.15.

        Returns all-None dict when fewer than 3 windows have score data.
    """
    _null: dict = {
        "score_mean_across_windows": None,
        "score_std_across_windows": None,
        "score_cv_across_windows": None,
        "score_trend_across_windows": None,
        "win_rate_score_corr": None,
        "score_system_stable": None,
    }
    scores: list[float] = []
    win_rates: list[float] = []
    for s in window_summaries:
        sc = s.get("candidate_pool_avg_composite_score")
        wr = s.get("next_close_positive_rate")
        if sc is None:
            continue
        try:
            scores.append(float(sc))
            win_rates.append(float(wr) if wr is not None else float("nan"))
        except (TypeError, ValueError):
            continue
    if len(scores) < 3:
        return _null

    n = len(scores)
    score_mean = round(sum(scores) / n, 4)
    score_std = round((sum((v - score_mean) ** 2 for v in scores) / n) ** 0.5, 4)
    score_cv = round(score_std / score_mean, 4) if score_mean != 0.0 else None

    # OLS linear slope: x = window index (0-based)
    xs = list(range(n))
    ys = scores
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    sx2 = sum((x - x_mean) ** 2 for x in xs)
    sxy = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n))
    score_trend = round(sxy / sx2, 6) if sx2 != 0.0 else 0.0

    # Spearman correlation between scores and win rates
    valid_pairs = [(scores[i], win_rates[i]) for i in range(n) if not (win_rates[i] != win_rates[i])]  # filter nan
    if len(valid_pairs) >= 3:
        sc_list = [p[0] for p in valid_pairs]
        wr_list = [p[1] for p in valid_pairs]
        win_rate_score_corr = _spearman_corr(sc_list, wr_list)
    else:
        win_rate_score_corr = None

    score_system_stable: bool | None = (score_cv < 0.15) if score_cv is not None else None

    return {
        "score_mean_across_windows": score_mean,
        "score_std_across_windows": score_std,
        "score_cv_across_windows": score_cv,
        "score_trend_across_windows": score_trend,
        "win_rate_score_corr": win_rate_score_corr,
        "score_system_stable": score_system_stable,
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


# ---------------------------------------------------------------------------
# Round 32, Task 1 (Gamma): Conditional tail-risk analysis
# ---------------------------------------------------------------------------
# Quantifies the probability of deep losses in the HIGH-score group vs the
# LOW-score group.  A scoring function that truly has edge should push tail
# losses away from the high-score bucket (score_tail_separation > 0).


def compute_conditional_tail_risk(rows: list[dict]) -> dict:
    """Compute tail-risk statistics conditioned on composite score percentile groups.

    Splits ``rows`` into a high-score group (score ≥ P75) and a low-score group
    (score < P25) then calculates CVaR / Expected-Shortfall at the 5 % tail for
    each group as well as the deep-loss probability P(return < −3 %).

    Score field priority: ``composite_score`` → ``runner_composite_score``.

    Args:
        rows: BTST candidate rows with at least ``next_close_return`` and a score field.

    Returns:
        Dict with keys:

        - ``high_score_tail_loss_rate``: float | None — P(return < −0.03 | high-score group).
        - ``high_score_cvar_5pct``: float | None — mean of worst-5 % returns in high-score group.
        - ``high_score_upside_5pct``: float | None — mean of best-5 % returns in high-score group.
        - ``tail_risk_asymmetry``: float | None — |cvar_5pct| / max(upside_5pct, 0.001).
        - ``low_score_tail_loss_rate``: float | None — P(return < −0.03 | low-score group).
        - ``low_score_cvar_5pct``: float | None — mean of worst-5 % returns in low-score group.
        - ``score_tail_separation``: float | None — low_rate − high_rate (>0 = score filters risk).
        - ``tail_risk_well_controlled``: bool | None — asymmetry < 1.5 AND separation > 0.
        - ``score_field_used``: str | None — which score field was resolved.
    """
    _null: dict = {
        "high_score_tail_loss_rate": None,
        "high_score_cvar_5pct": None,
        "high_score_upside_5pct": None,
        "tail_risk_asymmetry": None,
        "low_score_tail_loss_rate": None,
        "low_score_cvar_5pct": None,
        "score_tail_separation": None,
        "tail_risk_well_controlled": None,
        "score_field_used": None,
    }

    # Resolve score field.
    score_field: str | None = None
    for _candidate in ("composite_score", "runner_composite_score"):
        if any(row.get(_candidate) is not None for row in rows):
            score_field = _candidate
            break

    # Collect valid (score, return) pairs.
    pairs: list[tuple[float, float]] = []
    for row in rows:
        ret = row.get("next_close_return")
        if ret is None:
            continue
        if score_field is not None:
            sc = row.get(score_field)
            if sc is None:
                continue
            pairs.append((float(sc), float(ret)))

    def _tail_stats(returns: list[float]) -> tuple[float | None, float | None, float | None]:
        """Return (tail_loss_rate, cvar_5pct, upside_5pct) or (None, None, None) if <5 items."""
        if len(returns) < 5:
            return None, None, None
        n = len(returns)
        loss_rate = round(sum(1 for r in returns if r < -0.03) / n, 6)
        sorted_asc = sorted(returns)
        k5 = max(1, int(n * 0.05))
        cvar = round(sum(sorted_asc[:k5]) / k5, 6)
        upside = round(sum(sorted_asc[-k5:]) / k5, 6)
        return loss_rate, cvar, upside

    result = dict(_null)
    result["score_field_used"] = score_field

    if score_field is None or len(pairs) < 10:
        # No score available or too few rows — compute global tail stats only.
        all_rets = [float(row["next_close_return"]) for row in rows if row.get("next_close_return") is not None]
        if len(all_rets) >= 5:
            _lr, _cv, _up = _tail_stats(all_rets)
            result["high_score_tail_loss_rate"] = _lr
            result["high_score_cvar_5pct"] = _cv
            result["high_score_upside_5pct"] = _up
            if _cv is not None and _up is not None:
                _asym = round(abs(_cv) / max(_up, 0.001), 4) if _up is not None else None
                result["tail_risk_asymmetry"] = _asym
        return result

    scores_only = [sc for sc, _ in pairs]
    sorted_scores = sorted(scores_only)
    n_pairs = len(sorted_scores)
    p75_val = sorted_scores[int(n_pairs * 0.75)]
    p25_val = sorted_scores[int(n_pairs * 0.25)]

    # Use >= / <= so that bimodal distributions where p25_val equals min(scores)
    # still produce a non-empty low group.
    high_rets = [ret for sc, ret in pairs if sc >= p75_val]
    low_rets = [ret for sc, ret in pairs if sc <= p25_val]

    h_lr, h_cv, h_up = _tail_stats(high_rets)
    l_lr, l_cv, _l_up = _tail_stats(low_rets)

    result["high_score_tail_loss_rate"] = h_lr
    result["high_score_cvar_5pct"] = h_cv
    result["high_score_upside_5pct"] = h_up
    result["low_score_tail_loss_rate"] = l_lr
    result["low_score_cvar_5pct"] = l_cv

    if h_cv is not None and h_up is not None:
        result["tail_risk_asymmetry"] = round(abs(h_cv) / max(h_up, 0.001), 4)

    if h_lr is not None and l_lr is not None:
        sep = round(l_lr - h_lr, 6)
        result["score_tail_separation"] = sep
        asym = result.get("tail_risk_asymmetry")
        if asym is not None:
            result["tail_risk_well_controlled"] = bool(asym < 1.5 and sep > 0.0)
        else:
            result["tail_risk_well_controlled"] = None

    return result


# ---------------------------------------------------------------------------
# Round 32, Task 2 (Alpha): Volume anomaly detection
# ---------------------------------------------------------------------------
# Detects whether extreme volume expansion (放量) or strong net inflow
# correlates with higher win rates — a key signal for distinguishing
# institutional accumulation from distribution.


def compute_volume_anomaly_metrics(rows: list[dict]) -> dict:
    """Compute win-rate stratification by volume expansion and net inflow terciles.

    Splits ``rows`` into three equal-width buckets based on P33/P67 of
    ``volume_expansion_quality`` (VEQ) and ``t0_estimated_net_inflow_ratio`` (ENIR),
    then computes win rate and average return per bucket.

    Args:
        rows: BTST candidate rows with ``volume_expansion_quality``,
              ``t0_estimated_net_inflow_ratio``, and ``next_close_return``.

    Returns:
        Dict with keys:

        - ``volume_low_win_rate`` / ``volume_mid_win_rate`` / ``volume_high_win_rate``: float | None.
        - ``volume_monotone_win_rate``: bool | None — True when high ≥ mid ≥ low.
        - ``extreme_volume_win_rate_premium``: float | None — high_win_rate − low_win_rate.
        - ``inflow_low_win_rate`` / ``inflow_high_win_rate``: float | None.
        - ``inflow_win_rate_premium``: float | None — inflow_high − inflow_low win rate.
        - ``volume_inflow_alignment``: bool | None — monotone_vol AND inflow_premium > 0.05.
    """
    _null: dict = {
        "volume_low_win_rate": None,
        "volume_mid_win_rate": None,
        "volume_high_win_rate": None,
        "volume_low_avg_return": None,
        "volume_mid_avg_return": None,
        "volume_high_avg_return": None,
        "volume_monotone_win_rate": None,
        "extreme_volume_win_rate_premium": None,
        "inflow_low_win_rate": None,
        "inflow_mid_win_rate": None,
        "inflow_high_win_rate": None,
        "inflow_win_rate_premium": None,
        "volume_inflow_alignment": None,
    }

    def _bucket_stats(
        pairs: list[tuple[float, float]], p33: float, p67: float
    ) -> tuple[dict | None, dict | None, dict | None]:
        """Return (low_stats, mid_stats, high_stats) or None buckets when bucket < 3 rows."""
        low = [(sc, ret) for sc, ret in pairs if sc < p33]
        mid = [(sc, ret) for sc, ret in pairs if p33 <= sc < p67]
        high = [(sc, ret) for sc, ret in pairs if sc >= p67]

        def _stats(bucket: list[tuple[float, float]]) -> dict | None:
            if len(bucket) < 3:
                return None
            rets = [r for _, r in bucket]
            wr = round(sum(1 for r in rets if r > 0) / len(rets), 6)
            avg_r = round(sum(rets) / len(rets), 6)
            return {"win_rate": wr, "avg_return": avg_r, "count": len(bucket)}

        return _stats(low), _stats(mid), _stats(high)

    result = dict(_null)

    # --- Volume expansion quality analysis ---
    veq_pairs: list[tuple[float, float]] = [
        (float(row["volume_expansion_quality"]), float(row["next_close_return"]))
        for row in rows
        if row.get("volume_expansion_quality") is not None and row.get("next_close_return") is not None
    ]
    if len(veq_pairs) >= 9:
        sorted_veq = sorted(v for v, _ in veq_pairs)
        n_veq = len(sorted_veq)
        p33_veq = sorted_veq[int(n_veq * 0.33)]
        p67_veq = sorted_veq[int(n_veq * 0.67)]
        low_s, mid_s, high_s = _bucket_stats(veq_pairs, p33_veq, p67_veq)
        if low_s is not None:
            result["volume_low_win_rate"] = low_s["win_rate"]
            result["volume_low_avg_return"] = low_s["avg_return"]
        if mid_s is not None:
            result["volume_mid_win_rate"] = mid_s["win_rate"]
            result["volume_mid_avg_return"] = mid_s["avg_return"]
        if high_s is not None:
            result["volume_high_win_rate"] = high_s["win_rate"]
            result["volume_high_avg_return"] = high_s["avg_return"]

        if low_s is not None and mid_s is not None and high_s is not None:
            result["volume_monotone_win_rate"] = bool(
                high_s["win_rate"] >= mid_s["win_rate"] >= low_s["win_rate"]
            )
            result["extreme_volume_win_rate_premium"] = round(
                high_s["win_rate"] - low_s["win_rate"], 6
            )
        elif low_s is not None and high_s is not None:
            result["extreme_volume_win_rate_premium"] = round(
                high_s["win_rate"] - low_s["win_rate"], 6
            )

    # --- Net inflow ratio analysis ---
    enir_pairs: list[tuple[float, float]] = [
        (float(row["t0_estimated_net_inflow_ratio"]), float(row["next_close_return"]))
        for row in rows
        if row.get("t0_estimated_net_inflow_ratio") is not None and row.get("next_close_return") is not None
    ]
    if len(enir_pairs) >= 9:
        sorted_enir = sorted(v for v, _ in enir_pairs)
        n_enir = len(sorted_enir)
        p33_enir = sorted_enir[int(n_enir * 0.33)]
        p67_enir = sorted_enir[int(n_enir * 0.67)]
        i_low, i_mid, i_high = _bucket_stats(enir_pairs, p33_enir, p67_enir)
        if i_low is not None:
            result["inflow_low_win_rate"] = i_low["win_rate"]
        if i_mid is not None:
            result["inflow_mid_win_rate"] = i_mid["win_rate"]
        if i_high is not None:
            result["inflow_high_win_rate"] = i_high["win_rate"]
        if i_low is not None and i_high is not None:
            prem = round(i_high["win_rate"] - i_low["win_rate"], 6)
            result["inflow_win_rate_premium"] = prem

    # --- Combined alignment signal ---
    mono = result.get("volume_monotone_win_rate")
    inflow_prem = result.get("inflow_win_rate_premium")
    if mono is not None and inflow_prem is not None:
        result["volume_inflow_alignment"] = bool(mono and inflow_prem > 0.05)

    return result


# ---------------------------------------------------------------------------
# Round 32, Task 3 (Beta): Composite gate score
# ---------------------------------------------------------------------------
# Aggregates six key quality dimensions into a single 0–100 tradability score.
# Accepts the fully-populated surface_summary dict (after all other analysis
# functions have run) so it can read any previously computed metric.


def compute_composite_gate_score(surface_summary: dict) -> dict:
    """Compute a 0–100 composite gate score from six quality dimensions.

    Each dimension is linearly scaled from its practical floor (0 pts) to its
    practical ceiling (full weight).  Dimensions with ``None`` values are skipped
    and the remaining weights are re-normalised so the maximum possible score is
    always 100.

    Args:
        surface_summary: Fully-populated surface summary dict as returned by
                         ``build_surface_summary`` (or equivalent).

    Returns:
        Dict with keys:

        - ``composite_gate_score``: float — 0–100 composite tradability score (1 d.p.).
        - ``gate_score_grade``: str — "A" (≥80) / "B" (≥65) / "C" (≥50) / "D" (<50).
        - ``trade_recommended``: bool — True when composite_gate_score ≥ 65.
        - ``gate_score_components``: dict — per-dimension (raw_value, score, weight) breakdown.
    """
    # (key, floor, ceiling, weight, higher_is_better)
    _DIMS: list[tuple[str, float, float, float, bool]] = [
        ("next_close_positive_rate", 0.45, 0.55, 20.0, True),
        ("regime_consistency_score", 0.60, 0.80, 15.0, True),
        ("profile_health_score", 50.0, 80.0, 15.0, True),
        ("realized_payoff_ratio", 1.0, 1.5, 20.0, True),
        ("overfit_score", 0.20, 0.0, 15.0, False),  # lower is better; ceiling < floor intentionally
        ("kelly_fraction_half", 0.02, 0.05, 15.0, True),
    ]

    components: dict[str, dict] = {}
    total_weight = 0.0
    raw_score = 0.0

    for key, floor_v, ceiling_v, weight, higher_better in _DIMS:
        val = surface_summary.get(key)
        if val is None:
            components[key] = {"raw_value": None, "score": None, "weight": weight}
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            components[key] = {"raw_value": val, "score": None, "weight": weight}
            continue

        if higher_better:
            frac = (fval - floor_v) / (ceiling_v - floor_v) if ceiling_v != floor_v else 0.0
        else:
            # lower is better: floor_v is the BAD end, ceiling_v is the GOOD end
            frac = (floor_v - fval) / (floor_v - ceiling_v) if floor_v != ceiling_v else 0.0

        frac = max(0.0, min(1.0, frac))
        dim_score = frac * weight
        raw_score += dim_score
        total_weight += weight
        components[key] = {"raw_value": round(fval, 6), "score": round(dim_score, 4), "weight": weight}

    if total_weight <= 0.0:
        return {
            "composite_gate_score": None,
            "gate_score_grade": None,
            "trade_recommended": None,
            "gate_score_components": components,
        }

    # Normalise so maximum achievable = 100.
    gate_score = round((raw_score / total_weight) * 100.0, 1)
    gate_score = max(0.0, min(100.0, gate_score))

    if gate_score >= 80.0:
        grade = "A"
    elif gate_score >= 65.0:
        grade = "B"
    elif gate_score >= 50.0:
        grade = "C"
    else:
        grade = "D"

    return {
        "composite_gate_score": gate_score,
        "gate_score_grade": grade,
        "trade_recommended": bool(gate_score >= 65.0),
        "gate_score_components": components,
    }


# ---------------------------------------------------------------------------
# Round 33, Task 1 (Alpha): Expected value per trade
# ---------------------------------------------------------------------------
# Directly optimises E[R] = win_rate × avg_win − loss_rate × avg_loss.
# Requires at least 10 rows with a valid next_close_return to produce estimates.


def compute_expected_value_metrics(rows: list[dict]) -> dict:
    """Compute expected-value metrics from T+1 next-close return column.

    Args:
        rows: List of trade-row dicts, each expected to carry a
              ``next_close_return`` float (or ``None`` to skip).

    Returns:
        Dict with keys:

        - ``expected_value_per_trade``: float — E[R] = wr×avg_win + lr×avg_loss.
        - ``win_rate_ev``: float — fraction of positive-return rows.
        - ``avg_win_return``: float — mean return of winning rows (≥ 0).
        - ``avg_loss_return``: float — mean return of losing rows (≤ 0).
        - ``payoff_ratio_ev``: float | None — avg_win / |avg_loss|; None when no losses.
        - ``ev_positive``: bool — True when expected_value_per_trade > 0.
        - ``ev_grade``: str — "A"(>0.015) / "B"(>0.005) / "C"(>0) / "D"(≤0).

        All values are ``None`` when fewer than 10 valid rows are available.
    """
    _EMPTY: dict[str, Any] = {
        "expected_value_per_trade": None,
        "win_rate_ev": None,
        "avg_win_return": None,
        "avg_loss_return": None,
        "payoff_ratio_ev": None,
        "ev_positive": None,
        "ev_grade": None,
    }
    returns = [float(row["next_close_return"]) for row in rows if row.get("next_close_return") is not None]
    if len(returns) < 10:
        return _EMPTY
    win_rows = [r for r in returns if r > 0]
    loss_rows = [r for r in returns if r <= 0]
    win_rate_ev = len(win_rows) / len(returns)
    avg_win_return = round(mean(win_rows), 6) if win_rows else 0.0
    avg_loss_return = round(mean(loss_rows), 6) if loss_rows else 0.0
    loss_rate = 1.0 - win_rate_ev
    ev = round(win_rate_ev * avg_win_return + loss_rate * avg_loss_return, 6)
    payoff_ratio_ev = round(avg_win_return / abs(avg_loss_return), 4) if avg_loss_return != 0 else None
    ev_positive = ev > 0
    if ev > 0.015:
        ev_grade: str = "A"
    elif ev > 0.005:
        ev_grade = "B"
    elif ev > 0:
        ev_grade = "C"
    else:
        ev_grade = "D"
    return {
        "expected_value_per_trade": ev,
        "win_rate_ev": round(win_rate_ev, 4),
        "avg_win_return": avg_win_return,
        "avg_loss_return": avg_loss_return,
        "payoff_ratio_ev": payoff_ratio_ev,
        "ev_positive": ev_positive,
        "ev_grade": ev_grade,
    }


# ---------------------------------------------------------------------------
# Round 33, Task 2 (Gamma): Momentum decay curve
# ---------------------------------------------------------------------------
# Fits the T+1 / T+2 / T+3 absolute-return amplitude decay and derives a
# half-life that captures how quickly post-selection momentum fades.  A short
# half-life (< 1.5 days) confirms that BTST fast-exit is optimal; a long
# half-life (≥ 3 days) suggests wider holding horizons could add value.


def compute_momentum_decay_curve(rows: list[dict]) -> dict:
    """Fit a momentum-amplitude decay curve across T+1, T+2, T+3 horizons.

    Supports two sets of field-name conventions for the multi-day return columns:

    - ``t2_return`` / ``t3_return`` (test-friendly short names), **or**
    - ``t_plus_2_close_return`` / ``t_plus_3_close_return`` (production field names).

    The function uses whichever is present, preferring the short names.

    Args:
        rows: Trade-row dicts.  Must contain ``next_close_return`` (T+1); T+2 and
              T+3 columns are optional — their absence triggers a graceful empty result.

    Returns:
        Dict with keys:

        - ``momentum_half_life_days``: float | None — days until amplitude halves (clamped [0.5, 10]).
        - ``decay_curve_valid``: bool — True when sufficient data existed to fit the curve.
        - ``avg_t1_abs`` / ``avg_t2_abs`` / ``avg_t3_abs``: mean absolute returns per horizon.
        - ``momentum_persists``: bool — True when avg_t2_abs > 0.5 × avg_t1_abs.
        - ``decay_speed``: str — "fast"(<1.5d) / "medium"(<3d) / "slow"(≥3d).
    """
    import math as _math

    _EMPTY_DECAY: dict[str, Any] = {"momentum_half_life_days": None, "decay_curve_valid": False}

    def _get_t2(row: dict) -> float | None:
        v = row.get("t2_return")
        if v is None:
            v = row.get("t_plus_2_close_return")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _get_t3(row: dict) -> float | None:
        v = row.get("t3_return")
        if v is None:
            v = row.get("t_plus_3_close_return")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    t2_vals = [_get_t2(r) for r in rows]
    t3_vals = [_get_t3(r) for r in rows]
    t2_valid = [v for v in t2_vals if v is not None]
    t3_valid = [v for v in t3_vals if v is not None]

    # Graceful exit when T+2 / T+3 columns are wholly absent or undersized.
    if not t2_valid and not t3_valid:
        return _EMPTY_DECAY

    t1_vals = [float(r["next_close_return"]) for r in rows if r.get("next_close_return") is not None]
    if len(t1_vals) < 5 or len(t2_valid) < 5:
        return _EMPTY_DECAY

    avg_t1 = abs(mean(t1_vals))
    avg_t2 = abs(mean(t2_valid))
    avg_t3: float | None = abs(mean(t3_valid)) if len(t3_valid) >= 5 else None

    if avg_t1 <= 0.0:
        return _EMPTY_DECAY

    ratio = avg_t1 / max(avg_t2, 1e-6)
    if ratio <= 1.0:
        half_life = 10.0
    else:
        half_life = round(1.0 / _math.log2(ratio), 4)
    half_life = max(0.5, min(10.0, half_life))

    momentum_persists = avg_t2 > avg_t1 * 0.5

    if half_life < 1.5:
        decay_speed: str = "fast"
    elif half_life < 3.0:
        decay_speed = "medium"
    else:
        decay_speed = "slow"

    return {
        "momentum_half_life_days": half_life,
        "avg_t1_abs": round(avg_t1, 6),
        "avg_t2_abs": round(avg_t2, 6),
        "avg_t3_abs": round(avg_t3, 6) if avg_t3 is not None else None,
        "momentum_persists": momentum_persists,
        "decay_speed": decay_speed,
        "decay_curve_valid": True,
    }


# ---------------------------------------------------------------------------
# Round 34, Task 1 (Alpha): Multi-factor conditional joint effect
# ---------------------------------------------------------------------------
# Analyses whether win rate jumps significantly when multiple factors are
# simultaneously in high-quantile territory (P67+).  A multi_factor_lift > 0.05
# indicates genuine multi-factor synergy beyond individual-factor contributions.


def compute_cross_factor_conditional(rows: list[dict]) -> dict:
    """Analyse win-rate uplift when multiple factors are simultaneously high-ranked.

    Uses a fixed set of 7 BTST factors.  For each row counts how many factors
    are at or above their 67th-percentile threshold, groups rows by that count
    (0 / 1 / 2 / 3+), and computes group-level win rates.

    Args:
        rows: Trade-row dicts containing ``next_close_return`` and the factor
              fields listed in ``_CROSS_FACTORS``.

    Returns:
        Dict with keys:

        - ``group_win_rates``: dict {0|1|2|"3+"→float|None} — group win rate.
        - ``group_counts``: dict {0|1|2|"3+"→int} — number of rows per group.
        - ``multi_factor_lift``: float|None — win_rate[3+] − win_rate[0].
        - ``multi_factor_synergy``: bool|None — True when lift > 0.05.
        - ``optimal_factor_count``: int|str|None — group key with highest win rate.
    """
    _CROSS_FACTORS: list[str] = [
        "close_strength",
        "volume_expansion_quality",
        "sector_resonance",
        "rs_sector_rank",
        "t0_estimated_net_inflow_ratio",
        "breakout_quality_score",
        "momentum_slope_20d",
    ]

    _EMPTY: dict[str, Any] = {
        "group_win_rates": {},
        "group_counts": {},
        "multi_factor_lift": None,
        "multi_factor_synergy": None,
        "optimal_factor_count": None,
    }

    valid_rows = [r for r in rows if r.get("next_close_return") is not None]
    if len(valid_rows) < 20:
        return _EMPTY

    # Determine which factors actually exist and have non-None values.
    active_factors = [f for f in _CROSS_FACTORS if any(r.get(f) is not None for r in valid_rows)]
    if not active_factors:
        return _EMPTY

    # Compute P67 threshold per active factor.
    p67: dict[str, float] = {}
    for f in active_factors:
        vals = sorted(float(r[f]) for r in valid_rows if r.get(f) is not None)
        if not vals:
            continue
        idx = max(0, int(len(vals) * 0.67) - 1)
        p67[f] = vals[idx]

    if not p67:
        return _EMPTY

    # Build groups: 0, 1, 2, "3+".
    groups: dict[int | str, list[float]] = {0: [], 1: [], 2: [], "3+": []}
    for r in valid_rows:
        cnt = sum(1 for f in p67 if r.get(f) is not None and float(r[f]) >= p67[f])
        key: int | str = cnt if cnt <= 2 else "3+"
        groups[key].append(float(r["next_close_return"]))

    group_win_rates: dict[int | str, float | None] = {}
    group_counts: dict[int | str, int] = {}
    for k, rets in groups.items():
        group_counts[k] = len(rets)
        if len(rets) >= 5:
            group_win_rates[k] = round(sum(1 for x in rets if x > 0.0) / len(rets), 4)
        else:
            group_win_rates[k] = None

    wr_0 = group_win_rates.get(0)
    wr_3p = group_win_rates.get("3+")
    multi_factor_lift: float | None = round(wr_3p - wr_0, 4) if (wr_0 is not None and wr_3p is not None) else None
    multi_factor_synergy: bool | None = (multi_factor_lift > 0.05) if multi_factor_lift is not None else None

    valid_wr_keys = [k for k in [0, 1, 2, "3+"] if group_win_rates.get(k) is not None]
    optimal_factor_count: int | str | None = max(valid_wr_keys, key=lambda k: group_win_rates[k]) if valid_wr_keys else None  # type: ignore[arg-type]

    return {
        "group_win_rates": group_win_rates,
        "group_counts": group_counts,
        "multi_factor_lift": multi_factor_lift,
        "multi_factor_synergy": multi_factor_synergy,
        "optimal_factor_count": optimal_factor_count,
    }


# ---------------------------------------------------------------------------
# Round 34, Task 2 (Gamma): Adaptive sizing score
# ---------------------------------------------------------------------------
# Synthesises EV, Kelly, gate score, and tail-separation into a single 0–100
# position-sizing recommendation.  Higher scores justify larger position sizes.


def compute_adaptive_sizing_score(summary_dict: dict) -> dict:
    """Compute a composite adaptive position-sizing score from surface metrics.

    Combines four dimensions — expected value (EV), half-Kelly fraction, composite
    gate score, and score-tail separation — into a single 0–100 index.  Each
    dimension contributes an equal weight of 25 points; missing dimensions are
    skipped and the remaining weights are normalised so the total is always 100.

    Args:
        summary_dict: Surface-summary dict as produced by ``build_surface_summary``.
                      Keys used: ``expected_value_per_trade``, ``kelly_half`` (or
                      ``kelly_fraction_half``), ``composite_gate_score``, and
                      ``score_tail_separation``.

    Returns:
        Dict with keys:

        - ``adaptive_sizing_score``: float — 0–100 composite score (1 d.p.).
        - ``sizing_multiplier``: float — 0.5–1.0 position-size multiplier.
        - ``sizing_grade``: str — 'A'(≥80) | 'B'(≥65) | 'C'(≥50) | 'D'(<50).
        - ``full_size_recommended``: bool — True when adaptive_sizing_score ≥ 75.
    """

    def _clamp(val: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, val))

    def _frac(val: float | None, lo: float, hi: float) -> float | None:
        if val is None:
            return None
        return _clamp((val - lo) / max(hi - lo, 1e-8), 0.0, 1.0)

    ev_raw = summary_dict.get("expected_value_per_trade")
    # Support both kelly_half (T2 naming in T2 task spec) and kelly_fraction_half (production key).
    kelly_raw = summary_dict.get("kelly_half") if summary_dict.get("kelly_half") is not None else summary_dict.get("kelly_fraction_half")
    gate_raw = summary_dict.get("composite_gate_score")
    tail_raw = summary_dict.get("score_tail_separation")

    try:
        ev_val = float(ev_raw) if ev_raw is not None else None
    except (TypeError, ValueError):
        ev_val = None
    try:
        kelly_val = float(kelly_raw) if kelly_raw is not None else None
    except (TypeError, ValueError):
        kelly_val = None
    try:
        gate_val = float(gate_raw) if gate_raw is not None else None
    except (TypeError, ValueError):
        gate_val = None
    try:
        tail_val = float(tail_raw) if tail_raw is not None else None
    except (TypeError, ValueError):
        tail_val = None

    dims: list[tuple[float | None, float]] = [
        (_frac(ev_val, -0.05, 0.05), 25.0),
        (_frac(kelly_val, 0.0, 0.30), 25.0),
        (_frac(gate_val, 0.0, 100.0), 25.0),
        (_frac(tail_val, -0.10, 0.10), 25.0),
    ]

    weighted_sum = 0.0
    active_weight = 0.0
    for frac, wt in dims:
        if frac is not None:
            weighted_sum += frac * wt
            active_weight += wt

    if active_weight <= 0.0:
        score = 0.0
    else:
        score = round((weighted_sum / active_weight) * 100.0, 1)

    sizing_multiplier = round(min(1.0, 0.5 + score / 200.0), 4)

    if score >= 80:
        sizing_grade = "A"
    elif score >= 65:
        sizing_grade = "B"
    elif score >= 50:
        sizing_grade = "C"
    else:
        sizing_grade = "D"

    full_size_recommended = score >= 75.0

    return {
        "adaptive_sizing_score": score,
        "sizing_multiplier": sizing_multiplier,
        "sizing_grade": sizing_grade,
        "full_size_recommended": full_size_recommended,
    }


# ---------------------------------------------------------------------------
# Round 35, Task 1 (Alpha): Sharpe / Sortino risk-adjusted return metrics
# ---------------------------------------------------------------------------
# Computes annualised Sharpe (total-volatility) and Sortino (downside-volatility)
# ratios from the per-window next_close_return series so the optimiser can
# distinguish strategies with good win-rates but fat left tails.


def compute_sharpe_sortino_analysis(rows: list[dict]) -> dict:
    """Compute Sharpe, Sortino, and Calmar proxy risk-adjusted return metrics.

    Uses ``next_close_return`` as the per-trade return series and annualises on a
    252-trading-day basis.  Both the standard Sharpe (total volatility) and the Sortino
    (downside volatility only) are computed so callers can distinguish strategies that
    have a high win rate but fat left tails.

    Args:
        rows: Per-row dicts each containing a ``next_close_return`` float field.
              Rows where the field is absent or None are silently skipped.

    Returns:
        Dict with keys:

        - ``sharpe_ratio``: float|None — annualised Sharpe, clamped [-5, 5].
        - ``sortino_ratio``: float|None — annualised Sortino, clamped [-5, 5].
        - ``calmar_proxy``: float|None — mean_r / |max single-trade loss|, clamped [-5, 5].
        - ``annualized_return``: float|None — mean_r × 252.
        - ``annualized_vol``: float|None — std_r × √252.
        - ``risk_adjusted_grade``: str|None — 'A'(sortino>1.5)/'B'(>0.5)/'C'(>0)/'D'(≤0).
        - ``sortino_positive``: bool|None — True when sortino_ratio > 0.

        All values are None when fewer than 10 valid rows are present.
    """
    import math

    returns: list[float] = [float(r["next_close_return"]) for r in rows if r.get("next_close_return") is not None]
    if len(returns) < 10:
        return {"sharpe_ratio": None, "sortino_ratio": None, "calmar_proxy": None, "annualized_return": None, "annualized_vol": None, "risk_adjusted_grade": None, "sortino_positive": None}

    n = len(returns)
    mean_r = sum(returns) / n
    if n >= 2:
        variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
        std_r = math.sqrt(max(variance, 0.0))
    else:
        std_r = 1.0

    annualized_return = mean_r * 252
    annualized_vol = std_r * math.sqrt(252)

    def _clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, v))

    sharpe_ratio = _clamp(annualized_return / max(annualized_vol, 1e-8), -5.0, 5.0)

    downside_returns = [r for r in returns if r < 0]
    if len(downside_returns) >= 2:
        dm = sum(downside_returns) / len(downside_returns)
        d_var = sum((r - dm) ** 2 for r in downside_returns) / (len(downside_returns) - 1)
        downside_std = math.sqrt(max(d_var, 0.0))
    else:
        downside_std = std_r

    annualized_downside_vol = downside_std * math.sqrt(252)
    sortino_ratio = _clamp(annualized_return / max(annualized_downside_vol, 1e-8), -5.0, 5.0)

    worst_loss = min(returns)
    calmar_proxy = _clamp(mean_r / max(abs(worst_loss), 1e-6), -5.0, 5.0)

    if sortino_ratio > 1.5:
        risk_adjusted_grade = "A"
    elif sortino_ratio > 0.5:
        risk_adjusted_grade = "B"
    elif sortino_ratio > 0:
        risk_adjusted_grade = "C"
    else:
        risk_adjusted_grade = "D"

    return {
        "sharpe_ratio": round(sharpe_ratio, 4),
        "sortino_ratio": round(sortino_ratio, 4),
        "calmar_proxy": round(calmar_proxy, 4),
        "annualized_return": round(annualized_return, 6),
        "annualized_vol": round(annualized_vol, 6),
        "risk_adjusted_grade": risk_adjusted_grade,
        "sortino_positive": sortino_ratio > 0,
    }


# ---------------------------------------------------------------------------
# Round 35, Task 3 (Beta): Candidate pool sector/industry diversity score
# ---------------------------------------------------------------------------
# Measures how diversified the candidate pool is across sectors or industries
# using the Herfindahl-Hirschman Index (HHI) as the concentration measure.
# A high HHI (near 1.0) signals sector-concentrated pool; low HHI means broad
# diversification.  Registered as a quality floor (≥ 0.30) so strategies that
# routinely concentrate in one sector are flagged.


def compute_candidate_diversity_score(rows: list[dict]) -> dict:
    """Compute sector/industry diversity score for the candidate pool.

    Evaluates how diversified the candidate pool is across sectors or industries,
    using the Herfindahl-Hirschman Index (HHI) as the concentration measure.
    A high HHI (near 1.0) signals a sector-concentrated pool; low HHI means
    broad diversification across many sectors.

    Args:
        rows: Per-row dicts each optionally containing ``sector`` or ``industry``
              string fields.  ``sector`` is preferred; ``industry`` is tried when
              ``sector`` is entirely absent from all rows.

    Returns:
        Dict with keys:

        - ``sector_hhi``: float|None — Herfindahl-Hirschman Index ∈ [1/n, 1.0].
        - ``diversity_score``: float|None — 1 − HHI ∈ [0, 1]; higher = more diverse.
        - ``diversity_grade``: str|None — 'A'(≥0.70)/'B'(≥0.50)/'C'(≥0.30)/'D'(<0.30).
        - ``sector_count``: int|None — number of distinct sectors in the pool.
        - ``dominant_sector_share``: float|None — fraction held by the largest sector.
        - ``concentration_risk``: bool|None — True when dominant sector > 50 % of pool.

        Returns a dict of all-None values when fewer than 5 valid rows are available.
    """
    _null: dict = {"sector_hhi": None, "diversity_score": None, "diversity_grade": None, "sector_count": None, "dominant_sector_share": None, "concentration_risk": None}

    sector_values: list = [r.get("sector") for r in rows]
    if all(v is None for v in sector_values):
        sector_values = [r.get("industry") for r in rows]

    valid: list[str] = [v for v in sector_values if v is not None]
    if len(valid) < 5:
        return _null

    counts: dict[str, int] = {}
    for s in valid:
        counts[s] = counts.get(s, 0) + 1
    total = len(valid)
    freq = {s: c / total for s, c in counts.items()}

    sector_hhi = sum(f ** 2 for f in freq.values())
    diversity_score = round(1.0 - sector_hhi, 4)
    sector_count = len(counts)
    dominant_sector_share = max(freq.values())

    if diversity_score >= 0.70:
        diversity_grade = "A"
    elif diversity_score >= 0.50:
        diversity_grade = "B"
    elif diversity_score >= 0.30:
        diversity_grade = "C"
    else:
        diversity_grade = "D"

    return {
        "sector_hhi": round(sector_hhi, 4),
        "diversity_score": diversity_score,
        "diversity_grade": diversity_grade,
        "sector_count": sector_count,
        "dominant_sector_share": round(dominant_sector_share, 4),
        "concentration_risk": dominant_sector_share > 0.50,
    }


# ---------------------------------------------------------------------------
# Round 36, Task 1 (Alpha): Return percentile breakdown — right-tail dominance
# ---------------------------------------------------------------------------
def compute_return_percentile_breakdown(rows: list[dict]) -> dict:
    """Compute detailed return distribution percentiles and right-tail dominance metrics.

    Analyses the shape of the T+1 return distribution, focusing on whether the right
    tail (upside) is wider than the left tail (downside) — a prerequisite for BTST
    profitability even at moderate win rates.

    Args:
        rows: Per-row dicts each containing ``next_close_return`` (float|None).

    Returns:
        Dict with keys:

        - ``p5, p10, p25, p50, p75, p90, p95``: float|None — distribution percentiles.
        - ``right_tail_dominance``: float|None — (P95−P50)/|P5−P50|, clamped [0, 5].
        - ``iqr``: float|None — interquartile range P75−P25.
        - ``iqr_ratio``: float|None — IQR/|P50|, clamped [0, 10].
        - ``upper_fence``: float|None — P75 + 1.5×IQR.
        - ``lower_fence``: float|None — P25 − 1.5×IQR.
        - ``right_outlier_rate``: float|None — fraction of returns above upper_fence.
        - ``left_outlier_rate``: float|None — fraction of returns below lower_fence.
        - ``tail_asymmetry_index``: float|None — right_outlier_rate − left_outlier_rate.

        Returns all-None dict when fewer than 10 valid rows are available.
    """
    _null: dict = {
        "p5": None, "p10": None, "p25": None, "p50": None,
        "p75": None, "p90": None, "p95": None,
        "right_tail_dominance": None, "iqr": None, "iqr_ratio": None,
        "upper_fence": None, "lower_fence": None,
        "right_outlier_rate": None, "left_outlier_rate": None,
        "tail_asymmetry_index": None,
    }
    returns = [float(r["next_close_return"]) for r in rows if r.get("next_close_return") is not None]
    if len(returns) < 10:
        return _null

    p5, p10, p25, p50, p75, p90, p95 = np.percentile(returns, [5, 10, 25, 50, 75, 90, 95]).tolist()
    iqr = p75 - p25
    iqr_ratio = min(10.0, iqr / max(abs(p50), 1e-6))
    upper_fence = p75 + 1.5 * iqr
    lower_fence = p25 - 1.5 * iqr
    n = len(returns)
    right_outlier_rate = sum(1 for r in returns if r > upper_fence) / n
    left_outlier_rate = sum(1 for r in returns if r < lower_fence) / n
    tail_asymmetry_index = right_outlier_rate - left_outlier_rate
    right_tail_dominance = min(5.0, (p95 - p50) / max(abs(p5 - p50), 1e-6))
    right_tail_dominance = max(0.0, right_tail_dominance)
    return {
        "p5": round(p5, 6), "p10": round(p10, 6), "p25": round(p25, 6),
        "p50": round(p50, 6), "p75": round(p75, 6), "p90": round(p90, 6), "p95": round(p95, 6),
        "right_tail_dominance": round(right_tail_dominance, 4),
        "iqr": round(iqr, 6),
        "iqr_ratio": round(iqr_ratio, 4),
        "upper_fence": round(upper_fence, 6),
        "lower_fence": round(lower_fence, 6),
        "right_outlier_rate": round(right_outlier_rate, 4),
        "left_outlier_rate": round(left_outlier_rate, 4),
        "tail_asymmetry_index": round(tail_asymmetry_index, 4),
    }


# ---------------------------------------------------------------------------
# Round 36, Task 2 (Beta): Composite score IC — Spearman rank correlation
# ---------------------------------------------------------------------------
def compute_composite_score_ic(rows: list[dict]) -> dict:
    """Compute Spearman IC between composite score and T+1 return — verifies predictive validity.

    Uses the first available score field (runner_composite_score > composite_score > score)
    and computes Spearman rank correlation against next_close_return.  A positive IC
    confirms the scoring function correctly ranks candidates by future return.

    Args:
        rows: Per-row dicts each optionally containing a composite score field
              and ``next_close_return`` (float|None).

    Returns:
        Dict with keys:

        - ``composite_ic``: float|None — Spearman IC ∈ [−1, 1].
        - ``composite_ic_positive``: bool|None — True when IC > 0.
        - ``composite_ic_magnitude``: str|None — 'strong'(>0.10)/'moderate'(>0.05)/'weak'.
        - ``ic_t_stat``: float|None — t-statistic for H₀: IC = 0.
        - ``ic_significant``: bool|None — True when |t| > 1.96 (95 % confidence).

        Returns ``composite_ic=None, composite_ic_positive=None`` dict when fewer than
        10 paired observations are available.
    """
    _null: dict = {
        "composite_ic": None, "composite_ic_positive": None,
        "composite_ic_magnitude": None, "ic_t_stat": None, "ic_significant": None,
    }

    def _spearman_ic(x: list[float], y: list[float]) -> float:
        n = len(x)
        rank_x = sorted(range(n), key=lambda i: x[i])
        rank_y = sorted(range(n), key=lambda i: y[i])
        rx = [0] * n
        ry = [0] * n
        for r, i in enumerate(rank_x):
            rx[i] = r
        for r, i in enumerate(rank_y):
            ry[i] = r
        mean_rx = sum(rx) / n
        mean_ry = sum(ry) / n
        num = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
        den = (sum((rx[i] - mean_rx) ** 2 for i in range(n)) * sum((ry[i] - mean_ry) ** 2 for i in range(n))) ** 0.5
        return num / max(den, 1e-8)

    pairs: list[tuple[float, float]] = []
    for r in rows:
        ret = r.get("next_close_return")
        if ret is None:
            continue
        score = r.get("runner_composite_score")
        if score is None:
            score = r.get("composite_score")
        if score is None:
            score = r.get("score")
        if score is None:
            continue
        pairs.append((float(score), float(ret)))

    if len(pairs) < 10:
        return _null

    scores_list = [p[0] for p in pairs]
    returns_list = [p[1] for p in pairs]
    n = len(pairs)
    ic_raw = _spearman_ic(scores_list, returns_list)
    ic = max(-1.0, min(1.0, ic_raw))
    ic_t_stat = ic * ((n - 2) ** 0.5) / max((1 - ic ** 2) ** 0.5, 1e-8)
    if abs(ic) > 0.10:
        magnitude = "strong"
    elif abs(ic) > 0.05:
        magnitude = "moderate"
    else:
        magnitude = "weak"
    return {
        "composite_ic": round(ic, 6),
        "composite_ic_positive": ic > 0,
        "composite_ic_magnitude": magnitude,
        "ic_t_stat": round(ic_t_stat, 4),
        "ic_significant": abs(ic_t_stat) > 1.96,
    }


# ---------------------------------------------------------------------------
# Round 36, Task 3 (Gamma): Win-rate Bootstrap confidence interval
# ---------------------------------------------------------------------------
def compute_win_rate_confidence_interval(rows: list[dict]) -> dict:
    """Estimate win-rate 95 % confidence interval via deterministic Bootstrap (seed=42).

    Uses 200 bootstrap resamplings with a fixed random.Random(42) seed to produce
    a reproducible, scipy-free confidence interval for the observed win rate.
    A narrow CI (< 20 %) indicates the estimate is reliable; a wide CI signals
    insufficient sample size.

    Args:
        rows: Per-row dicts each containing ``next_close_return`` (float|None).

    Returns:
        Dict with keys:

        - ``observed_win_rate``: float|None — fraction of returns > 0.
        - ``ci_lower``: float|None — P2.5 of bootstrap distribution.
        - ``ci_upper``: float|None — P97.5 of bootstrap distribution.
        - ``ci_width``: float|None — ci_upper − ci_lower.
        - ``win_rate_reliable``: bool|None — True when ci_width < 0.20.
        - ``win_rate_ci_grade``: str|None — 'A'(<0.10)/'B'(<0.15)/'C'(<0.20)/'D'(≥0.20).

        Returns all-None dict when fewer than 10 valid rows are available.
    """
    import random

    _null: dict = {
        "observed_win_rate": None, "ci_lower": None, "ci_upper": None,
        "ci_width": None, "win_rate_reliable": None, "win_rate_ci_grade": None,
    }
    returns = [float(r["next_close_return"]) for r in rows if r.get("next_close_return") is not None]
    if len(returns) < 10:
        return _null

    wins = [1 if r > 0 else 0 for r in returns]
    n = len(wins)
    observed_win_rate = sum(wins) / n
    rng = random.Random(42)
    boot_rates: list[float] = []
    for _ in range(200):
        sample = [rng.choice(wins) for _ in range(n)]
        boot_rates.append(sum(sample) / n)
    boot_rates.sort()
    ci_lower = boot_rates[int(0.025 * 200)]
    ci_upper = boot_rates[int(0.975 * 200)]
    ci_width = ci_upper - ci_lower
    if ci_width < 0.10:
        grade = "A"
    elif ci_width < 0.15:
        grade = "B"
    elif ci_width < 0.20:
        grade = "C"
    else:
        grade = "D"
    return {
        "observed_win_rate": round(observed_win_rate, 4),
        "ci_lower": round(ci_lower, 4),
        "ci_upper": round(ci_upper, 4),
        "ci_width": round(ci_width, 4),
        "win_rate_reliable": ci_width < 0.20,
        "win_rate_ci_grade": grade,
    }


# ---------------------------------------------------------------------------
# Round 37, Task 1 (Alpha): Optimal holding period analysis — T+1 / T+2 / T+3
# ---------------------------------------------------------------------------
def compute_holding_period_analysis(rows: list[dict]) -> dict:
    """Compare T+1, T+2, T+3 exit strategies and determine optimal holding period.

    For each available holding period (T+1 always present; T+2/T+3 conditional),
    computes average return, win rate, and expected value (EV).  Selects the
    holding period with the highest EV as ``optimal_holding_days``.

    Args:
        rows: Per-row dicts containing ``next_close_return`` (T+1, required),
            ``t2_return`` (T+2, optional), ``t3_return`` (T+3, optional).

    Returns:
        Dict with keys:

        - ``optimal_holding_days``: int — 1/2/3, argmax of EV across valid periods.
        - ``holding_analysis_valid``: bool — False when T+2/T+3 data fully absent.
        - ``avg_return_t1``: float|None — mean T+1 next_close_return.
        - ``avg_return_t2``: float|None — mean T+2 return (None if unavailable).
        - ``avg_return_t3``: float|None — mean T+3 return (None if unavailable).
        - ``ev_t1``: float|None — T+1 expected value.
        - ``ev_t2``: float|None — T+2 expected value.
        - ``ev_t3``: float|None — T+3 expected value.
        - ``holding_period_monotone``: bool|None — True when avg T+1≥T+2≥T+3 (only when all 3 valid).
        - ``t1_vs_t2_advantage``: float|None — ev_t1 − ev_t2 (positive = T+1 better).
        - ``multi_day_cumulative_return``: float|None — simple sum of available avg returns.
    """
    _null: dict = {
        "optimal_holding_days": 1,
        "holding_analysis_valid": False,
        "avg_return_t1": None,
        "avg_return_t2": None,
        "avg_return_t3": None,
        "ev_t1": None,
        "ev_t2": None,
        "ev_t3": None,
        "holding_period_monotone": None,
        "t1_vs_t2_advantage": None,
        "multi_day_cumulative_return": None,
    }

    def _compute_ev(vals: list[float]) -> float | None:
        if len(vals) < 5:
            return None
        wins = [v for v in vals if v > 0]
        losses = [v for v in vals if v <= 0]
        n = len(vals)
        if n == 0:
            return None
        win_rate = len(wins) / n
        loss_rate = len(losses) / n
        avg_win = sum(wins) / max(len(wins), 1) if wins else 0.0
        avg_loss = abs(sum(losses) / max(len(losses), 1)) if losses else 0.0
        return round(win_rate * avg_win - loss_rate * avg_loss, 6)

    def _extract(field: str) -> list[float]:
        return [float(r[field]) for r in rows if r.get(field) is not None]

    t1_vals = _extract("next_close_return")
    t2_vals = _extract("t2_return")
    t3_vals = _extract("t3_return")

    if len(t1_vals) < 5:
        return _null

    has_t2 = len(t2_vals) >= 5
    has_t3 = len(t3_vals) >= 5

    if not has_t2 and not has_t3:
        ev_t1 = _compute_ev(t1_vals)
        avg_t1 = round(sum(t1_vals) / max(len(t1_vals), 1), 6)
        return {
            **_null,
            "avg_return_t1": avg_t1,
            "ev_t1": ev_t1,
            "multi_day_cumulative_return": avg_t1,
        }

    avg_t1 = round(sum(t1_vals) / max(len(t1_vals), 1), 6)
    avg_t2 = round(sum(t2_vals) / max(len(t2_vals), 1), 6) if has_t2 else None
    avg_t3 = round(sum(t3_vals) / max(len(t3_vals), 1), 6) if has_t3 else None
    ev_t1 = _compute_ev(t1_vals)
    ev_t2 = _compute_ev(t2_vals) if has_t2 else None
    ev_t3 = _compute_ev(t3_vals) if has_t3 else None

    ev_map: dict[int, float] = {}
    if ev_t1 is not None:
        ev_map[1] = ev_t1
    if ev_t2 is not None:
        ev_map[2] = ev_t2
    if ev_t3 is not None:
        ev_map[3] = ev_t3
    optimal_holding_days = max(ev_map, key=lambda d: ev_map[d]) if ev_map else 1

    monotone: bool | None = None
    if has_t2 and has_t3 and avg_t2 is not None and avg_t3 is not None:
        monotone = avg_t1 >= avg_t2 >= avg_t3

    t1_vs_t2_adv: float | None = None
    if ev_t2 is not None and ev_t1 is not None:
        t1_vs_t2_adv = round(ev_t1 - ev_t2, 6)

    cumulative = round(avg_t1 + (avg_t2 if avg_t2 is not None else 0.0) + (avg_t3 if avg_t3 is not None else 0.0), 6)

    return {
        "optimal_holding_days": optimal_holding_days,
        "holding_analysis_valid": True,
        "avg_return_t1": avg_t1,
        "avg_return_t2": avg_t2,
        "avg_return_t3": avg_t3,
        "ev_t1": ev_t1,
        "ev_t2": ev_t2,
        "ev_t3": ev_t3,
        "holding_period_monotone": monotone,
        "t1_vs_t2_advantage": t1_vs_t2_adv,
        "multi_day_cumulative_return": cumulative,
    }


# ---------------------------------------------------------------------------
# Round 37, Task 2 (Beta): Loss trade factor signature — divergence-based warning
# ---------------------------------------------------------------------------
def compute_loss_trade_signature(rows: list[dict]) -> dict:
    """Analyse factor characteristics of losing trades to build a loss-warning signal.

    For each of the 7 canonical BTST factors, computes the mean value in the
    win group vs. the loss group.  Large divergences indicate that the factor
    reliably separates winners from losers and can serve as a pre-entry warning.

    Args:
        rows: Per-row dicts with ``next_close_return`` (float|None) and factor fields.

    Returns:
        Dict with keys:

        - ``loss_warning_factors``: list[str] — factors with divergence > 0.05.
        - ``loss_warning_factor_count``: int — len(loss_warning_factors).
        - ``loss_signature_strength``: float|None — mean |divergence| across all factors.
        - ``loss_avoidable``: bool|None — True when loss_signature_strength > 0.03.
        - ``factor_divergence``: dict[str, float|None] — per-factor win−loss mean diff.

        Returns all-None/empty dict when fewer than 10 valid rows are available.
    """
    _factors = [
        "close_strength",
        "volume_expansion_quality",
        "sector_resonance",
        "rs_sector_rank",
        "t0_estimated_net_inflow_ratio",
        "breakout_quality_score",
        "momentum_slope_20d",
    ]
    _null: dict = {
        "loss_warning_factors": [],
        "loss_warning_factor_count": 0,
        "loss_signature_strength": None,
        "loss_avoidable": None,
        "factor_divergence": {f: None for f in _factors},
    }

    valid = [r for r in rows if r.get("next_close_return") is not None]
    if len(valid) < 10:
        return _null

    win_rows = [r for r in valid if float(r["next_close_return"]) > 0]
    loss_rows = [r for r in valid if float(r["next_close_return"]) <= 0]

    factor_divergence: dict[str, float | None] = {}
    for f in _factors:
        w_vals = [float(r[f]) for r in win_rows if r.get(f) is not None]
        l_vals = [float(r[f]) for r in loss_rows if r.get(f) is not None]
        if len(w_vals) < 3 or len(l_vals) < 3:
            factor_divergence[f] = None
            continue
        win_avg = sum(w_vals) / max(len(w_vals), 1)
        loss_avg = sum(l_vals) / max(len(l_vals), 1)
        factor_divergence[f] = round(win_avg - loss_avg, 6)

    loss_warning_factors = [f for f in _factors if factor_divergence.get(f) is not None and factor_divergence[f] > 0.05]  # type: ignore[operator]
    abs_divs = [abs(d) for d in factor_divergence.values() if d is not None]
    loss_signature_strength: float | None = None
    loss_avoidable: bool | None = None
    if abs_divs:
        loss_signature_strength = round(sum(abs_divs) / max(len(abs_divs), 1), 6)
        loss_avoidable = loss_signature_strength > 0.03

    return {
        "loss_warning_factors": loss_warning_factors,
        "loss_warning_factor_count": len(loss_warning_factors),
        "loss_signature_strength": loss_signature_strength,
        "loss_avoidable": loss_avoidable,
        "factor_divergence": factor_divergence,
    }


# ---------------------------------------------------------------------------
# Round 37, Task 3 (Gamma): Score Gini coefficient — evaluation distribution quality
# ---------------------------------------------------------------------------
def compute_score_gini_coefficient(rows: list[dict]) -> dict:
    """Measure score distribution concentration via Gini coefficient (Lorenz-curve area method).

    A Gini of 0 means all candidates share identical scores (no discrimination power).
    A Gini of 1 means a single candidate holds all score mass (excessive concentration).
    The ideal range 0.30–0.60 provides meaningful differentiation without extreme elitism.

    Args:
        rows: Per-row dicts with ``runner_composite_score`` (float|None) or
            ``composite_score`` (float|None) as fallback.

    Returns:
        Dict with keys:

        - ``score_gini``: float|None — Gini coefficient in [0, 1].
        - ``top20_share``: float|None — fraction of total score mass held by top 20 % rows.
        - ``elite_candidate_rate``: float|None — fraction of rows at or above P80.
        - ``score_distribution_quality``: str|None — 'A'(0.3–0.6)/'B'(0.2–0.7 excl A)/'C' otherwise.
        - ``score_well_differentiated``: bool|None — True when 0.20 ≤ gini ≤ 0.65.

        Returns all-None dict when fewer than 5 valid rows are available.
    """
    _null: dict = {
        "score_gini": None,
        "top20_share": None,
        "elite_candidate_rate": None,
        "score_distribution_quality": None,
        "score_well_differentiated": None,
    }

    raw_scores: list[float] = []
    for r in rows:
        v = r.get("runner_composite_score")
        if v is None:
            v = r.get("composite_score")
        if v is not None:
            raw_scores.append(float(v))

    if len(raw_scores) < 5:
        return _null

    min_s = min(raw_scores)
    scores = [s - min_s + 1e-6 for s in raw_scores]
    n = len(scores)
    scores_sorted = sorted(scores)
    total = sum(scores_sorted)
    cumsum = 0.0
    lorenz_sum = 0.0
    for s in scores_sorted:
        cumsum += s
        lorenz_sum += cumsum
    gini = 1.0 - 2.0 * lorenz_sum / max(n * total, 1e-8) + 1.0 / n
    gini = max(0.0, min(1.0, round(gini, 4)))

    total_sum = sum(scores_sorted)
    top20_count = max(1, int(0.20 * n))
    top20_share = round(sum(scores_sorted[-top20_count:]) / max(total_sum, 1e-8), 4)

    p80_idx = int(0.80 * n)
    p80_val = scores_sorted[p80_idx] if p80_idx < n else scores_sorted[-1]
    elite_candidate_rate = round(len([s for s in scores if s >= p80_val]) / max(n, 1), 4)

    if 0.3 <= gini <= 0.6:
        quality = "A"
    elif 0.2 <= gini < 0.3 or 0.6 < gini <= 0.7:
        quality = "B"
    else:
        quality = "C"

    return {
        "score_gini": gini,
        "top20_share": top20_share,
        "elite_candidate_rate": elite_candidate_rate,
        "score_distribution_quality": quality,
        "score_well_differentiated": 0.20 <= gini <= 0.65,
    }


# ---------------------------------------------------------------------------
# Round 38, Task 1 (Alpha): Market environment sensitivity — bull vs bear
# ---------------------------------------------------------------------------
def compute_market_environment_sensitivity(rows: list[dict]) -> dict:
    """Analyse strategy win-rate sensitivity to market environment (bull vs bear).

    Uses ``sector_resonance`` as a market-environment proxy: high resonance = bull-leaning
    market, low resonance = bear-leaning.  Splits at the P50 of ``sector_resonance``
    and computes win-rate / avg-return for each half.  The ``env_win_rate_gap`` metric
    surfaces environment-dependency so the optimizer can penalise strategies that only
    work in favourable macro conditions.

    Args:
        rows: Per-row dicts with ``next_close_return`` (float|None) and
            ``sector_resonance`` (float|None).

    Returns:
        Dict with keys:

        - ``bull_env_win_rate``: float|None — win rate when sector_resonance >= P50.
        - ``bear_env_win_rate``: float|None — win rate when sector_resonance < P50.
        - ``bull_env_avg_return``: float|None — mean return in bull-env rows.
        - ``bear_env_avg_return``: float|None — mean return in bear-env rows.
        - ``market_sensitivity_ratio``: float|None — bull_wr / max(bear_wr, 1e-6), clamped [0, 5].
        - ``env_win_rate_gap``: float|None — bull_wr − bear_wr (positive = bull-env better).
        - ``environment_adaptive``: bool|None — True when env_win_rate_gap > 0.05.
        - ``market_neutral``: bool|None — True when |env_win_rate_gap| < 0.03.

        Returns all-None dict when fewer than 10 valid paired rows are available.
    """
    _null: dict = {
        "bull_env_win_rate": None,
        "bear_env_win_rate": None,
        "bull_env_avg_return": None,
        "bear_env_avg_return": None,
        "market_sensitivity_ratio": None,
        "env_win_rate_gap": None,
        "environment_adaptive": None,
        "market_neutral": None,
    }

    valid: list[tuple[float, float]] = []
    for r in rows:
        ret = r.get("next_close_return")
        sr = r.get("sector_resonance")
        if ret is not None and sr is not None:
            valid.append((float(ret), float(sr)))

    if len(valid) < 10:
        return _null

    srs_sorted = sorted(v[1] for v in valid)
    n = len(srs_sorted)
    mid = n // 2
    p50 = (srs_sorted[mid - 1] + srs_sorted[mid]) / 2.0 if n % 2 == 0 else srs_sorted[mid]

    bull_returns: list[float] = [r for r, sr in valid if sr >= p50]
    bear_returns: list[float] = [r for r, sr in valid if sr < p50]

    bull_win_rate: float | None = None
    bear_win_rate: float | None = None
    bull_avg: float | None = None
    bear_avg: float | None = None

    if len(bull_returns) >= 5:
        bull_win_rate = sum(1 for r in bull_returns if r > 0) / max(len(bull_returns), 1)
        bull_avg = sum(bull_returns) / max(len(bull_returns), 1)

    if len(bear_returns) >= 5:
        bear_win_rate = sum(1 for r in bear_returns if r > 0) / max(len(bear_returns), 1)
        bear_avg = sum(bear_returns) / max(len(bear_returns), 1)

    sensitivity_ratio: float | None = None
    gap: float | None = None
    env_adaptive: bool | None = None
    neutral: bool | None = None

    if bull_win_rate is not None and bear_win_rate is not None:
        raw_ratio = bull_win_rate / max(bear_win_rate, 1e-6)
        sensitivity_ratio = round(max(0.0, min(5.0, raw_ratio)), 4)
        gap = round(bull_win_rate - bear_win_rate, 4)
        env_adaptive = gap > 0.05
        neutral = abs(gap) < 0.03

    return {
        "bull_env_win_rate": round(bull_win_rate, 4) if bull_win_rate is not None else None,
        "bear_env_win_rate": round(bear_win_rate, 4) if bear_win_rate is not None else None,
        "bull_env_avg_return": round(bull_avg, 6) if bull_avg is not None else None,
        "bear_env_avg_return": round(bear_avg, 6) if bear_avg is not None else None,
        "market_sensitivity_ratio": sensitivity_ratio,
        "env_win_rate_gap": gap,
        "environment_adaptive": env_adaptive,
        "market_neutral": neutral,
    }


# ---------------------------------------------------------------------------
# Round 38, Task 2 (Beta): Factor importance ranking — per-factor Spearman IC
# ---------------------------------------------------------------------------
_FACTORS_TO_RANK: list[str] = [
    "close_strength", "volume_expansion_quality", "sector_resonance",
    "breakout_quality_score", "momentum_slope_20d", "volume_price_divergence",
    "catalyst_theme_score", "relative_strength_rank", "market_cap_score",
    "news_sentiment_score", "float_turnover_rate", "t0_estimated_net_inflow_ratio",
    "rs_sector_rank",
]


def compute_factor_importance_ranking(rows: list[dict]) -> dict:
    """Rank the 13 BTST factors by individual Spearman IC against ``next_close_return``.

    Each factor is independently evaluated for its linear rank-correlation with the T+1
    close return.  Factors are sorted from highest to lowest IC so the optimizer can
    identify the most/least predictive signals and detect factor homogeneity when the
    IC spread is small.

    Args:
        rows: Per-row dicts with ``next_close_return`` (float|None) plus factor columns
            from :data:`_FACTORS_TO_RANK`.

    Returns:
        Dict with keys:

        - ``factor_ic_ranking``: list[tuple[str, float]] — sorted (factor, IC) pairs, highest first.
        - ``top_factor``: str|None — factor with the highest IC.
        - ``bottom_factor``: str|None — factor with the lowest IC (requires ≥ 2 ranked factors).
        - ``positive_ic_factor_count``: int|None — count of factors with IC > 0.
        - ``top3_avg_ic``: float|None — mean IC of the top-3 ranked factors (requires ≥ 3).
        - ``factor_ic_spread``: float|None — top IC − bottom IC (requires ≥ 2 ranked factors).

        Returns all-None / empty dict when fewer than 10 rows have valid ``next_close_return``.
    """
    _null: dict = {
        "factor_ic_ranking": [],
        "top_factor": None,
        "bottom_factor": None,
        "positive_ic_factor_count": None,
        "top3_avg_ic": None,
        "factor_ic_spread": None,
    }

    def _spearman_local(x: list[float], y: list[float]) -> float:
        m = len(x)
        rank_x = sorted(range(m), key=lambda i: x[i])
        rank_y = sorted(range(m), key=lambda i: y[i])
        rx = [0] * m
        ry = [0] * m
        for rank, idx in enumerate(rank_x):
            rx[idx] = rank
        for rank, idx in enumerate(rank_y):
            ry[idx] = rank
        mean_rx = sum(rx) / m
        mean_ry = sum(ry) / m
        num = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(m))
        den = (
            sum((rx[i] - mean_rx) ** 2 for i in range(m))
            * sum((ry[i] - mean_ry) ** 2 for i in range(m))
        ) ** 0.5
        return num / max(den, 1e-8)

    ret_rows = [r for r in rows if r.get("next_close_return") is not None]
    if len(ret_rows) < 10:
        return _null

    returns: list[float] = [float(r["next_close_return"]) for r in ret_rows]

    factor_ic: dict[str, float | None] = {}
    for factor in _FACTORS_TO_RANK:
        paired: list[tuple[float, float]] = [
            (float(r.get(factor)), returns[i])
            for i, r in enumerate(ret_rows)
            if r.get(factor) is not None
        ]
        if len(paired) >= 5:
            xs = [p[0] for p in paired]
            ys = [p[1] for p in paired]
            ic = _spearman_local(xs, ys)
            factor_ic[factor] = round(max(-1.0, min(1.0, ic)), 6)
        else:
            factor_ic[factor] = None

    ranking: list[tuple[str, float]] = sorted(
        [(f, ic) for f, ic in factor_ic.items() if ic is not None],
        key=lambda x: x[1],
        reverse=True,
    )

    top_factor = ranking[0][0] if ranking else None
    bottom_factor = ranking[-1][0] if len(ranking) >= 2 else None
    positive_ic_count: int | None = sum(1 for _, ic in ranking if ic > 0) if ranking else 0
    top3_avg: float | None = sum(ic for _, ic in ranking[:3]) / 3.0 if len(ranking) >= 3 else None
    spread: float | None = ranking[0][1] - ranking[-1][1] if len(ranking) >= 2 else None

    return {
        "factor_ic_ranking": ranking,
        "top_factor": top_factor,
        "bottom_factor": bottom_factor,
        "positive_ic_factor_count": positive_ic_count,
        "top3_avg_ic": round(top3_avg, 6) if top3_avg is not None else None,
        "factor_ic_spread": round(spread, 6) if spread is not None else None,
    }


# ---------------------------------------------------------------------------
# Round 38, Task 3 (Gamma): Score bucket win rates — quintile monotonicity check
# ---------------------------------------------------------------------------
def compute_score_bucket_win_rates(rows: list[dict]) -> dict:
    """Validate composite score monotonicity via quintile-bucket win-rate analysis.

    Splits candidates into five equal-width score quintiles (Q1=lowest … Q5=highest)
    and computes the win rate in each bucket.  A well-calibrated scoring system should
    produce strictly increasing win rates Q1 < Q2 < Q3 < Q4 < Q5.

    Args:
        rows: Per-row dicts with ``next_close_return`` (float|None) and either
            ``runner_composite_score`` or ``composite_score`` (float|None).

    Returns:
        Dict with keys:

        - ``win_rate_q1`` … ``win_rate_q5``: float|None — per-quintile win rate (None if bucket < 3 rows).
        - ``score_monotone``: bool|None — True when Q1 < Q2 < Q3 < Q4 < Q5 strictly (all 5 valid).
        - ``score_near_monotone``: bool|None — True when ≥ 3 of 4 consecutive pairs increase.
        - ``top_quintile_premium``: float|None — win_rate_q5 − win_rate_q1 (both must be valid).
        - ``score_rank_ic``: float|None — Spearman IC of bucket index (1–5) vs win-rate (≥ 3 valid).
        - ``score_discriminates_well``: bool|None — True when top_quintile_premium > 0.10.

        Returns all-None dict when fewer than 15 valid paired rows are available.
    """
    _null: dict = {
        "win_rate_q1": None, "win_rate_q2": None, "win_rate_q3": None,
        "win_rate_q4": None, "win_rate_q5": None,
        "score_monotone": None,
        "score_near_monotone": None,
        "top_quintile_premium": None,
        "score_rank_ic": None,
        "score_discriminates_well": None,
    }

    valid: list[tuple[float, float]] = []
    for r in rows:
        ret = r.get("next_close_return")
        score = r.get("runner_composite_score")
        if score is None:
            score = r.get("composite_score")
        if ret is not None and score is not None:
            valid.append((float(score), float(ret)))

    if len(valid) < 15:
        return _null

    scores_only = sorted(v[0] for v in valid)
    n = len(scores_only)

    def _pct(lst: list[float], p: float) -> float:
        idx = p / 100.0 * (len(lst) - 1)
        lo = int(idx)
        hi = min(lo + 1, len(lst) - 1)
        return lst[lo] + (idx - lo) * (lst[hi] - lst[lo])

    p20 = _pct(scores_only, 20)
    p40 = _pct(scores_only, 40)
    p60 = _pct(scores_only, 60)
    p80 = _pct(scores_only, 80)

    buckets: list[list[float]] = [[], [], [], [], []]
    for score, ret in valid:
        if score <= p20:
            buckets[0].append(ret)
        elif score <= p40:
            buckets[1].append(ret)
        elif score <= p60:
            buckets[2].append(ret)
        elif score <= p80:
            buckets[3].append(ret)
        else:
            buckets[4].append(ret)

    win_rates: list[float | None] = []
    for b in buckets:
        if len(b) >= 3:
            win_rates.append(sum(1 for r in b if r > 0) / max(len(b), 1))
        else:
            win_rates.append(None)

    all_valid = all(wr is not None for wr in win_rates)
    score_monotone: bool | None = None
    score_near_monotone: bool | None = None
    if all_valid:
        wrs = [wr for wr in win_rates if wr is not None]
        score_monotone = all(wrs[i] < wrs[i + 1] for i in range(4))
        mono_count = sum(1 for i in range(4) if wrs[i] < wrs[i + 1])
        score_near_monotone = mono_count >= 3

    top_quintile_premium: float | None = None
    if win_rates[4] is not None and win_rates[0] is not None:
        top_quintile_premium = round(win_rates[4] - win_rates[0], 4)

    score_rank_ic: float | None = None
    valid_wrs = [(i + 1, wr) for i, wr in enumerate(win_rates) if wr is not None]
    if len(valid_wrs) >= 3:
        m = len(valid_wrs)
        bi = [float(idx) for idx, _ in valid_wrs]
        wr_vals = [wr for _, wr in valid_wrs]
        rank_bi = sorted(range(m), key=lambda i: bi[i])
        rank_wr = sorted(range(m), key=lambda i: wr_vals[i])
        rx = [0] * m
        ry = [0] * m
        for rank, idx in enumerate(rank_bi):
            rx[idx] = rank
        for rank, idx in enumerate(rank_wr):
            ry[idx] = rank
        mean_rx = sum(rx) / m
        mean_ry = sum(ry) / m
        num = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(m))
        den = (
            sum((rx[i] - mean_rx) ** 2 for i in range(m))
            * sum((ry[i] - mean_ry) ** 2 for i in range(m))
        ) ** 0.5
        score_rank_ic = round(max(-1.0, min(1.0, num / max(den, 1e-8))), 4)

    score_discriminates_well: bool | None = top_quintile_premium is not None and top_quintile_premium > 0.10

    return {
        "win_rate_q1": round(win_rates[0], 4) if win_rates[0] is not None else None,
        "win_rate_q2": round(win_rates[1], 4) if win_rates[1] is not None else None,
        "win_rate_q3": round(win_rates[2], 4) if win_rates[2] is not None else None,
        "win_rate_q4": round(win_rates[3], 4) if win_rates[3] is not None else None,
        "win_rate_q5": round(win_rates[4], 4) if win_rates[4] is not None else None,
        "score_monotone": score_monotone,
        "score_near_monotone": score_near_monotone,
        "top_quintile_premium": top_quintile_premium,
        "score_rank_ic": score_rank_ic,
        "score_discriminates_well": score_discriminates_well,
    }


# ---------------------------------------------------------------------------
# Round 39, Task 1 (Alpha): Recency vs history performance analysis
# ---------------------------------------------------------------------------
# Detects whether the strategy's recent performance has degraded relative to
# its historical baseline — the most important overfitting warning signal.
# Splits rows (assumed time-ordered) into historical (first 70 %) and
# recent (last 30 %) cohorts and compares win-rate and average return.


def compute_recency_vs_history_analysis(rows: list[dict]) -> dict:
    """Compare recent (last 30 %) vs historical (first 70 %) BTST performance.

    Args:
        rows: Time-ordered list of trade rows.  Each row must contain
              ``next_close_return`` (float | None).

    Returns:
        Dict with recency gap metrics and degradation flags.
    """
    _null: dict = {
        "historical_win_rate": None,
        "historical_avg_return": None,
        "historical_ev": None,
        "recent_win_rate": None,
        "recent_avg_return": None,
        "recent_ev": None,
        "recency_win_rate_gap": None,
        "recency_return_gap": None,
        "recency_degraded": None,
        "recency_improved": None,
        "recency_stable": None,
    }

    valid = [r for r in rows if r.get("next_close_return") is not None]
    n = len(valid)
    if n < 15:
        return _null

    split = int(n * 0.70)
    historical_rows = valid[:split]
    recent_rows = valid[split:]

    def _segment_stats(seg: list[dict]) -> tuple[float | None, float | None, float | None]:
        if len(seg) < 5:
            return None, None, None
        rets = [float(r.get("next_close_return", 0.0)) for r in seg]
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r <= 0]
        m = len(rets)
        win_rate = len(wins) / max(m, 1)
        avg_return = sum(rets) / max(m, 1)
        avg_win = sum(wins) / max(len(wins), 1) if wins else 0.0
        avg_loss = sum(losses) / max(len(losses), 1) if losses else 0.0
        ev = win_rate * avg_win + (1 - win_rate) * avg_loss
        return round(win_rate, 4), round(avg_return, 4), round(ev, 4)

    h_wr, h_ar, h_ev = _segment_stats(historical_rows)
    r_wr, r_ar, r_ev = _segment_stats(recent_rows)

    recency_win_rate_gap: float | None = None
    recency_return_gap: float | None = None
    recency_degraded: bool | None = None
    recency_improved: bool | None = None
    recency_stable: bool | None = None

    if h_wr is not None and r_wr is not None:
        recency_win_rate_gap = round(r_wr - h_wr, 4)
        recency_return_gap = round((r_ar or 0.0) - (h_ar or 0.0), 4)
        recency_degraded = recency_win_rate_gap < -0.05
        recency_improved = recency_win_rate_gap > 0.05
        recency_stable = abs(recency_win_rate_gap) <= 0.05

    return {
        "historical_win_rate": h_wr,
        "historical_avg_return": h_ar,
        "historical_ev": h_ev,
        "recent_win_rate": r_wr,
        "recent_avg_return": r_ar,
        "recent_ev": r_ev,
        "recency_win_rate_gap": recency_win_rate_gap,
        "recency_return_gap": recency_return_gap,
        "recency_degraded": recency_degraded,
        "recency_improved": recency_improved,
        "recency_stable": recency_stable,
    }


# ---------------------------------------------------------------------------
# Round 39, Task 2 (Beta): Optimal score threshold search
# ---------------------------------------------------------------------------
# Scans candidate entry thresholds (P30–P80) in score space and identifies
# the percentile cutoff that maximises win-rate lift over the overall baseline.


def compute_optimal_score_threshold(rows: list[dict]) -> dict:
    """Find the score percentile threshold that maximises win-rate lift.

    Args:
        rows: List of trade rows.  Each row must contain ``next_close_return``
              (float | None) and a score field (``runner_composite_score`` >
              ``composite_score`` > ``score``).

    Returns:
        Dict with optimal threshold metrics.
    """
    import numpy as np

    _null: dict = {
        "optimal_threshold_pct": None,
        "optimal_score_threshold": None,
        "optimal_above_win_rate": None,
        "optimal_threshold_lift": None,
        "above_threshold_count": None,
        "threshold_coverage": None,
    }

    score_field: str | None = None
    for candidate_field in ("runner_composite_score", "composite_score", "score"):
        if any(r.get(candidate_field) is not None for r in rows):
            score_field = candidate_field
            break

    if score_field is None:
        return _null

    valid = [r for r in rows if r.get("next_close_return") is not None and r.get(score_field) is not None]
    total_count = len(valid)
    if total_count < 20:
        return _null

    rets = [float(r.get("next_close_return", 0.0)) for r in valid]
    scores = [float(r.get(score_field, 0.0)) for r in valid]
    overall_win_rate = sum(1 for rv in rets if rv > 0) / max(total_count, 1)

    pct_labels = ["P30", "P40", "P50", "P60", "P70", "P80"]
    pct_values = [float(np.percentile(scores, p)) for p in (30, 40, 50, 60, 70, 80)]

    best_label: str | None = None
    best_thr: float | None = None
    best_above_wr: float | None = None
    best_lift: float | None = None
    best_above_count: int | None = None

    for label, thr in zip(pct_labels, pct_values):
        above = [rv for rv, sc in zip(rets, scores) if sc >= thr]
        below = [rv for rv, sc in zip(rets, scores) if sc < thr]
        if len(above) < 5 or len(below) < 5:
            continue
        above_wr = sum(1 for rv in above if rv > 0) / max(len(above), 1)
        lift = above_wr - overall_win_rate
        if best_lift is None or lift > best_lift:
            best_lift = lift
            best_label = label
            best_thr = thr
            best_above_wr = above_wr
            best_above_count = len(above)

    if best_lift is None:
        return _null

    return {
        "optimal_threshold_pct": best_label,
        "optimal_score_threshold": round(best_thr, 4) if best_thr is not None else None,
        "optimal_above_win_rate": round(best_above_wr, 4) if best_above_wr is not None else None,
        "optimal_threshold_lift": round(best_lift, 4),
        "above_threshold_count": best_above_count,
        "threshold_coverage": round(best_above_count / max(total_count, 1), 4) if best_above_count is not None else None,
    }


# ---------------------------------------------------------------------------
# Round 39, Task 3 (Gamma): Simulated equity curve analysis
# ---------------------------------------------------------------------------
# Simulates sequential equal-weight BTST trades and computes max drawdown,
# consecutive losses, recovery factor, and equity curve slope.


def compute_simulated_equity_curve(rows: list[dict]) -> dict:
    """Simulate a sequential BTST equity curve and compute drawdown / recovery metrics.

    Args:
        rows: Time-ordered list of trade rows.  Each row must contain
              ``next_close_return`` (float | None).

    Returns:
        Dict with equity curve metrics.
    """
    _null: dict = {
        "total_return": None,
        "max_drawdown": None,
        "max_consecutive_losses": None,
        "recovery_factor": None,
        "equity_curve_slope": None,
        "equity_rising": None,
        "equity_curve_grade": None,
    }

    valid_rets = [float(r.get("next_close_return", 0.0)) for r in rows if r.get("next_close_return") is not None]
    n = len(valid_rets)
    if n < 10:
        return _null

    equity: list[float] = [1.0]
    for rv in valid_rets:
        equity.append(equity[-1] * (1.0 + rv))

    total_return = round(equity[-1] - 1.0, 6)

    peak = equity[0]
    drawdowns: list[float] = []
    for eq in equity:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / max(peak, 1e-8)
        drawdowns.append(dd)
    max_drawdown = round(max(drawdowns), 6)

    max_consec = 0
    current_consec = 0
    for rv in valid_rets:
        if rv < 0:
            current_consec += 1
            max_consec = max(max_consec, current_consec)
        else:
            current_consec = 0
    max_consecutive_losses = max_consec

    raw_recovery = total_return / max(max_drawdown, 1e-6)
    recovery_factor = round(max(-10.0, min(10.0, raw_recovery)), 4)

    t_vals = list(range(len(equity)))
    m = len(t_vals)
    mean_t = sum(t_vals) / m
    mean_eq = sum(equity) / m
    num_slope = sum((t_vals[i] - mean_t) * (equity[i] - mean_eq) for i in range(m))
    den_slope = sum((t_vals[i] - mean_t) ** 2 for i in range(m))
    raw_slope = num_slope / max(den_slope, 1e-8)
    equity_curve_slope = round(raw_slope / max(equity[0], 1e-8), 6)

    equity_rising = equity_curve_slope > 0

    if recovery_factor > 2:
        grade = "A"
    elif recovery_factor > 1:
        grade = "B"
    elif recovery_factor > 0:
        grade = "C"
    else:
        grade = "D"

    return {
        "total_return": total_return,
        "max_drawdown": max_drawdown,
        "max_consecutive_losses": max_consecutive_losses,
        "recovery_factor": recovery_factor,
        "equity_curve_slope": equity_curve_slope,
        "equity_rising": equity_rising,
        "equity_curve_grade": grade,
    }


# ---------------------------------------------------------------------------
# Round 40, Task 1 (Alpha): Factor synergy matrix — pairwise factor co-activation lift
# ---------------------------------------------------------------------------
# For every C(7,2)=21 pair of the 7 core BTST factors, compute the win-rate lift when
# BOTH factors are simultaneously above their P67 threshold.  The pair with the highest
# lift is the «best_factor_pair».  Also counts pairs with lift > 5% as synergy pairs.
#
# Guardrail floor: max_synergy_lift ≥ 0.0 — at least one pair must show positive synergy.

_SYNERGY_FACTORS: list[str] = [
    "close_strength",
    "volume_expansion_quality",
    "sector_resonance",
    "rs_sector_rank",
    "t0_estimated_net_inflow_ratio",
    "breakout_quality_score",
    "momentum_slope_20d",
]


def compute_factor_synergy_matrix(rows: list[dict]) -> dict:
    """Compute pairwise factor co-activation win-rate lift for the 7 core BTST factors.

    For each C(7,2)=21 factor pair (f1, f2) the function identifies rows where both
    factors exceed their individual P67 threshold and measures the resulting win-rate
    lift over the global base win rate.

    Args:
        rows: Per-trade row dicts.  Each row must contain ``next_close_return``
            (float | None) and optionally the 7 core factor fields.

    Returns:
        Dict with keys:

        - ``best_factor_pair`` (tuple[str,str] | None): pair with the largest lift.
        - ``best_pair_lift`` (float | None): win-rate lift of the best pair, clamped [-0.3, 0.5].
        - ``best_pair_win_rate`` (float | None): absolute win rate for the best pair.
        - ``synergy_pair_count`` (int): number of pairs with lift > 0.05.
        - ``max_synergy_lift`` (float | None): alias of best_pair_lift (registered metric).
        - ``synergy_matrix_valid`` (bool): True when computation succeeded.
    """
    _null: dict = {
        "best_factor_pair": None,
        "best_pair_lift": None,
        "best_pair_win_rate": None,
        "synergy_pair_count": 0,
        "max_synergy_lift": None,
        "synergy_matrix_valid": False,
    }
    valid_rows = [r for r in rows if r.get("next_close_return") is not None]
    if len(valid_rows) < 15:
        return _null

    all_returns = [float(r["next_close_return"]) for r in valid_rows]
    base_win_rate = sum(1 for rv in all_returns if rv > 0) / max(len(all_returns), 1)

    # Precompute P67 thresholds for each factor.
    p67_map: dict[str, float | None] = {}
    for f in _SYNERGY_FACTORS:
        vals = sorted(float(r[f]) for r in valid_rows if r.get(f) is not None)
        if not vals:
            p67_map[f] = None
            continue
        idx = max(0, int(len(vals) * 0.67) - 1)
        p67_map[f] = vals[min(idx, len(vals) - 1)]

    best_pair: tuple[str, str] | None = None
    best_lift: float = float("-inf")
    best_win_rate: float | None = None
    synergy_pair_count = 0

    from itertools import combinations as _combinations
    for f1, f2 in _combinations(_SYNERGY_FACTORS, 2):
        p67_f1 = p67_map.get(f1)
        p67_f2 = p67_map.get(f2)
        if p67_f1 is None or p67_f2 is None:
            continue
        both_high = [
            r for r in valid_rows
            if r.get(f1) is not None and r.get(f2) is not None
            and float(r[f1]) >= p67_f1 and float(r[f2]) >= p67_f2
        ]
        if len(both_high) < 5:
            continue
        pair_win_rate = sum(1 for r in both_high if float(r["next_close_return"]) > 0) / max(len(both_high), 1)
        pair_lift = pair_win_rate - base_win_rate
        if pair_lift > best_lift:
            best_lift = pair_lift
            best_pair = (f1, f2)
            best_win_rate = pair_win_rate
        if pair_lift > 0.05:
            synergy_pair_count += 1

    if best_pair is None:
        return _null

    clamped_lift = round(max(-0.3, min(0.5, best_lift)), 6)
    return {
        "best_factor_pair": best_pair,
        "best_pair_lift": clamped_lift,
        "best_pair_win_rate": round(best_win_rate, 6) if best_win_rate is not None else None,
        "synergy_pair_count": synergy_pair_count,
        "max_synergy_lift": clamped_lift,
        "synergy_matrix_valid": True,
    }


# ---------------------------------------------------------------------------
# Round 40, Task 2 (Beta): Float turnover analysis — optimal换手率 bucket for BTST
# ---------------------------------------------------------------------------
# Splits rows into low/mid/high turnover thirds by P33/P67 and computes per-bucket
# win rate.  Identifies optimal bucket and whether turnover monotonically predicts
# win rate.  Registers high_vs_low_lift as a diagnostic COMPARISON_METRIC.


def compute_float_turnover_analysis(rows: list[dict]) -> dict:
    """Analyse ``float_turnover_rate`` vs BTST next-day win rate across three buckets.

    Splits all rows with valid (non-None) turnover and return data into low/mid/high
    thirds using P33 and P67 thresholds of ``float_turnover_rate``.

    Args:
        rows: Per-trade row dicts with ``next_close_return`` (float | None) and
            ``float_turnover_rate`` (float | None).

    Returns:
        Dict with keys:

        - ``turnover_analysis_valid`` (bool): True when computation succeeded.
        - ``turnover_low_win_rate`` / ``turnover_mid_win_rate`` / ``turnover_high_win_rate``
          (float | None): win rate per bucket; None when bucket has fewer than 3 rows.
        - ``optimal_turnover_bucket`` (str | None): 'low'/'mid'/'high' with highest win rate.
        - ``turnover_monotone_win_rate`` (bool | None): True when low < mid < high.
        - ``high_vs_low_lift`` (float | None): high_win_rate − low_win_rate (diagnostic metric).
        - ``p33_turnover`` / ``p67_turnover`` (float | None): bucket boundary thresholds.
    """
    _null: dict = {
        "turnover_analysis_valid": False,
        "turnover_low_win_rate": None,
        "turnover_mid_win_rate": None,
        "turnover_high_win_rate": None,
        "optimal_turnover_bucket": None,
        "turnover_monotone_win_rate": None,
        "high_vs_low_lift": None,
        "p33_turnover": None,
        "p67_turnover": None,
    }
    if not rows:
        return _null
    # Check if float_turnover_rate is entirely None.
    if all(r.get("float_turnover_rate") is None for r in rows):
        return _null

    valid = [
        r for r in rows
        if r.get("next_close_return") is not None and r.get("float_turnover_rate") is not None
    ]
    if len(valid) < 10:
        return _null

    turnover_sorted = sorted(float(r["float_turnover_rate"]) for r in valid)
    n = len(turnover_sorted)
    p33 = turnover_sorted[max(0, int(n * 0.33) - 1)]
    p67 = turnover_sorted[max(0, int(n * 0.67) - 1)]

    low_rows = [r for r in valid if float(r["float_turnover_rate"]) < p33]
    mid_rows = [r for r in valid if p33 <= float(r["float_turnover_rate"]) < p67]
    high_rows = [r for r in valid if float(r["float_turnover_rate"]) >= p67]

    def _bucket_wr(bucket: list[dict]) -> float | None:
        if len(bucket) < 3:
            return None
        return round(sum(1 for r in bucket if float(r["next_close_return"]) > 0) / max(len(bucket), 1), 6)

    low_wr = _bucket_wr(low_rows)
    mid_wr = _bucket_wr(mid_rows)
    high_wr = _bucket_wr(high_rows)

    bucket_wrs: dict[str, float] = {}
    if low_wr is not None:
        bucket_wrs["low"] = low_wr
    if mid_wr is not None:
        bucket_wrs["mid"] = mid_wr
    if high_wr is not None:
        bucket_wrs["high"] = high_wr

    optimal_bucket: str | None = max(bucket_wrs, key=lambda k: bucket_wrs[k]) if bucket_wrs else None

    monotone: bool | None = None
    if low_wr is not None and mid_wr is not None and high_wr is not None:
        monotone = bool(low_wr < mid_wr < high_wr)

    high_vs_low: float | None = None
    if high_wr is not None and low_wr is not None:
        high_vs_low = round(high_wr - low_wr, 6)

    return {
        "turnover_analysis_valid": True,
        "turnover_low_win_rate": low_wr,
        "turnover_mid_win_rate": mid_wr,
        "turnover_high_win_rate": high_wr,
        "optimal_turnover_bucket": optimal_bucket,
        "turnover_monotone_win_rate": monotone,
        "high_vs_low_lift": high_vs_low,
        "p33_turnover": round(p33, 6),
        "p67_turnover": round(p67, 6),
    }


# ---------------------------------------------------------------------------
# Round 41, Task 2 (Beta): Volume-price direction alignment
# ---------------------------------------------------------------------------
# Detects whether volume-expansion direction and price-movement direction are
# consistent (量价共振) — a key BTST confirmation signal.


def compute_volume_price_alignment(rows: list[dict]) -> dict:
    """Measure alignment between volume-expansion direction and next-day price direction.

    Evaluates two complementary scenarios:

    - **Scenario 1 (VEQ)**: splits rows by ``volume_expansion_quality`` median (P50).
      High-VEQ rows should have higher win rates than low-VEQ rows.
    - **Scenario 2 (ENIR)**: splits rows by ``t0_estimated_net_inflow_ratio`` >= 0
      (net inflow) vs < 0 (net outflow).  Inflow rows should show higher win rates.

    Args:
        rows: Per-trade row dicts with ``next_close_return`` (float | None),
            ``volume_expansion_quality`` (float | None), and
            ``t0_estimated_net_inflow_ratio`` (float | None).

    Returns:
        Dict with keys:

        - ``vol_price_signal_valid`` (bool): True when at least one scenario is computable.
        - ``vol_price_alignment_rate`` (float | None): fraction of rows where volume direction
          matches return direction (Scenario 1).
        - ``vol_price_alignment_strong`` (bool | None): True when alignment rate > 0.55.
        - ``aligned_win_rate`` (float | None): win rate of high-VEQ rows (Scenario 1, ≥5 rows).
        - ``misaligned_win_rate`` (float | None): win rate of low-VEQ rows (Scenario 1, ≥5 rows).
        - ``inflow_win_rate`` (float | None): win rate when net inflow ≥ 0 (Scenario 2).
        - ``outflow_win_rate`` (float | None): win rate when net inflow < 0 (Scenario 2).
        - ``inflow_vs_outflow_lift`` (float | None): inflow_win_rate − outflow_win_rate.
    """
    _null: dict = {
        "vol_price_signal_valid": False,
        "vol_price_alignment_rate": None,
        "vol_price_alignment_strong": None,
        "aligned_win_rate": None,
        "misaligned_win_rate": None,
        "inflow_win_rate": None,
        "outflow_win_rate": None,
        "inflow_vs_outflow_lift": None,
    }
    if not rows:
        return _null

    valid = [r for r in rows if r.get("next_close_return") is not None]
    if len(valid) < 10:
        return _null

    has_veq = any(r.get("volume_expansion_quality") is not None for r in valid)
    has_enir = any(r.get("t0_estimated_net_inflow_ratio") is not None for r in valid)

    if not has_veq and not has_enir:
        return _null

    result: dict = {
        "vol_price_signal_valid": True,
        "vol_price_alignment_rate": None,
        "vol_price_alignment_strong": None,
        "aligned_win_rate": None,
        "misaligned_win_rate": None,
        "inflow_win_rate": None,
        "outflow_win_rate": None,
        "inflow_vs_outflow_lift": None,
    }

    # ------------------------------------------------------------------
    # Scenario 1: volume_expansion_quality split by median
    # ------------------------------------------------------------------
    if has_veq:
        veq_valid = [r for r in valid if r.get("volume_expansion_quality") is not None]
        if len(veq_valid) >= 10:
            veq_vals = sorted(float(r["volume_expansion_quality"]) for r in veq_valid)
            mid_idx = len(veq_vals) // 2
            p50_veq = veq_vals[mid_idx]

            high_vq_rows = [r for r in veq_valid if float(r["volume_expansion_quality"]) >= p50_veq]
            low_vq_rows = [r for r in veq_valid if float(r["volume_expansion_quality"]) < p50_veq]

            # aligned: high VEQ AND return>0  OR  low VEQ AND return<0
            aligned_count = sum(
                1 for r in veq_valid
                if (float(r["volume_expansion_quality"]) >= p50_veq and float(r["next_close_return"]) > 0)
                or (float(r["volume_expansion_quality"]) < p50_veq and float(r["next_close_return"]) < 0)
            )
            alignment_rate = round(aligned_count / max(len(veq_valid), 1), 6)
            result["vol_price_alignment_rate"] = alignment_rate
            result["vol_price_alignment_strong"] = alignment_rate > 0.55

            if len(high_vq_rows) >= 5:
                result["aligned_win_rate"] = round(
                    sum(1 for r in high_vq_rows if float(r["next_close_return"]) > 0) / max(len(high_vq_rows), 1), 6
                )
            if len(low_vq_rows) >= 5:
                result["misaligned_win_rate"] = round(
                    sum(1 for r in low_vq_rows if float(r["next_close_return"]) > 0) / max(len(low_vq_rows), 1), 6
                )

    # ------------------------------------------------------------------
    # Scenario 2: t0_estimated_net_inflow_ratio >= 0 vs < 0
    # ------------------------------------------------------------------
    if has_enir:
        enir_valid = [r for r in valid if r.get("t0_estimated_net_inflow_ratio") is not None]
        if len(enir_valid) >= 10:
            inflow_rows = [r for r in enir_valid if float(r["t0_estimated_net_inflow_ratio"]) >= 0.0]
            outflow_rows = [r for r in enir_valid if float(r["t0_estimated_net_inflow_ratio"]) < 0.0]

            inflow_wr: float | None = None
            outflow_wr: float | None = None
            if len(inflow_rows) >= 5:
                inflow_wr = round(
                    sum(1 for r in inflow_rows if float(r["next_close_return"]) > 0) / max(len(inflow_rows), 1), 6
                )
            if len(outflow_rows) >= 5:
                outflow_wr = round(
                    sum(1 for r in outflow_rows if float(r["next_close_return"]) > 0) / max(len(outflow_rows), 1), 6
                )
            result["inflow_win_rate"] = inflow_wr
            result["outflow_win_rate"] = outflow_wr
            if inflow_wr is not None and outflow_wr is not None:
                result["inflow_vs_outflow_lift"] = round(inflow_wr - outflow_wr, 6)

    return result


# ---------------------------------------------------------------------------
# Round 41, Task 3 (Gamma): Statistical significance tests
# ---------------------------------------------------------------------------
# Uses classical statistics (binomial normal approximation + t-test) to verify
# whether the strategy's win rate is significantly above 50% and whether mean
# return is significantly above 0.


def compute_statistical_significance_tests(rows: list[dict]) -> dict:
    """Apply binomial and t-test statistical significance tests to BTST returns.

    Runs two independent hypothesis tests:

    1. **Binomial (win rate > 50 %)**: Normal approximation z-test.
       ``z_winrate = (p_hat − 0.5) / sqrt(0.25 / n)``; one-sided.
    2. **t-test (mean return > 0)**: Student-t with df → ∞.
       ``t_stat = mean_r / (std_r / sqrt(n))``; one-sided.

    Args:
        rows: Per-trade row dicts with ``next_close_return`` (float | None).

    Returns:
        Dict with keys:

        - ``win_rate_p_value`` (float | None): two-sided p-value from z-test.
        - ``z_win_rate`` (float | None): z-statistic for win-rate test.
        - ``t_stat_return`` (float | None): t-statistic for mean-return test.
        - ``win_rate_significant_90`` (bool | None): True when z > 1.282 (one-sided 90 %).
        - ``win_rate_significant_95`` (bool | None): True when z > 1.645 (one-sided 95 %).
        - ``return_significant_90`` (bool | None): True when t > 1.282.
        - ``return_significant_95`` (bool | None): True when t > 1.645.
        - ``combined_significance_score`` (float | None): mean of four significance flags (0–1).
        - ``strategy_statistically_valid`` (bool | None): True when both 90% tests pass.
    """
    import math

    _null: dict = {
        "win_rate_p_value": None,
        "z_win_rate": None,
        "t_stat_return": None,
        "win_rate_significant_90": None,
        "win_rate_significant_95": None,
        "return_significant_90": None,
        "return_significant_95": None,
        "combined_significance_score": None,
        "strategy_statistically_valid": None,
    }
    if not rows:
        return _null

    returns: list[float] = [float(r["next_close_return"]) for r in rows if r.get("next_close_return") is not None]
    if len(returns) < 10:
        return _null

    n = len(returns)
    k = sum(1 for r in returns if r > 0)
    p_hat = k / n

    # Binomial z-test (normal approximation)
    z_wr = (p_hat - 0.5) / max((0.25 / n) ** 0.5, 1e-8)
    # Two-sided p-value using normal CDF approximation via math.erf
    def _normal_cdf(z: float) -> float:
        return 0.5 * (1.0 + math.erf(z / (2.0 ** 0.5)))

    win_rate_p_value = round(2.0 * (1.0 - _normal_cdf(abs(z_wr))), 8)
    wr_sig90 = z_wr > 1.282
    wr_sig95 = z_wr > 1.645

    # One-sample t-test (mean > 0)
    mean_r = sum(returns) / n
    variance_r = sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1)
    std_r = variance_r ** 0.5
    t_stat = mean_r / max(std_r / max(n ** 0.5, 1e-8), 1e-8)
    ret_sig90 = t_stat > 1.282
    ret_sig95 = t_stat > 1.645

    combined_score = round(
        (int(wr_sig90) + int(wr_sig95) + int(ret_sig90) + int(ret_sig95)) / 4.0, 6
    )
    strategy_valid = wr_sig90 and ret_sig90

    return {
        "win_rate_p_value": win_rate_p_value,
        "z_win_rate": round(z_wr, 6),
        "t_stat_return": round(t_stat, 6),
        "win_rate_significant_90": wr_sig90,
        "win_rate_significant_95": wr_sig95,
        "return_significant_90": ret_sig90,
        "return_significant_95": ret_sig95,
        "combined_significance_score": combined_score,
        "strategy_statistically_valid": strategy_valid,
    }


# ---------------------------------------------------------------------------
# Round 42, Task 1 (Alpha): Score calibration curve
# ---------------------------------------------------------------------------
# Checks whether the composite scoring system is well-calibrated: do higher
# scores actually correspond to higher win rates?  Splits candidates into 5
# equal-frequency bins and fits a linear calibration model (OLS slope).


def compute_score_calibration_curve(rows: list[dict]) -> dict:
    """Assess scoring-system calibration: do high scores predict high win rates?

    Splits rows into 5 equal-frequency bins (by P20/P40/P60/P80 score quantiles)
    and checks whether per-bin win rate increases monotonically with score.

    Args:
        rows: Per-trade row dicts.  Required fields per row:

            - Score field (first found wins): ``runner_composite_score``,
              ``composite_score``, or ``score`` (float | None).
            - ``next_close_return`` (float | None).

    Returns:
        Dict with keys:

        - ``calibration_slope`` (float | None): OLS slope of bin_win_rate on
          bin_avg_score across valid bins.  Positive = correctly ordered.
        - ``calibration_mse`` (float | None): Mean-squared deviation of each
          bin win-rate from the overall win rate (distribution width proxy).
        - ``calibration_monotone`` (bool | None): True when bin win rates are
          non-decreasing across all consecutive valid bins.
        - ``well_calibrated`` (bool | None): True when slope > 0 *and* monotone.
        - ``calibration_bin_count`` (int | None): Number of bins with ≥ 3 rows.
        - ``calibration_valid`` (bool): True when ≥ 15 paired rows and ≥ 3 valid bins.
    """
    _null: dict = {
        "calibration_slope": None,
        "calibration_mse": None,
        "calibration_monotone": None,
        "well_calibrated": None,
        "calibration_bin_count": None,
        "calibration_valid": False,
    }
    if not rows:
        return _null

    # Resolve score field by priority
    def _get_score(row: dict) -> float | None:
        for key in ("runner_composite_score", "composite_score", "score"):
            val = row.get(key)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
        return None

    paired: list[tuple[float, float]] = []
    for row in rows:
        s = _get_score(row)
        r = row.get("next_close_return")
        if s is not None and r is not None:
            try:
                paired.append((float(s), float(r)))
            except (TypeError, ValueError):
                continue

    if len(paired) < 15:
        return _null

    paired.sort(key=lambda x: x[0])
    n = len(paired)
    # Compute P20/P40/P60/P80 boundaries by index
    boundaries: list[float] = []
    for pct in (0.20, 0.40, 0.60, 0.80):
        idx = int(pct * n)
        boundaries.append(paired[min(idx, n - 1)][0])

    # Assign bins
    def _bin_idx(score: float) -> int:
        for i, b in enumerate(boundaries):
            if score <= b:
                return i
        return 4

    bin_scores: list[list[float]] = [[] for _ in range(5)]
    bin_returns: list[list[float]] = [[] for _ in range(5)]
    for s, r in paired:
        b = _bin_idx(s)
        bin_scores[b].append(s)
        bin_returns[b].append(r)

    overall_wr = sum(1 for _, r in paired if r > 0) / max(len(paired), 1)

    calibration_points: list[tuple[float, float]] = []
    for i in range(5):
        if len(bin_returns[i]) >= 3:
            avg_s = sum(bin_scores[i]) / len(bin_scores[i])
            win_r = sum(1 for r in bin_returns[i] if r > 0) / len(bin_returns[i])
            calibration_points.append((avg_s, win_r))

    if len(calibration_points) < 3:
        return {**_null, "calibration_valid": False}

    xs = [p[0] for p in calibration_points]
    ys = [p[1] for p in calibration_points]
    m = len(xs)
    mean_x = sum(xs) / m
    mean_y = sum(ys) / m
    cov_xy = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(m)) / max(m, 1)
    var_x = sum((x - mean_x) ** 2 for x in xs) / max(m, 1)
    slope = cov_xy / max(var_x, 1e-8)

    mse = sum((y - overall_wr) ** 2 for y in ys) / max(m, 1)

    monotone = all(ys[i] <= ys[i + 1] for i in range(m - 1))
    well_cal = slope > 0 and monotone

    return {
        "calibration_slope": round(slope, 6),
        "calibration_mse": round(mse, 8),
        "calibration_monotone": monotone,
        "well_calibrated": well_cal,
        "calibration_bin_count": m,
        "calibration_valid": True,
    }


# ---------------------------------------------------------------------------
# Round 42, Task 2 (Beta): Close-strength quartile stratification
# ---------------------------------------------------------------------------
# Checks whether close_strength factor creates a monotone win-rate ladder
# across four quartiles.  Top-quartile premium > 5 % is the key signal.


def compute_close_strength_stratification(rows: list[dict]) -> dict:
    """Stratify BTST win rate and returns by close_strength quartile.

    Splits rows into four equal-frequency quartiles (Q1–Q4) by close_strength
    and computes per-quartile win rate, average return, and key spread metrics.

    Args:
        rows: Per-trade row dicts.  Required fields per row:

            - ``close_strength`` (float | None): close-strength factor value.
            - ``next_close_return`` (float | None): T+1 close return.

    Returns:
        Dict with keys:

        - ``close_strength_valid`` (bool): False when all close_strength are None
          or fewer than 10 rows are available.
        - ``cs_win_rate_q1/q2/q3/q4`` (float | None): Win rate per quartile.
        - ``cs_monotone`` (bool | None): True when Q1 < Q2 < Q3 < Q4 win rates.
        - ``cs_top_quartile_premium`` (float | None): Q4 win rate − Q1 win rate.
        - ``cs_top_quartile_avg_return`` (float | None): Mean T+1 return in Q4.
        - ``cs_bottom_quartile_avg_return`` (float | None): Mean T+1 return in Q1.
        - ``cs_return_spread`` (float | None): Top-quartile minus bottom-quartile avg return.
        - ``cs_effective`` (bool | None): True when premium > 0.05.
    """
    _null_full: dict = {
        "close_strength_valid": False,
        "cs_win_rate_q1": None,
        "cs_win_rate_q2": None,
        "cs_win_rate_q3": None,
        "cs_win_rate_q4": None,
        "cs_monotone": None,
        "cs_top_quartile_premium": None,
        "cs_top_quartile_avg_return": None,
        "cs_bottom_quartile_avg_return": None,
        "cs_return_spread": None,
        "cs_effective": None,
    }
    if not rows:
        return _null_full

    # Check if all close_strength are None
    has_cs = any(row.get("close_strength") is not None for row in rows)
    if not has_cs:
        return _null_full

    paired: list[tuple[float, float]] = []
    for row in rows:
        cs = row.get("close_strength")
        ret = row.get("next_close_return")
        if cs is not None and ret is not None:
            try:
                paired.append((float(cs), float(ret)))
            except (TypeError, ValueError):
                continue

    if len(paired) < 10:
        return _null_full

    paired.sort(key=lambda x: x[0])
    n = len(paired)
    # P25/P50/P75 boundaries
    b25 = paired[int(0.25 * n)][0]
    b50 = paired[int(0.50 * n)][0]
    b75 = paired[int(0.75 * n)][0]

    def _quartile(cs: float) -> int:
        if cs <= b25:
            return 0
        if cs <= b50:
            return 1
        if cs <= b75:
            return 2
        return 3

    q_returns: list[list[float]] = [[], [], [], []]
    for cs, ret in paired:
        q_returns[_quartile(cs)].append(ret)

    def _win_rate(rets: list[float]) -> float | None:
        if len(rets) < 3:
            return None
        return sum(1 for r in rets if r > 0) / len(rets)

    def _avg_ret(rets: list[float]) -> float | None:
        if not rets:
            return None
        return sum(rets) / len(rets)

    wr1 = _win_rate(q_returns[0])
    wr2 = _win_rate(q_returns[1])
    wr3 = _win_rate(q_returns[2])
    wr4 = _win_rate(q_returns[3])

    if wr1 is not None and wr2 is not None and wr3 is not None and wr4 is not None:
        monotone: bool | None = wr1 < wr2 < wr3 < wr4
    else:
        monotone = None

    premium: float | None = None
    if wr4 is not None and wr1 is not None:
        premium = round(wr4 - wr1, 6)

    top_avg = _avg_ret(q_returns[3])
    bot_avg = _avg_ret(q_returns[0])
    spread: float | None = None
    if top_avg is not None and bot_avg is not None:
        spread = round(top_avg - bot_avg, 6)

    cs_effective: bool | None = None
    if premium is not None:
        cs_effective = premium > 0.05

    return {
        "close_strength_valid": True,
        "cs_win_rate_q1": round(wr1, 6) if wr1 is not None else None,
        "cs_win_rate_q2": round(wr2, 6) if wr2 is not None else None,
        "cs_win_rate_q3": round(wr3, 6) if wr3 is not None else None,
        "cs_win_rate_q4": round(wr4, 6) if wr4 is not None else None,
        "cs_monotone": monotone,
        "cs_top_quartile_premium": premium,
        "cs_top_quartile_avg_return": round(top_avg, 6) if top_avg is not None else None,
        "cs_bottom_quartile_avg_return": round(bot_avg, 6) if bot_avg is not None else None,
        "cs_return_spread": spread,
        "cs_effective": cs_effective,
    }


# ---------------------------------------------------------------------------
# Round 43, Task 1 (Alpha): Profit Factor Analysis — 盈利因子PF
# ---------------------------------------------------------------------------
# Computes the profit factor (gross_profit / gross_loss) and related win/loss
# asymmetry metrics.  Profit factor > 1.0 means the strategy earns more than it
# loses in aggregate.  Complements kelly_fraction_half (Kelly edge) and
# realized_payoff_ratio (per-trade asymmetry) with a portfolio-level view.


def compute_profit_factor_analysis(rows: list[dict]) -> dict:
    """Compute profit factor and win/loss asymmetry metrics from per-trade rows.

    Args:
        rows: Per-trade row dicts.  Required field per row:

            - ``next_close_return`` (float | None): T+1 close return.

    Returns:
        Dict with keys:

        - ``profit_factor`` (float | None): gross_profit / gross_loss, clamped [0, 10].
        - ``gross_profit`` (float | None): sum of positive returns.
        - ``gross_loss`` (float | None): abs(sum of negative returns).
        - ``avg_win`` (float | None): mean return of winning trades.
        - ``avg_loss`` (float | None): abs(mean return) of losing trades.
        - ``win_loss_ratio`` (float | None): avg_win / avg_loss, clamped [0, 10].
        - ``profit_factor_grade`` (str | None): 'A'/'B'/'C'/'D'.
        - ``profitable`` (bool | None): profit_factor >= 1.0.
        - ``profit_factor_vs_kelly_consistent`` (bool | None): profit_factor > 1.0.
        - ``profit_factor_valid`` (bool): False when fewer than 10 valid rows.
    """
    _null: dict = {
        "profit_factor": None,
        "gross_profit": None,
        "gross_loss": None,
        "avg_win": None,
        "avg_loss": None,
        "win_loss_ratio": None,
        "profit_factor_grade": None,
        "profitable": None,
        "profit_factor_vs_kelly_consistent": None,
        "profit_factor_valid": False,
    }
    if not rows:
        return _null

    returns: list[float] = []
    for row in rows:
        val = row.get("next_close_return")
        if val is None:
            continue
        try:
            returns.append(float(val))
        except (TypeError, ValueError):
            continue

    if len(returns) < 10:
        return _null

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    raw_pf = gross_profit / max(gross_loss, 1e-8)
    profit_factor = round(min(max(raw_pf, 0.0), 10.0), 6)

    avg_win: float = round(sum(wins) / len(wins), 6) if wins else 0.0
    avg_loss_val: float = round(abs(sum(losses) / len(losses)), 6) if losses else 0.0

    raw_wlr = avg_win / max(avg_loss_val, 1e-8)
    win_loss_ratio = round(min(max(raw_wlr, 0.0), 10.0), 6)

    if profit_factor >= 2.0:
        grade = "A"
    elif profit_factor >= 1.5:
        grade = "B"
    elif profit_factor >= 1.0:
        grade = "C"
    else:
        grade = "D"

    return {
        "profit_factor": profit_factor,
        "gross_profit": round(gross_profit, 6),
        "gross_loss": round(gross_loss, 6),
        "avg_win": avg_win,
        "avg_loss": avg_loss_val,
        "win_loss_ratio": win_loss_ratio,
        "profit_factor_grade": grade,
        "profitable": profit_factor >= 1.0,
        "profit_factor_vs_kelly_consistent": profit_factor > 1.0,
        "profit_factor_valid": True,
    }


# ---------------------------------------------------------------------------
# Round 43, Task 2 (Beta): News Sentiment Stratification — 情绪评分分层
# ---------------------------------------------------------------------------
# Checks whether news_sentiment_score creates a monotone win-rate ladder from
# low-sentiment to high-sentiment candidates.  A lift > 5 pp confirms that the
# sentiment signal adds genuine edge for next-day selection.


def compute_news_sentiment_stratification(rows: list[dict]) -> dict:
    """Stratify BTST T+1 win rate by news_sentiment_score percentile tercile.

    Splits rows into three equal-frequency terciles (low / mid / high) by
    ``news_sentiment_score`` and computes per-tercile win rate plus key spread
    metrics.  Degrades gracefully when the field is absent.

    Args:
        rows: Per-trade row dicts.  Required fields per row:

            - ``next_close_return`` (float | None): T+1 close return.
            - ``news_sentiment_score`` (float | None): news sentiment score.

    Returns:
        Dict with keys:

        - ``sentiment_analysis_valid`` (bool): False when field is absent or < 10 paired rows.
        - ``sentiment_low_win_rate`` (float | None): win rate in bottom tercile.
        - ``sentiment_mid_win_rate`` (float | None): win rate in middle tercile.
        - ``sentiment_high_win_rate`` (float | None): win rate in top tercile.
        - ``sentiment_monotone`` (bool | None): low < mid < high win rates.
        - ``high_vs_low_sentiment_lift`` (float | None): high_win_rate − low_win_rate.
        - ``optimal_sentiment_bucket`` (str | None): 'low'/'mid'/'high'.
        - ``sentiment_effective`` (bool | None): lift > 0.05.
    """
    _null: dict = {
        "sentiment_analysis_valid": False,
        "sentiment_low_win_rate": None,
        "sentiment_mid_win_rate": None,
        "sentiment_high_win_rate": None,
        "sentiment_monotone": None,
        "high_vs_low_sentiment_lift": None,
        "optimal_sentiment_bucket": None,
        "sentiment_effective": None,
    }
    if not rows:
        return _null

    has_sentiment = any(row.get("news_sentiment_score") is not None for row in rows)
    if not has_sentiment:
        return _null

    paired: list[tuple[float, float]] = []
    for row in rows:
        score = row.get("news_sentiment_score")
        ret = row.get("next_close_return")
        if score is None or ret is None:
            continue
        try:
            paired.append((float(score), float(ret)))
        except (TypeError, ValueError):
            continue

    if len(paired) < 10:
        return _null

    paired.sort(key=lambda x: x[0])
    n = len(paired)
    p33_idx = int(n / 3)
    p67_idx = int(2 * n / 3)
    p33_val = paired[min(p33_idx, n - 1)][0]
    p67_val = paired[min(p67_idx, n - 1)][0]

    low_rets: list[float] = []
    mid_rets: list[float] = []
    high_rets: list[float] = []
    for score, ret in paired:
        if score <= p33_val:
            low_rets.append(ret)
        elif score <= p67_val:
            mid_rets.append(ret)
        else:
            high_rets.append(ret)

    def _wr(rets: list[float]) -> float | None:
        if len(rets) < 3:
            return None
        return round(sum(1 for r in rets if r > 0) / len(rets), 6)

    wr_low = _wr(low_rets)
    wr_mid = _wr(mid_rets)
    wr_high = _wr(high_rets)

    monotone: bool | None = None
    if wr_low is not None and wr_mid is not None and wr_high is not None:
        monotone = wr_low < wr_mid < wr_high

    lift: float | None = None
    if wr_high is not None and wr_low is not None:
        lift = round(wr_high - wr_low, 6)

    valid_buckets = {"low": wr_low, "mid": wr_mid, "high": wr_high}
    best_bucket: str | None = None
    best_wr: float | None = None
    for bname, bwr in valid_buckets.items():
        if bwr is not None:
            if best_wr is None or bwr > best_wr:
                best_wr = bwr
                best_bucket = bname

    effective: bool | None = None
    if lift is not None:
        effective = lift > 0.05

    return {
        "sentiment_analysis_valid": True,
        "sentiment_low_win_rate": wr_low,
        "sentiment_mid_win_rate": wr_mid,
        "sentiment_high_win_rate": wr_high,
        "sentiment_monotone": monotone,
        "high_vs_low_sentiment_lift": lift,
        "optimal_sentiment_bucket": best_bucket,
        "sentiment_effective": effective,
    }


# ---------------------------------------------------------------------------
# Round 44, Task 1 (Alpha): Relative-Strength Quartile Stratification
# ---------------------------------------------------------------------------


def compute_relative_strength_stratification(rows: list[dict]) -> dict:
    """Stratify BTST T+1 win rate by relative_strength_rank quartile (Q1/Q2/Q3/Q4).

    Splits rows into four quartiles using P25/P50/P75 of ``relative_strength_rank``
    and computes per-quartile win rate (``next_day_return > 0`` fraction).  Quartiles
    with fewer than 3 rows are treated as invalid (None win rate).

    Args:
        rows: List of per-candidate dicts.  Each dict may contain:
            - ``relative_strength_rank`` (float | None): relative-strength rank score.
            - ``next_day_return`` (float | None): T+1 return used for win/loss.

    Returns:
        Dict with keys:

        - ``rs_stratification_valid`` (bool): True when ≥ 2 quartiles have valid win rates.
        - ``rs_q1_win_rate`` (float | None): Q1 (lowest RS) win rate.
        - ``rs_q2_win_rate`` (float | None): Q2 win rate.
        - ``rs_q3_win_rate`` (float | None): Q3 win rate.
        - ``rs_q4_win_rate`` (float | None): Q4 (highest RS) win rate.
        - ``rs_top_quartile_win_rate`` (float | None): same as rs_q4_win_rate.
        - ``rs_bottom_quartile_win_rate`` (float | None): same as rs_q1_win_rate.
        - ``rs_top_quartile_premium`` (float | None): Q4 − Q1 win rate differential.
        - ``rs_monotone`` (bool | None): True when Q1 < Q2 < Q3 < Q4 win rates.
    """
    _null: dict = {
        "rs_stratification_valid": False,
        "rs_q1_win_rate": None,
        "rs_q2_win_rate": None,
        "rs_q3_win_rate": None,
        "rs_q4_win_rate": None,
        "rs_top_quartile_win_rate": None,
        "rs_bottom_quartile_win_rate": None,
        "rs_top_quartile_premium": None,
        "rs_monotone": None,
    }
    if not rows:
        return _null

    has_rs = any(row.get("relative_strength_rank") is not None for row in rows)
    if not has_rs:
        return _null

    paired: list[tuple[float, float]] = []
    for row in rows:
        rs = row.get("relative_strength_rank")
        ret = row.get("next_day_return")
        if rs is None or ret is None:
            continue
        try:
            paired.append((float(rs), float(ret)))
        except (TypeError, ValueError):
            continue

    if not paired:
        return _null

    paired.sort(key=lambda x: x[0])
    n = len(paired)

    def _percentile_val(p: float) -> float:
        idx = (p / 100.0) * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return paired[lo][0] * (1.0 - frac) + paired[hi][0] * frac

    p25 = _percentile_val(25)
    p50 = _percentile_val(50)
    p75 = _percentile_val(75)

    q1_rets: list[float] = []
    q2_rets: list[float] = []
    q3_rets: list[float] = []
    q4_rets: list[float] = []
    for rs_val, ret_val in paired:
        if rs_val <= p25:
            q1_rets.append(ret_val)
        elif rs_val <= p50:
            q2_rets.append(ret_val)
        elif rs_val <= p75:
            q3_rets.append(ret_val)
        else:
            q4_rets.append(ret_val)

    def _wr(rets: list[float]) -> float | None:
        if len(rets) < 3:
            return None
        return round(sum(1 for r in rets if r > 0) / len(rets), 6)

    wr_q1 = _wr(q1_rets)
    wr_q2 = _wr(q2_rets)
    wr_q3 = _wr(q3_rets)
    wr_q4 = _wr(q4_rets)

    valid_count = sum(1 for w in (wr_q1, wr_q2, wr_q3, wr_q4) if w is not None)
    stratification_valid = valid_count >= 2

    premium: float | None = None
    if wr_q4 is not None and wr_q1 is not None:
        premium = round(wr_q4 - wr_q1, 6)

    monotone: bool | None = None
    if wr_q1 is not None and wr_q2 is not None and wr_q3 is not None and wr_q4 is not None:
        monotone = wr_q1 < wr_q2 < wr_q3 < wr_q4

    return {
        "rs_stratification_valid": stratification_valid,
        "rs_q1_win_rate": wr_q1,
        "rs_q2_win_rate": wr_q2,
        "rs_q3_win_rate": wr_q3,
        "rs_q4_win_rate": wr_q4,
        "rs_top_quartile_win_rate": wr_q4,
        "rs_bottom_quartile_win_rate": wr_q1,
        "rs_top_quartile_premium": premium,
        "rs_monotone": monotone,
    }


# ---------------------------------------------------------------------------
# Round 44, Task 2 (Beta): Breakout-Quality Tercile Stratification
# ---------------------------------------------------------------------------


def compute_breakout_quality_stratification(rows: list[dict]) -> dict:
    """Stratify BTST T+1 win rate by breakout_quality_score tercile (low/mid/high).

    Splits rows into three terciles using P33/P67 of ``breakout_quality_score``
    and computes per-tercile win rate.  Terciles with fewer than 3 rows are
    treated as invalid (None win rate).

    Args:
        rows: List of per-candidate dicts.  Each dict may contain:
            - ``breakout_quality_score`` (float | None): breakout quality score.
            - ``next_day_return`` (float | None): T+1 return used for win/loss.

    Returns:
        Dict with keys:

        - ``bq_stratification_valid`` (bool): True when ≥ 2 terciles have valid win rates.
        - ``bq_low_win_rate`` (float | None): low tercile win rate.
        - ``bq_mid_win_rate`` (float | None): mid tercile win rate.
        - ``bq_high_win_rate`` (float | None): high tercile win rate.
        - ``bq_high_vs_low_lift`` (float | None): high − low win rate differential.
        - ``bq_monotone`` (bool | None): True when low < mid < high win rates.
        - ``bq_effective`` (bool | None): True when bq_high_vs_low_lift > 0.05.
    """
    _null: dict = {
        "bq_stratification_valid": False,
        "bq_low_win_rate": None,
        "bq_mid_win_rate": None,
        "bq_high_win_rate": None,
        "bq_high_vs_low_lift": None,
        "bq_monotone": None,
        "bq_effective": None,
    }
    if not rows:
        return _null

    has_bq = any(row.get("breakout_quality_score") is not None for row in rows)
    if not has_bq:
        return _null

    paired: list[tuple[float, float]] = []
    for row in rows:
        bq = row.get("breakout_quality_score")
        ret = row.get("next_day_return")
        if bq is None or ret is None:
            continue
        try:
            paired.append((float(bq), float(ret)))
        except (TypeError, ValueError):
            continue

    if not paired:
        return _null

    paired.sort(key=lambda x: x[0])
    n = len(paired)
    p33_idx = int(n / 3)
    p67_idx = int(2 * n / 3)
    p33_val = paired[min(p33_idx, n - 1)][0]
    p67_val = paired[min(p67_idx, n - 1)][0]

    low_rets: list[float] = []
    mid_rets: list[float] = []
    high_rets: list[float] = []
    for bq_val, ret_val in paired:
        if bq_val <= p33_val:
            low_rets.append(ret_val)
        elif bq_val <= p67_val:
            mid_rets.append(ret_val)
        else:
            high_rets.append(ret_val)

    def _wr(rets: list[float]) -> float | None:
        if len(rets) < 3:
            return None
        return round(sum(1 for r in rets if r > 0) / len(rets), 6)

    wr_low = _wr(low_rets)
    wr_mid = _wr(mid_rets)
    wr_high = _wr(high_rets)

    valid_count = sum(1 for w in (wr_low, wr_mid, wr_high) if w is not None)
    stratification_valid = valid_count >= 2

    lift: float | None = None
    if wr_high is not None and wr_low is not None:
        lift = round(wr_high - wr_low, 6)

    monotone: bool | None = None
    if wr_low is not None and wr_mid is not None and wr_high is not None:
        monotone = wr_low < wr_mid < wr_high

    effective: bool | None = None
    if lift is not None:
        effective = lift > 0.05

    return {
        "bq_stratification_valid": stratification_valid,
        "bq_low_win_rate": wr_low,
        "bq_mid_win_rate": wr_mid,
        "bq_high_win_rate": wr_high,
        "bq_high_vs_low_lift": lift,
        "bq_monotone": monotone,
        "bq_effective": effective,
    }


# ---------------------------------------------------------------------------
# Task 1 (Round 45, Alpha): Market-Cap Tercile Stratification
# ---------------------------------------------------------------------------
# Splits rows into three market-cap terciles (low/mid/high) based on P33/P67
# of market_cap_score and reports next-day win rate per tier.


def compute_market_cap_stratification(rows: list[dict]) -> dict:
    """Stratify next-day win rates across three market-cap terciles.

    Args:
        rows: Per-row dicts containing ``market_cap_score`` and ``next_day_return``.

    Returns:
        Dict with keys:

        - ``mc_stratification_valid`` (bool): True when ≥ 2 terciles have ≥ 3 rows.
        - ``mc_low_win_rate`` (float | None): Win rate for lowest market-cap tercile.
        - ``mc_mid_win_rate`` (float | None): Win rate for middle market-cap tercile.
        - ``mc_high_win_rate`` (float | None): Win rate for highest market-cap tercile.
        - ``mc_high_vs_low_lift`` (float | None): mc_high_win_rate − mc_low_win_rate.
        - ``mc_monotone`` (bool | None): True when low < mid < high win rates.
        - ``mc_effective`` (bool | None): True when mc_high_vs_low_lift > 0.05.
    """
    _null: dict = {
        "mc_stratification_valid": False,
        "mc_low_win_rate": None,
        "mc_mid_win_rate": None,
        "mc_high_win_rate": None,
        "mc_high_vs_low_lift": None,
        "mc_monotone": None,
        "mc_effective": None,
    }
    if not rows:
        return _null

    has_mc = any(row.get("market_cap_score") is not None for row in rows)
    if not has_mc:
        return _null

    paired: list[tuple[float, float]] = []
    for row in rows:
        mc = row.get("market_cap_score")
        ret = row.get("next_day_return")
        if mc is None or ret is None:
            continue
        try:
            paired.append((float(mc), float(ret)))
        except (TypeError, ValueError):
            continue

    if not paired:
        return _null

    paired.sort(key=lambda x: x[0])
    n = len(paired)
    p33_idx = int(n / 3)
    p67_idx = int(2 * n / 3)
    p33_val = paired[min(p33_idx, n - 1)][0]
    p67_val = paired[min(p67_idx, n - 1)][0]

    low_rets: list[float] = []
    mid_rets: list[float] = []
    high_rets: list[float] = []
    for mc_val, ret_val in paired:
        if mc_val <= p33_val:
            low_rets.append(ret_val)
        elif mc_val <= p67_val:
            mid_rets.append(ret_val)
        else:
            high_rets.append(ret_val)

    def _wr(rets: list[float]) -> float | None:
        if len(rets) < 3:
            return None
        return round(sum(1 for r in rets if r > 0) / len(rets), 6)

    wr_low = _wr(low_rets)
    wr_mid = _wr(mid_rets)
    wr_high = _wr(high_rets)

    valid_count = sum(1 for w in (wr_low, wr_mid, wr_high) if w is not None)
    stratification_valid = valid_count >= 2

    lift: float | None = None
    if wr_high is not None and wr_low is not None:
        lift = round(wr_high - wr_low, 6)

    monotone: bool | None = None
    if wr_low is not None and wr_mid is not None and wr_high is not None:
        monotone = wr_low < wr_mid < wr_high

    effective: bool | None = None
    if lift is not None:
        effective = lift > 0.05

    return {
        "mc_stratification_valid": stratification_valid,
        "mc_low_win_rate": wr_low,
        "mc_mid_win_rate": wr_mid,
        "mc_high_win_rate": wr_high,
        "mc_high_vs_low_lift": lift,
        "mc_monotone": monotone,
        "mc_effective": effective,
    }


# ---------------------------------------------------------------------------
# Task 2 (Round 45, Beta): Catalyst-Theme-Score Quartile Stratification
# ---------------------------------------------------------------------------
# Splits rows into four quartiles (Q1–Q4) based on P25/P50/P75 of
# catalyst_theme_score and reports next-day win rate per quartile.


def compute_catalyst_score_stratification(rows: list[dict]) -> dict:
    """Stratify next-day win rates across four catalyst-theme-score quartiles.

    Args:
        rows: Per-row dicts containing ``catalyst_theme_score`` and ``next_day_return``.

    Returns:
        Dict with keys:

        - ``catalyst_stratification_valid`` (bool): True when ≥ 2 quartiles have ≥ 3 rows.
        - ``catalyst_q1_win_rate`` (float | None): Win rate for Q1 (lowest).
        - ``catalyst_q2_win_rate`` (float | None): Win rate for Q2.
        - ``catalyst_q3_win_rate`` (float | None): Win rate for Q3.
        - ``catalyst_q4_win_rate`` (float | None): Win rate for Q4 (highest).
        - ``catalyst_top_quartile_premium`` (float | None): Q4 win rate − Q1 win rate.
        - ``catalyst_monotone`` (bool | None): True when Q1 < Q2 < Q3 < Q4.
    """
    _null: dict = {
        "catalyst_stratification_valid": False,
        "catalyst_q1_win_rate": None,
        "catalyst_q2_win_rate": None,
        "catalyst_q3_win_rate": None,
        "catalyst_q4_win_rate": None,
        "catalyst_top_quartile_premium": None,
        "catalyst_monotone": None,
    }
    if not rows:
        return _null

    has_cat = any(row.get("catalyst_theme_score") is not None for row in rows)
    if not has_cat:
        return _null

    paired: list[tuple[float, float]] = []
    for row in rows:
        cat = row.get("catalyst_theme_score")
        ret = row.get("next_day_return")
        if cat is None or ret is None:
            continue
        try:
            paired.append((float(cat), float(ret)))
        except (TypeError, ValueError):
            continue

    if not paired:
        return _null

    paired.sort(key=lambda x: x[0])
    n = len(paired)
    p25_idx = int(n / 4)
    p50_idx = int(n / 2)
    p75_idx = int(3 * n / 4)
    p25_val = paired[min(p25_idx, n - 1)][0]
    p50_val = paired[min(p50_idx, n - 1)][0]
    p75_val = paired[min(p75_idx, n - 1)][0]

    q1_rets: list[float] = []
    q2_rets: list[float] = []
    q3_rets: list[float] = []
    q4_rets: list[float] = []
    for cat_val, ret_val in paired:
        if cat_val <= p25_val:
            q1_rets.append(ret_val)
        elif cat_val <= p50_val:
            q2_rets.append(ret_val)
        elif cat_val <= p75_val:
            q3_rets.append(ret_val)
        else:
            q4_rets.append(ret_val)

    def _wr(rets: list[float]) -> float | None:
        if len(rets) < 3:
            return None
        return round(sum(1 for r in rets if r > 0) / len(rets), 6)

    wr_q1 = _wr(q1_rets)
    wr_q2 = _wr(q2_rets)
    wr_q3 = _wr(q3_rets)
    wr_q4 = _wr(q4_rets)

    valid_count = sum(1 for w in (wr_q1, wr_q2, wr_q3, wr_q4) if w is not None)
    stratification_valid = valid_count >= 2

    premium: float | None = None
    if wr_q4 is not None and wr_q1 is not None:
        premium = round(wr_q4 - wr_q1, 6)

    monotone: bool | None = None
    if wr_q1 is not None and wr_q2 is not None and wr_q3 is not None and wr_q4 is not None:
        monotone = wr_q1 < wr_q2 < wr_q3 < wr_q4

    return {
        "catalyst_stratification_valid": stratification_valid,
        "catalyst_q1_win_rate": wr_q1,
        "catalyst_q2_win_rate": wr_q2,
        "catalyst_q3_win_rate": wr_q3,
        "catalyst_q4_win_rate": wr_q4,
        "catalyst_top_quartile_premium": premium,
        "catalyst_monotone": monotone,
    }


# ---------------------------------------------------------------------------
# Task 1 (Round 46, Alpha): Volume-Price Divergence Three-Tier Stratification
# ---------------------------------------------------------------------------
# Splits rows into three tiers (low/mid/high) based on P33/P67 of
# volume_price_divergence and reports next-day win rate per tier.
# Low divergence = good volume-price alignment (bullish); high = bearish signal.


def compute_volume_price_divergence_stratification(rows: list[dict]) -> dict:
    """Stratify next-day win rates across three volume-price-divergence tiers.

    Args:
        rows: Per-row dicts containing ``volume_price_divergence`` and ``next_day_return``.

    Returns:
        Dict with keys:

        - ``vpd_stratification_valid`` (bool): True when ≥ 2 tiers have ≥ 3 rows.
        - ``vpd_low_win_rate`` (float | None): Win rate for low-divergence tier.
        - ``vpd_mid_win_rate`` (float | None): Win rate for mid-divergence tier.
        - ``vpd_high_win_rate`` (float | None): Win rate for high-divergence tier.
        - ``vpd_low_vs_high_lift`` (float | None): low win rate − high win rate.
        - ``vpd_anti_monotone`` (bool | None): True when low > mid > high (expected signal).
        - ``vpd_effective`` (bool): True when vpd_low_vs_high_lift > 0.05.
    """
    _null: dict = {
        "vpd_stratification_valid": False,
        "vpd_low_win_rate": None,
        "vpd_mid_win_rate": None,
        "vpd_high_win_rate": None,
        "vpd_low_vs_high_lift": None,
        "vpd_anti_monotone": None,
        "vpd_effective": False,
    }
    if not rows:
        return _null

    has_vpd = any(row.get("volume_price_divergence") is not None for row in rows)
    if not has_vpd:
        return _null

    paired: list[tuple[float, float]] = []
    for row in rows:
        vpd = row.get("volume_price_divergence")
        ret = row.get("next_day_return")
        if vpd is None or ret is None:
            continue
        try:
            paired.append((float(vpd), float(ret)))
        except (TypeError, ValueError):
            continue

    if not paired:
        return _null

    vpd_vals = sorted(v for v, _ in paired)
    n = len(vpd_vals)
    p33_idx = max(0, int(n * 1 / 3) - 1)
    p67_idx = max(0, int(n * 2 / 3) - 1)
    p33_val = vpd_vals[p33_idx]
    p67_val = vpd_vals[p67_idx]

    low_rets: list[float] = []
    mid_rets: list[float] = []
    high_rets: list[float] = []
    for vpd_val, ret_val in paired:
        if vpd_val <= p33_val:
            low_rets.append(ret_val)
        elif vpd_val <= p67_val:
            mid_rets.append(ret_val)
        else:
            high_rets.append(ret_val)

    def _wr(rets: list[float]) -> float | None:
        if len(rets) < 3:
            return None
        return round(sum(1 for r in rets if r > 0) / len(rets), 6)

    wr_low = _wr(low_rets)
    wr_mid = _wr(mid_rets)
    wr_high = _wr(high_rets)

    valid_count = sum(1 for w in (wr_low, wr_mid, wr_high) if w is not None)
    stratification_valid = valid_count >= 2

    lift: float | None = None
    if wr_low is not None and wr_high is not None:
        lift = round(wr_low - wr_high, 6)

    anti_monotone: bool | None = None
    if wr_low is not None and wr_mid is not None and wr_high is not None:
        anti_monotone = wr_low > wr_mid > wr_high

    effective = lift is not None and lift > 0.05

    return {
        "vpd_stratification_valid": stratification_valid,
        "vpd_low_win_rate": wr_low,
        "vpd_mid_win_rate": wr_mid,
        "vpd_high_win_rate": wr_high,
        "vpd_low_vs_high_lift": lift,
        "vpd_anti_monotone": anti_monotone,
        "vpd_effective": effective,
    }


# ---------------------------------------------------------------------------
# Task 2 (Round 46, Beta): Score Distribution Moments Analysis
# ---------------------------------------------------------------------------
# Extracts the composite score for all rows and computes distribution moments:
# mean, std, skewness (3rd moment), kurtosis (4th excess moment), percentiles,
# IQR, and positive-score fraction.  No scipy dependency — pure Python/numpy.


def compute_score_distribution_moments(rows: list[dict]) -> dict:
    """Compute distribution moments of the composite score across rows.

    Score priority: ``runner_composite_score`` > ``composite_score`` > ``score``.

    Args:
        rows: Per-row dicts containing at least one score field.

    Returns:
        Dict with keys:

        - ``score_mean`` (float | None)
        - ``score_std`` (float | None)
        - ``score_skewness`` (float | None): 3rd-moment skewness (no scipy).
        - ``score_kurtosis`` (float | None): Excess kurtosis (4th moment − 3).
        - ``score_positive_pct`` (float | None): Fraction with score > 0.
        - ``score_p10`` / ``score_p25`` / ``score_p50`` / ``score_p75`` / ``score_p90`` (float | None)
        - ``score_iqr`` (float | None): P75 − P25.
    """
    _null: dict = {
        "score_mean": None,
        "score_std": None,
        "score_skewness": None,
        "score_kurtosis": None,
        "score_positive_pct": None,
        "score_p10": None,
        "score_p25": None,
        "score_p50": None,
        "score_p75": None,
        "score_p90": None,
        "score_iqr": None,
    }
    if not rows:
        return _null

    scores: list[float] = []
    for row in rows:
        raw = row.get("runner_composite_score")
        if raw is None:
            raw = row.get("composite_score")
        if raw is None:
            raw = row.get("score")
        if raw is None:
            continue
        try:
            scores.append(float(raw))
        except (TypeError, ValueError):
            continue

    if len(scores) < 5:
        return _null

    n = len(scores)
    mu = sum(scores) / n
    var = sum((x - mu) ** 2 for x in scores) / (n - 1)
    std = var ** 0.5

    if std < 1e-12:
        skewness = 0.0
        kurtosis = 0.0
    else:
        skewness = (sum((x - mu) ** 3 for x in scores) / n) / (std ** 3)
        kurtosis = (sum((x - mu) ** 4 for x in scores) / n) / (std ** 4) - 3.0

    positive_pct = sum(1 for s in scores if s > 0) / n

    sorted_scores = sorted(scores)

    def _percentile(data: list[float], pct: float) -> float:
        idx = (len(data) - 1) * pct / 100.0
        lo = int(idx)
        hi = min(lo + 1, len(data) - 1)
        frac = idx - lo
        return data[lo] + frac * (data[hi] - data[lo])

    p10 = _percentile(sorted_scores, 10)
    p25 = _percentile(sorted_scores, 25)
    p50 = _percentile(sorted_scores, 50)
    p75 = _percentile(sorted_scores, 75)
    p90 = _percentile(sorted_scores, 90)

    return {
        "score_mean": round(mu, 6),
        "score_std": round(std, 6),
        "score_skewness": round(skewness, 6),
        "score_kurtosis": round(kurtosis, 6),
        "score_positive_pct": round(positive_pct, 6),
        "score_p10": round(p10, 6),
        "score_p25": round(p25, 6),
        "score_p50": round(p50, 6),
        "score_p75": round(p75, 6),
        "score_p90": round(p90, 6),
        "score_iqr": round(p75 - p25, 6),
    }


# ---------------------------------------------------------------------------
# Task 1 (Round 47, Alpha): Momentum Slope Stratification
# ---------------------------------------------------------------------------
# Stratifies rows by ``momentum_slope_20d`` (P33/P67) and computes per-tier
# win rates (next_day_return > 0).  Expects high momentum → higher win rate.


def compute_momentum_slope_stratification(rows: list[dict]) -> dict:
    """Stratify rows by momentum_slope_20d and compute tier win rates.

    Args:
        rows: List of row dicts.  Each row should contain ``momentum_slope_20d``
            and ``next_day_return`` fields.

    Returns:
        Dict containing:

        - ``ms_stratification_valid`` (bool): True when ≥ 2 tiers have valid win rates.
        - ``ms_low_win_rate`` (float | None): Win rate for low-momentum tier (≤ P33).
        - ``ms_mid_win_rate`` (float | None): Win rate for mid-momentum tier (P33–P67).
        - ``ms_high_win_rate`` (float | None): Win rate for high-momentum tier (> P67).
        - ``ms_high_vs_low_lift`` (float | None): ms_high_win_rate − ms_low_win_rate.
        - ``ms_monotone`` (bool | None): True when low < mid < high.
        - ``ms_effective`` (bool): True when ms_high_vs_low_lift > 0.05.
    """
    _null: dict = {
        "ms_stratification_valid": False,
        "ms_low_win_rate": None,
        "ms_mid_win_rate": None,
        "ms_high_win_rate": None,
        "ms_high_vs_low_lift": None,
        "ms_monotone": None,
        "ms_effective": False,
    }
    if not rows:
        return _null

    has_ms = any(row.get("momentum_slope_20d") is not None for row in rows)
    if not has_ms:
        return _null

    paired: list[tuple[float, float]] = []
    for row in rows:
        ms = row.get("momentum_slope_20d")
        ret = row.get("next_day_return")
        if ms is None or ret is None:
            continue
        try:
            paired.append((float(ms), float(ret)))
        except (TypeError, ValueError):
            continue

    if not paired:
        return _null

    ms_vals = sorted(v for v, _ in paired)
    n = len(ms_vals)
    p33_idx = max(0, int(n * 1 / 3) - 1)
    p67_idx = max(0, int(n * 2 / 3) - 1)
    p33_val = ms_vals[p33_idx]
    p67_val = ms_vals[p67_idx]

    low_rets: list[float] = []
    mid_rets: list[float] = []
    high_rets: list[float] = []
    for ms_val, ret_val in paired:
        if ms_val <= p33_val:
            low_rets.append(ret_val)
        elif ms_val <= p67_val:
            mid_rets.append(ret_val)
        else:
            high_rets.append(ret_val)

    def _wr(rets: list[float]) -> float | None:
        if len(rets) < 3:
            return None
        return round(sum(1 for r in rets if r > 0) / len(rets), 6)

    wr_low = _wr(low_rets)
    wr_mid = _wr(mid_rets)
    wr_high = _wr(high_rets)

    valid_count = sum(1 for w in (wr_low, wr_mid, wr_high) if w is not None)
    stratification_valid = valid_count >= 2

    lift: float | None = None
    if wr_high is not None and wr_low is not None:
        lift = round(wr_high - wr_low, 6)

    monotone: bool | None = None
    if wr_low is not None and wr_mid is not None and wr_high is not None:
        monotone = wr_low < wr_mid < wr_high

    effective = lift is not None and lift > 0.05

    return {
        "ms_stratification_valid": stratification_valid,
        "ms_low_win_rate": wr_low,
        "ms_mid_win_rate": wr_mid,
        "ms_high_win_rate": wr_high,
        "ms_high_vs_low_lift": lift,
        "ms_monotone": monotone,
        "ms_effective": effective,
    }


# ---------------------------------------------------------------------------
# Task 2 (Round 47, Beta): Inflow Ratio Stratification
# ---------------------------------------------------------------------------
# Stratifies rows by ``t0_estimated_net_inflow_ratio`` (P33/P67) and computes
# per-tier win rates.  Expects high inflow → higher win rate.


def compute_inflow_ratio_stratification(rows: list[dict]) -> dict:
    """Stratify rows by t0_estimated_net_inflow_ratio and compute tier win rates.

    Args:
        rows: List of row dicts.  Each row should contain
            ``t0_estimated_net_inflow_ratio`` and ``next_day_return`` fields.

    Returns:
        Dict containing:

        - ``inflow_stratification_valid`` (bool): True when ≥ 2 tiers have valid win rates.
        - ``inflow_low_win_rate`` (float | None): Win rate for low-inflow tier (≤ P33).
        - ``inflow_mid_win_rate`` (float | None): Win rate for mid-inflow tier (P33–P67).
        - ``inflow_high_win_rate`` (float | None): Win rate for high-inflow tier (> P67).
        - ``inflow_high_vs_low_lift`` (float | None): inflow_high_win_rate − inflow_low_win_rate.
        - ``inflow_monotone`` (bool | None): True when low < mid < high.
        - ``inflow_effective`` (bool): True when inflow_high_vs_low_lift > 0.05.
    """
    _null: dict = {
        "inflow_stratification_valid": False,
        "inflow_low_win_rate": None,
        "inflow_mid_win_rate": None,
        "inflow_high_win_rate": None,
        "inflow_high_vs_low_lift": None,
        "inflow_monotone": None,
        "inflow_effective": False,
    }
    if not rows:
        return _null

    has_inflow = any(row.get("t0_estimated_net_inflow_ratio") is not None for row in rows)
    if not has_inflow:
        return _null

    paired: list[tuple[float, float]] = []
    for row in rows:
        inflow = row.get("t0_estimated_net_inflow_ratio")
        ret = row.get("next_day_return")
        if inflow is None or ret is None:
            continue
        try:
            paired.append((float(inflow), float(ret)))
        except (TypeError, ValueError):
            continue

    if not paired:
        return _null

    inflow_vals = sorted(v for v, _ in paired)
    n = len(inflow_vals)
    p33_idx = max(0, int(n * 1 / 3) - 1)
    p67_idx = max(0, int(n * 2 / 3) - 1)
    p33_val = inflow_vals[p33_idx]
    p67_val = inflow_vals[p67_idx]

    low_rets: list[float] = []
    mid_rets: list[float] = []
    high_rets: list[float] = []
    for inflow_val, ret_val in paired:
        if inflow_val <= p33_val:
            low_rets.append(ret_val)
        elif inflow_val <= p67_val:
            mid_rets.append(ret_val)
        else:
            high_rets.append(ret_val)

    def _wr(rets: list[float]) -> float | None:
        if len(rets) < 3:
            return None
        return round(sum(1 for r in rets if r > 0) / len(rets), 6)

    wr_low = _wr(low_rets)
    wr_mid = _wr(mid_rets)
    wr_high = _wr(high_rets)

    valid_count = sum(1 for w in (wr_low, wr_mid, wr_high) if w is not None)
    stratification_valid = valid_count >= 2

    lift: float | None = None
    if wr_high is not None and wr_low is not None:
        lift = round(wr_high - wr_low, 6)

    monotone: bool | None = None
    if wr_low is not None and wr_mid is not None and wr_high is not None:
        monotone = wr_low < wr_mid < wr_high

    effective = lift is not None and lift > 0.05

    return {
        "inflow_stratification_valid": stratification_valid,
        "inflow_low_win_rate": wr_low,
        "inflow_mid_win_rate": wr_mid,
        "inflow_high_win_rate": wr_high,
        "inflow_high_vs_low_lift": lift,
        "inflow_monotone": monotone,
        "inflow_effective": effective,
    }


# ---------------------------------------------------------------------------
# Round 48, Task 1 (Alpha): VEQ (Volume Expansion Quality) Stratification
# ---------------------------------------------------------------------------
def compute_veq_stratification(rows: list[dict]) -> dict:
    """Stratify candidates by ``volume_expansion_quality`` (VEQ) and compute per-tier win rates.

    Args:
        rows: List of per-candidate dicts; each must have ``volume_expansion_quality`` and
            ``next_day_return``.

    Returns:
        Dict with keys: ``veq_stratification_valid``, ``veq_low_win_rate``,
        ``veq_mid_win_rate``, ``veq_high_win_rate``, ``veq_high_vs_low_lift``,
        ``veq_monotone``, ``veq_effective``.
    """
    _null: dict = {
        "veq_stratification_valid": False,
        "veq_low_win_rate": None,
        "veq_mid_win_rate": None,
        "veq_high_win_rate": None,
        "veq_high_vs_low_lift": None,
        "veq_monotone": None,
        "veq_effective": False,
    }
    if not rows:
        return _null

    has_veq = any(row.get("volume_expansion_quality") is not None for row in rows)
    if not has_veq:
        return _null

    paired: list[tuple[float, float]] = []
    for row in rows:
        veq = row.get("volume_expansion_quality")
        ret = row.get("next_day_return")
        if veq is None or ret is None:
            continue
        try:
            paired.append((float(veq), float(ret)))
        except (TypeError, ValueError):
            continue

    if not paired:
        return _null

    veq_vals = sorted(v for v, _ in paired)
    n = len(veq_vals)
    p33_idx = max(0, int(n * 1 / 3) - 1)
    p67_idx = max(0, int(n * 2 / 3) - 1)
    p33_val = veq_vals[p33_idx]
    p67_val = veq_vals[p67_idx]

    low_rets: list[float] = []
    mid_rets: list[float] = []
    high_rets: list[float] = []
    for veq_val, ret_val in paired:
        if veq_val <= p33_val:
            low_rets.append(ret_val)
        elif veq_val <= p67_val:
            mid_rets.append(ret_val)
        else:
            high_rets.append(ret_val)

    def _wr(rets: list[float]) -> "float | None":
        if len(rets) < 3:
            return None
        return round(sum(1 for r in rets if r > 0) / len(rets), 6)

    wr_low = _wr(low_rets)
    wr_mid = _wr(mid_rets)
    wr_high = _wr(high_rets)

    valid_count = sum(1 for w in (wr_low, wr_mid, wr_high) if w is not None)
    stratification_valid = valid_count >= 2

    lift: "float | None" = None
    if wr_high is not None and wr_low is not None:
        lift = round(wr_high - wr_low, 6)

    monotone: "bool | None" = None
    if wr_low is not None and wr_mid is not None and wr_high is not None:
        monotone = wr_low < wr_mid < wr_high

    effective = lift is not None and lift > 0.05

    return {
        "veq_stratification_valid": stratification_valid,
        "veq_low_win_rate": wr_low,
        "veq_mid_win_rate": wr_mid,
        "veq_high_win_rate": wr_high,
        "veq_high_vs_low_lift": lift,
        "veq_monotone": monotone,
        "veq_effective": effective,
    }


# ---------------------------------------------------------------------------
# Round 48, Task 2 (Beta): Sector Resonance Stratification
# ---------------------------------------------------------------------------
def compute_sector_resonance_stratification(rows: list[dict]) -> dict:
    """Stratify candidates by ``sector_resonance`` and compute per-tier win rates.

    Args:
        rows: List of per-candidate dicts; each must have ``sector_resonance`` and
            ``next_day_return``.

    Returns:
        Dict with keys: ``sr_stratification_valid``, ``sr_low_win_rate``,
        ``sr_mid_win_rate``, ``sr_high_win_rate``, ``sr_high_vs_low_lift``,
        ``sr_monotone``, ``sr_effective``.
    """
    _null: dict = {
        "sr_stratification_valid": False,
        "sr_low_win_rate": None,
        "sr_mid_win_rate": None,
        "sr_high_win_rate": None,
        "sr_high_vs_low_lift": None,
        "sr_monotone": None,
        "sr_effective": False,
    }
    if not rows:
        return _null

    has_sr = any(row.get("sector_resonance") is not None for row in rows)
    if not has_sr:
        return _null

    paired: list[tuple[float, float]] = []
    for row in rows:
        sr = row.get("sector_resonance")
        ret = row.get("next_day_return")
        if sr is None or ret is None:
            continue
        try:
            paired.append((float(sr), float(ret)))
        except (TypeError, ValueError):
            continue

    if not paired:
        return _null

    sr_vals = sorted(v for v, _ in paired)
    n = len(sr_vals)
    p33_idx = max(0, int(n * 1 / 3) - 1)
    p67_idx = max(0, int(n * 2 / 3) - 1)
    p33_val = sr_vals[p33_idx]
    p67_val = sr_vals[p67_idx]

    low_rets: list[float] = []
    mid_rets: list[float] = []
    high_rets: list[float] = []
    for sr_val, ret_val in paired:
        if sr_val <= p33_val:
            low_rets.append(ret_val)
        elif sr_val <= p67_val:
            mid_rets.append(ret_val)
        else:
            high_rets.append(ret_val)

    def _wr(rets: list[float]) -> "float | None":
        if len(rets) < 3:
            return None
        return round(sum(1 for r in rets if r > 0) / len(rets), 6)

    wr_low = _wr(low_rets)
    wr_mid = _wr(mid_rets)
    wr_high = _wr(high_rets)

    valid_count = sum(1 for w in (wr_low, wr_mid, wr_high) if w is not None)
    stratification_valid = valid_count >= 2

    lift: "float | None" = None
    if wr_high is not None and wr_low is not None:
        lift = round(wr_high - wr_low, 6)

    monotone: "bool | None" = None
    if wr_low is not None and wr_mid is not None and wr_high is not None:
        monotone = wr_low < wr_mid < wr_high

    effective = lift is not None and lift > 0.05

    return {
        "sr_stratification_valid": stratification_valid,
        "sr_low_win_rate": wr_low,
        "sr_mid_win_rate": wr_mid,
        "sr_high_win_rate": wr_high,
        "sr_high_vs_low_lift": lift,
        "sr_monotone": monotone,
        "sr_effective": effective,
    }
