#!/usr/bin/env python3
"""fund_flow 缓存新鲜度哨点 (advisory, 2026-08-19).

背景 (对抗性复核): 2026-07-13 ~ 08-13 有 118 只 universe 票的资金流缓存整段
缺失而价格缓存同期完整 — 资金流逐票/预取链路对该子集持续失败, 且
cache_refresh.refresh_fund_flow_cache 只拉当日、从不回填, 缺口不会自愈.
缺口期 BTST 条件 2 用退化均值判定 (实例: 300684 8/13 被失真均值判 BLOCK,
补齐后应为 PASS), 全程无任何告警面.

设计 (与 court_asset_sentinel 同族):
- 只读诊断: 比较 universe (price_cache) 每只票的 fund_flow 最新日期 vs 价格
  最新日期; fund_flow 落后 ≥ _STALE_THRESHOLD_DAYS 个交易日 = stale.
- 永不影响管道 rc (由 run_daily_pipeline._run_advisory_sentinels 兜底捕获).
- 修复指引输出到 stdout, 由 pipeline log 留痕: scripts/backfill_fund_flow_cache.py
  --start <缺口起> --end <缺口止> (tushare moneyflow 批量, 与 akshare 逐分一致).
- 哨点自身故障 → 非零 rc, 由调用方忽略 (advisory 语义).

用法:
    uv run python scripts/fund_flow_freshness_sentinel.py
退出码: 0 = 健康或有 stale 但仅告警; 1 = 哨点自身故障 (读不到缓存等).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRICE_DIR = REPO / "data" / "price_cache"
FLOW_DIR = REPO / "data" / "fund_flow_cache"
CAL_PATH = REPO / "data" / "reports" / "trade_calendar.json"
# 落后 ≥2 个交易日即告警: 每日刷新正常时落后 0 (当日) 或 1 (非交易日/未开市).
_STALE_THRESHOLD_DAYS = 2
# 避免千票刷屏: 明细最多列 N 只, 其余只报计数.
_MAX_LISTED = 20


def _trading_days() -> set[str]:
    cal = json.loads(CAL_PATH.read_text(encoding="utf-8"))
    return {str(d) for d in cal}


def _latest_date(csv_path: Path) -> str | None:
    """该票缓存最后一行的日期 (YYYYMMDD). 文件不存在/空 → None."""
    try:
        last = ""
        with open(csv_path, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i == 0:  # header
                    continue
                if line.strip():
                    last = line
        if not last:
            return None
        return last.split(",")[0][:10].replace("-", "")
    except OSError:
        return None


def main() -> int:
    if not PRICE_DIR.exists() or not CAL_PATH.exists():
        print("[fund_flow_sentinel] price_cache 或 trade_calendar 缺失, 哨点无法运行")
        return 1
    tdays = _trading_days()

    stale: list[tuple[str, int]] = []  # (ticker, 落后交易日数)
    missing: list[str] = []
    checked = 0
    for p in sorted(PRICE_DIR.glob("*.csv")):
        ticker = p.stem
        price_latest = _latest_date(p)
        if price_latest is None:
            continue
        checked += 1
        flow_latest = _latest_date(FLOW_DIR / f"{ticker}.csv")
        if flow_latest is None:
            missing.append(ticker)
            continue
        if flow_latest >= price_latest:
            continue
        # 落后交易日数 = (flow_latest, price_latest] 内的交易日个数
        lag = sum(1 for d in tdays if flow_latest < d <= price_latest)
        if lag >= _STALE_THRESHOLD_DAYS:
            stale.append((ticker, lag))

    if not stale and not missing:
        print(f"[fund_flow_sentinel] OK: {checked} 只 universe 票资金流缓存均新鲜")
        return 0

    if missing:
        print(f"[fund_flow_sentinel] ⚠ {len(missing)} 只票完全无资金流缓存"
              f" (样例: {', '.join(missing[:_MAX_LISTED])})")
    if stale:
        stale.sort(key=lambda x: -x[1])
        print(f"[fund_flow_sentinel] ⚠ {len(stale)} 只票资金流落后价格缓存 ≥{_STALE_THRESHOLD_DAYS} 个交易日:")
        for ticker, lag in stale[:_MAX_LISTED]:
            print(f"    {ticker}: 落后 {lag} 个交易日")
        if len(stale) > _MAX_LISTED:
            print(f"    ... 其余 {len(stale) - _MAX_LISTED} 只略")
        print("  修复: uv run python scripts/backfill_fund_flow_cache.py "
              "--start <最早落后段起点> --end <昨日> (tushare 批量, 只补缺不覆盖)")
        print("  影响: 缺口期 BTST 条件 2 用退化/失真均值判定; 补齐后历史判定需重放复核")
    return 0


if __name__ == "__main__":
    sys.exit(main())
