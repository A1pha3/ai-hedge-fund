# btst-5d15-boundary-source-contract-repair-2026-05-22

## 本轮性质
- 本轮只做 boundary source contract repair 的回归确认，不做 alpha 提升验证。
- 目标是确认 `trend_continuation` 与 `short_term_reversal` 在 source contract 修复后，不再被 trace 归类为 `missing_everywhere`。
- 结论必须保持 fail-closed：只要链路下游仍未稳定暴露这些键，就只能继续归因为 contract 诊断，不得解释为选股能力提升。

## 回归结论
- 针对 `tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py` 新增回归后，先看到失败：旧夹具仍把 `trend_continuation` / `short_term_reversal` 留空，继续被判成 `missing_everywhere`。
- 更新 source-side fixture 后，同一条 trace 证明这两个键已从 `missing_everywhere` 退出。
- 在 source 已有值、但 attached/snapshot surface 仍未同步暴露的场景下，这两个键现在会进入下游 contract 诊断范围，而不是继续被误判为 upstream 完全缺失。

## live artifact 解释
- 本次重跑 `scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py` 后，刷新出的 live artifact 指向 `data/paper_trading_window_sample`，`boundary_row_count = 0`。
- 这说明当前工作树可供该脚本识别的 boundary 样本为空；它只能证明“本次重跑没有发现可追踪样本”，不能证明 repair 已经带来任何收益改善。
- 因为 live artifact 为零样本，所以治理结论仍然必须是 fail-closed：没有新证据支持放宽 boundary governance，也没有证据支持推进 runtime。

## 明确禁止的误读
- 这不是 alpha improvement validation。
- 这不构成 `docs/prompt/find_actor/` 的候选材料。
- 这不具备提升到 `ai-hedge-fund-btst` 流程的资格。

## 本轮可接受的唯一结论
- 允许确认：source contract repair 已被回归测试覆盖，且 `trend_continuation` / `short_term_reversal` 不应再被默认视为 `missing_everywhere`。
- 不允许确认：5D/+15% 胜率提升、赔率提升、筛选质量提升、或任何实盘可推广结论。
