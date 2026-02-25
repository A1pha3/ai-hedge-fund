#!/usr/bin/env python3
"""测试数据流 - 从 API 到 Agent"""

import os
import sys

sys.path.insert(0, '/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork')

# 设置环境变量
os.environ['TUSHARE_TOKEN'] = 'ab9ec94882de89ccf50a06744281e9f6bdeef378b509b30f8eaef7aa'

from src.tools.api import get_financial_metrics, get_prices
from src.tools.akshare_api import is_ashare

ticker = "600158"
end_date = "2024-12-31"
start_date = "2024-01-01"

print(f"测试股票: {ticker}")
print(f"是否为A股: {is_ashare(ticker)}")
print("-" * 50)

# 测试价格数据
print("\n1. 测试 get_prices...")
prices = get_prices(ticker, start_date, end_date)
if prices:
    print(f"✓ 成功获取 {len(prices)} 条价格数据")
else:
    print("✗ 未获取到价格数据")

# 测试财务指标
print("\n2. 测试 get_financial_metrics...")
metrics = get_financial_metrics(ticker, end_date, period="ttm", limit=10)
if metrics:
    print(f"✓ 成功获取 {len(metrics)} 条财务指标")
    # 检查数据内容
    print(f"\n第一条数据:")
    m = metrics[0]
    print(f"  - report_period: {m.report_period}")
    print(f"  - roe: {m.return_on_equity}")
    print(f"  - market_cap: {m.market_cap}")
    print(f"  - revenue_growth: {m.revenue_growth}")
else:
    print("✗ 未获取到财务指标")

# 检查数据是否满足分析要求
print("\n3. 检查数据质量...")
if metrics and len(metrics) >= 5:
    print(f"✓ 财务指标数量足够 ({len(metrics)} >= 5)")
else:
    print(f"✗ 财务指标数量不足 ({len(metrics) if metrics else 0} < 5)")
