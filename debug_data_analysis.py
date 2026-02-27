#!/usr/bin/env python3
"""
调试分析：检查各个 agent 之间的数据不一致性
"""

import json
from pathlib import Path


def analyze_data_issues():
    # 读取快照数据
    snapshot_path = Path("data/snapshots/001379/2026-02-27/financials.json")
    if not snapshot_path.exists():
        print(f"快照文件不存在: {snapshot_path}")
        return

    with open(snapshot_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    financial_metrics = data["financial_metrics"]
    line_items = data["line_items"]

    print("=" * 80)
    print("分析 001379 数据问题")
    print("=" * 80)

    # 1. 显示最新的财务指标
    print("\n【1】最新财务指标 (20250930):")
    latest_metrics = financial_metrics[0]
    print(f"  营收增长率 (revenue_growth): {latest_metrics['revenue_growth']:.2%}")
    print(f"  利润增长率 (earnings_growth): {latest_metrics['earnings_growth']:.2%}")
    print(f"  ROE: {latest_metrics['return_on_equity']:.2%}")
    print(f"  资产负债率 (debt_to_equity): {latest_metrics['debt_to_equity']:.2f}")

    # 2. 检查所有期的财务指标
    print("\n【2】所有期财务指标概览:")
    print(f"{'报告期':<12} {'营收增长':<12} {'利润增长':<12} {'ROE':<12}")
    print("-" * 48)
    for m in financial_metrics:
        rg = f"{m['revenue_growth']:.2%}" if m["revenue_growth"] is not None else "N/A"
        eg = f"{m['earnings_growth']:.2%}" if m["earnings_growth"] is not None else "N/A"
        roe = f"{m['return_on_equity']:.2%}" if m["return_on_equity"] is not None else "N/A"
        print(f"{m['report_period']:<12} {rg:<12} {eg:<12} {roe:<12}")

    # 3. 检查 line items 里的净利润
    print("\n【3】Line Items 净利润变化:")
    net_incomes = []
    for item in line_items:
        if item.get("net_income") is not None:
            net_incomes.append((item["report_period"], item["net_income"]))

    print(f"{'报告期':<12} {'净利润 (元)':<18}")
    print("-" * 32)
    for period, ni in net_incomes:
        print(f"{period:<12} {ni:,.2f}")

    # 4. 检查自由现金流
    print("\n【4】Line Items 自由现金流:")
    fcf_items = []
    for item in line_items:
        if item.get("free_cash_flow") is not None:
            fcf_items.append((item["report_period"], item["free_cash_flow"]))

    if fcf_items:
        print(f"{'报告期':<12} {'自由现金流 (元)':<20}")
        print("-" * 34)
        for period, fcf in fcf_items:
            print(f"{period:<12} {fcf:,.2f}")
    else:
        print("  无自由现金流数据")

    # 5. 对比报告中的问题
    print("\n" + "=" * 80)
    print("【问题分析】")
    print("=" * 80)
    print("\n报告中存在的不一致性:")
    print("1. Warren Buffett 说 'negative earnings growth (-26.1%)' - 但最新数据是 +9.80%")
    print("2. Rakesh Jhunjhunwala 说 'negative revenue CAGR of -1.3%' - 但最新数据是 +14.37%")
    print("3. Peter Lynch 说 'positive free cash flow of 344 million' - 这个是对的！最新FCF确实是3.44亿")
    print("4. Michael Burry 说 'No FCF data' - 但数据中确实有FCF")

    print("\n结论: 问题很可能出在 LLM 推理阶段，LLM 可能编造了一些数据！")
    print("建议: 检查各个 agent 的 prompt，确保它们使用真实数据而不是编造数据。")


if __name__ == "__main__":
    analyze_data_issues()
