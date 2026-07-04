"""P3-2: 策略动态权重校准 — 基于因子 IC 自动调整策略权重。

P1-4 (factor_ic_analysis) 已实现因子 IC 评估。
P3-2 在此基础上增加"权重校准"功能:
  - 收集各策略名下的因子 IC 历史
  - 构造"按策略"汇总的 IC mean / IR 指标
  - 校准权重 ∝ max(0, IR) (非负且放大有效信号)
  - 归一化到 sum = 1.0
  - 输出校准前后对比

设计原则:
  - **纯函数** — 无网络 / 数据库依赖, 测试可注入合成数据
  - **降级友好** — IC 数据不足时返回默认等权 (0.25 each)
  - **保守校准** — 用 IR 而非 IC mean (更稳健, 避免高方差因子权重虚高)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.research.factor_ic_analysis import (
    compute_factor_ic,
    FactorICResult,
)
from src.screening.models import DEFAULT_STRATEGY_WEIGHTS

logger = logging.getLogger(__name__)

#: 默认等权权重 (P3-2 校准数据不足时使用)
DEFAULT_EQUAL_WEIGHTS: dict[str, float] = {
    "trend": 0.25,
    "mean_reversion": 0.25,
    "fundamental": 0.25,
    "event_sentiment": 0.25,
}

#: 校准的最小 IC 序列长度 (低于此值跳过校准, 保持默认)
MIN_OBSERVATIONS_FOR_CALIBRATION = 5

#: 校准公式: weight ∝ max(0, IR)^alpha (alpha=1.0 为线性, alpha=2.0 偏激)
CALIBRATION_ALPHA: float = 1.0

#: 权重下限 (避免某个策略权重为 0 完全失效)
WEIGHT_FLOOR: float = 0.05


@dataclass
class StrategyICSummary:
    """一个策略名下的因子 IC 汇总。

    Attributes:
        strategy_name: 策略名 (trend / mean_reversion / fundamental / event_sentiment)
        factor_count: 该策略下的因子数
        avg_ic: 因子 IC mean 的平均
        avg_ir: 因子 IR 的平均
        n_periods: 总观测期数 (取该策略下最少的)
    """

    strategy_name: str = ""
    factor_count: int = 0
    avg_ic: float = 0.0
    avg_ir: float = 0.0
    n_periods: int = 0


@dataclass
class WeightCalibrationResult:
    """权重校准结果。

    Attributes:
        lookback_days: 回溯天数
        original_weights: 校准前权重 (默认权重)
        calibrated_weights: 校准后权重
        strategy_summaries: 策略级 IC 汇总列表
        n_factors: 总因子数
        n_observations: 实际观测期数
        calibration_skipped: 是否跳过校准 (因数据不足)
    """

    lookback_days: int = 30
    original_weights: dict[str, float] = field(default_factory=dict)
    calibrated_weights: dict[str, float] = field(default_factory=dict)
    strategy_summaries: list[StrategyICSummary] = field(default_factory=list)
    n_factors: int = 0
    n_observations: int = 0
    calibration_skipped: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _infer_strategy(factor_name: str) -> str:
    """推断因子所属策略 (前缀匹配)。"""
    if not factor_name or "." not in factor_name:
        return "unknown"
    prefix = factor_name.split(".", 1)[0].strip().lower()
    valid = set(DEFAULT_STRATEGY_WEIGHTS.keys())
    return prefix if prefix in valid else "unknown"


def _aggregate_strategy_ic(
    factor_results: dict[str, FactorICResult],
) -> list[StrategyICSummary]:
    """按策略聚合因子 IC 结果。"""
    by_strategy: dict[str, list[FactorICResult]] = {}
    for fname, res in factor_results.items():
        strat = _infer_strategy(fname)
        if strat == "unknown":
            continue
        by_strategy.setdefault(strat, []).append(res)

    summaries: list[StrategyICSummary] = []
    for strat, results in by_strategy.items():
        if not results:
            continue
        avg_ic = sum(r.ic_mean for r in results) / len(results)
        avg_ir = sum(r.ir for r in results) / len(results)
        n_periods = min((r.n_periods for r in results), default=0)
        summaries.append(
            StrategyICSummary(
                strategy_name=strat,
                factor_count=len(results),
                avg_ic=avg_ic,
                avg_ir=avg_ir,
                n_periods=n_periods,
            )
        )
    summaries.sort(key=lambda s: s.avg_ir, reverse=True)
    return summaries


def _calibrate_weights(
    summaries: list[StrategyICSummary],
    original_weights: dict[str, float],
) -> dict[str, float]:
    """从策略 IR 推导校准权重。

    公式: weight_i ∝ max(0, IR_i)^alpha, 归一化到 sum = 1.0, 再把
    低于 WEIGHT_FLOOR 的策略提升到 floor 并按比例缩放其余策略。

    BH-027: WEIGHT_FLOOR 此前在归一化**前**施加 (raw 阶段), 一个高 IR
    策略会把 floored 策略归一化后压到远低于 floor (例: IR=3.0 让其它
    策略落到 0.016 < 0.05), 违背模块"保守校准 / 避免某策略权重为 0
    完全失效"契约。修复: 先归一化, 再投影到 [floor, 1.0] 下界, 然后
    从仍有余量的策略里扣回被 floor 占用的预算, 保持 sum = 1.0。
    """
    raw: dict[str, float] = {}
    for strat in original_weights:
        # Find IR for this strategy. No-data strategies are treated the
        # same as zero-signal strategies (IR=0 → raw 0.0), so the
        # post-normalization floor applies uniformly to both.
        match = next((s for s in summaries if s.strategy_name == strat), None)
        ir = match.avg_ir if match is not None else 0.0
        raw[strat] = max(0.0, ir) ** CALIBRATION_ALPHA

    total = sum(raw.values())
    if total <= 0:
        # All strategies have no positive signal → equal weight.
        equal = 1.0 / len(original_weights)
        return {strat: equal for strat in original_weights}

    # First-pass normalization, then enforce WEIGHT_FLOOR as a true lower
    # bound by projecting any sub-floor weight up to the floor and
    # absorbing the deficit from the remaining (above-floor) strategies.
    normalized = {strat: value / total for strat, value in raw.items()}
    return _enforce_weight_floor(normalized, WEIGHT_FLOOR)


def _enforce_weight_floor(
    weights: dict[str, float],
    floor: float,
) -> dict[str, float]:
    """Project ``weights`` onto the simplex where every entry is >= floor.

    BH-027: makes WEIGHT_FLOOR a genuine post-normalization lower bound.
    Iteratively lifts sub-floor weights to the floor and absorbs the
    budget deficit from the strategies still above the floor, renormalizing
    until the constraint is satisfied or no donor budget remains. When no
    donor budget is available (every strategy would be floored), fall back
    to uniform weights — the floor is a *minimum*, not a guarantee that
    strong strategies can always retain their excess when too many
    strategies demand the floor.
    """
    n = len(weights)
    if n == 0:
        return {}
    # If even uniform weights violate the floor, the floor is infeasible
    # for this many strategies; clamp the effective floor to uniform.
    uniform = 1.0 / n
    effective_floor = min(floor, uniform)
    result = dict(weights)
    for _ in range(n + 1):  # converges in at most n iterations
        below = {k: v for k, v in result.items() if v < effective_floor - 1e-12}
        if not below:
            break
        deficit = sum(effective_floor - v for v in below.values())
        for k in below:
            result[k] = effective_floor
        donors = {k: v for k, v in result.items() if v > effective_floor + 1e-12}
        donor_total = sum(donors.values())
        if donor_total <= 0:
            # No donor budget — uniform is the only feasible solution.
            return {k: uniform for k in result}
        # Absorb the deficit proportionally from donors.
        for k, v in donors.items():
            result[k] = v - deficit * (v / donor_total)
    # Final renormalization guards against floating-point drift.
    total = sum(result.values())
    if total > 0:
        result = {k: v / total for k, v in result.items()}
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_weight_calibration(
    *,
    factor_history: dict[str, list[float]],
    return_history: list[float],
    lookback_days: int = 30,
    method: str = "spearman",
) -> WeightCalibrationResult:
    """主入口: 计算策略权重校准。

    Args:
        factor_history: ``{factor_name: [value_per_period]}`` — 来自 factor_ic_analysis
        return_history: 下期收益序列
        lookback_days: 回溯天数 (用于报告)
        method: IC 计算方法 ("spearman" | "pearson")

    Returns:
        WeightCalibrationResult
    """
    result = WeightCalibrationResult(
        lookback_days=lookback_days,
        original_weights=DEFAULT_STRATEGY_WEIGHTS.copy(),
    )

    if not factor_history or not return_history:
        result.calibrated_weights = DEFAULT_STRATEGY_WEIGHTS.copy()
        result.calibration_skipped = True
        return result

    # Compute IC for each factor
    factor_results = compute_factor_ic(factor_history, return_history, method=method)

    if not factor_results:
        result.calibrated_weights = DEFAULT_STRATEGY_WEIGHTS.copy()
        result.calibration_skipped = True
        return result

    result.n_factors = len(factor_results)
    result.n_observations = min((r.n_periods for r in factor_results.values()), default=0)

    # Aggregate by strategy
    summaries = _aggregate_strategy_ic(factor_results)
    result.strategy_summaries = summaries

    if result.n_observations < MIN_OBSERVATIONS_FOR_CALIBRATION:
        logger.info(
            "[WeightCalibration] 观测期数 %d < %d, 跳过校准",
            result.n_observations,
            MIN_OBSERVATIONS_FOR_CALIBRATION,
        )
        result.calibrated_weights = DEFAULT_STRATEGY_WEIGHTS.copy()
        result.calibration_skipped = True
        return result

    # Calibrate
    result.calibrated_weights = _calibrate_weights(summaries, DEFAULT_STRATEGY_WEIGHTS)
    return result


# ---------------------------------------------------------------------------
# CLI rendering
# ---------------------------------------------------------------------------


def render_weight_calibration(result: WeightCalibrationResult) -> str:
    """ASCII 渲染权重校准结果。"""
    lines: list[str] = []
    lines.append("━" * 70)
    lines.append(f"  策略权重校准 (P3-2) · 近 {result.lookback_days} 天")
    lines.append("━" * 70)
    lines.append("")

    if result.calibration_skipped:
        lines.append(f"  ⚠ 校准跳过 — {result.n_observations} < {MIN_OBSERVATIONS_FOR_CALIBRATION} 期观测")
        lines.append("  沿用默认权重")
    else:
        lines.append(f"  因子数: {result.n_factors}  |  观测期: {result.n_observations}")
        lines.append("")

        lines.append("  策略 IC 汇总 (按 IR 降序):")
        lines.append(f"  {'策略':<20} {'因子数':>5} {'avg IC':>8} {'avg IR':>8}")
        lines.append("  " + "-" * 50)
        for s in result.strategy_summaries:
            lines.append(f"  {s.strategy_name:<20} {s.factor_count:>5} {s.avg_ic:>+8.4f} {s.avg_ir:>+8.4f}")
        lines.append("")

    lines.append("  权重对比 (校准前 → 校准后):")
    lines.append(f"  {'策略':<20} {'原权重':>8} {'校准后':>8} {'Δ':>8}")
    lines.append("  " + "-" * 50)
    for strat in result.original_weights:
        orig = result.original_weights[strat]
        cal = result.calibrated_weights.get(strat, orig)
        delta = cal - orig
        delta_str = f"{delta:+.3f}"
        lines.append(f"  {strat:<20} {orig:>8.3f} {cal:>8.3f} {delta_str:>8}")

    # BH-027 follow-up: surface which strategies are held at WEIGHT_FLOOR by
    # the post-normalization floor projection. A weight exactly at the floor
    # is a *conservative floor*, not an IR-driven signal — without this note
    # the user cannot tell "5% because IR≈0" from "5% because the floor held
    # it there", which matters for trusting a dominating strategy's 85%.
    if not result.calibration_skipped:
        floored = sorted(strat for strat, w in result.calibrated_weights.items() if abs(w - WEIGHT_FLOOR) < 1e-9)
        if floored:
            names = "、".join(floored)
            lines.append("")
            lines.append(f"  ⓘ 下限保护 ({WEIGHT_FLOOR:g})：{names} 命中保守下限，" "非 IR 驱动；主导策略权重据此被压缩。")

    lines.append("━" * 70)
    return "\n".join(lines)
