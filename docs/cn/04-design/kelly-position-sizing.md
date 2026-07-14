---
难度: ⭐⭐⭐
类型: 进阶分析
预计时间: 14 分钟
前置知识:
  - [设计原则与权衡](principles.md) ⭐⭐⭐⭐
  - [风险框架](risk-framework.md) ⭐⭐⭐⭐
---

# Kelly 仓位

仓位计算在 `src/screening/offensive/kelly.py`，~80 行代码，核心是一个离散二元结果的 half-Kelly 公式。本文档讲清楚公式推导、per-setup 上限的设计依据、regime 加权系数的回测来源，以及"为什么 BTST 实际仓位永远触顶"这个反直觉事实。

## 公式：离散二元结果的 half-Kelly

`kelly.py::kelly_fraction` 实现的是离散二元结果（盈利或亏损）的 Kelly 公式：

```python
def kelly_fraction(winrate: float, avg_gain: float, avg_loss: float) -> float:
    if avg_gain <= 0 or avg_loss >= 0 or winrate <= 0 or winrate >= 1:
        return 0.0
    b = abs(avg_loss)
    g = avg_gain
    return winrate / b - (1 - winrate) / g
```

公式：`kelly_fraction = winrate / |avg_loss| - (1 - winrate) / avg_gain`

- `winrate`：胜率 [0, 1]
- `avg_gain`：单次盈利幅度（正数，如 0.20 = +20%）
- `avg_loss`：单次亏损幅度（负数，如 -0.08 = -8%）

这是 Kelly criterion 在「结果只有盈/亏两种」假设下的简化形式。A 股 BTST 持仓 T+10 的收益分布近似二元（要么涨停突破成功吃到 +15% 左右，要么失败回撤 -10% 左右），用这个简化形式误差可接受。

`compute_kelly_size` 把 `kelly_fraction` 折半（`_KELLY_FRACTION = 0.5`）得到 half-Kelly，再乘以相关性折价和市场温度因子，最后 cap 到 `max_pct`：

```python
def compute_kelly_size(
    dist: Distribution,
    correlation_discount: float = 1.0,
    market_temperature_factor: float = 1.0,
    max_pct: float = _DEFAULT_MAX_PCT,
) -> KellySize:
    kelly_raw = kelly_fraction(dist.winrate, dist.avg_gain, dist.avg_loss)
    kelly_half = _KELLY_FRACTION * kelly_raw
    adjusted = kelly_half * correlation_discount * market_temperature_factor
    if adjusted < 0:
        return KellySize(kelly_raw=kelly_raw, kelly_half=kelly_half, position_pct=0.0, capped=False)
    capped = adjusted > max_pct
    position_pct = min(adjusted, max_pct)
    return KellySize(kelly_raw=kelly_raw, kelly_half=kelly_half, position_pct=position_pct, capped=capped)
```

## 为什么是 half-Kelly

`kelly.py` 顶部 docstring 给出理由：

> full Kelly 对估计误差敏感, half-Kelly 牺牲约 25% 长期收益换大幅降低破产概率和方差

full Kelly 在分布参数估计有偏差时表现极差。`known_distributions.py::BTST_BREAKOUT_T10` 给出 `winrate=0.5878, avg_gain=0.1848, avg_loss=-0.1041`，如果真实 `winrate` 比估计低 5 个百分点（0.54 vs 0.59），full Kelly 仓位会从理论最优的 ~30% 跳到 ~25%，方差仍然很大。half-Kelly 把仓位压到 ~15%，即使估计偏差 10pp 也不会破产。

**权衡**：牺牲约 25% 长期收益（数学上 half-Kelly 的几何增长率是 full Kelly 的 75%），换取破产概率和方差大幅下降。代价是牛市样本下长期跑输 full Kelly。

## per-setup 仓位上限

`daily_action.py::_MAX_POSITION_PCT_BY_SETUP` 按 setup 区分仓位上限：

```python
_MAX_POSITION_PCT = 0.10  # 默认单票上限
_MAX_POSITION_PCT_BY_SETUP: dict[str, float] = {
    "btst_breakout": 0.10,       # v2 ledger stays at 10% until canonical regime evidence is bound
    "oversold_bounce": 0.05,     # OB: 无 alpha, 限制到 5% (即使恢复也低仓位)
}
_MAX_PORTFOLO_PCT = 0.60  # 组合 ≤ 60%
```

设计逻辑：

- **BTST 10%**：有统计显著的 alpha（`E=+8.15%, n=133`，CI 不跨 0），分配正常仓位。
- **OversoldBounce 5%**：无 alpha（`E=+0.34%, CI 跨 0`），严格限制。即使 `DAILY_ACTION_DISABLED_SETUPS=none` 恢复，也低仓位运行。
- **组合 60%**：留 40% 现金作为 drawdown 缓冲 + 新信号预留。

注释里的 "v2 ledger stays at 10% until canonical regime evidence is bound" 指当前 v2 台账系统把单票硬上限锁在 10%，12% regime 例外暂停，等 canonical regime evidence 可由 repository 重验后恢复。这是审计口径的安全降级，不是 Kelly 计算本身的限制。

## BTST 永远触顶的反直觉事实

`daily_action.py` 第 964-965 行有一条重要注释：

```python
# 仓位计算: per-setup 上限 × regime 加仓 × drawdown 降仓 × trigger_strength 调节.
# 简化: BTST Kelly f*=5.35 永远触顶 → 直接用 setup_max_pct, 去掉装饰性 Kelly 计算.
```

用 `BTST_BREAKOUT_T10` 的参数代入 Kelly 公式：`winrate=0.5878, avg_gain=0.1848, avg_loss=-0.1041`：

```
kelly_fraction = 0.5878 / 0.1041 - 0.4122 / 0.1848
              ≈ 5.645 - 2.231
              ≈ 3.41
half_kelly = 0.5 × 3.41 ≈ 1.71
```

half-Kelly 给出 171% 仓位，远超 10% 上限。所以实际仓位直接取 `setup_max_pct = 0.10`，Kelly 计算退化为"装饰性"。

这不是设计 bug，而是 BTST 在 2026 牛市样本下分布参数极端有利的自然结果。如果未来样本期 winrate 降到 0.50、avg_gain 降到 0.10，Kelly 会给出 ~50% 仓位，此时 cap 才会生效。

## trigger_strength 调节强弱信号

既然 Kelly 永远触顶，仓位差异化靠 `trigger_strength`：

```python
setup_max_pct = _MAX_POSITION_PCT_BY_SETUP.get(setup_name, _MAX_POSITION_PCT)
regime_factor = _regime_size_factor(regime, setup_name)
drawdown_factor = 0.5 if dd_action == "decrease" else 1.0
strength_factor = max(0.3, min(1.0, float(result.trigger_strength)))
kelly_pct = setup_max_pct * drawdown_factor * regime_factor * strength_factor
kelly_pct = min(kelly_pct, setup_max_pct * _REGIME_POSITION_CAP_MULTIPLE)
```

最终仓位 = `setup_max_pct × drawdown_factor × regime_factor × strength_factor`，且不超过 `setup_max_pct × 1.2`（`_REGIME_POSITION_CAP_MULTIPLE`）。

- `strength_factor` 下限 0.3：即使最弱信号也保留 30% 仓位，避免完全不下单。
- `_REGIME_POSITION_CAP_MULTIPLE = 1.2`：即使 crisis 触发 1.2× 加仓，单票最多 12%（10% × 1.2），防止仓位失控。

## regime 加权系数的回测依据

`_REGIME_SIZE_FACTORS_BY_SETUP` 是 countercyclical 仓位放大系数，来自 192 笔真实成交：

```python
_REGIME_SIZE_FACTORS_BY_SETUP = {
    "btst_breakout": {"crisis": 1.2, "risk_off": 1.1, "normal": 1.0},
    "oversold_bounce": {"crisis": 1.0, "risk_off": 1.0, "normal": 1.0},
}
```

`daily_action.py` 第 78-83 行的注释给出数据依据：

```
BTST:        crisis 76%/+16.93%  risk_off 78%/+8.87%  normal 66%/+6.29%  → crisis/risk_off 加仓
OversoldBounce: crisis 48%/-1.15%  normal 51%/+0.15%  → 不加仓
```

BTST 三个 regime 都赚钱，crisis 最强（+16.93% / 76% WR）→ crisis 加仓 1.2×。OversoldBounce 三个 regime 都不显著 → 不加仓 1.0×。

⚠️ 这条结论有样本期偏差：2026 上半年是牛市，crisis regime 的样本量也小。`DAILY_ACTION_REGIME_SIZING=false` 是逃生口，可在熊市/高波动期全局关闭 regime 加权。

## 与风险框架的衔接

Kelly 输出 `position_pct` 后，`daily_action.py` 用 `build_risk_plan` 算止损价位：

```python
risk = build_risk_plan(
    invalidation_condition=result.invalidation_condition,
    avg_loss=known_dist.avg_loss,
    natural_horizon=horizon,
    setup_name=setup_name,
    hard_stop_pct=hard_stop_override,
)
entry_price = float(last_row["close"])
soft_stop_price = entry_price * (1 + risk.stop_loss_pct)
hard_stop_price = entry_price * (1 + risk.hard_stop_pct)
```

注意 `hard_stop_override` 优先用 setup 给出的 `range_based_stop_pct`（基于 20 日最低价的盘整区底部），而不是固定 -8%。这是 BTST 的「物理结构自适应止损」，详见 [风险框架](risk-framework.md)。

## 已知限制

1. **Kelly 公式假设二元结果**：实际收益分布有厚尾，`avg_loss` 会被极端值拉大。`known_distributions.py` 用 `paper_trading_backtest` 真实成交重校准 `OVERSOLD_BOUNCE_T5.avg_loss` 从 -5.57% 修正到 -11.15%（2x 低估），就是修正这个偏差。
2. **组合上限口径**：`_enforce_open_cap` 默认 true，把 T+10 跨日持仓计入 60% 上限。此前 per-run 从 0 起算导致真实敞口峰值 260%（26 仓），61 天超 60% 上限。逃生口 `DAILY_ACTION_ENFORCE_OPEN_CAP=false` 仅供对比，不是正确口径。
3. **regime 加仓暂停**：当前 v2 ledger 单票硬上限 10%，12% regime 例外暂停。`_REGIME_POSITION_CAP_MULTIPLE = 1.2` 在代码里仍计算，但被 ledger 层 cap 到 10%。这是审计口径的安全降级，待 canonical regime evidence 完成绑定后恢复。

## 深入阅读

- [风险框架](risk-framework.md):止损策略与 drawdown 熔断
- [BTST 涨停突破设计](btst-breakout-design.md):trigger_strength 如何调节仓位强弱
- [纸面交易设计](paper-trading-design.md):portfolio_state 的 open_exposure 字段
