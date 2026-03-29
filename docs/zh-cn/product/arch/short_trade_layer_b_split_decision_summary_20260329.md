# 短线是否应从 Layer B 开始分叉：决策摘要

## 一句话结论

应该。从 Layer A 开始共享仍然合理，但从 Layer B 开始，short trade 不应继续复用 research 风格的 boundary candidate pool，而应使用独立的 short-trade boundary candidate builder。

## 为什么现在可以下这个结论

不是因为理念上“短线和长线不一样”这么抽象，而是因为真实窗口证据已经足够一致：旧路径里，short trade 会持续吃进 research 风格的 `layer_b_boundary` 边界样本，结果这些样本大多在 short-trade 评分里直接 score-fail；新路径把 short trade 的补充池改成独立 builder 之后，这个主失败簇在完整 4 日真实窗口里被稳定消掉。

## 证据收敛

### 旧路径的问题是什么

- `2026-03-23~2026-03-26` 四天旧路径累计出现 `23` 个 `layer_b_boundary` score-fail。
- 这些样本虽然 `score_b` 并不低，但 short-trade `score_target` 普遍很差，说明它们适合进入 research 边界观察，不适合进入次日买入候选。
- 失败并不是“阈值差一点”，而是候选本身普遍缺少 short trade 真正关心的 breakout、volume、catalyst 结构。

### 新路径改善了什么

- 新 builder 在真实 live 路径下把四天窗口中的 `layer_b_boundary` score-fail 从 `23` 压到 `0`。
- 同时保留下来的边界补充候选，不再是低质量 reject，而是 `6` 个 `short_trade_boundary` near-miss。
- 这些 near-miss 的均值分数稳定在 `0.53+`，已经进入“结构基本成立、只差最后一段距离”的区间，而不是旧路径那种 `0.10~0.15` 的低质量噪声。

### 每天都一致吗

是，而且不是只在 partial live 上成立。

- `2026-03-23,2026-03-24`：旧路径 `11` 个 `layer_b_boundary` score-fail，new path 为 `0`，并新增 `2` 个 `short_trade_boundary` near-miss，均值 `0.5487`。
- `2026-03-25`：旧路径 `6` 个 `layer_b_boundary` score-fail，new path 为 `0`，并新增 `2` 个 `short_trade_boundary` near-miss，均值 `0.5579`。
- `2026-03-26`：旧路径 `6` 个 `layer_b_boundary` score-fail，new path 为 `0`，并新增 `2` 个 `short_trade_boundary` near-miss，均值 `0.5372`。

这说明它不是单日 luck，也不是只在某个 ticker 上成立，而是窗口级稳定现象。

## 设计上应如何理解

### 哪一层可以继续共享

Layer A 仍然可以共享。原因很简单：Layer A 的职责更偏市场宽筛和统一候选发现，这一层不需要过早区分“长期研究”和“次日买入”。

### 哪一层必须分叉

从 Layer B 开始必须分叉。原因是 Layer B 已经进入“候选质量定义”的阶段，而 short trade 和 research 在这一层关心的结构并不相同：

- research 可以容忍“还没形成交易触发，但值得继续研究”的边界样本。
- short trade 需要的是更强的 breakout、trend、volume、catalyst 组合质量。

如果继续共用同一个 boundary pool，本质上就是把 research 的边界样本灌进 short trade，再让 short-trade scorer 在下游大量判死刑。这会制造无意义 rejection 簇，并污染 short-trade 诊断视野。

## 当前最合理的架构表述

推荐的表述不是“完全两套系统”，而是：

- Layer A 共享候选发现。
- Layer B 开始分叉候选质量定义。
- research 继续使用自己的 boundary / watchlist 语义。
- short trade 使用独立的 `short_trade_boundary` builder，只吸收满足 short-trade 结构 floor 的候选。

这比“继续共池、下游再过滤”更干净，也更符合当前真实数据已经显示出的失败机制。

## 这意味着下一步应该把精力放在哪

不需要再回头争论“要不要继续共用 Layer B 股票池”，这件事已经有足够证据，可以视为已决。现在更值得做的是：

1. 继续处理 `layer_c_bearish_conflict` blocked 簇，因为 boundary quality 主失败簇已经被清掉。
2. 把 short-trade boundary builder 的结构 floor 继续当成独立控制面来验证，而不是再退回 research 风格的 fast-score buffer 语义。
3. 对 `300724` 这类高分 blocked 样本做受控实验，判断它们是否应从 blocked 释放到 near-miss，而不是重新打开旧 boundary pool。

## 最终决策

结论可以写得很直接：

短线和长线不需要从最上游完全拆成两套系统，但 short trade 从 Layer B 开始应明确分叉，不能再继续共享 research 风格的 boundary candidate pool。当前真实 `2026-03-23~2026-03-26` 窗口已经证明，独立 `short_trade_boundary` builder 能稳定消除旧的主失败簇，因此这项架构调整应视为已验证成立，而不是待讨论假设。