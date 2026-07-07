"""Setup-1: 涨停突破 (BTST Breakout)。

触发条件 (设计文档 §3.1):
1. 今日涨停 (pct_change ≥ 9.5%)
2. 主力净流入 > 0 且 > 过去 20 日均值
3. 所属行业当日涨幅 > 2% (板块效应)

失效条件: 价格跌破触发日收盘 × 0.92 (即 -8% 止损线)

依赖:
- context["prices"]: 单 ticker 价格 DataFrame
- context["fund_flow_records"]: list[FundFlowRecord] (含历史)
- context["industry_day_pct"]: float, 行业当日涨幅
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.screening.offensive.data.fund_flow_store import FundFlowRecord
from src.screening.offensive.setups.base import DetectionResult, Setup

_LIMIT_UP_PCT = 9.5
_INDUSTRY_PCT_MIN = 2.0
_MAIN_FLOW_LOOKBACK_DAYS = 20


class BtstBreakoutSetup(Setup):
    name = "btst_breakout"
    # 数据驱动的 natural_horizon (全池回测 2020-2026, execution-adjusted):
    #   T+1  胜率 46.1% 均值 -0.17% 凸性 0.91 (负凸性, 弱)
    #   T+3  胜率 48.5% 均值 +0.53% 凸性 1.17 (凸性 < 1.5 准入门槛)
    #   T+5  胜率 47.8% 均值 +1.14% 凸性 1.29
    #   T+10 胜率 50.6% 均值 +2.57% 凸性 1.53 ← 首次过准入门槛 (convexity≥1.5, winrate≥50%)
    #   T+20 胜率 49.0% 均值 +4.47% 凸性 1.70
    # 文档 §3.1 原假设"T+1~T+3 最强"被数据推翻: BTST 的 edge 在长周期, 不是短周期.
    # T+10 也是 known_distributions.BTST_BREAKOUT_T10 + --daily-action 的口径.
    natural_horizon = 10

    def detect(self, ticker: str, trade_date: str, context: dict[str, Any]) -> DetectionResult:
        prices: pd.DataFrame | None = context.get("prices")
        if prices is None or len(prices) == 0:
            return self._miss(ticker, trade_date)

        prices = prices.copy()
        prices["date_str"] = pd.to_datetime(prices["date"]).dt.strftime("%Y%m%d")
        trigger_rows = prices[prices["date_str"] == trade_date]
        if len(trigger_rows) == 0:
            return self._miss(ticker, trade_date)
        trigger_idx = trigger_rows.index[0]
        trigger_row = prices.iloc[trigger_idx]

        # 条件 1: 今日涨停
        pct_change = float(trigger_row.get("pct_change", 0.0) or 0.0)
        if pct_change < _LIMIT_UP_PCT:
            return self._miss(ticker, trade_date)

        # 条件 2: 主力净流入 > 0 且 > 20 日均值
        records: list[FundFlowRecord] = context.get("fund_flow_records") or []
        today_flow = next((r.main_net_inflow for r in records if r.date == trade_date), None)
        if today_flow is None or today_flow <= 0:
            return self._miss(ticker, trade_date)
        historical = [r.main_net_inflow for r in records if r.date < trade_date]
        if len(historical) >= 5:  # 至少 5 日历史才有均值意义
            lookback = historical[-_MAIN_FLOW_LOOKBACK_DAYS:]
            hist_mean = sum(lookback) / len(lookback)
            if today_flow <= hist_mean:
                return self._miss(ticker, trade_date)

        # 条件 3: 行业板块效应
        industry_pct = float(context.get("industry_day_pct") or 0.0)
        if industry_pct < _INDUSTRY_PCT_MIN:
            return self._miss(ticker, trade_date)

        trigger_close = float(trigger_row["close"])
        invalidation = f"价格跌破 {trigger_close * 0.92:.2f} (-8% 止损线)"
        # trigger_strength: 标准化的涨停强度 + 主力流入强度
        strength = min(1.0, (pct_change / 10.0) * 0.5 + min(today_flow / 5_000_000, 1.0) * 0.5)

        return DetectionResult(
            hit=True,
            ticker=ticker,
            trade_date=trade_date,
            trigger_strength=strength,
            invalidation_condition=invalidation,
            metadata={
                "pct_change": pct_change,
                "main_net_inflow": today_flow,
                "industry_pct": industry_pct,
            },
        )

    @staticmethod
    def _miss(ticker: str, trade_date: str) -> DetectionResult:
        return DetectionResult(
            hit=False,
            ticker=ticker,
            trade_date=trade_date,
            trigger_strength=0.0,
            invalidation_condition="",
        )
