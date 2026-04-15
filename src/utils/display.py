import os
from datetime import datetime
from pathlib import Path

from colorama import Fore, Style
from tabulate import tabulate

from src.tools.akshare_api import is_ashare
from src.tools.tushare_api import get_stock_name, get_stock_details

from .analysts import ANALYST_ORDER
from .display_print_helpers import build_agent_signal_table_rows, build_decision_table_rows, build_portfolio_summary_rows, find_portfolio_manager_reasoning, wrap_output_text
from .display_report_helpers import build_trading_report_lines, build_trading_report_path
from .display_reasoning_helpers import build_reasoning_dict_section, build_reasoning_fallback_table, build_reasoning_signal_section
from .logging import get_logger

logger = get_logger(__name__)

REPORT_DIR = Path("data/reports")


def _currency_symbol(tickers: list[str] | str | None = None) -> str:
    """Return currency symbol based on ticker type. A-share uses ¥, others use $."""
    if tickers is None:
        return "$"
    if isinstance(tickers, str):
        tickers = [tickers]
    if tickers and is_ashare(tickers[0]):
        return "¥"
    return "$"


def _format_list_date(date_str: str) -> str:
    """Format list date from YYYYMMDD to YYYY-MM-DD."""
    if date_str and len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return date_str


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
    analyst_signals = result.get("analyst_signals", {})

    for ticker, decision in decisions.items():
        action = decision.get("action", "").upper()
        confidence = decision.get("confidence", 0)
        logger.info(f"Trading decision for {ticker}: {action} with {confidence:.1f}% confidence")
        print(f"\n{Fore.WHITE}{Style.BRIGHT}Analysis for {Fore.CYAN}{ticker}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 50}{Style.RESET_ALL}")

        table_data = sort_agent_signals(build_agent_signal_table_rows(ticker, analyst_signals))

        print(f"\n{Fore.WHITE}{Style.BRIGHT}AGENT ANALYSIS:{Style.RESET_ALL} [{Fore.CYAN}{ticker}{Style.RESET_ALL}]")
        print(
            tabulate(
                table_data,
                headers=[f"{Fore.WHITE}Agent", "Signal", "Confidence", "Reasoning"],
                tablefmt="grid",
                colalign=("left", "center", "right", "left"),
            )
        )

        print(f"\n{Fore.WHITE}{Style.BRIGHT}TRADING DECISION:{Style.RESET_ALL} [{Fore.CYAN}{ticker}{Style.RESET_ALL}]")
        print(tabulate(build_decision_table_rows(decision), tablefmt="grid", colalign=("left", "left")))

    print(f"\n{Fore.WHITE}{Style.BRIGHT}PORTFOLIO SUMMARY:{Style.RESET_ALL}")
    portfolio_data = build_portfolio_summary_rows(decisions, analyst_signals)

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

    portfolio_manager_reasoning = find_portfolio_manager_reasoning(decisions)
    if portfolio_manager_reasoning:
        print(f"\n{Fore.WHITE}{Style.BRIGHT}Portfolio Strategy:{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{wrap_output_text(portfolio_manager_reasoning)}{Style.RESET_ALL}")


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
        # Note: Terminal portfolio summary uses $ parsed from formatted strings; report uses _currency_symbol()
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
    if ticker_rows:
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
    else:
        print("No ticker rows for this backtest day.")

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
    total_value: float | None = None,
    return_pct: float | None = None,
    cash_balance: float | None = None,
    total_position_value: float | None = None,
    sharpe_ratio: float | None = None,
    sortino_ratio: float | None = None,
    max_drawdown: float | None = None,
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


def _format_reasoning_to_markdown(reasoning: dict | str) -> str:
    """将 reasoning 字典转换为 Markdown 表格格式"""
    if isinstance(reasoning, str):
        return reasoning

    if not isinstance(reasoning, dict):
        return str(reasoning)

    lines: list[str] = []

    # 处理包含 chinese_explanation 的情况（技术分析Agent）
    if "chinese_explanation" in reasoning:
        lines.append(reasoning["chinese_explanation"])
        return "\n".join(lines)

    # 处理标准信号结构
    for key, value in reasoning.items():
        if isinstance(value, dict):
            section_title = key.replace("_", " ").title()
            if any(field in value for field in ("signal", "confidence", "details", "metrics")):
                lines.extend(build_reasoning_signal_section(section_title, value))
            else:
                lines.extend(build_reasoning_dict_section(section_title, value))

        elif key in ["reasoning", "analysis"] and isinstance(value, str):
            lines.append(f"\n**分析说明**: {value}")

    if not lines:
        lines.extend(build_reasoning_fallback_table(reasoning))

    return "\n".join(lines)


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
        generated_at = datetime.now()
        report_path = build_trading_report_path(REPORT_DIR, tickers, generated_at)
        lines = build_trading_report_lines(
            result=result,
            decisions=decisions,
            tickers=tickers,
            model_name=model_name,
            model_provider=model_provider,
            start_date=start_date,
            end_date=end_date,
            generated_at=generated_at,
            get_stock_details=get_stock_details,
            get_stock_name=get_stock_name,
            format_list_date=_format_list_date,
            format_reasoning_to_markdown=_format_reasoning_to_markdown,
            currency_symbol=_currency_symbol,
        )

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

        lines.append("| 股票代码 | 股票名称 | 涨幅 | 昨日收盘价 | 今日收盘价 | 地域 | 所属行业 | 市场类型 | 上市日期 |")
        lines.append("|----------|----------|------|------------|------------|------|----------|----------|----------|")
        for item in items:
            ts_code = item.get("ts_code", "-")
            name = item.get("name", "-")
            area = item.get("area", "-")
            industry = item.get("industry", "-")
            market = item.get("market", "-")
            list_date = item.get("list_date", "-")
            pct_chg = item.get("pct_chg")
            pre_close = item.get("pre_close")
            close = item.get("close")
            pct_text = f"{pct_chg:.2f}%" if isinstance(pct_chg, (int, float)) else "-"
            pre_text = f"{pre_close:.2f}" if isinstance(pre_close, (int, float)) else "-"
            close_text = f"{close:.2f}" if isinstance(close, (int, float)) else "-"
            lines.append(f"| {ts_code} | {name} | {pct_text} | {pre_text} | {close_text} | {area} | {industry} | {market} | {list_date} |")

        lines.append("")
        report_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"[Report] 涨幅筛选报告已保存: {report_path}")
        return report_path
    except Exception as e:
        logger.warning(f"[Report] 保存涨幅筛选报告失败: {e}")
        return None
