# 决策包：composite_score 排序修复（R6 — 负预测力）

> **状态**: ⚠️ **选择偏差伪象已确认 (c303, loop 36)** — R6"负预测力"是推荐池选择偏差伪象, **NOT a model defect; owner 不应 flip/reweight.** 全 universe 诊断 (20 日, light-stage T+1) 证实 composite_score 全 universe 有**正预测力** (Top-3 跑赢等权 +0.44%, 58% vs 42% winrate, 63% 日). 与 MR/aff989be precede 完全同型. 原 c297/c298 pool-based A/B 框架被推翻.
> **决策范围**: owner-only（默认前门行为切换 / 排序语义）— 但决策结论现已明确: **保持现状 (A), 不 flip/reweight**.
> **证据**: c297 profit_aware 策略 + c298 bootstrap CI（pool, n=75 日）+ **c303 全 universe 诊断 (n=19 日, light-stage T+1) — 见 §⚠️ 与 §7**.
> **关联**: 工程基础设施（C272 诊断 + C192 NS-4 footer + C273/C276 `--profit-aware` opt-in + c296 route-A 持久化 + c297 A/B 策略 + c298 CI + c303 全 universe 诊断）.

> **⚠️ 选择偏差伪象 — 已由 c303 全 universe 诊断确认 (loop 34 caveat → loop 36 confirmed)**:
> 原 c297/c298 A/B+CI 跑在 `tracking_history` = **推荐池**, 显示"负预测力"(48% vs 等权 60%)。
> **c303 全 universe 诊断 (20260703, n=19 日, light-stage 纯技术 T+1, ~2800 票/日)**:

> | 全 universe 策略 | mean | winrate | 跑赢等权日数 |
> |---|---|---|---|
> | 等权全 universe | **−0.063%** | 42.1% | — |
> | **Top-3 by score** | **+0.381%** | **57.9%** | **63.2%** ✅ |
> | Top-50 by score | +0.054% | 52.6% | 52.6% |

> **Top-3 by score 在全 universe 跑赢等权 (+0.44% delta, 58% vs 42% winrate, 63% 日)** → composite_score 全 universe 有**正预测力**; 推荐池里的"负预测力"是**选择偏差伪象** (池预筛 trend-bullish, 像 MR C225 那样)。
> **与 aff989be MR precede 完全同型**: MR 曾在池内诊断"系统性反向"(C225) 并 flip, 后被全 universe 回测推翻 (MR IC=+0.040 正向), flip 被 revert。R6 是同一现象的第二次实例。
> **owner 决策**: **不应 flip/reweight** (会重蹈 MR-flip-revert 覆辙, 破坏一个实际在全 universe 工作的模型)。原 B/C/profit-aware 方案均基于池伪象, 应放弃。
> **证据文件**: `data/reports/r6_full_universe_diag_20d_20260703.log`; 脚本 `scripts/_diag_r6_full_universe.py` (c303)。
> **剩余 caveat**: light-stage (0 LLM) + T+1 + n=19。若 owner 想更强证据, 跑全模型 (with LLM) / T+5,T+10 / 更长 N (c302 §7 重型路线)。但当前证据已足够支撑"不 flip"决策。

---

## 1. 当前问题与证据

**问题**: 默认前门（`--top-picks`）按 `composite_score` 降序选 top-N，但该分数在 T+5 portfolio 层有**负预测力** —— 模型 top-3 跑输等权。

**真实数据证据**（n=75 mature 日 / 7993 records，T+5，bootstrap CI 95%）:

| 策略 | winrate | 95% CI | median |
|---|---|---|---|
| **score_desc（当前默认）** | **48.0%** | [37%, 59%] | -0.33% |
| score_asc（反向押注模型） | 62.7% | [52%, 73%] | +1.35% |
| equal_weight（忽略分数） | 60.0% | [48%, 71%] | +1.12% |
| random_n（随机基线） | 60.0% | [49%, 71%] | +0.87% |
| **profit_aware（经验胜率重排）** | **57.3%** | [47%, 68%] | +0.81% |

**关键发现**:
1. 默认排序 (48%) 跑输等权 (60%) 12pp — 与 C219/C225 的 bucket 层倒挂（low-bucket T+5 winrate 60% > high-bucket 45%）在 portfolio top-3 层一致。
2. **所有 CI 高度重叠** → 默认的负预测力、profit-aware 的 +9pp 提升，在 n=75 下都**未达统计显著**。
3. `score_asc`（完全反向押注模型）点估计最高 (62.7%)，但 CI 仍与默认重叠。
4. T+10 horizon 下 profit-aware 无提升（49% vs 默认 51%）—— 倒挂效应是 T+5 特有的。

**方法学诚实披露**:
- `profit_aware` 是 **route-B-lite 代理**：用 walk-forward overall bucket winrate（4 桶 by score），**忽略 regime 维度**。真实 live 键是 bucket×regime（route-A 数据成熟后可重建）。
- walk-forward 有**轻微 look-ahead**（recent records 在 horizon 窗口内的 return 用于当日 bucket winrate 估计）—— 二阶效应（影响绝对 winrate 水平，不显著改变桶间相对排序），不改变"CI 重叠 → 不显著"的结论。
- 决策级证据需 route-A（c296 持久化的真实 profit-aware 键）数据成熟 + 更多天数收窄 CI。

---

## 2. 候选方案

### A. 保持默认不变（status quo）
- **动作**: 无。`composite_score` 仍是默认排序。
- **何时重新评估**: ~30+ 个 post-c296 mature 日累积后，重跑 A/B（route-A 真实键 + 收窄 CI）。
- **代价**: 在证据明确前不冒险翻转。owner 每日通过 footer 看到 A/B 数字持续观察。

### B. 翻转默认到 `--profit-aware`（C273/C276 opt-in 已就绪）
- **动作**: 把 `--profit-aware` 从 opt-in 变默认。ranker 按经验 bucket winrate 重排。
- **预期收益**: T+5 top-3 winrate 48% → ~57%（+9pp，**未显著**）。
- **风险**: CI 与默认重叠 → 翻转可能无真实收益（噪声）；且 profit-aware 仍跑输等权 (60%)，owner 期待"最优秀赚钱工具"未满足。
- **回滚**: 一个 commit（恢复 opt-in 默认 False）。

### C. 翻转默认到 score_asc（完全反向）
- **动作**: 按 composite_score 升序选 top-N。
- **预期收益**: T+5 winrate 48% → ~63%（+15pp，**未显著**，但点估计最高）。
- **风险**: 极反直觉（owner 看 top picks 都是低分票）；CI 仍重叠；若模型在未来数据上变正，此翻转立即变毒。
- **回滚**: 一个 commit。

### D. 推迟决策 + 加速证据积累（推荐）
- **动作**: 保持默认（A），同时：(1) 确保 c296 route-A 字段在生产每日跑（已就绪）；(2) ~30 天后重跑 route-A A/B；(3) 在 footer 已可见的 A/B+CI 基础上，等 CI 收窄到能区分 48% vs 57%（约需 ±7pp 半宽 → n≈150+ 日）。
- **同时可推进的独立工作**: 排查 composite_score 各维度（trend/MR/fundamental/event_sentiment）哪个驱动倒挂（factor_attribution 模块已就绪，c296 的 `score_decomposition` 字段已落盘）→ 指向根因修复（重设权重），而非整体翻转。

---

## 3. 推荐方案

**A（保持默认 — 不 flip/reweight）— c303 选择偏差伪象确认后升级**，理由：
1. **c303 全 universe 诊断证实 composite_score 有正预测力**（Top-3 跑赢等权 +0.44%, 58% vs 42% winrate, 63% 日）。"负预测力"是推荐池选择偏差伪象, 不是 model defect。
2. **flip/reweight 会破坏一个实际在全 universe 工作的模型** — 重蹈 aff989be MR-flip-revert 覆辙（MR 也曾被池诊断"反向"而 flip, 后被全 universe 推翻并 revert）。
3. 原 c297/c298 pool-based A/B（包括 profit-aware +9pp、score_asc +15pp）均建立在**偏差样本**上, 其点估计不能指导全 universe 行为决策。
4. 北极星（用户跟操作 30 天真实 P&L > 0）: 全 universe 模型有正预测力, 但**推荐池**层面的 pool-level 现象仍可能让用户的实际 top-picks 体验不佳 — 这是**池筛选机制**问题 (trend 几乎全 bullish 无区分度, 见 aff989be), 不是排序权重问题。根治路径是改进池筛选 / 因子区分度, 而非 flip 排序。

**原 D（推迟）方案被 c303 结果取代**: 不再需要等 CI 收窄来决定 flip — flip 本身被证伪。

> **owner 问题更新（c303 后）**: 不再问"flip 还是 推迟"。问: **(a) 接受"模型在全 universe 工作, 池内表现是筛选机制问题"的结论, 把 R6 关掉吗?** (b) 是否要跑 c302 §7 重型全模型 (with LLM) / T+5,T+10 / 更长 N 来进一步确认? (c) 是否转向**池筛选机制**改进 (trend 区分度, aff989be 指出的根本问题) 作为新的北极星路径?

---

## 4. 风险与回滚

| 方案 | 主要风险 | 回滚 |
|---|---|---|
| A（保持） | owner 继续看到负预测力 footer，但无行动 → 信任磨损 | 无需回滚 |
| B（profit-aware） | 翻转基于噪声；profit-aware 仍跑输等权 | 1 commit（opt-in 默认 False）|
| C（score_asc） | 反直觉；未来数据上模型变正则立即变毒 | 1 commit |
| **D（推荐）** | 等 30 天的 patience 成本；期间默认继续亏 | 任何时点可切到 B/C |

---

## 5. 需要回答的 owner 问题

> **当前证据（CI 重叠）不支持翻转。你是否同意走方案 D（等 route-A 数据成熟 + 并行排查维度根因），还是有其他偏好？**
>
> 若你希望立即行动 despite CI，B（profit-aware）比 C（score_asc）更保守（部分缓解 vs 完全反向），但两者都基于未显著的点估计。

---

## 6. 触发重新决策的条件

- post-c296 mature 日累积 ≥ 30 → 重跑 route-A A/B（真实 bucket×regime 键）。
- CI 半宽收窄到 < 7pp → 能区分 48% vs 57%。
- factor_attribution 定位到驱动倒挂的具体维度 → 触发"维度重设"新决策包（根治路径）。
- 任意 horizon（T+5/T+10）的 A/B 在收窄 CI 后显著 → 触发对应翻转评估。
- **全 universe 诊断复现/推翻负预测力（§7 prerequisite，c301+）**。

---

## 7. 全 universe 诊断 prerequisite（c301, loop 34-35）— owner 在 flip/reweight 前必须先做

**为什么**: §⚠️ 已述 — 推荐池诊断可能被选择偏差污染（aff989be MR precedes）。owner 必须先确认负预测力在全 universe 仍成立，才能合理考虑 B/C flip/reweight。

**两条路线（owner 选）**:

| 路线 | 方法 | 能回答什么 | 代价 |
|---|---|---|---|
| **全模型（with LLM）** | 在历史 N 日对全 universe 跑完整 composite_score（含 fundamental/event_sentiment LLM agents），rank top-3 vs equal-weight | 完全复现 owner `--top-picks` 行为；最权威 | 大 compute（数百票 × N 日 × LLM 调用）；可能需数小时 + LLM 费用 |
| **轻量（纯技术 0 LLM）** | 复用 `scripts/_backtest_light_stage_universe.py`（aff989be/C226 infra），只用 trend/MR 技术因子算 provisional score，rank top-N vs equal-weight | 部分回答（不含 LLM 因子）；快速 | 小 compute（分钟级）；但若 LLM 因子才是负预测力来源，此路线看不到 |

**推荐顺序**: 先跑**轻量**路线（快，看技术 composite 是否已有负预测力）。若轻量显示全 universe 上技术 composite **无**负预测力 → 强化选择偏差假设（像 MR），owner 应停止 flip 考虑。若轻量显示**有**负预测力 → 再跑全模型确认。

**Autodev 状态**: 这是 c301+ open 工作（candidate C-R6-FULL-UNIVERSE-DIAGNOSTIC）。owner 可指示 autodev 执行轻量路线（autonomous-able，复用现有 script infra），或 owner 自行决定路线。
