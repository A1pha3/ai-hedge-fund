"""M1: 因子层归因 (factor contribution × 胜率) — decomposition 解锁.

owner 授权 C (decomposition 因子层归因). 本模块读 tracking_history record 的
``score_decomposition.base_contributions`` (per-strategy T/MR/F/E 贡献),
按各策略贡献分位分组算胜率 → 定位**哪个因子**让高分票输.

**horizon** (C229, 2026-06-28): 默认 ``next_5day_return`` (BUY gate 决策 horizon;
must-win 周期 T+30 → T+5/T+10). 可传 ``next_10day_return`` / ``next_30day_return``
(T+30 保留为长期 invalidation 诊断).

**前置**: main.py _build_auto_screening_payload 需注入 ``score_decomposition``
到 recommendation dict (向后兼容, 旧 records 无 → insufficient 静默).

**数据流**: FusedScore.compute_score_decomposition → recommendation["score_decomposition"]
→ tracking_history record → 本模块读 base_contributions 算 per-factor 单调性.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def _horizon_short_label(horizon_field: str) -> str:
    """next_5day_return → 'T+5'."""
    m = re.search(r"(\d+)", horizon_field)
    return f"T+{m.group(1)}" if m else horizon_field


@dataclass
class FactorContributionWinrate:
    """单个策略因子的贡献分位 × 胜率 (horizon 由报告 horizon_label 标)."""

    strategy: str  # T | MR | F | E | attention | stability | consensus
    high_contrib_winrate: float | None = None  # 贡献高 1/3 的胜率
    low_contrib_winrate: float | None = None  # 贡献低 1/3 的胜率
    high_n: int = 0
    low_n: int = 0
    verdict: str = "insufficient"  # inverted | positive | insufficient


@dataclass
class FactorAttributionReport:
    """per-factor 贡献 × 胜率归因报告 (horizon 默认 T+5, BUY gate 决策 horizon)."""

    factors: list[FactorContributionWinrate] = field(default_factory=list)
    sample_count: int = 0
    verdict: str = "insufficient"  # ok | insufficient
    worst_factor: str | None = None  # 倒挂最严重的因子
    worst_factor_inversion: float | None = None  # low - high (正=倒挂)
    horizon_label: str = "T+5"  # 决策 horizon (C229: 默认 T+5; 可传 next_10day_return / next_30day_return)


def compute_factor_attribution_from_loaded(
    records: list[dict[str, Any]],
    *,
    min_n: int = 15,
    horizon_field: str = "next_5day_return",
) -> FactorAttributionReport:
    """读 score_decomposition.base_contributions, 按 per-factor 贡献分位算胜率.

    horizon_field 默认 ``next_5day_return`` (BUY gate 决策 horizon; 2026-06-28 缩短自 T+30)。

    对每个策略 (T/MR/F/E/attention/stability/consensus):
      - 按该策略贡献排序, 取高 1/3 vs 低 1/3
      - 算两组胜率
      - 如果"贡献高 → 胜率低"(inverted), 该因子可能是倒挂根因
    """
    # 收集有 decomposition + 该 horizon return 的 records
    valid: list[dict[str, Any]] = []
    for rec in records:
        decomp = rec.get("score_decomposition")
        ret = _finite_float(rec.get(horizon_field))
        if decomp is None or ret is None:
            continue
        if not isinstance(decomp, dict):
            continue
        valid.append(rec)

    if len(valid) < min_n * 3:  # 需 3 组 (高/中/低 各 min_n)
        return FactorAttributionReport(sample_count=len(valid), verdict="insufficient")

    base_contribs = valid[0].get("score_decomposition", {}).get("base_contributions", {})
    if not isinstance(base_contribs, dict):
        base_contribs = {}
    strategy_keys = list(base_contribs.keys())
    if not strategy_keys:
        # 尝试其他 decomposition 字段
        for field_name in ("attention_contribution", "stability_bonus", "consensus_bonus"):
            if field_name in valid[0].get("score_decomposition", {}):
                strategy_keys.append(field_name)

    factors: list[FactorContributionWinrate] = []
    worst_factor = None
    worst_inversion = 0.0

    for key in strategy_keys:
        # 按 key 的贡献值排序, 取高/低 1/3
        def _get_contrib(rec: dict[str, Any]) -> float:
            d = rec.get("score_decomposition", {})
            if not isinstance(d, dict):
                return 0.0
            bc = d.get("base_contributions", {})
            if isinstance(bc, dict) and key in bc:
                return float(bc.get(key, 0.0) or 0.0)
            return float(d.get(key, 0.0) or 0.0)

        sorted_recs = sorted(valid, key=_get_contrib)
        third = len(sorted_recs) // 3
        if third < min_n:
            factors.append(FactorContributionWinrate(strategy=key, verdict="insufficient"))
            continue

        low_recs = sorted_recs[:third]
        high_recs = sorted_recs[-third:]

        low_returns = [_finite_float(r.get(horizon_field)) for r in low_recs]
        high_returns = [_finite_float(r.get(horizon_field)) for r in high_recs]
        low_returns = [r for r in low_returns if r is not None]
        high_returns = [r for r in high_returns if r is not None]

        if len(low_returns) < min_n or len(high_returns) < min_n:
            factors.append(FactorContributionWinrate(strategy=key, verdict="insufficient"))
            continue

        low_wr = sum(1 for x in low_returns if x > 0) / len(low_returns)
        high_wr = sum(1 for x in high_returns if x > 0) / len(high_returns)

        inversion = low_wr - high_wr  # 正=倒挂 (贡献高反而胜率低)
        if inversion > 0.05:  # 5pp 以上倒挂
            verdict = "inverted"
        elif high_wr > low_wr + 0.05:
            verdict = "positive"
        else:
            verdict = "insufficient"

        factors.append(FactorContributionWinrate(
            strategy=key,
            high_contrib_winrate=high_wr,
            low_contrib_winrate=low_wr,
            high_n=len(high_returns),
            low_n=len(low_returns),
            verdict=verdict,
        ))

        if inversion > worst_inversion:
            worst_inversion = inversion
            worst_factor = key

    return FactorAttributionReport(
        factors=factors,
        sample_count=len(valid),
        verdict="ok",
        worst_factor=worst_factor if worst_inversion > 0.05 else None,
        worst_factor_inversion=worst_inversion if worst_inversion > 0.05 else None,
        horizon_label=_horizon_short_label(horizon_field),
    )


def render_factor_attribution_line(report: FactorAttributionReport) -> str:
    """渲染 per-factor 归因 (insufficient → 空串).

    展示形如:
      ``  🔍 因子归因: MR 倒挂 (贡献高→胜率低, low 55% vs high 38%, Δ17pp) — MR 因子可能是倒挂根因``
      或 insufficient (旧 records 无 decomposition)
    """
    from src.utils.display import Fore, Style

    if report.verdict == "insufficient":
        return ""

    inverted = [f for f in report.factors if f.verdict == "inverted"]
    hlabel = f"({report.horizon_label})" if report.horizon_label else ""
    if not inverted:
        # 无倒挂因子 (好信号) 或全 insufficient
        ok_factors = [f for f in report.factors if f.verdict != "insufficient"]
        if not ok_factors:
            return ""
        return f"  🔍 因子归因 {hlabel}: 无倒挂因子 ({len(report.factors)} 因子检测, n={report.sample_count}) {__import__('src.utils.display', fromlist=['Fore']).Fore.GREEN}✓{Style.RESET_ALL}"

    parts = []
    for f in inverted:
        delta = (f.low_contrib_winrate or 0) - (f.high_contrib_winrate or 0)
        parts.append(
            f"{f.strategy} low {(f.low_contrib_winrate or 0):.0%} vs high {(f.high_contrib_winrate or 0):.0%} (Δ{delta:.0%})"
        )

    worst = f.report_worst_factor() if hasattr(f, 'report_worst_factor') else None
    suffix = ""
    if report.worst_factor:
        suffix = f" {Fore.RED}— {report.worst_factor} 因子可能是倒挂根因{Style.RESET_ALL}"

    return f"  🔍 因子归因 {hlabel}: {'; '.join(parts)}{suffix}"


__all__ = [
    "FactorContributionWinrate",
    "FactorAttributionReport",
    "compute_factor_attribution_from_loaded",
    "render_factor_attribution_line",
]
