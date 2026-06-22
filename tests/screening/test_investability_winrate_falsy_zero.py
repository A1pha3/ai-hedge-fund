"""TDD red test: build_front_door_verdict must flag actual 0% T+30 win rate
(R68/R96 falsy-zero family — ``if t30_win_rate and t30_win_rate < 0.5``
short-circuits on falsy 0.0, so a stock with an ACTUAL 0% win rate — the
worst possible — does NOT get the "同分组胜率跌破 50%" invalidation flag).

Line 218 of investability.py uses ``if t30_win_rate and t30_win_rate < 0.5``.
``t30_win_rate`` comes from ``_safe_metric(win_rates.get("t30"), 0.0)`` which
returns 0.0 for BOTH (a) missing data (key absent / None) AND (b) an actual
0.0 win rate. The ``and`` guard was intended to skip missing data, but
because ``0.0`` is falsy, it ALSO skips the lowest real win rate (0%) — the
case that most clearly should trigger the flag.

Verified empirically before fix:
- 0.0 win rate (actual) → flag MISSED (0.0 and ... short-circuits)
- 0.4 win rate → flag present (control)
- missing win_rates → flag absent (correct, no data)

Fix: distinguish "actual 0.0 win rate" from "missing data" with an explicit
presence check (R68/R96 canonical — ``is_finite_number`` on the raw value
before _safe_metric). 0.0 is a valid (if extreme) win rate and must trigger
the flag; None/NaN (missing/corrupt) must not.
"""
from __future__ import annotations

from src.screening.investability import build_front_door_verdict


def _base_avoid_rec(win_rate_t30) -> dict:
    """An AVOID-grade recommendation (composite below BUY/HOLD bars) with a
    configurable T+30 win rate. AVOID is the only verdict reachable with a
    0.0 win rate (BUY requires >=0.55, HOLD requires >=0.5)."""
    return {
        "decision": "neutral",
        "composite_score": 0.20,  # below 0.25 watchable bar → AVOID
        "score_b": 0.20,
        "expected_returns": {"t30": 0.01},
        "win_rates": {"t30": win_rate_t30},
        "bucket_sample_count": 30,
        "bucket_t30_mature_count": 25,
    }


def _has_win_rate_flag(verdict: dict) -> bool:
    reasons = verdict.get("invalidation_reason", "")
    return "胜率" in reasons and "50" in reasons


def test_actual_zero_win_rate_flags_below_50() -> None:
    """A stock with an ACTUAL 0.0 (0%) T+30 win rate — the worst possible —
    must trigger the '同分组胜率跌破 50%' invalidation flag. Currently the
    ``if t30_win_rate and ...`` guard short-circuits on falsy 0.0 and misses it."""
    v = build_front_door_verdict(_base_avoid_rec(0.0), market_regime="normal")
    assert v["action"] == "AVOID"
    assert _has_win_rate_flag(v), (
        "actual 0.0 (0%) T+30 win rate must trigger '胜率跌破 50%' flag — "
        "currently `if t30_win_rate and t30_win_rate < 0.5` short-circuits "
        "on falsy 0.0 (R68/R96 falsy-zero family)"
    )


def test_low_nonzero_win_rate_flags_below_50() -> None:
    """A 0.4 win rate (control) correctly triggers the flag (behavior-preserving)."""
    v = build_front_door_verdict(_base_avoid_rec(0.40), market_regime="normal")
    assert _has_win_rate_flag(v)


def test_missing_win_rate_data_does_not_flag() -> None:
    """Missing win-rate data (key absent) must NOT trigger the flag — we don't
    know the win rate, so flagging 'below 50%' would be misleading. The fix
    must distinguish missing data from actual 0.0."""
    rec = _base_avoid_rec(0.0)
    rec["win_rates"] = {}  # missing — no t30 key
    v = build_front_door_verdict(rec, market_regime="normal")
    assert not _has_win_rate_flag(v), (
        "missing win-rate data must not trigger the flag (no data to evaluate)"
    )


def test_high_win_rate_does_not_flag() -> None:
    """A 0.6 win rate (>=0.5) must not trigger the flag (behavior-preserving)."""
    v = build_front_door_verdict(_base_avoid_rec(0.60), market_regime="normal")
    assert not _has_win_rate_flag(v)
