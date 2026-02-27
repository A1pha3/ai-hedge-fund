#!/usr/bin/env python3
"""
调试脚本：检查 Warren Buffett agent 的 facts 数据
"""
import json
from pathlib import Path

# 首先，我们直接测试一下，用已有的数据快照
def test_facts_structure():
    """测试 facts 数据结构"""
    snapshot_path = Path("data/snapshots/001379/2026-02-27/financials.json")
    
    if snapshot_path.exists():
        with open(snapshot_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            metrics = data['financial_metrics'][0]
            print("=== 实际财务数据 ===")
            print(f"revenue_growth: {metrics.get('revenue_growth')}")
            print(f"earnings_growth: {metrics.get('earnings_growth')}")
            print(f"return_on_equity: {metrics.get('return_on_equity')}")
            print(f"operating_margin: {metrics.get('operating_margin')}")
            print(f"debt_to_equity: {metrics.get('debt_to_equity')}")
            print(f"current_ratio: {metrics.get('current_ratio')}")
            print()
            print("完整 metrics:")
            print(json.dumps(metrics, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    test_facts_structure()
