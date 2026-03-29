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
3. 后续 blocker 与 outcome 脚本是否能直接消费该目录。

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
2. 跑 `analyze_short_trade_boundary_score_failures.py` 与 frontier 版本。
3. 先做 `300383` 的 targeted release。
4. 再看 `600821` / `002015` recurring frontier。
5. 最后用 outcome 脚本验证 release 样本次日质量。

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
