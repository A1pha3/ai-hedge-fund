#!/usr/bin/env python3
"""龙虎榜机构席位质量因子 (R60, owner 数据效率工作线④).

定义: 因子(D) = 窗口内该票机构席位金额加权净买比的均值 —
窗口默认**止于 D 当日** (R64 纠错: 合约 T0 收盘后决策 18:06/23:05, 决策
截断 = 当日 23:00 北京; 当日榜 ~18:00 发布故合法可用; `--window-end prior`
保留旧 T-1 保守变体) —
    daily_ratio(t) = (Σbuy(t) − Σsell(t)) / (Σbuy(t) + Σsell(t))
    factor(D) = Σ_t w(t)·daily_ratio(t) / Σ_t w(t),  w(t) = Σbuy(t)+Σsell(t)
窗口 = 权威日历中严格 < D 的最近 3 个会话; 窗口内 ≥1 次上榜即有值,
否则 NaN (如实计数, 绝不静默当 0 — 无信息与中性信息是两回事)。

**PIT 生死线**: court 是 T0 收盘决策, D 日榜 D 日晚间才发布 — 因子在 D
只消费 < D 的榜单。用当日榜 = 未来函数, 全部回测结论作废 (测试钉死)。

输出: factor csv (signal_date,ts_code,factor) — 直接喂
scripts/factor_factory_eval.py --factor-csv; stderr 摘要 (窗口缺文件数/
上榜覆盖行数) 如实披露。

用法 (uv run, 仓库根):
  uv run python scripts/build_lhb_seat_factor.py \
      --start 20250702 --end 20260818 --out factor_lhb_seat.csv
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from fetch_lhb_daily import (  # noqa: E402
    LhbFetchError,
    load_calendar_sessions,
)

REPO_ROOT = _SCRIPTS.parent
DEFAULT_LHB_DIR = REPO_ROOT / "data" / "lhb_cache"
DEFAULT_CALENDAR = REPO_ROOT / "data" / "reports" / "trade_calendar.json"
WINDOW = 3


class LhbFactorError(RuntimeError):
    def __init__(self, code: str, details: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


def _typed(code: str, details: dict | None = None):
    raise LhbFactorError(code, details)


def _day_ratios(lhb_dir: Path, session: str) -> dict[str, tuple[float, float]]:
    """单日榜 → {ts_code: (金额加权净买比, 总金额)}。缺文件返回 {}。"""
    path = lhb_dir / f"{session}.csv"
    if not path.is_file():
        return {}
    frame = pd.read_csv(path, dtype={"ts_code": str})
    if frame.empty:
        return {}
    buy = frame.groupby("ts_code")["buy"].sum()
    sell = frame.groupby("ts_code")["sell"].sum()
    denom = buy + sell
    out: dict[str, tuple[float, float]] = {}
    for code in denom.index:
        d = float(denom[code])
        if d > 0:
            out[str(code)] = ((float(buy[code]) - float(sell[code])) / d, d)
    return out


def build_factor(
    *,
    lhb_dir: Path,
    calendar_path: Path,
    start: str,
    end: str,
    window: int = WINDOW,
    window_end: str = "day",
) -> tuple[pd.DataFrame, dict]:
    """返回 (因子帧 signal_date/ts_code/factor, 摘要 dict)。

    window_end: "day" (默认, R64 纠错) — 窗口止于 D 当日 (含): 合约 T0 收盘后
    决策 (18:06/23:05), 当日榜 ~18:00 发布, 早于决策截断 23:00 北京, 合法可用;
    "prior" — 旧 T-1 语义 (严格 <D), 保守变体保留供对照。
    """
    if window_end not in ("day", "prior"):
        _typed("invalid_window_end", {"window_end": window_end})
    sessions = load_calendar_sessions(calendar_path)
    if not (len(start) == 8 and start.isdigit() and len(end) == 8 and end.isdigit()):
        _typed("invalid_date_args", {"start": start, "end": end})
    if start > end:
        _typed("invalid_date_args", {"start": start, "end": end})
    if sessions[-1] < end:
        # 与 fetch/仪表同语义: 日历过期 = 分类不可信, 响亮 (先于空范围检查)
        _typed("calendar_stale", {"calendar_max": sessions[-1], "end": end})
    in_range = [s for s in sessions if start <= s <= end]
    if not in_range:
        _typed("no_sessions_in_range", {"start": start, "end": end})

    rows: list[dict] = []
    missing_window_files = 0
    for idx, day in enumerate(in_range):
        pos = sessions.index(day)
        if window_end == "day":
            window_sessions = sessions[max(0, pos - window + 1):pos + 1]
        else:
            window_sessions = sessions[max(0, pos - window):pos]
            window_sessions = [s for s in window_sessions if s < day]
        per_day: dict[str, list[tuple[float, float]]] = {}
        for s in window_sessions:
            if not (lhb_dir / f"{s}.csv").is_file():
                missing_window_files += 1
                continue
            for code, (ratio, weight) in _day_ratios(lhb_dir, s).items():
                per_day.setdefault(code, []).append((ratio, weight))
        for code, pairs in per_day.items():
            wsum = sum(w for _, w in pairs)
            if wsum <= 0:
                continue
            rows.append({
                "signal_date": day,
                "ts_code": code,
                "factor": sum(r * w for r, w in pairs) / wsum,
            })
    factor = pd.DataFrame(rows, columns=["signal_date", "ts_code", "factor"])
    summary = {
        "signal_days_requested": len(in_range),
        "signal_days_with_factor": int(factor["signal_date"].nunique()),
        "factor_rows": int(len(factor)),
        "window": window,
        "missing_window_files": missing_window_files,
    }
    return factor, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lhb-dir", default=str(DEFAULT_LHB_DIR))
    parser.add_argument("--calendar", default=str(DEFAULT_CALENDAR))
    parser.add_argument("--start", required=True, help="信号日起 (YYYYMMDD, 含)")
    parser.add_argument("--end", default=time.strftime("%Y%m%d"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--window", type=int, default=WINDOW)
    parser.add_argument("--window-end", default="day", choices=["day", "prior"],
                        help="day=窗口含信号日当日榜 (决策截断语义, 默认); "
                             "prior=旧 T-1 保守变体")
    args = parser.parse_args()

    try:
        factor, summary = build_factor(
            lhb_dir=Path(args.lhb_dir), calendar_path=Path(args.calendar),
            start=args.start, end=args.end, window=args.window,
            window_end=args.window_end)
    except LhbFetchError as exc:  # 日历错误复用 fetcher 的类型化码
        print(json.dumps({"ok": False, "code": exc.code, "details": exc.details},
                         ensure_ascii=False), file=sys.stderr)
        return 1
    except LhbFactorError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "details": exc.details},
                         ensure_ascii=False), file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    factor.to_csv(out, index=False)
    summary["out"] = str(out)
    print(json.dumps({"ok": True, **summary}, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
