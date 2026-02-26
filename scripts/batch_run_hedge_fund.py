#!/usr/bin/env python3
"""
批量运行对冲基金分析脚本
从 Markdown 文件中读取股票代码列表，按涨幅从低到高排序后逐个进行分析
"""

import argparse
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


def parse_change_percent(change_str: str) -> float:
    """解析涨幅字符串为浮点数"""
    # 移除 % 符号并转换为浮点数
    return float(change_str.replace("%", ""))


def extract_stocks_from_markdown(file_path: Path) -> List[StockInfo]:
    """从 Markdown 文件中提取股票信息"""
    stocks = []
    content = file_path.read_text(encoding="utf-8")

    # 匹配表格行格式: | xxxxxx.SH | 股票名称 | xx.xx% | ...
    # 股票代码格式: xxxxxx.SH 或 xxxxxx.SZ 或 xxxxxx.BJ
    # 提取时去掉后缀，只保留6位数字代码
    pattern = r"\|\s*(\d{6})\.(?:SH|SZ|BJ)\s*\|\s*([^|]+)\|\s*([\d.]+)%\s*\|"

    for match in re.finditer(pattern, content):
        ticker = match.group(1).strip()
        name = match.group(2).strip()
        change_percent = float(match.group(3))

        stocks.append(StockInfo(ticker=ticker, name=name, change_percent=change_percent))

    return stocks


def build_run_hedge_fund_command(
    ticker: str,
    model: str,
    analysts_all: bool,
    start_date: Optional[str],
    end_date: Optional[str],
    show_reasoning: bool,
) -> List[str]:
    """构建 run-hedge-fund.sh 命令参数"""
    script_path = Path(__file__).parent / "run-hedge-fund.sh"
    cmd = [str(script_path), "--ticker", ticker, "--model", model]

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


def main() -> int:
    """主函数"""
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
--model MiniMax-M2.5 \
--start-date 2025-06-01 \
--analysts-all \
--show-reasoning
        """,
    )

    parser.add_argument("--file", type=Path, required=True, help="Markdown 文件路径，包含股票代码列表")
    parser.add_argument("--model", default="MiniMax-M2.5", help="模型名称 (默认: MiniMax-M2.5)")
    parser.add_argument("--analysts-all", action="store_true", help="使用所有分析师")
    parser.add_argument("--start-date", help="开始日期 (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="结束日期 (YYYY-MM-DD)")
    parser.add_argument("--show-reasoning", action="store_true", help="显示每个代理的推理过程")
    parser.add_argument("--limit", type=int, default=0, help="限制处理前 N 只股票")

    args = parser.parse_args()

    # 检查文件是否存在
    if not args.file.exists():
        print(f"错误: 文件不存在: {args.file}", file=sys.stderr)
        return 1

    # 提取股票信息
    print("正在从文件中提取股票代码...")
    stocks = extract_stocks_from_markdown(args.file)

    if not stocks:
        print("错误: 未从文件中找到有效的股票代码", file=sys.stderr)
        print("支持的格式: xxxxxx.SH, xxxxxx.SZ, xxxxxx.BJ", file=sys.stderr)
        return 1

    print(f"找到 {len(stocks)} 只股票")

    # 按涨幅从低到高排序
    stocks.sort(key=lambda x: x.change_percent)
    print("已按涨幅从低到高排序")

    # 如果设置了限制，只取前 N 只
    if args.limit > 0 and args.limit < len(stocks):
        stocks = stocks[: args.limit]
        print(f"限制处理前 {args.limit} 只股票")

    # 逐只处理股票
    print()
    print("=" * 40)
    print("开始批量分析...")
    print("=" * 40)
    print()

    total = len(stocks)
    processed = 0

    for stock in stocks:
        processed += 1
        print(f"[{processed}/{total}] 正在分析: {stock.ticker} ({stock.name}) - 涨幅: {stock.change_percent}%")
        print("-" * 40)

        # 构建并执行命令
        cmd = build_run_hedge_fund_command(
            ticker=stock.ticker,
            model=args.model,
            analysts_all=args.analysts_all,
            start_date=args.start_date,
            end_date=args.end_date,
            show_reasoning=args.show_reasoning,
        )

        return_code = run_hedge_fund_analysis(cmd)

        if return_code != 0:
            print(f"警告: {stock.ticker} 分析失败，返回码: {return_code}", file=sys.stderr)

        print()
        print("=" * 40)
        print()

        # 添加短暂延迟，避免请求过于频繁
        if processed < total:
            time.sleep(3)

    print(f"批量分析完成！共处理 {processed} 只股票")
    return 0


if __name__ == "__main__":
    sys.exit(main())
