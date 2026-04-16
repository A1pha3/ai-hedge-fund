from datetime import datetime
from pathlib import Path
from collections.abc import Callable


def build_trading_report_path(report_dir: Path, tickers: list[str], generated_at: datetime) -> Path:
    tickers_str = "_".join(tickers[:3])
    if len(tickers) > 3:
        tickers_str += f"_etc{len(tickers)}"
    filename = f"{tickers_str}_{generated_at.strftime('%Y%m%d_%H%M%S')}.md"
    return report_dir / filename


def build_trading_report_lines(
    *,
    result: dict,
    decisions: dict,
    tickers: list[str],
    model_name: str,
    model_provider: str,
    start_date: str,
    end_date: str,
    generated_at: datetime,
    get_stock_details: Callable[[str], dict],
    get_stock_name: Callable[[str], str],
    format_list_date: Callable[[str], str],
    format_reasoning_to_markdown: Callable[[dict | str], str],
    currency_symbol: Callable[[list[str] | str | None], str],
) -> list[str]:
    lines = [
        "# 对冲基金分析报告\n",
        f"- **生成时间**: {generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **分析周期**: {start_date} ~ {end_date}",
        f"- **模型**: {model_provider} - {model_name}\n",
    ]
    lines.extend(_build_stock_overview_lines(tickers, decisions, get_stock_details, format_list_date))

    for ticker, decision in decisions.items():
        lines.extend(
            _build_ticker_analysis_lines(
                ticker=ticker,
                decision=decision,
                result=result,
                tickers=tickers,
                get_stock_name=get_stock_name,
                format_reasoning_to_markdown=format_reasoning_to_markdown,
                currency_symbol=currency_symbol(tickers),
            )
        )

    lines.append("---\n")
    lines.append("*本报告由 AI 对冲基金系统自动生成*\n")
    lines.append("*审阅提示：请检查分析师推理逻辑是否合理，数据来源是否可靠，风险管理参数是否适当。*\n")
    return lines


def _build_stock_overview_lines(
    tickers: list[str],
    decisions: dict,
    get_stock_details: Callable[[str], dict],
    format_list_date: Callable[[str], str],
) -> list[str]:
    lines = [
        "## 分析股票概览\n",
        "| 代码 | 股票名称 | 涨幅 | 昨日收盘价 | 今日收盘价 | 地域 | 所属行业 | 市场类型 | 上市日期 | 操作 | 置信度 |",
        "|------|------|------|------|------|------|------|------|------|------|--------|",
    ]
    for ticker in tickers:
        stock_details = get_stock_details(ticker)
        decision = decisions.get(ticker, {})
        action = decision.get("action", "N/A").upper()
        confidence = decision.get("confidence", 0)
        lines.append(
            f"| {ticker} | {stock_details.get('name', ticker)} | "
            f"{stock_details.get('pct_chg', 'N/A')} | "
            f"{stock_details.get('pre_close', 'N/A')} | "
            f"{stock_details.get('close', 'N/A')} | "
            f"{stock_details.get('area', 'N/A')} | "
            f"{stock_details.get('industry', 'N/A')} | "
            f"{stock_details.get('market', 'N/A')} | "
            f"{format_list_date(stock_details.get('list_date', 'N/A'))} | "
            f"{action} | {confidence:.1f}% |"
        )
    lines.append("")
    return lines


def _build_ticker_analysis_lines(
    *,
    ticker: str,
    decision: dict,
    result: dict,
    tickers: list[str],
    get_stock_name: Callable[[str], str],
    format_reasoning_to_markdown: Callable[[dict | str], str],
    currency_symbol: str,
) -> list[str]:
    stock_name = get_stock_name(ticker)
    lines = [f"## {ticker}（{stock_name}）详细分析\n"]
    lines.extend(_build_analyst_signal_summary_lines(ticker, result))
    lines.extend(_build_analyst_detail_lines(ticker, result, format_reasoning_to_markdown))

    risk_signals = result.get("analyst_signals", {}).get("risk_management_agent", {})
    if ticker in risk_signals:
        lines.extend(_build_risk_management_lines(risk_signals[ticker], currency_symbol))

    lines.extend(_build_final_decision_lines(decision))
    return lines


def _build_analyst_signal_summary_lines(ticker: str, result: dict) -> list[str]:
    lines = ["### 1. 分析师信号汇总\n", "| 分析师 | 信号 | 置信度 |", "|--------|------|--------|"]
    bullish_count = 0
    bearish_count = 0
    neutral_count = 0

    for agent, signals in result.get("analyst_signals", {}).items():
        if ticker not in signals or agent == "risk_management_agent":
            continue

        signal = signals[ticker]
        agent_name = agent.replace("_agent", "").replace("_", " ").title()
        signal_type = signal.get("signal", "").upper()
        confidence = signal.get("confidence", 0)

        if signal_type == "BULLISH":
            bullish_count += 1
        elif signal_type == "BEARISH":
            bearish_count += 1
        elif signal_type == "NEUTRAL":
            neutral_count += 1

        lines.append(f"| {agent_name} | {signal_type} | {confidence}% |")

    lines.append(f"\n**信号统计**: 看涨 {bullish_count} | 看跌 {bearish_count} | 中性 {neutral_count}\n")
    return lines


def _build_analyst_detail_lines(ticker: str, result: dict, format_reasoning_to_markdown: Callable[[dict | str], str]) -> list[str]:
    lines = ["### 2. 分析师详细推理\n"]
    for agent, signals in result.get("analyst_signals", {}).items():
        if ticker not in signals or agent == "risk_management_agent":
            continue

        signal = signals[ticker]
        agent_name = agent.replace("_agent", "").replace("_", " ").title()
        signal_type = signal.get("signal", "").upper()
        confidence = signal.get("confidence", 0)
        formatted_reasoning = format_reasoning_to_markdown(signal.get("reasoning", ""))

        lines.append(f"#### {agent_name}\n")
        lines.append(f"- **信号**: {signal_type}")
        lines.append(f"- **置信度**: {confidence}%")
        lines.append("- **推理过程**:\n")
        lines.append(f"{formatted_reasoning}\n")

        reasoning_cn = signal.get("reasoning_cn")
        if reasoning_cn and isinstance(reasoning_cn, str):
            lines.append(f"**中文翻译**：\n{reasoning_cn}\n")
    return lines


def _build_risk_management_lines(risk_data: dict, currency_symbol: str) -> list[str]:
    lines = ["### 3. 风险管理分析\n", "#### 仓位限制\n", "| 项目 | 值 |", "|------|------|"]
    remaining_limit = risk_data.get("remaining_position_limit", "N/A")
    current_price = risk_data.get("current_price", "N/A")
    if isinstance(remaining_limit, (int, float)):
        remaining_limit = f"{remaining_limit:,.2f}"
    if isinstance(current_price, (int, float)):
        current_price = f"{current_price:.2f}"
    lines.append(f"| 剩余仓位限制 | {remaining_limit} |")
    lines.append(f"| 当前价格 | {current_price} |")
    lines.append("")

    vol_metrics = risk_data.get("volatility_metrics", {})
    if vol_metrics:
        lines.extend(_build_risk_volatility_lines(vol_metrics))

    risk_reasoning = risk_data.get("reasoning", {})
    if risk_reasoning:
        lines.extend(_build_risk_reasoning_lines(risk_reasoning, currency_symbol))
    return lines


def _build_risk_volatility_lines(vol_metrics: dict) -> list[str]:
    lines = ["#### 波动率指标\n", "| 指标 | 值 |", "|------|------|"]
    daily_vol = vol_metrics.get("daily_volatility")
    annual_vol = vol_metrics.get("annualized_volatility")
    vol_percentile = vol_metrics.get("volatility_percentile")
    lines.append(f"| 日波动率 | {daily_vol:.4f} |" if daily_vol is not None else "| 日波动率 | N/A |")
    lines.append(f"| 年化波动率 | {annual_vol:.4f} |" if annual_vol is not None else "| 年化波动率 | N/A |")
    lines.append(f"| 波动率百分位 | {vol_percentile:.2f}% |" if vol_percentile is not None else "| 波动率百分位 | N/A |")
    lines.append(f"| 数据点数 | {vol_metrics.get('data_points', 'N/A')} |")
    lines.append("")
    return lines


def _build_risk_reasoning_lines(risk_reasoning: dict, currency_symbol: str) -> list[str]:
    lines = ["#### 风险调整计算\n", "| 项目 | 值 |", "|------|------|"]
    portfolio_value = risk_reasoning.get("portfolio_value")
    current_position_value = risk_reasoning.get("current_position_value")
    base_position_limit_pct = risk_reasoning.get("base_position_limit_pct")
    combined_position_limit_pct = risk_reasoning.get("combined_position_limit_pct")
    available_cash = risk_reasoning.get("available_cash")
    lines.append(f"| 投资组合价值 | {currency_symbol}{portfolio_value:,.2f} |" if portfolio_value is not None else "| 投资组合价值 | N/A |")
    lines.append(f"| 当前持仓价值 | {currency_symbol}{current_position_value:,.2f} |" if current_position_value is not None else "| 当前持仓价值 | N/A |")
    lines.append(f"| 基础仓位限制 | {base_position_limit_pct*100:.1f}% |" if base_position_limit_pct is not None else "| 基础仓位限制 | N/A |")
    lines.append(f"| 组合仓位限制 | {combined_position_limit_pct*100:.1f}% |" if combined_position_limit_pct is not None else "| 组合仓位限制 | N/A |")
    lines.append(f"| 可用现金 | {currency_symbol}{available_cash:,.2f} |" if available_cash is not None else "| 可用现金 | N/A |")
    lines.append(f"| 风险调整说明 | {risk_reasoning.get('risk_adjustment', 'N/A')} |")
    lines.append("")
    return lines


def _build_final_decision_lines(decision: dict) -> list[str]:
    action = decision.get("action", "").upper()
    quantity = decision.get("quantity", 0)
    confidence = decision.get("confidence", 0)
    reasoning = decision.get("reasoning", "")
    action_emoji = {"BUY": "📈", "SELL": "📉", "SHORT": "🔻", "COVER": "🔄", "HOLD": "⏸️"}.get(action, "❓")
    return [
        "### 4. 最终交易决策\n",
        "| 项目 | 值 |",
        "|------|------|",
        f"| 操作 | {action_emoji} **{action}** |",
        f"| 数量 | {quantity} 股 |",
        f"| 置信度 | {confidence:.1f}% |",
        f"| 决策理由 | {reasoning} |",
        "",
    ]
