"""Plan 06 Task 3: live-order adoption 证明.

v2 schema 不存在可表示的 live/ambiguous/cancel-pending order — 任何此类行在
盘点阶段即构成不可归因风险并阻断. adoption 因此是一份 *空证明*: 绑定 source
root, 声明没有任何需要接管的订单, 且永不重提交.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from src.screening.offensive.v3.contracts import (
    CanonicalModel,
    UtcInstant,
    domain_hash,
)

from src.screening.offensive.v3.migration.inventory import V2Inventory

ADOPTION_BLOCKED = "ADOPTION_BLOCKED"

_DOMAIN = "ai-hedge-fund.v3.migration.order-adoption.v1"


class AdoptionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class OrderAdoptionManifest(CanonicalModel):
    """空 adoption 证明: 绑定 source root, 不含任何可提交指令."""

    source_root: str
    adoptions: tuple[Mapping[str, Any], ...]
    adopted_at: UtcInstant
    never_resubmits: bool = True

    @property
    def manifest_hash(self) -> str:
        return domain_hash(
            _DOMAIN,
            2,
            {
                "source_root": self.source_root,
                "adoptions": list(self.adoptions),
                "adopted_at": self.adopted_at,
                "never_resubmits": self.never_resubmits,
            },
        )


def adopt_live_orders(
    inventory: V2Inventory, *, adopted_at: datetime
) -> OrderAdoptionManifest:
    """从盘点产出 adoption 证明; 盘点含订单行即阻断."""

    if inventory.orders:
        raise AdoptionError(
            ADOPTION_BLOCKED,
            f"unattributed order rows require manual adoption review: "
            f"{[row.order_id for row in inventory.orders]}",
        )
    return OrderAdoptionManifest(
        source_root=inventory.source_root,
        adoptions=(),
        adopted_at=adopted_at,
    )
