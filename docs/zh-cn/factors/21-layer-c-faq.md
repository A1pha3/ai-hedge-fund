# Layer C 常见问题 FAQ

适用对象：已经接触过 Layer C 文档，但在学习、复盘或调参时反复遇到相同疑问的开发者、研究者、产品和复盘人员。

这份 FAQ 解决的问题：

1. 把 Layer C 最常见的误解收成问答式入口。
2. 让读者在不通读整篇长文的前提下，也能快速抓住核心结论。
3. 给复盘和调参提供一份“先别误会这几点”的短清单。

建议搭配阅读：

1. [Layer C 一页速查卡](./19-layer-c-one-page-cheatsheet.md)
2. [Layer C 专题首页](./20-layer-c-topic-reading-path.md)
3. [Layer C 策略完全讲解](./16-layer-c-complete-beginner-guide.md)

---

## 1. Layer C 是不是就是一个 LLM 打分层

不是。

Layer C 不是单个 LLM 分数，而是：

1. 多 Agent 输出标准化
2. cohort 权重归一化
3. 原始与调整后研究分数计算
4. B/C 冲突识别
5. watchlist 决策接线

它本质上是研究确认层，而不是展示层。

---

## 2. `raw_score_c` 和 `score_c` 到底差在哪

`raw_score_c` 是未经 bearish investor attenuation 的原始研究净分歧。

`score_c` 是经过当前 investor bearish attenuation 之后，真正用于融合的 Layer C 分数。

所以：

1. `raw_score_c` 更适合看真实分歧。
2. `score_c` 更适合看当前系统最终怎么使用 Layer C。

---

## 3. 为什么 UI 里看起来 Layer C 没那么负，但还是会触发 `avoid`

因为冲突和 `avoid` 某些逻辑会参考 `raw_score_c`，而不是只看调整后的 `score_c`。

这意味着：

1. investor bearish 的负向贡献在融合时会被削弱。
2. 但如果原始研究层已经出现强 bearish 共识，系统仍然会把这类票识别成强冲突样本。

---

## 4. Layer C 通过了，是不是就一定会有 buy order

不是。

Layer C 通过后，后面还有：

1. watchlist 阈值
2. execution blocker
3. T+1 执行桥接

所以：

1. Layer B 通过，不等于 Layer C 通过。
2. Layer C 通过，不等于最终一定有 buy order。

---

## 5. 为什么当前融合权重和产品文档不一致

因为历史设计口径和当前代码口径不同。

当前代码默认近似使用：

1. `0.55 * score_b + 0.45 * score_c`

而历史产品文档写过更偏向 Layer C 的比例。后续做过 Layer C P1 校准，当前系统分析应以代码口径为准。

---

## 6. Layer C 复盘时能不能只看支持票数

不能。

只看支持票数会遗漏：

1. bearish 权重有多强
2. investor 和 analyst 两个 cohort 谁在主导
3. 原始分歧和调整后分数是否偏离
4. watchlist 没通过到底是 `avoid` 还是 `score_final` 不够

---

## 7. `quality_score` 是不是 Agent 文本里抽出来的情绪分

不是。

它来自 Layer B 的 fundamental 质量相关子因子再提一次，主要承接：

1. `profitability`
2. `financial_health`
3. `growth`

它更像质量桥接字段，而不是文本情绪分析结果。

---

## 8. 为什么一只票过了 Layer B，却还是在 Layer C 被打回

最常见的原因有两类：

1. 研究层没有形成足够共识，导致 `score_final_below_watchlist_threshold`
2. 出现强 B/C 冲突，直接进入 `decision_avoid`

因此，这种现象不自动说明 Layer B 有问题，更可能说明 Layer C 的研究层确认没有跟上。

---

## 9. watchlist 被拒绝时，最先该看什么

建议按这个顺序：

1. 先看 `decision`
2. 再看 `bc_conflict`
3. 再看 `raw_score_c`、`score_c`、`score_final`
4. 最后看 watchlist 过滤理由是 `decision_avoid` 还是 `score_final_below_watchlist_threshold`

这一步能先区分“被明确否决”和“只是共识厚度不够”。

---

## 10. 调 Layer C 时最容易犯什么错

最常见的错有三类：

1. 把历史产品口径当作当前代码口径
2. 只看调整后的 `score_c`，忽视 `raw_score_c`
3. 只看 Layer C 过线率，不看 watchlist、buy order 和 replay 解释质量

如果忽视这三点，很容易得到“看起来通过率更高，但系统解释力和 veto 质量更差”的假改善。

---

## 11. 我应该先看 FAQ、速查卡还是长文

可以按这个顺序选：

1. 只想 5 分钟建立轮廓：看 [19-layer-c-one-page-cheatsheet.md](./19-layer-c-one-page-cheatsheet.md)
2. 已经带着具体疑问进来：先看这份 FAQ
3. 想知道整套材料怎么组织：看 [20-layer-c-topic-reading-path.md](./20-layer-c-topic-reading-path.md)
4. 准备认真复盘或调参：看 [16-layer-c-complete-beginner-guide.md](./16-layer-c-complete-beginner-guide.md)

---

## 12. 一句话总结

这份 FAQ 的作用不是替代 Layer C 长文，而是把最容易反复误会的点先收口，让你知道哪些 Layer C 直觉不能直接拿来解释真实样本。
