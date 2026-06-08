# BTST 因子优化 90 轮进展复盘：哪些成果真正进入了报告与选股

适用对象：想系统复盘 BTST 因子挖掘进展、判断哪些优化已经进入运行时、哪些还停留在离线验证层，并据此审阅后续 BTST 报告的开发者、研究者、复盘人员。

这份文档解决的问题：

1. 我们这 90 轮因子优化，实质上推进了什么。
2. 这些因子是否都被 `ai-hedge-fund-btst` skill 生成报告时用到了。
3. 真正进入报告与选股链路的，是哪些因子、阈值、门控和护栏。
4. 这些工作到底带来了什么效果，是否已经显著提高了选股胜率。

---

## 1. 先说结论

如果只看最核心结论，可以先记这 8 条：

1. 这 90 轮工作的本质，不是“连续 90 次都在给 runtime 增加新因子”，而是 **核心打分因子、派生交互因子、运行时护栏、离线验证指标** 四层一起演进。
2. 仓内当前能直接追溯到的 round 记录，主要覆盖 **Round 4–89 的提交**，以及一份把 **Round 69–90** 汇总到一起的阶段总结；所以“90 轮”是整体项目口径，而不是每一轮都能在当前仓里用同一种形式逐条对齐。[`git log` Round 统计；`data/reports/btst_react_20260421_prepared_breakout_balance_summary.md:2172-2247`]
3. 进入 `ai-hedge-fund-btst` skill 报告链路的，只是这 90 轮成果中的 **运行时子集**：当前生效 profile 的权重、阈值、rank cap、gate、historical prior 解释和报告渲染字段，而不是所有离线诊断指标。[`src/paper_trading/optimized_profile_resolution.py:22-162`; `src/execution/daily_pipeline.py:1400-1469`; `src/research/review_renderer.py:36-117`]
4. 截至 `2026-05-13` 这次 BTST 报告，系统确实已经使用了 **optimized profile**，但用的是 **`btst_precision_v2` + overrides**，不是 Round 89 新增的 `trend_corrected_v1`。[`data/reports/paper_trading_20260512_20260512_live_m2_7_short_trade_only_20260513_plan_optimized_verify/session_summary.json:342-362`; `outputs/202605/20260513/BTST-LLM-20260512.md:29-49`]
5. 这意味着：**不是所有 90 轮因子成果都已经进入这次 skill 生成的报告。** 特别是 Round 89 的“反转因子翻转为趋势延续因子”修正，当时仍处于新 profile/新网格验证阶段，尚未成为那次报告的正式发布口径。[`src/targets/short_trade_target_profile_data.py:1279-1395`; `data/reports/btst_latest_optimized_profile.md:60-93`]
6. 已经进入运行时的优化，确实带来了 **排序重排、观察层重构、弱样本剔除、阈值与 rank cap 更精细化** 等效果；但它们带来的收益，更多体现在“更会排、会筛、会保守治理”，而不是“简单把更多股票抬进主交易层”。[`outputs/202605/20260513/BTST-LLM-20260512.md:25-28,60-61,125-130`]
7. 从仓内证据看，某些 profile 和某些窗口里，优化工作确实带来了 **局部胜率/收益改善**，例如 `momentum_tuned` 20 天回测显示日均收益 `+0.20%`、胜率 `48%`，优于默认 profile 的 `+0.11%`、`46%`。[`src/targets/short_trade_target_profile_data.py:1153-1163`; `data/reports/btst_react_20260421_prepared_breakout_balance_summary.md:2237-2246`]
8. 但如果问“这些工作是否已经稳定提高了整体选股胜率”，更准确的回答是：**有局部提升，但还没有足够强的仓内证据支持‘已经稳定显著提高整体 BTST 胜率’这个更强表述。** 多窗口验证和 rollout 结论仍偏保守。[`data/reports/btst_multi_window_profile_validation_20260406.md:31-36`; `data/reports/btst_latest_optimized_profile.md:60-93`]

---

## 2. 证据范围与口径

这份复盘主要基于 4 类证据：

1. **代码与配置**：当前运行时如何定义 profile、如何算分、如何 gate、如何渲染报告。  
   重点文件：`src/targets/`, `src/execution/`, `src/research/`, `src/paper_trading/`, `scripts/optimize_profile.py`。
2. **阶段性总结与实验报告**：尤其是 `data/reports/` 下的 profile validation、robustness decision、prepared breakout balance 总结等。
3. **实际 BTST skill 产物**：以 `outputs/202605/20260513/BTST-LLM-20260512.md` 和对应 `session_summary.json` 为代表。
4. **git round 提交轨迹**：当前仓内可见的 Round commit 覆盖 `4–89`，并且有一份明确写到 `Round 90` 最终状态的阶段总结。[`data/reports/btst_react_20260421_prepared_breakout_balance_summary.md:2220-2247`]

需要特别注意两个限制：

1. 当前仓内 **不是每一轮都以完全统一的方式保留**；有的体现在 commit message，有的体现在 summary 文档，有的体现在代码注释。
2. “被优化过” 不等于 “已经在当天 runtime 生效”；很多 round 的成果只进入了离线评价层，还没有通过 manifest 发布到正式报告链路。

---

## 3. 这 90 轮因子优化，本质上推进了什么

### 3.1 第一阶段：先把 BTST 的核心原语搭起来

这部分大体覆盖早期 round，核心目标是先让系统具备“能描述 BTST 机会结构”的基础变量，而不是一开始就追求极细的调参。

较早进入体系的核心变量包括：

1. `breakout_freshness`
2. `trend_acceleration`
3. `volume_expansion_quality`
4. `catalyst_freshness`
5. `close_strength`
6. `volatility_regime`
7. `sector_resonance`

随后又补进了一批更 BTST 化的日内与派生变量：

1. `t0_estimated_net_inflow_ratio`
2. `volume_price_divergence_score`
3. `t0_tail_strength`
4. `momentum_confirmation_score`
5. `volume_momentum_score`
6. `rs_sector_rank`

这些因子后来集中体现在 `BTST_FACTOR_NAMES` 与 IC 计算链路中，说明系统已经不是“拍脑袋看几个分数”，而是建立起了较完整的因子宇宙与前瞻收益相关性检验框架。[`scripts/btst_analysis_utils.py:13-46,132-152`]

与此同时，优化器也开始引入：

1. **时间衰减**：旧窗口样本按半衰期衰减，避免早期市场状态主导结论。[`scripts/optimize_profile.py:40-49`]
2. **IC 质量 guardrail**：如果有效正 IC 因子占比不够，就对试验结果降权或限制升级。[`scripts/optimize_profile.py:54-88`]
3. **多 horizon 指标**：T+1、T+2、T+3 一起看，避免只追某一个单日结果。[`scripts/optimize_profile.py:117-139`]

换句话说，前期工作的成果不是“某一个神因子”，而是把 **BTST 因子研究从单一打分推进成一个可验证的多因子框架**。

### 3.2 第二阶段：从“会打分”升级为“会诊断因子是否靠谱”

中期最关键的变化，是把大量诊断维度纳入 `scripts/optimize_profile.py` 的比较指标集合。这里不只是比较收益，还系统性地比较：

1. IC 与 IC 稳定性
2. 参数漂移
3. 过拟合风险
4. PCA 多样性
5. 因子冗余度
6. tail risk 与 drawdown
7. calibration / monotonicity / significance
8. 跨窗趋势是否恶化

从代码上看，这一层的扩张非常明显：`COMPARISON_METRICS` 从基础收益、胜率、coverage、liquidity，逐步扩展到了 `pca_diversity_score`、`overfit_score`、`param_drift_score`、`score_cv_across_windows`、`tail_risk_asymmetry`、`right_tail_dominance`、`win_rate_ci_width`、`factor_drift_score` 等大量诊断指标。[`scripts/optimize_profile.py:117-258,280-606`]

这说明 90 轮里相当大的一部分，不是在“给 runtime 再多加一个打分项”，而是在回答更难的问题：

1. 这个因子有没有预测力？
2. 它的预测力是不是只在少数窗口里成立？
3. 它和其他因子是不是在重复表达同一个东西？
4. 这个 uplift 是稳健的，还是被几天极端样本抬出来的？

这是整个项目从“调参数”走向“做因子工程”的关键转折。

### 3.3 第三阶段：把诊断结果转成运行时治理与执行护栏

再往后，优化不再停留在诊断层，而是开始沉淀成运行时可执行的约束：

1. `select_threshold` / `near_miss_threshold`
2. `selected_rank_cap_ratio` / `near_miss_rank_cap_ratio`
3. rank tightening
4. regime admission recovery
5. profitability hard cliff 与 boundary relief
6. prepared breakout / catalyst / volume / continuation 多种 relief
7. crisis / risk_off 下的 threshold lift 与 execution hard gate

这些逻辑集中沉淀在：

1. `src/targets/profiles.py`：profile 数据结构与默认权重/阈值/护栏字段。[`src/targets/profiles.py:10-140`]
2. `src/targets/short_trade_target_rank_helpers.py`：rank tightening、rank cap、regime recovery。[`src/targets/short_trade_target_rank_helpers.py:19-167,175-280`]
3. `src/targets/short_trade_target_evaluation_helpers.py`：突破阶段判断、初始决策、rank cap 执行、selected/near_miss/rejected 决策链。[`src/targets/short_trade_target_evaluation_helpers.py:210-279,281-357`]
4. `src/targets/short_trade_target_snapshot_relief_helpers.py`：risk_off / crisis 场景的 threshold lift 与 mild crisis override。[`src/targets/short_trade_target_snapshot_relief_helpers.py:292-337`]

这一步非常重要，因为它把“研究里看到的 uplift”转成了“交易当天能约束机器不乱冲”的具体规则。

### 3.4 第四阶段：开始出现真正能影响产线表现的 profile 固化

在 Round 75–88 之间，仓内已经出现一批不只是做分析，而是明确形成 profile 版本迭代的成果。

其中最典型的是 `momentum_tuned`：

1. 它是基于 `momentum_optimized` 继续把 `select_threshold` 调到 `0.38`、`near_miss_threshold` 调到 `0.24` 后固化出来的 profile。[`src/targets/short_trade_target_profile_data.py:1153-1163`]
2. 代码注释直接记录了回测结论：20 天回测日均收益约 `+0.20%`，胜率 `48%`，payoff `1.39`，优于默认 profile。[`src/targets/short_trade_target_profile_data.py:1153-1156`]
3. 阶段总结文档也明确写到：`momentum_tuned` 相比 `default`，日均收益从 `+0.11%` 提升到 `+0.20%`，正收益天数从 `10/18` 提升到 `11/18`。[`data/reports/btst_react_20260421_prepared_breakout_balance_summary.md:2206-2216,2237-2246`]

这说明到后期，项目已经不只是“看 metric 漂不漂亮”，而是在尝试把可重复的小优势固化成更稳定的 runtime profile。

### 3.5 第五阶段：Round 89 的方向性修正，是一个质变点

Round 89 最有代表性的不是“又多加了几个指标”，而是发现并修正了 **因子方向性错误**。

当前 profile 结构里保留了两个关键信号：

1. `short_term_reversal_weight`
2. `reversal_2d_weight`

但 Round 89 的研究明确指出：

1. 短期反转因子 IC 为负，正向加权等于在奖励超卖/下跌股。
2. 更合理的做法是把它翻转成 `trend_continuation = 1 - reversal`。

这在 `profiles.py` 和 `short_trade_target_profile_data.py` 里写得非常直白：

1. `profiles.py` 明确注释“反转因子 IC=-0.34，翻转后趋势延续因子 IC=+0.34”。[`src/targets/profiles.py:65-70`]
2. `trend_corrected_v1` 把 `short_term_reversal_weight` 与 `reversal_2d_weight` 归零，同时引入 `trend_continuation_weight=0.20`、`trend_continuation_2d_weight=0.12`。[`src/targets/short_trade_target_profile_data.py:1279-1326`]
3. 同一段代码还把多种 relief 与 penalty 重新搭配，说明这不是单点调权重，而是一次完整的 profile 方向修正。[`src/targets/short_trade_target_profile_data.py:1327-1380`]

如果把前 80 多轮看作“逐步积累诊断能力和约束能力”，那么 Round 89 更像一次 **发现核心方向错了以后做的结构性纠偏**。

---

## 4. 这些“因子”其实分成了 4 层，不要混着看

| 层级 | 典型内容 | 是否会直接进入 skill 报告 | 主要作用 |
|---|---|---|---|
| 运行时打分因子 | `breakout_freshness`、`trend_acceleration`、`volume_expansion_quality`、`close_strength`、`sector_resonance`、`catalyst_freshness`、`layer_c_alignment` | **会** | 直接参与 `score_target`、突破阶段判断、selected / near_miss / rejected 决策 |
| 运行时派生与修正因子 | `historical_continuation_score`、`momentum_strength`、`short_term_reversal`、`intraday_strength`、`trend_continuation` | **取决于当前 active profile** | 补充主打分因子，或修正方向性偏差 |
| 运行时护栏与治理变量 | threshold、rank cap、regime gate、profitability hard cliff、prepared breakout relief、risk_off/crisis threshold lift | **会，但往往以 gate / blocker / reason 形式出现** | 决定股票能否被提升、保留、降级或拦截 |
| 离线研究与验收指标 | IC 稳定性、过拟合分数、PCA 多样性、param drift、robustness、Sharpe / PF / EV 跨窗趋势 | **一般不会直接进入 skill 报告正文** | 用来决定一个 profile 是否值得发布成 manifest，或是否继续优化 |

把这 4 层分清很重要，因为用户常说的“因子是否用了”，其实至少有两种完全不同的含义：

1. **是不是直接参与了当日选股与报告生成。**
2. **是不是参与了 profile 的研究、筛选、批准与发布。**

很多 round 的成果属于第二种，不属于第一种。

---

## 5. `ai-hedge-fund-btst` skill 生成报告时，因子是怎样进入链路的

### 5.1 第一步：先解析当前批准的 optimized profile manifest

`resolve_btst_optimized_profile_manifest(...)` 会读取 manifest，得到：

1. `profile_name`
2. `profile_overrides`
3. `source_type`
4. `source_path`
5. `validated_by`
6. `status`

如果 manifest 无效或缺失，系统会回退到 `default`；只有 `status=ready` 且 `profile_overrides` 合法时，才算真正进入 optimized mode。[`src/paper_trading/optimized_profile_resolution.py:22-162`]

这意味着：**离线因子优化工作的绝大多数成果，必须先通过“发布为 manifest”这一步，才可能被 skill 报告真正吃到。**

### 5.2 第二步：paper trading / daily pipeline 把 profile 变成运行时决策对象

在 runtime 中，`daily_pipeline` 会基于当前 profile name + overrides 生成 `effective_profile`，然后把它传给 post-market target resolution、selection target 构建和执行计划构建。[`src/execution/daily_pipeline.py:1400-1453`]

真正开始影响选股的是这里：

1. **权重**：决定哪些因子推高 `score_target`。
2. **阈值**：决定 selected / near_miss 的门槛。
3. **rank cap**：决定即便分数够高，是否还能因为排序容量限制而被降级。
4. **regime / relief**：决定在 risk_off、crisis、prepared breakout、historical continuation 等语境下是否放宽或收紧。

### 5.3 第三步：候选股票被打分、分层、拦截、解释

`short_trade_target_evaluation_helpers.py` 中的主链路大致是：

1. 先判定突破阶段：`confirmed_breakout / prepared_breakout / watchlist_breakout`。[`src/targets/short_trade_target_evaluation_helpers.py:210-217`]
2. 再根据 `score_target` 与门槛做初始决策：`selected / near_miss / rejected / blocked`。[`src/targets/short_trade_target_evaluation_helpers.py:253-279`]
3. 再执行 rank cap、evidence deficiency、historical proof 等二次约束。[`src/targets/short_trade_target_evaluation_helpers.py:281-357`]
4. 最后把正向因子、relief、penalty、blocker 组织成 `top_reasons` 与 `rejection_reasons`。[`src/targets/short_trade_target_evaluation_helpers.py:458-534`]

所以 skill 报告里看到的：

1. `confirmed_breakout`
2. `trend_acceleration_supportive`
3. `profitability_hard_cliff`
4. `historical_execution_relief`
5. `historical_close_continuation`

这些并不是 LLM 在正文里临时发挥出来的，而是前面的 runtime 决策链已经算好、写好的解释字段。

### 5.4 第四步：selection snapshot 与 review renderer 把运行时结果写成报告素材

`SelectionSnapshot` 和 `render_selection_review(...)` 会把 selected / rejected / target summary / reporting summary / BTST regime gate 写成 markdown 或 json 产物。[`src/research/artifacts.py:20-33`; `src/research/review_renderer.py:36-133,160-172`]

这一步对 skill 报告特别关键，因为它定义了“报告能看到什么”：

1. 每只票的 `short_trade_target` 结论
2. `score_target`
3. `blockers`
4. top reasons / rejection reasons
5. BTST regime gate
6. selected / near_miss / blocked / rejected 计数

因此，从 skill 视角看，LLM 更多是在 **消费已经生成好的选择产物**，而不是重新发明一套因子解释。

### 5.5 第五步：skill 把 selection / execution 产物整理成中文说明文档

以 `20260513` 这次产物为例，最终写出的中文报告直接引用了：

1. `session_summary.json`
2. priority board
3. execution card
4. opening watch card
5. 各候选的层级、动作语义、top reasons、历史摘要

因此，`ai-hedge-fund-btst` skill 对因子的使用方式，主要是：

1. **读取运行时已经落盘的 profile / decision / artifact 结果**
2. **再把这些结果整理成更适合人审阅的中文文档**

它不是把 90 轮离线诊断指标全部重新跑一遍再写进报告。

---

## 6. 这次 BTST skill 生成报告时，哪些优化成果真正被用了

### 6.1 确认已经被用到的

在 `2026-05-13` 这次文档中，最明确已经被用到的是：

1. **approved optimized manifest**  
   `session_summary.json` 记录了 `optimization_profile_resolution.mode=optimized`，说明系统不是 default fallback，而是吃到了正式批准的优化配置。[`data/reports/paper_trading_20260512_20260512_live_m2_7_short_trade_only_20260513_plan_optimized_verify/session_summary.json:342-362`]
2. **`btst_precision_v2` 这条 active profile**  
   报告正文也明确写了 `profile_name = btst_precision_v2`。[`outputs/202605/20260513/BTST-LLM-20260512.md:33-40`]
3. **overrides 级别的阈值与 rank cap 调整**  
   例如 `select_threshold=0.34`、`near_miss_threshold=0.26`、`selected_rank_cap_ratio=0.16`、`near_miss_rank_cap_ratio=0.30` 等，已经直接进入运行时决策。[`outputs/202605/20260513/BTST-LLM-20260512.md:42-54`; `session_summary.json:345-355`]
4. **`btst_precision_v2` 自身携带的权重与 relief 体系**  
   它明确配置了 `breakout_freshness_weight`、`trend_acceleration_weight`、`volume_expansion_quality_weight`、`close_strength_weight`、`sector_resonance_weight`、`catalyst_freshness_weight`、`layer_c_alignment_weight`、`historical_continuation_score_weight`、`momentum_strength_weight` 等，并启用了 profitability / prepared breakout / continuation 一整套 relief 逻辑。[`src/targets/short_trade_target_profile_data.py:402-470`]
5. **historical prior 驱动的执行模式与报告解释**  
   比如 `historical_close_continuation` 会影响 `preferred_entry_mode`，并被加入 `top_reasons`，最终体现在 skill 报告正文里。[`src/paper_trading/_btst_reporting/entry_transforms.py:19-63`; `outputs/202605/20260513/BTST-LLM-20260512.md:93-108`]

### 6.2 明确没有被这次报告直接用到的

这次报告没有直接吃到的，至少包括两大类：

#### 6.2.1 大多数离线诊断指标

像下面这些 round 里加出来的指标：

1. `pca_diversity_score`
2. `overfit_score`
3. `param_drift_score`
4. `win_rate_ci_width`
5. `factor_drift_score`
6. `robustness_ratio`
7. `signal_quality_trend_slope`
8. `mc_ic_consistency_score`

它们主要存在于 `scripts/optimize_profile.py` 的搜索、比较、验收与发布决策里，用来判断 profile 值不值得升级；它们本身一般不会直接写进当日 BTST 中文报告正文。[`scripts/optimize_profile.py:117-606`]

#### 6.2.2 Round 89 的趋势延续修正 profile

虽然 Round 89 已经把 `trend_corrected_v1` 写进 profile 数据，并引入：

1. `trend_continuation_weight=0.20`
2. `trend_continuation_2d_weight=0.12`
3. `short_term_reversal_weight=0.0`
4. `reversal_2d_weight=0.0`

但这次实际报告仍然用的是 `btst_precision_v2`，而不是 `trend_corrected_v1`。[`src/targets/short_trade_target_profile_data.py:1279-1395`; `session_summary.json:343-356`]

更关键的是，`btst_precision_v2` 仍保留了 `short_term_reversal_weight=0.500`，说明当次发布口径还没有切到 Round 89 的方向修正版。[`src/targets/short_trade_target_profile_data.py:425-435`]

这一点和 rollout 报告是相互印证的：`btst_latest_optimized_profile.md` 的结论是 `hold`，manifest publication `skipped`，说明新的优化配置并没有全部进入正式发布链路。[`data/reports/btst_latest_optimized_profile.md:60-93`]

### 6.3 所以答案到底是什么

**不是所有 90 轮因子成果都被这次 `ai-hedge-fund-btst` skill 报告用到了。**

更准确地说：

1. **被用到的是已经“发布成 active profile 或 active override”的那部分。**
2. **没被直接用到的是仍处于研究、验证、比较、hold、未发布状态的那部分。**

---

## 7. 这些因子是怎样影响选股结果的

可以把它理解成 5 个连续动作。

### 7.1 因子先被压缩成一个 runtime profile

profile 决定：

1. 每个因子的权重
2. selected / near_miss 的阈值
3. rank cap
4. penalty / relief
5. regime gate 与恢复策略

这一步是“把 90 轮研究成果压缩成一张可执行的交易规则表”。

### 7.2 runtime 用 profile 把候选股票算成 `score_target`

随后，候选会经历：

1. 因子打分
2. breakout 阶段判断
3. threshold 对比
4. rank cap 与 evidence gate
5. blocker / relief / downgrade 组织

最后形成：

1. `selected`
2. `near_miss`
3. `rejected`
4. `blocked`

这一步决定的是 **“能不能进名单”**。

### 7.3 historical prior 再决定“即使进名单，应该怎么做”

系统还会根据 historical prior 决定：

1. `next_day_breakout_confirmation`
2. `intraday_confirmation_only`
3. `avoid_open_chase_confirmation`
4. `confirm_then_hold_breakout`
5. `strong_reconfirmation_only`

这一步决定的是 **“这票该不该追、该怎么追、是否只允许观察”**。[`src/targets/short_trade_target_evaluation_helpers.py:229-250`; `src/paper_trading/_btst_reporting/entry_transforms.py:19-63`]

### 7.4 报告把因子结果翻译成人能读懂的话

在 skill 报告里，你看到的是：

1. “主要理由”
2. “动作语义”
3. “推荐姿态”
4. “历史摘要”
5. “blocked / watch only / upgrade only”

这其实是在把前面已经算好的 `top_reasons`、`preferred_entry_mode`、historical prior、blocker 结果做中文整理。

### 7.5 最终效果不是“多选”，而是“更会分层”

这次报告里最能说明问题的一句话其实不是哪只票得分更高，而是：

1. **formal 主交易名单仍为空**
2. **观察层和机会池顺序被明显重排**
3. **弱样本被主动清理**

也就是说，当前因子优化的主要作用，更像是 **提高分层质量和治理质量**，而不是粗暴抬高入选率。[`outputs/202605/20260513/BTST-LLM-20260512.md:17-28,55-61,123-130`]

---

## 8. 目前已经看到的效果

### 8.1 选股排序与观察层质量更好了

从 `20260513` 这次 skill 产物看，优化后的 run：

1. 没有产生 formal 主交易名单。
2. 但观察层与机会池顺序明显重排。
3. 低质量观察样本被剔除。

报告明确写到：

1. 注意力从旧顺位切到 `000960`、`300308` 两只 near-miss。
2. `601179`、`688498`、`601698` 被整理到 upgrade-only 机会池。
3. `300113 顺网科技` 被从标准观察池剔除。

这类效果的意义在于：**系统正在更像一个有纪律的筛选器，而不是一个“把所有看起来不错的票都扔给人”的热度排序器。**[`outputs/202605/20260513/BTST-LLM-20260512.md:25-28,87-108,123-130`]

### 8.2 某些 profile 在局部窗口里确实跑出了更好的结果

最明确的正向例子是 `momentum_tuned`：

1. 日均收益：`+0.20%` vs `default +0.11%`
2. 胜率：`48%` vs `46%`
3. 赔率：`1.39` vs `1.38`
4. 正收益天数：`11/18` vs `10/18`

而且这些数字不是口头总结，而是直接写在阶段总结文档与 profile 注释里，说明这不是纯主观判断。[`src/targets/short_trade_target_profile_data.py:1153-1163`; `data/reports/btst_react_20260421_prepared_breakout_balance_summary.md:2206-2216,2237-2246`]

### 8.3 某些治理优化带来了稳健性收益，但 uplift 不算大

例如 `btst_v2_regime_guarded_cap_robustness_decision.json` 给出的共识参数，确实带来了：

1. `btst_score_delta = +0.0062`
2. `edge_score_delta = +0.0012`

同时它还给出了具体的 BTST 指标：

1. `next_close_positive_rate = 0.5339`
2. `next_close_payoff_ratio = 2.0152`
3. `next_close_expectancy = 0.0110`
4. `next_high_hit_rate = 0.6620`

这说明 rank cap / relief 方向不是没效果，但其效果更偏向 **治理和平衡**，不是那种“一换参数胜率就大跳升”的简单情形。[`data/reports/btst_v2_regime_guarded_cap_robustness_decision.json:34-87`]

### 8.4 项目已经学会了识别“哪些因子方向是错的”

Round 89 的最大价值之一，是系统终于把“因子方向性错误”当作一类一级问题来处理，而不是继续在错误方向上做细调。

这意味着：

1. 项目已经不只是会调权重。
2. 还开始会审查“这个因子应该被奖励，还是应该被反向使用”。

这对长期胜率比一次性的阈值优化更重要，因为它减少了“越优化越错”的风险。[`src/targets/profiles.py:65-70`; `src/targets/short_trade_target_profile_data.py:1281-1299`]

---

## 9. 这些工作是否已经提高了选股胜率

### 9.1 如果问“有没有局部提高”

答案是：**有。**

支持这个结论的证据包括：

1. `momentum_tuned` 相比默认 profile，20 天窗口里胜率从 `46%` 提到 `48%`，日均收益从 `+0.11%` 提到 `+0.20%`。[`data/reports/btst_react_20260421_prepared_breakout_balance_summary.md:2237-2246`]
2. 多窗口验证里，确实有若干窗口被标成 `variant_supports_t1_edge`，说明某些变体在 T+1 目标下存在正向支持证据。[`data/reports/btst_multi_window_profile_validation_20260406.md:26-29,31-35`]
3. skill 报告层面，排序重排和弱样本剔除说明“筛选质量”在改善，即使这不必然等于“主交易胜率立刻提高”。[`outputs/202605/20260513/BTST-LLM-20260512.md:25-28,125-130`]

### 9.2 如果问“能不能说已经稳定提高了整体 BTST 胜率”

答案是：**还不能说得这么满。**

更强的反证或保守证据包括：

1. `BTST Multi-Window Profile Validation` 的 aggregate verdict 明确写着：  
   `Variant behaves like a T+2 tradeoff rather than a strict BTST upgrade; keep the baseline default unless the objective changes.`  
   这等于说，变体更像在 T+2 目标上做了 tradeoff，而不是已经成为更好的“严格 BTST 默认版本”。[`data/reports/btst_multi_window_profile_validation_20260406.md:31-36`]
2. `btst_latest_optimized_profile.md` 的 rollout recommendation 是 `hold`，并且列出一串 blocker，包括 `win_rate_window_trend_regressed`、`pf_trend_slope_regressed`、`downside_p10_regressed_vs_default` 等，说明新配置在稳定性和下行维度上还没有过关。[`data/reports/btst_latest_optimized_profile.md:60-93`]
3. `btst_v2_regime_guarded_cap_robustness_decision.json` 里，虽然整体 score 有提升，但 `next_close_positive_rate_delta` 对比更激进方案反而是负的，收益改善与胜率改善并不总是同步。[`data/reports/btst_v2_regime_guarded_cap_robustness_decision.json:78-87`]
4. `20260513` 这次 skill 报告里，optimized run 仍然 **没有 formal 主交易名单**，这说明当前优化还不足以在真实运行口径下稳定地产生更强的主交易信号。[`outputs/202605/20260513/BTST-LLM-20260512.md:17-28,55-61`]

### 9.3 更准确的结论表述

如果要写成一句经得住复盘的表述，我建议这样说：

> 这 90 轮因子优化已经显著提升了 BTST 的因子研究能力、排序分层能力和运行时治理能力，并在部分 profile、部分窗口与部分目标函数上带来了局部胜率/收益改善；但截至当前仓内证据，仍不足以证明它已经稳定、普遍地提高了整体 BTST 次日选股胜率。

这是目前最符合仓内证据强弱关系的说法。

---

## 10. 为什么“很多优化成果没有直接出现在报告里”，却仍然很重要

这是最容易被误解的一点。

很多 round 的成果，例如：

1. IC 稳定性
2. overfit score
3. factor robustness
4. cross-window trend slope
5. significance / calibration / monotonicity
6. tail risk / drawdown / PF 趋势

它们不会直接在 BTST 中文报告里写成“主要理由：overfit_score 下降”。  
但它们依然很重要，因为它们决定了：

1. 哪个 profile 可以被批准发布
2. 哪个 profile 只能继续 hold
3. 某次 uplift 是真实 edge，还是样本噪声
4. 某个因子应该调高、调低，还是直接翻转方向

换句话说：

1. **report 用的是产线最终产物。**
2. **这 90 轮中的大量工作，做的是产线背后的“验证层、批准层、治理层”。**

没有这层，报告看起来可能更热闹，但更容易建立在错误 profile 之上。

---

## 11. 以后审阅 BTST 报告时，建议按这个顺序看

如果你以后要用这份文档做审阅基线，建议固定按下面 6 步看：

1. **先看 active profile 是谁**  
   是否是 default、published optimized，还是某个新 probe。先确认这个，再谈“因子是否被用了”。
2. **再看 overrides 改了什么**  
   重点看 threshold、rank cap、risk_off / crisis 相关配置，因为它们最直接改变 selected / near_miss 结构。
3. **再看 top reasons / blockers**  
   这是 runtime 真实发生的因子解释，不要跳过。
4. **再看是否出现 formal 主票**  
   没有主票时，不要只看“有没有更靠前的 near-miss”，要看是不是治理更保守、更干净。
5. **再对照 validation / rollout 报告**  
   判断当前 active profile 是“已被证明更好”，还是“只是暂时最能接受”。
6. **最后才问胜率是否提高**  
   胜率必须放在窗口、目标函数、coverage、drawdown 与 rollout blocker 的完整语境里看。

---

## 12. 最后一页式回答

### 12.1 我们在因子挖掘中取得了哪些进展

取得了 4 个层面的进展：

1. 从少量基础分数，扩展成完整的 BTST 因子宇宙与 IC 研究框架。
2. 从单窗口收益比较，扩展成跨窗口、跨 regime、跨风险维度的诊断体系。
3. 从离线研究，逐步沉淀出可执行的 profile、threshold、rank cap、gate、relief。
4. 到 Round 89，已经能识别并修正因子方向性错误，而不只是继续微调错误方向。

### 12.2 这些因子在这次 `ai-hedge-fund-btst` skill 报告生成过程中都用到了吗

**没有。**

1. 用到的是已经发布到 active manifest/profile 的那部分。
2. 没用到的是仍停留在离线诊断、hold、未发布状态的那部分。
3. 特别是 Round 89 的趋势延续修正，在这次 `20260513` 报告里还没有成为 active profile。

### 12.3 这些因子是如何使用的

链路是：

1. manifest 解析
2. active profile + overrides 生效
3. runtime 打分 / gate / rank cap / downgrade
4. selection snapshot 落盘
5. skill 把已落盘产物整理成中文报告

### 12.4 取得了哪些效果

1. 排序更稳定，观察层和机会池更可解释。
2. 低质量样本更容易被主动剔除。
3. 某些 profile 在局部窗口里，胜率、收益、赔率有改善。
4. 但最新 profile 发布仍受 rollout blocker 约束，说明系统更谨慎了。

### 12.5 是否帮我们提高了选股胜率

**局部有，整体尚未被充分证明。**

最稳妥的说法是：

1. 它已经提高了研究质量、筛选质量与局部窗口表现。
2. 但还没有足够强的仓内证据证明“整体、稳定、普遍地显著提高了 BTST 次日胜率”。

