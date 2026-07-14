"""Cross-cycle robustness of the BTST limit-up-breakout signal (2020-2026).

The Auto-300 gate-removal validation showed score_b membership does not predict
BTST edge, but its window was ~6 weeks of 2026. This tests the UNDERLYING signal
both inside/outside candidates share — a board-aware signal-day limit-up — over a
full bull/bear cycle using the deepened price_cache, split by calendar year and
by regime. If the edge is directionally stable across years (incl. 2022 bear),
the setup both groups rely on is cross-cycle robust.

Caveat: the universe is the current price_cache tickers (survivorship-biased);
this measures signal persistence, not a tradeable live-universe P&L.

Run (after scripts/deepen_price_cache.py):
    uv run python scripts/validate_btst_setup_cross_cycle.py
"""

from __future__ import annotations

from collections import defaultdict

from src.tools.ashare_board_utils import limit_up_pct_for_ticker
from scripts.validate_auto300_gate_removal import (
    HORIZONS,
    _fmt,
    _forward_return,
    _load_regimes,
    _summarize,
    load_price_series,
)


def collect_setup_events(series, regimes) -> list[dict]:
    events: list[dict] = []
    for ticker, df in series.items():
        threshold = limit_up_pct_for_ticker(ticker)
        df = df.reset_index(drop=True)
        closes = df["close"].astype(float).values
        highs = df["high"].astype(float).values
        lows = df["low"].astype(float).values
        vols = df["volume"].astype(float).values if "volume" in df.columns else None
        for idx in df.index[df["pct_change"] >= threshold].tolist():
            if idx + 1 >= len(df):
                continue
            r10 = _forward_return(df, idx, 10)
            r5 = _forward_return(df, idx, 5)
            if r10 is None and r5 is None:
                continue
            # Setup 核心过滤: 涨停前 5 日累计涨幅 (trigger-5 → trigger-1) ≤ 8% (防追高).
            # 复刻 btst_breakout._PRE_RUNUP; 数据不足按 setup 逻辑视为不通过.
            if idx - 5 >= 0 and closes[idx - 5] > 0:
                pre_runup = (closes[idx - 1] / closes[idx - 5] - 1) * 100
            else:
                pre_runup = 999.0
            # ATR-squeeze 代理: trigger 前 5 日 (high-low)/close 均值 < 3% = 低波动盘整
            # (btst_breakout: 低波动组 win 82.8% vs 高波动 60%). 数据不足则视为不通过.
            if idx - 5 >= 0:
                rngs = [
                    (highs[j] - lows[j]) / closes[j] * 100
                    for j in range(idx - 5, idx)
                    if closes[j] > 0
                ]
                atr_pct = sum(rngs) / len(rngs) if rngs else 999.0
            else:
                atr_pct = 999.0
            # 量比: today_vol / 前 20 日均量 (setup 偏好 1.0–2.0x 的温和放量).
            vol_ratio = 0.0
            if vols is not None and idx - 20 >= 0:
                prior = [v for v in vols[idx - 20:idx] if v > 0]
                if prior and vols[idx] > 0:
                    vol_ratio = vols[idx] / (sum(prior) / len(prior))
            day = str(df.iloc[idx]["compact"])
            events.append(
                {
                    "day": day,
                    "year": day[:4],
                    "regime": regimes.get(day, "unknown"),
                    "breakout": pre_runup <= 8.0,
                    "low_atr": atr_pct < 3.0,
                    "vol_band": 1.0 <= vol_ratio <= 2.0,
                    **{f"r{h}": _forward_return(df, idx, h) for h in HORIZONS},
                }
            )
    return events


def _report(title: str, bucket: dict[str, list[dict]]) -> None:
    print(f"=== {title} (T+10) ===")
    for key in sorted(bucket):
        vals = [e["r10"] for e in bucket[key] if e["r10"] is not None]
        print(f"  {key:<9}: {_fmt(_summarize(vals))}")
    print()


def main() -> None:
    series = load_price_series()
    regimes = _load_regimes()
    events = collect_setup_events(series, regimes)

    depths = [len(df) for df in series.values()]
    print(f"price_cache 股票: {len(series)}  中位深度: {sorted(depths)[len(depths)//2]} 行")
    days = sorted({e["day"] for e in events})
    print(f"涨停突破事件(可交易): {len(events)}  窗口: {days[0]} → {days[-1]}")
    print()

    # Overall by horizon.
    print("=== 全周期 各持有期 ===")
    for h in HORIZONS:
        vals = [e[f"r{h}"] for e in events if e[f"r{h}"] is not None]
        print(f"  T+{h:<2}: {_fmt(_summarize(vals))}")
    print()

    by_year: dict[str, list[dict]] = defaultdict(list)
    by_regime: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_year[e["year"]].append(e)
        by_regime[e["regime"]].append(e)

    _report("按年份 · 原始涨停", by_year)
    _report("按 regime · 原始涨停", by_regime)

    # Does the setup's key selectivity filter (pre-runup <= 8%) make the signal
    # cross-cycle robust? Compare raw vs breakout-filtered by year.
    filt = [e for e in events if e["breakout"]]
    print(f"=== 加 breakout 过滤 (涨停前5日涨幅≤8%): {len(filt)}/{len(events)} 事件 ===")
    fy: dict[str, list[dict]] = defaultdict(list)
    fr: dict[str, list[dict]] = defaultdict(list)
    for e in filt:
        fy[e["year"]].append(e)
        fr[e["regime"]].append(e)
    _report("按年份 · breakout过滤", fy)
    _report("按 regime · breakout过滤", fr)

    # Price-based selectivity proxy: breakout(≤8%) + 低波动盘整(ATR<3%). 逼近真实
    # setup 里贡献最大的 squeeze 过滤 (btst_breakout: 低波动 82.8% vs 高波动 60%),
    # 但缺资金流/行业/强度 ranker (无法从价量忠实复刻). 若熊市 E[r] 被拉正, 说明
    # setup 的价量选择性具备跨周期稳健性.
    full = [e for e in events if e["breakout"] and e["low_atr"]]
    print(f"=== 价量选择 (breakout≤8% + ATR<3%): {len(full)}/{len(events)} 事件 ===")
    gy: dict[str, list[dict]] = defaultdict(list)
    gr: dict[str, list[dict]] = defaultdict(list)
    for e in full:
        gy[e["year"]].append(e)
        gr[e["regime"]].append(e)
    _report("按年份 · 价量选择", gy)
    _report("按 regime · 价量选择", gr)


if __name__ == "__main__":
    main()
