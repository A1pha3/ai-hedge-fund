# BTST 文档导航

适用对象：第一次接触本项目 BTST 次日短线选股体系的新手、要复盘和扩窗验证的研究员、以及需要按步骤自动执行优化任务的 AI 助手。

这个目录的目标不是再写一份零散结论，而是把当前仓库里已经落地的 BTST 规则、验证方法和调参路径整理成一套可执行文档。

建议阅读顺序：

1. [01-btst-complete-guide.md](./01-btst-complete-guide.md)
2. [03-btst-one-page-cheatsheet.md](./03-btst-one-page-cheatsheet.md)
3. [07-btst-factor-metric-dictionary.md](./07-btst-factor-metric-dictionary.md)
4. [08-btst-current-window-case-studies.md](./08-btst-current-window-case-studies.md)
5. [02-btst-tuning-playbook.md](./02-btst-tuning-playbook.md)
6. [09-btst-variant-acceptance-checklist.md](./09-btst-variant-acceptance-checklist.md)
7. [10-btst-artifact-reading-manual.md](./10-btst-artifact-reading-manual.md)
8. [11-btst-optimization-decision-tree.md](./11-btst-optimization-decision-tree.md)
9. [04-btst-experiment-template.md](./04-btst-experiment-template.md)
10. [05-btst-ai-optimization-runbook.md](./05-btst-ai-optimization-runbook.md)
11. [06-btst-troubleshooting-playbook.md](./06-btst-troubleshooting-playbook.md)

如果你当前的任务更偏专项排障，建议搭配阅读：

1. [../03-layer-b-complete-beginner-guide.md](../03-layer-b-complete-beginner-guide.md)
2. [../22-layer-b-c-joint-review-manual.md](../22-layer-b-c-joint-review-manual.md)
3. [../24-execution-bridge-professional-guide.md](../24-execution-bridge-professional-guide.md)
4. [../28-paper-trading-tday-t1-timing-guide.md](../28-paper-trading-tday-t1-timing-guide.md)
5. [../../product/arch/dual_target_system/short_trade_target_rule_spec.md](../../product/arch/dual_target_system/short_trade_target_rule_spec.md)
6. [../../product/arch/dual_target_system/short_trade_target_metrics_and_validation.md](../../product/arch/dual_target_system/short_trade_target_metrics_and_validation.md)

如果你想按角色直达，推荐这样读：

1. 新手入门：`01 -> 03 -> 07 -> 08`
2. 研究调参：`02 -> 09 -> 10 -> 11 -> 04`
3. AI 助手执行：`02 -> 10 -> 11 -> 05 -> 04`
4. 线上排障：`03 -> 07 -> 10 -> 06`

读完整套 BTST 文档后，你应该能回答三类问题：

1. 当前 BTST 到底是如何从 Layer B 候选逐步变成次日执行计划的。
2. 为什么某个样本会被 selected、near_miss、blocked 或 rejected。
3. 当策略供给不足、次日表现变差、或 near-miss 太多时，应该先调什么、怎么调、如何验证。
4. 当前窗口里 `300724`、`300394`、`300502` 这类样本为什么不能用一套方法一起处理。
5. 一轮 BTST 变体什么时候只能保留为候选，什么时候才配升级默认。
