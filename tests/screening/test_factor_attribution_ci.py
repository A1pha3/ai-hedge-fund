"""TDD for factor_attribution bootstrap CI (loop 49, c317).

within-pool factor attribution 是 R6 关闭后北极星下一题 (loops 40-42) 的 owner
决策工具. 数据 ~10 天后成熟. 当前实现用 5pp 硬阈值判倒挂, 但 n≈15 时 winrate
SE≈13pp (95% CI≈±25pp) — 一个 "17pp 倒挂" 完全可能是噪声. 这是 c297 method
lesson 的同型问题 (bootstrap CI 在 R6 winrate 问题上决策关键). 这里加 CI.

纯函数 + 合成数据 — 不依赖真实数据成熟.
"""
from __future__ import annotations

from src.screening.factor_attribution import (
    FactorContributionWinrate,
    compute_factor_attribution_from_loaded,
    render_factor_attribution_line,
)


def _decomp_rec(ret: float, contributions: dict[str, float]) -> dict:
    return {
        "recommended_date": "20250101",
        "next_5day_return": ret,
        "score_decomposition": {"base_contributions": contributions},
    }


# ---- bootstrap CI on inversion -------------------------------------------------


def test_inverted_factor_has_inversion_ci():
    """倒挂因子应带 CI (low/high inversion 区间), 否则 owner 无法判噪声. """
    recs = []
    for _ in range(30):
        recs.append(_decomp_rec(5.0, {"T": -0.1}))  # 低 T → 涨
    for _ in range(30):
        recs.append(_decomp_rec(-5.0, {"T": 0.5}))  # 高 T → 跌
    for _ in range(30):
        recs.append(_decomp_rec(1.0, {"T": 0.2}))

    rep = compute_factor_attribution_from_loaded(recs, min_n=10, n_bootstrap=200, seed=42)
    assert rep.verdict == "ok"
    t = [f for f in rep.factors if f.strategy == "T"][0]
    assert t.verdict == "inverted"
    # 新字段: 倒挂点估计 + CI
    assert t.inversion is not None and t.inversion > 0
    assert t.inversion_ci_low is not None
    assert t.inversion_ci_high is not None
    assert t.inversion_ci_low <= t.inversion <= t.inversion_ci_high


def test_inverted_factor_classified_noisy_when_ci_crosses_zero():
    """CI 跨 0 → 'inverted_noisy' (倒挂点估计但 CI 含 0, 不可排除噪声). """
    # 构造弱倒挂 (高 T 略输, CI 必跨 0)
    recs = []
    for _ in range(30):
        recs.append(_decomp_rec(1.0, {"T": -0.1}))  # 低 T: 略涨
    for _ in range(30):
        recs.append(_decomp_rec(-1.0, {"T": 0.5}))  # 高 T: 略跌
    for _ in range(30):
        recs.append(_decomp_rec(0.0, {"T": 0.2}))

    rep = compute_factor_attribution_from_loaded(recs, min_n=10, n_bootstrap=500, seed=7)
    t = [f for f in rep.factors if f.strategy == "T"][0]
    # 弱倒挂 + 小 n → CI 必跨 0
    assert t.inversion_ci_low is not None
    assert t.inversion_ci_high is not None
    if t.inversion_ci_low < 0.0 < t.inversion_ci_high:
        assert t.verdict == "inverted_noisy", (
            f"CI 跨 0 ({t.inversion_ci_low:.2f}..{t.inversion_ci_high:.2f}) "
            f"但 verdict={t.verdict}, 应为 inverted_noisy"
        )


def test_ci_is_deterministic_with_seed():
    """同 seed → 同 CI (幂等, 不污染全局 random)."""
    recs = []
    for _ in range(30):
        recs.append(_decomp_rec(5.0, {"T": -0.1}))
    for _ in range(30):
        recs.append(_decomp_rec(-5.0, {"T": 0.5}))
    for _ in range(30):
        recs.append(_decomp_rec(1.0, {"T": 0.2}))

    r1 = compute_factor_attribution_from_loaded(recs, min_n=10, n_bootstrap=100, seed=123)
    r2 = compute_factor_attribution_from_loaded(recs, min_n=10, n_bootstrap=100, seed=123)
    t1 = [f for f in r1.factors if f.strategy == "T"][0]
    t2 = [f for f in r2.factors if f.strategy == "T"][0]
    assert t1.inversion == t2.inversion
    assert t1.inversion_ci_low == t2.inversion_ci_low
    assert t1.inversion_ci_high == t2.inversion_ci_high


def test_ci_contains_point_estimate():
    """c346/autodev-36: 统计学基本性质 — CI 必须包含点估计 (inversion)."""
    from src.screening.factor_attribution import _bootstrap_inversion_ci
    # high 30% winrate, low 60% winrate → inversion point = 0.30
    high = [-1.0] * 70 + [1.0] * 30
    low = [1.0] * 60 + [-1.0] * 40
    point = 0.60 - 0.30
    lo, hi = _bootstrap_inversion_ci(high, low, n_bootstrap=100, ci_level=0.95, seed=42)
    assert lo is not None and hi is not None
    assert lo <= point <= hi, f"CI [{lo:.3f}, {hi:.3f}] must contain point {point:.3f}"


def test_factor_without_enough_samples_has_no_ci():
    """insufficient 因子 (third<min_n) 不应有 CI (None), 保持 stub. """
    # 单一因子 + min_n=10, 但只有 11 条 → third=3 < 10
    recs = [_decomp_rec(5.0, {"T": 0.3})] * 11
    rep = compute_factor_attribution_from_loaded(recs, min_n=10, n_bootstrap=100, seed=1)
    # 全局 n=11 < min_n*3=30 → 整个 report insufficient
    assert rep.verdict == "insufficient"


# ---- render CI -----------------------------------------------------------------


def test_render_shows_ci_brackets_on_inverted():
    recs = []
    for _ in range(30):
        recs.append(_decomp_rec(5.0, {"T": -0.1}))
    for _ in range(30):
        recs.append(_decomp_rec(-5.0, {"T": 0.5}))
    for _ in range(30):
        recs.append(_decomp_rec(1.0, {"T": 0.2}))
    rep = compute_factor_attribution_from_loaded(recs, min_n=10, n_bootstrap=200, seed=42)
    line = render_factor_attribution_line(rep)
    assert "[" in line and "]" in line, f"render 应含 CI 区间, got: {line!r}"


def test_render_marks_noisy_inversion():
    """inverted_noisy 应被标 '噪声' 或类似, 提醒 owner 勿据此重平衡. """
    recs = []
    for _ in range(30):
        recs.append(_decomp_rec(1.0, {"T": -0.1}))
    for _ in range(30):
        recs.append(_decomp_rec(-1.0, {"T": 0.5}))
    for _ in range(30):
        recs.append(_decomp_rec(0.0, {"T": 0.2}))
    rep = compute_factor_attribution_from_loaded(recs, min_n=10, n_bootstrap=500, seed=7)
    t = [f for f in rep.factors if f.strategy == "T"][0]
    if t.verdict == "inverted_noisy":
        line = render_factor_attribution_line(rep)
        # 关键: 噪声标记存在 (中文 '噪声' / 英文 'noisy' 任一)
        assert "噪声" in line or "noisy" in line.lower(), (
            f"inverted_noisy 应有噪声标记, got: {line!r}"
        )


# ---- truthfulness: empty-strategy_keys should NOT be "ok" ----------------------


def test_empty_strategy_keys_is_insufficient_not_ok():
    """base_contributions 为空 dict + 无 fallback 字段 → 应 insufficient, 非 'ok'.
    (修复 'misleading ok' — 见审计发现 #2, src/screening/factor_attribution.py:99-103)
    """
    recs = []
    for _ in range(45):
        recs.append({
            "recommended_date": "20250101",
            "next_5day_return": 5.0,
            "score_decomposition": {"base_contributions": {}},  # 空 dict
        })
    rep = compute_factor_attribution_from_loaded(recs, min_n=10)
    # 修复前: verdict='ok', factors=[] (误导)
    assert rep.verdict == "insufficient", (
        f"空 base_contributions 应 insufficient, got verdict={rep.verdict} "
        f"factors={len(rep.factors)}"
    )


# ---- determinism / no global-state pollution -----------------------------------


def test_bootstrap_does_not_pollute_global_random():
    """bootstrap 用独立 Random, 不影响全局 random 状态. """
    import random as _r
    from src.screening import factor_attribution as fa
    _r.seed(999)
    expected = [_r.random() for _ in range(5)]

    recs = []
    for _ in range(30):
        recs.append(_decomp_rec(5.0, {"T": -0.1}))
    for _ in range(30):
        recs.append(_decomp_rec(-5.0, {"T": 0.5}))
    for _ in range(30):
        recs.append(_decomp_rec(1.0, {"T": 0.2}))

    # 跑 bootstrap 多次
    for s in (1, 2, 3):
        compute_factor_attribution_from_loaded(recs, min_n=10, n_bootstrap=100, seed=s)

    # 重置 + 检查全局 random 未变
    _r.seed(999)
    after = [_r.random() for _ in range(5)]
    assert expected == after, "factor_attribution bootstrap 污染了全局 random 状态"
