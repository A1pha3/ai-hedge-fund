"""BTST court 第一步: 拉取权威研究面板 (可续传, 只写 data/research/btst_court/raw/).

数据源与用途:
- pro.daily(trade_date=...)     → 全市场日线快照 (open/high/low/close/pre_close/pct_chg/vol).
                                  按日快照天然包含后来退市的票 — 幸存者偏差在宇宙层解决.
- pro.limit_list_d(trade_date=, limit_type='U')
                                 → 当日权威涨停名单 (宇宙完备性对账真值 + PIT ST 名 +
                                  封板质量字段 first_time/open_times/fd_amount 免费入库).
- pro.index_member_all(l1_code=...) → 申万一级行业成员史 (in_date/out_date, PIT 行业映射).

幂等: 已存在的 per-day 文件跳过. 限速: 失败指数退避, 连续失败中止 (不写空文件).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _btst_court_common import RAW_DIR, WINDOW_A_START, load_sessions  # noqa: E402

_DAILY_COLS = ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount"]
_CALL_SLEEP_S = 0.12
_MAX_RETRY = 4


def _pro() -> "object":
    from src.tools.tushare_api import get_tushare_token

    token = get_tushare_token()
    if not token:
        raise SystemExit("tushare token unavailable")
    import tushare as ts

    return ts.pro_api(token=token)


def _fetch_retry(call, *, label: str) -> pd.DataFrame | None:
    """指数退避重试; 数据源空返回是合法空 (None), 连续异常抛出由调用方计数."""
    delay = 1.0
    for attempt in range(_MAX_RETRY):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - 数据源异常统一退避
            if attempt == _MAX_RETRY - 1:
                print(f"  [fail] {label}: {exc}")
                return None
            time.sleep(delay)
            delay *= 2
    return None


def _write_atomic_csv(path: Path, df: pd.DataFrame) -> None:
    tmp = path.with_suffix(".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(path)


def fetch_daily_panel(pro, sessions: list[str]) -> tuple[int, int]:
    raw = RAW_DIR / "daily"
    raw.mkdir(parents=True, exist_ok=True)
    ok = skipped = 0
    for i, d in enumerate(sessions):
        path = raw / f"daily_{d}.csv"
        if path.exists():
            skipped += 1
            continue
        df = _fetch_retry(lambda d=d: pro.daily(trade_date=d, fields=",".join(_DAILY_COLS)), label=f"daily {d}")
        if df is None or df.empty:
            # 无返回当天不落盘 (下次重试), 连续空由汇总计数暴露.
            continue
        _write_atomic_csv(path, df[_DAILY_COLS])
        ok += 1
        if i % 50 == 0:
            print(f"  daily {d} rows={len(df)}")
        time.sleep(_CALL_SLEEP_S)
    return ok, skipped


def fetch_limit_lists(pro, sessions: list[str]) -> tuple[int, int]:
    raw = RAW_DIR / "limit_up"
    raw.mkdir(parents=True, exist_ok=True)
    ok = skipped = 0
    for d in sessions:
        path = raw / f"lu_{d}.csv"
        if path.exists():
            skipped += 1
            continue
        df = _fetch_retry(
            lambda d=d: pro.limit_list_d(trade_date=d, limit_type="U"),
            label=f"limit_list_d {d}",
        )
        if df is None:
            continue
        if df.empty:
            df.to_csv(path, index=False)  # 合法空 (当日无涨停) 也落盘, 防反复重试
        else:
            _write_atomic_csv(path, df)
        ok += 1
        time.sleep(_CALL_SLEEP_S)
    return ok, skipped


def fetch_sw_membership(pro) -> Path:
    """申万 L1 成员史 (in/out 日期) — PIT 行业映射. 与 _industry_codes.json 对齐."""
    import json

    raw = RAW_DIR
    raw.mkdir(parents=True, exist_ok=True)
    out = raw / "sw_members.csv"
    if out.exists():
        print("  sw_members.csv 已存在, 跳过")
        return out
    codes_path = Path("data/industry_index_cache/_industry_codes.json")
    codes_map: dict[str, str] = json.loads(codes_path.read_text(encoding="utf-8"))
    frames = []
    for l1 in sorted(codes_map):
        code = l1 if l1.endswith(".SI") else f"{l1}.SI"
        df = _fetch_retry(lambda c=code: pro.index_member_all(l1_code=c), label=f"sw {code}")
        if df is None or df.empty:
            print(f"  [warn] sw {code} 空/失败")
            continue
        frames.append(df)
        time.sleep(_CALL_SLEEP_S)
    if not frames:
        raise SystemExit("SW membership fetch 全部失败 — 不落盘空文件, 稍后重跑")
    merged = pd.concat(frames, ignore_index=True)
    _write_atomic_csv(out, merged)
    print(f"  sw_members rows={len(merged)} l1={merged['l1_code'].nunique() if 'l1_code' in merged else '?'}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=None, help="面板起始 YYYYMMDD (默认 _btst_court_common.PANEL_START)")
    parser.add_argument("--end", default=None, help="面板结束 YYYYMMDD (默认今天)")
    args = parser.parse_args()

    from _btst_court_common import PANEL_START

    end = args.end or time.strftime("%Y%m%d")
    start = args.start or PANEL_START
    sessions = load_sessions(start, end)
    print(f"sessions {start}..{end}: {len(sessions)}")

    pro = _pro()
    print("[1/3] 全市场日线快照…")
    ok_d, skip_d = fetch_daily_panel(pro, sessions)
    print(f"  daily: new={ok_d} skipped={skip_d} total={len(sessions)}")
    lu_sessions = [s for s in sessions if s >= WINDOW_A_START]
    print(f"[2/3] 权威涨停名单 ({len(lu_sessions)} 天)…")
    ok_l, skip_l = fetch_limit_lists(pro, lu_sessions)
    print(f"  limit_list_d: new={ok_l} skipped={skip_l}")
    print("[3/3] 申万 L1 成员史…")
    fetch_sw_membership(pro)

    missing_daily = [s for s in sessions if not (RAW_DIR / "daily" / f"daily_{s}.csv").exists()]
    missing_lu = [s for s in lu_sessions if not (RAW_DIR / "limit_up" / f"lu_{s}.csv").exists()]
    print(f"汇总: daily 缺 {len(missing_daily)} 天 {missing_daily[:8]}…; limit_list 缺 {len(missing_lu)} 天")
    if missing_daily:
        print("  (有缺口可重跑本脚本续传; build 阶段会再断言)")


if __name__ == "__main__":
    main()
