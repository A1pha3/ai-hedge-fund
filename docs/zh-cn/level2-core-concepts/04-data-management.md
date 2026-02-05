# 第四章：数据获取与缓存管理

## 学习目标

完成本章节学习后，你将能够理解系统数据获取的整体架构和工作流程，掌握金融数据 API 的使用方法和数据格式，了解缓存策略的实现原理和优化技巧，以及学会如何添加新的数据源。预计学习时间为 1-1.5 小时。

## 4.1 数据架构概述

### 数据流程总览

系统的数据获取架构采用分层设计，从底层到顶层依次为：数据源层、缓存层、接口层和应用层。这种分层设计确保了系统的可维护性、可扩展性和性能。

**数据源层**负责与外部金融数据 API 交互，获取原始数据。系统目前主要使用 Financial Datasets API 作为数据源，支持价格数据、财务数据、新闻数据等多种数据类型。

**缓存层**在内存和磁盘两个层面实现数据缓存，减少重复的 API 调用，提高响应速度，降低 API 成本。缓存策略考虑了数据的时效性和存储成本。

**接口层**提供统一的数据访问接口，屏蔽底层数据源的差异。应用层通过接口层获取所需数据，无需关心数据的具体来源和缓存细节。

**应用层**是智能体和回测系统，它们通过接口层获取数据，用于分析和回测。

### 支持的数据类型

系统支持获取以下类型的金融数据：

**价格数据（Price Data）**包括 OHLCV 数据（开盘价、最高价、最低价、收盘价、成交量），用于技术分析和回测。

**财务指标（Financial Metrics）**包括营收、利润、现金流、资产负债等关键财务指标，用于基本面分析。

**财务报表项目（Line Items）**包括详细的财务报表科目数据，如资本支出、折旧、研发费用等，用于深度分析。

**公司新闻（Company News）**包括公司相关的新闻报道和公告，用于情绪分析和事件驱动策略。

**内幕交易（Insider Trades）**包括公司高管和董事的买卖交易信息，作为交易信号的参考。

**市值数据（Market Cap）**包括公司的总市值数据，用于估值分析和规模筛选。

## 4.2 金融数据 API

### Financial Datasets API 概述

Financial Datasets API 是系统的主要数据来源，提供高质量的金融数据服务。API 的主要特点包括：全面的数据类型覆盖，支持股票、ETF、加密货币等多种资产；丰富的历史数据，大多数数据可以追溯到 10 年以上；标准化的数据格式，易于解析和处理；可靠的 SLA 保证，数据的及时性和准确性。

### API 接口函数

系统通过 `src/tools/api.py` 文件中的函数与 Financial Datasets API 交互。主要接口函数包括：

**get_prices(ticker, start_date, end_date)** 获取指定股票在日期范围内的价格数据。返回类型为 `List[Price]`，每条记录包含日期、开盘价、最高价、最低价、收盘价、成交量等字段。

**get_financial_metrics(ticker, end_date)** 获取指定股票的财务指标。返回类型为 `List[FinancialMetrics]`，包含营收增长率、利润率、ROE 等关键指标。

**search_line_items(ticker, fields, end_date)** 获取指定股票的财务报表项目数据。可以指定感兴趣的科目列表，如「资本支出」「净收入」「股东权益」等。返回类型为 `List[LineItem]`。

**get_company_news(ticker, date_range)** 获取指定公司在日期范围内的新闻数据。返回类型为 `List[CompanyNews]`，每条新闻包含标题、内容、发布时间、情感标签等字段。

**get_insider_trades(ticker, date_range)** 获取指定公司的内幕交易数据。返回类型为 `List[InsiderTrade]`，包含交易日期、交易方、交易类型、交易数量等信息。

**get_market_cap(ticker, end_date)** 获取指定公司在指定日期的市值数据。返回类型为 `float`。

### API 调用示例

```python
from src.tools.api import (
    get_prices,
    get_financial_metrics,
    search_line_items,
    get_market_cap
)

# 获取价格数据
prices = get_prices("AAPL", "2024-01-01", "2024-03-01")
for price in prices[:5]:
    print(f"日期: {price.date}, 收盘价: {price.close}")

# 获取财务指标
metrics = get_financial_metrics("AAPL", "2024-03-31")
print(f"营收增长率: {metrics.revenue_growth}")
print(f"净利润率: {metrics.net_profit_margin}")

# 获取特定财务科目
line_items = search_line_items(
    "AAPL",
    ["capital_expenditure", "depreciation", "net_income"],
    "2024-03-31"
)
for item in line_items:
    print(f"{item.field_name}: {item.value}")

# 获取市值
market_cap = get_market_cap("AAPL", "2024-03-31")
print(f"市值: ${market_cap:,.0f}")
```

### 错误处理

API 调用可能因为多种原因失败，包括网络问题、API 限制、数据不存在等。系统实现了以下错误处理机制：

**指数退避重试**：对于临时性错误（如网络超时、429 Too Many Requests），系统会指数退避重试，最多重试 3 次。

**异常转换**：将底层异常转换为统一的错误类型，便于上层处理。常见错误类型包括 `APIError`、`RateLimitError`、`DataNotFoundError` 等。

**备用数据源**：对于某些数据，可以配置备用数据源（如 Yahoo Finance），在主数据源失败时自动切换。

## 4.3 缓存策略

### 缓存架构

系统实现了多层缓存架构，包括内存缓存和磁盘缓存两个层面。

**内存缓存（_prices_cache 等）**：在进程生命周期内保持，用于存储频繁访问的数据。内存缓存使用字典实现，键为缓存键，值为缓存数据。

**磁盘缓存（data/cache/ 目录）**：持久化存储，用于跨进程共享和程序重启后保留。磁盘缓存使用 Pickle 格式存储，便于快速序列化和反序列化。

### 缓存键生成

缓存键是区分不同数据请求的唯一标识。系统使用以下规则生成缓存键：

**价格数据缓存键**：`prices:{ticker}:{start_date}:{end_date}`

**财务指标缓存键**：`metrics:{ticker}:{end_date}`

**财务报表科目缓存键**：`line_items:{ticker}:{fields}:{end_date}`

其中 `fields` 为按字母排序后的科目列表，确保相同数据的不同请求使用相同的缓存键。

### 缓存过期策略

不同类型的数据有不同的缓存过期策略：

**日级价格数据**：缓存 1 天，因为当日价格可能变化。

**财务指标**：缓存 7 天，财务报表按季度发布，不需要频繁更新。

**财务报表科目**：缓存 7 天，与财务指标相同。

**公司新闻**：缓存 1 小时，新闻更新较频繁。

**市值数据**：缓存 1 天。

### 缓存管理接口

```python
from src.data.cache import (
    get_cached_prices,
    cache_prices,
    clear_expired_cache,
    clear_all_cache
)

# 获取缓存（如果存在且未过期）
prices = get_cached_prices("AAPL", "2024-01-01", "2024-03-01")
if prices is None:
    # 缓存未命中，从 API 获取
    prices = get_prices("AAPL", "2024-01-01", "2024-03-01")
    # 存入缓存
    cache_prices("AAPL", "2024-01-01", "2024-03-01", prices)

# 清理过期缓存
clear_expired_cache()

# 清理所有缓存
clear_all_cache()
```

### 缓存优化建议

缓存是提高系统性能的关键。以下是一些缓存优化的最佳实践：

**预热重要数据**：对于常用的股票（如 AAPL、MSFT），可以在系统启动时预热缓存。

**监控缓存命中率**：定期检查缓存命中率，识别可以优化的地方。

**限制缓存大小**：设置最大缓存条目数，避免内存溢出。

**清理过期数据**：定期运行清理任务，删除过期缓存。

## 4.4 数据质量控制

### 数据验证

系统在存储数据前会进行基本验证：

**格式验证**：检查数据类型和格式是否符合预期。

**逻辑验证**：检查数值是否在合理范围内，如价格是否为正数、成交量是否为非负数。

**完整性检查**：检查必要字段是否缺失。

### 缺失数据处理

当检测到缺失数据时，系统采用以下策略：

**价格数据**：使用前向填充（Forward Fill），用最近一天的价格填充缺失日期。

**财务指标**：标记为不可用，避免使用不完整的数据进行分析。

**新闻数据**：跳过缺失的新闻记录，不影响其他数据获取。

### 数据一致性

为确保数据一致性，系统采取以下措施：

**事务性更新**：批量数据更新使用事务，确保要么全部成功，要么全部回滚。

**版本控制**：数据更新时检查版本，避免覆盖新数据。

**审计日志**：记录所有数据变更，便于追踪问题。

## 4.5 添加新数据源

### 数据源接口

要添加新的数据源，需要实现以下接口：

```python
from abc import ABC, abstractmethod
from typing import List, Optional
from src.data.models import Price, FinancialMetrics

class DataSource(ABC):
    """数据源抽象基类"""
    
    @abstractmethod
    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> List[Price]:
        """获取价格数据"""
        pass
    
    @abstractmethod
    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str
    ) -> Optional[FinancialMetrics]:
        """获取财务指标"""
        pass
    
    @abstractmethod
    def health_check(self) -> bool:
        """检查数据源健康状态"""
        pass
```

### 注册新数据源

在 `src/data/sources.py` 中注册新数据源：

```python
from src.data.sources import register_source

# 注册新数据源
register_source("my_datasource", MyDataSource)
```

### 配置多数据源

配置文件支持指定首选和备用数据源：

```yaml
data_sources:
  primary: financial_datasets
  fallback:
    - yahoo_finance
    - alpha_vantage
```

## 4.6 练习题

### 练习 4.1：数据获取实验

**任务**：获取并分析不同类型的数据。

**步骤**：首先编写脚本获取 AAPL 的价格数据并计算日收益率，然后获取 AAPL 的财务指标并打印关键指标，接着获取 AAPL 最近 30 天的新闻，最后获取 AAPL 的内幕交易数据。

**要求**：记录每个 API 调用的响应时间和数据量。

### 练习 4.2：缓存效果测试

**任务**：比较有无缓存时的 API 调用性能。

**实验设计**：首先清除所有缓存，然后测量首次获取数据的耗时，接着重复获取相同数据，最后测量缓存命中的耗时。

**要求**：计算缓存命中率提升的性能倍数。

### 练习 4.3：自定义数据源

**任务**：实现一个简单的自定义数据源。

**步骤**：创建一个新的数据源类，实现必需的方法，在配置文件中注册该数据源，测试数据获取功能。

**要求**：自定义数据源至少实现价格和财务指标两个接口。

---

## 进阶思考

思考以下问题。缓存策略如何平衡数据时效性和性能？不同类型的数据应该采用怎样的缓存过期策略？如何设计一个能够自动学习最优缓存策略的系统？

下一章节我们将学习风险管理的基本原理和实现方法。
