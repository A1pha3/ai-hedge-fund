#!/usr/bin/env python3
"""测试 Tushare 数据获取"""

import os
import sys

# 添加项目路径
sys.path.insert(0, '/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork')

from src.tools.tushare_api import (
    get_ashare_prices_with_tushare,
    get_ashare_financial_metrics_with_tushare
)

# 测试股票代码
ticker = "600158"  # 中体产业
start_date = "2024-01-01"
end_date = "2024-12-31"

print(f"测试获取股票 {ticker} 数据")
print(f"日期范围: {start_date} ~ {end_date}")
print("-" * 50)

# 测试价格数据
print("\n1. 测试获取价格数据...")
prices = get_ashare_prices_with_tushare(ticker, start_date, end_date)
if prices:
    print(f"✓ 成功获取 {len(prices)} 条价格数据")
    print(f"  第一条: {prices[0]}")
    print(f"  最后一条: {prices[-1]}")
else:
    print("✗ 未获取到价格数据")

# 测试财务指标
print("\n2. 测试获取财务指标...")
metrics = get_ashare_financial_metrics_with_tushare(ticker, end_date, limit=10)
if metrics:
    print(f"✓ 成功获取 {len(metrics)} 条财务指标")
    for i, m in enumerate(metrics[:3]):
        print(f"  记录 {i+1}: {m}")
else:
    print("✗ 未获取到财务指标")

print("\n" + "-" * 50)
if not prices or len(metrics) < 5:
    print("⚠️ 数据不足，可能导致 'Insufficient data' 错误")
    print("建议检查:")
    print("  1. TUSHARE_TOKEN 是否有效")
    print("  2. 股票代码是否正确")
    print("  3. Tushare 账户是否有权限获取该数据")
else:
    print("✓ 数据获取正常")
