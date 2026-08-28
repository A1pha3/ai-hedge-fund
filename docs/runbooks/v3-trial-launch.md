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

0. **前置（owner）**：身份目录 v2（R53 Op1 已于 2026-08-28 执行：v1 改名
   `data/v3_governance_identity-revoked-20260828` 废弃，v2 在 canonical
   路径 `data/v3_governance_identity` 生成，8 命名空间 `check` 全绿，
   有效期至 2027-08-28）。巡检命令：
```bash
uv run python scripts/v3_governance_identity.py check --dir data/v3_governance_identity
# namespaces 应含 regime/exchange-calendar/btst-bars/btst + 四个 governance.*
```
1. **genesis-seed（R39 生产入口，fresh-world 构造器；dry-run 默认零写入，
   `--execute` 才真写）**：一条命令完成四库空占位 + seed 台账创建
   （DAILY_BAR_PROXY 绑定、`broker_account_id=None`——影子试验模式矩阵）
   + genesis 封存 + 双臂 restore 到 arm_layout 约定路径。同参数重放幂等；
   四库占位任一非空 → `trial_root_not_fresh`（世界已初始化，换新 root）。
   `trial_root` 必须是 canonical 绝对路径（资本层路径守卫拒绝相对路径）；
   `--units`/`--unit-price-cents`/`--source-authority` 是落账后永久的
   genesis 经济事实（owner 显式决策，默认 10000 单位 @ ¥10.00）。
```bash
uv run python scripts/v3_trial_bootstrap.py genesis-seed \
    --trial-root <绝对路径 trial_root> --trial-id <trial_id> \
    [--units 10000] [--unit-price-cents 1000] \
    [--source-authority governance.bootstrap] [--execute] [--now <UTC ISO>]
```
   （既有 `v3_trial_genesis.py` 仍可用于对**外部既有台账**做 dry-run
   盘点/再封存；新 trial 世界一律走 `genesis-seed`。）
1b. **bootstrap 三步（R38 生产入口，均 dry-run 默认零写入，
    `--execute` 才真写；trial 参数的业务正确性由参数文件作者负责）**：
```bash
# 播种首会话 regime 观察 (固定 REGIME_EVIDENCE_ID, readiness 指纹绑定;
# 首个 decide 幂等复用种子观察) + bars 库 schema 落盘
uv run python scripts/v3_trial_bootstrap.py seed-evidence \
    --identity-dir <身份目录> --trial-root <trial_root> \
    --calendar data/reports/trade_calendar.json \
    --readiness-manifest data/reports/daily_action_readiness_YYYYMMDD.json \
    --signal-session YYYY-MM-DD [--execute] [--now <UTC ISO>]
# spine enrollment (权威日历派生, assessment = 排程末位 T+10)
uv run python scripts/v3_trial_bootstrap.py enroll-spine \
    --identity-dir <身份目录> --trial-root <trial_root> \
    --calendar data/reports/trade_calendar.json \
    --start YYYY-MM-DD --end YYYY-MM-DD [--execute]
# 治理封存 + stage 签发 + 回执归档 (trust 头自动从身份目录绑定)
uv run python scripts/v3_trial_bootstrap.py seal-trial \
    --identity-dir <身份目录> --trial-root <trial_root> \
    --trial-id <trial_id> --params <trial-params.json> [--execute]
```
   注意：seal 的 attempt 预留是消耗性（同参数重放=类型化冲突，
   multiplicity 纪律）；stage 契约要求 issued_at < enrollment_start。
2. 日度驱动（R36 CLI; R38 修正 decide 快照加载面 — 真实三参签名 +
   VerifiedSnapshotResult 解包，新增 `--data-dir`）：
```bash
uv run python scripts/v3_trial_session.py decide \
    --identity-dir <身份目录> --trial-root <trial_root> \
    --trial-id <trial_id> --calendar data/reports/trade_calendar.json \
    --readiness-manifest data/reports/daily_action_readiness_YYYYMMDD.json \
    --data-dir data --signal-session YYYY-MM-DD [--execute]
```
2b. **日度市场推进（R40 前置完备性）**：decide 之后的执行窗口推进
    （T+1..T+10 开盘结算 + marks 估值 + 守恒重验）。bar-source 必须是
    **未复权 tushare `pro.daily` 日快照**（court raw 格式
    `daily_YYYYMMDD.csv`，含 `pre_close`——限价围栏从 pre_close × 板块
    幅度推导）。刷新用研究面续传工具（幂等，已存在文件跳过）：
```bash
uv run python scripts/btst_court_fetch.py   # data/research/btst_court/raw/daily/
uv run python scripts/v3_trial_session.py advance \
    --identity-dir <身份目录> --trial-root <trial_root> \
    --trial-id <trial_id> --calendar data/reports/trade_calendar.json \
    --signal-session YYYY-MM-DD --through-session YYYY-MM-DD \
    --bar-source data/research/btst_court/raw/daily [--execute] [--now <UTC ISO>]
```
    dry-run 与 execute 共用前置校验（栈构造/证据发布之前）：冻结排程窗口
    （信号会话 + 后 10 会话）内每个会话的 `daily_*.csv` 必须在位，缺失
    即类型化 `bar_sessions_missing` 并输出完整缺失清单；窗口外
    through_session 在 dry-run 即拒（`advance_window_not_in_schedule`）；
    execute 只解析窗口内快照（driver 面同款整窗口预检——任一会话缺失
    时零 bar 发布）。
    ⚠ **不可用 `data/price_cache/` 作 bar-source**：它是 qfq 前复权且无
    `pre_close`（`src/tools/price.py`），限价围栏/资本标记口径全错——
    数据完整性红线（AGENTS.md）。
    ⚠ **decide 合法时间窗（R47 演练成文）**：SELECTED 候选证据的入库窗是
    `[signal_date 15:00 UTC, +24h]`（北京 T0 23:00 ～ T+1 23:00）——证据
    store 的 `ingested_at ∈ [observed_at, available_at]` 冻结契约强制。
    窗口内的 crash-retry 重跑合法（同会话恰等复用）；跨窗（隔日及以后）
    重跑/补驱动会在候选发布处以 `store_timeline_rejected`（ingested_at
    must be between observed_at and available_at）**类型化拒绝——这是预期
    PIT 行为，不是故障**（事后补写的候选永不满足 cutoff 前入库纪律）。
    此类会话的官方出口与跳过会话一致：本步 NO_RUN 补记。
    ⚠ **decide dry-run 假绿收口（R48 D6，D8 分层收敛）**：日历成员
    （`signal_session_not_in_calendar`）在 dry-run/execute 双面于构造栈
    之前类型化拒绝；**入库窗检查（`decide_window_violated`）是 dry-run
    专属**——dry-run 现在要求显式 `--now` 落在窗内才报绿（缺省真实墙钟
    对陈旧会话必然拒绝）。execute 面的窗口判定由 driver 首步守卫以
    store 真相权威执行：窗口外未提交 → 零发布类型化拒绝；窗口内已提交
    SELECTED 候选的窗口外重驱 → 恰等重放收敛（crash 复验形态；NO_SIGNAL
    pair 无候选不在逃生门内——pair 已完整，窗外重驱本无必要，拒绝无害）。
2c. **错过会话补记**：enrollment 窗口内因故未 decide 的会话，在
    assessment 日期过后补 NO_RUN 终态（幂等，append-only spine）。
    ⚠ **会话只许前向驱动（R41）**：跳过的会话一律走本步 NO_RUN 补记，
    **绝不回头补 decide**——晚于后续会话补驱动早会话会被驱动器以
    `regime_session_regression` 类型化拒绝（regime 修正链的 active 头
    只能随驱动前进；此前该形态会静默倒序并破坏晚会话的幂等重放）。
```bash
uv run python scripts/v3_trial_session.py finalize-missed \
    --identity-dir <身份目录> --trial-root <trial_root> \
    --trial-id <trial_id> --calendar data/reports/trade_calendar.json \
    [--execute] [--now <UTC ISO>]
```
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

## 生产 Trial Root 登记（2026-08-28，R53b Op2，owner 常设授权执行）

- 生产 root：`data/v3_trial_root`（绝对路径
  `/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/v3_trial_root`）
- trial_id：`trial-btst-regime-r1`；research_program：`research.btst.regime`
- genesis：10000 单位 @ ¥10.00（runbook 默认，DAILY_BAR_PROXY 绑定，
  `broker_account_id=None`）；seal manifest hash `0e981670…`；
  stage `stage-trial-btst-regime-r1-001`（回执归档于
  `<root>/archive/stage-issuance/trial-btst-regime-r1/`）
- 治理参数：`config/trials/trial-btst-regime-r1-params.json`（入册审计）。
  派生规则成文：champion/challenger 行为指纹 = sha256(各 policy section
  canonical JSON bytes)；attempt checkpoint = sha256("attempt-ledger:genesis:
  no-prior-attempts")（全局 attempt ledger 基础设施未建前的创世声明）；
  enrollment 2026-08-28..09-27（spine 已注册 20 会话，assessment=T+10，
  末次 2026-10-16）；stage loss budget 200000 cents（policy 0.02 cap ×
  ¥100,000 资本）
- 日度驱动（每晚）：
  1. 日度管道产出当日 readiness manifest（~18:30 北京）
  2. `v3_trial_bootstrap.py seed-evidence --signal-session <当日> --execute`
     （首会话必须；后续会话由 decide 幂等复用/追加 regime 修正链）
  3. `v3_trial_session.py decide --signal-session <当日> --execute`
     （窗口 [当日 15:00 UTC, +24h] 内）
  4. bar 源续传（`btst_court_fetch.py`）+ `advance --through-session <最新>`
  5. 错过会话一律 `finalize-missed` 补 NO_RUN，绝不回头补 decide
