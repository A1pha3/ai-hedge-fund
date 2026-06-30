# 1. 核心筛选流水线

> 本节对应主文档 §1,包含 Layer A 候选池筛选、Layer B 四策略评分、信号融合与冲突仲裁、市场状态检测。

## 1.1 全市场快筛 (Layer A 候选池)

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 全 A 股扫描 (~5000 只) | ✅ | `src/screening/candidate_pool.py` — 自动获取全市场股票列表 |
| 2 | ST/*ST 排除 | ✅ | 名称包含 ST 的标的自动排除 |
| 3 | 北交所排除 | ✅ | BJ 市场 / 4xxxxx / 8xxxxx / 92xxxx 排除 |
| 4 | 次新股排除 (<60 交易日) | ✅ | 上市不满 60 个交易日自动排除 |
| 5 | 停牌标的排除 | ✅ | 当日停牌标的排除 |
| 6 | 涨停标的排除 | ✅ | 当日涨停标的排除(买入排队失败) |
| 7 | 长期停牌复牌标的排除 | ✅ | 停牌超 5 日后复牌未满 3 个交易日排除 |
| 8 | 低流动性排除 (<5000 万) | ✅ | 近 20 日均成交额 <5000 万排除 |
| 9 | 冷却期标的排除 (15 日) | ✅ | 冲突仲裁标记的回避冷却期标的排除 |
| 10 | Shadow 影子池 | ✅ | 低流动性边界候选保留为影子池，用于扩展观察 |

## 1.2 四策略评分 (Layer B)

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 趋势策略评分 | ✅ | `src/screening/strategy_scorer_trend.py` — 趋势跟踪+动量因子 |
| 2 | 均值回归策略评分 | ✅ | `src/screening/strategy_scorer_mean_reversion.py` — 动量延续+反转因子 (NS-4 commit 023acd74 翻转: 短期 momentum 主导) |
| 3 | 基本面策略评分 | ✅ | `src/screening/strategy_scorer_fundamental.py` — 估值+财务质量因子 |
| 4 | 事件情绪策略评分 | ✅ | `src/screening/strategy_scorer.py` — 新闻情绪+龙虎榜+资金流 |
| 5 | 子因子聚合框架 | ✅ | SubFactor 标准三元组 (direction, confidence, completeness) |
| 6 | 数据完整度感知 | ✅ | completeness 指标自动降权不完整数据 |

## 1.3 信号融合与冲突仲裁 (Layer B → Layer C)

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 加权融合评分 (score_b) | ✅ | `src/screening/signal_fusion.py` — 四策略加权融合 |
| 2 | 市场状态自适应权重 | ✅ | trend/range/mixed/crisis 四状态动态调权 |
| 3 | Hurst 指数冲突解决 | ✅ | 趋势/反转信号冲突时的 Hurst 仲裁 |
| 4 | 强制回避仲裁 | ✅ | 极端信号自动触发回避标记 |
| 5 | 质量优先守卫 | ✅ | `LAYER_B_ANALYSIS_QUALITY_FIRST_GUARD` 防止低质量信号通过 |
| 6 | 行业集中度检查 | ✅ | Top N 推荐中同一行业占比超 40% 自动预警 |

## 1.4 市场状态检测

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | ADX 趋势强度 | ✅ | `src/screening/market_state.py` |
| 2 | ATR 价格波动率 | ✅ | 波动率异常检测 |
| 3 | 市场宽度 (涨跌比) | ✅ | 全市场涨跌家数比 |
| 4 | 北向资金连续流入/流出 | ✅ | 连续流入/流出天数统计 |
| 5 | 涨跌停数量 | ✅ | 极端市场信号 |
| 6 | 仓位系数 (position_scale) | ✅ | 根据市场状态动态调整建议仓位 |
| 7 | Regime Gate 级别 | ✅ | normal/caution/halt/shadow_only 四级门控 |

---

**相关章节**: [2. 执行系统](./execution-system.md) | [6. 数据基础设施](./data-infrastructure.md)
