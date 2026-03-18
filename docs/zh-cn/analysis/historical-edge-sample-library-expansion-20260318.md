# 历史 edge sample 扩库进展 2026-03-18

## 1. 结论先行

这一轮只读扩库的结论很明确：

1. 结构化 reports 里还没有自然长出第四个可准入的已验证 edge sample。
2. 当前固定 benchmark 仍应保持为三条：`20260224 / 600519`、`20260226 / 600519`、`20260226 / 300724`。
3. 历史线索可以继续扩，但必须分层管理：
   - 第一层是已验证 benchmark；
   - 第二层是“待补证历史候选”；
   - 第三层是明确排除的结构性冲突或噪声样本。
4. 在 benchmark 没有扩充之前，不应因为利用率压力去放松全局 Layer C / watchlist / avoid 规则。

## 2. 本轮扫描方法

本轮没有改 runtime 规则，只做了两类只读工作：

1. 继续复核既有中文分析文档，尤其是：
   - `paper-trading-edge-candidate-list-20260318.md`
   - `edge-sample-benchmark-20260318.md`
   - `paper-trading-agent-conflict-diagnosis-20260318.md`
   - `paper-trading-candidate-suppression-20260317.md`
   - `pipeline-funnel-scan-202602-window-20260312.md`
2. 补了一个只读扫描脚本 `scripts/scan_historical_edge_samples.py`，递归扫描 `data/reports` 下 `.json/.jsonl`，把满足以下条件的记录分成三档：
   - near-threshold watch：`decision = watch`、`bc_conflict = null`、`0.17 <= score_final <= 0.26`
   - sub-threshold watch：`decision = watch`、`bc_conflict = null`、`0.14 <= score_final < 0.17`
   - high-score watch：`decision = watch`、`bc_conflict = null`、`score_final > 0.26`

脚本输出已落到：

- `data/reports/historical_edge_sample_scan_20260318.json`

核心汇总如下：

1. `near_threshold_watch`：`1075` 条去重记录，只有 `300724`、`600519`、`600988` 三个 ticker。
2. `sub_threshold_watch`：`11` 条去重记录，只有 `600519`、`603993` 两个 ticker。
3. `high_score_watch`：`517` 条去重记录，只有 `300724`、`600519`、`601600`、`603993` 四个 ticker。

这进一步说明：当前结构化证据非常集中，根本不是“还有一大批安全边缘样本没整理出来”，而是大多数记录都在围绕少数已知票反复出现。

## 3. 结构化扫描的实质发现

### 3.1 `300724` 仍然是当前窗口里唯一大规模重复出现的 near-threshold non-conflict 样本

扫描结果里：

1. `300724` 在 `near_threshold_watch` 里有 `1061` 条去重记录。
2. 覆盖日期从 `20260202` 一直延伸到 `20260302`，其中当前验证窗口内最关键的是 `20260224` 到 `20260227` 这一段。
3. 这与既有结论一致：当前长窗口里真正的 clean edge sample，本质上还是 `300724` 这一类样本，而不是大量新的候选。

需要强调的是，`300724` 的大规模重复，不代表 benchmark 已经扩库；它只是说明现有结构化 artifacts 多次重复记录了同一类边缘模式。

### 3.2 `600519` 仍然是唯一稳定成立的第二类历史 edge sample

扫描结果里：

1. `600519` 在 `near_threshold_watch` 档只有 `10` 条去重记录，但日期稳定收敛到 `20260224` 与 `20260226`。
2. `sub_threshold_watch` 里还出现了 `20260225`、`20260227` 的 `0.158 ~ 0.164` 记录，这更像同一类样本在更保守场景下的下沿，而不是新的独立 edge family。
3. `high_score_watch` 里还有 `20260224` 的 `0.2624 ~ 0.2648`，说明它确实贴着边界上下波动。

因此，`600519` 仍然是可以和 `300724` 并列保留的另一类已验证历史 edge sample，但它并没有进一步扩出第三个 family。

### 3.3 `600988` 虽然在结构化扫描里出现了 `0.174` 的 watch 记录，但不能纳入样本库

脚本会把 `600988` 扫出来，因为它在 `20260226`、`20260227` 的部分 pipeline artifacts 中出现过 `score_final = 0.174`、`decision = watch`、`bc_conflict = null` 的记录。

但这个票仍然应该排除，原因不是主观偏好，而是高优先级证据与它直接冲突：

1. `paper-trading-agent-conflict-diagnosis-20260318.md` 已明确把 `600988` 定义为“investor 与 analyst 双负的结构性冲突样本”。
2. 该文档给出的代表日期就是 `20260226`、`20260227`，并记录了更稳定的状态是：
   - `decision = avoid`
   - `bc_conflict = b_positive_c_strong_bearish`
   - `score_final` 约 `0.1686 ~ 0.1687`
3. `paper-trading-candidate-suppression-20260317.md` 也给出了相同方向的结论：`600988` 是近端落选里的结构性冲突票，而不是安全边缘样本。

所以这里更合理的解释是：

1. `600988` 的 `0.174 watch` 只是个别 pipeline artifact 中的噪声切片。
2. 它没有得到 tradeoff 报告、suppression 报告、agent conflict 诊断三类证据的一致支持。
3. 因此它不能被视为第四个已验证样本，甚至不应进入“首轮待补证候选”。

## 4. 候选池分层

### 4.1 第一层：固定 benchmark，保持不变

当前仍只保留三条：

1. `20260224 / 600519`
2. `20260226 / 600519`
3. `20260226 / 300724`

这是后续所有最小化 Layer C / watchlist 实验的硬门槛。

### 4.2 第二层：待补证历史候选

这一层不是可直接准入的 edge sample，只是“值得继续补证的线索”。

#### `603993`

它是当前最值得放在待补证池头部的对象，但注意，它不是当前可准入的 edge sample。

原因：

1. `pipeline-funnel-scan-202602-window-20260312.md` 记录了它在 `20260202`、`20260203` 的 Layer B 近阈值卡点：
   - `20260202 = 0.3799`
   - `20260203 = 0.3776`
2. 新扫描脚本显示它在结构化 reports 里主要落在 `high_score_watch` 档：
   - 日期集中在 `20260202`、`20260203`、`20260204`
   - `score_final` 范围 `0.2650 ~ 0.2954`
3. 同时它也在 `sub_threshold_watch` 档留下了两条 `20260203 / 20260204` 的 `0.145` 记录。

这组证据说明：

1. `603993` 更像“上游 Layer B / Layer C 形成机制”的研究样本。
2. 它并不是当前 watchlist 边界上的 clean edge sample。
3. 如果后面要扩库，它更适合作为“上游接近阈值但最终转成高分 watch 的对照样本”，而不是直接加入 edge benchmark。

#### `688498`

这只票已经不再需要进入高优先级待补证序列。

原因：

1. `pipeline-funnel-scan-202602-window-20260312.md` 记录了它在 `20260205` 的 Layer B 值 `0.3516`；
2. 同一文档已说明它没有明显 hard negative fundamental blocker，更接近“第三条腿缺失 + 中性 mean_reversion 稀释”；
3. 历史结构化 scan 也没有给出它的 near-threshold non-conflict watch 证据。

因此它当前最多只需要保留为低优先级机制线索，而不是继续占用高优先级补证预算。

### 4.3 第三层：明确排除

这一层应继续排除在首轮扩库之外：

1. `600988`：高优先级文档已证明其为结构性冲突票。
2. `000426`：虽然早期 Layer B 有边缘线索，但它依赖 `event_sentiment` 的异常补分，且已被后续分析归入结构性冲突/不安全样本。
3. `000960`、`300251`、`300775`、`600111`、`300308`：既有诊断已明确它们不是“差一点能进”的安全边缘样本。

### 4.4 已完成补证、确认降格为机制样本

这一层不是 benchmark，也不再属于待补证候选，而是已经完成专项补证、确认不能进入 edge sample 库的样本。

#### `603993`

它已经完成专项补证，结论是：

1. baseline / scan 视角下主要表现为 Layer B near-threshold 或 sub-threshold；
2. frozen replay 中又能被抬成 high-score watch 并真实买入；
3. 随后快速进入 logic stop failure 链。

因此它的价值在“上游形成机制研究”，不在 benchmark。

#### `300065`

它也已经完成专项补证，结论比此前更明确：

1. 历史结构化 scan 里没有自然形成 final near-threshold non-conflict watch 证据；
2. `20260223`、`20260224`、`20260225` 连续三天只是在 Layer B 下沿 `0.3735 / 0.3739 / 0.3736` 压线；
3. 在长窗 paper trading 的 `20260223` prepared plan 中，它虽然到过 `score_b = 0.401`，但又被 `score_c = -0.6861` 压成 `score_final = -0.0882`、`decision = avoid`；
4. factor 分析说明其问题更接近 `profitability` 硬负项语义，而不是 arbitration 误杀。

因此它只能作为“上游近阈值 + 强负向 Layer C avoid”机制样本保留，不能再视为待补证 benchmark 候选。

#### `688498`

它也已经完成当前阶段的最低必要补证，结论是：

1. 历史结构化 scan 里没有 clean watch 足迹；
2. 一手 replay 里最接近阈值时也只是 `score_b = 0.3725`、`reason = below_fast_score_threshold`；
3. 机制上更接近“trend + fundamental 为正，但缺少第三条增量腿”，同时又被 `mean_reversion` 的中性 completeness 稀释；
4. 反事实分析显示，移除中性 `mean_reversion` 参与后它可以从 `0.3516` 抬到 `0.4688`。

因此它只能作为低优先级机制样本保留，不再视为待补证 benchmark 候选。

## 5. 当前可执行的后续动作

在不放松全局规则的前提下，后续顺序建议是：

1. 先把 `603993` 做成单独的“上游近阈值形成机制”补证样本，目标不是纳入 benchmark，而是看它为什么从 Layer B 边缘票转成高分 watch。
2. 如果 `603993` 的补证能形成稳定模板，再决定是否继续补 `300065`。
3. 在出现新的 clean near-threshold non-conflict 一手证据前，不做新的全局 Layer C / watchlist 放松实验。

## 6. 本轮更新的意义

这轮工作的价值不是“又找到了几个能放出来的票”，而是把扩库工作收得更紧：

1. 已验证 benchmark 仍然很小，但边界更清楚了。
2. 待补证候选与已补证机制样本已经分层，不再混在 benchmark 语义里。
3. `600988` 这种会误导判断的噪声样本，被结构化扫描和既有诊断一起重新压实为排除项。

这比继续盲目扫更多报表更重要，因为它避免了在 benchmark 不足时误把结构性冲突票当成“可释放边缘样本”。