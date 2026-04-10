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

from src.project_env import load_project_dotenv

load_project_dotenv()

from src.tools.tushare_api import get_stock_details


TABLE_HEADER = "| 代码 | 名称 | 涨幅 | 昨日收盘价 | 今日收盘价 | 地域 | 所属行业 | 市场类型 | 上市日期 | 操作 | 置信度 |"
TABLE_SEPARATOR = "|------|------|------|-----------|-----------|------|---------|---------|---------|------|--------|"
OLD_ROW_PATTERN = re.compile(r"\|\s*([0-9]{6})\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|")
DETAIL_ROW_PATTERN = re.compile(r"\|\s*([0-9]{6})\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|")


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


def _resolve_reports_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../data/reports"))


def _build_output_file(reports_dir: str) -> str:
    return os.path.join(reports_dir, f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")


def _append_entry(action: str, entry: str, ticker: str, buy_list: list, hold_list: list, short_list: list, ticker_category: dict) -> None:
    if "BUY" in action.upper():
        buy_list.append(entry)
        ticker_category[ticker] = "buy"
    elif "HOLD" in action.upper():
        hold_list.append(entry)
        ticker_category[ticker] = "hold"
    else:
        short_list.append(entry)
        ticker_category[ticker] = "short"


def _report_files(reports_dir: str) -> list[str]:
    files = [f for f in os.listdir(reports_dir) if f.endswith(".md") and f.startswith(("0", "3", "6", "9"))]
    files.sort(key=lambda x: os.path.getmtime(os.path.join(reports_dir, x)), reverse=True)
    return files


def _collect_detailed_matches(content: str, processed_tickers: set[str], buy_list: list, hold_list: list, short_list: list, ticker_category: dict) -> bool:
    matches = DETAIL_ROW_PATTERN.findall(content)
    if not matches:
        return False
    for match in matches:
        ticker = match[0].strip()
        if ticker in processed_tickers:
            continue
        processed_tickers.add(ticker)
        action = match[9].strip()
        row_data = [f" {item.strip()} " for item in match]
        _append_entry(action, "|" + "|".join(row_data) + "|", ticker, buy_list, hold_list, short_list, ticker_category)
    return True


def _collect_legacy_matches(filename: str, content: str, processed_tickers: set[str], buy_list: list, hold_list: list, short_list: list, ticker_category: dict) -> None:
    for match in OLD_ROW_PATTERN.findall(content):
        ticker, name, action, confidence = [item.strip() for item in match]
        if ticker in processed_tickers:
            continue
        processed_tickers.add(ticker)

        print(f"警告: 报告 {filename} 中 {ticker} 详情缺失，正在尝试使用 Tushare 补充...")
        details = _fetch_details_with_retry(ticker)
        entry = (
            f"| {ticker} | {details.get('name', name)} | {details.get('pct_chg', 'N/A')} | {details.get('pre_close', 'N/A')} | {details.get('close', 'N/A')} | "
            f"{details.get('area', 'N/A')} | {details.get('industry', 'N/A')} | {details.get('market', 'N/A')} | {details.get('list_date', 'N/A')} | **{action}** | {confidence} |"
        )
        _append_entry(action, entry, ticker, buy_list, hold_list, short_list, ticker_category)
        time.sleep(0.3)


def _build_markdown_content(reports_dir: str, buy_list: list, hold_list: list, short_list: list) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    buy_rows = "\n".join(sorted(buy_list))
    hold_rows = "\n".join(sorted(hold_list))
    short_rows = "\n".join(sorted(short_list))
    return f"""# 对冲基金投资建议汇总报告

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


def generate_summary():
    reports_dir = _resolve_reports_dir()
    output_file = _build_output_file(reports_dir)

    if not os.path.exists(reports_dir):
        print(f"错误: 目录 {reports_dir} 不存在")
        return

    buy_list = []
    hold_list = []
    short_list = []

    # 记录每只股票的分类，用于后续文件归类
    ticker_category = {}  # ticker -> "buy" | "hold" | "short"

    processed_tickers = set()
    files = _report_files(reports_dir)

    # 扫描收集
    for filename in files:
        filepath = os.path.join(reports_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            if _collect_detailed_matches(content, processed_tickers, buy_list, hold_list, short_list, ticker_category):
                continue
            _collect_legacy_matches(filename, content, processed_tickers, buy_list, hold_list, short_list, ticker_category)

    markdown_content = _build_markdown_content(reports_dir, buy_list, hold_list, short_list)

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
