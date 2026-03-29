# Factors 目录首页：学习地图、阅读入口与问题导向导航

适用对象：第一次进入 factors 目录的读者，以及需要快速判断“应该看哪篇”的开发者、研究者、产品和复盘人员。

这份文档解决的问题：

1. factors 目录下这些文档各自负责什么。
2. Layer B、fundamental、Layer C 相关材料之间的关系是什么。
3. 不同角色和不同问题应从哪篇开始读。
4. 如果只是来解决一个具体问题，怎样最快找到对应材料。

---

## 1. 这个目录主要覆盖什么

当前 factors 目录主要覆盖三类内容：

1. Layer B 的整体机制、聚合语义和源码读法。
2. fundamental 及其五个子因子的拆解、阅读路径和复盘方法。
3. Layer C 的整体机制与 B/C 融合后的研究读法。
4. 跨层复盘和按任务使用这些文档的方法。
5. watchlist 到 execution bridge 的执行承接读法。
6. paper trading 里 T 日计划到 T+1 执行的时序口径。
7. BTST 次日短线目标的策略、调参与验证闭环。

可以把它理解成一个从规则层、因子层到复盘层的知识目录，而不是单纯的说明文集合。

---

## 2. 目录分层

### 2.1 入门层：先建立整体框架

适合第一次进入这个目录的读者。

1. [Layer B 问题 5 分钟速读版](./02-layer-b-quick-read-for-non-developers.md)
2. [Layer B 策略完全讲解](./03-layer-b-complete-beginner-guide.md)
3. [Layer C 策略完全讲解](./16-layer-c-complete-beginner-guide.md)

这一层回答的是：

1. Layer B 和 Layer C 分别负责什么。
2. 为什么当前系统不会只看单一分数。
3. 从候选到 watchlist 再到执行，主要闸门在哪里。

### 2.2 机制层：先理解聚合语义和代码口径

适合已经知道系统大框架，但要开始认真排障或调参的读者。

1. [因子聚合语义入门](./01-aggregation-semantics-and-factor-traps.md)
2. [Layer B 源码导读](./06-layer-b-source-code-walkthrough.md)
3. [层 B 因子参数根因分析与实验矩阵](./04-%E5%B1%82B%E5%9B%A0%E5%AD%90%E5%8F%82%E6%95%B0%E6%A0%B9%E5%9B%A0%E5%88%86%E6%9E%90%E4%B8%8E%E5%AE%9E%E9%AA%8C%E7%9F%A9%E9%98%B5-20260326.md)

这一层回答的是：

1. 哪些调参直觉在聚合器里会失效。
2. 代码里到底如何形成 strategy signal。
3. 当前窗口问题是局部语义、供给不足，还是融合效应。

### 2.3 fundamental 专题层：把一条重要策略真正拆开

适合专门研究 fundamental 这条策略的人。

1. [Fundamental 专题首页](./14-fundamental-topic-reading-path.md)
2. [Fundamental 因子专业讲解](./07-fundamental-factor-professional-guide.md)
3. [Fundamental 因子一页速查卡](./08-fundamental-factor-one-page-cheatsheet.md)
4. [Fundamental 五子因子联动复盘手册](./15-fundamental-subfactor-joint-review-manual.md)
5. [Fundamental 常见问题 FAQ](./18-fundamental-faq.md)

这一层回答的是：

1. fundamental 到底是什么。
2. 五个子因子分别干什么。
3. 真正在 report 里怎么读、怎么复盘、怎么排误判。

### 2.4 子因子深潜层：只看某一条腿

适合已经定位到具体拖累项的读者。

1. [Profitability 子因子专业讲解](./09-profitability-subfactor-professional-guide.md)
2. [Growth 子因子专业讲解](./10-growth-subfactor-professional-guide.md)
3. [Financial Health 子因子专业讲解](./11-financial-health-subfactor-professional-guide.md)
4. [Growth Valuation 子因子专业讲解](./12-growth-valuation-subfactor-professional-guide.md)
5. [Industry PE 子因子专业讲解](./13-industry-pe-subfactor-professional-guide.md)

这一层最适合回答的问题是：

1. 这条腿到底为什么给负。
2. 这条腿是主杀器、放大器，还是缺助推器。
3. 要调参数时应该先看什么。

### 2.5 Layer C 专题层：把研究确认层真正拆开

适合专门研究 Layer C 这条研究确认链路的人。

1. [Layer C 专题首页](./20-layer-c-topic-reading-path.md)
2. [Layer C 策略完全讲解](./16-layer-c-complete-beginner-guide.md)
3. [Layer C 一页速查卡](./19-layer-c-one-page-cheatsheet.md)
4. [Layer C 常见问题 FAQ](./21-layer-c-faq.md)

这一层回答的是：

1. Layer C 到底如何形成分数、冲突和 watchlist 决策。
2. 复盘时最关键的字段是什么。
3. 最常见的 Layer C 误读有哪些。

### 2.6 跨层与任务层：把文档真正用起来

适合已经知道文档在哪里，但还需要“先看什么、后看什么”的读者。

1. [Layer B / Layer C 联动复盘手册](./22-layer-b-c-joint-review-manual.md)
2. [Factors 按任务导航](./23-factors-task-navigation.md)
3. [Execution Bridge 专业讲解](./24-execution-bridge-professional-guide.md)
4. [Execution Bridge 一页速查卡](./25-execution-bridge-one-page-cheatsheet.md)
5. [Paper Trading T 日到 T+1 时序专题](./28-paper-trading-tday-t1-timing-guide.md)

### 2.7 BTST 专题层：把次日短线独立成完整工作流

适合专门研究次日短线目标、short trade boundary、score frontier 和窗口级验证的人。

1. [BTST 文档导航](./BTST/README.md)
2. [BTST 次日短线策略完整指南](./BTST/01-btst-complete-guide.md)
3. [BTST 一页速查卡](./BTST/03-btst-one-page-cheatsheet.md)
4. [BTST 指标与因子判读词典](./BTST/07-btst-factor-metric-dictionary.md)
5. [BTST 当前窗口案例复盘手册](./BTST/08-btst-current-window-case-studies.md)
6. [BTST 调参与验证作战手册](./BTST/02-btst-tuning-playbook.md)
7. [BTST 变体验收清单与升级标准](./BTST/09-btst-variant-acceptance-checklist.md)
8. [BTST 产物判读手册](./BTST/10-btst-artifact-reading-manual.md)
9. [BTST 优化决策树](./BTST/11-btst-optimization-decision-tree.md)
10. [BTST AI 助手优化执行手册](./BTST/05-btst-ai-optimization-runbook.md)
11. [BTST 排障与问题定位手册](./BTST/06-btst-troubleshooting-playbook.md)
12. [BTST 次日短线 5 分钟简报](./BTST/12-btst-five-minute-brief.md)
13. [BTST 命令作战手册](./BTST/13-btst-command-cookbook.md)
14. [BTST 新人 30 分钟上手路径](./BTST/14-btst-newcomer-30-minute-guide.md)
15. [BTST 新人上手验收评分表](./BTST/15-btst-onboarding-readiness-scorecard.md)
16. [BTST 带教手册](./BTST/16-btst-trainer-handbook.md)
17. [BTST 样本练习册](./BTST/17-btst-sample-workbook.md)
18. [BTST 标准答案速评卡](./BTST/18-btst-workbook-quick-review-card.md)

这一层回答的是：

1. 短线目标为什么不能继续完全共用研究型目标的入口和阈值。
2. short trade boundary、short trade target、replay frontier 和次日结果验证之间如何闭环。
3. 研究员和 AI 助手应如何按固定步骤优化 BTST，而不是凭感觉试参数。

这一层回答的是：

1. 样本到底卡在 B、C、watchlist 还是 execution。
2. 当前是在排障、复盘、调参还是讲解时，该先看哪组材料。
3. 已经通过研究层的票，为什么仍然没有进入 buy order。
4. daily_events 里的 `prepared_plan`、`current_plan` 和 `executed_trades` 到底分别表示哪一天。

---

## 3. 按角色给阅读入口

### 3.1 产品或业务同学

建议顺序：

1. [02-layer-b-quick-read-for-non-developers.md](./02-layer-b-quick-read-for-non-developers.md)
2. [03-layer-b-complete-beginner-guide.md](./03-layer-b-complete-beginner-guide.md)
3. [08-fundamental-factor-one-page-cheatsheet.md](./08-fundamental-factor-one-page-cheatsheet.md)
4. [16-layer-c-complete-beginner-guide.md](./16-layer-c-complete-beginner-guide.md)
5. [19-layer-c-one-page-cheatsheet.md](./19-layer-c-one-page-cheatsheet.md)
6. [BTST 一页速查卡](./BTST/03-btst-one-page-cheatsheet.md)

### 3.2 开发和研究同学

建议顺序：

1. [01-aggregation-semantics-and-factor-traps.md](./01-aggregation-semantics-and-factor-traps.md)
2. [06-layer-b-source-code-walkthrough.md](./06-layer-b-source-code-walkthrough.md)
3. [14-fundamental-topic-reading-path.md](./14-fundamental-topic-reading-path.md)
4. [15-fundamental-subfactor-joint-review-manual.md](./15-fundamental-subfactor-joint-review-manual.md)
5. [16-layer-c-complete-beginner-guide.md](./16-layer-c-complete-beginner-guide.md)
6. [20-layer-c-topic-reading-path.md](./20-layer-c-topic-reading-path.md)
7. [BTST 次日短线策略完整指南](./BTST/01-btst-complete-guide.md)

### 3.3 复盘人员

建议顺序：

1. [05-layer-b-one-page-cheatsheet.md](./05-layer-b-one-page-cheatsheet.md)
2. [08-fundamental-factor-one-page-cheatsheet.md](./08-fundamental-factor-one-page-cheatsheet.md)
3. [15-fundamental-subfactor-joint-review-manual.md](./15-fundamental-subfactor-joint-review-manual.md)
4. [16-layer-c-complete-beginner-guide.md](./16-layer-c-complete-beginner-guide.md)
5. [19-layer-c-one-page-cheatsheet.md](./19-layer-c-one-page-cheatsheet.md)

---

## 4. 按问题找文档

如果你带着具体问题进来，可以直接按下面路径查：

1. “为什么 Layer B 调参常和直觉不一样”：看 [01-aggregation-semantics-and-factor-traps.md](./01-aggregation-semantics-and-factor-traps.md)
2. “我想从头看懂 Layer B”：看 [03-layer-b-complete-beginner-guide.md](./03-layer-b-complete-beginner-guide.md)
3. “我想从头看懂 Layer C”：看 [16-layer-c-complete-beginner-guide.md](./16-layer-c-complete-beginner-guide.md)
4. “我只想快速判断 fundamental 是不是主拖累”：看 [08-fundamental-factor-one-page-cheatsheet.md](./08-fundamental-factor-one-page-cheatsheet.md)
5. “我想系统研究 fundamental”：看 [14-fundamental-topic-reading-path.md](./14-fundamental-topic-reading-path.md)
6. “我在真实 report 里不知道先查谁”：看 [15-fundamental-subfactor-joint-review-manual.md](./15-fundamental-subfactor-joint-review-manual.md)
7. “我对 fundamental 有一堆重复疑问”：看 [18-fundamental-faq.md](./18-fundamental-faq.md)
8. “我只想快速判断 Layer C 为什么拦住了票”：看 [19-layer-c-one-page-cheatsheet.md](./19-layer-c-one-page-cheatsheet.md)
9. “我想系统研究 Layer C”：看 [20-layer-c-topic-reading-path.md](./20-layer-c-topic-reading-path.md)
10. “我对 Layer C 有一堆重复疑问”：看 [21-layer-c-faq.md](./21-layer-c-faq.md)
11. “我不知道问题到底卡在哪一层”：看 [22-layer-b-c-joint-review-manual.md](./22-layer-b-c-joint-review-manual.md)
12. “我只想按当前任务快速找入口”：看 [23-factors-task-navigation.md](./23-factors-task-navigation.md)
13. “我想搞清楚为什么进了 watchlist 还是没下单”：看 [24-execution-bridge-professional-guide.md](./24-execution-bridge-professional-guide.md)
14. “我只想快速判断 execution blocker 是什么意思”：看 [25-execution-bridge-one-page-cheatsheet.md](./25-execution-bridge-one-page-cheatsheet.md)
15. “我想搞清楚 T 日生成计划、T+1 执行到底怎么落盘”：看 [28-paper-trading-tday-t1-timing-guide.md](./28-paper-trading-tday-t1-timing-guide.md)
16. “我想系统看懂 BTST 次日短线”：看 [BTST/01-btst-complete-guide.md](./BTST/01-btst-complete-guide.md)
17. “我想按步骤优化 BTST 参数”：看 [BTST/02-btst-tuning-playbook.md](./BTST/02-btst-tuning-playbook.md)
18. “我只想快速抓 BTST 要点”：看 [BTST/03-btst-one-page-cheatsheet.md](./BTST/03-btst-one-page-cheatsheet.md)
19. “我想把 BTST 任务交给 AI 助手”：看 [BTST/05-btst-ai-optimization-runbook.md](./BTST/05-btst-ai-optimization-runbook.md)
20. “我看不懂 BTST 指标到底在说什么”：看 [BTST/07-btst-factor-metric-dictionary.md](./BTST/07-btst-factor-metric-dictionary.md)
21. “我想用真实样本理解 BTST 现在的主矛盾”：看 [BTST/08-btst-current-window-case-studies.md](./BTST/08-btst-current-window-case-studies.md)
22. “我想判断一个 BTST 变体能不能升级默认”：看 [BTST/09-btst-variant-acceptance-checklist.md](./BTST/09-btst-variant-acceptance-checklist.md)
23. “我不知道应该先看哪个 BTST artifact”：看 [BTST/10-btst-artifact-reading-manual.md](./BTST/10-btst-artifact-reading-manual.md)
24. “我知道问题存在，但不知道下一步该动哪里”：看 [BTST/11-btst-optimization-decision-tree.md](./BTST/11-btst-optimization-decision-tree.md)
25. “我只想 5 分钟知道当前 BTST 到底进展到哪了”：看 [BTST/12-btst-five-minute-brief.md](./BTST/12-btst-five-minute-brief.md)
26. “我准备直接跑脚本，但不知道命令顺序”：看 [BTST/13-btst-command-cookbook.md](./BTST/13-btst-command-cookbook.md)
27. “我是第一次接手 BTST，不知道 30 分钟内该先看哪几篇”：看 [BTST/14-btst-newcomer-30-minute-guide.md](./BTST/14-btst-newcomer-30-minute-guide.md)
28. “我想判断新人是否已经能独立使用 BTST 文档”：看 [BTST/15-btst-onboarding-readiness-scorecard.md](./BTST/15-btst-onboarding-readiness-scorecard.md)
29. “我要带别人学 BTST，但不知道培训脚本怎么排”：看 [BTST/16-btst-trainer-handbook.md](./BTST/16-btst-trainer-handbook.md)
30. “我要检查新人会不会做 BTST 样本分型和动作判断”：看 [BTST/17-btst-sample-workbook.md](./BTST/17-btst-sample-workbook.md)
31. “我要在带教现场快速核对 BTST 练习题答案”：看 [BTST/18-btst-workbook-quick-review-card.md](./BTST/18-btst-workbook-quick-review-card.md)

---

## 5. 最小使用方式

如果你不想一次看很多，可以把 factors 目录的最小使用方式压缩成 3 步：

1. 先选一篇整体导读，Layer B 看 [03-layer-b-complete-beginner-guide.md](./03-layer-b-complete-beginner-guide.md)，Layer C 看 [16-layer-c-complete-beginner-guide.md](./16-layer-c-complete-beginner-guide.md)。
2. 再选一篇速查卡，Layer B 看 [05-layer-b-one-page-cheatsheet.md](./05-layer-b-one-page-cheatsheet.md)，fundamental 看 [08-fundamental-factor-one-page-cheatsheet.md](./08-fundamental-factor-one-page-cheatsheet.md)。
3. 如果问题明确落在次日短线，再直接跳到 [BTST 文档导航](./BTST/README.md)。
4. 真要动手排障或调参时，再跳到机制层和专题层。

---

## 6. 一句话总结

这份目录首页的作用不是重复介绍每篇文档，而是让读者能按角色、问题和任务，快速从 factors 目录里找到正确入口。
