#!/usr/bin/env python3
import os
import re
import shutil
import sys
import time
from datetime import datetime

# 确保项目根目录在 sys.path 中，以便导入 src 包
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _project_root)

# 加载 .env 文件中的环境变量（TUSHARE_TOKEN 等）
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_project_root, ".env"))
except ImportError:
    pass

from src.tools.tushare_api import get_stock_details


TABLE_HEADER = "| 代码 | 名称 | 操作 | 置信度 | 涨幅 | 昨日收盘价 | 今日收盘价 | 地域 | 所属行业 | 市场类型 | 上市日期 |"
TABLE_SEPARATOR = "|------|------|------|--------|------|-----------|-----------|------|---------|---------|---------|"


def _fetch_details_with_retry(ticker: str, max_retries: int = 3) -> dict:
    """获取股票详情，带重试和速率限制保护"""
    for attempt in range(max_retries):
        details = get_stock_details(ticker)
        # 如果成功获取到名称（不为原始 ticker），直接返回
        if details.get("name") != ticker or details.get("area") != "N/A":
            return details
        if attempt < max_retries - 1:
            time.sleep(1)
    return details


def generate_summary():
    reports_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../data/reports"))
    output_file = os.path.join(reports_dir, f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")

    if not os.path.exists(reports_dir):
        print(f"错误: 目录 {reports_dir} 不存在")
        return

    buy_list = []
    hold_list = []
    short_list = []

    # 记录每只股票的分类，用于后续文件归类
    ticker_category = {}  # ticker -> "buy" | "hold" | "short"

    # 匹配表格行的正则，例如: | 000010 | 美丽生态 | SHORT | 88.0% |
    row_pattern = re.compile(r"\|\s*([0-9]{6})\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|")

    processed_tickers = set()

    # 获取所有 md 文件，按修改时间倒序排列（最新的在前）
    files = [f for f in os.listdir(reports_dir) if f.endswith(".md") and f.startswith(("0", "3", "6", "9"))]
    files.sort(key=lambda x: os.path.getmtime(os.path.join(reports_dir, x)), reverse=True)

    # 第一遍：收集所有待处理的股票
    ticker_entries = []  # [(ticker, name, action, confidence), ...]

    for filename in files:
        filepath = os.path.join(reports_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            matches = row_pattern.findall(content)
            for m in matches:
                ticker, name, action, confidence = [i.strip() for i in m]
                if ticker in processed_tickers:
                    continue
                processed_tickers.add(ticker)
                ticker_entries.append((ticker, name, action, confidence))

    # 第二遍：批量获取股票详细信息
    total = len(ticker_entries)
    print(f"共发现 {total} 只股票，正在获取详细信息...")

    for idx, (ticker, name, action, confidence) in enumerate(ticker_entries, 1):
        details = _fetch_details_with_retry(ticker)
        stock_name = details.get("name", name)
        pct_chg = details.get("pct_chg", "N/A")
        pre_close = details.get("pre_close", "N/A")
        close = details.get("close", "N/A")
        area = details.get("area", "N/A")
        industry = details.get("industry", "N/A")
        market = details.get("market", "N/A")
        list_date = details.get("list_date", "N/A")

        entry = f"| {ticker} | {stock_name} | **{action}** | {confidence} | {pct_chg} | {pre_close} | {close} | {area} | {industry} | {market} | {list_date} |"

        if "BUY" in action.upper():
            buy_list.append(entry)
            ticker_category[ticker] = "buy"
        elif "HOLD" in action.upper():
            hold_list.append(entry)
            ticker_category[ticker] = "hold"
        else:
            short_list.append(entry)
            ticker_category[ticker] = "short"

        if idx % 10 == 0 or idx == total:
            print(f"  进度: {idx}/{total}")

        # tushare 限速保护：每次请求间隔 0.3s
        time.sleep(0.3)

    # 格式化输出内容
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    buy_rows = "\n".join(sorted(buy_list))
    hold_rows = "\n".join(sorted(hold_list))
    short_rows = "\n".join(sorted(short_list))

    markdown_content = f"""# 对冲基金投资建议汇总报告

**生成时间**: {ts}
**扫描目录**: `{reports_dir}`

## 1. BUY (买入建议) - 共 {len(buy_list)} 只
{TABLE_HEADER}
{TABLE_SEPARATOR}
{buy_rows}

## 2. HOLD (观望建议) - 共 {len(hold_list)} 只
{TABLE_HEADER}
{TABLE_SEPARATOR}
{hold_rows}

## 3. SHORT (卖出/减持建议) - 共 {len(short_list)} 只
{TABLE_HEADER}
{TABLE_SEPARATOR}
{short_rows}

---
*本报告由脚本自动提取，仅汇总最新分析结果。*
"""

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(markdown_content)

    print(f"成功生成汇总报告: {output_file}")
    print(f"统计: BUY({len(buy_list)}), HOLD({len(hold_list)}), SHORT({len(short_list)})")

    # 将报告文件按分类复制到 buy/hold/short 子目录
    _classify_reports(reports_dir, ticker_category, files)


def _classify_reports(reports_dir: str, ticker_category: dict, all_files: list):
    """将报告文件按 buy/hold/short 分类复制到对应子目录"""
    # 创建分类目录
    for cat in ("buy", "hold", "short"):
        cat_dir = os.path.join(reports_dir, cat)
        os.makedirs(cat_dir, exist_ok=True)
        # 清空目录中的旧文件，确保分类结果是最新的
        for old_file in os.listdir(cat_dir):
            old_path = os.path.join(cat_dir, old_file)
            if os.path.isfile(old_path) and old_file.endswith(".md"):
                os.remove(old_path)

    # 遍历所有报告文件，根据 ticker 前缀归类
    copied = {"buy": 0, "hold": 0, "short": 0}
    for filename in all_files:
        # 从文件名提取 ticker（前6位数字）
        match = re.match(r"^(\d{6})_", filename)
        if not match:
            continue
        ticker = match.group(1)
        category = ticker_category.get(ticker)
        if not category:
            continue

        src_path = os.path.join(reports_dir, filename)
        dst_path = os.path.join(reports_dir, category, filename)
        shutil.move(src_path, dst_path)
        copied[category] += 1

    print(f"报告文件分类完成: buy/{copied['buy']}份, hold/{copied['hold']}份, short/{copied['short']}份")
    print(f"分类目录: {reports_dir}/{{buy,hold,short}}/")


if __name__ == "__main__":
    generate_summary()
