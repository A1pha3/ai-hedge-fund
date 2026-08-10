"""Task 8 Step 6: adapter-vs-core differential and property tests.

The authorised ``DailyBarProxy`` adapter and the shared
``settle_proxy_open`` core must produce identical economics for
equivalent normalized inputs: same cash, restricted cash, quantities,
cost basis, fees, and NAV. ``DailyBarProxy`` owns permit validation and
durable execution records; the core owns fill/fee/release economics.
Feeding the same scenario, bar, and genesis through both into two
equal-genesis ledgers, the only allowed divergence is provenance
(execution-record table rows) and provenance-derived IDs, so the
normalized capital snapshots must match exactly.

Property rules also hold regardless of candidate order, lot quantity,
price, bar shape, and crash replay: a crash between capital writes and
the durable record converges to the same state as the direct core.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.screening.offensive.v3.capital.fees import FeePolicy
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.execution.lifecycle import DailyBar
from src.screening.offensive.v3.execution.proxy import (
    DailyBarProxy,
    ProxyExecutionContext,
)
from src.screening.offensive.v3.execution.proxy_core import (
    NormalizedProxyOpenIntent,
    ProxyCostScenario,
    settle_proxy_open,
)
from tests.offensive.v3.contracts.checkpoint2_helpers import (
    SEND_DEADLINE,
    TARGET_SESSION,
    _api,
)
from tests.offensive.v3.execution.test_proxy import (
    _deposit,
    _proxy_permit,
    _proxy_seal,
    _seed_reserves,
    _touching_bars,
)
from tests.offensive.v3.execution.test_proxy_economic_core import (
    COMMAND_AT,
    RECORDED_AT,
    _deposit as _core_deposit,
    _entry_intent as _core_entry_intent,
    _seed_reserve,
)

UTC = timezone.utc

POLICY_V1 = FeePolicy(
    fee_policy_version="cn-a-share-30bps-tax.v2",
    commission_rate_ppm=3_000,
    min_commission_cents=500,
    stamp_tax_rate_ppm=1_000,
    transfer_fee_rate_ppm=20,
)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self._moment = start

    def __call__(self) -> datetime:
        return self._moment


def _cost_scenario(slippage_bps: int = 30) -> ProxyCostScenario:
    return ProxyCostScenario(
        scenario_id="current-cost" if slippage_bps == 30 else "double-slippage",
        entry_slippage_bps=slippage_bps,
        exit_slippage_bps=slippage_bps,
        fee_policy=POLICY_V1,
    )


def _proxy_repo(tmp_path, name: str) -> tuple[DailyBarProxy, CapitalRepository]:
    api = _api()
    seal = _proxy_seal(api)
    permit = _proxy_permit(api, seal=seal)
    repository = CapitalRepository.initialize(tmp_path / f"{name}-capital.sqlite3")
    _deposit(repository, 1_000_000, 1)
    _seed_reserves(repository, seal)
    proxy = DailyBarProxy(
        database_path=str(tmp_path / f"{name}-proxy.sqlite3"),
        clock=_Clock(RECORDED_AT),
    )
    return proxy, repository, seal, permit


def _proxy_context(repository: CapitalRepository) -> ProxyExecutionContext:
    return ProxyExecutionContext(
        repository=repository,
        command_at=COMMAND_AT,
        source_authority="daily-bar-proxy.v2",
    )


def _executed_lines(proxy, repository, seal, permit, bars, scenario):
    result = proxy.execute_open(
        seal=seal,
        permit=permit,
        bars=bars,
        scenario=scenario,
        context=_proxy_context(repository),
    )
    return result.lines


def _core_intent(*, quantity: int = 100, limit_price_cents: int = 1_050) -> NormalizedProxyOpenIntent:
    return _core_entry_intent(
        quantity=quantity,
        limit_price_cents=limit_price_cents,
    )


def _funded_core_repo(tmp_path, name: str) -> CapitalRepository:
    repository = CapitalRepository.initialize(tmp_path / f"{name}-capital.sqlite3")
    _core_deposit(repository, 1_000_000, 1)
    return repository


def _settle_core(
    repository: CapitalRepository, intent, *, bar: DailyBar | None, scenario
):
    return settle_proxy_open(
        intent,
        bar=bar,
        repository=repository,
        scenario=scenario,
        command_at=COMMAND_AT,
        send_deadline=SEND_DEADLINE,
    )


def _normalized_snapshot(repository: CapitalRepository) -> dict:
    snapshot = repository.capital_risk_snapshot(RECORDED_AT)
    return {
        "available_cash_cents": snapshot.available_cash_cents,
        "restricted_cash_cents": snapshot.restricted_cash_cents,
        "unsettled_cash_cents": snapshot.unsettled_cash_cents,
        "reserved_cash_cents": snapshot.reserved_cash_cents,
        "positions": {
            position.security_id: (
                position.settled_quantity,
                position.marked_gross_cents,
            )
            for position in snapshot.positions
        },
        "as_observed_nav_cents": snapshot.as_observed_nav_cents,
        "total_gross_exposure_cents": snapshot.total_gross_exposure_cents,
    }


# =============================================================================
# Differential: authorised adapter vs direct core, equal genesis
# =============================================================================


def test_adapter_and_core_match_for_current_cost(tmp_path) -> None:
    api = _api()
    seal = _proxy_seal(api)
    permit = _proxy_permit(api, seal=seal)

    proxy, proxy_repo, seal, permit = _proxy_repo(tmp_path, "proxy-arm")
    core_repo = _funded_core_repo(tmp_path, "core-arm")
    scenario = _cost_scenario(30)
    bars = _touching_bars()

    proxy_lines = _executed_lines(proxy, proxy_repo, seal, permit, bars, scenario)
    # The permit's two lines match the two sealed proposal lines; settle the
    # same economic intent directly through the core on the twin ledger.
    sealed_lines = seal.proposal.order_lines
    for line in sealed_lines:
        _seed_reserve(
            core_repo,
            source_id=f"reserve-{line.order_line_id}",
            gross_cents=line.worst_case_cash_reserve_cents,
        )
    core_fills = 0
    for permit_line in permit.permit_lines:
        sealed_line = next(
            line
            for line in sealed_lines
            if line.order_line_id == permit_line.order_line_id
        )
        if permit_line.permitted_quantity_units == 0:
            continue
        intent = _core_intent(
            quantity=int(permit_line.permitted_quantity_units),
            limit_price_cents=int(permit_line.limit_price_cents),
        )
        intent = replace(
            intent,
            security_id=sealed_line.security_id,
            execution_id=f"proxy:{permit_line.client_order_id}",
            order_id=permit_line.client_order_id,
            reserve_source_id=f"reserve-{permit_line.order_line_id}",
            reserve_remaining_cents=permit_line.remaining_reserve_cents,
            economic_lot_id=f"lot:{sealed_line.order_line_id}",
            position_lineage_id=sealed_line.economic_lineage_id,
            source_authority="daily-bar-proxy.v2",
            recorded_at=RECORDED_AT,
        )
        _seed_reserve(
            core_repo,
            source_id=f"reserve-{permit_line.order_line_id}",
            gross_cents=permit_line.remaining_reserve_cents,
        )
        result = _settle_core(
            core_repo,
            intent,
            bar=bars[sealed_line.security_id],
            scenario=scenario,
        )
        assert result.verdict is not None
        if result.verdict.value == "FILLED":
            core_fills += 1

    # At least one line actually filled through both paths.
    assert core_fills > 0
    assert any(line.verdict.value == "FILLED" for line in proxy_lines)

    assert _normalized_snapshot(proxy_repo) == _normalized_snapshot(core_repo)
    proxy_repo.assert_conservation()
    core_repo.assert_conservation()


def test_adapter_and_core_match_for_double_slippage(tmp_path) -> None:
    api = _api()
    seal = _proxy_seal(api)
    permit = _proxy_permit(api, seal=seal)

    proxy, proxy_repo, seal, permit = _proxy_repo(tmp_path, "proxy-arm")
    core_repo = _funded_core_repo(tmp_path, "core-arm")
    scenario = _cost_scenario(60)
    bars = _touching_bars()

    proxy_lines = _executed_lines(proxy, proxy_repo, seal, permit, bars, scenario)

    sealed_lines = seal.proposal.order_lines
    for permit_line in permit.permit_lines:
        sealed_line = next(
            line
            for line in sealed_lines
            if line.order_line_id == permit_line.order_line_id
        )
        if permit_line.permitted_quantity_units == 0:
            continue
        intent = _core_intent(
            quantity=int(permit_line.permitted_quantity_units),
            limit_price_cents=int(permit_line.limit_price_cents),
        )
        intent = replace(
            intent,
            security_id=sealed_line.security_id,
            execution_id=f"proxy:{permit_line.client_order_id}",
            order_id=permit_line.client_order_id,
            reserve_source_id=f"reserve-{permit_line.order_line_id}",
            reserve_remaining_cents=permit_line.remaining_reserve_cents,
            economic_lot_id=f"lot:{sealed_line.order_line_id}",
            position_lineage_id=sealed_line.economic_lineage_id,
            source_authority="daily-bar-proxy.v2",
            recorded_at=RECORDED_AT,
        )
        _seed_reserve(
            core_repo,
            source_id=f"reserve-{permit_line.order_line_id}",
            gross_cents=permit_line.remaining_reserve_cents,
        )
        result = _settle_core(
            core_repo,
            intent,
            bar=bars[sealed_line.security_id],
            scenario=scenario,
        )
        assert result.verdict is not None

    assert any(line.verdict.value == "FILLED" for line in proxy_lines)
    assert _normalized_snapshot(proxy_repo) == _normalized_snapshot(core_repo)
    proxy_repo.assert_conservation()
    core_repo.assert_conservation()


# =============================================================================
# Property: crash replay converges to the direct-core state
# =============================================================================


@pytest.mark.parametrize("phase", ["core.after_fill", "core.after_fee", "core.after_release"])
def test_crash_between_core_writes_converges_to_direct_core(
    tmp_path, phase: str
) -> None:
    api = _api()
    seal = _proxy_seal(api)
    permit = _proxy_permit(api, seal=seal)
    bars = _touching_bars()
    # Line-2 (buy limit 800) faces a bar whose open 795 touches it, so both
    # lines fill; give line-2 an untouched bar instead so the crash path
    # exercises the reserve release hook.
    bars["600001.SH"] = DailyBar(
        security_id="600001.SH",
        session=TARGET_SESSION,
        open_cents=850,
        high_cents=860,
        low_cents=845,
        close_cents=855,
        limit_up_cents=880,
        limit_down_cents=720,
    )
    scenario = _cost_scenario(30)

    core_repo = _funded_core_repo(tmp_path, "core-arm")
    sealed_lines = seal.proposal.order_lines
    for permit_line in permit.permit_lines:
        sealed_line = next(
            line
            for line in sealed_lines
            if line.order_line_id == permit_line.order_line_id
        )
        if permit_line.permitted_quantity_units == 0:
            continue
        intent = _core_intent(
            quantity=int(permit_line.permitted_quantity_units),
            limit_price_cents=int(permit_line.limit_price_cents),
        )
        intent = replace(
            intent,
            security_id=sealed_line.security_id,
            execution_id=f"proxy:{permit_line.client_order_id}",
            order_id=permit_line.client_order_id,
            reserve_source_id=f"reserve-{permit_line.order_line_id}",
            reserve_remaining_cents=permit_line.remaining_reserve_cents,
            economic_lot_id=f"lot:{sealed_line.order_line_id}",
            position_lineage_id=sealed_line.economic_lineage_id,
            source_authority="daily-bar-proxy.v2",
            recorded_at=RECORDED_AT,
        )
        _seed_reserve(
            core_repo,
            source_id=f"reserve-{permit_line.order_line_id}",
            gross_cents=permit_line.remaining_reserve_cents,
        )
        _settle_core(core_repo, intent, bar=bars[sealed_line.security_id], scenario=scenario)

    def hook(name: str) -> None:
        if name == phase:
            raise RuntimeError(f"simulated crash at {name}")

    proxy_repo = CapitalRepository.initialize(tmp_path / "proxy-crash-capital.sqlite3")
    _deposit(proxy_repo, 1_000_000, 1)
    _seed_reserves(proxy_repo, seal)
    crashing = DailyBarProxy(
        database_path=str(tmp_path / "proxy-crash.sqlite3"),
        clock=_Clock(RECORDED_AT),
        _fault_hook=hook,
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        _executed_lines(crashing, proxy_repo, seal, permit, bars, scenario)
    recovered = DailyBarProxy(
        database_path=str(tmp_path / "proxy-crash.sqlite3"),
        clock=_Clock(RECORDED_AT),
    )
    _executed_lines(recovered, proxy_repo, seal, permit, bars, scenario)

    assert _normalized_snapshot(proxy_repo) == _normalized_snapshot(core_repo)
    proxy_repo.assert_conservation()
    core_repo.assert_conservation()


# =============================================================================
# Property: candidate order, lot size, price, bar shape never change result
# =============================================================================


def test_bar_shape_variation_does_not_change_adapter_result(tmp_path) -> None:
    """Settle the same economic content through two adapter passes where the
    bar shape differs but the open (the only price the fill reads) is
    unchanged; the capital result must be identical."""

    api = _api()
    seal = _proxy_seal(api)
    permit = _proxy_permit(api, seal=seal)

    scenario = _cost_scenario(30)
    bars_a = _touching_bars()
    bars_b = dict(bars_a)
    # Same open (fill price pinned by min(open, limit) = 1040), different
    # high/low/close shape: the decision table reads only the open.
    bars_b["600000.SH"] = DailyBar(
        security_id="600000.SH",
        session=TARGET_SESSION,
        open_cents=1_040,
        high_cents=1_050,
        low_cents=1_035,
        close_cents=1_045,
        limit_up_cents=1_155,
        limit_down_cents=945,
    )

    proxy_a, repo_a, _, _ = _proxy_repo(tmp_path, "prop-a")
    proxy_b, repo_b, _, _ = _proxy_repo(tmp_path, "prop-b")

    _executed_lines(proxy_a, repo_a, seal, permit, bars_a, scenario)
    _executed_lines(proxy_b, repo_b, seal, permit, bars_b, scenario)

    assert _normalized_snapshot(repo_a) == _normalized_snapshot(repo_b)
    repo_a.assert_conservation()
    repo_b.assert_conservation()


def test_settlement_order_does_not_change_core_result(tmp_path) -> None:
    """The core settles each line independently, so settling the same two
    intents in either order must produce the same capital state."""

    api = _api()
    seal = _proxy_seal(api)
    scenario = _cost_scenario(30)
    bars = _touching_bars()

    sealed_lines = seal.proposal.order_lines
    intents = []
    for permit_line in _proxy_permit(api, seal=seal).permit_lines:
        sealed_line = next(
            line
            for line in sealed_lines
            if line.order_line_id == permit_line.order_line_id
        )
        intent = replace(
            _core_intent(
                quantity=int(permit_line.permitted_quantity_units),
                limit_price_cents=int(permit_line.limit_price_cents),
            ),
            security_id=sealed_line.security_id,
            execution_id=f"proxy:{permit_line.client_order_id}",
            order_id=permit_line.client_order_id,
            reserve_source_id=f"reserve-{permit_line.order_line_id}",
            reserve_remaining_cents=permit_line.remaining_reserve_cents,
            economic_lot_id=f"lot:{sealed_line.order_line_id}",
            position_lineage_id=sealed_line.economic_lineage_id,
            source_authority="daily-bar-proxy.v2",
            recorded_at=RECORDED_AT,
        )
        intents.append((permit_line, sealed_line, intent))

    repo_a = _funded_core_repo(tmp_path, "order-a")
    repo_b = _funded_core_repo(tmp_path, "order-b")
    for repo in (repo_a, repo_b):
        for permit_line, _, _ in intents:
            _seed_reserve(
                repo,
                source_id=f"reserve-{permit_line.order_line_id}",
                gross_cents=permit_line.remaining_reserve_cents,
            )

    for permit_line, sealed_line, intent in intents:
        _settle_core(
            repo_a, intent, bar=bars[sealed_line.security_id], scenario=scenario
        )
    for permit_line, sealed_line, intent in reversed(intents):
        _settle_core(
            repo_b, intent, bar=bars[sealed_line.security_id], scenario=scenario
        )

    assert _normalized_snapshot(repo_a) == _normalized_snapshot(repo_b)
    repo_a.assert_conservation()
    repo_b.assert_conservation()
