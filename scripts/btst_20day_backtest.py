#!/usr/bin/env python3
"""
BTST 20天真实回测：对比 default vs ic_optimized profile 的实际选股表现。

核心逻辑：
1. 对每个交易日，构建候选池（模拟pipeline的过滤逻辑）
2. 用历史价格数据计算7+1个因子的近似值
3. 分别用default和ic_optimized的在线profile权重计算score_target
4. 选出score_target超过阈值的股票
5. 对比次日实际收益

注意：这是因子层面的近似回测，不包含LLM agent评分（score_c）。
score_c在实际pipeline中贡献~40%权重，因此回测结果会低估实际区分度。
"""

import json
import math
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from src.targets import get_short_trade_target_profile

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def spearman_ic(x, y):
    x, y = np.array(x, dtype=float), np.array(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 10:
        return np.nan
    rx = pd.Series(x).rank().values
    ry = pd.Series(y).rank().values
    n = len(rx)
    d = rx - ry
    return 1.0 - 6.0 * np.sum(d**2) / (n * (n**2 - 1))


def compute_factors(hist_group, trade_date_price):
    """从历史价格数据计算各因子近似值。"""
    g = hist_group.sort_values("trade_date")
    close = g["close"].values
    vol_col = "vol" if "vol" in g.columns else "volume"
    volume = g[vol_col].values
    n = len(close)
    if n < 22:
        return None

    # --- 基础指标 ---
    last_close = close[-1]
    prev_close = close[-2] if n >= 2 else close[-1]
    open_price = g["open"].values[-1]

    # --- momentum_strength (trend agent momentum subfactor) ---
    mom_1m = (close[-1] / close[-22] - 1) if n >= 23 else 0
    mom_3m = (close[-1] / close[-min(66, n - 1)] - 1) if n >= 67 else mom_1m
    mom_1m_n = min(max(mom_1m / 0.3, 0), 1)
    mom_3m_n = min(max(mom_3m / 0.5, 0), 1)
    if n >= 133:
        mom_6m = close[-1] / close[-132] - 1
        mom_6m_n = min(max(mom_6m / 0.8, 0), 1)
        momentum_strength = min(max(0.4 * mom_1m_n + 0.3 * mom_3m_n + 0.3 * mom_6m_n, 0), 1)
    elif n >= 67:
        momentum_strength = min(max(0.6 * mom_1m_n + 0.4 * mom_3m_n, 0), 1)
    else:
        momentum_strength = mom_1m_n

    # --- volume_expansion_quality ---
    # 近5日成交量 vs 20日均量
    avg_vol_20 = np.mean(volume[-min(20, n) :]) if n >= 5 else 1
    avg_vol_5 = np.mean(volume[-5:]) if n >= 5 else 1
    vol_ratio = avg_vol_5 / avg_vol_20 if avg_vol_20 > 0 else 1.0
    volume_expansion = min(max((vol_ratio - 1.0) / 1.5, 0), 1)  # 0~2.5x volume → 0~1

    # --- close_strength (EMA alignment proxy) ---
    # 简化：用价格相对位置表示趋势强度
    high_20 = np.max(close[-min(20, n) :])
    low_20 = np.min(close[-min(20, n) :])
    price_range = high_20 - low_20 if high_20 > low_20 else 1
    close_strength = (last_close - low_20) / price_range  # 在区间中的位置

    # --- breakout_freshness (简化) ---
    # 近5日涨幅 + 当日涨幅
    ret_5d = (close[-1] / close[-min(6, n)] - 1) if n >= 6 else 0
    daily_return = (last_close / prev_close - 1) if prev_close > 0 else 0
    breakout_raw = 0.5 * min(max(ret_5d / 0.15, 0), 1) + 0.5 * min(max(daily_return / 0.05, 0), 1)
    breakout_freshness = min(max(breakout_raw, 0), 1)

    # --- trend_acceleration (简化) ---
    # 短期动量 vs 中期动量的加速度
    if n >= 44:
        mom_2w = close[-1] / close[-10] - 1
        mom_prev_2w = close[-11] / close[-21] - 1 if n >= 22 else 0
        accel = mom_2w - mom_prev_2w
        trend_acceleration = min(max(accel / 0.1, 0), 1)
    else:
        trend_acceleration = 0.5 * momentum_strength

    # --- sector_resonance (用行业beta近似) ---
    # 简化：当日涨幅vs市场涨幅
    sector_resonance = 0.5  # 无行业数据，取中性值

    # --- catalyst_freshness (用事件信号强度近似) ---
    # 简化：用换手率和涨幅组合
    amount = g["amount"].values[-1]
    avg_amount = np.mean(g["amount"].values[-min(20, n) :])
    amount_ratio = amount / avg_amount if avg_amount > 0 else 1.0
    catalyst_freshness = min(max(0.6 * min(amount_ratio / 3.0, 1) + 0.4 * breakout_freshness, 0), 1)

    # --- layer_c_alignment (简化) ---
    # 用阳线+涨跌幅组合
    is_bull = last_close > open_price
    layer_c_alignment = min(max(0.5 * float(is_bull) + 0.5 * min(max(daily_return / 0.03, 0), 1), 0), 1)

    # --- 短期反转因子 ---
    if n >= 6:
        ret_5d_raw = close[-1] / close[-6] - 1
        reversal = min(max(-ret_5d_raw / 0.10, 0), 1)  # 5日跌幅越大，反转值越高
    else:
        reversal = 0.0

    return {
        "momentum_strength": momentum_strength,
        "volume_expansion_quality": volume_expansion,
        "close_strength": close_strength,
        "breakout_freshness": breakout_freshness,
        "trend_acceleration": trend_acceleration,
        "sector_resonance": sector_resonance,
        "catalyst_freshness": catalyst_freshness,
        "layer_c_alignment": layer_c_alignment,
        "reversal": reversal,
        "daily_return": daily_return,
        "vol_ratio": vol_ratio,
    }


def summarize_return_stats(returns: pd.Series, *, big_win_threshold: float = 3.0) -> dict[str, float | None]:
    values = pd.Series(returns, dtype=float).dropna()
    if values.empty:
        return {
            "win_rate": 0.0,
            "avg_ret": 0.0,
            "big_win_rate": 0.0,
            "avg_win_ret": 0.0,
            "avg_loss_ret": 0.0,
            "payoff_ratio": None,
            "expectancy": 0.0,
            "downside_p10": 0.0,
        }

    wins = values[values > 0]
    losses = values[values <= 0]
    win_rate = float((values > 0).mean())
    avg_ret = float(values.mean())
    big_win_rate = float((values > big_win_threshold).mean())
    avg_win_ret = float(wins.mean()) if not wins.empty else 0.0
    avg_loss_ret = float(losses.mean()) if not losses.empty else 0.0
    payoff_ratio: float | None = None
    if avg_win_ret > 0 and avg_loss_ret < 0:
        payoff_ratio = float(avg_win_ret / abs(avg_loss_ret))
    expectancy = float((win_rate * avg_win_ret) + ((1.0 - win_rate) * avg_loss_ret))
    downside_p10 = float(values.quantile(0.10))
    return {
        "win_rate": win_rate,
        "avg_ret": avg_ret,
        "big_win_rate": big_win_rate,
        "avg_win_ret": avg_win_ret,
        "avg_loss_ret": avg_loss_ret,
        "payoff_ratio": payoff_ratio,
        "expectancy": expectancy,
        "downside_p10": downside_p10,
    }


PROFILE_WEIGHT_FIELDS = {
    "breakout_freshness": "breakout_freshness_weight",
    "trend_acceleration": "trend_acceleration_weight",
    "volume_expansion_quality": "volume_expansion_quality_weight",
    "close_strength": "close_strength_weight",
    "sector_resonance": "sector_resonance_weight",
    "catalyst_freshness": "catalyst_freshness_weight",
    "layer_c_alignment": "layer_c_alignment_weight",
    "momentum_strength": "momentum_strength_weight",
    "reversal": "short_term_reversal_weight",
}


def _build_profiles(profile_names: tuple[str, ...] = ("default", "ic_optimized")) -> dict[str, dict[str, object]]:
    profiles: dict[str, dict[str, object]] = {}
    for profile_name in profile_names:
        profile = get_short_trade_target_profile(profile_name)
        profiles[profile_name] = {
            "select_threshold": float(profile.select_threshold),
            "near_miss_threshold": float(profile.near_miss_threshold),
            "selected_rank_cap": int(profile.selected_rank_cap),
            "near_miss_rank_cap": int(profile.near_miss_rank_cap),
            "selected_rank_cap_ratio": float(profile.selected_rank_cap_ratio),
            "near_miss_rank_cap_ratio": float(profile.near_miss_rank_cap_ratio),
            "weights": {factor_name: float(getattr(profile, weight_field)) for factor_name, weight_field in PROFILE_WEIGHT_FIELDS.items()},
        }
    return profiles


PROFILES = _build_profiles()


def _resolve_effective_rank_cap(*, hard_cap: int, cap_ratio: float, rank_population: int) -> int | None:
    normalized_hard_cap = int(hard_cap or 0)
    normalized_ratio = float(cap_ratio or 0.0)
    dynamic_cap: int | None = None
    if normalized_ratio > 0 and rank_population > 0:
        dynamic_cap = max(1, int(math.ceil(rank_population * normalized_ratio)))
    if dynamic_cap is None:
        return normalized_hard_cap if normalized_hard_cap > 0 else None
    if normalized_hard_cap <= 0:
        return dynamic_cap
    return max(normalized_hard_cap, dynamic_cap)


def _apply_rank_caps_to_scored_results(
    results: pd.DataFrame,
    *,
    score_col: str,
    select_threshold: float,
    near_miss_threshold: float,
    selected_rank_cap: int,
    near_miss_rank_cap: int,
    selected_rank_cap_ratio: float = 0.0,
    near_miss_rank_cap_ratio: float = 0.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ranked = results.sort_values(score_col, ascending=False).copy()
    ranked["rank_hint"] = np.arange(1, len(ranked) + 1, dtype=int)
    rank_population = len(ranked)
    effective_selected_rank_cap = _resolve_effective_rank_cap(
        hard_cap=selected_rank_cap,
        cap_ratio=selected_rank_cap_ratio,
        rank_population=rank_population,
    )
    effective_near_miss_rank_cap = _resolve_effective_rank_cap(
        hard_cap=near_miss_rank_cap,
        cap_ratio=near_miss_rank_cap_ratio,
        rank_population=rank_population,
    )

    score_series = ranked[score_col]
    selected_score_mask = score_series >= select_threshold
    near_miss_score_mask = (score_series >= near_miss_threshold) & (score_series < select_threshold)

    selected_rank_mask = pd.Series(True, index=ranked.index) if effective_selected_rank_cap is None else ranked["rank_hint"] <= int(effective_selected_rank_cap)
    near_miss_rank_mask = pd.Series(True, index=ranked.index) if effective_near_miss_rank_cap is None else ranked["rank_hint"] <= int(effective_near_miss_rank_cap)

    selected_mask = selected_score_mask & selected_rank_mask
    demoted_selected_mask = selected_score_mask & ~selected_rank_mask & near_miss_rank_mask
    near_miss_mask = (near_miss_score_mask & near_miss_rank_mask) | demoted_selected_mask

    return ranked[selected_mask], ranked[near_miss_mask]


def normalize_weights(weights):
    total = sum(max(0.0, v) for v in weights.values())
    if total <= 0:
        return {k: 1.0 / len(weights) for k in weights}
    return {k: max(0.0, v) / total for k, v in weights.items()}


def compute_score(factors, weights):
    nw = normalize_weights(weights)
    score = sum(nw.get(k, 0) * factors.get(k, 0) for k in nw)
    return min(max(score, 0), 1)


def main():
    import tushare as ts

    ts.set_token(os.getenv("TUSHARE_TOKEN"))
    pro = ts.pro_api()

    # 获取交易日历
    cal = pro.trade_cal(exchange="SSE", start_date="20260220", end_date="20260414", is_open="1")
    all_dates = sorted(cal["cal_date"].tolist())
    # 构建 next_date 映射
    next_map = {d: all_dates[i + 1] for i, d in enumerate(all_dates) if i + 1 < len(all_dates)}

    test_dates = [d for d in all_dates if d <= "20260410"][-20:]

    print(f"回测日期: {test_dates[0]} ~ {test_dates[-1]} ({len(test_dates)}天)")
    print("=" * 90)

    sb = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name,industry")

    all_daily = {p: {"selected": [], "near_miss": [], "all_scores": []} for p in PROFILES}

    for di, test_date in enumerate(test_dates):
        next_date = next_map.get(test_date)
        if not next_date:
            continue

        # 获取当日数据
        try:
            df = pro.daily(trade_date=test_date)
        except:
            continue
        if df is None or df.empty:
            continue

        df = df.merge(sb, on="ts_code", how="left")
        # 候选池过滤
        df = df[df["amount"] >= 100000]
        df = df[~df["name"].str.contains("ST|退", na=False)]
        df = df[~df["ts_code"].str.startswith(("688", "8", "4"))]
        df = df[df["pct_chg"].between(-9.5, 9.5)]

        # 获取次日收益
        try:
            dfn = pro.daily(trade_date=next_date)[["ts_code", "pct_chg"]].rename(columns={"pct_chg": "next_ret"})
        except:
            continue
        df = df.merge(dfn, on="ts_code")
        if len(df) < 100:
            continue

        # 获取历史价格
        codes = df["ts_code"].tolist()
        history = []
        for i in range(0, len(codes), 80):
            batch = codes[i : i + 80]
            try:
                h = pro.daily(ts_code=",".join(batch), start_date="20250601", end_date=test_date)
                if h is not None and not h.empty:
                    history.append(h)
            except:
                continue
        if not history:
            continue

        hist = pd.concat(history, ignore_index=True)
        hist["trade_date"] = pd.to_datetime(hist["trade_date"], format="%Y%m%d")
        hist = hist.sort_values(["ts_code", "trade_date"])

        # 计算因子
        stock_factors = {}
        for code, g in hist.groupby("ts_code"):
            if len(g) < 22:
                continue
            f = compute_factors(g, None)
            if f is not None:
                stock_factors[code] = f

        if not stock_factors:
            continue

        # 为每只股票计算各profile的score
        results = df[df["ts_code"].isin(stock_factors.keys())].copy()
        if len(results) < 50:
            continue

        for pname, pconfig in PROFILES.items():
            scores = []
            for _, row in results.iterrows():
                f = stock_factors.get(row["ts_code"])
                if f is None:
                    scores.append(0)
                    continue
                s = compute_score(f, pconfig["weights"])
                scores.append(s)
            results[f"score_{pname}"] = scores

        # 统计各profile表现
        date_summary = {"date": test_date, "next_date": next_date, "n_pool": len(results)}
        for pname, pconfig in PROFILES.items():
            col = f"score_{pname}"
            sel, nm = _apply_rank_caps_to_scored_results(
                results,
                score_col=col,
                select_threshold=float(pconfig["select_threshold"]),
                near_miss_threshold=float(pconfig["near_miss_threshold"]),
                selected_rank_cap=int(pconfig["selected_rank_cap"]),
                near_miss_rank_cap=int(pconfig["near_miss_rank_cap"]),
                selected_rank_cap_ratio=float(pconfig["selected_rank_cap_ratio"]),
                near_miss_rank_cap_ratio=float(pconfig["near_miss_rank_cap_ratio"]),
            )

            for group_name, group_df in [("selected", sel), ("near_miss", nm)]:
                if len(group_df) < 1:
                    continue
                return_stats = summarize_return_stats(group_df["next_ret"])
                all_daily[pname][group_name].append(
                    {
                        "date": test_date,
                        "next_date": next_date,
                        "n": len(group_df),
                        "win_rate": return_stats["win_rate"],
                        "avg_ret": return_stats["avg_ret"],
                        "big_win_rate": return_stats["big_win_rate"],
                        "avg_win_ret": return_stats["avg_win_ret"],
                        "avg_loss_ret": return_stats["avg_loss_ret"],
                        "payoff_ratio": return_stats["payoff_ratio"],
                        "expectancy": return_stats["expectancy"],
                        "downside_p10": return_stats["downside_p10"],
                        "tickers": group_df["ts_code"].tolist()[:10],
                    }
                )

            # IC of score vs next_ret
            ic = spearman_ic(results[col].values, results["next_ret"].values)
            date_summary[f"{pname}_ic"] = ic
            date_summary[f"{pname}_selected"] = len(sel)
            date_summary[f"{pname}_near_miss"] = len(nm)

        print(f"[{di + 1}/{len(test_dates)}] {test_date}→{next_date}: pool={len(results)}", end="")
        for pname in PROFILES:
            s = date_summary.get(f"{pname}_selected", 0)
            ic = date_summary.get(f"{pname}_ic", 0)
            print(f"  {pname}: sel={s} IC={ic:+.3f}", end="")
        print()

    # ====== 汇总 ======
    print(f"\n{'=' * 90}")
    print("回测汇总")
    print(f"{'=' * 90}")

    for pname in PROFILES:
        print(f"\n--- {pname} profile ---")
        for group in ["selected", "near_miss"]:
            entries = all_daily[pname][group]
            if not entries:
                print(f"  {group}: 无数据")
                continue
            total_n = sum(e["n"] for e in entries)
            avg_wr = np.mean([e["win_rate"] for e in entries])
            avg_ret = np.mean([e["avg_ret"] for e in entries])
            avg_big = np.mean([e["big_win_rate"] for e in entries])
            avg_expectancy = np.mean([e.get("expectancy", 0.0) for e in entries])
            avg_downside_p10 = np.mean([e.get("downside_p10", 0.0) for e in entries])
            payoff_values = [float(e["payoff_ratio"]) for e in entries if e.get("payoff_ratio") is not None]
            avg_payoff = float(np.mean(payoff_values)) if payoff_values else np.nan
            n_days_positive = sum(1 for e in entries if e["avg_ret"] > 0)
            print(f"  {group}: {len(entries)}天有数据, 总计{total_n}只")
            payoff_text = f"{avg_payoff:.2f}" if np.isfinite(avg_payoff) else "N/A"
            print(f"    日均胜率={avg_wr:.0%} 日均收益={avg_ret:+.2f}% 大涨率={avg_big:.0%} " f"赔率={payoff_text} 期望={avg_expectancy:+.2f}% 下行P10={avg_downside_p10:+.2f}% " f"正收益天数={n_days_positive}/{len(entries)}")
            # 逐日明细
            for e in entries:
                day_payoff = "N/A" if e.get("payoff_ratio") is None else f"{float(e['payoff_ratio']):.2f}"
                print(f"    {e['date']}: {e['n']}只 胜率={e['win_rate']:.0%} 收益={e['avg_ret']:+.2f}% " f"赔率={day_payoff} 期望={e.get('expectancy', 0.0):+.2f}% 下行P10={e.get('downside_p10', 0.0):+.2f}% " f"{e['tickers'][:5]}")

    # 保存结果
    out = {}
    for pname in PROFILES:
        out[pname] = {}
        for group in ["selected", "near_miss"]:
            out[pname][group] = [
                {
                    "date": e["date"],
                    "next_date": e["next_date"],
                    "n": e["n"],
                    "win_rate": round(float(e["win_rate"]), 4),
                    "avg_ret": round(float(e["avg_ret"]), 4),
                    "big_win_rate": round(float(e["big_win_rate"]), 4),
                    "avg_win_ret": round(float(e.get("avg_win_ret", 0.0)), 4),
                    "avg_loss_ret": round(float(e.get("avg_loss_ret", 0.0)), 4),
                    "payoff_ratio": (round(float(e["payoff_ratio"]), 4) if e.get("payoff_ratio") is not None else None),
                    "expectancy": round(float(e.get("expectancy", 0.0)), 4),
                    "downside_p10": round(float(e.get("downside_p10", 0.0)), 4),
                    "tickers": e["tickers"],
                }
                for e in all_daily[pname][group]
            ]

    out_path = Path(__file__).resolve().parent.parent / "data" / "reports" / "btst_20day_backtest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存到 {out_path}")


if __name__ == "__main__":
    main()
