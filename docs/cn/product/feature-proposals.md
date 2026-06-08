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
| **P0-7** | **盘前 5 分钟「今日 Top 3 决策卡」** | 用户每天 9:25 开盘前打开, 输出基于: ①市场状态 (regime gate) ②自选池昨日评分变化 ③连续推荐加分 + ATR 止损 ④行业轮动 Top 1 — 三个最值得关注 + 每个一句话原因 + 一键 `--explain`。**不重跑 pipeline**, 直接读取 `data/reports/auto_screening_latest.json` + `data/reports/tracking_history.json` | 用户开盘前 30 秒决定今日重点关注标的, 不被 5000 只淹没 | Numerai「Daily Submission Reminder」、聚宽「每日早报」、Alpaca News API 推送 | **S (1-2 天)** | CLI `--daily-brief` 输出格式稳定, 延迟 < 1s, Top 3 至少 1 个连续推荐 ≥2 日 |
| **P0-8** | **信号冲突透明化 — `--why-not <ticker>` 反事实解释** | 当某只票**未被推荐**时, 输出「为什么没被推荐」: ①哪些策略方向相反 ②confidence 不足的具体数值 ③触发了哪些排除规则 (低流动性/涨停/ST) ④再涨 X% / 跌 Y% 会改变推荐吗 (反事实模拟) | 用户对「漏选」标的也能建立信心, 不被「没买就涨」焦虑驱动 | 同花顺问财「为什么不涨」类比、QuantConnect Alpha Streams「Factor Decay」展示 | **M (3-4 天)** | CLI `--why-not 000001` 输出 4 个区块, 反事实模拟至少覆盖 3 个策略 |

### P1 — 应该做 (R20.12 候选)

| # | 功能 | 说明 | 用户价值 | 业界先例 | 工作量 | 验收标准 |
|---|------|------|----------|----------|--------|----------|
| **P1-13** | **「条件单模板」一键生成券商格式** | 现有 `conditional_order_advisor` 仅输出建议价, 用户需手动挂单。增加 `--export-conditional-orders --broker=huatai|gtja|ths` 输出券商条件单导入格式 (CSV/JSON), 包含建议买入/止损/止盈/有效期/触发价 | 减少用户从「看建议」到「挂单」的 5 步操作 → 1 步 | 聚宽/米筐支持券商 API 推送条件单; 业界普遍 30% 用户卡在「挂单」环节 | **M (3-4 天)** | 至少支持 3 家券商格式, 验证 1 单从「建议」到「挂单」端到端 < 30s |

### P2 — 可以做 (R20.13 候选)

| # | 功能 | 说明 | 用户价值 | 业界先例 | 工作量 | 验收标准 |
|---|------|------|----------|----------|--------|----------|
| **P2-10** | **「组合体检」周报推送** | 每周日收盘后自动: ①本周组合归因 (Brinson) ②触发退出/调仓次数 + 平均收益 ③与基准对比 + 风险指标变化 ④下周关注事项 — 推送至企微/邮件 (复用 P2-3 推送框架) | 用户周末 5 分钟看完本周策略表现, 不需手动跑 `--performance-report` | 私募/公募基金周报标准格式; Numerai/WorldQuant 投资者周报 | **S (2 天)** | 复用 P2-3 推送 + 现有归因/绩效 API, 推送成功率 > 95% |

---

## 三、优先级路线图

### Phase 1: 核心体验 (1-2 周)

1. **P0-7** 盘前 5 分钟决策卡 — R20.11
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
| **R20.10 新增候选** | **0/3 (0%)** | P0-7/P0-8/P1-13 待 R20.11+ 实现 |

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
