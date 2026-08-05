"""Account identity binding for the AccountCapitalTruth ledger.

Plan 02 Task 1 introduced the binding inside ``repository.py``; Plan 02
Task 3 moves it here so the financing-flow DTOs (``capital/flows.py``) can
carry the binding without importing the repository module. ``repository``
re-exports the name unchanged.
"""

from __future__ import annotations

from pydantic import model_validator

from src.screening.offensive.v3.contracts import (
    CanonicalModel,
    ExecutionMode,
    Sha256,
)
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr


class AccountBinding(CanonicalModel):
    """The immutable account/environment/currency identity of one ledger.

    One real broker account owns exactly one AccountCapitalTruth stream; the
    binding freezes portfolio, account, mode, base currency, and the
    account/environment fingerprint together.
    """

    portfolio_id: NonEmptyStr
    mode: ExecutionMode
    broker_account_id: NonEmptyStr | None
    base_currency: NonEmptyStr
    environment_fingerprint: Sha256 | None

    @model_validator(mode="after")
    def validate_binding(self) -> "AccountBinding":
        if self.mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
            raise ValueError("research mode cannot bind executable capital truth")
        if self.mode is ExecutionMode.DAILY_BAR_PROXY:
            if self.broker_account_id is not None:
                raise ValueError("proxy mode cannot bind a real broker account")
        else:
            if self.broker_account_id is None:
                raise ValueError("manual and broker modes require an account")
            if self.environment_fingerprint is None:
                raise ValueError(
                    "manual and broker modes require an environment fingerprint"
                )
        return self


__all__ = ["AccountBinding"]
