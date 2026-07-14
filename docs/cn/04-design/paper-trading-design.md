---
难度: ⭐⭐⭐
类型: 进阶分析
预计时间: 14 分钟
前置知识:
  - [设计原则](principles.md) ⭐⭐⭐⭐
  - [风险框架](risk-framework.md) ⭐⭐⭐⭐
---

# 纸面交易设计

纸面交易（paper trading）是 `--daily-action` 的执行追踪层。代码在 `src/screening/offensive/paper_tracker.py`，记录每笔 action、计算滚动 P&L、输出 drawdown 状态供风控调整仓位。本文档讲清楚 journal 结构、portfolio_state 字段、T+N close 口径，以及 `paper_trading` vs `paper_trading_backtest` 的路径陷阱。

## 路径陷阱（最优先）

`AGENTS.md` 强调：

> **`data/paper_trading/` vs `data/paper_trading_backtest/`**：前者是运行时（0 EXIT），后者是回测（192 EXIT）。查成交数据用后者。

代码里 `_DEFAULT_JOURNAL_DIR = Path("data/paper_trading/")` 是运行时实例，每次 `--daily-action` 跑都会写入。但回测数据在 `data/paper_trading_backtest/`：

- `journal.jsonl`：403 条记录，211 BUY + 192 EXIT，覆盖 2026-01-15 → 2026-07-06。
- `portfolio_state.json`：`nav=2.10`，`realized_pnl=+110%`（2026 上半年回测）。

为什么有两个目录：运行时实例每次跑会覆盖状态，回测需要冻结快照供后续分析。`_load_backtest_setup_performance` 在 `daily_action.py` 里读 `data/paper_trading_backtest/journal.jsonl` 拿真实回测 stats 给 operator 披露：

```python
def _load_backtest_setup_performance() -> Any | None:
    """Load local paper-backtest setup performance for operator disclosure."""
    try:
        from src.screening.offensive.setup_performance import summarize_setup_performance
        # ...
        return summarize_setup_performance(
            Path("data/paper_trading_backtest/journal.jsonl"),
            regimes_by_date=regimes_by_date,
        )
```

⚠️ 查"系统真实表现"必须读 `paper_trading_backtest/`。读 `paper_trading/` 会看到 0 笔 EXIT，误判系统"0 笔成交"。

## journal.jsonl 结构

每行一个 JSON，字段在 `record_action` 里定义：

```python
def record_action(self, action: TradeAction):
    with open(self._journal_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "date": action.date,
            "ticker": action.ticker,
            "setup": action.setup,
            "horizon": action.horizon,
            "action": action.action,  # "BUY" | "HOLD" | "EXIT" | "SKIP"
            "kelly_pct": action.kelly_pct,
            "entry_price": action.entry_price,
            "soft_stop": action.soft_stop,
            "hard_stop": action.hard_stop,
            "time_exit": action.time_exit,
            "invalidation_condition": action.invalidation_condition,
            "reasoning": action.reasoning,
            "trigger_strength": action.trigger_strength,
            "degraded": action.degraded,
        }, ensure_ascii=False) + "\n")
```

`action` 字段四值：

- `BUY`：买入（T+0 信号日记录，T+1 开盘执行）。
- `HOLD`：持仓（不写入，靠 EXIT 推断）。
- `EXIT`：平仓（T+N 到期或止损触发）。
- `SKIP`：未触发 setup 或被风控过滤（仅 report 模式写入）。

`trigger_strength` 是闭环学习环的关键：记录 ranker 评分供回测验证（详见 [BTST 深度](btst-breakout-design.md)）。

## portfolio_state.json 字段

`PortfolioState` dataclass 定义状态：

```python
@dataclass
class PortfolioState:
    nav: float = 1.0  # 净值 (初始 1.0)
    peak: float = 1.0  # 历史净值最高点
    drawdown_pct: float = 0.0  # 当前回撤 (负数)
    open_positions: int = 0  # 当前持仓数
    open_exposure: float = 0.0  # 已开仓位 kelly_pct 之和 (组合敞口%)
    total_trades: int = 0
    realized_pnl_pct: float = 0.0  # 累计已实现收益%
    last_30d_pnl: list[float] = field(default_factory=list)
```

`open_exposure` 是 C-PORTFOLIO-CAP（20260710）修复加的字段。注释说明：

> 供 generate_daily_action 的 60% 组合上限判断 — 此前只数 open_positions (计数),
> 不追踪敞口% → 上限每次 run 从 0 起算, 忽略 T+10 跨日持仓 → 真实敞口峰值 260%

`_reconcile_open_positions` 在 `PaperTracker.__init__` 里从 journal 真值重算 `open_positions` 和 `open_exposure`：

```python
open_positions = 去重后 BUY 数 - EXIT 数
open_exposure  = sum(去重未平仓 BUY.kelly_pct)
```

这是为了自愈历史重复 BUY（旧版 record_buy 无跨进程幂等保护）导致 state 虚高。

## T+N close 口径

`close_matured` 是闭环核心：每次 `--daily-action` 运行开头平掉到期仓位，回填 realized P&L，驱动 drawdown 熔断。docstring 说明 P&L 口径：

> P&L 口径: T+10 收盘价 (close[D+horizon]/entry_price - 1), 与 BTST 先验分布
> (E=+2.57%) 和 north-star next_Nday_return 同口径, 保证 paper-pnl 可与先验
> 对比监测 edge 衰减.

实际计算优先级（`paper_tracker.py` line 555-568）：

1. **`_execution_adjusted_return`**：T+1 开盘 × (1+滑点) 入场，T+N 收盘 × (1-滑点) 出场。与 `ExecutionConfig` 默认滑点一致。
2. **`_close_to_close_return`**：T+0 收盘 → T+N 收盘（fallback，缺 open 列时）。
3. **`fetch_actual_returns` 的 `ret_pct`**：批量取 T+N 收益（last resort，以批次最早 buy_date 为锚 → 非 earliest 仓位 P&L 错误）。

Bug fix（2026-07-12）：`_execution_adjusted_return` 优先级最高，`price_loader` 出 result 时正常平仓；只有两个数据源都无结果时才跳过。旧代码 `ret_pct=None` 时直接 `continue`，跳过 price_loader 已算出的 execution_result → T+8 仓位永远无法平仓（`DEFAULT_HORIZONS=(1,3,5,10,15,20,25,30)` 不含 8）。

## 止损披露但不执行

`close_matured` 的止损检测：

```python
# 止损触发检测: 期间 low <= hard_stop (披露用, 不影响主 P&L 口径)
stop_would_have_triggered = False
execution_result: tuple[float, float] | None = None
stop_executed = False
if price_loader is not None:
    try:
        prices_df = price_loader(ticker, as_of)
        if hard_stop > 0:
            stop_would_have_triggered = self._check_stop_hit(prices_df, buy_date, horizon, hard_stop)
        execution_result = self._execution_adjusted_return(prices_df, buy_date, horizon)
        # 止损执行策略 (per-setup):
        stop_mode = _execution_stop_mode()
        if stop_mode == "none":
            setup_name = str(rec.get("setup", ""))
            if setup_name == "oversold_bounce":
                stop_mode = "fixed8"  # OB 默认执行 -8% 止损
        if stop_mode != "none" and execution_result is not None:
            stop_ret = self._stop_adjusted_return(prices_df, buy_date, horizon, stop_mode)
            if stop_ret is not None:
                execution_result = stop_ret  # 覆盖为止损价平仓
                stop_executed = True
```

- `stop_would_have_triggered`：期间 low <= hard_stop 时为 True（披露用）。
- `stop_executed`：`DAILY_ACTION_EXECUTION_STOP != "none"` 时真按止损价平仓，覆盖 T+N 收盘口径。

`render_daily_action` 把 `stop_would_have_triggered=True` 的仓位标 `⚠ 期间触硬止损`，让 operator 知道止损规则触发过，但 paper P&L 仍按 T+N 收盘回填（默认 `none` 模式）。

## 192 笔回测方法论

`data/paper_trading_backtest/journal.jsonl` 是回测实例，2026-01-15 → 2026-07-06，403 条记录（211 BUY + 192 EXIT）。关键统计：

```
BTST (n=133):           winrate=68%  E[r]=+8.15%   crisis=+16.93%/76%  risk_off=+8.87%/78%  normal=+6.29%/66%
OversoldBounce (n=59):  winrate=53%  E[r]=+0.34%   crisis=-1.15%/48%   normal=+0.15%/51%   risk_off=+13.11%/100%(n=3)
```

**测的是什么**：192 笔真实成交的 BUY → EXIT 配对，按 setup 和 regime 分层统计 WR、E[r]。

**反映哪部分系统**：反映 BTST 和 OversoldBounce 两个 setup 在 2026 上半年牛市样本下的真实表现，含 `close_matured` 的 T+N close 口径和执行滑点。

**不能推出什么**：

1. 不能推出熊市/震荡市下的表现。2026 上半年是牛市，crisis regime 的样本量也小。
2. 不能推出"OversoldBounce 在 crisis regime 亏钱"是稳定结论。`crisis n=21` 太小，`risk_off n=3` 反而 +13.11%，分层内部矛盾。
3. 不能推出 Phase 0 报告（`n=1762`）的数字可复现 — `setup_research.py` 直接跑会 n=0（`price_cache` 只有 6 个月深度），`phase0_report` 的数字在别处（更深历史）生成。

## 幂等与去重

`record_buy` 用 `(trade_date, ticker)` 作 natural-key 幂等：

```python
def record_buy(self, trade_date: str, ticker: str, ...):
    key = (str(trade_date), str(ticker))
    if key in self._existing_buy_keys():
        logger.debug("record_buy: %s 已存在, 跳过 (幂等)", key)
        return
```

`close_matured` 同样用 `(date, ticker)` 去重 EXIT：已有 EXIT 记录的仓位不重复平仓。`_reconcile_open_positions` 在初始化时从 journal 真值重算 open_positions，自愈历史重复 BUY。

## 闭环已自动

`render_daily_action` 末尾有一行：

```python
lines.append(f"\n  {Fore.WHITE}已写入 paper journal (按各 setup horizon 到期自动平仓 + 回填 realized P&L){Style.RESET_ALL}")
```

注释说明：

> 闭环已自动: close_matured 在 generate_daily_action 开头平到期仓并回填 P&L.
> 此前写 "30 天后用 --paper-pnl 复盘" 是死承诺 (该命令从未实现).

`close_matured` 在 `generate_daily_action` 第 866 行调用（步骤 2），在扫描新信号前先平到期仓。这是闭环核心：drawdown 熔断基于最新 nav，如果不先平仓回填 P&L，nav 永远是 1.0，熔断永远不触发。

## 已知陷阱

1. **`paper_trading` 不是 `paper_trading_backtest`**：运行时实例 0 EXIT，回测实例 192 EXIT。查成交数据必须读后者。
2. **`realized_pnl_pct` 口径**：是组合层面的累计贡献（`sum of realized × kelly`），不是单笔收益率。`update_pnl` 用加法累加 nav（非复利）。
3. **`last_30d_pnl` 滑动窗口**：只保留最近 30 天的 P&L 列表，用于短期波动监测。不是 30 天累计收益。
4. **`trigger_strength` 闭环学习**：每笔 BUY 记录 ranker 评分，回测时可按 strength 分桶验证 ranker 有效性。`_MIN_TRIGGER_STRENGTH = 0.50` 的阈值回测就是用这个字段做的（详见 [BTST 深度](btst-breakout-design.md)）。
5. **`matures_on` 用交易日保守下限**：`_trading_horizon_to_calendar_days` 把 T+N 交易日换算为 `N + 2*floor(N/5)` 日历日，不是纯日历日。旧实现 `timedelta(days=N)` 比 T+N 交易日早 4-12 天，导致"今日到期"但 day_N 数据未成熟。
