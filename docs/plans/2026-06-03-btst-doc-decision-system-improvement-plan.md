# BTST 文档、决策卡、系统与 Skill 优化计划

> 这份文档不讨论“再多给几只票”，而是讨论怎样把 BTST 这套系统变得更顺手、更可信、更少误导，并最终提高胜率稳定性和盈亏比质量。

## 学习目标

读完这份文档后，团队应该能回答 4 个问题：

1. 当前 BTST 文档包和决策卡，最影响使用体验的短板到底是什么。
2. 哪些问题只是文案层问题，哪些问题已经影响到实际交易判断。
3. 系统和 skill 应该优先改哪几处，才能最快提升“易用性 + 赚钱能力”。
4. 接下来 1 周、2 周、1 个月分别应该推进什么。

## 先给判断

当前 BTST 体系已经不缺“能不能生成文档”，真正缺的是下面 3 件事：

1. **把多份 artifact 压缩成一个真正可判断的执行结论。**
2. **让 conservative / aggressive 的比较不再停留在计数层，而是真正反映执行差异和历史收益差异。**
3. **把“freshness”“actionability”“profitability”三件事拆开写清楚，避免读者把 `exact` 误读成“今天就该打”。**

如果只从 `20260602` 这次产物看，系统已经能跑出完整文档包，但也暴露出一个很明确的事实：  
**生成能力已经足够，决策压缩层和反馈闭环还不够强。**

## 当前系统地图

| 层 | 当前入口 | 当前作用 | 主要短板 |
| --- | --- | --- | --- |
| 规则版主线 | `scripts/btst_full_report.py` | 给出规则筛选、市场状态和高确信候选 | 与最终执行结论的桥接仍偏弱 |
| 多智能体主线 | `scripts/run_paper_trading.py` | 给出 `short_trade_only` 候选、门控、执行约束 | 信息完整，但阅读成本偏高 |
| 文档包生成 | `scripts/generate_btst_doc_bundle.py` | 把规则版、多智能体、early-runner 写成 5+2 份文档 | 文档职责有重叠，profile compare 解释层偏浅 |
| 决策压缩 | profile compare + pretrade decision card | 在 `conservative / aggressive` 间做选择 | 目前只比较 3 个计数，不足以支撑“今天该偏哪边” |
| early-runner 叠加 | `btst_early_runner_v1_latest.*` + 日表 | 提供交集票、补充票、second-entry | freshness 和 actionability 容易被混读 |
| Skill 编排 | `ai-hedge-fund-btst` | 组织运行顺序、目录、回复口径 | 用户体验已经成型，但还可以再自动化一层 |

## 20260602 这次运行暴露出的具体问题

### 1. 决策卡过于“轻”，不足以承担真正的执行裁决

这次生成的决策卡只有 5 行有效信息：

- 推荐 profile：`conservative`
- 执行倾向：`偏保守执行`
- early-runner 状态：`exact`
- 交集票 / only early-runner / second-entry 全部为 `0`
- 推荐理由：两套 profile 没有有效差异，默认保守

这张卡有一个明显问题：  
**它能表达“今天偏保守”，但不能表达“为什么今天其实更重要的是先不交易或只做确认复核”。**

而同一天的多智能体主线已经给出更强的交易约束：

- `regime_gate_level=crisis`
- `gate=halt`
- `buy_orders_cleared=False`
- `report_mode=confirmation_review_only`

也就是说，这一天真正的最高优先级不是“保守 vs 激进”，而是：

> 市场门控已经把日内动作降级为“09:25 后确认复核；若承接和宽度不修复，则不执行”。

当前决策卡没有把这个结论提到第一层，会让读者误以为 profile 选择才是当天的核心分歧。

### 2. profile 对照现在太浅，容易做成“有跑等于有比较”

`conservative` 和 `aggressive` 目前确实来自两套不同配置文件：

- `config/btst_strategy_thresholds.json`
- `config/btst_strategy_thresholds_aggressive.json`

两者一共 **29 个阈值全部不同**，但当前 profile compare 文档只展示下面这些字段：

- `intersection_count`
- `only_early_runner_count`
- `second_entry_count`
- `written_file_count`
- `output_dir`

这会带来两个问题：

1. **即使阈值差异很大，只要 3 个计数相同，文档就会看起来像“今天两套 profile 完全一样”。**
2. **读者看不到“阈值差异具体把哪些票从正式层打回观察层，或从观察层放进回补层”。**

所以现在的 profile compare 更像“对输出计数做比较”，还不是“对交易影响做比较”。

### 3. `exact` 现在只表示“时间对齐”，不等于“今天有增量价值”

这次 early-runner 状态是 `exact`，但同一天文档里还出现了下面的信息：

- `deployment_mode=research_only`
- `gate_action=research_only`
- `watchlist 数量=0`
- `priority 数量=0`
- `second_entry 数量=0`
- 与正式 BTST 的重合票：`无`
- only early-runner：`无`

这意味着：

- **板子是当日的**，所以 freshness 没问题。
- **但它没有产出当日可行动的增量信息**。

当前文档虽然把这些信息都写出来了，但没有在最上层明确告诉读者：

> 今天是 `exact`，但 `exact` 只说明“板子新”，不说明“今天多出来了值得动手的票”。

这会影响使用体验，也会影响对 early-runner 价值的长期判断。

### 4. 顶层主文档与 profile compare 的桥接存在系统缺口

这次实际运行里，profile compare 脚本只把“今日执行倾向”桥接进了：

- `outputs/202606/20260602_profile_compare/conservative/BTST-20260602.md`
- `outputs/202606/20260602_profile_compare/aggressive/BTST-20260602.md`

却**没有自动桥接回顶层正式交付文档**：

- `outputs/202606/20260602/BTST-20260602.md`
- `outputs/202606/20260602/BTST-LLM-20260602.md`

这次是靠手工补写才保持了文档和最终回答同口径。  
这不是文案问题，而是一个明确的系统 bug / 流程缺口。

### 5. 文档已经完整，但还不够“低延迟决策”

当前 7 份文档的内容已经比较完整，但盘前真正高频使用时，读者最想回答的是 5 个问题：

1. 今天到底能不能做。
2. 如果能做，是“直接做”还是“等确认再做”。
3. 主票是谁，什么条件下取消。
4. early-runner 今天有没有提供增量 alpha。
5. conservative 和 aggressive 的分歧，究竟落在什么地方。

这 5 个问题散落在：

- `BTST-LLM`
- `EXEC-CHECKLIST`
- 决策卡
- profile compare
- early-runner 章节

现在还需要读者自己再压缩一遍。系统还没有把“压缩后的结论”做成默认产物。

## 一个真实任务流案例：20260602 这次系统是怎么跑完的

这次运行的真实链路大致是这样：

1. `btst_full_report.py` 先产出规则版报告，给出 228 只高确信标的和市场中性偏弱判断。
2. `run_paper_trading.py` 跑出 `short_trade_only + momentum_optimized` 的多智能体结果，主票是 `002463 沪电股份`。
3. `session_summary.json` 证明这次是 **optimized run**，不是 fallback。
4. early-runner 日表刷新成功，状态是 `exact`，但当日没有交集票、没有 only early-runner、没有 second-entry。
5. `generate_btst_doc_bundle.py` 生成顶层 7 份文档，同时把多智能体结论压缩为 `confirmation_review_only`。
6. `--compare-profiles conservative aggressive` 又额外生成两套 profile 子目录、对照文档和决策卡。
7. 但 compare 结果没有自动回写顶层主文档，只能人工补桥。

这条链路说明两件事：

1. **系统已经具备完整的 artifact 生产能力。**
2. **真正还没打通的是最后 10% 的“决策压缩 + 自动桥接 + 反馈闭环”。**

## 优化方向一：先把文档做成真正分工明确的产品

### 目标

不是继续堆细节，而是让每份文档都回答一个唯一问题。

### 建议

#### 1. 给 7 份文档重新定义唯一职责

| 文件 | 保留定位 | 应该强化什么 | 应该弱化什么 |
| --- | --- | --- | --- |
| `BTST-LLM` | 完整执行主线 | 正式执行层、门控、正式观察层、执行 guardrail | 不再重复解释太多“为什么偏保守” |
| `EXEC-CHECKLIST` | 次日盘前动作单 | 时间轴、触发条件、取消条件、仓位约束 | 弱化长篇背景解释 |
| `BTST` | 规则底稿 | 规则版市场状态、规则侧主候选 | 不承担 profile 裁决 |
| `通俗说明` | 快速理解版 | 今天为什么这样分层、什么能做、什么不能做 | 不重复列出所有指标 |
| `论坛短版` | 对外发布版 | 一句话结论、交易/观察边界 | 不承载细节 |
| `EARLY-WARNING` | 补充观察池 | only early-runner、second-entry、研究确认池 | 不和正式主票混写 |
| `EARLY-WARNING-CARD` | 超短摘要 | 今天 early-runner 是否有增量价值 | 不再堆完整明细 |

#### 2. 新增一份“一页盘前总卡”

建议增加：

```text
BTST-YYYYMMDD-ONE-PAGER.md
```

它只回答下面 8 行：

1. 今天是否允许交易。
2. 当天执行模式：`正常 / 确认复核 / 观望 / no-trade`。
3. 推荐 profile。
4. 主票 1-2 只。
5. 第一取消条件。
6. early-runner 是否有增量价值。
7. 交集票是否存在。
8. only early-runner / second-entry 是否值得花时间看。

这份文档不会替代现有 7 份文档，但会显著降低盘前阅读成本。

#### 3. 顶层统一引入“状态分层语义”

建议把顶部状态拆成 3 组，不再混写：

| 维度 | 例子 | 含义 |
| --- | --- | --- |
| Freshness | `exact / stale_fallback / unavailable` | 数据是不是当日的 |
| Actionability | `research_only / confirmation_only / executable` | 今天能不能把它变成执行动作 |
| Market gate | `normal / caution / halt / no-trade` | 市场是否允许出手 |

这样一来，读者不会再把 `exact` 理解成“今天就有明确可打的交集票”。

## 优化方向二：把决策卡从“计数卡”升级成“裁决卡”

### 当前问题

当前决策卡的推荐逻辑，只比较 3 个数字：

- 交集票数量
- only early-runner 数量
- second-entry 数量

这套逻辑过于单薄，至少漏掉了 6 类真正会影响交易结果的因素：

1. 正式执行层候选是否不同。
2. 观察层是否被不同 profile 明显收缩。
3. 市场门控是否已经压过 profile 差异。
4. 主票的历史胜率、盈亏比、样本稳健性是否不同。
5. risk budget / gate / contract 是否不同。
6. 历史上类似日型下，哪套 profile 的 realized outcome 更好。

### 决策卡 V2 应该长什么样

建议把决策卡升级成下面这套结构：

#### A. 最上层只保留一句执行裁决

- 今日动作：`no-trade / confirmation_review_only / conservative / aggressive`

注意，这里要允许出现 **不是 profile 名称** 的结论。  
例如像 `20260602` 这种 `crisis + halt` 日，就更应该直接写：

> 今日动作：`confirmation_review_only`

profile 选择可以退居第二层，而不是抢第一标题。

#### B. 第二层写“为什么不是另一边”

固定回答 4 个问题：

1. conservative 和 aggressive 的正式执行层差异是什么。
2. 哪一套带来的交集票更有价值。
3. 哪一套带来的 only early-runner 噪音更大。
4. 哪一套带来的 second-entry 干扰更大。

#### C. 第三层写“今天最重要的 3 个数字”

建议至少保留：

- formal selected count
- actionable selected count
- top candidate expected edge

如果是门控日，再加：

- gate level
- buy_orders_cleared
- position_scale

#### D. 第四层给“历史校准提示”

例如：

- 近 20 个类似 `halt / confirmation_only` 日里，执行 vs 不执行的差异
- 近 20 个“无交集票”日里，conservative 与 aggressive 的 realized outcome 对比

这样决策卡才不是静态说明，而是带有历史证据的裁决卡。

### 决策卡必须增加一个新字段：`dominant_reason_type`

当前 skill 强调要回答理由来自哪一项：

- 交集票
- only early-runner
- second-entry

但实际系统里还存在一个更常见的第四类原因：

- `no_effective_profile_diff`

以及一个第五类更重要的原因：

- `market_gate_override`

所以建议把字段正式扩展为：

```text
dominant_reason_type =
  intersection_advantage |
  only_early_runner_pressure |
  second_entry_interference |
  no_effective_profile_diff |
  market_gate_override
```

这能明显减少最终回复和文档里“明明是门控问题，却硬说成 profile 问题”的情况。

## 优化方向三：把 profile compare 从“结果计数”升级成“交易影响解释器”

### 当前最大问题

现在 compare 文档告诉你：

- 两套 profile 各有多少交集票
- 各有多少 only early-runner
- 各有多少 second-entry

但它没有告诉你：

- 哪些票发生了层级迁移。
- 为什么迁移。
- 这些迁移会不会改变主执行顺序。
- 这些迁移在历史上有没有提升收益质量。

### 建议新增“差异明细表”

| 股票 | conservative 层级 | aggressive 层级 | 变化原因 | 是否影响执行顺序 |
| --- | --- | --- | --- | --- |
| 002463 沪电股份 | 正式执行 | 正式执行 | 无 | 否 |
| 300308 中际旭创 | 观察层 | 正式观察前排 | threshold 放宽 | 可能 |

当日如果没有变化，也应该明确写：

> 今天两套 profile 在正式执行层、正式观察层、交集层和回补层都没有层级迁移，比较结果只剩默认 tie-break，不足以支持激进切换。

### 建议新增“历史胜率/赔率差异摘要”

profile compare 不应该只比当日结构，还应该顺手给出一个轻量历史摘要：

- 近 20 日 conservative 的 formal selected 胜率
- 近 20 日 aggressive 的 formal selected 胜率
- 近 20 日 conservative 的平均盈亏比
- 近 20 日 aggressive 的平均盈亏比
- 近 20 日 conservative 的 no-trade precision
- 近 20 日 aggressive 的 no-trade precision

这样 profile 选择才会从“今天谁多 1 张票”升级为“这套风格在最近这类环境里值不值得偏过去”。

## 优化方向四：把系统做成一个真正的“盘前控制台”

### 1. 提供一个统一入口，减少手工串脚本

现在完整流程至少涉及：

1. `btst_full_report.py`
2. `run_paper_trading.py`
3. `analyze_btst_early_runner_v1.py`
4. `generate_btst_early_runner_daily_tables.py`
5. `generate_btst_doc_bundle.py`
6. `generate_btst_doc_bundle.py --compare-profiles ...`

这条链路已经稳定，但还不够省心。建议新增统一入口，例如：

```bash
uv run python scripts/run_btst_next_day_package.py \
  --signal-date YYYYMMDD \
  --with-profile-compare \
  --default-output
```

统一入口至少做 5 件事：

1. 自动检查收盘数据可用性。
2. 自动串起规则版、多智能体、early-runner、文档包、profile compare。
3. 自动校验所有文件是否存在。
4. 自动桥接“今日执行倾向”到顶层文档。
5. 自动产出一个 `operator_summary.json`。

### 2. 新增 `operator_summary.json`

建议在每次完整运行后写一个统一摘要：

```json
{
  "signal_date": "20260602",
  "next_trade_date": "2026-06-03",
  "market_gate": "halt",
  "action_mode": "confirmation_review_only",
  "recommended_profile": "conservative",
  "dominant_reason_type": "market_gate_override",
  "top_formal_tickers": ["002463"],
  "early_runner_freshness": "exact",
  "early_runner_actionability": "research_only",
  "intersection_count": 0,
  "only_early_runner_count": 0,
  "second_entry_count": 0,
  "manual_patch_required": false
}
```

这会极大降低下游读取成本。skill、回复模板、日报脚本、回测校准脚本都可以直接消费它。

### 3. 修掉“compare 只桥接子目录，不桥接顶层主文档”的问题

这是最明确、回报也最高的 P0 级修复项。  
因为它现在已经造成：

- 最终回复和主文档可能不同口径
- 需要手工补写
- 自动化闭环不完整

### 4. 把 `exact` 和 `research_only` 分开写进所有摘要产物

当前很多地方只写 `early_runner_status=exact`。  
建议以后统一输出两组字段：

- `early_runner_freshness_status`
- `early_runner_actionability_status`

这会让“今天 exact，但其实只是 research-only”这种情况一眼可见。

## 优化方向五：想更能赚钱，优先改这 5 个杠杆

真正会拉高收益质量的，不是文档写得更漂亮，而是下面 5 个杠杆。

### 1. 提高 no-trade / confirmation-only 的正确率

很多日子的最大 alpha，不是“买哪只”，而是“今天别乱买”。  
像 `20260602` 这种 `crisis + halt` 日，如果系统能稳定地把错误出手拦下来，对收益曲线的改善往往比多抓一只强票更大。

**优先级：最高。**

### 2. 让 profile 选择基于历史 realized edge，而不是只基于计数

现在 conservative / aggressive 的裁决更像结构比较，不是收益比较。  
建议建立“同类日型下 profile realized outcome”面板，把下面这些做成默认特征：

- 市场 gate
- breadth
- selected count
- top1 / top3 historical edge
- overlap presence
- only early-runner noise
- second-entry load

然后再决定到底偏 conservative 还是 aggressive。

### 3. 给正式执行层增加“样本稳健性折扣”

像 `002463 沪电股份` 这次样本只有 `9`，虽然胜率 `66.67%`、盈亏比 `1.93`，但 Wilson 区间仍然较宽。  
建议把“样本少但看起来很美”的票再做一层统一折扣，减少偶然样本把主票顶得过高。

### 4. 把 only early-runner 从“补充名单”升级成“噪音受控研究池”

当前 only early-runner 的定位是对的，但还缺一个长期问题：

> 它们到底是在提供提前线索，还是只是在增加注意力噪音？

建议每月固定统计：

- only early-runner 次日正收益率
- only early-runner 3 日、5 日延续率
- only early-runner 被后来正式 BTST 捕捉到的比例

如果它长期仍然主要是噪音，就应该继续限制它，而不是给它更多展示面积。

### 5. 把 second-entry 从“展示层”升级成“独立策略层”

`second_entry_reentry` 的逻辑和首发主票不同。  
建议单独跟踪它的：

- T+1 / T+2 优势
- 对应日型
- 需要的盘口确认强度
- 单独仓位建议

这样它才不会只是“一个补充栏位”，而会变成真正有价值的回补机会层。

## 对 skill 的具体改进建议

### 1. skill 应默认区分“生成 compare”与“生成有意义的 compare”

当前只要用户要求，就会生成 profile compare。  
建议 skill 在最终回复里固定补一句：

- 是否存在**有效执行分歧**
- 如果没有，有效结论是“保守基线 + 门控优先”，而不是仅仅“推荐 conservative”

### 2. skill 应自动输出“今天最重要的不是 profile，而是 gate”这类顶层判断

当以下任一条件满足时：

- `gate=halt`
- `buy_orders_cleared=false`
- `report_mode=confirmation_review_only`

最终摘要的第一句应该优先写 market gate 结论，而不是 profile 结论。

### 3. skill 应把“手工干预”压缩到零

理想状态下，skill 不该再依赖人工：

- 手工补桥
- 手工判断是否该写 conservative
- 手工解释 `exact` 但无增量票

这些都应该由脚本产物自己给出来。

### 4. skill 应在最终回复里固定输出“今天有没有增量 alpha”

建议固定加一行：

- `early-runner 增量价值：有 / 无 / 仅研究价值`

这比单写 `exact` 更有用。

## 建议的实施顺序

## P0：1 到 3 天内完成

目标：先修最影响体验和口径一致性的地方。

1. 修复 profile compare 结果未自动桥接顶层主文档的问题。
2. 给决策卡增加 `dominant_reason_type`。
3. 给决策卡增加 `market_gate_override` / `no_effective_profile_diff` 两种原因类型。
4. 在所有摘要产物里拆分 `freshness` 和 `actionability`。
5. 新增 `operator_summary.json`。

## P1：1 到 2 周内完成

目标：把 compare 和 decision card 变成真正能辅助赚钱的组件。

1. 为 profile compare 增加“层级迁移明细表”。
2. 为决策卡增加 formal selected、actionable selected、risk budget 差异。
3. 接入近 20 日 realized outcome 校准摘要。
4. 新增 `BTST-YYYYMMDD-ONE-PAGER.md`。
5. 新增统一入口脚本 `run_btst_next_day_package.py`。

## P2：2 到 4 周内完成

目标：把系统从“日报生成器”升级成“可闭环优化的盘前决策系统”。

1. 建立 decision card 推荐结果的月度胜率/盈亏比归因面板。
2. 建立 conservative / aggressive 在不同 gate 日型下的 outcome 校准。
3. 建立 only early-runner 噪音率监控。
4. 建立 second-entry 独立回补策略评估。
5. 把“是否不交易”纳入正式策略优化目标，而不只是把“选出哪只票”当目标。

## 验收指标

优化完成后，至少看下面这些指标是否改善：

| 指标 | 目标 |
| --- | --- |
| 文档生成后手工修补次数 | 降到接近 0 |
| 顶层回复与主文档口径冲突次数 | 降到 0 |
| 盘前阅读时间 | 明显缩短 |
| no-trade / confirmation-only 日错误出手率 | 明显下降 |
| profile compare 出现“有意义差异”的可解释率 | 明显上升 |
| 决策卡与历史更优 outcome 的一致率 | 持续提升 |
| only early-runner 噪音率 | 可被量化并持续受控 |

## 最后一句判断

现在这套 BTST 系统最该做的，不是继续加更多候选和更多文档，而是把最后一层“裁决压缩、门控优先、历史校准、自动桥接”补齐。  
只要这几步补上，系统会同时变得更易用，也更接近真正能稳定赚钱的形态。
