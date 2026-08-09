"""board 合并决策实验 (Q3, factor_audit 首批决策包).

背景: factor_audit 审计 (median 主判据, exec-adjusted) 发现 board_score 三桶:
    0.0  (000/001 深主): mean -0.62% / WR 40.9%   ← 显著最差, board 真实区分度来源
    0.95 (688/60x):      mean +0.26% / WR 42.9%   ← 略优
    1.0  (002/300/301):  mean -0.26% / WR 42.2%
  0.95 vs 1.0: Wilson CI 重叠 → 打平 (无区分度), 但 0.95 三点微优.
  即 board 的区分度全在 0.0 vs 非零, 0.95/1.0 是无区分度刻度 (同 weekday 教训).

  打分与实测轻微倒挂: 实测略优的 688/60x(0.95) 打分低于 002/300(1.0).

本脚本在「池内宇宙」测合并处置 (都是当前生产公式 = Q6 后 board/low_vol/squeeze/volume):
  A 现状:   board 原值 (0.0/0.95/1.0)
  B 合并:   board 0.95→1.0 (二值化 0.0/1.0; 消除无区分度刻度, 纠正倒挂方向)

预登记判据 (池内口径, 同 strength_formula_ab / q6 纪律):
  1. rank IC (strength vs t10_return): B ≥ A
  2. top decile 质量: B 不劣
  3. 门槛 0.50 换血: 放入组 (B 新入) 不弱于挡出组 (B 新挡)
另报: 公式秩相关 (扰动幅度), 入池票数变化.

只读 data/price_cache; 结果落 data/reports/q3_board_merge_ab.json.
不碰 data/paper_trading*/.
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

OUT_PATH = Path("data/reports/q3_board_merge_ab.json")
GATE = 0.50  # _MIN_TRIGGER_STRENGTH (daily_action)


def _energy_bonus(squeeze: float, low_vol: float) -> float:
    """Q6 后: energy_bonus 挂 squeeze>=1.0 且 low_vol>=0.75 (完整弹簧释放)."""
    return 0.08 if squeeze >= 1.0 and low_vol >= 0.75 else 0.0


def _strength(board: float, low_vol: float, squeeze: float, volume: float) -> float:
    """当前生产公式 (Q6 后): 4 分量各 0.25 + energy_bonus."""
    eb = _energy_bonus(squeeze, low_vol)
    return min(1.0, 0.25 * (board + low_vol + squeeze + volume) + eb)


def formula_a(c: dict) -> float:
    """A = 现状: board 原值."""
    return _strength(c["board_score"], c["low_vol_score"], c["squeeze_score"], c["volume_score"])


def formula_b(c: dict) -> float:
    """B = 合并: board 0.95→1.0 (二值化, 纠正倒挂方向)."""
    board = 1.0 if c["board_score"] >= 0.95 else c["board_score"]
    return _strength(board, c["low_vol_score"], c["squeeze_score"], c["volume_score"])


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

    # 判据1: rank IC
    ic_a = _rank_ic([(s["strength_A"], s["t10_return"]) for s in pool])
    ic_b = _rank_ic([(s["strength_B"], s["t10_return"]) for s in pool])
    print(f"\n判据1 rank IC:  A={ic_a:+.5f}  B={ic_b:+.5f}  Δ={ic_b-ic_a:+.5f}  {'✓不劣' if ic_b >= ic_a else '✗劣化'}")

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
    # B 升 0.95→1.0 只增不减, newly_block 应为空; newly_pass 是新入池的 688/60x
    print(f"判据3 换血@{GATE}: 放入 n={sp['n']} mean={sp['mean']:+.3%} wr={sp['winrate']:.1%} | 挡出 n={sbk['n']} mean={sbk['mean']:+.3%}")
    print(f"  入池票数: A={sum(1 for s in pool if s['strength_A']>=GATE)} → B={sum(1 for s in pool if s['strength_B']>=GATE)}")

    # 扰动幅度
    corr_ab = _rank_ic([(s["strength_A"], s["strength_B"]) for s in pool])
    print(f"\n公式秩相关 A~B: {corr_ab:.5f} (越接近1扰动越小)")

    # 放入组的板别构成 (确认是 688/60x 升档)
    pass_boards = {}
    for s in pool:
        if s["strength_B"] >= GATE and s["strength_A"] < GATE:
            bk = str(s["board_score"])
            pass_boards[bk] = pass_boards.get(bk, 0) + 1

    result = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "purpose": "Q3 board 合并: 0.95/1.0 打平(无区分度)的池内 A/B",
        "universe": {**meta, "pool_executable": len(pool)},
        "caliber": f"池内 (pre_runup≤{_PRE_RUNUP_MAX_PCT}% 条件4已过) + 可执行 + T+1 open→T+10 close",
        "board_audit": "0.95 vs 1.0 Wilson 重叠=打平; 0.95 三点微优; 区分度全在 0.0 vs 非零",
        "formulas": {"A_现状": "board 原值 0.0/0.95/1.0", "B_合并": "board 0.95→1.0 二值化"},
        "rank_ic": {"A": ic_a, "B": ic_b, "delta": round(ic_b - ic_a, 5)},
        "top_decile": {"A": sa, "B": sb},
        "gate_transfusion_050": {"newly_pass_B": sp, "newly_block_B": sbk, "pass_board_composition": pass_boards},
        "formula_rank_correlation_AB": corr_ab,
        "verdict": (
            "合并中性/正向 → 可落" if ic_b >= ic_a and sb["mean"] >= sa["mean"] - 0.001 and sp["mean"] >= 0
            else "需人工判读"
        ),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  → {OUT_PATH}")


if __name__ == "__main__":
    main()
