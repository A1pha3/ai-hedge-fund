"""BTST 条件级重放分歧 — 生产 paper BUY 在今日 court 输入下的 detect 归因.

第一性原理: Op1 (realized_vs_court) 证明 14/18 生产信号在 court 宇宙之外,
但「为什么之外」才是胜率证据的关键 — 本工具对每笔生产 BUY 用**今日** court
输入 (raw 面板帧 + 资金流缓存 + 行业指数缓存 + 今日 regime 标签) 重放生产
detect 类, 把分歧归因到条件级, 并按「今日体系会怎样」分桶对照 realized:

  regime_blocked     当日 regime ∈ {crisis, risk_off} — 今日 gate 会阻断
  detect_miss_today  detect 重放 miss (miss_stage 细分: c1/c2/c3/c4)
  would_fire_today   hit ∧ court_strength ≥ 0.50 — 今日体系仍会开仓

机制注记 (Observe 期实证): 行业指数缓存 2026-09-01 起 index_daily→sw_daily
换源 (commit ba5b8447) 重写过历史; sw_daily 官方 pct_change 仅 2 位小数,
c3 门 (_INDUSTRY_PCT_MIN=2%) 在阈值附近对数据源舍入脆弱 — 生产当时值与
court 重建值可翻转。资金流缓存同理为时变数据。本工具测的是「今日数据下
的今日体系」, 与生产当时决策的差 = 数据/gate/公式演化的合计效果。

纪律 (先于数据写死):
  - 纯诊断 (宪法 #2): 任何据此的生产参数变化 = 新证据世代 owner 决策。
  - detect 通过 import 生产类复用 (绝不复制公式) — 与 court build 同源。
  - 分桶只用信号日事实 (regime 标签 + detect 结果), 绝不用事后价格分桶;
    realized 仅作为桶内对照量。
  - 确定性: 同输入逐字节同输出 (无 RNG)。

用法:
    uv run python scripts/btst_condition_replay.py
    uv run python scripts/btst_condition_replay.py --output-json PATH --output-md PATH
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup

JOURNAL_PATH = Path("data/paper_trading/journal.jsonl")
REGIME_PATH = Path("data/reports/regime_history.json")
RAW_DIR = Path("data/research/btst_court/raw")
REPORTS_DIR = Path("data/reports")

REGIME_BLOCK_LABELS = {"crisis", "risk_off"}
PRODUCTION_MIN_STRENGTH = 0.50
BUCKETS = ("regime_blocked", "detect_miss_today", "would_fire_today")

_REALIZED_RE = re.compile(r"realized=([+-]?\d+(?:\.\d+)?)%")


@dataclass(frozen=True)
class ReplayResult:
    """一笔 BUY 的今日输入重放结果."""

    signal_date: str
    ticker: str
    horizon: int
    regime: str
    hit: bool
    miss_stage: str | None
    court_strength: float
    industry_name: str | None
    industry_pct: float | None
    bucket: str
    realized_pct: float | None


def normalize_day(value: object) -> str:
    text = str(value).replace("-", "").strip()
    if len(text) == 8 and text.isdigit():
        return text
    raise ValueError(f"unparseable trade date: {value!r}")


def assign_bucket(regime: str, hit: bool, strength: float) -> tuple[str, str | None]:
    """信号日事实 → 三桶之一 (优先级: regime > detect > strength). 返回 (bucket, miss_stage 覆写)."""
    if regime in REGIME_BLOCK_LABELS:
        return "regime_blocked", None
    if not hit:
        return "detect_miss_today", None
    if strength < PRODUCTION_MIN_STRENGTH:
        return "detect_miss_today", "strength_below_threshold"
    return "would_fire_today", None


def replay_one(
    ticker: str,
    signal_date: str,
    *,
    prices: pd.DataFrame,
    fund_flow_records: Sequence[Any],
    industry_name: str | None,
    industry_pct: float | None,
    regime: str,
    horizon: int = 10,
) -> ReplayResult:
    """单笔重放: 生产 detect 类 + 今日上下文 → 三桶之一."""
    setup = BtstBreakoutSetup()
    result = setup.detect(
        ticker,
        signal_date,
        {
            "prices": prices,
            "fund_flow_records": list(fund_flow_records),
            "industry_day_pct": industry_pct,
            "regime": regime,
        },
    )
    hit = bool(getattr(result, "hit", False))
    miss_stage = getattr(result, "miss_stage", None)
    strength = float(getattr(result, "trigger_strength", 0.0) or 0.0)
    bucket, override = assign_bucket(regime, hit, strength)
    if override and not miss_stage:
        miss_stage = override
    return ReplayResult(
        signal_date=signal_date,
        ticker=ticker,
        horizon=horizon,
        regime=regime,
        hit=hit,
        miss_stage=str(miss_stage) if miss_stage else None,
        court_strength=strength,
        industry_name=industry_name,
        industry_pct=industry_pct,
        bucket=bucket,
        realized_pct=None,
    )


def realized_map_from_journal(journal: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], float]:
    mapping: dict[tuple[str, str], float] = {}
    for record in journal:
        if str(record.get("action") or "").upper() != "EXIT":
            continue
        match = _REALIZED_RE.search(str(record.get("reasoning") or ""))
        if match is None:
            continue
        mapping[(normalize_day(record.get("date")), str(record.get("ticker") or ""))] = float(
            match.group(1)
        )
    return mapping


def attach_realized(results: Sequence[ReplayResult], realized: Mapping[tuple[str, str], float]) -> list[ReplayResult]:
    return [
        ReplayResult(**{**r.__dict__, "realized_pct": realized.get((r.signal_date, r.ticker))})
        for r in results
    ]


def bucket_stats(results: Sequence[ReplayResult]) -> dict[str, Any]:
    """三桶 realized 对照 (只按信号日事实分桶, realized 是对照量)."""
    payload: dict[str, Any] = {}
    for bucket in BUCKETS:
        rows = [r for r in results if r.bucket == bucket]
        values = [r.realized_pct for r in rows if r.realized_pct is not None]
        wins = [v for v in values if v > 0]
        losses = [v for v in values if v <= 0]
        avg_win = sum(wins) / len(wins) if wins else None
        avg_loss = sum(losses) / len(losses) if losses else None
        payload[bucket] = {
            "n_buys": len(rows),
            "n_realized": len(values),
            "win_rate_pct": round(100.0 * len(wins) / len(values), 2) if values else None,
            "avg_win_pct": round(avg_win, 2) if avg_win is not None else None,
            "avg_loss_pct": round(avg_loss, 2) if avg_loss is not None else None,
            "expectancy_pct": round(sum(values) / len(values), 2) if values else None,
        }
    miss_stages: dict[str, int] = {}
    for r in results:
        if r.bucket == "detect_miss_today" and r.miss_stage:
            miss_stages[r.miss_stage] = miss_stages.get(r.miss_stage, 0) + 1
    payload["detect_miss_stages"] = dict(sorted(miss_stages.items()))
    return payload


def render_md(payload: Mapping[str, Any]) -> str:
    lines = [
        "# BTST 条件级重放分歧 (今日 court 输入 vs 生产 paper journal)",
        "",
        "纯诊断 (宪法 #2)。分桶只用信号日事实 (regime 标签 + 今日输入 detect 结果),",
        "realized 仅作桶内对照 — 绝不用事后价格分桶。",
        "",
        "| 桶 | n_buys | n_realized | 胜率% | avg_win% | avg_loss% | E% |",
        "|---|---|---|---|---|---|---|",
    ]
    for bucket in BUCKETS:
        s = payload["buckets"][bucket]
        lines.append(
            f"| {bucket} | {s['n_buys']} | {s['n_realized']} | {s['win_rate_pct']} "
            f"| {s['avg_win_pct']} | {s['avg_loss_pct']} | {s['expectancy_pct']} |"
        )
    stages = payload["buckets"].get("detect_miss_stages") or {}
    if stages:
        lines += ["", "## detect miss 归因 (今日输入)", "", "| stage | 笔数 |", "|---|---|"]
        for stage, count in stages.items():
            lines.append(f"| {stage} | {count} |")
    lines += ["", "## 逐笔明细", ""]
    lines.append("| 信号日 | 票 | regime | 桶 | miss_stage | court强度 | 行业 | 行业% | realized% |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in payload["records"]:
        lines.append(
            f"| {r['signal_date']} | {r['ticker']} | {r['regime']} | {r['bucket']} "
            f"| {r['miss_stage'] or '—'} | {r['court_strength']:.3f} "
            f"| {r['industry_name'] or '—'} | {r['industry_pct'] if r['industry_pct'] is not None else '—'} "
            f"| {r['realized_pct'] if r['realized_pct'] is not None else '—'} |"
        )
    lines += [
        "",
        "## 纪律",
        "",
        "- 纯诊断 (宪法 #2): 胜率/赔率不替代组合路径证据; 任何参数变化 = 新证据世代 owner 决策",
        "- detect 通过 import 生产类复用 (与 court build 同源, 公式指纹可对照)",
        "- 行业指数缓存 2026-09-01 起 index_daily→sw_daily 换源重写历史; sw_daily pct_change 仅 2 位小数,",
        "  c3 门 (≥2%) 在阈值附近对数据源舍入脆弱 — 「今日值 vs 当时值」的翻转是本工具测得的差异的一部分",
        "",
    ]
    return "\n".join(lines)


def _load_journal(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            payload = json.loads(line)
            if isinstance(payload, dict):
                records.append(payload)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--journal", type=Path, default=JOURNAL_PATH)
    parser.add_argument("--regime", type=Path, default=REGIME_PATH)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    args = parser.parse_args(argv)

    import sys

    sys.path.insert(0, "scripts")
    from btst_court_build import industry_of, load_panel, load_sw_industry, ticker_frame
    from setup_research import load_industry_day_pct

    from src.screening.offensive.data.fund_flow_store import FundFlowStore

    journal = _load_journal(args.journal)
    regime_labels = {
        normalize_day(k): str(v)
        for k, v in json.loads(args.regime.read_text(encoding="utf-8")).items()
    }

    panel = load_panel(args.raw_dir)
    groups = {c: df for c, df in panel.groupby("ts_code")}
    sw = load_sw_industry(args.raw_dir)
    sw_rows: dict[str, list] = {}
    for row in sw.itertuples(index=False):
        sw_rows.setdefault(row[0], []).append((row[1], row[2], row[3]))
    industry_day_pct = load_industry_day_pct()
    flow_store = FundFlowStore(cache_dir="data/fund_flow_cache/")

    realized = realized_map_from_journal(journal)
    seen: set[tuple[str, str]] = set()
    results: list[ReplayResult] = []
    for record in journal:
        if str(record.get("action") or "").upper() != "BUY":
            continue
        signal_date = normalize_day(record.get("date"))
        ticker = str(record.get("ticker") or "")
        key = (signal_date, ticker)
        if key in seen:
            continue
        seen.add(key)
        regime = regime_labels.get(signal_date, "unknown")
        ts_code = next((c for c in groups if c.startswith(ticker + ".")), None)
        if ts_code is None:
            continue  # 面板无此票 — 记录进 miss 明细意义有限, 跳过并计数
        frame = ticker_frame(groups[ts_code], signal_date)
        flows = flow_store.get_range(ticker, "20200101", "20991231")
        ind_name = industry_of(sw_rows, ticker, signal_date)
        ind_pct = industry_day_pct.get((ind_name, signal_date)) if ind_name else None
        results.append(
            replay_one(
                ticker,
                signal_date,
                prices=frame,
                fund_flow_records=flows,
                industry_name=ind_name,
                industry_pct=ind_pct,
                regime=regime,
                horizon=int(record.get("horizon") or 10),
            )
        )

    results = attach_realized(results, realized)
    payload = {
        "buckets": bucket_stats(results),
        "records": [r.__dict__ for r in results],
        "discipline": [
            "纯诊断 (宪法 #2); 分桶只用信号日事实",
            "detect 与 court build 同源 (import 生产类)",
            "行业数据源换源 (sw_daily, 2位小数) 的阈值脆弱性已披露",
        ],
    }
    from datetime import date

    stamp = date.today().strftime("%Y%m%d")
    out_json = args.output_json or (REPORTS_DIR / f"condition_replay_divergence_{stamp}.json")
    out_md = args.output_md or (REPORTS_DIR / f"condition_replay_divergence_{stamp}.md")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    out_md.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps(payload["buckets"], ensure_ascii=False)[:800])
    print(f"written: {out_json} / {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
