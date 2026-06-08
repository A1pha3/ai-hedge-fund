# 2026-03-18 历史 edge 日期覆盖矩阵

## 1. 文档目的

这份矩阵只回答一个问题：当前历史 edge 样本库里，关键 `trade_date` 应该回看哪个 artifact，以及该日期在样本判定里承担什么语义。

它是对 [historical-edge-evidence-inventory-20260318.md](./historical-edge-evidence-inventory-20260318.md) 的补充，不重复讨论结论，只压缩“日期 -> artifact -> 语义”的读取路径。

## 2. 固定 benchmark 日期矩阵

| trade_date | ticker | 核心 artifact | 语义 |
| --- | --- | --- | --- |
| `20260224` | `600519` | [data/reports/live_replay_600519_20260224_p1.json](../../data/reports/live_replay_600519_20260224_p1.json) | 历史阈值边缘样本，`watch + bc_conflict = null`，是“应当放出”的 benchmark 边界 |
| `20260226` | `600519` | [data/reports/live_replay_600519_20260226_p1.json](../../data/reports/live_replay_600519_20260226_p1.json) | 历史 near-threshold 不过线样本，仍是 `bc_conflict = null`，是“不能被过度放大”的 benchmark 边界 |
| `20260226` | `300724` | [data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl](../../data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl) | 当前长窗口 clean 边缘样本，`watch + bc_conflict = null`，同时受 re-entry 保护约束 |

## 3. 机制样本日期矩阵

### 3.1 603993

| trade_date | 核心 artifact | 语义 |
| --- | --- | --- |
| `20260202` | [data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl) | frozen replay 起点，`603993` 在 current plan 中已经形成 `watch + bc_conflict = null` 的上游形态 |
| `20260203` | [data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl) | 实际买入日，`executed_trades.603993 = 200` |
| `20260204` | [data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl) | 加仓延续日，`executed_trades.603993 = 100`，确认这不是单点噪声 |
| `20260205` | [data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl) | `logic_stop_loss` 触发卖出日，机制链闭合 |

读取顺序：

1. 先看 [data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl) 的 `20260203`、`20260204`、`20260205`。
2. 再回到 [603993-mechanism-supplement-20260318.md](./603993-mechanism-supplement-20260318.md) 看机制解释。

### 3.2 300065

| trade_date | 核心 artifact | 语义 |
| --- | --- | --- |
| `20260223` | [data/reports/paper_trading_window_20260217_20260228/daily_events.jsonl](../../data/reports/paper_trading_window_20260217_20260228/daily_events.jsonl) | 关键窗口起点，`300065` 已进入选中池但最终不是 clean watch 样本 |
| `20260224` | [data/reports/paper_trading_window_20260217_20260228/daily_events.jsonl](../../data/reports/paper_trading_window_20260217_20260228/daily_events.jsonl) | 关键冲突日，`selected_tickers = ["300065"]` 且 watchlist 中为 `decision = avoid`、`bc_conflict = b_positive_c_strong_bearish` |
| `20260225` | [data/reports/paper_trading_window_20260217_20260228/daily_events.jsonl](../../data/reports/paper_trading_window_20260217_20260228/daily_events.jsonl) | 压线窗口尾部，继续表现为 Layer B 不足以稳定放出 |

补充解释：

1. [pipeline-funnel-scan-202602-window-20260312.md](./pipeline-funnel-scan-202602-window-20260312.md) 用来解释为什么这类日期属于 Layer B 压线问题。
2. [300065-mechanism-supplement-20260318.md](./300065-mechanism-supplement-20260318.md) 用来解释为什么它最终不是 benchmark，而是 `Layer B 压线 + Layer C 强 bearish avoid` 机制样本。

### 3.3 688498

| trade_date | 核心 artifact | 语义 |
| --- | --- | --- |
| `20260202` | [data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl) | 仅表现为 `below_fast_score_threshold` 残留，说明早段没有形成 clean watch |
| `20260203` | [data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl) | 仍停留在 fast threshold 下方 |
| `20260204` | [data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl) | `score_b` 接近但仍未过线，属于第三腿缺失前的弱候选残留 |
| `20260205` | [data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl](../../data/reports/paper_trading_20260202_20260205_logic_stop_frozen_replay/daily_events.jsonl) | 可见 `688498` 仍只是 `below_fast_score_threshold`，说明其问题不是单日 Layer C 压制，而是更早的腿部缺失 |

补充解释：

1. [pipeline-funnel-scan-202602-window-20260312.md](./pipeline-funnel-scan-202602-window-20260312.md) 与 [688498-mechanism-supplement-20260318.md](./688498-mechanism-supplement-20260318.md) 一起使用，才能完整说明“第三条腿缺失 + 中性稀释”。

## 4. 冲突与抑制样本日期矩阵

这组对象不用单独追每个 ticker 的全窗口日期，优先回看同一个 prepared-plan 截面即可。

| prepared_plan date | artifact | 关键对象 | 语义 |
| --- | --- | --- | --- |
| `20260303` | [data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl](../../data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl) | `300775`、`600111`、`000426`、`300308`、`300251` | 同一截面里能直接看到 conflict/avoid 链，适合作为 suppression 主入口 |

补充主入口：

1. [data/reports/layer_c_edge_tradeoff_20260315.json](../../data/reports/layer_c_edge_tradeoff_20260315.json)
2. [data/reports/watchlist_suppression_analysis_20260315.json](../../data/reports/watchlist_suppression_analysis_20260315.json)

这两份文件承担的是“统一解释”，不是“逐日回放”。如果只是要判断对象是否已被更高优先级 conflict evidence 覆盖，先看这两份即可。

## 5. 低优先级观察对象日期矩阵

### 5.1 601600

| trade_date | 核心 artifact | 语义 |
| --- | --- | --- |
| `20260202` | [data/reports/paper_trading_window_20260202_20260303_exit_fix_cooldown5/daily_events.jsonl](../../data/reports/paper_trading_window_20260202_20260303_exit_fix_cooldown5/daily_events.jsonl) | 特定 exit-fix 实验里出现高分 watch 形态 |
| `20260203` | [data/reports/paper_trading_window_20260202_20260303_exit_fix_cooldown5/daily_events.jsonl](../../data/reports/paper_trading_window_20260202_20260303_exit_fix_cooldown5/daily_events.jsonl) | 延续高分或截断样本形态 |
| `20260303` | [data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl](../../data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl) | 仍以持仓残留出现，不构成新的 clean edge 证据 |
| baseline 视角 | [data/reports/rule_variant_backtests/baseline.timings.jsonl](../../data/reports/rule_variant_backtests/baseline.timings.jsonl) | 常退回 `below_fast_score_threshold + neutral` |

结论：

1. 601600 的问题不是“还没补足日期证据”，而是跨 artifact 语义不稳定。
2. 所以它保留观察位即可，不进入补证池。

## 6. 最短读取路径

如果后续只是为了快速判断某个日期是否已经被库存覆盖，建议按下面顺序：

1. benchmark 日期先查本页第 2 节。
2. 603993、300065、688498 先查本页第 3 节。
3. conflict/suppression 先查本页第 4 节的 `20260303` prepared-plan 截面。
4. 只有当日期不在这份矩阵里，才需要回到全量 reports 做新扫描。

## 7. 当前状态

截至 `2026-03-18`：

1. 三条 benchmark 的关键日期都已经有稳定一手入口。
2. 603993、300065、688498 的关键日期也已经能直接落到少数核心 artifacts 上。
3. conflict/suppression 样本已有统一 prepared-plan 截面可回看。
4. 当前缺的不是旧对象的日期入口，而是新的 clean near-threshold non-conflict 日期样本。