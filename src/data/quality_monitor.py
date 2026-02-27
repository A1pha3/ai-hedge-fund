import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DataQualityMetrics:
    """数据质量指标"""

    timestamp: datetime
    ticker: str
    source: str
    total_records: int
    valid_records: int
    missing_fields: dict[str, int]
    outlier_count: int
    unit_error_count: int
    validation_errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["timestamp"] = self.timestamp.isoformat()
        return result

    @property
    def quality_score(self) -> float:
        """计算质量分数"""
        if self.total_records == 0:
            return 0.0
        return self.valid_records / self.total_records


class DataQualityMonitor:
    """数据质量监控器

    功能：
    1. 记录质量检查结果
    2. 生成每日质量报告
    3. 触发质量告警
    """

    def __init__(self, storage_path: str = "data/quality_reports"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.metrics_history: list[DataQualityMetrics] = []

    def record_quality_check(self, metrics: DataQualityMetrics) -> None:
        """记录质量检查结果

        Args:
            metrics: 质量指标
        """
        self.metrics_history.append(metrics)
        self._save_metrics(metrics)

        if metrics.quality_score < 0.8:
            self._send_alert(metrics)

    def generate_daily_report(self) -> dict[str, Any]:
        """生成每日数据质量报告

        Returns:
            报告字典
        """
        today = datetime.now().date()
        today_metrics = [m for m in self.metrics_history if m.timestamp.date() == today]

        if not today_metrics:
            return {"message": "今日无数据", "date": str(today)}

        total_checks = len(today_metrics)
        avg_quality = sum(m.quality_score for m in today_metrics) / total_checks

        problematic_tickers = [m.ticker for m in today_metrics if m.quality_score < 0.8]

        return {
            "date": str(today),
            "total_checks": total_checks,
            "average_quality": f"{avg_quality:.2%}",
            "problematic_tickers": problematic_tickers,
            "common_issues": self._analyze_common_issues(today_metrics),
        }

    def get_quality_trend(self, days: int = 7) -> list[dict[str, Any]]:
        """获取质量趋势

        Args:
            days: 天数

        Returns:
            每日质量分数列表
        """
        trend = []
        today = datetime.now().date()

        for i in range(days):
            date = today - __import__("datetime").timedelta(days=i)
            day_metrics = [m for m in self.metrics_history if m.timestamp.date() == date]

            if day_metrics:
                avg_quality = sum(m.quality_score for m in day_metrics) / len(day_metrics)
                trend.append(
                    {
                        "date": str(date),
                        "quality_score": round(avg_quality, 4),
                        "total_checks": len(day_metrics),
                    }
                )

        return trend

    def _save_metrics(self, metrics: DataQualityMetrics) -> None:
        """保存指标到文件"""
        filename = self.storage_path / f"{metrics.timestamp.strftime('%Y%m%d')}.jsonl"

        try:
            with open(filename, "a", encoding="utf-8") as f:
                f.write(json.dumps(metrics.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"保存质量指标失败: {e}")

    def _send_alert(self, metrics: DataQualityMetrics) -> None:
        """发送质量告警"""
        logger.error(f"数据质量告警: {metrics.ticker} " f"质量分数 {metrics.quality_score:.2%}, " f"来源: {metrics.source}")

    def _analyze_common_issues(self, metrics_list: list[DataQualityMetrics]) -> dict[str, int]:
        """分析常见问题"""
        issues: dict[str, int] = {}

        for metrics in metrics_list:
            for error in metrics.validation_errors:
                issue_type = error.split(":")[0] if ":" in error else error
                issues[issue_type] = issues.get(issue_type, 0) + 1

        return dict(sorted(issues.items(), key=lambda x: x[1], reverse=True)[:10])


def create_quality_metrics(
    ticker: str,
    source: str,
    total_records: int,
    valid_records: int,
    validation_errors: list[str] | None = None,
    missing_fields: dict[str, int] | None = None,
    outlier_count: int = 0,
    unit_error_count: int = 0,
) -> DataQualityMetrics:
    """创建质量指标的便捷函数"""
    return DataQualityMetrics(
        timestamp=datetime.now(),
        ticker=ticker,
        source=source,
        total_records=total_records,
        valid_records=valid_records,
        missing_fields=missing_fields or {},
        outlier_count=outlier_count,
        unit_error_count=unit_error_count,
        validation_errors=validation_errors or [],
    )
