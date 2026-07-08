"""Setup-3: 板块轮动早期 (Sector Rotation Early)。

触发条件 (设计文档 §3.1 Setup-3):
1. 所属行业指数近 2 日涨幅 > 3%
2. 该票是行业龙头但本次未涨 (今日涨幅 < 行业涨幅 × 0.5)
3. 行业资金净流入 > 0 (板块整体在吸金)

失效条件: 行业指数跌破触发日收盘 × 0.97 (轮动失败)
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.screening.offensive.setups.base import DetectionResult, Setup

_INDUSTRY_2D_GAIN_MIN = 3.0  # 行业 2 日涨幅 > 3%
_LEADER_LAG_RATIO = 0.5  # 龙头今日涨幅 < 行业涨幅 × 0.5


class SectorRotationSetup(Setup):
    name = "sector_rotation"
    natural_horizon = 10  # 轮动慢, T+10~T+20 主升

    def detect(self, ticker: str, trade_date: str, context: dict[str, Any]) -> DetectionResult:
        # 行业 2 日涨幅 + 行业资金流 + 该票今日涨幅 都从 context 传入
        industry_2d_pct = float(context.get("industry_2d_pct", 0.0) or 0.0)
        industry_flow = float(context.get("industry_net_flow", 0.0) or 0.0)
        flow_provided = context.get("industry_net_flow") is not None and context.get("industry_net_flow") != 0.0
        stock_today_pct = float(context.get("stock_today_pct", 0.0) or 0.0)

        # 条件 1: 行业 2 日涨幅 > 3%
        if industry_2d_pct < _INDUSTRY_2D_GAIN_MIN:
            return self._miss(ticker, trade_date)

        # 条件 2: 龙头未涨 (今日涨幅 < 行业涨幅 × 0.5)
        if stock_today_pct >= industry_2d_pct * _LEADER_LAG_RATIO:
            return self._miss(ticker, trade_date)

        # 条件 3: 行业资金净流入 > 0
        # 诚实降级 (NS-17 同类): industry_net_flow 当前无真实数据源 (tushare 无行业资金流端点,
        # ftshare eastmoney_sector_flow 未接入). 此前条件3 是硬 miss (0.0 <= 0 → 永远 miss),
        # 导致 SectorRotation 全量 0 hits. 现在: 数据缺失时跳过条件3 但标 degraded=True,
        # 让 setup 退化为 2 条件版 (行业动量 + 龙头滞后), 命中集可参与 Phase 0. 数据接入后复跑.
        degraded = False
        degradation_reason = ""
        if flow_provided:
            if industry_flow <= 0:
                return self._miss(ticker, trade_date)
        else:
            degraded = True
            degradation_reason = "条件3 (行业资金净流入>0) 跳过: industry_net_flow 无真实数据源"

        prices: pd.DataFrame | None = context.get("prices")
        trigger_close = float(prices.iloc[-1]["close"]) if prices is not None and len(prices) > 0 else 0.0
        invalidation = f"行业指数跌破触发日水平 × 0.97 (轮动失败)"

        # 强度: 行业涨幅越大 + 龙头越滞后 → 越强
        strength = min(1.0, industry_2d_pct / 8.0) * 0.6 + min(1.0, max(0, industry_2d_pct - stock_today_pct) / 5.0) * 0.4

        return DetectionResult(
            hit=True,
            ticker=ticker,
            trade_date=trade_date,
            trigger_strength=strength,
            invalidation_condition=invalidation,
            metadata={
                "industry_2d_pct": industry_2d_pct,
                "stock_today_pct": stock_today_pct,
                "industry_net_flow": industry_flow,
            },
            degraded=degraded,
            degradation_reason=degradation_reason,
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
