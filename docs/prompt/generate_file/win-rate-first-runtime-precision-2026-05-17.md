# win-rate-first-runtime-precision-2026-05-17

## 原理
- 这次改动把 BTST 的 win-rate-first 目标落到了运行时 P5 执行合同层，而不是只停留在离线诊断里。
- 当 `BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE=true` 时，`selected` 里的候选如果没有 `execution_ready` 级别的 prior quality，就会从正式买入通道降到 `near_miss`；只有 `execution_ready` 且未被正式 execution block 的名字，才保留 `selected` 和 `execution_eligible` 身份。
- 同时，已经被 P2/P3/P5/P6 正式 block 的 raw `selected` 名字，会保留原始 `selected` provenance，避免把“形式上被挡住的好名字”和“本来就不该进主交易通道的边缘名字”混为一谈。

## 提升效果
- 提升不是“强行把更多名字打掉”，而是把主交易通道收紧到更接近真实可执行、历史先验更强的那一层。
- 这能直接减少 `watch_only`、prior quality 缺失、或仅靠标签优势挤进 `selected` 的名字进入正式买单，从机制上优先保护胜率。
- 当前已验证的效果是**运行时精度提升**：主交易通道更干净、execution eligibility 更一致、formal-blocked selected 的解释链更清楚；本轮没有单独宣称整体样本外胜率已经被量化抬升若干百分点。

## 如何验证
- 运行时行为验证来自 `tests/test_task1_win_rate_first_precision.py`：
  - `watch_only` 的 raw `selected` 在精度模式下会被降到 `near_miss`，并写入 `win_rate_first_precision_prior_not_execution_ready`。
  - `execution_ready` 的候选会保留 `selected`，同时继续保留 `execution_eligible=True`。
  - 已经 formal blocked 的 raw `selected` 不会被二次污染新的 P5 downgrade reasons，也不会丢失 blocked-selected provenance。
- 关键实现位于 `src/execution/daily_pipeline.py` 的 `_enforce_btst_execution_contract_p5()`，它把 `execution_ready`、formal block flags、buy order 过滤和 `execution_eligible` 统一到同一执行面。
- 这轮收口时，聚焦回归继续通过：`uv run pytest tests/test_optimize_profile_script.py tests/backtesting/test_walk_forward.py tests/targets/test_trend_continuation_strength_v2.py -q`。

## 观察到的权衡
- 这是典型的 precision-over-coverage 选择：会牺牲一部分 `selected` 覆盖率，换取更严格的入选质量。
- 对于某些本来处在边界附近、但并非 execution-ready 的名字，报告里更容易出现在 `near_miss` / watchlist 语境，而不是正式主交易语境。
- 因为该模式默认仍是关闭的，所以它目前属于**经过验证、可控启用**的运行时收紧能力，而不是强制替换所有 BTST 运行。

## 如何使用
- 运行时启用方式：
  - `BTST_0422_P5_EXECUTION_CONTRACT_MODE=enforce`
  - `BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE=true`
- 适用场景：当目标明确是“优先提高胜率”而不是“尽量多给候选”时，应打开该模式。
- 对 `ai-hedge-fund-btst` 的使用含义：后续若当前 run artifacts 显示启用了这套精度模式，中文报告可以明确说明主交易名单更偏向 `execution_ready` 候选；但如果当前 artifacts 没体现该模式，就不能凭这份文档反推当次运行已经启用。
