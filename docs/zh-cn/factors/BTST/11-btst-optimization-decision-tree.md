# BTST 优化决策树

适用对象：已经有一批 BTST 样本、分析报告或 replay 结果，但还不确定下一步应该改 admission、改 score frontier、改 blocked release，还是直接停止优化的人。

这份文档解决的问题：把 BTST 下一步动作收敛成一棵可执行决策树，减少“每次都从头争论该调什么”的摩擦。

建议搭配阅读：

1. [02-btst-tuning-playbook.md](./02-btst-tuning-playbook.md)
2. [06-btst-troubleshooting-playbook.md](./06-btst-troubleshooting-playbook.md)
3. [09-btst-variant-acceptance-checklist.md](./09-btst-variant-acceptance-checklist.md)
4. [10-btst-artifact-reading-manual.md](./10-btst-artifact-reading-manual.md)

---

## 1. 先讲结论：BTST 优化只允许从 5 个入口进入

每次准备优化 BTST 时，不要重新自由发挥。当前只允许从下面 5 个入口进入：

1. Layer B / 入口供给不足。
2. short-trade admission 太严。
3. short-trade score frontier 太严。
4. blocked 样本存在结构冲突。
5. 研究上通过，但 execution 承接差。

如果当前问题不属于这 5 类，先不要改规则，先补证据。

---

## 2. 决策树主干

### 第一步：当前 short-trade 样本是不是少得异常

如果是，继续问：

1. 上游 fused / Layer B 候选本来就少：先回到 Layer B 供给，不先动 BTST 阈值。
2. 上游候选不少，但 `short_trade_boundary` 很少：先看 admission floors。
3. `short_trade_boundary` 已经不少，但 `selected/near_miss` 还是少：先看 score frontier。

### 第二步：当前最大失败簇是什么

如果最大失败簇是：

1. `rejected_layer_b_boundary_score_fail`：说明你还在看旧共享边界池问题，先切换到独立 builder 口径，不先调 target threshold。
2. `rejected_short_trade_boundary_score_fail`：说明 admission 已不是主矛盾，优先看 score frontier。
3. `blocked`：说明结构冲突是主线，优先看 rescue queue，而不是放大 admission。

### 第三步：新增样本质量有没有变好

如果没有，停止继续放松。数量增加但 `next_close_return_mean` 和 `next_close_positive_rate` 变差，通常说明你在引入垃圾候选。

---

## 3. 入口 A：Layer B / 供给不足

进入条件：

1. 上游候选本身就偏少。
2. fast pool 过冷。
3. `short_trade_boundary` 没有足够原料可挑。

正确动作：

1. 回到 Layer B 语义、heavy leg 覆盖和阈值，不先动 BTST target profile。
2. 先判断供给问题是技术腿、fundamental、event 还是融合问题。

停止条件：

1. 如果 Layer B 已经恢复供给，再回到 BTST 入口层。
2. 如果供给仍不足，不要拿 BTST 调参掩盖上游问题。

---

## 4. 入口 B：admission 太严

进入条件：

1. 上游候选不低，但 `short_trade_boundary` 通过数偏少。
2. 过滤原因高度集中在某一个 floor。
3. 过滤样本中存在一批边缘高质量候选。

正确动作：

1. 优先做单项 floor 放松，而不是多项联动。
2. 先选“最集中、最边缘、最可控”的那一项。
3. 放松后立即看 pre-layer 次日表现，而不是只看通过数。

当前窗口的已知默认动作：

1. admission 扩覆盖优先看 `catalyst_freshness_min=0.00`。
2. 不优先联动放松 volume floor。

停止条件：

1. 一旦 close 质量明显恶化，立即回滚。
2. 如果 admission 放松后失败簇转向 score frontier，下一轮换入口，不要继续找第二条 floor。

---

## 5. 入口 C：score frontier 太严

进入条件：

1. admission 已通过。
2. 失败簇主要是 `rejected_short_trade_boundary_score_fail`。
3. 样本结构本身已像短线，但离 near-miss 仍有差距。

正确动作：

1. 先做 score-fail frontier 分析。
2. 区分 threshold-only 样本和 penalty 联动样本。
3. 先找低 adjustment cost 的 release row，不先做大范围阈值下调。

停止条件：

1. 如果大部分样本 gap 普遍很大，停止 threshold-only 实验。
2. 转去看 score construction 或 penalty 结构，而不是继续压阈值。

---

## 6. 入口 D：blocked 样本结构冲突

进入条件：

1. `blocked` 是主要失败簇或重要次失败簇。
2. 样本主要被 `layer_c_bearish_conflict` 或其他 hard block 卡住。

正确动作：

1. 先跑窗口级 rescue queue，排序低成本样本。
2. 只对存在 low-cost rescue row 的样本做 case-based release。
3. 先拆 hard block 与 surcharge，避免重复惩罚黑盒。

当前窗口的已知默认动作：

1. 优先审 `300724-only`。
2. 不做 blocked cluster-wide release。

停止条件：

1. 如果多数 blocked 样本没有 near-miss row，停止整簇 release 讨论。
2. 把样本转回 candidate-entry 或 penalty 研究路径。

---

## 7. 入口 E：execution 承接差

进入条件：

1. `selected` 或 `near_miss` 看起来不少。
2. 但 buy order 承接没改善，或真实执行端解释不通。

正确动作：

1. 先看 execution bridge，而不是继续放热 BTST 入口。
2. 区分“会选”和“会买”是两回事。

停止条件：

1. 如果问题确认在 execution bridge，就从 BTST 规则优化切换到 execution 优化。

---

## 8. 单票决策树

如果你面对的是某一只具体股票，建议按下面顺序走：

1. 它来自哪个 `candidate_source`。
2. 它是 `rejected` 还是 `blocked`。
3. 它的正向结构是弱，还是 penalty 太重。
4. 它有没有 low-cost rescue row。

然后直接归类：

1. 弱结构入口样本：走 candidate-entry / admission 路径。
2. score-fail 边界样本：走 frontier 路径。
3. low-cost blocked 样本：走 targeted release 路径。
4. 高成本 penalty 样本：先保存研究证据，不进入默认升级讨论。

---

## 9. 当前窗口的默认决策树落点

把最近窗口直接代入，可以得到一个非常具体的默认判断：

1. 如果你问“入口还要不要继续扩”，答案是先停在 catalyst-only，不再继续找第二条 floor。
2. 如果你问“下一轮最该救谁”，答案是 `short_trade_boundary` score-fail 簇和 `300724-only`。
3. 如果你问“`300394` 和 `300502` 要不要一起救”，答案是否定的，它们属于不同机制问题。

---

## 10. 一句话总结

BTST 优化最重要的不是多做实验，而是每一轮都能先把问题送进正确入口。入口选对了，实验数量会显著减少；入口选错了，做再多 frontier 也只是在噪声里打转。
