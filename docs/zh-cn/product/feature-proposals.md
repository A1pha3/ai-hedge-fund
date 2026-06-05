# 特性提案 (Feature Proposals)

> 最近更新: 2026-06-05
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

### 1.4 BTST 决策卡与 ONE-PAGER 的双重消费入口
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

### 2.1 30 天期望收益 / 风险预算 / 胜率三联卡片
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
- [ ] 1.1 30 天 edge 卡片端上可见 (S)
- [ ] 1.4 BTST 决策卡 / ONE-PAGER 双重消费入口 (S)
- [ ] 2.1 单票 30 天期望收益 / 风险预算 / 胜率三联卡 (M)

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
| 1.1 30D Edge 卡片 | Playwright: 打开 InvestmentReportDialog, 断言出现 `expected_30d_edge`、`risk_budget_ratio`、`cvar_95` 三项 |
| 1.4 ONE-PAGER 入口 | Playwright: 加载某日 replay artifact, 断言 8 张固定问题卡均能渲染 |
| 2.1 30 天期望收益 | pytest unit: 给定 `tests/backtesting/fixtures/` 下的 60 日 fixture, 期望 `stock_history_expectation` 输出的 win_rate/avg_return 与手工算一致 |
| 3.3 No auth 警告 | grep: `grep -R "No auth" app/` 应返回 0 命中 |
