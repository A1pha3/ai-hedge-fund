# BTST upstream shadow 盈利硬崖延伸惩罚闸门方案（2026-05-25）

## 结论先说

这轮主线没有继续扩大 `selected_historical_proof_missing` 的封杀范围，而是先把那条更宽的 proof gate 回滚，再收敛成一条更窄、更安全的 `profitability extension` 闸门。

当前验证下来的最小有效方案是：

1. 只处理 `candidate_source == upstream_liquidity_corridor_shadow`；
2. 只处理当前已经落到 `near_miss` 的样本；
3. 只在样本同时满足 `profitability_hard_cliff`、`historical_evaluable_count < 1`、`extension_without_room_penalty >= 0.40` 时，才把它从 `near_miss` 直接打成 `rejected`。

这条窄 gate 的价值，不在于“解决所有 upstream shadow 误报”，而在于它能精准砍掉当前 residual FP 面里最差的那两个名字，同时不再误杀已经证明会走强的 FN 样本。

## 为什么不能继续放大 proof gate

我们先做过一轮更激进的尝试：把 `selected_historical_proof_missing` 从“selected 降级 near_miss”扩大成“selected / near_miss 都直接 rejected”。

从表面上看，这条规则很诱人，因为它会把 residual FP 一次性清空；但真实反事实审计结果证明，它太宽了：

- 在 repeat-saturation guard 之后的 residual 面里，基线是：
  - `FN = 27`
  - `FP = 3`
- broad proof gate 会移除：
  - `FP = 3`
  - 但同时也会移除 `FN = 6`

而且这 `6` 个被误伤的 FN 里，有些是明显不能丢的：

1. `300720`（`2026-03-23`）  
   - `T+2 close return ≈ +18.28%`
   - `future_high_hit_15pct_2_5d = true`
2. `600844`（`2026-03-25`）  
   - `T+2 close return ≈ +20.82%`
   - `future_high_hit_15pct_2_5d = true`

所以这条 broad proof gate 虽然“看起来很干净”，但它不符合主线目标：它是在用大幅牺牲真实赢家，换表面上的 FP 清零。

## 这轮真正保留的最小规则

### alpha

alpha 侧这次不再把“无 evaluable history”的所有 upstream shadow 候选一刀切掉，而是回到更贴近 residual FP 子簇真实形态的条件：

- 候选已经只是 `near_miss`，说明它不是被正式晋级强行拉高的样本；
- `profitability_hard_cliff` 明确出现，说明盈利延续质量本身已经在发出风险信号；
- `extension_without_room_penalty >= 0.40`，说明样本已经进入“延伸过重、上方空间不足”的坏区间；
- `historical_evaluable_count < 1`，说明它又缺少能证明“这种延伸仍可继续跑”的历史支撑。

这四个条件叠加后，才是当前 residual FP 面里最值得直接拦掉的那层。

### beta

beta 侧没有去改全局 profile，也没有去下调全仓通用的 stale / extension hard block threshold，而是把逻辑放在 final decision override 层：

- 文件：`src/targets/short_trade_target_evaluation_helpers.py`
- 封装入口：`src/targets/short_trade_target.py`

这样做的好处有两个：

1. 改动范围小，不会把整个 short-trade snapshot / profile block contract 一起拖进重构；
2. 规则只会作用于 `upstream_liquidity_corridor_shadow` 的 residual near-miss 子簇，不会误伤别的 source family。

最终 rejection reason 落成：

- `profitability_unknown_extension_penalty`

### gamma

gamma 侧重点不是“这条规则能否多砍几个 FP”，而是先验证它有没有重新砍到 FN。

在当前 residual surface 上，结果是：

- 被移除的 FP：`2`
  1. `603660`（`2026-05-20`）
  2. `000301`（`2026-05-14`）
- 被移除的 FN：`0`

这正是本轮方案可以保留的关键理由。

## 当前 residual 面上的真实变化

以 repeat-saturation guard 之后的 residual 面为基线：

- 基线：
  - `FN = 27`
  - `FP = 3`
- 新 gate 落地后：
  - `FN = 27`
  - `FP = 1`

也就是：

1. `false_positive_removed = 2`
2. `false_negative_removed = 0`

被精准打掉的两个 residual FP 具有非常一致的形态：

| ticker | trade_date | extension_without_room_penalty | stale_trend_repair_penalty | T+2 close return |
|---|---|---:|---:|---:|
| 603660 | 2026-05-20 | 0.45 | 0.47 | -5.34% |
| 000301 | 2026-05-14 | 0.4406 | 0.2717 | -3.83% |

它们共同说明一个事实：

- 这批票并不是“差一点就能继续跑”的 near-miss；
- 而是“盈利质量已经掉下硬崖，同时走势又已经延伸过重”的 near-miss。

## 这轮代码落点

- `src/targets/short_trade_target_evaluation_helpers.py`
  - 新增窄范围 `profitability_unknown_extension_penalty` decision override
- `src/targets/short_trade_target.py`
  - 扩展薄封装签名，把 `candidate_source / profitability_hard_cliff / extension_without_room_penalty` 传入 helper
- `tests/targets/test_target_models.py`
  - 新增高 extension 样本必须 `rejected`
  - 新增中等 extension 样本必须保留 `near_miss`

## 验证

本轮 focused regression：

```bash
uv run pytest tests/targets/test_target_models.py tests/test_analyze_btst_candidate_pool_corridor_proof_gate_outcomes_script.py -q
```

结果：`130 passed`

对应 impact artifact：

- `/Users/matrix/.copilot/session-state/359fb789-0911-44b2-900a-26f7e4891fab/files/profitability_unknown_extension_gate_impact_2026-05-25.json`
- `/Users/matrix/.copilot/session-state/359fb789-0911-44b2-900a-26f7e4891fab/files/profitability_unknown_extension_gate_impact_2026-05-25.md`

## 当前判断

这轮方案值得保留，因为它完成了一个很重要的主线动作：

1. 先证明 broad proof gate 虽然“看起来强”，但会误伤真实赢家，所以不能保留；
2. 再把规则收敛成一条真正 `2 FP / 0 FN` 的最小闸门。

但它仍然不是终局方案。当前 residual FP 还剩：

- `300641`

而 `300641` 的主 reason cluster 已经不是这轮处理掉的 `profitability_hard_cliff + heavy extension`，而是更接近：

- `selected_historical_proof_missing`

所以下一阶段主线不该回到 broad proof gate，而应该继续寻找 **只打 `300641` 这类 seam、又不重伤 `300720 / 600844` 这类赢家** 的更窄契约。
