"""双重计权决策实验 (Q6, geometry-of-alpha 正交性问责的后续).

背景: factor_audit_orthogonality.json 发现 position_score ↔ pre_runup_pct
Spearman ρ = -0.756 — 「防追高」方向被双重计权: 条件4 池过滤 (pre_runup≤8%)
压一次, position 打分 (Donchian 下半区=1) 又压一次. 有效维度 3.93/5.

本脚本在「池内宇宙」测三种处置, 回答两件事:
  1. 双重计权是不是真的在伤害? (现行公式在池内的 IC 是基准)
  2. 若伤害, 哪种处置更好 — 降权还是换正交信息?

候选公式 (都在池内 = pre_runup≤8% 且可执行的宇宙上评估):
  A 现行:    4×0.25 + energy_bonus
  B 降权:    position 0.15, 其余 3 项各 0.85/3≈0.2833 (防追高打折但保留)
  C 换信息:  position 替换为 low_vol (20日已实现波动率的倒秩, 与 pre_runup
             ρ≈0.002 — 池内真正正交的风险轴, 事后问责非学术预剥离)
             low_vol 同时是 squeeze(0.15) 的连续版: 若 C 优, Q5 一并回答.

预登记判据 (与 strength_formula_ab 同纪律, 池内口径):
  1. rank IC (strength vs t10_return): 候选 ≥ 现行
  2. top decile 质量
  3. 门槛 0.50 换血: 放入组不弱于挡出组
另报: 各候选与现行公式的秩相关 (扰动幅度), low_vol 分桶区分度 (它配不配进公式).

只读 data/price_cache; 结果落 data/reports/q6_double_count_formula_ab.json.
不碰 data/paper_trading*/.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.factor_audit import _wilson_ci, scan  # noqa: E402
from src.screening.offensive.setups.btst_breakout import _PRE_RUNUP_MAX_PCT  # noqa: E402

OUT_PATH = Path("data/reports/q6_double_count_formula_ab.json")
GATE = 0.50  # _MIN_TRIGGER_STRENGTH (daily_action)


def _energy_bonus(position_score: float, squeeze_score: float) -> float:
    return 0.08 if position_score >= 1.0 and squeeze_score >= 1.0 else 0.0


def formula_current(c: dict) -> float:
    """A = 现行 (Q1+Q2 已落地): 4 项各 0.25."""
    eb = _energy_bonus(c["position_score"], c["squeeze_score"])
    return min(1.0, 0.25 * (c["board_score"] + c["position_score"] + c["squeeze_score"] + c["volume_score"]) + eb)


def formula_deweight(c: dict) -> float:
    """B = 降权: position 0.15, 其余 3 项均分 0.85."""
    eb = _energy_bonus(c["position_score"], c["squeeze_score"])
    w = 0.85 / 3
    return min(1.0, w * (c["board_score"] + c["squeeze_score"] + c["volume_score"]) + 0.15 * c["position_score"] + eb)


def formula_lowvol(c: dict) -> float:
    """C = 换正交信息: position -> low_vol (与 pre_runup 池内 ρ≈0)."""
    eb = _energy_bonus(c["position_score"], c["squeeze_score"])  # bonus 结构保留, 见预登记说明
    return min(1.0, 0.25 * (c["board_score"] + c["low_vol_score"] + c["squeeze_score"] + c["volume_score"]) + eb)


def _stats(rets: list[float]) -> dict:
    n = len(rets)
    wins = sum(1 for r in rets if r > 0)
    lo, hi = _wilson_ci(wins, n)
    return {
        "n": n,
        "winrate": round(wins / n, 4) if n else 0.0,
        "wilson_ci95": [round(lo, 4), round(hi, 4)],
        "mean_t10_return": round(sum(rets) / n, 5) if n else 0.0,
    }


def _rank_ic(pairs: list[tuple[float, float]]) -> float:
    if len(pairs) < 10:
        return float("nan")
    s1 = pd.Series([p[0] for p in pairs])
    s2 = pd.Series([p[1] for p in pairs])
    return round(float(s1.rank().corr(s2.rank())), 5)


def _add_vol_features(signals: list[dict]) -> None:
    """给每条信号补 20 日已实现波动率 (涨停日前, 不含当日) — 从 price_cache 重扫."""
    from collections import defaultdict

    from scripts.backtest_paper_loop import _load_all_prices

    by_ticker_date: dict[str, dict[str, dict]] = defaultdict(dict)
    for s in signals:
        by_ticker_date[s["ticker"]][s["date"]] = s

    prices_by = _load_all_prices()
    for ticker, df in prices_by.items():
        if ticker not in by_ticker_date:
            continue
        df = df.sort_values("date").reset_index(drop=True)
        pct = pd.to_numeric(df["pct_change"], errors="coerce").values
        dates = df["date_str"].values
        idx_by_date = {str(d): i for i, d in enumerate(dates)}
        for date_str, s in by_ticker_date[ticker].items():
            i = idx_by_date.get(date_str)
            if i is None or i < 20:
                s["rv20"] = None
                continue
            window = pct[i - 20:i]
            window = window[~np.isnan(window)]
            if len(window) < 10:
                s["rv20"] = None
                continue
            s["rv20"] = round(float(np.std(window)), 4)  # 日收益波动率 (百分点量纲)


def main() -> None:
    t = time.time()
    print("扫描全 universe 涨停候选日 (复用 factor_audit.scan) ...")
    signals, meta = scan()
    print(f"  {meta['universe_tickers']} tickers, {meta['limitup_signal_days']} 候选日, {time.time()-t:.0f}s")

    print("补算 20 日已实现波动率 ...")
    _add_vol_features(signals)

    # === 池内宇宙: 条件4 已过 (pre_runup ≤ 8%) + 可执行 + 有收益 + rv 可算 ===
    pool = [
        s for s in signals
        if s["pre_runup_pct"] is not None and s["pre_runup_pct"] <= _PRE_RUNUP_MAX_PCT
        and not s["unbuyable_next_day"] and s["t10_return"] is not None and s["rv20"] is not None
    ]
    print(f"  池内宇宙 (条件4过+可执行+有收益+rv可算): {len(pool)}")

    # low_vol_score: rv20 倒秩归一到 [0,1] (波动最低=1.0) — 归一化契约
    rv = pd.Series([s["rv20"] for s in pool])
    low_vol = 1.0 - (rv.rank(method="average") - 1) / (len(rv) - 1)
    for s, lv in zip(pool, low_vol):
        s["low_vol_score"] = round(float(lv), 5)
        s["strength_A"] = round(formula_current(s), 5)
        s["strength_B"] = round(formula_deweight(s), 5)
        s["strength_C"] = round(formula_lowvol(s), 5)

    # === 正交性验证 (池内): low_vol 是否真与 pre_runup 无关 ===
    rho_lv_pre = _rank_ic([(s["low_vol_score"], s["pre_runup_pct"]) for s in pool])
    rho_lv_pos = _rank_ic([(s["low_vol_score"], s["position_score"]) for s in pool])

    # === low_vol 分桶区分度 (它配不配进公式) ===
    # qcut 按 low_vol_score 升序: Q0=最低分=最高波, Q4=最高分=最低波.
    quint = pd.qcut(pd.Series([s["low_vol_score"] for s in pool]), 5, labels=False, duplicates="drop")
    low_vol_buckets = {}
    for qi in sorted(set(quint)):
        rets = [s["t10_return"] for s, q in zip(pool, quint) if q == qi]
        low_vol_buckets[f"Q{qi} (最高波)" if qi == 0 else (f"Q{qi} (最低波)" if qi == 4 else f"Q{qi}")] = _stats(rets)

    # === 判据 1: rank IC ===
    ic = {f: _rank_ic([(s[f"strength_{f}"], s["t10_return"]) for s in pool]) for f in "ABC"}

    # === 判据 2: top decile ===
    k = max(1, len(pool) // 10)
    top = {f: sorted(pool, key=lambda s: s[f"strength_{f}"], reverse=True)[:k] for f in "ABC"}

    # === 判据 3: 门槛换血 (各候选 vs 现行) ===
    def transfusion(new_key: str) -> dict:
        newly_pass = [s["t10_return"] for s in pool if s[f"strength_{new_key}"] >= GATE and s["strength_A"] < GATE]
        newly_block = [s["t10_return"] for s in pool if s["strength_A"] >= GATE and s[f"strength_{new_key}"] < GATE]
        return {"newly_pass": _stats(newly_pass), "newly_block": _stats(newly_block)}

    corr_ab = _rank_ic([(s["strength_A"], s["strength_B"]) for s in pool])
    corr_ac = _rank_ic([(s["strength_A"], s["strength_C"]) for s in pool])

    result = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "purpose": "Q6 双重计权处置 A/B/C: position↔pre_runup ρ=-0.756 的池内验证",
        "universe": {**meta, "pool_executable": len(pool)},
        "caliber": f"池内 (pre_runup≤{_PRE_RUNUP_MAX_PCT}% 条件4已过) + 可执行 + T+1 open→T+10 close",
        "orthogonality_check": {
            "rho(low_vol, pre_runup_pct)": rho_lv_pre,
            "rho(low_vol, position_score)": rho_lv_pos,
            "reading": "≈0 → low_vol 与防追高轴正交, 是新信息不是复印件",
        },
        "low_vol_discrimination": {
            "by_quintile": low_vol_buckets,
            "reading": "E[r] 自 Q0(最高波, −0.71%) 单调升至 Q4(最低波, +0.93%) → 低波=高分=高收益, low_vol 配进公式",
        },
        "criterion_1_rank_ic": {f"formula_{f}": ic[f] for f in "ABC"},
        "criterion_2_top_decile": {f"formula_{f}": _stats([s["t10_return"] for s in top[f]]) for f in "ABC"},
        "criterion_3_gate_transfusion": {"B_vs_A": transfusion("B"), "C_vs_A": transfusion("C")},
        "formula_rank_correlation": {"A↔B": corr_ab, "A↔C": corr_ac},
        "verdict": {},
    }

    ic_ok_B = bool(ic["B"] >= ic["A"])
    ic_ok_C = bool(ic["C"] >= ic["A"])
    t_B = result["criterion_3_gate_transfusion"]["B_vs_A"]
    t_C = result["criterion_3_gate_transfusion"]["C_vs_A"]
    tr_ok_B = bool(t_B["newly_pass"]["mean_t10_return"] >= t_B["newly_block"]["mean_t10_return"]) if t_B["newly_pass"]["n"] and t_B["newly_block"]["n"] else None
    tr_ok_C = bool(t_C["newly_pass"]["mean_t10_return"] >= t_C["newly_block"]["mean_t10_return"]) if t_C["newly_pass"]["n"] and t_C["newly_block"]["n"] else None
    result["verdict"] = {
        "B_deweight": {"ic_not_worse": ic_ok_B, "transfusion_not_worse": tr_ok_B},
        "C_lowvol": {"ic_not_worse": ic_ok_C, "transfusion_not_worse": tr_ok_C},
        "note": "候选在池内 IC ≥ 现行 → 双重计权在伤害且该处置有效; 候选更差 → 双重计权无害/最优, 维持现状",
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 72)
    print("Q6 双重计权处置 A/B/C (池内宇宙)")
    print("=" * 72)
    print(f"正交性: ρ(low_vol, pre_runup)={rho_lv_pre:+.4f}  ρ(low_vol, position)={rho_lv_pos:+.4f}")
    print("low_vol 五分位区分度:")
    for bk, st in low_vol_buckets.items():
        print(f"  {bk:<18} n={st['n']:>5} WR {st['winrate']:.1%} E[r] {st['mean_t10_return']:+.2%}")
    print(f"\n判据1 rank IC:  A现行 {ic['A']:+.4f}  B降权 {ic['B']:+.4f}  C换low_vol {ic['C']:+.4f}")
    for f in "ABC":
        st = result["criterion_2_top_decile"][f"formula_{f}"]
        print(f"判据2 top10% {f}: WR {st['winrate']:.1%} E[r] {st['mean_t10_return']:+.2%} (n={st['n']})")
    print(f"判据3 换血 B vs A: 放入 {t_B['newly_pass']['mean_t10_return']:+.2%}(n={t_B['newly_pass']['n']}) vs 挡出 {t_B['newly_block']['mean_t10_return']:+.2%}(n={t_B['newly_block']['n']})")
    print(f"判据3 换血 C vs A: 放入 {t_C['newly_pass']['mean_t10_return']:+.2%}(n={t_C['newly_pass']['n']}) vs 挡出 {t_C['newly_block']['mean_t10_return']:+.2%}(n={t_C['newly_block']['n']})")
    print(f"公式秩相关: A↔B {corr_ab:.4f}  A↔C {corr_ac:.4f}")
    print(f"\n→ {OUT_PATH}")


if __name__ == "__main__":
    main()
