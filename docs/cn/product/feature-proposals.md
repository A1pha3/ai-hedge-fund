# 产品功能提案清单

> **目标**: 让用户更高效地找到未来 30 天内最有投资价值的 A 股标的。
>
> **优先级定义**:
> - **P0** — 必须做，直接影响核心使用体验和选股准确性
> - **P1** — 应该做，显著提升效率和易用性
> - **P2** — 可以做，锦上添花
>
> **状态标记**: ✅ 已实现 | 🔄 优化中 | ❌ 未实现

---

## 一、核心筛选流水线

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

## 二、执行系统

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

## 三、回测与验证

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

## 四、模拟交易 (Paper Trading)

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

## 五、Web 应用 (前端 + 后端)

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

## 六、数据基础设施

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

## 七、LLM 系统

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

## 八、Agent 系统

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

## 九、CLI 工具

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

## 十、待优化功能 (已有功能的改进)

### P0 — 必须做

| # | 功能 | 现状 | 改进方案 | 用户价值 |
|---|------|------|----------|----------|
| P0-1 | **全市场筛选速度** ✅ | `--auto` 模式对 ~5000 只股票逐个评分，耗时较长 | 批量化 API 调用 (tushare/akshare 已有 batch 接口)，减少串行网络请求 | 用户等待时间从分钟级降到秒级 |
| P0-2 | **推荐结果可解释性** ✅ | `--explain` 展示策略分数和方向 | 增加 Top 3 因子贡献度明细 + 近 5 日关键事件时间线 + 同行业排名百分位 | 用户理解为什么推荐，建立信任 |
| P0-3 | **信号衰减提醒** | `src/execution/signal_decay.py` 已实现衰减逻辑 | 当推荐标的在 T+2/T+3 信号明显衰减时，在报告中增加衰减预警标记 | 避免用户在信号过弱时买入 |
| P0-4 | **回测结果可视化** | 回测结果仅输出 JSON/Markdown | 在 Web 前端增加回测净值曲线 + 回撤曲线 + 月度收益热力图 | 用户直观判断策略优劣 |
| P0-5 | **智能自选池 (Watchlist)** | 用户标记感兴趣的股票，系统每天自动更新这些标的的评分和信号，无需每次手动输入 ticker | 用户追踪自己的关注标的，系统自动推送变化 |
| P0-6 | **多日推荐聚合** | ✅ | `--auto` 每日独立运行，推荐结果不连续。增加「近 3 日连续推荐」标记 — 连续 3 天被推荐的标的更可靠 | 减少单日噪声，提高推荐稳定性 |

### P1 — 应该做

| # | 功能 | 现状 | 改进方案 | 用户价值 |
|---|------|------|----------|----------|
| P1-1 | **缓存命中率优化** | SQLite 缓存已实现但过期策略简单 | 增加「主动预热」模式：在盘后自动预拉取常用数据；增加按因子依赖的批量预加载 | 减少 `--auto` 运行时的冷启动延迟 |
| P1-2 | **行业轮动信号** | 行业暴露控制已有 (`industry_exposure.py`)，但仅限风控 | 增加行业动量/轮动评分，输出「本周强势行业 Top 5」，在推荐结果中标注行业标签 | 用户从行业视角筛选，减少信息噪音 |
| P1-3 | **推荐标的持续性追踪** | Lookback Audit 已有 (`lookback_audit.py`)，但需要手动触发 | 增加「自动追踪」：每次 `--auto` 运行后自动记录 Top 10 标的，次日盘后自动计算实际收益 | 无需手动对比，系统自动闭环验证 |
| P1-4 | **因子重要性排行** | 四策略各有子因子，但缺少全局排序 | 定期计算因子 IC (信息系数)，输出「本周最强因子 Top 10」，用于辅助用户理解市场风格 | 用户了解当前市场驱动因素 |
| P1-5 | **Web 端筛选一键执行** | 后端有 `/hedge-fund/run` 但无专门的筛选端点 | 新增 `POST /api/screening/auto` 端点，前端增加「一键选股」按钮 | Web 用户无需 CLI 即可使用核心功能 |
| P1-6 | **组合风险预警仪表盘** | `risk-monitor-panel.tsx` 已有基础展示 | 增加实时 VaR / CVaR 计算 + 行业集中度动态图 + 回撤预警线 | 用户对组合风险一目了然 |

### P2 — 可以做

| # | 功能 | 现状 | 改进方案 | 用户价值 |
|---|------|------|----------|----------|
| P2-1 | **Agent 推理过程可视化** | Agent 信号以 JSON 传递，前端无推理链展示 | 在 Web 端增加每个 Agent 的推理摘要卡片，点击可展开详细推理过程 | 理解每个 Agent 的决策依据 |
| P2-2 | **回测参数对比面板** | `param_grid.py` 支持参数搜索但无前端展示 | 增加参数对比表格 + 收益散点图 + Pareto 前沿图 | 对比不同参数组合的效果 |
| P2-3 | **邮件/Webhook 推送** | 所有报告仅本地存储 | 增加可选的每日选股结果推送 (邮件/企微/钉钉 Webhook) | 用户无需登录即可获取每日推荐 |
| P2-4 | **历史推荐胜率看板** | 历史数据已有 (`lookback_audit.py`) | 增加「近 30 天推荐胜率趋势图 + 平均收益率曲线」到前端 | 持续评估系统表现 |

---

## 十一、新功能提案

### P0 — 必须做

| # | 功能 | 说明 | 用户价值 |
|---|------|------|----------|
| P0-5 | **智能自选池 (Watchlist)** | 用户标记感兴趣的股票，系统每天自动更新这些标的的评分和信号，无需每次手动输入 ticker | 用户追踪自己的关注标的，系统自动推送变化 |
| P0-6 | **多日推荐聚合** ✅ | `--auto` 每日独立运行，推荐结果不连续。增加「近 3 日连续推荐」标记 — 连续 3 天被推荐的标的更可靠 | 减少单日噪声，提高推荐稳定性 |

### P1 — 应该做

| # | 功能 | 说明 | 用户价值 |
|---|------|------|----------|
| P1-7 | **选股报告 PDF 导出** | 每次筛选结果生成结构化 PDF 报告（含图表），可直接分享 | 专业用户需要可归档的报告格式 |
| P1-8 | **标的对比工具** | 输入 2-5 只股票，输出多维度雷达图对比（趋势/估值/动量/资金流/行业排名） | 用户在候选股之间做最终选择 |
| P1-9 | **市场温度计** | 在首页展示实时市场状态仪表盘：ADK 趋势强度、涨跌比、北向资金方向、涨停/跌停数、行业领涨 Top 3 | 用户一眼判断当日市场环境 |
| P1-10 | **条件单建议** | 基于回测历史统计各标的的最佳买入区间，输出「建议在 X 元附近关注」的条件单建议 | 用户获得具体操作价位参考 |
| P1-11 | **策略归因日报** | 每日收盘后自动生成「今日策略表现归因」：哪个策略贡献最大、哪个策略失效、原因分析 | 用户持续了解策略风格匹配度 |
| P1-12 | **组合再平衡建议** | 基于当前持仓和市场状态，输出「建议加仓/减仓/调仓」的具体操作列表 | 用户获得可执行的调仓建议 |

### P2 — 可以做

| # | 功能 | 说明 | 用户价值 |
|---|------|------|----------|
| P2-5 | **自定义策略权重** | 用户在 Web 端通过滑块调整四个策略的权重（趋势/均值回归/基本面/事件情绪），实时看到推荐变化 | 高级用户自定义选股偏好 |
| P2-6 | **标的分析详情页** | 输入单只股票，输出完整的分析报告：基本面+技术面+资金流+新闻+同行业对比+历史推荐记录 | 用户深度研究单个标的 |
| P2-7 | **回测场景回放** | 在 Web 端可视化回放历史某段时间的选股过程，逐日展示筛选结果和实际走势 | 理解系统在不同市场环境下的行为 |
| P2-8 | **组合绩效周报/月报** | 自动生成周/月度绩效报告：收益率、胜率、最大回撤、归因分析、与基准对比 | 定期评估投资系统整体表现 |
| P2-9 | **宏观数据集成** | 集成 CPI、PMI、社融、利率等宏观数据，作为市场状态判断的补充维度 | 更全面的市场环境判断 |

---

### P0-2 实现细节

**增强 `--explain` 推荐可解释性**：在原有策略贡献区块后新增三个信息区块。

**实现组件**:

- **修改文件**: `src/main.py` (run_explain 函数 + 4 个新辅助函数)
  - `_build_factor_bar(confidence)`: 10 格 ASCII 柱状图（0-100 线性映射）
  - `_print_factor_detail_block(rec)`: Block A — 因子贡献度明细，按策略分组展示 Top 3 子因子（按 |confidence| 降序）
  - `_print_recent_events_block(data, rec)`: Block B — 近 5 日关键事件时间线，优先从 report-level `recent_events`，次选从 `event_sentiment.sub_factors` 提取，无数据时展示"暂无"
  - `_print_industry_ranking_block(recs, rec)`: Block C — 同行业排名百分位，基于报告 Top N 推荐列表中同 `industry_sw` 的标的排名

- **输出格式**:
  ```
  因子明细:
    趋势策略:
      momentum_20d     ↑ 0.72  ████████░░
      supply_pressure  ↓ 0.45  █████░░░░░
    事件情绪:
      news_sentiment   ↑ 0.81  █████████░
  近期事件 (5 日):
    06-05  龙虎榜净买入 ¥2.3亿
    ...
  同行业排名: 电子 — 第 3/5 名 (前 60%)
  ```

- **向后兼容**: 旧版报告（无 `sub_factors`、无 `recent_events`、无 `industry_sw`）均能正常运行，显示"暂无"

- **测试覆盖**: `tests/test_explain.py` (14 个测试用例)
  - 因子明细: Top 3 排序、missing sub_factors 降级
  - 近期事件: 从 report / sub_factors 提取、无数据降级
  - 同行业排名: 排名计算、无行业信息降级
  - 辅助函数: bar chart 边界（0/50/100/clamp）、文章提取
  - Ticker 未找到: 已有逻辑验证

- **回归验证**: 14/14 通过 + 162 已有测试无回归

---

### P0-6 实现细节

**实现组件**:

- **新模块**: `src/screening/consecutive_recommendation.py`
  - `RecommendationStatus` 枚举: `first_appearance` / `consecutive_2days` / `consecutive_3plus` / `broken_streak`
  - `ConsecutiveStats` dataclass: `ticker` / `consecutive_days` / `status` / `recommendation_history` / `stability_bonus`
  - `compute_consecutive_recommendations(lookback_days, report_dir, end_date)`: 读取 `data/reports/auto_screening_*.json` 计算每个 ticker 的连续推荐统计
  - `enrich_recommendations_with_history(...)`: 给推荐结果附加 `consecutive_days` / `recommendation_history` / `stability_bonus` 三个字段
  - `resolve_report_dir()`: 跨 cwd 与项目根目录自动定位 `data/reports`

- **稳定性加权曲线** (0-10 分):
  - streak=1 → 0.0 分 (首次出现)
  - streak=2 → 3.0 分 (中等置信)
  - streak≥3 → 10.0 分 (高置信，上限)
  - 断点重启 (历史出现过但中间断档) → 0.0 分，状态标 `broken_streak`

- **集成点**: `src/main.py` 的 `run_auto_screening()`
  - 排序输出 Top N 后调用 `enrich_recommendations_with_history` 附加连续推荐元数据
  - 报告 payload (`data/reports/auto_screening_{YYYYMMDD}.json`) 中 `recommendations` 每条新增三个字段，并在顶层新增 `consecutive_recommendation.{lookback_days, high_streak_count}` 摘要
  - CLI 输出表格新增 **Consecutive** 列：
    - 连续 ≥3 天: 绿色加粗 (`3d`)
    - 连续 2 天: 黄色 (`2d`)
    - 连续 1 天: 白色 (`1d`)
    - 无历史: 红色 (`—`)
    - 连续 3+ 天的 ticker 整行 ticker 名称也以绿色加粗高亮

- **测试覆盖**: `tests/test_consecutive_recommendation.py` (15 个测试用例)
  - 空历史 / 单日历史 / 连续 2 天 / 连续 3 天 / 连续 4+ 天
  - 中间断档 / lookback 窗口外排除 / lookback=5 配置变更
  - 损坏 JSON 优雅降级 / 未知 ticker 默认 0 bonus
  - `load_auto_screening_history` 排序与降级
  - `resolve_report_dir` cwd 切换
  - `ConsecutiveStats` 数据结构 / `RecommendationStatus` 枚举值

- **配置项**: `DEFAULT_LOOKBACK_DAYS = 3` (模块顶部常量，可被 `enrich_recommendations_with_history(lookback_days=...)` 覆盖)

- **存储**: 复用现有 `data/reports/auto_screening_{YYYYMMDD}.json` JSON 报告，无需新建存储层

- **回归验证**: `tests/test_consecutive_recommendation.py` (15/15 通过) + `tests/screening/` (161/161 通过) + `tests/execution/` (169/169 通过) 均无回归

---

### P0-1 实现细节

**目标**: 将 `--auto` 模式对 ~5000 只 A 股的逐 ticker 串行评分从「分钟级」压缩到「秒级」，通过批量化 API 调用 + 短期内存缓存 + 并发 fallback 减少网络往返。

**实现组件**:

- **新模块**: `src/screening/batch_data_fetcher.py`
  - `BatchDataCache`: 短期内存缓存 (默认 TTL 60s)；支持 `get/set/clear/stats`；命中/未命中计数
  - `BatchDataFetcher`:
    - `fetch_daily_prices_batch(trade_date)` — 包装 `tushare get_daily_price_batch(trade_date)` 一次取全市场
    - `fetch_daily_basic_batch(trade_date)` — 包装 `tushare get_daily_basic_batch(trade_date)` 一次取全市场
    - `fetch_prices_for_tickers(tickers, start_date, end_date)` — 异步并发 (`asyncio.Semaphore(N)`) 拉取多 ticker 价格
    - `stats()` — 返回 `batch_calls / batch_failures / single_ticker_calls / cache_hits` 调用统计
  - `is_batch_fetcher_enabled()` — 读取 `USE_BATCH_FETCHER` 环境变量 (默认开启，`false`/`0`/`no`/`off` 关闭)
  - `get_global_batch_data_fetcher()` — 全局 lazy 单例；`reset_global_batch_data_fetcher()` 用于测试

- **降级策略**:
  - 批量接口抛异常 → `BatchDataFetcher` 捕获后返回 `None`，调用方决定是否回退
  - 批量返回空 DataFrame → 同样视为失败，记录 `batch_failures`
  - 不静默重试：失败清晰可见，便于上游决策

- **集成点**: `src/main.py` 的 `run_auto_screening()`
  - 入口创建 `batch_fetcher = get_global_batch_data_fetcher()` 并记录 `use_batch` / `max_concurrency`
  - 报告 payload (`data/reports/auto_screening_{YYYYMMDD}.json`) 顶层新增 `batch_data_fetcher.{use_batch, batch_calls, batch_failures, single_ticker_calls, cache_hits, cache_size}` 字段
  - 运行结束 logger.info 输出 batch fetcher 统计

- **环境变量**:
  - `USE_BATCH_FETCHER` — kill switch (默认 `true`；`false`/`0`/`no`/`off` 关闭)
  - `BATCH_FETCHER_CONCURRENCY` (可选) — 单 ticker fallback 并发度 (默认 8)

- **测试覆盖**: `tests/test_batch_data_fetcher.py` (19 个测试用例) + `tests/screening/test_screening_performance.py` (4 个性能对比用例)
  - 单元: `BatchDataCache` TTL 过期、key 命中、clear、stats
  - 单元: 批量接口数据格式校验、批量失败降级、缓存命中
  - 单元: `USE_BATCH_FETCHER=false` 走单 ticker；env var 默认开启/0/false/true
  - 并发: semaphore 限制生效 (peak <= max_concurrency)
  - 性能: 批量模式调用次数 << 串行模式 (5000 ticker: 1 call vs 5000 calls)；wallclock 至少 5x 加速

- **回归验证**: `tests/test_batch_data_fetcher.py` (19/19) + `tests/screening/test_screening_performance.py` (4/4) + `tests/screening/` (165/165) + `tests/research|execution|portfolio|backtesting|targets` (1037/1037) 均无回归

- **向后兼容**: 原 `get_prices` / `get_financial_metrics` / `get_daily_basic_batch` / `get_daily_price_batch` 单 ticker 或批量接口保留原样；`BatchDataFetcher` 仅作为「优先路径」，失败静默降级

---

## 十二、优先级路线图

### Phase 1: 核心体验 (1-2 周)

1. **P0-1** 全市场筛选速度优化 — 批量化 API 调用 ✅ *(已实现 — 见下文 P0-1 实现细节)*
2. **P0-5** 智能自选池 — 用户标记 + 自动更新
3. **P0-2** 推荐结果可解释性增强 — 因子明细 + 事件线 ✅ *(已实现 — 见下文 P0-2 实现细节)*
4. **P0-6** 多日推荐聚合 — 连续推荐标记 ✅ *(已实现 — 见上文 P0-6 实现细节)*

### Phase 2: 效率提升 (2-4 周)

5. **P1-5** Web 端一键选股 — `POST /api/screening/auto`
6. **P1-9** 市场温度计 — 首页实时状态
7. **P1-2** 行业轮动信号 — 强势行业标签
8. **P1-3** 推荐标的自动追踪 — 闭环验证
9. **P1-6** 组合风险预警仪表盘增强

### Phase 3: 深度分析 (4-6 周)

10. **P0-4** 回测结果可视化 — 净值曲线 + 回撤图
11. **P1-8** 标的对比工具 — 多维雷达图
12. **P1-4** 因子重要性排行 — IC 分析
13. **P1-10** 条件单建议 — 买入区间参考
14. **P1-11** 策略归因日报
15. **P1-12** 组合再平衡建议

### Phase 4: 高级功能 (6+ 周)

16. **P2-5** 自定义策略权重
17. **P2-6** 标的分析详情页
18. **P2-1** Agent 推理过程可视化
19. **P2-7** 回测场景回放
20. **P2-8** 组合绩效周报/月报
21. **P2-9** 宏观数据集成
22. **P2-3** 邮件/Webhook 推送

---

## 十三、技术债务与优化

### 性能

| # | 项目 | 现状 | 建议 |
|---|------|------|------|
| 1 | 全市场评分并行度 | `score_batch` 使用 `concurrent.futures` 但受限于 API 限速 | 增加请求合并和批量接口调用 |
| 2 | 缓存粒度 | 按标的+日期缓存 | 增加按因子缓存（同一因子多标的共享数据） |
| 3 | LLM 调用开销 | 17 个 Agent 每个 ticker 都调用 LLM | 增加 Agent 结果缓存（相同因子短期内复用） |

### 可靠性

| # | 项目 | 现状 | 建议 |
|---|------|------|------|
| 1 | 数据源容错 | 已有 `tushare` + `akshare` 双源但非自动切换 | 增加自动 Fallback：主源失败自动切换到备用源 |
| 2 | 网络超时处理 | 各 API 调用有基本超时 | 增加重试策略 (exponential backoff) + 断路器模式 |

### 代码质量

| # | 项目 | 现状 | 建议 |
|---|------|------|------|
| 1 | 模块拆分 | 部分文件过大 (`daily_pipeline.py`, `strategy_scorer.py`) | 继续按职责拆分 helpers (已在进行中) |
| 2 | 类型标注 | 已有 PEP 484 类型标注 | 补充 `validators` 中部分 Any 类型的精确标注 |

---

## 十四、不做的功能 (避免重复)

以下功能在现有系统中已有对应实现，不需要重复添加：

| 功能 | 已有实现 | 说明 |
|------|----------|------|
| 独立的选股排行榜 | `--auto --top-n N` 已输出排名 | 不需要单独的排行榜页面 |
| 独立的市场分析工具 | `market_state.py` 已集成到流水线 | 不需要独立模块 |
| 独立的止损计算器 | `exit_manager.py` 五层退出系统 | 不需要额外的止损工具 |
| 独立的仓位计算器 | `position_calculator.py` 已实现 | 不需要额外模块 |
| 独立的行业分析 | `industry_exposure.py` + 申万分类 | 已集成到流水线 |
| 独立的资金流分析 | `akshare_api.py: get_money_flow()` | 已集成到事件情绪策略 |

---

> **文档维护说明**: 本文档应在每次功能迭代后更新。已完成功能标记 ✅，新增功能按优先级添加到对应章节。
>
> **最后更新**: 2026-06-07 (Round 7: P0-2 可解释性增强)
