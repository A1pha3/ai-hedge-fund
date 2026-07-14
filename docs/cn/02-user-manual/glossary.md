---
难度: ⭐
类型: 入门教程
预计时间: 10 分钟
前置知识:
  - 无
---

# 术语表

本文档按英文字母序列出 A 股每日选股系统的核心术语，每条含中文名（English）、一句话定义与首次出现的文档链接。术语首次在正文出现时优先采用「中文（English）」格式，后续沿用中文。

## A

**ATR（Average True Range）**：平均真实波幅，Wilder 法计算的价格波动指标，用于推导止损价。首次出现：[输出报告解读](./interpreting-reports.md)。

**AVOID**：`--auto` 报告中的决策标记，表示 score_b 转负或触发风险条件，不开新仓并考虑减仓。首次出现：[输出报告解读](./interpreting-reports.md)。

## B

**BTST（Breakout To Strong Close）**：涨停突破 setup，主力策略。今日涨停 + 涨停前 5 日累计涨幅 ≤ 8%（防追高，`_PRE_RUNUP_MAX_PCT=8.0`）+ 主力资金净流入 > 20 日均值 + 行业当日涨 > 2%，持有 T+10。首次出现：[输出报告解读](./interpreting-reports.md)。

**BUY**：决策标记，表示 score_b 进入 Top N 且 investability 达标，可纳入次日开盘计划。首次出现：[输出报告解读](./interpreting-reports.md)。

## C

**CI（Confidence Interval）**：置信区间，E[r] 的 95% bootstrap 置信区间。CI 跨 0 表示统计上无法证明赚钱。首次出现：[输出报告解读](./interpreting-reports.md)。

**composite_score（组合评分）**：多信号融合为单一排名分，含动量、板块强度、一致性等维度。首次出现：[输出报告解读](./interpreting-reports.md)。

**convexity setup（凸性 setup）**：盈亏不对称、上行大于下行的策略。凸性比 > 1.5 才算合格。首次出现：[输出报告解读](./interpreting-reports.md)。

**crisis**：市场状态之一，危机环境。BTST 历史最强（胜率 76%，E +16.93%），触发 1.2× 加仓。首次出现：[输出报告解读](./interpreting-reports.md)。

**candidate pool（候选池）**：Layer A 通过的股票集合，约 300 只（`MAX_CANDIDATE_POOL_SIZE=300`），作为后续评分的输入。首次出现：[CLI 完整参考](./cli-reference.md)。

**consecutive recommendation（连续推荐）**：同一只票连续多日进入 Top N，作为信心排名的输入维度之一。首次出现：[CLI 完整参考](./cli-reference.md)。

## D

**degraded（残缺）**：setup 命中但部分条件因数据不足被跳过（如资金流历史 < 5 天），渲染为 `⚠残缺`。首次出现：[输出报告解读](./interpreting-reports.md)。

**drawdown（回撤）**：组合净值从峰值的回撤幅度，驱动风控状态。首次出现：[输出报告解读](./interpreting-reports.md)。

## E

**E[r]（Expected Return）**：期望收益，历史命中平均收益 = `胜率 × 平均盈利 + 亏损率 × 平均亏损`。首次出现：[输出报告解读](./interpreting-reports.md)。

**EXIT**：daily-action 动作标记，表示持仓到期或触发后关闭，回填已实现 P&L。首次出现：[输出报告解读](./interpreting-reports.md)。

## F

**factor scoring（因子评分）**：四策略（trend / mean_reversion / fundamental / event_sentiment）融合打分，产出 score_b。首次出现：[CLI 完整参考](./cli-reference.md)。

## H

**half-Kelly（半凯利）**：0.5 × 完整 Kelly 仓位。牺牲约 25% 长期收益换大幅降低破产概率和波动。首次出现：[输出报告解读](./interpreting-reports.md)。

**HOLD**：决策标记，表示已在推荐池但当前排名下滑，维持现有持仓不加仓。首次出现：[输出报告解读](./interpreting-reports.md)。

**horizon（持有期）**：setup 的自然持有周期，BTST 为 T+10，OversoldBounce 为 T+5。首次出现：[输出报告解读](./interpreting-reports.md)。

## I

**IC（Information Coefficient）**：信息系数，setup 信号与全市场基线的 rank 相关性，> 0 说明有排序信息。首次出现：[输出报告解读](./interpreting-reports.md)。

**investability（可投资性）**：综合流动性、市值、ST 过滤等维度的评分，决定是否纳入推荐池。首次出现：[输出报告解读](./interpreting-reports.md)。

**industry rotation（行业轮动）**：板块强度变化信号，用于行业配置参考。首次出现：[CLI 完整参考](./cli-reference.md)。

## K

**Kelly（凯利公式）**：基于历史分布的最优仓位公式，系统采用 half-Kelly 并叠加单票 10% / 组合 60% 硬上限。首次出现：[输出报告解读](./interpreting-reports.md)。

## L

**LLM（Large Language Model）**：大语言模型，系统中用于事件情绪、新闻解读等环节。首次出现：[故障排除](./troubleshooting.md)。

**LRU（Least Recently Used）**：最近最少使用，缓存淘汰策略。首次出现：[CLI 完整参考](./cli-reference.md)。

## N

**normal**：市场状态之一，默认 / 未知环境，所有 setup 1.0× 仓位。首次出现：[输出报告解读](./interpreting-reports.md)。

## O

**OversoldBounce（超跌反弹）**：备选 setup（默认暂停）。30 日跌幅 > 20% + 3 日主力资金回流转正 + 量比 > 1.5，持有 T+5。首次出现：[输出报告解读](./interpreting-reports.md)。

## P

**纸面交易（paper trading）**：Phase-A 模拟追踪，P&L 在 T+N 收盘回填，不按止损出场。首次出现：[输出报告解读](./interpreting-reports.md)。

**position_pct（仓位百分比）**：daily-action 输出字段，half-Kelly × regime 因子 × 回撤因子 × trigger_strength，受单票 10% 与组合 60% 约束。首次出现：[输出报告解读](./interpreting-reports.md)。

## R

**regime（市场状态）**：从 `regime_history.json` 按信号日读取的状态标签，分 crisis / risk_off / normal 三档，决定加仓倍数。首次出现：[输出报告解读](./interpreting-reports.md)。

**regime_authorization（regime 加仓授权）**：daily-action 输出字段，标示当前 regime 是否允许加仓。当前 v2 ledger 安全降级到 10%，不实际加仓。首次出现：[输出报告解读](./interpreting-reports.md)。

**risk_off**：市场状态之一，防御环境。BTST 1.1× 加仓（胜率 78%，E +8.87%）。首次出现：[输出报告解读](./interpreting-reports.md)。

## S

**score_b（综合评分）**：四策略融合后的评分，决定颜色编码与 high_pool 资格。`>= 0.35` 绿色，`>= 0.0` 黄色，`< 0.0` 红色。首次出现：[输出报告解读](./interpreting-reports.md)。

**signal fusion（信号融合）**：多信号合成单一排名分的环节，产出 composite_score。首次出现：[CLI 完整参考](./cli-reference.md)。

**SKIP**：daily-action 动作标记，表示该候选本次不纳入买入计划。首次出现：[输出报告解读](./interpreting-reports.md)。

**stop_loss（止损价）**：daily-action 输出字段，当前为披露用，不进入 P&L 结算。首次出现：[输出报告解读](./interpreting-reports.md)。

## T

**T+N**：买入后第 N 个交易日，结算按第 N 个交易日收盘价。T+10 ≈ 14 日历日。首次出现：[输出报告解读](./interpreting-reports.md)。

**trigger_strength（触发强度）**：5 因子 ranker 评分（星期 + 板块 + 区间位置 + 波动率压缩 + 反转深度），0-1 之间，`>= 0.50` 才出 BUY 信号。首次出现：[输出报告解读](./interpreting-reports.md)。

## W

**winrate（胜率）**：历史命中里正收益的比例。首次出现：[输出报告解读](./interpreting-reports.md)。

## 环境变量速查

| 变量 | 默认 | 作用 | 首次出现 |
|---|---|---|---|
| `DAILY_ACTION_DISABLED_SETUPS` | `oversold_bounce` | 暂停的 setup 集合，设 `none` 恢复全部 | [输出报告解读](./interpreting-reports.md) |
| `DAILY_ACTION_REGIME_SIZING` | 开启 | 设 `false` 关闭 regime 加仓 | [输出报告解读](./interpreting-reports.md) |
| `DAILY_ACTION_EXECUTION_STOP` | 未设置 | 启用真实止损执行：`atr_k2` / `atr_k3` / `fixed8` | [故障排除](./troubleshooting.md) |
| `DAILY_ACTION_ENFORCE_OPEN_CAP` | `true` | 组合上限是否计入已开仓 | [输出报告解读](./interpreting-reports.md) |
| `TUSHARE_TOKEN` | 必填 | tushare API 令牌 | [CLI 完整参考](./cli-reference.md) |

## 参考文件

术语对应的源码位置：

| 模块 | 文件 |
|---|---|
| 命令分发 | `src/cli/dispatcher.py` |
| 凸性 setup 主逻辑 | `src/screening/offensive/daily_action.py` |
| Setup 定义 | `src/screening/offensive/setups/btst_breakout.py`、`oversold_bounce.py` |
| Kelly 仓位 | `src/screening/offensive/kelly.py` |
| Paper tracker | `src/screening/offensive/paper_tracker.py` |
| 先验分布 | `src/screening/offensive/known_distributions.py` |
| 涨停板块判定 | `src/tools/ashare_board_utils.py` |
| score_b 阈值 | `src/main.py`（`SCORE_B_GREEN_FLOOR` / `SCORE_B_YELLOW_FLOOR`） |
