"""Plan Task 10 RED: shadow proxy T+10 exit resolution.

The lifecycle claims due exit mandates, settles each EXIT intent through the
shared ``settle_proxy_open`` core (capital fill commits before the exit-lane
``FILLED`` fact), records the cumulative attempt outcome, and releases the
lease. On ``UNKNOWN`` / ``NO_FILL`` the position and mandate are retained for
a later session; exits continue regardless of entry, risk, or stage halts.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.contracts import ExecutionMode
from src.screening.offensive.v3.contracts.trial import TrialArm
from src.screening.offensive.v3.execution.lifecycle import (
    DailyBar,
    OpenExecutionVerdict,
)
from src.screening.offensive.v3.execution.proxy_core import ProxyCostScenario
from src.screening.offensive.v3.execution.shadow_lifecycle import (  # RED target
    ShadowArmLifecycleState,
    ShadowProxyLifecycle,
)
from src.screening.offensive.v3.gateway.exits import ExitLane

# Reuse the Task 9 frozen paired world + capital/decision seed helpers.
_ENTRY_TEST_DIR = Path(__file__).resolve().parent
if str(_ENTRY_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_ENTRY_TEST_DIR))
from test_shadow_proxy_entry import (  # noqa: E402
    CLOSE,
    COMMAND_AT,
    FEE_POLICY,
    HASH,
    NOW,
    OBSERVE_AT,
    PORTFOLIO,
    RECORDED_AT,
    SEND_DEADLINE,
    SIGNAL_DATE,
    TRIAL_ID,
    _Clock,
    _cost_scenario,
    _funded_repo,
    _mechanical_bindings,
    _pair_key,
    _paired_decisions,
    _record,
    _touching_bars,
)

UTC = timezone.utc

# A trading calendar of A-share sessions starting at the signal date. The exit
# lane resolves the T+10 due date against this: first session strictly after
# the signal, plus the entry ordinal (1), plus the frozen exit ordinal (10)
# minus 2 -> 9 sessions past the first-after-signal index.
TRADING_SESSIONS = (
    date(2026, 8, 5),   # signal (Wed)
    date(2026, 8, 6),   # T+1 entry (Thu)
    date(2026, 8, 7),
    date(2026, 8, 10),
    date(2026, 8, 11),
    date(2026, 8, 12),
    date(2026, 8, 13),
    date(2026, 8, 14),
    date(2026, 8, 17),
    date(2026, 8, 18),
    date(2026, 8, 19),   # T+10 exit due session
    date(2026, 8, 20),
    date(2026, 8, 21),
)
ENTRY_SESSION = date(2026, 8, 6)
EXIT_DUE_SESSION = date(2026, 8, 19)
_EXIT_POLICY_FINGERPRINT = HASH  # a 64-char hex sha256 (the frozen exit policy hash)
GENESIS_AT = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)


def _genesis_funded_repo(tmp_path: Path, name: str):
    """A repo funded by genesis issuance (cash + unit quanta) so close
    valuation can confirm NAV. Genesis is the first and only financing fact."""

    from src.screening.offensive.v3.capital.flows import GenesisRequest
    from src.screening.offensive.v3.capital.repository import (
        AccountBinding,
        CapitalRepository,
    )

    repository = CapitalRepository.initialize(tmp_path / f"{name}.sqlite3")
    binding = AccountBinding(
        portfolio_id=PORTFOLIO,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        broker_account_id=None,
        base_currency="CNY",
        environment_fingerprint=None,
    )
    repository.initialize_genesis(
        GenesisRequest(
            idempotency_key=f"genesis-{name}",
            account_binding=binding,
            unit_quanta=1_000,
            unit_price_numerator=1_000,
            unit_price_denominator=1,
            source_authority="test.seed",
            authorization_reference="auth-genesis-1",
            effective_at=GENESIS_AT,
            as_of=GENESIS_AT,
        )
    )
    return repository


def _exit_bar(session: date, *, limit_down: bool = False, suspended: bool = False) -> DailyBar:
    """A normal exit-session bar; the open sells freely unless locked down."""

    open_cents = 990
    if limit_down:
        # Four prices collapse onto the down-limit fence -> one-price lock.
        return DailyBar(
            security_id="300001.SZ",
            session=session,
            open_cents=891,
            high_cents=891,
            low_cents=891,
            close_cents=891,
            limit_up_cents=1089,
            limit_down_cents=891,
            suspended=suspended,
        )
    return DailyBar(
        security_id="300001.SZ",
        session=session,
        open_cents=open_cents,
        high_cents=open_cents + 8,
        low_cents=open_cents - 8,
        close_cents=open_cents + 2,
        limit_up_cents=open_cents * 11 // 10,
        limit_down_cents=open_cents * 9 // 10,
        suspended=suspended,
    )


class _LifecycleWorld:
    """A paired shadow world wired with exit lanes + the lifecycle facade."""

    def __init__(self, tmp_path: Path) -> None:
        self.champion_decision, self.challenger_decision = _paired_decisions()
        self.decisions = {
            TrialArm.CHAMPION: self.champion_decision,
            TrialArm.CHALLENGER: self.challenger_decision,
        }
        self.pair_key = _pair_key(self.champion_decision)
        # One shared mutable clock across adapter, exit lanes, and lifecycle so
        # every timestamp in one phase agrees.
        self.clock = _Clock(RECORDED_AT)
        # Import the store + committed-pair machinery lazily to keep the module
        # importable before the v3 package is fully initialized.
        from test_shadow_proxy_entry import _bundle, _genesis_manifest
        from src.screening.offensive.v3.orchestration.trial_store import (
            TrialArmDecisionStore,
        )
        from src.screening.offensive.v3.execution.shadow_proxy import (
            ShadowProxyAdapter,
        )

        self.store = TrialArmDecisionStore(database_path=str(tmp_path / "trial.sqlite3"))
        self.store.register_trial(_bundle(), _genesis_manifest())
        self.store.commit_pair(
            _record(TrialArm.CHAMPION, self.champion_decision),
            _record(TrialArm.CHALLENGER, self.challenger_decision),
        )
        self.lease = self.store.claim_writer()
        self.capital = {
            TrialArm.CHAMPION: _genesis_funded_repo(tmp_path, "champ-capital"),
            TrialArm.CHALLENGER: _genesis_funded_repo(tmp_path, "chall-capital"),
        }
        self.adapters = {
            TrialArm.CHAMPION: ShadowProxyAdapter(
                database_path=str(tmp_path / "champ-proxy.sqlite3"),
                clock=self.clock,
            ),
            TrialArm.CHALLENGER: ShadowProxyAdapter(
                database_path=str(tmp_path / "chall-proxy.sqlite3"),
                clock=self.clock,
            ),
        }
        self.exit_lanes = {
            TrialArm.CHAMPION: ExitLane(
                database_path=str(tmp_path / "champ-exits.sqlite3"),
                clock=self.clock,
            ),
            TrialArm.CHALLENGER: ExitLane(
                database_path=str(tmp_path / "chall-exits.sqlite3"),
                clock=self.clock,
            ),
        }
        self.lifecycle = ShadowProxyLifecycle(
            self._states(),
            clock=self.clock,
        )

    def _states(self) -> dict[TrialArm, ShadowArmLifecycleState]:
        states: dict[TrialArm, ShadowArmLifecycleState] = {}
        for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
            decision = self.decisions[arm]
            states[arm] = ShadowArmLifecycleState(
                trial_id=TRIAL_ID,
                arm=arm,
                portfolio_id=PORTFOLIO,
                pair_key=self.pair_key,
                base_currency="CNY",
                broker_account_id=None,
                fixed_exit_policy_fingerprint=_EXIT_POLICY_FINGERPRINT,
                decision_store=self.store,
                capital_repository=self.capital[arm],
                exit_lane=self.exit_lanes[arm],
                adapter=self.adapters[arm],
                writer_lease=self.lease,
            )
        return states

    def open_position(self, arm: TrialArm) -> None:
        """Reserve at T0 then settle the T+1 entry so a position opens."""

        from src.screening.offensive.v3.execution.shadow_proxy import (
            ShadowArmExecutionContext,
        )

        self.clock._moment = COMMAND_AT  # noqa: SLF001
        contexts = {
            arm: ShadowArmExecutionContext(
                trial_id=TRIAL_ID,
                arm=arm,
                portfolio_id=PORTFOLIO,
                decision_store=self.store,
                capital_repository=self.capital[arm],
                writer_lease=self.lease,
            )
        }
        self.adapters[arm].reserve_committed_pair(self.pair_key, contexts)
        self.clock._moment = RECORDED_AT  # noqa: SLF001
        decision = self.decisions[arm]
        self.adapters[arm].execute_entries(
            self.pair_key,
            contexts[arm],
            mechanical_bindings=_mechanical_bindings(decision),
            bars=_touching_bars(decision),
            scenario=_cost_scenario(30),
            command_at=COMMAND_AT,
            send_deadline=SEND_DEADLINE,
        )

    def position_quantity(self, arm: TrialArm) -> int:
        snap = self.capital[arm].capital_risk_snapshot(self.clock())
        if not snap.positions:
            return 0
        return int(snap.positions[0].settled_quantity)

    def lot_key(self, arm: TrialArm) -> tuple[str, str]:
        snap = self.capital[arm].capital_risk_snapshot(self.clock())
        position = snap.positions[0]
        return position.position_lineage_id, position.economic_lot_id

    def _states_to_contexts(self) -> dict[TrialArm, object]:
        from src.screening.offensive.v3.execution.shadow_proxy import (
            ShadowArmExecutionContext,
        )

        return {
            arm: ShadowArmExecutionContext(
                trial_id=TRIAL_ID,
                arm=arm,
                portfolio_id=PORTFOLIO,
                decision_store=self.store,
                capital_repository=self.capital[arm],
                writer_lease=self.lease,
            )
            for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER)
        }


@pytest.fixture()
def world(tmp_path: Path) -> _LifecycleWorld:
    return _LifecycleWorld(tmp_path)


# =============================================================================
# Step 1: exit derivation + due date
# =============================================================================


def test_exit_derives_t_plus_10_open_due_date(world) -> None:
    arm = TrialArm.CHAMPION
    world.open_position(arm)
    mandates = world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    assert len(mandates) == 1
    assert mandates[0].due_session == EXIT_DUE_SESSION
    assert mandates[0].exit_session_ordinal == 10
    assert mandates[0].quantity_knowledge.value == "KNOWN"


def test_exit_derivation_is_idempotent_when_unchanged(world) -> None:
    arm = TrialArm.CHAMPION
    world.open_position(arm)
    first = world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    second = world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    assert second[0].exit_mandate_id == first[0].exit_mandate_id
    assert second[0].mandate_revision == first[0].mandate_revision


# =============================================================================
# Step 1: exit settlement outcomes
# =============================================================================


def test_exit_fills_at_open_and_closes_position(world) -> None:
    arm = TrialArm.CHAMPION
    world.open_position(arm)
    world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    held = world.position_quantity(arm)
    assert held > 0
    # Advance to the exit session evening and settle the due exit.
    world.clock._moment = datetime(  # noqa: SLF001
        EXIT_DUE_SESSION.year, EXIT_DUE_SESSION.month, EXIT_DUE_SESSION.day, 16, 0, tzinfo=UTC
    )
    results = world.lifecycle.execute_due_exits(
        arm, EXIT_DUE_SESSION, {"300001.SZ": _exit_bar(EXIT_DUE_SESSION)}, _cost_scenario(30)
    )
    assert len(results) == 1
    assert results[0].verdict is OpenExecutionVerdict.FILLED
    assert results[0].sold_quantity == held
    assert world.position_quantity(arm) == 0
    world.capital[arm].assert_conservation()


def test_unknown_exit_keeps_position_and_mandate(world) -> None:
    arm = TrialArm.CHAMPION
    world.open_position(arm)
    world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    held = world.position_quantity(arm)
    world.clock._moment = datetime(  # noqa: SLF001
        EXIT_DUE_SESSION.year, EXIT_DUE_SESSION.month, EXIT_DUE_SESSION.day, 16, 0, tzinfo=UTC
    )
    # No bar at all -> UNKNOWN, position and mandate retained.
    results = world.lifecycle.execute_due_exits(arm, EXIT_DUE_SESSION, {}, _cost_scenario(30))
    assert results[0].verdict is OpenExecutionVerdict.UNKNOWN
    assert world.position_quantity(arm) == held
    lineage, lot = world.lot_key(arm)
    projection = world.exit_lanes[arm].exit_state(lineage, lot)
    assert projection is not None
    assert projection.claimable_quantity > 0
    assert projection.status == "PENDING"


def test_one_price_limit_down_exit_is_unknown(world) -> None:
    arm = TrialArm.CHAMPION
    world.open_position(arm)
    world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    held = world.position_quantity(arm)
    world.clock._moment = datetime(  # noqa: SLF001
        EXIT_DUE_SESSION.year, EXIT_DUE_SESSION.month, EXIT_DUE_SESSION.day, 16, 0, tzinfo=UTC
    )
    bar = {"300001.SZ": _exit_bar(EXIT_DUE_SESSION, limit_down=True)}
    results = world.lifecycle.execute_due_exits(arm, EXIT_DUE_SESSION, bar, _cost_scenario(30))
    assert results[0].verdict is OpenExecutionVerdict.UNKNOWN
    assert results[0].reason == "one_price_limit_down"
    assert world.position_quantity(arm) == held


def test_suspended_exit_is_unknown(world) -> None:
    arm = TrialArm.CHAMPION
    world.open_position(arm)
    world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    held = world.position_quantity(arm)
    world.clock._moment = datetime(  # noqa: SLF001
        EXIT_DUE_SESSION.year, EXIT_DUE_SESSION.month, EXIT_DUE_SESSION.day, 16, 0, tzinfo=UTC
    )
    bar = {"300001.SZ": _exit_bar(EXIT_DUE_SESSION, suspended=True)}
    results = world.lifecycle.execute_due_exits(arm, EXIT_DUE_SESSION, bar, _cost_scenario(30))
    assert results[0].verdict is OpenExecutionVerdict.UNKNOWN
    assert world.position_quantity(arm) == held


def test_exit_retry_next_session_after_unknown(world) -> None:
    arm = TrialArm.CHAMPION
    world.open_position(arm)
    world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    held = world.position_quantity(arm)
    world.clock._moment = datetime(  # noqa: SLF001
        EXIT_DUE_SESSION.year, EXIT_DUE_SESSION.month, EXIT_DUE_SESSION.day, 16, 0, tzinfo=UTC
    )
    # Session N: UNKNOWN (no bar) -> mandate retained, lease released.
    world.lifecycle.execute_due_exits(arm, EXIT_DUE_SESSION, {}, _cost_scenario(30))
    assert world.position_quantity(arm) == held
    # Session N+1: a normal bar -> the same mandate is re-claimed and fills.
    next_session = date(2026, 8, 20)
    world.clock._moment = datetime(  # noqa: SLF001
        next_session.year, next_session.month, next_session.day, 16, 0, tzinfo=UTC
    )
    results = world.lifecycle.execute_due_exits(
        arm, next_session, {"300001.SZ": _exit_bar(next_session)}, _cost_scenario(30)
    )
    assert len(results) == 1
    assert results[0].verdict is OpenExecutionVerdict.FILLED
    assert world.position_quantity(arm) == 0


def test_exit_never_oversells(world) -> None:
    arm = TrialArm.CHAMPION
    world.open_position(arm)
    world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    held = world.position_quantity(arm)
    world.clock._moment = datetime(  # noqa: SLF001
        EXIT_DUE_SESSION.year, EXIT_DUE_SESSION.month, EXIT_DUE_SESSION.day, 16, 0, tzinfo=UTC
    )
    results = world.lifecycle.execute_due_exits(
        arm, EXIT_DUE_SESSION, {"300001.SZ": _exit_bar(EXIT_DUE_SESSION)}, _cost_scenario(30)
    )
    assert results[0].sold_quantity <= held
    # A second claim the same session has nothing left to lease.
    again = world.lifecycle.execute_due_exits(
        arm, EXIT_DUE_SESSION, {"300001.SZ": _exit_bar(EXIT_DUE_SESSION)}, _cost_scenario(30)
    )
    assert again == ()


def test_exit_releases_lease_explicitly(world) -> None:
    arm = TrialArm.CHAMPION
    world.open_position(arm)
    world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    world.clock._moment = datetime(  # noqa: SLF001
        EXIT_DUE_SESSION.year, EXIT_DUE_SESSION.month, EXIT_DUE_SESSION.day, 16, 0, tzinfo=UTC
    )
    # An UNKNOWN exit releases the lease, so the mandate is immediately
    # re-claimable (not blocked by a dangling lease).
    world.lifecycle.execute_due_exits(arm, EXIT_DUE_SESSION, {}, _cost_scenario(30))
    claims = world.exit_lanes[arm].claim_due_exit_work(
        as_of_session=EXIT_DUE_SESSION, worker_id="shadow-lifecycle"
    )
    assert len(claims) == 1


def test_exit_stable_attempt_and_fill_ids(world) -> None:
    arm = TrialArm.CHAMPION
    world.open_position(arm)
    world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    held = world.position_quantity(arm)
    world.clock._moment = datetime(  # noqa: SLF001
        EXIT_DUE_SESSION.year, EXIT_DUE_SESSION.month, EXIT_DUE_SESSION.day, 16, 0, tzinfo=UTC
    )
    first = world.lifecycle.execute_due_exits(
        arm, EXIT_DUE_SESSION, {"300001.SZ": _exit_bar(EXIT_DUE_SESSION)}, _cost_scenario(30)
    )
    cap_v = world.capital[arm].capital_version()
    assert first[0].sold_quantity == held
    # Exact replay: same stable identity, no second capital write.
    replay = world.lifecycle.execute_due_exits(
        arm, EXIT_DUE_SESSION, {"300001.SZ": _exit_bar(EXIT_DUE_SESSION)}, _cost_scenario(30)
    )
    assert replay == ()
    assert world.capital[arm].capital_version() == cap_v


# =============================================================================
# Step 1: ExitLane.release_lease (explicit, owner-gated, idempotent)
# =============================================================================


def test_release_lease_is_idempotent_and_owner_gated(world, tmp_path: Path) -> None:
    lane = ExitLane(database_path=str(tmp_path / "rl.sqlite3"), clock=_Clock(NOW))
    # No lease exists for an unknown id.
    with pytest.raises(Exception, match="exit_lease_unknown"):
        lane.release_lease("lease:missing", worker_id="shadow-lifecycle")
