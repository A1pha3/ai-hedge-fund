#!/bin/bash

# 显示所有可用的分析师信息

# 执行Python命令来获取分析师列表
uv run python -c '
from src.utils.analysts import ANALYST_CONFIG

print("可用分析师列表:")
print("-" * 80)

# 按顺序排序
for key, config in sorted(ANALYST_CONFIG.items(), key=lambda x: x[1]["order"]):
    print(f"分析师: {config["display_name"]}")
    print(f"键名: {key}")
    print(f"描述: {config["description"]}")
    print(f"投资风格: {config["investing_style"]}")
    print("-" * 80)
'

# 显示使用示例
echo "\n使用示例:"
echo "  ./scripts/run-hedge-fund.sh --ticker 600158 --model MiniMax-M2.5 --analysts warren_buffett,ben_graham"
echo "  ./scripts/run-hedge-fund.sh --ticker AAPL --model gpt-4o --analysts-all"
echo "  ./scripts/run-hedge-fund.sh --ticker MSFT --model gpt-4o --analysts technical_analyst,fundamentals_analyst"
