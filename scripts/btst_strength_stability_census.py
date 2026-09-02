"""强度轴跨窗稳定性普查 — R95 登记未交付的③号线落地 (纯诊断).

第一性原理: 阈值/强度讨论的一切结论都依赖「强度带的 E 是否跨时间窗稳定」。
R97 Op1 实证 ≥0.70 桶跨窗符号翻转 (production +1.69% vs early −0.50%) —
本工具把普查做完: 四强度带 + regime 参照轴 × 两窗 × 窗内时间序 split-half,
预注册判定规则冻结于代码:

  stable_positive   两窗 × 两半, E 全部 > 0 (格子 n≥30)
  stable_negative   两窗 × 两半, E 全部 < 0
  sign_unstable     任一格子符号与其余不一致
  insufficient      任一格子 n<30 (只披露不判定)

R15 verdict 纪律: 符号一致性是必要条件; 排序稳定性 (Spearman) 不足以判定
(排序稳定但符号翻转时「稳定」是误导性表述)。

CI: 复用 winrate_payoff_decomposition.cluster_boot_ci_low 单一实现
(per-call seeded RNG), 按信号日池化 bootstrap。

纪律 (先于数据写死):
  - 纯诊断 (宪法 #2): 任何据此的阈值/参数变化 = 新证据世代 owner 决策。
  - split-half = 窗内 signal_date 中位数切分 (时间序, 无随机)。
  - early 窗幸存者偏差方向为乐观化 → stable_negative 判定对偏差稳健,
    stable_positive 判定需打折 (成文于报告)。
  - 确定性: 同输入逐字节同输出。

用法:
    uv run python scripts/btst_strength_stability_census.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

COURT_TABLE = Path("data/research/btst_court/event_tables/event_table_v1.csv.gz")
EARLY_TABLE = Path("data/research/btst_court/event_tables_early/event_table_v1.csv.gz")
REPORTS_DIR = Path("data/reports")

MIN_CELL_N = 30
NET_COST_PCT = 0.65
STRENGTH_BANDS = (("<0.50", 0.0, 0.50), ("0.50-0.60", 0.50, 0.60), ("0.60-0.70", 0.60, 0.70), (">=0.70", 0.70, 9.0))
REGIME_LEVELS = ("crisis", "risk_off", "normal")
VERDICTS = ("stable_positive", "stable_negative", "sign_unstable", "insufficient")


def normalize_day(value: object) -> str:
    text = str(value).replace("-", "").strip()
    if len(text) == 8 and text.isdigit():
        return text
    raise ValueError(f"unparseable trade date: {value!r}")


def _cell(values: pd.Series, dates: pd.Series) -> dict[str, Any] | None:
    """一格 → n/E/胜率/聚类 CI90 下界 (复用分解工具单一实现)."""
    if len(values) == 0:
        return None
    row: dict[str, Any] = {"n": int(len(values))}
    if len(values) >= MIN_CELL_N:
        row["mean_net_e_pct"] = round(float(values.mean()), 2)
        row["win_rate_pct"] = round(float((values > 0).mean()) * 100.0, 1)
        try:
            from scripts.winrate_payoff_decomposition import cluster_boot_ci_low

            ci = cluster_boot_ci_low(dates.tolist(), values.tolist())
            row["ci90_low_pct"] = round(float(ci), 2) if ci is not None else None
        except Exception:  # noqa: BLE001 — CI 不可得时格子的判定仍可用 E 符号
            row["ci90_low_pct"] = None
    return row


def split_halves(dates: Sequence[str]) -> tuple[list[str], list[str]]:
    """时间序中位切分 (升序, 前半含中位). 无随机."""
    ordered = sorted(set(dates))
    if not ordered:
        return [], []
    mid = ordered[len(ordered) // 2]
    return [d for d in ordered if d <= mid], [d for d in ordered if d > mid]


def census_axis(
    events: pd.DataFrame,
    *,
    window: str,
    axis: str,
    groups: Sequence[tuple[str, Any, Any]],
) -> list[dict[str, Any]]:
    """单窗单轴普查: 每组 × (全窗/前半/后半) 三格."""
    df = events.copy()
    df["signal_date"] = df["signal_date"].map(normalize_day)
    df = df[df["gross_ret_t10"].notna()].copy()
    df["net"] = df["gross_ret_t10"] * 100.0 - NET_COST_PCT
    first_half, second_half = split_halves(df["signal_date"].tolist())
    rows: list[dict[str, Any]] = []
    for label, lo, hi in groups:
        if axis == "strength":
            mask = (df["trigger_strength"] >= lo) & (df["trigger_strength"] < hi)
        elif axis == "regime":
            mask = df["regime"] == label
        else:
            raise ValueError(f"unknown axis: {axis}")
        sub = df[mask]
        cells = {}
        for cell_name, part in (
            ("full", sub),
            ("h1", sub[sub["signal_date"].isin(first_half)]),
            ("h2", sub[sub["signal_date"].isin(second_half)]),
        ):
            cell = _cell(part["net"], part["signal_date"])
            if cell is not None:
                cells[cell_name] = cell
        rows.append({"window": window, "axis": axis, "group": label, "cells": cells})
    return rows


def verdict_for(row: Mapping[str, Any]) -> str:
    """预注册判定: 四格 (两窗两半) E 符号一致 → stable; n<30 → insufficient."""
    cells = row.get("cells") or {}
    es = {name: cell.get("mean_net_e_pct") for name, cell in cells.items()}
    ns = {name: cell.get("n", 0) for name, cell in cells.items()}
    required = ("full", "h1", "h2")
    if any(name not in cells for name in required):
        return "insufficient"
    if any(ns[name] < MIN_CELL_N for name in required):
        return "insufficient"
    signs = {es[name] > 0 for name in required}
    if len(signs) == 1:
        return "stable_positive" if signs.pop() else "stable_negative"
    return "sign_unstable"


def cross_window_verdict(rows: Sequence[Mapping[str, Any]], group: str) -> dict[str, Any]:
    """同名组跨两窗合并判定 (取两窗 verdict 的合取: 任一窗 unstable/insufficient 即降级)."""
    per_window = {r["window"]: verdict_for(r) for r in rows if r["group"] == group}
    values = set(per_window.values())
    if not values:
        return {"group": group, "per_window": per_window, "verdict": "insufficient"}
    if values == {"stable_positive"}:
        merged = "stable_positive"
    elif values == {"stable_negative"}:
        merged = "stable_negative"
    elif "insufficient" in values:
        merged = "insufficient"
    else:
        merged = "sign_unstable"
    return {"group": group, "per_window": per_window, "verdict": merged}


def render_md(payload: Mapping[str, Any]) -> str:
    lines = [
        "# 强度轴跨窗稳定性普查 (预注册判定)",
        "",
        f"判定规则: stable = 两窗 × 两半 E 全同号 (格 n≥{MIN_CELL_N}); 任一半翻转 → sign_unstable;",
        "任格 n<30 → insufficient。split-half = 窗内信号日时间序中位切分。",
        "",
        "| 轴 | 组 | 窗 | n | E% | 胜率% | CI90低% | 窗verdict | 跨窗verdict |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    merged = {m["group"]: m for m in payload["merged_verdicts"]}
    for row in payload["rows"]:
        cells = row["cells"]
        full = cells.get("full", {})
        group_key = row["group"]
        cross = merged.get(group_key, {}).get("verdict", "—") if row["axis"] == "strength" else "—"
        lines.append(
            f"| {row['axis']} | {row['group']} | {row['window']} | {full.get('n', 0)} "
            f"| {full.get('mean_net_e_pct', '—')} | {full.get('win_rate_pct', '—')} "
            f"| {full.get('ci90_low_pct', '—')} | {verdict_for(row)} | {cross} |"
        )
    lines += [
        "",
        "## 跨窗合并判定 (强度轴)",
        "",
        "| 组 | production | early | 合并 |",
        "|---|---|---|---|",
    ]
    for m in payload["merged_verdicts"]:
        lines.append(f"| {m['group']} | {m['per_window'].get('production','—')} | {m['per_window'].get('early','—')} | {m['verdict']} |")
    lines += [
        "",
        "## 纪律",
        "",
        "- 纯诊断 (宪法 #2); 任何阈值/参数变化 = 新证据世代 owner 决策",
        "- 符号一致性是必要条件 (R15 纪律); 排序稳定不足以判定",
        "- early 窗幸存者偏差方向为乐观化: stable_negative 判定对偏差稳健,",
        "  stable_positive 判定需打折 (early 的正 E 上界被高估)",
        "- 宇宙口径: 全候选 (含 crisis/risk_off 事件), 与分解工具的 normal-only 口径不同 —",
        "  例: production 0.50-0.60 全宇宙 E=−0.74% vs normal-only +0.17% (差额即危机污染);",
        "  regime 参照轴单独呈现, 消费方勿将本表与 normal-only 表混读",
        "- 多重比较告诫: 四带普查后 0.60-0.70 是唯一 stable_positive — post-hoc 选择,",
        "  属 hypothesis-generating; 前向确认 (触发器/前向 trial) 前不构成任何参数变更依据",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--court-table", type=Path, default=COURT_TABLE)
    parser.add_argument("--early-table", type=Path, default=EARLY_TABLE)
    args = parser.parse_args(argv)

    rows: list[dict[str, Any]] = []
    windows = []
    for window, path in (("production", args.court_table), ("early", args.early_table)):
        if not path.exists():
            continue
        events = pd.read_csv(path)
        windows.append(window)
        rows += census_axis(events, window=window, axis="strength", groups=STRENGTH_BANDS)
        rows += census_axis(events, window=window, axis="regime", groups=[(r, None, None) for r in REGIME_LEVELS])

    merged = [cross_window_verdict(rows, g) for g, _, _ in STRENGTH_BANDS]
    payload = {
        "rows": rows,
        "merged_verdicts": merged,
        "rules": {
            "min_cell_n": MIN_CELL_N,
            "verdicts": VERDICTS,
            "split": "window-median signal_date, time-ordered",
        },
        "universe": "all_candidates",
        "discipline": [
            "纯诊断 (宪法 #2); 参数变化 = 新证据世代 owner 决策",
            "符号一致性必要 (R15); early 幸存者偏差方向成文",
        ],
    }
    from datetime import date

    stamp = date.today().strftime("%Y%m%d")
    out_json = REPORTS_DIR / f"strength_stability_census_{stamp}.json"
    out_md = REPORTS_DIR / f"strength_stability_census_{stamp}.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    out_md.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps([{m["group"]: m["verdict"]} for m in merged], ensure_ascii=False))
    print(f"written: {out_json} / {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
