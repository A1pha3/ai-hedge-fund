#!/usr/bin/env python3
"""BTST Regime Gate x 15% Hit Rate Cross-Analysis.

Answers the key question: Does the 15% hit rate improve significantly on strong market days?
If yes, combining regime gating with factor selection could achieve the 55% target.

Usage:
    uv run python scripts/btst_regime_gate_15pct_cross_analysis.py
    uv run python scripts/btst_regime_gate_15pct_cross_analysis.py --output-json data/reports/btst_regime_gate_15pct_cross_analysis.json
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BACKTEST_JSON = Path("data/reports/btst_20day_backtest_regime_analysis.json")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_regime_gate_15pct_cross_analysis.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_regime_gate_15pct_cross_analysis.md")

TARGET_HIT_RATE = 0.55
TARGET_RETURN = 0.15
HOLDING_DAYS = 5


def _load_backtest_results(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def _fetch_index_data(pro, start_date: str, end_date: str) -> pd.DataFrame:
    df = pro.index_daily(ts_code="000001.SH", start_date=start_date, end_date=end_date)
    if df is None or df.empty:
        df = pro.index_daily(ts_code="000300.SH", start_date=start_date, end_date=end_date)
    if df is None or df.empty:
        return pd.DataFrame()
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df = df.sort_values("trade_date").reset_index(drop=True)
    return df


def _classify_regime(index_df: pd.DataFrame, trade_date: str) -> dict[str, Any]:
    td = pd.to_datetime(trade_date, format="%Y%m%d")
    row_mask = index_df["trade_date"] == td
    if not row_mask.any():
        return {"regime": "unknown", "breadth_proxy": None, "daily_return": None}
    idx = row_mask.idxmax()
    row = index_df.loc[idx]

    prev_mask = index_df["trade_date"] < td
    if prev_mask.sum() < 20:
        return {"regime": "unknown", "breadth_proxy": None, "daily_return": None}

    daily_return = float(row.get("pct_chg", 0) or 0) / 100.0

    recent = index_df[index_df["trade_date"] <= td].tail(20)
    adv_count = (recent["pct_chg"] > 0).sum()
    breadth_proxy = float(adv_count) / 20.0

    vol_col = "vol" if "vol" in recent.columns else "amount"
    if vol_col in recent.columns:
        avg_vol = recent[vol_col].iloc[-20:].mean()
        last_vol = float(row.get(vol_col, 0) or 0)
        vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1.0
    else:
        vol_ratio = 1.0

    if breadth_proxy <= 0.35 or daily_return <= -0.02:
        regime = "halt"
    elif breadth_proxy <= 0.45 or daily_return <= -0.01:
        regime = "risk_off"
    elif breadth_proxy >= 0.65 and daily_return >= 0.005:
        regime = "aggressive_trade"
    elif breadth_proxy >= 0.50:
        regime = "normal_trade"
    else:
        regime = "shadow_only"

    return {
        "regime": regime,
        "breadth_proxy": round(breadth_proxy, 4),
        "daily_return": round(daily_return, 6),
        "vol_ratio": round(vol_ratio, 4),
    }


def _fetch_forward_high_returns(pro, tickers: list[str], trade_date: str, holding_days: int = 5) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    td = pd.to_datetime(trade_date, format="%Y%m%d")
    end_date = (td + timedelta(days=holding_days * 2)).strftime("%Y%m%d")

    for i in range(0, len(tickers), 80):
        batch = tickers[i : i + 80]
        try:
            df = pro.daily(ts_code=",".join(batch), start_date=trade_date, end_date=end_date)
        except Exception:
            continue
        if df is None or df.empty:
            continue

        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
        df = df.sort_values(["ts_code", "trade_date"])

        for code, group in df.groupby("ts_code"):
            group = group[group["trade_date"] > td].head(holding_days)
            if group.empty:
                results[code] = {"max_high_return": None, "hit_15pct": None, "forward_days": 0}
                continue

            buy_close = df[(df["ts_code"] == code) & (df["trade_date"] == td)]
            if buy_close.empty:
                buy_price = group.iloc[0]["pre_close"]
            else:
                buy_price = buy_close.iloc[0]["close"]

            if buy_price <= 0:
                results[code] = {"max_high_return": None, "hit_15pct": None, "forward_days": len(group)}
                continue

            max_high = group["high"].max()
            max_high_return = (max_high - buy_price) / buy_price
            results[code] = {
                "max_high_return": round(float(max_high_return), 6),
                "hit_15pct": max_high_return >= TARGET_RETURN,
                "forward_days": len(group),
            }

    return results


def _compute_regime_stats(day_records: list[dict[str, Any]]) -> dict[str, Any]:
    if not day_records:
        return {
            "day_count": 0,
            "total_selected": 0,
            "total_evaluable": 0,
            "hit_15pct_count": 0,
            "hit_15pct_rate": None,
            "mean_max_high_return": None,
            "avg_daily_win_rate": None,
            "avg_daily_return": None,
        }

    total_selected = sum(r.get("n_selected", 0) for r in day_records)
    total_evaluable = sum(r.get("n_evaluable", 0) for r in day_records)
    hit_count = sum(r.get("hit_15pct_count", 0) for r in day_records)
    [r.get("hit_15pct_rate") for r in day_records if r.get("hit_15pct_rate") is not None]
    max_returns = [r.get("mean_max_high_return") for r in day_records if r.get("mean_max_high_return") is not None]
    win_rates = [r.get("win_rate") for r in day_records if r.get("win_rate") is not None]
    avg_rets = [r.get("avg_ret") for r in day_records if r.get("avg_ret") is not None]

    return {
        "day_count": len(day_records),
        "total_selected": total_selected,
        "total_evaluable": total_evaluable,
        "hit_15pct_count": hit_count,
        "hit_15pct_rate": round(hit_count / total_evaluable, 4) if total_evaluable > 0 else None,
        "mean_max_high_return": round(float(np.mean(max_returns)), 4) if max_returns else None,
        "avg_daily_win_rate": round(float(np.mean(win_rates)), 4) if win_rates else None,
        "avg_daily_return": round(float(np.mean(avg_rets)), 4) if avg_rets else None,
    }


def run_analysis(
    backtest_path: Path = BACKTEST_JSON,
    output_json: Path = DEFAULT_OUTPUT_JSON,
    output_md: Path = DEFAULT_OUTPUT_MD,
) -> dict[str, Any]:
    import tushare as ts

    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise ValueError("TUSHARE_TOKEN not set in environment")
    ts.set_token(token)
    pro = ts.pro_api()

    backtest = _load_backtest_results(backtest_path)

    all_dates: set[str] = set()
    profile_data: dict[str, list[dict[str, Any]]] = {}
    for profile_name, profile_content in backtest.items():
        if not isinstance(profile_content, dict):
            continue
        selected_list = profile_content.get("selected", [])
        if not isinstance(selected_list, list):
            continue
        profile_data[profile_name] = selected_list
        for entry in selected_list:
            d = str(entry.get("date", ""))
            if d:
                all_dates.add(d)

    if not all_dates:
        raise ValueError("No trade dates found in backtest results")

    sorted_dates = sorted(all_dates)
    start_date = sorted_dates[0]
    end_date = sorted_dates[-1]

    print(f"Loading index data for regime classification: {start_date} ~ {end_date}")
    index_df = _fetch_index_data(pro, start_date, end_date)
    if index_df.empty:
        raise ValueError("Failed to load index data for regime classification")

    regime_map: dict[str, dict[str, Any]] = {}
    for d in sorted_dates:
        regime_map[d] = _classify_regime(index_df, d)
        print(f"  {d}: regime={regime_map[d]['regime']} breadth_proxy={regime_map[d]['breadth_proxy']} daily_return={regime_map[d]['daily_return']}")

    results_by_profile: dict[str, dict[str, Any]] = {}

    for profile_name, selected_list in profile_data.items():
        print(f"\nAnalyzing profile: {profile_name}")

        day_records: list[dict[str, Any]] = []

        for entry in selected_list:
            trade_date = str(entry.get("date", ""))
            tickers = entry.get("tickers", [])
            n_selected = entry.get("n", 0)
            win_rate = entry.get("win_rate")
            avg_ret = entry.get("avg_ret")

            if not trade_date or not tickers:
                continue

            regime_info = regime_map.get(trade_date, {"regime": "unknown"})

            print(f"  Fetching forward returns for {trade_date} ({len(tickers)} tickers, regime={regime_info['regime']})...")
            forward_returns = _fetch_forward_high_returns(pro, tickers, trade_date, holding_days=HOLDING_DAYS)

            evaluable = {k: v for k, v in forward_returns.items() if v.get("max_high_return") is not None}
            hit_count = sum(1 for v in evaluable.values() if v.get("hit_15pct"))
            max_returns = [v["max_high_return"] for v in evaluable.values() if v.get("max_high_return") is not None]

            day_record = {
                "trade_date": trade_date,
                "regime": regime_info["regime"],
                "breadth_proxy": regime_info.get("breadth_proxy"),
                "daily_return": regime_info.get("daily_return"),
                "n_selected": n_selected,
                "n_evaluable": len(evaluable),
                "hit_15pct_count": hit_count,
                "hit_15pct_rate": round(hit_count / len(evaluable), 4) if evaluable else None,
                "mean_max_high_return": round(float(np.mean(max_returns)), 4) if max_returns else None,
                "win_rate": win_rate,
                "avg_ret": avg_ret,
            }
            day_records.append(day_record)

            if evaluable:
                print(f"    15% hit rate: {day_record['hit_15pct_rate']} ({hit_count}/{len(evaluable)}), mean max return: {day_record['mean_max_high_return']}")

        regime_groups: dict[str, list[dict[str, Any]]] = {}
        for rec in day_records:
            regime = rec["regime"]
            regime_groups.setdefault(regime, []).append(rec)

        overall_stats = _compute_regime_stats(day_records)
        regime_stats = {regime: _compute_regime_stats(records) for regime, records in regime_groups.items()}

        tradeable_regimes = {"normal_trade", "aggressive_trade"}
        tradeable_records = [r for r in day_records if r["regime"] in tradeable_regimes]
        tradeable_stats = _compute_regime_stats(tradeable_records)

        results_by_profile[profile_name] = {
            "overall": overall_stats,
            "by_regime": regime_stats,
            "tradeable_only": tradeable_stats,
            "daily_records": day_records,
            "regime_gate_impact": {
                "overall_hit_15pct_rate": overall_stats.get("hit_15pct_rate"),
                "tradeable_hit_15pct_rate": tradeable_stats.get("hit_15pct_rate"),
                "hit_rate_improvement": round(
                    (tradeable_stats.get("hit_15pct_rate") or 0) - (overall_stats.get("hit_15pct_rate") or 0),
                    4,
                ),
                "overall_mean_max_return": overall_stats.get("mean_max_high_return"),
                "tradeable_mean_max_return": tradeable_stats.get("mean_max_high_return"),
                "days_filtered": len(day_records) - len(tradeable_records),
                "tradeable_day_count": len(tradeable_records),
                "passes_55pct_target": (tradeable_stats.get("hit_15pct_rate") or 0) >= TARGET_HIT_RATE,
            },
        }

    output = {
        "generated_at": datetime.now().isoformat(),
        "analysis_period": f"{start_date} ~ {end_date}",
        "target_hit_rate": TARGET_HIT_RATE,
        "target_return": TARGET_RETURN,
        "holding_days": HOLDING_DAYS,
        "profiles": results_by_profile,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {output_json}")

    md = render_markdown(output)
    with open(output_md, "w") as f:
        f.write(md)
    print(f"Markdown report saved to {output_md}")

    return output


def render_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# BTST Regime Gate x 15% Hit Rate Cross-Analysis",
        "",
        f"- **Analysis Period**: {data['analysis_period']}",
        f"- **Target**: {data['target_hit_rate']*100:.0f}% hit rate for {data['target_return']*100:.0f}%+ gain within {data['holding_days']} days",
        f"- **Generated**: {data['generated_at']}",
        "",
    ]

    for profile_name, profile_result in data.get("profiles", {}).items():
        lines.append(f"## Profile: {profile_name}")
        lines.append("")

        impact = profile_result.get("regime_gate_impact", {})
        overall = profile_result.get("overall", {})
        tradeable = profile_result.get("tradeable_only", {})
        by_regime = profile_result.get("by_regime", {})

        lines.append("### Regime Gate Impact Summary")
        lines.append("")
        lines.append("| Metric | Overall | Tradeable Days Only | Improvement |")
        lines.append("|--------|---------|-------------------|-------------|")
        lines.append(f"| 15% Hit Rate | {overall.get('hit_15pct_rate', 'N/A')} | {tradeable.get('hit_15pct_rate', 'N/A')} | {impact.get('hit_rate_improvement', 'N/A')} |")
        lines.append(f"| Mean Max High Return | {overall.get('mean_max_high_return', 'N/A')} | {tradeable.get('mean_max_high_return', 'N/A')} | - |")
        lines.append(f"| Day Count | {overall.get('day_count', 0)} | {tradeable.get('day_count', 0)} | {impact.get('days_filtered', 0)} filtered |")
        lines.append(f"| Avg Daily Win Rate | {overall.get('avg_daily_win_rate', 'N/A')} | {tradeable.get('avg_daily_win_rate', 'N/A')} | - |")
        lines.append(f"| Avg Daily Return | {overall.get('avg_daily_return', 'N/A')} | {tradeable.get('avg_daily_return', 'N/A')} | - |")
        lines.append("")

        passes = impact.get("passes_55pct_target", False)
        lines.append(f"**Passes 55% Target**: {'✅ YES' if passes else '❌ NO'}")
        lines.append("")

        lines.append("### Breakdown by Market Regime")
        lines.append("")
        lines.append("| Regime | Days | Selected | Evaluable | 15% Hit Rate | Mean Max Return | Avg Win Rate |")
        lines.append("|--------|------|----------|-----------|-------------|----------------|-------------|")
        for regime in ["aggressive_trade", "normal_trade", "shadow_only", "risk_off", "halt", "unknown"]:
            stats = by_regime.get(regime, {})
            if not stats or stats.get("day_count", 0) == 0:
                continue
            lines.append(f"| {regime} | {stats.get('day_count', 0)} | {stats.get('total_selected', 0)} | " f"{stats.get('total_evaluable', 0)} | {stats.get('hit_15pct_rate', 'N/A')} | " f"{stats.get('mean_max_high_return', 'N/A')} | {stats.get('avg_daily_win_rate', 'N/A')} |")
        lines.append("")

        lines.append("### Daily Detail")
        lines.append("")
        lines.append("| Date | Regime | Breadth | Daily Ret | Selected | 15% Hit | Mean Max Ret |")
        lines.append("|------|--------|---------|-----------|----------|---------|-------------|")
        for rec in profile_result.get("daily_records", []):
            lines.append(f"| {rec.get('trade_date', '')} | {rec.get('regime', '')} | " f"{rec.get('breadth_proxy', 'N/A')} | {rec.get('daily_return', 'N/A')} | " f"{rec.get('n_evaluable', 0)} | {rec.get('hit_15pct_rate', 'N/A')} | " f"{rec.get('mean_max_high_return', 'N/A')} |")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="BTST Regime Gate x 15% Hit Rate Cross-Analysis")
    parser.add_argument("--backtest-json", default=str(BACKTEST_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    run_analysis(
        backtest_path=Path(args.backtest_json),
        output_json=Path(args.output_json),
        output_md=Path(args.output_md),
    )


if __name__ == "__main__":
    main()
