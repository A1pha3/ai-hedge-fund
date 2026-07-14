"""Validate the T8 Auto-300 gate removal on historical BTST edge.

Question: over the window where both `auto_screening_*.json` (score_b top-300
membership per signal day) and `price_cache` (forward returns) exist, do
limit-up-breakout BTST candidates that fall OUTSIDE the score_b top-300 have
comparable forward T+1..T+10 win-rate / payoff to those INSIDE it?

If outside candidates behave like inside ones, removing the Auto-300 gate (which
this repo did) is at worst neutral and admits valid BTST setups the gate had been
blocking. If they are materially worse, the gate removal needs a tighter filter.

Selection proxy: the defining BTST trigger is a signal-day limit-up (board-aware
threshold via `limit_up_pct_for_ticker`). Entry at T+1 open (skipping T+1 locked
limit-up = unbuyable), exit at T+N close. This is a deliberately simple, fully
reproducible proxy from local data only (no network).

Run:
    uv run python scripts/validate_auto300_gate_removal.py
"""

from __future__ import annotations

import glob
import json
import math
import statistics
from datetime import date
from pathlib import Path

import pandas as pd

from src.tools.ashare_board_utils import is_beijing_exchange_stock
from src.tools.ashare_board_utils import limit_up_pct_for_ticker

REPORTS = Path("data/reports")
PRICE_CACHE = Path("data/price_cache")
HORIZONS = (1, 3, 5, 10)


def _compact(d: str) -> str:
    return str(d).replace("-", "")[:8]


def load_auto300_by_day() -> dict[str, set[str]]:
    """{YYYYMMDD: set(score_b top pool tickers)} from every auto_screening report.

    Prefers ``candidate_pool_run.candidates`` (new schema = the exact pool the
    manifest gate used). Falls back to ``recommendations`` when it holds the full
    score_b top pool (>=100 entries); smaller Top-N outputs are not a membership
    pool and are skipped so the inside/outside split stays fair.
    """
    membership: dict[str, set[str]] = {}
    for path in glob.glob(str(REPORTS / "auto_screening_*.json")):
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        day = _compact(str(payload.get("date", "")))
        cpr = payload.get("candidate_pool_run")
        if isinstance(cpr, dict) and cpr.get("candidates"):
            rows = cpr["candidates"]
        else:
            recs = payload.get("recommendations")
            rows = recs if isinstance(recs, list) and len(recs) >= 100 else []
        tickers = {
            str(row.get("ticker"))
            for row in rows
            if isinstance(row, dict) and row.get("ticker")
        }
        if day and tickers:
            membership[day] = tickers
    return membership


def load_price_series() -> dict[str, pd.DataFrame]:
    series: dict[str, pd.DataFrame] = {}
    for path in glob.glob(str(PRICE_CACHE / "*.csv")):
        ticker = Path(path).stem
        if not (ticker.isdigit() and len(ticker) == 6):
            continue
        if is_beijing_exchange_stock(symbol=ticker):  # 北交所全面排除
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if not {"date", "open", "close", "high", "low", "pct_change"}.issubset(df.columns):
            continue
        df["compact"] = df["date"].astype(str).str.replace("-", "", regex=False).str[:8]
        df = df.sort_values("compact").reset_index(drop=True)
        series[ticker] = df
    return series


def _forward_return(df: pd.DataFrame, signal_idx: int, horizon: int) -> float | None:
    """Enter at T+1 open, exit at T+horizon close. None if unbuyable/insufficient."""
    entry_idx = signal_idx + 1
    exit_idx = signal_idx + horizon
    if exit_idx >= len(df):
        return None
    entry = df.iloc[entry_idx]
    # T+1 locked limit-up (high == low) → cannot buy → not an actionable trade.
    if float(entry["high"]) == float(entry["low"]):
        return None
    entry_open = float(entry["open"])
    if entry_open <= 0:
        return None
    exit_close = float(df.iloc[exit_idx]["close"])
    return (exit_close - entry_open) / entry_open * 100.0


def collect_events(
    membership: dict[str, set[str]], series: dict[str, pd.DataFrame]
) -> list[dict]:
    """One event per (ticker, signal-day limit-up) that has an auto report that day."""
    report_days = set(membership)
    regimes = _load_regimes()
    events: list[dict] = []
    for ticker, df in series.items():
        threshold = limit_up_pct_for_ticker(ticker)
        for idx in range(len(df) - 1):
            row = df.iloc[idx]
            day = str(row["compact"])
            if day not in report_days:
                continue
            try:
                pct = float(row["pct_change"])
            except (TypeError, ValueError):
                continue
            if pct < threshold:  # not a limit-up breakout
                continue
            rets = {h: _forward_return(df, idx, h) for h in HORIZONS}
            if rets[1] is None:  # unbuyable / no forward data
                continue
            events.append(
                {
                    "ticker": ticker,
                    "day": day,
                    "inside": ticker in membership[day],
                    "regime": regimes.get(day, "unknown"),
                    **{f"r{h}": rets[h] for h in HORIZONS},
                }
            )
    return events


def _load_regimes() -> dict[str, str]:
    try:
        payload = json.loads((REPORTS / "regime_history.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {_compact(k): str(v) for k, v in payload.items()} if isinstance(payload, dict) else {}


def _summarize(values: list[float]) -> dict:
    n = len(values)
    if n == 0:
        return {"n": 0}
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v <= 0]
    mean = statistics.fmean(values)
    std = statistics.pstdev(values) if n > 1 else 0.0
    se = std / math.sqrt(n) if n > 0 else 0.0
    avg_win = statistics.fmean(wins) if wins else 0.0
    avg_loss = statistics.fmean(losses) if losses else 0.0
    payoff = (avg_win / abs(avg_loss)) if losses and avg_loss != 0 else float("inf")
    return {
        "n": n,
        "winrate": len(wins) / n * 100.0,
        "E[r]%": mean,
        "median%": statistics.median(values),
        "ci95": (mean - 1.96 * se, mean + 1.96 * se),
        "payoff": payoff,
        "tail<-10%": sum(v < -10 for v in values) / n * 100.0,
        "tail<-15%": sum(v < -15 for v in values) / n * 100.0,
    }


def _fmt(s: dict) -> str:
    if s.get("n", 0) == 0:
        return "n=0"
    lo, hi = s["ci95"]
    return (
        f"n={s['n']:<4} winrate={s['winrate']:5.1f}%  E[r]={s['E[r]%']:+6.2f}%  "
        f"median={s['median%']:+6.2f}%  CI95=[{lo:+.2f},{hi:+.2f}]  "
        f"payoff={s['payoff']:.2f}  tail<-10%={s['tail<-10%']:.0f}%  tail<-15%={s['tail<-15%']:.0f}%"
    )


def main() -> None:
    membership = load_auto300_by_day()
    series = load_price_series()
    events = collect_events(membership, series)

    days = sorted({e["day"] for e in events})
    print(f"报告日(有 Auto-300 名单): {len(membership)}  price_cache 股票: {len(series)}")
    print(f"涨停突破事件(可交易): {len(events)}  覆盖信号日: {len(days)}")
    if days:
        print(f"窗口: {days[0]} → {days[-1]}")
    print()

    for horizon in HORIZONS:
        inside = [e[f"r{horizon}"] for e in events if e["inside"] and e[f"r{horizon}"] is not None]
        outside = [e[f"r{horizon}"] for e in events if not e["inside"] and e[f"r{horizon}"] is not None]
        si, so = _summarize(inside), _summarize(outside)
        print(f"--- T+{horizon} ---")
        print(f"  Auto-300 内 : {_fmt(si)}")
        print(f"  Auto-300 外 : {_fmt(so)}")
        if si.get("n") and so.get("n"):
            diff = so["E[r]%"] - si["E[r]%"]
            # Welch-style SE on the mean difference.
            vi = statistics.pvariance(inside) if len(inside) > 1 else 0.0
            vo = statistics.pvariance(outside) if len(outside) > 1 else 0.0
            se_diff = math.sqrt(vi / len(inside) + vo / len(outside)) if inside and outside else 0.0
            t = diff / se_diff if se_diff else 0.0
            print(f"  外-内 E[r] 差 = {diff:+.2f}%  (t≈{t:+.2f}; |t|<2 视为无显著差异)")
        print()

    # Cross-regime robustness at the BTST horizon (T+10): does "外 >= 内" hold in
    # the crisis / risk_off regimes too, not just normal?
    print("=== 跨 regime 稳健性 (T+10) ===")
    for regime in ("normal", "crisis", "risk_off"):
        reg_events = [e for e in events if e["regime"] == regime]
        inside = [e["r10"] for e in reg_events if e["inside"] and e["r10"] is not None]
        outside = [e["r10"] for e in reg_events if not e["inside"] and e["r10"] is not None]
        print(f"--- {regime} (信号日事件 {len(reg_events)}) ---")
        print(f"  内 : {_fmt(_summarize(inside))}")
        print(f"  外 : {_fmt(_summarize(outside))}")
    print()


if __name__ == "__main__":
    main()
