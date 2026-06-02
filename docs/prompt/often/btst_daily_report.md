# BTST Daily Report Prompts

这份文件只保留可直接复制的 ai-hedge-fund-btst 日常提示词模板。

## 当前约定

- `signal date` 指已经拿到收盘数据的交易日。
- `next trade date` 指要执行次日计划的交易日。
- 文档文件名使用 `signal date`，正文内明确写 `next trade date`。
- 默认全套文档是核心 `5` 份；如果 `scheme_a` 当前激活，通常再附加 `2` 份 EARLY-WARNING 文档。
- 如果希望生成 `conservative / aggressive` 对照和交易前决策卡，要在提示词里显式写出。
- 如果希望继续生成 opening watch card 和 premarket execution card，也要在提示词里显式写出。

详细规则见：

- [../../../skills/ai-hedge-fund-btst/使用说明.md](../../../skills/ai-hedge-fund-btst/%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E.md)
- [../../../skills/ai-hedge-fund-btst/references/trigger-examples.md](../../../skills/ai-hedge-fund-btst/references/trigger-examples.md)

## 推荐默认模板

这条最适合日常直接复用，只需要替换日期和目录。

```text
使用 ai-hedge-fund-btst skill，基于 YYYY-MM-DD 收盘数据，为 YYYY-MM-DD 生成 BTST 全套中文文档。按正式执行层、交集优先复审层、补充复审层、回补机会层输出；如果方案 A 当前激活，同时生成 EARLY-WARNING 补充文档。保存到 outputs/YYYYMM/YYYYMMDD_scheme_a/；如果当前不在 scheme_a，则保存到 outputs/YYYYMM/YYYYMMDD/。
```

## 目标交易日目录兼容模板

如果你仍然想按目标交易日存到 `outputs/YYYYMM/YYYYMMDD/`，建议补上“文件名按 signal date 生成”这一句，避免口径混淆。

```text
使用 ai-hedge-fund-btst skill，基于 YYYY-MM-DD 收盘数据，为 YYYY-MM-DD 生成 BTST 全套中文文档，保存到 outputs/YYYYMM/YYYYMMDD/。文件名按 signal date 生成，文档内明确 next trade date。
```

## 常用模板

### 1. 日常全套版

```text
使用 ai-hedge-fund-btst skill，基于 2026-05-29 收盘数据，为 2026-06-01 生成 BTST 全套中文文档。按正式执行层、交集优先复审层、补充复审层、回补机会层输出；如果方案 A 当前激活，同时生成 EARLY-WARNING 补充文档。保存到 outputs/202605/20260529_scheme_a/；如果当前不在 scheme_a，则保存到 outputs/202605/20260529/。
```

### 2. 双 Profile 对照版

适合你想让 skill 直接给出今天更偏 `conservative` 还是 `aggressive` 的时候。

```text
使用 ai-hedge-fund-btst skill，基于 2026-05-29 收盘数据，为 2026-06-01 生成 BTST 全套中文文档；如果 conservative 和 aggressive 存在执行分歧，额外生成双 profile 对照和交易前决策卡，并明确今天更偏 conservative 还是 aggressive，以及核心理由来自交集票、only early-runner 或 second-entry 的哪一项。保存到 outputs/202605/20260529_profile_compare/。
```

### 3. 盘前跟进版

适合已经要做次日执行跟进，而不只是停留在主文档阶段的时候。

```text
使用 ai-hedge-fund-btst skill，基于 2026-05-29 收盘数据，为 2026-06-01 生成 BTST 全套中文文档，并继续生成 opening watch card 和 premarket execution card。所有 follow-up 文档保持与主文档一致的 execution contract 口径。保存到 outputs/202605/20260529_scheme_a/；如果当前不在 scheme_a，则保存到 outputs/202605/20260529/。
```

### 4. 最简日用版

适合你在新会话里快速触发，不想一次写太多补充说明的时候。

```text
使用 ai-hedge-fund-btst skill，基于 YYYY-MM-DD 收盘数据，为下一交易日生成 BTST 全套中文文档，保存到默认推荐目录；如果方案 A 当前激活，同时补齐 EARLY-WARNING 文档。
```

## 优化复跑模板

适合策略刚调过，想比较优化前后结果是否真的更好。

```text
我下午已经用 ai-hedge-fund-btst skill，基于 YYYY-MM-DD 收盘数据，为 YYYY-MM-DD 生成过一版 BTST 全套中文文档，保存到 outputs/YYYYMM/YYYYMMDD-first/。现在我们优化了 btst 策略，请再次基于同一个 signal date 重新生成同一天的 BTST 全套中文文档，保存到 outputs/YYYYMM/YYYYMMDD-second/。然后比较两次的主票、备选层级、机会池、执行顺序、交易前决策卡和最终建议，判断这次优化是否值得保留，并说明差异来自哪些规则、profile 或下游产物变化。
```

## 使用提醒

- 最稳的写法是同时写清 `signal date` 和 `next trade date`。
- 如果要按目标交易日目录存放，最好补一句“文件名按 signal date 生成”。
- 如果你只写“生成全套文档”，skill 默认更偏主文档流，不一定自动补双 profile 对照或 follow-up cards。
- 如果你希望最终回复里直接给出“今天更偏 conservative 还是 aggressive”的结论，就要在提示词里显式要求交易前决策卡。
