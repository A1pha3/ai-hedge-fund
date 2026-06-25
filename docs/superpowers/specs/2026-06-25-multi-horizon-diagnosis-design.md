# 多周期诊断验证 (Multi-Horizon Diagnosis) 设计

> **日期**：2026-06-25
> **状态**：待用户最终审查
> **前置证据**：R-5.D 多时段诊断（commit `ea2d1d2f`）+ R-5.E 扩样本（32 日期 ~189 只）+ R-5.A regime 真实胜率披露（commit `c6ab9b92`）

## 一、背景与动机

### 用户原始需求

增加 T+5 / T+10 / T+15 / T+20 / T+25 / T+30 六个周期的胜率和赔率分析，在不同周期中选出"胜率和赔率都最优"的股票，以灵活决定如何交易。**赚钱标准：每天的最大收益率争取最大，各周期收益最大，持续累积，年化最大**。

### 已有能力（用户不一定知道）

系统**已经**计算和记录了多周期数据：

- `expected_return.py` 已定义 `HORIZONS = ("t1", "t5", "t10", "t20", "t30")`——5 个周期的预期收益和胜率
- `recommendation_tracker.py:54` `DEFAULT_HORIZONS = (1, 3, 5, 10, 20, 30)`——6 个实测收益 horizon
- `tracking_history.json` 已真实记录 6 周期实测收益：`next_{day,3day,5day,10day,20day,30day}_return`（293 条记录，30 日期）
- 但 BUY/HOLD/AVOID 决策**只用 T+30**（`investability.py:185`），其他周期未参与决策
- R-1 `horizon_conflict.py` 已检测 T+5 vs T+20 方向冲突
- **T+15 / T+25 确实缺失**——需补

### 真实证据约束（R-5.D，决定性）

R-5.D 扩样本回测（32 日期 ~189 只真实推荐）显示：三 regime 下典型票（median）都微亏到平——

| 市场 | 样本 | 胜率 | 典型(median) |
|---|---|---|---|
| normal | 60 | 43% | -4.4% |
| crisis | 119 | 47% | -0.9% |
| risk_off | 10 | 30% | -5.1% |

且 `score 高 ≠ 胜率高`（2025 夏季 score<0.4 的票 100% 胜率，2025 春季 score≥0.5 的票 0% 胜率）。

### 赚钱标准校准（诚实）

用户目标是**最大化收益**（追求赢，不是稳健不亏）。这改变了指标权重：
- mean 比 median 更重要（mean 捕获极端赢家，如 688008 +112%）
- upside / 盈亏比是核心
- 高分桶的关注度提升

**但"最大化收益"的前提是模型能选出正期望的票**。如果验证显示所有 horizon × 分桶组合的 median 都 ≤ 0（R-5.D 暗示很可能），"最大化"无从谈起——那时需重新讨论方向（regime-gating 或定位调整）。**验证仍然先于实现**。

## 二、目标与非目标

### 目标

回答 4 个关键问题，用真实数据决定后续是否做选股筛选（B）/快速赚钱（D）/时机标记（A）/仓位建议（C）：

- **Q1**：有没有某个 horizon × score 组合明显赚钱？（决定 B 选股筛选可行性）
- **Q2**：短周期（T+5/T+10）vs 长周期（T+20/T+30）哪个胜率更高？（决定 D 快速赚钱可行性）
- **Q3**：score 高低在哪个 horizon 最能预测胜负？（决定 score 体系是否需要重设）
- **Q4**：赔率不对称（盈亏比 > 1.5）的赢家组合存在吗？在哪个 horizon？（决定能否"小亏大赚"）

### 非目标

- **不**实现 A/B/C/D 中的任何一个（先看验证结果再决定）
- **不**改 BUY/HOLD/AVOID 决策逻辑（Phase 1 只加 horizon，不改决策）
- **不**做持久化诊断 CLI 工具（Phase 2 一次性脚本）

## 三、Phase 1：持久化基础设施（T+15 / T+25 扩展，commit）

### 关键发现

`fetch_actual_returns` 拉取的是**完整 45 天价格序列**（`to_dt + 45 days`），按 `DEFAULT_HORIZONS` 循环算各 horizon 收益。T+15/T+25 的价格数据已在内存，只是循环没算。

### 改动清单

| 改动点 | 文件 | 工作量 |
|---|---|---|
| 扩展常量 | `recommendation_tracker.py:54` `(1,3,5,10,15,20,25,30)` | 1 行 |
| 扩展 bucket_fields | `recommendation_tracker.py:607-614` 加 `15: "next_15day_return"`、`25: "next_25day_return"` | 2 行 |
| 扩展回填映射 | `recommendation_tracker.py:466-473` 加 `("next_15day_return", "day_15")`、`("next_25day_return", "day_25")` | 2 行 |
| 扩展 dataclass | `TrackedRecommendation` 加 `next_15day_return / next_25day_return: float \| None = None` | 4 行 |
| 扩展 verify 消费 | `verify_recommendations.py:216-230` `_extract_tracking_returns` 加 t15/t25 | 2 行 |
| 扩展汇总渲染 | `verify_recommendations.py:461-466` 加 `overall_t15_win_rate / overall_t25_win_rate` | ~6 行 |

### 副作用披露（行为改变）

- `verify_recommendations` 输出表格多 2 行（T+15 / T+25 胜率）
- `confidence_calibration` 若消费 `next_Xday_return`，需检查是否需要同步加 t15/t25 bucket（在 Phase 1 实现时确认）
- `btst_realized_bridge.py:157-158` 若依赖 horizon 映射，需检查
- 任何依赖 `DEFAULT_HORIZONS` 的下游都受影响——**实现时需 grep 确认所有消费者**

### TDD 要求

- 新 horizon 的回填测试（mock fetcher 返回 8 个点位，验证 day_15/day_25 算出）
- verify 的 t15/t25 提取测试
- 向后兼容测试（缺 day_15/day_25 的旧记录不破坏）

### 回填

跑一次 `update_tracking_returns`（或等价路径），让现有 293 条记录获得 T+15/T+25 实测值。tushare 价格大部分已缓存（R-5.E 已拉过 45 天窗口），预计 15-30 分钟。

## 四、Phase 2：一次性诊断脚本（跑完删除）

### 脚本位置

`scripts/_multi_horizon_diagnosis.py`（下划线前缀=临时性，~200 行，验证后删除，先例 `6de3935f`）

### 数据流

```
data/reports/tracking_history.json (293 条, Phase 1 后含 T+15/T+25)
    │ 每条: ticker, recommended_date, recommendation_score,
    │       next_{3,5,10,15,20,25,30}day_return
    ▼ 按 recommended_date 关联
data/reports/auto_screening_YYYYMMDD.json (30 个报告)
    │ 每个: market_state.regime_gate_level
    ▼ 合并 → 每条记录带上 regime
    ▼ 按 horizon × score_bucket × regime 分组
    │  horizon:       T+5, T+10, T+15, T+20, T+25, T+30 (6 个)
    │  score_bucket:  <0.4 / 0.4-0.5 / 0.5+ (3 桶)
    │  regime:        normal / crisis / risk_off (3 类)
    │  = 54 格
    ▼ 每格算 8 个指标
    ▼ 输出表格 + 结论
```

### 分桶逻辑（固定切分，跨 horizon 统一）

基于真实 score 分布 0.25~0.565 与 `investability.py` 既有阈值：

- `<0.4`：低分桶（多数票，`score < 0.4`）
- `0.4-0.5`：中分桶（少量票，`0.4 <= score < 0.5`）
- `0.5+`：高分桶（极少票，`score >= 0.5`，= BUY 候选门槛）

**为什么固定切分而非四分位数**：
1. 跨 horizon 可比（同桶定义，6 个 horizon 横向对比）
2. 直接 actionable（0.5=BUY 门槛，0.4=watchable 中点，结果直接转产品决策）
3. 暴露真相（高分桶样本少本身就是信息）

### 8 个指标定义

| # | 指标 | 定义 | 如何用于赚钱决策 |
|---|---|---|---|
| 1 | **n** | 样本数 | 统计可信度 |
| 2 | **胜率** | `count(r>0)/n` | 确定性 |
| 3 | **median** | `median(returns)` | 典型票表现（抗异常值） |
| 4 | **mean** | `mean(returns)` | 平均（捕获极端赢家，最大化收益目标看这个） |
| 5 | **上行赔率** | `mean(r[r>0])` | 赚的话赚多少 |
| 6 | **下行赔率** | `mean(r[r<0])` | 亏的话亏多少（复用 R-144 定义） |
| 7 | **盈亏比** | `upside/\|downside\|` | **直接决策**：>1.5 好机会；1.0-1.5 边际；<1.0 不利（除非胜率 60%+） |
| 8 | **5th pct** | 5% 分位数 | 真实尾部风险：5% 概率亏多少；反推仓位上限 |

**赚钱决策公式**：`E[收益] = 胜率 × 上行赔率 - (1-胜率) × |下行赔率|`。E > 0 才是正期望。

**收益范围过滤**：复用 `verify_recommendations.py` 的 `-50% ~ +50%`（百分点；防除权/停牌异常）。

### 样本不足处理

| n | 处理 |
|---|---|
| `n >= 20` | 完整 8 指标，正常展示 |
| `10 <= n < 20` | 指标照算，加 ⚠ "小样本"；**5th pct 不显示**（小样本不稳定） |
| `n < 10` | 指标照算，加 ❌ "样本不足"，**5th pct 不显示，不参与结论推断** |

- 缺某 horizon 数据的记录 → 该 horizon 的 n 减 1，不影响其他 horizon
- bucket 内无正收益 → 上行赔率/盈亏比显示 "—"
- bucket 内无负收益 → 下行赔率/盈亏比显示 "—"（极端乐观情形）

## 五、诚实约束（避免 p-hacking）

1. **不 cherry-pick**：所有 6 horizon × 3 分桶 × 3 regime = 54 格全部展示，即使难看
2. **不试不同分桶找"好看结果"**：固定 `<0.4 / 0.4-0.5 / 0.5+`
3. **不预设结论**：不假设"短周期更好"或"高分更准"，让数据说话
4. **regime 关联失败不丢数据**：找不到 market_state 的记录归 "unknown" 桶，单列展示

## 六、产出形式

### 1. 终端表格（每个 regime 一张，共 4 张含 unknown）

```
=== normal regime ===
周期  | Score    | n   | 胜率  | median   | mean     | 上行     | 下行     | 盈亏比 | 5th pct
T+5   | <0.4     | 85  | 42%  | -2.1%   | +0.5%   | +4.2%   | -6.3%   | 0.67  | -12.5%
T+5   | 0.4-0.5  | 22  | 50%  | +0.8%⚠  | +1.2%⚠  | +3.5%⚠  | -4.1%⚠  | 0.85⚠ | —
T+5   | 0.5+     | 3   | 67%  | +3.2%❌ | +5.0%❌ | +6.1%❌ | -2.1%❌ | 2.90❌ | —
T+10  | ...
T+15  | ...（新）
T+20  | ...
T+25  | ...（新）
T+30  | <0.4     | 85  | 43%  | -4.4%   | +1.3%   | +5.8%   | -8.2%   | 0.71  | -18.0%   ← baseline
...
```

### 2. 文字结论

直接回答 Q1/Q2/Q3/Q4，每题一段，**基于数据**。

### 3. 决策路径

根据结论决定 A/B/C/D 哪些值得做。**以下阈值为示意，最终由用户在看到真实数据后裁定**：

- Q1 发现某 horizon+score 组合 `median > +3%` 且 `n >= 20` → B 有意义，进 writing-plans 设计筛选逻辑
- Q2 发现短周期与长周期胜率差异 `< 5pp` → D 徒劳，放弃
- Q3 发现 score 高低在任何 horizon 都不能预测胜负 → 当前 score 体系问题，需重新讨论方向
- Q4 发现盈亏比 `> 1.5` 且 `n >= 20` → 即使胜率 40% 也可参与，进 C 仓位建议设计
- 所有 54 格 `median <= 0` → 多周期不能解决赚钱问题，转而讨论 regime-gating（R-5.F）或定位调整

## 七、脚本生命周期

### Phase 1（持久化，commit）

1. TDD：写 `next_15day_return / next_25day_return` 的回填 + verify 测试（RED）
2. 改 `recommendation_tracker.py` + `verify_recommendations.py`（GREEN）
3. 跑 FULL 回归（确保向后兼容）
4. 跑回填，让 tracking_history 获得 T+15/T+25 实测值
5. commit："feat(multi-horizon): 扩展 DEFAULT_HORIZONS 到 8 周期 (T+15/T+25)"

### Phase 2（一次性，跑完删除）

1. 写 `scripts/_multi_horizon_diagnosis.py`（~200 行）
2. 跑 `uv run python scripts/_multi_horizon_diagnosis.py`
3. 打印 54 格表 + 文字结论
4. 与用户一起看结果，决定 A/B/C/D
5. 删除脚本，commit "chore: 移除一次性诊断脚本"（先例 `6de3935f`）

## 八、成功标准

- **Phase 1 必要**：FULL 回归绿，tracking_history 293 条记录有 T+15/T+25 实测值，向后兼容
- **Phase 2 必要**：54 格全部展示（无隐藏），结论基于数据回答 Q1/Q2/Q3/Q4
- **Phase 2 数据完整性（sanity check）**：Phase 2 的 T+30 × 聚合全 score 桶，胜率应**约等于** R-5.A 的 `REGIME_HISTORICAL_WINRATES`（normal 43% / crisis 47% / risk_off 30%）。若偏离 > 5pp，说明数据集差异（293 条 vs R-5.D 用的 189 只）或 regime 关联逻辑有误，需先排查再下结论
- **充分**：结论足以让用户做出"做 A/B/C/D 中的哪些"的决策，或明确放弃

## 九、风险与已知局限

- **样本小**：293 条记录跨 30 日期，某些分桶（如 0.5+ × risk_off）必然 n < 10
- **regime 关联**：依赖 auto_screening 报告存在且含 market_state；若某日期报告缺失，归 unknown
- **score 时点不一致**（设计简化，必须明确）：验证用 tracking_history 的 `recommendation_score`（= **score_b**，原始分），但当前前门 BUY/HOLD/AVOID 决策用 `composite_score`（= score_b + 动量/行业/一致性/量价/趋势 bonus）。一只票可能 `score_b=0.40` 但 `composite=0.55`。**验证结论回答的是 score_b 的预测力**；若后续 B（选股筛选）用 composite 门槛，需二次验证 composite 的预测力（R-5.D 已用 score_b 保持一致，本验证沿用）
- **score 来源**：tracking_history 的 `recommendation_score` 是当时的 score_b（非 composite），与当前前门 composite_score 略有差异——R-5.D 已用此字段得出结论，保持一致
- **T+15/T+25 回填依赖 tushare 配额**：若配额耗尽，可能需要分批；R-5.E 已成功回填 32 日期，配额应该够
- **向后兼容风险**：扩 `DEFAULT_HORIZONS` 可能影响未知消费者——Phase 1 实现时必须 grep 全仓确认所有 `DEFAULT_HORIZONS` / `next_Xday_return` 消费者
