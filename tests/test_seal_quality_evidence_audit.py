"""封板质量证据审计契约 (R71)。

全合成 hermetic (R10 教训: court/lu 数据面是 gitignored 本地资产, slot 验证
零依赖); 数值断言用非对称 fixture (R13 教训: 对称数据掩盖方向性缺陷)。

钉死:
- PIT 隔离: 毒化 lu_{D+1} 不改变 factor(D); 存储因子可仅由 lu_D 独立重算精确复现
- 腿语义: 方向变换正确 (早封/少炸/大封单 → 高因子), 畸形腿逐腿计数不崩溃, 方向翻转→defect
- 覆盖定因: lu 缺文件/不在快照/三腿全缺/带腿丢行 (unclassified=构建器丢行缺陷) 四类互斥完备
- 覆盖偏差: 无偏 → CI 跨 0; uncovered 系统性更差 → CI 排除 0 (coverage_bias_detected)
- 独立 IC: rank_pct_average 并列语义与 pandas 一致; 独立 Spearman 与工厂路径同值;
  与工厂报告交叉超差 → defect
- 确定性: 同一世界两次 run_audit 输出逐字节相等 (无时间戳, per-call seeded)
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from audit_seal_quality_evidence import (  # noqa: E402
    SealAuditError,
    classify_coverage,
    rank_pct_average,
    recompute_day_factor,
    run_audit,
    spearman_independent,
)
from build_seal_quality_factor import build_factor  # noqa: E402 (fixture 用真实构建器)

# 非对称合成世界: 3 个信号日, 每日 8 票; 因子日 D=20260105
D0, D1, D2 = "20260105", "20260106", "20260107"
TICKERS = [f"{i:06d}.SZ" for i in range(8)]


def _lu_row(ts: str, first: int, opens: int, fd: float) -> dict:
    return {"ts_code": ts, "first_time": first, "open_times": opens,
            "fd_amount": fd}


def _write_lu(directory: Path, day: str, rows: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(directory / f"lu_{day}.csv", index=False)


def _default_lu_rows() -> list[dict]:
    """非对称: ts 0=早封/零炸/大封单 (高质量) … ts 7=晚封/多炸/小封单 (低质量)。"""
    rows = []
    for i, ts in enumerate(TICKERS):
        q = i / (len(TICKERS) - 1)  # 0..1, 大=低质量
        rows.append(_lu_row(
            ts,
            first=int(93000 + q * (140000 - 93000)),
            opens=int(round(q * 6)),
            fd=round(5e8 * (1 - q) + 1e6, 2),
        ))
    return rows


def _synthetic_court(days: list[str], tickers: list[str],
                     ret_of=None, factor_of=None) -> pd.DataFrame:
    """court 帧: 生产过滤列齐全 (全通过), 收益由注入函数驱动。"""
    rows = []
    for day in days:
        for i, ts in enumerate(tickers):
            gross = ret_of(day, i) if ret_of else 0.01
            rows.append({
                "signal_date": day,
                "ts_code": ts,
                "regime": "normal",
                "fillable": True,
                "gate_blocked": False,
                "degraded": False,
                "st_name": False,
                "industry_missing": False,
                "excluded_ticker": False,
                "price_ge_3": True,
                "trigger_strength": 0.6,
                "gross_ret_t3": gross,
                "gross_ret_t5": gross,
                "gross_ret_t8": gross,
                "gross_ret_t10": gross,
            })
    return pd.DataFrame(rows)


def _factor_rows(days: list[str], tickers: list[str], value_of=None) -> pd.DataFrame:
    rows = []
    for day in days:
        for i, ts in enumerate(tickers):
            rows.append({"signal_date": day, "ts_code": ts,
                         "factor": value_of(day, i) if value_of else 0.5 + i / 100})
    return pd.DataFrame(rows)


@pytest.fixture()
def world(tmp_path: Path):
    """lu 两天 (D0 主日 + D1 干扰日) + court 三天 + 存储因子 (仅 D0)。"""
    lu = tmp_path / "limit_up"
    _write_lu(lu, D0, _default_lu_rows())
    _write_lu(lu, D1, _default_lu_rows())  # 干扰日: 内容不同也不该影响 D0
    court_days = [D0, D1, D2]

    def ret_of(day: str, i: int) -> float:
        # 因子与收益反向 (封板反转语义): 高因子 → 低收益
        return round(0.10 - 0.02 * i, 6)

    court = _synthetic_court(court_days, TICKERS, ret_of=ret_of)
    court_path = tmp_path / "court.csv.gz"
    court.to_csv(court_path, index=False, compression="gzip")
    # 存储因子 = 真实构建器从合成快照产出 (隔离复现比对才有意义)
    calendar = tmp_path / "calendar.json"
    calendar.write_text(json.dumps([D0, D1, D2]))
    factor, _summary = build_factor(lu_dir=lu, calendar_path=calendar,
                                    start=D0, end=D1)
    factor_path = tmp_path / "seal_quality_v0.csv"
    factor.to_csv(factor_path, index=False)
    return {"lu": lu, "court": court_path, "factor": factor_path,
            "ret_of": ret_of}


def test_pit_isolation_poison_day_plus_one(world, tmp_path):
    """毒化 D+1 快照后 factor(D) 独立重算逐字节不变 (结构性隔离);
    还原后 iso 腿对一致世界验证「存储可仅由 lu_D 复现」。"""
    before = recompute_day_factor(world["lu"] / f"lu_{D0}.csv")
    poisoned = _default_lu_rows() + [_lu_row("999999.SZ", 92500, 0, 1e9)]
    _write_lu(world["lu"], D1, poisoned)
    after = recompute_day_factor(world["lu"] / f"lu_{D0}.csv")
    assert before == after
    # 文件与构建时不一致 → iso 如实报 stale (不静默); 还原后复现成立
    payload_stale = run_audit(court_path=world["court"], lu_dir=world["lu"],
                              factor_csv=world["factor"],
                              factory_eval_json=tmp_path / "absent.json")
    assert payload_stale["pit_isolation"]["ok"] is False  # D1 漂移被抓
    _write_lu(world["lu"], D1, _default_lu_rows())
    payload = run_audit(court_path=world["court"], lu_dir=world["lu"],
                        factor_csv=world["factor"],
                        factory_eval_json=tmp_path / "absent.json")
    iso = payload["pit_isolation"]
    assert iso["ok"] is True
    assert iso["days_checked"] == 2 and iso["rows_checked"] == 16
    assert iso["mismatch_count"] == 0 and iso["missing_lu_count"] == 0


def test_isolation_mismatch_detected(world, tmp_path):
    """存储因子被篡改 (含 lu_D 之外的值) → 隔离复现抓到 mismatch。"""
    fac = pd.read_csv(world["factor"])
    fac.loc[0, "factor"] = 0.123456
    tampered = tmp_path / "tampered.csv"
    fac.to_csv(tampered, index=False)
    payload = run_audit(court_path=world["court"], lu_dir=world["lu"],
                        factor_csv=tampered,
                        factory_eval_json=tmp_path / "absent.json")
    assert payload["pit_isolation"]["ok"] is False
    assert payload["verdict"] == "defects_found"
    assert "pit_isolation" in payload["defects"]


def test_leg_direction_semantics_and_flip(world, tmp_path):
    """存储因子与原始腿方向一致 (早封/少炸/大封单 → 高因子);
    存储因子以翻转方向构建 → leg_semantics defect (探测对存储工件判别)。"""
    payload = run_audit(court_path=world["court"], lu_dir=world["lu"],
                        factor_csv=world["factor"],
                        factory_eval_json=tmp_path / "absent.json")
    sem = payload["leg_semantics"]
    assert sem["ok"] is True
    assert sem["pooled_spearman"]["factor_vs_first_time"] < 0
    assert sem["pooled_spearman"]["factor_vs_open_times"] < 0
    assert sem["pooled_spearman"]["factor_vs_fd_amount"] > 0

    # 违反世界: legs 正常 (质量随 i 下降 → 正确因子应随 i 下降),
    # 存储因子却随 i 上升 (晚封→高分) → 方向违反被抓
    inverted = tmp_path / "inverted_factor.csv"
    _factor_rows([D0, D1], TICKERS, value_of=lambda d, i: 0.5 + i / 100).to_csv(
        inverted, index=False)
    payload2 = run_audit(court_path=world["court"], lu_dir=world["lu"],
                         factor_csv=inverted,
                         factory_eval_json=tmp_path / "absent.json")
    assert payload2["leg_semantics"]["ok"] is False
    assert "leg_semantics" in payload2["defects"]


def test_malformed_legs_counted_not_crash(world, tmp_path):
    """非数值腿 → 腿剔除 (NaN) 不崩溃, 形状探测逐腿计数。"""
    rows = _default_lu_rows()
    rows[0]["first_time"] = "not_a_number"
    rows[1]["open_times"] = -3  # 形状非法 (负炸板数)
    _write_lu(world["lu"], D0, rows)
    payload = run_audit(court_path=world["court"], lu_dir=world["lu"],
                        factor_csv=world["factor"],
                        factory_eval_json=tmp_path / "absent.json")
    sem = payload["leg_semantics"]
    assert sem["malformed_legs"]["open_times"] == 1
    assert sem["ok"] is False  # 形状非法即 defect (fail-closed)
    # ts0 首封腿缺失 → 因子仍由其余腿均值给出 (不冒充中性值)
    recomputed = recompute_day_factor(world["lu"] / f"lu_{D0}.csv")
    assert TICKERS[0] in recomputed  # 另两腿仍在


def test_missing_lu_column_typed(world, tmp_path):
    lu_bad = tmp_path / "lu_bad"
    lu_bad.mkdir()
    pd.DataFrame([{"ts_code": "000001.SZ", "first_time": 93000}]).to_csv(
        lu_bad / f"lu_{D0}.csv", index=False)
    with pytest.raises(SealAuditError) as excinfo:
        recompute_day_factor(lu_bad / f"lu_{D0}.csv")
    assert "lu_snapshot_missing_columns" in str(excinfo.value)


def test_coverage_classification_four_classes(tmp_path):
    """lu 缺文件 / 不在快照 / 三腿全缺 / 带腿丢行 四类互斥完备。"""
    lu = tmp_path / "limit_up"
    # D0: 8 票全封; D1: 只给 ts1..ts7 (ts0 当日榜缺) → not_in_lu_universe
    _write_lu(lu, D0, _default_lu_rows())
    _write_lu(lu, D1, _default_lu_rows()[1:])
    # D2: 文件缺失 → lu_file_missing
    court_days = [D0, D1, D2]
    court_path = tmp_path / "court.csv.gz"
    _synthetic_court(court_days, TICKERS).to_csv(court_path, index=False,
                                                 compression="gzip")
    # 因子: D0 全覆盖; D1 覆盖 ts1..ts7; D2 无 (lu 缺文件)
    frows = _factor_rows([D0], TICKERS)
    frows = pd.concat([frows, _factor_rows([D1], TICKERS[1:])])
    factor_path = tmp_path / "factor.csv"
    frows.to_csv(factor_path, index=False)

    cov = classify_coverage(factor_path, court_path, lu)
    cls = cov["classification"]
    assert cls["covered"] == 8 + 7
    assert cls["not_in_lu_universe"] == 1  # D1 ts0
    assert cls["lu_file_missing"] == 8    # D2 全部
    assert cls["all_legs_missing"] == 0
    assert cls["unclassified"] == 0

    # 带腿丢行: D1 快照恢复 8 票但因子仍只有 7 票 → 丢行缺陷被抓
    _write_lu(lu, D1, _default_lu_rows())
    cov2 = classify_coverage(factor_path, court_path, lu)
    assert cov2["classification"]["unclassified"] == 1
    assert cov2["ok"] is False


def test_coverage_bias_detection(tmp_path):
    """无偏 → CI 跨 0; uncovered 系统性更差 → CI 排除 0 (coverage_bias_detected)。"""
    lu = tmp_path / "limit_up"
    # 快照只封 6 票: uncovered (ts6/ts7) = 触及未封 → not_in_lu_universe 正常类
    _write_lu(lu, D0, _default_lu_rows()[:6])
    _write_lu(lu, D1, _default_lu_rows()[:6])
    court_path = tmp_path / "court.csv.gz"
    # 非对称: uncovered 固定大负, covered 固定正 — 偏倚可断言
    court = pd.concat([
        _synthetic_court([D0, D1], TICKERS[:6], ret_of=lambda d, i: 0.05),
        _synthetic_court([D0, D1], TICKERS[6:], ret_of=lambda d, i: -0.10),
    ])
    court.to_csv(court_path, index=False, compression="gzip")
    factor_path = tmp_path / "factor.csv"
    _factor_rows([D0, D1], TICKERS[:6]).to_csv(factor_path, index=False)

    cov = classify_coverage(factor_path, court_path, lu)
    assert cov["covered"]["n"] == 12 and cov["uncovered"]["n"] == 4
    assert cov["diff_covered_minus_uncovered"]["ci90_low"] > 0
    assert cov["ok"] is False

    # 无偏世界: covered/uncovered 同分布 (奇偶交替收益, 非全同值 —
    # 全同值 fixture 的 CI 退化到浮点噪声宽度, 无法断言跨 0)
    court_ok = _synthetic_court(
        [D0, D1], TICKERS,
        ret_of=lambda d, i: 0.02 if i % 2 == 0 else -0.01)
    court_ok_path = tmp_path / "court_ok.csv.gz"
    court_ok.to_csv(court_ok_path, index=False, compression="gzip")
    factor_ok = tmp_path / "factor_ok.csv"
    _factor_rows([D0, D1], TICKERS[:6]).to_csv(factor_ok, index=False)
    cov_ok = classify_coverage(factor_ok, court_ok_path, lu)
    d = cov_ok["diff_covered_minus_uncovered"]
    assert d["ci90_low"] <= 0 <= d["ci90_high"]
    assert cov_ok["ok"] is True


def test_rank_pct_average_ties_match_pandas():
    """并列取平均秩 / 非空数 — 与 pandas rank(pct=True) 逐值一致。"""
    rng = np.random.default_rng(7)
    for trial in range(20):
        vals = [None, None] + [round(float(rng.uniform(0, 1)), 3) for _ in range(10)]
        vals[3] = vals[5]  # 人造并列
        mine = rank_pct_average(vals)
        ref = pd.Series(vals).rank(pct=True).tolist()
        for m, r in zip(mine, ref):
            if m is None:
                assert math.isnan(r)
            else:
                assert abs(m - r) < 1e-12


def test_spearman_independent_known_value():
    """教科书值: 单调递增 → +1; 反序 → −1; 已知小样本 0.824 (n=5, 有并列外值)。"""
    assert spearman_independent([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman_independent([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    x = [1, 2, 3, 4, 5]
    y = [2, 1, 4, 3, 5]
    # 秩: y_ranks=[2,1,4,3,5], Σd²=4 → ρ = 1 − 24/120 = 0.8 (教科书精确值)
    assert spearman_independent(x, y) == pytest.approx(0.8, abs=1e-12)


def test_ic_crosscheck_tolerance(tmp_path, world):
    """独立 IC 与工厂报告差 >tol → ic_crosscheck defect; 缺报告 → 如实 skip 不假阳性。"""
    factory = tmp_path / "factory_eval.json"
    ev = pd.read_csv(world["court"], dtype={"signal_date": str})
    from winrate_payoff_decomposition import production_aligned, net_returns
    aligned = production_aligned(ev)
    fac = pd.read_csv(world["factor"], dtype={"signal_date": str, "ts_code": str})
    work = aligned.merge(fac.rename(columns={"factor": "cand"})[["signal_date", "ts_code", "cand"]],
                         on=["signal_date", "ts_code"], how="inner")
    work["net"] = net_returns(work["gross_ret_t10"].tolist())
    work = work.dropna(subset=["cand", "net"])
    daily = []
    for _, grp in work.groupby("signal_date"):
        if len(grp) < 5:
            continue
        daily.append(spearman_independent(grp["cand"].tolist(), grp["net"].tolist()))
    ic_mean = sum(daily) / len(daily)
    factory.write_text(json.dumps({"payload": {"daily_ic": {"ic_mean": float(ic_mean)}}}))
    payload = run_audit(court_path=world["court"], lu_dir=world["lu"],
                        factor_csv=world["factor"], factory_eval_json=factory)
    assert payload["ic_crosscheck"]["ok"] is True

    factory_bad = tmp_path / "factory_bad.json"
    factory_bad.write_text(json.dumps({"payload": {"daily_ic": {"ic_mean": float(ic_mean) + 0.05}}}))
    payload_bad = run_audit(court_path=world["court"], lu_dir=world["lu"],
                            factor_csv=world["factor"], factory_eval_json=factory_bad)
    assert payload_bad["ic_crosscheck"]["ok"] is False
    assert "ic_crosscheck" in payload_bad["defects"]

    # 报告缺失: crosscheck ok=False (无从交叉), 但如实披露 factory_ic=None
    payload_none = run_audit(court_path=world["court"], lu_dir=world["lu"],
                             factor_csv=world["factor"],
                             factory_eval_json=tmp_path / "absent.json")
    assert payload_none["ic_crosscheck"]["ic_mean_factory"] is None


def test_audit_determinism(world, tmp_path):
    """同一世界两次 run_audit 输出逐字节相等 (无时间戳 + per-call seeded)。"""
    a = run_audit(court_path=world["court"], lu_dir=world["lu"],
                  factor_csv=world["factor"], factory_eval_json=tmp_path / "absent.json")
    b = run_audit(court_path=world["court"], lu_dir=world["lu"],
                  factor_csv=world["factor"], factory_eval_json=tmp_path / "absent.json")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_factor_missing_typed(world, tmp_path):
    with pytest.raises(SealAuditError) as excinfo:
        run_audit(court_path=world["court"], lu_dir=world["lu"],
                  factor_csv=tmp_path / "nope.csv",
                  factory_eval_json=tmp_path / "absent.json")
    assert "factor_csv_not_found" in str(excinfo.value)
