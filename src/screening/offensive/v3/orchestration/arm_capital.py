"""Two-arm PIT capital checkpoint 读取原语 — 特权 worker primitive (2026-08-21).

Phase B: 两臂必须从各自已分化的 CapitalTruth 取得独立 PIT capital
snapshot (AGENTS 能力边界点名的历史缺口)。本模块提供:

- ``read_genesis_manifest``: trial root 冷读 ``<trial_id>/genesis-manifest.json``
  (lstat 守卫 + 严格解析 + 损坏/缺失/symlink 类型化拒绝 — 镜像 stage_archive
  纪律), genesis 绑定字段的唯一权威来源;
- ``arm_capital_checkpoint``: 从**该臂运行态台账**的
  ``capital_risk_snapshot(as_of)`` (PIT 投影, quiet 读) 构造
  ``ShadowCapitalCheckpoint`` — 臂台账路径由调用方提供 (运行态两臂台账
  的存放约定属 worker 编排, 本原语不发明路径), genesis 绑定字段
  (manifest hash / arm backup root) 从 manifest 派生, 调用方零供给。

offline primitive: 纯读原语, 不解锁 runner fail-closed、不构成权限;
as_of 的 PIT 深语义由资本套件背书 (本层只做绑定)。
"""

from __future__ import annotations

import stat
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from src.screening.offensive.v3.contracts import ExecutionMode
from src.screening.offensive.v3.contracts.trial import TrialArm
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.kernel.models import ShadowCapitalCheckpoint
from src.screening.offensive.v3.orchestration.genesis import TrialGenesisManifest


class ArmCapitalError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def _validate_root(root: Path) -> None:
    """Canonical absolute root, no '..' segment, no symlinked component (lstat walk)."""
    if ".." in root.parts:
        raise ArmCapitalError(
            "root_path_traversal",
            "a trial root must not contain a '..' path segment",
            root=str(root),
        )
    if not root.is_absolute():
        raise ArmCapitalError(
            "root_not_canonical",
            "a trial root must be a canonical absolute path",
            root=str(root),
        )
    current = Path(root.anchor)
    for part in root.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError as exc:
            raise ArmCapitalError(
                "root_not_found",
                "a trial root must be an existing directory",
                root=str(root),
            ) from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ArmCapitalError(
                "root_symlink_rejected",
                "a trial root must have no symlinked path component",
                component=str(current),
            )


def genesis_manifest_path(root: Path, trial_id: str) -> Path:
    return root / trial_id / "genesis-manifest.json"


def read_genesis_manifest(root: Path, trial_id: str) -> TrialGenesisManifest:
    """Cold-read the sealed genesis manifest of one trial."""
    _validate_root(root)
    target = genesis_manifest_path(root, trial_id)
    try:
        mode = target.lstat().st_mode
    except FileNotFoundError as exc:
        raise ArmCapitalError(
            "genesis_manifest_missing",
            "no genesis manifest is archived for this trial",
            trial_id=trial_id,
        ) from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ArmCapitalError(
            "genesis_manifest_rejected",
            "the genesis manifest must be a regular non-symlink file",
            trial_id=trial_id,
        )
    try:
        manifest = TrialGenesisManifest.model_validate_json(
            target.read_text(encoding="utf-8"), strict=True
        )
    except ValidationError as exc:
        raise ArmCapitalError(
            "genesis_manifest_corrupt",
            "the archived genesis manifest failed strict revalidation",
            trial_id=trial_id,
            reason=str(exc),
        ) from exc
    if manifest.trial_id != trial_id:
        raise ArmCapitalError(
            "genesis_trial_mismatch",
            "the archived genesis manifest names another trial",
            manifest_trial_id=manifest.trial_id,
            requested=trial_id,
        )
    return manifest


def arm_capital_checkpoint(
    *,
    repository: CapitalRepository,
    trial_id: str,
    arm: TrialArm,
    portfolio_id: str,
    mode: ExecutionMode,
    as_of: datetime,
    capital_store_id: str,
    genesis_manifest: TrialGenesisManifest,
) -> ShadowCapitalCheckpoint:
    """One arm's PIT capital checkpoint from its own differentiated ledger.

    台账 → ``capital_risk_snapshot(as_of)`` (PIT 投影) → checkpoint; genesis
    绑定字段 (trial genesis manifest hash / 该臂 backup root) 从归档
    manifest 派生, 调用方零供给。checkpoint 校验器 (shadow-capital-
    checkpoint.v2) 钉死 snapshot 哈希绑定与 portfolio/mode 一致性 —
    任何漂移在构造时即失败。
    """
    snapshot = repository.capital_risk_snapshot(as_of)
    genesis_root = (
        genesis_manifest.champion_backup_root
        if arm is TrialArm.CHAMPION
        else genesis_manifest.challenger_backup_root
    )
    return ShadowCapitalCheckpoint(
        trial_id=trial_id,
        arm=arm,
        portfolio_id=portfolio_id,
        mode=mode,
        capital_store_id=capital_store_id,
        trial_genesis_manifest_hash=genesis_manifest.content_hash(),
        arm_capital_genesis_root=genesis_root,
        capital_snapshot_hash=snapshot.content_hash(),
        capital_snapshot=snapshot,
    )


__all__ = [
    "ArmCapitalError",
    "arm_capital_checkpoint",
    "genesis_manifest_path",
    "read_genesis_manifest",
]
