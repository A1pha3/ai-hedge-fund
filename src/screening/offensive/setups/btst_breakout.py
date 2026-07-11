"""Setup-1: 涨停突破 (BTST Breakout)。

触发条件 (设计文档 §3.1 + 数据驱动改进):
1. 今日涨停 (pct_change ≥ 板块自适应阈值)
2. 主力净流入 > 过去 20 日均值
3. 所属行业当日涨幅 > 2% (板块效应)
4. 涨停前 5 日累计涨幅 ≤ 10% (防追高; 数据驱动条件, 见下方注释)

失效条件: 价格跌破触发日收盘 × 0.92 (即 -8% 止损线)

条件 4 的数据依据 (全池回测 2020-2026, 8825 涨停样本, T+5 execution-adjusted):
  涨停前5日涨幅  样本   E[r]    胜率   凸性
  ≤ 0%          553   +4.17%   61%   —     (超跌后首板, 最强)
  ≤ 5%         1299   +3.20%   60%   2.17
  ≤ 10%        2651   +2.59%   56%   1.90  ← 选此阈值 (样本量大 + trigger_strength ranker 补偿深度信号)
  无过滤        8825   +1.36%   49%   1.33  (不达凸性 1.5 门槛)
单调递减: 涨停前涨幅越大后续越弱. ≤10% 保留有基本面支撑的涨停 (非追高),
trigger_strength 的 trend 因子进一步区分 ≤0% (最强) 和 0-10% 的差异.

依赖:
- context["prices"]: 单 ticker 价格 DataFrame
- context["fund_flow_records"]: list[FundFlowRecord] (含历史)
- context["industry_day_pct"]: float, 行业当日涨幅
"""

from __future__ import annotations

from datetime import datetime as _dt
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


# ATR 中位数阈值: 用于区分低波动 vs 高波动.
# 回测验证: 5日 ATR/close 中位数 ≈ 3.0%, 低波动组 (<3%) win=82.8% vs 高波动组 win=60.0%
_ATR_MEDIAN_THRESHOLD = 3.0  # 百分比


def _compute_trend_vol_scores(pre_window: pd.DataFrame) -> tuple[float, float]:
    """计算涨停前 5 日的趋势分数和低波动分数.

    Args:
        pre_window: 涨停前 5 个交易日的 OHLCV DataFrame (含 close/high/low 列)

    Returns:
        (trend_score, low_vol_score), 各为 0.0 或 1.0.
        - trend_score: 5 日 close 线性回归斜率 > 0 → 1.0 (上行趋势涨停更强)
        - low_vol_score: 5 日 ATR/close < 阈值 → 1.0 (低波动涨停更强)

    数据不足时返回 (0.5, 0.5) (中性).
    """
    if pre_window is None or len(pre_window) < 3:
        return 0.5, 0.5

    try:
        closes = pre_window["close"].astype(float).values
        # 趋势: 简化线性回归斜率 (首尾差/天数), >0 则上行
        slope_pct = (closes[-1] / closes[0] - 1) * 100 if closes[0] > 0 else 0
        trend_score = 1.0 if slope_pct > 0 else 0.0

        # 波动率: 5 日 ATR (简化版 = mean of daily (high-low)/close)
        if "high" in pre_window.columns and "low" in pre_window.columns:
            highs = pre_window["high"].astype(float).values
            lows = pre_window["low"].astype(float).values
            daily_ranges = [(h - l) / c * 100 for h, l, c in zip(highs, lows, closes) if c > 0]
            avg_atr = sum(daily_ranges) / len(daily_ranges) if daily_ranges else _ATR_MEDIAN_THRESHOLD
            low_vol_score = 1.0 if avg_atr < _ATR_MEDIAN_THRESHOLD else 0.0
        else:
            low_vol_score = 0.5

        return trend_score, low_vol_score
    except Exception:
        return 0.5, 0.5


class BtstBreakoutSetup(Setup):
    name = "btst_breakout"
    # 数据驱动的 natural_horizon (全池回测 2020-2026, 新 detect 含条件4, execution-adjusted):
    #   T+10 凸性 1.81 胜率 54.2% E[r] +3.38% (n=1762, IC=0.126) ← known_distributions 口径
    #   T+20 (未单测, 但 E[r] 单调递增 — 慢均值回归特性)
    # 条件4 (涨停前5日涨幅≤5%) 加入后, BTST 从弱 setup (旧 cv=1.33/win=49%) 升级为
    # 强 setup (cv=1.81/win=54%), 与 OversoldBounce 的超跌反转逻辑同构.
    natural_horizon = 8  # T+8 mean 最优 (+6.33% vs T+10 +5.76%), 避免 T+9/T+10 收益回吐

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

        # 条件 4: 涨停前 5 日累计涨幅 ≤ 10% (防追高; trigger_strength 的 trend 因子进一步区分).
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
        # trigger_strength: 4 因子 alpha ranker (每个因子都有回测数据支撑, 权重均分).
        # 回测验证 (n=88, 有 price_cache 的 BTST 交易):
        #   weekday:  Wed-Fri 78% win vs Mon-Tue 51% (+27pp)
        #   board:    002/300 83% vs SZmain 45% (+38pp)
        #   trend:    5日上行 79.5% vs 下行 61.4% (+18pp)
        #   low_vol:  低ATR 82.8% vs 高ATR 60.0% (+23pp)

        trade_dow = _dt.strptime(trade_date, "%Y%m%d").weekday()  # 0=Mon
        weekday_score = 1.0 if trade_dow >= 2 else 0.0  # Wed-Fri=1, Mon-Tue=0
        board_score = _board_quality_score(ticker)  # 002/300=1.0, 688/60x=0.7, 000=0.0

        # 趋势+波动率因子: 用涨停前 5 日价格数据计算
        pre_window = prices.iloc[ref_idx : trigger_idx]  # 5 个交易日的 OHLCV
        trend_score, low_vol_score = _compute_trend_vol_scores(pre_window)

        strength = 0.25 * weekday_score + 0.25 * board_score + 0.25 * trend_score + 0.25 * low_vol_score

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
