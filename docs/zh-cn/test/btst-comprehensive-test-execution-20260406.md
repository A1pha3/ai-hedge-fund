# BTST 综合测试执行报告（2026-04-06）

## 执行摘要

本轮按照 `docs/zh-cn/test/btst-comprehensive-test-plan.md` 对 BTST 做了分层综合测试，结论可以先收敛为 4 点：

1. **结构层稳定**：本轮核心回归共 **99 个用例全部通过**，筛选、回测、continuation 治理与离线分析脚本没有发现功能性回归。
2. **默认 BTST 基线仍应保持不变**：fresh 多窗口验证再次表明，`watchlist_zero_catalyst_guard_relief @ select=0.40 / near_miss=0.40` 仍是更稳妥的默认口径，`0.34 / 0.40` 这类扩容 probe 更像 **T+2 tradeoff**，不是严格意义上的 BTST 升级。
3. **T+2 continuation 方向有效，但仍需隔离推进**：当前 continuation 治理链完整，`300505` 已进入 `paper_execution_candidate`；fresh lane validation 也再次显示 **T+2 分布优于 T+1** 的倾向，但整体仍应维持 `observation_only + paper_only`。
4. **下一轮最值得做的优化，不是全局放宽闸门，而是做更窄、更可解释的结构优化**：重点应放在 **continuation 专用 execution edge floor / sizing**、**300724 型弱确认 re-entry 抑制**、**T+2 continuation 识别与治理收敛**。

## 一、本轮实际执行了什么

### 1.1 核心回归

本轮直接执行了以下测试：

```bash
uv run pytest tests/screening/test_candidate_pool.py tests/screening/test_strategy_scorer.py tests/screening/test_phase2_screening.py -v
uv run pytest tests/backtesting/test_walk_forward.py tests/backtesting/test_compare.py tests/backtesting/test_rule_variant_compare.py -v
uv run pytest tests/test_generate_btst_tplus2_continuation_promotion_gate_script.py tests/test_generate_btst_tplus2_continuation_watchlist_execution_script.py tests/test_generate_btst_tplus2_continuation_eligible_gate_script.py tests/test_generate_btst_tplus2_continuation_eligible_execution_script.py tests/test_generate_btst_tplus2_continuation_execution_gate_script.py tests/test_generate_btst_tplus2_continuation_execution_overlay_script.py tests/test_generate_btst_tplus2_continuation_governance_board_script.py tests/test_generate_btst_tplus2_continuation_watchboard_script.py -v
uv run pytest tests/test_analyze_btst_multi_window_profile_validation_script.py tests/test_analyze_btst_tplus2_continuation_lane_validation_script.py tests/test_analyze_btst_tplus2_continuation_clusters_script.py tests/test_analyze_btst_tplus2_continuation_peer_rollup_script.py tests/test_generate_btst_tplus2_continuation_expansion_board_script.py -v
```

执行结果：

| 测试层 | 结果 |
|------|------|
| screening 回归 | `69 passed` |
| backtesting 回归 | `14 passed` |
| continuation 治理回归 | `11 passed` |
| 分析脚本回归 | `5 passed` |
| **合计** | **99 passed** |

本轮没有出现失败用例。仅有既有第三方依赖告警：

- `langchain_gigachat` 的 `PydanticDeprecatedSince20` 警告
- `Redis not available` 的缓存告警

这两类告警本轮都没有阻断测试结论。

### 1.2 fresh 离线聚合分析

本轮还 fresh 重跑了两份离线验证脚本：

```bash
uv run python scripts/analyze_btst_multi_window_profile_validation.py \
  --reports-root data/reports \
  --report-name-contains paper_trading_window \
  --baseline-profile watchlist_zero_catalyst_guard_relief \
  --variant-profile watchlist_zero_catalyst_guard_relief \
  --variant-select-threshold 0.34 \
  --variant-near-miss-threshold 0.40 \
  --output-json data/reports/btst_multi_window_profile_validation_20260406.json \
  --output-md data/reports/btst_multi_window_profile_validation_20260406.md

uv run python scripts/analyze_btst_tplus2_continuation_lane_validation.py \
  --reports-root data/reports \
  --anchor-ticker 600988 \
  --profile-name watchlist_zero_catalyst_guard_relief \
  --report-name-contains btst_ \
  --output-json data/reports/btst_tplus2_continuation_lane_validation_20260406.json \
  --output-md data/reports/btst_tplus2_continuation_lane_validation_20260406.md
```

这两份结果是本轮最重要的“真实效果验证”依据。

## 二、本轮测试得到的关键结论

### 2.1 默认 BTST 基线继续成立

fresh 多窗口验证覆盖了 **17 个 report window**，聚合结论是：

| 指标 | 结果 |
|------|------|
| `keep_baseline_count` | `4` |
| `variant_supports_t1_count` | `3` |
| `variant_improves_t2_only_count` | `1` |
| `mixed_count` | `9` |
| 聚合 recommendation | `Variant behaves like a T+2 tradeoff rather than a strict BTST upgrade; keep the baseline default unless the objective changes.` |

这说明：

1. `select=0.34 / near_miss=0.40` 的扩容 probe 并没有形成稳定的默认 BTST 升级证据。
2. 它在部分窗口中能带来更好的 `t+2_close_return_median`，但经常伴随更差的 `next_close_positive_rate` 或更弱的 T+1 尾部质量。
3. 因此，默认 BTST 不应放宽到更激进档位。

### 2.2 continuation lane 再次显示“T+2 优于 T+1”的结构倾向

fresh lane validation 聚合了 **40 条 lane row**，关键统计如下：

| 指标 | 结果 |
|------|------|
| `next_close_positive_rate` | `0.4` |
| `t_plus_2_close_positive_rate` | `0.525` |
| `next_close_return_median` | `-0.0181` |
| `t_plus_2_close_return_median` | `0.0117` |
| `next_high_hit_rate_at_threshold=2%` | `0.4` |

这组数据说明：

1. continuation 样本整体 **不适合直接并回 BTST 的 T+1 默认目标**。
2. 但它们在 T+2 的分布明显优于 T+1，符合“**独立 continuation lane**”这一设计初衷。
3. 当前脚本给出的 recommendation 仍是：**保留 `observation_only`，继续积累更多窗口**。

### 2.3 300505 的治理推进是合理的，但它仍只是隔离的 paper candidate

当前最新 watchboard 状态：

| 项目 | 当前值 |
|------|--------|
| `effective_watchlist_tickers` | `["600989", "300505"]` |
| `effective_eligible_tickers` | `["600988", "300505"]` |
| `effective_execution_candidates` | `["300505"]` |
| `lane_support_ratio` | `0.875` |
| `300505.t_plus_2_close_return_mean` | `0.0361` |
| 相对 watch benchmark 的 `t+2` 均值差 | `+0.0244` |

本轮判断：

1. `300505` 被推进到 `paper_execution_candidate` 有充分结构证据支撑。
2. 但它仍处于 `default_btst_blocked`、`paper_only`、`observation_only` 语义下。
3. 因此，它是 continuation 的强候选，不是默认 BTST 已升级的证据。

### 2.4 全局闸门放宽依然不是更优方向

从已有历史验证与本轮复核的结论可以继续确认：

1. `neutral mean_reversion` 一类大范围释放，会把样本面打开得过猛。
2. `fast threshold` 或更激进的阈值放宽，通常只是在扩大 tradeable surface，同时恶化 T+1 胜率与尾部。
3. `watchlist_019` 这类轻微 watchlist 阈值下调，对核心瓶颈帮助有限。

因此，**“多放一些票进去”不是当前最优优化方向**。

## 三、当前最清楚的系统短板

### 3.1 300724 型弱确认边缘样本仍然是主要噪声源

已有生命周期复盘表明：

1. `300724` 的主问题不是退出太晚，而是 **弱确认入场 + 弱确认 re-entry**。
2. 多条亏损腿都发生在 `0.20x ~ 0.225` 的边缘分数区间。
3. 当前默认基线拒绝弱确认回补，是合理的。

这意味着：

- 未来优化不应重新放松全局闸门，把 `300724` 这类样本重新大规模放回。

### 3.2 execution floor 既可能拦噪声，也可能误伤 continuation edge

execution score floor 复盘已经证明：

1. 默认 `WATCHLIST_MIN_SCORE = 0.225`
2. `600988 / score_final=0.2170` 在 `0.225` 下会被 `position_blocked_score` 拦住
3. 当 floor 降到 `0.21`，它会转为 **100 股最小 lot 可执行**

但问题在于：

1. 同样的放宽也会把部分 `300724` 边缘样本放出来
2. 因而 **不能做全局 execution floor 下调**

结论：

- execution floor 的优化方向应是 **局部化、带标签、带治理前提**，而不是全局参数放松。

## 四、本轮确认的更优优化方向

基于本轮综合测试，下一轮最值得做的方向有 3 个。

### 方向 1：做 continuation 专用的 execution edge floor / sizing

这是当前我认为**收益潜力最高、风险最可控**的方向。

原因：

1. `600988`、`300505` 这类样本更像 T+2 continuation 候选，而不是典型 T+1 BTST 样本。
2. 它们已经在 lane validation / governance 中表现出较强 continuation 特征。
3. execution floor 复盘说明，少量边缘 continuation 候选会被默认 `0.225` 硬门槛拦掉。

建议原则：

1. **不要降低全局 `WATCHLIST_MIN_SCORE`**
2. 只对满足 continuation 条件的样本开放更低 floor，例如：
   - 已带 `t_plus_2_continuation_candidate`
   - 已进入 eligible / execution governance
   - lane support ratio 达标
   - 仍保持 `paper_only`
3. 只给最小 lot 或更低 execution ratio，不做大仓位放大

预期价值：

- 有机会把 `600988 / 300505` 这类真正的 continuation edge 变成更真实的 paper execution 证据，同时避免把 `300724` 型噪声全局放出来。

### 方向 2：增强 300724 型 edge re-entry 的确认门槛

这是当前最明确的“降噪收益”方向。

原因：

1. 300724 的问题主轴已经比较清楚：**边缘入场质量不足 + re-entry 确认不足**
2. 默认基线已经在一定程度上把它压住，但未来如果做 continuation 或 edge execution 实验，必须防止它回流

建议方向：

1. 对 stop-loss 后的 re-entry 增加更强确认
2. 不看“时间冷却”本身，而看“确认是否显著改善”
3. 优先考虑：
   - breakout freshness 的再确认
   - trend acceleration 的提升
   - 更高的实际执行分数门槛
   - 对 repeated edge loser 做更强的重入惩罚

预期价值：

- 进一步降低 300724 这种高复发低质量样本对组合的拖累。

### 方向 3：继续做 T+2 continuation 识别与治理收敛，而不是继续做 BTST 默认档放宽

这是当前最符合证据的主路线。

原因：

1. fresh 多窗口验证已经说明，全局阈值放宽不是默认 BTST 升级方向。
2. fresh lane validation 又说明 continuation 的 T+2 特征是真实存在的。
3. `300505` 已经在治理链上走到了 `paper_execution_candidate`，表明这个方向具备可执行性。

建议继续做的事情：

1. 扩大 continuation cluster / peer purity 复核
2. 增加更多像 `300505` 这样可复核的第二批样本
3. 继续把 continuation 与默认 BTST 隔离治理
4. 在更多窗口上验证 continuation 的 closed-cycle 质量

预期价值：

- 把“默认 BTST 的稳定性”与“continuation 的增量 alpha 探索”同时保住。

## 五、当前不建议做的方向

### 5.1 不建议全局放宽 BTST 默认阈值

原因：

1. 多窗口验证不支持
2. T+1 质量会恶化
3. 容易把已知 offender 放回来

### 5.2 不建议大范围放宽 neutral mean reversion 或 Layer B 闸门

原因：

1. 过线样本扩张过猛
2. 结果不可解释
3. 风格暴露容易失控

### 5.3 不建议直接把 continuation 候选并入默认 BTST

原因：

1. continuation 的强项是 T+2，不是 T+1
2. 当前证据仍然更支持隔离 paper 验证

## 六、最终结论

本轮综合测试给出的最重要结论是：

1. **系统当前并没有“坏掉”**，反而结构上相当稳定。
2. **默认 BTST 当前没有被更优全局变体击败**，应继续保持默认档不变。
3. **更好的收益方向已经出现，但不在“全局放宽”上，而在“把 continuation 做成更窄、更可控的增量层”上。**

因此，下一轮如果要继续追求更高胜率和收益，最优优先级应当是：

1. **continuation 专用 execution edge floor / sizing**
2. **300724 型弱确认 re-entry 抑制**
3. **继续扩大 T+2 continuation 的样本验证与治理闭环**

## 七、产物索引

本轮新增或直接使用的关键产物：

- `docs/zh-cn/test/btst-comprehensive-test-plan.md`
- `docs/zh-cn/test/btst-comprehensive-test-execution-20260406.md`
- `data/reports/btst_multi_window_profile_validation_20260406.json`
- `data/reports/btst_multi_window_profile_validation_20260406.md`
- `data/reports/btst_tplus2_continuation_lane_validation_20260406.json`
- `data/reports/btst_tplus2_continuation_lane_validation_20260406.md`

---

**本轮判定**：

- 测试范围：筛选、回测、continuation 治理、离线多窗口验证、lane validation 复核
- baseline 配置：`watchlist_zero_catalyst_guard_relief @ select=0.40 / near_miss=0.40`
- variant / overlay 配置：`0.34 / 0.40` 扩容 probe + isolated T+2 continuation lane
- 最终建议：**保持默认 BTST 基线不变，优先推进 continuation 专用 execution 实验与弱确认 re-entry 抑制**
