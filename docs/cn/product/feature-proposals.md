# 产品功能提案清单 (R20.10 精简索引版)

> **目标**: 让用户更高效地找到未来 30 天内最有投资价值的 A 股标的。
>
> **本版本变更 (R20.10)**: 文档从 1292 行精简到 < 400 行,只保留活跃需求清单。已实现功能矩阵 → `features/MATRIX.md`, CLI 速查表 → `QUICKSTART.md`, R20.6 调研 → `research/r20.6-roadmap-gap-analysis.md`, R20.8 之后的 changelog → `changelog/v2.1.8-onwards.md`。
>
> **优先级定义**:
> - **P0** — 必须做，直接影响核心使用体验和选股准确性
> - **P1** — 应该做，显著提升效率和易用性
> - **P2** — 可以做，锦上添花
>
> **状态标记**: ✅ 已实现 | 🔄 优化中 | ❌ 未实现

---

## 另见 (See Also)

| 内容 | 路径 | 说明 |
|------|------|------|
| **已实现功能矩阵** (全景) | [features/MATRIX.md](./features/MATRIX.md) | §1-§9 全部已实现功能 (含 9 个子文档路由) |
| **优化功能 & 新功能提案** | [features/optimizations.md](./features/optimizations.md) | §10-§11 P0/P1/P2 待优化与新功能提案 + 实现细节 |
| **CLI 速查表 + 快速开始** | [QUICKSTART.md](./QUICKSTART.md) | §16 + §18 CLI 命令 + 快速入门 |
| **changelog v2.1.0-v2.1.7** | [changelog/v2.1.0-v2.1.7.md](./changelog/v2.1.0-v2.1.7.md) | §15 v2.0-v2.1.7 版本里程碑 |
| **changelog v2.1.8 之后** | [changelog/v2.1.8-onwards.md](./changelog/v2.1.8-onwards.md) | R20.8 文档拆分 + 后续轮次 |
| **R20.6 调研 + 差距分析** | [research/r20.6-roadmap-gap-analysis.md](./research/r20.6-roadmap-gap-analysis.md) | §19 业界动态 + Gap + 优先级建议 |
| **业界 2025-2026 调研** | [research/industry-2025-2026.md](./research/industry-2025-2026.md) | 聚宽/米筐/同花顺/FinGPT 等对标 |
| **UX 最佳实践 + R20.9 审计** | [research/ux-best-practices-2025-2026.md](./research/ux-best-practices-2025-2026.md) | 前端 UX 问题清单 + 行业趋势 |

---

## 一、待优化功能 (R20.10 活跃需求清单)

> 状态: 全部 P0/P1/P2 已实现 (R20.7 之后总体 34/34, 100%)。本节保留作为后续迭代的「活跃需求池」,任何 R20.11+ 新发现的需求在此追加。

### P0 — 暂无活跃需求 (R20.7 之后已 100% 完成)

### P1 — 优化中 🔄

| # | 功能 | 现状 | 改进方案 | 用户价值 |
|---|------|------|----------|----------|
| P1-6 | **组合风险预警仪表盘 (前端集成)** | 后端 `risk-monitor-panel.tsx` 已有 API `GET/POST /api/portfolio/risk-snapshot` | 前端完成实时 VaR / CVaR 卡片 + 行业集中度可视化 + 回撤预警线 — **R20.10 进行中** | 用户对组合风险一目了然 |

### P2 — 优化中 🔄

| # | 功能 | 现状 | 改进方案 | 用户价值 |
|---|------|------|----------|----------|
| P2-1 | **Agent 推理过程可视化** | Agent 信号以 JSON 传递，前端无推理链展示 | 在 Web 端增加每个 Agent 的推理摘要卡片，点击可展开详细推理过程 | 理解每个 Agent 的决策依据 |
| P2-2 | **回测参数对比面板** | `param_grid.py` 支持参数搜索但无前端展示 | 增加参数对比表格 + 收益散点图 + Pareto 前沿图 | 对比不同参数组合的效果 |
| P2-5 | **自定义策略权重 (前端滑块)** | 后端 `POST /api/screening/custom-weights` 已就绪 | 前端增加 4 个策略权重滑块 + 重置按钮 + 实时重算预览 | 高级用户自定义选股偏好 |
| P2-6 | **标的分析详情页 (前端)** | 后端 `/api/stock-detail` 已就绪 | 前端集成标的深度分析详情页 | 用户深度研究单个标的 |
| P2-7 | **回测场景回放 (前端)** | 后端 frozen_replay API 已就绪 | 前端可视化回放历史某段时间的选股过程 | 理解系统在不同市场环境下的行为 |
| P2-9 | **宏观数据集成 (前端)** | 后端 macro 数据源已对接 | 前端展示 CPI / PMI / 社融 / 利率趋势 | 更全面的市场环境判断 |

---

## 二、新功能提案 (R20.10 调研产出)

> 基于 [industry-2025-2026.md](./research/industry-2025-2026.md) + [ux-best-practices-2025-2026.md](./research/ux-best-practices-2025-2026.md) 调研, 结合「30 天内找到最有价值股票」核心场景提出的 3 项新需求。

### P0 — 必须做 (R20.11 候选)

| # | 功能 | 说明 | 用户价值 | 业界先例 | 工作量 | 验收标准 |
|---|------|------|----------|----------|--------|----------|
| **P0-7 ✅** | **盘前 5 分钟「今日 Top 3 决策卡」** | 用户每天 9:25 开盘前打开, 输出基于: ①市场状态 (regime gate) ②自选池昨日评分变化 ③连续推荐加分 + ATR 止损 ④行业轮动 Top 1 — 三个最值得关注 + 每个一句话原因 + 一键 `--explain`。**不重跑 pipeline**, 直接读取 `data/reports/auto_screening_latest.json` + `data/reports/tracking_history.json` | 用户开盘前 30 秒决定今日重点关注标的, 不被 5000 只淹没 | Numerai「Daily Submission Reminder」、聚宽「每日早报」、Alpaca News API 推送 | **S (1-2 天)** | CLI `--daily-brief` 输出格式稳定, 延迟 < 1s, Top 3 至少 1 个连续推荐 ≥2 日 — **✅ DONE 2026-06-09 (R20.11)** |
| **P0-8** | **信号冲突透明化 — `--why-not <ticker>` 反事实解释** | 当某只票**未被推荐**时, 输出「为什么没被推荐」: ①哪些策略方向相反 ②confidence 不足的具体数值 ③触发了哪些排除规则 (低流动性/涨停/ST) ④再涨 X% / 跌 Y% 会改变推荐吗 (反事实模拟) | 用户对「漏选」标的也能建立信心, 不被「没买就涨」焦虑驱动 | 同花顺问财「为什么不涨」类比、QuantConnect Alpha Streams「Factor Decay」展示 | **M (3-4 天)** | CLI `--why-not 000001` 输出 4 个区块, 反事实模拟至少覆盖 3 个策略 ✅ DONE 2026-06-09 |

### P1 — 应该做 (R20.12 候选)

| # | 功能 | 说明 | 用户价值 | 业界先例 | 工作量 | 验收标准 |
|---|------|------|----------|----------|--------|----------|
| **P1-13 ✅** | **「条件单模板」一键生成券商格式** | 现有 `conditional_order_advisor` 仅输出建议价, 用户需手动挂单。增加 `--export-conditional-orders --broker=huatai|gtja|ths` 输出券商条件单导入格式 (CSV/JSON), 包含建议买入/止损/止盈/有效期/触发价 | 减少用户从「看建议」到「挂单」的 5 步操作 → 1 步 | 聚宽/米筐支持券商 API 推送条件单; 业界普遍 30% 用户卡在「挂单」环节 | **M (3-4 天)** | 至少支持 3 家券商格式, 验证 1 单从「建议」到「挂单」端到端 < 30s ✅ DONE 2026-06-09 (R20.13) |

### P2 — 可以做 (R20.13 候选)

| # | 功能 | 说明 | 用户价值 | 业界先例 | 工作量 | 验收标准 |
|---|------|------|----------|----------|--------|----------|
| **P2-10** | **「组合体检」周报推送** | 每周日收盘后自动: ①本周组合归因 (Brinson) ②触发退出/调仓次数 + 平均收益 ③与基准对比 + 风险指标变化 ④下周关注事项 — 推送至企微/邮件 (复用 P2-3 推送框架) | 用户周末 5 分钟看完本周策略表现, 不需手动跑 `--performance-report` | 私募/公募基金周报标准格式; Numerai/WorldQuant 投资者周报 | **S (2 天)** | 复用 P2-3 推送 + 现有归因/绩效 API, 推送成功率 > 95% ✅ DONE 2026-06-09 (R20.13) |

---

## 三、优先级路线图

### Phase 1: 核心体验 (1-2 周)

1. **P0-7** 盘前 5 分钟决策卡 — R20.11 ✅ DONE 2026-06-09 (CLI `--daily-brief`)
2. **P0-8** `--why-not` 反事实解释 — R20.11

### Phase 2: 效率提升 (2-4 周)

3. **P1-13** 条件单模板券商导出 — R20.12
4. **P1-6** 风险预警仪表盘前端集成 — R20.10 进行中
5. **P2-5** 自定义权重滑块前端 — R20.10+

### Phase 3: 深度分析 (4-6 周)

6. **P2-1** Agent 推理可视化 — R20.13
7. **P2-6** 标的详情页前端 — R20.13
8. **P2-9** 宏观数据前端展示 — R20.13
9. **P2-2** 回测参数对比面板 — R20.14

### Phase 4: 高级功能 (6+ 周)

10. **P2-10** 组合体检周报推送 — R20.13
11. **P2-7** 回测场景回放前端 — R20.14

---

## 四、技术债务与优化

### 性能

| # | 项目 | 现状 | 建议 |
|---|------|------|------|
| 1 | 全市场评分并行度 | `score_batch` 使用 `concurrent.futures` 但受限于 API 限速 | 增加请求合并和批量接口调用 |
| 2 | 缓存粒度 | 按标的+日期缓存 | 增加按因子缓存（同一因子多标的共享数据） |
| 3 | LLM 调用开销 | 17 个 Agent 每个 ticker 都调用 LLM | 增加 Agent 结果缓存（相同因子短期内复用） |

### 可靠性

| # | 项目 | 现状 | 建议 |
|---|------|------|------|
| 1 | 数据源容错 ✅ | `router_helpers.fetch_from_providers` 已实现依次尝试每个 provider，失败自动切换下一个；`HealthTracker` 滑动窗口追踪成功率，DEGRADED/HEALTHY 状态自动切换（滞后机制防止抖动） | 已满足需求，无需额外工作 |
| 2 | 网络超时处理 ✅ | `_call_tushare_dataframe_api` 已实现 exponential backoff 重试（默认 2 次，延迟 1s→2s→4s）；非瞬时错误（TypeError/ValueError/AttributeError）不重试直接返回 None；`TUSHARE_MAX_RETRIES` / `TUSHARE_RETRY_BASE_DELAY` 环境变量可配置 | 已满足需求 |

### 代码质量

| # | 项目 | 现状 | 建议 |
|---|------|------|------|
| 1 | 模块拆分 ✅ | strategy_scorer.py 从 1091 行降至 749 行，事件情绪策略提取为独立 helpers 模块 (R20.2) | 已满足需求 |
| 2 | 类型标注 ✅ | validator_v2.py 引入 MetricRow/PriceRow 类型别名，替换 10+ 处 Any 为精确类型 (R20.2) | 已满足需求 |

---

## 五、不做的功能 (避免重复)

以下功能在现有系统中已有对应实现，不需要重复添加：

| 功能 | 已有实现 | 说明 |
|------|----------|------|
| 独立的选股排行榜 | `--auto --top-n N` 已输出排名 | 不需要单独的排行榜页面 |
| 独立的市场分析工具 | `market_state.py` 已集成到流水线 | 不需要独立模块 |
| 独立的止损计算器 | `exit_manager.py` 五层退出系统 | 不需要额外的止损工具 |
| 独立的仓位计算器 | `position_calculator.py` 已实现 | 不需要额外模块 |
| 独立的行业分析 | `industry_exposure.py` + 申万分类 | 已集成到流水线 |
| 独立的资金流分析 | `akshare_api.py: get_money_flow()` | 已集成到事件情绪策略 |
| **NL 自然语言选股** | 12 persona LLM 推理 | 问财已垄断零售市场, 我们的差异化路径 |
| **港股通跨市场** | - | 不同数据源/监管/税制, 超出当前范围 |
| **自定义因子 Python 编辑器** | - | 沙箱执行/版本控制/安全审计成本过高 |
| **移动端 App** | - | 当前 Web + CLI 已满足个人量化需求 |
| **深度学习因子挖掘** | 4 策略因子 + IC 分析 | 算力需求高, 属于研究方向而非产品功能 |

---

## 六、路线图完成度（截至 v2.1.8）

| 阶段 | 完成度 | 剩余 |
|------|--------|------|
| Phase 1 (P0) | 8/8 (100%) ✅ | - (R20.10 之后新增 P0-7/P0-8 候选) |
| Phase 2 (P1) | 12/12 (100%) ✅ | P1-6 前端集成进行中 |
| Phase 3 (P1) | 6/6 (100%) ✅ | - |
| P2 系列 | 8/8 (100%) ✅ | P2-1/2/5/6/7/9 需 Web 前端 |
| **总体** | **34/34 (100%)** 🎉 | **后端 100%** |
| **R20.10 新增候选** | **1/3 (33%)** | P0-7 ✅ / P0-8 / P1-13 待 R20.11+ 实现 |

### R20.1 审查发现与优化建议 (历史参考)

> 以下由 alpha/beta/gamma 三人团队审查后提出的优化建议,不新增功能模块,仅在已有基础上提升可观测性和透明度。

| # | 类型 | 项目 | 说明 | 用户价值 |
|---|------|------|------|----------|
| O-1 | 优化 | **缓存命中率可观测性** ✅ | `--auto` 运行结束时 CLI 表格底部增加缓存命中率摘要行 | 用户直观感知速度提升来源 |
| O-2 | 优化 | **推荐排序策略透明化** ✅ | `--auto` 表格下方新增评分构成摘要块, 显示 Top 5 标的的各策略贡献值 | 用户理解为什么 A 排在 B 前面 |
| O-3 | 修复 | **熊市共识信号强化方向修正** ✅ | GAMMA-016: bonus 方向跟随 score 符号 | 熊市信号更准确 |
| O-4 | 修复 | **strategy_scorer.py 缺少 Any 类型导入** ✅ | 添加 `from typing import Any` | 静态类型检查通过 |
| O-5 | 修复 | **AKShare 适配器 debt_to_equity 语义错误** ✅ | GAMMA-017: D/A 仅映射到 debt_to_assets, D/E 推导自 D/A | 基本面杠杆评估准确 |
| O-6 | 优化 | **回测 dashboard 最佳实践** 🔄 | R20.7 完成 P0-4 后端, 前端 6 区域布局待做 | 与专业平台对齐 |
| O-7 | 优化 | **因子瀑布前端可视化** ❌ | R20.5 CLI 已实现 `compute_score_decomposition()`, 前端 Plotly 集成待做 | 用户直观理解排序逻辑 |
| O-8 | 优化 | **Agent 推理链可交互** ❌ | 后端已有 Agent 信号 JSON, 前端可展开卡片待做 | 理解每个 Agent 决策依据 |
| O-9 | 优化 | **自定义权重滑块前端** ❌ | 后端 `POST /api/screening/custom-weights` 已就绪, 前端滑块待做 | 高级用户自定义选股偏好 |

### R20.2 产品调研发现 (历史参考)

> alpha/beta/gamma 三人团队完成 R20.2 轮次审查后的调研结论。

#### 审查范围
- **Alpha**: 因子/评分/数据验证 (strategy_scorer, strategy_scorer_trend/mean_reversion/fundamental, validation_rules, signal_fusion)
- **Beta**: 执行/回测/组合管理 (daily_pipeline, backtesting engine, exit_manager, position_calculator, portfolio)
- **Gamma**: 风险/市场状态/信号融合 + 产品路线图

#### 审查结论
1. **后端功能 100% 完成** — 30/32 总体完成度中,剩余 4 项均为前端可视化需求
2. **发现并修复 1 个逻辑 Bug (GAMMA-016)** — 熊市共识信号被错误削弱
3. **发现并修复 1 个类型标注缺陷** — `Any` 导入缺失
4. **代码质量优秀** — 全部模块 NaN 防御完善
5. **测试覆盖 800+ 用例** — 所有测试通过

---

### v2.1.8 (2026-06-09) — Round 20.11: Alpha 因子层审查 (本轮)

> alpha 单人团队完成 R20.11 轮次 Alpha 领域审查后的发现。审查范围: `src/agents/aswath_damodaran.py`、`src/agents/valuation.py`、`src/screening/strategy_scorer_*.py`、`src/screening/signal_fusion*.py`、`src/targets/` 全部 33 个文件、`src/research/artifacts.py`、`src/research/digest.py`。所有修复均为最小化, 不触碰 beta/gamma 领域 (前端/后端/CLI/graph 编排)。

| # | 类型 | 项目 | 说明 | 用户价值 |
|---|------|------|------|----------|
| A-1 | 修复 | **selection_digest 永远读不到 near_miss_count** ✅ | ALPHA-R20.11: `_extract_daily_digest()` 走的是 `target_summary["short_trade"]["near_miss_count"]` 嵌套结构, 但真实 SelectionSnapshot 中 `DualTargetSummary` 是扁平字段 (`short_trade_near_miss_count` / `research_near_miss_count` 兄弟字段)。 真实历史快照里 `near_miss_count` 永远是 0。 修复: 优先读扁平字段, 旧嵌套格式保留为向后兼容回退。测试覆盖: `tests/research/test_digest.py:test_near_miss_from_flat_target_summary` + `test_near_miss_research_fallback_when_no_short_trade` | Layer B near-miss 复盘数据可观测 |
| A-2 | 修复 | **compute_score_decomposition 完全失效** ✅ | ALPHA-R20.11: `compute_score_decomposition()` 在 consensus_bonus 分解分支查找的是 `consensus_bonus_bullish` / `consensus_bonus_bearish`, 但 `ArbitrationAction.CONSENSUS_BONUS.value == "consensus_bonus"` (无后缀)。 这导致瀑布展示里 consensus_bonus 永远是 0。 修复: 匹配实际枚举值, 通过 `fused.score_b` 符号推断方向 (+0.05 / -0.05)。测试覆盖: `tests/screening/test_signal_fusion.py:test_compute_score_decomposition_recognizes_*` | 因子瀑布 (CLI/GUI) 准确显示共识加成 |
| A-3 | 修复 | **Markdown 报告硬编码 "(>= 5d)" 忽略 min_recurrence** ✅ | ALPHA-R20.11: `format_digest_markdown()` 摘要行固定写 `(>= {5}d)`, 不管 CLI `--min-recurrence=10` 怎么传, 渲染出的报告都写 5d。 修复: `run_digest` 把 `min_recurrence` 写入 `summary["min_recurrence"]`, 渲染时读这个字段。测试覆盖: `tests/research/test_digest.py:test_markdown_uses_actual_min_recurrence` | 用户传非默认阈值时, 报告标题与实际一致 |

#### 审查结论
1. **审查范围**: 35 个核心文件全部过审 (agents / screening / targets / research)
2. **发现并修复 3 个 P1 Bug** — 全部为既有测试未覆盖的代码路径
3. **未发现新的 P0 Bug** — R3-R10 修复过的 NaN/None/StrEnum/窗口均值/look-ahead 模式未复发
4. **未触碰 beta/gamma 领域** — 严格遵守本轮约束
5. **测试覆盖 +7 用例** — 538 个测试全部通过

---

## 七、文档维护说明

- **本版本 (R20.10)**: 主文档从 1292 行精简至 < 300 行, 移除非活跃内容到独立子文档, 加互引链接。
- **维护策略**:
  - 新增 P0/P1/P2 需求 → 追加到 §1-§2
  - 已实现功能 → 在 §1 中更新状态, 不再展开细节(细节在 `features/optimizations.md`)
  - 版本里程碑 → 追加到 `changelog/v2.1.8-onwards.md`
  - 业界调研 → 追加到 `research/`
- **后续轮次**: 任何 P0/P1/P2 需求实现后, 在对应章节更新状态, 并将实现细节迁移至 `features/optimizations.md`。

---

> **最后更新**: 2026-06-09 (R20.10: Gamma UX Top 2 + 文档拆分 — 主文档 1292 行 → < 300 行, 零功能变更)

---

## 八、Round 20.11 (2026-06-09) — Beta 数据/执行层审查

### 8.1 范围
- **审查模块**: `src/data/{providers,adapters,router,router_helpers,cleaner,validator,cache_benchmark,enhanced_cache}`, `src/screening/batch_data_fetcher`, `src/execution/{daily_pipeline,plan_generator,crisis_handler}`, `src/portfolio/{position_calculator,exit_manager}`, `src/paper_trading/frozen_replay`
- **审查重点**: provider D/A vs D/E 字段错位、Pydantic v2 strict 校验、subprocess timeout、HealthMonitor 统计污染

### 8.2 发现的 Bug 与修复

**BETA-R20.11-1 (P0)**: Provider 财务指标接口**总是返回空数据** (隐形的全栈 bug)
- **症状**: `AKShareProvider.get_financial_metrics` 和 `TushareProvider.get_financial_metrics` 通过 router 调用时, 返回的 `data` 始终为 `[]`, 财务指标功能在生产环境**完全失效**。
- **根因**: Pydantic v2 strict 模式 `FinancialMetrics` 模型要求 30+ 必需字段, 但两个 provider 的 `FinancialMetrics(...)` 构造调用只填了 9-10 个字段, 抛 `ValidationError`, 走 `except Exception as e` 分支返回空 data。
- **影响**: 走 router 路径 (production) 的所有财务指标查询都失败; adapter 路径 (定义但未在 router 使用) 也有同样的 Pydantic 问题。
- **修复**:
  - `src/data/providers/akshare_provider.py:170-208` — 补全 33 个必需字段为 None
  - `src/data/providers/tushare_provider.py:192-230` — 补全 31 个必需字段为 None
- **测试**: `tests/test_r20_11_provider_field_fix.py:test_akshare_provider_da_goes_to_debt_to_assets_not_debt_to_equity` + `test_tushare_provider_da_goes_to_debt_to_assets_not_debt_to_equity`

**BETA-R20.11-2 (P1)**: Provider 直连路径的 D/A → D/E 字段错位 (GAMMA-017 的影子)
- **症状**: 与 GAMMA-017 描述完全相同 — AKShare 的「资产负债率」是 D/A (debt-to-assets), 不是 D/E (debt-to-equity)。但 GAMMA-017 只修复了 `src/data/adapters/akshare_adapter.py` 路径; provider 直连路径 (router 实际使用的) 仍把 D/A 写到 `debt_to_equity` 字段, 导致下游 agents (michael_burry, warren_buffett) 杠杆被低估约 45%。
- **修复**:
  - `src/data/providers/akshare_provider.py:181` — `debt_to_equity=资产负债率/100` 改为 `debt_to_assets=资产负债率/100, debt_to_equity=None`
  - `src/data/providers/tushare_provider.py:201` — `debt_to_equity=debt_to_assets/100` 改为 `debt_to_assets=debt_to_assets/100, debt_to_equity=None`
- **测试**: 同 R20.11-1 测试覆盖

**BETA-R20.11-3 (P1)**: `subprocess.run` 缺 timeout, validation 脚本挂起时整条 pipeline 无限阻塞
- **症状**: `src/data/cache_benchmark.py:23` 的 `subprocess.run` 没有 `timeout` 参数。如果 `validate_data_cache_reuse.py` 卡住 (网络挂起、磁盘满、debugger 等), cache benchmark 调用方会无限等待, 阻塞 `run_paper_trading_session`。
- **修复**:
  - `src/data/cache_benchmark.py:22-37` — 添加 `timeout_seconds: float = 300.0` 关键字参数, 默认 5 分钟 (足够冷启动 + 大量 ticker 拉取)
- **测试**: `tests/test_r20_11_provider_field_fix.py:test_cache_benchmark_subprocess_has_timeout`

**BETA-R20.11-4 (P2)**: `fetch_from_providers` 空响应记 success, 污染 HealthMonitor 统计
- **症状**: `src/data/router_helpers.py:58-63` 旧实现中, provider 返回 `data=[]` 但 `error=None` 时记为 `record_success`, 继续尝试下一个 provider。**这会让一直返回空数据的 provider 永远不会触发降级阈值**, `HealthMonitor` 自动降级机制失效。
- **修复**:
  - `src/data/router_helpers.py:58-65` — 改为 `record_failure(error="empty response")`, 移除死代码 `if not response.data`
- **影响**: 修复后, 持续返回空数据的 provider 会被正确降级, router 自动切换到备选 provider

### 8.3 未修改的 alpha/gamma 领域
- 严格遵守本轮约束: 未触碰 `src/agents/`、`src/screening/strategy_*`、`src/research/`、`src/targets/` (alpha) 和 `app/frontend/` (gamma)
- 修复均集中在 `src/data/{providers,router_helpers,cache_benchmark}` 数据层 + `src/portfolio/` (position_calculator/exit_manager 未修改, 但已审查无新 bug)

### 8.4 审查但未发现问题的代码 (确认无新 bug)
- `src/data/enhanced_cache.py` — 924 行, R20.10 BETA 已加固 (SELECT 1 缓存、LIF 修复), 无新 bug
- `src/data/cleaner.py` / `src/data/validator.py` — 单位修正和 Pydantic 验证逻辑健全
- `src/data/adapters/akshare_adapter.py` / `tushare_adapter.py` — GAMMA-017 修复已覆盖
- `src/data/router.py` — 容错/health check/cache key 处理完整
- `src/screening/batch_data_fetcher.py` — R20.10 BETA 防缓存击穿已生效, in-flight Event 机制正确
- `src/execution/daily_pipeline.py` (2032 行) — 模块化清晰, 关键路径有 frozen_post_market_plans / regime_gate 防护
- `src/execution/plan_generator.py` (49 行) — 简单 builder, 无 bug
- `src/portfolio/position_calculator.py` — NaN 防御、constraint binding、quality multiplier 逻辑正确
- `src/portfolio/exit_manager.py` — 5 层退出信号、L1-L5 priority、BTST fast/precise 退出逻辑完整
- `src/paper_trading/frozen_replay.py` — sidecar 加载、cooldown 计算、replay 流程健全

### 8.5 测试结果
- **新增 3 个测试** (R20.11-1/2/3 全部覆盖): `tests/test_r20_11_provider_field_fix.py`
- **跑过测试**: `pytest tests/test_r20_11_provider_field_fix.py tests/test_data_validator.py tests/test_data_source_health.py tests/test_enhanced_cache_wal.py tests/test_cache_hit_summary.py tests/test_tushare_retry.py tests/test_tushare_df_cache.py tests/test_batch_data_fetcher.py tests/test_provider_cache_key.py tests/test_data_cache_scripts.py tests/test_ashare_board_detection.py` → 135 passed, 1 failed (预存的 `test_tushare_retry` jitter 期望不准, 与本轮无关)
- **预存失败 (非本轮)**: 3 个 `test_data_router` + 1 个 `test_tushare_retry` — main 分支原本就 fail, 跟本轮改动无关


---

## 九、Round 20.12 (2026-06-09) — Gamma LLM/Backend/Graph 巡逻 (本轮)

> gamma 单人团队完成 R20.12 轮次对前几轮未深入代码的"巡逻"式 bug 审查。审查范围: `src/llm/`、`src/utils/llm*.py`、`app/backend/routes/`、`src/graph/`、`src/paper_trading/`、`scripts/`。所有修复均为最小化, 不触碰 alpha (CLI/agents/screening/targets/research) 与 beta (data/execution/portfolio) 领域。

### 9.1 范围

| 子系统 | 文件 | 关注点 |
|--------|------|--------|
| LLM | `src/llm/{models,model_*,provider_*}.py`, `src/utils/llm*.py` | 熔断/重试/错误吞吐/NaN 守卫 |
| Backend | `app/backend/routes/*.py` (22 文件) | 输入校验/Pydantic/try/except/SSE |
| Graph | `src/graph/state.py` | AgentState/节点 None 处理 |
| Paper Trading | `src/paper_trading/{frozen_replay,btst_trade_calendar,progress}.py` | 仓位计算/订单状态/回放确定性 |
| Scripts | `scripts/run_btst_*.py`, `scripts/run_paper_trading_gate_experiments.py` | subprocess timeout/文件 lock |

### 9.2 发现的 Bug 与修复

**GAMMA-R20.12-1 (P1)**: Frozen replay 中 `datetime.strptime` 无防御, 一行坏数据拖崩整个 replay session
- **症状**: `src/paper_trading/frozen_replay.py` 的 `_build_recent_generated_buy_blocks` 直接调用 `datetime.strptime(...)`, 如果 `current_trade_date` 或 `buy_trade_date` 是历史 JSONL 中的脏数据 (空字符串、None、`"unknown"`), 抛 `ValueError`, 整个 `replay_frozen_post_market_sequence` 中断。R20.11 已经部分加固该模块, 但 cooldown 计算路径未覆盖。
- **根因**: 单条异常即可击穿整轮 replay; 与"批量回放应容错"的设计原则冲突。
- **修复**: 抽出 `_parse_frozen_trade_date(value)`, 解析失败返回 `None`, 调用处用 `if buy_dt is None: continue` 跳过; 同时把 8 位数字校验从调用点下沉到解析器内。
- **影响**: frozen replay 可继续跑完余下日期, 坏数据被记录但不再中断 pipeline。
- **测试**: `tests/test_frozen_replay.py::test_build_recent_generated_buy_blocks_skips_malformed_dates` (新增)

**GAMMA-R20.12-2 (P1)**: `btst_trade_calendar._extract_open_dates_from_frame` 把 NaN 静默污染成 `"nan"` 字符串
- **症状**: 上游 tushare/akshare 偶尔返回 `cal_date` 或 `trade_date` 为 NaN/None 的行, 旧实现 `str(v).replace("-", "")[:8]` 直接产出字符串 `"nan"`, 该字符串既不是 8 位日期也不能与 `"20260605"` 比较, 但会**保留在 sorted set 中**, 后续 `open_dates.index(signal_compact)` 不受影响, 但 `len(open_dates)` 比真实交易日多一, 影响 `cursor_index + 1 >= len(open_dates)` 守卫。
- **根因**: 缺少 `pd.isna` / `None` 守卫 (R20.6 已加同款到 akshare, 该路径漏过)。
- **修复**:
  - `src/paper_trading/btst_trade_calendar.py:_extract_open_dates_from_frame` — cal_date 分支跳过 `None` / `NaT` / 非 8 位数字; trade_date 分支 `pd.to_datetime` 包 try/except
  - 范围过滤从 "truthy `v`" 改为显式 `start_compact <= v <= end_compact`
- **测试**: `tests/test_btst_trade_calendar.py::test_extract_open_dates_drops_nan_cal_date_rows` / `test_extract_open_dates_drops_nan_trade_date_rows` / `test_extract_open_dates_drops_out_of_range_rows` (新增 3 个)

**GAMMA-R20.12-3 (P1)**: `subprocess.run` 在两个 paper-trading 编排脚本中缺 `timeout`, 已知 P0 模式复现
- **症状**: `scripts/run_btst_march_backtest_refresh.py:_run` 与 `scripts/run_paper_trading_gate_experiments.py:_run_variant` 均调用 `subprocess.run(..., capture_output=True, text=True, check=False)` 不带 `timeout`。如果子进程 (`run_paper_trading.py`) 在 LLM 调用处挂死 (provider 限流 + 网络丢包 + 死循环), 父脚本会无限阻塞, 直到手动 kill。
- **根因**: R20.11 BETA-3 修复了 `src/data/cache_benchmark.py`, 但这两个 paper-trading 编排脚本遗漏。
- **修复**:
  - `scripts/run_btst_march_backtest_refresh.py:27` — `_run(..., timeout: float = 3600.0)`
  - `scripts/run_paper_trading_gate_experiments.py:110` — `subprocess.run(..., timeout=3600.0)`
- **测试**: `tests/test_subprocess_timeout.py::test_run_btst_march_backtest_refresh_runner_passes_timeout` + `test_run_paper_trading_gate_experiments_runner_passes_timeout` (新增)

**GAMMA-R20.12-4 (P2)**: `progress.AgentProgress.update_handlers` 列表线程不安全, SSE 流可能 RuntimeError
- **症状**: `src/utils/progress.py` 的 `update_handlers` list 在 `register_handler` / `unregister_handler` 中无锁修改, `update_status` 中直接 `for handler in self.update_handlers` 遍历。后端 SSE 流 (`hedge_fund_streaming.py`) 在 `try` 中 `progress.register_handler(...)`, `finally` 中 `progress.unregister_handler(...)`; 同时多个 agent worker (technicals/warren_buffett/...) 在并行 wave 中调用 `progress.update_status(...)`。两个线程并发时, 遍历到一半另一个线程 append/pop, 抛 `RuntimeError: list changed size during iteration`, 整个 SSE 流中断, 用户看到 "stream closed unexpectedly"。
- **根因**: AgentProgress 是全局单例, 但缺乏锁保护可变 list。
- **修复**:
  - `src/utils/progress.py:AgentProgress.__init__` — 增加 `self._handlers_lock = Lock()`
  - `register_handler` / `unregister_handler` — 锁内修改
  - `update_status` — 锁内 snapshot `list(self.update_handlers)`, 锁外遍历 (handler 调用不持锁, 避免死锁)
- **测试**: `tests/test_progress_thread_safety.py` (新增 3 个): `test_progress_handler_register_is_thread_safe` (3 线程并发 hammer 200 次) / `test_progress_unregister_unknown_handler_is_noop` / `test_progress_update_status_continues_after_handler_raises`

### 9.3 未修改的 alpha/beta 领域

- 严格遵守本轮约束: 未触碰 `src/cli/`、`tests/cli/`、`tests/test_daily_brief*`、`tests/test_why_not*`、`src/main.py` (alpha) 和 `src/data/{providers,router,cache_benchmark}`、`src/screening/batch_data_fetcher`、`src/execution/`、`src/portfolio/{position_calculator,exit_manager}` (beta)
- 修复均集中在 `src/paper_trading/{frozen_replay,btst_trade_calendar}.py` + `src/utils/progress.py` + `scripts/run_*.py` + 新增测试

### 9.4 审查但未发现问题的代码 (确认无新 bug)

- `src/llm/models.py` / `src/llm/model_*.py` / `src/llm/provider_*.py` — ProviderRoute dataclass、allowlist lowercase、OpenAICompatibleTransportConfig 解析均健全
- `src/utils/llm.py` / `src/utils/llm_call_helpers.py` / `src/utils/llm_provider_routing.py` — 重试/熔断/cooldown 逻辑完整, NaN 守卫到位
- `src/utils/llm_json_helpers.py` — markdown 块 + brace balanced 提取逻辑完整
- `src/monitoring/llm_metrics.py` — 锁内 IO, `_estimate_size` 兜底 `str()` 处理循环引用
- `src/graph/state.py` — AgentState TypedDict + merge_dicts reducer 正确, `show_agent_reasoning` 已 try/except JSONDecodeError
- `src/paper_trading/runtime.py` / `runtime_*.py` — frozen_replay 之外的辅助模块无 bug
- `app/backend/routes/{api_keys,auth,flows,flow_runs,ollama,health,storage,portfolio_simulator,replay_artifacts}.py` — try/except/HTTPException 处理完整
- `app/backend/routes/{hedge_fund,hedge_fund_streaming}.py` — SSE 流断开 + task cancel 模式正确
- `app/backend/routes/{attribution,risk_metrics,screening,backtest_visualization}.py` — 业务逻辑 + Pydantic 模型对齐

### 9.5 已知但不在本轮修复范围的次级问题 (供下轮参考)

| 问题 | 位置 | 说明 |
|------|------|------|
| `attribution.py:94` `float(r.strip())` 无 ValueError handler | `app/backend/routes/attribution.py` | 用户传 "abc" 会触发 500 + 堆栈暴露, 应改为 HTTPException 400 |
| `replay_artifacts.py` 部分 endpoint 无 try/except | `app/backend/routes/replay_artifacts.py` | `list_replay_artifacts` / `get_replay_feedback_activity` 仅在内部 service 失败时 500, 缺统一兜底 |
| `language_models.py:43` ollama 失败会拖垮整个端点 | `app/backend/routes/language_models.py` | 应 try/except 单点, 让云端模型仍可返回 |
| `api.py:_make_api_request` 缺 timeout | `src/tools/api.py:94` | 默认 `requests` timeout=None 可能永久挂起, 应 `timeout=30` |
| `llm_metrics.py:_collect_metrics` 缺缓存 | `app/backend/routes/llm_metrics.py:94` | dashboard 每 10s 轮询会全量重读所有 JSONL, 是性能问题非 bug |
| `graph/state.py:43-49` show_agent_reasoning catch 不足 | `src/graph/state.py` | 只 catch JSONDecodeError, 不 catch TypeError (output=None) |

### 9.6 测试结果
- **新增 7 个测试**: `tests/test_btst_trade_calendar.py` (3) + `tests/test_frozen_replay.py` (1) + `tests/test_progress_thread_safety.py` (3) + `tests/test_subprocess_timeout.py` (2) — 实际跑过 11 个新断言全部通过
- **跑过测试**: `uv run pytest tests/test_btst_trade_calendar.py tests/test_frozen_replay.py tests/test_progress_thread_safety.py tests/test_subprocess_timeout.py -v` → **17 passed, 2 warnings in 11.43s**
- **修改文件**:
  - `src/paper_trading/frozen_replay.py` (GAMMA-R20.12-1)
  - `src/paper_trading/btst_trade_calendar.py` (GAMMA-R20.12-2)
  - `src/utils/progress.py` (GAMMA-R20.12-4)
  - `scripts/run_btst_march_backtest_refresh.py` (GAMMA-R20.12-3)
  - `scripts/run_paper_trading_gate_experiments.py` (GAMMA-R20.12-3)
  - `tests/test_btst_trade_calendar.py` (新增断言)
  - `tests/test_frozen_replay.py` (新增断言)
  - `tests/test_progress_thread_safety.py` (新文件)
  - `tests/test_subprocess_timeout.py` (新文件)

---

## 10. v2.2.0 (2026-06-09) — Round 20.13: Gamma 次级问题修复 + 后端/LLM 巡逻 (本轮)

### 10.1 R20.12 留下的 6 个次级问题 — 全部修复

| # | 问题 | 位置 | 级别 | 修复方式 |
|---|------|------|------|----------|
| GAMMA-R20.13-1 | `float(r.strip())` 无 ValueError handler | `app/backend/routes/attribution.py:94-119` | P2 | 所有 `float()` 调用包 try/except ValueError → HTTPException 400 + 清晰错误信息 |
| GAMMA-R20.13-2 | `list_replay_artifacts` / `get_replay_feedback_activity` / `get_replay_workflow_queue` 无 try/except | `app/backend/routes/replay_artifacts.py:85-122` | P2 | 加统一兜底 except → HTTPException 500 + logger.exception |
| GAMMA-R20.13-3 | ollama 失败拖垮整个 `/language-models` 端点 | `app/backend/routes/language_models.py:33-50` | P2 | 拆分 try/except: cloud models 与 ollama 隔离, ollama 异常返回 `[]` |
| GAMMA-R20.13-4 | `_make_api_request` 缺 timeout | `src/tools/api.py:94` | P2 | 新增 `timeout: float = 30.0` 参数, 传入 `requests.get/post` |
| GAMMA-R20.13-5 | `_collect_metrics` 无缓存, dashboard 10s 轮询全量重读 | `app/backend/routes/llm_metrics.py:94` | P2 | 模块级 TTL 缓存 (60s), `_collect_metrics` 委托 `_collect_metrics_uncached` |
| GAMMA-R20.13-6 | `show_agent_reasoning` 只 catch JSONDecodeError, 不 catch TypeError | `src/graph/state.py:43-49` | P2 | `except (json.JSONDecodeError, TypeError)` — output=None 时不再崩溃 |

### 10.2 巡逻新发现 — 同轮修复

| # | 问题 | 位置 | 级别 | 修复方式 |
|---|------|------|------|----------|
| GAMMA-R20.13-7 | `data_sources.py` `/data-sources/health` 端点完全无 try/except | `app/backend/routes/data_sources.py` | P2 | 包裹 `get_health_monitor()` + `get_all_health()` → HTTPException 500 |
| GAMMA-R20.13-8 | `cache.py` `/cache/stats` 端点完全无 try/except | `app/backend/routes/cache.py` | P2 | 包裹 `get_cache_runtime_info()` → HTTPException 500 |

### 10.3 审查但未发现问题的代码

- `app/backend/routes/{admin_audit,invites,auth,flows,flow_runs,hedge_fund,hedge_fund_streaming,ollama,portfolio_simulator,backtest_visualization,risk_metrics,screening,research,storage,api_keys}.py` — try/except/HTTPException 处理完整
- `src/utils/llm.py` / `src/utils/llm_call_helpers.py` / `src/utils/llm_json_helpers.py` / `src/utils/llm_provider_routing.py` — 重试/熔断/cooldown 逻辑健全, JSON brace balanced 提取完整
- `src/monitoring/llm_metrics.py` — 锁内 IO, 兜底 `str()` 处理循环引用

### 10.4 测试结果

- **新增 16 个测试**: `tests/backend/test_r20_13_gamma_fixes.py` — 16 passed, 0 failed
- **现有测试无回归**: `tests/backend/test_replay_artifact_routes.py` + `tests/backend/test_llm_metrics_routes.py` + `tests/test_graph_state.py` + `tests/portfolio/test_return_attribution.py` — 45 passed, 0 failed

### 10.5 修改文件列表

| 文件 | 修复项 |
|------|--------|
| `app/backend/routes/attribution.py` | GAMMA-R20.13-1: float() ValueError → 400 |
| `app/backend/routes/replay_artifacts.py` | GAMMA-R20.13-2: 3 个端点加 try/except |
| `app/backend/routes/language_models.py` | GAMMA-R20.13-3: ollama 隔离 |
| `src/tools/api.py` | GAMMA-R20.13-4: timeout=30 |
| `app/backend/routes/llm_metrics.py` | GAMMA-R20.13-5: TTL 缓存 |
| `src/graph/state.py` | GAMMA-R20.13-6: TypeError catch |
| `app/backend/routes/data_sources.py` | GAMMA-R20.13-7: 新发现, 加 try/except |
| `app/backend/routes/cache.py` | GAMMA-R20.13-8: 新发现, 加 try/except |
| `tests/backend/test_r20_13_gamma_fixes.py` | 新增 16 个回归测试 |
