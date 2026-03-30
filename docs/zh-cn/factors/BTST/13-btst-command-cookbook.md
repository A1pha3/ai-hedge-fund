# BTST 命令作战手册

适用对象：要亲手运行 BTST replay、live validation、frontier 分析和窗口复盘的研究员、开发者、AI 助手。

这份文档解决的问题：把当前 BTST 最常用的命令、适用场景、先后顺序和结果解读整理成一份可直接执行的命令手册，减少“知道脚本名字，但不知道先跑哪个”的摩擦。

建议搭配阅读：

1. [02-btst-tuning-playbook.md](./02-btst-tuning-playbook.md)
2. [04-btst-experiment-template.md](./04-btst-experiment-template.md)
3. [09-btst-variant-acceptance-checklist.md](./09-btst-variant-acceptance-checklist.md)
4. [10-btst-artifact-reading-manual.md](./10-btst-artifact-reading-manual.md)
5. [11-btst-optimization-decision-tree.md](./11-btst-optimization-decision-tree.md)

---

## 1. 先讲结论：BTST 命令只分 5 类

当前 BTST 最常用的命令可以压缩成 5 类：

1. 跑真实窗口。
2. 重放 selection target。
3. 做 admission / boundary 分析。
4. 做 score frontier / structural rescue 分析。
5. 做次日表现与对照输出。

如果顺序打乱，最容易出现的问题是：先跑了很多 frontier，但其实你连当前主失败簇都没确认。

---

## 2. 运行前约定

### 2.1 默认工作目录

下面所有命令默认都在仓库根目录执行。

### 2.2 推荐 Python 调用方式

优先使用当前仓库虚拟环境：

```bash
./.venv/bin/python <script>
```

如果当前环境已经由任务或脚本统一管理，也可以沿用已有调用方式，但不要混用多个 Python 解释器。

### 2.3 输出目录命名建议

建议把输出目录统一带上：

1. 窗口
2. provider / model
3. 变体名
4. 日期

例如：

```text
data/reports/paper_trading_window_20260323_20260326_live_m2_7_dual_target_catalyst_floor_zero_validation_20260329
```

---

## 3. 第 1 类：跑真实窗口

### 3.1 默认 live paper trading

适用场景：

1. 你要验证当前 baseline。
2. 你要得到真实窗口 artifacts。

命令模板：

```bash
./.venv/bin/python scripts/run_paper_trading.py \
  --start-date 2026-03-23 \
  --end-date 2026-03-26 \
  --selection-target dual_target \
  --model-provider MiniMax \
  --model-name MiniMax-M2.7 \
  --output-dir data/reports/<your_report_dir>
```

你要看什么：

1. 是否成功生成 `selection_artifacts`。
2. `session_summary.json` 和 `daily_events.jsonl` 是否齐全。
3. `short_trade_only` 或 `dual_target` 运行后，目录下是否自动生成 `btst_next_day_trade_brief_latest.{json,md}` 与 `btst_premarket_execution_card_latest.{json,md}`，且 brief/card 中是否已经带出主票、near-miss 与自动机会池。
4. 后续 blocker 与 outcome 脚本是否能直接消费该目录。

### 3.2 admission 变体 live validation

适用场景：

1. 你要验证某条 boundary floor 放松是否成立。
2. 当前最典型的是 catalyst-only 变体。

命令模板：

```bash
DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_CATALYST_MIN=0.0 \
./.venv/bin/python scripts/run_paper_trading.py \
  --start-date 2026-03-23 \
  --end-date 2026-03-26 \
  --selection-target dual_target \
  --model-provider MiniMax \
  --model-name MiniMax-M2.7 \
  --output-dir data/reports/<variant_report_dir>
```

你要看什么：

1. `short_trade_boundary` 候选是否变多。
2. 旧 `layer_b_boundary` score-fail 是否仍保持为 0。
3. 新增样本的次日表现是否仍可接受。

---

## 4. 第 2 类：重放 selection target

### 4.1 通用 replay 校准

适用场景：

1. 你要验证 stored decision 与 replayed decision 是否一致。
2. 你要做 threshold、penalty、candidate-entry 试验。

命令模板：

```bash
./.venv/bin/python scripts/replay_selection_target_calibration.py \
  --input data/reports/<report_or_snapshot_or_replay_input_path>
```

常见扩展参数：

1. `--select-threshold`
2. `--near-miss-threshold`
3. `--avoid-penalty-grid`
4. `--stale-score-penalty-grid`
5. `--extension-score-penalty-grid`
6. `--breakout-freshness-max-grid`
7. `--volume-expansion-quality-max-grid`
8. `--catalyst-freshness-max-grid`
9. `--trend-acceleration-max-grid`
10. `--close-strength-max-grid`

你要看什么：

1. `decision_mismatch_count`
2. 哪些 ticker 发生变化。
3. 变化是 threshold-only，还是必须联动其他机制。

---

## 5. 第 3 类：admission / boundary 分析

### 5.1 看 boundary 候选为什么被过滤

适用场景：

1. 你怀疑 admission 太严。
2. 你想知道样本主要死在哪条 floor。

命令模板：

```bash
./.venv/bin/python scripts/analyze_short_trade_boundary_filtered_candidates.py \
  --report-dir data/reports/<report_dir>
```

你要看什么：

1. `filtered_reason_counts`
2. 是否高度集中在某个单项 floor。
3. 边缘候选是否属于高质量样本簇。

### 5.2 看 admission 放松变体是否值得继续

适用场景：

1. 你已经锁定某条 floor。
2. 你要比较 baseline 和一组 coverage variants。

命令模板：

```bash
./.venv/bin/python scripts/analyze_short_trade_boundary_coverage_variants.py \
  --report-dir data/reports/<report_dir> \
  --output-json data/reports/<coverage_variants>.json \
  --output-md data/reports/<coverage_variants>.md
```

你要看什么：

1. 每条变体新增了几个样本。
2. 是不是只释放边缘高质量样本。
3. 是否应进入 live validation。

### 5.3 跑 admission 变体的统一验证脚本

适用场景：

1. 你要对一条 boundary 变体做完整窗口验证。
2. 你不想手工拼多个步骤。

命令模板：

```bash
./.venv/bin/python scripts/run_short_trade_boundary_variant_validation.py \
  --start-date 2026-03-23 \
  --end-date 2026-03-26 \
  --selection-target dual_target \
  --model-provider MiniMax \
  --model-name MiniMax-M2.7 \
  --variant-name catalyst_floor_zero
```

---

## 6. 第 4 类：score frontier / structural rescue 分析

### 6.1 确认当前最大失败簇

命令模板：

```bash
./.venv/bin/python scripts/analyze_short_trade_blockers.py \
  --report-dir data/reports/<report_dir>
```

优先回答：

1. 当前主失败簇是 `layer_b_boundary`、`short_trade_boundary_score_fail`，还是 `blocked`。
2. 当前下一轮到底该进哪条主线。

### 6.2 分析 `short_trade_boundary` score fail

命令模板：

```bash
./.venv/bin/python scripts/analyze_short_trade_boundary_score_failures.py \
  --report-dir data/reports/<report_dir>

./.venv/bin/python scripts/analyze_short_trade_boundary_score_failures_frontier.py \
  --report-dir data/reports/<report_dir>
```

优先回答：

1. 哪些 ticker 属于 threshold-only 释放。
2. 哪些必须联动 stale / extension penalty。

### 6.3 做 targeted short-trade release

适用场景：

1. 你已经锁定单票，例如 `300383`。
2. 你想验证 release 是否低污染。

命令模板：

```bash
./.venv/bin/python scripts/analyze_targeted_short_trade_boundary_release.py \
  --report-dir data/reports/<report_dir> \
  --target-case 2026-03-26:300383
```

优先回答：

1. 目标 ticker 是否如预期变化。
2. 非目标样本是否完全不动。

### 6.4 做 recurring frontier 分析

适用场景：

1. 你想从单票走向 recurring ticker。
2. 你要判断 `600821`、`002015` 这类样本是不是局部 baseline。

命令模板：

```bash
./.venv/bin/python scripts/analyze_short_trade_boundary_recurring_frontier_cases.py \
  --report-dir data/reports/<report_dir>
```

以及：

```bash
./.venv/bin/python scripts/analyze_recurring_frontier_ticker_release.py \
  --report-dir data/reports/<report_dir> \
  --ticker 600821
```

如果要把 recurring frontier 候选正式收口成 shadow runbook，并明确它们是否还缺第二个独立窗口，可以继续跑：

```bash
./.venv/bin/python scripts/analyze_recurring_frontier_transition_candidates.py \
  --recurring-frontier-report data/reports/short_trade_boundary_recurring_frontier_cases_catalyst_floor_zero_<date>.json \
  --role-history-report-root-dirs data/reports \
  --report-name-contains paper_trading_window \
  --output-json data/reports/recurring_frontier_transition_candidates_all_windows_<date>.json \
  --output-md data/reports/recurring_frontier_transition_candidates_all_windows_<date>.md

./.venv/bin/python scripts/analyze_btst_recurring_shadow_runbook.py \
  --candidate-report data/reports/multi_window_short_trade_role_candidates_<date>.json \
  --recurring-transition-report data/reports/recurring_frontier_transition_candidates_all_windows_<date>.json \
  --output-json data/reports/p6_recurring_shadow_runbook_<date>.json \
  --output-md data/reports/p6_recurring_shadow_runbook_<date>.md
```

优先回答：

1. `002015`、`600821` 是否仍然都只是 `emergent_local_baseline`。
2. recurring shadow lane 当前是 `await_new_close_candidate_window` / `await_new_intraday_control_window`，还是已经具备跨窗口验证资格。
3. 下一次什么时候可以把这条 lane 回接进 `p5_btst_rollout_governance_board` 做升级评审。

### 6.5 分析 structural conflict rescue

适用场景：

1. 你面对的是 `blocked` 样本，而不是 score fail。
2. 当前最典型对象是 `300724`。

命令模板：

```bash
./.venv/bin/python scripts/analyze_structural_conflict_rescue_window.py \
  --report-dir data/reports/<report_dir>

./.venv/bin/python scripts/analyze_targeted_structural_conflict_release.py \
  --report-dir data/reports/<report_dir> \
  --target-case 2026-03-25:300724
```

---

## 7. 第 5 类：次日表现与对照输出

### 7.1 看前置候选次日质量

命令模板：

```bash
./.venv/bin/python scripts/analyze_pre_layer_short_trade_outcomes.py \
  --report-dir data/reports/<report_dir>
```

如果只看定向 ticker：

```bash
./.venv/bin/python scripts/analyze_pre_layer_short_trade_outcomes.py \
  --report-dir data/reports/<report_dir> \
  --tickers 300383
```

优先看：

1. `next_high_return_mean`
2. `next_close_return_mean`
3. `next_high_hit_rate@threshold`
4. `next_close_positive_rate`

### 7.2 看 recurring / targeted release 的结果对照

适用场景：

1. 你要把 frontier 结论和真实次日表现合在一起看。

命令模板：

```bash
./.venv/bin/python scripts/analyze_targeted_short_trade_boundary_release_outcomes.py \
  --report-dir data/reports/<report_dir> \
  --target-case 2026-03-26:300383
```

或：

```bash
./.venv/bin/python scripts/analyze_recurring_frontier_ticker_release_outcomes.py \
  --report-dir data/reports/<report_dir> \
  --ticker 600821
```

### 7.3 生成次日执行简报

适用场景：

1. 你已经跑完某个交易日的 live 或 replay report。
2. 你要把 `selected`、`near_miss`、自动机会池和 research 侧股票明确拆开，给出次日可执行清单。

命令模板：

```bash
./.venv/bin/python scripts/generate_btst_next_day_trade_brief.py \
  data/reports/<report_dir> \
  --trade-date 2026-03-27 \
  --next-trade-date 2026-03-30 \
  --output-dir data/reports
```

优先回答：

1. 主入场票是哪只 `selected`。
2. 哪些只是 `near_miss`，只能做盘中跟踪。
3. 哪些 `rejected` 但结构未坏的股票应进入自动机会池，等待盘中强度确认后再升级。
4. 哪些 research 侧 `selected` 股票不应误当成 short-trade 执行名单。

补充说明：

1. 如果你直接跑 `scripts/run_paper_trading.py --selection-target short_trade_only|dual_target`，上述 brief 会自动落在 report 目录中，无需手工再跑一次。

### 7.4 生成盘前执行卡

适用场景：

1. 你已经有了 BTST brief，想把它进一步压缩成盘前动作卡。
2. 你需要把 `selected`、`near_miss`、机会池、research-only exclusion 明确分层，避免盘前误读。

命令模板：

```bash
./.venv/bin/python scripts/generate_btst_premarket_execution_card.py \
  data/reports/<report_dir> \
  --trade-date 2026-03-27 \
  --next-trade-date 2026-03-30 \
  --output-dir data/reports
```

优先回答：

1. 主执行票是谁，以及它需要什么盘中确认。
2. 哪些票只允许 watch-only。
3. 哪些 research-only 股票必须明确写进 non-trade 区域。

### 7.5 为历史 report 回填 latest brief 与执行卡

适用场景：

1. 你已经有旧的 report 目录，但它是在自动落盘逻辑上线前生成的。
2. 你希望把历史 report 也补齐 `latest` 版 brief 和 execution card，并把路径回写进 `session_summary.json`。

命令模板：

```bash
./.venv/bin/python scripts/backfill_btst_followup_artifacts.py \
  data/reports/<report_dir>
```

如果要从报告根目录批量扫描：

```bash
./.venv/bin/python scripts/backfill_btst_followup_artifacts.py \
  data/reports \
  --report-name-contains paper_trading_window_
```

优先回答：

1. 历史 report 是否已经补齐 `btst_next_day_trade_brief_latest.{json,md}`。
2. 历史 report 是否已经补齐 `btst_premarket_execution_card_latest.{json,md}`。
3. `session_summary.json` 的 `btst_followup` 与 `artifacts` 区域是否已经能稳定引用这些路径。

### 7.6 做闭环微窗口回归对照

适用场景：

1. 你要把 closed-cycle baseline、已验证 admission 变体和 forward-only 样本放进同一套 BTST 框架里比较。
2. 你要明确当前问题到底是 `tradeable surface` 为空，还是 actionable 已经出现但仍有大量 false negative。
3. 你需要给周会或路线文提供一份统一的回归结论，而不是分别引用 blocker、brief、pre-Layer C outcome。

命令模板：

```bash
./.venv/bin/python scripts/analyze_btst_micro_window_regression.py \
  --baseline-report-dir data/reports/paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329 \
  --variant-report catalyst_floor_zero=data/reports/paper_trading_window_20260323_20260326_live_m2_7_dual_target_catalyst_floor_zero_validation_20260329 \
  --forward-report short_trade_20260327=data/reports/paper_trading_20260327_20260327_live_m2_7_short_trade_only_20260329 \
  --output-json data/reports/btst_micro_window_regression_20260330.json \
  --output-md data/reports/btst_micro_window_regression_20260330.md
```

### 7.7 做 profile frontier 闭环比较

适用场景：

1. 你已经确认 admission baseline 不应再盲目放宽，但想验证“只调 short-trade profile 语义”能不能把窗口从 0 actionable surface 推起来。
2. 你要把 `default`、`staged_breakout`、`aggressive`、`conservative` 放到同一个 closed-cycle BTST outcome 面上比较。
3. 你要回答“profile-only 变体是否已经足以形成 closed-cycle actionable surface，还是仍应回到 score construction / candidate entry 主线”。

命令模板：

```bash
./.venv/bin/python scripts/analyze_btst_profile_frontier.py \
  data/reports/paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329 \
  --baseline-profile default \
  --profile staged_breakout \
  --profile aggressive \
  --profile conservative \
  --output-json data/reports/btst_profile_frontier_20260330.json \
  --output-md data/reports/btst_profile_frontier_20260330.md
```

优先回答：

1. 哪个 profile 真的新增了 closed-cycle actionable surface。
2. profile-only 变体是否通过了 baseline false negative proxy 派生出的 guardrails。
3. 如果所有 profile 都还是 0 actionable，是否可以正式收敛到“下一步不再优先调 profile，而是回到 score frontier / candidate entry”。

优先回答：

1. baseline 的 `tradeable surface` 是否仍为 0，以及 `false_negative_proxy_summary` 还有多大。
2. 变体是否真的新增了 closed-cycle actionable 样本，而不只是把样本从 `rejected` 挪到 `near_miss`。
3. 新增 actionable 的 `next_high_hit_rate@2%`、`next_close_positive_rate`、`t_plus_2_close_positive_rate` 是否过 guardrail。
4. forward-only 样本是不是仍停留在 `t1_only`，如果是，就不得直接写成默认升级依据。

补充说明：

1. 这条脚本的定位不是替代 `analyze_short_trade_blockers.py` 或 `analyze_pre_layer_short_trade_outcomes.py`，而是把它们压成同一份 researcher-facing 回归摘要。
2. 当前 2026-03-30 的实跑结果已经落在 `data/reports/btst_micro_window_regression_20260330.{json,md}`，可直接用于引用 0323-0326 closed-cycle baseline 与 `catalyst_floor_zero` 的对照结论。

### 7.8 做 score construction frontier 闭环比较

适用场景：

1. 你已经验证过 admission baseline 和 profile-only 变体都没有把窗口从 0 actionable 推起来。
2. 你要确认“只调正向 score weight 分配”是否真能形成 closed-cycle actionable surface。
3. 你要把 `prepared_breakout_balance`、`catalyst_volume_balance`、`trend_alignment_balance` 放到同一个 outcome 面上比较。

命令模板：

```bash
./.venv/bin/python scripts/analyze_btst_score_construction_frontier.py \
  data/reports/paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329 \
  --baseline-profile default \
  --output-json data/reports/btst_score_construction_frontier_20260330.json \
  --output-md data/reports/btst_score_construction_frontier_20260330.md
```

优先回答：

1. 哪个正向 weight 变体真的新增了 closed-cycle actionable surface。
2. 如果所有 score 变体都仍是 0 actionable，是否可以正式把 score-only tuning 从主线里降级。
3. 这些 weight 变体有没有改变 baseline false negative proxy 的规模或质量。

补充说明：

1. 当前 2026-03-30 的实跑结果已经落在 `data/reports/btst_score_construction_frontier_20260330.{json,md}`。
2. 这份结果若依旧是全 0 actionable，就说明当前问题不能再理解成“只要重配正向分数权重就能推起 surface”。

### 7.9 做 candidate entry frontier 闭环比较

适用场景：

1. 你已经确认 score-only tuning 仍没有形成 actionable surface。
2. 你要验证 selective candidate-entry 语义，看看能不能过滤掉 300502 这类弱结构 watchlist_avoid 样本，同时保住 300394 这类 preserve 样本。
3. 你要把 `weak_structure_triplet`、`semantic_pair_300502`、`volume_only_20260326` 放到同一套 filtered-cohort outcome 面上比较。

命令模板：

```bash
./.venv/bin/python scripts/analyze_btst_candidate_entry_frontier.py \
  data/reports/paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329 \
  --focus-ticker 300502 \
  --preserve-ticker 300394 \
  --output-json data/reports/btst_candidate_entry_frontier_20260330.json \
  --output-md data/reports/btst_candidate_entry_frontier_20260330.md
```

优先回答：

1. 哪条 candidate-entry 规则能过滤 focus ticker，而不误伤 preserve ticker。
2. 被过滤 cohort 的 `next_high_hit_rate@2%`、`next_close_positive_rate` 是否显著弱于 baseline false negative pool。
3. 如果多条规则命中同一弱样本，应优先相信哪条 evidence tier 更高的规则。

补充说明：

1. 当前 2026-03-30 的实跑结果已经落在 `data/reports/btst_candidate_entry_frontier_20260330.{json,md}`。
2. 当前窗口里 `weak_structure_triplet`、`semantic_pair_300502`、`volume_only_20260326` 都命中了同一个 300502 弱样本，但默认应优先 `weak_structure_triplet`，因为它是 window-verified selective rule，而不是 single-day hypothesis。
3. 如果要把这条规则接回 replay calibration 主链路，直接复用 `exclude_watchlist_avoid_weak_structure_entries` 这个 structural variant 即可，不需要再造一条新的命名规则。

### 7.10 做 candidate entry 多窗口稳定性扫描

适用场景：

1. 你已经在当前窗口确认 `weak_structure_triplet` 是最强 candidate-entry selective rule。
2. 你要确认这条规则是不是只在一个窗口键里反复命中，还是已经具备跨窗口稳定性。
3. 你要先判断能不能进入 shadow rollout review，再决定是否值得做默认升级讨论。

命令模板：

```bash
./.venv/bin/python scripts/analyze_btst_candidate_entry_window_scan.py \
  --report-root-dirs data/reports \
  --report-name-contains paper_trading_window \
  --focus-tickers 300502 \
  --preserve-tickers 300394 \
  --output-json data/reports/btst_candidate_entry_window_scan_20260330.json \
  --output-md data/reports/btst_candidate_entry_window_scan_20260330.md
```

优先回答：

1. 弱结构规则到底命中了多少份 report，以及它们是否属于多个独立 `window_key`。
2. `preserve_misfire_report_count` 是否仍然保持为 0。
3. 当前结论应该是 `research_only`、`shadow_only_until_second_window`，还是已经能进入 `shadow_rollout_review_ready`。

补充说明：

1. 当前 2026-03-30 的实跑结果已经落在 `data/reports/btst_candidate_entry_window_scan_20260330.{json,md}`。
2. 真实结果扫描了 14 份 `paper_trading_window` 报告，其中只有 3 份报告过滤了 `300502`，且都落在同一个 `window_key=20260323_20260326`，所以当前结论只能是 `shadow_only_until_second_window`。
3. 由于 `preserve_misfire_report_count=0`，这条规则可以继续保留为 shadow candidate-entry 旁路，但不能升级为默认 admission 行为。

### 7.11 生成 candidate entry rollout governance 板

适用场景：

1. 你已经有 current-window candidate-entry frontier 结果。
2. 你已经用 structural variant 主链回放验证过 `exclude_watchlist_avoid_weak_structure_entries`。
3. 你需要把单窗 frontier、多窗扫描和 score frontier 零结果收口成一个明确的治理结论。

命令模板：

```bash
./.venv/bin/python scripts/analyze_btst_candidate_entry_rollout_governance.py \
  --frontier-report data/reports/btst_candidate_entry_frontier_20260330.json \
  --structural-validation-report data/reports/selection_target_structural_variants_candidate_entry_current_window_20260330.json \
  --window-scan-report data/reports/btst_candidate_entry_window_scan_20260330.json \
  --score-frontier-report data/reports/btst_score_construction_frontier_20260330.json \
  --output-json data/reports/p9_candidate_entry_rollout_governance_20260330.json \
  --output-md data/reports/p9_candidate_entry_rollout_governance_20260330.md
```

优先回答：

1. 当前 `candidate_entry_rule` 应该固定成哪条语义，以及对应哪条 structural variant。
2. 当前 lane status 是否只允许 `shadow_only_until_second_window`。
3. 为什么现在不能把 candidate-entry 规则误写成默认升级依据。

补充说明：

1. 当前 2026-03-30 的实跑结果已经落在 `data/reports/p9_candidate_entry_rollout_governance_20260330.{json,md}`。
2. 当前治理结论非常明确：`weak_structure_triplet` 只能以 `exclude_watchlist_avoid_weak_structure_entries` 的形式进入 shadow-only lane，`default_upgrade_status=blocked_by_single_window_candidate_entry_signal`。
3. `semantic_pair_300502` 与 `volume_only_20260326` 继续保留为研究参考，不进入 rollout 主链。

---

## 8. 两套推荐命令顺序

### 8.1 如果你现在要做 admission 扩覆盖

推荐顺序：

1. 跑 baseline report 或确认已有 report。
2. 跑 `analyze_short_trade_boundary_filtered_candidates.py`。
3. 跑 `analyze_short_trade_boundary_coverage_variants.py`。
4. 选单条 floor 进入 `run_short_trade_boundary_variant_validation.py`。
5. 用 `analyze_pre_layer_short_trade_outcomes.py` 验证新增样本质量。

### 8.2 如果你现在要做 score frontier 精修

推荐顺序：

1. 跑 `analyze_short_trade_blockers.py`。
2. 跑 `analyze_short_trade_boundary_score_failures.py` 与 frontier 版本，确认 score fail 主簇。
3. 跑 `analyze_btst_score_construction_frontier.py`，验证正向 weight 微调是否真能形成 closed-cycle actionable surface。
4. 如果 score frontier 仍然全是 0 actionable，再跑 `analyze_btst_candidate_entry_frontier.py`，验证 selective weak-structure 过滤能否清理 300502 类样本而不误伤 300394。
5. 跑 `analyze_btst_candidate_entry_window_scan.py`，确认这条 selective 规则是否已经跨多个独立 `window_key` 命中。
6. 跑 `analyze_btst_candidate_entry_rollout_governance.py`，把 frontier、多窗口扫描和主链验证收口成 lane status。
7. 再看 `300383` 的 targeted release 与 `600821` / `002015` recurring frontier。
8. 最后用 outcome 脚本验证 release 样本次日质量。

---

## 9. 最容易踩的 6 个坑

1. 一上来就调阈值，而没先确认主失败簇。
2. 把 `blocked` 和 `rejected` 样本混成一个集合分析。
3. admission 放松时只看样本数，不看 `next_close_return_mean`。
4. 拿旧 `layer_b_boundary` 历史窗口直接否定新 `short_trade_boundary` builder。
5. 把 `300724`、`300394`、`300502` 当成同一类样本一起救。
6. frontier 显示能救，就立刻想升级默认，而不先看污染面和真实次日表现。

---

## 10. 一句话总结

BTST 命令最重要的不是多，而是顺序。先确认主失败簇，再跑对应分析，再做定向 release，最后才看是否升级默认。顺序对了，命令才真正有用。
