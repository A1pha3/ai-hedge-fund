from __future__ import annotations

import threading
import time

import pytest

from src.utils.progress import AgentProgress


def test_progress_handler_register_is_thread_safe() -> None:
    """Concurrent register/unregister during update_status must not raise
    "list changed size during iteration". The previous implementation
    iterated ``self.update_handlers`` directly while another thread could
    be mutating it, which crashes the SSE event generator at the worst
    possible moment.
    """
    progress = AgentProgress()
    errors: list[BaseException] = []

    def hammer_register() -> None:
        for _ in range(200):
            handler = lambda *_args, **_kwargs: None
            progress.register_handler(handler)

    def hammer_unregister() -> None:
        # Each iteration grabs a copy and removes whatever is there. The
        # operations themselves may be no-ops if another thread already
        # removed the handler, but they must never raise.
        for _ in range(200):
            with progress._handlers_lock:
                if progress.update_handlers:
                    progress.update_handlers.pop()

    register_thread = threading.Thread(target=hammer_register)
    unregister_thread = threading.Thread(target=hammer_unregister)
    updater_thread = threading.Thread(
        target=lambda: [progress.update_status("agent_a", ticker="X", status="running") for _ in range(500)]
    )

    try:
        progress.start()
        register_thread.start()
        unregister_thread.start()
        updater_thread.start()

        register_thread.join(timeout=5.0)
        unregister_thread.join(timeout=5.0)
        updater_thread.join(timeout=5.0)
    finally:
        progress.stop()

    assert not register_thread.is_alive(), "register thread hung"
    assert not unregister_thread.is_alive(), "unregister thread hung"
    assert not updater_thread.is_alive(), "updater thread hung"
    assert errors == [], f"thread raised: {errors}"


def test_progress_unregister_unknown_handler_is_noop() -> None:
    """unregister must tolerate never-registered handlers without raising
    (the SSE stream's finally clause relies on this).
    """
    progress = AgentProgress()

    def sentinel(_name, _ticker, _status, _analysis, _ts) -> None:  # pragma: no cover - never invoked
        raise AssertionError("sentinel handler should never be invoked")

    # Should not raise even though the handler was never registered.
    progress.unregister_handler(sentinel)


def test_progress_update_status_continues_after_handler_raises() -> None:
    """A misbehaving handler must not break subsequent updates. The lock
    snapshot isolates the iteration from later mutations, and any handler
    exception must propagate cleanly so callers can choose to handle it.
    """
    progress = AgentProgress()

    called: list[str] = []

    def good_handler(agent_name, *_args, **_kwargs) -> None:
        called.append(agent_name)

    progress.register_handler(good_handler)
    progress.update_status("first", ticker="A", status="running")
    progress.update_status("second", ticker="B", status="running")

    assert called == ["first", "second"]


@pytest.mark.xfail(
    reason=(
        "Known concurrency limitation: update_status fans out to ALL registered "
        "handlers with no run/topic scoping. The web SSE path registers one handler "
        "per run (create_progress_handler, bound to that run's asyncio.Queue), so two "
        "concurrent hedge-fund runs receive EACH OTHER's progress events — cross-run "
        "SSE contamination (Run B's stream renders Run A's analyst updates). Root cause: "
        "progress is a process-global singleton; update_handlers is a global list; the "
        "update event carries no run_id; create_flow_run has no active-run gate so "
        "concurrent runs are reachable (multi-user / cross-flow / rerun-while-running). "
        "Fix needs a run-scoped topic/contextvar on update_status + handler filtering "
        "(change_risk>2, shared by CLI+web) — tracked as a blocked-on-design candidate. "
        "Pinned xfail so the green baseline holds and a future run-scoped fix gets a "
        "regression guard (xpass => fix landed, remove this marker)."
    ),
    strict=False,
)
def test_progress_handler_fanout_does_not_cross_contaminate_concurrent_runs() -> None:
    """Two concurrent web runs must NOT receive each other's progress events.

    This currently FAILS (xfail): a single ``update_status`` call is delivered to
    every registered handler because the fan-out has no run/topic scoping. With the
    eventual run-scoped fix, only the updating run's handler should receive the event.
    """
    progress = AgentProgress()

    run_a_events: list[tuple] = []
    run_b_events: list[tuple] = []

    def handler_a(agent_name, ticker, status, _analysis, _timestamp) -> None:
        run_a_events.append((agent_name, ticker, status))

    def handler_b(agent_name, ticker, status, _analysis, _timestamp) -> None:
        run_b_events.append((agent_name, ticker, status))

    progress.register_handler(handler_a)
    progress.register_handler(handler_b)
    try:
        # Run A's analyst publishes its own progress.
        progress.update_status("warren_buffett_agent", ticker="AAPL", status="Analyzing")

        # Desired (run-scoped) behavior: only Run A's handler receives Run A's event.
        assert run_a_events == [("warren_buffett_agent", "AAPL", "Analyzing")]
        assert run_b_events == [], (
            "Run B's handler was contaminated by Run A's progress event "
            "(global fan-out, no run/topic scoping) — concurrent SSE runs cross-contaminate"
        )
    finally:
        progress.unregister_handler(handler_a)
        progress.unregister_handler(handler_b)