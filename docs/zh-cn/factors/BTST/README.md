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
12. [12-btst-five-minute-brief.md](./12-btst-five-minute-brief.md)
13. [13-btst-command-cookbook.md](./13-btst-command-cookbook.md)
14. [14-btst-newcomer-30-minute-guide.md](./14-btst-newcomer-30-minute-guide.md)
15. [15-btst-onboarding-readiness-scorecard.md](./15-btst-onboarding-readiness-scorecard.md)
16. [16-btst-trainer-handbook.md](./16-btst-trainer-handbook.md)
17. [17-btst-sample-workbook.md](./17-btst-sample-workbook.md)
18. [18-btst-workbook-quick-review-card.md](./18-btst-workbook-quick-review-card.md)
19. [0330 BTST 优化路线设计文](./optimize0330/README.md)

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
5. 管理层 / 业务快读：`12 -> 03`
6. 命令执行：`13 -> 10 -> 04`
7. 新人 30 分钟上手：`14 -> 12 -> 03 -> 01`
8. 新人验收：`14 -> 15`
9. 带教培训：`16 -> 14 -> 17 -> 15`
10. 现场速评：`17 -> 18 -> 15`
11. 研究专项审阅：`19 -> 02 -> 09 -> 13`

读完整套 BTST 文档后，你应该能回答三类问题：

1. 当前 BTST 到底是如何从 Layer B 候选逐步变成次日执行计划的。
2. 为什么某个样本会被 selected、near_miss、blocked 或 rejected。
3. 当策略供给不足、次日表现变差、或 near-miss 太多时，应该先调什么、怎么调、如何验证。
4. 当前窗口里 `300724`、`300394`、`300502` 这类样本为什么不能用一套方法一起处理。
5. 一轮 BTST 变体什么时候只能保留为候选，什么时候才配升级默认。
6. 如果只有 5 分钟，当前 BTST 的阶段结论和下一步优先级到底是什么。
7. 如果要亲手跑 BTST 分析，当前最短且最稳的命令顺序是什么。
8. 如果今天第一次接手 BTST，30 分钟内最合理的学习顺序是什么。
9. 新人什么时候算已经能独立使用 BTST 文档做判断。
10. 如果我要带别人学 BTST，1 小时培训该怎么排。
11. 如果我要检验新人会不会做样本分型和动作判断，应该出什么练习题。
12. 如果我要在培训现场 1 分钟内快速核对练习答案，应该看什么。
13. 如果我要把一次 BTST 讨论整理成可评审的优化路线，应该先讲哪些证据、按什么执行顺序推进。
