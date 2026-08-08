"""trigger_strength 公式 A/B 对比 — 全量历史数据验证公式变更 (不等 dogfood).

动机 (2026-08-09): factor_audit Q1 把 weekday_score 移出 trigger_strength (5×0.20 →
4×0.25). 审计器预测「无区分度分量的移除不损甚至微升池内排序质量」. 该预测不必等
数周 dogfood — 全量历史信号上可直接 A/B (memory: 历史回测先于等未来数据).

方法:
  复用 factor_audit.scan() (同一口径: 全 universe price-eligible 涨停候选日,
  T+1 open -> T+10 close, execution-adjusted), 对每条信号用两个公式各算 strength,
  对比排序质量. 三个预登记判据:
    1. rank IC (Spearman, strength vs t10_return): 新 ≥ 旧 → 信息含量没丢
    2. top decile 质量: 各公式头部桶胜率/E[r]
    3. 门槛换血 (_MIN_TRIGGER_STRENGTH=0.50 边界): 新公式放入组 vs 挡出组的收益对比
  判定规则 (预登记): 新公式 rank IC ≥ 旧 且 放入组不弱于挡出组 → 预测兑现;
  明显更差 → 回滚并修正审计器.

口径说明: 本脚本在 price-eligible 全量宇宙测排序 (因子层), 不施加 detect 的
资金流/行业/追高池过滤 (避免推荐池选择偏差). energy_bonus 由 position/squeeze
分量推导 (>=1.0 同时成立), 与生产公式一致. 未来 Q2 (volume 重标定) / Q3 (board
合并) 的采纳前验证复用本脚本: 改 FORMULA_B 即可.

只读 data/price_cache; 结果落 data/reports/. 不碰 data/paper_trading*/.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.factor_audit import _wilson_ci, scan  # noqa: E402

OUT_PATH = Path("data/reports/q1_weekday_formula_ab.json")
GATE = 0.50  # _MIN_TRIGGER_STRENGTH (daily_action)


def _energy_bonus(position_score: float, squeeze_score: float) -> float:
    return 0.08 if position_score >= 1.0 and squeeze_score >= 1.0 else 0.0


def formula_old(c: dict) -> float:
    """A = 移除前: 5 项各 0.20 (含 weekday)."""
    eb = _energy_bonus(c["position_score"], c["squeeze_score"])
    return min(1.0, 0.20 * (c["weekday_score"] + c["board_score"] + c["position_score"] + c["squeeze_score"] + c["volume_score"]) + eb)


def formula_new(c: dict) -> float:
    """B = 移除后 (已落地 3111c11a): 4 项各 0.25 (不含 weekday)."""
    eb = _energy_bonus(c["position_score"], c["squeeze_score"])
    return min(1.0, 0.25 * (c["board_score"] + c["position_score"] + c["squeeze_score"] + c["volume_score"]) + eb)


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
    """Spearman 秩相关 (不引 scipy: 对两边各自取秩后算 Pearson)."""
    import pandas as pd

    if len(pairs) < 10:
        return float("nan")
    s1 = pd.Series([p[0] for p in pairs])
    s2 = pd.Series([p[1] for p in pairs])
    return round(float(s1.rank().corr(s2.rank())), 5)  # float(): 防 numpy 标量进 json


def main() -> None:
    t = time.time()
    print("扫描全 universe 涨停候选日 (复用 factor_audit.scan) ...")
    signals, meta = scan()
    print(f"  {meta['universe_tickers']} tickers, {meta['limitup_signal_days']} 候选日, {time.time()-t:.0f}s")

    for s in signals:
        s["strength_old"] = round(formula_old(s), 5)
        s["strength_new"] = round(formula_new(s), 5)

    # execution-adjusted + 有 T+10 收益 (判定口径)
    exe = [s for s in signals if not s["unbuyable_next_day"] and s["t10_return"] is not None]
    print(f"  可执行且有收益样本: {len(exe)}")

    # --- 判据 1: rank IC ---
    ic_old = _rank_ic([(s["strength_old"], s["t10_return"]) for s in exe])
    ic_new = _rank_ic([(s["strength_new"], s["t10_return"]) for s in exe])

    # --- 判据 2: top decile 质量 ---
    k = max(1, len(exe) // 10)
    top_old = sorted(exe, key=lambda s: s["strength_old"], reverse=True)[:k]
    top_new = sorted(exe, key=lambda s: s["strength_new"], reverse=True)[:k]
    overlap = len({id(s) for s in top_old} & {id(s) for s in top_new}) / k

    # --- 判据 3: 门槛 0.50 换血 ---
    newly_pass = [s["t10_return"] for s in exe if s["strength_new"] >= GATE and s["strength_old"] < GATE]
    newly_block = [s["t10_return"] for s in exe if s["strength_old"] >= GATE and s["strength_new"] < GATE]
    keep_pass = [s["t10_return"] for s in exe if s["strength_old"] >= GATE and s["strength_new"] >= GATE]

    # 公式间相关 (应为高相关 — 小扰动)
    formula_corr = _rank_ic([(s["strength_old"], s["strength_new"]) for s in exe])

    result = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "purpose": "Q1 (weekday 移除) 公式 A/B: 历史数据验证审计器预测, 不等 dogfood",
        "universe": {**meta, "executable_with_return": len(exe)},
        "caliber": "price-eligible 全量宇宙, T+1 open -> T+10 close, execution-adjusted",
        "criterion_1_rank_ic": {
            "old_5x0.20": ic_old,
            "new_4x0.25": ic_new,
            "delta": round(ic_new - ic_old, 5),
            "reading": "delta >= 0 → 移除 weekday 没丢排序信息",
        },
        "criterion_2_top_decile": {
            "top_by_old": _stats([s["t10_return"] for s in top_old]),
            "top_by_new": _stats([s["t10_return"] for s in top_new]),
            "overlap_ratio": round(overlap, 4),
        },
        "criterion_3_gate_0.50_transfusion": {
            "newly_pass (weekday=0 被提升)": _stats(newly_pass),
            "newly_block (weekday=1 被降权)": _stats(newly_block),
            "kept_pass_参照": _stats(keep_pass),
            "reading": "newly_pass 不弱于 newly_block → 换血是赚的或平价",
        },
        "formula_rank_correlation": formula_corr,
        "verdict": {},
    }

    # 预登记判定
    np_s, nb_s = result["criterion_3_gate_0.50_transfusion"]["newly_pass (weekday=0 被提升)"], result["criterion_3_gate_0.50_transfusion"]["newly_block (weekday=1 被降权)"]
    ic_ok = bool(ic_new >= ic_old)
    transfusion_ok = bool(np_s["mean_t10_return"] >= nb_s["mean_t10_return"]) if np_s["n"] and nb_s["n"] else None
    confirmed = bool(ic_ok and (transfusion_ok in (True, None)))
    result["verdict"] = {
        "rank_ic_not_worse": bool(ic_ok),
        "transfusion_not_worse": transfusion_ok,
        "prediction_confirmed": confirmed,
        "note": "兑现 → 审计器可信, 可推进 Q2-Q5; 落空 → 因子层区分度≠组合层收益, 修审计器",
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 72)
    print("Q1 公式 A/B (weekday 移除): 旧 5×0.20 vs 新 4×0.25")
    print("=" * 72)
    print(f"判据1 rank IC:  旧 {ic_old:+.4f}  新 {ic_new:+.4f}  (Δ{ic_new-ic_old:+.4f})  {'✅ 不劣' if ic_ok else '❌ 变劣'}")
    print(f"判据2 top10%:   旧 WR {result['criterion_2_top_decile']['top_by_old']['winrate']:.1%} E[r] {result['criterion_2_top_decile']['top_by_old']['mean_t10_return']:+.2%}"
          f"  |  新 WR {result['criterion_2_top_decile']['top_by_new']['winrate']:.1%} E[r] {result['criterion_2_top_decile']['top_by_new']['mean_t10_return']:+.2%}  (重叠 {overlap:.0%})")
    print(f"判据3 门槛换血: 放入 n={np_s['n']} E[r] {np_s['mean_t10_return']:+.2%}  vs  挡出 n={nb_s['n']} E[r] {nb_s['mean_t10_return']:+.2%}  {'✅ 放入不弱' if transfusion_ok else ('❌ 放入更弱' if transfusion_ok is False else '(样本不足)')}")
    print(f"公式间秩相关: {formula_corr:.4f} (高相关=小扰动)")
    print(f"\n→ 预测{'【兑现】' if confirmed else '【未兑现】'}  → {OUT_PATH}")


if __name__ == "__main__":
    main()
