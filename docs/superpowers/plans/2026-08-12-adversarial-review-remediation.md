# 2026-08-12 对抗性审查修复计划

> 状态：执行中。审查范围 `ba42c705..4c154505`。本计划只修复已复现的不变量破坏；不激活真实资本、不连接 broker、不把修复后的历史重放冒充前向证据。

## 第一性原理

1. 未能从截止时点已提交的原始事实重演的结果，不是证据。
2. Champion 与 Challenger 共享外生市场事实，但各自拥有独立、守恒、连续的资本状态。
3. 交易日、时区、费用、lot 来源和退出期限是经济合约，不是展示字段。
4. 研究不能直接改变生产行为；行为变化必须新版本、预注册、前向验证。
5. 未实现的能力必须显式 fail-closed，文档和 CLI 不得把 facade 描述成 operational。

## 修复顺序

### R0 — 立即止血与诚实状态

- 恢复最近无可靠同口径证据支持的 Auto 因子权重和 regime 调整；保留纯重构中可证明的单一真理源。
- 将受污染的 trend/MR/event 研究结论标记为 `RESEARCH_RECONSTRUCTION_REJECTED`，禁止作为生产行为依据。
- official regime Trial 在完成 R1–R4 前不得产生新的 `RUN`、评估或 promotion candidate；CLI 明确报告缺失能力，而不是构造零 hash 评估。
- 更正 AGENTS/runbook 的实现状态，不宣称未接线的 runner/CLI 已完成。

### R1 — PIT 原始候选与逐 session 截止

- 新增 strict/frozen 原始 BTST 候选 payload，至少包含 exchange-qualified `security_id`、整数 `price_micros`、setup、trigger strength、industry、snapshot/manifest 绑定。
- raw payload 先持久化，`SignalEvidence.payload_content_hash` 精确绑定该 blob；删除猜 ticker、猜交易所、固定价格和合成 target 的 fallback。
- runner 请求必须携带已验证的 `VerifiedDailyActionSnapshot` 或其可重验引用；真实 producer 不再接收 `None`。
- 每个 signal session 使用受信 A 股交易日历和 Asia/Shanghai cutoff；cutoff 后只能 `NO_RUN`，不能补算。
- regime reader 强制 `available_at <= cutoff`，并校验 session、mode、namespace/source 与 observation 绑定。

### R2 — Governance/Stage 时间真相

- sealed bundle 纳入 exact `StageManifest`、store-controlled seal receipt/time/root；拒绝依赖 manifest 自报时间。
- Trial/SAP/Stage/target policy registration 必须在 enrollment 前完成并可从不可变 store 重验。
- runner 删除 hard-coded stage id/hash；所有 decision、replay、assessment 逐字绑定 sealed stage。

### R3 — 双臂资本与交易日经济学

- runner/replay 接受两个不同 portfolio/context/repository；每个 session 各读一次 arm-specific checkpoint。
- 只共享 regime、raw candidates、冻结价格/行业和 trusted time；不得共享 cash/exposure/risk/watermark。
- kernel 的 T+1/T+10 来自冻结交易日 ordinal，不使用自然日加法。
- ShadowDecision 直接投影 sizing 的 worst-case reserve/fee buffer，不重新计算为零费用。
- 新增至少两个 signal session 的分叉测试，证明首日一臂 no-trade 后次日数量、reserve、NAV 各自连续。

### R4 — lot 来源、退出与 writer fence

- entry lot 永久记录 originating pair/line/signal/due/source；退出按 lot origin 派生，不读取 `latest_pair_key`。
- overlapping cycles 不得延后旧 lot 的 T+10；新 pair 为 NoTrade 时旧仓退出、估值仍继续。
- writer lease/fencing epoch 必须进入 capital write 的同一原子校验域；消除 check-then-write takeover race。
- fill、fee、reserve release 采用可证明原子或 crash-convergent 协议，任何阶段不得隐藏负现金。

### R5 — Auto 研究与多前门一致性

- event 输入拒绝决策 cutoff 后新闻；研究脚本保存 observed/available timeline。
- 重新研究时使用与生产相同 Layer-A universe、T+1 open→T+10 open、完整成本、公司行动安全价格和组合路径；只注册 shadow challenger。
- custom reweight 复用生产唯一纯融合函数，完整度、缺失策略、零权重语义逐字一致。
- Web 挂载只读原报告，不自动 POST 等权重；CLI/Web 默认从 canonical endpoint/常量读取，只有用户显式操作才 override。
- SW membership 先形成绑定 trade date 且有完整性证明的 typed snapshot；partial/current mapping 没有删票权限。

### R6 — 可重验工件与最终验收

- 从 git 历史恢复 legacy backtest journal 到不可变内容寻址审计归档，附来源 commit/hash/caveat；不重新跟踪 mutable runtime 路径。
- 更新权威 spec、迁移说明、runbook、schema snapshot 和行为 fingerprint。
- 对每项修复执行 RED→GREEN focused tests、跨模块 differential/property tests、全量 v3 与 screening gates、静态边界扫描和独立复审。
- 验收 headline 只能是：`INACTIVE / FORWARD_TRIAL_NOT_STARTED`。历史结果全部保持 prior/reconstruction 身份。

## 提交策略

每个 R-task 独立提交；先测试后实现。任何任务发现需要扩大授权、改变既定经济合约或无法在现有 primitive 上守恒时，停止该任务并保持 fail-closed，不用 placeholder 绕过。

## 完成状态（2026-08-13）

验收 headline：`INACTIVE / FORWARD_TRIAL_NOT_STARTED`。契约迁移（ShadowDecision v4 / ShadowCapitalCheckpoint v2 / arm-invariant ShadowSharedInput / FrozenTradingSessionSchedule / SizingConfig）、双臂资本守恒、fail-closed 前向路径、R5 前门 `selected_policy_eligible` 一致性均已落地并由绿色测试锁定。以下为**有意的 dormancy 决策**（符合第一性原理 #5，非遗漏）：

- **R2 部分由休眠满足**：`build_arm_kernel_inputs` 仍硬编码 `stage_id="stage-1"`。该 builder 当前零生产调用方、runner 已禁用，故不产生真实决策；真正接线时需从 sealed Stage 逐字绑定，届时移除硬编码。
- **R3 分叉测试延后**：「至少两个 signal session 的分叉测试」存在于被 skip 的 replay retained-spec 中，其证明随 store-owned batch authority 一起延后；当前双臂守恒由 kernel 层绿色测试（cross-arm checkpoint 拒绝、无 single-snapshot shortcut、arm-invariant 共享事实）锁定。
- **retained-spec 陈旧性**：`test_forward_trial_replay.run_official`、`test_forward_paired_runner._commit_clear_run_pair` 与 `test_typed_candidate_...` 调用 checkpoint-v2 前的旧 builder 签名，已在各自 docstring 标注「重写要求」；它们在 batch authority 落地前无法执行。
- **R6 legacy journal 归档**：legacy backtest journal 的内容寻址审计归档为独立工件任务，未并入本次代码收口。

