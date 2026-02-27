"""
财务计算工具模块 - 提供统一的财务指标计算方法

此模块确保所有分析师使用一致的计算逻辑，避免数据不一致问题。
"""

import math
from typing import List, Optional


def calculate_revenue_growth_cagr(revenues: List[float], years: Optional[int] = None) -> Optional[float]:
    """
    计算收入增长的复合年增长率 (CAGR)

    Args:
        revenues: 收入列表，按时间顺序从新到旧排列 [最新, ..., 最旧]
        years: 计算CAGR的年数，如果为None则使用全部数据

    Returns:
        CAGR 值，如果无法计算则返回 None
    """
    if not revenues or len(revenues) < 2:
        return None

    # 过滤掉 None 和负数
    valid_revenues = [r for r in revenues if r is not None and r > 0]
    if len(valid_revenues) < 2:
        return None

    latest = valid_revenues[0]
    oldest = valid_revenues[-1] if years is None else valid_revenues[min(years, len(valid_revenues) - 1)]

    if oldest <= 0:
        return None

    n_years = len(valid_revenues) - 1 if years is None else min(years, len(valid_revenues) - 1)
    if n_years <= 0:
        return None

    try:
        cagr = (latest / oldest) ** (1 / n_years) - 1
        if math.isfinite(cagr):
            return cagr
    except (ValueError, ZeroDivisionError, OverflowError):
        pass

    return None


def calculate_simple_revenue_growth(revenues: List[float]) -> Optional[float]:
    """
    计算简单的收入增长率（最新一期相比最旧一期）

    Args:
        revenues: 收入列表，按时间顺序从新到旧排列 [最新, ..., 最旧]

    Returns:
        简单增长率，如果无法计算则返回 None
    """
    if not revenues or len(revenues) < 2:
        return None

    valid_revenues = [r for r in revenues if r is not None and r != 0]
    if len(valid_revenues) < 2:
        return None

    latest = valid_revenues[0]
    oldest = valid_revenues[-1]

    if oldest == 0:
        return None

    try:
        growth = (latest - oldest) / abs(oldest)
        if math.isfinite(growth):
            return growth
    except (ValueError, ZeroDivisionError):
        pass

    return None


def calculate_yoy_revenue_growth(revenues: List[float], periods_per_year: int = 4) -> Optional[float]:
    """
    计算同比收入增长率（最新一期相比去年同期）

    Args:
        revenues: 收入列表，按时间顺序从新到旧排列 [最新, ..., 最旧]
        periods_per_year: 每年有多少个报告期（季度=4，月度=12，年度=1）

    Returns:
        同比增长率，如果无法计算则返回 None
    """
    if not revenues or len(revenues) < periods_per_year + 1:
        return None

    latest = revenues[0]
    yoy_period = min(periods_per_year, len(revenues) - 1)
    yoy_revenue = revenues[yoy_period]

    if latest is None or yoy_revenue is None or yoy_revenue == 0:
        return None

    try:
        growth = (latest - yoy_revenue) / abs(yoy_revenue)
        if math.isfinite(growth):
            return growth
    except (ValueError, ZeroDivisionError):
        pass

    return None


def calculate_fcf_growth(fcfs: List[float], years: Optional[int] = None) -> Optional[float]:
    """
    计算自由现金流的复合年增长率 (CAGR)

    Args:
        fcfs: 自由现金流列表，按时间顺序从新到旧排列
        years: 计算CAGR的年数，如果为None则使用全部数据

    Returns:
        CAGR 值，如果无法计算则返回 None
    """
    if not fcfs or len(fcfs) < 2:
        return None

    # FCF 可以是负数，所以只过滤 None
    valid_fcfs = [f for f in fcfs if f is not None]
    if len(valid_fcfs) < 2:
        return None

    latest = valid_fcfs[0]
    oldest = valid_fcfs[-1] if years is None else valid_fcfs[min(years, len(valid_fcfs) - 1)]

    # 如果最旧值为0或符号不同，无法计算有意义的CAGR
    if oldest == 0:
        return None

    n_years = len(valid_fcfs) - 1 if years is None else min(years, len(valid_fcfs) - 1)
    if n_years <= 0:
        return None

    try:
        # 对于可能为负数的FCF，使用简单增长率而非CAGR
        if latest * oldest < 0:  # 符号不同
            return (latest - oldest) / abs(oldest)

        cagr = (latest / oldest) ** (1 / n_years) - 1
        if math.isfinite(cagr):
            return cagr
    except (ValueError, ZeroDivisionError, OverflowError):
        pass

    return None


def get_revenue_growth_for_analysis(revenues: List[float], analysis_type: str = "cagr") -> Optional[float]:
    """
    统一接口：根据分析类型获取收入增长率

    Args:
        revenues: 收入列表，按时间顺序从新到旧排列
        analysis_type: 分析类型
            - "cagr": 复合年增长率（推荐用于长期分析）
            - "simple": 简单总增长率
            - "yoy": 同比增长率（推荐用于季度数据）

    Returns:
        对应类型的增长率
    """
    if analysis_type == "cagr":
        return calculate_revenue_growth_cagr(revenues)
    elif analysis_type == "simple":
        return calculate_simple_revenue_growth(revenues)
    elif analysis_type == "yoy":
        return calculate_yoy_revenue_growth(revenues)
    else:
        return calculate_revenue_growth_cagr(revenues)


def format_growth_for_display(growth: Optional[float], metric_name: str = "增长率") -> str:
    """
    格式化增长率用于显示

    Args:
        growth: 增长率值
        metric_name: 指标名称

    Returns:
        格式化后的字符串
    """
    if growth is None:
        return f"{metric_name}: N/A"

    if abs(growth) < 0.001:
        return f"{metric_name}: 0%"

    return f"{metric_name}: {growth:.1%}"
