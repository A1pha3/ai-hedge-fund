"""Plan 07 Task 1 (RED): durable broker raw inbox 收件箱测试.

锁定约束:
1. content-addressed: payload_hash = sha256(canonical_bytes(envelope));
   同 payload 重复 append = 幂等重放 (返回原 revision, 无新行).
2. source sequence 单调: 同 source 乱序/回退 = SEQUENCE_CONFLICT
   (最近 N 条响应语义在此层即拒绝, 不做猜测重排).
3. 相同 envelope_id 但不同 payload_hash = PAYLOAD_CONFLICT
   (身份与内容绑定, fail-closed).
4. durable-before-normalize: append 成功后进程崩溃, 重开 inbox 必须仍能
   读到原信封 (normalized 与否都不得丢原始事实).
5. secret 字段: 提交时给出 redaction 函数, 落盘 payload 必须被脱敏;
   原文绝不入库 (redact 若漏掉 secret 则 STRUCTURAL 失败而非静默).
6. parser_version 绑定: 每个 revision 记录解析版本, 供 Task 4 重放时
   判定兼容.
"""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

import pytest

from src.screening.offensive.v3.broker.ports import (
    BrokerAccountBinding,
    BrokerRawEnvelope,
)
from src.screening.offensive.v3.broker.raw_inbox import (
    BrokerRawInbox,
    RawInboxError,
)

T0 = datetime(2026, 8, 7, 1, 0, 0, tzinfo=timezone.utc)
FINGERPRINT = "a" * 64


def _binding() -> BrokerAccountBinding:
    return BrokerAccountBinding(
        account_id="acct-001",
        environment="sandbox",
        currency="CNY",
        endpoint_fingerprint=FINGERPRINT,
    )


def _envelope(
    *,
    sequence: int,
    payload: dict[str, object] | None = None,
    source: str = "broker-push",
) -> BrokerRawEnvelope:
    return BrokerRawEnvelope(
        authenticated=True,
        auth_fingerprint=FINGERPRINT,
        source=source,
        source_sequence=sequence,
        parser_version="v1",
        broker_observed_at=T0,
        received_at=T0,
        account=_binding(),
        payload=payload if payload is not None else {"kind": "order_update"},
    )


@pytest.fixture()
def inbox(tmp_path) -> BrokerRawInbox:
    return BrokerRawInbox(str(tmp_path / "raw-inbox.sqlite3"))


def test_append_assigns_monotone_revisions(inbox: BrokerRawInbox) -> None:
    first = inbox.append(_envelope(sequence=1), envelope_id="env-1")
    second = inbox.append(_envelope(sequence=2), envelope_id="env-2")
    assert first.revision == 1
    assert second.revision == 2
    assert first.payload_hash != second.payload_hash


def test_identical_replay_is_idempotent(inbox: BrokerRawInbox) -> None:
    envelope = _envelope(sequence=1)
    first = inbox.append(envelope, envelope_id="env-1")
    replayed = inbox.append(envelope, envelope_id="env-1")
    assert replayed.revision == first.revision
    assert replayed.payload_hash == first.payload_hash
    assert inbox.count() == 1


def test_conflicting_payload_same_identity_rejected(inbox: BrokerRawInbox) -> None:
    inbox.append(_envelope(sequence=1), envelope_id="env-1")
    forged = _envelope(sequence=1, payload={"kind": "tampered"})
    with pytest.raises(RawInboxError) as excinfo:
        inbox.append(forged, envelope_id="env-1")
    assert excinfo.value.code == "PAYLOAD_CONFLICT"


def test_sequence_rollback_rejected(inbox: BrokerRawInbox) -> None:
    inbox.append(_envelope(sequence=5), envelope_id="env-5")
    with pytest.raises(RawInboxError) as excinfo:
        inbox.append(_envelope(sequence=4), envelope_id="env-4")
    assert excinfo.value.code == "SEQUENCE_CONFLICT"


def test_sequence_gap_rejected(inbox: BrokerRawInbox) -> None:
    inbox.append(_envelope(sequence=1), envelope_id="env-1")
    with pytest.raises(RawInboxError) as excinfo:
        inbox.append(_envelope(sequence=3), envelope_id="env-3")
    assert excinfo.value.code == "SEQUENCE_CONFLICT"


def test_independent_sources_have_independent_sequences(
    inbox: BrokerRawInbox,
) -> None:
    push = inbox.append(
        _envelope(sequence=7, source="broker-push"), envelope_id="p-7"
    )
    poll = inbox.append(
        _envelope(sequence=1, source="broker-poll"), envelope_id="q-1"
    )
    assert push.revision == 1
    assert poll.revision == 2


def test_crash_after_append_preserves_envelope(tmp_path) -> None:
    path = str(tmp_path / "durable.sqlite3")
    writer = BrokerRawInbox(path)
    envelope = _envelope(sequence=1)
    record = writer.append(envelope, envelope_id="env-1")
    del writer  # 模拟进程崩溃: 不做任何优雅关闭

    recovered = BrokerRawInbox(path)
    restored = recovered.get(record.revision)
    assert restored is not None
    assert restored.envelope == envelope
    assert restored.payload_hash == record.payload_hash
    assert recovered.pending() == (record.revision,)


def test_secret_fields_redacted_before_durability(tmp_path) -> None:
    path = str(tmp_path / "redact.sqlite3")
    inbox = BrokerRawInbox(path)
    secret_payload: dict[str, object] = {
        "kind": "order_update",
        "session_token": "super-secret-token",
        "order_id": "B1",
    }
    record = inbox.append(
        _envelope(sequence=1, payload=secret_payload),
        envelope_id="env-1",
    )
    raw = sqlite3.connect(path)
    try:
        stored = raw.execute(
            "SELECT payload_json FROM raw_inbox_revisions WHERE revision = ?",
            (record.revision,),
        ).fetchone()[0]
    finally:
        raw.close()
    assert "super-secret-token" not in stored
    assert "REDACTED" in stored
    # 脱敏后信封仍可完整复原 (payload 中 secret 已替换为哨兵值).
    restored = inbox.get(record.revision)
    assert restored is not None
    assert restored.envelope.payload["session_token"] == "[REDACTED]"
    assert restored.envelope.payload["order_id"] == "B1"


def test_unredactable_secret_field_fails_closed(inbox: BrokerRawInbox) -> None:
    # payload 包含 redaction 无法处理的类型 (bytes), 必须结构拒绝而非
    # 静默丢弃/截断.
    envelope = BrokerRawEnvelope(
        authenticated=True,
        auth_fingerprint=FINGERPRINT,
        source="broker-push",
        source_sequence=1,
        parser_version="v1",
        broker_observed_at=T0,
        received_at=T0,
        account=_binding(),
        payload={"kind": "order_update"},
    )
    object.__setattr__(
        envelope, "payload", {"session_token": b"\x00binary-secret"}
    )
    with pytest.raises((RawInboxError, TypeError, ValueError)):
        inbox.append(envelope, envelope_id="env-bytes")


def test_mark_normalized_and_pending_queue(inbox: BrokerRawInbox) -> None:
    first = inbox.append(_envelope(sequence=1), envelope_id="env-1")
    second = inbox.append(_envelope(sequence=2), envelope_id="env-2")
    assert set(inbox.pending()) == {first.revision, second.revision}
    inbox.mark_normalized(first.revision, normalized_revision="exec-rev-1")
    assert inbox.pending() == (second.revision,)
    # 重复 mark 幂等; 同一 raw revision 绑定到不同 normalized id 则拒绝.
    inbox.mark_normalized(first.revision, normalized_revision="exec-rev-1")
    with pytest.raises(RawInboxError) as excinfo:
        inbox.mark_normalized(first.revision, normalized_revision="other")
    assert excinfo.value.code == "NORMALIZED_BINDING_CONFLICT"


def test_parser_version_recorded_per_revision(inbox: BrokerRawInbox) -> None:
    record = inbox.append(_envelope(sequence=1), envelope_id="env-1")
    assert record.parser_version == "v1"
