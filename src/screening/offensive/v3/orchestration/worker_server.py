"""特权 worker UDS 进程边界原语 — offline primitive (2026-08-22, R20).

把 ``ForwardSessionAssembler`` 从"库层编排"(Plan 05 owner 知情批准的
shadow 偏差) 升级为**独立进程边界**的服务面原语:

- ``bind``: socket 路径/进程 lease 复用 Plan 05 ``services/common`` 单一
  实现; stale socket(无活 lease 进程)清理重绑, 活 lease 冲突拒绝; bind
  后 ACL 自检 (0600 owner-only)。
- ``serve_once``: 单连接串行 — 对端凭证检查 (同 uid 准入, 凭证提取器
  可注入以便测试), JSON 请求协议 (``op=assemble``), assemble 结果以
  **可序列化摘要**返回 (stage/merkle root/watermark/冻结输入哈希 — 不
  整体序列化领域对象), 类型化错误面 (``ok:false + code``)。

本原语不解锁 runner、不启动 daemon (owner 启动工程后续)、不构成权限;
它消除的是「特权 worker 必须独立进程」这一 Plan 架构要求的技术缺口。
"""

from __future__ import annotations

import json
import os
import socket
import stat
import struct
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from src.screening.offensive.v3.orchestration.privileged_worker import (
    ForwardSessionAssembler,
    PrivilegedWorkerError,
)
from src.screening.offensive.v3.services.common import (
    ProcessLease,
    ServiceBoundaryError,
    lease_path_for,
    socket_path_for,
    validate_process_lease,
    validate_socket_acl,
)

SERVICE_NAME = "privileged-worker"
DEFAULT_TIMEOUT_SECONDS = 30.0


class WorkerServerError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def _default_peer_uid(conn: socket.socket) -> int:
    """对端 uid: Linux SO_PEERCRED / macOS LOCAL_PEERCRED。"""
    import platform

    system = platform.system()
    try:
        if system == "Linux":
            data = conn.getsockopt(socket.SOL_SOCKET, 17, struct.calcsize("3i"))
            return int(struct.unpack("3i", data)[1])
        if system == "Darwin":
            # struct xucred: uint32 version; uid_t[1]... — 取前 8 字节读 uid
            data = conn.getsockopt(0, 0x01, 8)  # SOL_LOCAL=0, LOCAL_PEERCRED=1
            return int(struct.unpack("2I", data)[1])
    except OSError as exc:  # pragma: no cover - platform dependent
        raise WorkerServerError(
            "peer_credential_unavailable",
            "failed to read the peer credential",
            platform=system,
        ) from exc
    raise WorkerServerError(
        "peer_credential_unsupported",
        "no peer credential mechanism on this platform",
        platform=system,
    )


@dataclass(frozen=True)
class WorkerServerConfig:
    socket_dir: Path
    service_name: str = SERVICE_NAME
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


class PrivilegedWorkerServer:
    """UDS 上的一次一连接 assemble 服务 (进程边界原语)。"""

    def __init__(
        self,
        *,
        assembler: ForwardSessionAssembler,
        config: WorkerServerConfig,
        peer_uid_extractor: Callable[[socket.socket], int] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._assembler = assembler
        self._config = config
        self._peer_uid = peer_uid_extractor or _default_peer_uid
        self._now = now or (lambda: datetime.now())
        self._socket: socket.socket | None = None

    # -- lifecycle ----------------------------------------------------------

    def bind(self) -> Path:
        """Bind socket + 写 lease; stale 清理 / 活 lease 冲突拒绝。"""
        sock_path = socket_path_for(self._config.socket_dir, self._config.service_name)
        lease_path = lease_path_for(self._config.socket_dir, self._config.service_name)
        self._config.socket_dir.mkdir(parents=True, exist_ok=True)

        if sock_path.exists():
            # 活 lease (pid 存活且身份匹配) = 冲突; 否则 stale → 清理重绑
            live = False
            if lease_path.exists():
                try:
                    validate_process_lease(
                        lease_path,
                        expected_service_name=self._config.service_name,
                        expected_owner_uid=os.getuid(),
                    )
                    live = True
                except ServiceBoundaryError:
                    live = False
            if live:
                raise WorkerServerError(
                    "worker_server_conflict",
                    "another privileged worker holds a live lease",
                    socket=str(sock_path),
                )
            sock_path.unlink()

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        os.chmod(sock_path, 0o600)
        server.listen(1)
        self._socket = server

        lease = ProcessLease(
            pid=os.getpid(),
            service_name=self._config.service_name,
            started_at=self._now().isoformat(),
            owner_uid=os.getuid(),
        )
        lease_path.write_text(
            json.dumps(
                {
                    "pid": lease.pid,
                    "service_name": lease.service_name,
                    "started_at": lease.started_at,
                    "owner_uid": lease.owner_uid,
                }
            ),
            encoding="utf-8",
        )
        validate_socket_acl(
            sock_path,
            expected_owner_uid=os.getuid(),
            expected_owner_gid=os.getgid(),
        )
        return sock_path

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        sock_path = socket_path_for(self._config.socket_dir, self._config.service_name)
        lease_path = lease_path_for(self._config.socket_dir, self._config.service_name)
        for path in (sock_path, lease_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    # -- serving ------------------------------------------------------------

    def serve_once(self) -> dict:
        """Accept 恰一个连接: 凭证检查 → 请求 → 响应 dict (同时返回给调用方)。

        决策与送达分离: 对端消失只影响送达 (response 标注 delivered=False),
        传输层异常不得以裸 OSError 逃逸杀死调用方 serve 循环。"""
        if self._socket is None:
            raise WorkerServerError("worker_server_not_bound", "call bind() first")
        self._socket.settimeout(self._config.timeout_seconds)
        try:
            conn, _ = self._socket.accept()
        except socket.timeout as exc:
            raise WorkerServerError(
                "worker_server_timeout", "no client connected within timeout"
            ) from exc
        except OSError as exc:
            # accept 侧资源类失败 (EMFILE/ENFILE 类) 类型化: 全量套件/运维压力
            # 下裸 OSError 逃逸会把 flake 变成不可归因的 KeyError (R42 登记)。
            raise WorkerServerError(
                "accept_failed", "accept raised an OS-level error", reason=str(exc)
            ) from exc
        with conn:
            peer_uid = self._peer_uid(conn)
            if peer_uid != os.getuid():
                response = {
                    "ok": False,
                    "code": "peer_uid_rejected",
                    "peer_uid": peer_uid,
                    "expected_uid": os.getuid(),
                }
            else:
                response = self._handle(conn)
            try:
                conn.sendall(
                    json.dumps(response, ensure_ascii=False).encode("utf-8")
                )
            except OSError as exc:
                # 对端在响应送达前消失 (EPIPE/ECONNRESET): 决策已作出——保留
                # 已计算 response 并如实标注送达失败, 单个消失客户端不得以
                # 裸传输异常杀死 daemon serve 循环。
                response = {
                    **response,
                    "delivered": False,
                    "delivery_error": f"{type(exc).__name__}: {exc}",
                }
        return response

    def _handle(self, conn: socket.socket) -> dict:
        try:
            raw = self._recv_json_object(conn)
        except WorkerServerError as exc:
            return {"ok": False, "code": exc.code, **exc.details}
        if not isinstance(raw, dict):
            return {"ok": False, "code": "request_not_object"}
        op = raw.get("op")
        if op != "assemble":
            return {"ok": False, "code": "op_unknown", "op": op}
        try:
            assembled = self._assembler.assemble(
                session=date.fromisoformat(str(raw["session"])),
                cutoff=datetime.fromisoformat(str(raw["cutoff"])),
                cycle_id=str(raw["cycle_id"]),
                trusted_at=datetime.fromisoformat(str(raw["trusted_at"])),
                schedule_evidence_id=str(raw["schedule_evidence_id"]),
                candidate_evidence_ids=tuple(raw.get("candidate_evidence_ids", ())),
            )
        except PrivilegedWorkerError as exc:
            return {"ok": False, "code": exc.code, **exc.details}
        except (KeyError, ValueError) as exc:
            return {"ok": False, "code": "request_invalid", "reason": str(exc)[:200]}
        authority = assembled.authority
        return {
            "ok": True,
            "op": "assemble",
            "stage_id": assembled.shared_input.stage_id,
            "session": assembled.shared_input.signal_session.isoformat(),
            "rule_version": authority.rule_version,
            "evidence_set_merkle_root": authority.evidence_set_merkle_root,
            "commit_sequence_watermark": authority.commit_sequence_watermark,
            "shared_input_hash": assembled.shared_input.content_hash(),
            "candidates": len(assembled.candidates),
        }

    def _recv_json_object(self, conn: socket.socket):
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > 1 << 20:
                raise WorkerServerError("request_too_large", "request exceeds 1 MiB")
            try:
                text = b"".join(chunks).decode("utf-8")
                return json.loads(text)
            except (ValueError, UnicodeDecodeError):
                continue
        raise WorkerServerError("request_empty", "connection closed before a request")


__all__ = [
    "PrivilegedWorkerServer",
    "WorkerServerConfig",
    "WorkerServerError",
]
