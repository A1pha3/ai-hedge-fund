"""P3-1: 推荐闭环验证 — 自动回测推荐实际收益。

自动回放过去 N 天的每日推荐, 计算 T+1/T+3/T+5 实际收益,
与基准 (沪深 300) 对比, 并归因到策略/因子层面。

数据来源:
  - ``data/reports/auto_screening_*.json`` (每日推荐)
  - ``data/reports/tracking_history.json`` (P1-3 实际收益追踪)
  - 后备: 从 akshare/tushare 获取收盘价自行计算

CLI::

    uv run python src/main.py --verify-recommendations [--verify-lookback=30]

输出:
  - 总推荐次数 / 胜率 / 平均 T+1/T+3/T+5 收益
  - 与沪深 300 同期对比
  - 策略归因: 哪个策略贡献正/负收益
  - 日度明细 (可选 ``--verify-detail``)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils.numeric import optional_float as _optional_float

logger = logging.getLogger(__name__)


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
        benchmark_return: 沪深 300 同期 T+1 收益 (None=无数据)
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
        overall_t20_win_rate: 整体 T+20 胜率
        overall_t30_win_rate: 整体 T+30 胜率
        avg_t1_return: 平均 T+1 收益率
        avg_t3_return: 平均 T+3 收益率
        avg_t5_return: 平均 T+5 收益率
        avg_t10_return: 平均 T+10 收益率
        avg_t20_return: 平均 T+20 收益率
        avg_t30_return: 平均 T+30 收益率
        benchmark_avg_t1: 沪深 300 同期平均 T+1 收益
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
    overall_t20_win_rate: float | None = None
    overall_t30_win_rate: float | None = None
    avg_t1_return: float | None = None
    avg_t3_return: float | None = None
    avg_t5_return: float | None = None
    avg_t10_return: float | None = None
    avg_t20_return: float | None = None
    avg_t30_return: float | None = None
    benchmark_avg_t1: float | None = None
    excess_return: float | None = None
    strategy_attribution: list[StrategyAttribution] = field(default_factory=list)
    daily_details: list[VerifyDay] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def _load_tracking_history(reports_dir: Path) -> list[dict[str, Any]]:
    """Load tracking_history.json from reports_dir."""
    path = reports_dir / "tracking_history.json"
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        records = data.get("records") if isinstance(data, dict) else data
        if isinstance(records, list):
            return records
        return []
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("verify: tracking_history load failed: %s", exc)
        return []


def _load_auto_screening_reports(reports_dir: Path, lookback_days: int) -> list[dict[str, Any]]:
    """Load auto_screening_*.json reports within lookback window."""
    reports: list[dict[str, Any]] = []
    if not reports_dir.exists():
        return reports
    for path in sorted(reports_dir.glob("auto_screening_*.json"), reverse=True):
        date_str = path.stem.replace("auto_screening_", "")
        try:
            cutoff = datetime.now() - __import__("datetime").timedelta(days=lookback_days + 10)
            report_date = datetime.strptime(date_str, "%Y%m%d")
            if report_date < cutoff:
                continue
        except ValueError:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data["_report_date"] = date_str
            reports.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return reports[:lookback_days]


def _extract_tracking_returns(tracking: list[dict[str, Any]], ticker: str, rec_date: str) -> tuple[float | None, float | None, float | None, float | None, float | None, float | None]:
    """Extract T+1/T+3/T+5/T+10/T+20/T+30 returns for a ticker from tracking history."""
    for entry in tracking:
        if str(entry.get("ticker", "")) != ticker:
            continue
        if str(entry.get("recommended_date", "")) != rec_date:
            continue
        t1 = _optional_float(entry.get("next_day_return"))
        t3 = _optional_float(entry.get("next_3day_return"))
        t5 = _optional_float(entry.get("next_5day_return"))
        t10 = _optional_float(entry.get("next_10day_return"))
        t20 = _optional_float(entry.get("next_20day_return"))
        t30 = _optional_float(entry.get("next_30day_return"))
        return t1, t3, t5, t10, t20, t30
    return None, None, None, None, None, None


def _compute_benchmark_returns(tracking: list[dict[str, Any]], rec_date: str) -> float | None:
    """Compute average T+1 return across all tickers on a date as benchmark proxy."""
    t1_returns: list[float] = []
    for entry in tracking:
        if str(entry.get("recommended_date", "")) != rec_date:
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
    all_t20: list[float] = []
    all_t30: list[float] = []
    all_tickers: set[str] = set()
    t1_wins = 0
    t3_wins = 0
    t5_wins = 0
    t10_wins = 0
    t20_wins = 0
    t30_wins = 0
    t1_total = 0
    t3_total = 0
    t5_total = 0
    t10_total = 0
    t20_total = 0
    t30_total = 0

    # Strategy attribution accumulators
    strat_returns: dict[str, list[float]] = {}

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
        day_t20: list[float] = []
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
            t1, t3, t5, t10, t20, t30 = _extract_tracking_returns(tracking, ticker, rec_date)

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

            if t20 is not None and -50.0 <= t20 <= 50.0:
                day_t20.append(t20)
                all_t20.append(t20)
                t20_total += 1
                if t20 > 0:
                    t20_wins += 1

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

        # Benchmark (cross-section average)
        benchmark_t1 = _compute_benchmark_returns(tracking, rec_date)
        avg_day_t1 = sum(day_t1) / len(day_t1) if day_t1 else None

        if include_detail:
            day_detail = VerifyDay(
                date=rec_date,
                tickers=day_tickers,
                top_score=top_score,
                avg_t1_return=avg_day_t1,
                avg_t3_return=sum(day_t3) / len(day_t3) if day_t3 else None,
                avg_t5_return=sum(day_t5) / len(day_t5) if day_t5 else None,
                avg_t10_return=sum(day_t10) / len(day_t10) if day_t10 else None,
                avg_t20_return=sum(day_t20) / len(day_t20) if day_t20 else None,
                avg_t30_return=sum(day_t30) / len(day_t30) if day_t30 else None,
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
    summary.overall_t20_win_rate = t20_wins / t20_total if t20_total > 0 else None
    summary.overall_t30_win_rate = t30_wins / t30_total if t30_total > 0 else None
    summary.avg_t1_return = sum(all_t1) / len(all_t1) if all_t1 else None
    summary.avg_t3_return = sum(all_t3) / len(all_t3) if all_t3 else None
    summary.avg_t5_return = sum(all_t5) / len(all_t5) if all_t5 else None
    summary.avg_t10_return = sum(all_t10) / len(all_t10) if all_t10 else None
    summary.avg_t20_return = sum(all_t20) / len(all_t20) if all_t20 else None
    summary.avg_t30_return = sum(all_t30) / len(all_t30) if all_t30 else None

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

    lines.append("  ┌──────────┬──────────┬──────────┐")
    lines.append("  │  指标     │  T+1     │  T+3     │")
    lines.append("  ├──────────┼──────────┼──────────┤")
    lines.append(f"  │  胜率     │ {_pct(summary.overall_t1_win_rate):>6}  │ {_pct(summary.overall_t3_win_rate):>6}  │")
    lines.append(f"  │  平均收益 │ {_ret(summary.avg_t1_return):>7} │ {_ret(summary.avg_t3_return):>7} │")
    lines.append("  └──────────┴──────────┴──────────┘")
    lines.append("")

    # Strategy attribution
    if summary.strategy_attribution:
        lines.append("  策略归因:")
        lines.append(f"  {'策略':<20} {'次数':>4} {'T+1收益':>8} {'胜率':>6}")
        lines.append("  " + "-" * 42)
        for s in summary.strategy_attribution:
            lines.append(
                f"  {s.strategy_name:<20} {s.recommendation_count:>4} {_ret(s.avg_t1_return):>8} {_pct(s.win_rate):>6}"
            )
        lines.append("")

    # Extended horizons display
    if any([
        summary.avg_t10_return is not None,
        summary.avg_t20_return is not None,
        summary.avg_t30_return is not None
    ]):
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

    lines.append("━" * 60)
    return "\n".join(lines)
