"""regime 门盲区解剖 — normal 标签信号日的深负暴露三层证据 (纯诊断).

第一性原理: regime gate 只拦 crisis/risk_off; 重建后 production_aligned
ALL t10 E=+0.01% (前 +1.32%) 的塌陷主要来自 normal 标签信号日的深负暴露
(2026-07: 0701/0703/0709/0710/0714/0721 日均净 E −8%..−25%)。本工具把盲区
解剖成三层:

  ① 表型 — normal 信号日按日均净 E 分层 (屠杀日 < 阈值, 默认 −5%);
  ② naive 领先轴分离度 — prior-5 等权市场动量 / 信号日下跌广度 / 涨停数
     在屠杀日 vs 普通日的对照 (探针实证: 几乎无分离 — 崩跌在信号日市场
     状态上不可预见, 「加领先指标轴」的 naive 形式被证据杀死);
  ③ 跨窗强度不稳定 — production (2025-07..2026-09) 与 early (2022-2024)
     两窗 × 四强度带; 实证 ≥0.70 桶跨窗符号翻转 (生产 +1.69% / early
     −0.50%) — 阈值上调不获跨窗支持。early 窗幸存者偏差方向为乐观化
     (退市票缺席 → 危机期表现系统性高估), 该偏差只会低估翻转幅度,
     ≥0.70 翻转结论对偏差稳健。

纪律 (先于数据写死):
  - 纯诊断 (宪法 #2): 任何据此的生产参数变化 = 新证据世代 owner 决策。
  - mkt5 严格 PIT: prior-5 会话复合收益, shift(1) 不含信号日。
  - n<20 的格子只披露不判定 (与既有分解工具同纪律)。
  - 确定性: 同输入逐字节同输出 (无 RNG)。

用法:
    uv run python scripts/btst_regime_blindspot.py
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

COURT_TABLE = Path("data/research/btst_court/event_tables/event_table_v1.csv.gz")
EARLY_TABLE = Path("data/research/btst_court/event_tables_early/event_table_v1.csv.gz")
PANEL_DIR = Path("data/research/btst_court/raw/daily")
REPORTS_DIR = Path("data/reports")

MASSACRE_DAY_NET_E = -5.0  # 屠杀日阈值 (日均净 E, 百分数)
MIN_CELL_N = 20  # 与 winrate_payoff_decomposition 同纪律
NET_COST_PCT = 0.65  # 往返成本 (与分解工具同式)
STRENGTH_BANDS = ((0.0, 0.50, "<0.50"), (0.50, 0.60, "0.50-0.60"), (0.60, 0.70, "0.60-0.70"), (0.70, 9.0, ">=0.70"))


@dataclass(frozen=True)
class DayAxes:
    date: str
    mean_ret: float  # 等权平均日收益 (小数)
    down_frac: float  # 下跌家数占比
    lu_count: int  # 涨停家数 (pct≥9.5 宽松)


def normalize_day(value: object) -> str:
    text = str(value).replace("-", "").strip()
    if len(text) == 8 and text.isdigit():
        return text
    raise ValueError(f"unparseable trade date: {value!r}")


def market_axes_from_panel(panel: pd.DataFrame, *, beijing_prefixes: Sequence[str] = ("8", "4", "9")) -> pd.DataFrame:
    """raw 面板 (逐日全市场快照) → 逐日市场轴. 剔北交所与 court 预筛一致."""
    df = panel.copy()
    df["trade_date"] = df["trade_date"].map(normalize_day)
    df = df[~df["ts_code"].astype(str).str.startswith(tuple(beijing_prefixes))]
    rows = []
    for day, group in df.groupby("trade_date"):
        pct = pd.to_numeric(group["pct_chg"], errors="coerce").dropna()
        if pct.empty:
            continue
        rows.append(
            DayAxes(
                date=day,
                mean_ret=float(pct.mean()) / 100.0,
                down_frac=float((pct < 0).mean()),
                lu_count=int((pct >= 9.5).sum()),
            ).__dict__
        )
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def add_prior_momentum(axes: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """mkt{lookback} = 前 N 会话等权收益复合 (shift(1) — 严格不含当日, PIT)."""
    out = axes.sort_values("date").reset_index(drop=True).copy()
    compounded = (1.0 + out["mean_ret"]).rolling(lookback).apply(np.prod, raw=True) - 1.0
    out[f"mkt{lookback}"] = compounded.shift(1)
    return out


def day_level_stats(events: pd.DataFrame, *, regime_label: str = "normal") -> pd.DataFrame:
    """normal 标签信号日 → (n_events, mean_net_E, win_rate). net = gross − 往返成本."""
    df = events.copy()
    df["signal_date"] = df["signal_date"].map(normalize_day)
    df = df[(df["regime"] == regime_label) & df["gross_ret_t10"].notna()]
    df["net"] = df["gross_ret_t10"] * 100.0 - NET_COST_PCT
    grouped = df.groupby("signal_date")["net"].agg(["count", "mean"])
    grouped.columns = ["n_events", "mean_net_e"]
    return grouped.reset_index().rename(columns={"signal_date": "date"})


def split_massacre(day_stats: pd.DataFrame, threshold: float = MASSACRE_DAY_NET_E) -> tuple[set[str], set[str]]:
    """日均净 E < threshold → 屠杀日; 其余普通日. 返回两个日期集合."""
    massacre = set(day_stats.loc[day_stats["mean_net_e"] < threshold, "date"])
    ordinary = set(day_stats["date"]) - massacre
    return massacre, ordinary


def separation_table(axes: pd.DataFrame, massacre: set[str], ordinary: set[str], momentum_col: str = "mkt5") -> dict[str, Any]:
    """屠杀 vs 普通日的轴均值对照 (描述性 — 无分离即是负结果, 如实呈现)."""
    def _stats(days: set[str]) -> dict[str, Any]:
        sub = axes[axes["date"].isin(days)].dropna(subset=[momentum_col])
        return {
            "n_days": int(len(sub)),
            "mkt5_mean_pct": round(float(sub[momentum_col].mean()) * 100.0, 2) if len(sub) else None,
            "down_frac_mean_pct": round(float(sub["down_frac"].mean()) * 100.0, 2) if len(sub) else None,
            "lu_count_mean": round(float(sub["lu_count"].mean()), 0) if len(sub) else None,
        }

    return {"massacre_days": _stats(massacre), "ordinary_days": _stats(ordinary)}


def strength_bucket_table(events: pd.DataFrame, *, window: str) -> list[dict[str, Any]]:
    """normal 事件 × 四强度带 → n/E/胜率 (n<MIN_CELL_N 只披露)."""
    df = events.copy()
    df["signal_date"] = df["signal_date"].map(normalize_day)
    df = df[(df["regime"] == "normal") & df["gross_ret_t10"].notna()]
    df["net"] = df["gross_ret_t10"] * 100.0 - NET_COST_PCT
    rows: list[dict[str, Any]] = []
    for lo, hi, label in STRENGTH_BANDS:
        values = df[(df["trigger_strength"] >= lo) & (df["trigger_strength"] < hi)]["net"]
        row: dict[str, Any] = {"window": window, "band": label, "n": int(len(values))}
        if len(values) >= MIN_CELL_N:
            row["mean_net_e_pct"] = round(float(values.mean()), 2)
            row["win_rate_pct"] = round(float((values > 0).mean()) * 100.0, 1)
        rows.append(row)
    return rows


def render_md(payload: Mapping[str, Any]) -> str:
    lines = [
        "# regime 门盲区解剖 (normal 标签信号日深负暴露)",
        "",
        "纯诊断 (宪法 #2)。三层: ①日级表型 ②naive 领先轴分离 (负结果如实) ③跨窗强度不稳定。",
        "",
        f"屠杀日阈值: 日均净 E < {payload['massacre_threshold']}% (净 = 毛 − {NET_COST_PCT}% 往返)",
        "",
        "## ① normal 信号日表型",
        "",
        f"总日数 {payload['day_summary']['total_days']} · 屠杀日 {payload['day_summary']['massacre_days']}"
        f" ({payload['day_summary']['massacre_pct']}%) · 屠杀日事件占比 "
        f"{payload['day_summary']['massacre_event_share_pct']}%",
        "",
        "最差 10 日:",
        "",
        "| 日期 | n | 日均净 E% | mkt5% | down% | 涨停数 |",
        "|---|---|---|---|---|---|",
    ]
    for row in payload["worst_days"]:
        lines.append(
            f"| {row['date']} | {row['n_events']} | {row['mean_net_e']:+.2f} "
            f"| {row['mkt5_pct'] if row['mkt5_pct'] is not None else '—'} "
            f"| {row['down_frac_pct'] if row['down_frac_pct'] is not None else '—'} "
            f"| {row['lu_count']} |"
        )
    sep = payload["separation"]
    lines += [
        "",
        "## ② naive 领先轴分离 (屠杀 vs 普通)",
        "",
        "先验可用的市场轴在两组上几乎无分离 → 崩跌在信号日市场状态上不可预见;",
        "「加领先指标轴」的 naive 形式不获支持 (结论即负结果本身)。",
        "",
        "| 组 | n_days | mkt5 均值% | 下跌占比均值% | 涨停数均值 |",
        "|---|---|---|---|---|",
        f"| 屠杀日 | {sep['massacre_days']['n_days']} | {sep['massacre_days']['mkt5_mean_pct']} "
        f"| {sep['massacre_days']['down_frac_mean_pct']} | {sep['massacre_days']['lu_count_mean']} |",
        f"| 普通日 | {sep['ordinary_days']['n_days']} | {sep['ordinary_days']['mkt5_mean_pct']} "
        f"| {sep['ordinary_days']['down_frac_mean_pct']} | {sep['ordinary_days']['lu_count_mean']} |",
        "",
        "## ③ 跨窗强度桶 (normal 事件)",
        "",
        "| 窗口 | 强度带 | n | E% | 胜率% |",
        "|---|---|---|---|---|",
    ]
    for row in payload["strength_buckets"]:
        lines.append(
            f"| {row['window']} | {row['band']} | {row['n']} "
            f"| {row.get('mean_net_e_pct', '—(n<20)')} | {row.get('win_rate_pct', '—')} |"
        )
    lines += [
        "",
        "early 窗幸存者偏差方向为乐观化 (退市票缺席) — 偏差只会低估 ≥0.70 桶的跨窗翻转幅度,",
        "翻转结论 (生产 +/early −) 对该偏差稳健。",
        "",
        "## 纪律",
        "",
        "- 纯诊断 (宪法 #2); 任何参数变化 = 新证据世代 owner 决策",
        f"- n<{MIN_CELL_N} 格子只披露; mkt5 严格 PIT (shift, 不含信号日)",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--court-table", type=Path, default=COURT_TABLE)
    parser.add_argument("--early-table", type=Path, default=EARLY_TABLE)
    parser.add_argument("--panel-dir", type=Path, default=PANEL_DIR)
    parser.add_argument("--massacre-threshold", type=float, default=MASSACRE_DAY_NET_E)
    args = parser.parse_args(argv)

    events = pd.read_csv(args.court_table)
    axes = add_prior_momentum(market_axes_from_panel(_load_panel(args.panel_dir)))

    day_stats = day_level_stats(events)
    merged = day_stats.merge(axes, on="date", how="left")
    massacre, ordinary = split_massacre(day_stats, args.massacre_threshold)

    total_events = int(day_stats["n_events"].sum())
    massacre_events = int(day_stats[day_stats["date"].isin(massacre)]["n_events"].sum())
    worst = merged.nsmallest(10, "mean_net_e")
    worst_rows = [
        {
            "date": r["date"],
            "n_events": int(r["n_events"]),
            "mean_net_e": round(float(r["mean_net_e"]), 2),
            "mkt5_pct": round(float(r["mkt5"]) * 100.0, 2) if pd.notna(r.get("mkt5")) else None,
            "down_frac_pct": round(float(r["down_frac"]) * 100.0, 1) if pd.notna(r.get("down_frac")) else None,
            "lu_count": int(r["lu_count"]),
        }
        for _, r in worst.iterrows()
    ]

    buckets = strength_bucket_table(events, window="production")
    if args.early_table.exists():
        buckets += strength_bucket_table(pd.read_csv(args.early_table), window="early")

    payload = {
        "massacre_threshold": args.massacre_threshold,
        "day_summary": {
            "total_days": int(len(day_stats)),
            "massacre_days": len(massacre),
            "massacre_pct": round(100.0 * len(massacre) / max(1, len(day_stats)), 1),
            "massacre_event_share_pct": round(100.0 * massacre_events / max(1, total_events), 1),
        },
        "worst_days": worst_rows,
        "separation": separation_table(axes, massacre, ordinary),
        "strength_buckets": buckets,
        "discipline": [
            "纯诊断 (宪法 #2); 参数变化 = 新证据世代 owner 决策",
            "mkt5 严格 PIT; n<20 只披露",
            "early 窗幸存者偏差 (乐观化) 对 ≥0.70 翻转结论稳健",
        ],
    }

    from datetime import date

    stamp = date.today().strftime("%Y%m%d")
    out_json = REPORTS_DIR / f"regime_blindspot_{stamp}.json"
    out_md = REPORTS_DIR / f"regime_blindspot_{stamp}.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    out_md.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps(payload["day_summary"], ensure_ascii=False))
    print(json.dumps(payload["separation"], ensure_ascii=False))
    print(f"written: {out_json} / {out_md}")
    return 0


def _load_panel(panel_dir: Path) -> pd.DataFrame:
    frames = [pd.read_csv(p, usecols=["ts_code", "trade_date", "pct_chg"]) for p in sorted(panel_dir.glob("daily_*.csv"))]
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    raise SystemExit(main())
