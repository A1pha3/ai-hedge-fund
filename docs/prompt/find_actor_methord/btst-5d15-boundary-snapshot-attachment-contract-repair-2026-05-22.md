# btst-5d15-boundary-snapshot-attachment-contract-repair-2026-05-22

## 结论

- 本轮修复针对的是 `selection_snapshot.json` / `selection_target_replay_input.json` 的序列化表层契约，不是新的 Alpha 因子。
- `breakout_freshness`、`trend_acceleration`、`volume_expansion_quality`、`close_strength` 现在会在 `selection_targets[*].short_trade` 顶层显式暴露。
- `trend_continuation`、`short_term_reversal` 仍然保持默认关闭（fail-closed）：如果它们只存在于嵌套层，边界追踪仍会继续报 `fix_snapshot_attachment_contract`。

## 这轮修复解决了什么

1. 保持短线评估器不变，不修改因子计算逻辑。
2. 仅在 artifact 写出前，将已存在的四个字段提升到 `short_trade` 表层。
3. 让 `selection_snapshot.json` 与 `selection_target_replay_input.json` 复用同一份序列化契约。

## 如何验证

1. 直接回归：`uv run pytest tests/research/test_selection_artifact_writer.py -q`
2. 边界回归：`uv run pytest tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py -q`
3. 本地诊断：`uv run python scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py`

## 默认关闭（fail-closed）说明

- 如果本地样本仍然为 `boundary_row_count=0`，这只说明当前样本窗口没有可追踪的边界行，不代表可以跳过回归测试。
- 本文档不能进入 `docs/prompt/find_actor/`。
- 本轮修复不能直接进入 `ai-hedge-fund-btst`，也不能被当作因子或策略提升结论。
