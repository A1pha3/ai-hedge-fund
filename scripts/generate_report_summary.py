#!/usr/bin/env python3
import os
import re
from datetime import datetime

def generate_summary():
    reports_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../data/reports"))
    output_file = os.path.join(reports_dir, f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")
    
    if not os.path.exists(reports_dir):
        print(f"错误: 目录 {reports_dir} 不存在")
        return

    buy_list = []
    hold_list = []
    short_list = []

    # 匹配表格行的正则，例如: | 000010 | 美丽生态 | SHORT | 88.0% |
    row_pattern = re.compile(r"\|\s*([0-9]{6})\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|")

    processed_tickers = set()

    # 获取所有 md 文件，按修改时间倒序排列（最新的在前）
    files = [f for f in os.listdir(reports_dir) if f.endswith(".md") and f.startswith(("0", "3", "6"))]
    files.sort(key=lambda x: os.path.getmtime(os.path.join(reports_dir, x)), reverse=True)

    for filename in files:
        filepath = os.path.join(reports_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            # 查找“分析股票概览”部分的表格行
            matches = row_pattern.findall(content)
            for m in matches:
                ticker, name, action, confidence = [i.strip() for i in m]
                # 每个股票只记录最新的结果
                if ticker in processed_tickers:
                    continue
                
                entry = f"| {ticker} | {name} | **{action}** | {confidence} |"
                processed_tickers.add(ticker)

                if "BUY" in action.upper():
                    buy_list.append(entry)
                elif "HOLD" in action.upper():
                    hold_list.append(entry)
                else:
                    short_list.append(entry)

    # 格式化输出内容
    markdown_content = f"""# 对冲基金投资建议汇总报告

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**扫描目录**: `{reports_dir}`

## 1. BUY (买入建议) - 共 {len(buy_list)} 只
| 代码 | 名称 | 操作 | 置信度 |
|------|------|------|--------|
""" + "\n".join(sorted(buy_list)) + f"""

## 2. HOLD (观望建议) - 共 {len(hold_list)} 只
| 代码 | 名称 | 操作 | 置信度 |
|------|------|------|--------|
""" + "\n".join(sorted(hold_list)) + f"""

## 3. SHORT (卖出/减持建议) - 共 {len(short_list)} 只
| 代码 | 名称 | 操作 | 置信度 |
|------|------|------|--------|
""" + "\n".join(sorted(short_list)) + """

---
*本报告由脚本自动提取，仅汇总最新分析结果。*
"""

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(markdown_content)
    
    print(f"成功生成汇总报告: {output_file}")
    print(f"统计: BUY({len(buy_list)}), HOLD({len(hold_list)}), SHORT({len(short_list)})")

if __name__ == "__main__":
    generate_summary()
