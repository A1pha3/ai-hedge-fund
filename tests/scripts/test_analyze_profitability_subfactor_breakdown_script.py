from __future__ import annotations

from types import SimpleNamespace

import scripts.analyze_profitability_subfactor_breakdown as breakdown


class _FakeSignal:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def model_dump(self) -> dict:
        return dict(self._payload)


def test_analyze_trade_dates_counts_triple_fail_profitability_breakdowns(monkeypatch) -> None:
    candidate = SimpleNamespace(ticker="300001", industry_sw="electronics", market_cap=80.0)
    fused_item = SimpleNamespace(
        ticker="300001",
        score_b=0.15,
        strategy_signals={
            "fundamental": _FakeSignal(
                {
                    "direction": -1,
                    "sub_factors": {
                        "profitability": {
                            "completeness": 1.0,
                            "metrics": {
                                "return_on_equity": 0.10,
                                "net_margin": 0.15,
                                "operating_margin": 0.10,
                                "positive_count": 0,
                            },
                        }
                    },
                }
            )
        },
    )

    monkeypatch.setattr(breakdown, "build_candidate_pool", lambda *_args, **_kwargs: [candidate])
    monkeypatch.setattr(breakdown, "detect_market_state", lambda *_args, **_kwargs: {"market": "neutral"})
    monkeypatch.setattr(breakdown, "score_batch", lambda candidates, *_args, **_kwargs: candidates)
    monkeypatch.setattr(breakdown, "fuse_batch", lambda *_args, **_kwargs: [fused_item])

    analysis = breakdown.analyze_trade_dates(["20260323"])

    assert analysis["blocked_with_profitability_scored"] == 1
    assert analysis["fund_nonpositive_with_profitability_scored"] == 1
    assert analysis["positive_count_0_blocked"] == 1
    assert analysis["positive_count_0_fund_nonpositive"] == 1
    assert analysis["metric_fail_blocked"] == {
        "return_on_equity": 1,
        "net_margin": 1,
        "operating_margin": 1,
    }
    assert analysis["fail_combo_blocked"]["net_margin+operating_margin+return_on_equity"] == 1
    assert analysis["triple_fail_industry_blocked"] == {"electronics": 1}
    assert analysis["triple_fail_market_cap_bucket_blocked"] == {"lt_100b": 1}
    assert analysis["triple_fail_examples"][0]["ticker"] == "300001"


def test_analyze_trade_dates_skips_fast_agent_and_incomplete_profitability(monkeypatch) -> None:
    candidate = SimpleNamespace(ticker="300002", industry_sw=None, market_cap=120.0)
    fast_agent_item = SimpleNamespace(
        ticker="300002",
        score_b=0.5,
        strategy_signals={
            "fundamental": _FakeSignal(
                {
                    "direction": 1,
                    "sub_factors": {
                        "profitability": {
                            "completeness": 1.0,
                            "metrics": {"positive_count": 1},
                        }
                    },
                }
            )
        },
    )
    incomplete_item = SimpleNamespace(
        ticker="300002",
        score_b=0.2,
        strategy_signals={
            "fundamental": _FakeSignal(
                {
                    "direction": 1,
                    "sub_factors": {
                        "profitability": {
                            "completeness": 0.0,
                            "metrics": {"positive_count": 0},
                        }
                    },
                }
            )
        },
    )

    monkeypatch.setattr(breakdown, "build_candidate_pool", lambda *_args, **_kwargs: [candidate])
    monkeypatch.setattr(breakdown, "detect_market_state", lambda *_args, **_kwargs: {"market": "neutral"})
    monkeypatch.setattr(breakdown, "score_batch", lambda candidates, *_args, **_kwargs: candidates)
    monkeypatch.setattr(breakdown, "fuse_batch", lambda *_args, **_kwargs: [fast_agent_item, incomplete_item])

    analysis = breakdown.analyze_trade_dates(["20260324"])

    assert analysis["blocked_with_profitability_scored"] == 0
    assert analysis["metric_fail_blocked"] == {}
    assert analysis["triple_fail_examples"] == []
