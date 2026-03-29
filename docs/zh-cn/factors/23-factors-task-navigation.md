# Factors 按任务导航：排障、复盘、调参与讲解该看什么

适用对象：已经知道 factors 目录里文档很多，但想按当前任务快速找到最有用入口的读者。

这份文档解决的问题：

1. 当前是在排障、复盘、调参还是给别人讲解时，应该先看哪篇。
2. 如何避免一上来就钻进不适合当前任务的长文。
3. 怎样用最少的阅读成本定位到正确文档组合。

---

## 1. 如果你现在是在排障

排障的目标是先定位问题发生在哪一层，而不是先下结论应该调什么。

推荐顺序：

1. [Factors 目录首页](./17-factors-overview-home.md)
2. [Layer B 一页速查卡](./05-layer-b-one-page-cheatsheet.md)
3. [Layer C 一页速查卡](./19-layer-c-one-page-cheatsheet.md)
4. [Layer B / Layer C 联动复盘手册](./22-layer-b-c-joint-review-manual.md)
5. 如果问题明确落在 BTST 次日短线，再看 [BTST 排障与问题定位手册](./BTST/06-btst-troubleshooting-playbook.md)
6. 如果问题明确落在 fundamental，再看 [Fundamental 五子因子联动复盘手册](./15-fundamental-subfactor-joint-review-manual.md)
7. 如果问题明确落在 buy order 承接，再看 [Execution Bridge 一页速查卡](./25-execution-bridge-one-page-cheatsheet.md)
8. 如果问题明确落在日级事件口径，再看 [Paper Trading T 日到 T+1 时序专题](./28-paper-trading-tday-t1-timing-guide.md)

适合的问题：

1. “这只票到底死在哪一层。”
2. “为什么它没进入 Layer C。”
3. “为什么它进了 Layer C 却没进 watchlist。”

---

## 2. 如果你现在是在复盘真实样本

复盘的目标是形成一句靠谱判断，并决定下一步要不要做实验。

推荐顺序：

1. [Layer B 一页速查卡](./05-layer-b-one-page-cheatsheet.md)
2. [Fundamental 因子一页速查卡](./08-fundamental-factor-one-page-cheatsheet.md)
3. [Layer C 一页速查卡](./19-layer-c-one-page-cheatsheet.md)
4. [Fundamental 五子因子联动复盘手册](./15-fundamental-subfactor-joint-review-manual.md)
5. [Layer B / Layer C 联动复盘手册](./22-layer-b-c-joint-review-manual.md)
6. 如果目标是复盘次日短线结论，再看 [BTST 一页速查卡](./BTST/03-btst-one-page-cheatsheet.md)
7. 如果你已经锁定 BTST 样本，还看不懂因子和 penalty 的语义，再看 [BTST 指标与因子判读词典](./BTST/07-btst-factor-metric-dictionary.md)
8. 如果你想用真实窗口样本快速对齐当前主矛盾，再看 [BTST 当前窗口案例复盘手册](./BTST/08-btst-current-window-case-studies.md)
9. 如果样本已经进 selected 但没买，再看 [24-execution-bridge-professional-guide.md](./24-execution-bridge-professional-guide.md)
10. 如果样本跨交易日才成交，再看 [Paper Trading T 日到 T+1 时序专题](./28-paper-trading-tday-t1-timing-guide.md)

适合的问题：

1. “这只票为什么被压下去。”
2. “它是被规则层挡住，还是研究层不买账。”
3. “它是厚度不够，还是结构性冲突。”

---

## 3. 如果你现在是在调参或设计实验

调参的目标不是找到一个看起来更热的阈值，而是确认主矛盾属于语义、供给、融合还是执行承接。

推荐顺序：

1. [因子聚合语义入门](./01-aggregation-semantics-and-factor-traps.md)
2. [层 B 因子参数根因分析与实验矩阵](./04-%E5%B1%82B%E5%9B%A0%E5%AD%90%E5%8F%82%E6%95%B0%E6%A0%B9%E5%9B%A0%E5%88%86%E6%9E%90%E4%B8%8E%E5%AE%9E%E9%AA%8C%E7%9F%A9%E9%98%B5-20260326.md)
3. [Fundamental 五子因子联动复盘手册](./15-fundamental-subfactor-joint-review-manual.md)
4. [Layer C 常见问题 FAQ](./21-layer-c-faq.md)
5. [Layer B / Layer C 联动复盘手册](./22-layer-b-c-joint-review-manual.md)
6. 如果当前主线是次日短线，再看 [BTST 调参与验证作战手册](./BTST/02-btst-tuning-playbook.md)
7. 如果你做完一轮变体后要判断能否升级默认，再看 [BTST 变体验收清单与升级标准](./BTST/09-btst-variant-acceptance-checklist.md)
8. 如果你连该先看哪个 artifact 都不确定，再看 [BTST 产物判读手册](./BTST/10-btst-artifact-reading-manual.md)
9. 如果知道问题存在但还选不出下一步动作，再看 [BTST 优化决策树](./BTST/11-btst-optimization-decision-tree.md)
10. 如果要把任务交给自动化代理，再看 [BTST AI 助手优化执行手册](./BTST/05-btst-ai-optimization-runbook.md)
11. 如果新增样本卡在 buy order，再看 [24-execution-bridge-professional-guide.md](./24-execution-bridge-professional-guide.md)

适合的问题：

1. “这是不是阈值问题。”
2. “是局部语义有问题，还是供给不足。”
3. “放宽 Layer B 后，样本会不会只是死在 Layer C。”

---

## 4. 如果你现在是在给别人讲解系统

讲解的目标是先让对方抓住边界、角色和主流程，而不是一上来就推公式。

推荐顺序：

1. [Layer B 问题 5 分钟速读版](./02-layer-b-quick-read-for-non-developers.md)
2. [Layer B 策略完全讲解](./03-layer-b-complete-beginner-guide.md)
3. [Layer C 策略完全讲解](./16-layer-c-complete-beginner-guide.md)
4. [Fundamental 专题首页](./14-fundamental-topic-reading-path.md)
5. [Layer C 专题首页](./20-layer-c-topic-reading-path.md)
6. 如果要专门讲次日短线，再看 [BTST 次日短线策略完整指南](./BTST/01-btst-complete-guide.md)
7. 如果要把“会选”和“会买”讲清楚，再看 [24-execution-bridge-professional-guide.md](./24-execution-bridge-professional-guide.md)
8. 如果要把“T 日生成计划、T+1 执行”讲清楚，再看 [28-paper-trading-tday-t1-timing-guide.md](./28-paper-trading-tday-t1-timing-guide.md)
9. 如果你只需要 5 分钟把当前 BTST 业务结论讲清楚，再看 [BTST 次日短线 5 分钟简报](./BTST/12-btst-five-minute-brief.md)

适合的问题：

1. “系统为什么要分 Layer B 和 Layer C。”
2. “fundamental 在里面扮演什么角色。”
3. “watchlist 是怎么从规则层和研究层一起出来的。”

---

## 5. 如果你只剩 10 分钟

建议直接读这 4 篇：

1. [05-layer-b-one-page-cheatsheet.md](./05-layer-b-one-page-cheatsheet.md)
2. [08-fundamental-factor-one-page-cheatsheet.md](./08-fundamental-factor-one-page-cheatsheet.md)
3. [19-layer-c-one-page-cheatsheet.md](./19-layer-c-one-page-cheatsheet.md)
4. [22-layer-b-c-joint-review-manual.md](./22-layer-b-c-joint-review-manual.md)
5. [25-execution-bridge-one-page-cheatsheet.md](./25-execution-bridge-one-page-cheatsheet.md)
6. 如果你只关心次日短线，再加读 [BTST/03-btst-one-page-cheatsheet.md](./BTST/03-btst-one-page-cheatsheet.md)
7. 如果你既想快速判断又要准备开跑脚本，再加读 [BTST/13-btst-command-cookbook.md](./BTST/13-btst-command-cookbook.md)

这 4 篇可以覆盖：

1. Layer B 是什么
2. fundamental 为什么常是主拖累
3. Layer C 为什么会二次否决
4. 跨层问题该怎么快速定位

---

## 6. 一句话总结

这份任务导航页的作用不是增加新知识，而是把现有文档按“你现在正在做什么”重新组织，让你先找到最对的入口，再决定是否需要读长文。
