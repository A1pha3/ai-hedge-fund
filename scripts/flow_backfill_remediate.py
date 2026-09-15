#!/usr/bin/env python3
"""资金流缺口自愈编排 (R232 Op1) — 哨兵 detection-only 结构病的修复半环.

背景 (R232 Observe 实录): fund_flow_freshness_sentinel (2026-08-19) 只检测
不修复, 而 cache_refresh.refresh_fund_flow_cache 只拉当日、逐票刷新只覆盖最新
auto_screening 候选 (~30 只) — 停牌票掉出候选集, 复牌日资金流行无人补, 缺口
永不自愈 (近两周哨兵轮换报警: 000635/002274/002743/600929/002870, 全部停牌
复牌形态)。缺口期 BTST 条件 2 (资金流 vs 20 日均值) 用退化/失真均值判定 —
直接扭曲信号检测, 且每夜不可自愈告警训练操作员疲劳 (R229 护栏疲劳同构)。

闭环 (与哨兵/回填单一实现协作, 本脚本零数据语义):
1. scan  — 复用哨兵 scan_stale (检测口径单一来源) 得 stale/missing;
2. plan  — 纯函数 derive_backfill_plan 推导联合回填窗
           [min(flow_latest)+1 交易日 .. max(price_latest)],
           超上限类型化拒绝 (结构性缺口属人工决策, court_nightly_refresh
           「编排器绝不擅自发明窗口」纪律同构);
3. heal  — 复用 backfill_fund_flow_cache 按日全市场批量回填
           (tushare moneyflow, merge 幂等只补缺, 本体零改动);
4. prove — 复扫披露 after 残留。

missing-flow 票只报告不自动回填 (118 票级整段缺失的修复窗属人工决策,
哨兵已单列披露) — 自动修复只针对 stale (lag ≥ 哨兵阈值) 类。

用法:
    uv run python scripts/flow_backfill_remediate.py             # dry-run 零写入
    uv run python scripts/flow_backfill_remediate.py --execute   # 夜链阶段形态
退出码: 0 = ok/no-op/dry-run; 2 = 类型化拒绝 (calendar_unavailable /
plan_window_exceeds_cap / gap_record_invalid); 1 = 回填执行失败 backfill_failed。
输出: 单行 typed JSON — {"ok":…, "mode":…, "plan":…, "before":…, "after":…}
成功 / {"ok": false, "code": "…"} 失败 (research_data_refresh.typed_code 契约)。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.fund_flow_freshness_sentinel import (  # noqa: E402
    _latest_date,
    scan_stale,
)

# 哨兵阈值单一来源: 规划器只处理哨兵会告警的缺口, 不发明第二套口径。
from scripts.fund_flow_freshness_sentinel import _STALE_THRESHOLD_DAYS  # noqa: E402

_BACKFILL_SCRIPT_DEFAULT = "scripts/backfill_fund_flow_cache.py"

# 回填窗交易日数上限: 覆盖典型停牌长度 (数日~六周); 超过即结构级缺口
# (长期退市/数据源断层/大规模缺失), 自动大窗自愈只会掩盖需要人工归因的事实。
_MAX_WINDOW_TRADING_DAYS_DEFAULT = 30


@dataclass(frozen=True)
class FlowGap:
    """一只票的资金流缺口事实 (scan_stale 的 stale 行 + 双侧最新日期)。"""

    ticker: str
    flow_latest: str  # YYYYMMDD
    price_latest: str  # YYYYMMDD


@dataclass(frozen=True)
class BackfillPlan:
    """按日全市场回填窗 (tickers 只作披露; 批量接口按日取全市场)。"""

    window_start: str  # YYYYMMDD (含)
    window_end: str  # YYYYMMDD (含)
    trading_days: tuple[str, ...]  # 窗内交易日 (上限计数口径)
    tickers: tuple[str, ...]


class BackfillPlanRefused(ValueError):
    """规划器类型化拒绝; code 走 typed JSON 输出契约。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def derive_backfill_plan(
    gaps: list[FlowGap],
    tdays_sorted: list[str],
    *,
    max_window_trading_days: int = _MAX_WINDOW_TRADING_DAYS_DEFAULT,
) -> BackfillPlan | None:
    """纯规划: 缺口集 → 联合回填窗; 空集 → None (no-op); 非法/超限 → 类型化拒绝。

    窗口语义: start = 第一 trades > min(flow_latest) 的交易日 (缺口首日),
    end = max(price_latest) (价格缓存最新日)。停牌日 (交易日但无成交) 在窗内
    被回填日请求自然跳过 (无数据), 复牌日补齐后 flow_latest 追平 price_latest,
    哨兵 lag 归零 — 窗口以 flow_latest 为锚而非缺口起点, 不要求补停牌空档。
    """
    if not gaps:
        return None
    for gap in gaps:
        if (
            not gap.ticker
            or not _is_yyyymmdd(gap.flow_latest)
            or not _is_yyyymmdd(gap.price_latest)
            or gap.price_latest <= gap.flow_latest
        ):
            raise BackfillPlanRefused("gap_record_invalid")
    window_start = _first_trading_day_after(min(g.flow_latest for g in gaps), tdays_sorted)
    window_end = max(g.price_latest for g in gaps)
    if window_start is None:
        raise BackfillPlanRefused("plan_window_empty")
    window_days = tuple(d for d in tdays_sorted if window_start <= d <= window_end)
    if not window_days:
        raise BackfillPlanRefused("plan_window_empty")
    if len(window_days) > max_window_trading_days:
        raise BackfillPlanRefused("plan_window_exceeds_cap")
    return BackfillPlan(
        window_start=window_start,
        window_end=window_end,
        trading_days=window_days,
        tickers=tuple(sorted(g.ticker for g in gaps)),
    )


def _is_yyyymmdd(value: str) -> bool:
    return len(value) == 8 and value.isdigit()


def _first_trading_day_after(date_str: str, tdays_sorted: list[str]) -> str | None:
    for day in tdays_sorted:
        if day > date_str:
            return day
    return None


def _scan_world(
    price_dir: Path, flow_dir: Path, cal_path: Path
) -> tuple[list[FlowGap], list[str], int]:
    """哨兵单一实现复扫 → (stale 缺口事实集, missing 票, checked 数)。"""
    try:
        tdays = sorted(set(json.loads(cal_path.read_text(encoding="utf-8"))))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BackfillPlanRefused("calendar_unavailable") from exc
    checked, stale, missing = scan_stale(price_dir, flow_dir, set(tdays), _STALE_THRESHOLD_DAYS)
    gaps: list[FlowGap] = []
    for ticker, _lag in stale:
        gaps.append(
            FlowGap(
                ticker=ticker,
                flow_latest=_latest_date(flow_dir / f"{ticker}.csv") or "",
                price_latest=_latest_date(price_dir / f"{ticker}.csv") or "",
            )
        )
    return gaps, missing, checked


def _snapshot(gaps: list[FlowGap], missing: list[str], checked: int) -> dict:
    return {
        "stale": [[g.ticker, g.flow_latest, g.price_latest] for g in gaps],
        "missing": missing,
        "checked": checked,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="资金流缺口自愈编排 (detect→plan→heal→prove)")
    parser.add_argument("--execute", action="store_true", help="真正调用回填 (缺省 dry-run 零写入)")
    parser.add_argument(
        "--max-window-days",
        type=int,
        default=_MAX_WINDOW_TRADING_DAYS_DEFAULT,
        help=f"回填窗交易日数上限 (默认 {_MAX_WINDOW_TRADING_DAYS_DEFAULT}; 超限类型化拒绝)",
    )
    parser.add_argument("--price-dir", default=str(_PROJECT_ROOT / "data" / "price_cache"))
    parser.add_argument("--flow-dir", default=str(_PROJECT_ROOT / "data" / "fund_flow_cache"))
    parser.add_argument(
        "--calendar", default=str(_PROJECT_ROOT / "data" / "reports" / "trade_calendar.json")
    )
    parser.add_argument("--backfill-script", default=_BACKFILL_SCRIPT_DEFAULT)
    parser.add_argument("--threshold", type=int, default=_STALE_THRESHOLD_DAYS)
    args = parser.parse_args(argv)

    def emit(envelope: dict, code: int) -> int:
        print(json.dumps(envelope, ensure_ascii=False))
        return code

    try:
        gaps, missing, checked = _scan_world(Path(args.price_dir), Path(args.flow_dir), Path(args.calendar))
    except BackfillPlanRefused as exc:
        return emit({"ok": False, "code": exc.code}, 2)
    tdays_sorted = sorted(set(json.loads(Path(args.calendar).read_text(encoding="utf-8"))))
    before = _snapshot(gaps, missing, checked)

    try:
        plan = derive_backfill_plan(gaps, tdays_sorted, max_window_trading_days=args.max_window_days)
    except BackfillPlanRefused as exc:
        return emit({"ok": False, "code": exc.code, "before": before}, 2)
    if plan is None:
        return emit({"ok": True, "mode": "noop", "before": before}, 0)

    plan_view = {
        "window_start": plan.window_start,
        "window_end": plan.window_end,
        "trading_days": len(plan.trading_days),
        "tickers": list(plan.tickers),
    }
    if not args.execute:
        return emit({"ok": True, "mode": "dry_run", "plan": plan_view, "before": before}, 0)

    proc = subprocess.run(
        [
            sys.executable,
            args.backfill_script,
            "--start",
            plan.window_start,
            "--end",
            plan.window_end,
        ],
        capture_output=True,
        text=True,
        cwd=str(_PROJECT_ROOT),
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-400:]
        return emit(
            {"ok": False, "code": "backfill_failed", "backfill_rc": proc.returncode,
             "plan": plan_view, "backfill_tail": tail},
            1,
        )
    after_gaps, after_missing, after_checked = _scan_world(
        Path(args.price_dir), Path(args.flow_dir), Path(args.calendar)
    )
    return emit(
        {
            "ok": True,
            "mode": "executed",
            "plan": plan_view,
            "before": before,
            "after": _snapshot(after_gaps, after_missing, after_checked),
        },
        0,
    )


if __name__ == "__main__":
    raise SystemExit(main())
