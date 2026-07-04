from collections.abc import Callable
from contextlib import contextmanager
from contextvars import Context, ContextVar
from datetime import datetime, UTC
from threading import Lock

from rich.console import Console
from rich.live import Live
from rich.style import Style
from rich.table import Table
from rich.text import Text

console = Console()

# R140: run-id scope for the web SSE path. The progress singleton is process-global
# and its handler fan-out historically delivered every run's events to every
# concurrent run's SSE queue. Setting this ContextVar (via scoped_run_id in tests/CLI,
# or attach_run_id + copy_context in run_graph_async for the executor-thread path)
# tags each update with its originating run; register_handler(run_id=...) then
# filters so a run-scoped handler only receives its own run's agent events (system
# events with no run_id still broadcast to all handlers).
_run_id_var: ContextVar[str | None] = ContextVar("progress_run_id", default=None)


@contextmanager
def scoped_run_id(run_id: str | None):
    """Set the run-id ContextVar for the current context (tests / CLI).

    The web execution path instead uses ``attach_run_id`` + ``copy_context().run``
    so the var propagates through ``run_in_executor`` into the graph.invoke thread.
    """
    token = _run_id_var.set(run_id)
    try:
        yield
    finally:
        _run_id_var.reset(token)


def attach_run_id(ctx: Context, run_id: str | None) -> Context:
    """Bind ``run_id`` into a copied ``contextvars.Context`` for run_in_executor.

    Used by ``run_graph_async``: ``ctx = attach_run_id(copy_context(), run_id)``
    then ``loop.run_in_executor(None, lambda: ctx.run(run_graph, ...))``. The graph's
    parallel analyst nodes inherit the context (verified: langgraph sync invoke
    propagates the calling context to parallel branches), so each agent's
    ``progress.update_status`` reads the correct run_id.
    """
    if run_id is not None:
        ctx.run(_run_id_var.set, run_id)
    return ctx


class AgentProgress:
    """Manages progress tracking for multiple agents."""

    def __init__(self):
        self.agent_status: dict[str, dict[str, str]] = {}
        self.table = Table(show_header=False, box=None, padding=(0, 1))
        self.live = Live(self.table, console=console, refresh_per_second=4)
        self.started = False
        self._handlers_lock = Lock()
        # R140: handlers now carry an optional run_id. A handler with run_id=None is
        # a broadcast handler (legacy/CLI) and receives every event. A handler with
        # run_id=X receives only updates whose run_id is X (its own run's agent
        # events) or None (system/broadcast events).
        self.update_handlers: list[Callable[..., None]] = []

    def register_handler(self, handler: Callable[..., None], run_id: str | None = None):
        """Register a handler to be called when agent status updates.

        If ``run_id`` is given the handler is run-scoped: it fires only for updates
        originating from that run (matching run_id) plus system events (run_id None),
        isolating concurrent runs. Without ``run_id`` the handler is broadcast (legacy).
        """
        with self._handlers_lock:
            self.update_handlers.append(handler)  # type: ignore[arg-type]
            # Stash the run_id alongside the handler via a private attribute so the
            # fan-out can read it without changing the handler-list shape that other
            # code (e.g. unregister pop) relies on.
            setattr(handler, "_progress_run_id", run_id)
        return handler  # Return handler to support use as decorator

    def unregister_handler(self, handler: Callable[..., None]):
        """Unregister a previously registered handler."""
        with self._handlers_lock:
            if handler in self.update_handlers:
                self.update_handlers.remove(handler)  # type: ignore[arg-type]

    def start(self):
        """Start the progress display."""
        if not self.started:
            self.live.start()
            self.started = True

    def stop(self):
        """Stop the progress display."""
        if self.started:
            self.live.stop()
            self.started = False

    def update_status(self, agent_name: str, ticker: str | None = None, status: str = "", analysis: str | None = None):
        """Update the status of an agent."""
        if agent_name not in self.agent_status:
            self.agent_status[agent_name] = {"status": "", "ticker": None}

        if ticker:
            self.agent_status[agent_name]["ticker"] = ticker
        if status:
            self.agent_status[agent_name]["status"] = status
        if analysis:
            self.agent_status[agent_name]["analysis"] = analysis

        # Set the timestamp as UTC datetime
        timestamp = datetime.now(UTC).isoformat()
        self.agent_status[agent_name]["timestamp"] = timestamp

        # Snapshot the handler list under the lock so concurrent
        # unregister/append calls don't mutate it mid-iteration.
        with self._handlers_lock:
            handler_snapshot = list(self.update_handlers)

        # R140: run-scoped fan-out. update_run_id is the originating run (set via the
        # run-id ContextVar on the executing thread; None for system/CLI/legacy events).
        update_run_id = _run_id_var.get()
        for handler in handler_snapshot:
            handler_run_id = getattr(handler, "_progress_run_id", None)
            # Skip only when BOTH are run-scoped AND differ. Broadcast handlers
            # (handler_run_id None) and system events (update_run_id None) always fire.
            if handler_run_id is not None and update_run_id is not None and handler_run_id != update_run_id:
                continue
            handler(agent_name, ticker, status, analysis, timestamp)

        self._refresh_display()

    def _get_display_name(self, agent_name: str) -> str:
        """Convert agent_name to a display-friendly format."""
        return agent_name.replace("_agent", "").replace("_", " ").title()

    def _refresh_display(self):
        """Refresh the progress display."""
        self.table.columns.clear()
        self.table.add_column(width=100)

        # Sort agents with Risk Management and Portfolio Management at the bottom
        def sort_key(item):
            agent_name = item[0]
            if "risk_management" in agent_name:
                return (2, agent_name)
            if "portfolio_management" in agent_name:
                return (3, agent_name)
            return (1, agent_name)

        for agent_name, info in sorted(self.agent_status.items(), key=sort_key):
            status = info["status"]
            ticker = info["ticker"]
            # Create the status text with appropriate styling
            if status.lower() == "done":
                style = Style(color="green", bold=True)
                symbol = "✓"
            elif status.lower() == "error":
                style = Style(color="red", bold=True)
                symbol = "✗"
            else:
                style = Style(color="yellow")
                symbol = "⋯"

            agent_display = self._get_display_name(agent_name)
            status_text = Text()
            status_text.append(f"{symbol} ", style=style)
            status_text.append(f"{agent_display:<20}", style=Style(bold=True))

            if ticker:
                status_text.append(f"[{ticker}] ", style=Style(color="cyan"))
            status_text.append(status, style=style)

            self.table.add_row(status_text)


# Create a global instance
progress = AgentProgress()
