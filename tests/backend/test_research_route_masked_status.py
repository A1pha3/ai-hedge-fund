"""c362/autodev-4: masked-HTTP-200-on-error drain on /research/lookback-audit.

The route at app/backend/routes/research.py:80 caught ``Exception`` and returned
a ``LookbackAuditErrorResponse`` body with HTTP 200 — defeating any monitoring
that keys off status codes (the audit could crash on every request and
dashboards would see "all green"). Every sibling route uses ``@safe_route``
which logs with traceback and converts to 500. This test is a source-text
regression guard asserting the masked-200 anti-pattern is gone.
"""

from __future__ import annotations

from pathlib import Path


def test_lookback_audit_route_does_not_mask_500_as_200():
    """The /research/lookback-audit route must not return an error body as 200.

    Verifies the route source:
    1. No longer contains ``return LookbackAuditErrorResponse(`` inside an
       ``except Exception`` block (the masked-200 anti-pattern).
    2. Uses ``@safe_route`` (the canonical sibling pattern) so unexpected
       exceptions become 500 + logger.exception.
    """
    src_path = Path(__file__).resolve().parents[2] / "app" / "backend" / "routes" / "research.py"
    src_text = src_path.read_text(encoding="utf-8")

    # The masked-200 anti-pattern: returning an error response from except.
    # After the fix, the only valid use of LookbackAuditErrorResponse is the
    # response_model declaration; an except block must NOT return it.
    fn_start = src_text.index("async def get_lookback_audit")
    fn_end = src_text.index("\n\n", fn_start)
    fn_body = src_text[fn_start:fn_end]
    assert "return LookbackAuditErrorResponse(" not in fn_body, "masked-HTTP-200 regression: /research/lookback-audit returns " "LookbackAuditErrorResponse from except block — must use @safe_route " "→ HTTPException(500) + logger.exception (sibling pattern)."

    # The route must use @safe_route so unhandled exceptions → 500 + log.
    # Locate the decorator stack above the function def.
    decorator_block = src_text[: src_text.index("async def get_lookback_audit")]
    last_router_line = decorator_block.rfind("@router.")
    decorators_above_fn = src_text[last_router_line : src_text.index("async def get_lookback_audit")]
    assert "@safe_route" in decorators_above_fn, f"@safe_route decorator missing from /research/lookback-audit route " f"(every sibling route uses it for consistent 500 + logger.exception): " f"{decorators_above_fn!r}"
