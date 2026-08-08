# Plan 08 设计：生产组合层与 fence send-path 接线（M1 闭环）

**日期**: 2026-08-08
**状态**: 待用户审阅
**前置**: Plan 01–07 已合并 main（broker gateway `35a78fa8`，review 尾巴 `82acf99c`），全部为离线 primitive。
**关联**: `2026-07-19-growth-kernel-07-broker-gateway.md`（Task 7 fence 不变式、Task 8 Step 5 编排）、`2026-07-19-growth-kernel-roadmap.md`（总体验收门）。

## 1. 背景与问题陈述

Plan 07 交付了 broker/DR 的全部离线 primitive，其中 fencing-epoch/writer fence 由 `WriterHandoff.fence_send` 与 `DisasterRecoveryCoordinator.fence_send` 实现。但整体独立审阅留下唯一一个被 defer 的 **MAJOR（M1）**：

> fence 只在 `WriterHandoff`/`DisasterRecoveryCoordinator` 上以**进程内不变式**执行，**未 wire 进 dispatcher 的 send path**。当前 `BrokerDispatcher.run_once` / `resend` 可被直接调用，跳过 fence 判定——绕过了 writer/epoch 权限检查。

之所以 defer，是因为当时没有 send path 的组合层可挂测试锚点。AGENTS.md（当前 v3 已实现范围段）明确记录："fencing-epoch/writer fence 目前只在 WriterHandoff/DisasterRecoveryCoordinator 上以进程内不变式执行，尚未 wire 进 dispatcher send path（留生产组合层）"。

**Plan 08 的目标**：落地这个生产组合层（`BrokerRuntime`），把 fence 强制接进 send path，并用 `DeterministicFakeBroker` 提供真实测试锚点，闭环 M1。

## 2. 范围（YAGNI 收边）

**做**：
- `BrokerRuntime` 组合层（新文件 `src/screening/offensive/v3/broker/runtime.py`），包裹 `BrokerDispatcher` + `WriterHandoff`（可选 `DisasterRecoveryCoordinator`）。
- 强制 send-path fence：所有 entry/resend 必须先过 `fence_send`。
- 离线测试锚点（`DeterministicFakeBroker` 驱动）。

**不做（显式排除，各留后续 plan / 运营门）**：
- ❌ 真实 broker adapter 接入、authority flip（INACTIVE→ACTIVE 生产切换）、签名服务——需真实凭证/环境/独立审批，本 plan 不触。
- ❌ privileged worker 独立进程 + UDS 部署形态变更——AGENTS.md 注"留 Plan 06+"，值得独立 plan。
- ❌ 首次 2% EXPLORATION envelope 的构造/守卫代码——Plan 03 Authorizer（EXPLORATION 仅 BROKER_CONFIRMED 且 ≤2%、恒 INACTIVE）+ Plan 07 Task 8 Step 5 编排已覆盖，不重复实现。本 spec 仅以审批清单形式引用（§7）。
- ❌ 生产资本激活。组合层 adapter 恒 disabled、in-process、tmp 存储、不读真实凭证/DSN。

## 3. 架构与组件

### 3.1 `BrokerRuntime`（组合层薄壳）

```python
@dataclass
class BrokerRuntime:
    dispatcher: BrokerDispatcher        # 已含 gateway/broker/inbox/account
    handoff: WriterHandoff              # writer/epoch fence 权威
    writer_id: str                      # 本 runtime 的 writer 身份
    recovery: DisasterRecoveryCoordinator | None = None  # 可选 DR 门
```

**职责**：对外暴露**唯一**的发单入口；在调用 dispatcher 前强制 fence 判定。它**不复制** dispatcher 的 claim/send/receipt/report 逻辑，只加 send-path fence 这一层横切约束。

**关键设计决策（已定案）**：采用"组合层包裹 dispatcher + handoff"，而非把 fence 回调注入 dispatcher。理由：
- `BrokerDispatcher` 已承担 claim→send→receipt→report 的重职责；再注入 fence 会让它背上组合职责，违背 v3 的分层（contracts/trust/governance/gateway/broker 各单一职责）。
- 独立组合层可独立单测、可独立替换，且 send-path fence 成为**强制代码路径**而非文档约定——这正是 M1 从"纸面不变式"变"已闭环"的区别。

### 3.2 fencing_epoch 来源

`fencing_epoch` **不作为构造字段快照**（会随 handoff/DR 完成而过期），而是在每次发送时**从 fence 权威即时读取**：
- 无 DR（`recovery is None`）→ `handoff.fencing_epoch`
- 有 DR → `recovery.fencing_epoch`（DR 完成会 raise epoch；DR 的 epoch 权威优先，因为 DR 是更强的外部性恢复）

runtime 提供只读 property `current_fencing_epoch()` 封装上述选取规则，保证 send path 永远用 live epoch 判定。

## 4. 数据流 / 发送序列

### 4.1 `submit_entry(permit, expected_versions, *, context) -> DispatchOutcome`

```
1. recovery is not None and not recovery.entry_permitted
       → raise BrokerRuntimeError("ENTRY_FENCED_DURING_RECOVERY")   # fail-closed, 不触 dispatcher
2. epoch = current_fencing_epoch()
3. handoff.fence_send(writer_id=self.writer_id, epoch=epoch)
       # HandoffError(ENTRY_FENCED / WRITER_NOT_AUTHORITY / EPOCH_SUPERSEDED) 任一 → 向上抛, 不触 dispatcher
4. return dispatcher.run_once(permit, expected_versions, context=context)
```

### 4.2 `submit_resend(permit, *, context, broker_cutoff=None, certified_idempotent=None, now=None) -> DispatchOutcome`

与 4.1 相同的 fence 前置（步骤 1–3），然后：
```
4. return dispatcher.resend(permit, context=context,
                            broker_cutoff=broker_cutoff,
                            certified_idempotent=certified_idempotent, now=now)
```
resend 的 cutoff/幂等前置守卫（`BROKER_CUTOFF_PASSED`/`IDEMPOTENCY_UNPROVEN`）由 dispatcher 保留，runtime 不重复；runtime 只补 fence 这一层。

**不变式**：任何一条到达 broker 的命令，其 writer_id 必须是 live authority、epoch 必须是 live fencing epoch，且（若有 DR）recovery 必须已完成。fence 失败时 dispatcher **完全不被触碰**（无 claim、无发送、无 receipt）。

## 5. 错误处理

- **新异常** `BrokerRuntimeError(RuntimeError)`，带稳定 `code`，与 `HandoffError`/`DispatcherError` 同族。本 plan 只引入一个 code：
  - `ENTRY_FENCED_DURING_RECOVERY`：DR 存在但未完成时尝试 entry/resend。
- **fence 失败**：`handoff.fence_send` 抛出的 `HandoffError`（`ENTRY_FENCED`/`WRITER_NOT_AUTHORITY`/`EPOCH_SUPERSEDED`）**原样向上传播**，不包装——保持既有错误码语义，调用方按既有契约处理。
- **dispatcher 错误**：`run_once`/`resend` 的 `DispatcherError` 原样传播。
- 全部失败路径 **fail-closed**：fence 不过 ⇒ 无 broker 动作；不产生任何 capital/seal/permit 副作用（dispatcher 未被调用）。

## 6. 测试策略（离线锚点，`DeterministicFakeBroker` 驱动）

新文件 `tests/offensive/v3/broker/test_runtime.py`（basename 在 v3 树内唯一）。构造真实 `CapitalGateway` + `DeterministicFakeBroker` + `BrokerRawInbox`(tmp_path) + `WriterHandoff`，包进 `BrokerRuntime`。

对抗用例（每条约 fence 优先性）：
1. **live writer + live epoch + ACTIVE** → submit_entry 成功触达 fake broker，返回 DispatchOutcome（正路径，证明不破坏正常流）。
2. **非 ACTIVE 状态（begin_drain 后）** → `ENTRY_FENCED`，fake broker 未收到任何命令。
3. **错误 writer_id**（非 authority）→ `WRITER_NOT_AUTHORITY`，fake broker 未收到命令。
4. **stale epoch**：完成一次 handoff（epoch 1→2）后，用旧 writer/旧 epoch 构造的 runtime → `EPOCH_SUPERSEDED`/`WRITER_NOT_AUTHORITY`，fake broker 未收到命令。**这是 M1 的核心回归**：证明旧 epoch 在 send path 被实际拦下，而非仅靠不变式。
5. **DR 未完成**（recovery 存在且 entry_permitted=False）→ `ENTRY_FENCED_DURING_RECOVERY`，fake broker 未收到命令。
6. **DR 完成后** epoch 已 raise，runtime 用新 epoch → 正常发送。
7. **submit_resend 同样被 fence**：非 authority writer 调 submit_resend → fence 拦截，不触 dispatcher.resend。
8. **fence 失败零副作用**：fence 拦截后 gateway 无新 claim、inbox 无新 receipt（断言 dispatcher 未被触碰）。

每个用例都断言"fake broker 未收到命令"以证明 fail-closed（命令根本没出门），而非仅断言异常类型。

## 7. 首次 BROKER_CONFIRMED 2% exploration 审批清单（仅引用，不实现）

本 plan **不实现** exploration 代码。真实激活时沿用 Plan 07 Task 8 Step 5 的编排，须逐项满足后方可执行（全部为运营/审批门，非本 plan 代码）：

- [ ] 独立 security/compliance/reconciliation/DR 四方审批。
- [ ] 新开 `BROKER_CONFIRMED` Trial/Stage + 治理签发的一次性 `EXPLORATION` envelope（exploration 合计 ≤2%；无既有 broker EDGE 时整 portfolio gross ≤2%）。
- [ ] expiry/assessment 后只 drain；未决 exploration 风险或法律 finality 缺口阻断重发；后续尝试重新消耗 Attempt/multiplicity/exploration budget，不续期、不改写为 edge。
- [ ] proxy/manual evidence 仅作 prior，不得冒充 broker 证据。
- [ ] **仅在真实 broker-confirmed round trip + reconciliation 证明该模式后**，才可更新 AGENTS.md 的 broker-mode 声明。

## 8. 验收门（Completion Gate）

- [ ] `uv run pytest tests/offensive/v3/broker/test_runtime.py -v` 全绿（8 用例）。
- [ ] `uv run pytest tests/offensive/v3/ -q` 全绿（在 2551 基础上 +8）。
- [ ] `git diff --check` 无输出。
- [ ] send path 的**生产组合 wiring** 只经 `BrokerRuntime`——本 plan 引入的 runtime 是唯一把 dispatcher 接入发送路径的组合单元。注：语言层面不强制私有化 `BrokerDispatcher.run_once/resend`（测试与既有模块仍可直接构造 dispatcher 测其自身逻辑）；本门约束的是"runtime 之外的 send-path wiring 不得新增"，而非禁止 dispatcher 被实例化。
- [ ] 生产 adapter 仍默认 disabled；本 plan 不构成任何真实 broker 授权/资本激活。

## 9. 安全边界声明

本 plan 落地的是**离线组合层 primitive**：adapter 恒 disabled（`BROKER_ADAPTER_NOT_CERTIFIED`）、in-process、测试存储一律 `tmp_path`、不读真实凭证/DSN/endpoint。它证明的是"fence 在 send path 真的拦"这一**代码不变式**，不是"能发单"。`BrokerRuntime` 的存在不构成权限、不激活资本、不连真实 broker。真实 `BROKER_CONFIRMED` 激活仍 gate 在 §7 的运营审批。
