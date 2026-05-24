# BTST relief alpha 质量闸门方案（2026-05-24）

## 结论先说

这轮优化的目标，不是继续放宽 execution gating，而是把已经放通的 relief 车道重新收紧到更像 `5` 日扩张票的那一小段。

当前验证下来的最小有效方案是：

1. 对 `shadow_only` / `halt` 的 relief 正式晋级，新增 `score_target >= 0.50` 约束；
2. 同时要求样本带有 `fresh_catalyst_support` 或 `catalyst_theme_short_trade_carryover_applied` 这类催化支撑；
3. carryover relief 继续保留，但也同步受 `score_target >= 0.50` 约束。

这不是最终解，因为距离目标 `5` 日内 `55%` 概率涨超 `15%` 还很远；但它已经把“弱 relief 样本混进正式单”这个问题明显压下去了。

## 为什么要加这道闸门

前一轮已经确认，系统的主矛盾从 execution chain 断裂，重新回到了上游候选质量：

- 在旧稳定逻辑下，`2026-05-06` 到 `2026-05-14` 这些有完整 `5` 日后验窗口的正式买单一共 `6` 笔；
- 其中只有 `1` 笔在 `T+1 open` 入场后，`5` 日内最高涨幅超过 `15%`；
- `hit_15pct_rate ≈ 16.67%`，`mean_max_high_return_5d ≈ +7.60%`。

更关键的是，这些完整窗口日期里，并没有“被 daily-limit 挤掉的更强隐藏赢家”。问题不在排序，而在**真正进正式单的 relief 样本本身就偏弱**。

进一步拆开看，拖后腿最明显的是两类名字：

1. `score_target` 明显偏低的 relief 样本；
2. 只有边界突破形态、但缺少 fresh catalyst / carryover 支撑的 relief 样本。

## 这轮采用的最小规则

### alpha

alpha 侧不再把所有 close-continuation relief 一视同仁，而是增加一层更贴近 `5` 日扩张目标的候选闸门：

- `score_target >= 0.50`
- `positive_tags` 必须带 `fresh_catalyst_support` 或 `catalyst_theme_short_trade_carryover_applied`

这一步的含义很直接：同样是 relief，只有“当前分数没掉到边界下方太远、并且催化没有明显衰减”的样本，才继续保留正式晋级资格。

### beta

beta 侧没有重写执行链，只在 `resolve_btst_shadow_promotion_payload()` 这一个 helper 里补了两道门槛：

- close-continuation relief：要求 `score_target >= 0.50` 且 relief context 有催化支撑；
- carryover relief：保留 carryover 逻辑，但同样要求 `score_target >= 0.50`。

这样做的好处是改动范围很小，P2 / P5 / P6 原有链路不需要重新设计。

### gamma

gamma 侧负责验证这道闸门会不会把刚恢复出来的正式单一起砍掉。结果是：

- `2026-05-20`：正式单从 `['002222', '002371']` 收紧到 `['002222']`
- `2026-05-21`：正式单保留为 `['600176', '002222']`

也就是说，它砍掉了更像“弱 relief 边界样本”的 `002371`，但没有把这两天最关键的正式主票一起清空。

## 完整 5 日窗口上的变化

把新规则套回 `2026-05-06` 到 `2026-05-14` 这些已经能完整观察 `5` 个交易日后验窗口的日期后，结果变成：

- 正式买单样本数：`6 -> 3`
- `5` 日内最高涨幅 >= `15%` 的命中数：`1 -> 1`
- `hit_15pct_rate`：`16.67% -> 33.33%`
- `mean_max_high_return_5d`：`+7.60% -> +10.97%`

对应的完整窗口正式单变成：

1. `2026-05-12`：`002222`，`max_high_return_5d ≈ +15.32%`
2. `2026-05-14`：`002222`，`max_high_return_5d ≈ +3.78%`
3. `2026-05-14`：`300054`，`max_high_return_5d ≈ +13.80%`

这组数说明两件事：

1. 新闸门确实把 weakest relief 样本压掉了；
2. 但系统距离最终目标仍然有明显差距，不能把这轮改动包装成“已经解决 BTST 胜率 / 赔率问题”。

## 这轮代码落点

- `src/execution/btst_shadow_promotion_helpers.py`
  - 新增 relief `score_target >= 0.50` 约束
  - 新增催化支撑 tag 约束
  - carryover relief 同步纳入分数闸门
- `tests/test_btst_execution_eligibility_contract.py`
  - 增加低分 relief / 无催化 relief 的失败合同测试
- `tests/execution/test_phase4_execution.py`
  - 更新 relief backfill fixture，使其符合新的 alpha 质量门槛
- `tests/test_btst_risk_budget_overlay.py`
  - 更新 relief 风险预算与 daily-limit fixture，使其符合新闸门

## 验证

本轮 focused regression：

```bash
uv run pytest tests/execution/test_phase4_execution.py tests/test_btst_regime_gate_enforcement.py tests/test_btst_execution_eligibility_contract.py tests/test_task1_win_rate_first_precision.py tests/test_btst_risk_budget_overlay.py -q
```

结果：`210 passed`

## 当前判断

这轮方案值得保留，因为它已经显示出“少买弱 relief、把正式单重新压回更强样本”的方向性改善；但它还只是 **alpha 质量闸门的第一刀**。

下一阶段真正该继续做的，不是重新放松 execution gating，而是继续围绕：

1. `5` 日 +`15%` 标签本身重做上游候选定义；
2. 区分“次日延续强”和“`5` 日扩张强”；
3. 把 `shadow_promotion` 里那些只有边界突破、没有新鲜催化支撑的样本进一步压缩。
