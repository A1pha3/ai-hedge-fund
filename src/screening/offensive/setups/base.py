"""Setup 抽象基类 — 所有凸性 setup 的统一接口。

v2 §C.6 关键: 每个 setup 必须返回 invalidation_condition (失效条件),
供 risk_framework 用作止损/退出依据。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DetectionResult:
    """Setup 检测结果。"""

    hit: bool
    ticker: str
    trade_date: str  # YYYYMMDD
    trigger_strength: float  # 0-1, 触发强度 (用于 IC 排序)
    invalidation_condition: str  # 失效条件描述 (trigger 反转判定)
    metadata: dict[str, Any] = field(default_factory=dict)


class Setup(ABC):
    """凸性 setup 抽象基类。子类实现 detect + 声明 natural_horizon。"""

    name: str = "abstract"
    natural_horizon: int = 5  # IC 最高的 horizon (子类覆盖)

    @abstractmethod
    def detect(self, ticker: str, trade_date: str, context: dict[str, Any]) -> DetectionResult:
        """检测 ticker 在 trade_date 是否命中本 setup。

        Args:
            ticker: 6 位代码
            trade_date: YYYYMMDD
            context: 共享上下文 (价格数据 / 资金流 / 行业信息 / regime)

        Returns:
            DetectionResult; hit=False 时其余字段填默认值
        """
        ...
