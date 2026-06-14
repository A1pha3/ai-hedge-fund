"""预期收益估算 — P9-1.

基于历史 score_b 分桶的实际收益, 为每只推荐估算预期 N 日收益。
复用 :mod:`confidence_calibration` 的校准数据, 无需额外数据源。

工作原理:
1. 加载历史 tracking 数据, 计算 score 分桶的平均收益
2. 根据当前推荐的 score_b, 找到所属分桶
3. 用该分桶的历史平均收益作为"预期收益"

业界对标: QuantConnect Alpha Streams 的预期收益展示; Numerai 的
"Expected Value" 列。

CLI 集成:
    通过 ``--decision-flow`` 或 ``--expected-returns`` 调用。
    结果也整合到 ``--auto`` 输出的推荐列表中。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.screening.confidence_calibration import (
    _find_bucket,
    _load_tracking_records,
    CalibrationSummary,
    compute_calibration,
)
from src.screening.consecutive_recommendation import resolve_report_dir
from src.utils.display import Fore, Style

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

HORIZONS = ("t1", "t5", "t10", "t20", "t30")

HORIZON_LABELS = {
    "t1": "T+1",
    "t5": "T+5",
    "t10": "T+10",
    "t20": "T+20",
    "t30": "T+30",
}


@dataclass
class ExpectedReturn:
    """单只推荐的预期收益信息。"""

    ticker: str
    score_b: float
    bucket_label: str
    bucket_sample_count: int
    expected_returns: dict[str, float | None]  # horizon → expected return pct
    win_rates: dict[str, float | None]  # horizon → win rate

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "score_b": round(self.score_b, 4),
            "bucket_label": self.bucket_label,
            "bucket_sample_count": self.bucket_sample_count,
            "expected_returns": {k: round(v, 4) if v is not None else None for k, v in self.expected_returns.items()},
            "win_rates": {k: round(v, 4) if v is not None else None for k, v in self.win_rates.items()},
        }


@dataclass
class ExpectedReturnReport:
    """预期收益汇总报告。"""

    trade_date: str
    lookback_days: int
    total_samples: int
    items: list[ExpectedReturn] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "lookback_days": self.lookback_days,
            "total_samples": self.total_samples,
            "items": [item.to_dict() for item in self.items],
        }


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _build_bucket_return_map(calibration: CalibrationSummary) -> dict[str, dict[str, float | None]]:
    """Build a mapping from bucket label → {horizon: avg_return}.

    Returns:
        ``{"高 (>0.8)": {"t1": 1.5, "t5": 3.2, ...}, ...}``
    """
    result: dict[str, dict[str, float | None]] = {}
    for bucket in calibration.buckets:
        result[bucket.label] = {
            "t1": bucket.t1_avg_return,
            "t5": bucket.t5_avg_return,
            "t10": bucket.t10_avg_return,
            "t20": bucket.t20_avg_return,
            "t30": bucket.t30_avg_return,
        }
    return result


def _build_bucket_winrate_map(calibration: CalibrationSummary) -> dict[str, dict[str, float | None]]:
    """Build a mapping from bucket label → {horizon: win_rate}."""
    result: dict[str, dict[str, float | None]] = {}
    for bucket in calibration.buckets:
        result[bucket.label] = {
            "t1": bucket.t1_win_rate,
            "t5": bucket.t5_win_rate,
            "t10": bucket.t10_win_rate,
            "t20": bucket.t20_win_rate,
            "t30": bucket.t30_win_rate,
        }
    return result


def _build_bucket_sample_map(calibration: CalibrationSummary) -> dict[str, int]:
    """Build a mapping from bucket label → sample count."""
    return {bucket.label: bucket.sample_count for bucket in calibration.buckets}


def compute_expected_returns(
    *,
    recommendations: list[dict[str, Any]],
    lookback_days: int = 60,
    reports_dir: Path | None = None,
) -> ExpectedReturnReport:
    """Compute expected returns for a list of recommendations.

    Args:
        recommendations: List of recommendation dicts (must have ``ticker`` and ``score_b``)
        lookback_days: How many days of history to use for calibration
        reports_dir: Reports directory for tracking history

    Returns:
        :class:`ExpectedReturnReport`
    """
    search_dir = reports_dir or resolve_report_dir()
    records = _load_tracking_records(search_dir)
    calibration = compute_calibration(records, lookback_days=lookback_days)
    return_map = _build_bucket_return_map(calibration)
    winrate_map = _build_bucket_winrate_map(calibration)
    sample_map = _build_bucket_sample_map(calibration)

    trade_date = ""
    items: list[ExpectedReturn] = []
    for rec in recommendations:
        ticker = str(rec.get("ticker", ""))
        score_b = float(rec.get("score_b", 0.0) or 0.0)
        if not trade_date:
            trade_date = str(rec.get("trade_date", ""))

        bucket_info = _find_bucket(score_b)
        if bucket_info is None:
            items.append(
                ExpectedReturn(
                    ticker=ticker,
                    score_b=score_b,
                    bucket_label="未知",
                    bucket_sample_count=0,
                    expected_returns={h: None for h in HORIZONS},
                    win_rates={h: None for h in HORIZONS},
                )
            )
            continue

        label = bucket_info[0]
        items.append(
            ExpectedReturn(
                ticker=ticker,
                score_b=score_b,
                bucket_label=label,
                bucket_sample_count=sample_map.get(label, 0),
                expected_returns=return_map.get(label, {h: None for h in HORIZONS}),
                win_rates=winrate_map.get(label, {h: None for h in HORIZONS}),
            )
        )

    return ExpectedReturnReport(
        trade_date=trade_date,
        lookback_days=lookback_days,
        total_samples=calibration.total_samples,
        items=items,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_return(value: float | None) -> str:
    """Format an expected return value with color coding."""
    if value is None:
        return f"{Fore.YELLOW}—{Style.RESET_ALL}"
    if value > 0:
        return f"{Fore.GREEN}+{value:.2f}%{Style.RESET_ALL}"
    if value < 0:
        return f"{Fore.RED}{value:.2f}%{Style.RESET_ALL}"
    return f"{Fore.WHITE}0.00%{Style.RESET_ALL}"


def _fmt_winrate(value: float | None) -> str:
    """Format a win rate value."""
    if value is None:
        return f"{Fore.YELLOW}—{Style.RESET_ALL}"
    if value >= 0.55:
        color = Fore.GREEN
    elif value >= 0.45:
        color = Fore.YELLOW
    else:
        color = Fore.RED
    return f"{color}{value:.0%}{Style.RESET_ALL}"


def render_expected_returns(report: ExpectedReturnReport) -> str:
    """Render expected returns as a readable table.

    Shows each recommendation with:
    - Score bucket
    - Historical sample count
    - Expected return per horizon (T+1/T+5/T+10/T+20/T+30)
    - Win rate per horizon
    """
    if not report.items:
        return f"\n{Fore.CYAN}📊 预期收益估算{Style.RESET_ALL}\n  无推荐数据\n"

    lines = [
        f"\n{Fore.CYAN}📊 预期收益估算{Style.RESET_ALL}",
        f"  基于最近 {report.lookback_days} 天 {report.total_samples} 条历史推荐",
        "",
        f"  {'标的':<8} {'Score':>6} {'分位':>10} {'样本':>4}  {'T+1':>8}  {'T+5':>8}  {'T+10':>8}  {'T+20':>9}  {'T+30':>9}",
        f"  {'─' * 8} {'─' * 6} {'─' * 10} {'─' * 4}  {'─' * 8}  {'─' * 8}  {'─' * 8}  {'─' * 9}  {'─' * 9}",
    ]

    for item in report.items:
        er = item.expected_returns
        row = (
            f"  {item.ticker:<8} {item.score_b:>6.3f} {item.bucket_label:>10} {item.bucket_sample_count:>4}"
            f"  {_fmt_return(er.get('t1')):>18}"
            f"  {_fmt_return(er.get('t5')):>18}"
            f"  {_fmt_return(er.get('t10')):>18}"
            f"  {_fmt_return(er.get('t20')):>19}"
            f"  {_fmt_return(er.get('t30')):>19}"
        )
        lines.append(row)

    lines.append("")
    lines.append(f"  {Fore.WHITE}说明: 预期收益 = 历史同 score 分位的平均实际收益。仅供参考。{Style.RESET_ALL}")
    return "\n".join(lines)


def render_expected_returns_compact(report: ExpectedReturnReport) -> str:
    """Render a compact summary for integration into decision flow."""
    if not report.items:
        return "无预期收益数据"

    # Long-horizon emphasis for 30-day stock selection
    lines = [f"  30天 edge (基于 {report.total_samples} 条历史):"]
    for item in report.items[:5]:
        er = item.expected_returns
        t20 = _fmt_return(er.get("t20"))
        t30 = _fmt_return(er.get("t30"))
        wr_str = _fmt_winrate(item.win_rates.get("t30"))
        lines.append(
            f"    {item.ticker:<8} score={item.score_b:.3f}  样本={item.bucket_sample_count:<3d}  T+20={t20}  T+30={t30}  T+30胜率={wr_str}"
        )

    return "\n".join(lines)
