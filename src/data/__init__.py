"""
数据模块

提供统一的数据获取、缓存、验证功能
"""

# 基础提供商接口
from src.data.base_provider import (
    APIError,
    BaseDataProvider,
    DataProviderError,
    DataRequest,
    DataResponse,
    DataType,
    RateLimitError,
    ValidationError,
)

# 缓存
from src.data.cache import (
    Cache,
    get_cache,
)
from src.data.enhanced_cache import (
    CacheAdapter,
    EnhancedCache,
    get_enhanced_cache,
)

# 基础模型
from src.data.models import (
    CompanyNews,
    CompanyNewsResponse,
    FinancialMetrics,
    FinancialMetricsResponse,
    InsiderTrade,
    InsiderTradeResponse,
    LineItem,
    LineItemResponse,
    Price,
    PriceResponse,
)

# 提供商
from src.data.providers import (
    AKShareProvider,
    MockProvider,
    TushareProvider,
)

# 路由器
from src.data.router import (
    DataRouter,
    get_router,
)

# 验证和清洗
from src.data.validator import (
    DataCleaner,
    DataPipeline,
    DataValidator,
    default_pipeline,
)

__all__ = [
    # 模型
    "Price",
    "FinancialMetrics",
    "CompanyNews",
    "InsiderTrade",
    "LineItem",
    "PriceResponse",
    "FinancialMetricsResponse",
    "CompanyNewsResponse",
    "InsiderTradeResponse",
    "LineItemResponse",
    # 提供商接口
    "BaseDataProvider",
    "DataRequest",
    "DataResponse",
    "DataType",
    "DataProviderError",
    "RateLimitError",
    "APIError",
    "ValidationError",
    # 路由器
    "DataRouter",
    "get_router",
    # 缓存
    "Cache",
    "get_cache",
    "EnhancedCache",
    "CacheAdapter",
    "get_enhanced_cache",
    # 验证和清洗
    "DataValidator",
    "DataCleaner",
    "DataPipeline",
    "default_pipeline",
    # 提供商
    "AKShareProvider",
    "TushareProvider",
    "MockProvider",
]
