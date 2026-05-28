# BTST `layer_c_watchlist` 正式层精度收缩方案（2026-05-28）

## 结论先说

当前最值得优先推进的，不是继续放宽阈值去追更多票，而是先把 `layer_c_watchlist` 从 formal `selected / execution_eligible / buy_order` 里系统性收掉。

这条线现在的正式状态已经不是“还在猜”，而是：

- `data/reports/btst_layer_c_rollout_validation_20260506_20260522.json`
- `data/reports/btst_layer_c_rollout_validation_20260506_20260522.md`

对应结论为：

- `status = governed_shadow_ready`
- `primary_lane = layer_c_formal_precision_tightening`
- `summary = 先收 formal buy：shadow 把 execution_eligible 收缩 3 个、buy_order 收缩 3 个，同时 5D/+15% 命中率从 0.3077 提升到 0.3333。`

也就是说，这条线已经够资格进入 **governed shadow rollout**，但还不够资格直接包装成默认 live 升级。

## 已验证问题

### 1. `layer_c_watchlist` 是扩窗后仍然稳定存在的 formal payoff drag

扩窗到 `2026-05-06 ~ 2026-05-22` 之后：

- 原始 `selected` 的 `5D/+15%` 命中率：`0.3077`
- shadow 剔除 `layer_c_watchlist` 后：`0.3333`

这说明单周里看起来像“边界问题”的噪声，扩窗后真正稳定留下来的 formal drag，主要就是 `layer_c_watchlist`。

### 2. 这条线不只会改 selected，还会真实收缩 formal buy

`data/reports/btst_shadow_profile_replay_sidecar_aware_20260506_20260522.json` 已经给出更关键的 replay 结果：

- `selected_count: 79 -> 74`
- `execution_eligible_count: 3 -> 0`
- `buy_order_count: 3 -> 0`

被 shadow 打掉的 formal execution / buy 名字是：

1. `20260508`：`688183`
2. `20260522`：`002222`、`300054`

这意味着它不是“统计口径上的 selected 重排”，而是已经能在 frozen replay 里复现出 **formal buy 收缩**。

### 3. replay fidelity 现在已经够支撑 rollout 判断

前面最大的技术障碍，是 sidecar-backed replay 对真实 live 基线的 selected / execution 层还原度不够。  
这轮修完之后：

- 稀疏 `selection_target_replay_input.watchlist` 会从 `selection_snapshot` 回填 rich row；
- `20260522` 的 `300054 / 002222` 已经能在 baseline replay 里恢复成原始 snapshot 的 `selected + execution_eligible=true`；
- `layer_c_watchlist_selected_rank_cap=0` 的 shadow delta 能同时打到 selected 层和 execution 层。

所以当前剩下的问题，已经不再是 replay fidelity，而是 **要不要继续扩窗、要不要进入默认升级评审**。

## alpha / beta / gamma 的统一判断

### alpha：先承认 `layer_c_watchlist` 不是 runner 主票

alpha 侧结论很直接：  
如果目标是“买入后 5 个交易日内，55% 以上概率冲到 +15%”，那 `layer_c_watchlist` 现在更像 continuation 观察池，不像应该直接放进 formal `selected` 的 runner 主票。

因此当前更合理的做法是：

1. 把 `layer_c_watchlist` 留在 shadow / 观察层；
2. 不再让它直接占 formal `selected` 名额；
3. 让 formal 票优先留给更接近 payoff-first 目标的来源。

### beta：先收 formal buy，而不是先改执行动作

beta 侧这轮最关键的判断不是“执行模式太保守”，而是“formal buy 里混进了不该走 formal execution 的名字”。

当前最优动作顺序是：

1. 先用 `layer_c_watchlist_selected_rank_cap=0` 把 formal buy 收掉；
2. 再看 continuation 主链有没有被误伤；
3. 只有在更长窗口里仍然稳定，才讨论默认 profile 是否跟进。

### gamma：状态是 `governed_shadow_ready`，不是 `default_upgrade_ready`

gamma 侧现在可以给出更明确的纪律口径：

1. **可以推进 governed shadow rollout**
2. **不改默认 profile**
3. **继续扩窗做样本外验证**
4. **等更多 closed-cycle 证据后，再决定要不要进默认升级评审**

## 执行方案

### 方案名

**layer_c_formal_precision_tightening**

### 当前实现载体

- shadow profile：`btst_precision_v2_layer_c_watchlist_shadow`
- 关键参数：`layer_c_watchlist_selected_rank_cap=0`

### 当前推荐动作

1. 正式层继续保持 baseline，不直接切默认；
2. 所有与 `layer_c_watchlist` formal 收缩相关的判断，先走 shadow replay；
3. 每次扩窗后都重新生成 rollout decision artifact，再决定是否升级状态。

## 如何复核这条结论

### 第一步：从周验证清单直接回放 shadow replay

现在 `scripts/analyze_btst_shadow_profile_replay.py` 已经支持直接吃周验证清单，不用再手工拼 `daily_events.jsonl` 列表。

建议固定对比：

- baseline：`btst_precision_v2`
- shadow：`btst_precision_v2_layer_c_watchlist_shadow`

核心输入：

- `data/reports/btst_weekly_validation_20260506_20260522.json`

核心产物：

- `data/reports/btst_shadow_profile_replay_sidecar_aware_20260506_20260522.json`
- `data/reports/btst_shadow_profile_replay_sidecar_aware_20260506_20260522.md`

### 第二步：把 payoff 结果和 replay delta 合成一张 rollout decision 卡

当前统一口径已经写进：

- `data/reports/btst_layer_c_rollout_validation_20260506_20260522.json`
- `data/reports/btst_layer_c_rollout_validation_20260506_20260522.md`

只要这张卡仍然维持：

- `shadow_hit_rate_15pct > selected_hit_rate_15pct`
- `execution_eligible_delta < 0`
- `buy_order_delta < 0`

就继续保留 `governed_shadow_ready` 状态。

## 现在不要做什么

1. 不要把 `layer_c_watchlist` 的收缩直接当成默认 live 升级完成；
2. 不要因为这条线有效，就顺手把 `short_trade_boundary` 一起全局收掉；
3. 不要把 runner recall、boundary 契约修复、`layer_c_watchlist` formal 收缩混成一个动作同时上线。

## 下一步

当前最稳的推进顺序是：

1. 继续沿 `layer_c_formal_precision_tightening` 做更长窗口 shadow replay；
2. 同步推进 `boundary` 契约修复和研究面降噪，避免上游噪声重新污染 rollout 判断；
3. 等扩窗后的 governed artifact 仍然稳定，再决定是否进入默认升级评审。
