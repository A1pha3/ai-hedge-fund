"""Plan 06 Task 1 共享 fixture: 真实 Ed25519 trust fabric + v2 盘点用 ledger 构造.

与 tests/offensive/v3/contracts/test_trust_registry.py 的 `_signed` /
`_root_verified_bundle` 同源, 但收敛为 Plan 06 migration 测试可直接复用的
具名 helper — 任何一处信任链语义变更只需要改这里.
"""

from __future__ import annotations

from base64 import b64encode
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.screening.offensive.ledger_repository import LedgerRepository
from src.screening.offensive.trade_lifecycle import ExecutionMode, FillSource
from src.screening.offensive.v3.contracts import (
    ArtifactKind,
    Capability,
    ExecutionMode as V3ExecutionMode,
    IssuerKind,
    SignedEnvelope,
    canonical_json_bytes,
)
from src.screening.offensive.v3.contracts.governance import TrustBundle
from src.screening.offensive.v3.trust import (
    CapabilityVerifier,
    CurrentTrustHeadWitness,
    RootTrustAnchor,
    SignedTrustBundle,
    TrustBundleVerifier,
    TrustedIssuer,
    TrustedRegistry,
    trust_bundle_signature_preimage,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64

MIGRATION_NAMESPACE = "capital.migration.v2-to-v3"
MIGRATION_MODE = V3ExecutionMode.DAILY_BAR_PROXY
MIGRATION_CAPABILITY_VERSION = "governance.migration.approval.v1"
MIGRATION_SCOPE = "v2-to-v3"


def _public_key_b64(private_key: Ed25519PrivateKey) -> str:
    return b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")


def make_migration_capability(**overrides: Any) -> Capability:
    values: dict[str, Any] = dict(
        artifact=ArtifactKind.MIGRATION_APPROVAL_MANIFEST,
        namespace=MIGRATION_NAMESPACE,
        mode=MIGRATION_MODE,
        schema_major=2,
        capability_version=MIGRATION_CAPABILITY_VERSION,
        scope=MIGRATION_SCOPE,
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=30),
        revoked_at=None,
    )
    values.update(overrides)
    return Capability(**values)


def make_issuer(
    private_key: Ed25519PrivateKey,
    capability: Capability,
    **overrides: Any,
) -> TrustedIssuer:
    values: dict[str, Any] = dict(
        issuer_id="governance-migration",
        key_id="governance-migration-key-1",
        issuer_kind=IssuerKind.GOVERNANCE,
        public_key=_public_key_b64(private_key),
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=30),
        revoked_at=None,
        capabilities=(capability,),
    )
    values.update(overrides)
    return TrustedIssuer(**values)


def sign_payload(
    private_key: Ed25519PrivateKey,
    capability: Capability,
    *,
    issuer_id: str,
    key_id: str,
    payload: bytes,
) -> SignedEnvelope:
    digest = hashlib.sha256(payload).hexdigest()
    protected = canonical_json_bytes(
        {
            "artifact": capability.artifact,
            "capability_scope": capability.scope,
            "capability_version": capability.capability_version,
            "issuer_id": issuer_id,
            "key_id": key_id,
            "mode": capability.mode,
            "namespace": capability.namespace,
            "payload": b64encode(payload).decode("ascii"),
            "payload_hash": digest,
            "schema_major": capability.schema_major,
        }
    )
    return SignedEnvelope(
        issuer_id=issuer_id,
        key_id=key_id,
        schema_major=capability.schema_major,
        artifact=capability.artifact,
        namespace=capability.namespace,
        mode=capability.mode,
        capability_version=capability.capability_version,
        capability_scope=capability.scope,
        payload_hash=digest,
        payload=payload,
        signature=b64encode(private_key.sign(protected)).decode("ascii"),
    )


class TrustFabric:
    """一次性测试信任链: root anchor -> genesis bundle -> registry."""

    def __init__(
        self,
        issuers: tuple[TrustedIssuer, ...],
        *,
        trusted_at: datetime = NOW,
    ) -> None:
        self.registry = TrustedRegistry(issuers=issuers)
        root_key = Ed25519PrivateKey.generate()
        root_public = _public_key_b64(root_key)
        root_hash = hashlib.sha256(
            root_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).hexdigest()
        anchor = RootTrustAnchor(
            root_hash=root_hash,
            root_key_id="offline-root-1",
            public_key=root_public,
            valid_from=trusted_at - timedelta(days=30),
            valid_until=trusted_at + timedelta(days=30),
            revoked_at=None,
        )
        bundle = TrustBundle(
            registry_epoch=1,
            predecessor_bundle_hash="0" * 64,
            root_hash=root_hash,
            root_key_id=anchor.root_key_id,
            trusted_issuer_registry_hash=self.registry.content_hash(),
            issued_at=trusted_at - timedelta(minutes=5),
            expires_at=trusted_at + timedelta(days=1),
            revoked_at=None,
            issuer_id="offline-governance-root",
            issuer_capability="root.trust.bundle.v1",
            schema_major=2,
        )
        signature = b64encode(
            root_key.sign(trust_bundle_signature_preimage(bundle, self.registry))
        ).decode("ascii")
        candidate = SignedTrustBundle(
            bundle=bundle, registry=self.registry, signature=signature
        )
        self.bundle_verifier = TrustBundleVerifier((anchor,))
        self.verifier = CapabilityVerifier(self.bundle_verifier, (candidate,))
        self.head = CurrentTrustHeadWitness(
            active_trust_bundle_hash=bundle.artifact_hash(),
            registry_epoch=bundle.registry_epoch,
            head_version=bundle.registry_epoch,
            store_version=1,
            observed_at=trusted_at,
        )
        self.trusted_at = trusted_at


def build_trust_fabric(
    *,
    capability: Capability | None = None,
    issuer_key: Ed25519PrivateKey | None = None,
    trusted_at: datetime = NOW,
) -> tuple[TrustFabric, Ed25519PrivateKey, Capability]:
    key = issuer_key or Ed25519PrivateKey.generate()
    cap = capability or make_migration_capability()
    fabric = TrustFabric((make_issuer(key, cap),), trusted_at=trusted_at)
    return fabric, key, cap


# ---------------------------------------------------------------------------
# v2 盘点用 ledger: 覆盖 plan/open/exit_pending/skipped + valuation + mark
# ---------------------------------------------------------------------------


def build_populated_ledger(
    directory: Path,
) -> tuple[Path, LedgerRepository]:
    """构造一个非空 v2 ledger; trade_id 被稳定化为可断言的字面量."""

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "ledger.sqlite3"
    repo = LedgerRepository(path, ledger_id="test", initial_cash=100_000)
    repo.initialize()

    planned = repo.create_plan(
        "000002",
        "btst_breakout",
        "v1",
        date(2026, 7, 18),
        date(2026, 7, 21),
        0.10,
        3,
    )
    opened = repo.create_plan(
        "000001",
        "btst_breakout",
        "v1",
        date(2026, 7, 14),
        date(2026, 7, 15),
        0.10,
        1,
    )
    pending = repo.create_plan(
        "000003",
        "btst_breakout",
        "v1",
        date(2026, 7, 13),
        date(2026, 7, 14),
        0.10,
        2,
    )
    skipped = repo.create_plan(
        "000004",
        "btst_breakout",
        "v1",
        date(2026, 7, 15),
        date(2026, 7, 16),
        0.10,
        4,
    )

    for trade_id, stable in (
        (planned.trade_id, "trade-planned"),
        (opened.trade_id, "trade-open"),
        (pending.trade_id, "trade-pending"),
        (skipped.trade_id, "trade-skipped"),
    ):
        _restamp_trade_id(path, trade_id, stable)

    repo.fill_plan(
        "trade-open",
        execution_mode=ExecutionMode.BROKER_CONFIRMED,
        fill_source=FillSource.BROKER_IMPORT,
        entry_date=date(2026, 7, 15),
        raw_fill_price=10.0,
        quantity=900,
        commission=5.0,
        tax=0.0,
        slippage_cost=30.0,
    )
    repo.fill_plan(
        "trade-pending",
        execution_mode=ExecutionMode.BROKER_CONFIRMED,
        fill_source=FillSource.BROKER_IMPORT,
        entry_date=date(2026, 7, 14),
        raw_fill_price=10.0,
        quantity=900,
        commission=5.0,
        tax=0.0,
        slippage_cost=30.0,
    )
    repo.mark_exit_pending("trade-pending", date(2026, 7, 20))
    repo.defer_exit("trade-pending", date(2026, 7, 21))
    repo.skip_plan("trade-skipped", date(2026, 7, 16), "capacity")
    repo.record_valuation(
        date(2026, 7, 17),
        cash=88_775.0,
        market_value=18_900.0,
        nav=107_675.0,
        peak=107_675.0,
        drawdown=0.0,
        stale_tickers=(),
    )
    repo.record_position_mark("trade-open", date(2026, 7, 17), 10.5)
    del repo  # 释放 LedgerRepository 持有的连接, 否则 checkpoint 拿不到写锁
    _checkpoint(path)
    _delete_wal_sidecars(path)
    return path, path


def _delete_wal_sidecars(path: Path) -> None:
    """checkpoint 后移除 WAL/SHM, 使 immutable 只读连接可见全量状态.

    生产盘点路径不允许这么做 (会有活跃 writer); 测试 fixture 在写入完成后
    调用, 等价于一次干净的 close-checkpoint.
    """

    import contextlib

    for suffix in ("-wal", "-shm"):
        with contextlib.suppress(FileNotFoundError):
            (path.parent / f"{path.name}{suffix}").unlink()


def _checkpoint(path: Path) -> None:
    """把 WAL 内容落回主库, 使只读盘点无需恢复日志即可看到全量状态.

    须等待 LedgerRepository 的短事务连接完全释放后再执行, 否则
    wal_checkpoint 会因读者仍持有读锁而拿不到写锁.
    """

    import sqlite3
    import time

    for attempt in range(50):
        try:
            with sqlite3.connect(path, timeout=5.0) as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return
        except sqlite3.OperationalError:
            if attempt == 49:
                raise
            time.sleep(0.05)


def _restamp_trade_id(path: Path, old: str, new: str) -> None:
    import sqlite3

    with sqlite3.connect(path, timeout=5.0) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "UPDATE trades SET trade_id = ? WHERE trade_id = ?", (new, old)
        )
        conn.execute(
            "UPDATE trade_events SET trade_id = ? WHERE trade_id = ?",
            (new, old),
        )
        conn.execute(
            "UPDATE trade_events SET idempotency_key = REPLACE("
            "idempotency_key, ?, ?)",
            (old, new),
        )
