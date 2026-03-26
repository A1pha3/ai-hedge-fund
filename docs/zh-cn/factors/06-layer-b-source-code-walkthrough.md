# Layer B 源码导读：按函数顺序看实现

适用对象：已经理解 Layer B 概念，现在想直接读源码、定位逻辑和调试路径的开发者。

---

## 1. 这份导读解决什么问题

主讲义解释的是“Layer B 是什么”。

这份文档解释的是：

1. 代码到底分布在哪几个文件里。
2. 一条候选股票是按什么顺序被打分的。
3. 哪些函数负责聚合，哪些函数负责仲裁，哪些函数负责调权。
4. 如果你要排障或做实验，最应该从哪几个函数下手。

---

## 2. 三个最重要的源码入口

如果你只看三个文件，就先看这三个：

1. [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py)
2. [src/screening/signal_fusion.py](../../src/screening/signal_fusion.py)
3. [src/screening/market_state.py](../../src/screening/market_state.py)

它们各自负责：

1. `strategy_scorer.py`：四条策略怎么打分。
2. `signal_fusion.py`：四条策略怎么融合、怎么仲裁。
3. `market_state.py`：市场状态如何改变权重。

配套数据结构在 [src/screening/models.py](../../src/screening/models.py)。

配套测试在 [tests/screening/test_phase2_screening.py](../../tests/screening/test_phase2_screening.py)。

---

## 3. 先建立运行顺序

一只候选股票进入 Layer B，大致按这个顺序走：

```text
score_batch / score_candidate
  -> 各策略 score_xxx_strategy
  -> aggregate_sub_factors
  -> detect_market_state
  -> apply_arbitration_rules
  -> compute_score_b
  -> fuse_signals_for_ticker
```

如果你读代码时总觉得乱，通常是因为把“单策略打分”和“多策略融合”混在了一起。

建议永远分成两层来看：

1. 单策略层：每条策略如何从子因子变成 `StrategySignal`。
2. 融合层：多条 `StrategySignal` 如何变成 `FusedScore`。

---

## 4. 先看模型：输入输出长什么样

先读 [src/screening/models.py](../../src/screening/models.py)。

重点看四个对象：

1. `SubFactor`
2. `StrategySignal`
3. `MarketState`
4. `FusedScore`

推荐阅读顺序：

1. 先看 `SubFactor`，理解最小因子单位有哪些字段。
2. 再看 `StrategySignal`，理解每条策略的标准化输出。
3. 再看 `MarketState`，理解权重为什么会变化。
4. 最后看 `FusedScore`，理解 Layer B 最终输出长什么样。

如果你不先把这四个对象看懂，后面函数名再多也只是细节噪声。

---

## 5. strategy_scorer.py 怎么读

### 5.1 第一段：常量区

文件开头先定义了很多常量：

1. `LIGHT_STRATEGY_WEIGHTS`
2. `TECHNICAL_SCORE_MAX_CANDIDATES`
3. `FUNDAMENTAL_SCORE_MAX_CANDIDATES`
4. `EVENT_SENTIMENT_MAX_CANDIDATES`
5. 四套子因子权重字典

这里的价值不是背下来，而是确认两件事：

1. 策略内部权重是显式写死的，不是隐式魔法。
2. 批量打分是分阶段的，不是对所有候选做同样重计算。

### 5.2 第二段：通用工具函数

建议先看这些函数：

1. `_clip()`
2. `_signal_to_direction()`
3. `_safe_date()`
4. `compute_event_decay()`
5. `derive_completeness()`

这几类函数解决的都是“统一语义”问题。

例如 `compute_event_decay()`：

$$
w(t) = e^{-0.35t}
$$

它把事件新鲜度的衰减写死成统一规则，避免不同地方各自定义事件时效。

### 5.3 第三段：最核心的聚合器 `aggregate_sub_factors()`

这是 Layer B 最值得精读的函数之一。

建议按下面顺序看：

1. 先过滤 `completeness > 0` 的子因子。
2. 再对可用子因子的权重归一化。
3. 再算方向分数 `score`。
4. 根据 `score` 的正负给整条策略定方向。
5. 再通过“和最终方向一致的子因子比例”算 `consistency`。
6. 最后再得到策略级 `confidence` 和 `completeness`。

如果你只看这个函数，就能理解两个反直觉现象：

1. 为什么调低某个负项 `confidence` 可能反而让结果更差。
2. 为什么改一个子因子的 active 身份，会影响整条策略结构。

### 5.4 第四段：趋势策略怎么实现

建议顺序看：

1. `_score_ema_alignment()`
2. `_score_adx_strength()`
3. `score_trend_strategy()`

这里有一个很适合新手抓住的点，就是你当前选中的那几行文案对应的代码来源。

在 `_score_ema_alignment()` 里，`ema_10`、`ema_30`、`ema_60` 先被计算出来，再通过它们之间的相对间距得到 `confidence`。

所以文档里这句：

1. 不是人工拍脑袋给的。
2. 而是看几条均线彼此的间距占当前价格的比例。
3. 均线拉得越开，趋势表达越清晰，置信度越高。

对应的不是概念化比喻，而是 `_score_ema_alignment()` 里的真实实现语义。

如果你要验证这点，直接看这个函数最有效。

### 5.5 第五段：均值回归策略怎么实现

建议顺序看：

1. `score_mean_reversion_strategy()`
2. 里面的 `rsi_factor` 构造逻辑
3. `hurst` 和 `z_score` 的组合逻辑

重点关注两个点：

1. `Hurst` 不只是输出给你看，它还会影响 `hurst_regime` 的方向与置信度。
2. 这也是后面趋势和均值回归冲突时，仲裁器要回头读取的重要信息源。

### 5.6 第六段：基本面策略怎么实现

建议顺序看：

1. `_score_profitability()`
2. `_score_growth()`
3. `_score_financial_health()`
4. `_score_growth_valuation()`
5. `_score_industry_pe()`
6. `score_fundamental_strategy()`

其中最关键的是 `_score_profitability()`。

这个函数里要注意三件事：

1. 默认 `zero_pass_mode` 是什么。
2. `positive_count == 0` 时如何落到 hard cliff 语义。
3. 实验模式下的 `inactive`、`neutral` 路径如何改变输出。

如果你要做 profitability 相关实验，第一站永远是这个函数。

### 5.7 第七段：事件情绪策略怎么实现

建议顺序看：

1. `_score_news_sentiment()`
2. `_score_insider_conviction()`
3. `_score_event_freshness()`
4. `score_event_sentiment_strategy()`

读这部分时要有一个现实预期：

1. 它不是高成本语义理解器。
2. 它是面向 Layer B 批量筛选的轻量规则化事件近似器。

### 5.8 第八段：批量打分是怎么分层的

最后看：

1. `_compute_light_signals()`
2. `_provisional_score()`
3. `_rank_candidates_for_technical_stage()`
4. `score_batch()`

这几段一起决定了：

1. 哪些票只做轻量技术评分。
2. 哪些票会进一步拿到 fundamental 计算。
3. 哪些票最终有资格拿到 event_sentiment 计算。

如果你发现某个候选缺事件层字段，先别急着怀疑数据坏了，先回头看它是不是根本没走到更重的阶段。

---

## 6. signal_fusion.py 怎么读

### 6.1 第一段：分析开关和实验开关

建议先看这些函数：

1. `_analysis_excludes_neutral_mean_reversion()`
2. `_get_neutral_mean_reversion_mode()`
3. `_quality_first_guard_enabled()`

这部分很重要，因为它告诉你：

1. 哪些逻辑是默认生产行为。
2. 哪些逻辑只是分析实验开关。

如果你不先区分这点，就很容易把实验结论误写成当前默认规则。

### 6.2 第二段：active 归一化是怎么做的

接着看：

1. `_normalize_active_weights()`
2. `_normalize_for_available_signals()`

核心理解只有一句：

**只要 `completeness > 0`，它通常就还在 active 集合里。**

这也是中性 `mean_reversion` 为什么会成为长期讨论对象的根因。

### 6.3 第三段：为什么会有 hard cliff 和 quality red flag

建议顺序看：

1. `_is_hard_cliff_profitability()`
2. `_get_sub_factor_snapshot()`
3. `_has_quality_first_red_flag()`

这几段一起定义了：

1. 哪些候选属于“质量问题已经足够严重”的票。
2. 为什么有些票明明趋势和事件不差，却仍然会被强制 `avoid`。

如果你要解释“为什么这票被一票否决”，通常要先读这里。

### 6.4 第四段：neutral mean_reversion 实验是怎么落地的

建议精读：

1. `_should_exclude_neutral_mean_reversion()`

这个函数里能直接看到：

1. `full_exclude` 为什么危险。
2. `guarded_dual_leg_033_no_hard_cliff` 这类模式为什么更保守。
3. 哪些条件下中性均值回归才会被允许排除出 active 集合。

如果你在研究 guarded 模式，这是最核心的代码入口。

### 6.5 第五段：仲裁规则怎么逐层落地

接着看：

1. `maybe_release_cooldown_early()`
2. `apply_arbitration_rules()`

其中 `apply_arbitration_rules()` 是第二个最值得精读的主函数。

建议按这个顺序看：

1. quality-first guard
2. fundamental 负面 + 强负信号直接 `avoid`
3. `short_hold` / `long_hold` 识别
4. 趋势与均值回归冲突时的 Hurst 仲裁
5. 三条以上同向时的 `consensus_bonus`

如果你想回答“为什么最后多了一个 `avoid`、`short_hold`、`trust_trend`”，答案基本都在这里。

### 6.6 第六段：总分怎么真正算出来

最后看：

1. `compute_score_b()`
2. `fuse_signals_for_ticker()`
3. `fuse_batch()`

你会看到：

1. active 权重先被归一化。
2. 分数再按方向、置信度、完整度计算。
3. 如果命中 `consensus_bonus`，再乘 `1.15`。
4. 如果被强制 `avoid`，则 `score_b = -1.0` 且直接 `strong_sell`。

这就是 Layer B 最终决策形成的最后一跳。

---

## 7. market_state.py 怎么读

这一文件建议按下面顺序看：

1. `_normalize_weights()`
2. `_northbound_streak()`
3. `detect_market_state()`

真正的主函数只有一个：`detect_market_state()`。

读它时重点关注：

1. 哪些市场指标被读取。
2. `TREND`、`RANGE`、`CRISIS` 分别怎么触发。
3. 触发后是改权重，还是改 `position_scale`。

如果你只想快速理解市场状态对 Layer B 的影响，直接看 `adjusted[...] += ...` 和 `adjusted[...] -= ...` 这些语句就够了。

---

## 8. 调试 Layer B 时，最值得下断点的地方

如果你要实战调试，推荐断点顺序如下：

1. `score_candidate()` 或 `score_batch()`
2. `aggregate_sub_factors()`
3. `_score_profitability()` 或 `_should_exclude_neutral_mean_reversion()`
4. `detect_market_state()`
5. `apply_arbitration_rules()`
6. `compute_score_b()`
7. `fuse_signals_for_ticker()`

这套顺序能最快回答三个问题：

1. 单策略是怎么形成的。
2. active 权重是怎么被改写的。
3. 最终为什么过线或不过线。

---

## 9. 如果你要追一只股票，最小排障路径是什么

以单 ticker 为例，建议按下面顺序问：

1. 这只票的四条 `StrategySignal` 分别是什么。
2. 有没有子因子被 `completeness = 0` 过滤掉。
3. 当前市场状态把默认权重改成了什么。
4. 有没有命中 `quality_first_guard`、`hard_cliff`、`trust_trend` 之类仲裁动作。
5. 最终 active 权重是不是被中性 `mean_reversion` 稀释了。
6. `score_b` 是否刚好卡在阈值边缘。

如果这六步走完，你通常已经能判断问题更像：

1. 子因子语义问题。
2. active 归一化问题。
3. 阈值问题。
4. 下游 Layer C / execution 问题。

---

## 10. 测试文件应该怎么配合着读

不要只读生产代码，也要读 [tests/screening/test_phase2_screening.py](../../tests/screening/test_phase2_screening.py)。

这份测试最有价值的地方是，它把很多设计意图写成了可执行断言。

建议重点看：

1. `test_completeness_derivation`
2. `test_event_decay`
3. `test_trend_market_weights`
4. `test_safety_first_rule`
5. `test_hurst_arbitration`
6. `test_consensus_bonus_and_score_range`
7. `test_quality_first_guard_blocks_low_quality_candidates_despite_positive_momentum`
8. neutral mean reversion 相关测试

如果你看到代码一时看不懂，先去看测试名，通常会更快理解作者想保护什么行为。

---

## 11. 源码阅读顺序建议

如果你是第一次读，建议按下面顺序：

1. [src/screening/models.py](../../src/screening/models.py)
2. [src/screening/strategy_scorer.py](../../src/screening/strategy_scorer.py) 中的 `aggregate_sub_factors()`
3. 同文件中的四条 `score_xxx_strategy()`
4. [src/screening/market_state.py](../../src/screening/market_state.py)
5. [src/screening/signal_fusion.py](../../src/screening/signal_fusion.py) 中的 active 归一化和仲裁函数
6. 同文件中的 `compute_score_b()` 与 `fuse_signals_for_ticker()`
7. [tests/screening/test_phase2_screening.py](../../tests/screening/test_phase2_screening.py)

这样读的好处是：

1. 先建模，再看打分。
2. 先单策略，再多策略。
3. 最后再用测试反证自己有没有理解歪。

---

## 12. 一页结论

Layer B 的代码并不神秘，它本质上就是三层：

1. `strategy_scorer.py` 负责把原始数据变成四条标准化策略信号。
2. `market_state.py` 负责根据市场环境改权重。
3. `signal_fusion.py` 负责 active 归一化、冲突仲裁和最终融合。

真正最值得精读的函数只有三个：

1. `aggregate_sub_factors()`
2. `apply_arbitration_rules()`
3. `compute_score_b()`

如果把这三个函数看懂，再配上 profitability 和 neutral mean reversion 两条实验主线，你就已经抓住了 Layer B 实现的核心。
