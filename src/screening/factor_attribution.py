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

import random as _random
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


def _bootstrap_inversion_ci(
    high_returns: list[float],
    low_returns: list[float],
    *,
    n_bootstrap: int,
    ci_level: float,
    seed: int,
) -> tuple[float | None, float | None]:
    """纯函数: bootstrap percentile CI on the inversion point estimate.

    inversion = low_winrate - high_winrate (正=倒挂). 我们 bootstrap 重采样
    high/low 两组各自有放回 n 次, 算每次重采样的 inversion, 取 percentile 区间.

    Returns:
      (ci_lower, ci_upper): 倒挂点估计的 CI; 都为 None 仅当某组为空.
      幂等: 同 seed + 同 input → 同 output (用独立 Random 实例).
    """
    n_high, n_low = len(high_returns), len(low_returns)
    if n_high == 0 or n_low == 0:
        return None, None
    high_wins = [1 if r > 0 else 0 for r in high_returns]
    low_wins = [1 if r > 0 else 0 for r in low_returns]
    rng = _random.Random(seed)  # 独立 PRNG, 不污染全局 random 状态
    boot_inversions: list[float] = []
    # c343/autodev-36: rng.choices (C-level batch) is 5x faster than randrange loop.
    # (c342 missed this file — family-tree audit lesson from c321 re-applied.)
    for _ in range(n_bootstrap):
        h_wr = sum(rng.choices(high_wins, k=n_high)) / n_high
        l_wr = sum(rng.choices(low_wins, k=n_low)) / n_low
        boot_inversions.append(l_wr - h_wr)  # 正=倒挂
    boot_inversions.sort()
    alpha = 1.0 - ci_level
    lower_idx = max(0, int(alpha / 2 * n_bootstrap))
    upper_idx = min(n_bootstrap - 1, int((1 - alpha / 2) * n_bootstrap))
    return boot_inversions[lower_idx], boot_inversions[upper_idx]


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
    verdict: str = "insufficient"  # inverted | inverted_noisy | positive | insufficient
    # 倒挂点估计 (low - high, 正=倒挂) + bootstrap percentile CI (c317).
    # 小 n (默认 tertile≈15) 时 winrate SE≈13pp, 5pp 硬阈值倒挂完全可能是
    # 噪声; CI 让 owner 区分 "真倒挂" vs "CI 跨 0 不可排除噪声" 再决定是否
    # 重平衡因子权重 (因子权重是 owner-only 决策, 见 autodev-contract).
    inversion: float | None = None
    inversion_ci_low: float | None = None
    inversion_ci_high: float | None = None


@dataclass
class FactorAttributionReport:
    """per-factor 贡献 × 胜率归因报告 (horizon 默认 T+5, BUY gate 决策 horizon)."""

    factors: list[FactorContributionWinrate] = field(default_factory=list)
    sample_count: int = 0
    verdict: str = "insufficient"  # ok | insufficient
    worst_factor: str | None = None  # 倒挂最严重的因子
    worst_factor_inversion: float | None = None  # low - high (正=倒挂)
    horizon_label: str = "T+5"  # 决策 horizon (C229: 默认 T+5; 可传 next_10day_return / next_30day_return)
    # c326/autodev-36: 数据时点 — 镜像 factor_attribution_by_state c325 模式
    as_of: str | None = None


def compute_factor_attribution_from_loaded(
    records: list[dict[str, Any]],
    *,
    min_n: int = 15,
    horizon_field: str = "next_5day_return",
    n_bootstrap: int = 2000,
    ci_level: float = 0.95,
    seed: int = 42,
) -> FactorAttributionReport:
    """读 score_decomposition.base_contributions, 按 per-factor 贡献分位算胜率.

    horizon_field 默认 ``next_5day_return`` (BUY gate 决策 horizon; 2026-06-28 缩短自 T+30)。

    对每个策略 (T/MR/F/E/attention/stability/consensus):
      - 按该策略贡献排序, 取高 1/3 vs 低 1/3
      - 算两组胜率
      - 如果"贡献高 → 胜率低"(inverted), 该因子可能是倒挂根因

    c317 (loop 49): 每个 inverted 因子附 bootstrap percentile CI on the inversion.
    小 n (tertile≈15) 时 winrate SE≈13pp, 5pp 硬阈值倒挂完全可能是噪声 — CI 让
    owner 在重平衡因子权重 (owner-only) 前区分 "真倒挂" vs "噪声". 见 c297 method
    lesson (bootstrap CI 在 R6 winrate 问题上决策关键).
    """
    # 收集有 decomposition + 该 horizon return 的 records
    valid: list[dict[str, Any]] = []
    max_date = ""
    for rec in records:
        decomp = rec.get("score_decomposition")
        ret = _finite_float(rec.get(horizon_field))
        if decomp is None or ret is None:
            continue
        if not isinstance(decomp, dict):
            continue
        valid.append(rec)
        d = str(rec.get("recommended_date", "") or "").strip()
        if d > max_date:
            max_date = d

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

    # 真实性 (c317): base_contributions 空 + 无 fallback → 无因子可分析, 必须
    # insufficient. 修复前这里返回 verdict='ok' + 空 factors 列表, 误导调用者
    # 以为分析成功 (审计发现: 同型 NS-17 'misleading ok' 病).
    if not strategy_keys:
        return FactorAttributionReport(
            sample_count=len(valid),
            verdict="insufficient",
            horizon_label=_horizon_short_label(horizon_field),
        )

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
        # c317: bootstrap CI on the inversion (决定倒挂是否可信)
        ci_low, ci_high = _bootstrap_inversion_ci(
            high_returns, low_returns,
            n_bootstrap=n_bootstrap, ci_level=ci_level, seed=seed,
        )
        # CI 跨 0 → 不能排除 inversion=0 (无倒挂), 即使点估计 >5pp
        ci_straddles_zero = (
            ci_low is not None and ci_high is not None
            and ci_low < 0.0 < ci_high
        )
        if inversion > 0.05 and ci_straddles_zero:
            verdict = "inverted_noisy"  # 倒挂但 CI 含 0 — 不可据 noise 重平衡
        elif inversion > 0.05:  # 5pp 以上倒挂 + CI 不含 0
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
            inversion=inversion,
            inversion_ci_low=ci_low,
            inversion_ci_high=ci_high,
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
        as_of=max_date or None,
    )


def render_factor_attribution_line(report: FactorAttributionReport) -> str:
    """渲染 per-factor 归因 (insufficient → 空串).

    展示形如:
      ``  🔍 因子归因 (T+5): MR 倒挂 low 55% vs high 38% (Δ17pp, CI[+3%, +30%]) — MR 因子可能是倒挂根因``
      倒挂但 CI 跨 0 (inverted_noisy) 时标 "⚠噪声", 提醒 owner 勿据噪声重平衡:
      ``  🔍 因子归因 (T+5): MR ⚠噪声倒挂 low 53% vs high 40% (Δ13pp, CI[-5%, +30%])``
      或 insufficient (旧 records 无 decomposition)
    """
    from src.utils.display import Fore, Style

    if report.verdict == "insufficient":
        return ""

    # c317: noisy inversions 也要展示 (标噪声), 让 owner 看见但不据此行动.
    flagged = [
        f for f in report.factors
        if f.verdict in ("inverted", "inverted_noisy")
    ]
    hlabel = f"({report.horizon_label})" if report.horizon_label else ""
    if not flagged:
        # 无倒挂因子 (好信号) 或全 insufficient
        ok_factors = [f for f in report.factors if f.verdict != "insufficient"]
        if not ok_factors:
            return ""
        as_of_suffix_clean = f" | 数据时点 {report.as_of}" if report.as_of else ""
        return f"  🔍 因子归因 {hlabel}: 无倒挂因子 ({len(report.factors)} 因子检测, n={report.sample_count}){as_of_suffix_clean} {Fore.GREEN}✓{Style.RESET_ALL}"

    parts = []
    for f in flagged:
        delta = (f.low_contrib_winrate or 0) - (f.high_contrib_winrate or 0)
        label = "⚠噪声倒挂" if f.verdict == "inverted_noisy" else "倒挂"
        ci_str = ""
        if f.inversion_ci_low is not None and f.inversion_ci_high is not None:
            ci_str = f", CI[{f.inversion_ci_low:+.0%}, {f.inversion_ci_high:+.0%}]"
        # c333/autodev-36: n 之前 computed-but-unrendered; 镜像 factor_attribution_by_state c332
        total_n = f.high_n + f.low_n
        n_str = f", n={total_n}" if total_n > 0 else ""
        parts.append(
            f"{f.strategy} {label} low {(f.low_contrib_winrate or 0):.0%} vs high {(f.high_contrib_winrate or 0):.0%} (Δ{delta:.0%}{ci_str}{n_str})"
        )

    suffix = ""
    if report.worst_factor:
        suffix = f" {Fore.RED}— {report.worst_factor} 因子可能是倒挂根因{Style.RESET_ALL}"

    # c326/autodev-36: 数据时点披露
    as_of_suffix = f" | 数据时点 {report.as_of}" if report.as_of else ""

    return f"  🔍 因子归因 {hlabel}: {'; '.join(parts)}{suffix}{as_of_suffix}"


__all__ = [
    "FactorContributionWinrate",
    "FactorAttributionReport",
    "compute_factor_attribution_from_loaded",
    "render_factor_attribution_line",
]
