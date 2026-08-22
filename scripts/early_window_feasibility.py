"""2022-2024 早期 court 窗口可行性评估 (只读, 2026-08-22, R22).

问题: court 全保真重放下界是 2025-07 (fund_flow 全市场覆盖起点), 跨牛熊
regime 证据只有 13 个月。2022-2024 是否可用**部分宇宙**构建早期窗口?

扫描面 (纯函数, 真实扫描为主进程):
1. 双缓存逐年覆盖: price_cache / fund_flow_cache 每年有数据的票数;
2. 交集宇宙: 两缓存 2022-2024 三年全覆盖的票;
3. 触发密度: 交集宇宙内按板块自适应阈值的涨停日数 (BTST 候选原料下界).

结论口径 (2026-08-22 真实扫描, 见 data/reports/early_window_feasibility_*.md):
交集 648 票 / 涨停日 5700 (年均 1900) — 原料充足、管道现成 (btst_court_
build 直接 import 生产检测器), **技术上可行**; 但 648 票是"历史数据可得"
子集, 幸存者偏差 (退市票缺席 → 危机期表现乐观偏置) 不可消除 — 早期窗口
只能作**方向性外部验证**, 不得作为 regime 差异的定量授权证据。

写入: data/reports/early_window_feasibility_YYYYMMDD.{md,json}。
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

PRICE_DIR = Path("data/price_cache")
FLOW_DIR = Path("data/fund_flow_cache")
REPORT_DIR = Path("data/reports")
YEARS = ("2022", "2023", "2024")


def year_coverage(csv_paths, date_candidates=("date", "trade_date", "day")):
    """纯函数: 文件列表 → {year: set(ticker)} (ticker = 文件名 stem)。"""
    by_year: dict[str, set[str]] = defaultdict(set)
    for path in csv_paths:
        try:
            df = pd.read_csv(path, usecols=lambda c: str(c).lower() in date_candidates)
        except Exception:  # noqa: BLE001 - 坏文件按无覆盖计, 报告披露计数
            continue
        col = next((c for c in df.columns if str(c).lower() in date_candidates), None)
        if col is None or df.empty:
            continue
        for y in df[col].astype(str).str[:4].unique():
            if str(y).startswith("20"):
                by_year[str(y)].add(path.stem)
    return dict(by_year)


def intersection_universe(coverage: dict, years=YEARS) -> set[str]:
    """纯函数: 逐年覆盖的交集 (指定年份全部覆盖的票)。"""
    sets = [coverage.get(y, set()) for y in years]
    if not sets or any(not s for s in sets):
        return set()
    return set.intersection(*sets)


def limit_up_pct_for(ticker: str) -> float:
    """板块自适应涨停阈值 — 与 ashare_board_utils 语义一致 (近似版)。"""
    t = str(ticker)
    if t.startswith(("300", "301", "688", "689")):
        return 19.5
    if t.startswith(("8", "4", "92")):
        return 29.0
    return 9.5


def limit_up_days(price_dir: Path, tickers, years=YEARS) -> dict[str, int]:
    """交集宇宙内逐年涨停日数 (pct_chg 判定近似 — court 触发的原料下界)。"""
    per_year = {y: 0 for y in years}
    for t in tickers:
        path = price_dir / f"{t}.csv"
        if not path.is_file():
            continue
        try:
            df = pd.read_csv(path)
        except Exception:  # noqa: BLE001
            continue
        dcol = next((c for c in df.columns if str(c).lower() in ("date", "trade_date")), None)
        pcol = next((c for c in df.columns if "pct" in str(c).lower()), None)
        if dcol is None or pcol is None:
            continue
        yser = df[dcol].astype(str).str[:4]
        sub = df[yser.isin(per_year)]
        mask = sub[pcol].astype(float) >= limit_up_pct_for(t)
        for y in per_year:
            per_year[y] += int(((sub[dcol].astype(str).str[:4] == y) & mask).sum())
    return per_year


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--price-dir", default=str(PRICE_DIR))
    parser.add_argument("--flow-dir", default=str(FLOW_DIR))
    parser.add_argument("--report-dir", default=str(REPORT_DIR))
    args = parser.parse_args(argv)

    price_cov = year_coverage(sorted(Path(args.price_dir).glob("*.csv")))
    flow_cov = year_coverage(sorted(Path(args.flow_dir).glob("*.csv")))
    universe = intersection_universe(flow_cov) & intersection_universe(price_cov)
    density = limit_up_days(Path(args.price_dir), sorted(universe))

    payload = {
        "generated": date.today().isoformat(),
        "price_coverage": {y: len(v) for y, v in sorted(price_cov.items())},
        "flow_coverage": {y: len(v) for y, v in sorted(flow_cov.items())},
        "intersection_universe_2022_2024": len(universe),
        "limit_up_days_by_year": density,
        "verdict": (
            "技术上可行 (原料充足, btst_court_build 管道现成, 交集宇宙需注入"
            " price/fund_flow 后重建); 但部分宇宙幸存者偏差不可消除 — 仅作"
            "方向性外部验证, 不作定量授权证据"
        ),
        "caveats": [
            "交集宇宙是『历史数据可得』子集: 退市票缺席 → 危机期表现系统性乐观",
            "涨停日数是 BTST 候选原料下界 (检测器全条件过滤后 hits 是其子集)",
            "行业映射需 SW 历史成员 (2022-2024 时点), 与现快照可能不一致",
        ],
    }
    stamp = date.today().strftime("%Y%m%d")
    out = Path(args.report_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"early_window_feasibility_{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    lines = [
        f"# 2022-2024 早期 court 窗口可行性评估 ({stamp})",
        "",
        f"- price 逐年覆盖: {payload['price_coverage']}",
        f"- fund_flow 逐年覆盖: {payload['flow_coverage']}",
        f"- 交集宇宙 (双缓存 2022-24 全覆盖): **{len(universe)} 票**",
        f"- 涨停日 (原料下界): {density} (合计 {sum(density.values())})",
        f"- 结论: {payload['verdict']}",
        "",
        "### 警示",
        "",
        *[f"- {c}" for c in payload["caveats"]],
        "",
    ]
    (out / f"early_window_feasibility_{stamp}.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(f"written: {out / f'early_window_feasibility_{stamp}.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
