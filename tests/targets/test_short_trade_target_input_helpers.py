from __future__ import annotations

from src.targets.short_trade_target_input_helpers import build_target_input_from_entry


def _normalize_reason_codes(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def test_build_target_input_from_entry_preserves_market_state_payload() -> None:
    market_state = {
        "breadth_ratio": 0.41,
        "position_scale": 0.67,
    }
    result = build_target_input_from_entry(
        trade_date="20260410",
        entry={
            "ticker": "000001",
            "market_state": market_state,
            "score_final": 0.58,
            "quality_score": 0.62,
            "strategy_signals": {"momentum": {"signal": "bullish", "confidence": 0.7}},
        },
        normalized_reason_codes_fn=_normalize_reason_codes,
    )

    assert result.market_state == market_state
