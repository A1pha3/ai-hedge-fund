"""Research package public API with side-effect-free package imports."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any


__all__ = [
    "DigestResult",
    "FileSelectionArtifactWriter",
    "SelectionArtifactWriter",
    "append_research_feedback",
    "build_selection_snapshot",
    "format_digest_markdown",
    "read_research_feedback",
    "render_selection_review",
    "run_digest",
    "summarize_research_feedback",
    "summarize_research_feedback_directory",
]

_EXPORTS = {
    "DigestResult": (".digest", "DigestResult"),
    "FileSelectionArtifactWriter": (".artifacts", "FileSelectionArtifactWriter"),
    "SelectionArtifactWriter": (".artifacts", "SelectionArtifactWriter"),
    "append_research_feedback": (".feedback", "append_research_feedback"),
    "build_selection_snapshot": (".artifacts", "build_selection_snapshot"),
    "format_digest_markdown": (".digest", "format_digest_markdown"),
    "read_research_feedback": (".feedback", "read_research_feedback"),
    "render_selection_review": (".review_renderer", "render_selection_review"),
    "run_digest": (".digest", "run_digest"),
    "summarize_research_feedback": (".feedback", "summarize_research_feedback"),
    "summarize_research_feedback_directory": (
        ".feedback",
        "summarize_research_feedback_directory",
    ),
}


def __getattr__(name: str) -> Any:
    """Resolve the historical package-level exports only when requested."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


if TYPE_CHECKING:
    from .artifacts import (
        FileSelectionArtifactWriter,
        SelectionArtifactWriter,
        build_selection_snapshot,
    )
    from .digest import DigestResult, format_digest_markdown, run_digest
    from .feedback import (
        append_research_feedback,
        read_research_feedback,
        summarize_research_feedback,
        summarize_research_feedback_directory,
    )
    from .review_renderer import render_selection_review
