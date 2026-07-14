---
难度: ⭐⭐⭐
类型: 进阶分析
预计时间: 8 分钟
前置知识:
  - [项目概览](../01-introduction/overview.md) ⭐⭐
  - [日常使用](../02-user-manual/daily-workflow.md) ⭐⭐
---

# 架构文档索引

本目录把这套 A 股每日选股系统拆成 5 条独立主线。它们看起来像一条流水线,实际是两条几乎不重叠的管线加三块支撑设施,各自有不同的触发命令、数据来源和退出条件。

阅读顺序按"先看整体,再进细节"。先读 [overview.md](./overview.md) 把两条管线的边界画清楚,再按需深入。

## 文档清单

| 文档 | 难度 | 覆盖主线 | 关键判断 |
|---|---|---|---|
| [overview.md](./overview.md) | ⭐⭐⭐ | 全系统 | `--auto` 与 `--daily-action` 是两条独立管线,只共享缓存 |
| [three-layer-pipeline.md](./three-layer-pipeline.md) | ⭐⭐⭐ | 管线 1: `--auto` | Layer A/B/C 是职责分离,不是流水线步骤 |
| [daily-action-system.md](./daily-action-system.md) | ⭐⭐⭐⭐ | 管线 2: `--daily-action` | 凸性 setup 不依赖 `--auto` 候选池,扫描全市场极端股票 |
| [data-layer.md](./data-layer.md) | ⭐⭐⭐ | 数据层 | 三级缓存实际只有 LRU + SQLite 在跑,Redis 是占位 |
| [llm-system.md](./llm-system.md) | ⭐⭐⭐ | LLM 系统 | 默认模型必须显式配置,不再回退到 provider 变量 |

## 阅读路径

**第一次读**:按上表顺序通读 5 篇,建立"两管线 + 三支撑"的整体地图。每篇前 20% 都有总览图或对照表,可以快速判断是否需要细读。

**运维优先**:先 [data-layer.md](./data-layer.md) 再 [llm-system.md](./llm-system.md)。这两块决定系统在什么情况下会"看起来在跑但没出结果"——通常是缓存命中失效或 LLM 默认模型未配置。

**研究优先**:先 [overview.md](./overview.md) 摸清两条管线的边界,再按研究方向选 [three-layer-pipeline.md](./three-layer-pipeline.md) (因子评分) 或 [daily-action-system.md](./daily-action-system.md) (凸性 setup 与 Kelly 仓位)。daily-action-system 包含回测数据解读,但这些数字反映的是 2026 H1 牛市样本,不能直接外推。

## 交叉引用

- 因子评分设计: [04-design/factor-scoring-design.md](../04-design/factor-scoring-design.md)
- BTST 设计: [04-design/btst-breakout-design.md](../04-design/btst-breakout-design.md)
- Kelly 仓位: [04-design/kelly-position-sizing.md](../04-design/kelly-position-sizing.md)
- 风险框架: [04-design/risk-framework.md](../04-design/risk-framework.md)
