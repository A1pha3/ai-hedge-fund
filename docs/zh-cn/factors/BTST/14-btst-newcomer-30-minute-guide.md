# BTST 新人 30 分钟上手路径

> 配套阅读：
>
> 1. [BTST 次日短线 5 分钟简报](./12-btst-five-minute-brief.md)
> 2. [BTST 一页速查卡](./03-btst-one-page-cheatsheet.md)
> 3. [BTST 次日短线策略完整指南](./01-btst-complete-guide.md)
> 4. [BTST 指标与因子判读词典](./07-btst-factor-metric-dictionary.md)
> 5. [BTST 当前窗口案例复盘手册](./08-btst-current-window-case-studies.md)
> 6. [BTST 产物判读手册](./10-btst-artifact-reading-manual.md)
> 7. [BTST 优化决策树](./11-btst-optimization-decision-tree.md)
> 8. [BTST 命令作战手册](./13-btst-command-cookbook.md)
> 9. [BTST 调参与验证作战手册](./02-btst-tuning-playbook.md)

## 1. 这份讲义解决什么问题

当前 BTST 文档已经足够完整，但对新人来说，真正困难的通常不是“没有材料”，而是：

1. 知道这些文档存在，却不知道先看哪一份。
2. 看完几篇后，仍然分不清当前 BTST 的主线到底是什么。
3. 遇到真实样本时，不知道该把它归到 admission、score frontier、blocked release 还是 candidate-entry 语义问题。

这份讲义的目标，就是把新人从“知道 BTST 这个词”带到“能够独立完成一次最小判读闭环”。

所谓最小判读闭环，至少包括 4 件事：

1. 能用一句话说清当前 BTST 的定位。
2. 能把入口问题、评分问题、结构冲突问题分开看。
3. 能用真实样本解释为什么 `300724`、`300394`、`300502` 不能混成一类。
4. 能在拿到一份 report 后，知道先看什么、再看什么，以及下一步该动哪条主线。

如果你读完后仍然只能说“BTST 就是次日短线规则”，那还不算真正上手。真正上手的标准是：你能独立看一个窗口，并给出一句不混层的、可执行的下一步建议。

---

## 2. 学习目标

读完后，你应该能够做到：

1. 用一句话解释 BTST 不是研究主线的附属阈值，而是一条独立短线目标链路。
2. 说清 `short_trade_boundary`、`short_trade_target`、T+1 执行和 replay 验证之间的关系。
3. 区分 `selected`、`near_miss`、`blocked`、`rejected` 的语义差异。
4. 看懂当前窗口里哪条主线已经成立，哪条主线仍是下一轮优化重点。
5. 在真实样本上写出一句合格的 BTST 复盘结论。

---

## 3. 先建立最小心智模型

### 3.1 先记住一句话

BTST 不是“给研究主线额外加一个短线阈值”，而是：

**从短线候选供给、独立建池、正式评分、T+1 执行到 replay 验证的一整条独立目标链路。**

这句话为什么重要：

1. 如果你把 BTST 当成 Layer C 的附属判断，就会误读很多 blocked / rejected 样本。
2. 如果你把 BTST 当成单个分数阈值，就会忽略 admission 和 candidate-entry 语义。

### 3.2 当前 BTST 最重要的阶段性结论

新人最先要知道的，不是某个参数值，而是当前主线已经推进到哪里。

请先记住下面 3 句：

1. 短线不该继续共用旧 Layer B 边界股票池。
2. 新 `short_trade_boundary` 独立建池已经在真实窗口里成立。
3. 下一步重点已经从“独立建池是否成立”转向“score frontier 如何精修释放效率”。

---

## 4. 新人最容易混掉的 4 组概念

### 4.1 研究目标和短线目标不是一回事

研究目标更偏“值得深入看和持有”，短线目标更偏“明天是否仍有交易弹性和执行价值”。

### 4.2 admission 和 target score 不是一回事

admission 解决的是“有没有资格进入正式比较池”，target score 解决的是“正式比较后是否能过线”。

### 4.3 `blocked` 和 `rejected` 不是一回事

`rejected` 更像正式比较后没过分数或风险线，`blocked` 更像存在结构性冲突或 hard block。

### 4.4 单票证据和窗口证据不是一回事

一只票成立，不代表一条规则成立。窗口级证据才决定能不能升级默认候选。

---

## 5. 推荐的 30 分钟上手顺序

### 第 1 段：5 分钟建立方向感

先读：

1. [BTST 次日短线 5 分钟简报](./12-btst-five-minute-brief.md)
2. [BTST 一页速查卡](./03-btst-one-page-cheatsheet.md)

这一段的目标只有一个：

你要知道当前 BTST 已经不在“有没有必要独立建池”的阶段，而在“独立建池后如何精修”的阶段。

### 第 2 段：10 分钟建立完整链路

再读：

1. [BTST 次日短线策略完整指南](./01-btst-complete-guide.md)

这一步不要求你记住所有因子，但要建立一条完整链路：

1. Layer B 给供给。
2. `short_trade_boundary` 给独立补池。
3. `short_trade_target` 给正式决策。
4. replay 和 T+1 结果负责回头校准规则。

### 第 3 段：10 分钟建立样本判读能力

再读：

1. [BTST 指标与因子判读词典](./07-btst-factor-metric-dictionary.md)
2. [BTST 当前窗口案例复盘手册](./08-btst-current-window-case-studies.md)

这一段最重要的不是背定义，而是学会样本分型：

1. `300724` 是 low-cost structural release 样本。
2. `300394` 是 penalty / score construction 样本。
3. `300502` 是 candidate-entry 语义样本。

只要这三类你能分开，后面大部分误判都会少很多。

### 第 4 段：5 分钟建立动作判断能力

最后读：

1. [BTST 产物判读手册](./10-btst-artifact-reading-manual.md)
2. [BTST 优化决策树](./11-btst-optimization-decision-tree.md)

这一段的目标是：

你拿到一份 report 后，能够回答“先看什么”和“下一步该调哪里”。

---

## 6. 第一天必须学会的 4 个判断动作

### 6.1 动作一：判断当前主矛盾在哪一层

你必须先判断：

1. 是上游供给不足。
2. 是 admission 太严。
3. 是 score frontier 太严。
4. 还是 blocked 样本存在结构冲突。

这一步如果错了，后面跑再多命令都只是噪声。

### 6.2 动作二：判断一只票属于哪种 archetype

新人第一天不需要会所有 frontier，但必须能把一只票大致归到下面 4 类之一：

1. 不该进来的弱结构入口样本。
2. 差一点就能释放的 score-fail 样本。
3. 可做定向 release 的 blocked 样本。
4. 需要单独研究的高成本 penalty 样本。

### 6.3 动作三：判断一条变体该不该升级默认

你至少要会问这 3 个问题：

1. 这轮变体只改了一类机制吗。
2. 新增样本质量有没有变坏。
3. 这是单票成立，还是窗口级成立。

### 6.4 动作四：判断下一步该读文档还是该跑命令

规则很简单：

1. 还没搞清主矛盾时，先读案例、词典和产物判读手册。
2. 主矛盾已经明确时，再去命令作战手册里按顺序执行。

---

## 7. 建议的第一轮练习

如果你是第一次真正接触 BTST，建议做下面这组最小练习：

1. 先用 [BTST 次日短线 5 分钟简报](./12-btst-five-minute-brief.md) 说出当前主线结论。
2. 再用 [BTST 当前窗口案例复盘手册](./08-btst-current-window-case-studies.md) 解释 `300724`、`300394`、`300502` 的差异。
3. 最后打开 [BTST 优化决策树](./11-btst-optimization-decision-tree.md)，写一句“如果明天继续优化，我会先做什么”。

如果你能把这三步做完并且不混层，基本就已经跨过“只会读文档，不会用文档”的阶段了。

---

## 8. 建议的 2 小时入门作业

如果要确认新人不是“看懂了”，而是真的“能开始工作”，建议安排一轮 2 小时作业：

1. 用 [BTST 产物判读手册](./10-btst-artifact-reading-manual.md) 说明拿到 report 后的最短阅读顺序。
2. 用 [BTST 指标与因子判读词典](./07-btst-factor-metric-dictionary.md) 解释 3 个关键指标的含义。
3. 用 [BTST 变体验收清单与升级标准](./09-btst-variant-acceptance-checklist.md) 判断 catalyst-only admission 为什么可以升级默认候选。
4. 用 [BTST 命令作战手册](./13-btst-command-cookbook.md) 写出一条你认为当前最应该先跑的命令链路。

这轮作业的目标不是跑出新结果，而是确认你已经具备独立开始 BTST 研究的基本判断能力。

---

## 9. 新人最常见的 6 个误区

1. 把 BTST 当成研究主线后面多加一个阈值。
2. 把 `blocked` 和 `rejected` 样本混着看。
3. 看见样本数增加就以为变体成功，而不看次日 quality 指标。
4. 把 `300724`、`300394`、`300502` 当成同一类问题一起救。
5. 一上来就跑很多 frontier，却没先判断当前主失败簇。
6. 单票结果一成立，就误以为默认规则已经成立。

---

## 10. 上手后的下一步

如果你已经完成这份讲义，后续建议按角色继续深入：

1. 研究调参：继续读 [BTST 调参与验证作战手册](./02-btst-tuning-playbook.md) 和 [BTST 变体验收清单与升级标准](./09-btst-variant-acceptance-checklist.md)。
2. AI 助手执行：继续读 [BTST 命令作战手册](./13-btst-command-cookbook.md) 和 [BTST AI 助手优化执行手册](./05-btst-ai-optimization-runbook.md)。
3. 业务快读：继续读 [BTST 次日短线 5 分钟简报](./12-btst-five-minute-brief.md) 和 [BTST 一页速查卡](./03-btst-one-page-cheatsheet.md)。

---

## 11. 一句话总结

BTST 新人上手最重要的不是一次看完所有文档，而是先建立正确顺序：先知道当前主线推进到哪，再学会分样本类型，再学会看 artifact，最后才进入命令和实验。顺序对了，上手速度会快很多。
