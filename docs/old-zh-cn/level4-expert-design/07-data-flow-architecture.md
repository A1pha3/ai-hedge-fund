# 数据流架构与缓存策略 ⭐⭐⭐⭐

> **📘 Level 4 专家设计**
>
> 本文档深入探讨 AI Hedge Fund 系统中数据流架构与缓存策略的设计与实现。完成本章节后，你将能够理解数据在系统中的流动方式，掌握缓存机制的核心原理，并具备优化数据访问性能的能力。

---

## 学习目标

完成本章节学习后，你将能够：

### 基础目标（必掌握）
- [ ] 理解数据在系统中的完整流动路径
- [ ] 掌握缓存机制的核心概念和实现
- [ ] 理解数据模型与 API 设计
- [ ] 能够阅读数据层的源代码

### 进阶目标（建议掌握）
- [ ] 能够自定义缓存策略
- [ ] 理解数据一致性与性能的关系
- [ ] 能够进行数据访问性能优化
- [ ] 理解分布式数据访问模式

### 专家目标（挑战）
- [ ] 设计多级缓存架构
- [ ] 实现数据预取和预测性加载
- [ ] 构建数据质量监控系统
- [ ] 实现分布式缓存方案

**预计学习时间**：6-12 小时

---

## 1. 数据流架构概述

### 1.1 为什么需要精心设计数据流？

在 AI Hedge Fund 系统中，数据是整个决策流程的基石。从外部 API 获取财务数据，到智能体分析，再到最终的交易决策，数据贯穿整个系统。

```
数据流全景图：

┌──────────────────────────────────────────────────────────────────────────┐
│                           外部数据源层                                     │
│                                                                          │
│   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐     │
│   │  Financial       │  │   News API       │  │   SEC Filings   │     │
│   │  Datasets API   │  │                  │  │                  │     │
│   └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘     │
└────────────┼──────────────────────┼──────────────────────┼───────────────┘
             │                      │                      │
             ▼                      ▼                      ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                           数据获取层                                       │
│                                                                          │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    API 客户端模块                               │   │
│   │  • 请求构建与参数验证                                           │   │
│   │  • 响应解析与模型验证                                           │   │
│   │  • 错误处理与重试逻辑                                           │   │
│   │  • 速率限制 (Rate Limiting)                                    │   │
│   └─────────────────────────────────────────────────────────────────┘   │
└────────────┬────────────────────────────────────────────────────┬─────────┘
             │                                                    │
             ▼                                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                           缓存层                                          │
│                                                                          │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────┐ │
│   │ 价格数据缓存  │  │财务指标缓存  │  │  新闻缓存    │  │ ...     │ │
│   └──────────────┘  └──────────────┘  └──────────────┘  └──────────┘ │
└────────────┬────────────────────────────────────────────────────┬─────────┘
             │                                                    │
             ▼                                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                           数据模型层                                       │
│                                                                          │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                   Pydantic 数据模型                             │   │
│   │  • Price, FinancialMetrics, LineItem, InsiderTrade, CompanyNews│   │
│   │  • 类型安全 • 自动验证 • JSON 序列化                           │   │
│   └─────────────────────────────────────────────────────────────────┘   │
└────────────┬────────────────────────────────────────────────────┬─────────┘
             │                                                    │
             ▼                                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                           智能体消费层                                     │
│                                                                          │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                 │
│   │ 价值投资     │  │ 成长投资     │  │ 风险管理    │                 │
│   │ 智能体       │  │ 智能体       │  │ 智能体      │                 │
│   └──────────────┘  └──────────────┘  └──────────────┘                 │
└──────────────────────────────────────────────────────────────────────────┘
```

### 1.2 数据类型分类

在我们的系统中，数据可以分为以下几类：

| 数据类型 | 获取频率 | 更新周期 | 典型用途 | 缓存策略 |
|----------|----------|----------|----------|----------|
| 价格数据 | 高 | 实时/日 | 风险计算、VaR | 短期缓存 |
| 财务指标 | 中 | 季度 | 价值分析 | 中期缓存 |
| 财务明细 | 中 | 季度 | 深度分析 | 中期缓存 |
| 新闻数据 | 高 | 实时 | 情绪分析 | 短期缓存 |
| 内幕交易 | 低 | 日/周 | 补充分析 | 长期缓存 |

---

## 2. 数据获取层设计

### 2.1 API 客户端架构

```python
# src/tools/api.py

def _make_api_request(
    url: str,
    headers: dict,
    method: str = "GET",
    json_data: dict = None,
    max_retries: int = 3
) -> requests.Response:
    """
    API 请求核心函数
    
    设计要点：
    1. 指数退避策略 (Exponential Backoff)
    2. 速率限制处理 (Rate Limiting)
    3. 错误分类与处理
    4. 重试机制
    """
    for attempt in range(max_retries + 1):
        # 发送请求
        if method.upper() == "POST":
            response = requests.post(url, headers=headers, json=json_data)
        else:
            response = requests.get(url, headers=headers)
        
        # 速率限制处理 (HTTP 429)
        if response.status_code == 429 and attempt < max_retries:
            # 线性退避：60s, 90s, 120s...
            delay = 60 + (30 * attempt)
            print(f"Rate limited (429). Attempt {attempt + 1}/{max_retries + 1}. "
                  f"Waiting {delay}s before retrying...")
            time.sleep(delay)
            continue
        
        # 返回响应（成功、其他错误、或最终的 429）
        return response
    
    return response  # 最后的响应（可能是 429 或错误）


def get_prices(
    ticker: str,
    start_date: str,
    end_date: str,
    api_key: str = None
) -> list[Price]:
    """
    获取股票价格数据
    
    流程：
    1. 构建缓存键
    2. 检查缓存
    3. 缓存命中 → 返回缓存数据
    4. 缓存未命中 → 调用 API
    5. 解析响应 → 存入缓存 → 返回
    """
    # 1. 构建缓存键
    cache_key = f"{ticker}_{start_date}_{end_date}"
    
    # 2. 检查缓存
    if cached_data := _cache.get_prices(cache_key):
        return [Price(**price) for price in cached_data]
    
    # 3. 构建 API 请求
    headers = {}
    financial_api_key = api_key or os.environ.get("FINANCIAL_DATASETS_API_KEY")
    if financial_api_key:
        headers["X-API-KEY"] = financial_api_key
    
    url = (f"https://api.financialdatasets.ai/prices/"
           f"?ticker={ticker}&interval=day&interval_multiplier=1"
           f"&start_date={start_date}&end_date={end_date}")
    
    response = _make_api_request(url, headers)
    if response.status_code != 200:
        return []
    
    # 4. 解析响应
    try:
        price_response = PriceResponse(**response.json())
        prices = price_response.prices
    except Exception:
        return []
    
    if not prices:
        return []
    
    # 5. 存入缓存并返回
    _cache.set_prices(cache_key, [p.model_dump() for p in prices])
    return prices
```

### 2.2 数据模型设计

```python
# src/data/models.py

from pydantic import BaseModel, Field
from typing import Optional
from datetime import date


class Price(BaseModel):
    """价格数据模型"""
    time: date = Field(description="交易日期")
    open: float = Field(description="开盘价")
    high: float = Field(description="最高价")
    low: float = Field(description="最低价")
    close: float = Field(description="收盘价")
    volume: int = Field(description="成交量")
    adjusted_close: Optional[float] = Field(
        default=None,
        description="调整后收盘价（考虑分红拆股）"
    )
    
    # 计算属性
    @property
    def daily_return(self) -> float:
        """计算日收益率（需要前一日收盘价）"""
        # 此属性需要上下文，在实际计算时通过 DataFrame 处理
        pass


class FinancialMetrics(BaseModel):
    """财务指标模型"""
    ticker: str
    report_period: date
    period: str = Field(description="期间类型：annual、quarterly、ttm")
    
    # 估值指标
    pe_ratio: Optional[float] = Field(default=None, description="市盈率")
    pb_ratio: Optional[float] = Field(default=None, description="市净率")
    ps_ratio: Optional[float] = Field(default=None, description="市销率")
    
    # 盈利能力
    gross_margin: Optional[float] = Field(default=None, description="毛利率")
    net_margin: Optional[float] = Field(default=None, description="净利率")
    roe: Optional[float] = Field(default=None, description="净资产收益率")
    roa: Optional[float] = Field(default=None, description="总资产收益率")
    
    # 财务健康
    debt_to_equity: Optional[float] = Field(default=None, description="负债权益比")
    current_ratio: Optional[float] = Field(default=None, description="流动比率")
    
    # 成长性
    revenue_growth: Optional[float] = Field(description="收入增长率")
    earnings_growth: Optional[float] = Field(description="盈利增长率")


class LineItem(BaseModel):
    """财务报表明细项目"""
    ticker: str
    report_period: date
    period: str
    
    # 损益表项目
    revenue: Optional[float] = Field(default=None, description="营业收入")
    gross_profit: Optional[float] = Field(default=None, description="毛利润")
    operating_income: Optional[float] = Field(
        default=None, 
        description="营业收入"
    )
    net_income: Optional[float] = Field(default=None, description="净利润")
    eps: Optional[float] = Field(default=None, description="每股收益")
    
    # 资产负债表项目
    total_assets: Optional[float] = Field(default=None, description="总资产")
    total_liabilities: Optional[float] = Field(
        default=None, 
        description="总负债"
    )
    shareholders_equity: Optional[float] = Field(
        default=None, 
        description="股东权益"
    )
    
    # 现金流量表项目
    operating_cash_flow: Optional[float] = Field(
        default=None, 
        description="经营活动现金流"
    )
    free_cash_flow: Optional[float] = Field(
        default=None, 
        description="自由现金流"
    )
    capital_expenditure: Optional[float] = Field(
        default=None, 
        description="资本支出"
    )
```

---

## 3. 缓存机制深度解析

### 3.1 缓存架构设计

```python
# src/data/cache.py

class Cache:
    """
    内存缓存实现
    
    设计特点：
    1. 内存缓存：快速访问
    2. 多类型支持：价格、财务、新闻等
    3. 数据合并：增量更新避免重复
    4. 键值存储：O(1) 查找复杂度
    """
    
    def __init__(self):
        # 按数据类型分区
        self._prices_cache: dict[str, list[dict[str, any]]] = {}
        self._financial_metrics_cache: dict[str, list[dict[str, any]]] = {}
        self._line_items_cache: dict[str, list[dict[str, any]]] = {}
        self._insider_trades_cache: dict[str, list[dict[str, any]]] = {}
        self._company_news_cache: dict[str, list[dict[str, any]]] = {}
    
    def _merge_data(
        self,
        existing: list[dict] | None,
        new_data: list[dict],
        key_field: str
    ) -> list[dict]:
        """
        增量数据合并
        
        避免重复数据：
        - 已有数据的键值集合
        - 仅添加不存在的新数据
        - 保持原有数据顺序
        
        示例：
        existing = [{period: '2024Q1'}, {period: '2024Q2'}]
        new_data = [{period: '2024Q2'}, {period: '2024Q3'}]
        result  = [{period: '2024Q1'}, {period: '2024Q2'}, {period: '2024Q3'}]
        """
        if not existing:
            return new_data
        
        # O(1) 查找
        existing_keys = {item[key_field] for item in existing}
        
        # 追加不存在的项
        merged = existing.copy()
        merged.extend([
            item for item in new_data 
            if item[key_field] not in existing_keys
        ])
        
        return merged
    
    # ===== 价格数据 =====
    
    def get_prices(self, ticker: str) -> list[dict[str, any]] | None:
        """获取缓存的价格数据"""
        return self._prices_cache.get(ticker)
    
    def set_prices(self, ticker: str, data: list[dict[str, any]]):
        """
        存储价格数据
        
        使用时间戳作为合并键
        """
        self._prices_cache[ticker] = self._merge_data(
            self._prices_cache.get(ticker),
            data,
            key_field="time"
        )
    
    # ===== 财务指标 =====
    
    def get_financial_metrics(self, ticker: str) -> list[dict[str, any]]:
        """获取缓存的财务指标"""
        return self._financial_metrics_cache.get(ticker)
    
    def set_financial_metrics(self, ticker: str, data: list[dict[str, any]]):
        """
        存储财务指标
        
        使用报告期作为合并键
        """
        self._financial_metrics_cache[ticker] = self._merge_data(
            self._financial_metrics_cache.get(ticker),
            data,
            key_field="report_period"
        )
    
    # ===== 其他数据类型... =====


# 全局缓存实例
_cache = Cache()


def get_cache() -> Cache:
    """获取全局缓存实例"""
    return _cache
```

### 3.2 缓存策略模式

```python
# 缓存策略模式

from enum import Enum
from datetime import datetime, timedelta
from typing import TypeVar, Generic, Optional, Callable
import json
import hashlib

T = TypeVar('T')


class CacheStrategy(Enum):
    """缓存策略类型"""
    CACHE_FIRST = "cache_first"       # 缓存优先
    NETWORK_FIRST = "network_first"   # 网络优先
    STALE_WHILE_REVALIDATE = "stale_while_revalidate"  # 缓存重用
    CACHE_ONLY = "cache_only"         # 仅缓存
    NETWORK_ONLY = "network_only"     # 仅网络


class CacheEntry(Generic[T]):
    """缓存条目"""
    value: T
    timestamp: datetime
    ttl: Optional[timedelta]  # Time To Live
    
    @property
    def is_expired(self) -> bool:
        if self.ttl is None:
            return False
        return datetime.now() - self.timestamp > self.ttl


class EnhancedCache:
    """
    增强缓存实现
    
    支持：
    1. TTL (Time To Live)
    2. LRU 淘汰
    3. 多种缓存策略
    4. 统计信息
    """
    
    def __init__(self, max_size: int = 1000):
        self._cache: dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0
        }
    
    def get(
        self,
        key: str,
        strategy: CacheStrategy = CacheStrategy.CACHE_FIRST,
        network_fetcher: Optional[Callable] = None
    ) -> Optional[any]:
        """
        获取缓存数据
        
        根据策略选择不同的获取方式
        """
        if strategy == CacheStrategy.CACHE_FIRST:
            return self._get_cache_first(key)
        elif strategy == CacheStrategy.NETWORK_FIRST:
            return self._get_network_first(key, network_fetcher)
        elif strategy == CacheStrategy.STALE_WHILE_REVALIDATE:
            return self._get_stale_while_revalidate(key, network_fetcher)
        else:
            return self._get_cache_first(key)
    
    def _get_cache_first(self, key: str) -> Optional[any]:
        """缓存优先策略"""
        entry = self._cache.get(key)
        
        if entry is None:
            self._stats["misses"] += 1
            return None
        
        if entry.is_expired:
            self._stats["misses"] += 1
            del self._cache[key]
            return None
        
        self._stats["hits"] += 1
        return entry.value
    
    def _get_network_first(
        self,
        key: str,
        network_fetcher: Optional[Callable]
    ) -> Optional[any]:
        """网络优先策略"""
        if network_fetcher:
            # 先尝试网络
            value = network_fetcher()
            if value:
                self.set(key, value)
                return value
        
        # 网络失败，使用缓存
        return self._get_cache_first(key)
    
    def _get_stale_while_revalidate(
        self,
        key: str,
        network_fetcher: Optional[Callable]
    ) -> Optional[any]:
        """
        缓存重用策略
        
        1. 立即返回缓存数据（快）
        2. 异步更新缓存（后台）
        3. 适用于不关键的数据
        """
        entry = self._cache.get(key)
        
        if entry:
            # 立即返回缓存
            self._stats["hits"] += 1
            
            # 后台异步更新
            if entry.is_expired and network_fetcher:
                # 实际实现中应该是异步任务
                try:
                    value = network_fetcher()
                    if value:
                        self.set(key, value)
                except Exception:
                    pass  # 更新失败不影响返回
            
            return entry.value
        
        # 无缓存，从网络获取
        self._stats["misses"] += 1
        if network_fetcher:
            value = network_fetcher()
            if value:
                self.set(key, value)
            return value
        
        return None
    
    def set(self, key: str, value: any, ttl: Optional[timedelta] = None):
        """
        存储缓存
        
        实现 LRU 淘汰
        """
        # 淘汰最老的条目
        if len(self._cache) >= self._max_size:
            oldest_key = min(
                self._cache.keys(),
                key=lambda k: self._cache[k].timestamp
            )
            del self._cache[oldest_key]
            self._stats["evictions"] += 1
        
        self._cache[key] = CacheEntry(
            value=value,
            timestamp=datetime.now(),
            ttl=ttl
        )
    
    def get_stats(self) -> dict:
        """获取缓存统计"""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total if total > 0 else 0
        
        return {
            **self._stats,
            "hit_rate": f"{hit_rate:.2%}",
            "size": len(self._cache)
        }
```

---

## 4. 数据流与状态管理

### 4.1 LangGraph 状态流

```python
# src/graph/state.py

from typing_extensions import Annotated, Sequence, TypedDict
import operator
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    """
    智能体系统状态
    
    设计要点：
    1. 消息流：累积而非覆盖
    2. 数据流：合并而非替换
    3. 元数据：追踪进度和控制信息
    """
    
    # 消息历史：记录智能体之间的对话
    # 使用 operator.add 意味着每次更新是追加而非覆盖
    messages: Annotated[Sequence[BaseMessage], operator.add]
    
    # 数据存储：存储分析数据
    # 使用 merge_dicts 意味着每次更新是合并而非替换
    data: Annotated[dict[str, any], merge_dicts]
    
    # 元数据：系统控制信息
    # 例如：进度、配置、日志选项
    metadata: Annotated[dict[str, any], merge_dicts]


def merge_dicts(a: dict[str, any], b: dict[str, any]) -> dict[str, any]:
    """
    字典合并函数
    
    用于 LangGraph 的状态更新
    后续的值会覆盖前面的值
    """
    return {**a, **b}
```

### 4.2 数据流动画

```
数据在 LangGraph 中的流动：

时间 →

┌──────────────────────────────────────────────────────────────────────┐
│ Step 1: 初始化状态                                                   │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  AgentState:                                                         │
│  {                                                                   │
│    messages: [],                                                     │
│    data: {                                                           │
│      tickers: ["AAPL", "MSFT"],                                     │
│      start_date: "2024-01-01",                                      │
│      end_date: "2024-12-31",                                        │
│      portfolio: { cash: 100000 }                                     │
│    },                                                                │
│    metadata: { show_reasoning: true }                               │
│  }                                                                   │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Step 2: 数据获取 → Risk Management Agent                            │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  AgentState:                                                         │
│  {                                                                   │
│    messages: [RiskManagementMessage],                               │
│    data: {                                                           │
│      ...previous_data...,                                           │
│      volatility_data: { AAPL: 0.25, MSFT: 0.22 },                  │
│      current_prices: { AAPL: 185.50, MSFT: 378.91 },                │
│      risk_limits: { AAPL: 10000, MSFT: 10000 }                     │
│    },                                                                │
│    ...                                                               │
│  }                                                                   │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Step 3-20: 智能体分析（并行/顺序执行）                                │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  AgentState:                                                         │
│  {                                                                   │
│    messages: [...18 个智能体的消息],                                  │
│    data: {                                                           │
│      ...previous_data...,                                            │
│      analyst_signals: {                                              │
│        "warren_buffett_agent": {                                    │
│          "AAPL": { signal: "bullish", confidence: 85 },             │
│          "MSFT": { signal: "bullish", confidence: 80 }              │
│        },                                                            │
│        "peter_lynch_agent": {                                        │
│          "AAPL": { signal: "neutral", confidence: 60 },            │
│          ...                                                         │
│        }                                                             │
│      }                                                               │
│    },                                                                │
│    ...                                                               │
│  }                                                                   │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Step 21: 投资组合管理 → Portfolio Manager                           │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  AgentState:                                                         │
│  {                                                                   │
│    messages: [...所有消息 + PortfolioDecisionMessage],               │
│    data: {                                                           │
│      ...previous_data...,                                            │
│      portfolio_decisions: {                                          │
│        "AAPL": { action: "buy", quantity: 100, confidence: 75 },   │
│        "MSFT": { action: "hold", quantity: 0, confidence: 65 }      │
│      }                                                               │
│    },                                                                │
│    ...                                                               │
│  }                                                                   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 5. 性能优化策略

### 5.1 数据访问优化

```python
# 性能优化技巧

# 1. 批量获取数据
def get_multiple_prices(tickers: list[str], start_date: str, end_date: str):
    """
    批量获取多只股票价格
    
    优于逐个获取：
    - 减少网络往返次数
    - 更好地利用 API 批量接口
    """
    prices = {}
    for ticker in tickers:
        prices[ticker] = get_prices(ticker, start_date, end_date)
    return prices


# 2. 并行数据获取
from concurrent.futures import ThreadPoolExecutor
import asyncio

async def get_prices_async(tickers: list[str], start_date: str, end_date: str):
    """
    异步并行获取价格数据
    
    显著减少总等待时间
    """
    loop = asyncio.get_event_loop()
    
    # 使用线程池并行执行
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            loop.run_in_executor(
                executor,
                get_prices,
                ticker, start_date, end_date
            )
            for ticker in tickers
        ]
        
        results = await asyncio.gather(*futures)
    
    return dict(zip(tickers, results))


# 3. 预取数据
class DataPrefetcher:
    """
    数据预取器
    
    预测下一步可能需要的数据，提前加载
    """
    
    def __init__(self):
        self._prefetch_queue = asyncio.Queue()
    
    async def prefetch_for_tickers(
        self,
        tickers: list[str],
        date_range: tuple[str, str]
    ):
        """预取股票相关数据"""
        prefetch_tasks = [
            # 价格数据
            get_prices(ticker, date_range[0], date_range[1])
            # 财务指标
            get_financial_metrics(ticker, date_range[1])
            # 新闻数据
            get_company_news(ticker, date_range[0], date_range[1])
            for ticker in tickers
        ]
        
        await asyncio.gather(*prefetch_tasks, return_exceptions=True)
```

### 5.2 缓存优化

```python
# 缓存优化示例

# 1. 多级缓存
class MultiLevelCache:
    """
    多级缓存架构
    
    L1: 内存缓存（最快，容量小）
    L2: 磁盘缓存（中等，容量大）
    L3: API 缓存（最慢，容量无限）
    """
    
    def __init__(self):
        self._memory_cache = {}  # L1
        self._disk_cache = DiskCache()  # L2
    
    def get(self, key: str):
        # L1 查找
        if key in self._memory_cache:
            return self._memory_cache[key]
        
        # L2 查找
        value = self._disk_cache.get(key)
        if value:
            self._memory_cache[key] = value  # 升级到 L1
            return value
        
        # L3 (API)
        return None


# 2. 缓存键设计
def generate_cache_key(ticker: str, start_date: str, end_date: str) -> str:
    """
    生成缓存键
    
    最佳实践：
    - 包含所有相关参数
    - 使用哈希处理长参数
    - 保持键的可读性（调试用）
    """
    params = f"{ticker}_{start_date}_{end_date}"
    return hashlib.md5(params.encode()).hexdigest()


# 3. 缓存预热
def warm_up_cache(tickers: list[str]):
    """
    缓存预热
    
    在系统启动时加载常用数据
    """
    for ticker in tickers:
        # 预取最近 5 年的年度数据
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=5*365)).strftime("%Y-%m-%d")
        
        get_prices(ticker, start_date, end_date)
        get_financial_metrics(ticker, end_date)
```

---

## 6. 常见模式与反模式

### 6.1 最佳实践

**模式一：缓存键包含完整参数**

```python
# ✅ 正确：包含所有影响结果的参数
def get_cache_key(ticker, start_date, end_date, interval="day"):
    return f"{ticker}_{interval}_{start_date}_{end_date}"

# ❌ 错误：参数不完整
def get_cache_key(ticker):
    return ticker  # 丢失日期范围信息
```

**模式二：增量更新**

```python
# ✅ 正确：合并增量数据
def update_cache(existing_data, new_data):
    return merge_data(existing_data, new_data, key_field="period")

# ❌ 错误：直接覆盖
def update_cache(existing_data, new_data):
    return new_data  # 丢失历史数据
```

**模式三：错误处理与降级**

```python
# ✅ 正确：有降级策略
def get_data_with_fallback(ticker):
    try:
        # 尝试从缓存获取
        cached = cache.get(ticker)
        if cached:
            return cached
    except CacheError:
        pass  # 缓存错误，继续尝试其他方式
    
    try:
        # 尝试从 API 获取
        return api.get(ticker)
    except APIError:
        # API 失败，返回默认数据
        return get_default_data(ticker)
```

### 6.2 反模式

**反模式一：无缓存键策略**

```python
# ❌ 错误：每次请求都产生新的缓存键
def get_data(ticker, date):
    cache_key = f"{ticker}_{time.time()}"  # 时间戳导致永远不命中！
    return fetch_and_cache(cache_key, ...)
```

**反模式二：无限缓存**

```python
# ❌ 错误：没有过期机制
def cache_data(key, data):
    global_cache[key] = data  # 永不清理，内存泄漏

# ✅ 正确：设置 TTL
def cache_data(key, data, ttl_seconds=3600):
    cache.set(key, data, ttl=timedelta(seconds=ttl_seconds))
```

**反模式三：忽视错误处理**

```python
# ❌ 错误：API 失败直接崩溃
def get_data(ticker):
    return api.get(ticker)  # 可能抛出异常

# ✅ 正确：完善的错误处理
def get_data(ticker):
    try:
        return api.get(ticker)
    except RateLimitError:
        wait_and_retry(max_retries=3)
    except APIError as e:
        log_error(e)
        return None  # 或返回缓存数据
```

---

## 7. 实践练习

### 练习 1：实现 Redis 缓存

**任务**：将内存缓存替换为 Redis 分布式缓存。

**需求**：
1. 安装 Redis
2. 实现 Redis 缓存适配器
3. 支持集群环境

**提示**：
```python
import redis

class RedisCache:
    def __init__(self, host='localhost', port=6379):
        self.client = redis.Redis(host=host, port=port)
    
    def get(self, key):
        value = self.client.get(key)
        return json.loads(value) if value else None
    
    def set(self, key, value, ttl=3600):
        self.client.setex(key, ttl, json.dumps(value))
```

---

### 练习 2：实现数据质量监控

**任务**：监控数据质量，检测异常数据。

**需求**：
1. 检测价格异常（负值、极端值）
2. 检测财务数据异常（缺失值、矛盾值）
3. 生成数据质量报告

---

### 练习 3：实现预测性数据预取

**任务**：根据用户历史行为预测并预取数据。

**需求**：
1. 跟踪用户常用的股票列表
2. 预测下一个可能请求的股票
3. 提前加载数据到缓存

---

## 8. 总结与进阶路径

### 8.1 本章要点回顾

| 主题 | 核心要点 |
|------|----------|
| **数据流** | 外部 API → 缓存 → 智能体 → 决策 |
| **缓存策略** | CACHE_FIRST, NETWORK_FIRST, STALE_WHILE_REVALIDATE |
| **状态管理** | LangGraph 的消息累积 + 数据合并 |
| **性能优化** | 批量获取、并行加载、预取 |

### 8.2 进阶学习路径

1. **Level 3 - 性能优化**：深入性能调优
2. **Level 3 - 数据源集成**：添加新的数据提供商
3. **Level 4 - 状态图深度**：深入 LangGraph 原理

---

## 自检清单

- [ ] **架构理解**：能够画出完整的数据流图
- [ ] **缓存机制**：能够解释不同缓存策略的适用场景
- [ ] **代码阅读**：能够阅读缓存和数据获取代码
- [ ] **性能优化**：能够实现基本的性能优化
- [ ] **问题诊断**：能够识别数据访问的性能瓶颈

---

## 参考资源

- 📖 [Redis 官方文档](https://redis.io/docs/)
- 📖 [Python requests 库文档](https://docs.python-requests.org/)
- 📖 [LangChain 缓存文档](https://python.langchain.com/docs/modules/memory/)

---

*本文档遵循专家级中文技术文档编写指南设计*
