# BTST corridor prior 管线修复与主矛盾切换方案（2026-05-24）

## 学习目标

- 看清 `300683` 这条 corridor-primary / upstream shadow 主线，问题已经从“prior 没进 replay”切换成“prior 质量本身不够强”。
- 区分 source 语义保留、followup brief 刷新、latest prior loader、replay 重建、historical execution relief 这几段链路各自负责什么。
- 明白为什么当前最该继续做的，不是再放松 relief 阈值，而是重做 upstream shadow 的 alpha 质量分层。
- 给 alpha、beta、gamma 一条还能继续回测、能直接接进 BTST 主线的分工方案。

## 先给结论

这轮回测之后，`300683` 这条主线最大的技术问题已经不是 source 丢失，也不是 latest prior 没有进入 replay。**这条管线现在已经打通了。**

真正暴露出来的新主矛盾是：`upstream_liquidity_corridor_shadow` 这类票虽然已经能在 replay 里拿到 `historical_prior`，但当前聚合出来的 prior 质量还是偏弱，更多落在 `balanced_confirmation`，而不是能支撑正式晋级的 `close_continuation`。结果就是：

1. `historical_execution_relief` 已经开始工作；
2. 但它大多是 `enabled = true`、`eligible = false`、`applied = false`；
3. 系统因此没有继续把弱样本误放成正式主票；
4. 主问题从“链路断了”切换成“alpha 证据不够强”。

换句话说，这一轮最重要的收获，不是直接把 `300683` 放成主票，而是**把一个假的技术阻塞排除了，逼出了真的策略短板**。

## 本轮回测在回答什么

这轮不是在证明系统已经达到“买入后 `5` 个交易日内，`55%` 概率涨超 `15%`”的目标，而是在确认下面这条链到底通没通：

`corridor / upstream shadow 候选 -> brief 产物 -> latest prior loader -> replay 重建 -> historical_execution_relief`

如果这条链不通，后面谈 alpha 因子质量、target 调参、signal 叠加都没有意义；因为系统连历史证据都吃不到。

本轮最关键的两个结果是：

| 指标 | 本轮结果 | 说明 |
| --- | --- | --- |
| `focused replay diagnostics` | 已能看到 `historical_execution_relief` 与 `historical_prior` | 说明 replay 侧已经真实消费 refreshed prior |
| merge replay validation | `relief_applied_count = 0`，`recommended_next_lever = target` | 说明当前不该继续放松 relief，而该回到 target / signal 质量 |

## 系统地图：这条链现在分成 4 段

| 段落 | 现在状态 | 这段负责什么 |
| --- | --- | --- |
| source 语义保留 | 已修通 | 防止 corridor / upstream shadow 在 rebucket 后被彻底写成 `catalyst_theme` |
| followup brief 与 latest prior | 已修通 | 让 `upstream_shadow_entries` 也能带 `historical_prior` 并被 loader 读到 |
| replay 重建 short-trade 目标 | 已修通 | `refresh_latest_historical_prior=True` 后，replay diagnostics 已能看到历史先验 |
| relief 最终晋级 | 还没放行 | 不是代码没吃到 prior，而是 prior 质量还不满足正式晋级条件 |

所以当前不是“一条链全坏了”，而是前三段已经恢复，第四段开始按真实历史证据做拒绝。

## 关键证据

### 1. `300683` 的 replay 侧已经能看到 refreshed prior

直接对 `2026-04-01` 到 `2026-04-03` 的 replay 输入重放后，`300683` 的 focused diagnostics 已经出现：

- `candidate_source = upstream_liquidity_corridor_shadow`
- `historical_execution_relief.enabled = true`
- explainability payload 里有非空 `historical_prior`

这说明当前 replay 重建，不再停留在“source 恢复了，但 prior 还没进来”的旧状态。

### 2. 但当前 prior 更像 `balanced_confirmation`，不是强延续

同一批 focused diagnostics 里，`300683` 当前最典型的历史画像是：

- `execution_quality_label = balanced_confirmation`
- `evaluable_count = 10`
- `next_close_positive_rate = 0.0`
- `next_high_hit_rate_at_threshold = 0.5`

这组数的含义很直接：系统已经拿到了历史证据，但这份证据本身并不支持“次日收盘继续强势”的结论。

### 3. merge replay validation 的方向判断已经变了

本轮针对 `300683` 的 merge replay validation 聚合了：

- `24` 个相关报告目录
- `118` 个 trade-date 样本

聚合结果里最关键的几项是：

- `overall_verdict = merge_replay_promotes_selected`
- `promoted_to_selected_count = 10`
- `relief_applied_count = 0`
- `recommended_next_lever = target`
- `recommended_signal_levers = sector_resonance, trend_acceleration`

这说明目前最值得继续压的，不是“让 relief 更容易放行”，而是**把 target / signal 这两层的质量做强**。

### 4. 一个具体样本：`2026-04-06` 的 `300683`

在一条 baseline replay focused row 里，`300683` 的表现已经是：

- `candidate_source = upstream_liquidity_corridor_shadow`
- `replayed_decision = near_miss`
- `historical_execution_relief.enabled = true`
- `historical_execution_relief.eligible = false`
- `historical_execution_relief.execution_quality_label = balanced_confirmation`

这里最重要的不是它没被放成正式票，而是：

> **系统终于是在“看见历史证据之后拒绝它”，而不是“因为历史证据没接上而误拒绝它”。**

这两种拒绝，策略含义完全不同。前一种说明该回 alpha；后一种才说明该修工程链路。

### 5. upstream shadow 全族的第一轮 alpha 分层结果已经出来了

把 `data/reports` 下面所有 replay 输入在 `refresh_latest_historical_prior` 打开后重建一遍，当前 upstream shadow 家族一共拿到了 `181` 条可分析样本：

- `balanced_confirmation = 97`
- `intraday_only = 36`
- `unknown = 28`
- `close_continuation = 14`
- `zero_follow_through = 5`
- `gap_chase_risk = 1`

这里最重要的不是标签分布本身，而是几个信号的可分性：

1. `sector_resonance` 在当前 upstream shadow 样本里几乎恒定在 `0.1`，暂时没有实际分层价值。
2. `trend_acceleration` 有明显分层能力。
3. `close_strength` 和 `trend_acceleration` 叠加以后，分层会进一步变干净。

最有用的一刀是：

- 当 `trend_acceleration >= 0.80` 时，样本数是 `21`
- 其中 `close_continuation` 占比约 `28.57%`
- 决策分布是 `selected = 10`、`near_miss = 9`、`rejected = 2`

对照组则明显更弱：

- 当 `trend_acceleration < 0.80` 时，样本数是 `160`
- `close_continuation` 占比只有 `5%`
- `balanced_confirmation` 占比约 `59.38%`
- 决策分布是 `near_miss = 39`、`rejected = 113`、`blocked = 8`

再加上 `close_strength` 以后，强分层更明显：

- `trend_acceleration >= 0.80` 且 `close_strength >= 0.85`
- 样本数 `17`
- `close_continuation` 占比约 `35.29%`
- `balanced_confirmation` 占比约 `11.76%`
- 决策分布是 `selected = 10`、`near_miss = 5`、`rejected = 2`

这说明下一轮 alpha 质量分层不该从 `sector_resonance` 开刀，而该先从 **`trend_acceleration` 主切，`close_strength` 辅切** 开始。

## 为什么我认为当前主问题已经不是别的

### 不是 source 丢失

这一段已经修过：`historical_execution_relief` 能从 `catalyst_theme` rebucket row 恢复 `upstream_candidate_source`，focused diagnostics 里也能重新看到 `upstream_liquidity_corridor_shadow`。

### 不是 latest prior loader 还在读空

这一段也已经修过：`upstream_shadow_entries` 现在会参与 history enrichment，report-local brief 刷新后，loader 对 `300683` 已能返回非空 prior。

### 不是 replay 还没消费 refreshed prior

这一段同样已经过验证：单日 replay 输入和最外层 merge replay validation 都能在 diagnostics 里看到 `historical_execution_relief` 与 explainability 里的 `historical_prior`。

### 当前真正的问题，是 alpha 证据质量

当 source、loader、replay 三段都通了以后，`300683` 仍然没有被 relief 放成正式主票，而且原因集中在：

- `execution_quality_support = false`
- `next_close_positive_rate` 不达标
- 历史标签更接近 `balanced_confirmation`

这已经不是 transport bug，而是策略证据本身不够强。

## 最佳解决方案：先把 upstream shadow prior 做成质量分层，再决定是否给 relief

这轮我不建议继续直接放松 relief 门槛。更稳的方案是：

> **先把 upstream shadow 的历史先验从“能不能接上”推进到“接上之后能不能区分强延续和弱确认”。**

### alpha：把 upstream shadow prior 拆成两层，不再把所有 same-ticker 证据混在一起

alpha 这一轮最该做的是重新定义 upstream shadow 的历史标签，而不是继续扩大样本池。

优先顺序建议是：

1. 先把 `same_ticker` 样本按 `close_continuation`、`balanced_confirmation`、`gap_chase_risk` 拆层。
2. 对 `300683` 这类样本，专门检查哪些失败样本拖低了 `next_close_positive_rate`。
3. 新增和当前验证结果直接相关的分层因子：
   - `trend_acceleration`
   - `close_strength`
   - `next_close persistence`
   - `next_open_to_close follow-through`
4. `sector_resonance` 先保留观察，不把它作为 upstream shadow 当前这一刀的主判别因子，因为现有 cohort 里几乎没有可用方差。
5. 不再只看“有 prior”，而要看“prior 是否属于可晋级的 continuation 族”。

alpha 这里要解决的是：**把“历史上有过表现”改成“历史上更像哪一种表现”。**

### beta：把 prior 刷新与 report-local brief 刷新固化成日常产线

beta 侧这轮不该再去放松 target gate，而要把已经修好的工程链固化下来，避免后面反复回到“brief 是旧的、loader 读不到、replay 看不到”的老问题。

建议直接做三件事：

1. 把 report-local `btst_next_day_trade_brief_latest.json` 的刷新流程固定进 replay / followup 产线。
2. 在 validation 产物里长期保留：
   - `historical_execution_relief`
   - `historical_prior.execution_quality_label`
   - `replayed_decision`
3. 给 `upstream_shadow_entries` 单独做 observability，不再和其它 followup row 混看。

beta 这边最重要的任务，不是“再放一批票”，而是**让优质 prior 和弱 prior 在系统里可区分、可回放、可复查**。

### gamma：用 rollout 明确 relief 的上线条件，不让“链路打通”被误读成“该放松了”

gamma 侧要守住两件事：

1. 代码链打通，不等于策略应该自动放行；
2. 当前 prior 偏弱时，继续强放 relief 只会把坏样本放大。

建议 gamma 直接把 rollout 条件写成硬门槛：

1. `execution_quality_label` 必须进入 `close_continuation` 或同等级别的强延续族。
2. `next_close_positive_rate >= 0.55`
3. `next_high_hit_rate_at_threshold >= 0.60`
4. 样本数不能只靠 `same_ticker` 的极少数观测撑起
5. 只有满足这些条件的 upstream shadow prior，才允许进入下一轮 relief 放行试验

这会让 gamma 守住主线：**先提升胜率和赔率，再考虑放宽放票。**

## 一个具体任务流：`300683` 这次到底经历了什么

按当前已经验证过的链路，`300683` 这次的真实流转是：

1. 上游 corridor / upstream shadow 候选进入 short-trade 体系。
2. rebucket 后它一度被写成 `catalyst_theme`，导致 source 语义变脏。
3. source fallback 修好后，`historical_execution_relief` 重新能识别它来自 `upstream_liquidity_corridor_shadow`。
4. followup brief 修好后，`upstream_shadow_entries` 开始真正生成并保存 `historical_prior`。
5. replay refresh 打开后，focused diagnostics 终于能读到这份 prior。
6. 但系统读完以后给出的判断是：`enabled = true, eligible = false`。

这个任务流说明，当前 `300683` 不是“被系统误杀的好票”，而是“把误杀链排除之后，暴露出它目前还不是足够强的历史画像”。

## 为什么这一步仍然有价值

因为如果这条管线不打通，团队后面会一直在两个错误方向里打转：

1. 把 replay 没吃到 prior，误判成“relief 阈值太严”；
2. 把旧 brief 读空，误判成“upstream shadow 这类票天然没有历史价值”。

现在这两个误判都可以拿掉了。接下来每一次放票或不放票，至少是在真实 prior 上做判断。

这让后面的 alpha 因子挖掘和 gamma rollout 开始有了干净地基。

## 下一步验证顺序

建议按下面顺序继续推进：

1. 对 `300683`、`301188` 这类 corridor / upstream shadow 样本，重建 `same_ticker` 历史失败样本清单。
2. 专门分析哪些失败样本拖低了 `next_close_positive_rate`，并按 `sector_resonance`、`trend_acceleration`、`close_strength persistence` 切分。
3. 在 replay validation 里新增一层对照：
   - `balanced_confirmation`
   - `close_continuation`
   - `gap_chase_risk`
4. 只对 `close_continuation` 族做下一轮 relief / target 放行实验。
5. 如果实验后 `5` 日 `15%` 命中率和 `next_close_positive_rate` 都没有抬起来，再回到 upstream shadow 召回定义，而不是继续微调 relief。

## 最新落地进展：第一版 upstream shadow 质量门槛已经接进 target rank-cap

这轮没有继续把 `trend_acceleration` / `close_strength` 往 `historical_execution_relief` 里塞，而是按前面的判断，把它们接进了更合适的 target rank-cap 层。

本次代码改动的核心是：

1. 在 `ShortTradeTargetProfile` 里新增了两个 upstream shadow 专用阈值：
   - `upstream_shadow_source_specific_rank_cap_trend_acceleration_min`
   - `upstream_shadow_source_specific_rank_cap_close_strength_min`
2. 在 `short_trade_target_rank_helpers.py` 里，把 upstream shadow source-specific cap 的启用条件从：
   - source 命中
   - reason 命中
   - override 存在
   - 可选的 `relief_applied`
   扩展成：
   - 上面几条全部满足
   - 并且 `trend_acceleration` 与 `close_strength` 同时达标
3. 在 rank-cap observability 与 metrics payload 里补出了：
   - 两个阈值本身
   - `trend_acceleration_pass`
   - `close_strength_pass`
   - `support_pass`
4. 把 `btst_precision_v2_liquidity_shadow_release_probe` 升级成了带这两个阈值的 probe，默认就按：
   - `trend_acceleration >= 0.80`
   - `close_strength >= 0.85`
   来看 upstream shadow 的 source-specific cap。

这样做的意义是：

- **强 upstream shadow**：允许进入更严格、但更有针对性的 rank-cap 约束；
- **弱 upstream shadow**：即便 source / reason 命中了，也不会误触发 shadow 专属 cap；
- `historical_execution_relief` 继续只做“历史先验解释”，不和最终 target 放行逻辑继续耦合膨胀。

## 这次实现验证了什么

我专门补了两条针对 upstream shadow 的测试：

1. **强样本正例**
   - `candidate_source = upstream_liquidity_corridor_shadow`
   - `trend_acceleration = 0.887`
   - `close_strength = 0.8625`
   - 结果：`shadow_source_specific_caps_enabled = true`
2. **弱样本反例**
   - 同样走 upstream shadow source / reason
   - 但 `trend_acceleration`、`close_strength` 明显不达标
   - 结果：`shadow_source_specific_caps_enabled = false`

同时补跑了直接相关回归：

- `tests/targets/test_target_models.py`
- `tests/targets/test_short_trade_event_catalyst_helpers.py`
- `tests/test_optimize_profile_script.py`

相关回归一共通过 `2656` 条，说明这次把 upstream shadow 质量门槛接进 rank-cap，没有打坏现有 catalyst / profile / optimize-profile 主线。

另外我又补了两轮 replay 验证，用来回答“这条新 gate 在真实样本里到底有没有动到东西”：

1. **真实 probe replay**
   - 直接用当前 `btst_precision_v2_liquidity_shadow_release_probe` 重跑 `data/reports`
   - 因为这个 probe 仍然要求 `relief_applied = true`
   - 当前 upstream shadow 样本里，quality gate 前后 `decision_change_count = 0`
   - 这说明这次改动**没有偷偷改写现网这批 replay 的最终决策**
2. **stress replay（临时关闭 `require_relief_applied`）**
   - 目的是把“quality gate 本身”的裁剪能力单独量出来
   - 结果显示：
     - 不加质量门槛时，`shadow_source_specific_caps_enabled = 224`
     - 加上 `trend_acceleration >= 0.80 && close_strength >= 0.85` 后，`shadow_source_specific_caps_enabled = 22`
   - 也就是说，这条 gate 已经把 shadow source-specific cap 的适用面，从**全量 upstream shadow 样本**压缩成了**只有约 9.8% 的强样本**

这两个 replay 结果合起来的含义很重要：

- **短期**：这次改动先把错误放大的风险收住了，没有冒进地改写真实 replay 决策；
- **中期**：一旦后续 gamma 确认要放宽 `relief_applied` 或把这条 gate 推到更前面，这套 `trend_acceleration + close_strength` 分层已经能立刻把弱 upstream shadow 样本挡在外面。

## 这一步对 alpha / beta / gamma 各自意味着什么

- **alpha**：现在不再只是“证明 `trend_acceleration` / `close_strength` 有分层价值”，而是已经把这组分层价值变成了系统里真实生效的 target quality gate。
- **beta**：工程边界变清楚了——prior 解释继续留在 relief，source-specific 的实际放行约束收敛到 rank-cap，不再混成一个越来越重的 helper。
- **gamma**：上线控制终于有了更干净的 rollout 入口。后面要不要放宽、要不要追加新阈值，可以直接围绕 `support_pass`、`selected/near_miss` 分布和真实 5D/15% 命中结果做样本外验证，而不是再回头怀疑 prior 管线有没有断。

## 边界

- 这份结论不能推出“`300683` 永远不该晋级”。
- 也不能推出“corridor / upstream shadow 这条线没价值”。
- 它只说明：**到 2026-05-24 这一轮验证为止，最大的技术堵点已经清掉，最大的策略堵点是 prior 质量还不够强。**

## 下一步建议

如果只允许做一件事，我建议先做：

> **把 upstream shadow 的历史先验从“是否存在”推进到“是否属于强延续分层”，先做 alpha 质量分层，再决定要不要继续给 relief。**

## 最新 rollout 结果：upstream shadow decision-impact 实验

这轮不再只看 `caps_enabled` 覆盖面，而是直接比较不同 rollout 变体对 `selected / near_miss / execution_eligible` 的真实影响。

本次最优变体是：`relief_free_shadow_caps`

- `selected_count_delta = 0`
- `near_miss_count_delta = 0`
- `tradeable_count_delta = 0`
- `execution_eligible_count_delta = 0`
- `aggregate_tradeable_next_close_positive_rate_delta = 0.0`
- `aggregate_tradeable_t_plus_2_close_return_median_delta = 0.0`

结论：

- 这次没有任何 upstream shadow rollout 变体把 `selected / near_miss / execution_eligible` 真正推高。
- `relief_free_quality_gate_tighter_caps` 虽然给出了 `next_close_positive_rate_delta = 0.2499`，但它同时带来 `next_close_return_p10_delta = -0.0009` 和 `t_plus_2_close_return_median_delta = -0.0135`，不满足“非负 T+1 guardrail”这一主线要求，所以不能算 rollout 胜利。
- 这说明当前主问题还在 **alpha / candidate 定义层**，而不是 rollout 开关本身；继续放松 relief 或继续改 shadow rank-cap 适用条件，都还不足以把 upstream shadow 变成更强的正式放票来源。
- 下一轮更该做的，不是继续切 rollout 开关，而是回到 `false negative / false positive` 样本，把哪些 upstream shadow 历史先验会误导 target 决策这件事再拆细。
