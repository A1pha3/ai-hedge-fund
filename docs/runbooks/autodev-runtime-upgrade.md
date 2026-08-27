# AutoDev Runtime 升级 Runbook

本文回答一个问题：skill 内核仓库（`/Volumes/mini_matrix/github/a1pha3/skills/autodev`）前进了新版本之后，如何把产品仓库（`/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork`）的 autodev runtime 跟随升级。

协议语义以内核 `SKILL.md` 与 `contracts/` 为准，本文只做操作层归纳；授权链与历史决策的权威记录在 `~/.zcode/skills/autodev-host-quant/owner_grants.json` 各条目的 `decision_memo`。

## 原理：为什么有两条路

runtime 账本封面上锚定了一个内核提交（`active_source_commit_oid`）与其契约包指纹（`active_contracts_digest`）。每次写账前，内核身份门核对"磁盘上的内核 checkout"与锚定是否一致，不一致即 `inactive_runtime` 拒绝写入——fail-closed，防止未经认可的内核版本动账本。

内核升级后：

- **契约没变**（`contracts/` 三个文件逐字节一致）→ `reanchor-source` 一条命令把锚点前移，账本原封不动；
- **契约变了** → reanchor 守卫按设计拒绝（`source_reanchor_contracts_changed`），唯一正路是 owner 显式的**归档旧 runtime + 在新内核上初始化新 runtime**（完整重激活）。

## 第 0 步：判定走哪条路

```bash
# 内核当前的契约包指纹
python3 ~/.zcode/skills/autodev/cli/autodev.py validate --kind contracts \
  --input /Volumes/mini_matrix/github/a1pha3/skills/autodev/contracts

# runtime 锚定的指纹
python3 ~/.zcode/skills/autodev/cli/autodev.py replay \
  --repo /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork | \
  python3 -c "import sys,json;print(json.load(sys.stdin)['data']['active_contracts_digest'])"
```

两个字符串相同 → **路线 A**；不同 → **路线 B**。

**共同前提**（两条路线都要求）：内核仓库 checkout 干净停在新 HEAD——

```bash
cd /Volumes/mini_matrix/github/a1pha3/skills/autodev
git status --short        # 必须无输出
git log --oneline -1      # 确认是新版本
```

有未提交改动时身份门报 `runtime_identity_untrusted`；先处理改动再升级。

## 路线 A：契约没变 —— 一条命令

```bash
python3 ~/.zcode/skills/autodev/cli/autodev.py reanchor-source \
  --repo /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork \
  --invocation-id reanchor-$(date +%Y%m%d-%H%M)
```

账本只追加一条 `source_reanchored` 事实，封面版本号前移。跑完 replay 确认 `active_source_commit_oid` = 新 HEAD 即完成。

## 路线 B：契约变了 —— 完整重激活（六步）

1. **归档前先取出当前 Product Contract**（归档后旧投影不可直读）：

```bash
python3 ~/.zcode/skills/autodev/cli/autodev.py replay \
  --repo /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork | \
  python3 -c "import sys,json;json.dump(json.load(sys.stdin)['data']['product_contract']['contract'],open('/tmp/pc.json','w'))"
```

2. **登记 owner 授权**：`~/.zcode/skills/autodev-host-quant/owner_grants.json` 顶部加条目，`actions` 含 `runtime.archive` / `runtime.initialize` / `product.record`，basis 写明触发指令，memo 记录归档语义与先例引用。裸 CLI 没有授权 adapter，第 3/4/5 步必须经 `host_driver.py` 走。

3. **归档旧 runtime**（在**旧锚定内核**的 checkout 下执行；授权回执绑定归档前账本字节摘要，旧 runtime 原子移动为 `.git/autodev-archive-<arc-id>/`，字节级保留）：

```bash
python3 ~/.zcode/skills/autodev-host-quant/host_driver.py archive-runtime \
  --repo /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork \
  --authority-ref ~/.zcode/skills/autodev-host-quant/owner_grants.json
```

4. **切到新 HEAD 初始化新 runtime**（initial receipt 绑定当前内核提交）：

```bash
git -C /Volumes/mini_matrix/github/a1pha3/skills/autodev checkout <新版本commit>
python3 ~/.zcode/skills/autodev-host-quant/host_driver.py init-runtime \
  --repo /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork \
  --authority-ref ~/.zcode/skills/autodev-host-quant/owner_grants.json \
  --initial-contract-bundle /Volumes/mini_matrix/github/a1pha3/skills/autodev/contracts
```

5. **重录 Product Contract + 冒烟**：

```bash
# product.record：payload = {"contract": <第 1 步内容>, "authority_ref": <grants 路径>}
python3 ~/.zcode/skills/autodev-host-quant/host_driver.py transact \
  --repo /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork \
  --invocation-id inv-runtime-upgrade-<日期> --request-id upgrade-product-record \
  --expected-projection-digest <replay 输出> \
  --action product.record --payload /tmp/pc_record.json

# campaign.start → campaign.close 空往返一次，验证写路径
```

6. **三查收尾**：replay 里 `active_source_commit_oid` = 新 HEAD、契约指纹与 `validate` 输出一致、产品仓库 `git status` 干净。

## 纪律红线

- 别在内核仓库有未提交改动时升级（`runtime_identity_untrusted`）。
- 别让两个会话同时操作内核 checkout——并发切版本是历史上 `inactive_runtime` 反复出现的根源；升级期间独占，做完即释放。
- 归档不是删除：旧账本字节级保留在 `.git/autodev-archive-<arc-id>/`，历史取证随时可用；不需要的归档也只是放着，不占运行路径。
- 新账本序列从事件 1 重新计数，campaign 编号从头开始——这是重激活的预期语义，不是故障。

## 偷懒方式

以上全部可以不背：直接对 agent 说一句「**把 autodev runtime 升级到最新版**」。agent 会自动做第 0 步判定，契约没变走 reanchor，契约变了走完整重激活（归档→重初始化→重录→冒烟），把指令登记为 owner 授权并汇报归档 ID 与验证结果。

## 升级实例记录

- **2026-08-27**：`209ce28` → `b3ba4cd`，走路线 B（契约变：`policy.json` 增 method 晋级 realized_efficacy probation 门）。归档 `arc-bf506fe2931d1a0f099396f0760072a5`（88 事件 + 3 个 op 分支），授权条目 `runtime-upgrade-b3ba4cd-2026-08-27`，Product Contract v4 逐字重录 confirmed，campaign 冒烟零 detach 通过。
- 历史归档：`arc-4f6b1ae3`（2026-08-25 前）、`arc-772c931f`（2026-08-25 rebuild-smoke）、`arc-bf506fe2`（本次）。
