# 两个系统，两套方案

## 1. `--daily-action` (BTST 均值回归): Donchian 位置因子

替换 `btst_breakout.py` 的 `trend_score` → `position_score`:

```python
low_5d = min(closes); high_5d = max(closes)
range_pct = (closes[-1] - low_5d) / (high_5d - low_5d) if (high_5d - low_5d) > 0 else 0.5
position_score = 1.0 if range_pct < 0.5 else 0.0  # 下半区=新鲜突破=好
```

语义："涨停是从低位拉起（新鲜=好）还是在高位追（衰竭=差）"——均值回归语义。

## 2. `--auto` (趋势+均值回归混合): 新增 2 个 trend 子因子

在 `strategy_scorer_trend.py` 的 `_build_trend_sub_factors` 中新增：

### 子因子 A: Donchian 位置 (donchian_position)
```python
def _score_donchian_position(prices_df, window=20):
    """价格在 N 日高低点区间的位置 (0=底部, 1=顶部).
    趋势跟踪语义: 上半区=趋势已确立=看多; 下半区=趋势未确立=中性."""
    high_N = prices_df["high"].rolling(window).max()
    low_N = prices_df["low"].rolling(window).min()
    position = (close - low_N) / (high_N - low_N)
    direction = +1 if position > 0.5 else -1
    confidence = position * 100  # 越靠近顶部, 置信度越高
```

### 子因子 B: MA 距离 (ma_distance)
```python
def _score_ma_distance(prices_df, ma_window=50):
    """收盘价到均线的距离 (乖离率).
    趋势健康度: 适中距离=健康趋势; 过大=过热; 过小=趋势弱."""
    ma = prices_df["close"].ewm(span=ma_window).mean()
    distance_pct = (close - ma) / ma * 100
    direction = +1 if distance_pct > 0 else -1
    # 置信度: 距离适中 (2-8%) 时最高; 过热 (>10%) 时降低
    confidence = clip(100 - abs(distance_pct - 5) * 10, 0, 100)
```

### 权重重分配
当前（死代码 long_trend 不计入）:
- ema_alignment: 0.30, adx: 0.16, momentum: 0.24, volatility: 0.15

新权重:
- ema_alignment: 0.22, adx: 0.14, momentum: 0.20, volatility: 0.12, **donchian: 0.16, ma_distance: 0.16**

去掉死代码 long_trend_alignment（需要 200 行但缓存只有 120 行，永远不会触发）。

## 改动清单

### `--daily-action` 侧:
1. `btst_breakout.py`: trend_score → position_score (Donchian 分位)
2. `daily_action.py`: 渲染文本更新

### `--auto` 侧:
3. `strategy_scorer_trend.py`: 新增 `_score_donchian_position` + `_score_ma_distance` 函数
4. `strategy_scorer_trend.py`: `_build_trend_sub_factors` 接入新因子
5. `strategy_scorer_utils.py`: 更新 `TREND_SUBFACTOR_WEIGHTS`（去掉 long_trend，加入 donchian + ma_distance）
6. 测试 + 回测验证

## 数据可行性
- price_cache ~120 行 OHLCV: 20/55 日 Donchian ✅, EMA20/50/60 ✅
- 不使用 200/252 日窗口（缓存不足）

## 不改的
- BTST 的 condition 1-4、T+8 持仓、止损策略
- --auto 的 candidate_pool、signal_fusion 权重、investability 排序
- regime 自适应权重（自动放大/缩小 trend 因子影响）