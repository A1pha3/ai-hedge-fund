"""Composite Confidence Score — P11-1.

Combines multiple independent signals into a single unified confidence score
per recommendation.  This gives users ONE number to rank picks, instead of
having to mentally combine score_b, momentum, sector strength, consistency,
etc.

Formula::

    composite = base_score
              + momentum_bonus   (from signal_momentum, ±0.10)
              + sector_bonus     (from sector_strength, ±0.05)
              + consistency_adj  (high +0.05, medium 0, low -0.10)
              + freshness_adj    (fresh 0, stale -0.05)

    composite is clamped to [-1.0, +1.0].

CLI::

    python src/main.py --composite-score [--top-n=20]

Integration:
    ``--decision-flow`` Step 10 outputs composite scores for all recommendations.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.screening.consecutive_recommendation import resolve_report_dir
from src.screening.data_quality_audit import _find_latest_report
from src.screening.sector_strength import compute_sector_strength
from src.screening.signal_consistency import check_signal_consistency
from src.screening.signal_momentum import compute_signal_momentum
from src.screening.trend_resonance import compute_trend_resonance
from src.screening.volume_confirmation import compute_volume_confirmation
from colorama import Fore, Style
from src.utils.numeric import coerce_score_b

# BH-021 / R48-R50 BH-017 同族: composite_score 此前无 module logger。composite score
# 直接驱动前门 R10 多策略共振 + BUY 门控；5 个信号维度 (momentum/sector/consistency/
# volume/trend) 任一瞬时失败时此前静默 → 该维度贡献 0 → composite 偏差 → 错误的
# Buy/Hold/Avoid 决策且无信号。debug 级降级诊断让运维可定位哪个维度降级。
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Consistency adjustment by level
_CONSISTENCY_ADJ: dict[str, float] = {
    "high": 0.05,
    "medium": 0.0,
    "low": -0.10,
    "unknown": -0.05,
}

#: Freshness penalty when data is stale
_STALE_PENALTY: float = -0.05


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class CompositeEntry:
    """Composite confidence score for a single ticker."""

    ticker: str
    name: str = ""
    base_score: float = 0.0
    momentum_bonus: float = 0.0
    sector_bonus: float = 0.0
    consistency_adj: float = 0.0
    volume_factor: float = 0.0
    trend_resonance_factor: float = 0.0
    composite_score: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompositeReport:
    """Composite confidence report."""

    trade_date: str = ""
    items: list[CompositeEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "items": [
                {
                    "ticker": item.ticker,
                    "name": item.name,
                    "base_score": round(item.base_score, 4),
                    "momentum_bonus": round(item.momentum_bonus, 4),
                    "sector_bonus": round(item.sector_bonus, 4),
                    "consistency_adj": round(item.consistency_adj, 4),
                    "volume_factor": round(item.volume_factor, 4),
                    "trend_resonance_factor": round(item.trend_resonance_factor, 4),
                    "composite_score": round(item.composite_score, 4),
                }
                for item in self.items
            ],
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_composite_scores(
    *,
    top_n: int = 20,
    lookback_days: int = 5,
    reports_dir: Path | None = None,
) -> CompositeReport:
    """Compute composite confidence scores for latest recommendations.

    Combines:
    1. Base score_b from the latest screening report
    2. Signal momentum bonus (P10-1)
    3. Sector strength bonus (P10-2)
    4. Signal consistency adjustment (P7-1)
    5. Volume-price confirmation (P11-2)

    Args:
        top_n: Number of top recommendations to score
        lookback_days: Lookback for momentum/sector analysis
        reports_dir: Reports directory

    Returns:
        :class:`CompositeReport`
    """
    import json

    search_dir = reports_dir or resolve_report_dir()

    # Load latest report
    report_path = _find_latest_report(search_dir)
    if report_path is None:
        return CompositeReport()

    # R104 (R88/BH-017 family): a corrupt/truncated report (partial write /
    # interrupted run) must not crash the composite-scoring path that --auto
    # depends on. Degrade to empty CompositeReport() (same semantics as the
    # missing-file branch above) + warning diagnostic so the operator can
    # distinguish "no report yet" vs "report corrupt".
    try:
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "[CompositeScore] 最新报告 %s 损坏或不可读 (%s); 降级为空 CompositeReport",
            report_path,
            exc,
        )
        return CompositeReport()
    recs = (report_data.get("recommendations") or [])[:top_n]
    trade_date = report_data.get("date", "")

    return compute_composite_scores_for_recommendations(
        recommendations=recs,
        trade_date=trade_date,
        lookback_days=lookback_days,
        reports_dir=search_dir,
    )


def _compute_dimension_bonus_map(
    dimension_name: str,
    compute_fn: Callable[..., Any],
    attr_name: str,
    *,
    top_n: int,
    search_dir: Path,
    lookback_days: int | None = None,
) -> dict[str, float]:
    """Compute a ``{ticker: bonus}`` map for one composite dimension.

    Shared shape for momentum / sector / volume / trend dimensions, which all
    expose a report with ``.items`` carrying a per-ticker bonus attribute.
    ``lookback_days`` is forwarded only when provided (trend uses just
    ``top_n`` + ``reports_dir``). On any failure the dimension degrades to an
    empty map (composite then scores that dimension as 0) and emits a BH-021
    debug log so the degradation is observable instead of silent.
    """
    compute_kwargs: dict[str, Any] = {"top_n": top_n, "reports_dir": search_dir}
    if lookback_days is not None:
        compute_kwargs["lookback_days"] = lookback_days
    try:
        report = compute_fn(**compute_kwargs)
        return {item.ticker: getattr(item, attr_name) for item in report.items}
    except Exception as exc:
        # BH-021 / R48 BH-017 同族: 该维度降级 → bonus 全部 0，composite 偏差
        # 直接影响 R10 共振与 BUY 门控。发降级诊断。
        logger.debug("composite %s dimension degraded to {}: %s", dimension_name, exc)
        return {}


def compute_composite_scores_for_recommendations(
    *,
    recommendations: list[dict[str, Any]],
    trade_date: str = "",
    lookback_days: int = 5,
    reports_dir: Path | None = None,
) -> CompositeReport:
    """Compute composite scores for an explicit recommendation list."""
    recs = list(recommendations)
    if not recs:
        return CompositeReport(trade_date=trade_date)

    # Compute momentum / sector / volume dimensions (shared P10-1/P10-2/P11-2 shape).
    top_n = len(recs)
    search_dir = reports_dir or resolve_report_dir()
    momentum_map = _compute_dimension_bonus_map(
        "momentum",
        compute_signal_momentum,
        "momentum_bonus",
        top_n=top_n,
        lookback_days=lookback_days,
        search_dir=search_dir,
    )
    sector_map = _compute_dimension_bonus_map(
        "sector",
        compute_sector_strength,
        "strength_bonus",
        top_n=top_n,
        lookback_days=lookback_days,
        search_dir=search_dir,
    )
    volume_map = _compute_dimension_bonus_map(
        "volume",
        compute_volume_confirmation,
        "volume_factor",
        top_n=top_n,
        lookback_days=lookback_days,
        search_dir=search_dir,
    )

    # Compute signal consistency (P7-1) — distinct shape (dict comprehension), not shared.
    try:
        consistency_results = check_signal_consistency(recs)
        consistency_map = {item.get("ticker", ""): _CONSISTENCY_ADJ.get(item.get("consistency_level", "unknown"), 0.0) for item in consistency_results}
    except Exception as exc:
        # BH-021 / R48 BH-017 同族: consistency 维度降级 → consistency_adj 全部 0。
        logger.debug("composite consistency dimension degraded to {}: %s", exc)
        consistency_map = {}

    # Compute trend resonance (P14-1) — uses _compute_dimension_bonus_map with
    # lookback_days=None (trend only takes top_n + reports_dir).
    trend_map = _compute_dimension_bonus_map(
        "trend",
        compute_trend_resonance,
        "resonance_factor",
        top_n=top_n,
        search_dir=search_dir,
    )

    # Build composite entries
    items: list[CompositeEntry] = []
    for rec in recs:
        ticker = str(rec.get("ticker", ""))
        name = str(rec.get("name", "") or "")
        # BH-012: ``float(nan or 0.0)`` stays NaN (NaN is truthy in Python),
        # and ``max(-1.0, min(1.0, nan))`` returns 1.0 on CPython — so a corrupt
        # score_b would silently get the HIGHEST composite and bubble to the top
        # of the front-door recommendation list. coerce_score_b rejects NaN/Inf
        # (and clamps non-finite to 0.0) so corrupt data never inflates ranking.
        base_score = coerce_score_b(rec.get("score_b", 0.0))

        mom = momentum_map.get(ticker, 0.0)
        sec = sector_map.get(ticker, 0.0)
        con = consistency_map.get(ticker, 0.0)
        vol = volume_map.get(ticker, 0.0)
        trf = trend_map.get(ticker, 0.0)

        # R78 (BH-012 同族): base_score 已通过 coerce_score_b 拒绝 NaN/Inf, 但
        # 5 个 dimension bonus 来自各 dimension calculator, 任一返回 NaN/Inf (未来
        # calculator 回归 / 缓存数据 corrupt) 都会让求和变为 NaN, 而
        # ``max(-1.0, min(1.0, nan))`` 在 CPython 上返回 ``1.0`` —— corrupt 标的
        # 会静默顶到前门推荐顶部 (BH-012 同型 silent-corruption)。对每个 dimension
        # bonus 做 finite-guard (非有限值降级为 0.0), 与 base_score 的 coerce 一致。
        mom = mom if math.isfinite(mom) else 0.0
        sec = sec if math.isfinite(sec) else 0.0
        con = con if math.isfinite(con) else 0.0
        vol = vol if math.isfinite(vol) else 0.0
        trf = trf if math.isfinite(trf) else 0.0

        composite = max(-1.0, min(1.0, base_score + mom + sec + con + vol + trf))

        items.append(
            CompositeEntry(
                ticker=ticker,
                name=name,
                base_score=base_score,
                momentum_bonus=mom,
                sector_bonus=sec,
                consistency_adj=con,
                volume_factor=vol,
                trend_resonance_factor=trf,
                composite_score=composite,
                details={
                    "momentum_label": "bonus" if mom > 0 else "penalty" if mom < 0 else "neutral",
                    "sector_label": "strong" if sec > 0 else "weak" if sec < 0 else "neutral",
                    "consistency_level": "high" if con > 0 else "low" if con < 0 else "medium",
                    "volume_confirmation": "confirmed" if vol > 0 else "divergence" if vol < 0 else "neutral",
                    "trend_resonance": "resonance" if trf > 0.02 else "conflict" if trf < -0.02 else "neutral",
                },
            )
        )

    # Sort by composite score descending. BH-011: add deterministic
    # secondary keys (base_score desc, then ticker asc) so equal-composite
    # tickers have a stable order — otherwise Top-N membership flips
    # nondeterministically across runs (Python stable sort preserves JSON-dict
    # input order, which is not contractually sorted).
    items.sort(key=lambda x: (-x.composite_score, -x.base_score, x.ticker))

    return CompositeReport(trade_date=trade_date, items=items)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_adj(value: float) -> str:
    """Format an adjustment value with color."""
    if value > 0:
        return f"{Fore.GREEN}+{value:.2f}{Style.RESET_ALL}"
    if value < 0:
        return f"{Fore.RED}{value:.2f}{Style.RESET_ALL}"
    return f" {value:.2f}"


def _composite_grade(score: float) -> str:
    """Convert composite score to a letter grade."""
    if score >= 0.7:
        return f"{Fore.GREEN}A{Style.RESET_ALL}"
    if score >= 0.5:
        return f"{Fore.GREEN}B{Style.RESET_ALL}"
    if score >= 0.3:
        return f"{Fore.YELLOW}C{Style.RESET_ALL}"
    if score >= 0.1:
        return f"{Fore.YELLOW}D{Style.RESET_ALL}"
    return f"{Fore.RED}F{Style.RESET_ALL}"


def render_composite_scores(report: CompositeReport) -> str:
    """Render composite confidence scores as a readable table."""
    if not report.items:
        return f"\n{Fore.CYAN}🎯 Composite Confidence Score{Style.RESET_ALL}\n  无推荐数据\n"

    lines = [
        f"\n{Fore.CYAN}🎯 Composite Confidence Score (综合信心评分){Style.RESET_ALL}",
        "  = base + momentum + sector + consistency + volume + trend",
        "",
        f"  {'标的':<8} {'名称':<10} {'Base':>6} {'动量':>6} {'行业':>6} {'一致':>6} {'量价':>6} {'趋势':>6} {'综合':>7} {'等级':>4}",
        f"  {'─' * 8} {'─' * 10} {'─' * 6} {'─' * 6} {'─' * 6} {'─' * 6} {'─' * 6} {'─' * 6} {'─' * 7} {'─' * 4}",
    ]

    for item in report.items:
        grade = _composite_grade(item.composite_score)
        lines.append(f"  {item.ticker:<8} {item.name[:10]:<10} " f"{item.base_score:>6.3f} {_fmt_adj(item.momentum_bonus):>14} " f"{_fmt_adj(item.sector_bonus):>14} {_fmt_adj(item.consistency_adj):>14} " f"{_fmt_adj(item.volume_factor):>14} {_fmt_adj(item.trend_resonance_factor):>14} " f"{item.composite_score:>+7.3f} {grade:>6}")

    # Summary
    a_count = sum(1 for i in report.items if i.composite_score >= 0.7)
    b_count = sum(1 for i in report.items if 0.5 <= i.composite_score < 0.7)
    weak_count = sum(1 for i in report.items if i.composite_score < 0.3)
    lines.append("")
    lines.append(f"  A级(≥0.7): {a_count}  B级(0.5-0.7): {b_count}  " f"低信心(<0.3): {weak_count}  总计: {len(report.items)}")
    return "\n".join(lines)


def render_composite_compact(report: CompositeReport) -> str:
    """Render a compact summary for decision flow integration."""
    if not report.items:
        return "  无综合评分数据"

    lines = [f"  综合信心评分 (Top {min(5, len(report.items))}):"]
    for item in report.items[:5]:
        grade = _composite_grade(item.composite_score)
        lines.append(f"    {item.ticker:<8} {item.name[:8]:<8} " f"综合={item.composite_score:+.3f} {grade}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def run_composite_score(argv: list[str] | None = None) -> int:
    """CLI entry point for --composite-score."""
    top_n = 20
    lookback = 5
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
    report = compute_composite_scores(
        top_n=top_n,
        lookback_days=lookback,
        reports_dir=reports_dir,
    )
    print(render_composite_scores(report))
    return 0
