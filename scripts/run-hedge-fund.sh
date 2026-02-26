#!/bin/bash

# 运行对冲基金交易系统的脚本

# 默认值
DEFAULT_TICKER="600158"
DEFAULT_MODEL="MiniMax-M2.5"
DEFAULT_ANALYSTS=""
DEFAULT_OLAMA=false
DEFAULT_INITIAL_CASH=100000.0
DEFAULT_MARGIN_REQUIREMENT=0.0
DEFAULT_SHOW_REASONING=false
DEFAULT_SHOW_AGENT_GRAPH=false
DEFAULT_START_DATE=""
DEFAULT_END_DATE=""

# 显示帮助信息
show_help() {
    echo "Usage: ./scripts/run-hedge-fund.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --ticker TICKER         股票代码 (默认: $DEFAULT_TICKER)"
    echo "  --model MODEL           模型名称 (默认: $DEFAULT_MODEL)"
    echo "  --analysts ANALYSTS     分析师列表，逗号分隔 (默认: 交互式选择)"
    echo "  --analysts-all          使用所有分析师"
    echo "  --ollama                使用Ollama本地LLM"
    echo "  --initial-cash CASH     初始现金 (默认: $DEFAULT_INITIAL_CASH)"
    echo "  --margin-requirement MR 保证金要求比例 (默认: $DEFAULT_MARGIN_REQUIREMENT)"
    echo "  --start-date DATE       开始日期 (YYYY-MM-DD，默认: 30天前)"
    echo "  --end-date DATE         结束日期 (YYYY-MM-DD，默认: 当前日期)"
    echo "  --show-reasoning        显示每个代理的推理过程"
    echo "  --show-agent-graph      显示代理图表"
    echo "  --help                  显示此帮助信息"
    echo "  --help-analysts         显示所有可用的分析师信息"
    echo ""
    echo "示例:"
    echo "  ./scripts/run-hedge-fund.sh --ticker 600158 --model MiniMax-M2.5"
    echo "  ./scripts/run-hedge-fund.sh --ticker AAPL,MSFT --model gpt-4o --analysts-all"
    echo "  ./scripts/run-hedge-fund.sh --ticker 600519 --initial-cash 500000"
    echo "  ./scripts/run-hedge-fund.sh --ticker 600158 --start-date 2026-01-01 --end-date 2026-02-25"
    echo "  ./scripts/run-hedge-fund.sh --ticker 600158 --end-date 2026-02-25"
}

# 显示分析师帮助信息
show_analysts_help() {
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
    exit 0
}

# 解析命令行参数
TICKER="$DEFAULT_TICKER"
MODEL="$DEFAULT_MODEL"
ANALYSTS="$DEFAULT_ANALYSTS"
ANALYSTS_ALL=false
OLAMA="$DEFAULT_OLAMA"
INITIAL_CASH="$DEFAULT_INITIAL_CASH"
MARGIN_REQUIREMENT="$DEFAULT_MARGIN_REQUIREMENT"
START_DATE="$DEFAULT_START_DATE"
END_DATE="$DEFAULT_END_DATE"
SHOW_REASONING="$DEFAULT_SHOW_REASONING"
SHOW_AGENT_GRAPH="$DEFAULT_SHOW_AGENT_GRAPH"

while [[ $# -gt 0 ]]; do
    case $1 in
        --ticker)
            TICKER="$2"
            shift 2
            ;;
        --model)
            MODEL="$2"
            shift 2
            ;;
        --analysts)
            ANALYSTS="$2"
            shift 2
            ;;
        --analysts-all)
            ANALYSTS_ALL=true
            shift
            ;;
        --ollama)
            OLAMA=true
            shift
            ;;
        --initial-cash)
            INITIAL_CASH="$2"
            shift 2
            ;;
        --margin-requirement)
            MARGIN_REQUIREMENT="$2"
            shift 2
            ;;
        --start-date)
            START_DATE="$2"
            shift 2
            ;;
        --end-date)
            END_DATE="$2"
            shift 2
            ;;
        --show-reasoning)
            SHOW_REASONING=true
            shift
            ;;
        --show-agent-graph)
            SHOW_AGENT_GRAPH=true
            shift
            ;;
        --help)
            show_help
            exit 0
            ;;
        --help-analysts)
            show_analysts_help
            ;;
        *)
            echo "未知参数: $1"
            show_help
            exit 1
            ;;
    esac
done

# 构建命令
COMMAND="uv run python src/main.py --tickers $TICKER --model $MODEL"

# 添加日期参数
if [ -n "$START_DATE" ]; then
    COMMAND="$COMMAND --start-date $START_DATE"
fi
if [ -n "$END_DATE" ]; then
    COMMAND="$COMMAND --end-date $END_DATE"
fi

# 添加分析师参数
if [ "$ANALYSTS_ALL" = true ]; then
    COMMAND="$COMMAND --analysts-all"
elif [ -n "$ANALYSTS" ]; then
    COMMAND="$COMMAND --analysts $ANALYSTS"
fi

# 添加Ollama参数
if [ "$OLAMA" = true ]; then
    COMMAND="$COMMAND --ollama"
fi

# 添加资金参数
COMMAND="$COMMAND --initial-cash $INITIAL_CASH --margin-requirement $MARGIN_REQUIREMENT"

# 添加显示参数
if [ "$SHOW_REASONING" = true ]; then
    COMMAND="$COMMAND --show-reasoning"
fi

if [ "$SHOW_AGENT_GRAPH" = true ]; then
    COMMAND="$COMMAND --show-agent-graph"
fi

# 显示执行的命令
echo "执行命令: $COMMAND"
echo ""

# 执行命令
eval $COMMAND