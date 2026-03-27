# Layer B 调参一页速查卡

适用对象：已经理解 Layer B 大框架，但在调参讨论、实验设计、人工审核和 AI 协作时需要快速抓重点的读者。

---

## 1. 一句话目标

Layer B 调参的目标不是“放出更多股票”，而是用最小、可归因、可回滚的规则变化，减少明显误伤，同时维持 Layer C 和 execution 的承接质量。

---

## 2. 先记住的 8 条原则

1. 先修语义，再降总阈值。
2. 先修中性项和缺失项，不先放宽强负项。
3. 先做条件式放宽，不做全市场统一放宽。
4. 先看新增样本质量，再看新增样本数量。
5. 每次只动一个机制。
6. 用目标区间看结果，不盯单一数字。
7. 先修边缘误伤，再修全盘稀缺。
8. 调参终点是让研究漏斗更健康，不是只让 Layer B 变热。

---

## 3. 当前最重要的优先级

| 优先级 | 主题 | 为什么先看它 | 当前建议动作 |
| --- | --- | --- | --- |
| P1 | neutral mean_reversion 语义 | 当前窗口里最像“边缘误伤主杠杆” | 继续收敛 partial-weight 中间档 |
| P2 | event_sentiment 缺失语义 | 缺失样本多，真实负面事件少 | 把 missing 与 negative 分开处理 |
| P3 | 供给侧扩容 | heavy legs 设计重要，但现实覆盖不足 | 小步扩大 event 或 technical 覆盖面 |
| P4 | profitability 软化 | 是左尾放大器，但不是当前主矛盾 | 只在前 3 项不足时再深挖 |
| P5 | fast gate / watch 阈值 | 容易做，也最容易误判 | 放在最后微调 |

---

## 4. 当前最推荐的调参顺序

### 4.1 先做什么

1. MR `quarter + event positive`
2. MR `quarter + event missing neutralized`
3. event 缺失语义中性化
4. `EVENT_SENTIMENT_MAX_CANDIDATES` 小步扩容

### 4.2 暂时不先做什么

1. 不先大幅下调 `FAST_AGENT_SCORE_THRESHOLD`
2. 不先整体放松 fundamental
3. 不先关闭 profitability 的质量红旗
4. 不同时改 MR、event、fundamental 和 threshold

---

## 5. 四类调参对象速查

| 类型 | 代表参数 | 它在解决什么问题 | 什么时候动 |
| --- | --- | --- | --- |
| 语义类 | `LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE` | active 资格和归一化语义是否误伤边缘票 | 最先动 |
| 缺失类 | event missing 处理语义 | 缺失数据是否被隐式当成拖累 | 很早动 |
| 供给类 | `EVENT_SENTIMENT_MAX_CANDIDATES`、`TECHNICAL_SCORE_MAX_CANDIDATES` | 谁能拿到 heavy signal | 语义后动 |
| 阈值类 | `FAST_AGENT_SCORE_THRESHOLD`、watch 阈值 | 最后一道门是否仍过严 | 最后动 |

---

## 6. 一轮标准实验流程

1. 固定 baseline：窗口、report、模型路由、默认规则。
2. 先回答主矛盾：供给、语义、融合、阈值，哪一个是第一问题。
3. 只选一个实验主题。
4. 设计一个最小变体，不要做组合拳。
5. 跑 baseline 和 2 个参照变体。
6. 导出新增样本人工审核台账。
7. 看 Layer C、watchlist、execution 是否承接。
8. 决定继续、停止或回滚。

---

## 7. 每轮至少要看哪些指标

### 7.1 Layer B 漏斗

1. `avg_layer_b_count`
2. `nonzero_layer_b_days`
3. `layer_b_pass_delta`
4. `near_threshold_count`

### 7.2 新增样本质量

1. `added_sample_count`
2. 优秀候选占比
3. 边界可接受占比
4. 可疑放行占比
5. 明显不该通过占比

### 7.3 跨层承接

1. `avg_watchlist_count`
2. `avg_buy_order_count`
3. Layer C 明确否决占比
4. execution blocker 占比

### 7.4 工程成本

1. `avg_total_day_seconds`
2. event 分析耗时变化
3. heavy score 覆盖面变化

---

## 8. 新增样本怎么判

最少分 4 类：

1. 优秀候选
2. 边界但可接受
3. 可疑放行
4. 明显不该通过

如果多数新增样本落在后两类，这轮实验不应继续放大。

---

## 9. 研究员与 AI 助手如何分工

### 9.1 研究员负责

1. 选窗口
2. 定主假设
3. 做人工审核
4. 决定是否继续下一轮

### 9.2 AI 助手负责

1. 定位代码
2. 实现最小变体
3. 跑对照实验
4. 导出台账
5. 汇总结果

---

## 10. 最常见的 6 个误区

1. 通过数太少，先降阈值。
2. fundamental 压制最强，所以先放 fundamental。
3. 新增样本多就是成功。
4. 只看 Layer B，不看 Layer C 承接。
5. 一轮实验同时改多个机制。
6. 单窗口有效，就直接当默认参数。

---

## 11. 当前最务实的下一步

如果现在就继续往下做，最稳的路径是：

1. baseline
2. MR `quarter + event positive`
3. MR `quarter + event missing neutralized`

先做当前窗口对照，再导出新增样本台账，先做人审，再决定要不要进入供给侧扩容。

---

## 12. 需要深入时看哪里

1. 方法长文：[26-layer-b-parameter-tuning-playbook.md](./26-layer-b-parameter-tuning-playbook.md)
2. 根因基线：[04-层B因子参数根因分析与实验矩阵-20260326.md](./04-%E5%B1%82B%E5%9B%A0%E5%AD%90%E5%8F%82%E6%95%B0%E6%A0%B9%E5%9B%A0%E5%88%86%E6%9E%90%E4%B8%8E%E5%AE%9E%E9%AA%8C%E7%9F%A9%E9%98%B5-20260326.md)
3. 联动复盘：[22-layer-b-c-joint-review-manual.md](./22-layer-b-c-joint-review-manual.md)
4. 执行承接：[24-execution-bridge-professional-guide.md](./24-execution-bridge-professional-guide.md)
