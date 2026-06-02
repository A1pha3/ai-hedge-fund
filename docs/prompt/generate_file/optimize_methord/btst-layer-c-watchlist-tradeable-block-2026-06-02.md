# BTST `layer_c_watchlist` tradeable 层封堵（2026-06-02）

## 一句话结论
`layer_c_watchlist` 在近期窗口里呈现稳定的 tradeable payoff drag（尤其是 5D/+15% runner 目标几乎为 0 命中），因此把它从 **tradeable（selected / near_miss / execution_eligible / buy_order）** 的名额中系统性封堵，作为“降噪 + 提升次日胜率/回撤控制”的治理动作；默认不动 `btst_precision_v2`，仅新增可 rollout 的 profile 变体。

---

## 证据（来自 frozen replay，对账可复现）

### 1) 在 paper_trading_window_20260429~20260514 中，封堵 layer_c 会真实减少 tradeable 并移除 buy_order
使用 `scripts/analyze_btst_shadow_profile_replay.py` 对窗口 `data/reports/paper_trading_window_20260429_20260514_live_m2_7_001309_window_generation_20260518/daily_events.jsonl` 做 frozen replay：

- baseline：`momentum_optimized` + overrides 允许 layer_c（`layer_c_watchlist_selected_rank_cap=999`, `layer_c_watchlist_near_miss_rank_cap=999`）
- shadow：`momentum_optimized` + overrides 封堵 layer_c（两个 cap 均为 0）

结果（见 session-state artifacts `shadow_profile_replay_window_20260429_20260514_layerc_block_20260602.{md,json}`）：
- `selected_count`: **116 → 105**（-11）
- `near_miss_count`: **61 → 52**（-9）
- `buy_order_count`: **1 → 0**（-1）
- 被移除 buy_order / execution_eligible：`20260430` 的 **688183**

### 2) `btst_precision_v2` 保持不变，但新增 `btst_precision_v2_no_layer_c_watchlist` 可用于 shadow/rollout
对同一窗口对比：
- baseline：`btst_precision_v2`
- shadow：`btst_precision_v2_no_layer_c_watchlist`

结果（见 session-state artifacts `shadow_profile_replay_window_20260429_20260514_btst_v2_no_layerc_20260602.{md,json}`）：
- `selected_count`: **53 → 49**（-4）
- `near_miss_count`: **17 → 13**（-4）
- `buy_order_count`: **1 → 1**（0）

### 3) 扩窗验证（20260506~20260529）：封堵 layer_c 的净影响较小，但确实移除部分 execution_eligible / buy_orders
使用 202605 的 32 个 paper_trading frozen `daily_events.jsonl` 作为 source（trade_dates 覆盖 20260506~20260529），对比：
- baseline：`btst_precision_v2`
- shadow：`btst_precision_v2_no_layer_c_watchlist`

结果（见 session-state artifacts `shadow_profile_replay_window_20260506_20260529_btst_v2_no_layerc_20260602.{md,json}`）：
- `buy_order_count`: **3 → 1**（-2）
- `execution_eligible_count`: **8 → 2**（-6）
- `selected_count`: **62 → 54**（-8）
- `near_miss_count`: **33 → 26**（-7）

被移除的 buy_orders（重复出现的票，值得重点复盘）：
- `20260522`：300054
- `20260529`：300054

被移除的 execution_eligible（按日期）：
- `20260519`：600487
- `20260522`：300054
- `20260525`：688008
- `20260526`：300054
- `20260527`：001309
- `20260529`：300054

这说明：封堵 layer_c 不是“只改排序”，而是对 tradeable 集合有可量化的净收缩；但在 202605 扩窗里对 buy_orders 的净影响相对温和（可能被其他 gate/预算覆盖所“吸收”）。同时通过“新增 variant”保持默认 BTST profile 不被隐式改变，满足 rollout 纪律。

---

## 实现（代码改动）

### A) `momentum_optimized` 默认封堵 layer_c_watchlist（tradeable 层）
文件：`src/targets/short_trade_target_profile_data.py`
- 在 `momentum_optimized` 中设置：
  - `layer_c_watchlist_selected_rank_cap=0`
  - `layer_c_watchlist_near_miss_rank_cap=0`

> 说明：这会连带影响以 `momentum_optimized` 为基底的 replace profile（如 `momentum_tuned*`），属于“默认降噪”策略。

### B) 新增 `btst_precision_v2_no_layer_c_watchlist`（rollout-safe 变体）
文件：`src/targets/short_trade_target_profile_data.py`
- 新增 profile：
  - `btst_precision_v2_no_layer_c_watchlist = replace(btst_precision_v2, layer_c_watchlist_selected_rank_cap=0, layer_c_watchlist_near_miss_rank_cap=0)`

### C) 测试修正（保持 override-plumbing 测试语义）
`momentum_optimized` 默认行为变化后，`tests/test_analyze_btst_shadow_profile_replay_script.py` 中的 override 测试更新为：
- baseline 显式 override cap=1（允许一条 layer_c）
- shadow override cap=0（封堵）

---

## 如何使用（落地方式）

### 方式 1：继续用 momentum_optimized（默认已封堵）
无需额外参数；如果想临时放开用于对比，可通过 profile overrides：
```bash
uv run python scripts/analyze_btst_shadow_profile_replay.py \
  --frozen-plan-source <path/to/daily_events.jsonl> \
  --baseline-profile momentum_optimized \
  --baseline-overrides '{"layer_c_watchlist_selected_rank_cap": 999, "layer_c_watchlist_near_miss_rank_cap": 999}' \
  --shadow-profile momentum_optimized \
  --shadow-overrides '{"layer_c_watchlist_selected_rank_cap": 0, "layer_c_watchlist_near_miss_rank_cap": 0}'
```

### 方式 2：BTST 正式 profile 先不动，使用 variant 做 governed shadow / A/B
在 pipeline / replay 中把 profile name 切为：
- baseline：`btst_precision_v2`
- shadow：`btst_precision_v2_no_layer_c_watchlist`

---

## 风险与边界
- 这不是直接提升 5D/+15% 命中率的“alpha 因子”，而是 **降噪/治理**：通过去掉低质量来源，给更高质量来源更多名额，并降低执行侧的坏样本暴露。
- 是否将 `btst_precision_v2_no_layer_c_watchlist` 推为默认，需要扩窗 + 样本外验证后再决定（推荐走 report→shadow→enforce 的 rollout 节奏）。
