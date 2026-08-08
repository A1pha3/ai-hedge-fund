# v3 迁移与 Canary 运行手册 (Plan 06)

## 范围

本文档覆盖 v2→v3 资本 authority 迁移与 mode-specific 2% canary 的
**操作程序**。迁移与激活都是一次性、短时、签名批准的动作; 本文档不授予
任何自动执行权。

## 角色与身份

| 主体 | 职责 | 永不持有 |
|---|---|---|
| Migration Coordinator | 推进状态机、绑定 preimage | v2/v3 写事务、签名材料 |
| Compatibility Writer | 迁移期唯一 v2 写入口 | v3 写能力 |
| Authority Registry | 单库 CAS flip | 跨库事务 |
| Canary Activator | 核验 2% 激活前提 | 签名、edge 评估 |
| Canary Monitor | maintain/tighten/fence/drain | 晋升、阻断 exit |

## 批准窗口

真实 freeze/flip/activate 前, 必须取得 `MigrationApprovalManifest`
(双人 attestation + GOVERNANCE Ed25519 签名), 且 `trusted_at` 落在
`[allowed_from, allowed_until]` 短时窗口内。窗口外即使签名有效也拒绝。

## 标准操作程序

```bash
# 0. 盘点 (只读)
uv run python scripts/v3_migration.py --state-path ... --migration-id ... \
    --source-path ... --ledger-id ... inventory

# 1. 冻结 v2 新风险 (mutation, 需 --manifest 且默认 dry-run)
uv run python scripts/v3_migration.py ... freeze-new-risk \
    --manifest approval.json --apply

# 2. adoption / reconcile / prepare
uv run python scripts/v3_migration.py ... adopt-orders --manifest ... --apply
#   (coordinator advance: CAPITAL_RECONCILED 由 verify 子命令完成)
uv run python scripts/v3_migration.py ... prepare --manifest ... --apply

# 3. 逐项守恒核验 (缺任一 section 即失败)
uv run python scripts/v3_migration.py ... verify

# 4. flip (单库 CAS; preimage 漂移/未决 lease/未 ACK 投影即拒绝)
uv run python scripts/v3_migration.py ... flip --manifest ... --apply

# 5. 重放 inbox 至 durable head
uv run python scripts/v3_migration.py ... replay-inbox --manifest ... --apply

# 6. 最终对账后 v2 只读; entry 此前保持 fenced
uv run python scripts/v3_migration.py ... finalize --manifest ... --apply

# 任意时刻只读状态
uv run python scripts/v3_migration.py ... status
```

## 崩溃恢复

| 崩溃点 | 状态 | 恢复 |
|---|---|---|
| v2 commit 前 | revision 未 projected | 重启后 `apply_next` 重放 |
| v2 commit 后 ACK 前 | projected 未 ACK, lease 未决 | flip 阻断; 只读对账证明真实源状态后重放 ACK |
| lease 持有期间 | unresolved lease | flip 阻断; 确认写者已死后释放 |
| flip CAS 中 | 单库事务, 要么全成要么全不成 | 重试 `compare_and_flip` |

任何模糊崩溃状态都阻断 flip, 直到只读对账证明真实源状态。

## Canary (2%)

- 只允许 `DAILY_BAR_PROXY` 或 `MANUAL_CONFIRMED`; `EXPLORATION` 一律拒绝;
  `BROKER_CONFIRMED` 首次 2% 等 Plan 07。
- gross cap 是同 mode portfolio aggregate ≤ 2%; 必须有固定整数 loss budget。
- monitor 只能 maintain/tighten/fence/drain; 永不自动晋升 5%/10%。
- 15% latch 恢复: 新 `RiskEpochStarted` + 更高 epoch `PolicyActivation` +
  `RECOVERY` envelope, 三件齐全; NAV/HWM 不重置, 继承风险全部计入。
- 所有 halt/outage 下 exit 继续。

## Shadow 一致性门禁

```bash
uv run python scripts/v3_shadow_audit.py --v2 v2.json --v3 v3.json \
    --expect exit:T+10:T+1 --enforce-gate
```

存在未解决 `DATA_MISMATCH | KERNEL_BUG | UNKNOWN` 且影响 capital/exit/
sample attribution 时, 不得 flip 或激活 canary。

## 灾难恢复演练

使用签名测试 `DisasterRecoveryManifest`: 核验备份 root/cursor → 提升
recovery/fencing epoch → 重放 inbox/outbox → 对账 live/ambiguous 状态 →
守恒通过前保持 entry fenced。真实 DR 前必须独立批准。
