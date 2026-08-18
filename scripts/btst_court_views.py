"""BTST court 第三步: 只读视图 + 预注册决策规则判定 → decision pack.

预注册规则 (先于任何数据写死; 改动 = 重开 court):
Q1 期限 (主对照 T+8 vs T+10, 配对, 净收益):
  G1 split-half: 按信号日中位数分两半, Δmean(t8−t10) 两半均为正;
  G2 成本压力: 滑点 60bps/边下 Δmean 仍为正;
  G3 regime 分层: normal-only 子集 Δ>0;
  G4 聚类推断: 按信号日聚类 bootstrap (重采样天, 不重采样事件) 的
     单侧 90% CI 下界 > 0.
  全过 → 允许提出 T+8 合约变更提案 (激活仍需新证据世代+在途迁移);
  任一不过 → no-change. T+3/T+5/ratchet 一律 exploratory, 不判规则.
Q2 阈值: 桶均值 Spearman ρ>0 且 p<0.05, 两半窗同号, 候选阈值带事件占比≥15%.
Q3 gap: +2% 以上桶均值单调不升, 且悬崖 (above−below<0) 过置换检验 p<0.10.

推断纪律: 主对照 CI 用按日聚类 bootstrap (同日事件共享市场抽签);
校准表是研究产物, 不构成任何接线授权.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _btst_court_common import (  # noqa: E402
    EXPLORATORY_HORIZONS,
    MIN_TRIGGER_STRENGTH,
    PRIMARY_HORIZON_PAIR,
    SELL_STAMP_BPS,
    SLIPPAGE_BPS,
    SLIPPAGE_STRESS_BPS,
    TABLE_DIR,
)
from review_btst_prior_court import (  # noqa: E402 — Round 2 已验证的消费侧守卫, 同目录复用
    MAX_TABLE_AGE_DAYS,
    current_setup_sha,
    table_freshness,
)

REBUILD_HINT = (
    "court 事件表不可信 — 重建: uv run python scripts/btst_court_fetch.py "
    "&& uv run python scripts/btst_court_build.py"
)


def freshness_problems(fresh: dict) -> list[str]:
    """表龄/公式漂移/manifest 缺失的问题清单 (空 = 可信)."""
    problems = []
    if not fresh.get("manifest_present"):
        problems.append("manifest 缺失 — 表龄与公式指纹不可验证")
        return problems
    age = fresh.get("age_days")
    if age is not None and age > MAX_TABLE_AGE_DAYS:
        problems.append(f"表龄 {age} 天 > {MAX_TABLE_AGE_DAYS} (built_at {fresh.get('built_at')})")
    if fresh.get("formula_match") is not True:
        problems.append(
            f"公式漂移: manifest {str(fresh.get('manifest_setup_sha'))[:8]} "
            f"!= 当前 {str(fresh.get('current_setup_sha'))[:8]} (court 表不代表当前生产口径)"
        )
    return problems


def freshness_line(fresh: dict) -> str:
    """决策包头部的新鲜度披露行 (match 无 ⚠; 有问题则 ⚠ + 重建指引)."""
    problems = freshness_problems(fresh)
    if not fresh.get("manifest_present"):
        return f"- 事件表新鲜度: ⚠ manifest 缺失 — 结论仅供存档参考。{REBUILD_HINT}"
    age = fresh.get("age_days")
    formula_ok = fresh.get("formula_match") is True
    head = (
        f"- 事件表新鲜度:{'' if not problems else ' ⚠'} built_at {fresh.get('built_at')} · "
        f"表龄 {age} 天 · 公式指纹{'一致' if formula_ok else '漂移'}"
    )
    if problems:
        head += f" · ⚠ {'; '.join(problems)}。{REBUILD_HINT}"
    return head

try:
    from scipy import stats as sps
except Exception:  # noqa: BLE001

    class _SpsFallback:
        @staticmethod
        def spearmanr(a, b):
            ra, rb = pd.Series(a).rank(), pd.Series(b).rank()
            r = np.corrcoef(ra, rb)[0, 1]
            # t 近似 p 值 (大样本)
            n = len(a)
            t = r * np.sqrt(max(1e-12, (n - 2) / max(1e-12, (1 - r**2))))
            from math import erf, sqrt

            p = 2 * (1 - erf(abs(t) / sqrt(2)))
            return r, p

    sps = _SpsFallback()

RNG = np.random.default_rng(20260815)  # 固定种子: pack 可复现
N_BOOT = 10_000


def net_ret(gross: pd.Series, slip_bps: float) -> pd.Series:
    return gross - (2 * slip_bps + SELL_STAMP_BPS) / 1e4


def cluster_boot_ci_low(diffs: pd.Series, days: pd.Series, ci: float = 0.90, n_boot: int = N_BOOT) -> float:
    """按信号日聚类 bootstrap (对抗性审查修复: 池化事件口径).

    重采样天 → 把被抽中天的全部事件池化后取逐事件均值. 估计量与 headline
    (逐事件均值) 同口径 — 旧实现"按日均值再平均"在事件数异方差时中心偏移
    (2026-08-15 审查发现: 中心 -0.187% vs 逐事件 -0.334%).
    """
    by_day = [g.to_numpy() for _, g in diffs.groupby(days)]
    n = len(by_day)
    means = np.empty(n_boot)
    for i in range(n_boot):
        pick = RNG.integers(0, n, n)
        means[i] = np.concatenate([by_day[j] for j in pick]).mean()
    return float(np.quantile(means, 1 - ci))


def fmt_pair(a: pd.Series, _unused=None) -> str:
    if a.empty:
        return "n=0"
    return f"n={len(a):4d} mean={a.mean():+.2%} win={(a > 0).mean():.0%}"


def q1_horizon(ev: pd.DataFrame, md: dict) -> dict:
    k_a, k_b = PRIMARY_HORIZON_PAIR
    col_a, col_b = f"gross_ret_t{k_a}", f"gross_ret_t{k_b}"
    base = ev[ev[col_a].notna() & ev[col_b].notna()].copy()
    out: dict = {"primary": f"T+{k_a} vs T+{k_b}", "n": len(base), "gates": {}, "exploratory": {}}

    def delta(df: pd.DataFrame, slip: float) -> pd.Series:
        return net_ret(df[col_a], slip) - net_ret(df[col_b], slip)

    d30 = delta(base, SLIPPAGE_BPS)
    d60 = delta(base, SLIPPAGE_STRESS_BPS)
    mid = base["signal_date"].sort_values().iloc[len(base) // 2]
    h1, h2 = base[base["signal_date"] < mid], base[base["signal_date"] >= mid]
    normal = base[base["regime"] == "normal"]
    ci_low = cluster_boot_ci_low(d30, base["signal_date"])

    out["headline"] = {
        f"t{k_a}_net30": fmt_pair(net_ret(base[col_a], SLIPPAGE_BPS), None),
        f"t{k_b}_net30": fmt_pair(net_ret(base[col_b], SLIPPAGE_BPS), None),
        "delta_mean_30bps": f"{d30.mean():+.3%}",
        "delta_mean_60bps": f"{d60.mean():+.3%}",
        "cluster_boot90_ci_low": f"{ci_low:+.3%}",
        "halves": [f"{delta(h, SLIPPAGE_BPS).mean():+.3%}" for h in (h1, h2)],
        "normal_only_delta": f"{delta(normal, SLIPPAGE_BPS).mean():+.3%}",
    }
    out["gates"] = {
        "G1_split_half_both_positive": bool(delta(h1, SLIPPAGE_BPS).mean() > 0 and delta(h2, SLIPPAGE_BPS).mean() > 0),
        "G2_stress_60bps_positive": bool(d60.mean() > 0),
        "G3_normal_only_positive": bool(delta(normal, SLIPPAGE_BPS).mean() > 0),
        "G4_cluster_ci_low_positive": bool(ci_low > 0),
    }
    out["primary_pass_all_gates"] = all(out["gates"].values())

    for k in EXPLORATORY_HORIZONS:
        col = f"gross_ret_t{k}"
        m = base[base[col].notna()]
        out["exploratory"][f"t{k}"] = {
            "net30": fmt_pair(net_ret(m[col], SLIPPAGE_BPS), None),
            "delta_vs_t10": f"{(net_ret(m[col], SLIPPAGE_BPS) - net_ret(m[f'gross_ret_t{k_b}'], SLIPPAGE_BPS)).mean():+.3%}",
        }
    m = base[base["ratchet_gross_ret"].notna()]
    out["exploratory"]["ratchet"] = {
        "n": len(m),
        "net30": fmt_pair(net_ret(m["ratchet_gross_ret"], SLIPPAGE_BPS), None),
        "delta_vs_t10": f"{(net_ret(m['ratchet_gross_ret'], SLIPPAGE_BPS) - net_ret(m[col_b], SLIPPAGE_BPS)).mean():+.3%}" if len(m) else "n=0",
        "reason_counts": m["ratchet_reason"].value_counts().to_dict() if len(m) else {},
        "median_exit_session": float(m["ratchet_exit_session"].median()) if len(m) else None,
    }
    return out


def q2_threshold(ev: pd.DataFrame) -> dict:
    df = ev[ev["gross_ret_t10"].notna()].copy()
    df["ret"] = net_ret(df["gross_ret_t10"], SLIPPAGE_BPS)
    bins = [0.0, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80, 1.01]
    df["bucket"] = pd.cut(df["trigger_strength"], bins)
    g = df.groupby("bucket", observed=True)["ret"].agg(["count", "mean", lambda s: (s > 0).mean()])
    g.columns = ["n", "E", "WR"]
    centers = [iv.mid for iv in g.index]
    rho, p = sps.spearmanr(centers, g["E"].to_numpy())
    mid = df["signal_date"].sort_values().iloc[len(df) // 2]
    rho1, _ = sps.spearmanr(centers, df[df["signal_date"] < mid].groupby("bucket", observed=True)["ret"].mean().reindex(g.index).to_numpy())
    rho2, _ = sps.spearmanr(centers, df[df["signal_date"] >= mid].groupby("bucket", observed=True)["ret"].mean().reindex(g.index).to_numpy())
    total_n = g["n"].sum()
    share_ok = {f"[{iv.left:.2f},{iv.right:.2f})": n / total_n for iv, n in zip(g.index, g["n"]) if n / total_n >= 0.15}
    return {
        "curve": {f"[{iv.left:.2f},{iv.right:.2f})": {"n": int(r.n), "E": round(r.E, 5), "WR": round(r.WR, 3)} for iv, r in g.iterrows()},
        "spearman_rho": round(float(rho), 4),
        "spearman_p": round(float(p), 5),
        "halves_rho": [round(float(rho1), 4), round(float(rho2), 4)],
        "bands_share_ge_15pct": share_ok,
        "gates": {
            "G1_rho_positive_p_lt_05": bool(rho > 0 and p < 0.05),
            "G2_halves_same_sign": bool(rho1 > 0 and rho2 > 0),
            "G3_candidate_band_exists": bool(share_ok),
        },
    }


def q3_gap(ev: pd.DataFrame) -> dict:
    df = ev[ev["gap_t1_open"].notna() & ev["gross_ret_t10"].notna()].copy()
    df["ret5"] = net_ret(df["gross_ret_t5"], SLIPPAGE_BPS)
    df["ret10"] = net_ret(df["gross_ret_t10"], SLIPPAGE_BPS)
    df["gap_decile"] = pd.qcut(df["gap_t1_open"], 10, duplicates="drop")
    g = df.groupby("gap_decile", observed=True)[["gap_t1_open", "ret5", "ret10"]].agg(["count", "mean"])
    above2 = df[df["gap_t1_open"] >= 0.02]
    buckets_above = above2.groupby(pd.cut(above2["gap_t1_open"], [0.02, 0.04, 0.06, 0.10]), observed=True)["ret10"].mean()
    monotone = all(buckets_above.to_numpy()[i] >= buckets_above.to_numpy()[i + 1] - 1e-12 for i in range(len(buckets_above) - 1)) if len(buckets_above) > 1 else False

    cliffs = {}
    for c in (0.03, 0.04, 0.05):
        hi, lo = df[df["gap_t1_open"] >= c]["ret10"], df[df["gap_t1_open"] < c]["ret10"]
        if len(hi) < 10 or len(lo) < 10:
            cliffs[f"{c:.0%}"] = {"status": "insufficient_n", "n_hi": len(hi), "n_lo": len(lo)}
            continue
        obs = hi.mean() - lo.mean()
        n_perm = 5000
        vals = df["ret10"].to_numpy()
        labels = (df["gap_t1_open"].to_numpy() >= c)
        perm = np.empty(n_perm)
        for i in range(n_perm):
            shuffled = RNG.permutation(labels)
            perm[i] = vals[shuffled].mean() - vals[~shuffled].mean()
        p_one = float((perm <= obs).mean())
        cliffs[f"{c:.0%}"] = {"delta": round(float(obs), 5), "p_one_sided": round(p_one, 4), "n_hi": len(hi), "n_lo": len(lo)}
    best_cliff = next((k for k, v in cliffs.items() if isinstance(v, dict) and v.get("p_one_sided", 1) < 0.10), None)
    # 形状披露 (对抗性审查 2026-08-15): 阶梯悬崖检验在"缓降+毒尾"形状下会机械过门 —
    # 门结论必须与分区形状同读, 毒性集中在哪个区间由数据说话, 不由检验构造代言.
    zones = {}
    for lo_, hi_, label in [(-1, 0.03, "<3%"), (0.03, 0.06, "3~6%"), (0.06, 9, ">6%")]:
        zs = df[(df["gap_t1_open"] >= lo_) & (df["gap_t1_open"] < hi_)]["ret10"]
        zones[label] = {"n": len(zs), "E": round(float(zs.mean()), 5) if len(zs) else None, "WR": round(float((zs > 0).mean()), 3) if len(zs) else None}
    return {
        "deciles": {
            f"{iv.left:+.1%}~{iv.right:+.1%}": {"n": int(r[("gap_t1_open", "count")]), "gap_mid": round(float(r[("gap_t1_open", "mean")]), 4),
                                                "ret5": round(float(r[("ret5", "mean")]), 5) if pd.notna(r[("ret5", "mean")]) else None,
                                                "ret10": round(float(r[("ret10", "mean")]), 5)}
            for iv, r in g.iterrows()
        },
        "above2_buckets_E_t10": {f"{iv}": round(float(v), 5) for iv, v in buckets_above.items()},
        "zone_breakdown": zones,
        "cliff_tests": cliffs,
        "gates": {
            "G1_monotone_above_2pct": bool(monotone),
            "G2_cliff_significant": bool(best_cliff),
        },
        "proposed_cliff": best_cliff,
    }


def calibration(ev: pd.DataFrame) -> dict:
    df = ev[ev["gross_ret_t10"].notna()].copy()
    df["ret"] = net_ret(df["gross_ret_t10"], SLIPPAGE_BPS)
    df["decile"] = pd.qcut(df["trigger_strength"].rank(method="first"), 10, labels=False) + 1
    g = df.groupby("decile").agg(
        n=("ret", "size"),
        ts_min=("trigger_strength", "min"),
        ts_max=("trigger_strength", "max"),
        E_t10=("ret", "mean"),
        WR_t10=("ret", lambda s: (s > 0).mean()),
    )
    df8 = ev[ev["gross_ret_t8"].notna()].copy()
    df8["ret"] = net_ret(df8["gross_ret_t8"], SLIPPAGE_BPS)
    g8 = df8.groupby(pd.qcut(df8["trigger_strength"].rank(method="first"), 10, labels=False) + 1)["ret"].mean()
    g["E_t8"] = g8
    return {int(i): {"n": int(r.n), "ts": f"[{r.ts_min:.2f},{r.ts_max:.2f}]", "E_t10": round(r.E_t10, 5), "WR_t10": round(r.WR_t10, 3), "E_t8": round(r.E_t8, 5) if pd.notna(r.E_t8) else None} for i, r in g.iterrows()}


def monthly_by_regime(ev: pd.DataFrame, horizon: int = 10) -> dict:
    """月度 × regime × gate 聚合 — 固化此前的一次性临时聚合, 口径显式可重验.

    band = traded (eligible ∩ fillable ∩ strength≥MIN_TRIGGER_STRENGTH; 保留
    gate_blocked 行以输出 gate_off 对照); 收益 = T+{horizon} 净口径 (30bps/边
    滑点 + 5bps 卖出印花税, 同 net_ret); 分组 = signal_date 前 6 位 (YYYYMM).
    缺失/非有限收益行排除且 n 如实; 空 regime 层显式 n=0, 不静默缺键.
    月度样本小 (n≈百级), 仅描述不检验 — 推断仍走 Q1 的按日聚类 bootstrap.
    """
    col = f"gross_ret_t{horizon}"
    band = ev[
        ~ev["degraded"] & ~ev["industry_missing"] & ~ev["st_name"] & ~ev["excluded_ticker"]
        & ev["price_ge_3"] & ev["fillable"] & (ev["trigger_strength"] >= MIN_TRIGGER_STRENGTH)
    ].copy()
    band["ret"] = net_ret(band[col], SLIPPAGE_BPS)
    band = band[band["ret"].notna()]
    band["month"] = band["signal_date"].astype(str).str[:6]

    def _stats(df: pd.DataFrame) -> dict:
        if df.empty:
            return {"n": 0, "mean": None, "winrate": None}
        return {
            "n": int(len(df)),
            "mean": round(float(df["ret"].mean()), 5),
            "winrate": round(float((df["ret"] > 0).mean()), 3),
        }

    out: dict = {}
    for month, g in band.groupby("month"):
        layers = {}
        for gate_key, sub in (("gate_on", g[~g["gate_blocked"]]), ("gate_off", g)):
            layers[gate_key] = {
                layer: _stats(sub if layer == "total" else sub[sub["regime"] == layer])
                for layer in ("total", "normal", "crisis", "risk_off")
            }
        out[month] = layers
    return out


def render_monthly_md(monthly: dict) -> list[str]:
    L = ["## 月度 × regime × gate (T+10 净收益, traded band)", ""]
    L.append("固化口径: band=eligible∩fillable∩strength≥0.5 · 净=30bps/边+5bps 印花税 · 分组=signal_date 月份")
    L.append("```")
    L.append("  月份   gate   n   E(T+10)  win |  normal        crisis       risk_off")
    for month, layers in monthly.items():
        for gate_key in ("gate_on", "gate_off"):
            t = layers[gate_key]
            parts = []
            for layer in ("normal", "crisis", "risk_off"):
                s = t[layer]
                m = "--" if s["mean"] is None else format(s["mean"], "+.2%")
                parts.append(f"{s['n']:3d} {m:>7}")
            mean_text = "--" if t["total"]["mean"] is None else format(t["total"]["mean"], "+.2%")
            win_text = "--" if t["total"]["winrate"] is None else f"{t['total']['winrate']:.0%}"
            L.append(
                f"  {month}  {'ON ' if gate_key == 'gate_on' else 'OFF'}  {t['total']['n']:4d}  {mean_text:>7}  {win_text:>3} | "
                + "  ".join(parts)
            )
    L.append("```")
    L.append("- gate OFF 行 = 同 band 不剔 gate_blocked 的对照 (评估 regime gate 月度价值的直接证据).")
    L.append("- ⚠ 月度样本 n≈百级且跨月事件相关, 本表只描述不检验; 显著性走 Q1 聚类 bootstrap.")
    L.append("")
    return L


def render_md(pack: dict, manifest: dict, eligibility: dict) -> str:
    L = ["# BTST Court Decision Pack", ""]
    L.append(f"- 构建日: {pack['as_of']} · 事件表: {manifest['artifact']} ({manifest['rows']} hits) · git `{manifest['git_sha'][:10]}`")
    L.append(f"- 窗口: {manifest['window']['start']}→{manifest['window']['end']} ({manifest['window']['sessions']} sessions) · 公式指纹见 manifest_v1.json")
    if "freshness" in pack:
        L.append(freshness_line(pack["freshness"]))
    L.append(f"- 资格漏斗: {json.dumps(eligibility, ensure_ascii=False)}")
    L.append(f"- 宇宙对账: {json.dumps(manifest['universe_audit'], ensure_ascii=False)}")
    xc = manifest["cross_check_vs_panel"]
    L.append(f"- 公式钉住交叉验证: {xc.get('matched', 0)} matched / {xc.get('mismatched', 0)} mismatched / {xc.get('absent', 0)} absent")
    L.append("")
    q1 = pack["q1"]
    L.append("## Q1 期限 (主对照 T+8 vs T+10, 配对, 净收益 30bps)")
    L.append(f"- T+8: {q1['headline']['t8_net30']} · T+10: {q1['headline']['t10_net30']}")
    L.append(f"- Δmean: 30bps {q1['headline']['delta_mean_30bps']} / 60bps {q1['headline']['delta_mean_60bps']} · 半窗 {[h for h in q1['headline']['halves']]} · normal-only {q1['headline']['normal_only_delta']}")
    L.append(f"- 聚类 bootstrap 90% CI 下界: {q1['headline']['cluster_boot90_ci_low']} (按信号日重采样)")
    L.append(f"- **预注册门: {q1['gates']} → {'✅ 允许提出 T+8 提案' if q1['primary_pass_all_gates'] else '❌ no-change'}**")
    L.append(f"- exploratory: {json.dumps(q1['exploratory'], ensure_ascii=False, default=str)}")
    L.append("")
    L.append("## Q2 阈值曲线 (净收益 T+10, 现行公式强度)")
    q2 = pack["q2"]
    L.append("```")
    for bkt, r in q2["curve"].items():
        L.append(f"  {bkt}  n={r['n']:4d}  E={r['E']:+.2%}  WR={r['WR']:.0%}")
    L.append("```")
    L.append(f"- Spearman ρ={q2['spearman_rho']} (p={q2['spearman_p']}) · 半窗 {q2['halves_rho']} · 门 {q2['gates']}")
    L.append("")
    L.append("## Q3 开盘 gap 条件曲线 (净收益, 执行口径)")
    q3 = pack["q3"]
    L.append("```")
    for bkt, r in q3["deciles"].items():
        ret5_text = format(r["ret5"], "+.2%") if r["ret5"] is not None else "--"
        L.append(f"  {bkt}  n={r['n']:4d}  ret5={ret5_text:>8}  ret10={r['ret10']:+.2%}")
    L.append("```")
    L.append(f"- +2% 以上分桶 E(t10): {q3['above2_buckets_E_t10']} · 分区形状 {json.dumps(q3['zone_breakdown'], ensure_ascii=False)}")
    L.append(f"- 悬崖检验 {json.dumps(q3['cliff_tests'], ensure_ascii=False)} · 门 {q3['gates']} · 候选悬崖 {q3['proposed_cliff']}")
    L.append("- ⚠ 形状同读: 悬崖门通过 ≠ 3% 处有悬崖; 若毒性集中在 >6% 尾区, 按 3% 跳过会误杀 3~6% 正 EV 区.")
    L.append("")
    L.extend(render_monthly_md(pack["monthly_by_regime"]))
    L.append("## 强度十分位校准表 (研究产物, 不构成接线授权)")
    L.append("```")
    for d, r in pack["calibration"].items():
        L.append(f"  D{d:02d} {r['ts']}  n={r['n']:4d}  E_t10={r['E_t10']:+.2%}  WR={r['WR_t10']:.0%}  E_t8={'' if r['E_t8'] is None else format(r['E_t8'], '+.2%')}")
    L.append("```")
    L.append("")
    L.append("## 边界声明")
    L.append("- 窗口仅 13.5 个月, 含一次 7 月回调; 2022/2024 跨周期不可证 (fund_flow 2025-07 起).")
    L.append("- 本 pack 只允许提出提案; 任何激活 = 新证据世代 + 版本化快照 + 在途计划迁移评估.")
    L.append("- 校准表派生自重放 (现行公式), panel 继续作为前向 OOS 仪器独立积累.")
    return "\n".join(L)


def main() -> None:
    table_path = TABLE_DIR / "event_table_v1.parquet"
    if not table_path.exists():
        table_path = TABLE_DIR / "event_table_v1.csv.gz"
    table = pd.read_parquet(table_path) if table_path.suffix == ".parquet" else pd.read_csv(table_path)
    manifest = json.loads((TABLE_DIR / "manifest_v1.json").read_text(encoding="utf-8"))

    eligible = table[
        ~table["degraded"] & ~table["industry_missing"] & ~table["st_name"] & ~table["excluded_ticker"]
        & table["price_ge_3"] & ~table["gate_blocked"]
    ].copy()
    # 生产交易带: _MIN_TRIGGER_STRENGTH=0.50 是计划资格的一部分 (scan 层过滤).
    # Q1/Q3/校准在交易带上评判; Q2 保留全距以显示梯度 (含 <0.5 毒带).
    traded = eligible[eligible["fillable"] & (eligible["trigger_strength"] >= MIN_TRIGGER_STRENGTH)]
    threshold_view = eligible[eligible["fillable"]]
    eligibility = {
        "hits_total": int(len(table)),
        "eligible": int(len(eligible)),
        "eligible_fillable": int(len(traded)),
        "blocked_by": {
            "degraded": int(table["degraded"].sum()),
            "industry_missing": int(table["industry_missing"].sum()),
            "st": int(table["st_name"].sum()),
            "gate": int(table["gate_blocked"].sum()),
            "unfillable_t1": int((eligible["fillable"] == False).sum()),  # noqa: E712
        },
    }

    # 主收益列预计算
    traded["ret"] = net_ret(traded["gross_ret_t10"], SLIPPAGE_BPS)
    fresh = table_freshness(manifest, current_setup_sha(), date.today())
    pack = {
        "as_of": date.today().isoformat(),
        "freshness": fresh,
        "eligibility": eligibility,
        "q1": q1_horizon(traded, manifest),
        "q2": q2_threshold(threshold_view),
        "q3": q3_gap(traded),
        "calibration": calibration(eligible[eligible["fillable"]]),
        "monthly_by_regime": monthly_by_regime(table),
    }
    stamp = date.today().strftime("%Y%m%d")
    md_path = Path(f"data/reports/btst_court_decision_pack_{stamp}.md")
    json_path = Path(f"data/reports/btst_court_decision_pack_{stamp}.json")
    md_path.write_text(render_md(pack, manifest, eligibility), encoding="utf-8")
    json_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(render_md(pack, manifest, eligibility))
    print(f"\n→ {md_path} / {json_path}")
    problems = freshness_problems(fresh)
    if problems:
        # 产物照写保留 (存档价值), 但以非零退出强提示 — 过期/错位表上的结论不可直接采信。
        print(f"\n⚠ {'; '.join(problems)}\n{REBUILD_HINT}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
