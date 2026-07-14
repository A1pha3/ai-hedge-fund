---
难度: ⭐
类型: 入门教程
预计时间: 5 分钟
前置知识:
  - 无
---

# AI Hedge Fund（A 股研究分叉）中文文档

本仓库是 [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) 的 A 股研究分叉。它用两条独立管线完成「全市场因子筛选」和「凸性 setup 触发」——前者给出 30 天投资周期的高分候选池，后者在缓存数据上扫描次日可执行的买入信号。**仅用于教育与量化研究，不用于实盘交易。**

入口是 `uv run python src/main.py`（不是 `poetry run`）。两条核心命令：

```bash
uv run python src/main.py --auto           # 收盘后跑全流程, 约 4 PM 后
uv run python src/main.py --daily-action   # 读缓存, 约 3 秒, 输出次日 BUY 信号
```

## 四类文档导航

| 类别 | 索引 | 回答什么问题 |
|---|---|---|
| 01 项目介绍 | [01-introduction/README.md](01-introduction/README.md) | 系统是什么、与上游差异、设计哲学 |
| 02 用户手册 | [02-user-manual/README.md](02-user-manual/README.md) | 安装、第一次运行、解读报告、故障排除 |
| 03 架构 | [03-architecture/README.md](03-architecture/README.md) | 三层管线、daily-action 系统、数据层、LLM 系统 |
| 04 设计 | [04-design/README.md](04-design/README.md) | 候选池、因子评分、BTST setup、Kelly 仓位、风险框架 |

## 学习路径

**新读者（10 分钟拿到第一份推荐）**

1. [项目总览](01-introduction/overview.md)：理解两条管线的边界
2. [快速开始](02-user-manual/getting-started.md)：安装与第一次 `--auto`
3. [输出报告解读](02-user-manual/interpreting-reports.md)：解读 `auto_screening_YYYYMMDD.json`

**研究者（理解 setup 有效性的依据）**

1. [项目总览](01-introduction/overview.md)
2. [设计哲学与原则](01-introduction/design-philosophy.md)：七条原则如何约束决策
3. [项目定位与边界](01-introduction/positioning.md)：研究语义边界
4. [凸性 setup 系统](03-architecture/daily-action-system.md)
5. [BTST 涨停突破设计](04-design/btst-breakout-design.md)

**Contributor（想 fork 或提交 PR）**

1. [项目定位与边界](01-introduction/positioning.md)：明确上游与本分叉的分界
2. [设计哲学与原则](01-introduction/design-philosophy.md)：约束改动方向
3. [三层管线架构](03-architecture/three-layer-pipeline.md)
4. [设计原则与权衡](04-design/principles.md)：各模块设计文档入口

## 关键事实

- 两条管线**只共享缓存数据**，决策逻辑独立
- 回测数据在 `data/paper_trading_backtest/`（403 条记录、nav=2.10），不是 `data/paper_trading/`（运行时实例，0 笔 EXIT）
- BTST 涨停突破（T+10）：✅ 启用，2026 H1 winrate=68%，E[r]=+8.15%
- OversoldBounce 超跌反弹（T+5）：⏸️ 默认暂停，E[r]=+0.34% 但 95% CI 跨 0，统计不显著
- `price_cache` 只有 6 个月深度，引用 Phase 0 报告结论前先用回测数据交叉验证

## 上游 README

本仓库根目录的 `README.md` 保留了上游 virattt/ai-hedge-fund 的英文说明以示 credit，但**本分叉的实际工作流、CLI、数据源与上游不同**。新用户请直接读本目录的中文文档，不要照上游英文说明操作。
