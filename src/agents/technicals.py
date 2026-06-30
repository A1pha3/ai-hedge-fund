"""Technical analysis agent.

Multi-strategy chart-based analysis: trend following, mean reversion, momentum,
volatility-regime, and statistical-arbitrage signals fused into a single
direction. Sub-scoring and Chinese-reasoning helpers live in
``technicals_reasoning_helpers``.
"""

import json
import math

import numpy as np
import pandas as pd
from langchain_core.messages import HumanMessage

from src.agents.technicals_reasoning_helpers import (
    _build_overall_signal_lines,
    _build_strategy_section_lines,
    _build_summary_lines,
)
from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import get_prices, prices_to_df
from src.utils.api_key import get_api_key_from_state
from src.utils.progress import progress

# ---------------------------------------------------------------------------
# Technical analysis constants (extracted from magic numbers in R20.8)
# ---------------------------------------------------------------------------

# Trend strategy: short / medium / long EMA windows
TREND_EMA_SHORT = 8
TREND_EMA_MEDIUM = 21
TREND_EMA_LONG = 55
TREND_ADX_PERIOD = 14

# Mean reversion strategy
MR_MA_WINDOW = 50
MR_RSI_FAST = 14
MR_RSI_SLOW = 28
MR_ZSCORE_BULL = -2
MR_ZSCORE_BEAR = 2
MR_ZSCORE_MAX = 4  # divisor that maps |z| to confidence ∈ [0, 1]
MR_PRICE_VS_BB_BULL = 0.2
MR_PRICE_VS_BB_BEAR = 0.8

# Momentum strategy
MOM_WINDOW_1M = 21
MOM_WINDOW_3M = 63
MOM_WINDOW_6M = 126
MOM_WEIGHT_1M = 0.4
MOM_WEIGHT_3M = 0.3
MOM_WEIGHT_6M = 0.3
# ALPHA-MOM.1: 阈值松绑 (2026-06-25 诊断驱动)
# 60日全universe回测显示 momentum dir=0 占比 53.7%, 但 +1 vs -1 T+1 差 +0.812% (因子有效)
# 主要压制因素: 量能确认 (1.0 太严, A股大量票日常量能<MA21) + 动量阈值 (5% 被加权稀释)
# 调整: 阈值 0.05→0.03, 量能确认 1.0→0.8 (保留语义但放宽)
MOM_THRESHOLD = 0.03
MOM_CONFIDENCE_SCALE = 5  # multiplier mapping momentum score to confidence
MOM_VOLUME_CONFIRM_RATIO = 0.8

# Volatility strategy
VOL_WINDOW = 21
VOL_REGIME_WINDOW = 63
VOL_ANNUALIZATION = 252  # trading days/year
VOL_LOW_THRESHOLD = 0.9  # B_narrow (C236): 0.8→0.9, shrink neutral band (53%→46% dir=0)
VOL_HIGH_THRESHOLD = 1.1  # B_narrow (C236): 1.2→1.1, shrink neutral band
VOL_Z_THRESHOLD = 1
VOL_CONFIDENCE_SCALE = 3

# Stat-arb strategy
STAT_ARB_WINDOW = 63
STAT_ARB_HURST_BULL = 0.4
STAT_ARB_SKEW_THRESHOLD = 1
STAT_ARB_HURST_SCALE = 2  # confidence = (0.5 - hurst) * SCALE

# Signal combination
SIGNAL_THRESHOLD = 0.2

# Neutral signal confidence
NEUTRAL_CONFIDENCE = 0.5


def safe_float(value, default=0.0):
    """
    Safely convert a value to float, handling NaN/Inf cases

    Args:
        value: The value to convert (can be pandas scalar, numpy value, etc.)
        default: Default value to return if the input is NaN/Inf or invalid

    Returns:
        float: The converted value or default if NaN/Inf/invalid
    """
    try:
        if pd.isna(value) or np.isnan(value):
            return default
        result = float(value)
        if not math.isfinite(result):
            return default
        return result
    except (ValueError, TypeError, OverflowError):
        return default


def safe_confidence(value, default=0.5):
    """Return a finite confidence score clamped to the [0, 1] range."""
    confidence = safe_float(value, default)
    if not math.isfinite(confidence):
        return default
    return max(0.0, min(confidence, 1.0))


def generate_chinese_reasoning(ticker: str, combined_signal: dict, strategy_signals: dict, weights: dict) -> str:
    """
    生成中文技术分析详细说明

    信号生成规则说明：

    1. 趋势跟踪策略 (Trend Following) - 权重25%
       - 使用EMA(8/21/55)多时间框架判断趋势方向
       - 短期趋势：EMA8 > EMA21 为上升趋势
       - 中期趋势：EMA21 > EMA55 为上升趋势
       - ADX > 25表示趋势较强，信号置信度更高
       - 信号规则：
         *  bullish: 短期和中期趋势均为上升
         *  bearish: 短期和中期趋势均为下降
         *  neutral: 趋势方向不一致

    2. 均值回归策略 (Mean Reversion) - 权重20%
       - 使用Z-Score判断价格偏离程度（Z-Score = (价格-50日均值)/50日标准差）
       - 结合布林带位置判断超买超卖
       - RSI(14/28)判断动量是否过度延伸
       - 信号规则 (NS-4 commit 023acd74 翻转: 短期 momentum 主导, 超卖票继续跌):
         *  bullish: Z-Score > +2 且 价格处于布林带上轨80%以上（超买, 动量延续看涨）
         *  bearish: Z-Score < -2 且 价格处于布林带下轨20%以内（超卖, 动量延续看跌）
         *  neutral: 其他情况

    3. 动量策略 (Momentum) - 权重25%
       - 计算1月/3月/6月价格动量（加权：40%/30%/30%）
       - 结合成交量动量确认（成交量 > 20日均量）
       - 信号规则：
         *  bullish: 动量得分 > 5% 且 成交量确认
         *  bearish: 动量得分 < -5% 且 成交量确认
         *  neutral: 其他情况

    4. 波动率策略 (Volatility) - 权重15%
       - 历史波动率 = 日收益率标准差 × √252
       - 波动率区间 = 当前波动率 / 63日平均波动率
       - 信号规则：
         *  bullish: 波动率区间 < 0.8 且 Z-Score < -1（低波动，可能扩张）
         *  bearish: 波动率区间 > 1.2 且 Z-Score > 1（高波动，可能收缩）
         *  neutral: 其他情况

    5. 统计套利策略 (Statistical Arbitrage) - 权重15%
       - Hurst指数判断时间序列特性（H < 0.5均值回归，H > 0.5趋势性）
       - 收益率分布偏度判断极端行情概率
       - 信号规则 (NS-4 commit 023acd74 翻转: 信号方向对齐 T+1):
         *  bullish: Hurst < 0.4 且 偏度 < -1（均值回归+左偏, 动量延续看涨）
         *  bearish: Hurst < 0.4 且 偏度 > 1（均值回归+右偏, 动量延续看跌）
         *  neutral: 其他情况

    综合信号计算：
    - 将各策略信号转换为数值（bullish=1, neutral=0, bearish=-1）
    - 加权求和：Σ(信号值 × 权重 × 置信度) / Σ(权重 × 置信度)
    - 最终得分 > 0.2 为 bullish，< -0.2 为 bearish，否则 neutral
    """
    final_signal = combined_signal["signal"]
    final_confidence = safe_confidence(combined_signal.get("confidence", 0.5)) * 100
    signal_cn = {"bullish": "看涨", "bearish": "看跌", "neutral": "中性"}
    lines = _build_overall_signal_lines(ticker, {"signal": final_signal, "confidence": final_confidence}, signal_cn)

    strategy_names = {"trend": "趋势跟踪", "mean_reversion": "均值回归", "momentum": "动量分析", "volatility": "波动率分析", "stat_arb": "统计套利"}

    for strategy_key, strategy_name in strategy_names.items():
        signal_data = strategy_signals.get(strategy_key, {})
        weight = weights.get(strategy_key, 0) * 100
        normalized_signal_data = {
            **signal_data,
            "confidence": safe_confidence(signal_data.get("confidence", 0.5)) * 100,
        }
        lines.extend(_build_strategy_section_lines(strategy_key, strategy_name, normalized_signal_data, weight, signal_cn))

    lines.extend(_build_summary_lines(final_signal, strategy_signals))

    return "\n".join(lines)


##### Technical Analyst #####
def technical_analyst_agent(state: AgentState, agent_id: str = "technical_analyst_agent"):
    """
    技术分析智能体 - 综合多策略技术分析系统

    该智能体结合5种经典交易策略，通过加权集成方法生成最终交易信号：
    1. 趋势跟踪 (Trend Following) - 权重25%: 使用EMA多时间框架和ADX判断趋势
    2. 均值回归 (Mean Reversion) - 权重20%: 使用Z-Score、布林带和RSI判断超买超卖
    3. 动量分析 (Momentum) - 权重25%: 使用多时间框架价格动量和成交量确认
    4. 波动率分析 (Volatility) - 权重15%: 基于波动率区间和ATR的交易策略
    5. 统计套利 (Statistical Arbitrage) - 权重15%: 使用Hurst指数和收益率分布特征

    信号生成规则详见 generate_chinese_reasoning 函数文档字符串
    """
    data = state["data"]
    start_date = data["start_date"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")
    # Initialize analysis for each ticker
    technical_analysis = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Analyzing price data")

        # Get the historical price data
        prices = get_prices(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key,
        )

        if not prices:
            progress.update_status(agent_id, ticker, "Failed: No price data found")
            technical_analysis[ticker] = {
                "signal": "neutral",
                "confidence": 0,
                "reasoning": {"error": "No price data available for technical analysis"},
            }
            continue

        # Convert prices to a DataFrame
        prices_df = prices_to_df(prices)

        progress.update_status(agent_id, ticker, "Calculating trend signals")
        trend_signals = calculate_trend_signals(prices_df)

        progress.update_status(agent_id, ticker, "Calculating mean reversion")
        mean_reversion_signals = calculate_mean_reversion_signals(prices_df)

        progress.update_status(agent_id, ticker, "Calculating momentum")
        momentum_signals = calculate_momentum_signals(prices_df)

        progress.update_status(agent_id, ticker, "Analyzing volatility")
        volatility_signals = calculate_volatility_signals(prices_df)

        progress.update_status(agent_id, ticker, "Statistical analysis")
        stat_arb_signals = calculate_stat_arb_signals(prices_df)

        # Combine all signals using a weighted ensemble approach
        strategy_weights = {
            "trend": 0.25,
            "mean_reversion": 0.20,
            "momentum": 0.25,
            "volatility": 0.15,
            "stat_arb": 0.15,
        }

        progress.update_status(agent_id, ticker, "Combining signals")
        combined_signal = weighted_signal_combination(
            {
                "trend": trend_signals,
                "mean_reversion": mean_reversion_signals,
                "momentum": momentum_signals,
                "volatility": volatility_signals,
                "stat_arb": stat_arb_signals,
            },
            strategy_weights,
        )

        # Prepare strategy signals for Chinese reasoning generation
        strategy_signals = {
            "trend": trend_signals,
            "mean_reversion": mean_reversion_signals,
            "momentum": momentum_signals,
            "volatility": volatility_signals,
            "stat_arb": stat_arb_signals,
        }

        # Generate Chinese detailed explanation
        chinese_reasoning = generate_chinese_reasoning(
            ticker=ticker,
            combined_signal=combined_signal,
            strategy_signals=strategy_signals,
            weights=strategy_weights,
        )

        # Generate detailed analysis report for this ticker
        technical_analysis[ticker] = {
            "signal": combined_signal["signal"],
            "confidence": round(safe_confidence(combined_signal.get("confidence", 0.5)) * 100),
            "reasoning": {
                "trend_following": {
                    "signal": trend_signals["signal"],
                    "confidence": round(safe_confidence(trend_signals.get("confidence", 0.5)) * 100),
                    "metrics": normalize_pandas(trend_signals["metrics"]),
                },
                "mean_reversion": {
                    "signal": mean_reversion_signals["signal"],
                    "confidence": round(safe_confidence(mean_reversion_signals.get("confidence", 0.5)) * 100),
                    "metrics": normalize_pandas(mean_reversion_signals["metrics"]),
                },
                "momentum": {
                    "signal": momentum_signals["signal"],
                    "confidence": round(safe_confidence(momentum_signals.get("confidence", 0.5)) * 100),
                    "metrics": normalize_pandas(momentum_signals["metrics"]),
                },
                "volatility": {
                    "signal": volatility_signals["signal"],
                    "confidence": round(safe_confidence(volatility_signals.get("confidence", 0.5)) * 100),
                    "metrics": normalize_pandas(volatility_signals["metrics"]),
                },
                "statistical_arbitrage": {
                    "signal": stat_arb_signals["signal"],
                    "confidence": round(safe_confidence(stat_arb_signals.get("confidence", 0.5)) * 100),
                    "metrics": normalize_pandas(stat_arb_signals["metrics"]),
                },
                "chinese_explanation": chinese_reasoning,
            },
        }
        progress.update_status(agent_id, ticker, "Done", analysis=json.dumps(technical_analysis, indent=4))

    # Create the technical analyst message
    message = HumanMessage(
        content=json.dumps(technical_analysis),
        name=agent_id,
    )

    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning(technical_analysis, "Technical Analyst")

    # Add the signal to the analyst_signals list
    state["data"]["analyst_signals"][agent_id] = technical_analysis

    progress.update_status(agent_id, None, "Done")

    return {
        "messages": state["messages"] + [message],
        "data": data,
    }


def calculate_trend_signals(prices_df):
    """
    Advanced trend following strategy using multiple timeframes and indicators
    """
    # Calculate EMAs for multiple timeframes
    ema_8 = calculate_ema(prices_df, TREND_EMA_SHORT)
    ema_21 = calculate_ema(prices_df, TREND_EMA_MEDIUM)
    ema_55 = calculate_ema(prices_df, TREND_EMA_LONG)

    # Calculate ADX for trend strength
    adx = calculate_adx(prices_df, TREND_ADX_PERIOD)

    # Determine trend direction and strength
    short_trend = ema_8 > ema_21
    medium_trend = ema_21 > ema_55

    # Combine signals with confidence weighting
    trend_strength = adx["adx"].iloc[-1] / 100.0

    if short_trend.iloc[-1] and medium_trend.iloc[-1]:
        signal = "bullish"
        confidence = trend_strength
    elif not short_trend.iloc[-1] and not medium_trend.iloc[-1]:
        signal = "bearish"
        confidence = trend_strength
    else:
        signal = "neutral"
        confidence = NEUTRAL_CONFIDENCE

    return {
        "signal": signal,
        "confidence": safe_confidence(confidence),
        "metrics": {
            "adx": safe_float(adx["adx"].iloc[-1]),
            "trend_strength": safe_float(trend_strength),
        },
    }


def calculate_mean_reversion_signals(prices_df):
    """
    Mean reversion strategy using statistical measures and Bollinger Bands
    """
    # Calculate z-score of price relative to moving average
    ma_50 = prices_df["close"].rolling(window=MR_MA_WINDOW).mean()
    std_50 = prices_df["close"].rolling(window=MR_MA_WINDOW).std()
    # Guard against inf when std_50 is 0 (constant price window)
    z_score_raw = (prices_df["close"] - ma_50) / std_50
    z_score = z_score_raw.replace([float("inf"), float("-inf")], 0.0).fillna(0.0)

    # Calculate Bollinger Bands
    bb_upper, bb_lower = calculate_bollinger_bands(prices_df)

    # Calculate RSI with multiple timeframes
    rsi_14 = calculate_rsi(prices_df, MR_RSI_FAST)
    rsi_28 = calculate_rsi(prices_df, MR_RSI_SLOW)

    # Mean reversion signals
    bb_width = bb_upper.iloc[-1] - bb_lower.iloc[-1]
    if bb_width > 0:
        price_vs_bb = (prices_df["close"].iloc[-1] - bb_lower.iloc[-1]) / bb_width
    else:
        price_vs_bb = 0.5  # No band width, default to middle

    # Combine signals
    # NS-4 flip (autodev C225 n=1193/factor, sep=-2.58%; mirrors volatility flip C224
    # commit 9059a4cf): mean-reversion logic was systematically REVERSED vs T+1 —
    # short-term momentum dominates, so oversold 票 keep falling. Swap labels:
    # oversold → bearish (momentum), overbought → bullish (momentum continuation).
    if z_score.iloc[-1] < MR_ZSCORE_BULL and price_vs_bb < MR_PRICE_VS_BB_BULL:
        signal = "bearish"  # NS-4: was "bullish" (mean-reversion bet; reversed vs T+1)
        confidence = min(abs(z_score.iloc[-1]) / MR_ZSCORE_MAX, 1.0)
    elif z_score.iloc[-1] > MR_ZSCORE_BEAR and price_vs_bb > MR_PRICE_VS_BB_BEAR:
        signal = "bullish"  # NS-4: was "bearish"
        confidence = min(abs(z_score.iloc[-1]) / MR_ZSCORE_MAX, 1.0)
    else:
        signal = "neutral"
        confidence = NEUTRAL_CONFIDENCE

    return {
        "signal": signal,
        "confidence": safe_confidence(confidence),
        "metrics": {
            "z_score": safe_float(z_score.iloc[-1]),
            "price_vs_bb": safe_float(price_vs_bb),
            "rsi_14": safe_float(rsi_14.iloc[-1]),
            "rsi_28": safe_float(rsi_28.iloc[-1]),
        },
    }


def calculate_momentum_signals(prices_df):
    """
    Multi-factor momentum strategy
    """
    # Price momentum
    returns = prices_df["close"].pct_change()
    mom_1m = returns.rolling(MOM_WINDOW_1M).sum()
    mom_3m = returns.rolling(MOM_WINDOW_3M).sum()
    mom_6m = returns.rolling(MOM_WINDOW_6M).sum()

    # Volume momentum
    volume_ma = prices_df["volume"].rolling(MOM_WINDOW_1M).mean()
    volume_momentum = prices_df["volume"] / volume_ma.replace(0, float("nan"))

    # Relative strength
    # (would compare to market/sector in real implementation)

    # Calculate momentum score
    momentum_score = (MOM_WEIGHT_1M * mom_1m + MOM_WEIGHT_3M * mom_3m + MOM_WEIGHT_6M * mom_6m).iloc[-1]

    # Volume confirmation — guard against NaN from zero volume_ma
    vol_mom_val = volume_momentum.iloc[-1]
    volume_confirmation = False if pd.isna(vol_mom_val) else vol_mom_val > MOM_VOLUME_CONFIRM_RATIO

    if momentum_score > MOM_THRESHOLD and volume_confirmation:
        signal = "bullish"
        confidence = min(abs(momentum_score) * MOM_CONFIDENCE_SCALE, 1.0)
    elif momentum_score < -MOM_THRESHOLD and volume_confirmation:
        signal = "bearish"
        confidence = min(abs(momentum_score) * MOM_CONFIDENCE_SCALE, 1.0)
    else:
        signal = "neutral"
        confidence = NEUTRAL_CONFIDENCE

    return {
        "signal": signal,
        "confidence": safe_confidence(confidence),
        "metrics": {
            "momentum_1m": safe_float(mom_1m.iloc[-1]),
            "momentum_3m": safe_float(mom_3m.iloc[-1]),
            "momentum_6m": safe_float(mom_6m.iloc[-1]),
            "volume_momentum": safe_float(volume_momentum.iloc[-1]),
        },
    }


def calculate_volatility_signals(prices_df):
    """
    Volatility-based trading strategy
    """
    # Calculate various volatility metrics
    returns = prices_df["close"].pct_change()

    # Historical volatility
    hist_vol = returns.rolling(VOL_WINDOW).std() * math.sqrt(VOL_ANNUALIZATION)

    # Volatility regime detection — guard against division by zero when vol_ma is 0
    vol_ma = hist_vol.rolling(VOL_REGIME_WINDOW).mean()
    vol_regime = hist_vol / vol_ma.replace(0, float("nan"))

    # Volatility mean reversion
    vol_std = hist_vol.rolling(VOL_REGIME_WINDOW).std()
    vol_z_score = (hist_vol - vol_ma) / vol_std.replace(0, float("nan"))

    # ATR ratio — guard against division by zero when close price is 0
    atr = calculate_atr(prices_df)
    atr_ratio = atr / prices_df["close"].replace(0, float("nan"))

    # Generate signal based on volatility regime.
    # safe_float already converts NaN/Inf to the default, so no separate
    # pd.isna() check is needed here.
    current_vol_regime = safe_float(vol_regime.iloc[-1], default=1.0)
    vol_z = safe_float(vol_z_score.iloc[-1], default=0.0)

    if current_vol_regime < VOL_LOW_THRESHOLD and vol_z < -VOL_Z_THRESHOLD:
        signal = "bearish"  # Low vol regime → stagnation (C224: labels were reversed vs T+1)
        confidence = min(abs(vol_z) / VOL_CONFIDENCE_SCALE, 1.0)
    elif current_vol_regime > VOL_HIGH_THRESHOLD and vol_z > VOL_Z_THRESHOLD:
        signal = "bullish"  # High vol regime → momentum continuation (C224 flip)
        confidence = min(abs(vol_z) / VOL_CONFIDENCE_SCALE, 1.0)
    else:
        signal = "neutral"
        confidence = NEUTRAL_CONFIDENCE

    return {
        "signal": signal,
        "confidence": safe_confidence(confidence),
        "metrics": {
            "historical_volatility": safe_float(hist_vol.iloc[-1]),
            "volatility_regime": safe_float(current_vol_regime),
            "volatility_z_score": safe_float(vol_z),
            "atr_ratio": safe_float(atr_ratio.iloc[-1]),
        },
    }


def calculate_stat_arb_signals(prices_df):
    """
    Statistical arbitrage signals based on price action analysis
    """
    # Calculate price distribution statistics
    returns = prices_df["close"].pct_change()

    # Skewness and kurtosis
    skew = returns.rolling(STAT_ARB_WINDOW).skew()
    kurt = returns.rolling(STAT_ARB_WINDOW).kurt()

    # Test for mean reversion using Hurst exponent
    hurst = calculate_hurst_exponent(prices_df["close"])

    # Correlation analysis
    # (would include correlation with related securities in real implementation)

    # Generate signal based on statistical properties
    # NS-4 flip (autodev C225 sep=-1.04%; same root cause as zscore_bbands flip above):
    # mean-reversion bet was reversed vs T+1. Swap labels.
    if hurst < STAT_ARB_HURST_BULL and skew.iloc[-1] > STAT_ARB_SKEW_THRESHOLD:
        signal = "bearish"  # NS-4: was "bullish"
        confidence = (0.5 - hurst) * STAT_ARB_HURST_SCALE
    elif hurst < STAT_ARB_HURST_BULL and skew.iloc[-1] < -STAT_ARB_SKEW_THRESHOLD:
        signal = "bullish"  # NS-4: was "bearish"
        confidence = (0.5 - hurst) * STAT_ARB_HURST_SCALE
    else:
        signal = "neutral"
        confidence = NEUTRAL_CONFIDENCE

    return {
        "signal": signal,
        "confidence": safe_confidence(confidence),
        "metrics": {
            "hurst_exponent": safe_float(hurst),
            "skewness": safe_float(skew.iloc[-1]),
            "kurtosis": safe_float(kurt.iloc[-1]),
        },
    }


def weighted_signal_combination(signals, weights):
    """
    Combines multiple trading signals using a weighted approach.

    Returns confidence as:
    - For bullish/bearish: abs(final_score) — how strongly directional
    - For neutral: weighted average of sub-strategy confidences that agree on neutral,
      reflecting how confidently we believe the signal is neutral
    """
    # Convert signals to numeric values
    signal_values = {"bullish": 1, "neutral": 0, "bearish": -1}

    weighted_sum = 0
    total_confidence = 0
    total_weight = 0

    for strategy, signal in signals.items():
        numeric_signal = signal_values[signal["signal"]]
        weight = weights[strategy]
        confidence = safe_confidence(signal.get("confidence", 0.5))

        weighted_sum += numeric_signal * weight * confidence
        total_confidence += weight * confidence
        total_weight += weight

    # Normalize the weighted sum
    final_score = weighted_sum / total_confidence if total_confidence > 0 else 0

    # Convert back to signal — see module-level SIGNAL_THRESHOLD for rationale
    if final_score > SIGNAL_THRESHOLD:
        signal = "bullish"
    elif final_score < -SIGNAL_THRESHOLD:
        signal = "bearish"
    else:
        signal = "neutral"

    # Calculate confidence
    if signal == "neutral":
        # For neutral signals, confidence = weighted average of sub-strategy confidences
        # This reflects "how confident are we that the signal is neutral"
        raw_confidence = total_confidence / total_weight if total_weight > 0 else 0
        confidence = min(raw_confidence, 1.0)
    else:
        confidence = abs(final_score)

    return {"signal": signal, "confidence": safe_confidence(confidence, default=0.0)}


def normalize_pandas(obj):
    """Convert pandas Series/DataFrames to primitive Python types"""
    if isinstance(obj, pd.Series):
        return obj.tolist()
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict("records")
    if isinstance(obj, dict):
        return {k: normalize_pandas(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [normalize_pandas(item) for item in obj]
    return obj


def calculate_rsi(prices_df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate RSI using Wilder's smoothing (EWMA with alpha=1/period).

    The classic RSI uses Wilder's smoothing (an EMA with smoothing factor 1/period),
    NOT a simple rolling mean. Simple rolling averages give too much weight to
    recent values and produce different RSI values from the standard definition.
    """
    delta = prices_df["close"].diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    # Wilder's smoothing: alpha = 1/period, adjust=False for recursive EMA
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    # Guard against division by zero: when avg_loss is 0, RSI should be 100
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(100.0)


def calculate_bollinger_bands(prices_df: pd.DataFrame, window: int = 20) -> tuple[pd.Series, pd.Series]:
    sma = prices_df["close"].rolling(window).mean()
    std_dev = prices_df["close"].rolling(window).std()
    upper_band = sma + (std_dev * 2)
    lower_band = sma - (std_dev * 2)
    return upper_band, lower_band


def calculate_ema(df: pd.DataFrame, window: int) -> pd.Series:
    """
    Calculate Exponential Moving Average

    Args:
        df: DataFrame with price data
        window: EMA period

    Returns:
        pd.Series: EMA values
    """
    return df["close"].ewm(span=window, adjust=False).mean()


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Calculate Average Directional Index (ADX)

    Args:
        df: DataFrame with OHLC data
        period: Period for calculations

    Returns:
        DataFrame with ADX values
    """
    # Work on a copy to avoid mutating the caller's DataFrame
    df = df.copy()

    # Calculate True Range
    df["high_low"] = df["high"] - df["low"]
    df["high_close"] = abs(df["high"] - df["close"].shift())
    df["low_close"] = abs(df["low"] - df["close"].shift())
    df["tr"] = df[["high_low", "high_close", "low_close"]].max(axis=1)

    # Calculate Directional Movement
    df["up_move"] = df["high"] - df["high"].shift()
    df["down_move"] = df["low"].shift() - df["low"]

    df["plus_dm"] = np.where((df["up_move"] > df["down_move"]) & (df["up_move"] > 0), df["up_move"], 0)
    df["minus_dm"] = np.where((df["down_move"] > df["up_move"]) & (df["down_move"] > 0), df["down_move"], 0)

    # Calculate ADX — guard against division by zero when TR EMA is 0
    tr_ema = df["tr"].ewm(span=period).mean().replace(0, float("nan"))
    df["+di"] = 100 * (df["plus_dm"].ewm(span=period).mean() / tr_ema)
    df["-di"] = 100 * (df["minus_dm"].ewm(span=period).mean() / tr_ema)
    di_sum = df["+di"] + df["-di"]
    df["dx"] = 100 * abs(df["+di"] - df["-di"]) / di_sum.replace(0, float("nan"))
    df["adx"] = df["dx"].ewm(span=period).mean()

    return df[["adx", "+di", "-di"]]


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate Average True Range

    Args:
        df: DataFrame with OHLC data
        period: Period for ATR calculation

    Returns:
        pd.Series: ATR values
    """
    high_low = df["high"] - df["low"]
    high_close = abs(df["high"] - df["close"].shift())
    low_close = abs(df["low"] - df["close"].shift())

    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)

    return true_range.rolling(period).mean()


def calculate_hurst_exponent(price_series: pd.Series, max_lag: int = 20) -> float:
    """
    Calculate Hurst Exponent to determine long-term memory of time series
    using the rescaled range (R/S) method.

    H < 0.5: Mean reverting series
    H = 0.5: Random walk
    H > 0.5: Trending series

    Args:
        price_series: Array-like price data
        max_lag: Maximum lag for R/S calculation

    Returns:
        float: Hurst exponent
    """
    # Convert to numpy array to avoid pandas index-alignment issues
    ts = np.asarray(price_series, dtype=float)
    ts = ts[~np.isnan(ts)]

    if len(ts) < max_lag + 2:
        return 0.5  # Not enough data

    lags = range(2, max_lag)
    # Rescaled range (R/S) method: tau[lag] = (max(diff) - min(diff)) / std(diff)
    # Using std(diffs) alone is incorrect — it omits the (max - min) term, which
    # captures the range spanned by the lagged increments. Guard against zero std
    # (constant series at a given lag) to avoid divide-by-zero.
    tau = []
    for lag in lags:
        diffs = ts[lag:] - ts[:-lag]
        std_val = np.std(diffs)
        if std_val == 0:
            tau.append(1e-8)
        else:
            tau.append((np.max(diffs) - np.min(diffs)) / std_val)

    # Return the Hurst exponent from linear fit of log(lag) vs log(tau)
    try:
        reg = np.polyfit(np.log(list(lags)), np.log(tau), 1)
        hurst = reg[0]  # Hurst exponent is the slope
        # Clamp to reasonable range [0, 1]
        return float(np.clip(hurst, 0.0, 1.0))
    except (ValueError, RuntimeWarning):
        # Return 0.5 (random walk) if calculation fails
        return 0.5
