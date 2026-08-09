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

import numpy as np
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
    """板块质量评分 (2026-08-09 Q3 用 factor_audit median 主判据重新校准).

    全 universe 审计口径 (exec-adjusted, T+10):
      688/60x:   mean +0.26% WR 42.9%   ← 三点微优
      002/300:   mean -0.26% WR 42.2%
      → 两者 Wilson CI 重叠 = 打平, 无区分度. board 真实区分度全在 0.0 vs 非零.
      000/001:   mean -0.62% WR 40.9%   ← 显著最差 (board 区分度来源)

    Q3 决策 (q3_board_merge_ab, 池内 n=12302, split-half 跨窗稳健):
      0.95/1.0 是无区分度刻度, 合并消除. 方向选「降」(002/300 1.0→0.95) 而非「升」:
      降挡出 823 票 E[r]=-1.067% 的负 EV 边缘票 (其他分量弱、靠 board 满值勉强入池),
      入池 mean +0.69%→+0.90% / 胜率 +0.3pp / rank IC +0.0449→+0.0460;
      升则放入 1160 票 E[r]=-0.13% 负 EV. 降是保护性 (缩小入池、挡出亏票), 符合北极星.
    """
    if ticker.startswith(("002", "300", "301")):
        return 0.95  # Q3: 旧 1.0, 与 688 合并 (审计口径打平); 降方向挡出负 EV 边缘票
    if ticker.startswith(("688", "60")):
        return 0.95  # 科创/沪主 (审计口径三点微优, 与中小创打平)
    return 0.0  # 深市主板 000/001 (审计显著最差)


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


def _compute_low_vol_score(prices: pd.DataFrame, trigger_idx: int) -> float:
    """低波动因子评分 (0~1) — 2026-08-09 新增 (geometry-of-alpha Q6, 双重计权的本质解).

    第一性原理: 审计器的正交性问责发现 position_score (Donchian 下半区) 与条件4
    池过滤 pre_runup≤8% 高度同源 (ρ=-0.756) — 「防追高」方向被双重计权, position
    是 pre_runup 的复印件. 池内 A/B (q6_double_count_ab, n=12049) 证明把 position
    换成与 pre_runup 正交的低波动轴, 池内 rank IC 从 +0.0298 升到 +0.0463 (+55%),
    且换血方向正确 (放入组 E[r]+0.48% > 挡出组 +0.16%).

    与既有 position_score 的本质区别: position 测「价位高低」(与 pre_runup 同源),
    low_vol 测「波动率高低」(池内独立风险轴). 波动率与「涨幅」在池内近乎无关
    (ρ=+0.177), 是真正的新信息而非复印件.

    计算: 涨停前 20 日已实现波动率 (pct_change 日收益的截面口径, 不含涨停日本身),
    低波动 = 弹簧压紧的连续度量 (是 squeeze 0/1 开关的连续版, 同时回答了 Q5).
    用 rv20 直接映射到 [0,1] (锚定池内实测分布, 见 q6 报告; 桶按 low_vol_score 升序,
    Q0=最低分=最高波, Q4=最高分=最低波, E[r] 自 Q0 −0.71% 单调升至 Q4 +0.93%):
      rv20 <= 1.5%   → 1.0   (最低波, 最高分侧, E[r] 最优的连续低波区)
      rv20 >= 4.5%   → 0.0   (最高波, 最低分侧, 区分度最差)
      中间线性过渡. 数据不足 (<10 个有效日收益) 回退 0.5 中性 (与同族回退一致).
    """
    if "pct_change" not in prices.columns:
        return 0.5
    try:
        pct = pd.to_numeric(prices["pct_change"], errors="coerce").values
        window = pct[max(0, trigger_idx - 20):trigger_idx]  # 不含涨停日
        # 滤非有限值 (NaN 与 ±inf): 仅 isnan 会让 inf 漏进 np.std → NaN → 比较全 False →
        # return NaN → min(1.0, NaN)=1.0 把 NaN 洗成满分过闸 (对抗审查发现). 与同列消费方
        # chained_return_pct 的 math.isfinite 一致.
        window = window[np.isfinite(window)]
        if len(window) < 10:
            return 0.5
        rv20 = float(np.std(window))  # 日收益波动率, 百分点量纲 (pct_change 已是 %)
        lo, hi = 1.5, 4.5
        if rv20 <= lo:
            return 1.0
        if rv20 >= hi:
            return 0.0
        return round(1.0 - (rv20 - lo) / (hi - lo), 5)
    except Exception:
        return 0.5


def _compute_volume_score(prices: pd.DataFrame, trigger_idx: int) -> float:
    """成交量因子评分 (0~1) — 2026-08-09 连续重标定 (factor_audit Q2).

    旧实现是 2026-07 小样本的离散阶梯 (1.0-1.2x→1.0 称"最佳" 61.4% 胜率), 全量复核
    (factor_audit, n=17994) 发现 0.9/1.0 映射倒挂 — 给 1.0 的桶实测胜率不高于给 0.9 的.
    细桶 + split-half 跨窗证据 (T+1 open -> T+10 close, execution-adjusted):
      <0.5x:      WR 33-41% E[r] 负   (极度缩量, 跨窗一致差)     → 0.0
      0.5-0.7x:   WR ~42%            (缩量, 偏弱)                → 0.4
      0.7-2.0x:   WR 43-45% E[r]+0.1~0.6% (温和放量=最佳平台)    → 1.0
      2.0-3.0x:   WR ~43%            (放量, 尚可)                → 0.6
      >=3.0x:     WR 38% E[r] 负     (过度换手, 跨窗一致差)      → 0.2
    连续 volume_ratio 直接映射 (中抬两端的倒 U), 消除旧阶梯 0.8-1.0x 被低估的倒挂.
    采纳前已过 strength_formula_ab A/B: rank IC Δ+0.0092, 换血方向正确, 秩相关 0.94.
    见 data/reports/q2_volume_recalib_formula_ab.json.

    第一性原理 (不变):
    - A 股涨停本质是多空博弈锁定: 缩量涨停 ≠ 弱势 (可以是筹码锁定)
    - 温和放量 (0.7-2.0x) = 刚好够 drive price up 但不过度换手 = 最优
    - 过度放量 (>=3.0x) = 抛压大/换手过高 → 后续回撤风险高
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
            return 0.0  # 极度缩量, 跨窗一致差
        if ratio < 0.7:
            return 0.4  # 缩量偏弱
        if ratio < 2.0:
            return 1.0  # 温和放量最佳平台 (0.7-2.0x)
        if ratio < 3.0:
            return 0.6  # 放量尚可
        return 0.2  # >=3.0x 过度换手, 跨窗一致差
    except Exception:
        return 0.5


def _compute_range_score(prices: pd.DataFrame, trigger_idx: int) -> float:
    """盘中振幅因子评分 (0~1) — 2026-08-09 新增 (新一轮因子挖掘).

    第一性原理: 现有 strength 分量 (board/low_vol/squeeze/volume) 全描述「涨停前」
    状态, range 描述「封板过程本身」——涨停日的盘中振幅 (high-low)/prev_close. 它是
    事件的正交时间帧 (与 6 个现有分量 |ρ|<0.10, 有效维 +1 整轴), 全 universe 审计
    单因子 IC +0.0622 为全场最高 (强于 low_vol +0.0437 / squeeze +0.0236 等).

    倒 U 经济意义 (exec-adjusted, median 主判据, 21232 信号日):
      range<4%    一字锁死板: 全天封死, 次日买不到/追高反转  (median −4.42%)   → 0.2
      4-6%        偏锁死, 偏弱                               (median −2.98%)   → 0.4
      6-11%       健康博弈, 多空充分换手, 封板有质量          (median −1.62%, WR 44%) → 1.0  甜区
      11-14%      偏振荡, 偏弱                               (median −2.80%)   → 0.4
      >=14%       盘中崩: 封板过程剧烈振荡, 主力分歧/出逃     (median −5.71%, WR 37.3%) → 0.2

    采纳前已过 range_factor_ab 池内 A/B (n=12302): 加为第 5 分量 (0.20×5) rank IC
    +0.04595→+0.06278 (+37%), split-half 两半同升, top10% +0.99%→+1.31%, 门槛换血
    放入 +0.51%/挡出 −0.12% (北极星方向). 归因排除重分权混淆 (rank IC 尺度不变,
    增益全来自 range 进 sum). 见 data/reports/range_factor_decision_pack_2026-08-09.md.

    数据不足 (无 high/low/close 列 / 无前收 / 非有限值 / hi<lo 数据错) 回退 0.5 中性
    (与同族 _compute_low_vol_score 回退一致). 阈值是数据驱动常量, 将定期 factor_audit
    保质期复跑 (同 streak/volume 教训: 因子会过期).
    """
    if prices is None or trigger_idx < 1 or trigger_idx >= len(prices):
        return 0.5
    try:
        if "high" not in prices.columns or "low" not in prices.columns or "close" not in prices.columns:
            return 0.5
        high = pd.to_numeric(prices["high"], errors="coerce").values
        low = pd.to_numeric(prices["low"], errors="coerce").values
        close = pd.to_numeric(prices["close"], errors="coerce").values
        prev_c = close[trigger_idx - 1]
        hi, lo = high[trigger_idx], low[trigger_idx]
        # 滤非有限值 (NaN/±inf) — 与 _compute_low_vol_score 同族纪律, 防 inf 漏进比较.
        if not (math.isfinite(prev_c) and math.isfinite(hi) and math.isfinite(lo)):
            return 0.5
        if prev_c <= 0 or hi < lo:
            return 0.5
        r = (hi - lo) / prev_c
        if r < 0.04:
            return 0.2  # 一字锁死板: 买不到/追高反转 (median −4.42%)
        if r < 0.06:
            return 0.4
        if r < 0.11:
            return 1.0  # 甜区 [0.06,0.11): median −1.62%, WR ~44%
        if r < 0.14:
            return 0.4
        return 0.2  # 盘中崩: median −5.71% 最差
    except Exception:
        return 0.5


def _compute_limit_up_streak(prices: pd.DataFrame, trigger_idx: int, limit_up_pct: float) -> int:
    """计算截至 trigger_idx 的连续涨停天数 (连板数, 含 trigger 日本身).

    2026-08-08 复核后仅作 metadata 观测, 不再进 trigger_strength: 当初的
    streak_bonus=0.04 (7/19, 凭 9497 样本 2连板 WR48.0% > 首板 45.5%) 在全量复核
    (1442 票/21232 信号日/至 2026-08-07) 下双口径反转 (2连板 WR 39.0% vs 首板 43.3%),
    因子前提不再成立, bonus 已移除. 见 data/reports/streak_factor_revalidation.json.

    Args:
        prices: 单 ticker 价格 DataFrame (需含 pct_change 列)
        trigger_idx: 涨停日 positional index
        limit_up_pct: 板块涨停阈值 (pct 下限, 如 9.5/19.5; 由 limit_up_pct_for_ticker 给)

    Returns:
        连续涨停天数 (含 trigger 日; 首板=1)。数据不足/异常保守返回 1。
    """
    if prices is None or "pct_change" not in prices.columns:
        return 1
    try:
        pcts = prices["pct_change"].astype(float).values
        if trigger_idx < 0 or trigger_idx >= len(pcts):
            return 1
        streak = 1
        k = trigger_idx - 1
        while k >= 0:
            try:
                prior_pct = float(pcts[k])
            except (TypeError, ValueError):
                break
            if math.isnan(prior_pct) or prior_pct < limit_up_pct:
                break
            streak += 1
            k -= 1
        return streak
    except Exception:
        return 1


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

        # trigger_strength: 5 因子等权 alpha ranker (0.20 each) + 能量耦合 bonus.
        #   board:    002/300 61.1% vs 000/001 44.9% (n=1212, 626 票全 universe 回测)
        #   low_vol:  20日已实现波动率 (低波=弹簧压紧) — 池内独立正交轴 (geometry Q6)
        #   squeeze:  波动率压缩(弹簧压紧) vs 未压缩 — 弱正向; Q6 后其信息多被 low_vol 连续轴吸收, 暂保留待复核
        #   volume:   成交量比率 (温和放量佳, 极端量差; 连续倒U重标定, 见 Q2)
        #   range:    涨停日盘中振幅 (倒U; 封板过程质量) — 正交新维度, 单因子 IC 全场最高 (新一轮挖掘)
        # 能量耦合: squeeze + low_vol 同时满值 = 完整弹簧释放, 给 0.08 bonus.
        #
        # position_score 已移出 strength (2026-08-09, geometry-of-alpha Q6, 本质解):
        # 正交性问责发现它与条件4 池过滤 pre_runup≤8% 高度同源 (ρ=-0.756) — 「防追高」
        # 被双重计权, position 是 pre_runup 的复印件. 池内 A/B (q6_double_count_ab,
        # n=12049) 证把 position 换成与 pre_runup 正交的低波动轴, 池内 rank IC 从
        # +0.0298 升到 +0.0463 (+55%), 换血方向正确 (放入 +0.48% > 挡出 +0.16%).
        # 降权 (position 0.15) 治不好本 — 复印件调小声还是复印件, 换血反而更差.
        # position_score 保留在 metadata 供观测. 见 data/reports/q6_double_count_formula_ab.json.
        #
        # weekday_score 已移出 strength (2026-08-09, factor_audit 复核): 当初凭 n=133 单
        # regime 样本「Wed-Fri 78% vs Mon-Tue 51%」给 0.20 权重, 但全量复核 (21232 信号日)
        # 无区分度 — E[r] 反号、跨窗 H1 反 H2 正 (方向漂移)、Wilson 未分离. 0.20 权重在
        # 稀释真信号 → 移除, 剩 4 项归一化到 0.25 (保持刻度与 _MIN_TRIGGER_STRENGTH 不变).
        # weekday_score 保留在 metadata 供观测 (day-of-week 效应是真信息, 只是不配权重).
        # 见 data/reports/factor_audit_decision_pack_2026-08-08.md (Q1).

        trade_dow = _dt.strptime(trade_date, "%Y%m%d").weekday()  # 0=Mon
        weekday_score = 1.0 if trade_dow >= 2 else 0.0  # Wed-Fri=1, Mon-Tue=0 (仅观测, 不进 strength)
        board_score = _board_quality_score(ticker)  # 002/300=1.0, 688/60x=0.95, 000=0.0

        # 低波动因子: 用涨停前 20 日 pct_change 计算 (池内正交轴, 替换 position 进 strength)
        low_vol_score = _compute_low_vol_score(prices, trigger_idx)
        # 位置因子: 用涨停前 5 日 close 计算 — 已移出 strength (Q6), 保留供 metadata 观测
        # 压缩因子: 用涨停前 20 日 high/low/close 计算 (需要更长的历史窗口)
        pre_window = prices.iloc[ref_idx : trigger_idx]  # 5 个交易日的 OHLCV
        position_score, squeeze_score = _compute_trend_vol_scores(pre_window, prices, trigger_idx)

        # ★ 成交量因子: 2026-08-09 连续重标定 (factor_audit Q2), 倒 U 映射,
        # 证据见 _compute_volume_score docstring. 旧 2026-07 阶梯的细分数据已被
        # 全量复核证伪 (0.9/1.0 倒挂), 不再赘述.
        volume_score = _compute_volume_score(prices, trigger_idx)

        # 盘中振幅因子 (2026-08-09 新一轮挖掘): 涨停日 (high-low)/prev_close 倒 U 映射.
        # 正交新维度 (封板过程 vs 涨停前状态), 池内 A/B rank IC +37%. 见 _compute_range_score.
        range_score = _compute_range_score(prices, trigger_idx)

        # energy_bonus 仅在 squeeze=1.0 且 low_vol 满值 (完整弹簧释放) 时发放 (2026-08-09 Q6).
        # 原为 position+squeeze 同时=1.0; position 移出 strength 后, 改挂 squeeze + low_vol
        # (池内正交的压缩轴 + 压缩确认 = 完整弹簧释放). Finding A (2026-07-16): 旧阈值
        # ``>= 0.5`` 把 squeeze=0.5 (中性/数据不足) 也算"完整弹簧释放" → 发未赚取的 +0.08,
        # 与 docstring 矛盾, 并把阶段证据不足的票抬过 _MIN_TRIGGER_STRENGTH. 故 squeeze
        # 须满值 1.0; low_vol 连续值须 >= 0.75 (低波区, 与「压紧」语义一致).
        energy_bonus = 0.08 if squeeze_score >= 1.0 and low_vol_score >= 0.75 else 0.0

        # ★ 连板数因子 — 2026-08-08 因子复核后移除 streak_bonus.
        # 当初 (7/19, commit 8c7fc078) 凭 9497 涨停样本「2连板 WR48.0% > 首板 45.5%」给
        # streak==2 +0.04. 但全量复核 (1442 票 / 21232 涨停信号日 / 至 2026-08-07) 双口径
        # 同向反转: 2连板 WR 39.0% vs 首板 43.3% (−4.25pp raw / −4.47pp exec-adjusted),
        # E[r] 同步走弱. 因子前提不再成立 → streak 不再进 trigger_strength, 仅作 metadata
        # 暴露供 dogfood 观测. 见 data/reports/streak_factor_revalidation.json.
        streak = _compute_limit_up_streak(prices, trigger_idx, limit_up_pct)
        # weekday/position 已移出 (见上方注释); 5 项各 0.20 + energy_bonus (2026-08-09
        # range 进 strength, 4→5 分量重新归一化 0.25→0.20, _MIN_TRIGGER_STRENGTH 刻度不变).
        strength = min(
            1.0,
            0.20 * board_score
            + 0.20 * low_vol_score
            + 0.20 * squeeze_score
            + 0.20 * volume_score
            + 0.20 * range_score
            + energy_bonus,
        )

        return DetectionResult(
            hit=True,
            ticker=ticker,
            trade_date=trade_date,
            trigger_strength=strength,
            invalidation_condition=invalidation,
            metadata={
                "pct_change": pct_change,
                "limit_up_streak": streak,
                "main_net_inflow": today_flow,
                "industry_pct": industry_pct,
                "pre_5d_runup_pct": pre_runup_pct,
                "limit_up_pct_threshold": limit_up_pct,
                "range_low": range_low,
                "range_based_stop_pct": round(range_based_stop_pct, 4),
                # 分量导出契约 (2026-08-09, geometry-of-alpha): 5 个 strength 分量 +
                # energy_bonus 全部归一到 [0,1]. 归一化是点积可比性的前提 — 审计器在
                # 同一测度下对分量取内积/相关, 未归一的量纲会让点积失真. 未来新增分量
                # 必须同样归一到 [0,1] 才允许进 metadata 与 trigger_strength.
                "weekday_score": weekday_score,
                "board_score": board_score,
                "position_score": position_score,  # 已移出 strength (Q6), 仅观测
                "low_vol_score": low_vol_score,    # Q6 新进 strength 的正交轴
                "squeeze_score": squeeze_score,
                "volume_score": volume_score,
                "range_score": range_score,        # 新一轮挖掘: 封板过程正交新维度
                "energy_bonus": energy_bonus,
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
