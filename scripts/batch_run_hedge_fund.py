#!/usr/bin/env python3
"""
批量运行对冲基金分析脚本
从 Markdown 文件中读取股票代码列表，按涨幅从低到高排序后逐个进行分析
"""

import argparse
import datetime
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class StockInfo:
    """股票信息"""

    ticker: str
    name: str
    change_percent: float
    market_type: str = ""  # 主板/创业板/科创板/北交所


def parse_change_percent(change_str: str) -> float:
    """解析涨幅字符串为浮点数"""
    # 移除 % 符号并转换为浮点数
    return float(change_str.replace("%", ""))


# 科创板/北交所 股票识别规则
_STAR_MARKET_PREFIXES = ("688",)  # 科创板
_BSE_PREFIXES = ("83", "87", "920")  # 北交所


def _detect_market_type(ticker: str, exchange_suffix: str) -> str:
    """根据股票代码和交易所后缀判断市场类型"""
    if exchange_suffix == "BJ" or any(ticker.startswith(p) for p in _BSE_PREFIXES):
        return "北交所"
    if any(ticker.startswith(p) for p in _STAR_MARKET_PREFIXES):
        return "科创板"
    if ticker.startswith("3"):
        return "创业板"
    return "主板"


def extract_stocks_from_markdown(file_path: Path) -> List[StockInfo]:
    """从 Markdown 文件中提取股票信息"""
    stocks = []
    content = file_path.read_text(encoding="utf-8")

    # 匹配表格行格式: | xxxxxx.SH | 股票名称 | xx.xx% | ...
    # 股票代码格式: xxxxxx.SH 或 xxxxxx.SZ 或 xxxxxx.BJ
    # 提取时去掉后缀，只保留6位数字代码
    pattern = r"\|\s*(\d{6})\.(SH|SZ|BJ)\s*\|\s*([^|]+)\|\s*([\d.]+)%\s*\|"

    for match in re.finditer(pattern, content):
        ticker = match.group(1).strip()
        exchange_suffix = match.group(2).strip()
        name = match.group(3).strip()
        change_percent = float(match.group(4))
        market_type = _detect_market_type(ticker, exchange_suffix)

        stocks.append(StockInfo(ticker=ticker, name=name, change_percent=change_percent, market_type=market_type))

    return stocks


def build_run_hedge_fund_command(
    ticker: str,
    model: Optional[str],
    analysts_all: bool,
    start_date: Optional[str],
    end_date: Optional[str],
    show_reasoning: bool,
) -> List[str]:
    """构建 run-hedge-fund.sh 命令参数"""
    script_path = Path(__file__).parent / "run-hedge-fund.sh"
    cmd = [str(script_path), "--ticker", ticker]

    if model:
        cmd.extend(["--model", model])

    if analysts_all:
        cmd.append("--analysts-all")

    if start_date:
        cmd.extend(["--start-date", start_date])

    if end_date:
        cmd.extend(["--end-date", end_date])

    if show_reasoning:
        cmd.append("--show-reasoning")

    return cmd


def run_hedge_fund_analysis(cmd: List[str]) -> int:
    """运行对冲基金分析脚本"""
    result = subprocess.run(cmd, capture_output=False, text=True)
    return result.returncode


def get_existing_tickers_from_reports(report_dir: Path, report_date: str) -> set[str]:
    """从报告目录中提取指定日期已生成报告的股票代码集合。"""
    existing_tickers: set[str] = set()
    if not report_dir.exists():
        return existing_tickers

    # 报告文件格式: 000001_20260302_123456.md
    pattern = re.compile(rf"^(\d{{6}})_{re.escape(report_date)}_\d{{6}}\.md$")
    for file_path in report_dir.glob(f"*_{report_date}_*.md"):
        match = pattern.match(file_path.name)
        if match:
            existing_tickers.add(match.group(1))

    return existing_tickers


def build_argument_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="批量运行对冲基金分析脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:

  # 基础用法 - 分析文件中的所有股票（按涨幅从低到高排序）
  python scripts/batch_run_hedge_fund.py --file data/stock/daliy/daily_gainers_20260226_gt5p0_20260226_233140.md

  # 使用所有分析师
  python scripts/batch_run_hedge_fund.py --file data/stock/daliy/daily_gainers_20260226_gt5p0_20260226_233140.md --analysts-all

  # 限制处理前10只股票（涨幅最低的10只）
  python scripts/batch_run_hedge_fund.py --file data/stock/daliy/daily_gainers_20260226_gt5p0_20260226_233140.md --limit 10

  # 显示推理过程
  python scripts/batch_run_hedge_fund.py --file data/stock/daliy/daily_gainers_20260226_gt5p0_20260226_233140.md --show-reasoning

  # 完整参数示例（注意：反斜杠后不能有空格）
  python scripts/batch_run_hedge_fund.py \
--file data/stock/daliy/daily_gainers_20260226_gt5p0_20260226_233140.md \
--start-date 2025-06-01 \
--analysts-all \
--show-reasoning
        """,
    )

    parser.add_argument("--file", type=Path, required=True, help="Markdown 文件路径，包含股票代码列表")
    parser.add_argument("--model", default=None, help="模型名称 (默认: 读取 .env 中的统一默认模型)")
    parser.add_argument("--analysts-all", action="store_true", help="使用所有分析师")
    parser.add_argument("--start-date", help="开始日期 (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="结束日期 (YYYY-MM-DD)")
    parser.add_argument("--show-reasoning", action="store_true", help="显示每个代理的推理过程")
    parser.add_argument("--limit", type=int, default=0, help="限制处理前 N 只股票")
    parser.add_argument("--skip-existing", action="store_true", default=True, help="跳过已生成当日报告的股票（默认开启）")
    parser.add_argument("--report-date", help="用于识别已生成报告的日期，格式 YYYYMMDD（默认: 今天）")
    parser.add_argument(
        "--exclude-boards",
        nargs="*",
        default=[],
        metavar="BOARD",
        help="排除指定板块的股票，可选值: 科创板 北交所 创业板 主板 (如: --exclude-boards 科创板 北交所)",
    )
    return parser


def _load_batch_stocks(args: argparse.Namespace) -> list[StockInfo] | None:
    """加载并准备待分析股票列表。"""
    if not args.file.exists():
        print(f"错误: 文件不存在: {args.file}", file=sys.stderr)
        return None
    print("正在从文件中提取股票代码...")
    stocks = extract_stocks_from_markdown(args.file)
    if not stocks:
        print("错误: 未从文件中找到有效的股票代码", file=sys.stderr)
        print("支持的格式: xxxxxx.SH, xxxxxx.SZ, xxxxxx.BJ", file=sys.stderr)
        return None
    print(f"找到 {len(stocks)} 只股票")
    if args.exclude_boards:
        excluded = set(args.exclude_boards)
        before_count = len(stocks)
        stocks = [s for s in stocks if s.market_type not in excluded]
        filtered_count = before_count - len(stocks)
        print(f"已过滤 {filtered_count} 只股票（排除板块: {', '.join(excluded)}），剩余 {len(stocks)} 只")
    stocks.sort(key=lambda x: x.change_percent)
    print("已按涨幅从低到高排序")
    if args.limit > 0 and args.limit < len(stocks):
        stocks = stocks[: args.limit]
        print(f"限制处理前 {args.limit} 只股票")
    return stocks


def _resolve_existing_tickers(args: argparse.Namespace) -> set[str]:
    """识别已生成报告的股票代码。"""
    report_date = args.report_date or datetime.datetime.now().strftime("%Y%m%d")
    project_root = Path(__file__).resolve().parent.parent
    reports_dir = project_root / "data" / "reports"
    existing_tickers = get_existing_tickers_from_reports(reports_dir, report_date) if args.skip_existing else set()
    if args.skip_existing:
        print(f"检测到 {len(existing_tickers)} 只股票在 {report_date} 已有报告，将自动跳过")
        print()
    return existing_tickers


def _should_retry_minimax(model: Optional[str], return_code: int) -> bool:
    """判断失败后是否按 MiniMax 限流策略重试。"""
    return return_code != 0 and isinstance(model, str) and "MiniMax" in model


def _retry_after_minimax_rate_limit(stock: StockInfo, cmd: List[str]) -> int:
    """在疑似 MiniMax 限流后等待并重试一次。"""
    print(f"\n警告: {stock.ticker} 分析失败。可能是 API 限流。")
    print("程序将休息 1 小时后再继续运行...")
    try:
        for i in range(3600, 0, -60):
            print(f"\r剩余休息时间: {i//60} 分钟... ", end="", flush=True)
            time.sleep(60)
        print("\n休息结束，准备重试该股票并继续后续分析。")
        return run_hedge_fund_analysis(cmd)
    except KeyboardInterrupt:
        print("\n用户中断休息，程序退出。")
        return 1


def _run_single_stock_analysis(stock: StockInfo, args: argparse.Namespace) -> int:
    """执行单只股票分析，并处理失败重试。"""
    cmd = build_run_hedge_fund_command(
        ticker=stock.ticker,
        model=args.model,
        analysts_all=args.analysts_all,
        start_date=args.start_date,
        end_date=args.end_date,
        show_reasoning=args.show_reasoning,
    )
    return_code = run_hedge_fund_analysis(cmd)
    if _should_retry_minimax(args.model, return_code):
        return_code = _retry_after_minimax_rate_limit(stock, cmd)
    if return_code != 0:
        print(f"错误: {stock.ticker} 分析仍然失败，返回码: {return_code}", file=sys.stderr)
    return return_code


def _process_batch_stock(
    stock: StockInfo,
    *,
    index: int,
    total: int,
    existing_tickers: set[str],
    args: argparse.Namespace,
) -> None:
    """处理单只股票的打印、跳过和执行逻辑。"""
    if args.skip_existing and stock.ticker in existing_tickers:
        print(f"[{index}/{total}] 跳过已完成: {stock.ticker} ({stock.name}) - 涨幅: {stock.change_percent}%")
        print("-" * 40)
        print()
        print("=" * 40)
        print()
        return
    print(f"[{index}/{total}] 正在分析: {stock.ticker} ({stock.name}) - 涨幅: {stock.change_percent}%")
    print("-" * 40)
    _run_single_stock_analysis(stock, args)
    print()
    print("=" * 40)
    print()


def main() -> int:
    """主函数"""
    args = build_argument_parser().parse_args()
    stocks = _load_batch_stocks(args)
    if stocks is None:
        return 1

    print()
    print("=" * 40)
    print("开始批量分析...")
    print("=" * 40)
    print()

    total = len(stocks)
    existing_tickers = _resolve_existing_tickers(args)
    for processed, stock in enumerate(stocks, start=1):
        _process_batch_stock(stock, index=processed, total=total, existing_tickers=existing_tickers, args=args)
        if processed < total and not (args.skip_existing and stock.ticker in existing_tickers):
            time.sleep(3)

    print(f"批量分析完成！共处理 {total} 只股票")
    return 0


if __name__ == "__main__":
    sys.exit(main())
