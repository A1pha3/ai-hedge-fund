# 本轮优化：修 3 个 operator-facing 谎言 + 2 个 alpha 提升 + 2 个简化

## 核心洞察

审计发现 trigger_strength ≥0.35 **单独**就实现了 88.7% 胜率/+15.3% E[r]，而 weekday/board 预过滤在此基础上几乎没有增量。系统最大的问题不是缺 alpha，而是代码说的和做的不一致——3 处 operator-facing 文档/注释/渲染文本描述的公式与实际执行的不符。

## 改动清单（7 项）

### 🔴 Bug 修复（3 个 operator-facing 谎言）

**Bug 1**: `btst_breakout.py` docstrings 说 ≤5%，实际代码是 ≤10%
- `:7, :14, :17, :109, :162` 全部更新为 ≤10%

**Bug 2**: `daily_action.py:1068` 渲染文本说 "反转深度40%+涨停强度30%+主力流入30%"，实际是 weekday/board/trend/low_vol 各 25%
- 更新为正确的 4 因子描述

**Bug 3**: `known_distributions.py` T+8 key 用 T+10 分布数据
- 创建真实的 `BTST_BREAKOUT_T8` 分布对象（用回测 T+8 数据：E[r]=+6.33%, winrate 从 T+10 的 54.2% 上调）
- 修复 soft_stop 用 T+10 avg_loss 偏宽的问题

### ⭐ Alpha 提升（2 项）

**Alpha 1**: 简化预过滤 — 去掉 weekday/board OR 逻辑，只靠 trigger_strength
- 数据：ts≥0.35 已实现 88.7% 胜率，OR 预过滤仅从 133→124 去掉 9 笔（E[r] +8.15%→+8.78%），但在 ts≥0.35 子集上无增量
- 改动：保留 ts≥0.35 最低阈值（真正的 alpha 过滤器），简化 OR 逻辑

**Alpha 2**: soft_stop 修复 — 用 T+8 avg_loss 替代 T+10
- 当前 soft_stop = T+10 avg_loss × 1.5 = -13.76%，比 hard_stop -8% 还宽（不可达）
- 修复后用 T+8 avg_loss，soft_stop 会比 hard_stop 窄，形成有效两级止损

### 🔧 简化（2 项）

**Simp 1**: `risk_framework.py` 删除 `drawdown_action` 模块级函数（与 PaperTracker.drawdown_action 重复，从未调用）

**Simp 2**: `btst_breakout.py` 把 `from datetime import datetime` 从 detect() 内部移到模块顶部

## 不改的

- `_PRE_RUNUP_MAX_PCT = 10.0` 保持（放宽增加样本量，ts ranker 已覆盖深度信号）
- `_ATR_MEDIAN_THRESHOLD = 3.0` 保持（回测验证效果最强，无需调整）
- `_MIN_TRIGGER_STRENGTH = 0.35` 保持（88.7% 胜率的完美拐点）
- 停损执行逻辑保持（BTST disclose_only, OB execute）