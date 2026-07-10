# `--daily-action` 术语对照表 (中英)

> 本表覆盖 `uv run python src/main.py --daily-action` 输出里出现的全部技术术语。
> 阅读日志时遇到不懂的词,按类别查这张表即可。
>
> 输出里的 setup 名已显示为「中文名(英文代号)」格式,例如 `涨停突破(btst_breakout)` ——
> 中文名方便阅读,英文代号用于和代码 / journal / 文档对照。

---

## 快速对照:输出里的两套统计数字

阅读日志前先理解这一点,**否则会误判**:

| 输出位置 | 标签 | 数字样例 | 来源 | 用途 |
|---|---|---|---|---|
| 表头「启用/暂停 setup」 | **真实回测** | `n=133 E=+8.15%` | `paper_trading_backtest` 2026 H1 实盘回测 | 验证策略是否有效 |
| 候选行 | **先验(驱动Kelly)** | `n=1762 E=+3.4%` | `known_distributions.py` 全池历史回测 | 计算 Kelly 仓位 |

这两套数字**样本不同、口径不同、不可直接比较**。你看到的「+8.15%」是说服你「这个策略能赚钱」的依据;系统实际算仓位用的是「+3.4%」。两者并列是设计如此,不是 bug。

---

## A. Setup 策略

| 中文 | 英文代号 | 含义 |
|---|---|---|
| 涨停突破 | btst_breakout | 主力策略。今日涨停 + 涨停前 5 日涨幅 ≤ 5%(防追高)+ 主力资金净流入 > 20 日均值 + 行业当日涨 > 2%。持有 T+10。 |
| 超跌反弹 | oversold_bounce | 备选策略(默认暂停)。30 日跌幅 > 20% + 3 日主力资金回流转正 + 量比 > 1.5。持有 T+5。 |
| 凸性 setup | convexity setup | 盈亏不对称、上行大于下行的策略。凸性比 > 1.5 才算合格。空仓时提示「今日无凸性 setup 命中」。 |
| 命中 | hit | 某只票在信号日满足了某 setup 的全部触发条件。 |
| 启用 / 暂停 | active / paused | 当前是否产生新 BUY 信号。`oversold_bounce` 默认暂停(统计不显著)。 |
| 残缺 | degraded | 命中但部分条件因数据不足被跳过(如资金流历史 < 5 天)。标记「⚠残缺」,运行时检测比回测分布更松。 |
| 双信号 | dual signal | BTST 命中同时也在 `--auto` Top-N 里。历史胜率更高但 CI 跨 0 未显著,标记「⭐双信号」,**勿据此加仓**。 |
| 失效条件 | invalidation | setup 逻辑反转的描述性条件(如「价格跌破 触发日收盘 × 0.92」)。只做披露,不自动卖出。 |

---

## B. 仓位管理

| 中文 | 英文 | 含义 |
|---|---|---|
| half-Kelly(半凯利) | half-Kelly | 0.5 × 完整 Kelly 仓位。牺牲约 25% 长期收益换大幅降低破产概率和波动。 |
| 仓位 | position size | 单票建议权重 = half-Kelly × 回撤因子 × regime 因子,受单票上限 10% 和组合上限 60% 约束。 |
| 组合敞口 | portfolio exposure | 全部持仓权重之和。输出形如「组合敞口: 150% / 60% 上限」。 |
| 超配 | overweight | 敞口超过 60% 上限,标记「⚠超配」,新信号被跳过直到仓位到期释放。 |
| 上限 | cap | 单票硬上限 10%(regime 加仓后 12%);组合上限 60%。 |
| 仓位释放 | position release | 持仓到期(T+N)后自动平仓,其权重释放回组合,可重新买入新信号。 |
| 先验(驱动Kelly) | prior (driving Kelly) | `known_distributions.py` 的历史分布,用于算 Kelly 仓位。与表头「真实回测」是两套独立统计。 |
| regime 仓位放大系数 | regime sizing factor | 逆周期加仓倍数:BTST crisis 1.2×、risk_off 1.1×;OversoldBounce 恒 1.0×。 |

---

## C. 风控

| 中文 | 英文 | 含义 |
|---|---|---|
| 软止损 | soft stop | 历史平均亏损 × 1.5 的观察参考线。**不是自动卖出触发**,只用于风险参考。 |
| 硬止损 | hard stop | 固定 −8% 的风控参考线。**只做披露 / 人工执行参考**,paper P&L 不按止损出场。 |
| 时间退出 | time exit | 「T+N」——第 N 个交易日收盘无条件平仓,不恋战。 |
| 回撤 | drawdown | 组合净值从峰值的回撤幅度。输出形如「回撤: +0.0%」。 |
| 风控状态 | risk state | 由回撤驱动的状态标签(见下三行)。 |
| 正常 | normal | 回撤在 (−15%, 0],正常仓位。 |
| −15%降仓 | decrease | 回撤 ≤ −15%,所有新仓仓位减半(0.5×)。 |
| −20%清仓 | liquidate | 回撤 ≤ −20%,DRAWDOWN 熔断,不出新仓且平掉所有持仓。 |
| 期间触硬止损 | stop would have triggered | 持仓期间价格曾触及硬止损;journal 记录该事实,但 paper P&L 仍在 T+N 收盘结算。 |

> ⚠️ **重要**:当前止损是「披露用」的,不实际执行。改风控逻辑时注意 `paper_tracker.py` 的 `stop_would_have_triggered` 不进 P&L。

---

## D. 统计 / 分布

| 中文 | 英文 | 含义 |
|---|---|---|
| 先验分布 | prior distribution | 全池历史回测的分布,格式「n=… winrate=… cv=… E=…」,用于 Kelly 仓位。 |
| 真实回测 | actual backtest | 表头的实盘回测统计,与先验独立。 |
| n | sample size | 该分布基于的历史命中样本数(execution-adjusted)。 |
| 胜率 | win rate | 历史命中里正收益的比例。 |
| 凸性比 (cv) | convexity ratio | `(平均盈利 × 胜率) / (|平均亏损| × 亏损率)`。> 1.5 才算凸性 setup。 |
| E / E[r] | expected return | 历史命中平均收益 = `胜率 × 平均盈利 + 亏损率 × 平均亏损`。 |
| CI(置信区间) | confidence interval | E[r] 的 95% bootstrap 置信区间。「CI 跨 0 不显著」= 统计上无法证明赚钱。 |
| IC | information coefficient | setup 信号与全市场基线的 rank 相关性。> 0 说明有排序信息(BTST IC=0.126)。 |
| 少样本 | low-confidence | setup 的实盘回测 n 太小,标记「⚠少样本」提示勿过度信任。 |
| 强度 | trigger strength | 0-1 分,决定同 setup 内候选的排序。涨停突破 = 反转深度 40% + 涨停强度 30% + 主力流入 30%。 |

---

## E. 时间 / 周期

| 中文 | 英文 | 含义 |
|---|---|---|
| T+N | T+N (trading days) | 买入后第 N 个**交易日**。结算按第 N 个交易日收盘价。T+10 ≈ 14 日历日。 |
| 信号日 | signal date | setup 触发的交易日。表头「信号日: {date}」。 |
| 计划买入日 | planned buy date | 信号日的下一个交易日,开盘买入。 |
| 交易日 | trading day | 开市日,用于 T+N 计数和 P&L 结算。 |
| 日历日 | calendar day | 「剩 N 天」用的口径(T+10 ≈ 14 日历日)。 |
| 剩 N 天 | days to maturity | 持仓距到期的**日历日**数。 |
| 到期 / 到期释放 | maturity / release | 持仓到达 setup horizon,自动平仓并回填 P&L,权重释放回组合。 |
| horizon | horizon | setup 的自然持有周期(涨停突破 10,超跌反弹 5)。 |

> ⚠️ 单位口径:T+N 和 P&L 用**交易日**;「剩 N 天」用**日历日**。三种口径同行展示,别混。

---

## F. regime 市场状态

| 中文 | 英文 | 含义 |
|---|---|---|
| regime | regime | 市场状态标签,从 `regime_history.json` 按信号日读取。reasoning 里显示「regime={regime}×{factor}」。 |
| crisis | crisis | 危机环境。BTST 历史最强(胜率 76%,E +16.93%)→ 1.2× 加仓。 |
| risk_off | risk-off | 防御环境。BTST 1.1× 加仓(胜率 78%,E +8.87%)。 |
| normal | normal | 默认 / 未知环境。所有 setup 1.0×。 |
| 逆周期 | countercyclical | crisis/risk_off 时加仓以捕获均值回归 alpha 的仓位逻辑。 |

---

## G. P&L / 账户

| 中文 | 英文 | 含义 |
|---|---|---|
| 组合净值 (nav) | portfolio NAV | paper 组合的净值。 |
| 累计已实现 | cumulative realized P&L | 已平仓交易盈亏之和。0 笔 EXIT 时标注「(待到期结算)」,否则「(N 笔已平仓)」。 |
| 浮动盈亏 | unrealized P&L | 未到期持仓的浮盈浮亏。**当前不计入**净值 / 回撤 / 风控(系统无 mark-to-market)。 |
| paper trading | paper trading | Phase-A 模拟追踪。P&L 在 T+N 收盘回填,不按止损出场。 |
| 持仓数 | open positions | 当前持有的 ticker 数量。 |
| 平仓 / EXIT | close / exit | 到期或触发后关闭持仓,回填已实现 P&L。 |

---

## 环境变量速查

| 变量 | 默认 | 作用 |
|---|---|---|
| `DAILY_ACTION_DISABLED_SETUPS` | `oversold_bounce` | 暂停的 setup 集合。设 `none` 恢复全部。 |
| `DAILY_ACTION_REGIME_SIZING` | 开启 | 设 `false` 关闭 regime 加仓(全部退化为 1.0×)。 |
| `DAILY_ACTION_ENFORCE_OPEN_CAP` | `true` | 组合上限是否计入已开仓。设 `false` 恢复旧的 per-run 行为(逃生口)。 |

---

## 参考文件

| 模块 | 文件 |
|---|---|
| 命令分发 | `src/cli/dispatcher.py` |
| 凸性 setup 主逻辑 | `src/screening/offensive/daily_action.py`(`generate_daily_action` / `render_daily_action`) |
| Setup 定义 | `src/screening/offensive/setups/btst_breakout.py`、`oversold_bounce.py` |
| Kelly 仓位 | `src/screening/offensive/kelly.py` |
| Paper tracker | `src/screening/offensive/paper_tracker.py` |
| 先验分布 | `src/screening/offensive/known_distributions.py` |
| 风控框架 | `src/screening/offensive/risk_framework.py` |
