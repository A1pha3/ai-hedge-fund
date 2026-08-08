# Runbook — V3 Shadow Services (Plan 05)

> Growth Kernel v3 的 CLI 库层 shadow 编排接线 (Plan 05 Task 9)。本文档面向
> **操作员** (运行 CLI / 回答 "v3 shadow 在做什么 / 为什么没输出 / 怎么轮换 policy")。
> 实现细节见 `src/cli/v3_shadow.py` + `src/screening/offensive/v3/orchestration/shadow_trust.py`。

## 一句话状态

Plan 05 落地了 v3 shadow 的**库层编排** (CLI 进程内构造 v3 服务跑 shadow 观测),
**不是** Plan Architecture 要求的 "privileged worker 独立进程 + UDS"。UDS worker
进程层留 Plan 06+。当前 default policy = `off` (零 v3 输出, v2 行为完全不变)。

---

## 当前能做什么 / 不能做什么

| 维度 | 状态 |
|------|------|
| `--daily-action` / `--auto` v2 行为 | ✅ 完全不变 (v3 hook 是只读旁路, OFF 默认零调用) |
| v3 shadow 编排 (DailyActionFlow / AutoFlow) | ✅ 库层跑通 (policy=shadow 时) |
| ShadowDecision 产出 | ✅ 有 capital baseline 时 (kernel ADMITTED → 非零 entry) |
| 真实 governance 激活 | ❌ Plan 禁止 (合成 authority 占位, 非真实授权) |
| 真实 broker 执行 | ❌ execution_authority 恒 `none`, 不连 broker |
| privileged worker (UDS) 进程隔离 | ❌ Plan 06+ (当前 CLI 进程内编排) |
| 真实 capital ledger 注入 | ❌ Plan 06+ (当前 graceful 降级: 无 ledger → capital failed) |

**关键诚实声明**: shadow CLI 真实运行通常**无 v3 capital baseline** (`data/v3_shadow/capital.sqlite3`
不存在), 故 capital 步 graceful failed, shadow 管线 skipped, **不产出 ShadowDecision**。
这是设计预期 (shadow 阶段无真实资本激活)。要产出 ShadowDecision 须先 seed capital
(见下文 "种子 capital")。真实 capital 注入是 Plan 06+ privileged worker 的事。

---

## 配置 (toml)

配置文件: `config/services/v3/services.example.toml` (示例; 复制为 `services.toml`
或显式路径后按本机调整)。CLI 默认读 example 文件 (owner 未显式提供时)。

### 键一览

| 键 | 说明 |
|----|------|
| `[paths].portfolio_id` | 本 flow 治理的 portfolio (ShadowDecision 键) |
| `[paths].evidence_database` | v3 evidence sqlite (BTST/auto 信号) |
| `[paths].blob_root` | v3 evidence blob 存储 |
| `[paths].capital_ledger` | **v3 shadow** capital ledger (Plan 06+ 真实激活态才存在; 缺失→graceful) |
| `[paths].gateway_database` | v3 gateway sqlite (authority/decisions/exits schema) |
| `[paths].shadow_artifacts_dir` | render_json 工件落盘目录 (**绝不**写 v2 reports) |
| `[policy].path` | PolicySnapshot JSON (决定 runtime_mode); 默认 `config/policies/v3/policy-v1.json` |
| `[sizing].*` (5 字段) | Kernel SizingConfig caps (cents); policy JSON 无对应物, 独立配 |

所有路径相对 **repo root** (CLI 由 `__file__` 推导, 不依赖 cwd); 也可填绝对路径。

### 【privileged service-owned】路径 (CLI 不触碰)

以下路径刻意**不在 toml 配置内** — CLI 不读取、不构造、不触达:
- 真实 capital ledger 激活态 (Plan 02 truth, 非 shadow 副本)
- signer keystore (持久化签名材料)
- governance authority DB
- broker credential

shadow-only 阶段 CLI 是同一 OS 用户下同一文件系统主体, OS 级 ACL 不可达 (Plan 06+
privileged worker 的事)。本 plan 守卫是**结构性 default-deny** (见下文 "安全边界")。

---

## Policy 轮换 (runtime_mode)

`runtime_mode` 由 `[policy].path` 指向的 PolicySnapshot JSON 决定。轮换 policy **只改
toml 的 path 键, 不改代码**。

| runtime_mode | 行为 |
|--------------|------|
| `off` (默认) | 零 v3 调用、零 v3 输出 (v2 完全不变) |
| `shadow` | 库层编排跑通 (DailyActionFlow / AutoFlow + reporting 投影) |
| `btst_canary` | ⚠ warning + flow 内建行为 (只读观测步照常, shadow 管线 skip) — 超前于 Plan 05 |
| `authoritative` | 同 btst_canary (超前 warning) — Plan 05 不激活 |

切换示例:

```bash
# 复制 example 配置, 指向 shadow policy
cp config/services/v3/services.example.toml config/services/v3/services.toml
# 编辑 services.toml: [policy].path = "config/policies/v3/policy-shadow.json"
# (须先创建 policy-shadow.json, runtime_mode=shadow)

# 或用环境变量 (Plan 06+ 接线 --v3-config; 当前默认读 example)
```

> Plan 05 只允许 `off` / `shadow`。`btst_canary` / `authoritative` 是超前 mode —
> CLI 打印 warning 并按 flow 内建行为放行 (shadow 管线 skip), 不激活。

---

## 安全边界 (shadow-only 阶段, in-process 偏差)

Plan Architecture 要求 "privileged worker 独立进程 + CLI 不持 writable DSN"。Plan 05
实际是**库层**编排 (Task 1-8 无 FastAPI/uvicorn server 进程层)。CLI 进程内构造服务
持有 capital sqlite 句柄 (shadow 只读), 严格说不满足进程级 writable-DSN 隔离 —
**owner 知情批准**。补偿控制 (AST 守卫锁定, 集成测试 `test_v3_shadow_services.py`
持续验证):

1. **import 面**: `v3_shadow.py` 不 import `v3.governance` / `v3.execution` /
   `v3.gateway` 写面 / `authorizer_api` / `governance_api` / `market_publisher`。
   (`capital_gateway_api` 读 facade 允许 — plan S4 批准; CLI 只用其读面。)
2. **调用面**: 不调用 `activate_*` / `publish_entry` / `claim_send` / `record_fill` /
   `issue_permit` / `seal` / `reserve` 等 authority 写方法。
3. **证据 signer**: 进程内 ephemeral Ed25519 key (`Ed25519PrivateKey.generate()`),
   不读持久化签名材料 — 与 plan 全局约束一致。代价: 证据 provenance 每运行匿名。
4. **物理独立 namespace**: v3 工件落 `data/v3_shadow/` (evidence/gateway/artifacts),
   绝不写 v2 `reports/` 或 `data/paper_trading_v2/`。

### ACL 守卫测试

`tests/offensive/v3/integration/test_v3_shadow_services.py::test_v3_shadow_acl_*`
用 AST (`ast.walk`, 捕获函数级 lazy import) 扫描 `v3_shadow.py`, 任一写面 import 或
写方法调用即测试失败。修改 `v3_shadow.py` 后必须保持这两测试绿。

---

## 启动顺序 / 调用链 (库层编排)

CLI 入口 (`--daily-action` / `--auto`) v2 渲染后调薄 hook:

```
dispatcher.py --daily-action → run_v3_shadow_daily_action(...)
main.py --auto               → run_v3_shadow_auto(...)
```

入口两层 try (rc 保护):
1. **config/policy 加载失败 → 静默返回** (fail-safe OFF; v3 是可选层, 不打扰 v2)。
2. **编排失败 → 打印 `⚠ v3 shadow 编排失败: ...` 并吞掉** (dispatch handler 异常→rc=1,
   故 v3 异常绝不漏出改写 v2 rc)。

SHADOW mode 编排链:
```
load config + policy → build ephemeral trust context (shadow_trust)
  → synthesize authority (PolicyActivation + Envelope 占位, 满足 admission)
  → 防御性 capital reader (ledger 存在→CapitalGatewayApi; 缺失→graceful)
  → DailyActionFlow/AutoFlow + ReportingService + InMemoryShadowStore
  → flow.run → reporting.build → render_text (stdout) + render_json (v3 工件)
```

---

## 种子 capital (产出 ShadowDecision 的前提)

shadow CLI 默认无 v3 capital ledger → capital 步 graceful failed → 不产出 ShadowDecision。
要观测真实 ShadowDecision (如 dogfood / 验证), 手动 seed:

```python
from src.screening.offensive.v3.capital.repository import (
    AccountBinding, CapitalRepository,
)
from src.screening.offensive.v3.capital.flows import GenesisRequest
from src.screening.offensive.v3.contracts import ExecutionMode
from datetime import datetime, timezone

repo = CapitalRepository.initialize("data/v3_shadow/capital.sqlite3")
T = datetime(2026, 8, 5, 15, 0, tzinfo=timezone.utc)  # signal_date 收盘
repo.initialize_genesis(GenesisRequest(
    idempotency_key="genesis-1",
    account_binding=AccountBinding(
        portfolio_id="paper-v3", mode=ExecutionMode.MANUAL_CONFIRMED,
        broker_account_id="acct", base_currency="CNY",
        environment_fingerprint="ab" * 32,
    ),
    unit_quanta=100_000_000,  # NAV 充裕使 kernel sizing 产出非零 entry
    unit_price_numerator=1, unit_price_denominator=1,
    source_authority="governance.test", authorization_reference="g1",
    effective_at=T, as_of=T,
))
```

集成测试 `test_flow_end_to_end_produces_shadow_decision` 示范完整 seed + 编排 + 断言。

> **时钟窗口**: capital snapshot `valid_until = as_of + 1h`。CLI clock 须在
> `[signal_date 15:00, valid_until]` 内 (即收盘后不久运行), 否则 kernel 判 STALE →
> NoTrade。cron 应在收盘后 5-30min 内运行。

---

## 合成 authority (观测用解锁, 非授权)

shadow 观测需要 kernel 实际 ADMIT 才能产出 ShadowDecision (而非恒 BLOCKED)。S2b 修了
family_id 断裂 (flow 用 `BTST_FAMILY` 常量), S4 补上"解锁 admission 的占位 envelope"
(`synthesize_shadow_authority`)。

- **确定性常量** (与 BTST producer 信封逐字一致, 写死不进 toml):
  - `behavior_fingerprint = BTST_BEHAVIOR_BASELINE` = `sha256("btst-v1")`
  - `execution_version = "btst.funnel.v1"`
  - `cost_version = "cn-a-share-costs.v1"`
- **不是授权**: flow `execution_authority` 恒 `none`, ShadowDecision `execution_authority`
  恒 `NONE`, 绝不产生可执行 line。合成 envelope 只是观测用解锁。
- 真实 governance 激活 (签名 envelope 的真实 issuer) 留 Plan 06+ privileged worker。

---

## 故障排查

| 现象 | 原因 / 处理 |
|------|-------------|
| 无 v3 输出 | policy=`off` (默认) 或 config/policy 加载失败 (fail-safe OFF)。检查 `[policy].path` JSON 的 `runtime_mode`。 |
| `⚠ v3 shadow 编排失败: ...` | 编排异常被吞 (rc 保护)。看错误类型: `FileNotFoundError`→路径; `V3ShadowConfigError`→toml 缺字段; 其他→看 stack (logger.debug)。v2 不受影响。 |
| `⚠ v3 shadow: runtime_mode=btst_canary 超前...` | policy 是超前 mode (Plan 05 只 off\|shadow)。改 policy 为 `shadow` 或接受 warning (只读观测)。 |
| capital 步 failed / 无 ShadowDecision | 无 v3 capital ledger (常态)。seed capital (见上文) 或接受 graceful 降级 (snapshot 观测照常)。 |
| ShadowDecision 全 `no_signal` | capital 不够 (sizing 0 entry)。增大 genesis `unit_quanta`; 或 clock 超出 freshness 窗口 (收盘后 5-30min 内运行)。 |

---

## 后续 (Plan 06+)

- privileged worker 独立进程 + UDS (`services/common.py` 已备 `socket_path_for` /
  `lease_path_for` / `validate_socket_acl` / `validate_process_lease` /
  `V3_SOCKET_MODE=0o600`)
- 真实 governance 激活 (替换合成 authority)
- 真实 capital ledger 注入 (替换 graceful reader)
- 真实 broker 执行 (execution proxy/manual, SEND_CLAIMED 线性化)
- 持久化 ShadowDecision (跨进程; 当前 InMemoryShadowStore 同进程桥)
