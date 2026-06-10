# 产品功能提案清单 (R20.19 精简索引版)

> **目标**: 让用户更高效地找到未来 30 天内最有投资价值的 A 股标的。
>
> **本版本变更 (R20.19)**: 主文档从 933 行精简到 < 200 行。R20.1-R20.18 详细审查档案移至 [`changelog/r20-audit-history.md`](./changelog/r20-audit-history.md)。
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
| P2-2 | 回测参数对比面板 (前端) | ✅ DONE R20.31: service layer (`param-compare-api.ts`) + 展示组件 (`param-compare-panel.tsx`: 排序对比表 + 最佳指标高亮 + 失败组合展示); 待接入后端 API 端点 |
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

业界对标: Numerai / QuantConnect / 聚宽 / 米筐 / 同花顺。我们的差异化: 20-agent persona 架构 + 完整可解释性链。

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
| P3-1 | 推荐闭环验证 (`--verify-recommendations`) | P0 | ✅ DONE R20.31: `src/screening/verify_recommendations.py` (VerifySummary + 策略归因) + CLI dispatcher; 16 pytest |
| P3-2 | 策略动态权重校准 | P1 | ❌ 未实现 |
| P3-3 | 行业 + 个股交叉选择 | P1 | ✅ DONE R20.31: `src/screening/industry_cross_picks.py` (CrossPick: 强势行业 Top N + 行业最优个股); 12 pytest |
| P3-4 | 推荐组合构建器 | P2 | ❌ 未实现 |

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
| `open()` encoding | R20.15/R20.18 累计 3 处修复 | ✅ 完成 |

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

## 六、路线图完成度 (R20.19)

| 阶段 | 完成度 | 剩余 |
|------|--------|------|
| Phase 1-3 (CLI 决策链) | **11/11 (100%)** ✅ | — |
| Phase 4 (前端集成) | **7/7 (100%)** 🎉 | — |
| **后端** | **100%** 🎉 | — |
| **CLI** | **100%** 🎉 | — |
| **前端** | **100%** 🎉 | — |

---

## 七、文档维护说明

- **R20.19 (本轮)**: 主文档 933 行 → < 200 行。R20.1-R20.18 详细审查档案移至 `changelog/r20-audit-history.md`。
- **维护策略**:
  - 新增 P0/P1/P2 需求 → 追加到 §1
  - 已实现功能 → §1 标记 ✅, 不再展开细节
  - 详细审查记录 → 追加到 `changelog/r20-audit-history.md`
  - 业界调研 → 追加到 `research/`

---

> **最后更新**: 2026-06-11 (R20.31 round 4: P3-1 推荐闭环验证 + P3-3 行业+个股交叉选择 实现 → Phase 5 进展 2/4)
