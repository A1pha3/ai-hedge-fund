"""
新数据 API 模块

使用新架构的统一数据获取接口
"""

import asyncio
from typing import List, Optional
import pandas as pd

from src.data import (
    get_router,
    DataRouter,
    DataValidator,
    DataCleaner,
    Price,
    FinancialMetrics,
    CompanyNews,
)


async def get_prices(
    ticker: str,
    start_date: str,
    end_date: str,
    use_cache: bool = True,
    validate: bool = True
) -> List[Price]:
    """
    获取价格数据（新架构）
    
    Args:
        ticker: 股票代码
        start_date: 开始日期（YYYY-MM-DD）
        end_date: 结束日期（YYYY-MM-DD）
        use_cache: 是否使用缓存
        validate: 是否验证数据
    
    Returns:
        Price 对象列表
    
    Example:
        >>> prices = await get_prices("600519", "2024-01-01", "2024-01-31")
        >>> print(f"Got {len(prices)} price records")
    """
    router = get_router()
    
    response = await router.get_prices(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        use_cache=use_cache
    )
    
    if response.error:
        raise Exception(f"Failed to get prices: {response.error}")
    
    prices = response.data
    
    # 数据验证和清洗
    if validate and prices:
        prices = DataValidator.validate_prices(prices)
        prices = DataCleaner.clean_prices(prices)
    
    return prices


async def get_financial_metrics(
    ticker: str,
    end_date: str,
    limit: int = 10,
    use_cache: bool = True,
    validate: bool = True
) -> List[FinancialMetrics]:
    """
    获取财务指标（新架构）
    
    Args:
        ticker: 股票代码
        end_date: 截止日期（YYYY-MM-DD）
        limit: 返回记录数
        use_cache: 是否使用缓存
        validate: 是否验证数据
    
    Returns:
        FinancialMetrics 对象列表
    
    Example:
        >>> metrics = await get_financial_metrics("600519", "2024-01-31")
        >>> print(f"P/E ratio: {metrics[0].price_to_earnings_ratio}")
    """
    router = get_router()
    
    response = await router.get_financial_metrics(
        ticker=ticker,
        end_date=end_date,
        limit=limit,
        use_cache=use_cache
    )
    
    if response.error:
        raise Exception(f"Failed to get financial metrics: {response.error}")
    
    metrics = response.data
    
    # 数据验证和清洗
    if validate and metrics:
        metrics = DataValidator.validate_financial_metrics(metrics)
        metrics = DataCleaner.clean_financial_metrics(metrics)
    
    return metrics


async def get_company_news(
    ticker: str,
    start_date: str,
    end_date: str,
    use_cache: bool = True,
    validate: bool = True
) -> List[CompanyNews]:
    """
    获取公司新闻（新架构）
    
    Args:
        ticker: 股票代码
        start_date: 开始日期
        end_date: 结束日期
        use_cache: 是否使用缓存
        validate: 是否验证数据
    
    Returns:
        CompanyNews 对象列表
    """
    router = get_router()
    
    response = await router.get_company_news(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        use_cache=use_cache
    )
    
    if response.error:
        raise Exception(f"Failed to get company news: {response.error}")
    
    news = response.data
    
    # 数据验证和清洗
    if validate and news:
        news = DataValidator.validate_news(news)
        news = DataCleaner.clean_news(news)
    
    return news


def prices_to_df(prices: List[Price]) -> pd.DataFrame:
    """
    将 Price 列表转换为 DataFrame
    
    Args:
        prices: Price 对象列表（可以是 Price 对象或字典）
    
    Returns:
        pandas DataFrame
    """
    if not prices:
        return pd.DataFrame()
    
    # 处理 Price 对象或字典
    data = []
    for p in prices:
        if hasattr(p, 'model_dump'):
            data.append(p.model_dump())
        elif isinstance(p, dict):
            data.append(p)
        else:
            data.append(p.__dict__)
    
    df = pd.DataFrame(data)
    df["Date"] = pd.to_datetime(df["time"])
    df.set_index("Date", inplace=True)
    
    numeric_cols = ["open", "close", "high", "low", "volume"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    df.sort_index(inplace=True)
    return df


async def get_price_data(
    ticker: str,
    start_date: str,
    end_date: str
) -> pd.DataFrame:
    """
    获取价格数据并转换为 DataFrame
    
    Args:
        ticker: 股票代码
        start_date: 开始日期
        end_date: 结束日期
    
    Returns:
        pandas DataFrame
    """
    prices = await get_prices(ticker, start_date, end_date)
    return prices_to_df(prices)


# 同步包装函数（方便在同步代码中使用）
def get_prices_sync(
    ticker: str,
    start_date: str,
    end_date: str,
    **kwargs
) -> List[Price]:
    """
    同步获取价格数据
    
    Args:
        ticker: 股票代码
        start_date: 开始日期
        end_date: 结束日期
        **kwargs: 其他参数
    
    Returns:
        Price 对象列表
    """
    return asyncio.run(get_prices(ticker, start_date, end_date, **kwargs))


def get_financial_metrics_sync(
    ticker: str,
    end_date: str,
    **kwargs
) -> List[FinancialMetrics]:
    """
    同步获取财务指标
    
    Args:
        ticker: 股票代码
        end_date: 截止日期
        **kwargs: 其他参数
    
    Returns:
        FinancialMetrics 对象列表
    """
    return asyncio.run(get_financial_metrics(ticker, end_date, **kwargs))


def get_price_data_sync(
    ticker: str,
    start_date: str,
    end_date: str
) -> pd.DataFrame:
    """
    同步获取价格数据 DataFrame
    
    Args:
        ticker: 股票代码
        start_date: 开始日期
        end_date: 结束日期
    
    Returns:
        pandas DataFrame
    """
    return asyncio.run(get_price_data(ticker, start_date, end_date))
