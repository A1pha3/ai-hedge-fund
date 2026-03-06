# 机构级多策略量化交易决策框架 — 开发计划

> **基于文档**：docs/zh-cn/product/institutional_multi_strategy_framework_v1.4.md  
> **制定日期**：2026-03-06  
> **代码库**：ai-hedge-fund-fork（分支 main，commit 036fac2）

---

## 一、现状评估：已有能力 vs 待建模块

### 1.1 已有能力（可直接复用）

| 能力 | 对应代码 | 覆盖度 | 备注 |
|------|---------|--------|------|
| 技术指标计算（EMA/ADX/ATR/RSI/布林带/Hurst） | `src/agents/technicals.py` | ✅ 完整 | 含 5 个子策略（趋势/均值回归/动量/波动率/统计套利）。⚠️ 现有均线参数为 EMA(8/21/55)，框架要求 EMA(10/30/60)，需在适配层重新计算 |
| 基本面分析 | `src/agents/fundamentals.py` | ✅ 完整 | 盈利/增长/财务健康评分 |
| 估值分析 | `src/agents/valuation.py` | ✅ 完整 | 多模型估值 |
| 成长分析 | `src/agents/growth_agent.py` | ✅ 完整 | 增速趋势评估 |
| 新闻情感分析 | `src/agents/news_sentiment.py` | ✅ 完整 | LLM 逐条新闻分类 |
| 情绪混合分析 | `src/agents/sentiment.py` | ✅ 完整 | 内部人交易 + 情绪指标 |
| 风险管理（波动率仓位/相关性） | `src/agents/risk_manager.py` | ⚠️ 部分 | 缺少行业暴露、CVaR、硬约束矩阵 |
| 组合决策 | `src/agents/portfolio_manager.py` | ⚠️ 部分 | 缺少四约束仓位计算、信号强度联动 |
| LangGraph 工作流编排 | `src/main.py` | ✅ 完整 | 并行 Agent → 风控 → 组合决策 |
| A 股数据接口（tushare/akshare） | `src/tools/tushare_api.py`, `src/tools/akshare_api.py` | ✅ 完整 | 日线、财务、新闻、内部人交易 |
| 数据缓存 + 质量校验 | `src/data/` | ✅ 完整 | 内存缓存 + Pydantic 验证 |
| 数据源路由与降级 | `src/data/router.py` | ⚠️ 部分 | 已有 DataRouter 健康检查 + 自动降级框架，缺少 LLM 不可用降级及业务级策略 |
| 回测引擎 | `src/backtesting/` | ⚠️ 部分 | 有 Sharpe/Sortino/MDD，缺 Calmar/盈亏比/换手率 |
| 12 投资大师 Agent | `src/agents/` | ✅ 完整 | 标准三元组输出 |
| CLI 入口 | `src/cli/input.py`, `src/main.py` | ✅ 完整 | 支持 ticker/analyst 选择 |
| 批量运行脚本 | `scripts/batch_run_hedge_fund.py` | ✅ 完整 | 涨幅榜筛股 → 批量分析 |

### 1.2 待建模块（Gap 分析）

| 模块 | 对应框架章节 | 优先级 | 依赖 |
|------|------------|--------|------|
| **候选池构建器**（Layer A 全市场快筛） | §1, §5.1 Step 1 | **P0** | tushare stock_basic + daily_basic |
| **四策略评分器**（Layer B 评分 + 子因子聚合） | §2.1~2.4, §2（聚合规则） | **P0** | 技术分析 Agent 子信号提取 |
| **信号融合引擎**（跨策略融合 + 冲突仲裁） | §3.1~3.4 | **P0** | 四策略评分器输出 |
| **市场状态检测器** | §3.2 | **P0** | 沪深300行情、成交额、涨跌停统计 |
| **增强仓位计算器**（四约束取最小 + 信号联动） | §4.1, §4.2 | **P0** | 行业暴露计算器 |
| **五层退出管理器** | §4.3 | **P0** | 持仓跟踪（入场价/最高浮盈/持仓天数） |
| **涨跌停处理器**（待买/待卖队列） | §4.4 | **P0** | 退出管理器 |
| **行业暴露计算器**（申万一级分类） | §4.2 | **P0** | tushare 行业分类数据（仓位计算器的前置依赖，仓位 P0 则此项也必须 P0） |
| **T+1 确认执行器**（三条确认规则） | §5.2 | **P1** | akshare 盘中实时行情 |
| **信号衰减检查器** | §5.3 | **P1** | ATR + 新闻监控 |
| **执行计划生成器**（结构化输出） | §5.1 Step 4, §6.4 | **P1** | 仓位计算器 + 退出管理器 |
| **极端场景处理器**（熔断/暴跌/恢复协议） | §6.1~6.2 | **P1** | 市场状态检测器 |
| **数据源降级管理器** | §6.3 | **P1** | 双数据源切换逻辑 |
| **监控告警系统**（策略漂移/DQR/异常） | §6.4 | **P2** | 历史信号分布存储 |
| **回测增强**（Calmar/盈亏比/换手率/CVaR/Beta） | §8.2 | **P2** | 现有回测引擎扩展 |
| **参数敏感性分析器** | §7.2 | **P2** | 回测引擎 |
| **A/B 实验框架** | §8.3 | **P2** | 回测增强 |
| **Layer C 聚合器**（Agent 加权投票 + B/C 融合 + 冲突处理） | §5.1 Layer C 聚合规则 | **P0** | 现有 LangGraph 工作流输出 |
| **阈值再标定模块**（月度自适应） | §3.1 | **P3** | 历史 Score_B 分布存储 |
| **相关性聚类合并器**（传递性处理） | §4.2 | **P3** | 相关性矩阵 |
| **运行手册与告警路由** | §6.5 | **P2** | 监控告警系统 |
| **涨幅榜策略封装**（现有涨幅榜筛股作为第五策略，权重10%） | §10 决策点3 | **P1** | 现有 `batch_run_hedge_fund.py` 逻辑封装 |
| **Agent completeness 输出扩展** | §5.1 规则4 | **P0** | 现有 Agent 无 completeness 字段，需扩展输出或在聚合层推断 |
| **停牌应急处理器**（停牌占仓>10%减仓） | §4.2 | **P0** | 仓位计算器 |
| **策略容量监控** | §11 | **P3** | 流动性约束 + 市场冲击成本 |

---

## 二、架构设计

### 2.1 模块分层与目录规划

> **与框架 §9.2 的偏离说明**：框架 §9.2 建议将候选池构建器、评分器等放在 `scripts/`，仓位/退出计算放在 `src/utils/`。本计划将其重新组织为 `src/screening/`、`src/portfolio/`、`src/execution/` 三个独立包——理由是这些模块具有明确的分层关系和复杂的内部依赖，比脚本级组织更适合长期维护。框架 §9.2 的 `scripts/` 定位更偏向一次性工具，与全流水线的工程需求不匹配。

```
src/
├── screening/                    # 新增：Layer A + Layer B
│   ├── __init__.py
│   ├── candidate_pool.py         # Layer A 候选池构建器
│   ├── strategy_scorer.py        # Layer B 四策略评分器
│   ├── signal_fusion.py          # 跨策略融合 + 冲突仲裁
│   ├── market_state.py           # 市场状态检测器
│   └── models.py                 # 筛选层数据模型
├── portfolio/                    # 新增：仓位 + 退出 + 行业
│   ├── __init__.py
│   ├── position_calculator.py    # 四约束仓位计算器
│   ├── exit_manager.py           # 五层退出级联
│   ├── limit_handler.py          # 涨跌停处理器（待买/待卖队列）
│   ├── suspension_handler.py     # 停牌应急处理器（停牌占仓>10%减仓）
│   ├── industry_exposure.py      # 行业暴露计算器
│   ├── correlation_cluster.py    # 相关性聚类合并
│   └── models.py                 # 组合层数据模型
├── execution/                    # 新增：日度执行流水线
│   ├── __init__.py
│   ├── models.py                 # LayerCResult / ExecutionPlan 等数据模型
│   ├── daily_pipeline.py         # 7 步执行编排
│   ├── layer_c_aggregator.py     # Layer C 聚合器（Agent 加权投票 + B/C 融合）
│   ├── t1_confirmation.py        # T+1 确认执行器
│   ├── signal_decay.py           # 信号衰减检查器
│   ├── plan_generator.py         # 执行计划生成器
│   └── crisis_handler.py         # 极端场景处理器
├── monitoring/                   # 新增：监控告警
│   ├── __init__.py
│   ├── drift_detector.py         # 策略漂移检测
│   ├── data_quality.py           # DQR 健康度监控
│   ├── daily_report.py           # 每日执行报告
│   └── runbook.py                # 运行手册与告警路由（P1/P2/P3 SLA）
├── agents/                       # 现有（需微调）
├── backtesting/                  # 现有（需扩展）
│   └── metrics.py                # 扩展：Calmar/盈亏比/换手率/CVaR/Beta
├── data/                         # 现有（需扩展）
│   └── providers/
│       └── failover.py           # 新增：数据源降级管理
├── tools/                        # 现有（需扩展）
│   ├── tushare_api.py            # 扩展：stock_basic 全量、申万行业分类
│   └── akshare_api.py            # 扩展：盘中实时行情、资金流向
└── main.py                       # 改造：集成新流水线入口
```

### 2.2 数据流总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     T 日 15:00 收盘后启动                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐    │
│  │ 市场状态检测器 │────▶│ 策略权重调整  │────▶│ 四策略评分器 (per stock)│   │
│  │ market_state  │     │ (自适应)      │     │ strategy_scorer       │   │
│  └──────────────┘     └──────────────┘     └──────────┬───────────┘    │
│        │                                                │               │
│        ▼                                                ▼               │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐    │
│  │ 候选池构建器  │────▶│ Layer A 输出  │────▶│ 冲突仲裁 + 信号融合   │   │
│  │ candidate_pool│     │ 150~300 只    │     │ signal_fusion         │   │
│  └──────────────┘     └──────────────┘     └──────────┬───────────┘    │
│                                                        │               │
│                                                        ▼               │
│                                             ┌──────────────────────┐   │
│                                             │ Layer B 高分池        │   │
│                                             │ Score_B ≥ +0.35      │   │
│                                             │ ≈ 60 只               │   │
│                                             └──────────┬───────────┘   │
│                                                        │               │
│                                                        ▼               │
│                                             ┌──────────────────────┐   │
│                                             │ Layer C: 18 Agent    │   │
│                                             │ 并行深度分析          │   │
│                                             │ (现有 LangGraph 工作流)│  │
│                                             └──────────┬───────────┘   │
│                                                        │               │
│                                                        ▼               │
│                                             ┌──────────────────────┐   │
│                                             │ Layer C 聚合器        │   │
│                                             │ layer_c_aggregator    │   │
│                                             │ Score_final =         │   │
│                                             │ 0.4×B + 0.6×C        │   │
│                                             │ + B/C 冲突处理        │   │
│                                             │ 淘汰 < +0.25         │   │
│                                             └──────────┬───────────┘   │
│                                                        │               │
│                                                        ▼               │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐   │
│  │ 退出管理器    │────▶│ 仓位计算器    │◀───│ 观察名单 ~10 只       │   │
│  │ exit_manager  │     │ pos_calculator│     │ Score_final ≥ +0.25  │   │
│  └──────────────┘     └──────┬───────┘     └──────────────────────┘   │
│                              │                                         │
│                              ▼                                         │
│                    ┌──────────────────────┐                            │
│                    │ 执行计划生成器        │                            │
│                    │ plan_generator        │                            │
│                    └──────────┬───────────┘                            │
│                              │                                         │
├──────────────────────────────┼─────────────────────────────────────────┤
│               T+1 日 09:15 盘前                                        │
│                              ▼                                         │
│                    ┌──────────────────────┐                            │
│                    │ 信号衰减 + 隔夜检查   │                            │
│                    │ signal_decay          │                            │
│                    └──────────┬───────────┘                            │
│                              │                                         │
│               T+1 日 14:30 盘中                                        │
│                              ▼                                         │
│                    ┌──────────────────────┐                            │
│                    │ T+1 确认执行器        │                            │
│                    │ t1_confirmation       │                            │
│                    └──────────┬───────────┘                            │
│                              │                                         │
│               14:30~14:57 执行                                         │
│                              ▼                                         │
│              ┌───────────────┴───────────────┐                        │
│              ▼                               ▼                        │
│   ┌──────────────────┐            ┌──────────────────┐               │
│   │ 买入执行          │            │ 卖出执行          │               │
│   │ 14:30~14:50       │            │ 14:50~14:57       │               │
│   │ (涨跌停处理器)     │            │ (五层退出级联)     │               │
│   └──────────────────┘            └──────────────────┘               │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.3 核心数据模型设计

> **设计决策**：使用 Pydantic `BaseModel` 而非 `@dataclass`，与项目现有验证模式一致（`src/data/models.py` 已使用 Pydantic），并支持自动 JSON 序列化和字段约束校验。

```python
# src/screening/models.py
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional

class CandidateStock(BaseModel):
    """Layer A 候选池标的"""
    ticker: str
    name: str
    industry_sw: str          # 申万一级行业
    market_cap: float         # 总市值（亿）
    avg_volume_20d: float     # 20日均成交额（万）
    listing_date: str         # 上市日期（YYYYMMDD），用于新股过滤规则
    disclosure_risk: bool = False  # 财报窗口期标记

class MarketStateType(str, Enum):
    """市场状态类型（§3.2 + §6.1）"""
    trend = "trend"           # 趋势市（ADX > 30）
    range_ = "range"          # 震荡市（ATR/Price < 1.2%）
    mixed = "mixed"           # 混合状态
    crisis = "crisis"         # 危机模式（沸深300日跌>5% 或 跌停>500家）

class StrategySignal(BaseModel):
    """单策略标准三元组（§2 子因子聚合规则）"""
    direction: int = Field(ge=-1, le=1)  # +1 看涨, 0 中性, -1 看跌
    confidence: float = Field(ge=0, le=100)
    completeness: float = Field(ge=0, le=1)
    sub_factors: dict        # 子因子明细

class MarketState(BaseModel):
    """市场状态检测结果（§3.2 五项指标）"""
    state_type: MarketStateType
    adx: float                       # 沪深300 ADX(20)
    atr_price_ratio: float           # ATR/Price 波幅占比
    limit_up_down_ratio: float       # 涨停/跌停家数比
    total_volume: float              # 两市成交额（亿）
    northbound_flow_days: int        # 北向资金连续净流入/出天数（正=流入）
    is_low_volume: bool              # 是否缩量市（< 5000亿）
    position_scale: float = Field(ge=0, le=1, default=1.0)  # 仓位折算系数
    adjusted_weights: dict[str, float]  # 调整后归一化的策略权重

class FusedScore(BaseModel):
    """单标的 Layer B 融合得分（§3.1 融合公式 + §3.4 决策阈值）"""
    ticker: str
    score_b: float = Field(ge=-1, le=1)
    strategy_signals: dict[str, StrategySignal]
    arbitration_applied: list[str]   # 触发的仲裁规则名称
    market_state: MarketState
    weights_used: dict[str, float]   # 实际使用的策略权重
    decision: str                    # strong_buy/watch/neutral/sell/strong_sell

class LayerCResult(BaseModel):
    """单标的 Layer C 聚合结果（§5.1 Layer C 聚合规则）"""
    ticker: str
    score_c: float = Field(ge=-1, le=1)  # Layer C 加权投票得分
    score_final: float       # 0.4 × score_b + 0.6 × score_c
    score_b: float           # 继承自 Layer B
    agent_signals: dict[str, StrategySignal]  # {agent_name: signal}
    bc_conflict: Optional[str] = None  # Layer B/C 冲突处理结果（§5.1 规则6）
    decision: str            # strong_buy/watch/neutral/avoid/strong_sell

# src/portfolio/models.py
from pydantic import BaseModel, Field

class PositionPlan(BaseModel):
    """仓位计划（§4.1 四约束取最小值）"""
    ticker: str
    shares: int              # 向下取整至 100
    amount: float
    constraint_binding: str  # 哪个约束生效（vol/cash/liquidity/industry）
    score_final: float
    execution_ratio: float   # 100% / 60% / hold

class ExitSignal(BaseModel):
    """退出信号（§4.3 五层退出级联）"""
    ticker: str
    level: str               # L1/L2/L2.5/L3/L4/L5
    trigger_reason: str
    urgency: str             # immediate/next_day
    sell_ratio: float = Field(ge=0, le=1)

class HoldingState(BaseModel):
    """持仓跟踪状态（需持久化至 JSON/SQLite）"""
    ticker: str
    entry_price: float
    entry_date: str
    shares: int
    cost_basis: float
    industry_sw: str         # 申万一级行业，用于行业暴露计算
    max_unrealized_pnl_pct: float  # 历史最高浮盈比例
    holding_days: int
    profit_take_stage: int = Field(ge=0, le=3)  # 0/1/2/3（止盈阶段）
    entry_score: float       # 入场时的 score_final

# src/execution/models.py
from pydantic import BaseModel

class ExecutionPlan(BaseModel):
    """每日执行计划（§5.1 七步流水线输出）"""
    date: str
    market_state: MarketState
    strategy_weights: dict[str, float]
    buy_orders: list[PositionPlan]
    sell_orders: list[ExitSignal]
    pending_buy_queue: list   # 涨停待买
    pending_sell_queue: list  # 跌停待卖
    portfolio_snapshot: dict
    risk_alerts: list[str]
    risk_metrics: dict        # {cvar_95, beta, hhi, max_drawdown}（§4.2 尾部风险指标）
    layer_a_count: int        # Layer A 候选池数量
    layer_b_count: int        # Layer B 高分池数量
    layer_c_count: int        # Layer C 观察名单数量
```

---

## 三、分阶段开发计划

### Phase 0：基础设施准备（3 天）

> **目标**：搭建新模块骨架，扩展数据接口，确保后续开发的数据基础就绪。

#### Task 0.0：评审决策清单确认（启动门禁）

> **对应框架 §10 的 11 项评审决策点**，在编码前逐项确认或调整默认值。此任务无代码产出，输出为一份决策记录文档。

| 决策点 | 默认值 | 确认/调整 |
|--------|--------|----------|
| 1. 硬止损比例 | -7% | 确认（A股日均波动2-3%，约2-3倍标差） |
| 2. 行业暴露上限 | 25%（申万一级） | 确认 |
| 3. 涨幅榜策略 | 保留为第五策略，权重10% | **需决策**：是否在 MVP 中纳入 |
| 4. 做空信号 | 仅标记不执行 | 确认（A股融券门槛高） |
| 5. 最大持仓天数 | 20日（基本面驱动可延至40日） | 确认 |
| 6. Sortino 目标 | > 1.0（首版） | 确认（v2 再追求 1.5） |
| 7. 信号有效期 | 2个交易日 | 确认 |
| 8. Layer B/C 权重 | 0.4 / 0.6 | **高敏感**：需 walk-forward 验证 |
| 9. Agent 权重分配 | 大师72% / 分析师28% | **高敏感**：需回测验证 |
| 10. 阈值再标定频率 | 月度，±0.05 | 确认 |
| 11. 策略资金容量 | 1-5亿AUM最优 | 确认 |

**交付物**：`docs/decisions/decision_log_v1.md`（含每项决策的确认理由或调整说明）

#### Task 0.1：项目结构搭建

| 子任务 | 文件 | 说明 |
|--------|------|------|
| 0.1.1 | `src/screening/__init__.py` | 创建 screening 包 |
| 0.1.2 | `src/screening/models.py` | 定义 StrategySignal / FusedScore / MarketState 等数据模型 |
| 0.1.3 | `src/portfolio/__init__.py` | 创建 portfolio 包 |
| 0.1.4 | `src/portfolio/models.py` | 定义 PositionPlan / ExitSignal / HoldingState 等数据模型 |
| 0.1.5 | `src/execution/__init__.py` | 创建 execution 包 |
| 0.1.6 | `src/execution/models.py` | 定义 LayerCResult / ExecutionPlan 等数据模型 |
| 0.1.7 | `src/monitoring/__init__.py` | 创建 monitoring 包 |

**验收标准**：所有包可正常 import，数据模型 Pydantic 验证通过。

#### Task 0.2：数据接口扩展

| 子任务 | 文件 | 新增接口 | 数据源 |
|--------|------|---------|--------|
| 0.2.1 | `src/tools/tushare_api.py` | `get_all_stock_basic()` → 全 A 股基本信息（代码/名称/上市日期/行业/市场/状态） | tushare `stock_basic` |
| 0.2.2 | `src/tools/tushare_api.py` | `get_daily_basic_batch(trade_date)` → 全市场当日基础面指标（PE/PB/换手率/成交额/总市值/流通市值） | tushare `daily_basic` |
| 0.2.3 | `src/tools/tushare_api.py` | `get_sw_industry_classification()` → 申万一级行业分类映射 | tushare `index_classify` + `index_member` |
| 0.2.4 | `src/tools/tushare_api.py` | `get_limit_list(trade_date)` → 当日涨跌停列表 | tushare `limit_list_d` |
| 0.2.5 | `src/tools/tushare_api.py` | `get_suspend_list(trade_date)` → 当日停牌列表 | tushare `suspend_d` |
| 0.2.6 | `src/tools/tushare_api.py` | `get_index_daily(index_code, ...)` → 指数日线行情（沪深300等） | tushare `index_daily` |
| 0.2.7 | `src/tools/akshare_api.py` | `get_realtime_quotes(tickers)` → 盘中实时行情（价格/成交量/成交额） | akshare `stock_zh_a_spot_em` |
| 0.2.8 | `src/tools/akshare_api.py` | `get_industry_realtime()` → 行业指数实时行情 | akshare `stock_board_industry_name_em` |
| 0.2.9 | `src/tools/akshare_api.py` | `get_money_flow(ticker)` → 主力资金流向 | akshare（需验证可用性） |
| 0.2.10 | `src/tools/tushare_api.py` | `get_northbound_flow(trade_date)` → 北向资金流向 | tushare `moneyflow_hsgt` |

**验收标准**：每个接口有独立的冒烟测试（调用一次，验证返回格式正确、数据非空）。

#### Task 0.3：回测指标扩展

| 子任务 | 文件 | 新增指标 |
|--------|------|---------|
| 0.3.1 | `src/backtesting/metrics.py` | Calmar Ratio = 年化收益 / 最大回撤 |
| 0.3.2 | `src/backtesting/metrics.py` | 盈亏比 = 平均盈利 / 平均亏损 |
| 0.3.3 | `src/backtesting/metrics.py` | 年化换手率 = 总交易额 / 平均净值 |
| 0.3.4 | `src/backtesting/metrics.py` | CVaR(95%) 历史模拟法 |
| 0.3.5 | `src/backtesting/metrics.py` | 组合 Beta（对沪深300） |
| 0.3.6 | `src/backtesting/metrics.py` | 胜率、交易次数统计（框架 §8.2 要求） |
| 0.3.7 | `src/backtesting/types.py` | 扩展 PerformanceMetrics 含新指标字段 |

**验收标准**：现有回测用例 `uv run pytest tests/backtesting/ -v` 全部通过 + 新指标在模拟数据上计算正确。

---

### Phase 1：Layer A — 候选池构建器（4 天）

> **目标**：实现全市场快筛，每日稳定输出 150~300 只候选池。
> **对应框架**：§1 先验约束矩阵 + §5.1 Step 1

#### Task 1.1：核心筛选逻辑

**文件**：`src/screening/candidate_pool.py`

```
输入：trade_date（交易日期）
输出：List[CandidateStock]（通过筛选的标的列表）

筛选规则（顺序执行）：
1. 获取全 A 股基本信息（~5000 只）
2. 排除 ST / *ST 标的（名称包含 ST）
3. 排除北交所标的（市场 = 'BJ' 或代码 8xxxxx / 4xxxxx）
4. 排除上市不满 60 个交易日的新股/次新股
5. 排除当日停牌标的
6. 排除当日涨停标的（买入排队失败）
7. 排除停牌超过 5 日后复牌未满 3 个正常交易日的标的
8. 排除近 20 日平均成交额 < 5000 万元的低流动性标的
9. 排除被冲突仲裁规则一标记的"回避冷却期"标的（15 个交易日）
```

#### Task 1.2：特殊事件处理

| 子任务 | 事件 | 实现 |
|--------|------|------|
| 1.2.1 | 除权除息 | 确认所有价格数据使用前复权（tushare adj=qfq） |
| 1.2.2 | 新股过滤 | 计算上市日期距今的交易日数，< 60 则排除 |
| 1.2.3 | 财报窗口期 | 4月/8月/10月自动检测，标记 `disclosure_risk=True` |
| 1.2.4 | 停牌复牌处理 | 查询停牌历史，复牌后需 3 个非涨跌停交易日 |
| 1.2.5 | 回避冷却期 | 维护 `cooldown_registry`（ticker → 到期日）持久化 JSON |

#### Task 1.3：候选池输出与缓存

| 子任务 | 说明 |
|--------|------|
| 1.3.1 | 候选池结果写入 `data/snapshots/candidate_pool_{date}.json` |
| 1.3.2 | 包含字段：ticker, name, industry_sw, market_cap, avg_volume_20d, listing_date, disclosure_risk |
| 1.3.3 | 增量缓存：当日已生成则跳过重新计算 |

#### Task 1.4：单元测试

| 测试 | 验证内容 |
|------|---------|
| test_exclude_st | ST 标的被正确过滤 |
| test_exclude_new_stock | 上市 < 60 日的标的被过滤 |
| test_exclude_low_liquidity | 成交额 < 5000 万的标的被过滤 |
| test_exclude_limit_up | 当日涨停的标的被过滤 |
| test_exclude_bj | 北交所标的被过滤 |
| test_cooldown | 冷却期内标的被过滤，到期后解除 |
| test_output_format | 输出 JSON 结构正确 |

**阶段验收**：`uv run python -m src.screening.candidate_pool --trade-date 2026-03-05` 输出 150~300 只标的，耗时 < 10 分钟。

---

### Phase 2：Layer B — 四策略评分 + 信号融合（7 天）

> **目标**：实现四策略独立评分、子因子聚合、市场状态自适应、冲突仲裁、加权融合。
> **对应框架**：§2 全部 + §3 全部

#### Task 2.1：子信号提取适配器

**文件**：`src/screening/strategy_scorer.py`

从现有 Agent 提取子信号，不调用 LLM，纯规则计算：

| 子任务 | 策略 | 复用来源 | 新增/适配 |
|--------|------|---------|-----------|
| 2.1.1 | 策略 A（趋势） | `technicals.py` → `calculate_trend_signals()` + `calculate_momentum_signals()` + `calculate_volatility_signals()` | 适配输出为 StrategySignal（方向/置信度/完整度）。**重要**：框架要求均线为 EMA(10/30/60)，现有代码使用 EMA(8/21/55)，必须在适配层重新计算而非修改原 Agent。`calculate_volatility_signals()` 作为趋势策略子因子纳入 |
| 2.1.2 | 策略 B（均值回归） | `technicals.py` → `calculate_mean_reversion_signals()` + `calculate_stat_arb_signals()` | 适配输出，增加 Hurst 判定逻辑 |
| 2.1.3 | 策略 C（基本面/估值） | `fundamentals.py` + `valuation.py` + `growth_agent.py` | 提取评分逻辑为纯函数，不走 LLM；需新增行业 PE 中位数对比 |
| 2.1.4 | 策略 D（事件/情绪） | `news_sentiment.py` + `sentiment.py` | 提取情绪分数为规则计算；新闻数量加权；事件衰减 $w(t) = e^{-0.35t}$ |

**关键设计决策**：
- Layer B 为**纯规则计算**，不调用 LLM（Layer C 才用 LLM），确保 200 只标的 5 分钟内完成
- 每个策略函数签名：`score_strategy_X(ticker, price_data, financial_data, ...) -> StrategySignal`
- **completeness 推断规则**（现有 Agent 无此字段，需在适配层派生）：
  - 数据完整时 completeness = 1.0
  - 缺少子因子时按缺失比例降低（如 5 个子因子缺 1 个则 completeness = 0.8）
  - 无数据时 completeness = 0，该策略权重重新分配给其余策略

#### Task 2.2：子因子聚合实现

**文件**：`src/screening/strategy_scorer.py`

实现 §2 子因子聚合规则：

```
对每个策略的 4~5 个子因子：
1. 等权计算方向投票：direction = sign(Σ w_k × d_k)
2. 加权平均置信度：confidence = Σ w_k × conf_k
3. 方向一致性折扣：confidence *= (多数方向子因子数 / 总子因子数)
4. 加权平均完整度：completeness = 加权平均（剔除 comp=0 的子因子，其权重重新分配给其余子因子）
5. 置信度截断至 [0, 100]
```

#### Task 2.3：市场状态检测器

**文件**：`src/screening/market_state.py`

| 子任务 | 指标 | 数据源 | 输出 |
|--------|------|--------|------|
| 2.3.1 | 沪深300 ADX(20) | `get_index_daily('000300.SH')` | trend_strength |
| 2.3.2 | 沪深300 ATR/Price (20日) | 同上 | volatility_ratio |
| 2.3.3 | 全市场涨停/跌停家数比 | `get_limit_list()` | sentiment_extreme |
| 2.3.4 | 两市成交额 | `get_daily_basic_batch()` 汇总 | volume_state |
| 2.3.5 | 北向资金连续流向 | `get_northbound_flow()` | northbound_trend |

输出：`MarketState` 对象 + 调整后的策略权重 dict + 仓位折算系数

**多指标优先级实现**（§3.2）：
1. 缩量市独立执行（降仓位不调权重）
2. ADX > 30 且 ATR/Price < 1.2% → 以 ADX 为准（趋势市）
3. 情绪极端独立叠加
4. 北向资金独立叠加
5. 叠加后统一归一化

#### Task 2.4：冲突仲裁引擎

**文件**：`src/screening/signal_fusion.py`

按优先级顺序实现四条仲裁规则：

| 规则 | 触发条件 | 动作 | 优先级 |
|------|---------|------|--------|
| 规则一：安全优先 | 任一策略强看跌(conf≥75) + 基本面方向=-1 | 强制“回避” + 进入 15 个交易日冷却期（基本面转正可提前解除，但至少 5 日） | 最高 |
| 规则二：时间框架分级 | 短周期 vs 长周期策略冲突 | 以市场状态调整后权重为基准，计算各策略绝对贡献度 |w_i×d_i×conf_i×comp_i|，趋势+情绪占总贡献 60%以上→短持，基本面+估值占 60%以上→长持，否则维持默认 | 高 |
| 规则三：趋势-回归互斥 | 趋势和均值回归反向强信号 | Hurst > 0.55 信趋势；< 0.45 信回归；中间均降权 50% | 中 |
| 规则四：共识加成 | ≥3 策略同向且均置信度 > 60% | 得分上浮 15%，截断至 [-1, +1] | 低 |

#### Task 2.5：信号融合与决策

**文件**：`src/screening/signal_fusion.py`

```
执行顺序：
1. 获取市场状态 → 调整基准权重
2. 执行仲裁规则 → 进一步修正权重
3. 归一化权重至 sum = 1
4. 计算 Score_B = Σ w_i × direction_i × confidence_i × completeness_i
5. 按阈值分档：强买入(>0.50) / 入池(0.35~0.50) / 中性 / 卖出 / 强卖出
```

#### Task 2.6：集成测试

| 测试 | 验证 |
|------|------|
| test_trend_market_weights | 趋势市下权重归一化正确 |
| test_safety_first_rule | 强看跌+基本面负面 → 强制回避 + 进入 15 日冷却期 |
| test_hurst_arbitration | Hurst > 0.55 时信任趋势 |
| test_consensus_bonus | 3+ 策略共识时上浮 15% |
| test_score_range | Score_B 始终在 [-1, +1] |
| test_cooldown_early_release | 基本面转正时冷却期提前解除（但不少于 5 日） |
| test_low_volume_position_scale | 缩量市仅降仓位不调权重 |
| test_event_decay | 事件衰减 $w(t)=e^{-0.35t}$ 权重计算正确 |
| test_completeness_derivation | completeness 按缺失子因子比例正确推断 |
| test_ema_period_override | 适配层使用 EMA(10/30/60) 而非原 Agent 的 EMA(8/21/55) |
| test_full_pipeline | 200 只标的 → 约 60 只高分池，耗时 < 5 分钟 |

**阶段验收**：对 2026-03-05 的全市场数据运行 Layer A + Layer B，输出约 60 只高分标的及其得分明细 JSON。

---

### Phase 3：仓位管理 + 退出级联（5 天）

> **目标**：实现四约束仓位计算、行业暴露控制、五层退出级联、涨跌停处理。
> **对应框架**：§4 全部

#### Task 3.1：行业暴露计算器

**文件**：`src/portfolio/industry_exposure.py`

| 子任务 | 说明 |
|--------|------|
| 3.1.1 | 加载申万一级行业分类映射（31 个行业） |
| 3.1.2 | 计算当前持仓的行业暴露度（各行业持仓市值 / 组合净值） |
| 3.1.3 | 计算 HHI 集中度指标 |
| 3.1.4 | 判定行业剩余可配额度 = 25% × NAV - 已有暴露 |

#### Task 3.2：增强仓位计算器

**文件**：`src/portfolio/position_calculator.py`

四约束取最小值：

```python
def calculate_position(ticker, score_final, portfolio, market_data, industry_data):
    vol_limit = portfolio.nav * vol_adjusted_ratio * corr_adjustment
    cash_limit = portfolio.available_cash
    liq_limit = avg_volume_20d * 0.02
    ind_limit = industry_remaining_quota

    base_shares = min(vol_limit, cash_limit, liq_limit, ind_limit) / current_price
    base_shares = (base_shares // 100) * 100  # 向下取整至 100

    # 信号强度联动（§4.1：使用 Score_final 而非 Score_B）
    if score_final > 0.50:
        exec_ratio = 1.0      # 强买入：满额建仓
    elif score_final >= 0.25:
        exec_ratio = 0.6      # 入池观察：60% 仓位，预留加仓空间
    else:
        exec_ratio = 0.0      # 不建仓（0~+0.25 对已持仓维持不变，由退出管理器管理）

    final_shares = int((base_shares * exec_ratio) // 100) * 100
    return final_shares
```

硬约束检查（不可覆盖）：
- 单票 ≤ 10% NAV（放宽至 12% 需**同时**满足三条件：Score_final > +0.50 + 同组无相关>0.7的已持仓 + 20日均额≥2亿且买入≤均额1%）
- 单行业 ≤ 25% NAV（申万一级 31 行业）
- 单日新开仓 ≤ 3 只（按 Score_final 排序取前 3）
- 单日交易额 ≤ 20% NAV
- 高相关性合并：Pearson > 0.8 → 合并视为同一敞口（由 correlation_cluster 提供）
- 停牌应急：停牌占仓 > 10% → 剩余持仓按比例减仓释放流动性
- 回撤预警 -10%（暂停新开仓）
- 回撤强制减仓 -15%（全组合缩减 50%）

尾部风险指标检查（§4.2）：
- CVaR(95%) > 3% NAV → 预警，禁止向高波标的加仓
- 组合 Beta > 1.3 → 增配低 Beta 标的
- 行业 HHI > 0.15 → 拒绝向头部行业增仓

#### Task 3.3：五层退出管理器

**文件**：`src/portfolio/exit_manager.py`

| 子任务 | 退出层级 | 实现要点 |
|--------|---------|---------|
| 3.3.1 | Level 1: 硬止损 | 浮亏 ≥ 7% → 次日市价卖出 |
| 3.3.2 | Level 2: 波动止损 | 收盘价 < 入场价 - 2×ATR(14)，且此线比 -7% 更紧 |
| 3.3.3 | Level 2.5: 浮盈回撤 | max_pnl ≥ 8% 后回落至 +1% 以下（与 L5 互斥） |
| 3.3.4 | Level 3: 逻辑止损 | 重新评估买入逻辑，趋势结构破坏则触发 |
| 3.3.5 | Level 4: 时间止损 | 持仓 > 20 日且收益 < 3%（与 L5 互斥） |
| 3.3.6 | Level 5: 分批止盈 | +15% 卖 50%；+25% 再卖剩余的 60%（即原仓位 30%）；最后 20% 移动止盈：从最高收益回落超过 max(5%, 最高收益×30%) 时清仓 |

**退出层级互斥关系**（§4.3）：
- L2.5 与 L5 互斥：已触发 L5 第一阶段止盈的剩余仓位，回撤保护由 L5 移动止盈接管
- L4 与 L5 互斥：已触发止盈分批的标的不再触发时间止损

**持仓状态跟踪**：`HoldingState` 需持久化（JSON/SQLite），记录入场价、最高浮盈、持仓天数、止盈阶段。

#### Task 3.4：涨跌停处理器

**文件**：`src/portfolio/limit_handler.py`

| 队列 | 入队条件 | 出队逻辑 |
|------|---------|---------|
| 待买队列 | T+1 涨停无法买入 | T+2 开板且得分 ≥ 原始 80% → 执行；连续 2 日涨停 → 移除 + 标记过热 30 日 |
| 待卖队列 | 止损触发但跌停无法卖出 | 次日集合竞价挂跌停价；连续 3 日跌停 → 预防性减仓其余持仓 |

#### Task 3.4.5：停牌应急处理器

**文件**：`src/portfolio/suspension_handler.py`

| 场景 | 触发条件 | 响应 |
|------|---------|------|
| 单票停牌占仓>10% | 持仓市值占比超阈值 | 剩余持仓按比例减仓释放流动性 |
| 复牌释放 | 停牌标的复牌 | 进入 3 日观察期（非涨跌停交易日），期间不加仓 |

#### Task 3.5：相关性增强

**文件**：`src/portfolio/correlation_cluster.py`

| 子任务 | 说明 |
|--------|------|
| 3.5.1 | 60 日滚动 Pearson 相关系数矩阵 |
| 3.5.2 | 聚类合并：传递性处理（A-B > 0.8, B-C > 0.8 → 合并为一组） |
| 3.5.3 | 市场状态修正：全市场中位相关 > 0.6 时，阈值从 0.8 收紧至 0.7 |

#### Task 3.6：单元测试

| 测试 | 验证 |
|------|------|
| test_position_min_constraint | 四约束取最小值正确 |
| test_round_to_100 | 向下取整至 100 的倍数 |
| test_industry_limit | 行业暴露超 25% 时拒绝新买入 |
| test_hard_stop_loss | 浮亏 7% 触发 L1 |
| test_trailing_stop | 浮盈 ≥ 8% 后回落至 1% 触发 L2.5 |
| test_staged_profit_take | 三阶段止盈比例正确（50%/30%/移动止盈） |
| test_l25_l5_mutual_exclusion | L2.5 浮盈回撤与 L5 分批止盈互斥 |
| test_l4_l5_mutual_exclusion | L4 时间止损与 L5 分批止盈互斥 |
| test_limit_up_queue | 涨停标的进入待买队列，T+2 逻辑正确 |
| test_limit_down_queue | 跌停待卖队列 + 连续 3 日跌停预防性减仓 |
| test_correlation_cluster | 传递性聚类合并正确 |
| test_correlation_market_correction | 全市场中位相关>0.6时阈值收紧至0.7 |
| test_suspend_emergency | 单票停牌占仓>10%时剩余持仓按比例减仓 |
| test_daily_trade_limit | 单日交易额不超过 20% NAV |
| test_cvar_warning | CVaR(95%) > 3% NAV 时禁止向高波标的加仓 |
| test_beta_rebalance | 组合 Beta > 1.3 时触发低 Beta 标的增配 |
| test_hhi_block | 行业 HHI > 0.15 时拒绝向头部行业增仓 |

**阶段验收**：给定一组模拟持仓和市场数据，仓位计算器和退出管理器输出符合所有硬约束。

---

### Phase 4：日度执行流水线（5 天）

> **目标**：将 Layer A → B → C → 仓位 → 退出串联为完整的 7 步日度流水线。
> **对应框架**：§5 全部

#### Task 4.1：Layer C 聚合器

> **说明**：此任务实现框架 §5.1 的 Layer C 聚合规则，是开发计划中的关键枢纽——将现有 LangGraph 18 Agent 的输出与 Layer B 得分融合为最终决策。

**文件**：`src/execution/layer_c_aggregator.py`

| 子任务 | 说明 |
|--------|------|
| 4.1.1 | Agent 权重配置：12 位投资大师各 6%（合计 72%），6 位技术分析师各 4.67%（合计 28%）——可从配置加载 |
| 4.1.2 | **Agent 输出标准化**：现有 Agent 输出 `{signal, confidence, reasoning}` 需转换为 `StrategySignal(direction, confidence, completeness)` 三元组。`signal` 映射：bullish→+1, neutral→0, bearish→-1。completeness 按 Agent 依赖数据的实际完整度推断（无数据则 completeness=0） |
| 4.1.3 | 计算 $Score_C = \sum_j w_j \times direction_j \times confidence_j \times completeness_j$，归一至 [-1, +1] |
| 4.1.4 | 计算 $Score_{final} = 0.4 \times Score_B + 0.6 \times Score_C$ |
| 4.1.5 | B/C 冲突处理（§5.1 规则6）：B 强买入(>0.50) + C 为负 → 降级为"入池观察"；B 为正 + C 强看跌(<-0.30) → 强制"回避" |
| 4.1.6 | 淘汰阈值：$Score_{final}$ < +0.25 的标的不进入观察名单 |
| 4.1.7 | 输出 `LayerCResult` 列表 |

**关键设计决策**：
- 此模块不调用 LLM，仅对现有 LangGraph 工作流输出做规则聚合
- Agent 输出需转换为标准 StrategySignal 格式（direction/confidence/completeness 三元组）
- 权重配置应外部化，便于后续回测调优（属于高敏感参数，见框架 §7.2）

#### Task 4.2：流水线编排器

**文件**：`src/execution/daily_pipeline.py`

```python
class DailyPipeline:
    def run_post_market(self, trade_date: str) -> ExecutionPlan:
        """T 日 15:00 后执行 Step 1~4"""
        # Step 1: Layer A 候选池
        candidates = self.candidate_pool.build(trade_date)

        # Step 2: Layer B 四策略评分
        market_state = self.market_state_detector.detect(trade_date)
        scored = self.strategy_scorer.score_batch(candidates, trade_date)
        fused = self.signal_fusion.fuse(scored, market_state)
        high_pool = [s for s in fused if s.score_b >= 0.35]  # ~60 只

        # Step 3: Layer C 多智能体深度分析（附录B 分层调用优化）
        # 先用低成本模型（GPT-4o-mini）筛全部 60 只
        agent_results = self.run_agent_analysis(high_pool, trade_date, model="fast")
        # Top 20 用高精度模型重新分析
        top_20 = sorted(high_pool, key=lambda s: s.score_b, reverse=True)[:20]
        if top_20:
            precise_results = self.run_agent_analysis(top_20, trade_date, model="precise")
            agent_results.update(precise_results)

        final_scores = self.layer_c_aggregator.aggregate(fused, agent_results)  # Task 4.1
        watchlist = [s for s in final_scores if s.score_final >= 0.25]  # ~10 只

        # Step 4: 生成执行计划（含退出检查）
        exits = self.exit_manager.check_all(self.portfolio, trade_date)
        plan = self.plan_generator.generate(watchlist, exits, self.portfolio, trade_date)
        return plan

    def run_pre_market(self, plan: ExecutionPlan, trade_date_t1: str):
        """T+1 日 09:15 前执行 Step 5"""
        plan = self.signal_decay.check(plan, trade_date_t1)
        return plan

    def run_intraday(self, plan: ExecutionPlan, trade_date_t1: str):
        """T+1 日 14:30 执行 Step 6~7"""
        confirmed = self.t1_confirmer.confirm(plan.buy_orders, trade_date_t1)
        exits = self.exit_manager.check_all(self.portfolio, trade_date_t1)
        return confirmed, exits
```

#### Task 4.3：T+1 确认执行器

**文件**：`src/execution/t1_confirmation.py`

三个确认条件（需满足 ≥ 2/3）：

| 条件 | 实现 | 数据源 |
|------|------|--------|
| 价格支撑 | 日内最低价 ≥ T 日 EMA(30) × 99% | akshare 实时/日线最低价 |
| 量价配合 | 累计成交量 ≥ 前 5 日同时段 80% 且 价格 > VWAP | akshare 实时/日线成交量 |
| 板块强度 | 所属行业排名前 50%（含尾盘异动容忍：个股涨跌幅强于行业指数 2 个百分点以上则仍通过） | akshare 行业指数/日线涨跌 |

**回测模式**：使用日线数据替代盘中数据（§5.2 回测处理说明）。

#### Task 4.4：信号衰减检查器

**文件**：`src/execution/signal_decay.py`

| 规则 | 实现 |
|------|------|
| 有效期 2 日 | T+2 仍在待买队列 → 重新计算得分，< 原始 80% 则移除 |
| 跳空取消 | T+1 跳空高开 > 1.5 × ATR → 取消买入 |
| 重大利空 | T+1 出现负面新闻 → 无条件取消（需新闻 API 检查） |

#### Task 4.5：执行计划生成器

**文件**：`src/execution/plan_generator.py`

输出标准化 JSON + 可读 Markdown 报告：

```json
{
  "date": "2026-03-06",
  "market_state": {"type": "trend", "adx": 32.5, "volume_state": "normal"},
  "strategy_weights": {"trend": 0.412, "mean_reversion": 0.098, ...},
  "buy_orders": [...],
  "sell_orders": [...],
  "pending_queues": {...},
  "portfolio_snapshot": {...},
  "risk_metrics": {"max_drawdown": -0.05, "cvar_95": -0.028, "hhi": 0.12}
}
```

#### Task 4.6：极端场景处理器

**文件**：`src/execution/crisis_handler.py`

| 场景 | 触发 | 响应 |
|------|------|------|
| 熔断日 | 沪深300日跌 > 5% 或跌停 > 500 家 | 全面防御模式：停止买入，仓位上限 30%，持续 5 日 |
| 缩量市 | 连续 3 日成交额 < 4000 亿 | 逐日减仓至半仓，待成交额恢复至 6000 亿以上 |
| 多票同时止损 | 系统性暴跌 | 按三级优先级排序卖出：①亏损幅度最大→②流动性最好→③策略贡献最低；超出单日 20%NAV 的止损单推迟至次日（享有最高执行优先级） |
| 回撤 -10% | 组合净值回撤 | 预警：暂停新开仓 |
| 回撤 -15% | 组合净值回撤 | 强制减仓 50% + 恢复协议（5日冷却→每满足一条恢复10%仓位：净值反弹>3%/沪深300连禁3日收阳/成交额>6000亿） |

#### Task 4.7：主入口改造

**文件**：`src/main.py`

新增 CLI 模式：

```bash
# 全流水线模式（新增）
uv run python src/main.py --pipeline --trade-date 2026-03-05

# 仅 Layer A+B（快筛模式）
uv run python src/main.py --screen-only --trade-date 2026-03-05

# 旧模式仍保留（指定 ticker 分析）
uv run python src/main.py --ticker 000001,300118
```

#### Task 4.8：集成测试

| 测试 | 验证 |
|------|------|
| test_full_pipeline_smoke | 全流程跑通，无异常 |
| test_layer_c_aggregation | Layer B 强买入 + Layer C 看跌 → 降级为“入池观察” |
| test_layer_c_bc_conflict_avoid | Layer B 正 + Layer C 强看跌(<-0.30) → 强制“回避” |
| test_layer_c_agent_conversion | Agent {signal, confidence} 正确转换为 StrategySignal 三元组 |
| test_crisis_defense_mode | 沪深300 跌 5% 时触发防御 |
| test_crisis_limit_down_500 | 跌停 > 500 家时触发全面防御模式 |
| test_recovery_protocol | 回撤 -15% 后恢复路径正确（5日冷却→三条件逐步恢复） |
| test_signal_decay_jump_gap | 跳空高开 > 1.5×ATR 时取消买入 |
| test_signal_decay_expiry | T+2 仍在待买队列且得分 < 原始 80% 则移除 |
| test_tiered_llm_call | 分层 LLM 调用（60只用fast模型 + Top20用precise模型） |
| test_plan_output_format | 执行计划 JSON 格式合规 |
| test_low_volume_shrink | 连续3日缩量(<4000亿)逐日减仓至半仓 |

**阶段验收**：`uv run python src/main.py --pipeline --trade-date 2026-03-05` 完整运行，输出执行计划文件。

---

### Phase 5：回测集成 + A/B 验证（5 天）

> **目标**：将新流水线接入回测引擎，与基线策略进行 A/B 对比。
> **对应框架**：§8 全部

#### Task 5.1：回测引擎适配

**文件**：`src/backtesting/engine.py`（改造）

| 子任务 | 说明 |
|--------|------|
| 5.1.1 | 新增 `BacktestMode.PIPELINE` 模式，调用 `DailyPipeline` 替代当前直接调 Agent |
| 5.1.2 | 回测循环中集成 Layer A → B → C → 仓位 → 退出全流程 |
| 5.1.3 | T+1 确认条件使用日线数据替代盘中数据 |
| 5.1.4 | 涨跌停限制：涨停不可买入、跌停不可卖出 |
| 5.1.5 | 滑点双档：常规 0.15%，低流动性（日均额<1亿）0.30% |
| 5.1.6 | 含手续费：佣金万 2.5 双边 + 印花税千 1 卖方 |
| 5.1.7 | **前视偏差标记**：MVP 阶段财报数据未加 45 天披露延迟（TD-01），回测报告中需显著标注此限制 |
| 5.1.8 | 回测样本包含已退市和被 ST 的历史数据（防止存活偏差，§7.1） |
| 5.1.9 | **小样本置信折扣**（§7.1）：某策略回测期间触发信号 < 30 次，该策略置信度自动打五折 |
| 5.1.10 | **股票代码去重**（§8.1）：按"代码+上市日期"唯一标识，防止退市后代码回收导致数据混淆（TD-02，MVP 标注限制） |

#### Task 5.2：A/B 实验框架

| 组别 | 策略流程 |
|------|---------|
| Group A（基线） | 涨幅榜筛股 → 多智能体分析 → 买入（现有 `batch_run_hedge_fund.py` 逻辑） |
| Group B（MVP-v1） | Layer A → Layer B → Layer C → T+1 确认 → 买入（新流水线） |

**时间窗口**：

| 用途 | 时段 |
|------|------|
| 训练/调参 | 2025-06-01 至 2025-12-31 |
| 样本外验证 | 2026-01-01 至 2026-02-28 |
| Walk-forward | 滚动 2 个月训练 + 1 个月测试 |

#### Task 5.3：评估报告生成

**文件**：`src/backtesting/output.py`（扩展）

输出 8 项核心指标的对比表：

| 指标 | Group A | Group B | 目标 |
|------|---------|---------|------|
| Sortino Ratio | — | — | > 1.0 |
| 最大回撤 | — | — | < 15% |
| Calmar Ratio | — | — | > 0.8 |
| Sharpe Ratio | — | — | > 0.8 |
| 盈亏比 | — | — | > 1.8 |
| 胜率 | — | — | > 42% |
| 年化换手率 | — | — | < 30x |
| 超额收益（vs 中证500） | — | — | > 0 |

统计检验：t 检验（p < 0.05）+ 1000 次 bootstrap + Mann-Whitney U。

#### Task 5.4：历史压力测试

对四个真实危机场景逐一回测：

| 场景 | 时段 | 验证重点 |
|------|------|---------|
| 2015.6 股灾 | 2015-06-15 ~ 2015-09-15 | 连续跌停处理、回撤触发 |
| 2016.1 熔断 | 2016-01-04 ~ 2016-01-07 | 全面防御模式 |
| 2020.2 疫情 | 2020-02-03 ~ 2020-03-23 | V 型反转中止损有效性 |
| 2024.9 急涨跌 | 2024-09-24 ~ 2024-10-18 | 追高过滤、涨停阻塞 |

**阶段验收**：A/B 对比报告生成，Group B 在样本外验证期的 Sortino > 1.0 且 MDD < 15%。

---

### Phase 6：监控告警 + 数据降级（3 天）

> **目标**：建设运行时监控能力，确保生产环境可观测。
> **对应框架**：§6.3~6.5, §10（评审决策清单部分集成至监控）

#### Task 6.1：数据源降级管理器

**文件**：`src/data/providers/failover.py`

| 故障 | 降级方案 |
|------|---------|
| tushare 不可用 | 切换 akshare；双重不可用 → 仅执行退出检查 |
| 数据异常 | 触发 validator 剔除异常标的 |
| LLM 不可用 | 跳过 Layer C，Layer B 高分池直接候选，仓位 × 60% |
| 新闻为空 | 情绪策略 completeness = 0 |

#### Task 6.2：策略漂移检测

**文件**：`src/monitoring/drift_detector.py`

| 监控项 | 方法 | 阈值 |
|--------|------|------|
| 信号分布偏移 | 每周 KS 检验 | p < 0.05 |
| 胜率滚动 | 近 20 笔交易胜率 | < 30% |
| 单日异常交易 | 买卖数 > μ + 2σ | 自动标记 |
| 策略贡献集中度 | 单策略加权贡献 > 70% | 仓位折算至 70% |

#### Task 6.3：数据质量监控

**文件**：`src/monitoring/data_quality.py`

| 指标 | 阈值 | 响应 |
|------|------|------|
| DQR（通过校验字段/应有字段） | < 98% | 禁止新开仓 |
| 关键字段缺失率 | > 1% | 对应策略 completeness = 0 |
| 行情延迟率 | > 5% | 延后评分 / 降级 |
| 异常值率 | > 0.5% | 剔除异常标的 |

#### Task 6.4：每日执行报告

**文件**：`src/monitoring/daily_report.py`

输出结构化报告（Markdown + JSON），含：
1. 执行摘要（日期/市场状态/策略权重）
2. 新买入列表
3. 退出列表（含退出层级）
4. 持仓快照
5. 异常记录

#### Task 6.5：运行手册与告警路由

**文件**：`src/monitoring/runbook.py`（新增）+ `docs/runbook.md`

> **对应框架 §6.5**——框架已完整定义事件分级与 SLA，需实现为代码中的告警路由逻辑。

| 事件级别 | 触发条件 | SLA | 自动响应 |
|---------|---------|-----|---------|
| **P1（阻断级）** | 数据源双活失败 / 下单逻辑异常 / 风险约束失效 | 15分钟 | 自动暂停新开仓 + 告警通知 |
| **P2（严重级）** | DQR < 98% / 连续3日信号漂移 / 成交阻塞异常 | 60分钟 | 自动降级执行（跳过 Layer C / 仅退出检查） |
| **P3（提示级）** | 单项指标轻微越阈 / 延迟上升 | 当日内 | 记录日志 + 纳入每日报告 |

**恢复操作**：恢复交易需双重确认（风控确认 + 量化研究确认），通过配置文件或 CLI 命令解除暂停。

**阶段验收**：模拟一次数据源故障场景，验证降级流程和告警路由正确运行。

---

### Phase 7：参数优化 + 模拟盘过渡（4 天）

> **目标**：参数敏感性分析，建立模拟盘过渡机制。
> **对应框架**：§7, §8.4

#### Task 7.1：参数敏感性分析器

**文件**：`scripts/parameter_sensitivity.py`

对高敏感参数做 ±20% 扰动：

| 参数 | 默认值 | 扰动范围 |
|------|--------|---------|
| EMA 周期 (10/30/60) | 10/30/60 | 8~12 / 24~36 / 48~72 |
| 硬止损 | -7% | -5.6% ~ -8.4% |
| 融合得分阈值 | +0.35/+0.50 | ±20% |
| 单票仓位上限 | 10% | 8% ~ 12% |
| Layer B/C 权重 | 0.4/0.6 | 0.3~0.5 / 0.5~0.7 |

输出：Sharpe 变化热力图 + 过拟合判定（变化 > 15% 则高风险）。

#### Task 7.2：阈值再标定模块

**文件**：`src/screening/signal_fusion.py`（扩展）

- 每月首个交易日按最近 60 个交易日的 Score_B 分布重估阈值
- 入池阈值参考 P80，强买入参考 P90
- 单月调整幅度 ≤ ±0.05
- 护栏：覆盖率 < 10% 或 > 40% 时回退

#### Task 7.3：模拟盘框架

| 阶段 | 最短时间 | 升级条件 |
|------|---------|---------|
| 纸上交易 | 4 周 | 执行偏差 < 回测偏差 1.5x |
| 小资金实盘 | 4 周 | Sortino > 0.8，MDD < 12% |
| 正式运行 | 持续 | 定期复盘 |

降级规则：连续 5 日偏差 > 2σ → 回退至前一阶段。

**阶段验收**：参数敏感性报告 + 模拟盘日志输出格式确认。

---

## 四、测试策略

### 4.1 测试分层

| 层级 | 范围 | 数量 | 位置 |
|------|------|------|------|
| 单元测试 | 每个函数/类的边界行为 | ~80 个 | `tests/screening/`, `tests/portfolio/`, `tests/execution/` |
| 集成测试 | Layer A→B→C 串联 | ~15 个 | `tests/integration/` |
| 回测验证 | 历史数据全流程 | 4 个压力场景 + 2 个 A/B 对比 | `tests/backtesting/` |
| 冒烟测试 | 数据接口可用性 | ~10 个 | `tests/data/` |

### 4.2 关键测试场景

| 场景 | 验证目的 | 分类 |
|------|---------|------|
| ST 股被过滤 | Layer A 正确性 | 单元 |
| 趋势市权重归一化 | 市场状态检测 + 权重调整 | 单元 |
| 安全优先规则触发回避 | 仲裁规则最高优先级生效 | 单元 |
| 四约束取最小值 | 仓位计算保守性 | 单元 |
| 硬止损 -7% 触发 | 退出级联最高优先级 | 单元 |
| 浮盈回撤止损与 L5 互斥 | L2.5 和 L5 不冲突 | 单元 |
| 涨停待买队列 T+2 逻辑 | 涨跌停协议完整性 | 集成 |
| Agent 输出到 StrategySignal 转换 | completeness 正确推断 | 单元 |
| CVaR/Beta/HHI 阈值检查 | 尾部风险约束生效 | 单元 |
| 小样本置信折扣 | 信号<30次自动打五折 | 回测 |
| 全流水线端到端 | Pipeline 无异常 | 集成 |
| 2015 股灾压力测试 | 极端场景生存性 | 回测 |
| Group A vs B 对比 | 策略有效性 | 回测 |

---

## 五、里程碑与交付物

| 里程碑 | Phases | 交付物 | 交付标准 |
|--------|--------|--------|---------|
| **M0: 基础就绪** | Phase 0 | 决策记录 + 数据接口冒烟测试 + 回测新指标 + 目录骨架 | 所有新接口返回有效数据，11 项决策确认 |
| **M1: 候选池上线** | Phase 1 | Layer A 候选池构建器 | 每日稳定输出 150~300 只 |
| **M2: 评分引擎上线** | Phase 2 | Layer B 评分 + 融合 + 仲裁 | 200→60 只，耗时 < 5 分钟 |
| **M3: 风控体系上线** | Phase 3 | 仓位计算 + 退出级联 + 涨跌停 | 硬约束 100% 覆盖 |
| **M4: 全流水线贯通** | Phase 4 | 日度 7 步执行流水线 + Layer C 聚合器 | 端到端运行无异常，Layer B/C 融合正确 |
| **M5: 回测验证通过** | Phase 5 | A/B 对比报告 + 压力测试 | Sortino > 1.0, MDD < 15% |
| **M6: 生产就绪** | Phase 6~7 | 监控告警 + 参数优化 + 模拟盘 | 降级流程验证 + 纸上交易启动 |

---

## 六、风险与缓解

| 风险 | 影响 | 概率 | 缓解方案 |
|------|------|------|---------|
| tushare 接口限流（200次/分钟） | Layer A 全市场筛选慢 | 高 | 批量接口 + 本地缓存 + 增量更新 |
| 策略 C 基本面数据不完整（行业 PE、分析师预期缺失） | 估值子因子精度低 | 高 | MVP 用历史增速线性外推，标注低可靠度 |
| Layer C 1080 次 LLM 调用成本/延迟 | 日运行成本过高或超时（GPT-4o-mini $0.15~0.30/日 vs GPT-4o $15~30/日） | 中 | 分层调用：低成本模型初筛 60 只 → 高精度模型仅 Top 20，可降成本约 60%（框架附录 B） |
| Hurst 指数在 0.45~0.55 区间占比过高 | 趋势-回归仲裁失效 | 中 | 该区间两策略均降权 50%，可接受 |
| 回测过拟合 | 实盘表现低于预期 | 中 | Walk-forward + 30% 盲测集 + 参数扰动 |
| 资金流向数据（akshare）不可用 | 策略 D 子因子缺失 | 中 | completeness 降低，权重自动归零 |
| 前视偏差（财报数据未加延迟） | 回测结果虚高 | 低 | MVP 标注限制，后续版本加 45 天延迟 |
| Agent completeness 概念缺失 | 现有 18 个 Agent 无 completeness 输出字段 | 中 | 在聚合层根据数据完整度推断；后续版本扩展 Agent 输出格式 |
| tushare 积分不足 | 批量查询命中 200 次/分钟限流 | 高 | 批量接口 + 本地缓存 + 合理 sleep；确认账户积分等级 |

---

## 七、技术债务追踪

以下事项在 MVP 中有意识地跳过，需在后续迭代中解决：

| 编号 | 技术债 | 影响 | 计划解决版本 |
|------|--------|------|------------|
| TD-01 | 财报数据未加 45 天披露延迟（前视偏差） | 基本面策略回测结果可能偏高 | v2.0 |
| TD-02 | 股票代码去重（退市后代码回收） | 极端情况下历史数据混淆 | v2.0 |
| TD-03 | 行业 PE 中位数使用线性外推替代 | 估值锚定精度低 | v1.5 |
| TD-04 | 相关系数仅用 Pearson（厚尾场景偏差） | 可能误判相关性 | v1.5 |
| TD-05 | 无 Markowitz/风险平价组合优化 | 仓位分配次优 | v2.0+ |
| TD-06 | 仅日频信号，无周频/月频嵌套 | 可能错过中长期拐点 | v2.0+ |
| TD-07 | 无券商 API 对接 | 仅输出执行计划文件 | v3.0 |
| TD-08 | 无 Brinson 归因 | 无法定量拆解超额来源 | v2.0 |
| TD-09 | Layer C Agent 权重固定（大师72%/分析师28%） | 可能不是最优配比 | v1.5（回测验证后调整） |
| TD-10 | 北交所标的排除 | 错过潜在机会 | v2.0（数据验证 + 参数适配后） |
| TD-11 | 策略拥挤监控缺失 | 持仓可能与市场热门题材高度重合 | v1.5 |
| TD-12 | 无宏观因子叠加 | 缺少利率/汇率/信用利差维度 | v2.0+ |

---

## 八、开发规范

### 8.1 代码规范

- **行长 420 字符**（与项目现有 black/flake8 配置一致）
- **类型注解必须**（PEP 484 + Pydantic 验证）
- **LLM 调用统一经 `src/utils/llm.call_llm()`**，不直接调用 provider
- **Agent 输出格式**：`{"signal": "bullish|bearish|neutral", "confidence": 0-100, "reasoning": "..."}`
- **进度跟踪**：`progress.update_status(agent_id, ticker, "Step")`

### 8.2 Git 工作流

- 每个 Phase 对应一个 feature 分支：`feature/phase-{N}-{name}`
- 每个 Task 对应一个 commit（或多个小 commit）
- Phase 完成后 PR 合并至 main，附带验收证据

### 8.3 数据接口规范

- 所有新增 tushare/akshare 接口函数需遵循现有模式（缓存 + 异常处理 + 日志）
- API 返回值需经 Pydantic model 验证
- 对外部 API 的调用需有 rate limiting（tushare 200 次/分钟）

---

## 九、依赖与前置条件

| 依赖项 | 状态 | 说明 |
|--------|------|------|
| tushare Pro Token | ✅ 已有 | 需确认积分是否足够批量查询 |
| akshare 库 | ✅ 已安装 | 需确认版本支持所需接口 |
| LLM API Key | ✅ 已有 | Layer C 需要（GPT-4o-mini / Claude Sonnet / Ollama） |
| Python 3.11~3.12 | ✅ 已配置 | 3.13+ 可能有兼容性问题 |
| uv 包管理器 | ✅ 已安装 | 用于运行和依赖管理 |
| 历史数据（2015~2026） | ⚠️ 需验证 | 压力测试需要 2015 年起的回测数据 |
| 申万行业分类数据 | ⚠️ 需获取 | tushare `index_classify` + `index_member` 接口 |
| 沪深300指数日线 | ⚠️ 需验证 | 市场状态检测器依赖 |
| 北向资金数据 | ⚠️ 需验证 | tushare `moneyflow_hsgt` 接口（市场状态检测器依赖） |

---

## 十、框架覆盖度矩阵

> 验证本开发计划对框架 v1.4 各章节的覆盖程度，确保无遗漏。

| 框架章节 | 内容 | 对应 Phase/Task | 覆盖度 | 备注 |
|---------|------|----------------|--------|------|
| §0 执行摘要 | 目标函数定义 | Phase 5 评估指标 | ✅ | Sortino 为第一衡量 |
| §1 先验约束矩阵 | A 股硬事实 + 特殊事件 | Phase 1 Task 1.1~1.2 | ✅ | |
| §2 四类策略评估 | 4 策略 + 子因子定义 + 聚合规则 | Phase 2 Task 2.1~2.2 | ✅ | |
| §3.1 融合公式 | Score_B 计算 + 阈值再标定 | Phase 2 Task 2.5 + Phase 7 Task 7.2 | ✅ | |
| §3.2 市场状态自适应 | 5 指标 + 优先级规则 | Phase 2 Task 2.3 | ✅ | |
| §3.3 冲突仲裁 | 4 规则 + 优先级 | Phase 2 Task 2.4 | ✅ | |
| §3.4 决策阈值 | 5 档分级 | Phase 2 Task 2.5 | ✅ | |
| §4.1 仓位计算 | 4 约束 + 信号联动 | Phase 3 Task 3.2 | ✅ | |
| §4.2 硬约束矩阵 | 9 项 + CVaR + Beta + HHI | Phase 3 Task 3.1~3.5 | ✅ | |
| §4.3 五层退出级联 | L1~L5 + 互斥规则 | Phase 3 Task 3.3 | ✅ | |
| §4.4 涨跌停协议 | 待买/待卖队列 | Phase 3 Task 3.4 | ✅ | |
| §5.1 执行时序 | 7 步 + Layer C 聚合规则 | Phase 4 Task 4.1~4.2 | ✅ | |
| §5.2 T+1 确认条件 | 3 条量化定义 + 盘中数据源 | Phase 4 Task 4.3 | ✅ | |
| §5.3 信号衰减 | 有效期 + 跳空 + 利空 | Phase 4 Task 4.4 | ✅ | |
| §6.1~6.2 极端场景 + 恢复 | 熔断 + 暴跌 + 恢复协议 | Phase 4 Task 4.6 | ✅ | |
| §6.3 数据降级 | 四种故障场景 | Phase 6 Task 6.1 | ✅ | |
| §6.4 监控告警 + DQR | 漂移 + 数据质量 + 报告 | Phase 6 Task 6.2~6.4 | ✅ | |
| §6.5 运行手册 | P1/P2/P3 事件分级 | Phase 6 Task 6.5 | ✅ | 已展开为完整任务（P1/P2/P3 SLA + 自动响应 + 恢复操作） |
| §7.1 过拟合防护 | 6 类风险 + 缓解 | Phase 5 Task 5.1.8~5.1.10 | ✅ | 存活偏差（Task 5.1.8）+ 小样本陷阱（Task 5.1.9）已显式实现 |
| §7.2 参数敏感性分级 | 高/中/低三级 | Phase 7 Task 7.1 | ✅ | |
| §8.1 回测硬要求 | 8 项 | Phase 5 Task 5.1 | ✅ | 前视偏差/代码去重标为 TD，已在 Task 5.1.7/5.1.10 显式标注 |
| §8.2 评估指标 | 8 指标 + 目标 | Phase 5 Task 5.3 | ✅ | |
| §8.3 A/B 实验 | 分组 + 统计检验 | Phase 5 Task 5.2 | ✅ | |
| §8.4 模拟盘过渡 | 三阶段 + 降级规则 | Phase 7 Task 7.3 | ✅ | |
| §9 实现映射 | 复用 + 新增建议 | 二、架构设计 | ✅ | 目录结构有意偏离 §9.2 建议 |
| §10 评审决策清单 | 11 项决策点 | Phase 0 Task 0.0 | ✅ | 已在 Phase 0 启动前作为门禁任务，逐11项确认 |
| §11 策略容量估算 | AUM 分级 | 待建模块表（P3） | ⚠️ | 框架明确三档容量分析：1-5亿最优 / 5-10亿需调流动性下限 / >10亿超MVP范围 |
| §12 框架边界 | 明确不做的 6 项 | 七、技术债追踪 | ✅ | 对应 TD-05~TD-08 |
