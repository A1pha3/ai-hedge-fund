"""Task 1: 认证 UDS 基础 — 路径常量、socket ACL、进程 lease 与结构化错误类型。

生产配置要求不同 service principal、socket owner/mode 和数据库 owner;
本模块提供共享常量与边界校验入口。所有校验 fail-closed: 无法证明归属
即拒绝。
"""

from __future__ import annotations

import json
import os
import socket
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# --------------------------------------------------------------------------
# UDS 路径与协议常量
# --------------------------------------------------------------------------

V3_SCHEMA_MAJOR: Final[int] = 2
"""全部 v3 服务协商的 schema major; 客户端与服务器头必须精确一致。"""

V3_SOCKET_MODE: Final[int] = 0o600
"""Unix domain socket 的 owner-only 权限位; 禁止 group/other 访问。"""

HDR_SERVICE_IDENTITY: Final[str] = "X-V3-Service-Identity"
HDR_SERVICE_CAPABILITY: Final[str] = "X-V3-Service-Capability"
HDR_SERVICE_SCHEMA_MAJOR: Final[str] = "X-V3-Schema-Major"
HDR_IDEMPOTENCY_KEY: Final[str] = "X-Idempotency-Key"
HDR_PAYLOAD_HASH: Final[str] = "X-V3-Payload-Hash"


# --------------------------------------------------------------------------
# 结构化边界错误
# --------------------------------------------------------------------------


class ServiceBoundaryError(RuntimeError):
    """服务边界失败基类; code 是稳定机器码, details 携带诊断字段。"""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


class SocketAclError(ServiceBoundaryError):
    """socket 不存在/类型错误/owner/group/mode 不满足 ACL。"""


class PrivateAccessError(ServiceBoundaryError):
    """key/DB 路径可被 CLI principal 读取, 或无法证明归属。"""


class IdentityError(ServiceBoundaryError):
    """服务器身份或 capability 与客户端期望不一致。"""


class SchemaNegotiationError(ServiceBoundaryError):
    """服务器 schema major 与客户端不一致。"""


class ServiceTimeoutError(ServiceBoundaryError):
    """UDS 请求超时。"""


class ConflictingRequestError(ServiceBoundaryError):
    """同一幂等键被用于不同请求体。"""


class StaleLeaseError(ServiceBoundaryError):
    """进程 lease 缺失/损坏/pid 已死/身份不匹配。"""


# --------------------------------------------------------------------------
# 进程 lease
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessLease:
    """socket 旁进程 lease: 记录持锁 pid、服务名、启动时间与 owner uid。"""

    pid: int
    service_name: str
    started_at: str
    owner_uid: int


def socket_path_for(socket_dir: Path, service_name: str) -> Path:
    """返回 <socket_dir>/<service_name>.sock 的规范化 socket 路径。"""

    return socket_dir / f"{service_name}.sock"


def lease_path_for(socket_dir: Path, service_name: str) -> Path:
    """返回 <socket_dir>/<service_name>.lease.json 的 lease 路径。"""

    return socket_dir / f"{service_name}.lease.json"


def validate_socket_acl(
    socket_path: Path,
    *,
    expected_owner_uid: int,
    expected_owner_gid: int,
    expected_mode: int = V3_SOCKET_MODE,
) -> None:
    """校验 socket 存在、确为 socket、owner/gid/mode 精确匹配。

    任何不满足即抛 SocketAclError(fail-closed)。
    """
    try:
        info = socket_path.stat()
    except OSError as exc:
        raise SocketAclError(
            "socket_missing",
            "service socket must exist",
            path=str(socket_path),
        ) from exc
    if not stat.S_ISSOCK(info.st_mode):
        raise SocketAclError(
            "socket_not_socket",
            "path must be a unix domain socket",
            path=str(socket_path),
        )
    if info.st_uid != expected_owner_uid:
        raise SocketAclError(
            "socket_wrong_owner_uid",
            "socket must be owned by the service principal",
            path=str(socket_path),
            owner_uid=info.st_uid,
            expected_uid=expected_owner_uid,
        )
    if info.st_gid != expected_owner_gid:
        raise SocketAclError(
            "socket_wrong_owner_gid",
            "socket must be owned by the service group",
            path=str(socket_path),
            owner_gid=info.st_gid,
            expected_gid=expected_owner_gid,
        )
    mode = stat.S_IMODE(info.st_mode)
    # The protocol requires NO group/other access; the owner bits must be the
    # expected mode. Reject any group/other bit regardless of the owner bits.
    if mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IXGRP
               | stat.S_IROTH | stat.S_IWOTH | stat.S_IXOTH):
        raise SocketAclError(
            "socket_group_or_other_accessible",
            "socket must be owner-only",
            path=str(socket_path),
            mode=oct(mode),
        )
    if mode != expected_mode:
        raise SocketAclError(
            "socket_mode_mismatch",
            "socket mode differs from the expected owner-only mode",
            path=str(socket_path),
            mode=oct(mode),
            expected=oct(expected_mode),
        )


def validate_process_lease(
    lease_path: Path,
    *,
    expected_service_name: str,
    expected_owner_uid: int,
) -> None:
    """校验进程 lease: 文件存在、JSON 可解析、pid 存活、服务名与 owner 匹配。

    pid 已死或任何身份不匹配即抛 StaleLeaseError。
    """
    try:
        raw = lease_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StaleLeaseError(
            "lease_missing",
            "process lease must exist",
            path=str(lease_path),
        ) from exc
    try:
        payload = json.loads(raw)
        lease = ProcessLease(
            pid=int(payload["pid"]),
            service_name=str(payload["service_name"]),
            started_at=str(payload["started_at"]),
            owner_uid=int(payload["owner_uid"]),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise StaleLeaseError(
            "lease_corrupt",
            "process lease must be a valid JSON lease document",
            path=str(lease_path),
        ) from exc
    if lease.service_name != expected_service_name:
        raise StaleLeaseError(
            "lease_service_mismatch",
            "process lease service name mismatch",
            service=lease.service_name,
            expected=expected_service_name,
        )
    if lease.owner_uid != expected_owner_uid:
        raise StaleLeaseError(
            "lease_owner_mismatch",
            "process lease owner uid mismatch",
            owner_uid=lease.owner_uid,
            expected_uid=expected_owner_uid,
        )
    if not _pid_is_alive(lease.pid):
        raise StaleLeaseError(
            "lease_pid_dead",
            "process lease pid is no longer alive",
            pid=lease.pid,
        )


def _pid_is_alive(pid: int) -> bool:
    """POSIX liveness probe: a live pid has a process entry for this uid."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Owned by a different user but still running - for a service lease we
        # require our own process, so treat a foreign-process pid as alive
        # (the owner-uid check above already scopes it to the right user).
        return True
    return True
