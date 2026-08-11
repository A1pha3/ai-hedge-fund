"""Task 8: the shared, authority-neutral proxy settlement core.

``settle_proxy_open`` is the stateless economic heart that both the
authorised ``DailyBarProxy`` adapter (entry from a sealed permit) and the
shadow adapter (entry/exit from a committed ``ShadowDecision``) drive. It
takes a normalized intent, one target-session daily bar, the live capital
repository, an explicit cost scenario, and the command timing; it resolves
the open through the existing decision table, applies integer adverse
slippage bounded by the limit, and books the fill / fee / reserve release
into capital truth. It owns no durable execution-record storage and no
clock: the authorised adapter keeps its record table, and every timestamp
comes from the injected intent.

RED today: ``settle_proxy_open``, ``NormalizedProxyOpenIntent``,
``ProxyCostScenario``, and ``ProxyOpenSettlement`` do not exist yet.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.screening.offensive.v3.capital.fees import FeePolicy
from src.screening.offensive.v3.capital.fills import FillAttribution
from src.screening.offensive.v3.capital.provenance import CapitalSourceBinding
from src.screening.offensive.v3.capital.repository import (
    AccountBinding,
    CapitalCommand,
    CapitalCommandPayload,
    CapitalRepository,
)
from src.screening.offensive.v3.capital.reserves import ReserveEntryRequest
from src.screening.offensive.v3.contracts import (
    ArtifactKind,
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
    OpenExecutionVerdict,
)
from src.screening.offensive.v3.execution.proxy_core import (  # RED target
    NormalizedProxyOpenIntent,
    ProxyCostScenario,
    ProxyOpenSettlement,
    settle_proxy_open,
)
from tests.offensive.v3.contracts.checkpoint2_helpers import (
    SEND_DEADLINE,
    TARGET_SESSION,
)

UTC = timezone.utc
# The settlement records at the T+1 opening-auction moment; the command was
# issued inside the T0 evening execution window (before the send deadline).
RECORDED_AT = datetime(2026, 7, 30, 1, 25, tzinfo=UTC)
COMMAND_AT = datetime(2026, 7, 29, 8, 2, 30, tzinfo=UTC)
LATE_COMMAND_AT = datetime(2026, 7, 30, 1, 24, tzinfo=UTC)  # past SEND_DEADLINE

# 30bps single-side commission, 5 yuan per-order minimum, 10bps sell-side
# stamp tax, 2bps transfer fee (the proxy v1 policy rates).
FEE_POLICY = FeePolicy(
    fee_policy_version="cn-a-share-30bps-tax.v2",
    commission_rate_ppm=3_000,
    min_commission_cents=500,
    stamp_tax_rate_ppm=1_000,
    transfer_fee_rate_ppm=20,
)

PROXY_BINDING = AccountBinding(
    portfolio_id="portfolio-shadow",
    mode=ExecutionMode.DAILY_BAR_PROXY,
    broker_account_id=None,
    base_currency="CNY",
    environment_fingerprint=None,
)

SHADOW_BINDING = CapitalSourceBinding(
    mode=ExecutionMode.DAILY_BAR_PROXY,
    artifact_kind=ArtifactKind.SHADOW_DECISION,
    artifact_id="shadow-decision-1",
    artifact_hash="a" * 64,
)


# -- capital seeding ---------------------------------------------------------


def _seed_moment(step: int) -> datetime:
    return datetime(2026, 7, 29, 7, 0, tzinfo=UTC) + _minutes(step)


def _minutes(step: int):
    from datetime import timedelta

    return timedelta(minutes=step)


def _deposit(repository: CapitalRepository, cents: int, sequence: int) -> None:
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
            as_of=_seed_moment(sequence) + _minutes(1),
            payload=CapitalCommandPayload(
                event_kind=EconomicEventKind.DIVIDEND_CASH_SETTLED,
                effective_at=_seed_moment(sequence) + _minutes(1),
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


def _seed_reserve(
    repository: CapitalRepository,
    *,
    source_id: str,
    gross_cents: int,
    binding: CapitalSourceBinding = SHADOW_BINDING,
) -> None:
    repository.reserve_entry(
        ReserveEntryRequest(
            source_id=source_id,
            research_program_id="btst-program-a",
            economic_lineage_id="btst-lineage-a",
            stage_id="auto-shadow-stage",
            reserved_entry_gross_cents=gross_cents,
            expected_stream_version=repository.stream_version(),
            as_of=_seed_moment(3),
            source_binding=binding,
        )
    )


@pytest.fixture()
def repository(tmp_path) -> CapitalRepository:
    return CapitalRepository.initialize(tmp_path / "capital.sqlite3")


@pytest.fixture()
def funded(repository: CapitalRepository) -> CapitalRepository:
    _deposit(repository, 1_000_000, 1)
    return repository


# -- intent / scenario / bar builders ---------------------------------------


def _attribution() -> FillAttribution:
    return FillAttribution(
        producer_namespace="auto.shadow",
        research_program_id="btst-program-a",
        economic_lineage_id="btst-lineage-a",
        stage_id="auto-shadow-stage",
    )


def _entry_intent(
    *,
    quantity: int = 100,
    limit_price_cents: int = 1_050,
    reserve_cents: int | None = None,
    execution_id: str = "proxy:client-line-1",
    order_id: str = "client-line-1",
    reserve_source_id: str | None = "entry-reserve-line-1",
) -> NormalizedProxyOpenIntent:
    # Default reserve covers worst-case price * qty + fee reserve.
    if reserve_cents is None:
        reserve_cents = limit_price_cents * quantity + 50
    return NormalizedProxyOpenIntent(
        side=ExecutionSide.ENTRY,
        security_id="600000.SH",
        limit_price_cents=limit_price_cents,
        quantity_units=quantity,
        lot_size_units=100,
        execution_id=execution_id,
        order_id=order_id,
        reserve_source_id=reserve_source_id,
        # The LIVE remaining reserve the kernel holds for this line; reported
        # on a no-fill/unknown release and consumed in full on a fill.
        reserve_remaining_cents=reserve_cents if reserve_source_id else 0,
        position_lineage_id="btst-lineage-a",
        economic_lot_id="lot:line-1",
        attribution=_attribution(),
        source_authority="daily-bar-proxy.v2",
        source_binding=SHADOW_BINDING,
        recorded_at=RECORDED_AT,
    )


def _cost_scenario(slippage_bps: int = 30) -> ProxyCostScenario:
    return ProxyCostScenario(
        scenario_id="current-cost" if slippage_bps == 30 else "double-slippage",
        entry_slippage_bps=slippage_bps,
        exit_slippage_bps=slippage_bps,
        fee_policy=FEE_POLICY,
    )


def _touching_buy_bar() -> DailyBar:
    # open 1040 < buy limit 1050 -> base fill at 1040.
    return DailyBar(
        security_id="600000.SH",
        session=TARGET_SESSION,
        open_cents=1_040,
        high_cents=1_060,
        low_cents=1_030,
        close_cents=1_055,
        limit_up_cents=1_155,
        limit_down_cents=945,
    )


def _touching_sell_bar() -> DailyBar:
    # open 810 > sell limit 800 -> base fill at 810.
    return DailyBar(
        security_id="600000.SH",
        session=TARGET_SESSION,
        open_cents=810,
        high_cents=815,
        low_cents=795,
        close_cents=808,
        limit_up_cents=880,
        limit_down_cents=720,
    )


def _settle(
    intent,
    repository: CapitalRepository,
    *,
    bar: DailyBar | None,
    scenario,
    command_at: datetime = COMMAND_AT,
):
    return settle_proxy_open(
        intent,
        bar=bar,
        repository=repository,
        scenario=scenario,
        command_at=command_at,
        send_deadline=SEND_DEADLINE,
    )


# =============================================================================
# Entry fills: slippage, limit bound, fees, reserve
# =============================================================================


def test_entry_fill_applies_adverse_slippage_within_the_limit(funded) -> None:
    intent = _entry_intent(quantity=100, limit_price_cents=1_050)
    _seed_reserve(funded, source_id="entry-reserve-line-1", gross_cents=105_050)
    settlement = _settle(intent, funded, bar=_touching_buy_bar(), scenario=_cost_scenario(30))
    assert settlement.verdict is OpenExecutionVerdict.FILLED
    # base 1040 + round(1040*30/10000)=3 -> 1043, below the 1050 limit.
    assert settlement.fill_price_cents == 1_043
    assert settlement.fill_receipt is not None
    assert settlement.fill_receipt.quantity == 100
    assert settlement.fill_receipt.gross_cents == 104_300
    assert settlement.fill_receipt.side is ExecutionSide.ENTRY
    funded.assert_conservation()


def test_entry_fill_price_cannot_exceed_the_limit(funded) -> None:
    intent = _entry_intent(quantity=100, limit_price_cents=1_050)
    _seed_reserve(funded, source_id="entry-reserve-line-1", gross_cents=105_050)
    # 600bps adverse: 1040 + round(1040*600/10000)=62 -> 1102, capped at 1050.
    settlement = _settle(intent, funded, bar=_touching_buy_bar(), scenario=_cost_scenario(600))
    assert settlement.verdict is OpenExecutionVerdict.FILLED
    assert settlement.fill_price_cents == 1_050
    funded.assert_conservation()


def test_double_slippage_changes_execution_price_not_final_return(
    tmp_path, repository: CapitalRepository
) -> None:
    # Two identical ledgers; the only difference is the slippage scenario.
    # 30bps fills at 1043, 60bps fills at 1046 (both below the 1050 limit).
    # The point: stress moves the *execution price*, so it flows through
    # capital — it is never a post-hoc constant subtracted from final return.
    current_repo = repository
    _deposit(current_repo, 1_000_000, 1)
    stressed_repo = CapitalRepository.initialize(tmp_path / "capital-stressed.sqlite3")
    _deposit(stressed_repo, 1_000_000, 1)

    for repo in (current_repo, stressed_repo):
        _seed_reserve(repo, source_id="entry-reserve-line-1", gross_cents=105_050)

    intent = _entry_intent(quantity=100, limit_price_cents=1_050)
    current = _settle(intent, current_repo, bar=_touching_buy_bar(), scenario=_cost_scenario(30))
    stressed = _settle(intent, stressed_repo, bar=_touching_buy_bar(), scenario=_cost_scenario(60))
    assert stressed.fill_price_cents >= current.fill_price_cents
    current_repo.assert_conservation()
    stressed_repo.assert_conservation()


def test_entry_fill_charges_fee_under_the_scenario_policy(funded) -> None:
    intent = _entry_intent(quantity=100, limit_price_cents=1_050)
    _seed_reserve(funded, source_id="entry-reserve-line-1", gross_cents=105_050)
    settlement = _settle(intent, funded, bar=_touching_buy_bar(), scenario=_cost_scenario(30))
    fee = settlement.fee_receipt
    assert fee is not None
    assert fee.fee_policy_version == FEE_POLICY.fee_policy_version
    # Entry has no sell-side stamp tax.
    assert fee.stamp_tax_cents == 0
    assert fee.commission_cents >= 0
    assert fee.transfer_fee_cents >= 0
    funded.assert_conservation()


def test_entry_fill_consumes_reserve_and_releases_surplus(funded) -> None:
    intent = _entry_intent(quantity=100, limit_price_cents=1_050)
    _seed_reserve(funded, source_id="entry-reserve-line-1", gross_cents=105_050)
    settlement = _settle(intent, funded, bar=_touching_buy_bar(), scenario=_cost_scenario(30))
    assert settlement.fill_receipt.reserve_consumed_cents == 105_050
    # surplus = consumed reserve - real gross
    assert settlement.released_reserve_cents == 105_050 - 104_300
    snapshot = funded.capital_risk_snapshot(RECORDED_AT)
    assert snapshot.reserved_cash_cents == 0
    assert snapshot.restricted_cash_cents == 0
    funded.assert_conservation()


def test_entry_fill_carries_the_source_binding(funded) -> None:
    intent = _entry_intent(quantity=100, limit_price_cents=1_050)
    _seed_reserve(funded, source_id="entry-reserve-line-1", gross_cents=105_050)
    settlement = _settle(intent, funded, bar=_touching_buy_bar(), scenario=_cost_scenario(30))
    assert settlement.fill_receipt is not None
    # The fill event payload must carry the decision-derived source binding.
    import sqlalchemy as sa

    with funded.engine.connect() as conn:  # noqa: SLF001
        row = conn.execute(
            sa.text(
                "SELECT payload_json FROM economic_events"
                " WHERE economic_event_id = :event_id"
            ),
            {"event_id": settlement.fill_receipt.event_id},
        ).one()
    stored = CapitalCommandPayload.model_validate_json(row[0])
    assert stored.source_binding == SHADOW_BINDING
    funded.assert_conservation()


# =============================================================================
# No-fill / unknown / zero quantity: reserve release, cash preserved
# =============================================================================


def test_missing_bar_is_unknown_and_releases_reserve(funded) -> None:
    intent = _entry_intent()
    _seed_reserve(funded, source_id="entry-reserve-line-1", gross_cents=105_050)
    settlement = _settle(intent, funded, bar=None, scenario=_cost_scenario(30))
    assert settlement.verdict is OpenExecutionVerdict.UNKNOWN
    assert settlement.reason == "missing_bar"
    assert settlement.fill_receipt is None
    assert settlement.fee_receipt is None
    assert settlement.released_reserve_cents == 105_050
    snapshot = funded.capital_risk_snapshot(RECORDED_AT)
    assert snapshot.reserved_cash_cents == 0
    assert snapshot.available_cash_cents == 1_000_000
    funded.assert_conservation()


def test_suspended_bar_is_unknown(funded) -> None:
    intent = _entry_intent()
    _seed_reserve(funded, source_id="entry-reserve-line-1", gross_cents=105_050)
    bar = DailyBar(
        security_id="600000.SH",
        session=TARGET_SESSION,
        open_cents=1_040,
        high_cents=1_060,
        low_cents=1_030,
        close_cents=1_055,
        limit_up_cents=1_155,
        limit_down_cents=945,
        suspended=True,
    )
    settlement = _settle(intent, funded, bar=bar, scenario=_cost_scenario(30))
    assert settlement.verdict is OpenExecutionVerdict.UNKNOWN
    assert settlement.reason == "suspended_bar"
    funded.assert_conservation()


def test_late_command_is_unknown(funded) -> None:
    intent = _entry_intent()
    _seed_reserve(funded, source_id="entry-reserve-line-1", gross_cents=105_050)
    settlement = _settle(
        intent,
        funded,
        bar=_touching_buy_bar(),
        scenario=_cost_scenario(30),
        command_at=LATE_COMMAND_AT,
    )
    assert settlement.verdict is OpenExecutionVerdict.UNKNOWN
    assert settlement.reason == "late_command"
    funded.assert_conservation()


def test_one_price_limit_up_buy_is_unknown(funded) -> None:
    intent = _entry_intent(limit_price_cents=1_050)
    _seed_reserve(funded, source_id="entry-reserve-line-1", gross_cents=105_050)
    bar = DailyBar(
        security_id="600000.SH",
        session=TARGET_SESSION,
        open_cents=1_050,
        high_cents=1_050,
        low_cents=1_050,
        close_cents=1_050,
        limit_up_cents=1_050,
        limit_down_cents=945,
    )
    settlement = _settle(intent, funded, bar=bar, scenario=_cost_scenario(30))
    assert settlement.verdict is OpenExecutionVerdict.UNKNOWN
    assert settlement.reason == "one_price_limit_up"
    funded.assert_conservation()


def test_untouched_limit_is_no_fill(funded) -> None:
    intent = _entry_intent(limit_price_cents=1_050)
    _seed_reserve(funded, source_id="entry-reserve-line-1", gross_cents=105_050)
    bar = DailyBar(
        security_id="600000.SH",
        session=TARGET_SESSION,
        open_cents=1_060,
        high_cents=1_070,
        low_cents=1_055,
        close_cents=1_065,
        limit_up_cents=1_155,
        limit_down_cents=945,
    )
    settlement = _settle(intent, funded, bar=bar, scenario=_cost_scenario(30))
    assert settlement.verdict is OpenExecutionVerdict.NO_FILL
    assert settlement.reason == "limit_not_touched"
    assert settlement.released_reserve_cents == 105_050
    funded.assert_conservation()


def test_zero_quantity_intent_is_no_fill_and_releases_nothing(funded) -> None:
    # A mechanically-shrunk-to-zero line has no live reserve (the gateway /
    # shadow reserve step already released it). The core never routes it
    # through the fill table.
    intent = _entry_intent(
        quantity=0,
        reserve_source_id=None,
        reserve_cents=0,
    )
    settlement = _settle(intent, funded, bar=_touching_buy_bar(), scenario=_cost_scenario(30))
    assert settlement.verdict is OpenExecutionVerdict.NO_FILL
    assert settlement.reason == "permit_quantity_zero"
    assert settlement.fill_receipt is None
    assert settlement.released_reserve_cents == 0
    funded.assert_conservation()


# =============================================================================
# Exit: sell-side slippage, stamp tax, limit floor
# =============================================================================


def test_exit_fill_applies_adverse_slippage_above_the_limit(funded) -> None:
    # Seed an entry position first so the exit has a lot to sell against.
    entry_intent = _entry_intent(
        quantity=100,
        limit_price_cents=1_050,
        execution_id="proxy:entry-1",
        order_id="entry-1",
        reserve_source_id="entry-reserve-1",
    )
    _seed_reserve(funded, source_id="entry-reserve-1", gross_cents=105_050)
    _settle(entry_intent, funded, bar=_touching_buy_bar(), scenario=_cost_scenario(30))

    exit_intent = NormalizedProxyOpenIntent(
        side=ExecutionSide.EXIT,
        security_id="600000.SH",
        limit_price_cents=800,
        quantity_units=100,
        lot_size_units=100,
        execution_id="proxy:exit-1",
        order_id="exit-1",
        reserve_source_id=None,
        reserve_remaining_cents=0,
        position_lineage_id="btst-lineage-a",
        economic_lot_id="lot:line-1",
        attribution=_attribution(),
        source_authority="daily-bar-proxy.v2",
        source_binding=SHADOW_BINDING,
        recorded_at=RECORDED_AT,
    )
    # open 810 > sell limit 800 -> base 810; 30bps adverse -> 810 - round(810*30/10000)=2 -> 808.
    settlement = _settle(
        exit_intent, funded, bar=_touching_sell_bar(), scenario=_cost_scenario(30)
    )
    assert settlement.verdict is OpenExecutionVerdict.FILLED
    assert settlement.fill_price_cents == 808
    fee = settlement.fee_receipt
    assert fee is not None
    # EXIT is a sell -> stamp tax applies.
    assert fee.stamp_tax_cents > 0
    funded.assert_conservation()


def test_exit_fill_price_cannot_fall_below_the_limit(funded) -> None:
    entry_intent = _entry_intent(
        quantity=100,
        limit_price_cents=1_050,
        execution_id="proxy:entry-1",
        order_id="entry-1",
        reserve_source_id="entry-reserve-1",
    )
    _seed_reserve(funded, source_id="entry-reserve-1", gross_cents=105_050)
    _settle(entry_intent, funded, bar=_touching_buy_bar(), scenario=_cost_scenario(30))

    exit_intent = NormalizedProxyOpenIntent(
        side=ExecutionSide.EXIT,
        security_id="600000.SH",
        limit_price_cents=800,
        quantity_units=100,
        lot_size_units=100,
        execution_id="proxy:exit-1",
        order_id="exit-1",
        reserve_source_id=None,
        reserve_remaining_cents=0,
        position_lineage_id="btst-lineage-a",
        economic_lot_id="lot:line-1",
        attribution=_attribution(),
        source_authority="daily-bar-proxy.v2",
        source_binding=SHADOW_BINDING,
        recorded_at=RECORDED_AT,
    )
    # 600bps adverse on base 810: 810 - round(810*600/10000)=49 -> 761, floored at 800.
    settlement = _settle(
        exit_intent, funded, bar=_touching_sell_bar(), scenario=_cost_scenario(600)
    )
    assert settlement.verdict is OpenExecutionVerdict.FILLED
    assert settlement.fill_price_cents == 800
    funded.assert_conservation()


# =============================================================================
# Idempotency: exact replay converges
# =============================================================================


def test_exact_replay_is_idempotent(funded) -> None:
    intent = _entry_intent(quantity=100, limit_price_cents=1_050)
    _seed_reserve(funded, source_id="entry-reserve-line-1", gross_cents=105_050)
    first = _settle(intent, funded, bar=_touching_buy_bar(), scenario=_cost_scenario(30))
    capital_version = funded.capital_version()
    stream_version = funded.stream_version()
    replay = _settle(intent, funded, bar=_touching_buy_bar(), scenario=_cost_scenario(30))
    assert replay.verdict is first.verdict
    assert replay.fill_price_cents == first.fill_price_cents
    assert funded.capital_version() == capital_version
    assert funded.stream_version() == stream_version
    funded.assert_conservation()
