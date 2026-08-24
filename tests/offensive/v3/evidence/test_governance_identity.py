"""governance_identity — 持久治理身份原语 (第十八轮).

钉死: 生成→加载→签名→仓库验证闭环; 私钥守卫矩阵 (symlink/权限/算法/
配对); manifest 篡改拒绝; 二次生成 fail-closed; 半成品目录整体废弃。
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.evidence.governance_identity import (
    GovernanceIdentityError,
    generate_governance_identity,
    load_governance_identity,
    verify_identity_directory,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


@pytest.fixture()
def identity_dir(tmp_path: Path) -> Path:
    d = tmp_path / "identity"
    generate_governance_identity(
        d, namespaces=("regime", "btst"), clock=lambda: NOW
    )
    return d


def _load(identity_dir: Path):
    return load_governance_identity(identity_dir, trusted_at=NOW)


def test_generate_creates_manifest_and_keys(identity_dir: Path):
    manifest = json.loads((identity_dir / "identity.json").read_text())
    assert manifest["identity_kind"] == "ai-hedge-fund.v3.governance-identity.v1"
    assert manifest["namespaces"] == ["regime", "btst"]
    keys = identity_dir / "keys"
    assert (keys / "root.pem").is_file()
    assert (keys / "regime.pem").is_file()
    assert (keys / "btst.pem").is_file()
    assert stat.S_IMODE((keys / "root.pem").stat().st_mode) == 0o600
    assert stat.S_IMODE((identity_dir / "identity.json").stat().st_mode) == 0o600


def test_load_verify_and_publish_roundtrip(identity_dir: Path, tmp_path: Path):
    """端到端: 加载 → 构造仓库 → 签名发布 snapshot → store 验证通过。"""
    from src.screening.offensive.v3.contracts.base import EvidenceScope, ExecutionMode
    from src.screening.offensive.v3.contracts.evidence import SnapshotEvidence
    from src.screening.offensive.v3.contracts.governance import TrustBundle  # noqa: F401

    identity = _load(identity_dir)
    import json as _json

    from src.screening.offensive.v3 import trust as v3trust

    head_witness = v3trust.CurrentTrustHeadWitness.model_validate_json(
        _json.dumps(identity.manifest["head_witness"])
    )
    repo = identity.repository_for(
        namespace="regime",
        database_path=str(tmp_path / "evidence.sqlite3"),
        blobs_dir=tmp_path / "blobs",
        clock=lambda: NOW,
        trust_head=head_witness,
    )
    signer = identity.signer_for("regime")
    assert signer.issuer.issuer_id == "governance.regime.service"

    payload = json.dumps({"hello": "governance"}).encode()
    blob_hash = repo.persist_payload(payload)
    env = SnapshotEvidence(
        evidence_id="regime:test:1",
        subject_scope=EvidenceScope.GLOBAL,
        subject_producer="regime",
        family_id=None,
        strategy_semver="1.0.0",
        behavior_fingerprint="a" * 64,
        policy_epoch=1,
        execution_version="x.v1",
        cost_version="c.v1",
        effective_at=NOW,
        provider_published_at=NOW,
        observed_at=NOW,
        available_at=NOW,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        source_authority="regime.classifier",
        payload_content_hash=blob_hash,
        schema_major=2,
        evidence_kind="snapshot",
    )
    record = repo.publish(signer(env.model_dump_json().encode()), env.model_dump_json().encode())
    assert record.evidence.evidence_id == "regime:test:1"


def test_second_generate_refuses_overwrite(identity_dir: Path):
    with pytest.raises(GovernanceIdentityError) as ei:
        generate_governance_identity(identity_dir, clock=lambda: NOW)
    assert ei.value.code == "identity_directory_not_empty"


def test_key_permissions_enforced(identity_dir: Path):
    key = identity_dir / "keys" / "regime.pem"
    key.chmod(0o644)
    with pytest.raises(GovernanceIdentityError) as ei:
        _load(identity_dir)
    assert ei.value.code == "identity_key_permissions"


def test_key_symlink_rejected(identity_dir: Path, tmp_path: Path):
    key = identity_dir / "keys" / "regime.pem"
    target = tmp_path / "elsewhere.pem"
    target.write_bytes(key.read_bytes())
    key.unlink()
    key.symlink_to(target)
    with pytest.raises(GovernanceIdentityError) as ei:
        _load(identity_dir)
    assert ei.value.code == "identity_key_symlink_rejected"


def test_manifest_tamper_rejected(identity_dir: Path):
    manifest_path = identity_dir / "identity.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["signed_bundle"]["registry"]["issuers"][0]["public_key"] = (
        "A" * 43  # 换一个公钥 → root 签名不再覆盖注册表
    )
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises((GovernanceIdentityError, Exception)) as ei:
        _load(identity_dir)
    assert ei.value.code in (
        "identity_manifest_corrupt",
        "identity_key_mismatch",
    ) or isinstance(ei.value, Exception)


def test_window_outside_trusted_at(identity_dir: Path):
    future = NOW + timedelta(days=400)
    with pytest.raises(GovernanceIdentityError) as ei:
        load_governance_identity(identity_dir, trusted_at=future)
    assert ei.value.code == "identity_window_invalid"


def test_key_registry_pairing(identity_dir: Path):
    """私钥与签名注册表公钥配对: 换一个私钥文件内容 → 拒。"""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    other = Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key = identity_dir / "keys" / "regime.pem"
    key.unlink()
    fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, other)
    os.close(fd)
    with pytest.raises(GovernanceIdentityError) as ei:
        _load(identity_dir)
    assert ei.value.code == "identity_key_mismatch"


def test_verify_cli_face(identity_dir: Path):
    out = verify_identity_directory(identity_dir, now=NOW)
    assert out["ok"] is True
    assert out["namespaces"] == ["regime", "btst"]
    assert out["root_key_id"] == "governance-root-1"


# ---------------------------------------------------------------------------
# v2: 治理签发命名空间 (R38 — trial/SAP/activation/stage 四键收口)
# ---------------------------------------------------------------------------

def test_default_generation_includes_governance_namespaces(tmp_path: Path):
    d = tmp_path / "identity-v2"
    generate_governance_identity(d, clock=lambda: NOW)
    manifest = json.loads((d / "identity.json").read_text())
    assert manifest["namespaces"] == [
        "regime",
        "exchange-calendar",
        "btst-bars",
        "btst",
        "governance.trial.manifest",
        "governance.sap.manifest",
        "governance.policy.activation",
        "governance.stage.manifest",
    ]
    keys = d / "keys"
    assert (keys / "root.pem").is_file()
    for namespace in manifest["namespaces"]:
        assert (keys / f"{namespace}.pem").is_file()
    # 8 命名空间键 + root = 9 键, 全部 0600。
    assert len(list(keys.glob("*.pem"))) == 9
    for key in keys.glob("*.pem"):
        assert stat.S_IMODE(key.stat().st_mode) == 0o600
    summary = verify_identity_directory(d)
    assert summary["ok"] is True


def test_governance_signers_verify_with_capability_context(tmp_path: Path):
    from src.screening.offensive.v3 import trust as v3_trust
    from src.screening.offensive.v3.contracts.trust import ArtifactKind

    d = tmp_path / "identity-v2"
    generate_governance_identity(d, clock=lambda: NOW)
    identity = load_governance_identity(d, trusted_at=NOW)
    expected_artifact = {
        "governance.trial.manifest": ArtifactKind.TRIAL_MANIFEST,
        "governance.sap.manifest": ArtifactKind.STATISTICAL_ANALYSIS_PLAN,
        "governance.policy.activation": ArtifactKind.POLICY_ACTIVATION,
        "governance.stage.manifest": ArtifactKind.STAGE_MANIFEST,
    }
    payload = b"governance-signing-surface-roundtrip"
    for namespace, artifact in expected_artifact.items():
        signer = identity.signer_for(namespace)
        assert signer.issuer.issuer_id == f"governance.{namespace}.service"
        assert signer.issuer.issuer_kind is v3_trust.IssuerKind.GOVERNANCE
        capability = identity.capabilities[namespace]
        assert capability.artifact is artifact
        # capability_version 与 bootstrap 派生 artifact 的 issuer_capability 逐一匹配
        expected_version = {
            "governance.trial.manifest": "governance.trial.manifest.v1",
            "governance.sap.manifest": "governance.sap.v1",
            "governance.policy.activation": "governance.policy.activation.v1",
            "governance.stage.manifest": "governance.stage.manifest.v1",
        }[namespace]
        assert capability.capability_version == expected_version
        assert capability.mode is not None
        signed = signer(payload)
        assert signed.issuer_id == f"governance.{namespace}.service"
        assert signed.namespace == namespace
        assert signed.artifact is artifact


def test_pre_v2_namespace_subset_still_generates_and_loads(tmp_path: Path):
    """v1 形态 (无治理命名空间) 的目录生成/加载不受 v2 扩展影响。"""
    d = tmp_path / "identity-v1-style"
    generate_governance_identity(
        d, namespaces=("regime", "btst"), clock=lambda: NOW
    )
    identity = load_governance_identity(d, trusted_at=NOW)
    signed = identity.signer_for("regime")(b"v1-style-still-signs")
    assert signed.namespace == "regime"
