# 第四章：数据获取与缓存管理

## 学习目标

完成本章节学习后，你将能够：

### 基础目标（必掌握）⭐

- [ ] 记住系统数据架构的四个层次：数据源层、缓存层、接口层、应用层
- [ ] 列举系统支持的六种金融数据类型：价格数据、财务指标、财务报表项目、公司新闻、内幕交易、市值数据
- [ ] 正确调用 Financial Datasets API 的核心函数：`get_prices()`、`get_financial_metrics()`、`search_line_items()`
- [ ] 解释 **OHLCV**（Open-High-Low-Close-Volume，开盘价-最高价-最低价-收盘价-成交量）的含义
- [ ] 使用缓存管理接口获取和存储数据

### 进阶目标（建议掌握）⭐⭐

- [ ] 分析缓存策略的权衡：时效性 vs 性能 vs 存储成本
- [ ] 根据数据特性选择合适的缓存过期时间
- [ ] 诊断缓存命中率问题并提出优化方案
- [ ] 理解数据验证的三种策略：格式验证、逻辑验证、完整性检查
- [ ] 实现数据源的切换机制和降级策略

### 专家目标（挑战）⭐⭐⭐⭐

- [ ] 设计自定义数据源并集成到系统中
- [ ] 制定团队的缓存策略规范和最佳实践
- [ ] 构建自动化的数据质量监控系统
- [ ] 优化缓存策略以应对高频交易场景
- [ ] 为金融数据 API 建立容灾和降级架构

**预计学习时间**：基础部分 1 小时，进阶部分 2 小时，专家部分 4+ 小时

---

## 4.1 数据架构概述

### 数据流程总览

系统的数据获取架构采用分层设计，从底层到顶层依次为：数据源层、缓存层、接口层和应用层。

#### 为什么采用分层架构？

**设计决策背景**：

在金融数据处理场景中，我们面临三个核心挑战：

1. **成本问题**：外部数据 API（如 Financial Datasets）按调用次数计费，每次请求都有成本
2. **性能问题**：实时获取数据需要网络往返，响应时间通常在 200-500ms
3. **可靠性问题**：外部服务可能因网络波动、配额限制、服务故障而不可用

**可选方案对比**：

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| 直接调用 | 实现简单 | 成本高、性能差 | 低频查询 |
| 简单缓存 | 降低成本 | 单一故障点 | 中频查询 |
| **分层架构**（最终选择） | 平衡性能、成本、可靠性 | 实现复杂度高 | **生产环境** |

**选择理由**：
- **关注点分离**：每层只负责一个职责，便于维护和测试
- **可扩展性**：新增数据源只需实现接口，无需修改应用层
- **容错能力**：缓存层可以作为降级手段，在数据源不可用时仍能提供数据
- **性能优化**：多层缓存（内存 + 磁盘）平衡响应速度和持久化需求

#### 架构四层详解

**数据源层**

负责与外部金融数据 API 交互，获取原始数据。系统目前主要使用 Financial Datasets API 作为数据源，支持价格数据、财务数据、新闻数据等多种数据类型。

> 💡 **知识延伸**：为什么选择 Financial Datasets？
> - 免费额度覆盖常用股票（AAPL、GOOGL、MSFT、NVDA、TSLA）
> - 数据质量高，经过清洗和验证
> - 支持多资产类别（股票、ETF、加密货币）
> - 提供 **SLA（Service Level Agreement，服务等级协议）** 保证

**缓存层**

在内存和磁盘两个层面实现数据缓存，减少重复的 API 调用，提高响应速度，降低 API 成本。缓存策略考虑了数据的时效性和存储成本。

**接口层**

提供统一的数据访问接口，屏蔽底层数据源的差异。应用层通过接口层获取所需数据，无需关心数据的具体来源和缓存细节。

**应用层**

是智能体和回测系统，它们通过接口层获取数据，用于分析和回测。

### 支持的数据类型

系统支持获取以下类型的金融数据：

#### 价格数据（Price Data）

包括 **OHLCV** 数据（Open-High-Low-Close-Volume，开盘价、最高价、最低价、收盘价、成交量），用于技术分析和回测。

> 📚 **术语解释**：OHLCV
> - **O**pen（开盘价）：当日第一笔交易价格
> - **H**igh（最高价）：当日最高成交价格
> - **L**ow（最低价）：当日最低成交价格
> - **C**lose（收盘价）：当日最后一笔交易价格
> - **V**olume（成交量）：当日累计成交股数
> OHLCV 是技术分析的基础数据，几乎所有技术指标（均线、MACD、RSI 等）都基于此计算

#### 财务指标（Financial Metrics）

包括营收、利润、现金流、资产负债等关键财务指标，用于基本面分析。

#### 财务报表项目（Line Items）

包括详细的财务报表科目数据，如资本支出、折旧、研发费用等，用于深度分析。

#### 公司新闻（Company News）

包括公司相关的新闻报道和公告，用于情绪分析和事件驱动策略。

#### 内幕交易（Insider Trades）

包括公司高管和董事的买卖交易信息，作为交易信号的参考。

#### 市值数据（Market Cap）

包括公司的总市值数据，用于估值分析和规模筛选。

---

## 4.2 金融数据 API

### Financial Datasets API 概述

Financial Datasets API 是系统的主要数据来源，提供高质量的金融数据服务。

#### API 核心特性

**全面的数据类型覆盖**：支持股票、ETF、加密货币等多种资产

**丰富的历史数据**：大多数数据可以追溯到 10 年以上

**标准化的数据格式**：易于解析和处理

**可靠的 SLA 保证**：数据的及时性和准确性

> 💡 **设计思考**：为什么需要统一的 API？
> 不同数据源（Bloomberg、Yahoo Finance、Alpha Vantage）的数据格式差异很大：
> - 日期格式：`2024-03-01` vs `01-Mar-2024` vs `1710000000`（时间戳）
> - 字段命名：`close_price` vs `Close` vs `c`
> - 数据结构：JSON vs XML vs CSV
>
> 统一 API 可以：
> 1. 屏蔽底层数据源差异
> 2. 提供一致的开发体验
> 3. 便于切换数据源（降低供应商锁定风险）

### API 接口函数

系统通过 `src/tools/api.py` 文件中的函数与 Financial Datasets API 交互。

#### 核心接口函数

**get_prices(ticker, start_date, end_date)**

获取指定股票在日期范围内的价格数据。

```python
def get_prices(
    ticker: str,
    start_date: str,
    end_date: str
) -> List[Price]:
    """获取价格数据

    Args:
        ticker: 股票代码（如 "AAPL"）
        start_date: 开始日期（格式 "YYYY-MM-DD"）
        end_date: 结束日期（格式 "YYYY-MM-DD"）

    Returns:
        价格数据列表，每条记录包含：
        - date: 日期
        - open: 开盘价
        - high: 最高价
        - low: 最低价
        - close: 收盘价
        - volume: 成交量

    Raises:
        APIError: API 调用失败
        ValueError: 日期格式错误
    """
```

**get_financial_metrics(ticker, end_date)**

获取指定股票的财务指标。

```python
def get_financial_metrics(
    ticker: str,
    end_date: str
) -> List[FinancialMetrics]:
    """获取财务指标

    Args:
        ticker: 股票代码
        end_date: 截止日期（通常为季度末）

    Returns:
        财务指标列表，包含：
        - revenue_growth: 营收增长率
        - net_profit_margin: 净利润率
        - roe: 净资产收益率
        - pe_ratio: 市盈率
        - ...

    Raises:
        APIError: API 调用失败
        DataNotFoundError: 数据不存在
    """
```

**search_line_items(ticker, fields, end_date)**

获取指定股票的财务报表项目数据。

```python
def search_line_items(
    ticker: str,
    fields: List[str],
    end_date: str
) -> List[LineItem]:
    """获取财务报表项目

    Args:
        ticker: 股票代码
        fields: 科目列表，如 ["capital_expenditure", "depreciation"]
        end_date: 截止日期

    Returns:
        财务报表项目列表

    Raises:
        APIError: API 调用失败
    """
```

**get_company_news(ticker, date_range)**

获取指定公司在日期范围内的新闻数据。

**get_insider_trades(ticker, date_range)**

获取指定公司的内幕交易数据。

**get_market_cap(ticker, end_date)**

获取指定公司在指定日期的市值数据。

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

API 调用可能因为多种原因失败。系统实现了以下错误处理机制：

#### 为什么需要错误处理？

金融数据是交易决策的基础，数据错误可能导致：

1. **资金损失**：基于错误数据做出的交易决策可能造成巨额亏损
2. **策略失效**：回测结果与实盘表现严重偏离
3. **系统崩溃**：未捕获的异常导致整个系统中断

#### 三层错误处理机制

**第一层：指数退避重试**

对于临时性错误（如网络超时、429 Too Many Requests），系统会指数退避重试，最多重试 3 次。

> 💡 **原理：指数退避（Exponential Backoff）**
>
> 指数退避是一种重试策略，每次重试的等待时间按指数增长：
> - 第 1 次重试：等待 1 秒
> - 第 2 次重试：等待 2 秒
> - 第 3 次重试：等待 4 秒
>
> **为什么选择指数退避？**
> 1. 避免雪崩：如果所有客户端同时重试，会压垮服务
> 2. 给服务恢复时间：指数增长给服务更多时间恢复
> 3. 减少无效请求：短时间的网络问题可能在几秒内解决

```python
# 指数退避示例
import time

def api_call_with_retry(func, max_retries=3):
    for attempt in range(max_retries):
        try:
            return func()
        except (TimeoutError, RateLimitError) as e:
            if attempt == max_retries - 1:
                raise
            wait_time = 2 ** attempt  # 1, 2, 4
            time.sleep(wait_time)
```

**第二层：异常转换**

将底层异常转换为统一的错误类型，便于上层处理。常见错误类型包括 `APIError`、`RateLimitError`、`DataNotFoundError` 等。

**第三层：备用数据源**

对于某些数据，可以配置备用数据源（如 Yahoo Finance），在主数据源失败时自动切换。

```python
# 备用数据源配置示例
data_sources:
  primary: financial_datasets
  fallback:
    - yahoo_finance
    - alpha_vantage
```

---

## 4.3 缓存策略

### 缓存架构

系统实现了多层缓存架构，包括内存缓存和磁盘缓存两个层面。

#### 内存缓存

在进程生命周期内保持，用于存储频繁访问的数据。内存缓存使用字典实现，键为缓存键，值为缓存数据。

**优点**：
- 访问速度极快（纳秒级）
- 无需序列化/反序列化

**缺点**：
- 进程结束后丢失
- 占用内存资源

#### 磁盘缓存

持久化存储，用于跨进程共享和程序重启后保留。磁盘缓存使用 **Pickle** 格式存储，便于快速序列化和反序列化。

> 📚 **术语解释**：Pickle
>
> Pickle 是 Python 标准库提供的序列化模块，可以将 Python 对象转换为字节流（序列化），也可以从字节流还原对象（反序列化）。
>
> **为什么使用 Pickle？**
> - 原生支持，无需额外依赖
> - 速度快，二进制格式
> - 支持几乎所有的 Python 对象类型
>
> **注意事项**：
> - 不安全：不要反序列化不受信任的数据源
> - 版本兼容性：不同 Python 版本可能不兼容

**优点**：
- 持久化存储
- 跨进程共享

**缺点**：
- 访问速度较慢（毫秒级）
- 需要 I/O 操作

### 缓存键生成

缓存键是区分不同数据请求的唯一标识。系统使用以下规则生成缓存键：

#### 缓存键规则

**价格数据缓存键**：`prices:{ticker}:{start_date}:{end_date}`

**财务指标缓存键**：`metrics:{ticker}:{end_date}`

**财务报表科目缓存键**：`line_items:{ticker}:{fields}:{end_date}`

其中 `fields` 为按字母排序后的科目列表，确保相同数据的不同请求使用相同的缓存键。

> 💡 **设计细节**：为什么对 fields 排序？
>
> 假设请求相同的科目，但顺序不同：
> ```python
> # 请求 A
> search_line_items("AAPL", ["a", "b"], "2024-03-31")
>
> # 请求 B
> search_line_items("AAPL", ["b", "a"], "2024-03-31")
> ```
>
> 如果不排序，缓存键会不同：
> - `line_items:AAPL:a,b:2024-03-31`
> - `line_items:AAPL:b,a:2024-03-31`
>
> 导致缓存无法命中。排序后两者都是 `line_items:AAPL:a,b:2024-03-31`。

### 缓存过期策略

不同类型的数据有不同的缓存过期策略：

#### 缓存过期时间表

| 数据类型 | 过期时间 | 选择理由 |
|----------|----------|----------|
| 日级价格数据 | 1 天 | 当日价格可能变化（盘中价格波动） |
| 财务指标 | 7 天 | 财务报表按季度发布，不需要频繁更新 |
| 财务报表科目 | 7 天 | 与财务指标相同 |
| 公司新闻 | 1 小时 | 新闻更新较频繁，需要保持时效性 |
| 市值数据 | 1 天 | 市值每日变化 |

#### 为什么财务指标缓存 7 天？

财务指标的数据更新频率决定了缓存策略：

1. **季度报表**：上市公司每季度发布一次财报（10-Q）
2. **年报**：每年发布一次年报（10-K）
3. **修正公告**：财报发布后可能有小幅修正（罕见）

因此，7 天的缓存期是合理的选择：
- 足够短：在财报更新后能及时获取新数据
- 足够长：避免频繁调用 API（降低成本）
- 平衡点：在成本和时效性之间取得平衡

> ⚠️ **注意**：对于需要实时数据的场景（如日内交易），可以缩短缓存时间或禁用缓存。

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

**预热重要数据**

对于常用的股票（如 AAPL、MSFT），可以在系统启动时预热缓存。

```python
# 启动时预热常用股票
def warmup_cache():
    popular_tickers = ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA"]
    for ticker in popular_tickers:
        # 预加载价格数据
        get_prices(ticker, "2023-01-01", "2024-12-31")
        # 预加载财务指标
        get_financial_metrics(ticker, "2024-12-31")
```

**监控缓存命中率**

定期检查缓存命中率，识别可以优化的地方。

```python
# 缓存监控
cache_stats = {
    "hits": 1000,
    "misses": 200,
    "hit_rate": 1000 / (1000 + 200) * 100  # 83.33%
}
```

**限制缓存大小**

设置最大缓存条目数，避免内存溢出。

**清理过期数据**

定期运行清理任务，删除过期缓存。

---

## 4.4 数据质量控制

### 数据验证

系统在存储数据前会进行基本验证：

#### 三层验证机制

**格式验证**

检查数据类型和格式是否符合预期。

```python
# 格式验证示例
def validate_price_data(price: Price) -> bool:
    """验证价格数据格式"""
    if not isinstance(price.date, str):
        return False
    if not isinstance(price.close, (int, float)):
        return False
    # ... 更多检查
    return True
```

**逻辑验证**

检查数值是否在合理范围内，如价格是否为正数、成交量是否为非负数。

```python
# 逻辑验证示例
def validate_price_logic(price: Price) -> bool:
    """验证价格数据逻辑"""
    # 价格必须为正数
    if price.close <= 0:
        return False

    # 最高价 >= 最低价
    if price.high < price.low:
        return False

    # 成交量必须非负
    if price.volume < 0:
        return False

    # OHLC 关系：最高 >= 开盘/收盘 >= 最低
    if not (price.low <= price.open <= price.high and
            price.low <= price.close <= price.high):
        return False

    return True
```

**完整性检查**

检查必要字段是否缺失。

### 缺失数据处理

当检测到缺失数据时，系统采用以下策略：

#### 价格数据：前向填充（Forward Fill）

用最近一天的价格填充缺失日期。

> 📚 **术语解释**：前向填充（Forward Fill）
>
> 前向填充是一种时间序列数据填充方法，用前一个有效值填充缺失值。
>
> **示例**：
> ```
> 原始数据：     [100, 105, nan, nan, 110]
> 前向填充后：    [100, 105, 105, 105, 110]
> ```
>
> **为什么价格数据用前向填充？**
> 1. 假设价格在没有新信息时保持不变
> 2. 避免技术指标计算出错（如均线）
> 3. 适用于长期趋势分析

```python
import pandas as pd

# 前向填充示例
df = pd.DataFrame({
    'date': ['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04'],
    'price': [100, 105, None, 110]
})

# 前向填充
df['price'] = df['price'].fillna(method='ffill')
# 结果：[100, 105, 105, 110]
```

#### 财务指标：标记为不可用

避免使用不完整的数据进行分析。

#### 新闻数据：跳过缺失的新闻记录

不影响其他数据获取。

### 数据一致性

为确保数据一致性，系统采取以下措施：

**事务性更新**

批量数据更新使用事务，确保要么全部成功，要么全部回滚。

**版本控制**

数据更新时检查版本，避免覆盖新数据。

**审计日志**

记录所有数据变更，便于追踪问题。

---

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

---

## 4.6 练习题

### 练习 4.1：概念理解（理解型）⭐

**问题**：以下关于缓存策略的描述，正确的是？

A. 财务指标的缓存过期时间应该设为 1 小时，以保证数据实时性
B. 价格数据使用前向填充会导致技术指标计算错误
C. 指数退避重试会导致 API 调用成本增加
D. 多层缓存（内存 + 磁盘）可以在性能和持久化之间取得平衡

**参考答案**：D

**解析**：
- A 错误：财务指标按季度发布，7 天的缓存期更合理
- B 错误：前向填充正是为了避免技术指标计算错误
- C 错误：指数退避减少的是重复调用，反而降低成本
- D 正确：内存缓存提供高速访问，磁盘缓存提供持久化

**知识点回顾**：
- 缓存策略的选择依据是数据更新频率和时效性要求
- 前向填充是处理时间序列缺失数据的有效方法
- 多层缓存的权衡是性能 vs 持久化

---

### 练习 4.2：数据获取实验（应用型）⭐⭐

**任务**：获取并分析不同类型的数据。

**步骤**：
1. 编写脚本获取 AAPL 的价格数据并计算日收益率
2. 获取 AAPL 的财务指标并打印关键指标
3. 获取 AAPL 最近 30 天的新闻
4. 获取 AAPL 的内幕交易数据

**要求**：
- 记录每个 API 调用的响应时间和数据量
- 计算日收益率的均值、标准差、最大值、最小值
- 绘制价格走势图（使用 matplotlib）

**参考代码框架**：

```python
import time
import matplotlib.pyplot as plt
from src.tools.api import get_prices, get_financial_metrics

def analyze_prices():
    """分析价格数据"""
    start_time = time.time()
    prices = get_prices("AAPL", "2024-01-01", "2024-03-01")
    elapsed = time.time() - start_time

    print(f"获取 {len(prices)} 条价格数据，耗时 {elapsed:.2f} 秒")

    # 计算日收益率
    returns = []
    for i in range(1, len(prices)):
        daily_return = (prices[i].close - prices[i-1].close) / prices[i-1].close
        returns.append(daily_return)

    # 统计分析
    print(f"日收益率均值: {sum(returns)/len(returns):.4f}")
    print(f"日收益率标准差: {(sum((r - sum(returns)/len(returns))**2 for r in returns)/len(returns))**0.5:.4f}")
    print(f"最大日收益率: {max(returns):.4f}")
    print(f"最小日收益率: {min(returns):.4f}")

    # 绘制价格走势图
    dates = [p.date for p in prices]
    closes = [p.close for p in prices]

    plt.figure(figsize=(12, 6))
    plt.plot(dates, closes)
    plt.title('AAPL Price Trend')
    plt.xlabel('Date')
    plt.ylabel('Price')
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig('price_trend.png')
    print("价格走势图已保存为 price_trend.png")

if __name__ == "__main__":
    analyze_prices()
```

**常见错误**：
- ❌ 忘记处理空列表（len(prices) == 0）
- ❌ 日收益率计算使用闭盘价/开盘价而非昨日闭盘
- ❌ 绘图时日期过多导致重叠

**扩展挑战**：
- 计算波动率指标
- 添加移动平均线
- 对比多只股票的价格走势

---

### 练习 4.3：缓存效果测试（应用型）⭐⭐

**任务**：比较有无缓存时的 API 调用性能。

**实验设计**：
1. 清除所有缓存
2. 测量首次获取数据的耗时（T1）
3. 重复获取相同数据，测量缓存命中的耗时（T2）
4. 计算缓存命中率提升的性能倍数

**要求**：
- 使用 `time` 模块精确计时
- 重复实验 3 次，取平均值
- 测试不同数据类型（价格、财务指标、新闻）的缓存效果

**参考代码框架**：

```python
import time
from src.data.cache import clear_all_cache, get_cached_prices, cache_prices
from src.tools.api import get_prices

def benchmark_cache(ticker: str, start_date: str, end_date: str):
    """测试缓存效果"""
    # 清除所有缓存
    clear_all_cache()

    # 首次获取（缓存未命中）
    start = time.time()
    prices_1 = get_prices(ticker, start_date, end_date)
    t1 = time.time() - start

    # 存入缓存
    cache_prices(ticker, start_date, end_date, prices_1)

    # 再次获取（缓存命中）
    start = time.time()
    prices_2 = get_cached_prices(ticker, start_date, end_date)
    t2 = time.time() - start

    # 计算性能提升
    speedup = t1 / t2 if t2 > 0 else 0

    print(f"首次获取耗时: {t1*1000:.2f} 毫秒")
    print(f"缓存命中耗时: {t2*1000:.2f} 毫秒")
    print(f"性能提升: {speedup:.1f} 倍")

    return speedup

if __name__ == "__main__":
    benchmark_cache("AAPL", "2024-01-01", "2024-03-01")
```

**预期结果**：
- 首次获取：200-500 毫秒（取决于网络）
- 缓存命中：1-5 毫秒
- 性能提升：50-500 倍

---

### 练习 4.4：自定义数据源（综合型）⭐⭐⭐

**任务**：实现一个简单的自定义数据源。

**需求**：
1. 创建一个新的数据源类 `MockDataSource`
2. 实现必需的方法：`get_prices()`、`get_financial_metrics()`、`health_check()`
3. 使用模拟数据返回结果（不调用真实 API）
4. 在配置文件中注册该数据源
5. 测试数据获取功能

**参考代码框架**：

```python
from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime, timedelta
from src.data.models import Price, FinancialMetrics

class MockDataSource(DataSource):
    """模拟数据源（用于测试）"""

    def __init__(self):
        self.is_healthy = True

    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> List[Price]:
        """获取模拟价格数据"""
        prices = []
        current_date = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        base_price = 100.0  # 基准价格

        while current_date <= end_dt:
            # 生成随机价格波动
            import random
            change = random.uniform(-2, 2)  # ±2 的随机波动
            open_price = base_price + change
            high_price = open_price + random.uniform(0, 1)
            low_price = open_price - random.uniform(0, 1)
            close_price = open_price + random.uniform(-1, 1)
            volume = random.randint(1000000, 10000000)

            price = Price(
                date=current_date.strftime("%Y-%m-%d"),
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume
            )
            prices.append(price)

            current_date += timedelta(days=1)
            base_price = close_price  # 下一日基准为今日收盘价

        return prices

    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str
    ) -> Optional[FinancialMetrics]:
        """获取模拟财务指标"""
        import random
        return FinancialMetrics(
            ticker=ticker,
            revenue_growth=random.uniform(-0.1, 0.3),  # -10% 到 30%
            net_profit_margin=random.uniform(0.05, 0.25),  # 5% 到 25%
            roe=random.uniform(0.1, 0.3),  # 10% 到 30%
            pe_ratio=random.uniform(10, 50)
        )

    def health_check(self) -> bool:
        """检查数据源健康状态"""
        return self.is_healthy
```

**评估标准**：

| 维度 | 标准 | 分值 |
|------|------|------|
| 功能完整性 | 所有必需方法都正确实现 | 30% |
| 数据合理性 | 生成的模拟数据符合金融常识 | 25% |
| 代码质量 | 可读性、可维护性 | 25% |
| 测试覆盖 | 有单元测试验证 | 20% |

**学习目标**：
完成本练习后，你将掌握：
- 理解数据源接口的设计思想
- 实现一个完整的数据源类
- 使用模拟数据进行开发和测试

---

### 练习 4.5：缓存策略诊断（诊断型）⭐⭐⭐

**场景**：你负责的系统出现以下问题...

**问题描述**：
> 用户反馈数据加载速度不稳定，有时很快（< 10ms），有时很慢（> 500ms）。

**监控数据**：
- 缓存命中率：70%
- API 调用次数：正常范围内
- 数据量：近期增长 50%

**你的任务**：
1. 分析可能的原因（列出至少 3 个假设）
2. 设计验证方案（如何确认每个假设）
3. 提出解决方案

**参考答案框架**：

**假设一**：缓存键冲突导致缓存未命中
**验证方法**：检查缓存键生成逻辑，确认是否有键冲突
**解决方案**：优化缓存键生成策略，使用更唯一标识

**假设二**：热门股票缓存被冷门数据挤出
**验证方法**：分析缓存使用情况，检查 LRU（最近最少使用）策略
**解决方案**：为热门股票设置更长的缓存时间

**假设三**：API 响应时间不稳定
**验证方法**：记录每次 API 调用的响应时间，绘制分布图
**解决方案**：增加备用数据源，实现降级机制

**专家点评**：
- 这类问题的典型排查顺序是：先看缓存命中率，再看缓存内容分布，最后看 API 性能
- 应该优先检查是否有缓存失效策略导致大量数据同时过期

---

## 自检清单

完成本章节学习后，请自检以下能力：

### 基础技能自检 ⭐

#### 概念理解
- [ ] 能够用自己的话解释四层数据架构的设计思想
- [ ] 能够区分内存缓存和磁盘缓存的适用场景
- [ ] 知道 OHLCV 的含义和应用场景

#### 动手能力
- [ ] 能够独立使用 Financial Datasets API 获取价格和财务数据
- [ ] 能够使用缓存管理接口存储和读取数据
- [ ] 能够处理常见的 API 错误

#### 问题解决
- [ ] 能够诊断缓存未命中的原因
- [ ] 能够修复缺失数据导致的错误
- [ ] 能够优化简单的缓存策略

### 进阶技能自检 ⭐⭐

#### 原理理解
- [ ] 理解指数退避重试的设计原理和适用场景
- [ ] 理解前向填充的优缺点和替代方案
- [ ] 理解多层缓存架构的权衡

#### 综合应用
- [ ] 能够为不同类型的数据设计合理的缓存策略
- [ ] 能够实现自定义数据源并集成到系统
- [ ] 能够诊断性能问题并提出优化方案

#### 专家思维
- [ ] 能够评估不同数据源的成本和收益
- [ ] 能够设计数据质量监控系统
- [ ] 能够制定团队的缓存策略规范

---

## 进阶思考

思考以下问题：

1. **缓存策略如何平衡数据时效性和性能？**
   - 提示：考虑不同用户场景（日内交易 vs 长期投资）

2. **不同类型的数据应该采用怎样的缓存过期策略？**
   - 提示：分析每种数据的更新频率和业务影响

3. **如何设计一个能够自动学习最优缓存策略的系统？**
   - 提示：考虑机器学习方法、历史数据分析、用户行为预测

4. **如果 Financial Datasets API 完全不可用，系统应该如何降级？**
   - 提示：考虑备用数据源、本地缓存、数据估算等方法

---

## 章节总结

本章节我们学习了：

### 核心概念
- ✅ 四层数据架构：数据源层、缓存层、接口层、应用层
- ✅ 六种金融数据类型：价格、财务指标、财务报表项目、新闻、内幕交易、市值
- ✅ 缓存策略：内存缓存 + 磁盘缓存，根据数据特性设置过期时间

### 实践技能
- ✅ 使用 Financial Datasets API 获取数据
- ✅ 实现和管理缓存
- ✅ 处理缺失数据和错误
- ✅ 添加自定义数据源

### 专家思维
- ✅ 理解设计决策的权衡
- ✅ 诊断和优化性能问题
- ✅ 设计容错和降级机制

**下一章节我们将学习风险管理的基本原理和实现方法。**

---

## 版本信息

| 项目 | 信息 |
|------|------|
| 文档版本 | 2.0.0 |
| 最后更新 | 2026年2月 |
| 适用版本 | 1.0.0+ |
| 难度级别 | ⭐⭐（核心概念） |

**更新日志**：
- v2.0.0 (2026.02)：按照 chinese-doc-writer 标准全面改进
  - 添加分层学习目标（基础/进阶/专家）
  - 完善术语管理，确保英文术语有中文解释
  - 优化认知负荷，使用分块呈现和渐进式复杂度
  - 增强原理解析，添加"为什么"的解释
  - 完善练习设计，增加理解型和诊断型练习
  - 修正格式规范，统一中英文混排
  - 添加自检清单和技能认证机制
- v1.0.2 (2026.02)：增加备用数据源配置说明
- v1.0.1 (2025.12)：完善缓存过期策略
- v1.0.0 (2025.10)：初始版本

---

## 反馈与贡献

如果您在阅读过程中发现问题或有改进建议，欢迎通过 GitHub Issues 提交反馈。

**改进建议方向**：
- 学习目标是否清晰可测？
- 概念解释是否易懂？
- 练习难度是否合适？
- 示例代码是否清晰？
- 是否有遗漏的重要知识点？

**贡献指南**：
1. Fork 本仓库
2. 创建改进分支
3. 提交 Pull Request
4. 说明改进点

感谢您的反馈和贡献！
