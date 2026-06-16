# 产品功能提案清单 (R20.42 活跃路线图版)

> **目标**：让用户用尽可能少的入口，稳定找到未来 30 天最有投资价值、最值得买入的 A 股标的。
>
> **本版调整**：Round 6 产品调研后新增 R32-R33 两项前门信息密度需求（一句话理由+风险标签、组合预期收益汇总）。Campaign 16 新增 R41（fundamental ann_date PIT 过滤，deferred backlog）。Campaign 18 完成 R41（fundamental ann_date PIT 过滤落地）。Campaign 19 research refill 新增 R42-R44（回测可信度家族续集：survivorship-bias 审计 / PIT 不变式集成测试 / disclosure 标注 PIT 覆盖面）。Campaign 20 交付 R42 审计原语 `filter_stock_basic_as_of`（接线 deferred）+ 修复 BH-013（risk_off HOLD 被 mature_count=0 误判为 AVOID）。Campaign 21 完成 R43（PIT 不变式集成测试，5 原语横切回归守卫）+ research refill R45（连续推荐 streak 跨长假误算，R36 trade_cal 同族残留）。Campaign 22 完成 R45（trade_cal 真实日历替代 weekday 近似，2 个 TDD 守卫测试覆盖 CNY 跨假期 + trade_cal 不可用回退）。

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
3. 更值得买的目标：胜率、赔率、持续时间，综合最优的候选，而不是单指标最优，比如（能连续5天涨停的，肯定要比能连续3天涨停的更值得买，10天能涨50%的，肯定要比5天涨20%的好）。
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
| R18 | P3 | ✅ | **回测交易表稳定 key** | `BacktestTradingTable` 的 `<TableRow>` 改用复合 key `${date}-${ticker}-${idx}`，替代纯 `idx`，避免列表更新时 React diff 误复用 DOM 节点导致的 stale state（来自 ux-best-practices-2025-2026.md A-4 行）。 |
| R19 | P3 | ✅ | **回测交易表 WCAG caption** | `BacktestTradingTable` 补 `<TableCaption className="sr-only">`，让屏幕阅读器识别表格用途（WCAG 2.1 要求），sighted 用户不可见（来自 ux-best-practices-2025-2026.md A-3 行）。注：A-3 同清单的 R-2 横向滚动经核查为误报 — shadcn `<Table>` 自带 `overflow-auto` wrapper。 |
| R20 | P3 | ✅ | **回测 KPI 卡片移动端响应式** | `BacktestEquityCurve` KPI 网格从 `grid-cols-2` 改为 `grid-cols-1 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-6`，避免 6 张卡片在 320px 手机上每张仅 ~150px 过度拥挤（来自 ux-best-practices-2025-2026.md R-3 行）。 |
| R21 | P2 | ✅ | **回测交易表 A股货币符号** | 新增 `currencySymbolForTicker()` helper（6 位数字 ticker → ¥，否则 $），应用到 `BacktestTradingTable` 价格/持仓市值单元格，修正 A 股数据显示 `$` 的错误（来自 ux-best-practices-2025-2026.md A-7/V-4 行）。剩余 `$` 硬编码点（final_portfolio/exposure 等）为大型切片待后续。 |
| R22 | P2 | ✅ | **回测聚合面板 A股货币符号（R21 续集）** | 新增 `currencySymbolForMarket()` helper（market 'cn' 默认 → ¥，'us' → $），应用到 `BacktestResults`（Final Cash / Margin Used / Gross Exposure / Net Exposure）+ `BacktestPerformanceMetrics`（Current Value / Initial Value / P&L）+ 持仓表 long/short cost basis（per-ticker helper）。至此 backtest UI 全部 `$` 硬编码点清零。 |
| R23 | P3 | ✅ | **投资报告对话框 A股货币符号** | `InvestmentReportDialog` 价格单元格（line 449）从硬编码 `$` 改用 `currencySymbolForTicker(ticker)`，与 R21/R22 一致；扩展 `investment-report-dialog.test.tsx` 增加 A 股 (¥12.34) + 美股 ($150.00) 货币符号 characterization 测试。 |
| R24 | P3 | ✅ | **StockDetailCard 关闭按钮可访问名** | `StockDetailCard` 的 2 个 `✕` 图标按钮（loading + loaded 状态）补 `aria-label="关闭"`，让屏幕阅读器能识别关闭动作（WCAG 2.1: 图标按钮必须有 accessible name）；新增 a11y 测试断言 `aria-label`。 |
| R25 | P1 | ✅ | **QUICKSTART 失效文档链接修复** | 全仓 doc-link audit 发现 `docs/cn/product/QUICKSTART.md`（新用户前门）有 7 处失效 markdown 链接（`../` 应为 `./`，`./cli-reference.md` 应为 `./features/cli-reference.md` 等）— 修复后 `docs/cn/**/*.md` 失效链接 = 0。新用户 onboarding 路径不再 404。 |
| R26 | P2 | ✅ | **过时文件引用修复** | stale-file-reference-audit 发现 3 处文档引用已移动/删除的文件：① 功能矩阵 `MATRIX.md`/`data-infrastructure.md` 仍把已删除的 `src/data/quality_monitor.py` 标 ✅（与 `data-layer.md` 的删除说明矛盾）→ 改标 ⛔ 已移除；② `user-manual.md` 把 `strategy_attribution_daily.py` 误指向 `src/portfolio/`（实际在 `src/screening/`）；③ `README.md` 指向已归档的 `docs/zh-cn/manual/`（实际在 `docs/old-zh-cn/manual/`）。消除"幻影文件"困惑。 |
| R27 | P2 | ✅ | **`.env.example` 失效环境变量修复** | config-env-drift audit 发现 `.env.example` 文档化的 `ARK_FALLBACK_MODEL` 在代码中从未被读取 — Volcengine ARK provider 实际读的是 `ARK_MODEL`（见 `provider_registry_defaults.py:100` `model_env_var`）。用户照 `.env.example` 设置 `ARK_FALLBACK_MODEL` 会静默无效。改为正确的 `ARK_MODEL` + 注释说明。dead-env-var audit 1 → 0。 |
| R28 | P1 | ✅ | **`fpdf2` 依赖缺失声明** | dependency-freshness audit 发现 `src/reporting/pdf_exporter.py` 顶层 `from fpdf import FPDF` 但 `fpdf2` **不在** pyproject.toml / poetry.lock / uv.lock 任何依赖声明中 — 当前仅因开发机 .venv 恰好装了 2.8.7 才能工作。新用户 `uv sync` 后跑 `--export-pdf` 会 `ModuleNotFoundError: fpdf`。在 `[project.dependencies]` 和 `[tool.poetry.dependencies]` 各加 `fpdf2>=2.8.7`，恢复安装可复现性。 |
| R29 | P3 | ✅ | **AttributionPage 演示按钮主题适配** | UX 研究 ux-best-practices-2025-2026.md V-3 行：`AttributionPage.tsx` 的 "Run Demo Attribution" 触发按钮原来是原生 `<button>` + 硬编码 `bg-blue-600` / `bg-blue-700`，不跟主题切换；改用 shadcn `<Button>`（default variant，落到 `bg-primary` / `text-primary-foreground` design token），自动获得统一的 focus-ring + disabled 样式与亮/暗主题适配。新增 `AttributionPage.test.tsx`（6 个 characterization 测试）锁定可访问名、design-token 类、`bg-blue-600/700` 反退守卫、`focus-visible:ring`、`mb-6` 布局间距、初始 enabled 状态。 |
| R30 | P3 | ✅ | **回测 SVG 窄屏 aspect-ratio 守卫** | UX 研究 ux-best-practices-2025-2026.md R-4 行：`backtest-equity-curve.tsx` 的 EquityCurveChart 与 DrawdownChart 两个 `<svg>` 固定 `viewBox="0 0 800 200"` 但缺 `preserveAspectRatio`，超窄屏（手机 320px）下浏览器默认行为不一致可能挤压变形。两个 SVG 都补 `preserveAspectRatio="xMidYMid meet"`，并扩展 `backtest-equity-curve.test.tsx` 加 R30 守卫测试断言两个 SVG 都声明此属性。 |
| R31 | P2 | ✅ | **CLI 参考补全 6 条缺失命令** | onboarding-command-smoke audit 发现 `src/cli/dispatcher.py` 注册的 6 条 power-user 命令在 `cli-reference.md`（自称的"完整 CLI 命令索引"）中完全缺失：`--daily-gainers`（每日涨幅筛选, MATRIX 已记录但 reference 漏）、`--export-conditional-orders`（券商条件单导出 P1-13）、`--sector-strength`（行业强度排序 P10-2）、`--signal-momentum`（信号动量评分 P10-1）、`--volume-confirm`（量价确认 P11-2）、`--weekly-report`（组合体检周报推送 P2-10）。补全后 dispatcher 注册表与 CLI 参考索引完全对齐（diff = 0），power-user 不再"知道命令存在但找不到文档"。 |
| R32 | P1 | ✅ | **前门一句话理由 + 风险标签** | `--top-picks` 每只推荐追加一行：`理由: 动量+行业共振 | 风险: 中(ATR 4.2%)`。复用 R15 因子归因（Top-2 因子→中文标签）+ R8 ATR（→ 低/中/高风险等级，阈值 3%/5%）。重构 `_render_stop_loss_take_profit` 提取 `_compute_pick_risk_advice`（R8+R32 共享一次取数）。14 个回归测试。 |
| R33 | P2 | ✅ | **前门组合预期收益汇总行** | `--top-picks` 底部追加一行：`组合 T+30 预期: +3.2% (加权) | 平均胜率: 58% | BUY 数: 4`。复用 `expected_return.py` 的 T+30 edge，对所有 BUY 等权平均（BUY 门控已要求 `bucket_sample_count >= 20`，低样本票不会进入 BUY 聚合，故无需额外降权），仅当 ≥2 只 BUY 时展示。回归测试含「低样本票永远不可能 BUY」守卫，防止未来 verdict 门控变更静默破坏等权假设。 |
| R34 | P3 | ✅ | **前门 decision-flow 升级提示** | `--top-picks` 底部追加一行：`💡 深度分析（阈值/一致性/逐因子明细）请运行 --decision-flow`。落实 Round 6 调研发现 1（round6-product-analysis.md:15）：前门已覆盖新鲜度/verdict/T+30/因子归因/止损，power-user 的深度链路需显式指引而非让用户两个命令都跑。服务于「避免前门分裂」目标。 |
| R35 | P1 | ✅ | **T+30 样本成熟度归因诚实化** | 前门/决策流/校准的 30 天 edge 旁的"样本"数此前用 `bucket_sample_count`（桶内全部历史推荐，含尚未满 30 天的未成熟记录），误导用户以为 T+30 数字由全量样本背书。新增 per-horizon 成熟样本计数字段（`tN_sample_count` / `total_t30_samples` / `bucket_t30_mature_count`），所有展示 T+30 edge/胜率 的位置（`--top-picks`、`--decision-flow`、`--expected-returns`、`--confidence-calibration`）改为同时显示"全部样本"与"T+30 成熟样本"，让用户判断 30 天统计的真实可信度。服务于"更高确信"目标。 |
| R36 | P1 | ✅ | **连续推荐 streak 用交易日步进（修复周末断裂）** | `consecutive_recommendation.py` 的 streak 追踪此前用自然日 `timedelta(days=1)` 步进，导致每个周末（周五→周一）streak 断裂为 1，把 R4 连续推荐加权在最常见的周一/周二报告上清零。改为交易日步进（`_prev_trading_day`，跳过周六/周日），周末跨度的连续推荐正确计入 streak。同时修复 R9 评分趋势箭头在 `previous_score=0.0`（由 None/NaN 归零）时误显"→"（应为空），以及 `_summarize_history` lookback 锚定墙钟 `datetime.now()` 导致回填数据被静默丢出窗口的问题（新增 `as_of` 参数）。服务于"更清晰决策"目标。 |
| R37 | P1 | ✅ | **回测价格复权改前复权（qfq）** | `_fetch_tushare_ashare_prices_df` 此前用 `pro.daily`（不复权），跨除权除息日（送股/分红/配股）产生假跳空缺口，系统性高估回撤/低估收益。改为 `ts.pro_bar(adj="qfq")`（前复权），消除分红缺口，收益计算干净。复权只作用于价格水平，不改变收益结构（止损/ATR 逻辑不受影响）。新增 `_cached_tushare_pro_bar_call` / `_call_tushare_pro_bar_api` 复用缓存+重试机制（pro_bar 是 tushare 顶层函数，非 pro 方法）。授权来源：用户明确同意 R37/R38/R39 全部实施。 |
| R38 | P2 | ✅ | **回测交易日历用 A 股真实交易日（trade_cal）** | `iter_backtest_dates` 此前用 pandas `freq="B"`（周一-周五通用工作日），不排除中国节假日（春节/国庆等）。节假日时 `load_current_prices` 回退到前一个交易日收盘价，产生 phantom zero-return bar，轻微稀释 Sharpe/年化。改为优先用 `get_open_trade_dates`（trade_cal，返回 A 股真实开市日），空列表/异常时 fallback 到 `freq="B"`（保证无 token 或网络失败时 backtest 仍可运行）。授权来源：用户明确同意 R37/R38/R39 全部实施。 |
| R39 | P1 | ✅ | **composite_score fallback domain mismatch — 保守 penalty 修正** | 当 ticker 不在 composite_report 中（composite 计算异常或超出 top_n），`rank_recommendations_by_investability` 的 fallback 此前把 `score_b`（域 [0,1]）直接赋给 `composite_score`（域 [-1,1]，含负 penalties），绕过 consistency/momentum/sector 负调整。改为对 fallback 应用 0.9 保守折扣（score_b=0.55 → 0.495 < BUY 0.5 门控）并标记 `composite_verified=False`，verified 路径标 `composite_verified=True`。验证结论：正常流程下 fallback 是 latent（composite 覆盖所有 ticker），仅在 composite 计算整体异常（main.py except 返回无 composite 的 ranking_pool）时触发，故采用保守折扣而非移除 fallback（避免把边界情况的好票打成 AVOID）。授权来源：用户明确同意 R37/R38/R39 全部实施。 |
| R40 | P2 | ✅ | **macro_data look-ahead 修复（fetch_macro_snapshot 新增 as_of 点在时间过滤）** | `src/data/macro_data.py` 的 `fetch_macro_snapshot()` 此前拉取"最新"宏观数据发布，无 `as_of`/`trade_date` 过滤。回测/replay 场景下会读到模拟交易日之后发布的宏观数据（point-in-time look-ahead）。新增可选 `as_of` 参数（YYYY-MM-DD 或 YYYYMMDD），通过 `_filter_df_as_of` 按 `month <= as_of_month` 过滤所有指标，消除前瞻。为 None 时保持原"取最新"行为（live 模式不变）。当前仅作为 `state.macro_context` 的 informational label，未被 `_resolve_regime_gate` / `classify_btst_regime_gate` / 仓位缩放 / risk-off 决策消费，且 `build_market_state` 不在 backtest 引擎调用路径内，故此修复为 latent 风险的前瞻性消除（确保未来接入 backtest 时不会读到未来数据），服务于"更高确信"目标。 |
| R41 | P1 | ✅ | **fundamental 财报 ann_date point-in-time 过滤（R40 lookahead hardening 续集）** | Bug Hunt（campaign 16）发现 fundamental 数据路径无 `ann_date`（公告日）过滤——`_should_include_financial_period`（`tushare_financial_metrics_helpers.py:262`）只按 period 类型（annual/quarterly/ttm）过滤，不检查公告日是否 ≤ trade date。回测会用模拟交易日后才公告的财报（如 2 月回测读到 4 月才公告的 2023 年报），系统性虚高 fundamental agents（Warren Buffett / Michael Burry / Cathie Wood 等）回测收益。**Campaign 18 修复**：`_should_include_financial_period` 新增 `ann_date_str` + `as_of_date` 参数，当二者均存在且 `ann_date > as_of` 时排除该行；缺省/格式异常时回退到历史行为（live 模式不变，避免过度过滤误丢合法数据，对齐 C2-BH2 鲁棒性契约）。trade date 与 ann_date 均做 dashed→compact 归一化。TDD：8 个 fixture 测试覆盖 live-mode-unchanged / PIT-exclude / PIT-include / dashed-normalize / malformed-fallback / 集成回测路径。服务于"更高确信"目标。 |
| R42 | P2 | 🔄 | **回测选股池 survivorship-bias 审计 + PIT 过滤原语（R37-R41 回测可信度家族续集）** | Campaign 19 产品研究（backlog 耗尽后的 research refill）发现：`_fetch_tushare_all_stock_basic`（`tushare_api.py:841`）用 `list_status="L"`（当前在市）构建股票池，历史回测的选股池因此**无法包含回测期间已退市的标的**，系统性美化结果（survivorship bias，beta veto 类，R37-R41 lookahead hardening 家族的同类残留——已修 prices/calendar/macro/fundamental，universe 构建漏审）。**Campaign 20 交付审计原语**：`filter_stock_basic_as_of(stock_basic, as_of=)` 纯函数——按 `list_date ≤ as_of` 且（无 `delist_date` 或 `delist_date > as_of`）过滤股票池，正是 survivorship-bias 的 PIT 修复原语。13 个 fixture 测试覆盖 6 个 PIT 边界（在市/IPO 后/IPO 当日/退市前/退市后/退市当日）+ 缺失 list_date 保守排除 + dashed 日期归一化 + 缺失 delist_date 列容错 + as_of=None live 模式 noop + audit summary 量化偏差面。**接线 deferred**：原语已就绪但尚未接入 backtest candidate_pool 路径（需 `get_all_stock_basic` 在 backtest 模式额外拉取 `list_status="D"` 退市股票并合并，再按 trade_date 调用 `filter_stock_basic_as_of`；属 beta veto 大切片，需独立 campaign 授权 + live API 验证）。next_smallest_slice: backtest 引擎在构建历史选股池时调用 `filter_stock_basic_as_of(universe_with_delist, as_of=trade_date)`。 |
| R43 | P2 | ✅ | **回测 PIT 不变式集成测试（R37-R41 回归守卫）** | Campaign 19 产品研究发现：R37-R41 每项各有单元测试（prices qfq / trade_cal / macro as_of / fundamental ann_date），但**没有任何单一集成测试断言"一次回测运行不会读到任何晚于模拟交易日的数据"**横跨四条已加固路径。lookahead 家族用了 5 场 campaign 才补完，说明完整性脆弱、缺回归守卫——任一加固可能在未来被静默回退。**Campaign 21 交付**：`tests/backtesting/test_pit_invariant_integration.py`——单一共享 `AS_OF=20240115` 场景，用合成 fixture 同时验证五个 PIT 原语（R37 qfq 价格锚定 / R40 macro 按月过滤 / R41 fundamental ann_date 排除 / R42 universe list/delist 过滤 / 跨原语一致性）。5 个测试覆盖"合法 PIT 数据保留 + 未来 lookahead 数据排除"横切契约，任一原语日期比较翻转（off-by-one/string-vs-int）即 loud break。test-only，不增产品臃肿，fixture-driven 无 live API。 |
| R44 | P3 | ✅ | **回测 disclosure 标注 PIT 加固覆盖面（gamma 可信度校准）** | Campaign 19 产品研究发现：`cli.py:127` 的 gamma disclosure 警告"回测为历史样本统计"，但**未告知用户 look-ahead 表面现已加固（R37-R41）**，用户无法校准对回测数字的信任度。trust calibration 是"更高确信"目标的一部分。**Campaign 19 交付**：`cli.py` 回测输出在原有风险警告后追加一行，列出已 PIT 加固的数据路径（价格前复权/A股真实交易日历/宏观 as_of/财报 ann_date）与已知未覆盖面（R42 survivorship 待审），让用户据实校准信任度。doc/text-only，5 个 cli 回归测试通过。 |
| R45 | P3 | ✅ | **连续推荐 streak 跨长假误算修复（R36 同族：交易日历近似残留）** | Campaign 21 research refill 发现：`_prev_trading_day`（`consecutive_recommendation.py:132`）用 weekday 近似（跳周六/周日）计算 streak 步进，与 R38 同族——R38 已修 backtest 日期迭代用真实 trade_cal，但 streak 计算仍用 weekday 近似。**影响**：春节/国庆等 7-9 天长假期间，weekday 近似会让节前最后交易日的报告误连接到节后首日的报告，phantom-连接虚增 streak 与 R4 加权。**Campaign 22 修复**：新增 `_resolve_real_open_trade_dates` (拉取 trade_cal 真实开市日，窗口前置 14 天预留长假闭市) + `_prev_real_trading_day` (基于 sorted open dates 二分查找前一交易日)，`compute_consecutive_recommendations` 改用真实日历步进；trade_cal 不可用时 fallback 到 `_prev_trading_day`（保持 R36 周末步进行为）。2 个 TDD 守卫测试：(a) CNY 跨假期 Wed+Thu+Mon+Tue 4-day 真实连续 streak；(b) trade_cal 空时回退到 weekday 近似。40/40 unit 测试全绿。服务于"更清晰决策"目标 (R36 同族缺口收口)。 |

> 各已完成项的实现级设计细节（现状 / 方案 / 收益）已归档到 [`changelog/completed-roadmap-phases.md` §五](./changelog/completed-roadmap-phases.md#五r8-r33-前门信息密度设计细节归档)，主文档仅保留上表的一句话价值结论，避免历史实现细节淹没当前目标（见 §六维护规则 #2）。

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

> **最后更新**：2026-06-17（Campaign 22：完成 R45 streak 跨长假修复，trade_cal 真实日历替代 weekday 近似）
