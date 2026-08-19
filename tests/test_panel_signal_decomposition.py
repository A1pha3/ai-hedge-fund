"""panel_signal_decomposition 纯函数回归网 — T+1 反向诊断工具首张测试.

锁定:
- split_groups/degraded 语义与 panel_health_check 同源 (degraded 标志或
  'readiness degraded' 前缀 → 排除且单独计数, 不入对照);
- strength_bucket 边界 (拒票归 <0.50 桶; eligible 0.50/0.60/0.70 三段;
  eligible 却 <0.50 的数据异常如实归异常桶);
- horizon_returns 只收数值 (None/缺失跳过);
- welch: 分离样本 p 小、同分布 p 大、空组返回 n 感知结构不抛;
- cell: n<MIN_CELL_N → sufficient=False (只披露纪律);
- block_reason_class 归类;
- decompose 端到端 (小 fixture): headline 方向 + 桶表键完整。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from panel_signal_decomposition import (  # noqa: E402
    MIN_CELL_N,
    contrast_t1_counts,
    block_reason_class,
    cell,
    decompose,
    horizon_returns,
    is_degraded,
    split_groups,
    strength_bucket,
    welch,
)


def _row(**kw) -> dict:
    base = {
        "ticker": "600000", "signal_date": "2026-08-01", "setup": "btst_breakout",
        "plan_eligible": False, "degraded": False, "block_reason": None,
        "trigger_strength": 0.55, "regime": "normal",
        "return_t1": 0.01, "return_t5": 0.02, "return_t10": 0.03,
    }
    base.update(kw)
    return base


# ---------- degraded 语义与分组 ----------


def test_split_groups_degraded_excluded_but_counted():
    rows = [
        _row(plan_eligible=True),
        _row(block_reason="强度 0.47 < 0.50 阈值"),
        _row(degraded=True),
        _row(block_reason="readiness degraded: industry_data_missing"),
    ]
    g = split_groups(rows)
    assert len(g["eligible"]) == 1
    assert len(g["rejected"]) == 1
    assert len(g["degraded"]) == 2  # 标志位 + 前缀两种来源都识别
    assert is_degraded(_row(block_reason="readiness degraded: x")) is True
    assert is_degraded(_row()) is False


# ---------- strength_bucket 边界 ----------


def test_strength_bucket_edges():
    assert strength_bucket(_row(plan_eligible=False)) == "拒(<0.50)"
    assert strength_bucket(_row(plan_eligible=True, trigger_strength=0.50)) == "0.50-0.60"
    assert strength_bucket(_row(plan_eligible=True, trigger_strength=0.5999)) == "0.50-0.60"
    assert strength_bucket(_row(plan_eligible=True, trigger_strength=0.60)) == "0.60-0.70"
    assert strength_bucket(_row(plan_eligible=True, trigger_strength=0.70)) == "≥0.70"
    assert strength_bucket(_row(plan_eligible=True, trigger_strength=0.42)) == "eligible(<0.50)·异常"


# ---------- horizon_returns / cell / welch ----------


def test_horizon_returns_skips_non_numeric():
    rows = [_row(return_t1=0.01), _row(return_t1=None), _row(return_t1=0.03),
            _row(return_t1="n/a")]
    assert horizon_returns(rows, 1) == [0.01, 0.03]


def test_cell_sufficient_flag_min_n():
    assert cell([0.01] * MIN_CELL_N)["sufficient"] is True
    assert cell([0.01] * (MIN_CELL_N - 1))["sufficient"] is False
    assert cell([]) == {"n": 0, "mean": None, "win_rate": None, "sufficient": False}


def test_welch_separated_vs_similar_vs_empty():
    a = [0.05 * ((i % 7) - 3) / 3 + 0.05 for i in range(40)]  # 均值 ~+5%
    b = [0.05 * ((i % 7) - 3) / 3 - 0.05 for i in range(40)]  # 均值 ~-5%
    sep = welch(a, b)
    assert sep["p"] < 0.01 and sep["cohens_d"] > 0
    same = welch(a, list(a))
    assert same["p"] > 0.99
    empty = welch([], b)
    assert empty["t"] is None and empty["p"] is None and empty["mean_a"] is None


# ---------- block_reason_class ----------


def test_block_reason_class_grouping():
    assert block_reason_class("readiness degraded: x") == "readiness_degraded"
    assert block_reason_class("trigger_strength_below_threshold") == "strength_below_threshold"
    assert block_reason_class("强度 0.46 < 0.50 阈值") == "strength_below_threshold"
    assert block_reason_class("") == "unclassified"
    assert block_reason_class("regime 闸（危机/避险日不开新仓）") == "regime 闸（危机/避险日不开新仓）"


# ---------- decompose 端到端 (小 fixture) ----------


def test_decompose_small_fixture_structure_and_direction():
    rows = []
    for i in range(35):
        rows.append(_row(ticker=f"E{i}", plan_eligible=True, return_t1=-0.01))
        rows.append(_row(ticker=f"R{i}", plan_eligible=False,
                         block_reason="trigger_strength_below_threshold", return_t1=+0.01))
    rows.append(_row(ticker="D1", degraded=True, return_t1=0.5))
    out = decompose(rows)
    assert out["rows_total"] == 71
    assert out["degraded_excluded"] == 1
    assert out["eligible_n"] == 35 and out["rejected_n"] == 35
    # headline T+1: eligible 均值 -1% vs 拒票 +1% → t 为负 (反向信号方向)
    assert out["headline"]["t1"]["mean_a"] < 0 < out["headline"]["t1"]["mean_b"]
    assert out["headline"]["t1"]["t"] < 0
    # 桶表四桶键完整, 拒票桶 n=35 充分
    assert set(out["strength_bucket_horizons"]["t1"]) == {"拒(<0.50)", "0.50-0.60", "0.60-0.70", "≥0.70"}
    assert out["strength_bucket_horizons"]["t1"]["拒(<0.50)"]["n"] == 35
    # regime 分解含 normal
    assert "normal" in out["regime_split_t1"]
    # 拒票原因结构: strength_below_threshold n=35
    assert out["rejected_reason_classes"]["strength_below_threshold"]["n"] == 35


# ---------- render_md 冒烟 ----------


def test_render_md_contains_sections_and_disclosure():
    from panel_signal_decomposition import render_md

    rows = [_row(ticker=f"E{i}", plan_eligible=True) for i in range(3)] + [
        _row(ticker="R0", plan_eligible=False, block_reason="强度 0.47 < 0.50 阈值")]
    payload = decompose(rows)
    md = render_md(payload, "20260819")
    assert "panel T+1 反向信号分解" in md
    assert "headline" in md and "强度桶" in md and "regime 分解" in md
    assert "⚠样本不足" in md  # 小样本格如实标注
    assert "不构成参数变更提案" in md  # 纪律句常驻


# ---------- contrast_t1_counts: 与 decompose 桶表奇偶一致 (单一事实源钉死) ----------


def test_contrast_t1_counts_parity_with_decompose():
    rows = []
    for i in range(12):
        rows.append(_row(ticker=f"M{i}", plan_eligible=True,
                         trigger_strength=0.55, return_t1=0.01))       # 边缘桶 12
        rows.append(_row(ticker=f"R{i}", plan_eligible=False,
                         block_reason="trigger_strength_below_threshold",
                         return_t1=-0.01))                              # 拒票组 12
    for i in range(5):
        rows.append(_row(ticker=f"S{i}", plan_eligible=True,
                         trigger_strength=0.75, return_t1=0.02))       # ≥0.70 桶 (不进对比)
    rows.append(_row(ticker="M13", plan_eligible=True,
                     trigger_strength=0.55, return_t1=None))           # T+1 未实现 (不数)
    rows.append(_row(ticker="D1", plan_eligible=True,
                     trigger_strength=0.55, degraded=True, return_t1=0.5))  # 降级排除
    marginal, rejected = contrast_t1_counts(rows)
    t1 = decompose(rows)["strength_bucket_horizons"]["t1"]
    assert (marginal, rejected) == (t1["0.50-0.60"]["n"], t1["拒(<0.50)"]["n"])
    assert (marginal, rejected) == (12, 12)
