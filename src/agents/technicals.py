import json
import math

import numpy as np
import pandas as pd
from langchain_core.messages import HumanMessage

from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import get_prices, prices_to_df
from src.utils.api_key import get_api_key_from_state
from src.utils.progress import progress


def safe_float(value, default=0.0):
    """
    Safely convert a value to float, handling NaN cases

    Args:
        value: The value to convert (can be pandas scalar, numpy value, etc.)
        default: Default value to return if the input is NaN or invalid

    Returns:
        float: The converted value or default if NaN/invalid
    """
    try:
        if pd.isna(value) or np.isnan(value):
            return default
        return float(value)
    except (ValueError, TypeError, OverflowError):
        return default


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
       - 信号规则：
         *  bullish: Z-Score < -2 且 价格处于布林带下轨20%以内（超卖）
         *  bearish: Z-Score > 2 且 价格处于布林带上轨80%以上（超买）
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
       - 信号规则：
         *  bullish: Hurst < 0.4 且 偏度 > 1（均值回归+右偏）
         *  bearish: Hurst < 0.4 且 偏度 < -1（均值回归+左偏）
         *  neutral: 其他情况

    综合信号计算：
    - 将各策略信号转换为数值（bullish=1, neutral=0, bearish=-1）
    - 加权求和：Σ(信号值 × 权重 × 置信度) / Σ(权重 × 置信度)
    - 最终得分 > 0.2 为 bullish，< -0.2 为 bearish，否则 neutral
    """
    lines = []
    lines.append(f"=== {ticker} 技术分析详细解读 ===\n")

    # 总体信号
    final_signal = combined_signal["signal"]
    final_confidence = combined_signal["confidence"] * 100
    signal_cn = {"bullish": "看涨", "bearish": "看跌", "neutral": "中性"}
    lines.append(f"【综合信号】{signal_cn.get(final_signal, final_signal)} (置信度: {final_confidence:.1f}%)\n")

    # 各策略详细说明
    strategy_names = {"trend": "趋势跟踪", "mean_reversion": "均值回归", "momentum": "动量分析", "volatility": "波动率分析", "stat_arb": "统计套利"}

    for strategy_key, strategy_name in strategy_names.items():
        signal_data = strategy_signals.get(strategy_key, {})
        signal = signal_data.get("signal", "neutral")
        confidence = signal_data.get("confidence", 0.5) * 100
        metrics = signal_data.get("metrics", {})
        weight = weights.get(strategy_key, 0) * 100

        lines.append(f"\n【{strategy_name}】权重{weight:.0f}% - {signal_cn.get(signal, signal)} (置信度: {confidence:.1f}%)")

        # 根据策略类型添加具体解释
        if strategy_key == "trend":
            adx = metrics.get("adx", 0)
            trend_strength = metrics.get("trend_strength", 0)
            lines.append(f"  • ADX(趋势强度): {adx:.2f} (ADX>25表示强趋势)")
            lines.append(f"  • 趋势强度得分: {trend_strength:.2f}")
            if signal == "bullish":
                lines.append(f"  • 解读: EMA8>EMA21且EMA21>EMA55，短期和中期趋势均为上升")
            elif signal == "bearish":
                lines.append(f"  • 解读: EMA8<EMA21且EMA21<EMA55，短期和中期趋势均为下降")
            else:
                lines.append(f"  • 解读: 短期和中期趋势方向不一致，处于震荡或转折期")

        elif strategy_key == "mean_reversion":
            z_score = metrics.get("z_score", 0)
            price_vs_bb = metrics.get("price_vs_bb", 0.5)
            rsi_14 = metrics.get("rsi_14", 50)
            rsi_28 = metrics.get("rsi_28", 50)
            lines.append(f"  • Z-Score(偏离度): {z_score:.2f} (|Z|>2表示显著偏离)")
            lines.append(f"  • 布林带位置: {price_vs_bb:.2f} (0=下轨, 1=上轨)")
            lines.append(f"  • RSI(14): {rsi_14:.2f}, RSI(28): {rsi_28:.2f}")
            if signal == "bullish":
                lines.append(f"  • 解读: 价格显著低于均值(Z<-2)且接近布林带下轨，存在反弹机会")
            elif signal == "bearish":
                lines.append(f"  • 解读: 价格显著高于均值(Z>2)且接近布林带上轨，存在回调风险")
            else:
                lines.append(f"  • 解读: 价格处于正常波动区间，无明显超买超卖")

        elif strategy_key == "momentum":
            mom_1m = metrics.get("momentum_1m", 0) * 100
            mom_3m = metrics.get("momentum_3m", 0) * 100
            mom_6m = metrics.get("momentum_6m", 0) * 100
            vol_mom = metrics.get("volume_momentum", 1)
            lines.append(f"  • 1月动量: {mom_1m:.2f}%, 3月动量: {mom_3m:.2f}%, 6月动量: {mom_6m:.2f}%")
            lines.append(f"  • 成交量动量: {vol_mom:.2f} (>1表示放量)")
            if signal == "bullish":
                lines.append(f"  • 解读: 价格动量强劲且成交量配合，上涨动能充足")
            elif signal == "bearish":
                lines.append(f"  • 解读: 价格动量疲弱且成交量配合，下跌动能充足")
            else:
                lines.append(f"  • 解读: 动量信号不明确，缺乏明确方向")

        elif strategy_key == "volatility":
            hist_vol = metrics.get("historical_volatility", 0) * 100
            vol_regime = metrics.get("volatility_regime", 1)
            vol_z = metrics.get("volatility_z_score", 0)
            atr_ratio = metrics.get("atr_ratio", 0) * 100
            lines.append(f"  • 历史波动率: {hist_vol:.2f}%")
            lines.append(f"  • 波动率区间: {vol_regime:.2f} (1=正常, <0.8=低波动, >1.2=高波动)")
            lines.append(f"  • ATR比率: {atr_ratio:.2f}%")
            if signal == "bullish":
                lines.append(f"  • 解读: 处于低波动区间，波动率有望扩张，可能伴随价格上涨")
            elif signal == "bearish":
                lines.append(f"  • 解读: 处于高波动区间，波动率有望收缩，可能伴随价格调整")
            else:
                lines.append(f"  • 解读: 波动率处于正常水平")

        elif strategy_key == "stat_arb":
            hurst = metrics.get("hurst_exponent", 0.5)
            skew = metrics.get("skewness", 0)
            kurt = metrics.get("kurtosis", 0)
            lines.append(f"  • Hurst指数: {hurst:.4f} (<0.5均值回归, >0.5趋势性)")
            lines.append(f"  • 偏度: {skew:.2f} (>0右偏, <0左偏)")
            lines.append(f"  • 峰度: {kurt:.2f}")
            if signal == "bullish":
                lines.append(f"  • 解读: 价格呈现均值回归特性且分布右偏，反弹概率较高")
            elif signal == "bearish":
                lines.append(f"  • 解读: 价格呈现均值回归特性且分布左偏，回调概率较高")
            else:
                lines.append(f"  • 解读: 价格行为接近随机游走，统计特征不明显")

    # 综合结论
    lines.append(f"\n【综合结论】")
    bullish_count = sum(1 for s in strategy_signals.values() if s.get("signal") == "bullish")
    bearish_count = sum(1 for s in strategy_signals.values() if s.get("signal") == "bearish")
    neutral_count = sum(1 for s in strategy_signals.values() if s.get("signal") == "neutral")
    lines.append(f"  • 看涨策略: {bullish_count}/5, 看跌策略: {bearish_count}/5, 中性策略: {neutral_count}/5")

    if final_signal == "bullish":
        lines.append(f"  • 多数策略指向看涨，建议关注买入机会")
    elif final_signal == "bearish":
        lines.append(f"  • 多数策略指向看跌，建议关注卖出或规避风险")
    else:
        lines.append(f"  • 策略信号分歧较大，建议观望等待更明确信号")

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
            "confidence": round(combined_signal["confidence"] * 100),
            "reasoning": {
                "trend_following": {
                    "signal": trend_signals["signal"],
                    "confidence": round(trend_signals["confidence"] * 100),
                    "metrics": normalize_pandas(trend_signals["metrics"]),
                },
                "mean_reversion": {
                    "signal": mean_reversion_signals["signal"],
                    "confidence": round(mean_reversion_signals["confidence"] * 100),
                    "metrics": normalize_pandas(mean_reversion_signals["metrics"]),
                },
                "momentum": {
                    "signal": momentum_signals["signal"],
                    "confidence": round(momentum_signals["confidence"] * 100),
                    "metrics": normalize_pandas(momentum_signals["metrics"]),
                },
                "volatility": {
                    "signal": volatility_signals["signal"],
                    "confidence": round(volatility_signals["confidence"] * 100),
                    "metrics": normalize_pandas(volatility_signals["metrics"]),
                },
                "statistical_arbitrage": {
                    "signal": stat_arb_signals["signal"],
                    "confidence": round(stat_arb_signals["confidence"] * 100),
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
    ema_8 = calculate_ema(prices_df, 8)
    ema_21 = calculate_ema(prices_df, 21)
    ema_55 = calculate_ema(prices_df, 55)

    # Calculate ADX for trend strength
    adx = calculate_adx(prices_df, 14)

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
        confidence = 0.5

    return {
        "signal": signal,
        "confidence": confidence,
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
    ma_50 = prices_df["close"].rolling(window=50).mean()
    std_50 = prices_df["close"].rolling(window=50).std()
    z_score = (prices_df["close"] - ma_50) / std_50

    # Calculate Bollinger Bands
    bb_upper, bb_lower = calculate_bollinger_bands(prices_df)

    # Calculate RSI with multiple timeframes
    rsi_14 = calculate_rsi(prices_df, 14)
    rsi_28 = calculate_rsi(prices_df, 28)

    # Mean reversion signals
    price_vs_bb = (prices_df["close"].iloc[-1] - bb_lower.iloc[-1]) / (bb_upper.iloc[-1] - bb_lower.iloc[-1])

    # Combine signals
    if z_score.iloc[-1] < -2 and price_vs_bb < 0.2:
        signal = "bullish"
        confidence = min(abs(z_score.iloc[-1]) / 4, 1.0)
    elif z_score.iloc[-1] > 2 and price_vs_bb > 0.8:
        signal = "bearish"
        confidence = min(abs(z_score.iloc[-1]) / 4, 1.0)
    else:
        signal = "neutral"
        confidence = 0.5

    return {
        "signal": signal,
        "confidence": confidence,
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
    mom_1m = returns.rolling(21).sum()
    mom_3m = returns.rolling(63).sum()
    mom_6m = returns.rolling(126).sum()

    # Volume momentum
    volume_ma = prices_df["volume"].rolling(21).mean()
    volume_momentum = prices_df["volume"] / volume_ma

    # Relative strength
    # (would compare to market/sector in real implementation)

    # Calculate momentum score
    momentum_score = (0.4 * mom_1m + 0.3 * mom_3m + 0.3 * mom_6m).iloc[-1]

    # Volume confirmation
    volume_confirmation = volume_momentum.iloc[-1] > 1.0

    if momentum_score > 0.05 and volume_confirmation:
        signal = "bullish"
        confidence = min(abs(momentum_score) * 5, 1.0)
    elif momentum_score < -0.05 and volume_confirmation:
        signal = "bearish"
        confidence = min(abs(momentum_score) * 5, 1.0)
    else:
        signal = "neutral"
        confidence = 0.5

    return {
        "signal": signal,
        "confidence": confidence,
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
    hist_vol = returns.rolling(21).std() * math.sqrt(252)

    # Volatility regime detection
    vol_ma = hist_vol.rolling(63).mean()
    vol_regime = hist_vol / vol_ma

    # Volatility mean reversion
    vol_z_score = (hist_vol - vol_ma) / hist_vol.rolling(63).std()

    # ATR ratio
    atr = calculate_atr(prices_df)
    atr_ratio = atr / prices_df["close"]

    # Generate signal based on volatility regime
    current_vol_regime = vol_regime.iloc[-1]
    vol_z = vol_z_score.iloc[-1]

    if current_vol_regime < 0.8 and vol_z < -1:
        signal = "bullish"  # Low vol regime, potential for expansion
        confidence = min(abs(vol_z) / 3, 1.0)
    elif current_vol_regime > 1.2 and vol_z > 1:
        signal = "bearish"  # High vol regime, potential for contraction
        confidence = min(abs(vol_z) / 3, 1.0)
    else:
        signal = "neutral"
        confidence = 0.5

    return {
        "signal": signal,
        "confidence": confidence,
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
    skew = returns.rolling(63).skew()
    kurt = returns.rolling(63).kurt()

    # Test for mean reversion using Hurst exponent
    hurst = calculate_hurst_exponent(prices_df["close"])

    # Correlation analysis
    # (would include correlation with related securities in real implementation)

    # Generate signal based on statistical properties
    if hurst < 0.4 and skew.iloc[-1] > 1:
        signal = "bullish"
        confidence = (0.5 - hurst) * 2
    elif hurst < 0.4 and skew.iloc[-1] < -1:
        signal = "bearish"
        confidence = (0.5 - hurst) * 2
    else:
        signal = "neutral"
        confidence = 0.5

    return {
        "signal": signal,
        "confidence": confidence,
        "metrics": {
            "hurst_exponent": safe_float(hurst),
            "skewness": safe_float(skew.iloc[-1]),
            "kurtosis": safe_float(kurt.iloc[-1]),
        },
    }


def weighted_signal_combination(signals, weights):
    """
    Combines multiple trading signals using a weighted approach
    """
    # Convert signals to numeric values
    signal_values = {"bullish": 1, "neutral": 0, "bearish": -1}

    weighted_sum = 0
    total_confidence = 0

    for strategy, signal in signals.items():
        numeric_signal = signal_values[signal["signal"]]
        weight = weights[strategy]
        confidence = signal["confidence"]

        weighted_sum += numeric_signal * weight * confidence
        total_confidence += weight * confidence

    # Normalize the weighted sum
    if total_confidence > 0:
        final_score = weighted_sum / total_confidence
    else:
        final_score = 0

    # Convert back to signal
    if final_score > 0.2:
        signal = "bullish"
    elif final_score < -0.2:
        signal = "bearish"
    else:
        signal = "neutral"

    return {"signal": signal, "confidence": abs(final_score)}


def normalize_pandas(obj):
    """Convert pandas Series/DataFrames to primitive Python types"""
    if isinstance(obj, pd.Series):
        return obj.tolist()
    elif isinstance(obj, pd.DataFrame):
        return obj.to_dict("records")
    elif isinstance(obj, dict):
        return {k: normalize_pandas(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [normalize_pandas(item) for item in obj]
    return obj


def calculate_rsi(prices_df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = prices_df["close"].diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


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

    # Calculate ADX
    df["+di"] = 100 * (df["plus_dm"].ewm(span=period).mean() / df["tr"].ewm(span=period).mean())
    df["-di"] = 100 * (df["minus_dm"].ewm(span=period).mean() / df["tr"].ewm(span=period).mean())
    df["dx"] = 100 * abs(df["+di"] - df["-di"]) / (df["+di"] + df["-di"])
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
    H < 0.5: Mean reverting series
    H = 0.5: Random walk
    H > 0.5: Trending series

    Args:
        price_series: Array-like price data
        max_lag: Maximum lag for R/S calculation

    Returns:
        float: Hurst exponent
    """
    lags = range(2, max_lag)
    # Add small epsilon to avoid log(0)
    tau = [max(1e-8, np.sqrt(np.std(np.subtract(price_series[lag:], price_series[:-lag])))) for lag in lags]

    # Return the Hurst exponent from linear fit
    try:
        reg = np.polyfit(np.log(lags), np.log(tau), 1)
        return reg[0]  # Hurst exponent is the slope
    except (ValueError, RuntimeWarning):
        # Return 0.5 (random walk) if calculation fails
        return 0.5
