# Layer C 一页速查卡

适用对象：已经知道系统大框架，但在复盘、排障、讨论时需要快速判断 Layer C 含义的读者。

---

## 1. 一句话定义

Layer C 是 Layer B 之后的多 Agent 研究确认层，负责把高分候选进一步做共识确认、冲突识别和 watchlist 决策。

---

## 2. 你先记住的 6 件事

1. Layer C 不是再跑一遍规则，而是把 18 个 Agent 的观点标准化后做聚合。
2. 它不只产出 `score_c`，还会产出 `raw_score_c`、`score_final`、`quality_score`、`bc_conflict` 和 `decision`。
3. UI 里常看到的 `score_c` 是调整后的分数，不是原始研究分歧分数。
4. 当前融合默认近似为 `0.55 * score_b + 0.45 * score_c`。
5. 一只票通过 Layer B，不等于一定进入 watchlist；Layer C 仍可能把它打成 `watch` 或 `avoid`。
6. 复盘 Layer C 时不能只看“支持票数”，还要看原始冲突、cohort 贡献和 watchlist 过滤原因。

---

## 3. 最核心的 5 个字段

| 字段 | 它在回答什么 | 复盘时怎么用 |
| --- | --- | --- |
| `raw_score_c` | 原始研究层净共识有多强 | 看真实分歧，不受 investor bearish attenuation 影响 |
| `score_c` | 当前用于融合的 Layer C 分数 | 看当前系统最终怎么使用 Layer C |
| `score_final` | B/C 融合后的最终分数 | 判断是否有机会进入 watchlist |
| `bc_conflict` | Layer B 与 Layer C 是否结构性打架 | 区分“边缘票”与“强冲突票” |
| `decision` | 当前 Layer C 的决策标签 | 直接影响 watchlist 资格 |

---

## 4. Layer C 分数怎么形成

近似理解：

$$
score^{raw}_c = \sum_j w^{norm}_j \times direction_j \times \frac{confidence_j}{100} \times completeness_j
$$

然后当前代码还会做一层 investor bearish attenuation：

$$
contribution^{adjusted}_j = 0.15 \times contribution^{raw}_j
$$

条件是：

1. 该 Agent 属于 investor cohort
2. 原始贡献为负

所以：

1. `raw_score_c` 更接近真实研究分歧。
2. `score_c` 更接近当前系统真正用于融合的 Layer C 分数。

---

## 5. quality_score 速查

quality_score 不是从 Agent 文本里抽出来的，而是从 Layer B fundamental 的三个质量相关子因子再提一次：

1. `profitability`，权重 `0.40`
2. `financial_health`，权重 `0.35`
3. `growth`，权重 `0.25`

它的作用：

1. 帮助 Layer C 解释质量语境
2. 作为 fundamental 和 Layer C 之间的桥接字段

---

## 6. B/C 冲突速查

当前最重要的两类冲突：

1. `score_b > 0.50` 且 `raw_score_c < 0`
   结果：`bc_conflict = b_strong_buy_c_negative`，`decision = watch`
2. `score_b > 0` 且 `raw_score_c < -0.30`
   结果：`bc_conflict = b_positive_c_strong_bearish`，`decision = avoid`

关键点：

1. 冲突逻辑看的是 `raw_score_c`，不是调整后的 `score_c`
2. 这是为了允许边缘票穿透，但保留强冲突票 veto

---

## 7. watchlist 怎么出来

当前直观规则：

$$
score_{final} \ge WATCHLIST\_SCORE\_THRESHOLD \quad 且 \quad decision \neq avoid
$$

默认阈值：

1. `WATCHLIST_SCORE_THRESHOLD = 0.20`

最常见的 watchlist 过滤理由：

1. `decision_avoid`
2. `score_final_below_watchlist_threshold`

---

## 8. 复盘时的最小阅读顺序

1. 先看 `score_b`、`raw_score_c`、`score_c`、`score_final`。
2. 再看 `decision` 和 `bc_conflict`。
3. 再看 active / positive / negative agent 数量和 cohort 贡献。
4. 最后看 watchlist 过滤理由，判断是研究层明确反对，还是共识厚度不够。

---

## 9. 最常见的 5 个误判

1. 把 `score_c` 当作原始研究共识分数。
2. 只看支持票数，不看 bearish 权重和 cohort 贡献。
3. 把 Layer C 被拒绝误解成 Layer B 有问题。
4. 把 `decision_avoid` 和 `score_final_below_watchlist_threshold` 混成一类。
5. 忽视 `quality_score`，误以为 Layer C 完全不承接 fundamental 质量信息。

---

## 10. 需要深入时看哪里

1. 长文版：[16-layer-c-complete-beginner-guide.md](./16-layer-c-complete-beginner-guide.md)
2. 阅读路径：[20-layer-c-topic-reading-path.md](./20-layer-c-topic-reading-path.md)
3. FAQ：[21-layer-c-faq.md](./21-layer-c-faq.md)
4. factors 总目录：[17-factors-overview-home.md](./17-factors-overview-home.md)
