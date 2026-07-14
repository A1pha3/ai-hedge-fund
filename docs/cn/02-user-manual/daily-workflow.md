---
难度: ⭐⭐
类型: 核心概念
预计时间: 25 分钟
前置知识:
  - [快速开始](getting-started.md) ⭐
  - [安装与配置](installation.md) ⭐
---

# 每日工作流

A 股每日选股系统由两条独立管线组成,共享缓存数据但产出不同。本文说明两条管线的协作时序、交易日各阶段的操作,以及次日买入决策的生成规则。

## 概念定义

### 管线 1:`--auto` 全市场筛选

收盘后运行,对全市场约 5000 只 A 股执行四策略因子评分,产出当日 Top 10 推荐。

- 命令:`uv run python src/main.py --auto`
- 运行时机:A 股收盘后(约 15:30 之后,建议 16:00 后)
- 耗时:数分钟(取决于网络与 LLM 速度)
- 输出:`data/reports/auto_screening_YYYYMMDD.json`
- 流程:Layer A 候选池快筛 → Layer B 四策略评分(trend / mean_reversion / fundamental / event_sentiment)→ score_b 融合 → investability 排序 → Top 10

### 管线 2:`--daily-action` 凸性 setup

读取 `--auto` 产出的缓存,扫描凸性 setup,产出次日 BUY 信号与仓位计划。

- 命令:`uv run python src/main.py --daily-action`
- 运行时机:`--auto` 完成后,当日 17:00 之前
- 耗时:约 3 秒(纯读缓存,不调 LLM)
- 输出:次日 BUY 信号 + 入场价 + 止损 + Kelly 仓位 + 风险计划
- 两种 setup:
  - BTST 涨停突破(T+10):✅ 启用。2026 H1 回测 winrate=68%,E[r]=+8.15%
  - OversoldBounce 超跌反弹(T+5):⏸️ 默认暂停(E[r]=+0.34%,95% CI 跨 0,统计不显著)

### 买入窗口

信号日 S 产出 BUY 信号后,计划买入日 = S 的下一交易日开盘。买入日当天 17:00 后视为窗口已过,未成交的信号不再有效。

## 使用场景

### 场景 A:每个交易日的例行流程

收盘后跑 `--auto` 刷新数据底座,晚间跑 `--daily-action` 拿到次日买入计划,次日开盘执行。

### 场景 B:盘中只读检查

交易日盘中(9:30 - 15:00)不需要跑任何命令。如果想查看前一日产出的信号,直接 `--daily-action` 读缓存即可,3 秒返回。

### 场景 C:补跑历史日期

用 `--end-date` 指定历史交易日,跳过 17:00 时间窗口检查:

```bash
uv run python src/main.py --daily-action --end-date=20260710
```

## 交易日时间线案例

以 2026-07-13(周一)交易日为例,展示从收盘到次日买入的完整流程。

### 09:00 盘前(可选)

```bash
# 查看市场状态与盘前摘要
uv run python src/main.py --market-status
uv run python src/main.py --daily-brief
```

`--daily-brief` 输出当日 Top 3 决策卡,基于上一交易日的 `--auto` 报告。

### 15:30 收盘

A 股收盘,当日行情数据开始流入 Tushare。等待约 30 分钟让数据源稳定。

### 16:00 运行 `--auto`

```bash
uv run python src/main.py --auto
```

产出 `data/reports/auto_screening_20260713.json`,包含当日 Top 10 推荐。这一步是数据底座,后续 `--daily-action` 依赖它写入的 price_cache 与 regime 数据。

### 16:30 运行 `--daily-action`

```bash
uv run python src/main.py --daily-action
```

读取 `--auto` 缓存的 price_cache 与 regime 数据,扫描 BTST 涨停突破 setup,产出 2026-07-14(周二)开盘的 BUY 信号。

输出包含:

- ticker 与名称
- setup 类型(BTST / OversoldBounce)
- 入场价(下一交易日开盘价预估)
- 止损价(ATR 计算)
- Kelly 仓位(half-Kelly,单票硬上限 10%)
- regime 授权(crisis / risk_off / normal)

### 17:00 信号生成窗口关闭

`--daily-action` 的 17:00 检查会阻止当日 17:00 之后产出新的次日信号。如果错过,用 `--end-date` 显式覆盖:

```bash
uv run python src/main.py --daily-action --end-date=20260713
```

### 2026-07-14 09:30 次日开盘

根据昨日 `--daily-action` 输出的计划执行买入。当日 17:00 后买入窗口关闭,未成交的信号失效。

## API/配置详解

### 环境变量

| 变量 | 默认 | 作用 |
|---|---|---|
| `DAILY_ACTION_DISABLED_SETUPS` | `oversold_bounce` | 暂停的 setup 列表;设为 `none` 恢复全部 |
| `DAILY_ACTION_EXECUTION_STOP` | (空) | 真实止损模式:`atr_k2` / `atr_k3` / `fixed8`;默认不执行 |
| `BTST_0422_P7_GAP_OVERLAY_MODE` | `off` | 跳空保护:`off` / `report` / `enforce` |
| `BTST_0422_P7_GAP_WARN_THRESHOLD` | `0.005` | 跳空警告阈值(0.5%) |
| `BTST_0422_P7_GAP_HALT_THRESHOLD` | `0.01` | 跳空熔断阈值(1%) |

### 仓位规则

- half-Kelly 计算
- 单票硬上限 10%
- 组合硬上限 60%
- regime 加仓(12%)当前暂停,待 canonical regime evidence 可由 repository 重验后恢复;扫描器请求加仓时会披露 `regime_authorization_evidence_unavailable` 并安全降级到 10%

### 止损规则

`stop_would_have_triggered` 默认只进 reasoning 字段,不影响 realized P&L。2026 牛市样本中,所有止损策略都会降低 E[r] 和 Sharpe(均值回归 setup 的波动反而赚钱)。熊市或高波动期可用 `DAILY_ACTION_EXECUTION_STOP=atr_k2` 启用真实止损执行,启用前应跑 `scripts/backtest_exit_strategies.py` 确认当前行情有利。

## 常见误区

### 误区 1:把 `--auto` 和 `--daily-action` 混为一谈

两条管线产出不同。`--auto` 产出 Top 10 推荐列表(因子评分排序),`--daily-action` 产出次日 BUY 信号(Kelly 仓位 + 止损)。前者是数据底座,后者是交易计划。`--daily-action` 不调 LLM,只读 `--auto` 写入的缓存。

### 误区 2:盘中跑 `--auto` 拿当日信号

`--auto` 依赖收盘后的完整行情数据。盘中跑会拿到不完整数据,导致评分失真。盘中如果想看信号,跑 `--daily-action` 读上一交易日的缓存。

### 误区 3:认为止损会自动执行

默认情况下,止损价只出现在 `--daily-action` 输出的 reasoning 字段里,不改变 P&L 口径。回测中 192 笔 EXIT 0 笔触发止损(2026 行情好)。需要真实止损时显式设置 `DAILY_ACTION_EXECUTION_STOP`。

### 误区 4:OversoldBounce 暂停是因为"亏钱"

OversoldBounce 暂停的统计理由是 E[r]=+0.34% 但 95% CI `[-3.15%, +3.83%]` 跨 0(t=0.19, p≈0.85),无法证明它赚钱;同时尾部亏损比 BTST 厚(亏损 >10% 占比 20% vs BTST 11%)。crisis 子样本 n=21 太小,不是独立决策依据;risk_off n=3 反而 +13.11%,与 crisis 矛盾,说明分层不可靠。

## 总结速查

| 阶段 | 时间 | 命令 | 耗时 | 产出 |
|---|---|---|---|---|
| 盘前(可选) | 09:00 | `--daily-brief` | <5 秒 | Top 3 决策卡 |
| 收盘后 | 16:00 | `--auto` | 数分钟 | Top 10 推荐 JSON |
| 晚间 | 16:30 | `--daily-action` | ~3 秒 | 次日 BUY 信号 |
| 次日开盘 | 09:30 | (手动执行) | - | 买入 |
| 窗口关闭 | 次日 17:00 | - | - | 信号失效 |

## 下一步

- [CLI 参考](cli-reference.md) — 浏览全部命令与参数
- [报告解读](interpreting-reports.md) — 读懂 JSON 报告字段
- [BTST 涨停突破设计](../04-design/btst-breakout-design.md) — setup 背后的设计逻辑
