"""
数据提供商模块

提供各种数据源的统一接口
"""

from src.data.base_provider import (
    BaseDataProvider,
    DataRequest,
    DataResponse,
    DataType,
    DataProviderError,
    RateLimitError,
    APIError,
    ValidationError,
)

# 导入具体提供商
try:
    from src.data.providers.akshare_provider import AKShareProvider
except ImportError:
    AKShareProvider = None

try:
    from src.data.providers.tushare_provider import TushareProvider
except ImportError:
    TushareProvider = None

# Mock 提供商总是可用
from src.data.providers.mock_provider import MockProvider

__all__ = [
    "BaseDataProvider",
    "DataRequest",
    "DataResponse",
    "DataType",
    "DataProviderError",
    "RateLimitError",
    "APIError",
    "ValidationError",
    "AKShareProvider",
    "TushareProvider",
    "MockProvider",
]
