import json
import os
from datetime import datetime
from pathlib import Path

from colorama import Fore, Style
from tabulate import tabulate

from src.tools.tushare_api import get_stock_name

from .analysts import ANALYST_ORDER
from .logging import get_logger

logger = get_logger(__name__)

REPORT_DIR = Path("data/reports")


def sort_agent_signals(signals):
    """Sort agent signals in a consistent order."""
    # Create order mapping from ANALYST_ORDER
    analyst_order = {display: idx for idx, (display, _) in enumerate(ANALYST_ORDER)}
    analyst_order["Risk Management"] = len(ANALYST_ORDER)  # Add Risk Management at the end

    return sorted(signals, key=lambda x: analyst_order.get(x[0], 999))


def print_trading_output(result: dict) -> None:
    """
    Print formatted trading results with colored tables for multiple tickers.

    Args:
        result (dict): Dictionary containing decisions and analyst signals for multiple tickers
    """
    decisions = result.get("decisions")
    if not decisions:
        logger.warning("No trading decisions available")
        print(f"{Fore.RED}No trading decisions available{Style.RESET_ALL}")
        return

    logger.info(f"Processing trading decisions for {len(decisions)} tickers")

    # Print decisions for each ticker
    for ticker, decision in decisions.items():
        action = decision.get("action", "").upper()
        confidence = decision.get("confidence", 0)
        logger.info(f"Trading decision for {ticker}: {action} with {confidence:.1f}% confidence")
        print(f"\n{Fore.WHITE}{Style.BRIGHT}Analysis for {Fore.CYAN}{ticker}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 50}{Style.RESET_ALL}")

        # Prepare analyst signals table for this ticker
        table_data = []
        for agent, signals in result.get("analyst_signals", {}).items():
            if ticker not in signals:
                continue

            # Skip Risk Management agent in the signals section
            if agent == "risk_management_agent":
                continue

            signal = signals[ticker]
            agent_name = agent.replace("_agent", "").replace("_", " ").title()
            signal_type = signal.get("signal", "").upper()
            confidence = signal.get("confidence", 0)

            signal_color = {
                "BULLISH": Fore.GREEN,
                "BEARISH": Fore.RED,
                "NEUTRAL": Fore.YELLOW,
            }.get(signal_type, Fore.WHITE)

            # Get reasoning if available
            reasoning_str = ""
            if "reasoning" in signal and signal["reasoning"]:
                reasoning = signal["reasoning"]

                # Handle different types of reasoning (string, dict, etc.)
                if isinstance(reasoning, str):
                    reasoning_str = reasoning
                elif isinstance(reasoning, dict):
                    # Convert dict to string representation
                    reasoning_str = json.dumps(reasoning, indent=2)
                else:
                    # Convert any other type to string
                    reasoning_str = str(reasoning)

                # Wrap long reasoning text to make it more readable
                wrapped_reasoning = ""
                current_line = ""
                # Use a fixed width of 60 characters to match the table column width
                max_line_length = 60
                for word in reasoning_str.split():
                    if len(current_line) + len(word) + 1 > max_line_length:
                        wrapped_reasoning += current_line + "\n"
                        current_line = word
                    else:
                        if current_line:
                            current_line += " " + word
                        else:
                            current_line = word
                if current_line:
                    wrapped_reasoning += current_line

                reasoning_str = wrapped_reasoning

            table_data.append(
                [
                    f"{Fore.CYAN}{agent_name}{Style.RESET_ALL}",
                    f"{signal_color}{signal_type}{Style.RESET_ALL}",
                    f"{Fore.WHITE}{confidence}%{Style.RESET_ALL}",
                    f"{Fore.WHITE}{reasoning_str}{Style.RESET_ALL}",
                ]
            )

        # Sort the signals according to the predefined order
        table_data = sort_agent_signals(table_data)

        print(f"\n{Fore.WHITE}{Style.BRIGHT}AGENT ANALYSIS:{Style.RESET_ALL} [{Fore.CYAN}{ticker}{Style.RESET_ALL}]")
        print(
            tabulate(
                table_data,
                headers=[f"{Fore.WHITE}Agent", "Signal", "Confidence", "Reasoning"],
                tablefmt="grid",
                colalign=("left", "center", "right", "left"),
            )
        )

        # Print Trading Decision Table
        action = decision.get("action", "").upper()
        action_color = {
            "BUY": Fore.GREEN,
            "SELL": Fore.RED,
            "HOLD": Fore.YELLOW,
            "COVER": Fore.GREEN,
            "SHORT": Fore.RED,
        }.get(action, Fore.WHITE)

        # Get reasoning and format it
        reasoning = decision.get("reasoning", "")
        # Wrap long reasoning text to make it more readable
        wrapped_reasoning = ""
        if reasoning:
            current_line = ""
            # Use a fixed width of 60 characters to match the table column width
            max_line_length = 60
            for word in reasoning.split():
                if len(current_line) + len(word) + 1 > max_line_length:
                    wrapped_reasoning += current_line + "\n"
                    current_line = word
                else:
                    if current_line:
                        current_line += " " + word
                    else:
                        current_line = word
            if current_line:
                wrapped_reasoning += current_line

        decision_data = [
            ["Action", f"{action_color}{action}{Style.RESET_ALL}"],
            ["Quantity", f"{action_color}{decision.get('quantity')}{Style.RESET_ALL}"],
            [
                "Confidence",
                f"{Fore.WHITE}{decision.get('confidence'):.1f}%{Style.RESET_ALL}",
            ],
            ["Reasoning", f"{Fore.WHITE}{wrapped_reasoning}{Style.RESET_ALL}"],
        ]

        print(f"\n{Fore.WHITE}{Style.BRIGHT}TRADING DECISION:{Style.RESET_ALL} [{Fore.CYAN}{ticker}{Style.RESET_ALL}]")
        print(tabulate(decision_data, tablefmt="grid", colalign=("left", "left")))

    # Print Portfolio Summary
    print(f"\n{Fore.WHITE}{Style.BRIGHT}PORTFOLIO SUMMARY:{Style.RESET_ALL}")
    portfolio_data = []

    # Extract portfolio manager reasoning (common for all tickers)
    portfolio_manager_reasoning = None
    for ticker, decision in decisions.items():
        if decision.get("reasoning"):
            portfolio_manager_reasoning = decision.get("reasoning")
            break

    analyst_signals = result.get("analyst_signals", {})
    for ticker, decision in decisions.items():
        action = decision.get("action", "").upper()
        action_color = {
            "BUY": Fore.GREEN,
            "SELL": Fore.RED,
            "HOLD": Fore.YELLOW,
            "COVER": Fore.GREEN,
            "SHORT": Fore.RED,
        }.get(action, Fore.WHITE)

        # Calculate analyst signal counts
        bullish_count = 0
        bearish_count = 0
        neutral_count = 0
        if analyst_signals:
            for agent, signals in analyst_signals.items():
                if ticker in signals:
                    signal = signals[ticker].get("signal", "").upper()
                    if signal == "BULLISH":
                        bullish_count += 1
                    elif signal == "BEARISH":
                        bearish_count += 1
                    elif signal == "NEUTRAL":
                        neutral_count += 1

        portfolio_data.append(
            [
                f"{Fore.CYAN}{ticker}{Style.RESET_ALL}",
                f"{action_color}{action}{Style.RESET_ALL}",
                f"{action_color}{decision.get('quantity')}{Style.RESET_ALL}",
                f"{Fore.WHITE}{decision.get('confidence'):.1f}%{Style.RESET_ALL}",
                f"{Fore.GREEN}{bullish_count}{Style.RESET_ALL}",
                f"{Fore.RED}{bearish_count}{Style.RESET_ALL}",
                f"{Fore.YELLOW}{neutral_count}{Style.RESET_ALL}",
            ]
        )

    headers = [
        f"{Fore.WHITE}Ticker",
        f"{Fore.WHITE}Action",
        f"{Fore.WHITE}Quantity",
        f"{Fore.WHITE}Confidence",
        f"{Fore.WHITE}Bullish",
        f"{Fore.WHITE}Bearish",
        f"{Fore.WHITE}Neutral",
    ]

    # Print the portfolio summary table
    print(
        tabulate(
            portfolio_data,
            headers=headers,
            tablefmt="grid",
            colalign=("left", "center", "right", "right", "center", "center", "center"),
        )
    )

    # Print Portfolio Manager's reasoning if available
    if portfolio_manager_reasoning:
        # Handle different types of reasoning (string, dict, etc.)
        reasoning_str = ""
        if isinstance(portfolio_manager_reasoning, str):
            reasoning_str = portfolio_manager_reasoning
        elif isinstance(portfolio_manager_reasoning, dict):
            # Convert dict to string representation
            reasoning_str = json.dumps(portfolio_manager_reasoning, indent=2)
        else:
            # Convert any other type to string
            reasoning_str = str(portfolio_manager_reasoning)

        # Wrap long reasoning text to make it more readable
        wrapped_reasoning = ""
        current_line = ""
        # Use a fixed width of 60 characters to match the table column width
        max_line_length = 60
        for word in reasoning_str.split():
            if len(current_line) + len(word) + 1 > max_line_length:
                wrapped_reasoning += current_line + "\n"
                current_line = word
            else:
                if current_line:
                    current_line += " " + word
                else:
                    current_line = word
        if current_line:
            wrapped_reasoning += current_line

        print(f"\n{Fore.WHITE}{Style.BRIGHT}Portfolio Strategy:{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{wrapped_reasoning}{Style.RESET_ALL}")


def print_backtest_results(table_rows: list) -> None:
    """Print the backtest results in a nicely formatted table"""
    # Clear the screen
    os.system("cls" if os.name == "nt" else "clear")

    # Split rows into ticker rows and summary rows
    ticker_rows = []
    summary_rows = []

    for row in table_rows:
        if isinstance(row[1], str) and "PORTFOLIO SUMMARY" in row[1]:
            summary_rows.append(row)
        else:
            ticker_rows.append(row)

    # Display latest portfolio summary
    if summary_rows:
        # Pick the most recent summary by date (YYYY-MM-DD)
        latest_summary = max(summary_rows, key=lambda r: r[0])
        print(f"\n{Fore.WHITE}{Style.BRIGHT}PORTFOLIO SUMMARY:{Style.RESET_ALL}")

        # Adjusted indexes after adding Long/Short Shares
        position_str = latest_summary[7].split("$")[1].split(Style.RESET_ALL)[0].replace(",", "")
        cash_str = latest_summary[8].split("$")[1].split(Style.RESET_ALL)[0].replace(",", "")
        total_str = latest_summary[9].split("$")[1].split(Style.RESET_ALL)[0].replace(",", "")

        print(f"Cash Balance: {Fore.CYAN}${float(cash_str):,.2f}{Style.RESET_ALL}")
        print(f"Total Position Value: {Fore.YELLOW}${float(position_str):,.2f}{Style.RESET_ALL}")
        print(f"Total Value: {Fore.WHITE}${float(total_str):,.2f}{Style.RESET_ALL}")
        print(f"Portfolio Return: {latest_summary[10]}")
        if len(latest_summary) > 14 and latest_summary[14]:
            print(f"Benchmark Return: {latest_summary[14]}")

        # Display performance metrics if available
        if latest_summary[11]:  # Sharpe ratio
            print(f"Sharpe Ratio: {latest_summary[11]}")
        if latest_summary[12]:  # Sortino ratio
            print(f"Sortino Ratio: {latest_summary[12]}")
        if latest_summary[13]:  # Max drawdown
            print(f"Max Drawdown: {latest_summary[13]}")

    # Add vertical spacing
    print("\n" * 2)

    # Print the table with just ticker rows
    print(
        tabulate(
            ticker_rows,
            headers=[
                "Date",
                "Ticker",
                "Action",
                "Quantity",
                "Price",
                "Long Shares",
                "Short Shares",
                "Position Value",
            ],
            tablefmt="grid",
            colalign=(
                "left",  # Date
                "left",  # Ticker
                "center",  # Action
                "right",  # Quantity
                "right",  # Price
                "right",  # Long Shares
                "right",  # Short Shares
                "right",  # Position Value
            ),
        )
    )

    # Add vertical spacing
    print("\n" * 4)


def format_backtest_row(
    date: str,
    ticker: str,
    action: str,
    quantity: float,
    price: float,
    long_shares: float = 0,
    short_shares: float = 0,
    position_value: float = 0,
    is_summary: bool = False,
    total_value: float = None,
    return_pct: float = None,
    cash_balance: float = None,
    total_position_value: float = None,
    sharpe_ratio: float = None,
    sortino_ratio: float = None,
    max_drawdown: float = None,
    benchmark_return_pct: float | None = None,
) -> list[any]:
    """Format a row for the backtest results table"""
    # Color the action
    action_color = {
        "BUY": Fore.GREEN,
        "COVER": Fore.GREEN,
        "SELL": Fore.RED,
        "SHORT": Fore.RED,
        "HOLD": Fore.WHITE,
    }.get(action.upper(), Fore.WHITE)

    if is_summary:
        return_color = Fore.GREEN if return_pct >= 0 else Fore.RED
        benchmark_str = ""
        if benchmark_return_pct is not None:
            bench_color = Fore.GREEN if benchmark_return_pct >= 0 else Fore.RED
            benchmark_str = f"{bench_color}{benchmark_return_pct:+.2f}%{Style.RESET_ALL}"
        return [
            date,
            f"{Fore.WHITE}{Style.BRIGHT}PORTFOLIO SUMMARY{Style.RESET_ALL}",
            "",  # Action
            "",  # Quantity
            "",  # Price
            "",  # Long Shares
            "",  # Short Shares
            f"{Fore.YELLOW}${total_position_value:,.2f}{Style.RESET_ALL}",  # Total Position Value
            f"{Fore.CYAN}${cash_balance:,.2f}{Style.RESET_ALL}",  # Cash Balance
            f"{Fore.WHITE}${total_value:,.2f}{Style.RESET_ALL}",  # Total Value
            f"{return_color}{return_pct:+.2f}%{Style.RESET_ALL}",  # Return
            f"{Fore.YELLOW}{sharpe_ratio:.2f}{Style.RESET_ALL}" if sharpe_ratio is not None else "",  # Sharpe Ratio
            f"{Fore.YELLOW}{sortino_ratio:.2f}{Style.RESET_ALL}" if sortino_ratio is not None else "",  # Sortino Ratio
            f"{Fore.RED}{max_drawdown:.2f}%{Style.RESET_ALL}" if max_drawdown is not None else "",  # Max Drawdown (signed)
            benchmark_str,  # Benchmark (S&P 500)
        ]
    else:
        return [
            date,
            f"{Fore.CYAN}{ticker}{Style.RESET_ALL}",
            f"{action_color}{action.upper()}{Style.RESET_ALL}",
            f"{action_color}{quantity:,.0f}{Style.RESET_ALL}",
            f"{Fore.WHITE}{price:,.2f}{Style.RESET_ALL}",
            f"{Fore.GREEN}{long_shares:,.0f}{Style.RESET_ALL}",  # Long Shares
            f"{Fore.RED}{short_shares:,.0f}{Style.RESET_ALL}",  # Short Shares
            f"{Fore.YELLOW}{position_value:,.2f}{Style.RESET_ALL}",
        ]


def save_trading_report(result: dict, tickers: list[str], model_name: str, model_provider: str, start_date: str, end_date: str) -> Path | None:
    """
    Save trading report to a markdown file with complete analysis details.

    Args:
        result: Dictionary containing decisions and analyst signals
        tickers: List of ticker symbols
        model_name: Name of the LLM model used
        model_provider: Provider of the LLM model
        start_date: Analysis start date
        end_date: Analysis end date

    Returns:
        Path to the saved report file, or None if save failed
    """
    decisions = result.get("decisions")
    if not decisions:
        logger.warning("No trading decisions to save")
        return None

    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        tickers_str = "_".join(tickers[:3])
        if len(tickers) > 3:
            tickers_str += f"_etc{len(tickers)}"
        filename = f"{tickers_str}_{timestamp}.md"
        report_path = REPORT_DIR / filename

        lines: list[str] = []
        lines.append("# 对冲基金分析报告\n")
        lines.append(f"- **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"- **分析周期**: {start_date} ~ {end_date}")
        lines.append(f"- **模型**: {model_provider} - {model_name}\n")

        lines.append("## 分析股票概览\n")
        lines.append("| 代码 | 名称 | 操作 | 置信度 |")
        lines.append("|------|------|------|--------|")
        for ticker in tickers:
            stock_name = get_stock_name(ticker)
            decision = decisions.get(ticker, {})
            action = decision.get("action", "N/A").upper()
            confidence = decision.get("confidence", 0)
            lines.append(f"| {ticker} | {stock_name} | {action} | {confidence:.1f}% |")
        lines.append("")

        for ticker, decision in decisions.items():
            stock_name = get_stock_name(ticker)
            lines.append(f"## {ticker}（{stock_name}）详细分析\n")

            lines.append("### 1. 分析师信号汇总\n")
            lines.append("| 分析师 | 信号 | 置信度 |")
            lines.append("|--------|------|--------|")

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

            lines.append("### 2. 分析师详细推理\n")
            for agent, signals in result.get("analyst_signals", {}).items():
                if ticker not in signals or agent == "risk_management_agent":
                    continue

                signal = signals[ticker]
                agent_name = agent.replace("_agent", "").replace("_", " ").title()
                signal_type = signal.get("signal", "").upper()
                confidence = signal.get("confidence", 0)
                reasoning = signal.get("reasoning", "")

                if isinstance(reasoning, dict):
                    reasoning = json.dumps(reasoning, ensure_ascii=False, indent=2)

                lines.append(f"#### {agent_name}\n")
                lines.append(f"- **信号**: {signal_type}")
                lines.append(f"- **置信度**: {confidence}%")
                lines.append(f"- **推理过程**:\n")
                lines.append(f"```\n{reasoning}\n```\n")

            risk_signals = result.get("analyst_signals", {}).get("risk_management_agent", {})
            if ticker in risk_signals:
                lines.append("### 3. 风险管理分析\n")
                risk_data = risk_signals[ticker]

                lines.append("#### 仓位限制\n")
                lines.append(f"| 项目 | 值 |")
                lines.append("|------|------|")
                lines.append(f"| 剩余仓位限制 | {risk_data.get('remaining_position_limit', 'N/A')} |")
                lines.append(f"| 当前价格 | {risk_data.get('current_price', 'N/A')} |")
                lines.append("")

                vol_metrics = risk_data.get("volatility_metrics", {})
                if vol_metrics:
                    lines.append("#### 波动率指标\n")
                    lines.append(f"| 指标 | 值 |")
                    lines.append("|------|------|")
                    lines.append(f"| 日波动率 | {vol_metrics.get('daily_volatility', 'N/A'):.4f} |" if vol_metrics.get("daily_volatility") else "| 日波动率 | N/A |")
                    lines.append(f"| 年化波动率 | {vol_metrics.get('annualized_volatility', 'N/A'):.4f} |" if vol_metrics.get("annualized_volatility") else "| 年化波动率 | N/A |")
                    lines.append(f"| 波动率百分位 | {vol_metrics.get('volatility_percentile', 'N/A'):.2f}% |" if vol_metrics.get("volatility_percentile") else "| 波动率百分位 | N/A |")
                    lines.append(f"| 数据点数 | {vol_metrics.get('data_points', 'N/A')} |")
                    lines.append("")

                risk_reasoning = risk_data.get("reasoning", {})
                if risk_reasoning:
                    lines.append("#### 风险调整计算\n")
                    lines.append(f"| 项目 | 值 |")
                    lines.append("|------|------|")
                    lines.append(f"| 投资组合价值 | ${risk_reasoning.get('portfolio_value', 'N/A'):,.2f} |" if risk_reasoning.get("portfolio_value") else "| 投资组合价值 | N/A |")
                    lines.append(f"| 当前持仓价值 | ${risk_reasoning.get('current_position_value', 'N/A'):,.2f} |" if risk_reasoning.get("current_position_value") else "| 当前持仓价值 | N/A |")
                    lines.append(f"| 基础仓位限制 | {risk_reasoning.get('base_position_limit_pct', 'N/A')*100:.1f}% |" if risk_reasoning.get("base_position_limit_pct") else "| 基础仓位限制 | N/A |")
                    lines.append(f"| 组合仓位限制 | {risk_reasoning.get('combined_position_limit_pct', 'N/A')*100:.1f}% |" if risk_reasoning.get("combined_position_limit_pct") else "| 组合仓位限制 | N/A |")
                    lines.append(f"| 可用现金 | ${risk_reasoning.get('available_cash', 'N/A'):,.2f} |" if risk_reasoning.get("available_cash") else "| 可用现金 | N/A |")
                    lines.append(f"| 风险调整说明 | {risk_reasoning.get('risk_adjustment', 'N/A')} |")
                    lines.append("")

            lines.append("### 4. 最终交易决策\n")
            action = decision.get("action", "").upper()
            quantity = decision.get("quantity", 0)
            confidence = decision.get("confidence", 0)
            reasoning = decision.get("reasoning", "")

            action_emoji = {"BUY": "📈", "SELL": "📉", "SHORT": "🔻", "COVER": "🔄", "HOLD": "⏸️"}.get(action, "❓")

            lines.append(f"| 项目 | 值 |")
            lines.append("|------|------|")
            lines.append(f"| 操作 | {action_emoji} **{action}** |")
            lines.append(f"| 数量 | {quantity} 股 |")
            lines.append(f"| 置信度 | {confidence:.1f}% |")
            lines.append(f"| 决策理由 | {reasoning} |")
            lines.append("")

        lines.append("---\n")
        lines.append("*本报告由 AI 对冲基金系统自动生成*\n")
        lines.append("*审阅提示：请检查分析师推理逻辑是否合理，数据来源是否可靠，风险管理参数是否适当。*\n")

        report_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"[Report] 分析报告已保存: {report_path}")
        return report_path

    except Exception as e:
        logger.warning(f"[Report] 保存分析报告失败: {e}")
        return None


def save_daily_gainers_report(items: list[dict], trade_date: str, pct_threshold: float, output_path: str | None = None) -> Path | None:
    """
    保存每日涨幅筛选结果到 Markdown 文件
    """
    try:
        if output_path:
            report_path = Path(output_path)
        else:
            base_dir = Path("/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/stock/daliy")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            threshold_str = str(pct_threshold).replace(".", "p")
            date_str = trade_date.replace("-", "")
            filename = f"daily_gainers_{date_str}_gt{threshold_str}_{timestamp}.md"
            report_path = base_dir / filename

        report_path.parent.mkdir(parents=True, exist_ok=True)

        lines: list[str] = []
        lines.append("# A股每日涨幅筛选结果\n")
        lines.append(f"- **交易日期**: {trade_date}")
        lines.append(f"- **涨幅阈值**: > {pct_threshold:.2f}%")
        lines.append(f"- **结果数量**: {len(items)}\n")

        lines.append("| 股票代码 | 股票名称 | 涨幅 | 昨日收盘价 | 今日收盘价 |")
        lines.append("|----------|----------|------|------------|------------|")
        for item in items:
            ts_code = item.get("ts_code", "-")
            name = item.get("name", "-")
            pct_chg = item.get("pct_chg")
            pre_close = item.get("pre_close")
            close = item.get("close")
            pct_text = f"{pct_chg:.2f}%" if isinstance(pct_chg, (int, float)) else "-"
            pre_text = f"{pre_close:.2f}" if isinstance(pre_close, (int, float)) else "-"
            close_text = f"{close:.2f}" if isinstance(close, (int, float)) else "-"
            lines.append(f"| {ts_code} | {name} | {pct_text} | {pre_text} | {close_text} |")

        lines.append("")
        report_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"[Report] 涨幅筛选报告已保存: {report_path}")
        return report_path
    except Exception as e:
        logger.warning(f"[Report] 保存涨幅筛选报告失败: {e}")
        return None
