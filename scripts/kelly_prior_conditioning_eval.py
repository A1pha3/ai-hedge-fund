"""Kelly 先验条件化评估 (只读诊断, 2026-08-22, 第十五轮).

问题: 现行 BTST 先验是全局常数 (w=46.45%, g=+13.44%, b=−10.62% → full
Kelly ≈ 0.39, half-Kelly ≈ 19.4%, 全部被 10% 单票 cap 截断)。若按强度桶
条件化先验, Kelly fraction 从 <0.50 桶的**负值** (不该下注) 到 ≥0.70 桶
≈ +1.84 差异巨大 — 但在现体系里 cap 是实际绑定约束, 条件化只是次级
调节器。本工具量化三件事:

1. 桶级 Kelly vs 全局先验对照 (复用 src kelly_fraction 纯函数), 含
   half-Kelly 与 cap 命中披露;
2. 桶间排序的 split-half 时间稳定性 (前/后半会话期独立算桶级 Kelly,
   排序 Spearman — 不稳定的条件化 = 过拟合, 无消费价值);
3. 每桶聚类 CI (镜像双口径工具 per-call seeded RNG 纪律)。

纪律: 本工具只产证据。任何先验/cap/阈值变更 = 策略行为变化 = 新证据
世代 (owner 决策 + 预注册); n<30 桶只披露不判定; 负 Kelly 桶如实披露
"全局先验会说下注、桶级证据说不该" 的张力。

写入: data/reports/kelly_conditioning_eval_YYYYMMDD.{md,json}。
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

COURT_TABLE = Path("data/research/btst_court/event_tables/event_table_v1.csv.gz")
REPORT_DIR = Path("data/reports")
MIN_CELL_N = 30
BOOT_SEED = 20260822
N_BOOT = 5_000
HORIZON = 10
ROUNDTRIP_COST = 0.0065  # 与 winrate_payoff_decomposition/btst_court_views 同式
HALF_KELLY = 0.5
CAP_PCT = 0.10
#: 近零亏损门槛: |avg_loss| 低于此值时二元 Kelly (w/b − (1−w)/g) 的第一项
#: 数值爆炸 (如 avg_loss=-0.0002 → kelly_full=825), 无消费意义 — 退化
#: 披露而非输出荒谬确定感 (R16 对抗审查 PoC)。
MIN_ABS_LOSS_FOR_KELLY = 0.005
BUCKETS = ("<0.50", "0.50-0.60", "0.60-0.70", "≥0.70")


def strength_bucket(strength: float) -> str:
    if strength is None or (isinstance(strength, float) and math.isnan(strength)):
        return "unknown"
    if strength < 0.50:
        return "<0.50"
    if strength < 0.60:
        return "0.50-0.60"
    if strength < 0.70:
        return "0.60-0.70"
    return "≥0.70"


def production_aligned(ev: pd.DataFrame) -> pd.DataFrame:
    """复用 review_btst_prior_court 单一实现 (与 winrate 工具同款, 防口径漂移)。"""
    import sys

    scripts = str(Path(__file__).resolve().parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from review_btst_prior_court import PRODUCTION_EXCLUDE_COLS, candidate_universe

    required = ["fillable", "gate_blocked", "price_ge_3", *PRODUCTION_EXCLUDE_COLS]
    missing = [c for c in required if c not in ev.columns]
    if missing:
        raise SystemExit(f"court 事件表缺少生产过滤列: {sorted(missing)}")
    universe = candidate_universe(ev)
    excluded = universe[list(PRODUCTION_EXCLUDE_COLS)].any(axis=1) | (
        universe["price_ge_3"] != True  # noqa: E712
    )
    return universe.loc[~excluded].copy()


def kelly_stats(rets: list[float]) -> dict[str, object] | None:
    """桶级 (w, g, b) → kelly_fraction (复用 src 纯函数) + cap 披露。"""
    from src.screening.offensive.kelly import kelly_fraction

    if not rets:
        return None
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    if not wins or not losses:
        return None  # 无盈或无亏 → Kelly 公式退化, 只披露不计算
    w = len(wins) / len(rets)
    g = sum(wins) / len(wins)
    b = sum(losses) / len(losses)
    degenerate = abs(b) < MIN_ABS_LOSS_FOR_KELLY
    if degenerate:
        return {
            "n": len(rets),
            "winrate": w,
            "avg_gain": g,
            "avg_loss": b,
            "kelly_full": None,
            "kelly_half": None,
            "implied_pct_uncapped": None,
            "capped_at_10pct": None,
            "negative_kelly": None,
            "degenerate_kelly": True,
        }
    full = kelly_fraction(w, g, b)
    half = HALF_KELLY * full
    return {
        "n": len(rets),
        "winrate": w,
        "avg_gain": g,
        "avg_loss": b,
        "kelly_full": full,
        "kelly_half": half,
        "implied_pct_uncapped": half,
        "capped_at_10pct": half > CAP_PCT,
        "negative_kelly": full < 0,
        "degenerate_kelly": False,
    }


def cluster_ci_low(rets: list[float], days: list[str]) -> float | None:
    if len(rets) < MIN_CELL_N or len(set(days)) < 2:
        return None
    rng = np.random.default_rng(BOOT_SEED)  # per-call: 与进程历史无关 (R13 纪律)
    pools = {}
    for r, d in zip(rets, days):
        pools.setdefault(d, []).append(r)
    arrs = [np.asarray(v) for v in pools.values()]
    k = len(arrs)
    means = np.empty(N_BOOT)
    for i in range(N_BOOT):
        pick = rng.integers(0, k, k)
        means[i] = np.concatenate([arrs[j] for j in pick]).mean()
    return float(np.quantile(means, 0.10))


def bucket_rows(frame: pd.DataFrame) -> list[dict[str, object]]:
    ret_col = f"net_ret_t{HORIZON}"
    work = frame[frame["gross_ret_t10"].notna()].copy()
    work[ret_col] = work["gross_ret_t10"] - ROUNDTRIP_COST
    work["bucket"] = work["trigger_strength"].map(strength_bucket)
    rows: list[dict[str, object]] = []
    for bucket in BUCKETS:
        sub = work[work["bucket"] == bucket]
        rets = sub[ret_col].tolist()
        days = sub["signal_date"].astype(str).tolist()
        entry: dict[str, object] = {"bucket": bucket}
        stats = kelly_stats(rets)
        if stats is None:
            entry.update({"n": len(rets), "note": "无盈或无亏, Kelly 退化"})
        else:
            entry.update(stats)
        entry["e_mean"] = (sum(rets) / len(rets)) if rets else None
        entry["cluster_ci_low_90"] = cluster_ci_low(rets, days)
        rows.append(entry)
    return rows


def _spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) != len(b) or len(a) < 3:
        return None
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def split_half_stability(frame: pd.DataFrame) -> dict[str, object]:
    """前/后半会话期独立算桶级 Kelly → 排序 Spearman + 逐桶符号一致性。"""
    work = frame[frame["gross_ret_t10"].notna()].copy()
    work["bucket"] = work["trigger_strength"].map(strength_bucket)
    sessions = sorted(work["signal_date"].unique())
    mid = sessions[len(sessions) // 2]
    halves = {
        "first_half": work[work["signal_date"] < mid],
        "second_half": work[work["signal_date"] >= mid],
    }
    half_rows = {name: bucket_rows(h) for name, h in halves.items()}
    order = [b for b in BUCKETS]
    k_first = [
        (r.get("kelly_full") if isinstance(r.get("kelly_full"), float) else None)
        for r in half_rows["first_half"]
    ]
    k_second = [
        (r.get("kelly_full") if isinstance(r.get("kelly_full"), float) else None)
        for r in half_rows["second_half"]
    ]
    usable = [i for i in range(len(order)) if k_first[i] is not None and k_second[i] is not None]
    rho = (
        _spearman([k_first[i] for i in usable], [k_second[i] for i in usable])
        if len(usable) >= 3
        else None
    )
    sign_stable = (
        all((k_first[i] > 0) == (k_second[i] > 0) for i in usable) if usable else None
    )
    return {
        "split_date": str(mid),
        "first_half_rows": half_rows["first_half"],
        "second_half_rows": half_rows["second_half"],
        "bucket_order": order,
        "spearman_kelly_order": rho,
        "kelly_sign_stable_across_halves": sign_stable,
        "verdict_hint": (
            "可用桶不足 (<3 桶可算 Kelly) — 样本不支持稳定性判定"
            if rho is None
            else "排序不稳定 — 条件化 Kelly 无消费价值 (过拟合)"
            if rho < 0.5
            else (
                "排序稳定但符号跨半翻转 — 桶级『下注/不下注』定性判断"
                "不稳定, 条件化证据不足 (符号一致是排序稳定的前置条件)"
                if sign_stable is not True
                else "排序且符号均稳定 — 条件化具备进一步评估资格 (仍非授权)"
            )
        ),
    }


def evaluate(ev: pd.DataFrame) -> dict[str, object]:
    aligned = production_aligned(ev)
    rows = bucket_rows(aligned)
    global_row = kelly_stats(
        (aligned["gross_ret_t10"].dropna() - ROUNDTRIP_COST).tolist()
    )
    return {
        "universe": "production_aligned (n=…见行)",
        "roundtrip_cost": ROUNDTRIP_COST,
        "global_prior_kelly": global_row,
        "buckets": rows,
        "split_half": split_half_stability(aligned),
        "cap_note": (
            f"现行 cap={CAP_PCT:.0%}; half-Kelly > cap 的桶全部触顶 — "
            "条件化在现体系是次级调节器, cap 才是绑定约束; 负 Kelly 桶是唯一"
            "全局先验无法表达的实质信号"
        ),
    }


def _fmt(v: object, pct: bool = True) -> str:
    if v is None:
        return "—"
    x = float(v)
    return f"{x:+.2%}" if pct else f"{x:.2f}"


def render_md(payload: dict[str, object], date_str: str) -> str:
    L: list[str] = []
    L.append(f"# Kelly 先验条件化评估 ({date_str})")
    L.append("")
    L.append("只读诊断 — 只产证据, 不提议参数变更 (任何先验/cap/阈值变化 = 新证据")
    L.append("世代 owner 决策)。宇宙 = court 生产对齐; 净收益扣往返 0.65%; Kelly 复用")
    L.append("src 纯函数; CI 按信号日池化 bootstrap (per-call seeded, R13 纪律);")
    L.append(f"n<{MIN_CELL_N} 只披露不判定。")
    L.append("")
    g = payload["global_prior_kelly"]
    L.append(f"全局先验: full Kelly = {g['kelly_full']:.3f}, half = {g['kelly_half']:.1%} "
             f"(w={g['winrate']:.2%}, g={g['avg_gain']:+.2%}, b={g['avg_loss']:+.2%}) — "
             f"capped@10%: {g['capped_at_10pct']}")
    L.append("")
    L.append("| 强度桶 | n | full K | half K | 触顶 | 负K | E | CI90下界 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in payload["buckets"]:
        L.append(
            f"| {r['bucket']} | {r['n']} | {_fmt(r.get('kelly_full'), pct=False)}"
            f" | {_fmt(r.get('kelly_half'))} | {'是' if r.get('capped_at_10pct') else '—'}"
            f" | {'**负**' if r.get('negative_kelly') else '—'}"
            f" | {_fmt(r.get('e_mean'))} | {_fmt(r.get('cluster_ci_low_90'))} |"
        )
    L.append("")
    sh = payload["split_half"]
    L.append(f"## split-half 稳定性 (切分日 {sh['split_date']})")
    L.append("")
    L.append(f"- 桶级 Kelly 排序 Spearman: {sh['spearman_kelly_order']}")
    L.append(f"- Kelly 符号跨半一致: {sh['kelly_sign_stable_across_halves']}")
    L.append(f"- 结论提示: {sh['verdict_hint']}")
    L.append(f"- cap 披露: {payload['cap_note']}")
    L.append("")
    L.append("复现: `uv run python scripts/kelly_prior_conditioning_eval.py`")
    L.append("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--court-table", default=str(COURT_TABLE))
    parser.add_argument("--report-dir", default=str(REPORT_DIR))
    args = parser.parse_args(argv)

    table = Path(args.court_table)
    if not table.exists():
        raise SystemExit(f"court 事件表缺失: {table}")
    ev = pd.read_csv(table)
    payload = evaluate(ev)
    date_str = date.today().strftime("%Y%m%d")
    out = Path(args.report_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"kelly_conditioning_eval_{date_str}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (out / f"kelly_conditioning_eval_{date_str}.md").write_text(
        render_md(payload, date_str), encoding="utf-8"
    )
    print(f"written: {out / f'kelly_conditioning_eval_{date_str}.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
