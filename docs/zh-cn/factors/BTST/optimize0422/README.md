# BTST 0422 优化专题

**文档日期**：2026-04-22  
**数据基准**：4/21 信号 → 4/22 实盘收盘验证 + 20 日回测滚动覆盖  
**适用对象**：需要理解当前 BTST 策略瓶颈、制定下阶段优化优先级的研究员和 AI 助手

---

## 本次优化的背景

4/22 收盘后，基于 4/21 信号的多智能体精选 4 只全部取得正收益（平均 +4.75%），单日胜率 100%。
这个结果看似理想，但结合 20 日历史回测（8485 样本）来看，当前策略的长期期望收益为 **-0.04%**（扣费后为负），胜率仅 47.27%，距离"可持续盈利"仍有明显缺口。

本次专题聚焦三个问题：

1. 今天为什么赢了，哪些因素是结构性优势，哪些是运气？
2. 20 日回测暴露了哪些系统性短板？
3. 按影响力排序，接下来应该优先优化哪些环节？

---

## 文档目录

| 文件 | 内容 |
|------|------|
| [01-0422-实盘复盘与数据证据.md](./01-0422-实盘复盘与数据证据.md) | 4/21→4/22 完整实盘验证表，20 日回测日级分布，selected vs near_miss 对比 |
| [02-0422-优化路线设计.md](./02-0422-优化路线设计.md) | 四层优化路线（择日门控 / 先验质量门槛 / 精选契约 / 风险预算），含代码落点、验证口径、灰度与回滚 |
| [03-0422-开发任务清单.md](./03-0422-开发任务清单.md) | 可执行开发拆解，按 P0-P6 列出改动文件、必须产物、完成标准与回滚条件 |

---

## 快速结论（一句话）

> 当前 BTST 的主矛盾不是选股质量太低，而是**弱势日仍然入场**——8 个弱势日损耗的期望利润几乎完全抵消了 7 个强势日的所有收益。
> 只要能识别并跳过弱势日，策略的正期望窗口将显著扩大。

---

## 建议阅读顺序

1. 先读 [01 复盘](./01-0422-实盘复盘与数据证据.md) — 了解数据来源和事实基线
2. 再读 [02 路线](./02-0422-优化路线设计.md) — 评估各方向的落地成本与预期收益
3. 再读 [03 清单](./03-0422-开发任务清单.md) — 按阶段推进开发、测试、报表与回滚
4. 可选：对比 [optimize0415](../optimize0415/gpt-5.4-analyze-0415.md) — 上一次强→弱转折日的系统失误分析

---

## 已落地的 PR1 产物

| 产物 | 路径 |
|------|------|
| P0 基线冻结 JSON / Markdown | `data/reports/p0_btst_0422_baseline_freeze.json` / `data/reports/p0_btst_0422_baseline_freeze.md` |
| P1 择日门控 shadow 评估 JSON / Markdown | `data/reports/p1_btst_regime_gate_shadow_eval.json` / `data/reports/p1_btst_regime_gate_shadow_eval.md` |
| P0 生成脚本 | `scripts/analyze_btst_0422_baseline_freeze.py` |
| P1 生成脚本 | `scripts/analyze_btst_regime_gate_effect.py` |

## 已落地的 PR2 产物

| 产物 | 路径 |
|------|------|
| P2 择日门控强制上线多窗口对比 JSON | `data/reports/p2_btst_regime_gate_enforced_window_compare.json` |
| P2 择日门控强制上线多窗口对比 Markdown | `data/reports/p2_btst_regime_gate_enforced_window_compare.md` |
| P2 生成脚本 | `scripts/analyze_btst_regime_gate_effect.py` |

### 回滚说明

PR2 通过环境变量 `BTST_0422_P2_REGIME_GATE_MODE` 控制择日门控的强制模式。
若需要回退到 PR1 之前的旧行为，将该变量设为 `off`（或不设置）即可恢复：

```bash
export BTST_0422_P2_REGIME_GATE_MODE=off
```

在 `off` 状态下，策略行为与 P0 基线完全一致，不执行任何择日过滤。

## 已落地的 PR3 产物

| 产物 | 路径 |
|------|------|
| P3 先验质量历史审计 JSON | `data/reports/p3_btst_historical_prior_quality_audit.json` |
| P3 先验质量历史审计 Markdown | `data/reports/p3_btst_historical_prior_quality_audit.md` |
| P3 生成脚本 | `scripts/analyze_btst_historical_prior_quality.py` |

### 回滚说明

PR3 通过环境变量 `BTST_0422_P3_PRIOR_QUALITY_MODE` 控制先验质量门控的强制模式。
若需要回退到 PR3 之前的旧行为，将该变量设为 `off`（或不设置）即可恢复：

```bash
export BTST_0422_P3_PRIOR_QUALITY_MODE=off
```

在 `off` 状态下，P3 先验质量门控完全不生效，策略行为与 PR2 基线完全一致。

## 已落地的 PR4 产物

| 产物 | 路径 |
|------|------|
| P4 先验收缩评估 JSON | `data/reports/p4_btst_prior_shrinkage_eval.json` |
| P4 先验收缩评估 Markdown | `data/reports/p4_btst_prior_shrinkage_eval.md` |
| P4 selected vs near_miss separation JSON | `data/reports/p4_btst_selected_nearmiss_separation.json` |
| P4 selected vs near_miss separation Markdown | `data/reports/p4_btst_selected_nearmiss_separation.md` |
| P4 生成脚本 | `scripts/analyze_btst_prior_shrinkage_eval.py` |
| P4 separation 脚本 | `scripts/analyze_btst_selected_nearmiss_separation.py` |

### 回滚说明

若需要关闭 PR4 先验收缩逻辑并回退到 PR3 行为，设置：

```bash
export BTST_0422_P4_PRIOR_SHRINKAGE_MODE=off
```

## 已落地的 PR5 产物

| 产物 | 路径 |
|------|------|
| P5 执行契约评估 JSON | `data/reports/p5_btst_execution_contract_eval.json` |
| P5 执行契约评估 Markdown | `data/reports/p5_btst_execution_contract_eval.md` |
| P5 生成脚本 | `scripts/analyze_btst_execution_contract_eval.py` |

### 回滚说明

若需要关闭 PR5 执行契约强制语义并回退到 PR4 行为，设置：

```bash
export BTST_0422_P5_EXECUTION_CONTRACT_MODE=off
```

## 已落地的 PR6 产物

| 产物 | 路径 |
|------|------|
| P6 风险预算 overlay 评估 JSON | `data/reports/p6_btst_risk_budget_overlay_eval.json` |
| P6 风险预算 overlay 评估 Markdown | `data/reports/p6_btst_risk_budget_overlay_eval.md` |
| P6 生成脚本 | `scripts/analyze_btst_risk_budget_overlay_eval.py` |

### 回滚说明

若需要关闭 PR6 风险预算 overlay 并回退到 PR5 行为，设置：

```bash
export BTST_0422_P6_RISK_BUDGET_MODE=off
```

## 报表生成输入样例

| 用途 | 路径 |
|------|------|
| P1 / P2 / P3 默认样例窗口 | `data/paper_trading_window_sample/` |
| P4 默认样例窗口 | `data/p4_prior_shrinkage_eval_sample/` |
| P5 默认样例窗口 | `data/p5_execution_contract_eval_sample/` |
| P6 默认样例窗口 | `data/p6_risk_budget_overlay_eval_sample/` |
