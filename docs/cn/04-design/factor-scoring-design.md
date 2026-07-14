---
难度: ⭐⭐⭐⭐
类型: 专家设计
预计时间: 20 分钟
前置知识:
  - [设计原则与权衡](principles.md) ⭐⭐⭐⭐
  - [候选池设计](candidate-pool-design.md) ⭐⭐⭐
---

# 因子评分设计

因子评分是 `--auto` 的 Layer B → Layer C 流程：四策略子因子打分 → score_b 融合 → Hurst 仲裁 → investability 排序。本文档讲清楚每一步的实现、关键常量、修复案例，以及为什么 `composite_score` 排序模式默认关闭。

## 四策略与子因子

`strategy_scorer.py` 是 Layer B 的入口，四策略在 `STRATEGY_KEYS` 中固定：

```python
# custom_weights.py
STRATEGY_KEYS: tuple[str, ...] = (
    "trend",
    "mean_reversion",
    "fundamental",
    "event_sentiment",
)
```

`score_batch` 用两阶段评分控制成本：

1. **Light 阶段**：所有候选都跑 `trend` + `mean_reversion`（纯技术，便宜），按 `_provisional_score` 排序。
2. **Heavy 阶段**：Top-N（`FUNDAMENTAL_SCORE_MAX_CANDIDATES ≈ 141`、`EVENT_SENTIMENT_MAX_CANDIDATES ≈ 60`）才跑 `fundamental`（要财务指标）和 `event_sentiment`（要新闻 + 龙虎榜）。

`LIGHT_STRATEGY_WEIGHTS` 是 light 阶段的固定权重：

```python
# strategy_scorer.py
LIGHT_STRATEGY_WEIGHTS = {
    "trend": 0.65,
    "mean_reversion": 0.35,
}
```

`trend:0.65 / MR:0.35` 不是拍脑袋，是 C226 revert 的结论。注释里写明：

> 全 universe 因子回测 (2026-06-25, n=8136) 证明 MR 是正向有效因子
> C226 revert: 全 universe 诊断 (C225 n=8901) 证实 MR 全 4 sub-factor 与 T+1 反向
> (sep<0, IC=-0.128); MR-heavy (0.65) 在更长样本下跑输 trend-heavy (daily excess -0.28%)
> mean-reversion bet 在 T+1 horizon 失败 (短期 momentum 主导). 回滚到 trend:0.65/MR:0.35

这条权重历史是：MR 反向（推荐池诊断）→ 全 universe 诊断发现 MR 正向 → 提到 0.65 → 更长样本显示 T+1 horizon 上 MR 仍然反向 → 回滚到 0.35。

## score_b 融合

`signal_fusion.py::compute_score_b` 是融合公式：

```python
def compute_score_b(signals: dict[str, StrategySignal], weights: dict[str, float], arbitration_applied: list[str]) -> float:
    normalized_weights = _normalize_for_available_signals(weights, signals)
    from src.screening.models import STRATEGY_DIRECTION_MULTIPLIER

    score = 0.0
    for name, signal in signals.items():
        weight = normalized_weights.get(name, 0.0)
        multiplier = STRATEGY_DIRECTION_MULTIPLIER.get(name, 1.0)
        score += weight * signal.direction * multiplier * (signal.confidence / 100.0) * signal.completeness

    if ArbitrationAction.CONSENSUS_BONUS.value in arbitration_applied:
        if score > 0:
            bonus = 0.05
        elif score < 0:
            bonus = -0.05
        else:
            bonus = 0.0
        score = score + bonus
    return max(-1.0, min(1.0, score))
```

公式：`score_b = Σ(weight × direction × multiplier × confidence/100 × completeness) + consensus_bonus`，clamp 到 [-1, +1]。

- `direction ∈ {-1, 0, +1}`：策略方向。
- `confidence ∈ [0, 100]`：置信度。
- `completeness ∈ [0, 1]`：数据完整度，缺失数据降权。
- `STRATEGY_DIRECTION_MULTIPLIER`：A 股动量市场里 MR 信号方向在 generator 层翻转对齐 T+1，`multiplier=1.0` 不再反转（见 `models.py` 注释）。
- `consensus_bonus`：≥3 个策略同向且 confidence > 60 时加 ±0.05（GAMMA-016 修复：方向跟随共识，不是固定 +0.05）。

## gate 与 ranking 解耦（C232 NS-11）

`compute_score_decomposition` 把 score_b 拆解，让 gate 用 `base_sum`、ranking 用 `total`：

```python
components_sum = base_sum + consensus_bonus
other_adjustments = float(fused.score_b) - components_sum
```

`attention_composite` 和 `stability_bonus` 是元数据，不进 `components_sum`。如果让它们进 sum，`other_adjustments` 会被迫承担虚假 offset（如 stability_bonus=10.0 会让 other=-10.0 来"抵消"）。

这条修复的背景：旧实现 ranking 和 gate 共用一个 score 字段，bonus 会跨域污染 gate 阈值判断。修复后 ranking 用 boosted score（含 bonus tie-breaker），gate 用 pre-bonus score（真实质量）。

## Hurst 仲裁

`apply_hurst_conflict_resolution` 在 `signal_fusion_arbitration_helpers.py` 里。Hurst 指数判断趋势持续性：

- `H > 0.5`：趋势持续，trend 信号优先。
- `H < 0.5`：均值回归，MR 信号优先。
- `H ≈ 0.5`：随机游走，两信号都不强。

当 trend 和 MR 信号冲突（一个 +1 一个 -1），Hurst 决定哪个胜出。这条仲裁写在 `arbitration_applied` 列表里，供 debug 时追溯。

## IC 监控与因子诊断

`known_distributions.py` 里每个分布都有 `ic` 字段：

```python
BTST_BREAKOUT_T10 = Distribution(
    # ...
    ic=0.15,
)
OVERSOLD_BOUNCE_T5 = Distribution(
    # ...
    ic=0.003,  # 极低，无排序信息
)
```

IC（Information Coefficient）是 setup 信号与未来收益的 Spearman 相关。IC > 0.05 有排序信息，IC > 0.1 较强。BTST `ic=0.15` 是有效 ranker；OversoldBounce `ic=0.003` 几乎无排序信息，与 `E[r]` 统计不显著一致。

**因子诊断必须用全 universe**（详见 [设计原则与权衡](principles.md) §7）。MR 因子反转问题就是反例：推荐池诊断显示 MR 反向 → 全 universe 诊断显示 MR 正向 → 推荐池选择偏差导致误判。

## factor_attribution horizon 对齐（C231）

`investability.py::_SHORT_HORIZON_KEYS` 固定排序 horizon 为 T+5 和 T+10：

```python
_SHORT_HORIZON_KEYS: tuple[str, ...] = ("t5", "t10")
```

注释说明：

> C222 (2026-06-28 horizon 一致性): BUY gate 主决策 horizon 是 T+5 OR T+10
> (见 ``_meets_quality_bar`` line 198-207). 排序键 tie-breaker 必须与 BUY gate
> horizon 一致 — 用 max(t5, t10) 取短期 horizon 最优 metric. T+30 metric 排除出
> 排序键 (保留为 long-term invalidation 信号, 见 ``invalidation_reasons`` 字段)

修复前 factor_attribution 用 T+30 horizon，与 BUY gate 决策 horizon（T+5/T+10）不匹配。T+30-strong 的票会排在 T+5/T+10-strong 前面，但 BUY verdict 是 T+5/T+10 驱动的，导致排序与决策脱节。

## crisis regime T+5 不可靠（C245）

`investability.py` 注释提到 C245 修复：

> crisis regime T+5 不可靠: crisis/risk_off regime 下 BUY gate 仅放行 T+10 信号

回测发现 crisis/risk_off regime 下 T+5 metric 噪声大，T+5 不可靠。修复后 crisis/risk_off regime 下 BUY gate 仅放行 T+10 信号，T+5 信号被屏蔽。

## composite_score 为何默认关闭

`AGENTS.md` 提到：

> `profit_aware` 排序模式默认关闭（代码注释称 composite_score 有负预测值，但未经本环境验证）

`composite_score` 是 `base_score + momentum_bonus + sector_bonus + consistency_adj + volume_factor + trend_resonance_factor`。代码注释称它有负预测值 — 即 composite_score 高的票反而表现差。这条结论未经本环境独立验证，所以默认关闭，用 `investability` 排序作为兜底。

`investability` 排序的逻辑：`composite_score` 作为主排序键 + `max(t5, t10)` 作为 tie-breaker，但 `_SHORT_HORIZON_KEYS = ("t5", "t10")` 限制了 tie-breaker 的 horizon，避免 T+30 污染。这是工程上的保守选择：宁可少用一个有争议的排序键，也不要冒负预测值的风险。

## MR 因子反转修复案例

这是因子诊断原则的最佳案例。问题链：

1. **推荐池诊断**（n=472）：MR 全 4 sub-factor 与 T+1 反向，`IC=-0.128`。结论：MR 是反向因子，应在 score_b 里反转方向。
2. **修复 v1**：在 `STRATEGY_DIRECTION_MULTIPLIER` 里把 MR 的 multiplier 设为 -1，反转方向。同时把 `LIGHT_STRATEGY_WEIGHTS` 调到 `MR:0.65`（MR-heavy）。
3. **全 universe 诊断**（n=8901）：MR 全 4 sub-factor 与 T+1 正向，`sep>0`。推荐池诊断的反向结论是选择偏差。
4. **修复 v2（C226 revert）**：移除 MR 反转，`multiplier=1.0`；`LIGHT_STRATEGY_WEIGHTS` 回滚到 `trend:0.65 / MR:0.35`。

教训：推荐池（n=472）是从全 universe（n=8901）里按 `score_b` 排序选出的「质量均匀偏高」子集。在子集上跑因子诊断，子集的选择偏差会让 MR 看起来反向，但全 universe 上 MR 仍然正向。这条原则现在写在 `strategy_scorer.py` 注释里，作为后续因子诊断的红线。

## 已知陷阱

1. **`_normalize_for_available_signals` 的 completeness 降权**：`completeness=0` 的策略会被排除出归一化分母。如果四策略里三个 completeness=0，剩下一个会拿到 100% 权重。这是设计：避免数据缺失的策略污染 score。
2. **`consensus_bonus` 方向跟随 score 符号**（GAMMA-016）：旧实现固定 +0.05，会让 bearish consensus（score<0）的票 score 被拉向 0，弱化看空信号。修复后 bonus 跟随 score 符号。
3. **`neutral_mean_reversion` 模式**：MR 信号 direction=0 时，可通过 `LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE` env 控制是全排除（`full_exclude`）还是部分权重（`partial_mr_*`）。默认 `off`，保留 MR 完整权重。

## 与 BTST 的边界

`--daily-action` 的 BTST setup 不读 `score_b`，直扫 `price_cache` 全市场。两个系统独立运行，只共享缓存数据。`C-DUAL-SIGNAL-CONVERGENCE` 是个例外：`--daily-action` 会读 `--auto` 报告的 Top-N，标记同日也在 `--auto` Top-N 的 BTST 命中为「⭐双信号」。但 bootstrap 验证显示这个收敛子集 95% CI 跨 0（`[-7%, +28%]`），未达统计显著，只能标记事实不能宣称更优。

## 深入阅读

- [候选池设计](candidate-pool-design.md):Layer A 如何预筛全市场
- [设计原则与权衡](principles.md):§6 gate-ranking 解耦、§7 全 universe 诊断
- [三层管线架构](../03-architecture/three-layer-pipeline.md):Layer B 在管线中的位置
