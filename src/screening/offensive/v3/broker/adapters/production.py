"""Plan 07 Task 1: production broker adapter placeholder.

The production adapter is disabled by default. It must not start until a
``BrokerEnablementManifest`` (Task 2) binds a frozen capability profile
and independent sandbox/order certification completes. Until then any
construction raises ``BROKER_ADAPTER_NOT_CERTIFIED``.

This module deliberately imports no vendor SDK and reads no credential
environment variable; it is the single egress boundary and it starts
closed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.screening.offensive.v3.broker.ports import BrokerPort

if TYPE_CHECKING:
    from src.screening.offensive.v3.broker.ports import (
        BrokerAccountBinding,
        BrokerRawEnvelope,
        NewOrderCommand,
    )


class ProductionAdapterError(RuntimeError):
    """Production adapter failure with a stable machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class ProductionBrokerAdapter(BrokerPort):
    """Disabled-by-default production broker adapter.

    Construction is only legal when a valid enablement manifest has been
    verified (Task 2). Until then every construction fails closed.
    """

    def __init__(self) -> None:
        raise ProductionAdapterError(
            "BROKER_ADAPTER_NOT_CERTIFIED",
            "production broker adapter is disabled until capability"
            " certification and a signed BrokerEnablementManifest complete",
        )

    @property
    def account(self) -> BrokerAccountBinding:
        raise ProductionAdapterError(
            "BROKER_ADAPTER_NOT_CERTIFIED", "adapter not enabled"
        )

    def submit(self, command: NewOrderCommand) -> BrokerRawEnvelope:
        raise ProductionAdapterError(
            "BROKER_ADAPTER_NOT_CERTIFIED", "adapter not enabled"
        )

    def cancel(self, client_order_id: str) -> BrokerRawEnvelope:
        raise ProductionAdapterError(
            "BROKER_ADAPTER_NOT_CERTIFIED", "adapter not enabled"
        )

    def query_order(self, client_order_id: str) -> BrokerRawEnvelope:
        raise ProductionAdapterError(
            "BROKER_ADAPTER_NOT_CERTIFIED", "adapter not enabled"
        )

    def query_fills(
        self, *, account: BrokerAccountBinding
    ) -> BrokerRawEnvelope:
        raise ProductionAdapterError(
            "BROKER_ADAPTER_NOT_CERTIFIED", "adapter not enabled"
        )
