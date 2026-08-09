"""range 因子池内 A/B (新一轮因子挖掘, 2026-08-09).

背景: factor_audit 提纯 range_pct=(high-low)/prev_close 涨停日盘中振幅, 全 universe 审计
(exec-adjusted, median 主判据) 通过全部挖掘门:
  - Wilson 分离 (best [0.09,0.11) vs worst [0.14,inf)): 中位差 +4.10pp 胜率差 +6.67pp
  - 跨窗 split-half 稳定: [0.06,0.11) 甜区 / [0.14,inf) 最差, 两半同向
  - 正交: range_pct 与 board/position/low_vol/squeeze/volume/pre_runup |ρ|<0.10 (新维度)
  - 经济意义: 倒 U — 一字锁死板(买不到/追高反转) 与 盘中崩(高振幅) 两端皆差, 中间甜区最优
  - 尾部测度平 (全市场崩盘不分振幅), 正常区间因子可接受

range 描述「封板过程本身」(涨停日盘中), 现有 4 分量全描述「封板前状态」 — 真正的新轴.

本脚本在「池内宇宙」测是否落地: 加 range_score 进 strength 是否提升 rank IC.
  A 现状:     strength = 0.25*(board+low_vol+squeeze+volume) + energy_bonus   (Q6 后生产公式)
  B 加 range: strength = 0.20*(board+low_vol+squeeze+volume+range) + energy_bonus  (5 分量等权)

range_score 倒 U 映射 (据 exec 口径分桶校准):
  range<0.04 → 0.2 (一字锁死, median -4.42%) | 0.04-0.06 → 0.4 | 0.06-0.11 → 1.0 (甜区)
  0.11-0.14 → 0.4 | ≥0.14 → 0.2 (盘中崩, median -5.71% 最差) | 缺失 → 0.5 (中性回退)

预登记判据 (池内口径, 同 strength_formula_ab / q3 / q6 纪律):
  1. rank IC: B ≥ A
  2. top decile 质量: B 不劣
  3. 门槛 0.50 换血: 放入组 不弱于 挡出组 (北极星=挡负 EV)
另报: 公式秩相关, 入池票数, range_score 池内分布, split-half 两半 IC.

只读 data/price_cache; 结果落 data/reports/range_factor_ab.json. 不碰 data/paper_trading*/.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.factor_audit import scan  # noqa: E402
from src.screening.offensive.setups.btst_breakout import _PRE_RUNUP_MAX_PCT  # noqa: E402

OUT_PATH = Path("data/reports/range_factor_ab.json")
GATE = 0.50  # _MIN_TRIGGER_STRENGTH (daily_action)


def _energy_bonus(squeeze: float, low_vol: float) -> float:
    """Q6 后: energy_bonus 挂 squeeze>=1.0 且 low_vol>=0.75 (完整弹簧释放)."""
    return 0.08 if squeeze >= 1.0 and low_vol >= 0.75 else 0.0


def _range_score(range_pct) -> float:
    """倒 U 映射 (exec 口径分桶校准). 缺失/非有限 → 0.5 中性回退 (同其他分量纪律)."""
    if range_pct is None:
        return 0.5
    try:
        r = float(range_pct)
    except (TypeError, ValueError):
        return 0.5
    import math
    if not math.isfinite(r):
        return 0.5
    if r < 0.04:
        return 0.2  # 一字锁死板: 买不到/追高反转 (median -4.42%)
    if r < 0.06:
        return 0.4
    if r < 0.11:
        return 1.0  # 甜区 [0.06,0.11): median -1.62%~-1.77%, WR ~44%
    if r < 0.14:
        return 0.4
    return 0.2  # 盘中崩: median -5.71% 最差


def formula_a(c: dict) -> float:
    """A = 现状 (Q6 后生产公式): 4 分量各 0.25 + energy_bonus."""
    eb = _energy_bonus(c["squeeze_score"], c["low_vol_score"])
    return min(1.0, 0.25 * (c["board_score"] + c["low_vol_score"] + c["squeeze_score"] + c["volume_score"]) + eb)


def formula_b(c: dict) -> float:
    """B = 加 range: 5 分量各 0.20 + energy_bonus."""
    eb = _energy_bonus(c["squeeze_score"], c["low_vol_score"])
    rs = _range_score(c.get("range_pct"))
    return min(1.0, 0.20 * (c["board_score"] + c["low_vol_score"] + c["squeeze_score"] + c["volume_score"] + rs) + eb)


def _stats(rets: list[float]) -> dict:
    n = len(rets)
    if not n:
        return {"n": 0, "mean": 0.0, "median": 0.0, "winrate": 0.0}
    wins = sum(1 for r in rets if r > 0)
    s = sorted(rets)
    return {
        "n": n,
        "mean": round(sum(rets) / n, 5),
        "median": round((s[n // 2] + s[(n - 1) // 2]) / 2, 5),
        "winrate": round(wins / n, 4),
    }


def _rank_ic(pairs: list[tuple[float, float]]) -> float:
    if len(pairs) < 10:
        return float("nan")
    s1 = pd.Series([p[0] for p in pairs])
    s2 = pd.Series([p[1] for p in pairs])
    return round(float(s1.rank().corr(s2.rank())), 5)


def main() -> None:
    t = time.time()
    print("扫描全 universe 涨停候选日 ...")
    signals, meta = scan()
    print(f"  {meta['universe_tickers']} tickers, {meta['limitup_signal_days']} 信号日, {time.time()-t:.0f}s")

    # 池内宇宙: 条件4 已过 (pre_runup≤8%) + 可执行 + 有收益
    pool = [
        s for s in signals
        if s["pre_runup_pct"] is not None
        and s["pre_runup_pct"] <= _PRE_RUNUP_MAX_PCT
        and not s["unbuyable_next_day"]
        and s["t10_return"] is not None
    ]
    print(f"  池内宇宙 (条件4过+可执行+有收益): {len(pool)}")

    for s in pool:
        s["strength_A"] = round(formula_a(s), 5)
        s["strength_B"] = round(formula_b(s), 5)
        s["range_score"] = _range_score(s.get("range_pct"))

    # range_score 池内分布
    import collections
    rs_dist = collections.Counter(s["range_score"] for s in pool)
    print(f"  range_score 池内分布: {dict(sorted(rs_dist.items()))}")

    # 判据1: rank IC (全池 + split-half)
    ic_a = _rank_ic([(s["strength_A"], s["t10_return"]) for s in pool])
    ic_b = _rank_ic([(s["strength_B"], s["t10_return"]) for s in pool])
    print(f"\n判据1 rank IC (全池):  A={ic_a:+.5f}  B={ic_b:+.5f}  Δ={ic_b-ic_a:+.5f}  {'✓不劣' if ic_b >= ic_a else '✗劣化'}")

    # split-half: 按 date 中位数切两半, 各自 IC (跨窗稳健性)
    dates = sorted({s["date"] for s in pool})
    mid_date = dates[len(dates) // 2]
    h1 = [s for s in pool if s["date"] < mid_date]
    h2 = [s for s in pool if s["date"] >= mid_date]
    ic_a_h1, ic_a_h2 = _rank_ic([(s["strength_A"], s["t10_return"]) for s in h1]), _rank_ic([(s["strength_A"], s["t10_return"]) for s in h2])
    ic_b_h1, ic_b_h2 = _rank_ic([(s["strength_B"], s["t10_return"]) for s in h1]), _rank_ic([(s["strength_B"], s["t10_return"]) for s in h2])
    print(f"  split-half@{mid_date}:  H1 A={ic_a_h1:+.5f} B={ic_b_h1:+.5f}  |  H2 A={ic_a_h2:+.5f} B={ic_b_h2:+.5f}")

    # 判据2: top decile
    k = max(1, len(pool) // 10)
    top_a = sorted(pool, key=lambda s: s["strength_A"], reverse=True)[:k]
    top_b = sorted(pool, key=lambda s: s["strength_B"], reverse=True)[:k]
    sa, sb = _stats([s["t10_return"] for s in top_a]), _stats([s["t10_return"] for s in top_b])
    print(f"判据2 top10%:   A mean={sa['mean']:+.3%} wr={sa['winrate']:.1%} | B mean={sb['mean']:+.3%} wr={sb['winrate']:.1%}  {'✓不劣' if sb['mean'] >= sa['mean'] - 0.001 else '~'}")

    # 判据3: 门槛换血
    newly_pass = [s["t10_return"] for s in pool if s["strength_B"] >= GATE and s["strength_A"] < GATE]
    newly_block = [s["t10_return"] for s in pool if s["strength_A"] >= GATE and s["strength_B"] < GATE]
    sp, sbk = _stats(newly_pass), _stats(newly_block)
    print(f"判据3 换血@{GATE}: 放入 n={sp['n']} mean={sp['mean']:+.3%} wr={sp['winrate']:.1%} | 挡出 n={sbk['n']} mean={sbk['mean']:+.3%} wr={sbk['winrate']:.1%}")
    print(f"  入池票数: A={sum(1 for s in pool if s['strength_A'] >= GATE)} → B={sum(1 for s in pool if s['strength_B'] >= GATE)}")

    # 扰动幅度
    corr_ab = _rank_ic([(s["strength_A"], s["strength_B"]) for s in pool])
    print(f"\n公式秩相关 A~B: {corr_ab:.5f} (越接近1扰动越小)")

    pass_ic = ic_b >= ic_a
    pass_top = sb["mean"] >= sa["mean"] - 0.001
    pass_gate = (sbk["n"] == 0) or (sp["mean"] >= sbk["mean"]) or (sp["n"] == 0)
    verdict = (
        "加 range 提升池内质量 → 可落 (加因子需 owner 拍板)" if pass_ic and pass_top and pass_gate
        else "需人工判读: " + ", ".join(
            x for x, ok in [("IC", pass_ic), ("top", pass_top), ("换血", pass_gate)] if not ok
        )
    )
    print(f"\n裁决: {verdict}")

    result = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "purpose": "range 因子池内 A/B: 加 range_score 进 strength 是否提升 rank IC",
        "universe": {**meta, "pool_executable": len(pool)},
        "caliber": f"池内 (pre_runup≤{_PRE_RUNUP_MAX_PCT}% 条件4已过) + 可执行 + T+1 open→T+10 close",
        "range_audit_summary": "倒 U; best [0.06,0.11) median -1.62% WR~44%; worst [0.14,inf) median -5.71% WR37.3%; Wilson分离; 跨窗稳定; 正交(|ρ|<0.10)",
        "formulas": {
            "A_现状": "0.25*(board+low_vol+squeeze+volume)+energy_bonus",
            "B_加range": "0.20*(board+low_vol+squeeze+volume+range)+energy_bonus",
        },
        "range_score_mapping": {"<0.04": 0.2, "0.04-0.06": 0.4, "0.06-0.11": 1.0, "0.11-0.14": 0.4, ">=0.14": 0.2, "missing": 0.5},
        "range_score_pool_dist": {str(k): v for k, v in sorted(rs_dist.items())},
        "rank_ic": {"A": ic_a, "B": ic_b, "delta": round(ic_b - ic_a, 5)},
        "rank_ic_split_half": {"mid_date": mid_date, "H1": {"A": ic_a_h1, "B": ic_b_h1}, "H2": {"A": ic_a_h2, "B": ic_b_h2}},
        "top_decile": {"A": sa, "B": sb},
        "gate_transfusion_050": {"newly_pass_B": sp, "newly_block_B": sbk},
        "admission_count": {"A": sum(1 for s in pool if s["strength_A"] >= GATE), "B": sum(1 for s in pool if s["strength_B"] >= GATE)},
        "formula_rank_correlation_AB": corr_ab,
        "verdict": verdict,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  → {OUT_PATH}")


if __name__ == "__main__":
    main()
