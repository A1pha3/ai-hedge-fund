"""Q-4 相关性仓位折减 — when BUY picks overlap, discount combined position.

R145 sizes each pick independently; P-4 flags industry concentration by count.
But two BUY picks in the same industry at high effective correlation ≠ two
independent bets — the combined position exceeds the intended risk budget. This
module computes a per-pick **discount factor** (0,1] from a correlation proxy,
so R145's position suggestion can be scaled down for overlapping picks.

Correlation proxy (no correlation matrix needed):
  - **industry overlap** (weight ``_W_INDUSTRY``): same industry_sw → +0.6
  - **score proximity** (weight ``_W_SCORE``): |Δscore_b| small → +up to 0.4
  - capped at 1.0

Discount: for each pick, find its max correlation with any OTHER pick; discount
factor = 1 - max_corr × ``_DISCOUNT_STRENGTH`` (bounded (0,1]).

设计原则:
  - **proxy 非精确相关** — 文档化 (true correlation 需收益率序列; 此处用行业 +
    分数邻近作 risk-overlap 代理, 适合 "同涨同跌" 的直观风险)
  - **per-pick factor** — 供 R145 ``_suggest_position_pct`` 乘以; 折减最高的 pick
  - **纯展示 + factor** — 不自动改 BUY 门控, 只标 ⚠ 并给 factor

CLI: ``--top-picks`` 当多只 BUY 相关时 footer 展示 ⚠ + 折减建议。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.utils.display import Fore, Style

#: industry-overlap 权重 (same industry → +0.6 correlation contribution)
_W_INDUSTRY: float = 0.6
#: score-proximity 权重 (|Δscore|→0 maps to +0.4; 完全无关分数 → +0)
_W_SCORE: float = 0.4
#: score 邻近的尺度 (|Δscore| 超过此值视为分数不邻近)
_SCORE_PROXIMITY_SCALE: float = 0.3
#: 折减强度 (max_corr=1.0 → 折减到此 factor; 0.5 → 半折减)
_DISCOUNT_STRENGTH: float = 0.5
#: 标 ⚠ 的 pair 相关阈值
_OVERLAP_WARN_THRESHOLD: float = 0.6

_UNKNOWN_INDUSTRIES: frozenset[str] = frozenset({"", "未知", "unknown", "none", "—"})


@dataclass
class CorrelationDiscountReport:
    """组合内 BUY pick 的相关性仓位折减。"""

    #: ticker → discount factor (0,1]; 1.0 = 无折减 (独立 pick)
    per_pick_discount: dict[str, float] = field(default_factory=dict)
    #: 最高 pair 相关度 (None = <2 picks)
    max_pair_correlation: float | None = None
    overlap_warning: bool = False
    #: 超阈值的 (ticker_a, ticker_b, correlation) 列表
    correlated_pairs: list[tuple[str, str, float]] = field(default_factory=list)


def _correlation_proxy(pick_a: dict[str, Any], pick_b: dict[str, Any]) -> float:
    """两 pick 的相关度代理 (industry overlap + score proximity), [0, 1]。

    同行业 → +0.6; 分数邻近 (|Δscore| 小) → +最多 0.4; capped at 1.0。
    """
    ind_a = str(pick_a.get("industry_sw", "") or "").strip()
    ind_b = str(pick_b.get("industry_sw", "") or "").strip()
    industry_known = bool(ind_a) and ind_a.lower() not in _UNKNOWN_INDUSTRIES
    industry_contribution = _W_INDUSTRY if (industry_known and ind_a == ind_b) else 0.0

    try:
        score_a = float(pick_a.get("score_b", 0.0) or 0.0)
        score_b = float(pick_b.get("score_b", 0.0) or 0.0)
    except (TypeError, ValueError):
        score_a = score_b = 0.0
    delta = abs(score_a - score_b)
    # proximity: Δ=0 → full _W_SCORE; Δ>=scale → 0; linear between
    proximity = max(0.0, 1.0 - delta / _SCORE_PROXIMITY_SCALE) * _W_SCORE

    return min(1.0, industry_contribution + proximity)


def compute_correlation_discount(
    picks: list[dict[str, Any]],
) -> CorrelationDiscountReport:
    """计算组合内每只 BUY pick 的相关性仓位折减 factor。

    Args:
        picks: BUY 推荐 dict 列表 (读 ``ticker`` / ``industry_sw`` / ``score_b``)

    Returns:
        :class:`CorrelationDiscountReport` (<2 picks → 无 pair, factor 全 1.0)
    """
    report = CorrelationDiscountReport()
    if not picks:
        return report

    tickers = [str(p.get("ticker", "") or "") for p in picks]
    # per-pick max correlation with any other pick
    max_corr_per_pick: dict[str, float] = {t: 0.0 for t in tickers}
    max_pair: float | None = None
    correlated_pairs: list[tuple[str, str, float]] = []

    for i in range(len(picks)):
        for j in range(i + 1, len(picks)):
            corr = _correlation_proxy(picks[i], picks[j])
            ta, tb = tickers[i], tickers[j]
            if corr > max_corr_per_pick.get(ta, 0.0):
                max_corr_per_pick[ta] = corr
            if corr > max_corr_per_pick.get(tb, 0.0):
                max_corr_per_pick[tb] = corr
            if max_pair is None or corr > max_pair:
                max_pair = corr
            if corr >= _OVERLAP_WARN_THRESHOLD:
                correlated_pairs.append((ta, tb, round(corr, 3)))

    # discount factor per pick: 1 - max_corr × strength, bounded (0,1]
    for t, mc in max_corr_per_pick.items():
        factor = max(0.01, 1.0 - mc * _DISCOUNT_STRENGTH)
        report.per_pick_discount[t] = round(factor, 3)

    report.max_pair_correlation = round(max_pair, 3) if max_pair is not None else None
    report.correlated_pairs = correlated_pairs
    report.overlap_warning = bool(correlated_pairs)
    return report


def render_correlation_note(report: CorrelationDiscountReport) -> str:
    """渲染相关性折减提示 (无重叠 → 空串)。"""
    if not report.per_pick_discount:
        return ""
    if not report.overlap_warning or not report.correlated_pairs:
        return ""
    pairs_str = ", ".join(f"{a}↔{b} ({c:.2f})" for a, b, c in report.correlated_pairs[:3])
    # show the most-discounted picks
    discounted = sorted(
        ((t, f) for t, f in report.per_pick_discount.items() if f < 1.0),
        key=lambda kv: kv[1],
    )[:3]
    disc_str = ", ".join(f"{t}×{f:.2f}" for t, f in discounted)
    return f"  {Fore.CYAN}🔗 相关性仓位折减:{Style.RESET_ALL} " f"{Fore.RED}⚠ 高相关对: {pairs_str}{Style.RESET_ALL}  " f"→ 建议折减 {disc_str} (同行业/分数邻近 ≠ 独立 bet)"


__all__ = [
    "CorrelationDiscountReport",
    "compute_correlation_discount",
    "render_correlation_note",
]
