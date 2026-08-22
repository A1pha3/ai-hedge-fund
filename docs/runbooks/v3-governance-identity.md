# v3 治理身份目录 — Owner Runbook (2026-08-22, R18)

前向 Trial 启动准备工程的第一步: 把 ephemeral 测试链 (每进程随机密钥)
升级为**持久治理身份**。本 runbook 是 owner 的全部操作面。

## 生成 (一次性)

```bash
uv run python scripts/v3_governance_identity.py generate --dir data/v3_governance_identity
```

产物 (全部 0600, `data/` 已被 gitignore 覆盖, 绝不提交):
- `identity.json` — anchor、签发的 issuer 注册表、root 签名 bundle、head witness
- `keys/root.pem` — **信任根私钥** (Ed25519 PKCS8)
- `keys/<namespace>.pem` — regime / 排程 / bar / btst 各签发面私钥

## 保管纪律

1. `root.pem` 泄露 = 整条信任链失守 (任何伪装 issuer 的注册表都能被签发)。
   建议目录放在全盘加密卷; 更高安全等级可离线存放 root、仅在轮换时接入。
2. 目录内私钥必须保持 0600 —— 加载面强制校验, 0644/symlink 一律拒绝。
3. 备份: 目录整体冷备一份 (密钥丢失 = 身份不可恢复, 只能换新身份)。

## 验证 (日常/巡检)

```bash
uv run python scripts/v3_governance_identity.py check --dir data/v3_governance_identity
```

检查面: manifest 严格重解析、root 签名经 `TrustBundleVerifier` 重验
(篡改任何哈希即失败)、私钥权限/symlink/算法、私钥↔签名注册表公钥配对、
信任窗口覆盖。

## 轮换协议

1. **绝不原地改写** — 已有 `identity.json` 的目录, generate 一律拒绝。
2. 轮换 = 在**新目录**生成新身份 (key_id 计划从 `-key-1` 递增,
   多身份并存期的 registry_epoch/predecessor 绑定接线留 Trial 启动工程)。
3. 旧目录人工标记废弃 (建议改名 `<dir>-revoked-<date>`), 不得再用于签发。

## 边界 (如实)

本原语不解锁 `ForwardPairedTrialRunner`、不激活任何 envelope、不连接
broker; 它只把"真实治理身份"从缺项变成 owner 三步操作。特权 worker
独立进程 + UDS 边界、两臂 capital 台账路径约定是启动清单的后续项。
