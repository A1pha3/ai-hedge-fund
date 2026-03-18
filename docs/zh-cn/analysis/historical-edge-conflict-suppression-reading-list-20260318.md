# 2026-03-18 历史 edge 冲突与抑制样本最小复核读单

## 1. 文档目的

这份读单只服务一个场景：后续如果需要快速确认某个 near-threshold 或 isolated watch 对象为什么已经被归入 conflict/suppression，而不是新的 clean benchmark，最少应该看哪些文件、分别确认什么。

它不新增结论，只把现有高优先级 conflict evidence 压成最低成本入口。

## 2. 最短复核顺序

### 第一步：先确认这组对象已经有统一 conflict 主入口

必读文件：

1. [historical-edge-evidence-inventory-20260318.md](./historical-edge-evidence-inventory-20260318.md)

读完应确认的事实：

1. `600988`、`000426`、`000960`、`300251`、`300775`、`600111`、`300308` 已经进入稳定的 conflict/suppression 覆盖范围。
2. 这组对象的主语义不是 clean watch，而是 `b_positive_c_strong_bearish` 或更广义的 watchlist suppression。
3. 它们不应重新进入 benchmark 候选池。

### 第二步：先看统一解释层，不先翻逐日回放

必读文件：

1. [data/reports/layer_c_edge_tradeoff_20260315.json](../../data/reports/layer_c_edge_tradeoff_20260315.json)
2. [data/reports/watchlist_suppression_analysis_20260315.json](../../data/reports/watchlist_suppression_analysis_20260315.json)

读完应确认的事实：

1. 这组对象的高优先级解释已经稳定落在 Layer C conflict 或 watchlist suppression 上。
2. 如果某个 ticker 已经在这两份 artifacts 里出现，就不应因为 isolated watch 切片重新开专项。
3. `000960` 的复核通常到这一步就够了，不需要优先回到逐日 prepared-plan 截面。

### 第三步：只在需要时回到同一 prepared-plan 截面

必读文件：

1. [data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl](../../data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl)
2. [historical-edge-date-coverage-matrix-20260318.md](./historical-edge-date-coverage-matrix-20260318.md)

读完应确认的事实：

1. `20260303` 是当前最低成本的 prepared-plan conflict 截面。
2. `300775`、`600111`、`000426`、`300308`、`300251` 可以优先在这个统一截面里复核 conflict/avoid 链。
3. 如果只是判断对象是否已经被更高优先级 suppression evidence 覆盖，到这一步就应停止，不再扩展到全窗口盲扫。

## 3. 一页式复核口径

如果只保留一页结论，应该记住下面三条：

1. 这组对象的主语义是 conflict/suppression，不是 clean near-threshold watch。
2. 高优先级主入口是 `layer_c_edge_tradeoff_20260315.json` 和 `watchlist_suppression_analysis_20260315.json`。
3. `20260303` prepared-plan 截面只用于低成本复核统一形态，不用于重开候选资格讨论。

## 4. 当前状态

截至 `2026-03-18`：

1. `600988`、`000426`、`000960`、`300251`、`300775`、`600111`、`300308` 都已经有最低成本 conflict/suppression 复核入口。
2. 这组对象的作用是解释为什么应排除，而不是扩 benchmark。
3. 当前样本库仍然只有三条固定 benchmark。
