# 产品功能提案清单 (R20.41 活跃路线图版)

> **目标**：让用户用尽可能少的入口，稳定找到未来 30 天最有投资价值、最值得买入的 A 股标的。
>
> **本版调整**：新增 R14-R15 两项前门增强需求，将已有行业轮动和因子归因数据整合到默认前门。

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
| R10 | P1 | ✅ | **多策略共振指标** | `--top-picks` 对每个候选展示 4 策略看多数量（如"共振 4/4"），直接提升决策确信度。 |
| R11 | P2 | ✅ | **行业聚焦摘要** | `--top-picks` 底部展示当日推荐行业分布一行摘要，帮助用户快速感知市场轮动方向。 |
| R12 | P1 | ✅ | **数据新鲜度守卫** | `--top-picks` 顶部检测报告日期，超过 1 交易日显示醒目过期警告，防止基于过时数据决策。 |
| R13 | P2 | ✅ | **新增/退出标的标记** | `--top-picks` 对比前一日报告，标出 🆕 新入选和 ❌ 退出的标的，帮助用户捕捉信号变化。 |
| R14 | P1 | ✅ | **行业轮动方向** | `--top-picks` 底部展示行业动量方向（↗ 进入聚焦 / ↘ 离开聚焦），复用已有 `industry_rotation` 数据，帮助用户把握板块轮动节奏。 |
| R15 | P2 | ✅ | **因子贡献归因** | `--top-picks` 对每个候选展示主要贡献因子（如"动量+行业强"），复用已有 `compute_score_decomposition`，让用户理解推荐来源而非只看总分。 |
| R16 | P2 | ✅ | **回测净值曲线 数据不足占位** | `BacktestEquityCurve` 在 `dailyResults.length < 2` 时显示 `数据点不足（需至少 2 天），等待回测数据...` 占位提示而非静默 `return null`，消除 1-day 回测的"白屏"困惑（来自 ux-best-practices-2025-2026.md L-2 行）。 |
| R17 | P3 | ✅ | **月度热力图键盘可访问性** | `BacktestEquityCurve` 月度热力图单元格补 `aria-label`（`title` 仅鼠标悬停可触发），让键盘 / 屏幕阅读器用户也能读到月度收益数值（来自 ux-best-practices-2025-2026.md A-5 行）。 |

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
- **R10** (P1)：复用已有 `strategy_signals` 数据，零新增依赖。4/4 共振的标的比 1/4 显著更可靠，直接提升前门决策确信度。
- **R11** (P2)：复用已有 `industry_sw` 数据，一行输出。帮助用户在不运行额外命令的情况下感知市场板块轮动。
- **R12** (P1)：零数据依赖，仅需比较报告日期与当前日期。直接防止最大操作风险：用过时数据交易。一行输出。
- **R14** (P1)：复用已有 `industry_rotation` 数据，零新增依赖。将 R11 静态分布升级为方向性信号，直接提升前门决策质量。
- **R15** (P2)：复用已有 `compute_score_decomposition`，零新增依赖。让推荐可解释，减少"黑箱"感。
- **R13** (P2)：复用已有 `_find_latest_report` 和推荐列表，对比相邻两份报告。帮助用户立即捕捉信号变化，无需手动对比。
- 所有项都是 **整合现有能力**，不新增独立命令，不新增数据依赖，符合"避免产品臃肿"原则。

### R10 设计细节

**现状**：每个推荐已有 `strategy_signals`（trend / mean_reversion / fundamental / event_sentiment），每条含 `direction`（1=看多, 0=中性, -1=看空）。但前门未展示多策略一致性。

**方案**：
1. 在 `run_top_picks()` 渲染每条候选时，统计 `strategy_signals` 中 direction=1 的数量
2. 展示为 `共振 N/4`（N=看多策略数），使用颜色编码：4/4 亮绿，3/4 绿，2/4 黄，1/4 灰
3. 不增加额外行，嵌入现有信号行

**收益**：用户一眼可区分"多策略共振确认"和"单策略独立信号"，减少对单策略偏差的误判。

### R11 设计细节

**现状**：每个推荐已有 `industry_sw` 行业分类字段，但前门不展示行业分布全貌。

**方案**：
1. 统计所有代表票的 `industry_sw` 分布
2. 在前门底部（verdict distribution 之后）输出一行：`行业聚焦: 电子(2) 医药(1) 机械(1)`
3. 仅展示出现 2 次以上的行业 + 其余合并为"其他"

**收益**：帮助用户快速感知"今天的市场热点在哪个板块"，无需手动统计。

### R12 设计细节

**现状**：`run_top_picks()` 读取最新报告但不检查报告日期是否为当天/最近交易日。用户可能在周末或假期基于过时数据做决策，这是最大的操作风险之一。

**方案**：
1. 比较 `report_data["date"]` 与当前日期
2. 如果报告日期早于最近一个交易日（简单逻辑：≥2 个自然日前），显示黄色警告：`⚠ 报告日期: 20260610（非最新，请先运行 --auto）`
3. 警告放在 `run_top_picks()` 输出的最顶部（在 "Today's Top Picks" 之前）

**收益**：防止用户基于过时数据交易。一行输出，零数据依赖。

### R13 设计细节

**现状**：`run_top_picks()` 已调用 `_find_latest_report()` 获取最新报告。但用户无法快速看到今天新增了哪些标的、哪些标的退出了推荐。

**方案**：
1. 在 `run_top_picks()` 中查找前一日报告（`auto_screening_{prev_date}.json`）
2. 对比两份报告的 ticker 集合
3. 对新增的 ticker 在输出中标记 `🆕`，对退出的 ticker 在底部显示一行摘要
4. 数据不足（无前一日报告）时静默跳过

**收益**：帮助用户立即捕捉信号变化——"今天新入选的标的值得关注，退出的标的需要检查原因"。

### R14 设计细节

**现状**：`calculate_industry_rotation()` 已在 `--auto` 管线中计算申万一级行业动量排名（5 日/20 日动量 + 强度评分），但 `--top-picks` 仅展示 R11 静态行业分布，不展示方向。

**方案**：
1. 在 `run_top_picks()` 中加载最新报告的 `industry_rotation` 数据
2. 对 R11 行业聚焦摘要中出现的行业，附加动量方向：↗（进入聚焦）/ ↘（离开聚焦）/ →（稳定）
3. 使用颜色编码：↗ 绿色，↘ 红色，→ 白色

**收益**：用户一眼可感知"今天的市场热点在哪个方向"，无需手动跑 `--decision-flow` 查看行业轮动数据。

### R15 设计细节

**现状**：`compute_score_decomposition()` 已能分解 score_b 为子因子贡献（趋势/动量/反转/情绪等），但该信息只在 `--decision-flow` 中展示，`--top-picks` 只展示总分和各调整项。

**方案**：
1. 在 `run_top_picks()` 中对每个代表票，调用 `compute_score_decomposition()` 获取因子贡献
2. 展示 Top-2 贡献因子：如"主因: 动量↑ + 反转↑"
3. 仅一行文本，嵌入现有信号行

**收益**：让用户理解"为什么这只票被推荐"，而不仅仅是"分数高"。直接提升推荐可解释性。

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

> **最后更新**：2026-06-14（R20-S6：R16/R17 BacktestEquityCurve UX/A11y 修复 — 来自 UX 研究 L-2/A-5）
