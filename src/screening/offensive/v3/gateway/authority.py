"""Capital Gateway authority store (Plan 04 Task 4).

One writer for authority state. Trust bundles, policy activations and
authorization envelopes activate through monotonic compare-and-swap in a
single transaction per portfolio; entry fences raise/acknowledge durably
and tombstone unclaimed entries without ever touching exits. Everything
here stays authority bookkeeping: no seal, permit or send right is
granted by this module.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Final

import sqlalchemy as sa

from src.screening.offensive.v3.contracts import (
    ExecutionMode,
    SignedEnvelope,
)
from src.screening.offensive.v3.contracts.authorization import (
    CapitalAuthorizationEnvelope,
)
from src.screening.offensive.v3.contracts.governance import (
    EntryFenceAcknowledgement,
    EntryFenceRaised,
    PolicyActivation,
    TrustBundle,
)

_SCHEMA_DDL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS trust_activations (
        trust_bundle_hash TEXT PRIMARY KEY,
        registry_epoch INTEGER NOT NULL,
        activated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS policy_activations (
        policy_activation_hash TEXT PRIMARY KEY,
        policy_epoch INTEGER NOT NULL,
        authority_epoch INTEGER NOT NULL,
        mode TEXT NOT NULL,
        broker_account_id TEXT,
        activated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS envelope_registry (
        authorization_id TEXT PRIMARY KEY,
        portfolio_id TEXT NOT NULL,
        authorization_version INTEGER NOT NULL,
        envelope_hash TEXT NOT NULL,
        policy_activation_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        activated_at TEXT NOT NULL,
        status_changed_at TEXT
    )
    """,
    """
    -- One active envelope per portfolio, enforced at the database level so
    -- concurrent replace/activate cannot both win a read-then-write CAS.
    CREATE UNIQUE INDEX IF NOT EXISTS uq_active_envelope_per_portfolio
        ON envelope_registry (portfolio_id) WHERE status = 'ACTIVE'
    """,
    """
    CREATE TABLE IF NOT EXISTS entry_fences (
        fence_id TEXT PRIMARY KEY,
        portfolio_id TEXT NOT NULL,
        fence_version INTEGER NOT NULL,
        fence_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        raised_at TEXT NOT NULL,
        acknowledged_at TEXT,
        acknowledgement_hash TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS authority_counters (
        portfolio_id TEXT PRIMARY KEY,
        fencing_epoch INTEGER NOT NULL DEFAULT 0,
        authorization_status_version INTEGER NOT NULL DEFAULT 0
    )
    """,
)


class GatewayAuthorityError(RuntimeError):
    """Fail-closed rejection of a gateway authority operation."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class ActiveAuthorityState:
    """Read-only projection of one portfolio's authority state."""

    portfolio_id: str
    active_authorization_id: str | None
    active_authorization_version: int | None
    active_envelope_hash: str | None
    policy_activation_hash: str | None
    fencing_epoch: int
    authorization_status_version: int
    open_fence_count: int


class TrustBundleVerifierProtocol:
    """Verifies one signed trust bundle against the root chain."""

    def verify_signed_bundle(
        self, signed: SignedEnvelope, *, trusted_at: datetime
    ) -> TrustBundle:
        raise NotImplementedError


class GatewayAuthorityRepository:
    """Monotonic CAS authority store for one gateway writer."""

    def __init__(
        self,
        *,
        database_path: str,
        mode: ExecutionMode,
        broker_account_id: str | None,
        bundle_verifier: TrustBundleVerifierProtocol,
        clock: Callable[[], datetime],
    ) -> None:
        self._mode = mode
        self._broker_account_id = broker_account_id
        self._bundle_verifier = bundle_verifier
        self._clock = clock
        self._engine = sa.create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        sa.event.listen(self._engine, "connect", _configure_connection)
        with self._engine.begin() as conn:
            for ddl in _SCHEMA_DDL:
                conn.execute(sa.text(ddl))

    # -- trust bundle activation -------------------------------------------

    def activate_trust_bundle(
        self, signed_bundle: SignedEnvelope, *, trusted_at: datetime
    ) -> TrustBundle:
        """Verify and activate one trust bundle; epochs never roll back."""

        bundle = self._bundle_verifier.verify_signed_bundle(
            signed_bundle, trusted_at=trusted_at
        )
        with self._engine.begin() as conn:
            current_epoch = self._max_registry_epoch(conn)
            if bundle.registry_epoch <= current_epoch:
                raise GatewayAuthorityError(
                    "registry_epoch_rollback",
                    "trust bundle epoch cannot move backwards or repeat",
                    current_epoch=current_epoch,
                    bundle_epoch=bundle.registry_epoch,
                )
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO trust_activations (trust_bundle_hash,"
                        " registry_epoch, activated_at)"
                        " VALUES (:hash, :epoch, :activated_at)"
                    ),
                    {
                        "hash": bundle.artifact_hash(),
                        "epoch": bundle.registry_epoch,
                        "activated_at": self._clock().isoformat(),
                    },
                )
            except sa.exc.IntegrityError as exc:
                raise GatewayAuthorityError(
                    "trust_bundle_already_active",
                    "trust bundle hash already activated",
                ) from exc
        return bundle

    def _max_registry_epoch(self, conn: sa.engine.Connection) -> int:
        row = conn.execute(
            sa.text(
                "SELECT COALESCE(MAX(registry_epoch), 0) AS epoch"
                " FROM trust_activations"
            )
        ).one()
        return int(row.epoch)

    # -- joint policy + envelope activation --------------------------------

    def activate_policy_and_envelope(
        self,
        policy_activation: PolicyActivation,
        envelope: CapitalAuthorizationEnvelope,
        *,
        expected_policy_epoch: int | None = None,
    ) -> None:
        """Activate one behavior policy together with its envelope.

        One transaction owns both rows; the policy activation hash the
        envelope claims must bind the policy artifact exactly, epochs must
        advance, and the account/mode must match this gateway writer.
        """

        if envelope.policy_activation_hash != (
            policy_activation.artifact_hash()
        ):
            raise GatewayAuthorityError(
                "policy_envelope_fingerprint_mismatch",
                "envelope does not bind this policy activation",
            )
        self._require_account_mode(policy_activation.mode)
        self._require_account_mode(envelope.mode)
        with self._engine.begin() as conn:
            current_policy_epoch, current_authority_epoch = (
                self._current_policy_epochs(conn)
            )
            if expected_policy_epoch is not None and (
                current_policy_epoch != expected_policy_epoch
            ):
                raise GatewayAuthorityError(
                    "policy_epoch_cas_conflict",
                    "policy epoch moved between read and activation",
                    expected=expected_policy_epoch,
                    current=current_policy_epoch,
                )
            if policy_activation.policy_epoch <= current_policy_epoch:
                raise GatewayAuthorityError(
                    "policy_epoch_rollback",
                    "policy epoch cannot move backwards or repeat",
                )
            if policy_activation.authority_epoch <= current_authority_epoch:
                raise GatewayAuthorityError(
                    "authority_epoch_rollback",
                    "authority epoch cannot move backwards or repeat",
                )
            active = self._active_envelope_row(
                conn, envelope.portfolio_id
            )
            if active is not None:
                raise GatewayAuthorityError(
                    "envelope_already_active",
                    "one portfolio holds at most one active envelope;"
                    " replacement must use replace_envelope",
                )
            now = self._clock().isoformat()
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO policy_activations ("
                        " policy_activation_hash, policy_epoch,"
                        " authority_epoch, mode, broker_account_id,"
                        " activated_at) VALUES (:hash, :policy_epoch,"
                        " :authority_epoch, :mode, :account, :activated_at)"
                    ),
                    {
                        "hash": policy_activation.artifact_hash(),
                        "policy_epoch": policy_activation.policy_epoch,
                        "authority_epoch": (
                            policy_activation.authority_epoch
                        ),
                        "mode": policy_activation.mode.value,
                        "account": self._broker_account_id,
                        "activated_at": now,
                    },
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO envelope_registry ("
                        " authorization_id, portfolio_id,"
                        " authorization_version, envelope_hash,"
                        " policy_activation_hash, status, activated_at)"
                        " VALUES (:auth_id, :portfolio, :version, :hash,"
                        " :policy_hash, 'ACTIVE', :activated_at)"
                    ),
                    {
                        "auth_id": envelope.authorization_id,
                        "portfolio": envelope.portfolio_id,
                        "version": envelope.authorization_version,
                        "hash": envelope.artifact_hash(),
                        "policy_hash": policy_activation.artifact_hash(),
                        "activated_at": now,
                    },
                )
            except sa.exc.IntegrityError as exc:
                raise GatewayAuthorityError(
                    "activation_conflict",
                    "policy or envelope identity already activated",
                ) from exc
            self._bump_status_version(conn, envelope.portfolio_id)

    def _current_policy_epochs(
        self, conn: sa.engine.Connection
    ) -> tuple[int, int]:
        row = conn.execute(
            sa.text(
                "SELECT COALESCE(MAX(policy_epoch), 0) AS policy_epoch,"
                " COALESCE(MAX(authority_epoch), 0) AS authority_epoch"
                " FROM policy_activations"
            )
        ).one()
        return int(row.policy_epoch), int(row.authority_epoch)

    def _require_account_mode(self, mode: ExecutionMode) -> None:
        if mode is not self._mode:
            raise GatewayAuthorityError(
                "mode_mismatch",
                "activation mode differs from the gateway writer mode",
            )

    def _active_envelope_row(
        self, conn: sa.engine.Connection, portfolio_id: str
    ):
        return conn.execute(
            sa.text(
                "SELECT * FROM envelope_registry"
                " WHERE portfolio_id = :portfolio AND status = 'ACTIVE'"
            ),
            {"portfolio": portfolio_id},
        ).first()

    def _bump_status_version(
        self, conn: sa.engine.Connection, portfolio_id: str
    ) -> None:
        conn.execute(
            sa.text(
                "INSERT INTO authority_counters (portfolio_id,"
                " fencing_epoch, authorization_status_version)"
                " VALUES (:portfolio, 0, 1)"
                " ON CONFLICT(portfolio_id) DO UPDATE SET"
                " authorization_status_version ="
                " authorization_status_version + 1"
            ),
            {"portfolio": portfolio_id},
        )

    # -- envelope replacement ----------------------------------------------

    def replace_envelope(
        self,
        current_envelope: CapitalAuthorizationEnvelope,
        new_envelope: CapitalAuthorizationEnvelope,
        *,
        policy_activation: PolicyActivation | None = None,
    ) -> None:
        """Replace the active envelope under CAS.

        A PURE tightening (grant subset, caps never increased, no new
        behavior/execution/cost identity) may replace alone; any behavior
        change requires the joint policy activation path.
        """

        with self._engine.begin() as conn:
            active = self._active_envelope_row(
                conn, current_envelope.portfolio_id
            )
            if active is None:
                raise GatewayAuthorityError(
                    "no_active_envelope",
                    "replacement requires an active envelope",
                )
            if str(active.envelope_hash) != (
                current_envelope.artifact_hash()
            ):
                raise GatewayAuthorityError(
                    "envelope_cas_conflict",
                    "current envelope hash does not match the registry;"
                    " another replacement landed first",
                )
            if int(active.authorization_version) != (
                current_envelope.authorization_version
            ):
                raise GatewayAuthorityError(
                    "envelope_cas_conflict",
                    "current envelope version does not match the registry",
                )
            if new_envelope.portfolio_id != (
                current_envelope.portfolio_id
            ):
                raise GatewayAuthorityError(
                    "envelope_portfolio_mismatch",
                    "replacement must target the same portfolio",
                )
            if new_envelope.authorization_version != (
                current_envelope.authorization_version + 1
            ):
                raise GatewayAuthorityError(
                    "envelope_version_not_successor",
                    "replacement version must be the exact successor",
                )
            tightening = is_pure_tightening(current_envelope, new_envelope)
            if not tightening and policy_activation is None:
                raise GatewayAuthorityError(
                    "behavior_change_requires_joint_activation",
                    "non-tightening replacement must activate a new policy"
                    " jointly",
                )
            if not tightening and policy_activation is not None:
                if new_envelope.policy_activation_hash != (
                    policy_activation.artifact_hash()
                ):
                    raise GatewayAuthorityError(
                        "policy_envelope_fingerprint_mismatch",
                        "replacement envelope does not bind the new policy",
                    )
            now = self._clock().isoformat()
            superseded = conn.execute(
                sa.text(
                    "UPDATE envelope_registry SET status = 'SUPERSEDED',"
                    " status_changed_at = :now"
                    " WHERE authorization_id = :auth_id AND status ="
                    " 'ACTIVE'"
                ),
                {
                    "now": now,
                    "auth_id": current_envelope.authorization_id,
                },
            )
            if superseded.rowcount != 1:
                # The read-then-write CAS lost: another writer already moved
                # this envelope (or a unique index already carries the active
                # row). Fail closed - never activate a second ACTIVE row.
                raise GatewayAuthorityError(
                    "envelope_cas_conflict",
                    "active envelope changed before replacement",
                )
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO envelope_registry ("
                        " authorization_id, portfolio_id,"
                        " authorization_version, envelope_hash,"
                        " policy_activation_hash, status, activated_at)"
                        " VALUES (:auth_id, :portfolio, :version, :hash,"
                        " :policy_hash, 'ACTIVE', :activated_at)"
                    ),
                    {
                        "auth_id": new_envelope.authorization_id,
                        "portfolio": new_envelope.portfolio_id,
                        "version": new_envelope.authorization_version,
                        "hash": new_envelope.artifact_hash(),
                        "policy_hash": (
                            new_envelope.policy_activation_hash
                        ),
                        "activated_at": now,
                    },
                )
            except sa.exc.IntegrityError as exc:
                raise GatewayAuthorityError(
                    "activation_conflict",
                    "replacement envelope identity already exists",
                ) from exc
            self._bump_status_version(conn, new_envelope.portfolio_id)

    # -- entry fences --------------------------------------------------------

    def raise_entry_fence(self, fence: EntryFenceRaised) -> None:
        """Persist one entry fence idempotently and fence the portfolio.

        The active envelope becomes FENCED (unclaimed entries are
        tombstoned for new seals); exits are never affected by entry
        fences.
        """

        with self._engine.begin() as conn:
            existing = conn.execute(
                sa.text(
                    "SELECT * FROM entry_fences WHERE fence_id = :fence"
                ),
                {"fence": fence.fence_id},
            ).first()
            if existing is not None:
                if int(existing.fence_version) != fence.fence_version or (
                    str(existing.fence_hash) != fence.artifact_hash()
                ):
                    raise GatewayAuthorityError(
                        "fence_identity_conflict",
                        "fence id already raised with different content",
                    )
                return  # idempotent identical retry
            conn.execute(
                sa.text(
                    "INSERT INTO entry_fences (fence_id, portfolio_id,"
                    " fence_version, fence_hash, status, raised_at)"
                    " VALUES (:fence, :portfolio, :version, :hash,"
                    " 'RAISED', :raised_at)"
                ),
                {
                    "fence": fence.fence_id,
                    "portfolio": fence.portfolio_id,
                    "version": fence.fence_version,
                    "hash": fence.artifact_hash(),
                    "raised_at": fence.raised_at.isoformat(),
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO authority_counters (portfolio_id,"
                    " fencing_epoch, authorization_status_version)"
                    " VALUES (:portfolio, 1, 1)"
                    " ON CONFLICT(portfolio_id) DO UPDATE SET"
                    " fencing_epoch = fencing_epoch + 1,"
                    " authorization_status_version ="
                    " authorization_status_version + 1"
                ),
                {"portfolio": fence.portfolio_id},
            )
            # Tombstone unclaimed entries: the active envelope becomes
            # FENCED; no new seal may issue while any fence is open.
            conn.execute(
                sa.text(
                    "UPDATE envelope_registry SET status = 'FENCED',"
                    " status_changed_at = :now"
                    " WHERE portfolio_id = :portfolio AND status ="
                    " 'ACTIVE'"
                ),
                {
                    "now": fence.raised_at.isoformat(),
                    "portfolio": fence.portfolio_id,
                },
            )

    def acknowledge_fence(self, ack: EntryFenceAcknowledgement) -> None:
        """Durably acknowledge one committed fence.

        ACKs only land after the fence row is committed; an ACK for an
        unknown fence fails closed and writes nothing.
        """

        with self._engine.begin() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT * FROM entry_fences WHERE fence_id = :fence"
                ),
                {"fence": ack.fence_id},
            ).first()
            if row is None:
                raise GatewayAuthorityError(
                    "fence_unknown",
                    "cannot acknowledge an uncommitted fence",
                )
            if str(row.fence_hash) != ack.entry_fence_hash:
                raise GatewayAuthorityError(
                    "fence_hash_mismatch",
                    "acknowledgement does not bind the committed fence",
                )
            if str(row.status) == "ACKNOWLEDGED":
                if str(row.acknowledgement_hash) != ack.artifact_hash():
                    raise GatewayAuthorityError(
                        "fence_ack_conflict",
                        "fence already acknowledged with different"
                        " content",
                    )
                return  # idempotent identical retry
            conn.execute(
                sa.text(
                    "UPDATE entry_fences SET status = 'ACKNOWLEDGED',"
                    " acknowledged_at = :ack_at, acknowledgement_hash ="
                    " :ack_hash WHERE fence_id = :fence"
                ),
                {
                    "ack_at": ack.durably_acknowledged_at.isoformat(),
                    "ack_hash": ack.artifact_hash(),
                    "fence": ack.fence_id,
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO authority_counters (portfolio_id,"
                    " fencing_epoch, authorization_status_version)"
                    " VALUES (:portfolio, 0, 1)"
                    " ON CONFLICT(portfolio_id) DO UPDATE SET"
                    " authorization_status_version ="
                    " authorization_status_version + 1"
                ),
                {"portfolio": ack.portfolio_id},
            )

    # -- read-only projection -------------------------------------------------

    def active_state(self, portfolio_id: str) -> ActiveAuthorityState:
        with self._engine.connect() as conn:
            active = self._active_envelope_row(conn, portfolio_id)
            counters = conn.execute(
                sa.text(
                    "SELECT fencing_epoch, authorization_status_version"
                    " FROM authority_counters WHERE portfolio_id ="
                    " :portfolio"
                ),
                {"portfolio": portfolio_id},
            ).first()
            open_fences = conn.execute(
                sa.text(
                    "SELECT COUNT(*) AS n FROM entry_fences"
                    " WHERE portfolio_id = :portfolio AND status ="
                    " 'RAISED'"
                ),
                {"portfolio": portfolio_id},
            ).one()
        return ActiveAuthorityState(
            portfolio_id=portfolio_id,
            active_authorization_id=(
                str(active.authorization_id) if active is not None else None
            ),
            active_authorization_version=(
                int(active.authorization_version)
                if active is not None
                else None
            ),
            active_envelope_hash=(
                str(active.envelope_hash) if active is not None else None
            ),
            policy_activation_hash=(
                str(active.policy_activation_hash)
                if active is not None
                else None
            ),
            fencing_epoch=(
                int(counters.fencing_epoch) if counters is not None else 0
            ),
            authorization_status_version=(
                int(counters.authorization_status_version)
                if counters is not None
                else 0
            ),
            open_fence_count=int(open_fences.n),
        )


def is_pure_tightening(
    old: CapitalAuthorizationEnvelope,
    new: CapitalAuthorizationEnvelope,
) -> bool:
    """Mechanical pure-tightening check: no new behavior, quantity, window
    or cap; every new grant matches an old grant with tightened bounds."""

    if new.target_portfolio_policy_fingerprint != (
        old.target_portfolio_policy_fingerprint
    ) or new.baseline_portfolio_policy_fingerprint != (
        old.baseline_portfolio_policy_fingerprint
    ):
        return False
    if new.portfolio_gross_cap > old.portfolio_gross_cap:
        return False
    if new.exploration_aggregate_gross_cap > (
        old.exploration_aggregate_gross_cap
    ):
        return False
    old_grants = {
        grant.grant_certificate_hash: grant for grant in old.lineage_grants
    }
    new_ids = set()
    for grant in new.lineage_grants:
        if grant.grant_certificate_hash in new_ids:
            return False
        new_ids.add(grant.grant_certificate_hash)
        old_grant = old_grants.get(grant.grant_certificate_hash)
        if old_grant is None:
            return False  # new grant = new behavior
        if (
            grant.behavior_fingerprint != old_grant.behavior_fingerprint
            or grant.execution_version != old_grant.execution_version
            or grant.cost_version != old_grant.cost_version
        ):
            return False
        if grant.capital_tier > old_grant.capital_tier:
            return False
        if grant.lineage_gross_cap > old_grant.lineage_gross_cap:
            return False
    return True


def _configure_connection(dbapi_connection: object, _record: object) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
    dbapi_connection.execute("PRAGMA busy_timeout=15000")


__all__ = [
    "ActiveAuthorityState",
    "GatewayAuthorityError",
    "GatewayAuthorityRepository",
    "TrustBundleVerifierProtocol",
    "is_pure_tightening",
]
