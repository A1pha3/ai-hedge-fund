# 多周期诊断验证 (Multi-Horizon Diagnosis) 设计

> **日期**：2026-06-25
> **状态**：待用户审查
> **前置证据**：R-5.D 多时段诊断（commit `ea2d1d2f`）+ R-5.E 扩样本（32 日期 ~189 只）+ R-5.A regime 真实胜率披露（commit `c6ab9b92`）

## 一、背景与动机

### 用户原始需求

增加 T+5 / T+10 / T+15 / T+20 / T+25 / T+30 六个周期的胜率和赔率分析，在不同周期中选出"胜率和赔率都最优"的股票，以灵活决定如何交易，目标"短时间内赚钱更有效率"。

### 已有能力（用户不一定知道）

系统**已经**计算和记录了多周期数据：

- `expected_return.py` 已定义 `HORIZONS = ("t1", "t5", "t10", "t20", "t30")`——5 个周期的预期收益和胜率
- `tracking_history.json` 已真实记录 6 个周期实测收益：`next_{day,3day,5day,10day,20day,30day}_return`（293 条记录，30 日期）
- 但 BUY/HOLD/AVOID 决策**只用 T+30**（`investability.py:185`），其他周期未参与决策
- R-1 `horizon_conflict.py` 已检测 T+5 vs T+20 方向冲突

### 真实证据约束（R-5.D，决定性）

R-5.D 扩样本回测（32 日期 ~189 只真实推荐）显示：三 regime 下典型票（median）都微亏到平——

| 市场 | 样本 | 胜率 | 典型(median) |
|---|---|---|---|
| normal | 60 | 43% | -4.4% |
| crisis | 119 | 47% | -0.9% |
| risk_off | 10 | 30% | -5.1% |

且 `score 高 ≠ 胜率高`（2025 夏季 score<0.4 的票 100% 胜率，2025 春季 score≥0.5 的票 0% 胜率）。

**推论**：如果 T+30 选不出赚钱的票，用同样的 score 在 T+5/T+10 排序大概率也选不出。多周期不能凭空创造 alpha。因此**在动代码前必须先验证**。

## 二、目标与非目标

### 目标

回答 3 个关键问题，用真实数据决定后续是否做选股筛选（B）/快速赚钱（D）/时机标记（A）/仓位建议（C）：

- **Q1**：有没有某个 horizon × score 组合明显赚钱？（决定 B 选股筛选可行性）
- **Q2**：短周期（T+5/T+10）vs 长周期（T+20/T+30）哪个胜率更高？（决定 D 快速赚钱可行性）
- **Q3**：score 高低在哪个 horizon 最能预测胜负？（决定 score 体系是否需要重设）

### 非目标

- **不**实现 A/B/C/D 中的任何一个（先看验证结果再决定）
- **不**补 T+15/T+25 数据（先看现有 4 周期是否够得出结论）
- **不**做持久化 CLI 工具（YAGNI，验证脚本一次性）
- **不**改任何产品行为（零代码改动到 src/）

## 三、验证方法

### 数据流

```
data/reports/tracking_history.json (293 条记录, 30 日期)
    │ 每条: ticker, recommended_date, recommendation_score,
    │       next_{day,3,5,10,20,30}day_return
    ▼ 按 recommended_date 关联
data/reports/auto_screening_YYYYMMDD.json (30 个报告)
    │ 每个: market_state.regime_gate_level
    ▼ 合并 → 每条记录带上 regime
    ▼ 按 horizon × score_bucket × regime 分组
    ▼ 每格算 5 个指标
    ▼ 输出表格 + 结论
```

### 分桶逻辑（固定切分，跨 horizon 统一）

基于真实 score 分布 0.25~0.565 与 `investability.py` 既有阈值：

- `<0.4`：低分桶（多数票，`score < 0.4`）
- `0.4-0.5`：中分桶（少量票，`0.4 <= score < 0.5`）
- `0.5+`：高分桶（极少票，`score >= 0.5`，= BUY 候选门槛）

**为什么固定切分而非四分位数**：
1. 跨 horizon 可比（同桶定义，T+5/T+10/T+20/T+30 横向对比）
2. 直接 actionable（0.5=BUY 门槛，0.4=watchable 中点，结果直接转产品决策）
3. 暴露真相（高分桶样本少本身就是信息，不掩盖）

### 指标定义（每格 5 个）

| 指标 | 定义 | 备注 |
|---|---|---|
| **n** | 样本数 | 统计可信度 |
| **胜率** | `count(return > 0) / n` | 正收益比例 |
| **典型(median)** | `median(returns)` | 抗异常值，R-6 已验证比 mean 更准 |
| **平均(mean)** | `mean(returns)` | 含异常值，与 median 对比看污染 |
| **赔率(下行)** | `mean(returns[r<0])` | 亏损票均值，复用 R-144 定义 |

收益范围过滤：复用 `verify_recommendations.py` 的 `-50% ~ +50%`（百分点；防数据错误，如除权/停牌异常）。

### 样本不足处理

| n | 处理 |
|---|---|
| `n >= 20` | 完整 5 指标，正常展示 |
| `10 <= n < 20` | 指标照算，加 ⚠ "小样本" |
| `n < 10` | 指标照算，加 ❌ "样本不足"，**不参与结论推断** |

缺某 horizon 数据的记录（`next_5day_return=None` 等）→ 该 horizon 的 n 减 1，不影响其他 horizon。

## 四、诚实约束（避免 p-hacking）

1. **不 cherry-pick**：所有 4 horizon × 3 分桶 × 3 regime = 36 格全部展示，即使难看
2. **不试不同分桶找"好看结果"**：固定 `<0.4 / 0.4-0.5 / 0.5+`
3. **不预设结论**：不假设"短周期更好"或"高分更准"，让数据说话
4. **regime 关联失败不丢数据**：找不到 market_state 的记录归 "unknown" 桶，单列展示

## 五、产出形式

### 1. 终端表格（每个 regime 一张）

```
=== normal regime ===
周期  | Score    | n   | 胜率  | 典型      | 平均      | 赔率(下行)
T+5   | <0.4     | 85  | 42%  | -2.1%    | +0.5%    | -6.3%
T+5   | 0.4-0.5  | 22  | 50%  | +0.8% ⚠  | +1.2% ⚠  | -4.1% ⚠
T+5   | 0.5+     | 3   | 67%  | +3.2% ❌ | +5.0% ❌ | -2.1% ❌
T+10  | ...
T+20  | ...
T+30  | <0.4     | 85  | 43%  | -4.4%    | +1.3%    | -8.2%   ← baseline (R-5.D 已知)

=== crisis regime ===
...
=== risk_off regime ===
...
=== unknown regime ===
...
```

### 2. 文字结论

直接回答 Q1/Q2/Q3，每题一段，**基于数据**而非预设。

### 3. 决策路径

根据结论决定 A/B/C/D 哪些值得做。**以下阈值为示意，用于说明决策逻辑，最终阈值由用户在看到真实数据后裁定**：
- 若 Q1 发现某 horizon+score 组合 median > +3% 且 n >= 20 → B 有意义，进 writing-plans 设计筛选逻辑
- 若 Q2 发现短周期与长周期胜率差异 < 5pp → D 徒劳，放弃
- 若 Q3 发现 score 高低在任何 horizon 都不能预测胜负 → 当前 score 体系问题，需重新讨论方向
- 若所有 36 格 median 都 ≤ 0 → 多周期不能解决赚钱问题，转而讨论 regime-gating（R-5.F）或定位调整

## 六、脚本生命周期

1. 写 `scripts/_multi_horizon_diagnosis.py`（下划线前缀=临时性，~150 行）
2. 跑 `uv run python scripts/_multi_horizon_diagnosis.py`
3. 打印表格 + 结论
4. 与用户一起看结果，决定 A/B/C/D
5. 删除脚本，commit "chore: 移除一次性诊断脚本"（先例：`6de3935f`）
6. **不 commit 脚本本身**，避免污染仓库

## 七、成功标准

- **必要**：表格 36 格全部展示（无隐藏），结论基于数据回答 Q1/Q2/Q3
- **必要**：脚本跑通不报错，输出可读
- **充分**：结论足以让用户做出"做 A/B/C/D 中的哪些"的决策，或明确放弃

## 八、风险与已知局限

- **样本小**：293 条记录跨 30 日期，某些分桶（如 0.5+ × risk_off）必然 n < 10
- **regime 关联**：依赖 auto_screening 报告存在且含 market_state；若某日期报告缺失，归 unknown
- **缺 T+15/T+25**：本验证不补，若结论 promising 后续再补
- **score 来源**：tracking_history 的 `recommendation_score` 是当时的 score_b（非 composite），与当前前门的 composite_score 略有差异——但 R-5.D 已用此字段得出结论，保持一致
