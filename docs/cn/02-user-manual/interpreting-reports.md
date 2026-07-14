---
title: 输出报告解读
difficulty: 2⭐⭐
type: 参考手册
estimated_time: 15 分钟
prerequisites:
  - 跑过至少一次 [CLI 命令](./cli-reference.md)
  - 了解 [日常运行流程](./daily-workflow.md)
---

# 输出报告解读

本文档解释 `--auto` 写入的 `auto_screening_YYYYMMDD.json` 与 `--daily-action` 终端输出里的字段含义、颜色编码与决策标记。读懂这两份输出，才能判断信号是否可信、仓位是否需要手工调整。

## 两套独立报告

| 报告 | 来源命令 | 落盘位置 | 用途 |
|---|---|---|---|
| 全市场筛选报告 | `--auto` | `data/reports/auto_screening_YYYYMMDD.json` | 四策略融合评分 + Top N 推荐池 |
| 凸性 setup 动作 | `--daily-action` | 终端 stdout（不落盘） | 次日 BUY / EXIT / SKIP 信号 |

两套报告共享 `price_cache` 与 `regime_history`，但评分逻辑、候选空间、持有期均独立，不应混读。

## auto_screening JSON 字段

### 顶层字段

| 字段 | 类型 | 含义 |
|---|---|---|
| `date` | str | 信号日 YYYYMMDD |
| `model_version` | str | 打分模型版本（git short sha） |
| `market_state` | object | 市场状态对象，含 `regime`、`limit_up_count`、`layer_a_count` |
| `recommendations` | array | Top N 推荐列表，按下文 `score_b` 排序 |
| `tracking_summary` | object | T+1 / T+3 / T+5 历史追踪统计 |
| `layer_a_count` | int | Layer A 通过的候选总数 |

### recommendations 元素字段

| 字段 | 类型 | 含义 |
|---|---|---|
| `ticker` | str | 6 位股票代码 |
| `name` | str | 股票名称 |
| `industry` | str | 申万行业 |
| `score_b` | float | 综合评分，决定颜色编码与 high_pool 资格 |
| `composite_score` | float | 组合评分（多信号融合，含动量/板块/一致性） |
| `investability` | float | 可投资性评分（流动性+市值+ST 过滤等） |
| `decision` | str | `BUY` / `HOLD` / `AVOID` |
| `strategy_scores` | object | `{trend, mean_reversion, fundamental, event_sentiment}` 四维分项 |
| `technicals_reasoning` | str | 技术面解读文本 |
| `pct_change` | float | 当日涨跌幅 |
| `industry_pct_change` | float | 行业当日涨跌幅 |
| `industry_2d_pct` | float | 行业 2 日涨跌幅 |
| `industry_net_flow` | float | 行业净资金流 |

### score_b 颜色编码

| 区间 | 颜色 | 含义 | 后续处理 |
|---|---|---|---|
| `>= 0.35` | 绿色 | 看多 | 进入 high_pool 候选 |
| `>= 0.0 且 < 0.35` | 黄色 | 中性 | 不入 high_pool，仍参与排名 |
| `< 0.0` | 红色 | 看空 | 排除出推荐池 |

阈值在 `src/main.py` 顶部以 `SCORE_B_GREEN_FLOOR = 0.35` / `SCORE_B_YELLOW_FLOOR = 0.0` 集中定义，修改时只动这两行。

### decision 标记含义

| decision | 触发条件 | 操作建议 |
|---|---|---|
| `BUY` | score_b 进入 Top N 且 investability 达标 | 可纳入次日开盘计划 |
| `HOLD` | 已在推荐池但当前排名下滑 | 维持现有持仓，不加仓 |
| `AVOID` | score_b 转负或触发风险条件 | 不开新仓，考虑减仓 |

## daily-action 终端输出字段

`--daily-action` 不写 JSON，直接打印到 stdout。每条候选行包含下列字段，渲染逻辑在 `src/screening/offensive/daily_action.py` 的 `render_daily_action_v2`。

### 候选行字段

| 字段 | 含义 | 取值示例 |
|---|---|---|
| `action` | 动作 | `BUY` / `EXIT` / `SKIP` |
| `ticker` | 6 位代码 | `000001` |
| `setup_name` | setup 代号 | `btst_breakout` / `oversold_bounce` |
| `entry_price` | 入场价（信号日收盘） | `12.34` |
| `stop_loss` | 止损价（披露用，不执行） | `11.20` |
| `position_pct` | 仓位百分比（half-Kelly，单票硬上限 10%） | `8.5%` |
| `regime_authorization` | regime 加仓授权 | `BTST_CRISIS` / `BTST_RISK_OFF` / `NORMAL` |
| `trigger_strength` | 5 因子 ranker 评分，`>= 0.50` 才出 BUY | `0.62` |
| `horizon` | 持有期 | `T+10`（BTST）/ `T+5`（OB） |
| `degraded` | 资金流历史不足时为 `True`，渲染为 `⚠残缺` | `True` |
| `regime_authorization_evidence_unavailable` | canonical manifest 缺失可重算证据时为 `True` | `True` |

### 关键标记解读

**`⚠残缺`（degraded=True）**：BTST 命中但「资金流 > 20d 均值」条件因 `fund_flow_cache` 深度不足（普遍 < 5 天）无法判定。运行时检测口径比回测分布更宽松，operator 须知晓该信号未通过完整过滤。

**`regime_authorization_evidence_unavailable=True`**：扫描器可能请求 crisis / risk_off 加仓，但 v2 ledger 因 canonical manifest 缺少可重算的 regime 授权证据而安全降级到 10%，不实际加仓。在证据完成绑定前，所有候选仓位均为基础值。

**`new_entries_blocked`**（输出末尾）：表示已加载 verified PIT snapshot 失败，本次不输出新 BUY，但持仓生命周期（到期结算 / EXIT / MTM）仍照常推进。需运行 readiness 流水线恢复新仓规划。

### setup 启用状态

| setup | 默认状态 | 持有期 | 控制 |
|---|---|---|---|
| `btst_breakout`（涨停突破） | 启用 | T+10 | 始终启用 |
| `oversold_bounce`（超跌反弹） | 暂停 | T+5 | `DAILY_ACTION_DISABLED_SETUPS=none` 恢复 |

OB 暂停理由不是「crisis 亏钱」（crisis n=21 样本太小不可靠），而是 E[r]=+0.34% 的 95% CI `[-3.15%, +3.83%]` 跨 0，统计上无法证明赚钱；同时尾部亏损比 BTST 厚（亏损 > 15% 占 12% vs 6%）。

## 两套统计数字的口径差异

阅读 daily-action 输出时常遇到两套并列的统计数字，混淆会误判。

| 输出位置 | 标签 | 样例 | 来源 | 用途 |
|---|---|---|---|---|
| 表头「启用/暂停 setup」 | 真实回测 | `n=133 E=+8.15%` | `paper_trading_backtest` 2026 H1 实盘回测 | 验证策略是否有效 |
| 候选行 | 先验（驱动 Kelly） | `n=1762 E=+3.4%` | `known_distributions.py` 全池历史回测 | 计算 Kelly 仓位 |

两套数字样本不同、口径不同，不可直接比较。「+8.15%」是说服 operator「策略能赚钱」的依据；系统实际算仓位用的是「+3.4%」。并列出现是设计如此。

## 止损字段的实际语义

`stop_loss` 与 `stop_would_have_triggered` 在当前版本是**披露用**字段，不进入 P&L 结算：

- 回测验证（2026-07-10，81 笔 BTST）显示所有止损策略在当前牛市样本都会降低 E[r] 和 Sharpe，均值回归 setup 的波动反而赚钱。
- paper P&L 一律按 T+N close 结算，不按止损出场。
- 熊市 / 高波动期可设 `DAILY_ACTION_EXECUTION_STOP=atr_k2|atr_k3|fixed8` 启用真实止损执行，改变 P&L 口径。启用前应跑 `scripts/backtest_exit_strategies.py` 确认当前行情有利。

## 常见误区

| 误区 | 实际行为 |
|---|---|
| 看到 `stop_loss` 就以为会自动卖出 | 当前只披露，不执行 |
| 把表头「真实回测」的 E[r] 当成仓位计算依据 | 仓位用的是「先验」分布 |
| `regime_authorization=BTST_CRISIS` 就以为已加仓到 12% | 当前安全降级到 10%，加仓暂停 |
| `degraded=True` 的信号当成完整 BTST | 资金流条件未完整过滤，需人工复核 |
| `--auto` 的 `decision=BUY` 等同于 `--daily-action` 的 BUY | 两套独立系统，前者是因子评分，后者是凸性 setup |

## 总结速查

- 读 JSON 看 `score_b` 决定颜色，看 `decision` 决定动作，看 `strategy_scores` 拆解因子贡献。
- 读 daily-action 终端看 `action` / `trigger_strength` / `position_pct` 三个字段即可。
- 任何带 `⚠` 或 `unavailable` / `blocked` 的标记都意味着该字段语义被降级，不能按字面值信任。
- 止损字段只读，不进 P&L；想启用真实止损要改环境变量并先跑回测。
