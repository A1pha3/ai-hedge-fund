# 机构级多策略量化交易决策框架

> **版本**：v1.0.0  
> **日期**：2026-03-04  
> **角色**：多策略量化研究总监 + 首席风控官（A股）  
> **目标函数**：最大化风险调整后收益（Sharpe / Sortino），而非单次命中率  
> **约束域**：T+1、涨跌停(±10%/±20%/±30%)、A股手续费(万2.5+千1印花税)、滑点、停牌、流动性  
> **上游文档**：[stock_selection_mvp_design_v0.md](stock_selection_mvp_design_v0.md)

---

## 0. 执行摘要

本框架将 v0 版"分层筛选+多因子评分"MVP 升级为**机构级可风控可回测**体系。核心变化：

| 维度 | v0 | v1（本文） |
|------|-----|-----------|
| 目标函数 | 隐式（降追高） | 显式：最大化 Sortino Ratio，组合级 MDD ≤ 15% |
| 策略覆盖 | 5因子评分 | 4类策略并行 + 跨策略信号融合 |
| 风控 | 护栏参数 | 硬约束矩阵 + 失效条件 + 参数敏感性备案 |
| 入场 | T+1确认 | T+1确认 + 流动性验证 + 涨跌停前置过滤 |
| 退出 | 硬止损/软止盈 | 多层退出级联（硬止损→波动止损→逻辑止损→时间止损→止盈） |
| 反脆弱 | 无 | 市场风格切换检测 + 策略权重自适应 + 过拟合清单 |

---

## 1. 先验约束矩阵（A股硬事实）

任何策略/信号/仓位计算必须首先通过此约束层，不可旁路。

| 约束 | 参数 | 处理规则 |
|------|------|---------|
| T+1 | 买入当日不可卖出 | 所有回测/实盘必须 enforce；信号 T 日生成 → T+1 执行 |
| 涨跌停 | 主板 ±10%，科创/创业 ±20%，北交所 ±30% | 涨停无法买入 → 跳过或次日排队；跌停无法卖出 → 止损可能失效，纳入压力测试 |
| 滑点 | 默认 0.15%（单边），低流动性标的提升至 0.3% | 回测中扣除，实盘按 VWAP 下单衡量 |
| 手续费 | 佣金万2.5双边 + 印花税千1（卖方单边） | 单次往返成本 ≈ 0.15%；回测必须含费 |
| 停牌 | 随机发生 | 持仓占比 ≤ 10% 的停牌可承受；>10% 触发风控预警 |
| 流动性 | 20日均成交额 ≥ 5000万 | 低于阈值不入池；回测时检查冲击成本 |
| 最小交易单位 | 100股（手） | 仓位计算按手取整 |

---

## 2. 四类策略并行评估框架

每只标的必须经过四类策略独立评估，产出标准化信号后融合。

### 2.1 策略 A：趋势跟踪（Trend Following）

**已有能力映射**：`src/agents/technicals.py` → 趋势跟踪子策略 + 动量子策略

| 子因子 | 计算方法 | 信号规则 | 置信度调整 |
|--------|---------|---------|-----------|
| 均线排列 | EMA(8/21/55) | 多头排列=+1，空头=-1 | ADX>25 置信度×1.3 |
| 价格动量 | 1M/3M/6M 加权(40/30/30) | >5%=bullish，<-5%=bearish | 成交量确认则×1.2 |
| 趋势质量 | EMA斜率 + 趋势持续天数 | 斜率加速+持续>10天=强趋势 | 持续>30天警惕反转 |
| 突破确认 | 价格突破20日高/低 + 量能 | 放量突破=确认信号 | 假突破过滤（需持续2日） |

**失效条件**：
- 市场处于窄幅震荡（20日ATR/价格 < 1.5%）时趋势策略胜率骤降
- 板块轮动速度 > 3日/轮（趋势尚未确立即切换）
- ADX < 15 且均线纠缠 → 自动降权至 0

**参数敏感性**：
- EMA周期 8/21/55 → 敏感区间 [5-13]/[15-30]/[40-70]，需在回测中做网格搜索
- 动量窗口对短线策略影响大，建议 walk-forward 验证

---

### 2.2 策略 B：均值回归（Mean Reversion）

**已有能力映射**：`src/agents/technicals.py` → 均值回归子策略 + 统计套利子策略

| 子因子 | 计算方法 | 信号规则 | 置信度调整 |
|--------|---------|---------|-----------|
| Z-Score | (Price - MA50) / StdDev50 | <-2=超卖买入，>2=超买卖出 | Hurst<0.5 时×1.3 |
| 布林带位置 | %B = (Price-Lower)/(Upper-Lower) | <0.2=买入区，>0.8=卖出区 | 带宽收窄后扩张=强信号 |
| RSI极值 | RSI(14)交叉30/70 | 从<25上穿30=买入 | 双RSI(14/28)共振×1.5 |
| 偏离率 | (Price - MA20) / MA20 | <-8%=超卖，>12%=超买 | 行业偏离率做参照 |

**失效条件**：
- 强单边趋势中（Hurst > 0.65）均值回归会持续亏损
- 个股基本面发生结构性变化（业绩暴雷/重组）→ 不再回归
- 流动性枯竭时价格可能长期偏离均值

**参数敏感性**：
- Z-Score 阈值 ±2 → 敏感区间 [1.5-2.5]，过紧减少信号，过松降低精度
- MA 周期 50 → 短线用 20，中线 50，长线 120，需与策略周期匹配

---

### 2.3 策略 C：基本面 / 估值（Fundamental & Valuation）

**已有能力映射**：
- `src/agents/fundamentals.py`：盈利/增长/财务健康
- `src/agents/valuation.py`：DCF/所有者收益/可比公司/账面价值
- `src/agents/growth_agent.py`：增长估值

| 子因子 | 计算方法 | 信号规则 | 数据源 |
|--------|---------|---------|--------|
| 估值锚 | PE_TTM vs 行业中位数 vs 自身5年中位数 | 低于中位数70%=低估 | tushare FinancialMetrics |
| DCF安全边际 | 内在价值 vs 当前市值 | 安全边际>30%=买入信号 | valuation agent 4模型 |
| 盈利质量 | FCF/NetIncome > 0.7 + 应计比率 | FCF强且应计低=高质量 | tushare LineItems |
| 增长趋势 | 连续N季度营收/利润增速 | 加速增长=正信号 | growth agent |
| 财务健康 | 流动比>1.5, 负债率<60%, 利息覆盖>3x | 全通过=健康 | fundamentals agent |

**失效条件**：
- 周期股在景气顶部 PE 最低 → 价值陷阱
- 高增长股估值长期偏高 → 不适用传统估值
- A股财报质量参差 → 需交叉验证（审计意见、关联交易、非标科目）

**缺失数据清单**：
| 数据项 | 当前状态 | 最小可行替代 |
|--------|---------|-------------|
| 行业PE中位数 | ❌ 缺失 | 用 tushare 行业指数估值API 或手动维护 TOP30 行业 PE |
| 分析师一致预期 | ❌ 缺失 | 暂跳过，用历史增速外推替代 |
| 审计意见 | ❌ 缺失 | 过滤 ST 股 + 最近年报非标审计意见 |
| 关联交易占比 | ❌ 缺失 | MVP 阶段跳过，标注风险 |

---

### 2.4 策略 D：事件 / 情绪（Event & Sentiment）

**已有能力映射**：
- `src/agents/news_sentiment.py`：LLM 新闻情感分析
- `src/agents/sentiment.py`：内部人交易 + 新闻混合信号

| 子因子 | 计算方法 | 信号规则 | 置信度调整 |
|--------|---------|---------|-----------|
| 新闻情感 | LLM 逐条分类→加权聚合 | 正面占比>65%=bullish | 新闻数量<3则降权 |
| 内部人交易 | 近90天净买入/卖出股数 | 连续净买入=正信号 | 高管级别加权（董事长>VP） |
| 资金流向 | 主力净流入/流出（大单统计） | 连续3日大单净流入=正 | ❌ 当前缺失 |
| 事件催化 | 政策/业绩预告/重组/回购 | 正面催化=加分 | 时效性衰减（3日半衰期） |

**失效条件**：
- 情绪极度一致时（全市场看多/看空）往往是反向信号
- 新闻滞后于价格 → 信息已在价格中反映
- A股散户占比高 → 情绪信号噪声更大

**缺失数据清单**：
| 数据项 | 当前状态 | 最小可行替代 |
|--------|---------|-------------|
| 主力资金流向 | ❌ 缺失 | akshare `stock_fund_flow_individual` 接口 |
| 融资融券余额 | ❌ 缺失 | akshare `stock_margin_detail_szse/sse` |
| 龙虎榜数据 | ❌ 缺失 | akshare `stock_lhb_detail_daily_sina` |
| 政策标签 | ❌ 缺失 | MVP跳过，人工标注重大政策事件 |

---

## 3. 跨策略信号融合引擎

### 3.1 标准化信号格式

每个策略输出统一结构：

```json
{
  "strategy": "trend|mean_reversion|fundamental|sentiment",
  "signal": "bullish|bearish|neutral",
  "confidence": 0-100,
  "sub_signals": {...},
  "reasoning": "...",
  "failure_conditions_triggered": [],
  "data_completeness": 0.0-1.0
}
```

### 3.2 自适应权重融合

**基准权重（默认市场状态）**：

| 策略 | 基准权重 | 说明 |
|------|---------|------|
| 趋势跟踪 | 0.30 | A股趋势性较强时主力策略 |
| 均值回归 | 0.20 | 震荡市主力策略 |
| 基本面/估值 | 0.30 | 中长期锚定 |
| 事件/情绪 | 0.20 | 短期催化 |

**市场风格自适应调整规则**：

```
IF 市场状态 == "强趋势"（沪深300 20日ADX > 30）:
    趋势权重 × 1.4, 均值回归权重 × 0.5
    
IF 市场状态 == "震荡"（沪深300 20日ATR/价格 < 1.2%）:
    均值回归权重 × 1.5, 趋势权重 × 0.6

IF 市场状态 == "情绪极端"（VIX等价或换手率异常）:
    情绪权重 × 0.5（反向解读）, 基本面权重 × 1.3

归一化：调整后权重 / Σ(调整后权重)
```

### 3.3 信号融合公式

$$
Score_{final} = \sum_{i \in \{T,M,F,S\}} w_i \cdot signal_i \cdot confidence_i \cdot completeness_i
$$

其中：
- $signal_i \in \{-1, 0, +1\}$（bearish/neutral/bullish 数值化）
- $confidence_i \in [0, 1]$
- $completeness_i \in [0, 1]$（数据完整度惩罚）
- $w_i$ = 自适应权重

**决策阈值**：

| $Score_{final}$ 区间 | 决策 | 备注 |
|---------------------|------|------|
| > +0.35 | 入池观察 | 进入 T+1 确认队列 |
| > +0.50 | 强买入候选 | 优先分配仓位 |
| [-0.35, +0.35] | 中性 / 持有 | 无新动作 |
| < -0.35 | 卖出 / 回避 | 已持仓则启动退出 |
| < -0.50 | 强卖出 | 优先退出 |

---

## 4. 仓位管理与风控硬约束

### 4.1 仓位计算公式

基于已有 `risk_manager.py` 的波动率+相关性框架，增加如下约束层：

$$
Position_{max} = \min\left(
  \frac{PortfolioValue \times VolLimit_{adj}}{Price},\;
  \frac{AvailableCash}{Price},\;
  \frac{ADV_{20} \times 0.02}{Price},\;
  IndustryLimit_{remaining}
\right)
$$

按100股取整：$Position_{final} = \lfloor Position_{max} / 100 \rfloor \times 100$

其中：
- $VolLimit_{adj}$ = `calculate_volatility_adjusted_limit()` × `correlation_multiplier`（现有逻辑）
- $ADV_{20} \times 0.02$ = 流动性约束（不超过20日均成交额的2%）
- $IndustryLimit_{remaining}$ = 行业上限 - 该行业已有持仓

### 4.2 硬约束矩阵

| 约束项 | 参数 | 触发动作 |
|--------|------|---------|
| 单票仓位上限 | 10% of Portfolio NAV | 超出部分不执行，记录日志 |
| 单行业暴露上限 | 25% of Portfolio NAV | 同行业新买入被拒 |
| 单日新开仓数量 | ≤ 3 只 | 按 Score 排序取 Top3 |
| 单日名义换手 | ≤ 20% of Portfolio NAV | 超出推迟至次日 |
| 组合最大回撤 | -10% 预警，-15% 强制减仓50% | 全组合比例缩减 |
| 单票最大亏损 | -7% 硬止损 | 次日开盘市价卖出 |
| 相关性约束 | 任意两票 corr > 0.8 → 合并计算仓位 | 视为同一敞口 |
| 停牌占比 | 单票停牌且占仓 >10% | 剩余票按比例减仓释放流动性 |

### 4.3 多层退出级联

按优先级从高到低执行，**触发即执行，不等待更低优先级确认**：

```
Level 1 [硬止损]：单票亏损 ≥ 7%  → T+1开盘卖出（受涨跌停限制）
Level 2 [波动止损]：ATR止损 = 入场价 - 2 × ATR(14)  → 收盘价破则次日卖出
Level 3 [逻辑止损]：买入逻辑被证伪（趋势破坏/业绩不及预期/事件失效） → 人工或Agent确认后卖出
Level 4 [时间止损]：持仓超过 Max_Hold_Days（默认20日）且收益 < 3%  → 卖出释放资金
Level 5 [止盈]：
  - 达到目标收益 15% → 卖出 50%
  - 达到目标收益 25% → 再卖出 30%
  - 剩余 20% 用 trailing stop（回落幅度 > Max(5%, 最高收益×30%）时清仓）
```

### 4.4 涨跌停处理协议

```
买入方向：
  - T日打分后标的 T+1 涨停 → 不追买，放入 "pending_buy" 队列
  - T+2 开板且 Score 仍有效 → 执行买入
  - 连续2日涨停 → 从队列移除，标注"短期过热"

卖出方向：
  - 止损触发但 T+1 跌停无法卖出 → 记录 "pending_sell"，次日集合竞价优先卖出
  - 连续跌停 → 压力测试：假设持有至开板，计算极端亏损
```

---

## 5. 完整执行流水线

### 5.1 日度执行时序

```
T日 15:00后（收盘数据到位）
├── Step 1: Layer A - 全市场快筛 → 200只候选池
│   ├── 排除：ST/停牌/退市/低流动性/北交所
│   ├── 排除：当日涨停（无法T+1建仓）
│   └── 输出：data/stock/candidates/pool_YYYYMMDD.csv
│
├── Step 2: Layer B - 四策略并行评分 → 60只高分池
│   ├── 策略A: 趋势跟踪评分（technicals agent 简化版）
│   ├── 策略B: 均值回归评分（Z-Score + RSI + 布林带）
│   ├── 策略C: 基本面评分（PE/PB/ROE/FCF快筛）
│   ├── 策略D: 情绪评分（新闻情感 + 内部人交易）
│   ├── 信号融合 → Score_final
│   └── 输出：data/stock/candidates/scored_YYYYMMDD.csv
│
├── Step 3: Layer C - 多智能体深度分析 → Top 10 观察名单
│   ├── 调用现有 src/main.py 分析流程（12+6 agents）
│   ├── Risk Manager 波动率 + 相关性评估
│   ├── Portfolio Manager 最终决策
│   └── 输出：data/stock/candidates/watchlist_YYYYMMDD.json
│
└── Step 4: 生成 T+1 执行计划
    ├── 确认条件检查清单
    ├── 仓位计算（含全部约束）
    ├── 退出检查（现有持仓止损/止盈/时间止损）
    └── 输出：data/stock/execution/plan_YYYYMMDD.json

T+1日 09:15-09:25（集合竞价前）
├── Step 5: 开盘前确认
│   ├── 检查隔夜重大新闻/公告
│   ├── 检查是否跳空超过 ATR(14)
│   ├── 检查涨跌停预判
│   └── 更新执行计划状态
│
T+1日 09:30-14:57（盘中）
├── Step 6: 确认入场
│   ├── 观察名单标的是否满足确认条件（满足其二）
│   │   ├── 条件1: 回踩不破关键均线/前低
│   │   ├── 条件2: 量价配合（上涨+合理放量）
│   │   └── 条件3: 板块相对强度未转弱
│   ├── 满足 → 执行买入（14:30-14:50 窗口）
│   └── 不满足 → 保留1日，次日重评
│
T+1日 14:57-15:00
└── Step 7: 收盘前止损/止盈执行
    ├── 检查所有持仓退出条件
    └── 执行卖出单
```

### 5.2 执行计划 JSON Schema

```json
{
  "date": "2026-03-04",
  "market_state": {
    "regime": "trending|ranging|volatile",
    "csi300_adx": 28.5,
    "strategy_weights": {"trend": 0.33, "mean_reversion": 0.17, "fundamental": 0.30, "sentiment": 0.20}
  },
  "new_entries": [
    {
      "ticker": "000001",
      "name": "平安银行",
      "score_final": 0.62,
      "strategy_scores": {
        "trend": {"signal": "bullish", "confidence": 72, "completeness": 1.0},
        "mean_reversion": {"signal": "neutral", "confidence": 45, "completeness": 1.0},
        "fundamental": {"signal": "bullish", "confidence": 65, "completeness": 0.8},
        "sentiment": {"signal": "bullish", "confidence": 55, "completeness": 0.6}
      },
      "position": {
        "target_shares": 1000,
        "target_pct": 0.05,
        "max_cost": 12500.0,
        "entry_window": "14:30-14:50"
      },
      "risk": {
        "hard_stop": -0.07,
        "atr_stop": 11.85,
        "target_profit_1": 0.15,
        "target_profit_2": 0.25,
        "max_hold_days": 20
      },
      "confirmation_checklist": [
        {"condition": "回踩不破MA20", "required": false},
        {"condition": "量价配合", "required": false},
        {"condition": "板块强度", "required": false}
      ],
      "failure_conditions": [
        "ADX<15 且均线纠缠",
        "行业PE高于历史90%分位"
      ]
    }
  ],
  "exits": [
    {
      "ticker": "300118",
      "exit_type": "hard_stop",
      "current_loss_pct": -0.072,
      "action": "sell_all",
      "priority": "Level 1"
    }
  ],
  "portfolio_constraints_check": {
    "max_drawdown_current": -0.035,
    "industry_exposure": {"银行": 0.12, "新能源": 0.08},
    "correlation_warnings": [],
    "daily_turnover_pct": 0.08,
    "all_constraints_passed": true
  }
}
```

---

## 6. 反脆弱机制

### 6.1 市场风格切换检测

每日检测以下信号，触发权重调整：

| 检测指标 | 阈值 | 触发动作 |
|---------|------|---------|
| 沪深300 20日ADX | >30 → 趋势市 | 趋势权重 ×1.4 |
| 沪深300 20日ATR/Price | <1.2% → 震荡市 | 均值回归权重 ×1.5 |
| 涨停/跌停家数比 | >3:1 或 <1:3 → 极端情绪 | 情绪权重 ×0.5（反向解读） |
| 两市成交额 | <5000亿 → 缩量 | 降低整体仓位至50% |
| 北向资金连续净流出 | >3日 | 基本面权重 ×1.2，趋势权重 ×0.8 |

### 6.2 过拟合风险清单

| 风险项 | 检测方法 | 缓解措施 |
|--------|---------|---------|
| 回测过拟合 | 训练集 vs 验证集 Sharpe 差异 > 0.5 | walk-forward 验证 + 参数扰动 ±20% |
| 数据窥探 | 同一数据集调参 > 3 次 | 保持30%数据为盲测集 |
| 存活偏差 | 仅分析在市股票 | 加入退市/ST 股票历史数据 |
| 前视偏差 | 使用财报日而非报告日数据 | 所有基本面数据加 T+45 天延迟 |
| 策略拥挤 | 同策略持仓与市场热度共振 | 监控板块拥挤度，触发阈值降仓 |
| 小样本陷阱 | 信号触发次数 < 30 | 该策略置信度 × 0.5 |

### 6.3 参数敏感性备案

MVP 阶段需对以下参数做敏感性分析（±20%扰动后观察 Sharpe 变化）：

```
[高敏感参数 - 必须 walk-forward]
├── EMA 周期组合 (8/21/55)
├── Z-Score 阈值 (±2)
├── 硬止损比例 (-7%)
├── 信号融合阈值 (+0.35)
└── 单票仓位上限 (10%)

[中敏感参数 - 需定期回测]
├── ATR 止损倍数 (2x)
├── 止盈目标 (15%/25%)
├── 最大持仓天数 (20日)
└── 流动性阈值 (5000万)

[低敏感参数 - 初版固定即可]
├── 手续费率 (万2.5)
├── 滑点率 (0.15%)
└── 最小交易单位 (100股)
```

---

## 7. 与现有系统的实现映射

### 7.1 可直接复用的模块

| 框架组件 | 现有代码 | 复用方式 |
|---------|---------|---------|
| 趋势跟踪信号 | `technicals.py` 5子策略 | 直接调用，提取子信号 |
| 均值回归信号 | `technicals.py` mean_reversion + stat_arb | 直接调用 |
| 基本面评分 | `fundamentals.py` + `valuation.py` + `growth_agent.py` | 组合调用 |
| 情绪信号 | `news_sentiment.py` + `sentiment.py` | 直接调用 |
| 波动率风控 | `risk_manager.py` | 扩展行业约束 |
| 仓位决策 | `portfolio_manager.py` | 增加硬约束层 |
| 回测引擎 | `src/backtesting/engine.py` | 增加含费回测 |
| 数据接口 | `src/tools/tushare_api.py` + `akshare_api.py` | 直接使用 |

### 7.2 需新增的模块

| 模块 | 位置 | 功能 | 优先级 |
|------|------|------|--------|
| `build_candidate_pool.py` | `scripts/` | Layer A 全市场快筛 | P0 |
| `multi_strategy_scorer.py` | `scripts/` | Layer B 四策略评分+融合 | P0 |
| `market_regime_detector.py` | `src/utils/` | 市场风格检测+权重自适应 | P1 |
| `position_sizer.py` | `src/utils/` | 完整约束仓位计算器 | P0 |
| `exit_manager.py` | `src/utils/` | 多层退出级联逻辑 | P0 |
| `confirm_entries.py` | `scripts/` | T+1确认执行 | P1 |
| `execution_plan_generator.py` | `scripts/` | 每日执行计划JSON生成 | P1 |
| `sensitivity_analyzer.py` | `scripts/` | 参数敏感性分析 | P2 |
| `industry_exposure.py` | `src/utils/` | 行业分类+暴露度计算 | P1 |

### 7.3 最小可执行路径（按周排期）

```
Week 1: 数据基础 + 快筛
  ├── build_candidate_pool.py（Layer A）
  ├── 验证 tushare/akshare 全市场数据可用性
  └── 输出：每日200只候选池

Week 2: 多策略评分引擎
  ├── multi_strategy_scorer.py（Layer B）
  ├── 复用 technicals.py 子信号
  ├── 信号融合逻辑
  └── 输出：每日60只高分池

Week 3: 风控约束 + 退出机制
  ├── position_sizer.py（完整约束）
  ├── exit_manager.py（多层退出）
  ├── 接入 batch_run_hedge_fund.py
  └── 输出：每日执行计划

Week 4: 回测验证 + 参数调优
  ├── 含费回测 vs baseline
  ├── walk-forward 验证
  ├── 参数敏感性基础扫描
  └── 输出：A/B对比报告
```

---

## 8. 回测验证规范

### 8.1 回测硬要求

- [x] 含手续费（万2.5双边 + 千1印花税）
- [x] 含滑点（0.15%单边）
- [x] T+1 限制（买入当日不可卖出）
- [x] 涨跌停限制（涨停不可买入、跌停不可卖出）
- [x] 最小交易100股
- [x] 排除退市/长期停牌股
- [ ] 前视偏差检查（财报延迟45天）← 后续版本

### 8.2 评估指标矩阵

| 指标 | 公式 | MVP目标 | 说明 |
|------|------|---------|------|
| **Sortino Ratio** | $\frac{R_p - R_f}{\sigma_{downside}}$ | > 1.5 | 主目标函数 |
| **Sharpe Ratio** | $\frac{R_p - R_f}{\sigma_p}$ | > 1.0 | 已有 `metrics.py` |
| **Max Drawdown** | $\max_{t} \frac{Peak_t - Trough_t}{Peak_t}$ | < 15% | 已有 `metrics.py` |
| **Calmar Ratio** | $\frac{Annual Return}{Max Drawdown}$ | > 1.0 | 需新增 |
| **胜率** | $\frac{盈利交易数}{总交易数}$ | > 45% | 非主目标 |
| **盈亏比** | $\frac{平均盈利}{平均亏损}$ | > 2.0 | 比胜率更重要 |
| **年化换手率** | $\frac{∑|交易金额|}{平均持仓NAV}$ | < 30x | 控制交易成本 |
| **超额收益** | $R_p - R_{benchmark}$ | > 0 | 基准=中证500 |

### 8.3 A/B 实验分组

```
Group A (Baseline)：涨幅榜 → 多智能体 → 买入
Group B (MVP-v1)：全市场快筛 → 四策略评分 → 多智能体 → T+1确认 → 买入

时间窗口：
  - 训练/调参：2025-06-01 ~ 2025-12-31（6个月）
  - 样本外验证：2026-01-01 ~ 2026-02-28（2个月）
  - Walk-forward：2个月窗口滚动，步长1个月

主假设（H0）：MVP-v1 Sortino Ratio ≤ Baseline Sortino Ratio
拒绝条件：单侧 t 检验 p < 0.05
```

---

## 9. 评审清单

### 9.1 关键决策（需明确）

| # | 决策点 | 默认值 | 影响 |
|---|--------|--------|------|
| 1 | 单票硬止损 -7% 是否过紧？ | -7% | A股波动大，可能频繁触发 |
| 2 | 行业暴露 25% 是否过宽？ | 25% | A股板块效应强，25%可能不够分散 |
| 3 | 涨幅榜策略是否保留为子策略？ | 保留但权重降至10% | 强趋势日仍有价值 |
| 4 | 是否引入做空信号？ | 仅标记，不执行做空 | A股融券难度大 |
| 5 | 最大持仓天数 20 日是否合适？ | 20日 | 基本面策略可能需更长 |
| 6 | MVP数据是否够用？ | 缺项见上文 | 先跑能跑的，标注缺失 |

### 9.2 本框架未覆盖（后续版本）

- 组合优化（Markowitz / Risk Parity）：当前是等权或波动率加权，未做优化
- 多周期嵌套：当前仅日频，未覆盖周频/月频视角
- 宏观因子叠加：利率/汇率/信用利差等
- 交易执行算法：TWAP/VWAP 拆单
- 实盘对接：券商 API 下单
- 绩效归因：Brinson / 因子归因

---

## 附录 A：数据依赖与可用性矩阵

| 数据 | 来源 | API | 可用性 | 延迟 |
|------|------|-----|--------|------|
| 日线行情 | tushare | `daily` | ✅ T+0 | 收盘后15分钟 |
| 财务指标(TTM) | tushare | `fina_indicator` | ✅ | 报告期+45天 |
| 财报明细 | tushare | `income/balancesheet/cashflow` | ✅ | 报告期+45天 |
| 内部人交易 | tushare | `stk_holdertrade` | ✅ | T+1 |
| 每日涨幅榜 | tushare | `daily_basic` | ✅ T+0 | 收盘后 |
| 公司新闻 | akshare | `stock_news_em` | ✅ | 实时 |
| 市值 | tushare | `daily_basic` | ✅ T+0 | 收盘后 |
| 行业分类 | tushare | `stock_basic` | ✅ | 静态 |
| 主力资金 | akshare | `stock_fund_flow` | ⚠️ 需验证 | 收盘后 |
| 融资融券 | akshare | `stock_margin` | ⚠️ 需验证 | T+1 |
| 板块指数 | tushare | `index_daily` | ✅ | 收盘后 |

## 附录 B：回测成本预估

| 执行阶段 | 标的数 | 预估API调用 | 预估LLM调用 | 单日耗时 |
|---------|--------|------------|------------|---------|
| Layer A 快筛 | ~4500 → 200 | ~4500次(日线) + 200次(基础面) | 0 | ~10分钟 |
| Layer B 评分 | 200 → 60 | ~800次(指标/新闻) | 0（规则计算） | ~5分钟 |
| Layer C 深度 | 60 → 10 | ~600次(多维度) | ~60×18=1080 次 | ~30分钟 |
| 总计 | - | ~5900次 | ~1080次 | ~45分钟 |

> 按 tushare 200次/分钟限流 + LLM批量并发，单日全流程 ≤ 1小时（现有算力可承受）。

## 附录 C：关键参数速查表

```yaml
# ===== 筛选参数 =====
candidate_pool_size: 200
deep_analysis_size: 60
final_watchlist_size: 10
liquidity_threshold_cny: 50_000_000  # 20日均成交额

# ===== 信号融合 =====
weights_default:
  trend: 0.30
  mean_reversion: 0.20
  fundamental: 0.30
  sentiment: 0.20
entry_threshold: 0.35
strong_entry_threshold: 0.50
exit_threshold: -0.35

# ===== 风控约束 =====
max_single_position_pct: 0.10
max_industry_exposure_pct: 0.25
max_daily_new_positions: 3
max_daily_turnover_pct: 0.20
max_portfolio_drawdown_warning: -0.10
max_portfolio_drawdown_forced: -0.15

# ===== 止损止盈 =====
hard_stop_loss: -0.07
atr_stop_multiplier: 2.0
max_hold_days: 20
profit_target_1: 0.15
profit_target_1_sell_pct: 0.50
profit_target_2: 0.25
profit_target_2_sell_pct: 0.30
trailing_stop_trigger: 0.05

# ===== 交易成本 =====
commission_rate: 0.00025  # 万2.5
stamp_tax_rate: 0.001     # 千1卖方
slippage_rate: 0.0015     # 0.15%
min_trade_unit: 100       # 股
```
