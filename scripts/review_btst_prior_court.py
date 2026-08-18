"""BTST court 先验重验 (研究只读): 当前生效 Kelly 先验 vs 全候选执行口径.

背景 (AGENTS.md trap 4): known_distributions.BTST_BREAKOUT_T10 于 2026-07-12
由 626 票连续涨停样本校准 (未扣费、非执行口径), 早于 2026-07-18 journal
锚定修正与 2026-08-16 执行口径重建, 从未按两者重验。先验直接进入 Kelly
仓位, 偏差量化是生产风险证据缺口。本脚本把重验固化为一条命令可重跑:

口径 (显式冻结, 改动即重开重验):
- 宇宙   : fillable==True & gate_blocked!=True & gross_ret_t10 非空
           (gate 放行 ≡ 生产 2026-08-14 起 crisis/risk_off 不开新仓)
- 收益   : T+1 开盘买 → T+10 开盘卖 (open→open), 毛值=事件表 gross_ret_t10
- 净成本 : 30bps/边滑点 + 5bps 卖出印花税 (与 btst_court_views.net_ret 同源)
- 推断   : 按信号日聚类 bootstrap (重采样天, 池化事件) 单侧 90% CI
- 五视角 : 全候选 / 强度五分位 / 每日 top-K / gate_blocked 对照 / 先验偏差

边界: 本脚本只产报告, 不改常量、不进 Kelly、不构成重校准授权;
重校准 = 策略行为变化, 需要 owner + 新证据世代 (宪章第 13 条)。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _btst_court_common import SELL_STAMP_BPS, SLIPPAGE_BPS, TABLE_DIR  # noqa: E402

TABLE_PATH = TABLE_DIR / "event_table_v1.csv.gz"
MANIFEST_PATH = TABLE_DIR / "manifest_v1.json"
HORIZON_COL = "gross_ret_t10"
BOOT_SEED = 20260818  # 固定种子: 报告可复现
N_BOOT_DEFAULT = 3_000
MAX_TABLE_AGE_DAYS = 45  # 跨期评估的表龄上限 (≈30 个交易日的宽松版)
SETUP_REL_PATH = Path("src/screening/offensive/setups/btst_breakout.py")
REBUILD_HINT = (
    "court 事件表不可信 — 重建: uv run python scripts/btst_court_fetch.py "
    "&& uv run python scripts/btst_court_build.py"
)


def load_manifest() -> dict | None:
    """读取 court manifest; 缺失返回 None (诚实披露, fail 与否由消费方决定)."""
    if not MANIFEST_PATH.exists():
        return None
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def current_setup_sha() -> str:
    """当前生产 BTST setup 的 sha256 (与 btst_court_build._file_sha256 同口径)."""
    repo_root = Path(__file__).resolve().parent.parent
    return hashlib.sha256((repo_root / SETUP_REL_PATH).read_bytes()).hexdigest()


def table_freshness(manifest: dict | None, setup_sha: str, today: date) -> dict:
    """事件表新鲜度 × 公式漂移守卫 (纯函数, 只产事实不猜)."""
    if manifest is None:
        return {
            "manifest_present": False,
            "built_at": None,
            "age_days": None,
            "manifest_setup_sha": None,
            "current_setup_sha": setup_sha,
            "formula_match": None,
        }
    built_at = date.fromisoformat(str(manifest.get("built_at")))
    manifest_sha = str(manifest.get("formula_fingerprint", {}).get("btst_breakout_sha256", ""))
    return {
        "manifest_present": True,
        "built_at": str(manifest.get("built_at")),
        "age_days": (today - built_at).days,
        "manifest_setup_sha": manifest_sha,
        "current_setup_sha": setup_sha,
        "formula_match": manifest_sha == setup_sha if manifest_sha else None,
    }


def net_ret(gross: pd.Series, slip_bps: float = SLIPPAGE_BPS) -> pd.Series:
    """毛收益 → 净收益 (双边滑点 + 卖出印花税), 与 court views 同口径."""
    return gross - (2 * slip_bps + SELL_STAMP_BPS) / 1e4


def prior_snapshot() -> dict:
    """生产先验原样引用 (committed 常量, 不复制数值到本文件)."""
    from src.screening.offensive.known_distributions import BTST_BREAKOUT_T10

    d = BTST_BREAKOUT_T10
    return {
        "expected_return": d.expected_return,
        "winrate": d.winrate,
        "avg_gain": d.avg_gain,
        "avg_loss": d.avg_loss,
        "ci_low": d.ci_low,
        "ci_high": d.ci_high,
        "n": d.n,
        "provenance": "known_distributions.BTST_BREAKOUT_T10 (2026-07-12 校准, 连续涨停样本, 未扣费)",
    }


def candidate_universe(ev: pd.DataFrame) -> pd.DataFrame:
    """gate 放行 & 可成交 & 有 T+10 收益的生产可比宇宙."""
    mask = (
        (ev["fillable"] == True)  # noqa: E712
        & (ev["gate_blocked"] != True)  # noqa: E712
        & ev[HORIZON_COL].notna()
    )
    return ev.loc[mask].copy()


def cluster_boot_ci_low(diffs: pd.Series, days: pd.Series, ci: float = 0.90, n_boot: int = N_BOOT_DEFAULT, seed: int = BOOT_SEED) -> float:
    """按信号日聚类 bootstrap 单侧下界 (重采样天 → 池化事件取均值).

    与 btst_court_views.cluster_boot_ci_low 同算法, 但种子可注入 (可测).
    """
    by_day = [g.to_numpy() for _, g in diffs.groupby(days)]
    n = len(by_day)
    if n == 0 or n_boot <= 0:
        return float("nan")
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    for i in range(n_boot):
        pick = rng.integers(0, n, n)
        means[i] = np.concatenate([by_day[j] for j in pick]).mean()
    return float(np.quantile(means, 1 - ci))


def _cluster_boot_quantile(
    diffs: pd.Series, days: pd.Series, q: float, n_boot: int, seed: int
) -> float:
    """聚类 bootstrap 的任意分位 (重采样天 → 池化事件取均值)."""
    by_day = [g.to_numpy() for _, g in diffs.groupby(days)]
    k = len(by_day)
    if k == 0 or n_boot <= 0:
        return float("nan")
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    for i in range(n_boot):
        pick = rng.integers(0, k, k)
        means[i] = np.concatenate([by_day[j] for j in pick]).mean()
    return float(np.quantile(means, q))


def stats_block(r: pd.Series, days: pd.Series, n_boot: int = N_BOOT_DEFAULT) -> dict:
    """n / mean / winrate / 单侧 90% 聚类 CI (上下界皆报, 空样本诚实返回 None)."""
    if len(r) == 0:
        return {"n": 0, "mean": None, "winrate": None, "ci90_low": None, "ci90_high": None}
    return {
        "n": int(len(r)),
        "mean": float(r.mean()),
        "winrate": float((r > 0).mean()),
        "ci90_low": _cluster_boot_quantile(r, days, 0.10, n_boot, BOOT_SEED),
        "ci90_high": _cluster_boot_quantile(r, days, 0.90, n_boot, BOOT_SEED + 1),
    }


def strength_quintiles(u: pd.DataFrame, n_boot: int = N_BOOT_DEFAULT) -> list[dict]:
    """trigger_strength 五分位 (生产排序键), 每组独立净口径 stats_block."""
    u = u.copy()
    u["q"] = pd.qcut(u["trigger_strength"], 5, labels=False, duplicates="drop")
    out = []
    for q in sorted(u["q"].dropna().unique()):
        g = u[u["q"] == q]
        s = stats_block(net_ret(g[HORIZON_COL]), g["signal_date"], n_boot=n_boot)
        out.append({
            "label": f"Q{int(q) + 1}",
            "strength_min": float(g["trigger_strength"].min()),
            "strength_max": float(g["trigger_strength"].max()),
            **s,
        })
    return out


def daily_topk(u: pd.DataFrame, k: int, n_boot: int = N_BOOT_DEFAULT) -> dict:
    """每日按强度取前 k 笔 (生产行为的组合路径近似), 净口径.

    笔级 E/win + 日组合等权收益的复合 NAV。NAV 是诊断口径: 允许同日并行、
    未建模资金占用/容量约束 — 用于与'笔级均值'对照, 不是回测。
    返回键用 trade_mean (笔级) 以区别于日组合均值。
    """
    u = u.sort_values(["signal_date", "trigger_strength"], ascending=[True, False])
    topk = u.groupby("signal_date").head(k)
    rets = net_ret(topk[HORIZON_COL])
    s = stats_block(rets, topk["signal_date"], n_boot=n_boot)
    daily = rets.groupby(topk["signal_date"]).mean()
    return {
        "trade_mean": s["mean"],
        **{k2: v for k2, v in s.items() if k2 != "mean"},
        "days": int(daily.shape[0]),
        "nav_compound": float((1 + daily).prod()),
    }


def deviation_block(court: dict, prior: dict) -> dict:
    """先验 vs 单一口径的偏差 (倍数与 pp; 空口径返回 None 不猜)."""
    if court.get("mean") is None:
        return {"er_multiple": None, "er_delta_pp": None, "winrate_delta_pp": None}
    er_mult = prior["expected_return"] / court["mean"] if court["mean"] != 0 else None
    return {
        "er_multiple": float(er_mult) if er_mult is not None else None,
        "er_delta_pp": float((prior["expected_return"] - court["mean"]) * 100),
        "winrate_delta_pp": float((prior["winrate"] - court["winrate"]) * 100),
    }


def build_report(ev: pd.DataFrame, n_boot: int = N_BOOT_DEFAULT) -> dict:
    prior = prior_snapshot()
    u = candidate_universe(ev)
    rets = net_ret(u[HORIZON_COL])
    all_view = stats_block(rets, u["signal_date"], n_boot=n_boot)
    topk = {f"top_{k}": daily_topk(u, k, n_boot=n_boot) for k in (1, 3, 5)}
    blocked = ev[(ev["gate_blocked"] == True) & ev[HORIZON_COL].notna()]  # noqa: E712
    blocked_rets = net_ret(blocked[HORIZON_COL]) if len(blocked) else pd.Series(dtype=float)
    blocked_days = blocked["signal_date"] if len(blocked) else pd.Series(dtype=object)
    blocked_stats = stats_block(blocked_rets, blocked_days, n_boot=n_boot)
    return {
        "fingerprint": {
            "rows": int(len(ev)),
            "date_min": str(ev["signal_date"].min()),
            "date_max": str(ev["signal_date"].max()),
            "horizon_col": HORIZON_COL,
            "cost_bps": 2 * SLIPPAGE_BPS + SELL_STAMP_BPS,
            "universe": "fillable & !gate_blocked & ret 非空",
            "n_boot": n_boot,
            "seed": BOOT_SEED,
            "prior": prior,
            **table_freshness(load_manifest(), current_setup_sha(), date.today()),
        },
        "all_candidates": all_view,
        "strength_quintiles": strength_quintiles(u, n_boot=n_boot),
        "daily_topk": topk,
        "gate_blocked_contrast": blocked_stats,
        "deviation": {
            "all_candidates": deviation_block(all_view, prior),
            "top_1": deviation_block(
                {"mean": topk["top_1"]["trade_mean"], "winrate": topk["top_1"]["winrate"]}, prior
            ),
        },
        "boundary": (
            "研究重验报告: 不改常量、不进 Kelly、不构成重校准授权; "
            "重校准 = 策略行为变化, 需 owner + 新证据世代 (宪章第 13 条)。"
        ),
    }


def run_check(ev: pd.DataFrame, today: date | None = None) -> None:
    """真实事件表方向断言 + 表新鲜度/公式漂移 fail-closed 断言 (verification 冻结命令)."""
    today = today or date.today()
    fresh = table_freshness(load_manifest(), current_setup_sha(), today)
    problems = []
    if not fresh["manifest_present"]:
        problems.append(f"manifest 缺失: {MANIFEST_PATH}")
    else:
        if fresh["age_days"] > MAX_TABLE_AGE_DAYS:
            problems.append(
                f"表龄 {fresh['age_days']} 天 > {MAX_TABLE_AGE_DAYS} (built_at {fresh['built_at']})"
            )
        if fresh["formula_match"] is not True:
            problems.append(
                f"公式漂移: manifest {str(fresh['manifest_setup_sha'])[:8]} "
                f"!= 当前 {str(fresh['current_setup_sha'])[:8]} (court 表不代表当前生产口径)"
            )
    if problems:
        print(json.dumps({"check": "blocked", "problems": problems, "hint": REBUILD_HINT}, ensure_ascii=False))
        raise SystemExit(2)
    rep = build_report(ev, n_boot=1_000)
    prior = rep["fingerprint"]["prior"]
    allv = rep["all_candidates"]
    top1 = rep["daily_topk"]["top_1"]
    assert allv["ci90_high"] < prior["ci_low"], (
        f"方向断言失败: 全候选净口径 CI 上界 {allv['ci90_high']:.4f} "
        f">= 先验 ci_low {prior['ci_low']:.4f} (先验或口径理解错误, 回 Observe)"
    )
    assert 0 < top1["trade_mean"] < 0.04, (
        f"top-1 量级断言失败: {top1['mean']:.4f} 不在 (0, 0.04) — 与预验 (+1.77% 毛 / +1.12% 净) 背离"
    )
    print(
        json.dumps({
            "check": "ok",
            "all_candidates": allv,
            "top_1": top1,
            "deviation": rep["deviation"],
        }, ensure_ascii=False)
    )


def render_md(rep: dict) -> str:
    fp = rep["fingerprint"]
    prior = fp["prior"]
    if fp.get("manifest_present") is True:
        age = fp.get("age_days")
        formula = fp.get("formula_match")
        stale = age is not None and age > MAX_TABLE_AGE_DAYS
        drift = formula is not True
        flag = " ⚠ " if (stale or drift) else ""
        notes = []
        if stale:
            notes.append(f"表龄 {age} 天 > {MAX_TABLE_AGE_DAYS}, 结论过期须重建")
        if drift:
            notes.append(f"公式漂移 (manifest {str(fp.get('manifest_setup_sha'))[:8]} != 当前 {str(fp.get('current_setup_sha'))[:8]}), court 表不代表当前生产口径")
        fresh_line = (
            f"- 事件表新鲜度:{flag} built_at {fp.get('built_at')} · 表龄 {age} 天 · "
            f"公式指纹{'一致' if formula is True else '漂移'}"
            + (f" · ⚠ {'; '.join(notes)}" if notes else "")
        )
    else:
        fresh_line = "- 事件表新鲜度: ⚠ manifest 缺失 — 表龄与公式指纹不可验证, 结论仅供存档参考"
    lines = [
        "# BTST T+10 先验 × court 全候选执行口径重验",
        "",
        f"- 事件表: {fp['rows']} 行, {fp['date_min']} → {fp['date_max']}",
        fresh_line,
        f"- 宇宙: {fp['universe']}; 净成本 {fp['cost_bps']:.0f}bps; 聚类 bootstrap n={fp['n_boot']} seed={fp['seed']}",
        f"- 先验: E={prior['expected_return']:+.2%} win={prior['winrate']:.1%} n={prior['n']} ({prior['provenance']})",
        "",
        "## 全候选 (净口径)",
        "",
        f"- n={rep['all_candidates']['n']}  E={rep['all_candidates']['mean']:+.4%}  "
        f"win={rep['all_candidates']['winrate']:.1%}  "
        f"CI90=[{rep['all_candidates']['ci90_low']:+.4%}, {rep['all_candidates']['ci90_high']:+.4%}]",
        "",
        "## 强度五分位 (净口径)",
        "",
        "| 档 | strength | n | E | win |",
        "|---|---|---|---|---|",
    ]
    for q in rep["strength_quintiles"]:
        lines.append(
            f"| {q['label']} | [{q['strength_min']:.2f}, {q['strength_max']:.2f}] "
            f"| {q['n']} | {q['mean']:+.4%} | {q['winrate']:.1%} |"
        )
    lines += ["", "## 每日 top-K (生产行为近似, 净口径)", "", "| 口径 | n | 天 | 笔级 E | win | 复合 NAV |", "|---|---|---|---|---|---|"]
    for name, t in rep["daily_topk"].items():
        lines.append(
            f"| {name} | {t['n']} | {t['days']} | {t['trade_mean']:+.4%} | {t['winrate']:.1%} | {t['nav_compound']:.3f} |"
        )
    if rep["gate_blocked_contrast"] and rep["gate_blocked_contrast"]["n"]:
        g = rep["gate_blocked_contrast"]
        lines += [
            "",
            "## gate_blocked 对照 (crisis/risk_off, 净口径)",
            "",
            f"- n={g['n']}  E={g['mean']:+.4%}  win={g['winrate']:.1%}  (gate 阻断的危机组, 应显著为负)",
        ]
    lines += ["", "## 先验偏差", ""]
    for name, d in rep["deviation"].items():
        if d["er_multiple"] is not None:
            lines.append(
                f"- {name}: 先验 E 是 court 的 {d['er_multiple']:.1f}× (+{d['er_delta_pp']:.1f}pp), "
                f"winrate 高 {d['winrate_delta_pp']:.1f}pp"
            )
    lines += ["", f"> {rep['boundary']}", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="真实事件表方向断言 (CI 上界 < 先验 ci_low 等)")
    parser.add_argument("--n-boot", type=int, default=N_BOOT_DEFAULT)
    args = parser.parse_args()

    if not TABLE_PATH.exists():
        raise SystemExit(f"event table missing: {TABLE_PATH} (先跑 btst_court_fetch/build)")
    ev = pd.read_csv(TABLE_PATH, dtype={"signal_date": str})
    if args.check:
        run_check(ev)
        return
    rep = build_report(ev, n_boot=args.n_boot)
    stamp = date.today().strftime("%Y%m%d")
    md_path = Path(f"data/reports/btst_prior_court_recheck_{stamp}.md")
    json_path = Path(f"data/reports/btst_prior_court_recheck_{stamp}.json")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    md_path.write_text(render_md(rep), encoding="utf-8")
    print(json.dumps({"written": str(md_path), "deviation": rep["deviation"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
