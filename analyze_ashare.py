#!/usr/bin/env python3
"""
A股股票分析示例脚本

使用方法:
    python analyze_ashare.py --ticker 600519 --start-date 2025-01-01 --end-date 2025-02-01
    
支持的股票代码格式:
    - 600519 (贵州茅台，自动判断上交所)
    - 000001 (平安银行，自动判断深交所)
    - sh600519 (带交易所前缀)
    - sz000001 (带交易所前缀)
"""

import sys
import os
import argparse
from datetime import datetime, timedelta

# 添加项目路径
sys.path.insert(0, '/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork')

from src.tools.akshare_api import (
    get_prices,
    get_financial_metrics,
    get_stock_info,
    is_ashare,
    get_mock_prices,
    get_mock_financial_metrics,
)


def print_header(title: str):
    """打印标题"""
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def analyze_stock(ticker: str, start_date: str, end_date: str, use_mock: bool = False):
    """
    分析 A 股股票
    
    Args:
        ticker: 股票代码
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        use_mock: 是否使用模拟数据
    """
    # 验证是否为 A 股代码
    if not is_ashare(ticker):
        print(f"错误: {ticker} 不是有效的 A 股代码")
        print("A 股代码格式: 6位数字 (如: 600519, 000001)")
        return
    
    print_header(f"A 股股票分析: {ticker}")
    
    # 1. 获取股票基本信息
    print("\n📊 股票基本信息")
    print("-" * 70)
    info = get_stock_info(ticker)
    if info:
        print(f"股票代码: {info.get('股票代码', 'N/A')}")
        print(f"股票名称: {info.get('股票简称', 'N/A')}")
        print(f"所属行业: {info.get('行业', 'N/A')}")
        print(f"最新价格: {info.get('最新', 'N/A')}")
        print(f"总市值: {info.get('总市值', 'N/A')}")
        print(f"流通市值: {info.get('流通市值', 'N/A')}")
        print(f"总股本: {info.get('总股本', 'N/A')}")
        print(f"上市时间: {info.get('上市时间', 'N/A')}")
    else:
        print("无法获取股票基本信息")
    
    # 2. 获取价格数据
    print("\n📈 价格数据分析")
    print("-" * 70)
    
    if use_mock:
        print("(使用模拟数据)")
        prices = get_mock_prices(ticker, start_date, end_date)
    else:
        prices = get_prices(ticker, start_date, end_date)
    
    if prices:
        print(f"数据区间: {prices[0].time} 至 {prices[-1].time}")
        print(f"数据条数: {len(prices)} 个交易日")
        print()

        # 计算价格统计
        opens = [p.open for p in prices]
        closes = [p.close for p in prices]
        highs = [p.high for p in prices]
        lows = [p.low for p in prices]
        volumes = [p.volume for p in prices]

        print(f"开盘价范围: {min(opens):.2f} - {max(opens):.2f}")
        print(f"收盘价范围: {min(closes):.2f} - {max(closes):.2f}")
        print(f"最高价: {max(highs):.2f}")
        print(f"最低价: {min(lows):.2f}")
        print(f"区间涨跌幅: {((closes[-1] - closes[0]) / closes[0] * 100):+.2f}%")
        print(f"平均成交量: {sum(volumes) / len(volumes):,.0f}")
        print()

        # 显示最近5天数据
        print("最近5个交易日:")
        print(f"{'日期':<12} {'开盘':<10} {'收盘':<10} {'最高':<10} {'最低':<10} {'成交量':<15}")
        print("-" * 70)
        for p in prices[-5:]:
            print(f"{p.time:<12} {p.open:<10.2f} {p.close:<10.2f} {p.high:<10.2f} {p.low:<10.2f} {p.volume:<15,}")
    else:
        print("无法获取价格数据")
        if not use_mock:
            print("提示: 可以使用 --mock 参数使用模拟数据进行测试")
    
    # 3. 获取财务指标
    print("\n💰 财务指标分析")
    print("-" * 70)
    
    if use_mock:
        print("(使用模拟数据)")
        metrics = get_mock_financial_metrics(ticker, end_date, limit=4)
    else:
        metrics = get_financial_metrics(ticker, end_date, limit=4)
    
    if metrics:
        print(f"{'报告期':<12} {'PE':<10} {'PB':<10} {'ROE':<10} {'毛利率':<10} {'净利率':<10}")
        print("-" * 70)
        for m in metrics:
            print(f"{m.report_period:<12} {m.price_to_earnings_ratio or 0:<10.2f} {m.price_to_book_ratio or 0:<10.2f} {m.return_on_equity or 0:<10.2f} {(m.gross_margin or 0) * 100:<10.2f}% {(m.net_margin or 0) * 100:<10.2f}%")
    else:
        print("无法获取财务指标")
        if not use_mock:
            print("提示: 可以使用 --mock 参数使用模拟数据进行测试")
    
    # 4. 投资建议
    print("\n📋 分析总结")
    print("-" * 70)
    
    if prices and metrics:
        latest_price = prices[-1].close
        latest_metric = metrics[0]

        print(f"当前价格: {latest_price:.2f}")
        if latest_metric.price_to_earnings_ratio:
            print(f"市盈率(PE): {latest_metric.price_to_earnings_ratio:.2f}")
        if latest_metric.price_to_book_ratio:
            print(f"市净率(PB): {latest_metric.price_to_book_ratio:.2f}")
        if latest_metric.return_on_equity:
            print(f"净资产收益率(ROE): {latest_metric.return_on_equity:.2f}%")
        
        print()
        print("注意: 以上分析仅基于历史数据，不构成投资建议。")
        print("投资有风险，入市需谨慎。")
    else:
        print("数据不足，无法生成分析总结")


def main():
    parser = argparse.ArgumentParser(
        description="A 股股票分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python analyze_ashare.py --ticker 600519
  python analyze_ashare.py --ticker 000001 --start-date 2025-01-01 --end-date 2025-02-01
  python analyze_ashare.py --ticker 600519 --mock
        """
    )
    
    parser.add_argument(
        "--ticker",
        type=str,
        required=True,
        help="股票代码 (如: 600519, 000001)"
    )
    
    parser.add_argument(
        "--start-date",
        type=str,
        default=(datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"),
        help="开始日期 (YYYY-MM-DD)，默认90天前"
    )
    
    parser.add_argument(
        "--end-date",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="结束日期 (YYYY-MM-DD)，默认今天"
    )
    
    parser.add_argument(
        "--mock",
        action="store_true",
        help="使用模拟数据（用于测试）"
    )
    
    args = parser.parse_args()
    
    # 执行分析
    analyze_stock(
        ticker=args.ticker,
        start_date=args.start_date,
        end_date=args.end_date,
        use_mock=args.mock
    )


if __name__ == "__main__":
    main()
