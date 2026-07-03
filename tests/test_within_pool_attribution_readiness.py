"""c316 (loop 48) — within-pool factor attribution 就绪检查 helper tests.

R6 关闭后, 真正的北极星难题是 within-pool RANKING (循环 40-42 结论性发现
"无干净 current-data signal": recommendation_score IC 弱, price 是 pool 放大伪象).
循环 42 当时想做 factor-level 分析 (用 score_decomposition 按 per-factor 贡献分
高/低组算 winrate 倒挂), 但被数据阻塞 — score_decomposition 覆盖 0/8025.

c316 发现: blocker 正在解除. _inject_score_decomposition (8a5d54e8) 已上线,
最近 3 天 (20260630-0702) 100% 覆盖, 每天积累 ~10-12 条. factor_attribution
需 min_n*3=45 条最小样本. 当前 32 条, 还差 ~13 条 (~1-2 天).

本 helper 让 owner/autodev 知道数据何时够 + 何时可跑 within-pool factor
attribution, 而非干等或反复手动查. 纯逻辑 (覆盖率统计 + 就绪估算) 必须可测:
误判就绪会跑出 insufficient 浪费精力; 误判未就绪会干等过久.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts._diag_within_pool_attribution_readiness import (  # noqa: E402
    attribution_readiness,
)


# ---------------------------------------------------------------------------
# attribution_readiness — coverage stats + ready verdict + ETA
# ---------------------------------------------------------------------------


def _rec(date: str, sd=None, ret5=None):
    """Build a minimal tracking_history record."""
    return {
        "recommended_date": date,
        "score_decomposition": sd,
        "next_5day_return": ret5,
    }


def test_readiness_empty_records_not_ready():
    r = attribution_readiness([], min_n=15, horizon_field="next_5day_return")
    assert r["valid_count"] == 0
    assert r["min_required"] == 45  # min_n * 3
    assert r["ready"] is False
    assert r["deficit"] == 45


def test_readiness_counts_only_sd_plus_horizon_records():
    """A record counts as 'valid' only if it has BOTH score_decomposition AND a
    finite horizon return — matching factor_attribution's filter (line 84-87).
    Records missing either don't count toward readiness (don't fake it)."""
    sd = {"base_contributions": {"trend": 0.1}}
    recs = [
        _rec("20260701", sd=sd, ret5=0.02),    # valid
        _rec("20260701", sd=sd, ret5=None),    # no horizon return — invalid
        _rec("20260701", sd=None, ret5=0.02),  # no decomposition — invalid
        _rec("20260701", sd="garbage", ret5=0.02),  # decomposition not dict — invalid
        _rec("20260702", sd=sd, ret5=-0.01),   # valid
    ]
    r = attribution_readiness(recs, min_n=15, horizon_field="next_5day_return")
    assert r["valid_count"] == 2  # only the two fully-valid records


def test_readiness_meets_threshold():
    sd = {"base_contributions": {"trend": 0.1}}
    recs = [_rec("20260701", sd=sd, ret5=0.02) for _ in range(45)]
    r = attribution_readiness(recs, min_n=15, horizon_field="next_5day_return")
    assert r["valid_count"] == 45
    assert r["min_required"] == 45
    assert r["ready"] is True
    assert r["deficit"] == 0


def test_readiness_one_short_of_threshold():
    sd = {"base_contributions": {"trend": 0.1}}
    recs = [_rec("20260701", sd=sd, ret5=0.02) for _ in range(44)]
    r = attribution_readiness(recs, min_n=15, horizon_field="next_5day_return")
    assert r["ready"] is False
    assert r["deficit"] == 1


def test_readiness_custom_min_n():
    """min_n is configurable (factor_attribution_by_state uses _MIN_N_DEFAULT=15,
    but factor_attribution.compute_factor_attribution_from_loaded accepts min_n).
    A smaller min_n lowers the bar."""
    sd = {"base_contributions": {"trend": 0.1}}
    recs = [_rec("20260701", sd=sd, ret5=0.02) for _ in range(30)]
    # min_n=10 → need 30; we have exactly 30 → ready
    r = attribution_readiness(recs, min_n=10, horizon_field="next_5day_return")
    assert r["ready"] is True
    assert r["min_required"] == 30


# ---------------------------------------------------------------------------
# per-factor coverage — which strategies have data to analyze?
# ---------------------------------------------------------------------------


def test_readiness_per_factor_coverage_lists_strategies():
    """The base_contributions keys tell us which strategies (T/MR/F/E) have
    data. This lets the owner see which factors will be analyzable once ready."""
    sd = {"base_contributions": {"trend": 0.1, "mean_reversion": 0.05, "fundamental": 0.2}}
    recs = [_rec("20260701", sd=sd, ret5=0.02) for _ in range(3)]
    r = attribution_readiness(recs, min_n=15, horizon_field="next_5day_return")
    assert set(r["factors_present"]) == {"trend", "mean_reversion", "fundamental"}


def test_readiness_per_factor_handles_missing_base_contributions():
    """Some decompositions may lack base_contributions (degraded). Don't crash;
    report what's present."""
    recs = [
        _rec("20260701", sd={"base_contributions": {"trend": 0.1}}, ret5=0.02),
        _rec("20260701", sd={"attention_contribution": 0.5}, ret5=0.02),  # no base_contributions
        _rec("20260701", sd=None, ret5=0.02),  # no decomposition at all
    ]
    r = attribution_readiness(recs, min_n=15, horizon_field="next_5day_return")
    assert "trend" in r["factors_present"]


# ---------------------------------------------------------------------------
# ETA estimate — when will data be ready, based on accrual rate?
# ---------------------------------------------------------------------------


def test_readiness_eta_uses_recent_accrual_rate():
    """Estimate days-to-ready from the recent daily accrual rate (last 7 days
    of valid records). This tells the owner 'check back in N days'."""
    sd = {"base_contributions": {"trend": 0.1}}
    # 3 distinct recent dates, 10 records each = 10/day accrual; need 45, have 30 → 15/10 = 2 days
    recs = []
    for d in ("20260630", "20260701", "20260702"):
        for _ in range(10):
            recs.append(_rec(d, sd=sd, ret5=0.02))
    r = attribution_readiness(recs, min_n=15, horizon_field="next_5day_return")
    assert r["valid_count"] == 30
    assert r["deficit"] == 15
    assert r["accrual_per_day"] == 10.0
    assert r["days_to_ready"] == 2  # ceil(15/10)


def test_readiness_eta_zero_accrual_returns_none():
    """If there are NO valid records at all (no accrual signal), can't estimate
    ETA — return None (not 0, not inf). Owner knows it's stalled/unstarted."""
    # no valid records: all missing sd or horizon return
    recs = [
        _rec("20260101", sd=None, ret5=0.02),
        _rec("20260101", sd={"base_contributions": {"trend": 0.1}}, ret5=None),
    ]
    r = attribution_readiness(recs, min_n=15, horizon_field="next_5day_return")
    assert r["valid_count"] == 0
    assert r["accrual_per_day"] == 0.0
    assert r["days_to_ready"] is None


def test_readiness_eta_already_ready_returns_zero():
    sd = {"base_contributions": {"trend": 0.1}}
    recs = [_rec("20260701", sd=sd, ret5=0.02) for _ in range(45)]
    r = attribution_readiness(recs, min_n=15, horizon_field="next_5day_return")
    assert r["ready"] is True
    assert r["days_to_ready"] == 0


# ---------------------------------------------------------------------------
# Reproducibility guard: the loop-48 real-data state.
#
# As of c316 (loop 48): 32 valid records across 3 days (20260630-0702), ~10.7/day
# accrual, deficit 13, ETA ~2 days. This pins the current state so a future
# refactor of attribution_readiness can't silently change the readiness math.
# ---------------------------------------------------------------------------


def test_loop48_current_state_32_records_not_ready_eta_2_days():
    """c316 real-data snapshot: 32 records, 3 days, deficit 13, ETA ~2 days.
    Pinning the readiness math against the actual current state."""
    sd = {"base_contributions": {"trend": 0.1, "mean_reversion": 0.05, "fundamental": 0.2, "event_sentiment": 0.0}}
    recs = []
    for d, n in (("20260630", 12), ("20260701", 10), ("20260702", 10)):
        for _ in range(n):
            recs.append(_rec(d, sd=sd, ret5=0.02))
    r = attribution_readiness(recs, min_n=15, horizon_field="next_5day_return")
    assert r["valid_count"] == 32
    assert r["min_required"] == 45
    assert r["ready"] is False
    assert r["deficit"] == 13
    assert abs(r["accrual_per_day"] - 32 / 3) < 0.1  # ~10.7/day
    assert r["days_to_ready"] == 2  # ceil(13 / 10.67) = 2
