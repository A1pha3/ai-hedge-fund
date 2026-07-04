"""Isotonic calibration — 纯函数模块 (R-5.C).

R-5.C 第 2/4 项: 在 bucket median 上拟合保序映射让预测中位数逼近实际中位数.
PAV (Pool Adjacent Violators) 算法, 无 sklearn 依赖, 可注入测试.

纯展示层, 不改推荐门控/排序/BUY 逻辑.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

#: bucket 样本数低于此值时标记"证据不足"不强行校准 (R-5.C 第 4 项)
MIN_BUCKET_SAMPLES: int = 20


@dataclass(frozen=True)
class IsotonicModel:
    """Isotonic 校准模型 — 保序映射.

    Attributes:
        breakpoints: 输入 x 的断点 (排序后的 unique x)
        values: 对应的 isotonic 校准后 y 值 (单调递增)
        insufficient: 样本不足时为 True, apply 时返回 None
    """

    breakpoints: tuple[float, ...]
    values: tuple[float, ...]
    insufficient: bool = False

    def apply(self, x: float) -> float | None:
        """对单个 x 值应用 isotonic 校准.

        线性插值: x < breakpoints[0] → values[0]; x > breakpoints[-1] → values[-1];
        中间值线性插值. insufficient 模型返回 None.
        """
        if self.insufficient or not self.breakpoints:
            return None
        if x <= self.breakpoints[0]:
            return self.values[0]
        if x >= self.breakpoints[-1]:
            return self.values[-1]
        # 线性插值
        for i in range(len(self.breakpoints) - 1):
            if self.breakpoints[i] <= x <= self.breakpoints[i + 1]:
                x0, x1 = self.breakpoints[i], self.breakpoints[i + 1]
                y0, y1 = self.values[i], self.values[i + 1]
                if x1 == x0:
                    return y0
                return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        return self.values[-1]


def pool_adjacent_violators(xs: Sequence[float], ys: Sequence[float]) -> list[float]:
    """PAV 算法 — 把 ys 调整为单调递增.

    输入: xs (已排序), ys (可能违反单调性)
    输出: 校准后的 ys (单调递增, 与 xs 一一对应)

    算法: 从左到右扫描, 如果当前 pool 的值 > 新值 (违反递增),
    则 pool 合并取加权平均, 继续向左检查.
    """
    if len(xs) != len(ys):
        raise ValueError("xs and ys must have same length")
    if not ys:
        return []
    if len(ys) == 1:
        return [float(ys[0])]

    # 用 (value, weight) 表示每个 pool, weight = pool 中的样本数
    pools: list[tuple[float, int]] = [(float(ys[0]), 1)]
    for i in range(1, len(ys)):
        y = float(ys[i])
        w = 1
        # 如果当前 pool 的值 > 新值 (违反递增), 合并
        while pools and pools[-1][0] > y:
            prev_y, prev_w = pools.pop()
            total_w = prev_w + w
            y = (prev_y * prev_w + y * w) / total_w
            w = total_w
        pools.append((y, w))

    # 展开 pools 回到与输入等长的列表
    result: list[float] = []
    for y, w in pools:
        result.extend([y] * w)
    return result


def fit_isotonic(
    xs: Sequence[float],
    ys: Sequence[float],
    min_samples: int = MIN_BUCKET_SAMPLES,
) -> IsotonicModel:
    """拟合 isotonic 校准模型.

    Args:
        xs: 输入 score (bucket center 或 raw score)
        ys: 目标值 (bucket t30_median_return)
        min_samples: 总样本数低于此值时标记 insufficient

    Returns:
        IsotonicModel — apply() 返回校准后的预测值
    """
    if len(xs) != len(ys):
        raise ValueError("xs and ys must have same length")
    if len(xs) < min_samples:
        return IsotonicModel(breakpoints=(), values=(), insufficient=True)

    # 按 x 排序
    pairs = sorted(zip(xs, ys))
    sorted_xs = [float(x) for x, _ in pairs]
    sorted_ys = [float(y) for _, y in pairs]

    # PAV 校准
    calibrated = pool_adjacent_violators(sorted_xs, sorted_ys)

    # 合并相同 x 的点 (取平均)
    unique_xs: list[float] = []
    unique_ys: list[float] = []
    for x, y in zip(sorted_xs, calibrated):
        if unique_xs and unique_xs[-1] == x:
            unique_ys[-1] = (unique_ys[-1] + y) / 2
        else:
            unique_xs.append(x)
            unique_ys.append(y)

    return IsotonicModel(
        breakpoints=tuple(unique_xs),
        values=tuple(unique_ys),
        insufficient=False,
    )


def apply_isotonic(model: IsotonicModel, xs: Sequence[float]) -> list[float | None]:
    """对一组 x 值应用 isotonic 校准.

    Returns:
        校准后的 y 值列表, insufficient 模型返回 [None, ...]
    """
    return [model.apply(x) for x in xs]


def is_bucket_insufficient(sample_count: int, min_samples: int = MIN_BUCKET_SAMPLES) -> bool:
    """判断 bucket 样本是否不足 (R-5.C 第 4 项).

    Args:
        sample_count: bucket 的 t30 样本数
        min_samples: 最低样本数阈值 (默认 20)

    Returns:
        True if sample_count < min_samples
    """
    return sample_count < min_samples
