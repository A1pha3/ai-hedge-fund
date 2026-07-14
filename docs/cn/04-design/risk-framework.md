---
难度: ⭐⭐⭐⭐
类型: 专家设计
预计时间: 16 分钟
前置知识:
  - [设计原则与权衡](principles.md) ⭐⭐⭐⭐
  - [Kelly 仓位](kelly-position-sizing.md) ⭐⭐⭐
---

# 风险框架

风险框架在 `src/screening/offensive/risk_framework.py` 和 `paper_tracker.py`，覆盖三层：单票止损 + 时间退出 + 组合 drawdown 熔断。本文档讲清楚每层的实现、关键阈值，以及「止损为何默认不执行」这条反直觉决策的数据依据。

## 三层风险计划

`build_risk_plan` 输出单票的 `RiskPlan`：

```python
@dataclass(frozen=True)
class RiskPlan:
    invalidation_condition: str  # setup 触发反转的描述性条件
    stop_loss_pct: float  # 软止损 (基于 setup 历史最大亏损)
    hard_stop_pct: float  # 硬止损 (绝对值, 默认 -8%)
    time_exit: str  # 时间退出 ("T+N")
    natural_horizon: int  # setup 自然 horizon
    stop_policy: str = "disclose_only"  # "disclose_only" / "execute"
```

- **软止损**：`avg_loss × 1.2`，clamp 到 `hard_stop × 0.8`。Bug fix 注释说明旧公式 `avg_loss × 1.5` 对 BTST 产生 -13.8% soft_stop，比 hard_stop -8% 更宽 → 不可达。修复后 `soft_stop = max(avg_loss × 1.2, hard_stop × 0.8)`，保证 soft < hard。
- **硬止损**：默认 -8%，但 BTST setup 会传入 `range_based_stop_pct`（基于 20 日最低价的盘整区底部）覆盖。
- **时间退出**：`T+<natural_horizon>`，BTST=10、OversoldBounce=5。
- **stop_policy**：`disclose_only`（只披露不执行）或 `execute`（真按止损平仓）。

## per-setup 止损策略

`_DEFAULT_STOP_POLICY` 按 setup 区分：

```python
_DEFAULT_STOP_POLICY: dict[str, str] = {
    "btst_breakout": "disclose_only",
    "oversold_bounce": "execute",
}
```

注释给出理由：

> BTST: disclose_only — 回测验证 (2026-07-10, 91 笔): no_stop E=+5.55%/Sharpe 0.37
>   优于所有止损变体. 均值回归 setup 的波动反而赚钱.
> OversoldBounce: execute fixed8 — 无 alpha (E=+0.34%), 尾部亏损 20% (>-10%).
>   执行止损截断尾部, 避免单笔大亏侵蚀组合.

**为什么 BTST 止损只披露不执行**：BTST 是均值回归 setup，涨停后的回调是正常的"洗盘"，止损会被洗出去再错过反弹。回测显示 no_stop 的 E[r] 和 Sharpe 都优于任何止损变体。

**为什么 OversoldBounce 止损执行**：OB 无 alpha，尾部亏损厚（亏损 >10% 占比 20%），执行 -8% 止损截断尾部，避免单笔大亏侵蚀组合。

## BTST 止损为何默认不执行：数据依据

`paper_tracker.py::_execution_stop_mode` 的 docstring 给出 81 笔 BTST 回测结论：

```python
def _execution_stop_mode() -> str:
    """解析 DAILY_ACTION_EXECUTION_STOP → 止损执行模式.

    回测验证 (2026-07-10, 81 笔 BTST) 显示: 在当前牛市样本上, 所有止损策略
    (固定/ATR/封顶) 都会**降低** E[r] 和 Sharpe — 均值回归 setup 的波动反而赚钱.
    故默认 ``none`` (止损只做披露 stop_would_have_triggered, 不影响 P&L, 与历史口径一致).
    """
```

回测对象：81 笔 BTST 交易，2026 上半年牛市样本。

回测结果：

| 策略 | E[r] | Sharpe |
| --- | --- | --- |
| no_stop | +5.55% | 0.37 |
| fixed8 | 低于 no_stop | 低于 no_stop |
| atr_k2 | 低于 no_stop | 低于 no_stop |
| atr_k3 | 低于 no_stop | 低于 no_stop |

**测的是什么**：在 2026 上半年牛市样本上，对同一批 BTST 信号分别按 no_stop / 固定 -8% / ATR×2 / ATR×3 出场，比较 E[r] 和 Sharpe。

**反映哪部分系统**：反映 BTST setup 在牛市样本下的「止损会过早出场错过反弹」特性。均值回归 setup 的波动反而赚钱 — 涨停后的回调是洗盘，止损出场会错过 T+5/T+10 的反弹。

**不能推出什么**：

1. 不能推出熊市/震荡市下止损仍然有害。熊市样本下止损可能截断尾部亏损，反而优于 no_stop。
2. 不能推出 OversoldBounce 也不该止损。OB 的尾部亏损比 BTST 厚（亏损 >10% 占比 20% vs 11%），OB 的 `stop_policy=execute` 是基于不同数据。
3. 不能推出"止损无用"。止损在 OB 上仍然执行，只是 BTST 在牛市样本上不执行。

## 真实止损启用方式

`DAILY_ACTION_EXECUTION_STOP` env 控制：

```python
raw = os.environ.get("DAILY_ACTION_EXECUTION_STOP", "").strip().lower()
if raw in {"atr_k2", "atr_k3", "fixed8"}:
    return raw
return "none"  # 默认: 止损只披露 (回测验证的当前最优口径)
```

启用方式：

```bash
# ATR 2.0x 止损真正影响 P&L
DAILY_ACTION_EXECUTION_STOP=atr_k2 uv run python src/main.py --daily-action

# ATR 3.0x (更宽, 少误杀)
DAILY_ACTION_EXECUTION_STOP=atr_k3 uv run python src/main.py --daily-action

# 固定 -8% 止损真正影响 P&L
DAILY_ACTION_EXECUTION_STOP=fixed8 uv run python src/main.py --daily-action
```

⚠️ 启用前必须跑 `scripts/backtest_exit_strategies.py` 确认当前行情下止损有利。启用止损会改变 paper P&L 口径，使其与 `known_distributions` 的 T+N 收盘分布不可比。

## ATR 止损计算

`atr_utils.py::compute_atr` 实现 Wilder RMA（首个周期算术均值 seed，之后递推）：

```python
def compute_atr(prices: pd.DataFrame, period: int = 14, at_idx: int | None = None) -> float | None:
    # True Range = max(high - low, |high - prev_close|, |low - prev_close|)
    # 首个 ATR = 前 period 个 TR 的算术均值；之后
    # ATR[t] = (ATR[t-1] * (period-1) + TR[t]) / period
```

`atr_stop_price(entry_price, atr, k=2.0) = entry_price - k × ATR`。

`at_idx` 参数用于回测时避免未来函数：只用 entry 前的数据算 ATR。`_stop_adjusted_return` 在 `paper_tracker.py` 里调用：

```python
if mode in ("atr_k2", "atr_k3"):
    k = 2.0 if mode == "atr_k2" else 3.0
    atr = compute_atr(df, period=20, at_idx=entry_idx)
    stop_price = atr_stop_price(entry_price, atr, k=k)
```

`period=20` 而非默认 14，因为 BTST 持仓 T+10，用更长窗口平滑 ATR。

## drawdown 熔断

`risk_framework.py` 定义两个阈值：

```python
DRAWDOWN_DECREASE_THRESHOLD = -0.15  # -15% 降仓
DRAWDOWN_LIQUIDATE_THRESHOLD = -0.20  # -20% 清仓

def drawdown_action(current_drawdown_pct: float) -> str:
    if current_drawdown_pct <= DRAWDOWN_LIQUIDATE_THRESHOLD:
        return "liquidate"
    if current_drawdown_pct <= DRAWDOWN_DECREASE_THRESHOLD:
        return "decrease"
    return "normal"
```

`paper_tracker.py::drawdown_action` 同口径。`generate_daily_action` 在每次运行开头调用 `tracker.drawdown_action()`：

- `normal`：正常下单。
- `decrease`：`drawdown_factor = 0.5`，仓位减半。
- `liquidate`：不出新仓，平掉所有持仓。

`update_pnl` 用加法累加 nav（非复利），因为每笔仓位的本金是组合的 `kelly_pct` 部分，收益是绝对值不是复利。注释说明旧实现用 `nav *= 1 + pnl` 导致 192 笔 × ~0.8% → nav 2.77（复利膨胀），实际应该 ~1.9。

## range_based_stop：BTST 的物理结构止损

`btst_breakout.py::detect` 计算基于盘整区底部的止损：

```python
# 止损: 基于盘整区底部 (物理结构自适应).
# 压缩越紧 → range_low 越接近 trigger_close → 止损越窄 → 盈亏比天然更大.
range_lookback = max(0, trigger_idx - 20)
range_low = float(prices.iloc[range_lookback:trigger_idx]["low"].min())
range_based_stop_pct = (range_low / trigger_close - 1)  # 负数, 如 -0.05 = -5%
# 安全下限: 止损不超过 -8% (如果盘整区底部太远, 用 -8% 兜底)
if range_based_stop_pct < -0.08:
    range_based_stop_pct = -0.08
```

设计逻辑：BTST 的涨停来自盘整区突破，止损应锚定盘整区底部（`range_low`）。压缩越紧 → `range_low` 越接近 `trigger_close` → 止损越窄 → 盈亏比天然更大。如果盘整区底部太远（`range_based_stop_pct < -0.08`），用 -8% 兜底，避免止损过宽。

`daily_action.py` 把这个 `range_based_stop_pct` 传给 `build_risk_plan` 作为 `hard_stop_override`，覆盖默认 -8%。

## 时间退出与到期判断

`_is_matured` 用交易日而非日历日判断到期：

```python
@staticmethod
def _is_matured(buy_date: str, horizon: int, as_of: str) -> bool:
    buy_dt = datetime.strptime(str(buy_date), "%Y%m%d").date()
    as_of_dt = datetime.strptime(str(as_of), "%Y%m%d").date()
    cal_days = _trading_horizon_to_calendar_days(horizon)
    return (buy_dt + timedelta(days=cal_days)) <= as_of_dt
```

`_trading_horizon_to_calendar_days` 把 T+N 交易日换算为保守日历日下限：

```python
def _trading_horizon_to_calendar_days(horizon: int) -> int:
    n = max(0, int(horizon))
    return n + 2 * (n // 5)
```

- `horizon=5 → 7 日历日`
- `horizon=10 → 14 日历日`

Bug fix 注释说明旧实现 `timedelta(days=horizon)` 把 N 个交易日当 N 个日历日，比真实 T+N 交易日早 4-12 天 → 过早触发 close_matured 但 day_N 收盘价未成熟 → 静默跳过 + 显示"今日到期"空窗 4-12 天。

## 已知陷阱

1. **`stop_would_have_triggered` 只披露**：默认 `DAILY_ACTION_EXECUTION_STOP=none` 时，止损触发只进 `reasoning` 字段，不影响 realized P&L。192 笔回测 0 笔止损触发（2026 牛市）。
2. **`open_exposure` 口径**：`_enforce_open_cap` 默认 true，T+10 跨日持仓计入 60% 上限。此前 per-run 从 0 起算导致真实敞口峰值 260%（26 仓），61 天超 60% 上限。
3. **样本期偏差**：所有止损回测都基于 2026 上半年牛市。BTST 的"no_stop 最优"结论在熊市/震荡市下可能反转。`scripts/backtest_exit_strategies.py` 是为切换行情时重测预留的工具。
4. **`_check_stop_hit` 窗口排除 T+0**：信号日 T+0 当天用户尚未买入（T+1 开盘才买），T+0 盘中 low 与止损无关。Bug fix 把 `>= buy_dt` 改为 `> buy_dt`，避免涨停日盘中波动误报止损触发。

## 深入阅读

- [Kelly 仓位设计](kelly-position-sizing.md):仓位上限如何与止损配合
- [BTST 涨停突破设计](btst-breakout-design.md):BTST 的 range_based_stop 物理结构止损
- [纸面交易设计](paper-trading-design.md):T+N close 口径与 P&L 回填机制
