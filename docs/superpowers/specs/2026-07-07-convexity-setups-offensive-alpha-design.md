# 凸性 Setup 检测器设计文档（进攻型 Alpha 系统）

**日期**: 2026-07-07
**状态**: 设计稿（待 owner 审阅 → 实施计划）
**作者**: owner + Claude（brainstorming 5 轮收敛）
**关联契约**: `docs/cn/product/autodev-contract.md`（本设计扩展北极星，不推翻）
**关联记忆**: `[[project_btst_optimization_20260415]]` / `[[project_btst_ic_analysis]]` / `[[historical-backtest-before-waiting-future-data-20260629]]`

---

## 0. TL;DR

把"打分器"（composite_score / alpha_score / 收益预测器）范式升级为**"凸性 setup 检测器"**：扫描全市场，检测已知的有利 setup 模式（涨停突破、超跌反弹、板块轮动早期、龙虎榜共振、催化首日），对每个命中回溯其历史 T+5/T+10 **条件分布**（不是均值），按凸性比（asymmetric payoff）排序，Kelly 仓位。

**新前门 `--top-setups` 与现有 `--top-picks`（防守）平行共存**，独立候选池、独立信号、独立 gate、独立目标。`--top-picks` 一行代码不改。

---

## 1. 背景与第一性动机

### 1.1 现有系统的本质：线性打分器

当前 `--top-picks` 流水线：

```
4 策略 (trend/MR/fundamental/event) → composite_score → BUY gate → 排序 → Top-N
```

`composite_score` 是一个 **0-1 质地分**，由人工设权的因子线性组合。它是一个**打分器/分类器**，不是一个**收益预测器**，更不是一个**凸性检测器**。

### 1.2 现有系统在高收益目标下的三个失败模式

| 失败 | 表现 | 根因 |
|------|------|------|
| 池内无排序力 | R6 选择偏差伪象；排序单调性倒挂（低60%→高45%） | 线性打分器不为"预测收益"设计，池内无信号 |
| 危机失能 | crisis regime → 0 BUY | gate 设计目标是"避免亏损"，危机下正确清空，但进攻需求无法满足 |
| 催化剂盲区 | event_sentiment 系统性 = 0；消息/资金/情绪信号缺失 | 现有 4 策略 75% 权重在滞后因子（趋势+基本面） |

### 1.3 第一性推导（5 轮 brainstorming 收敛路径）

1. **资金面塞进 composite** → 被 75% 滞后因子稀释成噪声
2. **两阶段（composite 筛选 + alpha 排序）** → 危机下阶段 1 清空，阶段 2 无米
3. **两系统（防守 D + 进攻 O 独立）** → 仍是打分器范式，O 的 alpha_score 不是收益预测器
4. **收益预测器（IC 加权线性多因子）** → 假设收益是线性 + 正态，**压扁了凸性**
5. **凸性 setup 检测器**（本设计）→ 直接用条件分布，捕捉不对称收益

### 1.4 核心第一性洞察

> **A 股短期（T+5/T+10）收益分布是非对称的（凸性/肥尾），不是正态的。**
>
> 线性因子模型（composite / 收益预测器）把凸性机会压扁成均值，丢掉了"小亏大赚"的不对称结构 —— 而这恰恰是"高收益"的本质。
>
> A 股短期 alpha 的来源是**行为偏差造成的可预测不对称**：散户追涨停板、踩板块轮动、恐慌割肉 —— 这些行为系统性制造凸性机会。只有"setup + 条件分布"框架能系统捕捉。

**典型凸性分布示例**（涨停首板突破后 5 天）：

```
60% 概率 +20%~+30% (连板续涨)
40% 概率 -5%~-10%  (炸板回落)

E[收益] = +8% (均值)
但分布是双峰的, 凸性比 = (avg_gain × winrate) / (|avg_loss| × lossrate) = (25%×0.6)/(7.5%×0.4) = 5.0
```

线性预测器会把这只票输出为"+8%"，和一只"90%概率+9%/10%概率-1%"的高方差防守票混淆（两者 E[收益] 接近）。凸性检测器直接用分布形状区分，凸性比 5.0 的票优先级远高于凸性比 1.0 的票。

---

## 2. 核心概念：凸性 Setup（Convexity Setup）

### 2.1 定义

**凸性 setup** = 一个可识别的市场模式 P，配一个历史条件分布 D(P)：

- **触发条件** `trigger(P)`: 可计算的布尔/数值规则（例如"今日涨停 + 主力净流入 > 均值+2σ + 所属行业当日涨幅 > 2%"）
- **历史分布** `D(P, horizon, regime)`: 在历史数据上，所有满足 trigger(P) 的样本在 T+5/T+10 的收益分布（胜率 / 均赚 / 均亏 / 凸性比 / 样本量 n）
- **适用 regime**: setup 可能 regime 相关（超跌反弹在 crisis 强，板块轮动在 normal 强）

### 2.2 凸性比（Convexity Ratio）

```
convexity_ratio(P) = (avg_gain × winrate) / (|avg_loss| × lossrate)
```

- `convexity_ratio > 1`: 正凸性（小亏大赚）—— 进攻目标想要的
- `convexity_ratio ≈ 1`: 对称（标准赌博）
- `convexity_ratio < 1`: 负凸性（大亏小赚）—— 避免

**准入门槛**（Phase 0 验证标准）：`convexity_ratio ≥ 1.5 AND winrate ≥ 50% AND n ≥ 30`。

### 2.3 与"因子"的区别

| 维度 | 因子（factor） | Setup |
|------|---------------|-------|
| 形式 | 数值 z-score | 布尔触发 + 分布 |
| 输出 | "高强度" / "低强度" | "命中" / "未命中" + 历史分布 |
| 组合方式 | 线性加权 | 多 setup 标签 + 凸性加权 |
| 数据需求 | 全市场打分 | 仅命中样本的分布回溯 |
| 可解释性 | "trend 强度 0.8" | "涨停突破 setup, 历史 60%/+25%" |
| 捕捉凸性 | ❌ | ✅ |

---

## 3. 候选 Setup 清单（Phase 0 待回测验证）

按数据完整度 + 文献支撑排序。Phase 0 必须验证每个 setup 的历史分布，不达标的淘汰。

### 3.1 核心 setup（数据完整，优先回测）

#### Setup-1: 涨停首板/连板突破（BTST-Convex）
- **触发**: `今日涨停 AND 主力净流入 > 阈值 AND 所属行业当日涨幅 > X%`
- **变体**: 首板（前 5 日未涨停）/ 2 连板 / 3+ 连板（分布不同，分开回测）
- **数据**: akshare `stock_zh_a_spot` + 涨跌停 + `stock_individual_fund_flow` + 行业指数
- **资产**: `[[project_btst_optimization_20260415]]` 已回测 53% 胜率（全样本），本设计按"首板/连板"分层重测
- **预期分布**: 60% +20%, 40% -8%（基于 BTST 历史）
- **风险**: 涨停策略拥挤度高，IC 可能衰减；需要监控

#### Setup-2: 超跌反弹 + 资金回流（Oversold-Bounce）
- **触发**: `近 30 日跌幅 > 20% AND 近 3 日主力净流入转正 AND 今日量比 > 1.5`
- **数据**: 现有价格数据 + 新增 `stock_individual_fund_flow`
- **预期分布**: 55% +15%, 45% -8%
- **Regime 偏好**: crisis / risk_off 下强（恐慌底反转）
- **价值**: **危机专属 setup** —— 直接填补"危机 0 BUY"的痛

#### Setup-3: 板块轮动早期（Sector-Rotation-Early）
- **触发**: `行业指数 2 日涨幅 > 3% AND 行业龙头未涨（<行业涨幅×0.5）AND 行业资金净流入 > 阈值`
- **数据**: 现有 `industry_rotation` 信号 + 行业指数 + 新增资金流聚合
- **预期分布**: 50% +25%, 50% -3%
- **Regime 偏好**: normal / cautious 下强
- **资产**: `industry_rotation` 已有，需深化"龙头未动"检测

#### Setup-4: 龙虎榜机构/游资共振（LHB-Confluence）
- **触发**: `今日上榜龙虎榜 AND 机构席位买入 > 0 AND 主力净流入 > 阈值`
- **数据**: akshare `stock_lhb_*`（未接入，需新增）
- **预期分布**: 55% +12%, 45% -5%
- **风险**: 数据稀疏（仅上榜日有），需聚合

#### Setup-5: 政策/事件催化首日（Catalyst-Day-1）
- **触发**: `news_sentiment 利好标签 AND 所属板块齐涨（≥3 只同板块票涨幅>3%）AND 龙头涨停`
- **数据**: news 抓取需修复（当前 event_sentiment=0 盲区）+ 板块齐涨检测
- **预期分布**: 60% +18%, 40% -6%
- **依赖**: 必须先修复 news 抓取覆盖率（autodev-13 loop 100/101 修了日期，覆盖率是遗留问题）

### 3.2 候选 setup（Phase 0 验证后再决定是否纳入）

- **Setup-6**: 缩量回调到支撑位（趋势中继，低凸性但高胜率）
- **Setup-7**: 北向资金连续 5 日流入（蓝筹偏好，可能偏防守）
- **Setup-8**: 大单突破 + 量价齐升（资金面纯技术）

### 3.3 Setup 准入门槛

Phase 0 普查后，每个 setup 必须满足：
- `convexity_ratio ≥ 1.5`（凸性够强）
- `winrate ≥ 50%`（不能纯靠赔率）
- `n ≥ 30`（样本足够）
- `IC > 0.05`（信号方向正确）
- regime 分层后至少一个 regime 仍达标

**不达标的 setup 淘汰，不进 Phase 1。** 这是 [[historical-backtest-before-waiting-future-data-20260629]] 原则的硬约束 —— 没 alpha 就不做。

---

## 4. 架构设计

### 4.1 总体架构（与现有系统平行）

```
┌─────────────────────────────────────────────────────────────────┐
│                       数据层 (共享)                              │
│  akshare/tushare + cache: 价格/资金流/龙虎榜/行业/news           │
└────────────┬────────────────────────────────────┬───────────────┘
             │                                    │
             ▼                                    ▼
┌────────────────────────────┐   ┌─────────────────────────────────┐
│  现有防守系统 (System D)    │   │  新进攻系统 (System O)           │
│  --top-picks               │   │  --top-setups                   │
│                            │   │                                 │
│  composite_score           │   │  setup_detector                 │
│  → BUY gate                │   │  → distribution_lookup          │
│  → rank by composite       │   │  → convexity_filter             │
│  → BUY/HOLD/AVOID          │   │  → rank by convexity_ratio      │
│                            │   │  → Kelly sizing                 │
│  目标: 不亏                │   │  目标: 最赚                     │
└─────────────────────────────┘   └─────────────────────────────────┘
             │                                    │
             ▼                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  共享: backtester / recommendation_tracker / --reconcile 对账   │
└─────────────────────────────────────────────────────────────────┘
```

**两个系统完全独立**：独立候选池、独立信号、独立 gate、独立排序、独立前门。共享的只有数据层和对账基础设施。

### 4.2 System O 流水线（`--top-setups`）

```python
def run_top_setups(trade_date, top_n=10):
    # 1. 候选池（进攻池，不过 composite/regime gate）
    pool = build_offensive_pool(trade_date)
    # 过滤: 流动性足 + 非 ST + 非北交所 + 上市>60日 + 今日成交额>阈值

    # 2. Setup 检测（每个票扫描所有已注册 setup）
    hits = []  # [(ticker, setup_id, trigger_strength), ...]
    for ticker in pool:
        for setup in REGISTERED_SETUPS:
            result = setup.detect(ticker, trade_date)
            if result.hit:
                hits.append((ticker, setup.id, result))

    # 3. 分布查询（每个命中查历史分布 + regime 条件）
    enriched = []
    for ticker, setup_id, trig in hits:
        dist = distribution_store.lookup(setup_id, horizon=5, regime=current_regime)
        enriched.append({
            "ticker": ticker,
            "setup_id": setup_id,
            "winrate": dist.winrate,
            "avg_gain": dist.avg_gain,
            "avg_loss": dist.avg_loss,
            "convexity_ratio": dist.convexity_ratio,
            "e_return": dist.expected_return,
            "n_samples": dist.n,
            "ci_low": dist.ci_low, "ci_high": dist.ci_high,
            "trigger_strength": trig.strength,
        })

    # 4. 凸性过滤（准入门槛）
    qualified = [h for h in enriched
                 if h["convexity_ratio"] >= 1.5
                 and h["winrate"] >= 0.50
                 and h["n_samples"] >= 30]

    # 5. 排序（凸性比 × E[收益] 加权，可选 trigger_strength 调整）
    qualified.sort(key=lambda h: h["convexity_ratio"] * h["e_return"], reverse=True)

    # 6. 去重 + 多 setup 融合（同一票命中多个 setup, 取最强 + 标注共振）
    fused = fuse_multi_setup_hits(qualified)

    # 7. Kelly 仓位建议
    for h in fused:
        h["kelly_pct"] = kelly_fraction(h["winrate"], h["avg_gain"], h["avg_loss"])

    # 8. 输出 Top-N
    return fused[:top_n]
```

### 4.3 关键模块

| 模块 | 位置 | 职责 |
|------|------|------|
| `offensive_pool_builder` | `src/screening/offensive/pool.py` | 构建进攻候选池（流动性/ST/上市天数过滤） |
| `setup_base` | `src/screening/offensive/setups/base.py` | Setup 抽象基类（detect + metadata 接口） |
| `setup_registry` | `src/screening/offensive/setups/registry.py` | Setup 注册表（启用/禁用/版本管理） |
| `setup_btst_breakout` | `src/screening/offensive/setups/btst_breakout.py` | Setup-1 实现 |
| `setup_oversold_bounce` | `src/screening/offensive/setups/oversold_bounce.py` | Setup-2 实现 |
| `setup_sector_rotation` | `src/screening/offensive/setups/sector_rotation.py` | Setup-3 实现 |
| `setup_lhb_confluence` | `src/screening/offensive/setups/lhb_confluence.py` | Setup-4 实现 |
| `setup_catalyst_day1` | `src/screening/offensive/setups/catalyst_day1.py` | Setup-5 实现 |
| `distribution_store` | `src/screening/offensive/distribution_store.py` | 历史 setup 分布存储 + 查询（regime/horizon 分层） |
| `distribution_builder` | `src/screening/offensive/distribution_builder.py` | 从历史数据回测构建分布（Phase 0 工具） |
| `convexity_filter` | `src/screening/offensive/convexity.py` | 凸性比计算 + 准入过滤 |
| `kelly_sizer` | `src/screening/offensive/kelly.py` | Kelly 仓位建议（含上限/分散约束） |
| `setup_fusion` | `src/screening/offensive/fusion.py` | 多 setup 命中融合 + 共振标注 |
| `run_top_setups` | `src/main.py`（新命令分发） | `--top-setups` CLI 入口 |
| `setup_research_cli` | `scripts/setup_research.py` | Phase 0 研究工具（回测 setup 分布） |

### 4.4 数据流

```
每日 --auto 跑完后:
  1. 主力资金流数据落盘 (akshare stock_individual_fund_flow, 全市场)
  2. 龙虎榜数据落盘 (akshare stock_lhb_*, 当日上榜)
  3. 行业指数 + 板块齐涨检测 (复用现有 industry_rotation)
  4. 涨跌停数据 (现有 candidate_pool 已有)

--top-setups 触发时:
  5. 加载当日数据 → build_offensive_pool → setup_detector → distribution_lookup → 排序 → 输出
```

### 4.5 与现有系统的集成点

| 集成点 | 方式 | 影响 |
|--------|------|------|
| `--top-picks` | 不修改 | 防守系统完全保留 |
| `recommendation_tracker` | System O 也写入 tracker（标记 source="setup"） | `--reconcile` 可对账两套 |
| `backtester` | 复用 + 扩展（加 setup 回测模式） | 不破坏现有回测 |
| `autodev-contract.md` | 加章节"进攻模式 --top-setups" | 扩展北极星，不推翻 |
| `regime gate` | System O **不**用 regime gate 过滤（但分布查询按 regime 分层） | 危机也能出票 |
| `BUY gate` | System O **不**用 BUY gate | 用凸性门槛代替 |

---

## 5. 数据源

### 5.1 新增数据源

| 数据 | 源 | 接口 | 频率 | 状态 |
|------|-----|------|------|------|
| 主力资金流（每日） | akshare | `stock_individual_fund_flow` | 日 | 待接入 |
| 龙虎榜 | akshare | `stock_lhb_detail_em` / `stock_lhb_stock_detail_em` | 日（有上榜才更新） | 待接入 |
| 北向资金（个股持仓） | akshare | `stock_hsgt_individual_detail` | 日 | 待接入（Setup-7 用） |
| 涨跌停名单 | akshare | 现有 candidate_pool 已含 | 日 | 已有 |

### 5.2 现有数据复用

- 价格/OHLCV: `src/tools/akshare_api.py`
- 行业指数/轮动: `src/screening/industry_rotation.py`
- 候选池基础过滤: `src/screening/candidate_pool.py`
- BTST 涨停股研究: `[[project_btst_*]]` 系列记忆 + 现有 BTST 代码
- recommendation_tracker: `src/screening/recommendation_tracker.py`

### 5.3 News 抓取修复（前置依赖）

Setup-5（催化首日）依赖 news 抓取。当前 `event_sentiment` 系统性 = 0，根因：
- akshare `stock_news_em` 接口覆盖率不足 / 偶发失败
- 日期解析已修（loop 101），但抓取量本身低

**修复方向**（Phase 0 子任务）：
- 评估 akshare news 接口实际返回量
- 考虑补充数据源（东方财富网页爬取 / tushare news）
- 这一步如果失败，Setup-5 推迟到 Phase 3

---

## 6. 成功标准（可量化）

### 6.1 Phase 0 成功标准（Setup 普查）

至少 **3 个 setup** 同时满足：
- `convexity_ratio ≥ 1.5`
- `winrate ≥ 50%`
- `n_samples ≥ 30`
- `IC > 0.05`（setup 命中 vs 全市场基线）
- regime 分层后至少一个 regime 仍达标

**若不达标**: STOP。说明"凸性 setup 在当前数据下没有足够 alpha"，不进 Phase 1。这是硬约束。

### 6.2 Phase 1 成功标准（上线 + shadow）

`--top-setups` shadow 跑 ≥ 2 周（10 个交易日）后：
- Setup 命中票的实际 T+5/T+10 收益分布与历史分布**一致**（KS 检验 p > 0.05，或均值在 CI 内）
- `--top-setups` Top-5 的实际 T+5 平均收益 **> `--top-picks` Top-5** 的实际 T+5 平均收益
- 凸性比预测与实际一致（实际凸性比 ≥ 1.0，未崩塌）

### 6.3 Phase 2 成功标准（仓位优化）

Kelly 仓位建议的组合：
- T+5 累积收益 > 等权 Top-N 组合
- 最大回撤 ≤ 等权组合 × 1.2（凸性应控制下行）
- Sharpe > 等权组合

### 6.4 长期北极星扩展（契约层）

契约 `autodev-contract.md` 北极星从：
> 让用户用尽可能少的入口，稳定找到未来 T+5 或 T+10 天**更值得买入**的 A 股标的

扩展为：
> 让用户用尽可能少的入口，稳定找到未来 T+5 或 T+10 天**更值得买入**的 A 股标的（防守，`--top-picks`）；
> **并在市场出现凸性机会时，识别"小亏大赚"的高期望 setup**（进攻，`--top-setups`）。

两个目标，两个前门，各管各的。

---

## 7. 风险与缓解

| 风险 | 严重度 | 缓解 |
|------|--------|------|
| **Setup IC 衰减**（策略拥挤） | 高 | 每月重测分布；IC 衰减 > 30% 的 setup 降权或淘汰；持续研究新 setup |
| **过拟合**（触发规则调到历史最优） | 高 | Walk-forward 回测；触发规则保持简单（≤5 个条件）；out-of-sample 验证 |
| **Regime shift**（setup 在新 regime 失效） | 高 | Regime 分层分布查询；IC 监控；crisis/normal 都要验证 |
| **凸性变方差**（高凸性 = 高方差，可能连续亏损） | 中 | Kelly 仓位上限（单 setup ≤ 10%）；多 setup 分散；最大同时持仓数 |
| **数据缺失**（龙虎榜稀疏 / news 盲区） | 中 | 数据完整的 setup 优先（资金流 + 价格）；稀疏 setup 标注 n 不足时禁用 |
| **操作者误用**（把 --top-setups 当必买清单） | 中 | 每只票显示分布 + CI + "历史非未来" disclaimer；不推送，仅按需查询 |
| **与防守系统冲突**（同一只票 --top-picks AVOID 但 --top-setups 命中） | 低 | 这是 feature 不是 bug：明确标注"进攻 setup vs 防守 gate 冲突"，操作者自决 |
| **回测样本不足**（n < 30） | 中 | 不达标 setup 不上线；持续累积数据；标注样本量 |

---

## 8. 实施路线图（高层，详细计划见后续 writing-plans）

### Phase 0: Setup 研究与验证（2-3 周，纯研究）

**目标**: 验证凸性 setup 在 A 股当前数据下有足够 alpha。**不写 live 代码。**

- 0.1 主力资金流数据接入 + 历史 backfill（2-3 年）
- 0.2 龙虎榜数据接入 + 历史 backfill
- 0.3 Setup 分布回测框架（`scripts/setup_research.py`）
- 0.4 逐 setup 回测（Setup-1 到 Setup-5），输出分布报告
- 0.5 准入决策：≥3 个 setup 达标 → 进 Phase 1；否则 STOP

**决策点**: Phase 0 结束时，owner 审阅分布报告，决定是否进 Phase 1。

### Phase 1: 检测器上线 + Shadow（1-2 周）

**目标**: `--top-setups` 命令上线，shadow 跑 ≥ 2 周。

- 1.1 Setup 抽象 + 注册表 + 检测框架
- 1.2 达标 setup 实现（Phase 0 验证过的）
- 1.3 分布存储 + 查询（regime/horizon 分层）
- 1.4 凸性过滤 + 排序 + 渲染
- 1.5 `--top-setups` 命令分发
- 1.6 Shadow 模式：自动跑 + 落 tracker，不推送
- 1.7 Shadow 对账（与 `--top-picks` 对比 T+5/T+10）

**决策点**: Shadow 2 周后，若实际分布与历史一致 + 收益 > `--top-picks`，进 Phase 2。

### Phase 2: 仓位优化 + 组合层（1-2 周）

- 2.1 Kelly 仓位建议（含上限/分散约束）
- 2.2 多 setup 融合 + 共振标注
- 2.3 组合层（setup 分散 + 行业分散 + 风险预算）
- 2.4 `--top-setups` 完整输出（含仓位建议）

### Phase 3: 扩展 + 维护（持续）

- 3.1 News 抓取修复 → Setup-5 上线
- 3.2 新 setup 研究（Setup-6/7/8）
- 3.3 Setup IC 衰减监控 + 自动告警
- 3.4 月度 setup 重校准

---

## 9. 契约改动（待 owner 批准）

### 9.1 北极星扩展

在 `docs/cn/product/autodev-contract.md` §北极星 后追加：

```markdown
## 进攻模式（凸性 setup）

2026-07-07 扩展: 在"防守型 --top-picks"之外，新增"进攻型 --top-setups"。

- `--top-picks`（防守）: 回答"哪些不亏"。composite + BUY gate + regime gate。
- `--top-setups`（进攻）: 回答"哪些最赚"。凸性 setup 检测 + 条件分布 + Kelly 仓位。

两个前门独立，不互相过滤。操作者按当日目标选择。
危机下 --top-picks 可能 0 BUY（正确，防守），--top-setups 仍可出票
（如果危机专属 setup 如"超跌反弹+资金回流"命中）。
```

### 9.2 AutoDev 自主范围扩展

AutoDev 可自主推进（不需 owner 决策）：
- Setup 数据接入（资金流/龙虎榜）
- Setup 回测框架
- Setup 检测器实现
- Shadow 模式 + 对账

需 owner 决策：
- 准入门槛（convexity_ratio / winrate / n 的具体数值）
- Phase 0 → Phase 1 的 go/no-go
- Phase 1 → live push 的 go/no-go
- Kelly 仓位上限
- 失效 setup 淘汰

---

## 10. 开放问题（实施时再定）

- Q1: Setup 分布用全部历史，还是近 N 个月（衰减加权）？倾向后者（IC 衰减适应）。
- Q2: 多 setup 共振（同票命中多个）如何融合？倾向"最强 setup 主标 + 共振加分"。
- Q3: Kelly 仓位的无风险利率 / 单 setup 上限？倾向单 setup ≤ 10%，组合 ≤ 60%。
- Q4: 涨停 setup 的执行现实（涨停买不到）？需检测"可买入性"（开盘 / 中段 / 尾盘不同）。
- Q5: 是否接入 tushare 资金流作为 akshare 备份？倾向是（数据可靠性）。

---

## 11. 与记忆的关联

- `[[project_btst_optimization_20260415]]` — Setup-1（涨停突破）的回测基础
- `[[project_btst_ic_analysis]]` — IC 分析基础设施，Phase 0 复用
- `[[project_btst_filter_backtest_results]]` — 涨停股 53% 胜率基础数据
- `[[historical-backtest-before-waiting-future-data-20260629]]` — Phase 0 先回测的原则
- `[[r5f-phase0-state-type-stop-20260625]]` — 防守系统不动的边界（System D 保留）
- `[[composite-score-reweighting-decision-pack-c301]]` — R6 选择偏差闭环（System O 不受影响）
- `[[money-tool-positioning-20260624]]` — "最优秀赚钱工具"定位，本设计直接服务北极星

---

## 附录 A: 为什么不是 ML（XGBoost/LightGBM）？

线性 IC 加权 vs 凸性 setup 检测 vs ML，三者在 A 股短期收益预测上的权衡：

| 维度 | 线性 IC 加权 | 凸性 setup 检测（本设计） | ML（XGBoost） |
|------|-------------|--------------------------|---------------|
| 数据需求 | 中 | 低（每个 setup 独立验证） | 高（7993 记录偏少） |
| 过拟合风险 | 中 | 低（触发规则简单） | 高 |
| 可解释性 | 中（IC 权重） | 高（"涨停突破 setup"） | 低（黑盒） |
| 捕捉凸性 | ❌ | ✅ | 部分（非线性） |
| 捕捉交互 | ❌ | 部分（共振标注） | ✅ |
| 实施成本 | 低 | 中 | 高 |
| 适合阶段 | 基线 | **Phase 0-2（本设计）** | Phase 3+（如线性/setup 欠拟合再上） |

**结论**: 凸性 setup 检测在当前数据规模 + 可解释性需求 + 凸性捕捉目标下是最优起点。ML 留作 Phase 3 的扩展选项（在 setup 检测框架内，用 ML 学习"setup 触发条件的最优组合"，而非替代 setup 框架）。

---

## 附录 B: 5 轮 brainstorming 收敛轨迹（决策溯源）

| 轮次 | 方案 | 为什么被推翻 |
|------|------|-------------|
| 1 | 资金面塞进 composite（4 选项 A/B/C/D） | 被 75% 滞后因子稀释成噪声 |
| 2 | 两阶段（composite 筛选 + alpha 排序） | 危机下阶段 1 清空，阶段 2 无米 |
| 3 | 两系统（防守 D + 进攻 O 独立打分） | 仍是打分器范式，不是收益预测器 |
| 4 | 收益预测器（IC 加权线性多因子） | 假设线性 + 正态，压扁凸性 |
| 5 | **凸性 setup 检测器**（本设计） | — |

每轮推翻都指向更深的第一性：**A 股短期收益是非对称的，必须用分布/setup 的语言，不能用打分/线性预测的语言。**

---

**审阅请求**: 请 owner 审阅本设计文档。审阅通过后，我会进入 writing-plans 阶段，把 Phase 0 拆成可执行的步骤计划。
