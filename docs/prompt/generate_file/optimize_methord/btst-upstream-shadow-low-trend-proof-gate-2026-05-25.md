# BTST upstream shadow 低趋势 proof gate 方案（2026-05-25）

## 结论先说

这轮不是把 `selected_historical_proof_missing` 继续做大，而是在已经落地的 `profitability unknown-extension gate` 之后，专门把 residual 面里最后那一个 `300641` seam 单独切出来，做成一条更窄的低趋势 proof gate。

当前验证下来的最小有效方案是：

1. 只处理 `candidate_source == upstream_liquidity_corridor_shadow`；
2. 只处理当前还停留在 `near_miss` 的样本；
3. 只在 `selected_historical_proof_deficiency["proof_missing"] == True` 且 `trend_acceleration < 0.65` 时，才直接拒绝。

这条 gate 的目标非常明确：不是继续清理“所有无历史 proof 的 shadow 候选”，而是只清理当前 residual surface 里那类 **连趋势加速度都不再 supportive，却还因为 proof 缺失停留在 near-miss 边界上** 的名字。

## 为什么还要再补这一刀

上一轮已经把 residual FP 里的两只盈利硬崖样本拿掉了：

1. `603660`
2. `000301`

但当前 residual surface 里仍剩下最后一只：

- `300641`

它和前两只并不是同一种问题。`300641` 的形态更接近：

- `selected_historical_proof_missing`
- `trend_acceleration = 0.581`
- `close_strength = 0.7943`
- `extension_without_room_penalty = 0.0422`
- `T+2 close return ≈ -6.65%`

也就是说，它不是“延伸过重”的误报，而是 **趋势本身已经不够强，却因为缺少历史 proof 没有被进一步打掉** 的误报。

## 为什么不能回到 broad proof gate

这一步最重要的纪律，是不能因为 `300641` 还剩着，就重新回去打开 broad proof gate。

原因已经被上一轮真实审计证明过：

- 如果把 `selected_historical_proof_missing` 扩大成所有 `selected / near_miss` 都直接 rejected，
- 虽然会把 residual FP 一次性清空，
- 但也会同时误伤 `6` 个 residual FN。

其中最不能接受的两个样本是：

1. `300720`  
   - `T+2 close return ≈ +18.28%`
   - `future_high_hit_15pct_2_5d = true`
2. `600844`  
   - `T+2 close return ≈ +20.82%`
   - `future_high_hit_15pct_2_5d = true`

所以这一轮只能继续往“更窄、更像 300641 本身”的契约上收，而不能把 old proof gate 重新放回来。

## 这轮采用的最小规则

### alpha

alpha 侧先把 residual proof-missing cohort 单独拆开看，结论很清楚：

- 在当前 residual proof-missing cohort 里，
  - `300641` 是唯一一只 `trend_acceleration < 0.65` 的 false positive；
  - 当前 residual false negatives 里，没有任何一只会落入这个区间。

也就是：

- `proof_missing + trend_acceleration < 0.65`

在当前主线数据面上，正好把 `300641` 单独圈出来。

### beta

beta 侧仍然没有去动全局 profile，也没有去改 snapshot block threshold，而是继续把逻辑收在 final decision override 层：

- 文件：`src/targets/short_trade_target_evaluation_helpers.py`
- 封装入口：`src/targets/short_trade_target.py`

最终 rejection reason 落成：

- `selected_historical_proof_low_trend_acceleration`

这一步的价值在于：

1. 不影响更广泛的 unknown-proof 样本；
2. 不需要重做 explainability / profile block 主链；
3. 仍然保持和上一轮 profitability gate 一样的“窄 seam 修补”风格。

### gamma

gamma 侧重点仍然是先看误伤：

- 单独看这条 low-trend proof gate：
  - `false_positive_removed = 1`
  - `false_negative_removed = 0`
- 被移除的就是：
  - `300641`

再和上一轮的 profitability unknown-extension gate 叠加后，当前 residual surface 变成：

- `false_positive_removed = 3 / 3`
- `false_negative_removed = 0 / 27`
- `remaining_false_positive_count = 0`

这说明这两条 gate 现在已经把当前 residual upstream-shadow FP 面完整收掉了，而且没有在当前样本面里换来新的 FN 成本。

## 这轮代码落点

- `src/targets/short_trade_target_evaluation_helpers.py`
  - 新增 low-trend proof gate decision override
- `src/targets/short_trade_target.py`
  - 扩展薄封装签名，把 `trend_acceleration` 传入 helper
- `tests/targets/test_target_models.py`
  - 新增 helper 级 TDD：
    - low-trend proof-missing corridor near-miss 必须 `rejected`
    - supportive trend 的 proof-missing corridor near-miss 必须保留 `near_miss`

## 验证

本轮 focused regression：

```bash
uv run pytest tests/targets/test_target_models.py tests/test_analyze_btst_candidate_pool_corridor_proof_gate_outcomes_script.py -q
```

结果：`132 passed`

对应 dual-gate impact artifact：

- `/Users/matrix/.copilot/session-state/359fb789-0911-44b2-900a-26f7e4891fab/files/upstream_shadow_dual_gate_impact_2026-05-25.json`
- `/Users/matrix/.copilot/session-state/359fb789-0911-44b2-900a-26f7e4891fab/files/upstream_shadow_dual_gate_impact_2026-05-25.md`

## 当前判断

这轮 low-trend proof gate 值得保留，因为它完成了一个非常关键的主线收尾动作：

1. 不重开 broad proof gate；
2. 只用一条更窄的趋势约束，把 `300641` 单独拿掉；
3. 让当前 residual upstream-shadow FP surface 暂时清零。

下一阶段不该继续围着旧 residual FP 面反复修补，而应该回到新的 dual-gate baseline，重新刷新 dossier，确认当前系统在这个 baseline 上下一组真正还限制胜率 / 赔率的问题是什么。
