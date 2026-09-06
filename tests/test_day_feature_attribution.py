"""day_feature_attribution — 日层 T0 特征归因的 fixture 驱动测试.

零网络/零 gitignored 资产: 全部输入在测试内构造 (R10 slot 自足纪律)。
非对称 oracle (R13 教训): fixture 数值刻意互异, 数值断言不被全对称
漂移掩盖。零 RNG 主面: Pearson/特征表/split-half 全部确定性。
"""

from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from scripts.day_feature_attribution import (
    PRIMARY_HORIZON,
    SCORE_COMPONENT_COLS,
    _day_net_by_day,
    build_payload,
    day_feature_table,
    feature_pearson,
    feature_terciles,
    pearson_r,
    render_md,
    split_half_stability,
    worst_days,
)
from src.screening.offensive.gap_disclosure import cohort_size_bucket

ROUNDTRIP = 0.0065  # ROUNDTRIP_COST 回显口径 (单一实现 net_returns 派生)


def _row(
    day: int,
    code: str,
    *,
    strength: float | None,
    ret: float,
    close: float = 10.0,
    industry: str | None = "电子",
    industry_missing: bool = False,
    gross_nan: bool = False,
) -> dict:
    row = {
        "signal_date": day,
        "ts_code": f"{code}.SZ",
        "trigger_strength": strength,
        "signal_close": close,
        "gross_ret_t10": None if gross_nan else ret,
        "gross_ret_t8": ret,
        "fillable": True,
        "gate_blocked": False,
        "price_ge_3": True,
        "degraded": False,
        "st_name": "",
        "industry_missing": industry_missing,
        "excluded_ticker": False,
        "industry_name": "" if (industry_missing or industry is None) else industry,
    }
    for col in SCORE_COMPONENT_COLS:
        row[col] = ret * 10.0  # score 分量与 ret 同源但量纲互异 (非对称)
    return row


def _two_day_world() -> pd.DataFrame:
    """双日非对称宇宙: day1 强而分化, day2 弱而集中 — 数值断言锚定. """
    return pd.DataFrame(
        [
            _row(20260701, "000001", strength=0.75, ret=0.03, close=9.0,
                 industry="电子"),
            _row(20260701, "000002", strength=0.65, ret=0.01, close=11.0,
                 industry="机械"),
            _row(20260701, "000003", strength=0.55, ret=-0.01, close=10.0,
                 industry="电子"),
            _row(20260702, "000004", strength=0.45, ret=-0.05, close=8.0,
                 industry="机械"),
            _row(20260702, "000005", strength=0.70, ret=0.02, close=12.0,
                 industry="机械"),
        ]
    )


# ---------------------------------------------------------------------------
# 特征表
# ---------------------------------------------------------------------------

def test_day_table_asymmetric_oracle() -> None:
    table = day_feature_table(_two_day_world())
    assert [r["signal_date"] for r in table] == ["20260701", "20260702"]
    d1, d2 = table
    # 逐格 oracle (净 = 毛 − 0.65%)
    assert d1["day_e_net_t10"] == pytest.approx((0.03 + 0.01 - 0.01) / 3 - ROUNDTRIP)
    assert d2["day_e_net_t10"] == pytest.approx((-0.05 + 0.02) / 2 - ROUNDTRIP)
    assert d1["cohort_n"] == 3 and d2["cohort_n"] == 2
    assert d1["cohort_bucket"] == cohort_size_bucket(3)
    assert d2["cohort_bucket"] == cohort_size_bucket(2)
    assert d1["strength_mean"] == pytest.approx((0.75 + 0.65 + 0.55) / 3)
    assert d1["strength_median"] == pytest.approx(0.65)
    # strong(>=0.70): day1 = 1/3, day2 = 1/2 — 左闭右开 0.70 含 0.70
    assert d1["strong_share"] == pytest.approx(1 / 3)
    assert d2["strong_share"] == pytest.approx(0.5)
    assert d1["close_median"] == pytest.approx(10.0)
    assert d2["close_median"] == pytest.approx(10.0)
    # 行业宽度: day1 电子×2+机械×1 → 宽度 2 / Top1 2/3; day2 全机械
    assert d1["industry_breadth"] == 2
    assert d1["top_industry_share"] == pytest.approx(2 / 3)
    assert d2["industry_breadth"] == 1
    assert d2["top_industry_share"] == pytest.approx(1.0)
    assert d1["strength_missing"] == 0 and d1["industry_missing_n"] == 0


def test_strength_missing_disclosed_not_zero() -> None:
    ev = pd.DataFrame(
        [
            _row(20260701, "000001", strength=0.75, ret=0.03),
            _row(20260701, "000002", strength=float("nan"), ret=-0.01),
        ]
    )
    (row,) = day_feature_table(ev)
    assert row["strength_missing"] == 1
    # 均值只由 finite 行承载, 绝不以 0 冒充缺失
    assert row["strength_mean"] == pytest.approx(0.75)
    assert row["strong_share"] == pytest.approx(1.0)


def test_industry_degenerate_all_missing() -> None:
    ev = pd.DataFrame(
        [
            _row(20260701, "000001", strength=0.75, ret=0.03,
                 industry_missing=True),
            _row(20260701, "000002", strength=0.65, ret=-0.01,
                 industry="电子", industry_missing=True),
        ]
    )
    (row,) = day_feature_table(ev)
    assert row["industry_missing_n"] == 2
    assert row["industry_breadth"] is None
    assert row["top_industry_share"] is None


def test_missing_column_fails_closed() -> None:
    ev = _two_day_world().drop(columns=["energy_bonus"])
    with pytest.raises(SystemExit, match="energy_bonus"):
        day_feature_table(ev)


def test_unmatured_row_fails_closed() -> None:
    ev = pd.DataFrame(
        [
            _row(20260701, "000001", strength=0.75, ret=0.03),
            _row(20260701, "000002", strength=0.65, ret=-0.01, gross_nan=True),
        ]
    )
    with pytest.raises(SystemExit, match="全成熟宇宙"):
        day_feature_table(ev)
    with pytest.raises(SystemExit, match="全成熟宇宙"):
        _day_net_by_day(ev)


# ---------------------------------------------------------------------------
# Pearson 归因
# ---------------------------------------------------------------------------

def test_pearson_perfect_and_anti() -> None:
    # 强度均值与日 E 完全线性 → |r| = 1; 反向构造 → r = -1
    rows = []
    for i, ret in enumerate([-0.06, -0.02, 0.02, 0.06]):
        rows.append(_row(20260701 + i, f"{i}", strength=0.5 + 0.05 * i,
                         ret=ret, industry="电子"))
    table = day_feature_table(pd.DataFrame(rows))
    a = feature_pearson(table, "strength_mean")
    assert a is not None
    assert a["pearson_r"] == pytest.approx(1.0)
    assert a["degenerate"] is False and a["days_feature_missing"] == 0

    rows_rev = []
    for i, ret in enumerate([0.06, 0.02, -0.02, -0.06]):
        rows_rev.append(_row(20260701 + i, f"{i}", strength=0.5 + 0.05 * i,
                             ret=ret, industry="电子"))
    table_rev = day_feature_table(pd.DataFrame(rows_rev))
    a_rev = feature_pearson(table_rev, "strength_mean")
    assert a_rev is not None and a_rev["pearson_r"] == pytest.approx(-1.0)


def test_pearson_constant_feature_none() -> None:
    rows = [
        _row(20260701 + i, f"{i}", strength=0.6, ret=0.03 - 0.02 * i,
             close=10.0, industry="电子")
        for i in range(4)
    ]
    table = day_feature_table(pd.DataFrame(rows))
    a = feature_pearson(table, "close_median")
    assert a is not None
    assert a["pearson_r"] is None
    assert a["degenerate"] is True


def test_pearson_skips_missing_days_with_count() -> None:
    # 删除 NaN 日后剩余三点对强度严格线性 (日 E = a − b·strength) → r = -1
    rows = [
        _row(20260701, "000001", strength=0.50, ret=0.06, industry="电子"),
        _row(20260702, "000002", strength=float("nan"), ret=0.02,
             industry="电子"),
        _row(20260703, "000003", strength=0.60, ret=-0.04, industry="电子"),
        _row(20260704, "000004", strength=0.70, ret=-0.14, industry="电子"),
    ]
    table = day_feature_table(pd.DataFrame(rows))
    a = feature_pearson(table, "strength_mean")
    assert a is not None
    assert a["n_days"] == 3
    assert a["days_feature_missing"] == 1
    assert a["pearson_r"] == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# 三分位事件面
# ---------------------------------------------------------------------------

def test_terciles_partition_and_order_independence() -> None:
    rows = [
        _row(20260701 + i, f"{i:06d}", strength=0.50 + 0.02 * i,
             ret=0.08 - 0.02 * i, industry="电子")
        for i in range(9)
    ]
    ev = pd.DataFrame(rows)
    table = day_feature_table(ev)
    day_net = _day_net_by_day(ev)
    t = feature_terciles(table, day_net, "strength_mean")
    assert t is not None
    assert t["days_total"] == 9 and t["days_feature_missing"] == 0
    assert [c["days"] for c in t["cells"]] == [3, 3, 3]
    # 特征严格单调 → 日 E 严格 T1 > T2 > T3 (构造: 强度高 → ret 低)
    es = [c["event_stats"]["expectancy"] for c in t["cells"]]
    assert es[0] > es[1] > es[2]
    # 输入行序扰动 → 逐字节同输出 (边界不依赖行序)
    shuffled = table[::-1]
    t_shuffled = feature_terciles(shuffled, day_net, "strength_mean")
    assert json.dumps(t_shuffled, sort_keys=True) == json.dumps(t, sort_keys=True)


def test_terciles_degenerate_few_days_and_all_missing() -> None:
    ev1 = pd.DataFrame([_row(20260701, "000001", strength=0.6, ret=0.03)])
    table1 = day_feature_table(ev1)
    t1 = feature_terciles(table1, _day_net_by_day(ev1), "strength_mean")
    assert t1 is not None
    assert t1["cells"][0]["days"] == 1
    assert t1["cells"][1]["event_stats"]["n"] == 0
    assert t1["cells"][1]["event_stats"]["expectancy"] is None
    assert t1["cells"][2]["event_stats"]["expectancy"] is None
    # 特征全缺失 (strength 全 NaN → strength_mean 全 None) → 整表 None
    ev_none = pd.DataFrame(
        [_row(20260701, "000001", strength=None, ret=0.03),
         _row(20260702, "000002", strength=None, ret=-0.03)]
    )
    table_none = day_feature_table(ev_none)
    assert feature_terciles(table_none, _day_net_by_day(ev_none),
                            "strength_mean") is None


# ---------------------------------------------------------------------------
# split-half 稳定性
# ---------------------------------------------------------------------------

def _linear_days(n_days: int, slope: float, base_ret: float = 0.0) -> pd.DataFrame:
    """n_days 单事件日, 强度线性升, 日 E = base + slope×i (噪声为零)."""
    rows = [
        _row(20260101 + i, f"{i:06d}", strength=0.50 + 0.005 * i,
             ret=base_ret + slope * i, industry="电子")
        for i in range(n_days)
    ]
    return pd.DataFrame(rows)


def test_split_half_qualified_with_enough_days() -> None:
    table = day_feature_table(_linear_days(64, slope=0.005))
    s = split_half_stability(table, "strength_mean")
    assert s is not None
    assert s["verdict"] == "具备资格"
    h1, h2 = s["halves"]
    assert h1["n_days"] == 32 and h2["n_days"] == 32
    assert h1["pearson_r"] == pytest.approx(1.0)
    assert h2["pearson_r"] == pytest.approx(1.0)


def test_split_half_sign_flip_disclosure_only() -> None:
    # 前半正相关 / 后半负相关 → 同号判据拒 → 只披露 (不能因样本大而资格化)
    rows = [
        _row(20260101 + i, f"{i:06d}", strength=0.50 + 0.005 * i,
             ret=0.005 * i, industry="电子")
        for i in range(32)
    ] + [
        _row(20260301 + i, f"{i:06d}", strength=0.66 + 0.005 * i,
             ret=-0.005 * i, industry="电子")
        for i in range(32)
    ]
    table = day_feature_table(pd.DataFrame(rows))
    s = split_half_stability(table, "strength_mean")
    assert s is not None and s["verdict"] == "只披露"


def test_split_half_insufficient_days() -> None:
    table = day_feature_table(_linear_days(10, slope=0.005))
    s = split_half_stability(table, "strength_mean")
    assert s is not None and s["verdict"] == "样本不足 — 只披露"


def test_split_half_degenerate_half() -> None:
    rows = [
        _row(20260101 + i, f"{i:06d}", strength=0.60, ret=0.005 * i,
             industry="电子")
        for i in range(32)
    ] + [
        _row(20260301 + i, f"{i:06d}", strength=0.70 + 0.005 * i,
             ret=0.005 * i, industry="电子")
        for i in range(32)
    ]
    table = day_feature_table(pd.DataFrame(rows))
    s = split_half_stability(table, "strength_mean")
    assert s is not None and s["verdict"] == "特征退化 — 只披露"
    assert s["halves"][0]["pearson_r"] is None


# ---------------------------------------------------------------------------
# worst-5 / payload / 渲染
# ---------------------------------------------------------------------------

def test_worst_days_stable_order() -> None:
    rows = [
        _row(20260701, "000001", strength=0.6, ret=-0.10, industry="电子"),
        _row(20260702, "000002", strength=0.6, ret=-0.30, industry="电子"),
        _row(20260703, "000003", strength=0.6, ret=0.20, industry="电子"),
        _row(20260704, "000004", strength=0.6, ret=-0.30, industry="电子"),
    ]
    table = day_feature_table(pd.DataFrame(rows))
    worst = worst_days(table, k=5)
    # 日 E 升序; -0.30 双日并列按日期升序; k>n 返回全部
    assert [w["signal_date"] for w in worst] == [
        "20260702", "20260704", "20260701", "20260703",
    ]


def test_payload_md_json_deterministic(tmp_path) -> None:
    ev = _two_day_world()
    csv_path = tmp_path / "event_table_v1.csv"
    ev.to_csv(csv_path, index=False)
    p1 = build_payload(ev, csv_path, report_date="20260906")
    p2 = build_payload(ev, csv_path, report_date="20260906")
    j1 = json.dumps(p1, ensure_ascii=False, sort_keys=True, indent=1)
    j2 = json.dumps(p2, ensure_ascii=False, sort_keys=True, indent=1)
    assert j1 == j2  # 零 RNG 主面: 两次构建逐字节同
    assert p1["caliber"]["universe_rows"] == 5
    assert p1["caliber"]["days"] == 2
    assert "0.65%" in p1["caliber"]["caliber_note"]
    assert "t0_note" in p1["caliber"]

    md1 = render_md(p1)
    md2 = render_md(p2)
    assert md1 == md2
    assert "宪法 #2" in md1
    assert "净=毛−0.65%" in md1
    assert "T0 可观测性" in md1
    assert "gap_t1_open" in md1  # T+1 列显式排除的披露在 MD 可见
    # court 绑定行带 content_digest 前缀
    assert "content_digest=" in md1
    assert p1["court_binding"]["rows"] == 5
    assert p1["court_binding"]["content_digest"] is not None


def test_pearson_formula_matches_reference() -> None:
    # 独立小样本对照 (非对称): 与手算协方差/方差公式一致
    xs = [1.0, 2.0, 4.0]
    ys = [0.5, 1.0, 2.5]
    r = pearson_r(xs, ys)
    mx, my = 7 / 3, 4 / 3
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    assert r == pytest.approx(sxy / math.sqrt(sxx * syy))
    assert pearson_r([1.0], [2.0]) is None  # n<2
    assert pearson_r([1.0, 2.0], [1.0, 2.0]) is not None
    assert pearson_r([1.0, 2.0], [3.0, 1.0]) == pytest.approx(-1.0)


def test_primary_horizon_pinned() -> None:
    assert PRIMARY_HORIZON == 10  # T+10 合约; 变更 = 新证据世代
