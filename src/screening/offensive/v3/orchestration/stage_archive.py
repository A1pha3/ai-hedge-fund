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
from src.screening.offensive.v3.orchestration.path_guards import (
    ensure_directory_components,
    require_safe_segment,
    walk_components,
)


class StageArchiveError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def stage_receipt_path(root: Path, receipt: StageIssuanceReceipt) -> Path:
    # 拼路径前拒绝非法段: 穿越与绝对注入不允许到达 lstat (2026-08-21
    # 对抗性审查 — pathlib ``root / '/abs'`` 会整体替换 root)。
    require_safe_segment(receipt.trial_id, field="trial_id", fail=StageArchiveError)
    require_safe_segment(receipt.stage_id, field="stage_id", fail=StageArchiveError)
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
    # 逐段创建 + 逐段验证 (第五轮): 此前 ``mkdir(parents=True)`` 先于
    # walk 执行 — 预置 symlink 中间段时目录已穿出到 root 外创建, walk
    # 事后才拒绝。ensure 原语把创建本身拆成单段步进, 穿出创建不可能
    # 发生; root 下全部组件 (含新建的 archive/stage-issuance/<trial_id>)
    # 同步覆盖。
    ensure_directory_components(
        target.parent,
        fail=StageArchiveError,
        missing_code="archive_component_missing",
        rejected_code="archive_component_rejected",
    )
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
    try:
        # O_EXCL|O_NOFOLLOW (Phase A 审查 P2-2): 预置的常规文件或 symlink
        # 都会在打开前被拒绝 — 绝不跟随敌方 tmp 写穿到任意文件。
        fd = os.open(
            tmp,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
    except FileExistsError as exc:
        raise StageArchiveError(
            "archive_tmp_conflict",
            "a stale or hostile temp artifact already exists",
            target=str(tmp),
        ) from exc
    except OSError as exc:
        raise StageArchiveError(
            "archive_tmp_open_failed",
            "cannot open the receipt temp file",
            target=str(tmp),
            reason=str(exc),
        ) from exc
    with os.fdopen(fd, "wb") as handle:
        handle.write(receipt.model_dump_json().encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, target)
    return target


def read_stage_issuance_receipt(path: Path) -> StageIssuanceReceipt:
    """Cold read face: strict parse + regular-file/symlink guard."""
    # 最终文件之前的每个父组件同样不得是 symlink (2026-08-21 对抗性
    # 审查: 中间 symlink 预置可让冷读面读到 root 之外的伪造工件)。
    walk_components(
        path.parent,
        fail=StageArchiveError,
        missing_code="archive_component_missing",
        rejected_code="archive_component_rejected",
    )
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
    # 损坏 JSON 也必须类型化拒绝 (R28: 写面 78-83 与 arm_capital 116-118
    # 均有 except ValidationError 先例, 唯读面漏 — 裸 ValidationError 会
    # 穿透所有 catch StageArchiveError 的消费者)。
    try:
        return StageIssuanceReceipt.model_validate_json(
            path.read_text(encoding="utf-8"), strict=True
        )
    except ValidationError as exc:
        raise StageArchiveError(
            "archive_artifact_corrupt",
            "the receipt artifact failed strict parse",
            path=str(path),
        ) from exc


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
