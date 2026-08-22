"""两臂 PIT capital 台账运行态路径约定 — Trial 启动工程 (2026-08-22, R21).

Phase B 的 ``arm_capital_checkpoint`` 落地了"从臂台账读 PIT 快照"的原语,
但**台账与臂的对应**此前是未成文的 worker 编排约定 (checkpoint docstring
第 ③ 条: "台账与臂的对应关系是 worker 编排约定, 台账无臂标记, genesis
相同、运行态才分化")。本模块把该约定收敛为唯一权威:

    <trial_root>/arms/<challenger|champion>/capital.sqlite3

- ``arm_capital_database_path``: 约定路径 (段形状校验 + root 组件 walk,
  ``path_guards`` 单一实现 — symlink/穿越家族纪律);
- ``open_arm_capital_repository``: 按约定打开**既有**台账 — 缺库
  fail-closed (``arm_ledger_missing``), 绝不静默新建 (新建属 genesis
  restore/初始化流程, 不属读路径);
- ``arm_session_checkpoint``: worker 组合面 — genesis 冷读 → 台账打开 →
  PIT 快照 → checkpoint, 调用方零路径知识。

offline primitive: 不解锁 runner、不初始化任何台账、不构成权限。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.contracts.base import ExecutionMode
from src.screening.offensive.v3.contracts.trial import TrialArm
from src.screening.offensive.v3.orchestration.arm_capital import (
    ArmCapitalError,
    arm_capital_checkpoint,
    read_genesis_manifest,
)
from src.screening.offensive.v3.orchestration.path_guards import (
    require_safe_segment,
    walk_components,
)

ARMS_SUBDIR = "arms"
CAPITAL_DB_NAME = "capital.sqlite3"


class ArmLayoutError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def arm_capital_database_path(trial_root: Path, arm: TrialArm) -> Path:
    """约定路径 <trial_root>/arms/<arm>/capital.sqlite3 (纯计算, 段形状校验)。

    存在性/组件守卫在 ``open_arm_capital_repository`` (读路径) 执行 —
    约定函数对尚不存在的 root 也可用 (写入面初始化前需要先算路径)。
    """
    root = Path(trial_root)
    segment = str(arm.value).lower()  # TrialArm 枚举名大写, 约定目录用小写
    require_safe_segment(segment, field="arm")
    return root / ARMS_SUBDIR / segment / CAPITAL_DB_NAME


def open_arm_capital_repository(
    trial_root: Path, arm: TrialArm
) -> CapitalRepository:
    """打开该臂的运行态台账 — 缺库 fail-closed, 绝不静默新建。"""
    path = arm_capital_database_path(trial_root, arm)
    if not path.is_file():
        raise ArmLayoutError(
            "arm_ledger_missing",
            "the arm's runtime capital ledger does not exist at the agreed path"
            " (initialization belongs to genesis restore, never to reads)",
            path=str(path),
            arm=arm.value,
        )
    walk_components(
        path.parent,
        missing_code="arm_ledger_missing",
        rejected_code="arm_layout_rejected",
        fail=ArmLayoutError,
    )
    return CapitalRepository.open(path)


def arm_session_checkpoint(
    trial_root: Path,
    *,
    trial_id: str,
    arm: TrialArm,
    portfolio_id: str,
    mode: ExecutionMode,
    as_of: datetime,
    capital_store_id: str,
):
    """worker 组合面: genesis 冷读 → 台账打开 → PIT 快照 → checkpoint。"""
    manifest = read_genesis_manifest(Path(trial_root), trial_id)
    repository = open_arm_capital_repository(Path(trial_root), arm)
    return arm_capital_checkpoint(
        repository=repository,
        trial_id=trial_id,
        arm=arm,
        portfolio_id=portfolio_id,
        mode=mode,
        as_of=as_of,
        capital_store_id=capital_store_id,
        genesis_manifest=manifest,
    )


__all__ = [
    "ArmLayoutError",
    "arm_capital_database_path",
    "arm_session_checkpoint",
    "open_arm_capital_repository",
]
