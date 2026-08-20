"""Replay session-facts assembler — Phase 5b of the paired BTST forward trial.

Pure assembly (evidence reads only, zero writes): one published bar-set record
plus optional regime observation and store-verified candidates become one
``ReplaySessionFacts``. Fail-closed semantics are preserved, not invented:
``selected_candidates`` stays ``None`` unless the caller has store-verified
records (the engine rejects None on signal sessions); marks are derived from
the same session's close prices (cents → micros) so valuation and execution
share one bar source.

Constitutional grounding (2026-08-20 review): replay inputs live on the
evidence timeline — the assembler never touches seeding sources directly.
"""

from __future__ import annotations

from datetime import date
from typing import Mapping

from src.screening.offensive.v3.evidence.market_bars import bars_from_record
from src.screening.offensive.v3.evidence.regime import ActiveRegimeObservation
from src.screening.offensive.v3.evidence.repository import EvidenceRepository
from src.screening.offensive.v3.orchestration.paired_trial import CommittedBtstCandidate
from src.screening.offensive.v3.orchestration.replay import ReplaySessionFacts

_CENTS_TO_MICROS = 10_000


class ReplayAssemblyError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def assemble_replay_session_facts(
    *,
    repository: EvidenceRepository,
    session: date,
    bar_record,
    regime_observation: ActiveRegimeObservation | None = None,
    selected_candidates: tuple[CommittedBtstCandidate, ...] | None = None,
) -> ReplaySessionFacts:
    """Assemble one session's PIT facts from published evidence.

    ``bar_record`` is the session's bar-set evidence record; it doubles as the
    per-session ``snapshot_evidence`` the close valuation binds (same-session,
    own evidence id — the idempotency contract ReplaySessionFacts documents).
    ``regime_observation`` is required on signal sessions by the engine; the
    assembler passes it through untouched. ``selected_candidates``: pass the
    store-verified tuple (``()`` is a legal empty signal session); leaving
    ``None`` preserves the engine's wiring-absent fail-closed.
    """
    if regime_observation is not None and regime_observation.observation.signal_session != session:
        raise ReplayAssemblyError(
            "regime_session_mismatch",
            f"regime observation is for {regime_observation.observation.signal_session}; "
            f"facts are for {session}",
        )
    if selected_candidates is not None:
        for candidate in selected_candidates:
            if candidate.payload.signal_session != session:
                raise ReplayAssemblyError(
                    "candidate_session_mismatch",
                    f"candidate {candidate.payload.candidate_id} is for "
                    f"{candidate.payload.signal_session}; facts are for {session}",
                )
    bars = bars_from_record(repository, bar_record, expected_session=session)
    marks = {security: bar.close_cents * _CENTS_TO_MICROS for security, bar in bars.items()}
    return ReplaySessionFacts(
        session=session,
        snapshot_evidence=bar_record,
        bars=bars,
        marks=marks,
        regime_observation=regime_observation,
        selected_candidates=selected_candidates,
    )


__all__ = ["ReplayAssemblyError", "assemble_replay_session_facts"]
