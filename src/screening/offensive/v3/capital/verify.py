"""Ledger verification report and CLI for one capital authority store.

Plan 02 Task 7: ``CapitalRepository.verify_ledger()`` recomputes the
capital conservation identity and the projection invariants from the
append-only history and reports ``PASS``/``FAIL`` per dimension; this
module carries the report types and the command-line verifier:

    python -m src.screening.offensive.v3.capital.verify --db PATH

The verifier opens the ledger read-only in intent (it never appends),
prints ``capital_conservation=... projection_rebuild=...`` and exits zero
only when both dimensions pass.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import Enum


class VerificationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class LedgerVerificationReport:
    """The two verification dimensions plus human-readable details."""

    capital_conservation: VerificationStatus
    projection_rebuild: VerificationStatus
    details: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return (
            self.capital_conservation is VerificationStatus.PASS
            and self.projection_rebuild is VerificationStatus.PASS
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="capital.verify",
        description=(
            "Verify one Plan 02 capital ledger database: conservation of"
            " the append-only history and projection rebuild."
        ),
    )
    parser.add_argument(
        "--db",
        required=True,
        help="Path to the capital ledger SQLite database.",
    )
    args = parser.parse_args(argv)

    from src.screening.offensive.v3.capital.repository import (
        CapitalRepository,
    )

    repository = CapitalRepository.initialize(args.db)
    report = repository.verify_ledger()
    print(
        f"capital_conservation={report.capital_conservation.value}"
        f" projection_rebuild={report.projection_rebuild.value}"
    )
    for detail in report.details:
        print(f"detail: {detail}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
