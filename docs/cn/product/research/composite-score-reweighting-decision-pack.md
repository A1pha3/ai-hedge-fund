# 决策包：composite_score 排序修复（R6 — 负预测力）

> **状态**: 证据已就绪 (c297+c298), 等 owner 决策。**当前不建议翻转默认** — CI 太宽。
> **决策范围**: owner-only（默认前门行为切换 / 排序语义）。
> **证据**: c297 profit_aware 策略 + c298 bootstrap CI（`compute_selection_profitability_from_loaded`），n=75 mature 日 / 7993 records。
> **关联**: 本决策的工程基础设施已全部交付（C272 诊断 + C192 NS-4 footer + C273/C276 `--profit-aware` opt-in + c296 route-A 持久化 + c297 A/B 策略 + c298 CI）。

> **⚠️ 关键警告（c301, loop 34 新增）— 选择偏差风险，可能推翻整个诊断**:
> 本决策包的所有证据（c297/c298 A/B+CI）都跑在 `tracking_history`，即**推荐池**里的记录，**不是全 universe**。
> 历史 precedes: MR 因子诊断（C225, n=8901 推荐池）显示"全 4 MR 因子系统性反向 sep<0"，但 `aff989be`（2026-06-25, FULL 9896 passed）的全 universe 回测（n=8136）**推翻**了它 —— MR 在 A 股实际是**正向统计显著因子**（IC=+0.040, p=0.0003），推荐池里的"反向"是**选择偏差**（池预筛 trend-bullish 强势股，把能反弹的"超跌"票过滤掉了）。
> **R6 的"负预测力"可能是同一选择偏差伪象**: 若 composite_score 在池内的排序区分度被选择偏差污染（像 MR 那样），则翻转/重设权重会重蹈 `aff989be` 回滚的 MR-flip 覆辙。
> **教训**（`aff989be` 原文）: "因子诊断必须用全 universe（无选择偏差），不能只看推荐池。选择偏差是真实风险。"
> **对本决策包的影响**: 下面"推荐 D（推迟）"的信心应**更强** —— 不仅 CI 太宽，连点估计的"负预测力"本身都可能被选择偏差推翻。**owner 在做任何 flip/reweight 决策前，应先确认全 universe 诊断是否复现负预测力**（这是 c301+ 的 open 工作）。

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

**D（推迟 + 加速证据）**，理由：
1. 现有证据**不支持翻转**（所有 CI 重叠）—— 在噪声上翻转默认是负 EV。
2. route-A 真实键数据正在累积（c296）—— 决策级证据会自然到来，无需赌。
3. 根因（哪个维度驱动倒挂）未定位 —— 整体翻转（B/C）是症状治疗；维度重设（D 的并行工作）是根治。
4. 北极星（用户跟操作 30 天真实 P&L > 0）在默认 48% winrate 下**未达成** —— 但翻转的 B/C 也未必达成（profit-aware 57% / score_asc 63% 都未显著且仍可能亏损 median）。

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
