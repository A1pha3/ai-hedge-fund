#!/usr/bin/env python3
"""
批量修复所有 agent 的 prompt，添加严格的不编造数据规则
"""

import re
from pathlib import Path


CRITICAL_RULES = """
                CRITICAL RULES (STRICTLY ENFORCED):
                1. ONLY use data explicitly provided in the provided data section
                2. NEVER invent, estimate, or make up any numbers or metrics
                3. If a data point is missing or null, state 'data not available'
                4. Do NOT reference any data not explicitly provided

"""


def add_critical_rules_to_file(file_path: Path) -> bool:
    """
    给单个文件添加严格规则
    """
    content = file_path.read_text(encoding="utf-8")

    # 检查是否已经有 CRITICAL RULES
    if "CRITICAL RULES" in content:
        print(f"✓ {file_path.name} 已包含规则，跳过")
        return False

    # 查找并替换不同模式的 system prompt
    patterns = [
        # 模式1: "You are X. Decide ... using only the provided facts."
        (
            r'(You are [A-Za-z\s]+?\.)( Decide [A-Za-z\s,]+?using only the provided facts\.)',
            lambda m: m.group(1) + m.group(2).replace("using only the provided facts", "using ONLY the provided facts") + CRITICAL_RULES
        ),
        # 模式2: 有 "When providing your reasoning" 或类似的详细说明
        (
            r'(When providing your reasoning, be thorough and specific by:)',
            lambda m: CRITICAL_RULES + m.group(1)
        ),
    ]

    modified = False
    for pattern, replacement in patterns:
        if re.search(pattern, content):
            content = re.sub(pattern, replacement, content)
            modified = True
            print(f"✓ 已修改 {file_path.name}")

    if modified:
        file_path.write_text(content, encoding="utf-8")

    return modified


def main():
    agents_dir = Path("src/agents")
    agent_files = list(agents_dir.glob("*.py"))

    print("=" * 80)
    print("批量修复 Agent Prompts")
    print("=" * 80)
    print(f"找到 {len(agent_files)} 个 agent 文件\n")

    modified_count = 0
    for file_path in sorted(agent_files):
        if file_path.name in ["__init__.py", "fundamentals.py", "technicals.py", "valuation.py",
                             "portfolio_manager.py", "risk_manager.py", "news_sentiment.py",
                             "sentiment.py", "growth_agent.py"]:
            print(f"○ 跳过 {file_path.name} (非 LLM-based agent)")
            continue

        if add_critical_rules_to_file(file_path):
            modified_count += 1

    print("\n" + "=" * 80)
    print(f"完成！共修改 {modified_count} 个文件")
    print("=" * 80)


if __name__ == "__main__":
    main()
