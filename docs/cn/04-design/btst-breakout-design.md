---
难度: ⭐⭐⭐⭐
类型: 专家设计
预计时间: 30 分钟
前置知识:
  - [设计原则](principles.md) ⭐⭐⭐⭐
  - [Kelly 仓位](kelly-position-sizing.md) ⭐⭐⭐
  - [风险框架](risk-framework.md) ⭐⭐⭐⭐
  - [纸面交易设计](paper-trading-design.md) ⭐⭐⭐
---

# BTST 涨停突破深度

BTST（Breakout To The Sky，涨停突破）是 `--daily-action` 当前唯一启用的 setup。代码在 `src/screening/offensive/setups/btst_breakout.py`，~400 行。本文档拆解到每个触发条件的常量、5 因子 ranker 的权重、板块质量评分的回测依据，以及 crisis 加仓的数据来源。

## setup 的第一性原理

`btst_breakout.py` docstring 给出设计依据：

> 交易的不是价格当前位置, 而是能量从积蓄到爆发的瞬时过程.

BTST 不是简单的"涨停就买"。它要捕捉的是「盘整区压缩 → 板块共振 → 主力流入 → 涨停突破」的完整能量释放过程。4 个触发条件对应这 4 个环节，缺一不可。

## 4 个触发条件

`detect` 方法按顺序检查 4 个条件，任一不满足返回 `_miss`：

### 条件 1：今日涨停（板块自适应阈值）

```python
from src.tools.ashare_board_utils import limit_up_pct_for_ticker

limit_up_pct = limit_up_pct_for_ticker(ticker)
try:
    pct_change = float(trigger_row.get("pct_change", 0.0))
except (TypeError, ValueError):
    pct_change = float("nan")
if math.isnan(pct_change) or pct_change < limit_up_pct:
    return self._miss(ticker, trade_date)
```

`limit_up_pct_for_ticker` 按板块返回阈值（`ashare_board_utils.py`）：

```python
_LIMIT_UP_PCT_MAIN = 9.5       # 主板 (60/00): 涨停 ≈ +10%, 下限 9.5%
_LIMIT_UP_PCT_STAR = 19.5      # 科创板 (688) / 创业板 (300/301): 涨停 ≈ +20%, 下限 19.5%
_LIMIT_UP_PCT_BJ = 29.0        # 北交所: 涨停 ±30%, 下限 29.0%

def limit_up_pct_for_ticker(ticker: Any) -> float:
    symbol = get_ashare_symbol(ticker)
    if _is_star_or_chinext_symbol(symbol):
        return _LIMIT_UP_PCT_STAR
    if symbol.startswith(("43", "83", "87")) or is_beijing_exchange_stock(symbol=symbol):
        return _LIMIT_UP_PCT_BJ
    return _LIMIT_UP_PCT_MAIN
```

旧固定 9.5% 会把科创/创业的非涨停大涨日（如 +13.9%）误判为涨停 → setup 语义被污染。2026-07-10 修复为板块自适应：主板 9.5%、科创/创业 19.5%、北交所 29.0%。`execution_adjuster.is_limit_up_unbuyable_next_day` 也同步修复。

NaN guard：`NaN or 0.0` 返回 NaN（NaN 是 truthy），`NaN < threshold` 永远 False。先 `float()` 再 `math.isnan()` 统一处理。

### 条件 2：主力净流入 > 20 日均值

```python
_MAIN_FLOW_LOOKBACK_DAYS = 20
_MAIN_FLOW_MIN_HISTORY_DAYS = 5  # 资金流历史 < 此值时无法判均值, degraded=True

records: list[FundFlowRecord] = context.get("fund_flow_records") or []
today_flow = next((r.main_net_inflow for r in records if r.date == trade_date), None)
if today_flow is None or math.isnan(today_flow):
    return self._miss(ticker, trade_date)
historical = [r.main_net_inflow for r in records if r.date < trade_date and not math.isnan(r.main_net_inflow)]
degraded = False
degradation_reason = ""
if len(historical) >= _MAIN_FLOW_MIN_HISTORY_DAYS:
    lookback = historical[-_MAIN_FLOW_LOOKBACK_DAYS:]
    hist_mean = sum(lookback) / len(lookback)
    if today_flow <= hist_mean:
        return self._miss(ticker, trade_date)
    if len(historical) < _MAIN_FLOW_LOOKBACK_DAYS:
        degraded = True
        degradation_reason = f"条件2 短窗口: 仅{len(historical)}天 (设计{_MAIN_FLOW_LOOKBACK_DAYS}d)"
else:
    degraded = True
    degradation_reason = f"条件2 跳过: 历史不足 ({len(historical)}<{_MAIN_FLOW_MIN_HISTORY_DAYS}日)"
```

设计逻辑：涨停日必然有正流入（多空博弈锁定），但条件 2 要求流入 > 20 日均值，过滤"今日流入虽正但低于近期均值"的弱势涨停。

**degraded 机制**（C234 NS-5 诚实披露）：资金流历史不足 5 天时，BTST 命中仍输出但标 `degraded=True`。`fund_flow_cache` 普遍浅（<5 天）时，绝大多数 BTST 命中是 degraded — 运行时检测口径比 `known_distributions` 的深历史回测更宽松（少了资金流均值过滤），必须向 operator 披露。

### 条件 3：所属行业当日涨幅 > 2%

```python
_INDUSTRY_PCT_MIN = 2.0

industry_pct: float | None = None
industry_pct_raw = context.get("industry_day_pct")
if industry_pct_raw is None:
    # 数据缺失: 不过滤但标记残缺
    if not degraded:
        degraded = True
        degradation_reason = "条件3 (行业涨幅≥2%) 跳过: 行业数据未加载"
else:
    try:
        industry_pct = float(industry_pct_raw)
    except (TypeError, ValueError):
        industry_pct = float("nan")
    if industry_pct != industry_pct or industry_pct < _INDUSTRY_PCT_MIN:
        return self._miss(ticker, trade_date)
```

板块效应：BTST 要的是「板块共振」的涨停，不是孤立涨停。`_INDUSTRY_PCT_MIN = 2.0` 要求所属行业当日涨幅 > 2%。

Bug fix（2026-07-12）：`industry_day_pct=None` 表示行业数据管道断裂（缓存缺失/import 失败）。旧实现把加载失败映射为 `industry_pct=0.0` → `0.0 < 2.0` → 全部 BTST miss。用户看到"今日无信号"，实际是数据管道断了。修正：None 时跳过行业过滤但标 degraded，与资金流浅数据降级同模式。

### 条件 4：涨停前 5 日累计涨幅 ≤ 8%（防追高）

```python
_PRE_RUNUP_LOOKBACK_DAYS = 5
_PRE_RUNUP_MAX_PCT = 8.0

ref_idx = trigger_idx - _PRE_RUNUP_LOOKBACK_DAYS
pre_trigger_idx = trigger_idx - 1
if ref_idx < 0 or pre_trigger_idx < 0:
    return self._miss(ticker, trade_date)
pre_close = float(prices.iloc[ref_idx]["close"])
pre_trigger_close = float(prices.iloc[pre_trigger_idx]["close"])
trigger_close = float(trigger_row["close"])
pre_runup_pct = (pre_trigger_close / pre_close - 1) * 100
if pre_runup_pct > _PRE_RUNUP_MAX_PCT:
    return self._miss(ticker, trade_date)
```

防追高：涨停前已经涨太多的票，涨停可能是末端加速而不是突破起点。`_PRE_RUNUP_MAX_PCT = 8.0` 是 2026-07 回测后从 10% 收紧的值。

**数据依据**（全池回测 2020-2026，8825 涨停样本，T+5 execution-adjusted）：

| 涨停前 5 日涨幅 | 样本 | E[r] | 胜率 | 凸性 |
| --- | --- | --- | --- | --- |
| ≤ 0% | 553 | +4.17% | 61% | — (超跌后首板，最强) |
| ≤ 5% | 1299 | +3.20% | 60% | 2.17 |
| ≤ 10% | 2651 | +2.59% | 56% | 1.90 (旧阈值) |
| 无过滤 | 8825 | +1.36% | 49% | 1.33 (不达凸性 1.5 门槛) |

单调递减：涨停前涨幅越大后续越弱。2026-07 回测后从 10% 收紧到 8%：8-10% 区间 52.4%/+3.10% 弱于池均值，<8% 58%+ 明显优于 >8% 53%。

## 5 因子 trigger_strength ranker

`detect` 末尾计算 `trigger_strength`，这是同 setup 内候选排序的真实依据：

```python
trade_dow = _dt.strptime(trade_date, "%Y%m%d").weekday()  # 0=Mon
weekday_score = 1.0 if trade_dow >= 2 else 0.0  # Wed-Fri=1, Mon-Tue=0
board_score = _board_quality_score(ticker)  # 002/300=1.0, 688/60x=0.95, 000=0.0

pre_window = prices.iloc[ref_idx : trigger_idx]  # 5 个交易日的 OHLCV
position_score, squeeze_score = _compute_trend_vol_scores(pre_window, prices, trigger_idx)

volume_score = _compute_volume_score(prices, trigger_idx)

energy_bonus = 0.08 if position_score >= 0.5 and squeeze_score >= 0.5 else 0.0
strength = min(1.0, 0.20 * weekday_score + 0.20 * board_score + 0.20 * position_score + 0.20 * squeeze_score + 0.20 * volume_score + energy_bonus)
```

5 因子等权 0.20 + 能量耦合 bonus 0.08：

1. **weekday（星期）**：Wed-Fri=1，Mon-Tue=0。回测：Wed-Fri 78% win vs Mon-Tue 51%（+27pp）。
2. **board（板块）**：见下文板块质量评分。
3. **position（区间位置）**：Donchian 分位 < 0.5 → 1.0（从低位拉起的新鲜突破=好）。
4. **squeeze（波动率压缩）**：近 3 日 ATR / 前 17 日 ATR < 0.8 → 1.0（弹簧压紧=爆发力强）。
5. **volume（成交量比率）**：见下文成交量因子。
6. **energy_bonus**：position + squeeze 同时=1 → +0.08（完整弹簧释放）。

### 板块质量评分

`_board_quality_score` 基于 626 只 A 股全 universe 回测（8% 涨停前涨幅门控 + 成交量过滤 + T+10，n=1212）：

```python
def _board_quality_score(ticker: str) -> float:
    """板块质量评分 (2026-07-12 用当前过滤器链重新校准).

    旧值基于 133 笔真实成交 (不同过滤器). 新值基于 626 只 A 股全 universe 回测
    (8% 涨停前涨幅门控 + 成交量过滤 + T+10, n=1212):
      688/60x:  WR=64.5% E[r]=+9.03%  → 0.95 (实际最优, 旧 0.7 低估)
      002/300:  WR=61.1% E[r]=+6.55%  → 1.0  (仍强, 保留)
      000/001:  WR=44.9% E[r]=+1.54%  → 0.0  (最差, 不变)
    """
    if ticker.startswith(("002", "300", "301")):
        return 1.0
    if ticker.startswith(("688", "60")):
        return 0.95  # 旧 0.7 低估: 实测 64.5% WR / +9.03% (全 universe 最优)
    return 0.0  # SZmain(000/001) 及其他
```

**校准历史**：688/60x 从 0.7 提升到 0.95，因为实测 64.5% WR / +9.03%（全 universe 最优），旧 0.7 低估。002/300 保持 1.0（61.1% WR / +6.55%，仍强）。000/001 保持 0.0（44.9% WR / +1.54%，最差）。

**为什么不是 1.0 给 688/60x**：688/60x 样本量比 002/300 小，给 0.95 留一点保守空间。如果后续样本累积证实 688/60x 稳定优于 002/300，再提到 1.0。

### 成交量因子

`_compute_volume_score` 基于 2409 涨停样本历史回测（2026-07，626 只）：

| 量比区间 | 胜率 | E[r] | 评分 |
| --- | --- | --- | --- |
| 1.0-1.2x | 61.4% | +6.05% | 1.0 (最佳) |
| 0.8-1.0x | 58.2% | +5.38% | 0.9 |
| 1.2-1.5x | 59.8% | +5.84% | 0.9 |
| 1.5-2.0x | 55.6% | +4.91% | 0.4 (噪讯区) |
| 0.5-0.8x | 49.7% | +2.82% | 0.0 (回避区) |
| <0.5 或 >5.0 | 样本不足 | — | 0.5 (中性) |

第一性原理（修正后）：A 股涨停本质是多空博弈锁定，缩量涨停 ≠ 弱势（可以是筹码锁定），放量涨停可能代表抛压大 / 筹码换手 → 后续回撤风险高。最优量 = 温和放量（刚好够 drive price up 但不过度换手）。

### squeeze 因子：波动率压缩

`_compute_squeeze_score` 计算「弹簧被压紧」：

```python
def _compute_squeeze_score(prices: pd.DataFrame, trigger_idx: int) -> float:
    lookback_end = trigger_idx  # 不含涨停日本身
    lookback_start = max(0, lookback_end - 20)
    # ...
    recent = daily_ranges[-3:] if len(daily_ranges) >= 3 else daily_ranges[-1:]
    prior = daily_ranges[:-3] if len(daily_ranges) > 3 else daily_ranges
    recent_atr = sum(recent) / len(recent)
    prior_atr = sum(prior) / len(prior)
    if prior_atr <= 0:
        return 0.5
    squeeze_ratio = recent_atr / prior_atr
    return 1.0 if squeeze_ratio < _SQUEEZE_RATIO_THRESHOLD else 0.0
```

`_SQUEEZE_RATIO_THRESHOLD = 0.8`：近 3 日 ATR / 前 17 日 ATR < 0.8 = 压缩（能量积蓄）。数据不足（<20 日）时回退到旧的绝对低波动逻辑（`_compute_absolute_low_vol_score`，ATR < 3%）。

## trigger_strength 阈值敏感性回测

`daily_action.py::_MIN_TRIGGER_STRENGTH = 0.50` 的回测依据（2026-07-12，626 只 A 股，1308 信号）：

| 阈值 | n | WR | E[r] | Sharpe |
| --- | --- | --- | --- | --- |
| ≥0.35 | 1114 | 61.0% | +7.16% | 0.365 (旧值) |
| ≥0.50 | 777 | 62.8% | +7.54% | 0.383 ← 取此 |
| ≥0.55 | 634 | 64.0% | +7.33% | 0.391 (Sharpe 最优但样本少) |
| ≥0.70 | 330 | 65.5% | +7.78% | 0.397 (WR 最高但仅 25% 样本) |

**为什么取 0.50 而不是 Sharpe 最优的 0.55**：`0.50` 在 WR（+1.8pp）、收益（+0.38pp）、Sharpe 上均优于 `0.35`，且保留 70% 样本（777/1114）。`0.55` 虽然 Sharpe 最优，但样本量降到 634（57%），统计显著性下降。`0.70` WR 最高但仅 25% 样本，噪声风险大。

NaN guard：`setup` 契约返回 float，但除零/log(0) 等可能产生 NaN。Python 中 `NaN < threshold` 永远为 False，必须用 `math.isnan` 显式拦截：

```python
ts = action.trigger_strength
if math.isnan(ts) or ts < _MIN_TRIGGER_STRENGTH:
    action.block_reason = f"强度 {ts:.2f} < {_MIN_TRIGGER_STRENGTH:.2f} 阈值" if not math.isnan(ts) else f"强度 NaN (setup 计算异常), 阈值 {_MIN_TRIGGER_STRENGTH:.2f}"
    blocked_candidates.append(action)
    continue
```

## crisis 加仓数据依据

`_REGIME_SIZE_FACTORS_BY_SETUP` 基于 192 笔真实成交（`data/paper_trading_backtest/journal.jsonl`）：

```python
_REGIME_SIZE_FACTORS_BY_SETUP = {
    "btst_breakout": {"crisis": 1.2, "risk_off": 1.1, "normal": 1.0},
    "oversold_bounce": {"crisis": 1.0, "risk_off": 1.0, "normal": 1.0},
}
```

BTST 三个 regime 的回测数据：

| regime | WR | E[r] | 加仓系数 |
| --- | --- | --- | --- |
| crisis | 76% | +16.93% | 1.2× |
| risk_off | 78% | +8.87% | 1.1× |
| normal | 66% | +6.29% | 1.0× |

**为什么 crisis 加仓**：crisis regime 下 BTST 的 WR（76%）和 E[r]（+16.93%）都是三个 regime 里最高。crisis 期市场恐慌，资金集中流入真正强势的票 → BTST 信号在 crisis 期更强。

**为什么 OversoldBounce 不加仓**：三个 regime 都不显著（crisis 48%/-1.15%、normal 51%/+0.15%），整体 E[r]≈0 → 无 alpha 可放大。

⚠️ **样本期偏差**：2026 上半年是牛市，crisis regime 的样本量也小。`risk_off n=3` 反而 +13.11% 与 crisis n=21 的 -1.15% 矛盾 → 分层在当前样本量下不可靠。`DAILY_ACTION_REGIME_SIZING=false` 是逃生口，可在熊市/高波动期全局关闭 regime 加权。

⚠️ **regime 加仓当前暂停**：v2 ledger 单票硬上限 10%，12% regime 例外暂停。`_REGIME_POSITION_CAP_MULTIPLE = 1.2` 在代码里仍计算，但被 ledger 层 cap 到 10%。这是审计口径的安全降级 — canonical regime evidence 可由 repository 重验后恢复。

## 失效条件与止损

```python
range_lookback = max(0, trigger_idx - 20)
range_low = float(prices.iloc[range_lookback:trigger_idx]["low"].min())
range_based_stop_pct = (range_low / trigger_close - 1)  # 负数, 如 -0.05 = -5%
if range_based_stop_pct < -0.08:
    range_based_stop_pct = -0.08
stop_price = trigger_close * (1 + range_based_stop_pct)
invalidation = f"价格跌破 {stop_price:.2f} (盘整区底部 {range_low:.2f}, {range_based_stop_pct:+.1%})"
```

止损锚定盘整区底部（`range_low`），不是固定 -8%。压缩越紧 → `range_low` 越接近 `trigger_close` → 止损越窄 → 盈亏比天然更大。安全下限 -8%：如果盘整区底部太远，用 -8% 兜底。

⚠️ **止损当前是摆设**：`stop_would_have_triggered` 只进 reasoning 字符串，不影响 realized P&L。详见 [风险框架](risk-framework.md) 的「BTST 止损为何默认不执行」章节 — 81 笔回测显示所有止损策略在当前牛市样本都会降低 E[r] 和 Sharpe。

## known_distributions：先验分布

`known_distributions.py` 给出 BTST 在 T+8 和 T+10 两个 horizon 的先验分布：

```python
BTST_BREAKOUT_T10 = Distribution(
    n=1458,
    winrate=0.5878,
    avg_gain=0.1848,  # +18.48%
    avg_loss=-0.1041,  # -10.41%
    convexity_ratio=2.53,
    expected_return=0.0657,  # +6.57%
    ci_low=0.0530,
    ci_high=0.0784,
    ic=0.15,
)
```

⚠️ **硬编码常量**：`n=1458` 等数字来自 2026-07-12 用当前过滤器链（8% 涨停前涨幅门控 + 成交量过滤）重校准。无自动刷新，引用前需与 `paper_trading_backtest` 真实数据交叉验证。

`paper_trading_backtest` 实测更优（牛市样本）：`win=68.4%, E=+8.15%, n=133`。这暗示 `known_distributions` 的先验可能偏保守 — 但样本期偏差（2026 牛市）让真实成交数字也可能偏乐观。两个数据源各有偏差，互为参考。

## 与 `--auto` 的双信号收敛

`daily_action.py::_load_auto_topn_tickers` 读 `--auto` 报告的 Top-N，标记同日也在 `--auto` Top-N 的 BTST 命中为「⭐双信号」：

```python
# C-DUAL-SIGNAL-CONVERGENCE (20260710): empirical dogfood 发现 BTST 命中里,
# 同日也在 ``--auto`` Top-N 的子集历史胜率更高 (76% vs 66%, n=34 vs 99,
# median +7.35% vs +5.67%; ⚠ n 小未达统计显著, 仅供 operator 参考).
```

但 bootstrap 验证显示这个收敛子集 95% CI 跨 0（`[-6.8%, +27.5%]`，P(无优势)=11.7%）→ 未达统计显著。诚实披露：标记事实（同日在两系统），但不宣称"已验证更优"，防止 operator 据噪声点估计加仓。待样本累积（n>100 收敛子集）后重测。

## 总结：BTST 的设计权衡

BTST 的核心设计是「不追高 + 板块共振 + 主力流入 + 能量释放」四重过滤。每重过滤都有回测依据，但每重也都牺牲了样本量：

- 条件 1（涨停）：从全市场缩到涨停日（~8825 样本/6 年）。
- 条件 2（主力流入 > 20 日均值）：缩到 ~2651（≤10% 涨停前涨幅）。
- 条件 3（行业涨幅 > 2%）：再缩 ~30%（板块共振过滤）。
- 条件 4（涨停前 5 日 ≤ 8%）：再缩 ~50%（防追高）。

最终触发样本量 ~1300，足以统计但不足以做 regime 分层（crisis n=21 太小）。这是 setup 设计的内在张力：过滤越严，信号越纯，但样本量越小，分层越不可靠。

`_MIN_TRIGGER_STRENGTH = 0.50` 是这个张力的平衡点：保留 70% 样本（777/1114），WR/收益/Sharpe 都优于旧值 0.35。如果未来样本累积到 n>5000，可以考虑提到 0.55 或 0.70 进一步收紧。
