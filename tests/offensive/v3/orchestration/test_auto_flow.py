"""Plan 05 Task 6 (RED): AutoFlow — --auto 独立 shadow 编排契约。

覆盖 Step 1 契约:
1. 2^3 全组合 — snapshot/outcome/auto_shadow 各成功/失败 → 8 种组合, 每种
   断言三个 status 精确值 + 独立提交 (失败步不阻止其他步; snapshot 失败时
   auto_shadow 因无输入记 "skipped" 且 producer 不被调用)。
2. rerun 幂等 — 同一天第二次 run() → 结果一致 (outcome 空 tuple = ok)。
3. unavailable services — finalizer 抛 EvidenceStoreError / producer 抛
   AutoProducerApiError → 各自 status failed, 其他步不受影响。
4. snapshot failure — loader 返回 snapshot=None + global_reason, 或抛异常
   → snapshot_status failed; outcome 仍照常执行; auto_shadow 记 "skipped"
   (reason "no_snapshot"), producer 不被调用。
5. correction pending fence — finalizer 抛 DependencyFixError("fence_not_active")
   → outcome_status failed, 其他步 ok。
6. report execution_authority=none — 任何组合下恒 "none" (含 dataclass 默认值)。
7. OFF 模式 — 三步全 "skipped" 且三步 double 零调用 (legacy 行为不变)。
8. SHADOW 模式 — 三步都执行; 真实 AutoProducerApi (SHADOW provider) 集成:
   发布 4 枚签名 SignalEvidence。

状态值域与 reason 形状 (与骨架 docstring 一致):
- status ∈ {"ok", "failed", "skipped"}: "failed" = 被尝试且抛异常,
  "skipped" = 未被尝试 (OFF / no_snapshot / not_shadow_mode)。
- failure_reason: {步名: 原因}; 异常原因 = f"{type(exc).__name__}: {exc}";
  snapshot 加载失败 = global_reason; skip = "no_snapshot"/"not_shadow_mode"。
- outcome 步 as_of = signal_date 15:00 UTC; program 透传构造参数。

本文件引用尚未实现的 AutoFlow 骨架 (方法体 raise NotImplementedError);
当前应整体 RED, 由主代理随后实现 GREEN。
"""

from __future__ import annotations

import hashlib
from base64 import b64encode
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from src.screening.offensive.daily_action_readiness import (
    _fingerprint,
    BOARD_RULE_VERSION,
    DAILY_ACTION_READINESS_SCHEMA_VERSION,
    DailyActionReadinessManifest,
    DailyActionTickerReadiness,
    NORMALIZATION_VERSION,
    READINESS_POLICY_VERSION,
    SharedReadinessEvidence,
    SuspensionReadinessEvidence,
)
from src.screening.offensive.daily_action_snapshot import (
    FrozenFlowRow,
    FrozenPriceRow,
    SnapshotLoadError,
    VerifiedDailyActionSnapshot,
    VerifiedSnapshotResult,
)
from src.screening.offensive.readiness_reference import ReferenceProvenance
from src.screening.offensive.setup_data_contracts import (
    SETUP_REQUIREMENTS_VERSION,
    SetupCapability,
)
from src.screening.offensive.setups.base import DetectionResult
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.v3 import trust as v3_trust
from src.screening.offensive.v3.contracts import (
    canonical_json_bytes,
    ExecutionMode,
    SUPPORTED_SCHEMA_MAJOR,
)
from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    SignalEvidence,
)
from src.screening.offensive.v3.contracts.governance import TrustBundle
from src.screening.offensive.v3.evidence.blob_store import BlobStore
from src.screening.offensive.v3.evidence.dependency_fix import DependencyFixError
from src.screening.offensive.v3.evidence.outcomes import OutcomeFinalizerError
from src.screening.offensive.v3.evidence.repository import EvidenceStoreError
from src.screening.offensive.v3.orchestration.auto_flow import (
    AutoFlow,
    AutoFlowResult,
)
from src.screening.offensive.v3.policy.models import RuntimeMode
from src.screening.offensive.v3.services.auto_producer_api import (
    AUTO_PRODUCER_NOT_SHADOW,
    AutoProducerApi,
    AutoProducerApiError,
)
from src.utils.date_utils import SIGNAL_SESSION_POLICY_VERSION

UTC = timezone.utc
# clock 落在 signal_date 次日 09:00 UTC (Task 5 同款); outcome as_of 由
# flow 从 signal_date 派生 (15:00 UTC), 与 producer 信封时间链起点一致。
NOW = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
SIGNAL_DATE = date(2026, 8, 5)
AS_OF = datetime(2026, 8, 5, 15, 0, tzinfo=UTC)
HASH = "e" * 64
CONSUMED_FP = "sha256:" + "a" * 64
SNAPSHOT_ID = "sha256:" + "b" * 64
CONTENT_FP = "sha256:" + "c" * 64
INPUT_FP = "sha256:" + "d" * 64
UNIVERSE_FP = "sha256:" + "f" * 64
SUSPENSION_FP = "sha256:" + "1" * 64
TICKERS = ("300001", "300002")
AUTO_NS = "auto"
AUTO_FINGERPRINT = "a" * 64
MANIFEST_MISSING = "manifest_missing"


# --------------------------------------------------------------------------
# 信任基建 (Task 5 同款): _Clock / Ed25519 / root context / 签名
# --------------------------------------------------------------------------


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


def _public_key_b64(private_key: Ed25519PrivateKey) -> str:
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return b64encode(public_bytes).decode("ascii")


def _trust_capability(namespace: str, **overrides):
    values = {
        "artifact": v3_trust.ArtifactKind.SIGNAL,
        "namespace": namespace,
        "mode": ExecutionMode.RESEARCH_RECONSTRUCTION,
        "schema_major": SUPPORTED_SCHEMA_MAJOR,
        "capability_version": "signal-producer.v1",
        "scope": f"evidence:{namespace}",
        "valid_from": NOW - timedelta(days=1),
        "valid_until": NOW + timedelta(days=1),
        "revoked_at": None,
    }
    values.update(overrides)
    return v3_trust.Capability(**values)


def _issuer(private_key, *capabilities, issuer_id, key_id, kind):
    return v3_trust.TrustedIssuer(
        issuer_id=issuer_id,
        key_id=key_id,
        issuer_kind=kind,
        public_key=_public_key_b64(private_key),
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=1),
        revoked_at=None,
        capabilities=tuple(capabilities),
    )


def _protected_input(*, issuer_id, key_id, capability, payload, payload_hash):
    return canonical_json_bytes(
        {
            "artifact": capability.artifact,
            "capability_scope": capability.scope,
            "capability_version": capability.capability_version,
            "issuer_id": issuer_id,
            "key_id": key_id,
            "mode": capability.mode,
            "namespace": capability.namespace,
            "payload": b64encode(payload).decode("ascii"),
            "payload_hash": payload_hash,
            "schema_major": capability.schema_major,
        }
    )


def _signed(private_key, capability, *, issuer_id, key_id, payload):
    digest = hashlib.sha256(payload).hexdigest()
    protected = _protected_input(
        issuer_id=issuer_id,
        key_id=key_id,
        capability=capability,
        payload=payload,
        payload_hash=digest,
    )
    signature = private_key.sign(protected)
    return v3_trust.SignedEnvelope(
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
        signature=b64encode(signature).decode("ascii"),
    )


def _root_context(registry):
    root_key = Ed25519PrivateKey.generate()
    root_public = _public_key_b64(root_key)
    root_hash = hashlib.sha256(
        root_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).hexdigest()
    anchor = v3_trust.RootTrustAnchor(
        root_hash=root_hash,
        root_key_id="offline-root-1",
        public_key=root_public,
        valid_from=NOW - timedelta(days=30),
        valid_until=NOW + timedelta(days=30),
        revoked_at=None,
    )
    bundle = TrustBundle(
        registry_epoch=1,
        predecessor_bundle_hash="0" * 64,
        root_hash=root_hash,
        root_key_id=anchor.root_key_id,
        trusted_issuer_registry_hash=registry.content_hash(),
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(days=1),
        revoked_at=None,
        issuer_id="offline-governance-root",
        issuer_capability="root.trust.bundle.v1",
        schema_major=2,
    )
    signature = b64encode(root_key.sign(v3_trust.trust_bundle_signature_preimage(bundle, registry))).decode("ascii")
    signed_bundle = v3_trust.SignedTrustBundle(bundle=bundle, registry=registry, signature=signature)
    verifier = v3_trust.TrustBundleVerifier((anchor,))
    delegate = v3_trust.CapabilityVerifier(verifier, (signed_bundle,))
    head = v3_trust.CurrentTrustHeadWitness(
        active_trust_bundle_hash=bundle.artifact_hash(),
        registry_epoch=bundle.registry_epoch,
        head_version=bundle.registry_epoch,
        store_version=1,
        observed_at=NOW,
    )

    class _HeadProvider:
        def current_trust_head(self, trusted_at):
            return head

    return delegate, _HeadProvider()


# --------------------------------------------------------------------------
# VerifiedDailyActionSnapshot fixture (Task 5 同款: 2 个可扫候选, OB 禁用)
# --------------------------------------------------------------------------


def _hit_result(ticker: str) -> DetectionResult:
    return DetectionResult(
        hit=True,
        ticker=ticker,
        trade_date=SIGNAL_DATE.strftime("%Y%m%d"),
        trigger_strength=0.90,
        invalidation_condition="price below trigger close",
        metadata={"range_based_stop_pct": -0.08},
        degraded=False,
        degradation_reason="",
    )


def _capability() -> SetupCapability:
    return SetupCapability(
        enabled=True,
        scannable=True,
        plan_eligible=True,
        degraded=False,
        block_reasons=(),
        warnings=(),
        consumed_fingerprint=CONSUMED_FP,
    )


def _disabled_capability() -> SetupCapability:
    return SetupCapability(
        enabled=False,
        scannable=False,
        plan_eligible=False,
        degraded=False,
        block_reasons=("setup_disabled_by_default",),
        warnings=(),
        consumed_fingerprint=None,
    )


def _shared_evidence() -> SharedReadinessEvidence:
    regime_row = {"trade_date": SIGNAL_DATE.isoformat(), "regime": "normal"}
    industry_by_ticker = {ticker: "software" for ticker in TICKERS}
    industry_day_pct = {ticker: 3.2 for ticker in TICKERS}
    security_status_by_ticker = {ticker: "listed" for ticker in TICKERS}
    security_reference = ReferenceProvenance.create(
        observed_on=SIGNAL_DATE,
        effective_from=SIGNAL_DATE,
        effective_through=SIGNAL_DATE,
        source="tushare.stock_basic",
        version="test-stock-basic-v1",
        content_fingerprint=_fingerprint({"security": TICKERS}),
    )
    sw_reference = ReferenceProvenance.create(
        observed_on=SIGNAL_DATE,
        effective_from=SIGNAL_DATE,
        effective_through=SIGNAL_DATE,
        source="tushare.index_classify+index_member",
        version="test-sw-v1",
        content_fingerprint=_fingerprint({"sw": TICKERS}),
    )
    return SharedReadinessEvidence(
        as_of_date=SIGNAL_DATE,
        regime_row=regime_row,
        industry_by_ticker=industry_by_ticker,
        industry_day_pct=industry_day_pct,
        security_status_by_ticker=security_status_by_ticker,
        regime_fingerprint=_fingerprint({"as_of_date": SIGNAL_DATE.isoformat(), "regime_row": regime_row}),
        industry_fingerprint=_fingerprint(
            {
                "as_of_date": SIGNAL_DATE.isoformat(),
                "industry_by_ticker": industry_by_ticker,
                "industry_day_pct": industry_day_pct,
            }
        ),
        security_fingerprint=_fingerprint(
            {
                "as_of_date": SIGNAL_DATE.isoformat(),
                "security_status_by_ticker": security_status_by_ticker,
            }
        ),
        security_reference=security_reference,
        sw_reference=sw_reference,
        frozen_source_fingerprint=_fingerprint({"frozen": TICKERS}),
        board_rule_version=BOARD_RULE_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        signal_session_policy_version=SIGNAL_SESSION_POLICY_VERSION,
    )


def _manifest() -> DailyActionReadinessManifest:
    return DailyActionReadinessManifest(
        schema_version=DAILY_ACTION_READINESS_SCHEMA_VERSION,
        domain="daily_action",
        run_id="plan05t6",
        trade_date=SIGNAL_DATE,
        created_at="2026-08-05T12:00:00+00:00",
        status="healthy",
        universe_kind="resolved_refresh_universe",
        universe_tickers=TICKERS,
        universe_fingerprint=UNIVERSE_FP,
        input_fingerprint=INPUT_FP,
        suspension_evidence=SuspensionReadinessEvidence("available_empty", (), SUSPENSION_FP),
        ticker_readiness=MappingProxyType(
            {
                ticker: DailyActionTickerReadiness(
                    evidence_status="verified",
                    capabilities=MappingProxyType(
                        {
                            "btst_breakout": _capability(),
                            "oversold_bounce": _disabled_capability(),
                        }
                    ),
                )
                for ticker in TICKERS
            }
        ),
        warnings=(),
        shared_evidence=_shared_evidence(),
        policy_versions=MappingProxyType(
            {
                "readiness_policy": READINESS_POLICY_VERSION,
                "normalization": NORMALIZATION_VERSION,
                "board_rule": BOARD_RULE_VERSION,
                "setup_requirements": SETUP_REQUIREMENTS_VERSION,
                "signal_session_cutoff": SIGNAL_SESSION_POLICY_VERSION,
            }
        ),
        content_fingerprint=CONTENT_FP,
    )


def _prices() -> tuple[FrozenPriceRow, ...]:
    rows: list[FrozenPriceRow] = []
    for index in range(22):
        session = SIGNAL_DATE - timedelta(days=21 - index)
        close = 10.0
        pct = 0.0
        if index == 16:
            close = 10.5
        if index == 21:
            close = 11.0
            pct = 10.0
        rows.append(
            FrozenPriceRow(
                trade_date=session,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1000000,
                pct_change=pct,
            )
        )
    return tuple(rows)


def _flows() -> tuple[FrozenFlowRow, ...]:
    return tuple(
        FrozenFlowRow(
            trade_date=SIGNAL_DATE - timedelta(days=offset),
            close=11.0,
            pct_change=0.0,
            main_net_inflow=1000000,
        )
        for offset in range(3)
    )


def _snapshot() -> VerifiedDailyActionSnapshot:
    return VerifiedDailyActionSnapshot(
        signal_date=SIGNAL_DATE,
        snapshot_id=SNAPSHOT_ID,
        manifest=_manifest(),
        universe_tickers=TICKERS,
        prices_by_ticker=MappingProxyType({ticker: _prices() for ticker in TICKERS}),
        fund_flow_by_ticker=MappingProxyType({ticker: _flows() for ticker in TICKERS}),
        industry_day_pct_by_ticker=MappingProxyType({ticker: 3.2 for ticker in TICKERS}),
        regime="normal",
        board_rule_version=BOARD_RULE_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        setup_requirements_version=SETUP_REQUIREMENTS_VERSION,
        ticker_blocks=MappingProxyType({}),
        consumed_fingerprint_by_ticker=MappingProxyType({ticker: MappingProxyType({"btst_breakout": CONSUMED_FP}) for ticker in TICKERS}),
    )


# --------------------------------------------------------------------------
# World: 信任上下文 + 真实 AutoProducerApi (SHADOW provider)
# --------------------------------------------------------------------------


class _AutoWorld:
    """信任上下文 + 同一 evidence DB 上的真实 ``AutoProducerApi`` (SHADOW)。"""

    def __init__(self, tmp_path: Path) -> None:
        self.clock = _Clock(NOW)
        self.auto_key = Ed25519PrivateKey.generate()
        self.auto_capability = _trust_capability(AUTO_NS)
        registry = v3_trust.TrustedRegistry(
            issuers=(
                _issuer(
                    self.auto_key,
                    self.auto_capability,
                    issuer_id="auto.producer",
                    key_id="auto-key-1",
                    kind=v3_trust.IssuerKind.SIGNAL_PRODUCER,
                ),
            )
        )
        self.verifier, self.head_provider = _root_context(registry)
        self.blob_store = BlobStore(tmp_path / "blobs")
        self.database_path = str(tmp_path / "evidence.sqlite3")
        self.auto_service = AutoProducerApi(
            database_path=self.database_path,
            blob_store=self.blob_store,
            verifier=self.verifier,
            trust_head_provider=self.head_provider,
            clock=self.clock,
            signer=self.sign_auto,
            behavior_fingerprint=AUTO_FINGERPRINT,
            runtime_mode_provider=lambda: RuntimeMode.SHADOW,
        )
        self.signed_payloads: list[bytes] = []

    def sign_auto(self, payload: bytes):
        self.signed_payloads.append(payload)
        return _signed(
            self.auto_key,
            self.auto_capability,
            issuer_id="auto.producer",
            key_id="auto-key-1",
            payload=payload,
        )


@pytest.fixture()
def auto_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _AutoWorld:
    # produce_auto_signals 内部会真实跑 BtstBreakoutSetup.detect;
    # 固定为命中 (Task 5 同款), 使每个 ticker 都产生候选 (2 个可扫候选)。
    monkeypatch.setattr(
        BtstBreakoutSetup,
        "detect",
        lambda self, ticker, trade_date, context: _hit_result(ticker),
    )
    return _AutoWorld(tmp_path)


# --------------------------------------------------------------------------
# 可注入的鸭子类型 fakes (flow 只依赖签名, 不依赖具体类型)
# --------------------------------------------------------------------------


class _FakeSnapshotLoader:
    """记录调用; 配置返回 VerifiedSnapshotResult 或抛异常。"""

    def __init__(
        self,
        result: VerifiedSnapshotResult | None = None,
        error: Exception | None = None,
    ) -> None:
        assert not (result is None and error is None), "loader needs result or error"
        self.result = result
        self.error = error
        self.calls: list[tuple[date, Path, Path]] = []

    def __call__(self, signal_date: date, *, reports_dir: Path, data_dir: Path) -> VerifiedSnapshotResult:
        self.calls.append((signal_date, reports_dir, data_dir))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class _FakeFinalizer:
    """记录 (as_of, program); 配置返回 tuple 或抛异常 (含 fence 错)。"""

    def __init__(
        self,
        result: tuple[str, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[datetime, str]] = []

    def finalize_due(self, as_of: datetime, *, program: str) -> tuple[str, ...]:
        self.calls.append((as_of, program))
        if self.error is not None:
            raise self.error
        return self.result


class _FakeProducer:
    """记录 snapshot; 配置返回 records 或抛 AutoProducerApiError。"""

    def __init__(
        self,
        result: tuple[EvidenceRecord[SignalEvidence], ...] = (),
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[VerifiedDailyActionSnapshot] = []

    def produce_and_publish(self, snapshot: VerifiedDailyActionSnapshot) -> tuple[EvidenceRecord[SignalEvidence], ...]:
        self.calls.append(snapshot)
        if self.error is not None:
            raise self.error
        return self.result


def _make_flow(
    *,
    snapshot_loader: _FakeSnapshotLoader,
    finalizer: _FakeFinalizer,
    producer: _FakeProducer,
    mode: RuntimeMode = RuntimeMode.SHADOW,
    program: str = "auto",
) -> AutoFlow:
    return AutoFlow(
        snapshot_loader=snapshot_loader,
        outcome_finalizer=finalizer,
        auto_producer=producer,
        mode_provider=lambda: mode,
        program=program,
    )


def _run(flow: AutoFlow, tmp_path: Path) -> AutoFlowResult:
    return flow.run(
        signal_date=SIGNAL_DATE,
        reports_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )


# --------------------------------------------------------------------------
# 契约测试
# --------------------------------------------------------------------------


# 2^3 组合: (snapshot_ok, outcome_ok, producer_ok) → 三个期望 status。
# 设计决策 (骨架 docstring 写死): snapshot 失败 → auto_shadow 无输入,
# 记 "skipped" + reason "no_snapshot", producer 不被调用 — 因此
# snapshot_ok=False 的行中 producer 的配置失败不会、也不应被尝试。
_COMBOS = [
    pytest.param(True, True, True, "ok", "ok", "ok", id="all_ok"),
    pytest.param(True, True, False, "ok", "ok", "failed", id="producer_fails"),
    pytest.param(True, False, True, "ok", "failed", "ok", id="outcome_fails"),
    pytest.param(True, False, False, "ok", "failed", "failed", id="outcome_and_producer_fail"),
    pytest.param(False, True, True, "failed", "ok", "skipped", id="snapshot_fails_rest_ok"),
    pytest.param(
        False,
        True,
        False,
        "failed",
        "ok",
        "skipped",
        id="snapshot_and_producer_fail_producer_not_attempted",
    ),
    pytest.param(False, False, True, "failed", "failed", "skipped", id="snapshot_and_outcome_fail"),
    pytest.param(False, False, False, "failed", "failed", "skipped", id="all_fail"),
]


@pytest.mark.parametrize(
    (
        "snapshot_ok",
        "outcome_ok",
        "producer_ok",
        "expected_snapshot",
        "expected_outcome",
        "expected_auto_shadow",
    ),
    _COMBOS,
)
def test_all_8_step_outcome_combinations(
    tmp_path: Path,
    snapshot_ok: bool,
    outcome_ok: bool,
    producer_ok: bool,
    expected_snapshot: str,
    expected_outcome: str,
    expected_auto_shadow: str,
) -> None:
    snapshot = _snapshot() if snapshot_ok else None
    loader = _FakeSnapshotLoader(result=(VerifiedSnapshotResult(snapshot=snapshot) if snapshot is not None else VerifiedSnapshotResult(snapshot=None, global_reason=MANIFEST_MISSING)))
    finalizer = _FakeFinalizer(
        result=("plan-line-1",) if outcome_ok else (),
        error=(None if outcome_ok else OutcomeFinalizerError("finalizer_down", "outcome unavailable")),
    )
    producer = _FakeProducer(
        result=("published",) if producer_ok else (),
        error=(None if producer_ok else AutoProducerApiError(AUTO_PRODUCER_NOT_SHADOW, "not shadow")),
    )
    flow = _make_flow(snapshot_loader=loader, finalizer=finalizer, producer=producer)
    result = _run(flow, tmp_path)

    assert result.snapshot_status == expected_snapshot
    assert result.outcome_status == expected_outcome
    assert result.auto_shadow_status == expected_auto_shadow
    assert result.execution_authority == "none"

    # 独立提交: snapshot/outcome 恒被尝试一次; producer 仅在 snapshot 成功时调用
    reports_dir = tmp_path / "reports"
    data_dir = tmp_path / "data"
    assert loader.calls == [(SIGNAL_DATE, reports_dir, data_dir)]
    assert finalizer.calls == [(AS_OF, "auto")]
    if snapshot_ok:
        assert producer.calls == [snapshot]
    else:
        assert producer.calls == []

    # failure_reason 精确形状 (ok 步无条目)
    expected_reason: dict[str, str] = {}
    if not snapshot_ok:
        expected_reason["snapshot"] = MANIFEST_MISSING
    if not outcome_ok:
        expected_reason["outcome"] = "OutcomeFinalizerError: finalizer_down: outcome unavailable"
    if not snapshot_ok:
        expected_reason["auto_shadow"] = "no_snapshot"
    elif not producer_ok:
        expected_reason["auto_shadow"] = f"AutoProducerApiError: {AUTO_PRODUCER_NOT_SHADOW}: not shadow"
    assert dict(result.failure_reason) == expected_reason


def test_rerun_same_day_is_idempotent(tmp_path: Path) -> None:
    loader = _FakeSnapshotLoader(result=VerifiedSnapshotResult(snapshot=_snapshot()))
    finalizer = _FakeFinalizer(result=())  # 空 tuple = 无到期行, 仍是 ok
    producer = _FakeProducer(result=("published",))
    flow = _make_flow(snapshot_loader=loader, finalizer=finalizer, producer=producer)

    first = _run(flow, tmp_path)
    second = _run(flow, tmp_path)

    assert first == second
    assert first.snapshot_status == "ok"
    assert first.outcome_status == "ok"
    assert first.auto_shadow_status == "ok"
    # rerun 是独立重放: 每步被再次尝试, 结果一致
    assert len(loader.calls) == 2
    assert len(finalizer.calls) == 2
    assert len(producer.calls) == 2


def test_unavailable_outcome_service_is_isolated(tmp_path: Path) -> None:
    loader = _FakeSnapshotLoader(result=VerifiedSnapshotResult(snapshot=_snapshot()))
    finalizer = _FakeFinalizer(error=EvidenceStoreError("outcome_store_down", "outcome store unavailable"))
    producer = _FakeProducer(result=("published",))
    flow = _make_flow(snapshot_loader=loader, finalizer=finalizer, producer=producer)

    result = _run(flow, tmp_path)

    assert result.snapshot_status == "ok"
    assert result.outcome_status == "failed"
    assert result.auto_shadow_status == "ok"
    assert "outcome_store_down" in result.failure_reason["outcome"]
    assert len(producer.calls) == 1  # outcome 失败不阻止 auto_shadow


def test_unavailable_producer_service_is_isolated(tmp_path: Path) -> None:
    loader = _FakeSnapshotLoader(result=VerifiedSnapshotResult(snapshot=_snapshot()))
    finalizer = _FakeFinalizer()
    producer = _FakeProducer(error=AutoProducerApiError(AUTO_PRODUCER_NOT_SHADOW, "not shadow"))
    flow = _make_flow(snapshot_loader=loader, finalizer=finalizer, producer=producer)

    result = _run(flow, tmp_path)

    assert result.snapshot_status == "ok"
    assert result.outcome_status == "ok"
    assert result.auto_shadow_status == "failed"
    assert AUTO_PRODUCER_NOT_SHADOW in result.failure_reason["auto_shadow"]
    assert len(producer.calls) == 1  # 失败前确实被尝试过


def test_snapshot_manifest_missing_blocks_only_auto_shadow(tmp_path: Path) -> None:
    loader = _FakeSnapshotLoader(result=VerifiedSnapshotResult(snapshot=None, global_reason=MANIFEST_MISSING))
    finalizer = _FakeFinalizer(result=("plan-line-1",))
    producer = _FakeProducer(result=("published",))
    flow = _make_flow(snapshot_loader=loader, finalizer=finalizer, producer=producer)

    result = _run(flow, tmp_path)

    assert result.snapshot_status == "failed"
    assert result.failure_reason["snapshot"] == MANIFEST_MISSING
    # outcome 独立于 snapshot 照常执行
    assert result.outcome_status == "ok"
    assert len(finalizer.calls) == 1
    # auto_shadow 无输入 → skipped + reason, 不调用 producer
    assert result.auto_shadow_status == "skipped"
    assert result.failure_reason["auto_shadow"] == "no_snapshot"
    assert producer.calls == []


def test_snapshot_loader_exception_is_isolated(tmp_path: Path) -> None:
    loader = _FakeSnapshotLoader(error=SnapshotLoadError("read failed"))
    finalizer = _FakeFinalizer(result=("plan-line-1",))
    producer = _FakeProducer(result=("published",))
    flow = _make_flow(snapshot_loader=loader, finalizer=finalizer, producer=producer)

    result = _run(flow, tmp_path)

    assert result.snapshot_status == "failed"
    assert "SnapshotLoadError: read failed" in result.failure_reason["snapshot"]
    assert result.outcome_status == "ok"
    assert result.auto_shadow_status == "skipped"
    assert result.failure_reason["auto_shadow"] == "no_snapshot"
    assert producer.calls == []


def test_correction_pending_fence_marks_outcome_failed(tmp_path: Path) -> None:
    loader = _FakeSnapshotLoader(result=VerifiedSnapshotResult(snapshot=_snapshot()))
    finalizer = _FakeFinalizer(
        error=DependencyFixError(
            "fence_not_active",
            "revision activation requires an ACTIVE dependency-fix manifest",
        )
    )
    producer = _FakeProducer(result=("published",))
    flow = _make_flow(snapshot_loader=loader, finalizer=finalizer, producer=producer)

    result = _run(flow, tmp_path)

    assert result.outcome_status == "failed"
    assert "fence_not_active" in result.failure_reason["outcome"]
    assert result.snapshot_status == "ok"
    assert result.auto_shadow_status == "ok"
    assert len(producer.calls) == 1


def test_execution_authority_is_always_none(tmp_path: Path) -> None:
    # dataclass 默认值: 未显式传入也是 "none"
    plain = AutoFlowResult(snapshot_status="ok", outcome_status="ok", auto_shadow_status="ok")
    assert plain.execution_authority == "none"
    assert plain.failure_reason == {}

    # 混合失败组合下仍为 "none"
    loader = _FakeSnapshotLoader(result=VerifiedSnapshotResult(snapshot=None, global_reason=MANIFEST_MISSING))
    finalizer = _FakeFinalizer(error=EvidenceStoreError("outcome_store_down", "unavailable"))
    flow = _make_flow(
        snapshot_loader=loader,
        finalizer=finalizer,
        producer=_FakeProducer(),
        mode=RuntimeMode.SHADOW,
    )
    result = _run(flow, tmp_path)
    assert result.snapshot_status == "failed"
    assert result.outcome_status == "failed"
    assert result.auto_shadow_status == "skipped"
    assert result.execution_authority == "none"


def test_off_mode_skips_everything_with_zero_calls(tmp_path: Path) -> None:
    loader = _FakeSnapshotLoader(result=VerifiedSnapshotResult(snapshot=_snapshot()))
    finalizer = _FakeFinalizer(result=("plan-line-1",))
    producer = _FakeProducer(result=("published",))
    flow = _make_flow(
        snapshot_loader=loader,
        finalizer=finalizer,
        producer=producer,
        mode=RuntimeMode.OFF,
    )

    result = _run(flow, tmp_path)

    assert result.snapshot_status == "skipped"
    assert result.outcome_status == "skipped"
    assert result.auto_shadow_status == "skipped"
    assert result.execution_authority == "none"
    assert result.failure_reason == {}
    # legacy 行为不变: 三步零调用
    assert loader.calls == []
    assert finalizer.calls == []
    assert producer.calls == []


def test_shadow_mode_runs_all_three_steps(tmp_path: Path) -> None:
    loader = _FakeSnapshotLoader(result=VerifiedSnapshotResult(snapshot=_snapshot()))
    finalizer = _FakeFinalizer(result=("plan-line-1",))
    producer = _FakeProducer(result=("published",))
    flow = _make_flow(
        snapshot_loader=loader,
        finalizer=finalizer,
        producer=producer,
        mode=RuntimeMode.SHADOW,
    )

    result = _run(flow, tmp_path)

    assert result.snapshot_status == "ok"
    assert result.outcome_status == "ok"
    assert result.auto_shadow_status == "ok"
    assert len(loader.calls) == 1
    assert len(finalizer.calls) == 1
    assert len(producer.calls) == 1


@pytest.mark.parametrize("mode", [RuntimeMode.BTST_CANARY, RuntimeMode.AUTHORITATIVE])
def test_non_shadow_active_modes_skip_auto_shadow_only(tmp_path: Path, mode: RuntimeMode) -> None:
    loader = _FakeSnapshotLoader(result=VerifiedSnapshotResult(snapshot=_snapshot()))
    finalizer = _FakeFinalizer(result=("plan-line-1",))
    producer = _FakeProducer(result=("published",))
    flow = _make_flow(
        snapshot_loader=loader,
        finalizer=finalizer,
        producer=producer,
        mode=mode,
    )

    result = _run(flow, tmp_path)

    assert result.snapshot_status == "ok"
    assert result.outcome_status == "ok"
    assert result.auto_shadow_status == "skipped"
    assert result.failure_reason["auto_shadow"] == "not_shadow_mode"
    assert len(loader.calls) == 1
    assert len(finalizer.calls) == 1
    assert producer.calls == []


def test_program_is_forwarded_to_finalize_due(tmp_path: Path) -> None:
    loader = _FakeSnapshotLoader(result=VerifiedSnapshotResult(snapshot=_snapshot()))
    finalizer = _FakeFinalizer()
    flow = _make_flow(
        snapshot_loader=loader,
        finalizer=finalizer,
        producer=_FakeProducer(),
        program="daily-action",
    )

    result = _run(flow, tmp_path)

    assert result.outcome_status == "ok"
    assert finalizer.calls == [(AS_OF, "daily-action")]


def test_real_auto_producer_shadow_mode_publishes_signed_evidence(auto_world: _AutoWorld, tmp_path: Path) -> None:
    loader = _FakeSnapshotLoader(result=VerifiedSnapshotResult(snapshot=_snapshot()))
    finalizer = _FakeFinalizer(result=())
    flow = AutoFlow(
        snapshot_loader=loader,
        outcome_finalizer=finalizer,
        auto_producer=auto_world.auto_service,
        mode_provider=lambda: RuntimeMode.SHADOW,
    )

    result = _run(flow, tmp_path)

    assert result.snapshot_status == "ok"
    assert result.outcome_status == "ok"
    assert result.auto_shadow_status == "ok"
    assert result.execution_authority == "none"
    assert result.failure_reason == {}
    # 真实 funnel: 2 候选 × (CANDIDATE → SELECTED) = 4 枚签名信封
    assert len(auto_world.signed_payloads) == 4


def test_real_auto_producer_gate_failure_is_isolated(auto_world: _AutoWorld, tmp_path: Path) -> None:
    gated = AutoProducerApi(
        database_path=auto_world.database_path,
        blob_store=auto_world.blob_store,
        verifier=auto_world.verifier,
        trust_head_provider=auto_world.head_provider,
        clock=auto_world.clock,
        signer=auto_world.sign_auto,
        behavior_fingerprint=AUTO_FINGERPRINT,
        # producer 侧 provider 与 flow 投影不一致 (配置错误) → 门拒绝
        runtime_mode_provider=lambda: RuntimeMode.OFF,
    )
    flow = AutoFlow(
        snapshot_loader=_FakeSnapshotLoader(result=VerifiedSnapshotResult(snapshot=_snapshot())),
        outcome_finalizer=_FakeFinalizer(result=()),
        auto_producer=gated,
        mode_provider=lambda: RuntimeMode.SHADOW,
    )

    result = _run(flow, tmp_path)

    assert result.snapshot_status == "ok"
    assert result.outcome_status == "ok"
    assert result.auto_shadow_status == "failed"
    assert AUTO_PRODUCER_NOT_SHADOW in result.failure_reason["auto_shadow"]
    # 门在签名前拒绝 → 零签名、零触达 store
    assert auto_world.signed_payloads == []
