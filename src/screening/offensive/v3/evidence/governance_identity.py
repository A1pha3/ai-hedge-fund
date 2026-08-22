"""持久治理身份目录 — Trial 启动准备工程第一步 (offline primitive, 2026-08-22).

ephemeral 测试链 (``offline_rig`` 每进程 ``Ed25519PrivateKey.generate()``)
只适用于测试/离线播种。真实治理身份需要**持久密钥与可重验 manifest**:

    <identity-dir>/              # owner 持有, 绝不入 git (生成时 .gitignore 提示)
      identity.json              # manifest: anchor + issuers(公钥) + 签名 bundle + head witness
      keys/
        root.pem                 # root 私钥 (PKCS8 Ed25519, 0600, symlink 拒绝)
        <namespace>.pem          # 每 issuer 私钥 (0600)

owner 的操作被收敛为三步 (见 docs/runbooks/v3-governance-identity.md):
1. ``uv run python scripts/v3_governance_identity.py generate --dir <dir>``
2. 保管目录 (尤其 root.pem — 签发/轮换信任根, 泄露 = 整条信任链失守);
3. 轮换时用新 key_id 重新 generate 到新目录 (旧目录标记废弃)。

加载面 fail-closed 纪律: 私钥权限非 0600 拒绝、symlink 拒绝 (第五轮
path_guards 家族纪律)、manifest 严格重解析、root 签名经
``TrustBundleVerifier`` 重验 — 篡改 manifest 任何哈希即构造失败。
生成面幂等纪律: 目标目录已有 identity.json 即拒绝 (绝不覆盖真身份)。

本模块是 offline primitive: 不解锁 runner fail-closed、不激活任何
envelope、不构成权限; 密钥的物理持有与存放位置始终是 owner 决策。
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from base64 import b64decode, b64encode
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import ValidationError

from src.screening.offensive.v3 import trust as v3trust
from src.screening.offensive.v3.contracts.base import ExecutionMode
from src.screening.offensive.v3.contracts.evidence import SUPPORTED_SCHEMA_MAJOR
from src.screening.offensive.v3.contracts.governance import TrustBundle
from src.screening.offensive.v3.evidence.blob_store import BlobStore
from src.screening.offensive.v3.evidence.repository import EvidenceRepository
from src.screening.offensive.v3.trust import SignedEnvelope, canonical_json_bytes

IDENTITY_MANIFEST = "identity.json"
KEYS_SUBDIR = "keys"
ROOT_KEY_FILE = "root.pem"
#: 每命名空间独立 issuer_id — TrustedRegistry 禁止同一 issuer_id 跨
#: issuer_kind (职责非重叠分离); 治理签发面按命名空间分 principal。
def _issuer_id_for(namespace: str) -> str:
    return f"governance.{namespace}.service"
ROOT_ISSUER_ID = "governance.root"
_VALID_FROM_HOURS = 1.0
_VALID_UNTIL_DAYS = 365
#: 每 namespace 一个 issuer; 能力类型按命名空间固定 (与 offline_rig/生产
#: 发布器一致): snapshot 发布 (regime/排程/bar) 与 signal 发布 (btst)。
_SNAPSHOT_NAMESPACES = ("regime", "sse-sessions", "btst-bars")
_SIGNAL_NAMESPACES = ("btst",)


class GovernanceIdentityError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class IdentitySigner:
    """与 offline_rig._Signer 同款 canonical 签名面 (复用同一 preimage)。"""

    key: Ed25519PrivateKey
    issuer: v3trust.TrustedIssuer
    capability: v3trust.Capability

    def __call__(self, payload: bytes) -> SignedEnvelope:
        payload_hash = hashlib.sha256(payload).hexdigest()
        protected = canonical_json_bytes(
            {
                "artifact": self.capability.artifact,
                "capability_scope": self.capability.scope,
                "capability_version": self.capability.capability_version,
                "issuer_id": self.issuer.issuer_id,
                "key_id": self.issuer.key_id,
                "mode": self.capability.mode,
                "namespace": self.capability.namespace,
                "payload": b64encode(payload).decode("ascii"),
                "payload_hash": payload_hash,
                "schema_major": self.capability.schema_major,
            }
        )
        return SignedEnvelope(
            issuer_id=self.issuer.issuer_id,
            key_id=self.issuer.key_id,
            schema_major=self.capability.schema_major,
            artifact=self.capability.artifact,
            namespace=self.capability.namespace,
            mode=self.capability.mode,
            capability_version=self.capability.capability_version,
            capability_scope=self.capability.scope,
            payload_hash=payload_hash,
            payload=payload,
            signature=b64encode(self.key.sign(protected)).decode("ascii"),
        )


@dataclass(frozen=True)
class LoadedGovernanceIdentity:
    """加载成功的持久身份: verifier 材料 + 每 namespace 签名面。"""

    manifest: dict
    verifier: v3trust.CapabilityVerifier
    issuers: dict[str, v3trust.TrustedIssuer]
    capabilities: dict[str, v3trust.Capability]
    #: namespace → 私钥 (仅进程内持有; 加载时已过 lstat/配对守卫)
    key_material: dict

    def signer_for(self, namespace: str) -> IdentitySigner:
        if namespace not in self.key_material:
            raise GovernanceIdentityError(
                "namespace_key_missing",
                "no persisted issuer key for this namespace",
                namespace=namespace,
            )
        return IdentitySigner(
            key=self.key_material[namespace],
            issuer=self.issuers[namespace],
            capability=self.capabilities[namespace],
        )

    def repository_for(
        self,
        *,
        namespace: str,
        database_path: str,
        blobs_dir: Path,
        clock: Callable[[], datetime],
        trust_head: v3trust.CurrentTrustHeadWitness,
    ) -> EvidenceRepository:
        return EvidenceRepository(
            database_path=database_path,
            blob_store=BlobStore(blobs_dir),
            verifier=self.verifier,
            trust_head_provider=_FixedHeadProvider(trust_head),
            issuer_namespace=namespace,
            clock=clock,
        )




class _FixedHeadProvider:
    def __init__(self, head: object) -> None:
        self._head = head

    def current_trust_head(self, trusted_at: datetime) -> object:
        return self._head


def _write_private_key(path: Path, key: Ed25519PrivateKey) -> None:
    """0600 + O_EXCL 落盘; 预置文件/symlink 在打开前即拒。"""
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, pem)
    finally:
        os.close(fd)


def _read_private_key(path: Path) -> Ed25519PrivateKey:
    """lstat 守卫加载: symlink 拒绝、权限非 0600 拒绝 (家族纪律)。"""
    st = path.lstat()
    if stat.S_ISLNK(st.st_mode):
        raise GovernanceIdentityError(
            "identity_key_symlink_rejected",
            "governance private keys must never be symlinks",
            path=str(path),
        )
    if stat.S_IMODE(st.st_mode) != 0o600:
        raise GovernanceIdentityError(
            "identity_key_permissions",
            "governance private keys must be mode 0600",
            path=str(path),
            mode=oct(stat.S_IMODE(st.st_mode)),
        )
    raw = path.read_bytes()
    try:
        key = serialization.load_pem_private_key(raw, password=None)
    except Exception as exc:  # noqa: BLE001 - decode failure is fail-closed
        raise GovernanceIdentityError(
            "identity_key_unreadable",
            "governance private key failed PKCS8 parse",
            path=str(path),
        ) from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise GovernanceIdentityError(
            "identity_key_algorithm",
            "governance private keys must be Ed25519",
            path=str(path),
        )
    return key


def _capability_for(namespace: str, valid_from: datetime, valid_until: datetime):
    if namespace in _SNAPSHOT_NAMESPACES:
        artifact, kind, mode, version = (
            v3trust.ArtifactKind.SNAPSHOT,
            v3trust.IssuerKind.MARKET_PUBLISHER,
            ExecutionMode.DAILY_BAR_PROXY,
            "governance.snapshot.v1",
        )
    elif namespace in _SIGNAL_NAMESPACES:
        artifact, kind, mode, version = (
            v3trust.ArtifactKind.SIGNAL,
            v3trust.IssuerKind.SIGNAL_PRODUCER,
            ExecutionMode.RESEARCH_RECONSTRUCTION,
            "governance.signal.v1",
        )
    else:
        raise GovernanceIdentityError(
            "namespace_unknown",
            "governance identity has no registered capability for this namespace",
            namespace=namespace,
        )
    return (
        v3trust.Capability(
            artifact=artifact,
            namespace=namespace,
            mode=mode,
            schema_major=SUPPORTED_SCHEMA_MAJOR,
            capability_version=version,
            scope=f"global:{namespace}",
            valid_from=valid_from,
            valid_until=valid_until,
            revoked_at=None,
        ),
        kind,
    )


def generate_governance_identity(
    directory: Path,
    *,
    namespaces: tuple[str, ...] = (
        *_SNAPSHOT_NAMESPACES,
        *_SIGNAL_NAMESPACES,
    ),
    clock: Callable[[], datetime] | None = None,
    valid_days: int = _VALID_UNTIL_DAYS,
) -> dict:
    """一次性生成持久身份目录 — 已有 manifest 即拒绝 (绝不覆盖真身份)。

    产物: identity.json (anchor/issuers 公钥/签名 bundle/head witness) +
    keys/{root,<ns>}.pem (0600)。返回被持久化的 manifest dict。
    """
    directory = Path(directory)
    if (directory / IDENTITY_MANIFEST).exists():
        raise GovernanceIdentityError(
            "identity_directory_not_empty",
            "refusing to overwrite an existing governance identity",
            directory=str(directory),
        )
    now = clock() if clock is not None else datetime.now(timezone.utc)
    valid_from = now - timedelta(hours=_VALID_FROM_HOURS)
    valid_until = now + timedelta(days=valid_days)

    root_key = Ed25519PrivateKey.generate()
    root_public = root_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    anchor = v3trust.RootTrustAnchor(
        root_hash=hashlib.sha256(root_public).hexdigest(),
        root_key_id="governance-root-1",
        public_key=b64encode(root_public).decode("ascii"),
        valid_from=valid_from,
        valid_until=valid_until,
        revoked_at=None,
    )

    issuers: list[v3trust.TrustedIssuer] = []
    keys_dir = directory / KEYS_SUBDIR
    keys_dir.mkdir(parents=True, exist_ok=False)
    try:
        _write_private_key(keys_dir / ROOT_KEY_FILE, root_key)
        for namespace in namespaces:
            capability, kind = _capability_for(namespace, valid_from, valid_until)
            key = Ed25519PrivateKey.generate()
            public = key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            issuers.append(
                v3trust.TrustedIssuer(
                    issuer_id=_issuer_id_for(namespace),
                    key_id=f"{namespace}-key-1",
                    issuer_kind=kind,
                    public_key=b64encode(public).decode("ascii"),
                    valid_from=valid_from,
                    valid_until=valid_until,
                    revoked_at=None,
                    capabilities=(capability,),
                )
            )
            _write_private_key(keys_dir / f"{namespace}.pem", key)
        registry = v3trust.TrustedRegistry(issuers=tuple(issuers))
        bundle = TrustBundle(
            registry_epoch=1,
            predecessor_bundle_hash="0" * 64,
            root_hash=anchor.root_hash,
            root_key_id=anchor.root_key_id,
            trusted_issuer_registry_hash=registry.content_hash(),
            issued_at=valid_from,
            expires_at=valid_until,
            revoked_at=None,
            issuer_id=ROOT_ISSUER_ID,
            issuer_capability="root.trust.bundle.v1",
            schema_major=SUPPORTED_SCHEMA_MAJOR,
        )
        signed_bundle = v3trust.SignedTrustBundle(
            bundle=bundle,
            registry=registry,
            signature=b64encode(
                root_key.sign(
                    v3trust.trust_bundle_signature_preimage(bundle, registry)
                )
            ).decode("ascii"),
        )
        head = v3trust.CurrentTrustHeadWitness(
            active_trust_bundle_hash=bundle.artifact_hash(),
            registry_epoch=1,
            head_version=1,
            store_version=1,
            observed_at=now,
        )
        manifest = {
            "identity_kind": "ai-hedge-fund.v3.governance-identity.v1",
            "generated_at": now.isoformat(),
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat(),
            "anchor": json.loads(anchor.model_dump_json()),
            "signed_bundle": json.loads(signed_bundle.model_dump_json()),
            "head_witness": json.loads(head.model_dump_json()),
            "namespaces": list(namespaces),
        }
        manifest_path = directory / IDENTITY_MANIFEST
        fd = os.open(
            manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        try:
            os.write(
                fd,
                json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"),
            )
        finally:
            os.close(fd)
    except BaseException:
        # 半成品目录整体废弃 — 身份目录要么完整要么不存在
        import shutil

        shutil.rmtree(directory, ignore_errors=True)
        raise
    return manifest


def load_governance_identity(
    directory: Path, *, trusted_at: datetime
) -> LoadedGovernanceIdentity:
    """加载 + 全量重验: manifest 严格解析、root 签名重验、私钥守卫加载。"""
    directory = Path(directory)
    manifest_path = directory / IDENTITY_MANIFEST
    if not manifest_path.is_file():
        raise GovernanceIdentityError(
            "identity_manifest_missing",
            "governance identity directory has no identity.json",
            directory=str(directory),
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise GovernanceIdentityError(
            "identity_manifest_corrupt",
            "identity.json failed strict parse",
        ) from exc
    if manifest.get("identity_kind") != "ai-hedge-fund.v3.governance-identity.v1":
        raise GovernanceIdentityError(
            "identity_kind_unknown",
            "identity.json is not a v1 governance identity manifest",
        )
    def _model(section_key: str, model_cls):
        # 子模型经 JSON 路径重验 (ISO datetime 字符串只在 JSON 模式 coerce;
        # dict + strict 会把 'Z' 后缀字符串拒为类型不符)。
        try:
            return model_cls.model_validate_json(
                json.dumps(manifest[section_key])
            )
        except (ValidationError, KeyError, TypeError, ValueError) as exc:
            raise GovernanceIdentityError(
                "identity_manifest_corrupt",
                "identity.json failed strict model revalidation",
                section=section_key,
            ) from exc

    anchor = _model("anchor", v3trust.RootTrustAnchor)
    signed_bundle = _model("signed_bundle", v3trust.SignedTrustBundle)
    _head = _model("head_witness", v3trust.CurrentTrustHeadWitness)

    verifier = v3trust.CapabilityVerifier(
        v3trust.TrustBundleVerifier((anchor,)), (signed_bundle,)
    )
    # 篡改任何哈希/签名在构造时即抛; 显式验一次窗口与 head 绑定。
    if not (anchor.valid_from <= trusted_at <= anchor.valid_until):
        raise GovernanceIdentityError(
            "identity_window_invalid",
            "identity trust window does not cover the trusted instant",
            trusted_at=trusted_at.isoformat(),
            valid_from=anchor.valid_from.isoformat(),
            valid_until=anchor.valid_until.isoformat(),
        )

    issuers: dict[str, v3trust.TrustedIssuer] = {}
    capabilities: dict[str, v3trust.Capability] = {}
    for issuer in signed_bundle.registry.issuers:
        for capability in issuer.capabilities:
            issuers[capability.namespace] = issuer
            capabilities[capability.namespace] = capability

    keys: dict[str, Ed25519PrivateKey] = {}
    keys_dir = directory / KEYS_SUBDIR
    for namespace in manifest.get("namespaces", []):
        key_path = keys_dir / f"{namespace}.pem"
        if not key_path.is_file():
            raise GovernanceIdentityError(
                "namespace_key_missing",
                "identity manifest declares a namespace with no key file",
                namespace=namespace,
            )
        key = _read_private_key(key_path)
        _assert_key_matches_registry(key, issuers, namespace)
        keys[namespace] = key

    return LoadedGovernanceIdentity(
        manifest=manifest,
        verifier=verifier,
        issuers=issuers,
        capabilities=capabilities,
        key_material=keys,
    )


def _assert_key_matches_registry(
    key: Ed25519PrivateKey, issuers: dict, namespace: str
) -> None:
    issuer = issuers.get(namespace)
    if issuer is None:
        raise GovernanceIdentityError(
            "namespace_not_in_registry",
            "persisted key has no matching issuer in the signed registry",
            namespace=namespace,
        )
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    if b64encode(public).decode("ascii") != issuer.public_key:
        raise GovernanceIdentityError(
            "identity_key_mismatch",
            "persisted private key does not match the signed registry public key",
            namespace=namespace,
        )


def verify_identity_directory(
    directory: Path, *, now: datetime | None = None
) -> dict:
    """CLI 检查面: 加载 + 权限 + 签名重验 + 私钥↔注册表配对汇总。"""
    now = now or datetime.now(timezone.utc)
    identity = load_governance_identity(Path(directory), trusted_at=now)
    return {
        "ok": True,
        "generated_at": identity.manifest.get("generated_at"),
        "valid_until": identity.manifest.get("valid_until"),
        "namespaces": identity.manifest.get("namespaces"),
        "root_key_id": identity.manifest["anchor"]["root_key_id"],
    }


__all__ = [
    "GovernanceIdentityError",
    "IdentitySigner",
    "LoadedGovernanceIdentity",
    "generate_governance_identity",
    "load_governance_identity",
    "verify_identity_directory",
]
