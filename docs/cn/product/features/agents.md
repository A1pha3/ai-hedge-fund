# 8. Agent 系统

> 本节对应主文档 §8,包含 12 投资者 Agent、6 分析师 Agent、2 管理 Agent、Agent 编排。

## 8.1 投资者 Agent (12 个)

| # | Agent | 状态 | 投资风格 |
|---|-------|------|----------|
| 1 | Warren Buffett | ✅ | 价值投资 + 长期持有 |
| 2 | Charlie Munger | ✅ | 质量企业 + 理性决策 |
| 3 | Ben Graham | ✅ | 安全边际 + 系统性价值分析 |
| 4 | Peter Lynch | ✅ | 买你了解的 + 10 倍股 |
| 5 | Phil Fisher | ✅ | Scuttlebutt 调研 + 长期成长 |
| 6 | Bill Ackman | ✅ | 激进投资 + 逆向操作 |
| 7 | Cathie Wood | ✅ | 颠覆性创新 + 成长投资 |
| 8 | Michael Burry | ✅ | 深度基本面 + 逆向做空 |
| 9 | Mohnish Pabrai | ✅ | Dhandho 价值投资 |
| 10 | Rakesh Jhunjhunwala | ✅ | 新兴市场 + 高成长行业 |
| 11 | Stanley Druckenmiller | ✅ | 宏观趋势 + 自上而下 |
| 12 | Aswath Damodaran | ✅ | 估值大师 + 内在价值 |

## 8.2 分析师 Agent (6 个)

| # | Agent | 状态 | 职责 |
|---|-------|------|------|
| 1 | Technical Analyst | ✅ | 技术指标 + 价格行为 |
| 2 | Fundamentals Analyst | ✅ | 财务报表 + 经济指标 |
| 3 | Growth Analyst | ✅ | 成长趋势 + 估值 |
| 4 | News Sentiment Analyst | ✅ | 新闻情绪分析 |
| 5 | Sentiment Analyst | ✅ | 市场情绪 + 行为分析 |
| 6 | Valuation Analyst | ✅ | 公司估值 + 模型分析 |

## 8.3 管理 Agent

| # | Agent | 状态 | 职责 |
|---|-------|------|------|
| 1 | Risk Manager | ✅ | 信号聚合 + 仓位限制 |
| 2 | Portfolio Manager | ✅ | 最终交易决策 + 订单生成 |

## 8.4 Agent 编排

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | LangGraph StateGraph | ✅ | `src/graph/state.py` — 图式工作流编排 |
| 2 | 并行波次执行 | ✅ | 按 Provider 分组并行调用 |
| 3 | 可选 Analyst 子集 | ✅ | `--analysts` 参数选择指定 Agent |
| 4 | 并发限制控制 | ✅ | `ANALYST_CONCURRENCY_LIMIT` 环境变量 |

---

**相关章节**: [7. LLM 系统](./llm-system.md) | [1. 核心筛选流水线](./core-pipeline.md)
