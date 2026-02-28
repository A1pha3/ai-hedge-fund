"""
财务计算工具模块 - 提供统一的财务指标计算方法

此模块确保所有分析师使用一致的计算逻辑，避免数据不一致问题。

注意：A股季度财报使用 YTD（年初至今）累计格式，例如：
  - 20250930: 前9个月累计收入
  - 20250630: 前6个月累计收入
  - 20250331: 仅Q1收入
  不同季度的 YTD 值不可直接比较用于 CAGR 计算。
  使用 calculate_cagr_from_line_items() 正确处理A股数据。
"""

import math
from typing import Any, List, Optional


def _compute_cagr(latest: float, oldest: float, n_years: int) -> Optional[float]:
    """内部辅助函数：计算 CAGR 值"""
    if oldest <= 0 or n_years <= 0:
        return None
    try:
        cagr = (latest / oldest) ** (1 / n_years) - 1
        if math.isfinite(cagr):
            return cagr
    except (ValueError, ZeroDivisionError, OverflowError):
        pass
    return None


def calculate_cagr_from_line_items(line_items: list, field: str = "revenue", years: Optional[int] = None) -> Optional[float]:
    """
    从 LineItem 列表中正确计算 CAGR，处理A股季度 YTD 累计数据。

    策略优先级：
    1. 仅使用年度数据（report_period 以 "1231" 结尾）
    2. 使用同季度 YoY 数据（如 Q3 2025 vs Q3 2024）
    3. 回退到原始 CAGR 计算（兜底）

    Args:
        line_items: LineItem 对象列表，按时间从新到旧排列
        field: 要分析的字段名（如 "revenue", "net_income"）
        years: 计算CAGR的年数，如果为None则使用全部数据

    Returns:
        CAGR 值，如果无法计算则返回 None
    """
    # 提取 (值, report_period) 对
    pairs = []
    for item in line_items:
        val = getattr(item, field, None)
        period = getattr(item, "report_period", "") or ""
        if val is not None and val > 0 and len(period) >= 8:
            pairs.append((val, period))

    if len(pairs) < 2:
        return None

    # 策略1：仅使用年度数据（report_period以"1231"结尾）— 最准确
    annual = [(r, p) for r, p in pairs if p[4:8] == "1231"]
    if len(annual) >= 2:
        n = min(years, len(annual) - 1) if years else len(annual) - 1
        return _compute_cagr(annual[0][0], annual[min(n, len(annual) - 1)][0], n)

    # 策略2：同季度 YoY 比较（如 Q3 2025 vs Q3 2024）— 可比性好
    latest_quarter = pairs[0][1][4:8]  # e.g. "0930"
    same_q = [(r, p) for r, p in pairs if p[4:8] == latest_quarter]
    if len(same_q) >= 2:
        n = min(years, len(same_q) - 1) if years else len(same_q) - 1
        return _compute_cagr(same_q[0][0], same_q[min(n, len(same_q) - 1)][0], n)

    # 策略3：回退 - 仅有单季度数据时无法可靠计算
    return None


def calculate_revenue_growth_cagr(revenues: List[float], years: Optional[int] = None) -> Optional[float]:
    """
    计算收入增长的复合年增长率 (CAGR)

    ⚠️ 对于A股季度数据，推荐使用 calculate_cagr_from_line_items() 代替本函数。
    本函数假设每个数据点代表一年/一个可比周期，不处理 YTD 累计问题。

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

    n_years = len(valid_revenues) - 1 if years is None else min(years, len(valid_revenues) - 1)
    return _compute_cagr(latest, oldest, n_years)


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


def annualize_ytd_value(value: float, report_period: str) -> Optional[float]:
    """
    将 YTD（年初至今）累计值年化。

    A股季度财报使用 YTD 累计格式：
      - Q1 (0331): 3个月累计 → 年化 = value * 12/3
      - Q2 (0630): 6个月累计 → 年化 = value * 12/6
      - Q3 (0930): 9个月累计 → 年化 = value * 12/9
      - Q4 (1231): 12个月累计 → 已是年度值

    Args:
        value: YTD 累计值
        report_period: 报告期字符串（如 "20250930"）

    Returns:
        年化值，如果报告期格式无效则返回 None
    """
    if not report_period or len(report_period) < 8:
        return None

    month_day = report_period[4:8]
    month_map = {"0331": 3, "0630": 6, "0930": 9, "1231": 12}
    months = month_map.get(month_day)

    if months is None:
        # 尝试从月份推断
        try:
            month = int(report_period[4:6])
            if 1 <= month <= 12:
                months = month
        except (ValueError, IndexError):
            return None

    if months is None or months <= 0:
        return None

    return value * 12 / months


def calculate_pe_from_line_items(market_cap: float, line_items: list) -> Optional[float]:
    """
    从 LineItem 列表中正确计算 P/E 比率。

    对于A股数据，使用年化净利润（而非 YTD 累计值）计算 P/E。
    优先使用年度数据，其次使用最新季度的年化值。

    Args:
        market_cap: 当前市值
        line_items: LineItem 对象列表，按时间从新到旧排列

    Returns:
        P/E 比率，如果无法计算则返回 None
    """
    if not market_cap or market_cap <= 0 or not line_items:
        return None

    # 策略1：优先使用最近的年度数据
    for item in line_items:
        net_income = getattr(item, "net_income", None)
        report_period = getattr(item, "report_period", "") or ""
        if net_income and net_income > 0 and report_period.endswith("1231"):
            return market_cap / net_income

    # 策略2：使用最新季度的年化净利润
    for item in line_items:
        net_income = getattr(item, "net_income", None)
        report_period = getattr(item, "report_period", "") or ""
        if net_income and net_income > 0 and len(report_period) >= 8:
            annualized = annualize_ytd_value(net_income, report_period)
            if annualized and annualized > 0:
                return market_cap / annualized

    return None


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
