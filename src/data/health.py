"""
数据源健康监控与自动降级模块

提供滑动窗口的成功率统计、延迟追踪和自动降级/恢复逻辑。
被 DataRouter 在每次请求后调用以记录结果，并在选择 provider 时
参考健康状态自动跳过已降级的数据源。

设计约束：
  - 使用 collections.deque 存储最近 N 次请求，内存不会无限增长
  - 降级阈值可通过环境变量或构造参数配置（默认 70%）
  - 线程安全（单线程 async 事件循环，无需加锁）
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

_DEFAULT_WINDOW_SIZE = int(os.environ.get("HEALTH_TRACKER_WINDOW_SIZE", "50"))
_DEFAULT_DEGRADE_THRESHOLD = float(os.environ.get("HEALTH_DEGRADE_THRESHOLD", "0.70"))
_DEFAULT_RECOVER_THRESHOLD = float(os.environ.get("HEALTH_RECOVER_THRESHOLD", "0.80"))


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


class SourceStatus(str, Enum):
    """数据源健康状态"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RequestRecord:
    """单次请求的简要记录（值对象）"""

    success: bool
    latency_ms: float
    timestamp: float = field(default_factory=time.time)
    error: str | None = None


@dataclass
class DataSourceHealth:
    """数据源健康状态快照

    用于对外暴露（API、CLI），不包含内部实现细节。
    """

    provider: str
    status: SourceStatus
    success_rate: float  # 0.0 ~ 1.0
    avg_latency_ms: float
    total_requests: int
    success_count: int
    last_check: str  # ISO 格式
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status.value,
            "success_rate": round(self.success_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "total_requests": self.total_requests,
            "success_count": self.success_count,
            "last_check": self.last_check,
            "last_error": self.last_error,
        }


# ---------------------------------------------------------------------------
# HealthTracker
# ---------------------------------------------------------------------------


class HealthTracker:
    """单 provider 的滑动窗口健康追踪器

    记录最近 *window_size* 次请求结果，计算成功率和平均延迟。
    当成功率低于 *degrade_threshold* 时标记为 DEGRADED，
    当成功率恢复到 *recover_threshold* 以上时恢复为 HEALTHY。

    Recover threshold 应高于 degrade threshold（滞后机制），防止
    边界值附近频繁切换。
    """

    def __init__(
        self,
        provider_name: str,
        window_size: int = _DEFAULT_WINDOW_SIZE,
        degrade_threshold: float = _DEFAULT_DEGRADE_THRESHOLD,
        recover_threshold: float = _DEFAULT_RECOVER_THRESHOLD,
    ) -> None:
        if not 0.0 < degrade_threshold <= 1.0:
            raise ValueError(f"degrade_threshold must be in (0, 1], got {degrade_threshold}")
        if not 0.0 < recover_threshold <= 1.0:
            raise ValueError(f"recover_threshold must be in (0, 1], got {recover_threshold}")
        if recover_threshold < degrade_threshold:
            raise ValueError(f"recover_threshold ({recover_threshold}) must be >= degrade_threshold ({degrade_threshold})")

        self.provider_name = provider_name
        self.window_size = window_size
        self.degrade_threshold = degrade_threshold
        self.recover_threshold = recover_threshold

        self._records: deque[RequestRecord] = deque(maxlen=window_size)
        self._status: SourceStatus = SourceStatus.UNKNOWN

    # ---- recording --------------------------------------------------------

    def record_success(self, latency_ms: float) -> None:
        """记录一次成功请求"""
        self._records.append(RequestRecord(success=True, latency_ms=latency_ms))
        self._update_status()

    def record_failure(self, latency_ms: float, error: str | None = None) -> None:
        """记录一次失败请求"""
        self._records.append(RequestRecord(success=False, latency_ms=latency_ms, error=error))
        self._update_status()

    # ---- status computation -----------------------------------------------

    def _compute_stats(self) -> tuple[float, float, int, int, str | None]:
        """从滑动窗口计算 (success_rate, avg_latency, total, successes, last_error)

        无数据时返回 (0.0, 0.0, 0, 0, None)。
        """
        if not self._records:
            return 0.0, 0.0, 0, 0, None

        total = len(self._records)
        successes = sum(1 for r in self._records if r.success)
        success_rate = successes / total
        avg_latency = sum(r.latency_ms for r in self._records) / total

        last_error: str | None = None
        for rec in reversed(self._records):
            if rec.error:
                last_error = rec.error
                break

        return success_rate, avg_latency, total, successes, last_error

    def _update_status(self) -> None:
        """根据当前统计数据更新状态（含滞后逻辑）

        状态机:
          UNKNOWN ──[有数据且 rate >= degrade]──> HEALTHY
          UNKNOWN ──[有数据且 rate < degrade]───> DEGRADED
          HEALTHY ──[rate < degrade]────────────> DEGRADED
          DEGRADED ──[rate >= recover]──────────> HEALTHY
        """
        if not self._records:
            self._status = SourceStatus.UNKNOWN
            return

        success_rate = sum(1 for r in self._records if r.success) / len(self._records)
        old_status = self._status

        if self._status == SourceStatus.DEGRADED:
            # 恢复需要更高的成功率（滞后）
            if success_rate >= self.recover_threshold:
                self._status = SourceStatus.HEALTHY
                logger.info(
                    "HealthTracker [%s] recovered: success_rate=%.2f%% >= recover_threshold=%.2f%%",
                    self.provider_name,
                    success_rate * 100,
                    self.recover_threshold * 100,
                )
        else:
            # HEALTHY 或 UNKNOWN
            if success_rate < self.degrade_threshold:
                self._status = SourceStatus.DEGRADED
                logger.warning(
                    "HealthTracker [%s] DEGRADED: success_rate=%.2f%% < degrade_threshold=%.2f%%",
                    self.provider_name,
                    success_rate * 100,
                    self.degrade_threshold * 100,
                )
            else:
                # 成功率达标，设为 HEALTHY（也处理 UNKNOWN -> HEALTHY）
                self._status = SourceStatus.HEALTHY

        if old_status != self._status:
            logger.info(
                "HealthTracker [%s] status transition: %s -> %s",
                self.provider_name,
                old_status.value,
                self._status.value,
            )

    # ---- query ------------------------------------------------------------

    @property
    def status(self) -> SourceStatus:
        return self._status

    @property
    def is_healthy(self) -> bool:
        return self._status != SourceStatus.DEGRADED

    def get_health(self) -> DataSourceHealth:
        """获取当前健康状态快照"""
        success_rate, avg_latency, total, successes, last_error = self._compute_stats()
        return DataSourceHealth(
            provider=self.provider_name,
            status=self._status,
            success_rate=success_rate,
            avg_latency_ms=avg_latency,
            total_requests=total,
            success_count=successes,
            last_check=datetime.now().isoformat(),
            last_error=last_error,
        )


# ---------------------------------------------------------------------------
# 全局 HealthMonitor — 管理所有 provider 的 tracker
# ---------------------------------------------------------------------------


class HealthMonitor:
    """全局健康监控器

    为每个 provider 名称维护一个 HealthTracker 实例。
    DataRouter 在每次请求后调用 record() 方法，路由时通过
    get_healthy_providers() 获取未降级的 provider 列表。
    """

    def __init__(
        self,
        window_size: int = _DEFAULT_WINDOW_SIZE,
        degrade_threshold: float = _DEFAULT_DEGRADE_THRESHOLD,
        recover_threshold: float = _DEFAULT_RECOVER_THRESHOLD,
    ) -> None:
        self.window_size = window_size
        self.degrade_threshold = degrade_threshold
        self.recover_threshold = recover_threshold
        self._trackers: dict[str, HealthTracker] = {}

    def _ensure_tracker(self, provider_name: str) -> HealthTracker:
        if provider_name not in self._trackers:
            self._trackers[provider_name] = HealthTracker(
                provider_name=provider_name,
                window_size=self.window_size,
                degrade_threshold=self.degrade_threshold,
                recover_threshold=self.recover_threshold,
            )
        return self._trackers[provider_name]

    # ---- recording --------------------------------------------------------

    def record_success(self, provider_name: str, latency_ms: float) -> None:
        self._ensure_tracker(provider_name).record_success(latency_ms)

    def record_failure(self, provider_name: str, latency_ms: float, error: str | None = None) -> None:
        self._ensure_tracker(provider_name).record_failure(latency_ms, error)

    def record(self, provider_name: str, success: bool, latency_ms: float, error: str | None = None) -> None:
        """便捷方法：根据 success 标志自动路由到 record_success / record_failure"""
        if success:
            self.record_success(provider_name, latency_ms)
        else:
            self.record_failure(provider_name, latency_ms, error)

    # ---- query ------------------------------------------------------------

    def is_healthy(self, provider_name: str) -> bool:
        tracker = self._trackers.get(provider_name)
        if tracker is None:
            return True  # 无历史数据时默认健康
        return tracker.is_healthy

    def get_healthy_providers(self, provider_names: list[str]) -> list[str]:
        """返回未降级的 provider 名称列表，保持原始顺序"""
        return [name for name in provider_names if self.is_healthy(name)]

    def get_health(self, provider_name: str) -> DataSourceHealth | None:
        tracker = self._trackers.get(provider_name)
        if tracker is None:
            return None
        return tracker.get_health()

    def get_all_health(self) -> dict[str, DataSourceHealth]:
        """获取所有已追踪 provider 的健康状态"""
        return {name: tracker.get_health() for name, tracker in self._trackers.items()}


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_monitor: HealthMonitor | None = None


def get_health_monitor() -> HealthMonitor:
    """获取全局 HealthMonitor 单例"""
    global _monitor
    if _monitor is None:
        _monitor = HealthMonitor()
    return _monitor


def reset_health_monitor() -> None:
    """重置全局 HealthMonitor（用于测试）"""
    global _monitor
    _monitor = None
