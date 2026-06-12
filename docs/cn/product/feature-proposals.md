# 产品功能提案清单 (R20.40 活跃路线图版)

> **目标**：让用户用尽可能少的入口，稳定找到未来 30 天最有投资价值、最值得买入的 A 股标的。
>
> **本版调整**：主文档不再承载大段已完成历史，只保留当前产品目标、默认前门、开放 backlog、明确不做项与维护规则。Phase 5-19 的完成态已外置到 [`changelog/completed-roadmap-phases.md`](./changelog/completed-roadmap-phases.md)。

---

## 另见

| 内容 | 路径 | 说明 |
|---|---|---|
| 已实现功能矩阵 | [features/MATRIX.md](./features/MATRIX.md) | 当前全量能力总览 |
| 已完成路线图归档 | [changelog/completed-roadmap-phases.md](./changelog/completed-roadmap-phases.md) | Phase 5-19 完成态与收口说明 |
| 审查历史 | [changelog/r20-audit-history.md](./changelog/r20-audit-history.md) | alpha / beta / gamma 历次审查 |
| 历史提案归档 | [features/optimizations.md](./features/optimizations.md) | 旧提案与实现细节，现仅作归档 |
| 行业调研 | [research/industry-2025-2026.md](./research/industry-2025-2026.md) | 业界对标与差距分析 |
| UX 审计 | [research/ux-best-practices-2025-2026.md](./research/ux-best-practices-2025-2026.md) | 前端体验问题与修复建议 |
| CLI 快速开始 | [QUICKSTART.md](./QUICKSTART.md) | 新用户入口 |
| CLI 参考 | [features/cli-reference.md](./features/cli-reference.md) | power-user 命令总表 |

---

## 一、产品目标与收敛原则

### 核心目标

1. 默认前门必须围绕 **未来 30 天的可投资性**，而不是让用户手动拼接多个短周期信号。
2. 用户最终需要的不是“更多指标”，而是 **更少候选、更高确信、更清晰的 Buy / Hold / Avoid 决策**。
3. 所有新增功能都要服务于这条主线：**更快筛掉低质量候选，更稳保留最值得买的代表票**。

### 约束

- **优先复用既有能力**：20-agent、composite score、T+30 posterior edge、market gate、position check、risk snapshot、verify pipeline 都已具备，不再平行造新入口。
- **避免前门分裂**：power-user 命令可以保留，但不应成为默认工作流。
- **避免冗余候选**：同主题、同行业、强相关标的不应在前门里成批挤占用户注意力。
- **避免产品臃肿**：不为“看起来先进”而新增重型功能。

---

## 二、当前默认前门

系统已经具备完整能力。自 R20.40 起，默认前门收敛为：

```text
--top-picks                 默认前门（代表票 + Buy/Hold/Avoid + T+30 证据）
--daily-brief               盘前补充摘要
--position-check            持仓监控
--decision-flow             power-user 深度链路
```

当前仍待继续收口的是文档层分工，而不是默认命令本身：

1. `--top-picks` 已经是默认入口，但 `QUICKSTART` / `cli-reference` / 历史研究仍有旧叙事残留。
2. `--daily-brief` 与 `--position-check` 现在更适合作为补充工作面，而不是并列前门。
3. 后续新增需求不应再把用户拉回“先决定跑哪个命令”的状态。

---

## 三、活跃 backlog

> **状态标记**：❌ 未开始 | 🔄 进行中 | ✅ 已完成

| ID | 优先级 | 状态 | 需求 | 目标 |
|---|---|---|---|---|
| R1 | P0 | ✅ | **单一 30 天决策前门** | `--top-picks` 已成为默认前门，固定输出 Buy / Hold / Avoid、T+30 edge、胜率、样本量、市场门控、失效条件。 |
| R2 | P0 | ✅ | **候选去重 + 代表票机制** | `--top-picks` 已按行业 / 主题簇优先保留代表票，并展示同簇备选，减少高重叠候选同时占满前门。 |
| R3 | P1 | ✅ | **前门文档收敛** | 主路线图、快速开始、完整 CLI 参考已完成分工；`r20.6-roadmap-gap-analysis.md` 也已收成历史索引，不再与研究正文重复维护。 |

### 为什么现在只保留这 3 项

- **R1** 已把默认前门收敛到单一命令，用户不再需要先判断该跑哪个入口。
- **R2** 已把“候选很多但高度重叠”的问题压缩成“代表票 + 备选”展示。
- **R3** 已把主路线图、上手入口、完整参考和历史研究索引拆回各自职责，避免旧叙事反复回流。

---

## 四、已完成能力（主文档只保留结论）

以下能力已完成，不再占用主路线图主体：

- **20-agent 多人格分析体系**：投资者 Agent、分析师 Agent、Risk Manager、Portfolio Manager 全量可用。
- **CLI 决策链**：从筛选、解释、校准、闭环验证到组合构建已闭环。
- **30 天 investability 收敛基础设施**：T+20 / T+30 posterior edge、统一排序逻辑、市场门控、持仓健康检查均已落地。
- **前端关键能力**：回测可视化、参数对比、Agent 推理展示、风险监控、宏观看板、筛选结果工作面均已接入。

完整完成态见：

- [`features/MATRIX.md`](./features/MATRIX.md)
- [`changelog/completed-roadmap-phases.md`](./changelog/completed-roadmap-phases.md)
- [`changelog/r20-audit-history.md`](./changelog/r20-audit-history.md)

---

## 五、明确不做（避免系统继续膨胀）

| 功能 | 原因 |
|---|---|
| NL 自然语言选股 | 问财等产品已占据该心智；我们更应该强化可解释的多 Agent 决策链。 |
| 移动端 App | 当前 Web + CLI 已覆盖核心使用场景，投入产出比低。 |
| 深度学习因子挖掘 | 研究价值高，但产品成本与维护复杂度过高，不适合作为当前前门能力。 |
| 自定义因子 Python 编辑器 | 安全、沙箱、版本治理成本过高。 |
| 港股通跨市场扩展 | 数据源、监管、税制完全不同，会稀释当前 A 股主目标。 |

---

## 六、维护规则

1. 主文档只维护 **当前开放 backlog**，不再顺手堆历史完成项。
2. 已完成需求只在主文档保留一句价值结论，技术细节写入 `features/`、`research/` 或 `changelog/`。
3. 新增需求前先检查是否与现有前门、排序逻辑、监控链路重复。
4. 只要需求不能直接提升“未来 30 天高确信选股效率”，默认不进入 P0 / P1。

---

> **最后更新**：2026-06-12（R20.40：`--top-picks` 收敛为默认前门并支持代表票去重；主路线图与已完成历史拆分）
