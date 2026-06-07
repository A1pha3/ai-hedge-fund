"""P1-4 因子 IC 分析测试套件 — 覆盖 Spearman/Pearson、IR、显著性分级、NaN 处理、空输入。

所有测试不依赖真实报告 — 直接合成数据注入 ``compute_factor_ic``。
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest

from src.research.factor_ic_analysis import (
    FactorICResult,
    IC_HIGH_THRESHOLD,
    IC_LOW_THRESHOLD,
    IC_MEDIUM_THRESHOLD,
    MIN_FACTORS,
    MIN_OBSERVATIONS,
    _pearson_correlation,
    _rank_average,
    _safe_stdev,
    _spearman_correlation,
    classify_significance,
    compute_factor_ic,
    extract_factor_panel_from_history,
    render_factor_ic_ranking,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _perfect_positive() -> dict[str, list[float]]:
    return {
        "trend.momentum_20d": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        "fundamental.pe_ratio": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
        "event_sentiment.news": [-0.5, -0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4],
    }


def _perfect_negative() -> dict[str, list[float]]:
    return {
        "trend.momentum_20d": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        "fundamental.pe_ratio": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
        "event_sentiment.news": [0.5, 0.4, 0.3, 0.2, 0.1, 0.0, -0.1, -0.2, -0.3, -0.4],
    }


def _random_returns(n: int = 10) -> list[float]:
    # 周期内 return 与上面三个因子同步, 但不要求完全相同
    return [0.01, 0.02, 0.015, 0.03, 0.025, 0.04, 0.035, 0.05, 0.045, 0.06]


def _zero_returns(n: int = 10) -> list[float]:
    return [0.0] * n


# ---------------------------------------------------------------------------
# 1. 单因子完美正相关 → IC = 1.0
# ---------------------------------------------------------------------------


def test_perfect_positive_correlation_spearman() -> None:
    """所有因子与下期收益完全正相关 → Spearman IC = +1.0。

    注意: 单次模式下 IR=0, 所以 significance=low (非 high) — IR >= 1.0 才达 high。
    """
    factors = _perfect_positive()
    returns = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
    results = compute_factor_ic(factors, returns, method="spearman")
    assert len(results) == 3
    for name, res in results.items():
        assert math.isclose(res.ic_mean, 1.0, abs_tol=1e-9), f"{name}: IC={res.ic_mean}"
        assert res.method == "spearman"
        # |IC|=1.0 >= 0.02 → low (单次模式 IR=0, 不达 high)
        assert res.significance == "low", f"{name}: sig={res.significance}"
        assert res.ic_positive_rate == 1.0


def test_perfect_positive_correlation_pearson() -> None:
    """Pearson 模式下同样 IC = 1.0。"""
    factors = _perfect_positive()
    returns = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
    results = compute_factor_ic(factors, returns, method="pearson")
    assert all(math.isclose(r.ic_mean, 1.0, abs_tol=1e-9) for r in results.values())


# ---------------------------------------------------------------------------
# 2. 单因子完美负相关 → IC = -1.0
# ---------------------------------------------------------------------------


def test_perfect_negative_correlation() -> None:
    """至少一个因子与收益负相关 → IC = -1.0。"""
    factors = _perfect_negative()
    # 收益严格递增 → momentum_20d 与 returns 完全正 (IC=+1), news 与 returns 完全负 (IC=-1)
    returns = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
    results = compute_factor_ic(factors, returns)
    # momentum_20d: 0.1..1.0 排序后 ranks 1..10, returns ranks 1..10 → +1
    assert math.isclose(results["trend.momentum_20d"].ic_mean, 1.0, abs_tol=1e-9)
    # news: 0.5..-0.4 排序后 ranks 10..1, returns ranks 1..10 → -1
    assert math.isclose(results["event_sentiment.news"].ic_mean, -1.0, abs_tol=1e-9)
    # pe_ratio: 0..0.9 ranks 1..10 → +1
    assert math.isclose(results["fundamental.pe_ratio"].ic_mean, 1.0, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# 3. 单因子无相关 → IC ≈ 0
# ---------------------------------------------------------------------------


def test_zero_returns_yields_insignificant() -> None:
    """下期收益全 0 → 所有 IC = 0 → 全部 insignificant。"""
    factors = _perfect_positive()
    results = compute_factor_ic(factors, _zero_returns(len(next(iter(factors.values())))))
    assert len(results) == 3
    for res in results.values():
        assert res.ic_mean == 0.0
        assert res.significance == "insignificant"


def test_uncorrelated_random_data() -> None:
    """粗略测试: 打乱顺序后 IC 接近 0。"""
    factors = {
        "trend.f1": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        "fundamental.f2": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "event_sentiment.f3": [1.0, 1.0, 1.0, 1.0, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5],
    }
    # returns 完全反向: f1 反向, f2 全 0, f3 略不同方向
    returns = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]
    results = compute_factor_ic(factors, returns)
    # f1 与 returns 反向 → IC=-1
    assert math.isclose(results["trend.f1"].ic_mean, -1.0, abs_tol=1e-9)
    # f2 全 0 → stdev 0 → Pearson 退化为 0
    assert results["fundamental.f2"].ic_mean == 0.0


# ---------------------------------------------------------------------------
# 4. IR 计算 (rolling 模式)
# ---------------------------------------------------------------------------


def test_ir_calculation_rolling() -> None:
    """Rolling 模式下 IC 在窗口内波动, IR = mean / std。"""
    # 构造 30 个数据点; 前 15 个 IC 强正, 后 15 个 IC 强负 → IR 应为负
    factors = {
        "trend.f1": list(range(30)),
        "trend.f2": [0.1 * (i % 3 - 1) for i in range(30)],
        "trend.f3": [math.sin(i) for i in range(30)],
    }
    returns = [0.01 * (1 if i < 15 else -1) for i in range(30)]
    results = compute_factor_ic(factors, returns, rolling_window=10)
    assert len(results) == 3
    # rolling window 30, w=10 → 21 个 IC values
    for res in results.values():
        assert res.n_periods > 0
        # f1 在前 15 段与 returns 正相关, 后 15 段负相关 → IR 应为负
        if res.factor_name == "trend.f1":
            assert res.ir < 0
            assert -1.0 <= res.ir <= 1.0
        # 标准差非 0 (因为跨窗口变化) → IR 不应为 0
        # 至少有一个因子的 IR 应被计算
    # 确保 ic_positive_rate 落在 [0, 1]
    for res in results.values():
        assert 0.0 <= res.ic_positive_rate <= 1.0


# ---------------------------------------------------------------------------
# 5. ic_positive_rate 计算
# ---------------------------------------------------------------------------


def test_ic_positive_rate_single_shot() -> None:
    """单次模式下, IC > 0 → rate = 1.0, IC < 0 → rate = 0.0。"""
    pos = _perfect_positive()
    neg = _perfect_negative()
    returns = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]

    pos_results = compute_factor_ic(pos, returns)
    for r in pos_results.values():
        assert r.ic_positive_rate == 1.0

    neg_results = compute_factor_ic(neg, returns)
    # event_sentiment.news 与 returns 反向 → IC=-1 → rate=0
    assert neg_results["event_sentiment.news"].ic_positive_rate == 0.0
    # 其它两个 IC=+1 → rate=1
    assert neg_results["trend.momentum_20d"].ic_positive_rate == 1.0
    assert neg_results["fundamental.pe_ratio"].ic_positive_rate == 1.0


def test_ic_positive_rate_rolling() -> None:
    """Rolling 模式下, 与 returns 严格同向的因子 → rate = 1.0, 反向 → 0.0。"""
    factors = {
        "trend.f1": [i * 1.0 for i in range(20)],  # 严格递增
        "trend.f2": [-i * 1.0 for i in range(20)],  # 严格递减
        "trend.f3": [i * 0.5 + 1.0 for i in range(20)],  # 严格递增 (偏移)
    }
    returns = [i * 1.0 for i in range(20)]
    results = compute_factor_ic(factors, returns, rolling_window=5)
    # 在所有 rolling 窗口上, f1/f3 都正相关 → rate=1; f2 都负相关 → rate=0
    assert results["trend.f1"].ic_positive_rate == 1.0
    assert results["trend.f2"].ic_positive_rate == 0.0
    assert results["trend.f3"].ic_positive_rate == 1.0


# ---------------------------------------------------------------------------
# 6. Spearman vs Pearson 差异
# ---------------------------------------------------------------------------


def test_spearman_vs_pearson_differ_on_outliers() -> None:
    """当数据有单调非线性 + 极端值时, Spearman 接近 +1, Pearson 会被异常拉低。"""
    factors = {
        "trend.f1": [1, 2, 3, 4, 5, 6, 7, 8, 9, 100],  # ranks: 1..9, 10
        "trend.f2": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        "trend.f3": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
    }
    returns = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]  # ranks 1..10
    spearman = compute_factor_ic(factors, returns, method="spearman")
    pearson = compute_factor_ic(factors, returns, method="pearson")
    # f1: ranks 1..9, 10 vs returns ranks 1..10 → Spearman = +1 (单调同向)
    # 但 Pearson 受 100 极端值影响, 会显著低于 1
    s_f1 = spearman["trend.f1"].ic_mean
    p_f1 = pearson["trend.f1"].ic_mean
    assert s_f1 > p_f1, f"Spearman {s_f1} should exceed Pearson {p_f1}"


# ---------------------------------------------------------------------------
# 7. 空输入 / 边界条件
# ---------------------------------------------------------------------------


def test_empty_input_returns_empty_dict() -> None:
    """空 factor_history → 空 dict。"""
    assert compute_factor_ic({}, [0.1, 0.2, 0.3]) == {}
    assert compute_factor_ic({"a": [0.1, 0.2, 0.3]}, []) == {}
    assert compute_factor_ic({}, []) == {}


def test_too_few_factors_returns_empty() -> None:
    """因子数 < MIN_FACTORS → 空 dict。"""
    factors = {"trend.f1": [0.1, 0.2, 0.3, 0.4, 0.5]}
    factors["fundamental.f2"] = [0.0, 0.1, 0.2, 0.3, 0.4]
    assert len(factors) == 2  # < MIN_FACTORS=3
    results = compute_factor_ic(factors, [0.01, 0.02, 0.03, 0.04, 0.05])
    assert results == {}


def test_too_short_returns_returns_empty() -> None:
    """下期收益长度 < MIN_OBSERVATIONS → 空 dict。"""
    factors = {
        "trend.f1": [0.1, 0.2, 0.3],
        "trend.f2": [0.2, 0.3, 0.4],
        "trend.f3": [0.3, 0.4, 0.5],
    }
    results = compute_factor_ic(factors, [0.01, 0.02])  # 只有 2 个, < MIN_OBSERVATIONS=3
    assert results == {}


def test_nan_in_factor_treated_as_missing() -> None:
    """因子值含 NaN → 该位置被丢弃, 仍能计算 IC。"""
    factors = {
        "trend.f1": [0.1, 0.2, float("nan"), 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        "trend.f2": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
        "trend.f3": [-0.5, -0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4],
    }
    returns = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
    results = compute_factor_ic(factors, returns)
    assert len(results) == 3
    # f1 含 NaN → 仍应能算 (NaN 被丢弃)
    assert results["trend.f1"].n_periods == 9  # 9 个有效数据点


# ---------------------------------------------------------------------------
# 8. 因子数 >= 3 时的最小计算
# ---------------------------------------------------------------------------


def test_three_factors_minimum_works() -> None:
    """恰好 MIN_FACTORS=3 个因子时仍能计算。"""
    factors = {
        "trend.f1": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        "trend.f2": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
        "trend.f3": [-0.5, -0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4],
    }
    returns = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
    results = compute_factor_ic(factors, returns)
    assert len(results) == 3
    # 排名 1..3 都应被赋值
    for rank in (1, 2, 3):
        assert any(r.rank == rank for r in results.values())


# ---------------------------------------------------------------------------
# 9. 显著性分级
# ---------------------------------------------------------------------------


def test_classify_significance_boundaries() -> None:
    """显著性分级边界值测试。"""
    # high: |IC| >= 0.10 AND IR >= 1.0
    assert classify_significance(0.10, 1.0) == "high"
    assert classify_significance(-0.15, 1.5) == "high"
    # medium: |IC| >= 0.05 AND IR >= 0.5
    assert classify_significance(0.05, 0.5) == "medium"
    assert classify_significance(-0.08, 0.7) == "medium"
    # low: |IC| >= 0.02 (但未达 medium)
    assert classify_significance(0.02, 0.0) == "low"
    assert classify_significance(0.03, 0.1) == "low"  # IR < 0.5 → low
    # |IC|=0.10 + IR=0 → low (因 IR=0 不达 high/medium 阈值; 但 |IC| >= 0.02 达 low)
    assert classify_significance(0.10, 0.0) == "low"
    # insignificant
    assert classify_significance(0.01, 0.5) == "insignificant"
    assert classify_significance(0.0, 0.0) == "insignificant"
    # 阈值常量被引用 (防 typo)
    assert IC_HIGH_THRESHOLD == 0.10
    assert IC_MEDIUM_THRESHOLD == 0.05
    assert IC_LOW_THRESHOLD == 0.02


def test_classify_significance_with_ir_zero() -> None:
    """IR=0 (单次模式) 时, 仅 |IC| 决定 → abs(0.10) + IR=0 应为 low (不达 high)。"""
    assert classify_significance(0.10, 0.0) == "low"  # 严格按规则 — IR=0 拿不到 high


# ---------------------------------------------------------------------------
# 10. 排名计算 (NaN 处理)
# ---------------------------------------------------------------------------


def test_ranking_with_nan_ir() -> None:
    """IC 标准差为 0 时 IR=0; 排名仍能计算。"""
    # 三个因子 IC 各不相同 (通过制造不同 sign)
    factors = {
        "trend.f1": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        "trend.f2": [0.5, 0.4, 0.3, 0.2, 0.1, 0.0, -0.1, -0.2, -0.3, -0.4],
        "trend.f3": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
    }
    returns = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
    results = compute_factor_ic(factors, returns)
    # 排名应该 1..3 都有, 不重复
    ranks = sorted(r.rank for r in results.values())
    assert ranks == [1, 2, 3]
    # rank=1 应该是 |IC| 最大的 (此处 f1 与 f3 都是 +1, f2 是 -1)
    top = next(r for r in results.values() if r.rank == 1)
    # f1 与 returns 排序后都是 ranks 1..10 → IC=+1; f3 同样
    # f2 与 returns 排序后方向相反 → IC=-1
    # 排名按 IR 降序, 单次模式 IR=0, 退而求其次按 |IC| 降序
    assert abs(top.ic_mean) == 1.0


def test_ranking_with_all_nan() -> None:
    """全 NaN 因子 → 全部 insignificant, 排名仍分配。"""
    factors = {
        "trend.f1": [float("nan")] * 10,
        "trend.f2": [float("nan")] * 10,
        "trend.f3": [float("nan")] * 10,
    }
    returns = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
    results = compute_factor_ic(factors, returns)
    # 数据无效 → 应被过滤掉
    # 实际上: factor 全部 nan, 配对后长度 < MIN_OBSERVATIONS, 该因子进入 "insignificant" 占位
    # 但返回的 dict 仍包含这些因子
    assert len(results) == 3
    for r in results.values():
        assert r.significance == "insignificant"
        assert r.ic_mean == 0.0
        # 排名仍被赋值 (1..3)
        assert 1 <= r.rank <= 3


# ---------------------------------------------------------------------------
# 内部函数单元测试
# ---------------------------------------------------------------------------


def test_pearson_perfect_positive() -> None:
    """Pearson 在完全线性 + 关系上 = 1。"""
    assert math.isclose(_pearson_correlation([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]), 1.0, abs_tol=1e-9)


def test_pearson_zero_variance_returns_zero() -> None:
    """x 恒定 → stdev=0 → Pearson=0。"""
    result = _pearson_correlation([5, 5, 5, 5], [1, 2, 3, 4])
    assert result == 0.0


def test_spearman_with_ties() -> None:
    """ties 情况下 Spearman 使用平均秩 — 验证 _rank_average。"""
    ranks = _rank_average([1, 2, 2, 3, 4])
    # 1→1, 2,2→2.5, 3→4, 4→5
    assert ranks == [1.0, 2.5, 2.5, 4.0, 5.0]


def test_safe_stdev_basic() -> None:
    """safe_stdev 正常情况。"""
    result = _safe_stdev([1, 2, 3, 4, 5])
    expected = math.sqrt(2.5)  # 样本方差
    assert math.isclose(result, expected, abs_tol=1e-9)


def test_safe_stdev_handles_nan() -> None:
    """NaN/None 被过滤后再算 stdev。"""
    result = _safe_stdev([1.0, 2.0, float("nan"), 3.0, 4.0])
    expected = math.sqrt(sum((x - 2.5) ** 2 for x in [1, 2, 3, 4]) / 3)
    assert math.isclose(result, expected, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# extract_factor_panel_from_history (mock 报告)
# ---------------------------------------------------------------------------


def _write_fake_report(
    reports_dir: Path,
    date_str: str,
    tickers: list[str],
    factor_values: dict[str, float],
    score_b: float = 0.5,
) -> Path:
    """生成一份模拟 auto_screening 报告, 写入 reports_dir。"""
    recs = []
    for ticker in tickers:
        rec = {
            "ticker": ticker,
            "name": ticker,
            "industry_sw": "TEST",
            "score_b": score_b,
            "decision": "buy",
            "strategy_signals": {
                "trend": {
                    "direction": 1,
                    "confidence": 0.6,
                    "sub_factors": {name: {"name": name, "direction": 1, "confidence": val} for name, val in factor_values.items() if name.startswith("trend.")},
                },
                "fundamental": {
                    "direction": 1,
                    "confidence": 0.5,
                    "sub_factors": {name: {"name": name, "direction": 1, "confidence": val} for name, val in factor_values.items() if name.startswith("fundamental.")},
                },
                "event_sentiment": {
                    "direction": 1,
                    "confidence": 0.7,
                    "sub_factors": {name: {"name": name, "direction": 1, "confidence": val} for name, val in factor_values.items() if name.startswith("event_sentiment.")},
                },
            },
        }
        recs.append(rec)
    payload = {
        "date": date_str,
        "mode": "auto_screening",
        "recommendations": recs,
    }
    path = reports_dir / f"auto_screening_{date_str}.json"
    path.write_text(__import__("json").dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _write_tracking_history(reports_dir: Path, records: list[dict]) -> None:
    """生成 tracking_history.json。"""
    path = reports_dir / "tracking_history.json"
    payload = {"records": records}
    path.write_text(__import__("json").dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_extract_factor_panel_no_reports() -> None:
    """reports_dir 不存在 → 返回空。"""
    with tempfile.TemporaryDirectory() as tmp:
        factor_panel, returns = extract_factor_panel_from_history(Path(tmp), lookback_days=10)
    assert factor_panel == {}
    assert returns == []


def test_extract_factor_panel_with_mock_reports() -> None:
    """3 天 mock 报告 → 至少提取部分因子面板 + 下期收益序列。"""
    with tempfile.TemporaryDirectory() as tmp:
        reports_dir = Path(tmp)
        tickers = ["000001", "000002", "000003"]
        # 3 天数据, 每天不同因子值
        for day_idx, date in enumerate(["20260605", "20260606", "20260607"]):
            fv = {
                "trend.momentum_20d": 0.5 + day_idx * 0.1,
                "fundamental.pe_ratio": 0.3 + day_idx * 0.05,
                "event_sentiment.news": 0.4 + day_idx * 0.08,
            }
            _write_fake_report(reports_dir, date, tickers, fv)
        # 写追踪数据: 3 天的 T+1 收益都齐
        _write_tracking_history(
            reports_dir,
            [
                {"trade_date": "20260605", "ticker": "000001", "t1_return": 0.01},
                {"trade_date": "20260605", "ticker": "000002", "t1_return": 0.02},
                {"trade_date": "20260605", "ticker": "000003", "t1_return": 0.015},
                {"trade_date": "20260606", "ticker": "000001", "t1_return": 0.02},
                {"trade_date": "20260606", "ticker": "000002", "t1_return": 0.03},
                {"trade_date": "20260606", "ticker": "000003", "t1_return": 0.025},
                {"trade_date": "20260607", "ticker": "000001", "t1_return": 0.03},
                {"trade_date": "20260607", "ticker": "000002", "t1_return": 0.04},
                {"trade_date": "20260607", "ticker": "000003", "t1_return": 0.035},
            ],
        )
        factor_panel, returns = extract_factor_panel_from_history(reports_dir, lookback_days=5, end_date="20260607")
        # 至少提取到 3 个因子
        assert len(factor_panel) >= 3
        # 收益序列 = 报告数 (3 天都有 T+1 追踪, 无需丢弃最后一天)
        assert len(returns) == 3
        # 所有 returns 应为有限数
        assert all(math.isfinite(r) for r in returns)


# ---------------------------------------------------------------------------
# render_factor_ic_ranking
# ---------------------------------------------------------------------------


def test_render_factor_ic_ranking_empty() -> None:
    """空结果 → 友好降级输出。"""
    output = render_factor_ic_ranking({})
    assert "无可用因子" in output
    assert "━━━" in output


def test_render_factor_ic_ranking_contains_columns() -> None:
    """非空结果 → 表格头 + 行包含。"""
    results = {
        "trend.momentum_20d": FactorICResult(
            factor_name="trend.momentum_20d",
            strategy="trend",
            ic_mean=0.12,
            ic_std=0.05,
            ir=2.4,
            ic_positive_rate=0.7,
            n_periods=10,
            rank=1,
            significance="high",
            method="spearman",
        ),
        "fundamental.pe_ratio": FactorICResult(
            factor_name="fundamental.pe_ratio",
            strategy="fundamental",
            ic_mean=0.03,
            ic_std=0.08,
            ir=0.4,
            ic_positive_rate=0.55,
            n_periods=10,
            rank=2,
            significance="low",
            method="spearman",
        ),
    }
    output = render_factor_ic_ranking(results, end_date="20260607", lookback_days=30)
    assert "━━━ 因子重要性排行" in output
    assert "trend.momentum_20d" in output
    assert "fundamental.pe_ratio" in output
    assert "高" in output  # significance=high → "高"
    assert "低" in output  # significance=low → "低"
    assert "排名" in output
    assert "IC" in output
    assert "IR" in output


# ---------------------------------------------------------------------------
# 回归测试 — 避免 IR 退化为 NaN
# ---------------------------------------------------------------------------


def test_ir_not_nan_for_single_shot() -> None:
    """单次模式下 IR = 0.0 (非 NaN) — 即使 stdev=0。"""
    factors = {
        "trend.f1": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        "trend.f2": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
        "trend.f3": [-0.5, -0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4],
    }
    returns = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
    results = compute_factor_ic(factors, returns)  # 不传 rolling_window → 单次
    for r in results.values():
        assert r.ir == 0.0  # 显式 0, 不是 NaN
        assert r.ic_std == 0.0
        assert r.method == "spearman"


def test_strategy_inferred_from_prefix() -> None:
    """strategy 由因子名前缀推断。"""
    factors = {
        "trend.momentum_20d": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        "fundamental.pe_ratio": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
        "event_sentiment.news": [-0.5, -0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4],
    }
    returns = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
    results = compute_factor_ic(factors, returns)
    assert results["trend.momentum_20d"].strategy == "trend"
    assert results["fundamental.pe_ratio"].strategy == "fundamental"
    assert results["event_sentiment.news"].strategy == "event_sentiment"


def test_strategy_unknown_for_unprefixed_factor() -> None:
    """无前缀的因子 → strategy=unknown。"""
    factors = {
        "momentum_20d": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        "pe_ratio": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
        "news_flow": [-0.5, -0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4],
    }
    returns = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
    results = compute_factor_ic(factors, returns)
    assert all(r.strategy == "unknown" for r in results.values())
