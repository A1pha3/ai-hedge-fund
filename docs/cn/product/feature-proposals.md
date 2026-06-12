# 产品功能提案清单 (R20.41 活跃路线图版)

> **目标**：让用户用尽可能少的入口，稳定找到未来 30 天最有投资价值、最值得买入的 A 股标的。
>
> **本版调整**：新增 R4-R5 两项前门整合需求，直接提升默认前门的决策质量。

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
2. 用户最终需要的不是"更多指标"，而是 **更少候选、更高确信、更清晰的 Buy / Hold / Avoid 决策**。
3. 所有新增功能都要服务于这条主线：**更快筛掉低质量候选，更稳保留最值得买的代表票**。

### 约束

- **优先复用既有能力**：20-agent、composite score、T+30 posterior edge、market gate、position check、risk snapshot、verify pipeline 都已具备，不再平行造新入口。
- **避免前门分裂**：power-user 命令可以保留，但不应成为默认工作流。
- **避免冗余候选**：同主题、同行业、强相关标的不应在前门里成批挤占用户注意力。
- **避免产品臃肿**：不为"看起来先进"而新增重型功能。

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
3. 后续新增需求不应再把用户拉回"先决定跑哪个命令"的状态。

---

## 三、活跃 backlog

> **状态标记**：❌ 未开始 | 🔄 进行中 | ✅ 已完成

| ID | 优先级 | 状态 | 需求 | 目标 |
|---|---|---|---|---|
| R1 | P0 | ✅ | **单一 30 天决策前门** | `--top-picks` 已成为默认前门。 |
| R2 | P0 | ✅ | **候选去重 + 代表票机制** | `--top-picks` 已按行业 / 主题簇优先保留代表票。 |
| R3 | P1 | ✅ | **前门文档收敛** | 主路线图、快速开始、完整 CLI 参考已完成分工。 |
| R4 | P0 | ✅ | **连续推荐加权集成到前门** | `--top-picks` 整合连续推荐天数到排序和展示。连续 3+ 天推荐的标的自动提升排序权重 + 可视化标注连续天数。直接提升前门命中率——历史数据表明连续推荐标的胜率显著高于单日推荐。 |
| R5 | P1 | ✅ | **前门历史命中率速览** | `--top-picks` 底部展示近 N 期推荐实际命中率摘要（T+5/T+10/T+30），与沪深 300 基准对比。让用户直观看到系统的历史表现，建立信任。 |
| R6 | P1 | ✅ | **市场机会指数信号灯** | `--top-picks` 顶部展示一键 GO/CAUTION/WAIT 信号，综合市场门控+标的质量+BUY比率。用户一眼判断当日是否适合投资，无需分析多个指标。 |
| R7 | P2 | ✅ | **BUY/HOLD/AVOID 分布摘要** | `--top-picks` 底部展示推荐的操作分布，让用户立即了解当日机会全景。 | | `--top-picks` 底部展示近 N 期推荐实际命中率摘要（T+5/T+10/T+30），与沪深 300 基准对比。让用户直观看到系统的历史表现，建立信任。 |

### R4 设计细节

**现状**：`consecutive_recommendation.enrich_recommendations_with_history()` 已能计算连续推荐天数、状态和新/持续/退出标签。但 `--top-picks` 未调用此能力。

**方案**：
1. `run_top_picks()` 中加载连续推荐数据，调用 `enrich_recommendations_with_history()`
2. `rank_recommendations_by_investability()` 增加 `consecutive_bonus` 因子：连续 3+ 天 → +0.03，5+ 天 → +0.05，10+ 天 → +0.08
3. 渲染输出增加连续天数标签和状态图标（🆕 新增 / 🔁 持续 / ⬇️ 降级）

### R5 设计细节

**现状**：`verify_recommendations.compute_verify_recommendations()` 已能计算近 N 期的实际 T+1/T-5/T+10/T+20/T+30 收益和胜率。但 `--top-picks` 未展示。

**方案**：
1. `run_top_picks()` 底部追加 3-5 行历史命中率摘要
2. 展示近 30/60 天的推荐总数、T+5 胜率、T+30 胜率、平均 T+30 收益
3. 与沪深 300 基准对比（超额收益）

### 为什么只保留这 5 项

- **R1-R3** 已完成，是前门收敛的基础设施。
- **R4** 是对现有能力的整合，直接提升选股命中率。连续推荐的标的在过去数据中胜率显著更高。
- **R5** 是对用户信任的投资。让用户看到系统历史表现，而非盲信黑盒。
- **R6** 是投资决策的即时信号。综合多个维度给出 GO/CAUTION/WAIT，避免用户在不利条件下盲目买入。
- **R7** 是操作分布的全景速览。一眼看到 BUY/HOLD/AVOID 分布，理解市场机会的整体格局。
- 四项(R4-R7)都不新增重型功能，只是把现有能力整合到默认前门中。

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
4. 只要需求不能直接提升"未来 30 天高确信选股效率"，默认不进入 P0 / P1。

---

> **最后更新**：2026-06-12（R20.41：R4-R7 全部完成 + 全域代码审查 0 bug + 市场机会指数 + BUY/HOLD/AVOID分布 + 脚本清理）
