#!/bin/bash

# 获取每日涨幅超过阈值的 A 股列表（默认剔除 ST）

DEFAULT_TRADE_DATE="$(date +%Y-%m-%d)"
DEFAULT_PCT_THRESHOLD=5.0
DEFAULT_OUTPUT_MD=""

show_help() {
    echo "Usage: ./scripts/run-daily-gainers.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --trade-date DATE       交易日期 (YYYY-MM-DD，默认: $DEFAULT_TRADE_DATE)"
    echo "  --pct-threshold VALUE   涨幅阈值 (默认: $DEFAULT_PCT_THRESHOLD)"
    echo "  --output-md PATH        输出 Markdown 文件路径 (默认: data/stock/daliy)"
    echo "  --help                  显示此帮助信息"
    echo ""
    echo "说明:"
    echo "  - 默认剔除 ST / *ST 股票"
    echo "  - 若指定日期非交易日，会自动回退到最近交易日"
    echo ""
    echo "示例:"
    echo "  ./scripts/run-daily-gainers.sh"
    echo "  ./scripts/run-daily-gainers.sh --pct-threshold 5"
    echo "  ./scripts/run-daily-gainers.sh --trade-date 2025-02-26 --pct-threshold 3.5"
    echo "  ./scripts/run-daily-gainers.sh --output-md /tmp/gainers.md"
}

TRADE_DATE="$DEFAULT_TRADE_DATE"
PCT_THRESHOLD="$DEFAULT_PCT_THRESHOLD"
OUTPUT_MD="$DEFAULT_OUTPUT_MD"

while [[ $# -gt 0 ]]; do
    case $1 in
        --trade-date)
            TRADE_DATE="$2"
            shift 2
            ;;
        --pct-threshold)
            PCT_THRESHOLD="$2"
            shift 2
            ;;
        --output-md)
            OUTPUT_MD="$2"
            shift 2
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            show_help
            exit 1
            ;;
    esac
done

COMMAND="uv run python src/main.py --daily-gainers --trade-date $TRADE_DATE --pct-threshold $PCT_THRESHOLD"

if [ -n "$OUTPUT_MD" ]; then
    COMMAND="$COMMAND --output-md $OUTPUT_MD"
fi

echo "执行命令: $COMMAND"
echo ""

eval $COMMAND
