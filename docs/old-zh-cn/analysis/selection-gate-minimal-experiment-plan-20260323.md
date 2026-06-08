# 选股闸门最小实验方案 2026-03-23

## 1. 目标

这份文档只回答一个问题：

- 基于 2026-03-23 之前已经完成的 live / frozen 验证，下一步最小、最可解释、最不容易把系统搞乱的闸门实验应该怎么做？

结论先行：

1. 不建议一上来做大范围规则重构。
2. 已确认：直接用 frozen current_plan replay 覆盖 `DAILY_PIPELINE_FAST_SCORE_THRESHOLD` 或 `DAILY_PIPELINE_WATCHLIST_SCORE_THRESHOLD`，不会重新生成 Layer B / Layer C / watchlist，因此不能把结果直接当成 gate 敏感性结论。
3. 第一轮应先做 selection_artifact margin scan，再对有价值的窗口做 fresh pipeline rerun；目标不是立刻提高收益，而是先回答“候选 scarcity、watchlist 抑制、300724 重复出现”分别对哪一个最小改动最敏感。

## 1.1 2026-03-23 同日修正

当日已实际运行 W1 窗口命令：

```bash
python scripts/run_paper_trading_gate_experiments.py \
  --start-date 2026-02-02 \
  --end-date 2026-03-13 \
  --frozen-plan-source data/reports/paper_trading_window_20260202_20260313_w1_live_m2_7_20260319/daily_events.jsonl \
  --variants baseline,fast_0375,watchlist_019,fast_0375_watchlist_019 \
  --output-root data/reports/gate_experiment_w1_20260202_20260313_20260323
```

得到的四组统计完全相同：

1. `high_pool=50`
2. `watchlist=15`
3. `buy_orders=4`

原因不是“阈值微调完全无效”，而是运行模式为 `frozen_current_plan_replay`，它会直接复用历史 `current_plan`。也就是说：

1. 这次运行只能验证 replay 链路本身没有被 env 覆盖破坏。
2. 它不能验证 post-market gate 是否真的被重新计算。
3. 因此，后续必须把 frozen replay 的用途改成“margin scan + execution parity”，而不是“真实 gate sensitivity replay”。

同一轮 margin scan 已经给出两个更有用的结论：

1. `fast_0375` 在当前 W1 窗口里只会打开 2 个 Layer B 边缘样本：`2026-03-04/300724(score_b=0.3790)` 与 `2026-03-05/600988(score_b=0.3798)`。
2. `watchlist_019` 在当前 W1 窗口里命中的 4 个 `0.19 <= score_final < 0.20` 样本全部仍然是 `decision_avoid`，包括 `601899` 1 次和 `000960` 3 次，因此单独下调 watchlist 阈值不构成有效释放。

2026-03-24 又补做了这 2 个 Layer B 边缘日的 fresh rerun，对 margin scan 进行了真实验证：

1. `2026-03-04` baseline 为 `high_pool=2/watchlist=0/buy_order=0`，`300724(score_b=0.3790)` 仍被挡在 Layer B 外；`fast_0375` 变为 `high_pool=3/watchlist=1/buy_order=1`，`300724` 真实进入 watchlist 且生成买单，`score_final=0.2263`，`bc_conflict=None`。
2. `2026-03-05` baseline 为 `high_pool=1/watchlist=0/buy_order=0`，`600988(score_b=0.3798)` 仍被挡在 Layer B 外；`fast_0375` 变为 `high_pool=2/watchlist=1/buy_order=0`，`600988` 真实进入 watchlist，`score_final=0.2170`，但被执行层 `position_blocked_score` 阻塞。
3. 这说明 `fast_0375` 的作用不是伪增量，而是“窄幅、真实、可解释”的 Layer B 边缘释放；同时它也说明后续瓶颈会立刻转移到 execution blocker，而不是自动转化为更多成交。

2026-03-24 同日继续对 execution blocker 做了第二层验证，并确认方法边界如下：

1. `position_blocked_score` 的根因是 `src/portfolio/position_calculator.py` 中的 `WATCHLIST_MIN_SCORE = 0.225` 硬阈值；本轮已将其改为可由 `PIPELINE_WATCHLIST_MIN_SCORE` 覆盖，默认行为保持不变。
2. 直接调用 `calculate_position()` 已证明：对 `600988 / score_final=0.2170`，默认阈值下返回 `constraint_binding=score, shares=0`；当 `PIPELINE_WATCHLIST_MIN_SCORE=0.21` 时，会转为可生成 `100` 股计划仓位。
3. 但 execution floor 不能用 fresh rerun 直接隔离验证，因为上游 LLM 每次都会重算；也不能用 frozen current_plan replay 直接验证，因为当前 frozen replay 只会复用历史 `buy_orders` 并重放 reentry filter，不会重新执行 `calculate_position()`。
4. 因此，execution score floor 的当前有效证据链应定义为：代码级公式确认 + 定向单元测试 + fresh rerun 样本定位，而不是把 frozen current_plan replay 误用为 execution sizing replay。

## 2. 当前证据如何约束下一步

截至目前，已经有三组关键证据：

### 2.1 长窗口 W1 统计

来自 `data/reports/paper_trading_window_20260202_20260313_w1_selection_artifact_validation_20260323/gating_summary_20260202_20260313.md`：

1. `4800` 个 candidate 中，`4750` 个直接被 Layer B `below_fast_score_threshold` 过滤。
2. 最终只形成 `50` 个 high_pool、`15` 个 watchlist、`4` 个 buy_order。
3. watchlist 阶段的主要原因是 `decision_avoid`，不是单纯排序截断。

这说明：

- 如果要解决“几乎没有候选”的问题，必须先观察 Layer B。
- 但仅仅扩大 Layer B，并不等于最终就会有更多可交易样本。

### 2.2 6 日 live 窗口复盘

来自 `data/reports/paper_trading_window_20260316_20260323_live_m2_7_20260323/threshold_analysis_20260316_20260323.md`：

1. 3 个交易日 `200/200` 候选全部死在 Layer B。
2. `002916` 已通过 Layer B，但被 Layer C 否决。
3. `300724` 连续两次过线，但都只是贴着阈值上方运行。

这说明：

- 当前窗口里的 scarcity 主因仍然偏 Layer B。
- near-miss 的否决则明显偏 Layer C。

### 2.3 300724 单票档案

来自 `data/reports/paper_trading_window_20260316_20260323_live_m2_7_20260323/300724_dossier_20260323.md`：

1. `300724` 在已汇总的两个关键窗口中一共出现 `16` 次痕迹。
2. 其中 `14` 次 selected、`2` 次 rejected、真正进入 buy_order 只有 `2` 次。
3. 未下单的主要原因是 `position_blocked_score`、`position_blocked_single_name`、冷却与重入确认。

这说明：

- 当前系统看到 `300724` 很稳定。
- 但执行层多数时候并不认可它值得继续交易。

所以，下一步实验不能只问“怎么让更多票过线”，还要问“过线后会不会只是把更多边界票送到执行层被继续拒绝”。

## 3. 为什么这轮先做闸门实验，而不是先改执行层

执行层 blocker 的确很多，但从顺序上不应该先动它，原因很直接：

1. 当前更大的问题是候选面太窄。
2. 如果前面没有候选，后面的执行层调得再松，也不会创造新机会。
3. 先把 Layer B / watchlist 的灵敏度做成可比较实验，更容易知道是“前面看不到”，还是“后面不愿接”。

因此，这轮实验应坚持一个约束：

- 只改闸门，不改执行层规则。

## 4. 当前真实开关位置

当前代码中的主要闸门参数是：

1. `src/execution/daily_pipeline.py`
   - `DAILY_PIPELINE_FAST_SCORE_THRESHOLD`，默认 `0.38`
   - `DAILY_PIPELINE_WATCHLIST_SCORE_THRESHOLD`，默认 `0.20`
2. `src/execution/layer_c_aggregator.py`
   - `DAILY_PIPELINE_LAYER_C_BLEND_B_WEIGHT`
   - `DAILY_PIPELINE_LAYER_C_BLEND_C_WEIGHT`
   - `DAILY_PIPELINE_LAYER_C_AVOID_SCORE_C_THRESHOLD`

本轮最小实验只动前两个，不动 Layer C blend，也不动 avoid 阈值。

原因：

1. 这样最容易解释。
2. 与 2026-03-23 当前窗口结论直接对应。
3. 如果连这一级最小实验都看不出方向，再谈更深的 Layer C 调整才有意义。

## 5. 推荐的 4 组最小实验

### 5.1 baseline

不做任何覆盖，作为对照组。

### 5.2 fast_0375

只调整：

- `DAILY_PIPELINE_FAST_SCORE_THRESHOLD = 0.375`

目的：

- 观察 Layer B 稍微放宽后，high_pool 是否从“极度稀缺”改善为“可复核但不过量”。

### 5.3 watchlist_019

只调整：

- `DAILY_PIPELINE_WATCHLIST_SCORE_THRESHOLD = 0.19`

目的：

- 观察当前系统是否存在一批“其实 Layer C 不强烈反对，只是卡在最终 0.20 阈值下方”的边界票。

### 5.4 fast_0375_watchlist_019

同时调整：

- `DAILY_PIPELINE_FAST_SCORE_THRESHOLD = 0.375`
- `DAILY_PIPELINE_WATCHLIST_SCORE_THRESHOLD = 0.19`

目的：

- 观察当 Layer B 与最终 watchlist 同时轻微放宽时，系统是否只会放大 `300724` 这类边界重复票，还是会真正扩展可复核候选面。

## 6. 为什么不是先直接调得更大

当前不建议一上来做下面这些动作：

1. 不建议先把 `0.38` 直接降到 `0.37` 或更低。
2. 不建议先把 watchlist 从 `0.20` 直接降到 `0.18`。
3. 不建议第一轮就同时改 Layer B、Layer C blend、avoid 阈值。

原因：

1. 一次改太多，会让“候选变多”到底来自哪里失去可解释性。
2. 现有证据已经说明 `300724` 这种边界票会稳定重复出现，过激放宽容易把重复噪声放大。
3. 先做最小幅度改动，更容易建立一个干净的前后对照。

## 7. 已新增的执行脚本

为避免每次手工拼环境变量和汇总结果，当前仓库已新增：

- `scripts/run_paper_trading_gate_experiments.py`

这个脚本会：

1. 对 frozen replay 逐个 variant 启动 `scripts/run_paper_trading.py`
2. 为每个 variant 写出独立 output_dir
3. 自动汇总 `selection_artifacts/*/selection_snapshot.json`
4. 生成 `gate_experiment_report.json`
5. 当运行模式是 `frozen_current_plan_replay` 且覆盖了 post-market gate env 时，额外写出 `frozen_gate_noop_warning` 与 `frozen_gate_margin_scan`，明确提醒“这不是有效的 gate replay”，同时给出阈值边缘样本扫描。

默认内置的 variant 就是：

1. `baseline`
2. `fast_0375`
3. `watchlist_019`
4. `fast_0375_watchlist_019`

## 8. 推荐运行方式

第一轮如果只是想知道“当前窗口是否存在值得 rerun 的边缘样本”，可以先跑 frozen replay + margin scan：

```bash
python scripts/run_paper_trading_gate_experiments.py \
  --start-date 2026-02-02 \
  --end-date 2026-03-13 \
  --frozen-plan-source data/reports/paper_trading_window_20260202_20260313_w1_live_m2_7_20260319/daily_events.jsonl \
  --variants baseline,fast_0375,watchlist_019,fast_0375_watchlist_019 \
  --output-root data/reports/paper_trading_gate_experiments_w1_20260323
```

如果只是做脚本烟雾验证，可以先跑单日：

```bash
python scripts/run_paper_trading_gate_experiments.py \
  --start-date 2026-02-05 \
  --end-date 2026-02-05 \
  --frozen-plan-source data/reports/logic_stop_threshold_scan_m0_20/daily_events.jsonl \
  --variants baseline,fast_0375
```

## 9. 第一轮看什么，不看什么

### 9.1 这轮必须看的指标

1. `total_high_pool_count`
2. `total_watchlist_count`
3. `total_buy_order_count`
4. `zero_high_pool_days`
5. `nonzero_high_pool_zero_watchlist_days`
6. `selected_freq_top10`
7. `rejected_freq_top10`
8. `frozen_gate_noop_warning`
9. `frozen_gate_margin_scan`

### 9.2 这轮暂时不要作为第一判断的指标

1. 最终收益率
2. Sharpe
3. 单窗口短期胜率

原因：

- 这轮首先是在做闸门敏感性分析，不是在做最终收益优化定案。

## 10. 实验通过与失败的判定口径

### 10.1 可以继续推进的信号

如果出现以下任一情况，就说明该 variant 值得进入下一轮 fresh rerun 分析：

1. `frozen_gate_margin_scan.fast_threshold_margin.released_count` 明显大于 0，且不是单一重复票反复出现。
2. `frozen_gate_margin_scan.watchlist_threshold_margin.threshold_only_release_count` 大于 0，而不是全部落入 `still_avoid_blocked_examples`。
3. 边缘样本里出现了 `300724` 之外的新候选，并且它们不带稳定的 `bc_conflict=b_positive_c_strong_bearish`。

### 10.2 应该直接降级的信号

如果出现以下情况，该 variant 应视为不适合继续做 fresh rerun：

1. `frozen_gate_noop_warning` 已明确指出当前 replay 只是复用历史 `current_plan`，但 margin scan 又没有给出可用边缘样本。
2. 新增候选主要只是把 `300724` 这类边界票重复放大。
3. 落入新阈值带的样本几乎全部仍然是 `decision_avoid` 或稳定 `bc_conflict=b_positive_c_strong_bearish`。

## 11. 当前推荐的实验顺序

按最稳妥顺序，应当这样推进：

1. 先跑 `baseline` 与 `fast_0375`，用 margin scan 判断 Layer B 是否真的存在边缘释放。
2. 再跑 `watchlist_019`，确认 `0.19..0.20` 这一带究竟是纯阈值 miss，还是本质上仍被 `decision_avoid` 压住。
3. 最后再看 `fast_0375_watchlist_019`，只把它当成“边缘样本 inventory 扩展”，不要当成真实 fresh rerun 结果。

这样能先回答：

1. 候选 scarcity 对 Layer B 微调是否敏感
2. near-miss 是否主要卡在最终 watchlist 阈值
3. 两者一起放宽时，会不会只是把重复边界票放大

## 12. 当前最谨慎的建议

基于 2026-03-23 之前的全部证据，当前最不容易犯错的下一步不是“马上改默认阈值”，而是：

1. 先用新增脚本把上述 4 组 frozen replay 跑成 margin scan，明确哪些窗口里真的存在可疑边缘样本。
2. 先回答候选面是否可能被改善，而不是只放大重复边界票。
3. 当前已经有 fresh rerun 实证支撑 `2026-03-04/300724` 与 `2026-03-05/600988` 两个样本，因此后续应优先围绕 execution blocker 与 Layer C 边缘票治理继续推进，而不是再回到 frozen current_plan replay 做同类 gate 对比。

这一步的价值不在于立刻优化收益，而在于把“下一步该改 Layer B、watchlist，还是该转向重复候选抑制”这件事从感觉判断，变成有边缘样本清单支撑的工程结论。
