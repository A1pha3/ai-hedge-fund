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

---

## 8. 2026-03-13 补充验证：扩窗 profitability 与 guarded mean_reversion

补充结果产物：

1. `data/reports/layer_b_rule_variants_20260_20260313.json`：把 profitability 继续扩到当前可用 `20260*` 快照，实际覆盖 `20260202 .. 20260303`。
2. `data/reports/layer_b_rule_variants_202602_20260313.json`：在原 2026-02 窗口内加入 guarded neutral mean_reversion 版本后重新回放。

### 8.1 profitability 扩窗后仍然稳定

把 profitability inactive 分支继续扩到当前可用的 21 日窗口后，结论没有变化：

1. baseline 仍是 `1` 次 Layer B 通过。
2. profitability-only 仍是 `4` 次 Layer B 通过，净增仍是 `+3`。
3. 新增样本仍然只有 `300065` on `20260223 / 20260224 / 20260225`。
4. 新加入的 `20260303` 没有带来新的放量样本。

这说明 profitability 的“温和但不参与聚合”语义，在当前可用扩窗范围内仍然只是在释放同一类硬 cliff 边缘票，没有出现向更多行业或更多结构扩散的迹象。

### 8.2 guarded neutral mean_reversion 的四个版本

为避免 full exclude 直接从 `1 -> 55`，本轮增加了四个带保护的 analysis 版本：

1. `guarded_dual_leg_033`
2. `guarded_dual_leg_032`
3. `guarded_dual_leg_033_no_hard_cliff`
4. `guarded_dual_leg_032_no_hard_cliff`

四个版本都要求样本属于同一类结构：

1. `trend` 为正
2. `fundamental` 为正
3. `mean_reversion` 为 neutral 且原本 active
4. `event_sentiment` 缺席

区别只在于：

1. baseline `score_b` 至少要达到 `0.33` 还是 `0.32`
2. 是否排除 profitability hard cliff 样本

### 8.3 各 guard 的实际量级

结果如下：

1. `guarded_dual_leg_033`：Layer B `1 -> 14`，净增 `+13`
2. `guarded_dual_leg_032`：Layer B `1 -> 25`，净增 `+24`
3. `guarded_dual_leg_033_no_hard_cliff`：Layer B `1 -> 5`，净增 `+4`
4. `guarded_dual_leg_032_no_hard_cliff`：Layer B `1 -> 16`，净增 `+15`

和 full exclude 的 `+54` 相比，四个 guard 都确实把量级压下来了，但压缩效果差异很大。

### 8.4 样本结构差异

`guarded_dual_leg_033` 的新增 13 条样本主要集中在：

1. `600111`：9 条
2. `300724`：2 条
3. `688008`：2 条

这个版本虽然已经比 full exclude 收敛很多，但仍然把 profitability hard cliff 的 `600111` 连续多日放出来，说明它仍在和 profitability 问题强耦合，风险还不算低。

`guarded_dual_leg_032` 进一步放宽阈值后，新增 24 条样本，基本由 `688008` 13 条和 `600111` 9 条主导，量级已经明显重新抬高，开始接近“中等规模持续放量”。

`guarded_dual_leg_033_no_hard_cliff` 是最克制的一版：

1. 只新增 `4` 条样本
2. 只涉及 `300724` 2 条和 `688008` 2 条
3. 不再把 profitability hard cliff 样本一起放出来
4. 新增日期也只是 `20260210`、`20260211`、`20260225`、`20260227`

这说明它保留了“修正 neutral mean_reversion 稀释双腿结构”的一部分收益，但明显切断了和 profitability cliff 的叠加放量。

`guarded_dual_leg_032_no_hard_cliff` 介于两者之间：

1. 净增 `+15`
2. 其中 `688008` 单票就占了 `13` 条
3. 另有 `300724` 2 条

虽然它也排除了 profitability hard cliff，但 `0.32` 这个门槛仍然让单票连续多日释放过多，控制力不够稳。

### 8.5 补充后的业务判断

把 profitability 扩窗结果和 guarded mean_reversion 一起看，当前主线的优先级可以进一步收敛为：

1. **最有希望继续向默认规则候选推进的，仍然是 profitability inactive 版本。** 它在当前可用扩窗内依然只释放 `300065` 这一类硬 cliff 边缘样本。
2. **如果 neutral mean_reversion 要继续推进，最稳的下一步候选是 `guarded_dual_leg_033_no_hard_cliff`。** 它不是收益最大的版本，但它是唯一一个把 full exclude 的 `+54` 明显压回个位数、同时仍保留一部分结构性收益的 guard。
3. `guarded_dual_leg_033` 虽然也收敛，但仍把 `600111` 这类 profitability hard cliff 样本持续放出来，说明它和 profitability 语义仍然耦合过深。
4. 两个 `0.32` guard 都偏激进，不适合作为当前默认规则候选。

因此，后续如果还要继续做 neutral mean_reversion 的最小规则分析，应优先把 `033_no_hard_cliff` 当作“可继续观察的保护版上限”，而不是重新回到 full exclude 或更宽的 `0.32` 版本。

---

## 9. 2026-03-15 补充验证：端到端 pipeline backtest 结果

补充结果产物：

1. `data/reports/layer_b_backtest_variants_20260202_20260227_20260314.json`
2. `data/reports/rule_variant_backtests/baseline.timings.jsonl`
3. `data/reports/rule_variant_backtests/profitability_inactive.timings.jsonl`
4. `data/reports/rule_variant_backtests/neutral_mean_reversion_guarded_033_no_hard_cliff.timings.jsonl`

这轮补充验证不再只看 Layer B 放量，而是直接跑完整条默认 backtester pipeline，对比三组规则在真实持仓、成交和收益上的差异。

### 9.1 三组最终收益完全一致

最终总表显示，三个变体的端到端结果完全相同：

1. `start_value` 全部是 `100000.0`
2. `end_value` 全部是 `100334.2000435`
3. `total_return_pct` 全部是 `0.3342`
4. `portfolio_value_points` 全部是 `15`
5. `sharpe_ratio`、`sortino_ratio`、`max_drawdown`、`calmar_ratio` 也全部一致

这说明前面在 Layer B 上看到的放量差异，并没有穿透到这段窗口内的最终收益结果。

### 9.2 真实成交也没有形成分化

按 timing 汇总看，三个变体的成交侧同样没有分化：

1. `pipeline_days` 全部是 `14`
2. `nonzero_buy_order_days` 全部是 `1`
3. `executed_order_days` 全部是 `1`
4. `avg_sell_order_count` 全部是 `0.0`

换句话说，这轮 2026-02-02 至 2026-02-27 窗口内，三组规则最终都只落成了同一量级的极少数真实买入，没有形成新增成交路径，也没有形成新增卖出结果。

### 9.3 规则变化主要停留在中游 funnel，没有穿透到最终订单

虽然最终收益相同，中游 funnel 仍然出现了明显差异：

1. baseline 的 `avg_layer_b_count = 2.14`
2. profitability_inactive 的 `avg_layer_b_count = 3.00`
3. guarded neutral mean_reversion 的 `avg_layer_b_count = 3.64`

但三组的 `avg_watchlist_count` 都只有 `0.0714`，`avg_buy_order_count` 也都只有 `0.0714`。

这说明本轮规则变化的真实效果是：

1. 它们确实把更多标的送进了 Layer B / Layer C
2. 但额外释放出来的标的，绝大部分都在 watchlist / final fusion / decision 阶段被重新压掉了
3. 所以最终组合路径、成交路径和收益路径没有发生实质变化

因此，当前主瓶颈已经不是“Layer B 候选太少”本身，而是“额外候选无法穿透后续决策链”。

### 9.4 运行成本反而显著上升

三组端到端平均日耗时如下：

1. baseline：`199.96s`
2. profitability_inactive：`282.46s`
3. guarded neutral mean_reversion：`258.74s`

也就是说，在这段窗口里：

1. baseline 最快
2. profitability_inactive 最慢
3. guarded neutral mean_reversion 次之

而它们最终收益完全一样，所以从端到端 ROI 看，这两种变体当前都没有证明自己值得替换 baseline。

### 9.5 截至当前主线的业务结论

把前面的 Layer B 验证和这轮端到端 backtest 放在一起，结论可以收敛为：

1. profitability inactive 仍然是更温和、可解释的 Layer B 分析候选。
2. `neutral_mean_reversion_guarded_033_no_hard_cliff` 仍然是比 full exclude 更安全的 protected MR 候选。
3. 但在真实 backtest 窗口 `2026-02-02 .. 2026-02-27` 内，这两者都**没有带来任何额外收益或额外真实成交结果**。
4. 因此，基于当前证据，不应把它们当成已经验证有效的默认规则升级。
5. 如果后续还要继续推进，重点应该从“继续放大 Layer B”转向“为什么新增候选在后续 watchlist / final fusion 环节全部失效”。

这意味着当前最稳妥的说法不是“这些规则无效”，而是：**它们只证明了自己能改变中游候选分布，还没有证明能改变最终交易结果。**

### 9.6 2026-03-15 focused replay：压票主因来自 investor cohort，而不是 analyst cohort

为了继续回答“为什么新增候选没有变成真实订单”，这一轮没有重跑正式整窗 backtest，而是只对 timing 日志里相对 baseline 新增、但最终死在 watchlist 的少数 ticker 做 focused replay，产物为：

1. `data/reports/layer_c_agent_contributors_focus_20260202_20260224_20260315.json`
2. `data/reports/layer_c_agent_contributors_focus_20260203_20260226_20260315.json`

这两份 replay 的用途不是替代正式回测，而是补出旧 timing 日志里没有记录的 agent 级贡献摘要，用来回答到底是谁在把这些新增候选压回去。

从四个聚焦日期的 replay 结果看，结论已经比较稳定：

1. `300699`、`300065`、`600089`、`002602`、`600111` 这类样本都不是被 analyst 群体主导压制，而是被 investor persona 群体一致性看空。
2. 在这些强负向样本上，`investor` cohort 的总贡献通常在 `-0.39` 到 `-0.60` 之间，而 `analyst` cohort 往往只在 `0` 到 `-0.12` 之间，量级明显更小。
3. 高频 top negative agents 主要集中在 `bill_ackman_agent`、`mohnish_pabrai_agent`、`rakesh_jhunjhunwala_agent`、`ben_graham_agent`、`aswath_damodaran_agent`，个别样本还会出现 `peter_lynch_agent`、`michael_burry_agent`。
4. 这说明新增候选被压掉，并不是单个技术分析 agent 的偶发噪声，而是多位 investor persona 在 Layer C 上形成了方向一致的负反馈。

几个关键样本的 replay 证据如下：

1. `300699`
    20260202 replay：`investor = -0.5557`，`analyst = -0.1234`
    20260203 replay：`investor = -0.5971`，`analyst = -0.1234`
    两天都触发 `b_positive_c_strong_bearish`，属于稳定的结构性强压制样本。
2. `600111`
    20260224 replay：`investor = -0.3893`，`analyst = -0.0175`
    20260203 replay：`investor = -0.4605`，`analyst = -0.0175`
    也是典型的 investor 主导负向样本。
3. `300065`、`600089`、`002602`
    三者的 `investor` 贡献分别约为 `-0.5952`、`-0.5151`、`-0.5392`，都明显强于 analyst 侧，且都落入 conflict-driven avoid。

但 `600519` 的模式不同。它在 20260224 replay 中接近中性偏正，在 20260226 replay 中又转成轻负，且两次都没有触发 `avoid` 冲突，只是 `score_final` 过不了 watchlist 阈值。这说明 `600519` 更像“边缘不过线”的阈值样本，而不是像 `300699` 或 `300065` 那样被 investor 群体稳定一致地强压制。

因此，把 focused replay 和前面的 watchlist suppression 结果合起来看，当前更准确的定位是：

1. profitability inactive 与 guarded MR 确实释放了更多 Layer B 候选。
2. 这些新增候选里，绝大多数强负向样本在 Layer C 被 investor persona 群体重新拉成负分，并触发 `b_positive_c_strong_bearish` 或把 `score_final` 压到 watchlist 阈值以下。
3. 真正值得后续做最小规则实验的，不是继续单纯扩张 Layer B，而是测试 investor 权重、冲突规则和 watchlist 阈值对“边缘样本”和“结构性强负样本”是否能够被有效区分。

### 9.7 2026-03-15 最小离线实验：存在“只放边缘样本、不泄漏强负样本”的干净增益区间

基于上面的 focused replay 结论，新增了一个更小范围的离线分析脚本：

1. `scripts/analyze_layer_c_edge_tradeoff.py`
2. `data/reports/layer_c_edge_tradeoff_20260315.json`

这个实验不重放 agent、不重跑整窗 backtest，只直接使用 focused replay 里已经提取出的 cohort 贡献摘要，把样本分成两类：

1. `edge_watch_threshold`：没有 `avoid` 冲突、只是 `score_final` 差一点不过线的边缘样本。当前聚焦样本里主要就是 `600519` 的两次出现。
2. `structural_conflict`：已经触发 `b_positive_c_strong_bearish` 的结构性强负样本。当前聚焦样本里包括 `300699`、`300065`、`600089`、`002602`、`600111`、`300502`。

实验的目标很直接：看是否存在某些温和参数组合，可以让 `600519` 这种边缘样本穿透 watchlist，同时仍然不放行这些结构性强负样本。

结果显示，有三档值得区分的结论：

1. **单独降 watchlist 阈值没有用。** `watchlist=0.20` 仍然无法放出任何边缘样本。
2. **单独削弱 investor 权重也没有用。** 把 `investor` cohort 缩到 `0.90`，在当前 `0.4/0.6` 融合和 `0.25` watchlist 下，仍然没有任何穿透。
3. **只有“轻度削弱 investor 压制 + 提高 B 权重”组合，才开始出现干净增益。**

当前聚焦样本上，至少有两组组合表现为“放出 `600519`，但不泄漏任何结构性强负样本”：

1. `investor_scale=0.90`、`b/c=0.55/0.45`、`watchlist=0.20`、`avoid=-0.30`
    结果：只放出 `20260224 / 600519`，`score_final=0.2463`，结构性强负样本泄漏数 `0`
2. `investor_scale=0.85`、`b/c=0.60/0.40`、`watchlist=0.20`、`avoid=-0.40`
    结果：同样只放出 `20260224 / 600519`，结构性强负样本泄漏数 `0`

如果进一步把 watchlist 再降到 `0.18`，则：

1. `investor_scale=0.90`、`b/c=0.60/0.40`、`watchlist=0.18` 可以同时放出 `20260224 / 600519` 和 `20260226 / 600519`
2. 但这已经属于比前两组更激进的边界组合，不应直接当作默认升级候选

因此，这一轮最小实验给出的新结论是：

1. 当前并不是完全不存在“只放边缘样本、不泄漏强负样本”的参数空间。
2. 这个空间不是通过简单放宽单一阈值得到的，而是要同时调节 investor cohort 压制强度和 B/C 融合权重。
3. 从保守性看，下一步最值得验证的不是 `watchlist=0.18` 这类更激进组合，而是先围绕 `investor_scale≈0.90` 与 `b_weight≈0.55` 的小范围参数带做更细的离线验证。

继续做细网格扫描后，候选矩阵还能再收敛一层。把 `investor_scale ∈ [0.85, 0.95]`、`b_weight ∈ [0.50, 0.60]`、`watchlist ∈ [0.18, 0.22]`、`avoid ∈ {-0.30, -0.35, -0.40}` 做组合搜索后，可以把当前聚焦样本上的 clean candidates 分成两档：

1. **保守单样本候选**
    代表组合：`investor_scale=0.90`、`b/c=0.55/0.45`、`watchlist=0.20`、`avoid=-0.30`
    结果：只放出 `20260224 / 600519`，没有任何结构性强负样本泄漏。
    含义：这是当前最接近“最小改动”的 clean gain 候选。
2. **边界双样本候选**
    代表组合：`investor_scale=0.95`、`b/c=0.60/0.40`、`watchlist=0.18`、`avoid=-0.30`
    结果：同时放出 `20260224 / 600519` 和 `20260226 / 600519`，仍然没有任何结构性强负样本泄漏。
    含义：要拿到两次 `600519` 穿透，当前关键不在于大幅削弱 investor，而在于把 `b_weight` 提到 `0.60` 并把 watchlist 压到 `0.18` 左右。

这说明细网格下的主导因素可以进一步概括为：

1. 想要一个更保守的默认候选，应优先围绕 `investor_scale≈0.90`、`b_weight≈0.55`、`watchlist≈0.20` 这一带继续验证。
2. 想要拿到更完整的边缘样本穿透，则必须进入 `b_weight=0.60` 且 `watchlist<=0.19` 的更激进区域。
3. 在当前聚焦样本上，`avoid` 阈值从 `-0.30` 放宽到 `-0.35/-0.40` 并不是决定性因素；真正决定穿透的是 B/C 融合权重与 watchlist 阈值的联动。

### 9.8 候选优先级矩阵

基于 `data/reports/layer_c_edge_tradeoff_20260315.json` 当前可以把下一步候选明确分成三档，而不是继续泛化地说“再调一调参数看看”。

1. **P1 保守候选，优先继续验证**
    参数：`investor_scale=0.90`、`b/c=0.55/0.45`、`watchlist=0.20`、`avoid=-0.30`
    结果：只放出 `20260224 / 600519`，结构性强负样本泄漏 `0`
    理由：这是当前最接近“最小改动”的 clean gain 方案，调参幅度相对小，业务语义也最容易解释。
2. **P2 边界候选，只作为上界证据保留**
    参数：`investor_scale=0.95`、`b/c=0.60/0.40`、`watchlist=0.18`、`avoid=-0.30`
    结果：同时放出 `20260224 / 600519` 和 `20260226 / 600519`，结构性强负样本泄漏 `0`
    理由：它证明“双样本穿透且不泄漏”在当前聚焦样本上是可达的，但需要进入更激进的 `b_weight=0.60` 与 `watchlist=0.18` 区域，不宜直接作为默认升级候选。
3. **P3 暂不优先的单旋钮方案**
    代表：只降 `watchlist` 到 `0.20`，或者只把 `investor_scale` 降到 `0.90`
    结果：边缘样本通过数仍然是 `0`
    理由：这些方案已经被当前 focused replay 证据否定，不值得再作为主线继续消耗分析预算。

如果下一步要把分析继续压缩成“最小规则提案”，当前最合理的顺序应当是：

1. 先以 P1 作为默认候选起点，因为它最接近可解释的最小变更。
2. 把 P2 保留为边界对照，用来说明如果业务想追求更高边缘样本穿透，需要付出多大程度的参数放宽。
3. 不再对 P3 这类单旋钮放宽方案投入时间，除非后续样本集出现新的反例。

### 9.9 最小规则提案

如果下一步要把分析转成真正可落地的规则提案，当前最合理的起点不是直接采用 P2，而是把 P1 翻译成一个**只影响 Layer C 和 watchlist、完全不触碰 Layer B 规则**的最小变更包。

建议提案如下：

1. 在 `src/execution/layer_c_aggregator.py` 中，把当前固定的 `score_final = 0.4 * score_b + 0.6 * score_c` 调整为**可配置**的 `0.55 / 0.45` 融合权重。
2. 在 `src/execution/layer_c_aggregator.py` 中，为 investor cohort 引入一个**可配置缩放因子**，默认候选值为 `0.90`。实现方式应是先对 investor 原始权重整体乘以 `0.90`，再与 analyst 权重一起重新归一化，而不是在 `score_c` 算完之后做二次裁剪。
3. 在 `src/execution/daily_pipeline.py` 中，把当前已经存在的 watchlist 阈值环境变量从默认 `0.25` 下调到候选值 `0.20`。
4. **不调整** `b_positive_c_strong_bearish` 的 avoid 阈值，继续保持 `score_c < -0.30` 时直接 `avoid`，避免把这轮已确认的结构性强负样本错误放行。

这样做的原因很明确：

1. `watchlist=0.20` 本身并不能单独解决问题，但它是 P1 组合成立的必要组成部分。
2. `investor_scale=0.90` 的作用不是“取消 investor 约束”，而是把 investor 群体从当前默认的强主导状态稍微往回拉一点，让 analyst 与 Layer B 的正向信息有更高机会保住边缘样本。
3. `b_weight=0.55` 的作用是把 Layer B 已经给出正向信号的样本，向最终分数多保留一部分；这对 `600519` 这类边缘样本有效，但对已经落入 `avoid` 冲突区的样本并不构成充分放行条件。

按当前 focused replay 样本估算，P1 的预期行为差异是：

1. 对 `300699`、`300065`、`600089`、`002602`、`600111`、`300502` 这类结构性强负样本，仍然保持拦截，因为它们的 `score_c` 负向幅度远低于 `-0.30`，不会因为轻度调权就脱离 `avoid` 区。
2. 对 `20260224 / 600519` 这类边缘 watch 样本，`score_final` 会从当前 replay 下的 `0.1979` 提升到约 `0.2463`，从而跨过 `0.20` 的 watchlist 门槛。
3. 对 `20260226 / 600519` 这类更弱的边缘样本，P1 仍然不会放行；这正是它比 P2 更保守的地方。

从工程落地角度看，这个提案的优点是：

1. 改动面非常小，只涉及 `src/execution/layer_c_aggregator.py` 和 `src/execution/daily_pipeline.py` 的参数化，不要求重写任何筛选逻辑。
2. 现有 observability 已经足够支撑验证，因为 watchlist diagnostics 里已经能看到 `score_b`、`score_c`、`score_final` 和 `agent_contribution_summary`。
3. 如果后续验证失败，回滚路径也非常简单，本质上只是恢复三个参数。

但它的风险也必须提前说清：

1. 这仍然只是基于 10 个 focused replay 样本形成的最小提案，不是正式生产升级结论。
2. 当前证据只能证明“它在聚焦样本上可能形成 clean gain”，不能证明它在完整窗口或未来窗口上同样不会引入额外误放。
3. 因此，P1 最合理的后续动作不是直接替换默认逻辑，而是作为下一轮 targeted replay 或小窗口验证的唯一主候选。

截至 2026-03-15 当前工作区，这个 P1 提案已经被实现为默认参数化版本：

1. `src/execution/layer_c_aggregator.py` 现已引入可配置的 Layer C 融合权重、investor cohort 缩放和 avoid 阈值，当前默认值分别为 `0.55/0.45`、`0.90`、`-0.30`。
2. `src/execution/daily_pipeline.py` 的 watchlist 默认阈值已调整为 `0.20`。
3. `tests/execution/test_phase4_execution.py` 已补充两条针对新默认行为的测试：
    一条验证 investor 缩放会在同 raw weight 下把相对权重轻微向 analyst 侧倾斜；
    一条验证 `score_final` 落在 `0.20` 到 `0.25` 之间的边缘样本现在可以进入 watchlist。
4. 聚焦执行层回归结果：`pytest tests/execution/test_phase4_execution.py -q` 通过，当前为 `23 passed`。

需要强调的是：代码层面的 P1 已经落地，但业务层面的验证仍未完成。它目前更适合作为“当前工作区的候选默认参数”，而不是已经经过整窗 backtest 重新验证的最终结论。

为了解决“真实 agent targeted replay 成本过高、容易超时”这个问题，当前工作区又补了一层**离线业务回归**到 `tests/execution/test_phase4_execution.py`：

1. 把 focused replay 中已经确认的 8 个结构性强负样本固化成离线回归断言，验证它们在当前 P1 默认参数下仍然保持 `decision=avoid`，不会穿透 watchlist。
2. 把 `600519` 的两个边缘样本也固化成离线回归断言，验证 `20260224` 这笔在当前 P1 默认参数下会通过，而 `20260226` 这笔仍然不会通过。
3. 这层回归不依赖真实 agent 重放，只依赖前面已经产出的 focused replay cohort 贡献摘要，因此可以稳定、快速地重复执行。

最新执行层测试结果已经更新为：`pytest tests/execution/test_phase4_execution.py -q` => `32 passed`。

这意味着当前工作区的验证状态已经分成两层：

1. **代码行为层**：P1 已实现，执行层单测与离线业务回归全部通过。
2. **真实 agent / 端到端业务层**：仍缺少一次成本可控的 targeted replay 或小窗口 backtest 作为最终补证。

为了让这层补证后续可执行，当前工作区还对 `scripts/replay_layer_c_agent_contributors.py` 做了工程化改造：

1. 支持在 `--output` 打开时按日期增量写出 partial JSON，而不是等整批 replay 完成后才一次性落盘。
2. 支持 `--resume` 从已有输出继续跑，自动跳过已经完成的日期。
3. 支持通过 `--ticker` 把 live replay 收缩到单个目标 ticker，避免无关样本把整次验证拖慢。
4. 这意味着后续如果继续做真实 targeted replay，应该优先按单日或少量日期切分执行，并始终开启 `--output --resume`，而不是再一次性跑整组日期。

这项改造本身不构成新的业务结论，但它解决了前面真实 replay 容易超时、结果无法持久化的问题，为后续补最后一层端到端证据创造了可执行路径。

2026-03-16 已经完成最小 live targeted replay：

1. `20260224 / 600519` 的 live replay `score_final = 0.2158`，已经跨过 `0.20` watchlist 门槛。
2. `20260226 / 600519` 的 live replay `score_final = 0.1962`，仍然保持边缘不过线。
3. 两次 replay 都成功落盘到 `data/reports/live_replay_600519_20260224_p1.json` 与 `data/reports/live_replay_600519_20260226_p1.json`。

因此，当前最务实的判断已经更新为：

1. 工具链已经足以支持可恢复的 live replay；
2. 最小 live 补证已经完成，并且结果符合 P1 的保守预期；
3. 当前剩余缺口不再是“没有 live replay 证据”，而是“还没有更长窗口或未来窗口的业务覆盖”。

### 9.10 P1 变更说明

下面这部分不再是分析结论，而是面向工程评审的变更摘要，描述当前工作区已经落地的 P1 改动边界、验证范围和回滚方式。

#### 9.10.1 变更范围

本次 P1 只修改 Layer C 与 watchlist，明确**不触碰 Layer B 规则**。

已落地的代码范围如下：

1. `src/execution/layer_c_aggregator.py`
    - Layer C 最终融合从固定 `0.4 / 0.6` 改为可配置默认 `0.55 / 0.45`
    - investor cohort 权重在归一化前增加 `0.90` 缩放
    - avoid 冲突阈值改为可配置，但默认仍保持 `-0.30`
2. `src/execution/daily_pipeline.py`
    - watchlist 默认阈值从 `0.25` 调整到 `0.20`
3. `tests/execution/test_phase4_execution.py`
    - 新增参数行为测试
    - 新增 focused replay 离线业务回归测试
4. `scripts/replay_layer_c_agent_contributors.py`
    - 支持 partial JSON 按日期增量写出
    - 支持 `--resume`
    - 支持 `--ticker-batch-size`
    - 支持 `--ticker` 精确过滤

#### 9.10.2 当前默认参数

截至当前工作区，P1 默认参数是：

1. Layer C blend：`b/c = 0.55 / 0.45`
2. investor scale：`0.90`
3. watchlist threshold：`0.20`
4. avoid threshold：`-0.30`

这些默认值的设计意图是：

1. 允许少量 Layer B 已经偏正、但 Layer C 只是略微偏弱的边缘样本进入 watchlist
2. 继续拦住已经形成强负一致性的 conflict 样本
3. 不改变 `b_positive_c_strong_bearish` 这条风险语义的定义本身

#### 9.10.3 已完成验证

当前已完成的验证，分为三层：

1. **执行层单元测试**
    - `pytest tests/execution/test_phase4_execution.py -q` 已通过，当前结果为 `32 passed`
2. **参数行为验证**
    - 已验证 investor 缩放会在相同 raw weight 下轻微提高 analyst 相对影响力
    - 已验证 `score_final` 处于 `0.20 .. 0.25` 之间的边缘样本现在可以进入 watchlist
3. **离线业务回归**
    - 已固化 8 个结构性强负样本，验证它们在 P1 下仍然保持 `avoid` / 不穿透
    - 已固化 `600519` 两个边缘样本，验证 `20260224` 可以通过、`20260226` 仍然不会通过
4. **最小 live targeted replay**
    - `20260224 / 600519`：live replay `score_final = 0.2158`，达到 watchlist 通过区间
    - `20260226 / 600519`：live replay `score_final = 0.1962`，仍保持边缘不过线

#### 9.10.4 尚未完成的更大范围验证

以下验证仍未完成，因此当前不能把 P1 说成“已经完成端到端业务验证”：

1. 没有重新跑正式整窗 backtest
2. 没有证明 P1 在更长窗口或未来窗口下仍然不会引入额外误放
3. 没有覆盖更多边缘样本与更多日期的 live replay 分布

当前 live replay 的状态已经更新为：

1. replay 脚本的可恢复能力已经补齐
2. `600519` 两个目标日期的 live replay 已完成并成功落盘
3. 当前剩余问题是样本覆盖范围，而不是“最后一层 live 证据完全缺失”

#### 9.10.5 残余风险

当前最需要显式记录的风险有三类：

1. **样本风险**
    当前业务回归与 live replay 仍只覆盖小样本，不代表完整分布。
2. **阈值迁移风险**
    把 watchlist 默认值改到 `0.20` 后，未来可能出现新的边缘样本进入 watchlist，需要继续依赖 funnel diagnostics 监控。
3. **权重解释风险**
    investor 缩放虽然是温和调整，但本质上改变了 investor 与 analyst 的相对投票权，后续如果继续迭代，必须避免在多轮调参中失去可解释性。

#### 9.10.6 回滚策略

如果后续 targeted replay 或小窗口验证显示 P1 带来了不可接受的误放，回滚路径非常直接：

1. `src/execution/layer_c_aggregator.py`
    - blend 恢复到 `0.40 / 0.60`
    - investor scale 恢复到 `1.00`
    - avoid threshold 继续保持 `-0.30`
2. `src/execution/daily_pipeline.py`
    - watchlist threshold 恢复到 `0.25`
3. 保留当前新增测试，但把预期值同步改回旧默认行为，确保回滚后测试仍然具备约束力

#### 9.10.7 当前建议

基于现有证据，当前最稳妥的工程建议是：

1. 把 P1 视为**已经完成最小 live 补证的候选默认参数**，可以进入评审，但仍不是完整窗口 fully validated 的正式发布结论。
2. 当前最合理的后续工作，不是继续推 P2，而是观察更长窗口下是否会出现新增误放。
3. 在没有新的分布级证据前，不建议继续向 P2 或更激进参数区间推进。

### 9.11 离线 Live Replay 执行方案

这一节不再扩展分析结论，而是把最后一层补证压缩成一个可以直接离线执行的最小流程。

#### 9.11.1 验证目标

只验证两个问题：

1. `20260224 / 600519` 在当前 P1 默认参数下，真实 agent replay 是否会进入通过 watchlist 的区间。
2. `20260226 / 600519` 在当前 P1 默认参数下，真实 agent replay 是否仍然不会通过，或者至少仍保持边缘不过线。

这一步不再追求整窗覆盖，也不再同时验证全部强负样本，因为这些已经被离线业务回归覆盖。

#### 9.11.2 执行原则

live replay 必须严格遵守三条约束：

1. 一次只跑一个日期。
2. 一次只跑一个 ticker。
3. 必须始终开启输出文件，以便中途中断后仍然留下可恢复产物。

当前真正的瓶颈已经不是脚本持久化，而是 live agent 链路本身的执行耗时。

#### 9.11.3 推荐命令

先跑 `20260224 / 600519`：

```bash
/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.venv/bin/python \
scripts/replay_layer_c_agent_contributors.py \
    --baseline data/reports/rule_variant_backtests/baseline.timings.jsonl \
    --variant data/reports/rule_variant_backtests/neutral_mean_reversion_guarded_033_no_hard_cliff.timings.jsonl \
    --dates 20260224 \
    --ticker 600519 \
    --ticker-batch-size 1 \
    --output data/reports/live_replay_600519_20260224_p1.json
```

再跑 `20260226 / 600519`：

```bash
/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.venv/bin/python \
scripts/replay_layer_c_agent_contributors.py \
    --baseline data/reports/rule_variant_backtests/baseline.timings.jsonl \
    --variant data/reports/rule_variant_backtests/neutral_mean_reversion_guarded_033_no_hard_cliff.timings.jsonl \
    --dates 20260226 \
    --ticker 600519 \
    --ticker-batch-size 1 \
    --output data/reports/live_replay_600519_20260226_p1.json
```

如果任务中断，直接对同一个输出文件加 `--resume` 续跑，不要新开文件：

```bash
scripts/run_live_replay_600519_p1.sh 20260224 --resume
scripts/run_live_replay_600519_p1.sh 20260226 --resume
```

如果希望一次把两个目标日期都顺序跑完，也可以直接调用包装脚本：

```bash
scripts/run_live_replay_600519_p1.sh all --resume
```

这个包装脚本会固定使用：

1. `baseline.timings.jsonl`
2. `neutral_mean_reversion_guarded_033_no_hard_cliff.timings.jsonl`
3. 单 ticker `600519`
4. `ticker-batch-size=1`
5. 稳定输出路径 `data/reports/live_replay_600519_<date>_p1.json`

因此后续补证时，优先使用它，而不是重新手工拼接长命令，以避免输出文件名漂移导致 `--resume` 无法复用。

```bash
/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.venv/bin/python \
scripts/replay_layer_c_agent_contributors.py \
    ...同上参数... \
    --resume
```

#### 9.11.4 验收标准

这轮 live replay 的验收标准应当保持极窄：

1. `20260224 / 600519`
    - 理想结果：`decision != avoid` 且 `score_final >= 0.20`
    - 可接受结果：`decision == watch`，并且 `score_final` 明显高于旧 replay 的 `0.1979`，至少证明 P1 在真实 replay 中保持了方向一致的改善
2. `20260226 / 600519`
    - 理想结果：仍未通过，或保持边缘不过线
    - 解释意义：说明 P1 仍然是保守候选，没有直接滑向 P2 的更激进区间

#### 9.11.5 结果记录格式

完成后只需要补三类信息：

1. replay 的 `score_c`
2. replay 的 `score_final`
3. replay 的 `decision / bc_conflict`

除非 live replay 与当前离线回归方向明显冲突，否则不需要再次展开全部 top agents。

建议直接使用下面的汇总脚本，把 replay JSON 整理成可贴回文档的 markdown：

```bash
/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.venv/bin/python \
scripts/summarize_live_replay_600519_p1.py \
    --output data/reports/live_replay_600519_p1_summary.md
```

如果只想汇总单个结果文件，也可以显式传入输入路径：

```bash
/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.venv/bin/python \
scripts/summarize_live_replay_600519_p1.py \
    data/reports/live_replay_600519_20260224_p1.json
```

推荐判读模板如下：

```md
### 20260224 / 600519
- replay：score_c=<value>，score_final=<value>，decision=<value>，bc_conflict=<value>
- 对照：旧 replay score_final=0.1979，旧 logged score_final=0.1584
- 结论：
    - 若 `decision != avoid` 且 `score_final >= 0.20`，记为“达到理想验收”
    - 若 `decision == watch` 且 `score_final > 0.1979`，记为“达到可接受验收”
    - 否则记为“未达到验收”

### 20260226 / 600519
- replay：score_c=<value>，score_final=<value>，decision=<value>，bc_conflict=<value>
- 对照：旧 replay score_final=0.0791，旧 logged score_final=0.1580
- 结论：
    - 若 `score_final < 0.20`，记为“达到理想验收”，说明仍保持边缘不过线
    - 若 `score_final >= 0.20`，记为“未达到验收”，说明行为比 P1 预期更激进
```

如果 live replay 成功落盘，优先把脚本生成的 markdown 作为结果正文，再视是否存在方向冲突决定要不要补充 top agents 细节。

#### 9.11.6 如果仍然超时

如果后续扩展到更多日期或更多 ticker 时再次超时，那么应直接接受以下判断：

1. 当前工作区已经具备充分的代码级和离线业务级证据。
2. 更大范围的 live replay 需要被视为独立离线任务，而不是当前交互式会话中的下一步。
3. 在这种情况下，P1 仍然可以作为候选默认参数进入评审，但必须显式标注“更长窗口证据待补”，而不是“最小 live replay 证据缺失”。

#### 9.11.7 Live Replay 实际结果

如果已经生成 `data/reports/live_replay_600519_p1_summary.md`，可以直接用下面的脚本把结果自动回填到当前文档：

```bash
/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.venv/bin/python \
scripts/update_live_replay_doc_600519_p1.py
```

如果只想预览回填后的结果而不真正写入文档，可以加 `--dry-run`：

```bash
/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.venv/bin/python \
scripts/update_live_replay_doc_600519_p1.py \
    --dry-run
```

<!-- LIVE_REPLAY_600519_P1:START -->

## 600519 P1 Live Replay 汇总

本摘要用于快速判断 20260224 和 20260226 两个目标日期是否符合 P1 的最小业务补证预期。

### 20260224 / 600519

- 来源文件：/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/reports/live_replay_600519_20260224_p1.json
- variant：neutral_mean_reversion_guarded_033_no_hard_cliff.timings
- logged：score_final=0.1584，decision=watch，bc_conflict=None
- replay：score_c=-0.0122，score_final=0.2158，decision=watch，bc_conflict=None
- delta：score_c=-0.0079，score_final=0.0574
- cohort：investor=-0.0122，analyst=0.0000，other=0.0000
- 对照基线：旧 replay score_final=0.1979，旧 logged score_final=0.1584
- 验收结论：ideal
- 说明：达到理想验收：已跨过 0.20 watchlist 门槛。

可直接贴入文档的结论：

> 20260224 / 600519 的 live replay 结果为 score_c=-0.0122、score_final=0.2158、decision=watch、bc_conflict=None。相较既有 replay，score_final 变化 0.0574。达到理想验收：已跨过 0.20 watchlist 门槛。

### 20260226 / 600519

- 来源文件：/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/reports/live_replay_600519_20260226_p1.json
- variant：neutral_mean_reversion_guarded_033_no_hard_cliff.timings
- logged：score_final=0.1580，decision=watch，bc_conflict=None
- replay：score_c=-0.0469，score_final=0.1962，decision=watch，bc_conflict=None
- delta：score_c=-0.0469，score_final=0.0382
- cohort：investor=-0.0469，analyst=0.0000，other=0.0000
- 对照基线：旧 replay score_final=0.0791，旧 logged score_final=0.1580
- 验收结论：ideal
- 说明：达到理想验收：仍保持边缘不过线，没有滑向更激进的 P2 区间。

可直接贴入文档的结论：

> 20260226 / 600519 的 live replay 结果为 score_c=-0.0469、score_final=0.1962、decision=watch、bc_conflict=None。相较既有 replay，score_final 变化 0.0382。达到理想验收：仍保持边缘不过线，没有滑向更激进的 P2 区间。

<!-- LIVE_REPLAY_600519_P1:END -->