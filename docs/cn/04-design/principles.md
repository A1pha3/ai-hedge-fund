---
难度: ⭐⭐⭐⭐
类型: 专家设计
预计时间: 22 分钟
前置知识:
  - [系统架构总览](../03-architecture/overview.md) ⭐⭐⭐
  - [设计哲学与原则](../01-introduction/design-philosophy.md) ⭐⭐⭐
---

# 设计原则与权衡

本系统的工程决策围绕一个判断：A 股市场在 2026 上半年给的是「均值回归 setup 的波动反而赚钱」的窗口，而不是「止损截断尾部就能稳定获利」的窗口。这条判断来自 192 笔真实成交（`data/paper_trading_backtest/journal.jsonl`），下文每条原则都给到对应数据依据，并显式列出权衡的代价。

## 1. 凸性优先（Phase A "稳定小 edge"）

`--daily-action` 全市场扫描 `data/price_cache/*.csv`，不依赖 `--auto` 输出的 `score_b` 候选池。理由写在 `src/screening/offensive/daily_action.py` 顶部 docstring：

> 凸性 setup 要极端股票，不是"好股票"

`score_b` 排序出来的是「质量均匀偏高」的票，而 BTST 涨停突破要的是「能量从积蓄到爆发」的极端样本。两者目标不同，候选空间也必须独立。`daily_action.py::_load_st_tickers` 在 full_market 模式下独立过滤 ST，因为 `--auto` 候选池在 Layer A 已经过滤过，但 full_market 直扫不经 Layer A。

**权衡**：放弃 `score_b` 排序的"质量筛选"作为初筛，换来 setup 信号不被候选池选择偏差污染。代价是扫描空间必须用涨停注入（`cache_refresh.py`）补齐小盘涨停股，否则会漏。

## 2. 机械执行移除情绪

`generate_daily_action` 把信号 → 计划 → 入场 → 止损 → 退出全部预提交。`render_daily_action` 输出的 BUY 列表带 `entry_price / soft_stop / hard_stop / time_exit / invalidation_condition` 五个字段，operator 只照着执行，不做盘中决策。

`_ENTRY_WINDOW_CUTOFF = time(17, 0)` 锁死买入窗口：信号日 S → 计划买入日 = S 下一交易日开盘。当日 17:00 后旧信号失效，避免事后补单。

**权衡**：放弃盘中机会（如尾盘抢筹），换取行为可复盘。代价是当 17:00 数据未就绪时当天不出信号，必须等次日。

## 3. 数据驱动迭代

阈值调整必须基于全 universe 回测，不能用推荐池。`btst_breakout.py::_PRE_RUNUP_MAX_PCT` 的注释给出对照：

```python
_PRE_RUNUP_MAX_PCT = 8.0  # 回测验证 (2026-07, 626 只 A 股): 8-10% 区间 52.4%/+3.10% 弱于池均值; <8% 58%+ 明显优于 >8% 53%
```

涨停前 5 日累计涨幅阈值从 10% 收紧到 8%，依据是 626 只 A 股全 universe 回测，不是推荐池子集。同理，`_MIN_TRIGGER_STRENGTH = 0.50` 来自 1308 信号阈值敏感性回测：

```python
# ts>=0.35: n=1114, WR 61.0%, +7.16%, Sharpe 0.365 (旧值)
# ts>=0.50: n=777,  WR 62.8%, +7.54%, Sharpe 0.383 ← 取此 (平衡 WR/收益/样本量)
# ts>=0.55: n=634,  WR 64.0%, +7.33%, Sharpe 0.391 (Sharpe 最优但样本少)
```

`0.50` 不是 Sharpe 最优（`0.55` 是），而是 WR / 收益 / 样本量三者的平衡点。

**权衡**：阈值调整需要每次跑全 universe 回测，迭代慢；换来的是阈值不被选择偏差污染。代价是每次校准都需要补全 `price_cache` 数据，否则 `setup_research.py` 会因数据浅而 n=0。

## 4. 统计显著性纪律

`OversoldBounce` 默认暂停（`_DEFAULT_DISABLED_SETUPS = {"oversold_bounce"}`），理由写在 `daily_action.py` 第 85-90 行：

> 1. 整体 E[r]=+0.34% 但 95% CI [-3.15%, +3.83] 跨 0 (p≈0.85) → 无法证明赚钱
> 2. 尾部比 BTST 更毒: 亏损>10% 占比 20% vs BTST 11%; 亏损>15% 占比 12% vs 6%
> 3. 机会成本: 仓位受限时有统计显著的替代品 (BTST E=+8.15%, p<<0.05)

关键不是"crisis 分层亏钱"，而是统计证据不足。`crisis n=21` 的 `-1.15%` 样本太小，`risk_off n=3` 反而 `+13.11%`，分层内部矛盾，不能作为独立决策依据。`known_distributions.py::OVERSOLD_BOUNCE_T5` 把这条证据固化进分布参数：

```python
OVERSOLD_BOUNCE_T5 = Distribution(
    n=59,
    winrate=0.525,
    avg_gain=0.1073,
    avg_loss=-0.1115,  # -11.15% (原 -5.57% 严重低估)
    convexity_ratio=0.96,  # <1.5 → Kelly f* ≈ 0
    expected_return=0.0034,  # +0.34%
    ci_low=-0.0315,  # 95% CI 跨 0
    ci_high=0.0383,
    ic=0.003,
)
```

`convexity_ratio=0.96 < 1.5` 的工程含义是：Kelly 公式给出接近零的仓位，仓位上限 5%（`_MAX_POSITION_PCT_BY_SETUP["oversold_bounce"]`）即使恢复也是低仓位。

**权衡**：放弃 crisis regime 可能的反弹机会，换取仓位配额不被无 alpha setup 占用。代价是 crisis 期可分配资金集中到 BTST，集中度风险上升。

## 5. 诚实披露 stale 数据

C234 NS-5 修复引入 `as_of` 字段标注数据时点 + staleness 检测。`btst_breakout.py` 的 `degraded` 字段就是这条原则的实例：

```python
if len(historical) >= _MAIN_FLOW_MIN_HISTORY_DAYS:
    lookback = historical[-_MAIN_FLOW_LOOKBACK_DAYS:]
    # ...
    if len(historical) < _MAIN_FLOW_LOOKBACK_DAYS:
        degraded = True
        degradation_reason = f"条件2 短窗口: 仅{len(historical)}天 (设计{_MAIN_FLOW_LOOKBACK_DAYS}d)"
else:
    degraded = True
    degradation_reason = f"条件2 跳过: 历史不足 ({len(historical)}<{_MAIN_FLOW_MIN_HISTORY_DAYS}日)"
```

资金流历史不足 5 天时，BTST 命中仍然输出但标 `degraded=True`，render 阶段挂 `⚠残缺` 提示。这比"假装重算硬编码值"诚实 — 后者会让 operator 误以为数据已更新但实际数据源仍 stale。

**权衡**：degraded 命中保留在候选列表，可能让 operator 误以为可下单；换来的是数据问题可见。代价是 operator 必须自己读 `⚠残缺` 标签判断是否入场。

## 6. gate 与 ranking 应解耦

C232 NS-11 修复：ranking 用 boosted score（含 consecutive bonus），gate 用 pre-bonus score。如果同一 score 字段同时喂 gate 和 ranking，bonus 会跨域污染 gate 决策。

`signal_fusion.py::compute_score_b` 的 `consensus_bonus` 只在 `arbitration_applied` 含 `consensus_bonus` 标记时加 ±0.05，gate 阶段读 `compute_score_decomposition` 的 `base_sum` 而不是 `total`，保证 bonus 不进 gate 阈值判断。

**权衡**：ranking 和 gate 用两套 score，实现复杂度上升；换来的是 gate 决策不被 bonus 污染。代价是 debug 时需要同时看两套 score 才能解释为什么某票没过 gate。

## 7. 因子诊断必须用全 universe

`strategy_scorer.py` 第 53-57 行的注释给出反面案例：

> 全 universe 因子回测 (2026-06-25, n=8136) 证明 MR 是正向有效因子
> C226 revert: 全 universe 诊断 (C225 n=8901) 证实 MR 全 4 sub-factor 与 T+1 反向
> (sep<0, IC=-0.128); MR-heavy (0.65) 在更长样本下跑输 trend-heavy (daily excess -0.28%)
> mean-reversion bet 在 T+1 horizon 失败 (短期 momentum 主导)

推荐池（n=472）显示 MR 反向 → 全 universe（n=8901）显示 MR 正向 → 推荐池选择偏差导致误判。最终回滚到 `trend:0.65 / mean_reversion:0.35`（`LIGHT_STRATEGY_WEIGHTS`）。

修复现有因子 > 挖新因子：`momentum` 阈值松绑（`MOM_THRESHOLD 0.05→0.03`，`MOM_VOLUME_CONFIRM_RATIO 1.0→0.8`）让 AVOID 比例从 56% 降到 42%，收益大于加 10 个新因子。

**权衡**：全 universe 回测每次跑要 8136+ 样本，耗时长；换来的是结论不被选择偏差污染。代价是迭代速度慢，且需要维护完整的 `price_cache` 数据。

## 总结：原则之间的张力

七条原则并非线性叠加。凸性优先要求全市场扫描，但全 universe 诊断要求完整数据 — 当 `price_cache` 只有 6 个月深度时（AGENTS.md 明示），两个原则同时受挫。诚实披露 stale 数据是兜底：数据不全时显式标注 `degraded`，让 operator 自己判断信号可信度，而不是让系统假装数据完整。

这套设计的最大风险是「样本期偏差」：所有回测都基于 2026 上半年牛市样本，BTST 三个 regime 都赚钱，crisis 最强。一旦市场切换到熊市或震荡市，crisis 加仓系数 1.2× 可能从「捕获 alpha」变成「放大亏损」。`DAILY_ACTION_EXECUTION_STOP` env 和 `DAILY_ACTION_REGIME_SIZING=false` 是为这种情况预留的逃生口。

## 深入阅读

- [设计哲学与原则](../01-introduction/design-philosophy.md):入门版七条原则概述
- [系统架构总览](../03-architecture/overview.md):两条管线的边界与共享约定
- [BTST 涨停突破设计](btst-breakout-design.md):凸性优先与统计显著性纪律的具体实例
