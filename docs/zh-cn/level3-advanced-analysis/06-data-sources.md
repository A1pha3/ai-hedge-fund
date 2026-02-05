# 第六章：数据源集成

## 学习目标

完成本章节学习后，你将能够理解系统数据获取的整体架构，掌握添加新数据源的方法和最佳实践，学会实现数据质量控制和数据治理，以及能够设计可靠的数据管道。预计学习时间为 2-3 小时。

## 6.1 数据架构概述

### 数据层设计原则

系统的数据层设计遵循几个核心原则，以确保数据的可靠性、可扩展性和可维护性。

**抽象化原则**：通过定义统一的数据接口，屏蔽不同数据源的实现细节。上层应用无需关心数据来自哪个提供商，只需调用统一的 API。

**缓存策略**：实现多层缓存机制，减少重复的 API 调用，提高响应速度并降低成本。

**容错机制**：当主数据源不可用时，自动切换到备用数据源，确保服务连续性。

**数据治理**：实施数据验证、清洗和质量检查，确保数据的准确性和一致性。

### 数据流程

```
┌─────────────────────────────────────────────────────────────────┐
│                        数据流程                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────┐    │
│  │ 数据请求 │───→│ 请求路由      │───→│ 主数据源查询     │    │
│  └──────────┘    │ (负载均衡)   │    └────────┬─────────┘    │
│                  └──────────────┘             │               │
│                                               ▼               │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────┐    │
│  │ 数据响应 │←───│ 结果聚合      │←───│ 备用数据源查询   │    │
│  └──────────┘    │ (容错处理)    │    └──────────────────┘    │
│                  └──────────────┘             │               │
│                                               ▼               │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────┐    │
│  │ 应用使用 │←───│ 缓存层        │←───│ 数据验证/清洗    │    │
│  └──────────┘    │ (LRU + Redis) │    └──────────────────┘    │
│                  └──────────────┘                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 6.2 数据源接口设计

### 统一数据接口

```python
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Generator
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class DataType(Enum):
    """数据类型枚举"""
    PRICE = "price"
    FUNDAMENTAL = "fundamental"
    NEWS = "news"
    INSIDER_TRADE = "insider_trade"
    ECONOMIC = "economic"

@dataclass
class DataRequest:
    """数据请求"""
    ticker: str
    data_type: DataType
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    fields: Optional[List[str]] = None
    kwargs: Optional[Dict[str, Any]] = None

@dataclass
class DataResponse:
    """数据响应"""
    data: Any
    source: str
    timestamp: datetime
    cached: bool = False
    error: Optional[str] = None

class BaseDataProvider(ABC):
    """数据提供商抽象基类"""
    
    def __init__(self, name: str, priority: int = 100):
        self.name = name
        self.priority = priority  # 优先级，数值越小优先级越高
        self.health_status = "unknown"
    
    @abstractmethod
    async def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """获取价格数据"""
        pass
    
    @abstractmethod
    async def get_financial_metrics(
        self,
        ticker: str,
        end_date: str
    ) -> Dict[str, Any]:
        """获取财务指标"""
        pass
    
    @abstractmethod
    async def get_company_news(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """获取公司新闻"""
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查"""
        pass
    
    @abstractmethod
    def rate_limit_info(self) -> Dict[str, Any]:
        """速率限制信息"""
        pass
```

### Financial Datasets 提供商实现

```python
class FinancialDatasetsProvider(BaseDataProvider):
    """Financial Datasets API 提供商"""
    
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.financialdatasets.ai"
    ):
        super().__init__("financial_datasets", priority=1)
        self.api_key = api_key
        self.base_url = base_url
        self.session = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取异步 HTTP 会话"""
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
        """获取价格数据"""
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
                raise RateLimitError("Financial Datasets API rate limit exceeded")
            else:
                raise APIError(f"Financial Datasets API error: {response.status}")
    
    async def get_financial_metrics(
        self,
        ticker: str,
        end_date: str
    ) -> Dict[str, Any]:
        """获取财务指标"""
        session = await self._get_session()
        
        url = f"{self.base_url}/financials/metrics"
        params = {
            "ticker": ticker,
            "end_date": end_date
        }
        
        async with session.get(url, params=params) as response:
            if response.status == 200:
                return await response.json()
            else:
                raise APIError(f"Financial Datasets API error: {response.status}")
    
    async def get_company_news(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """获取公司新闻"""
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
                raise APIError(f"Financial Datasets API error: {response.status}")
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/health") as response:
                return response.status == 200
        except Exception:
            return False
    
    def rate_limit_info(self) -> Dict[str, Any]:
        """速率限制信息"""
        return {
            "requests_per_minute": 100,
            "requests_per_day": 10000,
            "backoff_strategy": "exponential"
        }
    
    async def close(self):
        """关闭会话"""
        if self.session and not self.session.closed:
            await self.session.close()
```

### 备用数据源实现

```python
class YahooFinanceProvider(BaseDataProvider):
    """Yahoo Finance 数据提供商（备用）"""
    
    def __init__(self):
        super().__init__("yahoo_finance", priority=10)
        self._cache = {}
    
    async def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """获取价格数据（使用 yfinance 库）"""
        try:
            import yfinance as yf
            
            stock = yf.Ticker(ticker)
            hist = stock.history(
                start=start_date,
                end=end_date
            )
            
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
        """获取财务指标"""
        import yfinance as yf
        
        stock = yf.Ticker(ticker)
        info = stock.info
        
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
        """获取公司新闻"""
        # Yahoo Finance 没有直接的新闻 API
        return []
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            import yfinance as yf
            stock = yf.Ticker("AAPL")
            _ = stock.info
            return True
        except Exception:
            return False
    
    def rate_limit_info(self) -> Dict[str, Any]:
        """速率限制信息"""
        return {
            "requests_per_minute": 100,
            "requests_per_day": None,  # 无明确限制
            "backoff_strategy": "retry"
        }
```

## 6.3 数据路由器

### 智能路由

```python
class DataRouter:
    """数据路由器"""
    
    def __init__(self):
        self.providers: Dict[str, BaseDataProvider] = {}
        self.fallback_chains: Dict[DataType, List[str]] = {}
        self.load_balancer: Dict[str, int] = {}
    
    def register_provider(self, provider: BaseDataProvider):
        """注册数据提供商"""
        self.providers[provider.name] = provider
        self.load_balancer[provider.name] = 0
    
    def configure_fallback_chain(
        self,
        data_type: DataType,
        provider_names: List[str]
    ):
        """配置备用链路"""
        self.fallback_chains[data_type] = provider_names
    
    async def get_data(
        self,
        request: DataRequest
    ) -> DataResponse:
        """获取数据（带容错）"""
        data_type = request.data_type
        chain = self.fallback_chains.get(data_type, list(self.providers.keys()))
        
        last_error = None
        
        for provider_name in chain:
            provider = self.providers[provider_name]
            
            # 检查提供商健康状态
            if not await provider.health_check():
                continue
            
            # 负载均衡选择
            if self._should_skip_provider(provider_name):
                continue
            
            try:
                # 选择对应方法
                method = self._get_method(provider, data_type)
                if method is None:
                    continue
                
                # 调用数据获取
                data = await method(request)
                
                # 更新负载计数
                self.load_balancer[provider_name] += 1
                
                return DataResponse(
                    data=data,
                    source=provider_name,
                    timestamp=datetime.now(),
                    cached=False
                )
            
            except Exception as e:
                last_error = e
                # 记录失败，尝试下一个提供商
                continue
        
        # 所有提供商都失败
        raise DataProviderError(
            f"All providers failed for {data_type.value}: {str(last_error)}"
        )
    
    def _should_skip_provider(self, provider_name: str) -> bool:
        """检查是否应该跳过提供商"""
        # 简单实现：连续失败 3 次后跳过
        return False  # 简化处理
    
    def _get_method(
        self,
        provider: BaseDataProvider,
        data_type: DataType
    ):
        """获取对应的数据获取方法"""
        method_map = {
            DataType.PRICE: provider.get_prices,
            DataType.FUNDAMENTAL: provider.get_financial_metrics,
            DataType.NEWS: provider.get_company_news,
        }
        return method_map.get(data_type)
```

## 6.4 数据质量控制

### 验证规则

```python
from pydantic import BaseModel, validator, confloat
from typing import Optional

class PriceData(BaseModel):
    """价格数据模型"""
    date: str
    open: confloat(gt=0)
    high: confloat(gt=0)
    low: confloat(gt=0)
    close: confloat(gt=0)
    volume: int = 0
    
    @validator('high')
    def high_must_be_valid(cls, v, values):
        if 'low' in values and v < values['low']:
            raise ValueError('high must be >= low')
        return v
    
    @validator('close')
    def close_must_be_valid(cls, v, values):
        if 'open' in values and abs(v - values['open']) > 0.5 * values['open']:
            raise ValueError('close price seems anomalous')
        return v

class FinancialMetrics(BaseModel):
    """财务指标模型"""
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    roe: Optional[confloat(ge=-1, le=1)] = None
    debt_to_equity: Optional[float] = None
    revenue_growth: Optional[confloat(ge=-1, le=10)] = None
    profit_margin: Optional[confloat(ge=-1, le=1)] = None

class DataValidator:
    """数据验证器"""
    
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
        """验证数据"""
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

### 数据清洗

```python
class DataCleaner:
    """数据清洗器"""
    
    @staticmethod
    def clean_price_data(prices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """清洗价格数据"""
        cleaned = []
        
        for price in prices:
            # 处理缺失值
            if price.get('close') is None:
                # 使用前向填充
                if cleaned:
                    price['close'] = cleaned[-1]['close']
                else:
                    continue  # 跳过第一条
            
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
        """标准化日期格式"""
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
        """填充缺失值"""
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
                        # 向前查找
                        new_item[col] = None  # 简化处理
                else:
                    last_values[col] = new_item[col]
            
            filled.append(new_item)
        
        return filled
```

## 6.5 数据治理

### 数据血缘追踪

```python
class DataLineageTracker:
    """数据血缘追踪"""
    
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
        """记录血缘"""
        record = {
            "data_id": data_id,
            "source": source,
            "transformation": transformation,
            "timestamp": timestamp,
            "metadata": metadata or {}
        }
        self.lineage_records.append(record)
    
    def get_data_sources(self, data_id: str) -> List[Dict]:
        """获取数据来源"""
        return [
            r for r in self.lineage_records
            if r["data_id"] == data_id
        ]
    
    def trace_impact(self, source_id: str) -> List[str]:
        """追踪影响范围"""
        impacted = []
        for record in self.lineage_records:
            if record["source"] == source_id:
                impacted.append(record["data_id"])
        return impacted
```

### 数据目录

```python
class DataCatalog:
    """数据目录"""
    
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
        """注册数据集"""
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
        """搜索数据集"""
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
        """获取数据集信息"""
        return self.catalog.get(dataset_id)
```

## 6.6 练习题

### 练习 6.1：实现数据提供商

**任务**：实现一个新的数据提供商的完整集成。

**要求**：实现 BaseDataProvider 接口，实现所有必需的数据获取方法，实现健康检查和速率限制处理，编写单元测试。

### 练习 6.2：数据质量系统

**任务**：实现完整的数据质量控制系统。

**要求**：实现多类型数据验证器，实现数据清洗功能，实现异常检测和告警。

### 练习 6.3：数据治理框架

**任务**：实现数据治理的基础设施。

**要求**：实现数据血缘追踪，实现数据目录系统，实现数据质量监控。
