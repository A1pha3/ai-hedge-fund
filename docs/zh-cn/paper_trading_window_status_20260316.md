# 纸面交易长窗状态（2026-03-16）

## 观察对象

- 运行窗口：2026-02-17 到 2026-02-28
- 运行入口：scripts/run_paper_trading.py
- 当前参数：fast score threshold = 0.38，fast pool = 2，precise pool = 1，watchlist threshold = 0.20
- 当前状态：任务已完成。由于 2026-02-28 为非交易日，最终日事件落盘截止于 2026-02-27。
- 当前代码基线：已包含两项最小修正
	1. Layer C 仅削弱 investor bearish contribution 对 blended score 的压制，但保留 raw score_c 用于 avoid veto
	2. 仓位生成对 `score_final` 落在 `0.20 .. 0.25` 的边界 watchlist 样本开放小仓位执行通道

## 已落盘事实

截至 daily_events.jsonl 当前可读内容，已完成 9 个交易日：2026-02-17、2026-02-18、2026-02-19、2026-02-20、2026-02-23、2026-02-24、2026-02-25、2026-02-26、2026-02-27。

累计漏斗结果如下：

- Layer B 进入日数：5 天
- Layer C 进入日数：5 天
- Layer B 总条目：8
- Layer C 总条目：8
- Watchlist 日数：3 天
- Buy order 日数：3 天
- Executed trade 日数：2 天

这说明长窗运行已经不再卡死在 Layer C 或下单前，策略开始形成真实 watchlist、buy order 和执行成交。

## 分日演进

- 2026-02-17 到 2026-02-20：连续 4 个交易日全部停在 Layer B 之前，layer_b_count = 0。
- 2026-02-23：首次出现有效 Layer B 和 Layer C，layer_b_count = 1，layer_c_count = 1，但 300065 仍被 avoid，watchlist_count = 0。
- 2026-02-24：扩大到 layer_b_count = 2，layer_c_count = 2，300724 首次进入 watchlist，并生成 buy order。
- 2026-02-25：再次出现 layer_b_count = 2，layer_c_count = 2，300724 继续进入 watchlist，并在 T+1 执行首笔买入。
- 2026-02-26：再次出现 layer_b_count = 2，layer_c_count = 2，但当日候选重新被 avoid，watchlist_count = 0；同时前一日挂单/计划在该日执行第二笔加仓。
- 2026-02-27：仍有 layer_b_count = 1，layer_c_count = 1，300724 再次进入 watchlist 并生成 buy order，但由于窗口结束，未在本轮内继续结算后续执行。

因此，扩窗后的真实状态已经从“运行面可用但 0 交易”推进到“运行面可用且有真实成交”。当前问题不再是 Layer C 完全压死，而是信号集中度仍然很高，窗口内主要只有 300724 真正完成了持续穿透。

## 代表性失败样本

### 2026-02-23：300065

- score_b = 0.401
- score_c = -0.6861
- score_final = -0.0882
- decision = avoid
- active agents = 17
- negative agents = 14

该样本说明候选标的已经穿过 Layer B，但被 Layer C 的强负向 investor 共识直接压成 avoid。

主要负向 agent：

- bill_ackman_agent
- ben_graham_agent
- peter_lynch_agent

### 2026-02-24：000960

- score_b = 0.4099
- score_c = -0.3957
- score_final = 0.0473
- decision = avoid

主要负向 agent：

- bill_ackman_agent
- michael_burry_agent
- valuation_analyst_agent

### 2026-02-24：300724

- score_b = 0.394
- raw score_c 约 = -0.24
- adjusted score_c 已被抬升到 watchlist 可通过区间
- score_final >= 0.20
- decision = watch
- 结果：进入 watchlist，并生成 buy order

该样本现在成为最关键的穿透样本，说明最小校准已经能把边界票从“watch 但不过线”推进到“watchlist + order”。

### 2026-02-25：600988

- score_b = 0.3867
- raw score_c 仍显著为负
- 调整后仍未通过 avoid veto
- decision = avoid

主要负向 agent：

- mohnish_pabrai_agent
- bill_ackman_agent
- valuation_analyst_agent

### 2026-02-26：603799

- score_b = 0.3982
- score_c = -0.4803
- score_final = 0.0029
- decision = avoid

主要负向 agent：

- mohnish_pabrai_agent
- bill_ackman_agent
- valuation_analyst_agent

### 2026-02-27：300724

- score_b = 0.4049
- raw score_c 仍为负，但 adjusted score_c 足以支持边界仓位
- score_final >= 0.20
- decision = watch
- 结果：进入 watchlist，并生成 buy order

主要负向 agent：

- michael_burry_agent
- sentiment_analyst_agent
- bill_ackman_agent

## 当前抑制模式

截至当前已落盘窗口，watchlist 失败原因累计为：

- decision_avoid = 4
- score_final_below_watchlist_threshold = 0

当前最频繁的负向 agent 为：

- bill_ackman_agent = 8
- michael_burry_agent = 4
- valuation_analyst_agent = 4
- ben_graham_agent = 2
- sentiment_analyst_agent = 2
- mohnish_pabrai_agent = 2
- peter_lynch_agent = 1
- rakesh_jhunjhunwala_agent = 1

可以确认，当前主导剩余抑制仍然是 investor cohort 的负向共识，但它已经不再把所有可交易样本都压死。剩余问题从“完全无单”转成了“可交易样本过于集中”。

## 运行成本观察

- 2026-02-23 的 total_post_market 约 67.9 秒，其中 fast_agent 约 53.8 秒
- 2026-02-24 的 last_counts 为 fast_agent_ticker_count = 2，precise_agent_ticker_count = 1，但依然没有进入 buy order

说明当前真实成本仍显著集中在 agent 阶段，但这些成本已经开始转化为实际下单产出。

## 当前判断

现阶段最重要的结论有三点：

1. 纸面交易运行面已经成立，长窗任务可以持续落盘并恢复，当前不是基础设施问题。
2. 最小 Layer C 校准 + 仓位阶梯修正之后，策略已经能在长窗内形成真实 watchlist、buy order 和 executed trade。
3. 当前业务瓶颈已经从“0 交易”切换为“信号/持仓过度集中”，窗口内实际穿透样本主要仍是 300724。

补充最终实验结论：

- session_summary.json 显示本轮窗口 day_count = 9，executed_trade_days = 2，total_executed_orders = 2。
- 期末组合净值 = 100276.46，较初始资金 100000.0 上升约 0.28%。
- 期末持仓为 300724 多头 500 股，现金余额约 38416.46。
- 累计漏斗结果为 layer_b_total = 8、layer_c_total = 8、watchlist_total = 3、buy_total = 3。

## 下一步

- 现在已经值得继续扩大纸面交易窗口，因为链路已能形成真实交易，接下来应验证这种产出是否具备可持续性。
- 下一阶段的重点不再是“先把单打出来”，而是验证收益质量与稳定性，包括回撤、集中度和样本多样性。
- 优先检查 300724 是否只是单一偶发成功样本，并继续观察 investor cohort 的负向共识是否仍让大多数候选停在 avoid。