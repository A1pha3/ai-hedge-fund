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
    """
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
    """Compute single-bar T0 metrics for R16 Tasks 1, 2, and 3.

    All inputs are expected to be positive floats representing a single daily OHLCV bar on the
    trade day.  Returns a dict with the following keys:

    - ``t0_estimated_net_inflow_ratio`` (float): buying pressure in [-1, +1]; +1 = pure buying.
    - ``volume_price_divergence_score`` (float): bar-structure distribution risk in [0, 1]; 0 = no risk.
    - ``volume_price_divergence_flag`` (bool): True when bar is a confirmed false-breakout pattern.
    - ``t0_predicted_range_pct`` (float): T0 bar range as fraction of open (e.g. 0.05 = 5 % range).
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

    return {
        "t0_estimated_net_inflow_ratio": t0_estimated_net_inflow_ratio,
        "volume_price_divergence_score": volume_price_divergence_score,
        "volume_price_divergence_flag": volume_price_divergence_flag,
        "t0_predicted_range_pct": t0_predicted_range_pct,
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

    return {
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
