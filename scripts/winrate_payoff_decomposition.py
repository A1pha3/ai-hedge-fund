"""court 全候选胜率×赔率分解诊断 (只读, 2026-08-22, 第十轮).

背景: BTST 现行先验是全局常数 (court 生产对齐重校准: 净 E=+0.56%/
胜率 46.45%/CI90 [-1.30%,+2.39%] 跨 0) — 胜率与赔率被平均化掩盖了
条件化结构。本工具把 expectancy = p·W − (1−p)·L 做恒等分解:

    ΔE(组 vs 全体) = 胜率贡献 + 赔付贡献   (精确恒等, 无残差)
    胜率贡献 = (p_g − p_b)·(W_b + |L_b|)
    赔付贡献 = p_g·(W_g − W_b) − (1−p_g)·(|L_g| − |L_b|)

回答 "edge 是胜率驱动还是赔付驱动、集中在哪个 regime/强度桶" —
是强度阈值重校准 (panel 已见 0.50-0.60 桶反向) 与 Kelly 先验条件化
的共同地基。

预注册纪律 (先于数据):
- 证据宇宙 = court 全候选执行口径 (含退市者; 宪法 #2: 胜率/赔率只作
  诊断, 绝不替代组合路径证据; 陷阱 19: 不用 journal 成交子集);
- 净收益 = gross − (2×30bps + 5bps)/1e4, 与 btst_court_views.net_ret
  同式 (往返 0.65%);
- 聚类 CI: 按信号日聚类池化 bootstrap (镜像 btst_court_views 修复后
  口径 — 重采样天、池化事件后取逐事件均值, 固定种子可复现);
- 每格 n<30 → 只披露不给判定 (cluster_ci 为 None);
- 无亏损组 payoff 未定义 → None, 不给 inf;
- 本工具是诊断, 不是参数变更提案 — 任何阈值/先验/仓位调整 = 策略
  行为变化 = 新证据世代 (owner 决策)。

写入: data/reports/winrate_payoff_decomposition_YYYYMMDD.{md,json}。
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

SLIPPAGE_BPS = 30.0
SELL_STAMP_BPS = 5.0
ROUNDTRIP_COST = (2 * SLIPPAGE_BPS + SELL_STAMP_BPS) / 1e4  # 0.65%
MIN_CELL_N = 30  # 与 panel_health_check / panel_signal_decomposition 一致
N_BOOT = 10_000
RNG = np.random.default_rng(20260822)  # 固定种子: 报告可复现
PRIMARY_HORIZON = 10  # BTST 固定合约
CONTRAST_HORIZONS = (5,)

STRENGTH_BUCKETS: tuple[tuple[float, str], ...] = (
    (0.50, "0.50-0.60"),
    (0.60, "0.60-0.70"),
    (0.70, "≥0.70"),
)


def net_returns(gross: list[float | None]) -> list[float | None]:
    """gross → 净收益 (None 透传; 与 btst_court_views.net_ret 同式)。"""
    return [
        None if g is None or (isinstance(g, float) and math.isnan(g))
        else g - ROUNDTRIP_COST
        for g in gross
    ]


def strength_bucket(strength: float | None) -> str:
    """0.50/0.60/0.70 左闭右开 (与 panel_signal_decomposition 同侧)。"""
    if strength is None or (isinstance(strength, float) and math.isnan(strength)):
        return "unknown"
    if strength < 0.50:
        return "<0.50"
    if strength < 0.60:
        return "0.50-0.60"
    if strength < 0.70:
        return "0.60-0.70"
    return "≥0.70"


def win_loss_stats(
    rets: list[float],
    days: list[str] | None = None,
) -> dict[str, object]:
    """n/胜率/avg_win/avg_loss/payoff/expectancy + (n≥MIN_CELL_N) 聚类 CI 下界。

    expectancy 是逐事件均值的恒等重写 (p·W − (1−p)·L); 恰 0 净收益记
    负侧 (保守)。cluster_ci_low_90 只在样本足够时给出, 否则 None。
    """
    n = len(rets)
    if n == 0:
        return {
            "n": 0, "wins": 0, "winrate": None, "avg_win": None,
            "avg_loss": None, "payoff": None, "expectancy": None,
            "cluster_ci_low_90": None,
        }
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    p = len(wins) / n
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0  # 负值或 0(无亏损)
    payoff = (avg_win / abs(avg_loss)) if (losses and avg_loss < 0) else None
    stats: dict[str, object] = {
        "n": n,
        "wins": len(wins),
        "winrate": p,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff": payoff,
        "expectancy": p * avg_win + (1 - p) * avg_loss,
        "cluster_ci_low_90": None,
    }
    if days is not None and n >= MIN_CELL_N and len(set(days)) >= 2:
        stats["cluster_ci_low_90"] = cluster_boot_ci_low(rets, days)
    return stats


def cluster_boot_ci_low(
    rets: list[float], days: list[str], ci: float = 0.90, n_boot: int = N_BOOT
) -> float:
    """按信号日聚类池化 bootstrap (镜像 btst_court_views 修复后口径:
    重采样天 → 池化被抽中天的全部事件 → 逐事件均值)。"""
    by_day: dict[str, list[float]] = {}
    for r, d in zip(rets, days):
        by_day.setdefault(d, []).append(r)
    pools = [np.asarray(v) for v in by_day.values()]
    k = len(pools)
    means = np.empty(n_boot)
    for i in range(n_boot):
        pick = RNG.integers(0, k, k)
        means[i] = np.concatenate([pools[j] for j in pick]).mean()
    return float(np.quantile(means, 1 - ci))


def attribution(group: dict[str, object], base: dict[str, object]) -> dict[str, float]:
    """ΔE 的精确恒等分解: 胜率贡献 + 赔付贡献 == ΔE (无残差)。

    base 需含非 None 的 winrate/avg_win/avg_loss (基准=全体)。全胜/全负
    基准 (avg_loss=0 或 payoff None) 下恒等式仍成立 — 分解用 avg_win/
    avg_loss 本体, 不用 payoff 比。
    """
    p_g, p_b = float(group["winrate"]), float(base["winrate"])
    w_g, w_b = float(group["avg_win"]), float(base["avg_win"])
    l_g, l_b = float(group["avg_loss"]), float(base["avg_loss"])
    winrate_contrib = (p_g - p_b) * (w_b + abs(l_b))
    payoff_contrib = p_g * (w_g - w_b) - (1 - p_g) * (abs(l_g) - abs(l_b))
    return {
        "delta_expectancy": float(group["expectancy"]) - float(base["expectancy"]),
        "winrate_contribution": winrate_contrib,
        "payoff_contribution": payoff_contrib,
    }


def _group_rows(
    df: pd.DataFrame, horizon: int
) -> list[tuple[str, pd.DataFrame]]:
    """主分组面: 全体 / regime / 强度桶 / regime×强度。"""
    ret_col = f"net_ret_t{horizon}"
    valid = df[df[ret_col].notna()]
    out: list[tuple[str, pd.DataFrame]] = [("ALL", valid)]
    for regime in sorted(valid["regime"].dropna().unique()):
        out.append((f"regime={regime}", valid[valid["regime"] == regime]))
    for bucket in ("<0.50", "0.50-0.60", "0.60-0.70", "≥0.70", "unknown"):
        sub = valid[valid["strength_bucket"] == bucket]
        if len(sub):
            out.append((f"strength={bucket}", sub))
    for regime in sorted(valid["regime"].dropna().unique()):
        for bucket in ("0.50-0.60", "0.60-0.70", "≥0.70"):
            sub = valid[(valid["regime"] == regime) & (valid["strength_bucket"] == bucket)]
            if len(sub):
                out.append((f"{regime}×{bucket}", sub))
    return out


def decompose(df: pd.DataFrame) -> dict[str, object]:
    """对每个 horizon 产出分组表 + 相对全体的归因分解。"""
    payload: dict[str, object] = {
        "roundtrip_cost": ROUNDTRIP_COST,
        "min_cell_n": MIN_CELL_N,
        "horizons": {},
    }
    for horizon in (PRIMARY_HORIZON, *CONTRAST_HORIZONS):
        work = df.copy()
        work[f"net_ret_t{horizon}"] = net_returns(
            work[f"gross_ret_t{horizon}"].tolist()
        )
        work["strength_bucket"] = work["trigger_strength"].map(strength_bucket)
        rows = []
        base_stats: dict[str, object] | None = None
        for label, sub in _group_rows(work, horizon):
            rets = sub[f"net_ret_t{horizon}"].tolist()
            days = sub["signal_date"].astype(str).tolist()
            stats = win_loss_stats(rets, days)
            entry = {
                "group": label,
                **stats,
            }
            if label == "ALL":
                base_stats = stats
            rows.append(entry)
        assert base_stats is not None
        for entry in rows:
            if entry["n"] and entry["group"] != "ALL":
                entry["attribution_vs_all"] = attribution(entry, base_stats)
            else:
                entry["attribution_vs_all"] = None
        payload["horizons"][f"t{horizon}"] = rows
    return payload


def _fmt(v: object, pct: bool = True) -> str:
    if v is None:
        return "—"
    if isinstance(v, (int,)) and not isinstance(v, bool):
        return str(v)
    x = float(v)
    return f"{x:+.2%}" if pct else f"{x:.2f}"


def render_md(payload: dict[str, object], date_str: str) -> str:
    L: list[str] = []
    L.append(f"# court 全候选胜率×赔率分解 ({date_str})")
    L.append("")
    L.append("纯诊断 (宪法 #2: 胜率/赔率不替代组合路径证据; 陷阱 19: 证据宇宙 =")
    L.append("court 全候选执行口径, 非 journal 成交子集)。净收益 = 毛收益 −")
    L.append(f"往返 {ROUNDTRIP_COST:.2%} (30bps/边滑点 + 5bps 卖出印花税, 与")
    L.append("btst_court_views 同式)。归因分解为精确恒等: 胜率贡献 + 赔付贡献")
    L.append("= ΔE(组 vs 全体)。聚类 CI 按信号日池化 bootstrap (90% 下界);")
    L.append(f"n<{MIN_CELL_N} 的格子只披露不判定。")
    L.append("")
    for key, rows in payload["horizons"].items():
        L.append(f"## {key}")
        L.append("")
        L.append(
            "| 分组 | n | 胜率 | avg_win | avg_loss | payoff | E | 胜率贡献 | 赔付贡献 | ΔE | CI90下界 |"
        )
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for r in rows:
            attr = r.get("attribution_vs_all")
            if attr:
                wr, pf, de = (
                    _fmt(attr["winrate_contribution"]),
                    _fmt(attr["payoff_contribution"]),
                    _fmt(attr["delta_expectancy"]),
                )
            else:
                wr = pf = de = "—"
            ci = _fmt(r.get("cluster_ci_low_90"))
            L.append(
                f"| {r['group']} | {r['n']} | {_fmt(r['winrate'])} |"
                f" {_fmt(r['avg_win'])} | {_fmt(r['avg_loss'])} |"
                f" {_fmt(r['payoff'], pct=False)} | {_fmt(r['expectancy'])} |"
                f" {wr} | {pf} | {de} | {ci} |"
            )
        L.append("")
    L.append("## 纪律")
    L.append("")
    L.append("- 本报告是诊断证据, 不是参数变更提案; 任何阈值/先验/仓位调整 =")
    L.append("  策略行为变化 = 新证据世代 (owner 决策 + 预注册)。")
    L.append("- 无亏损组 payoff 未定义记 '—'; 恰 0 净收益记负侧 (保守)。")
    L.append("- 复现: `uv run python scripts/winrate_payoff_decomposition.py`")
    L.append(f"  (固定 bootstrap 种子; court 表 {COURT_TABLE})。")
    L.append("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--court-table", default=str(COURT_TABLE),
                        help="court 事件表路径 (默认生产 csv.gz; 测试用 fixture)")
    parser.add_argument("--report-dir", default=str(REPORT_DIR),
                        help="报告输出目录 (测试用 tmp)")
    args = parser.parse_args(argv)

    date_str = date.today().strftime("%Y%m%d")
    report_dir = Path(args.report_dir)
    json_path = report_dir / f"winrate_payoff_decomposition_{date_str}.json"
    md_path = report_dir / f"winrate_payoff_decomposition_{date_str}.md"

    court_table = Path(args.court_table)
    if not court_table.exists():
        raise SystemExit(f"court 事件表缺失: {court_table}")
    ev = pd.read_csv(court_table)
    payload = decompose(ev)
    payload["court_rows"] = len(ev)
    payload["court_sessions"] = int(ev["signal_date"].nunique())
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    md_path.write_text(render_md(payload, date_str), encoding="utf-8")
    print(f"written: {md_path} + {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
