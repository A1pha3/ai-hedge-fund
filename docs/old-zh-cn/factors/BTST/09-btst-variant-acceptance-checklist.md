# BTST 变体验收清单与升级标准

适用对象：已经跑完 replay 或 live validation，下一步要判断“这个 BTST 变体能不能升级成默认候选”的研究员、工程师、AI 助手。

这份文档解决的问题：把 BTST 的变体验收从“感觉这轮不错”变成统一的通过标准，避免把一次偶然热窗口误判成可升级默认逻辑。

建议搭配阅读：

1. [02-btst-tuning-playbook.md](./02-btst-tuning-playbook.md)
2. [04-btst-experiment-template.md](./04-btst-experiment-template.md)
3. [05-btst-ai-optimization-runbook.md](./05-btst-ai-optimization-runbook.md)
4. [08-btst-current-window-case-studies.md](./08-btst-current-window-case-studies.md)
5. [../../product/arch/pre_layer_short_trade_catalyst_floor_zero_full_live_summary_20260329.md](../../product/arch/pre_layer_short_trade_catalyst_floor_zero_full_live_summary_20260329.md)
6. [../../product/arch/pre_layer_short_trade_boundary_score_fail_frontier_summary_20260329.md](../../product/arch/pre_layer_short_trade_boundary_score_fail_frontier_summary_20260329.md)

---

## 1. 先讲结论：BTST 变体只分 3 种结果

一轮变体实验做完后，只允许给出 3 类结论：

1. 保留为下一轮候选：方向可能正确，但证据还不够升级默认。
2. 回滚：要么没有实质收益，要么副作用不可接受。
3. 升级为默认候选：已经具备足够稳定的 replay 和真实窗口证据。

最重要的一条纪律是：**不要用“感觉更合理”替代“已经过了升级标准”。**

---

## 2. 什么样的变体可以进入验收阶段

不是所有实验都值得做验收。进入验收前，至少应满足下面 4 个前提：

1. 已固定 baseline、窗口、模型、selection target mode。
2. 已说明本轮唯一实验主题是什么。
3. 已完成 replay 或至少有一轮等价的低成本校验。
4. 已明确这轮实验在回答哪一个问题分型：admission、score frontier、structural conflict、candidate entry、execution 承接中的哪一种。

如果连问题分型都不清楚，这轮结果不应进入“是否升级默认”的讨论。

---

## 3. BTST 升级标准总表

| 维度 | 必问问题 | 不通过时怎么解释 |
| ---- | -------- | ---------------- |
| 问题归因 | 这轮是否只改了一类机制 | 不能归因，结论无效 |
| replay 一致性 | 是否无明显 stored/replayed 漂移 | 输入契约或变体逻辑不稳定 |
| 样本质量 | 新增样本的 T+1 表现是否可接受 | 只是放热，不是扩覆盖 |
| 副作用 | 是否污染了不该动的样本 | 说明变体过粗 |
| 窗口稳定性 | 结果是否只依赖单日偶然样本 | 不能升级默认 |
| 可解释性 | 是否能明确说明 why/what/how | 不能进入长期维护路径 |

---

## 4. Replay 验收清单

### 4.1 基础一致性

至少逐项回答：

1. `stored decision` 和 `replayed decision` 是否一致。
2. 是否出现异常的 `decision_mismatch_count`。
3. 变体是否只改变了预期对象，而没有出现无关样本大面积漂移。

如果这一层不通过，后面即使 live 看起来更好，也不应升级默认。

### 4.2 最小影响面

优先检查：

1. 本轮变化是不是集中在预期样本簇。
2. 是否只改变了应该改变的 `trade_date:ticker`。
3. 是否把原本稳定的 selected / near_miss 样本误伤掉了。

定点 release 类实验尤其要满足这一条。像 `300724-only` 这种 case-based 变体之所以有价值，就是因为它的影响面可控。

### 4.3 frontier 合理性

至少回答：

1. 这是 threshold-only 变体，还是 penalty / threshold 联动变体。
2. 它的最小 rescue row adjustment cost 是否足够低。
3. 这条 frontier 是单样本特例，还是窗口里可复用的机制。

如果 adjustment cost 很高，通常不适合升级默认，只适合作为研究证据保存。

---

## 5. Live validation 验收清单

### 5.1 数量不是第一指标

先不要看“多了几个候选”，先看下面 4 个指标：

1. `next_high_return_mean`
2. `next_close_return_mean`
3. `next_high_hit_rate@threshold`
4. `next_close_positive_rate`

如果只看到样本数增加，但看不到这些质量指标保持或改善，这轮变体通常不应升级默认。

### 5.2 admission 变体的专用标准

如果你调的是 admission，例如 floor 放松，应至少满足：

1. 新增样本是边缘高质量样本，而不是大批垃圾样本。
2. `next_close_return_mean` 不出现明显恶化。
3. `next_close_positive_rate` 不出现明显恶化。
4. 没有重新引入旧 `layer_b_boundary` 式失败簇。

这也是为什么 catalyst-only 扩覆盖能进入默认候选，而 volume 联动放松不能。

### 5.3 score frontier 变体的专用标准

如果你调的是 `select_threshold`、`near_miss_threshold` 或 penalty 权重，应至少满足：

1. 新释放样本主要集中在 near-miss 邻域，而不是远距离强拉。
2. 不会把大量原本明显不合格样本一起放进来。
3. 变体对应的机制解释清楚，例如“只是释放接近 near-miss 的 score-fail 簇”。

### 5.4 structural conflict release 的专用标准

如果你调的是 blocked 样本 release，应至少满足：

1. 有明确 case-based 目标，而不是整簇放宽。
2. 影响面可控。
3. 被释放样本具备低成本 rescue row 证据。
4. 不污染其他 blocked 样本。

---

## 6. 升级默认候选的最低门槛

一个 BTST 变体要想被记为“默认候选”，至少同时满足下面 6 条：

1. 问题分型明确，且本轮只改一类机制。
2. replay 无明显契约漂移或无关样本污染。
3. 真实窗口中，新增样本质量指标没有明显恶化。
4. 影响面与预期一致，没有意外释放整簇噪声。
5. 能用一句话清楚解释这轮为什么成立。
6. 有明确理由说明它比 baseline 更适合长期维护，而不是只适合当前窗口。

如果 6 条里缺任意一条，都更适合先标记为“下一轮候选”。

---

## 7. 不同类型变体的常见判定结果

### 7.1 admission 单项 floor 放松

常见结论：

1. 若新增样本有限且质量稳定，可升级默认候选。
2. 若样本虽多但 close 质量明显走弱，回滚。

### 7.2 threshold-only rescue

常见结论：

1. 若只释放 low-cost near-miss 邻域，可保留候选。
2. 若需要大幅下调阈值才有收益，通常不升级默认。

### 7.3 penalty 联动 relief

常见结论：

1. 若只对单个 penalty 主导样本有效，保留研究证据即可。
2. 若要同时放松多项 penalty 才成立，通常不适合升级默认。

### 7.4 structural conflict 定向 release

常见结论：

1. 若是单样本、低成本、低污染 case，可保留为受控实验候选。
2. 若要整簇放宽才能见效，应回滚或继续拆样本。

---

## 8. 当前窗口可以直接套用的验收结论

基于最近 2026-03-23 到 2026-03-26 的窗口证据，可以直接记住下面两条：

1. `catalyst_freshness_min=0.00` 已满足 admission 变体的默认候选标准，因为它在完整 live 窗口下扩了 coverage，但没有把前置候选质量打坏。
2. `300724-only` 的 structural conflict release 目前更适合记为受控 case-based 候选，而不是默认规则升级，因为它成立的是单点、低污染、低成本 release，不是整簇机制放宽。

---

## 9. 最后验收模板

每轮实验结束后，建议只回答下面 8 个问题：

1. 本轮唯一实验主题是什么。
2. 它对应哪一个问题分型。
3. replay 是否稳定。
4. 改变的是不是预期样本。
5. 新增样本的 T+1 质量是否仍可接受。
6. 是否带来明显副作用。
7. 这轮更适合回滚、保留候选，还是升级默认。
8. 下一轮最合理的是继续放大、局部补证，还是换主线。

---

## 10. 一句话总结

BTST 的变体验收，核心不是“这轮有没有更高分”，而是“这轮是不是用可解释、可归因、可复用的方式，稳定改善了正确那批样本”。只有满足这一点，才配升级默认。
