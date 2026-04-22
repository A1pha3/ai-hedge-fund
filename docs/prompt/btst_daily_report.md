# BTST Daily Report Prompts

这份文件只保留可直接复用的 prompt 示例。

当前约定：

- ai-hedge-fund-btst 默认生成整套 5 份 BTST 文档
- 文件名使用信号日，不使用目标交易日
- 如果不写日期，skill 会自动寻找最新一个已有收盘数据的开市日

详细规则见：

- [../../skills/ai-hedge-fund-btst/使用说明.md](../../skills/ai-hedge-fund-btst/%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E.md)
- [../../skills/ai-hedge-fund-btst/references/trigger-examples.md](../../skills/ai-hedge-fund-btst/references/trigger-examples.md)

## Daily Report

- 使用 ai-hedge-fund-btst skill，生成 4 月 20 日的 BTST 全套文档，使用 4 月 17 日收盘数据，保存到默认目录。
- 使用 ai-hedge-fund-btst skill，生成 4 月 21 日的 BTST 全套文档，使用 4 月 20 日收盘数据，保存到 outputs/202604/20260421/。
- 使用 ai-hedge-fund-btst skill，生成 4 月 22 日的 BTST 全套文档，使用 4 月 21 日收盘数据，保存到 outputs/202604/20260422/。
- 使用 ai-hedge-fund-btst skill，生成 4 月 23 日的 BTST 全套文档，使用 4 月 22 日收盘数据，保存到 outputs/202604/20260423/。
- 使用 ai-hedge-fund-btst skill，生成明天的 BTST 全套文档，保存到默认目录。

## Daily Optimize

- 我下午已经用 ai-hedge-fund-btst skill，使用 4 月 17 日收盘数据，生成过一版 4 月 20 日的 BTST 全套文档，保存到 outputs/202604/20260420-first/。晚上我们优化了 btst 策略。现在请再次使用 4 月 17 日收盘数据，通过 ai-hedge-fund-btst skill 重新生成 4 月 20 日的 BTST 全套文档，保存到 outputs/202604/20260420-second/。然后比较两次的选股结果、候选层级、执行顺序和最终建议，评价这次优化是否更好，并说明差异来自哪些规则或产物变化。
- 我们刚调整了 btst 策略参数。请用同一个信号日分别复跑优化前和优化后的 BTST 全套文档，并把两次结果按主票、备选、机会池、观察层和执行清单分开比较，最后给出是否值得保留这次优化的结论。
