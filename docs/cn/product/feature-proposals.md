# 产品功能提案清单 (R20.42 活跃路线图版)

> **目标**：让用户用尽可能少的入口，稳定找到未来 30 天最有投资价值、最值得买入的 A 股标的。
>
> **本版调整**：Round 6 产品调研后新增 R32-R33 两项前门信息密度需求（一句话理由+风险标签、组合预期收益汇总）。Campaign 16 新增 R41（fundamental ann_date PIT 过滤，deferred backlog）。Campaign 18 完成 R41（fundamental ann_date PIT 过滤落地）。Campaign 19 research refill 新增 R42-R44（回测可信度家族续集：survivorship-bias 审计 / PIT 不变式集成测试 / disclosure 标注 PIT 覆盖面）。Campaign 20 交付 R42 审计原语 `filter_stock_basic_as_of`（接线 deferred）+ 修复 BH-013（risk_off HOLD 被 mature_count=0 误判为 AVOID）。Campaign 21 完成 R43（PIT 不变式集成测试，5 原语横切回归守卫）+ research refill R45（连续推荐 streak 跨长假误算，R36 trade_cal 同族残留）。Campaign 22 完成 R45（trade_cal 真实日历替代 weekday 近似，2 个 TDD 守卫测试覆盖 CNY 跨假期 + trade_cal 不可用回退）。Campaign 23 完成 R46（同族 drain：top-picks 报告新鲜度告警跨长假误报修复，3 个 TDD 守卫）。Campaign 24 完成 R47（trade_cal 降级可观测性：streak/freshness 回退时发 debug 日志）+ bisect 重构 `_prev_real_trading_day`。Campaign 25 完成 R48（BH-017 核心 sorting 静默 except drain：4 处 silent except 加可观测日志，2 TDD 守卫）。Campaign 26 完成 R49（BH-017 同族续：data_freshness_guard 5 处 silent except drain + 1 TDD 守卫）。Campaign 27 完成 R50（BH-017 同族收口：回测持仓 mark-to-market + 缓存预热 silent except drain + 2 处显式 reject）。Campaign 28 完成 R51（verify 推荐闭环验证补 T+5 渲染：computed-but-hidden 一致性修复，主表升级 4 列 T+1/T+3/T+5）。Campaign 29 完成 R52（--expected-returns 全量表补 T+30 胜率列：computed-but-hidden 同族 drain）。Campaign 30 完成 R53（--top/--auto 衰减标记补 days_since_peak：computed-but-hidden 同族收口，2 个 row builder + 3 TDD 守卫）。Campaign 31 完成 R54（BH-018 / R36 同族：verify lookback cutoff 锚定墙钟 now() → 改锚定最新报告日期，修复回填/历史分析静默失效）。

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
| R46 | P2 | ✅ | **--top-picks 报告新鲜度告警跨长假误报修复（R45 同族 drain）** | Campaign 22 Bug Hunt 发现 R45 同族同根因：`top_picks.py:_trading_days_between` 用 weekday 近似计算"已过期 N 个交易日"。**影响**：春节/国庆等长假期间，weekday 近似会把假期内的工作日误计入 elapsed trading days，让 `--top-picks` 顶部对节前报告显示"⚠ 非最新，请先运行 --auto 更新"——但市场闭市期间根本不会有新数据，告警误导用户在闭市期间反复跑 --auto。**Campaign 23 修复**：抽取 `_real_trading_days_between` (基于 trade_cal 计数严格区间内开市日) ，`_trading_days_between` 改为 trade_cal 优先 + weekday 回退；`_check_report_freshness` 通过现有 `_trading_days_elapsed` 自动获益。3 个 TDD 守卫测试：(a) CNY 闭市期内复查 pre-CNY 报告无误报；(b) post-CNY 真实经过 ≥2 交易日仍正确告警；(c) trade_cal 空时回退到 weekday（R36 行为保持）。8 → 11 freshness 测试全绿。服务于"更清晰决策"+ 用户对回测/选股结果的信任度。 |
| R47 | P3 | ✅ | **trade_cal 降级可观测性（R45/R46 配套）** | Campaign 24 发现：R45/R46 让 streak 与 freshness 路径优先用真实 trade_cal、不可用时静默回退到 weekday 近似。但 trade_cal 返回空（无 TUSHARE_TOKEN / 网络失败）时此前**完全无日志**，运维与用户无法诊断"长假窗口的计算为何可能偏差"。**修复**：`_resolve_real_open_trade_dates`（streak 路径）与 `_real_trading_days_between`（freshness 路径）在 trade_cal 返回空时各发一条 `logger.debug` 降级提示，说明已回退到 weekday 近似且长假精度会降级；`top_picks.py` 新增 module-level logger（此前无 logging）。debug 级别避免噪音，运维调高级别即可诊断。服务于"更高确信"+ 可运维性，不改变任何行为。 |
| R48 | P2 | ✅ | **核心排序降级可观测性（BH-017 silent except drain）** | Campaign 25 Bug Hunt 发现：`_rank_pool_by_investability`（main.py:496）用 `except Exception: return ranking_pool` **静默吞掉所有排序异常**——composite-score / expected-return / investability ranking 任一失败时，用户看到的是未排序的 fallback pool，但无任何信号表明排序已降级。这直接破坏"更高确信"目标：用户以为看到的是投资性排序结果，实际是无序回退。**修复**：except 分支新增 `logger.warning` 记录降级原因；同类 drain 另外 3 处 silent except（decay per-ticker 解析 / FusedScore 旧格式跳过 / expected-returns 显示）各加 `logger.debug` 诊断日志。行为零变更（仍 fallback），但降级完全可观测。2 个 TDD 守卫（降级时 warn / 正常路径不 warn）。服务于"更高确信"+ 可运维性。 |
| R49 | P2 | ✅ | **数据新鲜度审计降级可观测性（BH-017 同族 drain 续）** | Campaign 26 Bug Hunt 发现 R48 同族：`data_freshness_guard._check_cache_freshness` 有 5 处 `except Exception: pass`——缓存 DB 连接失败（locked/corrupt/permission）或某数据源查询失败时，新鲜度审计静默返回空，让 `--auto` / `--decision-flow` 对真实过期的缓存报"全部新鲜"的假信号。**修复**：外层 DB 连接失败加 `logger.warning`（整个审计不可用 = 重大）；3 个 per-source 查询失败加 `logger.debug`（best-effort 诊断）；模块新增 logger（此前无 logging）。1 个 TDD 守卫（connect 失败时返回空 dict + 发 warning）。行为零变更，但缓存新鲜度审计的 false-"all fresh" 风险完全可诊断。 |
| R50 | P2 | ✅ | **回测持仓 mark-to-market + 缓存预热降级可观测性（BH-017 同族收口）** | Campaign 27 Bug Hunt 收口 BH-017 同族剩余 silent except：① `engine_market_data.hydrate_position_prices` 持仓 mark-to-market 价格拉取失败时静默回退 cost_basis——这是**回测数据正确性路径**，静默回退可能扭曲 NAV/回撤而无信号；② `cache_preheater` per-ticker 财务指标预热拉取失败静默跳过，系统性 fetch 失败会静默降低预热覆盖。**修复**：两处各加 `logger.debug` 降级诊断。**reject**：`enhanced_cache` 的 `.close()` 已失败连接清理（合法静默——清理 broken conn 失败不可操作）+ `pdf_exporter` 字体回退（纯 cosmetic）。2 处修复 + 2 处显式 reject。回测 460 测试全绿。至此 BH-017 silent-except 家族在数据正确性/排序/新鲜度/回测路径全部收口。 |
| R51 | P2 | ✅ | **verify 推荐闭环验证补 T+5 渲染（computed-but-hidden 一致性修复）** | Campaign 28 Bug Hunt 发现：`verify_recommendations.py` 计算了完整 T+1/T+3/T+5/T+10/T+20/T+30 六档胜率与平均收益（`overall_t5_win_rate` / `avg_t5_return` 全量 populated），模块 docstring 也宣称"T+1/T+3/T+5"，但 `render_verify_recommendations` 主表只渲染 T+1/T+3、扩展表只渲染 T+10/T+20/T+30——**T+5 被计算却从未展示**，成了 wasted computation，用户也看不到 T+3→T+10 之间的中间档。**修复**：主表升级为 4 列 (T+1/T+3/T+5)，让完整 horizon ladder 对用户可见，兑现 docstring 承诺。1 个 TDD 守卫（`test_render_shows_t5_column`：summary 有 T+5 数据时渲染输出必须含 "T+5"）。25 verify 测试全绿。服务于"更高确信"（用户看到完整周期阶梯验证推荐质量）。 |
| R52 | P2 | ✅ | **--expected-returns 补 T+30 胜率列（computed-but-hidden 同族 drain）** | Campaign 29 Bug Hunt 发现 R51 同族：`ExpectedReturn` dataclass 有 `win_rates: dict[horizon→win_rate]` 全量计算（所有周期），但 `render_expected_returns`（`--expected-returns` CLI 用的全量表）只展示 `expected_returns`，**完全不展示任何 win rate**。compact renderer 只展示 T+30 胜率。**影响**：T+30 edge 驱动 BUY 门控，但用户在全量表里看不到这个 edge 的胜率——+5% 预期 + 40% 胜率 vs +3% 预期 + 70% 胜率，后者更优却无法从展示判断。**修复**：全量表加 "T+30胜率" 列，让决策周期胜率可见。1 个 TDD 守卫。26 expected_return 测试全绿。 |
| R53 | P2 | ✅ | **--top/--auto 衰减标记补 days_since_peak（computed-but-hidden 同族收口）** | Campaign 30 Bug Hunt 收口 R51/R52 同族：`DecayInfo.days_since_peak`（ticker 评分距历史最高的天数）由 `signal_decay_detector` 计算并序列化进报告，但 `--top` / `--auto` 表格的 decay 标记只展示 `change_pct`，**days_since_peak 从未渲染**。**影响**：↓20% 在 1 天内发生（急跌，可能恐慌）vs ↓20% 在 5 天内发生（缓慢衰退，趋势结束）是不同的决策信号，但用户无法区分。**修复**：两个 row builder (`_build_top_table_row` / `_build_auto_screening_table_row`) 的 decay 标记追加 `(Nd)` 后缀（days_since_peak > 0 时），如 `↓20%(5d)`；peak 当天（0 天）不追加。3 个 TDD 守卫（含 Nd 后缀 / peak 不追加 / none 显示 —）。至此 computed-but-hidden 家族（T+5 / T+30胜率 / days_since_peak）收口。 |
| R54 | P1 | ✅ | **verify 推荐闭环验证 lookback 锚定修复（BH-018 / R36 同族：wall-clock now() 残留）** | Campaign 31 Bug Hunt 发现 R36 同族残留：`verify_recommendations._load_auto_screening_reports` 的 lookback cutoff 用 `datetime.now() - timedelta(lookback+10)`——锚定墙钟而非数据。**影响**：任何比 `now() - (lookback+10)` 更旧的报告被**静默丢弃**（`continue`），导致回填/历史分析全部失效：一个全是 2026-01 报告的目录在 2026-06 跑 `--verify-recommendations --verify-lookback=30` 时返回空（"无推荐数据"），尽管这些报告相对彼此完全在窗口内。同时 `__import__("datetime").timedelta` 是 hack 代码味（因只 import 了 datetime 类未 import timedelta）。**修复**：cutoff 锚定到目录内**最新报告日期**（两遍扫描：先收集候选+最新日期，再按 `latest - (lookback+10)` 过滤），与 R36 `as_of` 修复同型；正确 import `timedelta`。1 个 TDD 守卫（2026-01 三份报告在 6 月墙钟下全部加载，anchored-to-latest）。26 verify + 460 backtest 测试全绿。服务于"更高确信"（历史/回填推荐验证不再静默失效）。 |
| R55 | P1 | ✅ | **PDF 追踪总结 schema 契约错配修复 + 全 horizon 渲染（BH-019 / R51-R53 computed-but-hidden 同族 + 契约错配）** | Campaign 33 Bug Hunt 发现：`pdf_exporter._render_tracking_summary` 读取 `t1_win_rate` / `t3_win_rate` / `t5_win_rate` / `total_observations` / `avg_t1_return` / `avg_t3_return`，但 `tracking_summary` 的真实生产者 `recommendation_tracker._summarize_history` / `get_tracking_summary` **从未写入这些键**（它写 `win_rate_day{N}` / `avg_return_day{N}` / `tracked_count_day{N}`，N∈DEFAULT_HORIZONS=1/3/5/10/20/30）。**双重影响**：① `--export-pdf` 报告的"追踪总结"区块在真实 payload 上**所有胜率恒为 "n/a"、总观察样本恒为 0** —— 用户据 PDF 校准推荐可信度时拿到的是误导性空白（false-"无数据"）；② 即便键名对上，也只渲染 T+1/T+3/T+5，丢弃 T+10/T+20/T+30（R51/R52 computed-but-hidden 同族）。**修复**：改读真实 producer schema 键，渲染完整 6-horizon ladder（T+1/T+3/T+5/T+10/T+20/T+30 胜率 + 平均收益 + 样本数 tag）。2 个 TDD 守卫（real-producer-schema 渲染断言 via _kv_line spy + None horizon 优雅 "n/a" 不崩）；`_full_report` fixture 改用真实 producer schema。24 pdf 测试全绿。服务于"更高确信"（PDF 推荐追踪总结不再误导，完整 horizon ladder 可见）。 |
| R56 | P1 | ✅ | **--verify-detail 日度明细渲染修复（BH-020 / dead-CLI-flag + computed-but-hidden）** | Campaign 34 Bug Hunt 发现：`--verify-detail`（`include_detail=True`）触发 `compute_verify_recommendations` 填充 `summary.daily_details`（`VerifyDay` 记录，含 date / tickers / top_score / avg_t1~t30_return / benchmark_return / excess_return 全量字段），但 `render_verify_recommendations` **从不渲染 daily_details** —— 整个 `--verify-detail` flag 在展示层是 silent no-op：用户加了 `--verify-detail` 却看不到任何额外输出，尽管每个 VerifyDay 字段都被计算了。这是 dead-CLI-flag + computed-but-hidden（R51-R55 同族）双重缺陷。**修复**：`render_verify_recommendations` 新增"日度明细"表格（仅当 daily_details 非空时渲染），列含 日期 / 标的数 / T+1均收 / 基准T+1 / 超额 / 最高分，让 power-user 能逐日核查推荐质量与基准表现。2 个 TDD 守卫（detail 模式渲染 daily_dates + "日度明细" marker；非 detail 模式不渲染空 section）。先确认 fail 再修（systematic-debugging）。121 verify+top_picks 测试全绿。服务于"更高确信"（power-user 深度审计工具恢复可用）。 |

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

> **最后更新**：2026-06-17（Campaign 34：完成 R56 --verify-detail 日度明细渲染修复 BH-020 / dead-CLI-flag + computed-but-hidden 同族）
