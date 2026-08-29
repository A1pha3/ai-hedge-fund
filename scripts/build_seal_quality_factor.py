#!/usr/bin/env python3
"""封板质量复合因子 (R65, 候选 #4; 预注册单一规格).

结构假设: 封板质量 = 涨停需求的真实性 (盘口微观结构), 与强度因子 (涨幅幅度)
机制独立。

预注册规格 (**单一规格, 三腿方向声明, 零自由参数** — 等权秩平均, 改腿/改权
= 新候选重注册):
    factor(D, 票) = mean( rank_pct(−first_time),      # 首封越早 秩越高
                          rank_pct(−open_times),       # 炸板越少 秩越高
                          rank_pct(+fd_amount) )       # 封单越大 秩越高
秩基 = **当日全市场涨停板** (lu_D 快照内横截面), 非跨日。单腿缺失取可得腿
均值; 三腿全缺 → 无行并计数 (不冒充中性值)。

PIT (R64 语义): 三腿皆为 D 日 15:00 前盘中事实, 快照晚间发布 — 早于决策截断
(当日 23:00 北京), 合法入窗; 只读 signal_date=D 的当日快照, 无跨日信息。

数据源: data/research/btst_court/raw/limit_up/lu_YYYYMMDD.csv (宇宙 = 权威
涨停名单, 故对候选覆盖 ~100%)。

用法 (uv run, 仓库根):
  uv run python scripts/build_seal_quality_factor.py \
      --start 20250702 --end 20260818 \
      --out data/research/btst_court/factors/seal_quality_v0.csv
"""

from __future__ import annotations

import argparse
import json
import sys
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
DEFAULT_LU_DIR = REPO_ROOT / "data/research/btst_court/raw/limit_up"
DEFAULT_CALENDAR = REPO_ROOT / "data/reports/trade_calendar.json"


class SealFactorError(RuntimeError):
    def __init__(self, code: str, details: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


def _typed(code: str, details: dict | None = None):
    raise SealFactorError(code, details)


REQUIRED_COLS = ("first_time", "open_times", "fd_amount")


def _day_legs(path: Path) -> pd.DataFrame | None:
    """单日快照 → 三腿数值列 (方向变换后); 缺文件 None。"""
    if not path.is_file():
        return None
    frame = pd.read_csv(path, dtype={"ts_code": str})
    for col in REQUIRED_COLS:
        if col not in frame.columns:
            _typed("lu_snapshot_missing_columns",
                   {"path": str(path), "missing": [col]})
    out = pd.DataFrame({"ts_code": frame["ts_code"].astype(str)})
    out["first_time"] = pd.to_numeric(frame["first_time"], errors="coerce")
    out["open_times"] = pd.to_numeric(frame["open_times"], errors="coerce")
    out["fd_amount"] = pd.to_numeric(frame["fd_amount"], errors="coerce")
    return out


def build_factor(
    *,
    lu_dir: Path,
    calendar_path: Path,
    start: str,
    end: str,
) -> tuple[pd.DataFrame, dict]:
    sessions = load_calendar_sessions(calendar_path)
    if not (len(start) == 8 and start.isdigit() and len(end) == 8 and end.isdigit()):
        _typed("invalid_date_args", {"start": start, "end": end})
    if start > end:
        _typed("invalid_date_args", {"start": start, "end": end})
    if sessions[-1] < end:
        _typed("calendar_stale", {"calendar_max": sessions[-1], "end": end})
    in_range = [s for s in sessions if start <= s <= end]
    if not in_range:
        _typed("no_sessions_in_range", {"start": start, "end": end})

    rows: list[dict] = []
    missing_files = 0
    all_legs_missing = 0
    for day in in_range:
        legs = _day_legs(lu_dir / f"lu_{day}.csv")
        if legs is None:
            missing_files += 1
            continue
        # 方向变换后的秩 (当日横截面): first_time 越小(越早)越好 → rank(−first_time);
        # open_times 越小(炸板少)越好 → rank(−open_times);
        # fd_amount 越大越好 → rank(+fd_amount) 原值秩即大者高
        ranks = pd.DataFrame({
            "r_first": (-legs["first_time"]).rank(pct=True),
            "r_open": (-legs["open_times"]).rank(pct=True),
            "r_fd": legs["fd_amount"].rank(pct=True),
        })
        valid = ranks.notna().sum(axis=1)
        mean_rank = ranks.mean(axis=1)          # NaN 腿自动排除 (pandas mean)
        for ts_code, value, n_valid in zip(legs["ts_code"], mean_rank, valid):
            if n_valid == 0:
                all_legs_missing += 1
                continue
            rows.append({
                "signal_date": day,
                "ts_code": ts_code,
                "factor": float(value),
            })
    factor = pd.DataFrame(rows, columns=["signal_date", "ts_code", "factor"])
    summary = {
        "days_requested": len(in_range),
        "missing_files": missing_files,
        "all_legs_missing_rows": all_legs_missing,
        "factor_rows": int(len(factor)),
    }
    return factor, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lu-dir", default=str(DEFAULT_LU_DIR))
    parser.add_argument("--calendar", default=str(DEFAULT_CALENDAR))
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    try:
        factor, summary = build_factor(
            lu_dir=Path(args.lu_dir), calendar_path=Path(args.calendar),
            start=args.start, end=args.end)
    except (LhbFetchError, SealFactorError) as exc:
        code = getattr(exc, "code", "seal_factor_failed")
        details = getattr(exc, "details", {})
        print(json.dumps({"ok": False, "code": code, "details": details},
                         ensure_ascii=False), file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    factor.to_csv(out, index=False)
    print(json.dumps({"ok": True, **summary, "out": str(out)},
                     ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
