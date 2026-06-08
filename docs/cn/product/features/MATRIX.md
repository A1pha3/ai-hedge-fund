# 已实现功能矩阵 (v2.1 全景索引)

> 本文档对应主文档 §1-§9,作为已实现功能的「全景索引」。每个章节均包含到细分 `features/*.md` 子文档的链接,供深入阅读。
>
> **状态**: 全部 ✅ 已实现(R20.7 之后总体 34/34 路由完成度 100%, 6 项需前端集成)
>
> **主文档**: [feature-proposals.md](../feature-proposals.md) | **本节路由**: [§1](./core-pipeline.md) | [§2](./execution-system.md) | [§3](./backtesting.md) | [§4](./paper-trading.md) | [§5](./web-app.md) | [§6](./data-infrastructure.md) | [§7](./llm-system.md) | [§8](./agents.md) | [§9](./cli-reference.md)

---

## §1. 核心筛选流水线

详细章节: [core-pipeline.md](./core-pipeline.md)

### 1.1 全市场快筛 (Layer A 候选池)

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 全 A 股扫描 (~5000 只) | ✅ | `src/screening/candidate_pool.py` — 自动获取全市场股票列表 |
| 2 | ST/*ST 排除 | ✅ | 名称包含 ST 的标的自动排除 |
| 3 | 北交所排除 | ✅ | BJ 市场 / 4xxxxx / 8xxxxx / 92xxxx 排除 |
| 4 | 次新股排除 (<60 交易日) | ✅ | 上市不满 60 个交易日自动排除 |
| 5 | 停牌标的排除 | ✅ | 当日停牌标的排除 |
| 6 | 涨停标的排除 | ✅ | 当日涨停标的排除(买入排队失败) |
| 7 | 长期停牌复牌标的排除 | ✅ | 停牌超 5 日后复牌未满 3 个交易日排除 |
| 8 | 低流动性排除 (<5000 万) | ✅ | 近 20 日均成交额 <5000 万排除 |
| 9 | 冷却期标的排除 (15 日) | ✅ | 冲突仲裁标记的回避冷却期标的排除 |
| 10 | Shadow 影子池 | ✅ | 低流动性边界候选保留为影子池，用于扩展观察 |

### 1.2 四策略评分 (Layer B)

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 趋势策略评分 | ✅ | `src/screening/strategy_scorer_trend.py` — 趋势跟踪+动量因子 |
| 2 | 均值回归策略评分 | ✅ | `src/screening/strategy_scorer_mean_reversion.py` — 超跌反弹+反转因子 |
| 3 | 基本面策略评分 | ✅ | `src/screening/strategy_scorer_fundamental.py` — 估值+财务质量因子 |
| 4 | 事件情绪策略评分 | ✅ | `src/screening/strategy_scorer.py` — 新闻情绪+龙虎榜+资金流 |
| 5 | 子因子聚合框架 | ✅ | SubFactor 标准三元组 (direction, confidence, completeness) |
| 6 | 数据完整度感知 | ✅ | completeness 指标自动降权不完整数据 |

### 1.3 信号融合与冲突仲裁 (Layer B → Layer C)

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 加权融合评分 (score_b) | ✅ | `src/screening/signal_fusion.py` — 四策略加权融合 |
| 2 | 市场状态自适应权重 | ✅ | trend/range/mixed/crisis 四状态动态调权 |
| 3 | Hurst 指数冲突解决 | ✅ | 趋势/反转信号冲突时的 Hurst 仲裁 |
| 4 | 强制回避仲裁 | ✅ | 极端信号自动触发回避标记 |
| 5 | 质量优先守卫 | ✅ | `LAYER_B_ANALYSIS_QUALITY_FIRST_GUARD` 防止低质量信号通过 |
| 6 | 行业集中度检查 | ✅ | Top N 推荐中同一行业占比超 40% 自动预警 |

### 1.4 市场状态检测

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | ADX 趋势强度 | ✅ | `src/screening/market_state.py` |
| 2 | ATR 价格波动率 | ✅ | 波动率异常检测 |
| 3 | 市场宽度 (涨跌比) | ✅ | 全市场涨跌家数比 |
| 4 | 北向资金连续流入/流出 | ✅ | 连续流入/流出天数统计 |
| 5 | 涨跌停数量 | ✅ | 极端市场信号 |
| 6 | 仓位系数 (position_scale) | ✅ | 根据市场状态动态调整建议仓位 |
| 7 | Regime Gate 级别 | ✅ | normal/caution/halt/shadow_only 四级门控 |

---

## §2. 执行系统

详细章节: [execution-system.md](./execution-system.md)

### 2.1 日度执行流水线

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 七步流水线 | ✅ | `src/execution/daily_pipeline.py` — Layer A → B → C → 买入/卖出决策 |
| 2 | 执行计划生成 (ExecutionPlan) | ✅ | 买入/卖出/待处理订单完整输出 |
| 3 | 待处理订单队列 (涨跌停) | ✅ | PendingOrder 管理，涨停排队自动排队 |
| 4 | Catalyst Theme 催化剂主题 | ✅ | 热点主题候选评分与入选 |
| 5 | 历史先验附加 | ✅ | 历史选股结果附加到候选分析 |
| 6 | Shadow Promotion 影子晋升 | ✅ | 影子池候选满足条件后晋升到正式池 |
| 7 | 危机处理 (Crisis Handler) | ✅ | `src/execution/crisis_handler.py` — 极端行情自动降仓 |
| 8 | 行业暴露控制 | ✅ | `src/portfolio/industry_exposure.py` — 单行业上限 25% |
| 9 | 相关性聚类 | ✅ | `src/portfolio/correlation_cluster.py` — 高相关标的合并控制 |

### 2.2 退出管理

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 硬止损 (-6%) | ✅ | `src/portfolio/exit_manager.py` |
| 2 | 逻辑止损 (score < -0.20) | ✅ | 评分跌破阈值触发逻辑止损 |
| 3 | 利润回撤止盈 | ✅ | 6% 回撤后触发，1% 回撤退出 |
| 4 | 最大持仓天数限制 | ✅ | 普通标的上限 20 天，基本面上限 40 天 |
| 5 | BTST 快速确认机制 | ✅ | 4% 快速确认 + 1% 收盘确认 |
| 6 | 五层退出管理 | ✅ | 硬止损 / 逻辑止损 / 回撤止盈 / 时间止损 / 快速确认 |

### 2.3 仓位计算

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 质量执行乘数 | ✅ | `src/portfolio/position_calculator.py` — quality_score 越高仓位越大 |
| 2 | 单一标的仓位上限 | ✅ | 默认 10%，扩展 12%，低流动性 8% |
| 3 | Beta 调整 | ✅ | 组合 Beta 对标基准动态调整 |
| 4 | A 股最小交易单位 (100 股) | ✅ | 自动按 100 股取整 |

---

## §3. 回测与验证

详细章节: [backtesting.md](./backtesting.md)

### 3.1 回测引擎

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 连续回测引擎 | ✅ | `src/backtesting/engine.py` — 跨时间段的连续模拟 |
| 2 | 检查点保存/恢复 | ✅ | 断点续跑能力 |
| 3 | 待处理订单处理 | ✅ | 涨停排队模拟 |
| 4 | 基准对比 | ✅ | `src/backtesting/benchmarks.py` — 沪深 300 等基准对比 |
| 5 | Agent 模式回测 | ✅ | `src/backtesting/engine_agent_mode.py` — LLM Agent 参与的回测 |
| 6 | Walk-Forward 验证 | ✅ | `src/backtesting/walk_forward.py` — 滚动窗口前瞻验证 |
| 7 | 参数网格搜索 | ✅ | `src/backtesting/param_grid.py` |
| 8 | 策略变体对比 | ✅ | `src/backtesting/rule_variant_compare.py` |
| 9 | Profile 稳定性评估 | ✅ | 连续窗口非推广占比检测 |
| 10 | Promotion Gate | ✅ | `src/backtesting/promotion_gate.py` — 上线门槛控制 |

### 3.2 性能指标

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | Sharpe/Sortino 比率 | ✅ | `src/backtesting/metrics.py` |
| 2 | 最大回撤 | ✅ | 组合和单标的级别 |
| 3 | 胜率/盈亏比 | ✅ | 全面的交易统计 |
| 4 | 日度收益分析 | ✅ | 日频回报率计算 |

---

## §4. 模拟交易 (Paper Trading)

详细章节: [paper-trading.md](./paper-trading.md)

### 4.1 运行时系统

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 日度自动运行 | ✅ | `src/paper_trading/runtime.py` — 完整的日度运行框架 |
| 2 | JSONL 记录器 | ✅ | 所有决策和结果持久化 |
| 3 | 优化 Profile 解析 | ✅ | `src/paper_trading/optimized_profile_resolution.py` |
| 4 | 冻结回放 | ✅ | `src/paper_trading/frozen_replay.py` — 历史执行计划回放 |
| 5 | LLM 可观测性 | ✅ | 模型调用链路追踪和性能统计 |

### 4.2 报告系统

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 日度交易简报 | ✅ | `src/paper_trading/_btst_reporting/` — 完整的日报系统 |
| 2 | 盘前执行卡 | ✅ | `btst_premarket_markdown_helpers.py` |
| 3 | 开盘观察卡 | ✅ | `btst_opening_watch_markdown_helpers.py` |
| 4 | 优先级看板 | ✅ | `btst_priority_board_markdown_helpers.py` |
| 5 | 催化剂主题报告 | ✅ | `catalyst_render_helpers.py` |
| 6 | Shadow 影子池报告 | ✅ | `btst_trade_brief_shadow_markdown_helpers.py` |
| 7 | 收益复盘 (Payoff Review) | ✅ | `payoff_review_lane.py` |
| 8 | 历史先验报告 | ✅ | `historical_prior.py` |

---

## §5. Web 应用 (前端 + 后端)

详细章节: [web-app.md](./web-app.md)

### 5.1 后端 API

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 对冲基金运行 (SSE 流式) | ✅ | `POST /api/hedge-fund/run` — 实时 SSE 推送 |
| 2 | 回测运行 (SSE 流式) | ✅ | `POST /api/hedge-fund/backtest` |
| 3 | 健康检查 | ✅ | `GET /api/health` |
| 4 | 缓存管理 | ✅ | `app/backend/routes/cache.py` |
| 5 | 数据源管理 | ✅ | `app/backend/routes/data_sources.py` |
| 6 | Flow 工作流管理 | ✅ | `app/backend/routes/flows.py` — 工作流 CRUD |
| 7 | Flow 运行管理 | ✅ | `app/backend/routes/flow_runs.py` |
| 8 | Ollama 本地模型管理 | ✅ | `app/backend/routes/ollama.py` |
| 9 | LLM 模型列表 | ✅ | `app/backend/routes/language_models.py` |
| 10 | API Key 管理 | ✅ | `app/backend/routes/api_keys.py` |
| 11 | LLM 调用指标 | ✅ | `app/backend/routes/llm_metrics.py` — 调用统计和性能分析 |
| 12 | 回放制品管理 | ✅ | `app/backend/routes/replay_artifacts.py` |
| 13 | 研究回溯审计 | ✅ | `GET /api/research/lookback-audit` |
| 14 | 组合归因分析 | ✅ | `GET /api/portfolio/attribution` — Brinson 归因 |
| 15 | 组合调整模拟器 | ✅ | `POST /api/portfolio/simulate-adjustment` |
| 16 | 管理员审计 | ✅ | `app/backend/routes/admin_audit.py` |
| 17 | 用户认证 (JWT) | ✅ | `app/backend/routes/auth.py` + invite 系统 |

### 5.2 前端界面

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | ReactFlow 工作流编辑器 | ✅ | 可视化编排 Agent 节点 |
| 2 | 登录/注册/密码重置 | ✅ | 完整的用户认证流程 |
| 3 | 管理员面板 | ✅ | `AdminPage.tsx` — 用户/invite 管理 |
| 4 | 归因分析面板 | ✅ | `AttributionPage.tsx` — Brinson 归因可视化 |
| 5 | 风险监控面板 | ✅ | `risk-monitor-panel.tsx` |
| 6 | Lookback 审计面板 | ✅ | `lookback-audit-panel.tsx` — 历史选股效果回溯 |
| 7 | 期望值卡片 | ✅ | `expectation-card.tsx` |
| 8 | Edge Card 边缘卡片 | ✅ | `edge-card.tsx` |
| 9 | 缓存状态指示器 | ✅ | `cache-status-indicator.tsx` |
| 10 | 组合调整模拟器 | ✅ | `adjustment-simulator.tsx` |
| 11 | 设置面板 | ✅ | `settings/` 目录 |

---

## §6. 数据基础设施

详细章节: [data-infrastructure.md](./data-infrastructure.md)

### 6.1 数据源

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | Tushare 数据源 (A 股) | ✅ | `src/tools/tushare_api.py` — 日线/分钟线/财务/龙虎榜/北向资金 |
| 2 | AKShare 数据源 (A 股) | ✅ | `src/tools/akshare_api.py` — 行情/分钟/资金流/龙虎榜 |
| 3 | Financial Datasets (美股) | ✅ | `src/tools/api.py` — 美股数据源 |
| 4 | 数据路由器 | ✅ | `src/data/router.py` — 自动识别 A 股/美股路由到对应数据源 |
| 5 | Tushare 批量获取 | ✅ | `src/tools/tushare_batch_fetch_helpers.py` |
| 6 | 申万行业分类 | ✅ | `src/tools/tushare_sw_industry_helpers.py` |

### 6.2 缓存系统

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | SQLite 磁盘缓存 | ✅ | `src/data/enhanced_cache.py` — 持久化缓存 |
| 2 | LRU 内存缓存 | ✅ | 热点数据内存缓存 |
| 3 | 缓存基准测试 | ✅ | `src/data/cache_benchmark.py` — 缓存命中率分析 |
| 4 | 缓存管理 CLI | ✅ | `scripts/manage_data_cache.py` — 查看/清理缓存 |
| 5 | 可配置缓存路径 | ✅ | `DISK_CACHE_PATH` 环境变量 |

### 6.3 数据质量

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 数据验证器 (V2) | ✅ | `src/data/validator_v2.py` — 增强验证框架 |
| 2 | 验证规则集 | ✅ | `src/data/validation_rules.py` |
| 3 | 数据清洗 | ✅ | `src/data/cleaner.py` |
| 4 | 健康检查 | ✅ | `src/data/health_checker.py` |
| 5 | 质量监控 | ✅ | `src/data/quality_monitor.py` |
| 6 | 数据快照 | ✅ | `src/data/snapshot.py` — Markdown + JSON 双格式快照 |

---

## §7. LLM 系统

详细章节: [llm-system.md](./llm-system.md)

### 7.1 多模型支持

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 16+ LLM 提供商 | ✅ | OpenAI/Anthropic/DeepSeek/Groq/Google/Ollama/Zhipu 等 |
| 2 | 并行 Provider 执行计划 | ✅ | `src/utils/llm.py` — 多 Provider 并行调用 |
| 3 | Provider 路由 | ✅ | `src/utils/llm_provider_routing.py` |
| 4 | 双 Provider 模式 | ✅ | 主/备 Provider 配置 |
| 5 | Ollama 本地模型支持 | ✅ | `src/utils/ollama.py` — 自动下载模型 |
| 6 | 模型目录管理 | ✅ | `src/llm/model_catalog_helpers.py` |

### 7.2 调用框架

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 统一 LLM 调用接口 | ✅ | `src/utils/llm.py: call_llm()` — 唯一 LLM 入口 |
| 2 | JSON 输出助手 | ✅ | `src/utils/llm_json_helpers.py` |
| 3 | LLM 调用指标收集 | ✅ | `src/monitoring/llm_metrics.py` — 完整的调用统计 |
| 4 | 指标摘要脚本 | ✅ | `scripts/summarize_llm_metrics.py` |
| 5 | 模型选择工具 | ✅ | `scripts/model_selection.py` |
| 6 | 模型列表工具 | ✅ | `scripts/list-models.py` |

---

## §8. Agent 系统

详细章节: [agents.md](./agents.md)

### 8.1 投资者 Agent (12 个)

| # | Agent | 状态 | 投资风格 |
|---|-------|------|----------|
| 1 | Warren Buffett | ✅ | 价值投资 + 长期持有 |
| 2 | Charlie Munger | ✅ | 质量企业 + 理性决策 |
| 3 | Ben Graham | ✅ | 安全边际 + 系统性价值分析 |
| 4 | Peter Lynch | ✅ | 买你了解的 + 10 倍股 |
| 5 | Phil Fisher | ✅ | Scuttlebutt 调研 + 长期成长 |
| 6 | Bill Ackman | ✅ | 激进投资 + 逆向操作 |
| 7 | Cathie Wood | ✅ | 颠覆性创新 + 成长投资 |
| 8 | Michael Burry | ✅ | 深度基本面 + 逆向做空 |
| 9 | Mohnish Pabrai | ✅ | Dhandho 价值投资 |
| 10 | Rakesh Jhunjhunwala | ✅ | 新兴市场 + 高成长行业 |
| 11 | Stanley Druckenmiller | ✅ | 宏观趋势 + 自上而下 |
| 12 | Aswath Damodaran | ✅ | 估值大师 + 内在价值 |

### 8.2 分析师 Agent (6 个)

| # | Agent | 状态 | 职责 |
|---|-------|------|------|
| 1 | Technical Analyst | ✅ | 技术指标 + 价格行为 |
| 2 | Fundamentals Analyst | ✅ | 财务报表 + 经济指标 |
| 3 | Growth Analyst | ✅ | 成长趋势 + 估值 |
| 4 | News Sentiment Analyst | ✅ | 新闻情绪分析 |
| 5 | Sentiment Analyst | ✅ | 市场情绪 + 行为分析 |
| 6 | Valuation Analyst | ✅ | 公司估值 + 模型分析 |

### 8.3 管理 Agent

| # | Agent | 状态 | 职责 |
|---|-------|------|------|
| 1 | Risk Manager | ✅ | 信号聚合 + 仓位限制 |
| 2 | Portfolio Manager | ✅ | 最终交易决策 + 订单生成 |

### 8.4 Agent 编排

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | LangGraph StateGraph | ✅ | `src/graph/state.py` — 图式工作流编排 |
| 2 | 并行波次执行 | ✅ | 按 Provider 分组并行调用 |
| 3 | 可选 Analyst 子集 | ✅ | `--analysts` 参数选择指定 Agent |
| 4 | 并发限制控制 | ✅ | `ANALYST_CONCURRENCY_LIMIT` 环境变量 |

---

## §9. CLI 工具

详细章节: [cli-reference.md](./cli-reference.md) 和 [cli-tools.md](./cli-tools.md)

### 9.1 主要运行模式

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 单票分析模式 | ✅ | `--ticker AAPL` |
| 2 | 多票分析模式 | ✅ | `--ticker AAPL,MSFT,NVDA` |
| 3 | A 股模式 | ✅ | `--ticker 000001,000880` |
| 4 | 全市场自动筛选 | ✅ | `--auto` — Layer A → B → C 全流程 |
| 5 | 解释推荐原因 | ✅ | `--explain 000001` — 读取报告解释推荐逻辑 |
| 6 | 每日涨幅筛选 | ✅ | `--daily-gainers` |
| 7 | 流水线模式 | ✅ | `--pipeline` — 完整日度执行流水线 |
| 8 | 仅筛选模式 | ✅ | `--screen-only` — 只跑 Layer A + Layer B |
| 9 | 模型配置查看 | ✅ | `--show-default-model` |

---

## 维护说明

- **本表为快照**：反映 R20.7 之后(2026-06-08)的实现状态。后续轮次如有新增功能,应同时更新本表与对应子文档。
- **拆分子文档的原因**: 完整功能矩阵超 50KB, 难以快速浏览; 拆分为 9 个子文档后, 用户可按需深入。
- **本表来源**: 主文档 `feature-proposals.md` §1-§9 完整保留内容 + 引用子文档, 无信息丢失。

---

**最后更新**: 2026-06-09 (R20.10 文档拆分)
