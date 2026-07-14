---
难度: ⭐⭐⭐⭐
类型: 专家设计
预计时间: 8 分钟
前置知识:
  - [系统架构总览](../03-architecture/overview.md) ⭐⭐⭐
  - [设计哲学与原则](../01-introduction/design-philosophy.md) ⭐⭐⭐
---

# 设计文档索引

本目录记录 A 股每日选股系统的「为什么这样设计」与「代码如何实现」。文档不堆功能清单，而是把每个模块的设计意图、关键常量、回测依据和已知陷阱写到可被复核的程度。

## 文档地图

| 序号 | 文档 | 难度 | 主题 |
| --- | --- | --- | --- |
| 1 | [设计原则与权衡](principles.md) | ⭐⭐⭐⭐ | 凸性优先 / 机械执行 / 数据驱动 / 统计显著性 / 诚实披露 / gate-ranking 解耦 / 全 universe 诊断 |
| 2 | [候选池设计](candidate-pool-design.md) | ⭐⭐⭐ | Layer A 全市场快筛：ST / 北交所 / 流动性 / 行业配额 |
| 3 | [因子评分设计](factor-scoring-design.md) | ⭐⭐⭐⭐ | 四策略子因子、score_b 融合、Hurst 仲裁、IC 监控、MR 反转修复 |
| 4 | [BTST 涨停突破深度](btst-breakout-design.md) | ⭐⭐⭐⭐ | 4 触发条件、板块自适应涨停、5 因子 trigger_strength、crisis 加仓 |
| 5 | [Kelly 仓位](kelly-position-sizing.md) | ⭐⭐⭐ | half-Kelly 离散二元模型、per-setup 上限、regime 加权 |
| 6 | [风险框架](risk-framework.md) | ⭐⭐⭐⭐ | drawdown 熔断、ATR 止损、时间退出、止损为何默认不执行 |
| 7 | [纸面交易设计](paper-trading-design.md) | ⭐⭐⭐ | journal.jsonl 结构、T+N close 口径、回测方法论 |

## 阅读路径

- 想理解整套系统为何这么做 → 从 [设计原则与权衡](principles.md) 入手，再读 [BTST 深度](btst-breakout-design.md)。
- 想知道信号从哪来 → [候选池](candidate-pool-design.md) → [因子评分](factor-scoring-design.md) → [BTST](btst-breakout-design.md)。
- 想知道仓位与风控怎么算 → [Kelly 仓位](kelly-position-sizing.md) → [风险框架](risk-framework.md) → [纸面交易](paper-trading-design.md)。
- 想验证回测结论 → 直接看 [纸面交易设计](paper-trading-design.md) 的口径与陷阱章节。

## 数据一致性约定

本目录所有数字必须可在 `data/paper_trading_backtest/` 或源码常量中追溯。引用 Phase 0 报告的结论前，先与真实回测交叉验证 — 详见 [纸面交易设计](paper-trading-design.md) 的「路径陷阱」章节。
