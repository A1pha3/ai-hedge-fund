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
        "provenance": f"known_distributions.BTST_BREAKOUT_T10 ({d.provenance})",
    }


def candidate_universe(ev: pd.DataFrame) -> pd.DataFrame:
    """gate 放行 & 可成交 & 有 T+10 收益的生产可比宇宙."""
    mask = (
        (ev["fillable"] == True)  # noqa: E712
        & (ev["gate_blocked"] != True)  # noqa: E712
        & ev[HORIZON_COL].notna()
    )
    return ev.loc[mask].copy()


# 生产可计划过滤链在研究重验中的对齐维度 (degraded/ST/行业缺失/排除名单/低价).
# 列缺失 = 口径理解错误, fail closed 不静默当作不过滤.
PRODUCTION_EXCLUDE_COLS = ("degraded", "st_name", "industry_missing", "excluded_ticker")
PRODUCTION_DISCLOSURE_KEYS = PRODUCTION_EXCLUDE_COLS + ("price_lt_3",)
# 预注册半年度切片 (court 研究窗口 20250102 起 — R90 Op3 随 owner 授权的
# 窗口前扩重注册, 2025H1 段覆盖回填权威宇宙审计后的新可见历史; 末段右开,
# 窗口再移动 (如跨 2027) 后需再次重注册 — time_slices 对越界行 fail-closed)
TIME_SLICE_BOUNDS = (
    # 早期窗口 (2022-24) 预注册段 (R94): 全市场 flow 回填后早期表升级为一等
    # 评估面 — 生产表运行时这些段呈 n=0 空段 (slice_partitions 空段诚实保留),
    # 早期表运行时 2025+ 段为空段; 覆盖守卫对两宇宙同时成立。
    ("2022H1", "20220104", "20220630"),
    ("2022H2", "20220701", "20221231"),
    ("2023H1", "20230101", "20230630"),
    ("2023H2", "20230701", "20231231"),
    ("2024H1", "20240101", "20240630"),
    ("2024H2", "20240701", "20241231"),
    ("2025H1", "20250102", "20250630"),
    ("2025H2", "20250701", "20251231"),
    ("2026H1", "20260101", "20260630"),
    ("2026H2+", "20260701", "99999999"),
)


def _require_production_cols(u: pd.DataFrame) -> None:
    missing = [c for c in PRODUCTION_EXCLUDE_COLS + ("price_ge_3",) if c not in u.columns]
    if missing:
        raise ValueError(f"production-universe columns missing: {missing} (口径理解错误, fail closed)")


def production_universe(u: pd.DataFrame) -> pd.DataFrame:
    """candidate_universe 之上再对齐生产可计划过滤链 (degraded/ST/行业缺失/排除名单/低价)."""
    _require_production_cols(u)
    mask = ~u[list(PRODUCTION_EXCLUDE_COLS)].any(axis=1)
    mask &= u["price_ge_3"] == True  # noqa: E712
    return u.loc[mask].copy()


def exclusion_disclosure(u: pd.DataFrame, n_boot: int = N_BOOT_DEFAULT) -> dict:
    """生产过滤链排除行的分组披露 (净口径; 组间可有重叠, total 为去重行数).

    排除行的 E 是生产过滤链样本外价值的直接证据 (trap 20 同型: 数据管道
    缺口 vs 策略过滤 是两层, 这里量化的是策略过滤层).
    """
    _require_production_cols(u)
    excluded_any = u[list(PRODUCTION_EXCLUDE_COLS)].any(axis=1) | (u["price_ge_3"] != True)  # noqa: E712
    groups = []
    for key in PRODUCTION_DISCLOSURE_KEYS:
        m = (~u["price_ge_3"]) if key == "price_lt_3" else u[key]
        g = u[m == True]  # noqa: E712
        rets = net_ret(g[HORIZON_COL]) if len(g) else pd.Series(dtype=float)
        s = stats_block(rets, g["signal_date"] if len(g) else pd.Series(dtype=object), n_boot=n_boot)
        groups.append({"key": key, "n": s["n"], "mean": s["mean"], "winrate": s["winrate"]})
    return {
        "groups": groups,
        "total_excluded": int(excluded_any.sum()),
        "retained": int((~excluded_any).sum()),
        "note": "组间可重叠 (一行命中多维度); total_excluded 为去重行数",
    }


def slice_partitions(u: pd.DataFrame) -> list[tuple[str, str, str, pd.DataFrame]]:
    """预注册半年度切片划分的单一实现: ``[(label, lo, hi, 子帧)]``.

    消费方: 本模块 ``time_slices`` (整宇宙切片统计) 与
    ``winrate_payoff_decomposition.slice_bucket_stability`` (切片×强度桶) —
    划分口径 (标签/边界/完备覆盖守卫) 一份, 防两侧漂移.

    日期序列化容错: 比较 ``signal_date`` 前剥掉 ISO 短横 (``2026-01-02`` →
    ``20260102``), 生产表为紧凑格式, 行为不变; 覆盖守卫不依赖序列化格式.
    空段诚实保留 (n=0 子帧), 越界行 fail-closed (窗口移动后必须重注册
    TIME_SLICE_BOUNDS, 不静默缺段).
    """
    sd = u["signal_date"].astype(str).str.slice(0, 10).str.replace("-", "", regex=False)
    parts: list[tuple[str, str, str, pd.DataFrame]] = []
    covered = None
    for label, lo, hi in TIME_SLICE_BOUNDS:
        in_slice = (sd >= lo) & (sd <= hi)
        covered = in_slice if covered is None else (covered | in_slice)
        parts.append((label, lo, hi, u[in_slice]))
    outside = int((~covered).sum()) if covered is not None else 0
    if outside:
        samples = sorted(sd[~covered].unique())[:5]
        raise ValueError(
            f"time-slice coverage gap: {outside} rows outside preregistered "
            f"slices (样例 {samples}) — 窗口移动后必须重注册 TIME_SLICE_BOUNDS, "
            "不静默缺段 (切片完备覆盖不重不漏的执行面)"
        )
    return parts


def time_slices(u: pd.DataFrame, n_boot: int = N_BOOT_DEFAULT) -> list[dict]:
    """预注册半年度切片: 全候选 stats + 段内每日 top-1 (生产行为近似).

    空段诚实保留 (n=0/mean=None); 划分与越界 fail-closed 守卫在
    ``slice_partitions`` (单一实现, 切片完备覆盖不重不漏的执行面).
    """
    out = []
    for label, lo, hi, m in slice_partitions(u):
        s = stats_block(net_ret(m[HORIZON_COL]), m["signal_date"], n_boot=n_boot) if len(m) else {
            "n": 0, "mean": None, "winrate": None, "ci90_low": None, "ci90_high": None,
        }
        top1 = {"n": 0, "trade_mean": None, "winrate": None}
        if len(m):
            t = m.sort_values("trigger_strength", ascending=False).groupby("signal_date").head(1)
            rets = net_ret(t[HORIZON_COL])
            top1 = {
                "n": int(len(t)),
                "trade_mean": float(rets.mean()),
                "winrate": float((rets > 0).mean()),
            }
        out.append({"label": label, "range": f"{lo}..{hi}", **s, "top_1": top1})
    return out


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
    p = production_universe(u)
    prod_view = stats_block(net_ret(p[HORIZON_COL]), p["signal_date"], n_boot=n_boot)
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
            "universe": "现行=fillable & !gate_blocked & ret 非空; 生产对齐=再排除 degraded/ST/行业缺失/排除名单/price<3",
            "n_boot": n_boot,
            "seed": BOOT_SEED,
            "prior": prior,
            **table_freshness(load_manifest(), current_setup_sha(), date.today()),
        },
        "all_candidates": all_view,
        "production_aligned": prod_view,
        "exclusion_disclosure": exclusion_disclosure(u, n_boot=n_boot),
        "time_slices": time_slices(p, n_boot=n_boot),
        "strength_quintiles": strength_quintiles(u, n_boot=n_boot),
        "daily_topk": topk,
        "gate_blocked_contrast": blocked_stats,
        "deviation": {
            "all_candidates": deviation_block(all_view, prior),
            "production_aligned": deviation_block(prod_view, prior),
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
    prod = rep["production_aligned"]
    top1 = rep["daily_topk"]["top_1"]
    # 2026-08-19 owner 批准重校准后, 先验即 court 生产对齐口径 — 断言从
    # 「先验系统性虚高」(旧) 改为「对齐」: 先验期望须落在生产对齐宇宙
    # bootstrap CI 的宽容带内 (±1pp, 覆盖不同 n_boot 种子抖动), 且方向
    # 不允许回到虚高 >6pp 的旧关系; 若 court 表重建后对齐破坏, 这里当天暴露.
    er_delta_pp = abs(prior["expected_return"] - prod["mean"]) * 100
    assert er_delta_pp <= 1.0, (
        f"对齐断言失败: 先验期望 {prior['expected_return']:.4f} 与生产对齐宇宙 "
        f"{prod['mean']:.4f} 偏离 {er_delta_pp:.2f}pp > 1pp — 先验与 court 口径脱钩, 回 Observe"
    )
    assert prior["winrate"] - prod["winrate"] < 0.10, (
        f"方向断言失败: 先验胜率 {prior['winrate']:.4f} 高于生产对齐宇宙 "
        f"{prod['winrate']:.4f} 达 10pp — 回到旧「虚高」关系, 重校准失效"
    )
    assert 0 < top1["trade_mean"] < 0.04, (
        f"top-1 量级断言失败: {top1['mean']:.4f} 不在 (0, 0.04) — 与预验 (+1.77% 毛 / +1.12% 净) 背离"
    )
    # T+8 对齐哨点 (2026-08-22 补齐重校准的配套): 与 T+10 同款 ±1pp/胜率
    # 虚高 <10pp 语义 — court 表重建后 T+8 先验脱钩当天暴露.
    from src.screening.offensive.known_distributions import BTST_BREAKOUT_T8

    t8 = net_ret(candidate_universe(ev)["gross_ret_t8"].dropna())
    t8_er_delta = abs(BTST_BREAKOUT_T8.expected_return - t8.mean()) * 100
    assert t8_er_delta <= 1.0, (
        f"T+8 对齐断言失败: 先验期望 {BTST_BREAKOUT_T8.expected_return:.4f} 与 "
        f"court 生产对齐 {t8.mean():.4f} 偏离 {t8_er_delta:.2f}pp > 1pp"
    )
    assert BTST_BREAKOUT_T8.winrate - (t8 > 0).mean() < 0.10, (
        f"T+8 方向断言失败: 先验胜率 {BTST_BREAKOUT_T8.winrate:.4f} 高于 court "
        f"{(t8 > 0).mean():.4f} 达 10pp — 回到旧虚高关系"
    )
    print(
        json.dumps({
            "check": "ok",
            "all_candidates": allv,
            "production_aligned": prod,
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
        "## 生产对齐宇宙 (净口径, 再排除 degraded/ST/行业缺失/排除名单/price<3)",
        "",
        f"- n={rep['production_aligned']['n']}  E={rep['production_aligned']['mean']:+.4%}  "
        f"win={rep['production_aligned']['winrate']:.1%}  "
        f"CI90=[{rep['production_aligned']['ci90_low']:+.4%}, {rep['production_aligned']['ci90_high']:+.4%}]",
        "",
        "## 排除行披露 (现行宇宙内被生产过滤链排除的行, 净口径)",
        "",
        "| 维度 | n | E | win |",
        "|---|---|---|---|",
    ]
    ed = rep["exclusion_disclosure"]
    for g in ed["groups"]:
        mean_txt = f"{g['mean']:+.4%}" if g["mean"] is not None else "—"
        win_txt = f"{g['winrate']:.1%}" if g["winrate"] is not None else "—"
        lines.append(f"| {g['key']} | {g['n']} | {mean_txt} | {win_txt} |")
    lines += [
        f"",
        f"- 去重排除 {ed['total_excluded']} 行 · 保留 {ed['retained']} 行 ({ed['note']})",
        "",
        "## 时间切片 (生产对齐宇宙, 预注册半年度)",
        "",
        "| 段 | n | E | win | top1 n | top1 E | top1 win |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in rep["time_slices"]:
        mean_txt = f"{t['mean']:+.4%}" if t["mean"] is not None else "—"
        win_txt = f"{t['winrate']:.1%}" if t["winrate"] is not None else "—"
        t1 = t["top_1"]
        t1_mean = f"{t1['trade_mean']:+.4%}" if t1["trade_mean"] is not None else "—"
        t1_win = f"{t1['winrate']:.1%}" if t1["winrate"] is not None else "—"
        lines.append(f"| {t['label']} | {t['n']} | {mean_txt} | {win_txt} | {t1['n']} | {t1_mean} | {t1_win} |")
    lines += [
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
