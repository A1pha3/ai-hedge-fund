# v3 BTST 前向 Trial 启动 Runbook — 解锁前置检查清单 (2026-08-22, R21)

目标: `ForwardPairedTrialRunner` 解锁（= 官方 Trial 启动）前的 owner 检查
清单与操作顺序。每步都有可执行的验证命令；**任何一步未过，正确结果是
不启动**。

## 前置检查清单（全部必须绿）

### ① 治理身份（原语已落地 R18）
```bash
uv run python scripts/v3_governance_identity.py check --dir data/v3_governance_identity
# 期望 {"ok": true, ...}; 未生成则先跑 generate (见 v3-governance-identity.md)
```

### ② 特权 worker 进程边界（原语已落地 R20）
- daemon 部署形态与生命周期管理（systemd/launchd 或手动 nohup）是
  owner 启动工程的部署决策——原语面（bind/lease/peer-cred/serve_once
  + 5 测）已就绪，接线方式不设限但必须保持: socket 0600、活 lease
  单实例、同 uid 准入。

### ③ 两臂 capital 台账（路径约定已落地 R21）
- 约定路径 `<trial_root>/arms/<champion|challenger>/capital.sqlite3`
  （`v3/orchestration/arm_layout.py` 单一权威）；两臂库由 genesis
  restore 初始化（`scripts/v3_trial_genesis.py`，capital-only 已支持），
  读路径缺库 fail-closed、绝不静默新建。
- **模式矩阵（2026-08-22 执行演练实证）**：影子前向试验的 seed 台账
  用 `DAILY_BAR_PROXY` 绑定且 `broker_account_id=None`（proxy 池语义，
  `AccountBinding` 校验器强制）；arm_session_checkpoint 的 mode 必须与
  台账绑定 mode 一致（checkpoint 校验器强制）。演练链 seed→dry-run→
  seal→冷读→hash→双臂 restore→约定路径 open→PIT checkpoint 全绿
  （scratch: `data/tmp/trial-scratch`，可删）。

### ④ 证据/治理/决策三库与 spine
- trial root 单 evidence 库 + governance 库 + stage 回执归档
  （Phase A 原语）；SessionSpine 注册与 expected-session 一致性。

## 启动顺序

0. **前置（owner）**：trial root 四库空文件占位（`evidence.sqlite3` /
   `bars-evidence.sqlite3` / `spine.sqlite3` / `governance.sqlite3` 各
   `touch`）＋ 身份目录 v2 再生成（R38 起治理签发四键随默认生成集产出；
   v1 目录缺 exchange-calendar/治理键，见 v3-governance-identity.md）。
1. ①②③④ 全绿 → 生成/确认 trial genesis（`v3_trial_genesis.py`，
   dry-run 默认零写入，先 dry 后真跑）。
1b. **bootstrap 三步（R38 生产入口，均 dry-run 默认零写入）**：
   `scripts/v3_trial_bootstrap.py seed-evidence`（首会话 regime 观察＋bars
   schema）→ `enroll-spine`（权威日历派生 enrollment，assessment=T+10）→
   `seal-trial`（参数文件→互证 artifact→治理键签名→封存→stage 签发→回执
   归档）。注意：seal 的 attempt 预留是消耗性（同参数重放=类型化冲突，
   multiplicity 纪律）。
2. 用治理身份 signer 替换 ephemeral rig（`governance_identity.load` →
   `repository_for`/`signer_for` 接线）。
3. 特权 worker daemon 启动（UDS bind）→ 用一次 `assemble` 请求冒烟
   （返回 `ok:true` + merkle root）。
4. **runner 解锁**：这是最后的 owner 开关动作（代码 fail-closed 的解除
   本身是一个显式提交，须 owner 在场执行，不由 autodev 代理）。
5. 首会话后核对：session_batch seal 幂等、pair 提交恰等重放、两臂
   checkpoint 从各自台账读出。

## 回退

- 启动后任何一层 fail-closed 触发：不重试猜测，先 `replay`/`verify`
  定位；Trial 的证据时间轴 append-only，回退 = 停止后续会话推进
  （已封存会话保持可验，不删除）。
- 治理身份泄露: 按 identity runbook 轮换（新目录新 key_id），旧身份
  目录作废，受影响签发面重签。

## 边界（如实）

本 runbook 是清单与顺序，不是权限——runner 解锁、daemon 部署形态、
身份密钥物理保管始终是 owner 决策。R18/R20/R21 消除的只是三块技术
缺口。
