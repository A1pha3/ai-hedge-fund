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
| R4 | P0 | ✅ | **连续推荐加权集成到前门** | `--top-picks` 整合连续推荐天数到排序和展示。 |
| R5 | P1 | ✅ | **前门历史命中率速览** | `--top-picks` 底部展示近 N 期推荐实际命中率摘要。 |
| R6 | P1 | ✅ | **市场机会指数信号灯** | `--top-picks` 顶部展示一键 GO/CAUTION/WAIT 信号。 |
| R7 | P2 | ✅ | **BUY/HOLD/AVOID 分布摘要** | `--top-picks` 底部展示推荐的操作分布。 |
| R8 | P1 | ✅ | **前门止损止盈价位** | `--top-picks` 对每个 BUY 建议附加 ATR 止损/止盈价位，复用 `conditional_order_advisor`。 |
| R9 | P2 | ✅ | **推荐评分趋势线** | `--top-picks` 对连续推荐标的展示 score_b 变化方向（↑↑/→/↓↓），复用 `signal_decay` 数据。 |

### R8 设计细节

**现状**：`conditional_order_advisor` 已能计算 ATR、买入区间、止损/止盈价位、盈亏比。但它是独立的 `--conditional-orders` 命令，用户需要额外运行。

**方案**：
1. `run_top_picks()` 中对每个 BUY 判定的代表票，调用 `compute_advice_from_history()` 获取止损止盈建议
2. 渲染输出在每个 BUY 条目下方增加一行：`买入区间=xx-xx  止损=xx(-X%)  止盈=xx(+X%)  盈亏比=X.X`
3. 数据不足时降级显示 `止损止盈: 数据不足`

**收益**：用户看到 BUY 信号后不用再跑 `--conditional-orders`，减少操作步骤。

### R9 设计细节

**现状**：`signal_decay_detector.detect_signal_decay()` 已能对比当前与历史 score_b，计算衰减百分比和等级。但该信息只在 `--auto` 表格中展示，`--top-picks` 未呈现连续推荐标的的趋势方向。

**方案**：
1. 对 `consecutive_days >= 2` 的标的，加载 `signal_decay` 数据
2. 展示一个趋势箭头：连续上升 → ↑↑，稳定 → →，衰减 → ↓↓
3. 仅一行文本，不增加输出复杂度

**收益**：帮助用户在连续推荐标的中区分"正在加强"和"正在减弱"的信号。

### 优先级排序理由

- **R8** (P1)：将已有的条件单能力整合到前门，减少用户操作步骤，直接提升"可操作性"。不新增重型功能。
- **R9** (P2)：将已有的衰减检测整合到前门，帮助用户在连续推荐中做更好的判断。信息密度高，代码改动小。
- 两项都是 **整合现有能力**，不新增独立命令，不新增数据依赖，符合"避免产品臃肿"原则。

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

> **最后更新**：2026-06-12（R20.42：修复 3 个 trade_date key bug + R8/R9 新需求 + R7 重复文本清理）
