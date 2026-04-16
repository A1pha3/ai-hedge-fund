"""
数据验证和清洗模块

实现数据质量检查、验证规则、清洗逻辑
"""

import logging
from typing import Any, Optional
from collections.abc import Callable

from src.data.models import CompanyNews, FinancialMetrics, Price
from src.data.validator_metric_helpers import collect_metric_warning_messages, validate_metric_required_fields
from src.data.validator_helpers import validate_price_row

logger = logging.getLogger(__name__)


class DataValidator:
    """
    数据验证器

    提供数据质量检查和验证功能
    """

    @staticmethod
    def _get_attr(obj: Any, attr: str, default: Any = None) -> Any:
        """
        获取对象属性（支持字典和模型对象）

        Args:
            obj: 对象
            attr: 属性名
            default: 默认值

        Returns:
            属性值
        """
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    @staticmethod
    def validate_prices(prices: list[Price | dict]) -> list[Price | dict]:
        """
        验证价格数据

        检查项：
        - 价格是否为正数
        - 最高价 >= 开盘价、收盘价 >= 最低价
        - 成交量是否为正数
        - 日期格式是否正确

        Args:
            prices: 价格数据列表（可以是 Price 对象或字典）

        Returns:
            验证通过的数据列表

        Raises:
            ValidationError: 验证失败
        """
        if not prices:
            return []

        valid_prices = []
        errors = []

        for i, price in enumerate(prices):
            try:
                get_attr = DataValidator._get_attr
                is_valid, error = validate_price_row(price, i, get_attr)
                if not is_valid:
                    errors.append(str(error))
                    continue
                valid_prices.append(price)

            except Exception as e:
                errors.append(f"Price[{i}]: validation error - {e}")

        if errors:
            logger.warning(f"Price validation errors: {errors}")

        return valid_prices

    @staticmethod
    def validate_financial_metrics(metrics: list[FinancialMetrics | dict]) -> list[FinancialMetrics | dict]:
        """
        验证财务指标数据

        检查项：
        - 必需字段是否存在
        - 数值是否在合理范围内
        - 比率是否大于 0

        Args:
            metrics: 财务指标列表（可以是 FinancialMetrics 对象或字典）

        Returns:
            验证通过的数据列表
        """
        if not metrics:
            return []

        valid_metrics = []
        errors = []
        get_attr = DataValidator._get_attr

        for i, metric in enumerate(metrics):
            try:
                is_valid, error = validate_metric_required_fields(metric, i, get_attr)
                if not is_valid:
                    errors.append(str(error))
                    continue

                for warning in collect_metric_warning_messages(metric, i, get_attr):
                    logger.warning(warning)
                valid_metrics.append(metric)

            except Exception as e:
                errors.append(f"Metric[{i}]: validation error - {e}")

        if errors:
            logger.warning(f"Financial metrics validation errors: {errors}")

        return valid_metrics

    @staticmethod
    def validate_news(news_list: list[CompanyNews | dict]) -> list[CompanyNews | dict]:
        """
        验证新闻数据

        检查项：
        - 标题和内容是否存在
        - 日期格式是否正确

        Args:
            news_list: 新闻列表（可以是 CompanyNews 对象或字典）

        Returns:
            验证通过的数据列表
        """
        if not news_list:
            return []

        valid_news = []
        errors = []
        get_attr = DataValidator._get_attr

        for i, news in enumerate(news_list):
            try:
                # 检查必需字段
                ticker = get_attr(news, "ticker")
                if not ticker:
                    errors.append(f"News[{i}]: missing ticker")
                    continue

                title = get_attr(news, "title")
                if not title:
                    errors.append(f"News[{i}]: missing title")
                    continue

                date = get_attr(news, "date")
                if not date:
                    errors.append(f"News[{i}]: missing date")
                    continue

                valid_news.append(news)

            except Exception as e:
                errors.append(f"News[{i}]: validation error - {e}")

        if errors:
            logger.warning(f"News validation errors: {errors}")

        return valid_news


class DataCleaner:
    """
    数据清洗器

    提供数据清洗和标准化功能
    """

    @staticmethod
    def _get_key(obj: Any, key: str, default: Any = None) -> Any:
        """
        获取对象键值（支持字典和模型对象）

        Args:
            obj: 对象
            key: 键名
            default: 默认值

        Returns:
            键值
        """
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    @staticmethod
    def clean_prices(prices: list[Price | dict]) -> list[Price | dict]:
        """
        清洗价格数据

        清洗操作：
        - 去重（按日期）
        - 排序（按日期）
        - 填充缺失值
        - 平滑异常值

        Args:
            prices: 价格数据列表

        Returns:
            清洗后的数据列表
        """
        if not prices:
            return []

        get_key = DataCleaner._get_key

        # 去重（保留最新）
        seen_dates = {}
        for price in prices:
            date_key = get_key(price, "time")
            if date_key:
                seen_dates[date_key] = price

        unique_prices = list(seen_dates.values())

        # 按日期排序
        unique_prices.sort(key=lambda p: get_key(p, "time", ""))

        return unique_prices

    @staticmethod
    def clean_financial_metrics(metrics: list[FinancialMetrics | dict]) -> list[FinancialMetrics | dict]:
        """
        清洗财务指标数据

        清洗操作：
        - 去重（按报告期）
        - 排序（按报告期降序）
        - 处理异常值

        Args:
            metrics: 财务指标列表

        Returns:
            清洗后的数据列表
        """
        if not metrics:
            return []

        get_key = DataCleaner._get_key

        # 去重（按报告期）
        seen_periods = {}
        for metric in metrics:
            period_key = get_key(metric, "report_period")
            if period_key:
                seen_periods[period_key] = metric

        unique_metrics = list(seen_periods.values())

        # 按报告期降序排序
        unique_metrics.sort(key=lambda m: get_key(m, "report_period", ""), reverse=True)

        return unique_metrics

    @staticmethod
    def clean_news(news_list: list[CompanyNews | dict]) -> list[CompanyNews | dict]:
        """
        清洗新闻数据

        清洗操作：
        - 去重（按标题）
        - 排序（按日期降序）
        - 过滤空内容

        Args:
            news_list: 新闻列表

        Returns:
            清洗后的数据列表
        """
        if not news_list:
            return []

        get_key = DataCleaner._get_key

        # 去重（按标题）
        seen_titles = {}
        for news in news_list:
            title_key = str(get_key(news, "title", "")).strip().lower()
            if title_key and title_key not in seen_titles:
                seen_titles[title_key] = news

        unique_news = list(seen_titles.values())

        # 按日期降序排序
        unique_news.sort(key=lambda n: get_key(n, "date", ""), reverse=True)

        return unique_news


class DataPipeline:
    """
    数据处理管道

    组合验证和清洗步骤
    """

    def __init__(self, validators: Optional[list[Callable]] = None, cleaners: Optional[list[Callable]] = None):
        """
        初始化数据管道

        Args:
            validators: 验证器列表
            cleaners: 清洗器列表
        """
        self.validators = validators or []
        self.cleaners = cleaners or []

    def process(self, data: Any, data_type: str) -> Any:
        """
        处理数据

        Args:
            data: 原始数据
            data_type: 数据类型（prices/metrics/news）

        Returns:
            处理后的数据
        """
        # 验证
        if data_type == "prices":
            data = DataValidator.validate_prices(data)
            data = DataCleaner.clean_prices(data)
        elif data_type == "metrics":
            data = DataValidator.validate_financial_metrics(data)
            data = DataCleaner.clean_financial_metrics(data)
        elif data_type == "news":
            data = DataValidator.validate_news(data)
            data = DataCleaner.clean_news(data)

        return data


# 默认管道实例
default_pipeline = DataPipeline()
