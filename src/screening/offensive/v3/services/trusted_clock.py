"""Task 1: 可信时钟 — 单调序列 + wall time, 检测 rollback/skew, 门控时间敏感 entry。

unhealthy/rollback 必须 block 时间敏感 entry(seal/execution);
exit/reconcile 保持可调用: observe() 永不抛错, 只记录健康状态。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Callable, Final

from src.screening.offensive.v3.contracts import ClockHealth, TrustedClockObservation
from src.screening.offensive.v3.contracts.base import canonical_json_bytes

DEFAULT_MAX_SKEW: Final[timedelta] = timedelta(minutes=5)
DEFAULT_CLOCK_SOURCE: Final[str] = "monotonic_ns+wall_utc"


class TrustedClock:
    """包装单调时钟与 UTC wall clock, 产出 TrustedClockObservation。"""

    def __init__(
        self,
        *,
        wall_clock: Callable[[], datetime],
        monotonic_ns: Callable[[], int],
        max_skew: timedelta = DEFAULT_MAX_SKEW,
        source: str = DEFAULT_CLOCK_SOURCE,
    ) -> None:
        self._wall_clock = wall_clock
        self._monotonic_ns = monotonic_ns
        self._max_skew = max_skew
        self._source = source
        self._sequence: int = 0
        self._last_wall: datetime | None = None
        self._last_mono: int | None = None
        self._last_health: ClockHealth | None = None

    @property
    def source(self) -> str:
        """时钟来源描述(观察本身不含来源字段, 由时钟实例声明)。"""
        return self._source

    def observe(self) -> TrustedClockObservation:
        """读取一次时钟, 返回不可变观察; 永不抛错(exit/reconcile 保持可调用)。

        健康判定: 与上一次观察比较 wall/mono 增量。
        - wall 后退 -> ROLLBACK_DETECTED
        - wall 增量与 mono 增量偏差超 max_skew -> EXCESSIVE_SKEW
        - 其余 -> HEALTHY(首条观察恒为 HEALTHY)
        无 latch: 每条观察独立判定, 后续一致增量即恢复 HEALTHY。
        """
        wall = self._wall_clock()
        mono = self._monotonic_ns()
        self._sequence += 1
        health = self._classify(wall, mono)
        self._last_wall = wall
        self._last_mono = mono
        self._last_health = health
        return TrustedClockObservation(
            observation_id=f"clock-{uuid.uuid4().hex}",
            raw_payload_hash=self._raw_payload_hash(wall, mono),
            wall_clock_utc=wall,
            monotonic_observation_ns=mono,
            monotonic_sequence=self._sequence,
            clock_health=health,
        )

    def health(self) -> ClockHealth:
        """最近一次观察的健康状态; 无观察时为 UNKNOWN。"""
        if self._last_health is None:
            return ClockHealth.UNKNOWN
        return self._last_health

    @property
    def is_healthy(self) -> bool:
        """health() 为 HEALTHY 时为 True。"""
        return self.health() is ClockHealth.HEALTHY

    def allows_time_sensitive(self) -> bool:
        """时间敏感 entry 门控: 仅 HEALTHY 放行, 其余 fail-closed。"""
        return self.health() is ClockHealth.HEALTHY

    # ------------------------------------------------------------------

    def _classify(self, wall: datetime, mono: int) -> ClockHealth:
        if self._last_wall is None or self._last_mono is None:
            return ClockHealth.HEALTHY
        wall_delta = wall - self._last_wall
        mono_delta = mono - self._last_mono
        if wall_delta < timedelta(0):
            return ClockHealth.ROLLBACK_DETECTED
        # mono_delta 为负说明单调时钟本身倒卷, 同样视为 rollback。
        if mono_delta < 0:
            return ClockHealth.ROLLBACK_DETECTED
        wall_skew = abs(wall_delta - timedelta(microseconds=mono_delta // 1000))
        if wall_skew > self._max_skew:
            return ClockHealth.EXCESSIVE_SKEW
        return ClockHealth.HEALTHY

    @staticmethod
    def _raw_payload_hash(wall: datetime, mono: int) -> str:
        """sha256 仅 (wall, mono): 规范 JSON 保证不同实例相同输入相同输出。"""
        import hashlib

        payload = canonical_json_bytes((wall.isoformat(), mono))
        return hashlib.sha256(payload).hexdigest()
