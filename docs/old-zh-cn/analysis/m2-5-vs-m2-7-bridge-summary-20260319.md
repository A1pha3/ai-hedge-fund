# 2026-03-19 M2.5 与 M2.7 对照摘要

## 1. 文档目的

这份摘要用于回答两个问题：

1. MiniMax 默认模型从 M2.5 切到 M2.7 之后，历史 benchmark 语义是否发生了可见变化。
2. W0 的 M2.7 live bridge anchor 能否直接视为对当前 M2.5 基线的等价替代。

本文只记录当前已经完成的两类证据：

1. `600519` benchmark 最小重验。
2. `2026-02-02 .. 2026-03-04` 窗口的 W0 live bridge anchor。

## 2. 口径冻结

当前主基线仍固定为 [paper-trading-reentry-validation-20260317.md](./paper-trading-reentry-validation-20260317.md) 中已经确认的 frozen replay：

1. 产物目录是 [data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/session_summary.json](../../../data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/session_summary.json)
2. 模型指纹是 `MiniMax / MiniMax-M2.5`
3. `plan_generation.mode = frozen_current_plan_replay`

本轮 M2.7 bridge anchor 的产物目录是 [data/reports/paper_trading_window_20260202_20260304_bridge_live_anchor_m2_7_20260319/session_summary.json](../../../data/reports/paper_trading_window_20260202_20260304_bridge_live_anchor_m2_7_20260319/session_summary.json)

它的用途是“桥接 live anchor”，不是替换主基线。原因有两点：

1. 它使用的是 `live_pipeline`，与 frozen replay 的生成模式不同。
2. 同一 provider 的模型版本已经确认存在语义漂移，不能把不同模型路由的结果直接并入同一张主表横比。

## 3. Benchmark 最小重验结论

本轮只重验最核心的 `600519` benchmark 两个日期，目的是先判断 M2.7 是否改变 near-threshold 语义。

证据文件：

1. [data/reports/m2_7_benchmark_replays_20260319/live_replay_600519_20260224_p1.json](../../../data/reports/m2_7_benchmark_replays_20260319/live_replay_600519_20260224_p1.json)
2. [data/reports/m2_7_benchmark_replays_20260319/live_replay_600519_20260226_p1.json](../../../data/reports/m2_7_benchmark_replays_20260319/live_replay_600519_20260226_p1.json)
3. 参考边界说明见 [validation-scoreboard-20260318.md](./validation-scoreboard-20260318.md)

### 3.1 结果对照

| Date | Logged `score_final` | M2.7 Replay `score_final` | Delta | Decision |
| --- | --- | --- | --- | --- |
| `20260224 / 600519` | `0.1584` | `0.2577` | `+0.0993` | `watch -> watch` |
| `20260226 / 600519` | `0.1580` | `0.2547` | `+0.0967` | `watch -> watch` |

### 3.2 判断

1. 虽然最终决策都还停在 `watch`，但两次 replay 的 `score_final` 都被抬升到 `0.25x`，已经不是原来那种 `0.15x` 的近下沿状态。
2. 两次抬升都主要来自 `score_c` 变化，不是 `score_b` 变化，这说明漂移发生在更偏语义、agent 聚合和 Layer C 相关的部分。
3. 因此可以确认：`MiniMax-M2.7` 相对 `MiniMax-M2.5` 已经发生可见语义漂移，不能把两者结果直接当成同口径主表数据。

## 4. W0 Bridge Anchor 结论

### 4.1 核心数值

M2.5 frozen baseline 与 M2.7 live bridge anchor 的 `session_summary.json` 期末指标如下：

| Metric | M2.5 Baseline | M2.7 W0 Bridge |
| --- | --- | --- |
| Model | `MiniMax-M2.5` | `MiniMax-M2.7` |
| Plan Mode | `frozen_current_plan_replay` | `live_pipeline` |
| Final Value | `99447.9922` | `99447.9922` |
| Sharpe | `-1.7564` | `-1.7564` |
| Max Drawdown | `-1.8893%` | `-1.8893%` |
| Final Position | `601600` only | `601600` only |

对应证据文件：

1. [data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/session_summary.json](../../../data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/session_summary.json)
2. [data/reports/paper_trading_window_20260202_20260304_bridge_live_anchor_m2_7_20260319/session_summary.json](../../../data/reports/paper_trading_window_20260202_20260304_bridge_live_anchor_m2_7_20260319/session_summary.json)

### 4.2 这说明了什么

1. 从最终净值和风险指标看，W0 live bridge anchor 没有破坏当前 M2.5 frozen baseline 的结果边界。
2. 这说明在当前窗口、当前数据和当前规则下，M2.7 live 运行至少没有把组合最终结果推离现有主基线。
3. 但这不等于“ M2.7 与 M2.5 已被证明完全等价”，因为 benchmark 已经证明两者语义并不相同。

### 4.3 为什么 W0 只能当 bridge，不能当替换证明

W0 本轮仍然只能被解释为 bridge anchor，不能直接升格为新主基线，原因如下：

1. benchmark 最小重验已经证明 M2.7 会改变 `600519` 的 near-threshold 打分分布。
2. bridge anchor 的 `session_summary` 虽然保留了全窗口 `portfolio_values`，但 `daily_event_stats.day_count = 3`，说明该摘要中的执行统计更像续跑增量，不应误读为完整窗口执行总量。
3. 本次运行过程中，尾窗曾观察到 provider fallback 和 `<think>` 包裹 JSON 触发重试；这些是本轮运行观察，不是当前 artifact 内已经结构化落盘的字段，因此不能把 W0 当成完全无污染的纯净样本。

## 5. 当前可执行结论

截至 2026-03-19，最稳妥的判断是：

1. 主基线继续保持为 [data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/session_summary.json](../../../data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/session_summary.json)，不切换主表口径。
2. M2.7 已被证明存在语义漂移，因此后续任何 fresh replay、bridge run、live anchor 都必须单列，不并入现有 M2.5 主表。
3. W0 的价值在于说明“在 live pipeline 下，M2.7 目前没有把窗口最终结果明显打坏”，而不是说明“从此可以把 M2.7 与 M2.5 视作同一口径”。

## 6. 是否进入 W1

在当前状态下，可以进入 W1，但前提要写清楚：

1. W1 的目的应是拿到一份干净的 M2.7 live / replay 样本，而不是复写 M2.5 主基线。
2. W1 产物必须继续单列，并保留明确的 provider / model 指纹。
3. 解释 W1 时必须同时引用本页与 [llm-routing-and-minimax-config-20260319.md](./llm-routing-and-minimax-config-20260319.md)，说明当前自动 fallback 只允许跨 provider，same-provider 不自动降级。

如果 W1 后续没有再出现 provider fallback、非结构化 JSON 重试或统计口径混杂，那么再决定是否把 M2.7 路线提升为新的独立验证分支，而不是直接替换旧分支。
