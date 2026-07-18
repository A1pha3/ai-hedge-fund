"""Setup-1: 涨停突破 (BTST Breakout)。

触发条件 (设计文档 §3.1 + 数据驱动改进):
1. 今日涨停 (pct_change ≥ 板块自适应阈值)
2. 主力净流入 > 过去 20 日均值
3. 所属行业当日涨幅 > 2% (板块效应)
4. 涨停前 5 日累计涨幅 ≤ 8% (防追高; 数据驱动条件, 见下方注释)

失效条件: 价格跌破触发日收盘 × 0.92 (即 -8% 止损线)

条件 4 的数据依据 (全池回测 2020-2026, 8825 涨停样本, T+5 execution-adjusted):
  ⚠ 下表基于旧口径 close[T]/close[T-5] (含涨停日本身), 已不描述现行过滤器
  (现行为 close[T-1]/close[T-5], 不含涨停日), 仅留作历史参考.
  涨停前5日涨幅  样本   E[r]    胜率   凸性
  ≤ 0%          553   +4.17%   61%   —     (超跌后首板, 最强)
  ≤ 5%         1299   +3.20%   60%   2.17
  ≤ 10%        2651   +2.59%   56%   1.90  (旧阈值, 样本量大 + trigger_strength ranker 补偿深度信号)
  无过滤        8825   +1.36%   49%   1.33  (不达凸性 1.5 门槛)
单调递减: 涨停前涨幅越大后续越弱. 2026-07 回测后从 10% 收紧到 8%
(_PRE_RUNUP_MAX_PCT): 8-10% 区间 52.4%/+3.10% 弱于池均值, <8% 58%+ 明显优于 >8% 53%.

依赖:
- context["prices"]: 单 ticker 价格 DataFrame
- context["fund_flow_records"]: list[FundFlowRecord] (含历史)
- context["industry_day_pct"]: float, 行业当日涨幅
"""

from __future__ import annotations

import math
from datetime import datetime as _dt
from typing import Any

import pandas as pd

from src.screening.offensive.data.fund_flow_store import FundFlowRecord
from src.screening.offensive.price_returns import chained_return_pct
from src.screening.offensive.setups.base import DetectionResult, Setup

# 涨停判定: 板块自适应 (主板 9.5%, 科创/创业 19.5%, 北交所 29.0%).
# 旧固定 9.5% 会把科创/创业的非涨停大涨日误判为涨停 → setup 语义被污染.
# 通过 limit_up_pct_for_ticker(ticker) 按板块取阈值, 保持「涨停突破」语义.
_INDUSTRY_PCT_MIN = 2.0
_MAIN_FLOW_LOOKBACK_DAYS = 20
_MAIN_FLOW_MIN_HISTORY_DAYS = 5  # 资金流历史 < 此值时无法判均值, degraded=True
_PRE_RUNUP_LOOKBACK_DAYS = 5
_PRE_RUNUP_MAX_PCT = 8.0  # 回测验证 (2026-07, 626 只 A 股): 8-10% 区间 52.4%/+3.10% 弱于池均值; <8% 58%+ 明显优于 >8% 53%


def _board_quality_score(ticker: str) -> float:
    """板块质量评分 (2026-07-12 用当前过滤器链重新校准).

    旧值基于 133 笔真实成交 (不同过滤器). 新值基于 626 只 A 股全 universe 回测
    (8% 涨停前涨幅门控 + 成交量过滤 + T+10, n=1212):
      688/60x:  WR=64.5% E[r]=+9.03%  → 0.95 (实际最优, 旧 0.7 低估)
      002/300:  WR=61.1% E[r]=+6.55%  → 1.0  (仍强, 保留)
      000/001:  WR=44.9% E[r]=+1.54%  → 0.0  (最差, 不变)
    """
    if ticker.startswith(("002", "300", "301")):
        return 1.0
    if ticker.startswith(("688", "60")):
        return 0.95  # 旧 0.7 低估: 实测 64.5% WR / +9.03% (全 universe 最优)
    return 0.0  # SZmain(000/001) 及其他


# ATR 中位数阈值: 用于区分低波动 vs 高波动.
# 回测验证: 5日 ATR/close 中位数 ≈ 3.0%, 低波动组 (<3%) win=82.8% vs 高波动组 win=60.0%
_ATR_MEDIAN_THRESHOLD = 3.0  # 百分比
# 波动率压缩阈值: 近 3 日 ATR / 前 17 日 ATR < 此值 = 压缩 (弹簧压紧).
# 文档 §1: "波动率从极低状态向极高水平回归" — 不是绝对低, 而是"被压缩"的过程.
_SQUEEZE_RATIO_THRESHOLD = 0.8  # 近期波动率缩减 ≥20% = 能量积蓄


def _compute_trend_vol_scores(
    pre_window: pd.DataFrame,
    prices: pd.DataFrame,
    trigger_idx: int,
) -> tuple[float, float]:
    """计算涨停前的区间位置分数和波动率压缩分数.

    第一性原理: 交易的不是价格当前位置, 而是能量从积蓄到爆发的瞬时过程.
    - position_score: 价格在 5 日区间中的位置 (Donchian 分位)
    - squeeze_score: 波动率是否处于"被压缩"状态 (能量积蓄)

    Args:
        pre_window: 涨停前 5 个交易日的 OHLCV (用于 Donchian 位置)
        prices: 完整价格 DataFrame (~120 行, 用于波动率压缩计算)
        trigger_idx: 涨停日在 prices 中的 positional index

    Returns:
        (position_score, squeeze_score), 各为 0.0 或 1.0.

    position_score: Donchian 分位 < 0.5 → 1.0 (从低位拉起的新鲜涨停=好)
    squeeze_score: 近 3 日 ATR / 前 17 日 ATR < 0.8 → 1.0 (波动率压缩=能量积蓄=爆发力强)

    数据不足时返回 (0.5, 0.5) (中性).
    """
    if pre_window is None or len(pre_window) < 3:
        return 0.5, 0.5

    try:
        # === 位置因子 (Donchian 分位): 用 pre_window 5 日 close ===
        closes = pre_window["close"].astype(float).values
        high_5d = max(closes)
        low_5d = min(closes)
        range_span = high_5d - low_5d
        if range_span > 0:
            range_pct = (closes[-1] - low_5d) / range_span
        else:
            range_pct = 0.5
        position_score = 1.0 if range_pct < 0.5 else 0.0  # 下半区=新鲜突破

        # === 波动率压缩因子: 用 prices 涨停前 20 日 high/low/close ===
        squeeze_score = _compute_squeeze_score(prices, trigger_idx)

        return position_score, squeeze_score
    except Exception:
        return 0.5, 0.5


def _compute_squeeze_score(prices: pd.DataFrame, trigger_idx: int) -> float:
    """计算波动率压缩分数.

    第一性原理: "弹簧被压紧" = 近期波动率 (ATR) 显著小于前期波动率.
    压缩后的涨停 = 弹簧释放 = 爆发力强.

    计算: 取涨停前 20 日 (不含涨停日本身) 的日内波幅 (high-low)/close.
    - recent_atr = 最近 3 日的平均波幅
    - prior_atr = 之前 17 日的平均波幅
    - squeeze_ratio = recent_atr / prior_atr (< 1.0 = 压缩中)

    数据不足 (<20 日) 时回退到旧的绝对低波动逻辑 (ATR < 3%).
    """
    lookback_end = trigger_idx  # 不含涨停日本身
    lookback_start = max(0, lookback_end - 20)

    if lookback_end - lookback_start < 8:
        # 数据不足, 回退到旧的绝对低波动逻辑
        return _compute_absolute_low_vol_score(prices, lookback_end)

    try:
        window = prices.iloc[lookback_start:lookback_end]
        if not all(c in window.columns for c in ["high", "low", "close"]):
            return 0.5

        highs = window["high"].astype(float).values
        lows = window["low"].astype(float).values
        closes = window["close"].astype(float).values
        daily_ranges = [(h - l) / c * 100 for h, l, c in zip(highs, lows, closes) if c > 0]

        if len(daily_ranges) < 8:
            return _compute_absolute_low_vol_score(prices, lookback_end)

        # 近 3 日 vs 前 N 日
        recent = daily_ranges[-3:] if len(daily_ranges) >= 3 else daily_ranges[-1:]
        prior = daily_ranges[:-3] if len(daily_ranges) > 3 else daily_ranges
        recent_atr = sum(recent) / len(recent)
        prior_atr = sum(prior) / len(prior)

        if prior_atr <= 0:
            return 0.5

        squeeze_ratio = recent_atr / prior_atr
        return 1.0 if squeeze_ratio < _SQUEEZE_RATIO_THRESHOLD else 0.0
    except Exception:
        return 0.5


def _compute_absolute_low_vol_score(prices: pd.DataFrame, trigger_idx: int) -> float:
    """回退: 涨停前 5 日绝对 ATR < 3% → 1.0 (旧的 low_vol_score 逻辑)."""
    start = max(0, trigger_idx - 5)
    window = prices.iloc[start:trigger_idx]
    if len(window) < 3:
        return 0.5
    try:
        closes = window["close"].astype(float).values
        if not all(c in window.columns for c in ["high", "low"]):
            return 0.5
        highs = window["high"].astype(float).values
        lows = window["low"].astype(float).values
        daily_ranges = [(h - l) / c * 100 for h, l, c in zip(highs, lows, closes) if c > 0]
        avg_atr = sum(daily_ranges) / len(daily_ranges) if daily_ranges else _ATR_MEDIAN_THRESHOLD
        return 1.0 if avg_atr < _ATR_MEDIAN_THRESHOLD else 0.0
    except Exception:
        return 0.5


def _compute_volume_score(prices: pd.DataFrame, trigger_idx: int) -> float:
    """成交量因子评分 (0~1), 基于 2409 涨停样本历史回测 (2026-07, 626 只).

    回测结论:
      1.0-1.2x: 61.4% 胜率 / +6.05%  → 1.0 (最佳成交量区)
      0.8-1.0x: 58.2% / +5.38%        → 0.9
      1.2-1.5x: 59.8% / +5.84%        → 0.9
      1.5-2.0x: 55.6% / +4.91%        → 0.4 (噪讯区, 无增量 α)
      0.5-0.8x: 49.7% / +2.82%        → 0.0 (回避区, 无 α)
      <0.5 或 >5.0: 样本不足          → 0.5 (中性)

    第一性原理 (修正后):
    - A 股涨停本质是多空博弈锁定: 缩量涨停 ≠ 弱势 (可以是筹码锁定)
    - 放量涨停可能代表抛压大 / 筹码换手 → 后续回撤风险高
    - 最优量 = 温和放量 (刚好够 drive price up 但不过度换手)
    """
    if prices is None or len(prices) < 2:
        return 0.5
    try:
        if "volume" not in prices.columns:
            return 0.5
        volumes = prices["volume"].astype(float).values
        if trigger_idx < 0 or trigger_idx >= len(volumes):
            return 0.5
        today_vol = float(volumes[trigger_idx])
        if today_vol <= 0:
            return 0.5
        lookback_start = max(0, trigger_idx - 20)
        prior_volumes = volumes[lookback_start:trigger_idx]
        if len(prior_volumes) < 5:
            return 0.5
        avg_vol = sum(prior_volumes) / len(prior_volumes)
        if avg_vol <= 0:
            return 0.5
        ratio = today_vol / avg_vol

        if ratio < 0.5:
            return 0.4  # 极低量, 略弱
        if ratio < 0.8:
            return 0.0  # 回避区: 49.7% 胜率 ≈ 无 α
        if ratio < 1.0:
            return 0.9  # 优质区: 58.2%
        if ratio < 1.2:
            return 1.0  # 最佳区: 61.4%
        if ratio < 1.5:
            return 0.9  # 优质区: 59.8%
        if ratio < 2.0:
            return 0.4  # 噪讯区: 55.6%, 收益摊薄
        return 0.3  # >2.0x: 换手率过高, 55.1% 但收益显著偏低 (+2.83%)
    except Exception:
        return 0.5


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
        from src.tools.ashare_board_utils import (
            limit_up_cap_pct_for_ticker,
            limit_up_pct_for_ticker,
        )

        limit_up_pct = limit_up_pct_for_ticker(ticker)
        limit_up_cap = limit_up_cap_pct_for_ticker(ticker)
        # NaN guard: `NaN or 0.0` 返回 NaN (NaN 是 truthy), `NaN < threshold` 永远 False.
        # 先 float() 再 math.isnan() 统一处理, 数据缺失时保守 miss.
        try:
            pct_change = float(trigger_row.get("pct_change", 0.0))
        except (TypeError, ValueError):
            pct_change = float("nan")
        if math.isnan(pct_change) or pct_change < limit_up_pct:
            return self._miss(ticker, trade_date)
        # 上界护栏: pct 超过交易所真实板帽 (如 +10.5%/+20.5%/+30.5%) 的交易日是
        # 无涨跌幅限制日 (长期停牌复牌/新股上市初期), 不是涨停 — 案例 000792
        # 2021-08-10 停牌 15 个月复牌 +306%, pre_runup≈0 会被当成"超跌后首板"误放.
        if pct_change > limit_up_cap + 0.5:
            return self._miss(ticker, trade_date)

        # 条件 2: 主力净流入 > 20 日均值.
        # 注意: 涨停日主力净流出是常态 (~59% 的涨停日 main_net_inflow<0, 封板时大单
        # 卖出打进买单队列), 因此这里有意不含 >0 检查 — 裸信号分组回测未见 E[r] 受损
        # (负流入组 E[r] 不弱于正流入组). 不要把 ">0" 当作冗余加回来而不跑分组回测.
        records: list[FundFlowRecord] = context.get("fund_flow_records") or []
        today_flow = next((r.main_net_inflow for r in records if r.date == trade_date), None)
        # Bug fix (2026-07-12): NaN guard — fund_flow_store 已修复 `or 0.0` 对 NaN 无效,
        # 但防御性检查 today_flow 的 NaN (上游数据源可能未修复或第三方传入异常数据).
        if today_flow is None or math.isnan(today_flow):
            return self._miss(ticker, trade_date)
        historical = [r.main_net_inflow for r in records if r.date < trade_date and not math.isnan(r.main_net_inflow)]
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
        # Bug fix (2026-07-12): industry_day_pct=None 表示行业数据管道断裂 (缓存缺失/import 失败).
        # 旧实现: daily_action 把加载失败映射为 industry_pct=0.0 → 0.0 < 2.0 → 全部 BTST miss.
        # 用户看到"今日无信号", 实际是数据管道断了. 修正: None 时跳过行业过滤但标 degraded,
        # 与资金流浅数据降级同模式. 有行业数据 (含 0.0) 时正常过滤.
        industry_pct: float | None = None
        industry_pct_raw = context.get("industry_day_pct")
        if industry_pct_raw is None:
            # 数据缺失: 不过滤但标记残缺, 让 operator 知道行业条件未验证
            if not degraded:
                degraded = True
                degradation_reason = "条件3 (行业涨幅≥2%) 跳过: 行业数据未加载"
        else:
            try:
                industry_pct = float(industry_pct_raw)
            except (TypeError, ValueError):
                industry_pct = float("nan")
            if industry_pct != industry_pct or industry_pct < _INDUSTRY_PCT_MIN:  # NaN guard
                return self._miss(ticker, trade_date)

        # 条件 4: 涨停前窗口累计涨幅 ≤ 8% (防追高, close[T-1]/close[T-5]).
        # 收益用 pct_change 链式复合 (price_returns.chained_return_pct): 原始价比值
        # 跨除权缺口会产生幻影 — 如 688167 20260615 raw5=-19.9% (幻影"超跌后首板"),
        # 实际调整后 +15.9% (追高). 链条断裂 (NaN) 时保守 miss, 与数据不足同语义.
        ref_idx = trigger_idx - _PRE_RUNUP_LOOKBACK_DAYS
        pre_trigger_idx = trigger_idx - 1
        if ref_idx < 0 or pre_trigger_idx < 0:
            return self._miss(ticker, trade_date)  # 数据不足, 保守 miss
        pre_runup_pct = chained_return_pct(prices, ref_idx, pre_trigger_idx)
        if pre_runup_pct is None or pre_runup_pct > _PRE_RUNUP_MAX_PCT:
            return self._miss(ticker, trade_date)

        # 止损: 基于盘整区底部 (物理结构自适应).
        # 文档 §3.3: "初始止损设在 LL 下方一点" — 止损锚定压缩区间底部, 不是固定 -8%.
        # 压缩越紧 → range_low 越接近 trigger_close → 止损越窄 → 盈亏比天然更大.
        trigger_close = float(trigger_row["close"])
        range_lookback = max(0, trigger_idx - 20)
        range_low = float(prices.iloc[range_lookback:trigger_idx]["low"].min())
        # 除权日前的 low 在旧价格尺度上, 可能高于现价 → 钳到现价之下,
        # 防止输出"跌破 X (X > 现价)"的 nonsense 止损披露 (仅影响披露, 不进 P&L).
        range_low = min(range_low, trigger_close)
        range_based_stop_pct = (range_low / trigger_close - 1)  # 负数, 如 -0.05 = -5%
        # 安全下限: 止损不超过 -8% (如果盘整区底部太远, 用 -8% 兜底)
        if range_based_stop_pct < -0.08:
            range_based_stop_pct = -0.08
        stop_price = trigger_close * (1 + range_based_stop_pct)
        invalidation = f"价格跌破 {stop_price:.2f} (盘整区底部 {range_low:.2f}, {range_based_stop_pct:+.1%})"

        # trigger_strength: 5 因子等权 alpha ranker + 能量耦合 bonus.
        #   weekday:  Wed-Fri 78% win vs Mon-Tue 51% (n=133, 2026 单 regime 样本, 待跨周期验证)
        #   board:    002/300 61.1% vs 000/001 44.9% (n=1212, 626 票全 universe 回测)
        #   position: Donchian 下半区(新鲜突破) vs 上半区(追高)
        #   squeeze:  波动率压缩(弹簧压紧) vs 未压缩
        #   volume:   成交量比率 (0.8-1.5x 最佳, 0.5-0.8x 最差 ≈ 49.7% 无 α)
        # 能量耦合: position+squeeze 同时=1 = 完整弹簧释放, 给 0.08 bonus.

        trade_dow = _dt.strptime(trade_date, "%Y%m%d").weekday()  # 0=Mon
        weekday_score = 1.0 if trade_dow >= 2 else 0.0  # Wed-Fri=1, Mon-Tue=0
        board_score = _board_quality_score(ticker)  # 002/300=1.0, 688/60x=0.95, 000=0.0

        # 位置因子: 用涨停前 5 日 close 计算
        # 压缩因子: 用涨停前 20 日 high/low/close 计算 (需要更长的历史窗口)
        pre_window = prices.iloc[ref_idx : trigger_idx]  # 5 个交易日的 OHLCV
        position_score, squeeze_score = _compute_trend_vol_scores(pre_window, prices, trigger_idx)

        # ★ 成交量因子 (2026-07 历史回测: 626 只股票, 2409 涨停样本实测):
        # 1.0-1.2x: 61.4% 胜率 / +6.05% ← 最佳
        # 0.8-1.0x: 58.2% / +5.38%  ← 优质
        # 1.2-1.5x: 59.8% / +5.84%  ← 优质
        # 1.5-2.0x: 55.6% / +4.91%  ← 中性偏弱 (噪音)
        # 0.5-0.8x: 49.7% / +2.82%  ← 回避区 (无 α)
        # <0.5 或 >5.0: 样本少, 中性处理
        volume_score = _compute_volume_score(prices, trigger_idx)

        # energy_bonus 仅在 position+squeeze 同时=1.0 (完整弹簧释放) 时发放.
        # Finding A (2026-07-16): 旧阈值 ``>= 0.5`` 把 squeeze/position=0.5
        # (中性/数据不足: _compute_trend_vol_scores 与 _compute_squeeze_score 在
        # 数据不足/前段波动率为 0 时回退 0.5) 也算"完整弹簧释放" → 发未赚取的 +0.08,
        # 与 docstring "同时=1" 矛盾, 并把阶段证据不足的票抬过 _MIN_TRIGGER_STRENGTH.
        # 两 score 取值集合 {0.0, 0.5, 1.0}; ``>= 1.0`` == "都到满正值" 即文档意图.
        energy_bonus = 0.08 if position_score >= 1.0 and squeeze_score >= 1.0 else 0.0
        strength = min(1.0, 0.20 * weekday_score + 0.20 * board_score + 0.20 * position_score + 0.20 * squeeze_score + 0.20 * volume_score + energy_bonus)

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
                "range_low": range_low,
                "range_based_stop_pct": round(range_based_stop_pct, 4),
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
