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
    natural_horizon = 3  # 涨停动量爆发短, T+1~T+3 最强

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
            hit=False, ticker=ticker, trade_date=trade_date,
            trigger_strength=0.0, invalidation_condition="",
        )
