# BTST 2026-04-15 复盘驱动系统优化方案

## 阅读目标

1. 看清 2026-04-14 生成的 BTST 策略，在 2026-04-15 实盘环境下到底错在什么地方。
2. 区分“单日市场变化导致的失手”和“系统结构本身的缺口”。
3. 给出一条适合当前仓库的最佳优化路线，而不是继续做分散、低解释力的参数微调。
4. 明确每一项优化应该落到哪个模块、脚本和验证口径上。

## 任务定义

本方案基于两类证据整理：

1. 昨日策略文档：/Volumes/mini_matrix/github/a1pha3/prompt_alpha/quant/ai_hedge_fud_work/short/202604/BTST-20260414.md
2. 今日真实行情：Tushare Pro 2026-04-15 全市场日线、指数日线、涨跌停列表、北向资金数据

本方案不是重新写一版择股结论，而是回答三个更重要的问题：

1. 昨天的策略，哪些判断在今天被证伪。
2. 这些被证伪的部分，暴露了当前 BTST 交易系统的哪些结构性短板。
3. 参考高收益超短量化系统的共性做法，当前仓库最应该优先做哪条优化主线。

## 0415 客观复盘

### 一、市场层先错位了

昨天文档使用 04-14 收盘横截面，给出的总判断是“偏强，可适当进攻”。但 04-15 的真实市场结构不是“全面强”，而是“宽度走弱、风格分化、高低切换剧烈”。

| 维度 | 04-14 文档信号日口径 | 04-15 Tushare 真实结果 | 结论 |
| --- | --- | --- | --- |
| 候选池上涨占比 | 69% | 38.13% | 宽度明显恶化 |
| 候选池均涨幅 | +1.24% | -0.1904% | 市场从顺风切到逆风 |
| 候选池中位涨幅 | 未强调 | -0.6747% | 中位股更弱，亏钱效应扩散 |
| 上证指数 | 强势背景 | +0.0145% | 权重表面平稳 |
| 深证成指 | 强势背景 | -0.9665% | 成长风格明显走弱 |
| 创业板指 | 强势背景 | -1.2243% | 高弹性票风险显著放大 |
| 涨跌停结构 | 0 涨停 / 0 跌停 | 57 涨停 / 7 跌停 | 不是普涨，而是强分化 |

这意味着昨天系统默认的前提其实是错的：

1. 它把 04-14 的强势横截面，近似当成了 04-15 的可延续交易环境。
2. 它没有提前识别“权重不弱，但成长和中小票转弱”的风格切换。
3. 它没有把“宽度下降但涨停家数上升”的高分化环境，识别为 BTST 最危险的假突破日。

### 二、分层结果不是“全错”，而是“盘中给机会、尾盘承接差”

这次最关键的证据，不是某几只票涨跌，而是不同分层在“盘中摸高”和“收盘兑现”两个目标上的表现完全不同。

| 分层 | 样本数 | 收盘为正 | 盘中高点 ≥ 前收 +2% | 假突破数量 | 平均收盘收益 |
| --- | ---: | ---: | ---: | ---: | ---: |
| LLM 主票 | 1 | 1 | 1 | 0 | +0.11% |
| LLM 备选票 | 3 | 0 | 1 | 1 | -4.53% |
| LLM 观察票 | 6 | 2 | 4 | 2 | -2.38% |
| 因子层 Top 票 | 10 | 5 | 8 | 3 | +0.55% |
| 低吸优选票 | 4 | 2 | 2 | 0 | +0.50% |
| 反转票 | 5 | 2 | 2 | 0 | +0.43% |

这里有三个重要结论：

1. 因子层不是没有 Alpha。它抓到了盘中弹性，但无法稳定识别尾盘承接。
2. LLM 主票 001309 没有出大错，但也没有走成高质量 follow-through，只是“方向勉强对、收益质量偏低”。
3. LLM 备选和观察层问题最大，它们对盘中确认的依赖过强，但系统没有把“确认后是否能守住”单独建模。

### 三、关键个股复盘

#### 1. 主票 001309：方向部分正确，但利润质量不足

04-15 真实结果：

1. 高点相对前收 +3.87%。
2. 收盘相对前收仅 +0.11%。
3. 开盘到收盘基本走平，属于“盘中有确认，尾盘无扩展”。

这说明 yesterday 文档的主票选择并非完全失真，但当前系统把它描述成 confirm_then_hold_breakout，仍然高估了“确认后继续持有到收盘”的质量。

#### 2. 备选票 605117、000988、001267：边界票筛选质量明显不够

04-15 真实结果：

1. 605117 收盘 -5.67%，全天无有效突破。
2. 000988 收盘 -6.91%，全天弱势下杀。
3. 001267 盘中一度 +3.89%，收盘 -1.00%，属于标准假突破。

备选票平均收盘收益 -4.53%，说明“能不能成为备选”的门槛和“能不能进入真实交易”的门槛，当前系统还没有拉开。

#### 3. 观察票：历史命中率很高，但今天多数不适合隔夜执行

观察票里的 000338、300757 还有一定正向收益，但 000657、002491 都出现了盘中摸高后尾盘明显回落：

1. 000657 高点 +2.14%，收盘 -5.53%。
2. 002491 高点 +2.72%，收盘 -5.90%。

这类样本暴露的不是“不会突破”，而是“突破以后承接极差”。这正是当前 BTST 系统最需要补上的模型空白。

#### 4. 因子层高分票：有真强势，也有灾难性假强势

因子层 Top 票中：

1. 603890 收盘 +9.99%，全天强封。
2. 000889 收盘 +9.98%，全天强封。
3. 002787 收盘 +10.03%，低吸分支中最强。
4. 001299 高点一度 +3.02%，但收盘 -9.98%，属于极端尾盘踩踏。
5. 000586、300686 也都直接弱化。

这说明系统的根问题不是“完全找不到强票”，而是没有把“真突破”和“尾盘兑现失败的假突破”分开建模。

## 0415 暴露出的系统不足

### 一、现有市场状态机制是反应型，不是预测型

仓库里已经有市场状态模块：

1. `src/screening/market_state_helpers.py`
2. `src/screening/market_state.py`
3. `src/targets/short_trade_target_snapshot_relief_helpers.py`

现有机制已经会根据 `breadth_ratio`、`position_scale`、`limit_down_count` 对阈值做 risk-off 调整。但它的主要问题是：

1. 这些调整是在“已知当日市场状态”的前提下生效。
2. 04-14 夜里做 04-15 计划时，系统没有一个“隔夜 regime flip 预测层”。
3. 现有状态变量偏重全市场宽度，没有把上证、深证、创业板之间的风格裂口单独建模。

结论：当前系统有 market state，但没有 next-day regime forecast。

### 二、目标函数混在一起，导致“盘中摸高”和“收盘赚钱”被当成同一件事

04-15 的核心证据是：很多票盘中能给到 +2%，但收盘并不赚钱。

如果系统仍然把以下目标混在一起：

1. 次日盘中是否能冲高。
2. 次日收盘是否为正。
3. 次日收盘是否强于开盘。
4. 是否适合真正 BTST 隔夜持有。

那么它就会持续高估“有弹性但没承接”的票。

结论：当前短线目标需要从单一 continuation 逻辑，升级为双目标甚至三目标标签体系。

### 三、同票历史先验权重过高，容易过拟合

昨日文档对 001309 的论证里，强调了“同票历史 31 例、next_high≥2% 命中率 100%、next_close 正收益率 100%”。

这种信息有价值，但在高分化环境里有两个问题：

1. 同票样本很容易带来情境外推，忽略当前市场风格已经换挡。
2. 单票先验没有向“板块、阶段、突破类型、宽度分层”的簇先验收缩。
3. 备选票和观察票的真实今天表现，说明 same-ticker prior 不能直接映射为今日可交易概率。

结论：同票先验必须 shrink 到 cluster prior，而不是直接拿来决定实盘动作。

### 四、执行语义仍偏定性，缺乏量化入场闸门

当前系统里已经有：

1. `confirm_then_hold_breakout`
2. `breakout_confirm`
3. `prepared breakout relief`
4. `continuation execution overrides`

问题不在“有没有执行语义”，而在于这些语义还不够量化：

1. 没有把开盘竞价、前 5 分钟、前 15 分钟的承接质量写成可验证的量化条件。
2. 没有把“突破后回落到开盘价下方”定义成硬性撤销信号。
3. 没有把“高点 +2% 但收盘转负”的 breakout trap 直接写成反标签。

结论：执行层现在像规则描述，不像可统计学习的元模型。

### 五、暴露预算不够，容易被风格集中拖累

04-15 失败样本中，通信设备、专用机械、高弹性成长票占比很高。系统当前更像“按单票打分”，而不是“按组合暴露管理”。

缺口包括：

1. 没有主板 / 创业板 / 高波动风格暴露上限。
2. 没有题材簇或行业簇上限。
3. 没有在 risk-off 日自动降低高弹性分支仓位的动态资金分配器。

结论：当前系统还是票级最优，尚未升级到组合级最优。

### 六、备选票和观察票的置信度映射失真

04-15 这一天，主票至少没有造成大损失，但备选票平均 -4.53%，观察票平均 -2.38%。

这说明：

1. 主票、备选票、观察票之间的分层差异不够大。
2. score_target 和 confidence 还没有被校准成真实可比较的概率。
3. “可以观察”与“可以交易”之间的阈值还不够硬。

结论：必须做概率校准和分层仓位映射，不能只给定性标签。

### 七、事后归因维度还不够细

当前仓库已有大量 replay 和 validation 脚本，但 0415 这种日子还需要一个专门的失败归因板：

1. 哪些票是从开盘就弱。
2. 哪些票是盘中摸高后尾盘崩。
3. 哪些票是高开过多，不适合追。
4. 哪些票是因为风格切换被错杀。

没有这层归因，后续优化很容易又回到“继续扫阈值”的老路。

## 对标高收益超短量化系统后的最佳优化路线

### 核心判断

当前最优路线不是继续堆更多因子，也不是继续扫更多 frontier。最优路线是把 BTST 升级为一条四层联动链路：

1. `隔夜环境闸门（Regime Gate）`
2. `双目标标签（Breakout vs Close Retention）`
3. `执行元模型（Execution Meta-Label）`
4. `组合暴露预算（Exposure Budget）`

如果只能做一条主线，我建议把它定义为：

> 用“环境闸门 + 双目标标签 + 执行元模型”替代“单一延续分数 + 定性确认语义”。

### 一、Regime Gate：新增隔夜风格切换预测层

目标：在 04-14 夜里就识别出“04-15 不适合扩张执行”。

建议新增的预测特征：

1. 上证、深证、创业板、沪深 300 的相对强弱差。
2. 前一日强势票群的次日开盘承压概率。
3. 高弹性板块宽度与主板宽度的差值。
4. 涨停家数扩张但宽度恶化的“高分化预警”。
5. 北向资金方向与成长指数方向是否背离。

建议落点：

1. `src/screening/market_state_helpers.py`：扩充 state metrics。
2. `src/screening/market_state.py`：引入 board/style dispersion。
3. `src/targets/short_trade_target_snapshot_relief_helpers.py`：把 next-day regime score 接入阈值抬升逻辑。

这一步不是为了预测指数涨跌，而是为了回答：明天是“可以放大 breakout”的日子，还是“只保留主票、压缩备选和观察票”的日子。

### 二、Dual Label：把“会冲高”和“能收住”拆开建模

建议新增三组标签：

1. `y_breakout_hit`：次日盘中高点是否达到前收 +2%。
2. `y_close_positive`：次日收盘是否高于前收。
3. `y_breakout_trap`：次日曾达到 +2%，但收盘转负。

如果能拿到分钟级数据，再加一组：

1. `y_hold_above_vwap_15m`：突破后 15 分钟是否仍站在 VWAP 上方。

建议落点：

1. `src/targets/models.py`：补充标签与概率字段。
2. `src/targets/short_trade_target_signal_snapshot_helpers.py`：输出拆分后的 snapshot 指标。
3. `src/targets/short_trade_target_snapshot_relief_helpers.py`：新增 close retention score、trap penalty。
4. `src/targets/router.py`：用双目标概率决定 selected / near-miss / watch 的分层。

这一步能直接解决 0415 这种“很多票盘中有机会、尾盘不赚钱”的核心问题。

### 三、Execution Meta-Label：把 confirm 语义变成量化闸门

建议把当前 `confirm_then_hold_breakout` 和 `breakout_confirm`，落成明确的执行条件：

1. 开盘涨幅不超过阈值，例如 +2.5% 或 +3.0%。
2. 9:35 或前 15 分钟价格必须重新站上前收和开盘价。
3. 突破发生后，回落不能跌破 breakout anchor。
4. 若突破后 15 分钟内失守开盘价或 VWAP，直接撤销 BTST 隔夜资格。
5. 对 risk-off regime，下调备选票和观察票的确认容忍度。

建议落点：

1. `src/execution/daily_pipeline.py`：把 continuation overrides 扩展为 execution meta-label gate。
2. `src/targets/short_trade_prepared_breakout_helpers.py`：加入“准备突破”与“完成突破”的状态迁移。
3. `src/targets/short_trade_target_snapshot_relief_helpers.py`：把 prepared breakout 与 trap risk 合并进 snapshot。

这一步的价值在于：不是等交易员靠主观判断“看起来不太对”，而是让系统自动识别不该做隔夜的弱确认。

### 四、Exposure Budget：从票级最优升级为组合级最优

建议新增四条预算约束：

1. 高弹性板块总仓位上限。
2. 单行业簇上限。
3. 创业板 / 主板暴露平衡约束。
4. risk-off 日下，备选票和观察票总仓位上限。

建议落点：

1. `src/targets/router.py`：在 selection target 输出阶段附带 exposure bucket。
2. `src/execution/daily_pipeline.py`：在 buy order 构建阶段执行预算上限。
3. `src/research/artifacts.py`：把暴露预算结果写入 selection artifacts，方便复盘。

这一步可以直接降低“今天某个风格整体崩掉，组合一起受伤”的问题。

### 五、Confidence Calibration：把历史先验变成可用概率

建议把当前 `score_target`、`confidence` 和历史先验，改成经过校准的真实概率：

1. 同票样本只是局部先验。
2. 主导概率来自“行业 × breakout_stage × market_regime × candidate_source”的簇先验。
3. 用近 60 到 120 个交易日做 walk-forward 校准。
4. 让主票、备选、观察票的阈值建立在校准后概率，而不是原始分数上。
5. 对“31 例历史 100% 命中率”这类同票先验，先做 empirical Bayes 收缩，再参与分层与仓位映射。

建议落点：

1. `src/targets/short_trade_target_evaluation_helpers.py`
2. `src/targets/short_trade_target.py`
3. `scripts/analyze_btst_micro_window_regression.py`

这一步能直接修复“备选票分数看起来还行，实盘却持续负收益”的问题。

建议采用的第一版校准原则：

1. 用 Beta-Binomial 或 empirical Bayes 对 same-ticker hit rate 做收缩，避免小样本 100% 命中率造成过度自信。
2. 同票先验只作为局部修正项，不直接决定 `selected`。
3. 若同票样本小于 20，优先回落到 cluster prior，而不是继续放大单票历史。

### 六、Tail Behavior Features：把尾盘承接和缺口行为变成特征，而不是口号

glm5.1 文档里最值得吸收的补充，不是“弱市直接追高开”，而是提醒我们把尾盘承接和缺口行为做成 **regime-specific feature**。

应优先吸收的不是结论，而是下面这组三类特征：

1. 尾盘 14:30 到收盘的收益、放量、收盘相对日内高点的回撤。
2. 开盘缺口与市场状态的交互，例如 `open_gap × regime`。
3. 高开后前 5 分钟能否守住开盘价、前收和 VWAP。

这里要强调两条边界：

1. 04-15 单日确实出现了“弱市中高开票明显更强”的现象，但这只能作为条件化特征，不能直接升级成默认追高规则。
2. 第一版不必等待完整的分钟线基础设施，可以先用开盘缺口、上影线、收盘位置、日内高低回撤做代理特征。

建议落点：

1. `src/targets/short_trade_target_signal_snapshot_helpers.py`：新增 `late_day_return_proxy`、`close_from_high`、`open_gap_regime_interaction` 等特征。
2. `src/targets/short_trade_prepared_breakout_helpers.py`：把准备突破、完成突破、失败突破的状态迁移与缺口行为联动。
3. `src/execution/daily_pipeline.py`：在 execution gate 中增加“高开后承接失败即撤销 BTST 资格”的硬规则。
4. `scripts/analyze_btst_latest_close_validation.py`：新增尾盘承接和缺口行为的复盘摘要。

### 七、Residual Reversal：把弱市反转从经验判断变成条件化信号

glm5.1 文档关于“弱市里动量因子可能逆转、反转因子应增强”的方向有价值，但不能直接把纯价格反转提成新的默认主线。更稳妥的统一版做法是：

1. 只在 `risk_off` 或 `regime_flip` 预测日提升反转相关权重。
2. 优先做“残差反转”或“条件化反转”，尽量剔除市场和行业 Beta 后再计算。
3. 让反转分支主要服务于 `near_miss` 救援和 `low_absorb` 分支，而不是和主 breakout lane 混成一套规则。

建议落点：

1. `src/targets/short_trade_target_snapshot_relief_helpers.py`：增加条件化 `reversal_relief`，只在 risk-off 预测日启用。
2. `src/targets/router.py`：把反转信号限制在观察层和救援层，而不是直接扩张主入场票。
3. `scripts/analyze_btst_micro_window_regression.py`：按 `market_regime` 和 `candidate_source` 拆分反转表现。

### 八、重模型应放在研究支线，不应抢占当前主线

glm5.1 文档提到 HMM、Wasserstein 聚类、LightGBM、LSTM 混合模型，这些方向可以保留为长期研究支线，但不应替代当前最优主线。

当前统一版的取舍原则是：

1. P0 到 P2 只做能直接接进现有 BTST snapshot、router、pipeline 的轻量改动。
2. HMM、Wasserstein、LightGBM 只有在 walk-forward 证明明显优于当前轻量规则后，才考虑并入主链路。
3. 在此之前，重模型只能服务于验证和对照，不应直接接管实盘分层与执行。

## 最佳落地方案：按四个阶段推进

### P0：先修方向，不先扫更多阈值

周期：1 到 2 天

目标：用最小改动先防住 0415 这类日子的错误放大。

动作：

1. 在 `market_state_helpers.py` 增加 style dispersion 和 regime flip 风险分。
2. 在 `short_trade_target_snapshot_relief_helpers.py` 增加 `breakout_trap_risk`。
3. 在 `router.py` 中对 risk-off 预测日直接压缩备选和观察票数量。
4. 在 `daily_pipeline.py` 中给备选票加硬性执行闸门，不满足确认直接空仓。

验收：

1. risk-off 日不再出现“主票正常、备选票平均大幅亏损”的放大结构。
2. 备选票平均收盘收益显著改善。

### P1：把标签拆开，结束“盘中摸高=隔夜合格”的混用

周期：3 到 5 天

目标：建立 BTST 的双目标标签体系。

动作：

1. 新增 `breakout_hit`、`close_positive`、`breakout_trap` 标签。
2. 在 snapshot 中同时保存 `breakout_probability` 和 `close_retention_probability`。
3. 让 selected 主要依赖 `close_retention_probability`，让 near-miss / watch 主要承接 breakout 机会。
4. 补充尾盘承接、收盘相对高点回撤、开盘缺口与 regime 交互等轻量特征。

验收：

1. 盘中有冲高但收盘为负的样本，不再大面积进入 selected / backup。
2. 因子层 Top 票的中位收盘收益明显改善。

### P2：把执行语义变成量化元模型

周期：1 到 2 周

目标：让“确认后买入”真正可统计、可复盘、可自动化。

动作：

1. 增加竞价、前 5 分钟、前 15 分钟、VWAP 保持等执行特征。
2. 对每个执行模式输出 `can_enter_now`、`must_wait_retest`、`abort_after_failed_breakout`。
3. 在 `daily_pipeline.py` 中把语义性执行建议改成硬规则。
4. 对 same-ticker 历史命中率做 empirical Bayes 收缩，再决定主票、备选票、观察票的概率阈值。
5. 为 risk-off 日增加条件化 residual reversal 分支，但只允许服务观察层和救援层。

验收：

1. breakout trap 数量下降。
2. “确认后持有”样本的收盘兑现率提升。

### P3：把置信度、暴露和复盘串成完整闭环

周期：2 到 4 周

目标：从单票择时系统，升级成可持续优化的短线组合系统。

动作：

1. 做 regime-bucket 概率校准。
2. 做行业 / 板块 / 波动风格预算。
3. 新增 breakout trap board、regime mismatch board、confidence calibration board。
4. 把这些结果接回 nightly control tower。
5. 只有在轻量特征链路跑通后，再评估 HMM、Wasserstein 或 LightGBM 是否值得进入研究支线。

验收：

1. 系统能解释为什么今天只保留主票，为什么今天压缩观察票。
2. 研究员不再需要靠人工回忆失败案例做归因。

## 需要修改和新增的模块建议

| 模块 | 现状 | 建议优化 |
| --- | --- | --- |
| `src/screening/market_state_helpers.py` | 有 breadth 和基础 regime 调整 | 增加风格裂口、宽度恶化、涨停分化、隔夜 regime flip 预测因子 |
| `src/screening/market_state.py` | 市场状态构建入口 | 输出 board/style dispersion 状态 |
| `src/targets/short_trade_target_signal_snapshot_helpers.py` | 已有 snapshot 辅助层 | 增加尾盘承接、收盘相对高点回撤、缺口与 regime 交互特征 |
| `src/targets/short_trade_target_snapshot_relief_helpers.py` | 有 threshold lift 和 relief 逻辑 | 增加 breakout trap risk、close retention score |
| `src/targets/router.py` | 负责 selected / near-miss / short_trade_only 分层 | 用双目标概率和 exposure budget 重写分层规则 |
| `src/targets/short_trade_target_evaluation_helpers.py` | 已有 target evaluation 辅助层 | 引入 empirical Bayes 先验收缩和 cluster prior 校准 |
| `src/execution/daily_pipeline.py` | 有 continuation overrides，但执行语义仍偏描述性 | 增加量化入场闸门和失败突破撤销逻辑 |
| `src/research/artifacts.py` | 已有 replay input 和 selection artifacts | 持久化 breakout trap、regime gate、exposure bucket |
| `scripts/analyze_btst_latest_close_validation.py` | 更像收盘总结 | 增加 breakout trap 和 regime mismatch 专栏 |
| `scripts/analyze_btst_micro_window_regression.py` | 已有窗口回归框架 | 按 regime bucket 和标签拆分做回归 |

建议新增三个脚本：

1. `scripts/analyze_btst_breakout_trap_board.py`
2. `scripts/analyze_btst_regime_flip_validation.py`
3. `scripts/analyze_btst_tail_behavior_board.py`

## 验收指标

不能只看“有没有抓到涨停”，必须看交易系统最在意的四个指标：

| 指标 | 0415 基线 | 优化目标 |
| --- | --- | --- |
| 备选票平均收盘收益 | -4.53% | 提升到不低于 -0.50%，并最终转正 |
| 观察票平均收盘收益 | -2.38% | 提升到不低于 -0.50% |
| `high_hit_2pct` 后转负的假突破率 | 约 33% | 压到 15% 到 20% 以下 |
| 因子层 Top 票中位收盘收益 | -0.10% | 提升到正值并稳定高于 0 |
| risk-off 日备选 / 观察票数量 | 当前偏多 | 至少压缩 30% 到 50% |
| 单一风格 / 行业簇集中暴露 | 当前无硬约束 | 设置明确上限并写入 artifacts |

注意：验收必须做 walk-forward，不接受只在单日或少数个股上讲故事。

## 本轮最不该做的四件事

1. 不要继续只做 threshold 或 penalty 微调。
2. 不要把单日“高开票更强”的现象直接翻译成默认追高规则。
3. 不要继续把 same-ticker 100% 历史命中率当成最强证据。
4. 不要跳过现有轻量链路，直接把 HMM、Wasserstein、LightGBM 接成主交易引擎。

## 推荐的下一步动作顺序

1. 先做 P0，把 regime gate 和 breakout trap risk 接进现有 snapshot 与 router。
2. 再做 P1，把 `next_high` 和 `next_close` 分成两个目标，不再混用，并补进尾盘承接和缺口交互特征。
3. 然后做 P2，把确认语义变成前 5 分钟 / 前 15 分钟可执行规则，并加入 same-ticker 历史先验的贝叶斯收缩。
4. 最后做 P3，把概率校准、组合预算和研究支线验证接进 nightly control tower。

## 结论

04-15 这次复盘说明，当前 BTST 系统已经能抓到一部分强势票，但它仍然把“有盘中弹性”误当成了“适合 BTST 隔夜持有”。

因此，最佳优化方向不是继续堆更多择股因子，也不是继续堆更多 LLM 提示词，而是把系统升级为：

1. 能识别隔夜风格切换的环境闸门。
2. 能区分“冲高概率”和“收盘承接概率”的双目标模型。
3. 能把确认语义量化的执行元模型。
4. 能限制风格集中和边界样本风险放大的组合预算系统。

只要这四层补齐，BTST 才会从“会找热点票”真正升级为“会做可兑现隔夜交易”的系统。
