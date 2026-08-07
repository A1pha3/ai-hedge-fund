"""Task 1: 服务身份 — 服务名、capability namespace、owner uid/gid、socket 与 DB DSN 归属。

CLI principal 不持有签名材料或 writable DSN; require_private_access 证明
给定 key/DB 路径对 CLI principal 不可读(fail-closed)。
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from src.screening.offensive.v3.services.common import PrivateAccessError


@dataclass(frozen=True)
class ServiceIdentity:
    """一个窄服务的完整进程身份与资源归属声明。"""

    service_name: str
    capability_namespace: str
    owner_uid: int
    owner_gid: int
    socket_path: Path
    db_dsn: str

    def require_private_access(self, path: Path) -> None:
        """证明给定 key/DB 路径不被 CLI principal 可读; 否则抛 PrivateAccessError。

        A signing key or writable DSN must be readable only by the owning
        service principal: owner-only mode (no group/other bits) AND owned by
        this service. Anything readable by a different principal (group/other
        bits set, or a different owner uid) fails closed.
        """
        try:
            mode = path.stat().st_mode
            owner_uid = path.stat().st_uid
        except OSError as exc:
            raise PrivateAccessError(
                "private_path_unreadable",
                "signing key or writable DSN must exist for the owning service",
                path=str(path),
            ) from exc
        if stat.S_IMODE(mode) & (stat.S_IRGRP | stat.S_IROTH):
            raise PrivateAccessError(
                "private_path_group_or_other_readable",
                "signing key or writable DSN must be owner-only",
                path=str(path),
                mode=oct(stat.S_IMODE(mode)),
            )
        if owner_uid != self.owner_uid:
            raise PrivateAccessError(
                "private_path_not_owned_by_service",
                "signing key or writable DSN must be owned by the service principal",
                path=str(path),
                owner_uid=owner_uid,
                expected_uid=self.owner_uid,
            )

    def matches(self, principal: ServiceIdentity) -> bool:
        """服务名、capability namespace 与 owner uid/gid 全部一致才视为同一身份。"""
        return (
            self.service_name == principal.service_name
            and self.capability_namespace == principal.capability_namespace
            and self.owner_uid == principal.owner_uid
            and self.owner_gid == principal.owner_gid
        )
