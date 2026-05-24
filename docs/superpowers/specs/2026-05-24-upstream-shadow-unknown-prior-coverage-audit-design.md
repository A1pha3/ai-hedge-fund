# Upstream Shadow Unknown Prior Coverage Audit 设计文档

- **日期：** 2026-05-24
- **主题：** BTST upstream-shadow 主线在真实 FN/FP dossier 之后的下一轮诊断设计
- **推荐方向：** 先做 `attachment-first` 的 unknown-prior coverage audit，再决定是否需要改历史 prior 分类或运行时治理

## 1. 阅读目标

读完这份设计文档后，读者应当能回答 3 个问题：

1. 为什么当前 upstream-shadow 主线的首要问题不是 rollout 开关，而是 `historical_execution_quality_label = unknown` 的覆盖缺口。
2. 为什么这轮要优先审 `prior attachment`，而不是直接改 `execution_quality_label` 分类规则。
3. 这个新 audit 脚本应当输出什么、如何 fail-closed、以及后续如何验证它的结论。

## 2. 问题定义

最新真实 `upstream-shadow FN/FP dossier` 已经把主矛盾从“要不要继续放松 rollout”转到了“为什么大量 upstream-shadow 样本没有稳定拿到可解释的 historical prior”。

当前最关键的证据是：

1. `cohort_count = 146`
2. `false_negative_count = 33`
3. `false_positive_count = 7`
4. `quality_label_split = {'unknown': 128, 'close_continuation': 10, 'balanced_confirmation': 6, 'intraday_only': 2}`
5. FN 行中 `unknown` 占 `28 / 33`
6. FP 行中 `unknown` 占 `7 / 7`

这意味着下一轮最值得回答的问题不再是：

> 哪个 rollout 开关还能再放松一点？

而是：

> upstream-shadow 样本的 `historical_prior` 到底是在 attach 之前就缺失了，还是 attach 之后仍然因为样本太弱而保持 `unknown`？

如果这个问题不先拆开，后面无论去改 `execution_quality_label` 规则、因子阈值还是 rollout 治理，都会把不同根因混在一起。

## 3. 目标与非目标

### 3.1 目标

设计一个窄而明确的分析周期，用来：

1. 逐行解释 upstream-shadow cohort 中 `unknown` 的来源。
2. 把 `unknown` 至少拆成“没有 attach 上 prior”和“attach 上了但 prior 太弱”两类。
3. 对重复 ticker 给出时间线视图，说明同一名字在不同 report 中的 prior 状态如何演化。
4. 产出一个可复跑、可复查的诊断 artifact，为下一轮 Alpha refinement 提供依据。

### 3.2 非目标

- 这轮不直接修改 `historical_prior` 分类规则。
- 不在设计阶段调整 runtime score 阈值。
- 不把这轮 audit 变成新的 rollout 放松实验。
- 不更新 `ai-hedge-fund-btst`。
- 不在还没拆清 `unknown` 根因前重启大范围新因子搜索。

## 4. 备选方案

### 4.1 方案 A：`attachment-first` 审计（**推荐**）

新增一个薄分析脚本，复用现有 `followup → latest prior → final resolve` 链路，对每个 upstream-shadow row 做 prior trace，并按 trace 状态聚合输出。

**优点**

- 直接对应当前 `128 / 146 unknown` 的主矛盾。
- 能先回答“没挂上”还是“挂上了但太弱”，避免过早动 label 规则。
- 复用已有 loader 和 merge 逻辑，风险最小。
- 输出结果可以直接成为后续 Alpha / Beta / Gamma 讨论的共同基线。

**代价**

- 需要新增一个专门的 research script。
- 依赖已有 followup brief 和 historical prior artifact 的可解析性。

### 4.2 方案 B：先做 label-generation 审计

直接沿 `_classify_execution_quality_prior(...)` 这条链审 `execution_quality_label` 是如何生成的，优先判断是不是分类规则太粗或空白区太大。

**优点**

- 如果问题确实集中在标签规则，这条线能较快暴露分类边界问题。
- 与后续 potential label refinement 路径更接近。

**代价**

- 如果很多 row 在 attach 前就没有拿到可用 prior，这条线会先分析一个并不存在的上游输入。
- 容易把“数据缺口”和“分类缺陷”混成同一个问题。

### 4.3 方案 C：先做重复 ticker 单票深挖

围绕 `300683 / 300720 / 003036 / 301188` 这类重复名字做 timeline dossier，再从案例反推 prior 覆盖缺口。

**优点**

- 结果直观，便于快速讨论。
- 有助于形成后续 Alpha 文档里的典型案例。

**代价**

- 容易被单票偶然性带偏。
- 无法先给全量 cohort 的系统性解释。

## 5. 推荐设计

这轮应当先做一个专门的 **upstream-shadow unknown-prior coverage audit**。

它回答的核心问题只有 4 个：

1. 哪些 upstream-shadow row 在 report / brief 层已经能看到 prior，但到了 final row 层却没有稳定保留下来。
2. 哪些 row 确实拿到了 prior，但 `sample_count`、`evaluable_count` 或质量标签太弱，导致最终仍然不具解释力。
3. 哪些重复 ticker 在多个 trade date 上反复落入相同的 unknown 模式。
4. 下一轮最高价值的动作，是修 attachment、修弱 prior fallback，还是再去审 label-generation。

这份 artifact 的目标不是直接产出一个新 profile，而是把 `unknown` 的结构拆开，让后续动作有明确优先级。

## 6. 设计边界

这个设计刻意收窄在 5 个边界内：

1. 只研究 upstream-shadow cohort，不覆盖整个 BTST universe。
2. 先做诊断，不直接改运行时决策规则。
3. 优先复用已有 loader / resolver / attach helper，不新造平行数据入口。
4. 输出以诊断 artifact 为终点，不自动触发 rollout 或 skill 更新。
5. 默认 fail-closed：宁可显式保留数据缺口，也不把缺口误解释成 attachment bug。

## 7. 组件设计

### 7.1 Cohort 提取层

脚本应当先提取 upstream-shadow cohort。优先保留：

1. `candidate_source == "upstream_liquidity_corridor_shadow"` 的 row。
2. 能从 upstream-shadow followup / observation 结构里稳定归一化回同一家族的 row。

这样可以覆盖已经 materialize 成 short-trade row 的样本，也能覆盖仍停留在 observation / followup 层但带有 prior 线索的样本。

### 7.2 Prior trace 层

每个 row 都应生成一条 `prior_trace`，至少包含 4 部分：

1. `embedded_prior`
   - 来自单个 report brief / followup merge 结果中的 `historical_prior`。
2. `latest_loader_prior`
   - 来自 `load_latest_btst_historical_prior_by_ticker(...)` 的 ticker 级最优 prior。
3. `resolved_final_prior`
   - 来自 `resolve_historical_prior_for_ticker(...)` 与 attachment 逻辑之后，最终落在 row 上的 prior。
4. `trace_status`
   - 对这一行为何仍然 `unknown` 或 prior 弱化的结论性状态。

### 7.3 `trace_status` 枚举

第一版只保留少量稳定状态，避免把脚本做成一份解释性散文。

推荐首版状态：

1. `missing_upstream_prior`
2. `latest_prior_missing`
3. `resolve_kept_unknown`
4. `resolve_dropped_stronger_prior`
5. `resolved_but_low_sample`

后续如果需要再扩枚举，但第一版不做过度细分。

### 7.4 聚合层

首版 aggregate output 只保留下面 4 块：

1. `attachment_gap_rows`
   - report / brief 或 latest loader 已能看到 prior，但 final row 没有稳定保留。
2. `low_sample_or_weak_prior_rows`
   - final row 拿到了 prior，但样本量或质量信号太弱，无法给出更强判断。
3. `ticker_timeline_board`
   - 对重复 ticker 显示 report → brief → latest prior → final row 的状态演变。
4. `coverage_summary`
   - 说明这次 audit 到底覆盖了多少 row，跳过了多少，多少是 partial trace。

### 7.5 重复 ticker 视图

`ticker_timeline_board` 应优先服务当前高频重复名字，例如：

1. `300683`
2. `300720`
3. `003036`
4. `300018`
5. `600361`

这块输出的目的不是做漂亮时间线，而是回答：

- 同一个 ticker 在不同 report 中，prior 是一直缺、偶尔有、还是经常被后续 resolve 覆盖掉？
- 重复 ticker 的 `unknown` 是单一机制主导，还是混合机制主导？

## 8. Alpha / Beta / Gamma 分工

### Alpha

Alpha 负责：

- 定义 `trace_status` 是否足够区分真实 Alpha 问题。
- 判断 `attachment_gap_rows` 与 `low_sample_or_weak_prior_rows` 哪个更值得进入下一轮 refinement。
- 从重复 ticker 案例里归纳下一轮最值得试的 sample-quality split。

### Beta

Beta 负责：

- 复用已有 loader / resolver / attach helper 拼装新脚本。
- 确保 `prior_trace` 是确定性的、可复跑的。
- 避免复制已有 replay / historical prior 逻辑，保持脚本薄而清晰。

### Gamma

Gamma 负责：

- 约束这轮工作不要偷偷滑向 rollout loosening。
- 审查 `trace_status` 是否会夸大证据。
- 要求输出保持 fail-closed，避免把不完整数据写成强结论。

## 9. 数据流设计

这轮 audit 应按下面顺序流动：

1. 解析 report 输入，定位 upstream-shadow cohort。
2. 为每个 row 提取 `embedded_prior`。
3. 加载 ticker 级 `latest_loader_prior`。
4. 复现 final row 的 resolve / attach 路径，得到 `resolved_final_prior`。
5. 生成 `trace_status`。
6. 聚合成 `attachment_gap_rows`、`low_sample_or_weak_prior_rows`、`ticker_timeline_board`、`coverage_summary`。
7. 输出 JSON 与 Markdown artifact，以及一条明确 recommendation。

这里的关键设计点是：**不要只看 final row 的一个静态切片**。如果没有三层 prior 快照，脚本就无法区分 attachment 缺口和弱 prior 缺口。

## 10. 错误处理与 fail-closed 规则

这个 audit 必须 fail-closed，至少遵守 4 条规则：

1. 如果 report brief 或必要 artifact 缺失，把 report 记进 `skipped_reports`，不要伪造 row。
2. 如果某个 row 只有部分 trace 可用，保留 partial trace，但不要升级成强诊断。
3. 只有在得出结论所需层都齐全时，才允许输出 `resolve_dropped_stronger_prior` 这类强状态。
4. `coverage_summary` 必须明确区分：
   - `rows_audited`
   - `rows_skipped_for_missing_report_inputs`
   - `rows_with_partial_trace`

脚本允许对单行保留空字段，但不允许静默吞掉整个 cohort。

## 11. 验证设计

首版验证应保持 focused，而不是一上来跑大而全回归。

最小测试面包括：

1. `trace_status` 分类测试。
2. embedded / latest / resolved 三层 prior 排序与 merge 测试。
3. partial trace 与 missing report 的 fail-closed 测试。
4. 重复 ticker timeline 聚合测试。
5. 脚本级 JSON / Markdown 渲染测试。

建议新增：

- `tests/test_analyze_btst_upstream_shadow_unknown_prior_audit_script.py`

fixture 应使用最小化 `session_summary` / `brief_json` payload，避免对真实 report 目录的完整语料产生硬依赖。

## 12. 产物规划

如果后续实现获批，这轮至少要产出：

1. 一个 machine-readable 的 JSON audit artifact。
2. 一个供 Alpha / Beta / Gamma 讨论的 Markdown audit artifact。
3. 一条明确 recommendation，说明下一轮应优先修 attachment、修弱 prior fallback，还是再进入 label-generation 审计。
4. 不自动触发 skill 更新、runtime 调整或 rollout 放松。

## 13. 成功标准与退出条件

这轮设计在实现后，至少要能稳定回答 4 个问题：

1. 当前 upstream-shadow 的 `unknown`，主要是 attach 丢失还是弱 prior 主导。
2. 哪些 ticker / trade date 组合最能代表 attachment 缺口。
3. 哪些 ticker / trade date 组合其实拿到了 prior，但 prior 本身证据太弱。
4. 下一轮最应该进入的子项目，是 attachment repair、weak-prior fallback 审计，还是 label-generation 审计。

在这 4 个问题被稳定回答之前，upstream-shadow 主线应继续停留在 diagnosis mode，而不是重新进入 rollout-expansion mode。
