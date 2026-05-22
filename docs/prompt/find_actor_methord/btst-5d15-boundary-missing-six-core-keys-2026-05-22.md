# btst-5d15-boundary-missing-six-core-keys-2026-05-22

## 本轮定位的核心结论
- 本轮不是 alpha 提升结论，而是对 `short_trade_boundary` / `layer_b_boundary` 上游 contract 的逐键追踪。
- live trace 共覆盖 121 条 boundary row。
- 4 个键 `breakout_freshness` / `trend_acceleration` / `volume_expansion_quality` / `close_strength` 并没有在链路中彻底消失：
  - 在 `short_trade_boundary` 的 source entry 中可见 75 次；
  - 在 attached / snapshot 的 `short_trade.metrics_payload` 中可见 121 次；
  - 但在当前 round1 row builder 可读取的 surface 层中始终为 0 次。
- 2 个键 `trend_continuation` / `short_term_reversal` 在 121 条样本里 source / attached metrics / snapshot metrics 都为 0，属于真正的 upstream 缺失。
- `t0_tail_strength` 在这次严格 trace 的 source / attached surface / snapshot surface / metrics 层里也都是 0；它不能作为本轮 upstream contract 的有效幸存键。

## Alpha 视角
- 这轮结果说明 boundary 样本里并不是“6 个键全部彻底消失”。
- 真实情况是：
  - 4 个键已经进入 attached / snapshot 的 nested metrics；
  - 但当前研究行提取逻辑没有把这些 nested metrics 暴露到可分析 surface；
  - 另外 2 个键则确实还没有进入 upstream source contract。
- 因此这轮不能得出任何“5天15%目标已经改善”的结论，也不能进入因子验证/推广流程。

## Beta 视角
- 当前最重要的不是继续在 fill-path 层补洞，而是先修 boundary source contract。
- 原因是 governance board 仍然 fail-closed 地指向 `fix_boundary_source_contract`：
  - 只要 `trend_continuation` / `short_term_reversal` 仍然在 source 侧完全缺失，
  - 就不能把问题简单归为 snapshot / attachment surface 暴露不足。
- 等 source contract 补齐后，第二步才是把 4 个已经存在于 nested metrics 的键继续提升到 row builder 可见的 surface 层。

## Gamma 视角
- 121 条样本全部继续保持 fail-closed。
- 治理结论不是 runtime 放行，而是：
  - 第一优先级：`fix_boundary_source_contract`
  - 第二优先级：在 source 修复后，再看是否需要 `fix_snapshot_attachment_contract`
- 当前没有任何理由把 boundary cohort 重新接入正式选股 surface。

## 与 live artifact 对齐的数字
- boundary_row_count = 121
- `surface_trace_status_counts`:
  - `missing_at_source` = 547
  - `dropped_before_snapshot` = 300
- `missing_six_key_diagnosis_counts`:
  - `nested_only` = 484
  - `missing_everywhere` = 242
  - `surface_visible` = 0
  - `lost_after_source` = 0
- source 分组：
  - `short_trade_boundary`: 75 行，`nested_only=300`，`missing_everywhere=150`
  - `layer_b_boundary`: 46 行，`nested_only=184`，`missing_everywhere=92`

## 结论与后续动作
- 本轮只确认 upstream contract 问题，不确认任何 alpha 提升。
- 不推进到 `docs/prompt/find_actor/`。
- 不接入 `ai-hedge-fund-btst`。
- 下一轮应先补 `trend_continuation` / `short_term_reversal` 的 boundary source contract，再重新跑同一条 trace，确认：
  1. `missing_everywhere` 是否归零；
  2. 4 个 nested-only 键是否还需要 surface 提升；
  3. 修复后是否有资格进入后续回测验证。
