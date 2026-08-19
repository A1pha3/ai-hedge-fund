"""OB (OversoldBounce) court 复核第一步: 全候选不可变事件表 (2026-08-19).

目的: OB 默认暂停的依据是 journal 成交子集执行口径 (E=-2.15%/wr=39%, n=56)
— trap 19 已证明成交子集受回测资金/排队状态条件化, 存在选择偏差。本管道以
btst_court 同族口径 (全市场含退市者面板、生产 OversoldBounceSetup 原样
import、T+1 开盘买入 + 30bps/边滑点 + 5bps 卖出印花税) 复核暂停决定,
使证据宇宙与被复核策略的候选宇宙一致。

正确性契约 (预注册, 先于数据):
1. detect 通过 import 生产类复用, 绝不复制公式; 公式指纹 = 源文件 sha256
   (oversold_bounce.py + price_returns.py) 记入 manifest。
2. 预筛 = 面板 pct_chg 链式 30 行复合 ≤ -20% (与生产 chained_return_pct
   同数学: prod(1+pct/100)-1, 窗口任一 pct 缺失 → 排除, 与 detect 保守
   miss 一致); 抽查断言预筛值与 detect 输入帧重算 |Δ|<1e-9。
3. 宇宙 = 当日面板全市场 (含退市者, 幸存者偏差在宇宙层解决), 剔北交所。
   OB 无涨停名单式外部权威对账, 完备性由「预筛与 detect 同面板同数学」
   保证并以抽查披露; ST 标记不可得 (面板无 name 列) — st_name 恒 None,
   ST 5% 板在一字判定中按 10% 处理, 作为已知局限入 manifest。
4. regime 用 regime_history (缺标签日 fail-closed 剔除, >10% 中止)。
5. 前向: forward_open_returns (公共函数) T+1 开盘买, T+3/T+5/T+10 开盘卖
   (缺 bar 顺延 T+15 内), 主视野 T+5 = OB natural_horizon。

写入: 仅 data/research/ob_court/event_tables/ (事件表 + manifest)。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import numpy as np  # noqa: F401 — log1p/exp 预筛用

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _btst_court_common import (  # noqa: E402
    FORWARD_SESSIONS,
    WINDOW_A_START,
    forward_open_returns,
    load_regime_history,
    load_sessions,
)

from src.screening.offensive.data.fund_flow_store import FundFlowStore  # noqa: E402
from src.screening.offensive.price_returns import chained_return_pct  # noqa: E402
from src.screening.offensive.setups.oversold_bounce import OversoldBounceSetup  # noqa: E402
from src.tools.ashare_board_utils import is_beijing_exchange_ts_code  # noqa: E402

OB_RESEARCH_DIR = Path("data/research/ob_court")
OB_TABLE_DIR = OB_RESEARCH_DIR / "event_tables"

# 与生产 OversoldBounceSetup 同源 (研究侧声明; 改生产须同步)
_DROP_THRESHOLD = -20.0
_LOOKBACK_DROP_ROWS = 30
PRIMARY_HORIZON = 5  # OB natural_horizon
REF_HORIZONS = (3, 10)

_PRICE_COLS = {"open", "high", "low", "close", "pct_chg", "vol"}


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _file_sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_panel(raw_dir: Path) -> pd.DataFrame:
    frames = [pd.read_csv(p, dtype={"trade_date": str}) for p in sorted((raw_dir / "daily").glob("daily_*.csv"))]
    if not frames:
        raise SystemExit("panel empty — 先跑 scripts/btst_court_fetch.py")
    df = pd.concat(frames, ignore_index=True)
    for col in _PRICE_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close", "open"]).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return df


def drop30_index(panel: pd.DataFrame) -> dict[tuple[str, str], float]:
    """向量化预筛: 每 (ts_code, date) 的 30 行 pct 链式复合收益 (%).

    与生产 chained_return_pct(frame, i-30, i) 同数学 (prod(1+pct/100)-1,
    i 为该日行号); pandas 3.0 无 Rolling.prod → 用数学等价的
    exp(rolling(log)) 实现 (30 项浮点差 ≪ 1e-9, 抽查断言兜底)。
    只保留 ≤ -20% (生产条件 1 同阈值) 的键; 窗口不足 30 行或任一
    pct 缺失 → 不产出 (detect 同样保守 miss)。北交所行不产出。
    """
    out: dict[tuple[str, str], float] = {}
    df = panel[["ts_code", "trade_date", "pct_chg"]].copy()
    df["log_compound"] = np.log1p(df["pct_chg"] / 100.0)
    for ts_code, g in df.groupby("ts_code", sort=False):
        if is_beijing_exchange_ts_code(ts_code):
            continue
        roll = np.exp(g["log_compound"].rolling(_LOOKBACK_DROP_ROWS, min_periods=_LOOKBACK_DROP_ROWS).sum()) - 1.0
        mask = roll.notna() & (roll <= _DROP_THRESHOLD / 100.0)  # 只留跌幅达标 (生产条件 1 同阈值)
        for d, v in zip(g.loc[mask, "trade_date"], (roll[mask] * 100.0)):
            out[(ts_code, str(d))] = float(v)
    return out


def ticker_frame(group: pd.DataFrame, upto: str) -> pd.DataFrame:
    """detect 语义的 prices 帧 (date/open/high/low/close/volume/pct_change), 截止 upto."""
    sub = group[group["trade_date"] <= upto]
    return pd.DataFrame(
        {
            "date": pd.to_datetime(sub["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d"),
            "open": sub["open"].astype(float),
            "high": sub["high"].astype(float),
            "low": sub["low"].astype(float),
            "close": sub["close"].astype(float),
            "volume": sub["vol"].astype(float),
            "pct_change": sub["pct_chg"].astype(float),
        }
    ).reset_index(drop=True)


def overwrite_allowed(prior_fp: str | None, new_fp: str, *, force: bool) -> bool:
    """防覆盖护栏 (btst_court_build 同族): 指纹变化须开新版本文件, force 例外。"""
    if not prior_fp or prior_fp == new_fp:
        return True
    return bool(force)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--end", default=None, help="窗口末日 YYYYMMDD (默认今天)")
    parser.add_argument("--repo-root", default=".", help="数据根 (面板/日历/regime/fund_flow 相对此目录; 默认 cwd)")
    parser.add_argument("--rebuild-force", action="store_true",
                        help="公式指纹变化时允许覆盖既有表 (同行为重建逃生门, manifest 如实披露)")
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()
    os.chdir(args.repo_root)  # 相对路径资产 (fund_flow_cache/日历/regime/btst 面板) 以 repo-root 解析
    end = args.end or date.today().strftime("%Y%m%d")

    sessions_cal = load_sessions(WINDOW_A_START, end)
    regime = load_regime_history()
    regime_missing = [s for s in sessions_cal if s not in regime]
    sessions_cal = [s for s in sessions_cal if s in regime]
    if regime_missing:
        print(f"  [warn] regime 缺标签 {len(regime_missing)} 天, 剔除: {regime_missing}")
        if len(regime_missing) / max(1, len(regime_missing) + len(sessions_cal)) > 0.10:
            raise SystemExit(f"regime 缺口 >10% ({len(regime_missing)} 天) — court 无意义, 中止")

    print("[1/5] 加载面板 (btst_court raw 复用)…")
    panel = load_panel(Path("data/research/btst_court/raw"))
    print(f"  panel rows={len(panel):,} tickers={panel['ts_code'].nunique():,}")

    print("[2/5] 30 日链式跌幅预筛…")
    drop30 = drop30_index(panel)
    by_day: dict[str, pd.DataFrame] = {d: g for d, g in panel.groupby("trade_date")}
    groups = {c: g for c, g in panel.groupby("ts_code")}
    panel_dates = set(by_day.keys())
    sessions = [s for s in sessions_cal if s in panel_dates]
    print(f"  Window A sessions={len(sessions)} ({sessions[0]}..{sessions[-1]}) 预筛候选={len(drop30):,}")

    flow_store = FundFlowStore(cache_dir="data/fund_flow_cache/")
    ff_cache: dict[str, list] = {}
    setup = OversoldBounceSetup()

    events: list[dict] = []
    funnel = {"sessions": 0, "prefilter": 0, "history_short": 0, "hits": 0,
              "misses": 0, "flow_missing_days": 0}
    spot_checked = 0
    spot_max_mismatch = 0.0

    print("[3/5] 逐日重放 detect (生产 OversoldBounceSetup)…")
    for si, s in enumerate(sessions):
        funnel["sessions"] += 1
        # 当日预筛候选 (面板内、跌幅达标)
        day_rows = by_day[s]
        day_set = set(day_rows["ts_code"])
        cand = [(ts, drop30[(ts, s)]) for ts in day_set if (ts, s) in drop30]
        funnel["prefilter"] += len(cand)

        for ts_code, d30 in cand:
            group = groups.get(ts_code)
            if group is None:
                continue
            frame = ticker_frame(group, s)
            if len(frame) < _LOOKBACK_DROP_ROWS + 1 or frame.iloc[-1]["date"].replace("-", "") != s:
                funnel["history_short"] += 1
                continue

            # 抽查: 预筛链式跌幅 vs detect 输入帧逐字重算 (同数学, 须逐位一致)
            if spot_checked < 50:
                idx = len(frame) - 1
                v = chained_return_pct(frame, idx - _LOOKBACK_DROP_ROWS, idx)
                if v is not None:
                    spot_max_mismatch = max(spot_max_mismatch, abs(v - d30))
                spot_checked += 1

            symbol = str(ts_code).split(".")[0]
            flows = ff_cache.get(symbol)
            if flows is None:
                flows = flow_store.get_range(symbol, "20200101", end)
                ff_cache[symbol] = flows
                if not flows:
                    funnel["flow_missing_days"] += 1
            try:
                result = setup.detect(symbol, s, {"prices": frame, "fund_flow_records": flows})
            except Exception:  # noqa: BLE001 - 单票异常不拖垮全日, 不计入 hits
                continue
            if not result.hit:
                funnel["misses"] += 1
                continue
            funnel["hits"] += 1
            md = result.metadata or {}
            row = day_rows[day_rows["ts_code"] == ts_code].iloc[0]
            signal_close = float(row["close"])
            fwd = forward_open_returns(by_day, sessions_cal, ts_code, s, signal_close,
                                       symbol, horizons=(PRIMARY_HORIZON,) + REF_HORIZONS)
            ev = {
                "symbol": symbol,
                "ts_code": ts_code,
                "signal_date": s,
                "regime": regime[s],
                "trigger_strength": float(result.trigger_strength),
                "drop_30d_pct": md.get("drop_30d_pct"),
                "recent_flow_3d": md.get("recent_flow_3d"),
                "degraded": bool(getattr(result, "degraded", False)),
                "signal_close": signal_close,
                "gap_t1_open": fwd.get("gap_t1_open"),
                "fillable": fwd["fillable"],
                "t1_unbuyable": fwd["t1_unbuyable"],
                "t1_missing_bar": fwd["t1_missing_bar"],
            }
            for k in (PRIMARY_HORIZON,) + REF_HORIZONS:
                ev[f"gross_ret_t{k}"] = fwd.get(f"gross_ret_t{k}")
            events.append(ev)
        if si % 40 == 0:
            print(f"  {s} 累计 hits={funnel['hits']}")

    if spot_max_mismatch > 1e-9:
        raise SystemExit(f"预筛与 detect 帧重算不一致 (max |Δ|={spot_max_mismatch}) — 中止")
    print(f"[4/5] events={len(events)} funnel={funnel}")
    if not events:
        raise SystemExit("零事件 — 检查面板/资金流覆盖")

    table = pd.DataFrame(events)
    OB_TABLE_DIR.mkdir(parents=True, exist_ok=True)
    new_fp = _file_sha256("src/screening/offensive/setups/oversold_bounce.py")
    prior_manifest = OB_TABLE_DIR / "manifest_v1.json"
    rebuild_count = 0
    prior_fp: str | None = None
    forced: dict = {}
    if prior_manifest.exists():
        prior = json.loads(prior_manifest.read_text(encoding="utf-8"))
        prior_fp = prior.get("formula_fingerprint", {}).get("oversold_bounce_sha256")
        if not overwrite_allowed(prior_fp, new_fp, force=args.rebuild_force):
            raise SystemExit(
                f"ob_event_table_v1 已由不同公式指纹构建 ({prior_fp[:8]} → {new_fp[:8]}): "
                "行为变化须写新版本文件, 不覆盖; 如确要覆盖用 --rebuild-force"
            )
        rebuild_count = int(prior.get("rebuild_count", 0)) + 1
        if prior_fp and prior_fp != new_fp:
            forced = {"formula_change_forced": True, "prior_formula_fingerprint": prior_fp}
    out = OB_TABLE_DIR / "ob_event_table_v1.csv.gz"
    table.to_csv(out, index=False, compression="gzip")

    xcheck = _cross_check_vs_panel(table)
    manifest = {
        "version": 1,
        "built_at": date.today().isoformat(),
        "git_sha": _git_sha(),
        "formula_fingerprint": {
            "oversold_bounce_sha256": new_fp,
            "price_returns_sha256": _file_sha256("src/screening/offensive/price_returns.py"),
        },
        "window": {"start": WINDOW_A_START, "end": end, "sessions": len(sessions)},
        "primary_horizon": PRIMARY_HORIZON,
        "regime_missing_sessions": regime_missing,
        "funnel": funnel,
        "spot_check": {"checked": spot_checked, "max_abs_diff": spot_max_mismatch},
        "cross_check_vs_panel": xcheck,
        "known_limitations": [
            "st_name 不可得 (面板无 name 列) — ST 5% 板在一字判定按 10% 处理",
            "OB 无外部权威候选名单 — 宇宙完备性由预筛与 detect 同面板同数学保证",
        ],
        "rebuild_count": rebuild_count,
        **forced,
        "rows": len(table),
        "artifact": out.name,
    }
    (OB_TABLE_DIR / "manifest_v1.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[5/5] manifest 写入完成")
    print(json.dumps({k: manifest[k] for k in ("window", "funnel", "spot_check", "cross_check_vs_panel", "rows")}, ensure_ascii=False, indent=2))


def _cross_check_vs_panel(table: pd.DataFrame) -> dict:
    """公式代际交叉验证: 重放强度 vs panel 中 oversold_bounce 记录 (新代)."""
    panel_path = Path("data/reports/setup_output_panel.jsonl")
    if not panel_path.exists():
        return {"status": "panel_missing"}
    recs = [json.loads(l) for l in panel_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    new_gen = [r for r in recs if r.get("setup") == "oversold_bounce"]
    matched = mismatched = absent = 0
    details: list[dict] = []
    for r in new_gen:
        key = (str(r.get("ticker")), str(r.get("signal_date"))[:8].replace("-", ""))
        m = table[(table["symbol"] == key[0]) & (table["signal_date"] == key[1])]
        if m.empty:
            absent += 1
            details.append({"ticker": key[0], "date": key[1], "status": "not_in_replay"})
            continue
        replay_ts = float(m.iloc[0]["trigger_strength"])
        panel_ts = float(r.get("trigger_strength") or 0)
        if abs(replay_ts - panel_ts) < 1e-6:
            matched += 1
        else:
            mismatched += 1
            details.append({"ticker": key[0], "date": key[1], "replay": replay_ts, "panel": panel_ts})
    return {"new_gen_records": len(new_gen), "matched": matched, "mismatched": mismatched, "absent": absent, "details": details[:12]}


if __name__ == "__main__":
    main()
