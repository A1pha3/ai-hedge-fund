# 产品功能提案清单 (R20.19 精简索引版)

> **目标**: 让用户更高效地找到未来 30 天最有投资价值的 A 股标的。
>
> **本版本变更 (R20.19 → R20.38)**: 主文档已从 933 行重构为路由式索引。当前主文档仅保留活跃路线图、关键完成态与维护规则；详细审查档案继续外置到 [`changelog/r20-audit-history.md`](./changelog/r20-audit-history.md)。
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
| **R20.1-R20.18 审查档案** | [changelog/r20-audit-history.md](./changelog/r20-audit-history.md) | 各轮 alpha/beta/gamma 审查完整记录 (bug 清单 + 重构 + 业界对标) |
| **已实现功能矩阵** (全景) | [features/MATRIX.md](./features/MATRIX.md) | §1-§9 全部已实现功能 (含 9 个子文档路由) |
| **优化功能 & 新功能提案** | [features/optimizations.md](./features/optimizations.md) | §10-§11 P0/P1/P2 待优化与新功能提案 + 实现细节 |
| **CLI 速查表 + 快速开始** | [QUICKSTART.md](./QUICKSTART.md) | §16 + §18 CLI 命令 + 快速入门 |
| **changelog v2.1.0-v2.1.7** | [changelog/v2.1.0-v2.1.7.md](./changelog/v2.1.0-v2.1.7.md) | §15 v2.0-v2.1.7 版本里程碑 |
| **changelog v2.1.8 之后** | [changelog/v2.1.8-onwards.md](./changelog/v2.1.8-onwards.md) | R20.8 文档拆分 + 后续轮次 |
| **R20.6 调研 + 差距分析** | [research/r20.6-roadmap-gap-analysis.md](./research/r20.6-roadmap-gap-analysis.md) | §19 业界动态 + Gap + 优先级建议 |
| **业界 2025-2026 调研** | [research/industry-2025-2026.md](./research/industry-2025-2026.md) | 聚宽/米筐/同花顺/FinGPT 等对标 |
| **R20.31 Phase 5 调研** | [research/r20-31-next-phase-analysis.md](./research/r20-31-next-phase-analysis.md) | 全功能完成后的差距分析 + P3-1~P3-4 提案 |
| **UX 最佳实践 + R20.9 审计** | [research/ux-best-practices-2025-2026.md](./research/ux-best-practices-2025-2026.md) | 前端 UX 问题清单 + 行业趋势 |

---

## 一、活跃需求清单 (R20.19)

> R20.7 之后后端 100% 完成。R20.11+ 新增的 CLI 决策工具链已全部落地。

### P0 — 已全部完成 ✅

| # | 功能 | 状态 | CLI |
|---|------|------|-----|
| P0-7 | 盘前 5 分钟「今日 Top 3 决策卡」 | ✅ DONE R20.11 | `--daily-brief` |
| P0-8 | 信号冲突透明化 `--why-not` | ✅ DONE R20.11 | `--why-not <ticker>` |
| P0-9 | 置信度校准 (score → 历史命中率) | ✅ DONE R20.17 | `--confidence-calibration` |
| P0-10 | 数据质量审计 (completeness) | ✅ DONE R20.17 | `--data-quality-audit` |
| P0-11 | 综合信心排名 (4 信号融合) | ✅ DONE R20.18 | `--conviction-ranking` |

### P1 — 已全部完成 ✅

| # | 功能 | 现状 | 改进方案 |
|---|------|------|----------|
| P1-6 | **组合风险预警仪表盘 (前端集成)** | ✅ DONE R20.28 (live section: VaR 95/99 + CVaR 99 + 回撤预警线 + 行业集中度 + Beta) | 后端 `GET/POST /api/portfolio/risk-snapshot` + 前端 `risk-snapshot-api.ts` + `LiveRiskSnapshotSection` |
| P1-13 | 条件单模板券商导出 | ✅ DONE R20.13 | `--export-conditional-orders --broker=huatai\|gtja\|ths` |

### P2 — 前端集成 ✅ 全部完成

| # | 功能 | 现状 |
|---|------|------|
| P2-1 | Agent 推理过程可视化 | ✅ DONE R20.16 |
| P2-2 | 回测参数对比面板 (前端) | ✅ DONE R20.33: service layer (`param-compare-api.ts`) + 展示组件 (`param-compare-panel.tsx`) + 后端 `GET/POST /api/backtest/param-compare` |
| P2-5 | 自定义策略权重 (前端滑块) | ✅ DONE R20.30 (端到端) |
| P2-6 | 标的分析详情页 (前端) | ✅ DONE R20.31: 4-Tab 深度分析 (基本面/技术面/资金面/系统历史) + 点击推荐行拉取详情 |
| P2-7 | 回测场景回放 (前端) | ✅ ReplayArtifactsWorkspace 已实现 (R20.13+, 8 vitest); 逐日回放 + 信号-交易对比 + 反馈 |
| P2-9 | 宏观数据集成 (前端) | ✅ DONE R20.31: service (`macro-snapshot-api.ts`) + 仪表盘 (`macro-dashboard.tsx`: 7 指标 + 3 派生标签); 15 vitest |
| P2-10 | 「组合体检」周报推送 | ✅ DONE R20.13 |

---

## 二、CLI 决策工具链 (完整闭环)

R20.11-R20.18 构建的端到端选股决策工作流:

```
--auto                     找票 (全市场扫描 + Top N)
   ↓
--conviction-ranking       排序 (Score + 连续 + 质量 + 历史命中率 综合排名)
   ↓
--data-quality-audit       验证 (推荐背后数据是否完整)
   ↓
--confidence-calibration   验证 (相似 score 历史命中率/预期收益)
   ↓
--why-not <ticker>         复查 (某只票为何未被推荐)
   ↓
--daily-brief              盘前 (9:25 前 Top 3 决策卡)
```

### R20.31 闭环验证与策略进化 (Phase 5 CLI)

```
--verify-recommendations   闭环 (过去 N 天推荐实际收益 + 策略归因)
   ↓
--cross-picks              行业+个股交叉选择 (强势行业 Top N + 行业最优个股)
   ↓
--build-portfolio          组合构建 (Top N → 优化权重 + 行业/单股约束)
   ↓
--calibrate-weights        策略权重校准 (基于因子 IC 自动调权)
```

### R20.37 信号精度增强 CLI

```
--signal-momentum          信号动量 (score_b 3-5日轨迹, 识别改善/衰减)
   ↓
--sector-strength          行业轮动加权 (强势行业加分, 弱势行业减分)
   ↓
--volume-confirm           量价确认 (放量确认/缩量背离检测)
   ↓
--composite-score          综合信心评分 (5因子融合, A-F评级)
   ↓
--top-picks                一键买点 (今日最佳 Top N, 零学习成本)
```

业界对标: Numerai / QuantConnect / 聚宽 / 米筐 / 同花顺。我们的差异化: 20-agent persona 架构 + 完整可解释性链 + 端到端闭环验证。

---

## 三、优先级路线图 (R20.19 更新)

### Phase 1-3: CLI 决策链 — ✅ 100% 完成 (R20.11-R20.18)

P0-7/8/9/10/11 + P1-13 + P2-1/10 全部 DONE。

### Phase 4: 前端集成 — ✅ 100% 完成

所有前端功能已完成 (P2 全部 ✅, P1-6 ✅ R20.28)。

### Phase 5: 闭环验证与策略进化 (R20.31 提案)

详见 [research/r20-31-next-phase-analysis.md](./research/r20-31-next-phase-analysis.md)。

| # | 功能 | 优先级 | 状态 |
|---|------|--------|------|
| P3-1 | 推荐闭环验证 (`--verify-recommendations`) | P0 | ✅ DONE R20.31: `src/screening/verify_recommendations.py` + CLI; 16 pytest |
| P3-2 | 策略动态权重校准 | P1 | ✅ DONE R20.31: `src/research/weight_calibration.py` (基于 IR 自动调权 + 权重下限 + 校准前后对比); 15 pytest |
| P3-3 | 行业 + 个股交叉选择 | P1 | ✅ DONE R20.31: `src/screening/industry_cross_picks.py`; 12 pytest |
| P3-4 | 推荐组合构建器 | P2 | ✅ DONE R20.31: `src/portfolio/builder.py` (贪心算法 + 行业/单股双约束 + 预期 Sharpe vs 等权对比); 14 pytest |

### Phase 6: 选股精度增强 (R20.32 提案)

| # | 功能 | 优先级 | 状态 |
|---|------|--------|------|
| P4-1 | **行业内相对强度** — 标的 score_b 相对同行业百分位排名, 解决"绝对分相同但行业强弱不同"问题 | P1 | ✅ DONE R20.32: `signal_fusion._compute_relative_strength()` + `metrics["industry_relative_strength"]`; 8 pytest |
| P4-2 | **智能再入场信号** — 曾被推荐 (score_b≥0.3) 后消失又重返的标的, 获中等 bonus (5.0), 高于首次出现 (0.0) 低于连续 3 天 (10.0) | P1 | ✅ DONE R20.32: `RecommendationStatus.REENTRY_SIGNAL` + `stability_bonus=5.0`; 5 pytest |

### Phase 7: 回测精度修复 (R20.32 提案)

| # | 功能 | 优先级 | 状态 |
|---|------|--------|------|
| P4-3 | **A 股最低佣金 5 元/笔** — 小额交易回测从 < ¥0.25 修正到 ¥5, 反映实际成本 | P0 | ✅ DONE R20.32: `_apply_commission_floor()` + `TradingConstraints.commission_floor_yuan=5.0`; 11 pytest |
| P4-4 | **印花税更新至 0.05%** — 自 2023-08-28 起中国印花税从 0.1% 降至 0.05%, 卖出回测现在反映实际成本 | P0 | ✅ DONE R20.32: `TradingConstraints.stamp_duty_rate` default 0.001 → 0.0005 |
| P4-5 | **停牌股票检测** — `volume=0` 的标的 (停牌) 不再被回测引擎按 carry-forward 价格虚拟成交 | P0 | ✅ DONE R20.32: `engine_market_data.load_current_prices` 跳过零成交量; 6 pytest |
| P4-6 | **executor atexit 清理** — `_SHARED_TIMEOUT_EXECUTOR` 注册 atexit 清理, 非守护线程不再延迟进程退出 | P2 | ✅ DONE R20.32: `atexit.register(executor.shutdown, wait=False)` |

### Phase 8: 30 天目标对齐 (R20.33 审计提案)

| # | 功能 | 优先级 | 状态 |
|---|------|--------|------|
| P5-1 | **30 天闭环验证扩展** — 把 `--verify-recommendations` / `--confidence-calibration` 的验证口径从 T+1/T+3/T+5 扩到 T+10/T+20/T+30 | P0 | ✅ DONE R20.34: 修复 `tracking_history.json` 读取契约, 并补齐 `--tracking-summary` / `--confidence-calibration` 的 T+10/T+20/T+30 输出 |
| P5-2 | **时序行业轮动增强** — 让 `industry_rotation.py` 基于真实 lookback 窗口而不是单日快照，优先服务未来 30 天胜率/赔率 | P1 | ✅ DONE |

### Phase 9: 数据质量与推荐体验增强 (R20.35 提案)

> **目标**: 确保推荐基于新鲜完整的数据，并让用户快速掌握推荐变化。

| # | 功能 | 优先级 | 状态 |
|---|------|--------|------|
| P6-1 | **数据新鲜度守门员** — `--auto` 运行时自动检测数据时效性 (行情/财务/行业), 过期数据触发警告并降低推荐置信度 | P1 | ✅ DONE R20.35: `src/screening/data_freshness_guard.py` + `--check-freshness` CLI; 12 pytest |
| P6-2 | **推荐日间变动摘要** — 每日 `--auto` 后自动生成与上一交易日的推荐对比 (新增/移除/分数变动), `--daily-delta` CLI | P1 | ✅ DONE R20.35: `src/screening/daily_delta.py` + `--daily-delta` CLI; 19 pytest |

### Phase 10: 信号质量自校验 (R20.35 提案)

> **目标**: 通过内部信号一致性校验和动态推荐阈值，提升选股准确性和自适应性。

| # | 功能 | 优先级 | 状态 |
|---|------|--------|------|
| P7-1 | **信号一致性交叉校验** -- 多策略信号方向冲突时标记为低置信度, 帮助用户规避内部不确定的标的 | P1 | ✅ DONE R20.35: `src/screening/signal_consistency.py` + `--signal-consistency` CLI; 11 pytest |
| P7-2 | **动态推荐阈值** -- 根据近 N 天推荐胜率自动调整 score_b 阈值: 输多则变严, 赢多则放松, 自我修正 | P1 | ✅ DONE R20.35: `src/screening/dynamic_threshold.py` + `--dynamic-threshold` CLI; 12 pytest |

### Phase 11: 用户体验增强 (R20.35 提案)

> **目标**: 一键完成决策链, 并自动检测异常推荐。

| # | 功能 | 优先级 | 状态 |
|---|------|--------|------|
| P8-1 | **一键决策流水线** -- `--decision-flow` 单命令串联: 选股→新鲜度→一致性→阈值→变动 | P1 | ✅ DONE R20.35: `src/screening/decision_flow.py`; 3 pytest |
| P8-2 | **推荐异常值检测** -- 检测 score_b 日间剧变 (>=30%), 标记潜在数据质量问题 | P1 | ✅ DONE R20.35: `src/screening/outlier_detect.py` + `--outlier-detect` CLI; 11 pytest |

### Phase 12: 预期收益与决策整合 (R20.36 提案)

> **目标**: 让用户直接看到每只推荐的预期收益, 并通过一键流水线获得完整可执行的决策。
>
> **差距分析**: 系统已有 score_b 排名和置信度校准, 但缺少"预期收益"直接展示。用户需要运行多个 CLI 命令才能获得完整决策。Phase 12 补齐这两个关键缺口。

| # | 功能 | 优先级 | 状态 |
|---|------|--------|------|
| P9-1 | **预期收益估算** — 基于历史 score_b 分桶的 T+1/T+5/T+10/T+20/T+30 实际收益, 为每只推荐估算预期收益; 展示"历史同分位平均收益"让用户量化预期 | P1 | ✅ DONE R20.36；R20.38 起默认强调 T+20/T+30 posterior edge |
| P9-2 | **决策流水线整合** — 增强 `--decision-flow` 集成异常检测 (P8-2) + 预期收益 (P9-1), 输出"今日 Top N 可执行决策卡" | P1 | ✅ DONE R20.36 |

### Phase 13: 选股精度增强 — 动量与行业整合

> **目标**: 通过信号动量和行业轮动加权, 直接提升选股准确性和组合质量。
>
> **差距分析**: 系统已有 score_b 排名和连续推荐追踪, 但缺少「信号趋势方向」(动量) 和「自上而下行业强度」的整合。一只 score_b 从 0.3 持续上升到 0.5 的标的, 比一直停留在 0.5 的更有价值; 同样, 强势行业中的标的比弱势行业中的更有可能跑赢大盘。

| # | 功能 | 优先级 | 状态 |
|---|------|--------|------|
| P10-1 | **信号动量评分** — 跟踪每只推荐标的 score_b 的 3-5 日轨迹 (线性回归斜率), 识别信号"持续改善"vs"正在衰减"的标的; 动量 bonus 融入 conviction_ranking | P0 | ✅ DONE R20.37: `src/screening/signal_momentum.py` + `--signal-momentum` CLI; 29 pytest |
| P10-2 | **行业轮动加权** — 利用 industry_rotation 行业动量, 对强势行业标的施加 +0.05 加分, 弱势行业 -0.05 惩罚; 实现自上而下(行业)与自下而上(个股)的综合评分 | P1 | ✅ DONE R20.37: `src/screening/sector_strength.py` + `--sector-strength` CLI; 13 pytest |

### Phase 14: 综合信心评分与量价确认

> **目标**: 将所有独立信号融合为单一可操作评分, 并通过量价确认提升信号可靠性。
>
> **差距分析**: 用户需要在多个指标(score_b, 动量, 行业强度, 一致性)之间手动判断。量价背离是经典技术分析原则, 但系统未检查成交量是否支持价格信号。Phase 14 补齐两个关键缺口。

| # | 功能 | 优先级 | 状态 |
|---|------|--------|------|
| P11-1 | **综合信心评分** — 融合 score_b + 动量bonus + 行业bonus + 一致性adj + 量价factor 为单一 composite_score (A-F 评级), 用户一眼判断最佳标的; `--decision-flow` 扩展为 10 步 | P0 | ✅ DONE R20.37: `src/screening/composite_score.py` + `--composite-score` CLI; 13 pytest |
| P11-2 | **量价确认信号** — 检测成交量是否支持价格信号: 放量确认(+0.03) / 缩量背离(-0.03) / 中性; 融入 composite_score | P1 | ✅ DONE R20.37: `src/screening/volume_confirmation.py` + `--volume-confirm` CLI; 17 pytest |

### Phase 15: 极简决策入口 (R20.37 提案)

> **目标**: 让用户一个命令获得今日最佳买点, 不需要理解 10 步决策流。
>
> **差距分析**: 系统功能丰富但入口复杂。用户需要记住 `--auto` → `--decision-flow` → `--composite-score` 等一系列命令。Phase 15 提供"一键买点"入口, 并在 `--auto` 中直接展示综合评分。

| # | 功能 | 优先级 | 状态 |
|---|------|--------|------|
| P12-1 | **`--auto` 默认排序切到 investability ranking** — 在原始 `score_b` 透明展示不变的前提下, 让 top tranche 默认按 composite_score + T+30 posterior edge + 胜率/样本量重排 | P0 | ✅ DONE R20.38: `compute_auto_screening_results()` 现对候选 tranche 做可投资性重排, `score_b` 保留为基础分 |
| P12-2 | **`--top-picks` 一键买点** — 单命令输出今日 Top N 最佳买点 (composite_score + A-F评级 + 信号解读), 零学习成本 | P0 | ✅ DONE R20.37；R20.38 起附带 T+30 预期收益 / 胜率 / 样本量证据 |

### Phase 16: 30 天 investability 决策收敛 (R20.38)

> **目标**: 不再让用户在 `score_b`、composite、校准、追踪摘要之间手工拼接，默认前门直接围绕“未来 30 天最值得买的票”输出可投资证据。
>
> **设计原则**:
> - 优先复用既有能力，不再新增独立入口
> - 默认展示长周期 posterior edge，而不是只强调短周期收益
> - 保留原始 `score_b` 透明度，但默认排序与决策说明统一收敛到 investability 口径

| # | 功能 | 优先级 | 状态 |
|---|------|--------|------|
| P13-1 | **30 天 posterior edge 默认化** — `--decision-flow` / `--top-picks` / `--auto` 默认输出 T+20/T+30 预期收益、T+30 胜率与样本量, 让 30 天证据成为前门信息 | P0 | ✅ DONE R20.38: `render_expected_returns_compact()` 长周期化, `top_picks.py` / `decision_flow.py` 默认展示 T+30 证据 |
| P13-2 | **单一 investability 排序口径** — `--auto` top tranche、`--top-picks` 与 `--decision-flow` 统一按 composite_score + T+30 edge + 胜率/样本量做排序与摘要, 降低入口重复与认知切换 | P0 | ✅ DONE R20.38: 新增 `src/screening/investability.py` 共享排序逻辑 |

### Phase 17: 信号精度与用户体验最终打磨 (R20.39 提案)

> **目标**: 通过多时间框架趋势共振检测,进一步提升选股准确性; 通过相关性过滤提升推荐组合的实用性。
>
> **差距分析**: 系统已有 composite_score 融合 5 个独立信号 (base/momentum/sector/consistency/volume), 但缺少**多时间框架趋势一致性**检查。一只 5 日内上涨但 20/60 日均下跌的标的, 其上涨持续性远弱于三个时间框架均上涨的标的。这是经典量化选股的核心原则。同时, `--top-picks` 输出不做相关性过滤, 可能推荐 5 只同行业股票。

| # | 功能 | 优先级 | 状态 |
|---|------|--------|------|
| P14-1 | **多时间框架趋势共振** — 对每只推荐标的计算 5d/20d/60d 价格趋势方向 (线性回归斜率), 三个方向一致时给予共振 bonus (+0.05), 方向冲突时惩罚 (-0.05); 融入 composite_score 作为第 6 个信号因子 | P0 | ✅ DONE R20.39: `src/screening/trend_resonance.py` + `--trend-resonance` CLI; 35 pytest |
| P14-2 | **Top picks 相关性过滤** — `--top-picks` 输出时检查推荐标的之间的行业重叠, 若 3+ 只来自同一申万行业则发出集中度警告并建议替换 | P1 | ✅ DONE R20.39: `top_picks.py` 行业集中度警告 |

### Phase 18: 持仓监控与策略学习 (R20.39 提案)

> **目标**: 补齐"买入后无人管"的缺口, 让用户在持仓期间获得卖出信号和策略优化建议。
>
> **差距分析**: 系统有完善的买入决策链 (`--auto` → `--top-picks`), 但买入后的持续监控完全依赖用户手动检查。`exit_manager.py` 仅在 paper_trading 内部使用, 不对外暴露。用户最需要的是: "我昨天买的票, 今天还该持有吗?" 同时, 系统策略权重是静态的 (仅靠市场状态调整), 缺少基于近期表现的自动学习反馈。

| # | 功能 | 优先级 | 状态 |
|---|------|--------|------|
| P15-1 | **持仓健康检查** — `--position-check 000001,300750` 对用户已持仓标的输出综合健康评估 (composite_score 变化趋势 + 信号衰减 + 趋势共振状态 + 卖出建议), 复用全部既有信号基础设施 | P0 | ✅ DONE R20.39: `src/screening/position_health.py` + `--position-check` CLI; 18 pytest |
| P15-2 | **策略表现周报** — `--strategy-report` 输出近 7 天各策略 (趋势/均值回归/基本面/事件情绪) 的独立胜率与贡献度, 帮助用户理解当前市场风格并调整权重 | P1 | ✅ DONE R20.39: `src/screening/strategy_report.py` + `--strategy-report` CLI; 11 pytest |

### Phase 19: 每日工作流整合 (R20.39 提案)

> **目标**: 让用户每天只运行一个命令就能获得完整决策信息, 而不需要记住多个 CLI 标志。
>
> **差距分析**: 当前每日工作流需要运行 3 个独立命令: `--daily-brief` (盘前) → `--top-picks` (买点) → `--position-check` (监控)。用户体验碎片化。同时, `--top-picks` 不检查市场状态, 在风险厌恶行情下仍会推荐买入。
>
> **重叠清理**: Signal Analysis 的 6 个独立命令 (`--signal-momentum`, `--sector-strength`, `--volume-confirm`, `--trend-resonance`, `--signal-consistency`, `--composite-score`) 已全部被 `--decision-flow` 和 `--top-picks` 整合, 标记为 power-user 工具, 不列入推荐工作流。

| # | 功能 | 优先级 | 状态 |
|---|------|--------|------|
| P16-1 | **`--top-picks` 市场门控** — 当市场处于 risk-off/crisis 状态时, `--top-picks` 输出增加醒目警告 "当前市场环境不适合买入", 并降低推荐置信度 | P0 | ✅ DONE R20.39: `top_picks.py` `_market_gate_warning()` |
| P16-2 | **`--daily-brief` 整合持仓检查** — 增强 `--daily-brief` 输出, 在 Top 3 决策卡之前增加市场状态摘要 + 持仓健康预警 (如果用户配置了 `--watchlist`) | P1 | ✅ DONE R20.39: `daily_brief.py` `_print_watchlist_health()` |

---

## 四、技术债务与优化

| 维度 | 现状 | 状态 |
|------|------|------|
| 全市场评分并行度 | `score_batch` ThreadPoolExecutor + API 限速 | ✅ 已优化 |
| 缓存粒度 | 按标的+日期 + inflight-lock 防击穿 | ✅ 已优化 |
| LLM 调用开销 | 17 agent 并行 wave + cooldown | ✅ 已优化 |
| 数据源容错 | router 依次尝试 + HealthTracker 滑动窗口 | ✅ 健全 |
| 网络超时处理 | exponential backoff + `TUSHARE_MAX_RETRIES` | ✅ 健全 |
| 模块拆分 | R20.14-R20.16 累计 -3264 行重构 | ✅ 完成 |
| 类型标注 | PEP 484 + Pydantic v2 | ✅ 完成 |
| `x or default` 模式 | R20.15-R20.17 累计 36+ 处修复 | ✅ 完成 |
| `open()` encoding | R20.15/R20.18/R20.35 累计 4 处修复 | ✅ 完成 |

---

## 五、不做的功能 (避免重复 / 防臃肿)

| 功能 | 已有实现 / 决策 |
|------|----------------|
| 独立的选股排行榜 | `--auto --top-n` 已输出排名 |
| 独立的市场分析工具 | `market_state.py` 已集成流水线 |
| 独立的止损计算器 | `exit_manager.py` 五层退出 |
| 独立的仓位计算器 | `position_calculator.py` 已实现 |
| 独立的行业分析 | `industry_exposure.py` + 申万分类 |
| 独立的资金流分析 | `akshare_api.py: get_money_flow()` |
| NL 自然语言选股 | 12 persona LLM 推理 (问财已垄断零售) |
| 港股通跨市场 | 不同数据源/监管/税制, 超出范围 |
| 自定义因子 Python 编辑器 | 沙箱/版本控制/安全审计成本过高 |
| 移动端 App | Web + CLI 已满足个人量化需求 |
| 深度学习因子挖掘 | 4 策略因子 + IC 分析已足够 |

---

## 六、路线图完成度 (R20.35)

| 阶段 | 完成度 | 剩余 |
|------|--------|------|
| Phase 1-3 (CLI 决策链) | **11/11 (100%)** ✅ | — |
| Phase 4 (前端集成) | **7/7 (100%)** 🎉 | — |
| Phase 5 (闭环验证) | **4/4 (100%)** ✅ | — |
| Phase 6 (选股精度) | **2/2 (100%)** ✅ | — |
| Phase 7 (回测精度) | **4/4 (100%)** ✅ | — |
| Phase 8 (30 天目标对齐) | **2/2 (100%)** ✅ | P5-1 ✅ R20.34 / P5-2 ✅ |
| Phase 9 (数据质量增强) | **2/2 (100%)** ✅ | P6-1 ✅ R20.35 / P6-2 ✅ R20.35 |
| Phase 10 (信号质量自校验) | **2/2 (100%)** ✅ | P7-1 ✅ R20.35 / P7-2 ✅ R20.35 |
| Phase 11 (用户体验增强) | **2/2 (100%)** ✅ | P8-1 ✅ R20.35 / P8-2 ✅ R20.35 |
| Phase 12 (预期收益与决策整合) | **2/2 (100%)** ✅ | P9-1 ✅ R20.36 / P9-2 ✅ R20.36 |
| Phase 13 (动量与行业整合) | **2/2 (100%)** ✅ | P10-1 ✅ R20.37 / P10-2 ✅ R20.37 |
| Phase 14 (综合评分与量价确认) | **2/2 (100%)** ✅ | P11-1 ✅ R20.37 / P11-2 ✅ R20.37 |
| Phase 15 (极简决策入口) | **2/2 (100%)** ✅ | P12-1 ✅ R20.37 / P12-2 ✅ R20.37 |
| Phase 16 (30 天 investability 收敛) | **2/2 (100%)** ✅ | P13-1 ✅ R20.38 / P13-2 ✅ R20.38 |
| Phase 17 (信号精度最终打磨) | **2/2 (100%)** ✅ | P14-1 ✅ R20.39 / P14-2 ✅ R20.39 |
| Phase 18 (持仓监控与策略学习) | **2/2 (100%)** ✅ | P15-1 ✅ R20.39 / P15-2 ✅ R20.39 |
| Phase 19 (每日工作流整合) | **2/2 (100%)** ✅ | P16-1 ✅ R20.39 / P16-2 ✅ R20.39 |
| **后端** | **100%** 🎉 | — |
| **CLI** | **100%** 🎉 | — |
| **前端** | **100%** 🎉 | — |

---

## 七、文档维护说明

- **R20.19-R20.38**: 主文档已转为“活跃路线图 + 路由索引”模式；详细审查档案、行业调研与历史提案继续沉到子文档维护。
- **维护策略**:
  - 新增 P0/P1/P2 需求 → 追加到 §1
  - 已实现功能 → 主文档只保留一句话价值与状态，技术细节写入 `features/` 或 `research/`
  - 详细审查记录 → 追加到 `changelog/r20-audit-history.md`
  - 业界调研 → 追加到 `research/`

---

> **最后更新**: 2026-06-12 (R20.39: Phase 17 P14-1~P14-2 完成；多时间框架趋势共振+行业集中度过滤；7660 pytest 通过)
