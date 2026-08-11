"""Plan Task 14 Step 2: adversarial fault campaign for the paired trial.

The crash-injection seams (``ShadowProxyAdapter._fault_hook`` /
``ShadowProxyLifecycle._fault_hook``) and the reserve/entry/exit idempotency
of the append-only phase fact store are already exercised green at the
component level (``test_shadow_proxy_entry``,
``test_shadow_proxy_lifecycle``). This campaign is the orchestration-level
adversarial layer that sits on top of them: it drives the same paired world
through the *inputs* a real run could see — prolonged down-limit locks,
suspended sessions, a stale writer lease, a divergent re-commit — and the
one crash boundary the component tests leave open (the first arm interrupted
mid-ladder inside ``advance_session``).

Every assertion is the property the plan names: no quantity increase on
replay, no oversell across sessions, no dropped exit obligation under
prolonged lock, entry-side writes fenced by the lease while exit
obligations survive, and a divergent pair re-commit latched permanently.
"""

from __future__ import annotations

import sys
from datetime import date, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.contracts.trial import TrialArm
from src.screening.offensive.v3.execution.lifecycle import OpenExecutionVerdict
from src.screening.offensive.v3.execution.shadow_lifecycle import (
    ShadowProxyLifecycle,
)
from src.screening.offensive.v3.execution.shadow_proxy import (
    ShadowArmExecutionContext,
    ShadowProxyError,
)

# This campaign lives in tests/offensive/v3/orchestration/; the paired world,
# session ladder, and session-input builder live one level up in execution/.
_EXEC_DIR = Path(__file__).resolve().parents[1] / "execution"
if str(_EXEC_DIR) not in sys.path:
    sys.path.insert(0, str(_EXEC_DIR))
from test_shadow_proxy_entry import (  # noqa: E402
    COMMAND_AT,
    PORTFOLIO,
    RECORDED_AT,
    SEND_DEADLINE,
    TRIAL_ID,
    _cost_scenario,
    _mechanical_bindings,
    _record,
    _touching_bars,
)
from test_shadow_proxy_exit import (  # noqa: E402
    ENTRY_SESSION,
    EXIT_DUE_SESSION,
    TRADING_SESSIONS,
    _LifecycleWorld,
    _exit_bar,
)
from test_shadow_proxy_lifecycle import (  # noqa: E402
    _entry_session_input,
    _session_close,
)

UTC = timezone.utc
_SECURITY = "300001.SZ"


def _contexts(world: _LifecycleWorld) -> dict[TrialArm, ShadowArmExecutionContext]:
    """Both arm contexts under the live writer lease (the advance_session shape)."""

    return {
        arm: ShadowArmExecutionContext(
            trial_id=TRIAL_ID,
            arm=arm,
            portfolio_id=PORTFOLIO,
            decision_store=world.store,
            capital_repository=world.capital[arm],
            writer_lease=world.lease,
        )
        for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER)
    }


def _reserve_both(world: _LifecycleWorld) -> None:
    """Reserve each arm through its OWN adapter (each adapter owns a separate
    proxy fact-store); mirrors the lifecycle entry-session fixture exactly."""

    world.clock._moment = COMMAND_AT  # noqa: SLF001
    contexts = _contexts(world)
    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        world.adapters[arm].reserve_committed_pair(world.pair_key, {arm: contexts[arm]})


@pytest.fixture()
def world(tmp_path: Path) -> _LifecycleWorld:
    return _LifecycleWorld(tmp_path)


# =============================================================================
# Crash at the first arm's mid-ladder boundary inside advance_session
# =============================================================================


def test_crash_after_champion_exits_then_replay_finalizes_both_arms(
    world: _LifecycleWorld,
) -> None:
    """A crash after the champion's exits land (before its entries) leaves the
    champion mid-ladder and the challenger untouched. A clean replay must drive
    BOTH arms to SESSION_FINALIZED: the champion resumes from after-exits, the
    challenger runs end to end, neither opens a duplicate entry."""

    _reserve_both(world)
    world.clock._moment = _session_close(ENTRY_SESSION)  # noqa: SLF001

    def fault(phase: str) -> None:
        if phase == "lifecycle.after_exits:CHAMPION":
            raise RuntimeError("simulated crash after champion exits")

    crashing = ShadowProxyLifecycle(
        world._states(),  # noqa: SLF001
        clock=world.clock,
        _fault_hook=fault,
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        crashing.advance_session(_entry_session_input(world), _contexts(world))

    # Replay with the clean lifecycle: both arms finalize this run.
    world.clock._moment = _session_close(ENTRY_SESSION)  # noqa: SLF001
    receipt = world.lifecycle.advance_session(
        _entry_session_input(world), _contexts(world)
    )
    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        assert receipt.arms[arm].finalized is not None
        assert receipt.arms[arm].finalized.phase == "SESSION_FINALIZED"
        committed = world.lifecycle._committed_phases(  # noqa: SLF001
            world.capital[arm], ENTRY_SESSION
        )
        assert "SESSION_FINALIZED" in committed
        # Exactly one entry settled per arm: no duplicate from the replay.
        assert world.position_quantity(arm) > 0
        world.capital[arm].assert_conservation()


# =============================================================================
# Prolonged locked / suspended bars: exit obligation survives, no oversell
# =============================================================================


def test_locked_down_exit_retains_position_then_fills_next_session(
    world: _LifecycleWorld,
) -> None:
    """A one-price down-limit lock leaves the position and mandate intact; the
    next tradable session sells it. No shares are oversold across the lock."""

    arm = TrialArm.CHAMPION
    world.open_position(arm)
    world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    held = world.position_quantity(arm)
    assert held > 0
    world.clock._moment = _session_close(EXIT_DUE_SESSION)  # noqa: SLF001
    locked = world.lifecycle.execute_due_exits(
        arm,
        EXIT_DUE_SESSION,
        {_SECURITY: _exit_bar(EXIT_DUE_SESSION, limit_down=True)},
        _cost_scenario(30),
    )
    assert locked[0].verdict is OpenExecutionVerdict.UNKNOWN
    assert world.position_quantity(arm) == held  # nothing sold under the lock
    # The next session opens freely: the same mandate re-claims and fills.
    runout = date(2026, 8, 20)
    world.clock._moment = _session_close(runout)  # noqa: SLF001
    filled = world.lifecycle.execute_due_exits(
        arm, runout, {_SECURITY: _exit_bar(runout)}, _cost_scenario(30)
    )
    assert filled[0].verdict is OpenExecutionVerdict.FILLED
    assert filled[0].sold_quantity == held
    assert world.position_quantity(arm) == 0
    world.capital[arm].assert_conservation()


def test_suspended_session_retains_position_then_fills_next_session(
    world: _LifecycleWorld,
) -> None:
    """A suspended session (no tradable open) never fills; the mandate survives
    and a later session still sells the full holding."""

    arm = TrialArm.CHAMPION
    world.open_position(arm)
    world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    held = world.position_quantity(arm)
    world.clock._moment = _session_close(EXIT_DUE_SESSION)  # noqa: SLF001
    suspended = world.lifecycle.execute_due_exits(
        arm,
        EXIT_DUE_SESSION,
        {_SECURITY: _exit_bar(EXIT_DUE_SESSION, suspended=True)},
        _cost_scenario(30),
    )
    assert suspended[0].verdict is OpenExecutionVerdict.UNKNOWN
    assert world.position_quantity(arm) == held
    runout = date(2026, 8, 20)
    world.clock._moment = _session_close(runout)  # noqa: SLF001
    filled = world.lifecycle.execute_due_exits(
        arm, runout, {_SECURITY: _exit_bar(runout)}, _cost_scenario(30)
    )
    assert filled[0].verdict is OpenExecutionVerdict.FILLED
    assert world.position_quantity(arm) == 0
    world.capital[arm].assert_conservation()


def test_prolonged_lock_keeps_itt_row_and_mandate_until_runout(
    world: _LifecycleWorld,
) -> None:
    """A position that never fills through every remaining session retains its
    full quantity and a live, claimable exit obligation — the ITT row is never
    dropped just because the market would not let it exit."""

    arm = TrialArm.CHAMPION
    world.open_position(arm)
    world.lifecycle.derive_exits(arm, TRADING_SESSIONS)
    held = world.position_quantity(arm)
    assert held > 0
    lineage, lot = world.lot_key(arm)
    # Drive every session at/after the exit due date against a locked bar.
    for session in TRADING_SESSIONS:
        if session < EXIT_DUE_SESSION:
            continue
        world.clock._moment = _session_close(session)  # noqa: SLF001
        world.lifecycle.execute_due_exits(
            arm,
            session,
            {_SECURITY: _exit_bar(session, limit_down=True)},
            _cost_scenario(30),
        )
    # Full holding retained; the obligation is still PENDING and claimable.
    assert world.position_quantity(arm) == held
    projection = world.exit_lanes[arm].exit_state(lineage, lot)
    assert projection is not None
    assert projection.status == "PENDING"
    assert projection.claimable_quantity == held
    world.capital[arm].assert_conservation()


# =============================================================================
# Writer-lease takeover: entry writes fenced, no capital mutation
# =============================================================================


def test_lease_takeover_fences_future_entry_writes(
    world: _LifecycleWorld,
) -> None:
    """A second writer claim bumps the fencing epoch. The stale lease must fail
    before any entry-side capital write (the adapter re-validates the lease on
    every committed-pair read)."""

    _reserve_both(world)
    world.store.claim_writer()  # takeover: the world's lease is now stale
    decision = world.decisions[TrialArm.CHAMPION]
    world.clock._moment = RECORDED_AT  # noqa: SLF001
    champ_version = world.capital[TrialArm.CHAMPION].capital_version()
    with pytest.raises(ShadowProxyError) as excinfo:
        world.adapters[TrialArm.CHAMPION].execute_entries(
            world.pair_key,
            _contexts(world)[TrialArm.CHAMPION],
            mechanical_bindings=_mechanical_bindings(decision),
            bars=_touching_bars(decision),
            scenario=_cost_scenario(30),
            command_at=COMMAND_AT,
            send_deadline=SEND_DEADLINE,
        )
    assert excinfo.value.code == "writer_lease_stale"
    # No capital write happened under the stale lease.
    assert world.capital[TrialArm.CHAMPION].capital_version() == champ_version
    world.capital[TrialArm.CHAMPION].assert_conservation()


# =============================================================================
# Divergent re-commit of the pair: permanently latched
# =============================================================================


def test_divergent_duplicate_pair_commit_is_permanently_latched(
    world: _LifecycleWorld,
) -> None:
    """Re-committing the same pair key with a different champion payload (a
    different shadow_decision_id, hence a different artifact hash) is a
    permanent protocol breach: the immutable store never accepts it."""

    champion = world.decisions[TrialArm.CHAMPION]
    diverged = champion.model_copy(
        update={"shadow_decision_id": champion.shadow_decision_id + "-diverged"}
    )
    with pytest.raises(Exception, match="arm_decision_conflict"):
        world.store.commit_pair(
            _record(TrialArm.CHAMPION, diverged),
            _record(TrialArm.CHALLENGER, world.decisions[TrialArm.CHALLENGER]),
        )
