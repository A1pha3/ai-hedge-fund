#!/usr/bin/env python3
"""龙虎榜日更续传 (R58 数据新鲜度工作线).

补齐 data/lhb_cache/ 从最新缓存会话到期望会话的缺口:
``pro.top_inst(trade_date=d)`` → ``YYYYMMDD.csv`` (复用 backtest_phase_b 的
缓存形状: trade_date,ts_code,exalter,buy,buy_rate,sell,sell_rate,net_buy,side,reason)。

与旧写入方 (_ensure_lhb_backfill) 的两点纪律分歧:
- 旧实现 ``except: pass`` 静默吞错 → lhb 自 2026-07-07 静默死亡 53 天无人知。
  本实现任何 API/IO 失败类型化退出 (rc=1, JSON ``{"ok": false, "code": ...}}``),
  绝不静默。
- 空返回日落**表头空文件**标记"已尝试" — 否则永久无榜日会让续传窗口每次都
  从同一位置重试, 永远追不上日历 (新鲜度仪表以文件覆盖度为新鲜信号)。

幂等: 已存在的日文件零 API 调用跳过。限速: 相邻调用间 rate_sleep 秒。

用法 (uv run, 仓库根):
    uv run python scripts/fetch_lhb_daily.py
注入面: run_fetch() 的 fetch_fn 参数供 hermetic 测试 (零网络)。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = REPO_ROOT / "data" / "lhb_cache"
DEFAULT_CALENDAR = REPO_ROOT / "data" / "reports" / "trade_calendar.json"

LHB_COLUMNS = [
    "trade_date", "ts_code", "exalter", "buy", "buy_rate",
    "sell", "sell_rate", "net_buy", "side", "reason",
]


class LhbFetchError(RuntimeError):
    """类型化失败: code + 详情, CLI 转成 JSON + rc=1 (绝不静默吞)。"""

    def __init__(self, code: str, details: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


def load_calendar_sessions(calendar_path: Path) -> list[str]:
    """权威交易日历 → 排序会话列表 (YYYYMMDD 字符串)。缺失/畸形类型化拒绝。"""
    try:
        raw = json.loads(calendar_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LhbFetchError("calendar_not_found", {"path": str(calendar_path)}) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LhbFetchError("calendar_unreadable", {"path": str(calendar_path)}) from exc
    if not isinstance(raw, list) or not raw or not all(
        isinstance(x, str) and len(x) == 8 and x.isdigit() for x in raw
    ):
        raise LhbFetchError("calendar_malformed", {"path": str(calendar_path)})
    return sorted(raw)


def expected_session(calendar_path: Path, today: str) -> str:
    """期望会话 = **今日之前的最近已完成交易日** (T-1 语义, 严格 < today)。

    拉取面与仪表共用此语义: 研究保证是「今晨睁眼有 T-1 数据」; 且续传只碰
    已完结会话 — 当日 18:30 时 tushare 可能尚未发布今日榜, 若把今日当期望,
    空返回会误落表头空文件 (已尝试标记), 数据晚到后该日被幂等跳过, 永久缺失。
    """
    sessions = load_calendar_sessions(calendar_path)
    covered = [s for s in sessions if s < today]
    if not covered:
        raise LhbFetchError("no_session_before_today", {"today": today})
    expected = covered[-1]
    if sessions[-1] < today:
        # R57 同款语义: 日历过期 = 分类不可信 = 运维缺口, 响亮而非降级
        raise LhbFetchError(
            "calendar_stale", {"calendar_max": sessions[-1], "today": today}
        )
    return expected


def _cached_sessions(cache_dir: Path) -> set[str]:
    return {
        p.stem for p in cache_dir.glob("*.csv")
        if len(p.stem) == 8 and p.stem.isdigit()
    }


def run_fetch(
    *,
    cache_dir: Path,
    calendar_path: Path,
    today: str,
    fetch_fn,
    rate_sleep: float = 0.2,
    start: str | None = None,
) -> dict:
    """续传主循环。fetch_fn(trade_date) -> DataFrame | None (hermetic 注入点)。

    start: 有界回补窗起点 (含) — 只补 [start, expected] 的缺口;
    None (默认) = 从最新缓存之后追平 (日更语义)。研究回补历史时用。
    返回摘要 dict; 失败抛 LhbFetchError (类型化, CLI 层转 JSON)。
    """
    if not (len(today) == 8 and today.isdigit()):
        raise LhbFetchError("invalid_today", {"today": today})
    if start is not None and not (len(start) == 8 and start.isdigit()):
        raise LhbFetchError("invalid_start", {"start": start})
    expected = expected_session(calendar_path, today)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = _cached_sessions(cache_dir)
    sessions = load_calendar_sessions(calendar_path)
    if start is None:
        # 日更追平语义 (R58): 从最新缓存之后到期望会话
        missing = [s for s in sessions if expected >= s > max(cached, default="")]
    else:
        # 有界回补窗 (R61): [start, expected] 内所有未缓存会话 —
        # 缓存最晚位置无关 (回补既有缓存之前的历史正是本语义的存在理由)
        missing = [s for s in sessions
                   if start <= s <= expected and s not in cached]
    fetched, empty_days = [], []
    for session in missing:
        try:
            frame = fetch_fn(session)
        except LhbFetchError:
            raise
        except Exception as exc:  # API/网络/限速故障: 类型化, 绝不静默
            raise LhbFetchError(
                "lhb_api_failed", {"session": session, "error": str(exc)[:200]}
            ) from exc
        target = cache_dir / f"{session}.csv"
        if frame is None or len(frame) == 0:
            # 空返回日: 落表头空文件标记已尝试, 续传窗口得以越过它
            pd.DataFrame(columns=LHB_COLUMNS).to_csv(target, index=False)
            empty_days.append(session)
        else:
            frame.to_csv(target, index=False)
            fetched.append(session)
        if rate_sleep > 0:
            time.sleep(rate_sleep)
    return {
        "expected_session": expected,
        "already_cached": max(cached, default="") ,
        "fetched": fetched,
        "empty_days": empty_days,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--calendar", default=str(DEFAULT_CALENDAR))
    parser.add_argument(
        "--today", default=time.strftime("%Y%m%d"),
        help="期望会话锚点 (YYYYMMDD, 默认今天; hermetic 注入)",
    )
    parser.add_argument("--rate-sleep", type=float, default=0.2)
    parser.add_argument("--start", default=None,
                        help="有界回补窗起点 (YYYYMMDD, 含); 默认从最新缓存追平")
    args = parser.parse_args()

    from src.tools.tushare_api import _get_pro

    pro = _get_pro()
    try:
        summary = run_fetch(
            cache_dir=Path(args.cache_dir),
            calendar_path=Path(args.calendar),
            today=args.today,
            fetch_fn=lambda d: pro.top_inst(trade_date=d),
            rate_sleep=args.rate_sleep,
            start=args.start,
        )
    except LhbFetchError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "details": exc.details},
                         ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
