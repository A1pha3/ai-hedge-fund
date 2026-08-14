"""Fund-flow gate (条件2) + industry gate (条件3) offline A/B (P2/P3, 2026-08-14).

Question: do detect's condition-2 (main_net_inflow > 20d mean) and condition-3
(industry_day_pct >= 2%) actually discriminate forward returns? The live panel
cannot answer this — detect-miss tickers never reach the panel, so there is no
control group. This script rebuilds the control group offline:

  pool = 涨停 (board-adaptive, 上界护栏) + 防追高 (pre-5d runup <= 8%)   [条件1+4]
  arms:  {过条件2, 不过条件2} and {过条件3, 不过条件3, 行业数据缺失}
  metric: T+1 open → T+5/T+10 close forward return (与 setup_output_panel 同口径)

Window: 2025-07-14 → 2026-08-12 (fund_flow cache starts 2025-07; matches the
live panel window so results are directly comparable).

If a gate's blocked arm is NOT significantly worse than its passed arm, the
gate carries no information and is a candidate for deletion (P2/P3).
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import pandas as pd

from scripts.validate_auto300_gate_removal import _forward_return
from src.screening.offensive.price_returns import chained_return_pct
from src.tools.ashare_board_utils import limit_up_cap_pct_for_ticker, limit_up_pct_for_ticker

_PRICE_DIR = Path("data/price_cache")
_FLOW_DIR = Path("data/fund_flow_cache")
WINDOW_START = "20250714"
WINDOW_END = "20260812"
HORIZONS = (5, 10)
_PRE_RUNUP_LOOKBACK = 5
_PRE_RUNUP_MAX = 8.0
_FLOW_LOOKBACK = 20
_FLOW_MIN_HIST = 5
_INDUSTRY_MIN = 2.0


def _load_flows(ticker: str) -> dict[str, float]:
    path = _FLOW_DIR / f"{ticker}.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype={"date": str})
    out: dict[str, float] = {}
    for _, row in df.iterrows():
        try:
            v = float(row["main_net_inflow"])
        except (TypeError, ValueError, KeyError):
            continue
        if math.isfinite(v):
            out[str(row["date"]).replace("-", "")] = v
    return out


def _stats(vals: list[float]) -> dict:
    n = len(vals)
    if n == 0:
        return {"n": 0}
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v < 0]
    wr = len(wins) / n
    avg = sum(vals) / n
    se = (pd.Series(vals).std() / math.sqrt(n)) if n > 1 else float("nan")
    return {
        "n": n,
        "winrate": round(wr, 4),
        "avg_pct": round(avg, 3),
        "ci95": [round(avg - 1.96 * se, 3), round(avg + 1.96 * se, 3)] if n > 1 else None,
        "avg_gain": round(sum(wins) / len(wins), 3) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 3) if losses else None,
    }


def main() -> None:
    from scripts.setup_research import load_industry_day_pct
    from src.screening.offensive.daily_action import _load_ticker_to_industry_from_snapshots

    tickers = [p.stem for p in _PRICE_DIR.glob("*.csv")]
    ticker_to_industry = _load_ticker_to_industry_from_snapshots(tickers)
    industry_day_pct = load_industry_day_pct()

    # arm -> horizon -> returns
    flow_arms: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    ind_arms: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    pool_size = 0

    for ticker in tickers:
        df = pd.read_csv(_PRICE_DIR / f"{ticker}.csv", dtype={"date": str})
        if "close" not in df.columns or len(df) < 40:
            continue
        df = df.reset_index(drop=True)
        df["date_str"] = df["date"].str.replace("-", "", regex=False)
        flows = _load_flows(ticker)
        flow_dates = sorted(flows)
        industry = ticker_to_industry.get(ticker, "")
        limit_up_pct = limit_up_pct_for_ticker(ticker)
        limit_up_cap = limit_up_cap_pct_for_ticker(ticker)

        for idx in range(len(df)):
            ds = df.at[idx, "date_str"]
            if ds < WINDOW_START or ds > WINDOW_END:
                continue
            try:
                pct = float(df.at[idx, "pct_change"])
            except (TypeError, ValueError):
                continue
            if math.isnan(pct) or pct < limit_up_pct or pct > limit_up_cap + 0.5:
                continue
            # 条件4: 防追高
            if idx - _PRE_RUNUP_LOOKBACK < 0:
                continue
            pre_runup = chained_return_pct(df, idx - _PRE_RUNUP_LOOKBACK, idx - 1)
            if pre_runup is None or pre_runup > _PRE_RUNUP_MAX:
                continue
            pool_size += 1
            fwd = {h: _forward_return(df, idx, h) for h in HORIZONS}

            # 条件2 分组 (与 detect 同口径: 严格历史 < 当日, 不足 5 天无法分组)
            hist = [flows[d] for d in flow_dates if d < ds][-_FLOW_LOOKBACK:]
            today_flow = flows.get(ds)
            if today_flow is not None and len(hist) >= _FLOW_MIN_HIST:
                passed = today_flow > (sum(hist) / len(hist))
                arm = "cond2_pass" if passed else "cond2_blocked"
                for h, r in fwd.items():
                    if r is not None:
                        flow_arms[arm][h].append(r)

            # 条件3 分组
            ind_pct = industry_day_pct.get((industry, ds)) if industry else None
            arm = "cond3_no_data" if ind_pct is None else ("cond3_pass" if ind_pct >= _INDUSTRY_MIN else "cond3_blocked")
            for h, r in fwd.items():
                if r is not None:
                    ind_arms[arm][h].append(r)

    report = {
        "window": f"{WINDOW_START}→{WINDOW_END}",
        "pool_cond1_cond4": pool_size,
        "cond2": {arm: {f"t{h}": _stats(v) for h, v in sorted(hz.items())} for arm, hz in sorted(flow_arms.items())},
        "cond3": {arm: {f"t{h}": _stats(v) for h, v in sorted(hz.items())} for arm, hz in sorted(ind_arms.items())},
    }
    out = "data/reports/gate_cond2_cond3_ab_20260814.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"written: {out}")


if __name__ == "__main__":
    main()
