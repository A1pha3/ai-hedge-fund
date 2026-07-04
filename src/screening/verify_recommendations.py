"""P3-1: 推荐闭环验证 — 自动回测推荐实际收益。

自动回放过去 N 天的每日推荐, 计算 T+1/T+3/T+5 实际收益,
与"推荐组合自身均值"参考点对比 (非市场指数), 并归因到策略/因子层面。

数据来源:
  - ``data/reports/auto_screening_*.json`` (每日推荐)
  - ``data/reports/tracking_history.json`` (P1-3 实际收益追踪)
  - 后备: 从 akshare/tushare 获取收盘价自行计算

CLI::

    uv run python src/main.py --verify-recommendations [--verify-lookback=30]

输出:
  - 总推荐次数 / 胜率 / 平均 T+1/T+3/T+5 收益
  - 与推荐组合自身均值对比 (参考基准, 非沪深 300 等市场指数)
  - 策略归因: 哪个策略贡献正/负收益
  - 日度明细 (可选 ``--verify-detail``)

NOTE (BETA-009): 本模块历史上宣称"与沪深 300 对比", 但代码从未拉取市场指数数据 —
``_compute_benchmark_returns`` 计算的是当日推荐组合的横截面均值, 作为同日参考点。
真正的沪深 300 基准需要实时指数数据, 超出本离线验证路径的范畴。所有面向用户的标签
均已校正为"推荐均值"。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.utils.numeric import optional_float as _optional_float

logger = logging.getLogger(__name__)


def _mean_or_none(values: list[float]) -> float | None:
    """Return the arithmetic mean of ``values``, or ``None`` when empty.

    Centralises the ``sum(x) / len(x) if x else None`` idiom repeated across
    the per-horizon / per-day / aggregate mean computations in this module so
    the empty-list contract is identical everywhere (DRY).
    """
    if not values:
        return None
    return sum(values) / len(values)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class VerifyDay:
    """单日推荐验证记录。

    Attributes:
        date: 推荐日期 YYYYMMDD
        tickers: 当日推荐标的列表
        top_score: 当日最高 score_b
        avg_t1_return: 当日推荐平均 T+1 收益率 (None=无数据)
        avg_t3_return: 当日推荐平均 T+3 收益率
        avg_t5_return: 当日推荐平均 T+5 收益率
        avg_t10_return: 当日推荐平均 T+10 收益率
        avg_t20_return: 当日推荐平均 T+20 收益率
        avg_t30_return: 当日推荐平均 T+30 收益率
        benchmark_return: 当日推荐组合平均 T+1 收益 (参考基准, 非市场指数; None=无数据)
        excess_return: 超额收益 (avg_t1 - benchmark)
    """

    date: str = ""
    tickers: list[str] = field(default_factory=list)
    top_score: float = 0.0
    avg_t1_return: float | None = None
    avg_t3_return: float | None = None
    avg_t5_return: float | None = None
    avg_t10_return: float | None = None
    avg_t20_return: float | None = None
    avg_t30_return: float | None = None
    benchmark_return: float | None = None
    excess_return: float | None = None


@dataclass
class StrategyAttribution:
    """策略级别归因。

    Attributes:
        strategy_name: 策略名 (trend / mean_reversion / fundamental / event_sentiment)
        recommendation_count: 该策略主导推荐的次数
        avg_t1_return: 平均 T+1 收益
        win_rate: 胜率 (T+1 收益 > 0 的比例)
    """

    strategy_name: str = ""
    recommendation_count: int = 0
    avg_t1_return: float | None = None
    win_rate: float | None = None


@dataclass
class VerifySummary:
    """推荐闭环验证汇总。

    Attributes:
        lookback_days: 回溯天数
        total_days: 有推荐数据的天数
        total_recommendations: 总推荐标的数 (含重复)
        unique_tickers: 不重复标的数
        overall_t1_win_rate: 整体 T+1 胜率
        overall_t3_win_rate: 整体 T+3 胜率
        overall_t5_win_rate: 整体 T+5 胜率
        overall_t10_win_rate: 整体 T+10 胜率
        overall_t15_win_rate: 整体 T+15 胜率 (multi-horizon diagnosis Task 3)
        overall_t20_win_rate: 整体 T+20 胜率
        overall_t25_win_rate: 整体 T+25 胜率 (multi-horizon diagnosis Task 3)
        overall_t30_win_rate: 整体 T+30 胜率
        avg_t1_return: 平均 T+1 收益率
        avg_t3_return: 平均 T+3 收益率
        avg_t5_return: 平均 T+5 收益率
        avg_t10_return: 平均 T+10 收益率
        avg_t15_return: 平均 T+15 收益率 (multi-horizon diagnosis Task 3)
        avg_t20_return: 平均 T+20 收益率
        avg_t25_return: 平均 T+25 收益率 (multi-horizon diagnosis Task 3)
        avg_t30_return: 平均 T+30 收益率
        benchmark_avg_t1: 推荐组合平均 T+1 收益 (参考基准, 非市场指数)
        excess_return: 超额收益 (avg_t1 - benchmark)
        strategy_attribution: 策略归因列表
        daily_details: 日度明细 (仅 --verify-detail 时填充)
    """

    lookback_days: int = 30
    total_days: int = 0
    total_recommendations: int = 0
    unique_tickers: int = 0
    overall_t1_win_rate: float | None = None
    overall_t3_win_rate: float | None = None
    overall_t5_win_rate: float | None = None
    overall_t10_win_rate: float | None = None
    overall_t15_win_rate: float | None = None
    overall_t20_win_rate: float | None = None
    overall_t25_win_rate: float | None = None
    overall_t30_win_rate: float | None = None
    avg_t1_return: float | None = None
    avg_t3_return: float | None = None
    avg_t5_return: float | None = None
    avg_t10_return: float | None = None
    avg_t15_return: float | None = None
    avg_t20_return: float | None = None
    avg_t25_return: float | None = None
    avg_t30_return: float | None = None
    benchmark_avg_t1: float | None = None
    excess_return: float | None = None
    strategy_attribution: list[StrategyAttribution] = field(default_factory=list)
    daily_details: list[VerifyDay] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def _load_tracking_history(reports_dir: Path) -> list[dict[str, Any]]:
    """Load tracking_history.json from reports_dir.

    Delegates to :func:`src.screening.consecutive_recommendation.load_tracking_history`.
    """
    from src.screening.consecutive_recommendation import load_tracking_history

    return load_tracking_history(reports_dir)


def _load_auto_screening_reports(reports_dir: Path, lookback_days: int) -> list[dict[str, Any]]:
    """Load auto_screening_*.json reports within lookback window.

    BH-018 / R36 same-class drain: the lookback cutoff is anchored to the
    LATEST report date in the directory, not wall-clock ``datetime.now()``.
    Anchoring to ``now()`` silently dropped any report older than
    ``now() - (lookback+10)`` — breaking backfilled / historical analysis
    (an all-old-data directory returned empty despite having in-window
    reports relative to its own latest date). Anchoring to the latest report
    date makes the window relative to the data, mirroring R36's ``as_of`` fix.
    """
    reports: list[dict[str, Any]] = []
    if not reports_dir.exists():
        return reports
    candidates: list[tuple[str, Path]] = []
    for path in sorted(reports_dir.glob("auto_screening_*.json"), reverse=True):
        date_str = path.stem.replace("auto_screening_", "")
        try:
            # Validate the date parses (skip malformed filenames) without
            # anchoring to now() — the cutoff is derived below from the latest
            # valid report date, R36-style.
            datetime.strptime(date_str, "%Y%m%d")
        except ValueError:
            continue
        candidates.append((date_str, path))
    if not candidates:
        return reports
    # Anchor the cutoff to the latest report date (newest, since sorted desc).
    latest_dt = datetime.strptime(candidates[0][0], "%Y%m%d")
    cutoff = latest_dt - timedelta(days=lookback_days + 10)
    for date_str, path in candidates:
        try:
            report_date = datetime.strptime(date_str, "%Y%m%d")
        except ValueError:
            continue
        if report_date < cutoff:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data["_report_date"] = date_str
            reports.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return reports[:lookback_days]


def _extract_tracking_returns(tracking: list[dict[str, Any]], ticker: str, rec_date: str) -> tuple[float | None, float | None, float | None, float | None, float | None, float | None, float | None, float | None]:
    """Extract T+1/T+3/T+5/T+10/T+15/T+20/T+25/T+30 returns for a ticker from tracking history.

    Returns an 8-tuple in chronological horizon order. Horizons absent from a
    given tracking entry degrade to ``None`` (the caller filters ``None`` and
    out-of-range values before accumulating).
    """
    for entry in tracking:
        if str(entry.get("ticker", "")) != ticker:
            continue
        if str(entry.get("recommended_date", "")) != rec_date:
            continue
        t1 = _optional_float(entry.get("next_day_return"))
        t3 = _optional_float(entry.get("next_3day_return"))
        t5 = _optional_float(entry.get("next_5day_return"))
        t10 = _optional_float(entry.get("next_10day_return"))
        t15 = _optional_float(entry.get("next_15day_return"))
        t20 = _optional_float(entry.get("next_20day_return"))
        t25 = _optional_float(entry.get("next_25day_return"))
        t30 = _optional_float(entry.get("next_30day_return"))
        return t1, t3, t5, t10, t15, t20, t25, t30
    return None, None, None, None, None, None, None, None


def _compute_benchmark_returns(
    tracking: list[dict[str, Any]],
    rec_date: str,
    basket_tickers: set[str] | None = None,
) -> float | None:
    """Compute the *recommended-basket* average T+1 return on a date.

    NOTE (BETA-009): this is the picks' own cross-section mean, used as a
    same-day reference point — it is **not** a real market benchmark such as
    CSI 300. User-facing labels must reflect that honestly (e.g. "推荐均值"),
    not claim a market index. A true 沪深300 benchmark requires live index
    data which is out of scope for this offline-verify path; the label was
    previously misleading.

    BH-004: when ``basket_tickers`` is provided, only tracking entries whose
    ticker is in the current report's basket are averaged. Previously every
    tracking entry with ``recommended_date == rec_date`` was averaged, so if
    the report's Top-N was trimmed/re-ranked relative to the tracked universe,
    the "benchmark" and the per-day basket mean were computed over different
    ticker sets on the same day — breaking the structural identity
    ``excess_return ≡ 0`` for a reason unrelated to edge (Top-N trimming noise,
    not alpha). Restricting to the same basket restores the identity.
    """
    t1_returns: list[float] = []
    for entry in tracking:
        if str(entry.get("recommended_date", "")) != rec_date:
            continue
        if basket_tickers is not None and str(entry.get("ticker", "")) not in basket_tickers:
            continue
        t1 = _optional_float(entry.get("next_day_return"))
        if t1 is not None and -50.0 <= t1 <= 50.0:
            t1_returns.append(t1)
    if not t1_returns:
        return None
    return sum(t1_returns) / len(t1_returns)


def compute_verify_recommendations(
    *,
    reports_dir: Path | str | None = None,
    lookback_days: int = 30,
    include_detail: bool = False,
) -> VerifySummary:
    """Main entry: compute recommendation verification summary.

    Args:
        reports_dir: Path to data/reports/. None → auto-resolve.
        lookback_days: How many days back to verify.
        include_detail: Include daily breakdown.

    Returns:
        VerifySummary with aggregated stats.
    """
    if reports_dir is None:
        reports_dir = Path("data/reports")
    else:
        reports_dir = Path(reports_dir)

    summary = VerifySummary(lookback_days=lookback_days)

    # Load data sources
    tracking = _load_tracking_history(reports_dir)
    reports = _load_auto_screening_reports(reports_dir, lookback_days)

    if not reports:
        return summary

    summary.total_days = len(reports)

    # Accumulate per-day stats
    all_t1: list[float] = []
    all_t3: list[float] = []
    all_t5: list[float] = []
    all_t10: list[float] = []
    all_t15: list[float] = []
    all_t20: list[float] = []
    all_t25: list[float] = []
    all_t30: list[float] = []
    all_tickers: set[str] = set()
    t1_wins = 0
    t3_wins = 0
    t5_wins = 0
    t10_wins = 0
    t15_wins = 0
    t20_wins = 0
    t25_wins = 0
    t30_wins = 0
    t1_total = 0
    t3_total = 0
    t5_total = 0
    t10_total = 0
    t15_total = 0
    t20_total = 0
    t25_total = 0
    t30_total = 0

    # Strategy attribution accumulators
    strat_returns: dict[str, list[float]] = {}

    # Per-day recommended-basket average T+1 (reference, not a market benchmark)
    benchmark_t1_values: list[float] = []
    # Per-day basket-mean T+1 (same weighting as benchmark_t1_values) so the
    # aggregate excess_return uses a CONSISTENT basis with benchmark_avg_t1.
    # NOTE (BETA-009-drain): the previous implementation subtracted summary.avg_t1_return
    # (a pick-weighted mean — every pick across all days pooled equally) from
    # summary.benchmark_avg_t1 (a day-weighted mean — mean of per-day basket means).
    # When pick counts vary per day, the two averages drift and the subtraction is
    # meaningless. We now accumulate the per-day basket mean in the same day-weighted
    # space as the benchmark, then subtract within that space.
    basket_avg_t1_values: list[float] = []

    for report in reports:
        rec_date = report.get("_report_date", "")
        recommendations = report.get("recommendations", [])
        if not recommendations:
            continue

        day_tickers: list[str] = []
        day_t1: list[float] = []
        day_t3: list[float] = []
        day_t5: list[float] = []
        day_t10: list[float] = []
        day_t15: list[float] = []
        day_t20: list[float] = []
        day_t25: list[float] = []
        day_t30: list[float] = []
        top_score = 0.0

        for rec in recommendations:
            if not isinstance(rec, dict):
                continue
            ticker = str(rec.get("ticker", ""))
            if not ticker:
                continue
            day_tickers.append(ticker)
            all_tickers.add(ticker)

            score = _optional_float(rec.get("score_b")) or 0.0
            if score > top_score:
                top_score = score

            # Get actual returns from tracking
            t1, t3, t5, t10, t15, t20, t25, t30 = _extract_tracking_returns(tracking, ticker, rec_date)

            if t1 is not None and -50.0 <= t1 <= 50.0:
                day_t1.append(t1)
                all_t1.append(t1)
                t1_total += 1
                if t1 > 0:
                    t1_wins += 1

            if t3 is not None and -50.0 <= t3 <= 50.0:
                day_t3.append(t3)
                all_t3.append(t3)
                t3_total += 1
                if t3 > 0:
                    t3_wins += 1

            if t5 is not None and -50.0 <= t5 <= 50.0:
                day_t5.append(t5)
                all_t5.append(t5)
                t5_total += 1
                if t5 > 0:
                    t5_wins += 1

            if t10 is not None and -50.0 <= t10 <= 50.0:
                day_t10.append(t10)
                all_t10.append(t10)
                t10_total += 1
                if t10 > 0:
                    t10_wins += 1

            if t15 is not None and -50.0 <= t15 <= 50.0:
                day_t15.append(t15)
                all_t15.append(t15)
                t15_total += 1
                if t15 > 0:
                    t15_wins += 1

            if t20 is not None and -50.0 <= t20 <= 50.0:
                day_t20.append(t20)
                all_t20.append(t20)
                t20_total += 1
                if t20 > 0:
                    t20_wins += 1

            if t25 is not None and -50.0 <= t25 <= 50.0:
                day_t25.append(t25)
                all_t25.append(t25)
                t25_total += 1
                if t25 > 0:
                    t25_wins += 1

            if t30 is not None and -50.0 <= t30 <= 50.0:
                day_t30.append(t30)
                all_t30.append(t30)
                t30_total += 1
                if t30 > 0:
                    t30_wins += 1

            # Strategy attribution: use dominant strategy direction
            signals = rec.get("strategy_signals", {})
            if isinstance(signals, dict):
                best_strat = ""
                best_conf = 0.0
                for strat_name, sig in signals.items():
                    if isinstance(sig, dict):
                        conf = _optional_float(sig.get("confidence")) or 0.0
                        if conf > best_conf:
                            best_conf = conf
                            best_strat = strat_name
                if best_strat and t1 is not None and -50.0 <= t1 <= 50.0:
                    strat_returns.setdefault(best_strat, []).append(t1)

        summary.total_recommendations += len(day_tickers)

        # Recommended-basket average T+1 (reference point, NOT a market index —
        # see _compute_benchmark_returns docstring / BETA-009).
        # BH-004: restrict the benchmark to the same basket as the per-day mean
        # so excess_return ≡ 0 holds structurally (no Top-N trimming noise).
        benchmark_t1 = _compute_benchmark_returns(tracking, rec_date, basket_tickers=set(day_tickers))
        avg_day_t1 = _mean_or_none(day_t1)
        if benchmark_t1 is not None:
            benchmark_t1_values.append(benchmark_t1)
        # Accumulate the per-day basket mean in the same day-weighted space as
        # benchmark_t1 so the aggregate excess_return is internally consistent
        # (BETA-009-drain: previously mixed pick-weighted vs day-weighted means).
        if avg_day_t1 is not None:
            basket_avg_t1_values.append(avg_day_t1)

        if include_detail:
            day_detail = VerifyDay(
                date=rec_date,
                tickers=day_tickers,
                top_score=top_score,
                avg_t1_return=avg_day_t1,
                avg_t3_return=_mean_or_none(day_t3),
                avg_t5_return=_mean_or_none(day_t5),
                avg_t10_return=_mean_or_none(day_t10),
                avg_t20_return=_mean_or_none(day_t20),
                avg_t30_return=_mean_or_none(day_t30),
                benchmark_return=benchmark_t1,
                excess_return=(avg_day_t1 - benchmark_t1) if avg_day_t1 is not None and benchmark_t1 is not None else None,
            )
            summary.daily_details.append(day_detail)

    # Aggregate
    summary.unique_tickers = len(all_tickers)
    summary.overall_t1_win_rate = t1_wins / t1_total if t1_total > 0 else None
    summary.overall_t3_win_rate = t3_wins / t3_total if t3_total > 0 else None
    summary.overall_t5_win_rate = t5_wins / t5_total if t5_total > 0 else None
    summary.overall_t10_win_rate = t10_wins / t10_total if t10_total > 0 else None
    summary.overall_t15_win_rate = t15_wins / t15_total if t15_total > 0 else None
    summary.overall_t20_win_rate = t20_wins / t20_total if t20_total > 0 else None
    summary.overall_t25_win_rate = t25_wins / t25_total if t25_total > 0 else None
    summary.overall_t30_win_rate = t30_wins / t30_total if t30_total > 0 else None
    summary.avg_t1_return = _mean_or_none(all_t1)
    summary.avg_t3_return = _mean_or_none(all_t3)
    summary.avg_t5_return = _mean_or_none(all_t5)
    summary.avg_t10_return = _mean_or_none(all_t10)
    summary.avg_t15_return = _mean_or_none(all_t15)
    summary.avg_t20_return = _mean_or_none(all_t20)
    summary.avg_t25_return = _mean_or_none(all_t25)
    summary.avg_t30_return = _mean_or_none(all_t30)

    # Recommended-basket reference (BETA-009): aggregate the per-day basket mean
    # and the excess of the picks' average over it, so the front-door
    # ``超额收益`` line renders real numbers instead of being dead code.
    summary.benchmark_avg_t1 = _mean_or_none(benchmark_t1_values)
    # BETA-009-drain: excess_return must subtract within the SAME weighting space.
    # Both basket_avg_t1_values and benchmark_t1_values are day-weighted (one entry
    # per day with a valid basket), so their means are directly comparable.
    # (Previously this used summary.avg_t1_return, a pick-weighted mean, which
    # is incomparable with the day-weighted benchmark and produced a misleading
    # excess_return whenever daily pick counts differed.)
    basket_avg = _mean_or_none(basket_avg_t1_values)
    benchmark_avg = summary.benchmark_avg_t1
    if basket_avg is not None and benchmark_avg is not None:
        summary.excess_return = basket_avg - benchmark_avg
    else:
        summary.excess_return = None

    # Strategy attribution
    for strat_name, returns in strat_returns.items():
        if not returns:
            continue
        wins = sum(1 for r in returns if r > 0)
        summary.strategy_attribution.append(
            StrategyAttribution(
                strategy_name=strat_name,
                recommendation_count=len(returns),
                avg_t1_return=sum(returns) / len(returns),
                win_rate=wins / len(returns),
            )
        )
    summary.strategy_attribution.sort(key=lambda s: s.avg_t1_return or 0.0, reverse=True)

    return summary


# ---------------------------------------------------------------------------
# CLI rendering
# ---------------------------------------------------------------------------


def render_verify_recommendations(summary: VerifySummary) -> str:
    """Render verification summary as ASCII table."""
    lines: list[str] = []

    lines.append("━" * 60)
    lines.append(f"  推荐闭环验证 · 近 {summary.lookback_days} 天")
    lines.append("━" * 60)
    lines.append("")

    lines.append(f"  有推荐天数: {summary.total_days}")
    lines.append(f"  总推荐次数: {summary.total_recommendations}")
    lines.append(f"  不重复标的: {summary.unique_tickers}")
    lines.append("")

    # Win rates
    def _pct(v: float | None) -> str:
        if v is None:
            return "—"
        return f"{v * 100:.1f}%"

    def _ret(v: float | None) -> str:
        if v is None:
            return "—"
        return f"{v:+.2f}%"

    # R51: T+5 was previously computed but never rendered (the module docstring
    # promises T+1/T+3/T+5). Add the T+5 rung so the full horizon ladder
    # (T+1/T+3/T+5 in the main table + T+10/T+20/T+30 in the extended table)
    # is visible and the T+5 computation is not wasted.
    lines.append("  ┌──────────┬──────────┬──────────┬──────────┐")
    lines.append("  │  指标     │  T+1     │  T+3     │  T+5     │")
    lines.append("  ├──────────┼──────────┼──────────┼──────────┤")
    lines.append(f"  │  胜率     │ {_pct(summary.overall_t1_win_rate):>6}  │ {_pct(summary.overall_t3_win_rate):>6}  │ {_pct(summary.overall_t5_win_rate):>6}  │")
    lines.append(f"  │  平均收益 │ {_ret(summary.avg_t1_return):>7} │ {_ret(summary.avg_t3_return):>7} │ {_ret(summary.avg_t5_return):>7} │")
    lines.append("  └──────────┴──────────┴──────────┴──────────┘")
    lines.append("")

    # Strategy attribution
    if summary.strategy_attribution:
        lines.append("  策略归因:")
        lines.append(f"  {'策略':<20} {'次数':>4} {'T+1收益':>8} {'胜率':>6}")
        lines.append("  " + "-" * 42)
        for s in summary.strategy_attribution:
            lines.append(f"  {s.strategy_name:<20} {s.recommendation_count:>4} {_ret(s.avg_t1_return):>8} {_pct(s.win_rate):>6}")
        lines.append("")

    # Extended horizons display
    if any([summary.avg_t10_return is not None, summary.avg_t20_return is not None, summary.avg_t30_return is not None]):
        lines.append("  扩展周期 (T+10/T+20/T+30):")
        lines.append("  ┌──────────┬──────────┬──────────┬──────────┐")
        lines.append("  │  指标     │  T+10    │  T+20    │  T+30    │")
        lines.append("  ├──────────┼──────────┼──────────┼──────────┤")
        lines.append(f"  │  胜率     │ {_pct(summary.overall_t10_win_rate):>6}  │ {_pct(summary.overall_t20_win_rate):>6}  │ {_pct(summary.overall_t30_win_rate):>6}  │")
        lines.append(f"  │  平均收益 │ {_ret(summary.avg_t10_return):>7} │ {_ret(summary.avg_t20_return):>7} │ {_ret(summary.avg_t30_return):>7} │")
        lines.append("  └──────────┴──────────┴──────────┴──────────┘")
        lines.append("")

    if summary.total_days == 0:
        lines.append("  ⚠ 无推荐数据 — 请先运行 --auto 生成报告")

    # BH-020: ``--verify-detail`` populates ``summary.daily_details`` (VerifyDay
    # records), but this render function never surfaced them — the entire flag
    # was a silent no-op at the presentation layer despite every VerifyDay
    # field (date / tickers / avg_tN_return / benchmark_return / excess_return)
    # being computed. Render a per-day detail table so the flag delivers on its
    # promise. Skipped when daily_details is empty (default --verify without
    # --verify-detail, or empty data) so no misleading empty section is shown.
    if summary.daily_details:
        lines.append("  日度明细 (--verify-detail):")
        lines.append(f"  {'日期':<10} {'标的数':>5} {'T+1均收':>8} {'基准T+1':>8} {'超额':>7} {'最高分':>7}")
        lines.append("  " + "-" * 52)
        for d in summary.daily_details:
            lines.append(f"  {d.date:<10} {len(d.tickers):>5} " f"{_ret(d.avg_t1_return):>8} {_ret(d.benchmark_return):>8} " f"{_ret(d.excess_return):>7} {d.top_score:>7.2f}")
        lines.append("")

    lines.append("━" * 60)
    return "\n".join(lines)
