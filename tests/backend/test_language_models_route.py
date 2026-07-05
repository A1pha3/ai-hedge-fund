"""c360/autodev-4: NS-17 silent-except drain on /language-models route.

The Ollama fallback at app/backend/routes/language_models.py:46 swallowed
``except Exception`` with no logger call — operator saw a silently shortened
model list when Ollama was broken (not just "not running"), with no trace.
Sibling service layer (OllamaService.get_available_models) logs at ERROR,
but the route-layer swallow still masked the call-site failure from the
route's own observability. Mirrors the c290-c295 screening-route verdict
fallback pattern (logger.warning + exc_info=True before the degraded path).
"""

from __future__ import annotations

from pathlib import Path


def test_ollama_fallback_logs_warning_not_silent():
    """NS-17 regression guard: the Ollama fallback except block must log.

    Verifies the route source no longer contains a bare ``except Exception``
    followed by an empty fallback body with no logger call. This is a
    source-text regression guard (the route's exception path is async and
    network-dependent, hard to exercise deterministically in a unit test).
    """
    src_path = Path(__file__).resolve().parents[2] / "app" / "backend" / "routes" / "language_models.py"
    src_text = src_path.read_text(encoding="utf-8")
    # Locate the Ollama fallback block.
    assert "ollama_models = await ollama_service.get_available_models()" in src_text
    # The except block must include a logger call (warning/info/exception/debug),
    # not a bare pass / empty assignment.
    fn_start = src_text.index("async def get_language_models")
    fn_end = src_text.index("\n\n\n", fn_start)
    fn_body = src_text[fn_start:fn_end]
    # Find the except block within this function
    assert "except Exception" in fn_body, "expected except Exception for Ollama fallback"
    # The except block must reference logger.* — extract the lines after except
    except_idx = fn_body.index("except Exception")
    except_block = fn_body[except_idx : except_idx + 300]
    assert "logger." in except_block, f"NS-17 regression: language_models route Ollama fallback except block has no logger call " f"(should mirror screening.py:267 logger.warning + exc_info=True): {except_block!r}"
    assert "exc_info=True" in except_block or "exc_info()" in except_block, f"NS-17 regression: Ollama fallback log must include exc_info for diagnosability " f"(screening c314 pattern): {except_block!r}"
