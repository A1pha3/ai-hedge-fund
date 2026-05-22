# btst-5d15-boundary-missing-six-core-keys-2026-05-22

## 本轮定位的核心结论
- 本轮不是 Alpha 提升结论，而是对 `short_trade_boundary` / `layer_b_boundary` 上游契约（contract）的逐键追踪。
- 实时追踪（live trace）共覆盖 121 条边界样本行（boundary row）。
- 4 个键——`breakout_freshness`、`trend_acceleration`、`volume_expansion_quality`、`close_strength`——并没有在链路中彻底消失：
  - 在 `short_trade_boundary` 的来源条目（source entry）中共出现 75 次；
  - 在 attached / snapshot 的 `short_trade.metrics_payload` 中共出现 121 次；
  - 但在当前可供 round1 row builder 读取的表层（surface）中始终为 0 次。
- 2 个键——`trend_continuation`、`short_term_reversal`——在 121 条样本里，无论来源侧、attached metrics 还是 snapshot metrics 都为 0，属于真正的上游缺失（upstream missing）。
- `t0_tail_strength` 在本次严格 trace 的 source、attached surface、snapshot surface 与 metrics 层中也全部为 0，因此不能作为本轮上游契约中的有效幸存键。

## Alpha 视角
- 这轮结果说明：boundary 样本里并不是“6 个键全部彻底消失”。
- 更准确的情况是：
  - 4 个键已经进入 attached / snapshot 的嵌套 metrics；
  - 但当前研究行提取逻辑没有把这些嵌套 metrics 暴露到可分析的表层；
  - 另外 2 个键则确实尚未进入上游 source contract。
- 因此，本轮不能得出任何“5 天 15% 目标已经改善”的结论，也不能进入因子验证或推广流程。

## Beta 视角
- 当前最重要的工作，不是继续在补全路径（fill-path）层补洞，而是优先修复边界来源契约（boundary source contract）。
- 原因在于治理看板（governance board）仍然以默认关闭（fail-closed）的方式指向 `fix_boundary_source_contract`：
  - 只要 `trend_continuation` / `short_term_reversal` 仍然在 source 侧完全缺失；
  - 就不能把问题简单归类为 snapshot / attachment 表层暴露不足。
- 待来源契约（source contract）补齐之后，第二步才是评估是否需要把 4 个已存在于嵌套 metrics 中的键继续提升到 row builder 可见的表层。

## Gamma 视角
- 121 条样本全部继续保持默认关闭（fail-closed）。
- 当前治理结论不是运行时放行，而是：
  - 第一优先级：`fix_boundary_source_contract`
  - 第二优先级：待 source 修复后，再评估是否需要 `fix_snapshot_attachment_contract`
- 当前没有任何理由把这批边界样本群（boundary cohort）重新接回正式选股表层。

## 与 live artifact 对齐的数字
- `boundary_row_count = 121`
- `surface_trace_status_counts`：
  - `missing_at_source = 547`
  - `dropped_before_snapshot = 300`
- `missing_six_key_diagnosis_counts`：
  - `nested_only = 484`
  - `missing_everywhere = 242`
  - `surface_visible = 0`
  - `lost_after_source = 0`
- 按来源分组：
  - `short_trade_boundary`：75 行，`nested_only=300`，`missing_everywhere=150`
  - `layer_b_boundary`：46 行，`nested_only=184`，`missing_everywhere=92`

## 结论与后续动作
- 本轮只确认上游契约问题，不确认任何 Alpha 提升。
- 不推进到 `docs/prompt/find_actor/`。
- 不接入 `ai-hedge-fund-btst`。
- 下一轮应先补齐 `trend_continuation` / `short_term_reversal` 的边界来源契约（boundary source contract），再重跑同一条实时追踪（trace），确认：
  1. `missing_everywhere` 是否归零；
  2. 4 个 `nested_only` 键是否仍需要表层提升；
  3. 修复后是否具备进入后续回测验证的资格。
