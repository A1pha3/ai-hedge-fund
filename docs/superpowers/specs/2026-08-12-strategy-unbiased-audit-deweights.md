# 三策略降权研究重建（已拒绝）

**日期**：2026-08-12

**复核日期**：2026-08-12

**状态**：`RESEARCH_RECONSTRUCTION_REJECTED`

**性质**：保留用于审计的历史研究记录，不是生产设计、策略证据或授权输入

## 结论

本文件原先据 `scripts/strategy_unbiased_audit.py` 的输出，把 mean_reversion 默认权重从 `0.20` 降为 `0.0`，并把 regime 调整改为乘性语义。两项行为变化均已撤销：生产默认权重恢复为 `0.40/0.20/0.15/0.05`，regime 恢复此前的 additive contract。

原报告不得用于改变生产准入、排序、仓位或资本授权，也不得作为 `PolicyActivation`、Trial、SAP、Stage、EDGE evidence 或治理签发物。配置、报告状态和测试通过记录都不构成权限。

## 原研究记录

原报告给出过以下统计。表中数值仅保留为可追溯的历史输出，不能作为策略优劣或生产权重的有效证据：

| 策略 | n | 原 signed ρ | 原裁决 | 当前解释 |
|---|---:|---:|---|---|
| mean_reversion | 16,470 | −0.0819 | 反 IC | 受 universe、exit 和公司行动口径影响，待重验 |
| fundamental | 4,432 | +0.0239 | 弱正 | mutable/PIT 输入与生产决策样本未完整冻结，待重验 |
| event_sentiment | 1,787 | +0.0638 | 正 IC | 存在已确认的未来新闻泄漏，原结论无效 |

因此，“mean_reversion 是负贡献”“event_sentiment 是唯一真信号”“降权是零风险改善”等原判断全部撤销。它们可以转化为新的研究假设，但不能继续支撑已上线行为。

## 拒绝原因

1. **候选宇宙不一致**：审计脚本扫描价格缓存中所有涨停 ticker-day，而生产 `--auto` 只对每个决策日实际冻结的 Layer-A 候选、过滤结果和可用数据做评分与排序。即使扫描没有先按 score_b 选样，也不等于生产 universe，更不能证明 Top-N 排名变化后的组合效果。
2. **退出与执行合约不一致**：脚本使用 T+1 `open` 买入、T+10 `close` 卖出；开盘价无效时静默改用同日 `close`。目标合约是 T+1 开盘买、T+10 开盘卖，还包含成本、现金占用、涨跌停、停牌、未成交和部分成交状态。当前统计不是目标合约的完整组合路径。
3. **公司行动未纳入收益真相**：MR、fundamental 和 event 路径都用 `exit_close / entry_open - 1` 计算收益，没有调用 `chained_return_pct`，也没有消费版本化公司行动事件。拆分、分红或复权口径变化会污染方向、分桶与 IC。
4. **event 存在未来新闻泄漏**：`scan_event()` 先把缓存中的整段新闻装入 `news_by_ticker`，随后对窗口内每个历史 `date_i` 传入同一份列表。修复前的纯输入 scorer 没有决策 cutoff，并把未来行产生的负 `days_old` 压成 `0`。最小复现是把日期为 2026-08-11 的新闻传给 2026-02-26 决策：它会被当作最新事件参与评分。原 event 正 IC、窗口比较以及“唯一真信号”结论因此无效；必须在修复后从原始、可用时点明确的数据重跑。
5. **证据与版本门缺失**：研究没有冻结受信 `observed_at`/`ingested_at`/`available_at`、active revision、policy fingerprint、成本模型、公司行动版本、expected-session spine 或组合净值路径。它无法开启新的生产证据世代，更不能授权乘性 regime 调整。

## 生产处置

- 保留 `DEFAULT_STRATEGY_WEIGHTS` 作为唯一默认权重真理源，`MarketState`、custom weights 默认值和融合路径继续从它派生。
- 默认权重恢复为 trend `0.40`、mean_reversion `0.20`、fundamental `0.15`、event_sentiment `0.05`。
- regime 恢复研究变更前的 additive 规则；未机械撤销无关的重构和缺陷修复。
- 纯输入 event scorer 在没有可信时刻时只接受决策日前的新闻，同日新闻默认拒绝；只有调用方显式提供时区明确的决策 cutoff 时，才接受该 cutoff 及之前、且自身也带时刻的同日新闻。带 offset 的新闻时间按完整 instant 换算，禁止截掉 offset 后冒充上海本地时间；同日只有日期而无时刻仍视为未知。该修复只阻止后续同类泄漏，不会修复已经生成的历史报告。
- custom/策略子集权重是用户明确的相对权重；所选策略证据不可用时 score 为 0，不得回退默认权重并让未选策略重新参与排序。生产融合内部的默认权重 fallback 保持独立、显式。

## 重新研究条件

新的 deweight 或 regime 候选必须在不可改名的 research program 下作为版本化 shadow challenger 预注册，并至少满足：

- 逐决策日冻结与 `--auto` 一致的 Layer-A universe、过滤和排序输入；
- 使用 T+1 open / T+10 open、真实成本、现金占用和组合净值路径；
- 使用公司行动安全的收益链和版本化原始证据；
- event 只消费决策 cutoff 前已入库且当时 active 的 revision；
- 收集同模式前向、未复用的 OOS 样本并通过治理门。

完成研究门槛仍只会生成 inactive candidate；生产行为只能由正式激活的治理对象改变。
