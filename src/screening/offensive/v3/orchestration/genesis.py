"""Plan Task 6: equal-genesis seal for the two trial arms.

Two arm ledgers must start from byte-identical normalized economic state
(cash, units, positions, lots, reserves, pending exits, receivables/payables,
risk state, watermarks, stream/capital versions, unresolved proxy phases)
before a paired trial may enroll. ``TrialArmGenesisSource.normalized_state()``
projects one arm's capital ledger (plus the optional exit lane and proxy-state
reader) into ``NormalizedTrialArmState``, excluding only the arm/portfolio
identity. ``TrialGenesisArchive.seal()`` captures a consistent SQLite backup of
each capital ledger under a content-addressed trial directory, recomputes the
roots, binds both backups plus one equal normalized hash into an immutable
``TrialGenesisManifest``, and rejects any economic difference before
enrollment. Sealing is exact-idempotent; ``restore_genesis_arm()`` verifies the
content root and restores a fresh, normalized-hash-equal ledger.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.contracts.base import CanonicalModel
from src.screening.offensive.v3.contracts.capital import (
    CapitalPositionRisk,
    CapitalRiskSnapshot,
    RiskExposureBucket,
)
from src.screening.offensive.v3.gateway.exits import ExitLane
from src.screening.offensive.v3.orchestration.path_guards import (
    require_safe_segment,
    walk_components,
)

SCHEMA_MAJOR = 2

_IDENTITY_EXCLUDED = "identity-excluded"
_ZERO_HASH = "0" * 64


def _genesis_fail(code: str, detail: str, **_details: object) -> Exception:
    """path_guards 守卫错误 → TrialGenesisError (两参签名的族适配)。"""
    return TrialGenesisError(code, detail)
#: Fixed observation window for the normalized snapshot. The two arm reads
#: happen at slightly different wall-clock instants; the as-of window is
#: identity, not economics, so it normalizes to one canonical window.
_SENTINEL_AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)
_SENTINEL_VALID_UNTIL = datetime(2026, 1, 2, tzinfo=timezone.utc)


class TrialGenesisError(ValueError):
    """A paired genesis seal or restore failed a frozen invariant."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


class NormalizedTrialArmState(CanonicalModel):
    """One arm's complete economic state with arm/portfolio identity excluded.

    Everything that moves capital truth is retained: cash/units/positions/
    reserves/receivables/payables, risk state, watermarks, stream and capital
    versions, pending exit obligations and unresolved proxy phases. The
    portfolio identity and any arm-derived identity/authority fields are
    excluded, so two arm ledgers with identical economics hash equal
    regardless of which arm each ledger serves.
    """

    # capital ledger truth (identity-excluded)
    capital_snapshot: CapitalRiskSnapshot
    # pending exit obligations carry economic truth and must match across arms
    pending_exits: tuple[tuple[tuple[str, str], date, str, int, int], ...] = ()
    # live exit leases (unreleased) carry scheduler truth across arms
    live_exit_leases: tuple[tuple[tuple[str, str], str, str], ...] = ()
    # submitted exit attempts carry durable quantity truth across arms
    exit_attempts: tuple[tuple[tuple[str, str], str, int, int, int, int], ...] = ()
    # open exit reconciliations carry unresolved truth across arms
    open_exit_reconciliations: tuple[tuple[tuple[str, str], str], ...] = ()
    # unresolved proxy phases must match across arms before enrollment
    unresolved_proxy_phases: tuple[tuple[str, str, str], ...] = ()

    def content_hash(self) -> str:
        return super().content_hash()


def normalized_trial_arm_state(source: "TrialArmGenesisSource") -> NormalizedTrialArmState:
    """Project one arm into ``NormalizedTrialArmState``.

    The projection excludes only arm/portfolio identity: the risk snapshot's
    derived identity and authority fields (snapshot id, portfolio id,
    authorization, epochs, policy binding, observation window) are stripped.
    All economic fields survive; pending exit obligations and unresolved
    proxy phases are appended.
    """

    snapshot = source._capital_repository.capital_risk_snapshot(
        datetime.now(timezone.utc)
    )
    return NormalizedTrialArmState(
        capital_snapshot=_strip_identity(snapshot),
        pending_exits=source._exit_lane.pending_exit_rows(),
        live_exit_leases=source._exit_lane.live_exit_leases(),
        exit_attempts=source._exit_lane.exit_attempts(),
        open_exit_reconciliations=source._exit_lane.open_exit_reconciliations(),
        unresolved_proxy_phases=source._proxy_state_reader.unresolved_phases(),
    )


def _strip_identity(snapshot: CapitalRiskSnapshot) -> CapitalRiskSnapshot:
    return snapshot.model_copy(
        update={
            "risk_snapshot_id": _ZERO_HASH,
            "portfolio_id": _IDENTITY_EXCLUDED,
            "authorization_id": _IDENTITY_EXCLUDED,
            "policy_activation_hash": _ZERO_HASH,
            "as_of": _SENTINEL_AS_OF,
            "valid_until": _SENTINEL_VALID_UNTIL,
            "exposures": _strip_bucket_identity(snapshot.exposures),
            "positions": _strip_position_identity(snapshot.positions),
        }
    )


def _strip_bucket_identity(
    buckets: tuple[RiskExposureBucket, ...],
) -> tuple[RiskExposureBucket, ...]:
    stripped: list[RiskExposureBucket] = []
    for bucket in buckets:
        if bucket.portfolio_id is not None:
            bucket = bucket.model_copy(update={"portfolio_id": _IDENTITY_EXCLUDED})
        stripped.append(bucket)
    return tuple(stripped)


def _strip_position_identity(
    positions: tuple[CapitalPositionRisk, ...],
) -> tuple[CapitalPositionRisk, ...]:
    return tuple(
        position.model_copy(update={"portfolio_id": _IDENTITY_EXCLUDED})
        for position in positions
    )


class TrialGenesisManifest(CanonicalModel):
    """The sealed, immutable genesis record for one paired trial.

    ``normalized_genesis_hash`` is the one equal normalized full-state hash
    binding both arms; each arm's backup is separately content-addressed.
    """

    trial_id: str
    normalized_genesis_hash: str
    champion_normalized_hash: str
    challenger_normalized_hash: str
    champion_backup_root: str
    challenger_backup_root: str
    champion_exit_lane_root: str | None = None
    challenger_exit_lane_root: str | None = None
    champion_proxy_root: str | None = None
    challenger_proxy_root: str | None = None
    trial_manifest_hash: str
    sap_manifest_hash: str
    sealed_at: datetime
    schema_major: int = SCHEMA_MAJOR

    def content_hash(self) -> str:
        return super().content_hash()


class TrialArmGenesisSource:
    """One arm's genesis truth: capital ledger + optional exit lane/proxy store."""

    def __init__(
        self,
        capital_repository: CapitalRepository,
        exit_lane: ExitLane | None = None,
        proxy_state_reader: object | None = None,
        portfolio_id: str | None = None,
    ) -> None:
        self._capital_repository = capital_repository
        self._exit_lane = _ExitLaneReader(exit_lane)
        self._proxy_state_reader = _ProxyStateReader(proxy_state_reader)
        self._portfolio_id = portfolio_id

    @property
    def portfolio_id(self) -> str | None:
        return self._portfolio_id

    def normalized_state(self) -> NormalizedTrialArmState:
        return normalized_trial_arm_state(self)

    def capital_repository(self) -> CapitalRepository:
        return self._capital_repository

    def backup_capital(self, destination: Path) -> str:
        manifest = self._capital_repository.backup_consistent(destination)
        return manifest.content_root

    def backup_exit_lane(self, destination: Path) -> str | None:
        if self._exit_lane._lane is None:
            return None
        self._exit_lane.export_backup(destination)
        return hashlib.sha256(destination.read_bytes()).hexdigest()

    def backup_proxy_state(self, destination: Path) -> str | None:
        if self._proxy_state_reader._reader is None:
            return None
        self._proxy_state_reader.export_backup(destination)
        if destination.is_file():
            return hashlib.sha256(destination.read_bytes()).hexdigest()
        return None


class _ExitLaneReader:
    """Protocol-shaped reader over a live ExitLane (or None)."""

    def __init__(self, lane: ExitLane | None) -> None:
        self._lane = lane

    def pending_exit_rows(
        self,
    ) -> tuple[tuple[tuple[str, str], date, str, int, int], ...]:
        if self._lane is None:
            return ()
        import sqlalchemy as sa

        with self._lane._engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT position_lineage_id, economic_lot_id, due_session,"
                    " security_id, tradable_quantity, live_exit_leaves"
                    " FROM exit_mandates"
                    " WHERE status != 'SUPERSEDED'"
                    " ORDER BY position_lineage_id, economic_lot_id"
                )
            ).fetchall()
        return tuple(
            (
                (row[0], row[1]),
                date.fromisoformat(row[2]),
                row[3],
                int(row[4]),
                int(row[5]),
            )
            for row in rows
        )

    def live_exit_leases(
        self,
    ) -> tuple[tuple[tuple[str, str], str, str], ...]:
        """Unreleased leases: lot identity, leased_at, expires_at.

        The worker/lease ids are scheduler identity, not economics; the
        existence and window of a live lease is the truth that must match
        across arms.
        """

        if self._lane is None:
            return ()
        import sqlalchemy as sa

        with self._lane._engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT m.position_lineage_id, m.economic_lot_id,"
                    " l.leased_at, l.expires_at"
                    " FROM exit_leases l"
                    " JOIN exit_mandates m ON m.mandate_hash = l.mandate_hash"
                    " WHERE l.released_at IS NULL"
                    " ORDER BY m.position_lineage_id, m.economic_lot_id,"
                    " l.leased_at"
                )
            ).fetchall()
        return tuple(
            (
                (row[0], row[1]),
                row[2],
                row[3],
            )
            for row in rows
        )

    def exit_attempts(
        self,
    ) -> tuple[tuple[tuple[str, str], str, int, int, int, int], ...]:
        """Submitted exit work: lot identity + the durable quantity facts.

        The attempt/order ids are dispatch identity, not economics; the
        submitted/filled/cancelled quantities are the truth that must match.
        """

        if self._lane is None:
            return ()
        import sqlalchemy as sa

        with self._lane._engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT m.position_lineage_id, m.economic_lot_id,"
                    " a.submitted_leaves, a.filled_quantity,"
                    " a.late_filled_quantity, a.cancelled_quantity"
                    " FROM exit_attempts a"
                    " JOIN exit_mandates m ON m.mandate_hash = a.mandate_hash"
                    " ORDER BY m.position_lineage_id, m.economic_lot_id,"
                    " a.recorded_at"
                )
            ).fetchall()
        return tuple(
            (
                (row[0], row[1]),
                row[2],
                int(row[3]),
                int(row[4]),
                int(row[5]),
                int(row[6]),
            )
            for row in rows
        )

    def open_exit_reconciliations(
        self,
    ) -> tuple[tuple[tuple[str, str], str], ...]:
        if self._lane is None:
            return ()
        import sqlalchemy as sa

        with self._lane._engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT position_lineage_id, economic_lot_id, reason"
                    " FROM exit_reconciliations"
                    " WHERE resolved_at IS NULL"
                    " ORDER BY position_lineage_id, economic_lot_id,"
                    " scheduled_at"
                )
            ).fetchall()
        return tuple(
            ((row[0], row[1]), row[2])
            for row in rows
        )

    def export_backup(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(str(self._lane._database_path))
        try:
            target = sqlite3.connect(str(destination))
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()


class _ProxyStateReader:
    """Protocol-shaped reader over a proxy-state store (or None)."""

    def __init__(self, proxy_state_reader: object | None) -> None:
        self._reader = proxy_state_reader

    def unresolved_phases(self) -> tuple[tuple[str, str, str], ...]:
        if self._reader is None:
            return ()
        if not hasattr(self._reader, "unresolved_phases"):
            return ()
        result = self._reader.unresolved_phases()
        return tuple(tuple(phase) for phase in result)

    def export_backup(self, destination: Path) -> None:
        if self._reader is None:
            return
        if hasattr(self._reader, "export_backup"):
            self._reader.export_backup(destination)


class TrialGenesisArchive:
    """Content-addressed immutable store for paired genesis backups.

    Layout: ``{root}/{trial_id}/{content_root}/capital.sqlite3`` — the
    content root addresses the backup bytes, so a sealed backup is immutable
    and any byte drift is detected on read.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def seal(
        self,
        trial_id: str,
        champion_source: TrialArmGenesisSource,
        challenger_source: TrialArmGenesisSource,
    ) -> TrialGenesisManifest:
        # 拼任何路径前拒绝非法 trial_id (2026-08-21 对抗性审查: 此前
        # driver 侧有 _TRIAL_ID_RE 而本类裸拼 root/<trial_id>/...)。
        require_safe_segment(trial_id, field="trial_id", fail=_genesis_fail)
        champion_state = champion_source.normalized_state()
        challenger_state = challenger_source.normalized_state()
        if champion_state != challenger_state:
            raise TrialGenesisError(
                "genesis_economic_state_mismatch",
                "the two arms must start from identical normalized economic state",
            )
        normalized_hash = champion_state.content_hash()
        existing = self._find_existing_seal(trial_id)
        if existing is not None:
            if (
                existing.normalized_genesis_hash == normalized_hash
                and existing.champion_normalized_hash == champion_state.content_hash()
                and existing.challenger_normalized_hash == challenger_state.content_hash()
            ):
                # Exact idempotent replay: the same trial over the same
                # normalized state returns the already-sealed manifest.
                return existing
            raise TrialGenesisError(
                "genesis_conflict",
                "this trial already sealed a different genesis;"
                " the archive is immutable",
            )
        # Conservation/rebuild drift in either arm fails the seal closed: a
        # ledger whose projections cannot be recomputed from its event stream
        # (or whose watermark contradicts confirmed NAV history) must never
        # enroll a paired trial.
        for label, source in (
            ("champion", champion_source),
            ("challenger", challenger_source),
        ):
            repository = source._capital_repository
            rebuild_ok, details = repository.rebuild_projections()
            if not rebuild_ok:
                raise TrialGenesisError(
                    "genesis_ledger_verification_failed",
                    f"the {label} arm ledger failed conservation/rebuild"
                    f" verification: {'; '.join(details)}",
                )
        champion_root = champion_source.backup_capital(
            self._staging_path(trial_id, "champion")
        )
        challenger_root = challenger_source.backup_capital(
            self._staging_path(trial_id, "challenger")
        )
        # Move each backup under its content root once the bytes are known.
        self._finalize_backup(trial_id, "champion", champion_root)
        self._finalize_backup(trial_id, "challenger", challenger_root)
        champion_exit_root = champion_source.backup_exit_lane(
            self._exit_backup_path(trial_id, "champion")
        )
        challenger_exit_root = challenger_source.backup_exit_lane(
            self._exit_backup_path(trial_id, "challenger")
        )
        champion_proxy_root = champion_source.backup_proxy_state(
            self._proxy_backup_path(trial_id, "champion")
        )
        challenger_proxy_root = challenger_source.backup_proxy_state(
            self._proxy_backup_path(trial_id, "challenger")
        )
        manifest = TrialGenesisManifest(
            trial_id=trial_id,
            normalized_genesis_hash=normalized_hash,
            champion_normalized_hash=champion_state.content_hash(),
            challenger_normalized_hash=challenger_state.content_hash(),
            champion_backup_root=champion_root,
            challenger_backup_root=challenger_root,
            champion_exit_lane_root=champion_exit_root,
            challenger_exit_lane_root=challenger_exit_root,
            champion_proxy_root=champion_proxy_root,
            challenger_proxy_root=challenger_proxy_root,
            trial_manifest_hash=_ZERO_HASH,
            sap_manifest_hash=_ZERO_HASH,
            sealed_at=datetime.now(timezone.utc),
        )
        (self._root / trial_id / "genesis-manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        return manifest

    def _staging_path(self, trial_id: str, arm: str) -> Path:
        return self._root / trial_id / f".staging-{arm}.sqlite3"

    def _finalize_backup(self, trial_id: str, arm: str, root: str) -> Path:
        staging = self._staging_path(trial_id, arm)
        final = self._capital_backup_path(trial_id, arm, root)
        final.parent.mkdir(parents=True, exist_ok=True)
        staging.replace(final)
        # ``backup_consistent`` writes a sibling ``.manifest.json`` next to
        # the staging name; it is a seal-time artifact, not part of the
        # content-addressed archive, so remove it after the move.
        sibling = staging.with_name(staging.name + ".manifest.json")
        if sibling.is_file():
            sibling.unlink()
        return final

    def _capital_backup_path(self, trial_id: str, arm: str, root: str) -> Path:
        return self._root / trial_id / root / "capital.sqlite3"

    def _exit_backup_path(self, trial_id: str, arm: str) -> Path:
        return self._root / trial_id / f"exit-lane-{arm}.sqlite3"

    def _proxy_backup_path(self, trial_id: str, arm: str) -> Path:
        return self._root / trial_id / f"proxy-{arm}.sqlite3"

    def _find_existing_seal(self, trial_id: str) -> TrialGenesisManifest | None:
        manifest_path = self._root / trial_id / "genesis-manifest.json"
        if not manifest_path.is_file():
            return None
        manifest = TrialGenesisManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8"), strict=True
        )
        # Recompute the sealed backups' roots: any byte drift breaks the
        # content-addressed binding and fails closed.
        for arm, root_field in (
            ("champion", "champion_backup_root"),
            ("challenger", "challenger_backup_root"),
        ):
            backup_path = self._capital_backup_path(
                trial_id, arm, getattr(manifest, root_field)
            )
            if not backup_path.is_file():
                raise TrialGenesisError(
                    "archive_missing_backup",
                    f"the sealed trial archive lost the {arm} capital backup",
                )
            actual = hashlib.sha256(backup_path.read_bytes()).hexdigest()
            if actual != getattr(manifest, root_field):
                raise TrialGenesisError(
                    "content_root",
                    f"the sealed {arm} capital backup no longer hashes to its"
                    " manifest root",
                )
        return manifest

    def manifest(self, trial_id: str) -> TrialGenesisManifest:
        sealed = self._find_existing_seal(trial_id)
        if sealed is None:
            raise TrialGenesisError(
                "trial_not_sealed",
                f"no genesis seal exists for trial {trial_id}",
            )
        return sealed

    @property
    def root(self) -> Path:
        return self._root


def restore_genesis_arm(
    manifest: TrialGenesisManifest,
    archive_root: str | Path,
    new_path: str | Path,
    *,
    arm: str,
) -> CapitalRepository:
    """Restore one verified genesis backup to a fresh ledger path.

    The backup bytes must hash to the manifest's arm root before any trust is
    granted; the restored store must then reproduce the same normalized
    genesis hash.
    """

    if arm not in ("CHAMPION", "CHALLENGER"):
        raise TrialGenesisError("unknown_arm", f"unknown genesis arm: {arm}")
    root = (
        manifest.champion_backup_root
        if arm == "CHAMPION"
        else manifest.challenger_backup_root
    )
    # 路径纵深 (2026-08-21 对抗性审查): 内容哈希绑定的是字节, 不是路径 —
    # symlink 预置可让 read_bytes 发生在 archive root 之外。读取前对全部
    # 组件逐级 lstat 拒 symlink/穿越; backup root 本身是内容哈希段, 同样
    # 走形状校验。
    require_safe_segment(manifest.trial_id, field="trial_id", fail=_genesis_fail)
    require_safe_segment(root, field="backup_root", fail=_genesis_fail)
    backup_path = Path(archive_root) / manifest.trial_id / root / "capital.sqlite3"
    walk_components(
        backup_path.parent,
        fail=_genesis_fail,
        missing_code="archive_component_missing",
        rejected_code="archive_component_rejected",
    )
    actual_root = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    if actual_root != root:
        raise TrialGenesisError(
            "content_root",
            "backup bytes do not hash to the manifest content root",
        )
    new_path = Path(new_path)
    new_path.parent.mkdir(parents=True, exist_ok=True)
    new_path.write_bytes(backup_path.read_bytes())
    return CapitalRepository.initialize(new_path)


__all__ = [
    "NormalizedTrialArmState",
    "TrialArmGenesisSource",
    "TrialGenesisArchive",
    "TrialGenesisError",
    "TrialGenesisManifest",
    "normalized_trial_arm_state",
    "restore_genesis_arm",
]
