# 特性提案 (Feature Proposals)

> 最近更新: 2026-06-05 (补充 5.x 优化建议 + 6.x 新功能提案 + 7.x 合并路线图)
> 目标: 提升产品易用性, 让用户在 30 天投资窗口内更高效地找到最有价值的股票

## 0. 方法论与范围

本文档以"**帮用户在 30 天投资窗口内更快找到最高收益股票**"为目标, 系统梳理了
`docs/zh-cn/product/` 与 `docs/plans/` 下 8 份产品/计划文档 (`stock_selection_mvp_design.md`、
`institutional_multi_strategy_framework_v1.4.md`、`auth_design.md`、4 份 BTST
相关 plan, 以及 `arch_optimize.md` 主线架构) 与 `src/`、`scripts/`、`app/` 中已落地代码之间的
差距, 输出三类提案:

- **待优化 (Optimize)**: 文档有定义, 代码有实现, 但使用体验/产出质量低于设计目标。
- **待新增 (Add)**: 文档明确点名要补、但当前代码缺失的核心能力。
- **应清理 (Remove)**: 已废弃但仍在产物中暴露, 制造噪声或误导的接口。

2026-06-05 补充: 在原有 1~4 章基础上, 新增 **5.x 已有功能优化建议** (6 条,
聚焦缓存键设计 / N+1 IO / 数据质量可见性 / 投资报告体验 / 参数对比 / 脚本索引)
和 **6.x 新功能提案** (4 条, 聚焦数据源健康 / 选股回顾闭环 / 收益归因 / LLM 成本),
并合并为 **7.x 统一路线图**。

提案中每条都引用至少一份 source doc, 关键诉求"避免重复"已通过
[附录 A 文档清单] 与 [附录 B 已识别的文档内已有提案] 双向核对。

---

## 1. 待优化功能 (Optimize existing)

### 1.1 把"是否有增量 alpha"做到端上可见
- **现状**: `src/research/artifacts.py` 已经把 `risk_budget_ratio` /
  `p6_risk_budget` / `expected_edge` (在 `artifacts.py` 与
  `run_btst_next_day_package.py` 中均已写入) 落进了 `operator_summary.json`
  和 research artifact, 但前端 `app/frontend/src/components/replay-artifacts/`
  与 `nodes/components/investment-report-dialog.tsx` 仍以"JSON / 报告文本"裸读,
  没有任何可视化字段强调"这只票未来 30 天的预期 edge"或"风险预算剩余"。
- **痛点**: 用户读盘最关心的问题 ——"如果买这只, 30 天最坏/最好/期望能到多少, 我能下多少"
  —— 仍需要从 JSON 里自己换算。
- **改进方案**: 在 `InvestmentReportDialog` 中新增 `EdgeCard` 组件, 渲染 3 个数字
  (expected 30d edge, CVaR(95%) 单票敞口, 当前 risk budget ratio), 配 1 句机器
  生成的"为什么是这个数"摘要。表头新增 1 个 `30D Edge` 排序按钮。
- **预期收益**: 盘前 30 秒内能从 UI 看见"哪只票 30 天期望收益最高 / 风险预算最满",
  不必打开 `operator_summary.json`。
- **估算工作量**: S (1-2 天)
- **优先级**: P0

> 来源: `docs/plans/2026-06-03-btst-doc-decision-system-improvement-plan.md` P0
> 第 4 条 "ONE-PAGER 8 行主问题" + `arch_optimize.md` §2 "可归因原则"。

### 1.2 把 Layer B/C 融合权重在 UI 中显式化
- **现状**: `src/screening/signal_fusion.py` 与 `src/screening/signal_fusion_arbitration_helpers.py`
  已经实现 v1.4 框架的"市场状态调整 → 仲裁 → 归一化 → 融合"完整流程,
  并支持 0.4/0.6 的 Layer B/C 权重, 但前端 `portfolio-manager-node.tsx` /
  `investment-report-node.tsx` 只展示最终 `Score_C`, 不展示"Layer B 贡献 vs Layer C 贡献"。
- **痛点**: 用户想判断"这只票是规则系统看好, 还是 LLM 看好" 时看不到。
  v1.4 框架把这条作为高敏感参数 (7.2 节), 看不到贡献拆分就无法做归因。
- **改进方案**: 在 `InvestmentReportNode` 摘要里增加 `Score_B / Score_C` 双进度条,
  颜色和当前 `market_state` 关联 (trend=蓝, range=绿, emotion=橙), 点击展开
  4 策略子因子雷达图。
- **预期收益**: 让 walk-forward 调权 0.4/0.6 时的争议收敛 — 用户能立刻看到权重
  调整有没有意义, 而不是只看 Sharpe Ratio。
- **估算工作量**: M (3-5 天)
- **优先级**: P1

> 来源: `institutional_multi_strategy_framework_v1.4.md` §3.1 / §5.1 / §7.2。

### 1.3 让"反向验证 / 解压回放"在 Web 上能直接跑
- **现状**: `scripts/validate_btst_early_runner_history.py`、
  `scripts/run_btst_recurring_shadow_close_bundle.py`、
  `scripts/run_btst_candidate_pool_corridor_validation_pack.py` 等回放/验证脚本
  存在, 但 `app/backend/routes/replay_artifacts.py` 只暴露 `replay-artifacts`
  列表/查看 API, 没有"选择某日 + 重跑某脚本"的 endpoint;
  `replay-artifacts-inspector.tsx` 也只读不写。
- **痛点**: 研究员想验证"v1.4 框架在 2024-09 那次急涨急跌下是否爆仓"时,
  必须 ssh 到服务器手串 CLI, UI 上的 inspector 看不到回放结果。
- **改进方案**: 新增 `POST /replay-artifacts/{date}/re-run` 路由, 接受
  `{scripts: ["validate_btst_early_runner_history", ...], params: {...}}`,
  在 worker pool 中跑并把结果写回 `replay-artifacts/`; Inspector 加 1 个
  "Re-run" 按钮 + 进度条 + 渲染回放结论。
- **预期收益**: 30 天回放实验从 1 小时 (本地 CLI) 降到 5 分钟 (UI 一键),
  让"日常可归因"成为可能 (呼应 `arch_optimize.md` §3.2)。
- **估算工作量**: M (3-5 天)
- **优先级**: P1

> 来源: `arch_optimize.md` §2 "可归因原则" + `2026-04-19-backtesting-engine-refactor.md`
> Task 5 暗示的"市场数据 / 回放"分层方向。

### 1.4 BTST 决策卡 / ONE-PAGER 双重消费入口 (S) ✅ DONE 2026-06-05
- **现状**: `scripts/run_btst_next_day_package.py` 已经支持产出
  `operator_summary.json` 与 `BTST-YYYYMMDD-ONE-PAGER.md`,
  `app/backend/routes/replay_artifacts.py` 暴露了文件读 API,
  但前端没有针对 ONE-PAGER 的渲染组件, 也没有"决策卡 ↔ 7 份文档"的双向跳转。
- **痛点**: 用户看到 ONE-PAGER 上"主票 002463", 想跳到 `BTST-LLM-*.md`
  看完整理由, 目前需要自己到文件系统翻目录。
- **改进方案**: 在 `replay-artifacts-inspector.tsx` 新增 `OnePagerView`,
  解析 ONE-PAGER 的 8 个固定问题为卡片, 每张卡提供 "展开源文档" 链接,
  跳到对应长文档锚点; 决策卡的 `action_mode=halt` 等枚举值渲染成不同
  颜色徽章。
- **预期收益**: 决策卡/ONE-PAGER 真正替代"先扫一眼哪个文件"的人工判断。
- **估算工作量**: S (1-2 天)
- **优先级**: P0
- **实施状态** (2026-06-05): 前端 `InvestmentReportDialog` 顶部新增
  `<BtstDecisionCardOnePagerTabs>` section，由 `BtstDecisionCard` (BUY/HOLD/SELL
  + 仓位估算) 和 `BtstOnePager` (8 行主问题 + 展开源文档链接) 通过 Radix
  Tabs 切换。一份 `BtstPanelData` 同时供给两个视图，零数据漂移。
  - 新增: `app/frontend/src/nodes/components/btst/{types,btst-decision-card,btst-one-pager,btst-decision-card-one-pager-tabs}.tsx`
  - 测试: `app/frontend/src/nodes/components/btst/btst.test.tsx` — 11 个 vitest
    用例覆盖数据映射、卡片渲染、Tab 切换、空数据 fallback、数据一致性。
  - 类型: TypeScript 严格模式编译通过 (`tsc --noEmit`)。

> 来源: `2026-06-03-btst-doc-decision-system-improvement-plan.md` §优化方向一 第 3 条。

### 1.5 行业暴露 / HHI / CVaR 监控面板
- **现状**: `src/portfolio/position_calculator.py` 已实现 CVaR / beta 计算,
  `src/portfolio/industry_exposure.py` 实现了申万一级行业暴露,
  `src/portfolio/correlation_cluster_helpers.py` 实现了敞口聚类,
  `src/portfolio/models.py` 暴露了 `cvar_95 / portfolio_beta / max_industry_exposure`
  三个模型字段; 但前端没有"组合级风险监控"页面, 用户需要去
  `replay-artifacts-inspector.tsx` 翻 JSON。
- **痛点**: v1.4 框架把"组合回撤 -10% 暂停新开仓、-15% 强制减仓"作为
  硬约束, 但当前 UI 无法一眼看到组合是否触发预警。
- **改进方案**: 新增 `app/frontend/src/pages/PortfolioRiskPage.tsx`,
  渲染 3 个 gauge (CVaR / HHI / Beta) + 行业敞口桑基图, 数据从
  新增的 `GET /portfolio/risk-snapshot` (聚合现有 `position_calculator` 输出)
  拉取。
- **预期收益**: 满足 v1.4 框架 §4.2 / §6.4 监控与告警的"看得见"诉求,
  把"组合回撤预警"从 7 份文档的描述变成 1 个页面。
- **估算工作量**: M (3-5 天)
- **优先级**: P1

> 来源: `institutional_multi_strategy_framework_v1.4.md` §4.2 硬约束矩阵 / §6.4
> 日常监控。

---

## 2. 待新增功能 (Add new)

### 2.1 30 天期望收益 / 风险预算 / 胜率三联卡片  ✅ DONE 2026-06-09
- **现状**: `src/research/artifacts.py` 已经把 `risk_budget_ratio`、
  `expected_edge` 等字段写入 artifact, 但当前没有任何模块把"过去 60 日该票
  在当前策略下的历史胜率 / 期望收益 / 30 天最大可能回撤"算出来。
  v1.4 框架 §8.2 把 Sortino / 胜率 / 盈亏比列为评估矩阵, 但这只在回测引擎
  里有, 没有绑定到"单只票"层面。
- **痛点**: 用户看到 1 只候选票, 最想问的就是"这策略以前买它, 平均 30 天
  赚多少, 最坏多少, 赢几次输几次"。当前必须先在 `tests/backtesting/`
  写 fixture 跑 backtest, 体验成本极高。
- **改进方案**: 新增 `src/portfolio/stock_history_expectation.py`,
  输入 `{ticker, strategy, lookback_days=60}`, 输出
  `{win_rate, avg_30d_return, worst_30d_return, n_trades}` 四元组。
  在 `InvestmentReportDialog` 顶部新增 `ExpectationCard` 渲染这三个数 +
  样本数, 样本 < 5 时打"小样本"警告 (与 v1.4 框架 §7.1 一致)。
- **预期收益**: 30 天股票发现效率直接提升 ——
  从"看 score → 拍脑袋"变成"看 score + 60 日历史实证", 这是 v1.4 框架
  §0 "目标函数: Sortino Ratio 最大化" 在单票层面的体现。
- **估算工作量**: M (3-5 天)
- **优先级**: P0
- **实施状态** (2026-06-09): 后端 `compute_stock_history_expectation()` +
  `StockHistoryExpectation` dataclass 已实现并通过 10 个单元测试。位于
  `src/portfolio/stock_history_expectation.py`, 测试于
  `tests/portfolio/test_stock_history_expectation.py`。前端 `ExpectationCard`
  组件待实施 (见 1.1 路线图)。

> 来源: `institutional_multi_strategy_framework_v1.4.md` §0 / §7.1 / §8.2,
> `2026-04-19-backtesting-engine-refactor.md` 已为 backtest 引擎搭好骨架。

### 2.2 候选池 / 评分 / 调参结果 → 用户可订阅的"调参记录流"
- **现状**: `docs/zh-cn/product/arch/dual_target_system/dual_target_implementation_plan.md`
  与 `stock_selection_mvp_design.md` §6.2 都明确说"在 Step 1/2/3 改造
  `scripts/batch_run_hedge_fund.py` 之后, 每日的候选池 / 评分 / T+1 确认
  结果应该可被研究员人工评审"。`src/screening/candidate_pool.py`、
  `strategy_scorer.py`、`signal_fusion.py` 均能落盘 artifact,
  但没有任何 UI/CLI 命令把这些 artifact 串成"30 天趋势曲线"。
- **痛点**: 研究员想回答"过去 30 日我这套候选池构建规则筛出的票, 表现
  有没有变差"时, 只能去 `data/stock/candidates/` 下手拼 CSV。
- **改进方案**: 新增 `scripts/aggregate_screening_daily_digest.py`,
  聚合过去 N 日的 `candidate_pool_*.csv` + `scored_candidates_*.csv`,
  输出 `outputs/digest/screening-{YYYYMM}.csv` (含: date, layer, n_candidates,
  avg_score, top10_realized_5d, top10_realized_30d)。前端在
  `replay-artifacts-inspector.tsx` 加 1 个 "30-day digest" tab。
- **预期收益**: 把 v1.4 框架 §7.1 "回测过拟合" + §8.3 "A/B 实验" 真正
  日常化, 不必每次都开新 notebook。
- **估算工作量**: M (3-5 天)
- **优先级**: P1

> 来源: `stock_selection_mvp_design.md` §6.2 实施路径 + v1.4 §7 / §8.3。

### 2.3 早盘"取消 / 减仓" 一键模拟器
- **现状**: v1.4 框架 §5.2 把 T+1 14:30 确认条件 + §4.3 五层退出级联 +
  §4.4 涨跌停处理协议全部定义清楚, `src/portfolio/exit_manager.py`、
  `src/portfolio/limit_handler.py`、`src/portfolio/suspension_handler.py`
  也实现了对应逻辑, 但"我当前组合 + 当前行情 → 现在该减哪只"的模拟
  入口在 web 上不存在。
- **痛点**: 用户复盘"今天该不该止损 X"时, 只能人脑模拟五层退出条件。
- **改进方案**: 新增 `app/frontend/src/pages/PositionActionSimulator.tsx`,
  调用 `GET /portfolio/simulate-exits?as_of=...`, 后端用当日收盘价 +
  ATR + 入场价 + 浮盈最高价跑五层退出 + 涨跌停协议, 返回"按 L1/L2/L2.5/
  L3/L4/L5 各应卖出多少, 净额" 的清单。
- **预期收益**: 30 天内的"少亏" = "多赚"。L1 (-7%) 早卖一天 vs 晚卖一天
  的差异对回撤影响大, 模拟器把"该不该卖"从脑算变成可点选。
- **估算工作量**: L (1-2 周)
- **优先级**: P2

> 来源: `institutional_multi_strategy_framework_v1.4.md` §4.3 / §4.4。

### 2.4 历史回放中的"信号 vs 实际成交"对比层
- **现状**: `src/backtesting/walk_forward.py`、`src/backtesting/early_runner_walk_forward.py`、
  `src/backtesting/promotion_gate.py` 都已经存在, `app/frontend/src/components/
  replay-artifacts/replay-artifacts-inspector.tsx` 能查看 artifact, 但没有
  "把历史 T 日的 T+1 确认条件 (v1.4 §5.2) 当日实际是否满足" 落到可视化对比层。
- **痛点**: 研究员复盘"为什么我 5 月那笔单亏了 8%, 是选股错了还是
  确认条件错了"时, 没有工具区分这两层 (这正是 v1.4 §5.2 注释里说
  "回测结果与实盘的偏差主要来自此处")。
- **改进方案**: 在 `replay-artifacts-inspector.tsx` 新增 "Confirm Conditions
  Replay" tab, 对历史每笔买入展示"价格支撑 / 量价配合 / 板块强度" 3 个
  条件在 T+1 当日是否满足的复盘结果, 用 traffic light 颜色标记。
- **预期收益**: 把 v1.4 §5.2 注释里"必须在模拟盘阶段重点验证"的承诺
  落到 UI, 让"回测 vs 实盘偏差"首次可视化。
- **估算工作量**: L (1-2 周)
- **优先级**: P2

> 来源: `institutional_multi_strategy_framework_v1.4.md` §5.2 注释 +
  `2026-04-19-backtesting-engine-refactor.md` 暗示的回放分离方向。

### 2.5 团队协作: 邀请码 / 用户角色的"审计 / 撤销" 闭环
- **现状**: `app/backend/auth/` 完整实现了 `auth_design.md` 的 F-01 ~ F-08
  (JWT、bcrypt、邀请码), `app/frontend/src/pages/{Login,Register,ForgotPassword,
  ResetPassword,UserSettings}Page.tsx` 5 个页面就位。但 `auth_design.md` §3.4
  + §7 描述的"管理员可撤销会话 / 强制下线 / 审计操作" 在 routes 层只看到
  `auth.py`, 没有任何 admin-only 的 audit endpoint; 前端也没有 admin console。
- **痛点**: 当研究员 A 创建一条关键策略后离职, 系统无法追溯这条策略的
  后续修改; 没有 admin UI, 只能直接动 DB。
- **改进方案**: 新增 `app/backend/routes/admin_audit.py` (`GET /admin/audit-log?since=...`,
  `POST /admin/revoke-session/{user_id}`), 前端新增 `/admin/audit` 页面,
  复用现有 `auth/dependencies.py` 中的 admin 校验。
- **预期收益**: 把"安全优先 / 操作可追溯"从 `auth_design.md` 的设计原则
  真正落到运营, 防止出现"多人用同一个 admin 密码 + 没有任何操作日志"的
  风险。
- **估算工作量**: S (1-2 天)
- **优先级**: P2

> 来源: `auth_design.md` §1.3 设计原则 + §7 安全设计。

---

## 3. 已废弃 / 应清理 (Remove / deprecate)

### 3.1 v1.0 ~ v1.2 重复的选股框架文档
- **位置**: `docs/zh-cn/product/institutional_multi_strategy_framework_v1.0.md`、
  `v1.1.md`、`v1.2.1.md` 与 `v1.3.md` 4 份文档; 同时 `stock_selection_mvp_design.md`
  与 `stock_selection_mvp_design_v0.md` 内容完全相同 (`diff` 为空)。
- **废弃原因**: 已被 v1.4 完全覆盖; 变更日志已经写明每版的修改点,
  没人会回到 v1.0 / v1.1 查内容, 但它们在搜索时会被 hit, 制造版本混乱。
- **替代方案**: 保留 v1.2.1 与 v1.3 作为历史快照, 其它移到 `docs/zh-cn/product/
  archive/` 目录; `stock_selection_mvp_design_v0.md` 直接删除。
- **风险**: 0 — 全部是产品文档, 不影响代码。

### 3.2 早期 P0 baseline / 边界 quarantine 一批 BTST 实验脚本
- **位置**: `scripts/_p0_baseline_stats.py` 28KB + `scripts/analyze_btst_5d_15pct_*.py`
  共 12 个实验性分析脚本 (Apr/May 2026)。
- **废弃原因**: 这些是 4 月 5 日 15% 边界 / baseline 冻结 阶段的产物,
  当前已被 `scripts/analyze_btst_5d_15pct_objective_monitor.py` 与
  `scripts/run_btst_top3_experiments.py` 替代; 它们还在 `__pycache__` 留下
  大量陈旧引用, 启动时偶尔报 `ModuleNotFoundError`。
- **替代方案**: 移到 `scripts/archive/2026Q2_baseline/` 子目录, README
  说明"实验性脚本, 不再维护, 仅供复盘"。
- **风险**: 低 — 仅影响命令行, 不影响 BTST 文档流或回测引擎。

### 3.3 `app/backend/AGENTS.md` 标注的 "No auth" 警告
- **位置**: `app/backend/AGENTS.md` 中 "No auth — All backend endpoints public"。
- **废弃原因**: `auth_design.md` v1.0 + `app/backend/auth/` 完整实现已经落地,
  但 `AGENTS.md` 仍写 "No auth" 误导新成员以为当前没认证, 容易把策略
  关键 API 误暴露。
- **替代方案**: 把这行更新为 "Auth required — see `app/backend/auth/`
  + `docs/zh-cn/product/auth_design.md` (v1.0 已实现, v1.1 规划中)"。
- **风险**: 0 — 文案修改, 不会改任何代码行为。

---

## 4. 实施路线图 (Roadmap)

### P0 (本月, 必须完成)
- [x] 1.1 30 天 edge 卡片端上可见 (S) ✅ DONE 2026-06-05
- [ ] 1.4 BTST 决策卡 / ONE-PAGER 双重消费入口 (S)
- [x] 2.1 单票 30 天期望收益 / 风险预算 / 胜率三联卡 (M) — 后端 2026-06-09, 前端待办

### P1 (下月)
- [ ] 1.2 Layer B/C 融合权重 UI 显式化 (M)
- [ ] 1.3 反向验证 / 解压回放一键重跑 (M)
- [ ] 1.5 行业暴露 / HHI / CVaR 监控面板 (M)
- [ ] 2.2 候选池 / 评分 30 日 digest 流 (M)

### P2 (下季度)
- [ ] 2.3 早盘"取消 / 减仓" 一键模拟器 (L)
- [ ] 2.4 历史回放中的"信号 vs 实际成交" 对比层 (L)
- [ ] 2.5 邀请码 / 角色 审计 / 撤销 闭环 (S)
- [ ] 3.1 ~ 3.3 三项清理 (合计 ≤ 1 天)

---

## 附录 A: 已审阅文档清单

| 文档 | 一句话总结 |
|------|----------|
| [auth_design.md] | 登录/注册/JWT/邀请码完整设计, v1.0 已实现, admin audit 未实现 |
| [stock_selection_mvp_design.md] | v0 选股 MVP, 三层流水线 (A/B/C) + T+1 确认, 与 v1.4 框架互补 |
| [institutional_multi_strategy_framework_v1.4.md] | 机构级四策略并行 + 五层退出 + 极端预案, 540+ 行, 主参考 |
| [arch/arch_optimize.md] | 选股/执行分离 + 可归因原则 + 可审计原则, 优化哲学 |
| [arch/dual_target_system/*] | 双目标 (研究 + 次日短线) 专题, 已落 src/targets/short_trade_target.py |
| [2026-04-19-backtesting-engine-refactor.md] | BacktestEngine God Object 拆分 (5 任务), 主要影响回测 |
| [2026-05-27-early-runner-adoption-plan.md] | 方案 A 落地: 5 步日链 + 4 层选股分级, 阶段 1~3 通过标准 |
| [2026-05-27-early-runner-scheme-a-operations.md] | scheme_a 观察期 SOP, 目录规范 + 状态判读 + 切回正式标准 |
| [2026-06-03-btst-doc-decision-system-improvement-plan.md] | v2.1 P0 4 件: operator_summary / freshness+actionability / ONE-PAGER / 统一入口 |

## 附录 B: 已识别的"文档内已有提案" (避免重复)

为避免本文与已存在的设计文档重复, 已识别以下提案已存在于上游文档,
本文档只做引用而非重写:

- `2026-06-03-*.md` P0 4 件 → 已被 `run_btst_next_day_package.py` 实现
  (search verified: `operator_summary`、`actionability_status`、
  `ONE-PAGER` 均已在该脚本出现), 不再列为本文待新增项。
- `2026-04-19-*.md` 5 个 backtesting 重构任务 → 由该 plan 自身跟进,
  不属于"产品特性"层面, 不在本文范围。
- `2026-05-27-*.md` 4 层选股分级 / 5 步日链 → 已落 `generate_btst_doc_bundle.py`,
  属于"流程规约"而非"产品 UI 特性", 不在本文范围。
- v1.4 框架 §11 策略容量估算 / §6.5 运行手册 → 属于"内部运营规范",
  不是面向终端用户的特性, 不在本文范围。

## 附录 C: 验证方法 (用于 P0 完工验收)

| 提案 | 验收测试 |
|------|----------|
| 1.1 30D Edge 卡片 | Playwright: 打开 InvestmentReportDialog, 断言出现 `expected_30d_edge`、`risk_budget_ratio`、`cvar_95` 三项 — **前端 2026-06-05 已完成** (`app/frontend/src/components/edge-card.tsx` + `app/frontend/src/nodes/components/investment-report-dialog.tsx` 30D Edge 表头排序按钮 + `app/backend/routes/hedge_fund_streaming.py` `_compute_edge_data_for_completion` 后端派生, `tests/backend/test_hedge_fund_streaming.py` 6 个新增单元测试全部通过) |
| 1.4 ONE-PAGER 入口 | Playwright: 加载某日 replay artifact, 断言 8 张固定问题卡均能渲染 |
| 2.1 30 天期望收益 | pytest unit: 给定 `tests/backtesting/fixtures/` 下的 60 日 fixture, 期望 `stock_history_expectation` 输出的 win_rate/avg_return 与手工算一致 — **后端 2026-06-09 已完成** (`tests/portfolio/test_stock_history_expectation.py` 10/10 通过) |
| 3.3 No auth 警告 | grep: `grep -R "No auth" app/` 应返回 0 命中 |

---

## 5. 补充分析: 已有功能优化建议 (2026-06-05 代码审查)

> 以下优化建议基于 `src/`、`app/`、`scripts/` 的实际代码审查, 与上面 1.1~1.5 互补,
> 聚焦于"代码有实现但存在性能瓶颈或体验问题"的场景。

### 5.1 [优化建议] 缓存键缺少 provider 维度, akshare/tushare 数据互相覆盖

- **位置**: `src/data/enhanced_cache.py` `CacheAdapter._make_key()`
- **现状**: `_make_key` 只拼接 `f"{prefix}:{identifier}"` (如 `prices:000001`),
  不区分 akshare 与 tushare 两条数据路径。`src/tools/akshare_api.py` 和
  `src/tools/tushare_api.py` 都有 `get_prices` / `get_financial_metrics` 同名函数,
  当 `src/data/router.py` 根据 `ashare_data_sources` 配置切换 provider 时,
  新 provider 的数据会覆盖旧 provider 的缓存条目, 导致:
  - A-share 与 US 数据格式不一致时反序列化失败
  - 研究员切换 provider 后拿到的是旧 provider 的缓存数据
- **改进方案**: `_make_key` 改为 `f"{prefix}:{provider}:{identifier}"`,
  `CacheAdapter` 的 `get_*` / `set_*` 方法增加可选参数 `provider: str | None = None`,
  未传 provider 时从 `src/data/router.py` 的当前活跃 provider 推断。
- **预期收益**: 消除 provider 切换时的缓存污染, 同时为未来"多数据源对比"打下基础。
- **估算工作量**: S (1-2 天)
- **优先级**: P1

> 来源: 代码审查 `src/data/enhanced_cache.py` L544-596。

### 5.2 [优化建议] score_batch 的 N+1 IO 模式拖慢 Layer B 全量评分

- **位置**: `src/screening/strategy_scorer.py` `_build_provisional_ranking()` → `_compute_light_signals()` → `_load_price_frame()`
- **现状**: `score_batch()` 对 ~160 只候选股逐一调用 `_load_price_frame()` (单只 400 日 K 线),
  每次调用 `get_prices(ticker=...)` → `prices_to_df(prices)`, 内部是同步 HTTP 请求。
  160 只 * 1 次 HTTP = 160 次串行网络 IO, 即使 tushare/akshare 有缓存,
  冷启动场景下单次 `score_batch` 耗时 3~5 分钟。
  同时 `_build_indtraday_short_trade_metrics` 内部又对 top 12 只做
  `get_intraday_bars` + `get_intraday_ticks`, 也是串行。
- **改进方案**: 在 `_build_provisional_ranking` 中用 `concurrent.futures.ThreadPoolExecutor(max_workers=4)`
  并行加载价格数据。tushare 的 `get_daily_price_batch` 已有批量接口,
  可以一次性拉全市场日线再按 ticker 过滤, 跳过 160 次单只调用。
- **预期收益**: Layer B 评分冷启动从 3~5 分钟降到 30 秒以内。
- **估算工作量**: M (3-5 天)
- **优先级**: P0

> 来源: 代码审查 `src/screening/strategy_scorer.py` L556-567。

### 5.3 [优化建议] 缓存命中率与数据质量无 UI 呈现, 问题"黑箱"化

- **位置**: `src/data/enhanced_cache.py` `get_cache_stats()` + `src/data/validator_v2.py` `ValidationReport`
- **现状**: `get_cache_stats()` 已经在内存中维护了完整的 `_stats` 字典
  (lru_hits / redis_hits / disk_hits / misses / sets / hit_rate),
  `get_cache_runtime_info()` 甚至能查 disk 路径和条目数。
  但这些数据只被 `tests/` 引用, 不写入 `llm_metrics` JSONL, 也不暴露为 API。
  同时 `src/data/validator_v2.py` 的 `EnhancedDataValidator` 会输出 `ValidationReport`
  (total / passed / failed / warnings / pass_rate / errors_list),
  但前端和 CLI 都没有"今天哪几只票数据被拒"的入口。
- **改进方案**: (1) 在 `src/monitoring/llm_metrics.py` 中新增 `record_cache_snapshot()`
  函数, 每次回测/流水线完成后把 cache stats 追加到同一 JSONL。
  (2) 新增 `GET /system/cache-stats` 和 `GET /system/data-quality?date=...` 两个后端路由,
  前端在 `settings` tab 下加"数据健康"子页。
- **预期收益**: 研究员首次遇到"为什么这只票没有评分"时, 能在 10 秒内确认
  "是数据被拒还是缓存未命中", 而不是翻日志。
- **估算工作量**: S (1-2 天)
- **优先级**: P1

> 来源: 代码审查 `src/data/enhanced_cache.py` L514-525, `src/data/validator_v2.py` L11-33。

### 5.4 [优化建议] 投资报告 agent 信号展示无"矛盾高亮", 关键分歧需人工比对

- **位置**: `app/frontend/src/nodes/components/investment-report-dialog.tsx` L163-220
- **现状**: `Accordion` 按 ticker 展开, 内部按 agent 列表逐个展示 signal badge
  (bullish/bearish/neutral) + confidence badge。但:
  - agent 排列顺序由 `agents` 数组决定, 该数组来自 `Object.keys(analyst_signals)`,
    字典插入顺序可能跨运行不一致。
  - 当 bullish/bearish 各有 5+ agent 时, 用户需要逐条扫读才能发现"谁是少数派"。
  - 缺少"矛盾高亮": 如技术面 strongly bullish 但基本面 strongly bearish 的 ticker
    应在 ticker 行级别标黄/标红。
- **改进方案**: (1) 在 `AccordionTrigger` 的 ticker 行新增一个 mini bar chart:
    3 个色块 (红/灰/绿), 宽度按 bullish/neutral/bearish 人数比例。
  (2) 当同一 ticker 有 2+ 个 confidence > 70 的 agent 方向相反时,
    `AccordionTrigger` 加 `ring-2 ring-amber-500` 边框。
  (3) agent 排列改为固定顺序 (用 `ANALYST_ORDER`)。
- **预期收益**: 从"逐条扫 20 个 agent" 降到 "3 秒看 mini bar + 只展开标红 ticker"。
- **估算工作量**: S (1-2 天)
- **优先级**: P1

> 来源: 代码审查 `app/frontend/src/nodes/components/investment-report-dialog.tsx` L97-101, L163-220。

### 5.5 [优化建议] 回测 CLI 缺少"批量参数对比"模式, walk-forward 需反复手动执行

- **位置**: `src/backtesting/cli.py` + `src/main.py`
- **现状**: `backtester` 支持 `--walk-forward-preset` (5 个预设),
  也支持 A/B compare (`--ab-compare`), 但研究员最常见的工作流是:
  "同一只票, lookback 30d vs 60d, 看 Sharpe 差多少" ——
  这需要手动跑 2 次 backtester, 手工对比 2 个 JSON 文件。
  `--ab-compare` 只做"规则 A vs 规则 B"的 walk-forward,
  不做"同规则不同参数"的网格对比。
- **改进方案**: 新增 `--param-grid` 模式, 接受 JSON 文件:
  ```json
  {"lookback_days": [30, 60, 90], "score_threshold": [0.30, 0.35, 0.40]}
  ```
  自动做笛卡尔积, 每组参数跑一次 backtest, 最终输出一个 CSV:
  `lookback_days, score_threshold, sharpe, max_drawdown, win_rate, total_return`。
  可复用现有 `BacktestEngine` + `run_walk_forward` 基础设施。
- **预期收益**: 参数调优从 "跑 N 次命令 + 手动整理 Excel" 降到 "一条命令 + 一个 CSV"。
- **估算工作量**: M (3-5 天)
- **优先级**: P1

> 来源: 代码审查 `src/backtesting/cli.py` L25-80, `src/backtesting/param_search.py` (已有骨架但未暴露为 CLI)。

### 5.6 [优化建议] 317 个 scripts/ 文件缺乏索引, 新人上手成本极高

- **位置**: `scripts/` 目录 (317 个 .py 文件)
- **现状**: 目录下有 317 个 Python 脚本, 绝大多数是 BTST 分析/实验脚本,
  命名模式为 `analyze_btst_*` / `run_btst_*` / `validate_*`,
  但没有 `scripts/README.md` 或 `scripts/INDEX.md` 告诉用户:
  - 哪些是"日常使用"的脚本 (如 `run_btst_next_day_package.py`)
  - 哪些是"一次性实验" (如 `analyze_btst_5d_15pct_boundary_quarantine.py`)
  - 各脚本的输入/输出是什么
  提案 3.2 建议归档到 `scripts/archive/`, 但归档不能替代"可发现的索引"。
- **改进方案**: (1) 在 scripts 下新增 `README.md`, 列出 ~20 个核心脚本的
  名称 / 用途 / 输入 / 输出, 分为 "日常使用" / "回测验证" / "数据管理" 三类。
  (2) 其余 ~300 个实验脚本加文件头注释 `# Status: archived / experimental / active`,
  便于 grep 过滤。
- **预期收益**: 新成员从 "不知道该运行哪个脚本" 到 "5 分钟找到正确的入口"。
- **估算工作量**: S (1 天)
- **优先级**: P2

> 来源: `ls scripts/ | wc -l` = 317, 与提案 3.2 互补 (归档解决 "噪音", 索引解决 "发现")。

---

## 6. 补充分析: 新功能提案 (2026-06-05 代码审查)

> 以下提案与 2.1~2.5 不重叠, 聚焦于"当前代码完全没有覆盖"的能力缺口。

### 6.1 数据源健康看板与自动降级
- **现状**: `src/data/router.py` 支持按 `ashare_data_sources` 配置切换 provider,
  `src/data/health_checker.py` 存在但只在内部使用。
  当 tushare 接口限流 (每分钟 200 次) 或 akshare 返回空 DataFrame 时,
  `strategy_scorer.py` 和 `candidate_pool.py` 会静默返回空数据,
  导致评分偏低但不报错。研究员无法区分"这只票确实没数据"和"数据源挂了"。
- **痛点**: 用户花 30 分钟跑完一次 `--screen-only`, 拿到 0 只候选,
  最后发现是 tushare token 过期, 浪费时间。
- **改进方案**: (1) `src/data/health_checker.py` 每次调用 provider 时记录
  `{provider, endpoint, latency_ms, success, error_type, timestamp}` 到内存环形缓冲区。
  (2) 新增 `GET /system/data-sources/health` 路由, 返回最近 100 次调用的成功率/延迟。
  (3) 当某 provider 成功率 < 80% 时自动降级到备用 provider, 并在 CLI/Web 上显示
  黄色警告 "tushare 成功率 72%, 已切换 akshare"。
- **预期收益**: 消除"静默数据缺失"导致的无谓空跑, 让"数据源是否可用"在运行前就可见。
- **估算工作量**: M (3-5 天)
- **优先级**: P1

> 来源: 代码审查 `src/data/router.py`, `src/data/health_checker.py`,
> `src/screening/strategy_scorer.py` L125-131 (`_load_price_frame` 静默返回空)。

### 6.2 每日选股结果与实际走势的"30 天回顾"自动对标
- **现状**: 提案 2.4 聚焦于"信号 vs 实际成交"的回放层, 但缺少一个更基础的闭环:
  "30 天前选出的 top 10 候选, 实际涨了多少"。`src/research/artifacts.py`
  已经把每日的 `selection_artifact` 落盘, `src/portfolio/stock_history_expectation.py`
  能算单票历史期望, 但没有任何模块把这两个能力串起来:
  "取出 30 天前的 selection_artifact → 拉这 10 只票的后 30 天走势 → 算 hit rate"。
- **痛点**: 研究员验证"这套选股策略过去 3 个月有没有效"时,
  只能写临时脚本从 `data/snapshots/` 读 artifact 再手动对标行情。
- **改进方案**: 新增 `src/research/lookback_audit.py`:
  输入 `{audit_date, lookforward_days=30}`,
  自动读取 `audit_date` 的 selection_artifact 拿到 top N ticker,
  调 `get_prices()` 拉后 30 天走势, 输出:
  `{ticker, entry_price, exit_price_30d, return_pct, max_drawdown, vs_hs300}` 列表。
  暴露为 `GET /research/lookback-audit?date=YYYYMMDD&days=30`。
- **预期收益**: 把"策略有没有效"从"写脚本算"变成"点一下看表",
  直接提升用户对系统的信任度和调参动力。
- **估算工作量**: M (3-5 天)
- **优先级**: P0

> 来源: 代码审查 `src/research/artifacts.py` (已有 selection artifact),
> `src/portfolio/stock_history_expectation.py` (已有单票期望)。
> 与提案 2.2 (digest 流) 互补: 2.2 做的是候选池统计趋势, 本提案做的是选股结果 vs 实际收益对标。

### 6.3 组合归因面板: "钱赚在哪里 / 亏在哪里"
- **现状**: 提案 1.5 聚焦于"组合级风险监控" (CVaR / HHI / Beta gauge),
  但缺少一个更直观的功能: "过去 N 天的组合收益, 有多少来自选股,
  有多少来自仓位管理, 有多少来自市场 beta"。
  `src/backtesting/metrics.py` 已实现 Sharpe / Sortino / max_drawdown 等指标,
  `src/backtesting/valuation.py` 有 `compute_exposures()`,
  但没有把"收益分解"做到 ticker × agent 维度。
- **痛点**: 用户看到组合月度 +8% 回报, 但不知道:
  这 8% 里 A 股贡献多少、选股 alpha 贡献多少、仓位杠杆贡献多少。
  调参时无法判断"该优化选股还是该优化仓位"。
- **改进方案**: 新增 `src/portfolio/return_attribution.py`:
  输入 `{start_date, end_date, portfolio_snapshots: list}`,
  用 Brinson 模型拆分为:
  - 配置贡献 (超配/低配行业)
  - 选股贡献 (行业内选股 alpha)
  - 交互贡献
  输出到 `GET /portfolio/attribution?start=...&end=...`。
  前端新增 `AttributionPage.tsx`, 用瀑布图展示。
- **预期收益**: 让调参决策从"凭直觉改权重"变成"看归因图决定优化方向"。
- **估算工作量**: L (1-2 周)
- **优先级**: P2

> 来源: 代码审查 `src/backtesting/metrics.py`, `src/backtesting/valuation.py`。
> 与提案 1.5 互补: 1.5 是风险监控, 本提案是收益归因。

### 6.4 LLM 调用成本与延迟的"热力图"面板
- **现状**: `src/monitoring/llm_metrics.py` 已经记录了每次 LLM 调用的
  `{provider, model, agent, duration_ms, prompt_chars, response_chars}`,
  写入 `logs/llm_metrics_*.jsonl`。`scripts/summarize_llm_metrics.py`
  能生成 CLI 摘要。但:
  - 没有按 agent 维度的"成本热力图" (哪些 agent 最贵/最慢)
  - 没有按 provider 维度的"可用性时间线" (哪个 provider 最近经常超时)
  - 数据只存在于 JSONL 文件, 没有 API / UI 消费入口
- **痛点**: 运行一次完整流水线 (20 agents × 3 tickers) 花费 $0.5~2,
  用户无法知道"哪几个 agent 占了 80% 的成本"以及"能否用更便宜的模型替代"。
- **改进方案**: (1) 新增 `GET /system/llm-metrics/summary?last_n_sessions=10`,
  聚合最近 N 次运行的 cost / latency / error_rate 按 agent/provider 分组。
  (2) 前端在 settings 下新增 `LLM Metrics` 子页, 用 bar chart 展示
  top-10 最贵 agent + top-5 最慢 provider + 最近 24h error spike 时间线。
  (3) 增加一个 "cost saving suggestion" 卡片:
  "warren_buffett agent 平均 4s / $0.08, 可考虑用 Haiku 替代以节省 60%"。
- **预期收益**: 让 LLM 成本从"月底看账单才知道"变成"每次运行后可见"。
- **估算工作量**: M (3-5 天)
- **优先级**: P2

> 来源: 代码审查 `src/monitoring/llm_metrics.py`, `scripts/summarize_llm_metrics.py`。

---

## 7. 优化后实施路线图 (合并 2026-06-05 新提案)

### P0 (本月, 必须完成)
- [x] 1.1 30 天 edge 卡片端上可见 (S) ✅ DONE 2026-06-05
- [ ] 1.4 BTST 决策卡 / ONE-PAGER 双重消费入口 (S)
- [x] 2.1 单票 30 天期望收益 / 风险预算 / 胜率三联卡 (M) — 后端 2026-06-09, 前端待办
- [x] 5.2 score_batch N+1 IO 并行化 (M) — 性能瓶颈 ✅ DONE 2026-06-05
- [x] 6.2 每日选股结果 30 天回顾自动对标 (M) — 核心闭环 ✅ DONE 2026-06-05

### P1 (下月)
- [ ] 1.2 Layer B/C 融合权重 UI 显式化 (M)
- [ ] 1.3 反向验证 / 解压回放一键重跑 (M)
- [ ] 1.5 行业暴露 / HHI / CVaR 监控面板 (M)
- [ ] 2.2 候选池 / 评分 30 日 digest 流 (M)
- [x] 5.1 缓存键增加 provider 维度 (S) ✅ DONE 2026-06-05
- [ ] 5.3 缓存命中率与数据质量 UI 呈现 (S)
- [ ] 5.4 投资报告矛盾高亮 + agent 排序 (S)
- [ ] 5.5 回测批量参数对比模式 (M)
- [ ] 6.1 数据源健康看板与自动降级 (M)

### P2 (下季度)
- [ ] 2.3 早盘"取消 / 减仓" 一键模拟器 (L)
- [ ] 2.4 历史回放中的"信号 vs 实际成交" 对比层 (L)
- [ ] 2.5 邀请码 / 角色 审计 / 撤销 闭环 (S)
- [ ] 3.1 ~ 3.3 三项清理 (合计 <= 1 天)
- [x] 5.6 scripts/ 目录 README 索引 (S) ✅ DONE 2026-06-05
- [ ] 6.3 组合归因面板 (L)
- [ ] 6.4 LLM 调用成本热力图面板 (M)
