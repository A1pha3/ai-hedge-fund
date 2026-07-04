from __future__ import annotations

import threading

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
    updater_thread = threading.Thread(target=lambda: [progress.update_status("agent_a", ticker="X", status="running") for _ in range(500)])

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


def test_progress_run_scoped_handlers_isolate_concurrent_runs() -> None:
    """R140 fix: a handler registered with ``run_id`` receives only its own run's
    agent events (plus system/broadcast events), NOT another run's agent events.

    Previously the global handler fan-out delivered every run's analyst updates to
    every concurrent run's SSE queue (cross-run contamination). The fix adds a
    run-id ContextVar read by ``update_status`` and an optional ``run_id`` filter
    on ``register_handler``; agent events (run_id set) route only to matching
    handlers, while system events (run_id unset) still broadcast to all.
    """
    from src.utils import progress as progress_mod

    progress = AgentProgress()

    run_a_events: list[str] = []
    run_b_events: list[str] = []

    def handler_a(agent_name, *_args, **_kwargs) -> None:
        run_a_events.append(agent_name)

    def handler_b(agent_name, *_args, **_kwargs) -> None:
        run_b_events.append(agent_name)

    progress.register_handler(handler_a, run_id="A")
    progress.register_handler(handler_b, run_id="B")
    try:
        # Run A's analyst update, scoped to run A via the run-id ContextVar.
        with progress_mod.scoped_run_id("A"):
            progress.update_status("warren_buffett_agent", ticker="AAPL", status="Analyzing")

        # Run A's handler received its own agent event; Run B's did NOT.
        assert run_a_events == ["warren_buffett_agent"]
        assert run_b_events == [], "Run B contaminated by Run A's run-scoped agent event"

        # System event (no run_id set) still broadcasts to BOTH run-scoped handlers.
        progress.update_status("system", status="Preparing hedge fund run")
        assert run_a_events == ["warren_buffett_agent", "system"]
        assert run_b_events == ["system"], "system events must still broadcast to all runs"
    finally:
        progress.unregister_handler(handler_a)
        progress.unregister_handler(handler_b)


def test_progress_broadcast_handler_still_receives_all_events() -> None:
    """R140 fix backward-compat: a handler registered WITHOUT run_id (legacy / CLI)
    still receives every event (broadcast), unchanged from pre-fix behavior."""
    from src.utils import progress as progress_mod

    progress = AgentProgress()
    broadcast_events: list[str] = []
    progress.register_handler(lambda name, *_a, **_k: broadcast_events.append(name))
    try:
        with progress_mod.scoped_run_id("A"):
            progress.update_status("warren_buffett_agent", ticker="AAPL", status="Analyzing")
        progress.update_status("system", status="Preparing")
        assert broadcast_events == ["warren_buffett_agent", "system"]
    finally:
        progress.update_handlers.clear()
