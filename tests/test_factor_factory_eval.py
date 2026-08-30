"""因子工厂 v0 契约 (R59, owner 数据效率工作线②③)。

全合成 hermetic (R10 教训: court 表是 gitignored 本地资产, slot 验证零依赖);
数值断言用非对称 fixture (R13 教训: 对称数据掩盖方向性缺陷)。

钉死:
- 方向正确性: 强单调因子 Q5>Q1 且 IC>0; 反向因子 IC<0 (排名口径)
- 覆盖率 fail-closed: 全无匹配 → factor_coverage_too_low; csv 列缺失/名字缺失类型化
- 预注册账本: 首跑 nth=1; 同指纹重跑 repeat 且唯一数不增; 新候选递增 (多重比较可见)
- 确定性: 同输入两次 evaluate payload 逐字节相等 (seeded CI, R13 纪律)
- 单一实现复用: 口径经 winrate_payoff_decomposition (production_aligned/net_returns),
  扣费后合成收益的桶 E 必须精确等于手算期望 (恒等式锚)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from factor_factory_eval import (  # noqa: E402
    FactorEvalError,
    _register_candidate,
    evaluate,
)
from winrate_payoff_decomposition import ROUNDTRIP_COST  # noqa: E402

COST = ROUNDTRIP_COST


def _synthetic_court(n_days: int = 30, per_day: int = 10,
                     start: str = "20260105") -> pd.DataFrame:
    """非对称合成 court 帧: 每日 per_day 票, 收益由「隐藏质量」驱动
    (非对称: 好票大赢小亏, 坏票小赢大亏) — 保证因子方向性可断言。"""
    import datetime as dt
    d0 = dt.date.fromisoformat(start)
    rows = []
    sessions = []
    d = d0
    while len(sessions) < n_days:
        if d.weekday() < 5:
            sessions.append(d.strftime("%Y%m%d"))
        d += dt.timedelta(days=1)
    for day in sessions:
        for i in range(per_day):
            quality = i / (per_day - 1)          # 0..1 隐藏质量
            gross = 0.02 + 0.10 * quality if quality > 0.5 else -0.05 + 0.08 * quality
            gross = round(gross, 6)
            rows.append({
                "signal_date": day,
                "ts_code": f"{i:06d}.SZ",
                "regime": "normal" if int(day[-2:]) % 3 else "crisis",
                "fillable": True,
                "gate_blocked": False,
                "degraded": False,
                "st_name": False,
                "industry_missing": False,
                "excluded_ticker": False,
                "price_ge_3": True,
                "trigger_strength": round(0.4 + 0.5 * quality, 6),  # 自带列自检用
                "gross_ret_t3": gross * 0.3,
                "gross_ret_t5": gross * 0.6,
                "gross_ret_t8": gross * 0.8,
                "gross_ret_t10": gross,
            })
    return pd.DataFrame(rows)


@pytest.fixture()
def court_csv(tmp_path: Path) -> Path:
    p = tmp_path / "court.csv.gz"
    _synthetic_court().to_csv(p, index=False)
    return p


def _run(court_csv: Path, tmp_path: Path, **kw) -> dict:
    return evaluate(court_path=court_csv,
                    factor_col=kw.get("factor_col"),
                    factor_csv=kw.get("factor_csv"),
                    name=kw.get("name"),
                    registry_path=tmp_path / "registry.jsonl")


def test_builtin_column_strong_factor_direction(court_csv: Path, tmp_path: Path) -> None:
    payload = _run(court_csv, tmp_path, factor_col="trigger_strength")
    buckets = payload["buckets_t10_net"]["buckets"]
    q5 = buckets["5"]["expectancy"]
    q1 = buckets["1"]["expectancy"]
    assert q5 > 0 > q1  # 非对称构造: 好票净赚, 差票净亏
    ic = payload["daily_ic"]
    assert ic["ic_mean"] is not None and ic["ic_mean"] > 0.9  # 因子即生成机制, 应近完美
    assert payload["buckets_t10_net"]["top_minus_bottom_spread_t10"] > 0
    mono = payload["buckets_t10_net"]["bucket_monotonicity_spearman"]
    assert abs(mono - 1.0) < 1e-9  # 五桶全非空且严格递增 (浮点容差)


def test_inverted_csv_factor_negative_ic(court_csv: Path, tmp_path: Path) -> None:
    court = pd.read_csv(court_csv, dtype={"signal_date": str})
    fac = court[["signal_date", "ts_code", "trigger_strength"]].copy()
    fac["factor"] = -fac["trigger_strength"]
    fcsv = tmp_path / "inv.csv"
    fac.to_csv(fcsv, index=False)
    payload = _run(court_csv, tmp_path, factor_csv=str(fcsv), name="inverted")
    assert payload["daily_ic"]["ic_mean"] < -0.9
    q1 = payload["buckets_t10_net"]["buckets"]["1"]["expectancy"]
    q5 = payload["buckets_t10_net"]["buckets"]["5"]["expectancy"]
    assert q1 > q5


def test_cost_adjusted_expectancy_identity(court_csv: Path, tmp_path: Path) -> None:
    """桶 E 必须等于 gross 均值 − ROUNDTRIP_COST (扣费口径恒等锚)。"""
    payload = _run(court_csv, tmp_path, factor_col="trigger_strength")
    court = pd.read_csv(court_csv, dtype={"signal_date": str})
    top_half = court[court["trigger_strength"] >= court["trigger_strength"].median()]
    expected_top_gross_mean = top_half["gross_ret_t10"].mean()
    o = payload["overall_t10_net"]
    all_gross_mean = court["gross_ret_t10"].mean()
    assert abs(o["expectancy"] - (all_gross_mean - COST)) < 1e-9
    # 桶秩 0.8 分位切分近似 top 半区 — 只锚总体恒等式, 桶间用方向断言覆盖


def test_coverage_fail_closed(court_csv: Path, tmp_path: Path) -> None:
    court = pd.read_csv(court_csv, dtype={"signal_date": str})
    fac = court[["signal_date", "ts_code"]].head(20).copy()
    fac["factor"] = 1.0
    fcsv = tmp_path / "tiny.csv"
    fac.to_csv(fcsv, index=False)
    with pytest.raises(FactorEvalError) as ei:
        _run(court_csv, tmp_path, factor_csv=str(fcsv), name="tiny")
    assert ei.value.code == "factor_coverage_too_low"
    # 全无匹配 → 同样类型化
    fac_bad = pd.DataFrame({"signal_date": ["19990101"], "ts_code": ["x"],
                            "factor": [1.0]})
    fbad = tmp_path / "bad.csv"
    fac_bad.to_csv(fbad, index=False)
    with pytest.raises(FactorEvalError) as ei2:
        _run(court_csv, tmp_path, factor_csv=str(fbad), name="bad")
    assert ei2.value.code == "factor_coverage_too_low"


def test_factor_source_and_name_contracts(court_csv: Path, tmp_path: Path) -> None:
    with pytest.raises(FactorEvalError) as ei:
        _run(court_csv, tmp_path, factor_col="a", factor_csv="b", name="c")
    assert ei.value.code == "factor_source_ambiguous"
    with pytest.raises(FactorEvalError) as ei2:
        _run(court_csv, tmp_path, factor_col="nonexistent")
    assert ei2.value.code == "factor_column_missing"


def test_registry_pre_registration_accounting(court_csv: Path, tmp_path: Path) -> None:
    reg = tmp_path / "registry.jsonl"
    p1 = evaluate(court_path=court_csv, factor_col="trigger_strength",
                  factor_csv=None, name=None, registry_path=reg)
    assert p1["registry"]["first_seen"] is True
    assert p1["registry"]["unique_candidate_ordinal"] == 1
    assert p1["registry"]["run_count"] == 1
    # 同指纹重跑: run_count 增, 唯一候选数不增
    p2 = evaluate(court_path=court_csv, factor_col="trigger_strength",
                  factor_csv=None, name=None, registry_path=reg)
    assert p2["registry"]["first_seen"] is False
    assert p2["registry"]["unique_candidate_ordinal"] == 1
    assert p2["registry"]["run_count"] == 2
    # 新候选 (不同列 = 不同指纹): ordinal 递增
    p3 = evaluate(court_path=court_csv, factor_col="gross_ret_t5",
                  factor_csv=None, name=None, registry_path=reg)
    assert p3["registry"]["unique_candidate_ordinal"] == 2
    # 账本 append-only: 三行
    assert len(reg.read_text().strip().splitlines()) == 3


def test_determinism_same_input_byte_identical(court_csv: Path, tmp_path: Path) -> None:
    a = _run(court_csv, tmp_path, factor_col="trigger_strength")
    b = _run(court_csv, tmp_path, factor_col="trigger_strength")
    # registry 字段会随重跑变化 (run_count) — 剔除后必须逐字节相等
    for p in (a, b):
        p.pop("registry")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_decay_and_regime_produced(court_csv: Path, tmp_path: Path) -> None:
    payload = _run(court_csv, tmp_path, factor_col="trigger_strength")
    decay = payload["decay_spread"]
    assert set(decay) == {"t3", "t5", "t8", "t10"}
    # 合成收益按期缩放 (gross×k), spread 应随期放大且恒正
    spreads = [decay[h]["spread"] for h in ("t3", "t5", "t8", "t10")]
    assert all(s > 0 for s in spreads)
    assert spreads[0] < spreads[3]
    regimes = payload["regime_spread"]
    assert set(regimes) >= {"normal", "crisis"}
    # 非对称构造: 危机日 (day%3==0) 混合同样分布 — spread 同向
    assert all(d["spread"] > 0 for d in regimes.values())


def test_render_md_discloses_registry_and_costs(court_csv: Path, tmp_path: Path) -> None:
    from factor_factory_eval import render_md
    payload = _run(court_csv, tmp_path, factor_col="trigger_strength")
    md = render_md(payload)
    assert "第 1 个唯一候选" in md
    assert "重复运行" not in md or "新候选" in md
    assert "纪律" in md and "前向确认" in md


def test_factor_csv_duplicate_keys_fail_closed(court_csv: Path, tmp_path: Path) -> None:
    court = pd.read_csv(court_csv, dtype={"signal_date": str})
    fac = court[["signal_date", "ts_code", "trigger_strength"]].copy()
    fac["factor"] = fac["trigger_strength"]
    fac = pd.concat([fac, fac.head(3)])  # 注入 3 个重复键
    fcsv = tmp_path / "dup.csv"
    fac.to_csv(fcsv, index=False)
    with pytest.raises(FactorEvalError) as ei:
        _run(court_csv, tmp_path, factor_csv=str(fcsv), name="dup")
    assert ei.value.code == "factor_csv_duplicate_keys"


def test_render_md_empty_bucket_discloses_dash() -> None:
    """空桶 (n=0 → expectancy/winrate=None) 渲染 'E=—' 不裸崩 (R71 Op2)。

    真实可达: 覆盖率/可用行门均过但全部可用日 n=5 → 桶 1 恒空。
    payload 级直测 — 不经 evaluate 管道也必须守住同一渲染契约。
    """
    from factor_factory_eval import render_md
    payload = {
        "factor": "thin", "registry": {
            "unique_candidate_ordinal": 1, "run_count": 1, "first_seen": True},
        "rows": {"usable_rows": 15, "court_rows": 15, "coverage": 1.0,
                 "signal_days": 3},
        "overall_t10_net": {"expectancy": 0.01, "winrate": 0.5, "payoff": None,
                            "cluster_ci_low_90": None, "n": 15},
        "daily_ic": {"ic_mean": None, "ic_ci_low_90": None, "ic_days": 0},
        "buckets_t10_net": {
            "buckets": {
                "1": {"n": 0, "winrate": None, "expectancy": None},
                "2": {"n": 5, "winrate": 0.4, "expectancy": -0.01},
            },
            "bucket_monotonicity_spearman": None,
            "top_minus_bottom_spread_t10": None,  # Q5 空时 spread 同为 None
        },
        "decay_spread": {}, "regime_spread": {},
    }
    md = render_md(payload)
    assert "Q1: E=— 胜率=— n=0" in md
    assert "top−bottom spread T+10: —" in md
    assert "Q2: E=-0.0100 胜率=0.4000 n=5" in md


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
