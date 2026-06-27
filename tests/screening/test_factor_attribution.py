"""M1: 因子层归因 (factor attribution) 模块的合成数据测试.

不依赖真实 decomposition 数据 — 全部用内联合成 records.
旧 records 无 score_decomposition → insufficient (诚实静默).
"""
from __future__ import annotations

from src.screening.factor_attribution import (
    FactorAttributionReport,
    compute_factor_attribution_from_loaded,
    render_factor_attribution_line,
)


def _decomp_rec(t30: float, contributions: dict[str, float]) -> dict:
    """合成含 score_decomposition 的 record."""
    return {
        "recommended_date": "20250101",
        "next_30day_return": t30,
        "score_decomposition": {"base_contributions": contributions},
    }


def test_insufficient_when_no_decomposition():
    """旧 records 无 score_decomposition → insufficient."""
    recs = [{"recommended_date": "20250101", "next_30day_return": 5.0}] * 100
    rep = compute_factor_attribution_from_loaded(recs, min_n=10)
    assert rep.verdict == "insufficient"


def test_insufficient_when_too_few_with_decomposition():
    recs = [_decomp_rec(5.0, {"T": 0.3})] * 5  # n=5 < min_n*3
    rep = compute_factor_attribution_from_loaded(recs, min_n=10)
    assert rep.verdict == "insufficient"


def test_detects_inverted_factor():
    """T 策略贡献高 → T+30 胜率低 (倒挂): 该因子可能是根因."""
    # T 贡献低 + 涨; T 贡献高 + 跌 → T 倒挂
    recs = []
    # 低 T 贡献组 (涨)
    for _ in range(30):
        recs.append(_decomp_rec(5.0, {"T": -0.1, "MR": 0.2}))
    # 高 T 贡献组 (跌)
    for _ in range(30):
        recs.append(_decomp_rec(-5.0, {"T": 0.5, "MR": -0.1}))
    # 中间组
    for _ in range(30):
        recs.append(_decomp_rec(1.0, {"T": 0.2, "MR": 0.1}))

    rep = compute_factor_attribution_from_loaded(recs, min_n=10)
    assert rep.verdict == "ok"
    t_factor = [f for f in rep.factors if f.strategy == "T"][0]
    assert t_factor.verdict == "inverted"
    assert rep.worst_factor == "T"


def test_no_inverted_when_factor_positive():
    """T 贡献高 → 胜率高 (正向): 无倒挂."""
    recs = []
    for _ in range(30):
        recs.append(_decomp_rec(-5.0, {"T": -0.1}))
    for _ in range(30):
        recs.append(_decomp_rec(5.0, {"T": 0.5}))
    for _ in range(30):
        recs.append(_decomp_rec(1.0, {"T": 0.2}))

    rep = compute_factor_attribution_from_loaded(recs, min_n=10)
    t_factor = [f for f in rep.factors if f.strategy == "T"][0]
    assert t_factor.verdict == "positive"
    assert rep.worst_factor is None


def test_render_inverted_factor():
    recs = []
    for _ in range(30):
        recs.append(_decomp_rec(5.0, {"T": -0.1}))
    for _ in range(30):
        recs.append(_decomp_rec(-5.0, {"T": 0.5}))
    for _ in range(30):
        recs.append(_decomp_rec(1.0, {"T": 0.2}))
    rep = compute_factor_attribution_from_loaded(recs, min_n=10)
    line = render_factor_attribution_line(rep)
    assert line
    assert "T" in line
    assert "倒挂" in line or "inverted" in line.lower()


def test_render_silent_when_insufficient():
    recs = [{"recommended_date": "20250101", "next_30day_return": 5.0}] * 100
    rep = compute_factor_attribution_from_loaded(recs, min_n=10)
    assert render_factor_attribution_line(rep) == ""
