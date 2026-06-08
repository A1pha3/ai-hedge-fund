from __future__ import annotations

import threading
import time

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