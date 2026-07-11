"""Setup-2: 超跌反弹 + 资金回流 (Oversold Bounce)。

触发条件 (设计文档 §3.1 Setup-2):
1. 近 30 日跌幅 > 20%
2. 近 3 日主力净流入转正 (累计 > 0)
3. 今日量比 > 1.5 (放量)

失效条件: 价格跌破近 30 日最低点 × 0.95 (破位)

危机专属 setup — 直接填补"危机 0 BUY"的痛。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.screening.offensive.data.fund_flow_store import FundFlowRecord
from src.screening.offensive.setups.base import DetectionResult, Setup

_LOOKBACK_DROP_DAYS = 30
_DROP_THRESHOLD = -20.0  # 30 日跌幅 > 20%
_FLOW_LOOKBACK_DAYS = 3
_VOLUME_RATIO_MIN = 1.5


class OversoldBounceSetup(Setup):
    name = "oversold_bounce"
    natural_horizon = 5  # 反弹持续 3-7 日, 中位 5

    def detect(self, ticker: str, trade_date: str, context: dict[str, Any]) -> DetectionResult:
        prices: pd.DataFrame | None = context.get("prices")
        if prices is None or len(prices) == 0:
            return self._miss(ticker, trade_date)

        prices = prices.copy()
        prices = prices.reset_index(drop=True)  # Bug fix: 保证 index=0..n-1, 防 iloc 混用
        prices["date_str"] = pd.to_datetime(prices["date"]).dt.strftime("%Y%m%d")
        trigger_rows = prices[prices["date_str"] == trade_date]
        if len(trigger_rows) == 0:
            return self._miss(ticker, trade_date)
        trigger_idx = trigger_rows.index[0]

        # 条件 1: 近 30 日跌幅 > 20%
        ref_idx = trigger_idx - _LOOKBACK_DROP_DAYS
        if ref_idx < 0:
            return self._miss(ticker, trade_date)
        ref_close = float(prices.iloc[ref_idx]["close"])
        trigger_close = float(prices.iloc[trigger_idx]["close"])
        drop_pct = (trigger_close / ref_close - 1) * 100
        if drop_pct > _DROP_THRESHOLD:  # drop_pct 是负数, > -20 表示没跌够
            return self._miss(ticker, trade_date)

        # 条件 2: 近 3 日 (含触发日) 主力净流入累计 > 0 (转正)
        # Bug fix: 原来窗口 range(1, N+1) = T-1/T-2/T-3 (排除触发日 T). 对于反弹 setup,
        # 触发日当天的资金流入是最强反转信号, 排除它会让"今天大幅流出但前3天微流入"的
        # 股票通过过滤. 改为 range(0, N) = T/T-1/T-2, 含触发日.
        records: list[FundFlowRecord] = context.get("fund_flow_records") or []
        recent_dates = set()
        for i in range(0, _FLOW_LOOKBACK_DAYS):  # 0=触发日, 1=T-1, 2=T-2
            if trigger_idx - i >= 0:
                recent_dates.add(prices.iloc[trigger_idx - i]["date_str"])
        recent_flow = sum(r.main_net_inflow for r in records if r.date in recent_dates and r.date <= trade_date)
        if recent_flow <= 0:
            return self._miss(ticker, trade_date)

        # 条件 3: 今日量比 > 1.5
        # 诚实降级 (NS-17 同类): price_cache 无 volume 列时, 条件3 无法判定.
        # 此前静默跳过 → OversoldBounce 退化为 2 条件 setup 却无标识, Phase 0 据此
        # 判 PASS 但那是残缺版. 现在: hit 仍 True (条件1+2 满足), 但 degraded=True
        # 让下游披露. 数据接入后复跑, 命中集/分布可能变 (条件3 会进一步过滤).
        degraded = False
        degradation_reason = ""
        volume_col = "volume" if "volume" in prices.columns else None
        if volume_col is None:
            degraded = True
            degradation_reason = "条件3 (量比>1.5) 跳过: price_cache 无 volume 列"
        elif trigger_idx < 20:
            degraded = True
            degradation_reason = f"条件3 (量比>1.5) 跳过: 历史数据不足 (trigger_idx={trigger_idx} < 20)"
        else:
            today_vol = float(prices.iloc[trigger_idx][volume_col])
            avg_vol = float(prices.iloc[trigger_idx - 20 : trigger_idx][volume_col].mean())
            vol_ratio = today_vol / avg_vol if avg_vol > 0 else 0
            if vol_ratio < _VOLUME_RATIO_MIN:
                return self._miss(ticker, trade_date)

        # 失效条件: 跌破 30 日低点 × 0.95
        low_30 = float(prices.iloc[ref_idx : trigger_idx + 1]["low"].min()) if "low" in prices.columns else trigger_close * 0.9
        invalidation = f"价格跌破 {low_30 * 0.95:.2f} (30 日低点 -5%)"

        # trigger_strength: 跌幅越深 + 资金回流越强 → 强度越高
        depth_score = min(1.0, abs(drop_pct) / 40.0)  # -40% 满分
        flow_score = min(1.0, recent_flow / 10_000_000)  # 1000 万满分
        strength = depth_score * 0.6 + flow_score * 0.4

        return DetectionResult(
            hit=True,
            ticker=ticker,
            trade_date=trade_date,
            trigger_strength=strength,
            invalidation_condition=invalidation,
            metadata={
                "drop_30d_pct": drop_pct,
                "recent_flow_3d": recent_flow,
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
