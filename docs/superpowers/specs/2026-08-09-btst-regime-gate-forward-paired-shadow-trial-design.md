# BTST Regime Gate 前向配对 Shadow Trial 设计

> - 日期：2026-08-09
> - 状态：设计已逐节获 owner 认可；本文待书面复核
> - 适用范围：BTST 的 `BLOCK_CRISIS_RISK_OFF` 准入策略，执行模式固定为 `DAILY_BAR_PROXY`
> - 上位规范：`docs/superpowers/specs/2026-07-19-evidence-gated-growth-kernel-design.md`
> - 安全边界：只产生前向 shadow 证据；不激活策略、不签发执行 permit、不连接 broker、不改变真实资本
> - 历史材料定位：commit `055c3a0d` 及其 regime-gate court 结果只属于 `RESEARCH_RECONSTRUCTION`

## 1. 阅读目标

读完本文，开发者和审阅者应能回答以下问题：

1. 为什么 commit `055c3a0d` 的数值可以复现，却不能作为 regime gate 的部署证据。
2. Champion 与 Challenger 之间唯一允许的外生行为差异是什么。
3. 两条组合路径如何共享市场事实，同时保留各自真实演进的现金、仓位和风险状态。
4. 崩溃、缺失行情、停牌、涨跌停、迟到费用和 correction 如何处理，且不伪造成交。
5. 哪些统计门必须同时通过，哪些单票指标只能用来诊断。
6. 为什么 `DAILY_BAR_PROXY` 通过后仍不能直接进入 broker 或真实资本路径。

## 2. 决策摘要

本设计不继续把 legacy court 修补成授权级回测。regime gate 的晋级路径改为一个预注册、固定策略、同起点、双账本的前向配对 Shadow Trial：

- Champion：当前 BTST 行为，不用 regime 阻断准入。
- Challenger：除 `BLOCK_CRISIS_RISK_OFF` 外与 Champion 相同。
- 两臂消费同一份 T0 点时（point-in-time，PIT）市场证据、候选、排序规则、成本版本、执行版本和后续市场观测。
- 两臂使用独立 `DAILY_BAR_PROXY` 资本账本，各自保存现金、reserve、整数仓位、gross、NAV、退出义务和 correction。
- 主要裁决对象是完整锁定窗口内的 `Challenger - Champion` 日对数增长差，不是胜率、平均单票收益或某个 regime 子组。
- 历史 court 可继续用于冒烟、反证和假设形成，但在类型与导入规则上不能进入 `PRIMARY_PROMOTION`。

该设计回答的是“怎样获得可信的前向证据”，不预设 gate 有效。正确结果可以是长期保持 shadow，或最终否决 Challenger。

## 3. 背景与证据审计

### 3.1 可复现的研究结果

对 commit `055c3a0d` 的隔离复跑可以复现决策包的主要数值：

| 研究配置 | 组合 NAV | BTST 样本 | BTST 均值 | BTST 胜率 |
|---|---:|---:|---:|---:|
| ungated | 0.759116 | 121 | -2.479% | 38.84% |
| gated，保留全部 setup | 1.175058 | 179 | +1.637% | 50.84% |
| gated，仅 BTST | 1.449448 | 214 | +2.100% | 51.87% |

这些数字证明研究脚本可重复地产生相同输出，不证明输出符合目标执行合约，也不证明 regime gate 有可授权的增量 edge。

### 3.2 阻断部署解释的问题

当前 court 至少存在以下部署级阻断项：

1. `price_loader` 忽略 `as_of` 并返回完整价格缓存。214 笔 gated BTST 中有 73 笔在当时尚未成熟的 session 提前读取了后续 T+10 bar。
2. 每个信号日把 `portfolio_used` 重置为零，没有带入未平仓 exposure。gated BTST 峰值 exposure 达到 300%，结束时仍有 17 个仓位、170% exposure，不能称为受 60% gross cap 约束的组合。
3. NAV 只做 realized P&L 加法，没有现金、整数股、reserve、每日 mark-to-market 和单位份额守恒。
4. “最大回撤”实际取最终 drawdown；独立连续路径重算与报告值不一致。
5. 实际执行仍是 T+1 open 到 T+10 close，只收每边 30 bps，没有完整卖出税费，也没有严格的停牌、涨跌停和不可成交状态。
6. candidate 遍历与 live 排序、日内容量规则不一致；mutable journal、regime history 和报告没有完整 PIT timeline 与输入 hash。
7. 2022、2024 年没有可供完整 BTST setup 使用的 signal-day fund-flow 数据；ticker universe 和行业映射也存在 survivorship/PIT 缺口。补价格不能补出缺失的历史决策事实。

因此，本设计给出以下 owner 结论：

> commit `055c3a0d` 及其决策包可以保留为 `RESEARCH_RECONSTRUCTION` 诊断，但应拒绝作为部署、授权或 promotion 证据。

### 3.3 不继续升级 legacy court 的原因

若在 legacy 脚本内依次补 as-of、组合账本、T+10 open、完整费用、公司行动、统计治理和 expected-session spine，最终会形成第二套 v3。两套实现迟早再次发生执行语义、成本版本和资本事实漂移。

仓库已经具备 Evidence Store、Trial/SAP、SessionSpine、Growth Kernel、AccountCapitalTruth、ExitLane、DailyBarProxy、OutcomeFinalizer 和统计治理 primitive。新增工作应把这些能力接成一条前向证据路径，而不是复制它们。

## 4. 第一性原理与不变量

### 4.1 唯一经济目标

目标保持为扣除成本、约束和现金占用后的组合单位净值长期对数增长。任何裁决必须来自连续组合路径：

```text
G_arm = (1 / D) * Σ_t [
    log(UnitNAV_arm,t / UnitNAV_arm,t-1)
    - log(Benchmark_t / Benchmark_t-1)
]
```

胜率、赔率、平均单票收益、payoff、IC 和 regime 子组均值只能解释结果，不能替代该目标。

### 4.2 一次只检验一个外生差异

本 Trial 只允许一个预注册策略差异：

```text
regime_entry_policy:
    Champion   = OBSERVE_ONLY
    Challenger = BLOCK_CRISIS_RISK_OFF
```

不得同时改变 setup、候选、强度公式、排序、Kelly、单票上限、组合上限、成本、执行、退出、日历或数据口径。任何这类变化都要产生新的行为指纹和 Trial。

### 4.3 共享外生事实，允许内生状态分化

两臂必须共享：

- T0 Evidence Store cutoff 和原始 evidence root；
- BTST 候选集合与候选字段；
- 排序、容量、仓位和风险算法版本；
- 交易日历、价格限制、费用与 execution contract；
- T+1、持有期 mark、T+10 及后续退出的市场 observation。

两臂的资本快照不能被强行做成相同。Challenger 阻断过一次入场后，现金、持仓、gross、drawdown 和后续可用容量会自然分化。该分化是策略差异的内生结果，必须保留。

因此，“只有一个差异”的准确含义是：**外生输入和算法只有 regime admission 不同；由既往政策选择造成的 arm-specific capital state 可以不同。** 禁止把两个不同资本快照伪装成同一个 `KernelInput` hash。

### 4.4 未知不默认为 normal

regime evidence 缺失、过期、版本不匹配或无法在 T0 cutoff 前证明可用时，两臂都不新增风险，退出继续。该 session 记录为共享未知/不入场并保留在 ITT 分母中，不能事后补成 normal。

### 4.5 Shadow 不产生权限

本 Trial 的 proposal、paired record、proxy event、checkpoint、统计结果和 promotion candidate 都不构成：

- active `PolicyActivation`；
- active `CapitalAuthorizationEnvelope`；
- 可执行 `ExecutionPermit`；
- broker order 或 broker evidence；
- 真实账户资本事实。

Trial runtime 只能写入隔离的 `DAILY_BAR_PROXY` namespace，且 broker adapter 在类型和依赖图上均不可达。

当前 `KernelInput` 结构要求携带 `PolicyActivation` 与 `CapitalAuthorizationEnvelope`。Coordinator 只能复用 Plan 05 的 shadow-trust 模式，按 Trial/SAP 确定性构造**未激活候选 witness**：`execution_authority=NONE`，不登记到 active Authority Store，也不能传给 Gateway。本文所称“不激活”是禁止 active authority，不是通过删除 kernel 必填字段绕开验证。

## 5. 范围与非目标

### 5.1 本设计覆盖

- BTST Champion/Challenger 的预注册前向配对 Trial。
- PIT regime evidence 与固定 admission policy。
- 双臂 proposal、proxy entry/exit、独立资本账本和每日 paired fact。
- expected-session、错误恢复、完整性门、统计评估和 ledger-derived 报告。
- legacy court 的非授权定位与机器可拒绝边界。

### 5.2 明确排除

- `--auto`、OversoldBounce、streak、composite 或其他 factor。
- regime 分类器重训、阈值搜索或多个 gate 变体并行竞争。
- 补造 2022/2024 fund-flow、行业或 universe 的 PIT 历史。
- 把 `scripts/backtest_paper_loop.py` 改造成授权级回测系统。
- 真实 broker adapter、生产 authority flip、真实资金 canary 或自动部署。
- 通用实验平台、UI 或与本 Trial 无关的重构。

OversoldBounce 已默认暂停，不需要借本 Trial 再次证明其停用。历史跨期 reconstruction 可以另开研究任务，但不能进入本 Trial 的 promotion 样本。

## 6. 方案比较

| 方案 | 优点 | 主要缺陷 | 决策 |
|---|---|---|---|
| 修补 legacy court | 短期改动看似少，可立即重跑旧区间 | 会复制 v3 的 PIT、账本、执行和统计能力；仍有同段选择偏差 | 不采用 |
| 建完整历史 PIT 回放 | 可覆盖多个市场周期 | 当前缺失 2022/2024 fund-flow 与 as-of universe；无法诚实补造 | 仅可作为未来独立工程 |
| 前向配对 Shadow Trial | 因果边界清楚；共享当日事实；直接观察完整组合增量 | 需要等待时间和 adverse window，无法立刻给部署结论 | 采用 |

选择前向配对 Trial 的代价是等待。这个代价不能用事后数据、缩短窗口或复用旧样本规避。

## 7. Trial 合约

### 7.1 Champion 与 Challenger

| 属性 | Champion | Challenger |
|---|---|---|
| producer | BTST | BTST |
| setup | 同一冻结版本 | 同一冻结版本 |
| regime policy | `OBSERVE_ONLY` | `BLOCK_CRISIS_RISK_OFF` |
| normal | 允许进入后续准入 | 允许进入后续准入 |
| crisis | 允许进入后续准入 | 阻断全部 BTST 新仓 |
| risk_off | 允许进入后续准入 | 阻断全部 BTST 新仓 |
| unknown | 两臂共享 no-entry | 两臂共享 no-entry |
| exit | 独立、始终继续 | 独立、始终继续 |

`regime_entry_policy` 只决定是否把当日 BTST 候选交给后续相同的 ranking/sizing/risk 过程。它不修改 strength，不乘仓位，不重排候选。

unknown 时的共同 no-entry 是 sealed Trial measurement rule，不宣称复现 active Champion 在该日的实际行为。unknown/attrition 超过 SAP 预注册上限、集中在某个 regime，或无法证明与结果无关时，Trial 不得晋级；不能把这些日期从分母删除。

### 7.2 Regime evidence

regime 必须由 signal cutoff 前已提交到 Evidence Store 的原始输入派生。有效记录至少绑定：

- `signal_session`；
- 原始 payload hash 与 active revision；
- `effective_at`、`provider_published_at`、`observed_at`、`ingested_at`、`commit_sequence`、`available_at`；
- classifier semver、behavior fingerprint 和输入 schema hash；
- 输出枚举 `normal | crisis | risk_off | unknown`；
- 计算所消费的 evidence IDs 和 evidence root。

`detect_market_state(date)` 可以作为冻结 classifier 的纯计算入口，但不能在评估时从最新缓存重新计算过去标签。`data/reports/regime_history.json` 是 mutable legacy projection，不是本 Trial 的权威输入。

### 7.3 Trial/SAP seal

首个 official signal 之前，Governance 必须原子完成 Attempt reservation、`TrialManifest` 与 `StatisticalAnalysisPlan` seal，并生成 expected-session spine。除上位规范已有字段外，本 Trial 的 SAP 必须显式冻结：

- Champion 与 Challenger policy fingerprint；
- regime evidence schema/classifier/version；
- `DAILY_BAR_PROXY` execution version；
- T0/T+1/T+10 contract、fee policy 和 2× slippage stress；
- 两臂共同 genesis checkpoint；
- enrollment、entry stop、follow-up finality 和 fixed assessment；
- paired status inclusion/attrition 规则；
- `Challenger - Champion` 符号方向；
- absolute MEE、incremental MEE、tail/capacity gate；
- block bootstrap 方法、block rule、seed、repetitions 和 multiplicity policy；
- canonical outcome 与 governance evaluation-unit counting key。

本文不替 Governance 选择具体 MEE、attrition ceiling、adverse-window 定义或日期。Trial 启动时必须从当期 `StatisticalGovernancePolicy` 取得不可放宽的 floor/ceiling，再由 SAP 选择相同或更保守的确定值；任何值缺失、版本不一致或仍需人工补填时，禁止 enrollment。

解盲后改变任一项都不能修改原 Trial，只能登记新 Attempt。

## 8. 组件与复用边界

### 8.1 直接复用的 v3 primitive

| 现有能力 | 在本设计中的用途 |
|---|---|
| Evidence Store | 保存 T0 输入、regime 派生记录、后续市场 observation 与 revision |
| `TrialManifest` / `StatisticalAnalysisPlan` | 冻结行为、时间窗、统计与 multiplicity |
| `SessionSpine` | 预登记 expected session，保留 `NO_RUN`、`DATA_UNKNOWN` 和 cancellation |
| Growth Kernel | 使用 arm-specific capital snapshot 与未激活 shadow witness 计算确定的组合 proposal |
| AccountCapitalTruth | 保存每条 proxy arm 的现金、仓位、费用、reserve、units、NAV 与 correction |
| ExitLane / lifecycle scheduler | 生成并推进 T+10 退出义务；entry halt 不阻断 exit |
| DailyBarProxy | 复用同一开盘成交判定和费用结算规则 |
| OutcomeFinalizer | 按 plan-line/economic-contract key 终结 outcome，不因 revision 膨胀样本 |
| EvidenceConsumptionLedger | 阻止同一 evidence/evaluation unit 重复用于 promotion |
| 统计治理 primitive | MEE、LCB、ESS、MDD、CDaR、覆盖门与 multiplicity |

### 8.2 三个新增单元

#### `RegimeEntryPolicy`

纯函数。输入是冻结 regime evidence 与 policy enum，输出为：

```text
ALLOW
BLOCK_CRISIS
BLOCK_RISK_OFF
SHARED_DATA_UNKNOWN
```

它不读文件、数据库、时钟或环境变量，不负责 ranking、sizing、capital 或授权。

#### `PairedShadowTrialCoordinator`

负责单个 Trial 的顺序推进：

- 读取已验证 Trial/SAP 与 expected session；
- 冻结共享 decision input；
- 从各自资本账本取得 arm-specific checkpoint；
- 调用同一 producer 与 Growth Kernel；
- 验证外生差异只来自 `RegimeEntryPolicy`；
- 原子提交 paired decision；
- 以稳定 event ID 驱动两条 proxy 账本；
- 处理 crash replay、entry halt 和 run-out。

Coordinator 不实现成交算法、不计算 NAV、不计算统计、不签发权限。

#### `PairedTrialProjection`

只从 canonical paired records、两条资本台账 checkpoint 和 Evidence Store observation 派生：

- 每日两臂 cash、gross、reserve、positions、UnitNAV、drawdown；
- 每日两臂 log return 与 `challenger_minus_champion_log_growth`；
- paired disposition、unknown、attrition、protocol breach；
- 连续 MDD、CDaR、overshoot 和 capacity facts；
- assessment 所需的 immutable input set/hash chain。

报告和统计服务只能读取该 projection，不能从 journal 或内存重新拼收益。

### 8.3 DailyBarProxy 的 shadow 接口约束

现有 `DailyBarProxy.execute_open` 消费 seal/permit。该接口不能被 Trial 伪造权限后复用。实现时应把其日线判定与结算规则提取为共享的纯 resolver，并增加只接受非授权 `ShadowProxyPlan` 的 trial 入口：

- `ShadowProxyPlan` 只能绑定 `DAILY_BAR_PROXY` 和隔离 trial portfolio；
- 不能转换为 `ExecutionPermit` 或 broker command；
- authorised proxy 路径与 shadow trial 路径调用同一 resolver，避免两套成交语义；
- entry 与 exit 都使用该 resolver，方向相关的一字涨跌停规则分别判定；
- shadow 入口写入的仍是 canonical proxy capital events，而不是 journal P&L。

这属于现有 DailyBarProxy 的边界扩展，不建设新的执行引擎。

## 9. 数据契约

### 9.1 SharedDecisionInput

每个 decision cycle 先形成一份共享输入，至少包含：

```text
trial_id
research_program_id
signal_session
decision_cycle_id
evidence_cutoff
evidence_root
regime_evidence_hash
candidate_set_hash
candidate_score_table_hash
ranking_algorithm_version
sizing_algorithm_version
risk_algorithm_version
calendar_version
execution_version
cost_version
shared_deadline_contract_hash
```

两臂各自再绑定：

```text
arm_id
portfolio_id
regime_entry_policy
admission_result_hash
eligible_candidate_view_hash
capital_checkpoint_hash
capital_version
```

共享字段不同是协议错误；arm-specific capital 字段不同是预期状态，不得被 `only_delta` 检查误报。

### 9.2 PairedDecisionRecord

两臂 proposal 都在内存中完成并通过差异验证后，Coordinator 才能在一个本地事务中写入：

```text
pair_id = H(trial_id, signal_session, decision_cycle_id)
shared_input_hash
champion_capital_checkpoint_hash
challenger_capital_checkpoint_hash
champion_arm_input_hash
challenger_arm_input_hash
champion_admission_result_hash
challenger_admission_result_hash
champion_proposal_hash
challenger_proposal_hash
champion_policy_hash
challenger_policy_hash
allowed_exogenous_delta = regime_entry_policy
created_at
previous_pair_hash
pair_hash
```

paired record 写入前不得修改任一 arm 账本。两个资本库之间不宣称跨库原子性；paired record 是 crash recovery 的 durable intent，后续写入依靠固定 event ID 幂等收敛。

### 9.3 PairedDayFact

每个市场日仅在两臂 checkpoint 都通过资本守恒与 projection rebuild 后生成：

```text
trial_id / market_session
paired_disposition
champion_checkpoint_hash / challenger_checkpoint_hash
champion_unit_nav / challenger_unit_nav
champion_log_return / challenger_log_return
challenger_minus_champion_log_growth
champion_cash / challenger_cash
champion_gross / challenger_gross
champion_drawdown / challenger_drawdown
shared_observation_root
unknown_count / pending_exit_count
previous_day_fact_hash / day_fact_hash
```

持久化 money、quantity 和 units 仍使用整数最小单位。log return 是由 checkpoint 中的精确 UnitNAV 派生的统计值，不反向成为资本真相；进入 hash chain 时按 SAP 冻结的高精度 Decimal 算法、精度和舍入规则编码为 canonical string，不保存平台相关的 binary float 真相。

### 9.4 PairedSessionDisposition

`SessionSpine.SessionStatus` 保持上位规范的现有值域。本 Trial 另派生一个 paired disposition，不覆盖 SessionSpine：

| disposition | 含义 |
|---|---|
| `PAIRED_VALID` | 两臂已从同一共享输入完成并通过 checkpoint |
| `SHARED_NO_ENTRY` | `NO_SIGNAL`、共享 evidence unknown 或共同 fail-closed；两臂 lifecycle 仍完整推进 |
| `SESSION_CANCELLED` | 仅由已验证的交易所日历 revision 产生 |
| `PROTOCOL_BREACH` | `NO_RUN`、非 gate 外生漂移、无法收敛或完整性失败 |

运行中可以有内部 `PENDING`，但 finalization 后每个 expected session 必须得到一个永久 disposition。late correction 可以追加资本和 outcome revision，不能悄悄把 primary disposition 改成更有利类别。唯一例外是交易所依法取消交易日：已验证的 calendar revision 可以追加 `SESSION_CANCELLED`，但必须保留此前 disposition，不得物理覆盖。

## 10. 状态推进

### 10.1 试验前

1. Governance 原子保留 Attempt/multiplicity budget 并 seal Trial/SAP。
2. 生成完整 enrollment expected-session spine。
3. 两条 proxy portfolio 从同一 genesis economic state 创建，但使用不同 `portfolio_id`、不同 checkpoint chain。共同起点 hash 覆盖 cash、units、positions、live orders、reserves、pending exits、receivables/payables、risk state 和 session watermark。
4. 验证 broker adapter、真实 account identity 和生产 authority 在依赖图中不可达。

genesis 后不接受单臂外部申购或赎回。治理要求的共同资本 correction 必须按同一 effective time 和金额镜像到两臂，并通过单位份额规则从收益中剥离。

### 10.2 每个 signal session

在冻结 T0 输入前，必须先处理截至 T0 close 已知的 entry/exit、费用、公司行动、correction 和 marks，并让两臂各自产生通过验证的 close checkpoint。Growth Kernel 只能读取这些 checkpoint，不能读取尚未入账的未来事件。

状态按以下顺序单调推进：

```text
INPUT_FROZEN
  -> DECISIONS_COMMITTED
  -> ENTRY_RESOLVED
  -> LIFECYCLE_RUNNING
  -> DAY_CHECKPOINTED
```

#### `INPUT_FROZEN`

Evidence Store 在 T0 cutoff 冻结证据 root。BTST producer 只运行一次，生成供两臂共享的候选集合。regime evidence 不合格时写入共享 no-entry intent，跳过两臂新仓计算，但继续退出与 checkpoint。

#### `DECISIONS_COMMITTED`

Coordinator 使用同一共享输入和两臂自己的资本快照计算 proposal。只有两臂都完成并通过 exogenous-delta 检查，才能写 `PairedDecisionRecord`。

#### `ENTRY_RESOLVED`

T+1 开盘 observation 在 Evidence Store 中只保存一次并内容寻址。两臂通过同一 proxy resolver 处理自己的 proposal；每个 event ID 从 `pair_id + arm_id + order_line_id + event_kind` 确定派生。

#### `LIFECYCLE_RUNNING`

两臂独立推进：

- cash、reserve、integer lots、gross 和 marks；
- T+10 open `ExitMandate`；
- 停牌、不可卖、partial/unknown exit；
- fee/tax、公司行动、bust 和 correction；
- entry halt 下仍持续退出、公司行动与对账。

#### `DAY_CHECKPOINTED`

两臂分别通过 `capital_conservation=PASS` 与 `projection_rebuild=PASS` 后，才生成 `PairedDayFact`。若任一臂失败，当日不能发布可用于统计的 paired fact。

不同 signal session 的状态机会因 T+1 入场和 T+10 退出而重叠；上述顺序约束单个 decision cycle，不要求组合等待上一批仓位结束。每日 checkpoint 必须汇总所有仍在途 cycle 的真实状态。

### 10.3 enrollment 结束与 run-out

`enrollment_end` 后不再产生新 entry proposal，Trial 进入 exit-only run-out。直到以下事实全部完成才可 final assessment：

- 两臂全部持仓与 exit mandate 达到预注册 finality；
- fee、tax、公司行动和已知 correction 已结算；
- 两臂最终 checkpoint 和 paired hash chain 通过；
- expected-session spine 没有未分类行。

到 `followup_finality_date` 仍存在未知 NAV、未解决退出或 blocking reconciliation 时，结论固定为不晋级；不能延长赢家的窗口或删除 pending 样本。

## 11. 执行语义

### 11.1 固定经济合约

```text
T0 close finalized -> 决策
T+1 open            -> 买入尝试
T+10 open           -> 第 10 个交易 session 的首次卖出尝试
```

entry 与 exit 都必须绑定同一 frozen execution version、calendar version、lot rule 和 price-boundary version。成本由 sealed `FeePolicy` 计算；本 Trial 注册时必须包含适用的双边滑点、佣金和卖出税费，不允许在 Coordinator 内散落常量。

### 11.2 不可成交与未知

- 缺失 bar、停牌、late command、价格冲突或方向相关的一字板锁死，不得补造成交。
- entry 无法证明成交时为 `UNKNOWN/NO_FILL`，释放对应 reserve，现金不减少。
- exit 无法证明成交时保持 pending mandate；不得用 stale close 或未来可见价格结束仓位。
- 不知道可卖数量时不得超卖；后续确认数量后由同一 mandate revision 继续。
- 日内 high/low 只能按 frozen DailyBarProxy 判定表使用，不能反推出一个不存在的开盘成交。

### 11.3 每日估值

每日 NAV 必须从两臂各自的资本 checkpoint 派生，包含：

- settled 与 pending cash；
- open/exit-pending positions；
- reserves、fees、tax 和 receivable/payable；
- 公司行动与外部资金流；
- 可审计 mark 或预注册 conservative stress。

报告不得以 realized trade P&L 加总替代 UnitNAV 路径。

## 12. 失败语义与完整性门

### 12.1 共享输入失败

regime、候选、日历或其他预注册共享 evidence 在 cutoff 前不可用时：

- 两臂都不新增风险；
- 已有退出继续；
- session 记录 `DATA_UNKNOWN` 与 `SHARED_NO_ENTRY`；
- 缺失原因进入 attrition 报告。

不得只让 Champion 继续而把 Challenger 缺失样本删除，也不得默认 regime 为 normal。

### 12.2 paired commit 前失败

任一 arm 的 producer/kernel 调用失败，或发现除允许 policy/内生 capital state 外的差异时：

- 两个 proposal 都不持久化；
- 两臂都不新增风险；
- exits/lifecycle 继续；
- final disposition 为 `PROTOCOL_BREACH`，除非在 session finalization deadline 前以相同 ID 完整恢复。

### 12.3 paired commit 后崩溃

使用固定键重放：

```text
(trial_id, signal_session, decision_cycle_id)
```

arm 和经济 event ID 不随 retry、epoch 或进程重启变化。已写入一臂而另一臂未写入时，从 durable paired record 补齐缺失事件；禁止删除成功一臂、换 ID 重跑或重算更有利 proposal。

### 12.4 资本或投影失败

任一臂出现 conservation、projection rebuild、checkpoint chain 或负不可能持仓失败时，Trial 锁存 entry halt：

- 两臂停止后续新仓，避免继续扩大不可比较状态；
- 两臂 exits、公司行动、对账和 correction 继续；
- 未解决 breach 阻断 promotion。

### 12.5 行为漂移

policy、classifier、producer、ranking、sizing、cost、execution、calendar、evidence schema 或统计规则发生变化时，当前 Trial 不再 enroll 新 session。后续行为必须新建 fingerprint、Attempt、Trial/SAP 和 expected-session spine。

### 12.6 revision 与样本身份

- late fee、bust、correction 和 outcome restatement 只能追加 revision，不覆盖 canonical event。
- 同一 plan-line 的 revision 不增加成熟 outcome 数。
- 同一 expected session 不得删除、改名或换 evaluation-unit ID 重用。
- `PROTOCOL_BREACH` 在 fixed assessment 时仍未解决，promotion Boolean 固定为 false。

## 13. 统计裁决

### 13.1 主要估计量

完整锁定窗口内，每个市场日计算：

```text
d_t = log(UnitNAV_challenger,t / UnitNAV_challenger,t-1)
    - log(UnitNAV_champion,t / UnitNAV_champion,t-1)

DeltaG = mean(d_t)
```

符号固定为 `Challenger - Champion`。截至 commit `055c3a0d`，现有 `evaluate_predictable_adaptive` primitive 使用的是 `Champion - Challenger` 方向，且面向 adaptive fold；实现不得通过交换参数名绕过语义。应在现有统计模块内增加或修正一个命名明确的 frozen paired evaluator，并用方向反转测试锁定契约。

Trial 主推断使用预注册的单侧 95% 下界：

```text
LCB95(DeltaG) >= incremental_MEE
```

等于阈值视为通过，与上位规范的 `>=` 一致。不能只检验大于零。

`d_t` 覆盖锁定窗口内每个未取消市场日，包括 cash day、no-signal day 和两臂当日 proposal 相同的日期；不得只保留 gate 直接触发日。主推断属于 `FROZEN_POLICY` 的完整配对市场日序列，使用 SAP 冻结的 block-bootstrap/HAC 交叉约束并取最保守结论。decision/disagreement day 只用于覆盖与 ESS 门，不替代完整路径。

### 13.2 绝对增长门

Champion 与 Challenger 还要分别计算相对冻结现金基准的 absolute excess log growth。当前成本和 2× slippage stress 下，两臂的保守下界都必须达到 sealed `absolute_MEE`；`Challenger - Champion` 的增量 LCB 在两种成本情景下也都必须达到 `incremental_MEE`。若 benchmark 在 Trial seal 时不可用，只能继续 shadow，不能产生 promotion candidate。

2× slippage 不是在最终收益上减一个常数。assessment 必须从同一 genesis、原始 shared decision inputs 和 frozen observations 重新计算 proposal，并按时间顺序完整重放两臂的 reserve、fills、cash、capacity、positions、exits 与 NAV；不能在 stress 已改变 reserve、sizing 或 capacity 时继续套用 current-cost proposal。

### 13.3 独立覆盖门

以下门槛必须分别报告并全部满足：

- Challenger 至少有 150 个按预注册 plan-line/economic-contract key 去重并达到 finality 的成熟 outcome；Champion outcome 只作同窗基线，不能补足 Challenger 的计数。同一 Challenger plan-line 的 partial fill 或 revision 始终只算一次，blocked/no-fill 不能伪装成持仓收益。
- 至少 60 个独立 decision day，且实际组合分歧的 governance-minted paired evaluation units 满足 `ESS >= 60`；同一日的 Champion/Challenger 只能共享一个 evaluation unit。
- 至少 80 个不同 ticker。
- 至少 12 个月前向覆盖。
- 至少经历一个预注册 adverse market window。
- 日期、行业和 ticker 集中度不超过预注册上限。

完整连续组合路径、150 个 mature outcome 和 60 个 decision-day/ESS 是三类独立事实，不能互相替代。

### 13.4 尾部与容量门

两臂都要满足预注册的：

- MDD 绝对上限；
- CDaR 与 15% 回撤后 overshoot 上限；
- Challenger 相对 Champion 的 non-inferiority margin；
- liquidity、gross、cash、unknown 和 pending-exit 上限；
- 当前容量与 stress capacity 场景。

MDD、CDaR 和 halt 恢复时长只能从连续资本路径计算。block bootstrap 不能拼接独立 NAV 片段后声称状态型风险安全。

### 13.5 裁决 Boolean

promotion eligibility 为以下谓词的逻辑与：

```text
timeline_complete
AND no_unresolved_protocol_breach
AND both_capital_conservation_pass
AND both_projection_rebuild_pass
AND paired_hash_chain_pass
AND minimum_evidence_pass
AND absolute_growth_pass_current_cost
AND absolute_growth_pass_2x_slippage
AND incremental_growth_lcb_pass_current_cost
AND incremental_growth_lcb_pass_2x_slippage
AND tail_non_inferiority_pass
AND capacity_pass
AND multiplicity_and_consumption_pass
```

风险改善不能替代增长证明。Challenger 即使显著降低回撤，只要增量增长 LCB 未达到 MEE，仍保持 shadow；增长通过但尾部门失败，同样不得晋级。

### 13.6 诊断指标

以下指标可以展示，但不能进入 promotion Boolean：

- 胜率与 Wilson interval；
- payoff、最大单票盈利和平均单票收益；
- normal、risk_off、crisis 子组表现；
- setup hit rate、候选数和被 gate 阻断数；
- 单个 ticker 或单个日期的贡献。

### 13.7 固定评估与多重检验

- fixed assessment 前不得每日窥视后选择最好日期停止。
- 伤害或 futility 早停只能按 SAP 预注册规则触发，且仍消耗 Attempt/multiplicity budget。
- 改 gate 组合、阈值、MEE、block rule 或 primary metric 都是新 Trial。
- PASS 只产生 inactive promotion candidate，仍需治理审评和另行 activation。
- `DAILY_BAR_PROXY` 证据只能支持同模式候选；broker 必须新建 `BROKER_CONFIRMED` Trial。

## 14. 报告契约

报告必须来自 `PairedTrialProjection`，至少同时显示：

- Champion、Challenger 的绝对 UnitNAV、log growth、MDD、CDaR、gross、cash；
- `Challenger - Champion` 点估计、LCB、MEE 和符号定义；
- current-cost 与 2× slippage 结果；
- expected-session 总数及四类 paired disposition；
- `NO_RUN`、`DATA_UNKNOWN`、unknown fill、pending exit 和 protocol breach；
- mature outcomes、decision days、ESS、ticker、月份与 adverse-window 覆盖；
- as-observed 与 restated-final 两套路径，禁止择优混接；
- Trial/SAP/policy/evidence/cost/execution/checkpoint hash。

报告不得自行重算 NAV，不读取 mutable journal 作为资金真相，也不得使用“edge 已证实”“可直接落地”等超出门禁的文案。未满足任一门时 headline 固定为 `NOT_ELIGIBLE`；全部通过时也只能写 `INACTIVE_PROMOTION_CANDIDATE`。

## 15. Legacy court 的处理

`scripts/backtest_paper_loop.py` 及 `block_regimes`、`only_setups` 参数可以继续服务诊断，但必须满足：

- structured output 明示 `execution_mode=RESEARCH_RECONSTRUCTION`；
- 明示 `promotion_eligible=false`；
- 不生成 Trial/SAP、Stage、authorization、permit 或 `PRIMARY_PROMOTION` consumption；
- 继续由 `scripts/v3_import_research_evidence.py` 强制导入为 `PRIOR | RESEARCH`；
- 决策包若保留，必须标注其部署解释已被 owner review 否决。

本设计不要求删除历史 artifact，也不把修正其研究质量列为前向 Trial 的前置条件。若未来修复 court，其结果仍保持 `RESEARCH_RECONSTRUCTION`，除非另有完整 PIT 历史与独立设计。

## 16. 测试策略

### 16.1 纯语义测试

- normal：两臂 regime admission 都为 ALLOW。
- crisis/risk_off：Champion ALLOW，Challenger BLOCK。
- unknown/invalid revision/stale version：两臂共享 no-entry。
- `RegimeEntryPolicy` 不读 I/O，输入相同则 canonical output/hash 相同。
- 任何第二个外生差异都触发 protocol breach。

### 16.2 组合与守恒测试

- 两臂从同一 genesis economic state 启动，但 checkpoint chain 独立。
- gross cap 跨日约束，不能像 legacy court 一样按日清零 exposure。
- cash、reserve、integer lots、fees、tax、units 和 NAV 全部守恒。
- T+1 open entry、T+10 open exit、重叠持仓和每日 mark-to-market 可连续重建。
- 正常 regime 且两臂资本状态仍相同时，proposal 与 NAV 逐字节一致。
- gate 造成一次分歧后，后续 arm-specific capital 差异被视为内生状态，不误报为外生漂移。

### 16.3 执行边界测试

- missing、suspended、late、conflicting price 和方向相关的一字板均不伪造成交。
- entry unknown 释放 reserve、保留现金。
- exit unknown 保留 mandate，后续可执行 session 继续，不用 stale close。
- 佣金、双边滑点和卖出税费来自同一 sealed FeePolicy。
- shadow plan 无法转换成 `ExecutionPermit`，无法进入 broker dispatcher。

### 16.4 故障注入

- 双臂计算之间崩溃：无 paired record、无 arm entry side effect。
- paired record 后、一臂写入后崩溃：以相同 event ID 补齐另一臂。
- 重复 observation、重复 fee、重复 correction：经济事实只作用一次。
- capital/checkpoint/rebuild 失败：两臂 entry halt，exit 与 correction 继续。
- 版本漂移：旧 Trial 停止 enrollment，不能热改继续积样本。

### 16.5 可重验与属性测试

- 清空 projection 后，仅从 canonical evidence、paired records 和 capital events 重建，结果与原 projection 逐字节一致。
- 文件 glob 顺序、进程重启和消息重复不改变 proposal、event ID、NAV 或 hash chain。
- expected session 不允许 UPDATE/DELETE；signed calendar cancellation 只追加 revision。
- 当两臂策略相同且资本状态相同时，paired delta 恒为零。
- 交换 Champion/Challenger 后，增量序列符号精确翻转；锁定 `Challenger - Champion` 方向。

### 16.6 统计与验收测试

- 缺少任一 evidence、ESS、月份、adverse、完整性、增长或尾部门时，结果只能 `NOT_ELIGIBLE`。
- 只有所有 Boolean 谓词同时为 true 才生成 inactive candidate。
- 风险改善但 growth LCB 不达 MEE 时拒绝。
- growth 通过但 tail/capacity 失败时拒绝。
- late revision 不增加 outcome/evaluation-unit 数。
- `DAILY_BAR_PROXY` 结果不能被 authorizer 当作 `BROKER_CONFIRMED`。

## 17. 实现收边与完成门

实现计划必须保持以下收边：

1. 新增架构单元只有 `RegimeEntryPolicy`、`PairedShadowTrialCoordinator`、`PairedTrialProjection`；其余改动是对现有 primitive 的契约扩展或接线。
2. 不新增第二套 NAV、fee、execution、statistics 或 evidence store。
3. 不写 `data/paper_trading*` legacy journal/state，不修改用户现有历史数据。
4. 不读取 broker credential、endpoint 或真实 account identity。
5. 不产生 active authorization、permit、outbox 或 broker command。

完成门至少包括：

- 新增测试与相关 v3 测试全绿；
- `capital_conservation=PASS`、`projection_rebuild=PASS`；
- paired decision/day-fact hash chain 可重验；
- fault injection 证明 crash replay 恰好一次；
- AST/依赖边界证明 trial runtime 无 governance activation、gateway send 和 broker 写面；
- `git diff --check` 无输出；
- 文档、契约 snapshot、机器可读 policy 候选和迁移说明与行为变更同步；
- 运行结束只得到 shadow Trial 状态，不改变 v2 或任何生产 authority。

## 18. 维护与变更规则

本规格从属于 2026-07-19 Evidence-Gated Growth Kernel 权威设计。若两者冲突，先修订并重新批准本规格，不得以实现便利解释冲突。

以下变更必须新开行为世代和 Trial：

- regime 定义、输入、阈值或 classifier 改动；
- gate 从 admission 移到 ranking/sizing；
- setup、strength、排序、仓位或 risk policy 改动；
- T+1/T+10、费用、涨跌停或 unknown 语义改动；
- primary metric、MEE、LCB、ESS、tail gate 或 assessment window 改动。

未来维护者应先核对 Trial/SAP hash、policy fingerprint、execution/cost version 和两臂 genesis checkpoint，再解释任何收益差。Markdown headline 不是事实来源；canonical evidence、capital events 和可重建 projection 才是。

## 19. 最终安全声明

本设计不会把 `+44.9%` 转化为部署批准，也不会预判 regime gate 最终胜出。它把问题改写为一个可以被未来事实否证的前向试验：共享可用信息，只改变一个策略选择，用两条守恒组合路径观察增量长期增长。

在 Trial 达到完整时间窗、样本覆盖、增长、尾部、容量和完整性门之前，regime 继续保持 shadow。即使全部通过，结果仍只是 `DAILY_BAR_PROXY` 同模式的 inactive promotion candidate；真实 broker 必须从新的 `BROKER_CONFIRMED` Trial 开始。
