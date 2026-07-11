# 简化设计 + 提升 alpha 的优化方案

## 核心洞察（回测数据验证）

当前系统最大的问题不是代码复杂，而是 **ranker 失效**：
- `trigger_strength` 公式中 30% 权重给了涨停强度（对主板恒=1.0，零区分度）
- `expected_return` 和 `convexity_ratio` 在排序键里是 **常量**（同一 setup 的先验）→ 4 键排序实际只有 1 键在干活
- **journal 从不记录 trigger_strength** → 无法验证 ranker 是否有效 → 学习闭环断裂

回测数据揭示了 **3 个被完全忽略的强信号**：

| 信号 | 基线 win/E[r] | 过滤后 win/E[r] | 样本保留 |
|---|---|---|---|
| **星期效应**: Mon+Tue 51%/+2.6% vs Wed-Fri 78%/+11.2% | 68%/+8.2% | 78%/+11.2% | 65% |
| **板块效应**: SZmain(000) 45%/+1.6% vs 其余 70%+/+7%+ | 68%/+8.2% | 70%+/+8.5% | 92% |
| **价格效应**: <15元 62%/+4.0% vs ≥15元 70%+/+8.6% | 68%/+8.2% | 70%+/+8.6% | 88% |
| **三者叠加** | 68%/+8.2% | **81%/+12.2%** | 56% |

---

## 改动清单（6 项，按收益排序）

### 1. ⭐ 简化 trigger_strength → 真正的 alpha ranker
**文件**: `btst_breakout.py:131-140`

当前公式 3 项退化：项 1 恒=0.30（主板涨停+10%），项 2 按市值排序，项 3 多数≈0。

新公式（3 因子，每个都有回测支撑）：
```python
trigger_strength = (
    0.35 * weekday_score    # Wed-Fri=1.0, Mon-Tue=0.0 (回测: 78% vs 51% win)
  + 0.35 * board_score      # 002/300=1.0, 688/60x=0.7, 000=0.0 (回测: 83%/45%)
  + 0.30 * depth_score      # clip(-pre_runup_pct/5, 0, 1)
)
```

### 2. ⭐ 简化排序键 → 去掉假多因子
**文件**: `daily_action.py:779-786`

从 `(-expected_return, -trigger_strength, -convexity_ratio, ticker)` 改为 `(-trigger_strength, ticker)`。

### 3. ⭐ 记录 trigger_strength 到 journal → 闭合学习环
**文件**: `paper_tracker.py:232` (`record_buy` 签名)

增加 trigger_strength/degraded 参数写入 journal。

### 4. 简化 BTST 资金流条件 → 去冗余
**文件**: `btst_breakout.py:80-81`

条件 2 去掉冗余 `today_flow > 0`（涨停日必然正流入），只保留 `> hist_mean`。同时合并 degraded 分支的重复代码。

### 5. 简化 condition 4 → 从硬门限变连续评分
**文件**: `btst_breakout.py:116-128`

门限从 ≤5% 放宽到 ≤10%，让 depth_score 在 ranker 里区分强弱。增加样本 → 更多分散。

### 6. 简化 Kelly → 承认它是装饰性的
**文件**: `daily_action.py`

BTST Kelly f*=5.35 永远触顶。直接用 setup_max_pct，去掉 Kelly 装饰性计算。

---

## 验证方案

1. 回测验证：用 journal.jsonl 重算
2. 单元测试：trigger_strength 新公式、排序键简化、journal 记录
3. 全量回归：uv run pytest tests/offensive/ tests/tools/ -q