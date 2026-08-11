# 两层打分机器因子词汇统一设计

> **⚠️ 已否决 (2026-08-11)** — 本 spec 的方向经独立子代理对抗审查 + 两轮无偏实验后被否决。
> 动机证据 "+3.55% vs −1.19%" 来自不同候选宇宙（混淆变量未控制），归因不成立。
> 最终方案见 `2026-08-11-trend-strategy-deweight-design.md`（化简为 trend 单因子降权）。
> 本文件保留供未来审计者了解被否决方向及否决证据，勿据此实施。

**日期**: 2026-08-11
**状态**: ⚠️ 已否决（见下方横幅）
**北极星**: 用户按推荐操作 30 天真实 P&L > 0

## 1. 背景与问题

### 1.1 两层断层（代码铁证）

系统有两层打分机器，**因子词汇零交集**：

| | Layer 1（审计器 / `scripts/factor_audit.py`） | Layer 2（组合器 / `src/screening/signal_fusion.py`） |
|---|---|---|
| 因子词汇 | board / low_vol / squeeze / volume / range | trend / mean_reversion / fundamental / event_sentiment |
| 产出 | `trigger_strength`（5 分量 0.20 等权 + energy_bonus） | `score_b`（= `recommendation_score`） |
| 用途 | **只做 gate 门槛 + kelly 缩放** | **决定排序和推荐** |

铁证：
- `recommendation_score == score_b total`（逐位相等，0.4816 == 0.4816）
- `base_contributions = {trend: 0.294, fundamental: 0.138, MR: 0.020, event: 0.029}` —— 全是 Layer 2 策略，Layer 1 因子踪影全无
- `trigger_strength` 在 `daily_action.py` 只进 `strength_factor = max(0.3, min(1.0, ts))` 的仓位缩放 + `trigger_strength_below_threshold` 门槛，**从不进入 `score_b`**
- `ORTHO/DISCRETE/CONTINUOUS` 因子词汇 ∩ `STRATEGY_KEYS` = ∅

**结论**：审计器辛苦审计、经四轮对抗审查打磨的涨停结构 alpha，没有数值化地流进决定推荐的 `score_b`。决定推荐的 `score_b` 由一套**从未受审计器管辖**的策略信号构成。

### 1.2 这解释了既有矛盾

- **纯 `score_b` 高分组合 T+10 −1.19% 跑输等权（反向）**：score_b 由未审计的 trend（追高回落）主导。
- **gated 真实 ledger +3.55%（正收益）**：trigger_strength（审计过的 alpha）做 gate 把 Layer 2 噪声挡掉。
- 正收益来自 Layer 1 的 gating，反向来自 Layer 2 主导分数。两者同炉不矛盾。

### 1.3 既有机制（非完全无知）

系统已有粗粒度"双信号收敛"（`daily_action.py:407-409`）：同时被 Layer 1 detect 和 Layer 2 score_b Top-N 选中的票，历史胜率 76% vs 66%。但收敛只是 **AND 标记**，trigger_strength 仍无数值化地流入 score_b。

## 2. 第一性原理

### 2.1 点积机器的原子真相

memory 里"点积机器 = `dot(已归一向量, 已冻结测度)`"是哲学概括。代码实际原子是：

> **`(测度谓词 s→bool) → 按特征分桶 → 桶内条件分布聚合（winrate / median / Wilson CI）`**

这是**非参数条件分布分离检验**——比线性点积更强（非参数、右偏免疫、小样本 Wilson 诚实）。正交性用 Spearman 矩阵 + 有效维度（participation ratio）。这个澄清决定性地影响方案：**局限不在原子，而在作用域**。

### 2.2 选择：扩大作用域，不换算法

原子本身经四轮对抗审查打磨，接近最优。真正缺的是让它覆盖该覆盖的范围——把 Layer 2 进 `score_b` 的策略信号纳入同一审计口径。零新算法 = 最简洁优雅。

### 2.3 否决的捷径

**tracking_history base_contributions 直接审计**：验证后发现只有 265/8258 (3.2%) 记录有 base_contributions，有 T+10 跟踪的仅 175 条，分桶每桶 ~35，**样本严重不足**，不可用。回到重算路径。

## 3. 方案 A：先审后融（已选定）

用户授权"从第一性原理选最简洁优雅安全强大健壮的"。选定**先审后融**：

- **阶段 1 审**：扩展审计器覆盖 Layer 2 策略信号，用证据淘汰反向/无区分度信号（像 weekday/streak 那样源头剔除）。
- **阶段 2 融**：审计存活的有效信号保留；把 trigger_strength 的正交维度流入 score_b，**同步从 kelly 路径去耦**（否则双重计权）。

### 3.1 审计边界（数据源可得性 × 权重贡献）

| 策略 | normal regime 权重 | 数据源 | 决策 |
|---|---|---|---|
| trend | 0.56 | price-only（scan 现成） | **审**（主嫌疑，零扩展） |
| fundamental | 0.25 | feature_store（metrics+PE） | **审**（中等扩展） |
| mean_reversion | 0.13 | price-only | **审**（零扩展） |
| event_sentiment | 0.055 | news+trades（重/稀疏） | **降级观测** |

trend+MR+fundamental 合计 **0.94 权重**，数据源可控。event 权重最小、数据最重最稀疏，且 `completeness` 机制已动态 gate（无新闻时贡献趋零）——硬审边际价值低于数据成本。**计划覆盖全部 4 策略意图，执行先拿下 0.94 权重的三个**；event 降级为"观测 completeness-gate 是否充分"。

## 4. 阶段 1 技术设计

### 4.1 特征注册（scan 扩展）

审计器现有 scan 对每个涨停候选日已有 `(ticker, date, prices_df)`。扩展：
- trend: `score_trend_strategy(prices_df, ticker=ticker)` —— 零扩展
- MR: `score_mean_reversion_strategy(prices_df)` —— 零扩展
- fundamental: `score_fundamental_strategy_from_metrics(metrics, industry_sw, industry_pe_medians)` —— 需 feature_store 加载 metrics + PE。标注：`industry_sw`（申万行业）数据缺口，实现时补；加载 IO 需缓存控 scan 耗时。

特征契约不变：研究/运行同一份生产函数。

### 4.2 分桶口径

策略信号 = `(direction, confidence, completeness)`。审 **`direction × multiplier × confidence/100`**：
- 对齐生产方向（含 MR 的 `STRATEGY_DIRECTION_MULTIPLIER` 翻转）
- 剥离 `weight`（regime 调制是下游）和 `completeness`（数据完整度非预测力）
- `completeness` 降级为**测度谓词**（只在数据完整样本上审，沿用 MEASURES 一等公民）
- 涨停候选日大多 direction=+1，分桶自然退化为按 confidence 测"多头确信度区分度"，退化方向正确

### 4.3 交互审计（二维联合分桶）

聚焦 **Layer 2 三策略彼此间**（它们共同进 score_b，是真正的组合器，从未被审过交互）。不审 Layer1×Layer2 跨层（阶段 2 融合才相关）。

做法：复用 `correlation_report` 的 Spearman 矩阵预筛高相关对，只对 |ρ| > 阈值的对做二维联合分桶，避免 25 桶爆炸。

### 4.4 判据

完全复用 `_agg_returns` / `_verdict` / Wilson 非重叠 + median 分离 + 跨窗同向 + exec 测度。Wilson 不分离或 median 反向的策略 → 从 `STRATEGY_KEYS` 移出，并在 `STRATEGY_DIRECTION_MULTIPLIER` / 权重配置留痕。

## 5. 阶段 2 框架（细节待阶段 1 证据）

### 5.1 融合的两种候选形式

- **加性**：trigger_strength 正交分量作为 score_b 一项加性贡献。难点：量纲（[0,1] vs [-1,+1]）映射，不扰动 `_MIN_TRIGGER_STRENGTH` 刻度。
- **乘性**：trigger_strength 作为 score_b 的连续置信度调制 `final = score_b × g(trigger_strength)`。把硬 gate（threshold）升级为连续 gate——更轻量，但仍不把 alpha 作为独立因子注入排序。

由阶段 1 证据 + A/B 裁决。

### 5.2 kelly 去耦（硬约束）

现 `strength_factor = max(0.3, min(1.0, trigger_strength))` 用于 kelly 缩放。trigger_strength 一旦进 score_b，kelly 必须改用正交来源（纯 score_b，或 trigger_strength 另一分量），否则双重计权（Q6 教训）。去耦点由 **trigger_strength 分量的既有正交性审计**（`correlation_report` 的 ORTHO_FEATURES 矩阵已覆盖 board/low_vol/squeeze/volume/range 两两 Spearman + 有效维度）支持——选一个与将流入 score_b 的分量正交的来源做 kelly。无需阶段 1 新增 Layer1 内部交互审计（与 §4.3 范围一致）。

### 5.3 A/B 兜底

A = 现行 score_b；B = 融合 + kelly 去耦。判据：B 池内 rank IC 优于 A **且** 分桶单调性改善（Q5 高分不再反向）才落地；否则保留 A，阶段 1 审计仍有独立价值。

## 6. 验收标准

- **阶段 1**：3 策略各产出 verdict（Wilson 分离 + 跨窗同向 + median 方向），明确"留 / 移出"。empirical dogfood（真实数据），不只静态审计。
- **阶段 2（若执行）**：rank IC ≥ 现行 + 分桶单调性改善（Q5 转正）+ 不退化 btst/offensive 现有套件。

## 7. 测试策略

- 回归基线：复用 btst 25 + offensive 3441。
- 阶段 1 新增：3 策略审计锚定测试（verdict 方向 + Wilson 计算）+ 二维交互守卫。
- 阶段 2 新增：融合 A/B 锚定 + kelly 去耦的双重计权守卫。

## 8. 风险与对策

1. fundamental 数据加载拖慢 scan → 缓存 + 批量
2. 审计结论 regime 依赖 → 已有跨窗同向 + 时间块 split-half
3. 全 universe 口径与生产决策域差异 → 解读时标注，阶段 2 用池内 A/B 校准
4. 融合可能不改善 → A/B 兜底，不改善不落地
5. 双重计权 → 去耦硬约束 + 守卫

## 9. 交付边界

**阶段 1 完整定死，阶段 2 画框架**。理由：阶段 2 融合形式由阶段 1 证据驱动，预先定死违背"先审后融"。阶段 1 是确定能做对的、高价值的（Layer 2 首次受审），先做扎实。

## 10. 关键事实附录

- `score_b = clamp(Σ w·direction·multiplier·(confidence/100)·completeness + consensus_bonus, -1, +1)`（`signal_fusion.py:359-385`）
- Layer 2 信号是**数值计算**非 LLM（`strategy_scorer_trend.py` 等）
- tracking_history base_contributions 覆盖率 3.2%（捷径不可用）
- 审计器经四轮对抗审查（`dfaf2170` → `f7961f2b` → `43533e3b` → `e6c03caf`），累计修 5 真缺陷
