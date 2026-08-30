"""因子工厂评估机器差分回归 (R71 Op2, 对抗审查收口)。

全合成 hermetic (R10 教训); 数值断言非对称 fixture (R13 教训)。

钉死:
- render_md 空桶不崩: 全部可用日 n=5 (桶1 恒空) → 'Q1: E=—' 而非 TypeError
  (对抗审查发现: f'{None:.4f}' 裸崩, 正常生产路径可达)
- 桶边界 exactness: n=5..40 全部 k/n 的 int(pct*5)+1 桶分配与名义五分位
  逐值相等 (浮点边界 0.2/0.4/0.6/0.8 钉死)
- 五分位谓词一致性: bucket∈{1,5} 行集合与 decay/regime 的 pct<0.2 / ≥0.8
  集合逐行相等 (同一 universe 不得两套分桶语义)
- 全块差分: overall/daily_ic/buckets/decay/regime 五块 vs 独立重算
  (测试内自带 rank/pearson/E 实现, 不复用被测工具内部) ±1e-9
- 统计块确定性: 独立 registry 两次 evaluate 统计块逐字节相等 (R13)
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from factor_factory_eval import evaluate, render_md  # noqa: E402
from winrate_payoff_decomposition import (  # noqa: E402
    ROUNDTRIP_COST,
    production_aligned,
)

# ---------------------------------------------------------------------------
# 独立数值基元 (被测工具不能自证 — 测试内自带实现)
# ---------------------------------------------------------------------------

def _rank_pct(values: list[float]) -> list[float]:
    """平均秩百分比 (并列取平均 1-based 秩 / 非空数)。"""
    valid = [i for i, v in enumerate(values) if not math.isnan(v)]
    out = [float("nan")] * len(values)
    if not valid:
        return out
    keyed = sorted(valid, key=lambda i: values[i])
    ranks: dict[int, float] = {}
    i = 0
    while i < len(keyed):
        j = i
        while j + 1 < len(keyed) and values[keyed[j + 1]] == values[keyed[i]]:
            j += 1
        avg = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[keyed[k]] = avg
        i = j + 1
    for idx in valid:
        out[idx] = ranks[idx] / len(valid)
    return out


def _spearman(xs: list[float], ys: list[float]) -> float:
    rx, ry = _rank_pct(xs), _rank_pct(ys)
    pairs = [(a, b) for a, b in zip(rx, ry) if not math.isnan(a) and not math.isnan(b)]
    n = len(pairs)
    if n < 2:
        return float("nan")
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    sx = sum((p[0] - mx) ** 2 for p in pairs)
    sy = sum((p[1] - my) ** 2 for p in pairs)
    return sxy / math.sqrt(sx * sy)


def _bucket_of(pct: float) -> int:
    v = min(pct * 5, 4.999)
    return int(v) + 1


# ---------------------------------------------------------------------------
# 合成世界: 混合日宽 (12/8/5)、并列秩、缺 T+10、crisis/normal 混合
# ---------------------------------------------------------------------------

DAYS = ["20260105", "20260106", "20260107", "20260108"]
WIDTHS = [12, 8, 5, 10]


def _world() -> tuple[pd.DataFrame, pd.DataFrame]:
    """返回 (court 帧, 因子帧)。因子与收益反向 (非对称: 强因子票小赢/弱因子票大亏)。"""
    rows, frows = [], []
    for day, width in zip(DAYS, WIDTHS):
        for i in range(width):
            ts = f"{i:06d}.SZ"
            q = i / max(width - 1, 1)  # 0..1
            gross = round(0.06 - 0.12 * q, 6)  # 高因子 → 低收益 (非对称)
            if day == DAYS[1] and i == 3:
                gross = None  # 缺 T+10 (现实缺口)
            rows.append({
                "signal_date": day,
                "ts_code": ts,
                "regime": "crisis" if int(day[-2:]) % 2 else "normal",
                "fillable": True,
                "gate_blocked": False,
                "degraded": False,
                "st_name": False,
                "industry_missing": False,
                "excluded_ticker": False,
                "price_ge_3": True,
                "trigger_strength": round(0.4 + 0.5 * q, 6),
                "gross_ret_t3": None if gross is None else gross * 0.3,
                "gross_ret_t5": None if gross is None else gross * 0.6,
                "gross_ret_t8": None if gross is None else gross * 0.8,
                "gross_ret_t10": gross,
            })
            frows.append({"signal_date": day, "ts_code": ts,
                          "factor": round(0.5 + 0.4 * q, 6) + (0.01 if i % 3 == 0 else 0.0)})
    return pd.DataFrame(rows), pd.DataFrame(frows)


@pytest.fixture()
def payload(tmp_path: Path) -> dict:
    court, fac = _world()
    court_path = tmp_path / "court.csv.gz"
    court.to_csv(court_path, index=False, compression="gzip")
    factor_path = tmp_path / "factor.csv"
    fac.to_csv(factor_path, index=False)
    return evaluate(court_path=court_path, factor_col=None,
                    factor_csv=str(factor_path), name="diff_factor",
                    registry_path=tmp_path / "registry.jsonl")


def _independent_recompute(court: pd.DataFrame, fac: pd.DataFrame) -> dict:
    """独立重算五块: overall/daily_ic/buckets/decay/regime (±1e-9 断言用)。"""
    aligned = production_aligned(court)
    aligned = aligned.copy()
    aligned["signal_date"] = aligned["signal_date"].astype(str)
    merged = aligned.merge(fac.assign(signal_date=fac["signal_date"].astype(str)),
                           on=["signal_date", "ts_code"], how="left")
    work = merged.dropna(subset=["factor", "gross_ret_t10"]).copy()
    work["net"] = [None if g is None or (isinstance(g, float) and math.isnan(g))
                   else g - ROUNDTRIP_COST for g in work["gross_ret_t10"]]
    work = work.dropna(subset=["net"])

    nets = work["net"].astype(float).tolist()
    days = work["signal_date"].tolist()
    n = len(nets)
    wins = [r for r in nets if r > 0]
    losses = [r for r in nets if r <= 0]
    p = len(wins) / n
    aw = sum(wins) / len(wins)
    al = sum(losses) / len(losses)
    overall = {"expectancy": p * aw + (1 - p) * al, "winrate": p, "n": n}

    by_day: dict[str, list[tuple[float, float]]] = {}
    for day, f, r in zip(days, work["factor"].astype(float), work["net"].astype(float)):
        by_day.setdefault(day, []).append((f, r))
    ics = []
    for day, pairs in sorted(by_day.items()):
        if len(pairs) < 5:
            continue
        rho = _spearman([f for f, _ in pairs], [r for _, r in pairs])
        if not math.isnan(rho):
            ics.append(rho)
    daily_ic = {"ic_mean": sum(ics) / len(ics), "ic_days": len(ics)}

    pct: dict[tuple[str, str], float] = {}
    for day, grp in by_day.items():
        rp = _rank_pct([f for f, _ in grp])
        for (f, r), pr in zip(grp, rp):
            pct[(day, f)] = pr
    work_key = list(zip(work["signal_date"], work["factor"].astype(float)))
    work = work.assign(pct=[pct[k] for k in work_key],
                       bucket=[_bucket_of(pct[k]) for k in work_key])
    buckets = {}
    for b in range(1, 6):
        sub = work[work["bucket"] == b]["net"].astype(float).tolist()
        if not sub:
            buckets[str(b)] = None
            continue
        w = [r for r in sub if r > 0]
        l = [r for r in sub if r <= 0]
        pb = len(w) / len(sub)
        buckets[str(b)] = {
            "n": len(sub),
            "winrate": pb,
            "expectancy": pb * (sum(w) / len(w) if w else 0.0)
            + (1 - pb) * (sum(l) / len(l) if l else 0.0),
        }
    e_series = [(k, v["expectancy"]) for k, v in buckets.items() if v is not None]
    mono = _spearman([float(k) for k, _ in e_series], [e for _, e in e_series]) \
        if len(e_series) >= 3 else None

    decay = {}
    for h in ("t3", "t5", "t8", "t10"):
        col = f"gross_ret_{h}"
        vals = {row_col: [] for row_col in ()}
        tops, bots = [], []
        for row, k2 in zip(work.itertuples(index=False), work_key):
            pr = pct[k2]
            r = getattr(row, col)
            if r is None or (isinstance(r, float) and math.isnan(r)):
                continue
            if pr >= 0.8:
                tops.append(float(r) - ROUNDTRIP_COST)
            elif pr < 0.2:
                bots.append(float(r) - ROUNDTRIP_COST)
        if tops and bots:
            decay[h] = (sum(tops) / len(tops) - sum(bots) / len(bots),
                        len(tops), len(bots))

    regimes = {}
    for reg in ("normal", "crisis"):
        tops, bots = [], []
        for row, k2 in zip(work.itertuples(index=False), work_key):
            if row.regime != reg:
                continue
            pr = pct[k2]
            r = row.net
            if pr >= 0.8:
                tops.append(float(r))
            elif pr < 0.2:
                bots.append(float(r))
        if tops and bots:
            regimes[reg] = (sum(tops) / len(tops) - sum(bots) / len(bots),
                            len(tops), len(bots))
    return {"overall": overall, "daily_ic": daily_ic, "buckets": buckets,
            "mono": mono, "decay": decay, "regimes": regimes}


def test_full_block_differential_against_independent(tmp_path, payload):
    """evaluate 五块统计 vs 独立重算 (测试内自带实现) ±1e-9。"""
    court, fac = _world()
    ref = _independent_recompute(court, fac)

    o = payload["overall_t10_net"]
    assert o["expectancy"] == pytest.approx(ref["overall"]["expectancy"], abs=1e-9)
    assert o["winrate"] == pytest.approx(ref["overall"]["winrate"], abs=1e-9)
    assert o["n"] == ref["overall"]["n"]

    ic = payload["daily_ic"]
    assert ic["ic_mean"] == pytest.approx(ref["daily_ic"]["ic_mean"], abs=1e-9)
    assert ic["ic_days"] == ref["daily_ic"]["ic_days"]

    for k, ref_v in ref["buckets"].items():
        got = payload["buckets_t10_net"]["buckets"][k]
        if ref_v is None:
            assert got["n"] == 0
            continue
        assert got["expectancy"] == pytest.approx(ref_v["expectancy"], abs=1e-9)
        assert got["winrate"] == pytest.approx(ref_v["winrate"], abs=1e-9)
        assert got["n"] == ref_v["n"]

    for h, (spread, tn, bn) in ref["decay"].items():
        got = payload["decay_spread"][h]
        assert got["spread"] == pytest.approx(spread, abs=1e-9)
    for reg, (spread, tn, bn) in ref["regimes"].items():
        got = payload["regime_spread"][reg]
        assert got["spread"] == pytest.approx(spread, abs=1e-9)
        assert got["top_n"] == tn and got["bottom_n"] == bn


def test_quintile_predicate_consistency(payload):
    """bucket∈{1,5} 行集合与 decay 的 pct<0.2 / ≥0.8 集合逐行一致 (同一语义)。"""
    court, fac = _world()
    aligned = production_aligned(court)
    aligned = aligned.copy()
    aligned["signal_date"] = aligned["signal_date"].astype(str)
    merged = aligned.merge(fac.assign(signal_date=fac["signal_date"].astype(str)),
                           on=["signal_date", "ts_code"], how="left")
    work = merged.dropna(subset=["factor", "gross_ret_t10"]).copy()
    by_day: dict[str, list[tuple[float, str]]] = {}
    for day, f, ts in zip(work["signal_date"], work["factor"], work["ts_code"]):
        by_day.setdefault(day, []).append((float(f), ts))
    pct: dict[str, float] = {}
    for day, pairs in by_day.items():
        rp = _rank_pct([f for f, _ in pairs])
        for (f, ts), pr in zip(pairs, rp):
            pct[ts] = pr
    bucket1 = {ts for ts in pct if _bucket_of(pct[ts]) == 1}
    bucket5 = {ts for ts in pct if _bucket_of(pct[ts]) == 5}
    bottom = {ts for ts in pct if pct[ts] < 0.2}
    top = {ts for ts in pct if pct[ts] >= 0.8}
    assert bucket1 == bottom
    assert bucket5 == top


def test_bucket_boundary_exactness():
    """n=5..40 全部 k/n: int(min(pct*5, 4.999))+1 与名义五分位逐值相等。"""
    for n in range(5, 41):
        for k in range(1, n + 1):
            pct = k / n
            got = _bucket_of(pct)
            nominal = 5 if pct >= 0.8 else int(pct * 5) + 1
            assert got == nominal, (n, k, pct, got, nominal)


def test_render_md_empty_bucket_no_crash(tmp_path):
    """全部可用日 n=5 → 桶1 恒空 → render_md 须 'Q1: E=—' 而非 TypeError (RED→GREEN)。"""
    days = ["20260105", "20260106", "20260107"]
    rows, frows = [], []
    for day in days:
        for i in range(5):  # 每日恰 5 票: pct ∈ {.2,.4,.6,.8,1.0} → 桶1 恒空
            ts = f"{i:06d}.SZ"
            q = i / 4
            rows.append({
                "signal_date": day, "ts_code": ts, "regime": "normal",
                "fillable": True, "gate_blocked": False, "degraded": False,
                "st_name": False, "industry_missing": False,
                "excluded_ticker": False, "price_ge_3": True,
                "trigger_strength": 0.6,
                "gross_ret_t3": 0.01, "gross_ret_t5": 0.01,
                "gross_ret_t8": 0.01, "gross_ret_t10": round(0.06 - 0.12 * q, 6),
            })
            frows.append({"signal_date": day, "ts_code": ts,
                          "factor": round(0.5 + 0.4 * q, 6)})
    court_path = tmp_path / "court.csv.gz"
    pd.DataFrame(rows).to_csv(court_path, index=False, compression="gzip")
    factor_path = tmp_path / "factor.csv"
    pd.DataFrame(frows).to_csv(factor_path, index=False)
    payload = evaluate(court_path=court_path, factor_col=None,
                       factor_csv=str(factor_path), name="thin_factor",
                       registry_path=tmp_path / "registry.jsonl")
    assert payload["buckets_t10_net"]["buckets"]["1"]["n"] == 0
    md = render_md(payload)  # 修复前: TypeError (None.__format__)
    assert "Q1: E=—" in md
    assert "n=0" in md


def test_stats_blocks_deterministic(tmp_path):
    """独立 registry 两次 evaluate → 统计块逐字节相等 (registry 计数按设计递增)。"""
    court, fac = _world()
    court_path = tmp_path / "court.csv.gz"
    court.to_csv(court_path, index=False, compression="gzip")
    factor_path = tmp_path / "factor.csv"
    fac.to_csv(factor_path, index=False)
    stat_keys = ("rows", "overall_t10_net", "daily_ic", "buckets_t10_net")
    a = evaluate(court_path=court_path, factor_col=None,
                 factor_csv=str(factor_path), name="det_factor",
                 registry_path=tmp_path / "r1.jsonl")
    b = evaluate(court_path=court_path, factor_col=None,
                 factor_csv=str(factor_path), name="det_factor",
                 registry_path=tmp_path / "r2.jsonl")
    assert json.dumps({k: a[k] for k in stat_keys}, sort_keys=True) == \
        json.dumps({k: b[k] for k in stat_keys}, sort_keys=True)
