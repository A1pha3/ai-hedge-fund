# Layer B 一页速查卡

适用对象：已经读过主讲义，但需要在复盘、排障、讨论时快速查要点的读者。

---

## 1. 一句话定义

Layer B 是选股流水线里的规则化中间筛选层，负责把 Layer A 候选池压缩成值得进入 Layer C 深度研究的高优先级样本。

---

## 2. 你只需要先记住的 6 件事

1. Layer B 不是最终买入层。
2. Layer B 主要看四条策略：趋势、均值回归、基本面、事件情绪。
3. Layer B 不只是加权求和，还包含子因子聚合、市场状态调权和冲突仲裁。
4. `confidence` 不是单纯音量旋钮，`completeness` 也不是简单权重缩放器。
5. Layer B 放出更多票，不等于最终策略更优。
6. 看 Layer B 一定要连着看 Layer C、watchlist 和 execution bridge。

---

## 3. 四条策略速查

| 策略 | 它回答什么问题 | 核心子因子 | 默认权重 |
| --- | --- | --- | --- |
| 趋势 `trend` | 这只票是不是处于较健康的顺势结构里 | `ema_alignment`、`adx_strength`、`momentum`、`volatility` | 0.30 |
| 均值回归 `mean_reversion` | 价格是不是偏离太多，存在回归机会 | `zscore_bbands`、`rsi_extreme`、`stat_arb`、`hurst_regime` | 0.20 |
| 基本面 `fundamental` | 经营质量、成长质量、估值支撑够不够 | `profitability`、`growth`、`financial_health`、`growth_valuation`、`industry_pe` | 0.30 |
| 事件情绪 `event_sentiment` | 最近新闻、事件、内部人行为是在加分还是减分 | `news_sentiment`、`insider_conviction`、`event_freshness` | 0.20 |

---

## 4. 两层公式速查

### 4.1 单策略内部聚合

近似理解：

$$
score_{strategy} = \sum_k w_k \times direction_k \times \frac{confidence_k}{100}
$$

然后再根据方向一致性得到整条策略的最终 `direction`、`confidence`、`completeness`。

### 4.2 Layer B 总分融合

$$
Score_B = \sum_i w_i \times direction_i \times \frac{confidence_i}{100} \times completeness_i
$$

这里的关键是：

1. `direction` 决定正负。
2. `confidence` 决定强弱。
3. `completeness` 决定证据是否完整。
4. `w_i` 会被市场状态和 active 集合重新归一化。

---

## 5. Layer B 决策阈值速查

| `score_b` 区间 | 决策标签 | 你应该怎么理解 |
| --- | --- | --- |
| `> 0.50` | `strong_buy` | Layer B 明确强正，但仍不等于最终一定买 |
| `0.35 ~ 0.50` | `watch` | 值得继续研究，通常进入后续链路 |
| `-0.20 ~ 0.35` | `neutral` | 规则层优势不够厚，通常不会优先推进 |
| `-0.50 ~ -0.20` | `sell` | 偏负，通常不作为候选 |
| `< -0.50` | `strong_sell` | 强烈回避，很多情形还会进入冷却逻辑 |

---

## 6. Replay Artifacts 里怎么读 Layer B

按下面顺序最稳。

1. 先看 `selection_review.md` 里的 Layer B 因子摘要。
2. 再看 `selection_snapshot.json` 里的 `layer_b_summary`。
3. 再看 `funnel_diagnostics.filters.layer_b`。
4. 最后再和 `layer_c_summary`、`watchlist`、`execution_bridge` 对照。

如果不按这个顺序，很容易混淆：

1. 是 Layer B 本身没放行。
2. 还是 Layer C 否决了它。
3. 还是 execution 最终没承接。

---

## 7. 解释可信度分级速查

| 等级 | 含义 | 使用口径 |
| --- | --- | --- |
| A 档 | 原生 `strategy_signals` 解释 | 可用于细粒度因子和规则讨论 |
| B 档 | 基于原生信号的渲染摘要 | 适合复盘和培训，排障时最好回到底层字段 |
| C 档 | 兼容回退解释，例如 `legacy_plan_fields` | 只能作为辅助线索，不宜下最高强度结论 |

如果你看到：

1. `explanation_source = legacy_plan_fields`
2. `fallback_used = true`

就默认按 C 档处理。

---

## 8. 最常见的 5 个坑

1. 以为 `confidence` 调小就是温和化规则。
2. 以为 `completeness` 从 `1.0` 改到 `0.5` 就等于只占半份归一化席位。
3. 以为 Layer B 通过数增加就说明规则优化成功。
4. 以为 `watch` 已经等于快下单。
5. 以为 Layer B 分高的票没成交，就是 Layer B 出错。

---

## 9. 当前这条主线最重要的实验结论

1. `profitability` 的 hard cliff 是真实问题，但不能只靠调低 `confidence` 解决。
2. 中性 `mean_reversion` 持续参与 active 归一化，确实会稀释 `trend + fundamental` 双主腿。
3. 粗暴排除中性均值回归会释放过多样本，风险很高。
4. 一些 Layer B 放宽实验虽然增加了候选，但很多新增样本最终死在 Layer C 或 watchlist。
5. 因此，Layer B 变更必须和整条漏斗一起看，不能只看 `layer_b_count`。

---

## 10. 复盘时的最小判断模板

如果你只想快速写一句判断，用下面模板最稳：

1. “Layer B 主要由哪两条策略支撑。”
2. “这份解释是原生证据还是回退解释。”
3. “最终未成交的主因是在 Layer C、watchlist，还是 execution。”

示例：

“该样本在 Layer B 上主要由 fundamental 和 trend 支撑，属于规则层面较完整的候选；但当前解释来自 fallback，结论应保守，最终未成交的直接原因是 execution blocker，而不是 Layer B 未放行。”

---

## 11. 需要深入时看哪里

1. 主讲义：[03-layer-b-complete-beginner-guide.md](./03-layer-b-complete-beginner-guide.md)
2. 语义陷阱：[01-aggregation-semantics-and-factor-traps.md](./01-aggregation-semantics-and-factor-traps.md)
3. 规则实验：[../analysis/layer-b-rule-variant-validation-20260312.md](../analysis/layer-b-rule-variant-validation-20260312.md)
4. 选股页面读法：[../manual/replay-artifacts-stock-selection-manual.md](../manual/replay-artifacts-stock-selection-manual.md)
