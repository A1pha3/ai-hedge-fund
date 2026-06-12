"""Multi-Timeframe Trend Resonance — P14-1.

A classic quantitative principle: **stocks trending in the SAME direction
across multiple timeframes are significantly more likely to continue**.

Logic:
    - Compute 5d / 20d / 60d trend direction via linear regression slope
    - All three aligned (all up or all down) → "resonance" (strong signal)
    - Two aligned, one flat → "partial" (moderate signal)
    - Conflicting directions → "mixed" (weak signal)
    - Integrates into composite_score as the 6th signal factor

CLI::

    python src/main.py --trend-resonance [--top-n=20]

Integration:
    ``--composite-score`` includes trend resonance as a sub-factor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.screening.consecutive_recommendation import (
    load_auto_screening_history,
    resolve_report_dir,
)
from src.utils.display import Fore, Style


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Timeframes to check (in days)
_TIMEFRAMES: tuple[int, ...] = (5, 20, 60)

#: Minimum slope to consider "trending" (per-day score_b change)
_TREND_THRESHOLD: float = 0.003

#: Resonance bonus/penalty for composite score
_RESONANCE_BONUS: float = 0.05
_PARTIAL_BONUS: float = 0.02
_CONFLICT_PENALTY: float = -0.05


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class TrendResonanceEntry:
    """Trend resonance info for a single ticker."""

    ticker: str
    name: str = ""
    slope_5d: float = 0.0
    slope_20d: float = 0.0
    slope_60d: float = 0.0
    direction_5d: str = "flat"  # up / down / flat
    direction_20d: str = "flat"
    direction_60d: str = "flat"
    resonance_label: str = "neutral"  # resonance / partial / mixed / neutral
    resonance_factor: float = 0.0


@dataclass
class TrendResonanceReport:
    """Trend resonance report for all recommended tickers."""

    trade_date: str = ""
    items: list[TrendResonanceEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "items": [
                {
                    "ticker": item.ticker,
                    "name": item.name,
                    "slope_5d": round(item.slope_5d, 6),
                    "slope_20d": round(item.slope_20d, 6),
                    "slope_60d": round(item.slope_60d, 6),
                    "direction_5d": item.direction_5d,
                    "direction_20d": item.direction_20d,
                    "direction_60d": item.direction_60d,
                    "resonance_label": item.resonance_label,
                    "resonance_factor": round(item.resonance_factor, 4),
                }
                for item in self.items
            ],
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def _simple_slope(values: list[float]) -> float:
    """Compute linear regression slope through *values*.

    Uses the formula:  slope = Σ((x - x̄)(y - ȳ)) / Σ((x - x̄)²)

    Returns 0.0 if fewer than 2 data points.
    """
    n = len(values)
    if n < 2:
        return 0.0

    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n

    numerator = 0.0
    denominator = 0.0
    for i, y in enumerate(values):
        dx = float(i) - x_mean
        dy = y - y_mean
        numerator += dx * dy
        denominator += dx * dx

    if denominator == 0.0:
        return 0.0

    return numerator / denominator


def _classify_direction(slope: float) -> str:
    """Classify slope into up/down/flat."""
    if slope > _TREND_THRESHOLD:
        return "up"
    if slope < -_TREND_THRESHOLD:
        return "down"
    return "flat"


def _classify_resonance(directions: tuple[str, str, str]) -> tuple[str, float]:
    """Classify multi-timeframe resonance.

    Returns (label, factor).
    """
    ups = sum(1 for d in directions if d == "up")
    downs = sum(1 for d in directions if d == "down")

    # Full resonance: all three aligned
    if ups == 3:
        return "resonance_up", _RESONANCE_BONUS
    if downs == 3:
        return "resonance_down", -_RESONANCE_BONUS

    # Partial: two aligned, one flat or same direction
    if ups >= 2 and downs == 0:
        return "partial_up", _PARTIAL_BONUS
    if downs >= 2 and ups == 0:
        return "partial_down", -_PARTIAL_BONUS

    # Mixed: conflicting directions
    if ups > 0 and downs > 0:
        return "mixed", _CONFLICT_PENALTY

    return "neutral", 0.0


def _extract_score_history(
    ticker: str,
    history: list[dict[str, Any]],
    max_days: int = 60,
) -> list[float]:
    """Extract score_b time series for a ticker from report history.

    Returns list of score_b values ordered from oldest to newest.
    """
    scores: list[float] = []
    for report in reversed(history):
        recs = (report.get("payload", {}).get("recommendations")) or []
        for rec in recs:
            if str(rec.get("ticker", "")) == ticker:
                try:
                    score = float(rec.get("score_b", 0.0) or 0.0)
                    scores.append(score)
                except (TypeError, ValueError):
                    scores.append(0.0)
                break
    return scores[-max_days:] if len(scores) > max_days else scores


def compute_trend_resonance(
    *,
    top_n: int = 20,
    reports_dir: Path | None = None,
) -> TrendResonanceReport:
    """Compute multi-timeframe trend resonance for latest recommendations.

    Args:
        top_n: Number of top recommendations to analyze
        reports_dir: Reports directory

    Returns:
        :class:`TrendResonanceReport`
    """
    search_dir = reports_dir or resolve_report_dir()

    # Load 60 days of history to compute all three timeframes
    history = load_auto_screening_history(
        lookback_days=60,
        report_dir=search_dir,
    )

    if not history:
        return TrendResonanceReport()

    latest = history[0]
    latest_payload = latest.get("payload", {})
    trade_date = latest.get("date", "")
    latest_recs = (latest_payload.get("recommendations") or [])[:top_n]

    if not latest_recs:
        return TrendResonanceReport(trade_date=trade_date)

    items: list[TrendResonanceEntry] = []
    for rec in latest_recs:
        ticker = str(rec.get("ticker", ""))
        name = str(rec.get("name", "") or "")

        # Extract score_b history
        scores = _extract_score_history(ticker, history, max_days=60)

        if len(scores) < 5:
            items.append(
                TrendResonanceEntry(
                    ticker=ticker,
                    name=name,
                    resonance_label="neutral",
                    resonance_factor=0.0,
                )
            )
            continue

        # Compute slopes for each timeframe
        slope_5d = _simple_slope(scores[-5:])
        slope_20d = _simple_slope(scores[-20:]) if len(scores) >= 20 else _simple_slope(scores)
        slope_60d = _simple_slope(scores[-60:]) if len(scores) >= 60 else _simple_slope(scores)

        d5 = _classify_direction(slope_5d)
        d20 = _classify_direction(slope_20d)
        d60 = _classify_direction(slope_60d)

        label, factor = _classify_resonance((d5, d20, d60))

        items.append(
            TrendResonanceEntry(
                ticker=ticker,
                name=name,
                slope_5d=slope_5d,
                slope_20d=slope_20d,
                slope_60d=slope_60d,
                direction_5d=d5,
                direction_20d=d20,
                direction_60d=d60,
                resonance_label=label,
                resonance_factor=factor,
            )
        )

    # Sort by resonance factor descending
    items.sort(key=lambda x: x.resonance_factor, reverse=True)

    return TrendResonanceReport(trade_date=trade_date, items=items)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _direction_icon(direction: str) -> str:
    if direction == "up":
        return f"{Fore.GREEN}↑{Style.RESET_ALL}"
    if direction == "down":
        return f"{Fore.RED}↓{Style.RESET_ALL}"
    return f"{Fore.WHITE}→{Style.RESET_ALL}"


def _resonance_colored(label: str, factor: float) -> str:
    if "resonance" in label:
        color = Fore.GREEN if factor > 0 else Fore.RED
        arrow = "共振↑" if factor > 0 else "共振↓"
        return f"{color}{arrow}{Style.RESET_ALL}"
    if "partial" in label:
        color = Fore.GREEN if factor > 0 else Fore.RED
        arrow = "偏多" if factor > 0 else "偏空"
        return f"{color}{arrow}{Style.RESET_ALL}"
    if label == "mixed":
        return f"{Fore.YELLOW}冲突{Style.RESET_ALL}"
    return f"{Fore.WHITE}中性{Style.RESET_ALL}"


def render_trend_resonance(report: TrendResonanceReport) -> str:
    """Render trend resonance as a readable table."""
    if not report.items:
        return f"\n{Fore.CYAN}🔮 Trend Resonance (多时间框架趋势共振){Style.RESET_ALL}\n  无推荐数据\n"

    lines = [
        f"\n{Fore.CYAN}🔮 Trend Resonance (多时间框架趋势共振){Style.RESET_ALL}",
        "  5d / 20d / 60d score_b 趋势方向一致性",
        "",
        f"  {'标的':<8} {'名称':<10} {'5d':>4} {'20d':>4} {'60d':>4}  {'共振':>8}  {'因子':>6}",
        f"  {'─' * 8} {'─' * 10} {'─' * 4} {'─' * 4} {'─' * 4}  {'─' * 8}  {'─' * 6}",
    ]

    for item in report.items:
        d5 = _direction_icon(item.direction_5d)
        d20 = _direction_icon(item.direction_20d)
        d60 = _direction_icon(item.direction_60d)
        resonance = _resonance_colored(item.resonance_label, item.resonance_factor)
        factor_str = (
            f"{Fore.GREEN}+{item.resonance_factor:.2f}{Style.RESET_ALL}"
            if item.resonance_factor > 0
            else f"{Fore.RED}{item.resonance_factor:.2f}{Style.RESET_ALL}"
            if item.resonance_factor < 0
            else "  0.00"
        )
        lines.append(
            f"  {item.ticker:<8} {item.name[:10]:<10} {d5:>4} {d20:>4} {d60:>4}  {resonance:>14}  {factor_str:>14}"
        )

    resonance_up = sum(1 for i in report.items if i.resonance_label == "resonance_up")
    partial_up = sum(1 for i in report.items if i.resonance_label == "partial_up")
    mixed = sum(1 for i in report.items if i.resonance_label == "mixed")
    neutral = len(report.items) - resonance_up - partial_up - mixed

    lines.append("")
    lines.append(
        f"  {Fore.GREEN}共振↑: {resonance_up}{Style.RESET_ALL}  "
        f"{Fore.GREEN}偏多: {partial_up}{Style.RESET_ALL}  "
        f"{Fore.WHITE}中性: {neutral}{Style.RESET_ALL}  "
        f"{Fore.YELLOW}冲突: {mixed}{Style.RESET_ALL}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def run_trend_resonance(argv: list[str] | None = None) -> int:
    """CLI entry point for --trend-resonance."""
    top_n = 20
    if argv:
        for arg in argv:
            if arg.startswith("--top-n="):
                try:
                    top_n = int(arg.split("=")[1])
                except ValueError:
                    pass

    reports_dir = resolve_report_dir()
    report = compute_trend_resonance(
        top_n=top_n,
        reports_dir=reports_dir,
    )
    print(render_trend_resonance(report))
    return 0
