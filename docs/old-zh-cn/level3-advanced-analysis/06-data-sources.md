# 第六章：数据源集成 ⭐⭐⭐

## 学习目标

完成本章节学习后，你将能够：

### 基础目标（必掌握）

- [ ] 理解 **数据架构** 的核心设计原则和思想
- [ ] 掌握 **数据提供商抽象（Data Provider Abstraction）** 的概念和作用
- [ ] 能够识别和说明数据流程中的各个组件（路由器、缓存层、验证层）
- [ ] 理解 **容错机制（Fault Tolerance）** 和 **数据质量（Data Quality）** 的基本概念

### 进阶目标（建议掌握）

- [ ] 能够实现自定义的数据提供商类
- [ ] 掌握数据验证和清洗的实现方法
- [ ] 理解数据血缘追踪和数据治理的价值
- [ ] 能够设计简单的数据管道

### 专家目标（挑战）

- [ ] 分析不同数据源选择方案的权衡
- [ ] 设计高可用、高可靠的数据架构
- [ ] 制定团队的数据治理规范和最佳实践

**预计学习时间**：3-4 小时

**前置知识**：
- Python 异步编程（async/await）
- 面向对象编程基础（抽象类、接口）
- HTTP API 基础知识

---

## 6.1 数据架构概述

### 为什么需要数据架构？

在深入具体实现之前，我们需要先理解：**为什么系统需要一个精心设计的数据架构？**

> 💡 **设计背景**：
> - 量化系统需要从多个数据源获取数据（免费 API、付费 API、数据库等）
> - 不同数据源的质量、可靠性、更新频率各不相同
> - API 调用有速率限制和成本
> - 数据可能包含错误、缺失、异常值

**核心问题**：
1. 如何让上层应用**不关心数据来自哪里**？
2. 如何在某个数据源失效时**自动切换**到备用源？
3. 如何避免重复调用相同的 API（**节省成本**）？
4. 如何确保数据的质量和一致性？

**设计决策**：

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 方案 A：每个模块直接调用 API | 简单直接 | 难以维护、无法统一容错 | ❌ |
| 方案 B：统一抽象层 | 可扩展、易维护 | 初期开发成本高 | ✅ |
| 方案 C：中间件模式 | 灵活、可插拔 | 复杂度高 | ⚠️ |

我们选择了**方案 B（统一抽象层）**，原因如下：
- 平衡了简单性和可扩展性
- 符合**依赖倒置原则（Dependency Inversion Principle）**
- 便于未来添加新的数据源

---

### 数据层设计原则

系统的数据层设计遵循几个核心原则，理解这些原则有助于你设计自己的数据架构。

#### 原则一：抽象化（Abstraction）

**核心思想**：通过定义统一的数据接口，屏蔽不同数据源的实现细节。

> 🎯 **为什么要抽象？**
> - **解耦**：上层应用不依赖具体的数据源实现
> - **可替换**：可以随时切换数据源而不影响上层代码
> - **可测试**：可以轻松 mock 数据源进行单元测试

```python
# ❌ 不好的做法：直接依赖具体实现
data = yfinance.Ticker("AAPL").history()

# ✅ 好的做法：通过抽象接口
data = await data_router.get_price("AAPL", "2024-01-01", "2024-01-31")
```

#### 原则二：缓存策略（Caching Strategy）

**核心思想**：实现多层缓存机制，减少重复的 API 调用。

> 🎯 **为什么需要缓存？**
> - **成本控制**：API 调用通常按次数计费
> - **性能优化**：从缓存读取比远程调用快 10-100 倍
> - **容错**：当 API 不可用时，可以使用缓存数据

**缓存策略选择**：

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| **LRU（Least Recently Used）** | 淘汰最近最少使用的数据 | 热点数据、内存有限 |
| **TTL（Time To Live）** | 超时自动失效 | 需要定期更新的数据 |
| **Write-Through** | 写入时同步更新缓存 | 数据一致性要求高 |
| **Write-Behind** | 异步写入缓存 | 写入性能优先 |

本系统使用 **LRU + Redis** 的组合：
- LRU 用于内存缓存（快速访问）
- Redis 用于持久化缓存（进程重启后仍可用）

#### 原则三：容错机制（Fault Tolerance）

**核心思想**：当主数据源不可用时，自动切换到备用数据源。

> 🎯 **为什么需要容错？**
> - **高可用性**：避免因单个数据源故障导致系统停摆
> - **SLA 保证**：金融系统对可靠性要求极高（99.9%+）
> - **用户体验**：减少因数据获取失败导致的等待时间

**容错模式**：

```
主数据源故障
    ↓
自动切换到备用源
    ↓
记录故障日志
    ↓
监控主数据源恢复
    ↓
切回主数据源
```

#### 原则四：数据治理（Data Governance）

**核心思想**：实施数据验证、清洗和质量检查，确保数据的准确性和一致性。

> 🎯 **为什么需要数据治理？**
> - **避免垃圾进、垃圾出（Garbage In, Garbage Out）**
> - **合规要求**：金融行业对数据质量有严格监管
> - **决策可靠性**：错误的财务指标会导致错误的投资决策

---

### 数据流程

理解数据在系统中的流动路径，有助于你理解各个组件的作用。

```
┌─────────────────────────────────────────────────────────────────┐
│                        数据流程全景图                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────┐    │
│  │ 应用请求 │───→│ 请求路由      │───→│ 主数据源查询     │    │
│  │(DataRequest) │ │(DataRouter) │    │(Primary Provider) │ │
│  └──────────┘    │ (负载均衡)   │    └────────┬─────────┘    │
│                  └──────────────┘             │               │
│                                               ▼ 优先级 1      │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────┐    │
│  │ 数据响应 │←───│ 结果聚合      │←───│ 备用数据源查询   │    │
│  │(DataResponse) │ │(Response)   │    │(Backup Provider)  │ │
│  └──────────┘    │ (容错处理)    │    └────────┬─────────┘    │
│                  └──────────────┘             │ 优先级 2      │
│                                               ▼               │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────┐    │
│  │ 应用使用 │←───│ 缓存层        │←───│ 数据验证/清洗    │    │
│  └──────────┘    │ (LRU + Redis) │    │(Validator/Cleaner)  │
│                  └──────────────┘    └──────────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**流程说明**：

1. **请求阶段**：应用发起 `DataRequest`，指定数据类型、时间范围等
2. **路由阶段**：`DataRouter` 根据数据类型选择合适的数据源（考虑优先级、健康状态）
3. **查询阶段**：依次尝试主数据源、备用数据源（容错机制）
4. **清洗阶段**：对返回的数据进行验证和清洗（去重、补全、异常值处理）
5. **缓存阶段**：将清洗后的数据存入缓存（下次请求优先使用缓存）
6. **响应阶段**：返回 `DataResponse`，包含数据、来源、时间戳、缓存状态等信息

---

## 6.2 数据源接口设计

### 统一数据接口

为了实现数据源的抽象化，我们需要定义一个统一的数据接口。

> 🔍 **设计模式**：这里使用了**策略模式（Strategy Pattern）** 和 **模板方法模式（Template Method Pattern）** 的组合。
> - 策略模式：不同的数据提供商是不同的策略
> - 模板方法：定义了数据获取的流程骨架

```python
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Generator
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class DataType(Enum):
    """
    数据类型枚举（Enumeration）

    枚举（Enum）是一种特殊的数据类型，用于定义一组命名常量。
    在这里，我们定义了系统支持的数据类型。

    为什么使用 Enum？
    - 类型安全：避免使用字符串时的拼写错误
    - 自文档化：明确列出了所有支持的数据类型
    - 易于维护：添加新类型时只需在此处修改
    """
    PRICE = "price"                # 价格数据（开盘、收盘、最高、最低等）
    FUNDAMENTAL = "fundamental"     # 基本面数据（财务指标）
    NEWS = "news"                   # 新闻数据（公司新闻、公告）
    INSIDER_TRADE = "insider_trade" # 内部交易数据
    ECONOMIC = "economic"          # 经济指标数据（GDP、CPI 等）

@dataclass
class DataRequest:
    """
    数据请求

    使用 DataClass 可以自动生成 __init__、__repr__ 等方法，
    减少样板代码，使代码更简洁。

    为什么使用 DataClass 而不是普通类？
    - 自动生成常用方法
    - 类型注解更清晰
    - 支持不可变对象（frozen=True）
    """
    ticker: str                        # 股票代码（如 "AAPL", "MSFT"）
    data_type: DataType                # 数据类型
    start_date: Optional[str] = None   # 开始日期（可选）
    end_date: Optional[str] = None     # 结束日期（可选）
    fields: Optional[List[str]] = None  # 需要的字段列表（可选）
    kwargs: Optional[Dict[str, Any]] = None  # 其他参数（可选）

@dataclass
class DataResponse:
    """
    数据响应

    不仅包含数据本身，还包含元数据（metadata），
    这些元数据对调试和监控非常重要。
    """
    data: Any                          # 实际数据
    source: str                        # 数据来源（哪个提供商）
    timestamp: datetime                # 获取时间
    cached: bool = False               # 是否来自缓存
    error: Optional[str] = None        # 错误信息（如果有）

class BaseDataProvider(ABC):
    """
    数据提供商抽象基类（Abstract Base Class, ABC）

    抽象基类定义了所有数据提供商必须实现的接口，
    但不提供具体实现。这确保了所有提供商遵循相同的契约。

    为什么使用抽象基类？
    - 强制实现：子类必须实现所有抽象方法
    - 类型安全：可以用 BaseDataProvider 类型引用任何子类
    - 多态性：可以统一处理不同的数据提供商
    """

    def __init__(self, name: str, priority: int = 100):
        """
        初始化数据提供商

        Args:
            name: 提供商名称（如 "financial_datasets", "yahoo_finance"）
            priority: 优先级，数值越小优先级越高（1 = 最高优先级）

        优先级用途：
        - 路由器优先使用高优先级的提供商
        - 主提供商失败时，尝试次优先级的提供商
        """
        self.name = name
        self.priority = priority
        self.health_status = "unknown"  # 健康状态：unknown/healthy/unhealthy

    @abstractmethod
    async def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """
        获取价格数据（抽象方法）

        Args:
            ticker: 股票代码
            start_date: 开始日期（格式：YYYY-MM-DD）
            end_date: 结束日期（格式：YYYY-MM-DD）

        Returns:
            价格数据列表，每个元素包含 date, open, high, low, close, volume

        Raises:
            DataProviderError: 数据获取失败
            RateLimitError: 超过速率限制
        """
        pass  # 子类必须实现

    @abstractmethod
    async def get_financial_metrics(
        self,
        ticker: str,
        end_date: str
    ) -> Dict[str, Any]:
        """
        获取财务指标（抽象方法）

        Args:
            ticker: 股票代码
            end_date: 截止日期（格式：YYYY-MM-DD）

        Returns:
            财务指标字典，包含 market_cap, pe_ratio, roe 等
        """
        pass  # 子类必须实现

    @abstractmethod
    async def get_company_news(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """
        获取公司新闻（抽象方法）

        Args:
            ticker: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            新闻列表，每个元素包含 title, date, summary, url 等
        """
        pass  # 子类必须实现

    @abstractmethod
    async def health_check(self) -> bool:
        """
        健康检查（抽象方法）

        Returns:
            True 表示健康，False 表示不健康

        用途：
        - 路由器在调用前检查提供商健康状态
        - 不健康的提供商会被暂时跳过
        - 定期健康检查可以自动恢复
        """
        pass  # 子类必须实现

    @abstractmethod
    def rate_limit_info(self) -> Dict[str, Any]:
        """
        速率限制信息（抽象方法）

        Returns:
            速率限制信息字典，包含：
            - requests_per_minute: 每分钟请求限制
            - requests_per_day: 每天请求限制
            - backoff_strategy: 退避策略（exponential/fixed/none）

        用途：
        - 路由器可以据此实现智能限流
        - 避免触发 API 的速率限制
        """
        pass  # 子类必须实现
```

> 📝 **设计意图说明**：
> - 使用 `async` 异步方法以提高性能（多个请求可以并发）
> - 所有方法都返回类型注解（Type Hints），便于 IDE 自动补全和类型检查
> - 异常处理在子类实现，基类只定义接口

---

### Financial Datasets 提供商实现

现在我们实现一个具体的数据提供商：**Financial Datasets API**。

> 🎯 **为什么选择这个 API？**
> - 免费额度较高（前 5 只股票免费）
> - 数据质量高（官方财务数据）
> - 支持多种数据类型（价格、财务指标、新闻等）
> - 响应速度快

```python
import aiohttp

class FinancialDatasetsProvider(BaseDataProvider):
    """
    Financial Datasets API 提供商

    这是一个付费 API，但提供免费试用。
    文档：https://api.financialdatasets.ai

    为什么选择 aiohttp？
    - 支持异步 HTTP 请求（async/await）
    - 性能优秀，适合高并发场景
    - 连接池管理，避免频繁创建连接
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.financialdatasets.ai"
    ):
        """
        初始化 Financial Datasets 提供商

        Args:
            api_key: API 密钥（从 https://financialdatasets.ai 获取）
            base_url: API 基础 URL（用于测试可以切换到 mock 服务器）
        """
        super().__init__("financial_datasets", priority=1)  # 最高优先级
        self.api_key = api_key
        self.base_url = base_url
        self.session = None  # 懒加载：只在第一次使用时创建

    async def _get_session(self) -> aiohttp.ClientSession:
        """
        获取或创建 HTTP 会话

        为什么不直接创建 session？
        - session 包含连接池，应该复用
        - 懒加载避免不必要的资源占用

        Returns:
            aiohttp.ClientSession 实例
        """
        if self.session is None or self.session.closed:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            self.session = aiohttp.ClientSession(headers=headers)
        return self.session

    async def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """
        获取价格数据

        API 端点：GET /prices

        错误处理：
        - 200: 成功
        - 429: 超过速率限制（需要退避重试）
        - 401: API 密钥无效
        - 404: 股票代码不存在
        - 500: 服务器错误
        """
        session = await self._get_session()

        url = f"{self.base_url}/prices"
        params = {
            "ticker": ticker,
            "start_date": start_date,
            "end_date": end_date
        }

        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("prices", [])
            elif response.status == 429:
                # 速率限制：需要实现退避重试机制
                raise RateLimitError("Financial Datasets API rate limit exceeded")
            elif response.status == 401:
                raise APIError("Invalid API key. Check your FINANCIAL_DATASETS_API_KEY.")
            elif response.status == 404:
                raise APIError(f"Ticker not found: {ticker}")
            else:
                raise APIError(f"Financial Datasets API error: {response.status}")

    async def get_financial_metrics(
        self,
        ticker: str,
        end_date: str
    ) -> Dict[str, Any]:
        """
        获取财务指标

        API 端点：GET /financials/metrics

        包含的指标：
        - market_cap: 市值
        - pe_ratio: 市盈率
        - pb_ratio: 市净率
        - roe: 净资产收益率
        - debt_to_equity: 债务权益比
        - revenue_growth: 营收增长率
        - profit_margin: 利润率
        """
        session = await self._get_session()

        url = f"{self.base_url}/financials/metrics"
        params = {
            "ticker": ticker,
            "end_date": end_date
        }

        async with session.get(url, params=params) as response:
            if response.status == 200:
                return await response.json()
            elif response.status == 404:
                # 某些股票可能没有财务数据
                return {}
            else:
                raise APIError(f"Financial Datasets API error: {response.status}")

    async def get_company_news(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """
        获取公司新闻

        API 端点：GET /news

        注意：
        - 新闻数据可能很大，需要分页处理
        - 某些小盘股可能没有新闻
        """
        session = await self._get_session()

        url = f"{self.base_url}/news"
        params = {
            "ticker": ticker,
            "start_date": start_date,
            "end_date": end_date
        }

        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("news", [])
            else:
                # 新闻不是关键数据，失败时返回空列表
                return []

    async def health_check(self) -> bool:
        """
        健康检查

        通过调用 /health 端点验证 API 是否可用
        """
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/health") as response:
                self.health_status = "healthy" if response.status == 200 else "unhealthy"
                return response.status == 200
        except Exception as e:
            self.health_status = "unhealthy"
            return False

    def rate_limit_info(self) -> Dict[str, Any]:
        """
        速率限制信息

        Financial Datasets 的限制（以实际情况为准）：
        - 免费账户：100 次/分钟，10,000 次/天
        - 付费账户：更高限制
        """
        return {
            "requests_per_minute": 100,
            "requests_per_day": 10000,
            "backoff_strategy": "exponential"  # 指数退避
        }

    async def close(self):
        """
        关闭会话

        在程序退出时调用，释放资源
        """
        if self.session and not self.session.closed:
            await self.session.close()
```

> ⚠️ **常见错误**：
> - 忘记调用 `close()` 方法导致资源泄漏
> - 在每次请求时创建新的 session（性能差）
> - 忽略 429 错误（导致账户被封禁）

---

### 备用数据源实现

Yahoo Finance 作为一个备用数据源，虽然数据质量略低，但完全免费。

> 🎯 **为什么需要备用数据源？**
> - 主数据源可能因维护、配额用完、网络问题而不可用
> - 免费备用源可以降低成本（付费 API 通常按次计费）
> - 不同数据源的数据可以交叉验证（提高数据可信度）

```python
class YahooFinanceProvider(BaseDataProvider):
    """
    Yahoo Finance 数据提供商（备用）

    使用 yfinance 库（不是官方 API，而是网页抓取）

    优点：
    - 完全免费
    - 数据覆盖广（全球市场）
    - 历史数据完整

    缺点：
    - 不是官方 API（可能不稳定）
    - 数据质量可能不如付费 API
    - 容易被反爬虫限制
    """

    def __init__(self):
        """
        初始化 Yahoo Finance 提供商

        Yahoo Finance 不需要 API 密钥
        """
        super().__init__("yahoo_finance", priority=10)  # 较低优先级
        self._cache = {}  # 简单内存缓存

    async def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """
        获取价格数据（使用 yfinance 库）

        注意：yfinance 是同步库，这里用 asyncio.to_thread 转换为异步
        """
        try:
            import yfinance as yf

            stock = yf.Ticker(ticker)
            hist = stock.history(
                start=start_date,
                end=end_date
            )

            # 转换为标准格式
            prices = []
            for date, row in hist.iterrows():
                prices.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": int(row["Volume"])
                })

            return prices
        except Exception as e:
            raise DataProviderError(f"Yahoo Finance error: {str(e)}")

    async def get_financial_metrics(
        self,
        ticker: str,
        end_date: str
    ) -> Dict[str, Any]:
        """
        获取财务指标

        Yahoo Finance 的财务数据有限，只返回基本的指标
        """
        import yfinance as yf

        stock = yf.Ticker(ticker)
        info = stock.info

        # 返回可用的指标
        return {
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "pb_ratio": info.get("priceToBook"),
            "roe": info.get("returnOnEquity"),
            "debt_to_equity": info.get("debtToEquity"),
            "revenue_growth": info.get("revenueGrowth"),
            "profit_margin": info.get("profitMargins")
        }

    async def get_company_news(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """
        获取公司新闻

        Yahoo Finance 没有直接的新闻 API（需要网页抓取）
        这里返回空列表，实际使用时可以考虑其他新闻源
        """
        # Yahoo Finance 没有直接的新闻 API
        return []

    async def health_check(self) -> bool:
        """
        健康检查

        通过查询 AAPL 股票信息验证连接
        """
        try:
            import yfinance as yf
            stock = yf.Ticker("AAPL")
            _ = stock.info
            return True
        except Exception:
            return False

    def rate_limit_info(self) -> Dict[str, Any]:
        """
        速率限制信息

        Yahoo Finance 没有官方限制，但频繁请求可能被封禁
        建议加适当的延迟（如每次请求间隔 1 秒）
        """
        return {
            "requests_per_minute": 60,  # 建议限制
            "requests_per_day": None,   # 无明确限制
            "backoff_strategy": "retry"  # 失败后重试
        }
```

> 💡 **实践建议**：
> - 对于生产环境，建议使用官方 API（如 Bloomberg、Alpha Vantage）
> - 可以配置多个备用数据源（主数据源 → 备用源 1 → 备用源 2）
> - 定期监控各数据源的健康状态和响应时间

---

## 6.3 数据路由器

### 智能路由

数据路由器（Data Router）是数据架构的核心组件，负责：

1. **选择合适的数据源**（根据优先级、健康状态、负载）
2. **实现容错机制**（主源失败时自动切换）
3. **负载均衡**（避免单个数据源过载）

> 🎯 **设计模式**：这里使用了**外观模式（Facade Pattern）** 和 **责任链模式（Chain of Responsibility）** 的组合。

```python
from typing import Dict, List

class DataRouter:
    """
    数据路由器

    职责：
    1. 管理所有已注册的数据提供商
    2. 根据请求类型选择合适的数据源
    3. 实现容错和负载均衡
    4. 缓存数据以减少 API 调用

    为什么需要路由器？
    - 上层应用不需要关心数据来自哪里
    - 统一的容错和负载均衡逻辑
    - 便于监控和调试
    """

    def __init__(self):
        """初始化路由器"""
        self.providers: Dict[str, BaseDataProvider] = {}     # 提供商注册表
        self.fallback_chains: Dict[DataType, List[str]] = {}  # 备用链路
        self.load_balancer: Dict[str, int] = {}              # 负载计数
        self.cache: Dict[str, DataResponse] = {}              # 简单缓存

    def register_provider(self, provider: BaseDataProvider):
        """
        注册数据提供商

        Args:
            provider: 数据提供商实例

        示例：
            router = DataRouter()
            router.register_provider(FinancialDatasetsProvider(api_key="xxx"))
            router.register_provider(YahooFinanceProvider())
        """
        self.providers[provider.name] = provider
        self.load_balancer[provider.name] = 0

    def configure_fallback_chain(
        self,
        data_type: DataType,
        provider_names: List[str]
    ):
        """
        配置备用链路

        Args:
            data_type: 数据类型
            provider_names: 提供商名称列表（按优先级排序）

        示例：
            router.configure_fallback_chain(
                DataType.PRICE,
                ["financial_datasets", "yahoo_finance"]
            )
        """
        self.fallback_chains[data_type] = provider_names

    async def get_data(
        self,
        request: DataRequest
    ) -> DataResponse:
        """
        获取数据（带容错）

        Args:
            request: 数据请求

        Returns:
            数据响应

        Raises:
            DataProviderError: 所有提供商都失败

        工作流程：
        1. 检查缓存
        2. 遍历备用链路
        3. 尝试每个提供商
        4. 成功则返回并缓存
        5. 失败则尝试下一个
        """
        data_type = request.data_type

        # 生成缓存键
        cache_key = f"{request.ticker}_{data_type.value}_{request.start_date}_{request.end_date}"

        # 检查缓存
        if cache_key in self.cache:
            cached_response = self.cache[cache_key]
            cached_response.cached = True
            return cached_response

        # 获取备用链路（如果没有配置，则使用所有提供商）
        chain = self.fallback_chains.get(data_type, list(self.providers.keys()))

        last_error = None

        # 遍历备用链路
        for provider_name in chain:
            provider = self.providers[provider_name]

            # 检查提供商健康状态
            if not await provider.health_check():
                continue  # 跳过不健康的提供商

            # 负载均衡选择
            if self._should_skip_provider(provider_name):
                continue  # 跳过负载过高的提供商

            try:
                # 选择对应方法
                method = self._get_method(provider, data_type)
                if method is None:
                    continue  # 该提供商不支持此数据类型

                # 调用数据获取
                data = await method(request)

                # 更新负载计数
                self.load_balancer[provider_name] += 1

                # 构建响应
                response = DataResponse(
                    data=data,
                    source=provider_name,
                    timestamp=datetime.now(),
                    cached=False
                )

                # 缓存响应
                self.cache[cache_key] = response

                return response

            except Exception as e:
                last_error = e
                # 记录失败，尝试下一个提供商
                continue

        # 所有提供商都失败
        raise DataProviderError(
            f"All providers failed for {data_type.value}: {str(last_error)}"
        )

    def _should_skip_provider(self, provider_name: str) -> bool:
        """
        检查是否应该跳过提供商

        简单实现：负载过高时跳过
        高级实现可以加入：速率限制、错误率、响应时间等
        """
        load = self.load_balancer.get(provider_name, 0)
        return load > 100  # 示例：超过 100 次请求后跳过

    def _get_method(
        self,
        provider: BaseDataProvider,
        data_type: DataType
    ):
        """
        获取对应的数据获取方法

        将 DataType 映射到具体的提供商方法
        """
        method_map = {
            DataType.PRICE: provider.get_prices,
            DataType.FUNDAMENTAL: provider.get_financial_metrics,
            DataType.NEWS: provider.get_company_news,
        }
        return method_map.get(data_type)
```

---

## 6.4 数据质量控制

### 为什么需要数据质量控制？

在金融领域，数据质量至关重要。错误的数据会导致：

- **错误的投资决策**
- **无法通过合规审计**
- **模型训练失败**
- **系统崩溃**

> 📊 **数据质量维度**：
> - **准确性**（Accuracy）：数据是否正确
> - **完整性**（Completeness）：数据是否缺失
> - **一致性**（Consistency）：数据格式是否统一
> - **时效性**（Timeliness）：数据是否最新
> - **唯一性**（Uniqueness）：是否有重复数据

---

### 验证规则

我们使用 **Pydantic** 库进行数据验证。

> 🎯 **为什么使用 Pydantic？**
> - 基于 Python 类型注解
> - 自动生成验证逻辑
> - 清晰的错误提示
> - 支持 JSON 序列化

```python
from pydantic import BaseModel, validator, confloat
from typing import Optional, Tuple

class PriceData(BaseModel):
    """
    价格数据模型

    使用 Pydantic 自动验证：
    - 类型检查
    - 范围检查
    - 业务逻辑验证

    confloat 约束：
    - gt=0: 大于 0（greater than）
    - ge=0: 大于等于 0（greater or equal）
    """
    date: str
    open: confloat(gt=0)  # 开盘价必须大于 0
    high: confloat(gt=0)  # 最高价必须大于 0
    low: confloat(gt=0)   # 最低价必须大于 0
    close: confloat(gt=0) # 收盘价必须大于 0
    volume: int = 0      # 成交量

    @validator('high')
    def high_must_be_valid(cls, v, values):
        """
        验证最高价

        规则：最高价 >= 最低价
        """
        if 'low' in values and v < values['low']:
            raise ValueError('high must be >= low')
        return v

    @validator('close')
    def close_must_be_valid(cls, v, values):
        """
        验证收盘价

        规则：收盘价不应该偏离开盘价太大（超过 50% 可能是异常）
        """
        if 'open' in values and abs(v - values['open']) > 0.5 * values['open']:
            raise ValueError('close price seems anomalous')
        return v

class FinancialMetrics(BaseModel):
    """
    财务指标模型

    使用可选字段（Optional），因为某些指标可能缺失
    """
    market_cap: Optional[float] = None      # 市值
    pe_ratio: Optional[float] = None       # 市盈率
    pb_ratio: Optional[float] = None       # 市净率
    roe: Optional[confloat(ge=-1, le=1)] = None      # ROE: -100% 到 100%
    debt_to_equity: Optional[float] = None  # 债务权益比
    revenue_growth: Optional[confloat(ge=-1, le=10)] = None  # 营收增长: -100% 到 1000%
    profit_margin: Optional[confloat(ge=-1, le=1)] = None    # 利润率: -100% 到 100%

class DataValidator:
    """
    数据验证器

    职责：
    1. 验证数据格式和范围
    2. 识别异常值
    3. 返回验证结果和错误列表
    """

    VALIDATORS = {
        "price": PriceData,
        "financial": FinancialMetrics
    }

    @classmethod
    def validate(
        cls,
        data_type: str,
        data: List[Dict[str, Any]]
    ) -> Tuple[List[Any], List[Dict]]:
        """
        批量验证数据

        Args:
            data_type: 数据类型
            data: 待验证的数据列表

        Returns:
            (验证通过的数据, 错误列表)

        错误格式：
            {
                "index": 行号,
                "error": 错误信息,
                "data": 原始数据
            }
        """
        validator_cls = cls.VALIDATORS.get(data_type)
        if validator_cls is None:
            return data, []

        validated = []
        errors = []

        for i, item in enumerate(data):
            try:
                validated_item = validator_cls(**item)
                validated.append(validated_item.dict())
            except Exception as e:
                errors.append({
                    "index": i,
                    "error": str(e),
                    "data": item
                })

        return validated, errors
```

---

### 数据清洗

验证后的数据可能需要清洗，处理缺失值、异常值等。

> 🎯 **清洗策略**：
> - **缺失值**：前向填充、均值填充、删除
> - **异常值**：检测、修正、删除
> - **重复数据**：去重
> - **格式统一**：日期格式、数值精度

```python
class DataCleaner:
    """
    数据清洗器

    常用的数据清洗方法
    """

    @staticmethod
    def clean_price_data(prices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        清洗价格数据

        处理：
        1. 缺失值：使用前向填充
        2. 异常值：负数取绝对值
        3. 日期格式：统一为 YYYY-MM-DD
        """
        cleaned = []

        for price in prices:
            # 处理缺失值
            if price.get('close') is None:
                # 使用前向填充（Forward Fill）
                if cleaned:
                    price['close'] = cleaned[-1]['close']
                else:
                    continue  # 第一条数据缺失，跳过

            # 处理异常值
            if price['close'] < 0:
                price['close'] = abs(price['close'])

            # 标准化日期格式
            if 'date' in price:
                price['date'] = DataCleaner._normalize_date(price['date'])

            cleaned.append(price)

        return cleaned

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        """
        标准化日期格式

        支持：YYYY-MM-DD, MM/DD/YYYY, DD-MM-YYYY 等
        """
        from dateutil import parser
        try:
            dt = parser.parse(date_str)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return date_str

    @staticmethod
    def fill_missing_values(
        data: List[Dict[str, Any]],
        columns: List[str],
        method: str = "forward"
    ) -> List[Dict[str, Any]]:
        """
        填充缺失值

        Args:
            data: 数据列表
            columns: 需要填充的列名
            method: 填充方法
                - forward: 前向填充（使用前一个值）
                - backward: 后向填充（使用后一个值）
                - mean: 均值填充
        """
        if not data:
            return data

        filled = []
        last_values = {col: None for col in columns}

        for item in data:
            new_item = item.copy()

            for col in columns:
                if new_item.get(col) is None:
                    if method == "forward" and last_values[col] is not None:
                        new_item[col] = last_values[col]
                    elif method == "backward":
                        # 向前查找（简化处理）
                        new_item[col] = None
                    elif method == "mean":
                        # 计算均值（简化处理）
                        pass
                else:
                    last_values[col] = new_item[col]

            filled.append(new_item)

        return filled
```

---

## 6.5 数据治理

### 数据血缘追踪

数据血缘（Data Lineage）记录数据的来源和转换历史。

> 🎯 **为什么需要数据血缘？**
> - **审计**：追踪数据的来源和变更历史
> - **故障排查**：数据有问题时，可以找到根源
> - **影响分析**：数据源变更会影响哪些下游任务

```python
class DataLineageTracker:
    """
    数据血缘追踪

    记录：
    1. 数据来源
    2. 转换操作
    3. 时间戳
    4. 元数据
    """

    def __init__(self):
        self.lineage_records = []

    def record_lineage(
        self,
        data_id: str,
        source: str,
        transformation: str,
        timestamp: datetime,
        metadata: Dict[str, Any] = None
    ):
        """
        记录血缘信息

        Args:
            data_id: 数据标识（如 "AAPL_prices_2024-01-01"）
            source: 数据源（如 "financial_datasets"）
            transformation: 转换操作（如 "validation", "cleaning"）
            timestamp: 时间戳
            metadata: 其他元数据
        """
        record = {
            "data_id": data_id,
            "source": source,
            "transformation": transformation,
            "timestamp": timestamp,
            "metadata": metadata or {}
        }
        self.lineage_records.append(record)

    def get_data_sources(self, data_id: str) -> List[Dict]:
        """
        获取数据的来源

        Args:
            data_id: 数据标识

        Returns:
            血缘记录列表
        """
        return [
            r for r in self.lineage_records
            if r["data_id"] == data_id
        ]

    def trace_impact(self, source_id: str) -> List[str]:
        """
        追踪影响范围

        Args:
            source_id: 数据源标识

        Returns:
            受影响的数据列表
        """
        impacted = []
        for record in self.lineage_records:
            if record["source"] == source_id:
                impacted.append(record["data_id"])
        return impacted
```

---

### 数据目录

数据目录（Data Catalog）是一个元数据管理系统，用于发现和管理数据。

> 🎯 **数据目录的作用**：
> - **数据发现**：快速找到需要的数据
> - **数据理解**：了解数据的含义和结构
> - **数据质量**：查看数据质量指标
> - **访问控制**：管理数据访问权限

```python
class DataCatalog:
    """
    数据目录

    功能：
    1. 注册数据集
    2. 搜索数据集
    3. 查看数据集信息
    """

    def __init__(self):
        self.catalog = {}

    def register_dataset(
        self,
        dataset_id: str,
        name: str,
        description: str,
        schema: Dict[str, Any],
        source: str,
        update_frequency: str,
        owner: str
    ):
        """
        注册数据集

        Args:
            dataset_id: 数据集唯一标识
            name: 数据集名称
            description: 描述
            schema: 数据结构（字段、类型）
            source: 数据源
            update_frequency: 更新频率（daily, weekly, monthly）
            owner: 负责人

        示例 schema:
            {
                "date": "string",
                "open": "float",
                "high": "float",
                "low": "float",
                "close": "float",
                "volume": "int"
            }
        """
        self.catalog[dataset_id] = {
            "id": dataset_id,
            "name": name,
            "description": description,
            "schema": schema,
            "source": source,
            "update_frequency": update_frequency,
            "owner": owner,
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }

    def search_datasets(
        self,
        query: str = None,
        filters: Dict[str, Any] = None
    ) -> List[Dict]:
        """
        搜索数据集

        Args:
            query: 关键词（搜索名称和描述）
            filters: 过滤条件（如 {"source": "financial_datasets"}）

        Returns:
            匹配的数据集列表
        """
        results = []

        for dataset in self.catalog.values():
            # 文本搜索
            if query:
                if query.lower() not in dataset["name"].lower() and \
                   query.lower() not in dataset["description"].lower():
                    continue

            # 过滤
            if filters:
                match = True
                for key, value in filters.items():
                    if dataset.get(key) != value:
                        match = False
                        break
                if not match:
                    continue

            results.append(dataset)

        return results

    def get_dataset_info(self, dataset_id: str) -> Dict:
        """
        获取数据集信息

        Args:
            dataset_id: 数据集标识

        Returns:
            数据集信息（不存在返回 None）
        """
        return self.catalog.get(dataset_id)
```

---

## 6.6 练习题

### 练习 6.1：实现数据提供商（应用型练习）⭐⭐

**任务**：实现一个新的数据提供商的完整集成。

**要求**：
1. 实现 `BaseDataProvider` 接口的所有方法
2. 实现健康检查和速率限制处理
3. 编写至少 3 个单元测试

**提示**：
- 可以选择 Alpha Vantage、IEX Cloud、Polygon.io 等免费 API
- 使用 `aiohttp` 或 `httpx` 进行异步 HTTP 请求
- 参考已有的 `FinancialDatasetsProvider` 实现

**验收标准**：
- [ ] 能够成功获取价格数据
- [ ] 健康检查方法正确实现
- [ ] 单元测试通过（覆盖率 > 80%）

**参考答案框架**：
```python
class MyDataProvider(BaseDataProvider):
    def __init__(self, api_key: str):
        super().__init__("my_provider", priority=5)
        # TODO: 初始化

    async def get_prices(self, ticker: str, start_date: str, end_date: str):
        # TODO: 实现
        pass

    # TODO: 其他方法
```

---

### 练习 6.2：数据质量系统（综合型练习）⭐⭐⭐

**任务**：实现完整的数据质量控制系统。

**要求**：
1. 实现多类型数据验证器（价格、财务指标、新闻）
2. 实现数据清洗功能（缺失值、异常值、重复数据）
3. 实现异常检测和告警

**提示**：
- 使用 Pydantic 进行验证
- 实现统计方法检测异常值（如 Z-Score、IQR）
- 使用日志记录清洗过程

**验收标准**：
- [ ] 验证器能够检测所有定义的异常
- [ ] 清洗方法处理缺失值和异常值
- [ ] 异常检测准确率 > 95%

**参考答案框架**：
```python
class AdvancedDataValidator:
    def __init__(self):
        self.validators = {}
        self.cleaners = {}
        self.detectors = {}

    def validate(self, data_type, data):
        # TODO: 验证逻辑
        pass

    def clean(self, data_type, data):
        # TODO: 清洗逻辑
        pass

    def detect_anomalies(self, data_type, data):
        # TODO: 异常检测逻辑
        pass
```

---

### 练习 6.3：数据治理框架（专家级练习）⭐⭐⭐⭐

**任务**：设计并实现数据治理的基础设施。

**要求**：
1. 实现完整的数据血缘追踪
2. 实现数据目录系统（支持搜索、过滤、权限）
3. 实现数据质量监控和报告

**提示**：
- 使用数据库存储血缘记录（如 SQLite、PostgreSQL）
- 实现图形化界面（可选）
- 集成告警系统（如邮件、Slack）

**验收标准**：
- [ ] 能够追踪任意数据的来源和变更历史
- [ ] 数据目录支持全文搜索和高级过滤
- [ ] 生成数据质量报告（PDF 或 HTML）

**参考答案框架**：
```python
class DataGovernanceFramework:
    def __init__(self):
        self.lineage_tracker = DataLineageTracker()
        self.data_catalog = DataCatalog()
        self.quality_monitor = DataQualityMonitor()

    def register_data(self, data_id, metadata):
        # TODO: 注册数据
        pass

    def trace_lineage(self, data_id):
        # TODO: 追踪血缘
        pass

    def generate_quality_report(self, data_id):
        # TODO: 生成报告
        pass
```

---

## 6.7 常见问题与故障排查

### 问题 1：API 调用失败

**症状**：
```
APIError: Financial Datasets API error: 401
```

**可能原因**：
1. API 密钥无效或过期
2. API 密钥未正确配置
3. API 服务端故障

**排查步骤**：

1. 检查 `.env` 文件：
```bash
cat .env | grep FINANCIAL_DATASETS_API_KEY
```

2. 验证 API 密钥：
```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
     https://api.financialdatasets.ai/health
```

3. 检查 API 密钥是否过期：
- 登录 Financial Datasets 控制台
- 查看 API 密钥状态

**解决方案**：
- 重新生成 API 密钥
- 更新 `.env` 文件
- 重启应用

---

### 问题 2：速率限制错误

**症状**：
```
RateLimitError: Financial Datasets API rate limit exceeded
```

**可能原因**：
1. 请求过于频繁
2. 多个并发请求
3. 缓存未生效

**排查步骤**：

1. 检查请求频率：
```python
import time
# 在 get_prices 方法中添加日志
logger.info(f"Request count: {request_count}")
```

2. 检查缓存状态：
```python
# 检查缓存键是否存在
print(router.cache.keys())
```

**解决方案**：
- 实现请求限流（如 `asyncio.Semaphore`）
- 增加缓存时间
- 实现指数退避重试

---

### 问题 3：数据验证失败

**症状**：
```
ValueError: high must be >= low
```

**可能原因**：
1. 数据源返回的数据有误
2. 数据格式解析错误
3. 异常值处理不当

**排查步骤**：

1. 检查原始数据：
```python
# 在验证前打印数据
print(f"Raw data: {raw_data}")
```

2. 检查验证规则：
```python
# 确认验证规则是否合理
print(validator_cls.__validators__)
```

**解决方案**：
- 调整验证规则
- 实现更灵活的验证逻辑
- 记录失败的数据用于分析

---

### 问题 4：内存泄漏

**症状**：
- 应用运行一段时间后变慢
- 内存占用持续增长

**可能原因**：
1. 缓存无限增长
2. HTTP 会话未关闭
3. 事件循环阻塞

**排查步骤**：

1. 检查内存使用：
```python
import psutil
print(psutil.virtual_memory())
```

2. 检查缓存大小：
```python
print(f"Cache size: {len(router.cache)}")
```

**解决方案**：
- 实现 LRU 缓存限制大小
- 确保所有会话都关闭
- 使用内存分析工具（如 `memory_profiler`）

---

## 6.8 总结与进阶

### 核心概念回顾

| 概念 | 作用 | 关键点 |
|------|------|--------|
| **抽象化原则** | 解耦数据源和应用 | 使用抽象基类定义接口 |
| **容错机制** | 提高系统可靠性 | 备用链路 + 健康检查 |
| **缓存策略** | 降低成本、提高性能 | LRU + Redis 组合 |
| **数据验证** | 确保数据质量 | Pydantic 自动验证 |
| **数据血缘** | 追踪数据来源 | 记录变更历史 |

---

### 最佳实践总结

1. **始终使用异步 I/O**：提高并发性能
2. **实现健康检查**：定期监控数据源状态
3. **合理配置缓存**：平衡性能和成本
4. **完善的错误处理**：捕获并记录所有异常
5. **数据验证必不可少**：避免垃圾进、垃圾出
6. **记录数据血缘**：便于审计和故障排查

---

### 进阶学习路径

完成本章后，你可以继续学习：

1. **分布式数据架构**（Level 4）
   - 消息队列（Kafka、RabbitMQ）
   - 数据湖和数据仓库
   - 实时流处理

2. **高级数据治理**（Level 4）
   - 数据质量自动评估
   - 数据血缘可视化
   - 数据合规性检查

3. **性能优化**（Level 3）
   - 缓存优化策略
   - 数据压缩
   - 批处理优化

---

### 推荐资源

- **书籍**：《Designing Data-Intensive Applications》
- **文章**：[Data Engineering Best Practices](https://towardsdatascience.com/data-engineering-best-practices)
- **工具**：
  - Apache Airflow（数据编排）
  - Great Expectations（数据验证）
  - Apache Kafka（消息队列）

---

## 自检清单

完成本章节学习后，请自检以下能力：

### 概念理解
- [ ] 能够用自己的话解释数据架构的设计原则
- [ ] 知道为什么需要抽象化、缓存、容错机制
- [ ] 理解数据质量控制的重要性

### 动手能力
- [ ] 能够实现自定义的数据提供商
- [ ] 能够编写数据验证和清洗逻辑
- [ ] 能够配置数据路由器和备用链路

### 问题解决
- [ ] 能够诊断 API 调用失败的原因
- [ ] 能够处理速率限制错误
- [ ] 能够排查数据验证失败的问题

### 进阶能力
- [ ] 能够为团队制定数据治理规范
- [ ] 能够设计高可用的数据架构
- [ ] 能够监控和优化数据管道性能

---

**下一章预告**：第七章 - 系统集成与部署
