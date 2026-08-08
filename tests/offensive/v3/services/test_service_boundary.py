"""Plan 05 Task 1 (RED): 认证 UDS 基础、进程身份与可信时钟边界。

覆盖 Step 1 要求: wrong server identity/capability、socket owner/mode、
schema negotiation、timeout、duplicate/conflicting request、key path
readable by CLI、stale process lease、clock rollback/skew。

本文件引用尚未实现的行为(骨架方法一律 raise NotImplementedError);
当前应整体 RED, 由主代理随后实现 GREEN。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket as socket_module
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from src.screening.offensive.v3.contracts import ClockHealth
from src.screening.offensive.v3.services.clients import ServiceClient
from src.screening.offensive.v3.services.common import (
    ConflictingRequestError,
    HDR_IDEMPOTENCY_KEY,
    HDR_PAYLOAD_HASH,
    HDR_SERVICE_CAPABILITY,
    HDR_SERVICE_IDENTITY,
    HDR_SERVICE_SCHEMA_MAJOR,
    IdentityError,
    PrivateAccessError,
    SchemaNegotiationError,
    ServiceTimeoutError,
    SocketAclError,
    StaleLeaseError,
    validate_process_lease,
    validate_socket_acl,
)
from src.screening.offensive.v3.services.identity import ServiceIdentity
from src.screening.offensive.v3.services.trusted_clock import TrustedClock

UTC = timezone.utc
NOW = datetime(2026, 8, 7, 9, 0, 0, tzinfo=UTC)
GATEWAY_NAME = "capital-gateway"
GATEWAY_CAPABILITY = "capital-gateway.writable.v2"


# --------------------------------------------------------------------------
# 测试工具
# --------------------------------------------------------------------------

# macOS AF_UNIX 路径上限 104 字节, pytest tmp_path 经常超长 → 用短临时目录
# 作为 socket 目录(并最终清理)。
_SOCKET_DIR: Path | None = None


def _socket_dir() -> Path:
    global _SOCKET_DIR
    if _SOCKET_DIR is None:
        _SOCKET_DIR = Path(tempfile.mkdtemp(prefix="v3sock-"))
    return _SOCKET_DIR


def _make_identity(
    tmp_path: Path,
    *,
    service_name: str = GATEWAY_NAME,
    capability: str = GATEWAY_CAPABILITY,
    owner_uid: int | None = None,
    owner_gid: int | None = None,
) -> ServiceIdentity:
    return ServiceIdentity(
        service_name=service_name,
        capability_namespace=capability,
        owner_uid=os.getuid() if owner_uid is None else owner_uid,
        owner_gid=os.getgid() if owner_gid is None else owner_gid,
        socket_path=_socket_dir() / f"{service_name}.sock",
        db_dsn=f"sqlite:///{tmp_path}/gateway.sqlite",
    )


def _bind_unix_socket(path: Path) -> None:
    # 生产服务启动时同样会清理陈旧 socket 文件后再 bind
    try:
        path.unlink()
    except OSError:
        pass
    sock = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    try:
        sock.bind(str(path))
    finally:
        sock.close()


def _ok_headers() -> dict[str, str]:
    return {
        HDR_SERVICE_IDENTITY: GATEWAY_NAME,
        HDR_SERVICE_CAPABILITY: GATEWAY_CAPABILITY,
        HDR_SERVICE_SCHEMA_MAJOR: "2",
    }


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, headers=_ok_headers(), json={"status": "ok"})


def _make_client(
    tmp_path: Path, *, transport: httpx.BaseTransport | None = None
) -> ServiceClient:
    return ServiceClient(identity=_make_identity(tmp_path), transport=transport, timeout=2.0)


def _make_clock(
    wall_values: list[datetime],
    mono_values: list[int],
    *,
    max_skew: timedelta = timedelta(minutes=5),
) -> TrustedClock:
    wall_iter = iter(wall_values)
    mono_iter = iter(mono_values)
    return TrustedClock(
        wall_clock=lambda: next(wall_iter),
        monotonic_ns=lambda: next(mono_iter),
        max_skew=max_skew,
    )


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=30)
    return proc.pid


def _write_lease(
    path: Path,
    *,
    pid: int,
    service_name: str,
    owner_uid: int,
    started_at: str = "2026-08-07T09:00:00+00:00",
) -> None:
    path.write_text(
        json.dumps(
            {
                "pid": pid,
                "service_name": service_name,
                "started_at": started_at,
                "owner_uid": owner_uid,
            }
        )
    )


# --------------------------------------------------------------------------
# socket owner/mode ACL
# --------------------------------------------------------------------------


def test_socket_acl_accepts_owner_only_socket(tmp_path: Path) -> None:
    socket_path = _socket_dir() / f"{GATEWAY_NAME}.sock"
    _bind_unix_socket(socket_path)
    os.chmod(socket_path, 0o600)
    validate_socket_acl(
        socket_path,
        expected_owner_uid=os.getuid(),
        expected_owner_gid=os.getgid(),
    )  # 不抛即通过


def test_socket_acl_rejects_missing_socket(tmp_path: Path) -> None:
    with pytest.raises(SocketAclError):
        validate_socket_acl(
            _socket_dir() / "missing.sock",
            expected_owner_uid=os.getuid(),
            expected_owner_gid=os.getgid(),
        )


def test_socket_acl_rejects_regular_file(tmp_path: Path) -> None:
    socket_path = _socket_dir() / "not-a-socket"
    socket_path.write_text("x")
    with pytest.raises(SocketAclError):
        validate_socket_acl(
            socket_path,
            expected_owner_uid=os.getuid(),
            expected_owner_gid=os.getgid(),
        )


def test_socket_acl_rejects_group_readable_socket(tmp_path: Path) -> None:
    socket_path = _socket_dir() / f"{GATEWAY_NAME}.sock"
    _bind_unix_socket(socket_path)
    os.chmod(socket_path, 0o640)
    with pytest.raises(SocketAclError):
        validate_socket_acl(
            socket_path,
            expected_owner_uid=os.getuid(),
            expected_owner_gid=os.getgid(),
        )


def test_socket_acl_rejects_world_readable_socket(tmp_path: Path) -> None:
    socket_path = _socket_dir() / f"{GATEWAY_NAME}.sock"
    _bind_unix_socket(socket_path)
    os.chmod(socket_path, 0o644)
    with pytest.raises(SocketAclError):
        validate_socket_acl(
            socket_path,
            expected_owner_uid=os.getuid(),
            expected_owner_gid=os.getgid(),
        )


def test_socket_acl_rejects_wrong_owner_uid(tmp_path: Path) -> None:
    socket_path = _socket_dir() / f"{GATEWAY_NAME}.sock"
    _bind_unix_socket(socket_path)
    os.chmod(socket_path, 0o600)
    with pytest.raises(SocketAclError):
        validate_socket_acl(
            socket_path,
            expected_owner_uid=os.getuid() + 1,
            expected_owner_gid=os.getgid(),
        )


def test_socket_acl_rejects_wrong_owner_gid(tmp_path: Path) -> None:
    socket_path = _socket_dir() / f"{GATEWAY_NAME}.sock"
    _bind_unix_socket(socket_path)
    os.chmod(socket_path, 0o600)
    with pytest.raises(SocketAclError):
        validate_socket_acl(
            socket_path,
            expected_owner_uid=os.getuid(),
            expected_owner_gid=os.getgid() + 1,
        )


# --------------------------------------------------------------------------
# key/DB 路径对 CLI principal 不可读(require_private_access)
# --------------------------------------------------------------------------


def test_private_access_accepts_owner_only_key(tmp_path: Path) -> None:
    key = tmp_path / "signing-key.pem"
    key.write_text("opaque-key-material")
    os.chmod(key, 0o600)
    _make_identity(tmp_path).require_private_access(key)  # 不抛即通过


def test_private_access_rejects_world_readable_key(tmp_path: Path) -> None:
    key = tmp_path / "signing-key.pem"
    key.write_text("opaque-key-material")
    os.chmod(key, 0o644)
    with pytest.raises(PrivateAccessError):
        _make_identity(tmp_path).require_private_access(key)


def test_private_access_rejects_group_readable_key(tmp_path: Path) -> None:
    key = tmp_path / "signing-key.pem"
    key.write_text("opaque-key-material")
    os.chmod(key, 0o640)
    with pytest.raises(PrivateAccessError):
        _make_identity(tmp_path).require_private_access(key)


def test_private_access_rejects_cli_owned_key(tmp_path: Path) -> None:
    # 测试进程扮演 CLI principal: 文件归 CLI 所有, 服务 principal 是另一 uid
    db = tmp_path / "writable-db.sqlite"
    db.write_text("db-bytes")
    os.chmod(db, 0o600)
    service_identity = _make_identity(tmp_path, owner_uid=os.getuid() + 1)
    with pytest.raises(PrivateAccessError):
        service_identity.require_private_access(db)


def test_private_access_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(PrivateAccessError):
        _make_identity(tmp_path).require_private_access(tmp_path / "missing-key.pem")


# --------------------------------------------------------------------------
# ServiceIdentity 匹配与归属
# --------------------------------------------------------------------------


def test_identity_matches_equal_identity(tmp_path: Path) -> None:
    identity = _make_identity(tmp_path)
    twin = _make_identity(tmp_path)
    assert identity.matches(twin)
    assert twin.matches(identity)


def test_identity_mismatch_service_name(tmp_path: Path) -> None:
    assert not _make_identity(tmp_path).matches(
        _make_identity(tmp_path, service_name="market-publisher")
    )


def test_identity_mismatch_capability(tmp_path: Path) -> None:
    assert not _make_identity(tmp_path).matches(
        _make_identity(tmp_path, capability="market.writable.v2")
    )


def test_identity_mismatch_owner(tmp_path: Path) -> None:
    assert not _make_identity(tmp_path).matches(
        _make_identity(tmp_path, owner_uid=os.getuid() + 1)
    )


def test_identity_carries_socket_and_db_ownership(tmp_path: Path) -> None:
    identity = _make_identity(tmp_path)
    assert identity.socket_path == _socket_dir() / f"{GATEWAY_NAME}.sock"
    assert identity.db_dsn.startswith("sqlite:///")
    assert identity.owner_uid == os.getuid()


# --------------------------------------------------------------------------
# stale process lease
# --------------------------------------------------------------------------


def test_lease_accepts_live_own_process(tmp_path: Path) -> None:
    lease = tmp_path / "gateway.lease.json"
    _write_lease(lease, pid=os.getpid(), service_name=GATEWAY_NAME, owner_uid=os.getuid())
    validate_process_lease(
        lease,
        expected_service_name=GATEWAY_NAME,
        expected_owner_uid=os.getuid(),
    )  # 不抛即通过


def test_stale_process_lease_detected(tmp_path: Path) -> None:
    lease = tmp_path / "gateway.lease.json"
    _write_lease(lease, pid=_dead_pid(), service_name=GATEWAY_NAME, owner_uid=os.getuid())
    with pytest.raises(StaleLeaseError):
        validate_process_lease(
            lease,
            expected_service_name=GATEWAY_NAME,
            expected_owner_uid=os.getuid(),
        )


def test_lease_service_name_mismatch(tmp_path: Path) -> None:
    lease = tmp_path / "gateway.lease.json"
    _write_lease(lease, pid=os.getpid(), service_name="market-publisher", owner_uid=os.getuid())
    with pytest.raises(StaleLeaseError):
        validate_process_lease(
            lease,
            expected_service_name=GATEWAY_NAME,
            expected_owner_uid=os.getuid(),
        )


def test_lease_owner_mismatch(tmp_path: Path) -> None:
    lease = tmp_path / "gateway.lease.json"
    _write_lease(lease, pid=os.getpid(), service_name=GATEWAY_NAME, owner_uid=os.getuid() + 1)
    with pytest.raises(StaleLeaseError):
        validate_process_lease(
            lease,
            expected_service_name=GATEWAY_NAME,
            expected_owner_uid=os.getuid(),
        )


def test_lease_missing_file(tmp_path: Path) -> None:
    with pytest.raises(StaleLeaseError):
        validate_process_lease(
            tmp_path / "missing.lease.json",
            expected_service_name=GATEWAY_NAME,
            expected_owner_uid=os.getuid(),
        )


# --------------------------------------------------------------------------
# 可信时钟: rollback / skew / 健康门控
# --------------------------------------------------------------------------


def test_clock_healthy_sequence_and_monotonic_source(tmp_path: Path) -> None:
    clock = _make_clock([NOW, NOW + timedelta(minutes=1)], [1_000, 60_000_000_001])
    first = clock.observe()
    second = clock.observe()
    assert first.clock_health is ClockHealth.HEALTHY
    assert second.clock_health is ClockHealth.HEALTHY
    assert first.monotonic_sequence == 1
    assert second.monotonic_sequence == 2
    assert first.wall_clock_utc == NOW
    assert first.monotonic_observation_ns == 1_000
    assert second.wall_clock_utc == NOW + timedelta(minutes=1)
    assert second.monotonic_observation_ns == 60_000_000_001
    assert bool(re.fullmatch(r"[0-9a-f]{64}", first.raw_payload_hash))
    assert first.observation_id
    assert clock.health() is ClockHealth.HEALTHY
    assert clock.is_healthy
    assert clock.allows_time_sensitive()
    assert clock.source


def test_clock_health_unknown_before_first_observation(tmp_path: Path) -> None:
    clock = _make_clock([NOW], [1_000])
    assert clock.health() is ClockHealth.UNKNOWN
    assert not clock.is_healthy
    assert not clock.allows_time_sensitive()


def test_clock_rollback_detected_blocks_time_sensitive(tmp_path: Path) -> None:
    clock = _make_clock([NOW, NOW - timedelta(minutes=1)], [1_000, 2_000])
    clock.observe()
    second = clock.observe()
    assert second.clock_health is ClockHealth.ROLLBACK_DETECTED
    assert clock.health() is ClockHealth.ROLLBACK_DETECTED
    assert not clock.is_healthy
    assert not clock.allows_time_sensitive()


def test_clock_rollback_keeps_exit_observable(tmp_path: Path) -> None:
    # exit/reconcile 在 unhealthy 时仍可调用: observe() 永不抛错
    clock = _make_clock([NOW, NOW - timedelta(minutes=1)], [1_000, 2_000])
    clock.observe()
    observation = clock.observe()
    assert observation.clock_health is ClockHealth.ROLLBACK_DETECTED
    assert observation.monotonic_sequence == 2


def test_clock_excessive_skew_blocks_time_sensitive(tmp_path: Path) -> None:
    clock = _make_clock([NOW, NOW + timedelta(hours=2)], [1_000, 2_000])
    clock.observe()
    second = clock.observe()
    assert second.clock_health is ClockHealth.EXCESSIVE_SKEW
    assert not clock.allows_time_sensitive()


def test_clock_recovers_after_consistent_deltas(tmp_path: Path) -> None:
    clock = _make_clock(
        [NOW, NOW + timedelta(hours=2), NOW + timedelta(hours=2, minutes=1)],
        [1_000, 2_000, 60_000_000_001],
    )
    clock.observe()
    assert clock.observe().clock_health is ClockHealth.EXCESSIVE_SKEW
    assert clock.observe().clock_health is ClockHealth.HEALTHY


def test_clock_raw_payload_hash_is_deterministic(tmp_path: Path) -> None:
    clock_a = _make_clock([NOW, NOW], [7, 7])
    clock_b = _make_clock([NOW, NOW], [7, 7])
    assert clock_a.observe().raw_payload_hash == clock_b.observe().raw_payload_hash


# --------------------------------------------------------------------------
# ServiceClient: 身份/capability/schema 校验、超时、幂等与 UDS 传输
# --------------------------------------------------------------------------


def test_client_round_trip_verified_headers(tmp_path: Path) -> None:
    seen_headers: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers)
        return _ok_handler(request)

    client = _make_client(tmp_path, transport=httpx.MockTransport(handler))
    response = client.request(
        "POST",
        "/v1/capital/risk-snapshot",
        payload=b'{"ok": true}',
        idempotency_key="idem-1",
    )
    assert response.status_code == 200
    headers = seen_headers[0]
    assert headers[HDR_SERVICE_IDENTITY] == GATEWAY_NAME
    assert headers[HDR_SERVICE_CAPABILITY] == GATEWAY_CAPABILITY
    assert headers[HDR_SERVICE_SCHEMA_MAJOR] == "2"
    assert headers[HDR_IDEMPOTENCY_KEY] == "idem-1"
    assert headers[HDR_PAYLOAD_HASH] == hashlib.sha256(b'{"ok": true}').hexdigest()


def test_client_rejects_wrong_server_identity(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={**_ok_headers(), HDR_SERVICE_IDENTITY: "market-publisher"},
            json={},
        )

    client = _make_client(tmp_path, transport=httpx.MockTransport(handler))
    with pytest.raises(IdentityError):
        client.request("GET", "/v1/health")


def test_client_rejects_wrong_server_capability(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={**_ok_headers(), HDR_SERVICE_CAPABILITY: "market.writable.v2"},
            json={},
        )

    client = _make_client(tmp_path, transport=httpx.MockTransport(handler))
    with pytest.raises(IdentityError):
        client.request("GET", "/v1/health")


def test_client_rejects_schema_mismatch(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={**_ok_headers(), HDR_SERVICE_SCHEMA_MAJOR: "1"},
            json={},
        )

    client = _make_client(tmp_path, transport=httpx.MockTransport(handler))
    with pytest.raises(SchemaNegotiationError):
        client.request("GET", "/v1/health")


def test_client_timeout_raises_service_timeout(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated read timeout")

    client = _make_client(tmp_path, transport=httpx.MockTransport(handler))
    with pytest.raises(ServiceTimeoutError):
        client.request("GET", "/v1/health")


def test_client_conflicting_idempotency_key(tmp_path: Path) -> None:
    client = _make_client(tmp_path, transport=httpx.MockTransport(_ok_handler))
    client.request("POST", "/v1/capital/gateway-command", payload=b'{"a": 1}', idempotency_key="k-1")
    with pytest.raises(ConflictingRequestError):
        client.request("POST", "/v1/capital/gateway-command", payload=b'{"a": 2}', idempotency_key="k-1")


def test_client_replay_with_same_key_allowed(tmp_path: Path) -> None:
    # 同一幂等键 + 相同请求体 = 幂等重放, 放行
    client = _make_client(tmp_path, transport=httpx.MockTransport(_ok_handler))
    client.request("POST", "/v1/capital/gateway-command", payload=b'{"a": 1}', idempotency_key="k-2")
    client.request("POST", "/v1/capital/gateway-command", payload=b'{"a": 1}', idempotency_key="k-2")


def test_client_uses_uds_transport_by_default(tmp_path: Path) -> None:
    # 未注入 transport 时客户端必须走真实 UDS 路径(此处无人监听 → ConnectError)
    client = _make_client(tmp_path)
    with pytest.raises(httpx.ConnectError):
        client.request("GET", "/v1/health")


def _teardown_socket_dir() -> None:
    global _SOCKET_DIR
    if _SOCKET_DIR is not None:
        for child in _SOCKET_DIR.iterdir():
            try:
                child.unlink()
            except OSError:
                pass
        try:
            _SOCKET_DIR.rmdir()
        except OSError:
            pass
        _SOCKET_DIR = None


def pytest_sessionfinish(session: object, exitstatus: object) -> None:
    _teardown_socket_dir()
