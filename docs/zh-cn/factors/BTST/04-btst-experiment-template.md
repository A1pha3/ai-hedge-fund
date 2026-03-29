# BTST 实验记录模板

适用对象：要做 BTST replay、live validation、参数校准和窗口级复盘的研究员、开发者、AI 助手。

用途：

1. 把每轮 BTST 调参与验证沉淀成统一记录。
2. 降低“做了很多实验，但事后说不清楚为什么做、改了什么、结果意味着什么”的风险。
3. 让研究员和 AI 助手可以按同一模板交接。

---

## 模板

### 1. 基本信息

- 实验名称：
- 实验日期：
- 负责人：
- 协作者：
- 仓库版本 / 关键分支：
- 模型提供方：
- 模型名称：
- target mode：
- 评估窗口：
- baseline report / replay 输入：

### 2. 本轮为什么做

当前主假设：

1.
2.

当前主问题分型：

- [ ] Layer B 供给过冷
- [ ] short trade boundary admission 太严
- [ ] short trade target score frontier 太严
- [ ] structural conflict / penalty 过重
- [ ] execution 承接不足

为什么判断为这个分型：

### 3. 本轮只改什么

本轮唯一实验主题：

改动项：

1.

明确不改的项：

1.
2.
3.

### 4. 变体配置

#### 4.1 baseline

- 参数 / profile：
- 关键阈值：
- 数据源：
- 输出目录：

#### 4.2 variant

- 参数 / profile：
- 关键阈值：
- 数据源：
- 输出目录：

### 5. 执行命令

#### 5.1 replay 命令

```bash

```

#### 5.2 live validation 命令

```bash

```

#### 5.3 分析命令

```bash

```

### 6. replay 结果摘要

- replay_input_count：
- decision_mismatch_count：
- stored decision counts：
- replayed decision counts：
- decision transitions：

关键观察：

1.
2.
3.

### 7. 真实窗口结果摘要

- candidate_count：
- selected / near_miss / blocked / rejected：
- next_high_return_mean：
- next_close_return_mean：
- next_high_hit_rate@threshold：
- next_close_positive_rate：

关键观察：

1.
2.
3.

### 8. focused ticker 诊断

| ticker | baseline 决策 | variant 决策 | 主正贡献 | 主负贡献 | 结论 |
| ------ | ------------- | ------------ | -------- | -------- | ---- |
|        |               |              |          |          |      |

### 9. 风险与副作用

本轮已识别副作用：

1.
2.

当前还没验证的风险：

1.
2.

### 10. 本轮结论

三选一：

- A. 保留为下一轮候选
- B. 回滚，不再继续
- C. 升级为默认参数候选

最终选择：

原因：

1.
2.
3.

### 11. 下一轮最合理动作

只写 1 到 2 个动作：

1.
2.

### 12. 关联产物

- 相关 report：
- 相关 selection artifacts：
- 相关 markdown 摘要：
- 相关 json 结果：
- 相关测试：

---

## 最小示例

### 示例 1. 基本信息

- 实验名称：BTST catalyst floor zero live validation
- 实验日期：2026-03-29
- 负责人：research
- 协作者：AI assistant
- 仓库版本 / 关键分支：main
- 模型提供方：MiniMax
- 模型名称：MiniMax-M2.7
- target mode：dual_target
- 评估窗口：2026-03-23 ~ 2026-03-26
- baseline report / replay 输入：paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329

### 示例 2. 本轮为什么做

当前主假设：

1. short trade boundary 的 admission 更可能被 catalyst floor 误伤，而不是被 breakout / volume floor 误伤。
2. 把 `catalyst_freshness_min` 从 `0.12` 放到 `0.00`，可能提升覆盖而不显著损伤前置候选质量。

当前主问题分型：

- [ ] Layer B 供给过冷
- [x] short trade boundary admission 太严
- [ ] short trade target score frontier 太严
- [ ] structural conflict / penalty 过重
- [ ] execution 承接不足

### 示例 3. 本轮只改什么

本轮唯一实验主题：short trade boundary admission 中的 catalyst floor。

改动项：

1. `DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_CATALYST_MIN=0.0`

明确不改的项：

1. 不改 `volume_expansion_quality_min`
2. 不改 target profile 阈值
3. 不改 penalty 权重

### 示例 4. 变体配置

#### 示例 4.1 baseline

- 参数 / profile：default
- 关键阈值：`catalyst_freshness_min=0.12`
- 数据源：live paper trading report
- 输出目录：baseline report dir

#### 示例 4.2 variant

- 参数 / profile：default + catalyst floor zero
- 关键阈值：`catalyst_freshness_min=0.00`
- 数据源：live paper trading report
- 输出目录：variant report dir

### 示例 5. 执行命令

#### 示例 5.1 replay 命令

```bash
python scripts/replay_selection_target_calibration.py <input_or_report_dir>
```

#### 示例 5.2 live validation 命令

```bash
python scripts/run_short_trade_boundary_variant_validation.py \
  --start-date 2026-03-23 \
  --end-date 2026-03-26 \
  --selection-target dual_target \
  --model-provider MiniMax \
  --model-name MiniMax-M2.7 \
  --variant-name catalyst_floor_zero
```

#### 示例 5.3 分析命令

```bash
python scripts/analyze_pre_layer_short_trade_outcomes.py --report-dir <variant_report_dir>
python scripts/analyze_short_trade_boundary_score_failures.py --report-dir <variant_report_dir>
```

### 示例 6. replay 结果摘要

- replay_input_count：按 report 实际值填写
- decision_mismatch_count：按 report 实际值填写
- stored decision counts：按 report 实际值填写
- replayed decision counts：按 report 实际值填写
- decision transitions：按 report 实际值填写

### 示例 7. 真实窗口结果摘要

- candidate_count：24
- selected / near_miss / blocked / rejected：按窗口报告填写
- next_high_return_mean：0.0471
- next_close_return_mean：0.0186
- next_high_hit_rate@threshold：0.75
- next_close_positive_rate：0.7083

### 示例 10. 本轮结论

- 最终选择：A. 保留为下一轮候选

原因：

1. 该 admission 变体已在完整窗口下验证过覆盖与质量。
2. 主问题已转向 score frontier，而不是 admission 本身。
3. 下一轮应继续看 score-fail frontier，而不是再找第二条 admission floor。
