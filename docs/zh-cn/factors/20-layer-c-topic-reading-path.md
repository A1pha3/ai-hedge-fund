# Layer C 专题首页：阅读路径、学习顺序与使用场景

适用对象：第一次系统学习 Layer C 的读者，以及想快速定位“该看哪篇”的开发者、研究者、产品和复盘人员。

这份文档解决的问题：

1. 16、19、21 这一组 Layer C 文档分别讲什么。
2. 不同角色和不同场景应该按什么顺序读。
3. 如果只是带着一个具体问题进来，应该从哪里切入。

---

## 1. 这组文档整体在解决什么

Layer C 不是单一分数模块，而是一套研究层决策机制，涉及：

1. 多 Agent 信号标准化
2. 原始与调整后分数
3. B/C 融合
4. 冲突逻辑
5. watchlist 决策

因此，只读一篇长文往往会出现两个问题：

1. 新读者抓不住最重要的字段和结论。
2. 带着具体问题进来的读者，不知道该先看整体解释还是冲突与 watchlist 部分。

这份专题首页就是把 Layer C 材料组织成一条可执行阅读路径。

---

## 2. 文档地图

### 2.1 第一层：先知道 Layer C 是什么

1. [Layer C 策略完全讲解](./16-layer-c-complete-beginner-guide.md)
2. [Layer C 一页速查卡](./19-layer-c-one-page-cheatsheet.md)

这一层回答的是：

1. Layer C 在系统里负责什么。
2. 哪些字段最关键。
3. 为什么它不能只看支持票数。

### 2.2 第二层：快速纠正常见误解

1. [Layer C 常见问题 FAQ](./21-layer-c-faq.md)

这一层回答的是：

1. `raw_score_c` 和 `score_c` 到底差在哪。
2. 为什么 Layer C 通过不等于最终一定有 buy order。
3. 为什么当前代码里融合权重和历史产品文档不同。

### 2.3 第三层：需要放回系统全局时看哪里

1. [Layer B 策略完全讲解](./03-layer-b-complete-beginner-guide.md)
2. [Layer B 一页速查卡](./05-layer-b-one-page-cheatsheet.md)
3. [Factors 目录首页](./17-factors-overview-home.md)
4. [Replay Artifacts 选股阅读手册](../manual/replay-artifacts-stock-selection-manual.md)

这一层回答的是：

1. Layer C 如何承接 Layer B。
2. Layer C 的结论如何体现在 replay、watchlist 和执行层。

---

## 3. 三种读法

### 3.1 新人读法

建议顺序：

1. [19-layer-c-one-page-cheatsheet.md](./19-layer-c-one-page-cheatsheet.md)
2. [16-layer-c-complete-beginner-guide.md](./16-layer-c-complete-beginner-guide.md)
3. [21-layer-c-faq.md](./21-layer-c-faq.md)

这是从轮廓、到机制、再到纠偏的一条最短路径。

### 3.2 复盘读法

如果你正在看一只票为什么没有进 watchlist，建议顺序如下：

1. [19-layer-c-one-page-cheatsheet.md](./19-layer-c-one-page-cheatsheet.md)
2. [21-layer-c-faq.md](./21-layer-c-faq.md)
3. 再回到 [16-layer-c-complete-beginner-guide.md](./16-layer-c-complete-beginner-guide.md) 查冲突、融合和 watchlist 章节

### 3.3 调参读法

如果你准备讨论 Layer C 参数或阈值，建议顺序如下：

1. [16-layer-c-complete-beginner-guide.md](./16-layer-c-complete-beginner-guide.md)
2. [21-layer-c-faq.md](./21-layer-c-faq.md)
3. [Layer C P1 变更提交说明](../analysis/layer-b-p1-pr-summary-20260316.md)
4. [Layer C P1 短版提交模板](../analysis/layer-b-p1-short-templates-20260316.md)

---

## 4. 按问题找文档

1. “Layer C 到底负责什么”：看 [16-layer-c-complete-beginner-guide.md](./16-layer-c-complete-beginner-guide.md)
2. “我只想 5 分钟搞懂 Layer C”：看 [19-layer-c-one-page-cheatsheet.md](./19-layer-c-one-page-cheatsheet.md)
3. “为什么 raw_score_c 和 score_c 不一样”：看 [21-layer-c-faq.md](./21-layer-c-faq.md)
4. “为什么过了 Layer B 还是没进 watchlist”：先看 [19-layer-c-one-page-cheatsheet.md](./19-layer-c-one-page-cheatsheet.md)，再看 [16-layer-c-complete-beginner-guide.md](./16-layer-c-complete-beginner-guide.md)
5. “为什么历史产品文档的权重和当前代码不一样”：看 [21-layer-c-faq.md](./21-layer-c-faq.md)

---

## 5. 最小使用方式

如果你不想一次看很多，Layer C 的最小使用方式可以压缩成 3 步：

1. 先用 [19-layer-c-one-page-cheatsheet.md](./19-layer-c-one-page-cheatsheet.md) 建立整体心智模型。
2. 遇到具体疑问时先看 [21-layer-c-faq.md](./21-layer-c-faq.md)。
3. 真要复盘、排障或调参时，再看 [16-layer-c-complete-beginner-guide.md](./16-layer-c-complete-beginner-guide.md)。

---

## 6. 一句话总结

16 解决的是“Layer C 到底如何工作”，19 解决的是“先抓住什么最重要”，21 解决的是“哪些误解要先排除”，而这份首页负责把它们组织成一条可查、可学、可落到复盘的阅读路径。
