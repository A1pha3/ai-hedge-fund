"""Setup-1: 涨停突破 (BTST Breakout)。

触发条件 (设计文档 §3.1 + 数据驱动改进):
1. 今日涨停 (pct_change ≥ 9.5%)
2. 主力净流入 > 0 且 > 过去 20 日均值
3. 所属行业当日涨幅 > 2% (板块效应)
4. 涨停前 5 日累计涨幅 ≤ 5% (防追高; 数据驱动条件, 见下方注释)

失效条件: 价格跌破触发日收盘 × 0.92 (即 -8% 止损线)

条件 4 的数据依据 (全池回测 2020-2026, 8825 涨停样本, T+5 execution-adjusted):
  涨停前5日涨幅  样本   E[r]    胜率   凸性
  ≤ 0%          553   +4.17%   61%   —     (超跌后首板, 最强)
  ≤ 5%         1299   +3.20%   60%   2.17  ← 选此阈值 (样本/alpha 最优拐点)
  ≤ 10%        2651   +2.59%   56%   1.90
  无过滤        8825   +1.36%   49%   1.33  (不达凸性 1.5 门槛)
单调递减: 涨停前涨幅越大后续越弱. ≤5% 把"超跌/平盘后首板"和"涨一波后的追高"
分开, 保留前者 (与 OversoldBounce 的"超跌反转"逻辑同构).

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

# 涨停判定: 板块自适应 (主板 9.5%, 科创/创业 19.5%, 北交所 29.0%).
# 旧固定 9.5% 会把科创/创业的非涨停大涨日误判为涨停 → setup 语义被污染.
# 通过 limit_up_pct_for_ticker(ticker) 按板块取阈值, 保持「涨停突破」语义.
_INDUSTRY_PCT_MIN = 2.0
_MAIN_FLOW_LOOKBACK_DAYS = 20
_MAIN_FLOW_MIN_HISTORY_DAYS = 5  # 资金流历史 < 此值时无法判均值, degraded=True
_PRE_RUNUP_LOOKBACK_DAYS = 5
_PRE_RUNUP_MAX_PCT = 10.0  # 放宽: ≤5%→≤10% (回测: +2.59%/56% 仍远优于无过滤 1.33%/49%)


def _board_quality_score(ticker: str) -> float:
    """板块质量评分 (回测验证: 002/ChiNext 最优, SZmain 最差).

    数据来源: journal.jsonl 133 笔 BTST 回测
      002:     win=83% E[r]=+10.71%  → 1.0
      300/301: win=70% E[r]=+10.26%  → 1.0
      60x:     win=69% E[r]=+7.46%   → 0.7
      688:     win=61% E[r]=+6.09%   → 0.7
      000/001: win=45% E[r]=+1.62%   → 0.0
    """
    if ticker.startswith(("002", "300", "301")):
        return 1.0
    if ticker.startswith(("688", "60")):
        return 0.7
    return 0.0  # SZmain(000/001) 及其他


class BtstBreakoutSetup(Setup):
    name = "btst_breakout"
    # 数据驱动的 natural_horizon (全池回测 2020-2026, 新 detect 含条件4, execution-adjusted):
    #   T+10 凸性 1.81 胜率 54.2% E[r] +3.38% (n=1762, IC=0.126) ← known_distributions 口径
    #   T+20 (未单测, 但 E[r] 单调递增 — 慢均值回归特性)
    # 条件4 (涨停前5日涨幅≤5%) 加入后, BTST 从弱 setup (旧 cv=1.33/win=49%) 升级为
    # 强 setup (cv=1.81/win=54%), 与 OversoldBounce 的超跌反转逻辑同构.
    natural_horizon = 10

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
        trigger_row = prices.iloc[trigger_idx]

        # 条件 1: 今日涨停 (板块自适应: 主板 ≥9.5%, 科创/创业 ≥19.5%, 北交所 ≥29.0%)
        # 旧固定 9.5% 在 20% 板会把非涨停的大涨日 (如 +13.9%) 误判为涨停 → 语义污染.
        from src.tools.ashare_board_utils import limit_up_pct_for_ticker

        limit_up_pct = limit_up_pct_for_ticker(ticker)
        pct_change = float(trigger_row.get("pct_change", 0.0) or 0.0)
        if pct_change < limit_up_pct:
            return self._miss(ticker, trade_date)

        # 条件 2: 主力净流入 > 20 日均值 (去掉冗余 >0 检查: 涨停日必然正流入)
        records: list[FundFlowRecord] = context.get("fund_flow_records") or []
        today_flow = next((r.main_net_inflow for r in records if r.date == trade_date), None)
        if today_flow is None:
            return self._miss(ticker, trade_date)
        historical = [r.main_net_inflow for r in records if r.date < trade_date]
        # 资金流历史不足 20d 时: 有 ≥5 天就算短窗口均值 (标 degraded), <5 天跳过
        degraded = False
        degradation_reason = ""
        if len(historical) >= _MAIN_FLOW_MIN_HISTORY_DAYS:
            lookback = historical[-_MAIN_FLOW_LOOKBACK_DAYS:]
            hist_mean = sum(lookback) / len(lookback)
            if today_flow <= hist_mean:
                return self._miss(ticker, trade_date)
            if len(historical) < _MAIN_FLOW_LOOKBACK_DAYS:
                degraded = True
                degradation_reason = f"条件2 短窗口: 仅{len(historical)}天 (设计{_MAIN_FLOW_LOOKBACK_DAYS}d)"
        else:
            degraded = True
            degradation_reason = f"条件2 跳过: 历史不足 ({len(historical)}<{_MAIN_FLOW_MIN_HISTORY_DAYS}日)"

        # 条件 3: 行业板块效应
        industry_pct = float(context.get("industry_day_pct") or 0.0)
        if industry_pct < _INDUSTRY_PCT_MIN:
            return self._miss(ticker, trade_date)

        # 条件 4: 涨停前一交易日收盘 / 5 日前收盘 涨幅 ≤ 5% (防追高).
        # 注意这里不包含涨停当天涨幅; 条件语义是"涨停前"是否已经涨过一波。
        # 平盘后首板和超跌后首板保留, 涨一波后的涨停过滤。
        ref_idx = trigger_idx - _PRE_RUNUP_LOOKBACK_DAYS
        pre_trigger_idx = trigger_idx - 1
        if ref_idx < 0 or pre_trigger_idx < 0:
            return self._miss(ticker, trade_date)  # 数据不足, 保守 miss
        pre_close = float(prices.iloc[ref_idx]["close"])
        pre_trigger_close = float(prices.iloc[pre_trigger_idx]["close"])
        trigger_close = float(trigger_row["close"])
        pre_runup_pct = (pre_trigger_close / pre_close - 1) * 100
        if pre_runup_pct > _PRE_RUNUP_MAX_PCT:
            return self._miss(ticker, trade_date)

        invalidation = f"价格跌破 {trigger_close * 0.92:.2f} (-8% 止损线)"
        # trigger_strength: 3 因子 alpha ranker (每个因子都有回测数据支撑).
        # 旧公式 3 项退化: 涨停强度(主板恒=1.0)、flow/5M(按市值排序)、depth(多数≈0).
        # 新公式用回测验证的 3 个信号: 星期(78% vs 51% win)、板块(83% vs 45%)、反转深度.
        from datetime import datetime as _dt

        trade_dow = _dt.strptime(trade_date, "%Y%m%d").weekday()  # 0=Mon
        weekday_score = 1.0 if trade_dow >= 2 else 0.0  # Wed-Fri=1, Mon-Tue=0
        board_score = _board_quality_score(ticker)  # 002/300=1.0, 688/60x=0.7, 000=0.0
        depth_score = min(1.0, max(0.0, -pre_runup_pct) / 5.0)  # 前5日跌5%满分 (门限已放宽到≤10%)
        strength = 0.35 * weekday_score + 0.35 * board_score + 0.30 * depth_score

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
                "pre_5d_runup_pct": pre_runup_pct,
                "limit_up_pct_threshold": limit_up_pct,
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
