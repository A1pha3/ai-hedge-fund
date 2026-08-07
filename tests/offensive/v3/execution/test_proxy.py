"""Plan 04 Task 8: DAILY_BAR_PROXY open execution against daily bars.

The proxy resolves every ALLOW permit line against the target-session
daily bar under the locked decision table:

- missing bar, suspension, or a late command (issued after the execution
  window's gateway send deadline) resolve UNKNOWN and keep the cash;
- a one-price limit lock (open == high == low == close == limit) is
  ambiguous for the locked side: one daily bar can never prove the
  order's queue position, so a buy into a one-price limit-up or a sell
  into a one-price limit-down resolves UNKNOWN;
- an ordinary limit touch fills at min(open, limit) for buys and
  max(open, limit) for sells, never worse than the sealed worst-case
  price, with fees pinned to the injected fee-policy (cost) version;
- an untouched limit resolves NO_FILL.

No known executable open means unknown/cash, never a stale-close fill:
a close inside the limit can never rescue a bar whose open is unproven.
FILLED lines land in the capital kernel as attributed, reserve-consuming
revisions whose worst-case surplus is released; UNKNOWN/NO_FILL lines
release their remaining reserve. Resolutions are durable, idempotent
under replay, conflicting on divergent replay, and replayable to a
complete state after crashes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.screening.offensive.v3.capital.fees import FeePolicy
from src.screening.offensive.v3.capital.repository import (
    AccountBinding,
    CapitalCommand,
    CapitalCommandPayload,
    CapitalRepository,
)
from src.screening.offensive.v3.capital.reserves import ReserveEntryRequest
from src.screening.offensive.v3.contracts import (
    CashEconomicEventLeg,
    CashReceivableEconomicEventLeg,
    EconomicAssetKind,
    EconomicEventKind,
    EconomicLegDirection,
    ExecutionMode,
    ExecutionSide,
)
from src.screening.offensive.v3.execution.lifecycle import (
    DailyBar,
    ExecutionError,
    OpenExecutionResolution,
    OpenExecutionVerdict,
    resolve_open_execution,
)
from src.screening.offensive.v3.execution.proxy import (
    DailyBarProxy,
    ProxyExecutionContext,
    ProxyExecutionResult,
)
from tests.offensive.v3.contracts.checkpoint2_helpers import (
    AUTHORIZATION_ID,
    AUTHORIZATION_VERSION,
    BROKER_CUTOFF,
    CLOSE_FINALIZED,
    EVIDENCE_ROOT,
    HASH_A,
    HASH_B,
    HASH_C,
    HASH_D,
    HASH_E,
    PORTFOLIO_ID,
    SEND_DEADLINE,
    SIGNAL_SESSION,
    STAGE_ID,
    TARGET_SESSION,
    _api,
    _permit,
    _permit_line,
    _seal,
    _window,
)

UTC = timezone.utc
# The proxy executes at the T+1 opening auction; the command itself must
# have been issued inside the T0 evening execution window.
NOW = datetime(2026, 7, 30, 1, 25, tzinfo=UTC)
SEED_T0 = datetime(2026, 7, 29, 7, 0, tzinfo=UTC)
COMMAND_AT = datetime(2026, 7, 29, 8, 2, 30, tzinfo=UTC)  # before SEND_DEADLINE
LATE_COMMAND_AT = datetime(2026, 7, 30, 1, 24, tzinfo=UTC)  # past the deadline

# Versioned fee policy copied from the Plan 02 capital tests: 30bps
# commission with a 5 yuan per-order minimum, 10bps sell-side stamp tax,
# 2bps transfer fee.
POLICY_V1 = FeePolicy(
    fee_policy_version="fee-schedule-2026-v1",
    commission_rate_ppm=3_000,
    min_commission_cents=500,
    stamp_tax_rate_ppm=1_000,
    transfer_fee_rate_ppm=20,
)

# Proxy mode binds no broker account and no environment fingerprint.
PROXY_BINDING = AccountBinding(
    portfolio_id=PORTFOLIO_ID,
    mode=ExecutionMode.DAILY_BAR_PROXY,
    broker_account_id=None,
    base_currency="CNY",
    environment_fingerprint=None,
)

# Reserve amounts of the two sealed lines (worst case price x qty + fee).
LINE_1_RESERVE = 1_050 * 100 + 50  # 105_050
LINE_2_RESERVE = 800 * 200 + 75  # 160_075


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


@pytest.fixture()
def clock() -> _Clock:
    return _Clock(NOW)


@pytest.fixture()
def api() -> SimpleNamespace:
    return _api()


@pytest.fixture()
def repository(tmp_path) -> CapitalRepository:
    return CapitalRepository.initialize(tmp_path / "capital.sqlite3")


@pytest.fixture()
def seal(api):
    return _proxy_seal(api)


@pytest.fixture()
def permit(api, seal):
    return _proxy_permit(api, seal)


@pytest.fixture()
def proxy(tmp_path, clock) -> DailyBarProxy:
    return DailyBarProxy(
        database_path=str(tmp_path / "proxy.sqlite3"),
        clock=clock,
    )


@pytest.fixture()
def capital(repository: CapitalRepository, seal) -> CapitalRepository:
    """A bound proxy ledger with seed cash and both sealed reserves live."""

    _deposit(repository, 1_000_000, 1)
    _seed_reserves(repository, seal)
    return repository


# -- proxy-mode seal/permit world --------------------------------------------
#
# The checkpoint-2 helpers hardcode BROKER_CONFIRMED with a bound broker
# account, which the contracts forbid for DAILY_BAR_PROXY (proxy execution
# cannot bind a broker account, and the issuer capability mode must equal
# the artifact mode). These builders mirror the helper structure with
# mode=DAILY_BAR_PROXY and broker_account_id=None everywhere.


def _proxy_plan(api, *, suffix: str = "1", economic_lineage_id: str = "btst-lineage-a"):
    return api.PlanEvidence(
        evidence_id=f"plan-{suffix}",
        subject_scope=api.EvidenceScope.STRATEGY_LINEAGE,
        subject_producer="btst",
        family_id="btst-family",
        strategy_semver="3.0.0",
        behavior_fingerprint=HASH_A,
        policy_epoch=4,
        execution_version="t1-open-t10-open.v1",
        cost_version="cn-a-share.v1",
        effective_at=CLOSE_FINALIZED,
        provider_published_at=CLOSE_FINALIZED,
        observed_at=CLOSE_FINALIZED,
        available_at=CLOSE_FINALIZED,
        mode=api.ExecutionMode.DAILY_BAR_PROXY,
        source_authority="btst-producer",
        payload_content_hash=HASH_B,
        schema_major=2,
        evidence_kind="plan",
        portfolio_id=PORTFOLIO_ID,
        signal_session=SIGNAL_SESSION,
        economic_lineage_id=economic_lineage_id,
        snapshot_id=f"signal-snapshot-{suffix}",
        raw_target_fraction=Decimal("0.01"),
        created_at=CLOSE_FINALIZED,
    )


def _proxy_line(api, *, suffix: str = "1", security_id: str = "600000.SH"):
    is_first = suffix == "1"
    lineage = "btst-lineage-a" if is_first else "btst-lineage-b"
    program = "btst-program-a" if is_first else "btst-program-b"
    stage = STAGE_ID if is_first else "stage-broker-2pct-b"
    plan = _proxy_plan(api, suffix=suffix, economic_lineage_id=lineage)
    plan_record = api.EvidenceRecord[api.PlanEvidence](
        evidence=plan,
        ingested_at=plan.available_at,
        commit_sequence=int(suffix),
        revision=1,
        supersedes_revision=None,
        active_revision=1,
    )
    quantity = 100 if suffix == "1" else 200
    price = 1_050 if suffix == "1" else 800
    fee = 50 if suffix == "1" else 75
    return api.PortfolioOrderLine(
        order_line_id=f"line-{suffix}",
        security_id=security_id,
        order_action="ENTRY",
        producer_namespace="btst",
        family_id="btst-family",
        economic_lineage_id=lineage,
        research_program_id=program,
        stage_id=stage,
        stage_manifest_hash=HASH_C,
        grant_id=f"grant-{lineage}",
        grant_certificate_hash=HASH_D,
        authorization_id=AUTHORIZATION_ID,
        authorization_version=AUTHORIZATION_VERSION,
        plan_evidence=plan_record,
        plan_evidence_artifact_hash=plan_record.artifact_hash(),
        plan_payload_content_hash=plan.payload_content_hash,
        mode=api.ExecutionMode.DAILY_BAR_PROXY,
        target_entry_session=TARGET_SESSION,
        exit_session_ordinal=10,
        sealed_quantity_units=quantity,
        lot_size_units=100,
        lot_rule_version="cn-a-share-lot.v1",
        order_type="LIMIT",
        limit_price_cents=price,
        worst_case_price_cents=price,
        price_boundary_version="cn-price-limit.v1",
        time_in_force="OPEN_AUCTION",
        worst_case_fee_reserve_cents=fee,
        worst_case_cash_reserve_cents=price * quantity + fee,
    )


def _proxy_proposal(api):
    lines = (
        _proxy_line(api),
        _proxy_line(api, suffix="2", security_id="600001.SH"),
    )
    return api.PortfolioDecision(
        logical_key=api.DecisionLogicalKey(
            portfolio_id=PORTFOLIO_ID,
            signal_session=SIGNAL_SESSION,
            decision_cycle_id="daily-t1-open-v1",
        ),
        portfolio_id=PORTFOLIO_ID,
        broker_account_id=None,
        broker_account_fingerprint=None,
        base_currency="CNY",
        mode=api.ExecutionMode.DAILY_BAR_PROXY,
        target_entry_session=TARGET_SESSION,
        target_portfolio_policy_fingerprint=HASH_E,
        policy_activation_hash=HASH_A,
        trust_bundle_hash=HASH_B,
        registry_epoch=7,
        policy_epoch=4,
        authority_epoch=5,
        risk_epoch=6,
        authorization_id=AUTHORIZATION_ID,
        authorization_version=AUTHORIZATION_VERSION,
        authorization_artifact_hash=HASH_C,
        evidence_set_merkle_root=EVIDENCE_ROOT,
        risk_snapshot_id="risk-snapshot-1",
        risk_snapshot_artifact_hash=HASH_D,
        risk_snapshot_as_of=CLOSE_FINALIZED,
        capital_version=10,
        capital_stream_version=29,
        writer_fencing_epoch=11,
        order_lines=lines,
        total_worst_case_cash_reserve_cents=sum(
            line.worst_case_cash_reserve_cents for line in lines
        ),
        decision_cutoff=CLOSE_FINALIZED + timedelta(seconds=30),
        proposal_created_at=CLOSE_FINALIZED + timedelta(seconds=45),
        schema_major=2,
    )


def _proxy_issuer(api, artifact_kind, namespace):
    return api.GatewayIssuerBinding(
        issuer_id="capital-gateway.service",
        key_id="capital-gateway-key-1",
        capability_artifact_kind=artifact_kind,
        capability_namespace=namespace,
        capability_mode=api.ExecutionMode.DAILY_BAR_PROXY,
        capability_schema_major=2,
        capability_version="capital-gateway.v1",
        capability_scope=f"portfolio:{PORTFOLIO_ID}",
        verification_result="VALID",
        verified_at=CLOSE_FINALIZED,
        valid_until=BROKER_CUTOFF,
        trust_bundle_hash=HASH_B,
        registry_epoch=7,
    )


def _proxy_seal(api, **overrides):
    return _seal(
        api,
        proposal=_proxy_proposal(api),
        issuer_binding=_proxy_issuer(
            api,
            api.ArtifactKind.PORTFOLIO_DECISION_SEAL,
            "capital-gateway.entry-seal.v1",
        ),
        **overrides,
    )


def _proxy_permit(api, seal=None, **overrides):
    if seal is None:
        seal = _proxy_seal(api)
    return _permit(
        api,
        seal=seal,
        issuer_binding=_proxy_issuer(
            api,
            api.ArtifactKind.EXECUTION_PERMIT,
            "capital-gateway.entry-permit.v1",
        ),
        **overrides,
    )


# -- daily bar builders --------------------------------------------------------


def _bar(
    security_id: str,
    *,
    session: date = TARGET_SESSION,
    open_cents: int,
    high_cents: int,
    low_cents: int,
    close_cents: int,
    limit_up_cents: int,
    limit_down_cents: int,
    suspended: bool = False,
) -> DailyBar:
    return DailyBar(
        security_id=security_id,
        session=session,
        open_cents=open_cents,
        high_cents=high_cents,
        low_cents=low_cents,
        close_cents=close_cents,
        limit_up_cents=limit_up_cents,
        limit_down_cents=limit_down_cents,
        suspended=suspended,
    )


def _one_price_limit_up_bar(
    security_id: str,
    *,
    session: date = TARGET_SESSION,
    limit_up_cents: int,
    limit_down_cents: int,
    suspended: bool = False,
) -> DailyBar:
    return _bar(
        security_id,
        session=session,
        open_cents=limit_up_cents,
        high_cents=limit_up_cents,
        low_cents=limit_up_cents,
        close_cents=limit_up_cents,
        limit_up_cents=limit_up_cents,
        limit_down_cents=limit_down_cents,
        suspended=suspended,
    )


def _one_price_limit_down_bar(
    security_id: str,
    *,
    session: date = TARGET_SESSION,
    limit_up_cents: int,
    limit_down_cents: int,
    suspended: bool = False,
) -> DailyBar:
    return _bar(
        security_id,
        session=session,
        open_cents=limit_down_cents,
        high_cents=limit_down_cents,
        low_cents=limit_down_cents,
        close_cents=limit_down_cents,
        limit_up_cents=limit_up_cents,
        limit_down_cents=limit_down_cents,
        suspended=suspended,
    )


def _touching_bar(security_id: str) -> DailyBar:
    if security_id == "600000.SH":
        return _bar(
            security_id,
            open_cents=1_040,
            high_cents=1_060,
            low_cents=1_030,
            close_cents=1_055,
            limit_up_cents=1_155,
            limit_down_cents=945,
        )
    return _bar(
        security_id,
        open_cents=795,
        high_cents=810,
        low_cents=790,
        close_cents=805,
        limit_up_cents=880,
        limit_down_cents=720,
    )


def _touching_bars() -> dict[str, DailyBar]:
    return {
        "600000.SH": _touching_bar("600000.SH"),
        "600001.SH": _touching_bar("600001.SH"),
    }


# -- capital world -------------------------------------------------------------


def _seed_moment(step: int) -> datetime:
    return SEED_T0 + timedelta(minutes=step)


def _deposit(repository: CapitalRepository, cents: int, sequence: int) -> None:
    """Seed cash with the only inflow available before Task 3 genesis."""

    amount = Decimal(cents) / 100
    receivable_id = f"rcv-{sequence}"
    repository.append_atomic(
        CapitalCommand(
            idempotency_key=f"declare-{sequence}",
            account_binding=PROXY_BINDING,
            expected_stream_version=repository.stream_version(),
            as_of=_seed_moment(sequence),
            payload=CapitalCommandPayload(
                event_kind=EconomicEventKind.DIVIDEND_RECEIVABLE,
                effective_at=_seed_moment(sequence),
                source_authority="test.seed",
                legs=(
                    CashReceivableEconomicEventLeg(
                        leg_id=f"declare-{sequence}-r",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=receivable_id,
                        security_id="000001.SZ",
                        cash_amount=amount,
                    ),
                ),
            ),
        )
    )
    repository.append_atomic(
        CapitalCommand(
            idempotency_key=f"settle-{sequence}",
            account_binding=PROXY_BINDING,
            expected_stream_version=repository.stream_version(),
            as_of=_seed_moment(sequence) + timedelta(seconds=30),
            payload=CapitalCommandPayload(
                event_kind=EconomicEventKind.DIVIDEND_CASH_SETTLED,
                effective_at=_seed_moment(sequence) + timedelta(seconds=30),
                source_authority="test.seed",
                legs=(
                    CashReceivableEconomicEventLeg(
                        leg_id=f"settle-{sequence}-r",
                        direction=EconomicLegDirection.DEBIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=receivable_id,
                        security_id="000001.SZ",
                        cash_amount=amount,
                    ),
                    CashEconomicEventLeg(
                        leg_id=f"settle-{sequence}-c",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.CASH,
                        cash_amount=amount,
                    ),
                ),
            ),
        )
    )


def _seed_reserves(
    repository: CapitalRepository,
    seal,
    *,
    amounts: dict[str, int] | None = None,
) -> None:
    """Open the live reserves the seal admission would have created."""

    amounts = amounts or {}
    lines_by_id = {line.order_line_id: line for line in seal.proposal.order_lines}
    for step, item in enumerate(seal.line_reserve_bindings, start=2):
        order_line = lines_by_id[item.order_line_id]
        repository.reserve_entry(
            ReserveEntryRequest(
                source_id=item.reservation_allocation_id,
                research_program_id=order_line.research_program_id,
                economic_lineage_id=order_line.economic_lineage_id,
                stage_id=order_line.stage_id,
                reserved_entry_gross_cents=amounts.get(
                    item.order_line_id, item.reserved_cash_cents
                ),
                expected_stream_version=repository.stream_version(),
                as_of=_seed_moment(step),
            )
        )


def _context(
    repository: CapitalRepository,
    *,
    command_at: datetime = COMMAND_AT,
) -> ProxyExecutionContext:
    return ProxyExecutionContext(
        repository=repository,
        command_at=command_at,
        source_authority="daily-bar-proxy.v1",
    )


def _execute(
    proxy: DailyBarProxy,
    repository: CapitalRepository,
    seal,
    permit,
    *,
    bars: dict[str, DailyBar] | None = None,
    command_at: datetime = COMMAND_AT,
) -> ProxyExecutionResult:
    if bars is None:
        bars = _touching_bars()
    return proxy.execute_open(
        seal=seal,
        permit=permit,
        bars=bars,
        fee_policy=POLICY_V1,
        context=_context(repository, command_at=command_at),
    )


# =============================================================================
# Pure resolution: the locked decision table
# =============================================================================


def _resolve(
    bar: DailyBar | None,
    *,
    side: ExecutionSide = ExecutionSide.ENTRY,
    limit_price_cents: int = 1_050,
    command_at: datetime = COMMAND_AT,
    send_deadline: datetime = SEND_DEADLINE,
) -> OpenExecutionResolution:
    return resolve_open_execution(
        side=side,
        limit_price_cents=limit_price_cents,
        bar=bar,
        command_at=command_at,
        send_deadline=send_deadline,
    )


def test_missing_bar_is_unknown_and_never_fills() -> None:
    resolution = _resolve(None)
    assert resolution.verdict is OpenExecutionVerdict.UNKNOWN
    assert resolution.fill_price_cents is None
    assert resolution.reason == "missing_bar"


def test_suspended_bar_is_unknown_and_never_fills() -> None:
    bar = _bar(
        "600000.SH",
        open_cents=1_040,
        high_cents=1_060,
        low_cents=1_030,
        close_cents=1_055,
        limit_up_cents=1_155,
        limit_down_cents=945,
        suspended=True,
    )
    resolution = _resolve(bar)
    assert resolution.verdict is OpenExecutionVerdict.UNKNOWN
    assert resolution.fill_price_cents is None
    assert resolution.reason == "suspended_bar"


def test_late_command_is_unknown_even_when_limit_touched() -> None:
    resolution = _resolve(_touching_bar("600000.SH"), command_at=LATE_COMMAND_AT)
    assert resolution.verdict is OpenExecutionVerdict.UNKNOWN
    assert resolution.fill_price_cents is None
    assert resolution.reason == "late_command"


def test_command_at_send_deadline_is_not_late() -> None:
    # "Late" means strictly after the gateway send deadline; a command at
    # the exact deadline still resolves on the bar.
    resolution = _resolve(_touching_bar("600000.SH"), command_at=SEND_DEADLINE)
    assert resolution.verdict is OpenExecutionVerdict.FILLED
    assert resolution.fill_price_cents == 1_040


def test_one_price_limit_up_buy_is_unknown() -> None:
    # Buy limit == locked price: price-wise the order could have filled,
    # but one daily bar cannot prove its queue position.
    bar = _one_price_limit_up_bar("600000.SH", limit_up_cents=1_050, limit_down_cents=945)
    resolution = _resolve(bar, limit_price_cents=1_050)
    assert resolution.verdict is OpenExecutionVerdict.UNKNOWN
    assert resolution.fill_price_cents is None
    assert resolution.reason == "one_price_limit_up"


def test_one_price_limit_up_buy_never_uses_stale_close() -> None:
    # The stale-close trap: close == limit_up == buy limit sits "within
    # limit", yet the open is unproven so the close must not rescue it.
    bar = _one_price_limit_up_bar("600000.SH", limit_up_cents=1_050, limit_down_cents=945)
    resolution = _resolve(bar, limit_price_cents=1_050)
    assert resolution.verdict is OpenExecutionVerdict.UNKNOWN
    assert resolution.fill_price_cents is None
    assert resolution.reason != "limit_touched"


def test_one_price_limit_down_sell_is_unknown() -> None:
    bar = _one_price_limit_down_bar("600001.SH", limit_up_cents=880, limit_down_cents=800)
    resolution = _resolve(
        bar, side=ExecutionSide.EXIT, limit_price_cents=800
    )
    assert resolution.verdict is OpenExecutionVerdict.UNKNOWN
    assert resolution.fill_price_cents is None
    assert resolution.reason == "one_price_limit_down"


def test_one_price_limit_down_sell_never_uses_stale_close() -> None:
    # Symmetric stale-close trap on the sell side.
    bar = _one_price_limit_down_bar("600001.SH", limit_up_cents=880, limit_down_cents=800)
    resolution = _resolve(
        bar, side=ExecutionSide.EXIT, limit_price_cents=800
    )
    assert resolution.verdict is OpenExecutionVerdict.UNKNOWN
    assert resolution.fill_price_cents is None
    assert resolution.reason != "limit_touched"


def test_one_price_limit_down_buy_fills_at_open() -> None:
    # A locked limit-down day has endless sellers: the buy provably
    # executes at the locked price (the ambiguity is one-directional).
    bar = _one_price_limit_down_bar("600000.SH", limit_up_cents=1_155, limit_down_cents=945)
    resolution = _resolve(bar, limit_price_cents=1_050)
    assert resolution.verdict is OpenExecutionVerdict.FILLED
    assert resolution.fill_price_cents == 945  # min(open, limit)


def test_one_price_limit_up_sell_fills_at_open() -> None:
    bar = _one_price_limit_up_bar("600001.SH", limit_up_cents=880, limit_down_cents=720)
    resolution = _resolve(
        bar, side=ExecutionSide.EXIT, limit_price_cents=800
    )
    assert resolution.verdict is OpenExecutionVerdict.FILLED
    assert resolution.fill_price_cents == 880  # max(open, limit)


def test_flat_bar_off_limit_fills_normally() -> None:
    # One-price ambiguity exists only AT the limit lock: a flat bar inside
    # the band proves the open like any other bar.
    bar = _bar(
        "600000.SH",
        open_cents=1_000,
        high_cents=1_000,
        low_cents=1_000,
        close_cents=1_000,
        limit_up_cents=1_155,
        limit_down_cents=945,
    )
    resolution = _resolve(bar, limit_price_cents=1_050)
    assert resolution.verdict is OpenExecutionVerdict.FILLED
    assert resolution.fill_price_cents == 1_000


def test_ordinary_touch_buy_fills_at_min_open_limit() -> None:
    below = _resolve(_touching_bar("600000.SH"), limit_price_cents=1_050)
    assert below.verdict is OpenExecutionVerdict.FILLED
    assert below.fill_price_cents == 1_040  # open < limit: open wins
    assert below.reason == "limit_touched"
    at_limit = _bar(
        "600000.SH",
        open_cents=1_050,
        high_cents=1_060,
        low_cents=1_045,
        close_cents=1_055,
        limit_up_cents=1_155,
        limit_down_cents=945,
    )
    resolution = _resolve(at_limit, limit_price_cents=1_050)
    assert resolution.verdict is OpenExecutionVerdict.FILLED
    assert resolution.fill_price_cents == 1_050  # min(open, limit)


def test_ordinary_touch_sell_fills_at_max_open_limit() -> None:
    above = _bar(
        "600001.SH",
        open_cents=810,
        high_cents=815,
        low_cents=795,
        close_cents=808,
        limit_up_cents=880,
        limit_down_cents=720,
    )
    resolution = _resolve(
        above, side=ExecutionSide.EXIT, limit_price_cents=800
    )
    assert resolution.verdict is OpenExecutionVerdict.FILLED
    assert resolution.fill_price_cents == 810  # open > limit: open wins
    at_limit = _bar(
        "600001.SH",
        open_cents=800,
        high_cents=812,
        low_cents=795,
        close_cents=808,
        limit_up_cents=880,
        limit_down_cents=720,
    )
    resolution = _resolve(
        at_limit, side=ExecutionSide.EXIT, limit_price_cents=800
    )
    assert resolution.verdict is OpenExecutionVerdict.FILLED
    assert resolution.fill_price_cents == 800  # max(open, limit)


def test_untouched_buy_is_no_fill() -> None:
    bar = _bar(
        "600000.SH",
        open_cents=1_060,
        high_cents=1_070,
        low_cents=1_055,
        close_cents=1_065,
        limit_up_cents=1_155,
        limit_down_cents=945,
    )
    resolution = _resolve(bar, limit_price_cents=1_050)
    # low 1055 > limit 1050: the order provably never traded.
    assert resolution.verdict is OpenExecutionVerdict.NO_FILL
    assert resolution.fill_price_cents is None
    assert resolution.reason == "limit_not_touched"


def test_untouched_sell_is_no_fill() -> None:
    bar = _bar(
        "600001.SH",
        open_cents=785,
        high_cents=795,
        low_cents=780,
        close_cents=790,
        limit_up_cents=880,
        limit_down_cents=720,
    )
    resolution = _resolve(
        bar, side=ExecutionSide.EXIT, limit_price_cents=800
    )
    # high 795 < limit 800.
    assert resolution.verdict is OpenExecutionVerdict.NO_FILL
    assert resolution.fill_price_cents is None
    assert resolution.reason == "limit_not_touched"


def test_daily_bar_one_price_limit_properties() -> None:
    up = _one_price_limit_up_bar("600000.SH", limit_up_cents=1_155, limit_down_cents=945)
    assert up.is_one_price_limit_up is True
    assert up.is_one_price_limit_down is False
    down = _one_price_limit_down_bar("600000.SH", limit_up_cents=1_155, limit_down_cents=945)
    assert down.is_one_price_limit_down is True
    assert down.is_one_price_limit_up is False
    ordinary = _touching_bar("600000.SH")
    assert ordinary.is_one_price_limit_up is False
    assert ordinary.is_one_price_limit_down is False
    flat_off_limit = _bar(
        "600000.SH",
        open_cents=1_000,
        high_cents=1_000,
        low_cents=1_000,
        close_cents=1_000,
        limit_up_cents=1_155,
        limit_down_cents=945,
    )
    # Four equal prices away from the limits are not a limit lock.
    assert flat_off_limit.is_one_price_limit_up is False
    assert flat_off_limit.is_one_price_limit_down is False


# =============================================================================
# Proxy execution: pre-sealed T+1 open against the capital kernel
# =============================================================================


def test_execute_open_fills_pre_sealed_t1_open(proxy, capital, seal, permit) -> None:
    result = _execute(proxy, capital, seal, permit)
    assert result.seal_id == seal.seal_id
    assert result.permit_id == permit.permit_id
    assert tuple(line.order_line_id for line in result.lines) == ("line-1", "line-2")

    first, second = result.lines
    assert first.client_order_id == "client-line-1"
    assert first.verdict is OpenExecutionVerdict.FILLED
    assert first.fill_price_cents == 1_040
    assert first.fill_receipt is not None
    assert first.fill_receipt.order_id == "client-line-1"
    assert first.fill_receipt.side is ExecutionSide.ENTRY
    assert first.fill_receipt.quantity == 100
    assert first.fill_receipt.gross_cents == 104_000
    assert first.fill_receipt.unattributed is False
    assert first.fill_receipt.reserve_consumed_cents == LINE_1_RESERVE
    assert first.fee_receipt is not None
    assert first.fee_receipt.fee_policy_version == POLICY_V1.fee_policy_version
    assert first.fee_receipt.total_cents == 502
    # The worst-case surplus over the real fill returns to cash.
    assert first.released_reserve_cents == LINE_1_RESERVE - 104_000

    assert second.client_order_id == "client-line-2"
    assert second.verdict is OpenExecutionVerdict.FILLED
    assert second.fill_price_cents == 795
    assert second.fill_receipt is not None
    assert second.fill_receipt.gross_cents == 159_000
    assert second.fill_receipt.reserve_consumed_cents == LINE_2_RESERVE
    assert second.fee_receipt is not None
    assert second.fee_receipt.total_cents == 503
    assert second.released_reserve_cents == LINE_2_RESERVE - 159_000

    # The durable execution records mirror the in-memory result.
    assert tuple(record.client_order_id for record in result.execution_records) == (
        "client-line-1",
        "client-line-2",
    )
    assert tuple(record.verdict for record in result.execution_records) == (
        OpenExecutionVerdict.FILLED,
        OpenExecutionVerdict.FILLED,
    )
    capital.assert_conservation()


def test_fill_price_bounded_by_worst_case_and_surplus_released(
    proxy, capital, seal, permit
) -> None:
    result = _execute(proxy, capital, seal, permit)
    worst_case = {
        line.order_line_id: line.worst_case_price_cents
        for line in permit.permit_lines
    }
    for line in result.lines:
        assert line.verdict is OpenExecutionVerdict.FILLED
        assert line.fill_price_cents is not None
        assert line.fill_price_cents <= worst_case[line.order_line_id]
    snapshot = capital.capital_risk_snapshot(NOW)
    # Reserves fully consumed; every surplus cent released back to cash:
    # 1_000_000 - (104_000 + 502) - (159_000 + 503) = 735_995.
    assert snapshot.reserved_cash_cents == 0
    assert snapshot.restricted_cash_cents == 0
    assert snapshot.available_cash_cents == 735_995
    quantities = {
        position.security_id: position.settled_quantity
        for position in snapshot.positions
    }
    assert quantities == {"600000.SH": 100, "600001.SH": 200}
    capital.assert_conservation()


def test_missing_bar_line_keeps_cash_and_releases_reserve(
    proxy, capital, seal, permit
) -> None:
    bars = {"600000.SH": _touching_bar("600000.SH")}
    result = _execute(proxy, capital, seal, permit, bars=bars)
    first, second = result.lines
    assert first.verdict is OpenExecutionVerdict.FILLED
    assert second.verdict is OpenExecutionVerdict.UNKNOWN
    assert second.reason == "missing_bar"
    assert second.fill_price_cents is None
    assert second.fill_receipt is None
    assert second.fee_receipt is None
    # Cash is preserved on the unproven open, never committed.
    assert second.released_reserve_cents == LINE_2_RESERVE
    records = {record.client_order_id: record for record in result.execution_records}
    assert records["client-line-2"].verdict is OpenExecutionVerdict.UNKNOWN
    assert records["client-line-2"].fill_price_cents is None
    snapshot = capital.capital_risk_snapshot(NOW)
    assert snapshot.reserved_cash_cents == 0
    assert snapshot.restricted_cash_cents == 0
    assert snapshot.available_cash_cents == 1_000_000 - 104_000 - 502
    assert [position.security_id for position in snapshot.positions] == ["600000.SH"]
    capital.assert_conservation()


def test_bar_from_wrong_session_is_treated_as_missing(
    proxy, capital, seal, permit
) -> None:
    stale = _bar(
        "600001.SH",
        session=TARGET_SESSION - timedelta(days=1),
        open_cents=795,
        high_cents=810,
        low_cents=790,
        close_cents=805,
        limit_up_cents=880,
        limit_down_cents=720,
    )
    bars = {"600000.SH": _touching_bar("600000.SH"), "600001.SH": stale}
    result = _execute(proxy, capital, seal, permit, bars=bars)
    _, second = result.lines
    # A bar outside the target entry session is not a usable bar.
    assert second.verdict is OpenExecutionVerdict.UNKNOWN
    assert second.reason == "missing_bar"
    assert second.fill_receipt is None
    snapshot = capital.capital_risk_snapshot(NOW)
    assert [position.security_id for position in snapshot.positions] == ["600000.SH"]
    capital.assert_conservation()


def test_suspended_line_is_unknown_preserves_cash(proxy, capital, seal, permit) -> None:
    suspended = _bar(
        "600001.SH",
        open_cents=795,
        high_cents=810,
        low_cents=790,
        close_cents=805,
        limit_up_cents=880,
        limit_down_cents=720,
        suspended=True,
    )
    bars = {"600000.SH": _touching_bar("600000.SH"), "600001.SH": suspended}
    result = _execute(proxy, capital, seal, permit, bars=bars)
    first, second = result.lines
    assert first.verdict is OpenExecutionVerdict.FILLED
    assert second.verdict is OpenExecutionVerdict.UNKNOWN
    assert second.reason == "suspended_bar"
    assert second.fill_receipt is None
    assert second.released_reserve_cents == LINE_2_RESERVE
    snapshot = capital.capital_risk_snapshot(NOW)
    assert snapshot.available_cash_cents == 1_000_000 - 104_000 - 502
    capital.assert_conservation()


def test_one_price_limit_up_line_is_unknown_preserves_cash(
    proxy, capital, seal, permit
) -> None:
    # Locked at the buy limit itself: close sits "within limit", but the
    # one-price open is unprovable - the proxy must not fill off the close.
    locked = _one_price_limit_up_bar("600001.SH", limit_up_cents=800, limit_down_cents=720)
    bars = {"600000.SH": _touching_bar("600000.SH"), "600001.SH": locked}
    result = _execute(proxy, capital, seal, permit, bars=bars)
    first, second = result.lines
    assert first.verdict is OpenExecutionVerdict.FILLED
    assert second.verdict is OpenExecutionVerdict.UNKNOWN
    assert second.reason == "one_price_limit_up"
    assert second.fill_price_cents is None
    assert second.fill_receipt is None
    assert second.released_reserve_cents == LINE_2_RESERVE
    snapshot = capital.capital_risk_snapshot(NOW)
    assert [position.security_id for position in snapshot.positions] == ["600000.SH"]
    assert snapshot.available_cash_cents == 1_000_000 - 104_000 - 502
    capital.assert_conservation()


def test_late_command_aborts_every_line_to_unknown(proxy, capital, seal, permit) -> None:
    result = _execute(
        proxy, capital, seal, permit, command_at=LATE_COMMAND_AT
    )
    for line in result.lines:
        assert line.verdict is OpenExecutionVerdict.UNKNOWN
        assert line.reason == "late_command"
        assert line.fill_receipt is None
    snapshot = capital.capital_risk_snapshot(NOW)
    # Every reserve released; not a single cent committed.
    assert snapshot.available_cash_cents == 1_000_000
    assert snapshot.reserved_cash_cents == 0
    assert snapshot.restricted_cash_cents == 0
    assert snapshot.positions == ()
    capital.assert_conservation()


def test_untouched_line_is_no_fill_and_releases_reserve(
    proxy, capital, seal, permit
) -> None:
    untouched = _bar(
        "600001.SH",
        open_cents=810,
        high_cents=820,
        low_cents=805,
        close_cents=815,
        limit_up_cents=880,
        limit_down_cents=720,
    )
    bars = {"600000.SH": _touching_bar("600000.SH"), "600001.SH": untouched}
    result = _execute(proxy, capital, seal, permit, bars=bars)
    first, second = result.lines
    assert first.verdict is OpenExecutionVerdict.FILLED
    # low 805 > limit 800: provably never traded, an honest NO_FILL.
    assert second.verdict is OpenExecutionVerdict.NO_FILL
    assert second.reason == "limit_not_touched"
    assert second.fill_price_cents is None
    assert second.fill_receipt is None
    assert second.released_reserve_cents == LINE_2_RESERVE
    snapshot = capital.capital_risk_snapshot(NOW)
    assert snapshot.reserved_cash_cents == 0
    assert snapshot.restricted_cash_cents == 0
    assert snapshot.available_cash_cents == 1_000_000 - 104_000 - 502
    assert [position.security_id for position in snapshot.positions] == ["600000.SH"]
    capital.assert_conservation()


def test_execute_open_fills_permitted_quantity_not_sealed(
    proxy, repository, api, seal
) -> None:
    sealed_lines = seal.proposal.order_lines
    # Shrink the 200-share second line to one whole 100-share lot; A-share
    # permit lines must remain exact whole lots, so a shrink only lands on
    # whole-lot boundaries.
    permit_lines = (
        _permit_line(api, sealed_lines[0]),
        _permit_line(
            api,
            sealed_lines[1],
            permitted_quantity=100,
            reason_code=api.PermitReasonCode.CASH_REDUCTION,
        ),
    )
    permit = _proxy_permit(api, seal, permit_lines=permit_lines)
    _deposit(repository, 1_000_000, 1)
    # The permit-time shrink released part of the sealed reserve; the
    # kernel holds the permit's remaining 800 * 100 + 75 = 80_075.
    _seed_reserves(repository, seal, amounts={"line-2": 80_075})
    bars = {"600000.SH": _touching_bar("600000.SH"), "600001.SH": _touching_bar("600001.SH")}
    result = _execute(proxy, repository, seal, permit, bars=bars)
    _, second = result.lines
    assert second.verdict is OpenExecutionVerdict.FILLED
    assert second.fill_receipt is not None
    assert second.fill_receipt.quantity == 100
    assert second.fill_receipt.gross_cents == 79_500
    assert second.fill_receipt.reserve_consumed_cents == 80_075
    assert second.released_reserve_cents == 575
    snapshot = repository.capital_risk_snapshot(NOW)
    quantities = {
        position.security_id: position.settled_quantity
        for position in snapshot.positions
    }
    assert quantities == {"600000.SH": 100, "600001.SH": 100}
    repository.assert_conservation()


def test_zero_quantity_allow_line_releases_reserve_without_filling(
    proxy, capital, seal, api
) -> None:
    # A permit line the gateway zeroed (a mechanical cap left it no executable
    # quantity) is contract-valid: execution.py forces every sealed line to
    # appear in the permit, so an unfundable line lands as permitted_quantity=0
    # with no client order id. The proxy must never route it through the fill
    # table - a zero-quantity fill is not a valid capital fact. It resolves
    # NO_FILL, releases the line's reserve, and records the outcome, even when
    # the daily bar would otherwise resolve FILLED (limit touched).
    sealed_lines = seal.proposal.order_lines
    zero_line = _permit_line(
        api,
        sealed_lines[1],
        permitted_quantity=0,
        reason_code=api.PermitReasonCode.CASH_REDUCTION,
    )
    permit = _proxy_permit(
        api,
        seal,
        permit_lines=(_permit_line(api, sealed_lines[0]), zero_line),
    )
    # Both bars touch the limit; without the short-circuit line-2 would resolve
    # FILLED and crash the fill request (quantity must be positive).
    result = _execute(proxy, capital, seal, permit)

    first, second = result.lines
    assert first.verdict is OpenExecutionVerdict.FILLED  # line-1 still fills
    assert second.verdict is OpenExecutionVerdict.NO_FILL
    assert second.reason == "permit_quantity_zero"
    assert second.fill_receipt is None
    assert second.fee_receipt is None
    # The line's locked reserve returns to cash; nothing was spent on it.
    assert second.released_reserve_cents == LINE_2_RESERVE
    record_by_line = {
        record.order_line_id: record for record in result.execution_records
    }
    assert record_by_line["line-2"].verdict is OpenExecutionVerdict.NO_FILL
    assert record_by_line["line-2"].reason == "permit_quantity_zero"
    assert record_by_line["line-2"].fill_price_cents is None
    snapshot = capital.capital_risk_snapshot(NOW)
    assert snapshot.reserved_cash_cents == 0
    assert snapshot.restricted_cash_cents == 0
    assert snapshot.available_cash_cents == 1_000_000 - 104_000 - 502
    quantities = {
        position.security_id: position.settled_quantity
        for position in snapshot.positions
    }
    assert quantities == {"600000.SH": 100}
    capital.assert_conservation()


def test_zero_quantity_allow_line_is_idempotent_under_replay(
    proxy, capital, seal, api
) -> None:
    sealed_lines = seal.proposal.order_lines
    zero_line = _permit_line(
        api,
        sealed_lines[1],
        permitted_quantity=0,
        reason_code=api.PermitReasonCode.CASH_REDUCTION,
    )
    permit = _proxy_permit(
        api,
        seal,
        permit_lines=(_permit_line(api, sealed_lines[0]), zero_line),
    )
    _execute(proxy, capital, seal, permit)
    # Replay the whole permit: line-1 fill is idempotent, line-2 NO_FILL is
    # idempotent, and cash is unchanged by the second pass.
    replay = _execute(proxy, capital, seal, permit)
    assert replay.lines[1].verdict is OpenExecutionVerdict.NO_FILL
    assert replay.lines[1].reason == "permit_quantity_zero"
    assert replay.lines[1].released_reserve_cents == LINE_2_RESERVE
    snapshot = capital.capital_risk_snapshot(NOW)
    assert snapshot.available_cash_cents == 1_000_000 - 104_000 - 502
    capital.assert_conservation()


def test_execute_open_rejects_broker_confirmed_permit(proxy, repository, api) -> None:
    broker_seal = _seal(api)  # helper default: BROKER_CONFIRMED + account
    broker_permit = _permit(api, seal=broker_seal)
    with pytest.raises(ExecutionError) as excinfo:
        _execute(proxy, repository, broker_seal, broker_permit)
    assert excinfo.value.code == "proxy_mode_mismatch"
    # Fail-closed before any capital write.
    assert repository.stream_version() == 0


def test_execute_open_rejects_permit_line_without_reserve_binding(
    proxy, repository, api, seal, permit
) -> None:
    # A permit line whose order_line_id has no sealed reserve binding is an
    # inconsistent injected truth; the proxy rejects it zero-write rather
    # than silently filling without consuming (or orphaning) a reserve.
    _deposit(repository, 1_000_000, 1)
    stream_before = repository.stream_version()
    orphan_line = permit.permit_lines[0].model_copy(
        update={"order_line_id": "line-without-reserve"}
    )
    orphan_permit = permit.model_copy(
        update={"permit_lines": (orphan_line, permit.permit_lines[1])}
    )
    with pytest.raises(ExecutionError) as excinfo:
        _execute(proxy, repository, seal, orphan_permit)
    # The orphan line is absent from both the proposal and the reserve
    # bindings; the proposal-line guard fires first, either code is an
    # acceptable fail-closed rejection of the inconsistent truth.
    assert excinfo.value.code in {
        "proxy_proposal_line_missing",
        "proxy_reserve_binding_missing",
    }
    # Fail-closed before any execution capital write.
    assert repository.stream_version() == stream_before


def test_execute_open_rejects_unknown_execution_policy_version(
    proxy, repository, api
) -> None:
    # The trusted execution window's execution_policy_version is propagated
    # end-to-end through seal and permit, so a legitimately built permit can
    # never diverge from it. The proxy still guards the boundary directly:
    # a permit whose window carries a foreign policy version is rejected
    # before any capital write. Build the permit at the pinned version, then
    # mutate only the window the proxy inspects.
    seal = _proxy_seal(api)
    permit = _proxy_permit(api, seal)
    foreign_window = permit.execution_window.model_copy(
        update={"execution_policy_version": "t2-midday.v9"}
    )
    permit = permit.model_copy(update={"execution_window": foreign_window})
    with pytest.raises(ExecutionError) as excinfo:
        _execute(proxy, repository, seal, permit)
    assert excinfo.value.code == "proxy_execution_version_mismatch"
    assert repository.stream_version() == 0


# =============================================================================
# Replay, restart, and crash durability
# =============================================================================


def test_execute_open_replay_is_idempotent(proxy, capital, seal, permit) -> None:
    first = _execute(proxy, capital, seal, permit)
    capital_version = capital.capital_version()
    stream_version = capital.stream_version()
    replay = _execute(proxy, capital, seal, permit)
    # Same client order IDs and seal: no second fill, no version growth.
    assert capital.capital_version() == capital_version
    assert capital.stream_version() == stream_version
    assert [line.verdict for line in replay.lines] == [
        line.verdict for line in first.lines
    ]
    assert [line.fill_price_cents for line in replay.lines] == [1_040, 795]
    first_ids = [line.fill_receipt.execution_id for line in first.lines]
    replay_ids = [line.fill_receipt.execution_id for line in replay.lines]
    assert replay_ids == first_ids
    assert replay.execution_records == first.execution_records
    snapshot = capital.capital_risk_snapshot(NOW)
    quantities = {
        position.security_id: position.settled_quantity
        for position in snapshot.positions
    }
    assert quantities == {"600000.SH": 100, "600001.SH": 200}
    capital.assert_conservation()


def test_execute_open_replay_with_divergent_bars_conflicts(
    proxy, capital, seal, permit
) -> None:
    _execute(proxy, capital, seal, permit)
    divergent = dict(_touching_bars())
    divergent["600000.SH"] = _bar(
        "600000.SH",
        open_cents=1_030,
        high_cents=1_060,
        low_cents=1_020,
        close_cents=1_055,
        limit_up_cents=1_155,
        limit_down_cents=945,
    )
    with pytest.raises(ExecutionError) as excinfo:
        _execute(proxy, capital, seal, permit, bars=divergent)
    assert excinfo.value.code == "proxy_resolution_conflict"


def test_execution_records_survive_restart(tmp_path, clock, capital, seal, permit) -> None:
    database_path = str(tmp_path / "proxy-restart.sqlite3")
    first_proxy = DailyBarProxy(database_path=database_path, clock=clock)
    first = _execute(first_proxy, capital, seal, permit)
    capital_version = capital.capital_version()

    restarted = DailyBarProxy(database_path=database_path, clock=clock)
    records = restarted.execution_records(permit.permit_id)
    assert records == first.execution_records
    replay = _execute(restarted, capital, seal, permit)
    assert [line.verdict for line in replay.lines] == [
        OpenExecutionVerdict.FILLED,
        OpenExecutionVerdict.FILLED,
    ]
    first_ids = [line.fill_receipt.execution_id for line in first.lines]
    replay_ids = [line.fill_receipt.execution_id for line in replay.lines]
    assert replay_ids == first_ids
    # The restart replay stays converged: no duplicate economic effect.
    assert capital.capital_version() == capital_version
    capital.assert_conservation()


def test_zero_quantity_line_survives_restart(
    tmp_path, clock, capital, seal, api
) -> None:
    sealed_lines = seal.proposal.order_lines
    zero_line = _permit_line(
        api,
        sealed_lines[1],
        permitted_quantity=0,
        reason_code=api.PermitReasonCode.CASH_REDUCTION,
    )
    permit = _proxy_permit(
        api,
        seal,
        permit_lines=(_permit_line(api, sealed_lines[0]), zero_line),
    )
    database_path = str(tmp_path / "proxy-zeroqty-restart.sqlite3")
    first_proxy = DailyBarProxy(database_path=database_path, clock=clock)
    first = _execute(first_proxy, capital, seal, permit)

    restarted = DailyBarProxy(database_path=database_path, clock=clock)
    records = restarted.execution_records(permit.permit_id)
    # The durable records round-trip exactly through a restart.
    assert records == first.execution_records
    # The zero-quantity line persists with no client order id (not a "None"
    # string) and a NO_FILL verdict, never a stale fill.
    zero_record = next(
        record for record in records if record.order_line_id == "line-2"
    )
    assert zero_record.client_order_id is None
    assert zero_record.verdict is OpenExecutionVerdict.NO_FILL
    assert zero_record.reason == "permit_quantity_zero"
    assert zero_record.fill_price_cents is None
    capital.assert_conservation()


_PROXY_CRASH_PHASES = (
    "proxy.after_fill",
    "proxy.after_fee",
    "proxy.after_release",
    "proxy.after_record",
)


def _crashing_proxy(tmp_path, clock: _Clock, phase: str) -> DailyBarProxy:
    def hook(name: str) -> None:
        if name == phase:
            raise RuntimeError(f"simulated crash at {name}")

    return DailyBarProxy(
        database_path=str(tmp_path / "proxy-crash.sqlite3"),
        clock=clock,
        _fault_hook=hook,
    )


@pytest.mark.parametrize("phase", _PROXY_CRASH_PHASES)
def test_crash_mid_execution_replays_to_complete_state(
    tmp_path, clock, capital, seal, permit, phase
) -> None:
    bars = {
        "600000.SH": _touching_bar("600000.SH"),
        # NO_FILL line exercises the reserve-release write on recovery.
        "600001.SH": _bar(
            "600001.SH",
            open_cents=810,
            high_cents=820,
            low_cents=805,
            close_cents=815,
            limit_up_cents=880,
            limit_down_cents=720,
        ),
    }

    def drive(candidate: DailyBarProxy) -> ProxyExecutionResult:
        return _execute(candidate, capital, seal, permit, bars=bars)

    crashing = _crashing_proxy(tmp_path, clock, phase)
    crashed = False
    try:
        drive(crashing)
    except ExecutionError:
        raise
    except RuntimeError as exc:
        assert "simulated crash" in str(exc)
        crashed = True
    assert crashed

    recovered = DailyBarProxy(
        database_path=str(tmp_path / "proxy-crash.sqlite3"), clock=clock
    )
    result = drive(recovered)
    first, second = result.lines
    assert first.verdict is OpenExecutionVerdict.FILLED
    assert first.fill_price_cents == 1_040
    assert second.verdict is OpenExecutionVerdict.NO_FILL

    # Whatever the crash interrupted, a further replay stays converged.
    replay = drive(recovered)
    assert [line.verdict for line in replay.lines] == [
        OpenExecutionVerdict.FILLED,
        OpenExecutionVerdict.NO_FILL,
    ]

    snapshot = capital.capital_risk_snapshot(NOW)
    quantities = {
        position.security_id: position.settled_quantity
        for position in snapshot.positions
    }
    # No partial or duplicated economic effect across the crash.
    assert quantities == {"600000.SH": 100}
    assert snapshot.available_cash_cents == 1_000_000 - 104_000 - 502
    assert snapshot.reserved_cash_cents == 0
    assert snapshot.restricted_cash_cents == 0
    records = recovered.execution_records(permit.permit_id)
    assert sorted(record.client_order_id for record in records) == [
        "client-line-1",
        "client-line-2",
    ]
    capital.assert_conservation()
