# 2026-03-18 统一长窗口 Replay 摘要模板

## 1. 目的

P2-1 的目标是把长窗口 replay 的摘要结构固定下来，减少每次从 `session_summary.json`、`daily_events.jsonl`、`pipeline_timings.jsonl` 手工拼装结论的成本。

这份模板不替代 validation scoreboard，而是把 scoreboard、专项分析和 run 级摘要之间的接口固定下来。后续每个新 replay 至少应产出一份符合本模板结构的摘要文档。

## 2. 模板原则

1. `session_summary.json` 负责 run 元信息和基础绩效。
2. `daily_events.jsonl` 负责 funnel、blocker、ticker 执行摘要与资金利用率补算。
3. `pipeline_timings.jsonl` 负责 runtime 与阶段耗时。
4. benchmark / guardrail 结论不从原始文件自动推断，仍由研究结论层显式判定。
5. 摘要必须同时回答“整体结果如何”和“为什么会这样”，不能只抄 KPI。

## 3. 最小输入集合

每次新 replay 的摘要，最少需要下面三份 artifacts：

1. `session_summary.json`
2. `daily_events.jsonl`
3. `pipeline_timings.jsonl`

如果 run 需要和固定边界做比较，还应补充：

1. 当前有效 benchmark 文档
2. validation scoreboard 的字段定义
3. 如涉及特定机制问题，对应的专项文档入口

## 4. 建议摘要结构

### 4.1 Run Header

固定记录：

1. run 名称
2. 时间窗口
3. `plan_generation.mode`
4. model provider / model name
5. 基线身份：`default baseline`、`legacy comparison`、`experimental variant`、`guardrail probe` 四选一

### 4.2 Headline KPI

优先直接从 `session_summary.json` 读取：

1. `initial_capital`
2. `final_value`
3. `total_return_pct`
4. `sharpe_ratio`
5. `sortino_ratio`
6. `max_drawdown`
7. `max_drawdown_date`
8. `executed_trade_days`
9. `total_executed_orders`

其中：

1. `final_value` 可以直接使用 summary 中最后一个 `Portfolio Value`，也可以按当前 scoreboard 口径复算一次。
2. `total_return_pct` 建议统一使用与 scoreboard 一致的复算口径，避免不同文档里出现多套收益率定义。

### 4.3 Deployment / Funnel / Runtime

这部分不应只看 summary，必须补算：

1. 平均资金利用率
2. 峰值资金利用率
3. 峰值单票权重
4. 平均 `layer_b_count`
5. 平均 `watchlist_count`
6. 平均 `buy_order_count`
7. 主 buy blockers
8. 主 watchlist blockers
9. 平均 `total_day` 耗时
10. 平均 `post_market` 耗时

用途：

1. 把 run 放回 validation scoreboard 的同一比较平面。
2. 避免只凭收益结论忽略“低利用率 + 单票集中”这类结构问题。

### 4.4 Ticker Execution Digest

每份摘要至少要列出窗口内的关键 ticker，建议不超过 3 到 5 只。对每只 ticker 固定记录：

1. 买入次数
2. 卖出次数
3. 首次建仓日期
4. 最后一次退出或期末状态
5. 期末持仓股数
6. 已实现盈亏
7. 最大浮盈或持仓质量信号
8. 一句话角色描述，例如：`edge opportunity`、`static parking position`、`weak re-entry driver`

如果 ticker 根本没进入 watchlist / buy order / executed 层，则不写进这张表，应该在“未能部署的候选”段落统一说明。

### 4.5 Guardrail / Taxonomy Status

这部分保持人工判定，但格式固定：

1. benchmark 是否被守住
2. 当前 run 更接近哪个 taxonomy：`benchmark-stable`、`weak-entry`、`weak-reentry`、`formation jump`、`profitability cliff`、`conflict/suppression dominated`
3. 与默认 baseline 的相对关系：`better_return_but_weaker_guardrail`、`safer_but_lower_exposure`、`legacy_only` 等

### 4.6 Open Questions / Next Step

每份摘要最后只保留 1 到 3 条：

1. 当前 run 留下的主要未决问题
2. 下一步应该进入哪个 backlog 项
3. 是否需要新专项文档，而不是继续扩写当前摘要

## 5. 字段来源映射

| 字段组 | 主要来源 | 自动化级别 | 说明 |
| --- | --- | --- | --- |
| Run Header | `session_summary.json` | `direct` | 可以直接读取 |
| Headline KPI | `session_summary.json` | `direct` / `recompute` | 收益和终值建议复用 scoreboard 口径 |
| Deployment | `daily_events.jsonl` | `derived` | 需要按 `portfolio_snapshot + current_prices` 补算 |
| Funnel Counts | `daily_events.jsonl` | `derived` | 来自 `current_plan.risk_metrics.counts` |
| Blockers | `daily_events.jsonl` | `derived` | 聚合 `funnel_diagnostics.filters.*.reason_counts` |
| Runtime | `pipeline_timings.jsonl` | `derived` | 聚合 `timing_seconds` |
| Ticker Execution Digest | `daily_events.jsonl` + `session_summary.json` | `derived` | 需要按 ticker 汇总交易、期末状态和 realized gains |
| Guardrail Status | benchmark / 专项文档 | `manual` | 保持研究层人工判定 |
| Taxonomy Status | P1-3 taxonomy 文档 | `manual` | 保持研究层人工归类 |

## 6. 标准摘要骨架

下面这份骨架可直接复制为新 replay 摘要文档：

```md
# YYYY-MM-DD <run_name> Replay 摘要

## 1. Run Header

- Source: `<report_dir>`
- Window: `<start_date> .. <end_date>`
- Plan Mode: `<plan_generation.mode>`
- Model: `<provider>/<model_name>`
- Run Identity: `<default baseline|legacy comparison|experimental variant|guardrail probe>`

## 2. Headline KPI

| Metric | Value |
| --- | --- |
| Return | `<...>` |
| Final Value | `<...>` |
| Sharpe | `<...>` |
| Sortino | `<...>` |
| Max Drawdown | `<...>` |
| Max DD Date | `<...>` |
| Trade Days / Orders | `<...>` |

## 3. Deployment / Funnel / Runtime

| Metric | Value |
| --- | --- |
| Avg Invested | `<...>` |
| Peak Invested | `<...>` |
| Peak Single Name | `<...>` |
| Avg Layer B | `<...>` |
| Avg Watchlist | `<...>` |
| Avg Buy Order | `<...>` |
| Main Buy Blockers | `<...>` |
| Main Watch Blockers | `<...>` |
| Avg Total Day Sec | `<...>` |
| Avg Post Market Sec | `<...>` |

## 4. Ticker Execution Digest

| Ticker | Buy / Sell | Final Position | Realized PnL | Max Float Signal | Role |
| --- | --- | --- | --- | --- | --- |
| `<ticker>` | `<...>` | `<...>` | `<...>` | `<...>` | `<...>` |

## 5. Guardrail / Taxonomy Status

1. Benchmark status: `<pass|fail|not_applicable>`
2. Taxonomy tag: `<...>`
3. Relative to baseline: `<...>`

## 6. Direct Conclusion

1. `<整体结果>`
2. `<结构性问题>`
3. `<与既有基线/guardrail 的关系>`

## 7. Open Questions / Next Step

1. `<...>`
2. `<...>`

## 8. Data Sources

1. `session_summary.json`
2. `daily_events.jsonl`
3. `pipeline_timings.jsonl`
4. `<相关 benchmark 或专项文档>`
```

## 7. 当前默认口径下的补充规则

为了避免每次摘要又长回自由格式，当前阶段建议固定三条补充规则：

1. 如果 run 涉及 `300724` re-entry，必须显式写 `Guardrail / Taxonomy Status`，不能只写收益。
2. 如果平均利用率低于 `20%`，必须写出“候选不足”还是“尾部构造不足”的一句归因。
3. 如果窗口内只有 1 到 2 只真实成交 ticker，必须写 Ticker Execution Digest，不能跳过。

## 8. 与现有文档的关系

这份模板与现有产物的关系如下：

1. [validation-scoreboard-20260318.md](./validation-scoreboard-20260318.md) 负责跨 run 比较面板。
2. [capital-deployment-concentration-20260318.md](./capital-deployment-concentration-20260318.md) 负责 deployment / concentration 专项解释。
3. [reentry-quality-review-20260318.md](./reentry-quality-review-20260318.md) 与 [300724-lifecycle-review-20260318.md](./300724-lifecycle-review-20260318.md) 负责 ticker 级行为专项。
4. 新 replay 先按本模板出 run 摘要，再决定是否需要新专项，而不是反过来。

## 9. 当前收口

截至 `2026-03-18`，P2-1 可以先收口为：

1. run 级摘要的标准结构已经固定。
2. `session_summary` 与 scoreboard 的边界已经拆清：summary 管基础绩效，scoreboard 管补算指标与跨 run 比较。
3. 当前阶段不必先写汇总脚本，也能做到半自动生成摘要；若后续 run 数继续增长，再把本模板转成脚本输出即可。
