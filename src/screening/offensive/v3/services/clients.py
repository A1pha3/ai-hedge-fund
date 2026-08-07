"""Task 1: UDS-only ServiceClient — 幂等头、超时包装、重复/冲突检测与身份协商校验。"""

from __future__ import annotations

import hashlib

import httpx

from src.screening.offensive.v3.services.common import (
    ConflictingRequestError,
    HDR_IDEMPOTENCY_KEY,
    HDR_PAYLOAD_HASH,
    HDR_SERVICE_CAPABILITY,
    HDR_SERVICE_IDENTITY,
    HDR_SERVICE_SCHEMA_MAJOR,
    IdentityError,
    SchemaNegotiationError,
    ServiceTimeoutError,
    V3_SCHEMA_MAJOR,
)
from src.screening.offensive.v3.services.identity import ServiceIdentity


class ServiceClient:
    """通过 Unix domain socket 调用窄服务的无特权客户端。

    request() 携带身份/capability/schema 头与幂等键, 并校验服务器回应的
    身份/capability/schema; 回放同一幂等键+同一 payload 放行, 同键不同
    payload 抛 ConflictingRequestError。未注入 transport 时走真实 UDS。
    """

    def __init__(
        self,
        *,
        identity: ServiceIdentity,
        timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._identity = identity
        self._timeout = timeout
        self._transport = transport
        self._seen_payloads: dict[str, bytes] = {}

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: bytes | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        """发送请求并校验服务器身份/capability/schema; 超时与冲突按类型上抛。"""
        headers = {
            HDR_SERVICE_IDENTITY: self._identity.service_name,
            HDR_SERVICE_CAPABILITY: self._identity.capability_namespace,
            HDR_SERVICE_SCHEMA_MAJOR: str(V3_SCHEMA_MAJOR),
        }
        if payload is not None:
            headers[HDR_PAYLOAD_HASH] = hashlib.sha256(payload).hexdigest()
        if idempotency_key is not None:
            headers[HDR_IDEMPOTENCY_KEY] = idempotency_key
            prior = self._seen_payloads.get(idempotency_key)
            if prior is not None and prior != payload:
                raise ConflictingRequestError(
                    "idempotency_key_payload_conflict",
                    "same idempotency key reused for a different payload",
                    idempotency_key=idempotency_key,
                )

        transport = self._transport
        if transport is None:
            transport = httpx.HTTPTransport(
                uds=str(self._identity.socket_path),
                retries=0,
            )
        # UDS 客户端没有真实 host; httpx cookie jar 解析相对 URL 会崩溃,
        # 因此用合成绝对 URL, 仅 host 占位, 实际请求仍由 UDS 传输接管。
        url = f"http://uds.local{path}"
        try:
            with httpx.Client(
                transport=transport, timeout=self._timeout, trust_env=False
            ) as client:
                response = client.request(method, url, headers=headers, content=payload)
        except httpx.TimeoutException as exc:
            raise ServiceTimeoutError(
                "service_timeout",
                "service request timed out",
                path=path,
            ) from exc

        if response.headers.get(HDR_SERVICE_IDENTITY) != self._identity.service_name:
            raise IdentityError(
                "server_identity_mismatch",
                "server identity does not match the expected service",
                expected=self._identity.service_name,
                observed=response.headers.get(HDR_SERVICE_IDENTITY),
            )
        if (
            response.headers.get(HDR_SERVICE_CAPABILITY)
            != self._identity.capability_namespace
        ):
            raise IdentityError(
                "server_capability_mismatch",
                "server capability does not match the expected namespace",
                expected=self._identity.capability_namespace,
                observed=response.headers.get(HDR_SERVICE_CAPABILITY),
            )
        if response.headers.get(HDR_SERVICE_SCHEMA_MAJOR) != str(V3_SCHEMA_MAJOR):
            raise SchemaNegotiationError(
                "server_schema_major_mismatch",
                "server schema major does not match the client",
                expected=str(V3_SCHEMA_MAJOR),
                observed=response.headers.get(HDR_SERVICE_SCHEMA_MAJOR),
            )

        if idempotency_key is not None:
            self._seen_payloads[idempotency_key] = payload
        return response
