"""Volume-Price Confirmation Signal — P11-2.

A classic technical analysis principle: **bullish signals WITHOUT volume
confirmation are less reliable**.  This module checks whether each
recommendation's recent price movement is supported by increasing volume.

Logic:
    - Compute 5-day average volume for each ticker from recent reports
    - If latest volume > 1.2x avg → "confirmed" (volume supports the move)
    - If latest volume < 0.8x avg → "divergence" (price up, volume down)
    - Otherwise → "neutral"

The result is a ``volume_factor`` (0.0 ~ 1.0) that can be integrated into
the composite confidence score.

CLI::

    python src/main.py --volume-confirm [--top-n=20]

Integration:
    ``--composite-score`` includes volume confirmation as a sub-factor.
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

_CONFIRMED_THRESHOLD: float = 1.2  # volume > 1.2x avg = confirmed
_DIVERGENCE_THRESHOLD: float = 0.8  # volume < 0.8x avg = divergence
_DEFAULT_LOOKBACK: int = 5

#: Volume confirmation factor for composite score
_CONFIRMED_BONUS: float = 0.03
_DIVERGENCE_PENALTY: float = -0.03


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class VolumeEntry:
    """Volume confirmation info for a single ticker."""

    ticker: str
    name: str = ""
    latest_volume: float = 0.0
    avg_volume: float = 0.0
    volume_ratio: float = 1.0
    confirmation: str = "neutral"  # confirmed / divergence / neutral
    volume_factor: float = 0.0


@dataclass
class VolumeReport:
    """Volume confirmation report."""

    trade_date: str = ""
    lookback_days: int = _DEFAULT_LOOKBACK
    items: list[VolumeEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "lookback_days": self.lookback_days,
            "items": [
                {
                    "ticker": item.ticker,
                    "name": item.name,
                    "volume_ratio": round(item.volume_ratio, 4),
                    "confirmation": item.confirmation,
                    "volume_factor": round(item.volume_factor, 4),
                }
                for item in self.items
            ],
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def _extract_volume_from_rec(rec: dict[str, Any]) -> float:
    """Extract volume (or volume-ratio proxy) from a recommendation record.

    Priority:
        1. Direct 'volume' field on rec (legacy synthetic fixtures).
        2. metrics['volume'/'vol'/'turnover'] (legacy synthetic fixtures).
        3. metrics['amount_ratio_5'] — NS-12 fix: real FusedScore.metrics key
           (5-day amount ratio; closest to single-day volume-ratio semantics).
        4. metrics['turnover_ratio_20'] — NS-12 fix fallback (20-day turnover ratio).

    Returns 0.0 if no usable value is found. The historical ratio logic in
    ``compute_volume_confirmation`` is scale-invariant (latest/avg), so feeding
    ratio proxies still yields a meaningful "increasing vs decreasing" signal
    even though the absolute scale differs from raw volume.
    """
    # Try direct volume field
    vol = rec.get("volume")
    if vol is not None:
        try:
            return float(vol)
        except (TypeError, ValueError):
            pass

    # Try metrics
    metrics = rec.get("metrics") or {}
    for key in ("volume", "vol", "turnover"):
        val = metrics.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass

    # NS-12: real FusedScore.metrics keys — 修复死信号 (原本永远返回 0.0)
    for key in ("amount_ratio_5", "turnover_ratio_20"):
        val = metrics.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass

    return 0.0


def compute_volume_confirmation(
    *,
    top_n: int = 20,
    lookback_days: int = _DEFAULT_LOOKBACK,
    reports_dir: Path | None = None,
) -> VolumeReport:
    """Compute volume-price confirmation for latest recommendations.

    Args:
        top_n: Number of top recommendations to check
        lookback_days: How many days for average volume
        reports_dir: Reports directory

    Returns:
        :class:`VolumeReport`
    """
    search_dir = reports_dir or resolve_report_dir()
    history = load_auto_screening_history(
        lookback_days=lookback_days,
        report_dir=search_dir,
    )

    if not history:
        return VolumeReport(lookback_days=lookback_days)

    # Latest report
    latest = history[0]
    latest_payload = latest.get("payload", {})
    trade_date = latest.get("date", "")
    latest_recs = (latest_payload.get("recommendations") or [])[:top_n]

    if not latest_recs:
        return VolumeReport(trade_date=trade_date, lookback_days=lookback_days)

    # Build volume history per ticker
    ticker_volumes: dict[str, list[float]] = {}
    ticker_names: dict[str, str] = {}

    for report in reversed(history):
        recs = (report.get("payload", {}).get("recommendations")) or []
        for rec in recs:
            ticker = str(rec.get("ticker", ""))
            if not ticker:
                continue
            vol = _extract_volume_from_rec(rec)
            if vol > 0:
                ticker_volumes.setdefault(ticker, []).append(vol)
            name = str(rec.get("name", "") or "")
            if name and ticker not in ticker_names:
                ticker_names[ticker] = name

    # Compute confirmation for each recommendation
    items: list[VolumeEntry] = []
    for rec in latest_recs:
        ticker = str(rec.get("ticker", ""))
        name = str(rec.get("name", "") or ticker_names.get(ticker, ""))
        volumes = ticker_volumes.get(ticker, [])

        if len(volumes) < 2:
            items.append(
                VolumeEntry(
                    ticker=ticker,
                    name=name,
                    confirmation="neutral",
                    volume_factor=0.0,
                )
            )
            continue

        latest_vol = volumes[-1]
        avg_vol = sum(volumes[:-1]) / (len(volumes) - 1) if len(volumes) > 1 else latest_vol

        if avg_vol <= 0:
            ratio = 1.0
        else:
            ratio = latest_vol / avg_vol

        if ratio >= _CONFIRMED_THRESHOLD:
            confirmation = "confirmed"
            factor = _CONFIRMED_BONUS
        elif ratio <= _DIVERGENCE_THRESHOLD:
            confirmation = "divergence"
            factor = _DIVERGENCE_PENALTY
        else:
            confirmation = "neutral"
            factor = 0.0

        items.append(
            VolumeEntry(
                ticker=ticker,
                name=name,
                latest_volume=latest_vol,
                avg_volume=avg_vol,
                volume_ratio=ratio,
                confirmation=confirmation,
                volume_factor=factor,
            )
        )

    # Sort by volume factor descending
    items.sort(key=lambda x: x.volume_factor, reverse=True)

    return VolumeReport(
        trade_date=trade_date,
        lookback_days=lookback_days,
        items=items,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _confirmation_colored(label: str) -> str:
    if label == "confirmed":
        return f"{Fore.GREEN}✓ 放量确认{Style.RESET_ALL}"
    if label == "divergence":
        return f"{Fore.RED}✗ 缩量背离{Style.RESET_ALL}"
    return f"{Fore.WHITE}— 中性{Style.RESET_ALL}"


def render_volume_confirmation(report: VolumeReport) -> str:
    """Render volume confirmation as a readable table."""
    if not report.items:
        return f"\n{Fore.CYAN}📊 Volume Confirmation (量价确认){Style.RESET_ALL}\n  无推荐数据\n"

    lines = [
        f"\n{Fore.CYAN}📊 Volume Confirmation (量价确认){Style.RESET_ALL}",
        f"  基于 {report.lookback_days} 天成交量对比",
        "",
        f"  {'标的':<8} {'名称':<10} {'量比':>6} {'状态':<20} {'因子':>6}",
        f"  {'─' * 8} {'─' * 10} {'─' * 6} {'─' * 20} {'─' * 6}",
    ]

    for item in report.items:
        label = _confirmation_colored(item.confirmation)
        factor_str = f"{Fore.GREEN}+{item.volume_factor:.2f}{Style.RESET_ALL}" if item.volume_factor > 0 else f"{Fore.RED}{item.volume_factor:.2f}{Style.RESET_ALL}" if item.volume_factor < 0 else "  0.00"
        lines.append(f"  {item.ticker:<8} {item.name[:10]:<10} " f"{item.volume_ratio:>5.2f}x {label:>28} {factor_str:>14}")

    confirmed = sum(1 for i in report.items if i.confirmation == "confirmed")
    divergence = sum(1 for i in report.items if i.confirmation == "divergence")
    neutral = len(report.items) - confirmed - divergence
    lines.append("")
    lines.append(f"  {Fore.GREEN}放量确认: {confirmed}{Style.RESET_ALL}  " f"{Fore.WHITE}中性: {neutral}{Style.RESET_ALL}  " f"{Fore.RED}缩量背离: {divergence}{Style.RESET_ALL}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def run_volume_confirm(argv: list[str] | None = None) -> int:
    """CLI entry point for --volume-confirm."""
    top_n = 20
    lookback = _DEFAULT_LOOKBACK
    if argv:
        for arg in argv:
            if arg.startswith("--top-n="):
                try:
                    top_n = int(arg.split("=")[1])
                except ValueError:
                    pass
            elif arg.startswith("--lookback="):
                try:
                    lookback = int(arg.split("=")[1])
                except ValueError:
                    pass

    reports_dir = resolve_report_dir()
    report = compute_volume_confirmation(
        top_n=top_n,
        lookback_days=lookback,
        reports_dir=reports_dir,
    )
    print(render_volume_confirmation(report))
    return 0
