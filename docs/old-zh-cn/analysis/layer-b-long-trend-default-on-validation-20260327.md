# Layer B 长期趋势因子默认开启验证

文档日期：2026 年 3 月 27 日  
适用范围：默认 Layer B 趋势策略  
验证窗口：2026-03-02 至 2026-03-26 的 19 个交易日  
结果产物：data/reports/layer_b_rule_variants_long_trend_default_on_202603_20260327.json  
验证脚本：scripts/analyze_layer_b_rule_variants.py

---

## 1. 这轮验证回答什么问题

这轮不是重新评估 profitability、mean_reversion 或 Layer C，而是只回答一个更窄的问题：

1. 把 `long_trend_alignment` 设为默认开启后，当前 202603 缓存窗口里的 Layer B 过线结果会不会发生明显变化。
2. 如果变化不明显，是否说明它只是补充解释能力，而不是当前窗口里的主要放量来源。

为了保证对照清楚，本轮使用：

1. `baseline`：默认开启 `LAYER_B_ANALYSIS_ENABLE_LONG_TREND_ALIGNMENT`
2. `long_trend_alignment_disabled`：显式关闭长期趋势因子

这比旧的“baseline vs long_trend_alignment_only”更适合当前主线，因为长期趋势因子现在已经是默认规则的一部分。

---

## 2. 默认规则现在是什么

当前默认趋势策略包含五个子因子：

1. `ema_alignment`
2. `adx_strength`
3. `momentum`
4. `volatility`
5. `long_trend_alignment`

其中：

1. `ema_alignment` 继续负责短中期 `EMA10 / EMA30 / EMA60` 排列语义。
2. `long_trend_alignment` 负责长期 `EMA10 / EMA200` 背景确认。
3. 两者并列存在，不互相替代。

默认权重为：

1. `ema_alignment = 0.26`
2. `adx_strength = 0.21`
3. `momentum = 0.21`
4. `volatility = 0.17`
5. `long_trend_alignment = 0.15`

---

## 3. 验证方法

本轮回放命令等价于：

```bash
/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.venv/bin/python \
  scripts/analyze_layer_b_rule_variants.py \
  --month-prefix 202603 \
  --variants long_trend_alignment_disabled \
  --output data/reports/layer_b_rule_variants_long_trend_default_on_202603_20260327.json
```

验证基于 `data/snapshots` 里的缓存候选池完成，因此即使终端里出现 `TUSHARE_TOKEN` 未初始化告警，回放仍然成功产出了结果文件。

---

## 4. 核心结果

窗口结果非常直接：

1. `baseline_total_layer_b_passes = 1`
2. `long_trend_alignment_disabled.variant_total_layer_b_passes = 1`
3. `layer_b_pass_delta = 0`
4. `added_sample_count = 0`
5. `removed_sample_count = 0`

按日看，19 个交易日里只有 `20260325` 出现了 1 次 Layer B 通过，其余交易日 baseline 与关闭版都完全一致。

这说明在当前 202603 窗口里：

1. 默认开启长期趋势因子没有释放新的 Layer B 过线样本。
2. 关闭长期趋势因子也没有拿掉已有过线样本。
3. 它在当前窗口里更像是“补充背景确认”，而不是“直接放量阀门”。

---

## 5. 应该如何解读这个结果

这个结果**不是**说长期趋势因子没有意义，而是说：

1. 在当前 202603 这 19 个交易日里，原有趋势主干已经足以决定是否过 Layer B。
2. 新增的 `long_trend_alignment` 没有把任何边缘票推过 `0.38` 快速门槛。
3. 同时，它也没有制造额外的放量副作用。

所以这轮验证更像是在证明两件事：

1. 把它默认打开目前是安全的。
2. 它至少在当前窗口里不是一个高风险、强放量的规则改动。

---

## 6. 结论

当前可以形成的业务结论是：

1. `long_trend_alignment` 可以保留为默认开启规则。
2. 当前 202603 窗口没有证据表明它会显著扩大 Layer B 通过量。
3. 它更适合作为趋势解释与长期背景确认的补充，而不是作为主放量杠杆来期待。

如果后续还要继续验证，优先级更高的不是再调这个因子的默认开关，而是：

1. 找更长窗口或更有代表性的历史样本，看它是否能在边缘趋势票上稳定发挥作用。
2. 继续观察它在 Replay Artifacts 页面中的解释价值，尤其是那些短中期结构刚转强、但长期背景也已改善的样本。
