import logging
import math
from typing import Any

from src.data.models import FinancialMetrics

logger = logging.getLogger(__name__)


class OutlierDetector:
    """异常值检测器

    提供多种异常值检测方法：
    1. Z-Score 方法：基于标准差
    2. IQR 方法：基于四分位距
    3. 百分位数方法：基于百分位数
    """

    @staticmethod
    def zscore_method(values: list[float], threshold: float = 3.0) -> list[int]:
        """Z-Score 方法检测异常值

        Args:
            values: 数值列表
            threshold: Z-Score 阈值，默认 3.0

        Returns:
            异常值的索引列表
        """
        if len(values) < 3:
            return []

        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        std = math.sqrt(variance)

        if std == 0:
            return []

        z_scores = [abs(x - mean) / std for x in values]
        return [i for i, z in enumerate(z_scores) if z > threshold]

    @staticmethod
    def iqr_method(values: list[float], k: float = 1.5) -> list[int]:
        """IQR 方法检测异常值

        Args:
            values: 数值列表
            k: IQR 倍数，默认 1.5

        Returns:
            异常值的索引列表
        """
        if len(values) < 4:
            return []

        sorted_values = sorted(values)
        n = len(sorted_values)
        q1_idx = n // 4
        q3_idx = (3 * n) // 4

        q1 = sorted_values[q1_idx]
        q3 = sorted_values[q3_idx]
        iqr = q3 - q1

        lower_bound = q1 - k * iqr
        upper_bound = q3 + k * iqr

        return [i for i, v in enumerate(values) if v < lower_bound or v > upper_bound]

    @staticmethod
    def percentile_method(values: list[float], lower: float = 1, upper: float = 99) -> list[int]:
        """百分位数方法检测异常值

        Args:
            values: 数值列表
            lower: 下百分位数，默认 1
            upper: 上百分位数，默认 99

        Returns:
            异常值的索引列表
        """
        if len(values) < 10:
            return []

        sorted_values = sorted(values)
        n = len(sorted_values)

        lower_idx = max(0, int(n * lower / 100))
        upper_idx = min(n - 1, int(n * upper / 100))

        lower_bound = sorted_values[lower_idx]
        upper_bound = sorted_values[upper_idx]

        return [i for i, v in enumerate(values) if v < lower_bound or v > upper_bound]


class SmartDataCleaner:
    """智能数据清洗器

    提供数据清洗功能：
    1. 单位错误自动修正
    2. 异常值检测和处理
    3. 缺失值填补
    """

    UNIT_ERROR_THRESHOLDS = {
        "return_on_equity": 2.0,
        "return_on_assets": 1.0,
        "gross_margin": 1.0,
        "operating_margin": 1.0,
        "net_margin": 1.0,
        "debt_to_equity": 10.0,
        "revenue_growth": 10.0,
        "earnings_growth": 10.0,
    }

    def __init__(self):
        self.detector = OutlierDetector()

    def clean_financial_metrics(self, metrics: list[FinancialMetrics], ticker: str = "") -> list[FinancialMetrics]:
        """清洗财务指标数据

        Args:
            metrics: 财务指标列表
            ticker: 股票代码（用于日志）

        Returns:
            清洗后的指标列表
        """
        if not metrics:
            return []

        metrics = self._fix_unit_errors(metrics, ticker)
        metrics = self._handle_outliers(metrics, ticker)

        return metrics

    def _fix_unit_errors(self, metrics: list[FinancialMetrics], ticker: str) -> list[FinancialMetrics]:
        """自动修正单位错误

        检测疑似单位错误（如百分比未除以100）并自动修正
        """
        fixed_metrics: list[FinancialMetrics] = []

        for metric in metrics:
            updates: dict[str, Any] = {}

            for field, threshold in self.UNIT_ERROR_THRESHOLDS.items():
                value = getattr(metric, field, None)
                if value is not None and abs(value) > threshold:
                    logger.warning(f"[{ticker}] {field}={value} 疑似单位错误，自动除以100")
                    updates[field] = value / 100

            if updates:
                fixed_metric = metric.model_copy(update=updates)
                fixed_metrics.append(fixed_metric)
            else:
                fixed_metrics.append(metric)

        return fixed_metrics

    def _handle_outliers(self, metrics: list[FinancialMetrics], ticker: str) -> list[FinancialMetrics]:
        """处理异常值

        使用 IQR 方法检测异常值并记录日志
        """
        roe_values = [m.return_on_equity for m in metrics if m.return_on_equity is not None]

        if len(roe_values) >= 4:
            outlier_indices = self.detector.iqr_method(roe_values)
            if outlier_indices:
                logger.warning(f"[{ticker}] 检测到 {len(outlier_indices)} 个 ROE 异常值")

        return metrics

    def clean_dict_metrics(self, metrics: list[dict[str, Any]], ticker: str = "") -> list[dict[str, Any]]:
        """清洗字典格式的财务指标

        Args:
            metrics: 字典格式的指标列表
            ticker: 股票代码

        Returns:
            清洗后的指标列表
        """
        if not metrics:
            return []

        fixed_metrics: list[dict[str, Any]] = []

        for metric in metrics:
            fixed = metric.copy()

            for field, threshold in self.UNIT_ERROR_THRESHOLDS.items():
                value = metric.get(field)
                if value is not None and abs(float(value)) > threshold:
                    logger.warning(f"[{ticker}] {field}={value} 疑似单位错误，自动除以100")
                    fixed[field] = float(value) / 100

            fixed_metrics.append(fixed)

        return fixed_metrics


def clean_financial_metrics(metrics: list[FinancialMetrics], ticker: str = "") -> list[FinancialMetrics]:
    """清洗财务指标的便捷函数

    Args:
        metrics: 财务指标列表
        ticker: 股票代码

    Returns:
        清洗后的指标列表
    """
    cleaner = SmartDataCleaner()
    return cleaner.clean_financial_metrics(metrics, ticker)
