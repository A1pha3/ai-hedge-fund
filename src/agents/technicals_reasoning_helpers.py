def _build_overall_signal_lines(ticker: str, combined_signal: dict, signal_cn: dict[str, str]) -> list[str]:
    final_signal = combined_signal["signal"]
    final_confidence = combined_signal["confidence"]
    return [
        f"=== {ticker} 技术分析详细解读 ===\n",
        f"【综合信号】{signal_cn.get(final_signal, final_signal)} (置信度: {final_confidence:.1f}%)\n",
    ]


def _build_trend_lines(metrics: dict, signal: str) -> list[str]:
    adx = metrics.get("adx", 0)
    trend_strength = metrics.get("trend_strength", 0)
    lines = [
        f"  • ADX(趋势强度): {adx:.2f} (ADX>25表示强趋势)",
        f"  • 趋势强度得分: {trend_strength:.2f}",
    ]
    if signal == "bullish":
        lines.append("  • 解读: EMA8>EMA21且EMA21>EMA55，短期和中期趋势均为上升")
    elif signal == "bearish":
        lines.append("  • 解读: EMA8<EMA21且EMA21<EMA55，短期和中期趋势均为下降")
    else:
        lines.append("  • 解读: 短期和中期趋势方向不一致，处于震荡或转折期")
    return lines


def _build_mean_reversion_lines(metrics: dict, signal: str) -> list[str]:
    z_score = metrics.get("z_score", 0)
    price_vs_bb = metrics.get("price_vs_bb", 0.5)
    rsi_14 = metrics.get("rsi_14", 50)
    rsi_28 = metrics.get("rsi_28", 50)
    lines = [
        f"  • Z-Score(偏离度): {z_score:.2f} (|Z|>2表示显著偏离)",
        f"  • 布林带位置: {price_vs_bb:.2f} (0=下轨, 1=上轨)",
        f"  • RSI(14): {rsi_14:.2f}, RSI(28): {rsi_28:.2f}",
    ]
    # NS-4 (commit 023acd74): signal generators flipped — short-term momentum
    # dominates T+1, so oversold 票 keep falling. bullish now means OVERBOUGHT
    # (z>+2, near upper band); bearish now means OVERSOLD (z<-2, near lower band).
    if signal == "bullish":
        lines.append("  • 解读: 价格显著高于均值(Z>+2)且接近布林带上轨，动量延续看涨")
    elif signal == "bearish":
        lines.append("  • 解读: 价格显著低于均值(Z<-2)且接近布林带下轨，动量延续看跌")
    else:
        lines.append("  • 解读: 价格处于正常波动区间，无明显超买超卖")
    return lines


def _build_momentum_lines(metrics: dict, signal: str) -> list[str]:
    mom_1m = metrics.get("momentum_1m", 0) * 100
    mom_3m = metrics.get("momentum_3m", 0) * 100
    mom_6m = metrics.get("momentum_6m", 0) * 100
    vol_mom = metrics.get("volume_momentum", 1)
    lines = [
        f"  • 1月动量: {mom_1m:.2f}%, 3月动量: {mom_3m:.2f}%, 6月动量: {mom_6m:.2f}%",
        f"  • 成交量动量: {vol_mom:.2f} (>1表示放量)",
    ]
    if signal == "bullish":
        lines.append("  • 解读: 价格动量强劲且成交量配合，上涨动能充足")
    elif signal == "bearish":
        lines.append("  • 解读: 价格动量疲弱且成交量配合，下跌动能充足")
    else:
        lines.append("  • 解读: 动量信号不明确，缺乏明确方向")
    return lines


def _build_volatility_lines(metrics: dict, signal: str) -> list[str]:
    hist_vol = metrics.get("historical_volatility", 0) * 100
    vol_regime = metrics.get("volatility_regime", 1)
    atr_ratio = metrics.get("atr_ratio", 0) * 100
    lines = [
        f"  • 历史波动率: {hist_vol:.2f}%",
        f"  • 波动率区间: {vol_regime:.2f} (1=正常, <0.9=低波动, >1.1=高波动)",
        f"  • ATR比率: {atr_ratio:.2f}%",
    ]
    # C224 (commit 9059a4cf): signal labels flipped — bullish now means
    # HIGH-VOL regime (momentum continuation); bearish means LOW-VOL regime (stagnation).
    # C236 (commit 2af98d88): thresholds narrowed 0.8/1.2 → 0.9/1.1 (B_narrow).
    if signal == "bullish":
        lines.append("  • 解读: 处于高波动区间，动量延续看涨 (C224: 高波动=近期强势股延续)")
    elif signal == "bearish":
        lines.append("  • 解读: 处于低波动区间，动量停滞看跌 (C224: 低波动=停滞盘整)")
    else:
        lines.append("  • 解读: 波动率处于正常水平")
    return lines


def _build_stat_arb_lines(metrics: dict, signal: str) -> list[str]:
    hurst = metrics.get("hurst_exponent", 0.5)
    skew = metrics.get("skewness", 0)
    kurt = metrics.get("kurtosis", 0)
    lines = [
        f"  • Hurst指数: {hurst:.4f} (<0.5均值回归, >0.5趋势性)",
        f"  • 偏度: {skew:.2f} (>0右偏, <0左偏)",
        f"  • 峰度: {kurt:.2f}",
    ]
    # NS-4 (commit 023acd74): signal generators flipped — bullish now means
    # NEGATIVE skew (左偏); bearish now means POSITIVE skew (右偏).
    if signal == "bullish":
        lines.append("  • 解读: 价格呈现均值回归特性且分布左偏，动量延续看涨")
    elif signal == "bearish":
        lines.append("  • 解读: 价格呈现均值回归特性且分布右偏，动量延续看跌")
    else:
        lines.append("  • 解读: 价格行为接近随机游走，统计特征不明显")
    return lines


_STRATEGY_LINE_BUILDERS = {
    "trend": _build_trend_lines,
    "mean_reversion": _build_mean_reversion_lines,
    "momentum": _build_momentum_lines,
    "volatility": _build_volatility_lines,
    "stat_arb": _build_stat_arb_lines,
}


def _build_strategy_section_lines(strategy_key: str, strategy_name: str, signal_data: dict, weight: float, signal_cn: dict[str, str]) -> list[str]:
    signal = signal_data.get("signal", "neutral")
    confidence = signal_data.get("confidence", 0.5)
    metrics = signal_data.get("metrics", {})
    lines = [f"\n【{strategy_name}】权重{weight:.0f}% - {signal_cn.get(signal, signal)} (置信度: {confidence:.1f}%)"]
    lines.extend(_STRATEGY_LINE_BUILDERS[strategy_key](metrics, signal))
    return lines


def _build_summary_lines(final_signal: str, strategy_signals: dict) -> list[str]:
    bullish_count = sum(1 for signal in strategy_signals.values() if signal.get("signal") == "bullish")
    bearish_count = sum(1 for signal in strategy_signals.values() if signal.get("signal") == "bearish")
    neutral_count = sum(1 for signal in strategy_signals.values() if signal.get("signal") == "neutral")

    lines = [
        "\n【综合结论】",
        f"  • 看涨策略: {bullish_count}/5, 看跌策略: {bearish_count}/5, 中性策略: {neutral_count}/5",
    ]
    if final_signal == "bullish":
        lines.append("  • 多数策略指向看涨，建议关注买入机会")
    elif final_signal == "bearish":
        lines.append("  • 多数策略指向看跌，建议关注卖出或规避风险")
    else:
        lines.append("  • 策略信号分歧较大，建议观望等待更明确信号")
    return lines
