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

from collections.abc import Callable, Mapping
from datetime import date

from src.screening.offensive.v3.contracts.evidence import EvidenceRecord
from src.screening.offensive.v3.evidence.market_bars import bars_from_record
from src.screening.offensive.v3.evidence.regime import ActiveRegimeObservation
from src.screening.offensive.v3.evidence.repository import EvidenceRepository
from src.screening.offensive.v3.execution.lifecycle import DailyBar
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
    marked_securities: frozenset[str] | set[str] | None = None,
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
    # marks 纪律 (对抗审查 2026-08-20): 退出结算后 flat 证券的 mark 是冲突 —
    # 顺序重放的驱动层按当期持仓集传 marked_securities; None = 全量 (仅限
    # 尚无持仓维度的构建期/测试用途)。
    if marked_securities is not None:
        missing = set(marked_securities) - set(bars)
        if missing:
            raise ReplayAssemblyError(
                "marked_security_bar_missing",
                f"marked securities without bars in session {session}: {sorted(missing)[:5]}",
            )
    marks = {
        security: bar.close_cents * _CENTS_TO_MICROS
        for security, bar in bars.items()
        if marked_securities is None or security in marked_securities
    }
    return ReplaySessionFacts(
        session=session,
        snapshot_evidence=bar_record,
        bars=bars,
        marks=marks,
        regime_observation=regime_observation,
        selected_candidates=selected_candidates,
    )


def evidence_backed_bar_for(
    repository: EvidenceRepository,
    bar_records: Mapping[date, EvidenceRecord],
) -> Callable[[date, str], DailyBar | None]:
    """replay_assembly ↔ session_driver 的唯一正式汇合点 (终轮审查 P3-b)。

    每个会话的 bar-set 证据记录按需组装成 ``ReplaySessionFacts`` (blob →
    信封绑定 → 严格解码, 全部在证据时间轴内), 再向驱动器供 bar 查询。
    官方接线必须经此构造 ``bar_for`` —— 签名上只接受证据仓库与已发布
    记录, 调用方**无法**绕过证据时间轴喂 CSV/price_cache 原始数据 (驱动
    器 ``bar_for`` 源契约, P3-a)。marks 不经此层: 驱动器从同一 bar 源自
    建持仓过滤的收盘 marks, 与 facts 同源。
    """
    facts_cache: dict[date, ReplaySessionFacts] = {}

    def bar_for(session: date, security_id: str) -> DailyBar | None:
        record = bar_records.get(session)
        if record is None:
            return None  # 未发布证据的会话没有可观测 bar (结算判 UNKNOWN)
        if session not in facts_cache:
            facts_cache[session] = assemble_replay_session_facts(
                repository=repository, session=session, bar_record=record
            )
        return facts_cache[session].bars.get(security_id)

    return bar_for


__all__ = [
    "ReplayAssemblyError",
    "assemble_replay_session_facts",
    "evidence_backed_bar_for",
]
