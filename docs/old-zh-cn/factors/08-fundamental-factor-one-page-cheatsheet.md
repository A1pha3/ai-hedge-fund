# Fundamental 因子一页速查卡

适用对象：已经知道 Layer B 大框架，但在复盘、排障、讨论时需要快速判断 fundamental 因子含义的读者。

---

## 1. 一句话定义

fundamental 是 Layer B 里的质量锚策略，负责用盈利、增长、财务健康和相对估值，快速判断一只股票是否具备中期可研究价值。

---

## 2. 你先记住的 6 件事

1. fundamental 不是只看 PE，也不是只看利润，而是五个子因子的复合策略。
2. 它在 Layer B 默认权重里占 `0.30`，和 trend 并列第一权重。
3. 它经常成为主压制项，不等于规则有 bug，更常见是候选本身质量不够正。
4. profitability 是最敏感的硬门槛，因为 `0 项达标` 默认会直接走强负分支。
5. fundamental 不只是影响 `score_b`，还会影响 Layer C 质量分和 fundamental-driven 持仓语义。
6. 复盘时必须分清：是 fundamental 本身给负分，还是根本没拿到完整 fundamental 评分。

---

## 3. 五个子因子速查

| 子因子 | 它在问什么 | 典型判定逻辑 | 默认权重 |
| --- | --- | --- | --- |
| `profitability` | 盈利能力底线是否过关 | `ROE`、`net_margin`、`operating_margin` 三项至少两项达标才明显偏正 | 0.25 |
| `growth` | 增长趋势是否可信 | 基于最近多期 `ttm` 数据判断增长质量，`score > 0.6` 才明显偏正 | 0.25 |
| `financial_health` | 财务结构是否健康 | 看偿债、杠杆、流动性等质量约束，弱时会明显拖累整体 | 0.20 |
| `growth_valuation` | 成长是否配得上当前估值 | 不是越便宜越好，而是成长和估值是否匹配 | 0.15 |
| `industry_pe` | 相对行业是贵还是便宜 | 看 `current_pe / industry_median_pe`，避免跨行业硬比 PE | 0.15 |

---

## 4. profitability 速查

当前阈值：

1. `ROE >= 0.15`
2. `net_margin >= 0.20`
3. `operating_margin >= 0.15`

默认判定：

1. `2` 项及以上达标：正向
2. `1` 项达标：中性
3. `0` 项达标：负向

实验开关：

1. `LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE = bearish|neutral|inactive`

最重要的业务直觉：

1. 它不是连续扣分器，更像硬 cliff。
2. 只调 `confidence` 往往不是正确修法。

---

## 5. fundamental 信号怎么形成

先做子因子聚合，再进入 Layer B 融合。

近似理解：

$$
score_{fundamental} = \sum_k normalized\_weight_k \times direction_k \times \frac{confidence_k}{100}
$$

然后再结合方向一致性，得到策略级：

1. `direction`
2. `confidence`
3. `completeness`

关键点：

1. 子因子不是简单相加。
2. 数据缺失会改变 active 集合和归一化权重。
3. 子因子互相打架时，最终 confidence 会被 consistency 压低。

---

## 6. 为什么它经常压住大多数股票

通常是这三类原因叠加：

1. 候选本身盈利、增长、财务健康并不够正。
2. profitability hard cliff 把一部分边缘票直接推向负向。
3. fundamental 本来就是质量因子，不会像趋势腿那样对大量样本频繁亮绿灯。

所以看到 fundamental 压制多，不要直接理解成“它太严了”，而应先理解成“它在系统里承担质量过滤职责”。

---

## 7. 复盘时的最小阅读顺序

1. 先看 fundamental 的 `direction / confidence / completeness`。
2. 再看五个子因子里到底是谁在拖累。
3. 再看这只票有没有拿到完整 fundamental 评分。
4. 最后再放回 Layer B 融合，判断是它自身冷，还是被其他腿抵消。

---

## 8. 最常见的 5 个误判

1. 把 fundamental 误解成“估值因子”。
2. 把 profitability 误解成“只要调低 confidence 就会放松”。
3. 把 fundamental 低通过率误解成“因子没用”。
4. 把所有 fundamental 负向样本都归因到 profitability。
5. 忽视重评分覆盖率，误把“没评分”当成“被评分后看空”。

---

## 9. 需要深入时看哪里

1. 专题版：[07-fundamental-factor-professional-guide.md](./07-fundamental-factor-professional-guide.md)
2. profitability 专题：[09-profitability-subfactor-professional-guide.md](./09-profitability-subfactor-professional-guide.md)
3. 语义陷阱：[01-aggregation-semantics-and-factor-traps.md](./01-aggregation-semantics-and-factor-traps.md)
4. growth 专题：[10-growth-subfactor-professional-guide.md](./10-growth-subfactor-professional-guide.md)
5. financial health 专题：[11-financial-health-subfactor-professional-guide.md](./11-financial-health-subfactor-professional-guide.md)
6. 源码导读：[06-layer-b-source-code-walkthrough.md](./06-layer-b-source-code-walkthrough.md)
7. growth valuation 专题：[12-growth-valuation-subfactor-professional-guide.md](./12-growth-valuation-subfactor-professional-guide.md)
8. industry pe 专题：[13-industry-pe-subfactor-professional-guide.md](./13-industry-pe-subfactor-professional-guide.md)
9. 专题首页：[14-fundamental-topic-reading-path.md](./14-fundamental-topic-reading-path.md)
10. 联动复盘手册：[15-fundamental-subfactor-joint-review-manual.md](./15-fundamental-subfactor-joint-review-manual.md)
11. FAQ：[18-fundamental-faq.md](./18-fundamental-faq.md)
