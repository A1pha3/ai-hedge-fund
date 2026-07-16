from __future__ import annotations

from datetime import date

from src.screening.offensive.readiness_reference import (
    ReferenceProvenance,
    reference_fingerprint,
)


def shared_reference_fields(as_of: date, seed: object) -> dict[str, object]:
    """Deterministic exact-session reference provenance for readiness tests."""

    security = ReferenceProvenance.create(
        observed_on=as_of,
        effective_from=as_of,
        effective_through=as_of,
        source="tushare.stock_basic",
        version="test-stock-basic-v1",
        content_fingerprint=reference_fingerprint(
            {"dataset": "security", "seed": seed}
        ),
    )
    sw = ReferenceProvenance.create(
        observed_on=as_of,
        effective_from=as_of,
        effective_through=as_of,
        source="tushare.index_classify+index_member",
        version="test-sw-membership-v1",
        content_fingerprint=reference_fingerprint(
            {"dataset": "sw", "seed": seed}
        ),
    )
    return {
        "security_reference": security,
        "sw_reference": sw,
        "frozen_source_fingerprint": reference_fingerprint(
            {
                "dataset": "frozen_shared_source",
                "seed": seed,
                "security": security.source_fingerprint,
                "sw": sw.source_fingerprint,
            }
        ),
    }
