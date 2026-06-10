# 10-11. 待优化功能 & 新功能提案

> 本节对应主文档 §10-11,包含 P0/P1/P2 优先级功能优化与新功能提案,以及关键功能的实现细节。

## 10. 待优化功能 (已有功能的改进)

### P0 — 必须做

| # | 功能 | 现状 | 改进方案 | 用户价值 |
|---|------|------|----------|----------|
| P0-1 | **全市场筛选速度** ✅ | `--auto` 模式对 ~5000 只股票逐个评分,耗时较长 | 批量化 API 调用 (tushare/akshare 已有 batch 接口),减少串行网络请求 | 用户等待时间从分钟级降到秒级 |
| P0-2 | **推荐结果可解释性** ✅ | `--explain` 展示策略分数和方向 | 增加 Top 3 因子贡献度明细 + 近 5 日关键事件时间线 + 同行业排名百分位 | 用户理解为什么推荐,建立信任 |
| P0-3 | **信号衰减提醒** ✅ | `src/execution/signal_decay.py` 已实现衰减逻辑 | 当推荐标的在 T+2/T+3 信号明显衰减时,在报告中增加衰减预警标记 | 避免用户在信号过弱时买入 |
| P0-4 | **回测结果可视化** ✅ | Web 前端已实现: `backtest-equity-curve.tsx` 渲染净值曲线 + 水下图(回撤) + 月度收益热力图 + 6 KPI 卡片 (R20.29 补 15 测试 + 修 TDZ 前置声明) | — | 用户直观判断策略优劣 |
| P0-5 | **智能自选池 (Watchlist)** ✅ | 用户标记感兴趣的股票,系统每天自动更新这些标的的评分和信号,无需每次手动输入 ticker | 用户追踪自己的关注标的,系统自动推送变化 |
| P0-6 | **多日推荐聚合** | ✅ | `--auto` 每日独立运行,推荐结果不连续。增加「近 3 日连续推荐」标记 — 连续 3 天被推荐的标的更可靠 | 减少单日噪声,提高推荐稳定性 |

### P1 — 应该做

| # | 功能 | 现状 | 改进方案 | 用户价值 |
|---|------|------|----------|----------|
| P1-1 | **缓存命中率优化** ✅ | SQLite 缓存已实现但过期策略简单 | 增加「主动预热」模式:在盘后自动预拉取常用数据(daily_basic / daily_prices / 行业分类 / 北向资金 / 财务指标) — 已实现:`src/data/cache_preheater.py` + `--preheat [--preheat-tasks=...] [--force] [--list-tasks]` CLI + `PREHEAT_BEFORE_AUTO=true` 自动预热 | 减少 `--auto` 运行时的冷启动延迟 |
| P1-2 | **行业轮动信号** ✅ | 行业暴露控制已有 (`industry_exposure.py`),但仅限风控 | 增加行业动量/轮动评分,输出「本周强势行业 Top 5」,在推荐结果中标注行业标签 | 用户从行业视角筛选,减少信息噪音 |
| P1-3 | **推荐标的持续性追踪** ✅ | Lookback Audit 已有 (`lookback_audit.py`),但需要手动触发 | 增加「自动追踪」:每次 `--auto` 运行后自动记录 Top 10 标的,次日盘后自动计算实际收益 | 无需手动对比,系统自动闭环验证 — 已实现:`src/screening/recommendation_tracker.py` + `--tracking-summary` CLI |
| P1-4 | **因子重要性排行** ✅ | 四策略各有子因子,但缺少全局排序 | 定期计算因子 IC (信息系数),输出「本周最强因子 Top 10」,用于辅助用户理解市场风格 — 已实现:`src/research/factor_ic_analysis.py` + `--factor-ic [--ic-lookback=N] [--ic-method=spearman]` CLI | 用户了解当前市场驱动因素 |
| P1-5 | **Web 端筛选一键执行** ✅ | 后端已有 `/hedge-fund/run` | 后端已实现 `POST /api/screening/auto` 端点(`app/backend/routes/screening.py`)+ 结果查询 `GET /api/screening/latest`;前端「一键选股」按钮待集成 | Web 用户无需 CLI 即可使用核心功能 |
| P1-6 | **组合风险预警仪表盘** | ✅ | `risk-monitor-panel.tsx` 已有基础展示 — 已增强: 实时 VaR / CVaR + 行业集中度 + 回撤预警线 | 用户对组合风险一目了然 |

### P2 — 可以做

| # | 功能 | 现状 | 改进方案 | 用户价值 |
|---|------|------|----------|----------|
| P2-1 | **Agent 推理过程可视化** | Agent 信号以 JSON 传递,前端无推理链展示 | 在 Web 端增加每个 Agent 的推理摘要卡片,点击可展开详细推理过程 | 理解每个 Agent 的决策依据 |
| P2-2 | **回测参数对比面板** | `param_grid.py` 支持参数搜索但无前端展示 | 增加参数对比表格 + 收益散点图 + Pareto 前沿图 | 对比不同参数组合的效果 |
| P2-3 | **邮件/Webhook 推送** ✅ | 所有报告仅本地存储 | 增加可选的每日选股结果推送 (邮件/企微/钉钉/通用 Webhook) — 已实现:`src/notification/push.py` + `data/push_config.json.example` + `--push-test` CLI + `--push-test --init` 生成默认模板 + 集成到 `--auto` 流程末尾 (失败容错不影响主流程) | 用户无需登录即可获取每日推荐 |
| P2-4 | **历史推荐胜率看板** ✅ | 历史数据已有 (`lookback_audit.py`) | 增加「近 30 天推荐胜率趋势图 + 平均收益率曲线」到前端 — 已实现:`src/screening/winrate_dashboard.py` + `--winrate-dashboard [--winrate-lookback=30]` CLI + `GET /api/screening/winrate-dashboard?lookback_days=30` Web 端点 | 持续评估系统表现 |

## 11. 新功能提案

### P0 — 必须做

| # | 功能 | 说明 | 用户价值 |
|---|------|------|----------|
| P0-5 | **智能自选池 (Watchlist)** ✅ | 用户标记感兴趣的股票,系统每天自动更新这些标的的评分和信号,无需每次手动输入 ticker — 已实现:`src/screening/watchlist.py` + `--watchlist-add/remove/list/status` CLI | 用户追踪自己的关注标的,系统自动推送变化 |
| P0-6 | **多日推荐聚合** ✅ | `--auto` 每日独立运行,推荐结果不连续。增加「近 3 日连续推荐」标记 — 连续 3 天被推荐的标的更可靠 | 减少单日噪声,提高推荐稳定性 |

### P1 — 应该做

| # | 功能 | 说明 | 用户价值 |
|---|------|------|----------|
| P1-7 | **选股报告 PDF 导出** ✅ | 每次筛选结果生成结构化 PDF 报告(含图表),可直接分享 — 已实现:`src/reporting/pdf_exporter.py` + `src/main.py --export-pdf` + `AUTO_EXPORT_PDF=true` 环境变量 | 专业用户需要可归档的报告格式 |
| P1-8 | **标的对比工具** ✅ | 输入 2-5 只股票,输出多维度雷达图对比(趋势/估值/动量/资金流/行业排名) — 已实现:`src/screening/compare_tool.py` + `--compare` CLI + `GET /api/screening/compare` | 用户在候选股之间做最终选择 |
| P1-9 | **市场温度计** ✅ | 在首页展示实时市场状态仪表盘:ADK 趋势强度、涨跌比、北向资金方向、涨停/跌停数、行业领涨 Top 3 | 用户一眼判断当日市场环境 |
| P1-10 | **条件单建议** ✅ | 基于 ATR 波动率给出每只推荐标的的「建议买入区间 / 止损价 / 止盈价 / 盈亏比 / 历史命中率」 — 已实现:`src/screening/conditional_order_advisor.py` + `--conditional-orders [--top-n=N] [--atr-period=14] [--co-lookback=60]` CLI + `GET /api/screening/conditional-orders` Web 端点 + `--auto` 报告顶层 `conditional_orders` 字段 | 用户获得具体操作价位参考,可直接挂条件单 |
| P1-11 | **策略归因日报** ✅ | 每日收盘后自动生成「今日策略表现归因」:哪个策略贡献最大、哪个策略失效、原因分析 | 用户持续了解策略风格匹配度 |
| P1-12 | **组合再平衡建议** ✅ | 基于当前持仓和市场状态,输出「建议加仓/减仓/调仓」的具体操作列表 — 已实现:`src/portfolio/rebalance_advisor.py` + `src/main.py --rebalance` + `GET/POST /api/portfolio/rebalance` + `--auto` 自动附加到报告顶层 `rebalance_actions` | 用户获得可执行的调仓建议 |

### P2 — 可以做

| # | 功能 | 说明 | 用户价值 |
|---|------|------|----------|
| P2-5 | **自定义策略权重** | 用户在 Web 端通过滑块调整四个策略的权重(趋势/均值回归/基本面/事件情绪),实时看到推荐变化 — 已实现:`src/screening/custom_weights.py` + `src/main.py --custom-weights` + `POST /api/screening/custom-weights`;前端待加滑块面板(建议 0.25/0.25/0.25/0.25 默认 + 重置按钮 + 实时重算) | 高级用户自定义选股偏好 |
| P2-6 | **标的分析详情页** | 输入单只股票,输出完整的分析报告:基本面+技术面+资金流+新闻+同行业对比+历史推荐记录 | 用户深度研究单个标的 |
| P2-7 | **回测场景回放** | 在 Web 端可视化回放历史某段时间的选股过程,逐日展示筛选结果和实际走势 | 理解系统在不同市场环境下的行为 |
| P2-8 | **组合绩效周报/月报** ✅ | 自动生成周/月度绩效报告:收益率、胜率、最大回撤、归因分析、与基准对比 — 已实现:`src/portfolio/performance_report.py` + `src/main.py --performance-report` + `GET/POST /api/portfolio/performance-report` | 定期评估投资系统整体表现 |
| P2-9 | **宏观数据集成** | 集成 CPI、PMI、社融、利率等宏观数据,作为市场状态判断的补充维度 | 更全面的市场环境判断 |

---

## 关键实现细节

### P0-2 实现细节 — 推荐可解释性增强

**增强 `--explain` 推荐可解释性**:在原有策略贡献区块后新增三个信息区块。

**实现组件**:

- **修改文件**: `src/main.py` (run_explain 函数 + 4 个新辅助函数)
  - `_build_factor_bar(confidence)`: 10 格 ASCII 柱状图(0-100 线性映射)
  - `_print_factor_detail_block(rec)`: Block A — 因子贡献度明细,按策略分组展示 Top 3 子因子(按 |confidence| 降序)
  - `_print_recent_events_block(data, rec)`: Block B — 近 5 日关键事件时间线,优先从 report-level `recent_events`,次选从 `event_sentiment.sub_factors` 提取,无数据时展示"暂无"
  - `_print_industry_ranking_block(recs, rec)`: Block C — 同行业排名百分位,基于报告 Top N 推荐列表中同 `industry_sw` 的标的排名

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

- **向后兼容**: 旧版报告(无 `sub_factors`、无 `recent_events`、无 `industry_sw`)均能正常运行,显示"暂无"

- **测试覆盖**: `tests/test_explain.py` (14 个测试用例)
  - 因子明细: Top 3 排序、missing sub_factors 降级
  - 近期事件: 从 report / sub_factors 提取、无数据降级
  - 同行业排名: 排名计算、无行业信息降级
  - 辅助函数: bar chart 边界(0/50/100/clamp)、文章提取
  - Ticker 未找到: 已有逻辑验证

- **回归验证**: 14/14 通过 + 162 已有测试无回归

---

### P0-6 实现细节 — 多日推荐聚合

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
  - streak≥3 → 10.0 分 (高置信,上限)
  - 断点重启 (历史出现过但中间断档) → 0.0 分,状态标 `broken_streak`

- **集成点**: `src/main.py` 的 `run_auto_screening()`
  - 排序输出 Top N 后调用 `enrich_recommendations_with_history` 附加连续推荐元数据
  - 报告 payload (`data/reports/auto_screening_{YYYYMMDD}.json`) 中 `recommendations` 每条新增三个字段,并在顶层新增 `consecutive_recommendation.{lookback_days, high_streak_count}` 摘要
  - CLI 输出表格新增 **Consecutive** 列:
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

- **配置项**: `DEFAULT_LOOKBACK_DAYS = 3` (模块顶部常量,可被 `enrich_recommendations_with_history(lookback_days=...)` 覆盖)

- **存储**: 复用现有 `data/reports/auto_screening_{YYYYMMDD}.json` JSON 报告,无需新建存储层

- **回归验证**: `tests/test_consecutive_recommendation.py` (15/15 通过) + `tests/screening/` (161/161 通过) + `tests/execution/` (169/169 通过) 均无回归

---

### P0-1 实现细节 — 全市场筛选速度

**目标**: 将 `--auto` 模式对 ~5000 只 A 股的逐 ticker 串行评分从「分钟级」压缩到「秒级」,通过批量化 API 调用 + 短期内存缓存 + 并发 fallback 减少网络往返。

**实现组件**:

- **新模块**: `src/screening/batch_data_fetcher.py`
  - `BatchDataCache`: 短期内存缓存 (默认 TTL 60s);支持 `get/set/clear/stats`;命中/未命中计数
  - `BatchDataFetcher`:
    - `fetch_daily_prices_batch(trade_date)` — 包装 `tushare get_daily_price_batch(trade_date)` 一次取全市场
    - `fetch_daily_basic_batch(trade_date)` — 包装 `tushare get_daily_basic_batch(trade_date)` 一次取全市场
    - `fetch_prices_for_tickers(tickers, start_date, end_date)` — 异步并发 (`asyncio.Semaphore(N)`) 拉取多 ticker 价格
    - `stats()` — 返回 `batch_calls / batch_failures / single_ticker_calls / cache_hits` 调用统计
  - `is_batch_fetcher_enabled()` — 读取 `USE_BATCH_FETCHER` 环境变量 (默认开启,`false`/`0`/`no`/`off` 关闭)
  - `get_global_batch_data_fetcher()` — 全局 lazy 单例;`reset_global_batch_data_fetcher()` 用于测试

- **降级策略**:
  - 批量接口抛异常 → `BatchDataFetcher` 捕获后返回 `None`,调用方决定是否回退
  - 批量返回空 DataFrame → 同样视为失败,记录 `batch_failures`
  - 不静默重试:失败清晰可见,便于上游决策

- **集成点**: `src/main.py` 的 `run_auto_screening()`
  - 入口创建 `batch_fetcher = get_global_batch_data_fetcher()` 并记录 `use_batch` / `max_concurrency`
  - 报告 payload (`data/reports/auto_screening_{YYYYMMDD}.json`) 顶层新增 `batch_data_fetcher.{use_batch, batch_calls, batch_failures, single_ticker_calls, cache_hits, cache_size}` 字段
  - 运行结束 logger.info 输出 batch fetcher 统计

- **环境变量**:
  - `USE_BATCH_FETCHER` — kill switch (默认 `true`;`false`/`0`/`no`/`off` 关闭)
  - `BATCH_FETCHER_CONCURRENCY` (可选) — 单 ticker fallback 并发度 (默认 8)

- **测试覆盖**: `tests/test_batch_data_fetcher.py` (19 个测试用例) + `tests/screening/test_screening_performance.py` (4 个性能对比用例)
  - 单元: `BatchDataCache` TTL 过期、key 命中、clear、stats
  - 单元: 批量接口数据格式校验、批量失败降级、缓存命中
  - 单元: `USE_BATCH_FETCHER=false` 走单 ticker;env var 默认开启/0/false/true
  - 并发: semaphore 限制生效 (peak <= max_concurrency)
  - 性能: 批量模式调用次数 << 串行模式 (5000 ticker: 1 call vs 5000 calls);wallclock 至少 5x 加速

- **回归验证**: `tests/test_batch_data_fetcher.py` (19/19) + `tests/screening/test_screening_performance.py` (4/4) + `tests/screening/` (165/165) + `tests/research|execution|portfolio|backtesting|targets` (1037/1037) 均无回归

- **向后兼容**: 原 `get_prices` / `get_financial_metrics` / `get_daily_basic_batch` / `get_daily_price_batch` 单 ticker 或批量接口保留原样;`BatchDataFetcher` 仅作为「优先路径」,失败静默降级

---

### P1-4 实现细节 — 因子重要性排行

**目标**: 用 **IC (Information Coefficient)** 量化每个子因子对下期收益的预测能力, 输出「本周最强因子 Top 10」, 让研究员了解当前市场驱动因素, 为下次回测 / 调参提供数据支撑。

**IC 标准定义**:
- IC = corr(因子值序列, 下期收益序列), Spearman 秩相关 (推荐) 或 Pearson
- IR (Information Ratio) = mean(IC) / std(IC), 反映 IC 跨期稳健性
- ic_positive_rate = IC > 0 的比例, 反映胜率

**实现组件**:

- **新模块**: `src/research/factor_ic_analysis.py` — 纯函数, 无网络/数据库依赖
  - `FactorICResult` dataclass: `factor_name / strategy / ic_mean / ic_std / ir / ic_positive_rate / n_periods / rank / significance / method`
  - `compute_factor_ic(factor_history, return_history, *, method, rolling_window)`:
    - **单次模式** (默认): 整段时间序列算一个 IC; IR=0
    - **Rolling 模式** (`rolling_window > 1`): 滑动窗口, 收集 IC 序列, 计算 IR + ic_positive_rate
  - `classify_significance(ic_mean, ir)` — high / medium / low / insignificant 四级
  - `extract_factor_panel_from_history(reports_dir, lookback_days, end_date)` — 从 `data/reports/auto_screening_*.json` + `tracking_history.json` 提取因子面板 + 下期收益 (T+1)
  - `render_factor_ic_ranking(results, end_date, lookback_days)` — 中文文本排行表
  - `run_factor_ic(lookback_days, method)` — CLI 入口
  - 内部 helpers: `_pearson_correlation` / `_spearman_correlation` (基于秩, 处理 ties 用平均秩) / `_rank_average` / `_safe_stdev` (过滤 NaN) / `_is_finite`
  - 数值安全: 全部输入经 `_is_finite` 过滤, NaN/Inf/None → 0.0 (避免污染); 单次模式 IR=0 而非 NaN; ties 用平均秩

- **集成点**: `src/main.py` CLI 早期分发 (在 `parse_cli_inputs` 之前)
  - `--factor-ic` 主开关
  - `--ic-lookback=N` 回溯天数 (默认 30)
  - `--ic-method=spearman|pearson` (默认 spearman)
  - 数据来源: `data/reports/auto_screening_*.json` + `data/reports/tracking_history.json` (P1-3 自动追踪)
  - 阈值常量: `IC_HIGH=0.10 / IC_MEDIUM=0.05 / IC_LOW=0.02 / IR_HIGH=1.0 / IR_MEDIUM=0.5`
  - 最小输入: `MIN_FACTORS=3` 个因子 + `MIN_OBSERVATIONS=3` 期数据

- **降级策略**:
  - reports 目录不存在 / 历史报告数 < 3 → 友好提示退出码 1
  - 因子数 < MIN_FACTORS → 跳过 (返回空 dict)
  - 跟踪历史缺失 → 自动用 `score_b` 截面均值作代理 (粗略, 但能产生可计算序列)
  - 报告 JSON 损坏 → 跳过该日, 不影响其他日

- **CLI 输出格式**:
  ```
  ━━━ 因子重要性排行 · 20260607 · 近 30 天 ━━━

  排名 | 因子名                | 策略      | IC      | IR    | 胜率  | 显著性
  ----------------------------------------------------------------
   1  | trend.momentum_20d    | 趋势      | +0.142  | 1.85  | 67%   | 高
   2  | fundamental.pe_ratio  | 基本面    | +0.118  | 1.42  | 62%   | 高
   3  | event_sentiment.news  | 事件情绪  | +0.095  | 1.18  | 58%   | 中
  ...
  20  | mean_reversion.bounce | 均值回归  | +0.022  | 0.18  | 51%   | 低

  按 IR 降序排列, 共 20 个因子 (高 3 / 中 5 / 无效 12)。前 1/3 建议保留; 后 1/3 建议淘汰。
  ```

- **测试覆盖**: `tests/test_factor_ic_analysis.py` (**30 个测试用例, 全部通过**)
  - 相关性: 完美正/负/无相关 (Spearman + Pearson)
  - IR 计算: rolling 模式下 mean/std 验证
  - ic_positive_rate: 单次模式 (0/1) + rolling 模式 (按符号计数)
  - Spearman vs Pearson 差异: 异常值时 Spearman 优于 Pearson
  - 边界: 空输入 / 因子数 < 3 / 收益长度 < 3 → 空 dict
  - NaN 处理: 因子值含 NaN 时该位置被丢弃, n_periods 减 1
  - 显著性分级: 4 个等级 + 边界值 (0.02/0.05/0.10)
  - 排名: NaN IR 不破坏排序; rank 1..N 完整分配
  - 内部: `_pearson_correlation` / `_spearman_correlation` (ties) / `_safe_stdev` (NaN 过滤)
  - 集成: mock 报告 + tracking_history → extract + compute
  - 渲染: 中文表格头 + 行内容验证
  - 策略推断: `trend.momentum_20d` → strategy=trend; 无前缀 → "unknown"

- **回归验证**: `tests/test_factor_ic_analysis.py` 30/30 通过; 周边关键模块 (screening/consecutive_recommendation 等) 无回归

- **设计取舍**:
  - **不依赖 scipy**: 手动实现 Spearman/Pearson + 平均秩, 避免引入科学计算依赖 (~50 行代码)
  - **单次 vs rolling 双模式**: 简单用例直接拿单值, 严谨用例可传 `rolling_window` 拿 IR
  - **策略推断用前缀**: `trend.xxx` → strategy=trend; 比要求调用方传 strategy 映射更轻量
  - **T+1 收益来源**: 优先用 `tracking_history.json` (P1-3 已有数据), 缺失时 fallback 到 `score_b` 截面均值

---

### P1-6 实现细节 — 组合风险预警仪表盘

**目标**: 为前端 `risk-monitor-panel.tsx` 提供实时 VaR / CVaR / 行业集中度 / 回撤预警的 API 端点 + 后端计算模块, 解决现有面板只展示静态 HHI/CVaR proxy 的局限。

**实现组件**:

- **新模块**: `src/portfolio/risk_metrics.py` — 纯函数 + dataclass, 无 I/O
  - `RiskSnapshot` dataclass: `portfolio_value / var_95 / var_99 / cvar_95 / cvar_99 / max_drawdown / current_drawdown / drawdown_warning / industry_concentration / concentration_warning / single_position_max / position_count / beta_adjusted / timestamp`
  - `compute_risk_snapshot(positions, lookback_returns, *, timestamp, initial_portfolio_value, var_horizon_days, confidence_levels, benchmark_returns, ...)` — 主入口
  - 内部工具: `_histogram_var` / `_histogram_cvar` (历史模拟法), `_max_drawdown_from_equity` / `_current_drawdown_from_equity`, `_weighted_portfolio_daily_returns` (按市值加权聚合 per-ticker → portfolio-level 日收益), `_aggregate_industry_weights`, `_resolve_beta`
  - 阈值常量: `INDUSTRY_CONCENTRATION_WARNING_THRESHOLD=0.25`, `SINGLE_POSITION_WARNING_THRESHOLD=0.12`, `DRAWDOWN_WARNING_THRESHOLD=0.10`

- **新模块**: `app/backend/routes/risk_metrics.py` — FastAPI 端点
  - `GET /api/portfolio/risk-snapshot?lookback_days=60` — 空快照 (前端初始加载用)
  - `POST /api/portfolio/risk-snapshot` — 完整 payload: positions + lookback_returns + 阈值参数
  - `GET /api/portfolio/risk-snapshot/thresholds` — 诊断端点, 返回当前生效阈值
  - Pydantic model: `PositionInput` / `LookbackReturnInput` / `RiskSnapshotRequest` / `RiskSnapshotResponse`

- **集成点**: `app/backend/routes/__init__.py` 注册 `risk_metrics_router` (public, `tags=["portfolio"]`)

- **算法选择**:
  - VaR / CVaR: 历史模拟法 (sorted tail), 不依赖参数分布假设; 95% / 99% 同时输出
  - 多日 VaR: `sqrt(T)` 缩放 (约定)
  - 行业集中度: `max(weight) > 0.25` 触发; 单一标的: `max(weight) > 0.12` 也触发集中度预警
  - 回撤: `current_dd >= 0.10` 触发预警; `max_dd` 始终计算
  - Beta: 至少 10 个观测点 + benchmark 序列; 不足则回退到 1.0 (market-neutral proxy), 避免误报 (GAMMA-005 / ALPHA-007)

- **数值安全**: 所有输入经 `_safe_float` 过滤, NaN/Inf → 0.0 (GAMMA-009 兼容)
- **无状态**: 路由层不绑 paper_trading 运行时, 由调用方 (前端/回测/审计) 注入持仓 + 回溯收益

- **测试覆盖**: `tests/test_risk_metrics.py` (18 个测试用例)
  - VaR/CVaR: 单一持仓 / 多持仓分散 VaR 更低 / 加权日收益聚合
  - 行业集中度: 求和归一化 / 阈值触发 / 分散解除预警
  - 回撤: 当前回撤 / 最大回撤 / 预警线
  - 单一标的: 占比上限触发预警
  - 端点: GET/POST / 阈值端点 / 路由注册
  - 边界: 空输入零快照 / NaN/Inf 不崩溃 / 无 industry_sw 退化为 "UNKNOWN" / var_horizon_days 缩放 / 响应模型往返

- **回归验证**: `tests/test_risk_metrics.py` (18/18 通过); 路由注册测试通过

---

## 12. 功能重复/臃肿审查 (R20.25 alpha-loop 调研)

> R20.25 迭代发现: 后端 API 已全部就绪, 剩余 P1-6, P2-2/5/6/7/9 均为前端工作。
> 鉴于产品目标 ("更易用、更高效找到未来 30 天最有投资价值的股票") 要求**简洁**, 建议在投入前端开发前
> 评估功能重复/合并机会, 避免系统臃肿。

### 12.1 候选功能合并

| 原 P# | 功能 | 与现有功能重叠 | 建议 |
|-------|------|----------------|------|
| **P2-5** 自定义策略权重 (前端滑块) | P0-2 推荐可解释性 (Top 3 因子贡献明细) 已展示各策略贡献 | **合并**: 将权重滑块作为 P0-2 可解释性面板的"高级设置", 不单独建滑块页面 |
| **P2-6** 标的分析详情页 | P1-8 标的对比工具 (--compare) 已支持多标的雷达图对比 | **合并**: 实现 P2-6 详情页 = P1-8 单数模式 (`--compare <single_ticker>`), 不需独立后端 |
| **P2-7** 回测场景回放 | 回测 dashboard (O-6) 已有回测可视化能力 | **合并**: 实现 P2-7 = O-6 回测 dashboard 的"历史滑块模式", 不另建独立模块 |

### 12.2 删除候选 (低价值/重复)

| 功能 | 删除理由 |
|------|----------|
| NL 自然语言选股 (R20.6 调研已标记) | 问财已垄断零售, 我们用 12 persona 差异化 |
| 移动端 App | Web + CLI 已满足, 投入产出比低 |
| 独立回测场景回放模块 (P2-7 原始版本) | 与回测 dashboard 重叠, 合并即可 |

### 12.3 R20.25 后端剩余工作 (scripts/ 测试债)

scripts/ 仍有 6 个行为变更测试失败 (R20.25-G), 需重构作者或产品负责人确认意图
后修复 (详情见 `changelog/r20-audit-history.md` R20.25 节)。**不建议在产品功能迭代中
绕过这些测试债**, 应在 R20.26 专项处理。

### 12.4 后续建议

- **Phase D 实现两项最高优先需求**: 按 alpha/beta/gamma 角色匹配, 后端优化类的为:
  - **P0-4 回测前端可视化** (O-6 业界对标 HIGH 优先级, 后端 API 已就绪) —— 可由 beta/gamma 协作
  - **P1-6 组合风险仪表盘** (后端 risk-snapshot API 已就绪) —— gamma 负责

---

**相关章节**: [1. 核心筛选流水线](./core-pipeline.md) | [3. 回测与验证](./backtesting.md) | [changelog/v2.1.0-v2.1.7.md](../changelog/v2.1.0-v2.1.7.md)
