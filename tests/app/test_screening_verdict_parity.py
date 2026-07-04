"""C290: web screening front-door must attach verdict (CLI↔web parity).

Dogfood (AST silent-skip scan of app/backend → inspected _build_screening_response)
found the web screening endpoint (`POST /api/screening/auto` and the latest
result getter) returns recommendations WITHOUT attaching `build_front_door_verdict`.
The CLI `--top-picks` attaches a per-pick verdict (action=BUY/HOLD/AVOID +
invalidation_reason + signal_horizon + market_regime) at top_picks.py:228 —
the result of days of trust-calibration work (c282/c283, NS-18). The web
front door, a pre-production auth-gated surface where users act on real
recommendations, gets NONE of it: ScreeningResponse has no verdict field,
_screening_response doesn't import build_front_door_verdict.

This is a cross-layer parity gap (CLI has verdict, web doesn't) in the
NS-18 trust-calibration family — the same "gate correct but presentation
dishonest on one surface" pattern c283 closed on the ranker→verdict path.
Web users see picks with no BUY/AVOID verdict, no composite_verified/
invalidation disclosure, same picks CLI users see WITH that disclosure.

Fix: _build_screening_response attaches a `verdict` dict to each rec via
build_front_door_verdict (reading market_regime from payload market_state
regime_gate_level), matching CLI behavior. This is additive — existing
rec fields unchanged, verdict is a new per-rec key the frontend can render.
"""

from __future__ import annotations

from app.backend.routes.screening import _build_screening_response


def _make_payload(*, regime: str = "normal", n_recs: int = 3) -> dict:
    """Construct a minimal mock auto_screening payload with BUY-gate inputs."""
    recs = []
    for i in range(n_recs):
        recs.append(
            {
                "ticker": f"{600000 + i:06d}",
                "name": f"测试股票{i}",
                "score_b": 0.5 + i * 0.05,
                "decision": "bullish",
                # BUY-gate inputs (build_front_door_verdict reads these)
                "composite_score": 0.55 + i * 0.05,
                "composite_score_gated": 0.55 + i * 0.05,
                "composite_verified": True,
                "expected_returns": {"t5": 0.02, "t10": 0.025, "t30": 0.03},
                "win_rates": {"t5": 0.60, "t10": 0.62, "t30": 0.55},
                "bucket_sample_count": 100,
                "bucket_t30_mature_count": 80,
            }
        )
    return {
        "mode": "auto_screening",
        "date": "20260607",
        "market_state": {
            "state_type": "trend",
            "regime_gate_level": regime,
        },
        "layer_a_count": 500,
        "total_scored": 480,
        "high_pool_count": 60,
        "top_n": n_recs,
        "recommendations": recs,
    }


def test_build_screening_response_attaches_verdict_to_each_rec() -> None:
    """c290: each recommendation in the web response must carry a `verdict` dict.

    The CLI attaches build_front_door_verdict output per pick; the web must
    match (it's the same front door, just a different surface). Without it,
    web users act on picks with no BUY/AVOID verdict + no invalidation
    disclosure that CLI users now see.
    """
    payload = _make_payload(regime="normal", n_recs=3)
    resp = _build_screening_response(
        payload,
        trade_date="20260607",
        score_threshold=0.0,
        use_explain=False,
        strategies=None,
        execution_time_seconds=1.0,
    )
    assert len(resp.recommendations) == 3
    for rec in resp.recommendations:
        verdict = rec.get("verdict")
        assert verdict is not None, f"each rec must carry a verdict; got keys={list(rec.keys())}"
        # verdict must have the action + disclosure fields CLI has
        assert "action" in verdict, f"verdict must have action (BUY/HOLD/AVOID); got {verdict}"
        assert verdict["action"] in {"BUY", "HOLD", "AVOID"}, f"action must be a verdict value; got {verdict['action']!r}"
        assert "invalidation_reason" in verdict, "verdict must disclose invalidation reasons (c283)"
        assert "market_regime" in verdict, "verdict must carry market_regime"
        assert "signal_horizon" in verdict, "verdict must carry signal_horizon (C221)"


def test_verdict_uses_market_regime_from_payload_market_state() -> None:
    """c290: verdict's market_regime must come from payload market_state regime_gate_level.

    This is the same regime the CLI's _render_market_gate reads — the verdict
    gate (crisis → T+10-only) depends on it being wired correctly. A crisis
    regime must produce a verdict consistent with the gate (HOLD/AVOID, not BUY
    on T+5 alone).
    """
    payload = _make_payload(regime="crisis", n_recs=2)
    resp = _build_screening_response(
        payload,
        trade_date="20260607",
        score_threshold=0.0,
        use_explain=False,
        strategies=None,
        execution_time_seconds=1.0,
    )
    for rec in resp.recommendations:
        v = rec["verdict"]
        # crisis regime must be reflected in the verdict's market_regime
        assert "crisis" in v["market_regime"] or "risk_off" in v["market_regime"], f"crisis payload → verdict market_regime must reflect crisis; got {v['market_regime']!r}"


def test_verdict_absent_when_market_state_missing_does_not_crash() -> None:
    """c290: if market_state is missing (degraded pipeline), verdict must still
    attach (with market_regime='unknown') rather than crash the response build.

    build_front_door_verdict already handles regime='unknown' (c282 gap 1 →
    'regime 未识别' honest label). The web builder must not pre-empt that
    by crashing; it must pass market_regime='unknown' through.
    """
    payload = _make_payload(regime="normal", n_recs=1)
    del payload["market_state"]  # simulate degraded pipeline (no market_state)
    resp = _build_screening_response(
        payload,
        trade_date="20260607",
        score_threshold=0.0,
        use_explain=False,
        strategies=None,
        execution_time_seconds=1.0,
    )
    rec = resp.recommendations[0]
    v = rec["verdict"]
    assert v["market_regime"] == "unknown", f"missing market_state → verdict market_regime must be 'unknown' (not crash); got {v['market_regime']!r}"
    # and the invalidation_reason must flag regime 未识别 (c282 honest label)
    assert "regime 未识别" in v["invalidation_reason"], f"unknown regime must disclose 'regime 未识别' (c282); got {v['invalidation_reason']!r}"


def test_verdict_compute_exception_is_logged_not_swallowed(monkeypatch, caplog) -> None:
    """c314 (loop 46): if build_front_door_verdict raises, the defensive AVOID
    fallback must LOG the exception — not swallow it silently. This is the NS-17
    silent-except disease class: c290 added the try/except to make the verdict
    never crash the web response (correct), but the except block had NO logger
    call, so a verdict-computation failure produced an AVOID with no operator-
    visible trace of why. The comment said 'Log via meta below' but no log
    existed. An operator seeing a sudden cluster of AVOID 'verdict 计算失败'
    picks could not diagnose the root cause from logs.

    Same disease class F5 retired across the decision chain (c267-c281) and the
    web storage route (c292). The verdict path is money-acting (operator acts
    on BUY/AVOID), so a silent failure there is exactly the high-cost case.
    """
    import logging

    import app.backend.routes.screening as screening_mod

    def _boom(rec, market_regime=None):  # noqa: ARG001
        raise RuntimeError("simulated verdict compute failure")

    monkeypatch.setattr(screening_mod, "build_front_door_verdict", _boom)
    payload = _make_payload(regime="normal", n_recs=2)

    with caplog.at_level(logging.WARNING, logger="app.backend.routes.screening"):
        resp = _build_screening_response(
            payload,
            trade_date="20260607",
            score_threshold=0.0,
            use_explain=False,
            strategies=None,
            execution_time_seconds=1.0,
        )

    # defensive AVOID still attaches (response must not crash)
    for rec in resp.recommendations:
        assert rec["verdict"]["action"] == "AVOID"
        assert "verdict 计算失败" in rec["verdict"]["invalidation_reason"]
    # AND the failure is logged (not swallowed) — the NS-17 fix
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "verdict" in joined.lower(), f"verdict-compute exception must be logged for operator diagnosis; " f"got records: {caplog.records!r}"
    # the exception detail itself should reach the log (exc_info or message)
    assert any("simulated verdict compute failure" in (r.getMessage() + str(getattr(r, "exc_text", "") or "")) for r in caplog.records), "the underlying exception message must reach the log so the operator can diagnose"


# ---------------------------------------------------------------------------
# c329 (loop 84): /api/screening/custom-weights must attach verdict too —
# the c290 verdict-parity fix shipped only on /auto and /latest. The custom-
# weights endpoint renders through the SAME ScreeningResultsPanel frontend
# component, so an operator doing weight sensitivity analysis sees picks
# with NO BUY/AVOID badge, no invalidation_reason, no regime gate — exactly
# the trust-calibration disclosure the contract requires on the BUY surface.
# ---------------------------------------------------------------------------


def test_custom_weights_endpoint_attaches_verdict(monkeypatch) -> None:
    """c329: the custom-weights endpoint must attach build_front_door_verdict
    to each rec, mirroring /auto and /latest. The frontend renders custom-
    weights picks through the same panel, so a missing verdict silently
    drops the BUY/AVOID badge + invalidation disclosure."""
    from app.backend.routes import screening as screening_mod
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    # Mock the payload loader to return a controlled payload (isolates from
    # real data/reports/ — important so the test doesn't pass by accident
    # when a real report happens to exist at the requested date).
    payload = _make_payload(regime="normal", n_recs=2)
    monkeypatch.setattr(
        screening_mod,
        "_load_latest_auto_screening_payload",
        lambda trade_date=None: payload,
    )
    # Stub the reweight to pass-through (we're testing verdict attachment, not
    # the reweight math).
    monkeypatch.setattr(
        "src.screening.custom_weights.reweight_recommendations",
        lambda recs, weights: recs,
    )

    app = FastAPI()
    app.include_router(screening_mod.router)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/screening/custom-weights",
        json={
            "trade_date": "20260607",
            "trend": 0.4,
            "mean_reversion": 0.2,
            "fundamental": 0.2,
            "event_sentiment": 0.2,
            "top_n": 2,
        },
    )
    assert response.status_code == 200, f"expected 200, got {response.status_code}: {response.text}"
    body = response.json()
    assert len(body["recommendations"]) == 2
    for rec in body["recommendations"]:
        verdict = rec.get("verdict")
        assert verdict is not None, (
            f"custom-weights rec must carry a verdict (c329 parity with /auto); "
            f"got keys={list(rec.keys())}"
        )
        assert verdict["action"] in {"BUY", "HOLD", "AVOID"}, f"verdict action must be valid; got {verdict['action']!r}"
        assert "invalidation_reason" in verdict, "verdict must disclose invalidation (c283)"
        assert "market_regime" in verdict, "verdict must carry market_regime"
