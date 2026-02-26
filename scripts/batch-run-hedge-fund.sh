#!/bin/bash

# 批量运行对冲基金分析脚本
# 从 Markdown 文件中读取股票代码列表，逐个进行分析

# 默认值
DEFAULT_MODEL="MiniMax-M2.5"
DEFAULT_ANALYSTS_ALL=false
DEFAULT_START_DATE=""
DEFAULT_END_DATE=""
DEFAULT_SHOW_REASONING=false

# 显示帮助信息
show_help() {
    echo "Usage: ./scripts/batch-run-hedge-fund.sh --file FILE [OPTIONS]"
    echo ""
    echo "必需参数:"
    echo "  --file FILE             Markdown 文件路径，包含股票代码列表"
    echo ""
    echo "可选参数:"
    echo "  --model MODEL           模型名称 (默认: $DEFAULT_MODEL)"
    echo "  --analysts-all          使用所有分析师"
    echo "  --start-date DATE       开始日期 (YYYY-MM-DD)"
    echo "  --end-date DATE         结束日期 (YYYY-MM-DD)"
    echo "  --show-reasoning        显示每个代理的推理过程"
    echo "  --limit N               限制处理前 N 只股票"
    echo "  --help                  显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  ./scripts/batch-run-hedge-fund.sh --file /path/to/daily_gainers.md --analysts-all"
    echo "  ./scripts/batch-run-hedge-fund.sh --file /path/to/daily_gainers.md --limit 10 --show-reasoning"
    echo "  ./scripts/batch-run-hedge-fund.sh --file /path/to/daily_gainers.md --start-date 2025-06-01 --analysts-all"
    echo "  ./scripts/batch-run-hedge-fund.sh --file /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/stock/daliy/daily_gainers_20260226_gt5p0_20260226_233140.md --model MiniMax-M2.5 --start-date 2025-06-01 --analysts-all --show-reasoning"
}

# 解析命令行参数
FILE=""
MODEL="$DEFAULT_MODEL"
ANALYSTS_ALL=false
START_DATE="$DEFAULT_START_DATE"
END_DATE="$DEFAULT_END_DATE"
SHOW_REASONING=false
LIMIT=0

while [[ $# -gt 0 ]]; do
    case $1 in
        --file)
            FILE="$2"
            shift 2
            ;;
        --model)
            MODEL="$2"
            shift 2
            ;;
        --analysts-all)
            ANALYSTS_ALL=true
            shift
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
        --limit)
            LIMIT="$2"
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

# 检查必需参数
if [ -z "$FILE" ]; then
    echo "错误: 必须指定 --file 参数"
    show_help
    exit 1
fi

if [ ! -f "$FILE" ]; then
    echo "错误: 文件不存在: $FILE"
    exit 1
fi

# 从 Markdown 文件中提取股票代码
# 股票代码格式: xxxxxxx.SH 或 xxxxxxx.SZ 或 xxxxxx.BJ
echo "正在从文件中提取股票代码..."

# 使用 grep 提取股票代码，格式为: | xxxxxx.SH | 或 | xxxxxx.SZ |
TICKERS=$(grep -oE '\|[[:space:]]*[0-9]{6}\.(SH|SZ|BJ)[[:space:]]*\|' "$FILE" | \
    sed 's/|//g' | \
    sed 's/[[:space:]]//g' | \
    sort -u)

# 统计股票数量
TICKER_COUNT=$(echo "$TICKERS" | grep -c '^' || echo "0")

if [ "$TICKER_COUNT" -eq 0 ]; then
    echo "错误: 未从文件中找到有效的股票代码"
    echo "支持的格式: xxxxxx.SH, xxxxxx.SZ, xxxxxx.BJ"
    exit 1
fi

echo "找到 $TICKER_COUNT 只股票"

# 如果设置了限制，只取前 N 只
if [ "$LIMIT" -gt 0 ] && [ "$LIMIT" -lt "$TICKER_COUNT" ]; then
    TICKERS=$(echo "$TICKERS" | head -n "$LIMIT")
    echo "限制处理前 $LIMIT 只股票"
fi

# 构建基础命令参数
BASE_ARGS="--model $MODEL"

if [ "$ANALYSTS_ALL" = true ]; then
    BASE_ARGS="$BASE_ARGS --analysts-all"
fi

if [ -n "$START_DATE" ]; then
    BASE_ARGS="$BASE_ARGS --start-date $START_DATE"
fi

if [ -n "$END_DATE" ]; then
    BASE_ARGS="$BASE_ARGS --end-date $END_DATE"
fi

if [ "$SHOW_REASONING" = true ]; then
    BASE_ARGS="$BASE_ARGS --show-reasoning"
fi

# 逐只处理股票
echo ""
echo "========================================"
echo "开始批量分析..."
echo "========================================"
echo ""

CURRENT=0
for TICKER in $TICKERS; do
    CURRENT=$((CURRENT + 1))
    echo "[$CURRENT/$TICKER_COUNT] 正在分析: $TICKER"
    echo "----------------------------------------"

    # 调用 run-hedge-fund.sh
    ./scripts/run-hedge-fund.sh --ticker "$TICKER" $BASE_ARGS

    echo ""
    echo "========================================"
    echo ""

    # 添加短暂延迟，避免请求过于频繁
    sleep 1
done

echo "批量分析完成！共处理 $CURRENT 只股票"
