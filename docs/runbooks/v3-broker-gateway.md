# v3 Broker Gateway 运行手册 (Plan 07)

## 范围

本文档覆盖可选 broker gateway 的**操作程序**: 能力认证、enablement、
dispatcher、normalization、对账、生命周期调度、writer handoff 与灾备。
所有真实 broker 动作都是一次性、短时、签名批准的; 本文档不授予任何自动
执行权。**默认生产 adapter 为 disabled** — 在选定券商、账户环境、API
版本、合规与 sandbox/小额实测完成前, `BROKER_CONFIRMED` startup 必须失败。

## 角色与身份

| 主体 | 职责 | 永不持有 |
|---|---|---|
| Capital Gateway | entry/capital 唯一权威; `SEND_CLAIMED` 线性化 | broker credential、adapter key |
| Broker Dispatcher | 取已 claimed 命令发送、写 durable inbox、回报状态 | 修改授权/seal/reserve/资本 |
| Execution Normalizer | 把累计 broker 观察映射为 execution revisions | 直接入账资本 (Plan 02 幂等入账) |
| Reconciler | 分页完整对账 orders/fills/cash/positions/fees | 放弃任何 external fact |
| Lifecycle Scheduler | 独立 entry/exit/query/reconcile 队列 + 限流预算 | 跨 kind 借用预算 |
| Writer Handoff / DR | 单一 egress authority 的唯一迁移路径 | 复用旧凭证/旧 epoch |

CLI/Agent/producer/Governance/Authorizer **永不** 持有 broker credential、
adapter key、network egress 或 Capital Gateway writable DSN。

## 锁定不变量

1. 没有 authenticated broker receipt/ACK 不能称 broker accepted/fill;
   本地 outbox/send time 不是 broker time。
2. 只有经能力测试证明账户/交易日作用域内 client ID 幂等, 才允许截止前同
   `client_order_id` 重试; 绝不生成新 ID 猜测重发。
3. 查询必须证明分页完整、cursor 连续、历史 retention 覆盖; 截断/回退/最近
   N 条响应都是 unknown (BLOCKING break, 非 clamp)。
4. 累计成交只按 `new_cumulative - last_cumulative` 入账; 非显式 bust 的回退
   锁存 reconciliation halt。
5. broker-live 不复用 proxy/manual fill 或晋级样本; 真实但未关联事实先入
   AccountCapitalTruth 并 halt, 不得丢弃。
6. broker account ID、环境、币种、endpoint/certificate fingerprint 必须与
   portfolio binding 精确相等。

## 1. 能力认证 (只读探针默认)

```bash
# 只读探针模板 (默认, 无 mutation)
uv run python scripts/v3_broker_certify.py probes --account <acct> \
    --environment sandbox > findings.json

# 冻结一个 BrokerCapabilityProfile (fail-closed: 未证明/截断/超容差即拒)
uv run python scripts/v3_broker_certify.py profile --findings findings.json \
    --output profile.json

# 任何 sandbox/order mutation 必须显式 --mutation-approval (签名)
uv run python scripts/v3_broker_certify.py probes --account <acct> \
    --environment sandbox --mutation-approval approval.json
```

profile 的每个能力区 (trusted clock / raw envelope / idempotency / auction
TIF+ cutoff / pagination+cursor+retention / execution / exit rate / credential
session fencing) 都 fail-closed。任何 `UNPROVEN` / 截断 / cursor 回退 /
clock skew 超容差在 profile 构造时即拒绝。

## 2. Enablement (BrokerEnablementManifest)

production adapter 只能加载 hash 被有效 `BrokerEnablementManifest` 绑定的冻结
profile。manifest 是双人一次性 + GOVERNANCE Ed25519 签名, `trusted_at` 落在
`[issued_at, expires_at]` 窗口内。窗口外或任一 area hash 漂移 (account/
environment/currency/clock/.../fencing) 拒绝并命名违规区。

```text
verify_broker_enablement(envelope, profile, verifier, current_head,
                         required_capability, trusted_at)
  -> VerifiedBrokerEnablement
```

## 3. Dispatcher (SEND_CLAIMED)

dispatcher 不做 adapter-side precheck 代替 Gateway 事务。序列:
请求 Gateway `SEND_CLAIMED` -> 用精确 client ID 发送不可变 payload ->
durable append raw receipt/timeout -> 向 Gateway 回报状态。

**恢复规则**: 一个 claimed 命令若无 durable authenticated ACK, 状态为
`SUBMISSION_AMBIGUOUS`。若认证幂等且 send/cutoff 截止都仍有效, 重试**相同**
ID/payload; 否则只 query/cancel/reconcile。生成新 ID 被禁止。

## 4. Normalization

`apply_cumulative_execution` 按 `new_cumulative - last_cumulative` 产生 delta;
非显式 bust 的累计回退 = `UNEXPLAINED_CUMULATIVE_ROLLBACK` halt (不 clamp)。
`apply_bust` 追加逆经济; `apply_correction` 先 bust-old 再 apply-new。同一
canonical source 集合的任意 push/poll 排列经 `normalize_batch` 收敛到相同
revision/资本。historical order state 保持 terminal, 但 active 经济投影可能
重开 position/ExitMandate (重建 exit duty)。

## 5. 对账 (分页完整)

`Reconciler.capture_complete_snapshot()` 绑定 query parameters、页数、cursor、
broker as-of/received time 与 raw envelope root。tolerance 按 fact 类型版本化
(qty/notional/cash BLOCKING, fee ADVISORY); 无通用货币 epsilon。material/
unknown break 锁定 no-entry 但**先持久化** external fact (不丢弃)。confirmation
只 link 已有 canonical fact 或 post delta, 不重复资本。

## 6. 生命周期调度

独立 entry/exit/query/reconcile 队列与限流 bucket。exit 不能耗 entry 授权,
entry 不能耗 exit/query/reconcile 容量。进程 lease release 只释放进程 lease,
不释放任何 durable exit-work lease (重启后 exit duty 仍在队列)。过 cutoff 的
entry 被拒, exit/query/reconcile 继续。broker throttle 退还本次 attempt 并延后。
unknown sellable shares 触发 query/reconcile + 零额卖出, 不猜数量。

## 7. Writer Handoff

```
ACTIVE -> DRAINING -> BROKER_RECONCILED -> HANDOFF_COMPLETE
```

monotonic fencing epoch。old worker 停 entry、drain/reconcile, 然后证明外部
credential/session 已撤销 + network egress 已移除 (若 broker 无法撤销 session,
需 process/host termination proof + network-policy proof)。只有这些 proof
**且** durable cursor checkpoint 后, new worker 才收到下一个 fencing epoch。
旧 epoch 永久失效: 任何其下 send 被 fence (WRITER_NOT_AUTHORITY /
EPOCH_SUPERSEDED / ENTRY_FENCED), 击败旧 writer 复活与 stale fd/socket 重发。
DRAINING/BROKER_RECONCILED 期间 entry fenced, 仅 exit/query/reconcile 继续。

## 8. 灾备 (DisasterRecoveryManifest)

```
PRE_RESTORE -> BACKUP_VERIFIED -> STORES_RESTORED -> RECONCILED
    -> RECOVERY_COMPLETE
```

restore 需签名 `DisasterRecoveryManifest` (双人一次性):
1. 全 CapabilityVerifier 链校验 manifest。
2. backup root hash 必须与 manifest 绑定精确相等 (BACKUP_ROOT_MISMATCH)。
3. recovery/fencing epoch 必须严格超过 live epoch (RECOVERY_EPOCH_NOT_ADVANCED
   / FENCING_EPOCH_NOT_ADVANCED) — 陈旧/重放 manifest 不能重开 entry。
4. durable inbox/outbox/broker cursor 必须存在且与 manifest cursor proof 绑定。
5. 进入前必须 reconcile 完整 broker 状态并重证 conservation; live/ambiguous
   order 未清零 / 守恒未证阻断。
6. lost credential 不可复用 — complete 前必须 present 新 fence proof。
7. 激活新 writer 于提升后的 fencing epoch; 旧 writer/旧 epoch 永久失效。

RECOVERY_COMPLETE 前 entry 全程 fenced, 仅 exit/tightening/query/reconcile
继续。

## 9. 首次 BROKER_CONFIRMED exploration (未启用)

取得独立 security/compliance/reconciliation/DR 批准后, 用签名一次性
`EXPLORATION` envelope 启动新 BROKER_CONFIRMED Trial/Stage: exploration
aggregate <=2%; 无现存 broker EDGE grant 时 total portfolio gross <=2%。
expiry/assessment 后只 drain; 任何未决 exploration 风险或法律 finality 缺口
阻断重发, 后续尝试必须重新消耗 Attempt/multiplicity/exploration budget,
不能续期或改写为 edge。proxy/manual evidence 是 prior only。

**仅在真实 broker round trip + reconciliation 证明该 mode 后更新 AGENTS.md。**
当前生产 adapter 仍为 disabled, 本节为前瞻性程序, 不构成启用授权。

## 完成门槛 (Completion Gate)

- 恰好一个有效 adapter epoch 可发送; 每个 order 有一个 durable Gateway claim
  与一个不可变 client ID。
- BrokerCapabilityProfile 证明账号绑定、幂等、auction TIF/cutoff、
  pagination/cursor/retention 与 clock 语义。
- duplicate/late/out-of-order/bust/correction 从不复制或隐藏资本; 重开风险
  重建 exit duty。
- 旧 credential/session/process/network 路径在 handoff 或 DR 后不能提交。
- durable scheduler 在 CLI/entry/service 故障与独立限流下保留 exit。
- 首次 broker 风险使用新 broker-mode evidence 与完整 2% exploration envelope;
  无 proxy/manual authorization 被 relabel。
