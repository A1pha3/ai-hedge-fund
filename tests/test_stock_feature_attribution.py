"""stock_feature_attribution — within-day T0 特征归因的 fixture 驱动测试.

零网络/零 gitignored 资产: 全部输入在测试内构造 (R10 slot 自足纪律)。
非对称 oracle (R13 教训): fixture 数值刻意互异, 数值断言不被全对称
漂移掩盖。零 RNG 主面: 去均值 Pearson/特征表/秩三分位全部确定性;
CI 面经 per-call seeded RNG 逐次恒同。
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.stock_feature_attribution import (
    PRIMARY_HORIZON,
    SCORE_COMPONENT_COLS,
    build_payload,
    main,
    render_md,
    split_half_within,
    stock_feature_table,
    within_day_pearson,
    within_day_terciles,
)
from src.screening.offensive.threshold_trigger import strength_bucket

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


def _world_b() -> pd.DataFrame:
    """混淆对照世界: 组内强度↑收益↑ (r_within=+1), 日层反向偏移使
    pooled r≈-0.98 — 两列之差即日层混淆的带牙 oracle."""
    return pd.DataFrame(
        [
            _row(20260701, "000001", strength=0.50, ret=0.00, industry="电子"),
            _row(20260701, "000002", strength=0.52, ret=0.02, industry="电子"),
            _row(20260702, "000003", strength=0.30, ret=0.20, industry="机械"),
            _row(20260702, "000004", strength=0.32, ret=0.22, industry="电子"),
        ]
    )


# ---------------------------------------------------------------------------
# 特征表 (恒等面)
# ---------------------------------------------------------------------------

def test_stock_table_asymmetric_oracle() -> None:
    ev = pd.DataFrame(
        [
            _row(20260701, "000001", strength=0.50, ret=0.00, close=9.0),
            _row(20260701, "000002", strength=0.65, ret=0.02, close=11.0),
            _row(20260701, "000003", strength=0.70, ret=-0.01, close=10.0),
        ]
    )
    table = stock_feature_table(ev)
    assert [r["ts_code"] for r in table] == [
        "000001.SZ", "000002.SZ", "000003.SZ",
    ]
    # 逐格 oracle (净 = 毛 − 0.65%)
    assert table[0]["net_ret_t10"] == pytest.approx(0.00 - ROUNDTRIP)
    assert table[1]["net_ret_t10"] == pytest.approx(0.02 - ROUNDTRIP)
    assert table[2]["net_ret_t10"] == pytest.approx(-0.01 - ROUNDTRIP)
    assert table[1]["strength_bucket"] == strength_bucket(0.65)
    assert table[2]["strength_bucket"] == "≥0.70"  # 左闭右开 0.70 含 0.70
    # score 分量逐格 = ret×10 (fixture 构造)
    assert table[1]["energy_bonus"] == pytest.approx(0.2)
    assert table[0]["signal_close"] == pytest.approx(9.0)
    # 同日 3 票互异行业缺失面: 全电子 → peer_n 全 3
    assert all(r["industry_peer_n"] == 3 for r in table)


def test_industry_peer_n_oracle_and_missing() -> None:
    ev = pd.DataFrame(
        [
            _row(20260701, "000001", strength=0.50, ret=0.00, industry="电子"),
            _row(20260701, "000002", strength=0.65, ret=0.02, industry="电子"),
            _row(20260701, "000003", strength=0.70, ret=-0.01, industry="机械"),
            _row(20260701, "000004", strength=0.55, ret=0.03,
                 industry_missing=True),
        ]
    )
    table = stock_feature_table(ev)
    peers = [r["industry_peer_n"] for r in table]
    assert peers == [2, 2, 1, None]  # 缺失行 None, 绝不冒充 1 或 0


def test_strength_out_of_bounds_missing_not_zero() -> None:
    # R132 Op2 同族纪律: 界外毒值缺失不入面 (绝不让 -0.30 冒充合法观测)
    ev = pd.DataFrame(
        [
            _row(20260701, "000001", strength=-0.30, ret=0.00),
            _row(20260701, "000002", strength=1.50, ret=0.02),
            _row(20260701, "000003", strength=0.65, ret=-0.01),
        ]
    )
    table = stock_feature_table(ev)
    assert [r["trigger_strength"] for r in table] == [None, None, 0.65]
    assert [r["strength_bucket"] for r in table] == [
        "unknown", "unknown", "0.60-0.70",
    ]


def test_missing_column_fails_closed() -> None:
    ev = _world_b().drop(columns=["energy_bonus"])
    with pytest.raises(SystemExit, match="energy_bonus"):
        stock_feature_table(ev)


def test_unmatured_row_fails_closed() -> None:
    ev = pd.DataFrame(
        [
            _row(20260701, "000001", strength=0.50, ret=0.00),
            _row(20260701, "000002", strength=0.52, ret=0.02, gross_nan=True),
        ]
    )
    with pytest.raises(SystemExit, match="全成熟宇宙"):
        stock_feature_table(ev)


# ---------------------------------------------------------------------------
# within-day 去均值 Pearson
# ---------------------------------------------------------------------------

def test_within_day_vs_pooled_confound_contrast() -> None:
    a = within_day_pearson(stock_feature_table(_world_b()), "trigger_strength")
    assert a["n_events"] == 4 and a["n_days"] == 2
    # 组内两日同为完美正相关 → r_within = +1
    assert a["pearson_r_within"] == pytest.approx(1.0)
    # 日层反向偏移 (day2 低强度日高收益) → pooled r = −0.0396/0.0404
    assert a["pearson_r_pooled"] == pytest.approx(-0.0396 / 0.0404)
    # n_events=4 < 30 → CI 不产出且如实给原因
    assert a["cluster_ci_low_90"] is None
    assert a["ci_reason"] == "insufficient_events"
    assert a["days_below_pair_floor"] == 0
    assert a["days_zero_within_variance"] == 0


def test_single_stock_day_excluded_and_counted() -> None:
    ev = pd.DataFrame(
        [
            _row(20260701, "000001", strength=0.50, ret=0.00),
            _row(20260701, "000002", strength=0.60, ret=0.02),
            _row(20260702, "000003", strength=0.90, ret=0.50),  # 单票日 (离群)
            _row(20260703, "000004", strength=0.50, ret=0.00),
            _row(20260703, "000005", strength=0.60, ret=0.02),
        ]
    )
    a = within_day_pearson(stock_feature_table(ev), "trigger_strength")
    assert a["days_below_pair_floor"] == 1
    assert a["n_events"] == 4  # 单票日事件不入面
    assert a["pearson_r_within"] == pytest.approx(1.0)  # 离群票未稀释


def test_zero_within_variance_day_excluded_and_counted() -> None:
    ev = pd.DataFrame(
        [
            _row(20260701, "000001", strength=0.60, ret=0.00),
            _row(20260701, "000002", strength=0.60, ret=0.05),  # 特征当日恒定
            _row(20260702, "000003", strength=0.50, ret=0.00),
            _row(20260702, "000004", strength=0.70, ret=0.02),
        ]
    )
    a = within_day_pearson(stock_feature_table(ev), "trigger_strength")
    assert a["days_zero_within_variance"] == 1
    assert a["n_events"] == 2 and a["n_days"] == 1
    assert a["pearson_r_within"] == pytest.approx(1.0)


def test_day_cluster_ci_deterministic_and_exact_oracle() -> None:
    # 20 日 × 2 票, 组内结构逐日全同 (dm x=±0.05, dm y=±0.01) → 每个重采样
    # 复现 r=+1 → CI 下界恰为 1.0 (带牙精确 oracle, 非区间式弱断言)
    rows = []
    for i in range(20):
        rows.append(_row(20260101 + i, f"A{i:02d}", strength=0.50,
                         ret=0.01, industry="电子"))
        rows.append(_row(20260101 + i, f"B{i:02d}", strength=0.60,
                         ret=0.03, industry="机械"))
    table = stock_feature_table(pd.DataFrame(rows))
    a1 = within_day_pearson(table, "trigger_strength")
    a2 = within_day_pearson(table, "trigger_strength")
    assert a1["n_events"] == 40 >= 30 and a1["n_days"] == 20 >= 2
    assert a1["cluster_ci_low_90"] == pytest.approx(1.0)
    assert a1["ci_reason"] is None
    # per-call seeded RNG: 两次调用逐字节恒同 (R13 纪律)
    assert json.dumps(a1, sort_keys=True) == json.dumps(a2, sort_keys=True)


def test_feature_missing_events_counted() -> None:
    ev = pd.DataFrame(
        [
            _row(20260701, "000001", strength=float("nan"), ret=0.00),
            _row(20260701, "000002", strength=0.60, ret=0.02),
            _row(20260701, "000003", strength=0.50, ret=0.01),
            _row(20260702, "000004", strength=float("nan"), ret=0.01),
            _row(20260702, "000005", strength=0.55, ret=0.04),
            _row(20260702, "000006", strength=0.65, ret=0.00),
        ]
    )
    a = within_day_pearson(stock_feature_table(ev), "trigger_strength")
    assert a["events_feature_missing"] == 2
    # 缺失事件不入面: 每日 2 有效观测, 两日 4 事件
    assert a["n_events"] == 4 and a["n_days"] == 2
    assert a["days_below_pair_floor"] == 0


# ---------------------------------------------------------------------------
# within-day 秩三分位
# ---------------------------------------------------------------------------

def test_tercile_face_monotone_and_small_day_excluded() -> None:
    ev = pd.DataFrame(
        [
            _row(20260701, "000001", strength=0.50, ret=0.30),
            _row(20260701, "000002", strength=0.60, ret=0.20),
            _row(20260701, "000003", strength=0.70, ret=0.10),
            _row(20260702, "000004", strength=0.50, ret=0.05),  # 单票日
            _row(20260702, "000005", strength=0.90, ret=-0.05),
        ]
    )
    table = stock_feature_table(ev)
    t = within_day_terciles(table, "trigger_strength")
    assert t is not None
    assert t["days_used"] == 1 and t["days_excluded_small"] == 1
    assert t["events_excluded"] == 2
    es = [c["event_stats"]["expectancy"] for c in t["cells"]]
    ns = [c["event_stats"]["n"] for c in t["cells"]]
    assert ns == [1, 1, 1]
    # 组内强度升 → 收益严格降 (构造): T1 > T2 > T3, 逐格 oracle
    assert es[0] == pytest.approx(0.30 - ROUNDTRIP)
    assert es[1] == pytest.approx(0.20 - ROUNDTRIP)
    assert es[2] == pytest.approx(0.10 - ROUNDTRIP)
    # 输入行序扰动 → 逐字节同输出 (边界不依赖行序)
    t_rev = within_day_terciles(table[::-1], "trigger_strength")
    assert json.dumps(t_rev, sort_keys=True) == json.dumps(t, sort_keys=True)


def test_tercile_tie_broken_by_ts_code_not_row_order() -> None:
    ev = pd.DataFrame(
        [
            _row(20260701, "000003", strength=0.60, ret=0.03),
            _row(20260701, "000001", strength=0.60, ret=0.01),
            _row(20260701, "000002", strength=0.60, ret=0.02),
        ]
    )
    t = within_day_terciles(stock_feature_table(ev), "trigger_strength")
    # 全同值 → 按代码定序: T1=000001 (ret .01), T2=000002 (.02), T3=000003 (.03)
    es = [c["event_stats"]["expectancy"] for c in t["cells"]]
    assert es == [pytest.approx(v) for v in
                  (0.01 - ROUNDTRIP, 0.02 - ROUNDTRIP, 0.03 - ROUNDTRIP)]


# ---------------------------------------------------------------------------
# split-half (预注册判据 R134: 同号且两半 |r|>=0.10)
# ---------------------------------------------------------------------------

def _paired_days(n_days: int, flip_second_half: bool = False) -> pd.DataFrame:
    rows = []
    for i in range(n_days):
        rets = (0.01, 0.03)
        if flip_second_half and i >= n_days // 2:
            rets = (0.03, 0.01)
        rows.append(_row(20260101 + i, f"A{i:02d}", strength=0.50,
                         ret=rets[0], industry="电子"))
        rows.append(_row(20260101 + i, f"B{i:02d}", strength=0.60,
                         ret=rets[1], industry="电子"))
    return pd.DataFrame(rows)


def test_split_half_qualified() -> None:
    s = split_half_within(stock_feature_table(_paired_days(32)),
                          "trigger_strength")
    assert s is not None and s["verdict"] == "具备资格"
    h1, h2 = s["halves"]
    assert h1["n_events"] == 32 and h2["n_events"] == 32
    assert h1["pearson_r_within"] == pytest.approx(1.0)
    assert h2["pearson_r_within"] == pytest.approx(1.0)


def test_split_half_sign_flip_disclosure_only() -> None:
    # 前半 +1 / 后半 −1 → 同号判据拒 (不能因样本大而资格化)
    s = split_half_within(stock_feature_table(_paired_days(32, flip_second_half=True)),
                          "trigger_strength")
    assert s is not None and s["verdict"] == "只披露"


def test_split_half_insufficient_events() -> None:
    s = split_half_within(stock_feature_table(_paired_days(4)),
                          "trigger_strength")
    assert s is not None and s["verdict"] == "样本不足 — 只披露"


def test_split_half_degenerate_half() -> None:
    # 后半组内收益恒定 → 去均值 y 全 0 → syy=0 → r=None (n_events 达标)
    rows = []
    for i in range(32):
        rets = (0.01, 0.03) if i < 16 else (0.02, 0.02)
        rows.append(_row(20260101 + i, f"A{i:02d}", strength=0.50,
                         ret=rets[0], industry="电子"))
        rows.append(_row(20260101 + i, f"B{i:02d}", strength=0.60,
                         ret=rets[1], industry="电子"))
    s = split_half_within(stock_feature_table(pd.DataFrame(rows)),
                          "trigger_strength")
    assert s is not None and s["verdict"] == "特征退化 — 只披露"
    assert s["halves"][0]["pearson_r_within"] == pytest.approx(1.0)
    assert s["halves"][1]["pearson_r_within"] is None


# ---------------------------------------------------------------------------
# payload / 渲染 / CLI
# ---------------------------------------------------------------------------

def test_payload_md_json_deterministic_and_disclosures(tmp_path) -> None:
    ev = _world_b()
    csv_path = tmp_path / "event_table_v1.csv"
    ev.to_csv(csv_path, index=False)
    p1 = build_payload(ev, csv_path, report_date="20260906")
    p2 = build_payload(ev, csv_path, report_date="20260906")
    j1 = json.dumps(p1, ensure_ascii=False, sort_keys=True, indent=1)
    j2 = json.dumps(p2, ensure_ascii=False, sort_keys=True, indent=1)
    assert j1 == j2  # 零 RNG 主面 + seeded CI: 两次构建逐字节同
    assert p1["caliber"]["universe_rows"] == 4
    assert p1["caliber"]["days"] == 2
    assert "0.65%" in p1["caliber"]["caliber_note"]
    assert "fixed_effect_note" in p1["caliber"]

    md1 = render_md(p1)
    assert md1 == render_md(p2)
    assert "宪法 #2" in md1
    assert "净=毛−0.65%" in md1
    assert "T0 可观测性" in md1
    assert "gap_t1_open" in md1  # T+1 列显式排除的披露在 MD 可见
    assert "日固定效应" in md1
    assert "content_digest=" in md1
    assert p1["court_binding"]["rows"] == 4
    assert p1["court_binding"]["content_digest"] is not None
    # 恒等面: stock_features 表在 JSON 且逐格可复算
    assert len(p1["stock_features"]) == 4


def test_date_str_rejects_non_8digit(tmp_path) -> None:
    # R119 P2 同族纪律: 日期形状守卫, banana 不得产出工件
    ev = _world_b()
    csv_path = tmp_path / "event_table_v1.csv"
    ev.to_csv(csv_path, index=False)
    report_dir = tmp_path / "reports"
    with pytest.raises(SystemExit, match="8 位数字"):
        main(["--court-table", str(csv_path), "--report-dir", str(report_dir),
              "--date-str", "banana"])
    assert not report_dir.exists()  # 拒绝路径零文件落盘
    with pytest.raises(SystemExit, match="8 位数字"):
        main(["--court-table", str(csv_path), "--report-dir", str(report_dir),
              "--date-str", "202609061234"])
    rc = main(["--court-table", str(csv_path), "--report-dir", str(report_dir),
               "--date-str", "20260906"])
    assert rc == 0
    assert (report_dir / "stock_feature_attribution_20260906.md").exists()
    assert (report_dir / "stock_feature_attribution_20260906.json").exists()


def test_primary_horizon_pinned() -> None:
    assert PRIMARY_HORIZON == 10  # T+10 合约; 变更 = 新证据世代
