"""TDD for isotonic_calibration — R-5.C 纯函数模块.

RED→GREEN: PAV 算法 + isotonic fit/apply + insufficient bucket.
R-5.C 第 2/4 项: isotonic 单调校准 + n<20 诚实标注.
"""
from __future__ import annotations

import pytest

from src.screening.isotonic_calibration import (
    MIN_BUCKET_SAMPLES,
    IsotonicModel,
    apply_isotonic,
    fit_isotonic,
    is_bucket_insufficient,
    pool_adjacent_violators,
)


class TestPoolAdjacentViolators:
    """PAV 算法 — 把 ys 调整为单调递增."""

    def test_already_monotonic_increasing_unchanged(self) -> None:
        """已单调递增的 ys 不变."""
        ys = pool_adjacent_violators([1, 2, 3, 4], [1, 2, 3, 4])
        assert ys == [1.0, 2.0, 3.0, 4.0]

    def test_single_violation_pooled(self) -> None:
        """违反单调性: [1, 3, 2] → [1, 2.5, 2.5]."""
        ys = pool_adjacent_violators([1, 2, 3], [1, 3, 2])
        assert ys == [1.0, 2.5, 2.5]

    def test_decreasing_sequence_pooled_to_constant(self) -> None:
        """完全递减: [3, 2, 1] → [2, 2, 2] (全 pool)."""
        ys = pool_adjacent_violators([1, 2, 3], [3, 2, 1])
        assert ys == [2.0, 2.0, 2.0]

    def test_multiple_violations_monotonic_result(self) -> None:
        """多次违反: 结果必须单调递增."""
        ys = pool_adjacent_violators([1, 2, 3, 4, 5], [5, 1, 3, 2, 4])
        # PAV 保证输出单调递增 (非严格)
        assert all(ys[i] <= ys[i + 1] + 1e-9 for i in range(len(ys) - 1))
        assert len(ys) == 5

    def test_empty_input(self) -> None:
        ys = pool_adjacent_violators([], [])
        assert ys == []

    def test_single_point(self) -> None:
        ys = pool_adjacent_violators([1], [5])
        assert ys == [5.0]

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            pool_adjacent_violators([1, 2], [1])


class TestFitIsotonic:
    """fit_isotonic — 拟合 isotonic 校准模型."""

    def test_known_monotonic_mapping_recovered(self) -> None:
        """已知单调映射 f(x)=2x 可复原."""
        xs = [1, 2, 3, 4, 5]
        ys = [2, 4, 6, 8, 10]
        model = fit_isotonic(xs, ys, min_samples=1)
        assert not model.insufficient
        assert abs(model.apply(3) - 6) < 0.01

    def test_violation_corrected(self) -> None:
        """违反单调性被修正: [1, 3, 2] → isotonic 后 apply(2) ≈ 2.5."""
        xs = [1, 2, 3]
        ys = [1, 3, 2]
        model = fit_isotonic(xs, ys, min_samples=1)
        assert not model.insufficient
        assert abs(model.apply(2) - 2.5) < 0.01

    def test_insufficient_samples(self) -> None:
        """样本不足时标记 insufficient."""
        xs = [1, 2, 3]
        ys = [1, 2, 3]
        model = fit_isotonic(xs, ys, min_samples=20)
        assert model.insufficient
        assert model.apply(2) is None

    def test_empty_input_insufficient(self) -> None:
        model = fit_isotonic([], [], min_samples=1)
        assert model.insufficient
        assert model.apply(1) is None

    def test_extrapolation_clamped(self) -> None:
        """超出范围的 x 被 clamp 到边界值."""
        xs = [1, 2, 3]
        ys = [10, 20, 30]
        model = fit_isotonic(xs, ys, min_samples=1)
        assert model.apply(0) == 10
        assert model.apply(5) == 30

    def test_linear_interpolation(self) -> None:
        """中间值线性插值."""
        xs = [1, 3]
        ys = [10, 30]
        model = fit_isotonic(xs, ys, min_samples=1)
        assert abs(model.apply(2) - 20) < 0.01

    def test_duplicate_x_averaged(self) -> None:
        """相同 x 的点取平均."""
        xs = [1, 1, 2, 3]
        ys = [10, 20, 30, 40]
        model = fit_isotonic(xs, ys, min_samples=1)
        # x=1 的两个点 (10, 20) 平均 → 15
        assert abs(model.apply(1) - 15) < 0.01


class TestApplyIsotonic:
    """apply_isotonic — 批量应用校准."""

    def test_batch_apply(self) -> None:
        xs = [1, 2, 3, 4, 5]
        ys = [2, 4, 6, 8, 10]
        model = fit_isotonic(xs, ys, min_samples=1)
        results = apply_isotonic(model, [1, 3, 5])
        assert len(results) == 3
        assert abs(results[0] - 2) < 0.01  # type: ignore
        assert abs(results[1] - 6) < 0.01  # type: ignore
        assert abs(results[2] - 10) < 0.01  # type: ignore

    def test_insufficient_returns_none_list(self) -> None:
        model = fit_isotonic([1, 2], [1, 2], min_samples=20)
        results = apply_isotonic(model, [1, 2, 3])
        assert results == [None, None, None]


class TestIsBucketInsufficient:
    """is_bucket_insufficient — 样本不足判断 (R-5.C 第 4 项)."""

    def test_below_threshold(self) -> None:
        assert is_bucket_insufficient(19) is True

    def test_at_threshold(self) -> None:
        assert is_bucket_insufficient(20) is False

    def test_above_threshold(self) -> None:
        assert is_bucket_insufficient(21) is False

    def test_zero(self) -> None:
        assert is_bucket_insufficient(0) is True

    def test_custom_threshold(self) -> None:
        assert is_bucket_insufficient(9, min_samples=10) is True
        assert is_bucket_insufficient(10, min_samples=10) is False

    def test_default_threshold_is_20(self) -> None:
        assert MIN_BUCKET_SAMPLES == 20
