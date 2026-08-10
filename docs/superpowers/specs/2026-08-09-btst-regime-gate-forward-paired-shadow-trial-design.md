# BTST Regime Admission 前向配对 Proxy Trial 设计（Revision 2）

> - 修订日期：2026-08-10
> - 状态：Revision 2 已获 owner 书面终审通过；尚未实施或启动 Trial
> - 执行模式：仅 `DAILY_BAR_PROXY`
> - 上位规范：`docs/superpowers/specs/2026-07-19-evidence-gated-growth-kernel-design.md`
> - 安全边界：只产生 `execution_authority="NONE"` 的前向反事实证据；不激活策略或资本授权，不签发 `ExecutionPermit`，不连接 broker
> - 历史材料：commit `055c3a0d` 及 regime-gate court 结果仅为 `RESEARCH_RECONSTRUCTION`

## 1. 决策

不继续把 legacy court 修补成授权级回测，也不为一个 regime 试验复制 Evidence Store、NAV、执行、统计或完整性系统。本 Trial 采用：

> 一条 PIT 证据脊柱、两个隔离的 proxy 资本世界、一个共享经济核心、一个纯评估器。

Champion 与 Challenger 的唯一预注册政策差异是：

```text
Champion   regime_admission_mode = IGNORE
Challenger regime_admission_mode = NORMAL_ONLY
```

`NORMAL_ONLY` 是 allowlist。冻结 classifier 遇到无法识别的原始值时必须归一为 `UNKNOWN`，Challenger 自动禁止新增风险；新增 canonical regime 状态本身属于行为变化，必须开启新 Trial。Champion 保持 ungated 总策略。两臂共享外生事实，但允许由不同历史决策造成的现金、持仓、回撤和容量自然分化。

Trial 主要估计完整组合路径的 `Challenger - Champion` 日对数增长差。胜率、平均单票收益、payoff 和 regime 子组只作诊断。

## 2. 为什么旧 court 不能晋级

commit `055c3a0d` 的 headline 可以复现，但部署解释被以下事实阻断：

- 价格加载忽略 `as_of`，会提前读取尚未成熟的 T+10 bar；
- 每个信号日重置 exposure，实际路径突破 60% gross cap，且期末仍有未平仓仓位；
- NAV 是 realized P&L 加法，不是现金、reserve、整数仓位、费用和逐日 mark 守恒后的 UnitNAV；
- 实际合约仍是 T+10 close，成本和不可成交处理不完整；
- regime、candidate、行业和 universe 缺少完整 PIT lineage；
- 2022/2024 缺少完整 setup 所需的 signal-day fund-flow，无法诚实补造跨期 OOS。

因此旧结果只能形成假设和反证测试，不能进入 `PRIMARY_PROMOTION`，也不能支持部署、授权或 canary。

## 3. 第一性不变量

### 3.1 测量总策略，不测标签美观度

实验对象不是“crisis 标签是否准确”，而是两个可完整定义的政策：

```text
P0 = 当前 BTST 完整政策，不把 regime 用于 admission
P1 = 与 P0 完全相同，但只有 NORMAL 可新增 BTST 风险
```

任何 setup、排序、sizing、风险、成本、T+1/T+10、日历或数据语义变化，都开启新的行为世代和 Trial。

### 3.2 配对是同观测，不是同行动

两臂共享同一个 T0 cutoff、候选集合、regime observation、市场 bar、公司行动、费用版本和交易日历。它们不要求有相同 proposal、fill 或持仓。

因此有效的 `UNKNOWN` regime 下：Champion 可以继续，Challenger 必须阻断。让两臂共同 no-entry 会改变 Champion，并把估计量错误地条件化在 regime 数据可用性上。

### 3.3 每类事实只有一个权威来源

| 事实 | 唯一来源 |
|---|---|
| 原始市场数据、候选、regime 输入与后续 observation | Evidence Store trusted timeline |
| official expected session 与运行状态 | `SessionSpine` |
| 每臂冻结的政策决策 | append-only `TrialArmDecisionStore` |
| 每臂现金、reserve、仓位、费用、UnitNAV、退出与 correction | 各自 `AccountCapitalTruth` |
| Trial/SAP/Stage、attempt、multiplicity、样本消费 | 现有 governance/evidence ledger |
| paired delta、覆盖和门禁结果 | 固定 assessment 时的纯 projection |

不新增 `PairedDayFact`、`PairedSessionDisposition`、配对经济 hash chain 或持久化 `PairedTrialProjection`。它们都可从上述事实确定性重建；重复持久化只会制造冲突。

### 3.4 权限与经济计算分离

`ShadowDecision` 是不可执行的完整反事实，不能为复用 Gateway 而伪造 active 或 inactive `CapitalAuthorizationEnvelope`。正式与 shadow 路径只在边界处分型：

```text
已授权边界 -> shared decision core -> executable proposal
Trial 边界  -> shared decision core -> ShadowDecision(authority=NONE)

ExecutionPermit -> shared proxy execution/settlement core -> capital events
ShadowDecision  -> shared proxy execution/settlement core -> isolated proxy events
```

内部排序、sizing、风险、开盘判定、费用和资本 reducer 必须共用；权限对象、issuer、namespace 和可达依赖必须不同。

## 4. Regime 合约

### 4.1 类型

```text
RegimeState         = NORMAL | RISK_OFF | CRISIS | UNKNOWN
RegimeAdmissionMode = IGNORE | NORMAL_ONLY
```

它们是 `PolicySnapshot` 和 shadow kernel 输入中的 strict/frozen value，不是环境变量、CLI 参数或独立服务。

| observation | Champion `IGNORE` | Challenger `NORMAL_ONLY` |
|---|---|---|
| `NORMAL` | 进入相同后续 admission/ranking/sizing | 同左 |
| `RISK_OFF` | 同左 | 全部 BTST 新仓 blocked |
| `CRISIS` | 同左 | 全部 BTST 新仓 blocked |
| `UNKNOWN` | 同左 | 全部 BTST 新仓 blocked |

regime 只决定候选是否进入后续相同流程，不改 strength、不乘仓位、不重排候选。Champion 在 `UNKNOWN` 下继续的前提是 BTST 自身需要的 setup/candidate evidence 仍然有效；`IGNORE` 不能复活缺失的核心候选事实。

### 4.2 Canonical observation 与运行故障不同

每个 session 在 T0 cutoff 前形成一个 strict `RegimeObservation`，作为现有 `SnapshotEvidence` 的版本化 payload 提交，不新增第五种 Evidence envelope。它绑定：

- `signal_session`、`state` 与 typed reason；
- active source evidence IDs、revision、commit sequence 和 evidence root；
- `effective_at`、`provider_published_at`、`observed_at`、store-owned `ingested_at`/`available_at`；
- classifier semver、behavior fingerprint、input schema hash。

输入缺失、过期或无法判定时，应正常产出 `state=UNKNOWN`；不能回退 `normal`，也不能在 assessment 时从最新缓存重算历史标签。legacy `regime_history.json` 不是权威来源。

只有 Evidence Store/runner 故障导致在截止前连 canonical observation 都无法提交时，才是 operational `NO_RUN`：两臂不新增风险、退出继续，session 留在 ITT spine 中。不得把该故障伪装成政策 `UNKNOWN`，也不得事后删除。

## 5. 最小架构增量

### 5.1 Shadow kernel boundary

当前 `KernelInput` 强制携带 `PolicyActivation` 与 `CapitalAuthorizationEnvelope`，适用于可执行 admission，不适合首批 shadow 证据。正式 Trial 必须增加 exact `ShadowKernelInput`，至少绑定：

```text
trial / SAP / stage hashes
arm PolicySnapshot and ShadowPolicyBinding
portfolio / arm / signal_session / decision_cycle_id
DAILY_BAR_PROXY mode
trusted evidence cutoff and root
RegimeObservation and RegimeAdmissionMode
arm-specific CapitalRiskSnapshot/checkpoint
raw candidates and frozen price/industry inputs
deadline, cost and execution versions
```

`ShadowPolicyBinding` 是 strict union：Champion 引用 TrialManifest 已绑定的 baseline activation hash 与对应 PolicySnapshot；Challenger 引用 target policy registration hash 与对应 PolicySnapshot。两者都冻结 snapshot hash/fingerprint/source kind/source hash，但都不是 activation token。

`ShadowKernelInput` 不含 `PolicyActivation` 对象、`CapitalAuthorizationEnvelope`、nonce 或 broker account。shadow admission 与 executable admission 分别验证自己的边界，再映射到同一个内部 `DecisionConstraints`，由同一个纯 decision core 完成排序、容量、sizing 和 risk-once 计算。

输出为 `ShadowDecision | NoTradeDecision`。禁止沿用 Plan 05 的临时 synthetic-authority workaround 作为 official Trial 输入。

现有 `ShadowDecision.policy_activation_hash` 会迫使 shadow artifact 冒充 activation provenance。Revision 2 必须提升其 schema major，并以 `ShadowPolicyBinding` 取代该字段；旧 schema 只留 compatibility read，official Trial 拒绝写入或晋级。`policy_epoch` 只能来自所绑定的 PolicySnapshot，不能由 runner 自填。

### 5.2 `TrialArmDecisionStore`

现有 `InMemoryShadowStore` 是进程内 last-write-wins，仅适合一次性观测。本 Trial 使用带 FK、不可变触发器和唯一键的 SQLite/WAL append-only store，并提供一个原子 `commit_pair(champion, challenger)`。

每个 arm record 至少保存：

```text
key = (trial_id, signal_session, decision_cycle_id, arm)
shared_input_hash
arm_policy_fingerprint
arm_capital_checkpoint_hash
regime_observation_hash
decision = ShadowDecision | NoTradeDecision
created_at / artifact_hash
```

约束：

- 两臂在同一事务写入；写入前不得修改任一资本账本；
- exact replay 幂等，same key/different bytes 永久冲突；
- 两条 arm record 的存在即可证明 pair complete，不再持久化 `PairedDecisionRecord`；
- store 不保存收益、NAV 或可由 Evidence/CapitalTruth 重建的 payload 副本；
- `NoTradeDecision` 也必须持久化，不能因 `ShadowDecision` 要求非空 lines 而丢失 no-signal/blocked session。

### 5.3 `ForwardPairedTrialRunner`

runner 只负责编排：读取 sealed Trial/SAP/SessionSpine，冻结共享输入与一次 trusted-clock observation，读取两臂资本 checkpoint，各运行一次 shadow kernel，原子提交 pair，并以稳定 ID 推进 shadow proxy lifecycle。两个 kernel 调用必须消费同一个冻结时间，不能因调用先后得到不同 deadline 结果。

两个隔离 proxy portfolio 由同一 fenced single-writer lease 管理；correction/lifecycle 也经该 writer 排序。它不把两库冒充一个事务，但防止 decision 与 reserve 之间出现并发 writer 漂移。

runner 不实现 classifier、ranking、sizing、成交、费用、NAV、统计或授权；不签名、不激活、不发送。

### 5.4 Shared proxy execution/settlement core

现有 `resolve_open_execution` 已是 entry/exit 共用的纯日线判定。实现时把 `DailyBarProxy` 中仍与 permit 形状耦合的费用、reserve 释放、fill settlement 和 idempotency 逻辑收敛为共享 core，并保留两个不可互换的 adapter：

- authorised adapter：只接受 mode-matched `ExecutionPermit`；
- shadow adapter：只接受 `ShadowDecision`、Trial binding 和隔离 proxy portfolio。

shadow adapter：

- 永远返回 proxy resolution/capital event，不返回 permit、outbox 或 broker command；
- 使用 `trial_id + arm + decision_cycle_id + shadow_line_id + event_kind` 派生稳定经济 ID；
- 在 T+1 先调用与 Gateway 共用的 frozen mechanical shrink/cancel resolver，只能按 availability、price、capacity、cash、capital/risk 等已注册条件缩减或取消，绝不能增加 T0 数量；结果作为 authority-free proxy execution record 持久化，不包装成 permit；
- T0 reserve、T+1 open、费用、integer lots、T+10 open exit、partial/unknown、公司行动和 correction 全部写入该 arm 的 mode-pure资本台账；
- entry unknown/no-fill 释放 reserve、保留现金；exit unknown 保留 mandate，不用 stale close 或未来价补造；
- 只依赖 Evidence Store observation、CapitalTruth 和纯 resolver；broker module 在静态依赖图上不可达。

每个由 Trial 决策派生的 reserve、trade、fee 与 execution correction 必须同时标记 `mode=DAILY_BAR_PROXY` 与 `source_artifact_kind=SHADOW_DECISION`；close mark/valuation 则如实绑定产生它的 `SnapshotEvidence`，不能把市场估值伪称为决策产物。所有事实只允许进入该 Trial/arm 的隔离 portfolio；它们是 mode-pure counterfactual capital truth，不是真实账户资本事实。

这不是第二套执行引擎：两种 adapter 必须通过 differential/property tests 证明，对归一化后等价的 quantity、limit、bar、费用、reserve 和资本前态产生相同经济 resolution。

## 6. 前向状态推进

### 6.1 Trial seal

首个 official signal 前，Governance 在同一事务保留 Attempt/multiplicity budget并 seal Trial/SAP 与不可执行 target PolicySnapshot registration；随后必须在 enrollment 前验证已签名且精确绑定这些 hash 的 StageManifest，并生成完整 expected-session spine。SAP 直接引用上位规范 §13 的最低证据、MEE、ESS、tail、capacity、stress、ITT、finality 和 consumption 规则，本文不复制第二份阈值。

Official OOS 时间顺序必须满足上位规范：Trial seal 早于 signal/evidence，signal computation 与 Evidence Store commit 不晚于 decision cutoff，`ShadowDecision.created_at` 不晚于该 cutoff。旧 payload 在 seal 后重新导入不能获得新 OOS 身份。

两臂从逐字段相同的 genesis economic state 建立，但使用不同 `portfolio_id` 和独立资本 event/checkpoint stream。genesis 覆盖 cash、units、positions、reserves、pending exits、receivables/payables、risk state 与 watermark。

### 6.2 每个 signal session

```text
prior lifecycle/corrections settled
  -> two close checkpoints verified
  -> shared PIT input and RegimeObservation frozen
  -> producer runs once
  -> shadow kernel runs once per arm
  -> commit_pair atomically
  -> T+1/T+10 proxy lifecycle settles idempotently
  -> two daily capital checkpoints verified
```

两臂 decision commit 后才允许任何本 cycle 的 reserve/fill side effect。两库之间不宣称跨库事务；一臂结算后崩溃时，根据已提交决策和稳定 event ID 补齐另一臂，禁止换 ID、删除成功一臂或重新计算更有利的 proposal。

不同 cycle 可以重叠持仓。gross、cash、drawdown、capacity 和 pending exits 始终来自各臂完整前态，绝不能按日重置。

不新增 paired disposition；现有 SessionSpine 的映射固定为：pair 成功提交且至少一臂进入有效政策决策为 `RUN`（即使另一臂被 regime blocked），共享 producer 无候选为 `NO_SIGNAL`，共享核心证据未知为 `DATA_UNKNOWN`，共同风险/完整性阻断为 `BLOCKED`，pipeline 未在截止前形成 pair 为 `NO_RUN`，交易所签名修订才可为 `SESSION_CANCELLED`。arm-specific 原因只存在各自 decision record 中。

### 6.3 Enrollment 结束

`enrollment_end` 后停止新决策，继续 exit-only run-out。到 sealed finality date 必须满足：两臂退出/费用/公司行动/correction 已达到规定 finality，资本 conservation/rebuild 通过，SessionSpine 无未分类行。否则 assessment 固定为不晋级，不能延长赢家窗口或删除 pending 样本。

## 7. 失败语义

- canonical `UNKNOWN`：按两臂总政策分别决策；不是共同 no-entry。
- shared infrastructure `NO_RUN`：两臂不新增风险，退出继续，保留 ITT 行。
- pair commit 前失败：零本 cycle 资本副作用；截止前可用相同 key 重试，逾期永久 `NO_RUN`/`BLOCKED`。
- pair commit 后失败：固定 ID 重放收敛；same ID/different payload 锁存 protocol breach。
- 任一资本流 conservation、projection rebuild 或负不可能持仓失败：两臂共同 entry halt；退出、公司行动、对账和 correction 继续。
- policy/classifier/setup/cost/execution/schema 漂移：停止当前 Trial enrollment；新行为必须新 fingerprint、Attempt、Trial/SAP/Stage。
- late fee、bust、公司行动与 outcome correction：只追加 revision，不覆盖 canonical event，不增加 outcome 或 evaluation-unit 数。

任何 unresolved protocol breach 都使 promotion Boolean 为 false，不能用更多好样本稀释。

## 8. 评估与报告

固定 assessment 时，纯 evaluator 按市场 session 对齐两条已验证 UnitNAV checkpoint 流：

```text
d_t = log(NAV_challenger,t / NAV_challenger,t-1)
    - log(NAV_champion,t / NAV_champion,t-1)

DeltaG = mean(d_t)
```

符号永远是 `Challenger - Champion`。现有 `evaluate_predictable_adaptive` 使用相反方向且属于 adaptive fold；不得交换参数名冒充修复。应增加命名明确的 frozen paired evaluator，并用 swap-sign property 锁定方向。阈值相等按上位规范使用 `>= MEE`。

主序列包含所有未取消市场日：cash day、no-signal、blocked、两臂相同和分歧日。decision/disagreement day 只用于独立覆盖与 ESS，不替代连续组合路径。current-cost 与 2× slippage stress 都必须从 genesis 完整重放资本状态，不能在最终 return 上减常数。

promotion eligibility 直接调用上位规范冻结的逻辑与：

- timeline/ITT/finality 完整；
- 两臂 capital conservation 与 rebuild 通过；
- 最低 mature outcome、decision-day/ESS、ticker、月份和 adverse-window 覆盖通过；
- 两臂 absolute growth 与 `Challenger - Champion` incremental LCB 达到各自 MEE；
- current-cost 和 stress 都通过；
- MDD、CDaR、overshoot、liquidity、capacity 和 unknown/pending 上限通过；
- attempt、multiplicity 与 evidence/evaluation-unit consumption 通过；
- 无 unresolved breach。

报告是 evaluator 的可删除 projection，只引用 Evidence/Decision/Capital checkpoint hashes。缺任一门时 headline 为 `NOT_ELIGIBLE`；全部通过也只能是同模式 `INACTIVE_PROMOTION_CANDIDATE`。`DAILY_BAR_PROXY` 永远不能标为 broker fill 或直接授权真实资本。

## 9. 测试与完成门

### 9.1 语义与因果

- `NORMAL` 且资本状态相同：两臂的经济决策投影（排序、数量、价格、reserve）逐字节相同；arm、portfolio 与 policy provenance 自然不同；
- `RISK_OFF/CRISIS/UNKNOWN`：Champion 按 ungated 政策继续，Challenger blocked；
- 无 canonical observation：共同 operational no-run，不回填 normal；
- regime 不能影响排序、strength 或 sizing；
- 任意第二个外生政策差异都使 Trial 失败。

### 9.2 确定性与守恒

- `commit_pair` 原子、append-only、exact replay 幂等、冲突 replay 拒绝；
- producer 只运行一次，kernel 每臂恰好一次；
- gross 不跨日清零，现金/reserve/整数股/费用/税/units/NAV 守恒；
- T+1 open 与 T+10 open、重叠仓位、unknown exit 和每日 mark 可从 canonical facts 重建；
- 删除全部 assessment projection 后可得到逐字节相同结果；
- 交换两臂后 delta 精确变号；相同政策与状态下 delta 恒零。

### 9.3 Adapter parity 与权限隔离

- authorised/shadow adapter 对等价经济输入给出相同 resolution；
- `ShadowKernelInput` 拒绝 PolicyActivation、Envelope、permit nonce 和 broker identity；
- shadow adapter 拒绝 `ExecutionPermit`，authorised adapter 拒绝 `ShadowDecision`；
- trial runtime 的 AST/import guard 禁止 broker dispatcher/runtime、authority activation、Gateway publish/claim-send 和 production outbox；
- shadow artifact 无法转换、包装或反序列化为 permit/broker command；
- proxy outcome 无法进入 `BROKER_CONFIRMED` authorizer path。

### 9.4 故障注入

- 两臂计算之间、pair commit 前后、一臂资本写后和 checkpoint 前后崩溃；
- observation/fee/fill/correction 重复、乱序和内容冲突；
- missing/suspended/late/一字板、partial exit 和长期 pending；
- policy/evidence/capital version 漂移；
- conservation/rebuild 失败后 entry 停止而 exit 继续。

完成声明必须同时有相关 v3 套件全绿、fault injection、snapshot/fixture 更新、`git diff --check`、权威设计/机器策略/迁移说明同步，以及静态证明 trial 没有任何真实发单路径。

## 10. 明确删除与非目标

Revision 2 删除原设计中的：

- `RegimeEntryPolicy` 服务对象；
- `PairedShadowTrialCoordinator` 大型组件；
- `ShadowProxyPlan`；
- `PairedDecisionRecord`；
- `PairedDayFact` 与独立 hash chain；
- `PairedSessionDisposition`；
- 持久化 `PairedTrialProjection`。

保留的新增面只有 typed policy/observation、authority-free shadow kernel boundary、durable arm decision store、薄 runner、shadow proxy adapter 和纯 evaluator；经济算法全部下沉到现有共享 core。

本设计不覆盖 `--auto`、OversoldBounce、regime 重训/阈值搜索、历史 PIT 数据补造、真实迁移、broker enablement、真实资本 canary 或自动 activation。

## 11. 最终安全声明

本设计不把 `+44.9%` 转化为部署批准，也不预判 gate 胜出。它只建立一个能被未来事实否证的前向测量系统：Champion 保持真实 ungated 语义，Challenger 使用 fail-closed `NORMAL_ONLY`，两臂共享外生事实并在各自守恒资本路径中演进。

在完整时间窗、增长、尾部、容量、覆盖与完整性门全部通过前，regime gate 保持 shadow。即使全部通过，也只产生 `DAILY_BAR_PROXY` 同模式的 inactive candidate；`BROKER_CONFIRMED` 必须使用新的、不复用的真实前向 Trial。
