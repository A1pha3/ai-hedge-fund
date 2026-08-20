"""Stage issuance receipt → trial root archive — 特权 worker primitive (2026-08-20).

签发回执 (frozen CanonicalModel, 自验证) 落入 trial root 的
``archive/stage-issuance/<trial_id>/<stage_id>.json`` — 冷读 (无需 sqlite)、
原子写 (同目录 tmp + os.replace)、幂等 (同 content_hash 重写为 no-op)、
背离冲突、symlink/路径穿越拒绝。CLI/特权进程从此可以只凭文件系统验证
治理签发真相, 不必打开 WAL 活库。

offline primitive: 不解封任何 runner/CLI fail-closed、不构成权限。
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from pydantic import ValidationError

from src.screening.offensive.v3.governance.stage_issuance import StageIssuanceReceipt


class StageArchiveError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def stage_receipt_path(root: Path, receipt: StageIssuanceReceipt) -> Path:
    return (
        root
        / "archive"
        / "stage-issuance"
        / receipt.trial_id
        / f"{receipt.stage_id}.json"
    )


def write_stage_issuance_receipt(
    root: Path, receipt: StageIssuanceReceipt
) -> Path:
    """Write one receipt into the root archive; idempotent, conflict-divergent."""
    _validate_root(root)
    target = stage_receipt_path(root, receipt)
    target.parent.mkdir(parents=True, exist_ok=True)
    _validate_root(root)  # 新建目录组件也不得是 symlink/穿越
    try:
        mode = target.lstat().st_mode
    except FileNotFoundError:
        mode = None
    if mode is not None:
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise StageArchiveError(
                "archive_artifact_rejected",
                "the receipt artifact must be a regular non-symlink file",
                target=str(target),
            )
        try:
            existing = StageIssuanceReceipt.model_validate_json(
                target.read_text(encoding="utf-8"), strict=True
            )
        except ValidationError as exc:
            raise StageArchiveError(
                "archive_artifact_corrupt",
                "the archived receipt no longer strict-parses",
                target=str(target),
            ) from exc
        if existing.content_hash() != receipt.content_hash():
            raise StageArchiveError(
                "stage_archive_conflict",
                "this stage already archived a different receipt",
                stage_id=receipt.stage_id,
            )
        return target  # 恰等重放幂等
    tmp = target.parent / f".{receipt.stage_id}.json.tmp"
    with open(tmp, "wb") as handle:
        handle.write(receipt.model_dump_json().encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, target)
    return target


def read_stage_issuance_receipt(path: Path) -> StageIssuanceReceipt:
    """Cold read face: strict parse + regular-file/symlink guard."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise StageArchiveError(
            "archive_artifact_missing", "no archived receipt at path", path=str(path)
        ) from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise StageArchiveError(
            "archive_artifact_rejected",
            "the receipt artifact must be a regular non-symlink file",
            path=str(path),
        )
    return StageIssuanceReceipt.model_validate_json(
        path.read_text(encoding="utf-8"), strict=True
    )


def _validate_root(root: Path) -> None:
    """Canonical absolute root, no '..' segment, no symlinked component (lstat walk)."""
    if ".." in root.parts:
        raise StageArchiveError(
            "root_path_traversal",
            "a trial root must not contain a '..' path segment",
            root=str(root),
        )
    if not root.is_absolute():
        raise StageArchiveError(
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
            raise StageArchiveError(
                "root_not_found",
                "a trial root must be an existing directory",
                root=str(root),
            ) from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise StageArchiveError(
                "root_symlink_rejected",
                "a trial root must have no symlinked path component",
                component=str(current),
            )


__all__ = [
    "StageArchiveError",
    "read_stage_issuance_receipt",
    "stage_receipt_path",
    "write_stage_issuance_receipt",
]
