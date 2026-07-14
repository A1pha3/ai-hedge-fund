---
难度: ⭐⭐⭐
类型: 进阶分析
预计时间: 15 分钟
前置知识:
  - [项目总览](overview.md) ⭐⭐
  - [项目定位与边界](positioning.md) ⭐⭐
---

# 设计哲学与原则

本分叉的工程决策可以收束为七条原则。这些原则不是宣传口号——每一条都对应一个具体的代码行为或数据治理动作。读懂这七条，就能预判系统在新场景下会如何反应。

| 原则 | 一句话表达 | 落到代码的具体动作 |
|---|---|---|
| 凸性优先 | 选择「尾部上翘、回撤可控」的 setup | BTST 启用、OversoldBounce 暂停 |
| 机械执行移除情绪 | 决策由规则给出，不由人工判断 | `--daily-action` 全自动扫描 + Kelly 仓位 |
| 数据驱动迭代 | 结论必须能用本地数据复现 | paper_trading_backtest 是第一性原理依据 |
| 统计显著性纪律 | E[r] 符号不能单独支持决策，看 CI 与尾部 | OversoldBounce 暂停不是因为「亏钱」 |
| 诚实披露 stale 数据 | 浅数据必须降级标记 | `degraded=True`、`⚠残缺`、`regime_authorization_evidence_unavailable` |
| gate 与 ranking 解耦 | ranking 用 boosted score，gate 用 pre-bonus score | C232 NS-11：bonus 只进 ranking，不污染 gate 阈值 |
| 因子诊断用全 universe | 结论必须用全 universe 回测验证 | MR 因子推荐池诊断反向 vs 全 universe 正向 → 回滚反转 |

## 凸性优先

凸性（convexity）指「亏损有限、收益分布右偏」的 payoff 结构。本分叉只接受凸性 setup 进入 `--daily-action`，对称或左偏 setup 即使 E[r] 为正也不进入。

2026 H1 回测显示 BTST 涨停突破在三个 regime 都赚钱：

```
BTST (n=133):  crisis=+16.93%/76%  risk_off=+8.87%/78%  normal=+6.29%/66%
```

crisis 反而最强（+16.93%/76%）——这是「危机加仓有数据支持」的直接依据。系统据此设计 regime 加仓逻辑：crisis/risk_off 触发时，扫描器请求 12% 仓位例外。当前因 canonical manifest 缺少可重算的 regime 授权证据，v2 ledger 安全降级到 10% 并披露 `regime_authorization_evidence_unavailable`，证据完成绑定前不实际加仓。

## 机械执行移除情绪

`--daily-action` 的设计目标是「读缓存 3 秒返回次日 BUY 信号」，整个流程没有任何人工干预点：

1. 扫描器在 `price_cache` 上跑 setup 定义（`src/screening/offensive/setups/btst_breakout.py`）
2. Kelly 仓位公式给出每票权重（`src/screening/offensive/kelly.py`，half-Kelly，单票硬上限 10%）
3. 写入 `data/paper_trading_v2/ledger.sqlite3`

这种机械化的代价是：当 setup 定义本身有 bug 时，错误会无差别扩散到所有触发标的。2026-07-10 修复的涨停板块判定 bug 就是典型——旧固定 9.5% 阈值会把 20% 板的非涨停大涨日误判为涨停，导致 BTST 触发条件被错误满足。修复后 `limit_up_pct_for_ticker` 按板块前缀取阈值（主板 9.5%/科创创业 19.5%/北交所 29.0%）。

机械执行的纪律要求：每次 setup 定义变更后，必须用 `data/paper_trading_backtest/journal.jsonl` 重跑回测验证。`✅ 已验证`：59 笔 OversoldBounce 回测用的是完整版 setup（volume 列在 commit `7c51cef8`(07-07) 加入，回测在 07-08 跑），不是残缺版。

## 数据驱动迭代

每个 setup 的去留、每个参数的调整，都必须能用本地数据复现。`data/paper_trading_backtest/journal.jsonl` 是验证 setup 有效性的第一性原理依据——403 条记录（211 BUY + 192 EXIT），覆盖 2026-01-15 → 2026-07-06。

⚠ **不要和 `data/paper_trading/`（运行时实例，0 笔 EXIT）混淆**。曾因此误判系统「0 笔成交」。

数据驱动迭代的反向约束：当本地数据不足以验证时，结论必须降级。`price_cache` 只有 6 个月深度，导致 `scripts/setup_research.py` 直接跑会 n=0（IS/OOS 切分按 2020-2026，但价格数据只有 2026）。`phase0_report_20260708.md` 声称的 n=1762 **无法从本地数据复现**——它在别处（更深历史）生成。

当报告结论与回测数据冲突时，以回测数据为准。曾发生过一次盲信报告的事故：Phase 0 报告声称 OversoldBounce E=+3.42%（n=1113），据此对 OversoldBounce 统一加仓，但真实回测（n=59/E=+0.34%/CI 跨 0）显示无 alpha 可放大 → 有害。事故后确立规则：**引用 Phase 0 报告的结论前，先与 paper_trading_backtest 真实数据交叉验证**。`known_distributions.py` 中的硬编码常量（n=1762 等）无自动刷新，引用前同样需要交叉验证。

## 统计显著性纪律

E[r] 的符号不能单独支持决策。OversoldBounce 暂停的理由不是「亏钱」——它的 E[r]=+0.34% 是正的。暂停理由是统计证据不足：

| 检查项 | BTST | OversoldBounce | 决策含义 |
|---|---|---|---|
| E[r] | +8.15% | +0.34% | 都为正，不能单独判定 |
| 95% CI | 远高于 0 | `[-3.15%, +3.83%]` 跨 0 | OB 无法证明赚钱 |
| t 值 / p 值 | 显著 | t=0.19, p≈0.85 | OB 不显著 |
| 亏损>10% 占比 | 11% | 20% | OB 尾部更毒 |
| 亏损>15% 占比 | 6% | 12% | OB 尾部更毒 |
| crisis 分层 | +16.93%/76%（n=21） | -1.15%/48%（n=21） | OB crisis n 太小不可靠 |
| risk_off 分层 | +8.87%/78% | +13.11%/100%（n=3） | OB 与 crisis 矛盾 → 分层不可靠 |
| 机会成本 | — | 仓位受限时有统计显著的 BTST 替代 | OB 占仓位有害 |

恢复 OversoldBounce 的方式是 `DAILY_ACTION_DISABLED_SETUPS=none`，但前提是「补全历史数据重跑后再决定去留」。

## 诚实披露 stale 数据

当数据深度不足以判定条件时，系统**降级标记**而非静默通过：

- BTST 的「资金流 >20d 均值」条件依赖 `data/fund_flow_cache/*.csv`。该缓存普遍浅（<5 天），条件无法判定 → `degraded=True`，渲染时标 `⚠残缺`。
- 运行时检测口径比回测分布更宽松，operator 须知晓。
- `stop_would_have_triggered` 只进 reasoning 字符串、不影响 realized P&L。回测验证（2026-07-10，81 笔 BTST）显示所有止损策略在当前牛市样本都会降低 E[r] 和 Sharpe——均值回归 setup 的波动反而赚钱，故默认不执行。可用 `DAILY_ACTION_EXECUTION_STOP=atr_k2|atr_k3|fixed8` 在熊市/高波动期手动启用真实止损执行（改变 P&L 口径，启用前应跑 `scripts/backtest_exit_strategies.py` 确认当前行情有利）。

⚠ 止损是「披露用的，不执行」这一事实必须显式说明，不能让读者误以为系统有动态止损保护。2026 H1 的 192 笔回测 0 笔触发，是因为行情好；这不能外推到熊市。

## gate 与 ranking 应解耦

C232 NS-11 修复确立了一条边界：ranking 用 boosted score（含 consecutive bonus），gate 用 pre-bonus score。如果同一 score 字段同时喂 gate 和 ranking，bonus 会跨域污染 gate 决策——本来不该过 gate 的票因为 bonus 加成被错误放行。

具体实现是 `signal_fusion.py::compute_score_b` 的 `consensus_bonus` 只在 `arbitration_applied` 含 `consensus_bonus` 标记时加 ±0.05，gate 阶段读 `compute_score_decomposition` 的 `base_sum` 而不是 `total`。代价是 debug 时需要同时看两套 score 才能解释为什么某票没过 gate。详见 [设计原则与权衡](../04-design/principles.md) §6。

## 因子诊断必须用全 universe

因子诊断的结论必须用全 universe 回测验证，不能用推荐池子集。推荐池（n=472）显示 mean-reversion 因子与 T+1 收益**反向**，但全 universe（n=8901）证实 MR 全 4 sub-factor 与 T+1 **正向**——推荐池的选择偏差导致误判方向。最终回滚到 `trend:0.65 / mean_reversion:0.35`（`LIGHT_STRATEGY_WEIGHTS`）。

这条原则的工程含义是：每次阈值调整都要跑全 universe 回测，迭代慢但结论不被选择偏差污染。代价是 `price_cache` 数据必须完整，否则 `setup_research.py` 会因数据浅而 n=0。详见 [设计原则与权衡](../04-design/principles.md) §7。

## 一个例子把这些原则串起来

假设今天是 2026-07-14，operator 想跑 `--daily-action`：

1. **机械执行**：扫描器跑 BTST setup，按板块自适应判定涨停（凸性优先——只接受右尾 setup）。
2. **数据驱动**：扫描到的候选需要资金流条件验证；若 `fund_flow_cache` 浅，标 `⚠残缺`（诚实披露 stale 数据）。
3. **统计显著性纪律**：BTST 候选可出 BUY 信号（E[r]=+8.15%、CI 不跨 0）；OversoldBounce 候选默认被 `DAILY_ACTION_DISABLED_SETUPS` 拦截。
4. **数据驱动迭代**：仓位上限受 canonical manifest 证据约束，证据缺失时降级到 10% 并披露 `regime_authorization_evidence_unavailable`，不实际加仓——报告与回测冲突时以回测为准。操作完成后，新触发的 BUY 写入 `data/paper_trading_v2/ledger.sqlite3`，未来用 `journal.jsonl` 重跑回测验证 setup 是否仍有 alpha。

## 下一步阅读

- 想跑通第一次 `--auto`：[快速开始](../02-user-manual/getting-started.md)
- 想看 BTST setup 的完整定义：[BTST 涨停突破设计](../04-design/btst-breakout-design.md)
- 想看仓位规则细节：[Kelly 仓位设计](../04-design/kelly-position-sizing.md)
- 想看七条原则的完整设计与权衡：[设计原则与权衡](../04-design/principles.md)
