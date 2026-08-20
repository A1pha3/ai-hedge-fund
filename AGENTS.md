# AGENTS.md — AI 助手项目指令

本文件给 AI 助手（zcode / claude / codex 等）提供本项目的关键上下文。
**修改代码前必读**，尤其是数据完整性部分。

## 当前 legacy 项目概览

A 股每日选股系统。用户每天跑两个命令获取次日买入信号：
```bash
uv run python src/main.py --auto           # 收盘后跑全流程, ~4PM 后
uv run python src/main.py --daily-action   # 读缓存, ~3 秒, 输出次日 BUY 信号
```

- **`--auto`**：四策略因子评分（trend/mean_reversion/fundamental/event_sentiment）→ score_b → investability 排序 → Top 10。存 `data/reports/auto_screening_YYYYMMDD.json`。
- **`--daily-action`**：凸性 setup（BTST 涨停突破 T+10、OversoldBounce 超跌反弹 T+5，默认暂停）→ Kelly 仓位 → paper trading。**在当前 legacy 实现中与 `--auto` 是两套独立系统**，只共享缓存数据；目标态会共享不可变 Evidence Store/Outcome/Capital Truth 基础设施，但 producer namespace、edge 与评分永久独立。
- 入口在 `src/cli/dispatcher.py`（命令分发），核心逻辑在 `src/screening/offensive/`。

## 长期目标架构宪章（Revision 2 于 2026-07-26 已批准，尚未全部实现）

完整、唯一权威设计见 [`docs/superpowers/specs/2026-07-19-evidence-gated-growth-kernel-design.md`](docs/superpowers/specs/2026-07-19-evidence-gated-growth-kernel-design.md)。本节是所有 Agent 修改、实现或审阅相关代码时必须遵守的短约束；下文“当前状态”描述的是 legacy 现实，**不得据此声称目标架构已经上线**。若旧文档与该设计冲突，以该设计为准；实际行为仍以代码、版本化策略快照和可重验台账为准。

1. **两个生产者保持独立**：`--auto` 与 BTST 不合并分数。目标态初期只有 BTST 可申请交易授权；`--auto`、OversoldBounce、regime、streak、composite 等均为 shadow/feature，未经新的同模式前向证据不得影响准入、排序或仓位。
2. **唯一经济目标与固定合约**：优化扣除真实成本、约束和现金占用后的组合单位净值长期对数增长；可执行合约固定为 T0 收盘后决策、T+1 开盘买、T+10 开盘卖。胜率、赔率、IC 和单票收益只作诊断，不能替代完整组合路径证据。
3. **执行模式分池，真实账户统一守恒**：`RESEARCH_RECONSTRUCTION`、`DAILY_BAR_PROXY`、`MANUAL_CONFIRMED`、`BROKER_CONFIRMED` 的业绩、NAV 和晋级样本永不混算；同一真实 broker account 的全部成交、费用、现金和公司行动必须进入唯一 `AccountCapitalTruth`，不能按模式拆掉真实资本事实。
4. **三层事实独立**：PIT 数据 readiness、策略 edge 证据、资本/台账真相互不替代。未知、过期、版本不匹配、执行不确定或不可重验时禁止新增风险，但真实退出、公司行动、对账和补偿事件继续。
5. **配置不是权限**：本地 JSON、环境变量、CLI 参数和未激活签名只是候选输入。只有 Governance Control Plane 签发并单调激活的 `TrustBundle`、`PolicyActivation`、Trial/SAP/Stage、授权及迁移/broker/灾备 manifest 才能改变权限；producer、CLI 和 Agent 不持有这些签发能力。
6. **授权是完整组合包络**：每个 portfolio 同时最多一个 active `CapitalAuthorizationEnvelope`，kind 为 `EDGE | EXPLORATION | RECOVERY`，必须绑定账户、mode、policy/trust/authority/risk epoch、完整 target portfolio policy、`lineage_grants[]`、总 gross cap 和 stage/program loss budget。多个 lineage 不能机械叠加；含 exploration 时所有探索合计最多 2%，首次 broker 且无既有 EDGE 时整个 portfolio 也最多 2%。
7. **唯一 entry 线性化域**：Growth Kernel 是纯函数，只输出完整 `PortfolioDecision` proposal；Capital Gateway Authority Store 在同一事务验证 active policy/envelope、`CapitalRiskSnapshot`、风险/损失锁存、permit、期限与 fence，原子 reserve 并发布 `PortfolioDecisionSeal`。经济幂等键固定为 `(portfolio_id, signal_session, decision_cycle_id)`，不得把 epoch 塞进 key 绕过冲突。
8. **发送前最后一次授权检查**：entry 状态必须按 `SEALED -> PERMITTED -> OUTBOX_DURABLE -> SEND_CLAIMED -> SUBMISSION_AMBIGUOUS | BROKER_ACK` 单调推进；`SEND_CLAIMED` 是最终发送权线性化点，必须在 Gateway 同一事务重新验证并消费全部版本/nonce/deadline。只在券商能力测试证明同一 `client_order_id` 幂等时才可同 ID 重试，绝不能换 ID 猜测重发。
9. **entry 与 exit 分道**：新仓必须消费有效 envelope；`ExitMandate` 只由权威经济持仓派生并由 durable scheduler 推进，不依赖 edge、readiness、stage loss 或 entry kill switch。未知可卖数量时不得超卖；bust/correction 使头寸重现时必须重开退出义务。
10. **时点不可回填伪造**：必须满足 `T0 close finalized < seal_creation_deadline < permit_issue_deadline < ExecutionPermit.expires_at <= gateway_send_deadline < broker auction cutoff`。T+1 只能按冻结机械条件缩减或取消，不能看到开盘后增加；未成交、部分成交、撤单未确认、停牌/涨跌停未知必须保留真实状态，禁止用日线高低价或事后价格补造成交。
11. **风险与 stage loss 各作用一次**：回撤不足 10% 不缩放，10%–15% 对未缩放 lineage 和组合 gross ceiling 线性降至 0，15% 锁存 `RISK_HALTED`。stage loss budget 在激活时冻结为整数分，并与 fill/fee/mark/reserve 同一资本事务按 `max(previous, instantaneous_charge)` 单调消费；盈利、反弹、重命名或换 epoch 均不能回补。恢复必须新 Risk/Authority Epoch，以 `RECOVERY` envelope 在组合 2% cap 内重启并计入全部继承风险和历史 loss consumption。
12. **证据是受信时间轴，不只是双时间戳**：保存原始 payload，并记录 `effective_at`、`provider_published_at`、`observed_at`、Evidence Store 控制的 `ingested_at`/`commit_sequence`、`available_at`、revision/supersedes/active revision 和 mode。官方 OOS 只能消费信号 cutoff 前已入库的数据；fingerprint 只证明一致性，不能授予发行权限。
13. **行为变化开启新证据世代**：策略、过滤、排序、仓位、成本、执行或数据口径变化时，更新 semver/behavior fingerprint/policy epoch，并在不可改名的 economic lineage/research program 下预注册 champion/challenger、Trial、SAP、Stage 与 expected-session spine。Attempt reservation 与 Trial/SAP seal 必须原子；failed/abandoned 也消耗全局 multiplicity budget。
14. **样本不能换 ID 复用**：`EvidenceConsumptionLedger` 对 `(research_program_id, evidence_id, PRIMARY_PROMOTION)` 与 `(research_program_id, governance_minted_evaluation_unit_id, PRIMARY_PROMOTION)` 分别唯一；partial fill、late fee 和 outcome revision 不增加 plan-line outcome 数，decision-day/ESS 是另一独立评价单元。完整连续组合路径、150 个成熟 outcome 与 60 个 decision-day/ESS 是不同门槛，不能互相替代。
15. **资本真相必须精确且可更正**：持久化 money/quantity/unit 全用整数最小单位，不保存 float 真相；显式 genesis units、`pending_redeemed_units`、`TERMINATING/TERMINATED`、`INSOLVENT` 和 as-observed/restated-final。每个经济事实只有一个 canonical event；公司行动用有理数 entitlement/cash-in-lieu，继承 lot/exit；历史订单 terminal 后发生 bust/correction 仍追加 revision、重投影资本，负持仓是 reconciliation halt，不能 clamp 为 0。
16. **broker 与迁移必须证明外部完整性**：broker 前须绑定账户/环境指纹、可信时钟、authenticated raw envelope、分页/cursor/retention、client ID 幂等、集合竞价 TIF/cutoff、独立退出限流和 credential/session/network fencing，并有 `BrokerEnablementManifest` 与 `DisasterRecoveryManifest`。v2→v3 前须有签名 `MigrationApprovalManifest`、共享 durable inbox、live-order adoption manifest、精确 source/target 守恒、handoff cursor 和包含全部版本/root/fence 的 CAS；旧 writer/旧会话必须失权。
17. **先 shadow，后逐模式 canary，允许不交易**：v3 与 v2 分账，完成版本绑定、资本守恒和 CAS authority flip 后 v2 才只读；shadow 类型/namespace 必须让 gateway 技术上无法接受。proxy/manual 的 2% 不能冒充 broker 证据；首次 broker 另开 `BROKER_CONFIRMED` Trial/Stage 和 one-shot 2% `EXPLORATION` envelope。每个 2%→5%→最多 10% stage 都使用新的、不复用的同模式前向证据；`--auto` 另行证明。任何关键门未过时，正确结果是 no-trade。

任何影响上述语义的代码变更，必须同步更新权威设计、机器可读策略快照（实现后）、契约/故障注入测试和迁移说明；不得通过修改报告文案掩盖台账、授权或证据冲突。

### 当前 v3 已实现范围（2026-08-05）

已实现 Plan 01 Revision 2 Tasks 1–5 的无存储 strict/frozen **候选领域契约、纯验证与 final structural ports**：六个 current runtime-checkable ports 只提供结构接口，不提供实现或权限；active evidence query 是四种 concrete `EvidenceRecord` 的闭合 union，verifier 显式标注 current-head witness 与 trusted time。Plan 04 前，production `src` 的 `*.py`/`*.pyi` 必须保持 zero static `GrowthKernelPort` references；仅允许 `contracts/ports.py` 的 top-level Protocol 定义/精确 list-or-tuple `__all__`，以及 `contracts/__init__.py` 的 top-level 精确 import/`__all__`。There is no downstream typing or runtime exception：import、attribute、alias、annotation、runtime check、quoted/reflection token、stub 与 contracts star import 均拒绝。Plan 04 只有在 concrete strict/frozen `KernelInput`/`NoTradeDecision`、真实入口重验及独立审阅的 replacement gate 同时落地后才能改变此边界，不能把 generic port 当作预授权。Revision 1 primitives 继续按 `dccb76c5` 冻结；current policy/trust verifier 的 exact-type/non-virtual-dispatch 防御、active plan-record 绑定和 unknown publication fail-closed 语义不变。所有 witness、`Verified*` 结果和 ports 都不是 activation token 或权限。

Dynamic or fragmented string construction is outside this static proof. Plan 04 must keep default-deny and use new RED-to-GREEN TDD to allow only an exact consumer module and the exact `GrowthKernelPort[KernelInput, NoTradeDecision]` signature; alias, runtime-check, and star-import exceptions remain forbidden.

旧 Revision 1 接口的 repository acceptance scan 覆盖整个 production `src`，只排除两个冻结 compatibility 模块；`tests` 不属于这项生产扫描。控制文档另用 token-aware lexical historical-context guard，保证旧名称同一行带历史标记；该 guard 只是词法约束，不是自然语言语义证明。

Tasks 1–5 implementation is present and the Plan 01 completion gate is closed (2026-08-04): the checked-in snapshot matrix (`tests/offensive/v3/contracts/test_revision2_snapshot_matrix.py` + `fixtures/revision2/`) covers all public decision/capital/execution/evidence/trust/policy model schema goldens, strict round-trip and canonical hashes, independently recomputed artifact hashes, protected domain preimages, public enum/alias types and port signatures. Gate closure is a re-verifiable documentation statement; it does not make any port, policy candidate, or verified witness active authority.

Plan 02（AccountCapitalTruth 与 Gateway Authority Store）primitives 已实现（2026-08-05）：append-only 资本台账（整数 quanta、SQLite WAL+FK、UPDATE/DELETE 不可变触发器、Alembic 迁移 0001–0005）、exact fills/fees/reserves 投影与守恒重验、公司行动 lot/exit 继承、NAV 单位与生命周期、`CapitalRiskSnapshot` 与 stage loss 单调消费、bust/correction 重投影与 exit 义务重开（负不可能状态原样保留、从不 clamp）、session checkpoints、backup/restore 与 `capital.verify` 全量验证（`capital_conservation=PASS projection_rebuild=PASS`）。这些是资本真相与权威存储的 primitives：不读 producer/evidence 库、不激活授权、不产生可执行 seal、不发送订单、不连 broker；capital version、risk epoch 与 stage loss budget 均不构成权限。

Plan 03（Evidence Store、统计评估与治理授权）primitives 已实现（2026-08-05）：受信证据时间轴（blob-before-envelope、store-owned `ingested_at`/`commit_sequence`、strict revision 链与 cutoff-correct active 投影、issuer namespace 隔离）、trial/SAP seal 与 expected-session spine（calendar revision 走 `SESSION_CANCELLED` 不删除）、mode-pure Outcome Finalizer（一个 plan-line contract 一个成熟 outcome，partial fill/fee revision/correction 不膨胀样本，EXIT_PENDING 不终结）、样本不可复用（两条独立 PRIMARY_PROMOTION 唯一键 + 全局 multiplicity budget，failed/abandoned attempt 同样消费）、保守统计（excess daily log growth、单边 95% LCB、ESS/MDD/CDaR、最小证据为独立谓词、cutoff 后证据不入 OOS）、EDGE Authorizer 与 Governance EXPLORATION/RECOVERY 分权签发（EXPLORATION 仅 BROKER_CONFIRMED 且 ≤2%、RECOVERY 引用全部继承 risk/loss 版本、签名失败零残留）、dependency-fix fence ACK 协议与 `scripts/v3_import_research_evidence.py`（legacy 强制 `PRIOR | RESEARCH_RECONSTRUCTION`，拒绝 broker-mode legacy claims）。所有签发的 envelope/授权候选均 INACTIVE：无 Capital Gateway activation CAS、无 entry permit、无发单；下一步 Plan 04（Growth Kernel 与 proxy execution）。

Plan 04（Growth Kernel、Capital Gateway、Exit、Proxy/Manual Execution）primitive 已实现（2026-08-07，Task 9 集成验证通过、v3 套件 1987 绿）：纯 kernel（admission/risk/sizing/decide/models，AST 边界测试锁定无 storage/network/v2 import，replay 逐字节确定、风险/容量 scaling 只算一次）；Capital Gateway 入场准入（publish_entry 单事务 seal + 精确 worst-case reserve + 经济幂等键 `(portfolio_id, signal_session, decision_cycle_id)` 不可被 epoch/retry 绕过；SEALED→PERMITTED→OUTBOX_DURABLE→SEND_CLAIMED→SUBMISSION_AMBIGUOUS|BROKER_ACK + TOMBSTONED 状态机；claim_send 是发权最终线性化点，事务内重验 seal/permit nonce/durable outbox/reserve/deadline/全部 authority+capital+risk+stage+fence truth 再消费 nonce；read-only `entry_state`/`active_seal` 投影，无 portfolio-wide listing）；独立 ExitLane（exit mandate derive/claim/reconcile + `exit_state` 投影，halt 不阻断 exit，entry 失败不得阻塞/抹除/超卖 exit）；DAILY_BAR_PROXY（锁定日线判定表：missing/suspended/late/一字 lock→UNKNOWN 保现金，普通触及→min/max(open,limit)，绝不 stale-close；qty=0 permit 行短路 NO_FILL）与 MANUAL_CONFIRMED（官方 OOS 验→attributed fill；协议外成交→三件套 sentinel lot `unattributed:{execution_id}` + `CapitalRiskSnapshot.unattributed_risk_cents` + `ReconciliationLatchState.RECONCILIATION_HALT`）。capital kernel 与 gateway 是两个物理 SQLite，跨库 crash 收敛靠 fill/fee 幂等键 + divergent 前置检查，不靠跨库事务。

这些仍是离线 primitive：**proxy/manual 不得标 BROKER_CONFIRMED**；无 broker 网络适配器、runtime 保持关闭、本 plan 未启用任何真实 broker 调用或生产资本激活；kernel/gateway/exit/execution record、seal、permit、verified witness 均不构成权限或真实资本事实。

Plan 05（服务/CLI/Scheduler/报告）primitive 已实现（2026-08-08，Task 9 集成验证通过、v3 套件 2255 绿）：可信时钟 + 进程身份 + UDS 基础（TrustedClock 单调序列+wall、rollback/skew 检测门控时间敏感 entry；socket/lease ACL 工具 V3_SOCKET_MODE=0o600）；Publisher/Finalizer/Authorizer/Governance 服务对象（进程内构造）；Capital Gateway API 读 facade（risk_snapshot/authority_state/entry_state/active_seal/exit_state/lifecycle_state quiet 读不增长 version，无 portfolio-wide listing）；独立 durable lifecycle scheduler（ExitMandate derive/claim/reconcile）；Auto/BTST producer 适配器；AutoFlow（--auto 三步独立、OFF 零调用）+ DailyActionFlow（--daily-action 四步独立：capital 只读投影+lifecycle 义务+影子决策+v2 对比）；ledger-derived ReportingService（9 级 headline、capital_read_status 与 kernel BLOCK 语义对齐、partial_failure 不崩溃）。Task 9 CLI 库层接线：src/cli/v3_shadow.py 两入口按 policy runtime_mode（off|shadow）门控；ephemeral 信任上下文 + 合成 authority（确定性 grant 与 BTST producer 信封逐字一致，协同 S2b family_id=BTST_FAMILY 修复使 kernel 真正 ADMITTED 而非恒 BLOCKED）+ 防御性 capital reader（ledger 缺失→graceful）+ rc 保护（v3 失败不改写 v2 退出码）+ AST ACL 守卫（不 import governance/execution/gateway 写面、不调用 activate_*/publish_entry/claim_send 写方法）。

**安全边界（shadow-only in-process 偏差，owner 知情批准）**：Plan 05 是库层编排（CLI 进程内构造服务持 capital sqlite 句柄，shadow 只读），非 Plan Architecture 要求的 privileged worker 独立进程+UDS（留 Plan 06+）。补偿控制：(1) AST 守卫锁定 CLI 无写面 import+调用；(2) 物理独立 v3 namespace（data/v3_shadow/，绝不写 v2 reports）；(3) 证据 signer 进程内 ephemeral key（不读持久化 keystore）；(4) execution_authority 恒 none。不构成权限、无真实资本激活、不连 broker、无 authority flip（INACTIVE→ACTIVE）、合成 authority 非授权（仅观测用解锁 admission）。

Plan 06（迁移/shadow/canary）primitive 已实现（2026-08-08，migration+canary 套件 118 绿、v3 全套 2373 绿）：签名 MigrationApprovalManifest 验证（双人 attestation + Ed25519 + 短时窗口强制）+ v2 只读盘点（immutable URI、逐项 section root、不可归因表/NULL 即阻断）+ durable 外部收件箱（append-only、幂等去重、projected/acked 两阶段）+ CompatibilityWriter（单写者 lease、v2 commit→ACK→release、fence 一次性）+ 线性迁移状态机（DISCOVERED→…→V2_READ_ONLY、跳步/回退/异 root 冲突拒绝）+ 逐项守恒核验（cash/positions/plans/pending_exits/fees/counts 六节点名漂移）+ 空 adoption 证明（v2 无可表示 live order；永不重提交）+ 单库 authority CAS flip（preimage 逐字段绑定、并发恰一成功、flip 后 entry 保持 fenced 至 final reconciliation）+ shadow parity 审计与差异分类（EXPECTED_POLICY_CHANGE/DATA_MISMATCH/KERNEL_BUG/LEGACY_BUG/UNKNOWN，阻断类门禁）+ 2% canary 激活守卫（mode/kind/cap/budget/trust/risk/NAV 前提，EXPLORATION 一律拒绝，永不授予 broker authority）+ monitor（maintain/tighten/fence/drain，exit 恒继续，latch 恢复需 RiskEpochStarted+高 epoch PolicyActivation+RECOVERY envelope 三件齐全，永不自动晋升）。CLI：scripts/v3_migration.py（mutation 子命令需 --manifest 且默认 dry-run）与 scripts/v3_shadow_audit.py（--enforce-gate 门禁）。**仍无任何真实迁移/flip/canary 激活发生；全部为离线 primitive 与演练工具。**

BTST regime 前向配对影子试验（Tasks 1–14）当前只有**契约、存储、runner/replay/evaluator primitive 与 fixture 驱动测试**，不等于可运行的官方前向 Trial。已存在的范围包括 Champion=`IGNORE` / Challenger=`NORMAL_ONLY` 双 policy 绑定、`PolicySnapshot` schema-major 2、`ShadowDecision` schema-major 4、原子 pair commit、`SessionSpine`、`ForwardPairedTrialRunner`、`ForwardTrialReplayEngine`、frozen paired evaluator/`TrialAssessmentProjection`、对抗 fault campaign 与 AST import 边界守卫；这些测试证明受控 fixture 下的组件不变式，不能证明真实组合路径已接通。

**前向 Trial 接线 Phase 1–4 primitive（2026-08-20，四轮对抗审查后落地，v3 套件 2960 绿）**：① 交易排程证据发布（`v3/evidence/trading_schedule.py`——恰 10 后继会话切片指纹身份：`calendar_version` 为权威身份 `sse-sessions-v1`（policy 一次钉死）、`calendar_artifact_hash` 只绑消费切片（窗口外日历追加零扰动、窗口内修订=新证据记录追加而旧决策对旧切片依然可验）；blob 先行+信封绑定+注入 signer，`available_at` 只来自注入 clock 且**发布必须早于该 session 的 trusted_evidence_cutoff**（spine 注册时预发布，非 18:01 晚间管道）；同切片晚签 = store 的 `evidence_id_conflict`；复核面 `schedule_from_record` 三重交叉② `ForwardBtstProducerPort` + `committed_candidates`（`paired_trial.py`——从测试鸭子协议升为 src Protocol，`BtstProducerApi` 天然满足；发布恰一次→store 复核→`CommittedBtstCandidate` 四重绑定 fail-closed）。③ `freeze_shared_input` 纯构造器落地（throw→实现：bundle 供身份/哈希，外部参数接排程回执/evidence merkle/stage 绑定/registry_epoch/cutoff；fail-closed 下沉到 `ShadowSharedInput` 校验器本体，runner 入口仍禁用待特权 worker）。④ 双臂 genesis 封存 driver（`scripts/v3_trial_genesis.py`——既有 `TrialGenesisArchive.seal` 的 CLI 接线，dry-run 默认零写入，逐组件 lstat 拒 symlink；capital-only genesis，exit-lane/lot 继承留 Phase 5）。对抗审查修复：symlink 守卫死代码、日历畸形行静默跳过→fail-closed。全部离线 primitive：不启动 Trial、不解除 fail-closed、不构成权限。

**前向 Trial Phase 5 primitive（2026-08-20，四轮对抗审查收敛，v3 套件 2989 绿）**：① `v3/evidence/market_bars.py` — bar-set 证据（每会话一张，execution 层 `DailyBar` 的 CanonicalModel 投影，信封纪律同排程）；② `v3/orchestration/replay_assembly.py` — 纯组装器（bar 证据→bars+marks[分→micros 同源]+snapshot_evidence；`marked_securities` 持仓过滤——退出后 flat 证券的 mark 是冲突；regime/candidate session 交叉拒绝）+ `scripts/v3_seed_market_bars.py` 播种器（court raw→证据时间轴唯一入口，围栏=前收×板块幅度 **half-up 舍入**——交易所规则，非银行家）；③ `v3/orchestration/arm_lifecycle.py` — 结算驱动（构造 `NormalizedProxyOpenIntent` 确定性身份后**委托 `settle_proxy_open`**：判定+adverse 滑点+fee+reserve 一次到位；双情景常量复用引擎 `scenario_cost` 工厂单一事实源；EXIT 量须取自仓位投影）；④ `v3/evidence/offline_rig.py` — 离线 ephemeral 信任链 rig（测试/播种共用，非生产身份）。组合接缝测试钉死"证据→组装→双情景结算→守恒"全链；多 issuer 命名空间同库共存已验证（trial root 单 evidence.sqlite3 成立）。全部离线 primitive：不启动 Trial、不解除 fail-closed、不构成权限。

**前向 Trial Phase 6 + ⑦ 胶水收口（2026-08-20，终轮全局审查后落地，v3 套件 2998 绿）**：① `v3/orchestration/session_driver.py` — 顺序会话生命周期驱动器（出场先于入场；出场会话由 kernel 冻结的 `target_exit_session` 排程日期驱动，驱动器不做位次算术；出场日停牌/一字 UNKNOWN 时持仓保留、义务顺延到下一会话成交——宪法 #9 语义，`>=` 而非 `==`；逐会话持仓集演化 `held_by_session` 是 marks 过滤事实源；每会话 mark-only `close_valuation` AS_OBSERVED 估值，停牌顺延最后已知收盘；窗口末端持仓披露不强制平仓；全程守恒重验）+ `open_line_from_shadow_line` 映射（kernel 行是身份/量/限价/日期权威；无条件 T+10 开盘卖出 = 1 分下限；lot/lineage id 由 shadow line id 确定性派生保证重放资本身份一致；入场限价=买上限、出场限价=卖下限显式分字段）。② ⑦ 胶水测试 `tests/offensive/v3/orchestration/test_glue_replay_assembly_session_driver.py` — replay_assembly 与 session_driver 两条平行抽象的**显式汇合点** `evidence_backed_bar_for`（只接受已发布 bar-set 证据记录、按需组装 facts 供 bar 查询，替代隐式 lambda；终轮审查 P3-b）；`SessionLifecycleDriver` docstring 钉死 `bar_for` 源契约（官方接线必须经 `bars_from_record`/`assemble_replay_session_facts`，直喂 CSV/price_cache 绕过 5a 数据面裁决的运行不是官方重放；P3-a；签名同步收紧 `DailyBar | None`）。断言面四件：pair 幂等（恰等重放同 receipt + 冻结输入完全重建逐字节复现 + 同键背离 `arm_decision_conflict`）/ OpenLine↔kernel 行八字段逐一映射 / 驱动器全周期守恒 / NAV 序列精确计数（genesis 1 + 每驱动会话 1，成交不另增观察行，干净全周期无 restatement）；fixture 世界模块级构建一次（crib `test_shadow_kernel.py:814-839` checkpoint-v2 绿色调用法，不触标注 RETAINED-SPEC STALENESS 的 `run_official`）。全部离线 primitive：不启动 Trial、不解除 fail-closed、不构成权限；下一步治理签名 → 特权 worker + CLI。

**诚实能力边界（2026-08-12；2026-08-20 更新）**：前向 Trial 接线 Phase 1–4 primitive 已落地 （排程证据回执/producer port+候选绑定/freeze_shared_input 纯构造器/genesis 封存 driver，见上节）——但官方 Trial 仍未启动：runner/replay 入口仍 `forward_input_authority_unavailable`（待特权 worker），Phase 3 的 stage 绑定/evidence merkle 参数尚无签发机制，CLI 四命令仍 unavailable，无任何评估/晋级/授权。历史缺口记录（两臂资本快照分化、签名 Stage、日历绑定、T+1/T+10 lot lifecycle、assessment 接线）中：producer 输入与排程绑定已补 primitive，其余仍开放；两臂必须从各自已分化的 CapitalTruth/UnitNAV/现金、reserve、fill、fee 状态取得独立 PIT capital snapshot，不能继续共享一个 capital snapshot；签名 Stage、逐 session evidence cutoff 与权威交易所 calendar 尚未完整绑定；T+1/T+10 open、原始 lot 到 ExitLane、公司行动/correction 的全生命周期仍需修复并完成 current-cost 与 2×-slippage 全量重放；assessment 所需 official replay、双臂 capital report 与 consumption-ledger inputs 尚未接线。故**官方 Trial 尚未启动，不可验证、不可评估、不可形成晋级候选，更不可授权资本**。`src/cli/v3_regime_trial.py` 四命令目前全部 unavailable：它们只以逐组件 `lstat` 检查 root/layout/trial-id 的路径形状并拒绝 symlink/traversal，绝不打开 SQLite、读取 Trial 内容或绑定任何 frozen policy/regime/cap 值，随后以稳定 typed JSON 和固定非零 rc fail-closed；`validate` 使用 `validation_inputs_unavailable`，因为当前 root 尚无签名 Stage、immutable store-seal receipt 与 hash-bound complete SessionSpine，而 active WAL 不能用忽略 WAL 页的 SQLite `immutable=1` 充当 current truth。`decide-session`/`advance-session` 使用 `privileged_context_required`，`assess` 使用 `assessment_inputs_unavailable`；所有命令均不改变 Trial 文件或 SQLite sidecar，`assess` 也不写 output。root 必须使用 canonical、全路径组件均非 symlink 的路径（macOS 临时目录写 `/private/tmp/...`，不用 `/tmp/...`）。真正 validate 必须等待 Governance/Stage 与 cold immutable snapshot 设计完成。基线 `runtime_mode "off"` + 全 0 caps + `execution_authority "NONE"` 三重 fail-closed；无 broker 连接、无 authority flip、无真实资本激活。权威设计见 spec §12；运行边界见 `docs/runbooks/v3-btst-regime-forward-trial.md`。

Plan 07（Broker Gateway 与 DR）primitive 已实现（2026-08-08，broker 套件 174 绿、v3 全套 2547 绿，整体独立审阅 2 CRITICAL/4 MAJOR 已修）：broker-neutral port + authenticated raw envelope（无认证即不称 accepted）+ content-addressed durable raw inbox（redacted secret、per-source sequence fence、幂等重放）；`DeterministicFakeBroker` 驱动 ack/duplicate/reject/timeout/乱序/截断；production adapter 默认 disabled（`BROKER_ADAPTER_NOT_CERTIFIED`，缺 verified enablement 即拒）；双人一次性 `BrokerEnablementManifest` gate（全信任链 + account/env/currency/endpoint/clock/idempotency/auction TIF+cutoff/pagination+cursor+retention/execution/exit-rate/credential-fencing 逐 area hash 绑定，任一漂移命名违规区）；SEND_CLAIMED dispatcher（claim→发送精确不可变命令→durable append receipt→回报；REJECT 永不当作 ACK——reject 单保持 SUBMISSION_AMBIGUOUS 待 reconcile；resend 只复用相同 client id，前置 certified 幂等 + broker cutoff）；push/poll normalization（累计成交只按 `new-last` 入账，非显式 bust 回退锁存 halt 不 clamp，correction 省略 economics 即 fail-closed）；分页完整对账（缺页/重复页/cursor 回退/retention 过短=BLOCKING 先行阻断，qty/notional/cash BLOCKING、fee ADVISORY，material/unknown break 先持久化 external fact）；独立 entry/exit/query/reconcile 队列+限流（exit 不耗 entry 授权、进程 kill 后 exit 义务存活、unknown 可卖量零额卖出+dedup query+超界 escalate 不 livelock）；writer handoff fencing（ACTIVE→DRAINING→BROKER_RECONCILED→HANDOFF_COMPLETE，单调 fencing epoch，credential/session/network proof 缺一不可，旧 epoch 永久失效）；灾备（`DisasterRecoveryCoordinator` PRE_RESTORE→…→RECOVERY_COMPLETE，篡改 manifest/陈旧备份/账号错配/cursor 漂移/epoch race/lost credential/旧 writer 复活全 fail-closed）。**生产 broker 连接、真实资本激活、首次 BROKER_CONFIRMED 2% exploration 均未启用；生产 adapter 仍默认 disabled，全部为离线 primitive，不构成任何真实 broker 授权或资本事实。**

**目标架构仍未在生产上线，也没有资本授权（无真实资本激活路径）。** Plan 04 的 kernel/gateway/exit/proxy-manual primitive 与 Plan 07 的 broker/DR primitive 均已离线落地（见上），但真实生产路径仍未上线：仍未实现 broker connection、authority flip（INACTIVE→ACTIVE 的生产切换）、签名服务或任何真实发单/成交/资本激活路径；Plan 03 的 Authorizer/Issuer 仍只产生 INACTIVE 候选 envelope；Plan 05 的 CLI shadow 编排仅为库层观测（ephemeral 信任 + 合成 authority，非真实授权，仅解锁 admission 供观测），privileged worker 独立进程+UDS 仍未上线（留 Plan 06+）；Plan 07 的 fencing-epoch/writer fence 此前只在 WriterHandoff/DisasterRecoveryCoordinator 上以进程内不变式执行；Plan 08（2026-08-08）已落地 `BrokerRuntime` 组合层（`broker/runtime.py`）把它 wire 进 dispatcher send path——`submit_entry`/`submit_resend` 在触 dispatcher 前强制 fence（DR 存在时经 DR `fence_send`，否则经 WriterHandoff `fence_send`；epoch 从 fence 权威即时读取而非构造快照），stale epoch/非 authority writer/DR 未完成都在 broker 收到任何命令前 fail-closed（无 claim、无 receipt），fence 失败透出权威原生错误（HandoffError/DisasterRecoveryError）。现有 Revision 1 ports/`DecisionSeal` 只能留在显式 compatibility namespace，不得进入 final `CapabilityVerifier` 或继续作为最终接口扩散。

## 数据完整性（⚠ 最重要，曾因此误判）

### legacy 历史成交候选源（研究重建用，非授权证据）

**位置：`data/paper_trading_backtest/`**（不是 `data/paper_trading/`！）

- `journal.jsonl`：⚠️ **磁盘上的该文件自 2026-08-15 晚起是 2024 跨周期重放**（171 BUY，trap-15 修复验证工作用 `scripts/backtest_paper_loop.py` 重跑 2024 时覆盖了它）——**2026 原版（403 条 = 211 BUY + 192 EXIT，2026-01-15 → 2026-07-06）已从 git `0be66383` 恢复至 `outputs/journal_20260115_20260706_recovered.jsonl`**，本节全部 2026 结论以恢复副本为准。journal 自 commit `22cb6026` 起不被 git 跟踪，重放前先备份。
- `portfolio_state.json`：legacy 记录为 nav=2.10、realized_pnl=+110%；该数值受下述锚定 bug 与零成本/T0 收盘口径污染，**不得继续作为有效业绩引用**（当前磁盘版本描述的是 2024 重放，同样不引用）。
- **这是 legacy 回测的成交候选子集（研究重建用，非授权证据）**，但不是可直接引用的收益真相；验证 setup、regime 或止损前必须按本仓位锚点和目标执行合约重建。⚠️ **全候选评估用 `btst_court` 研究管道**（`data/research/btst_court/event_tables/event_table_v1.csv.gz`，2025-07→2026-08-18，全市场含退市者快照、生产 `BtstBreakoutSetup` 原样重放）——journal 成交子集与全候选月度口径可差 7.5pp（2026-06：+5.95% vs -1.60%；journal 侧可由 `outputs/journal_execution_stats_20260816.json` 重验，court 侧由 `btst_court_views` 的 `monthly_by_regime` 固化视图重验，d06c175f 起不再依赖临时聚合），**任何月度/regime/止损评估优先用 court，不用 journal 子集**（陷阱 19）。
- ⚠️ **不要和 `data/paper_trading/`（运行时实例，0 笔 EXIT）混淆**。曾因此误判系统"0 笔成交"。
- ⚠️ **journal 的 recorded P&L 存在锚定 bug（2026-07-18 对抗性审查定位，三方独立复现）**：生成它的回测以 `price_loader=None` 调用 `close_matured`（`scripts/backtest_paper_loop.py:134`），`fetch_actual_returns` 把每票收益锚到**本批次最早 buy_date** 而非本仓位 buy_date；且入场口径是 **T0 收盘**（不是文档声称的 T+1 开盘）、零成本。可复核 139 笔中 **42% 偏差 >0.5pp，最大 ±31.6pp**（300033 两笔不同仓位同记 -26.74%，精确复现锚定窗口）。**下表引述值因此系统性虚高**，修正后见"2026 实测表现"。另：**53/192 笔（28%）的 ticker 缓存文件已被删除，永久不可复核**——回测产物必须连同输入数据快照归档。
- ⚠️ **journal 的 EXIT.date 与 BUY.date 相同**（回测把开仓/平仓都记在信号日），到期日必须从交易日历机械推导，不能拿 EXIT.date 当卖出日。

### 2026 实测表现（截至 2026-07-09，源自 paper_trading_backtest；2026-07-18 全量修正 + 2026-08-16 执行口径重建）

三列口径：journal recorded 原值（锚定 bug 污染）→ **全量修正值**（192/192 可复核，own-anchor 本仓位 T0 收盘、零成本、pct_change 链除权免疫）→ **可执行合约**（T+1 开盘买、信号日+horizon 交易日开盘卖、30bps/边滑点+5bps 卖出印花税、复权帧 open-to-open、一字/停牌/缺 bar 逐项排除；`scripts/rebuild_journal_execution_returns.py`，186 filled/6 excluded/19 unpaired）：

```
BTST (n=133):  recorded +8.15%/68%  →  corrected +5.07%/60%  →  executable +3.41%/57% (n=130)
  crisis (21):   +16.93%/76%       →  +10.44%/67%          →  +8.23%/62%   (仍最强)
  risk_off (9):  +8.87%/78%        →  +1.97%/56%           →  +4.15%/67%   (n=9, 本就不可靠)
  normal (103):  +6.29%/66%        →  +4.24%/59%           →  +2.33%/55%   (n=100)
OB (n=59):     recorded +0.34%/52%  →  corrected -0.13%/44%  →  executable -2.15%/39% (n=56, 无 alpha 确认)
```

- **执行口径结论（2026-08-16 首次落地，产物 `outputs/journal_execution_stats_20260816.json`）**：BTST 扣成本与 T+1 开盘 gap 后仍为正（+3.41%，较 corrected 低 ~1.6pp = 成本 0.65pp + 开盘 gap ~1pp），crisis 仍最强（+8.23%）——"不能断言只会更低"的悬案就此关闭：**更低，但仍为正**。OB 执行口径 −2.15%/39%，**维持默认暂停**。一字排除 0 笔经独立验证为真（74 笔触发日涨停样本中次日开盘最大 +6.8%，无一续一字）；6 笔停牌/缺 bar 排除（BTST 3、OB 3），19 笔回测结束时未平仓（unpaired）。corrected-T0 对照列与 2026-07-18 产物交叉验证：**8 组逐分复现（delta=0.00，PASS）**。
- **双锚口径与防御（2026-08-16 对抗审查 F1/F2 修复）**：executable 用**日历锚**（T+N 个交易日，停牌排除——合约语义）；corrected/recorded 对照列用**个股锚 frame+N**（停牌顺延——0718 修正的实际口径，变体对撞逐分确认后跟随）+ 全配对分母（含被排除仓位，n=133/59），两列分母刻意不同。曾误把 risk_off 1.57pp 差异归因"排除项"（该组排除数为 0）——已更正：差异全部来自停牌仓位的锚点分歧。复权回落（pct 缺失/非有限，`_back_adjust_ohlcv` 静默返回原始价的 fail-open 路径）现以 `adjusted_fallback_raw` 显式排除并计数（本样本 0 触发）；涨停阈值不含 ST 5% 板（journal 无名称字段，样本是否含 ST 未核验；候选池按设计排除 ST）。
- **方向结论不变**（BTST 三 regime 都为正、crisis 最强；OB 统计不显著），但 **E[r] 系统性高估 3.1pp、胜率高估 8pp**。修正产物：`outputs/journal_corrected_stats_20260718.json`；journal 原文件未改动（锚定 bug 机制见上条警示）。
- **BTST 执行匹配证据已重建，但仍不构成 regime 加仓授权**：样本期仅 6 个月（顺行情）、每 regime 样本小、且这是 RESEARCH_RECONSTRUCTION 研究重建——v2 ledger 的 regime 加仓需要的是可由 repository 重验的 canonical regime 授权证据，不是研究脚本产物。risk_off 的 1.1× 依据已基本消失。
- **OversoldBounce 默认暂停（2026-08-19 证据升级为 court 全候选口径）**：`scripts/ob_court_build.py` 重放生产 `OversoldBounceSetup`（预筛 84,229 → hits 2,313 → fillable 2,281），T+5 净 E=-0.40%/win=46.4%（n=2,205，聚类 CI90 下界 -1.21% ≤ 0）——没有可授权的正 alpha，暂停从 journal 偏差子集（-2.15%/39%，n=56）升级为与候选宇宙一致的全候选证据；先验常量已同源重校准（见陷阱 4）。journal 三列数字仅作历史审计线索。
- ⚠️ 样本期仅 6 个月，可能有样本期偏差；补全历史数据重跑前，这些结论是"当前最佳依据"而非定论。
- ✅ **已验证**：59 笔回测用的是完整版 setup（volume 列存在、量比条件3 生效），不是残缺版。git 证据：volume 列在 commit `7c51cef8`(07-07) 加入，回测在 07-08 跑，setup 代码当时已有完整过滤逻辑。

### price_cache（个股价格，回测/扫描数据源）

**位置：`data/price_cache/*.csv`**（每股一个文件，6 位代码命名）

- **深度已补齐且持续增长**（票数随涨停注入每日增加——2026-08-17 约 1600；2026-07-17 曾为 823 票/中位 1579 行，2020-01-02 起；07-08 时曾只有 6 个月 ~117 行/股）。⚠️ 文档不要写死当前票数——任何快照次日即过期，引用时用 `ls data/price_cache/*.csv | wc -l` 实测。
- ⚠️ 把资金流深度当作历史回放瓶颈的旧叙述**已过期**——fund_flow 已补齐（见下表），历史评估的现行资产是 court 管道（见陷阱 9），旧 Phase 0 框架及其瓶颈叙述不再指导任何工作。
- `data/reports/setup_research/phase0_report_20260708.md` 声称的 n=1762 **无法从本地数据复现**——它在别处（更深资金流历史）生成。
- ⚠️ **引用 Phase 0 报告的结论前，先与修正后的 paper_trading_backtest 重建结果交叉验证。** 曾因盲信 Phase 0（声称 OB E=+3.42%/n=1113）对 OversoldBounce 统一加仓；全量修正后 OB 为 n=59/E=-0.13%/winrate=44%，没有可授权 alpha。

### 其它历史数据（深度较全）

| 数据源 | 位置 | 深度 |
|---|---|---|
| regime_history | `data/reports/regime_history.json` | 2020-2026，`--auto` 每日追加当日 regime（2026-07-18 起有生产写入者）；此前停在 20260707，legacy 路径静默退化 normal |
| industry_index_cache | `data/industry_index_cache/*.csv` | 2020-2026，31 个行业，1577 行 ✅ 完整 |
| fund_flow_cache | `data/fund_flow_cache/*.csv` | 5244 文件（2026-08-16 实测）：99% 最早数据 ≤2025-07、28% ≤2022；2026-04/05/06 每月 ~5200 票有数据、~5185 票 ≥15 天 ✅ 已补齐（旧"深度不一、部分仅 1 行"快照为 2026-07-17 实测，已过期） |
| btst_court 事件表 | `data/research/btst_court/event_tables/event_table_v1.csv.gz` | 全候选（含退市者）执行口径事件表，2025-07-02→2026-08-18（270 会话；2026-08-19 同行为重建：formula 6cb38b0c 对齐、rebuild_count=1、formula_change_forced=true+prior 披露）；manifest 含 git_sha/formula_fingerprint/universe_audit；管道 `scripts/btst_court_*`（build 直接 import 生产 `BtstBreakoutSetup`） |
| tracking_history | `data/reports/tracking_history.json` | `--auto` 推荐追踪，跨日 T+1/T+3/T+5 收益 |
| ob_court 事件表 | `data/research/ob_court/event_tables/`（本地资产，不入 git） | OB 全候选执行口径重放，2025-07-02→2026-08-18（270 会话；预筛 84,229 → hits 2,313 → fillable 2,281）；重建 `uv run python scripts/ob_court_build.py --end YYYYMMDD`；manifest 含公式指纹/漏斗/抽查一致性 |


## 当前选股系统状态（截至 2026-08-16）

### 凸性 setup（`--daily-action`）

- **BTST 涨停突破（T+10）**：✅ 启用（normal regime）。**regime gate（2026-08-14 接线，R-5.F 收口）：信号日 regime ∈ {crisis, risk_off} 不开新仓**（`_REGIME_GATE_BLOCK_REGIMES`；detect 照跑、blocked 以 `regime_gate_halt` 带完整 trigger_strength 诊断——面板继续积累危机日对照组，仅仓位/计划层阻断）。证据链：① 诚实 court（T+1 开盘+滑点、**全触发候选**、2026H1）：crisis 9%/−8.98% (n=11)、risk_off 8%/−16.12% (n=13)——**灾难 regime 该阻断而非加仓**；gated BTST-only NAV 1.430 vs ungated 1.133。② 跨期复现（2025H2）方向一致。③ 止损×gate 联合网格：gate 优于止损。见 `data/reports/regime_gate_decision_pack_2026-08-09.md`、`data/reports/stop_loss_x_regime_gate_court_20260814.json`。⚠️ 旧 1.2×/1.1× regime 加仓表已于 2026-08-14 删除（对抗性审查 P1a：依据是受污染 recorded P&L + 成交宇宙选择偏差，且从未生效——"挂着引信的错误开关"）；服务层 `regime_authorization_evidence_unavailable` 披露保留为纵深防御。**任何未来 regime 仓位差异化必须用全候选 court 重放证据，不得用 journal 成交子集**（见陷阱 19）。
- **OversoldBounce 超跌反弹（T+5）**：⏸️ **默认暂停**（2026-08-19 court 全候选复核：净 E[r]=-0.40%、winrate=46.4%、n=2,205、CI90 下界 ≤0，无正 alpha；证据宇宙与候选宇宙一致，见"2026 实测表现"与 `data/reports/ob_pause_court_recheck_20260819.md`）。
  - 控制：`DAILY_ACTION_DISABLED_SETUPS` env（默认含 `oversold_bounce`）。
  - 恢复：`DAILY_ACTION_DISABLED_SETUPS=none`（补全历史数据重跑后再决定去留）。
  - ⚠️ 旧 `+0.34%`、CI、crisis 和尾部数字来自受污染 recorded P&L，不再作为恢复或分层依据。详见上文“2026 实测表现”。
- Kelly 仓位：half-Kelly，当前 v2 ledger 单票硬上限 10%，组合上限 60%；regime 加仓例外已随 2026-08-14 gate 决定**移除**（crisis/risk_off 直接阻断新仓而非加仓）。
- **Drawdown 熔断 + 行业集中度（2026-07-18 恢复，v2 迁移时曾丢失）**：组合回撤 ≤-20% 停止一切新仓、≤-15% 新仓权重减半（与 legacy `drawdown_action` 对齐）；同一入场日同行业新仓 ≤2（含当日已预留，依据：集中日 E[r] +6.3% vs 分散日 +9.7%）。
- **计划层容量拦截披露（2026-08-18 审查修复）**：service 路径 `_create_capacity_safe_plans` 的行业集中/组合敞口/单票上限拦截此前是裸 `continue`——强度达标的候选从漏斗凭空消失（8-17 实况：命中 13 只只交代 7 只，603110 型候选无解释）。现记录为 `CapacitySkip` 并渲染「容量拦截（N 只）」区 + 漏斗第三项（命中 = 可计划 + 不可计划 + 容量拦截）；幂等重跑不把已持久化计划误报为被拦。同批修复：v2 渲染恢复敞口行（持仓+待成交/60% 上限）与 Regime 行；强度分量「板块」改名「上市板」（board_score 是 002/300/301/688/60x=0.95 的上市板质量分，非行业动量——与「行业当日 +X%」并排会被误读）。
- **执行成本口径 v2.1**（2026-07-18）：v2 ledger 执行成本从零成本改为 30bps/边滑点 + 5bps 卖出印花税，与 Kelly 先验（`adjust_returns` 30bps/边）对齐；此前零成本使实盘 P&L 系统性优于证据 ~0.6pp/笔，污染 edge 衰减监测。成本版本不匹配的计划按 `cost_version_mismatch` skip（不再 raise 崩溃死锁）。
- **运行护栏**（2026-07-18）：`--end-date` 不得晚于 17:00 规则的自然信号日（未来日会永久杀掉排队计划并写入未来估值）；入场日 09:30 后不再创建当日入场计划（`entry_window_missed`，防止按不可执行的开盘价记账）；交易日历前向覆盖 <30 天时保留旧文件（防止年末日历截断静默失效）；drawdown 熔断/日历不可用/窗口阻断在默认渲染可见（不再伪装成"今日无信号"），并输出台账净值/回撤行。
- **panel 样本外闭环**（2026-07-18）：v2 scan 对象已补齐 logger 字段（trigger_strength/entry_price/metadata/kelly_pct 别名），`candidate_not_plan_eligible`（未触发的契约拒票）不再写入 panel 对照组（防止对照总体被宇宙噪声稀释成假 ✅）；`_forward_return` 已除权免疫（T+1 日内腿同日价 + 后续 pct_change 链）。
- 止损：⚠️ **当前是披露用的，不执行**——`stop_would_have_triggered` 只进 reasoning 字符串，**不影响 realized P&L**（账面按 T+N close）。⚠️ 旧述"192 笔回测 0 笔触发（2026 行情好）"**因果错误**（2026-07-18 审查定位）：生成该 journal 的回测传了 `price_loader=None`，止损检测根本没运行（0 触发是默认值不是检测结果）；独立重算持有期 raw low ≤ -8% 硬止损 **43% 会触发**。"止损不执行不伤 P&L"的有效证据是 `scripts/backtest_exit_strategies.py` 的独立止损回测（2026-07-10，81 笔 BTST：所有止损策略在当前牛市样本都降低 E[r] 和 Sharpe），不是 journal 的 0 触发。可用 `DAILY_ACTION_EXECUTION_STOP=atr_k2|atr_k3|fixed8` 在熊市/高波动期手动启用真实止损执行（改变 P&L 口径，启用前应跑 `scripts/backtest_exit_strategies.py` 确认当前行情有利）。

### 因子评分（`--auto`）

- 四策略 → score_b → composite_score → investability 排序（`profit_aware` 默认开启，`INVESTABILITY_PROFIT_AWARE=false` 回退；主键 empirical bucket 胜率，composite 末位 tie-break；bucket 证据缺失的票按 0.5 胜率/0.0 期望中性处理，不再 -inf 垫底）。
- ⚠️ **profit_aware 校准池曾 89/89 天为空**（2026-07-18 定位修复）：严格模式的 git-sha 等值过滤（历史中 27 个版本，上一 commit 的证据次日即失效）+ 98.3% 记录缺 `return_tN_date` 被 pop，导致排序实际从未脱离 composite。修复：model_version 仅作 provenance 不过滤；未标注日期的成熟 label 用交易日历推断 `realized_on`（recommended+N 个交易日）。**切换前的"profit_aware 已开启"结论需重验**——它自开启起一天都没真正生效过。
- **评分链已回溯复权**（2026-07-18）：`load_price_frame` 用 pct_change 链把 OHLC 复权到最新行口径（末行=原始价），此前 EMA/RSI/动量/布林带/ATR 从 raw close 重算，除权缺口被读成崩盘幻影（001388 型 raw -26.8% 实际 +10%；~19% 的票近 126 行内有缺口）。**修复前生成的 composite/score_b 与全部因子 IC/校准证据是在幻影污染的信号上量的，重跑前不可直接对比。**
- **因子数学修正**（2026-07-18）：① growth 趋势符号反转修复（newest-first 序列倒序回归，此前 50.8% 的票加速/减速判反）；② ADX 改 Wilder RMA（与 RSI 同平滑，此前 ewm(span) 系统性偏高、31.5% 趋势门翻转）；③ growth 钳位 score=0 区分负增长/零增长（raw_score 保留原值，此前 27.4% 零增长票被满置信看空）；④ 动量三窗改对数收益求和（消除高波动票动量高估的横截面偏差）。
- 排序证据（双确认）：composite/score_b 主键在真实 Top10 切片显著反向 — c272（47% vs 60%）+ 2026-07-18 独立复核（T+5 IC=-0.112 t=-2.49，top-3 45% vs 反选 58%）。全池 300 票日 IC 为正——顶部非单调反转。tracking 回填改用 price_cache pct_change 链（43 条幻影记录已迁移重算）。
- **展示层 v3（2026-08-16 重构，冻结规格；同日冷读收口）**：`--auto` 候选表按 SCORE_BUCKETS 桶分组，桶级钱数（近 60 推荐日 T+5 胜率/均值/盈亏笔均/赔率，`scorecard.py::compute_bucket_stats`）只在桶头渲染一次（此前逐行重复"48%·428" 7 次）；header 记分牌行常驻（briefing 卡「排序」段 / legacy 回退时表格上方）：Top10 切片胜率·均值·日内 Spearman IC·前3vs后7 + 三态 verdict（positive 需 IC t≥2 且切片均值>0；t≤−2 判反向；**IC 日数 <2 时 t=None「样本不足」、单日 IC 不宣称显著**——2026-08-16 收口 commit `25fcabe2`；**tracking 只记录每日 Top10，无池级基准，不编造**）；桶成熟样本 <5 不给点估计、5–19 带 ⚠少样本（对齐 BUY-gate backing_sample≥20 纪律）。**冷读验收（2026-08-16）通过**：三问（信几成/为什么/做什么）可全部从表内推导；补齐三个口径标注——档头与记分牌均值标 **（未扣费）**（往返 ~0.65%，均值扣费即净先验）、完整图例声明 **T+5 是诊断口径、与 --daily-action T+1/T+10 合约不同窗口**、图例固化 **verdict=信任档（无正向证据→只读不跟）**。**冷读反馈迭代（同日）**：内部标签「桶 较低 (0.3-0.4)」对读者是黑话+悖论（"较低"会被读成"这票差"，实际只描述信号分绝对区间——全池普遍 <0.5，0.3-0.4 即常见高位；且表内已无信号分列，区间指代悬空）——档头改为 **「信号分档 0.3-0.4（本表第 1-7 名）」**：只报区间+名次归属，定性标签（较低/低）留在数据层不进显示；展示术语统一「桶头→档头」。
- **第二轮同类问题清扫（2026-08-16，用户冷读反馈驱动）**：① P9-1 预期收益块中文化+区间化——"长期 invalidation horizon T+20/T+30 edge"→"长期失效视野 T+20/T+30（毛收益，未扣费…）"、`bucket=较低 (0.3-0.4)`→`信号分档 0.3-0.4`（与档头同款 `bucket_band_text` 提取）、`尾=`→`最差5%=`、`T30熟=`→`满30天=`；② `--top` 迁 v3 同款桶分组纪律（删 4 位小数信号分/逐行池胜率/决策列与过期图例句「其余列含义同 --auto」；保留 --top 独有「前门」列插在综合分后；`score_b=None` 行为从渲染 0.0 改为跳行+警告——FusedScore 校验失败不静默补零）；③ 术语定义入册：全量图例新增 IC（秩相关，|t|≥2 显著且重叠样本偏乐观）/信号分 vs 综合分区别/仓位系数三条定义，记分牌行内 IC 附「(秩相关)」gloss（None 安全分支保留，a275d261 B1 契约）。
- **第三轮清扫（2026-08-16，次要展示面收尾）**：英文枚举/黑话在剩余 surface 清零——PDF 推荐表（score_b 表头→信号分、+0.7200→+0.72、决策列原始英文枚举→中文）、push 推送（buy/AVOID→买入/回避、4dp→2dp）、`--daily-brief`（bullish/bearish 裸枚举+前门英文→中文，矛盾标记 ⚠ 契约不变）、`--explain`/`--why-not`（Score B→信号分）、`--custom-weights` 差异视图（score_b 标签）、`--top-picks`（`bucket=低(<0.5)`→`信号分档 <0.5`，与档头同款提取）。共享映射 `DECISION_LABELS_ZH` 入 `src/screening/models.py`（覆盖 FusedScore 域 strong_buy/watch/… 与旧报告域 buy/hold/bullish/bearish 两套枚举，未知值原样回退）。评分构成块已删（与因子瀑布同数据两遍），因子瀑布需 `AUTO_TABLE_VERBOSE=1`；图例两行 + `--top --legend` 全量；`gap_to_limit≤0.01` → 行内 ⚠距涨停<1%（T+1 买不进风险）；行业集中警示改 count≥3（旧 ratio>0.4 在 sector cap=3 下永不触发，是死代码）；行业轮动行加 ⚠背离（价格动量与 avg score_b 反向）；P9-1 预期收益块样本不足时显式披露行（不再静默消失）。测试：`tests/test_scorecard.py`、`test_auto_briefing.py`、`test_auto_screening_display.py`、`test_score_decomposition.py::TestAutoScreeningTableRowV3`、`test_sector_concentration.py`。

### 样本外验证闭环（logger → backfill → panel）

**为什么存在**：**2025-07 以前**没有全市场覆盖的完整重放（2025-07 是 fund_flow 的全市场覆盖下界——99% 文件自此起；2022–2024 仅约 28% 文件有数据，court `WINDOW_A_START` 按全保真口径取 2025-07 未前推，需要更早窗口须另行构建部分宇宙）；**2025-07 起** `btst_court` 研究管道已能全保真重放生产 BTST（全候选、T+1 开盘+滑点、含退市者，见"研究重放资产"节）。跨周期 court 证据显示月度差异主要是 regime 差异（gate ON 口径 2026-04 显著为正、2026-03 为负；`monthly_by_regime` 固化视图，`btst_court_views` 重跑即复算）。⚠️ 旧文本把回放失败归因于 --auto composite 特征依赖、称"回放不出真实候选"，**已过期**：生产 BTST setup 不消费 composite（`btst_breakout.py` 无 scoring import），court 直接重放检测器。panel 前向累积仍是**样本外**（与 court 回放互补，不互相替代）。

**数据流**（两条命令天然衔接，无需人工干预）：

```
--daily-action  →  log_setup_outputs()   →  data/reports/setup_output_log/YYYYMMDD.jsonl   （当日每票信号快照, 幂等覆盖）
--auto          →  backfill_panel()       →  data/reports/setup_output_panel.jsonl          （新 bar 到位即回填 T+1..T+10）
```

- **logger**（`setup_output_log.py`）：`--daily-action` 每跑一次，把当日所有候选（含被过滤的）连同 `plan_eligible`/`degraded`/`trigger_strength`/`entry_price`/`kelly_pct`/`regime`/`block_reason` + 扁平化 metadata（pct_change / main_net_inflow / industry_pct / pre_5d_runup_pct / limit_up_pct_threshold）写成当日 JSONL。原子覆盖 = 幂等。
- **backfill**（`join_setup_outputs_with_returns.py` 的 `backfill_panel()`）：`--auto` 末尾 best-effort 调用（`try/except`，永不拖垮 `--auto`）。只加载**已记录票**的价格序列（不是全 700+ 只），join 出 T+1/T+3/T+5/T+10 前向收益，写 panel。到期才标 `realized=True`。
- **面板按 `plan_eligible`(过全过滤) vs 策略过滤组（检测器正常但被策略判断拒绝）分层**：这是判断「全过滤是否真的挑出 alpha」的样本外依据。`degraded=True` / `readiness degraded:` 数据护栏降级票**不入对照、单独披露**（commit 362a2789 分层修复）——2026-07-08/07-15 两天各 263 张涨停注入候选因旧行业映射路径（候选池快照仅覆盖 ~4%）被降级，07-17 readiness v2 强制 SW 精确覆盖宇宙后 0 复发；混入对照曾产出 p<0.001「全过滤挑 alpha」假阳性。首个诚实结论（2026-08-16, 326 realized）：T+1 反向显著（策略过滤 +1.30% vs eligible −1.37%, p=0.040）、T+3/T+5/T+10 不显著——**尚无证据全过滤挑 alpha**。样本够大前不要据此改策略参数。**2026-08-19 反向信号分解**（`scripts/panel_signal_decomposition.py` + `data/reports/panel_decomposition_20260819.md`）：方向复现（eligible -0.89% vs 拒票 +1.45%，p=0.046，d=-0.53），反向**集中于 0.50-0.60 边缘强度桶**（T+1 -2.79%/胜率 7%，n=14）而非拒票组普涨；≥0.70 桶 T+5/T+10 呈强（+5.8%/+5.9%，胜率 70%，n=10）——全部格子 n<30 不足判定，工具可随 panel 增长复跑；若边缘桶深负持续，强度阈值 0.50 重校准是候选 owner 决策（新证据世代）。**边缘对照成熟门控（2026-08-19）**：「面板体检」行末追加 `边缘对照 a|b/30` 计数段（预注册对比两侧的 T+1 已实现数，min(a,b)≥MIN_CELL_N 时标「⚠可初判」）——count-only 反偷看（不报均值/p，推断留给分解报告），计数与 `decompose()` 桶表同源（`contrast_t1_counts` 单一实现，奇偶测试钉死），段自身异常隔离为 `(桶计数不可用)` 不拖垮体检行。分解报告同步携带**等待投影**（`contrast_wait_projection`：聚类 bootstrap 对比差 CI90；跨 0 且半宽>2pp 时按 SE∝1/√n 外推所需每侧样本，半宽已≤2pp 仍跨 0 时如实报告"精确测到差≈0、继续收集无益"——区分『样本不足』与『无差异』两种不可判）。
- ⚠️ **panel 是样本外累积，不是回测**：`data/paper_trading_backtest/` 才是历史回测（192 EXIT）。两者别混。刚上线时 panel 里多数 `realized=False`（前向窗口未到期）属正常。

### --auto 缓存刷新性能（2026-07-17 优化，~408s → ~21s）

`refresh_daily_action_caches` 的耗时曾是 --auto 大头（本地 O(全历史) 重处理，不是网络）。优化点：

- **价格幂等跳写**：当日行已存在且值未变 → 跳过全量校验 + 原子重写（证据照采，指纹不变），计数 `price_skipped_current`；原每轮 ~90s 空转写盘消除。
- **日期处理向量化**：`_fund_flow_dates`/`_price_dates` 纯字符串整列操作，替代逐值 `pd.to_datetime`（800 票 × 中位 1579 行 × 多趟）。
- **PIT 指纹快路**（`pit_evidence.py`）：`to_dict(records)` → `itertuples` 行迭代 + 零填充 ISO 日期快速路径；`_normalize_daily_batch` 与 `_daily_batch_evidence_fingerprint` 改用 `canonical_price_row_fingerprint`（免每行 DataFrame 构造）。**逐位等价已验证**：优化前后对全部真实缓存（6042 个指纹，含 daily_batch manifest 指纹）逐位一致。
- **资金流批量预取**（`DAILY_ACTION_FUND_FLOW_BATCH`，默认开）：stale 票用 `fetch_batch_fund_flow_tushare(trade_date)` 单次 API 全市场拉取替代逐票串行（~1.3s/票），命中票免网络与 rate-limit；close/pct_change 从当日 daily batch 填，main_net_pct 留 NaN（见陷阱 11）。冷缓存实测 68 票 30.6s → 6.4s；首日 ~500 票场景从 >10min 量级降到秒级。批量失败/未覆盖自动回落逐票路径。

### Daily Action readiness v2 legacy 数据完整性链

- **legacy v2 数据完整性/来源路径**：`--auto` 刷新 Daily Action 缓存 → `DailyActionRefreshResult` 冻结结果 → readiness schema v2 manifest → `load_verified_daily_action_snapshot()` 重算 PIT 指纹 → `scan_from_verified_snapshot()` → `DailyActionService.complete_run()` → ledger 写入 `verification_status="verified"`、`snapshot_id`、`setup_consumed_fingerprint`。`verified` **只表示数据合格，不构成 edge authorization**，不得把这条 legacy 路径原样迁移成 v3 新仓授权。
- **schema v1 只读迁移行为**：旧 `schema_version=1` readiness 文件没有新仓授权；loader 必须返回 `readiness_schema_unsupported`，生命周期仍可先结算到期退出，但不得创建新计划。
- **fail closed**：空/未知策略版本、伪造或空 fingerprint、字符串布尔值、manifest / candidate / ledger provenance 不匹配，都没有新仓权限。
- **部署后必须重跑 `uv run python src/main.py --auto`**，让 schema v2 manifest 与最新缓存证据重新发布；不要用旧 v1 readiness 文件授权 `--daily-action` 新仓。
- **证据捕获自愈**（2026-07-17 修复）：`end_daily_readiness_reference_capture` 在捕获窗内自行补齐缺失的 stock_basic/SW 观测，不再依赖候选池构建的副作用——此前候选池当日缓存命中时两个 fetcher 不会被调用，同日重复跑 `--auto` 必然发布失败（`typed dated reference snapshot is required`）。数据源失败仍按原样 fail closed。
- **宇宙退市过滤**（2026-07-17 修复）：`resolve_daily_action_refresh_tickers` 用 stock_basic(L) 自动剔除退市/非上市标的（数据源不可用或宇宙 <3000 只时 fail-open 不过滤，由 readiness 严格校验兜底）。此前一只退市票（002808）就会让 security/SW 精确覆盖校验把全宇宙清单整体阻断。
- **停牌证据宇宙投影**（2026-07-17 修复）：tushare 停牌列表是全市场的，而 v2 清单要求停牌证据 ⊆ 宇宙；`refresh_daily_action_caches` 在冻结结果前把停牌证据投影到宇宙内（source_fingerprint 按投影后行重导，保持自校验）。不投影时清单一律 fail-closed（`suspension evidence contains ticker outside universe`）。
- **测试隔离规则**：readiness v2 / ledger 集成测试必须把 `data/`、`data/reports/`、ledger sqlite 都建在 `tmp_path`（或测试专用生成目录）下，禁止写工作区运行时 `data/reports`、生产 ledger、`data/paper_trading_backtest/`、历史报告或 legacy ledgers。`tests/offensive/conftest.py` 的 autouse fixture 会把退市过滤的默认 loader 置为 fail-open，测试过滤器时显式传 `listed_universe_loader=`。

## 已知数据/逻辑陷阱（避坑）

1. **`data/paper_trading/` vs `data/paper_trading_backtest/`**：前者是运行时（0 EXIT），后者是回测（192 EXIT）。查成交数据用后者。
2. **price_cache 深度已补齐（2026-07-17 实测：823 票中位 1579 行，2020→2026）**；fund_flow 也已补齐（2026-08-16 实测 5244 文件，99% ≥2025-07，见数据表）——旧"`setup_research.py` 仍 n≈0、瓶颈是资金流浅"**已过期**（n≈0 是否仍成立未在当前 session 重验，但该框架已被 court 研究管道取代，跨周期评估一律用 court）。`phase0_report` 的数字仍不可复现。
3. **止损默认是披露用的，不执行**：`stop_would_have_triggered` 不进 P&L。回测验证（2026-07-10，81 笔 BTST）显示**所有止损策略在当前牛市样本都会降低 E[r] 和 Sharpe**（均值回归 setup 的波动反而赚钱），故默认不执行。可用 `DAILY_ACTION_EXECUTION_STOP=atr_k2|atr_k3|fixed8` 在熊市/高波动期手动启用真实止损执行（改变 P&L 口径，启用前应跑 `scripts/backtest_exit_strategies.py` 确认当前行情有利）。
4. **`known_distributions.py` 是硬编码常量，2026-08-19 owner 批准重校准（新证据世代）**：现行生效 BTST T+10 与 OversoldBounce T+5 先验已从 **court 全候选重放**重校准（owner 2026-08-19 决策）——BTST T+10：court 生产对齐宇宙 n=1464、净 E=+0.56%、win=46.45%、CI90 [-1.30%,+2.39%]（跨 0，单期不显著如实披露）、IC 0.096（87 日日内 Spearman）；OB T+5：court 全候选 n=2,205、净 E=-0.40%、win=46.4%、CI90 下界 -1.21% ≤ 0（维持暂停）。**旧值（2026-07-12 的 626 票连续涨停样本、未扣费）虚高 E ~6pp/胜率 ~12pp，仅保留为历史审计线索；BTST T+8 未重校准（court 重验只有 T+10 视图），provenance 已显式标注"仅回测兼容"**。`--check` 断言（daemon 哨点恒跑）已从「先验虚高方向断言」改为「对齐断言」：先验期望与 court 生产对齐宇宙偏离 >1pp 或胜率回到虚高 ≥10pp 即当天暴露。先验不进仓位链（仓位 = setup_max_pct×drawdown×strength），重校准影响面是披露层（先验行/脚注/期望）；先验行标签口径中性（「历史回放 n=…」），扣费与否由 `Distribution.provenance` 表达。重验工具 `scripts/review_btst_prior_court.py`（三视图 + 对齐断言），产物 `data/reports/btst_prior_court_recheck_YYYYMMDD.{md,json}`；OB 侧重放管道 `scripts/ob_court_{build,report}.py`（本地资产 `data/research/ob_court/`，同 btst_court 约定不入 git）
5. **`--daily-action` 扫描空间 = price_cache 文件名集合**：曾因只含候选池"好股票"而漏掉涨停小盘股（已用涨停注入修复，见 `cache_refresh.py`）。
6. **BTST 涨停判定是板块自适应的**（2026-07-10 修复）：`limit_up_pct_for_ticker` 按前缀取阈值——主板 9.5%，科创/创业 19.5%，北交所 29.0%。旧固定 9.5% 会把 20% 板的非涨停大涨日误判为涨停。`execution_adjuster.is_limit_up_unbuyable_next_day` 也同步修复。
7. **BTST 资金流条件在浅数据下降级**（2026-07-10 修复；2026-08-17 前提更新）：单票 `fund_flow` 历史 <5 天时「资金流 >20d 均值」无法判定 → `degraded=True`，渲染标 `⚠残缺`。fund_flow 已回填后全市场性浅数据的状况不再成立，触发面收窄为新上市/新注入票；降级机制与 operator 披露语义不变（`_MAIN_FLOW_MIN_HISTORY_DAYS=5`）。
8. **setup-output panel 是样本外累积、不是回测**（2026-07-15 新增）：`data/reports/setup_output_panel.jsonl` 由 `--daily-action` 逐日记录 + `--auto` 回填前向收益生成，用于验证「全过滤挑 alpha」是否成立。别和 `data/paper_trading_backtest/` 的历史回测混淆。样本够大前**不要据此改策略参数**；刚上线多数 `realized=False` 属正常。跨周期裸信号已证明 2026 胜率是顺行情、非周期稳健。
9. **完整 setup 2025-07 起可全保真重放（court），2020–2024 仍不可**（2026-08-16 更新）：旧"历史 fund_flow/industry 数据太浅 + 强度排序不可回放"（2026-07-15 记录）**已过期**——fund_flow 已补齐（99% ≥2025-07），生产 BTST 不依赖 composite（`btst_breakout.py` import 链无 scoring）。`data/research/btst_court/event_tables/event_table_v1.csv.gz`（2025-07→2026-08-18）即全候选跨周期重放产物。引用「跨周期回测」结论前仍先确认口径（裸信号 / court 全候选 / journal 成交子集）；2025-07 以前的全市场全保真仍拿不到（部分票 2022 起有数据但非全宇宙），跨周期结论以 2025-07 起 court 为准。
10. **东财 push2his 会按源 IP 行为封禁，ProxyError 有误导性**（2026-07-17 定位）：`--auto` 每日对 `push2his.eastmoney.com` 逐票数百次 fflow 请求（含 enrich 补全），东财 WAF 对本机 IP 的 `/api/qt/*` 100% 断连（TLS 正常、请求发出后 empty reply；根路径 404、push2 实时 API 200 → 定点封 API 路径，非网络故障）。报错显示 ProxyError 是因为 requests 走系统代理（Clash），**根因不在代理**。已加熔断器（`src/tools/akshare_fund_flow.py`：连续 5 次网络错误熔断 15 分钟、半开自动复位；enrich 路径同步跳过），熔断期 akshare 源由 tushare/ftshare 兜底。注意：`push2` 的 `fflow/kline/get` 只有当日实时数据，**不能**替代历史接口；分片主机 `N.push2his.*` 同被封。封禁期 ftshare 缺的日子 `close`/`main_net_pct` 补不上属预期代价，解封后（通常数小时~几天）自动恢复。
11. **东财 `main_net_pct` 口径 ≠ 主力净流入/成交额**（2026-07-17 实测）：000504 2026-07-16 tushare 推导 -13.76%（net_mf/成交额，成交额与 daily amount 吻合）vs 东财缓存 -2.83%（分母疑为流通市值）。且 2026-07-16 批次东财行 pct 与 main_net_inflow **符号大量不一致**（如 000014 inflow=-2164万 却 pct=+26.45），该列数据质量存疑。**下游 setup（BTST/OB）只消费 `main_net_inflow` 金额，不消费 pct**，影响为零；但任何新逻辑引用 pct 前必须重新核对口径。资金流批量预取路径因此 pct 留 NaN（落盘补 0.0，同逐票 tushare 惯例）。
12. **缓存目录不能放在 symlink 路径下**（2026-07-17 实测）：`atomic_write_csv` 的 `_open_parent` 用 `O_NOFOLLOW` 逐层打开目录组件，macOS 的 `/var`、`/tmp`（→ `/private/*`）会报 `[Errno 20] Not a directory: 'var'`。`tempfile.TemporaryDirectory()` 创建的目录就在其下——测试/bench 里构造缓存目录要用项目内路径或 pytest `tmp_path`（本仓库 basetemp 在工作区内）。生产 `data/` 用相对路径不受影响。
13. **readiness v2 精确覆盖 vs 现实数据滞后**（2026-07-17 记录）：v2 要求宇宙内每票都有 stock_basic(L) + 申万行业成员证据，缺一票全局 fail-closed。退市票由宇宙构建时的 stock_basic(L) 过滤解决（见"宇宙退市过滤"）；残留风险是**新上市/次新股尚未纳入申万行业指数**（stock_basic 有、SW 成员没有）——若此类票经涨停注入进入宇宙，SW 覆盖校验仍会阻断当日清单。出现时把该票加入 `EXTRA_EXCLUDED_TICKERS` 临时屏蔽，或等申万收录后自愈。
14. **质量门常量必须与管线设计对齐**（2026-07-18 定位）：`quality_decision` 曾长期 degraded，三根同类的"门与设计矛盾"：① `price_history` 的 eligible 误用全池 300，而技术阶段按设计只消费流动性前 75%（225）→ 现由 scorer 用 `note_eligible_tickers` 显式声明设计消费集；② 生产端"成功观测 0 行"（合法空）不落盘空快照，消费端误报 UNAVAILABLE → `load_event_inputs` 现依据生产端逐源证据把合法空提升回 SUCCESS（且**合法空压过 stale 回退**：今日权威空 + 昨日非空快照时以今日空为准，不再触发 required_stale_fallback）；③ `min_usable_rows=200` 与候选池 `MIN_LISTING_DAYS=60` 矛盾（次新票按设计只有 ~60 根 bar）→ 硬门槛改为 60，200 保留为 informational 的 full-factor 目标。**改质量门常量前，先确认它约束的是"异常"还是"设计状态"。**
15. **price_cache 是不复权价，跨日窗口收益必须用 pct_change 链**（2026-07-18 对抗性审查；2026-08-16 autodev 两轮收口）：825 票中 173 票近 200 行内有除权缺口（close 链收益与 pct_change 偏差 >1pp）。原始价比值跨缺口产生幻影（2026H1 全市场 817 个幻影超跌票日，OB 回测成交 31% 是幻影）。**已修：setup 检测窗、panel `_forward_return`、tracking 回填、--auto 评分链（`load_price_frame` 回溯复权）、realized P&L 三处成交收益链（`paper_tracker._execution_adjusted_return`/`_close_to_close_return` + `execution_adjuster.adjust_returns`，统一复用 `chained_return_pct`；commit `39849222`）、以及第三轮 shadow/未实现路径（commit `2f46b56d`：`daily_action_service._evaluate_shadow_path` 复权到 entry 日口径重放——激活阈值/移动止盈线/ATR 缺口 spike 三重失真一并免疫；`paper_tracker.open_positions_detail` 的 `unrealized_pct` 检出缺口时改链式口径）全部除权免疫**；pct_change 不可用时诚实回退原始比值（逐位同旧口径），shadow 复权用 ±0.5% 缺口检测门（无缺口窗口输出与旧口径逐位一致，tushare pct 两位小数舍入不触发）。修复前实测影响：2024 journal 171 BUY 中仅 1 笔偏差 >0.5pp（全部低估方向），修复性质是正确性而非当前量级，分红季频率更高；shadow 侧探针复现：armed 后 10送10 除权日触发虚假 `close_below_trailing_line`（真实涨幅 +2%）、unrealized 显示 -67% vs 真实 +36.7%。回归：`tests/offensive/test_paper_tracker_corp_action_returns.py` + `tests/offensive/test_shadow_exit_corp_action.py`（RED→GREEN + 恒等/回退逐位一致）。另外 v2 ledger 的 MarketBar limit_up/limit_down 现由前收 × 板块幅度按交易所规则推导（除权日锚点偏宽，每年 ~1 天/票）。
16. **profit_aware 校准池饥饿与 None 语义**（2026-07-18 定位）：严格模式 git-sha 等值过滤（27 版本漂移）+ 98% 记录无 `return_tN_date`，校准池 89/89 天为空 → profit_aware 实际从未生效（排序静默退回 composite）。已修：sha 仅 provenance 不过滤、未标注日期用交易日历推断 realized_on。另：profit_aware 主键 None 从 -inf 改中性（0.5 胜率/0.0 期望）——旧语义让"已知 30% 胜率"排在"未知"前（方向错误）。
17. **台账初始资金的整手截断**（2026-07-18 定位并修复）：10% 单票上限 × 10 万 = 1 万，股价 >100 元即买不起一手（journal 样本 28%~46% 的价格带，含 688 高价龙头）。**已解决**：initial_cash 默认提至 100 万（`DAILY_ACTION_LEDGER_INITIAL_CASH` 可覆盖），旧 10 万台账归档于 `data/paper_trading_v2/archive/`（0 成交，无损失）；skip 原因区分 `lot_floor_zero_shares` vs `cash_capacity`。
18. **低桶细分与盈利阈值校准**（2026-07-18）：① `SCORE_BUCKETS` 的 <0.5 单桶细分为 5 桶（tracking n=8168 实证内部单调梯度：0.1-0.2 峰 62.0% → 0.4-0.5 44.7%，高桶边界不变），profit_aware 主键在 Top10 内恢复区分度（此前 ~56% 的天全落同桶）；② profitability 阈值从美股口径（ROE≥0.15/NM≥0.20/OM≥0.15，A 股 75% 满置信看空）改为 A 股全市场 ~p65-70（0.08/0.09/0.11，n≈4800 快照），0 通过率 75%→~30%，quality-first 红旗恢复选择性。
19. **journal 成交子集做 regime 证据 = 选择偏差；文档滞后曾误导一次加仓特性开发**（2026-08-16 定位并当场回退）：journal 的 192 笔 EXIT 是 legacy 回测**实际买入**的仓位子集（P1a 审查点名的"成交宇宙选择偏差"），在其上重建的执行口径 regime 统计（如 crisis +8.23%/n=21）**不能**作为 regime 仓位差异化证据——正确宇宙是全触发候选 court 重放（同策略全候选 T+1 开盘+滑点：crisis 9%/−8.98%，结论相反）。2026-08-16 曾据本文件过期的"待 canonical regime evidence 恢复 12%"句（描述 2026-07-18 状态，未反映 2026-08-14 的 gate 决定）开发了 crisis 12% 授权 manifest 并生成，核对 `daily_action.py:85-106` 注释后**整体回退**。教训：① 引用"当前状态"段落前先 grep 代码内的决策包引用与日期更新的注释；② 加仓/授权类特性的证据宇宙必须与被授权策略的候选宇宙一致。
20. **信号覆盖断层无检测 + 注入票行业映射缺失**（2026-08-17 对抗性审查，华正新材 603186 案例驱动，两项均已修复）：① `--daily-action` 长期大面积断跑且系统零检测——哨点上线实测（2026-08-17 视角）：最近 30 个交易日中 **19 天**无 setup_output_log（不止 8-05~8-11，7-23/24/27/30、8-04 同缺）；8-05 华正新材四条件全 PASS、生产 detect 重放 strength=0.79（8-04 超跌反包首板当日电子 +5.73%、前 5 日 −18.97%，被条件 2 挡；8-05 才勉强放行），信号就此漏掉。修复：`setup_output_log.audit_signal_log_coverage`/`warn_missing_signal_log_sessions` 双哨点（`--auto` cache_refresh 收尾 + `--daily-action` 信号解析后，30 交易日有界窗口，0 字节文件=已覆盖，advisory 不阻断）。⚠️ 2026-08-18 审查发现 daily-action 侧哨点初版只挂在 legacy `generate_daily_action`，生产 v2 路径（dispatcher → `scan_from_verified_snapshot` + `DailyActionService`）从不执行它——已接入 dispatcher v2 路径（就绪阻断时也跑，测试 `tests/test_cli_dispatcher.py::test_daily_action_v2_path_runs_signal_coverage_sentinel`）；告警走 `logger.warning`（stderr），不在渲染正文里。**策略能力问题与运营覆盖问题是两层：先查日志文件是否存在再谈选股因子。** ② BTST 条件 3 的票→行业映射此前只来自候选池快照并集，涨停注入票（从未进池）拿不到行业 → 被「行业缺失=miss」静默砍掉（8-14 涨停 62 只中 38 只无映射、15 只死在该缺口——数据管道缺口伪装成策略过滤）。修复：`--auto` 每晚落盘全市场 SW L1 映射至 `data/snapshots/sw_industry_latest.json`（`cache_refresh._persist_sw_industry_snapshot`，跟随 refresh 的 snapshot_dir 保测试隔离），`daily_action._load_ticker_to_industry_from_snapshots` 两层加载（SW 文件优先、快照兜底），修复后 8-14 映射覆盖 62/62、hit 2→3（301419 阿莱德修复前死于缺口）。测试：`tests/offensive/test_setup_output_log.py` + `tests/offensive/test_sw_industry_mapping.py`。
21. **条件 2（主力净流入>20日均值）在全候选 court 口径下无可检出区分度**（2026-08-17 复核，`scripts/review_cond2_fund_flow_gate.py` + `data/reports/cond2_gate_court_review_20260817.{json,md}`）：cond1+3+4 宇宙 3314 例按条件 2 分流，pass vs fail 的 T+5/T+8/T+10 Welch t 全部 |t|<1.2（T+5 方向反向），margin 八分位无单调性，normal regime +0.66% vs +0.44% 不显著；crisis/risk_off 两组深度为负（条件 2 无保护作用）。华正新材 8-14 被条件 2 挡掉**不是错误拒绝的系统性证据**。复刻忠实性经生产 detect 逐行仲裁（9/9 一致，差异全为 court 构建日 08-15 与 fund_flow 08-16 补齐的数据代际差）。**维持现状不改**；未来动它 = 策略行为变化走新证据世代。新 setup 设计不得预置资金流条件。


22. **court 公式指纹漂移的两种处置（2026-08-19 定型，`--rebuild-force` 逃生门落地 43a53dd1）**：build 的防覆盖护栏用**文件级 sha256** 做公式指纹——纯注释/非公式行变更也会触发"指纹不一致"假阳性（实测：93b904b5..43a53dd1 对 `btst_breakout.py` 仅一行注释，court 全部消费侧守卫即判定"不代表当前生产口径"）。处置分两支：① **detect 公式行为真实变化** → 不覆盖 v1，开新版本文件（护栏缺省 fail-closed 即为此设计）；② **同行为假阳性**（diff 证明仅注释/非公式变更）→ `btst_court_build.py --rebuild-force` 同行为重建，manifest 如实记录 `formula_change_forced=true` + `prior_formula_fingerprint` + `rebuild_count` 递增，消费侧守卫（views/recheck 的 formula_match）随即恢复绿。判断分支的前置动作永远是 `git diff <manifest.git_sha>..HEAD -- src/screening/offensive/setups/btst_breakout.py` 逐行确认变更性质，不许跳过 diff 直接 force。另：逃生门 flag 曾在护栏提示中存在但 argparse 未注册（提示指向不存在的门），已修复并有 8 测回归网（`tests/test_btst_court_build_rebuild_flag.py`）。

## 关键文件速查

| 模块 | 文件 |
|---|---|
| 命令分发 | `src/cli/dispatcher.py`（`--daily-action` 在 `_resolve_daily_action`） |
| 凸性 setup 主逻辑 | `src/screening/offensive/daily_action.py`（`generate_daily_action`） |
| Setup 定义 | `src/screening/offensive/setups/btst_breakout.py`、`oversold_bounce.py` |
| Kelly 仓位 | `src/screening/offensive/kelly.py` |
| Paper tracker | `src/screening/offensive/paper_tracker.py`（成交记录、止损、drawdown） |
| 缓存刷新 | `src/screening/offensive/cache_refresh.py`（`--auto` → `--daily-action` 桥梁；已排除北交所；幂等跳写 + 资金流批量预取，见性能小节） |
| PIT 证据指纹 | `src/screening/offensive/pit_evidence.py`（canonical 指纹/校验；输出是 ledger 契约，改实现必须做逐位等价验证） |
| 样本外 logger | `src/screening/offensive/setup_output_log.py`（`--daily-action` 逐日写信号快照） |
| 样本外 backfill | `scripts/join_setup_outputs_with_returns.py`（`backfill_panel()`；`--auto` 末尾回填前向收益 → panel） |
| 面板体检（只读） | `scripts/panel_health_check.py`（plan_eligible vs 策略过滤组 Welch t 检验，数据护栏降级票不入对照只披露；`--auto` 末尾打印一行摘要，realized≥30/组≥5 时出结论） |
| 排序记分牌/桶头统计 | `src/screening/scorecard.py`（Top10 切片胜率/均值/日内 IC 三态 verdict + SCORE_BUCKETS 桶头 T+5 实证；briefing 卡「排序」行与 `--auto` 桶分组表的单一事实源，只读 tracking_history） |
| 跨周期裸信号验证 | `scripts/validate_btst_setup_cross_cycle.py`、`scripts/validate_auto300_gate_removal.py` |
| ATR 止损工具 | `src/screening/offensive/atr_utils.py`（Wilder ATR + 止损价计算） |
| 涨停板块判定 | `src/tools/ashare_board_utils.py`（`limit_up_pct_for_ticker`：主板9.5%/科创创业19.5%/北交所29%） |
| 止损策略回测 | `scripts/backtest_exit_strategies.py`（对比 no_stop/固定/ATR 止损的 E[r]/Sharpe） |
| 执行口径重放 | `scripts/rebuild_journal_execution_returns.py`（2026 journal 第三列：T+1 开盘买/T+N 开盘卖+真实成本+除权免疫；测试 `tests/test_execution_replay_core.py`；输入用 `outputs/journal_20260115_20260706_recovered.jsonl`，勿指向被 2024 重放覆盖的运行时 journal） |
| 全候选 court 管道 | `scripts/btst_court_fetch.py` / `btst_court_build.py` / `btst_court_views.py` + `scripts/_btst_court_common.py`（全市场含退市者快照 → 生产 `BtstBreakoutSetup` 原样重放 → 执行口径事件表 `data/research/btst_court/event_tables/event_table_v1.csv.gz`，2025-07→2026-08-18（2026-08-19 重建）构建产物（不自动更新，跨期评估前先重建；公式漂移处置见陷阱 22）；**全候选月度/regime/止损评估一律用 court，不用 journal 成交子集**） |
| BTST 先验重验三视图 | `scripts/review_btst_prior_court.py`（court 事件表上重验 `known_distributions` 先验：生产对齐宇宙/排除行披露/预注册半年度时间切片三个纯函数视图 + `--check` 方向断言恒跑；产物 `data/reports/btst_prior_court_recheck_YYYYMMDD.{md,json}`，2026-08-19 起 owner 重校准决策材料） |
| OB court 复核管道 | `scripts/ob_court_build.py` / `ob_court_report.py`（生产 `OversoldBounceSetup` 原样重放：30 日链式跌幅向量化预筛 → 全候选事件表 → 预注册暂停复核谓词；本地资产 `data/research/ob_court/` 不入 git；2026-08-19 结论：维持暂停） |
| panel T+1 反向分解 | `scripts/panel_signal_decomposition.py`（只读诊断：强度桶×regime×horizon，n<30 只披露；产物 `data/reports/panel_decomposition_YYYYMMDD.{md,json}`） |
| 回测框架 | `scripts/setup_research.py`（Phase 0，旧框架，已被 court 取代） |
| 条件2 资金流 gate 复核 | `scripts/review_cond2_fund_flow_gate.py`（court 管道 cond1+3+4 宇宙重建 + cond2 分流 A/B + 生产 detect 仲裁自检；产物 `data/reports/cond2_gate_court_review_20260817.{json,md}`） |
| 题材动量 setup 设计 | `docs/superpowers/specs/2026-08-17-theme-momentum-setup-design.md`（设计稿，Phase 0 未开始，不构成授权；**§9 = 实现后的使用形态备忘**——三种结局各自用法/"做"则成为与 BTST 并存的第三 setup 共享风控独立证据/时间线/无论结局事件表都可反哺 BTST 条件3 与 event_sentiment） |
| 题材动量 Tier A 决策包 | `data/reports/theme_momentum_tier_a_decision_pack_20260818.md`（**已跑两级**：Tier A 申万一级 −0.26pp CI(−1.77,+1.25)；**Tier B1 东财细行业 +0.33pp CI(−0.81,+1.47)**——粒度忠实度改善 +0.59pp 被证实但 exec 净值 −0.32pp，均 near_zero → B2 概念成分是阶梯最后一步，仍不成立则关闭方向；结构信号跨粒度一致：**dist1-2 唯一正值区、3 天后深负 −2.6~−3.2pp**；华正案例 B1 完整复原；决策包 `data/reports/theme_momentum_tier_decision_pack_20260818*.md`） |
| 题材动量研究计划 | `docs/superpowers/plans/2026-08-17-theme-momentum-research.md`（**已执行完毕并关闭（2026-08-18）**——v3.4 粒度阶梯；原文：v3.3 两级火箭：Tier A 确认 = **双条件分离**（家数跳变 ≥3∧20 日中位≤1 + 占比≥5% 防普涨；v3 的 max(2×baseline) 在零基线恒真退化已修）·零新数据源先出方向性决策包（基线锚定确认日、双粒度预注册、matured 截尾、第四态、每月 2-15 确认日 sanity 锚）；Tier B 唯一新增数据 = 月度 as-of 成分，概念涨停家数由 lu 快照∩成分**自算**；主假设预注册唯一且为 **¬BTST-eligible 增量子集 + 按确认日聚类 CI**；先验披露 20-35%——Phase 2 shadow 是阳性后强制步骤；court raw 静态快照前置依赖显式化，研究窗口截至快照构建日） |
| 因子评分 | `src/screening/`（candidate_pool / strategy_scorer / signal_fusion / investability） |

## 每日自动调度（2026-08-18 起）

常驻守护 `scripts/daily_daemon.sh`（用户终端手动启动、每天 18:01 自动跑 `--auto → --daily-action` 串行链）：

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork
nohup bash scripts/daily_daemon.sh >> logs/cron/daemon.log 2>&1 &   # 启动（--now 可先立即跑一轮）
kill $(cat logs/.daily_daemon.pid)                                   # 停止
```

- 单实例 mkdir 原子锁（macOS 无 flock）+ PID 活性检查/陈旧锁自愈；管道锁冲突（rc=75，如手动 --auto 在跑）自动等待重试 3 次；`--daily-action` rc=14（POLICY_HALT：regime 全闸/熔断/窗口）归一为成功。
- 状态 `logs/.daily_run_status.json`；日志 `logs/cron/pipeline_YYYYMMDD.log`；覆盖哨点在链内自动运行。
- **为什么不用 launchd/cron**：外置卷受 macOS TCC 保护，launchd/cron 启动的进程读卷上文件被拒（2026-08-18 探针实测 rc=126/78）；终端启动的守护继承授权。机器重启后需手动重启守护。
- 检查是否在跑：`ps -p $(cat logs/.daily_daemon.pid)`。

## 测试

```bash
uv run pytest tests/offensive/ -v          # 凸性 setup + paper tracker 全套
uv run pytest tests/test_main_auto_cache_refresh.py -v  # auto 缓存刷新回归
uv run pytest tests/offensive/test_daily_action_cache_refresh.py -v  # 涨停注入
```
；信封 `behavior_fingerprint` = 推导规则常数 domain_hash（消费方可复算）、`strategy_semver="1.0.0"`（2026-08-20 对抗审查语义修正——字段不再过载 artifact hash/权威身份））。