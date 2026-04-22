# Trigger Examples

Load this file only when activation is ambiguous or the user asks how to invoke the skill.

## Strong triggers

- 生成明天的 BTST 全套文档，保存到默认目录。
- 使用 2026-04-21 收盘数据生成次日 BTST 交易计划。
- 生成 4 月 22 日的 BTST 通俗说明，保存到 /自定义/目录。
- 生成次日短线交易文档，使用 4 月 21 日收盘数据。

## Still valid triggers

- 生成明天的 BTST 交易计划。
- 生成明天的 BTST 通俗说明。
- 生成 4 月 22 日的 BTST 文档。

Default behavior remains: generate the full 5-file pack unless the user explicitly narrows scope.

## Non-triggers

- 只分析某只股票明天能不能买。
- 跑 BTST 回测或优化实验。
- 刷新 nightly control tower 或 reports manifest。
- 只想生成 paper trading 原始报告，不需要 5 份最终中文文档。

## Ambiguity handling

- If BTST + next-day document intent is clear but the user did not mention a directory, still trigger and ask the required opening question.
- If the user only asks how to use the skill, give one recommended prompt instead of running commands.
- If the user mixes BTST docs with unrelated research or backtest work, keep this skill scoped to the BTST next-day document workflow only.
