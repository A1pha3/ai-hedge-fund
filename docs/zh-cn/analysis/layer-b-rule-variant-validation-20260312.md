# Layer B 最小规则变体验证

文档日期：2026 年 3 月 12 日  
适用范围：默认 CLI / backtester pipeline  
验证窗口：2026-02-02 至 2026-02-27 的 20 个交易日  
结果产物：data/reports/layer_b_rule_variants_202602_20260312.json  
验证脚本：scripts/analyze_layer_b_rule_variants.py

---

## 1. 这轮验证回答什么问题

本轮不是重新讨论 provider、rolling scheduler 或 Web/API，而是严格围绕同一条主业务线，按顺序验证三件事：

1. profitability 单改是否能温和释放 Layer B 边缘样本。
2. neutral mean_reversion 退出 active 归一化后会释放多少样本，以及风险是否过高。
3. 两者联合后是否过猛。

所有验证都通过默认 CLI / backtester pipeline 的真实 Layer B 路径完成，没有先改 `FAST_AGENT_SCORE_THRESHOLD`。

---

## 2. 先记录一个与既有文档冲突的事实

本轮 fresh replay 与前面文档里记录的绝对基线数存在冲突：

1. 之前文档与 repo memory 记录的 2026-02 20 日窗口 baseline 是 `4` 次 Layer B 通过。
2. 当前工作区在 2026-03-12 这次 fresh replay 下，baseline 只得到 `1` 次 Layer B 通过。
3. 这说明当前窗口的绝对通过数存在漂移，至少说明本地快照或上游数据可得性与前一轮记录不是完全冻结状态。

因此，本轮验证仍然可用于比较三种变体的相对增量，但**不应直接拿当前 fresh replay 的绝对通过数去覆盖之前的历史扫描结论**。

本轮后续结论都按“相对 baseline 增量”来解释。

---

## 3. 第一步：profitability 单独验证

### 3.1 首轮实现先出现了语义副作用

本轮先按最直觉的分析分支做了一个候选版本：

1. 把 `0 项达标 => 强负` 改成 `direction = 0`
2. 但仍让该 sub-factor 以 active 身份参与 fundamental 聚合

结果这个版本对 `600111` 出现了明显反效果：

1. `20260209` baseline 下 `600111` 的 `score_b = 0.4390`，可以过线。
2. 同一日把 profitability 改成“active-neutral”后，`score_b` 反而掉到 `0.3563`。
3. fundamental 的聚合 confidence 也从 `57.35` 掉到 `35.29`。
4. 仲裁还从无动作变成了 `short_hold`。

这和前面因子语义文档的主结论一致：**只把硬负改成“中性但仍 active”，仍然会通过聚合一致性语义伤害结果。**

### 3.2 因此本轮正式验证采用了更稳的温和语义

为了继续完成第一步验证，本轮把 profitability 的分析分支改成：

1. 仅当 `0 项达标` 时
2. 输出“温和但不参与聚合”的语义
3. 具体表现为 `direction = 0`、`confidence = 0`、`completeness = 0`

这仍然是分析用最小改动，不改默认生产规则。

### 3.3 窗口结果

在这个 revised profitability 分支下：

1. Layer B 总通过数从 `1` 提升到 `4`。
2. 净增 `3` 个过线样本。
3. 没有出现任何 baseline 已过线样本被拿掉的情况。

新增过线样本只有：

1. `300065` on `20260223`
2. `300065` on `20260224`
3. `300065` on `20260225`

### 3.4 新增样本主要是哪类票

新增样本高度集中，没有扩散：

1. 行业全部是 `国防军工`。
2. 三条记录都是同一只票 `300065` 的连续三天。
3. 标签结构全部一致：`profitability_hard_cliff`、`trend_fundamental_dual_leg`、`event_sentiment_missing`。

这说明 profitability 单改主要释放的是：

1. 已经有 trend 主干
2. fundamental 总体仍可为正
3. 但被 profitability 硬 cliff 卡住的边缘票

### 3.5 是否出现明显过度释放

没有。

证据很直接：

1. 只新增 `3` 条样本。
2. 全部是同一只边缘票 `300065`，没有向多行业、多风格扩散。
3. 单样本分数抬升也很克制，都是 `+0.0135` 左右，从 `0.3735 ~ 0.3739` 仅仅推到 `0.3870 ~ 0.3874`。

本轮 fresh replay 下，profitability 单改是**收益有限但风险最可控**的一刀。

---

## 4. 第二步：neutral mean_reversion 单独验证

### 4.1 验证语义

本轮按既定优先方案验证了：

1. 当 `mean_reversion.direction == 0`
2. 不让它进入 Layer B active 归一化集合

没有再做已被证明无效的 completeness 降到 `0.5` / `0.25` 版本。

### 4.2 窗口结果

窗口结果非常激进：

1. Layer B 总通过数从 `1` 跳到 `55`。
2. 净增 `54` 个过线样本。
3. 几乎从 `20260209` 之后连续多日都新增过线。

### 4.3 新增样本是否过多

是，明显过多。

行业分布：

1. `有色金属`：23
2. `电子`：16
3. `传媒`：13
4. `电力设备`：2

按日看也不是零星释放，而是持续放量：

1. `20260210` 到 `20260227` 大多数交易日都有 `3 ~ 5` 个新增样本。
2. 单日最高新增达到 `5`。

### 4.4 是否明显偏向 trend + fundamental 双腿结构

是，偏向非常明显。

标签统计：

1. `neutral_mean_reversion_active`：54
2. `trend_fundamental_dual_leg`：54
3. `event_sentiment_missing`：53
4. `profitability_hard_cliff`：23

这说明新增样本几乎清一色是：

1. trend 为正
2. fundamental 为正
3. event_sentiment 仍然缺席
4. 原先只是被 neutral mean_reversion 稀释掉

换句话说，这一刀的收益几乎全部来自把 trend + fundamental 双腿结构整体放大。

### 4.5 风险是否高于 profitability 单改

明显高于。

原因不是它方向错，而是它的量级过大：

1. profitability 单改只释放 `3` 条样本。
2. neutral mean_reversion 单改直接释放 `54` 条。
3. 且释放出来的样本高度集中在同一种结构上，说明风格暴露会显著放大。

因此，它虽然是**单刀收益最大的候选**，但也是**单刀风险最大的候选**。

---

## 5. 第三步：联合验证

### 5.1 窗口结果

在 profitability 与 neutral mean_reversion 联合后：

1. Layer B 总通过数从 `1` 跳到 `82`。
2. 净增 `81` 个过线样本。
3. 单日新增在后半窗口经常达到 `5 ~ 9` 个。

### 5.2 联合样本结构

行业分布进一步扩散：

1. `电子`：31
2. `有色金属`：24
3. `传媒`：15
4. `国防军工`：5
5. `汽车`：3
6. `电力设备`：2
7. `通信`：1

标签统计也说明联合版本把两类问题叠加放大了：

1. `event_sentiment_missing`：80
2. `neutral_mean_reversion_active`：78
3. `trend_fundamental_dual_leg`：70
4. `profitability_hard_cliff`：50

### 5.3 联合后是否过猛

是，过猛。

本轮 fresh replay 下：

1. profitability 单改已经证明可以克制地释放边缘票。
2. neutral mean_reversion 单改已经显示出高度敏感。
3. 两者联合后直接从 `1` 走到 `82`，量级已经超出“最小规则验证”的安全区间。

因此，联合版本目前只能当作上边界测试，不适合作为默认规则候选。

---

## 6. 最终业务结论

把三步结果并排看，本轮 fresh replay 的结论很清楚：

1. **收益最稳的一刀**：profitability 单改。
2. **单刀收益最大的一刀**：neutral mean_reversion 单改。
3. **单刀风险最大的一刀**：neutral mean_reversion 单改。
4. **整体最猛的版本**：联合版本。
5. **联合后是否过猛**：是，明显过猛。

如果继续沿当前主业务线推进，更稳的排序仍然应该是：

1. 先把 profitability 作为更有希望的默认规则候选继续看。
2. neutral mean_reversion 只能继续做带保护的分析，不应直接形成默认规则。
3. 联合版本暂时只保留为边界证据。

---

## 7. 本轮同时确认的实现层结论

这轮代码与回放还额外确认了一点：

1. profitability 的“温和化”不能简单做成 active-neutral。
2. 否则它仍会通过 `aggregate_sub_factors()` 的一致性语义伤害 fundamental 输出。
3. 所以如果后续继续推进 profitability 默认规则，候选实现应更接近“温和但不参与聚合”，而不是“中性但继续占位”。

这点需要和前面的因子语义文档一起看，不能单独理解。