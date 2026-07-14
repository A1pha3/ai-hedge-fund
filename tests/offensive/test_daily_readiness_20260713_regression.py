"""Deterministic 2026-07-13 regression: Auto stays independent while Daily Action
readiness covers the full 652-ticker refresh universe, with two confirmed
suspensions and seven BSE-unsupported fund-flow tickers correctly classified as
expected states (not unexplained failures).

This proves the spec's core scenario (design sections 4.1 / 12.2) without a
652-row hand-written artifact: a compact fixture stores the observed category
counts plus the known suspended/unsupported identities, and a factory expands it
to 652 synthetic six-digit tickers with a conserving status distribution.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from src.screening.offensive.cache_readiness import (
    DailyActionRefreshResult,
    FundFlowStatus,
    PriceStatus,
    SuspensionEvidence,
    TickerRefreshOutcome,
    derive_stats_from_outcomes,
    universe_fingerprint,
)
from src.screening.offensive.daily_action_readiness import (
    build_daily_action_readiness,
    publish_daily_action_readiness,
)
from src.screening.offensive.daily_action_readiness import (
    SharedReadinessEvidence,
)
from src.utils.date_utils import SIGNAL_SESSION_POLICY_VERSION

_FIXTURE = Path(__file__).parent / "fixtures" / "daily_readiness_20260713.json"
_SIGNAL_DATE = date(2026, 7, 13)


def _load_fixture() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _expand_to_universe(fixture: dict) -> dict[str, TickerRefreshOutcome]:
    """Deterministically expand the compact fixture to 652 per-ticker outcomes.

    Distribution (conserving to 652):
      - price:      650 current, 2 suspended
      - fund flow:  642 current, 3 suspended, 7 unsupported
    The two confirmed suspensions and seven BSE-unsupported identities come from
    the fixture; the remaining tickers are synthetic six-digit fillers.
    """
    total = fixture["universe_total"]
    known_suspended = list(fixture["known_suspended"])
    known_unsupported = list(fixture["known_unsupported"])
    price_suspended = fixture["price_status_counts"]["suspended"]
    flow_suspended = fixture["fund_flow_status_counts"]["suspended"]
    flow_unsupported = fixture["fund_flow_status_counts"]["unsupported"]

    assert len(known_suspended) == price_suspended
    assert len(known_unsupported) == flow_unsupported

    reserved = set(known_suspended) | set(known_unsupported)
    fillers: list[str] = []
    idx = 1
    while len(fillers) < total - len(reserved):
        candidate = f"{idx:06d}"
        if candidate not in reserved:
            fillers.append(candidate)
        idx += 1

    outcomes: dict[str, TickerRefreshOutcome] = {}

    # Two confirmed suspensions: no price, no fund flow.
    for ticker in known_suspended:
        outcomes[ticker] = TickerRefreshOutcome(
            ticker=ticker,
            price_status=PriceStatus.SUSPENDED,
            price_history_rows=0,
            fund_flow_status=FundFlowStatus.SUSPENDED,
            fund_flow_history_rows=0,
        )

    # Seven BSE tickers: price current but fund flow unsupported by the provider.
    for ticker in known_unsupported:
        outcomes[ticker] = TickerRefreshOutcome(
            ticker=ticker,
            price_status=PriceStatus.CURRENT,
            price_history_rows=100,
            fund_flow_status=FundFlowStatus.UNSUPPORTED,
            fund_flow_history_rows=0,
        )

    # One additional confirmed fund-flow suspension (price still current) to
    # reach the observed 3 suspended fund-flow outcomes.
    extra_flow_suspended = flow_suspended - price_suspended
    filler_iter = iter(fillers)
    for _ in range(extra_flow_suspended):
        ticker = next(filler_iter)
        outcomes[ticker] = TickerRefreshOutcome(
            ticker=ticker,
            price_status=PriceStatus.CURRENT,
            price_history_rows=100,
            fund_flow_status=FundFlowStatus.SUSPENDED,
            fund_flow_history_rows=0,
        )

    # Remaining fillers: fully current, plan-eligible depth.
    for ticker in filler_iter:
        outcomes[ticker] = TickerRefreshOutcome(
            ticker=ticker,
            price_status=PriceStatus.CURRENT,
            price_history_rows=100,
            fund_flow_status=FundFlowStatus.CURRENT,
            fund_flow_history_rows=25,
        )

    assert len(outcomes) == total
    return outcomes


def _shared_evidence() -> SharedReadinessEvidence:
    return SharedReadinessEvidence(
        regime_row={"trend": "up"},
        regime_fingerprint="sha256:regime",
        industry_mapping_fingerprint="sha256:industry",
        security_status_fingerprint="sha256:sec",
        board_rule_version="board-rule-v1",
        normalization_version="norm-v1",
        signal_session_policy_version=SIGNAL_SESSION_POLICY_VERSION,
    )


def _refresh_result(outcomes: dict[str, TickerRefreshOutcome]) -> DailyActionRefreshResult:
    universe = tuple(outcomes.keys())
    return DailyActionRefreshResult(
        trade_date=_SIGNAL_DATE,
        universe_tickers=universe,
        universe_fingerprint=universe_fingerprint(universe),
        daily_batch_fingerprint="sha256:batch",
        suspension_evidence=SuspensionEvidence.available(
            _SIGNAL_DATE, set(_load_fixture()["known_suspended"])
        ),
        outcomes=outcomes,
        stats=derive_stats_from_outcomes(outcomes),
    )


def test_20260713_universe_is_652_and_conserves_categories():
    """Full refresh universe is 652 with conserving price/fund-flow categories."""
    fixture = _load_fixture()
    outcomes = _expand_to_universe(fixture)
    refresh = _refresh_result(outcomes)

    assert len(refresh.universe_tickers) == 652
    assert refresh.stats.price_status_counts == {"current": 650, "suspended": 2}
    assert refresh.stats.fund_flow_status_counts == {
        "current": 642,
        "suspended": 3,
        "unsupported": 7,
    }
    # Conservation: every category sum equals the universe total.
    assert sum(refresh.stats.price_status_counts.values()) == 652
    assert sum(refresh.stats.fund_flow_status_counts.values()) == 652


def test_20260713_readiness_is_healthy_despite_suspensions_and_unsupported(tmp_path):
    """Two suspensions + seven unsupported must NOT degrade the whole batch."""
    fixture = _load_fixture()
    outcomes = _expand_to_universe(fixture)
    refresh = _refresh_result(outcomes)

    manifest = build_daily_action_readiness(
        refresh,
        _shared_evidence(),
        run_id="run-20260713-regression",
    )

    assert manifest.domain == "daily_action"
    assert manifest.status == "healthy"
    assert manifest.is_healthy is True
    assert len(manifest.universe_tickers) == 652

    # The two confirmed suspensions are expected states, not unexplained gaps.
    for ticker in fixture["known_suspended"]:
        tr = manifest.ticker_readiness[ticker]
        assert tr.evidence_status == "blocked"
        assert tr.capabilities["btst_breakout"].scannable is False
        assert tr.capabilities["btst_breakout"].plan_eligible is False

    # A fully-current filler remains plan-eligible → Auto's 300 is not a gate.
    healthy_ticker = next(
        t
        for t, o in outcomes.items()
        if o.fund_flow_status is FundFlowStatus.CURRENT
        and o.fund_flow_history_rows >= 20
    )
    assert manifest.ticker_readiness[healthy_ticker].capabilities[
        "btst_breakout"
    ].plan_eligible is True

    # Independent atomic publication of the readiness canonical.
    publication = publish_daily_action_readiness(manifest, tmp_path)
    assert publication.status == "healthy"
    assert publication.summary["universe"]["total"] == 652
    assert (tmp_path / "daily_action_readiness_20260713.json").exists()
