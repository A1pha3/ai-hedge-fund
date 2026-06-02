# BTST Daily Report Prompts

这份文件只保留可直接复制的 ai-hedge-fund-btst 日常提示词模板（最新规则：**单日期输入 + 严格交易日历推算 next_trade_date + 默认输出目录**）。

## 当前约定（最新规则）

- **只必填 `signal_date`**：已经拿到收盘数据的交易日（信号日）。
- **`next_trade_date` 自动推算**：使用 SSE 交易日历从 `signal_date` 严格推算下一交易日（周五/节假日会跳到下一开市日；`signal_date` 若非开市日会直接报错）。
- **默认输出目录按执行日归档**：
  - 非 scheme_a：`outputs/<next_yyyymm>/<next_yyyymmdd>_from_<signal_yyyymmdd>/`
  - scheme_a：`outputs/<next_yyyymm>/<next_yyyymmdd>_scheme_a_from_<signal_yyyymmdd>/`
- 文档文件名仍以 `signal_date` 为主（便于复盘数据来源），正文内明确写 `next_trade_date`。
- 默认全套文档是核心 `5` 份；如果 `scheme_a` 当前激活，通常再附加 `2` 份 EARLY-WARNING 文档。
- opening watch card / premarket execution card 属于 follow-up 产物，必须与主文档保持一致的 execution contract 口径，并落在同一输出目录。

详细规则见：

- [../../../skills/ai-hedge-fund-btst/使用说明.md](../../../skills/ai-hedge-fund-btst/%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E.md)
- [../../../skills/ai-hedge-fund-btst/references/trigger-examples.md](../../../skills/ai-hedge-fund-btst/references/trigger-examples.md)

## 推荐默认模板（单日期）

日常最推荐这条：只替换 `signal_date`。

```text
使用 ai-hedge-fund-btst skill，基于 YYYY-MM-DD 收盘数据，为下一交易日生成 BTST 全套中文文档，并继续生成 opening watch card 和 premarket execution card。所有 follow-up 文档保持与主文档一致的 execution contract 口径。保存到默认推荐目录；如果方案 A 当前激活，自动输出到 scheme_a 目录。

（可选一致性校验：目标交易日=YYYY-MM-DD）
```

## 常用模板

### 1. 日常全套版（单日期 + 自动目录）

```text
使用 ai-hedge-fund-btst skill，基于 2026-06-01 收盘数据，为下一交易日生成 BTST 全套中文文档。按正式执行层、交集优先复审层、补充复审层、回补机会层输出；如果方案 A 当前激活，同时生成 EARLY-WARNING 补充文档。保存到默认推荐目录。
```

### 2. 盘前跟进版（含两张卡片）

```text
使用 ai-hedge-fund-btst skill，基于 2026-06-01 收盘数据，为下一交易日生成 BTST 全套中文文档，并继续生成 opening watch card 和 premarket execution card。所有 follow-up 文档保持与主文档一致的 execution contract 口径。保存到默认推荐目录。
```

### 3. 双 Profile 对照版

适合你想让 skill 直接给出今天更偏 `conservative` 还是 `aggressive` 的时候。

```text
使用 ai-hedge-fund-btst skill，基于 YYYY-MM-DD 收盘数据，为下一交易日生成 BTST 全套中文文档；如果 conservative 和 aggressive 存在执行分歧，额外生成双 profile 对照和交易前决策卡，并明确今天更偏 conservative 还是 aggressive，以及核心理由来自交集票、only early-runner 或 second-entry 的哪一项。保存到默认推荐目录（或你自定义的 profile_compare 目录）。
```

## 优化复跑模板

适合策略刚调过，想比较优化前后结果是否真的更好。

```text
我下午已经用 ai-hedge-fund-btst skill，基于 YYYY-MM-DD 收盘数据，为下一交易日生成过一版 BTST 全套中文文档，保存到 outputs/<next_yyyymm>/<next_yyyymmdd>_from_<signal_yyyymmdd>-first/。现在我们优化了 btst 策略，请再次基于同一个 signal date 重新生成同一天的 BTST 全套中文文档，保存到 outputs/<next_yyyymm>/<next_yyyymmdd>_from_<signal_yyyymmdd>-second/。然后比较两次的主票、备选层级、机会池、执行顺序、交易前决策卡和最终建议，判断这次优化是否值得保留，并说明差异来自哪些规则、profile 或下游产物变化。
```

## 使用提醒

- 如果你想“强校验” next_trade_date（比如周五收盘怕自己写错），就在提示词里加一行：`目标交易日=YYYY-MM-DD`（仅用于一致性校验，不用于推算）。
- 如果你只写“生成全套文档”，skill 默认更偏主文档流；需要 follow-up cards、双 profile 对照、交易前决策卡时要显式写出。
