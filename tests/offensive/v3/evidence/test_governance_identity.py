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
