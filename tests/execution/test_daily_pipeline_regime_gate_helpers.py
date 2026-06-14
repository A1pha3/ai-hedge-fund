"""Unit tests for src/execution/daily_pipeline_regime_gate_helpers.py

Covers env-var mode resolution (P1/P2), gate payload building (off/shadow),
downstream market-state payload assembly, P1 shadow attachment, and P2
enforcement branches (off / non-blocked / blocked gate).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.execution.daily_pipeline_regime_gate_helpers import (
    attach_btst_regime_gate_shadow,
    attach_downstream_target_market_state_payload,
    BTST_0422_P1_REGIME_GATE_MODE_ENV,
    BTST_0422_P2_REGIME_GATE_MODE_ENV,
    build_btst_regime_gate_payload,
    build_downstream_target_market_state_payload,
    enforce_btst_regime_gate_p2,
    get_or_classify_gate,
    resolve_btst_regime_gate_mode,
    resolve_btst_regime_gate_p2_mode,
)
from src.execution.models import ExecutionPlan
from src.screening.models import MarketState


def _market_state() -> MarketState:
    return MarketState(adjusted_weights={"trend": 0.5})


def _plan(**overrides: Any) -> ExecutionPlan:
    base: dict[str, Any] = dict(
        date="20260613",
        market_state=_market_state(),
        buy_orders=[],
        selection_targets={},
        risk_metrics={},
    )
    base.update(overrides)
    return ExecutionPlan(**base)


# ---------------------------------------------------------------------------
# resolve_btst_regime_gate_mode / resolve_btst_regime_gate_p2_mode
# ---------------------------------------------------------------------------


def test_resolve_p1_mode_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, raising=False)
    assert resolve_btst_regime_gate_mode() == "off"


def test_resolve_p1_mode_shadow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, "shadow")
    assert resolve_btst_regime_gate_mode() == "shadow"


def test_resolve_p1_mode_invalid_falls_back_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, "nonsense")
    assert resolve_btst_regime_gate_mode() == "off"


def test_resolve_p1_mode_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, "SHADOW")
    assert resolve_btst_regime_gate_mode() == "shadow"


def test_resolve_p1_mode_empty_string_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, "")
    assert resolve_btst_regime_gate_mode() == "off"


def test_resolve_p2_mode_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BTST_0422_P2_REGIME_GATE_MODE_ENV, raising=False)
    assert resolve_btst_regime_gate_p2_mode() == "off"


def test_resolve_p2_mode_enforce(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P2_REGIME_GATE_MODE_ENV, "enforce")
    assert resolve_btst_regime_gate_p2_mode() == "enforce"


def test_resolve_p2_mode_invalid_falls_back_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P2_REGIME_GATE_MODE_ENV, "shadow")
    assert resolve_btst_regime_gate_p2_mode() == "off"


# ---------------------------------------------------------------------------
# build_btst_regime_gate_payload
# ---------------------------------------------------------------------------


def test_build_gate_payload_off_mode_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, "off")
    assert build_btst_regime_gate_payload(_market_state()) == {}


def test_build_gate_payload_shadow_mode_with_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, "shadow")

    import src.screening.market_state_helpers as msh

    monkeypatch.setattr(
        msh,
        "classify_btst_regime_gate_from_market_state",
        lambda ms: {"gate": "halt", "reason": "crisis"},
    )
    payload = build_btst_regime_gate_payload(_market_state())
    assert payload["gate"] == "halt"
    assert payload["mode"] == "shadow"


def test_build_gate_payload_shadow_mode_empty_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, "shadow")

    import src.screening.market_state_helpers as msh

    monkeypatch.setattr(msh, "classify_btst_regime_gate_from_market_state", lambda ms: None)
    assert build_btst_regime_gate_payload(_market_state()) == {}


# ---------------------------------------------------------------------------
# build_downstream_target_market_state_payload
# ---------------------------------------------------------------------------


def test_build_downstream_payload_none_market_state() -> None:
    assert build_downstream_target_market_state_payload(None) == {}


def test_build_downstream_payload_from_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, "off")
    payload = build_downstream_target_market_state_payload(_market_state())
    assert "adjusted_weights" in payload
    assert "btst_regime_gate" not in payload  # off mode → no gate


def test_build_downstream_payload_from_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, "off")
    payload = build_downstream_target_market_state_payload({"state_type": "crisis"})
    assert payload["state_type"] == "crisis"


def test_build_downstream_payload_includes_gate_in_shadow_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, "shadow")
    import src.screening.market_state_helpers as msh

    monkeypatch.setattr(
        msh, "classify_btst_regime_gate_from_market_state", lambda ms: {"gate": "halt"}
    )
    payload = build_downstream_target_market_state_payload(_market_state())
    assert payload["btst_regime_gate"]["gate"] == "halt"


def test_build_downstream_payload_non_model_non_dict_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, "off")
    assert build_downstream_target_market_state_payload("not_a_model") == {}  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# attach_downstream_target_market_state_payload
# ---------------------------------------------------------------------------


def test_attach_downstream_no_payload_returns_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, "off")

    class _Item:
        market_state: dict = {"existing": True}

        def model_copy(self, *, update):
            obj = _Item()
            obj.market_state = update.get("market_state", self.market_state)
            return obj

    result = attach_downstream_target_market_state_payload([_Item()], market_state=None)
    assert len(result) == 1
    assert result[0].market_state == {"existing": True}


# ---------------------------------------------------------------------------
# attach_btst_regime_gate_shadow
# ---------------------------------------------------------------------------


def test_attach_shadow_off_mode_no_change(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, "off")
    plan = _plan()
    result = attach_btst_regime_gate_shadow(plan)
    assert "btst_regime_gate" not in (result.risk_metrics or {})


def test_attach_shadow_shadow_mode_adds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, "shadow")
    import src.screening.market_state_helpers as msh

    monkeypatch.setattr(msh, "classify_btst_regime_gate_from_market_state", lambda ms: {"gate": "halt"})
    plan = _plan()
    result = attach_btst_regime_gate_shadow(plan)
    assert result.risk_metrics["btst_regime_gate"]["gate"] == "halt"
    assert result.risk_metrics["funnel_diagnostics"]["btst_regime_gate"]["gate"] == "halt"


def test_attach_shadow_does_not_mutate_original(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, "shadow")
    import src.screening.market_state_helpers as msh

    monkeypatch.setattr(msh, "classify_btst_regime_gate_from_market_state", lambda ms: {"gate": "halt"})
    plan = _plan()
    original_metrics = dict(plan.risk_metrics or {})
    attach_btst_regime_gate_shadow(plan)
    assert plan.risk_metrics == original_metrics  # deep-copied, not mutated


# ---------------------------------------------------------------------------
# get_or_classify_gate
# ---------------------------------------------------------------------------


def test_get_gate_reuses_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(risk_metrics={"btst_regime_gate": {"gate": "shadow_only"}})
    assert get_or_classify_gate(plan) == "shadow_only"


def test_get_gate_classifies_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.screening.market_state_helpers as msh

    monkeypatch.setattr(msh, "classify_btst_regime_gate_from_market_state", lambda ms: {"gate": "halt"})
    plan = _plan(risk_metrics={})
    assert get_or_classify_gate(plan) == "halt"


def test_get_gate_returns_none_when_classification_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.screening.market_state_helpers as msh

    monkeypatch.setattr(msh, "classify_btst_regime_gate_from_market_state", lambda ms: None)
    plan = _plan(risk_metrics={})
    assert get_or_classify_gate(plan) is None


# ---------------------------------------------------------------------------
# enforce_btst_regime_gate_p2
# ---------------------------------------------------------------------------


def test_enforce_p2_off_mode_no_change(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P2_REGIME_GATE_MODE_ENV, "off")
    plan = _plan()
    result = enforce_btst_regime_gate_p2(plan)
    assert result is plan  # returned as-is (no copy when off)


def test_enforce_p2_gate_none_no_change(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P2_REGIME_GATE_MODE_ENV, "enforce")
    import src.screening.market_state_helpers as msh

    monkeypatch.setattr(msh, "classify_btst_regime_gate_from_market_state", lambda ms: None)
    plan = _plan()
    result = enforce_btst_regime_gate_p2(plan)
    # gate None → returns early (deep copy made but no enforcement payload)
    assert "btst_regime_gate_enforcement" not in (result.risk_metrics or {})


def test_enforce_p2_non_blocked_gate_enforced_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P2_REGIME_GATE_MODE_ENV, "enforce")
    plan = _plan(risk_metrics={"btst_regime_gate": {"gate": "pass"}})
    result = enforce_btst_regime_gate_p2(plan)
    enforcement = result.risk_metrics["btst_regime_gate_enforcement"]
    assert enforcement["enforced"] is False
    assert enforcement["gate"] == "pass"
    assert enforcement["buy_orders_cleared"] is False
    assert enforcement["shadow_promotion_count"] == 0


def test_enforce_p2_blocked_gate_clears_buy_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P2_REGIME_GATE_MODE_ENV, "enforce")
    from src.portfolio.models import PositionPlan

    plan = _plan(
        risk_metrics={"btst_regime_gate": {"gate": "halt"}},
        buy_orders=[
            PositionPlan(ticker="000001", action="buy"),
            PositionPlan(ticker="000002", action="buy"),
        ],
        selection_targets={},
    )
    result = enforce_btst_regime_gate_p2(plan)
    enforcement = result.risk_metrics["btst_regime_gate_enforcement"]
    assert enforcement["enforced"] is True
    assert enforcement["gate"] == "halt"
    assert enforcement["buy_orders_cleared"] is True
    assert enforcement["buy_orders_cleared_count"] == 2
    assert len(result.buy_orders) == 0  # all cleared (no shadow promotions)
    # counts updated
    assert result.risk_metrics["counts"]["buy_order_count"] == 0


def test_enforce_p2_blocked_gate_preserves_shadow_promoted_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BTST_0422_P2_REGIME_GATE_MODE_ENV, "enforce")

    # Mock shadow promotion: 000001 is eligible, 000002 is not.
    # Patch in the CALLING module (top-level import binding), not the source module.
    def _promo(*, evaluation, short_trade_result=None, gate=None):
        return {"eligible": evaluation.ticker == "000001"}

    monkeypatch.setattr(
        "src.execution.daily_pipeline_regime_gate_helpers.resolve_btst_shadow_promotion_payload", _promo
    )
    from src.portfolio.models import PositionPlan
    from src.targets.models import DualTargetEvaluation

    plan = _plan(
        risk_metrics={"btst_regime_gate": {"gate": "halt"}},
        buy_orders=[
            PositionPlan(ticker="000001", action="buy"),
            PositionPlan(ticker="000002", action="buy"),
        ],
        selection_targets={
            "000001": DualTargetEvaluation(ticker="000001", trade_date="20260613"),
            "000002": DualTargetEvaluation(ticker="000002", trade_date="20260613"),
        },
    )
    result = enforce_btst_regime_gate_p2(plan)
    enforcement = result.risk_metrics["btst_regime_gate_enforcement"]
    assert enforcement["shadow_promotion_count"] == 1
    assert enforcement["shadow_promotion_tickers"] == ["000001"]
    assert [o.ticker for o in result.buy_orders] == ["000001"]
